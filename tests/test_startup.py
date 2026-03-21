from __future__ import annotations

import unittest
from unittest.mock import patch

from vigilance_assets import create_repository_from_settings, load_runtime_settings
from vigilance_assets.google_sheets import GoogleSheetsConfigurationError


class GoogleSheetsStartupBehaviorTests(unittest.TestCase):
    def test_repository_read_only_gateway_raises_clear_error_for_write_without_credentials(self) -> None:
        repository = create_repository_from_settings(
            load_runtime_settings(
                {
                    'VIGILANCE_SPREADSHEET_BACKEND': 'google_sheets',
                    'VIGILANCE_SPREADSHEET_GOOGLE_ID': 'sheet-123',
                    'VIGILANCE_GOOGLE_SHEETS_MODE': 'auto',
                }
            )
        )

        with self.assertRaisesRegex(GoogleSheetsConfigurationError, 'read_only mode'):
            repository.gateway.append_row('ASSETS', {'Asset_ID': 'AST-123'})

    def test_repository_google_sheets_read_path_can_be_mocked_without_network(self) -> None:
        repository = create_repository_from_settings(
            load_runtime_settings(
                {
                    'VIGILANCE_SPREADSHEET_BACKEND': 'google_sheets',
                    'VIGILANCE_SPREADSHEET_GOOGLE_ID': 'sheet-123',
                    'VIGILANCE_GOOGLE_SHEETS_MODE': 'auto',
                }
            )
        )

        with patch.object(repository.gateway, 'list_rows', return_value=[]):
            page = repository.list_assets()

        self.assertEqual(page.total, 0)


if __name__ == '__main__':
    unittest.main()
