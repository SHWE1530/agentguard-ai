import { Loader2, RotateCcw, ShieldCheck, Siren } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Card, EmptyState, ErrorState, Loading, RISK_COLOR, fmtDateTime,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type { Incident, RiskLevel } from '../types'

const STATUS_CLASS: Record<string, string> = {
  OPEN: 'bg-crit/12 text-crit ring-crit/30',
  RECOVERING: 'bg-warn/12 text-warn ring-warn/30',
  RECOVERED: 'bg-safe/12 text-safe ring-safe/30',
  RESOLVED: 'bg-safe/12 text-safe ring-safe/30',
  RECOVERY_FAILED: 'bg-crit/12 text-crit ring-crit/30',
}

export default function Incidents() {
  const { data, error, loading, reload } = useApi(() => api.incidents(), [])
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [filter, setFilter] = useState<string>('ALL')

  useEventListener(['incident', 'recovery'], () => reload())

  const recover = async (id: string) => {
    setBusy(id)
    setMsg(null)
    try {
      const res = await api.recover(id)
      setMsg(
        res.verified
          ? `${res.reference}: state restored and verified healthy.`
          : `${res.reference}: recovery ran but verification FAILED — ${res.verification.summary}`,
      )
      reload()
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : 'Recovery could not be started.')
    } finally {
      setBusy(null)
    }
  }

  if (loading && !data) return <Loading label="Loading incidents…" />
  if (error) return <ErrorState message={error} onRetry={reload} />

  const incidents = (data ?? []).filter(
    (i) => filter === 'ALL' || (filter === 'ACTIVE' ? i.status === 'OPEN' : i.severity === filter),
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">Incident Center</h1>
          <p className="mt-1 text-sm text-slate-500">
            Every HIGH or CRITICAL intervention becomes an incident with a full evidence trail.
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {['ALL', 'ACTIVE', 'CRITICAL', 'HIGH'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                filter === f
                  ? 'bg-beam/12 text-beam ring-1 ring-inset ring-beam/25'
                  : 'text-slate-500 hover:bg-white/[0.04]'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {msg && (
        <p className="rounded-lg border border-white/10 bg-ink-850 px-3 py-2 text-sm text-slate-300">
          {msg}
        </p>
      )}

      {incidents.length === 0 ? (
        <Card>
          <EmptyState
            title="No incidents match this filter"
            hint="Run the Critical Misbehaviour scenario in the Simulation Lab to generate one."
            icon={<ShieldCheck size={28} />}
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {incidents.map((i: Incident) => {
            const color = RISK_COLOR[i.severity as RiskLevel] ?? '#64748b'
            const done = i.status === 'RESOLVED' || i.status === 'RECOVERED'
            return (
              <article
                key={i.id}
                className="card card-pad flex flex-col gap-3"
                style={{ borderTop: `2px solid ${color}` }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-mono text-xs text-slate-500">{i.reference}</p>
                    <h3 className="mt-0.5 text-sm font-semibold leading-snug text-slate-100">
                      {i.title}
                    </h3>
                  </div>
                  <span
                    className="chip shrink-0 ring-1 ring-inset"
                    style={{ color, backgroundColor: `${color}18`, borderColor: `${color}40` }}
                  >
                    <Siren size={11} /> {i.severity}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span
                    className={`chip ring-1 ring-inset ${
                      STATUS_CLASS[i.status] ?? 'bg-white/5 text-slate-400 ring-white/10'
                    }`}
                  >
                    {i.status.replace(/_/g, ' ')}
                  </span>
                  <span className="font-mono text-slate-500">
                    risk {Math.round(i.risk_score)}/100
                  </span>
                  <span className="text-slate-600">{i.agent_name ?? 'agent'}</span>
                </div>

                <p className="line-clamp-4 text-xs leading-relaxed text-slate-400">{i.reason}</p>

                <p className="text-[11px] text-slate-600">{fmtDateTime(i.created_at)}</p>

                <div className="mt-auto flex gap-2 pt-1">
                  <Link to={`/app/incidents/${i.id}`} className="btn-ghost flex-1 !py-1.5 text-xs">
                    View details
                  </Link>
                  <button
                    className="btn-safe flex-1 !py-1.5 text-xs"
                    disabled={done || busy === i.id}
                    onClick={() => recover(i.id)}
                    title={done ? 'This incident has already been recovered' : 'Roll back the simulated state'}
                  >
                    {busy === i.id ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <RotateCcw size={13} />
                    )}
                    {done ? 'Recovered' : 'Start recovery'}
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
