"""Factory for deterministic PROC-01 ranked recommendations."""

from agents.procurement_exception_agent.models import (
    ProcurementRiskRecommendation,
    RiskAssessment,
)
from models.scm_event import RecommendationAction, RiskLevel

from .explanation_builder import build_expected_impact, build_recommendation_reason


def generate_proc01_recommendations(
    risk_assessments: list[RiskAssessment],
    data_gaps: list[str],
) -> list[ProcurementRiskRecommendation]:
    """
    Convert ranked risk assessments into up to three deterministic recommendations.

    The factory does not call tools or LLMs. It maps risk levels to allowed action
    enums and uses the risk score order calculated by the risk service.
    """
    if data_gaps and not risk_assessments:
        return []

    recommendations: list[ProcurementRiskRecommendation] = []
    for rank, assessment in enumerate(risk_assessments[:3], start=1):
        action = _action_for_risk(assessment.risk_level)
        recommendations.append(
            ProcurementRiskRecommendation(
                rank=rank,
                action=action,
                risk_level=assessment.risk_level,
                confidence=_confidence_for_risk(assessment.risk_level, data_gaps),
                reason=build_recommendation_reason(
                    assessment.risk_level,
                    assessment.purchase_order_number,
                    assessment.item_number,
                ),
                expected_impact=build_expected_impact(assessment.risk_level),
                policy_constraints=[
                    "PROC-01: Deterministic inventory coverage risk calculation",
                    "Human approval required before ERP action",
                ],
                approval_required=True,
                risk_assessment=assessment,
            )
        )
    return recommendations


def _action_for_risk(risk_level: RiskLevel) -> RecommendationAction:
    if risk_level in {RiskLevel.CRITICAL, RiskLevel.HIGH}:
        return RecommendationAction.EXPEDITE_ORDER
    if risk_level == RiskLevel.MEDIUM:
        return RecommendationAction.HOLD_AND_MONITOR
    return RecommendationAction.HOLD_AND_MONITOR


def _confidence_for_risk(risk_level: RiskLevel, data_gaps: list[str]) -> float:
    if data_gaps:
        return 0.60
    if risk_level == RiskLevel.CRITICAL:
        return 0.92
    if risk_level == RiskLevel.HIGH:
        return 0.86
    if risk_level == RiskLevel.MEDIUM:
        return 0.76
    return 0.68
