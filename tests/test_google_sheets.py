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

    def test_build_snapshot_skips_blank_and_non_asset_rows_after_header(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers)
        headers = list(self.mapper.ordered_headers)
        blank_row = [""] * len(headers)
        partial_row = [""] * len(headers)
        partial_row[headers.index("Asset_Name")] = "Separator-ish row"
        valid_row = [""] * len(headers)
        valid_values = {
            "Asset_ID": "AST-010",
            "Asset_Name": "Threat Radar",
            "Asset_Category": "Cybersecurity Tool",
            "Owner_Org": "OpenAI Security Lab",
            "Owner_Contact": "alice@example.org",
            "Pilot (s)": "Pilot A",
            "Purpose (1-2 sentences)": "Aggregates threat findings for analysts.",
            "Status": "Active",
            "TRL_Start": "4",
            "TRL_Target": "7",
            "Related_Result": "RS3",
            "Related_WP_Task": "T5.3",
            "Deployment_Context": "Cloud",
            "Last_Updated": "2026-03-21",
            "Updated_By": "alice@example.org",
            "Tool_Type": "SIEM (Security Information and Event Management)",
        }
        for index, header in enumerate(headers):
            if header in valid_values:
                valid_row[index] = valid_values[header]

        snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=None,
            raw_rows=[headers, blank_row, partial_row, valid_row],
        )

        self.assertEqual(len(snapshot.rows), 1)
        self.assertEqual(snapshot.rows[0].row_number, 4)
        self.assertEqual(snapshot.rows[0].values['Asset_ID'], 'AST-010')

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
        self.assertEqual(snapshot.header_row_number, 2)
        self.assertEqual(snapshot.worksheet_column_count, row_length)
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

    def test_append_row_targets_canonical_header_row_with_separator_columns(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers, api_service=Mock())
        headers = list(self.mapper.ordered_headers)
        tool_type_index = headers.index('Tool_Type')
        service_type_index = headers.index('Service_Type')
        row_length = len(headers) + 2
        end_column = gateway._column_index_to_a1(row_length - 1)
        actual_header_row = headers[:tool_type_index] + ['Tool_Type', ''] + headers[tool_type_index + 1:service_type_index] + [''] + headers[service_type_index:]

        initial_snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=12,
            raw_rows=[
                ['Decorative groupings'] + [''] * (row_length - 1),
                actual_header_row,
                ['AST-001', 'Threat Radar', 'Cybersecurity Tool'] + [''] * (row_length - 3),
            ],
        )
        appended_row = [''] * row_length
        appended_row[0] = 'ASSET-003'
        appended_row[1] = 'Fresh Asset'
        appended_row[2] = 'Cybersecurity Tool'
        appended_row[tool_type_index] = 'SIEM (Security Information and Event Management)'
        appended_snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=12,
            raw_rows=[
                ['Decorative groupings'] + [''] * (row_length - 1),
                actual_header_row,
                ['AST-001', 'Threat Radar', 'Cybersecurity Tool'] + [''] * (row_length - 3),
                appended_row,
            ],
        )
        gateway._load_snapshot = Mock(side_effect=[initial_snapshot, appended_snapshot])
        values_resource = Mock()
        values_resource.append.return_value.execute.return_value = {
            'updates': {
                'updatedRange': f"'Inventory Assets'!A4:{end_column}4",
                'updatedRows': 1,
                'updatedColumns': row_length,
            }
        }
        gateway._spreadsheets_values = Mock(return_value=values_resource)

        record = gateway.append_row('Inventory Assets', {
            'Asset_ID': 'ASSET-003',
            'Asset_Name': 'Fresh Asset',
            'Asset_Category': 'Cybersecurity Tool',
            'Tool_Type': 'SIEM (Security Information and Event Management)',
        })

        append_kwargs = values_resource.append.call_args.kwargs
        self.assertEqual(append_kwargs['range'], f"'Inventory Assets'!A2:{end_column}")
        sent_values = append_kwargs['body']['values'][0]
        self.assertEqual(len(sent_values), row_length)
        self.assertEqual(sent_values[0], 'ASSET-003')
        self.assertEqual(sent_values[1], 'Fresh Asset')
        self.assertEqual(sent_values[tool_type_index], 'SIEM (Security Information and Event Management)')
        self.assertEqual(sent_values[tool_type_index + 1], '')
        self.assertEqual(sent_values[service_type_index + 1], '')
        self.assertEqual(record.row_number, 4)
        self.assertEqual(record.values['Asset_ID'], 'ASSET-003')

    def test_append_row_aligns_common_and_selected_category_columns_only(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers, api_service=Mock())
        headers = list(self.mapper.ordered_headers)
        actual_header_row, canonical_column_map = self._header_with_category_separators(gateway, headers)
        row_length = len(actual_header_row)
        end_column = gateway._column_index_to_a1(row_length - 1)

        initial_snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=12,
            raw_rows=[
                ['Decorative groupings'] + [''] * (row_length - 1),
                actual_header_row,
                ['AST-001', 'Threat Radar', 'Cybersecurity Tool'] + [''] * (row_length - 3),
            ],
        )
        gateway._load_snapshot = Mock(return_value=initial_snapshot)
        values_resource = Mock()
        values_resource.append.return_value.execute.return_value = {
            'updates': {
                'updatedRange': f"'Inventory Assets'!A4:{end_column}4",
                'updatedRows': 1,
                'updatedColumns': row_length,
            }
        }
        gateway._spreadsheets_values = Mock(return_value=values_resource)
        gateway._find_appended_row = Mock(return_value=Mock(row_number=4, values={'Asset_ID': 'AST-777'}))

        cases = [
            (
                'Cybersecurity Tool',
                {'Tool_Type': 'SIEM (Security Information and Event Management)'},
                {'Tool_Type'},
                {'Service_Type', 'Compute_Form'},
            ),
            (
                'Platform / Service',
                {'Service_Type': 'Security Service'},
                {'Service_Type'},
                {'Tool_Type', 'Compute_Form'},
            ),
            (
                'Compute Resource',
                {'Compute_Form': 'Container'},
                {'Compute_Form'},
                {'Tool_Type', 'Service_Type'},
            ),
        ]
        for category, category_values, expected_filled, expected_blank in cases:
            with self.subTest(category=category):
                payload = {
                    'Asset_ID': 'AST-777',
                    'Asset_Name': f'{category} asset',
                    'Asset_Category': category,
                    **category_values,
                }
                gateway.append_row('Inventory Assets', payload)
                append_kwargs = values_resource.append.call_args.kwargs
                self.assertEqual(append_kwargs['range'], f"'Inventory Assets'!A2:{end_column}")
                sent_values = append_kwargs['body']['values'][0]
                self.assertEqual(len(sent_values), row_length)
                self.assertEqual(sent_values[canonical_column_map['Asset_ID']], 'AST-777')
                self.assertEqual(sent_values[canonical_column_map['Asset_Name']], f'{category} asset')
                self.assertEqual(sent_values[canonical_column_map['Asset_Category']], category)
                for field_name in expected_filled:
                    self.assertNotEqual(sent_values[canonical_column_map[field_name]], '')
                for field_name in expected_blank:
                    self.assertEqual(sent_values[canonical_column_map[field_name]], '')

                separator_indexes = [index for index, value in enumerate(actual_header_row) if not gateway._normalize_header_key(value)]
                self.assertTrue(separator_indexes)
                for separator_index in separator_indexes:
                    self.assertEqual(sent_values[separator_index], '')

    def test_append_row_anchors_to_first_canonical_column_when_sheet_has_leading_decorative_columns(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers, api_service=Mock())
        headers = list(self.mapper.ordered_headers)
        leading_padding = 52  # Column BA.
        actual_header_row = ([''] * leading_padding) + headers
        row_length = len(actual_header_row)
        end_column = gateway._column_index_to_a1(row_length - 1)
        first_canonical_column = gateway._column_index_to_a1(leading_padding)

        snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=12,
            raw_rows=[
                ['Decorative groupings'] + [''] * (row_length - 1),
                actual_header_row,
            ],
        )
        gateway._load_snapshot = Mock(return_value=snapshot)
        values_resource = Mock()
        values_resource.append.return_value.execute.return_value = {
            'updates': {
                'updatedRange': f"'Inventory Assets'!{first_canonical_column}3:{end_column}3",
                'updatedRows': 1,
                'updatedColumns': len(headers),
            }
        }
        gateway._spreadsheets_values = Mock(return_value=values_resource)
        gateway._find_appended_row = Mock(return_value=Mock(row_number=3, values={'Asset_ID': 'ASSET-900'}))

        gateway.append_row('Inventory Assets', {
            'Asset_ID': 'ASSET-900',
            'Asset_Name': 'Anchored asset',
            'Asset_Category': 'Cybersecurity Tool',
            'Tool_Type': 'SIEM (Security Information and Event Management)',
        })

        append_kwargs = values_resource.append.call_args.kwargs
        self.assertEqual(append_kwargs['range'], f"'Inventory Assets'!{first_canonical_column}2:{end_column}")
        sent_values = append_kwargs['body']['values'][0]
        self.assertEqual(len(sent_values), len(headers))
        self.assertEqual(sent_values[0], 'ASSET-900')
        self.assertEqual(sent_values[1], 'Anchored asset')
        self.assertEqual(sent_values[2], 'Cybersecurity Tool')
        self.assertEqual(sent_values[headers.index('Tool_Type')], 'SIEM (Security Information and Event Management)')

    def test_aligned_row_round_trip_preserves_separators_and_column_mapping(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers, api_service=Mock())
        headers = list(self.mapper.ordered_headers)
        actual_header_row, canonical_column_map = self._header_with_category_separators(gateway, headers)
        row_length = len(actual_header_row)
        row = [''] * row_length
        row[canonical_column_map['Asset_ID']] = 'AST-314'
        row[canonical_column_map['Asset_Name']] = 'Compute host'
        row[canonical_column_map['Asset_Category']] = 'Compute Resource'
        row[canonical_column_map['Compute_Form']] = 'VM'
        row[canonical_column_map['Service_Type']] = ''

        snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=12,
            raw_rows=[
                ['Decorative'] + [''] * (row_length - 1),
                actual_header_row,
                row,
            ],
        )

        parsed_values = snapshot.rows[0].values
        rebuilt = gateway._row_to_worksheet_values(parsed_values, snapshot)
        self.assertEqual(len(rebuilt), row_length)
        self.assertEqual(rebuilt[canonical_column_map['Asset_ID']], 'AST-314')
        self.assertEqual(rebuilt[canonical_column_map['Compute_Form']], 'VM')
        self.assertEqual(rebuilt[canonical_column_map['Service_Type']], '')
        separator_indexes = [index for index, value in enumerate(actual_header_row) if not gateway._normalize_header_key(value)]
        for separator_index in separator_indexes:
            self.assertEqual(rebuilt[separator_index], '')

    def test_append_row_preserves_separator_column_alignment_with_prefixed_layout(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers, api_service=Mock())
        headers = list(self.mapper.ordered_headers)
        prefixed_headers = [''] * 2
        actual_header_row, canonical_column_map = self._header_with_category_separators(
            gateway,
            headers,
            prefix_columns=prefixed_headers,
        )
        row_length = len(actual_header_row)
        first_canonical_index = min(canonical_column_map.values())
        first_canonical_column = gateway._column_index_to_a1(first_canonical_index)
        end_column = gateway._column_index_to_a1(row_length - 1)

        snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=12,
            raw_rows=[
                ['Decorative groupings'] + [''] * (row_length - 1),
                actual_header_row,
            ],
        )
        gateway._load_snapshot = Mock(return_value=snapshot)
        values_resource = Mock()
        values_resource.append.return_value.execute.return_value = {
            'updates': {
                'updatedRange': f"'Inventory Assets'!{first_canonical_column}3:{end_column}3",
                'updatedRows': 1,
                'updatedColumns': row_length - first_canonical_index,
            }
        }
        gateway._spreadsheets_values = Mock(return_value=values_resource)
        gateway._find_appended_row = Mock(return_value=Mock(row_number=3, values={'Asset_ID': 'AST-777'}))

        gateway.append_row('Inventory Assets', {
            'Asset_ID': 'AST-777',
            'Asset_Name': 'Cyber tool',
            'Asset_Category': 'Cybersecurity Tool',
            'Tool_Type': 'SIEM (Security Information and Event Management)',
            'Service_Type': None,
        })

        append_kwargs = values_resource.append.call_args.kwargs
        self.assertEqual(append_kwargs['range'], f"'Inventory Assets'!{first_canonical_column}2:{end_column}")
        sent_values = append_kwargs['body']['values'][0]
        self.assertEqual(sent_values[0], 'AST-777')
        self.assertEqual(sent_values[1], 'Cyber tool')
        self.assertEqual(sent_values[2], 'Cybersecurity Tool')

        service_rel_index = canonical_column_map['Service_Type'] - first_canonical_index
        tool_rel_index = canonical_column_map['Tool_Type'] - first_canonical_index
        self.assertEqual(sent_values[tool_rel_index], 'SIEM (Security Information and Event Management)')
        self.assertEqual(sent_values[service_rel_index], '')
        separator_indexes = [index for index, value in enumerate(actual_header_row) if not gateway._normalize_header_key(value)]
        for separator_index in separator_indexes:
            if separator_index < first_canonical_index:
                continue
            self.assertEqual(sent_values[separator_index - first_canonical_index], '')

    def test_append_row_requires_confirmed_google_api_update_metadata(self) -> None:
        gateway = GoogleSheetsTableGateway(settings=self.auth_settings, expected_headers=self.mapper.ordered_headers, api_service=Mock())
        snapshot = gateway._build_snapshot(
            sheet_name='Inventory Assets',
            sheet_id=12,
            raw_rows=[list(self.mapper.ordered_headers)],
        )
        gateway._load_snapshot = Mock(return_value=snapshot)
        values_resource = Mock()
        values_resource.append.return_value.execute.return_value = {'updates': {'updatedRows': 0}}
        gateway._spreadsheets_values = Mock(return_value=values_resource)

        with self.assertRaisesRegex(GoogleSheetsWorksheetError, 'did not confirm a single appended row'):
            gateway.append_row('Inventory Assets', {'Asset_ID': 'ASSET-003'})

    @staticmethod
    def _header_with_category_separators(
        gateway: GoogleSheetsTableGateway,
        headers: list[str],
        prefix_columns: list[str] | None = None,
    ) -> tuple[list[str], dict[str, int]]:
        block_starts = {'Service_Type', 'Compute_Form', 'Telemetry_Type', 'Store_Type', 'Asset_Subtype'}
        expanded_headers: list[str] = list(prefix_columns or [])
        for header in headers:
            if header in block_starts:
                expanded_headers.append('')
            expanded_headers.append(header)
        canonical_column_map = {
            gateway._normalized_expected_headers[gateway._normalize_header_key(header)]: index
            for index, header in enumerate(expanded_headers)
            if gateway._normalize_header_key(header)
        }
        return expanded_headers, canonical_column_map


if __name__ == '__main__':
    unittest.main()
