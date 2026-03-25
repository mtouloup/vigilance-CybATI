# vigilance-CybATI

VIGILANCE T2.3 Cybersecurity Asset & Technology Inventory service.

This Flask backend exposes the canonical inventory API defined by `docs/assets-schema.md` and `schema/assets_schema.json`, while keeping spreadsheet persistence behind repository adapters.

## Storage backends

Select backend at runtime with:

- `VIGILANCE_STORAGE_BACKEND=google_sheets` (default)
- `VIGILANCE_STORAGE_BACKEND=sharepoint`

The domain model, validators, services, and API contracts are unchanged across backends.

## Canonical model

Canonical asset schema and vocabulary files:

- `docs/assets-schema.md`
- `schema/assets_schema.json`

The backend detects the canonical header row in the `ASSETS` worksheet, respects the decorative grouping row above it, writes aligned rows beginning at `Asset_ID`, preserves separator columns, and finds the next empty data row explicitly.

---

## Google Sheets backend

### Required environment variables

- `VIGILANCE_STORAGE_BACKEND=google_sheets`
- `VIGILANCE_GOOGLE_SPREADSHEET_ID`

For authenticated read/write (recommended), set exactly one:

- `VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE`
- `VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON`

Optional:

- `VIGILANCE_GOOGLE_WORKSHEET_NAME` (default `ASSETS`)
- `VIGILANCE_GOOGLE_READ_ONLY_PUBLIC` (default `false`)

### One-time setup

1. Create/select a Google Cloud project.
2. Enable Google Sheets API.
3. Create a service account and key JSON.
4. Share the target spreadsheet with service-account `client_email`.

---

## SharePoint backend (Microsoft Graph)

### Required environment variables

- `VIGILANCE_STORAGE_BACKEND=sharepoint`
- `VIGILANCE_SHAREPOINT_TENANT_ID`
- `VIGILANCE_SHAREPOINT_CLIENT_ID`
- `VIGILANCE_SHAREPOINT_CLIENT_SECRET` (or adapt implementation for certificate flow)
- one of:
  - `VIGILANCE_SHAREPOINT_SITE_ID`, or
  - `VIGILANCE_SHAREPOINT_SITE_URL`
- optionally `VIGILANCE_SHAREPOINT_DRIVE_ID` (auto-resolved if omitted)
- one of:
  - `VIGILANCE_SHAREPOINT_ITEM_ID`, or
  - `VIGILANCE_SHAREPOINT_WORKBOOK_PATH`
- optional `VIGILANCE_SHAREPOINT_WORKSHEET_NAME` (default `ASSETS`)

### One-time Azure/SharePoint setup

1. Register an app in Microsoft Entra ID.
2. Create a client secret for the app registration.
3. Grant **application** Microsoft Graph permissions (minimum typically includes `Sites.ReadWrite.All` and `Files.ReadWrite.All`) and grant admin consent.
4. Ensure the app has access to the target SharePoint site/document library containing the workbook.
5. Capture tenant/client IDs, and site/workbook identifiers (or workbook path).

The backend authenticates via OAuth2 client-credentials against Microsoft Graph, then reads/writes the Excel workbook through Graph workbook endpoints.

---

## Run locally (`python app.py`)

Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### Local run (Google Sheets)

```bash
export VIGILANCE_STORAGE_BACKEND=google_sheets
export VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id
export VIGILANCE_GOOGLE_WORKSHEET_NAME=ASSETS
export VIGILANCE_GOOGLE_SERVICE_ACCOUNT_FILE=$PWD/secrets/google-service-account.json
python app.py
```

### Local run (SharePoint)

```bash
export VIGILANCE_STORAGE_BACKEND=sharepoint
export VIGILANCE_SHAREPOINT_TENANT_ID=your_tenant_id
export VIGILANCE_SHAREPOINT_CLIENT_ID=your_client_id
export VIGILANCE_SHAREPOINT_CLIENT_SECRET=your_client_secret
export VIGILANCE_SHAREPOINT_SITE_ID=your_site_id
export VIGILANCE_SHAREPOINT_ITEM_ID=your_workbook_item_id
export VIGILANCE_SHAREPOINT_WORKSHEET_NAME=ASSETS
python app.py
```

## Docker

Build:

```bash
docker build -t vigilance-assets .
```

### Docker run (Google Sheets)

```bash
docker run --rm -p 8000:8000 \
  -e VIGILANCE_STORAGE_BACKEND=google_sheets \
  -e VIGILANCE_GOOGLE_SPREADSHEET_ID=your_spreadsheet_id \
  -e VIGILANCE_GOOGLE_SERVICE_ACCOUNT_JSON="$(cat ./secrets/google-service-account.json)" \
  vigilance-assets
```

### Docker run (SharePoint)

```bash
docker run --rm -p 8000:8000 \
  -e VIGILANCE_STORAGE_BACKEND=sharepoint \
  -e VIGILANCE_SHAREPOINT_TENANT_ID=your_tenant_id \
  -e VIGILANCE_SHAREPOINT_CLIENT_ID=your_client_id \
  -e VIGILANCE_SHAREPOINT_CLIENT_SECRET=your_client_secret \
  -e VIGILANCE_SHAREPOINT_SITE_ID=your_site_id \
  -e VIGILANCE_SHAREPOINT_ITEM_ID=your_workbook_item_id \
  vigilance-assets
```

### Compose

Set environment variables for your selected backend, then:

```bash
docker compose up --build
```

## API docs

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
