"""
Smoke test for the D365 F&O OData client.

Verifies that the configured Entra ID service principal can acquire a token
and reach the F&O OData endpoint, then prints a sample of available entity
sets. Optionally queries one entity set if passed as an argument.

Usage (from the project directory):
    .venv\\Scripts\\python.exe scripts\\_d365_smoke_test.py
    .venv\\Scripts\\python.exe scripts\\_d365_smoke_test.py PurchaseOrderHeadersV2

Configuration is read from environment variables; if they are not already set,
they are loaded from local.settings.json (the same file the Functions host
uses locally).
"""

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


def _load_local_settings() -> None:
    """Populate os.environ from local.settings.json if D365 vars are absent."""
    if os.environ.get("D365_ODATA_BASE_URL"):
        return
    settings_path = PROJECT_DIR / "local.settings.json"
    if not settings_path.exists():
        return
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

    print("=" * 64)
    print("  D365 F&O OData connectivity smoke test")
    print("=" * 64)
    print(f"  Base URL    : {config.base_url}")
    print(f"  Company     : {config.data_area_id or '(none / cross-company)'}")
    print(f"  Tenant      : {config.tenant_id}")
    print(f"  Client ID   : {config.client_id}")
    print(f"  Scope       : {config.scope}")
    print("-" * 64)

    client = D365ODataClient(config)

    try:
        print("[1/2] Acquiring token + reading service document ...")
        entity_sets = client.list_entity_sets()
        print(f"      OK — {len(entity_sets)} entity sets available.")
        print("      Sample:", ", ".join(sorted(entity_sets)[:10]) or "(none)")
    except D365ODataError as exc:
        print(f"[FAILED] {exc}")
        if exc.body:
            print("Response body:", exc.body)
        return 1

    if len(sys.argv) > 1:
        entity = sys.argv[1]
        print(f"[2/2] Querying top 3 from '{entity}' ...")
        try:
            rows = client.query(entity, top=3)
            print(f"      OK — {len(rows)} row(s) returned.")
            for row in rows:
                print("      ", json.dumps(row)[:300])
        except D365ODataError as exc:
            print(f"[FAILED] {exc}")
            if exc.body:
                print("Response body:", exc.body)
            return 1
    else:
        print("[2/2] Skipped entity query (pass an entity set name to enable).")

    print("-" * 64)
    print("[SUCCESS] D365 OData connectivity verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
