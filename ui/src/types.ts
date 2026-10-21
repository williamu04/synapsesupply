// Mirrors src/synapse/contracts.py (the subset the console reads). Keep in sync with docs/contracts.md.

export type CaseStatus =
  | "NEW" | "ANALYZING" | "AWAITING_APPROVAL" | "EXECUTED" | "REJECTED" | "BLOCKED" | "FAILED" | "NO_ACTION_NEEDED";
export type TraceKind =
  | "PLAN" | "TOOL_CALL" | "TOOL_RESULT" | "REASONING" | "POLICY" | "APPROVAL" | "ACTION" | "ERROR" | "DONE";
export type PolicyEffect = "ALLOW" | "ESCALATE" | "DENY";
export type Compliance = "PASS" | "HOLD" | "BLOCK" | "NOT_APPLICABLE";

export const FINAL_STATUSES: ReadonlySet<string> = new Set([
  "EXECUTED", "REJECTED", "BLOCKED", "NO_ACTION_NEEDED", "FAILED",
]);

export interface TraceEvent {
  case_id: string;
  seq: number;
  ts: string;
  kind: TraceKind;
  title: string;
  detail: Record<string, unknown>;
}

export interface RejectedAlternative {
  description: string;
  reason: string;
  compliance_outcome: Compliance | null;
  financial_impact_usd: number | null;
}

export interface ActionProposal {
  action_type: string;
  plant: string;
  material: string;
  quantity: number;
  unit: string;
  delivery_date: string;
  supplier: string | null;
  supplying_plant: string | null;
  financial_impact_usd: number;
  confidence: number;
  compliance_outcome: Compliance | null;
  rationale: string;
  alternatives: RejectedAlternative[];
  option_id: string | null;
}

export interface PolicyDecision {
  effect: PolicyEffect;
  policy_ids: string[];
  reasons: string[];
}

export interface CaseRecord {
  case_id: string;
  process_type: string;
  payload_source: string;
  status: CaseStatus;
  created_at: string;
  updated_at: string;
  plant: string | null;
  material: string | null;
  summary: string;
  proposal: ActionProposal | null;
  policy: PolicyDecision | null;
  approver: string | null;
  sap_document: string | null;
}

export interface ProjectionDay {
  day: string;
  receipts: number;
  closing: number;
  below_safety_stock: boolean;
}

export interface StockAnalysis {
  plant: string;
  material: string;
  unit: string;
  today: string;
  on_hand_unrestricted: number;
  other_stock_not_available: number;
  daily_demand_mean: number;
  safety_stock: number;
  reorder_point: number;
  eoq: number | null;
  projection: ProjectionDay[];
  projected_minimum: number;
  first_breach_day: string | null;
  shortfall: number;
  status: "OK" | "BELOW_SAFETY_STOCK" | "STOCKOUT";
}

export interface SourcingOption {
  option_id: string;
  kind: "PURCHASE_ORDER" | "STOCK_TRANSFER";
  source: string;
  source_name: string;
  earliest_arrival: string;
  arrives_in_time: boolean;
  lead_days: number;
  unit_cost: number;
  incremental_cost_per_unit: number;
  incremental_cost_for_quantity: number;
  max_quantity: number | null;
  covers_quantity: boolean;
  compliance: Compliance;
  compliance_findings: string[];
  // Delivery-risk prediction (purchase orders only): SAP RPT-1, or the empirical fallback
  predicted_delay_days?: number;
  on_time_probability?: number;
  expected_arrival?: string;
  prediction_method?: string;
}

export interface SourcingResult {
  plant: string;
  material: string;
  quantity: number;
  needed_by: string;
  baseline_price: number;
  delay_prediction?: { method: string | null; history_rows: number };
  options: SourcingOption[];
}

export interface PolicyDetail {
  effect: PolicyEffect;
  policy_ids: string[];
  reasons: string[];
  confidence: number;
  financial_impact_usd: number;
  compliance: Compliance;
  option_id: string;
}

export interface Scenario {
  scenario_id: string;
  title: string;
  process_type: string;
  expected: { policy_effect: PolicyEffect };
}
