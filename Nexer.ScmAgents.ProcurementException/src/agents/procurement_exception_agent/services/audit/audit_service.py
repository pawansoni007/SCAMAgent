"""
Audit Service — mock implementation.

Represents writes to the Audit Log (Cosmos DB / Azure SQL).
Every agent run must call writeAuditLog() to store the reasoning
and decision trace as per the blueprint's auditability requirements.

In production this would write to Cosmos DB or Azure SQL with
the full audit schema defined in the Agent Design Contract.
"""

from agents.procurement_exception_agent.models import AuditLogEntry


_AUDIT_LOG: list[dict] = []


def write_audit_log(entry: AuditLogEntry) -> str:
    """
    Write an audit log entry for a completed agent reasoning run.

    Stores the full decision trace including tools called, rules applied,
    number of recommendations generated, and human approval requirement.

    Args:
        entry: AuditLogEntry containing the full reasoning trace.

    Returns:
        Confirmation string with the execution_id that was logged.
    """
    record = entry.model_dump()
    _AUDIT_LOG.append(record)

    print(f"[AUDIT] {entry.timestamp} | {entry.execution_id} | "
          f"tenant={entry.tenant_id} | item={entry.item_id} | "
          f"event={entry.event_type} | tools={entry.tools_called} | "
          f"recommendations={entry.recommendations_generated}")

    return f"Audit log entry written. execution_id={entry.execution_id}"


def get_audit_log() -> list[dict]:
    """Return all in-memory audit log entries (for debugging/inspection)."""
    return list(_AUDIT_LOG)
