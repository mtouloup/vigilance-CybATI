from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from .config import GoogleSheetsSettings, SpreadsheetBackendSettings
from .spreadsheet import RowData, SheetRecord, SpreadsheetBackendError, SpreadsheetTableGateway

_GOOGLE_READ_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)


class GoogleSheetsConfigurationError(SpreadsheetBackendError):
    """Raised when Google Sheets configuration or credentials are invalid."""


class GoogleSheetsConnectivityError(SpreadsheetBackendError):
    """Raised when the Google Sheets backend cannot be reached."""


class GoogleSheetsWorksheetError(SpreadsheetBackendError):
    """Raised when a required worksheet or header row is invalid."""


@dataclass(frozen=True, slots=True)
class WorksheetSnapshot:
    sheet_name: str
    sheet_id: int | None
    header_row_number: int
    headers: tuple[str, ...]
    rows: tuple[SheetRecord, ...]


@dataclass(slots=True)
class GoogleSheetsTableGateway(SpreadsheetTableGateway):
    """Google Sheets adapter using API credentials when available and gviz fallback for public reads."""

    settings: GoogleSheetsSettings
    expected_headers: Sequence[str] = ()
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        self._expected_header_set = set(self.expected_headers)

    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        sheet_name = self._resolve_sheet_name(sheet_name)
        snapshot = self._load_snapshot(sheet_name)
        return [SheetRecord(row_number=row.row_number, values=dict(row.values)) for row in snapshot.rows]

    def append_row(self, sheet_name: str, values: RowData) -> SheetRecord:
        sheet_name = self._resolve_sheet_name(sheet_name)
        self._ensure_write_enabled()
        snapshot = self._load_snapshot(sheet_name, require_authenticated=True)
        service = self._build_service()
        ordered_values = [self._normalize_outbound_value(values.get(header)) for header in snapshot.headers]
        response = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.settings.spreadsheet_id,
                range=self._sheet_range(sheet_name),
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                includeValuesInResponse=True,
                body={"values": [ordered_values]},
            )
            .execute()
        )
        updates = response.get("updates", {})
        updated_range = updates.get("updatedRange", "")
        row_number = self._extract_row_number(updated_range)
        updated_data = updates.get("updatedData", {})
        returned_values = (updated_data.get("values") or [ordered_values])[0]
        return SheetRecord(row_number=row_number, values=self._row_values_from_sequence(snapshot.headers, returned_values))

    def update_row(self, sheet_name: str, row_number: int, values: RowData) -> SheetRecord:
        sheet_name = self._resolve_sheet_name(sheet_name)
        self._ensure_write_enabled()
        snapshot = self._load_snapshot(sheet_name, require_authenticated=True)
        self._ensure_data_row(snapshot, row_number)
        service = self._build_service()
        existing_row = next((row for row in snapshot.rows if row.row_number == row_number), None)
        merged = dict(existing_row.values) if existing_row is not None else {header: None for header in snapshot.headers}
        merged.update(values)
        ordered_values = [self._normalize_outbound_value(merged.get(header)) for header in snapshot.headers]
        response = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.settings.spreadsheet_id,
                range=self._sheet_row_range(sheet_name, row_number, len(snapshot.headers)),
                valueInputOption="USER_ENTERED",
                includeValuesInResponse=True,
                body={"values": [ordered_values]},
            )
            .execute()
        )
        returned_values = (response.get("updatedData", {}).get("values") or [ordered_values])[0]
        return SheetRecord(row_number=row_number, values=self._row_values_from_sequence(snapshot.headers, returned_values))

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        sheet_name = self._resolve_sheet_name(sheet_name)
        self._ensure_write_enabled()
        snapshot = self._load_snapshot(sheet_name, require_authenticated=True)
        self._ensure_data_row(snapshot, row_number)
        if snapshot.sheet_id is None:
            raise GoogleSheetsWorksheetError(f"Worksheet metadata for {sheet_name!r} did not include a numeric sheet id.")
        service = self._build_service()
        (
            service.spreadsheets()
            .batchUpdate(
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
            )
            .execute()
        )

    def _load_snapshot(self, sheet_name: str, *, require_authenticated: bool = False) -> WorksheetSnapshot:
        if self._should_use_authenticated_access():
            return self._load_snapshot_via_api(sheet_name)
        if require_authenticated:
            raise GoogleSheetsConfigurationError(
                "Google Sheets write operations require service account credentials and read_write mode."
            )
        return self._load_snapshot_via_public_gviz(sheet_name)

    def _load_snapshot_via_api(self, sheet_name: str) -> WorksheetSnapshot:
        service = self._build_service()
        metadata = (
            service.spreadsheets()
            .get(spreadsheetId=self.settings.spreadsheet_id, includeGridData=False)
            .execute()
        )
        sheet_properties = self._find_sheet_properties(metadata, sheet_name)
        values_response = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=self.settings.spreadsheet_id, range=self._sheet_range(sheet_name))
            .execute()
        )
        raw_rows = values_response.get("values", [])
        return self._build_snapshot(
            sheet_name=sheet_name,
            sheet_id=sheet_properties.get("sheetId"),
            raw_rows=raw_rows,
        )

    def _load_snapshot_via_public_gviz(self, sheet_name: str) -> WorksheetSnapshot:
        url = (
            f"https://docs.google.com/spreadsheets/d/{quote(self.settings.spreadsheet_id or '')}"
            f"/gviz/tq?tqx=out:json&sheet={quote(sheet_name)}"
        )
        try:
            with urlopen(url, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            raise GoogleSheetsConnectivityError(
                f"Failed to fetch public Google Sheets data for worksheet {sheet_name!r}: HTTP {exc.code}."
            ) from exc
        except URLError as exc:
            raise GoogleSheetsConnectivityError(
                f"Failed to reach Google Sheets for worksheet {sheet_name!r}: {exc.reason}."
            ) from exc
        match = re.search(r"setResponse\((.*)\);?$", payload, flags=re.DOTALL)
        if match is None:
            raise GoogleSheetsConnectivityError("Google Sheets public response was not in the expected gviz JSON format.")
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise GoogleSheetsConnectivityError("Google Sheets public response contained invalid JSON.") from exc
        status = data.get("status")
        if status != "ok":
            raise GoogleSheetsConnectivityError(f"Google Sheets public response reported status {status!r}.")
        table = data.get("table", {})
        raw_rows = [self._extract_gviz_row(row) for row in table.get("rows", [])]
        return self._build_snapshot(sheet_name=sheet_name, sheet_id=None, raw_rows=raw_rows)

    def _build_snapshot(
        self,
        *,
        sheet_name: str,
        sheet_id: int | None,
        raw_rows: Sequence[Sequence[Any]],
    ) -> WorksheetSnapshot:
        header_row_index, headers = self._locate_header_row(raw_rows)
        self._validate_headers(sheet_name, headers)
        normalized_headers = tuple(header.strip() for header in headers)
        records: list[SheetRecord] = []
        for index, row in enumerate(raw_rows[header_row_index + 1 :], start=header_row_index + 2):
            if not any(self._normalize_inbound_value(value) not in (None, "") for value in row):
                continue
            values = {
                header: self._normalize_inbound_value(row[position] if position < len(row) else None)
                for position, header in enumerate(normalized_headers)
            }
            records.append(SheetRecord(row_number=index, values=values))
        return WorksheetSnapshot(
            sheet_name=sheet_name,
            sheet_id=sheet_id,
            header_row_number=header_row_index + 1,
            headers=normalized_headers,
            rows=tuple(records),
        )

    def _locate_header_row(self, raw_rows: Sequence[Sequence[Any]]) -> tuple[int, tuple[str, ...]]:
        for index, row in enumerate(raw_rows):
            normalized_row = tuple("" if value is None else str(value).strip() for value in row)
            normalized = tuple(value for value in normalized_row if value)
            if not normalized:
                continue
            if self._expected_header_set and self._expected_header_set.issubset(set(normalized)):
                return index, normalized_row
            if "Asset_ID" in normalized:
                return index, normalized_row
        raise GoogleSheetsWorksheetError("Could not locate a header row containing Asset_ID in the worksheet.")

    def _validate_headers(self, sheet_name: str, headers: Sequence[str]) -> None:
        cleaned = [header for header in (header.strip() for header in headers) if header]
        if not cleaned:
            raise GoogleSheetsWorksheetError(f"Worksheet {sheet_name!r} does not contain any non-empty headers.")
        duplicates = sorted({header for header in cleaned if cleaned.count(header) > 1})
        if duplicates:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} contains duplicate headers: {', '.join(duplicates)}."
            )
        if self._expected_header_set:
            missing = sorted(self._expected_header_set.difference(cleaned))
            if missing:
                raise GoogleSheetsWorksheetError(
                    f"Worksheet {sheet_name!r} is missing required headers: {', '.join(missing)}."
                )

    def _ensure_data_row(self, snapshot: WorksheetSnapshot, row_number: int) -> None:
        if row_number <= snapshot.header_row_number:
            raise GoogleSheetsWorksheetError(
                f"Row {row_number} is not a data row in worksheet {snapshot.sheet_name!r}."
            )

    def _find_sheet_properties(self, metadata: Mapping[str, Any], sheet_name: str) -> Mapping[str, Any]:
        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == sheet_name:
                return properties
        raise GoogleSheetsWorksheetError(f"Worksheet {sheet_name!r} was not found in the target spreadsheet.")

    def _build_service(self):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleSheetsConfigurationError(
                "Google Sheets dependencies are not installed. Install google-api-python-client and google-auth."
            ) from exc
        credentials_info: Mapping[str, Any] | None = None
        if self.settings.credentials_json:
            try:
                credentials_info = json.loads(self.settings.credentials_json)
            except json.JSONDecodeError as exc:
                raise GoogleSheetsConfigurationError("VIGILANCE_GOOGLE_CREDENTIALS_JSON is not valid JSON.") from exc
            credentials = service_account.Credentials.from_service_account_info(credentials_info, scopes=_GOOGLE_READ_SCOPES)
        elif self.settings.credentials_path:
            try:
                credentials = service_account.Credentials.from_service_account_file(
                    self.settings.credentials_path,
                    scopes=_GOOGLE_READ_SCOPES,
                )
            except OSError as exc:
                raise GoogleSheetsConfigurationError(
                    f"Could not read Google credentials file at {self.settings.credentials_path!r}."
                ) from exc
        else:
            raise GoogleSheetsConfigurationError(
                "Google Sheets credentials are required for authenticated access but were not provided."
            )
        try:
            return build("sheets", "v4", credentials=credentials, cache_discovery=False)
        except Exception as exc:  # noqa: BLE001
            raise GoogleSheetsConnectivityError("Failed to initialize the Google Sheets API client.") from exc

    def _should_use_authenticated_access(self) -> bool:
        if self.settings.mode == "read_only":
            return False
        if self.settings.mode == "read_write":
            return True
        return bool(self.settings.credentials_path or self.settings.credentials_json)

    def _resolve_sheet_name(self, requested_sheet_name: str) -> str:
        if requested_sheet_name == "ASSETS":
            return self.settings.assets_sheet_name
        if requested_sheet_name == "VOCABULARIES":
            return self.settings.vocabularies_sheet_name
        return requested_sheet_name

    def _ensure_write_enabled(self) -> None:
        if not self._should_use_authenticated_access() or self.settings.mode == "read_only":
            raise GoogleSheetsConfigurationError(
                "Google Sheets gateway is running in read_only mode; provide credentials and set mode to read_write or auto for writes."
            )

    @staticmethod
    def _sheet_range(sheet_name: str) -> str:
        escaped = sheet_name.replace("'", "''")
        return f"'{escaped}'"

    @classmethod
    def _sheet_row_range(cls, sheet_name: str, row_number: int, header_count: int) -> str:
        escaped = sheet_name.replace("'", "''")
        return f"'{escaped}'!A{row_number}:{cls._column_letter(header_count)}{row_number}"

    @staticmethod
    def _column_letter(index: int) -> str:
        result = ""
        current = index
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            result = chr(65 + remainder) + result
        return result or "A"

    @staticmethod
    def _extract_row_number(updated_range: str) -> int:
        match = re.search(r"![A-Z]+(\d+):[A-Z]+\d+$", updated_range)
        if match is None:
            raise GoogleSheetsWorksheetError(f"Could not determine appended row number from range {updated_range!r}.")
        return int(match.group(1))

    @staticmethod
    def _extract_gviz_row(row: Mapping[str, Any]) -> list[Any]:
        extracted: list[Any] = []
        for cell in row.get("c", []):
            if cell is None:
                extracted.append(None)
            else:
                extracted.append(cell.get("f") if cell.get("f") is not None else cell.get("v"))
        return extracted

    @staticmethod
    def _normalize_inbound_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed or None
        return value

    @staticmethod
    def _normalize_outbound_value(value: Any) -> Any:
        return "" if value is None else value

    @staticmethod
    def _row_values_from_sequence(headers: Sequence[str], row: Sequence[Any]) -> RowData:
        return {
            header: GoogleSheetsTableGateway._normalize_inbound_value(row[index] if index < len(row) else None)
            for index, header in enumerate(headers)
        }


def build_google_sheets_gateway(settings: SpreadsheetBackendSettings) -> GoogleSheetsTableGateway:
    if not settings.google_sheets.spreadsheet_id:
        raise GoogleSheetsConfigurationError("Google Sheets backend requires a spreadsheet id.")
    from .spreadsheet import AssetSpreadsheetMapper

    mapper = AssetSpreadsheetMapper()
    return GoogleSheetsTableGateway(settings=settings.google_sheets, expected_headers=mapper.ordered_headers)
