import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from agents.procurement_exception_agent.models import PurchaseOrder
from agents.procurement_exception_agent.services.procurement.procurement_service import (
    _is_overdue,
)


class ProcurementServiceOverdueTests(unittest.TestCase):
    def test_unreceived_past_due_line_is_overdue(self):
        po = PurchaseOrder(
            po_id="PO-OVERDUE",
            item_id="ITEM001",
            supplier_id="SUP001",
            qty_ordered=10,
            qty_outstanding=10,
            status="Invoiced",
            expected_delivery_date="2000-01-01",
            product_receipt_date=None,
        )

        self.assertTrue(_is_overdue(po))

    def test_received_invoiced_line_is_not_overdue(self):
        po = PurchaseOrder(
            po_id="PO-RECEIVED",
            item_id="ITEM001",
            supplier_id="SUP001",
            qty_ordered=10,
            qty_outstanding=0,
            status="Invoiced",
            expected_delivery_date="2000-01-01",
            product_receipt_date="2000-01-02",
        )

        self.assertFalse(_is_overdue(po))

    def test_received_late_line_is_not_currently_overdue(self):
        po = PurchaseOrder(
            po_id="PO-RECEIVED-LATE",
            item_id="ITEM001",
            supplier_id="SUP001",
            qty_ordered=10,
            qty_outstanding=10,
            status="Invoiced",
            expected_delivery_date="2000-01-01",
            product_receipt_date="2000-01-02",
        )

        self.assertFalse(_is_overdue(po))


if __name__ == "__main__":
    unittest.main()
