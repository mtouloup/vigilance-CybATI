from __future__ import annotations

import unittest

from vigilance_assets import (
    GoogleSheetsTableGateway,
    ConfigurationError,
    SpreadsheetGatewayFactoryError,
    SpreadsheetGatewayFactoryRegistry,
    build_spreadsheet_repository,
    load_runtime_settings,
)
from vigilance_assets.spreadsheet import SheetRecord


class StubGateway:
    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        return []

    def append_row(self, sheet_name: str, values: dict[str, object]) -> SheetRecord:
        raise AssertionError("not used")

    def update_row(self, sheet_name: str, row_number: int, values: dict[str, object]) -> SheetRecord:
        raise AssertionError("not used")

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        raise AssertionError("not used")


class ConfigTests(unittest.TestCase):
    def test_load_runtime_settings_defaults_to_memory_backend(self) -> None:
        settings = load_runtime_settings({})

        self.assertEqual(settings.spreadsheet.backend, "memory")
        self.assertEqual(settings.spreadsheet.resolved_workbook_reference, "in-memory")

    def test_load_runtime_settings_supports_google_sheets_backend(self) -> None:
        settings = load_runtime_settings(
            {
                "VIGILANCE_SPREADSHEET_BACKEND": "google_sheets",
                "VIGILANCE_SPREADSHEET_GOOGLE_ID": "sheet-123",
                "VIGILANCE_GOOGLE_CREDENTIALS_PATH": "/tmp/creds.json",
            }
        )

        self.assertEqual(settings.spreadsheet.backend, "google_sheets")
        self.assertEqual(settings.spreadsheet.google_sheets.spreadsheet_id, "sheet-123")
        self.assertEqual(settings.spreadsheet.resolved_workbook_reference, "sheet-123")


    def test_load_runtime_settings_supports_google_sheets_mode(self) -> None:
        settings = load_runtime_settings(
            {
                "VIGILANCE_SPREADSHEET_BACKEND": "google_sheets",
                "VIGILANCE_SPREADSHEET_GOOGLE_ID": "sheet-123",
                "VIGILANCE_GOOGLE_SHEETS_MODE": "read_only",
            }
        )

        self.assertEqual(settings.spreadsheet.google_sheets.mode, "read_only")

    def test_load_runtime_settings_requires_workbook_path_for_workbook_backend(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_runtime_settings({"VIGILANCE_SPREADSHEET_BACKEND": "workbook"})

    def test_load_runtime_settings_validates_boolean_values(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_runtime_settings(
                {
                    "VIGILANCE_SPREADSHEET_BACKEND": "workbook",
                    "VIGILANCE_SPREADSHEET_WORKBOOK_PATH": "inventory.xlsx",
                    "VIGILANCE_SPREADSHEET_WORKBOOK_READ_ONLY": "maybe",
                }
            )

    def test_build_spreadsheet_repository_uses_registered_gateway_factory(self) -> None:
        registry = SpreadsheetGatewayFactoryRegistry()
        registry.register("workbook", lambda settings: StubGateway())

        repository = build_spreadsheet_repository(
            env={
                "VIGILANCE_SPREADSHEET_BACKEND": "workbook",
                "VIGILANCE_SPREADSHEET_WORKBOOK_PATH": "inventory.xlsx",
            },
            gateway_factories=registry,
        )

        self.assertEqual(repository.workbook_reference, "inventory.xlsx")
        self.assertIsInstance(repository.gateway, StubGateway)


    def test_build_spreadsheet_repository_registers_default_google_sheets_factory(self) -> None:
        repository = build_spreadsheet_repository(
            env={
                "VIGILANCE_SPREADSHEET_BACKEND": "google_sheets",
                "VIGILANCE_SPREADSHEET_GOOGLE_ID": "sheet-123",
                "VIGILANCE_GOOGLE_SHEETS_MODE": "read_only",
            },
        )

        self.assertIsInstance(repository.gateway, GoogleSheetsTableGateway)

    def test_build_spreadsheet_repository_requires_registered_backend_factory(self) -> None:
        with self.assertRaises(SpreadsheetGatewayFactoryError):
            build_spreadsheet_repository(
                env={
                    "VIGILANCE_SPREADSHEET_BACKEND": "google_sheets",
                    "VIGILANCE_SPREADSHEET_GOOGLE_ID": "sheet-123",
                },
                gateway_factories=SpreadsheetGatewayFactoryRegistry(),
            )


if __name__ == "__main__":
    unittest.main()
