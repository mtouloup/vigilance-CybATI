from __future__ import annotations

import unittest
from unittest.mock import patch

from vigilance_assets import AppRuntimeSettings, GoogleSheetsSettings, create_repository_from_settings
from vigilance_assets.google_sheets import GoogleSheetsConnectivityError, GoogleSheetsWorksheetError


class GoogleSheetsStartupBehaviorTests(unittest.TestCase):
    def test_repository_startup_surfaces_missing_worksheet_errors(self) -> None:
        settings = AppRuntimeSettings(google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-123'))

        with patch(
            'vigilance_assets.runtime.build_google_sheets_gateway',
            side_effect=GoogleSheetsWorksheetError("Worksheet 'ASSETS' was not found in the target spreadsheet."),
        ):
            with self.assertRaisesRegex(GoogleSheetsWorksheetError, "Worksheet 'ASSETS' was not found"):
                create_repository_from_settings(settings)

    def test_repository_startup_surfaces_public_connectivity_errors(self) -> None:
        settings = AppRuntimeSettings(google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-123'))

        with patch(
            'vigilance_assets.runtime.build_google_sheets_gateway',
            side_effect=GoogleSheetsConnectivityError('Failed to reach the public Google Sheet export.'),
        ):
            with self.assertRaisesRegex(GoogleSheetsConnectivityError, 'Failed to reach the public Google Sheet export'):
                create_repository_from_settings(settings)


if __name__ == '__main__':
    unittest.main()
