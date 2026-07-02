"""
Inventory Service.

Inventory on-hand is sourced from D365 F&O (InventoryOnHandForAI) and safety
stock / reorder thresholds from item coverage settings (ItemCoverageSettingsV2)
when the D365 connection is configured; otherwise (or on any error) the bundled
mock dataset is used.

Aggregation note: D365 holds on-hand and coverage per site/warehouse/dimension.
Our domain model carries a single value per item, so quantities are summed
across all of an item's records (scoped to the configured company).
"""

import logging

from agents.procurement_exception_agent.models import InventoryStatus, SafetyStock
from integrations.d365 import is_configured as _d365_enabled, get_client as _d365_client, to_int

logger = logging.getLogger(__name__)


_MOCK_INVENTORY: dict[str, InventoryStatus] = {
    "ITEM001": InventoryStatus(item_id="ITEM001", available_qty=120, safety_stock=100),
    "ITEM002": InventoryStatus(item_id="ITEM002", available_qty=50,  safety_stock=100),
    "ITEM003": InventoryStatus(item_id="ITEM003", available_qty=0,   safety_stock=200),
    "ITEM004": InventoryStatus(item_id="ITEM004", available_qty=300, safety_stock=150),
}

_MOCK_SAFETY_STOCK: dict[str, SafetyStock] = {
    "ITEM001": SafetyStock(item_id="ITEM001", safety_stock_qty=100, reorder_point=120, max_stock_qty=500, unit_of_measure="EA"),
    "ITEM002": SafetyStock(item_id="ITEM002", safety_stock_qty=100, reorder_point=150, max_stock_qty=400, unit_of_measure="EA"),
    "ITEM003": SafetyStock(item_id="ITEM003", safety_stock_qty=200, reorder_point=250, max_stock_qty=800, unit_of_measure="KG"),
    "ITEM004": SafetyStock(item_id="ITEM004", safety_stock_qty=150, reorder_point=180, max_stock_qty=600, unit_of_measure="EA"),
}


# ---------------------------------------------------------------------------
# D365 mapping. Verify against {D365_ODATA_BASE_URL}/data/$metadata or via
# scripts/_d365_inspect_entity.py. Edit values below to adjust — no other
# code changes required.
# ---------------------------------------------------------------------------
_ONHAND_ENTITY = "InventoryOnHandForAI"
_ONHAND_FIELD = {
    "item_id": "ItemNumber",
    "site_id": "InventorySiteId",
    "warehouse_id": "InventoryWarehouseId",
    "available_qty": "AvailPhysical",
}

_COVERAGE_ENTITY = "ItemCoverageSettingsV2"
_COVERAGE_FIELD = {
    "item_id": "ItemNumber",
    "safety_stock_qty": "MinimumOnHandInventoryQuantity",
    "reorder_point": "ReorderPoint",
    "max_stock_qty": "MaximumOnHandInventoryQuantity",
}

# D365 has no per-item UoM on the coverage entity; default until mapped from
# ReleasedProductsV2 if needed.
_DEFAULT_UOM = "EA"

# Safety caps on rows pulled when listing all items.
_LIST_QUERY_TOP = 1000


def get_inventory(
    item_id: str,
    site_id: str | None = None,
    warehouse_id: str | None = None,
) -> InventoryStatus | None:
    """Retrieve current inventory levels for an item."""
    if _d365_enabled():
        try:
            return _fetch_inventory_d365(item_id, site_id, warehouse_id)
        except Exception as exc:
            logger.warning(
                "D365 inventory lookup failed for '%s'; falling back to mock. Error: %s",
                item_id,
                exc,
            )
    return _MOCK_INVENTORY.get(item_id)


def list_inventory() -> list[InventoryStatus]:
    """Retrieve the stock position of all items."""
    if _d365_enabled():
        try:
            return _fetch_inventory_list_d365()
        except Exception as exc:
            logger.warning(
                "D365 inventory list failed; falling back to mock. Error: %s", exc
            )
    return list(_MOCK_INVENTORY.values())


def get_safety_stock(item_id: str) -> SafetyStock | None:
    """Retrieve safety stock thresholds and reorder parameters for an item."""
    if _d365_enabled():
        try:
            return _fetch_safety_stock_d365(item_id)
        except Exception as exc:
            logger.warning(
                "D365 safety-stock lookup failed for '%s'; falling back to mock. Error: %s",
                item_id,
                exc,
            )
    return _MOCK_SAFETY_STOCK.get(item_id)


# ---------------------------------------------------------------------------
# D365 F&O integration (inventory + coverage)
# ---------------------------------------------------------------------------

def _fetch_inventory_d365(
    item_id: str,
    site_id: str | None,
    warehouse_id: str | None,
) -> InventoryStatus | None:
    from integrations.d365 import D365ODataClient

    filters = [
        f"{_ONHAND_FIELD['item_id']} eq '{D365ODataClient.escape_literal(item_id)}'"
    ]
    if site_id:
        filters.append(
            f"{_ONHAND_FIELD['site_id']} eq '{D365ODataClient.escape_literal(site_id)}'"
        )
    if warehouse_id:
        filters.append(
            f"{_ONHAND_FIELD['warehouse_id']} eq '{D365ODataClient.escape_literal(warehouse_id)}'"
        )
    item_filter = " and ".join(filters)
    onhand_rows = _d365_client().query(_ONHAND_ENTITY, filter=item_filter, top=_LIST_QUERY_TOP)

    cov_filter = f"{_COVERAGE_FIELD['item_id']} eq '{D365ODataClient.escape_literal(item_id)}'"
    coverage_rows = _d365_client().query(_COVERAGE_ENTITY, filter=cov_filter, top=_LIST_QUERY_TOP)

    if not onhand_rows and not coverage_rows:
        return None

    available = _sum_field(onhand_rows, _ONHAND_FIELD["available_qty"])
    safety = _sum_field(coverage_rows, _COVERAGE_FIELD["safety_stock_qty"])
    return InventoryStatus(item_id=item_id, available_qty=available, safety_stock=safety)


def _fetch_inventory_list_d365() -> list[InventoryStatus]:
    onhand_rows = _d365_client().query(_ONHAND_ENTITY, top=_LIST_QUERY_TOP)
    coverage_rows = _d365_client().query(_COVERAGE_ENTITY, top=_LIST_QUERY_TOP)

    available_by_item: dict[str, int] = {}
    for row in onhand_rows:
        item = str(row.get(_ONHAND_FIELD["item_id"], "") or "")
        if item:
            available_by_item[item] = available_by_item.get(item, 0) + to_int(
                row.get(_ONHAND_FIELD["available_qty"])
            )

    safety_by_item: dict[str, int] = {}
    for row in coverage_rows:
        item = str(row.get(_COVERAGE_FIELD["item_id"], "") or "")
        if item:
            safety_by_item[item] = safety_by_item.get(item, 0) + to_int(
                row.get(_COVERAGE_FIELD["safety_stock_qty"])
            )

    items = sorted(set(available_by_item) | set(safety_by_item))
    return [
        InventoryStatus(
            item_id=item,
            available_qty=available_by_item.get(item, 0),
            safety_stock=safety_by_item.get(item, 0),
        )
        for item in items
    ]


def _fetch_safety_stock_d365(item_id: str) -> SafetyStock | None:
    from integrations.d365 import D365ODataClient

    cov_filter = f"{_COVERAGE_FIELD['item_id']} eq '{D365ODataClient.escape_literal(item_id)}'"
    rows = _d365_client().query(_COVERAGE_ENTITY, filter=cov_filter, top=_LIST_QUERY_TOP)
    if not rows:
        return None

    return SafetyStock(
        item_id=item_id,
        safety_stock_qty=_sum_field(rows, _COVERAGE_FIELD["safety_stock_qty"]),
        reorder_point=_sum_field(rows, _COVERAGE_FIELD["reorder_point"]),
        max_stock_qty=_sum_field(rows, _COVERAGE_FIELD["max_stock_qty"]),
        unit_of_measure=_DEFAULT_UOM,
    )


def _sum_field(rows: list[dict], field: str) -> int:
    return sum(to_int(row.get(field)) for row in rows)
