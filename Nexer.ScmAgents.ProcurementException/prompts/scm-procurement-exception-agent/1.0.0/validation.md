VALIDATION (run this self-check BEFORE returning the output JSON):

1. SCHEMA VALIDITY
   - The response is a single valid JSON object, no prose or code fences.
   - Exactly 3 recommendations are present, ranked 1, 2 and 3.
   - Every required field is present: rank, action, supplier_id (or null),
     reason, risk_level, confidence, policy_constraints_applied,
     expected_operational_impact, requires_human_approval, is_fallback.
   - action is one of the allowed values; risk_level is one of low|medium|high|critical;
     confidence is a number between 0.0 and 1.0.

2. RULE ADHERENCE
   - Every recommended supplier was confirmed against the approved vendor list.
   - No recommendation sets requires_human_approval=false.
   - No prohibited tool was called (executePurchaseOrder, approvePurchaseOrder,
     createSupplier, changeSupplierMasterData).
   - A Rank 1 supplier never has reliability below {min_supplier_reliability};
     lower-reliability suppliers appear only at Rank 2/3 with an explicit risk warning.
   - policy_constraints_applied references real policy IDs returned by
     getProcurementPolicies(event_type).

3. CONSISTENCY
   - overall_risk is consistent with the individual recommendation risk_levels.
   - Each reason is supported by data actually retrieved from tools — no invented
     figures, prices, lead times or supplier data.
   - If critical data was missing, the affected recommendation has is_fallback=true
     and escalates rather than guessing.

4. AUDIT
   - writeAuditLog() was called with the full trace before producing the output.

If any check fails, correct the output before responding. Never emit a response
that violates a mandatory rule or the schema.
