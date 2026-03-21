from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .models import AssetRecord
from .repository import (
    AssetPage,
    AssetRepository,
    DeleteMode,
)
from .validation import AssetValidator


class AssetService:
    """Application service orchestrating validation and repository access."""

    def __init__(
        self,
        repository: AssetRepository,
        validator: AssetValidator | None = None,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.validator = validator or AssetValidator(repository.catalog)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def create_asset(self, payload: dict[str, Any], *, updated_by: str | None = None) -> AssetRecord:
        prepared_payload = self._prepare_mutation_payload(payload, updated_by=updated_by)
        existing_asset_id = prepared_payload.get(self.repository.catalog.id_field)
        existing_ids = (
            {existing_asset_id}
            if isinstance(existing_asset_id, str) and self.repository.get_asset(existing_asset_id) is not None
            else set()
        )
        asset = self.validator.validate_for_create(prepared_payload, existing_asset_ids=existing_ids)
        return self.repository.create_asset(asset)

    def get_asset(self, asset_id: str) -> AssetRecord:
        asset = self.repository.get_asset(asset_id)
        if asset is None:
            from .repository import AssetNotFoundError

            raise AssetNotFoundError(f"Asset not found: {asset_id}")
        return asset

    def list_assets(self, query: AssetListQuery | None = None) -> AssetPage:
        return self.repository.list_assets(query)

    def patch_asset(
        self,
        asset_id: str,
        payload: dict[str, Any],
        *,
        updated_by: str | None = None,
    ) -> AssetRecord:
        current = self.get_asset(asset_id)
        merged_payload = {**current.to_dict(), **payload, self.repository.catalog.id_field: asset_id}
        prepared_payload = self._prepare_mutation_payload(merged_payload, updated_by=updated_by)
        asset = self.validator.validate_for_replace(prepared_payload, expected_asset_id=asset_id)
        return self.repository.update_asset(asset_id, asset)

    def replace_asset(
        self,
        asset_id: str,
        payload: dict[str, Any],
        *,
        updated_by: str | None = None,
    ) -> AssetRecord:
        self.get_asset(asset_id)
        replacement_payload = {**payload, self.repository.catalog.id_field: asset_id}
        prepared_payload = self._prepare_mutation_payload(replacement_payload, updated_by=updated_by)
        asset = self.validator.validate_for_replace(prepared_payload, expected_asset_id=asset_id)
        return self.repository.update_asset(asset_id, asset)

    def delete_asset(self, asset_id: str, *, mode: DeleteMode = "archive") -> None:
        self.get_asset(asset_id)
        self.repository.delete_asset(asset_id, mode=mode)

    def archive_asset(self, asset_id: str) -> None:
        self.delete_asset(asset_id, mode="archive")

    def _prepare_mutation_payload(
        self,
        payload: dict[str, Any],
        *,
        updated_by: str | None,
    ) -> dict[str, Any]:
        prepared = dict(payload)
        prepared["Last_Updated"] = self._now_provider()
        if updated_by is not None:
            prepared["Updated_By"] = updated_by
        return prepared
