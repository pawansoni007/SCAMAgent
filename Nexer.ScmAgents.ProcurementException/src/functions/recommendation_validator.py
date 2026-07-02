"""
Recommendation Validator — runtime step 9 (JSON schema + confidence + policy checks).

Validates the structured Top3Response before it reaches the human approver:
  1. Schema validation (already guaranteed by Pydantic parse — re-verified here).
  2. Ranking integrity — ranks must be unique, sequential, starting at 1.
  3. Confidence sanity — all confidences within [0, 1].
  4. Deterministic rules — delegated to the RulesEngine.
"""

from pydantic import BaseModel, Field

from models.scm_event import Top3Response
from services.tenant_config_service import TenantConfig
from .rules_engine import RulesEngine, RuleViolation


class ValidationResult(BaseModel):
    is_valid: bool = Field(..., description="Overall validation outcome")
    schema_errors: list[str] = Field(default_factory=list)
    rule_violations: list[RuleViolation] = Field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return bool(self.schema_errors or self.rule_violations)


class RecommendationValidator:
    """Validates structured agent output before human approval."""

    def __init__(self) -> None:
        self._rules_engine = RulesEngine()

    def validate(self, response: Top3Response, config: TenantConfig) -> ValidationResult:
        schema_errors: list[str] = []

        # Re-run model validation (defence in depth — catches any post-parse mutation)
        try:
            Top3Response.model_validate(response.model_dump())
        except Exception as exc:
            schema_errors.append(f"Schema validation failed: {exc}")

        # Ranking integrity
        ranks = sorted(rec.rank for rec in response.recommendations)
        expected = list(range(1, len(response.recommendations) + 1))
        if ranks != expected:
            schema_errors.append(
                f"Recommendation ranks {ranks} are not sequential starting at 1."
            )

        # Confidence bounds (Pydantic enforces ge/le, but verify aggregate sanity)
        for rec in response.recommendations:
            if not (0.0 <= rec.confidence <= 1.0):
                schema_errors.append(
                    f"Rank {rec.rank}: confidence {rec.confidence} out of bounds."
                )

        # Deterministic tenant rules (mutates response where needed)
        rule_violations = self._rules_engine.apply(response, config)

        return ValidationResult(
            is_valid=not schema_errors,
            schema_errors=schema_errors,
            rule_violations=rule_violations,
        )
