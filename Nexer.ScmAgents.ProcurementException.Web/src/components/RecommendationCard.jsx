const ACTION_LABELS = {
  expedite_order: "Expedite Order",
  switch_supplier: "Switch Supplier",
  raise_purchase_order: "Raise Purchase Order",
  escalate_to_manager: "Escalate to Manager",
  hold_and_monitor: "Hold & Monitor",
  request_data_validation: "Request Data Validation",
};

export default function RecommendationCard({ rec, decision, onDecide }) {
  const confidencePct = Math.round(rec.confidence * 100);

  return (
    <article className={`rec-card ${rec.rank === 1 ? "rec-primary" : ""}`}>
      <div className="rec-head">
        <span className="rank-pill">#{rec.rank}</span>
        <h3>{ACTION_LABELS[rec.action] || rec.action}</h3>
        <span className={`risk-badge risk-${rec.risk_level}`}>{rec.risk_level}</span>
      </div>

      {rec.supplier_id && <div className="supplier-tag">Supplier: {rec.supplier_id}</div>}

      <p className="rec-reason">{rec.reason}</p>

      <div className="confidence">
        <div className="confidence-label">
          <span>Confidence</span>
          <span>{confidencePct}%</span>
        </div>
        <div className="confidence-track">
          <div
            className={`confidence-fill ${confidencePct >= 75 ? "good" : confidencePct >= 50 ? "mid" : "low"}`}
            style={{ width: `${confidencePct}%` }}
          />
        </div>
      </div>

      <p className="rec-impact">
        <strong>Impact:</strong> {rec.expected_operational_impact}
      </p>

      {rec.policy_constraints_applied.length > 0 && (
        <div className="policy-chips">
          {rec.policy_constraints_applied.map((p, i) => (
            <span key={i} className="chip" title={p}>
              {p.length > 48 ? p.slice(0, 48) + "…" : p}
            </span>
          ))}
        </div>
      )}

      <div className="flags">
        {rec.is_fallback && <span className="flag fallback">fallback</span>}
        {rec.requires_human_approval && <span className="flag approval">needs approval</span>}
      </div>

      {decision ? (
        <div className={`decision-result ${decision.decision}`}>
          <strong>{decision.decision.toUpperCase()}</strong>
          <span>{decision.next_step}</span>
        </div>
      ) : (
        <div className="actions">
          <button className="btn approve" onClick={() => onDecide(rec.rank, "approved")}>
            Approve
          </button>
          <button className="btn reject" onClick={() => onDecide(rec.rank, "rejected")}>
            Reject
          </button>
          <button className="btn escalate" onClick={() => onDecide(rec.rank, "escalated")}>
            Escalate
          </button>
        </div>
      )}
    </article>
  );
}
