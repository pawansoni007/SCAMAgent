"""Quick smoke test for POST /api/chat (multi-turn)."""
import json
import urllib.request

URL = "http://127.0.0.1:7071/api/chat"


def post(payload: dict) -> dict:
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as res:
        return json.loads(res.read())


print("=== Turn 1: overdue PO question ===")
r1 = post({"message": "Which purchase orders are overdue right now?"})
print("session:", r1["session_id"])
print(r1["reply"])

print()
print("=== Turn 2: follow-up (tests session memory) ===")
r2 = post({
    "message": "For the most critical one, which supplier should I order from?",
    "session_id": r1["session_id"],
})
print(r2["reply"])
