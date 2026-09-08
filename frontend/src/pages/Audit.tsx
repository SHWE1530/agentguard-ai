import { Download, RefreshCw, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Card, EmptyState, ErrorState, Loading, RISK_COLOR, fmtDateTime } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { api } from '../services/api'
import type { AuditRow, RiskLevel } from '../types'

const EVENT_TONE: Record<string, string> = {
  ACTION_BLOCKED: 'text-crit',
  AGENT_PAUSED: 'text-crit',
  AGENT_STOPPED: 'text-crit',
  INCIDENT_CREATED: 'text-crit',
  RECOVERY_FAILED: 'text-crit',
  HUMAN_REJECTION: 'text-crit',
  POLICY_VIOLATION: 'text-high',
  ANOMALY_DETECTED: 'text-ai',
  APPROVAL_REQUESTED: 'text-ai',
  RISK_CALCULATED: 'text-warn',
  RECOVERY_VERIFIED: 'text-safe',
  RECOVERY_COMPLETED: 'text-safe',
  INCIDENT_RESOLVED: 'text-safe',
  HUMAN_APPROVAL: 'text-safe',
}

export default function Audit() {
  const [eventType, setEventType] = useState('')
  const [riskLevel, setRiskLevel] = useState('')
  const [search, setSearch] = useState('')
  const [sessionId, setSessionId] = useState('')

  const { data: types } = useApi(() => api.auditEventTypes(), [])
  const { data, error, loading, reload } = useApi(
    () =>
      api.audit({
        event_type: eventType || undefined,
        risk_level: riskLevel || undefined,
        search: search || undefined,
        session_id: sessionId || undefined,
        limit: 500,
      }),
    [eventType, riskLevel, search, sessionId],
  )

  useEventListener(['audit'], () => reload())

  const rows = data ?? []
  const sessions = useMemo(
    () => Array.from(new Set(rows.map((r) => r.session_id).filter(Boolean))) as string[],
    [rows],
  )

  const exportCsv = () => {
    const header = ['timestamp', 'event', 'agent', 'session', 'action', 'risk', 'level', 'decision', 'reason']
    const lines = rows.map((r) =>
      [
        r.timestamp, r.event_type, r.agent_name ?? '', r.session_id ?? '', r.action_type ?? '',
        r.risk_score ?? '', r.risk_level ?? '', r.decision ?? '',
        `"${(r.reason ?? '').replace(/"/g, '""')}"`,
      ].join(','),
    )
    const blob = new Blob([[header.join(','), ...lines].join('\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'agent-sentinel-audit.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const clear = () => {
    setEventType('')
    setRiskLevel('')
    setSearch('')
    setSessionId('')
  }

  const hasFilters = Boolean(eventType || riskLevel || search || sessionId)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">Audit Trail</h1>
          <p className="mt-1 text-sm text-slate-500">
            Append-only record of every safety-relevant event. This is the evidence trail.
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={reload} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button className="btn-ghost" onClick={exportCsv} disabled={!rows.length}>
            <Download size={14} /> Export CSV
          </button>
        </div>
      </div>

      <Card>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block">
            <span className="label">Event type</span>
            <select
              className="input mt-1"
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
            >
              <option value="">All events</option>
              {(types ?? []).map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Risk level</span>
            <select
              className="input mt-1"
              value={riskLevel}
              onChange={(e) => setRiskLevel(e.target.value)}
            >
              <option value="">All levels</option>
              {['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Session</span>
            <select
              className="input mt-1"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
            >
              <option value="">All sessions</option>
              {sessions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">Search reason</span>
            <span className="relative mt-1 block">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-600" />
              <input
                className="input pl-9"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="e.g. DELETE_DATABASE"
              />
            </span>
          </label>
        </div>
        {hasFilters && (
          <button
            onClick={clear}
            className="mt-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
          >
            <X size={12} /> Clear filters
          </button>
        )}
      </Card>

      {error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : loading && !data ? (
        <Loading label="Loading audit events…" />
      ) : rows.length === 0 ? (
        <Card>
          <EmptyState
            title="No audit events match these filters"
            hint="Clear the filters, or run a simulation to generate activity."
          />
        </Card>
      ) : (
        <Card subtitle={`${rows.length} event(s)`} title="Events">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  <th className="th">Timestamp</th>
                  <th className="th">Event</th>
                  <th className="th">Agent</th>
                  <th className="th">Action</th>
                  <th className="th">Risk</th>
                  <th className="th">Decision</th>
                  <th className="th">Reason</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r: AuditRow) => (
                  <tr key={r.id} className="border-b border-white/[0.04] hover:bg-white/[0.02]">
                    <td className="td whitespace-nowrap font-mono text-[11px] text-slate-500">
                      {fmtDateTime(r.timestamp)}
                    </td>
                    <td className={`td whitespace-nowrap text-xs font-semibold ${EVENT_TONE[r.event_type] ?? 'text-slate-300'}`}>
                      {r.event_type.replace(/_/g, ' ')}
                    </td>
                    <td className="td whitespace-nowrap text-xs text-slate-400">
                      {r.agent_name ?? '—'}
                    </td>
                    <td className="td whitespace-nowrap font-mono text-[11px] text-slate-400">
                      {r.action_type ?? '—'}
                    </td>
                    <td className="td whitespace-nowrap">
                      {r.risk_score === null ? (
                        <span className="text-xs text-slate-600">—</span>
                      ) : (
                        <span
                          className="font-mono text-xs font-semibold tabular-nums"
                          style={{ color: RISK_COLOR[(r.risk_level ?? 'LOW') as RiskLevel] }}
                        >
                          {Math.round(r.risk_score)}
                          <span className="ml-1 text-[10px] opacity-70">{r.risk_level}</span>
                        </span>
                      )}
                    </td>
                    <td className="td whitespace-nowrap text-xs text-slate-400">
                      {r.decision?.replace(/_/g, ' ') ?? '—'}
                    </td>
                    <td className="td max-w-xl text-xs text-slate-500">{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
