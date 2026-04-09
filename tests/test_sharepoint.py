from __future__ import annotations

import unittest
from urllib.parse import unquote

from vigilance_assets.config import SharePointSettings
from vigilance_assets.sharepoint import SharePointTableGateway
from vigilance_assets.spreadsheet import AssetSpreadsheetMapper


class FakeGraphClient:
    def __init__(self, used_rows: list[list[str]], post_append_rows: list[list[str]] | None = None) -> None:
        self.used_rows = used_rows
        self.post_append_rows = post_append_rows
        self.patch_calls: list[tuple[str, dict[str, object], dict[str, str] | None]] = []
        self.delete_calls: list[tuple[str, dict[str, object], dict[str, str] | None]] = []
        self.session_calls: list[tuple[str, dict[str, object] | None]] = []
        self.get_calls: list[tuple[str, dict[str, str] | None]] = []

    def get(self, path: str, *, headers: dict[str, str] | None = None):
        self.get_calls.append((path, headers))
        if path.endswith('/usedRange(valuesOnly=false)'):
            if self.patch_calls and self.post_append_rows is not None:
                return {'values': self.post_append_rows}
            return {'values': self.used_rows}
        if path.endswith('/drive'):
            return {'id': 'drive-1'}
        if '/root:/' in path:
            return {'id': 'item-1'}
        return {'id': 'site-1'}

    def patch(self, path: str, payload: dict[str, object], *, headers: dict[str, str] | None = None):
        self.patch_calls.append((path, payload, headers))
        return {}

    def post(self, path: str, payload: dict[str, object] | None = None, *, headers: dict[str, str] | None = None):
        if path.endswith('/workbook/createSession'):
            self.session_calls.append((path, payload))
            return {'id': 'session-123'}
        self.delete_calls.append((path, payload or {}, headers))
        return {}


class SharePointGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = AssetSpreadsheetMapper()
        self.settings = SharePointSettings(
            tenant_id='tenant',
            client_id='client',
            client_secret='secret',
            site_id='site-1',
            drive_id='drive-1',
            item_id='item-1',
            worksheet_name='Inventory Assets',
        )

    def test_build_snapshot_ignores_decorative_row_and_separator_columns(self) -> None:
        gateway = SharePointTableGateway(settings=self.settings, expected_headers=self.mapper.ordered_headers)
        headers = list(self.mapper.ordered_headers)
        tool_idx = headers.index('Tool_Type')
        service_idx = headers.index('Service_Type')
        actual_headers = headers[:tool_idx] + [' Tool_Type ', ''] + headers[tool_idx + 1:service_idx] + [''] + headers[service_idx:]
        decorative = [''] * len(actual_headers)
        decorative[tool_idx] = 'CYBERSECURITY TOOL–SPECIFIC FIELDS'
        data = [''] * len(actual_headers)
        normalized_columns = {
            gateway._normalize_header_key(v): i
            for i, v in enumerate(actual_headers)
            if gateway._normalize_header_key(v)
        }
        values = {
            'Asset_ID': 'AST-001',
            'Asset_Name': 'Threat Radar',
            'Asset_Category': 'Cybersecurity Tool',
            'Owner_Org': 'OpenAI Security Lab',
            'Owner_Contact': 'alice@example.org',
            'Pilot (s)': 'Pilot A',
            'Purpose (1-2 sentences)': 'Aggregates findings.',
            'Status': 'Active',
            'TRL_Start': '4',
            'TRL_Target': '7',
            'Related_Result': 'RS3',
            'Related_WP_Task': 'T5.3',
            'Deployment_Context': 'Cloud',
            'Last_Updated': '2026-03-21',
            'Updated_By': 'alice@example.org',
            'Tool_Type': 'SIEM (Security Information and Event Management)',
        }
        for header, value in values.items():
            data[normalized_columns[gateway._normalize_header_key(header)]] = value

        snapshot = gateway._build_snapshot(sheet_name='Inventory Assets', raw_rows=[decorative, actual_headers, data])

        self.assertEqual(snapshot.header_row_number, 2)
        self.assertEqual(snapshot.rows[0].row_number, 3)
        self.assertEqual(snapshot.rows[0].values['Asset_ID'], 'AST-001')

    def test_append_row_writes_aligned_range_and_preserves_separator_columns(self) -> None:
        headers = list(self.mapper.ordered_headers)
        tool_idx = headers.index('Tool_Type')
        service_idx = headers.index('Service_Type')
        actual_headers = headers[:tool_idx] + ['Tool_Type', ''] + headers[tool_idx + 1:service_idx] + [''] + headers[service_idx:]
        existing = ['AST-001', 'Threat Radar', 'Cybersecurity Tool'] + [''] * (len(actual_headers) - 3)
        appended = [''] * len(actual_headers)
        appended[0] = 'AST-002'
        appended[1] = 'Beacon'
        appended[2] = 'Cybersecurity Tool'
        appended[tool_idx] = 'EDR (Endpoint Detection and Response)'

        graph = FakeGraphClient(
            used_rows=[['decorative'] + [''] * (len(actual_headers) - 1), actual_headers, existing],
            post_append_rows=[['decorative'] + [''] * (len(actual_headers) - 1), actual_headers, existing, appended],
        )
        gateway = SharePointTableGateway(
            settings=self.settings,
            expected_headers=self.mapper.ordered_headers,
            graph_client=graph,
        )

        record = gateway.append_row(
            'Inventory Assets',
            {
                'Asset_ID': 'AST-002',
                'Asset_Name': 'Beacon',
                'Asset_Category': 'Cybersecurity Tool',
                'Tool_Type': 'EDR (Endpoint Detection and Response)',
            },
        )

        self.assertEqual(record.row_number, 4)
        patch_path, payload, headers = graph.patch_calls[0]
        end_column = gateway._column_index_to_a1(len(actual_headers) - 1)
        self.assertIn(f"range(address='A4:{end_column}4')", unquote(patch_path))
        self.assertEqual(headers, {'workbook-session-id': 'session-123'})
        sent_values = payload['values'][0]
        self.assertEqual(sent_values[tool_idx], 'EDR (Endpoint Detection and Response)')
        self.assertEqual(sent_values[tool_idx + 1], '')
        self.assertEqual(sent_values[service_idx + 1], '')
        self.assertEqual(len(graph.session_calls), 1)

    def test_resolve_item_id_uses_root_path_addressing_with_trailing_colon(self) -> None:
        settings = SharePointSettings(
            tenant_id='tenant',
            client_id='client',
            client_secret='secret',
            site_id='site-1',
            drive_id='drive-1',
            workbook_path='Shared Documents/inventory.xlsx',
        )
        graph = FakeGraphClient(used_rows=[['Asset_ID', 'Asset_Category']])
        gateway = SharePointTableGateway(
            settings=settings,
            expected_headers=self.mapper.ordered_headers,
            graph_client=graph,
            use_workbook_sessions=False,
        )

        gateway._resolved_item_id = None
        gateway._resolve_item_id('site-1', 'drive-1')

        path_calls = [path for path, _ in graph.get_calls if '/root:/' in path]
        self.assertTrue(path_calls)
        self.assertTrue(path_calls[0].endswith(':'))

    def test_mapper_orders_data_origin_after_sharing_policy(self) -> None:
        headers = list(self.mapper.ordered_headers)
        self.assertGreater(headers.index('Data_Origin'), headers.index('Sharing_Policy'))


if __name__ == '__main__':
    unittest.main()
