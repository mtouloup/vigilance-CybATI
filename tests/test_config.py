from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

from vigilance_assets import (
    DEFAULT_ASSETS_WORKSHEET,
    AppRuntimeSettings,
    ConfigurationError,
    GoogleSheetsSettings,
    create_repository_from_settings,
    load_runtime_settings,
)


class ConfigTests(unittest.TestCase):
    def test_load_runtime_settings_requires_spreadsheet_id(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, 'VIGILANCE_GOOGLE_SPREADSHEET_ID must be set'):
            load_runtime_settings({})

    def test_load_runtime_settings_defaults_worksheet_name_to_assets(self) -> None:
        settings = load_runtime_settings({'VIGILANCE_GOOGLE_SPREADSHEET_ID': 'sheet-123'})
        self.assertEqual(settings.google_sheets.worksheet_name, DEFAULT_ASSETS_WORKSHEET)

    def test_load_runtime_settings_accepts_explicit_worksheet_name(self) -> None:
        settings = load_runtime_settings(
            {
                'VIGILANCE_GOOGLE_SPREADSHEET_ID': 'sheet-123',
                'VIGILANCE_GOOGLE_WORKSHEET_NAME': 'Inventory Assets',
            }
        )

        self.assertEqual(settings.google_sheets.spreadsheet_id, 'sheet-123')
        self.assertEqual(settings.google_sheets.worksheet_name, 'Inventory Assets')

    def test_create_repository_from_settings_uses_google_sheets_backend(self) -> None:
        settings = AppRuntimeSettings(google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-123'))

        fake_gateway = object()
        with patch('vigilance_assets.runtime.build_google_sheets_gateway', return_value=fake_gateway):
            repository = create_repository_from_settings(settings)

        self.assertIs(repository.gateway, fake_gateway)
        self.assertEqual(repository.workbook_reference, 'sheet-123')
        self.assertTrue(repository.read_only)

    def test_create_runtime_app_registers_runtime_settings_for_container_startup(self) -> None:
        from vigilance_assets.runtime import create_runtime_app

        settings = AppRuntimeSettings(google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-123'))
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
