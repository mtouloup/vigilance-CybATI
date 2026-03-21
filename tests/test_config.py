from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vigilance_assets import (
    FILE_BACKEND,
    GOOGLE_SHEETS_BACKEND,
    MEMORY_BACKEND,
    GoogleSheetsTableGateway,
    InMemorySpreadsheetGateway,
    ConfigurationError,
    WorkbookFileGateway,
    create_repository_from_settings,
    load_runtime_settings,
)


class ConfigTests(unittest.TestCase):
    def test_load_runtime_settings_defaults_to_memory_backend(self) -> None:
        settings = load_runtime_settings({})

        self.assertEqual(settings.spreadsheet.backend, MEMORY_BACKEND)
        self.assertEqual(settings.spreadsheet.workbook_reference, "in-memory")

    def test_load_runtime_settings_supports_google_sheets_backend(self) -> None:
        settings = load_runtime_settings(
            {
                "VIGILANCE_SPREADSHEET_BACKEND": "google_sheets",
                "VIGILANCE_SPREADSHEET_GOOGLE_ID": "sheet-123",
                "VIGILANCE_GOOGLE_CREDENTIALS_PATH": "/tmp/creds.json",
            }
        )

        self.assertEqual(settings.spreadsheet.backend, GOOGLE_SHEETS_BACKEND)
        self.assertEqual(settings.spreadsheet.google_sheets.spreadsheet_id, "sheet-123")
        self.assertEqual(settings.spreadsheet.workbook_reference, "sheet-123")

    def test_load_runtime_settings_accepts_file_backend_aliases(self) -> None:
        settings = load_runtime_settings(
            {
                "VIGILANCE_SPREADSHEET_BACKEND": "workbook",
                "VIGILANCE_SPREADSHEET_WORKBOOK_PATH": "inventory.xlsx",
            }
        )

        self.assertEqual(settings.spreadsheet.backend, FILE_BACKEND)
        self.assertEqual(settings.spreadsheet.file.path, "inventory.xlsx")
        self.assertEqual(settings.spreadsheet.workbook_reference, "inventory.xlsx")

    def test_load_runtime_settings_supports_google_sheets_mode(self) -> None:
        settings = load_runtime_settings(
            {
                "VIGILANCE_SPREADSHEET_BACKEND": "google_sheets",
                "VIGILANCE_SPREADSHEET_GOOGLE_ID": "sheet-123",
                "VIGILANCE_GOOGLE_SHEETS_MODE": "read_only",
            }
        )

        self.assertEqual(settings.spreadsheet.google_sheets.mode, "read_only")

    def test_load_runtime_settings_requires_file_path_for_file_backend(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_runtime_settings({"VIGILANCE_SPREADSHEET_BACKEND": "file"})

    def test_load_runtime_settings_validates_boolean_values(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_runtime_settings(
                {
                    "VIGILANCE_SPREADSHEET_BACKEND": "file",
                    "VIGILANCE_SPREADSHEET_FILE_PATH": "inventory.xlsx",
                    "VIGILANCE_SPREADSHEET_FILE_READ_ONLY": "maybe",
                }
            )

    def test_create_repository_from_settings_uses_memory_backend(self) -> None:
        settings = load_runtime_settings({})
        repository = create_repository_from_settings(settings)

        self.assertIsInstance(repository.gateway, InMemorySpreadsheetGateway)
        self.assertEqual(repository.workbook_reference, "in-memory")

    def test_create_repository_from_settings_uses_file_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "inventory.xlsx"
            settings = load_runtime_settings(
                {
                    "VIGILANCE_SPREADSHEET_BACKEND": "file",
                    "VIGILANCE_SPREADSHEET_FILE_PATH": str(workbook_path),
                }
            )

            repository = create_repository_from_settings(settings)

        self.assertIsInstance(repository.gateway, WorkbookFileGateway)
        self.assertEqual(repository.workbook_reference, str(workbook_path))

    def test_create_repository_from_settings_uses_google_sheets_backend(self) -> None:
        repository = create_repository_from_settings(
            load_runtime_settings(
                {
                    "VIGILANCE_SPREADSHEET_BACKEND": "google_sheets",
                    "VIGILANCE_SPREADSHEET_GOOGLE_ID": "sheet-123",
                    "VIGILANCE_GOOGLE_SHEETS_MODE": "read_only",
                }
            )
        )

        self.assertIsInstance(repository.gateway, GoogleSheetsTableGateway)

    def test_create_repository_from_settings_propagates_file_backend_initialization_errors(self) -> None:
        settings = load_runtime_settings(
            {
                "VIGILANCE_SPREADSHEET_BACKEND": "file",
                "VIGILANCE_SPREADSHEET_FILE_PATH": "inventory.xlsx",
                "VIGILANCE_ASSETS_SHEET_NAME": "MISSING",
            }
        )

        with patch('vigilance_assets.runtime.WorkbookFileGateway.list_rows', side_effect=ConfigurationError('missing sheet')):
            with self.assertRaisesRegex(ConfigurationError, 'missing sheet'):
                create_repository_from_settings(settings)

    def test_google_sheets_repository_initializes_without_credentials_in_read_only_mode(self) -> None:
        repository = create_repository_from_settings(
            load_runtime_settings(
                {
                    "VIGILANCE_SPREADSHEET_BACKEND": "google_sheets",
                    "VIGILANCE_SPREADSHEET_GOOGLE_ID": "sheet-123",
                    "VIGILANCE_GOOGLE_SHEETS_MODE": "read_only",
                }
            )
        )

        self.assertIsInstance(repository.gateway, GoogleSheetsTableGateway)
        self.assertEqual(repository.gateway.settings.mode, 'read_only')
        self.assertIsNone(repository.gateway.settings.credentials_path)

    def test_create_runtime_app_registers_runtime_settings_for_container_startup(self) -> None:
        from vigilance_assets.runtime import create_runtime_app

        settings = load_runtime_settings({})
        repository = create_repository_from_settings(settings)

        with patch('vigilance_assets.runtime.load_runtime_settings', return_value=settings), patch(
            'vigilance_assets.runtime.create_repository_from_settings', return_value=repository
        ):
            app = create_runtime_app()

        self.assertIn('RUNTIME_SETTINGS', app.config)
        self.assertEqual(app.config['RUNTIME_SETTINGS'].spreadsheet.backend, MEMORY_BACKEND)
        self.assertIn('/openapi.json', {rule.rule for rule in app.url_map.iter_rules()})

    def test_wsgi_module_creates_app_during_import(self) -> None:
        import vigilance_assets.wsgi as wsgi_module

        fake_app = object()
        with patch('vigilance_assets.runtime.create_runtime_app', return_value=fake_app):
            reloaded = importlib.reload(wsgi_module)

        self.assertIs(reloaded.app, fake_app)


if __name__ == "__main__":
    unittest.main()
