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
    UnsupportedCategoryError,
    UnsupportedVocabularyError,
    build_asset_record,
    create_app,
)


class ApiRepository(AssetRepository):
    def __init__(self) -> None:
        super().__init__()
        payload = {
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
            "Last_Updated": datetime(2026, 3, 21, 10, 0, tzinfo=timezone.utc),
            "Updated_By": "alice@example.org",
            "Tool_Type": "SIEM (Security Information and Event Management)",
        }
        self.asset = build_asset_record(payload)
        self.deleted: list[tuple[str, str]] = []

    def list_assets(self, query: AssetListQuery | None = None) -> AssetPage:
        query = query or AssetListQuery()
        items = [self.asset]
        for field, expected in query.filters.items():
            if isinstance(expected, tuple):
                items = [asset for asset in items if asset.to_dict().get(field) in expected]
            else:
                items = [asset for asset in items if asset.to_dict().get(field) == expected]
        if query.search:
            needle = query.search.casefold()
            items = [asset for asset in items if needle in asset.common.Asset_Name.casefold()]
        return AssetPage(items=tuple(items), total=len(items), page=query.page, page_size=query.page_size)

    def get_asset(self, asset_id: str) -> AssetRecord | None:
        return self.asset if asset_id == self.asset.asset_id else None

    def create_asset(self, asset: AssetRecord) -> AssetRecord:
        if asset.asset_id == self.asset.asset_id:
            raise DuplicateAssetError(asset.asset_id)
        self.asset = asset
        return asset

    def update_asset(self, asset_id: str, asset: AssetRecord) -> AssetRecord:
        if asset_id != self.asset.asset_id:
            raise AssetNotFoundError(asset_id)
        self.asset = asset
        return asset

    def delete_asset(self, asset_id: str, *, mode: str = "archive") -> None:
        if asset_id != self.asset.asset_id:
            raise AssetNotFoundError(asset_id)
        self.deleted.append((asset_id, mode))

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
        service = AssetService(repository, AssetValidator(repository.catalog))
        self.client = create_app(service).test_client()

    def test_get_assets_returns_consistent_payload(self) -> None:
        response = self.client.get(
            '/assets?Asset_Category=Cybersecurity+Tool&Owner_Org=OpenAI+Security+Lab'
            '&Status=Active&Pilot_s=Pilot+A&Deployment_Context=Cloud'
            '&Related_WP_Task=T5.3&search=  threat  &sort=Asset_Name&page=1&page_size=10'
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(payload['error'])
        self.assertEqual(payload['meta']['total'], 1)
        self.assertEqual(payload['data']['items'][0]['Asset_ID'], 'AST-001')
        self.assertEqual(payload['meta']['filters']['Asset_Category'], 'Cybersecurity Tool')
        self.assertEqual(payload['meta']['filters']['Owner_Org'], 'OpenAI Security Lab')
        self.assertEqual(payload['meta']['filters']['Pilot_s'], 'Pilot A')
        self.assertEqual(payload['meta']['filters']['Related_WP_Task'], 'T5.3')
        self.assertEqual(payload['meta']['search'], 'threat')
        self.assertEqual(payload['meta']['sort'][0]['field'], 'Asset_Name')


    def test_post_assets_creates_asset_and_returns_created_payload(self) -> None:
        response = self.client.post(
            '/assets',
            json={
                'Asset_ID': 'AST-002',
                'Asset_Name': 'Beacon',
                'Asset_Category': 'Platform / Service',
                'Owner_Org': 'OpenAI Security Lab',
                'Owner_Contact': 'bob@example.org',
                'Pilot_s': 'Pilot B',
                'Purpose': 'Correlates detections across services.',
                'Status': 'Planned',
                'TRL_Start': 3,
                'TRL_Target': 6,
                'Related_Result': 'RS4',
                'Related_WP_Task': 'T5.4',
                'Deployment_Context': 'Hybrid',
                'Updated_By': 'ignored@example.org',
                'Service_Type': 'Security Service',
            },
            headers={'X-Updated-By': 'api-user@example.org'},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload['data']['Asset_ID'], 'AST-002')
        self.assertEqual(payload['data']['Updated_By'], 'api-user@example.org')

    def test_patch_assets_returns_machine_readable_validation_errors(self) -> None:
        response = self.client.patch('/assets/AST-001', json={'Asset_ID': 'AST-999'})

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload['error']['code'], 'validation_error')
        self.assertEqual(payload['error']['details'][0]['field'], 'Asset_ID')
        self.assertEqual(payload['error']['details'][0]['code'], 'immutable')

    def test_put_assets_replaces_existing_asset(self) -> None:
        response = self.client.put(
            '/assets/AST-001',
            json={
                'Asset_Name': 'Threat Radar 2',
                'Asset_Category': 'Cybersecurity Tool',
                'Owner_Org': 'OpenAI Security Lab',
                'Owner_Contact': 'alice@example.org',
                'Pilot_s': 'Pilot A',
                'Purpose': 'Updated purpose.',
                'Status': 'Deprecated',
                'TRL_Start': 4,
                'TRL_Target': 8,
                'Related_Result': 'RS3',
                'Related_WP_Task': 'T5.3',
                'Deployment_Context': 'Cloud',
                'Updated_By': 'ignored@example.org',
                'Tool_Type': 'SIEM (Security Information and Event Management)',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['data']['Asset_Name'], 'Threat Radar 2')
        self.assertEqual(payload['data']['Status'], 'Deprecated')

    def test_delete_assets_defaults_to_archive_mode(self) -> None:
        response = self.client.delete('/assets/AST-001')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['data']['mode'], 'archive')

    def test_get_asset_returns_not_found_error_payload(self) -> None:
        response = self.client.get('/assets/missing')

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertEqual(payload['error']['code'], 'asset_not_found')
        self.assertIsNone(payload['data'])

    def test_get_vocabularies_returns_all_vocabularies(self) -> None:
        response = self.client.get('/vocabularies')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn('Status', payload['data'])
        self.assertGreater(payload['meta']['total'], 0)

    def test_get_vocabulary_returns_single_vocabulary(self) -> None:
        response = self.client.get('/vocabularies/Status')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['data']['name'], 'Status')
        self.assertIn('Active', payload['data']['values'])

    def test_get_vocabulary_returns_structured_error_for_unknown_name(self) -> None:
        response = self.client.get('/vocabularies/missing')

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertEqual(payload['error']['code'], 'unsupported_vocabulary')

    def test_get_schema_assets_returns_schema_view(self) -> None:
        response = self.client.get('/schema/assets')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['data']['id_field'], 'Asset_ID')
        self.assertIn('Cybersecurity Tool', payload['data']['category_fields'])

    def test_get_schema_assets_category_returns_single_category_schema(self) -> None:
        response = self.client.get('/schema/assets/Cybersecurity%20Tool')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(list(payload['data']['category_fields'].keys()), ['Cybersecurity Tool'])

    def test_get_schema_assets_category_returns_structured_error_for_unknown_category(self) -> None:
        response = self.client.get('/schema/assets/missing')

        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertEqual(payload['error']['code'], 'unsupported_category')

    def test_invalid_query_parameters_return_structured_bad_request(self) -> None:
        response = self.client.get('/assets?page=0')

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload['error']['code'], 'invalid_request')

    def test_get_assets_rejects_unsupported_query_parameters(self) -> None:
        response = self.client.get('/assets?Tool_Type=SIEM')

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload['error']['code'], 'invalid_request')
        self.assertIn('Unsupported query parameter', payload['error']['message'])


if __name__ == '__main__':
    unittest.main()
