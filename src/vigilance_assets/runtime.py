from __future__ import annotations

import logging

from .config import AppRuntimeSettings, load_runtime_settings
from .google_sheets import build_google_sheets_gateway
from .repository import SpreadsheetAssetRepository
from .sharepoint import build_sharepoint_gateway
from .spreadsheet import AssetSpreadsheetMapper


LOGGER = logging.getLogger(__name__)


def create_repository_from_settings(settings: AppRuntimeSettings) -> SpreadsheetAssetRepository:
    mapper = AssetSpreadsheetMapper()
    if settings.storage_backend == "google_sheets":
        google_settings = settings.google_sheets
        if google_settings is None:
            raise ValueError("Google Sheets settings are not configured.")
        gateway = build_google_sheets_gateway(google_settings, mapper.ordered_headers)
        repository = SpreadsheetAssetRepository(
            workbook_reference=google_settings.spreadsheet_id,
            gateway=gateway,
            read_only=gateway.is_read_only,
        )
        LOGGER.info(
            "Initialized spreadsheet repository for Google spreadsheet %s in %s mode.",
            google_settings.spreadsheet_id,
            google_settings.runtime_mode_label,
        )
        return repository

    if settings.storage_backend == "sharepoint":
        sharepoint_settings = settings.sharepoint
        if sharepoint_settings is None:
            raise ValueError("SharePoint settings are not configured.")
        gateway = build_sharepoint_gateway(sharepoint_settings, mapper.ordered_headers)
        workbook_reference = sharepoint_settings.item_id or sharepoint_settings.workbook_path or "sharepoint-workbook"
        repository = SpreadsheetAssetRepository(
            workbook_reference=workbook_reference,
            gateway=gateway,
            read_only=False,
        )
        LOGGER.info("Initialized spreadsheet repository for SharePoint workbook %s.", workbook_reference)
        return repository

    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")


def create_runtime_app():
    from .api import create_app

    settings = load_runtime_settings()
    repository = create_repository_from_settings(settings)
    app = create_app(repository=repository)
    app.config["RUNTIME_SETTINGS"] = settings
    app.config.setdefault("SWAGGER_UI_URL", "/docs")
    return app
