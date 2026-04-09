from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from vigilance_assets import build_asset_record
from vigilance_assets.models import normalize_last_updated

from tests.fixtures import asset_payload


class AssetModelTests(unittest.TestCase):
    def test_build_asset_record_normalizes_common_and_category_fields(self) -> None:
        asset = build_asset_record(asset_payload("Compute Resource", asset_id="AST-201"))

        self.assertEqual(asset.asset_id, "AST-201")
        self.assertEqual(asset.category, "Compute Resource")
        self.assertEqual(asset.category_fields.Compute_Form, "Container")
        self.assertEqual(asset.common.Last_Updated, datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc))

    def test_to_dict_round_trips_model_payload(self) -> None:
        payload = asset_payload("Physical / Cyber-Physical Asset", asset_id="AST-202")
        asset = build_asset_record(payload)

        self.assertEqual(asset.to_dict()["Asset_Subtype"], "PLC")
        self.assertEqual(asset.to_dict()["Asset_ID"], "AST-202")

    def test_to_dict_round_trips_telemetry_data_origin_field(self) -> None:
        payload = asset_payload("Data Stream / Data Source / Telemetry", asset_id="AST-203")
        asset = build_asset_record(payload)

        self.assertEqual(asset.to_dict()["Data_Origin"], "Real-world")

    def test_normalize_last_updated_accepts_date_and_naive_datetime(self) -> None:
        normalized_date = normalize_last_updated(date(2026, 3, 21))
        normalized_datetime = normalize_last_updated(datetime(2026, 3, 21, 8, 15))

        self.assertEqual(normalized_date, datetime(2026, 3, 21, tzinfo=timezone.utc))
        self.assertEqual(normalized_datetime, datetime(2026, 3, 21, 8, 15, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
