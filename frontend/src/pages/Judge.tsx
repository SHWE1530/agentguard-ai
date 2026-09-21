import { Activity, CheckCircle2, Circle, Loader2, Play, RotateCcw, ScrollText } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ActionRow } from '../components/ActionStream'
import { CounterfactualPanel } from '../components/analysis'
import { BehaviorGraph } from '../components/BehaviorGraph'
import { RecoveryChecklist } from '../components/RecoveryChecklist'
import { AgentStatusPill, Card, DecisionBadge, RiskMeter, TrustRing } from '../components/ui'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type {
  AgentAction, DemoStage, GraphData, Incident, LiveEvent, RecoveryStep, RiskLevel, Verification,
} from '../types'

const FLOW = ['Normal agent', 'Normal actions', 'Misbehaviour', 'Detection', 'Risk escalation', 'Block', 'Pause', 'Explanation', 'Recovery', 'Verification', 'Audit']

/**
 * Judge mode: one button runs a scripted, repeatable walkthrough of the REAL
 * pipeline. Only the narration and pacing are scripted; every score, decision
 * and recovery step below comes from the running system.
 */
export default function Judge() {
  const [stages, setStages] = useState<DemoStage[]>([])
  const [current, setCurrent] = useState<number>(-1)
  const [running, setRunning] = useState(false)
  const [finished, setFinished] = useState<{ audit_events_total: number; audit_events_flagship: number } | null>(null)
  const [busy, setBusy] = useState<'start' | 'reset' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [actions, setActions] = useState<AgentAction[]>([])
  const [status, setStatus] = useState('IDLE')
  const [trust, setTrust] = useState<number | null>(null)
  const [trustBefore, setTrustBefore] = useState<number | null>(null)
  const [incident, setIncident] = useState<Incident | null>(null)
  const [steps, setSteps] = useState<RecoveryStep[]>([])
  const [outcome, setOutcome] = useState<'SUCCESS' | 'PARTIAL' | 'FAILED' | undefined>()
  const [verification, setVerification] = useState<Verification | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const sess = useRef<string | null>(null)
  sess.current = sessionId

  useEffect(() => {
    api.demoStatus().then((s) => { setStages(s.stages); setRunning(s.running) }).catch(() => {})
  }, [])

  const clear = useCallback(() => {
    setCurrent(-1); setFinished(null); setActions([]); setStatus('IDLE'); setIncident(null); setSteps([])
    setOutcome(undefined); setVerification(null); setGraph(null); setSessionId(null); setTrust(null); setTrustBefore(null)
  }, [])

  useEventListener(
    ['demo_stage', 'demo_finished', 'demo_reset', 'simulation_started', 'action', 'incident', 'recovery', 'agent_status', 'error'],
    (e: LiveEvent) => {
      switch (e.type) {
        case 'demo_stage': setCurrent(e.data.index); setRunning(true); break
        case 'demo_finished': setFinished(e.data); setRunning(false); break
        case 'demo_reset': clear(); break
        case 'simulation_started':
          // every scenario in the demo starts a fresh session; show the current one
          setSessionId(e.data.session_id); setActions([]); setGraph(null); setStatus('RUNNING'); setIncident(null)
          setSteps([]); setOutcome(undefined); setVerification(null)
          break
        case 'action': {
          const a = e.data as AgentAction
          if (sess.current && a.session_id !== sess.current) break
          setActions((p) => [a, ...p.filter((x) => x.id !== a.id)])
          if (a.agent_status) setStatus(a.agent_status)
          if (a.trust !== undefined) setTrust((t) => { if (t === null) setTrustBefore(a.trust!); return a.trust! })
          api.sessionGraph(a.session_id).then(setGraph).catch(() => {})
          break
        }
        case 'incident': if (!sess.current || e.data.session_id === sess.current) setIncident(e.data); break
        case 'agent_status': setStatus(e.data.status); break
        case 'recovery': {
          const d = e.data
          if (d.stage === 'STARTED') { setSteps([]); setOutcome(undefined); setVerification(null) }
          else if (d.stage === 'STEP') setSteps((p) => [...p.filter((x) => x.step !== d.step.step), d.step])
          else { setOutcome(d.outcome); setVerification(d.verification) }
          break
        }
        case 'error': setError(e.data.message); setRunning(false); break
      }
    },
  )

  const start = async () => {
    setBusy('start'); setError(null); clear()
    try { await api.demoStart(); setRunning(true) }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not start the demo.') }
    finally { setBusy(null) }
  }

  const reset = async () => {
    setBusy('reset'); setError(null)
    try { await api.demoReset(); clear() }
    catch (e) { setError(e instanceof ApiError ? e.message : 'Could not reset the demo.') }
    finally { setBusy(null) }
  }

  const stage = stages[current]
  const latest = actions[0]
  const flagged = actions.find((a) => a.decision === 'BLOCK' || a.decision === 'TERMINATE')

  return (
    <div className="space-y-5">
      <div className="card card-pad relative overflow-hidden">
        <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-ai/10 blur-3xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-4">
          <div className="max-w-2xl">
            <p className="label text-ai">Judge mode</p>
            <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-white">Watch a safe-autonomy incident, end to end</h1>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              About 2½ minutes. A normal agent, a legitimate-but-unusual burst that must <em>not</em> be blocked, then an agent that
              goes rogue: detected, blocked, halted, explained, recovered and verified. All numbers are live pipeline output.
            </p>
          </div>
          <div className="flex gap-2">
            <button className="btn-primary px-6 py-3 text-base" onClick={start} disabled={running || busy !== null}>
              {busy === 'start' || running ? <Loader2 size={17} className="animate-spin" /> : <Play size={17} />}
              {running ? 'Demo running…' : 'START DEMO'}
            </button>
            <button className="btn-ghost px-4" onClick={reset} disabled={running || busy !== null} title="Reset to a known seeded state">
              {busy === 'reset' ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />} RESET DEMO
            </button>
          </div>
        </div>
        {error && <p className="relative mt-3 rounded-lg border border-crit/25 bg-crit/[0.07] px-3 py-2 text-sm text-crit">{error}</p>}
        <div className="relative mt-4 flex flex-wrap items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-slate-600">
          {FLOW.map((f, i) => <span key={f} className="flex items-center gap-1">{f}{i < FLOW.length - 1 && <span className="text-slate-800">→</span>}</span>)}
        </div>
      </div>

      {/* narration */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Narration" className="lg:col-span-2">
          {stage ? (
            <div key={stage.key} className="animate-fade-up">
              <p className="text-lg font-bold text-white">{stage.title}</p>
              <p className="mt-2 text-sm leading-relaxed text-slate-400">{stage.narration}</p>
            </div>
          ) : (
            <p className="py-4 text-sm text-slate-500">Press START DEMO. Use RESET DEMO first for a clean, repeatable run.</p>
          )}
          <ol className="mt-4 grid gap-1.5 sm:grid-cols-2">
            {stages.map((s, i) => {
              const done = i < current || (finished && i <= current)
              const now = i === current && !finished
              return (
                <li key={s.key} className={`flex items-center gap-2 text-xs ${now ? 'text-white' : done ? 'text-slate-400' : 'text-slate-600'}`}>
                  {done ? <CheckCircle2 size={14} className="text-safe" /> : now ? <Loader2 size={14} className="animate-spin text-beam" /> : <Circle size={14} />}
                  {s.title}
                </li>
              )
            })}
          </ol>
        </Card>

        <Card title="Agent" icon={<Activity size={14} className="text-slate-500" />}>
          <div className="flex items-center gap-4">
            <RiskMeter score={latest?.risk_score ?? 0} level={(latest?.risk_level ?? 'LOW') as RiskLevel} size={112} />
            <div className="space-y-2">
              <AgentStatusPill status={status} />
              {latest && <DecisionBadge decision={latest.decision} />}
              <p className="font-mono text-[11px] text-ai">anomaly {latest ? latest.anomaly_score.toFixed(2) : '—'}</p>
            </div>
          </div>
          {trust !== null && (
            <div className="mt-3 flex items-center gap-3 border-t border-white/[0.06] pt-3">
              <TrustRing score={trust} size={64} />
              <p className="text-xs text-slate-500">
                Agent trust {trustBefore !== null && trustBefore !== trust ? `fell from ${Math.round(trustBefore)} to ${Math.round(trust)}` : 'is computed from its recorded history'}.
                Low trust tightens enforcement.
              </p>
            </div>
          )}
        </Card>
      </div>

      <Card title="Live action stream" subtitle="Click any row for the evidence behind the decision"
            action={running && <span className="chip bg-beam/10 text-beam ring-1 ring-inset ring-beam/25"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-beam" /> Live</span>}>
        {actions.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-600">Actions appear here as the agent works.</p>
        ) : (
          <ul className="space-y-2">
            {actions.map((a, i) => <ActionRow key={a.id} action={a} defaultOpen={i === 0 && (a.decision === 'BLOCK' || a.decision === 'TERMINATE')} />)}
          </ul>
        )}
      </Card>

      {flagged && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="What would have happened" subtitle="Counterfactual simulation of the blocked action">
            <CounterfactualPanel cf={flagged.risk_factors.counterfactual} compact />
          </Card>
          {graph && (
            <Card title="Behaviour graph" subtitle="The suspicious path is red">
              <BehaviorGraph data={graph} />
            </Card>
          )}
        </div>
      )}

      {(steps.length > 0 || incident) && (
        <Card title={`Recovery & verification${incident ? ` · ${incident.reference}` : ''}`} subtitle="Executed step by step, verified independently">
          <RecoveryChecklist steps={steps} running={steps.length > 0 && !outcome} outcome={outcome} verification={verification} />
        </Card>
      )}

      {finished && (
        <Card title="Audit" icon={<ScrollText size={14} className="text-slate-500" />}>
          <p className="text-sm text-slate-400">
            {finished.audit_events_flagship} audit events were recorded for the rogue-agent session alone
            ({finished.audit_events_total} in total): detection, policy rule, risk factors, decision, recovery steps and trust change.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link to="/app/audit" className="btn-primary">Open the audit trail</Link>
            {incident && <Link to={`/app/incidents/${incident.id}`} className="btn-ghost">Replay the incident</Link>}
            <Link to="/app/evaluation" className="btn-ghost">See the evaluation</Link>
          </div>
        </Card>
      )}
    </div>
  )
}
