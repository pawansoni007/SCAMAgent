"""
Reference data for the Event Simulation UI.

Builds dropdown options from live D365 data when configured. The simulation
supports a single event type: overdue_purchase_order (PROC-01).
"""

from __future__ import annotations

import logging

from models.scm_event import RiskLevel, ScmEventType

logger = logging.getLogger(__name__)

SIMULATION_EVENT_TYPE = ScmEventType.OVERDUE_PURCHASE_ORDER.value


def build_reference_data(tenant_ids: list[str]) -> dict:
    """Assemble reference-data payload for GET /api/reference-data."""
    from integrations.d365 import is_configured as is_d365_configured
    from agents.procurement_exception_agent.services.inventory import (
        get_inventory,
        list_inventory,
    )
    from agents.procurement_exception_agent.services.supplier import (
        get_approved_suppliers_for_item,
        get_supplier_performance,
    )
    from agents.procurement_exception_agent.services.procurement import (
        get_overdue_purchase_orders,
    )

    logger.info(
        "Building reference data "
        "(tenant_count=%s, d365_configured=%s, event_type=%s)",
        len(tenant_ids),
        is_d365_configured(),
        SIMULATION_EVENT_TYPE,
    )

    logger.info("Reference data step started: overdue purchase orders")
    overdue_pos = get_overdue_purchase_orders()
    logger.info(
        "Reference data step completed: overdue purchase orders "
        "(count=%s)",
        len(overdue_pos),
    )

    sample_po = overdue_pos[0] if overdue_pos else None
    item_ids = sorted({po.item_id for po in overdue_pos})
    logger.info(
        "Reference data item extraction completed "
        "(item_count=%s, item_ids=%s)",
        len(item_ids),
        item_ids,
    )

    logger.info("Reference data step started: inventory list")
    inventory_by_id = {inv.item_id: inv for inv in list_inventory()}
    logger.info(
        "Reference data step completed: inventory list "
        "(inventory_count=%s)",
        len(inventory_by_id),
    )

    items = []
    for item_id in item_ids:
        logger.info(
            "Reference data inventory lookup started (item_id=%s)",
            item_id,
        )
        inv = inventory_by_id.get(item_id) or get_inventory(item_id)
        items.append(inv.model_dump() if inv else {"item_id": item_id})
        logger.info(
            "Reference data inventory lookup completed "
            "(item_id=%s, found=%s)",
            item_id,
            bool(inv),
        )

    suppliers_by_item = {}
    purchase_orders_by_item = {}
    for item_id in item_ids:
        logger.info(
            "Reference data supplier lookup started (item_id=%s)",
            item_id,
        )
        approved = get_approved_suppliers_for_item(item_id)
        by_id = {s.supplier_id: s.model_dump() for s in approved}
        for po in [order for order in overdue_pos if order.item_id == item_id]:
            if po.supplier_id and po.supplier_id not in by_id:
                logger.info(
                    "Reference data supplier performance lookup started "
                    "(item_id=%s, supplier_id=%s)",
                    item_id,
                    po.supplier_id,
                )
                perf = get_supplier_performance(po.supplier_id)
                if perf:
                    by_id[po.supplier_id] = perf.model_dump()
                logger.info(
                    "Reference data supplier performance lookup completed "
                    "(item_id=%s, supplier_id=%s, found=%s)",
                    item_id,
                    po.supplier_id,
                    bool(perf),
                )
        suppliers_by_item[item_id] = list(by_id.values())
        purchase_orders_by_item[item_id] = [
            po.model_dump() for po in overdue_pos if po.item_id == item_id
        ]
        logger.info(
            "Reference data supplier and PO grouping completed "
            "(item_id=%s, supplier_count=%s, overdue_po_count=%s)",
            item_id,
            len(suppliers_by_item[item_id]),
            len(purchase_orders_by_item[item_id]),
        )

    event_sample = None
    if sample_po:
        logger.info(
            "Reference data event sample selected "
            "(item_id=%s, po_id=%s, supplier_id=%s)",
            sample_po.item_id,
            sample_po.po_id,
            sample_po.supplier_id,
        )
        event_sample = {
            "item_id": sample_po.item_id,
            "supplier_id": sample_po.supplier_id,
            "purchase_order_id": sample_po.po_id,
            "plant": sample_po.site_id,
            "severity": RiskLevel.HIGH.value,
            "context": {
                "triggered_by": "event_simulation",
                "use_case": "PROC-01",
                "exception_reason": "Overdue PO impact prioritization by inventory coverage risk",
            },
        }

    logger.info(
        "Reference data build completed "
        "(tenant_count=%s, item_count=%s, supplier_groups=%s, po_groups=%s, "
        "has_event_sample=%s)",
        len(tenant_ids),
        len(items),
        len(suppliers_by_item),
        len(purchase_orders_by_item),
        bool(event_sample),
    )

    return {
        "event_type": SIMULATION_EVENT_TYPE,
        "event_sample": event_sample,
        "items": items,
        "suppliers_by_item": suppliers_by_item,
        "purchase_orders_by_item": purchase_orders_by_item,
        "tenants": tenant_ids,
        "severities": [risk.value for risk in RiskLevel],
    }
