import os
import sys
import unittest
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from agents.procurement_exception_agent.services.risk.procurement_risk_service import (
    RECEIPT_STATUS_CURRENTLY_OVERDUE,
    RECEIPT_STATUS_NO_PLANNED_DATE,
    RECEIPT_STATUS_NOT_YET_DUE,
    RECEIPT_STATUS_RECEIVED_LATE,
    RECEIPT_STATUS_RECEIVED_ON_TIME_OR_EARLY,
    assess_overdue_po_coverage_risk,
    calculate_projected_runout_date,
    calculate_receipt_assessment,
    classify_coverage_risk,
)
from agents.procurement_exception_agent.models import DatedDemandLine
from models.scm_event import RiskLevel


class ReceiptAssessmentTests(unittest.TestCase):
    def test_currently_overdue_when_unreceived_and_planned_date_is_past(self):
        result = calculate_receipt_assessment(
            product_receipt_date=None,
            confirmed_receipt_date="2026-06-01",
            requested_receipt_date="2026-06-03",
            current_date=date(2026, 6, 23),
        )

        self.assertEqual(result.receipt_status, RECEIPT_STATUS_CURRENTLY_OVERDUE)
        self.assertEqual(result.effective_planned_receipt_date, "2026-06-01")
        self.assertEqual(result.comparison_date, "2026-06-23")
        self.assertEqual(result.receipt_variance_days, 22)

    def test_received_late_when_product_receipt_is_after_planned_date(self):
        result = calculate_receipt_assessment(
            product_receipt_date="2026-06-10",
            confirmed_receipt_date="2026-06-01",
            requested_receipt_date="2026-06-03",
            current_date=date(2026, 6, 23),
        )

        self.assertEqual(result.receipt_status, RECEIPT_STATUS_RECEIVED_LATE)
        self.assertEqual(result.receipt_variance_days, 9)

    def test_not_yet_due_when_unreceived_and_planned_date_is_future(self):
        result = calculate_receipt_assessment(
            product_receipt_date=None,
            confirmed_receipt_date=None,
            requested_receipt_date="2026-06-30",
            current_date=date(2026, 6, 23),
        )

        self.assertEqual(result.receipt_status, RECEIPT_STATUS_NOT_YET_DUE)
        self.assertEqual(result.effective_planned_receipt_date, "2026-06-30")
        self.assertEqual(result.receipt_variance_days, -7)

    def test_received_on_time_or_early_when_receipt_is_on_or_before_planned_date(self):
        result = calculate_receipt_assessment(
            product_receipt_date="2026-06-01",
            confirmed_receipt_date=None,
            requested_receipt_date="2026-06-03",
            current_date=date(2026, 6, 23),
        )

        self.assertEqual(result.receipt_status, RECEIPT_STATUS_RECEIVED_ON_TIME_OR_EARLY)
        self.assertEqual(result.comparison_date, "2026-06-01")
        self.assertEqual(result.receipt_variance_days, -2)

    def test_no_planned_receipt_date_when_confirmed_and_requested_are_blank(self):
        result = calculate_receipt_assessment(
            product_receipt_date=None,
            confirmed_receipt_date=None,
            requested_receipt_date=None,
            current_date=date(2026, 6, 23),
        )

        self.assertEqual(result.receipt_status, RECEIPT_STATUS_NO_PLANNED_DATE)
        self.assertIsNone(result.effective_planned_receipt_date)
        self.assertEqual(result.comparison_date, "2026-06-23")
        self.assertIsNone(result.receipt_variance_days)


class CoverageRiskFormulaTests(unittest.TestCase):
    def test_proc01_thresholds_match_documented_rules(self):
        self.assertEqual(classify_coverage_risk(3, 0), RiskLevel.CRITICAL)
        self.assertEqual(classify_coverage_risk(7, 0), RiskLevel.HIGH)
        self.assertEqual(classify_coverage_risk(14, 0), RiskLevel.MEDIUM)
        self.assertEqual(classify_coverage_risk(15, 0), RiskLevel.LOW)
        self.assertEqual(classify_coverage_risk(None, 22), RiskLevel.LOW)

    def test_projected_runout_date_uses_cumulative_dated_demand(self):
        result = calculate_projected_runout_date(
            date(2026, 6, 23),
            100,
            [
                DatedDemandLine(
                    item_id="ITEMX",
                    demand_date="2026-06-25",
                    demand_qty=40,
                    demand_source="sales_order",
                ),
                DatedDemandLine(
                    item_id="ITEMX",
                    demand_date="2026-06-27",
                    demand_qty=70,
                    demand_source="production",
                ),
            ],
        )

        self.assertEqual(result, "2026-06-27")

    def test_assessment_uses_dated_open_demand_for_runout(self):
        result = assess_overdue_po_coverage_risk("ITEM003", tenant_id="test")

        self.assertTrue(result.risk_assessments)
        top = result.risk_assessments[0]
        self.assertEqual(top.open_demand_qty, 170.0)
        self.assertIsNone(top.daily_demand)
        self.assertEqual(top.projected_runout_date, "2026-06-29")
        self.assertEqual(top.risk_level, RiskLevel.CRITICAL)
        self.assertTrue(top.demand_lines)


if __name__ == "__main__":
    unittest.main()
