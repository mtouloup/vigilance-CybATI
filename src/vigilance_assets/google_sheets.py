from __future__ import annotations

import csv
import io
import re
import unicodedata
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


@dataclass(frozen=True, slots=True)
class HeaderSelection:
    header_row_index: int
    headers: tuple[str, ...]
    canonical_headers: tuple[str, ...]
    canonical_indexes: tuple[int, ...]
    matched_count: int


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
    header_scan_limit: int = 10

    def __post_init__(self) -> None:
        self._expected_headers = tuple(self.expected_headers)
        self._expected_header_set = set(self._expected_headers)
        self._normalized_expected_headers = {
            self._normalize_header_key(header): header for header in self._expected_headers
        }

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


def build_google_sheets_gateway(settings: GoogleSheetsSettings, expected_headers: Sequence[str]) -> GoogleSheetsTableGateway:
    gateway = GoogleSheetsTableGateway(settings=settings, expected_headers=expected_headers)
    gateway.validate_connection()
    return gateway
