from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


ENV_PREFIX = "VIGILANCE_"
DEFAULT_ASSETS_WORKSHEET = "ASSETS"


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
class AppRuntimeSettings:
    google_sheets: GoogleSheetsSettings

    def validate(self) -> None:
        self.google_sheets.validate()


def load_runtime_settings(env: Mapping[str, str] | None = None) -> AppRuntimeSettings:
    values = env if env is not None else os.environ
    settings = AppRuntimeSettings(
        google_sheets=GoogleSheetsSettings(
            spreadsheet_id=_read_optional_str(values, "GOOGLE_SPREADSHEET_ID") or "",
            worksheet_name=_read_str(values, "GOOGLE_WORKSHEET_NAME", default=DEFAULT_ASSETS_WORKSHEET),
            service_account_file=_read_optional_str(values, "GOOGLE_SERVICE_ACCOUNT_FILE"),
            service_account_json=_read_optional_str(values, "GOOGLE_SERVICE_ACCOUNT_JSON"),
            read_only_public_fallback=_read_bool(values, "GOOGLE_READ_ONLY_PUBLIC", default=False),
        )
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
