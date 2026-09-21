import { AlertTriangle, ArrowRight, CheckCircle2, HelpCircle, ShieldCheck, XCircle } from 'lucide-react'
import type { AllowRationale, Analysis, Counterfactual, ZeroTrustAnswer } from '../types'
import { Bar } from './ui'

export const FACTOR_LABEL: Record<string, string> = {
  behavior_anomaly: 'Behaviour anomaly (ML)',
  resource_sensitivity: 'Resource sensitivity',
  permission_risk: 'Permission risk',
  action_severity: 'Action severity',
  intent_misalignment: 'Intent misalignment',
  sequence_risk: 'Sequence risk',
  behavior_context: 'Trust / drift / taint',
  counterfactual_impact: 'Counterfactual impact',
}

const barColor = (v: number) => (v >= 80 ? '#dc2626' : v >= 50 ? '#ea580c' : '#0284c7')

/** Risk composition: each factor, its weight and the points it contributed. */
export function FactorBars({ a }: { a: Analysis }) {
  const weights = Object.entries(a.factors).map(([k, v]) => {
    const contrib = a.weighted_contributions?.[k] ?? 0
    return { k, v, contrib, w: v > 0 ? contrib / v : 0 }
  })
  const total = Object.values(a.weighted_contributions ?? {}).reduce((x, y) => x + y, 0)
  return (
    <div>
      <div className="space-y-1.5">
        {weights.map(({ k, v, contrib, w }) => (
          <div key={k} className="flex items-center gap-3">
            <span className="w-44 shrink-0 text-xs text-slate-400">{FACTOR_LABEL[k] ?? k}</span>
            <span className="flex-1"><Bar value={v} color={barColor(v)} /></span>
            <span className="w-8 shrink-0 text-right font-mono text-xs tabular-nums text-slate-300">{Math.round(v)}</span>
            <span className="w-24 shrink-0 text-right font-mono text-[10px] text-slate-600">
              ×{w.toFixed(2)} = {contrib.toFixed(1)}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] leading-relaxed text-slate-600">
        Weighted sum {total.toFixed(1)}
        {a.weighted_contributions?.policy_violations
          ? ` + ${a.weighted_contributions.policy_violations} policy-violation penalty`
          : ''}
        {a.floors?.length ? ` · floor applied: ${a.floors.join('; ')}` : ''}. Anomaly came from{' '}
        {a.ml_source}
        {a.ml_raw_score !== null && a.ml_raw_score !== undefined ? ` (raw ${a.ml_raw_score.toFixed(4)})` : ''}.
      </p>
    </div>
  )
}

/** "What could happen if this action were allowed?" ALLOW vs BLOCK, from a simulation. */
export function CounterfactualPanel({ cf, compact = false }: { cf: Counterfactual; compact?: boolean }) {
  const al = cf.allow
  const none = al.resources_impacted.length === 0
  return (
    <div className="space-y-2.5">
      <div className={`grid gap-2 ${compact ? '' : 'sm:grid-cols-2'}`}>
        <div className={`rounded-lg border p-3 ${none ? 'border-safe/20 bg-safe/[0.05]' : 'border-crit/25 bg-crit/[0.06]'}`}>
          <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
            {none ? <CheckCircle2 size={13} className="text-safe" /> : <AlertTriangle size={13} className="text-crit" />}
            If ALLOWED
            <span className="ml-auto font-mono text-[11px] text-slate-400">impact {al.impact_score.toFixed(0)}/100</span>
          </p>
          {none ? (
            <p className="mt-1.5 text-[11px] text-slate-500">No modelled change to the environment.</p>
          ) : (
            <ul className="mt-1.5 space-y-1">
              {al.resources_impacted.map((r) => (
                <li key={r.resource} className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className="font-mono text-slate-400">{r.resource}</span>
                  <ArrowRight size={10} className="text-slate-600" />
                  <span className="font-mono font-semibold text-crit">{r.to}</span>
                  {r.cascade && <span className="chip bg-warn/12 text-warn ring-1 ring-inset ring-warn/25">cascade</span>}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
            {al.recovery_required ? `Recovery required, ~${al.est_recovery_minutes} min (modelled). ` : ''}
            {al.irreversible ? 'Includes harm a state rollback cannot undo. ' : ''}
            {al.privilege_compromise ? 'Privilege compromise. ' : ''}
            {al.data_exposure > 0 ? `Data exposure ${(al.data_exposure * 100).toFixed(0)}%. ` : ''}
            {al.availability_loss > 0 ? `Availability loss ${(al.availability_loss * 100).toFixed(0)}%.` : ''}
          </p>
        </div>
        <div className="rounded-lg border border-safe/20 bg-safe/[0.05] p-3">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
            <ShieldCheck size={13} className="text-safe" /> If BLOCKED
            <span className="ml-auto font-mono text-[11px] text-slate-400">impact {cf.block.impact_score.toFixed(0)}/100</span>
          </p>
          <p className="mt-1.5 text-[11px] text-slate-500">Environment unchanged. No recovery needed.</p>
          <p className="mt-1 text-[10px] leading-relaxed text-slate-500">Task effect: {cf.block.task_effect}.</p>
        </div>
      </div>
      {cf.chain_projection && (
        <div className="rounded-lg border border-high/25 bg-high/[0.05] p-3">
          <p className="text-xs font-semibold text-slate-200">If the attack chain were allowed to continue</p>
          <p className="mt-1 font-mono text-[11px] text-high">
            {cf.chain_projection.steps.join(' → ')} · impact {cf.chain_projection.impact_score_if_chain_completes.toFixed(0)}/100
          </p>
          <p className="mt-1 text-[10px] text-slate-500">
            Also changes: {cf.chain_projection.additional_changes.map((c) => `${c.resource}→${c.to}`).join(', ')}
          </p>
        </div>
      )}
      <p className="text-[10px] text-slate-600">
        Simulated on a copy of the sandbox. Recovery times are modelled estimates, not measurements.
      </p>
    </div>
  )
}

export function ZeroTrustPanel({ items }: { items: ZeroTrustAnswer[] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((q) => (
        <li key={q.question} className="flex gap-2 text-xs">
          {q.ok ? (
            <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-safe" />
          ) : (
            <XCircle size={14} className="mt-0.5 shrink-0 text-crit" />
          )}
          <span>
            <span className="font-semibold text-slate-300">{q.question}</span>{' '}
            <span className="text-slate-400">{q.answer}</span>
          </span>
        </li>
      ))}
      <li className="pt-1 text-[10px] text-slate-600">
        Being an approved agent never implies an approved action: every action is evaluated on these six questions.
      </li>
    </ul>
  )
}

/** "Why was this action allowed?" for borderline actions. */
export function AllowRationaleCard({ r }: { r: AllowRationale }) {
  const rows: [string, string][] = [
    ['Anomaly', r.anomaly],
    ['Policy', r.policy],
    ['Intent alignment', r.intent_alignment],
    ['Resource sensitivity', r.resource_sensitivity],
    ['Sequence', r.sequence],
    ['Final decision', r.final_decision],
  ]
  return (
    <div className="rounded-lg border border-safe/25 bg-safe/[0.05] p-3">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-slate-100">
        <HelpCircle size={13} className="text-safe" /> Why was this action allowed?
      </p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-3">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt className="text-slate-500">{k}</dt>
            <dd className={`font-mono ${k === 'Final decision' ? 'font-semibold text-safe' : 'text-slate-300'}`}>{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{r.why}</p>
    </div>
  )
}

export function MatchedRules({ rules }: { rules: Analysis['matched_rules'] }) {
  if (!rules?.length) return null
  return (
    <ul className="space-y-1">
      {rules.slice(0, 4).map((r, i) => (
        <li key={r.id} className="flex flex-wrap items-baseline gap-2 text-[11px]">
          <span className={`chip ring-1 ring-inset ${i === 0 ? 'bg-beam/12 text-beam ring-beam/25' : 'bg-white/[0.04] text-slate-500 ring-white/10'}`}>
            {r.id}
          </span>
          <span className="font-mono text-slate-500">{r.effect}</span>
          <span className="text-slate-400">{r.reason}</span>
        </li>
      ))}
    </ul>
  )
}
