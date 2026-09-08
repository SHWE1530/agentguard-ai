import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { AgentAction } from '../types'
import { AnomalyPill, Bar, RISK_COLOR, RiskBadge, StatusBadge, fmtTime } from './ui'

const FACTOR_LABEL: Record<string, string> = {
  behavior_anomaly: 'Behaviour anomaly',
  resource_sensitivity: 'Resource sensitivity',
  permission_risk: 'Permission risk',
  action_severity: 'Action severity',
  task_relevance_gap: 'Task relevance gap',
}

/** One row in the live stream, expandable into the full "why". */
export function ActionRow({ action, defaultOpen = false }: { action: AgentAction; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const color = RISK_COLOR[action.risk_level]
  const rf = action.risk_factors
  const blocked = action.action_status === 'BLOCKED' || action.action_status === 'REJECTED'

  return (
    <li
      className="animate-fade-up rounded-lg border border-white/[0.06] bg-ink-850/60"
      style={{ borderLeft: `3px solid ${color}` }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-white/[0.02]"
      >
        <span className="text-slate-600">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="shrink-0 font-mono text-[11px] text-slate-500">
          {fmtTime(action.timestamp)}
        </span>
        <span
          className={`min-w-0 flex-1 truncate font-mono text-xs font-semibold ${
            blocked ? 'text-crit line-through decoration-crit/50' : 'text-slate-200'
          }`}
        >
          {action.action_type}
        </span>
        <span className="hidden shrink-0 md:block">
          <AnomalyPill score={action.anomaly_score} />
        </span>
        <StatusBadge status={action.action_status} />
        <RiskBadge level={action.risk_level} score={action.risk_score} />
      </button>

      {open && (
        <div className="space-y-3 border-t border-white/[0.06] px-3 py-3 pl-9">
          <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Tool" value={action.tool_name} mono />
            <Field label="Resource" value={action.resource} mono />
            <Field label="Permission" value={action.permission_level} />
            <Field label="Task relevance" value={action.task_relevance.toFixed(2)} mono />
          </div>

          <div>
            <p className="label">Why this score — risk factors (0–100)</p>
            <div className="mt-2 space-y-1.5">
              {Object.entries(rf.factors ?? {}).map(([k, v]) => (
                <div key={k} className="flex items-center gap-3">
                  <span className="w-40 shrink-0 text-xs text-slate-400">
                    {FACTOR_LABEL[k] ?? k}
                  </span>
                  <span className="flex-1">
                    <Bar value={v} color={v >= 80 ? '#ef4444' : v >= 50 ? '#f97316' : '#38bdf8'} />
                  </span>
                  <span className="w-9 shrink-0 text-right font-mono text-xs tabular-nums text-slate-300">
                    {Math.round(v)}
                  </span>
                  <span className="w-14 shrink-0 text-right font-mono text-[10px] text-slate-600">
                    ×{(rf.weighted_contributions?.[k] / (v || 1)).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] text-slate-600">
              Weighted sum ={' '}
              {Object.values(rf.weighted_contributions ?? {})
                .reduce((a, b) => a + b, 0)
                .toFixed(1)}{' '}
              → risk {action.risk_score} ({action.risk_level}). Anomaly score{' '}
              {action.anomaly_score.toFixed(2)} came from {rf.ml_source ?? 'the model'}
              {rf.ml_raw_score !== null && rf.ml_raw_score !== undefined
                ? ` (raw ${rf.ml_raw_score.toFixed(4)})`
                : ''}
              .
            </p>
          </div>

          {rf.policy_violations?.length > 0 && (
            <div>
              <p className="label">Policy violations</p>
              <ul className="mt-1.5 space-y-1">
                {rf.policy_violations.map((v) => (
                  <li key={v} className="flex gap-2 text-xs text-slate-400">
                    <span className="chip shrink-0 bg-crit/12 text-crit ring-1 ring-inset ring-crit/25">
                      {v.replace(/_/g, ' ')}
                    </span>
                    <span className="pt-0.5">{rf.policy_details?.[v]}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <p className="label">Explanation</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">{action.explanation}</p>
          </div>
        </div>
      )}
    </li>
  )
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="label">{label}</p>
      <p className={`mt-0.5 truncate text-slate-300 ${mono ? 'font-mono text-[11px]' : ''}`}>
        {value}
      </p>
    </div>
  )
}

export function ActionStream({
  actions, emptyHint,
}: {
  actions: AgentAction[]
  emptyHint?: string
}) {
  if (!actions.length) {
    return (
      <p className="py-10 text-center text-sm text-slate-600">
        {emptyHint ?? 'No actions yet.'}
      </p>
    )
  }
  return (
    <ul className="space-y-2">
      {actions.map((a, i) => (
        <ActionRow key={a.id} action={a} defaultOpen={i === 0 && a.risk_level === 'CRITICAL'} />
      ))}
    </ul>
  )
}

/**
 * Behavioural sequence visualisation: the sanctioned baseline against what the
 * agent actually did, with the deviation point highlighted.
 */
export function SequenceDeviation({
  planned, actual,
}: {
  planned: string[]
  actual: AgentAction[]
}) {
  return (
    <div className="space-y-3">
      <div>
        <p className="label">Normal sequence for this agent</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {['CHECK', 'READ', 'MAINTAIN', 'REPORT'].map((s, i, arr) => (
            <span key={s} className="flex items-center gap-1">
              <span className="rounded bg-safe/10 px-2 py-1 font-mono text-[10px] font-semibold text-safe ring-1 ring-inset ring-safe/20">
                {s}
              </span>
              {i < arr.length - 1 && <span className="text-slate-700">→</span>}
            </span>
          ))}
        </div>
      </div>
      <div>
        <p className="label">Actual sequence observed</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {(actual.length ? actual.map((a) => a) : []).map((a, i, arr) => {
            const deviating = a.risk_level === 'HIGH' || a.risk_level === 'CRITICAL'
            return (
              <span key={a.id} className="flex items-center gap-1">
                <span
                  className={`rounded px-2 py-1 font-mono text-[10px] font-semibold ring-1 ring-inset ${
                    deviating
                      ? 'bg-crit/12 text-crit ring-crit/30 animate-pulse-ring'
                      : 'bg-safe/10 text-safe ring-safe/20'
                  }`}
                  title={`risk ${a.risk_score} · anomaly ${a.anomaly_score.toFixed(2)}`}
                >
                  {a.action_type}
                </span>
                {i < arr.length - 1 && <span className="text-slate-700">→</span>}
              </span>
            )
          })}
          {actual.length === 0 &&
            planned.map((p, i) => (
              <span key={p + i} className="flex items-center gap-1">
                <span className="rounded bg-white/[0.04] px-2 py-1 font-mono text-[10px] text-slate-600 ring-1 ring-inset ring-white/[0.06]">
                  {p}
                </span>
                {i < planned.length - 1 && <span className="text-slate-800">→</span>}
              </span>
            ))}
        </div>
        {actual.some((a) => a.risk_level === 'HIGH' || a.risk_level === 'CRITICAL') && (
          <p className="mt-2 text-[11px] text-crit">
            Highlighted steps deviate from the learned behavioural profile.
          </p>
        )}
      </div>
    </div>
  )
}
