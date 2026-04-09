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

The SharePoint adapter preserves worksheet alignment behavior:

- detects the canonical `ASSETS` header row
- ignores the decorative row above it
- anchors writes at the `Asset_ID` column
- explicitly finds the next empty data row
- writes explicit aligned A1 ranges
- preserves late category-specific columns and separator columns

---

## Authentication and authorization modes

### `VIGILANCE_AUTH_MODE=none` (default)

No API bearer-token enforcement. Useful only for local/testing environments.

### `VIGILANCE_AUTH_MODE=entra_obo`

The API requires Microsoft Entra ID JWT bearer tokens and validates:

- issuer (`https://login.microsoftonline.com/<tenant>/v2.0`)
- tenant (`tid` claim must match `VIGILANCE_ENTRA_TENANT_ID`)
- audience (`aud` claim must match `VIGILANCE_ENTRA_API_AUDIENCE`)

When SharePoint backend is enabled, the API uses OAuth 2.0 On-Behalf-Of (OBO) to exchange the incoming API token for a delegated Microsoft Graph token per request.

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

---

## SharePoint backend with delegated Graph access (Entra OBO)

> For SharePoint + Excel workbook write APIs, this service uses delegated Graph access via OBO. It does **not** use app-only Graph permissions for workbook write operations.

### Required environment variables

- `VIGILANCE_STORAGE_BACKEND=sharepoint`
- `VIGILANCE_AUTH_MODE=entra_obo`
- `VIGILANCE_ENTRA_TENANT_ID`
- `VIGILANCE_ENTRA_CLIENT_ID`
- `VIGILANCE_ENTRA_CLIENT_SECRET`
- `VIGILANCE_ENTRA_API_AUDIENCE` (for example `api://<api-app-client-id>`)
- `VIGILANCE_GRAPH_SCOPES` (default `https://graph.microsoft.com/.default`)
- one of:
  - `VIGILANCE_SHAREPOINT_SITE_ID`, or
  - `VIGILANCE_SHAREPOINT_SITE_URL`
- optionally `VIGILANCE_SHAREPOINT_DRIVE_ID` (auto-resolved if omitted)
- one of:
  - `VIGILANCE_SHAREPOINT_ITEM_ID`, or
  - `VIGILANCE_SHAREPOINT_WORKBOOK_PATH`
- optional `VIGILANCE_SHAREPOINT_WORKSHEET_NAME` (default `ASSETS`)

### Entra app registration (high level)

1. Register **API app** (the Flask API):
   - Expose an API (Application ID URI, e.g. `api://<api-app-client-id>`)
   - Define delegated scope(s), e.g. `access_as_user`
2. Register **client app** (SPA/web/native calling Flask API):
   - Request delegated permission to the Flask API scope
3. Configure the Flask API app with Graph delegated permissions needed for workbook and file operations (for example `Files.ReadWrite`, `Sites.ReadWrite.All` as required by your tenancy policy).
4. Grant tenant admin consent where required.
5. Ensure users who call the API also have SharePoint permissions to the workbook location (`gft365.sharepoint.com` tenant).

For this deployment, the expected Entra tenant is the one backing `gft365.sharepoint.com`.

### End-to-end delegated/OBO flow

1. User signs in to Entra ID and client obtains access token for **this API** (`aud=VIGILANCE_ENTRA_API_AUDIENCE`).
2. Client calls Flask API with `Authorization: Bearer <api_token>`.
3. Flask validates token against tenant + audience.
4. Flask performs OBO token exchange against Entra token endpoint.
5. Flask calls Microsoft Graph workbook APIs using the **delegated Graph token**.
6. SharePoint authorization is enforced by Graph using the signed-in user’s permissions.

Result: only authenticated users with workbook access can read/write assets.

### Addressing the workbook (`driveItem`)

You can target the workbook in either mode:

- **Direct item mode**: `SITE_ID` (+ optional `DRIVE_ID`) and `ITEM_ID`
- **Path mode**: `SITE_ID` or `SITE_URL`, plus `WORKBOOK_PATH` (for example `Shared Documents/T2.3 inventory.xlsx`)

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

### Local run (SharePoint + Entra OBO)

```bash
export VIGILANCE_STORAGE_BACKEND=sharepoint
export VIGILANCE_AUTH_MODE=entra_obo
export VIGILANCE_ENTRA_TENANT_ID=your_tenant_id
export VIGILANCE_ENTRA_CLIENT_ID=your_api_app_client_id
export VIGILANCE_ENTRA_CLIENT_SECRET=your_api_app_client_secret
export VIGILANCE_ENTRA_API_AUDIENCE=api://your_api_app_client_id
export VIGILANCE_GRAPH_SCOPES="https://graph.microsoft.com/.default"
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

### Docker run (SharePoint + OBO)

```bash
docker run --rm -p 8000:8000 \
  -e VIGILANCE_STORAGE_BACKEND=sharepoint \
  -e VIGILANCE_AUTH_MODE=entra_obo \
  -e VIGILANCE_ENTRA_TENANT_ID=your_tenant_id \
  -e VIGILANCE_ENTRA_CLIENT_ID=your_api_app_client_id \
  -e VIGILANCE_ENTRA_CLIENT_SECRET=your_api_app_client_secret \
  -e VIGILANCE_ENTRA_API_AUDIENCE=api://your_api_app_client_id \
  -e VIGILANCE_GRAPH_SCOPES="https://graph.microsoft.com/.default" \
  -e VIGILANCE_SHAREPOINT_SITE_ID=your_site_id \
  -e VIGILANCE_SHAREPOINT_ITEM_ID=your_workbook_item_id \
  -e VIGILANCE_SHAREPOINT_WORKSHEET_NAME=ASSETS \
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

### Swagger interactive Entra login

`/docs` and `/openapi.json` stay public so users can reach Swagger before signing in.

Enable OAuth in Swagger UI with:

- `VIGILANCE_SWAGGER_USE_OAUTH=true`
- `VIGILANCE_ENTRA_TENANT_ID`
- `VIGILANCE_ENTRA_CLIENT_ID`
- `VIGILANCE_ENTRA_API_SCOPE` (or `VIGILANCE_ENTRA_API_SCOPES`)
- optional `VIGILANCE_ENTRA_AUTHORIZATION_URL`
- optional `VIGILANCE_ENTRA_TOKEN_URL`

When enabled, OpenAPI publishes an OAuth2 `authorizationCode` scheme and Swagger shows **Authorize**. Swagger acquires an access token for this API scope (not Graph) and sends it as bearer auth to protected endpoints.
