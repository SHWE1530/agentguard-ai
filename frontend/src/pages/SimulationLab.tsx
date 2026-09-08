import {
  Activity, AlertTriangle, BrainCircuit, CheckCircle2, Database, Eye, Gauge,
  Loader2, Play, RotateCcw, ShieldCheck, Siren, Square, UserCheck,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ActionStream, SequenceDeviation } from '../components/ActionStream'
import {
  AgentStatusPill, Card, ErrorState, Loading, RiskMeter, VerifyBadge, fmtTime,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type {
  AgentAction, EnvironmentState, Incident, LiveEvent, RiskLevel, Scenario,
} from '../types'

/* -------------------------------------------------------- pipeline stages */

const STAGES = [
  { key: 'observe', label: 'Observe', icon: Eye, color: '#38bdf8' },
  { key: 'detect', label: 'Detect', icon: BrainCircuit, color: '#8b5cf6' },
  { key: 'assess', label: 'Assess', icon: Gauge, color: '#eab308' },
  { key: 'intervene', label: 'Intervene', icon: Siren, color: '#f97316' },
  { key: 'recover', label: 'Recover', icon: RotateCcw, color: '#22c55e' },
  { key: 'verify', label: 'Verify', icon: ShieldCheck, color: '#22c55e' },
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
                className={`grid h-9 w-9 place-items-center rounded-lg ring-1 ring-inset transition-all duration-300 ${
                  now ? 'scale-110' : ''
                }`}
                style={{
                  color: on ? color : '#3a4560',
                  backgroundColor: on ? `${color}18` : 'rgba(255,255,255,0.02)',
                  boxShadow: now ? `0 0 14px ${color}55` : 'none',
                  ['--tw-ring-color' as any]: on ? `${color}45` : 'rgba(255,255,255,0.06)',
                }}
              >
                <Icon size={16} />
              </span>
              <span
                className="text-[10px] font-semibold uppercase tracking-wide"
                style={{ color: on ? color : '#475569' }}
              >
                {label}
              </span>
            </div>
            {i < STAGES.length - 1 && (
              <span
                className="hidden h-px w-4 sm:block"
                style={{ backgroundColor: on ? `${color}55` : 'rgba(255,255,255,0.07)' }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------ recovery box */

const RECOVERY_STEPS = [
  { stage: 'STARTED', label: 'Threat detected · agent paused' },
  { stage: 'RESTORED', label: 'Simulated state restoration' },
  { stage: 'VERIFIED', label: 'State verification' },
] as const

function RecoveryPanel({ stages, verification }: { stages: string[]; verification: any }) {
  return (
    <div className="space-y-2.5">
      {RECOVERY_STEPS.map(({ stage, label }) => {
        const done = stages.includes(stage) || (stage === 'VERIFIED' && stages.includes('VERIFICATION_FAILED'))
        const failed = stage === 'VERIFIED' && stages.includes('VERIFICATION_FAILED')
        const running = !done && stages.length > 0 && !stages.includes('VERIFIED')
        return (
          <div key={stage} className="flex items-center gap-2.5">
            <span
              className={`grid h-6 w-6 shrink-0 place-items-center rounded-full text-ink-950 ${
                failed ? 'bg-crit' : done ? 'bg-safe' : running ? 'bg-warn' : 'bg-ink-700'
              }`}
            >
              {failed ? (
                <AlertTriangle size={12} className="text-white" />
              ) : done ? (
                <CheckCircle2 size={13} />
              ) : running ? (
                <Loader2 size={12} className="animate-spin text-ink-950" />
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-slate-600" />
              )}
            </span>
            <span className={`text-sm ${done ? 'text-slate-200' : 'text-slate-500'}`}>{label}</span>
          </div>
        )
      })}
      {verification && (
        <div className="mt-3 rounded-lg border border-white/[0.06] bg-ink-850/60 p-3">
          <VerifyBadge verified={verification.verified} />
          <p className="mt-2 text-xs leading-relaxed text-slate-400">{verification.summary}</p>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {verification.checks?.map((c: any) => (
              <li key={c.resource} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="truncate font-mono text-slate-500">{c.resource}</span>
                <span className={c.passed ? 'text-safe' : 'text-crit'}>
                  {c.passed ? 'PASS' : `FAIL (${c.observed})`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------- page */

export default function SimulationLab() {
  const { data: scenarios, error: scenErr, loading, reload } = useApi(() => api.scenarios(), [])
  const [selected, setSelected] = useState<string>('critical')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [planned, setPlanned] = useState<string[]>([])
  const [scenarioName, setScenarioName] = useState<string>('')
  const [task, setTask] = useState<string>('')
  const [actions, setActions] = useState<AgentAction[]>([])
  const [agentStatus, setAgentStatus] = useState('IDLE')
  const [sessionStatus, setSessionStatus] = useState<string | null>(null)
  const [incident, setIncident] = useState<Incident | null>(null)
  const [recoveryStages, setRecoveryStages] = useState<string[]>([])
  const [verification, setVerification] = useState<any>(null)
  const [env, setEnv] = useState<EnvironmentState['resources'] | null>(null)
  const [log, setLog] = useState<{ t: string; msg: string; tone: string }[]>([])
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [activeStage, setActiveStage] = useState<StageKey | null>(null)
  const sessionRef = useRef<string | null>(null)
  sessionRef.current = sessionId

  const reached = useMemo(() => {
    const s = new Set<StageKey>()
    if (sessionId) s.add('observe')
    if (actions.length) {
      s.add('detect')
      s.add('assess')
    }
    if (actions.some((a) => a.action_status !== 'ALLOWED')) s.add('intervene')
    if (recoveryStages.includes('STARTED')) s.add('recover')
    if (recoveryStages.includes('VERIFIED') || recoveryStages.includes('VERIFICATION_FAILED'))
      s.add('verify')
    return s
  }, [sessionId, actions, recoveryStages])

  const pushLog = useCallback((msg: string, tone = 'text-slate-400') => {
    setLog((l) => [...l, { t: new Date().toLocaleTimeString(), msg, tone }].slice(-40))
  }, [])

  const currentRisk = actions.length ? actions[0] : null

  /* --------------------------------------------------------- live events */
  useEventListener(
    ['action', 'incident', 'recovery', 'agent_status', 'simulation_finished',
     'approval_requested', 'approval_decided', 'error'],
    (e: LiveEvent) => {
      const sid = sessionRef.current
      const evSession = e.data?.session_id
      if (sid && evSession && evSession !== sid) return

      switch (e.type) {
        case 'action': {
          const a = e.data as AgentAction
          setActions((prev) => [a, ...prev.filter((x) => x.id !== a.id)])
          if (a.agent_status) setAgentStatus(a.agent_status)
          setActiveStage(a.action_status === 'ALLOWED' ? 'assess' : 'intervene')
          pushLog(
            `${a.action_type} → ${a.action_status} · anomaly ${a.anomaly_score.toFixed(2)} · risk ${a.risk_score}`,
            a.action_status === 'BLOCKED' ? 'text-crit' :
            a.action_status === 'PENDING_APPROVAL' ? 'text-ai' :
            a.risk_level === 'MEDIUM' ? 'text-warn' : 'text-safe',
          )
          break
        }
        case 'incident':
          setIncident(e.data)
          pushLog(
            e.data.escalated
              ? `Incident ${e.data.reference} escalated — now ${e.data.title}`
              : `Incident ${e.data.reference} raised — ${e.data.severity}`,
            'text-crit',
          )
          break
        case 'agent_status':
          setAgentStatus(e.data.status)
          break
        case 'approval_requested':
          setAgentStatus('PAUSED')
          pushLog(`Human approval required for ${e.data.action_type}`, 'text-ai')
          break
        case 'approval_decided':
          pushLog(`Operator ${e.data.status.toLowerCase()} ${e.data.action_type}`, 'text-ai')
          break
        case 'recovery':
          setActiveStage(e.data.stage === 'VERIFIED' ? 'verify' : 'recover')
          setRecoveryStages((prev) => [...prev, e.data.stage])
          if (e.data.restored_state) setEnv(e.data.restored_state)
          if (e.data.verification) setVerification(e.data.verification)
          pushLog(
            `Recovery: ${e.data.stage.replace(/_/g, ' ').toLowerCase()}`,
            e.data.stage === 'VERIFIED' ? 'text-safe' :
            e.data.stage === 'VERIFICATION_FAILED' ? 'text-crit' : 'text-slate-300',
          )
          break
        case 'simulation_finished':
          setSessionStatus(e.data.status)
          setActiveStage(null)
          pushLog(`Simulation finished — session ${e.data.status}`, 'text-slate-300')
          break
        case 'error':
          setRunError(e.data.message)
          break
      }
    },
  )

  // Keep the sandbox panel current.
  useEffect(() => {
    api.environment().then((d) => setEnv(d.resources)).catch(() => {})
  }, [sessionId])

  useEffect(() => {
    if (!sessionId) return
    const t = setInterval(() => {
      api.environment().then((d) => setEnv(d.resources)).catch(() => {})
    }, 4000)
    return () => clearInterval(t)
  }, [sessionId])

  const start = async () => {
    setStarting(true)
    setRunError(null)
    setActions([])
    setIncident(null)
    setRecoveryStages([])
    setVerification(null)
    setSessionStatus('RUNNING')
    setLog([])
    setActiveStage('observe')
    try {
      const res = await api.startSimulation(selected)
      setSessionId(res.session_id)
      setPlanned(res.planned_sequence)
      setScenarioName(res.scenario_name)
      setTask(res.task)
      setAgentStatus('RUNNING')
      pushLog(`Agent started · task: ${res.task}`, 'text-beam')
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : 'Could not start the simulation.')
      setSessionStatus(null)
      setActiveStage(null)
    } finally {
      setStarting(false)
    }
  }

  const manualRecover = async () => {
    if (!incident) return
    try {
      await api.recover(incident.id)
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : 'Recovery failed.')
    }
  }

  if (loading && !scenarios) return <Loading label="Loading scenarios…" />
  if (scenErr) return <ErrorState message={scenErr} onRetry={reload} />

  const running = sessionStatus === 'RUNNING'
  const compromised = env ? Object.entries(env).filter(([, s]) => s !== 'HEALTHY') : []

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Simulation Lab</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Pick a scenario and start it. The agent proposes actions; the safety layer decides what
          actually happens. Everything below is live output from the running pipeline.
        </p>
      </div>

      {/* Step 1 — choose */}
      <Card
        title="1 · Choose a scenario"
        subtitle="Each one exercises a different part of the safety layer"
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {scenarios?.map((s: Scenario) => {
            const on = selected === s.key
            const tone =
              s.key === 'normal' ? '#22c55e' :
              s.key === 'abnormal' ? '#f97316' :
              s.key === 'critical' ? '#ef4444' : '#8b5cf6'
            const Icon =
              s.key === 'normal' ? ShieldCheck :
              s.key === 'abnormal' ? AlertTriangle :
              s.key === 'critical' ? Siren : UserCheck
            return (
              <button
                key={s.key}
                onClick={() => setSelected(s.key)}
                disabled={running}
                className={`rounded-xl border p-4 text-left transition-all disabled:opacity-50 ${
                  on ? 'bg-white/[0.05]' : 'border-white/[0.07] bg-ink-850/50 hover:bg-white/[0.03]'
                }`}
                style={on ? { borderColor: `${tone}70`, boxShadow: `0 0 0 1px ${tone}35` } : {}}
              >
                <span className="flex items-center gap-2">
                  <Icon size={16} style={{ color: tone }} />
                  <span className="text-sm font-semibold text-slate-100">{s.name}</span>
                </span>
                <p className="mt-2 text-xs leading-relaxed text-slate-500">{s.summary}</p>
                <p className="mt-2 text-[11px] leading-relaxed" style={{ color: tone }}>
                  {s.expected}
                </p>
                <div className="mt-2.5 flex flex-wrap gap-1">
                  {s.sequence.map((a) => (
                    <span
                      key={a}
                      className="rounded bg-black/30 px-1.5 py-0.5 font-mono text-[9px] text-slate-500"
                    >
                      {a}
                    </span>
                  ))}
                </div>
              </button>
            )
          })}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-white/[0.06] pt-4">
          <button className="btn-primary px-6" onClick={start} disabled={starting || running}>
            {starting ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
            {running ? 'Simulation running…' : 'Start simulation'}
          </button>
          {sessionId && (
            <span className="font-mono text-[11px] text-slate-600">session {sessionId}</span>
          )}
          {sessionStatus && sessionStatus !== 'RUNNING' && (
            <span className="chip bg-white/[0.05] text-slate-400 ring-1 ring-inset ring-white/10">
              <Square size={11} /> {sessionStatus}
            </span>
          )}
        </div>
        {runError && (
          <p className="mt-3 rounded-lg border border-crit/25 bg-crit/[0.07] px-3 py-2 text-sm text-crit">
            {runError}
          </p>
        )}
      </Card>

      {/* Step 2 — pipeline */}
      <Card title="2 · Safety pipeline" subtitle="Stages light up as the run progresses">
        <PipelineStages reached={reached} active={activeStage} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Agent + risk */}
        <Card
          title="3 · Agent state"
          subtitle={task || 'No task assigned yet'}
          icon={<Activity size={14} className="text-slate-500" />}
        >
          <div className="flex items-center gap-5">
            <RiskMeter
              score={currentRisk?.risk_score ?? 0}
              level={(currentRisk?.risk_level ?? 'LOW') as RiskLevel}
            />
            <div className="min-w-0 space-y-2.5">
              <div>
                <p className="label">Agent</p>
                <p className="mt-0.5 text-sm font-semibold text-slate-100">OpsAssist-Agent</p>
              </div>
              <AgentStatusPill status={agentStatus} />
              <div>
                <p className="label">Latest action</p>
                <p className="mt-0.5 truncate font-mono text-xs text-slate-300">
                  {currentRisk?.action_type ?? '—'}
                </p>
              </div>
              <div>
                <p className="label">Anomaly score (ML)</p>
                <p className="mt-0.5 font-mono text-sm text-ai">
                  {currentRisk ? currentRisk.anomaly_score.toFixed(2) : '—'}
                </p>
              </div>
              <p className="text-[10px] text-slate-600">
                {scenarioName ? `Scenario: ${scenarioName}` : 'No scenario running'}
              </p>
            </div>
          </div>
        </Card>

        {/* Sequence deviation */}
        <Card
          title="4 · Behavioural sequence"
          subtitle="Learned profile vs. what actually happened"
        >
          <SequenceDeviation planned={planned} actual={[...actions].reverse()} />
        </Card>

        {/* Sandbox */}
        <Card
          title="5 · Simulated environment"
          subtitle="Sandboxed state — no real systems"
          icon={<Database size={14} className="text-slate-500" />}
        >
          {env ? (
            <>
              <ul className="space-y-1.5">
                {Object.entries(env).map(([name, state]) => {
                  const ok = state === 'HEALTHY'
                  return (
                    <li key={name} className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-[11px] text-slate-400">{name}</span>
                      <span
                        className={`chip shrink-0 transition-colors ${
                          ok
                            ? 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25'
                            : 'bg-crit/12 text-crit ring-1 ring-inset ring-crit/30 animate-pulse-ring'
                        }`}
                      >
                        {state}
                      </span>
                    </li>
                  )
                })}
              </ul>
              <p className="mt-3 text-[11px] text-slate-600">
                {compromised.length
                  ? `${compromised.length} resource(s) deviate from baseline.`
                  : 'All resources match their known-good baseline.'}
              </p>
            </>
          ) : (
            <p className="py-6 text-center text-sm text-slate-600">Loading sandbox state…</p>
          )}
        </Card>
      </div>

      {/* Live stream */}
      <Card
        title="6 · Live action stream"
        subtitle="Newest first — click any row to see exactly why the system decided what it did"
        action={
          running && (
            <span className="chip bg-beam/10 text-beam ring-1 ring-inset ring-beam/25">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-beam" /> Live
            </span>
          )
        }
      >
        <ActionStream
          actions={actions}
          emptyHint="Start a simulation to see the agent's actions evaluated in real time."
        />
      </Card>

      {/* Incident + recovery */}
      {incident && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card
            title="7 · Incident raised"
            subtitle={incident.reference}
            icon={<Siren size={14} className="text-crit" />}
            action={
              <Link to={`/app/incidents/${incident.id}`} className="btn-ghost !px-3 !py-1.5 text-xs">
                View details
              </Link>
            }
          >
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="chip bg-crit/12 text-crit ring-1 ring-inset ring-crit/30">
                  {incident.severity}
                </span>
                <span className="font-mono text-xs text-slate-400">
                  risk {Math.round(incident.risk_score)}/100
                </span>
                <span className="chip bg-white/[0.05] text-slate-400 ring-1 ring-inset ring-white/10">
                  {incident.status}
                </span>
              </div>
              <p className="text-sm font-medium text-slate-200">{incident.title}</p>
              <p className="text-xs leading-relaxed text-slate-400">{incident.reason}</p>
              {!recoveryStages.length && (
                <button className="btn-safe" onClick={manualRecover}>
                  <RotateCcw size={14} /> Start recovery
                </button>
              )}
            </div>
          </Card>

          <Card
            title="8 · Recovery & verification"
            subtitle="State is re-inspected — success is never assumed"
            icon={<RotateCcw size={14} className="text-safe" />}
          >
            {recoveryStages.length ? (
              <RecoveryPanel stages={recoveryStages} verification={verification} />
            ) : (
              <p className="py-6 text-center text-sm text-slate-600">
                Recovery has not started for this incident yet.
              </p>
            )}
          </Card>
        </div>
      )}

      {/* Console log */}
      {log.length > 0 && (
        <Card title="Run log" subtitle="Plain-language trace of what the safety layer did">
          <ul className="max-h-56 space-y-1 overflow-y-auto font-mono text-[11px]">
            {log.map((l, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0 text-slate-700">{l.t}</span>
                <span className={l.tone}>{l.msg}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {sessionId && selected === 'approval' && (
        <p className="text-center text-sm text-slate-500">
          Waiting on a decision?{' '}
          <Link to="/app/approvals" className="text-beam hover:underline">
            Go to the Human Approval page →
          </Link>
        </p>
      )}
      <p className="pb-2 text-center text-[11px] text-slate-700">
        Last event {log.length ? log[log.length - 1].t : fmtTime(new Date().toISOString())} ·
        controlled simulation, no real systems affected
      </p>
    </div>
  )
}
