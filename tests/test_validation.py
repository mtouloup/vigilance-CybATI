from datetime import datetime
import unittest

from vigilance_assets import AssetValidator, ValidationError


class AssetValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = AssetValidator()
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
            "Last_Updated": "2026-03-21T10:00:00",
            "Updated_By": "alice@example.org",
            "Tool_Type": "SIEM (Security Information and Event Management)",
        }

    def test_valid_asset_creation_per_category(self) -> None:
        asset = self.validator.validate_for_create(self.base_payload)
        self.assertEqual(asset.common.Asset_ID, "AST-001")
        self.assertEqual(asset.category_fields.Tool_Type, "SIEM (Security Information and Event Management)")
        self.assertEqual(asset.common.Last_Updated, datetime.fromisoformat("2026-03-21T10:00:00").replace(tzinfo=asset.common.Last_Updated.tzinfo))

    def test_rejects_category_incompatible_fields(self) -> None:
        payload = {**self.base_payload, "Service_Type": "Security Service"}
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_create(payload)
        self.assertTrue(any(issue.code == "category_exclusive" for issue in exc.exception.issues))

    def test_rejects_invalid_vocabulary_values(self) -> None:
        payload = {**self.base_payload, "Status": "Running"}
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_create(payload)
        self.assertTrue(any(issue.field == "Status" for issue in exc.exception.issues))

    def test_rejects_trl_out_of_range(self) -> None:
        payload = {**self.base_payload, "TRL_Start": 10}
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_create(payload)
        self.assertTrue(any(issue.field == "TRL_Start" for issue in exc.exception.issues))

    def test_rejects_duplicate_asset_id(self) -> None:
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_create(self.base_payload, existing_asset_ids={"AST-001"})
        self.assertTrue(any(issue.code == "duplicate" for issue in exc.exception.issues))

    def test_patch_validates_partial_payload_and_immutable_id(self) -> None:
        patch = {"Status": "Deprecated", "Asset_ID": "AST-999"}
        with self.assertRaises(ValidationError) as exc:
            self.validator.validate_for_patch("Cybersecurity Tool", patch)
        self.assertTrue(any(issue.code == "immutable" for issue in exc.exception.issues))


if __name__ == "__main__":
    unittest.main()
