"""Smoke test: analyze -> Durable approval lifecycle -> draft PO creation."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:7071/api"


def call(method: str, path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=240) as res:
        return json.loads(res.read())


print("=== 1. POST /procurement/analyze (runs agents, starts orchestration) ===")
result = call("POST", "/procurement/analyze", {
    "event": {
        "event_type": "overdue_purchase_order",
        "tenant_id": "nexer-demo",
        "item_id": "ITEM003",
        "supplier_id": "SUP001",
        "purchase_order_id": "PO-10004",
        "plant": "PLANT-UK-01",
        "severity": "high",
        "context": {"triggered_by": "durable_smoke_test", "days_late": 13},
    }
})
request_id = result["response"]["request_id"]
print(f"request_id           : {request_id}")
print(f"approval_instance_id : {result['approval_instance_id']}")
print(f"recommendations      : {len(result['response']['recommendations'])}")
print(f"rank 1               : {result['response']['recommendations'][0]['action']}"
      f" via {result['response']['recommendations'][0].get('supplier_id')}")

print("\n=== 2. GET /approval/status (should be Running, waiting for human) ===")
status = call("GET", f"/approval/status/{request_id}")
print(f"runtime_status: {status['runtime_status']}")

print("\n=== 3. POST /approval/decision (human approves rank 1) ===")
decision = call("POST", "/approval/decision", {
    "request_id": request_id,
    "rank": 1,
    "decision": "approved",
    "comment": "Approved in durable smoke test",
})
print(f"next_step: {decision['next_step']}")

print("\n=== 4. GET /approval/status (orchestration should complete with draft PO) ===")
for _ in range(15):
    time.sleep(2)
    status = call("GET", f"/approval/status/{request_id}")
    if status["runtime_status"] not in ("Running", "Pending"):
        break
print(f"runtime_status: {status['runtime_status']}")
print(f"output        : {json.dumps(status['output'], indent=2)}")
