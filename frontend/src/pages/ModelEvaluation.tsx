import { AlertTriangle, BrainCircuit, Database, FileWarning, Info } from 'lucide-react'
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Card, ErrorState, Loading, StatCard } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'

const tooltipStyle = {
  backgroundColor: '#0f1422',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 8,
  fontSize: 12,
  color: '#e2e8f0',
}

export default function ModelEvaluation() {
  const { data, error, loading, reload } = useApi(() => api.mlStatus(), [])
  const { data: policy } = useApi(() => api.policy(), [])

  if (loading && !data) return <Loading label="Loading model status…" />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (!data) return null

  if (!data.loaded || !data.evaluation) {
    return (
      <div className="space-y-5">
        <h1 className="text-xl font-bold tracking-tight text-white">Model Evaluation</h1>
        <Card>
          <div className="flex items-start gap-3 py-4">
            <FileWarning size={20} className="mt-0.5 shrink-0 text-warn" />
            <div>
              <p className="text-sm font-semibold text-slate-100">
                The trained model is not available
              </p>
              <p className="mt-1 text-sm text-slate-400">
                {data.error ?? 'No evaluation report was found.'}
              </p>
              <p className="mt-3 text-xs text-slate-500">
                The safety layer still runs — it falls back to a transparent heuristic and labels
                every score accordingly — but the ML component is inactive.
              </p>
              <pre className="mt-3 overflow-x-auto rounded-lg bg-ink-850 p-3 font-mono text-[11px] text-slate-400">
{`python -m backend.ml.generate_dataset
python -m backend.ml.train_model`}
              </pre>
            </div>
          </div>
        </Card>
      </div>
    )
  }

  const ev = data.evaluation
  const m = ev.metrics
  const chart = [
    { name: 'Precision', value: m.precision * 100, color: '#38bdf8' },
    { name: 'Recall', value: m.recall * 100, color: '#8b5cf6' },
    { name: 'F1', value: m.f1 * 100, color: '#22c55e' },
    { name: 'Accuracy', value: m.accuracy * 100, color: '#64748b' },
    { name: 'FPR', value: m.false_positive_rate * 100, color: '#f97316' },
    { name: 'FNR', value: m.false_negative_rate * 100, color: '#ef4444' },
  ]

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white">Model Evaluation</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Measured on a held-out split of the synthetic dataset. These figures are read from the
          report written by the training script — they are not typed in by hand.
        </p>
      </div>

      <div className="rounded-lg border border-warn/25 bg-warn/[0.06] px-4 py-3">
        <p className="flex items-start gap-2 text-sm text-slate-300">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" />
          <span>
            <strong className="text-warn">Synthetic data.</strong> {ev.dataset} It is generated
            locally from a hand-written behavioural model of the agent and is not real-world
            telemetry. Numbers below describe the prototype only.
          </span>
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Precision" value={m.precision.toFixed(3)} tone="ai"
          hint="Of the actions flagged, how many were genuinely abnormal" />
        <StatCard label="Recall" value={m.recall.toFixed(3)} tone="safe"
          hint="Of the abnormal actions, how many were caught" />
        <StatCard label="F1 score" value={m.f1.toFixed(3)}
          hint="Harmonic mean of precision and recall" />
        <StatCard label="False positive rate" value={m.false_positive_rate.toFixed(3)} tone="high"
          hint="Legitimate actions wrongly flagged" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Metric comparison"
          subtitle="All values as percentages"
          icon={<BrainCircuit size={14} className="text-ai" />}
        >
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={chart}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="name" stroke="#64748b" fontSize={11} tickLine={false} />
              <YAxis stroke="#64748b" fontSize={11} domain={[0, 100]} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ fill: 'rgba(255,255,255,0.03)' }}
                formatter={(v: number) => `${v.toFixed(1)}%`}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {chart.map((c) => (
                  <Cell key={c.name} fill={c.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Confusion matrix" subtitle="Held-out test split">
          <div className="grid grid-cols-2 gap-3">
            {[
              ['True positives', m.true_positives, 'text-safe', 'Abnormal actions correctly flagged'],
              ['False positives', m.false_positives, 'text-high', 'Normal actions wrongly flagged'],
              ['False negatives', m.false_negatives, 'text-crit', 'Abnormal actions missed'],
              ['True negatives', m.true_negatives, 'text-slate-300', 'Normal actions correctly passed'],
            ].map(([label, value, cls, hint]) => (
              <div key={String(label)} className="rounded-lg border border-white/[0.06] bg-ink-850/60 p-3">
                <p className="label">{label as string}</p>
                <p className={`mt-1 font-mono text-2xl font-bold tabular-nums ${cls as string}`}>
                  {value as number}
                </p>
                <p className="mt-1 text-[10px] leading-snug text-slate-600">{hint as string}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="label">Mean anomaly · normal</p>
              <p className="mt-0.5 font-mono text-safe">{ev.mean_anomaly_normal.toFixed(3)}</p>
            </div>
            <div>
              <p className="label">Mean anomaly · abnormal</p>
              <p className="mt-0.5 font-mono text-crit">{ev.mean_anomaly_abnormal.toFixed(3)}</p>
            </div>
          </div>
        </Card>
      </div>

      <Card
        title="Why accuracy is the wrong headline here"
        icon={<Info size={14} className="text-beam" />}
      >
        <p className="text-sm leading-relaxed text-slate-400">{ev.note}</p>
        <p className="mt-3 text-sm leading-relaxed text-slate-400">
          Accuracy on this split is {(m.accuracy * 100).toFixed(1)}%, but the classes are
          imbalanced ({ev.test_positives} abnormal out of {ev.n_test} test records) and the model
          never sees a label during training — it is a one-class novelty detector fitted on{' '}
          {ev.n_train_normal.toLocaleString()} sanctioned actions only. That is also precisely why
          the model is one input to the decision and never the decision itself: at a{' '}
          {(m.false_positive_rate * 100).toFixed(1)}% false-positive rate, a model-only guardrail
          would block legitimate agent work several times an hour.
        </p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Model configuration"
          subtitle="Loaded once at startup — never retrained on boot"
          icon={<Database size={14} className="text-slate-500" />}
        >
          <dl className="space-y-2 text-sm">
            {[
              ['Algorithm', ev.model],
              ['Features', String(data.n_features)],
              ['Training samples (normal only)', ev.n_train_normal.toLocaleString()],
              ['Test samples', ev.n_test.toLocaleString()],
              ['Decision threshold', String(ev.decision_threshold)],
              ['Calibration t (5th pct of normal raw scores)', data.calibration.t.toFixed(5)],
              ['Calibration s (std/4)', data.calibration.s.toFixed(5)],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 border-b border-white/[0.04] pb-1.5">
                <dt className="text-slate-500">{k}</dt>
                <dd className="text-right font-mono text-xs text-slate-300">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-[11px] leading-relaxed text-slate-600">
            Isolation Forest returns an unbounded score where higher means more normal. It is
            mapped to a 0–1 anomaly value with the logistic curve{' '}
            <code className="font-mono text-slate-500">1 / (1 + exp((raw − t) / s))</code>, using
            constants stored alongside the model so training and runtime scoring stay identical.
          </p>
        </Card>

        <Card title="Behavioural features" subtitle="Extracted for every attempted action">
          <div className="flex flex-wrap gap-1.5">
            {data.feature_names.map((f) => (
              <span
                key={f}
                className="rounded bg-ai/10 px-2 py-1 font-mono text-[10px] text-ai ring-1 ring-inset ring-ai/20"
              >
                {f}
              </span>
            ))}
          </div>
          {policy && (
            <>
              <p className="label mt-5">Active policy</p>
              <dl className="mt-2 space-y-1.5 text-xs">
                <Row k="Policy version" v={policy.policy_version} />
                <Row k="Anomaly alert threshold" v={String(policy.thresholds?.anomaly_alert)} />
                <Row k="Privilege ceiling" v={policy.max_permission_level} />
                <Row k="Min task relevance" v={String(policy.task_scope?.min_task_relevance)} />
                <Row k="Always blocked" v={`${policy.always_block?.length ?? 0} actions`} />
                <Row k="Requires approval" v={(policy.require_human_approval ?? []).join(', ')} />
              </dl>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-white/[0.04] pb-1.5">
      <dt className="text-slate-500">{k}</dt>
      <dd className="text-right font-mono text-slate-300">{v}</dd>
    </div>
  )
}
