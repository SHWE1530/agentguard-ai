import { authStore } from './authStore'
import type {
  Agent, AgentAction, AgentProfile, Approval, Architecture, AuditRow, BaselineResult, DemoStage,
  EnvironmentState, Evaluation, GraphData, Incident, IncidentDetail, MLStatus, Metrics, RecoveryResult,
  Replay, Scenario, SimulationDetail, SimulationStart,
} from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const KEY = import.meta.env.VITE_API_KEY ?? ''

/** Thrown for any non-2xx response, carrying the backend's friendly detail. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(KEY ? { 'X-API-Key': KEY } : {}),
        ...(authStore.token() ? { Authorization: `Bearer ${authStore.token()}` } : {}),
      },
      ...init,
    })
  } catch {
    throw new ApiError(
      0,
      'Cannot reach the Agent Sentinel backend. Start it with: uvicorn backend.app.main:app --reload',
    )
  }
  if (res.status === 401 && authStore.token()) authStore.notifyUnauthorized()
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      detail = body.detail ?? body.error ?? detail
      if (Array.isArray(detail)) detail = detail.map((d: any) => d.msg).join('; ')
    } catch {
      /* body was not JSON; keep the generic message */
    }
    throw new ApiError(res.status, String(detail))
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) })

const qs = (params: Record<string, string | number | undefined>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  if (!entries.length) return ''
  return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
}

export const api = {
  health: () => request<{ status: string; model_loaded: boolean }>('/api/health'),
  agents: () => request<Agent[]>('/api/agents'),
  agentProfile: (id: string) => request<AgentProfile>(`/api/agents/${id}/profile`),
  updateBaseline: (id: string, sessionId?: string) =>
    post<{ results: BaselineResult[]; active_version: number }>(`/api/agents/${id}/baseline/update`, { session_id: sessionId }),

  scenarios: () => request<Scenario[]>('/api/scenarios'),
  startSimulation: (scenario: string) => post<SimulationStart>('/api/simulations/start', { scenario }),
  simulation: (id: string) => request<SimulationDetail>(`/api/simulations/${id}`),
  sessionGraph: (id: string) => request<GraphData>(`/api/sessions/${id}/graph`),

  actions: (p: { session_id?: string; risk_level?: string; status?: string; limit?: number } = {}) =>
    request<AgentAction[]>(`/api/actions${qs(p)}`),

  incidents: (p: { status?: string; severity?: string } = {}) => request<Incident[]>(`/api/incidents${qs(p)}`),
  incident: (id: string) => request<IncidentDetail>(`/api/incidents/${id}`),
  replay: (id: string) => request<Replay>(`/api/incidents/${id}/replay`),
  recover: (id: string, fault?: string) => post<RecoveryResult>(`/api/incidents/${id}/recover`, { fault }),

  pendingApprovals: () => request<Approval[]>('/api/pending-approvals'),
  allApprovals: () => request<Approval[]>('/api/approvals'),
  approve: (id: string, by: string, note?: string) => post<Approval>(`/api/approvals/${id}/approve`, { decided_by: by, note }),
  reject: (id: string, by: string, note?: string) => post<Approval>(`/api/approvals/${id}/reject`, { decided_by: by, note }),
  requestEvidence: (id: string, by: string) => post<Approval>(`/api/approvals/${id}/request-evidence`, { decided_by: by }),

  audit: (p: { event_type?: string; risk_level?: string; session_id?: string; agent_name?: string; search?: string; limit?: number } = {}) =>
    request<AuditRow[]>(`/api/audit${qs(p)}`),
  auditEventTypes: () => request<string[]>('/api/audit/event-types'),

  metrics: () => request<Metrics>('/api/metrics'),
  environment: () => request<EnvironmentState>('/api/environment'),
  mlStatus: () => request<MLStatus>('/api/ml/status'),
  evaluation: () => request<Evaluation>('/api/evaluation'),
  architecture: () => request<Architecture>('/api/architecture'),
  policy: () => request<Record<string, any>>('/api/policy'),

  demoStatus: () => request<{ running: boolean; stage: string | null; session_ids: string[]; stages: DemoStage[] }>('/api/demo/status'),
  demoStart: () => post<{ started: boolean; stages: DemoStage[] }>('/api/demo/start'),
  demoReset: () => post<Record<string, any>>('/api/demo/reset'),
}

export function wsUrl(): string {
  const q = authStore.token() ? `?token=${encodeURIComponent(authStore.token()!)}` : ''
  if (BASE) return BASE.replace(/^http/, 'ws') + '/ws/events' + q
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/events${q}`
}
