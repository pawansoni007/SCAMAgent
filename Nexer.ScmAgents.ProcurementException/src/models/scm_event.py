from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ScmEventType(str, Enum):
    """
    Procurement event types handled by the platform (Buyer persona,
    D365 Procurement & Sourcing domain).

    Inventory events (stockout risk, shortages), demand-planning events
    (demand spikes) and other domains belong to their own specialist
    agents and are intentionally NOT part of the Procurement Agent scope.
    """
    OVERDUE_PURCHASE_ORDER = "overdue_purchase_order"
    SUPPLIER_DELAY = "supplier_delay"
    BLOCKED_PURCHASE_ORDER = "blocked_purchase_order"
    LEAD_TIME_DEVIATION = "lead_time_deviation"
    SUPPLIER_RISK_ALERT = "supplier_risk_alert"
    PROCUREMENT_EXCEPTION = "procurement_exception"


class RiskLevel(str, Enum):
    """Risk level of a recommendation."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecommendationAction(str, Enum):
    """Possible actions the agent can recommend."""
    EXPEDITE_ORDER = "expedite_order"
    SWITCH_SUPPLIER = "switch_supplier"
    RAISE_PURCHASE_ORDER = "raise_purchase_order"
    ESCALATE_TO_MANAGER = "escalate_to_manager"
    HOLD_AND_MONITOR = "hold_and_monitor"
    REQUEST_DATA_VALIDATION = "request_data_validation"


class ScmEvent(BaseModel):
    """
    Represents a raw SCM business event that enters the platform.
    The orchestrator uses this to decide which specialist agent to invoke.
    """
    event_type: ScmEventType = Field(
        ...,
        description="Type of SCM event that triggered the agent",
    )
    tenant_id: str = Field(
        ...,
        description="Client tenant identifier for multi-tenant routing",
    )
    item_id: str = Field(
        ...,
        description="Affected item or material ID",
    )
    plant: Optional[str] = Field(
        default=None,
        description="Plant or location where the exception occurred",
    )
    supplier_id: Optional[str] = Field(
        default=None,
        description="Primary supplier ID associated with the event",
    )
    purchase_order_id: Optional[str] = Field(
        default=None,
        description="Purchase order ID if the event relates to an existing PO",
    )
    severity: RiskLevel = Field(
        default=RiskLevel.MEDIUM,
        description="Severity of the event as assessed by the source system",
    )
    context: Optional[dict] = Field(
        default=None,
        description="Additional key-value context from the source system",
    )


class OrchestratorRequest(BaseModel):
    """
    The request payload accepted by the Orchestration Agent.
    Wraps the SCM event with routing metadata.
    """
    event: ScmEvent = Field(
        ...,
        description="The SCM event to be processed",
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Unique request identifier for tracing and audit",
    )
    requires_human_approval: bool = Field(
        default=True,
        description="Whether the result must go through human approval before ERP action",
    )


class ProcurementRecommendation(BaseModel):
    """
    A single ranked recommendation produced by the Procurement Exception Agent.
    """
    rank: int = Field(
        ...,
        ge=1,
        le=3,
        description="Recommendation rank (1 = best option)",
    )
    action: RecommendationAction = Field(
        ...,
        description="Recommended action to resolve the exception",
    )
    supplier_id: Optional[str] = Field(
        default=None,
        description="Supplier ID this recommendation applies to, if relevant",
    )
    reason: str = Field(
        ...,
        description="Plain-language explanation of why this action is recommended",
    )
    risk_level: RiskLevel = Field(
        ...,
        description="Risk level associated with this recommendation",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Agent confidence score for this recommendation (0.0 - 1.0)",
    )
    policy_constraints_applied: list[str] = Field(
        default_factory=list,
        description="List of procurement policy rules that were applied",
    )
    expected_operational_impact: str = Field(
        ...,
        description="Expected impact on operations if this recommendation is followed",
    )
    requires_human_approval: bool = Field(
        default=True,
        description="Whether this specific recommendation requires human sign-off",
    )
    is_fallback: bool = Field(
        default=False,
        description="True if this is a fallback recommendation due to limited data",
    )


class Top3Response(BaseModel):
    """
    Structured Top 3 recommendations returned by the Procurement Exception Agent.
    This is the final output that goes to the human approver.
    """
    request_id: Optional[str] = Field(
        default=None,
        description="Echo of the originating request ID for traceability",
    )
    tenant_id: str = Field(
        ...,
        description="Tenant that originated this request",
    )
    item_id: str = Field(
        ...,
        description="Item ID for which recommendations were generated",
    )
    event_type: ScmEventType = Field(
        ...,
        description="The SCM event type that triggered analysis",
    )
    recommendations: list[ProcurementRecommendation] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="Ranked list of up to 3 recommendations",
    )
    overall_risk: RiskLevel = Field(
        ...,
        description="Overall risk assessment for the situation",
    )
    summary: str = Field(
        ...,
        description="Agent summary of the situation and analysis",
    )
    human_approval_required: bool = Field(
        default=True,
        description="Whether any of the recommendations requires human approval",
    )
    agent_id: str = Field(
        default="scm-procurement-exception-agent",
        description="ID of the agent that produced this response",
    )
    agent_version: str = Field(
        default="1.0.0",
        description="Version of the agent that produced this response",
    )
