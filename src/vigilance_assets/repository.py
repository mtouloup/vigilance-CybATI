from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

from .models import AssetRecord, build_asset_record
from .schema import AssetSchemaCatalog, FieldDefinition, load_schema_catalog
from .spreadsheet import SpreadsheetTableGateway

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
    ) -> None:
        super().__init__(catalog=catalog)
        self.workbook_reference = workbook_reference
        self.gateway = gateway
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
        for _, asset in self._load_sheet_rows():
            if asset.asset_id == asset_id:
                return asset
        return None

    def create_asset(self, asset: AssetRecord) -> AssetRecord:
        if self.get_asset(asset.asset_id) is not None:
            raise DuplicateAssetError(asset.asset_id)
        record = self._require_gateway().append_row(self.mapper.sheet_name, self.mapper.asset_to_row(asset))
        return self.mapper.row_to_asset(record.values)

    def update_asset(self, asset_id: str, asset: AssetRecord) -> AssetRecord:
        gateway = self._require_gateway()
        for row_number, existing_asset in self._load_sheet_rows():
            if existing_asset.asset_id == asset_id:
                record = gateway.update_row(self.mapper.sheet_name, row_number, self.mapper.asset_to_row(asset))
                return self.mapper.row_to_asset(record.values)
        raise AssetNotFoundError(asset_id)

    def delete_asset(self, asset_id: str, *, mode: DeleteMode = "archive") -> None:
        gateway = self._require_gateway()
        for row_number, existing_asset in self._load_sheet_rows():
            if existing_asset.asset_id != asset_id:
                continue
            if mode == "delete":
                gateway.delete_row(self.mapper.sheet_name, row_number)
                return
            archived_payload = {**existing_asset.to_dict(), "Status": "Deprecated"}
            archived_asset = build_asset_record(archived_payload)
            gateway.update_row(self.mapper.sheet_name, row_number, self.mapper.asset_to_row(archived_asset))
            return
        raise AssetNotFoundError(asset_id)

    def _load_sheet_rows(self) -> list[tuple[int, AssetRecord]]:
        gateway = self._require_gateway()
        return [
            (record.row_number, self.mapper.row_to_asset(record.values))
            for record in gateway.list_rows(self.mapper.sheet_name)
        ]

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
