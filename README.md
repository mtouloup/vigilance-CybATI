# vigilance-CybATI

VIGILANCE T2.3 Cybersecurity Asset & Technology Inventory service.

This repository implements a Flask API over the canonical VIGILANCE asset schema defined in `docs/assets-schema.md` and `schema/assets_schema.json`. The application now supports **Google Sheets only** as its persistence backend. At runtime it connects to a single Google spreadsheet, reads and writes the canonical `ASSETS` worksheet by header name, and exposes CRUD, schema, vocabulary, and quality-report endpoints for the asset inventory.

## Canonical model

The repository-level source of truth for the asset model is:

- `docs/assets-schema.md`
- `schema/assets_schema.json`

Important rules carried through the implementation:

- one row in the `ASSETS` worksheet represents exactly one asset
- `Asset_ID` is the stable unique API identifier
- common fields apply to every asset
- category-specific fields apply only to the chosen `Asset_Category`
- the API validates controlled vocabularies, TRL ranges, URLs, timestamps, and category exclusivity
- spreadsheet columns are always mapped by **header name**, never by hardcoded column index

## Architecture

The app remains layered, but it is simplified for a single backend:

```text
Flask blueprints
      |
      v
 AssetService
      |
      v
SpreadsheetAssetRepository
      |
      v
GoogleSheetsTableGateway
      |
      v
Google Sheets API (ASSETS worksheet only)
```

### What changed in this migration

- Google Sheets is the **only supported backend**.
- Runtime configuration no longer supports local workbook files, in-memory storage, or backend switching.
- Startup now validates:
  - spreadsheet ID presence
  - credentials presence and loadability
  - target worksheet existence
  - exact header compatibility with the canonical schema
- The app is organized with Flask blueprints and browser-accessible Swagger UI.

## Environment variables

The service reads configuration from environment variables with the `VIGILANCE_` prefix.

### Required

- `VIGILANCE_GOOGLE_SPREADSHEET_ID`
  - The Google spreadsheet ID.
- One of:
  - `VIGILANCE_GOOGLE_CREDENTIALS_PATH`
  - `VIGILANCE_GOOGLE_CREDENTIALS_JSON`

### Optional

- `VIGILANCE_GOOGLE_WORKSHEET_NAME`
  - Defaults to `ASSETS`.
  - Use this only if the workbook uses a different tab name for the asset inventory while still representing the canonical ASSETS table.
- `PORT`
  - Default container/runtime port is `8000`.
- `GUNICORN_WORKERS`
  - Default `2` in Docker.
- `GUNICORN_THREADS`
  - Default `4` in Docker.

## Google credentials

The expected authentication model is a standard Google service account with access to the target spreadsheet.

### Option 1: credentials file path

Set:

```bash
export VIGILANCE_GOOGLE_CREDENTIALS_PATH=/absolute/path/to/service-account.json
```

### Option 2: credentials JSON directly

Set:

```bash
export VIGILANCE_GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}'
```

### Required Google setup

1. Create or choose a Google Cloud project.
2. Enable the Google Sheets API.
3. Create a service account.
4. Download the service account JSON key, or inject it securely as environment JSON.
5. Share the target spreadsheet with the service account email.

Do **not** hardcode credentials or commit secrets into the repository.

## Spreadsheet expectations

The target workbook may contain multiple tabs, but this application only uses the asset inventory worksheet.

- The runtime worksheet name defaults to `ASSETS`.
- The first row of that worksheet must contain the canonical headers defined by `schema/assets_schema.json`.
- Header validation is strict: startup fails if required headers are missing, duplicated, or if unexpected headers are present.
- Reads and writes are performed against the configured worksheet only.

## Running locally

Create and activate a Python 3.11+ environment, then install the project:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

Set environment variables:

```bash
export VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id
export VIGILANCE_GOOGLE_CREDENTIALS_PATH=/absolute/path/to/service-account.json
# optional
export VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS
```

Run the app:

```bash
flask --app vigilance_assets.wsgi run --debug --host 0.0.0.0 --port 8000
```

Or with Gunicorn:

```bash
gunicorn --bind 0.0.0.0:8000 vigilance_assets.wsgi:app
```

## Running with Docker

Build the image:

```bash
docker build -t vigilance-assets .
```

### Using a mounted credentials file

```bash
docker run --rm -p 8000:8000 \
  -e VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id \
  -e VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS \
  -e VIGILANCE_GOOGLE_CREDENTIALS_PATH=/run/secrets/google-service-account.json \
  -v /absolute/path/to/service-account.json:/run/secrets/google-service-account.json:ro \
  vigilance-assets
```

### Using credentials JSON directly

```bash
docker run --rm -p 8000:8000 \
  -e VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id \
  -e VIGILANCE_GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}' \
  vigilance-assets
```

## Swagger / OpenAPI

When the service starts successfully, OpenAPI documentation is available at:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

The Swagger UI is served by the Flask app and works locally and inside Docker.

## API endpoints

### Assets

- `GET /assets`
- `GET /assets/<asset_id>`
- `GET /assets/quality`
- `POST /assets`
- `PATCH /assets/<asset_id>`
- `PUT /assets/<asset_id>`
- `DELETE /assets/<asset_id>`

### Vocabularies

- `GET /vocabularies`
- `GET /vocabularies/<name>`

### Schema

- `GET /schema/assets`
- `GET /schema/assets/<category>`

## Filtering, sorting, pagination, and search

`GET /assets` supports:

- filtering on schema-defined filterable fields such as `Asset_Category`, `Owner_Org`, `Status`, `Pilot_s`, `Deployment_Context`, `Security_Domain`, and `Related_WP_Task`
- pagination via `page` and `page_size`
- sorting via `sort`
- free-text search via `search`

Example:

```bash
curl 'http://localhost:8000/assets?Asset_Category=Cybersecurity%20Tool&Status=Active&sort=Asset_Name&page=1&page_size=20'
```

## Startup failure behavior

The application intentionally fails fast during startup when runtime configuration is invalid. Typical startup errors include:

- missing `VIGILANCE_GOOGLE_SPREADSHEET_ID`
- missing credentials configuration
- invalid or unreadable service account credentials
- configured worksheet not found in the spreadsheet
- worksheet headers not matching the canonical schema

This is deliberate so misconfiguration is caught immediately in local runs, container runs, and deployments.

## Development notes

The code keeps domain models, validation, service orchestration, transport, and persistence concerns separate, but the runtime backend path is now intentionally single-purpose and Google-Sheets-only.
