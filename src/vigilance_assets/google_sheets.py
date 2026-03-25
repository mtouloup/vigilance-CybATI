from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from http import HTTPStatus
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import GoogleSheetsSettings
from .schema import load_schema_catalog
from .spreadsheet import RowData, SheetRecord, SpreadsheetBackendError, SpreadsheetTableGateway

LOGGER = logging.getLogger(__name__)
SHEETS_API_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def _extract_google_api_error_details(exc: HttpError) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = getattr(exc, "reason", None)
    details: list[str] = []
    if status is not None:
        try:
            phrase = HTTPStatus(status).phrase
            details.append(f"HTTP {status} {phrase}")
        except ValueError:
            details.append(f"HTTP {status}")
    if reason:
        details.append(str(reason))

    content = getattr(exc, "content", None)
    if content:
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if message:
                    details.append(str(message))
                status_text = error.get("status")
                if status_text:
                    details.append(f"status={status_text}")
    if not details:
        return str(exc) or exc.__class__.__name__
    return "; ".join(dict.fromkeys(details))


def _google_api_setup_guidance(exc: HttpError) -> list[str]:
    status = getattr(getattr(exc, "resp", None), "status", None)
    details = _extract_google_api_error_details(exc).casefold()
    guidance: list[str] = []
    if status in {403, 429, 503} or "service disabled" in details or "api has not been used" in details or "google sheets api" in details and "enable" in details:
        guidance.append(
            "If the Google Sheets API is disabled for the Google Cloud project that owns the service account, enable the Google Sheets API for that project and retry."
        )
    if status in {401, 403, 404} or "not found" in details or "permission" in details or "caller does not have permission" in details:
        guidance.append(
            "Confirm that the target spreadsheet is shared with the service account email and that VIGILANCE_GOOGLE_SPREADSHEET_ID points to the correct spreadsheet."
        )
    if status in {500, 502, 503, 504}:
        guidance.append(
            "The Google Sheets API may be temporarily unavailable; verify Google API availability and retry once connectivity is restored."
        )
    return guidance


def _format_google_api_error(context: str, exc: HttpError) -> str:
    details = _extract_google_api_error_details(exc)
    guidance = _google_api_setup_guidance(exc)
    message = f"{context} Underlying Google API error: {details}."
    if guidance:
        message = f"{message} {' '.join(guidance)}"
    return message



class GoogleSheetsConfigurationError(SpreadsheetBackendError):
    """Raised when Google Sheets configuration is invalid."""


class GoogleSheetsConnectivityError(SpreadsheetBackendError):
    """Raised when the Google Sheets backend cannot be reached."""


class GoogleSheetsWorksheetError(SpreadsheetBackendError):
    """Raised when a required worksheet or header row is invalid."""


class GoogleSheetsReadOnlyError(SpreadsheetBackendError):
    """Raised when a mutation is requested against a read-only sheet."""


@dataclass(frozen=True, slots=True)
class WorksheetSnapshot:
    sheet_name: str
    sheet_id: int | None
    headers: tuple[str, ...]
    header_row_number: int
    canonical_indexes: tuple[int, ...]
    canonical_header_by_column: tuple[str | None, ...]
    canonical_index_by_header: Mapping[str, int]
    asset_id_column_index: int
    write_start_column_index: int
    write_end_column_index: int
    worksheet_column_count: int
    rows: tuple[SheetRecord, ...]


@dataclass(frozen=True, slots=True)
class HeaderSelection:
    header_row_index: int
    headers: tuple[str, ...]
    canonical_headers: tuple[str, ...]
    canonical_indexes: tuple[int, ...]
    matched_count: int


@dataclass(slots=True)
class GoogleSheetsTableGateway(SpreadsheetTableGateway):
    """Google Sheets adapter for the canonical ASSETS worksheet.

    Authenticated mode uses the Google Sheets API with a service account and
    supports read/write CRUD operations. Public mode is kept only as an
    explicitly configured read-only fallback using the CSV export endpoint.
    """

    settings: GoogleSheetsSettings
    expected_headers: Sequence[str] = ()
    timeout_seconds: float = 20.0
    header_scan_limit: int = 10
    api_service: Any | None = None

    def __post_init__(self) -> None:
        self._expected_headers = tuple(self.expected_headers)
        self._expected_header_set = set(self._expected_headers)
        self._normalized_expected_headers = {
            self._normalize_header_key(header): header for header in self._expected_headers
        }
        catalog = load_schema_catalog()
        self._expected_asset_categories = set(catalog.category_fields)
        self._common_headers = {field.sheet_header for field in catalog.common_fields}
        self._category_headers_by_category = {
            category: {field.sheet_header for field in fields}
            for category, fields in catalog.category_fields.items()
        }
        self._all_category_headers = set().union(*self._category_headers_by_category.values())
        self._api_service = self.api_service

    @property
    def worksheet_name(self) -> str:
        return self.settings.worksheet_name

    @property
    def is_read_only(self) -> bool:
        return self.settings.read_only_public_fallback

    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        snapshot = self._load_snapshot(sheet_name)
        return [SheetRecord(row_number=row.row_number, values=dict(row.values)) for row in snapshot.rows]

    def append_row(self, sheet_name: str, values: RowData) -> SheetRecord:
        if self.is_read_only:
            raise GoogleSheetsReadOnlyError(self._read_only_message(sheet_name))
        snapshot = self._load_snapshot(sheet_name)
        start_column_index = snapshot.write_start_column_index
        end_column_index = snapshot.write_end_column_index
        append_range = self._append_range(snapshot, start_column_index, end_column_index)
        ordered_values = self._row_to_aligned_worksheet_values(
            values,
            snapshot,
            start_column_index=start_column_index,
            end_column_index=end_column_index,
        )
        body = {"values": [ordered_values]}
        LOGGER.debug(
            "Google Sheets append column mapping worksheet=%s columns=%s",
            snapshot.sheet_name,
            self._column_mapping_diagnostics(snapshot),
        )
        LOGGER.info(
            "Appending asset row to Google Sheet spreadsheet=%s worksheet=%s range=%s start_column=%s(%s) payload_width=%s values=%s populated_fields=%s",
            self.settings.spreadsheet_id,
            snapshot.sheet_name,
            append_range,
            self._column_index_to_a1(start_column_index),
            start_column_index + 1,
            len(ordered_values),
            ordered_values,
            self._populated_field_column_diagnostics(values, snapshot),
        )
        try:
            response = self._spreadsheets_values().append(
                spreadsheetId=self.settings.spreadsheet_id,
                range=append_range,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                includeValuesInResponse=True,
                body=body,
            ).execute()
        except HttpError as exc:
            message = _format_google_api_error(
                "Failed to append a row through the Google Sheets API.",
                exc,
            )
            LOGGER.exception(message)
            raise GoogleSheetsConnectivityError(message) from exc
        LOGGER.info(
            "Google Sheets append response spreadsheet=%s worksheet=%s range=%s updates=%s",
            self.settings.spreadsheet_id,
            snapshot.sheet_name,
            append_range,
            response,
        )
        appended_row_number = self._extract_appended_row_number(response)
        self._validate_append_response(response, snapshot.sheet_name)
        return self._find_appended_row(snapshot.sheet_name, values.get("Asset_ID"), appended_row_number=appended_row_number)

    def update_row(self, sheet_name: str, row_number: int, values: RowData) -> SheetRecord:
        if self.is_read_only:
            raise GoogleSheetsReadOnlyError(self._read_only_message(sheet_name))
        snapshot = self._load_snapshot(sheet_name)
        start_column_index = snapshot.write_start_column_index
        end_column_index = snapshot.write_end_column_index
        row_range = (
            f"{self._worksheet_range(snapshot.sheet_name)}!"
            f"{self._column_index_to_a1(start_column_index)}{row_number}:{self._column_index_to_a1(end_column_index)}{row_number}"
        )
        ordered_values = self._row_to_aligned_worksheet_values(
            values,
            snapshot,
            start_column_index=start_column_index,
            end_column_index=end_column_index,
        )
        try:
            self._spreadsheets_values().update(
                spreadsheetId=self.settings.spreadsheet_id,
                range=row_range,
                valueInputOption="USER_ENTERED",
                body={"values": [ordered_values]},
            ).execute()
        except HttpError as exc:
            message = _format_google_api_error(
                f"Failed to update row {row_number} through the Google Sheets API.",
                exc,
            )
            LOGGER.exception(message)
            raise GoogleSheetsConnectivityError(message) from exc
        return SheetRecord(row_number=row_number, values=dict(values))

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        if self.is_read_only:
            raise GoogleSheetsReadOnlyError(self._read_only_message(sheet_name))
        snapshot = self._load_snapshot(sheet_name)
        if snapshot.sheet_id is None:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {snapshot.sheet_name!r} is missing a Google Sheets sheetId required for row deletion."
            )
        try:
            self._spreadsheets().batchUpdate(
                spreadsheetId=self.settings.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": snapshot.sheet_id,
                                    "dimension": "ROWS",
                                    "startIndex": row_number - 1,
                                    "endIndex": row_number,
                                }
                            }
                        }
                    ]
                },
            ).execute()
        except HttpError as exc:
            message = _format_google_api_error(
                f"Failed to delete row {row_number} through the Google Sheets API.",
                exc,
            )
            LOGGER.exception(message)
            raise GoogleSheetsConnectivityError(message) from exc

    def validate_connection(self) -> WorksheetSnapshot:
        snapshot = self._load_snapshot(self.worksheet_name)
        LOGGER.info(
            "Configured Google Sheets backend for spreadsheet %s worksheet %s in %s mode.",
            self.settings.spreadsheet_id,
            snapshot.sheet_name,
            self.settings.runtime_mode_label,
        )
        return snapshot

    def _load_snapshot(self, sheet_name: str) -> WorksheetSnapshot:
        resolved_sheet_name = self._resolve_sheet_name(sheet_name)
        if self.is_read_only:
            raw_rows = self._fetch_public_rows(resolved_sheet_name)
            return self._build_snapshot(sheet_name=resolved_sheet_name, sheet_id=None, raw_rows=raw_rows)

        metadata = self._fetch_authenticated_sheet_metadata(resolved_sheet_name)
        raw_rows = self._fetch_authenticated_rows(resolved_sheet_name)
        return self._build_snapshot(
            sheet_name=resolved_sheet_name,
            sheet_id=metadata["properties"]["sheetId"],
            raw_rows=raw_rows,
        )

    def _fetch_authenticated_sheet_metadata(self, sheet_name: str) -> dict[str, Any]:
        try:
            response = self._spreadsheets().get(
                spreadsheetId=self.settings.spreadsheet_id,
                fields="sheets(properties(sheetId,title))",
            ).execute()
        except HttpError as exc:
            message = _format_google_api_error(
                "Failed to load spreadsheet metadata from the Google Sheets API.",
                exc,
            )
            LOGGER.exception(message)
            raise GoogleSheetsConnectivityError(message) from exc
        for sheet in response.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == sheet_name:
                return sheet
        raise GoogleSheetsWorksheetError(
            f"Worksheet {sheet_name!r} was not found in the target spreadsheet."
        )

    def _fetch_authenticated_rows(self, sheet_name: str) -> list[list[Any]]:
        try:
            response = self._spreadsheets_values().get(
                spreadsheetId=self.settings.spreadsheet_id,
                range=self._worksheet_range(sheet_name),
                majorDimension="ROWS",
            ).execute()
        except HttpError as exc:
            message = _format_google_api_error(
                f"Failed to read worksheet {sheet_name!r} through the Google Sheets API.",
                exc,
            )
            LOGGER.exception(message)
            raise GoogleSheetsConnectivityError(message) from exc
        rows = [list(row) for row in response.get("values", [])]
        if not rows:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} returned no data from the Google Sheets API."
            )
        return rows

    def _fetch_public_rows(self, sheet_name: str) -> list[list[str]]:
        url = self._public_csv_url(sheet_name)
        request = Request(url, headers={"User-Agent": "vigilance-assets/0.1"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8-sig")
        except HTTPError as exc:
            if exc.code == 404:
                raise GoogleSheetsWorksheetError(
                    f"Worksheet {sheet_name!r} could not be read from the public spreadsheet export endpoint. "
                    "Confirm that the spreadsheet is publicly accessible and the worksheet name is correct."
                ) from exc
            raise GoogleSheetsConnectivityError(
                f"Failed to fetch the public Google Sheet export for worksheet {sheet_name!r} (HTTP {exc.code})."
            ) from exc
        except URLError as exc:
            raise GoogleSheetsConnectivityError(
                f"Failed to reach the public Google Sheet export for worksheet {sheet_name!r}."
            ) from exc

        rows = [list(row) for row in csv.reader(io.StringIO(payload))]
        if not rows:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} returned no data from the public spreadsheet export endpoint."
            )
        return rows

    def _build_snapshot(self, *, sheet_name: str, sheet_id: int | None, raw_rows: Sequence[Sequence[Any]]) -> WorksheetSnapshot:
        if not raw_rows:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} is empty; the worksheet must contain the canonical ASSETS headers."
            )
        selection = self._select_header_row(sheet_name, raw_rows)
        canonical_index_by_header = {
            canonical_header: column_index
            for canonical_header, column_index in zip(selection.canonical_headers, selection.canonical_indexes)
        }
        asset_id_column_index = canonical_index_by_header.get("Asset_ID")
        if asset_id_column_index is None:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} header row {selection.header_row_index + 1} is missing required canonical header Asset_ID."
            )
        write_end_column_index = max(selection.canonical_indexes)
        records: list[SheetRecord] = []
        scanned_rows = 0
        blank_rows = 0
        skipped_rows = 0
        for row_number, row in enumerate(raw_rows[selection.header_row_index + 1 :], start=selection.header_row_index + 2):
            scanned_rows += 1
            values = {
                canonical_header: self._normalize_inbound_value(row[column_index] if column_index < len(row) else None)
                for canonical_header, column_index in zip(selection.canonical_headers, selection.canonical_indexes)
            }
            if not any(value not in (None, "") for value in values.values()):
                blank_rows += 1
                continue
            if not self._looks_like_asset_row(values):
                skipped_rows += 1
                continue
            records.append(SheetRecord(row_number=row_number, values=values))
        LOGGER.debug(
            "Loaded Google Sheets snapshot for worksheet=%s header_row=%s asset_id_column=%s(%s) write_start_column=%s(%s) write_end_column=%s(%s) scanned=%s blank=%s skipped=%s parsed=%s",
            sheet_name,
            selection.header_row_index + 1,
            self._column_index_to_a1(asset_id_column_index),
            asset_id_column_index + 1,
            self._column_index_to_a1(asset_id_column_index),
            asset_id_column_index + 1,
            self._column_index_to_a1(write_end_column_index),
            write_end_column_index + 1,
            scanned_rows,
            blank_rows,
            skipped_rows,
            len(records),
        )
        return WorksheetSnapshot(
            sheet_name=sheet_name,
            sheet_id=sheet_id,
            headers=selection.canonical_headers,
            header_row_number=selection.header_row_index + 1,
            canonical_indexes=selection.canonical_indexes,
            canonical_header_by_column=self._build_canonical_header_by_column(selection),
            canonical_index_by_header=canonical_index_by_header,
            asset_id_column_index=asset_id_column_index,
            write_start_column_index=asset_id_column_index,
            write_end_column_index=write_end_column_index,
            worksheet_column_count=len(selection.headers),
            rows=tuple(records),
        )


    def _looks_like_asset_row(self, values: Mapping[str, Any]) -> bool:
        asset_id = values.get("Asset_ID")
        asset_category = values.get("Asset_Category")
        if not isinstance(asset_id, str) or not asset_id.strip():
            return False
        if not isinstance(asset_category, str) or not asset_category.strip():
            return False
        if asset_category not in self._expected_asset_categories:
            return False
        return True

    def _select_header_row(self, sheet_name: str, raw_rows: Sequence[Sequence[Any]]) -> HeaderSelection:
        best_selection: HeaderSelection | None = None
        scan_limit = min(len(raw_rows), self.header_scan_limit)
        for row_index in range(scan_limit):
            selection = self._evaluate_header_row(row_index, raw_rows[row_index])
            if selection is None:
                continue
            if best_selection is None or selection.matched_count > best_selection.matched_count:
                best_selection = selection
        if best_selection is None:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} does not contain a recognizable canonical ASSETS header row within the first {scan_limit} rows."
            )
        self._validate_detected_headers(sheet_name, best_selection)
        return best_selection

    def _evaluate_header_row(self, row_index: int, row: Sequence[Any]) -> HeaderSelection | None:
        canonical_headers: list[str] = []
        canonical_indexes: list[int] = []
        seen_headers: set[str] = set()
        for column_index, value in enumerate(row):
            normalized_key = self._normalize_header_key(value)
            if not normalized_key:
                continue
            canonical_header = self._normalized_expected_headers.get(normalized_key)
            if canonical_header is None or canonical_header in seen_headers:
                continue
            seen_headers.add(canonical_header)
            canonical_headers.append(canonical_header)
            canonical_indexes.append(column_index)
        if not canonical_headers:
            return None
        return HeaderSelection(
            header_row_index=row_index,
            headers=tuple(self._normalize_header(value) for value in row),
            canonical_headers=tuple(canonical_headers),
            canonical_indexes=tuple(canonical_indexes),
            matched_count=len(canonical_headers),
        )

    def _validate_detected_headers(self, sheet_name: str, selection: HeaderSelection) -> None:
        duplicates = sorted({header for header in selection.canonical_headers if selection.canonical_headers.count(header) > 1})
        if duplicates:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} header row {selection.header_row_index + 1} contains duplicate canonical headers: {', '.join(duplicates)}."
            )
        missing = sorted(self._expected_header_set.difference(selection.canonical_headers))
        if missing:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} header row {selection.header_row_index + 1} is missing canonical headers: {', '.join(missing)}."
            )

    def _resolve_sheet_name(self, requested_sheet_name: str) -> str:
        if requested_sheet_name in {"ASSETS", self.settings.worksheet_name}:
            return self.settings.worksheet_name
        raise GoogleSheetsWorksheetError(
            f"Only the canonical ASSETS worksheet is supported; received {requested_sheet_name!r}."
        )

    def _row_to_ordered_values(self, values: RowData, headers: Sequence[str]) -> list[Any]:
        return [self._serialize_outbound_value(values.get(header)) for header in headers]

    def _row_to_worksheet_values(self, values: RowData, snapshot: WorksheetSnapshot) -> list[Any]:
        worksheet_values = [""] * snapshot.worksheet_column_count
        raw_category = values.get("Asset_Category")
        category = raw_category.strip() if isinstance(raw_category, str) else None
        allowed_category_headers = self._category_headers_by_category.get(category, set())
        for column_index, canonical_header in enumerate(snapshot.canonical_header_by_column):
            if canonical_header is None:
                continue
            if canonical_header in self._all_category_headers and canonical_header not in allowed_category_headers:
                worksheet_values[column_index] = ""
                continue
            worksheet_values[column_index] = self._serialize_outbound_value(values.get(canonical_header))
        return worksheet_values

    def _row_to_aligned_worksheet_values(
        self,
        values: RowData,
        snapshot: WorksheetSnapshot,
        *,
        start_column_index: int,
        end_column_index: int,
    ) -> list[Any]:
        worksheet_values = self._row_to_worksheet_values(values, snapshot)
        return worksheet_values[start_column_index : end_column_index + 1]

    def _build_canonical_header_by_column(self, selection: HeaderSelection) -> tuple[str | None, ...]:
        header_by_normalized_key = {
            self._normalize_header_key(header): header for header in selection.canonical_headers
        }
        aligned_headers: list[str | None] = []
        for header in selection.headers:
            normalized_key = self._normalize_header_key(header)
            aligned_headers.append(header_by_normalized_key.get(normalized_key))
        return tuple(aligned_headers)

    def _find_appended_row(self, sheet_name: str, asset_id: Any, *, appended_row_number: int | None = None) -> SheetRecord:
        snapshot = self._load_snapshot(sheet_name)
        if appended_row_number is not None:
            for record in snapshot.rows:
                if record.row_number == appended_row_number:
                    if asset_id is None or record.values.get("Asset_ID") == asset_id:
                        return record
        if asset_id is None:
            if not snapshot.rows:
                raise GoogleSheetsWorksheetError("The appended row could not be confirmed after the write completed.")
            return snapshot.rows[-1]
        for record in reversed(snapshot.rows):
            if record.values.get("Asset_ID") == asset_id:
                return record
        raise GoogleSheetsWorksheetError(
            f"The appended row for Asset_ID {asset_id!r} could not be located after the write completed."
        )

    def _worksheet_range(self, sheet_name: str) -> str:
        return f"'{sheet_name}'"

    def _append_range(self, snapshot: WorksheetSnapshot, start_column_index: int, end_column_index: int) -> str:
        start_column = self._column_index_to_a1(start_column_index)
        end_column = self._column_index_to_a1(end_column_index)
        return f"{self._worksheet_range(snapshot.sheet_name)}!{start_column}{snapshot.header_row_number}:{end_column}"

    def _column_mapping_diagnostics(self, snapshot: WorksheetSnapshot) -> dict[str, str]:
        diagnostics: dict[str, str] = {}
        for column_index, canonical_header in enumerate(snapshot.canonical_header_by_column):
            if canonical_header is None:
                continue
            diagnostics[canonical_header] = f"{self._column_index_to_a1(column_index)}({column_index + 1})"
        return diagnostics

    def _populated_field_column_diagnostics(self, values: RowData, snapshot: WorksheetSnapshot) -> dict[str, str]:
        diagnostics: dict[str, str] = {}
        for canonical_header, column_index in snapshot.canonical_index_by_header.items():
            value = values.get(canonical_header)
            if value in (None, ""):
                continue
            diagnostics[canonical_header] = (
                f"{self._column_index_to_a1(column_index)}({column_index + 1})"
            )
        return diagnostics

    @staticmethod
    def _column_index_to_a1(column_index: int) -> str:
        if column_index < 0:
            raise ValueError("Column index must be non-negative.")
        result = ""
        current = column_index + 1
        while current:
            current, remainder = divmod(current - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def _validate_append_response(self, response: dict[str, Any], sheet_name: str) -> None:
        updates = response.get("updates")
        if not isinstance(updates, dict):
            raise GoogleSheetsWorksheetError(
                f"Google Sheets append response for worksheet {sheet_name!r} did not include update metadata."
            )
        updated_rows = updates.get("updatedRows")
        updated_range = updates.get("updatedRange")
        if updated_rows != 1 or not updated_range:
            raise GoogleSheetsWorksheetError(
                f"Google Sheets append response for worksheet {sheet_name!r} did not confirm a single appended row: {updates!r}."
            )

    @staticmethod
    def _extract_appended_row_number(response: dict[str, Any]) -> int | None:
        updates = response.get("updates")
        if not isinstance(updates, dict):
            return None
        updated_range = updates.get("updatedRange")
        if not isinstance(updated_range, str):
            return None
        match = re.search(r"![A-Z]+(\d+):[A-Z]+(\d+)$", updated_range)
        if match is None:
            return None
        start_row = int(match.group(1))
        end_row = int(match.group(2))
        if start_row != end_row:
            return None
        return start_row

    def _create_api_service(self) -> Any:
        credentials = _load_service_account_credentials(self.settings)
        return build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def _spreadsheets(self) -> Any:
        return self._service().spreadsheets()

    def _spreadsheets_values(self) -> Any:
        return self._spreadsheets().values()

    def _service(self) -> Any:
        if self._api_service is None:
            self._api_service = self._create_api_service()
        return self._api_service

    def _public_csv_url(self, sheet_name: str) -> str:
        query = urlencode({"tqx": "out:csv", "sheet": sheet_name})
        return f"https://docs.google.com/spreadsheets/d/{self.settings.spreadsheet_id}/gviz/tq?{query}"

    def _read_only_message(self, sheet_name: str) -> str:
        return (
            f"Worksheet {self._resolve_sheet_name(sheet_name)!r} is configured in explicit public read-only mode. "
            "Set service-account credentials to enable POST, PATCH, PUT, and DELETE operations."
        )

    @staticmethod
    def _normalize_header(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @classmethod
    def _normalize_header_key(cls, value: Any) -> str:
        header = cls._normalize_header(value)
        if not header:
            return ""
        normalized = unicodedata.normalize("NFKC", header)
        normalized = normalized.replace("–", "-").replace("—", "-").replace("−", "-")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.casefold()

    @staticmethod
    def _normalize_inbound_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed or None
        return value

    @staticmethod
    def _serialize_outbound_value(value: Any) -> Any:
        if value is None:
            return ""
        return value


def _load_service_account_credentials(settings: GoogleSheetsSettings) -> Credentials:
    guidance = (
        " Confirm that the service account JSON is valid, belongs to the intended Google Cloud project, "
        "and that the target spreadsheet is shared with the service account email."
    )
    if settings.service_account_file:
        credential_path = Path(settings.service_account_file)
        if not credential_path.exists():
            raise GoogleSheetsConfigurationError(
                f"Service account credentials file was not found: {credential_path}." + guidance
            )
        try:
            return Credentials.from_service_account_file(str(credential_path), scopes=[SHEETS_API_SCOPE])
        except (ValueError, TypeError) as exc:
            message = f"Failed to load Google service account credentials from {credential_path}." + guidance
            raise GoogleSheetsConfigurationError(message) from exc
    if settings.service_account_json:
        try:
            info = json.loads(settings.service_account_json)
        except json.JSONDecodeError as exc:
            raise GoogleSheetsConfigurationError(
                "VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON." + guidance
            ) from exc
        try:
            return Credentials.from_service_account_info(info, scopes=[SHEETS_API_SCOPE])
        except (ValueError, TypeError) as exc:
            message = "Failed to load Google service account credentials from VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON." + guidance
            raise GoogleSheetsConfigurationError(message) from exc
    raise GoogleSheetsConfigurationError(
        "Authenticated Google Sheets mode requires VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE or "
        "VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON."
    )


def build_google_sheets_gateway(settings: GoogleSheetsSettings, expected_headers: Sequence[str]) -> GoogleSheetsTableGateway:
    gateway = GoogleSheetsTableGateway(settings=settings, expected_headers=expected_headers)
    try:
        gateway.validate_connection()
    except (GoogleSheetsConfigurationError, GoogleSheetsConnectivityError, GoogleSheetsWorksheetError):
        LOGGER.exception(
            "Google Sheets startup validation failed for spreadsheet %s worksheet %s in %s mode.",
            settings.spreadsheet_id,
            settings.worksheet_name,
            settings.runtime_mode_label,
        )
        raise
    return gateway
