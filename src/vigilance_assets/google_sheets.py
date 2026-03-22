from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import GoogleSheetsSettings
from .spreadsheet import RowData, SheetRecord, SpreadsheetBackendError, SpreadsheetTableGateway

LOGGER = logging.getLogger(__name__)
SHEETS_API_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


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
        body = {"values": [self._row_to_ordered_values(values, snapshot.headers)]}
        try:
            self._spreadsheets_values().append(
                spreadsheetId=self.settings.spreadsheet_id,
                range=self._worksheet_range(snapshot.sheet_name),
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                includeValuesInResponse=True,
                body=body,
            ).execute()
        except HttpError as exc:
            raise GoogleSheetsConnectivityError("Failed to append a row through the Google Sheets API.") from exc
        return self._find_appended_row(snapshot.sheet_name, values.get("Asset_ID"))

    def update_row(self, sheet_name: str, row_number: int, values: RowData) -> SheetRecord:
        if self.is_read_only:
            raise GoogleSheetsReadOnlyError(self._read_only_message(sheet_name))
        snapshot = self._load_snapshot(sheet_name)
        try:
            self._spreadsheets_values().update(
                spreadsheetId=self.settings.spreadsheet_id,
                range=f"{snapshot.sheet_name}!{row_number}:{row_number}",
                valueInputOption="USER_ENTERED",
                body={"values": [self._row_to_ordered_values(values, snapshot.headers)]},
            ).execute()
        except HttpError as exc:
            raise GoogleSheetsConnectivityError(
                f"Failed to update row {row_number} through the Google Sheets API."
            ) from exc
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
            raise GoogleSheetsConnectivityError(
                f"Failed to delete row {row_number} through the Google Sheets API."
            ) from exc

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
            raise GoogleSheetsConnectivityError("Failed to load spreadsheet metadata from the Google Sheets API.") from exc
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
            raise GoogleSheetsConnectivityError(
                f"Failed to read worksheet {sheet_name!r} through the Google Sheets API."
            ) from exc
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
        records: list[SheetRecord] = []
        for row_number, row in enumerate(raw_rows[selection.header_row_index + 1 :], start=selection.header_row_index + 2):
            values = {
                canonical_header: self._normalize_inbound_value(row[column_index] if column_index < len(row) else None)
                for canonical_header, column_index in zip(selection.canonical_headers, selection.canonical_indexes)
            }
            if not any(value not in (None, "") for value in values.values()):
                continue
            records.append(SheetRecord(row_number=row_number, values=values))
        return WorksheetSnapshot(
            sheet_name=sheet_name,
            sheet_id=sheet_id,
            headers=selection.canonical_headers,
            rows=tuple(records),
        )

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

    def _find_appended_row(self, sheet_name: str, asset_id: Any) -> SheetRecord:
        snapshot = self._load_snapshot(sheet_name)
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
    if settings.service_account_file:
        credential_path = Path(settings.service_account_file)
        if not credential_path.exists():
            raise GoogleSheetsConfigurationError(
                f"Service account credentials file was not found: {credential_path}"
            )
        return Credentials.from_service_account_file(str(credential_path), scopes=[SHEETS_API_SCOPE])
    if settings.service_account_json:
        try:
            info = json.loads(settings.service_account_json)
        except json.JSONDecodeError as exc:
            raise GoogleSheetsConfigurationError(
                "VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON."
            ) from exc
        return Credentials.from_service_account_info(info, scopes=[SHEETS_API_SCOPE])
    raise GoogleSheetsConfigurationError(
        "Authenticated Google Sheets mode requires VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE or "
        "VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON."
    )


def build_google_sheets_gateway(settings: GoogleSheetsSettings, expected_headers: Sequence[str]) -> GoogleSheetsTableGateway:
    gateway = GoogleSheetsTableGateway(settings=settings, expected_headers=expected_headers)
    gateway.validate_connection()
    return gateway
