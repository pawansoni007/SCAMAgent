/**
 * PBI 818 – Top 3 recommendation detail view
 *
 * Route: rendered when a user selects an exception from InboxPage.
 * Responsibilities:
 *  - Fetch orchestration status and poll until runtimeStatus reaches a
 *    terminal state or "WaitingForApproval".
 *  - Render RecommendationCard (rank, action, risk, confidence) ×3.
 *  - Render D365 context sidebar sourced from the exception payload.
 *  - Allow approve / reject / escalate via submitApproval.
 *  - Surface a ValidationPanel for rules applied.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import ApprovalModal from "../components/ApprovalModal";
import RecommendationCard from "../components/RecommendationCard";
import ValidationPanel from "../components/ValidationPanel";
import { api } from "../api.js";
import type {
  HumanApprovalDecision,
  OrchestrationStatus,
  ProcurementException,
  RiskLevel,
  Top3RecommendationsResponse,
} from "../types/procurement";
import { isTop3Output } from "../utils/procurement";

// ── Local types ──
type ApprovalPayload = {
  decision: "approved" | "rejected" | "escalated";
  feedback?: string;
  selectedRank?: number;
};
type ModalDecision = "approved" | "rejected" | "escalated";
type DecisionResult = {
  decision: string;
  next_step: string;
};

// ─── Constants ───────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 2_500;
const POLL_MAX_ATTEMPTS = 72; // 3 minutes
const MAX_RETRIES = 2;

// Terminal statuses at which we stop polling
const TERMINAL_STATUSES = new Set([
  "Completed",
  "Failed",
  "Terminated",
  "WaitingForExternalEvent", // Durable Functions HITL gate
]);

// ─── Types ────────────────────────────────────────────────────────────────────

type PollState =
  | { phase: "idle" }
  | { phase: "polling"; attempt: number }
  | { phase: "ready"; data: Top3RecommendationsResponse }
  | { phase: "error"; message: string };

// ─── Component ────────────────────────────────────────────────────────────────

interface ExceptionDetailPageProps {
  /** The exception record selected from the inbox */
  exception: ProcurementException;
  /** Navigate back to inbox */
  onBack: () => void;
}

export default function ExceptionDetailPage({
  exception,
  onBack,
}: ExceptionDetailPageProps) {
  const [pollState, setPollState] = useState<PollState>({ phase: "idle" });
  const [decisions, setDecisions] = useState<Record<number, DecisionResult>>({});
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalRank, setModalRank] = useState(1);
  const [modalAction, setModalAction] = useState<ModalDecision>("approved");

  const abortRef = useRef(false);        
  
  const retryCountRef = useRef(0);  
  // ── Polling ──────────────────────────────────────────────────────────────

  const startPolling = useCallback(async () => {
    if (!exception.instance_id) {
      setPollState({
        phase: "error",
        message: "No orchestration instance associated with this exception.",
      });
      return;
    }

    abortRef.current = false;
    setPollState({ phase: "polling", attempt: 0 });

    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt++) {
      if (abortRef.current) return;

      try {
       const status: OrchestrationStatus =
  await api.getOrchestrationStatus(exception.instance_id);
        

        // Happy path — output is Top3
        if (status.output && isTop3Output(status.output)) {
          setPollState({
  phase: "ready",
  data: status.output as Top3RecommendationsResponse,
});
          return;
        }

        // Terminal failure
        if (
          status.runtimeStatus === "Failed" ||
          status.runtimeStatus === "Terminated"
        ) {
          const out = status.output as
            | { status?: string; reason?: string; errors?: string[]; error?: string }
            | undefined;

          const msg =
            out?.errors?.join("; ") ??
            out?.reason ??
            out?.error ??
            "Orchestration failed or was terminated.";

          setPollState({ phase: "error", message: msg });
          return;
        }

        // Stop polling if we've reached a terminal or HITL-wait state
        if (status.runtimeStatus && TERMINAL_STATUSES.has(status.runtimeStatus)) {
          if (status.output && isTop3Output(status.output)) {
            setPollState({
  phase: "ready",
  data: status.output as Top3RecommendationsResponse,
});
          } else {
            setPollState({
              phase: "error",
              message: "Workflow is waiting for human approval but no recommendations were found.",
            });
          }
          return;
        }

        
        setPollState({ phase: "polling", attempt });
        await new Promise<void>((resolve) =>
          setTimeout(resolve, POLL_INTERVAL_MS),
        );
       } catch (err) {
  if (abortRef.current) return;
  const msg = err instanceof Error ? err.message : "Status check failed.";
  

  const isGone = msg.includes("404") || msg.includes("gone") || 
                 msg.includes("completed or failed");
  
  setPollState({
    phase: "error",
    message: isGone
      ? "This exception has already been processed. No pending recommendations."
      : msg,
  });
  return;
}
    }

    setPollState({
      phase: "error",
      message: "Timed out waiting for recommendations. Please retry.",
    });
  }, [exception.instance_id]);

  useEffect(() => {
    void startPolling();
    return () => {
      abortRef.current = true;
    };
  }, [startPolling]);

  // ── Approval handlers ─────────────────────────────────────────────────────

  function handleDecide(
    rank: number,
    decision: "approved" | "rejected" | "escalated",
  ) {
    setModalRank(rank);
    setModalAction(decision);
    setModalOpen(true);
  }

  async function handleModalConfirm(payload: ApprovalPayload) {
    if (!exception.instance_id || pollState.phase !== "ready") return;

    const approval: HumanApprovalDecision =
      payload.decision === "approved"
        ? { approved: true, selected_rank: payload.selectedRank ?? modalRank }
        : {
            approved: false,
            feedback: payload.feedback,
          };

    setApprovalLoading(true);
    setApprovalError(null);
    setModalOpen(false);

    try {
      await api.submitApproval(exception.instance_id, approval);
      setDecisions((prev) => ({
        ...prev,
        [modalRank]: {
          decision: payload.decision,
          next_step:
            payload.decision === "approved"
              ? "Purchase order draft created in ERP."
              : payload.decision === "escalated"
                ? "Escalated to procurement manager."
                : "Rejected — no ERP action taken.",
        },
      }));
    } catch (err) {
      setApprovalError(
        err instanceof Error ? err.message : "Approval submission failed.",
      );
    } finally {
      setApprovalLoading(false);
    }
  }

  // ── Derived values ────────────────────────────────────────────────────────

  const recommendations =
    pollState.phase === "ready" ? pollState.data.recommendations : [];

  const overallRisk: RiskLevel = recommendations.some(
    (r) => r.risk_level === "high",
  )
    ? "high"
    : recommendations.some((r) => r.risk_level === "medium")
      ? "medium"
      : "low";

  const validation =
    pollState.phase === "ready"
      ? {
          is_valid: true,
          rules_applied: pollState.data.rules_applied ?? [],
        }
      : null;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="detail-page">
      {/* ── Breadcrumb / back nav ── */}
      <div className="detail-breadcrumb">
        <button className="btn-back" onClick={onBack} aria-label="Back to inbox">
          ‹ Exception inbox
        </button>
        <span className="breadcrumb-sep">/</span>
        <span className="breadcrumb-current">
          {exception.item_id} — {exception.event_type.replace(/_/g, " ")}
        </span>
      </div>

      <div className="detail-layout">
        {/* ── Left: main content ── */}
        <div className="detail-main">
          {/* Exception header card */}
          <ExceptionHeaderCard exception={exception} overallRisk={overallRisk} />

          {/* Poll states */}
          {pollState.phase === "polling" && (
            <PollingIndicator attempt={pollState.attempt} />
          )}

          {pollState.phase === "error" && (
            <div className="detail-error">
              <span className="error-icon">⚠</span>
              <div>
                <strong>Could not load recommendations</strong>
                <p>{pollState.message}</p>
              </div>
              <button
  className="btn-ghost"
  disabled={retryCountRef.current >= MAX_RETRIES}
  onClick={() => {
    if (retryCountRef.current >= MAX_RETRIES) return;
    retryCountRef.current += 1;
    void startPolling();
  }}
>
  {retryCountRef.current >= MAX_RETRIES ? "Max retries reached" : "Retry"}
</button>
            </div>
          )}

          {pollState.phase === "ready" && (
            <>
              {/* Analysis summary */}
              <div className="summary-card">
                <div className="summary-head">
                  <h2>Analysis Summary</h2>
                  <span className={`risk-badge risk-${overallRisk}`}>
                    {overallRisk.toUpperCase()} RISK
                  </span>
                </div>
                <p>{pollState.data.summary}</p>
                <div className="meta-row">
                  <span title={pollState.data.execution_id}>
                    Execution: {pollState.data.execution_id.slice(0, 8)}…
                  </span>
                  <span>
                    Agent: {pollState.data.agent_id} v
                    {pollState.data.agent_version}
                  </span>
                  <span>Event: {pollState.data.event_type}</span>
                </div>
              </div>

              {/* Validation */}
              {validation && <ValidationPanel validation={validation} />}

              {/* Approval-level error banner */}
              {approvalError && (
                <div className="detail-error">
                  <span className="error-icon">⚠</span>
                  <span>{approvalError}</span>
                </div>
              )}

              {approvalLoading && (
                <div className="approval-loading">
                  <div className="spinner spinner-sm" />
                  Submitting decision…
                </div>
              )}

              {/* Recommendation cards */}
              <h2 className="rec-title">
                Top {recommendations.length} Recommendations
                <span className="approval-note">
                  human approval required before any ERP action
                </span>
              </h2>

              <div className="rec-grid">
                {recommendations.map((rec) => (
                  <RecommendationCard
                    key={rec.rank}
                    rec={rec}
                    decision={decisions[rec.rank]}
                    onDecide={handleDecide}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        {/* ── Right: D365 context sidebar ── */}
        <aside className="detail-sidebar">
          <D365ContextSidebar exception={exception} />
        </aside>
      </div>

      {/* ── Approval modal ── */}
      {modalOpen && pollState.phase === "ready" && (
        <ApprovalModal
          recommendations={recommendations}
          initialRank={modalRank}
          action={modalAction}
          onConfirm={handleModalConfirm}
          onCancel={() => setModalOpen(false)}
          submitting={approvalLoading}
        />
      )}
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

/** Header card showing exception metadata with severity / status badges */
function ExceptionHeaderCard({
  exception,
  overallRisk,
}: {
  exception: ProcurementException;
  overallRisk: RiskLevel;
}) {
  return (
    <div className="exception-header-card">
      <div className="ehc-row">
        <div className="ehc-identity">
          <h1 className="ehc-title">
            {exception.event_type.replace(/_/g, " ")}
          </h1>
          <span className="ehc-id">ID: {exception.id}</span>
        </div>
        <div className="ehc-badges">
          <span
            className={`badge ${exception.severity === "high" ? "badge-high" : exception.severity === "medium" ? "badge-medium" : "badge-low"}`}
          >
            {exception.severity}
          </span>
          <span
            className={`badge ${exception.status === "approved" ? "badge-approved" : exception.status === "rejected" ? "badge-rejected" : exception.status === "escalated" ? "badge-escalated" : "badge-pending"}`}
          >
            {exception.status}
          </span>
          <span className={`risk-badge risk-${overallRisk}`}>
            {overallRisk} risk
          </span>
        </div>
      </div>

      <dl className="ehc-meta">
        <div className="ehc-meta-item">
          <dt>Item</dt>
          <dd>{exception.item_id}</dd>
        </div>
        <div className="ehc-meta-item">
          <dt>Plant</dt>
          <dd>{exception.plant}</dd>
        </div>
        <div className="ehc-meta-item">
          <dt>Tenant</dt>
          <dd>{exception.tenant_id}</dd>
        </div>
        <div className="ehc-meta-item">
          <dt>Created</dt>
          <dd>{new Date(exception.created_at).toLocaleString()}</dd>
        </div>
        {exception.instance_id && (
          <div className="ehc-meta-item">
            <dt>Instance</dt>
            <dd className="ehc-instance" title={exception.instance_id}>
              {exception.instance_id.slice(0, 16)}…
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

/** Animated polling indicator with attempt counter */
function PollingIndicator({ attempt }: { attempt: number }) {
  return (
    <div className="polling-panel">
      <div className="spinner" />
      <div className="polling-text">
        <h3>Agents reasoning…</h3>
        <p>
          Orchestrator → Procurement Exception Agent → tools (inventory,
          suppliers, forecast, policies) → rules engine → validation
        </p>
        <span className="polling-attempt">
          Check {attempt + 1} of {POLL_MAX_ATTEMPTS}
        </span>
      </div>
    </div>
  );
}

function D365ContextSidebar({
  exception,
}: {
  exception: ProcurementException;
}) {
  const sections: Array<{
    label: string;
    icon: string;
    rows: Array<{ key: string; value: string | undefined | null }>;
  }> = [
    {
      label: "Item context",
      icon: "📦",
      rows: [
        { key: "Item ID", value: exception.item_id },
        { key: "Plant", value: exception.plant },
        { key: "Tenant", value: exception.tenant_id },
      ],
    },
    {
      label: "Event classification",
      icon: "🔔",
      rows: [
        {
          key: "Type",
          value: exception.event_type.replace(/_/g, " "),
        },
        { key: "Severity", value: exception.severity },
        { key: "Status", value: exception.status },
      ],
    },
    {
      label: "ERP references",
      icon: "🔗",
      rows: [
        { key: "Exception ID", value: exception.id },
        {
          key: "Orchestration",
          value: exception.instance_id
            ? exception.instance_id.slice(0, 20) + "…"
            : undefined,
        },
      ],
    },
    {
      label: "Timeline",
      icon: "🕐",
      rows: [
        {
          key: "Created",
          value: new Date(exception.created_at).toLocaleString(),
        },
        {
          key: "Last updated",
          value: exception.updated_at
            ? new Date(exception.updated_at).toLocaleString()
            : undefined,
        },
      ],
    },
  ];

  return (
    <div className="d365-sidebar">
      <div className="sidebar-header">
        <span className="sidebar-logo">D</span>
        <span className="sidebar-title">Dynamics 365 Context</span>
      </div>

      <p className="sidebar-hint">
        Payload snippets sourced from ERP. Read-only reference for reviewer
        context.
      </p>

      {sections.map((section) => {
        const visibleRows = section.rows.filter(
          (r) => r.value != null && r.value !== "",
        );
        if (visibleRows.length === 0) return null;

        return (
          <div key={section.label} className="sidebar-section">
            <div className="sidebar-section-head">
              <span className="sidebar-section-icon">{section.icon}</span>
              <span className="sidebar-section-label">{section.label}</span>
            </div>
            <dl className="sidebar-dl">
              {visibleRows.map((row) => (
                <div key={row.key} className="sidebar-row">
                  <dt>{row.key}</dt>
                  <dd>{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        );
      })}

      <div className="sidebar-footer">
        <span className="sidebar-source">
          Source: SCM AI Agents · Exception payload
        </span>
      </div>
    </div>
  );
}