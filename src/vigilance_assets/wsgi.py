from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from .api import create_app
from .config import load_runtime_settings
from .infrastructure import build_spreadsheet_repository
from .repository import SpreadsheetAssetRepository
from .spreadsheet import SheetRecord, SpreadsheetTableGateway


@dataclass(slots=True)
class InMemorySpreadsheetGateway(SpreadsheetTableGateway):
    """Minimal header-keyed gateway used for local/container startup."""

    _rows_by_sheet: dict[str, list[SheetRecord]] = field(default_factory=dict)

    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        return [
            SheetRecord(row_number=record.row_number, values=dict(record.values))
            for record in self._rows_by_sheet.get(sheet_name, [])
        ]

    def append_row(self, sheet_name: str, values: dict[str, object]) -> SheetRecord:
        rows = self._rows_by_sheet.setdefault(sheet_name, [])
        record = SheetRecord(row_number=len(rows) + 1, values=dict(values))
        rows.append(record)
        return SheetRecord(row_number=record.row_number, values=dict(record.values))

    def update_row(self, sheet_name: str, row_number: int, values: dict[str, object]) -> SheetRecord:
        rows = self._rows_by_sheet.setdefault(sheet_name, [])
        for index, record in enumerate(rows):
            if record.row_number == row_number:
                updated = SheetRecord(row_number=row_number, values=dict(values))
                rows[index] = updated
                return SheetRecord(row_number=updated.row_number, values=dict(updated.values))
        raise KeyError(f"Row {row_number} not found in sheet {sheet_name}.")

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        rows = self._rows_by_sheet.setdefault(sheet_name, [])
        for index, record in enumerate(rows):
            if record.row_number == row_number:
                del rows[index]
                return
        raise KeyError(f"Row {row_number} not found in sheet {sheet_name}.")


MEMORY_BACKEND: Final[str] = "memory"


def create_runtime_app():
    """Create an app instance using environment-based runtime settings."""

    settings = load_runtime_settings()
    if settings.spreadsheet.backend == MEMORY_BACKEND:
        repository = SpreadsheetAssetRepository(
            workbook_reference=settings.spreadsheet.resolved_workbook_reference,
            gateway=InMemorySpreadsheetGateway(),
        )
    else:
        repository = build_spreadsheet_repository(settings=settings)
    return create_app(repository=repository)


app = create_runtime_app()
