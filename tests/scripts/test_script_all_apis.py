
#!/usr/bin/env python3
"""
VIGILANCE Asset Inventory API test runner.

Exercises:
- discovery endpoints
- schema/vocabulary endpoints
- list/get
- create valid assets for all categories
- invalid create scenarios
- duplicate ID handling
- patch/put
- delete and post-delete checks

Usage:
  python test_vigilance_api.py --base-url http://localhost:8000

Optional:
  --token <bearer_token>
  --updated-by <name>
  --keep-created
  --timeout 30
  --request-delay 1.25
  --report-dir .
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import random
import string
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests


@dataclass
class TestResult:
    name: str
    method: str
    url: str
    expected: str
    ok: bool
    status_code: Optional[int] = None
    details: str = ""
    response_excerpt: Any = None


@dataclass
class TestContext:
    base_url: str
    session: requests.Session
    timeout: float
    keep_created: bool
    updated_by: str
    request_delay: float
    report_dir: str
    created_ids: List[str] = field(default_factory=list)
    results: List[TestResult] = field(default_factory=list)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rand_suffix(n: int = 6) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))


def asset_id(prefix: str) -> str:
    return f"{prefix}-{rand_suffix()}"


def pretty_excerpt(obj: Any, limit: int = 500) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return s[:limit] + ("..." if len(s) > limit else "")


def try_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def record(ctx: TestContext, result: TestResult) -> None:
    ctx.results.append(result)
    status = "PASS" if result.ok else "FAIL"
    code = f" [{result.status_code}]" if result.status_code is not None else ""
    print(f"{status}{code} {result.name}")
    if not result.ok and result.details:
        print(f"      {result.details}")
    if not result.ok and result.response_excerpt is not None:
        print(f"      response: {pretty_excerpt(result.response_excerpt)}")


def request_json(
    ctx: TestContext,
    name: str,
    method: str,
    path: str,
    *,
    expected_status: Tuple[int, ...],
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
) -> Tuple[bool, Optional[requests.Response], Any]:
    url = ctx.base_url.rstrip("/") + path
    merged_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        merged_headers.update(headers)

    if ctx.request_delay > 0:
        time.sleep(ctx.request_delay)

    try:
        resp = ctx.session.request(
            method=method.upper(),
            url=url,
            json=json_body,
            headers=merged_headers,
            timeout=ctx.timeout,
        )
        payload = try_json(resp)
        ok = resp.status_code in expected_status
        record(ctx, TestResult(
            name=name,
            method=method.upper(),
            url=url,
            expected=" or ".join(map(str, expected_status)),
            ok=ok,
            status_code=resp.status_code,
            details="" if ok else f"Expected {expected_status}, got {resp.status_code}",
            response_excerpt=None if ok else payload,
        ))
        return ok, resp, payload
    except Exception as exc:
        record(ctx, TestResult(
            name=name,
            method=method.upper(),
            url=url,
            expected=" or ".join(map(str, expected_status)),
            ok=False,
            details=f"Request failed: {exc}",
        ))
        return False, None, None


def updater_headers(updated_by: str) -> Dict[str, str]:
    return {"X-Updated-By": updated_by}


def common_fields(aid: str, name: str, category: str) -> Dict[str, Any]:
    return {
        "Asset_ID": aid,
        "Asset_Name": name,
        "Asset_Category": category,
        "Owner_Org": "CUT",
        "Owner_Contact": "marios.touloupou@cut.ac.cy",
        "Pilot_s": "Pilot 1",
        "Purpose": f"Automated test asset for category {category}.",
        "Status": "Active",
        "TRL_Start": 5,
        "TRL_Current": 6,
        "TRL_Target": 7,
        "Related_Result": "RS3",
        "Related_WP_Task": "T5.3",
        "Deployment_Context": "Cloud",
        "Standards_Compliance": "ISO 27001",
        "Security_Domain": "Multi-domain",
        "Documentation_Link": "https://example.com/test-asset",
        "Last_Updated": utc_now_iso(),
        "Updated_By": "api-test-runner",
    }


def payload_cybersecurity_tool(aid: str) -> Dict[str, Any]:
    p = common_fields(aid, "Threat Detection SIEM", "Cybersecurity Tool")
    p.update({
        "Tool_Type": "SIEM (Security Information and Event Management)",
        "Security_Function": "Detect",
        "Interfaces_Provided": "REST API, Dashboard",
        "Interfaces_Consumed": "Syslog, Kafka",
        "Dependencies": "ElasticSearch, Kafka",
        "Code_Availability": "Yes",
        "License_IP": "Commercial",
    })
    return p


def payload_platform_service(aid: str) -> Dict[str, Any]:
    p = common_fields(aid, "Policy Orchestration Service", "Platform / Service")
    p.update({
        "Service_Type": "Policy Management",
        "Inputs": "Incidents, policy rules",
        "Outputs": "Policy decisions, audit events",
        "Scalability_Mode": "Horizontal",
    })
    return p


def payload_compute_resource(aid: str) -> Dict[str, Any]:
    p = common_fields(aid, "Inference Compute Node", "Compute Resource")
    p.update({
        "Compute_Form": "VM",
        "OS_Runtime": "Ubuntu 22.04 / Python 3.11",
        "Min_CPU": "8 vCPU",
        "Min_RAM": "16 GB",
        "GPU": "NVIDIA T4",
        "Storage": "200 GB SSD",
        "Network_Ports": "443, 9092",
    })
    return p


def payload_telemetry(aid: str) -> Dict[str, Any]:
    p = common_fields(aid, "Industrial Telemetry Stream", "Data Stream / Data Source / Telemetry")
    p.update({
        "Telemetry_Type": "Sensor Telemetry",
        "Data_Format": "JSON",
        "Frequency": "Real-time",
        "Data_Sensitivity": "Restricted",
        "Sharing_Policy": "Pilot-restricted",
        "Data_Origin": "Real-world",
    })
    return p


def payload_data_store(aid: str) -> Dict[str, Any]:
    p = common_fields(aid, "Kafka Message Backbone", "Data Store / Message Backbone")
    p.update({
        "Store_Type": "Message Bus",
        "Technology": "Apache Kafka",
        "Retention": "7 days",
        "Encryption": "TLS in transit",
    })
    return p


def payload_physical_asset(aid: str) -> Dict[str, Any]:
    p = common_fields(aid, "PLC Controller", "Physical / Cyber-Physical Asset")
    p.update({
        "Asset_Subtype": "PLC",
        "Connectivity": "Ethernet/IP",
        "Firmware_Version": "v1.2.3",
        "Criticality": "High",
        "Constraints": "Safety-critical environment",
    })
    return p


def test_root_and_discovery(ctx: TestContext) -> None:
    for name, method, path in [
        ("GET /", "GET", "/"),
        ("GET /assets", "GET", "/assets"),
        ("GET /schema/assets", "GET", "/schema/assets"),
        ("GET /vocabularies", "GET", "/vocabularies"),
        ("GET /swagger", "GET", "/swagger"),
        ("GET /docs", "GET", "/docs"),
        ("GET /openapi.json", "GET", "/openapi.json"),
    ]:
        request_json(ctx, name, method, path, expected_status=(200, 404, 405))


def test_list_assets(ctx: TestContext) -> None:
    request_json(ctx, "List assets", "GET", "/assets", expected_status=(200,))


def test_schema_and_vocab(ctx: TestContext) -> None:
    request_json(ctx, "Fetch schema assets", "GET", "/schema/assets", expected_status=(200, 404))
    request_json(ctx, "Fetch schema telemetry category", "GET", "/schema/assets/Data%20Stream%20%2F%20Data%20Source%20%2F%20Telemetry", expected_status=(200, 404))
    request_json(ctx, "Fetch vocabularies", "GET", "/vocabularies", expected_status=(200, 404))
    request_json(ctx, "Fetch Data_Origin vocabulary", "GET", "/vocabularies/Data_Origin", expected_status=(200, 404))


def create_asset(ctx: TestContext, payload: Dict[str, Any], label: str) -> Optional[dict]:
    ok, _, body = request_json(
        ctx,
        f"Create {label}",
        "POST",
        "/assets",
        expected_status=(200, 201),
        json_body=payload,
        headers=updater_headers(ctx.updated_by),
    )
    if ok:
        ctx.created_ids.append(payload["Asset_ID"])
        return body
    return None


def test_create_all_categories(ctx: TestContext) -> None:
    for label, factory in [
        ("Cybersecurity Tool", payload_cybersecurity_tool),
        ("Platform / Service", payload_platform_service),
        ("Compute Resource", payload_compute_resource),
        ("Telemetry", payload_telemetry),
        ("Data Store", payload_data_store),
        ("Physical Asset", payload_physical_asset),
    ]:
        create_asset(ctx, factory(asset_id("ASSET")), label)


def test_duplicate_id(ctx: TestContext) -> None:
    aid = asset_id("DUP")
    payload = payload_cybersecurity_tool(aid)
    first = create_asset(ctx, payload, "duplicate-id seed")
    if first is None:
        return
    request_json(
        ctx,
        "Reject duplicate Asset_ID",
        "POST",
        "/assets",
        expected_status=(400, 409, 422),
        json_body=payload,
        headers=updater_headers(ctx.updated_by),
    )


def test_invalid_category_mismatch(ctx: TestContext) -> None:
    aid = asset_id("BADCAT")
    payload = payload_cybersecurity_tool(aid)
    payload["Service_Type"] = "Policy Management"
    request_json(
        ctx,
        "Reject category-mismatched fields",
        "POST",
        "/assets",
        expected_status=(400, 422),
        json_body=payload,
        headers=updater_headers(ctx.updated_by),
    )


def test_invalid_vocab(ctx: TestContext) -> None:
    aid = asset_id("BADVOC")
    payload = payload_telemetry(aid)
    payload["Data_Origin"] = "Alien Data"
    request_json(
        ctx,
        "Reject invalid Data_Origin vocabulary",
        "POST",
        "/assets",
        expected_status=(400, 422),
        json_body=payload,
        headers=updater_headers(ctx.updated_by),
    )


def test_missing_required(ctx: TestContext) -> None:
    aid = asset_id("MISS")
    payload = payload_platform_service(aid)
    del payload["Asset_Category"]
    request_json(
        ctx,
        "Reject missing required field",
        "POST",
        "/assets",
        expected_status=(400, 422),
        json_body=payload,
        headers=updater_headers(ctx.updated_by),
    )


def test_get_single(ctx: TestContext) -> None:
    aid = asset_id("GETONE")
    payload = payload_compute_resource(aid)
    created = create_asset(ctx, payload, "single-get seed")
    if created is None:
        return
    request_json(ctx, "Get single asset", "GET", f"/assets/{aid}", expected_status=(200,))


def test_filtering(ctx: TestContext) -> None:
    request_json(ctx, "Filter by category", "GET", "/assets?Asset_Category=Cybersecurity%20Tool", expected_status=(200,))
    request_json(ctx, "Filter by owner", "GET", "/assets?Owner_Org=CUT", expected_status=(200,))
    request_json(ctx, "Filter by deployment context", "GET", "/assets?Deployment_Context=Cloud", expected_status=(200,))
    request_json(ctx, "Free-text search", "GET", "/assets?search=policy", expected_status=(200, 400, 404))


def test_patch_and_put(ctx: TestContext) -> None:
    aid = asset_id("PATCH")
    payload = payload_telemetry(aid)
    if create_asset(ctx, payload, "patch seed") is None:
        return

    patch_body = {
        "Status": "Planned",
        "Purpose": "Updated by automated PATCH test.",
        "Data_Origin": "Hybrid",
    }
    request_json(
        ctx,
        "Patch existing asset",
        "PATCH",
        f"/assets/{aid}",
        expected_status=(200, 204),
        json_body=patch_body,
        headers=updater_headers(ctx.updated_by),
    )

    full_body = payload_telemetry(aid)
    full_body["Status"] = "Active"
    full_body["Purpose"] = "Updated by automated PUT test."
    full_body["Data_Origin"] = "Synthetic / Simulated"
    request_json(
        ctx,
        "Put existing asset",
        "PUT",
        f"/assets/{aid}",
        expected_status=(200, 204, 405),
        json_body=full_body,
        headers=updater_headers(ctx.updated_by),
    )

    request_json(ctx, "Get patched asset", "GET", f"/assets/{aid}", expected_status=(200,))


def test_delete_flow(ctx: TestContext) -> None:
    aid = asset_id("DEL")
    payload = payload_physical_asset(aid)
    if create_asset(ctx, payload, "delete seed") is None:
        return

    request_json(
        ctx,
        "Delete existing asset",
        "DELETE",
        f"/assets/{aid}",
        expected_status=(200, 202, 204),
        headers=updater_headers(ctx.updated_by),
    )

    request_json(
        ctx,
        "Get deleted asset",
        "GET",
        f"/assets/{aid}",
        expected_status=(200, 202, 204),
    )


def cleanup_created(ctx: TestContext) -> None:
    if ctx.keep_created:
        return
    for aid in reversed(ctx.created_ids):
        request_json(
            ctx,
            f"Cleanup delete {aid}",
            "DELETE",
            f"/assets/{aid}",
            expected_status=(200, 202, 204, 404, 410),
            headers=updater_headers(ctx.updated_by),
        )


def write_report(ctx: TestContext) -> str:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = Path(ctx.report_dir).expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"vigilance_api_test_report_{timestamp}.json"
    data = {
        "base_url": ctx.base_url,
        "generated_at": utc_now_iso(),
        "summary": {
            "total": len(ctx.results),
            "passed": sum(1 for r in ctx.results if r.ok),
            "failed": sum(1 for r in ctx.results if not r.ok),
        },
        "results": [r.__dict__ for r in ctx.results],
        "created_ids": ctx.created_ids,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return str(path)


def print_summary(ctx: TestContext, report_path: str) -> int:
    total = len(ctx.results)
    passed = sum(1 for r in ctx.results if r.ok)
    failed = total - passed
    print("\n=== Summary ===")
    print(f"Base URL : {ctx.base_url}")
    print(f"Passed   : {passed}")
    print(f"Failed   : {failed}")
    print(f"Total    : {total}")
    print(f"Report   : {report_path}")
    if failed:
        print("\nFailed tests:")
        for r in ctx.results:
            if not r.ok:
                print(f"- {r.name} ({r.method} {r.url}) -> expected {r.expected}, got {r.status_code}")
    return 0 if failed == 0 else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Base URL of the API, e.g. http://localhost:8000")
    parser.add_argument("--token", help="Optional Bearer token")
    parser.add_argument("--updated-by", default="api-test-runner", help="Updater identity to send")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    parser.add_argument("--request-delay", type=float, default=1.25, help="Delay in seconds before each HTTP request")
    parser.add_argument("--report-dir", default=".", help="Directory where the JSON report will be written")
    parser.add_argument("--keep-created", action="store_true", help="Keep created test assets")
    args = parser.parse_args(argv)

    session = requests.Session()
    if args.token:
        session.headers["Authorization"] = f"Bearer {args.token}"

    ctx = TestContext(
        base_url=args.base_url,
        session=session,
        timeout=args.timeout,
        keep_created=args.keep_created,
        updated_by=args.updated_by,
        request_delay=args.request_delay,
        report_dir=args.report_dir,
    )

    try:
        test_root_and_discovery(ctx)
        test_list_assets(ctx)
        test_schema_and_vocab(ctx)
        test_create_all_categories(ctx)
        test_duplicate_id(ctx)
        test_invalid_category_mismatch(ctx)
        test_invalid_vocab(ctx)
        test_missing_required(ctx)
        test_get_single(ctx)
        test_filtering(ctx)
        test_patch_and_put(ctx)
        test_delete_flow(ctx)
    finally:
        cleanup_created(ctx)

    report_path = write_report(ctx)
    return print_summary(ctx, report_path)


if __name__ == "__main__":
    raise SystemExit(main())
