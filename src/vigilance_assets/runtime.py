from __future__ import annotations

import logging

from .config import AppRuntimeSettings, load_runtime_settings
from .google_sheets import build_google_sheets_gateway
from .repository import SpreadsheetAssetRepository
from .spreadsheet import AssetSpreadsheetMapper


LOGGER = logging.getLogger(__name__)


def create_repository_from_settings(settings: AppRuntimeSettings) -> SpreadsheetAssetRepository:
    mapper = AssetSpreadsheetMapper()
    google_settings = settings.google_sheets
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


def create_runtime_app():
    from .api import create_app

    settings = load_runtime_settings()
    repository = create_repository_from_settings(settings)
    app = create_app(repository=repository)
    app.config["RUNTIME_SETTINGS"] = settings
    app.config.setdefault("SWAGGER_UI_URL", "/docs")
    return app
