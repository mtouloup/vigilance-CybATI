import unittest

from vigilance_assets import AssetRepository, SpreadsheetAssetRepository, UnsupportedCategoryError, UnsupportedVocabularyError


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


if __name__ == "__main__":
    unittest.main()
