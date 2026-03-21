from __future__ import annotations

from datetime import datetime, timezone
import unittest

from vigilance_assets import (
    AssetListQuery,
    AssetNotFoundError,
    AssetPage,
    AssetRecord,
    AssetRepository,
    AssetService,
    AssetSort,
    AssetValidator,
    DuplicateAssetError,
    InventoryPayload,
    ValidationError,
    build_asset_record,
)

from tests.fixtures import asset_payload, canonical_assets, now_utc


class InMemoryAssetRepository(AssetRepository):
    def __init__(self) -> None:
        super().__init__()
        seed_assets = canonical_assets()
        seed_assets[0]["Asset_Name"] = "Threat Radar"
        seed_assets[0]["Purpose"] = "Aggregates threat findings for analysts."
        seed_assets[1]["Asset_Name"] = "Beacon"
        seed_assets[1]["Purpose"] = "Correlates detections across services."
        seed_assets[1]["Status"] = "Planned"
        self._assets: dict[str, AssetRecord] = {payload["Asset_ID"]: build_asset_record(payload) for payload in seed_assets[:2]}
        self.deleted: list[tuple[str, str]] = []
        self.last_query: AssetListQuery | None = None

    def list_assets(self, query: AssetListQuery | None = None) -> AssetPage:
        self.last_query = query
        query = query or AssetListQuery()
        items = list(self._assets.values())
        for field, expected in query.filters.items():
            if isinstance(expected, tuple):
                items = [asset for asset in items if asset.to_dict().get(field) in expected]
            else:
                items = [asset for asset in items if asset.to_dict().get(field) == expected]
        if query.search:
            needle = query.search.casefold()
            items = [asset for asset in items if any(needle in str(asset.to_dict().get(field, "")).casefold() for field in self.catalog.searchable_fields)]
        for sort in reversed(query.sort):
            items.sort(key=lambda asset, field=sort.field: asset.to_dict().get(field), reverse=sort.direction == "desc")
        total = len(items)
        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        return AssetPage(items=tuple(items[start:end]), total=total, page=query.page, page_size=query.page_size)

    def get_asset(self, asset_id: str) -> AssetRecord | None:
        return self._assets.get(asset_id)

    def create_asset(self, asset: AssetRecord) -> AssetRecord:
        if asset.asset_id in self._assets:
            raise DuplicateAssetError(asset.asset_id)
        self._assets[asset.asset_id] = asset
        return asset

    def update_asset(self, asset_id: str, asset: AssetRecord) -> AssetRecord:
        if asset_id not in self._assets:
            raise AssetNotFoundError(asset_id)
        self._assets[asset_id] = asset
        return asset

    def iter_inventory_payloads(self) -> tuple[InventoryPayload, ...]:
        return (
            InventoryPayload(payload=asset_payload("Cybersecurity Tool", asset_id="AST-001"), row_number=2),
            InventoryPayload(
                payload=asset_payload(
                    "Cybersecurity Tool",
                    asset_id="AST-001",
                    asset_name="Broken Radar",
                    Owner_Org="",
                    Status="Unknown",
                    TRL_Start=0,
                    Last_Updated="bad-date",
                    Service_Type="Security Service",
                ),
                row_number=3,
            ),
        )

    def delete_asset(self, asset_id: str, *, mode: str = "archive") -> None:
        if asset_id not in self._assets:
            raise AssetNotFoundError(asset_id)
        self.deleted.append((asset_id, mode))
        if mode == "delete":
            del self._assets[asset_id]


class AssetServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryAssetRepository()
        self.service = AssetService(
            self.repository,
            AssetValidator(self.repository.catalog),
            now_provider=now_utc,
        )
        self.base_payload = asset_payload("Cybersecurity Tool", asset_id="AST-999", Updated_By="ignored-on-write@example.org")

    def test_get_asset_quality_report_includes_duplicate_and_schema_violations(self) -> None:
        report = self.service.get_asset_quality_report()

        self.assertEqual(report.total_assets, 2)
        self.assertEqual(report.assets_with_issues, 2)
        self.assertGreaterEqual(report.issue_count, 5)
        issue_codes = {(issue.row_number, issue.field, issue.code) for issue in report.issues}
        self.assertIn((2, "Asset_ID", "duplicate"), issue_codes)
        self.assertIn((3, "Asset_ID", "duplicate"), issue_codes)
        self.assertIn((3, "Owner_Org", "required"), issue_codes)
        self.assertIn((3, "Status", "invalid_choice"), issue_codes)
        self.assertIn((3, "TRL_Start", "out_of_range"), issue_codes)
        self.assertIn((3, "Last_Updated", "invalid_datetime"), issue_codes)
        self.assertIn((3, "Service_Type", "category_exclusive"), issue_codes)

    def test_create_asset_validates_and_stamps_metadata(self) -> None:
        asset = self.service.create_asset(self.base_payload, updated_by="service@example.org")

        self.assertEqual(asset.asset_id, "AST-999")
        self.assertEqual(asset.common.Updated_By, "service@example.org")
        self.assertEqual(asset.common.Last_Updated, datetime(2026, 3, 21, 12, 30, tzinfo=timezone.utc))

    def test_create_asset_rejects_duplicate_asset_id(self) -> None:
        with self.assertRaises(ValidationError) as exc:
            self.service.create_asset(asset_payload("Cybersecurity Tool", asset_id="AST-001"), updated_by="service@example.org")
        self.assertTrue(any(issue.code == "duplicate" for issue in exc.exception.issues))

    def test_get_asset_raises_not_found_for_unknown_id(self) -> None:
        with self.assertRaises(AssetNotFoundError):
            self.service.get_asset("missing")

    def test_list_assets_delegates_filter_sort_pagination_and_search(self) -> None:
        query = AssetListQuery(
            filters={"Status": "Planned"},
            search="correlates",
            sort=(AssetSort(field="Asset_Name", direction="desc"),),
            page=1,
            page_size=1,
        )

        page = self.service.list_assets(query)

        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].asset_id, "AST-002")
        self.assertEqual(self.repository.last_query, query)

    def test_patch_asset_merges_existing_record_and_enforces_category_validation(self) -> None:
        with self.assertRaises(ValidationError) as exc:
            self.service.patch_asset(
                "AST-001",
                {"Asset_Category": "Platform / Service"},
                updated_by="editor@example.org",
            )
        self.assertTrue(any(issue.field == "Service_Type" for issue in exc.exception.issues))
        self.assertTrue(any(issue.code == "category_exclusive" for issue in exc.exception.issues))

    def test_patch_asset_updates_existing_asset(self) -> None:
        updated = self.service.patch_asset(
            "AST-001",
            {"Status": "Deprecated", "Security_Function": "Monitor"},
            updated_by="editor@example.org",
        )

        self.assertEqual(updated.common.Status, "Deprecated")
        self.assertEqual(updated.category_fields.Security_Function, "Monitor")
        self.assertEqual(updated.common.Updated_By, "editor@example.org")

    def test_patch_asset_rejects_attempt_to_change_asset_id(self) -> None:
        with self.assertRaises(ValidationError) as exc:
            self.service.patch_asset(
                "AST-001",
                {"Asset_ID": "AST-999"},
                updated_by="editor@example.org",
            )
        self.assertTrue(any(issue.field == "Asset_ID" and issue.code == "immutable" for issue in exc.exception.issues))

    def test_replace_asset_requires_complete_valid_payload(self) -> None:
        with self.assertRaises(ValidationError) as exc:
            self.service.replace_asset(
                "AST-001",
                {"Asset_Name": "Replacement", "Asset_Category": "Cybersecurity Tool"},
                updated_by="editor@example.org",
            )
        self.assertTrue(any(issue.field == "Owner_Org" and issue.code == "required" for issue in exc.exception.issues))

    def test_delete_asset_uses_archive_mode_by_default(self) -> None:
        self.service.delete_asset("AST-001")

        self.assertEqual(self.repository.deleted, [("AST-001", "archive")])


if __name__ == "__main__":
    unittest.main()
