import {
  Activity, BrainCircuit, CheckCircle2, Database, Gauge, ShieldX, Siren, Timer, UserCheck,
} from 'lucide-react'
import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { AgentStatusPill, Card, ErrorState, Loading, RISK_COLOR, StatCard, TrustRing } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { api } from '../services/api'
import type { RiskLevel } from '../types'

const tip = {
  backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12, color: '#0f172a',
}
const DECISION_FILL: Record<string, string> = {
  ALLOW: '#16a34a', MONITOR: '#ca8a04', REQUIRE_APPROVAL: '#7c3aed', BLOCK: '#ea580c', TERMINATE: '#dc2626',
}

export default function Dashboard() {
  const { data: m, error, loading, reload } = useApi(() => api.metrics(), [])

  useEventListener(['action', 'incident', 'recovery', 'approval_decided', 'agent_status', 'simulation_finished'], () => reload())
  useEffect(() => {
    const t = setInterval(reload, 15000)
    return () => clearInterval(t)
  }, [reload])

  if (loading && !m) return <Loading label="Loading system metrics…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!m) return null

  const env = Object.entries(m.environment)
  const compromised = env.filter(([, s]) => s !== 'HEALTHY' && s !== 'FAILED_OVER')
  // drift history, one series point per session, by agent
  const driftRows = m.drift_history.map((d, i) => ({
    i: i + 1, agent: d.agent, peak: Math.round(d.peak * 100), threshold: Math.round(d.threshold * 100),
  }))

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">System Dashboard</h1>
          <p className="mt-1 text-sm text-slate-500">Every figure is computed from recorded pipeline output. Nothing is hard-coded.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`chip ring-1 ring-inset ${compromised.length ? 'bg-crit/10 text-crit ring-crit/25' : 'bg-safe/10 text-safe ring-safe/25'}`}>
            {compromised.length ? <ShieldX size={12} /> : <CheckCircle2 size={12} />}
            {compromised.length ? `${compromised.length} resource(s) compromised` : 'Sandbox healthy'}
          </span>
          <Link to="/app/judge" className="btn-primary">Judge mode</Link>
        </div>
      </div>

      {/* agent health + trust */}
      <div className="grid gap-3 md:grid-cols-2">
        {m.agents.map((a) => (
          <div key={a.id} className="card card-pad flex items-center gap-4">
            <TrustRing score={a.trust} band={a.trust_band} size={92} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="truncate text-sm font-semibold text-slate-100">{a.name}</p>
                <AgentStatusPill status={a.status} />
              </div>
              <p className="mt-0.5 truncate text-xs text-slate-500">{a.purpose}</p>
              <dl className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                <div><dt className="label">Trust band</dt><dd className="mt-0.5 font-mono text-slate-300">{a.trust_band}</dd></div>
                <div><dt className="label">Fingerprint</dt><dd className="mt-0.5 font-mono text-slate-300">v{a.baseline_version}</dd></div>
                <div>
                  <dt className="label">Drift (last)</dt>
                  <dd className={`mt-0.5 font-mono ${a.last_drift_peak !== null && a.last_drift_peak >= a.drift_threshold ? 'text-warn' : 'text-slate-300'}`}>
                    {a.last_drift_peak === null ? '—' : `${Math.round(a.last_drift_peak * 100)}%`}
                    <span className="text-slate-600"> / {Math.round(a.drift_threshold * 100)}%</span>
                  </dd>
                </div>
              </dl>
            </div>
            {a.active_incidents > 0 && (
              <Link to="/app/incidents" className="chip shrink-0 bg-crit/12 text-crit ring-1 ring-inset ring-crit/30">
                <Siren size={11} /> {a.active_incidents}
              </Link>
            )}
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Agent actions" value={m.total_actions} hint={`${m.total_sessions} sessions · ${m.suspicious_actions} high/critical`} icon={<Activity size={15} />} />
        <StatCard label="Blocked actions" value={m.blocked_actions} tone={m.blocked_actions ? 'crit' : 'default'}
                  hint="Stopped before execution" icon={<ShieldX size={15} />} />
        <StatCard label="Active incidents" value={m.active_incidents} tone={m.active_incidents ? 'high' : 'safe'}
                  hint={`${m.total_incidents} total · ${m.critical_incidents} critical`} icon={<Siren size={15} />} />
        <StatCard label="Recovery success" value={m.recovery_success_rate === null ? '—' : `${m.recovery_success_rate}%`}
                  tone={m.recovery_success_rate === 100 ? 'safe' : m.recovery_success_rate === null ? 'default' : 'warn'}
                  hint={m.recovery_success_rate === null ? 'No recovery attempted yet'
                    : `${m.recovered_incidents} verified · ${m.recovery_partial} partial · ${m.recovery_failed} failed`}
                  icon={<CheckCircle2 size={15} />} />
        <StatCard label="Avg anomaly score" value={m.avg_anomaly_score.toFixed(3)} tone="ai" hint="Isolation Forest output" icon={<BrainCircuit size={15} />} />
        <StatCard label="Avg risk score" value={m.avg_risk_score.toFixed(1)} tone={m.avg_risk_score >= 60 ? 'high' : m.avg_risk_score >= 30 ? 'warn' : 'safe'}
                  hint="Multi-layer fusion, 0–100" icon={<Gauge size={15} />} />
        <StatCard label="Pending approvals" value={m.pending_approvals} tone={m.pending_approvals ? 'ai' : 'default'}
                  hint={m.human_approval_rate === null ? 'No human decision yet' : `${m.human_approval_rate}% of decisions approved`} icon={<UserCheck size={15} />} />
        <StatCard label="Decision latency" value={m.latency_ms.decision_total ? `${m.latency_ms.decision_total.toFixed(0)} ms` : '—'}
                  hint={m.latency_ms.ml ? `ML ${m.latency_ms.ml.toFixed(0)} ms · rest ${(m.latency_ms.decision_total - m.latency_ms.ml).toFixed(0)} ms` : 'Measured per action'}
                  icon={<Timer size={15} />} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Agent activity over time" subtitle="Actions per minute by outcome" className="lg:col-span-2">
          {m.activity.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-600">No activity yet. Run a simulation.</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={m.activity}>
                <defs>
                  <linearGradient id="gT" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#0284c7" stopOpacity={0.5} /><stop offset="100%" stopColor="#0284c7" stopOpacity={0} /></linearGradient>
                  <linearGradient id="gS" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#dc2626" stopOpacity={0.5} /><stop offset="100%" stopColor="#dc2626" stopOpacity={0} /></linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(15,23,42,0.08)" vertical={false} />
                <XAxis dataKey="bucket" stroke="#64748b" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={tip} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Area type="monotone" dataKey="total" name="All actions" stroke="#0284c7" fill="url(#gT)" strokeWidth={2} />
                <Area type="monotone" dataKey="suspicious" name="High/Critical" stroke="#dc2626" fill="url(#gS)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Enforcement decisions" subtitle="What the policy engine did">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={m.decisions} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid stroke="rgba(15,23,42,0.08)" horizontal={false} />
              <XAxis type="number" stroke="#64748b" fontSize={11} allowDecimals={false} tickLine={false} />
              <YAxis type="category" dataKey="decision" stroke="#64748b" fontSize={10} tickLine={false} axisLine={false} width={100}
                     tickFormatter={(v: string) => v.replace('REQUIRE_', 'REQ. ')} />
              <Tooltip contentStyle={tip} cursor={{ fill: 'rgba(15,23,42,0.04)' }} />
              <Bar dataKey="count" name="Actions" radius={[0, 4, 4, 0]}>
                {m.decisions.map((d) => <Cell key={d.decision} fill={DECISION_FILL[d.decision]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Behaviour drift by session" subtitle="Peak drift vs each agent's alert threshold" className="lg:col-span-2">
          {driftRows.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-600">Drift is recorded when a session finishes.</p>
          ) : (
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={driftRows}>
                <CartesianGrid stroke="rgba(15,23,42,0.08)" vertical={false} />
                <XAxis dataKey="i" stroke="#64748b" fontSize={11} tickLine={false} label={{ value: 'session', position: 'insideBottom', offset: -2, fill: '#475569', fontSize: 10 }} />
                <YAxis stroke="#64748b" fontSize={11} domain={[0, 100]} tickLine={false} axisLine={false} unit="%" />
                <Tooltip contentStyle={tip} formatter={(v: number) => `${v}%`} labelFormatter={(l, p) => `Session ${l} · ${p?.[0]?.payload?.agent ?? ''}`} />
                <ReferenceLine y={driftRows[0].threshold} stroke="#ca8a04" strokeDasharray="4 3" label={{ value: 'alert', fill: '#ca8a04', fontSize: 10, position: 'right' }} />
                <Line type="monotone" dataKey="peak" name="Peak drift" stroke="#ea580c" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Normal vs suspicious" subtitle="By assessed risk">
          <ResponsiveContainer width="100%" height={210}>
            <PieChart>
              <Pie data={m.normal_vs_suspicious} dataKey="value" nameKey="name" innerRadius={50} outerRadius={78} paddingAngle={3} stroke="none">
                <Cell fill="#16a34a" /><Cell fill="#dc2626" />
              </Pie>
              <Tooltip contentStyle={tip} /><Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Risk distribution" subtitle="Actions by risk level">
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={m.risk_distribution}>
              <CartesianGrid stroke="rgba(15,23,42,0.08)" vertical={false} />
              <XAxis dataKey="level" stroke="#64748b" fontSize={11} tickLine={false} />
              <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tip} cursor={{ fill: 'rgba(15,23,42,0.04)' }} />
              <Bar dataKey="count" name="Actions" radius={[4, 4, 0, 0]}>
                {m.risk_distribution.map((d) => <Cell key={d.level} fill={RISK_COLOR[d.level as RiskLevel]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Incidents by severity">
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={m.incidents_by_severity}>
              <CartesianGrid stroke="rgba(15,23,42,0.08)" vertical={false} />
              <XAxis dataKey="severity" stroke="#64748b" fontSize={11} tickLine={false} />
              <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tip} cursor={{ fill: 'rgba(15,23,42,0.04)' }} />
              <Bar dataKey="count" name="Incidents" radius={[4, 4, 0, 0]}>
                {m.incidents_by_severity.map((d) => <Cell key={d.severity} fill={RISK_COLOR[d.severity as RiskLevel] ?? '#64748b'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Simulated environment" subtitle="Sandbox only" icon={<Database size={14} className="text-slate-500" />}>
          <ul className="space-y-1">
            {env.map(([name, state]) => {
              const bad = state !== 'HEALTHY' && state !== 'FAILED_OVER'
              return (
                <li key={name} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate font-mono text-[11px] text-slate-400">{name}</span>
                  <span className={`chip shrink-0 ${bad ? 'bg-crit/12 text-crit ring-1 ring-inset ring-crit/30' : state === 'FAILED_OVER' ? 'bg-warn/12 text-warn ring-1 ring-inset ring-warn/25' : 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25'}`}>{state}</span>
                </li>
              )
            })}
          </ul>
        </Card>
      </div>
    </div>
  )
}
