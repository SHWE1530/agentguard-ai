import { ArrowLeft, BrainCircuit, Loader2, PlayCircle, RotateCcw, Siren } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ActionRow, SequenceDeviation } from '../components/ActionStream'
import { CounterfactualPanel, FactorBars, MatchedRules, ZeroTrustPanel } from '../components/analysis'
import { BehaviorGraph } from '../components/BehaviorGraph'
import { RecoveryChecklist } from '../components/RecoveryChecklist'
import { ReplayPlayer } from '../components/ReplayPlayer'
import { Card, ErrorState, Loading, RISK_COLOR, RiskMeter, fmtDateTime, fmtTime } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type { Analysis, RecoveryResult, RecoveryStep, RiskLevel } from '../types'

const EVENT_COLOR: Record<string, string> = {
  ACTION_BLOCKED: '#dc2626', AGENT_PAUSED: '#dc2626', INCIDENT_CREATED: '#dc2626', POLICY_VIOLATION: '#ea580c',
  SEQUENCE_PATTERN_DETECTED: '#ea580c', PRIVILEGE_ESCALATION_DETECTED: '#ea580c', INJECTION_INDICATOR_DETECTED: '#7c3aed',
  ANOMALY_DETECTED: '#7c3aed', RISK_CALCULATED: '#ca8a04', DRIFT_DETECTED: '#ca8a04', RECOVERY_STARTED: '#0284c7',
  RECOVERY_STEP: '#0284c7', RECOVERY_VERIFIED: '#16a34a', INCIDENT_RESOLVED: '#16a34a', RECOVERY_PARTIAL: '#ca8a04',
  RECOVERY_FAILED: '#dc2626', HUMAN_APPROVAL: '#16a34a', HUMAN_REJECTION: '#dc2626',
}

export default function IncidentDetail() {
  const { id = '' } = useParams()
  const { data, error, loading, reload } = useApi(() => api.incident(id), [id])
  const graph = useApi(() => (data ? api.sessionGraph(data.session_id) : Promise.resolve(null)), [data?.session_id])
  const replay = useApi(() => api.replay(id), [id, data?.status])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<RecoveryResult | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [showRaw, setShowRaw] = useState(false)

  useEventListener(['recovery'], (e) => { if (e.data?.incident_id === id) reload() })
  useEffect(() => setResult(null), [id])

  const recover = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await api.recover(id)
      setResult(r)
      reload()
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : 'Recovery could not be started.')
    } finally { setBusy(false) }
  }

  if (loading && !data) return <Loading label="Loading incident…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  const color = RISK_COLOR[data.severity as RiskLevel] ?? '#64748b'
  const rf = data.risk_factors as Analysis
  const has = Boolean(rf?.factors)
  const done = data.status === 'RESOLVED'

  // recovery steps: prefer the fresh result, else reconstruct from stored events
  const stored: RecoveryStep[] = data.recovery_events
    .filter((r) => ['PAUSE_AGENT', 'REVERT_PERMISSIONS', 'RESTORE_RESOURCES', 'INTEGRITY_VERIFICATION'].includes(r.recovery_action))
    .map((r) => ({ step: r.recovery_action, status: r.recovery_status as RecoveryStep['status'], detail: r.detail }))
  // keep the most recent attempt (last four steps)
  const latestSteps = result?.steps ?? stored.slice(-4)
  const outcome = result?.outcome ?? (data.status === 'RESOLVED' ? 'SUCCESS' : data.status === 'RECOVERY_PARTIAL' ? 'PARTIAL' : data.status === 'RECOVERY_FAILED' ? 'FAILED' : undefined)

  return (
    <div className="space-y-5">
      <Link to="/app/incidents" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-300"><ArrowLeft size={14} /> Back to Incident Center</Link>

      <div className="card card-pad" style={{ borderTop: `2px solid ${color}` }}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-mono text-xs text-slate-500">{data.reference}</p>
            <h1 className="mt-1 text-xl font-bold tracking-tight text-white">{data.title}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <span className="chip ring-1 ring-inset" style={{ color, backgroundColor: `${color}18`, borderColor: `${color}40` }}><Siren size={11} /> {data.severity}</span>
              <span className="chip bg-white/[0.05] text-slate-300 ring-1 ring-inset ring-white/10">{data.status.replace(/_/g, ' ')}</span>
              <span className="chip bg-white/[0.05] text-slate-400 ring-1 ring-inset ring-white/10">{data.kind}</span>
              <span className="text-slate-500">{data.agent_name}</span>
              <span className="text-slate-600">{fmtDateTime(data.created_at)}</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <RiskMeter score={data.risk_score} level={data.severity as RiskLevel} size={104} />
            <button className="btn-safe" onClick={recover} disabled={busy || done}>
              {busy ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              {done ? 'Recovered' : data.recovery_attempts ? 'Retry recovery' : 'Start recovery'}
            </button>
          </div>
        </div>
        {msg && <p className="mt-3 rounded-lg border border-white/10 bg-ink-850 px-3 py-2 text-sm text-slate-300">{msg}</p>}
      </div>

      <Card title="Incident replay" subtitle="Scrub through what happened, as recorded in the audit trail" icon={<PlayCircle size={14} className="text-beam" />}>
        {replay.loading && !replay.data ? <Loading label="Building replay…" /> : replay.data ? <ReplayPlayer replay={replay.data} /> : null}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Why the system intervened" subtitle="Generated from the signals that actually fired" icon={<BrainCircuit size={14} className="text-ai" />}>
          <p className="text-sm leading-relaxed text-slate-300">{data.ai_explanation}</p>
          {has && rf.matched_rules?.length > 0 && <div className="mt-4"><p className="label mb-1.5">Policy rules that fired</p><MatchedRules rules={rf.matched_rules} /></div>}
          {has && rf.policy_violations.length > 0 && (
            <div className="mt-4">
              <p className="label">Policy violations</p>
              <ul className="mt-1.5 space-y-1.5">
                {rf.policy_violations.map((v) => (
                  <li key={v} className="text-xs"><span className="chip bg-crit/12 text-crit ring-1 ring-inset ring-crit/25">{v.replace(/_/g, ' ')}</span><span className="ml-2 text-slate-400">{rf.policy_details[v]}</span></li>
                ))}
              </ul>
            </div>
          )}
        </Card>
        <Card title="Risk factor breakdown" subtitle="How the 0–100 score was composed">
          {has ? <FactorBars a={rf} /> : <p className="py-6 text-center text-sm text-slate-600">No risk factors recorded.</p>}
        </Card>
      </div>

      {has && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Counterfactual: ALLOW vs BLOCK" subtitle="Simulated on a copy of the sandbox">
            <CounterfactualPanel cf={rf.counterfactual} />
          </Card>
          <Card title="Zero-trust evaluation" subtitle="Six questions asked of every action">
            <ZeroTrustPanel items={rf.zero_trust} />
          </Card>
        </div>
      )}

      <Card title="Behavioural sequence" subtitle="Where the agent left its learned profile">
        <SequenceDeviation actual={data.actions} prevented={data.prevented_steps} />
      </Card>

      {graph.data && (
        <Card title="Behaviour graph" subtitle="Suspicious path highlighted in red">
          <BehaviorGraph data={graph.data} />
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Recovery & verification" subtitle={data.recovery_attempts ? `${data.recovery_attempts} attempt(s)` : 'Not yet attempted'}>
          {latestSteps.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-600">Recovery has not been run for this incident.</p>
          ) : (
            <RecoveryChecklist steps={latestSteps} outcome={outcome} verification={result?.verification}
                               residual={result?.residual_risk} attempt={result?.attempt ?? data.recovery_attempts}
                               onRetry={recover} retrying={busy} />
          )}
        </Card>

        <Card title="Incident timeline" subtitle="Every recorded event, in order">
          <ol className="relative max-h-[420px] space-y-3 overflow-y-auto border-l border-white/[0.08] pl-5">
            {data.timeline.map((e) => {
              const c = EVENT_COLOR[e.event_type] ?? '#475569'
              return (
                <li key={e.id} className="relative">
                  <span className="absolute -left-[26px] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-ink-900" style={{ backgroundColor: c }} />
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-mono text-[11px] text-slate-600">{fmtTime(e.timestamp)}</span>
                    <span className="text-xs font-semibold" style={{ color: c }}>{e.event_type.replace(/_/g, ' ')}</span>
                    {e.risk_score !== null && <span className="font-mono text-[10px] text-slate-600">risk {Math.round(e.risk_score)}</span>}
                  </div>
                  <p className="mt-0.5 text-xs leading-relaxed text-slate-400">{e.reason}</p>
                </li>
              )
            })}
          </ol>
        </Card>
      </div>

      <Card title="Action sequence" subtitle="Every action in the session, with the model output behind each decision"
            action={<button className="text-xs text-slate-500 hover:text-slate-300" onClick={() => setShowRaw((s) => !s)}>{showRaw ? 'Collapse all' : 'Expand trigger action'}</button>}>
        <ul className="space-y-2">
          {data.actions.map((a) => <ActionRow key={a.id} action={a} defaultOpen={showRaw ? a.id === data.trigger_action_id : false} />)}
        </ul>
      </Card>
    </div>
  )
}
