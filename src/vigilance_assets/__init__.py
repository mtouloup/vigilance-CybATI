"""Domain models and validators for the VIGILANCE asset inventory service."""

from .models import (
    AssetRecord,
    CommonAssetFields,
    CategorySpecificFields,
    CybersecurityToolFields,
    PlatformServiceFields,
    ComputeResourceFields,
    DataStreamFields,
    DataStoreFields,
    PhysicalAssetFields,
    build_asset_record,
)
from .repository import (
    AssetListQuery,
    AssetPage,
    AssetRepository,
    AssetSchemaView,
    AssetSort,
    AssetNotFoundError,
    DuplicateAssetError,
    SpreadsheetAssetRepository,
    UnsupportedCategoryError,
    UnsupportedVocabularyError,
)
from .schema import AssetSchemaCatalog, load_schema_catalog
from .service import AssetService
from .validation import AssetValidator, ValidationError, ValidationIssue

__all__ = [
    "AssetListQuery",
    "AssetNotFoundError",
    "AssetPage",
    "AssetRecord",
    "AssetRepository",
    "AssetSchemaView",
    "AssetSort",
    "AssetSchemaCatalog",
    "AssetService",
    "AssetValidator",
    "CategorySpecificFields",
    "CommonAssetFields",
    "ComputeResourceFields",
    "CybersecurityToolFields",
    "DuplicateAssetError",
    "DataStoreFields",
    "DataStreamFields",
    "PhysicalAssetFields",
    "PlatformServiceFields",
    "SpreadsheetAssetRepository",
    "UnsupportedCategoryError",
    "UnsupportedVocabularyError",
    "ValidationError",
    "ValidationIssue",
    "build_asset_record",
    "load_schema_catalog",
]
