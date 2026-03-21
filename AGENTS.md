# AGENTS.md

## Project purpose

This repository implements an asset inventory service for the VIGILANCE T2.3 cybersecurity asset and technology inventory.

The service must treat the spreadsheet as a storage backend, not as the domain model itself.

The API should expose a clean inventory service over the `ASSETS` sheet, with:
- CRUD operations for assets
- filtering, sorting, pagination, and free-text search
- category-aware validation
- controlled vocabulary endpoints
- schema discovery endpoints
- a storage abstraction so the backend can later move from spreadsheet storage to a database without changing the API surface

## Canonical schema and vocabulary files

Always treat the following files as the canonical repository-level definition of the asset model:

- `docs/assets-schema.md`
- `schema/assets_schema.json`

If implementation details conflict with assumptions, prefer the actual `ASSETS` sheet column structure reflected in `schema/assets_schema.json`.

## Domain model rules

### General
- One row in the `ASSETS` sheet represents exactly one asset.
- `Asset_ID` is the unique stable identifier for an asset.
- The API resource key is `Asset_ID`.
- Common fields apply to all assets.
- Category-specific fields apply only to the selected `Asset_Category`.

### Required common fields
These fields are required for all assets unless the schema says otherwise:

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

### Category rule
Each asset has exactly one `Asset_Category`.

Only the category-specific fields for that category may be populated. Fields belonging to other categories must be empty, null, or omitted in API payloads unless the schema explicitly allows `"N/A"`.

### Validation
Implement validation for:
- required common fields
- unique `Asset_ID`
- controlled vocabulary values where vocabularies are defined
- integer TRL values in the range 1..9
- category-specific required fields
- category-specific field exclusivity
- `Documentation_Link` as optional URL
- `Last_Updated` as date or datetime accepted by the API, normalized internally

### Storage and architecture
Do not couple Flask routes directly to spreadsheet access.

Use a storage abstraction such as:
- `AssetRepository` interface
- `SpreadsheetAssetRepository` implementation

Routes should depend on application services or repository interfaces, not directly on Google Sheets or Excel logic.

Do not hardcode spreadsheet column indexes. Always map by header name.

## API expectations

The first implementation should support:

- `GET /assets`
- `GET /assets/<asset_id>`
- `POST /assets`
- `PATCH /assets/<asset_id>`
- `PUT /assets/<asset_id>` if convenient
- `DELETE /assets/<asset_id>` or a soft-delete/archive strategy
- `GET /vocabularies`
- `GET /vocabularies/<name>`
- `GET /schema/assets`
- `GET /schema/assets/<category>`

### `GET /assets`
Support:
- filtering by key fields such as category, owner, status, pilot, deployment context, security domain, and related WP task
- sorting
- pagination
- optional free-text search on selected descriptive fields

## Spreadsheet assumptions

The current workbook has:
- an `ASSETS` sheet as the inventory table
- a `VOCABULARIES` sheet with controlled values
- an example sheet for reference

The API should primarily target the `ASSETS` sheet for now.

The `RELATIONSHIPS` sheet is out of scope for the first version unless explicitly requested.

## Implementation priorities

### Version 1
Focus on:
1. schema models
2. validation
3. repository abstraction
4. spreadsheet-backed repository
5. CRUD endpoints
6. filtering and search
7. vocabulary endpoints
8. tests

### Version 2
Potential follow-up work:
- bulk import/update
- audit trail
- completeness/quality report
- authentication and authorization
- relationship support

## Testing
Add tests for:
- valid asset creation per category
- rejection of category-incompatible fields
- rejection of invalid vocabulary values
- TRL range validation
- retrieval by `Asset_ID`
- filtering on common fields
- update semantics for `PATCH`

## Practical constraints
- Keep code modular and production-oriented.
- Prefer explicit models and validators over ad hoc dictionary handling.
- Keep spreadsheet-specific logic isolated so the backend can later be swapped for PostgreSQL or another datastore.
