# Asset Inventory Schema

## Overview

This document describes the asset model used by the VIGILANCE T2.3 cybersecurity asset and technology inventory.

The inventory is backed initially by a spreadsheet, but the service should behave as an inventory API rather than a thin spreadsheet wrapper.

The `ASSETS` sheet is the primary data table. Each row represents exactly one asset.

## Design principles

- One row = one asset
- Each asset has one stable unique identifier: `Asset_ID`
- Each asset belongs to exactly one `Asset_Category`
- All assets share a set of common fields
- Each category has its own category-specific fields
- Controlled vocabularies must be enforced where defined
- Fields from non-selected categories must remain empty or omitted

## Asset categories

The current controlled asset categories are:

- `Cybersecurity Tool`
- `Platform / Service`
- `Compute Resource`
- `Data Stream / Data Source / Telemetry`
- `Data Store / Message Backbone`
- `Physical / Cyber-Physical Asset`

## Common fields

The following fields are common to all assets.

### `Asset_ID`
Unique and stable asset identifier. This is the API resource identifier and must remain stable over time.

### `Asset_Name`
Human-readable name of the asset.

### `Asset_Category`
High-level category of the asset. Must be one of the controlled vocabulary values.

### `Owner_Org`
Organisation that owns or is responsible for the asset.

### `Owner_Contact`
Contact person for the asset.

### `Pilot_s`
Pilot or pilots in which the asset is used, or `N/A` if not pilot-specific.

### `Purpose`
Short description of the role and intended use of the asset. The spreadsheet guidance suggests 1–2 sentences.

### `Status`
Lifecycle status of the asset. Current controlled values are:
- `Not Started`
- `Planned`
- `Active`
- `Deprecated`

### `TRL_Start`
Technology Readiness Level at the start of the project. Integer in the range 1..9.

### `TRL_Current`
Current Technology Readiness Level. Integer in the range 1..9. This is useful operationally, even if not explicitly listed among the minimum mandatory fields in the guidance.

### `TRL_Target`
Target Technology Readiness Level by the end of the project. Integer in the range 1..9.

### `Related_Result`
Project result or results associated with the asset, for example `RS3`, `RS4`, or `N/A`.

### `Related_WP_Task`
Work package and task primarily associated with the asset, for example `T5.3`.

### `Deployment_Context`
Deployment environment for the asset. Current controlled values are:
- `IT`
- `OT`
- `IoT`
- `Cloud`
- `Hybrid`

### `Standards_Compliance`
Standards, frameworks, or specifications associated with the asset, for example `IEC 62443` or `NIST SP 800-207`.

### `Security_Domain`
Security domain to which the asset mainly belongs. Current controlled values include:
- `Network Security`
- `Endpoint Security`
- `Identity Security`
- `Application Security`
- `Data Security`
- `Cloud Security`
- `OT Security`
- `IoT Security`
- `Multi-domain`
- `N/A`

### `Documentation_Link`
Optional URL to supporting documentation or reference material.

### `Last_Updated`
Timestamp or date of the last update.

### `Updated_By`
Identifier, organisation, or person that last updated the record.

## Category-specific fields

Only the fields for the selected category may be populated.

---

## Category: `Cybersecurity Tool`

These fields apply only when `Asset_Category = Cybersecurity Tool`.

### `Tool_Type`
Functional classification of the tool.

Current controlled values:
- `SIEM (Security Information and Event Management)`
- `EDR (Endpoint Detection and Response)`
- `IAM (Identity and Access Management)`
- `TEM (Threat Exposure Management)`
- `Scanner (Vulnerability / Security Scanner)`
- `Red Teaming`
- `Policy Engine`
- `Threat Intelligence`
- `N/A`

### `Security_Function`
Primary security function.

Current controlled values:
- `Prevent`
- `Detect`
- `Respond`
- `Recover`
- `Investigate`
- `Monitor`
- `Assess`
- `Govern`
- `N/A`

### `Interfaces_Provided`
Interfaces, APIs, or outputs exposed by the tool.

### `Interfaces_Consumed`
Interfaces, APIs, or input dependencies used by the tool.

### `Dependencies`
External services, datasets, platforms, or components required by the tool.

### `Code_Availability`
Current controlled values:
- `Yes`
- `Partial`
- `No`
- `TBD`

### `License_IP`
Licensing or intellectual-property conditions.

Suggested minimum category-specific requirement:
- `Tool_Type`

---

## Category: `Platform / Service`

These fields apply only when `Asset_Category = Platform / Service`.

### `Service_Type`
Functional classification of the platform or service.

Current controlled values:
- `Platform Infrastructure`
- `Policy Management`
- `Security Service`
- `Reasoning / Analytics`
- `Identity`
- `Data Management`
- `Integration / API Service`
- `N/A`

### `Inputs`
Data or information consumed by the service.

### `Outputs`
Data or information produced by the service.

### `Scalability_Mode`
Deployment or scaling characteristic, for example horizontal, vertical, fixed, or `N/A`.

Suggested minimum category-specific requirement:
- `Service_Type`

Note: the workbook guidance dictionary mentions an `AuthN_AuthZ` field, but this field is not present in the current `ASSETS` sheet header. It is therefore excluded from the current schema.

---

## Category: `Compute Resource`

These fields apply only when `Asset_Category = Compute Resource`.

### `Compute_Form`
Form factor of the compute resource.

Current controlled values:
- `VM`
- `Container`
- `Kubernetes Cluster`
- `Edge Node`
- `Bare Metal`
- `N/A`

### `OS_Runtime`
Operating system or runtime environment.

### `Min_CPU`
Minimum CPU requirement or capacity description.

### `Min_RAM`
Minimum memory requirement or capacity description.

### `GPU`
GPU requirement or availability.

### `Storage`
Storage requirement or capacity.

### `Network_Ports`
Networking or port requirements.

Suggested minimum category-specific requirement:
- `Compute_Form`

---

## Category: `Data Stream / Data Source / Telemetry`

These fields apply only when `Asset_Category = Data Stream / Data Source / Telemetry`.
Canonical telemetry field order in the worksheet/API mapping:
`Telemetry_Type`, `Data_Format`, `Frequency`, `Data_Sensitivity`, `Sharing_Policy`, `Data_Origin`.

### `Telemetry_Type`
Type of telemetry or data source. No controlled vocabulary is currently defined in the workbook.

### `Data_Format`
Data format, for example JSON, CSV, syslog, protobuf.

### `Frequency`
Frequency or mode of generation, for example real-time, event-driven, hourly, batch.

### `Data_Sensitivity`
Sensitivity classification. No controlled vocabulary is currently defined in the workbook.

### `Sharing_Policy`
Current controlled values:
- `Public`
- `Consortium-internal`
- `Pilot-restricted`
- `Restricted`
- `Confidential`
- `N/A`

### `Data_Origin`
Telemetry/data provenance origin classification.

Current controlled values:
- `Real-world`
- `Synthetic / Simulated`
- `Hybrid`

Suggested minimum category-specific requirement:
- `Telemetry_Type`

---

## Category: `Data Store / Message Backbone`

These fields apply only when `Asset_Category = Data Store / Message Backbone`.

### `Store_Type`
Type of store or messaging component. No controlled vocabulary is currently defined in the workbook.

### `Technology`
Underlying technology.

### `Retention`
Retention policy or duration.

### `Encryption`
Encryption status or encryption mechanism.

Suggested minimum category-specific requirement:
- `Store_Type`

---

## Category: `Physical / Cyber-Physical Asset`

These fields apply only when `Asset_Category = Physical / Cyber-Physical Asset`.

### `Asset_Subtype`
Subtype of the physical or cyber-physical asset. No controlled vocabulary is currently defined in the workbook.

### `Connectivity`
Connectivity interfaces or protocols.

### `Firmware_Version`
Firmware or software version.

### `Criticality`
Operational or security criticality.

Current controlled values:
- `Low`
- `Medium`
- `High`

### `Constraints`
Operational, safety, regulatory, or technical constraints.

Suggested minimum category-specific requirement:
- `Asset_Subtype`

## Required fields

### Required for all assets
The following should be treated as required at API level:

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

### Strongly recommended for all assets
These should usually be present, even if not strictly enforced in the first API version:

- `TRL_Current`
- `Security_Domain`

### Required category-specific discriminator field
At minimum, exactly one of the following must be present depending on category:

- `Tool_Type`
- `Service_Type`
- `Compute_Form`
- `Telemetry_Type`
- `Store_Type`
- `Asset_Subtype`

## Validation rules

### Identifiers
- `Asset_ID` must be unique.
- `Asset_ID` should be treated as immutable after creation unless there is an explicit administrative migration.

### TRL values
- `TRL_Start`, `TRL_Current`, and `TRL_Target` must be integers in `1..9` when provided.

### Vocabulary enforcement
Where the workbook defines a controlled vocabulary, the API must validate against it.

### Category exclusivity
If an asset belongs to category `X`, fields for categories `Y` and `Z` must not be populated.

### URLs
- `Documentation_Link` is optional.
- If present, it should be a valid URL.

### Timestamps
- `Last_Updated` should accept ISO date or datetime input and be normalized by the service.

## API serialization guidance

For API payloads, normalize spreadsheet-style field names into consistent JSON keys if desired, but preserve a reversible mapping to spreadsheet column headers.

Suggested normalization:
- replace spaces and punctuation with underscores
- keep names stable
- avoid ambiguous aliases

Example:
- spreadsheet header `Pilot (s)` → API field `Pilot_s`
- spreadsheet header `Purpose (1-2 sentences)` → API field `Purpose`

## Recommended implementation strategy

The service should define:
- a common asset base model
- category-specific validation rules
- a repository interface
- a spreadsheet-backed repository implementation

The spreadsheet is currently the persistence layer, not the schema definition layer.
