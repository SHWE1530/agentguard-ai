export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type Decision = 'ALLOW' | 'MONITOR' | 'REQUIRE_APPROVAL' | 'BLOCK' | 'TERMINATE'

export interface SequencePattern {
  id: string
  name: string
  description: string
  progress: number
  total: number
  terminate_at: number
  path: string[]
  risk: number
  completed: boolean
}

export interface Counterfactual {
  action: string
  allow: {
    resources_impacted: { resource: string; from: string; to: string; cascade: boolean }[]
    availability_loss: number
    data_exposure: number
    privilege_compromise: boolean
    irreversible: boolean
    recovery_required: boolean
    est_recovery_minutes: number
    impact_score: number
  }
  block: {
    resources_impacted: unknown[]
    recovery_required: boolean
    est_recovery_minutes: number
    impact_score: number
    task_effect: string
  }
  chain_projection: {
    steps: string[]
    additional_changes: { resource: string; to: string }[]
    impact_score_if_chain_completes: number
  } | null
  impact_score: number
  modelled: boolean
}

export interface ZeroTrustAnswer {
  question: string
  answer: string
  ok: boolean
}

export interface AllowRationale {
  anomaly: string
  policy: string
  intent_alignment: string
  resource_sensitivity: string
  sequence: string
  final_decision: string
  why: string
}

/** The full analysis stored with every action. */
export interface Analysis {
  factors: Record<string, number>
  weighted_contributions: Record<string, number>
  floors: string[]
  intent: { task_type: string; alignment: number; kind?: string; semantic?: number }
  sequence: {
    bigram_deviation: number
    trigram_novel: number
    patterns: SequencePattern[]
    privilege_escalation: { detected: boolean; kind?: string; description?: string; path?: { action: string; level: string }[] }
    loop: { kind: string | null; consecutive_same?: number; consecutive_failures?: number; observe_streak?: number }
    sequence_risk: number
    pattern_terminate: string | null
    window: string[]
  }
  drift: { score: number; insufficient?: number; action_mix?: number; novel_transitions?: number; novel_resources?: number; permission_shift?: number; timing_shift?: number }
  drift_alert: boolean
  drift_threshold: number
  policy_violations: string[]
  policy_details: Record<string, string>
  matched_rules: { id: string; effect: string; reason: string }[]
  counterfactual: Counterfactual
  zero_trust: ZeroTrustAnswer[]
  allow_rationale: AllowRationale | null
  alternative: { action: string; note: string } | null
  trust: number
  tainted: boolean
  injection: { score: number; tainted: boolean; indicators: { label: string; match: string }[] } | null
  fingerprint_version: number
  ml_source: string
  ml_raw_score: number | null
  features: Record<string, number>
  latency_ms: Record<string, number>
}

export interface AgentAction {
  id: string
  timestamp: string
  session_id: string
  agent_id: string
  task_id: string
  step_index: number
  action_type: string
  tool_name: string
  resource: string
  permission_level: string
  task_relevance: number
  action_status: string
  decision: Decision
  execution_result: string
  interval_s: number
  anomaly_score: number
  risk_score: number
  risk_level: RiskLevel
  policy_violation: string | null
  explanation: string
  risk_factors: Analysis
  incident_id: string | null
  executed?: boolean
  agent_status?: string
  trust?: number
  tainted?: boolean
  guard_bypassed?: boolean
  simulated_effects?: Record<string, string>
}

export interface Agent {
  id: string
  name: string
  purpose: string
  status: string
  created_at: string
  current_session: string | null
  current_scenario: string | null
  session_status: string | null
  current_task: string | null
  current_action: AgentAction | null
  trust: number
  trust_band: string
  baseline_version: number
  allowed_actions: string[]
  restricted_actions: string[]
}

export interface TrustInfo {
  score: number
  band: string
  n_sessions: number
  components: Record<string, number>
  rates?: Record<string, number>
  clean_sessions?: number
}

export interface AgentProfile {
  agent: Agent
  trust: TrustInfo
  trust_history: { t: string; score: number; event: string }[]
  drift_history: { session_id: string; peak: number; final: number; threshold: number; reference: number; t: string }[]
  fingerprint: {
    version: number
    source: string
    n_sessions: number
    n_actions: number
    top_actions: { action: string; share: number }[]
    top_tools: { tool: string; share: number }[]
    resource_prefixes: { prefix: string; share: number }[]
    top_transitions: { from: string; to: string; count: number }[]
    mean_permission: number
    typical_interval_s: number
    reference_drift: { mean: number; p95: number }
    drift_threshold: number
  }
  baselines: { version: number; source: string; active: boolean; anchor_divergence: number; note: string; created_at: string }[]
}

export interface BaselineResult {
  session_id: string
  accepted: boolean
  reasons: string[]
  version?: number
  step_divergence?: number
  anchor_divergence?: number
  peak_risk: number
  peak_drift: number
}

export interface Incident {
  id: string
  reference: string
  session_id: string
  agent_id: string
  agent_name?: string | null
  severity: RiskLevel
  title: string
  reason: string
  risk_score: number
  status: string
  kind: string
  recovery_attempts: number
  trigger_action_id: string
  created_at: string
  resolved_at: string | null
}

export interface RecoveryStep {
  step: string
  status: 'OK' | 'FAILED' | 'PARTIAL' | 'SKIPPED'
  detail: string
  resources?: string[]
  failed?: string[]
  integrity_mismatch?: string[]
}

export interface Verification {
  verified: boolean
  summary: string
  checks: { resource: string; kind: string; expected: string; observed: string; state_ok: boolean; integrity_ok: boolean; passed: boolean }[]
  failed_checks: unknown[]
}

export interface RecoveryResult {
  incident_id: string
  reference: string
  status: string
  outcome: 'SUCCESS' | 'PARTIAL' | 'FAILED'
  verified: boolean
  attempt: number
  fault: string | null
  steps: RecoveryStep[]
  verification: Verification
  residual_risk: string[]
}

export interface RecoveryEventRow {
  id: string
  incident_id: string
  recovery_action: string
  previous_state: Record<string, string>
  restored_state: Record<string, string>
  recovery_status: string
  detail: string
  timestamp: string
}

export interface AuditRow {
  id: string
  timestamp: string
  event_type: string
  agent_id: string | null
  agent_name: string | null
  session_id: string | null
  incident_id: string | null
  action_type: string | null
  risk_score: number | null
  risk_level: RiskLevel | null
  decision: string | null
  reason: string
}

export interface IncidentDetail extends Incident {
  actions: AgentAction[]
  trigger_action: AgentAction | null
  risk_factors: Analysis | Record<string, never>
  ai_explanation: string
  prevented_steps: string[]
  interventions: { id: string; action_id: string; decision: Decision; reason: string; agent_state_after: string; created_at: string }[]
  recovery_events: RecoveryEventRow[]
  timeline: AuditRow[]
}

export interface EvidenceFinding {
  source: string
  finding: string
  signal: 'supports_approval' | 'supports_rejection' | 'neutral'
}

export interface Approval {
  id: string
  action_id: string
  session_id: string
  agent_id: string
  agent_name?: string | null
  action_type: string
  risk_score: number
  reason: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED'
  evidence: {
    top_risk_factors: { factor: string; value: number; contribution: number | null }[]
    intent: { task_type: string; alignment: number }
    anomaly: number
    sequence_patterns: SequencePattern[]
    matched_rules: { id: string; effect: string; reason: string }[]
    policy_violations: { code: string; detail: string }[]
    recent_actions: { action: string; alignment: number; blocked: boolean }[]
    trust: number
    drift: number
    rounds?: { round: number; findings: EvidenceFinding[] }[]
  }
  impact: Counterfactual
  alternative: { action: string; note: string } | null
  evidence_rounds: number
  decision_note: string | null
  decided_by: string | null
  created_at: string
  decided_at: string | null
  action?: AgentAction | null
}

export interface Scenario {
  key: string
  name: string
  category: string
  agent: string
  task: string
  description: string
  expected_normal: string
  abnormal_behavior: string
  risk: string
  expected_intervention: string
  recovery_method: string
  sequence: string[]
  auto_recover: boolean
  fault: string | null
  tags: string[]
  n_steps: number
}

export interface AgentSummary {
  id: string
  name: string
  status: string
  purpose: string
  trust: number
  trust_band: string
  baseline_version: number
  drift_threshold: number
  reference_drift: number
  last_drift_peak: number | null
  active_incidents: number
}

export interface Metrics {
  total_actions: number
  normal_actions: number
  suspicious_actions: number
  blocked_actions: number
  total_incidents: number
  critical_incidents: number
  active_incidents: number
  recovered_incidents: number
  recovery_success_rate: number | null
  recovery_partial: number
  recovery_failed: number
  avg_anomaly_score: number
  avg_risk_score: number
  pending_approvals: number
  human_approval_rate: number | null
  active_agents: number
  paused_agents: number
  total_sessions: number
  recovery_events: number
  min_trust: number
  agents: AgentSummary[]
  decisions: { decision: string; count: number }[]
  risk_distribution: { level: RiskLevel; count: number }[]
  incidents_by_severity: { severity: string; count: number }[]
  normal_vs_suspicious: { name: string; value: number }[]
  activity: { bucket: string; total: number; blocked: number; suspicious: number }[]
  drift_history: { agent: string; session_id: string; peak: number; final: number; threshold: number; reference: number; t: string }[]
  latency_ms: Record<string, number>
  environment: Record<string, string>
}

export interface Prf {
  tp: number; fp: number; tn: number; fn: number
  precision: number; recall: number; f1: number; accuracy: number
  false_positive_rate: number; false_negative_rate: number; balanced_accuracy: number
}

export interface DetectorEval {
  action_level: Prf
  session_level: Prf
  benign_sessions_only: { false_positive_rate: number; false_positives: number; benign_actions: number }
  detection_latency_steps: { mean: number | null; median: number | null; p95: number | null; flagged_on_first_malicious_step: number; sessions_flagged_before_onset: number }
  roc_auc: number | null
  pr_auc: number | null
  auc_note?: string
  roc_curve?: [number, number][]
  pr_curve?: [number, number][]
}

export interface Evaluation {
  generated_at: string
  model: string
  dataset: string
  split: string
  mode: string
  threshold: number
  n_test_sessions: number
  n_malicious_sessions: number
  n_benign_sessions: number
  n_test_actions: number
  n_malicious_actions: number
  novel_families: string[]
  detector_labels: Record<string, string>
  dev_set: { note: string; n_sessions: number; detectors: Record<string, { action_level: Prf; session_level: Prf }> }
  ablation: Record<string, DetectorEval>
  per_family: Record<string, { n_sessions: number; malicious: boolean; novel: boolean } & Record<string, any>>
  friction_on_benign: { benign_actions: number; monitor_rate: number }
  single_feature_separability: { feature: string; auc: number }[]
  live_latency: { n_actions: number; mean_ms: number; p50_ms: number; p95_ms: number; stage_mean_ms: Record<string, number> }
  robustness: Record<string, { n_sessions: number } & Record<string, any>>
  limitations: string[]
  eval_seconds: number
}

export interface MLStatus {
  model: string
  loaded: boolean
  error: string | null
  calibration: { t: number; s: number }
  threshold: number
  n_features: number
  feature_names: string[]
}

export interface GraphData {
  session_id: string
  nodes: { id: string; kind: string; label: string; suspicious: boolean; step?: number; decision?: Decision; risk?: number; risk_level?: RiskLevel; executed?: boolean }[]
  edges: { id: string; source: string; target: string; suspicious: boolean; kind: string }[]
  suspicious_path: string[]
  chain: string[]
}

export interface ReplayFrame {
  t: number
  event_type: string
  reason: string
  action_type: string | null
  risk_score: number | null
  risk_level: RiskLevel | null
  decision: string | null
  agent_status: string
  environment: Record<string, string>
  action: AgentAction | null
}

export interface Replay {
  incident_id: string
  reference: string
  frames: ReplayFrame[]
  duration_s: number
}

export interface Architecture {
  stages: { id: string; name: string; module: string; does: string; inputs: string; outputs: string; stat: string; implemented: boolean; note?: string }[]
  future_work: { name: string; why: string }[]
  decision_latency_ms: Record<string, number>
  n_actions_measured: number
  zero_trust: { principle: string; per_action_questions: string[]; claim: string }
}

export interface SimulationStart {
  session_id: string
  task_id: string
  agent_id: string
  agent_name: string
  scenario: string
  scenario_name: string
  task: string
  planned_sequence: string[]
  status: string
}

export interface SimulationDetail {
  id: string
  scenario: string
  status: string
  agent: { id: string; name: string; status: string } | null
  task: string | null
  tainted: boolean
  planned_sequence: string[]
  prevented_steps: string[]
  actions: AgentAction[]
  incidents: Incident[]
  approvals: Approval[]
}

export interface DemoStage {
  key: string
  title: string
  narration: string
  index?: number
  total?: number
}

export interface LiveEvent {
  type: string
  timestamp: string
  data: any
}

export interface EnvironmentState {
  resources: Record<string, string>
  verification: Verification
}
