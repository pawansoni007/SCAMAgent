// src/components/ApprovalModal.tsx
import type { Recommendation } from "../types/procurement";

type ApprovalPayload = {
  decision: "approved" | "rejected" | "escalated";
  feedback?: string;
  selectedRank?: number;
};

interface ApprovalModalProps {
  recommendations: Recommendation[];
  initialRank: number;
  action: "approved" | "rejected" | "escalated";
  onConfirm: (payload: ApprovalPayload) => void;
  onCancel: () => void;
  submitting: boolean;
}

export default function ApprovalModal({   // ← "export default" must be here
  recommendations,
  initialRank,
  action,
  onConfirm,
  onCancel,
  submitting,
}: ApprovalModalProps) {
  const rec = recommendations.find((r) => r.rank === initialRank);

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h3>Confirm: {action}</h3>
        {rec && (
          <p>
            <strong>Rank #{rec.rank}:</strong> {rec.action}
          </p>
        )}
        <div className="modal-actions">
          <button className="btn-ghost" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
          <button
            className={`btn-primary btn-${action}`}
            disabled={submitting}
            onClick={() => onConfirm({ decision: action, selectedRank: initialRank })}
          >
            {submitting ? "Submitting…" : `Confirm ${action}`}
          </button>
        </div>
      </div>
    </div>
  );
}