"""
End-to-end test of the procurement-agent services against live D365 data.

Exercises the service layer (which transparently uses D365 when configured)
with real USMF identifiers and prints the mapped domain objects.

Usage (from the project directory):
    .venv\\Scripts\\python.exe scripts\\_d365_service_test.py [ITEM] [VENDOR]
"""

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


def _load_local_settings() -> None:
    if os.environ.get("D365_ODATA_BASE_URL"):
        return
    settings_path = PROJECT_DIR / "local.settings.json"
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        for key, value in data.get("Values", {}).items():
            os.environ.setdefault(key, str(value))


def _show(label, obj):
    if obj is None:
        print(f"  {label}: None")
    elif hasattr(obj, "model_dump"):
        print(f"  {label}: {json.dumps(obj.model_dump())}")
    else:
        print(f"  {label}: {obj}")


def main() -> int:
    _load_local_settings()

    from agents.procurement_exception_agent.services import inventory as inventory_service
    from agents.procurement_exception_agent.services import supplier as supplier_service
    from agents.procurement_exception_agent.services import procurement as procurement_service

    item = sys.argv[1] if len(sys.argv) > 1 else "M0001"
    vendor = sys.argv[2] if len(sys.argv) > 2 else "US-101"

    print("=" * 64)
    print(f"  D365 service-layer test (item={item}, vendor={vendor})")
    print("=" * 64)

    print("\n[inventory_service]")
    _show("get_inventory", inventory_service.get_inventory(item))
    _show("get_safety_stock", inventory_service.get_safety_stock(item))
    inv_list = inventory_service.list_inventory()
    print(f"  list_inventory: {len(inv_list)} item(s); sample: "
          + json.dumps([i.model_dump() for i in inv_list[:3]]))

    print("\n[supplier_service]")
    _show("get_supplier_performance", supplier_service.get_supplier_performance(vendor))
    approved = supplier_service.get_approved_suppliers()
    print(f"  get_approved_suppliers: {len(approved)} supplier(s); sample: "
          + json.dumps([s.model_dump() for s in approved[:3]]))

    print("\n[procurement_service]")
    pos = procurement_service.get_open_purchase_orders(item)
    print(f"  get_open_purchase_orders: {len(pos)} PO(s); sample: "
          + json.dumps([p.model_dump() for p in pos[:3]]))
    _show("get_supplier_prices", procurement_service.get_supplier_prices(vendor, item))
    _show("get_lead_time_data", procurement_service.get_lead_time_data(vendor, item))

    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
