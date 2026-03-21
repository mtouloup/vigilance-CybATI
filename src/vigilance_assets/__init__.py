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
from .schema import AssetSchemaCatalog, load_schema_catalog
from .validation import AssetValidator, ValidationError, ValidationIssue

__all__ = [
    "AssetRecord",
    "AssetSchemaCatalog",
    "AssetValidator",
    "CategorySpecificFields",
    "CommonAssetFields",
    "ComputeResourceFields",
    "CybersecurityToolFields",
    "DataStoreFields",
    "DataStreamFields",
    "PhysicalAssetFields",
    "PlatformServiceFields",
    "ValidationError",
    "ValidationIssue",
    "build_asset_record",
    "load_schema_catalog",
]
