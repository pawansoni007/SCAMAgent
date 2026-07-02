"""
Supplier Service.

Vendor identity and approval status are sourced from D365 Finance & Operations
(Vendors entity) when the D365 connection is configured; otherwise (or on any
error) the bundled mock dataset is used.

NOTE on reliability/risk: D365 F&O has no native "reliability score" or "risk
rating" field. Until a real vendor-performance source (e.g. vendor evaluation /
analytics) is connected, `risk` is derived from the vendor's on-hold status and
`reliability` uses a neutral placeholder. These are clearly marked below.
"""

import logging
from datetime import date

from agents.procurement_exception_agent.models import Supplier
from integrations.d365 import (
    is_configured as _d365_enabled,
    get_client as _d365_client,
    to_float,
    to_date,
)

logger = logging.getLogger(__name__)


_MOCK_SUPPLIERS: dict[str, Supplier] = {
    "SUP001": Supplier(supplier_id="SUP001", name="FastTrack Supply Co.",     reliability=0.95, risk="Low",    lead_time_days=5,  is_approved=True),
    "SUP002": Supplier(supplier_id="SUP002", name="MidRange Materials Ltd.",  reliability=0.70, risk="Medium", lead_time_days=10, is_approved=True),
    "SUP003": Supplier(supplier_id="SUP003", name="RiskyVendor GmbH",         reliability=0.55, risk="High",   lead_time_days=14, is_approved=False),
    "SUP004": Supplier(supplier_id="SUP004", name="Reliable Parts Inc.",      reliability=0.90, risk="Low",    lead_time_days=7,  is_approved=True),
}


# ---------------------------------------------------------------------------
# D365 Vendors mapping.
#
# IMPORTANT: Verify these entity/field names against your environment:
#   GET {D365_ODATA_BASE_URL}/data/$metadata
#   scripts/_d365_smoke_test.py VendorsV3
# To adjust, edit the values below — no other code changes are required.
# ---------------------------------------------------------------------------
_VENDOR_ENTITY = "VendorsV3"
_VENDOR_FIELD = {
    "supplier_id": "VendorAccountNumber",
    "name": "VendorOrganizationName",
    "on_hold": "OnHoldStatus",
}

# OnHoldStatus values that mean the vendor is usable / approved for ordering.
_APPROVED_ON_HOLD_STATUSES = {"", "No", "None"}

# Placeholder reliability until a real vendor-performance source is connected.
_DEFAULT_RELIABILITY = 0.9

# D365 item-specific approved vendor list (the "Approved vendor list" feature).
# Links an item to the vendors explicitly approved to supply it, with a validity
# window. This is item-scoped, unlike the global vendor master (VendorsV3).
_APPROVED_VENDOR_ENTITY = "ProductApprovedVendorsForAI"
_APPROVED_VENDOR_FIELD = {
    "item_id": "ItemNumber",
    "supplier_id": "ApprovedVendorAccountNumber",
    "valid_from": "ValidFrom",
    "valid_to": "ValidTo",
}


def get_supplier_performance(supplier_id: str) -> Supplier | None:
    """Retrieve reliability score, risk rating, and lead time for a supplier."""
    if _d365_enabled():
        try:
            return _fetch_supplier_d365(supplier_id)
        except Exception as exc:
            logger.warning(
                "D365 vendor lookup failed for '%s'; falling back to mock. Error: %s",
                supplier_id,
                exc,
            )
    return _MOCK_SUPPLIERS.get(supplier_id)


def get_approved_suppliers() -> list[Supplier]:
    """Retrieve all suppliers currently on the approved vendor list."""
    if _d365_enabled():
        try:
            return [s for s in _fetch_all_vendors_d365() if s.is_approved]
        except Exception as exc:
            logger.warning(
                "D365 approved-vendor lookup failed; falling back to mock. Error: %s",
                exc,
            )
    return [s for s in _MOCK_SUPPLIERS.values() if s.is_approved]


def get_approved_suppliers_for_item(item_id: str) -> list[Supplier]:
    """Retrieve vendors approved to supply a SPECIFIC item.

    Sourced from D365's item-level approved vendor list
    (ProductApprovedVendorsForAI), honouring each entry's validity window.
    Returns an empty list when no vendor is approved for the item — callers
    must treat that as "no item-specific approved vendors", NOT as an error.
    """
    if _d365_enabled():
        try:
            return _fetch_approved_suppliers_for_item_d365(item_id)
        except Exception as exc:
            logger.warning(
                "D365 item approved-vendor lookup failed for '%s'; "
                "falling back to mock. Error: %s",
                item_id,
                exc,
            )
    return [s for s in _MOCK_SUPPLIERS.values() if s.is_approved]


# ---------------------------------------------------------------------------
# D365 F&O integration (vendors)
# ---------------------------------------------------------------------------

def _fetch_supplier_d365(supplier_id: str) -> Supplier | None:
    from integrations.d365 import D365ODataClient

    f = _VENDOR_FIELD
    filter_expr = f"{f['supplier_id']} eq '{D365ODataClient.escape_literal(supplier_id)}'"
    row = _d365_client().get_first(_VENDOR_ENTITY, filter=filter_expr)
    return _map_vendor(row) if row else None


def _fetch_all_vendors_d365(top: int = 500) -> list[Supplier]:
    rows = _d365_client().query(_VENDOR_ENTITY, top=top)
    return [_map_vendor(row) for row in rows]


def _fetch_approved_suppliers_for_item_d365(item_id: str) -> list[Supplier]:
    from integrations.d365 import D365ODataClient

    f = _APPROVED_VENDOR_FIELD
    filter_expr = f"{f['item_id']} eq '{D365ODataClient.escape_literal(item_id)}'"
    rows = _d365_client().query(_APPROVED_VENDOR_ENTITY, filter=filter_expr, top=200)

    today = date.today().isoformat()
    suppliers: list[Supplier] = []
    seen: set[str] = set()
    for row in rows:
        # Honour the approval validity window (ValidFrom <= today <= ValidTo).
        valid_from = (to_date(row.get(f["valid_from"])) or "")[:10]
        valid_to = (to_date(row.get(f["valid_to"])) or "")[:10]
        if valid_from and valid_from > today:
            continue
        if valid_to and valid_to < today:
            continue

        vendor = str(row.get(f["supplier_id"], "") or "")
        if not vendor or vendor in seen:
            continue
        seen.add(vendor)

        # Enrich with vendor master data (name, on-hold -> approval/risk).
        supplier = _fetch_supplier_d365(vendor)
        if supplier is None:
            supplier = Supplier(
                supplier_id=vendor,
                name="",
                reliability=_DEFAULT_RELIABILITY,
                risk="Low",
                is_approved=True,
            )
        suppliers.append(supplier)
    return suppliers


def _map_vendor(row: dict) -> Supplier:
    f = _VENDOR_FIELD
    on_hold = str(row.get(f["on_hold"], "") or "")
    is_approved = on_hold in _APPROVED_ON_HOLD_STATUSES

    # Derived, NOT native D365 fields (see module docstring):
    risk = "Low" if is_approved else "High"
    reliability = to_float(row.get("reliability"), _DEFAULT_RELIABILITY)

    return Supplier(
        supplier_id=str(row.get(f["supplier_id"], "") or ""),
        name=str(row.get(f["name"], "") or ""),
        reliability=reliability,
        risk=risk,
        is_approved=is_approved,
    )
