from __future__ import annotations

import unittest

from vigilance_assets import AssetListQuery, AssetRepository, SpreadsheetAssetRepository, UnsupportedCategoryError, UnsupportedVocabularyError, build_asset_record

from tests.fixtures import asset_payload, canonical_assets


class RepositoryDouble(AssetRepository):
    def __init__(self) -> None:
        super().__init__()
        self._assets = {payload["Asset_ID"]: build_asset_record(payload) for payload in canonical_assets()[:2]}

    def list_assets(self, query: AssetListQuery | None = None):
        query = query or AssetListQuery()
        items = tuple(self._assets.values())
        return __import__("vigilance_assets").AssetPage(items=items, total=len(items), page=query.page, page_size=query.page_size)

    def get_asset(self, asset_id: str):
        return self._assets.get(asset_id)

    def create_asset(self, asset):
        self._assets[asset.asset_id] = asset
        return asset

    def update_asset(self, asset_id: str, asset):
        self._assets[asset_id] = asset
        return asset

    def delete_asset(self, asset_id: str, *, mode: str = "archive") -> None:
        self._assets.pop(asset_id, None)


class RepositoryInterfaceTests(unittest.TestCase):
    def test_schema_view_exposes_canonical_metadata(self) -> None:
        repository = SpreadsheetAssetRepository("workbook.xlsx")
        schema_view = repository.get_asset_schema()
        self.assertEqual(schema_view.id_field, "Asset_ID")
        self.assertIn("Cybersecurity Tool", schema_view.category_fields)
        self.assertIn("Status", schema_view.vocabularies)

    def test_category_schema_rejects_unknown_category(self) -> None:
        repository = SpreadsheetAssetRepository("workbook.xlsx")
        with self.assertRaises(UnsupportedCategoryError):
            repository.get_category_schema("Unknown")

    def test_vocabulary_lookup_rejects_unknown_name(self) -> None:
        repository = SpreadsheetAssetRepository("workbook.xlsx")
        with self.assertRaises(UnsupportedVocabularyError):
            repository.get_vocabulary("Unknown")

    def test_spreadsheet_repository_is_repository_subclass(self) -> None:
        self.assertTrue(issubclass(SpreadsheetAssetRepository, AssetRepository))

    def test_iter_inventory_payloads_uses_domain_records(self) -> None:
        repository = RepositoryDouble()

        payloads = repository.iter_inventory_payloads()

        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0].payload["Asset_ID"], "AST-001")
        self.assertIsNone(payloads[0].row_number)

    def test_repository_schema_helpers_return_filtered_category_view(self) -> None:
        repository = RepositoryDouble()

        schema = repository.get_category_schema("Platform / Service")

        self.assertEqual(list(schema.category_fields), ["Platform / Service"])
        self.assertTrue(any(field.name == "Service_Type" for field in schema.category_fields["Platform / Service"]))


if __name__ == "__main__":
    unittest.main()
