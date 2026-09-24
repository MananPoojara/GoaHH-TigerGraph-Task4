// Types mirroring the FastAPI payloads.
//
// These are hand-maintained rather than generated so the UI depends on a
// narrow, readable contract. The backend is authoritative: if a field here
// disagrees with the API, the API is right.

export type Verdict = 'fraud' | 'legitimate' | 'uncertain';

export type Route = 'auto' | 'L1' | 'L2';

export type CaseStatus =
  | 'open'
  | 'closed_fraud'
  | 'closed_legitimate'
  | 'escalated'
  | 'not_started';

export type EvidenceDirection = 'supports_fraud' | 'supports_legitimate' | 'context';

export type EvidenceSource = 'graph' | 'document' | 'customer' | 'external';

export interface QueueRow {
  case_id: string;
  opened_at: string;
  trigger_type: string;
  trigger_text: string;
  flagged_txn_id: string;
  card_id: string;
  customer_id: string;
  risk_score: number | null;
  investigated: boolean;
  status: CaseStatus;
  verdict: Verdict | null;
  fraud_probability: number | null;
  pattern: string | null;
  exposure_usd: number | null;
  pending_approvals: number;
}

export interface Assessment {
  verdict: Verdict;
  fraud_probability: number;
  pattern: string;
  pattern_description: string;
  confidence: number;
  uncertainty: string;
  independent_signal_count: number;
  conflicting_evidence: boolean;
  rationale: string;
  trigger_risk_score: number | null;
}

export interface AssessmentHistoryEntry {
  stage: string;
  verdict: Verdict;
  fraud_probability: number;
  pattern: string;
}

export interface Hypothesis {
  pattern: string;
  score: number;
  rationale: string;
}

export interface PriorCase {
  case_id: string;
  outcome: string;
  pattern: string;
  link_reason: string;
  structural_score: number;
  analyst_notes: string;
}

export interface EvidenceRequestView {
  request_no: number;
  type: string;
  asked_after_step: number;
  reason: string;
  assumed_response: string;
  simulated: boolean;
}

export interface CaseDetail {
  case_id: string;
  run_id: string;
  status: CaseStatus;
  trigger: {
    type: string;
    text: string;
    flagged_txn_id: string;
    card_id: string;
    customer_id: string;
    opened_at: string;
    risk_score: number | null;
  };
  assessment: Assessment | null;
  assessment_history: AssessmentHistoryEntry[];
  hypotheses: Hypothesis[];
  scope: {
    affected_txn_ids: string[];
    first_suspicious_txn_id: string;
    exposure_usd: number;
    connected_card_ids: string[];
    connected_device_profiles: string[];
  };
  evidence_count: number;
  counter_evidence_count: number;
  prior_cases: PriorCase[];
  evidence_requests: EvidenceRequestView[];
  sar: { file: boolean; reason: string; narrative: string };
  summary: string;
  stop_reason: string;
  written_to_graph: boolean;
  graph_case_id: string;
  telemetry: { tool_calls: number; tokens: number; latency_s: number; steps: number };
  errors: string[];
}

export interface EvidenceItem {
  seq: number;
  claim: string;
  source: EvidenceSource;
  ref: string;
  entity_ids: string[];
  direction: EvidenceDirection;
  source_family: string;
  result_hash: string;
}

export interface TimelineEvent {
  step: number;
  at: string;
  node: string;
  event: string;
  detail: string;
}

export interface ActionView {
  action: string;
  route: Route;
  reason: string;
  stage: string;
  state: string;
  requires_approval: boolean;
}

export interface ApprovalView {
  action: string;
  route: string;
  decided_by: string;
  decision: string;
  rationale: string;
  decided_at: string;
}

export interface ActionsPayload {
  initial: ActionView[];
  final: ActionView[];
  what_changed: string;
  triggered_rules: string[];
  barred_actions: string[];
  executed: string[];
  approvals: ApprovalView[];
}

export interface GraphNode {
  id: string;
  label: string;
  kind: 'customer' | 'card' | 'transaction' | 'device' | 'connected_card' | 'prior_case';
  affected?: boolean;
  amount?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  label: string;
}

export interface CaseGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Health {
  status: string;
  graph_backend: string;
  graph_live: boolean;
  llm_available: boolean;
  case_pack_size: number;
  cases_investigated: number;
  policy_version: string;
  dataset_version: string;
  simulate_external_actions: boolean;
}
