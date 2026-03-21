from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Final, Mapping


ENV_PREFIX = "VIGILANCE_"
MEMORY_BACKEND: Final[str] = "memory"
FILE_BACKEND: Final[str] = "file"
GOOGLE_SHEETS_BACKEND: Final[str] = "google_sheets"
BACKEND_ALIASES: Final[dict[str, str]] = {
    "memory": MEMORY_BACKEND,
    "test": MEMORY_BACKEND,
    "in_memory": MEMORY_BACKEND,
    "file": FILE_BACKEND,
    "local": FILE_BACKEND,
    "workbook": FILE_BACKEND,
    "google_sheets": GOOGLE_SHEETS_BACKEND,
    "google": GOOGLE_SHEETS_BACKEND,
}
VALID_BACKENDS: Final[tuple[str, ...]] = (MEMORY_BACKEND, FILE_BACKEND, GOOGLE_SHEETS_BACKEND)
VALID_GOOGLE_SHEETS_MODES: Final[tuple[str, ...]] = ("auto", "read_only", "read_write")


class ConfigurationError(ValueError):
    """Raised when runtime configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class SheetNames:
    assets: str = "ASSETS"
    vocabularies: str = "VOCABULARIES"


@dataclass(frozen=True, slots=True)
class GoogleSheetsSettings:
    spreadsheet_id: str | None = None
    credentials_path: str | None = None
    credentials_json: str | None = None
    mode: str = "auto"


@dataclass(frozen=True, slots=True)
class FileBackendSettings:
    path: str | None = None
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class SpreadsheetBackendSettings:
    backend: str = MEMORY_BACKEND
    reference: str | None = None
    sheets: SheetNames = SheetNames()
    file: FileBackendSettings = FileBackendSettings()
    google_sheets: GoogleSheetsSettings = GoogleSheetsSettings()

    def validate(self) -> None:
        if self.backend not in VALID_BACKENDS:
            raise ConfigurationError(
                "VIGILANCE_SPREADSHEET_BACKEND must be one of: memory, file, google_sheets."
            )
        if self.backend == FILE_BACKEND and not self.file.path:
            raise ConfigurationError(
                "VIGILANCE_SPREADSHEET_FILE_PATH must be set when backend is file."
            )
        if self.backend == GOOGLE_SHEETS_BACKEND and not self.google_sheets.spreadsheet_id:
            raise ConfigurationError(
                "VIGILANCE_SPREADSHEET_GOOGLE_ID must be set when backend is google_sheets."
            )
        if self.google_sheets.mode not in VALID_GOOGLE_SHEETS_MODES:
            raise ConfigurationError(
                "VIGILANCE_GOOGLE_SHEETS_MODE must be one of: auto, read_only, read_write."
            )

    @property
    def workbook_reference(self) -> str:
        if self.reference:
            return self.reference
        if self.backend == GOOGLE_SHEETS_BACKEND:
            if self.google_sheets.spreadsheet_id is None:
                raise ConfigurationError("Missing Google Sheets spreadsheet id.")
            return self.google_sheets.spreadsheet_id
        if self.backend == FILE_BACKEND:
            if self.file.path is None:
                raise ConfigurationError("Missing file backend path.")
            return self.file.path
        return "in-memory"


@dataclass(frozen=True, slots=True)
class AppRuntimeSettings:
    spreadsheet: SpreadsheetBackendSettings = SpreadsheetBackendSettings()


def load_runtime_settings(env: Mapping[str, str] | None = None) -> AppRuntimeSettings:
    values = env if env is not None else os.environ
    backend = _normalize_backend(_read_str(values, "SPREADSHEET_BACKEND", default=MEMORY_BACKEND))
    settings = AppRuntimeSettings(
        spreadsheet=SpreadsheetBackendSettings(
            backend=backend,
            reference=_read_optional_str(values, "SPREADSHEET_REFERENCE"),
            sheets=SheetNames(
                assets=_read_str(values, "ASSETS_SHEET_NAME", default="ASSETS"),
                vocabularies=_read_str(values, "VOCABULARIES_SHEET_NAME", default="VOCABULARIES"),
            ),
            file=FileBackendSettings(
                path=_read_optional_str(values, "SPREADSHEET_FILE_PATH")
                or _read_optional_str(values, "SPREADSHEET_WORKBOOK_PATH"),
                read_only=_read_bool(values, "SPREADSHEET_FILE_READ_ONLY", default=None)
                if _has_any(values, "SPREADSHEET_FILE_READ_ONLY")
                else _read_bool(values, "SPREADSHEET_WORKBOOK_READ_ONLY", default=False),
            ),
            google_sheets=GoogleSheetsSettings(
                spreadsheet_id=_read_optional_str(values, "SPREADSHEET_GOOGLE_ID"),
                credentials_path=_read_optional_str(values, "GOOGLE_CREDENTIALS_PATH"),
                credentials_json=_read_optional_str(values, "GOOGLE_CREDENTIALS_JSON"),
                mode=_read_str(values, "GOOGLE_SHEETS_MODE", default="auto").lower(),
            ),
        )
    )
    settings.spreadsheet.validate()
    return settings


def _normalize_backend(value: str) -> str:
    normalized = value.strip().lower()
    try:
        return BACKEND_ALIASES[normalized]
    except KeyError as exc:
        raise ConfigurationError(
            "VIGILANCE_SPREADSHEET_BACKEND must be one of: memory, file, google_sheets."
        ) from exc


def _env_name(name: str) -> str:
    return f"{ENV_PREFIX}{name}"


def _has_any(env: Mapping[str, str], name: str) -> bool:
    return _env_name(name) in env


def _read_optional_str(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(_env_name(name))
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _read_str(env: Mapping[str, str], name: str, *, default: str) -> str:
    return _read_optional_str(env, name) or default


def _read_bool(env: Mapping[str, str], name: str, *, default: bool | None) -> bool:
    value = _read_optional_str(env, name)
    if value is None:
        if default is None:
            raise ConfigurationError(f"{_env_name(name)} must be set to a boolean value.")
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{_env_name(name)} must be a boolean value.")
