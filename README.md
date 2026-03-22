# vigilance-CybATI

VIGILANCE T2.3 Cybersecurity Asset & Technology Inventory service.

This Flask backend exposes the canonical inventory API defined by `docs/assets-schema.md` and `schema/assets_schema.json`, using Google Sheets as the storage backend for the `ASSETS` worksheet only. The spreadsheet remains a storage implementation detail behind the repository and service layers.

## Google Sheets runtime modes

The backend now supports two explicit runtime modes:

1. **Authenticated read/write mode** (default and recommended)
   - uses the Google Sheets API
   - authenticates with a Google service account
   - enables full CRUD support for the `ASSETS` worksheet
   - powers `POST`, `PATCH`, `PUT`, and `DELETE`

2. **Explicit public read-only mode**
   - uses Google Sheets' unauthenticated public CSV export endpoint
   - keeps `GET` endpoints working without Google credentials
   - disables all mutation endpoints
   - is enabled only when `VIGILANCE_GOOGLE_READ_ONLY_PUBLIC=true`

At startup the app validates connectivity and logs whether it is running in `authenticated-read-write` or `public-read-only` mode.

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

## Service-account setup

To enable authenticated writes:

1. Create or choose a Google Cloud project.
2. Enable the **Google Sheets API** for that project.
3. Create a **service account**.
4. Generate a JSON key for the service account.
5. Share the target Google Sheet with the service account's `client_email`.
   - Give it **Editor** access for full CRUD support.
6. Set `VIGILANCE_GOOGLE_SPREADSHEET_ID` to the workbook ID.
7. Provide credentials through exactly one of:
   - `VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE`
   - `VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON`

If the service account is not shared on the sheet, authenticated startup will fail even if the credentials are otherwise valid.

## Environment variables

The service reads runtime configuration from environment variables prefixed with `VIGILANCE_`.

### Required

- `VIGILANCE_GOOGLE_SPREADSHEET_ID`
  - the Google Spreadsheet ID

### Required for authenticated read/write mode

Provide exactly one:

- `VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE`
  - path to a Google service-account JSON file inside the runtime environment
- `VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON`
  - the raw JSON document as an environment variable value

### Optional

- `VIGILANCE_GOOGLE_WORKSHEET_NAME`
  - defaults to `ASSETS`
  - the backend still only supports the canonical asset worksheet
- `VIGILANCE_GOOGLE_READ_ONLY_PUBLIC`
  - default `false`
  - set to `true` only if you intentionally want public-sheet read-only fallback
- `VIGILANCE_LOG_LEVEL`
  - default `INFO`
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

## CRUD behavior by mode

### Authenticated read/write mode

When credentials are configured and the service account has access to the spreadsheet:

- `GET /assets`
- `GET /assets/<asset_id>`
- `GET /assets/quality`
- `GET /vocabularies`
- `GET /vocabularies/<name>`
- `GET /schema/assets`
- `GET /schema/assets/<category>`
- `POST /assets`
- `PATCH /assets/<asset_id>`
- `PUT /assets/<asset_id>`
- `DELETE /assets/<asset_id>`

all operate against the Google Sheets `ASSETS` worksheet.

### Explicit public read-only mode

When `VIGILANCE_GOOGLE_READ_ONLY_PUBLIC=true` is set:

- all `GET` endpoints remain available
- `POST`, `PATCH`, `PUT`, and `DELETE` return a structured read-only error

This fallback exists only for intentionally public deployments and is not enabled automatically.

## Spreadsheet expectations

The configured workbook may contain multiple sheets, but this application reads and writes only the worksheet configured by `VIGILANCE_GOOGLE_WORKSHEET_NAME`, which defaults to `ASSETS`.

Startup validates that:

- a spreadsheet ID is configured
- the target worksheet exists
- the worksheet contains the canonical headers from `schema/assets_schema.json`
- spreadsheet access works in the configured runtime mode

## Run locally with `python app.py`

Create and activate a Python 3.11+ virtual environment, then install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### Option A: credentials file path

```bash
export VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id
export VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS
export VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE=$PWD/secrets/google-service-account.json
export VIGILANCE_PORT=8000
export VIGILANCE_DEBUG=true
python app.py
```

### Option B: credentials JSON in an environment variable

```bash
export VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id
export VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS
export VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON="$(cat ./secrets/google-service-account.json)"
python app.py
```

### Optional explicit public read-only startup

```bash
export VIGILANCE_GOOGLE_SPREADSHEET_ID=your_public_spreadsheet_id
export VIGILANCE_GOOGLE_READ_ONLY_PUBLIC=true
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

### Docker with mounted service-account file

```bash
docker run --rm -p 8000:8000 \
  -e VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id \
  -e VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS \
  -e VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE=/run/secrets/google-service-account.json \
  -v "$PWD/secrets/google-service-account.json:/run/secrets/google-service-account.json:ro" \
  vigilance-assets
```

### Docker with credentials JSON env var

```bash
docker run --rm -p 8000:8000 \
  -e VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id \
  -e VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS \
  -e VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON="$(cat ./secrets/google-service-account.json)" \
  vigilance-assets
```

### Compose

Set the relevant environment variables, then run:

```bash
docker compose up --build
```

## Swagger UI

Swagger UI is served by the app at:

- `http://localhost:8000/docs`

The OpenAPI document is available at:

- `http://localhost:8000/openapi.json`
