import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import type {
  AuditEntry,
  EventType,
  ExceptionHistoryRecord,
  Severity,
} from "../types/procurement";

const PAGE_SIZE = 10;

const STATUS_OPTIONS = ["all", "approved", "rejected", "escalated"] as const;
const EVENT_TYPE_OPTIONS: Array<"all" | EventType> = [
  "all",
  "overdue_purchase_order",
  "stockout_risk",
  "supplier_delay",
  "procurement_exception",
  "blocked_purchase_order",
  "demand_spike",
  "supplier_risk_alert",
  "lead_time_deviation",
  "critical_item_shortage",
];

type StatusFilter = (typeof STATUS_OPTIONS)[number];

function severityClass(s: Severity) {
  return s === "high" ? "badge-high" : s === "medium" ? "badge-medium" : "badge-low";
}

function statusClass(s: string) {
  if (s === "approved") return "badge-approved";
  if (s === "rejected") return "badge-rejected";
  if (s === "escalated") return "badge-escalated";
  return "badge-pending";
}

function auditActionClass(a: string) {
  if (a === "approved") return "audit-approved";
  if (a === "rejected") return "audit-rejected";
  if (a === "escalated") return "audit-escalated";
  if (a === "created") return "audit-created";
  return "audit-default";
}

function AuditTrail({ entries }: { entries: AuditEntry[] }) {
  return (
    <div className="audit-trail">
      {entries.map((entry) => (
        <div key={entry.id} className={`audit-entry ${auditActionClass(entry.action)}`}>
          <div className="audit-entry-head">
            <span className={`audit-action-badge ${auditActionClass(entry.action)}`}>
              {entry.action}
            </span>
            <span className="audit-by">{entry.performed_by}</span>
            <span className="audit-time">
              {new Date(entry.performed_at).toLocaleString()}
            </span>
          </div>
          {entry.notes && <p className="audit-notes">{entry.notes}</p>}
          {entry.selected_rank !== undefined && (
            <p className="audit-notes">Selected recommendation #{entry.selected_rank}</p>
          )}
        </div>
      ))}
    </div>
  );
}

function HistoryRow({
  record,
  expanded,
  onToggle,
}: {
  record: ExceptionHistoryRecord;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <tr
      className={`history-row ${expanded ? "history-row-expanded" : ""}`}
      onClick={onToggle}
      style={{ cursor: "pointer" }}
    >
      <td className="cell-bold">{record.item_id}</td>
      <td>{record.plant}</td>
      <td>{record.tenant_id}</td>
      <td>{record.event_type.replace(/_/g, " ")}</td>
      <td>
        <span className={`badge ${severityClass(record.severity)}`}>
          {record.severity}
        </span>
      </td>
      <td>
        <span className={`badge ${statusClass(record.final_status)}`}>
          {record.final_status}
        </span>
      </td>
      <td>{new Date(record.created_at).toLocaleDateString()}</td>
      <td>{record.resolved_at ? new Date(record.resolved_at).toLocaleDateString() : "-"}</td>
      <td className="expand-cell">{expanded ? "▲" : "▼"}</td>
    </tr>
  );
}

export default function HistoryPage() {
  const [records, setRecords] = useState<ExceptionHistoryRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<StatusFilter>("all");
  const [filterEventType, setFilterEventType] = useState<"all" | EventType>("all");
  const [filterTenant, setFilterTenant] = useState("all");
  const [filterDateFrom, setFilterDateFrom] = useState<string>("");
  const [filterDateTo, setFilterDateTo] = useState<string>("");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getExceptionHistory();
      setRecords(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const tenants = ["all", ...Array.from(new Set(records.map((r) => r.tenant_id)))];

  const filtered = records.filter((rec) => {
    if (filterStatus !== "all" && rec.final_status !== filterStatus) return false;
    if (filterEventType !== "all" && rec.event_type !== filterEventType) return false;
    if (filterTenant !== "all" && rec.tenant_id !== filterTenant) return false;
    const createdAt = new Date(rec.created_at);
    if (filterDateFrom) {
      const from = new Date(filterDateFrom);
      from.setHours(0, 0, 0, 0);
      if (createdAt < from) return false;
    }
    if (filterDateTo) {
      const to = new Date(filterDateTo);
      to.setHours(23, 59, 59, 999);
      if (createdAt > to) return false;
    }
    if (search) {
      const q = search.toLowerCase();
      if (
        !rec.item_id.toLowerCase().includes(q) &&
        !rec.plant.toLowerCase().includes(q) &&
        !rec.tenant_id.toLowerCase().includes(q)
      )
        return false;
    }
    return true;
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const selectedRecord = records.find((r) => r.id === expandedId);

  const summary = {
    total: records.length,
    approved: records.filter((r) => r.final_status === "approved").length,
    rejected: records.filter((r) => r.final_status === "rejected").length,
    escalated: records.filter((r) => r.final_status === "escalated").length,
  };

  function resetFilters() {
    setFilterStatus("all");
    setFilterEventType("all");
    setFilterTenant("all");
    setFilterDateFrom("");
    setFilterDateTo("");
    setSearch("");
    setPage(1);
  }

  function toggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  function exportCsv() {
    const headers = ["Item", "Plant", "Tenant", "Event Type", "Severity", "Status", "Created", "Resolved"];
    const rows = filtered.map((r) => [
      r.item_id,
      r.plant,
      r.tenant_id,
      r.event_type,
      r.severity,
      r.final_status,
      new Date(r.created_at).toLocaleDateString(),
      r.resolved_at ? new Date(r.resolved_at).toLocaleDateString() : "-",
    ]);
    const csv = [headers, ...rows].map((row) => row.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `procurement-history-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="inbox-page">
      {/* Summary widgets */}
      <div className="dashboard-widgets">
        <div className="widget">
          <span className="widget-value">{summary.total}</span>
          <span className="widget-label">Total resolved</span>
        </div>
        <div className="widget widget-success">
          <span className="widget-value">{summary.approved}</span>
          <span className="widget-label">Approved</span>
        </div>
        <div className="widget widget-danger">
          <span className="widget-value">{summary.rejected}</span>
          <span className="widget-label">Rejected</span>
        </div>
        <div className="widget widget-warn">
          <span className="widget-value">{summary.escalated}</span>
          <span className="widget-label">Escalated</span>
        </div>
      </div>

      {/* Filters */}
      <div className="inbox-filters">
        <input
          className="filter-search"
          type="text"
          placeholder="Search item, plant, tenant…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        />
        <select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value as StatusFilter); setPage(1); }}>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s === "all" ? "All statuses" : s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>
        <select value={filterEventType} onChange={(e) => { setFilterEventType(e.target.value as "all" | EventType); setPage(1); }}>
          {EVENT_TYPE_OPTIONS.map((t) => (
            <option key={t} value={t}>{t === "all" ? "All event types" : t.replace(/_/g, " ")}</option>
          ))}
        </select>
        <select value={filterTenant} onChange={(e) => { setFilterTenant(e.target.value); setPage(1); }}>
          {tenants.map((t) => (
            <option key={t} value={t}>{t === "all" ? "All tenants" : t}</option>
          ))}
        </select>
        <div className="date-field">
          <span className="date-label">From</span>
          <div className="date-input-wrap">
            <input
              type="date"
              className="date-input"
              value={filterDateFrom}
              onChange={(e) => { setFilterDateFrom(e.target.value); setPage(1); }}
            />
          </div>
        </div>
        <div className="date-field">
          <span className="date-label">To</span>
          <div className="date-input-wrap">
            <input
              type="date"
              className="date-input"
              value={filterDateTo}
              onChange={(e) => { setFilterDateTo(e.target.value); setPage(1); }}
            />
          </div>
        </div>
        <button className="btn-ghost" onClick={resetFilters}>Reset</button>
        <button className="btn-ghost" onClick={() => void load()}>⟳ Refresh</button>
        <button className="btn-ghost" onClick={exportCsv}>↓ Export CSV</button>
      </div>

      {/* States */}
      {loading && (
        <div className="inbox-loading">
          <div className="spinner" /> Loading history…
        </div>
      )}

      {error && (
        <div className="inbox-error">
          ⚠ {error}
          <button className="btn-ghost" onClick={() => void load()}>Retry</button>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="inbox-empty">
          <p>No resolved exceptions match your filters.</p>
          <button className="btn-ghost" onClick={resetFilters}>Clear filters</button>
        </div>
      )}

      {!loading && !error && filtered.length > 0 && (
        <>
          <div className="inbox-table-wrap">
            <table className="inbox-table">
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Plant</th>
                  <th>Tenant</th>
                  <th>Event type</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Resolved</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {paginated.map((rec) => (
                  <HistoryRow
                    key={rec.id}
                    record={rec}
                    expanded={expandedId === rec.id}
                    onToggle={() => toggleExpand(rec.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="inbox-pagination">
            <span className="pagination-info">
              Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}
            </span>
            <div className="pagination-controls">
              <button disabled={page === 1} onClick={() => setPage(1)}>«</button>
              <button disabled={page === 1} onClick={() => setPage((p) => p - 1)}>‹</button>
              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter((p) => p === 1 || p === totalPages || Math.abs(p - page) <= 1)
                .map((p, idx, arr) => (
                  <>
                    {idx > 0 && arr[idx - 1] !== p - 1 && (
                      <span key={`gap-${p}`} className="pagination-gap">…</span>
                    )}
                    <button key={p} className={page === p ? "active" : ""} onClick={() => setPage(p)}>{p}</button>
                  </>
                ))}
              <button disabled={page === totalPages} onClick={() => setPage((p) => p + 1)}>›</button>
              <button disabled={page === totalPages} onClick={() => setPage(totalPages)}>»</button>
            </div>
          </div>

          {selectedRecord && (
            <div className="history-side-panel">
              <div className="history-side-header">
                <div>
                  <h3>{selectedRecord.item_id}</h3>
                  <p>
                    {selectedRecord.event_type
                      ? selectedRecord.event_type.replace(/_/g, " ")
                      : "-"}
                  </p>
                </div>
                <button
                  className="btn-ghost"
                  onClick={() => setExpandedId(null)}
                >
                  Close
                </button>
              </div>

              <div className="history-side-content">
                <div className="detail-section">
                  <h4>Status</h4>
                  <span className={`badge ${statusClass(selectedRecord.final_status || "pending")}`}>
                    {selectedRecord.final_status || "-"}
                  </span>
                </div>

                <div className="detail-section">
                  <h4>Summary</h4>
                  <p>
                    {"summary" in selectedRecord
                      ? selectedRecord.summary || "No summary available"
                      : "No summary available"}
                  </p>
                </div>

                {"selected_action" in selectedRecord && selectedRecord.selected_action && (
                  <div className="detail-section">
                    <h4>Selected action</h4>
                    <p>{selectedRecord.selected_action}</p>
                  </div>
                )}

                {"rules_applied" in selectedRecord &&
                  Array.isArray(selectedRecord.rules_applied) &&
                  selectedRecord.rules_applied.length > 0 && (
                    <div className="detail-section">
                      <h4>Rules applied</h4>
                      <div className="rules-list">
                        {selectedRecord.rules_applied.map((rule: string) => (
                          <span key={rule} className="chip">{rule}</span>
                        ))}
                      </div>
                    </div>
                  )}

                <div className="detail-section">
                  <h4>Audit trail</h4>
                  {"audit_trail" in selectedRecord &&
                  Array.isArray(selectedRecord.audit_trail) &&
                  selectedRecord.audit_trail.length > 0 ? (
                    <AuditTrail entries={selectedRecord.audit_trail} />
                  ) : (
                    <p>No audit entries</p>
                  )}
                </div>

                <div className="detail-section">
                  <button className="btn-ghost" onClick={() => window.print()}>
                    Print / Save PDF
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}