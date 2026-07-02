export default function ValidationPanel({ validation }) {
  const ok = validation.is_valid && validation.rule_violations.length === 0;

  return (
    <div className={`validation-panel ${ok ? "ok" : "warn"}`}>
      <div className="validation-head">
        <span className="validation-icon">{ok ? "✓" : "!"}</span>
        <strong>
          {ok
            ? "Output validation passed — schema, ranking and tenant rules"
            : "Validation flagged items — rules engine adjustments applied"}
        </strong>
      </div>

      {validation.schema_errors.length > 0 && (
        <ul className="validation-list">
          {validation.schema_errors.map((e, i) => (
            <li key={`s${i}`} className="schema-error">
              {e}
            </li>
          ))}
        </ul>
      )}

      {validation.rule_violations.length > 0 && (
        <ul className="validation-list">
          {validation.rule_violations.map((v, i) => (
            <li key={`r${i}`}>
              <code>{v.rule}</code> on rank {v.recommendation_rank}: {v.detail}{" "}
              <em>({v.action_taken})</em>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
