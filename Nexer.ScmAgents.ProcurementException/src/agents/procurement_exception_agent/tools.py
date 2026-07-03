"""
Procurement Exception Agent — Tool/API Contract.

Implements all tools defined in the blueprint's Tool/API Contract (Section 6).

Permission levels:
  Allowed    — agent may call freely during reasoning
  Restricted — only callable after human approval has been confirmed
  Required   — must be called on every agent run (audit trail)
  Not Allowed — executePurchaseOrder, approvePurchaseOrder, createSupplier,
                changeSupplierMasterData are NOT registered as tools.
"""

import functools
import inspect
import json
import uuid

from agent_framework import FunctionTool, tool

from agents.procurement_exception_agent.services.inventory import (
    get_inventory,
    get_safety_stock,
    list_inventory,
)
from agents.procurement_exception_agent.services.supplier import (
    get_approved_suppliers,
    get_approved_suppliers_for_item,
    get_supplier_performance,
)
from agents.procurement_exception_agent.services.forecast import get_demand_forecast
from agents.procurement_exception_agent.services.procurement import (
    get_lead_time_data,
    get_supplier_prices,
    get_open_purchase_orders,
    get_overdue_purchase_orders,
)
from agents.procurement_exception_agent.services.risk import assess_overdue_po_coverage_risk
from agents.procurement_exception_agent.services.policy import get_procurement_policies
from agents.procurement_exception_agent.services.audit import write_audit_log
from agents.procurement_exception_agent.models import AuditLogEntry
from services.debug_trace import record_debug_call


def _tool_arguments(func, args, kwargs) -> dict:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return {**{f"arg_{idx}": value for idx, value in enumerate(args)}, **kwargs}


def _tracked_tool(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        record_debug_call(
            "tool",
            func.__name__,
            arguments=_tool_arguments(func, args, kwargs),
        )
        return func(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Allowed Tools
# ---------------------------------------------------------------------------

def getInventoryStatus(item_id: str) -> str:
    """Retrieve current inventory levels and stock position for ONE specific item.

    Use when the question names a single item (current stock, availability,
    below safety stock?). Do NOT use for portfolio-wide questions where no
    item ID is given, and do NOT use for configured safety-stock/reorder
    parameters (that is getSafetyStock).

    Args:
        item_id: The item or material identifier.

    Returns:
        JSON with available_qty, safety_stock, is_below_safety_stock, stock_gap.
    """
    inventory = get_inventory(item_id)
    if inventory is None:
        return json.dumps({"error": f"Item '{item_id}' not found in inventory system."})
    return json.dumps({
        "item_id": inventory.item_id,
        "available_qty": inventory.available_qty,
        "safety_stock": inventory.safety_stock,
        "is_below_safety_stock": inventory.is_below_safety_stock,
        "stock_gap": inventory.stock_gap,
    })


def listInventoryStatus() -> str:
    """Retrieve the stock position of ALL items at once.

    Use this to find items below safety stock or to give an inventory overview
    when no specific item ID was provided. Do NOT use when the buyer names a
    specific item — use getInventoryStatus(item_id) for that.

    Returns:
        JSON list of all items with available_qty, safety_stock,
        is_below_safety_stock, stock_gap.
    """
    return json.dumps({
        "items": [
            {
                "item_id": inv.item_id,
                "available_qty": inv.available_qty,
                "safety_stock": inv.safety_stock,
                "is_below_safety_stock": inv.is_below_safety_stock,
                "stock_gap": inv.stock_gap,
            }
            for inv in list_inventory()
        ]
    })


def getSafetyStock(item_id: str) -> str:
    """Retrieve safety stock thresholds and reorder parameters for an item.

    Use for CONFIGURED planning parameters (safety stock threshold, reorder
    point, max stock). Do NOT use for the current stock level or whether the
    item is below safety stock right now — that is getInventoryStatus.

    Args:
        item_id: The item or material identifier.

    Returns:
        JSON with safety_stock_qty, reorder_point, max_stock_qty, unit_of_measure.
    """
    ss = get_safety_stock(item_id)
    if ss is None:
        return json.dumps({"error": f"Safety stock data not found for item '{item_id}'."})
    return json.dumps({
        "item_id": ss.item_id,
        "safety_stock_qty": ss.safety_stock_qty,
        "reorder_point": ss.reorder_point,
        "max_stock_qty": ss.max_stock_qty,
        "unit_of_measure": ss.unit_of_measure,
    })


def getDemandForecast(item_id: str) -> str:
    """Retrieve demand forecast for an item over 7-day and 30-day horizons.

    Args:
        item_id: The item or material identifier.

    Returns:
        JSON with forecast_qty_7d, forecast_qty_30d, confidence, trend, source.
    """
    forecast = get_demand_forecast(item_id)
    if forecast is None:
        return json.dumps({"error": f"Demand forecast not found for item '{item_id}'."})
    return json.dumps({
        "item_id": forecast.item_id,
        "forecast_qty_7d": forecast.forecast_qty_7d,
        "forecast_qty_30d": forecast.forecast_qty_30d,
        "forecast_confidence": forecast.forecast_confidence,
        "trend": forecast.trend,
        "source": forecast.source,
    })


def getApprovedSuppliers() -> str:
    """Retrieve the GLOBAL approved vendor list (all suppliers, all items).

    Use ONLY when no specific item is in scope (e.g. "show me the approved
    vendor list"). When the question concerns suppliers for a specific item,
    use getApprovedSuppliersForItem(item_id) instead; when it concerns one
    known supplier's performance, use getSupplierPerformance(supplier_id).

    Returns:
        JSON list of all approved suppliers with reliability, risk, and lead time.
    """
    suppliers = get_approved_suppliers()
    return json.dumps({
        "approved_suppliers": [
            {
                "supplier_id": s.supplier_id,
                "name": s.name,
                "reliability": s.reliability,
                "risk": s.risk,
                "lead_time_days": s.lead_time_days,
            }
            for s in suppliers
        ]
    })


def getApprovedSuppliersForItem(item_id: str) -> str:
    """Retrieve the vendors approved to supply a SPECIFIC item.

    Use this for item-level supplier comparison (e.g. "compare suppliers for
    <item>"). This returns ONLY the vendors on that item's approved vendor list
    in the ERP — unlike getApprovedSuppliers, which returns the global vendor
    list and is NOT item-specific.

    If no vendor is approved for the item, approved_supplier_count is 0 and the
    list is empty: this means no vendor is explicitly approved to supply this
    item — do NOT substitute the global approved vendor list in that case.

    Args:
        item_id: The item or material identifier.

    Returns:
        JSON with item_id, approved_supplier_count, and approved_suppliers
        (supplier_id, name, reliability, risk, lead_time_days, is_approved).
    """
    suppliers = get_approved_suppliers_for_item(item_id)
    return json.dumps({
        "item_id": item_id,
        "approved_supplier_count": len(suppliers),
        "approved_suppliers": [
            {
                "supplier_id": s.supplier_id,
                "name": s.name,
                "reliability": s.reliability,
                "risk": s.risk,
                "lead_time_days": s.lead_time_days,
                "is_approved": s.is_approved,
            }
            for s in suppliers
        ],
    })


def getSupplierPerformance(supplier_id: str) -> str:
    """Retrieve reliability score, risk rating, and approval status for ONE supplier.

    Use when the buyer asks about a specific, named supplier ("how reliable is
    SUP-200?"). Do NOT use to find or compare suppliers for an item (use
    getApprovedSuppliersForItem), and do NOT use for supplier-item delivery
    lead times (use getLeadTimeData).

    Args:
        supplier_id: The supplier identifier.

    Returns:
        JSON with supplier_id, name, reliability, risk, lead_time_days, is_approved.
    """
    supplier = get_supplier_performance(supplier_id)
    if supplier is None:
        return json.dumps({"error": f"Supplier '{supplier_id}' not found."})
    return json.dumps({
        "supplier_id": supplier.supplier_id,
        "name": supplier.name,
        "reliability": supplier.reliability,
        "risk": supplier.risk,
        "lead_time_days": supplier.lead_time_days,
        "is_approved": supplier.is_approved,
    })


def getLeadTimeData(supplier_id: str, item_id: str) -> str:
    """Retrieve delivery lead time data for a supplier-item combination.

    This is the authoritative source for lead-time questions when both a
    supplier and an item are known (standard vs expedited, last actual,
    on-time rate). Prefer it over the coarse per-supplier lead_time_days
    summary returned by supplier-list tools.

    Args:
        supplier_id: The supplier identifier.
        item_id: The item or material identifier.

    Returns:
        JSON with standard_lead_time_days, expedited_lead_time_days,
        last_actual_lead_time_days, on_time_delivery_rate.
    """
    lead_time = get_lead_time_data(supplier_id, item_id)
    if lead_time is None:
        return json.dumps({
            "error": f"Lead time data not found for supplier '{supplier_id}' / item '{item_id}'."
        })
    return json.dumps({
        "supplier_id": lead_time.supplier_id,
        "item_id": lead_time.item_id,
        "standard_lead_time_days": lead_time.standard_lead_time_days,
        "expedited_lead_time_days": lead_time.expedited_lead_time_days,
        "last_actual_lead_time_days": lead_time.last_actual_lead_time_days,
        "on_time_delivery_rate": lead_time.on_time_delivery_rate,
    })


def getSupplierPrices(supplier_id: str, item_id: str) -> str:
    """Retrieve current pricing for a supplier-item combination.

    Args:
        supplier_id: The supplier identifier.
        item_id: The item or material identifier.

    Returns:
        JSON with unit_price, currency, minimum_order_qty,
        price_valid_until, discount_rate.
    """
    price = get_supplier_prices(supplier_id, item_id)
    if price is None:
        return json.dumps({
            "error": f"Pricing not found for supplier '{supplier_id}' / item '{item_id}'."
        })
    return json.dumps({
        "supplier_id": price.supplier_id,
        "item_id": price.item_id,
        "unit_price": price.unit_price,
        "currency": price.currency,
        "minimum_order_qty": price.minimum_order_qty,
        "price_valid_until": price.price_valid_until,
        "discount_rate": price.discount_rate,
    })


def getOpenPurchaseOrders(item_id: str) -> str:
    """Retrieve all open or in-progress purchase orders for an item.

    Use for questions about pending/incoming orders regardless of lateness
    ("are there open POs for X?", "what is already on order?"). Do NOT use
    when the buyer asks specifically about OVERDUE orders (use
    getOverduePurchaseOrders) or which orders are most critical (use
    getOverduePOCoverageRisk).

    Args:
        item_id: The item or material identifier.

    Returns:
        JSON list of purchase orders with status, quantities, and block information.
    """
    orders = get_open_purchase_orders(item_id)
    return json.dumps({
        "purchase_orders": [
            {
                "po_id": po.po_id,
                "line_num": po.line_num,
                "supplier_id": po.supplier_id,
                "invent_dim_id": po.invent_dim_id,
                "site_id": po.site_id,
                "warehouse_id": po.warehouse_id,
                "qty_ordered": po.qty_ordered,
                "qty_outstanding": po.qty_outstanding,
                "remaining_purchase_quantity": po.remaining_purchase_quantity,
                "status": po.status,
                "expected_delivery_date": po.expected_delivery_date,
                "requested_receipt_date": po.requested_receipt_date,
                "confirmed_receipt_date": po.confirmed_receipt_date,
                "product_receipt_date": po.product_receipt_date,
                "days_late": po.days_late,
                "net_amount": po.net_amount,
                "is_blocked": po.is_blocked,
                "block_reason": po.block_reason,
            }
            for po in orders
        ]
    })


def getOverduePurchaseOrders(item_id: str | None = None,
                             page: int = 1,
                             page_size: int = 25,) -> str:
    """Retrieve calculated-overdue purchase orders (a plain listing).

    Use when the buyer asks WHICH purchase orders are overdue — with or
    without an item filter. Do NOT use when the buyer asks which overdue POs
    are most critical, what to act on first, or about inventory coverage /
    runout impact — that ranking comes from getOverduePOCoverageRisk.

    Overdue is calculated from receipt facts, not from the source ERP status:

        qty_outstanding > 0
        AND no product_receipt_date
        AND expected_delivery_date < current_date.

    Supports server-side pagination so the agent can retrieve large result sets
    page by page instead of requesting every purchase order at once.

    Args:
        item_id:
            Optional item filter. Omit to retrieve overdue purchase orders
            across all items.

        page:
            1-based page number to retrieve.
            Default is 1.

        page_size:
            Number of purchase orders returned per page.
            Default is 25.

    Returns:
        JSON containing:

        - total_count
        - returned_count
        - page
        - page_size
        - has_more
        - purchase_orders

    The agent should use has_more together with page/page_size to retrieve
    additional pages when the buyer asks for "next", "continue",
    "show more", or "remaining purchase orders".
    """
    orders = get_overdue_purchase_orders(item_id)

    total = len(orders)

    start = (page - 1) * page_size
    end = start + page_size

    page_orders = orders[start:end]

    return json.dumps({
        "total_count": total,
        "returned_count": len(page_orders),
        "page": page,
        "page_size": page_size,
        "has_more": end < total,
        "purchase_orders": [
            {
                "po_id": po.po_id,
                "line_num": po.line_num,
                "item_id": po.item_id,
                "supplier_id": po.supplier_id,
                "invent_dim_id": po.invent_dim_id,
                "site_id": po.site_id,
                "warehouse_id": po.warehouse_id,
                "qty_ordered": po.qty_ordered,
                "qty_outstanding": po.qty_outstanding,
                "remaining_purchase_quantity": po.remaining_purchase_quantity,
                "status": po.status,
                "expected_delivery_date": po.expected_delivery_date,
                "requested_receipt_date": po.requested_receipt_date,
                "confirmed_receipt_date": po.confirmed_receipt_date,
                "product_receipt_date": po.product_receipt_date,
                "days_late": po.days_late,
                "net_amount": po.net_amount,
                "is_blocked": po.is_blocked,
                "block_reason": po.block_reason,
            }
            for po in page_orders
        ]
    })


def getOverduePOCoverageRisk(item_id: str, tenant_id: str = "nexer-demo") -> str:
    """Rank overdue purchase orders by deterministic inventory coverage risk.

    Use for PROC-01 / overdue PO prioritization questions: which overdue POs
    are most critical, what to act on first, expedite-vs-wait decisions, and
    how late deliveries affect inventory coverage or projected runout for an
    item. Do NOT use for a plain "which POs are overdue" listing (that is
    getOverduePurchaseOrders). This tool composes
    approved services only: open purchase orders, product receipt facts,
    inventory status and demand data. It calculates receipt status, days late,
    open demand, days of cover, projected runout date, risk level, risk_score
    and up to three ranked recommendations without using an LLM.

    Args:
        item_id: The item or material identifier.
        tenant_id: Tenant identifier used for traceability.

    Returns:
        JSON with execution_id, risk_assessments, recommendations, data_gaps and
        fallback status.
    """
    response = assess_overdue_po_coverage_risk(item_id=item_id, tenant_id=tenant_id)
    return json.dumps(response.model_dump(mode="json"))


def getProcurementPolicies(event_type: str) -> str:
    """Retrieve procurement policies applicable to the current event type.

    Calls Azure AI Search (RAG) to retrieve relevant policy documents.

    Args:
        event_type: The procurement event type (e.g. 'overdue_purchase_order', 'supplier_delay').

    Returns:
        JSON list of applicable policies with IDs, titles, descriptions,
        and mandatory flags.
    """
    policies = get_procurement_policies(event_type)
    return json.dumps({
        "policies": [
            {
                "policy_id": p.policy_id,
                "title": p.title,
                "description": p.description,
                "is_mandatory": p.is_mandatory,
            }
            for p in policies
        ]
    })


# ---------------------------------------------------------------------------
# Restricted Tool — only after human approval
# ---------------------------------------------------------------------------

def createPurchaseOrderDraft(
    item_id: str,
    supplier_id: str,
    qty: int,
    plant: str,
    justification: str,
) -> str:
    """Create a purchase order draft in the ERP system.

    RESTRICTED: This tool may only be called after explicit human approval
    has been confirmed for the corresponding recommendation. It creates a
    draft PO only — it does NOT execute or submit the order.

    Args:
        item_id: The item or material to order.
        supplier_id: The approved supplier to raise the PO against.
        qty: Quantity to order.
        plant: Receiving plant or location.
        justification: Human-approved justification for this PO.

    Returns:
        JSON with draft_po_id and confirmation that the draft was created.
    """
    draft_po_id = f"DRAFT-{uuid.uuid4().hex[:8].upper()}"
    return json.dumps({
        "status": "draft_created",
        "draft_po_id": draft_po_id,
        "item_id": item_id,
        "supplier_id": supplier_id,
        "qty": qty,
        "plant": plant,
        "justification": justification,
        "note": "Draft PO created. Requires buyer approval before submission to ERP.",
    })


# ---------------------------------------------------------------------------
# Required Tool — must be called after every agent run
# ---------------------------------------------------------------------------

def writeAuditLog(
    execution_id: str,
    tenant_id: str,
    agent_id: str,
    agent_version: str,
    item_id: str,
    event_type: str,
    tools_called: str,
    rules_applied: str,
    recommendations_generated: int,
) -> str:
    """Store the agent's reasoning and decision trace in the audit log.

    REQUIRED: This tool must be called at the end of every agent run to
    maintain a complete audit trail as per the blueprint's governance requirements.

    Args:
        execution_id: Unique trace identifier for this run.
        tenant_id: Tenant that originated the request.
        agent_id: ID of the agent producing this entry.
        agent_version: Version of the agent.
        item_id: Item ID that was analyzed.
        event_type: SCM event type that triggered the run.
        tools_called: JSON array string of tool names that were invoked.
        rules_applied: JSON array string of business rules that were applied.
        recommendations_generated: Number of recommendations produced.

    Returns:
        Confirmation string with execution_id that was logged.
    """
    try:
        tools_list = json.loads(tools_called) if tools_called else []
        rules_list = json.loads(rules_applied) if rules_applied else []
    except json.JSONDecodeError:
        tools_list = [tools_called]
        rules_list = [rules_applied]

    entry = AuditLogEntry(
        execution_id=execution_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_version=agent_version,
        item_id=item_id,
        event_type=event_type,
        tools_called=tools_list,
        rules_applied=rules_list,
        recommendations_generated=recommendations_generated,
        human_approval_required=True,
    )
    return write_audit_log(entry)


# ---------------------------------------------------------------------------
# Tool registry — passed to Agent(tools=PROCUREMENT_TOOLS)
# ---------------------------------------------------------------------------

PROCUREMENT_TOOLS: list[FunctionTool] = [
    # Allowed tools
    tool(_tracked_tool(getInventoryStatus)),
    tool(_tracked_tool(getSafetyStock)),
    tool(_tracked_tool(getDemandForecast)),
    tool(_tracked_tool(getApprovedSuppliers)),
    tool(_tracked_tool(getApprovedSuppliersForItem)),
    tool(_tracked_tool(getSupplierPerformance)),
    tool(_tracked_tool(getLeadTimeData)),
    tool(_tracked_tool(getSupplierPrices)),
    tool(_tracked_tool(getOpenPurchaseOrders)),
    tool(_tracked_tool(getOverduePurchaseOrders)),
    tool(_tracked_tool(getOverduePOCoverageRisk)),
    tool(_tracked_tool(getProcurementPolicies)),
    # Restricted tool — requires human approval before use
    tool(_tracked_tool(createPurchaseOrderDraft), approval_mode="always_require"),
    # Required tool — audit trail for every run
    tool(_tracked_tool(writeAuditLog)),
]

# Buyer chat variant: same Tool/API Contract, but human approval for
# createPurchaseOrderDraft happens conversationally — the buyer confirms
# in the chat before the agent may call it (enforced via prompt rules),
# instead of the framework-level approval gate used in the event pipeline.
BUYER_CHAT_TOOLS: list[FunctionTool] = [
    tool(_tracked_tool(getInventoryStatus)),
    tool(_tracked_tool(listInventoryStatus)),
    tool(_tracked_tool(getSafetyStock)),
    tool(_tracked_tool(getDemandForecast)),
    tool(_tracked_tool(getApprovedSuppliers)),
    tool(_tracked_tool(getApprovedSuppliersForItem)),
    tool(_tracked_tool(getSupplierPerformance)),
    tool(_tracked_tool(getLeadTimeData)),
    tool(_tracked_tool(getSupplierPrices)),
    tool(_tracked_tool(getOpenPurchaseOrders)),
    tool(_tracked_tool(getOverduePurchaseOrders)),
    tool(_tracked_tool(getOverduePOCoverageRisk)),
    tool(_tracked_tool(getProcurementPolicies)),
    tool(_tracked_tool(createPurchaseOrderDraft)),
    tool(_tracked_tool(writeAuditLog)),
]
