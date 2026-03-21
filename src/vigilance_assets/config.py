from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


ENV_PREFIX = "VIGILANCE_"


class ConfigurationError(ValueError):
    """Raised when runtime configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class GoogleSheetsSettings:
    spreadsheet_id: str | None = None
    credentials_path: str | None = None
    credentials_json: str | None = None
    assets_sheet_name: str = "ASSETS"
    vocabularies_sheet_name: str = "VOCABULARIES"


@dataclass(frozen=True, slots=True)
class WorkbookSettings:
    path: str | None = None
    assets_sheet_name: str = "ASSETS"
    vocabularies_sheet_name: str = "VOCABULARIES"
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class SpreadsheetBackendSettings:
    backend: str = "memory"
    workbook_reference: str | None = None
    google_sheets: GoogleSheetsSettings = GoogleSheetsSettings()
    workbook: WorkbookSettings = WorkbookSettings()

    def validate(self) -> None:
        if self.backend == "google_sheets" and not self.google_sheets.spreadsheet_id:
            raise ConfigurationError(
                "VIGILANCE_SPREADSHEET_GOOGLE_ID must be set when backend is google_sheets."
            )
        if self.backend == "workbook" and not self.workbook.path:
            raise ConfigurationError(
                "VIGILANCE_SPREADSHEET_WORKBOOK_PATH must be set when backend is workbook."
            )

    @property
    def resolved_workbook_reference(self) -> str:
        if self.workbook_reference:
            return self.workbook_reference
        if self.backend == "google_sheets":
            if self.google_sheets.spreadsheet_id is None:
                raise ConfigurationError("Missing Google Sheets spreadsheet id.")
            return self.google_sheets.spreadsheet_id
        if self.backend == "workbook":
            if self.workbook.path is None:
                raise ConfigurationError("Missing workbook path.")
            return self.workbook.path
        return "in-memory"


@dataclass(frozen=True, slots=True)
class AppRuntimeSettings:
    spreadsheet: SpreadsheetBackendSettings = SpreadsheetBackendSettings()


def load_runtime_settings(env: Mapping[str, str] | None = None) -> AppRuntimeSettings:
    values = env if env is not None else os.environ
    backend = _read_str(values, "SPREADSHEET_BACKEND", default="memory").lower()
    if backend not in {"memory", "google_sheets", "workbook"}:
        raise ConfigurationError(
            "VIGILANCE_SPREADSHEET_BACKEND must be one of: memory, google_sheets, workbook."
        )

    settings = AppRuntimeSettings(
        spreadsheet=SpreadsheetBackendSettings(
            backend=backend,
            workbook_reference=_read_optional_str(values, "SPREADSHEET_REFERENCE"),
            google_sheets=GoogleSheetsSettings(
                spreadsheet_id=_read_optional_str(values, "SPREADSHEET_GOOGLE_ID"),
                credentials_path=_read_optional_str(values, "GOOGLE_CREDENTIALS_PATH"),
                credentials_json=_read_optional_str(values, "GOOGLE_CREDENTIALS_JSON"),
                assets_sheet_name=_read_str(values, "ASSETS_SHEET_NAME", default="ASSETS"),
                vocabularies_sheet_name=_read_str(values, "VOCABULARIES_SHEET_NAME", default="VOCABULARIES"),
            ),
            workbook=WorkbookSettings(
                path=_read_optional_str(values, "SPREADSHEET_WORKBOOK_PATH"),
                assets_sheet_name=_read_str(values, "ASSETS_SHEET_NAME", default="ASSETS"),
                vocabularies_sheet_name=_read_str(values, "VOCABULARIES_SHEET_NAME", default="VOCABULARIES"),
                read_only=_read_bool(values, "SPREADSHEET_WORKBOOK_READ_ONLY", default=False),
            ),
        )
    )
    settings.spreadsheet.validate()
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
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{_env_name(name)} must be a boolean value.")
