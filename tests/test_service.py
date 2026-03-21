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
    AssetValidator,
    DuplicateAssetError,
    InventoryPayload,
    ValidationError,
)


class InMemoryAssetRepository(AssetRepository):
    def __init__(self) -> None:
        super().__init__()
        self._assets: dict[str, AssetRecord] = {}
        self.deleted: list[tuple[str, str]] = []

    def list_assets(self, query: AssetListQuery | None = None) -> AssetPage:
        items = tuple(self._assets.values())
        return AssetPage(items=items, total=len(items), page=1 if query is None else query.page, page_size=len(items) or 1)

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
            InventoryPayload(
                payload={
                    "Asset_ID": "AST-001",
                    "Asset_Name": "Threat Radar",
                    "Asset_Category": "Cybersecurity Tool",
                    "Owner_Org": "OpenAI Security Lab",
                    "Owner_Contact": "alice@example.org",
                    "Pilot_s": "Pilot A",
                    "Purpose": "Aggregates threat findings for analysts.",
                    "Status": "Active",
                    "TRL_Start": 4,
                    "TRL_Target": 7,
                    "Related_Result": "RS3",
                    "Related_WP_Task": "T5.3",
                    "Deployment_Context": "Cloud",
                    "Last_Updated": "2026-03-21T10:00:00",
                    "Updated_By": "alice@example.org",
                    "Tool_Type": "SIEM (Security Information and Event Management)",
                },
                row_number=2,
            ),
            InventoryPayload(
                payload={
                    "Asset_ID": "AST-001",
                    "Asset_Name": "Broken Radar",
                    "Asset_Category": "Cybersecurity Tool",
                    "Owner_Org": "",
                    "Owner_Contact": "alice@example.org",
                    "Pilot_s": "Pilot A",
                    "Purpose": "Broken row.",
                    "Status": "Unknown",
                    "TRL_Start": 0,
                    "TRL_Target": 7,
                    "Related_Result": "RS3",
                    "Related_WP_Task": "T5.3",
                    "Deployment_Context": "Cloud",
                    "Last_Updated": "bad-date",
                    "Updated_By": "alice@example.org",
                    "Tool_Type": "SIEM (Security Information and Event Management)",
                    "Service_Type": "Security Service",
                },
                row_number=3,
            ),
        )

    def delete_asset(self, asset_id: str, *, mode: str = "archive") -> None:
        if asset_id not in self._assets:
            raise AssetNotFoundError(asset_id)
        self.deleted.append((asset_id, mode))
        if mode == 'delete':
            del self._assets[asset_id]


class AssetServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryAssetRepository()
        self.service = AssetService(
            self.repository,
            AssetValidator(self.repository.catalog),
            now_provider=lambda: datetime(2026, 3, 21, 12, 30, tzinfo=timezone.utc),
        )
        self.base_payload = {
            "Asset_ID": "AST-001",
            "Asset_Name": "Threat Radar",
            "Asset_Category": "Cybersecurity Tool",
            "Owner_Org": "OpenAI Security Lab",
            "Owner_Contact": "alice@example.org",
            "Pilot_s": "Pilot A",
            "Purpose": "Aggregates threat findings for analysts.",
            "Status": "Active",
            "TRL_Start": 4,
            "TRL_Target": 7,
            "Related_Result": "RS3",
            "Related_WP_Task": "T5.3",
            "Deployment_Context": "Cloud",
            "Updated_By": "ignored-on-write@example.org",
            "Tool_Type": "SIEM (Security Information and Event Management)",
        }


    def test_get_asset_quality_report_includes_duplicate_and_schema_violations(self) -> None:
        report = self.service.get_asset_quality_report()

        self.assertEqual(report.total_assets, 2)
        self.assertEqual(report.assets_with_issues, 2)
        self.assertGreaterEqual(report.issue_count, 5)
        issue_codes = {(issue.row_number, issue.field, issue.code) for issue in report.issues}
        self.assertIn((2, 'Asset_ID', 'duplicate'), issue_codes)
        self.assertIn((3, 'Asset_ID', 'duplicate'), issue_codes)
        self.assertIn((3, 'Owner_Org', 'required'), issue_codes)
        self.assertIn((3, 'Status', 'invalid_choice'), issue_codes)
        self.assertIn((3, 'TRL_Start', 'out_of_range'), issue_codes)
        self.assertIn((3, 'Last_Updated', 'invalid_datetime'), issue_codes)
        self.assertIn((3, 'Service_Type', 'category_exclusive'), issue_codes)

    def test_create_asset_validates_and_stamps_metadata(self) -> None:
        asset = self.service.create_asset(self.base_payload, updated_by="service@example.org")

        self.assertEqual(asset.asset_id, "AST-001")
        self.assertEqual(asset.common.Updated_By, "service@example.org")
        self.assertEqual(asset.common.Last_Updated, datetime(2026, 3, 21, 12, 30, tzinfo=timezone.utc))

    def test_create_asset_rejects_duplicate_asset_id(self) -> None:
        self.service.create_asset(self.base_payload, updated_by="service@example.org")

        with self.assertRaises(ValidationError) as exc:
            self.service.create_asset(self.base_payload, updated_by="service@example.org")

        self.assertTrue(any(issue.code == "duplicate" for issue in exc.exception.issues))

    def test_get_asset_raises_not_found_for_unknown_id(self) -> None:
        with self.assertRaises(AssetNotFoundError):
            self.service.get_asset("missing")

    def test_patch_asset_merges_existing_record_and_enforces_category_validation(self) -> None:
        self.service.create_asset(self.base_payload, updated_by="creator@example.org")

        with self.assertRaises(ValidationError) as exc:
            self.service.patch_asset(
                "AST-001",
                {"Asset_Category": "Platform / Service"},
                updated_by="editor@example.org",
            )

        self.assertTrue(any(issue.field == "Service_Type" for issue in exc.exception.issues))
        self.assertTrue(any(issue.code == "category_exclusive" for issue in exc.exception.issues))

    def test_patch_asset_updates_existing_asset(self) -> None:
        self.service.create_asset(self.base_payload, updated_by="creator@example.org")

        updated = self.service.patch_asset(
            "AST-001",
            {"Status": "Deprecated", "Security_Function": "Monitor"},
            updated_by="editor@example.org",
        )

        self.assertEqual(updated.common.Status, "Deprecated")
        self.assertEqual(updated.category_fields.Security_Function, "Monitor")
        self.assertEqual(updated.common.Updated_By, "editor@example.org")


    def test_patch_asset_rejects_attempt_to_change_asset_id(self) -> None:
        self.service.create_asset(self.base_payload, updated_by="creator@example.org")

        with self.assertRaises(ValidationError) as exc:
            self.service.patch_asset(
                "AST-001",
                {"Asset_ID": "AST-999"},
                updated_by="editor@example.org",
            )

        self.assertTrue(any(issue.field == "Asset_ID" and issue.code == "immutable" for issue in exc.exception.issues))

    def test_replace_asset_rejects_attempt_to_change_asset_id(self) -> None:
        self.service.create_asset(self.base_payload, updated_by="creator@example.org")

        with self.assertRaises(ValidationError) as exc:
            self.service.replace_asset(
                "AST-001",
                {**self.base_payload, "Asset_ID": "AST-999"},
                updated_by="editor@example.org",
            )

        self.assertTrue(any(issue.field == "Asset_ID" and issue.code == "immutable" for issue in exc.exception.issues))

    def test_replace_asset_requires_complete_valid_payload(self) -> None:
        self.service.create_asset(self.base_payload, updated_by="creator@example.org")

        with self.assertRaises(ValidationError) as exc:
            self.service.replace_asset(
                "AST-001",
                {"Asset_Name": "Replacement", "Asset_Category": "Cybersecurity Tool"},
                updated_by="editor@example.org",
            )

        self.assertTrue(any(issue.field == "Owner_Org" and issue.code == "required" for issue in exc.exception.issues))

    def test_delete_asset_uses_archive_mode_by_default(self) -> None:
        self.service.create_asset(self.base_payload, updated_by="creator@example.org")

        self.service.delete_asset("AST-001")

        self.assertEqual(self.repository.deleted, [("AST-001", "archive")])


if __name__ == "__main__":
    unittest.main()
