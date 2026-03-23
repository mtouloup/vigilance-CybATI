from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
from typing import Any, Literal, Mapping, Sequence

from .models import AssetRecord, build_asset_record
from .schema import AssetSchemaCatalog, FieldDefinition, load_schema_catalog
from .spreadsheet import SpreadsheetTableGateway

LOGGER = logging.getLogger(__name__)

SortDirection = Literal["asc", "desc"]
DeleteMode = Literal["archive", "delete"]
FilterValue = str | int | float | bool | None | Sequence[str | int | float | bool]


@dataclass(frozen=True, slots=True)
class AssetSort:
    """Sort instruction for asset listing operations."""

    field: str
    direction: SortDirection = "asc"


@dataclass(frozen=True, slots=True)
class AssetListQuery:
    """Query parameters for repository-level asset listing.

    This object captures the API-facing capabilities described in the schema
    and project instructions without coupling the repository to Flask request
    objects or spreadsheet-specific concepts.
    """

    filters: Mapping[str, FilterValue] = field(default_factory=dict)
    search: str | None = None
    sort: tuple[AssetSort, ...] = ()
    page: int = 1
    page_size: int = 50




@dataclass(frozen=True, slots=True)
class InventoryPayload:
    """Schema-keyed inventory payload used for non-mutating quality analysis."""

    payload: Mapping[str, Any]
    row_number: int | None = None


@dataclass(frozen=True, slots=True)
class AssetPage:
    """Paginated result set returned by :meth:`AssetRepository.list_assets`."""

    items: tuple[AssetRecord, ...]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class AssetSchemaView:
    """Repository-facing schema payload for all assets or a single category."""

    id_field: str
    common_fields: tuple[FieldDefinition, ...]
    category_fields: Mapping[str, tuple[FieldDefinition, ...]]
    vocabularies: Mapping[str, tuple[str, ...]]


class RepositoryError(Exception):
    """Base class for repository-layer errors."""


class AssetNotFoundError(RepositoryError):
    """Raised when a requested asset cannot be found."""


class DuplicateAssetError(RepositoryError):
    """Raised when attempting to create an asset with an existing ID."""


class UnsupportedVocabularyError(RepositoryError):
    """Raised when a requested controlled vocabulary does not exist."""


class UnsupportedCategoryError(RepositoryError):
    """Raised when a requested asset category does not exist in the schema."""


class ReadOnlyRepositoryError(RepositoryError):
    """Raised when a mutating operation is attempted against a read-only backend."""


class AssetRepository(ABC):
    """Abstract storage interface for the asset inventory domain.

    Implementations may persist data in spreadsheets, databases, files, or any
    other backend, but callers should only depend on this interface and the
    domain models it returns.
    """

    def __init__(self, catalog: AssetSchemaCatalog | None = None) -> None:
        self.catalog = catalog or load_schema_catalog()

    @abstractmethod
    def list_assets(self, query: AssetListQuery | None = None) -> AssetPage:
        """Return a paginated list of assets matching the provided query."""

    @abstractmethod
    def get_asset(self, asset_id: str) -> AssetRecord | None:
        """Return the asset with the given identifier, if it exists."""

    @abstractmethod
    def create_asset(self, asset: AssetRecord) -> AssetRecord:
        """Persist a new asset and return the stored record.

        Implementations should raise :class:`DuplicateAssetError` when the
        identifier already exists.
        """

    @abstractmethod
    def update_asset(self, asset_id: str, asset: AssetRecord) -> AssetRecord:
        """Replace the stored representation of an existing asset."""

    @abstractmethod
    def delete_asset(self, asset_id: str, *, mode: DeleteMode = "archive") -> None:
        """Remove or archive an asset depending on backend capabilities.

        The default mode is ``archive`` so implementations can support soft
        deletion even when a physical delete is undesirable.
        """

    def iter_inventory_payloads(self) -> tuple[InventoryPayload, ...]:
        """Return schema-keyed inventory payloads for quality/reporting workflows."""

        page = self.list_assets(AssetListQuery(page=1, page_size=10_000))
        return tuple(InventoryPayload(payload=asset.to_dict()) for asset in page.items)

    def get_vocabularies(self) -> Mapping[str, tuple[str, ...]]:
        """Return all controlled vocabularies defined by the canonical schema."""

        return self.catalog.vocabularies

    def get_vocabulary(self, name: str) -> tuple[str, ...]:
        """Return a single controlled vocabulary by name."""

        try:
            return self.catalog.vocabularies[name]
        except KeyError as exc:
            raise UnsupportedVocabularyError(f"Unknown vocabulary: {name}") from exc

    def get_asset_schema(self) -> AssetSchemaView:
        """Return the canonical schema definition for the asset resource."""

        return AssetSchemaView(
            id_field=self.catalog.id_field,
            common_fields=self.catalog.common_fields,
            category_fields=self.catalog.category_fields,
            vocabularies=self.catalog.vocabularies,
        )

    def get_category_schema(self, category: str) -> AssetSchemaView:
        """Return the schema definition restricted to a single category."""

        if category not in self.catalog.category_fields:
            raise UnsupportedCategoryError(f"Unknown category: {category}")
        return AssetSchemaView(
            id_field=self.catalog.id_field,
            common_fields=self.catalog.common_fields,
            category_fields={category: self.catalog.category_fields[category]},
            vocabularies=self.catalog.vocabularies,
        )


class SpreadsheetAssetRepository(AssetRepository):
    """Spreadsheet-backed repository over a generic header-based gateway."""

    def __init__(
        self,
        workbook_reference: str,
        gateway: SpreadsheetTableGateway | None = None,
        catalog: AssetSchemaCatalog | None = None,
        *,
        read_only: bool = False,
    ) -> None:
        super().__init__(catalog=catalog)
        self.workbook_reference = workbook_reference
        self.gateway = gateway
        self.read_only = read_only
        from .spreadsheet import AssetSpreadsheetMapper

        self.mapper = AssetSpreadsheetMapper(self.catalog)

    def list_assets(self, query: AssetListQuery | None = None) -> AssetPage:
        query = query or AssetListQuery()
        matched = [asset for _, asset in self._load_sheet_rows() if self._matches_query(asset, query)]
        for sort in reversed(query.sort):
            matched.sort(
                key=lambda asset, field=sort.field: self._sort_value(asset, field),
                reverse=sort.direction == "desc",
            )
        total = len(matched)
        start = max(query.page - 1, 0) * query.page_size
        end = start + query.page_size
        return AssetPage(items=tuple(matched[start:end]), total=total, page=query.page, page_size=query.page_size)

    def get_asset(self, asset_id: str) -> AssetRecord | None:
        return self._find_asset_row(asset_id)[1]

    def create_asset(self, asset: AssetRecord) -> AssetRecord:
        self._ensure_writable()
        if self.get_asset(asset.asset_id) is not None:
            raise DuplicateAssetError(asset.asset_id)
        record = self._require_gateway().append_row(self.mapper.sheet_name, self.mapper.asset_to_row(asset))
        return self.mapper.row_to_asset(record.values)

    def update_asset(self, asset_id: str, asset: AssetRecord) -> AssetRecord:
        self._ensure_writable()
        gateway = self._require_gateway()
        row_number, _ = self._find_asset_row_or_raise(asset_id)
        record = gateway.update_row(self.mapper.sheet_name, row_number, self.mapper.asset_to_row(asset))
        return self.mapper.row_to_asset(record.values)

    def delete_asset(self, asset_id: str, *, mode: DeleteMode = "archive") -> None:
        self._ensure_writable()
        gateway = self._require_gateway()
        row_number, existing_asset = self._find_asset_row_or_raise(asset_id)
        if mode == "delete":
            gateway.delete_row(self.mapper.sheet_name, row_number)
            return
        archived_payload = {**existing_asset.to_dict(), "Status": "Deprecated"}
        archived_asset = build_asset_record(archived_payload)
        gateway.update_row(self.mapper.sheet_name, row_number, self.mapper.asset_to_row(archived_asset))

    def iter_inventory_payloads(self) -> tuple[InventoryPayload, ...]:
        payloads: list[InventoryPayload] = []
        for record in self._require_gateway().list_rows(self.mapper.sheet_name):
            payload = self.mapper.row_to_payload(record.values)
            if not self.mapper.is_parsable_asset_payload(payload):
                continue
            payloads.append(InventoryPayload(payload=payload, row_number=record.row_number))
        return tuple(payloads)

    def _load_sheet_rows(self) -> list[tuple[int, AssetRecord]]:
        gateway = self._require_gateway()
        scanned_rows = 0
        skipped_rows = 0
        parsed_rows: list[tuple[int, AssetRecord]] = []
        for record in gateway.list_rows(self.mapper.sheet_name):
            scanned_rows += 1
            payload = self.mapper.row_to_payload(record.values)
            if not self.mapper.is_parsable_asset_payload(payload):
                skipped_rows += 1
                continue
            parsed_rows.append((record.row_number, self.mapper.payload_to_asset(payload)))
        LOGGER.debug(
            "Loaded asset rows from workbook=%s scanned=%s skipped=%s parsed=%s",
            self.workbook_reference,
            scanned_rows,
            skipped_rows,
            len(parsed_rows),
        )
        return parsed_rows

    def _find_asset_row(self, asset_id: str) -> tuple[int | None, AssetRecord | None]:
        for row_number, asset in self._load_sheet_rows():
            if asset.asset_id == asset_id:
                return row_number, asset
        return None, None

    def _find_asset_row_or_raise(self, asset_id: str) -> tuple[int, AssetRecord]:
        row_number, asset = self._find_asset_row(asset_id)
        if row_number is None or asset is None:
            raise AssetNotFoundError(asset_id)
        return row_number, asset


    def _ensure_writable(self) -> None:
        if self.read_only:
            raise ReadOnlyRepositoryError(
                "This deployment is running in explicit public read-only Google Sheets mode, so asset mutations are disabled. "
                "Configure a service account to enable write operations."
            )

    def _require_gateway(self) -> SpreadsheetTableGateway:
        if self.gateway is None:
            raise NotImplementedError("Spreadsheet gateway integration has not been configured.")
        return self.gateway

    def _matches_query(self, asset: AssetRecord, query: AssetListQuery) -> bool:
        payload = asset.to_dict()
        for field, expected in query.filters.items():
            actual = payload.get(field)
            if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        if query.search:
            haystacks = [str(payload.get(field, "")) for field in self.catalog.searchable_fields]
            needle = query.search.casefold()
            if not any(needle in haystack.casefold() for haystack in haystacks):
                return False
        return True

    @staticmethod
    def _sort_value(asset: AssetRecord, field: str) -> tuple[bool, object]:
        value = asset.to_dict().get(field)
        return (value is None, value)
