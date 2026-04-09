from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Literal, Mapping


ENV_PREFIX = "VIGILANCE_"
DEFAULT_ASSETS_WORKSHEET = "ASSETS"
DEFAULT_STORAGE_BACKEND = "google_sheets"
DEFAULT_AUTH_MODE = "none"
DEFAULT_GRAPH_SCOPES = "https://graph.microsoft.com/.default"
DEFAULT_API_SCOPES = ""
DEFAULT_AUTH_PUBLIC_PATHS = ("/docs", "/openapi.json", "/swagger.json", "/health", "/swaggerui")
DEFAULT_SWAGGER_USE_OAUTH = False


class ConfigurationError(ValueError):
    """Raised when runtime configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class GoogleSheetsSettings:
    spreadsheet_id: str
    worksheet_name: str = DEFAULT_ASSETS_WORKSHEET
    service_account_file: str | None = None
    service_account_json: str | None = None
    read_only_public_fallback: bool = False

    @property
    def runtime_mode_label(self) -> str:
        return "public-read-only" if self.read_only_public_fallback else "authenticated-read-write"

    def validate(self) -> None:
        if not self.spreadsheet_id:
            raise ConfigurationError("VIGILANCE_GOOGLE_SPREADSHEET_ID must be set.")
        if not self.worksheet_name:
            raise ConfigurationError("VIGILANCE_GOOGLE_WORKSHEET_NAME must be set.")
        if self.read_only_public_fallback:
            return
        if self.service_account_file and self.service_account_json:
            raise ConfigurationError(
                "Set only one of VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE or VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON."
            )
        if not self.service_account_file and not self.service_account_json:
            raise ConfigurationError(
                "Authenticated Google Sheets access requires VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE or "
                "VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON, unless VIGILANCE_GOOGLE_READ_ONLY_PUBLIC is enabled."
            )


@dataclass(frozen=True, slots=True)
class SharePointSettings:
    worksheet_name: str = DEFAULT_ASSETS_WORKSHEET
    site_id: str | None = None
    site_url: str | None = None
    drive_id: str | None = None
    item_id: str | None = None
    workbook_path: str | None = None

    def validate(self) -> None:
        if not self.worksheet_name:
            raise ConfigurationError("VIGILANCE_SHAREPOINT_WORKSHEET_NAME must be set.")
        if not self.site_id and not self.site_url:
            raise ConfigurationError("Set either VIGILANCE_SHAREPOINT_SITE_ID or VIGILANCE_SHAREPOINT_SITE_URL.")
        if self.site_id and self.site_url:
            raise ConfigurationError("Set only one of VIGILANCE_SHAREPOINT_SITE_ID or VIGILANCE_SHAREPOINT_SITE_URL.")
        if not self.item_id and not self.workbook_path:
            raise ConfigurationError("Set either VIGILANCE_SHAREPOINT_ITEM_ID or VIGILANCE_SHAREPOINT_WORKBOOK_PATH.")
        if self.item_id and self.workbook_path:
            raise ConfigurationError("Set only one of VIGILANCE_SHAREPOINT_ITEM_ID or VIGILANCE_SHAREPOINT_WORKBOOK_PATH.")


@dataclass(frozen=True, slots=True)
class EntraOboSettings:
    tenant_id: str
    client_id: str
    client_secret: str
    api_audience: str
    graph_scopes: tuple[str, ...] = (DEFAULT_GRAPH_SCOPES,)

    def validate(self) -> None:
        if not self.tenant_id:
            raise ConfigurationError("VIGILANCE_ENTRA_TENANT_ID must be set.")
        if not self.client_id:
            raise ConfigurationError("VIGILANCE_ENTRA_CLIENT_ID must be set.")
        if not self.client_secret:
            raise ConfigurationError("VIGILANCE_ENTRA_CLIENT_SECRET must be set.")
        if not self.api_audience:
            raise ConfigurationError("VIGILANCE_ENTRA_API_AUDIENCE must be set.")
        if not self.graph_scopes:
            raise ConfigurationError("VIGILANCE_GRAPH_SCOPES must include at least one scope.")


@dataclass(frozen=True, slots=True)
class AppRuntimeSettings:
    storage_backend: Literal["google_sheets", "sharepoint"] = DEFAULT_STORAGE_BACKEND
    auth_mode: Literal["none", "entra_obo"] = DEFAULT_AUTH_MODE
    google_sheets: GoogleSheetsSettings | None = None
    sharepoint: SharePointSettings | None = None
    entra_obo: EntraOboSettings | None = None
    auth_public_paths: tuple[str, ...] = DEFAULT_AUTH_PUBLIC_PATHS
    swagger_use_oauth: bool = DEFAULT_SWAGGER_USE_OAUTH
    swagger_entra_tenant_id: str | None = None
    swagger_entra_client_id: str | None = None
    swagger_entra_api_scope: str | None = None
    swagger_oauth_authorization_url: str | None = None
    swagger_oauth_token_url: str | None = None
    swagger_oauth_scopes: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.storage_backend == "google_sheets":
            if self.google_sheets is None:
                raise ConfigurationError("Google Sheets backend selected but Google settings are not configured.")
            self.google_sheets.validate()
        elif self.storage_backend == "sharepoint":
            if self.sharepoint is None:
                raise ConfigurationError("SharePoint backend selected but SharePoint settings are not configured.")
            self.sharepoint.validate()
        else:
            raise ConfigurationError(
                f"Unsupported VIGILANCE_STORAGE_BACKEND value: {self.storage_backend}. "
                "Supported values: google_sheets, sharepoint."
            )

        if self.auth_mode == "none":
            return
        if self.auth_mode == "entra_obo":
            if self.entra_obo is None:
                raise ConfigurationError("Entra OBO auth mode selected but Entra settings are not configured.")
            self.entra_obo.validate()
            return
        raise ConfigurationError(
            f"Unsupported VIGILANCE_AUTH_MODE value: {self.auth_mode}. Supported values: none, entra_obo."
        )


def load_runtime_settings(env: Mapping[str, str] | None = None) -> AppRuntimeSettings:
    values = env if env is not None else os.environ
    storage_backend = _read_str(values, "STORAGE_BACKEND", default=DEFAULT_STORAGE_BACKEND).lower()
    auth_mode = _read_str(values, "AUTH_MODE", default=DEFAULT_AUTH_MODE).lower()
    settings = AppRuntimeSettings(
        storage_backend=storage_backend,  # type: ignore[arg-type]
        auth_mode=auth_mode,  # type: ignore[arg-type]
        google_sheets=GoogleSheetsSettings(
            spreadsheet_id=_read_optional_str(values, "GOOGLE_SPREADSHEET_ID") or "",
            worksheet_name=_read_str(values, "GOOGLE_WORKSHEET_NAME", default=DEFAULT_ASSETS_WORKSHEET),
            service_account_file=_read_optional_str(values, "GOOGLE_SERVICE_ACCOUNT_FILE"),
            service_account_json=_read_optional_str(values, "GOOGLE_SERVICE_ACCOUNT_JSON"),
            read_only_public_fallback=_read_bool(values, "GOOGLE_READ_ONLY_PUBLIC", default=False),
        ),
        sharepoint=SharePointSettings(
            worksheet_name=_read_str(values, "SHAREPOINT_WORKSHEET_NAME", default=DEFAULT_ASSETS_WORKSHEET),
            site_id=_read_optional_str(values, "SHAREPOINT_SITE_ID"),
            site_url=_read_optional_str(values, "SHAREPOINT_SITE_URL"),
            drive_id=_read_optional_str(values, "SHAREPOINT_DRIVE_ID"),
            item_id=_read_optional_str(values, "SHAREPOINT_ITEM_ID"),
            workbook_path=_read_optional_str(values, "SHAREPOINT_WORKBOOK_PATH"),
        ),
        entra_obo=EntraOboSettings(
            tenant_id=_read_optional_str(values, "ENTRA_TENANT_ID") or "",
            client_id=_read_optional_str(values, "ENTRA_CLIENT_ID") or "",
            client_secret=_read_optional_str(values, "ENTRA_CLIENT_SECRET") or "",
            api_audience=_read_optional_str(values, "ENTRA_API_AUDIENCE") or "",
            graph_scopes=_read_scopes(values),
        ),
        auth_public_paths=_read_auth_public_paths(values),
        swagger_use_oauth=_read_bool(values, "SWAGGER_USE_OAUTH", default=DEFAULT_SWAGGER_USE_OAUTH),
        swagger_entra_tenant_id=_read_optional_str(values, "ENTRA_TENANT_ID"),
        swagger_entra_client_id=_read_optional_str(values, "ENTRA_CLIENT_ID"),
        swagger_entra_api_scope=_read_optional_str(values, "ENTRA_API_SCOPE"),
        swagger_oauth_authorization_url=_read_optional_str(values, "ENTRA_AUTHORIZATION_URL"),
        swagger_oauth_token_url=_read_optional_str(values, "ENTRA_TOKEN_URL"),
        swagger_oauth_scopes=_read_api_scopes(values),
    )
    settings.validate()
    return settings


def _env_name(name: str) -> str:
    return f"{ENV_PREFIX}{name}"


def _read_optional_str(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(_env_name(name))
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _read_str(env: Mapping[str, str], name: str, *, default: str) -> str:
    return _read_optional_str(env, name) or default


def _read_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = _read_optional_str(env, name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _read_scopes(env: Mapping[str, str]) -> tuple[str, ...]:
    raw_value = _read_str(env, "GRAPH_SCOPES", default=DEFAULT_GRAPH_SCOPES)
    scopes = tuple(part.strip() for part in raw_value.split() if part.strip())
    return scopes or (DEFAULT_GRAPH_SCOPES,)


def _read_auth_public_paths(env: Mapping[str, str]) -> tuple[str, ...]:
    raw_value = _read_optional_str(env, "AUTH_PUBLIC_PATHS")
    if raw_value is None:
        return DEFAULT_AUTH_PUBLIC_PATHS
    paths = tuple(part.strip() for part in raw_value.split(",") if part.strip())
    return paths or DEFAULT_AUTH_PUBLIC_PATHS


def _read_api_scopes(env: Mapping[str, str]) -> tuple[str, ...]:
    raw_value = _read_optional_str(env, "ENTRA_API_SCOPE")
    if raw_value is None:
        raw_value = _read_str(env, "ENTRA_API_SCOPES", default=DEFAULT_API_SCOPES)
    scopes = tuple(part.strip() for part in raw_value.replace(",", " ").split() if part.strip())
    return scopes
