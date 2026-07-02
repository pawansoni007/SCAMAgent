"""Deterministic PROC-01 overdue PO inventory coverage risk service."""

import uuid
from dataclasses import dataclass
from datetime import date

from agents.procurement_exception_agent.models import (
    DemandSummary,
    DatedDemandLine,
    ProcurementRiskResponse,
    RiskAssessment,
)
from agents.procurement_exception_agent.services.demand import get_open_demand
from agents.procurement_exception_agent.services.inventory import get_inventory
from agents.procurement_exception_agent.services.procurement import get_open_purchase_orders
from models.scm_event import RiskLevel

from .explanation_builder import build_risk_reason
from .recommendation_factory import generate_proc01_recommendations

RECEIPT_STATUS_NO_PLANNED_DATE = "No planned receipt date"
RECEIPT_STATUS_CURRENTLY_OVERDUE = "Currently Overdue"
RECEIPT_STATUS_RECEIVED_LATE = "Received Late"
RECEIPT_STATUS_NOT_YET_DUE = "Not Yet Due"
RECEIPT_STATUS_RECEIVED_ON_TIME_OR_EARLY = "Received On Time / Early"


@dataclass(frozen=True)
class ReceiptAssessment:
    receipt_status: str
    receipt_variance_days: int | None
    effective_planned_receipt_date: str | None
    comparison_date: str


def assess_overdue_po_coverage_risk(
    item_id: str,
    tenant_id: str = "nexer-demo",
) -> ProcurementRiskResponse:
    """
    Rank overdue purchase orders for an item by deterministic coverage risk.

    This service intentionally does not call LLMs. It composes existing approved
    services and applies the PROC-01 rules from docs/procurement/proc-01.md.
    """
    execution_id = f"PROC01-{uuid.uuid4().hex[:12].upper()}"
    data_gaps: list[str] = []

    current_date = date.today()
    purchase_orders = get_open_purchase_orders(item_id)
    if not purchase_orders:
        data_gaps.append(f"No purchase order lines found for item '{item_id}'.")

    risk_assessments: list[RiskAssessment] = []
    if purchase_orders:
        for po in purchase_orders:
            receipt_assessment = calculate_receipt_assessment(
                product_receipt_date=po.product_receipt_date,
                confirmed_receipt_date=po.confirmed_receipt_date,
                requested_receipt_date=po.requested_receipt_date or po.expected_delivery_date,
                current_date=current_date,
            )
            if receipt_assessment.receipt_status != RECEIPT_STATUS_CURRENTLY_OVERDUE:
                continue

            inventory = get_inventory(po.item_id, po.site_id, po.warehouse_id)
            if inventory is None:
                data_gaps.append(
                    "Inventory data is missing for "
                    f"item '{po.item_id}'"
                    + (f", site '{po.site_id}'" if po.site_id else "")
                    + (f", warehouse '{po.warehouse_id}'" if po.warehouse_id else "")
                    + "."
                )
                continue

            demand = _get_demand_summary(
                item_id=po.item_id,
                site_id=po.site_id,
                warehouse_id=po.warehouse_id,
            )
            if demand is None:
                data_gaps.append(
                    "Open dated demand is missing for "
                    f"item '{po.item_id}'"
                    + (f", site '{po.site_id}'" if po.site_id else "")
                    + (f", warehouse '{po.warehouse_id}'" if po.warehouse_id else "")
                    + "."
                )
                continue

            days_late = max(receipt_assessment.receipt_variance_days or 0, 0)
            projected_runout_date = calculate_projected_runout_date(
                current_date,
                inventory.available_qty,
                demand.demand_lines,
            )
            days_of_cover = calculate_days_of_cover(current_date, projected_runout_date)
            risk_level = classify_coverage_risk(days_of_cover, days_late)
            risk_assessments.append(
                RiskAssessment(
                    purchase_order_number=po.po_id,
                    line_num=po.line_num,
                    item_number=po.item_id,
                    invent_dim_id=po.invent_dim_id,
                    site_id=po.site_id,
                    warehouse_id=po.warehouse_id,
                    supplier_id=po.supplier_id,
                    status=receipt_assessment.receipt_status,
                    available_inventory=inventory.available_qty,
                    open_demand_qty=demand.open_demand_qty,
                    demand_lines=demand.demand_lines,
                    daily_demand=demand.daily_demand,
                    days_of_cover=days_of_cover,
                    projected_runout_date=projected_runout_date,
                    days_late=days_late,
                    supplier_delay_days=days_late,
                    receipt_status=receipt_assessment.receipt_status,
                    receipt_variance_days=receipt_assessment.receipt_variance_days,
                    effective_planned_receipt_date=(
                        receipt_assessment.effective_planned_receipt_date
                    ),
                    comparison_date=receipt_assessment.comparison_date,
                    risk_level=risk_level,
                    risk_score=calculate_risk_score(
                        risk_level,
                        days_of_cover,
                        days_late,
                    ),
                    reason=build_risk_reason(
                        available_inventory=inventory.available_qty,
                        open_demand_qty=demand.open_demand_qty or 0,
                        days_of_cover=days_of_cover,
                        projected_runout_date=projected_runout_date,
                        receipt_variance_days=receipt_assessment.receipt_variance_days,
                        receipt_status=receipt_assessment.receipt_status,
                        risk_level=risk_level,
                    ),
                )
            )

    if purchase_orders and not risk_assessments:
        data_gaps.append(
            f"No purchase order lines are calculated as '{RECEIPT_STATUS_CURRENTLY_OVERDUE}' "
            f"for item '{item_id}'."
        )

    risk_assessments.sort(
        key=lambda r: (
            -r.risk_score,
            r.days_of_cover if r.days_of_cover is not None else 999999,
            -r.days_late,
            r.purchase_order_number,
        )
    )

    recommendations = generate_proc01_recommendations(risk_assessments, data_gaps)

    top_assessment = risk_assessments[0] if risk_assessments else None
    return ProcurementRiskResponse(
        execution_id=execution_id,
        tenant_id=tenant_id,
        item_id=item_id,
        recommendations=recommendations,
        risk_assessments=risk_assessments,
        receipt_status=top_assessment.receipt_status if top_assessment else None,
        receipt_variance_days=top_assessment.receipt_variance_days if top_assessment else None,
        effective_planned_receipt_date=(
            top_assessment.effective_planned_receipt_date if top_assessment else None
        ),
        comparison_date=top_assessment.comparison_date if top_assessment else None,
        is_fallback=bool(data_gaps),
        data_gaps=data_gaps,
    )


def calculate_days_of_cover(
    current_date: date,
    projected_runout_date: str | None,
) -> int | None:
    """DaysOfCover = RunoutDate - Today."""
    if projected_runout_date is None:
        return None
    runout = _parse_date(projected_runout_date)
    if runout is None:
        return None
    return (runout - current_date).days


def calculate_projected_runout_date(
    current_date: date,
    available_inventory: int,
    demand_lines: list[DatedDemandLine],
) -> str | None:
    """Return the first demand date where cumulative open demand exceeds stock."""
    cumulative_qty = 0.0
    for demand in sorted(demand_lines, key=lambda line: line.demand_date):
        demand_date = _parse_date(demand.demand_date)
        if demand_date is None:
            continue
        cumulative_qty += demand.demand_qty
        if cumulative_qty > available_inventory:
            return demand_date.isoformat()
    return None


def calculate_receipt_assessment(
    *,
    product_receipt_date: str | None,
    confirmed_receipt_date: str | None,
    requested_receipt_date: str | None,
    current_date: date | None = None,
) -> ReceiptAssessment:
    """
    Apply PROC-01 receipt status formulas without using ERP status values.

    ComparisonDate = ProductReceiptDate if present else CurrentDate.
    EffectivePlannedReceiptDate = ConfirmedReceiptDate if present else RequestedReceiptDate.
    ReceiptVarianceDays = ComparisonDate - EffectivePlannedReceiptDate.
    """
    comparison = _parse_date(product_receipt_date) or (current_date or date.today())
    effective_planned = _parse_date(confirmed_receipt_date) or _parse_date(requested_receipt_date)

    if effective_planned is None:
        return ReceiptAssessment(
            receipt_status=RECEIPT_STATUS_NO_PLANNED_DATE,
            receipt_variance_days=None,
            effective_planned_receipt_date=None,
            comparison_date=comparison.isoformat(),
        )

    variance_days = (comparison - effective_planned).days
    if variance_days > 0:
        receipt_status = (
            RECEIPT_STATUS_CURRENTLY_OVERDUE
            if not product_receipt_date
            else RECEIPT_STATUS_RECEIVED_LATE
        )
    else:
        receipt_status = (
            RECEIPT_STATUS_NOT_YET_DUE
            if not product_receipt_date
            else RECEIPT_STATUS_RECEIVED_ON_TIME_OR_EARLY
        )

    return ReceiptAssessment(
        receipt_status=receipt_status,
        receipt_variance_days=variance_days,
        effective_planned_receipt_date=effective_planned.isoformat(),
        comparison_date=comparison.isoformat(),
    )


def calculate_days_late(expected_delivery_date: str | None) -> int:
    """days_late = (current_date - ExpectedDeliveryDate).days when overdue."""
    if not expected_delivery_date:
        return 0
    due = date.fromisoformat(expected_delivery_date[:10])
    return max((date.today() - due).days, 0)


def classify_coverage_risk(
    days_of_cover: float | None,
    days_late: int,
) -> RiskLevel:
    """Apply PROC-01 deterministic risk classification."""
    if days_of_cover is None:
        return RiskLevel.LOW
    if days_of_cover <= 3:
        return RiskLevel.CRITICAL
    if 3 < days_of_cover <= 7:
        return RiskLevel.HIGH
    if 7 < days_of_cover <= 14:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def calculate_risk_score(
    risk_level: RiskLevel,
    days_of_cover: float | None,
    days_late: int,
) -> float:
    """
    Deterministic score for sorting risks.

    Risk level dominates. Delay and low coverage refine ordering within the same
    level. The score is only for ranking and is not an ML confidence score.
    """
    base = {
        RiskLevel.CRITICAL: 400.0,
        RiskLevel.HIGH: 300.0,
        RiskLevel.MEDIUM: 200.0,
        RiskLevel.LOW: 100.0,
    }[risk_level]
    coverage_pressure = 50.0 if days_of_cover is None else max(0.0, 30.0 - days_of_cover)
    delay_pressure = min(float(days_late), 60.0)
    return round(base + coverage_pressure + delay_pressure, 2)


def _get_demand_summary(
    item_id: str,
    site_id: str | None,
    warehouse_id: str | None,
) -> DemandSummary | None:
    """Use dated sales, production and transfer demand for PROC-01 runout."""
    demand_lines = get_open_demand(item_id, site_id, warehouse_id)
    if not demand_lines:
        return None
    open_demand_qty = round(sum(line.demand_qty for line in demand_lines), 2)
    return DemandSummary(
        item_id=item_id,
        daily_demand=None,
        demand_source="sales+production+transfer dated open demand",
        open_demand_qty=open_demand_qty,
        demand_lines=demand_lines,
    )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])
