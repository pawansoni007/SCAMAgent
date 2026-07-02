"""
Request Handler — runtime step 3 (validate payload + tenant).

In production this is the Azure Functions HTTP entry point sitting behind
the Enterprise Gateway Layer (Front Door/WAF + APIM + Entra ID).
Here it is a plain function performing payload and tenant validation
before anything reaches the orchestrator.
"""

import uuid

from models.scm_event import OrchestratorRequest, ScmEvent
from services.tenant_config_service import TenantConfigService
from services.agent_registry import AgentRegistry

ORCHESTRATOR_AGENT_ID = "scm-orchestrator-agent"


class RequestValidationError(Exception):
    """Raised when an incoming payload fails validation."""


def validate_request(
    payload: dict,
    tenant_config_service: TenantConfigService,
    agent_registry: AgentRegistry,
) -> OrchestratorRequest:
    """
    Validate an incoming SCM event payload and resolve the tenant.

    Steps:
      1. Parse and validate the payload against the ScmEvent schema (Pydantic).
      2. Verify the tenant is registered in tenant configuration.
      3. Verify the orchestrator agent is active and available to the tenant.
      4. Assign a request_id if not provided.

    Args:
        payload: Raw request payload (e.g. JSON body of an HTTP request).
        tenant_config_service: Tenant configuration lookup.
        agent_registry: Agent Registry for availability checks.

    Returns:
        A validated OrchestratorRequest ready for the orchestrator.

    Raises:
        RequestValidationError: If the payload, tenant, or agent status is invalid.
    """
    try:
        event = ScmEvent.model_validate(payload.get("event", payload))
    except Exception as exc:
        raise RequestValidationError(f"Invalid SCM event payload: {exc}") from exc

    if tenant_config_service.get(event.tenant_id) is None:
        raise RequestValidationError(
            f"Tenant '{event.tenant_id}' is not registered. "
            "Onboard the tenant in tenant configuration before sending events."
        )

    if not agent_registry.is_available(ORCHESTRATOR_AGENT_ID, event.tenant_id):
        raise RequestValidationError(
            f"Orchestrator agent is not active or not available to tenant '{event.tenant_id}'."
        )

    return OrchestratorRequest(
        event=event,
        request_id=payload.get("request_id") or f"REQ-{uuid.uuid4().hex[:12].upper()}",
        requires_human_approval=True,
    )
