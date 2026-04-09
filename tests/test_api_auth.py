from __future__ import annotations

import unittest
from unittest.mock import Mock

from vigilance_assets import (
    AppRuntimeSettings,
    AssetRepository,
    AssetService,
    EntraOboSettings,
    GoogleSheetsSettings,
    SharePointSettings,
    build_asset_record,
    create_app,
)
from vigilance_assets.auth import AuthContext, configure_auth
from tests.fixtures import asset_payload


class _Repo(AssetRepository):
    def __init__(self) -> None:
        super().__init__()
        payload = {
            'Asset_ID': 'AST-001',
            'Asset_Name': 'Threat Radar',
            'Asset_Category': 'Cybersecurity Tool',
            'Owner_Org': 'Org',
            'Owner_Contact': 'owner@example.org',
            'Pilot_s': 'Pilot A',
            'Purpose': 'Purpose',
            'Status': 'Active',
            'TRL_Start': 3,
            'TRL_Target': 5,
            'Related_Result': 'RS3',
            'Related_WP_Task': 'T5.3',
            'Deployment_Context': 'Cloud',
            'Last_Updated': '2026-01-01',
            'Updated_By': 'user@example.org',
            'Tool_Type': 'EDR (Endpoint Detection and Response)',
        }
        self.record = build_asset_record(payload)

    def list_assets(self, query=None):
        from vigilance_assets.repository import AssetPage

        return AssetPage(items=(self.record,), total=1, page=1, page_size=50)

    def get_asset(self, asset_id: str):
        if asset_id == self.record.asset_id:
            return self.record
        return None

    def create_asset(self, asset):
        return asset

    def update_asset(self, asset_id, asset):
        return asset

    def delete_asset(self, asset_id: str, *, mode: str = 'archive'):
        return None


class ApiAuthTests(unittest.TestCase):
    def _build_client(self):
        app = create_app(service=AssetService(_Repo()))
        settings = AppRuntimeSettings(
            storage_backend='google_sheets',
            auth_mode='entra_obo',
            google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet', read_only_public_fallback=True),
            sharepoint=SharePointSettings(site_id='site', item_id='item'),
            entra_obo=EntraOboSettings(
                tenant_id='tenant-id',
                client_id='client-id',
                client_secret='secret',
                api_audience='api://asset-api',
            ),
        )
        configure_auth(app, settings)
        validator = app.config['JWT_VALIDATOR']
        validator.validate = Mock(return_value=AuthContext('sub-1', 'tenant-id', 'api://asset-api', None, None, None))
        return app.test_client(), validator

    def test_denies_missing_auth_header(self):
        client, _ = self._build_client()

        response = client.post('/assets', json={'Asset_ID': 'AST-2'})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['error']['code'], 'authentication_failed')

    def test_docs_is_public_without_token(self):
        client, validator = self._build_client()

        response = client.get('/docs')

        self.assertEqual(response.status_code, 200)
        self.assertIn('swagger-ui', response.get_data(as_text=True))
        validator.validate.assert_not_called()

    def test_openapi_is_public_without_token(self):
        client, validator = self._build_client()

        response = client.get('/openapi.json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['openapi'], '3.0.3')
        validator.validate.assert_not_called()

    def test_allows_authenticated_mutation(self):
        client, validator = self._build_client()

        payload = asset_payload('Cybersecurity Tool', asset_id='AST-123')
        response = client.post('/assets', json=payload, headers={'Authorization': 'Bearer token'})

        self.assertEqual(response.status_code, 201)
        validator.validate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
