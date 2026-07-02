"""
Local entry point for running a single procurement analysis.

Uses a sample event payload, routes it through the orchestrator and specialist
agent, validates the response, and prints the recommendations.
"""

import asyncio
import os

from functions.request_handler import validate_request, RequestValidationError
from functions.recommendation_validator import RecommendationValidator
from services.agent_registry import AgentRegistry
from services.prompt_registry import PromptRegistry
from services.tenant_config_service import TenantConfigService
from orchestrator.orchestrator_agent import OrchestratorAgent

PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT",
    "https://scm-azure-foundry-dev.services.ai.azure.com/api/projects/scm-agent-dev",
)
MODEL = os.environ.get("FOUNDRY_MODEL", "gpt-4o")


# Sample event payload (local run only)
INCOMING_PAYLOAD = {
    "request_id": "REQ-2026-001",
    "event": {
        "event_type": "overdue_purchase_order",
        "tenant_id": "nexer-demo",
        "item_id": "ITEM002",
        "supplier_id": "SUP001",
        "purchase_order_id": "PO-10001",
        "plant": "PLANT-UK-01",
        "severity": "high",
        "context": {"triggered_by": "po_due_date_monitor", "days_late": 10},
    },
}


async def main() -> None:
    print("=" * 64)
    print("  SCM Procurement Runtime Flow")
    print("=" * 64)

    # Load runtime services
    agent_registry = AgentRegistry()
    prompt_registry = PromptRegistry()
    tenant_config_service = TenantConfigService()

    # Validate request payload and tenant
    try:
        request = validate_request(INCOMING_PAYLOAD, tenant_config_service, agent_registry)
    except RequestValidationError as exc:
        print(f"\n[REJECTED] {exc}")
        return

    tenant_config = tenant_config_service.get_or_default(request.event.tenant_id)

    print(f"\n[REQUEST VALIDATED]")
    print(f"  Request ID : {request.request_id}")
    print(f"  Event Type : {request.event.event_type.value}")
    print(f"  Item ID    : {request.event.item_id}")
    print(f"  Tenant     : {request.event.tenant_id}")
    print(f"  Tenant Rules: approved_suppliers_only={tenant_config.rules.approved_suppliers_only}, "
          f"min_reliability={tenant_config.rules.min_supplier_reliability}")

    # Route to specialist agent
    print("\n[ROUTING] Orchestrator -> specialist agent ...")
    orchestrator = OrchestratorAgent(
        project_endpoint=PROJECT_ENDPOINT,
        model=MODEL,
        agent_registry=agent_registry,
        prompt_registry=prompt_registry,
        tenant_config=tenant_config,
    )

    response = await orchestrator.route(request)

    # Validate recommendations against configured rules
    validator = RecommendationValidator()
    validation = validator.validate(response, tenant_config)

    print(f"\n[VALIDATION] valid={validation.is_valid}")
    for err in validation.schema_errors:
        print(f"  schema error : {err}")
    for v in validation.rule_violations:
        print(f"  rule violation: [{v.rule}] rank {v.recommendation_rank} - {v.detail}")

    # Output recommendations for human approval
    print("\n[TOP 3 RECOMMENDATIONS]")
    print(f"  Overall Risk : {response.overall_risk.value.upper()}")
    print(f"  Summary      : {response.summary}")
    print(f"  Agent        : {response.agent_id} v{response.agent_version}")
    print()

    for rec in response.recommendations:
        print(f"  Rank #{rec.rank} - {rec.action.value}")
        print(f"    Supplier   : {rec.supplier_id or 'N/A'}")
        print(f"    Reason     : {rec.reason}")
        print(f"    Risk       : {rec.risk_level.value}  |  Confidence: {rec.confidence:.0%}")
        print(f"    Impact     : {rec.expected_operational_impact}")
        print(f"    Policies   : {', '.join(rec.policy_constraints_applied) or 'none'}")
        print(f"    Fallback   : {rec.is_fallback}  |  Needs Approval: {rec.requires_human_approval}")
        print()

    print("-" * 64)
    print("[AWAITING HUMAN APPROVAL - no ERP action taken]")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
