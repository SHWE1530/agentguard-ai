import {
  ArrowLeft, BrainCircuit, Loader2, PlayCircle, RotateCcw, Siren, SkipForward,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ActionRow, SequenceDeviation } from '../components/ActionStream'
import {
  Bar, Card, ErrorState, Loading, RISK_COLOR, RiskMeter, VerifyBadge, fmtDateTime, fmtTime,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type { RiskLevel } from '../types'

const FACTOR_LABEL: Record<string, string> = {
  behavior_anomaly: 'Behaviour anomaly (ML)',
  resource_sensitivity: 'Resource sensitivity',
  permission_risk: 'Permission risk',
  action_severity: 'Action severity',
  task_relevance_gap: 'Task relevance gap',
}

const EVENT_COLOR: Record<string, string> = {
  ACTION_BLOCKED: '#ef4444',
  AGENT_PAUSED: '#ef4444',
  INCIDENT_CREATED: '#ef4444',
  POLICY_VIOLATION: '#f97316',
  ANOMALY_DETECTED: '#8b5cf6',
  RISK_CALCULATED: '#eab308',
  RECOVERY_STARTED: '#38bdf8',
  RECOVERY_COMPLETED: '#22c55e',
  RECOVERY_VERIFIED: '#22c55e',
  RECOVERY_FAILED: '#ef4444',
  INCIDENT_RESOLVED: '#22c55e',
  HUMAN_APPROVAL: '#22c55e',
  HUMAN_REJECTION: '#ef4444',
}

export default function IncidentDetail() {
  const { id = '' } = useParams()
  const { data, error, loading, reload } = useApi(() => api.incident(id), [id])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  // Audit replay: step through the timeline like a recording.
  const [replayIdx, setReplayIdx] = useState<number | null>(null)

  useEventListener(['recovery'], (e) => {
    if (e.data?.incident_id === id) reload()
  })

  useEffect(() => {
    if (replayIdx === null || !data) return
    if (replayIdx >= data.timeline.length) {
      setReplayIdx(null)
      return
    }
    const t = setTimeout(() => setReplayIdx((i) => (i === null ? null : i + 1)), 600)
    return () => clearTimeout(t)
  }, [replayIdx, data])

  const recover = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const res = await api.recover(id)
      setMsg(
        res.verified
          ? 'Recovery completed and verified: every simulated resource matches its baseline.'
          : `Recovery ran but verification FAILED — ${res.verification.summary}`,
      )
      reload()
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : 'Recovery could not be started.')
    } finally {
      setBusy(false)
    }
  }

  if (loading && !data) return <Loading label="Loading incident…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  const color = RISK_COLOR[data.severity as RiskLevel] ?? '#64748b'
  const factors = (data.risk_factors as any)?.factors ?? {}
  const contributions = (data.risk_factors as any)?.weighted_contributions ?? {}
  const violations: string[] = (data.risk_factors as any)?.policy_violations ?? []
  const violationDetails: Record<string, string> = (data.risk_factors as any)?.policy_details ?? {}
  const features: Record<string, number> = (data.risk_factors as any)?.features ?? {}
  const done = data.status === 'RESOLVED' || data.status === 'RECOVERED'
  const visibleTimeline =
    replayIdx === null ? data.timeline : data.timeline.slice(0, Math.max(1, replayIdx))
  const verifyEvent = data.recovery_events.find((e) => e.recovery_action === 'STATE_VERIFICATION')

  return (
    <div className="space-y-5">
      <Link to="/app/incidents" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-300">
        <ArrowLeft size={14} /> Back to Incident Center
      </Link>

      <div className="card card-pad" style={{ borderTop: `2px solid ${color}` }}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-mono text-xs text-slate-500">{data.reference}</p>
            <h1 className="mt-1 text-xl font-bold tracking-tight text-white">{data.title}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <span
                className="chip ring-1 ring-inset"
                style={{ color, backgroundColor: `${color}18`, borderColor: `${color}40` }}
              >
                <Siren size={11} /> {data.severity}
              </span>
              <span className="chip bg-white/[0.05] text-slate-300 ring-1 ring-inset ring-white/10">
                {data.status.replace(/_/g, ' ')}
              </span>
              <span className="text-slate-500">{data.agent_name}</span>
              <span className="text-slate-600">{fmtDateTime(data.created_at)}</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <RiskMeter score={data.risk_score} level={data.severity as RiskLevel} size={104} />
            <button className="btn-safe" onClick={recover} disabled={busy || done}>
              {busy ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              {done ? 'Recovered' : 'Start recovery'}
            </button>
          </div>
        </div>
        {msg && (
          <p className="mt-3 rounded-lg border border-white/10 bg-ink-850 px-3 py-2 text-sm text-slate-300">
            {msg}
          </p>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Why the system intervened"
          subtitle="Generated from the factors that actually fired"
          icon={<BrainCircuit size={14} className="text-ai" />}
        >
          <p className="text-sm leading-relaxed text-slate-300">{data.ai_explanation}</p>
          {violations.length > 0 && (
            <>
              <p className="label mt-4">Policy violations</p>
              <ul className="mt-1.5 space-y-1.5">
                {violations.map((v) => (
                  <li key={v} className="text-xs">
                    <span className="chip bg-crit/12 text-crit ring-1 ring-inset ring-crit/25">
                      {v.replace(/_/g, ' ')}
                    </span>
                    <span className="ml-2 text-slate-400">{violationDetails[v]}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>

        <Card title="Risk factor breakdown" subtitle="How the 0–100 score was composed">
          {Object.keys(factors).length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-600">
              No risk factors recorded for this incident.
            </p>
          ) : (
            <>
              <div className="space-y-2.5">
                {Object.entries(factors).map(([k, v]) => (
                  <div key={k}>
                    <div className="flex items-baseline justify-between gap-2 text-xs">
                      <span className="text-slate-400">{FACTOR_LABEL[k] ?? k}</span>
                      <span className="font-mono tabular-nums text-slate-300">
                        {Math.round(v as number)}
                        <span className="ml-2 text-[10px] text-slate-600">
                          → {(contributions[k] ?? 0).toFixed(1)} pts
                        </span>
                      </span>
                    </div>
                    <div className="mt-1">
                      <Bar
                        value={v as number}
                        color={(v as number) >= 80 ? '#ef4444' : (v as number) >= 50 ? '#f97316' : '#38bdf8'}
                      />
                    </div>
                  </div>
                ))}
              </div>
              {contributions.policy_violations !== undefined && (
                <p className="mt-3 text-[11px] text-slate-500">
                  Policy-violation penalty added {contributions.policy_violations} points on top of
                  the weighted behavioural score.
                </p>
              )}
              <p className="mt-2 text-[11px] text-slate-600">
                Behavioural features fed to the model:{' '}
                {Object.entries(features)
                  .filter(([, v]) => v > 0)
                  .slice(0, 6)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(', ')}
              </p>
            </>
          )}
        </Card>
      </div>

      <Card
        title="Behavioural sequence"
        subtitle="Where the agent left its learned profile"
      >
        <SequenceDeviation planned={[]} actual={data.actions} />
      </Card>

      <Card
        title="Action sequence"
        subtitle="Every action in the session, with the model output that drove the decision"
      >
        <ul className="space-y-2">
          {data.actions.map((a) => (
            <ActionRow key={a.id} action={a} defaultOpen={a.id === data.trigger_action_id} />
          ))}
        </ul>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Incident timeline"
          subtitle="Every recorded event, in order"
          action={
            <button
              className="btn-ghost !px-3 !py-1.5 text-xs"
              onClick={() => setReplayIdx(replayIdx === null ? 1 : null)}
            >
              {replayIdx === null ? <PlayCircle size={13} /> : <SkipForward size={13} />}
              {replayIdx === null ? 'Replay' : 'Show all'}
            </button>
          }
        >
          <ol className="relative space-y-3 border-l border-white/[0.08] pl-5">
            {visibleTimeline.map((e) => {
              const c = EVENT_COLOR[e.event_type] ?? '#475569'
              return (
                <li key={e.id} className="animate-fade-up relative">
                  <span
                    className="absolute -left-[26px] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-ink-900"
                    style={{ backgroundColor: c }}
                  />
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-mono text-[11px] text-slate-600">
                      {fmtTime(e.timestamp)}
                    </span>
                    <span className="text-xs font-semibold" style={{ color: c }}>
                      {e.event_type.replace(/_/g, ' ')}
                    </span>
                    {e.risk_score !== null && (
                      <span className="font-mono text-[10px] text-slate-600">
                        risk {Math.round(e.risk_score)}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{e.reason}</p>
                </li>
              )
            })}
          </ol>
        </Card>

        <Card title="Recovery & verification" subtitle="Rollback of the simulated environment">
          {data.recovery_events.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-600">
              Recovery has not been run for this incident.
            </p>
          ) : (
            <div className="space-y-3">
              {verifyEvent && (
                <VerifyBadge verified={verifyEvent.recovery_status === 'VERIFIED'} />
              )}
              <ol className="space-y-3">
                {data.recovery_events.map((r) => (
                  <li key={r.id} className="rounded-lg border border-white/[0.06] bg-ink-850/60 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-xs font-semibold text-slate-200">
                        {r.recovery_action.replace(/_/g, ' ')}
                      </span>
                      <span
                        className={`chip ${
                          r.recovery_status === 'VERIFIED' || r.recovery_status === 'COMPLETED'
                            ? 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25'
                            : r.recovery_status === 'VERIFICATION_FAILED' || r.recovery_status === 'FAILED'
                              ? 'bg-crit/12 text-crit ring-1 ring-inset ring-crit/25'
                              : 'bg-white/5 text-slate-400 ring-1 ring-inset ring-white/10'
                        }`}
                      >
                        {r.recovery_status}
                      </span>
                    </div>
                    <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{r.detail}</p>
                    <p className="mt-1 font-mono text-[10px] text-slate-600">
                      {fmtDateTime(r.timestamp)}
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </Card>
      </div>

      <Card title="Interventions" subtitle="Enforcement decisions taken during this session">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px]">
            <thead>
              <tr className="border-b border-white/[0.06]">
                <th className="th">Time</th>
                <th className="th">Decision</th>
                <th className="th">Agent state after</th>
                <th className="th">Reason</th>
              </tr>
            </thead>
            <tbody>
              {data.interventions.map((v) => (
                <tr key={v.id} className="border-b border-white/[0.04]">
                  <td className="td font-mono text-xs text-slate-500">{fmtTime(v.created_at)}</td>
                  <td className="td">
                    <span
                      className={`chip ${
                        v.decision.startsWith('BLOCK')
                          ? 'bg-crit/12 text-crit ring-1 ring-inset ring-crit/25'
                          : v.decision === 'REQUIRE_APPROVAL'
                            ? 'bg-ai/12 text-ai ring-1 ring-inset ring-ai/25'
                            : v.decision === 'MONITOR'
                              ? 'bg-warn/12 text-warn ring-1 ring-inset ring-warn/25'
                              : 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25'
                      }`}
                    >
                      {v.decision.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="td text-xs">{v.agent_state_after}</td>
                  <td className="td line-clamp-2 max-w-lg text-xs text-slate-500">{v.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
