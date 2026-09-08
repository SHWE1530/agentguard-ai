import {
  Activity, BrainCircuit, CheckCircle2, Database, Gauge, ShieldX, Siren, UserCheck,
} from 'lucide-react'
import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import {
  Card, ErrorState, Loading, RISK_COLOR, StatCard,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { api } from '../services/api'
import type { RiskLevel } from '../types'

const tooltipStyle = {
  backgroundColor: '#0f1422',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 8,
  fontSize: 12,
  color: '#e2e8f0',
}

export default function Dashboard() {
  const { data: m, error, loading, reload } = useApi(() => api.metrics(), [])
  const { data: ml } = useApi(() => api.mlStatus(), [])

  // Any pipeline event invalidates the metrics, so refresh live.
  useEventListener(['action', 'incident', 'recovery', 'approval_decided'], () => reload())

  useEffect(() => {
    const t = setInterval(reload, 15000)
    return () => clearInterval(t)
  }, [reload])

  if (loading && !m) return <Loading label="Loading system metrics…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!m) return null

  const envEntries = Object.entries(m.environment)
  const compromised = envEntries.filter(([, s]) => s !== 'HEALTHY')

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">System Dashboard</h1>
          <p className="mt-1 text-sm text-slate-500">
            Every figure below is computed from recorded pipeline output — nothing is hard-coded.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`chip ring-1 ring-inset ${
              compromised.length
                ? 'bg-crit/10 text-crit ring-crit/25'
                : 'bg-safe/10 text-safe ring-safe/25'
            }`}
          >
            {compromised.length ? <ShieldX size={12} /> : <CheckCircle2 size={12} />}
            {compromised.length
              ? `${compromised.length} resource(s) compromised`
              : 'Sandbox healthy'}
          </span>
          <Link to="/app/lab" className="btn-primary">
            Run a simulation
          </Link>
        </div>
      </div>

      {/* Primary metrics */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total agent actions"
          value={m.total_actions}
          hint={`${m.total_sessions} session(s) recorded`}
          icon={<Activity size={15} />}
        />
        <StatCard
          label="Blocked actions"
          value={m.blocked_actions}
          tone={m.blocked_actions ? 'crit' : 'default'}
          hint={`${m.suspicious_actions} high/critical risk`}
          icon={<ShieldX size={15} />}
        />
        <StatCard
          label="Active incidents"
          value={m.active_incidents}
          tone={m.active_incidents ? 'high' : 'safe'}
          hint={`${m.total_incidents} total · ${m.critical_incidents} critical`}
          icon={<Siren size={15} />}
        />
        <StatCard
          label="Recovery success rate"
          value={m.recovery_success_rate === null ? '—' : `${m.recovery_success_rate}%`}
          tone={m.recovery_success_rate === 100 ? 'safe' : m.recovery_success_rate === null ? 'default' : 'warn'}
          hint={
            m.recovery_success_rate === null
              ? 'No recovery attempted yet'
              : `${m.recovered_incidents} recovered & verified`
          }
          icon={<CheckCircle2 size={15} />}
        />
      </div>

      {/* Secondary metrics */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Avg anomaly score"
          value={m.avg_anomaly_score.toFixed(3)}
          tone="ai"
          hint={ml?.loaded ? 'Isolation Forest output' : 'Model not loaded — heuristic fallback'}
          icon={<BrainCircuit size={15} />}
        />
        <StatCard
          label="Avg risk score"
          value={m.avg_risk_score.toFixed(1)}
          tone={m.avg_risk_score >= 60 ? 'high' : m.avg_risk_score >= 30 ? 'warn' : 'safe'}
          hint="Weighted across all recorded actions"
          icon={<Gauge size={15} />}
        />
        <StatCard
          label="Pending approvals"
          value={m.pending_approvals}
          tone={m.pending_approvals ? 'ai' : 'default'}
          hint={
            m.human_approval_rate === null
              ? 'No human decision made yet'
              : `${m.human_approval_rate}% of decisions approved`
          }
          icon={<UserCheck size={15} />}
        />
        <StatCard
          label="Agents"
          value={`${m.active_agents} active`}
          tone={m.paused_agents ? 'crit' : 'default'}
          hint={`${m.paused_agents} paused by the safety layer`}
          icon={<Activity size={15} />}
        />
      </div>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          title="Agent activity over time"
          subtitle="Actions per minute, split by intervention outcome"
          className="lg:col-span-2"
        >
          {m.activity.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-600">
              No activity recorded yet. Run a simulation to populate this chart.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={230}>
              <AreaChart data={m.activity}>
                <defs>
                  <linearGradient id="gTotal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#38bdf8" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gSus" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis dataKey="bucket" stroke="#64748b" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Area type="monotone" dataKey="total" name="All actions" stroke="#38bdf8" fill="url(#gTotal)" strokeWidth={2} />
                <Area type="monotone" dataKey="suspicious" name="High/Critical" stroke="#ef4444" fill="url(#gSus)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Normal vs suspicious" subtitle="Share of actions by risk classification">
          <ResponsiveContainer width="100%" height={230}>
            <PieChart>
              <Pie
                data={m.normal_vs_suspicious}
                dataKey="value"
                nameKey="name"
                innerRadius={54}
                outerRadius={82}
                paddingAngle={3}
                stroke="none"
              >
                <Cell fill="#22c55e" />
                <Cell fill="#ef4444" />
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Risk distribution" subtitle="Actions by assessed risk level">
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={m.risk_distribution}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="level" stroke="#64748b" fontSize={11} tickLine={false} />
              <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
              <Bar dataKey="count" name="Actions" radius={[4, 4, 0, 0]}>
                {m.risk_distribution.map((d) => (
                  <Cell key={d.level} fill={RISK_COLOR[d.level as RiskLevel]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Incidents by severity" subtitle="Raised by the intervention engine">
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={m.incidents_by_severity}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="severity" stroke="#64748b" fontSize={11} tickLine={false} />
              <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
              <Bar dataKey="count" name="Incidents" radius={[4, 4, 0, 0]}>
                {m.incidents_by_severity.map((d) => (
                  <Cell key={d.severity} fill={RISK_COLOR[d.severity as RiskLevel] ?? '#64748b'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Simulated environment"
          subtitle="The sandboxed world — no real systems"
          icon={<Database size={14} className="text-slate-500" />}
        >
          <ul className="space-y-1.5">
            {envEntries.map(([name, state]) => {
              const ok = state === 'HEALTHY'
              return (
                <li key={name} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate font-mono text-xs text-slate-400">{name}</span>
                  <span
                    className={`chip shrink-0 ${
                      ok
                        ? 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25'
                        : 'bg-crit/12 text-crit ring-1 ring-inset ring-crit/30'
                    }`}
                  >
                    {state}
                  </span>
                </li>
              )
            })}
          </ul>
        </Card>
      </div>
    </div>
  )
}
