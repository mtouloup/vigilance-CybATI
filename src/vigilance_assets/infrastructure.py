from __future__ import annotations

from collections.abc import Mapping

from .config import AppRuntimeSettings, load_runtime_settings
from .repository import SpreadsheetAssetRepository
from .runtime import create_repository_from_settings


def build_spreadsheet_repository(
    settings: AppRuntimeSettings | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> SpreadsheetAssetRepository:
    """Build a spreadsheet repository from runtime settings."""

    resolved_settings = settings or load_runtime_settings(env)
    return create_repository_from_settings(resolved_settings)
