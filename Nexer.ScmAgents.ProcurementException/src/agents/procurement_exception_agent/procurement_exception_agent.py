"""
Procurement exception specialist agent.

Uses the agent design contract, tool contract, and versioned prompt package to
produce top-3 recommendations for buyer review.
"""

import json

from azure.core.credentials import TokenCredential
from agent_framework import Agent
from agent_framework_foundry import FoundryChatClient

from services.azure_credential import get_azure_credential
from agents.procurement_exception_agent.services.policy.policy_service import (
    get_policies_for_exception,
    format_policies_for_prompt,
)
from models.scm_event import (
    OrchestratorRequest,
    Top3Response,
    ProcurementRecommendation,
    RiskLevel,
    RecommendationAction,
)
from services.prompt_registry import PromptRegistry
from services.tenant_config_service import TenantConfig
from agents.procurement_exception_agent.tools import PROCUREMENT_TOOLS

AGENT_ID = "scm-procurement-exception-agent"
AGENT_VERSION = "1.0.0"


class ProcurementExceptionAgent:
    """
    Procurement Exception Agent — Microsoft Agent Framework implementation.

    Runtime assets are loaded at construction time:
      - Prompt package   : from the PromptRegistry (active version per agent)
      - Tenant variables : substituted into prompt placeholders (Section 7)
      - Tool contract    : PROCUREMENT_TOOLS (FunctionTool list, Section 6)

    Exposes:
      - analyze()  : direct invocation with OrchestratorRequest → Top3Response
      - as_tool()  : wraps this agent as a FunctionTool for the OrchestratorAgent
    """

    def __init__(
        self,
        project_endpoint: str,
        model: str = "gpt-4o",
        credential: TokenCredential | None = None,
        tenant_config: TenantConfig | None = None,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        registry = prompt_registry or PromptRegistry()
        package = registry.load_package(AGENT_ID)
        self.prompt_package_version = package.package_version

        variables = tenant_config.prompt_variables() if tenant_config else {}
        instructions = package.build_instructions(variables)

        self._agent = Agent(
            client=FoundryChatClient(
                project_endpoint=project_endpoint,
                model=model,
                credential=credential or get_azure_credential(),
            ),
            name=AGENT_ID,
            description=(
                "Analyzes procurement exceptions and produces Top 3 ranked "
                "recommendations for human approval. Covers overdue purchase "
                "orders, supplier delays, blocked purchase orders, lead time "
                "deviations and supplier risk alerts."
            ),
            instructions=instructions,
            tools=PROCUREMENT_TOOLS,
        )

    def as_tool(self):
        """
        Expose this agent as a FunctionTool for the OrchestratorAgent,
        using Agent Framework's built-in .as_tool().
        """
        return self._agent.as_tool(
            name="analyze_procurement_exception",
            description=(
                "Analyze a procurement exception event and return Top 3 ranked "
                "recommendations for human approval. Invoke for event types: "
                "overdue_purchase_order, supplier_delay, blocked_purchase_order, "
                "lead_time_deviation, supplier_risk_alert, procurement_exception."
            ),
            arg_name="task",
            arg_description=(
                "Full description of the procurement exception to analyze. Include: "
                "event_type, item_id, supplier_id (if known), plant, severity, tenant_id, "
                "purchase_order_id (if applicable), and any additional context."
            ),
        )

    async def analyze(self, request: OrchestratorRequest) -> Top3Response:
        """
        Run the agent for the given OrchestratorRequest and return a Top3Response.

        Step 1 — Policy retrieval: query Azure AI Search for policies relevant
                 to this exception BEFORE the LLM sees the prompt.
        Step 2 — Context prompt: inject both the SCM event fields AND the
                 retrieved policies so the LLM reasons against real rules.
        Step 3 — Agent run: LLM calls tools, applies policies, ranks Top 3.
        """
        event = request.event

        # ── Step 1: Fetch relevant policies from Azure AI Search ──────────────
        exception_context = {
            "exception_type":  event.event_type.value,
            "item_description": event.item_id,
            "supplier_name":   event.supplier_id,
            "is_emergency":    event.severity.value == "high",
            "total_value":     (event.context or {}).get("total_value"),
            "is_single_source": (event.context or {}).get("is_single_source", False),
        }
        policies = get_policies_for_exception(exception_context, event.tenant_id)
        policy_text = format_policies_for_prompt(policies)

        # ── Step 2: Build context prompt with policies injected ───────────────
        context_prompt = (
            f"Analyze the following procurement exception and produce Top 3 recommendations.\n\n"
            f"=== SCM Event Context ===\n"
            f"Event Type      : {event.event_type.value}\n"
            f"Tenant ID       : {event.tenant_id}\n"
            f"Item ID         : {event.item_id}\n"
            f"Supplier ID     : {event.supplier_id or 'not specified — use getApprovedSuppliers()'}\n"
            f"Plant           : {event.plant or 'not specified'}\n"
            f"Purchase Order  : {event.purchase_order_id or 'not specified'}\n"
            f"Severity        : {event.severity.value}\n"
            f"Request ID      : {request.request_id or 'not set'}\n"
        )
        if event.context:
            context_prompt += f"Additional Context: {json.dumps(event.context)}\n"

        context_prompt += f"\n{policy_text}\n"

        context_prompt += (
            "\nFollow the reasoning steps in your instructions. "
            "Call tools to gather data, apply the procurement policies above, "
            "rank recommendations, write the audit log, then return the JSON output. "
            "Every recommendation MUST reference any applicable policy by its ID "
            "(e.g. POL-001) in the policy_constraints_applied field."
        )

        # ── Step 3: Run agent ─────────────────────────────────────────────────
        agent_response = await self._agent.run(context_prompt)
        raw_text = agent_response.text.strip()

        return self.parse_response(raw_text, request)

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """
        Extract a JSON object from the agent's raw output.

        Handles markdown code fences and any leading/trailing prose by
        locating the outermost '{' ... '}' span if a direct parse fails.
        """
        text = raw_text
        if text.startswith("```"):
            text = "\n".join(
                line for line in text.splitlines() if not line.startswith("```")
            ).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end <= start:
                raise
            return json.loads(text[start:end + 1])

    def parse_response(self, raw_text: str, request: OrchestratorRequest) -> Top3Response:
        """
        Parse the agent's JSON output into a validated Top3Response.

        If parsing fails, returns a safe fallback Top3Response with
        is_fallback=True and an escalation recommendation
        (blueprint fallback scenario: 'LLM output invalid').
        """
        try:
            data = self._extract_json(raw_text)

            recommendations = [
                ProcurementRecommendation(
                    rank=rec["rank"],
                    action=RecommendationAction(rec["action"]),
                    supplier_id=rec.get("supplier_id"),
                    reason=rec["reason"],
                    risk_level=RiskLevel(rec["risk_level"]),
                    confidence=float(rec["confidence"]),
                    policy_constraints_applied=rec.get("policy_constraints_applied", []),
                    expected_operational_impact=rec["expected_operational_impact"],
                    requires_human_approval=rec.get("requires_human_approval", True),
                    is_fallback=rec.get("is_fallback", False),
                )
                for rec in data["recommendations"]
            ]

            return Top3Response(
                request_id=request.request_id,
                tenant_id=request.event.tenant_id,
                item_id=request.event.item_id,
                event_type=request.event.event_type,
                recommendations=recommendations,
                overall_risk=RiskLevel(data["overall_risk"]),
                summary=data["summary"],
                human_approval_required=True,
                agent_id=AGENT_ID,
                agent_version=AGENT_VERSION,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            return Top3Response(
                request_id=request.request_id,
                tenant_id=request.event.tenant_id,
                item_id=request.event.item_id,
                event_type=request.event.event_type,
                recommendations=[
                    ProcurementRecommendation(
                        rank=1,
                        action=RecommendationAction.ESCALATE_TO_MANAGER,
                        reason=(
                            f"Agent response could not be parsed. Manual review required. "
                            f"Raw output (first 300 chars): {raw_text[:300]}"
                        ),
                        risk_level=RiskLevel.HIGH,
                        confidence=0.0,
                        policy_constraints_applied=["POL-002: Human Approval Requirement"],
                        expected_operational_impact="Unknown — manual review and escalation required.",
                        is_fallback=True,
                    )
                ],
                overall_risk=RiskLevel.HIGH,
                summary=(
                    f"Agent response parsing failed ({exc}). "
                    "Automatic escalation to procurement manager recommended."
                ),
                human_approval_required=True,
                agent_id=AGENT_ID,
                agent_version=AGENT_VERSION,
            )
