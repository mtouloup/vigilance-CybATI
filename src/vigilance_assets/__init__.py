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
    InventoryPayload,
    AssetSchemaView,
    AssetSort,
    AssetNotFoundError,
    DuplicateAssetError,
    SpreadsheetAssetRepository,
    UnsupportedCategoryError,
    UnsupportedVocabularyError,
)
from .schema import AssetSchemaCatalog, load_schema_catalog
from .api import create_app
from .service import AssetService
from .spreadsheet import ASSETS_SHEET_NAME, AssetSpreadsheetMapper, SheetRecord, SpreadsheetBackendError, SpreadsheetTableGateway
from .validation import (
    AssetValidationSummary,
    AssetValidator,
    InventoryValidationIssue,
    InventoryValidationReport,
    ValidationError,
    ValidationIssue,
)

__all__ = [
    "AssetListQuery",
    "AssetNotFoundError",
    "AssetPage",
    "AssetRecord",
    "AssetRepository",
    "InventoryPayload",
    "AssetSchemaView",
    "AssetSort",
    "AssetSchemaCatalog",
    "AssetService",
    "create_app",
    "ASSETS_SHEET_NAME",
    "AssetSpreadsheetMapper",
    "AssetValidationSummary",
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
    "SpreadsheetBackendError",
    "SpreadsheetTableGateway",
    "SheetRecord",
    "UnsupportedCategoryError",
    "UnsupportedVocabularyError",
    "InventoryValidationIssue",
    "InventoryValidationReport",
    "ValidationError",
    "ValidationIssue",
    "build_asset_record",
    "load_schema_catalog",
]
