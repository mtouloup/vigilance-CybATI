from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

BASE_COMMON = {
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
    "Updated_By": "owner@example.org",
}

CATEGORY_SPECIFICS: dict[str, dict[str, Any]] = {
    "Cybersecurity Tool": {
        "Tool_Type": "SIEM (Security Information and Event Management)",
        "Security_Function": "Monitor",
        "Interfaces_Provided": "REST API",
        "Interfaces_Consumed": "Syslog",
        "Dependencies": "Threat feed",
        "Code_Availability": "Yes",
        "License_IP": "Apache-2.0",
    },
    "Platform / Service": {
        "Service_Type": "Security Service",
        "Inputs": "Telemetry",
        "Outputs": "Alerts",
        "Scalability_Mode": "Horizontal",
    },
    "Compute Resource": {
        "Compute_Form": "Container",
        "OS_Runtime": "Linux",
        "Min_CPU": "4 vCPU",
        "Min_RAM": "8 GB",
        "GPU": "None",
        "Storage": "50 GB",
        "Network_Ports": "443/tcp",
    },
    "Data Stream / Data Source / Telemetry": {
        "Telemetry_Type": "Network flow telemetry",
        "Data_Format": "JSON",
        "Frequency": "real-time",
        "Data_Sensitivity": "Restricted",
        "Sharing_Policy": "Consortium-internal",
        "Data_Origin": "Real-world",
    },
    "Data Store / Message Backbone": {
        "Store_Type": "Message queue",
        "Technology": "Kafka",
        "Retention": "14 days",
        "Encryption": "AES-256",
    },
    "Physical / Cyber-Physical Asset": {
        "Asset_Subtype": "PLC",
        "Connectivity": "Ethernet",
        "Firmware_Version": "v1.2.3",
        "Criticality": "High",
        "Constraints": "Maintenance window only",
    },
}


def asset_payload(category: str, *, asset_id: str | None = None, asset_name: str | None = None, **overrides: Any) -> dict[str, Any]:
    payload = {
        "Asset_ID": asset_id or f"AST-{abs(hash(category)) % 1000:03d}",
        "Asset_Name": asset_name or f"{category} Asset",
        "Asset_Category": category,
        **BASE_COMMON,
        **CATEGORY_SPECIFICS[category],
    }
    payload.update(overrides)
    return deepcopy(payload)


def canonical_assets() -> list[dict[str, Any]]:
    categories = list(CATEGORY_SPECIFICS)
    return [
        asset_payload(category, asset_id=f"AST-{index:03d}", asset_name=f"{category} #{index}")
        for index, category in enumerate(categories, start=1)
    ]


def now_utc() -> datetime:
    return datetime(2026, 3, 21, 12, 30, tzinfo=timezone.utc)
