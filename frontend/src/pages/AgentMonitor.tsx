import { Activity, Ban, CheckCircle2, Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ActionStream } from '../components/ActionStream'
import {
  AgentStatusPill, AnomalyPill, Card, ErrorState, Loading, RiskMeter,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { api } from '../services/api'
import type { AgentAction, RiskLevel } from '../types'

export default function AgentMonitor() {
  const { data: agents, error, loading, reload } = useApi(() => api.agents(), [])
  const [actions, setActions] = useState<AgentAction[]>([])

  const load = () => api.actions({ limit: 60 }).then(setActions).catch(() => {})
  useEffect(() => {
    load()
  }, [])

  useEventListener(['action'], (e) => {
    const a = e.data as AgentAction
    setActions((prev) => [a, ...prev.filter((x) => x.id !== a.id)].slice(0, 60))
    reload()
  })
  useEventListener(['agent_status', 'simulation_finished', 'approval_decided'], () => reload())

  if (loading && !agents) return <Loading label="Loading agents…" />
  if (error) return <ErrorState message={error} onRetry={reload} />

  const agent = agents?.[0]
  const latest = actions[0]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">Agent Monitor</h1>
          <p className="mt-1 text-sm text-slate-500">
            Real-time view of the monitored agent and every action it attempts.
          </p>
        </div>
        <Link to="/app/lab" className="btn-ghost">
          <Play size={14} /> Run a simulation
        </Link>
      </div>

      {!agent ? (
        <Card>
          <p className="py-8 text-center text-sm text-slate-500">
            No agent registered yet. Start a simulation to create one.
          </p>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card
            title={agent.name}
            subtitle={agent.purpose}
            icon={<Activity size={14} className="text-beam" />}
          >
            <div className="flex items-center gap-5">
              <RiskMeter
                score={latest?.risk_score ?? 0}
                level={(latest?.risk_level ?? 'LOW') as RiskLevel}
              />
              <div className="min-w-0 space-y-2.5">
                <AgentStatusPill status={agent.status} />
                <div>
                  <p className="label">Current task</p>
                  <p className="mt-0.5 text-xs text-slate-300">{agent.current_task ?? '—'}</p>
                </div>
                <div>
                  <p className="label">Current action</p>
                  <p className="mt-0.5 truncate font-mono text-xs text-slate-300">
                    {agent.current_action?.action_type ?? '—'}
                  </p>
                </div>
                <div>
                  <p className="label">Anomaly score</p>
                  <div className="mt-0.5">
                    {agent.current_action ? (
                      <AnomalyPill score={agent.current_action.anomaly_score} />
                    ) : (
                      <span className="text-xs text-slate-500">—</span>
                    )}
                  </div>
                </div>
                <div>
                  <p className="label">Session</p>
                  <p className="mt-0.5 font-mono text-[11px] text-slate-500">
                    {agent.current_session ?? '—'}{' '}
                    {agent.session_status && (
                      <span className="text-slate-600">({agent.session_status})</span>
                    )}
                  </p>
                </div>
              </div>
            </div>
          </Card>

          <Card title="Capability set" subtitle="What policy sanctions for this agent">
            <p className="label">Allowed</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {agent.allowed_actions.map((a) => (
                <span
                  key={a}
                  className="rounded bg-safe/10 px-1.5 py-0.5 font-mono text-[10px] text-safe ring-1 ring-inset ring-safe/20"
                >
                  <CheckCircle2 size={9} className="mr-1 inline" />
                  {a}
                </span>
              ))}
            </div>
            <p className="label mt-4">Restricted</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {agent.restricted_actions.map((a) => (
                <span
                  key={a}
                  className="rounded bg-crit/10 px-1.5 py-0.5 font-mono text-[10px] text-crit ring-1 ring-inset ring-crit/20"
                >
                  <Ban size={9} className="mr-1 inline" />
                  {a}
                </span>
              ))}
            </div>
          </Card>

          <Card title="Session summary" subtitle="Outcomes for the actions on screen">
            <ul className="space-y-2 text-sm">
              {[
                ['Actions observed', actions.length, 'text-slate-200'],
                ['Allowed', actions.filter((a) => a.action_status === 'ALLOWED').length, 'text-safe'],
                ['Monitored', actions.filter((a) => a.action_status === 'MONITORED').length, 'text-warn'],
                ['Blocked', actions.filter((a) => a.action_status === 'BLOCKED').length, 'text-crit'],
                ['Held for approval', actions.filter((a) => a.action_status === 'PENDING_APPROVAL').length, 'text-ai'],
              ].map(([label, value, cls]) => (
                <li key={String(label)} className="flex items-center justify-between">
                  <span className="text-slate-500">{label as string}</span>
                  <span className={`font-mono font-semibold tabular-nums ${cls as string}`}>
                    {value as number}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}

      <Card
        title="Live action stream"
        subtitle="Every attempted action with its ML score, risk and decision"
      >
        <ActionStream
          actions={actions}
          emptyHint="No actions recorded yet. Start a simulation from the Simulation Lab."
        />
      </Card>
    </div>
  )
}
