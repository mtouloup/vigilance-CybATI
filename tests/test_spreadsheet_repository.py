from __future__ import annotations

import unittest

from vigilance_assets import AssetListQuery, AssetSort, DuplicateAssetError, SpreadsheetAssetRepository
from vigilance_assets.spreadsheet import SheetRecord


class FakeSpreadsheetGateway:
    def __init__(self) -> None:
        self._rows = [
            SheetRecord(
                row_number=1,
                values={
                    "Tool_Type": "CYBERSECURITY TOOL–SPECIFIC FIELDS (if Asset_Category = Cybersecurity Tool)",
                    "Service_Type": "PLATFORM / SERVICE—SPECIFIC FIELDS (if Asset_Category = Platform / Service)",
                },
            ),
            SheetRecord(
                row_number=2,
                values={
                    "Asset_ID": "Asset_ID",
                    "Asset_Name": "Asset_Name",
                    "Asset_Category": "Asset_Category",
                },
            ),
            SheetRecord(row_number=3, values={}),
            SheetRecord(
                row_number=4,
                values={
                    "Asset_Name": "Missing discriminator row",
                    "Owner_Org": "OpenAI Security Lab",
                },
            ),
            SheetRecord(
                row_number=5,
                values={
                    "Asset_ID": "AST-001",
                    "Asset_Name": "Threat Radar",
                    "Asset_Category": "Cybersecurity Tool",
                    "Owner_Org": "OpenAI Security Lab",
                    "Owner_Contact": "alice@example.org",
                    "Pilot (s)": "Pilot A",
                    "Purpose (1-2 sentences)": "Aggregates threat findings for analysts.",
                    "Status": "Active",
                    "TRL_Start": "4",
                    "TRL_Target": 7,
                    "Related_Result": "RS3",
                    "Related_WP_Task": "T5.3",
                    "Deployment_Context": "Cloud",
                    "Security_Domain": "Cloud Security",
                    "Last_Updated": "2026-03-21T10:00:00+00:00",
                    "Updated_By": "alice@example.org",
                    "Tool_Type": "SIEM (Security Information and Event Management)",
                },
            ),
            SheetRecord(
                row_number=6,
                values={
                    "Asset_ID": "AST-003",
                    "Asset_Name": "Telemetry Lake",
                    "Asset_Category": "Platform / Service",
                    "Owner_Org": "Consortium Ops",
                    "Owner_Contact": "carol@example.org",
                    "Pilot (s)": "Pilot B",
                    "Purpose (1-2 sentences)": "Stores telemetry for reporting and analytics.",
                    "Status": "Planned",
                    "TRL_Start": 3,
                    "TRL_Target": 6,
                    "Related_Result": "RS4",
                    "Related_WP_Task": "T5.4",
                    "Deployment_Context": "Hybrid",
                    "Security_Domain": "Data Security",
                    "Last_Updated": "2026-03-20",
                    "Updated_By": "carol@example.org",
                    "Service_Type": "Data Management",
                },
            ),
        ]

    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        self.last_sheet_name = sheet_name
        return list(self._rows)

    def append_row(self, sheet_name: str, values: dict[str, object]) -> SheetRecord:
        record = SheetRecord(row_number=len(self._rows) + 2, values=values)
        self._rows.append(record)
        return record

    def update_row(self, sheet_name: str, row_number: int, values: dict[str, object]) -> SheetRecord:
        for index, record in enumerate(self._rows):
            if record.row_number == row_number:
                updated = SheetRecord(row_number=row_number, values=values)
                self._rows[index] = updated
                return updated
        raise AssertionError("row not found")

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        self._rows = [record for record in self._rows if record.row_number != row_number]


class SpreadsheetRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = FakeSpreadsheetGateway()
        self.repository = SpreadsheetAssetRepository("workbook.xlsx", gateway=self.gateway)

    def test_get_asset_maps_headers_to_domain_fields(self) -> None:
        asset = self.repository.get_asset("AST-001")

        assert asset is not None
        self.assertEqual(asset.common.Pilot_s, "Pilot A")
        self.assertEqual(asset.common.Purpose, "Aggregates threat findings for analysts.")
        self.assertEqual(asset.common.TRL_Start, 4)

    def test_list_assets_supports_filter_search_sort_and_pagination(self) -> None:
        created = self.repository.create_asset(
            self.repository.mapper.row_to_asset(
                {
                    "Asset_ID": "AST-002",
                    "Asset_Name": "Beacon",
                    "Asset_Category": "Cybersecurity Tool",
                    "Owner_Org": "OpenAI Security Lab",
                    "Owner_Contact": "bob@example.org",
                    "Pilot (s)": "Pilot B",
                    "Purpose (1-2 sentences)": "Monitors endpoint posture.",
                    "Status": "Deprecated",
                    "TRL_Start": 2,
                    "TRL_Target": 5,
                    "Related_Result": "RS4",
                    "Related_WP_Task": "T5.4",
                    "Deployment_Context": "IT",
                    "Security_Domain": "Endpoint Security",
                    "Last_Updated": "2026-03-22",
                    "Updated_By": "bob@example.org",
                    "Tool_Type": "EDR (Endpoint Detection and Response)",
                }
            )
        )
        self.assertEqual(created.asset_id, "AST-002")

        page = self.repository.list_assets(
            AssetListQuery(
                filters={
                    "Asset_Category": "Cybersecurity Tool",
                    "Owner_Org": "OpenAI Security Lab",
                    "Status": ("Active", "Deprecated"),
                    "Pilot_s": ("Pilot A", "Pilot B"),
                    "Deployment_Context": ("Cloud", "IT"),
                    "Security_Domain": ("Cloud Security", "Endpoint Security"),
                    "Related_WP_Task": ("T5.3", "T5.4"),
                },
                search="endpoint",
                sort=(AssetSort(field="Asset_Name", direction="desc"),),
                page=1,
                page_size=1,
            )
        )

        self.assertEqual(page.total, 1)
        self.assertEqual(page.page_size, 1)
        self.assertEqual(page.items[0].asset_id, "AST-002")

    def test_load_sheet_rows_skips_layout_artifacts_and_partial_rows(self) -> None:
        rows = self.repository._load_sheet_rows()

        self.assertEqual([row_number for row_number, _ in rows], [5, 6])
        self.assertEqual([asset.asset_id for _, asset in rows], ["AST-001", "AST-003"])

    def test_duplicate_check_get_asset_ignores_non_asset_rows_before_insert(self) -> None:
        asset = self.repository.mapper.row_to_asset(
            {
                "Asset_ID": "AST-001",
                "Asset_Name": "Threat Radar",
                "Asset_Category": "Cybersecurity Tool",
                "Owner_Org": "OpenAI Security Lab",
                "Owner_Contact": "alice@example.org",
                "Pilot (s)": "Pilot A",
                "Purpose (1-2 sentences)": "Aggregates threat findings for analysts.",
                "Status": "Active",
                "TRL_Start": 4,
                "TRL_Target": 7,
                "Related_Result": "RS3",
                "Related_WP_Task": "T5.3",
                "Deployment_Context": "Cloud",
                "Last_Updated": "2026-03-21",
                "Updated_By": "alice@example.org",
                "Tool_Type": "SIEM (Security Information and Event Management)",
            }
        )

        with self.assertRaisesRegex(DuplicateAssetError, "AST-001"):
            self.repository.create_asset(asset)

    def test_delete_asset_archives_by_default(self) -> None:
        self.repository.delete_asset('AST-001')

        asset = self.repository.get_asset('AST-001')
        assert asset is not None
        self.assertEqual(asset.common.Status, 'Deprecated')

    def test_delete_asset_can_physically_remove_row(self) -> None:
        self.repository.delete_asset('AST-001', mode='delete')

        self.assertIsNone(self.repository.get_asset('AST-001'))

    def test_asset_to_row_clears_non_category_columns(self) -> None:
        asset = self.repository.get_asset("AST-001")
        assert asset is not None

        row = self.repository.mapper.asset_to_row(asset)

        self.assertIn("Pilot (s)", row)
        self.assertIsNone(row["Service_Type"])
        self.assertEqual(row["Purpose (1-2 sentences)"], "Aggregates threat findings for analysts.")


if __name__ == "__main__":
    unittest.main()
