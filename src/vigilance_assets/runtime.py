from __future__ import annotations

import logging

from .auth import configure_auth
from .config import AppRuntimeSettings, load_runtime_settings
from .google_sheets import build_google_sheets_gateway
from .repository import SpreadsheetAssetRepository
from .sharepoint import build_sharepoint_gateway
from .spreadsheet import AssetSpreadsheetMapper
from .token_acquisition import EntraOboTokenBroker, RequestScopedGraphTokenProvider


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
        if settings.auth_mode != "entra_obo" or settings.entra_obo is None:
            raise ValueError("SharePoint backend requires VIGILANCE_AUTH_MODE=entra_obo for delegated Graph access.")

        obo_broker = EntraOboTokenBroker(settings.entra_obo)
        graph_token_provider = RequestScopedGraphTokenProvider(obo_broker)
        gateway = build_sharepoint_gateway(
            sharepoint_settings,
            mapper.ordered_headers,
            graph_access_token_provider=graph_token_provider,
            validate_on_startup=False,
        )
        workbook_reference = sharepoint_settings.item_id or sharepoint_settings.workbook_path or "sharepoint-workbook"
        repository = SpreadsheetAssetRepository(
            workbook_reference=workbook_reference,
            gateway=gateway,
            read_only=False,
        )
        LOGGER.info(
            "Initialized spreadsheet repository for SharePoint workbook %s with delegated Graph access (OBO).",
            workbook_reference,
        )
        return repository

    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")


def create_runtime_app():
    from .api import create_app

    settings = load_runtime_settings()
    repository = create_repository_from_settings(settings)
    app = create_app(repository=repository)
    configure_auth(app, settings)
    app.config["RUNTIME_SETTINGS"] = settings
    app.config.setdefault("SWAGGER_UI_URL", "/docs")
    app.config["SWAGGER_USE_OAUTH"] = settings.swagger_use_oauth
    app.config["SWAGGER_ENTRA_TENANT_ID"] = settings.swagger_entra_tenant_id
    app.config["SWAGGER_CLIENT_ID"] = settings.swagger_client_id
    app.config["SWAGGER_API_SCOPE"] = settings.swagger_api_scope
    app.config["SWAGGER_OAUTH_SCOPES"] = settings.swagger_oauth_scopes
    app.config["SWAGGER_OAUTH_AUTHORIZATION_URL"] = settings.swagger_oauth_authorization_url
    app.config["SWAGGER_OAUTH_TOKEN_URL"] = settings.swagger_oauth_token_url

    LOGGER.info(
        "Startup mode: storage_backend=%s auth_mode=%s sharepoint_worksheet=%s",
        settings.storage_backend,
        settings.auth_mode,
        settings.sharepoint.worksheet_name if settings.sharepoint else "n/a",
    )
    return app
