from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any


@dataclass(slots=True)
class CommonAssetFields:
    Asset_ID: str
    Asset_Name: str
    Asset_Category: str
    Owner_Org: str
    Owner_Contact: str
    Pilot_s: str
    Purpose: str
    Status: str
    TRL_Start: int
    TRL_Current: int | None = None
    TRL_Target: int | None = None
    Related_Result: str | None = None
    Related_WP_Task: str | None = None
    Deployment_Context: str | None = None
    Standards_Compliance: str | None = None
    Security_Domain: str | None = None
    Documentation_Link: str | None = None
    Last_Updated: datetime | None = None
    Updated_By: str | None = None


@dataclass(slots=True)
class CategorySpecificFields:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CybersecurityToolFields(CategorySpecificFields):
    Tool_Type: str
    Security_Function: str | None = None
    Interfaces_Provided: str | None = None
    Interfaces_Consumed: str | None = None
    Dependencies: str | None = None
    Code_Availability: str | None = None
    License_IP: str | None = None


@dataclass(slots=True)
class PlatformServiceFields(CategorySpecificFields):
    Service_Type: str
    Inputs: str | None = None
    Outputs: str | None = None
    Scalability_Mode: str | None = None


@dataclass(slots=True)
class ComputeResourceFields(CategorySpecificFields):
    Compute_Form: str
    OS_Runtime: str | None = None
    Min_CPU: str | None = None
    Min_RAM: str | None = None
    GPU: str | None = None
    Storage: str | None = None
    Network_Ports: str | None = None


@dataclass(slots=True)
class DataStreamFields(CategorySpecificFields):
    Telemetry_Type: str
    Data_Format: str | None = None
    Frequency: str | None = None
    Data_Sensitivity: str | None = None
    Sharing_Policy: str | None = None


@dataclass(slots=True)
class DataStoreFields(CategorySpecificFields):
    Store_Type: str
    Technology: str | None = None
    Retention: str | None = None
    Encryption: str | None = None


@dataclass(slots=True)
class PhysicalAssetFields(CategorySpecificFields):
    Asset_Subtype: str
    Connectivity: str | None = None
    Firmware_Version: str | None = None
    Criticality: str | None = None
    Constraints: str | None = None


CATEGORY_MODEL_TYPES: dict[str, type[CategorySpecificFields]] = {
    "Cybersecurity Tool": CybersecurityToolFields,
    "Platform / Service": PlatformServiceFields,
    "Compute Resource": ComputeResourceFields,
    "Data Stream / Data Source / Telemetry": DataStreamFields,
    "Data Store / Message Backbone": DataStoreFields,
    "Physical / Cyber-Physical Asset": PhysicalAssetFields,
}


@dataclass(slots=True)
class AssetRecord:
    common: CommonAssetFields
    category_fields: CategorySpecificFields

    @property
    def asset_id(self) -> str:
        return self.common.Asset_ID

    @property
    def category(self) -> str:
        return self.common.Asset_Category

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self.common)
        payload.update(self.category_fields.to_dict())
        return payload


def normalize_last_updated(value: str | date | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_asset_record(payload: dict[str, Any]) -> AssetRecord:
    category = payload["Asset_Category"]
    category_model = CATEGORY_MODEL_TYPES[category]

    common_field_names = set(CommonAssetFields.__annotations__.keys())
    common_payload = {
        key: (normalize_last_updated(value) if key == "Last_Updated" else value)
        for key, value in payload.items()
        if key in common_field_names
    }
    category_payload = {
        key: value
        for key, value in payload.items()
        if key in category_model.__annotations__
    }
    return AssetRecord(
        common=CommonAssetFields(**common_payload),
        category_fields=category_model(**category_payload),
    )
