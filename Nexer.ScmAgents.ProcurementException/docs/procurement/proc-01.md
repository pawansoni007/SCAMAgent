PROC-01 - Overdue PO Impact Prioritization

Objective:
Rank overdue purchase order lines by inventory coverage risk so buyers can focus
first on the delays most likely to cause stockouts.

Data access rules:
- Use only D365 F&O APIs/data entities or approved application tools.
- Do not use SQL.
- Do not create, update, approve, or submit any D365 transaction.
- Treat getOverduePOCoverageRisk() output as authoritative in chat responses.
- Do not derive overdue status, days of cover, or risk labels with LLM reasoning.

Required D365 facts:
- Purchase order header: PO number, vendor account, order status, buyer group,
  delivery terms.
- Purchase order line: PO number, line number, item, ordered quantity, remaining
  quantity, requested receipt date, confirmed receipt date, site, warehouse,
  line status.
- Product receipt lines: actual product receipt date, received quantity,
  remaining purchase quantity.
- Vendor master: vendor account and vendor name.
- Inventory/on-hand: item, site, warehouse, physical inventory, available
  physical quantity, on-order quantity.
- Inventory dimensions: site, warehouse, inventory dimension ID.
- Demand sources, when available: open sales demand, production component
  demand, transfer demand.

Receipt status formulas:

ComparisonDate =
IF ProductReceiptDate is available
THEN ProductReceiptDate
ELSE CurrentDate

EffectivePlannedReceiptDate =
IF ConfirmedReceiptDate is available
THEN ConfirmedReceiptDate
ELSE RequestedReceiptDate

ReceiptVarianceDays =
IF EffectivePlannedReceiptDate is available
THEN ComparisonDate - EffectivePlannedReceiptDate
ELSE blank

ReceiptStatus =
IF EffectivePlannedReceiptDate is blank
THEN "No planned receipt date"
ELSE IF ReceiptVarianceDays > 0
     THEN IF ProductReceiptDate is blank
          THEN "Currently Overdue"
          ELSE "Received Late"
     ELSE IF ProductReceiptDate is blank
          THEN "Not Yet Due"
          ELSE "Received On Time / Early"

Only include purchase order lines where ReceiptStatus = "Currently Overdue".

Inventory coverage formulas:

Use available physical inventory for immediate coverage.

OpenDemandQty =
OpenSalesDemandQty + OpenProductionConsumptionQty + OpenTransferDemandQty

DemandSet =
- Sales demand: ShippingDateConfirmed and remaining sales quantity where
  TransactionIssueStatus = "On order"
- Production demand: Raw material date and BOM component quantity
- Transfer demand: Ship date and remaining transfer quantity where
  TransactionIssueStatus = "On order"

SortedDemand =
Sort DemandSet by demand date ascending

RunoutDate =
Set CumulativeQty = 0.
For each demand line in SortedDemand:
  CumulativeQty = CumulativeQty + DemandQty
  If CumulativeQty > AvailablePhysicalQty:
    RunoutDate = DemandDate
    Stop

DaysOfCover =
IF RunoutDate is a date
THEN RunoutDate - CurrentDate
ELSE blank

ProjectedRunoutDate = RunoutDate

Risk classification:

RiskLevel =
IF DaysOfCover <= 3
THEN "Critical"
ELSE IF DaysOfCover > 3 AND DaysOfCover <= 7
THEN "High"
ELSE IF DaysOfCover > 7 AND DaysOfCover <= 14
THEN "Medium"
ELSE "Low"

Response guidance:
- Clearly separate ERP facts from calculated insights.
- Do not invent missing D365 data. State missing values as data gaps.
- Sort the prioritized output by highest risk first.

ERP Facts:
- PO Number
- Line
- Vendor
- Item
- Site
- Warehouse
- Requested Receipt Date
- Confirmed Receipt Date
- Available Inventory
- Open Demand, when available

Calculated Insights:
- Receipt Status
- Receipt Variance Days
- Days Late
- Days Of Cover
- Projected Runout Date, when available
- Risk Level
- Explanation