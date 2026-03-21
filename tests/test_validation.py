from __future__ import annotations

from datetime import datetime, timezone
import unittest

from vigilance_assets import AssetValidator, ValidationError

from tests.fixtures import CATEGORY_SPECIFICS, asset_payload


class AssetValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = AssetValidator()

    def test_valid_asset_creation_per_category(self) -> None:
        for index, category in enumerate(CATEGORY_SPECIFICS, start=1):
            with self.subTest(category=category):
                asset = self.validator.validate_for_create(asset_payload(category, asset_id=f"AST-{index:03d}"))
                required_field = next(iter(CATEGORY_SPECIFICS[category]))
                self.assertEqual(asset.category, category)
                self.assertIsNotNone(getattr(asset.category_fields, required_field))
                self.assertEqual(asset.common.Last_Updated, datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc))

    def test_rejects_category_incompatible_fields(self) -> None:
        payload = asset_payload("Cybersecurity Tool", Service_Type="Security Service")
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_create(payload)
        self.assertTrue(any(issue.code == "category_exclusive" and issue.field == "Service_Type" for issue in exc.exception.issues))

    def test_rejects_invalid_vocabulary_values(self) -> None:
        payload = asset_payload("Platform / Service", Status="Running")
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_create(payload)
        self.assertTrue(any(issue.field == "Status" and issue.code == "invalid_choice" for issue in exc.exception.issues))

    def test_rejects_trl_out_of_range(self) -> None:
        payload = asset_payload("Compute Resource", TRL_Start=10)
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_create(payload)
        self.assertTrue(any(issue.field == "TRL_Start" and issue.code == "out_of_range" for issue in exc.exception.issues))

    def test_rejects_duplicate_asset_id(self) -> None:
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_create(asset_payload("Cybersecurity Tool", asset_id="AST-001"), existing_asset_ids={"AST-001"})
        self.assertTrue(any(issue.code == "duplicate" for issue in exc.exception.issues))

    def test_patch_validates_partial_payload_and_immutable_id(self) -> None:
        patch = {"Status": "Deprecated", "Asset_ID": "AST-999"}
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_patch("Cybersecurity Tool", patch)
        self.assertTrue(any(issue.code == "immutable" for issue in exc.exception.issues))

    def test_patch_rejects_invalid_category_specific_field_for_new_category(self) -> None:
        patch = {"Asset_Category": "Platform / Service", "Tool_Type": "SIEM (Security Information and Event Management)"}
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_patch("Platform / Service", patch)
        self.assertTrue(any(issue.field == "Tool_Type" and issue.code == "category_exclusive" for issue in exc.exception.issues))


if __name__ == "__main__":
    unittest.main()
