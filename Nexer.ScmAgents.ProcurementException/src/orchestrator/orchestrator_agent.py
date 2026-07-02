import json
from azure.core.credentials import TokenCredential
from agent_framework import Agent
from agent_framework_foundry import FoundryChatClient

from services.azure_credential import get_azure_credential
from models.scm_event import OrchestratorRequest, Top3Response, ScmEventType
from services.agent_registry import AgentRegistry
from services.prompt_registry import PromptRegistry
from services.tenant_config_service import TenantConfig
from agents.procurement_exception_agent.procurement_exception_agent import (
    ProcurementExceptionAgent,
    AGENT_ID as PROCUREMENT_AGENT_ID,
)

ORCHESTRATOR_ID = "scm-orchestrator-agent"
ORCHESTRATOR_VERSION = "1.0.0"

# Event types handled by the Procurement Exception Agent
PROCUREMENT_EVENT_TYPES = {
    ScmEventType.OVERDUE_PURCHASE_ORDER,
    ScmEventType.SUPPLIER_DELAY,
    ScmEventType.BLOCKED_PURCHASE_ORDER,
    ScmEventType.LEAD_TIME_DEVIATION,
    ScmEventType.SUPPLIER_RISK_ALERT,
    ScmEventType.PROCUREMENT_EXCEPTION,
}

ORCHESTRATOR_INSTRUCTIONS = """
You are the SCM Orchestration Agent for the SCM procurement platform.

YOUR ROLE:
You receive Supply Chain Management (SCM) exception events and route them
to the correct specialist agent for analysis and recommendation generation.

AVAILABLE SPECIALIST AGENTS (registered as tools):
- analyze_procurement_exception(task):
    Handles all procurement-related exceptions including:
    overdue_purchase_order, supplier_delay, blocked_purchase_order,
    lead_time_deviation, supplier_risk_alert, procurement_exception.

ROUTING RULES:
1. Read the event_type from the task description.
2. If event_type is one of the procurement types listed above,
   call analyze_procurement_exception with the full task description.
3. Always forward the complete event details (event_type, item_id, supplier_id,
   severity, tenant_id, and any context) to the specialist agent.
4. If no specialist agent matches the event type, respond with:
   {"error": "No specialist agent available for event type: <event_type>"}

OUTPUT RULES (CRITICAL):
- The specialist tool returns a JSON object as its result.
- Your final response MUST be that JSON object EXACTLY as the tool returned it.
- Do NOT summarize, reformat, rephrase, or wrap it in markdown.
- Do NOT add any text before or after the JSON.
- Your entire response must be a single valid JSON object and nothing else.

IMPORTANT:
- You are a routing layer only. Do NOT generate recommendations yourself.
- Always delegate reasoning to the appropriate specialist agent.
- Always pass the full event context to the specialist agent tool.
""".strip()


class OrchestratorAgent:
    """
    SCM Orchestration Agent — Microsoft Agent Framework implementation.

    Registers specialist agents as FunctionTools via agent.as_tool() and
    consults the Agent Registry before routing.
    """

    def __init__(
        self,
        project_endpoint: str,
        model: str = "gpt-4o",
        credential: TokenCredential | None = None,
        agent_registry: AgentRegistry | None = None,
        prompt_registry: PromptRegistry | None = None,
        tenant_config: TenantConfig | None = None,
    ) -> None:
        resolved_credential = credential or get_azure_credential()
        self._agent_registry = agent_registry or AgentRegistry()

        self._procurement_agent = ProcurementExceptionAgent(
            project_endpoint=project_endpoint,
            model=model,
            credential=resolved_credential,
            tenant_config=tenant_config,
            prompt_registry=prompt_registry,
        )

        self._agent = Agent(
            client=FoundryChatClient(
                project_endpoint=project_endpoint,
                model=model,
                credential=resolved_credential,
            ),
            name=ORCHESTRATOR_ID,
            description=(
                "SCM Orchestration Agent. Routes SCM exception events to "
                "the appropriate specialist agent for analysis."
            ),
            instructions=ORCHESTRATOR_INSTRUCTIONS,
            tools=[
                self._procurement_agent.as_tool(),
            ],
        )

    async def route(self, request: OrchestratorRequest) -> Top3Response:
        """
        Route an OrchestratorRequest to the appropriate specialist agent.

        Checks the Agent Registry for specialist availability, builds the
        routing prompt, runs the orchestrator (which delegates via the
        specialist's FunctionTool), and returns the parsed Top3Response.

        Raises:
            ValueError: If no specialist handles the event type, or the
                specialist is not active/available to the tenant.
        """
        event = request.event

        if event.event_type not in PROCUREMENT_EVENT_TYPES:
            raise ValueError(
                f"No specialist agent registered for event type '{event.event_type.value}'."
            )

        if not self._agent_registry.is_available(PROCUREMENT_AGENT_ID, event.tenant_id):
            raise ValueError(
                f"Specialist agent '{PROCUREMENT_AGENT_ID}' is not active or not "
                f"available to tenant '{event.tenant_id}' (Agent Registry check failed)."
            )

        routing_prompt = self._build_routing_prompt(request)
        agent_response = await self._agent.run(routing_prompt)
        raw_text = agent_response.text.strip()

        return self._procurement_agent.parse_response(raw_text, request)

    def _build_routing_prompt(self, request: OrchestratorRequest) -> str:
        """Build the routing prompt the orchestrator LLM uses to pick a specialist tool."""
        event = request.event
        lines = [
            "Route the following SCM exception event to the correct specialist agent.\n",
            f"Request ID    : {request.request_id or 'not set'}",
            f"Event Type    : {event.event_type.value}",
            f"Item ID       : {event.item_id}",
            f"Supplier ID   : {event.supplier_id or 'not specified'}",
            f"Plant         : {event.plant or 'not specified'}",
            f"Purchase Order: {event.purchase_order_id or 'not specified'}",
            f"Severity      : {event.severity.value}",
            f"Tenant ID     : {event.tenant_id}",
        ]
        if event.context:
            lines.append(f"Additional Context: {json.dumps(event.context)}")

        lines.append(
            "\nCall the appropriate specialist agent tool with the full event details above."
        )
        return "\n".join(lines)
