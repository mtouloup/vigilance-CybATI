# vigilance-CybATI

VIGILANCE T2.3 Cybersecurity Asset & Technology Inventory service.

This Flask backend exposes the canonical inventory API defined by `docs/assets-schema.md` and `schema/assets_schema.json`, using a **public Google Sheet** as the storage backend. The application explicitly targets the `ASSETS` worksheet inside a workbook that may contain multiple tabs.

## Public Google Sheet behavior

The backend now uses Google Sheets' **unauthenticated public CSV export** mechanism for the configured worksheet. That means:

- no Google credentials are required
- no service account is required
- no OAuth flow is required
- no credential JSON or credential file path is supported
- the sheet must already be publicly accessible or published by design

Because this access path is public and unauthenticated, **read operations work, but write operations do not**. The API therefore runs in a deliberate **read-only mode** when backed by a public sheet. Mutating endpoints return a clear error instead of pretending to write.

## Canonical model

The canonical asset model lives in:

- `docs/assets-schema.md`
- `schema/assets_schema.json`

Important implementation rules:

- one row in the `ASSETS` worksheet represents exactly one asset
- `Asset_ID` is the stable unique API identifier
- spreadsheet columns are mapped by header name
- the app validates records against the canonical schema
- only the configured `ASSETS` worksheet is used for inventory data

## Environment variables

The service reads runtime configuration from environment variables prefixed with `VIGILANCE_`.

### Required

- `VIGILANCE_GOOGLE_SPREADSHEET_ID`
  - the Google Spreadsheet ID for the public workbook

### Optional

- `VIGILANCE_GOOGLE_WORKSHEET_NAME`
  - defaults to `ASSETS`
  - use this only if the asset worksheet tab has a different public tab name
- `VIGILANCE_PORT`
  - default local port override
- `PORT`
  - default container/runtime port override
- `VIGILANCE_DEBUG` or `FLASK_DEBUG`
  - enable Flask debug mode locally
- `GUNICORN_WORKERS`
  - default `2` in Docker
- `GUNICORN_THREADS`
  - default `4` in Docker

## Spreadsheet expectations

The configured workbook may contain multiple sheets, but this application reads only the worksheet configured by `VIGILANCE_GOOGLE_WORKSHEET_NAME`, which defaults to `ASSETS`.

Startup validates that:

- a spreadsheet ID is configured
- the target worksheet can be fetched through the public Google Sheets export endpoint
- the first row contains the canonical headers from `schema/assets_schema.json`
- there are no duplicate or unexpected headers

## Run locally with `python app.py`

Create and activate a Python 3.11+ virtual environment, then install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

Set environment variables directly or place them in a local `.env` file:

```bash
export VIGILANCE_GOOGLE_SPREADSHEET_ID=your_public_spreadsheet_id
export VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS
export VIGILANCE_PORT=8000
export VIGILANCE_DEBUG=true
```

Start the app:

```bash
python app.py
```

Then open:

- API root: `http://localhost:8000/`
- assets endpoint: `http://localhost:8000/assets`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Run with Docker

Build the image:

```bash
docker build -t vigilance-assets .
```

Run the container:

```bash
docker run --rm -p 8000:8000 \
  -e VIGILANCE_GOOGLE_SPREADSHEET_ID=your_public_spreadsheet_id \
  -e VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS \
  vigilance-assets
```

Or with Compose:

```bash
docker compose up --build
```

## Swagger UI

Swagger UI is served by the app at:

- `http://localhost:8000/docs`

The OpenAPI document is available at:

- `http://localhost:8000/openapi.json`

## API surface

Read endpoints remain fully available:

- `GET /assets`
- `GET /assets/<asset_id>`
- `GET /assets/quality`
- `GET /vocabularies`
- `GET /vocabularies/<name>`
- `GET /schema/assets`
- `GET /schema/assets/<category>`

Mutation endpoints are still present for API compatibility, but public-sheet deployments return a clear read-only error:

- `POST /assets`
- `PATCH /assets/<asset_id>`
- `PUT /assets/<asset_id>`
- `DELETE /assets/<asset_id>`

## Public-sheet write limitation

Google's public export mechanisms provide anonymous reads, not authenticated edits. Within this repository's current spreadsheet-backed design, there is **no legitimate unauthenticated way** to perform safe writes back to a public Google Sheet.

Accordingly, this backend intentionally does **not** fake write support. It keeps reads working against the public `ASSETS` worksheet and returns explicit read-only errors for mutations.
