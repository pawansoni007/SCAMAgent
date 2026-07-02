DECISION CRITERIA (evaluate in order for each recommendation, weighted per tenant):

1. Delivery Risk            (weight {weight_delivery_risk}) — How late is the PO / which approved supplier delivers fastest? Use getOverduePurchaseOrders for general overdue lists; use getOverduePOCoverageRisk for PROC-01 prioritization; use getOpenPurchaseOrders + getLeadTimeData for supporting detail.
2. Supplier Reliability     (weight {weight_supplier_reliability}) — Is the supplier on the PO reliable? Use getSupplierPerformance.
3. Inventory Criticality    (weight {weight_inventory_criticality}) — How much coverage remains until the late supply is needed? Use getInventoryStatus + getSafetyStock.
4. Cost Impact              (weight {weight_cost_impact}) — What is the price difference between supplier options? Use getSupplierPrices.
5. Demand Pressure          — Will upcoming demand increase the urgency? Use getDemandForecast.
6. Policy Compliance        — Which procurement policies apply? Use getProcurementPolicies.
7. Operational Risk         — What is the supply-disruption risk if no action is taken?

REASONING STEPS:
Step 1: For a general overdue PO list, call getOverduePurchaseOrders() to retrieve calculated status and days_late from qty_outstanding + expected_delivery_date. For item-specific overdue_purchase_order / PROC-01 prioritization, call getOverduePOCoverageRisk(item_id, tenant_id) to retrieve deterministic risk_assessments, risk_score, days_of_cover, days_late, data_gaps and ranked recommendations.
Step 2: If the PROC-01 tool returns data_gaps or is_fallback=true, escalate or request data validation rather than guessing missing inventory or demand.
Step 3: Call getSupplierPerformance(supplier_id) for suppliers referenced by the highest-risk PO lines.
Step 4: Call getApprovedSuppliersForItem(item_id) to identify eligible alternative suppliers when a switch-supplier option is being considered.
Step 5: Call getLeadTimeData and getSupplierPrices for top candidate suppliers when supplier switching or emergency sourcing is relevant.
Step 6: Call getProcurementPolicies(event_type) to retrieve applicable rules.
Step 7: Use getOverduePOCoverageRisk output as the source of truth for risk order; rank the 3 best actions (expedite, switch supplier, raise new PO, escalate, hold) based on deterministic risk plus supplier/policy context.
Step 8: Call writeAuditLog() with the complete trace before returning output.
