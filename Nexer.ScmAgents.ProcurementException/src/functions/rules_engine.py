"""
Rules Engine — runtime step 7 (deterministic policy validation).

Applies tenant-specific deterministic rules to the agent's recommendations
AFTER LLM reasoning. The LLM may not override these rules (Design Contract:
"The agent may not override deterministic rules").

Checks implemented:
  - approved_suppliers_only  : recommended suppliers must be on the approved list
  - min_supplier_reliability : Rank 1 supplier must meet the tenant threshold
  - low_confidence_threshold : low-confidence recommendations force escalation
  - always_requires_human_approval : enforced on every recommendation
"""

from pydantic import BaseModel, Field

from models.scm_event import Top3Response, RiskLevel
from services.tenant_config_service import TenantConfig
from agents.procurement_exception_agent.services.supplier import (
    get_supplier_performance,
)


class RuleViolation(BaseModel):
    rule: str = Field(..., description="Rule identifier that was violated")
    recommendation_rank: int = Field(..., description="Rank of the affected recommendation")
    detail: str = Field(..., description="Human-readable violation detail")
    action_taken: str = Field(..., description="What the rules engine did about it")


class RulesEngine:
    """Deterministic post-reasoning rule validation. No LLM involvement."""

    def apply(self, response: Top3Response, config: TenantConfig) -> list[RuleViolation]:
        """
        Validate and adjust a Top3Response against tenant rules in place.

        Returns the list of violations found (empty list = fully compliant).
        Adjustments made:
          - Non-approved supplier → recommendation flagged as fallback + escalated risk.
          - Rank 1 below reliability threshold → confidence reduced, violation logged.
          - Confidence below tenant threshold → human approval enforced (already default).
          - Human approval flag force-set per tenant approval policy.
        """
        violations: list[RuleViolation] = []

        for rec in response.recommendations:
            # Rule: approved suppliers only
            if config.rules.approved_suppliers_only and rec.supplier_id:
                supplier = get_supplier_performance(rec.supplier_id)
                if supplier is None or not supplier.is_approved:
                    violations.append(RuleViolation(
                        rule="approved_suppliers_only",
                        recommendation_rank=rec.rank,
                        detail=(
                            f"Supplier '{rec.supplier_id}' is not on the approved list."
                        ),
                        action_taken="Recommendation flagged as fallback; risk raised to high.",
                    ))
                    rec.is_fallback = True
                    rec.risk_level = RiskLevel.HIGH
                    rec.policy_constraints_applied.append(
                        "rules_engine: approved_suppliers_only violation"
                    )

            # Rule: minimum supplier reliability for Rank 1
            if rec.rank == 1 and rec.supplier_id:
                supplier = get_supplier_performance(rec.supplier_id)
                if supplier and supplier.reliability < config.rules.min_supplier_reliability:
                    violations.append(RuleViolation(
                        rule="min_supplier_reliability",
                        recommendation_rank=rec.rank,
                        detail=(
                            f"Rank 1 supplier '{rec.supplier_id}' reliability "
                            f"{supplier.reliability:.2f} is below tenant threshold "
                            f"{config.rules.min_supplier_reliability:.2f}."
                        ),
                        action_taken="Confidence capped at threshold; violation logged.",
                    ))
                    rec.confidence = min(rec.confidence, config.approval_policy.low_confidence_threshold)
                    rec.policy_constraints_applied.append(
                        "rules_engine: min_supplier_reliability violation"
                    )

            # Rule: low confidence forces escalation
            if rec.confidence < config.approval_policy.low_confidence_threshold:
                rec.requires_human_approval = True
                rec.policy_constraints_applied.append(
                    f"rules_engine: confidence {rec.confidence:.2f} below "
                    f"threshold {config.approval_policy.low_confidence_threshold:.2f} — escalation enforced"
                )

            # Rule: tenant approval policy
            if config.approval_policy.always_requires_human_approval:
                rec.requires_human_approval = True

        if config.approval_policy.always_requires_human_approval:
            response.human_approval_required = True

        return violations
