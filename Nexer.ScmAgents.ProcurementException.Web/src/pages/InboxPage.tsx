import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import type {
  EventType,
  ProcurementException,
  Severity,
} from "../types/procurement";

const PAGE_SIZE = 10;

const STATUS_OPTIONS = [
  "all",
  "pending",
  "approved",
  "rejected",
  "escalated",
] as const;

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
  return s === "high"
    ? "badge-high"
    : s === "medium"
      ? "badge-medium"
      : "badge-low";
}

function statusClass(s: string) {
  if (s === "approved") return "badge-approved";
  if (s === "rejected") return "badge-rejected";
  if (s === "escalated") return "badge-escalated";
  return "badge-pending";
}

// ─── Component ────────────────────────────────────────────────────────────────

interface InboxPageProps {
  /** Called when the user clicks a row — App navigates to ExceptionDetailPage */
  onSelectException: (exception: ProcurementException) => void;
}

export default function InboxPage({ onSelectException }: InboxPageProps) {
  const [exceptions, setExceptions] = useState<ProcurementException[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const [filterStatus, setFilterStatus] = useState<StatusFilter>("all");
  const [filterEventType, setFilterEventType] = useState<"all" | EventType>(
    "all",
  );
  const [filterTenant, setFilterTenant] = useState("all");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getExceptions();
      setExceptions(data);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load exceptions",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const tenants = [
    "all",
    ...Array.from(new Set(exceptions.map((e) => e.tenant_id))),
  ];

  const filtered = exceptions.filter((ex) => {
    if (filterStatus !== "all" && ex.status !== filterStatus) return false;
    if (filterEventType !== "all" && ex.event_type !== filterEventType)
      return false;
    if (filterTenant !== "all" && ex.tenant_id !== filterTenant) return false;
    if (filterDateFrom && new Date(ex.created_at) < new Date(filterDateFrom))
      return false;
    if (filterDateTo && new Date(ex.created_at) > new Date(filterDateTo))
      return false;
    if (search) {
  const q = search.toLowerCase();
  if (
    !(ex.item_id ?? "").toLowerCase().includes(q) &&
    !(ex.plant ?? "").toLowerCase().includes(q) &&
    !(ex.tenant_id ?? "").toLowerCase().includes(q)
  )
    return false;
}
    return true;
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = filtered.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE,
  );

  const summary = {
    total: exceptions.length,
    pending: exceptions.filter((e) => e.status === "pending").length,
    approved: exceptions.filter((e) => e.status === "approved").length,
    rejected: exceptions.filter((e) => e.status === "rejected").length,
    high: exceptions.filter((e) => e.severity === "high").length,
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

  return (
    <div className="inbox-page">
      {/* ── Dashboard widgets ── */}
      <div className="dashboard-widgets">
        <div className="widget">
          <span className="widget-value">{summary.total}</span>
          <span className="widget-label">Total exceptions</span>
        </div>
        <div className="widget widget-warn">
          <span className="widget-value">{summary.pending}</span>
          <span className="widget-label">Awaiting approval</span>
        </div>
        <div className="widget widget-success">
          <span className="widget-value">{summary.approved}</span>
          <span className="widget-label">Approved</span>
        </div>
        <div className="widget widget-danger">
          <span className="widget-value">{summary.rejected}</span>
          <span className="widget-label">Rejected</span>
        </div>
        <div className="widget widget-high">
          <span className="widget-value">{summary.high}</span>
          <span className="widget-label">High severity</span>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className="inbox-filters">
        <input
          className="filter-search"
          type="text"
          placeholder="Search item, plant, tenant…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
        <select
          value={filterStatus}
          onChange={(e) => {
            setFilterStatus(e.target.value as StatusFilter);
            setPage(1);
          }}
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s === "all"
                ? "All statuses"
                : s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
        <select
          value={filterEventType}
          onChange={(e) => {
            setFilterEventType(e.target.value as "all" | EventType);
            setPage(1);
          }}
        >
          {EVENT_TYPE_OPTIONS.map((t) => (
            <option key={t} value={t}>
              {t === "all" ? "All event types" : t.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <select
          value={filterTenant}
          onChange={(e) => {
            setFilterTenant(e.target.value);
            setPage(1);
          }}
        >
          {tenants.map((t) => (
            <option key={t} value={t}>
              {t === "all" ? "All tenants" : t}
            </option>
          ))}
        </select>
        <div className="date-field">
          <span className="date-label">From</span>
          <div className="date-input-wrap">
            <input
              type="date"
              className="date-input"
              value={filterDateFrom}
              onChange={(e) => {
                setFilterDateFrom(e.target.value);
                setPage(1);
              }}
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
              onChange={(e) => {
                setFilterDateTo(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>
        <button className="btn-ghost" onClick={resetFilters}>
          Reset
        </button>
        <button className="btn-ghost" onClick={() => void load()}>
          ⟳ Refresh
        </button>
      </div>

      {/* ── States ── */}
      {loading && (
        <div className="inbox-loading">
          <div className="spinner" /> Loading exceptions…
        </div>
      )}

      {error && (
        <div className="inbox-error">
          ⚠ {error}
          <button className="btn-ghost" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="inbox-empty">
          <p>No exceptions match your filters.</p>
          <button className="btn-ghost" onClick={resetFilters}>
            Clear filters
          </button>
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
                  <th aria-label="Open detail" />
                </tr>
              </thead>
              <tbody>
                {paginated.map((ex) => (
                  <tr
                    key={ex.id}
                    className="inbox-row inbox-row-clickable"
                    onClick={() => onSelectException(ex)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelectException(ex);
                      }
                    }}
                    tabIndex={0}
                    role="button"
                    aria-label={`Open exception ${ex.item_id}`}
                  >
                    <td className="cell-bold">{ex.item_id}</td>
                    <td>{ex.plant}</td>
                    <td>{ex.tenant_id}</td>
                    <td>{ex.event_type.replace(/_/g, " ")}</td>
                    <td>
                      <span className={`badge ${severityClass(ex.severity)}`}>
                        {ex.severity}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${statusClass(ex.status)}`}>
                        {ex.status}
                      </span>
                    </td>
                    <td>
                      {ex.created_at
  ? new Date(ex.created_at).toLocaleString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  : "—"}

                    </td>
                    <td className="cell-chevron" aria-hidden="true">
                      ›
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* ── Pagination ── */}
          <div className="inbox-pagination">
            <span className="pagination-info">
              Showing {(page - 1) * PAGE_SIZE + 1}–
              {Math.min(page * PAGE_SIZE, filtered.length)} of{" "}
              {filtered.length}
            </span>
            <div className="pagination-controls">
              <button disabled={page === 1} onClick={() => setPage(1)}>
                «
              </button>
              <button
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                ‹
              </button>
              {Array.from({ length: totalPages }, (_, i) => i + 1)
  .filter(
    (p) =>
      p === 1 ||
      p === totalPages ||
      Math.abs(p - page) <= 1,
  )
  .map((p, idx, arr) => (
    <Fragment key={p}>
      {idx > 0 && arr[idx - 1] !== p - 1 && (
        <span className="pagination-gap">…</span>
      )}
      <button
        className={page === p ? "active" : ""}
        onClick={() => setPage(p)}
      >
        {p}
      </button>
    </Fragment>
  ))}
                      
              <button
                disabled={page === totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                ›
              </button>
              <button
                disabled={page === totalPages}
                onClick={() => setPage(totalPages)}
              >
                »
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}