import {
  AlertTriangle, Check, FileSearch, Lightbulb, Loader2, ShieldCheck, ThumbsDown, ThumbsUp, UserCheck, X,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ActionDetail } from '../components/ActionStream'
import { CounterfactualPanel, FACTOR_LABEL } from '../components/analysis'
import { Bar, Card, EmptyState, ErrorState, Loading, RiskMeter, Section, fmtDateTime } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useAuth } from '../hooks/useAuth'
import { useEventListener } from '../hooks/useEvents'
import { ApiError, api } from '../services/api'
import type { Approval, RiskLevel } from '../types'

const levelFor = (s: number): RiskLevel => (s >= 85 ? 'CRITICAL' : s >= 60 ? 'HIGH' : s >= 30 ? 'MEDIUM' : 'LOW')
const SIGNAL = {
  supports_approval: ['text-safe', 'supports approving', <ThumbsUp key="a" size={11} />],
  supports_rejection: ['text-crit', 'supports rejecting', <ThumbsDown key="r" size={11} />],
  neutral: ['text-slate-500', 'context', null],
} as const

function EvidenceRounds({ a }: { a: Approval }) {
  const rounds = a.evidence.rounds ?? []
  if (!rounds.length) return null
  return (
    <div className="space-y-2">
      {rounds.map((r) => (
        <div key={r.round} className="rounded-lg border border-beam/20 bg-beam/[0.04] p-3">
          <p className="text-xs font-semibold text-beam">Additional evidence · round {r.round}</p>
          <ul className="mt-2 space-y-1.5">
            {r.findings.map((f) => {
              const [cls, label, icon] = SIGNAL[f.signal]
              return (
                <li key={f.source} className="text-xs">
                  <span className="font-semibold text-slate-300">{f.source}: </span>
                  <span className="text-slate-400">{f.finding}</span>{' '}
                  <span className={`inline-flex items-center gap-1 text-[10px] font-semibold ${cls}`}>{icon}{label}</span>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </div>
  )
}

export default function Approvals() {
  const pending = useApi(() => api.pendingApprovals(), [])
  const history = useApi(() => api.allApprovals(), [])
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const auth = useAuth()
  const [operator, setOperator] = useState('operator')
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  useEventListener(['approval_requested', 'approval_decided', 'approval_updated'], () => { pending.reload(); history.reload() })

  const act = async (id: string, kind: 'approve' | 'reject' | 'evidence') => {
    setBusy(`${id}:${kind}`); setResult(null)
    const who = auth.config?.enabled && auth.user ? auth.user : operator.trim() || 'operator'
    try {
      if (kind === 'evidence') {
        const r = await api.requestEvidence(id, who)
        setResult({ ok: true, text: `Evidence round ${r.evidence_rounds} gathered for ${r.action_type}. The request is still pending your decision.` })
      } else {
        const r = kind === 'approve' ? await api.approve(id, who, note || undefined) : await api.reject(id, who, note || undefined)
        setResult({
          ok: true,
          text: kind === 'approve'
            ? `${r.action_type} approved by ${r.decided_by}. It was executed against the simulated environment, the agent resumed, and the decision is in the audit trail.`
            : `${r.action_type} rejected by ${r.decided_by}. It was not executed, the agent resumed, and the decision is in the audit trail.`,
        })
        setNote('')
      }
      pending.reload(); history.reload()
    } catch (e) {
      setResult({ ok: false, text: e instanceof ApiError ? e.message : 'The request could not be completed.' })
    } finally { setBusy(null) }
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
          Some actions are legitimate but too consequential to automate. Policy holds them here with the evidence, the modelled
          impact and a safer alternative. Nothing executes while a request is pending.
        </p>
      </div>

      {result && (
        <p className={`rounded-lg border px-3 py-2.5 text-sm ${result.ok ? 'border-safe/25 bg-safe/[0.07] text-slate-200' : 'border-crit/25 bg-crit/[0.07] text-crit'}`}>{result.text}</p>
      )}

      {rows.length === 0 ? (
        <Card>
          <EmptyState title="No actions are waiting for a decision" hint="Run the Human Approval, Repeated failures or Drift scenario in the Simulation Lab." icon={<ShieldCheck size={28} />} />
          <div className="mt-2 text-center"><Link to="/app/lab" className="text-sm text-beam hover:underline">Open the Simulation Lab →</Link></div>
        </Card>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block"><span className="label">Deciding as</span>
              <input className="input mt-1" value={auth.config?.enabled && auth.user ? auth.user : operator} disabled={Boolean(auth.config?.enabled)} onChange={(e) => setOperator(e.target.value)} maxLength={64} /></label>
            <label className="block"><span className="label">Note (recorded in the audit trail)</span>
              <input className="input mt-1" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Optional justification" maxLength={500} /></label>
          </div>

          {rows.map((a) => {
            const cf = a.impact
            return (
              <div key={a.id} className="card card-pad border-ai/25">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <span className="chip bg-ai/12 text-ai ring-1 ring-inset ring-ai/25"><AlertTriangle size={11} /> Human decision required</span>
                    <h2 className="mt-2.5 font-mono text-lg font-bold text-slate-100">{a.action_type}</h2>
                    <p className="mt-1 text-xs text-slate-500">{a.agent_name ?? a.agent_id} · requested {fmtDateTime(a.created_at)} · task “{a.evidence.intent.task_type.replace(/_/g, ' ')}”</p>
                    {a.evidence.matched_rules[0] && (
                      <p className="mt-2 text-xs text-slate-400"><span className="font-semibold text-slate-300">Why it was held: </span>{a.evidence.matched_rules[0].reason} <span className="font-mono text-[10px] text-slate-600">({a.evidence.matched_rules[0].id})</span></p>
                    )}
                  </div>
                  <RiskMeter score={a.risk_score} level={levelFor(a.risk_score)} size={100} />
                </div>

                <div className="mt-4 grid gap-4 lg:grid-cols-3">
                  <Section label="Evidence">
                    <div className="space-y-1.5 text-xs">
                      {a.evidence.top_risk_factors.map((f) => (
                        <div key={f.factor} className="flex items-center gap-2">
                          <span className="w-36 shrink-0 text-slate-400">{FACTOR_LABEL[f.factor] ?? f.factor}</span>
                          <span className="flex-1"><Bar value={f.value} color={f.value >= 80 ? '#dc2626' : f.value >= 50 ? '#ea580c' : '#0284c7'} /></span>
                          <span className="w-7 text-right font-mono text-slate-300">{Math.round(f.value)}</span>
                        </div>
                      ))}
                      <p className="pt-1 text-[11px] text-slate-500">
                        Anomaly {a.evidence.anomaly.toFixed(2)} · intent alignment {a.evidence.intent.alignment.toFixed(2)} · agent trust {Math.round(a.evidence.trust)} · drift {Math.round(a.evidence.drift * 100)}%
                      </p>
                      <p className="font-mono text-[10px] leading-relaxed text-slate-600">
                        recent: {a.evidence.recent_actions.map((r) => r.action).join(' → ')}
                      </p>
                    </div>
                  </Section>
                  <Section label="Potential impact if approved">
                    <CounterfactualPanel cf={cf} compact />
                  </Section>
                  <Section label="Alternative safe action">
                    {a.alternative ? (
                      <div className="flex gap-2 rounded-lg border border-beam/25 bg-beam/[0.05] p-3 text-xs">
                        <Lightbulb size={14} className="mt-0.5 shrink-0 text-beam" />
                        <span className="text-slate-400"><span className="font-mono font-semibold text-beam">{a.alternative.action}</span><br />{a.alternative.note}</span>
                      </div>
                    ) : <p className="text-xs text-slate-600">No catalogued alternative for this action.</p>}
                  </Section>
                </div>

                <div className="mt-4"><EvidenceRounds a={a} /></div>

                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-4">
                  <button className="btn-safe" disabled={!!busy} onClick={() => act(a.id, 'approve')}>
                    {busy === `${a.id}:approve` ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Approve
                  </button>
                  <button className="btn-danger" disabled={!!busy} onClick={() => act(a.id, 'reject')}>
                    {busy === `${a.id}:reject` ? <Loader2 size={14} className="animate-spin" /> : <X size={14} />} Reject
                  </button>
                  <button className="btn-ghost" disabled={!!busy || a.evidence_rounds >= 3} onClick={() => act(a.id, 'evidence')}>
                    {busy === `${a.id}:evidence` ? <Loader2 size={14} className="animate-spin" /> : <FileSearch size={14} />} Request more evidence
                    <span className="font-mono text-[10px] text-slate-500">{a.evidence_rounds}/3</span>
                  </button>
                  <button className="ml-auto text-xs text-slate-500 hover:text-slate-300" onClick={() => setOpen(open === a.id ? null : a.id)}>
                    {open === a.id ? 'Hide' : 'Show'} full analysis
                  </button>
                </div>
                {open === a.id && a.action && <div className="mt-4 border-t border-white/[0.06] pt-4"><ActionDetail action={a.action} /></div>}
              </div>
            )
          })}
        </div>
      )}

      {decided.length > 0 && (
        <Card title="Decision history" subtitle="Every human decision is part of the audit trail" icon={<UserCheck size={14} className="text-slate-500" />}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px]">
              <thead><tr className="border-b border-white/[0.06]"><th className="th">Action</th><th className="th">Risk</th><th className="th">Decision</th><th className="th">By</th><th className="th">Evidence rounds</th><th className="th">Note</th><th className="th">When</th></tr></thead>
              <tbody>
                {decided.map((a) => (
                  <tr key={a.id} className="border-b border-white/[0.04]">
                    <td className="td font-mono text-xs">{a.action_type}</td>
                    <td className="td font-mono text-xs">{Math.round(a.risk_score)}</td>
                    <td className="td"><span className={`chip ${a.status === 'APPROVED' ? 'bg-safe/12 text-safe ring-1 ring-inset ring-safe/25' : 'bg-crit/12 text-crit ring-1 ring-inset ring-crit/25'}`}>{a.status}</span></td>
                    <td className="td text-xs">{a.decided_by ?? '—'}</td>
                    <td className="td font-mono text-xs">{a.evidence_rounds}</td>
                    <td className="td max-w-[240px] truncate text-xs text-slate-500">{a.decision_note ?? '—'}</td>
                    <td className="td font-mono text-xs text-slate-500">{a.decided_at ? fmtDateTime(a.decided_at) : '—'}</td>
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
