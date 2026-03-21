# vigilance-CybATI

VIGILANCE T2.3 Cybersecurity Asset & Technology Inventory service.

This repository implements a Flask-based inventory API over the canonical VIGILANCE asset schema. The spreadsheet is treated as a storage backend, not as the domain model itself: the code loads a schema catalog from `schema/assets_schema.json`, validates API payloads against that catalog, and exposes repository-backed CRUD, schema, vocabulary, and quality-report endpoints. 

## What this service does

The service is designed around one core domain rule: one row in the `ASSETS` sheet represents one asset, and `Asset_ID` is the stable API identifier. The canonical asset model and vocabulary are defined in:

- `docs/assets-schema.md`
- `schema/assets_schema.json`

The implementation currently provides:

- CRUD-style asset endpoints over `/assets`
- controlled vocabulary endpoints over `/vocabularies`
- schema discovery endpoints over `/schema/assets`
- spreadsheet-oriented storage abstractions that map by header name instead of column index
- category-aware validation with field exclusivity rules
- filtering, pagination, sorting, and free-text search for `GET /assets`
- an inventory quality report endpoint at `/assets/quality`

## Architecture overview

The implementation is intentionally layered so the API surface does not depend on spreadsheet mechanics.

```text
HTTP / Flask routes
        |
        v
   AssetService
        |
        v
 AssetRepository interface
        |
        +--> SpreadsheetAssetRepository
                |
                v
      SpreadsheetTableGateway
```

### Layer responsibilities

#### 1. API layer: `src/vigilance_assets/api.py`
Responsible for:

- creating the Flask application
- parsing request bodies, headers, and query parameters
- translating query strings into repository-level query objects
- serializing domain records to JSON responses
- mapping domain and validation exceptions to structured HTTP error responses

Not responsible for:

- direct spreadsheet access
- business validation rules
- canonical schema interpretation beyond request parsing/response formatting

#### 2. Service layer: `src/vigilance_assets/service.py`
Responsible for:

- orchestrating validation and persistence
- applying server-managed mutation behavior
- setting `Last_Updated` on create/replace/patch
- optionally overriding `Updated_By` from the `X-Updated-By` request header
- enforcing `Asset_ID` immutability during updates
- generating the `/assets/quality` audit report

#### 3. Validation layer: `src/vigilance_assets/validation.py`
Responsible for:

- validating required common fields
- validating category-specific required fields
- rejecting unknown fields
- enforcing controlled vocabularies where defined
- enforcing integer TRL values within the schema range of `1..9`
- enforcing category-specific field exclusivity
- validating `Documentation_Link` as a URL
- validating `Last_Updated` as ISO date/datetime input, `date`, or `datetime`
- providing structured machine-readable validation issues

#### 4. Repository layer: `src/vigilance_assets/repository.py`
Responsible for:

- defining the `AssetRepository` abstraction consumed by the service layer
- providing repository data structures such as `AssetListQuery`, `AssetPage`, and `AssetSchemaView`
- implementing `SpreadsheetAssetRepository`, which applies filtering, sorting, search, pagination, and persistence against a spreadsheet gateway

The rest of the application should depend on `AssetRepository`, not on spreadsheet-specific code.

#### 5. Spreadsheet mapping layer: `src/vigilance_assets/spreadsheet.py`
Responsible for:

- mapping schema field names to physical sheet headers
- converting spreadsheet rows to schema-keyed payloads and `AssetRecord` objects
- serializing `AssetRecord` objects back into header-keyed spreadsheet rows
- isolating the repository from backend-specific spreadsheet implementations

This is where the implementation preserves the important project constraint: it maps by header name, not by hardcoded column index.

#### 6. Canonical schema layer: `src/vigilance_assets/schema.py`
Responsible for:

- loading `schema/assets_schema.json`
- materializing field definitions, vocabularies, validation rules, and default searchable/filterable/sortable fields into an `AssetSchemaCatalog`

## Current storage strategy

The repository includes a spreadsheet-backed implementation, `SpreadsheetAssetRepository`, but it does **not** directly read or write Excel or Google Sheets APIs. Instead, it depends on a `SpreadsheetTableGateway` protocol that exposes header-keyed row operations:

- `list_rows(sheet_name)`
- `append_row(sheet_name, values)`
- `update_row(sheet_name, row_number, values)`
- `delete_row(sheet_name, row_number)`

This means the current strategy is:

1. treat the spreadsheet as the persistence backend
2. isolate spreadsheet access behind a gateway protocol
3. map rows by sheet header names through `AssetSpreadsheetMapper`
4. keep the service and route layers backend-agnostic

At the moment, the repository is ready for integration with a real spreadsheet backend, but this repository does not yet ship a production Excel/Google Sheets adapter. Tests use in-memory fakes and test repositories to exercise behavior.

Infrastructure preparation for future adapters is available through `vigilance_assets.config` and `vigilance_assets.infrastructure`. Runtime settings can be loaded from `VIGILANCE_`-prefixed environment variables, and concrete gateway factories can be registered for `google_sheets` or `workbook` backends without introducing SDK-specific code into the domain, repository contract, or service layers.

## Canonical asset model summary

All assets share a common field set, including:

- `Asset_ID`
- `Asset_Name`
- `Asset_Category`
- `Owner_Org`
- `Owner_Contact`
- `Pilot_s`
- `Purpose`
- `Status`
- `TRL_Start`
- `TRL_Target`
- `Related_Result`
- `Related_WP_Task`
- `Deployment_Context`
- `Last_Updated`
- `Updated_By`

The canonical categories are:

- `Cybersecurity Tool`
- `Platform / Service`
- `Compute Resource`
- `Data Stream / Data Source / Telemetry`
- `Data Store / Message Backbone`
- `Physical / Cyber-Physical Asset`

Only the fields belonging to the selected `Asset_Category` may be populated for an asset. For example, a `Cybersecurity Tool` can include `Tool_Type`, but not `Service_Type` or `Compute_Form`.

For the full field-level definition, descriptions, and controlled vocabularies, use:

- `GET /schema/assets`
- `GET /schema/assets/<category>`
- the canonical files in `docs/` and `schema/`

## API response shape

The API returns a consistent envelope:

```json
{
  "data": {},
  "meta": {},
  "error": null
}
```

On error, `data` is `null` and `error` contains a machine-readable object:

```json
{
  "data": null,
  "meta": {},
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      {
        "field": "Asset_ID",
        "message": "Asset_ID is immutable.",
        "code": "immutable"
      }
    ]
  }
}
```

## Endpoint list

### Asset endpoints

- `GET /assets`
- `GET /assets/<asset_id>`
- `GET /assets/quality`
- `POST /assets`
- `PATCH /assets/<asset_id>`
- `PUT /assets/<asset_id>`
- `DELETE /assets/<asset_id>`

### Vocabulary endpoints

- `GET /vocabularies`
- `GET /vocabularies/<name>`

### Schema endpoints

- `GET /schema/assets`
- `GET /schema/assets/<category>`

## `GET /assets`: filtering, sorting, pagination, and search

### Supported query parameters

Reserved parameters:

- `page` - 1-based page number
- `page_size` - positive page size
- `search` - free-text search term
- `sort` - one or more sort directives

Supported filter parameters are driven by the schema catalog's default filterable fields:

- `Asset_Category`
- `Owner_Org`
- `Status`
- `Deployment_Context`
- `Security_Domain`
- `Pilot_s`
- `Related_WP_Task`

Any unsupported query parameter is rejected with a `400 invalid_request` response.

### Filtering behavior

- Repeating a filter parameter is treated as multi-value matching for that field.
- Matching is equality-based after request parsing.
- Integer filter values would be coerced to integers using schema metadata, although the current default filter set is string-oriented.

Example:

```http
GET /assets?Status=Active&Deployment_Context=Cloud&Pilot_s=Pilot%20A
```

### Search behavior

Free-text search is case-insensitive substring matching against the schema catalog's default searchable fields:

- `Asset_Name`
- `Owner_Org`
- `Owner_Contact`
- `Pilot_s`
- `Purpose`
- `Related_Result`
- `Related_WP_Task`

Example:

```http
GET /assets?search=threat
```

### Sorting behavior

Sort fields are restricted to the schema catalog's default sortable fields:

- `Asset_ID`
- `Asset_Name`
- `Asset_Category`
- `Owner_Org`
- `Status`
- `TRL_Start`
- `TRL_Current`
- `TRL_Target`
- `Deployment_Context`
- `Last_Updated`

Sort syntax:

- `sort=Asset_Name` for ascending
- `sort=-Asset_Name` for descending
- `sort=Status,-Asset_Name` for multiple sort keys
- repeated `sort` parameters are also supported

Example:

```http
GET /assets?Status=Active&search=threat&sort=-Asset_Name&page=1&page_size=10
```

### Pagination behavior

- `page` defaults to `1`
- `page_size` defaults to `50`
- both must be positive integers
- the response `meta` block includes `page`, `page_size`, `total`, and `returned`

### Example list response

```json
{
  "data": {
    "items": [
      {
        "Asset_ID": "AST-001",
        "Asset_Name": "Threat Radar",
        "Asset_Category": "Cybersecurity Tool",
        "Owner_Org": "OpenAI Security Lab",
        "Owner_Contact": "owner@example.org",
        "Pilot_s": "Pilot A",
        "Purpose": "Aggregates threat findings for analysts.",
        "Status": "Active",
        "TRL_Start": 4,
        "TRL_Current": 5,
        "TRL_Target": 7,
        "Related_Result": "RS3",
        "Related_WP_Task": "T5.3",
        "Deployment_Context": "Cloud",
        "Standards_Compliance": "IEC 62443",
        "Security_Domain": "Cloud Security",
        "Documentation_Link": "https://example.org/assets/docs",
        "Last_Updated": "2026-03-21T10:00:00+00:00",
        "Updated_By": "owner@example.org",
        "Tool_Type": "SIEM (Security Information and Event Management)",
        "Security_Function": "Monitor",
        "Interfaces_Provided": "REST API",
        "Interfaces_Consumed": "Syslog",
        "Dependencies": "Threat feed",
        "Code_Availability": "Yes",
        "License_IP": "Apache-2.0"
      }
    ]
  },
  "meta": {
    "page": 1,
    "page_size": 10,
    "total": 1,
    "returned": 1,
    "filters": {
      "Status": "Active"
    },
    "search": "threat",
    "sort": [
      {
        "field": "Asset_Name",
        "direction": "desc"
      }
    ]
  },
  "error": null
}
```

## Validation behavior

### Create and replace validation

`POST /assets` and `PUT /assets/<asset_id>` require a complete asset payload for the selected category.

Validation includes:

- required common fields must be populated
- required category-specific fields must be populated
- `Asset_ID` must be unique on create
- `Asset_ID` is immutable on update
- unknown fields are rejected
- controlled vocabulary fields must use a valid configured value
- `TRL_Start`, `TRL_Current`, and `TRL_Target` must be integers in the range `1..9` when provided
- `Documentation_Link` must be a valid URL when provided
- `Last_Updated` must be an ISO date/datetime string, `date`, or `datetime`
- fields from other categories are rejected when populated

### Patch validation

`PATCH /assets/<asset_id>` accepts partial updates, but:

- the payload still must not contain unknown fields
- if `Asset_Category` is changed, the payload is validated against the new category
- category-incompatible fields are rejected
- `Asset_ID` cannot be supplied or changed
- merged state is fully revalidated before persistence

### Server-managed mutation behavior

For create, patch, and replace operations:

- the service overwrites `Last_Updated` with the current server time
- if the request includes `X-Updated-By`, the service overwrites `Updated_By` with that header value

### Delete behavior

`DELETE /assets/<asset_id>` supports two modes:

- default `archive` mode: the repository marks the asset `Status` as `Deprecated`
- `mode=delete`: the repository removes the row physically

Example:

```http
DELETE /assets/AST-001?mode=delete
```

## Example requests and responses

### 1. Create an asset: `POST /assets`

Request:

```http
POST /assets
Content-Type: application/json
X-Updated-By: api-user@example.org
```

```json
{
  "Asset_ID": "AST-099",
  "Asset_Name": "Alert Fusion Service",
  "Asset_Category": "Platform / Service",
  "Owner_Org": "OpenAI Security Lab",
  "Owner_Contact": "owner@example.org",
  "Pilot_s": "Pilot A",
  "Purpose": "Supports cyber defence workflows across pilots.",
  "Status": "Active",
  "TRL_Start": 4,
  "TRL_Current": 5,
  "TRL_Target": 7,
  "Related_Result": "RS3",
  "Related_WP_Task": "T5.3",
  "Deployment_Context": "Cloud",
  "Standards_Compliance": "IEC 62443",
  "Security_Domain": "Cloud Security",
  "Documentation_Link": "https://example.org/assets/docs",
  "Last_Updated": "2026-03-21T10:00:00+00:00",
  "Updated_By": "ignored@example.org",
  "Service_Type": "Security Service",
  "Inputs": "Telemetry",
  "Outputs": "Alerts",
  "Scalability_Mode": "Horizontal"
}
```

Response:

```json
{
  "data": {
    "Asset_ID": "AST-099",
    "Asset_Name": "Alert Fusion Service",
    "Asset_Category": "Platform / Service",
    "Owner_Org": "OpenAI Security Lab",
    "Owner_Contact": "owner@example.org",
    "Pilot_s": "Pilot A",
    "Purpose": "Supports cyber defence workflows across pilots.",
    "Status": "Active",
    "TRL_Start": 4,
    "TRL_Current": 5,
    "TRL_Target": 7,
    "Related_Result": "RS3",
    "Related_WP_Task": "T5.3",
    "Deployment_Context": "Cloud",
    "Standards_Compliance": "IEC 62443",
    "Security_Domain": "Cloud Security",
    "Documentation_Link": "https://example.org/assets/docs",
    "Last_Updated": "2026-03-21T12:30:00+00:00",
    "Updated_By": "api-user@example.org",
    "Service_Type": "Security Service",
    "Inputs": "Telemetry",
    "Outputs": "Alerts",
    "Scalability_Mode": "Horizontal"
  },
  "meta": {},
  "error": null
}
```

### 2. Get one asset: `GET /assets/<asset_id>`

Request:

```http
GET /assets/AST-001
```

Response:

```json
{
  "data": {
    "Asset_ID": "AST-001",
    "Asset_Name": "Threat Radar",
    "Asset_Category": "Cybersecurity Tool",
    "Owner_Org": "OpenAI Security Lab",
    "Owner_Contact": "owner@example.org",
    "Pilot_s": "Pilot A",
    "Purpose": "Aggregates threat findings for analysts.",
    "Status": "Active",
    "TRL_Start": 4,
    "TRL_Current": 5,
    "TRL_Target": 7,
    "Related_Result": "RS3",
    "Related_WP_Task": "T5.3",
    "Deployment_Context": "Cloud",
    "Standards_Compliance": "IEC 62443",
    "Security_Domain": "Cloud Security",
    "Documentation_Link": "https://example.org/assets/docs",
    "Last_Updated": "2026-03-21T10:00:00+00:00",
    "Updated_By": "owner@example.org",
    "Tool_Type": "SIEM (Security Information and Event Management)",
    "Security_Function": "Monitor",
    "Interfaces_Provided": "REST API",
    "Interfaces_Consumed": "Syslog",
    "Dependencies": "Threat feed",
    "Code_Availability": "Yes",
    "License_IP": "Apache-2.0"
  },
  "meta": {},
  "error": null
}
```

### 3. Patch an asset: `PATCH /assets/<asset_id>`

Request:

```http
PATCH /assets/AST-001
Content-Type: application/json
X-Updated-By: patcher@example.org
```

```json
{
  "Status": "Deprecated",
  "Security_Function": "Investigate"
}
```

Response:

```json
{
  "data": {
    "Asset_ID": "AST-001",
    "Status": "Deprecated",
    "Security_Function": "Investigate",
    "Updated_By": "patcher@example.org",
    "Last_Updated": "2026-03-21T12:30:00+00:00"
  },
  "meta": {},
  "error": null
}
```

### 4. Replace an asset: `PUT /assets/<asset_id>`

Request:

```http
PUT /assets/AST-001
Content-Type: application/json
```

```json
{
  "Asset_Name": "Threat Radar 2",
  "Asset_Category": "Cybersecurity Tool",
  "Owner_Org": "OpenAI Security Lab",
  "Owner_Contact": "owner@example.org",
  "Pilot_s": "Pilot A",
  "Purpose": "Supports cyber defence workflows across pilots.",
  "Status": "Deprecated",
  "TRL_Start": 4,
  "TRL_Current": 5,
  "TRL_Target": 7,
  "Related_Result": "RS3",
  "Related_WP_Task": "T5.3",
  "Deployment_Context": "Cloud",
  "Standards_Compliance": "IEC 62443",
  "Security_Domain": "Cloud Security",
  "Documentation_Link": "https://example.org/assets/docs",
  "Last_Updated": "2026-03-21T10:00:00+00:00",
  "Updated_By": "owner@example.org",
  "Tool_Type": "SIEM (Security Information and Event Management)",
  "Security_Function": "Monitor",
  "Interfaces_Provided": "REST API",
  "Interfaces_Consumed": "Syslog",
  "Dependencies": "Threat feed",
  "Code_Availability": "Yes",
  "License_IP": "Apache-2.0"
}
```

Response:

```json
{
  "data": {
    "Asset_ID": "AST-001",
    "Asset_Name": "Threat Radar 2",
    "Status": "Deprecated"
  },
  "meta": {},
  "error": null
}
```

### 5. Delete or archive an asset: `DELETE /assets/<asset_id>`

Request:

```http
DELETE /assets/AST-001
```

Response:

```json
{
  "data": {
    "asset_id": "AST-001",
    "mode": "archive"
  },
  "meta": {},
  "error": null
}
```

### 6. List vocabularies: `GET /vocabularies`

Request:

```http
GET /vocabularies
```

Response:

```json
{
  "data": {
    "Status": ["Not Started", "Planned", "Active", "Deprecated"],
    "Deployment_Context": ["IT", "OT", "IoT", "Cloud", "Hybrid"]
  },
  "meta": {
    "total": 11
  },
  "error": null
}
```

### 7. Get one vocabulary: `GET /vocabularies/<name>`

Request:

```http
GET /vocabularies/Status
```

Response:

```json
{
  "data": {
    "name": "Status",
    "values": ["Not Started", "Planned", "Active", "Deprecated"]
  },
  "meta": {
    "total": 4
  },
  "error": null
}
```

### 8. Get schema metadata: `GET /schema/assets`

Request:

```http
GET /schema/assets
```

Response shape:

```json
{
  "data": {
    "id_field": "Asset_ID",
    "common_fields": [
      {
        "name": "Asset_ID",
        "sheet_header": "Asset_ID",
        "field_type": "string",
        "required": true,
        "nullable": false,
        "description": "Unique stable identifier for the asset."
      }
    ],
    "category_fields": {
      "Cybersecurity Tool": [
        {
          "name": "Tool_Type",
          "sheet_header": "Tool_Type",
          "field_type": "string",
          "required": true,
          "nullable": false,
          "enum_ref": "Tool_Type"
        }
      ]
    },
    "vocabularies": {
      "Status": ["Not Started", "Planned", "Active", "Deprecated"]
    }
  },
  "meta": {},
  "error": null
}
```

### 9. Get category schema metadata: `GET /schema/assets/<category>`

Request:

```http
GET /schema/assets/Cybersecurity%20Tool
```

Response behavior:

- returns the common field set
- restricts `category_fields` to the requested category only
- returns all vocabularies

### 10. Get inventory quality report: `GET /assets/quality`

Request:

```http
GET /assets/quality
```

Response shape:

```json
{
  "data": {
    "assets": [
      {
        "asset_id": "AST-001",
        "category": "Cybersecurity Tool",
        "row_number": 2,
        "issue_count": 1
      }
    ],
    "issues": [
      {
        "asset_id": "AST-002",
        "category": "Cybersecurity Tool",
        "field": "TRL_Start",
        "message": "Field must be between 1 and 9.",
        "code": "out_of_range",
        "row_number": 3,
        "severity": "error"
      }
    ]
  },
  "meta": {
    "total_assets": 3,
    "assets_with_issues": 3,
    "issue_count": 6,
    "schema_name": "vigilance_t23_assets",
    "schema_version": "0.1.0",
    "id_field": "Asset_ID"
  },
  "error": null
}
```

## Running locally

### Requirements

- Python 3.11+
- `pip`
- optionally, a concrete `SpreadsheetTableGateway` implementation if you want to run against a real spreadsheet backend

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Start the Flask app

This repository exposes `create_app`, but it does not yet include a packaged production entrypoint or a built-in real spreadsheet gateway. The easiest local run flow for development is to create a small bootstrap script that wires `create_app()` to a repository implementation.

Example development bootstrap using an in-memory/fake repository pattern:

```python
from vigilance_assets import AssetService, create_app
from tests.test_api import ApiRepository

repository = ApiRepository()
service = AssetService(repository)
app = create_app(service)

if __name__ == "__main__":
    app.run(debug=True)
```

You can save that as `dev_server.py` and run:

```bash
python dev_server.py
```

If you are integrating a real spreadsheet backend, instantiate `SpreadsheetAssetRepository(workbook_reference=..., gateway=...)` and pass it into `AssetService` or directly to `create_app(repository=...)`.

## Running tests

Install test dependencies and run:

```bash
pip install pytest
pytest
```

The test suite covers:

- schema loading
- model construction and normalization
- validation rules
- repository behavior
- spreadsheet row mapping
- API endpoint behavior
- service-layer mutation logic

## Assumptions and implementation notes

- The canonical source of truth for fields and controlled vocabularies is `schema/assets_schema.json`, with supporting narrative in `docs/assets-schema.md`.
- `GET /assets` currently only accepts the repository catalog's default filterable fields; category-specific filters such as `Tool_Type` are intentionally rejected at the API layer today.
- `GET /assets/quality` is implemented in addition to the base CRUD/schema/vocabulary requirements and returns a machine-readable audit of inventory-level issues.
- `DELETE /assets` defaults to archive semantics by setting `Status` to `Deprecated` in the spreadsheet-backed repository.
- The repository is architected for spreadsheet-backed persistence, but a concrete production spreadsheet gateway is still expected to be provided by an integrator.


## Containerized execution

The repository now includes a production-oriented container image for running the Flask API behind Gunicorn.

### Files added for containerization

- `Dockerfile` - builds a slim Python 3.11 image, installs the package, and starts Gunicorn
- `.dockerignore` - keeps the image build context small and excludes local caches, tests, and VCS metadata
- `docker-compose.yml` - convenient local runner for `docker compose`
- `src/vigilance_assets/wsgi.py` - environment-driven application entry point for container startup

### Runtime configuration

The container startup path uses the existing `VIGILANCE_` environment variables from `src/vigilance_assets/config.py`.

Common variables:

- `PORT` - container listen port for Gunicorn, default `8000`
- `GUNICORN_WORKERS` - Gunicorn worker count, default `2`
- `GUNICORN_THREADS` - Gunicorn threads per worker, default `4`
- `VIGILANCE_SPREADSHEET_BACKEND` - backend selector: `memory`, `workbook`, or `google_sheets`; default `memory`
- `VIGILANCE_SPREADSHEET_REFERENCE` - optional logical workbook reference
- `VIGILANCE_SPREADSHEET_WORKBOOK_PATH` - workbook path when using `workbook`
- `VIGILANCE_SPREADSHEET_WORKBOOK_READ_ONLY` - workbook read-only toggle when using `workbook`
- `VIGILANCE_SPREADSHEET_GOOGLE_ID` - spreadsheet identifier when using `google_sheets`
- `VIGILANCE_GOOGLE_CREDENTIALS_PATH` - credential file path for Google Sheets integrations
- `VIGILANCE_GOOGLE_CREDENTIALS_JSON` - inline credential JSON for Google Sheets integrations
- `VIGILANCE_ASSETS_SHEET_NAME` - assets sheet name override, default `ASSETS`
- `VIGILANCE_VOCABULARIES_SHEET_NAME` - vocabularies sheet name override, default `VOCABULARIES`

> Note: this repository currently ships an in-memory gateway suitable for local/container startup. The non-memory backends remain configuration-ready, but still require a registered spreadsheet gateway implementation before they can talk to a real workbook or Google Sheets backend.

### Build the image

```bash
docker build -t vigilance-assets:local .
```

### Run the container with `docker run`

Default local startup uses the in-memory backend:

```bash
docker run --rm -p 8000:8000 vigilance-assets:local
```

Pass environment variables with `-e` flags:

```bash
docker run --rm \
  -p 8000:8000 \
  -e PORT=8000 \
  -e GUNICORN_WORKERS=2 \
  -e VIGILANCE_SPREADSHEET_BACKEND=memory \
  vigilance-assets:local
```

If you need to inject many variables, you can use an env file:

```bash
docker run --rm \
  --env-file .env \
  -p 8000:8000 \
  vigilance-assets:local
```

Stop the container by pressing `Ctrl+C` in the foreground, or if running detached:

```bash
docker stop <container_id_or_name>
```

### Run with Docker Compose

Start the service:

```bash
docker compose up --build
```

Run detached:

```bash
docker compose up --build -d
```

Override variables either in your shell or in a `.env` file that Docker Compose will read automatically. Example:

```dotenv
PORT=8000
VIGILANCE_SPREADSHEET_BACKEND=memory
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
```

Stop the compose stack:

```bash
docker compose down
```

### Health check / quick verification

After the container starts, verify the API is responding:

```bash
curl http://127.0.0.1:8000/schema/assets
```
