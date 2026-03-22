from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import GoogleSheetsSettings
from .spreadsheet import RowData, SheetRecord, SpreadsheetBackendError, SpreadsheetTableGateway

_GOOGLE_SHEETS_SCOPE = ("https://www.googleapis.com/auth/spreadsheets",)


class GoogleSheetsConfigurationError(SpreadsheetBackendError):
    """Raised when Google Sheets configuration or credentials are invalid."""


class GoogleSheetsConnectivityError(SpreadsheetBackendError):
    """Raised when the Google Sheets backend cannot be reached."""


class GoogleSheetsWorksheetError(SpreadsheetBackendError):
    """Raised when a required worksheet or header row is invalid."""


@dataclass(frozen=True, slots=True)
class WorksheetSnapshot:
    sheet_name: str
    sheet_id: int
    headers: tuple[str, ...]
    rows: tuple[SheetRecord, ...]


@dataclass(slots=True)
class GoogleSheetsTableGateway(SpreadsheetTableGateway):
    """Google Sheets adapter for the canonical ASSETS worksheet."""

    settings: GoogleSheetsSettings
    expected_headers: Sequence[str] = ()
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        self._expected_headers = tuple(self.expected_headers)
        self._expected_header_set = set(self._expected_headers)
        self._service = self._build_service()

    @property
    def worksheet_name(self) -> str:
        return self.settings.worksheet_name

    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        snapshot = self._load_snapshot(sheet_name)
        return [SheetRecord(row_number=row.row_number, values=dict(row.values)) for row in snapshot.rows]

    def append_row(self, sheet_name: str, values: RowData) -> SheetRecord:
        snapshot = self._load_snapshot(sheet_name)
        ordered_values = [self._normalize_outbound_value(values.get(header)) for header in snapshot.headers]
        response = (
            self._service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.settings.spreadsheet_id,
                range=self._sheet_range(snapshot.sheet_name),
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
        returned_values = (updates.get("updatedData", {}).get("values") or [ordered_values])[0]
        return SheetRecord(row_number=row_number, values=self._row_values_from_sequence(snapshot.headers, returned_values))

    def update_row(self, sheet_name: str, row_number: int, values: RowData) -> SheetRecord:
        snapshot = self._load_snapshot(sheet_name)
        self._ensure_data_row(snapshot, row_number)
        existing_row = next((row for row in snapshot.rows if row.row_number == row_number), None)
        merged = dict(existing_row.values) if existing_row is not None else {header: None for header in snapshot.headers}
        merged.update(values)
        ordered_values = [self._normalize_outbound_value(merged.get(header)) for header in snapshot.headers]
        response = (
            self._service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.settings.spreadsheet_id,
                range=self._sheet_row_range(snapshot.sheet_name, row_number, len(snapshot.headers)),
                valueInputOption="USER_ENTERED",
                includeValuesInResponse=True,
                body={"values": [ordered_values]},
            )
            .execute()
        )
        returned_values = (response.get("updatedData", {}).get("values") or [ordered_values])[0]
        return SheetRecord(row_number=row_number, values=self._row_values_from_sequence(snapshot.headers, returned_values))

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        snapshot = self._load_snapshot(sheet_name)
        self._ensure_data_row(snapshot, row_number)
        (
            self._service.spreadsheets()
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

    def validate_connection(self) -> WorksheetSnapshot:
        return self._load_snapshot(self.worksheet_name)

    def _load_snapshot(self, sheet_name: str) -> WorksheetSnapshot:
        resolved_sheet_name = self._resolve_sheet_name(sheet_name)
        metadata = (
            self._service.spreadsheets()
            .get(spreadsheetId=self.settings.spreadsheet_id, includeGridData=False)
            .execute()
        )
        sheet_properties = self._find_sheet_properties(metadata, resolved_sheet_name)
        values_response = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self.settings.spreadsheet_id, range=self._sheet_range(resolved_sheet_name))
            .execute()
        )
        raw_rows = values_response.get("values", [])
        return self._build_snapshot(
            sheet_name=resolved_sheet_name,
            sheet_id=sheet_properties["sheetId"],
            raw_rows=raw_rows,
        )

    def _build_snapshot(self, *, sheet_name: str, sheet_id: int, raw_rows: Sequence[Sequence[Any]]) -> WorksheetSnapshot:
        if not raw_rows:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} is empty; the first row must contain the canonical ASSETS headers."
            )
        headers = tuple(self._normalize_header(value) for value in raw_rows[0])
        self._validate_headers(sheet_name, headers)
        cleaned_headers = tuple(header for header in headers if header)
        records: list[SheetRecord] = []
        for row_number, row in enumerate(raw_rows[1:], start=2):
            values = {
                header: self._normalize_inbound_value(row[index] if index < len(row) else None)
                for index, header in enumerate(cleaned_headers)
            }
            if not any(value not in (None, "") for value in values.values()):
                continue
            records.append(SheetRecord(row_number=row_number, values=values))
        return WorksheetSnapshot(sheet_name=sheet_name, sheet_id=sheet_id, headers=cleaned_headers, rows=tuple(records))

    def _validate_headers(self, sheet_name: str, headers: Sequence[str]) -> None:
        cleaned = [header for header in headers if header]
        if not cleaned:
            raise GoogleSheetsWorksheetError(f"Worksheet {sheet_name!r} does not contain any non-empty headers.")
        duplicates = sorted({header for header in cleaned if cleaned.count(header) > 1})
        if duplicates:
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} contains duplicate headers: {', '.join(duplicates)}."
            )
        missing = sorted(self._expected_header_set.difference(cleaned))
        extra = sorted(set(cleaned).difference(self._expected_header_set))
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append(f"missing headers: {', '.join(missing)}")
            if extra:
                details.append(f"unexpected headers: {', '.join(extra)}")
            raise GoogleSheetsWorksheetError(
                f"Worksheet {sheet_name!r} headers do not match the canonical schema ({'; '.join(details)})."
            )

    def _find_sheet_properties(self, metadata: Mapping[str, Any], sheet_name: str) -> Mapping[str, Any]:
        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == sheet_name:
                if "sheetId" not in properties:
                    raise GoogleSheetsWorksheetError(
                        f"Worksheet metadata for {sheet_name!r} did not include a numeric sheet id."
                    )
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

        if self.settings.credentials_json:
            try:
                credentials_info = json.loads(self.settings.credentials_json)
            except json.JSONDecodeError as exc:
                raise GoogleSheetsConfigurationError("VIGILANCE_GOOGLE_CREDENTIALS_JSON is not valid JSON.") from exc
            credentials_factory = service_account.Credentials.from_service_account_info
            credentials_source = credentials_info
        elif self.settings.credentials_path:
            credentials_path = Path(self.settings.credentials_path)
            if not credentials_path.is_file():
                raise GoogleSheetsConfigurationError(
                    f"Google credentials file was not found at {self.settings.credentials_path!r}."
                )
            credentials_factory = service_account.Credentials.from_service_account_file
            credentials_source = str(credentials_path)
        else:
            raise GoogleSheetsConfigurationError(
                "Google Sheets credentials are required; provide VIGILANCE_GOOGLE_CREDENTIALS_PATH or "
                "VIGILANCE_GOOGLE_CREDENTIALS_JSON."
            )

        try:
            credentials = credentials_factory(credentials_source, scopes=_GOOGLE_SHEETS_SCOPE)
        except Exception as exc:  # noqa: BLE001
            raise GoogleSheetsConfigurationError("Failed to load Google service account credentials.") from exc
        try:
            return build("sheets", "v4", credentials=credentials, cache_discovery=False)
        except Exception as exc:  # noqa: BLE001
            raise GoogleSheetsConnectivityError("Failed to initialize the Google Sheets API client.") from exc

    def _resolve_sheet_name(self, requested_sheet_name: str) -> str:
        if requested_sheet_name in {"ASSETS", self.settings.worksheet_name}:
            return self.settings.worksheet_name
        raise GoogleSheetsWorksheetError(
            f"Only the canonical ASSETS worksheet is supported; received {requested_sheet_name!r}."
        )

    @staticmethod
    def _normalize_header(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

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
        import re

        match = re.search(r"![A-Z]+(\d+):[A-Z]+\d+$", updated_range)
        if match is None:
            raise GoogleSheetsWorksheetError(f"Could not determine appended row number from range {updated_range!r}.")
        return int(match.group(1))

    @staticmethod
    def _row_values_from_sequence(headers: Sequence[str], row: Sequence[Any]) -> RowData:
        return {
            header: GoogleSheetsTableGateway._normalize_inbound_value(row[index] if index < len(row) else None)
            for index, header in enumerate(headers)
        }

    @staticmethod
    def _ensure_data_row(snapshot: WorksheetSnapshot, row_number: int) -> None:
        if row_number < 2:
            raise GoogleSheetsWorksheetError(
                f"Row {row_number} is not a data row in worksheet {snapshot.sheet_name!r}."
            )


def build_google_sheets_gateway(settings: GoogleSheetsSettings, expected_headers: Sequence[str]) -> GoogleSheetsTableGateway:
    gateway = GoogleSheetsTableGateway(settings=settings, expected_headers=expected_headers)
    gateway.validate_connection()
    return gateway
