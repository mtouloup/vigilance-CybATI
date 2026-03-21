from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

from .models import AssetRecord
from .schema import AssetSchemaCatalog, FieldDefinition, load_schema_catalog

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
    """Placeholder spreadsheet-backed repository.

    This stub exists so application services can depend on the intended
    repository type today while Google Sheets or workbook access is deferred to
    a later implementation.
    """

    def __init__(self, workbook_reference: str, catalog: AssetSchemaCatalog | None = None) -> None:
        super().__init__(catalog=catalog)
        self.workbook_reference = workbook_reference

    def list_assets(self, query: AssetListQuery | None = None) -> AssetPage:
        raise NotImplementedError("Spreadsheet asset access is not implemented yet.")

    def get_asset(self, asset_id: str) -> AssetRecord | None:
        raise NotImplementedError("Spreadsheet asset access is not implemented yet.")

    def create_asset(self, asset: AssetRecord) -> AssetRecord:
        raise NotImplementedError("Spreadsheet asset access is not implemented yet.")

    def update_asset(self, asset_id: str, asset: AssetRecord) -> AssetRecord:
        raise NotImplementedError("Spreadsheet asset access is not implemented yet.")

    def delete_asset(self, asset_id: str, *, mode: DeleteMode = "archive") -> None:
        raise NotImplementedError("Spreadsheet asset access is not implemented yet.")
