from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from vigilance_assets.config import GoogleSheetsSettings
from vigilance_assets.google_sheets import (
    GoogleSheetsReadOnlyError,
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
        )

    def test_build_snapshot_requires_exact_canonical_headers(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.settings, expected_headers=self.mapper.ordered_headers)

        with self.assertRaisesRegex(GoogleSheetsWorksheetError, 'missing headers'):
            gateway._build_snapshot(
                sheet_name='Inventory Assets',
                sheet_id=None,
                raw_rows=[
                    ['Asset_ID', 'Asset_Name', 'Asset_Category'],
                    ['AST-001', 'Threat Radar', 'Cybersecurity Tool'],
                ],
            )

    def test_build_snapshot_rejects_unexpected_headers(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.settings, expected_headers=self.mapper.ordered_headers)

        with self.assertRaisesRegex(GoogleSheetsWorksheetError, 'unexpected headers'):
            gateway._build_snapshot(
                sheet_name='Inventory Assets',
                sheet_id=None,
                raw_rows=[list(self.mapper.ordered_headers) + ['Extra_Column']],
            )

    def test_validate_connection_reads_public_csv_export(self) -> None:
        csv_payload = '\n'.join([
            ','.join(self.mapper.ordered_headers),
            ','.join([
                'AST-001', 'Threat Radar', 'Cybersecurity Tool', 'OpenAI Security Lab', 'alice@example.org',
                'Pilot A', 'Aggregates threat findings for analysts.', 'Active', '4', '5', '7', 'RS3', 'T5.3',
                'Cloud', 'IEC 62443', 'Cloud Security', 'https://example.org/tool', '2026-03-21',
                'alice@example.org', 'SIEM (Security Information and Event Management)'
            ] + [''] * (len(self.mapper.ordered_headers) - 20)),
        ])

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def read(self):
                return csv_payload.encode('utf-8')

        with patch('vigilance_assets.google_sheets.urlopen', return_value=FakeResponse()):
            gateway = GoogleSheetsTableGateway(settings=self.settings, expected_headers=self.mapper.ordered_headers)
            snapshot = gateway.validate_connection()

        self.assertEqual(snapshot.sheet_name, 'Inventory Assets')
        self.assertIsNone(snapshot.sheet_id)
        self.assertEqual(snapshot.rows[0].values['Asset_ID'], 'AST-001')
        self.assertEqual(snapshot.rows[0].row_number, 2)

    def test_build_google_sheets_gateway_validates_on_construction(self) -> None:
        fake_gateway = GoogleSheetsTableGateway(settings=self.settings, expected_headers=self.mapper.ordered_headers)
        with patch.object(fake_gateway, 'validate_connection', return_value=None) as validate_connection, patch(
            'vigilance_assets.google_sheets.GoogleSheetsTableGateway', return_value=fake_gateway
        ) as gateway_class:
            gateway = build_google_sheets_gateway(self.settings, self.mapper.ordered_headers)

        self.assertIs(gateway, fake_gateway)
        gateway_class.assert_called_once()
        validate_connection.assert_called_once_with()

    def test_public_sheet_writes_raise_read_only_error(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.settings, expected_headers=self.mapper.ordered_headers)

        with self.assertRaisesRegex(GoogleSheetsReadOnlyError, 'read-only'):
            gateway.append_row('Inventory Assets', {'Asset_ID': 'AST-001'})

    def test_missing_public_sheet_surfaces_clear_error(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.settings, expected_headers=self.mapper.ordered_headers)
        error = HTTPError('https://example.test', 404, 'Not Found', hdrs=None, fp=None)

        with patch('vigilance_assets.google_sheets.urlopen', side_effect=error):
            with self.assertRaisesRegex(GoogleSheetsWorksheetError, 'publicly accessible'):
                gateway.validate_connection()


if __name__ == '__main__':
    unittest.main()
