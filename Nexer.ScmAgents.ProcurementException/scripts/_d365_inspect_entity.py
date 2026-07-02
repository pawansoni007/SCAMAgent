"""
Inspect D365 F&O OData entities: print the field names from one sample row.

Helps map our domain models to the correct entity fields.

Usage (from the project directory):
    .venv\\Scripts\\python.exe scripts\\_d365_inspect_entity.py InventoryOnHandForAI ItemCoverageSettingsV2
"""

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

# Default candidate entities to inspect when none are passed on the CLI.
_DEFAULTS = [
    "InventoryOnHandForAI",
    "ItemCoverageSettingsV2",
    "ItemCoverageWithDerivedSettingsEntity",
    "ProductSpecificOrderSettingsV3",
    "ProductDefaultOrderSettings",
    "ProductApprovedVendorsForAI",
    "OpenPurchasePriceJournalLinesV2",
    "PurchasePriceAgreements",
    "VendorsV3",
    "ReleasedProductsForAI",
]


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
    from integrations.d365 import D365ODataClient, D365ODataError

    entities = sys.argv[1:] or _DEFAULTS
    client = D365ODataClient()

    for entity in entities:
        print("=" * 70)
        print(entity)
        print("-" * 70)
        row = None
        last = None
        reachable = False
        # Try default company first, then cross-company (master/transactional
        # data often lives in a company other than the SP's default).
        for kwargs in ({"scope_to_company": False}, {"scope_to_company": False, "cross_company": True}):
            try:
                rows = client.query(entity, top=1, **kwargs)
                reachable = True
                if rows:
                    row = rows[0]
                    break
            except D365ODataError as exc:
                last = exc
                continue

        if row:
            for key in sorted(row.keys()):
                if key.startswith("@odata"):
                    continue
                value = row[key]
                preview = json.dumps(value) if not isinstance(value, str) else value
                print(f"   {key} = {str(preview)[:60]}")
        elif reachable:
            print("   (entity reachable but returned 0 rows, even cross-company)")
        else:
            print(f"   [ERROR] {last}")
            if getattr(last, "body", None):
                print("   body:", last.body[:400])
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
