from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from vigilance_assets.config import GoogleSheetsSettings
from vigilance_assets.google_sheets import (
    GoogleSheetsConfigurationError,
    GoogleSheetsTableGateway,
    GoogleSheetsWorksheetError,
    build_google_sheets_gateway,
)
from vigilance_assets.spreadsheet import AssetSpreadsheetMapper


class GoogleSheetsGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = AssetSpreadsheetMapper()
        self.settings = GoogleSheetsSettings(
            spreadsheet_id='sheet-123',
            worksheet_name='Inventory Assets',
            credentials_json='{"type": "service_account"}',
        )

    def test_build_snapshot_requires_exact_canonical_headers(self) -> None:
        gateway = object.__new__(GoogleSheetsTableGateway)
        gateway.settings = self.settings
        gateway.expected_headers = self.mapper.ordered_headers
        gateway._expected_headers = tuple(self.mapper.ordered_headers)
        gateway._expected_header_set = set(self.mapper.ordered_headers)

        with self.assertRaisesRegex(GoogleSheetsWorksheetError, 'missing headers'):
            gateway._build_snapshot(
                sheet_name='Inventory Assets',
                sheet_id=123,
                raw_rows=[
                    ['Asset_ID', 'Asset_Name', 'Asset_Category'],
                    ['AST-001', 'Threat Radar', 'Cybersecurity Tool'],
                ],
            )

    def test_build_snapshot_rejects_unexpected_headers(self) -> None:
        gateway = object.__new__(GoogleSheetsTableGateway)
        gateway.settings = self.settings
        gateway.expected_headers = self.mapper.ordered_headers
        gateway._expected_headers = tuple(self.mapper.ordered_headers)
        gateway._expected_header_set = set(self.mapper.ordered_headers)

        with self.assertRaisesRegex(GoogleSheetsWorksheetError, 'unexpected headers'):
            gateway._build_snapshot(
                sheet_name='Inventory Assets',
                sheet_id=123,
                raw_rows=[list(self.mapper.ordered_headers) + ['Extra_Column']],
            )

    def test_validate_connection_uses_api_metadata_and_values(self) -> None:
        metadata_call = Mock()
        metadata_call.execute.return_value = {'sheets': [{'properties': {'title': 'Inventory Assets', 'sheetId': 99}}]}
        values_call = Mock()
        values_call.execute.return_value = {
            'values': [
                list(self.mapper.ordered_headers),
                [
                    'AST-001', 'Threat Radar', 'Cybersecurity Tool', 'OpenAI Security Lab', 'alice@example.org',
                    'Pilot A', 'Aggregates threat findings for analysts.', 'Active', '4', '5', '7', 'RS3', 'T5.3',
                    'Cloud', 'IEC 62443', 'Cloud Security', 'https://example.org/tool', '2026-03-21',
                    'alice@example.org', 'SIEM (Security Information and Event Management)'
                ] + [''] * (len(self.mapper.ordered_headers) - 20)
            ]
        }
        service = Mock()
        service.spreadsheets.return_value.get.return_value = metadata_call
        service.spreadsheets.return_value.values.return_value.get.return_value = values_call

        with patch.object(GoogleSheetsTableGateway, '_build_service', return_value=service):
            gateway = GoogleSheetsTableGateway(settings=self.settings, expected_headers=self.mapper.ordered_headers)
            snapshot = gateway.validate_connection()

        self.assertEqual(snapshot.sheet_name, 'Inventory Assets')
        self.assertEqual(snapshot.sheet_id, 99)
        self.assertEqual(snapshot.rows[0].values['Asset_ID'], 'AST-001')
        self.assertEqual(snapshot.rows[0].row_number, 2)

    def test_build_google_sheets_gateway_validates_on_construction(self) -> None:
        fake_gateway = Mock(spec=GoogleSheetsTableGateway)
        fake_gateway.validate_connection.return_value = None
        with patch('vigilance_assets.google_sheets.GoogleSheetsTableGateway', return_value=fake_gateway) as gateway_class:
            gateway = build_google_sheets_gateway(self.settings, self.mapper.ordered_headers)

        self.assertIs(gateway, fake_gateway)
        gateway_class.assert_called_once()
        fake_gateway.validate_connection.assert_called_once_with()

    def test_missing_credentials_path_fails_clearly(self) -> None:
        settings = GoogleSheetsSettings(
            spreadsheet_id='sheet-123',
            credentials_path='/tmp/missing-creds.json',
        )

        with self.assertRaisesRegex(GoogleSheetsConfigurationError, 'Google credentials file was not found'):
            GoogleSheetsTableGateway(settings=settings, expected_headers=self.mapper.ordered_headers)


if __name__ == '__main__':
    unittest.main()
