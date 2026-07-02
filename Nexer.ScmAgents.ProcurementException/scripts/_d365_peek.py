"""
Peek at specific fields of a company-scoped D365 entity query.

Usage:
    .venv\\Scripts\\python.exe scripts\\_d365_peek.py <Entity> <field1,field2,...> [top]
Example:
    .venv\\Scripts\\python.exe scripts\\_d365_peek.py PurchasePriceAgreements VendorAccountNumber,ItemNumber,Price,PriceCurrencyCode,ProcurementLeadTimeDays 15
"""

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))


def _load_local_settings() -> None:
    if os.environ.get("D365_ODATA_BASE_URL"):
        return
    p = PROJECT_DIR / "local.settings.json"
    if p.exists():
        for k, v in json.loads(p.read_text(encoding="utf-8")).get("Values", {}).items():
            os.environ.setdefault(k, str(v))


def main() -> int:
    _load_local_settings()
    from integrations.d365 import D365ODataClient

    entity = sys.argv[1] if len(sys.argv) > 1 else "PurchasePriceAgreements"
    fields = (sys.argv[2].split(",") if len(sys.argv) > 2 else None)
    top = int(sys.argv[3]) if len(sys.argv) > 3 else 15

    client = D365ODataClient()
    rows = client.query(entity, select=fields, top=top)
    print(f"{entity}: {len(rows)} row(s) (company-scoped)")
    for r in rows:
        if fields:
            print({f: r.get(f) for f in fields})
        else:
            print(json.dumps(r)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
