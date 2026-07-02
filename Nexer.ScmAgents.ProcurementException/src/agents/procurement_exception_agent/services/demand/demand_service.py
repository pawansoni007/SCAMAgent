"""Open dated demand service for PROC-01 runout calculations.

The D365 entity and field names below are intentionally isolated here so an
F&O technical owner can validate them against the target environment metadata.
If live demand entities are not available, the service falls back to deterministic
mock demand for the demo.
"""

from __future__ import annotations

import logging

from agents.procurement_exception_agent.models import DatedDemandLine
from integrations.d365 import (
    is_configured as _d365_enabled,
    get_client as _d365_client,
    to_float,
    to_date,
)
from services.debug_trace import traced_function

logger = logging.getLogger(__name__)

_SALES_ENTITY = "SalesOrderLinesV2"
_SALES_FIELD = {
    "item_id": "ItemNumber",
    "reference_id": "SalesOrderNumber",
    "site_id": "ShippingSiteId",
    "warehouse_id": "ShippingWarehouseId",
    "remaining_qty": "RemainingSalesQuantity",
    "issue_status": "TransactionIssueStatus",
    "ship_date": "ShippingDateConfirmed",
}

_PRODUCTION_ENTITY = "ProductionOrderBOMLines"
_PRODUCTION_FIELD = {
    "item_id": "ItemNumber",
    "reference_id": "ProductionOrderNumber",
    "site_id": "ProductionSiteId",
    "warehouse_id": "ProductionWarehouseId",
    "required_qty": "BOMComponentQuantity",
    "raw_material_date": "RawMaterialDate",
}

_TRANSFER_ENTITY = "TransferOrderLines"
_TRANSFER_FIELD = {
    "item_id": "ItemNumber",
    "reference_id": "TransferOrderNumber",
    "site_id": "FromSiteId",
    "warehouse_id": "FromWarehouseId",
    "remaining_qty": "RemainingTransferQuantity",
    "issue_status": "TransactionIssueStatus",
    "ship_date": "ShippingDateConfirmed",
}

_ISSUE_STATUS_ON_ORDER = "On order"
_DEMAND_QUERY_TOP = 1000

_MOCK_DEMAND: dict[str, list[DatedDemandLine]] = {
    "ITEM001": [
        DatedDemandLine(
            item_id="ITEM001",
            demand_date="2026-07-10",
            demand_qty=60,
            demand_source="sales_order",
            reference_id="SO-10001",
            site_id="SITE-02",
            warehouse_id="WH-01",
        ),
        DatedDemandLine(
            item_id="ITEM001",
            demand_date="2026-07-20",
            demand_qty=90,
            demand_source="production",
            reference_id="PROD-10001",
            site_id="SITE-02",
            warehouse_id="WH-01",
        ),
    ],
    "ITEM002": [
        DatedDemandLine(
            item_id="ITEM002",
            demand_date="2026-06-30",
            demand_qty=30,
            demand_source="sales_order",
            reference_id="SO-20001",
            site_id="SITE-01",
            warehouse_id="WH-01",
        ),
        DatedDemandLine(
            item_id="ITEM002",
            demand_date="2026-07-03",
            demand_qty=45,
            demand_source="transfer",
            reference_id="TO-20001",
            site_id="SITE-01",
            warehouse_id="WH-01",
        ),
        DatedDemandLine(
            item_id="ITEM002",
            demand_date="2026-07-08",
            demand_qty=80,
            demand_source="production",
            reference_id="PROD-20001",
            site_id="SITE-01",
            warehouse_id="WH-02",
        ),
    ],
    "ITEM003": [
        DatedDemandLine(
            item_id="ITEM003",
            demand_date="2026-06-29",
            demand_qty=50,
            demand_source="production",
            reference_id="PROD-30001",
            site_id="SITE-03",
            warehouse_id="WH-03",
        ),
        DatedDemandLine(
            item_id="ITEM003",
            demand_date="2026-07-02",
            demand_qty=120,
            demand_source="sales_order",
            reference_id="SO-30001",
            site_id="SITE-03",
            warehouse_id="WH-03",
        ),
    ],
}


@traced_function("method")
def get_open_demand(
    item_id: str,
    site_id: str | None = None,
    warehouse_id: str | None = None,
) -> list[DatedDemandLine]:
    """Retrieve open sales, production and transfer demand for an item."""
    if _d365_enabled():
        try:
            return _fetch_open_demand_d365(item_id, site_id, warehouse_id)
        except Exception as exc:
            logger.warning(
                "D365 open-demand lookup failed for '%s'; falling back to mock. Error: %s",
                item_id,
                exc,
            )
    return _filter_mock_demand(item_id, site_id, warehouse_id)


def _fetch_open_demand_d365(
    item_id: str,
    site_id: str | None,
    warehouse_id: str | None,
) -> list[DatedDemandLine]:
    demand = [
        *_fetch_sales_demand(item_id, site_id, warehouse_id),
        *_fetch_production_demand(item_id, site_id, warehouse_id),
        *_fetch_transfer_demand(item_id, site_id, warehouse_id),
    ]
    return sorted(demand, key=lambda line: line.demand_date)


@traced_function("method", entity=_SALES_ENTITY)
def _fetch_sales_demand(
    item_id: str,
    site_id: str | None,
    warehouse_id: str | None,
) -> list[DatedDemandLine]:
    f = _SALES_FIELD
    rows = _d365_client().query(
        _SALES_ENTITY,
        filter=_and_filter(
            [
                _eq(f["item_id"], item_id),
                _eq(f["issue_status"], _ISSUE_STATUS_ON_ORDER),
                _eq(f["site_id"], site_id),
                _eq(f["warehouse_id"], warehouse_id),
            ]
        ),
        top=_DEMAND_QUERY_TOP,
        orderby=f["ship_date"],
    )
    return [
        _demand_line(row, f, "sales_order", f["ship_date"], f["remaining_qty"])
        for row in rows
    ]


@traced_function("method", entity=_PRODUCTION_ENTITY)
def _fetch_production_demand(
    item_id: str,
    site_id: str | None,
    warehouse_id: str | None,
) -> list[DatedDemandLine]:
    f = _PRODUCTION_FIELD
    rows = _d365_client().query(
        _PRODUCTION_ENTITY,
        filter=_and_filter(
            [
                _eq(f["item_id"], item_id),
                _eq(f["site_id"], site_id),
                _eq(f["warehouse_id"], warehouse_id),
            ]
        ),
        top=_DEMAND_QUERY_TOP,
        orderby=f["raw_material_date"],
    )
    return [
        _demand_line(row, f, "production", f["raw_material_date"], f["required_qty"])
        for row in rows
    ]


@traced_function("method", entity=_TRANSFER_ENTITY)
def _fetch_transfer_demand(
    item_id: str,
    site_id: str | None,
    warehouse_id: str | None,
) -> list[DatedDemandLine]:
    f = _TRANSFER_FIELD
    rows = _d365_client().query(
        _TRANSFER_ENTITY,
        filter=_and_filter(
            [
                _eq(f["item_id"], item_id),
                _eq(f["issue_status"], _ISSUE_STATUS_ON_ORDER),
                _eq(f["site_id"], site_id),
                _eq(f["warehouse_id"], warehouse_id),
            ]
        ),
        top=_DEMAND_QUERY_TOP,
        orderby=f["ship_date"],
    )
    return [
        _demand_line(row, f, "transfer", f["ship_date"], f["remaining_qty"])
        for row in rows
    ]


def _filter_mock_demand(
    item_id: str,
    site_id: str | None,
    warehouse_id: str | None,
) -> list[DatedDemandLine]:
    lines = _MOCK_DEMAND.get(item_id, [])
    return [
        line
        for line in lines
        if (not site_id or line.site_id == site_id)
        and (not warehouse_id or line.warehouse_id == warehouse_id)
    ]


def _demand_line(
    row: dict,
    fields: dict[str, str],
    demand_source: str,
    date_field: str,
    qty_field: str,
) -> DatedDemandLine:
    return DatedDemandLine(
        item_id=str(row.get(fields["item_id"], "") or ""),
        demand_date=to_date(row.get(date_field)) or "",
        demand_qty=to_float(row.get(qty_field)),
        demand_source=demand_source,
        reference_id=str(row.get(fields["reference_id"], "") or "") or None,
        site_id=str(row.get(fields["site_id"], "") or "") or None,
        warehouse_id=str(row.get(fields["warehouse_id"], "") or "") or None,
    )


def _eq(field: str, value: str | None) -> str | None:
    if not value:
        return None
    from integrations.d365 import D365ODataClient

    return f"{field} eq '{D365ODataClient.escape_literal(value)}'"


def _and_filter(parts: list[str | None]) -> str | None:
    cleaned = [part for part in parts if part]
    return " and ".join(cleaned) if cleaned else None
