import { AlertTriangle, Check, Loader2, ShieldCheck, UserCheck, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ActionRow } from '../components/ActionStream'
import {
  Card, EmptyState, ErrorState, Loading, RiskMeter, fmtDateTime,
} from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type { Approval, RiskLevel } from '../types'

function levelFor(score: number): RiskLevel {
  if (score >= 85) return 'CRITICAL'
  if (score >= 60) return 'HIGH'
  if (score >= 30) return 'MEDIUM'
  return 'LOW'
}

export default function Approvals() {
  const pending = useApi(() => api.pendingApprovals(), [])
  const history = useApi(() => api.allApprovals(), [])
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [operator, setOperator] = useState('operator')
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null)

  useEventListener(['approval_requested', 'approval_decided'], () => {
    pending.reload()
    history.reload()
  })

  const decide = async (id: string, approve: boolean) => {
    setBusy(id)
    setResult(null)
    try {
      const res = approve
        ? await api.approve(id, operator || 'operator', note || undefined)
        : await api.reject(id, operator || 'operator', note || undefined)
      setResult({
        ok: true,
        text: approve
          ? `${res.action_type} approved by ${res.decided_by}. The action was executed against the simulated environment and recorded in the audit trail.`
          : `${res.action_type} rejected by ${res.decided_by}. The action was blocked and the decision recorded in the audit trail.`,
      })
      setNote('')
      pending.reload()
      history.reload()
    } catch (e) {
      setResult({
        ok: false,
        text: e instanceof ApiError ? e.message : 'The decision could not be recorded.',
      })
    } finally {
      setBusy(null)
    }
  }

  if (pending.loading && !pending.data) return <Loading label="Loading approval queue…" />
  if (pending.error) return <ErrorState message={pending.error} onRetry={pending.reload} />

  const rows = pending.data ?? []
  const decided = (history.data ?? []).filter((a) => a.status !== 'PENDING')

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Human Approval</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Some actions are legitimate but too consequential to automate. Policy holds them here
          until a person decides. Nothing executes while a request is pending.
        </p>
      </div>

      {result && (
        <p
          className={`rounded-lg border px-3 py-2.5 text-sm ${
            result.ok
              ? 'border-safe/25 bg-safe/[0.07] text-slate-200'
              : 'border-crit/25 bg-crit/[0.07] text-crit'
          }`}
        >
          {result.text}
        </p>
      )}

      {rows.length === 0 ? (
        <Card>
          <EmptyState
            title="No actions are waiting for a decision"
            hint="Run the Human Approval scenario in the Simulation Lab to see this flow."
            icon={<ShieldCheck size={28} />}
          />
          <div className="mt-2 text-center">
            <Link to="/app/lab" className="text-sm text-beam hover:underline">
              Open the Simulation Lab →
            </Link>
          </div>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="label">Deciding as</span>
              <input
                className="input mt-1"
                value={operator}
                onChange={(e) => setOperator(e.target.value)}
                placeholder="Your name"
                maxLength={64}
              />
            </label>
            <label className="block">
              <span className="label">Note (recorded in the audit trail)</span>
              <input
                className="input mt-1"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Optional justification"
                maxLength={500}
              />
            </label>
          </div>

          {rows.map((a: Approval) => (
            <div key={a.id} className="card card-pad border-ai/25">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <span className="chip bg-ai/12 text-ai ring-1 ring-inset ring-ai/25">
                    <AlertTriangle size={11} /> High-risk action · human decision required
                  </span>
                  <h2 className="mt-2.5 font-mono text-lg font-bold text-slate-100">
                    {a.action_type}
                  </h2>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                    <span>Agent: {a.agent_name ?? a.agent_id}</span>
                    <span className="font-mono">Requested {fmtDateTime(a.created_at)}</span>
                  </div>
                  <p className="mt-3 text-sm leading-relaxed text-slate-400">{a.reason}</p>
                </div>
                <div className="flex flex-col items-center gap-3">
                  <RiskMeter score={a.risk_score} level={levelFor(a.risk_score)} size={104} />
                  <div className="flex gap-2">
                    <button
                      className="btn-safe"
                      disabled={busy === a.id}
                      onClick={() => decide(a.id, true)}
                    >
                      {busy === a.id ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                      Approve
                    </button>
                    <button
                      className="btn-danger"
                      disabled={busy === a.id}
                      onClick={() => decide(a.id, false)}
                    >
                      <X size={14} /> Reject
                    </button>
                  </div>
                </div>
              </div>

              {a.action && (
                <div className="mt-4 border-t border-white/[0.06] pt-4">
                  <p className="label mb-2">The held action, as the pipeline assessed it</p>
                  <ul>
                    <ActionRow action={a.action} defaultOpen />
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {decided.length > 0 && (
        <Card
          title="Decision history"
          subtitle="Every human decision is part of the audit trail"
          icon={<UserCheck size={14} className="text-slate-500" />}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px]">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  <th className="th">Action</th>
                  <th className="th">Risk</th>
                  <th className="th">Decision</th>
                  <th className="th">By</th>
                  <th className="th">When</th>
                </tr>
              </thead>
              <tbody>
                {decided.map((a) => (
                  <tr key={a.id} className="border-b border-white/[0.04]">
                    <td className="td font-mono text-xs">{a.action_type}</td>
                    <td className="td font-mono text-xs">{Math.round(a.risk_score)}</td>
                    <td className="td">
                      <span
                        className={`chip ${
                          a.status === 'APPROVED'
                            ? 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25'
                            : 'bg-crit/12 text-crit ring-1 ring-inset ring-crit/25'
                        }`}
                      >
                        {a.status}
                      </span>
                    </td>
                    <td className="td text-xs">{a.decided_by ?? '—'}</td>
                    <td className="td font-mono text-xs text-slate-500">
                      {a.decided_at ? fmtDateTime(a.decided_at) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
