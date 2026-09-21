import { Ban, CheckCircle2, Fingerprint, Loader2, Play, ShieldCheck, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { ActionStream } from '../components/ActionStream'
import {
  AgentStatusPill, Bar, Card, ErrorState, Loading, RiskMeter, TRUST_COLOR, TrustRing,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type { AgentAction, BaselineResult, RiskLevel } from '../types'

const tip = { backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12, color: '#0f172a' }

const COMP_LABEL: Record<string, string> = {
  incident_penalty: 'Incidents (recency-weighted, less if recovered)',
  violation_penalty: 'Policy-violation rate',
  anomaly_penalty: 'Anomaly frequency',
  block_penalty: 'Blocked-action rate',
  drift_penalty: 'Latest behavioural drift',
  clean_session_credit: 'Clean completed sessions',
}

export default function AgentMonitor() {
  const { data: agents, error, loading, reload } = useApi(() => api.agents(), [])
  const [sel, setSel] = useState<string | null>(null)
  const [actions, setActions] = useState<AgentAction[]>([])
  const [results, setResults] = useState<BaselineResult[] | null>(null)
  const [learning, setLearning] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const agentId = sel ?? agents?.[0]?.id ?? null
  const profile = useApi(() => (agentId ? api.agentProfile(agentId) : Promise.resolve(null)), [agentId])

  useEffect(() => {
    api.actions({ limit: 80 }).then(setActions).catch(() => {})
  }, [])

  const refresh = () => { reload(); profile.reload() }
  useEventListener(['action'], (e) => {
    const a = e.data as AgentAction
    setActions((p) => [a, ...p.filter((x) => x.id !== a.id)].slice(0, 80))
  })
  useEventListener(['agent_status', 'simulation_finished', 'approval_decided', 'recovery', 'incident'], refresh)

  const learn = async () => {
    if (!agentId) return
    setLearning(true); setMsg(null)
    try {
      const r = await api.updateBaseline(agentId)
      setResults(r.results)
      profile.reload()
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : 'Baseline update failed.')
    } finally {
      setLearning(false)
    }
  }

  if (loading && !agents) return <Loading label="Loading agents…" />
  if (error) return <ErrorState message={error} onRetry={reload} />

  const p = profile.data
  const agent = p?.agent
  const mine = actions.filter((a) => a.agent_id === agentId)
  const latest = mine[0]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">Agent Monitor</h1>
          <p className="mt-1 text-sm text-slate-500">Per-agent behavioural fingerprint, trust, drift and adaptive baseline.</p>
        </div>
        <Link to="/app/lab" className="btn-ghost"><Play size={14} /> Run a simulation</Link>
      </div>

      <div className="flex flex-wrap gap-2">
        {agents?.map((a) => (
          <button key={a.id} onClick={() => { setSel(a.id); setResults(null) }}
                  className={`flex items-center gap-3 rounded-xl border px-3 py-2 text-left transition-colors ${a.id === agentId ? 'border-beam/40 bg-beam/[0.06]' : 'border-white/[0.07] bg-ink-850/50 hover:bg-white/[0.03]'}`}>
            <span className="grid h-8 w-8 place-items-center rounded-lg font-mono text-xs font-bold" style={{ color: TRUST_COLOR(a.trust), backgroundColor: `${TRUST_COLOR(a.trust)}18` }}>{Math.round(a.trust)}</span>
            <span><span className="block text-sm font-semibold text-slate-100">{a.name}</span>
              <span className="block text-[11px] text-slate-500">{a.trust_band} · {a.status}</span></span>
          </button>
        ))}
      </div>

      {profile.loading && !p ? <Loading label="Loading profile…" /> : profile.error ? <ErrorState message={profile.error} onRetry={profile.reload} /> : p && agent && (
        <>
          <div className="grid gap-4 lg:grid-cols-3">
            <Card title={agent.name} subtitle={agent.purpose} icon={<ShieldCheck size={14} className="text-beam" />}>
              <div className="flex items-center gap-4">
                <RiskMeter score={latest?.risk_score ?? 0} level={(latest?.risk_level ?? 'LOW') as RiskLevel} size={110} />
                <div className="min-w-0 space-y-2">
                  <AgentStatusPill status={agent.status} />
                  <div><p className="label">Current task</p><p className="mt-0.5 text-xs text-slate-300">{agent.current_task ?? '—'}</p></div>
                  <div><p className="label">Last action</p><p className="mt-0.5 truncate font-mono text-xs text-slate-300">{agent.current_action?.action_type ?? '—'}</p></div>
                </div>
              </div>
            </Card>

            <Card title="Trust score" subtitle="Computed from recorded history, never random">
              <div className="flex items-center gap-4">
                <TrustRing score={p.trust.score} band={p.trust.band} size={96} />
                <div className="min-w-0 flex-1 space-y-1.5">
                  <p className="font-mono text-xs font-semibold" style={{ color: TRUST_COLOR(p.trust.score) }}>{p.trust.band}</p>
                  {Object.entries(p.trust.components).map(([k, v]) => (
                    <div key={k} className="flex items-baseline justify-between gap-2 text-[11px]">
                      <span className="truncate text-slate-500">{COMP_LABEL[k] ?? k}</span>
                      <span className={`font-mono tabular-nums ${v < 0 ? 'text-crit' : v > 0 ? 'text-safe' : 'text-slate-600'}`}>{v > 0 ? '+' : ''}{v}</span>
                    </div>
                  ))}
                </div>
              </div>
              <p className="mt-3 text-[10px] leading-relaxed text-slate-600">
                Below 40 trust, medium-risk actions need a human (rule R13). Trust rises again as the agent behaves.
              </p>
            </Card>

            <Card title="Trust over time" subtitle="Snapshot after each incident, recovery and session">
              {p.trust_history.length < 2 ? <p className="py-8 text-center text-xs text-slate-600">Needs at least two snapshots.</p> : (
                <ResponsiveContainer width="100%" height={150}>
                  <LineChart data={p.trust_history.map((t, i) => ({ i: i + 1, score: t.score, event: t.event }))} margin={{ left: -18, right: 6 }}>
                    <CartesianGrid stroke="rgba(15,23,42,0.08)" vertical={false} />
                    <XAxis dataKey="i" stroke="#64748b" fontSize={10} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={10} domain={[0, 100]} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={tip} labelFormatter={(_l, pl) => `${pl?.[0]?.payload?.event ?? ''}`} />
                    <ReferenceLine y={40} stroke="#dc2626" strokeDasharray="3 3" />
                    <Line type="stepAfter" dataKey="score" stroke="#0284c7" strokeWidth={2} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Behavioural fingerprint" subtitle={`v${p.fingerprint.version} · ${p.fingerprint.source} · effective sample ${Math.round(p.fingerprint.n_actions)} actions`}
                  icon={<Fingerprint size={14} className="text-ai" />}>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <p className="label">Normal actions</p>
                  <div className="mt-1.5 space-y-1">
                    {p.fingerprint.top_actions.map((a) => (
                      <div key={a.action} className="flex items-center gap-2 text-[11px]">
                        <span className="w-40 shrink-0 truncate font-mono text-slate-400">{a.action}</span>
                        <span className="flex-1"><Bar value={a.share * 100} color="#7c3aed" /></span>
                        <span className="w-9 shrink-0 text-right font-mono text-slate-500">{(a.share * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="space-y-3">
                  <div>
                    <p className="label">Normal resources</p>
                    <p className="mt-1 font-mono text-[11px] text-slate-400">{p.fingerprint.resource_prefixes.map((r) => `${r.prefix} ${(r.share * 100).toFixed(0)}%`).join(' · ')}</p>
                  </div>
                  <div>
                    <p className="label">Normal tools</p>
                    <p className="mt-1 font-mono text-[11px] text-slate-400">{p.fingerprint.top_tools.map((t) => t.tool).join(' · ')}</p>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-[11px]">
                    <div><p className="label">Permission</p><p className="mt-0.5 font-mono text-slate-300">{p.fingerprint.mean_permission.toFixed(2)}</p></div>
                    <div><p className="label">Interval</p><p className="mt-0.5 font-mono text-slate-300">{p.fingerprint.typical_interval_s}s</p></div>
                    <div><p className="label">Normal drift</p><p className="mt-0.5 font-mono text-slate-300">{Math.round(p.fingerprint.reference_drift.mean * 100)}%</p></div>
                  </div>
                  <div>
                    <p className="label">Most common transitions</p>
                    <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                      {p.fingerprint.top_transitions.slice(0, 5).map((t) => `${t.from.replace('<START>', 'START')}→${t.to}`).join('  ·  ')}
                    </p>
                  </div>
                </div>
              </div>
            </Card>

            <Card title="Drift, session by session" subtitle="Peak drift vs this agent's alert threshold">
              {p.drift_history.length === 0 ? <p className="py-8 text-center text-xs text-slate-600">Recorded when a session ends.</p> : (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={p.drift_history.map((d, i) => ({ i: i + 1, peak: Math.round(d.peak * 100), thr: Math.round(d.threshold * 100) }))} margin={{ left: -18, right: 6 }}>
                    <CartesianGrid stroke="rgba(15,23,42,0.08)" vertical={false} />
                    <XAxis dataKey="i" stroke="#64748b" fontSize={10} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={10} domain={[0, 100]} tickLine={false} axisLine={false} unit="%" />
                    <Tooltip contentStyle={tip} formatter={(v: number) => `${v}%`} />
                    <ReferenceLine y={Math.round(p.fingerprint.drift_threshold * 100)} stroke="#ca8a04" strokeDasharray="4 3" />
                    <Line type="monotone" dataKey="peak" name="Peak drift" stroke="#ea580c" strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </Card>
          </div>

          <Card title="Adaptive baseline" subtitle="Normal is not frozen, but suspicious behaviour is never learned as normal"
                action={<button className="btn-primary !py-1.5 text-xs" onClick={learn} disabled={learning}>
                  {learning ? <Loader2 size={13} className="animate-spin" /> : <Fingerprint size={13} />} Offer last 5 sessions to the baseline</button>}>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px]">
                  <thead><tr className="border-b border-white/[0.06]"><th className="th">Version</th><th className="th">Source</th><th className="th">Divergence from v1</th><th className="th">State</th></tr></thead>
                  <tbody>
                    {p.baselines.map((b) => (
                      <tr key={b.version} className="border-b border-white/[0.04]">
                        <td className="td font-mono text-xs">v{b.version}</td>
                        <td className="td text-xs">{b.source}</td>
                        <td className="td font-mono text-xs">{b.anchor_divergence.toFixed(4)}</td>
                        <td className="td"><span className={`chip ${b.active ? 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25' : 'bg-white/5 text-slate-500 ring-1 ring-inset ring-white/10'}`}>{b.active ? 'active' : 'superseded'}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-[10px] leading-relaxed text-slate-600">
                  A session is learned only if it completed with no block, hold, incident, taint or high drift, and the result stays
                  within a limit of both the previous version and the ORIGINAL v1 (defeats slow poisoning).
                </p>
              </div>
              <div>
                {msg && <p className="mb-2 text-xs text-crit">{msg}</p>}
                {!results ? <p className="py-6 text-center text-xs text-slate-600">Offer recent sessions to see which are accepted or rejected, and why.</p> : (
                  <ul className="space-y-2">
                    {results.map((r) => (
                      <li key={r.session_id} className="rounded-lg border border-white/[0.06] bg-ink-850/60 p-2.5 text-xs">
                        <p className="flex items-center gap-1.5">
                          {r.accepted ? <CheckCircle2 size={14} className="text-safe" /> : <XCircle size={14} className="text-crit" />}
                          <span className="font-mono text-slate-400">{r.session_id}</span>
                          <span className={r.accepted ? 'text-safe' : 'text-crit'}>{r.accepted ? `learned → v${r.version}` : 'not learned'}</span>
                        </p>
                        {r.reasons.map((x) => <p key={x} className="mt-1 flex gap-1.5 text-[11px] text-slate-500"><Ban size={11} className="mt-0.5 shrink-0 text-crit" />{x}</p>)}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Capability set" subtitle="What policy sanctions for this agent">
              <p className="label">Allowed</p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {agent.allowed_actions.map((a) => <span key={a} className="rounded bg-safe/10 px-1.5 py-0.5 font-mono text-[10px] text-safe ring-1 ring-inset ring-safe/20"><CheckCircle2 size={9} className="mr-1 inline" />{a}</span>)}
              </div>
              <p className="label mt-4">Restricted</p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {agent.restricted_actions.map((a) => <span key={a} className="rounded bg-crit/10 px-1.5 py-0.5 font-mono text-[10px] text-crit ring-1 ring-inset ring-crit/20"><Ban size={9} className="mr-1 inline" />{a}</span>)}
              </div>
            </Card>
            <Card title="Live action stream" subtitle="This agent's recent actions">
              <div className="max-h-[420px] overflow-y-auto pr-1">
                <ActionStream actions={mine.slice(0, 25)} emptyHint="No actions recorded for this agent yet." />
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
