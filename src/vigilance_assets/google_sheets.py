from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import GoogleSheetsSettings
from .spreadsheet import RowData, SheetRecord, SpreadsheetBackendError, SpreadsheetTableGateway


class GoogleSheetsConfigurationError(SpreadsheetBackendError):
    """Raised when Google Sheets configuration is invalid."""


class GoogleSheetsConnectivityError(SpreadsheetBackendError):
    """Raised when the public Google Sheets backend cannot be reached."""


class GoogleSheetsWorksheetError(SpreadsheetBackendError):
    """Raised when a required worksheet or header row is invalid."""


class GoogleSheetsReadOnlyError(SpreadsheetBackendError):
    """Raised when a mutation is requested against a public read-only sheet."""


@dataclass(frozen=True, slots=True)
class WorksheetSnapshot:
    sheet_name: str
    sheet_id: int | None
    headers: tuple[str, ...]
    rows: tuple[SheetRecord, ...]


@dataclass(slots=True)
class GoogleSheetsTableGateway(SpreadsheetTableGateway):
    """Public Google Sheets adapter for the canonical ASSETS worksheet.

    The gateway intentionally uses the unauthenticated CSV export endpoint for a
    publicly accessible worksheet. Google does not provide anonymous write
    operations for Sheets through this approach, so mutation methods raise a
    dedicated read-only error.
    """

    settings: GoogleSheetsSettings
    expected_headers: Sequence[str] = ()
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        self._expected_headers = tuple(self.expected_headers)
        self._expected_header_set = set(self._expected_headers)

    @property
    def worksheet_name(self) -> str:
        return self.settings.worksheet_name

    @property
    def is_read_only(self) -> bool:
        return True

    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        snapshot = self._load_snapshot(sheet_name)
        return [SheetRecord(row_number=row.row_number, values=dict(row.values)) for row in snapshot.rows]

    def append_row(self, sheet_name: str, values: RowData) -> SheetRecord:
        raise GoogleSheetsReadOnlyError(self._read_only_message(sheet_name))

    def update_row(self, sheet_name: str, row_number: int, values: RowData) -> SheetRecord:
        raise GoogleSheetsReadOnlyError(self._read_only_message(sheet_name))

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        raise GoogleSheetsReadOnlyError(self._read_only_message(sheet_name))

    def validate_connection(self) -> WorksheetSnapshot:
        return self._load_snapshot(self.worksheet_name)

    def _load_snapshot(self, sheet_name: str) -> WorksheetSnapshot:
        resolved_sheet_name = self._resolve_sheet_name(sheet_name)
        raw_rows = self._fetch_public_rows(resolved_sheet_name)
        return self._build_snapshot(
            sheet_name=resolved_sheet_name,
            sheet_id=None,
            raw_rows=raw_rows,
        )

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

    def _resolve_sheet_name(self, requested_sheet_name: str) -> str:
        if requested_sheet_name in {"ASSETS", self.settings.worksheet_name}:
            return self.settings.worksheet_name
        raise GoogleSheetsWorksheetError(
            f"Only the canonical ASSETS worksheet is supported; received {requested_sheet_name!r}."
        )

    def _public_csv_url(self, sheet_name: str) -> str:
        query = urlencode({"tqx": "out:csv", "sheet": sheet_name})
        return f"https://docs.google.com/spreadsheets/d/{self.settings.spreadsheet_id}/gviz/tq?{query}"

    def _read_only_message(self, sheet_name: str) -> str:
        return (
            f"Worksheet {self._resolve_sheet_name(sheet_name)!r} is configured through the public Google Sheets export "
            "endpoint, which is read-only. Authenticated Google API writes have been intentionally disabled."
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


def build_google_sheets_gateway(settings: GoogleSheetsSettings, expected_headers: Sequence[str]) -> GoogleSheetsTableGateway:
    gateway = GoogleSheetsTableGateway(settings=settings, expected_headers=expected_headers)
    gateway.validate_connection()
    return gateway
