"""
Procurement Exception Agent — domain models.

All data structures returned by the agent's service integrations.
Using Pydantic BaseModel for validation and JSON serialisation.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from models.scm_event import RecommendationAction, RiskLevel


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

class InventoryStatus(BaseModel):
    item_id: str = Field(..., description="Item or material identifier")
    available_qty: int = Field(..., description="Current available quantity in stock")
    safety_stock: int = Field(..., description="Minimum stock level threshold")

    @property
    def is_below_safety_stock(self) -> bool:
        return self.available_qty < self.safety_stock

    @property
    def stock_gap(self) -> int:
        """Units below safety stock (positive = deficit, negative = surplus)."""
        return self.safety_stock - self.available_qty


class SafetyStock(BaseModel):
    item_id: str = Field(..., description="Item or material identifier")
    safety_stock_qty: int = Field(..., description="Safety stock threshold quantity")
    reorder_point: int = Field(..., description="Quantity at which a reorder should be triggered")
    max_stock_qty: int = Field(..., description="Maximum stock level before overstock warning")
    unit_of_measure: str = Field(default="EA", description="Unit of measure (EA, KG, L, etc.)")


# ---------------------------------------------------------------------------
# Demand Forecast
# ---------------------------------------------------------------------------

class DemandForecast(BaseModel):
    item_id: str = Field(..., description="Item or material identifier")
    forecast_qty_7d: int = Field(..., description="Forecasted demand over the next 7 days")
    forecast_qty_30d: int = Field(..., description="Forecasted demand over the next 30 days")
    forecast_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score for forecast (0.0–1.0)")
    trend: str = Field(..., description="Demand trend: increasing, stable, decreasing")
    source: str = Field(default="Microsoft Fabric / Forecast API", description="Forecast data source")


class DatedDemandLine(BaseModel):
    item_id: str = Field(..., description="Item or material identifier")
    demand_date: str = Field(..., description="Demand date used for runout sequencing")
    demand_qty: float = Field(..., ge=0.0, description="Open demand quantity on this date")
    demand_source: str = Field(..., description="sales_order, production, or transfer")
    reference_id: Optional[str] = Field(default=None, description="Source document or order reference")
    site_id: Optional[str] = Field(default=None, description="Demand site")
    warehouse_id: Optional[str] = Field(default=None, description="Demand warehouse")


# ---------------------------------------------------------------------------
# Supplier
# ---------------------------------------------------------------------------

class Supplier(BaseModel):
    supplier_id: str = Field(..., description="Supplier identifier")
    name: str = Field(default="", description="Supplier display name")
    reliability: float = Field(..., ge=0.0, le=1.0, description="Reliability score 0.0–1.0")
    risk: str = Field(..., description="Risk label: Low, Medium, High")
    lead_time_days: int = Field(default=7, description="Expected lead time in days")
    is_approved: bool = Field(default=True, description="Whether supplier is on the approved list")


class LeadTimeData(BaseModel):
    supplier_id: str = Field(..., description="Supplier identifier")
    item_id: str = Field(..., description="Item or material identifier")
    standard_lead_time_days: int = Field(..., description="Standard lead time in days")
    expedited_lead_time_days: Optional[int] = Field(
        default=None, description="Lead time if order is expedited (rush)"
    )
    last_actual_lead_time_days: Optional[int] = Field(
        default=None, description="Most recent actual delivery lead time"
    )
    on_time_delivery_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Historical on-time delivery rate 0.0–1.0"
    )


class SupplierPrice(BaseModel):
    supplier_id: str = Field(..., description="Supplier identifier")
    item_id: str = Field(..., description="Item or material identifier")
    unit_price: float = Field(..., description="Price per unit in base currency")
    currency: str = Field(default="GBP", description="Currency code")
    minimum_order_qty: int = Field(default=1, description="Minimum order quantity")
    price_valid_until: Optional[str] = Field(
        default=None, description="Date until which price is valid (ISO 8601)"
    )
    discount_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="Applicable discount rate")


# ---------------------------------------------------------------------------
# Purchase Orders
# ---------------------------------------------------------------------------

class PurchaseOrder(BaseModel):
    po_id: str = Field(..., description="Purchase order identifier")
    line_num: Optional[str] = Field(default=None, description="Purchase order line number")
    item_id: str = Field(..., description="Item or material covered by this PO")
    invent_dim_id: Optional[str] = Field(default=None, description="D365 inventory dimension identifier")
    site_id: Optional[str] = Field(default=None, description="Receiving site")
    warehouse_id: Optional[str] = Field(default=None, description="Receiving warehouse")
    supplier_id: str = Field(..., description="Supplier this PO is placed with")
    qty_ordered: int = Field(..., description="Quantity ordered")
    qty_outstanding: int = Field(..., description="Quantity not yet received")
    remaining_purchase_quantity: Optional[int] = Field(
        default=None, description="Remaining purchase quantity from product receipt data"
    )
    status: str = Field(..., description="PO status: open, blocked, delayed, cancelled, closed")
    expected_delivery_date: Optional[str] = Field(
        default=None, description="Expected delivery date (ISO 8601)"
    )
    requested_receipt_date: Optional[str] = Field(
        default=None, description="Buyer-requested receipt date (ISO 8601)"
    )
    confirmed_receipt_date: Optional[str] = Field(
        default=None, description="Vendor-confirmed receipt date (ISO 8601)"
    )
    product_receipt_date: Optional[str] = Field(
        default=None, description="Actual product receipt date if received (ISO 8601)"
    )
    days_late: int = Field(default=0, ge=0, description="Calculated days late")
    net_amount: float = Field(default=0.0, description="Net line amount (excl. tax)")
    is_blocked: bool = Field(default=False, description="Whether the PO is currently blocked")
    block_reason: Optional[str] = Field(default=None, description="Reason for PO block if applicable")


# ---------------------------------------------------------------------------
# PROC-01 Risk Assessment
# ---------------------------------------------------------------------------

class DemandSummary(BaseModel):
    item_id: str = Field(..., description="Item or material identifier")
    daily_demand: Optional[float] = Field(
        default=None, ge=0.0, description="Legacy daily demand value when available"
    )
    demand_source: str = Field(..., description="Demand source used for the calculation")
    open_demand_qty: Optional[float] = Field(
        default=None, ge=0.0, description="Open demand quantity used for PROC-01 coverage"
    )
    demand_lines: list[DatedDemandLine] = Field(
        default_factory=list, description="Dated demand lines used to calculate runout"
    )
    forecast_qty_7d: Optional[int] = Field(
        default=None, description="Forecast quantity over the next 7 days"
    )
    forecast_qty_30d: Optional[int] = Field(
        default=None, description="Forecast quantity over the next 30 days"
    )
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Demand source confidence"
    )


class RiskAssessment(BaseModel):
    purchase_order_number: str = Field(..., description="Purchase order identifier")
    line_num: Optional[str] = Field(default=None, description="Purchase order line number")
    item_number: str = Field(..., description="Item or material identifier")
    invent_dim_id: Optional[str] = Field(default=None, description="D365 inventory dimension identifier")
    site_id: Optional[str] = Field(default=None, description="Receiving site")
    warehouse_id: Optional[str] = Field(default=None, description="Receiving warehouse")
    supplier_id: str = Field(default="", description="Supplier account on the PO")
    status: str = Field(..., description="Calculated PO status for risk assessment")
    available_inventory: int = Field(..., description="Available inventory used for coverage")
    open_demand_qty: Optional[float] = Field(
        default=None, ge=0.0, description="Open demand quantity used for coverage"
    )
    demand_lines: list[DatedDemandLine] = Field(
        default_factory=list, description="Dated demand lines used to calculate runout"
    )
    daily_demand: Optional[float] = Field(
        default=None, ge=0.0, description="Legacy daily demand value when available"
    )
    days_of_cover: Optional[float] = Field(
        default=None, description="Runout date minus current date"
    )
    projected_runout_date: Optional[str] = Field(
        default=None, description="First dated demand line where cumulative demand exceeds stock"
    )
    days_late: int = Field(..., ge=0, description="Calculated days late from expected delivery date")
    supplier_delay_days: int = Field(
        ..., ge=0, description="Alias of days_late retained for recommendation compatibility"
    )
    receipt_status: str = Field(..., description="Calculated PROC-01 receipt status")
    receipt_variance_days: Optional[int] = Field(
        default=None, description="ComparisonDate minus EffectivePlannedReceiptDate"
    )
    effective_planned_receipt_date: Optional[str] = Field(
        default=None, description="Confirmed receipt date, otherwise requested receipt date"
    )
    comparison_date: str = Field(
        ..., description="Product receipt date if present, otherwise current date"
    )
    risk_level: RiskLevel = Field(..., description="Calculated coverage risk level")
    risk_score: float = Field(..., ge=0.0, description="Deterministic score used for ranking")
    reason: str = Field(..., description="Business explanation for the risk label")


class ProcurementRiskRecommendation(BaseModel):
    rank: int = Field(..., ge=1, le=3, description="Recommendation rank")
    action: RecommendationAction = Field(..., description="Recommended mitigation action")
    risk_level: RiskLevel = Field(..., description="Risk level driving the recommendation")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Deterministic confidence score")
    reason: str = Field(..., description="Why this option is recommended")
    expected_impact: str = Field(..., description="Expected operational impact")
    policy_constraints: list[str] = Field(default_factory=list)
    approval_required: bool = Field(default=True)
    risk_assessment: RiskAssessment = Field(..., description="Risk assessment behind the option")


class ProcurementRiskResponse(BaseModel):
    execution_id: str = Field(..., description="Unique execution identifier")
    tenant_id: str = Field(..., description="Tenant that originated the request")
    generated_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="UTC timestamp when the risk response was generated",
    )
    item_id: str = Field(..., description="Item assessed")
    recommendations: list[ProcurementRiskRecommendation] = Field(default_factory=list)
    risk_assessments: list[RiskAssessment] = Field(default_factory=list)
    receipt_status: Optional[str] = Field(
        default=None, description="Receipt status for the highest-priority assessment"
    )
    receipt_variance_days: Optional[int] = Field(
        default=None, description="Receipt variance days for the highest-priority assessment"
    )
    effective_planned_receipt_date: Optional[str] = Field(
        default=None, description="Effective planned receipt date for the highest-priority assessment"
    )
    comparison_date: Optional[str] = Field(
        default=None, description="Comparison date for the highest-priority assessment"
    )
    is_fallback: bool = Field(default=False, description="True when data gaps force escalation")
    data_gaps: list[str] = Field(default_factory=list, description="Missing data that affected analysis")


# ---------------------------------------------------------------------------
# Procurement Policies
# ---------------------------------------------------------------------------

class ProcurementPolicy(BaseModel):
    policy_id: str = Field(..., description="Unique policy identifier")
    title: str = Field(..., description="Policy title")
    description: str = Field(..., description="Full policy description")
    applies_to: list[str] = Field(
        default_factory=list,
        description="Event types or scenarios this policy applies to",
    )
    is_mandatory: bool = Field(default=True, description="Whether this policy is mandatory or advisory")
    source: str = Field(default="Azure AI Search / Policy Store", description="Policy source")


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

class AuditLogEntry(BaseModel):
    execution_id: str = Field(..., description="Unique trace identifier for this agent run")
    tenant_id: str = Field(..., description="Tenant that originated the request")
    agent_id: str = Field(..., description="Agent that produced this entry")
    agent_version: str = Field(..., description="Agent version")
    prompt_package_version: str = Field(default="1.0.0", description="Prompt package version used")
    tool_contract_version: str = Field(default="1.0.0", description="Tool/API contract version used")
    item_id: str = Field(..., description="Item ID that was analyzed")
    event_type: str = Field(..., description="SCM event type that triggered the agent")
    tools_called: list[str] = Field(
        default_factory=list,
        description="Names of all tools invoked during reasoning",
    )
    rules_applied: list[str] = Field(
        default_factory=list,
        description="Deterministic business rules evaluated",
    )
    recommendations_generated: int = Field(..., description="Number of recommendations generated")
    human_approval_required: bool = Field(default=True, description="Whether human approval is required")
    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z",
        description="UTC timestamp of the audit entry",
    )
