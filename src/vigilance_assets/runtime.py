from __future__ import annotations

from .config import AppRuntimeSettings, load_runtime_settings
from .google_sheets import build_google_sheets_gateway
from .repository import SpreadsheetAssetRepository
from .spreadsheet import AssetSpreadsheetMapper


def create_repository_from_settings(settings: AppRuntimeSettings) -> SpreadsheetAssetRepository:
    mapper = AssetSpreadsheetMapper()
    gateway = build_google_sheets_gateway(settings.google_sheets, mapper.ordered_headers)
    return SpreadsheetAssetRepository(
        workbook_reference=settings.google_sheets.spreadsheet_id,
        gateway=gateway,
    )


def create_runtime_app():
    from .api import create_app

    settings = load_runtime_settings()
    repository = create_repository_from_settings(settings)
    app = create_app(repository=repository)
    app.config["RUNTIME_SETTINGS"] = settings
    app.config.setdefault("SWAGGER_UI_URL", "/docs")
    return app
