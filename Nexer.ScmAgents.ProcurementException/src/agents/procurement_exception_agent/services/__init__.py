"""Procurement agent domain services.

Each service type lives in its own subpackage:
    inventory/   — on-hand stock and safety-stock coverage
    supplier/    — vendor master and approved vendor lists
    procurement/ — purchase orders, supplier pricing, lead time
    risk/        — deterministic procurement risk calculations
    policy/      — procurement policy retrieval
    forecast/    — demand forecast
    demand/      — dated open demand for runout calculation
    audit/       — audit log writes
"""

from .inventory import get_inventory, get_safety_stock, list_inventory
from .supplier import (
    get_supplier_performance,
    get_approved_suppliers,
    get_approved_suppliers_for_item,
)
from .forecast import get_demand_forecast
from .demand import get_open_demand
from .procurement import (
    get_lead_time_data,
    get_supplier_prices,
    get_open_purchase_orders,
    get_overdue_purchase_orders,
)
from .risk import assess_overdue_po_coverage_risk
from .policy import get_procurement_policies
from .audit import write_audit_log

__all__ = [
    "get_inventory",
    "get_safety_stock",
    "list_inventory",
    "get_supplier_performance",
    "get_approved_suppliers",
    "get_approved_suppliers_for_item",
    "get_demand_forecast",
    "get_open_demand",
    "get_lead_time_data",
    "get_supplier_prices",
    "get_open_purchase_orders",
    "get_overdue_purchase_orders",
    "assess_overdue_po_coverage_risk",
    "get_procurement_policies",
    "write_audit_log",
]
