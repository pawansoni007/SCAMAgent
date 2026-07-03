"""Tool-selection regression eval for the buyer chat agent.

Sends canned buyer queries to POST /api/chat with debug enabled and asserts
on which tools the agent actually called (debug.tools_called). Run this
BEFORE and AFTER any prompt or tool-description change; treat a drop in the
pass count as a regression.

Usage:
    python scripts/tool_selection_eval.py                # single pass
    python scripts/tool_selection_eval.py --runs 3       # determinism check
    python scripts/tool_selection_eval.py --url http://127.0.0.1:7071/api/chat
    python scripts/tool_selection_eval.py --filter overdue

Requires the Functions host running locally with working Foundry/D365 access.
Exit code is non-zero when any case fails.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:7071/api/chat"

# writeAuditLog is a governance side-channel, not a routing decision.
IGNORED_TOOLS = {"writeAuditLog"}

# Each case: query plus expectations on the set of tools called.
#   expect_any : at least one of these must be called
#   expect_all : every one of these must be called
#   forbid     : none of these may be called
#   no_tools   : no tool at all may be called (greetings/meta questions)
CASES = [
    # --- Inventory cluster: getInventoryStatus vs listInventoryStatus vs getSafetyStock
    {
        "name": "inventory-single-item",
        "query": "What is the current stock level for item ITEM-100?",
        "expect_any": ["getInventoryStatus"],
        "forbid": ["listInventoryStatus"],
    },
    {
        "name": "inventory-overview",
        "query": "Which items are currently below safety stock?",
        "expect_any": ["listInventoryStatus"],
        "forbid": ["getInventoryStatus"],
    },
    {
        "name": "safety-stock-params",
        "query": "What is the safety stock threshold and reorder point configured for ITEM-100?",
        "expect_any": ["getSafetyStock"],
        "forbid": ["listInventoryStatus"],
    },
    # --- Supplier cluster: getApprovedSuppliers vs getApprovedSuppliersForItem vs getSupplierPerformance
    {
        "name": "suppliers-global-list",
        "query": "Show me the approved vendor list.",
        "expect_any": ["getApprovedSuppliers"],
        "forbid": ["getApprovedSuppliersForItem"],
    },
    {
        "name": "suppliers-for-item",
        "query": "Which suppliers are approved for item ITEM-100?",
        "expect_any": ["getApprovedSuppliersForItem"],
        "forbid": ["getApprovedSuppliers"],
    },
    {
        "name": "suppliers-compare-for-item",
        "query": "Compare the suppliers I could order ITEM-100 from.",
        "expect_any": ["getApprovedSuppliersForItem"],
        "forbid": ["getApprovedSuppliers"],
    },
    {
        "name": "supplier-performance",
        "query": "How reliable is supplier SUP-200? What's their risk rating?",
        "expect_any": ["getSupplierPerformance"],
        "forbid": ["getApprovedSuppliers", "getApprovedSuppliersForItem"],
    },
    # --- Lead time overlap: getLeadTimeData vs getSupplierPerformance
    {
        "name": "lead-time-pair",
        "query": "What is the delivery lead time for item ITEM-100 from supplier SUP-200?",
        "expect_any": ["getLeadTimeData"],
        "forbid": ["getSupplierPerformance"],
    },
    {
        "name": "supplier-prices",
        "query": "What price does supplier SUP-200 charge for ITEM-100?",
        "expect_any": ["getSupplierPrices"],
    },
    # --- PO cluster: getOpenPurchaseOrders vs getOverduePurchaseOrders vs getOverduePOCoverageRisk
    {
        "name": "open-pos-for-item",
        "query": "Are there any open purchase orders for ITEM-100?",
        "expect_any": ["getOpenPurchaseOrders"],
        "forbid": ["getOverduePurchaseOrders", "getOverduePOCoverageRisk"],
    },
    {
        "name": "overdue-pos-list",
        "query": "Which purchase orders are overdue right now?",
        "expect_any": ["getOverduePurchaseOrders"],
        "forbid": ["getOverduePOCoverageRisk", "getOpenPurchaseOrders"],
    },
    {
        "name": "overdue-pos-for-item",
        "query": "List the overdue purchase orders for item ITEM-100.",
        "expect_any": ["getOverduePurchaseOrders"],
        "forbid": ["getOverduePOCoverageRisk"],
    },
    {
        "name": "overdue-prioritization",
        "query": "Which overdue POs for ITEM-100 should I act on first?",
        "expect_any": ["getOverduePOCoverageRisk"],
        "forbid": ["getOpenPurchaseOrders"],
    },
    {
        "name": "coverage-risk",
        "query": "How does inventory coverage look for ITEM-100 given its late deliveries? What's the runout risk?",
        "expect_any": ["getOverduePOCoverageRisk"],
    },
    # --- Forecast / policies
    {
        "name": "demand-forecast",
        "query": "What is the demand forecast for ITEM-100 over the next 30 days?",
        "expect_any": ["getDemandForecast"],
        "forbid": ["getInventoryStatus"],
    },
    {
        "name": "policies",
        "query": "What procurement policies apply to overdue purchase orders?",
        "expect_any": ["getProcurementPolicies"],
    },
    # --- Guardrails
    {
        "name": "greeting-no-tools",
        "query": "Hi! What can you help me with?",
        "no_tools": True,
    },
    {
        "name": "no-po-draft-without-confirmation",
        "query": "Stock is low on ITEM-100, what are my options?",
        "forbid": ["createPurchaseOrderDraft"],
    },
]


def post_chat(url: str, message: str, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps({"message": message, "debug": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read())


def tools_called(response: dict) -> list[str]:
    calls = (response.get("debug") or {}).get("tools_called") or []
    return [
        call.get("name")
        for call in calls
        if call.get("name") and call.get("name") not in IGNORED_TOOLS
    ]


def check_case(case: dict, called: list[str]) -> list[str]:
    """Return a list of failure descriptions (empty = pass)."""
    failures = []
    called_set = set(called)

    if case.get("no_tools") and called:
        failures.append(f"expected no tools, got {called}")

    expect_any = case.get("expect_any")
    if expect_any and not called_set.intersection(expect_any):
        failures.append(f"expected one of {expect_any}, got {called or 'none'}")

    expect_all = case.get("expect_all")
    if expect_all:
        missing = [t for t in expect_all if t not in called_set]
        if missing:
            failures.append(f"missing required tools {missing}, got {called or 'none'}")

    forbidden = called_set.intersection(case.get("forbid", []))
    if forbidden:
        failures.append(f"forbidden tools called: {sorted(forbidden)}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--runs", type=int, default=1,
                        help="repeat each case N times; also flags nondeterminism")
    parser.add_argument("--filter", default="",
                        help="only run cases whose name contains this substring")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    cases = [c for c in CASES if args.filter in c["name"]]
    if not cases:
        print(f"No cases match filter {args.filter!r}")
        return 2

    passed = failed = 0
    for case in cases:
        runs: list[list[str]] = []
        case_failures: list[str] = []

        for run_idx in range(args.runs):
            try:
                response = post_chat(args.url, case["query"], args.timeout)
            except (urllib.error.URLError, OSError) as exc:
                print(f"FAIL  {case['name']}: request error: {exc}")
                print("      Is the Functions host running? "
                      f"(url={args.url})")
                return 2
            called = tools_called(response)
            runs.append(called)
            for failure in check_case(case, called):
                case_failures.append(f"run {run_idx + 1}: {failure}")

        distinct = {tuple(r) for r in runs}
        if len(distinct) > 1:
            case_failures.append(f"nondeterministic tool choice across runs: {runs}")

        if case_failures:
            failed += 1
            print(f"FAIL  {case['name']}  ({case['query']!r})")
            for failure in case_failures:
                print(f"      {failure}")
        else:
            passed += 1
            print(f"pass  {case['name']}  tools={runs[0] or 'none'}")

    print(f"\n{passed}/{passed + failed} cases passed"
          f" ({args.runs} run(s) per case)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
