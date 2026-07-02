OUTPUT FORMAT:
You MUST respond with a single valid JSON object. No text before or after the JSON.

{
  "recommendations": [
    {
      "rank": 1,
      "action": "<one of: expedite_order | switch_supplier | raise_purchase_order | escalate_to_manager | hold_and_monitor | request_data_validation>",
      "supplier_id": "<supplier_id or null>",
      "reason": "<clear business reason explaining why this action is recommended>",
      "risk_level": "<low | medium | high | critical>",
      "confidence": 0.0,
      "policy_constraints_applied": ["<policy_id: policy title>"],
      "expected_operational_impact": "<expected impact on operations if action is taken>",
      "requires_human_approval": true,
      "is_fallback": false
    },
    { "rank": 2 },
    { "rank": 3 }
  ],
  "overall_risk": "<low | medium | high | critical>",
  "summary": "<2-3 sentence summary of the situation and the analysis performed>"
}
