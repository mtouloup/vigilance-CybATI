from __future__ import annotations

from datetime import datetime, timezone
import unittest

from vigilance_assets import (
    AssetListQuery,
    AssetPage,
    AssetRecord,
    AssetRepository,
    AssetService,
    AssetValidator,
    AssetNotFoundError,
    DuplicateAssetError,
    InventoryPayload,
    UnsupportedCategoryError,
    UnsupportedVocabularyError,
    build_asset_record,
    create_app,
)

from tests.fixtures import asset_payload, canonical_assets, now_utc


class ApiRepository(AssetRepository):
    def __init__(self) -> None:
        super().__init__()
        payloads = canonical_assets()[:3]
        payloads[0]["Asset_Name"] = "Threat Radar"
        payloads[0]["Purpose"] = "Aggregates threat findings for analysts."
        payloads[1]["Asset_Name"] = "Beacon"
        payloads[1]["Purpose"] = "Correlates detections across services."
        payloads[1]["Status"] = "Planned"
        payloads[2]["Asset_Name"] = "Compute Sentinel"
        payloads[2]["Purpose"] = "Protects runtime execution nodes."
        payloads[2]["Status"] = "Deprecated"
        self.assets = {payload["Asset_ID"]: build_asset_record(payload) for payload in payloads}
        self.deleted: list[tuple[str, str]] = []

    def list_assets(self, query: AssetListQuery | None = None) -> AssetPage:
        query = query or AssetListQuery()
        items = list(self.assets.values())
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
        return self.assets.get(asset_id)

    def create_asset(self, asset: AssetRecord) -> AssetRecord:
        if asset.asset_id in self.assets:
            raise DuplicateAssetError(asset.asset_id)
        self.assets[asset.asset_id] = asset
        return asset

    def update_asset(self, asset_id: str, asset: AssetRecord) -> AssetRecord:
        if asset_id not in self.assets:
            raise AssetNotFoundError(asset_id)
        self.assets[asset_id] = asset
        return asset

    def delete_asset(self, asset_id: str, *, mode: str = "archive") -> None:
        if asset_id not in self.assets:
            raise AssetNotFoundError(asset_id)
        self.deleted.append((asset_id, mode))

    def iter_inventory_payloads(self) -> tuple[InventoryPayload, ...]:
        valid_payload = self.assets["AST-001"].to_dict()
        invalid_payload = {
            **valid_payload,
            "Asset_ID": "AST-002",
            "Owner_Org": "",
            "TRL_Start": 10,
            "Tool_Type": "Unknown Tool Type",
            "Service_Type": "Security Service",
            "Documentation_Link": "not-a-url",
        }
        duplicate_payload = {
            **valid_payload,
            "Asset_Name": "Threat Radar Clone",
        }
        return (
            InventoryPayload(payload=valid_payload, row_number=2),
            InventoryPayload(payload=invalid_payload, row_number=3),
            InventoryPayload(payload=duplicate_payload, row_number=4),
        )

    def get_vocabulary(self, name: str) -> tuple[str, ...]:
        if name == "missing":
            raise UnsupportedVocabularyError(name)
        return super().get_vocabulary(name)

    def get_category_schema(self, category: str):
        if category == "missing":
            raise UnsupportedCategoryError(category)
        return super().get_category_schema(category)


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        repository = ApiRepository()
        service = AssetService(repository, AssetValidator(repository.catalog), now_provider=now_utc)
        self.client = create_app(service).test_client()

    def test_get_assets_returns_filtered_sorted_paginated_search_results(self) -> None:
        response = self.client.get(
            "/assets?Status=Active&search=threat&sort=-Asset_Name&page=1&page_size=1"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(payload["error"])
        self.assertEqual(payload["meta"]["total"], 1)
        self.assertEqual(payload["meta"]["page_size"], 1)
        self.assertEqual(payload["data"]["items"][0]["Asset_ID"], "AST-001")
        self.assertEqual(payload["meta"]["filters"]["Status"], "Active")
        self.assertEqual(payload["meta"]["search"], "threat")
        self.assertEqual(payload["meta"]["sort"][0]["field"], "Asset_Name")
        self.assertEqual(payload["meta"]["sort"][0]["direction"], "desc")

    def test_get_assets_quality_returns_machine_readable_inventory_report(self) -> None:
        response = self.client.get("/assets/quality")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["meta"]["total_assets"], 3)
        self.assertEqual(payload["meta"]["assets_with_issues"], 3)
        self.assertGreaterEqual(payload["meta"]["issue_count"], 6)
        issue_codes = {(issue["row_number"], issue["field"], issue["code"]) for issue in payload["data"]["issues"]}
        self.assertIn((3, "Owner_Org", "required"), issue_codes)
        self.assertIn((3, "TRL_Start", "out_of_range"), issue_codes)
        self.assertIn((3, "Tool_Type", "invalid_choice"), issue_codes)
        self.assertIn((3, "Service_Type", "category_exclusive"), issue_codes)
        self.assertIn((3, "Documentation_Link", "invalid_url"), issue_codes)
        self.assertIn((2, "Asset_ID", "duplicate"), issue_codes)
        self.assertIn((4, "Asset_ID", "duplicate"), issue_codes)

    def test_post_assets_creates_asset_and_returns_created_payload(self) -> None:
        response = self.client.post(
            "/assets",
            json=asset_payload("Platform / Service", asset_id="AST-099", Updated_By="ignored@example.org"),
            headers={"X-Updated-By": "api-user@example.org"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload["data"]["Asset_ID"], "AST-099")
        self.assertEqual(payload["data"]["Updated_By"], "api-user@example.org")

    def test_patch_assets_returns_machine_readable_validation_errors(self) -> None:
        response = self.client.patch("/assets/AST-001", json={"Asset_ID": "AST-999"})

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "validation_error")
        self.assertEqual(payload["error"]["details"][0]["field"], "Asset_ID")
        self.assertEqual(payload["error"]["details"][0]["code"], "immutable")

    def test_patch_assets_updates_partial_fields(self) -> None:
        response = self.client.patch(
            "/assets/AST-001",
            json={"Status": "Deprecated", "Security_Function": "Investigate"},
            headers={"X-Updated-By": "patcher@example.org"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["Status"], "Deprecated")
        self.assertEqual(payload["data"]["Security_Function"], "Investigate")
        self.assertEqual(payload["data"]["Updated_By"], "patcher@example.org")

    def test_put_assets_replaces_existing_asset(self) -> None:
        replacement = asset_payload("Cybersecurity Tool", asset_id="AST-001", asset_name="Threat Radar 2", Status="Deprecated")
        response = self.client.put("/assets/AST-001", json=replacement)

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["Asset_Name"], "Threat Radar 2")
        self.assertEqual(payload["data"]["Status"], "Deprecated")

    def test_delete_assets_defaults_to_archive_mode(self) -> None:
        response = self.client.delete("/assets/AST-001")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["mode"], "archive")

    def test_get_asset_returns_not_found_error_payload(self) -> None:
        response = self.client.get("/assets/missing")

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "asset_not_found")
        self.assertIsNone(payload["data"])

    def test_get_vocabularies_returns_all_vocabularies(self) -> None:
        response = self.client.get("/vocabularies")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("Status", payload["data"])
        self.assertGreater(payload["meta"]["total"], 0)

    def test_get_vocabulary_returns_single_vocabulary(self) -> None:
        response = self.client.get("/vocabularies/Status")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["name"], "Status")
        self.assertIn("Active", payload["data"]["values"])

    def test_get_vocabulary_returns_structured_error_for_unknown_name(self) -> None:
        response = self.client.get("/vocabularies/missing")

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "unsupported_vocabulary")

    def test_get_schema_assets_returns_schema_view(self) -> None:
        response = self.client.get("/schema/assets")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["id_field"], "Asset_ID")
        self.assertIn("Cybersecurity Tool", payload["data"]["category_fields"])

    def test_get_schema_assets_category_returns_single_category_schema(self) -> None:
        response = self.client.get("/schema/assets/Cybersecurity%20Tool")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(list(payload["data"]["category_fields"].keys()), ["Cybersecurity Tool"])

    def test_get_schema_assets_category_returns_structured_error_for_unknown_category(self) -> None:
        response = self.client.get("/schema/assets/missing")

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "unsupported_category")

    def test_invalid_query_parameters_return_structured_bad_request(self) -> None:
        response = self.client.get("/assets?page=0")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "invalid_request")

    def test_get_assets_rejects_unsupported_query_parameters(self) -> None:
        response = self.client.get("/assets?Tool_Type=SIEM")

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertIn("Unsupported query parameter", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
