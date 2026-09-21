import { ArrowDown, CheckCircle2, Clock, ShieldQuestion } from 'lucide-react'
import { useState } from 'react'
import { Card, ErrorState, Loading } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'

/** The architecture, with LIVE numbers read from the running system for each stage. */
export default function ArchitecturePage() {
  const { data, error, loading, reload } = useApi(() => api.architecture(), [])
  const [open, setOpen] = useState<string>('ml')

  if (loading && !data) return <Loading label="Loading architecture…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null
  const sel = data.stages.find((s) => s.id === open) ?? data.stages[0]

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">System Architecture</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          A layered safety envelope: no single mechanism decides whether an agent is safe. Click a stage. The figures come from the
          running system (counts and measured latency), and each stage names the module that implements it.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <ol className="space-y-1.5">
            {data.stages.map((s, i) => (
              <li key={s.id}>
                <button onClick={() => setOpen(s.id)}
                        className={`w-full rounded-xl border px-3 py-2.5 text-left transition-colors ${s.id === open ? 'border-beam/40 bg-beam/[0.07]' : 'border-white/[0.07] bg-ink-850/50 hover:bg-white/[0.03]'}`}>
                  <span className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                    <span className="grid h-5 w-5 place-items-center rounded bg-white/[0.06] font-mono text-[10px] text-slate-400">{i + 1}</span>
                    {s.name}
                    {s.implemented && <CheckCircle2 size={13} className="ml-auto text-safe" />}
                  </span>
                  <span className="mt-1 block truncate font-mono text-[10px] text-slate-500">{s.stat}</span>
                </button>
                {i < data.stages.length - 1 && <ArrowDown size={13} className="mx-auto my-0.5 text-slate-700" />}
              </li>
            ))}
          </ol>
        </div>

        <div className="space-y-4 lg:col-span-3">
          <Card title={sel.name} subtitle={sel.module}>
            <p className="text-sm leading-relaxed text-slate-300">{sel.does}</p>
            <dl className="mt-4 grid gap-3 sm:grid-cols-3">
              <div><dt className="label">Inputs</dt><dd className="mt-1 text-xs text-slate-400">{sel.inputs}</dd></div>
              <div><dt className="label">Outputs</dt><dd className="mt-1 text-xs text-slate-400">{sel.outputs}</dd></div>
              <div><dt className="label">Live</dt><dd className="mt-1 font-mono text-xs text-beam">{sel.stat}</dd></div>
            </dl>
            {sel.note && <p className="mt-3 rounded-lg border border-warn/25 bg-warn/[0.06] px-3 py-2 text-xs text-warn">Limitation: {sel.note}</p>}
          </Card>

          <Card title="Measured decision latency per stage" subtitle={`Mean over the last ${data.n_actions_measured} recorded actions`} icon={<Clock size={14} className="text-slate-500" />}>
            {Object.keys(data.decision_latency_ms).length === 0 ? <p className="text-xs text-slate-600">No actions recorded yet.</p> : (
              <div className="space-y-1.5">
                {Object.entries(data.decision_latency_ms).filter(([k]) => k !== 'total').sort((a, b) => b[1] - a[1]).map(([k, v]) => {
                  const max = Math.max(...Object.entries(data.decision_latency_ms).filter(([kk]) => !['total', 'decision_total'].includes(kk)).map(([, x]) => x), 0.001)
                  const isTotal = k === 'decision_total'
                  return (
                    <div key={k} className="flex items-center gap-3 text-xs">
                      <span className="w-32 shrink-0 font-mono text-slate-400">{k.replace('_', ' ')}</span>
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700"><span className="block h-full rounded-full" style={{ width: `${Math.min(100, (v / (isTotal ? v : max)) * 100)}%`, backgroundColor: isTotal ? '#16a34a' : '#0284c7' }} /></span>
                      <span className="w-16 shrink-0 text-right font-mono text-slate-300">{v.toFixed(2)} ms</span>
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Zero-trust principle" icon={<ShieldQuestion size={14} className="text-ai" />}>
          <p className="text-sm font-semibold text-slate-200">{data.zero_trust.principle}</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-slate-400">
            {data.zero_trust.per_action_questions.map((q) => <li key={q}>{q}</li>)}
          </ol>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">{data.zero_trust.claim}</p>
        </Card>
        <Card title="Not implemented (future work)" subtitle="Listed so nothing here is mistaken for a claim">
          <ul className="space-y-2">
            {data.future_work.map((f) => (
              <li key={f.name} className="text-xs"><span className="font-semibold text-slate-300">{f.name}</span><span className="text-slate-500"> — {f.why}</span></li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
