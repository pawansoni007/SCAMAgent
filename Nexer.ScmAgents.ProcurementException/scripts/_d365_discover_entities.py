"""
Discover D365 F&O OData entity sets relevant to the procurement agent.

Lists all entity sets exposed by the configured environment and groups the
ones that look relevant to the services we still need to map (inventory
on-hand, safety stock / coverage, lead time, purchase prices, vendors).

Usage (from the project directory):
    .venv\\Scripts\\python.exe scripts\\_d365_discover_entities.py
    .venv\\Scripts\\python.exe scripts\\_d365_discover_entities.py onhand coverage
"""

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

# Keyword buckets -> substrings to match (case-insensitive) in entity set names.
_BUCKETS = {
    "On-hand inventory": ["onhand", "inventsum", "inventoryonhand", "onhandinventory"],
    "Coverage / safety stock / reorder": ["coverage", "safetystock", "reorder", "minmax", "ordersetting"],
    "Lead time": ["leadtime"],
    "Purchase price / trade agreements": ["purchaseprice", "pricediscount", "tradeagreement", "purchprice", "priceagreement"],
    "Vendors": ["vendor"],
    "Inventory (other)": ["inventory", "warehouseonhand"],
    "Released products / items": ["releasedproduct", "inventitem", "productsv2"],
}


def _load_local_settings() -> None:
    if os.environ.get("D365_ODATA_BASE_URL"):
        return
    settings_path = PROJECT_DIR / "local.settings.json"
    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        for key, value in data.get("Values", {}).items():
            os.environ.setdefault(key, str(value))


def main() -> int:
    _load_local_settings()
    from integrations.d365 import D365Config, D365ConfigError, D365ODataClient, D365ODataError

    try:
        config = D365Config.from_env()
    except D365ConfigError as exc:
        print(f"[CONFIG ERROR] {exc}")
        return 2

    print(f"Connecting to {config.base_url} ...")
    client = D365ODataClient(config)
    try:
        names = client.list_entity_sets()
    except D365ODataError as exc:
        print(f"[FAILED] {exc}")
        if exc.body:
            print("Response body:", exc.body[:1000])
        return 1

    print(f"Total entity sets: {len(names)}")
    lower = {n.lower(): n for n in names}

    extra_terms = [a.lower() for a in sys.argv[1:]]
    buckets = dict(_BUCKETS)
    if extra_terms:
        buckets["Custom search (" + ",".join(extra_terms) + ")"] = extra_terms

    print("=" * 64)
    for label, terms in buckets.items():
        matches = sorted(
            {orig for low, orig in lower.items() if any(t in low for t in terms)}
        )
        print(f"\n## {label}  ({len(matches)})")
        for m in matches[:40]:
            print(f"   {m}")
        if len(matches) > 40:
            print(f"   ... +{len(matches) - 40} more")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
