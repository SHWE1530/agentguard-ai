import { AlertTriangle, FileWarning, Info, Timer } from 'lucide-react'
import { useState } from 'react'
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Card, Loading, StatCard } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { DetectorEval, Evaluation } from '../types'

const DETS = ['A_rules', 'B_ml', 'C_ml_policy', 'D_full'] as const
const SHORT: Record<string, string> = { A_rules: 'A · Rules only', B_ml: 'B · ML only', C_ml_policy: 'C · ML + policy', D_full: 'D · Full architecture' }
const COLOR: Record<string, string> = { A_rules: '#64748b', B_ml: '#7c3aed', C_ml_policy: '#0284c7', D_full: '#16a34a' }
const tip = { backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12, color: '#0f172a' }
const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(d)}%`)
const f3 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toFixed(3))

function Cell({ v, bad = false, good = false }: { v: string; bad?: boolean; good?: boolean }) {
  return <td className={`td font-mono text-xs tabular-nums ${bad ? 'text-crit' : good ? 'text-safe' : 'text-slate-300'}`}>{v}</td>
}

function Confusion({ d }: { d: DetectorEval }) {
  const a = d.action_level
  const cells = [
    ['True positives', a.tp, 'text-safe', 'malicious actions flagged'],
    ['False positives', a.fp, 'text-high', 'benign actions flagged'],
    ['False negatives', a.fn, 'text-crit', 'malicious actions missed'],
    ['True negatives', a.tn, 'text-slate-300', 'benign actions passed'],
  ] as const
  return (
    <div className="grid grid-cols-2 gap-2">
      {cells.map(([k, v, c, h]) => (
        <div key={k} className="rounded-lg border border-white/[0.06] bg-ink-850/60 p-3">
          <p className="label">{k}</p>
          <p className={`mt-1 font-mono text-xl font-bold tabular-nums ${c}`}>{v.toLocaleString()}</p>
          <p className="text-[10px] text-slate-600">{h}</p>
        </div>
      ))}
    </div>
  )
}

function Curves({ ev, kind }: { ev: Evaluation; kind: 'roc' | 'pr' }) {
  const series = (['B_ml', 'C_ml_policy', 'D_full'] as const).map((d) => ({
    d, pts: (kind === 'roc' ? ev.ablation[d].roc_curve : ev.ablation[d].pr_curve) ?? [],
  }))
  // merge on x for a single LineChart
  const xs = Array.from(new Set(series.flatMap((s) => s.pts.map((p) => p[0])))).sort((a, b) => a - b)
  const data = xs.map((x) => {
    const row: Record<string, number> = { x }
    series.forEach((s) => {
      const prev = [...s.pts].filter((p) => p[0] <= x).at(-1)
      if (prev) row[s.d] = prev[1]
    })
    return row
  })
  return (
    <ResponsiveContainer width="100%" height={230}>
      <LineChart data={data} margin={{ left: -10, right: 8 }}>
        <CartesianGrid stroke="rgba(15,23,42,0.08)" />
        <XAxis dataKey="x" type="number" domain={[0, 1]} stroke="#64748b" fontSize={10} tickLine={false}
               label={{ value: kind === 'roc' ? 'False positive rate' : 'Recall', position: 'insideBottom', offset: -2, fill: '#64748b', fontSize: 10 }} />
        <YAxis domain={[0, 1]} stroke="#64748b" fontSize={10} tickLine={false} axisLine={false}
               label={{ value: kind === 'roc' ? 'Recall' : 'Precision', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 10 }} />
        <Tooltip contentStyle={tip} formatter={(v: number) => v.toFixed(3)} />
        <Legend wrapperStyle={{ fontSize: 11 }} formatter={(v) => SHORT[v]} />
        {series.map((s) => <Line key={s.d} type="stepAfter" dataKey={s.d} stroke={COLOR[s.d]} strokeWidth={2} dot={false} connectNulls />)}
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function EvaluationPage() {
  const { data: ev, error, loading, reload } = useApi(() => api.evaluation(), [])
  const [conf, setConf] = useState<(typeof DETS)[number]>('D_full')

  if (loading && !ev) return <Loading label="Loading evaluation…" />
  if (error || !ev) {
    return (
      <div className="space-y-5">
        <h1 className="text-xl font-bold tracking-tight text-white">Evaluation</h1>
        <div className="card card-pad flex items-start gap-3">
          <FileWarning size={20} className="mt-0.5 shrink-0 text-warn" />
          <div>
            <p className="text-sm font-semibold text-slate-100">No evaluation report is available</p>
            <p className="mt-1 text-sm text-slate-400">{error ?? 'Run the pipeline below.'}</p>
            <pre className="mt-3 overflow-x-auto rounded-lg bg-ink-850 p-3 font-mono text-[11px] text-slate-400">{`python -m backend.ml.generate_dataset\npython -m backend.ml.train_model`}</pre>
            <button className="btn-ghost mt-3" onClick={reload}>Retry</button>
          </div>
        </div>
      </div>
    )
  }

  const A = ev.ablation
  const D = A.D_full
  const B = A.B_ml
  const fams = Object.entries(ev.per_family)
  const mal = fams.filter(([, r]) => r.malicious)
  const ben = fams.filter(([, r]) => !r.malicious)
  const rob = Object.entries(ev.robustness)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Evaluation</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Every number is computed by <code className="font-mono text-slate-400">backend/ml/evaluate.py</code> from held-out sessions, running the same analyzer used in production.
          Report generated {ev.generated_at.replace('T', ' ')} in {ev.eval_seconds}s.
        </p>
      </div>

      <div className="rounded-lg border border-warn/25 bg-warn/[0.06] px-4 py-3">
        <p className="flex items-start gap-2 text-sm text-slate-300">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" />
          <span><strong className="text-warn">Synthetic data.</strong> {ev.dataset} {ev.split} Results show the pipeline works on this data;
            they do not establish performance on real agent telemetry. {ev.mode}</span>
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Test set" value={ev.n_test_sessions.toLocaleString()} hint={`${ev.n_malicious_sessions} malicious · ${ev.n_benign_sessions} benign sessions · ${ev.n_test_actions.toLocaleString()} actions`} />
        <StatCard label="Full architecture · F1" value={D.action_level.f1.toFixed(3)} tone="safe" hint={`P ${D.action_level.precision.toFixed(3)} · R ${D.action_level.recall.toFixed(3)} (action level)`} />
        <StatCard label="False-positive rate" value={pct(D.benign_sessions_only.false_positive_rate, 2)} tone="safe"
                  hint={`ML alone: ${pct(B.benign_sessions_only.false_positive_rate, 1)} of benign actions flagged`} />
        <StatCard label="Decision latency" value={`${ev.live_latency.mean_ms.toFixed(0)} ms`} tone="ai" hint={`p95 ${ev.live_latency.p95_ms.toFixed(0)} ms · ML inference is ${(100 * (ev.live_latency.stage_mean_ms.ml ?? 0) / ev.live_latency.mean_ms).toFixed(0)}% of it`} icon={<Timer size={15} />} />
      </div>

      {/* ablation */}
      <Card title="Ablation: what each layer adds" subtitle="Same test sessions, same actions. No winner is declared: read the trade-offs.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px]">
            <thead>
              <tr className="border-b border-white/[0.06]">
                <th className="th">Detector</th><th className="th">Precision</th><th className="th">Recall</th><th className="th">F1</th>
                <th className="th">FPR</th><th className="th">FNR</th><th className="th">ROC-AUC</th><th className="th">PR-AUC</th>
                <th className="th">Session recall</th><th className="th">Benign sessions flagged</th><th className="th">Latency (steps)</th>
              </tr>
            </thead>
            <tbody>
              {DETS.map((d) => {
                const m = A[d]; const a = m.action_level; const s = m.session_level
                return (
                  <tr key={d} className="border-b border-white/[0.04]">
                    <td className="td whitespace-nowrap text-xs font-semibold" style={{ color: COLOR[d] }}>{SHORT[d]}</td>
                    <Cell v={f3(a.precision)} /><Cell v={f3(a.recall)} /><Cell v={f3(a.f1)} />
                    <Cell v={pct(m.benign_sessions_only.false_positive_rate, 2)} bad={m.benign_sessions_only.false_positive_rate > 0.05} good={m.benign_sessions_only.false_positive_rate < 0.01} />
                    <Cell v={pct(a.false_negative_rate)} bad={a.false_negative_rate > 0.5} />
                    <Cell v={f3(m.roc_auc)} /><Cell v={f3(m.pr_auc)} />
                    <Cell v={pct(s.recall)} /><Cell v={pct(s.false_positive_rate)} bad={s.false_positive_rate > 0.2} good={s.false_positive_rate === 0} />
                    <Cell v={m.detection_latency_steps.mean === null ? '—' : m.detection_latency_steps.mean.toFixed(2)} />
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="mt-4 grid gap-3 text-xs leading-relaxed text-slate-400 md:grid-cols-2">
          <p><strong className="text-slate-300">A · Rules only</strong> never falsely flags ({pct(A.A_rules.benign_sessions_only.false_positive_rate, 1)}) but recalls only {pct(A.A_rules.action_level.recall, 0)} of malicious actions:
            it cannot see anything built from sanctioned actions (the {ev.novel_families.length} novel families) or loops.</p>
          <p><strong className="text-slate-300">B · ML only</strong> generalises (recall {pct(B.action_level.recall, 0)}) but flags {pct(B.session_level.false_positive_rate, 0)} of benign sessions, because
            unusual behaviour is not the same as dangerous behaviour. A model-only guard would block legitimate work.</p>
          <p><strong className="text-slate-300">C · ML + policy</strong> is B with hard rules OR-ed in: it inherits B's false positives. Adding rules to a noisy detector does not fix the noise.</p>
          <p><strong className="text-slate-300">D · Full architecture</strong> is the only configuration with both low false positives and high recall here. The cost is complexity, a {ev.live_latency.mean_ms.toFixed(0)} ms decision, and rules
            (sequence patterns, loop thresholds) that encode assumptions from the same designer as the data.</p>
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="ROC curve" subtitle={`Action level · ROC-AUC B ${f3(B.roc_auc)} · D ${f3(D.roc_auc)}`}><Curves ev={ev} kind="roc" /></Card>
        <Card title="Precision–recall curve" subtitle={`PR-AUC B ${f3(B.pr_auc)} · D ${f3(D.pr_auc)}`}><Curves ev={ev} kind="pr" /></Card>
        <Card title="Confusion matrix" subtitle="Action level, at the deployed operating point"
              action={<select className="input !w-auto !py-1 text-xs" value={conf} onChange={(e) => setConf(e.target.value as any)}>{DETS.map((d) => <option key={d} value={d}>{SHORT[d]}</option>)}</select>}>
          <Confusion d={A[conf]} />
          <p className="mt-2 text-[10px] text-slate-600">Accuracy is {pct(A[conf].action_level.accuracy)}, but with imbalanced classes it is the wrong headline: use precision, recall and FPR.</p>
        </Card>
      </div>

      {/* per family */}
      <Card title="Results by behaviour family" subtitle="Action recall (R), session detection (S) and mean latency in steps (L) for attacks · session FPR for benign · * = novel family, no rule targets it">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px]">
            <thead><tr className="border-b border-white/[0.06]"><th className="th">Family</th><th className="th">Sessions</th>{DETS.map((d) => <th key={d} className="th" style={{ color: COLOR[d] }}>{SHORT[d].split(' · ')[0]}</th>)}</tr></thead>
            <tbody>
              {mal.map(([name, r]) => (
                <tr key={name} className="border-b border-white/[0.04]">
                  <td className="td text-xs font-medium text-slate-200">{name.replace(/_/g, ' ')}{r.novel && <span className="ml-1 text-warn">*</span>}</td>
                  <td className="td font-mono text-xs text-slate-500">{r.n_sessions}</td>
                  {DETS.map((d) => (
                    <td key={d} className="td font-mono text-[11px] text-slate-400">
                      R {r[d].action_recall.toFixed(2)} · S {r[d].session_detection.toFixed(2)}{r[d].mean_latency_steps !== null && ` · L ${r[d].mean_latency_steps}`}
                    </td>
                  ))}
                </tr>
              ))}
              {ben.map(([name, r]) => (
                <tr key={name} className="border-b border-white/[0.04] bg-safe/[0.03]">
                  <td className="td text-xs font-medium text-slate-200">{name.replace(/_/g, ' ')} <span className="text-slate-600">(benign)</span></td>
                  <td className="td font-mono text-xs text-slate-500">{r.n_sessions}</td>
                  {DETS.map((d) => (
                    <td key={d} className={`td font-mono text-[11px] ${r[d].session_fpr > 0.2 ? 'text-crit' : 'text-safe'}`}>sessions flagged {pct(r[d].session_fpr, 0)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* robustness */}
      <Card title="Robustness" subtitle="Benign-session false-positive rate and malicious-session detection under perturbation (subsample)">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px]">
            <thead><tr className="border-b border-white/[0.06]"><th className="th">Perturbation</th><th className="th">Sessions</th>{DETS.map((d) => <th key={d} className="th" style={{ color: COLOR[d] }}>{SHORT[d].split(' · ')[0]} · FPR / detect</th>)}</tr></thead>
            <tbody>
              {rob.map(([name, r]) => (
                <tr key={name} className="border-b border-white/[0.04]">
                  <td className="td text-xs font-medium text-slate-200">{name.replace(/_/g, ' ')}</td>
                  <td className="td font-mono text-xs text-slate-500">{r.n_sessions}</td>
                  {DETS.map((d) => (
                    <td key={d} className="td font-mono text-[11px]">
                      <span className={r[d].benign_session_fpr > 0.2 ? 'text-crit' : r[d].benign_session_fpr === 0 ? 'text-safe' : 'text-slate-300'}>{pct(r[d].benign_session_fpr, 1)}</span>
                      <span className="text-slate-600"> / </span><span className="text-slate-300">{pct(r[d].malicious_session_detection, 1)}</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-slate-600">
          noise = 25% extra benign steps · duplicates = repeated events · delays = 15% of intervals ×15 · missing = 20% of events dropped ·
          task change = a benign session judged against a different plausible task · benign prior drift = normal behaviour from a much more perturbed transition prior.
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Latency" icon={<Timer size={14} className="text-slate-500" />} subtitle="Measured on real per-action inference">
          <dl className="space-y-1.5 text-sm">
            {[
              ['Decision latency, mean / p50 / p95', `${ev.live_latency.mean_ms} / ${ev.live_latency.p50_ms} / ${ev.live_latency.p95_ms} ms`],
              ...Object.entries(ev.live_latency.stage_mean_ms).map(([k, v]) => [`  stage · ${k}`, `${v} ms`]),
              ['Detection latency (D), mean steps after onset', D.detection_latency_steps.mean === null ? '—' : String(D.detection_latency_steps.mean)],
              ['Flagged on the first malicious step (D)', pct(D.detection_latency_steps.flagged_on_first_malicious_step, 0)],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 border-b border-white/[0.04] pb-1"><dt className="whitespace-pre text-slate-500">{k}</dt><dd className="font-mono text-xs text-slate-300">{v}</dd></div>
            ))}
          </dl>
        </Card>
        <Card title="How separable is this data?" subtitle="Honest disclosure: best single-feature ROC-AUC on the test set" icon={<Info size={14} className="text-beam" />}>
          <ul className="space-y-1.5">
            {ev.single_feature_separability.map((f) => (
              <li key={f.feature} className="flex items-center justify-between text-xs"><span className="font-mono text-slate-400">{f.feature}</span><span className="font-mono text-slate-300">{f.auc.toFixed(3)}</span></li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
            An early version of this project scored F1 0.88 mostly because one hand-written feature separated the classes at AUC 0.995. The
            corpus and features were redesigned (session-grouped splits, learned fingerprints, hard negatives, novel attacks, distribution shift) and that number is now {ev.single_feature_separability[0]?.auc.toFixed(2)}.
          </p>
        </Card>
      </div>

      <Card title="Development set vs fresh holdout" subtitle="The STAGNATION and BULK_READ loop rules were added after inspecting the dev set">
        <p className="text-xs leading-relaxed text-slate-400">{ev.dev_set.note}</p>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[520px]"><thead><tr className="border-b border-white/[0.06]"><th className="th">Detector</th><th className="th">F1 dev</th><th className="th">F1 test</th><th className="th">Session recall dev</th><th className="th">Session recall test</th></tr></thead>
            <tbody>{DETS.map((d) => (
              <tr key={d} className="border-b border-white/[0.04]"><td className="td text-xs" style={{ color: COLOR[d] }}>{SHORT[d]}</td>
                <Cell v={f3(ev.dev_set.detectors[d].action_level.f1)} /><Cell v={f3(A[d].action_level.f1)} />
                <Cell v={pct(ev.dev_set.detectors[d].session_level.recall)} /><Cell v={pct(A[d].session_level.recall)} /></tr>))}</tbody></table>
        </div>
      </Card>

      <Card title="Limitations" icon={<AlertTriangle size={14} className="text-warn" />}>
        <ul className="list-disc space-y-1.5 pl-5 text-xs leading-relaxed text-slate-400">
          {ev.limitations.map((l) => <li key={l}>{l}</li>)}
          <li>{(ev.friction_on_benign.monitor_rate * 100).toFixed(1)}% of benign actions still receive a MONITOR decision: low friction, not zero.</li>
        </ul>
      </Card>
    </div>
  )
}
