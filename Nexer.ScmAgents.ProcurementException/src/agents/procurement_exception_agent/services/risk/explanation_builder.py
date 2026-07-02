"""Reusable explanation builders for deterministic procurement risk output."""

from models.scm_event import RiskLevel


def build_risk_reason(
    *,
    available_inventory: int,
    open_demand_qty: float,
    days_of_cover: int | None,
    projected_runout_date: str | None,
    receipt_variance_days: int | None,
    receipt_status: str,
    risk_level: RiskLevel,
) -> str:
    """Create a concise business explanation for a PROC-01 risk label."""
    if days_of_cover is None:
        return (
            f"Open demand ({open_demand_qty:.0f}) does not consume available "
            f"inventory ({available_inventory}) in the dated demand set, so no "
            "runout date was calculated."
        )

    variance = (
        "unknown"
        if receipt_variance_days is None
        else str(receipt_variance_days)
    )
    runout = projected_runout_date or "unknown"
    if risk_level == RiskLevel.CRITICAL:
        return (
            f"Available inventory ({available_inventory}) is consumed by dated open "
            f"demand ({open_demand_qty:.0f}) by {runout}, leaving {days_of_cover} "
            f"days of cover. Calculated receipt status is "
            f"{receipt_status} with receipt variance of {variance} days. Inventory "
            "covers 3 days or less of demand."
        )
    if risk_level == RiskLevel.HIGH:
        return (
            f"Dated open demand consumes available inventory by {runout}, leaving "
            f"{days_of_cover} days of cover. Calculated receipt status is "
            f"{receipt_status} with receipt variance of "
            f"{variance} days, and coverage is 7 days or less."
        )
    if risk_level == RiskLevel.MEDIUM:
        return (
            f"Dated open demand consumes available inventory by {runout}, leaving "
            f"{days_of_cover} days of cover. Coverage is above one week but "
            f"within two weeks, and calculated receipt status is "
            f"{receipt_status}."
        )
    return (
        f"The dated demand set gives {days_of_cover} days of cover, which is above "
        f"the 14-day low-risk threshold. Calculated receipt status is "
        f"{receipt_status} with receipt variance of {variance} days."
    )


def build_recommendation_reason(risk_level: RiskLevel, po_id: str, item_id: str) -> str:
    """Create the action rationale used by ranked PROC-01 recommendations."""
    if risk_level == RiskLevel.CRITICAL:
        return (
            f"PO {po_id} for item {item_id} has critical coverage risk. Expedite "
            "the supplier first because it is the fastest mitigation path for an "
            "already overdue replenishment."
        )
    if risk_level == RiskLevel.HIGH:
        return (
            f"PO {po_id} for item {item_id} has high coverage risk. Expedite or "
            "confirm partial shipment before the remaining cover is consumed."
        )
    if risk_level == RiskLevel.MEDIUM:
        return (
            f"PO {po_id} for item {item_id} has medium coverage risk. Monitor the "
            "supplier commitment and prepare an alternative if the delay worsens."
        )
    return (
        f"PO {po_id} for item {item_id} is currently low risk based on available "
        "coverage. Continue monitoring rather than taking urgent action."
    )


def build_expected_impact(risk_level: RiskLevel) -> str:
    """Describe expected operational impact for the recommended action."""
    if risk_level == RiskLevel.CRITICAL:
        return "Reduces immediate stockout or production-interruption risk."
    if risk_level == RiskLevel.HIGH:
        return "Reduces near-term supply disruption risk before coverage is exhausted."
    if risk_level == RiskLevel.MEDIUM:
        return "Keeps the buyer prepared while avoiding unnecessary emergency action."
    return "Maintains visibility with no immediate operational intervention."
