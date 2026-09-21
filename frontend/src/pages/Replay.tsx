import { PlayCircle } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ReplayPlayer } from '../components/ReplayPlayer'
import { Card, EmptyState, ErrorState, Loading, RISK_COLOR, fmtDateTime } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { RiskLevel } from '../types'

/** Pick any incident and replay it like a recording. */
export default function ReplayPage() {
  const incidents = useApi(() => api.incidents(), [])
  const [sel, setSel] = useState<string | null>(null)
  const id = sel ?? incidents.data?.[0]?.id ?? null
  const replay = useApi(() => (id ? api.replay(id) : Promise.resolve(null)), [id])

  if (incidents.loading && !incidents.data) return <Loading label="Loading incidents…" />
  if (incidents.error) return <ErrorState message={incidents.error} onRetry={incidents.reload} />
  const list = incidents.data ?? []

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Incident Replay</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Select an incident and replay its timeline: agent status, risk and the simulated environment are reconstructed from the audit trail.
        </p>
      </div>
      {list.length === 0 ? (
        <Card><EmptyState title="No incidents to replay yet" hint="Run the Critical or Privilege escalation scenario." icon={<PlayCircle size={28} />} /></Card>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {list.map((i) => {
              const c = RISK_COLOR[i.severity as RiskLevel] ?? '#64748b'
              return (
                <button key={i.id} onClick={() => setSel(i.id)}
                        className={`rounded-xl border px-3 py-2 text-left ${i.id === id ? 'border-beam/40 bg-beam/[0.06]' : 'border-white/[0.07] bg-ink-850/50 hover:bg-white/[0.03]'}`}>
                  <span className="flex items-center gap-2 text-xs font-semibold text-slate-100"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: c }} />{i.reference}
                    <span className="font-normal text-slate-500">{i.severity}</span></span>
                  <span className="mt-0.5 block max-w-[260px] truncate text-[11px] text-slate-500">{i.title}</span>
                  <span className="block font-mono text-[10px] text-slate-600">{fmtDateTime(i.created_at)}</span>
                </button>
              )
            })}
          </div>
          <Card title={list.find((i) => i.id === id)?.reference ?? 'Replay'} subtitle="Interactive: play, pause, step and scrub"
                action={id && <Link to={`/app/incidents/${id}`} className="btn-ghost !px-3 !py-1.5 text-xs">Open incident</Link>}>
            {replay.loading && !replay.data ? <Loading label="Building replay…" /> : replay.error ? <ErrorState message={replay.error} onRetry={replay.reload} /> : replay.data ? <ReplayPlayer key={replay.data.incident_id} replay={replay.data} /> : null}
          </Card>
        </>
      )}
    </div>
  )
}
