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
    credentials_path: str | None = None
    credentials_json: str | None = None

    def validate(self) -> None:
        if not self.spreadsheet_id:
            raise ConfigurationError("VIGILANCE_GOOGLE_SPREADSHEET_ID must be set.")
        if not self.worksheet_name:
            raise ConfigurationError("VIGILANCE_GOOGLE_WORKSHEET_NAME must be set.")
        if not self.credentials_path and not self.credentials_json:
            raise ConfigurationError(
                "Provide Google service account credentials via "
                "VIGILANCE_GOOGLE_CREDENTIALS_PATH or VIGILANCE_GOOGLE_CREDENTIALS_JSON."
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
            spreadsheet_id=_read_required_str(values, "GOOGLE_SPREADSHEET_ID"),
            worksheet_name=_read_str(values, "GOOGLE_WORKSHEET_NAME", default=DEFAULT_ASSETS_WORKSHEET),
            credentials_path=_read_optional_str(values, "GOOGLE_CREDENTIALS_PATH"),
            credentials_json=_read_optional_str(values, "GOOGLE_CREDENTIALS_JSON"),
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


def _read_required_str(env: Mapping[str, str], name: str) -> str:
    value = _read_optional_str(env, name)
    if value is None:
        raise ConfigurationError(f"{_env_name(name)} must be set.")
    return value


def _read_str(env: Mapping[str, str], name: str, *, default: str) -> str:
    return _read_optional_str(env, name) or default
