from __future__ import annotations

import unittest
from unittest.mock import Mock, patch
from httplib2 import Response
from urllib.error import HTTPError

from googleapiclient.errors import HttpError

from vigilance_assets.config import GoogleSheetsSettings
from vigilance_assets.google_sheets import (
    GoogleSheetsConfigurationError,
    GoogleSheetsConnectivityError,
    GoogleSheetsReadOnlyError,
    GoogleSheetsTableGateway,
    GoogleSheetsWorksheetError,
    _load_service_account_credentials,
    build_google_sheets_gateway,
)
from vigilance_assets.spreadsheet import AssetSpreadsheetMapper


class GoogleSheetsGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = AssetSpreadsheetMapper()
        self.auth_settings = GoogleSheetsSettings(
            spreadsheet_id='sheet-123',
            worksheet_name='Inventory Assets',
            service_account_json='{"type":"service_account","client_email":"svc@example.org","token_uri":"https://oauth2.googleapis.com/token","private_key_id":"key","private_key":"-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n"}',
        )
        self.public_settings = GoogleSheetsSettings(
            spreadsheet_id='sheet-123',
            worksheet_name='Inventory Assets',
            read_only_public_fallback=True,
        )

    def test_build_snapshot_requires_all_canonical_headers_in_detected_row(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers)

        with self.assertRaisesRegex(GoogleSheetsWorksheetError, 'missing canonical headers'):
            gateway._build_snapshot(
                sheet_name='Inventory Assets',
                sheet_id=None,
                raw_rows=[
                    ['CYBERSECURITY TOOL–SPECIFIC FIELDS'],
                    ['Asset_ID', 'Asset_Name', 'Asset_Category'],
                    ['AST-001', 'Threat Radar', 'Cybersecurity Tool'],
                ],
            )

    def test_build_snapshot_ignores_decorative_row_and_blank_separator_columns(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers)
        headers = list(self.mapper.ordered_headers)
        tool_type_index = headers.index('Tool_Type')
        service_type_index = headers.index('Service_Type')
        row_length = len(headers) + 2

        decorative_row = [''] * row_length
        decorative_row[tool_type_index] = ' CYBERSECURITY TOOL–SPECIFIC FIELDS (if Asset_Category = Cybersecurity Tool) '
        decorative_row[service_type_index + 1] = 'PLATFORM / SERVICE—SPECIFIC FIELDS (if Asset_Category = Platform / Service)'

        actual_header_row = headers[:tool_type_index] + ['  Tool_Type  ', ''] + headers[tool_type_index + 1:service_type_index] + [''] + headers[service_type_index:]
        data_row = [''] * row_length
        row_values = {
            'Asset_ID': 'AST-001',
            'Asset_Name': 'Threat Radar',
            'Asset_Category': 'Cybersecurity Tool',
            'Owner_Org': 'OpenAI Security Lab',
            'Owner_Contact': 'alice@example.org',
            'Pilot (s)': 'Pilot A',
            'Purpose (1-2 sentences)': 'Aggregates threat findings for analysts.',
            'Status': 'Active',
            'TRL_Start': '4',
            'TRL_Current': '5',
            'TRL_Target': '7',
            'Related_Result': 'RS3',
            'Related_WP_Task': 'T5.3',
            'Deployment_Context': 'Cloud',
            'Standards_Compliance': 'IEC 62443',
            'Security_Domain': 'Cloud Security',
            'Documentation_Link': 'https://example.org/tool',
            'Last_Updated': '2026-03-21',
            'Updated_By': 'alice@example.org',
            'Tool_Type': 'SIEM (Security Information and Event Management)',
        }
        normalized_columns = {
            gateway._normalize_header_key(value): index
            for index, value in enumerate(actual_header_row)
            if gateway._normalize_header_key(value)
        }
        for header, value in row_values.items():
            data_row[normalized_columns[gateway._normalize_header_key(header)]] = value

        snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=None,
            raw_rows=[decorative_row, actual_header_row, data_row],
        )

        self.assertEqual(snapshot.headers, self.mapper.ordered_headers)
        self.assertEqual(snapshot.rows[0].row_number, 3)
        self.assertEqual(snapshot.rows[0].values['Asset_ID'], 'AST-001')
        self.assertEqual(snapshot.rows[0].values['Tool_Type'], 'SIEM (Security Information and Event Management)')
        self.assertNotIn('', snapshot.rows[0].values)

    def test_validate_connection_reads_public_csv_export_when_explicitly_configured(self) -> None:
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
            gateway = GoogleSheetsTableGateway(settings=self.public_settings, expected_headers=self.mapper.ordered_headers)
            snapshot = gateway.validate_connection()

        self.assertEqual(snapshot.sheet_name, 'Inventory Assets')
        self.assertIsNone(snapshot.sheet_id)
        self.assertEqual(snapshot.rows[0].values['Asset_ID'], 'AST-001')
        self.assertEqual(snapshot.rows[0].row_number, 2)
        self.assertTrue(gateway.is_read_only)

    def test_authenticated_gateway_reads_rows_via_google_api(self) -> None:
        values_resource = Mock()
        values_resource.get.return_value.execute.return_value = {
            'values': [
                list(self.mapper.ordered_headers),
                ['AST-001', 'Threat Radar', 'Cybersecurity Tool'] + [''] * (len(self.mapper.ordered_headers) - 3),
            ]
        }
        spreadsheets_resource = Mock()
        spreadsheets_resource.get.return_value.execute.return_value = {
            'sheets': [{'properties': {'sheetId': 12, 'title': 'Inventory Assets'}}]
        }
        spreadsheets_resource.values.return_value = values_resource
        service = Mock()
        service.spreadsheets.return_value = spreadsheets_resource

        gateway = GoogleSheetsTableGateway(
            settings=self.auth_settings,
            expected_headers=self.mapper.ordered_headers,
            api_service=service,
        )

        snapshot = gateway.validate_connection()

        self.assertEqual(snapshot.sheet_id, 12)
        self.assertEqual(snapshot.rows[0].values['Asset_ID'], 'AST-001')
        self.assertFalse(gateway.is_read_only)


    def test_authenticated_metadata_error_includes_google_api_details_and_guidance(self) -> None:
        error_content = b'{"error":{"code":403,"message":"Google Sheets API has not been used in project 123 before or it is disabled.","status":"PERMISSION_DENIED"}}'
        service = Mock()
        service.spreadsheets.return_value.get.return_value.execute.side_effect = HttpError(
            Response({'status': '403'}),
            error_content,
        )

        gateway = GoogleSheetsTableGateway(
            settings=self.auth_settings,
            expected_headers=self.mapper.ordered_headers,
            api_service=service,
        )

        with self.assertRaisesRegex(GoogleSheetsConnectivityError, 'Underlying Google API error: HTTP 403 Forbidden') as context:
            gateway.validate_connection()

        self.assertIn('Google Sheets API is disabled', str(context.exception))
        self.assertIn('shared with the service account email', str(context.exception))
        self.assertIsInstance(context.exception.__cause__, HttpError)

    def test_invalid_service_account_payload_includes_actionable_guidance(self) -> None:
        with self.assertRaisesRegex(GoogleSheetsConfigurationError, 'belongs to the intended Google Cloud project'):
            _load_service_account_credentials(
                GoogleSheetsSettings(
                    spreadsheet_id='sheet-123',
                    service_account_json='{"type":"service_account"}',
                )
            )

    def test_authenticated_gateway_can_delete_rows(self) -> None:
        gateway = GoogleSheetsTableGateway(
            settings=self.auth_settings,
            expected_headers=self.mapper.ordered_headers,
            api_service=Mock(),
        )
        gateway._load_snapshot = Mock(return_value=type('Snapshot', (), {'sheet_name': 'Inventory Assets', 'sheet_id': 42, 'headers': self.mapper.ordered_headers})())
        gateway._spreadsheets = Mock()
        gateway._spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}

        gateway.delete_row('Inventory Assets', 5)

        body = gateway._spreadsheets.return_value.batchUpdate.call_args.kwargs['body']
        delete_range = body['requests'][0]['deleteDimension']['range']
        self.assertEqual(delete_range['sheetId'], 42)
        self.assertEqual(delete_range['startIndex'], 4)
        self.assertEqual(delete_range['endIndex'], 5)

    def test_build_google_sheets_gateway_validates_on_construction(self) -> None:
        fake_gateway = GoogleSheetsTableGateway(settings=self.public_settings, expected_headers=self.mapper.ordered_headers)
        with patch.object(fake_gateway, 'validate_connection', return_value=None) as validate_connection, patch(
            'vigilance_assets.google_sheets.GoogleSheetsTableGateway', return_value=fake_gateway
        ) as gateway_class:
            gateway = build_google_sheets_gateway(self.public_settings, self.mapper.ordered_headers)

        self.assertIs(gateway, fake_gateway)
        gateway_class.assert_called_once()
        validate_connection.assert_called_once_with()

    def test_public_sheet_writes_raise_read_only_error(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.public_settings, expected_headers=self.mapper.ordered_headers)

        with self.assertRaisesRegex(GoogleSheetsReadOnlyError, 'read-only'):
            gateway.append_row('Inventory Assets', {'Asset_ID': 'AST-001'})

    def test_missing_public_sheet_surfaces_clear_error(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.public_settings, expected_headers=self.mapper.ordered_headers)
        error = HTTPError('https://example.test', 404, 'Not Found', hdrs=None, fp=None)

        with patch('vigilance_assets.google_sheets.urlopen', side_effect=error):
            with self.assertRaisesRegex(GoogleSheetsWorksheetError, 'publicly accessible'):
                gateway.validate_connection()

    def test_service_account_json_must_be_valid_json(self) -> None:
        with self.assertRaisesRegex(GoogleSheetsConfigurationError, 'not valid JSON'):
            _load_service_account_credentials(
                GoogleSheetsSettings(spreadsheet_id='sheet-123', service_account_json='not-json')
            )


if __name__ == '__main__':
    unittest.main()
