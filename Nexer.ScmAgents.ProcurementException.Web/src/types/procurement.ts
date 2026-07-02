export type EventType =
  | "overdue_purchase_order"
  | "stockout_risk"
  | "supplier_delay"
  | "procurement_exception"
  | "demand_spike"
  | "supplier_risk_alert"
  | "lead_time_deviation"
  | "critical_item_shortage"
  | "blocked_purchase_order";

export type Severity = "low" | "medium" | "high" | "critical";
export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface ProcurementExceptionEvent {
  tenant_id: string;
  item_id: string;
  plant: string;
  event_type: EventType;
  severity?: Severity;
  open_po_id?: string | null;
}

export interface Recommendation {
  rank: number;
  action: string;
  supplier_id?: string | null;
  reason: string;
  risk_level: RiskLevel;
  confidence: number;
  policy_constraints?: string[];
  expected_impact: string;
  requires_human_approval: boolean;
}

export interface Top3RecommendationsResponse {
  execution_id: string;
  agent_id: string;
  agent_version: string;
  prompt_package_version: string;
  event_type: string;
  recommendations: Recommendation[];
  summary: string;
  fallback_status?: string | null;
  rules_applied?: string[];
}

export interface HumanApprovalDecision {
  approved: boolean;
  selected_rank?: number;
  feedback?: string;
  modified_action?: string;
}

export interface RunOrchestrationResponse {
  message: string;
  agent_id: string;
  instanceId: string;
  statusQueryGetUri: string;
}

export interface OrchestrationStatus {
  instanceId: string;
  runtimeStatus: string | null;
  workflowStatus?: unknown;
  output?: Top3RecommendationsResponse | { status: string; reason?: string };
}


export interface ProcurementException {
  id: string;
  tenant_id: string;
  item_id: string;
  plant: string;
  event_type: EventType;
  severity: Severity;
  status: "pending" | "approved" | "rejected" | "escalated";
  created_at: string;
  updated_at?: string;
  instance_id?: string;
}



export type AuditAction =
  | "created"
  | "approved"
  | "rejected"
  | "escalated"
  | "viewed"
  | "updated";

export interface AuditEntry {
  id: string;
  action: AuditAction;
  performed_by: string;
  performed_at: string;
  notes?: string;
  selected_rank?: number;
}

export interface ExceptionHistoryRecord {
  id: string;
  tenant_id: string;
  item_id: string;
  plant: string;
  event_type: EventType;
  severity: Severity;

  final_status: "approved" | "rejected" | "escalated";

  created_at: string;
  resolved_at: string;

  instance_id: string;

  selected_action?: string;
  selected_rank?: number;

  summary?: string;

  rules_applied?: string[];

  audit_trail: AuditEntry[];
}