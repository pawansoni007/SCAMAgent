"""
Procurement Service.

Provides procurement data for the agent, sourced from D365 Finance & Operations
via OData when the D365 connection is configured (D365_ODATA_BASE_URL present);
mock data is used only when D365 is not configured.

  - PROC-01 purchase lines -> PurchaseOrderLinesV2 (PurchPurchaseOrderLineV2Entity)
  - PROC-01 PO headers     -> PurchaseOrderHeadersV2 (vendor account)
  - PROC-01 receipts       -> ProductReceiptLinesV2 (VendProductReceiptLineV2Entity)
  - Supplier pricing       -> PurchasePriceAgreements
  - Lead time data         -> PurchasePriceAgreements (ProcurementLeadTimeDays)

Note: purchase price agreements do not carry an on-time-delivery rate or
expedited lead time, so those fields use placeholders / None (see below).
"""

import logging
from datetime import date

from agents.procurement_exception_agent.models import LeadTimeData, SupplierPrice, PurchaseOrder
from integrations.d365 import (
    is_configured as _d365_enabled,
    get_client as _d365_client,
    to_int,
    to_float,
)
from services.debug_trace import traced_function

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PROC-01 D365 OData public collection names and field mappings.
# Verify against scripts/_d365_inspect_entity.py on your environment.
# Do not use source ERP status values for PROC-01 overdue determination.
# ---------------------------------------------------------------------------
_PO_ENTITY = "PurchaseOrderLinesV2"
_PO_FIELD = {
    "po_id": "PurchaseOrderNumber",
    "line_num": "LineNumber",
    "item_id": "ItemNumber",
    "requested_receipt_date": "RequestedDeliveryDate",
    "confirmed_receipt_date": "ConfirmedDeliveryDate",
    "qty_ordered": "OrderedPurchaseQuantity",
    "status": "PurchaseOrderLineStatus",
    "net_amount": "LineAmount",
    "site_id": "ReceivingSiteId",
    "warehouse_id": "ReceivingWarehouseId",
}

_PO_HEADER_ENTITY = "PurchaseOrderHeadersV2"
_PO_HEADER_FIELD = {
    "po_id": "PurchaseOrderNumber",
    "supplier_id": "OrderVendorAccountNumber",
}

_PRODUCT_RECEIPT_ENTITY = "ProductReceiptLinesV2"
_PRODUCT_RECEIPT_FIELD = {
    "po_id": "PurchaseOrderNumber",
    "line_num": "PurchaseOrderLineNumber",
    "remaining_purchase_quantity": "RemainingPurchaseQuantity",
    "product_receipt_date": "ProductReceiptDate",
}

# Max PO lines to pull per item from D365 for general open-PO lookups.
_PO_QUERY_TOP = 100

# Max D365 overdue candidate lines to inspect before applying receipt-status
# logic. Candidates are prefiltered by planned receipt date and ordered oldest
# first so the agent does not miss overdue lines behind received/invoiced rows.
_PO_OVERDUE_CANDIDATE_CAP = 5000
_D365_NULL_DATETIME = "1900-01-01T12:00:00Z"

# D365 PurchasePriceAgreements mapping (supplier pricing + lead time).
_PRICE_ENTITY = "PurchasePriceAgreements"
_PRICE_FIELD = {
    "item_id": "ItemNumber",
    "supplier_id": "VendorAccountNumber",
    "unit_price": "Price",
    "currency": "PriceCurrencyCode",
    "minimum_order_qty": "FromQuantity",
    "valid_to": "PriceApplicableToDate",
    "lead_time_days": "ProcurementLeadTimeDays",
}

# D365 "no end date" sentinel (PriceApplicableToDate when open-ended).
_D365_NULL_DATE_PREFIX = "1900-01-01"

# On-time-delivery rate is not present in price agreements; placeholder until a
# vendor-performance source is connected. Required by the LeadTimeData model.
_DEFAULT_ON_TIME_RATE = 0.95


_MOCK_LEAD_TIMES: dict[tuple[str, str], LeadTimeData] = {
    ("SUP001", "ITEM001"): LeadTimeData(supplier_id="SUP001", item_id="ITEM001", standard_lead_time_days=5,  expedited_lead_time_days=2, last_actual_lead_time_days=5,  on_time_delivery_rate=0.96),
    ("SUP001", "ITEM002"): LeadTimeData(supplier_id="SUP001", item_id="ITEM002", standard_lead_time_days=5,  expedited_lead_time_days=2, last_actual_lead_time_days=6,  on_time_delivery_rate=0.94),
    ("SUP002", "ITEM002"): LeadTimeData(supplier_id="SUP002", item_id="ITEM002", standard_lead_time_days=10, expedited_lead_time_days=5, last_actual_lead_time_days=12, on_time_delivery_rate=0.70),
    ("SUP004", "ITEM002"): LeadTimeData(supplier_id="SUP004", item_id="ITEM002", standard_lead_time_days=7,  expedited_lead_time_days=3, last_actual_lead_time_days=7,  on_time_delivery_rate=0.91),
    ("SUP001", "ITEM003"): LeadTimeData(supplier_id="SUP001", item_id="ITEM003", standard_lead_time_days=5,  expedited_lead_time_days=2, last_actual_lead_time_days=5,  on_time_delivery_rate=0.95),
}

_MOCK_PRICES: dict[tuple[str, str], SupplierPrice] = {
    ("SUP001", "ITEM001"): SupplierPrice(supplier_id="SUP001", item_id="ITEM001", unit_price=12.50, currency="GBP", minimum_order_qty=50,  price_valid_until="2026-12-31"),
    ("SUP001", "ITEM002"): SupplierPrice(supplier_id="SUP001", item_id="ITEM002", unit_price=8.75,  currency="GBP", minimum_order_qty=100, price_valid_until="2026-12-31"),
    ("SUP002", "ITEM002"): SupplierPrice(supplier_id="SUP002", item_id="ITEM002", unit_price=7.50,  currency="GBP", minimum_order_qty=200, price_valid_until="2026-09-30", discount_rate=0.05),
    ("SUP004", "ITEM002"): SupplierPrice(supplier_id="SUP004", item_id="ITEM002", unit_price=9.00,  currency="GBP", minimum_order_qty=50,  price_valid_until="2026-12-31"),
    ("SUP001", "ITEM003"): SupplierPrice(supplier_id="SUP001", item_id="ITEM003", unit_price=25.00, currency="GBP", minimum_order_qty=20,  price_valid_until="2026-12-31"),
}

# Demo dataset includes overdue purchase orders (planned receipt date in the
# past) so the overdue_purchase_order flow is demonstrable. ITEM003 has zero
# on-hand stock, making PO-10004 the most critical overdue line.
_MOCK_PURCHASE_ORDERS: list[PurchaseOrder] = [
    PurchaseOrder(po_id="PO-10001", line_num="1", item_id="ITEM002", invent_dim_id="DIM-001", site_id="SITE-01", warehouse_id="WH-01", supplier_id="SUP001", qty_ordered=200, qty_outstanding=200, remaining_purchase_quantity=200, status="delayed",  expected_delivery_date="2026-06-02", requested_receipt_date="2026-06-02", confirmed_receipt_date=None, product_receipt_date=None, net_amount=1750.00, is_blocked=False, block_reason=None),
    PurchaseOrder(po_id="PO-10002", line_num="1", item_id="ITEM002", invent_dim_id="DIM-002", site_id="SITE-01", warehouse_id="WH-02", supplier_id="SUP002", qty_ordered=100, qty_outstanding=100, remaining_purchase_quantity=100, status="blocked",  expected_delivery_date="2026-06-15", requested_receipt_date="2026-06-15", confirmed_receipt_date=None, product_receipt_date=None, net_amount=750.00,  is_blocked=True,  block_reason="Missing goods receipt"),
    PurchaseOrder(po_id="PO-10003", line_num="1", item_id="ITEM001", invent_dim_id="DIM-003", site_id="SITE-02", warehouse_id="WH-01", supplier_id="SUP001", qty_ordered=150, qty_outstanding=50,  remaining_purchase_quantity=50,  status="open",     expected_delivery_date="2026-06-05", requested_receipt_date="2026-06-05", confirmed_receipt_date=None, product_receipt_date=None, net_amount=1875.00, is_blocked=False, block_reason=None),
    PurchaseOrder(po_id="PO-10004", line_num="1", item_id="ITEM003", invent_dim_id="DIM-004", site_id="SITE-03", warehouse_id="WH-03", supplier_id="SUP001", qty_ordered=300, qty_outstanding=300, remaining_purchase_quantity=300, status="delayed",  expected_delivery_date="2026-05-30", requested_receipt_date="2026-05-30", confirmed_receipt_date=None, product_receipt_date=None, net_amount=7500.00, is_blocked=False, block_reason=None),
]


@traced_function("method")
def get_lead_time_data(supplier_id: str, item_id: str) -> LeadTimeData | None:
    """Retrieve delivery lead time data for a supplier-item combination."""
    if _d365_enabled():
        try:
            return _fetch_lead_time_d365(supplier_id, item_id)
        except Exception as exc:
            logger.warning(
                "D365 lead-time lookup failed for '%s'/'%s'; falling back to mock. Error: %s",
                supplier_id,
                item_id,
                exc,
            )
    return _MOCK_LEAD_TIMES.get((supplier_id, item_id))


@traced_function("method")
def get_supplier_prices(supplier_id: str, item_id: str) -> SupplierPrice | None:
    """Retrieve current pricing for a supplier-item combination."""
    if _d365_enabled():
        try:
            return _fetch_supplier_price_d365(supplier_id, item_id)
        except Exception as exc:
            logger.warning(
                "D365 price lookup failed for '%s'/'%s'; falling back to mock. Error: %s",
                supplier_id,
                item_id,
                exc,
            )
    return _MOCK_PRICES.get((supplier_id, item_id))


@traced_function("method")
def get_open_purchase_orders(item_id: str) -> list[PurchaseOrder]:
    """Retrieve all open or in-progress purchase orders for an item.

    Uses live D365 F&O data when configured; mock data is used only when D365 is
    not configured.
    """
    if _d365_enabled():
        return _fetch_open_purchase_orders_d365(item_id)
    return [po for po in _MOCK_PURCHASE_ORDERS if po.item_id == item_id]


@traced_function("method")
def get_overdue_purchase_orders(item_id: str | None = None) -> list[PurchaseOrder]:
    """Retrieve purchase orders whose overdue status is calculated deterministically."""
    if _d365_enabled():
        orders = _fetch_overdue_purchase_orders_d365(item_id)
        return [_with_calculated_overdue_status(po) for po in orders if _is_overdue(po)]
    orders = _MOCK_PURCHASE_ORDERS
    if item_id:
        orders = [po for po in orders if po.item_id == item_id]
    return [_with_calculated_overdue_status(po) for po in orders if _is_overdue(po)]


# ---------------------------------------------------------------------------
# D365 F&O integration (open purchase orders)
# ---------------------------------------------------------------------------

@traced_function("method", entity=_PO_ENTITY)
def _fetch_open_purchase_orders_d365(item_id: str | None) -> list[PurchaseOrder]:
    """Query open PO lines for an item from D365 and map to PurchaseOrder."""
    from integrations.d365 import D365ODataClient

    f = _PO_FIELD
    filter_expr = (
        f"{f['item_id']} eq '{D365ODataClient.escape_literal(item_id)}'"
        if item_id
        else None
    )
    return _fetch_purchase_orders_d365(
        filter_expr=filter_expr,
        top=_PO_QUERY_TOP,
        requested_item_id=item_id,
    )


@traced_function("method", entity=_PO_ENTITY)
def _fetch_overdue_purchase_orders_d365(item_id: str | None) -> list[PurchaseOrder]:
    """Query D365 for past-planned PO lines, then map for deterministic filtering."""
    from integrations.d365 import D365ODataClient

    f = _PO_FIELD
    filters = [_planned_receipt_overdue_filter()]
    if item_id:
        filters.append(f"{f['item_id']} eq '{D365ODataClient.escape_literal(item_id)}'")

    return _fetch_purchase_orders_d365(
        filter_expr=_and_filter(filters),
        top=None,
        requested_item_id=item_id,
        orderby=f"{f['requested_receipt_date']} asc",
        page_cap=_PO_OVERDUE_CANDIDATE_CAP,
    )


def _fetch_purchase_orders_d365(
    *,
    filter_expr: str | None,
    top: int | None,
    requested_item_id: str | None,
    orderby: str | None = None,
    page_cap: int | None = None,
) -> list[PurchaseOrder]:
    f = _PO_FIELD
    rows = _d365_client().query(
        _PO_ENTITY,
        filter=filter_expr,
        top=top,
        orderby=orderby,
        page_cap=page_cap or _PO_QUERY_TOP,
    )
    if not rows:
        return []

    po_keys = {
        _po_line_key(
            str(row.get(f["po_id"], "") or ""),
            str(row.get(f["line_num"], "") or ""),
        )
        for row in rows
        if row.get(f["po_id"])
    }
    receipt_by_line = _fetch_product_receipt_map(po_keys)
    po_numbers = {po_id for po_id, _ in po_keys}
    header_by_po = _fetch_po_header_map(po_numbers)

    orders: list[PurchaseOrder] = []
    for row in rows:
        po_id = str(row.get(f["po_id"], "") or "")
        line_num = str(row.get(f["line_num"], "") or "")
        receipt = receipt_by_line.get(_po_line_key(po_id, line_num), {})
        header = header_by_po.get(po_id, {})

        confirmed_receipt_date = _optional_date(row.get(f["confirmed_receipt_date"]))
        requested_receipt_date = _optional_date(row.get(f["requested_receipt_date"]))
        product_receipt_date = receipt.get("product_receipt_date")
        expected_delivery_date = confirmed_receipt_date or requested_receipt_date
        qty_ordered = to_int(row.get(f.get("qty_ordered", "")))
        remaining_purchase_quantity = receipt.get("remaining_purchase_quantity")
        qty_outstanding = (
            remaining_purchase_quantity
            if remaining_purchase_quantity is not None
            else qty_ordered
        )
        source_status = str(row.get(f.get("status", ""), "") or "open")
        calculated_status = _derive_overdue_status(
            qty_outstanding=qty_outstanding,
            expected_delivery_date=expected_delivery_date,
            source_status=source_status,
        )

        orders.append(
            PurchaseOrder(
                po_id=po_id,
                line_num=line_num or None,
                item_id=str(row.get(f["item_id"], "") or requested_item_id or ""),
                invent_dim_id=None,
                site_id=str(row.get(f["site_id"], "") or "") or None,
                warehouse_id=str(row.get(f["warehouse_id"], "") or "") or None,
                supplier_id=str(header.get("supplier_id", "") or ""),
                qty_ordered=qty_ordered,
                qty_outstanding=qty_outstanding,
                remaining_purchase_quantity=remaining_purchase_quantity,
                status=calculated_status,
                expected_delivery_date=expected_delivery_date,
                requested_receipt_date=requested_receipt_date,
                confirmed_receipt_date=confirmed_receipt_date,
                product_receipt_date=product_receipt_date,
                days_late=_calculate_days_late(expected_delivery_date),
                net_amount=to_float(row.get(f.get("net_amount", ""))),
                is_blocked=False,
                block_reason=None,
            )
        )
    return orders


@traced_function("method", entity=_PRODUCT_RECEIPT_ENTITY)
def _fetch_product_receipt_map(po_keys: set[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    if not po_keys:
        return {}
    fields = _PRODUCT_RECEIPT_FIELD
    rows = _fetch_rows_by_values(
        _PRODUCT_RECEIPT_ENTITY,
        values={po_id for po_id, _ in po_keys if po_id},
        field=fields["po_id"],
    )

    receipt_by_line: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = _po_line_key(
            str(row.get(fields["po_id"], "") or ""),
            str(row.get(fields["line_num"], "") or ""),
        )
        if key not in po_keys:
            continue
        receipt_date = _optional_date(row.get(fields["product_receipt_date"]))
        existing = receipt_by_line.get(key)
        if existing and receipt_date and existing.get("product_receipt_date", "") > receipt_date:
            continue
        receipt_by_line[key] = {
            "remaining_purchase_quantity": to_int(
                row.get(fields["remaining_purchase_quantity"])
            ),
            "product_receipt_date": receipt_date,
        }
    return receipt_by_line


@traced_function("method", entity=_PO_HEADER_ENTITY)
def _fetch_po_header_map(po_numbers: set[str]) -> dict[str, dict[str, str]]:
    if not po_numbers:
        return {}
    fields = _PO_HEADER_FIELD
    rows = _fetch_rows_by_values(
        _PO_HEADER_ENTITY,
        values=po_numbers,
        field=fields["po_id"],
    )
    return {
        str(row.get(fields["po_id"], "") or ""): {
            "supplier_id": str(row.get(fields["supplier_id"], "") or ""),
        }
        for row in rows
    }


def _value_filter_clause(values: set[str], field: str) -> str:
    from integrations.d365 import D365ODataClient

    esc = D365ODataClient.escape_literal
    return " or ".join(f"{field} eq '{esc(value)}'" for value in sorted(values))


def _fetch_rows_by_values(entity: str, *, values: set[str], field: str) -> list[dict]:
    rows: list[dict] = []
    for chunk in _chunks(sorted(value for value in values if value), 40):
        rows.extend(
            _d365_client().query(
                entity,
                filter=_value_filter_clause(set(chunk), field),
            )
        )
    return rows


def _chunks(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _planned_receipt_overdue_filter() -> str:
    today = date.today().isoformat()
    f = _PO_FIELD
    return (
        f"(({f['confirmed_receipt_date']} ne {_D365_NULL_DATETIME} "
        f"and {f['confirmed_receipt_date']} lt {today}T00:00:00Z) "
        f"or ({f['confirmed_receipt_date']} eq {_D365_NULL_DATETIME} "
        f"and {f['requested_receipt_date']} lt {today}T00:00:00Z))"
    )


def _and_filter(filters: list[str]) -> str | None:
    non_empty = [filter_expr for filter_expr in filters if filter_expr]
    if not non_empty:
        return None
    return " and ".join(f"({filter_expr})" for filter_expr in non_empty)


def _po_line_key(po_id: str, line_num: str) -> tuple[str, str]:
    return (po_id, str(line_num).rstrip("0").rstrip(".") if "." in str(line_num) else str(line_num))


# ---------------------------------------------------------------------------
# D365 F&O integration (supplier pricing + lead time)
# ---------------------------------------------------------------------------

@traced_function("method", entity=_PRICE_ENTITY)
def _fetch_price_agreement_row(supplier_id: str, item_id: str) -> dict | None:
    """Resolve a purchase price agreement for a supplier+item.

    Mirrors D365 trade-agreement search precedence: a vendor-specific ("Table")
    agreement wins; otherwise an item-level "All vendors" agreement (blank
    VendorAccountNumber) applies.
    """
    from integrations.d365 import D365ODataClient

    f = _PRICE_FIELD
    esc = D365ODataClient.escape_literal
    item_clause = f"{f['item_id']} eq '{esc(item_id)}'"

    # 1) Vendor-specific agreement.
    row = _d365_client().get_first(
        _PRICE_ENTITY,
        filter=f"{f['supplier_id']} eq '{esc(supplier_id)}' and {item_clause}",
    )
    if row:
        return row

    # 2) Fall back to an "All vendors" agreement for the item.
    return _d365_client().get_first(
        _PRICE_ENTITY,
        filter=f"{item_clause} and {f['supplier_id']} eq ''",
    )


@traced_function("method", entity=_PRICE_ENTITY)
def _fetch_supplier_price_d365(supplier_id: str, item_id: str) -> SupplierPrice | None:
    from integrations.d365 import to_float

    f = _PRICE_FIELD
    row = _fetch_price_agreement_row(supplier_id, item_id)
    if not row:
        return None

    return SupplierPrice(
        supplier_id=str(row.get(f["supplier_id"], "") or supplier_id),
        item_id=str(row.get(f["item_id"], "") or item_id),
        unit_price=to_float(row.get(f["unit_price"])),
        currency=str(row.get(f["currency"], "") or "GBP"),
        minimum_order_qty=to_int(row.get(f["minimum_order_qty"]) or 1),
        price_valid_until=_optional_date(row.get(f["valid_to"])),
        discount_rate=0.0,  # not modelled in purchase price agreements
    )


@traced_function("method", entity=_PRICE_ENTITY)
def _fetch_lead_time_d365(supplier_id: str, item_id: str) -> LeadTimeData | None:
    f = _PRICE_FIELD
    row = _fetch_price_agreement_row(supplier_id, item_id)
    if not row:
        return None

    return LeadTimeData(
        supplier_id=str(row.get(f["supplier_id"], "") or supplier_id),
        item_id=str(row.get(f["item_id"], "") or item_id),
        standard_lead_time_days=to_int(row.get(f["lead_time_days"])),
        expedited_lead_time_days=None,
        last_actual_lead_time_days=None,
        on_time_delivery_rate=_DEFAULT_ON_TIME_RATE,
    )


def _optional_date(value) -> str | None:
    """Map an OData date to ISO date, treating the 1900-01-01 sentinel as None."""
    from integrations.d365 import to_date

    iso = to_date(value)
    if iso and iso.startswith(_D365_NULL_DATE_PREFIX):
        return None
    return iso


def _derive_overdue_status(
    qty_outstanding: int,
    expected_delivery_date: str | None,
    source_status: str,
) -> str:
    if qty_outstanding > 0 and expected_delivery_date and expected_delivery_date[:10] < date.today().isoformat():
        return "Overdue"
    return source_status


def _calculate_days_late(expected_delivery_date: str | None) -> int:
    if not expected_delivery_date:
        return 0
    return max((date.today() - date.fromisoformat(expected_delivery_date[:10])).days, 0)


def _is_overdue(po: PurchaseOrder) -> bool:
    return (
        po.qty_outstanding > 0
        and not po.product_receipt_date
        and bool(po.expected_delivery_date)
        and po.expected_delivery_date[:10] < date.today().isoformat()
    )


def _with_calculated_overdue_status(po: PurchaseOrder) -> PurchaseOrder:
    return po.model_copy(
        update={
            "status": _derive_overdue_status(
                po.qty_outstanding,
                po.expected_delivery_date,
                po.status,
            ),
            "days_late": _calculate_days_late(po.expected_delivery_date),
            "requested_receipt_date": po.requested_receipt_date or po.expected_delivery_date,
            "confirmed_receipt_date": po.confirmed_receipt_date,
            "product_receipt_date": po.product_receipt_date,
        }
    )
