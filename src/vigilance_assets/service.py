from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from .models import AssetRecord
from .repository import (
    AssetListQuery,
    AssetPage,
    AssetRepository,
    AssetSchemaView,
    DeleteMode,
)
from .validation import (
    AssetValidationSummary,
    AssetValidator,
    InventoryValidationReport,
    ValidationError,
    ValidationIssue,
)


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

    def get_vocabularies(self) -> Mapping[str, tuple[str, ...]]:
        return self.repository.get_vocabularies()

    def get_vocabulary(self, name: str) -> tuple[str, ...]:
        return self.repository.get_vocabulary(name)

    def get_asset_schema(self) -> AssetSchemaView:
        return self.repository.get_asset_schema()

    def get_category_schema(self, category: str) -> AssetSchemaView:
        return self.repository.get_category_schema(category)


    def get_asset_quality_report(self) -> InventoryValidationReport:
        inventory_payloads = self.repository.iter_inventory_payloads()
        duplicate_counts = Counter(
            payload.payload.get(self.repository.catalog.id_field)
            for payload in inventory_payloads
            if isinstance(payload.payload.get(self.repository.catalog.id_field), str)
        )
        duplicate_asset_ids = {asset_id for asset_id, count in duplicate_counts.items() if count > 1}

        issues = []
        asset_summaries: list[AssetValidationSummary] = []
        for inventory_payload in inventory_payloads:
            payload = dict(inventory_payload.payload)
            asset_issues = self.validator.audit_payload(
                payload,
                row_number=inventory_payload.row_number,
                duplicate_asset_ids=duplicate_asset_ids,
            )
            asset_id = payload.get(self.repository.catalog.id_field)
            category = payload.get("Asset_Category")
            asset_summaries.append(
                AssetValidationSummary(
                    asset_id=asset_id if isinstance(asset_id, str) else None,
                    category=category if isinstance(category, str) else None,
                    row_number=inventory_payload.row_number,
                    issue_count=len(asset_issues),
                )
            )
            issues.extend(asset_issues)

        return InventoryValidationReport(
            total_assets=len(inventory_payloads),
            assets_with_issues=sum(1 for asset in asset_summaries if asset.issue_count > 0),
            issue_count=len(issues),
            issues=tuple(issues),
            assets=tuple(asset_summaries),
        )

    def patch_asset(
        self,
        asset_id: str,
        payload: dict[str, Any],
        *,
        updated_by: str | None = None,
    ) -> AssetRecord:
        current = self.get_asset(asset_id)
        self._ensure_asset_id_is_not_mutated(asset_id, payload)
        category = payload.get("Asset_Category", current.category)
        self.validator.validate_for_patch(category, payload)
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
        self._ensure_asset_id_is_not_mutated(asset_id, payload)
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

    def _ensure_asset_id_is_not_mutated(self, asset_id: str, payload: dict[str, Any]) -> None:
        requested_asset_id = payload.get(self.repository.catalog.id_field)
        if requested_asset_id is None or requested_asset_id == asset_id:
            return
        raise ValidationError(
            [ValidationIssue(self.repository.catalog.id_field, "Asset_ID is immutable.", "immutable")]
        )
