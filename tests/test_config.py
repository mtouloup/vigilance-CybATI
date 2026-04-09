from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

from vigilance_assets import (
    DEFAULT_ASSETS_WORKSHEET,
    AppRuntimeSettings,
    ConfigurationError,
    EntraOboSettings,
    GoogleSheetsSettings,
    SharePointSettings,
    create_repository_from_settings,
    load_runtime_settings,
)


class ConfigTests(unittest.TestCase):
    def test_load_runtime_settings_defaults_to_google_backend(self) -> None:
        settings = load_runtime_settings(
            {
                'VIGILANCE_GOOGLE_SPREADSHEET_ID': 'sheet-123',
                'VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON': '{"type":"service_account"}',
            }
        )
        self.assertEqual(settings.storage_backend, 'google_sheets')

    def test_load_runtime_settings_requires_google_spreadsheet_id_for_google_backend(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, 'VIGILANCE_GOOGLE_SPREADSHEET_ID must be set'):
            load_runtime_settings({'VIGILANCE_STORAGE_BACKEND': 'google_sheets'})

    def test_load_runtime_settings_defaults_worksheet_name_to_assets(self) -> None:
        settings = load_runtime_settings(
            {
                'VIGILANCE_GOOGLE_SPREADSHEET_ID': 'sheet-123',
                'VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON': '{"type":"service_account"}',
            }
        )
        self.assertEqual(settings.google_sheets.worksheet_name, DEFAULT_ASSETS_WORKSHEET)

    def test_load_runtime_settings_requires_sharepoint_values_for_sharepoint_backend(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, 'VIGILANCE_SHAREPOINT_SITE_ID'):
            load_runtime_settings({'VIGILANCE_STORAGE_BACKEND': 'sharepoint'})

    def test_load_runtime_settings_accepts_sharepoint_path_configuration(self) -> None:
        settings = load_runtime_settings(
            {
                'VIGILANCE_STORAGE_BACKEND': 'sharepoint',
                'VIGILANCE_AUTH_MODE': 'entra_obo',
                'VIGILANCE_ENTRA_TENANT_ID': 'tenant-id',
                'VIGILANCE_ENTRA_CLIENT_ID': 'client-id',
                'VIGILANCE_ENTRA_CLIENT_SECRET': 'secret',
                'VIGILANCE_ENTRA_API_AUDIENCE': 'api://asset-api',
                'VIGILANCE_SHAREPOINT_SITE_ID': 'site-id',
                'VIGILANCE_SHAREPOINT_WORKBOOK_PATH': 'Shared Documents/inventory.xlsx',
            }
        )

        self.assertEqual(settings.storage_backend, 'sharepoint')
        assert settings.sharepoint is not None
        self.assertEqual(settings.sharepoint.worksheet_name, DEFAULT_ASSETS_WORKSHEET)
        self.assertEqual(settings.sharepoint.workbook_path, 'Shared Documents/inventory.xlsx')
        self.assertEqual(settings.auth_mode, 'entra_obo')

    def test_load_runtime_settings_rejects_unknown_backend(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, 'Unsupported VIGILANCE_STORAGE_BACKEND value'):
            load_runtime_settings({'VIGILANCE_STORAGE_BACKEND': 'sqlite'})

    def test_load_runtime_settings_requires_credentials_unless_explicit_public_mode_is_enabled(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, 'Authenticated Google Sheets access requires'):
            load_runtime_settings({'VIGILANCE_GOOGLE_SPREADSHEET_ID': 'sheet-123'})

        settings = load_runtime_settings(
            {
                'VIGILANCE_GOOGLE_SPREADSHEET_ID': 'sheet-123',
                'VIGILANCE_GOOGLE_READ_ONLY_PUBLIC': 'true',
            }
        )
        self.assertTrue(settings.google_sheets.read_only_public_fallback)

    def test_load_runtime_settings_supports_custom_auth_public_paths(self) -> None:
        settings = load_runtime_settings(
            {
                'VIGILANCE_GOOGLE_SPREADSHEET_ID': 'sheet-123',
                'VIGILANCE_GOOGLE_READ_ONLY_PUBLIC': 'true',
                'VIGILANCE_AUTH_PUBLIC_PATHS': '/docs,/openapi.json,/health',
            }
        )
        self.assertEqual(settings.auth_public_paths, ('/docs', '/openapi.json', '/health'))

    def test_load_runtime_settings_reads_swagger_oauth_values(self) -> None:
        settings = load_runtime_settings(
            {
                'VIGILANCE_GOOGLE_SPREADSHEET_ID': 'sheet-123',
                'VIGILANCE_GOOGLE_READ_ONLY_PUBLIC': 'true',
                'VIGILANCE_SWAGGER_USE_OAUTH': 'true',
                'VIGILANCE_ENTRA_TENANT_ID': 'tenant-id',
                'VIGILANCE_ENTRA_CLIENT_ID': 'client-id',
                'VIGILANCE_ENTRA_API_SCOPE': 'api://asset-api/access_as_user',
                'VIGILANCE_ENTRA_AUTHORIZATION_URL': 'https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize',
                'VIGILANCE_ENTRA_TOKEN_URL': 'https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token',
            }
        )

        self.assertTrue(settings.swagger_use_oauth)
        self.assertEqual(settings.swagger_entra_tenant_id, 'tenant-id')
        self.assertEqual(settings.swagger_entra_client_id, 'client-id')
        self.assertEqual(settings.swagger_entra_api_scope, 'api://asset-api/access_as_user')
        self.assertEqual(settings.swagger_oauth_scopes, ('api://asset-api/access_as_user',))
        self.assertEqual(settings.swagger_oauth_authorization_url, 'https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize')
        self.assertEqual(settings.swagger_oauth_token_url, 'https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token')

    def test_create_repository_from_settings_uses_google_sheets_backend(self) -> None:
        settings = AppRuntimeSettings(
            storage_backend='google_sheets',
            google_sheets=GoogleSheetsSettings(
                spreadsheet_id='sheet-123',
                service_account_json='{"type":"service_account"}',
            ),
            sharepoint=SharePointSettings(site_id='s', item_id='i'),
        )

        fake_gateway = type('Gateway', (), {'is_read_only': False})()
        with patch('vigilance_assets.runtime.build_google_sheets_gateway', return_value=fake_gateway):
            repository = create_repository_from_settings(settings)

        self.assertIs(repository.gateway, fake_gateway)
        self.assertEqual(repository.workbook_reference, 'sheet-123')
        self.assertFalse(repository.read_only)

    def test_create_repository_from_settings_uses_sharepoint_backend(self) -> None:
        settings = AppRuntimeSettings(
            storage_backend='sharepoint',
            auth_mode='entra_obo',
            google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-123', read_only_public_fallback=True),
            sharepoint=SharePointSettings(
                site_id='site-id',
                item_id='item-id',
            ),
            entra_obo=EntraOboSettings(
                tenant_id='tenant',
                client_id='client',
                client_secret='secret',
                api_audience='api://asset-api',
            ),
        )

        fake_gateway = type('Gateway', (), {'is_read_only': False})()
        with patch('vigilance_assets.runtime.EntraOboTokenBroker') as broker_cls, patch('vigilance_assets.runtime.build_sharepoint_gateway', return_value=fake_gateway) as gateway_builder:
            broker_cls.return_value = object()
            repository = create_repository_from_settings(settings)

        self.assertIs(repository.gateway, fake_gateway)
        _, kwargs = gateway_builder.call_args
        self.assertFalse(kwargs['validate_on_startup'])
        self.assertTrue(callable(kwargs['graph_access_token_provider']))
        self.assertEqual(repository.workbook_reference, 'item-id')
        self.assertFalse(repository.read_only)

    def test_create_repository_from_settings_uses_sharepoint_workbook_path_reference(self) -> None:
        settings = AppRuntimeSettings(
            storage_backend='sharepoint',
            auth_mode='entra_obo',
            google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-123', read_only_public_fallback=True),
            sharepoint=SharePointSettings(
                site_id='site-id',
                workbook_path='Shared Documents/assets.xlsx',
            ),
            entra_obo=EntraOboSettings(
                tenant_id='tenant',
                client_id='client',
                client_secret='secret',
                api_audience='api://asset-api',
            ),
        )

        fake_gateway = type('Gateway', (), {'is_read_only': False})()
        with patch('vigilance_assets.runtime.EntraOboTokenBroker') as broker_cls, patch('vigilance_assets.runtime.build_sharepoint_gateway', return_value=fake_gateway):
            broker_cls.return_value = object()
            repository = create_repository_from_settings(settings)

        self.assertEqual(repository.workbook_reference, 'Shared Documents/assets.xlsx')

    def test_create_runtime_app_registers_runtime_settings_for_container_startup(self) -> None:
        from vigilance_assets.runtime import create_runtime_app

        settings = AppRuntimeSettings(
            storage_backend='google_sheets',
            google_sheets=GoogleSheetsSettings(
                spreadsheet_id='sheet-123',
                service_account_json='{"type":"service_account"}',
            ),
            sharepoint=SharePointSettings(site_id='s', item_id='i'),
        )
        from tests.test_repository import RepositoryDouble

        repository = RepositoryDouble()

        with patch('vigilance_assets.runtime.load_runtime_settings', return_value=settings), patch(
            'vigilance_assets.runtime.create_repository_from_settings', return_value=repository
        ):
            app = create_runtime_app()

        self.assertIn('RUNTIME_SETTINGS', app.config)
        self.assertEqual(app.config['RUNTIME_SETTINGS'].google_sheets.spreadsheet_id, 'sheet-123')
        self.assertIn('/openapi.json', {rule.rule for rule in app.url_map.iter_rules()})
        self.assertIn('/docs', {rule.rule for rule in app.url_map.iter_rules()})

    def test_wsgi_module_creates_app_during_import(self) -> None:
        fake_app = object()
        with patch('vigilance_assets.runtime.create_runtime_app', return_value=fake_app):
            wsgi_module = importlib.import_module('vigilance_assets.wsgi')
            reloaded = importlib.reload(wsgi_module)

        self.assertIs(reloaded.app, fake_app)


if __name__ == '__main__':
    unittest.main()
