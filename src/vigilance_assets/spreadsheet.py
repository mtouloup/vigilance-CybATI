from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from .models import AssetRecord, normalize_last_updated
from .schema import AssetSchemaCatalog, FieldDefinition, load_schema_catalog

ASSETS_SHEET_NAME = "ASSETS"

CellValue = str | int | float | bool | date | datetime | None
RowData = dict[str, CellValue]


class SpreadsheetBackendError(RuntimeError):
    """Raised when a spreadsheet backend cannot satisfy a repository request."""


@dataclass(frozen=True, slots=True)
class SheetRecord:
    """Physical sheet row represented only by header names and row number."""

    row_number: int
    values: RowData


class SpreadsheetTableGateway(Protocol):
    """Generic spreadsheet gateway isolated from the repository domain.

    Implementations may wrap Google Sheets, Excel files, CSV adapters, or test
    doubles. All row payloads must be keyed by sheet header name.
    """

    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        """Return all data rows for a sheet."""

    def append_row(self, sheet_name: str, values: RowData) -> SheetRecord:
        """Append a row keyed by sheet headers and return the stored row."""

    def update_row(self, sheet_name: str, row_number: int, values: RowData) -> SheetRecord:
        """Replace a row by row number using header-keyed values."""

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        """Delete a row by row number."""


class AssetSpreadsheetMapper:
    """Maps between spreadsheet rows and domain asset records."""

    def __init__(self, catalog: AssetSchemaCatalog | None = None) -> None:
        self.catalog = catalog or load_schema_catalog()
        field_definitions = [*self.catalog.common_fields]
        for fields in self.catalog.category_fields.values():
            field_definitions.extend(fields)
        self._fields_by_name = {field.name: field for field in field_definitions}
        self._headers_by_name = {field.name: field.sheet_header for field in field_definitions}
        self._names_by_header = {field.sheet_header: field.name for field in field_definitions}

    @property
    def sheet_name(self) -> str:
        return ASSETS_SHEET_NAME

    @property
    def ordered_headers(self) -> tuple[str, ...]:
        headers = [field.sheet_header for field in self.catalog.common_fields]
        for fields in self.catalog.category_fields.values():
            for field in fields:
                if field.sheet_header not in headers:
                    headers.append(field.sheet_header)
        return tuple(headers)

    def row_to_payload(self, row: RowData) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for header, value in row.items():
            field_name = self._names_by_header.get(header)
            if field_name is None:
                continue
            converted = self._deserialize_cell(self._fields_by_name[field_name], value)
            if converted is not None:
                payload[field_name] = converted
        return payload

    def row_to_asset(self, row: RowData) -> AssetRecord:
        payload = self.row_to_payload(row)
        from .models import build_asset_record

        return build_asset_record(payload)

    def asset_to_row(self, asset: AssetRecord) -> RowData:
        payload = asset.to_dict()
        category = asset.category
        allowed_names = self.catalog.common_field_names | self.catalog.category_field_names(category)
        row: RowData = {}
        for header in self.ordered_headers:
            field_name = self._names_by_header[header]
            if field_name not in allowed_names:
                row[header] = None
                continue
            row[header] = self._serialize_cell(self._fields_by_name[field_name], payload.get(field_name))
        return row

    def _deserialize_cell(self, field: FieldDefinition, value: CellValue) -> Any:
        if value in (None, ""):
            return None
        if field.name == "Last_Updated":
            return normalize_last_updated(value)
        if field.field_type == "integer":
            if isinstance(value, int):
                return value
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.isdigit():
                    return int(stripped)
        if field.field_type == "string" and not isinstance(value, str):
            return str(value)
        return value

    def _serialize_cell(self, field: FieldDefinition, value: Any) -> CellValue:
        if value is None:
            return None
        if field.name == "Last_Updated":
            normalized = normalize_last_updated(value)
            return normalized.isoformat() if normalized is not None else None
        return value
