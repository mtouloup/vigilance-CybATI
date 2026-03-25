from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from .config import SharePointSettings
from .schema import load_schema_catalog
from .spreadsheet import RowData, SheetRecord, SpreadsheetBackendError, SpreadsheetTableGateway

LOGGER = logging.getLogger(__name__)
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class SharePointConfigurationError(SpreadsheetBackendError):
    """Raised when SharePoint configuration is invalid."""


class SharePointConnectivityError(SpreadsheetBackendError):
    """Raised when the SharePoint backend cannot be reached."""


class SharePointWorksheetError(SpreadsheetBackendError):
    """Raised when the ASSETS worksheet cannot be resolved or parsed."""


@dataclass(frozen=True, slots=True)
class WorksheetSnapshot:
    sheet_name: str
    headers: tuple[str, ...]
    header_row_number: int
    canonical_indexes: tuple[int, ...]
    canonical_header_by_column: tuple[str | None, ...]
    canonical_index_by_header: Mapping[str, int]
    asset_id_column_index: int
    write_start_column_index: int
    write_end_column_index: int
    worksheet_column_count: int
    rows: tuple[SheetRecord, ...]


@dataclass(frozen=True, slots=True)
class HeaderSelection:
    header_row_index: int
    headers: tuple[str, ...]
    canonical_headers: tuple[str, ...]
    canonical_indexes: tuple[int, ...]
    matched_count: int


@dataclass(slots=True)
class GraphApiClient:
    settings: SharePointSettings
    timeout_seconds: float = 20.0
    _access_token: str | None = None

    def _token(self) -> str:
        if self._access_token is None:
            self._access_token = self._request_access_token()
        return self._access_token

    def _request_access_token(self) -> str:
        token_url = f"https://login.microsoftonline.com/{self.settings.tenant_id}/oauth2/v2.0/token"
        body = urlencode(
            {
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "scope": GRAPH_SCOPE,
                "grant_type": "client_credentials",
            }
        ).encode("utf-8")
        request = Request(token_url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise SharePointConnectivityError("Failed to acquire Microsoft Graph access token.") from exc
        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise SharePointConfigurationError("Microsoft Graph token response did not include access_token.")
        return token

    def get(self, path: str) -> dict[str, Any]:
        return self._request_json("GET", path)

    def post(self, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._request_json("POST", path, payload)

    def patch(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._request_json("PATCH", path, payload)

    def _request_json(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        url = f"{GRAPH_BASE_URL}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            details = _extract_http_error_details(exc)
            raise SharePointConnectivityError(f"Microsoft Graph request failed: {details}.") from exc
        except (URLError, TimeoutError) as exc:
            raise SharePointConnectivityError("Failed to reach Microsoft Graph API.") from exc
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(loaded, dict):
            return loaded
        return {}


@dataclass(slots=True)
class SharePointTableGateway(SpreadsheetTableGateway):
    settings: SharePointSettings
    expected_headers: Sequence[str] = ()
    timeout_seconds: float = 20.0
    header_scan_limit: int = 10
    graph_client: GraphApiClient | None = None

    def __post_init__(self) -> None:
        self._expected_headers = tuple(self.expected_headers)
        self._expected_header_set = set(self._expected_headers)
        self._normalized_expected_headers = {
            self._normalize_header_key(header): header for header in self._expected_headers
        }
        catalog = load_schema_catalog()
        self._expected_asset_categories = set(catalog.category_fields)
        self._category_headers_by_category = {
            category: {field.sheet_header for field in fields}
            for category, fields in catalog.category_fields.items()
        }
        self._all_category_headers = set().union(*self._category_headers_by_category.values())
        self._graph_client = self.graph_client
        self._resolved_site_id: str | None = self.settings.site_id
        self._resolved_drive_id: str | None = self.settings.drive_id
        self._resolved_item_id: str | None = self.settings.item_id

    @property
    def is_read_only(self) -> bool:
        return False

    @property
    def worksheet_name(self) -> str:
        return self.settings.worksheet_name

    def validate_connection(self) -> WorksheetSnapshot:
        snapshot = self._load_snapshot(self.worksheet_name)
        LOGGER.info(
            "Configured SharePoint backend for site=%s worksheet=%s workbook=%s.",
            self.settings.site_id or self.settings.site_url,
            snapshot.sheet_name,
            self.settings.item_id or self.settings.workbook_path,
        )
        return snapshot

    def list_rows(self, sheet_name: str) -> list[SheetRecord]:
        snapshot = self._load_snapshot(sheet_name)
        return [SheetRecord(row_number=row.row_number, values=dict(row.values)) for row in snapshot.rows]

    def append_row(self, sheet_name: str, values: RowData) -> SheetRecord:
        snapshot = self._load_snapshot(sheet_name)
        next_empty_row = self._find_next_empty_data_row(snapshot)
        row_range = self._row_range(snapshot, row_number=next_empty_row)
        payload = {
            "values": [
                self._row_to_aligned_worksheet_values(
                    values,
                    snapshot,
                    start_column_index=snapshot.write_start_column_index,
                    end_column_index=snapshot.write_end_column_index,
                )
            ]
        }
        self._graph().patch(self._worksheet_endpoint(f"/range(address='{row_range}')"), payload)
        return self._find_appended_row(snapshot.sheet_name, values.get("Asset_ID"), appended_row_number=next_empty_row)

    def update_row(self, sheet_name: str, row_number: int, values: RowData) -> SheetRecord:
        snapshot = self._load_snapshot(sheet_name)
        row_range = self._row_range(snapshot, row_number=row_number)
        payload = {
            "values": [
                self._row_to_aligned_worksheet_values(
                    values,
                    snapshot,
                    start_column_index=snapshot.write_start_column_index,
                    end_column_index=snapshot.write_end_column_index,
                )
            ]
        }
        self._graph().patch(self._worksheet_endpoint(f"/range(address='{row_range}')"), payload)
        return SheetRecord(row_number=row_number, values=dict(values))

    def delete_row(self, sheet_name: str, row_number: int) -> None:
        snapshot = self._load_snapshot(sheet_name)
        delete_range = self._row_range(snapshot, row_number=row_number)
        self._graph().post(self._worksheet_endpoint(f"/range(address='{delete_range}')/delete"), {"shift": "Up"})

    def _load_snapshot(self, sheet_name: str) -> WorksheetSnapshot:
        resolved_sheet_name = self._resolve_sheet_name(sheet_name)
        response = self._graph().get(self._worksheet_endpoint("/usedRange(valuesOnly=false)"))
        raw_rows = response.get("values")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise SharePointWorksheetError(
                f"Worksheet {resolved_sheet_name!r} returned no data from Microsoft Graph usedRange API."
            )
        return self._build_snapshot(sheet_name=resolved_sheet_name, raw_rows=raw_rows)

    def _worksheet_endpoint(self, suffix: str) -> str:
        worksheet = quote(self.settings.worksheet_name, safe="")
        return f"{self._workbook_base_path()}/workbook/worksheets/{worksheet}{suffix}"

    def _workbook_base_path(self) -> str:
        site_id = self._resolve_site_id()
        drive_id = self._resolve_drive_id(site_id)
        item_id = self._resolve_item_id(site_id, drive_id)
        return f"/sites/{quote(site_id, safe='')}/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}"

    def _resolve_site_id(self) -> str:
        if self._resolved_site_id:
            return self._resolved_site_id
        if not self.settings.site_url:
            raise SharePointConfigurationError("SharePoint site identifier is missing.")
        parsed = urlparse(self.settings.site_url)
        if not parsed.hostname or not parsed.path:
            raise SharePointConfigurationError("VIGILANCE_SHAREPOINT_SITE_URL must be a full SharePoint site URL.")
        path = quote(parsed.path, safe="/")
        endpoint = f"/sites/{parsed.hostname}:{path}"
        response = self._graph().get(endpoint)
        site_id = response.get("id")
        if not isinstance(site_id, str) or not site_id:
            raise SharePointWorksheetError("Unable to resolve SharePoint site id from VIGILANCE_SHAREPOINT_SITE_URL.")
        self._resolved_site_id = site_id
        return site_id

    def _resolve_drive_id(self, site_id: str) -> str:
        if self._resolved_drive_id:
            return self._resolved_drive_id
        response = self._graph().get(f"/sites/{quote(site_id, safe='')}/drive")
        drive_id = response.get("id")
        if not isinstance(drive_id, str) or not drive_id:
            raise SharePointWorksheetError("Unable to resolve default SharePoint drive id for the configured site.")
        self._resolved_drive_id = drive_id
        return drive_id

    def _resolve_item_id(self, site_id: str, drive_id: str) -> str:
        if self._resolved_item_id:
            return self._resolved_item_id
        if not self.settings.workbook_path:
            raise SharePointConfigurationError("SharePoint workbook identifier is missing.")
        encoded_path = quote(self.settings.workbook_path.strip("/"), safe="/")
        response = self._graph().get(f"/sites/{quote(site_id, safe='')}/drives/{quote(drive_id, safe='')}/root:/{encoded_path}")
        item_id = response.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise SharePointWorksheetError("Unable to resolve workbook item id from VIGILANCE_SHAREPOINT_WORKBOOK_PATH.")
        self._resolved_item_id = item_id
        return item_id

    def _build_snapshot(self, *, sheet_name: str, raw_rows: Sequence[Sequence[Any]]) -> WorksheetSnapshot:
        selection = self._select_header_row(sheet_name, raw_rows)
        canonical_index_by_header = {
            canonical_header: column_index
            for canonical_header, column_index in zip(selection.canonical_headers, selection.canonical_indexes)
        }
        asset_id_column_index = canonical_index_by_header.get("Asset_ID")
        if asset_id_column_index is None:
            raise SharePointWorksheetError(
                f"Worksheet {sheet_name!r} header row {selection.header_row_index + 1} is missing required canonical header Asset_ID."
            )
        write_end_column_index = max(selection.canonical_indexes)
        records: list[SheetRecord] = []
        for row_number, row in enumerate(raw_rows[selection.header_row_index + 1 :], start=selection.header_row_index + 2):
            values = {
                canonical_header: self._normalize_inbound_value(row[column_index] if column_index < len(row) else None)
                for canonical_header, column_index in zip(selection.canonical_headers, selection.canonical_indexes)
            }
            if not any(value not in (None, "") for value in values.values()):
                continue
            if not self._looks_like_asset_row(values):
                continue
            records.append(SheetRecord(row_number=row_number, values=values))
        return WorksheetSnapshot(
            sheet_name=sheet_name,
            headers=selection.canonical_headers,
            header_row_number=selection.header_row_index + 1,
            canonical_indexes=selection.canonical_indexes,
            canonical_header_by_column=self._build_canonical_header_by_column(selection),
            canonical_index_by_header=canonical_index_by_header,
            asset_id_column_index=asset_id_column_index,
            write_start_column_index=asset_id_column_index,
            write_end_column_index=write_end_column_index,
            worksheet_column_count=len(selection.headers),
            rows=tuple(records),
        )

    def _looks_like_asset_row(self, values: Mapping[str, Any]) -> bool:
        asset_id = values.get("Asset_ID")
        asset_category = values.get("Asset_Category")
        if not isinstance(asset_id, str) or not asset_id.strip():
            return False
        if not isinstance(asset_category, str) or not asset_category.strip():
            return False
        return asset_category in self._expected_asset_categories

    def _select_header_row(self, sheet_name: str, raw_rows: Sequence[Sequence[Any]]) -> HeaderSelection:
        best_selection: HeaderSelection | None = None
        scan_limit = min(len(raw_rows), self.header_scan_limit)
        for row_index in range(scan_limit):
            selection = self._evaluate_header_row(row_index, raw_rows[row_index])
            if selection is None:
                continue
            if best_selection is None or selection.matched_count > best_selection.matched_count:
                best_selection = selection
        if best_selection is None:
            raise SharePointWorksheetError(
                f"Worksheet {sheet_name!r} does not contain a recognizable canonical ASSETS header row within the first {scan_limit} rows."
            )
        self._validate_detected_headers(sheet_name, best_selection)
        return best_selection

    def _evaluate_header_row(self, row_index: int, row: Sequence[Any]) -> HeaderSelection | None:
        canonical_headers: list[str] = []
        canonical_indexes: list[int] = []
        seen_headers: set[str] = set()
        for column_index, value in enumerate(row):
            normalized_key = self._normalize_header_key(value)
            if not normalized_key:
                continue
            canonical_header = self._normalized_expected_headers.get(normalized_key)
            if canonical_header is None or canonical_header in seen_headers:
                continue
            seen_headers.add(canonical_header)
            canonical_headers.append(canonical_header)
            canonical_indexes.append(column_index)
        if not canonical_headers:
            return None
        return HeaderSelection(
            header_row_index=row_index,
            headers=tuple(self._normalize_header(value) for value in row),
            canonical_headers=tuple(canonical_headers),
            canonical_indexes=tuple(canonical_indexes),
            matched_count=len(canonical_headers),
        )

    def _validate_detected_headers(self, sheet_name: str, selection: HeaderSelection) -> None:
        missing = sorted(self._expected_header_set.difference(selection.canonical_headers))
        if missing:
            raise SharePointWorksheetError(
                f"Worksheet {sheet_name!r} header row {selection.header_row_index + 1} is missing canonical headers: {', '.join(missing)}."
            )

    def _resolve_sheet_name(self, requested_sheet_name: str) -> str:
        if requested_sheet_name in {"ASSETS", self.settings.worksheet_name}:
            return self.settings.worksheet_name
        raise SharePointWorksheetError(f"Only the canonical ASSETS worksheet is supported; received {requested_sheet_name!r}.")

    def _row_to_worksheet_values(self, values: RowData, snapshot: WorksheetSnapshot) -> list[Any]:
        worksheet_values = [""] * snapshot.worksheet_column_count
        raw_category = values.get("Asset_Category")
        category = raw_category.strip() if isinstance(raw_category, str) else None
        allowed_category_headers = self._category_headers_by_category.get(category, set())
        for column_index, canonical_header in enumerate(snapshot.canonical_header_by_column):
            if canonical_header is None:
                continue
            if canonical_header in self._all_category_headers and canonical_header not in allowed_category_headers:
                worksheet_values[column_index] = ""
                continue
            worksheet_values[column_index] = self._serialize_outbound_value(values.get(canonical_header))
        return worksheet_values

    def _row_to_aligned_worksheet_values(
        self,
        values: RowData,
        snapshot: WorksheetSnapshot,
        *,
        start_column_index: int,
        end_column_index: int,
    ) -> list[Any]:
        worksheet_values = self._row_to_worksheet_values(values, snapshot)
        return worksheet_values[start_column_index : end_column_index + 1]

    def _build_canonical_header_by_column(self, selection: HeaderSelection) -> tuple[str | None, ...]:
        header_by_normalized_key = {
            self._normalize_header_key(header): header for header in selection.canonical_headers
        }
        aligned_headers: list[str | None] = []
        for header in selection.headers:
            normalized_key = self._normalize_header_key(header)
            aligned_headers.append(header_by_normalized_key.get(normalized_key))
        return tuple(aligned_headers)

    def _row_range(self, snapshot: WorksheetSnapshot, *, row_number: int) -> str:
        return (
            f"{self._column_index_to_a1(snapshot.write_start_column_index)}{row_number}:"
            f"{self._column_index_to_a1(snapshot.write_end_column_index)}{row_number}"
        )

    def _find_next_empty_data_row(self, snapshot: WorksheetSnapshot) -> int:
        first_data_row = snapshot.header_row_number + 1
        occupied_rows = {record.row_number for record in snapshot.rows}
        next_row = first_data_row
        while next_row in occupied_rows:
            next_row += 1
        return next_row

    def _find_appended_row(self, sheet_name: str, asset_id: Any, *, appended_row_number: int | None = None) -> SheetRecord:
        snapshot = self._load_snapshot(sheet_name)
        if appended_row_number is not None:
            for record in snapshot.rows:
                if record.row_number == appended_row_number:
                    if asset_id is None or record.values.get("Asset_ID") == asset_id:
                        return record
        if asset_id is None and snapshot.rows:
            return snapshot.rows[-1]
        for record in reversed(snapshot.rows):
            if record.values.get("Asset_ID") == asset_id:
                return record
        raise SharePointWorksheetError(f"The appended row for Asset_ID {asset_id!r} could not be located after write.")

    def _graph(self) -> GraphApiClient:
        if self._graph_client is None:
            self._graph_client = GraphApiClient(self.settings, timeout_seconds=self.timeout_seconds)
        return self._graph_client

    @staticmethod
    def _normalize_header(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @classmethod
    def _normalize_header_key(cls, value: Any) -> str:
        header = cls._normalize_header(value)
        if not header:
            return ""
        normalized = unicodedata.normalize("NFKC", header)
        normalized = normalized.replace("–", "-").replace("—", "-").replace("−", "-")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.casefold()

    @staticmethod
    def _normalize_inbound_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @staticmethod
    def _serialize_outbound_value(value: Any) -> Any:
        if value is None:
            return ""
        return value

    @staticmethod
    def _column_index_to_a1(column_index: int) -> str:
        if column_index < 0:
            raise ValueError("Column index must be non-negative.")
        result = ""
        current = column_index + 1
        while current:
            current, remainder = divmod(current - 1, 26)
            result = chr(65 + remainder) + result
        return result


def _extract_http_error_details(exc: HTTPError) -> str:
    details = [f"HTTP {exc.code} {HTTPStatus(exc.code).phrase}" if exc.code else str(exc)]
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) else None
        if message:
            details.append(str(message))
    return "; ".join(details)


def build_sharepoint_gateway(settings: SharePointSettings, expected_headers: Sequence[str]) -> SharePointTableGateway:
    gateway = SharePointTableGateway(settings=settings, expected_headers=expected_headers)
    gateway.validate_connection()
    return gateway
