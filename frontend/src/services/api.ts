import type {
  Agent, AgentAction, Approval, AuditRow, EnvironmentState, Incident,
  IncidentDetail, MLStatus, Metrics, Scenario, SimulationDetail, SimulationStart,
} from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

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
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError(
      0,
      'Cannot reach the Agent Sentinel backend. Start it with: uvicorn backend.app.main:app --reload',
    )
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      detail = body.detail ?? body.error ?? detail
      if (Array.isArray(detail)) detail = detail.map((d: any) => d.msg).join('; ')
    } catch {
      /* body was not JSON; keep the generic message */
    }
    throw new ApiError(res.status, detail)
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
  scenarios: () => request<Scenario[]>('/api/scenarios'),

  startSimulation: (scenario: string) =>
    post<SimulationStart>('/api/simulations/start', { scenario }),
  simulation: (id: string) => request<SimulationDetail>(`/api/simulations/${id}`),

  actions: (params: { session_id?: string; risk_level?: string; status?: string; limit?: number } = {}) =>
    request<AgentAction[]>(`/api/actions${qs(params)}`),

  incidents: (params: { status?: string; severity?: string } = {}) =>
    request<Incident[]>(`/api/incidents${qs(params)}`),
  incident: (id: string) => request<IncidentDetail>(`/api/incidents/${id}`),
  recover: (id: string) => post<any>(`/api/incidents/${id}/recover`),

  pendingApprovals: () => request<Approval[]>('/api/pending-approvals'),
  allApprovals: () => request<Approval[]>('/api/approvals'),
  approve: (id: string, decidedBy: string, note?: string) =>
    post<Approval>(`/api/approvals/${id}/approve`, { decided_by: decidedBy, note }),
  reject: (id: string, decidedBy: string, note?: string) =>
    post<Approval>(`/api/approvals/${id}/reject`, { decided_by: decidedBy, note }),

  audit: (params: {
    event_type?: string; risk_level?: string; session_id?: string
    agent_name?: string; search?: string; limit?: number
  } = {}) => request<AuditRow[]>(`/api/audit${qs(params)}`),
  auditEventTypes: () => request<string[]>('/api/audit/event-types'),

  metrics: () => request<Metrics>('/api/metrics'),
  environment: () => request<EnvironmentState>('/api/environment'),
  mlStatus: () => request<MLStatus>('/api/ml/status'),
  policy: () => request<Record<string, any>>('/api/policy'),
}

export function wsUrl(): string {
  if (BASE) return BASE.replace(/^http/, 'ws') + '/ws/events'
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/events`
}
