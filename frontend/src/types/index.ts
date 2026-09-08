export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type Decision =
  | 'ALLOW' | 'MONITOR' | 'BLOCK' | 'BLOCK_AND_STOP' | 'REQUIRE_APPROVAL'

export interface RiskFactors {
  factors: Record<string, number>
  weighted_contributions: Record<string, number>
  sequence_deviation: number
  ml_source: string
  ml_raw_score: number | null
  features: Record<string, number>
  policy_violations: string[]
  policy_details: Record<string, string>
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
  anomaly_score: number
  risk_score: number
  risk_level: RiskLevel
  policy_violation: string | null
  explanation: string
  risk_factors: RiskFactors
  incident_id: string | null
  decision?: Decision
  executed?: boolean
  agent_status?: string
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
  allowed_actions: string[]
  restricted_actions: string[]
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
  trigger_action_id: string
  created_at: string
  resolved_at: string | null
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

export interface InterventionRow {
  id: string
  action_id: string
  decision: Decision
  reason: string
  agent_state_after: string
  created_at: string
}

export interface IncidentDetail extends Incident {
  actions: AgentAction[]
  trigger_action: AgentAction | null
  risk_factors: RiskFactors | Record<string, never>
  ai_explanation: string
  interventions: InterventionRow[]
  recovery_events: RecoveryEventRow[]
  timeline: AuditRow[]
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
  decided_by: string | null
  created_at: string
  decided_at: string | null
  action?: AgentAction | null
}

export interface Scenario {
  key: string
  name: string
  task: string
  summary: string
  expected: string
  sequence: string[]
  auto_recover: boolean
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
  avg_anomaly_score: number
  avg_risk_score: number
  pending_approvals: number
  human_approval_rate: number | null
  active_agents: number
  paused_agents: number
  total_sessions: number
  recovery_events: number
  risk_distribution: { level: RiskLevel; count: number }[]
  incidents_by_severity: { severity: string; count: number }[]
  normal_vs_suspicious: { name: string; value: number }[]
  activity: { bucket: string; total: number; blocked: number; suspicious: number }[]
  environment: Record<string, string>
}

export interface MLStatus {
  model: string
  loaded: boolean
  model_path: string
  error: string | null
  calibration: { t: number; s: number }
  n_features: number
  feature_names: string[]
  evaluation: {
    model: string
    dataset: string
    n_features: number
    n_train_normal: number
    n_test: number
    test_positives: number
    decision_threshold: number
    mean_anomaly_normal: number
    mean_anomaly_abnormal: number
    note: string
    metrics: {
      precision: number
      recall: number
      f1: number
      accuracy: number
      false_positive_rate: number
      false_negative_rate: number
      true_positives: number
      false_positives: number
      true_negatives: number
      false_negatives: number
    }
  } | null
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
  started_at: string
  ended_at: string | null
  agent: { id: string; name: string; status: string } | null
  task: string | null
  live: boolean
  actions: AgentAction[]
  incidents: Incident[]
  approvals: Approval[]
}

export interface LiveEvent {
  type: string
  timestamp: string
  data: any
}

export interface EnvironmentState {
  resources: Record<string, string>
  verification: {
    verified: boolean
    summary: string
    checks: {
      resource: string
      kind: string
      expected: string
      observed: string
      passed: boolean
    }[]
    failed_checks: unknown[]
  }
}
