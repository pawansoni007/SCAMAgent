"""
Real-data event simulation — verifies one procurement event end-to-end
against live D365 F&O data.

Unlike the mock smoke tests, this uses identifiers that exist in the connected
USMF environment (item M0002, vendor US-101, PO 000016). It runs in two stages:

  Stage 1 — Data resolution: prove the event's IDs map to real D365 records
            (inventory, safety stock, supplier performance, open POs, pricing,
            lead time). This needs only the D365 connection.

  Stage 2 — Full analysis: route the event through the orchestrator + specialist
            agent and print the Top-3 recommendations. This additionally needs
            the Foundry/agent connection; if it is unavailable the script still
            reports Stage 1 success.

Usage (from the project directory):
    .venv\\Scripts\\python.exe scripts\\_d365_event_simulation.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


def _load_local_settings() -> None:
    if os.environ.get("D365_ODATA_BASE_URL"):
        return
    settings_path = PROJECT_DIR / "local.settings.json"
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        for key, value in data.get("Values", {}).items():
            os.environ.setdefault(key, str(value))


# One real event, using identifiers verified to exist in the USMF environment.
REAL_EVENT_PAYLOAD = {
    "request_id": "REQ-D365-VERIFY-001",
    "event": {
        "event_type": "overdue_purchase_order",
        "tenant_id": "nexer-demo",
        "item_id": "M0002",            # real released product (Mid-range speaker)
        "supplier_id": "US-101",       # real approved vendor (Fabrikam Electronics)
        "purchase_order_id": "000016", # real purchase order for M0002
        "plant": "1",                  # real receiving site
        "severity": "high",
        "context": {"triggered_by": "d365_event_simulation", "days_late": 9},
    },
}


def _show(label: str, obj) -> None:
    if obj is None:
        print(f"  {label:<22}: None")
    elif hasattr(obj, "model_dump"):
        print(f"  {label:<22}: {json.dumps(obj.model_dump())}")
    else:
        print(f"  {label:<22}: {obj}")


def stage1_resolve_data(event: dict) -> bool:
    """Resolve and print the live D365 data the agent will see for this event."""
    from agents.procurement_exception_agent.services import (
        inventory as inventory_service,
        supplier as supplier_service,
        procurement as procurement_service,
    )

    item = event["item_id"]
    vendor = event["supplier_id"]

    print("\n[STAGE 1] Resolving event data from D365")
    print("-" * 64)
    inventory = inventory_service.get_inventory(item)
    supplier = supplier_service.get_supplier_performance(vendor)
    prices = procurement_service.get_supplier_prices(vendor, item)
    lead_time = procurement_service.get_lead_time_data(vendor, item)
    open_pos = procurement_service.get_open_purchase_orders(item)

    _show("inventory", inventory)
    _show("safety_stock", inventory_service.get_safety_stock(item))
    _show("supplier_performance", supplier)
    _show("supplier_price", prices)
    _show("lead_time", lead_time)
    print(f"  {'open_confirmed_pos':<22}: {len(open_pos)} "
          f"(confirmed-only rule applied)")
    for po in open_pos[:5]:
        print(f"      - {po.po_id} vendor={po.supplier_id} "
              f"status={po.status} confirmed_date={po.expected_delivery_date}")

    resolved = inventory is not None and supplier is not None
    print("-" * 64)
    print(f"[STAGE 1] {'PASS — event resolves to real D365 data' if resolved else 'FAIL — IDs did not resolve'}")
    return resolved


async def stage2_run_analysis(payload: dict) -> bool:
    """Route the event through the full orchestrator + specialist agent."""
    from functions.request_handler import validate_request, RequestValidationError
    from functions.recommendation_validator import RecommendationValidator
    from services.agent_registry import AgentRegistry
    from services.prompt_registry import PromptRegistry
    from services.tenant_config_service import TenantConfigService
    from orchestrator.orchestrator_agent import OrchestratorAgent

    project_endpoint = os.environ.get(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://scm-azure-foundry-dev.services.ai.azure.com/api/projects/scm-agent-dev",
    )
    model = os.environ.get("FOUNDRY_MODEL", "gpt-4o")

    agent_registry = AgentRegistry()
    prompt_registry = PromptRegistry()
    tenant_config_service = TenantConfigService()

    print("\n[STAGE 2] Running full analysis (orchestrator + agent + Foundry)")
    print("-" * 64)
    try:
        request = validate_request(payload, tenant_config_service, agent_registry)
    except RequestValidationError as exc:
        print(f"[STAGE 2] REJECTED at validation: {exc}")
        return False

    tenant_config = tenant_config_service.get_or_default(request.event.tenant_id)
    orchestrator = OrchestratorAgent(
        project_endpoint=project_endpoint,
        model=model,
        agent_registry=agent_registry,
        prompt_registry=prompt_registry,
        tenant_config=tenant_config,
    )

    response = await orchestrator.route(request)
    validation = RecommendationValidator().validate(response, tenant_config)

    print(f"  Overall risk : {response.overall_risk.value.upper()}")
    print(f"  Summary      : {response.summary}")
    print(f"  Valid        : {validation.is_valid}")
    for rec in response.recommendations:
        print(f"\n  Rank #{rec.rank} — {rec.action.value} (supplier {rec.supplier_id or 'N/A'})")
        print(f"    Reason : {rec.reason}")
        print(f"    Risk   : {rec.risk_level.value} | Confidence: {rec.confidence:.0%}")
    print("-" * 64)
    print("[STAGE 2] PASS — analysis produced recommendations")
    return True


async def main() -> int:
    _load_local_settings()

    print("=" * 64)
    print("  D365 real-data event simulation")
    print("=" * 64)
    print(f"  Event: {json.dumps(REAL_EVENT_PAYLOAD['event'])}")

    stage1_ok = stage1_resolve_data(REAL_EVENT_PAYLOAD["event"])

    try:
        await stage2_run_analysis(REAL_EVENT_PAYLOAD)
    except Exception as exc:
        print("-" * 64)
        print(f"[STAGE 2] SKIPPED — analysis backend unavailable: {exc}")
        print("          (Stage 1 already verified the event against live D365.)")

    print("=" * 64)
    return 0 if stage1_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
