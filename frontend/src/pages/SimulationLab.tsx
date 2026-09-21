import {
  Activity, AlertTriangle, BrainCircuit, Database, Eye, Gauge, GitBranch, Loader2, Play,
  RotateCcw, ShieldCheck, Siren, UserCheck,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ActionStream, SequenceDeviation } from '../components/ActionStream'
import { CounterfactualPanel, MatchedRules } from '../components/analysis'
import { BehaviorGraph } from '../components/BehaviorGraph'
import { DriftChart } from '../components/DriftChart'
import { RecoveryChecklist } from '../components/RecoveryChecklist'
import {
  AgentStatusPill, Card, DecisionBadge, ErrorState, Loading, RiskMeter, TrustRing,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type {
  AgentAction, EnvironmentState, GraphData, Incident, LiveEvent, RecoveryStep, RiskLevel, Scenario, Verification,
} from '../types'

/* -------------------------------------------------------- pipeline stages */

const STAGES = [
  { key: 'observe', label: 'Observe', icon: Eye, color: '#0284c7' },
  { key: 'detect', label: 'Detect', icon: BrainCircuit, color: '#7c3aed' },
  { key: 'assess', label: 'Assess', icon: Gauge, color: '#ca8a04' },
  { key: 'intervene', label: 'Intervene', icon: Siren, color: '#ea580c' },
  { key: 'recover', label: 'Recover', icon: RotateCcw, color: '#16a34a' },
  { key: 'verify', label: 'Verify', icon: ShieldCheck, color: '#16a34a' },
] as const
type StageKey = (typeof STAGES)[number]['key']

function PipelineStages({ reached, active }: { reached: Set<StageKey>; active: StageKey | null }) {
  return (
    <div className="flex flex-wrap items-center gap-x-1 gap-y-3">
      {STAGES.map(({ key, label, icon: Icon, color }, i) => {
        const on = reached.has(key)
        const now = active === key
        return (
          <div key={key} className="flex items-center gap-1">
            <div className="flex w-[72px] flex-col items-center gap-1.5 sm:w-[84px]">
              <span
                className={`grid h-9 w-9 place-items-center rounded-lg ring-1 ring-inset transition-all duration-300 ${now ? 'scale-110' : ''}`}
                style={{
                  color: on ? color : '#94a3b8', backgroundColor: on ? `${color}18` : 'rgba(15,23,42,0.03)',
                  boxShadow: now ? `0 0 14px ${color}55` : 'none',
                  ['--tw-ring-color' as any]: on ? `${color}45` : 'rgba(15,23,42,0.10)',
                }}
              >
                <Icon size={16} />
              </span>
              <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: on ? color : '#475569' }}>{label}</span>
            </div>
            {i < STAGES.length - 1 && <span className="hidden h-px w-4 sm:block" style={{ backgroundColor: on ? `${color}55` : 'rgba(15,23,42,0.10)' }} />}
          </div>
        )
      })}
    </div>
  )
}

const CAT_COLOR: Record<string, string> = {
  baseline: '#16a34a', 'false-positive': '#16a34a', 'data-access': '#ea580c', privilege: '#dc2626',
  destructive: '#dc2626', sequence: '#dc2626', injection: '#7c3aed', drift: '#ca8a04', 'rate-abuse': '#ca8a04',
  reliability: '#ca8a04', 'human-in-the-loop': '#7c3aed', recovery: '#0284c7',
}

/* ------------------------------------------------------------------- page */

export default function SimulationLab() {
  const { data: scenarios, error: scenErr, loading, reload } = useApi(() => api.scenarios(), [])
  const [selected, setSelected] = useState<string>('multi_step')
  const [cat, setCat] = useState<string>('all')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [actions, setActions] = useState<AgentAction[]>([])
  const [agentStatus, setAgentStatus] = useState('IDLE')
  const [sessionStatus, setSessionStatus] = useState<string | null>(null)
  const [prevented, setPrevented] = useState<string[]>([])
  const [incident, setIncident] = useState<Incident | null>(null)
  const [recSteps, setRecSteps] = useState<RecoveryStep[]>([])
  const [recOutcome, setRecOutcome] = useState<'SUCCESS' | 'PARTIAL' | 'FAILED' | undefined>()
  const [recVerification, setRecVerification] = useState<Verification | null>(null)
  const [recAttempt, setRecAttempt] = useState<number | undefined>()
  const [residual, setResidual] = useState<string[]>([])
  const [recRunning, setRecRunning] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [env, setEnv] = useState<EnvironmentState['resources'] | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)
  const [trust, setTrust] = useState<number | null>(null)
  const [tainted, setTainted] = useState(false)
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [activeStage, setActiveStage] = useState<StageKey | null>(null)
  const sessionRef = useRef<string | null>(null)
  sessionRef.current = sessionId

  const scenario: Scenario | undefined = scenarios?.find((s) => s.key === selected)
  const categories = useMemo(() => ['all', ...Array.from(new Set((scenarios ?? []).map((s) => s.category)))], [scenarios])

  const reached = useMemo(() => {
    const s = new Set<StageKey>()
    if (sessionId) s.add('observe')
    if (actions.length) { s.add('detect'); s.add('assess') }
    if (actions.some((a) => a.decision !== 'ALLOW')) s.add('intervene')
    if (recSteps.length || recRunning) s.add('recover')
    if (recOutcome) s.add('verify')
    return s
  }, [sessionId, actions, recSteps, recRunning, recOutcome])

  const latest = actions[0] ?? null
  const flagged = actions.find((a) => a.decision !== 'ALLOW') ?? null
  const focus = flagged ?? latest

  const refreshEnv = useCallback(() => { api.environment().then((d) => setEnv(d.resources)).catch(() => {}) }, [])
  const refreshGraph = useCallback((sid: string) => { api.sessionGraph(sid).then(setGraph).catch(() => {}) }, [])
  useEffect(refreshEnv, [refreshEnv, sessionId])

  useEventListener(
    ['action', 'incident', 'recovery', 'agent_status', 'simulation_finished', 'simulation_paused',
     'approval_requested', 'approval_decided', 'taint', 'error'],
    (e: LiveEvent) => {
      const sid = sessionRef.current
      const evSession = e.data?.session_id
      if (sid && evSession && evSession !== sid) return
      switch (e.type) {
        case 'action': {
          const a = e.data as AgentAction
          setActions((prev) => [a, ...prev.filter((x) => x.id !== a.id)])
          if (a.agent_status) setAgentStatus(a.agent_status)
          if (a.trust !== undefined) setTrust(a.trust)
          if (a.tainted) setTainted(true)
          setActiveStage(a.decision === 'ALLOW' ? 'assess' : 'intervene')
          refreshEnv()
          if (sid) refreshGraph(sid)
          break
        }
        case 'incident': setIncident(e.data); break
        case 'agent_status': setAgentStatus(e.data.status); break
        case 'taint': setTainted(true); break
        case 'approval_requested': setAgentStatus('PAUSED'); break
        case 'recovery': {
          const d = e.data
          if (d.stage === 'STARTED') {
            setRecSteps([]); setRecOutcome(undefined); setRecVerification(null); setResidual([]); setRecRunning(true)
            setRecAttempt(d.attempt); setActiveStage('recover')
          } else if (d.stage === 'STEP') {
            setRecSteps((p) => [...p.filter((x) => x.step !== d.step.step), d.step])
          } else {
            setRecRunning(false)
            setRecOutcome(d.outcome)
            setRecVerification(d.verification)
            setResidual(d.residual_risk ?? [])
            setActiveStage('verify')
            refreshEnv()
          }
          break
        }
        case 'simulation_finished':
          setSessionStatus(e.data.status)
          setPrevented(e.data.prevented_steps ?? [])
          if (e.data.agent_status) setAgentStatus(e.data.agent_status)
          setActiveStage((s) => (s === 'recover' || s === 'verify' ? s : null))
          if (sid) refreshGraph(sid)
          break
        case 'simulation_paused': setSessionStatus(e.data.status); break
        case 'error': setRunError(e.data.message); break
      }
    },
  )

  const start = async () => {
    setStarting(true)
    setRunError(null)
    setActions([]); setIncident(null); setRecSteps([]); setRecOutcome(undefined); setRecVerification(null)
    setResidual([]); setGraph(null); setPrevented([]); setTainted(false); setTrust(null)
    setSessionStatus('RUNNING'); setActiveStage('observe')
    try {
      const res = await api.startSimulation(selected)
      setSessionId(res.session_id); setAgentStatus('RUNNING')
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : 'Could not start the simulation.')
      setSessionStatus(null); setActiveStage(null)
    } finally {
      setStarting(false)
    }
  }

  const recover = async (retry = false) => {
    if (!incident) return
    setRetrying(retry); setRecRunning(true)
    try {
      const r = await api.recover(incident.id)
      setRecSteps(r.steps); setRecOutcome(r.outcome); setRecVerification(r.verification)
      setResidual(r.residual_risk); setRecAttempt(r.attempt); refreshEnv()
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : 'Recovery failed.')
    } finally {
      setRecRunning(false); setRetrying(false)
    }
  }

  if (loading && !scenarios) return <Loading label="Loading scenarios…" />
  if (scenErr) return <ErrorState message={scenErr} onRetry={reload} />

  const running = sessionStatus === 'RUNNING'
  const compromised = env ? Object.entries(env).filter(([, s]) => s !== 'HEALTHY') : []
  const shown = (scenarios ?? []).filter((s) => cat === 'all' || s.category === cat)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Simulation Lab</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          A library of {scenarios?.length} controlled scenarios. The agent proposes actions; the safety layer decides
          what actually happens. Everything below is live output from the running pipeline.
        </p>
      </div>

      <Card title="1 · Choose a scenario" subtitle="Each one exercises a different part of the safety layer">
        <div className="mb-3 flex flex-wrap gap-1">
          {categories.map((c) => (
            <button key={c} onClick={() => setCat(c)}
                    className={`rounded-lg px-2.5 py-1 text-[11px] font-semibold capitalize transition-colors ${cat === c ? 'bg-beam/12 text-beam ring-1 ring-inset ring-beam/25' : 'text-slate-500 hover:bg-white/[0.04]'}`}>
              {c.replace(/-/g, ' ')}
            </button>
          ))}
        </div>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {shown.map((s) => {
            const on = selected === s.key
            const tone = CAT_COLOR[s.category] ?? '#0284c7'
            return (
              <button key={s.key} onClick={() => setSelected(s.key)} disabled={running}
                      className={`rounded-xl border p-3 text-left transition-all disabled:opacity-50 ${on ? 'bg-white/[0.05]' : 'border-white/[0.07] bg-ink-850/50 hover:bg-white/[0.03]'}`}
                      style={on ? { borderColor: `${tone}70`, boxShadow: `0 0 0 1px ${tone}35` } : {}}>
                <span className="flex items-center gap-2">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: tone }} />
                  <span className="text-[13px] font-semibold text-slate-100">{s.name}</span>
                </span>
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-500">{s.description}</p>
                <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[9px] text-slate-600">
                  <span>{s.agent.replace('-Agent', '')}</span><span>·</span><span>{s.n_steps} steps</span><span>·</span><span>{s.risk}</span>
                </p>
              </button>
            )
          })}
        </div>

        {scenario && (
          <div className="mt-4 grid gap-3 rounded-xl border border-white/[0.06] bg-ink-850/50 p-4 text-xs sm:grid-cols-2 lg:grid-cols-3">
            {[
              ['Agent & task', `${scenario.agent} — “${scenario.task}”`],
              ['Expected normal behaviour', scenario.expected_normal],
              ['Abnormal behaviour', scenario.abnormal_behavior],
              ['Risk', scenario.risk],
              ['Expected intervention', scenario.expected_intervention],
              ['Recovery method', scenario.recovery_method],
            ].map(([k, v]) => (
              <div key={k}>
                <p className="label">{k}</p>
                <p className="mt-1 leading-relaxed text-slate-300">{v}</p>
              </div>
            ))}
            <div className="sm:col-span-2 lg:col-span-3">
              <p className="label">Planned action sequence</p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {scenario.sequence.map((a, i) => (
                  <span key={a + i} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{i + 1}. {a}</span>
                ))}
              </div>
              {scenario.tags.length > 0 && (
                <p className="mt-2 text-[10px] text-warn">Simulation devices used: {scenario.tags.join(', ').replace(/-/g, ' ')}</p>
              )}
            </div>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-white/[0.06] pt-4">
          <button className="btn-primary px-6" onClick={start} disabled={starting || running}>
            {starting ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            {running ? 'Simulation running…' : 'Start simulation'}
          </button>
          {sessionId && <span className="font-mono text-[11px] text-slate-600">session {sessionId}</span>}
          {sessionStatus && sessionStatus !== 'RUNNING' && (
            <span className="chip bg-white/[0.05] text-slate-400 ring-1 ring-inset ring-white/10">{sessionStatus.replace(/_/g, ' ')}</span>
          )}
          {sessionStatus === 'AWAITING_APPROVAL' && (
            <Link to="/app/approvals" className="btn-ghost text-xs"><UserCheck size={13} /> Decide on the Approvals page</Link>
          )}
        </div>
        {runError && <p className="mt-3 rounded-lg border border-crit/25 bg-crit/[0.07] px-3 py-2 text-sm text-crit">{runError}</p>}
      </Card>

      <Card title="2 · Safety pipeline" subtitle="Stages light up as the run progresses">
        <PipelineStages reached={reached} active={activeStage} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="3 · Agent state" subtitle={scenario?.task ?? 'No task assigned'} icon={<Activity size={14} className="text-slate-500" />}>
          <div className="flex items-center gap-4">
            <RiskMeter score={latest?.risk_score ?? 0} level={(latest?.risk_level ?? 'LOW') as RiskLevel} size={116} />
            <div className="min-w-0 space-y-2">
              <AgentStatusPill status={agentStatus} />
              <div>
                <p className="label">Latest decision</p>
                <div className="mt-0.5 flex items-center gap-2">
                  {latest ? <DecisionBadge decision={latest.decision} /> : <span className="text-xs text-slate-600">—</span>}
                </div>
              </div>
              <div>
                <p className="label">Anomaly (ML) · alignment</p>
                <p className="mt-0.5 font-mono text-xs text-ai">
                  {latest ? `${latest.anomaly_score.toFixed(2)} · ${latest.task_relevance.toFixed(2)}` : '—'}
                </p>
              </div>
            </div>
            {trust !== null && <TrustRing score={trust} />}
          </div>
          {tainted && (
            <p className="mt-3 rounded-lg border border-crit/25 bg-crit/[0.07] px-2.5 py-1.5 text-[11px] text-crit">
              Session TAINTED: untrusted content contained injection indicators.
            </p>
          )}
        </Card>

        <Card title="4 · Behaviour drift" subtitle="Recent window vs this agent's fingerprint" icon={<GitBranch size={14} className="text-slate-500" />}>
          <DriftChart actions={actions} />
        </Card>

        <Card title="5 · Simulated environment" subtitle="Sandboxed state; no real systems" icon={<Database size={14} className="text-slate-500" />}>
          {env ? (
            <>
              <ul className="space-y-1">
                {Object.entries(env).map(([name, state]) => {
                  const ok = state === 'HEALTHY'
                  return (
                    <li key={name} className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-[11px] text-slate-400">{name}</span>
                      <span className={`chip shrink-0 ${ok ? 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25' : 'bg-crit/12 text-crit ring-1 ring-inset ring-crit/30 animate-pulse-ring'}`}>{state}</span>
                    </li>
                  )
                })}
              </ul>
              <p className="mt-2 text-[11px] text-slate-600">
                {compromised.length ? `${compromised.length} resource(s) deviate from baseline.` : 'All resources match their known-good baseline.'}
              </p>
            </>
          ) : <p className="py-6 text-center text-sm text-slate-600">Loading sandbox state…</p>}
        </Card>
      </div>

      <Card title="6 · Behavioural sequence" subtitle="Learned profile vs what happened; prevented steps are dashed">
        <SequenceDeviation actual={[...actions].reverse()} prevented={sessionStatus && sessionStatus !== 'RUNNING' ? prevented : []} />
      </Card>

      {focus && (
        <Card
          title={`7 · ${flagged ? 'Latest intervention' : 'Latest action'}: ${focus.action_type}`}
          subtitle="Why the system decided what it did, and what it prevented"
          action={<DecisionBadge decision={focus.decision} />}
        >
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-3">
              <p className="text-xs leading-relaxed text-slate-400">{focus.explanation}</p>
              <MatchedRules rules={focus.risk_factors.matched_rules} />
              {focus.risk_factors.alternative && (
                <p className="text-xs text-beam">
                  Safer alternative: <span className="font-mono">{focus.risk_factors.alternative.action}</span> — {focus.risk_factors.alternative.note}
                </p>
              )}
            </div>
            <CounterfactualPanel cf={focus.risk_factors.counterfactual} compact />
          </div>
        </Card>
      )}

      <Card title="8 · Live action stream" subtitle="Newest first. Click a row for the full evidence: risk factors, sequence, policy, counterfactual, zero-trust"
            action={running && <span className="chip bg-beam/10 text-beam ring-1 ring-inset ring-beam/25"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-beam" /> Live</span>}>
        <ActionStream actions={actions} emptyHint="Start a simulation to see the agent's actions evaluated in real time." />
      </Card>

      {graph && graph.nodes.length > 2 && (
        <Card title="9 · Behaviour graph" subtitle="Agent → task → actions → tools → resources → permissions; suspicious paths in red">
          <BehaviorGraph data={graph} />
        </Card>
      )}

      {incident && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title={`10 · Incident ${incident.reference}`} icon={<AlertTriangle size={14} className="text-crit" />}
                action={<Link to={`/app/incidents/${incident.id}`} className="btn-ghost !px-3 !py-1.5 text-xs">Details &amp; replay</Link>}>
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="chip bg-crit/12 text-crit ring-1 ring-inset ring-crit/30">{incident.severity}</span>
                <span className="chip bg-white/[0.05] text-slate-400 ring-1 ring-inset ring-white/10">{incident.kind}</span>
                <span className="font-mono text-xs text-slate-400">risk {Math.round(incident.risk_score)}/100</span>
              </div>
              <p className="text-sm font-medium text-slate-200">{incident.title}</p>
              <p className="text-xs leading-relaxed text-slate-400">{incident.reason}</p>
              {!recSteps.length && !recRunning && (
                <button className="btn-safe" onClick={() => recover(false)}><RotateCcw size={14} /> Start recovery</button>
              )}
            </div>
          </Card>
          <Card title="11 · Recovery & verification" subtitle="Each step is executed and independently verified; success is never assumed" icon={<RotateCcw size={14} className="text-safe" />}>
            {recSteps.length || recRunning ? (
              <RecoveryChecklist steps={recSteps} running={recRunning} outcome={recOutcome} verification={recVerification}
                                 residual={residual} attempt={recAttempt} onRetry={() => recover(true)} retrying={retrying} />
            ) : <p className="py-6 text-center text-sm text-slate-600">Recovery has not started for this incident.</p>}
          </Card>
        </div>
      )}
    </div>
  )
}
