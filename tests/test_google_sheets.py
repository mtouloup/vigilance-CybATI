from __future__ import annotations

import unittest
from unittest.mock import patch

from vigilance_assets.google_sheets import (
    GoogleSheetsConfigurationError,
    GoogleSheetsTableGateway,
    GoogleSheetsWorksheetError,
    build_google_sheets_gateway,
)
from vigilance_assets.spreadsheet import AssetSpreadsheetMapper
from vigilance_assets.config import GoogleSheetsSettings, SheetNames, SpreadsheetBackendSettings


class _Response:
    def __init__(self, payload: str) -> None:
        self.payload = payload.encode('utf-8')

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class GoogleSheetsGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = AssetSpreadsheetMapper()
        self.settings = GoogleSheetsSettings(
            spreadsheet_id='sheet-123',
            mode='read_only',
        )
        self.gateway = GoogleSheetsTableGateway(
            settings=self.settings,
            sheet_names=SheetNames(assets='Inventory Assets'),
            expected_headers=self.mapper.ordered_headers,
        )

    def test_list_rows_reads_public_gviz_data_and_uses_configured_sheet_name(self) -> None:
        import vigilance_assets.google_sheets as module

        payload = (
            'google.visualization.Query.setResponse('
            '{"status":"ok","table":{"rows":['
            '{"c":[null,null,null]},'
            '{"c":['
            + ','.join('{"v":"%s"}' % header.replace('"', '\\"') for header in self.mapper.ordered_headers)
            + ']},'
            '{"c":['
            '{"v":"AST-001"},'
            '{"v":"Threat Radar"},'
            '{"v":"Cybersecurity Tool"},'
            '{"v":"OpenAI Security Lab"},'
            '{"v":"alice@example.org"},'
            '{"v":"Pilot A"},'
            '{"v":"Aggregates threat findings for analysts."},'
            '{"v":"Active"},'
            '{"v":"4"},'
            '{"v":"5"},'
            '{"v":"7"},'
            '{"v":"RS3"},'
            '{"v":"T5.3"},'
            '{"v":"Cloud"},'
            '{"v":"IEC 62443"},'
            '{"v":"Cloud Security"},'
            '{"v":"https://example.org/tool"},'
            '{"v":"2026-03-21"},'
            '{"v":"alice@example.org"},'
            '{"v":"SIEM (Security Information and Event Management)"}'
            + ',null' * (len(self.mapper.ordered_headers) - 20)
            + ']}'
            ']}});'
        )
        seen_urls: list[str] = []
        original_urlopen = module.urlopen
        module.urlopen = lambda url, timeout=20.0: seen_urls.append(url) or _Response(payload)
        try:
            rows = self.gateway.list_rows('ASSETS')
        finally:
            module.urlopen = original_urlopen

        self.assertEqual(len(rows), 1)
        self.assertIn('sheet=Inventory%20Assets', seen_urls[0])
        self.assertEqual(rows[0].row_number, 3)
        self.assertEqual(rows[0].values['Asset_ID'], 'AST-001')
        self.assertEqual(rows[0].values['Pilot (s)'], 'Pilot A')

    def test_list_rows_in_auto_mode_falls_back_to_public_read_when_credentials_missing(self) -> None:
        import vigilance_assets.google_sheets as module

        gateway = GoogleSheetsTableGateway(
            settings=GoogleSheetsSettings(spreadsheet_id='sheet-123', mode='auto'),
            expected_headers=self.mapper.ordered_headers,
        )
        payload = (
            'google.visualization.Query.setResponse('
            '{"status":"ok","table":{"rows":['
            '{"c":['
            + ','.join('{"v":"%s"}' % header.replace('"', '\\"') for header in self.mapper.ordered_headers)
            + ']},'
            '{"c":[{"v":"AST-777"},{"v":"Fallback Asset"},{"v":"Cybersecurity Tool"}'
            + ',null' * (len(self.mapper.ordered_headers) - 3)
            + ']}'
            ']}});'
        )

        with patch.object(module, 'urlopen', return_value=_Response(payload)) as mock_urlopen:
            rows = gateway.list_rows('ASSETS')

        self.assertEqual(rows[0].values['Asset_ID'], 'AST-777')
        self.assertEqual(mock_urlopen.call_count, 1)

    def test_build_snapshot_requires_expected_headers_by_name(self) -> None:
        raw_rows = [
            ['Asset_ID', 'Asset_Name', 'Asset_Category'],
            ['AST-001', 'Threat Radar', 'Cybersecurity Tool'],
        ]

        with self.assertRaises(GoogleSheetsWorksheetError):
            self.gateway._build_snapshot(sheet_name='ASSETS', sheet_id=None, raw_rows=raw_rows)

    def test_build_google_sheets_gateway_uses_canonical_header_mapping(self) -> None:
        gateway = build_google_sheets_gateway(
            SpreadsheetBackendSettings(
                backend='google_sheets',
                sheets=SheetNames(assets='Inventory Assets', vocabularies='Controlled Vocabulary'),
                google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-123', mode='read_only'),
            )
        )

        self.assertEqual(gateway.sheet_names.assets, 'Inventory Assets')
        self.assertIn('Pilot (s)', gateway.expected_headers)
        self.assertIn('Purpose (1-2 sentences)', gateway.expected_headers)

    def test_append_row_rejects_read_only_mode(self) -> None:
        with self.assertRaises(GoogleSheetsConfigurationError):
            self.gateway.append_row('ASSETS', {'Asset_ID': 'AST-999'})

    def test_read_write_mode_requires_credentials_for_authenticated_access(self) -> None:
        gateway = GoogleSheetsTableGateway(
            settings=GoogleSheetsSettings(spreadsheet_id='sheet-123', mode='read_write'),
            expected_headers=self.mapper.ordered_headers,
        )

        with self.assertRaises(GoogleSheetsConfigurationError):
            gateway.list_rows('ASSETS')


if __name__ == '__main__':
    unittest.main()
