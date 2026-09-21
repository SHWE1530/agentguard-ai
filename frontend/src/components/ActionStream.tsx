import { ChevronDown, ChevronRight, Lightbulb, Timer } from 'lucide-react'
import { useState } from 'react'
import type { AgentAction } from '../types'
import {
  AllowRationaleCard, CounterfactualPanel, FactorBars, MatchedRules, ZeroTrustPanel,
} from './analysis'
import {
  AnomalyPill, DecisionBadge, RISK_COLOR, RiskBadge, Section, StatusBadge, fmtTime,
} from './ui'

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="label">{label}</p>
      <p className={`mt-0.5 truncate text-slate-300 ${mono ? 'font-mono text-[11px]' : ''}`}>{value}</p>
    </div>
  )
}

/** Everything the system knew when it decided, for one action. */
export function ActionDetail({ action }: { action: AgentAction }) {
  const rf = action.risk_factors
  if (!rf?.factors) return <p className="text-xs text-slate-500">{action.explanation}</p>
  const seq = rf.sequence
  const lat = rf.latency_ms ?? {}
  const drift = rf.drift ?? { score: 0 }

  return (
    <div className="space-y-4">
      <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Tool" value={action.tool_name} mono />
        <Field label="Resource" value={action.resource} mono />
        <Field label="Permission" value={action.permission_level} />
        <Field label="Intent alignment" value={`${rf.intent.alignment.toFixed(2)} · ${rf.intent.task_type}`} mono />
        <Field label="Execution" value={action.execution_result.replace(/_/g, ' ')} />
      </div>

      <Section label="Explanation">
        <p className="text-xs leading-relaxed text-slate-400">{action.explanation}</p>
      </Section>

      {rf.allow_rationale && <AllowRationaleCard r={rf.allow_rationale} />}

      <div className="grid gap-4 lg:grid-cols-2">
        <Section label="Why this risk score (0–100)">
          <FactorBars a={rf} />
        </Section>

        <div className="space-y-4">
          <Section label="Sequence, escalation, loops and drift">
            <ul className="space-y-1.5 text-xs text-slate-400">
              <li>
                Transition surprisal{' '}
                <span className="font-mono text-slate-300">{seq.bigram_deviation.toFixed(2)}</span>
                {seq.trigram_novel ? ' · novel trigram' : ''}
                {' · '}window: <span className="font-mono text-slate-500">{seq.window.slice(-4).join(' → ')}</span>
              </li>
              {seq.patterns.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-1.5">
                  <span className={`chip ring-1 ring-inset ${p.completed ? 'bg-crit/12 text-crit ring-crit/30' : 'bg-high/12 text-high ring-high/25'}`}>
                    {p.name} {p.progress}/{p.total}
                  </span>
                  <span className="font-mono text-[11px] text-slate-500">{p.path.join(' → ')}</span>
                </li>
              ))}
              {seq.privilege_escalation.detected && (
                <li className="text-crit">Privilege escalation ({seq.privilege_escalation.kind}): {seq.privilege_escalation.description}</li>
              )}
              {seq.loop.kind && (
                <li className="text-high">
                  {seq.loop.kind.replace(/_/g, ' ')}: {seq.loop.consecutive_same} identical, {seq.loop.consecutive_failures} failures,
                  {' '}{seq.loop.observe_streak} read-only in a row
                </li>
              )}
              <li>
                Drift <span className="font-mono text-slate-300">{(drift.score * 100).toFixed(0)}%</span> vs threshold{' '}
                <span className="font-mono">{(rf.drift_threshold * 100).toFixed(0)}%</span>
                {rf.drift_alert && <span className="ml-1.5 text-warn">⚠ behavioural drift detected</span>}
              </li>
              {rf.tainted && <li className="text-crit">Session is TAINTED by untrusted content with injection indicators.</li>}
              {rf.injection?.tainted && (
                <li className="text-crit">
                  Injection indicators: {rf.injection.indicators.map((i) => i.label).join(', ')} (score {rf.injection.score})
                </li>
              )}
            </ul>
          </Section>

          <Section label="Policy decision">
            {rf.policy_violations.length > 0 && (
              <ul className="mb-2 space-y-1">
                {rf.policy_violations.map((v) => (
                  <li key={v} className="flex gap-2 text-[11px] text-slate-400">
                    <span className="chip shrink-0 bg-crit/12 text-crit ring-1 ring-inset ring-crit/25">{v.replace(/_/g, ' ')}</span>
                    <span className="pt-0.5">{rf.policy_details?.[v]}</span>
                  </li>
                ))}
              </ul>
            )}
            <MatchedRules rules={rf.matched_rules} />
          </Section>
        </div>
      </div>

      <Section label="Counterfactual: what if this action were allowed?">
        <CounterfactualPanel cf={rf.counterfactual} compact />
      </Section>

      {rf.alternative && (
        <div className="flex gap-2 rounded-lg border border-beam/25 bg-beam/[0.05] p-3 text-xs">
          <Lightbulb size={14} className="mt-0.5 shrink-0 text-beam" />
          <span className="text-slate-400">
            <span className="font-semibold text-slate-200">Safer alternative: </span>
            <span className="font-mono text-beam">{rf.alternative.action}</span> — {rf.alternative.note}
          </span>
        </div>
      )}

      <Section label="Zero-trust evaluation">
        <ZeroTrustPanel items={rf.zero_trust} />
      </Section>

      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/[0.05] pt-2 font-mono text-[10px] text-slate-600">
        <Timer size={11} />
        decision {lat.decision_total?.toFixed(1) ?? lat.total?.toFixed(1)} ms
        {Object.entries(lat).filter(([k]) => !['total', 'decision_total'].includes(k)).map(([k, v]) => (
          <span key={k}>{k} {v.toFixed(2)}</span>
        ))}
        <span>fingerprint v{rf.fingerprint_version}</span>
        <span>trust {rf.trust}</span>
      </p>
    </div>
  )
}

/** One row in the live stream, expandable into the full "why". */
export function ActionRow({ action, defaultOpen = false }: { action: AgentAction; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const color = RISK_COLOR[action.risk_level]
  const blocked = action.decision === 'BLOCK' || action.decision === 'TERMINATE'
  return (
    <li className="animate-fade-up rounded-lg border border-white/[0.06] bg-ink-850/60" style={{ borderLeft: `3px solid ${color}` }}>
      <button onClick={() => setOpen((o) => !o)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-left hover:bg-white/[0.02]">
        <span className="text-slate-600">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</span>
        <span className="shrink-0 font-mono text-[11px] text-slate-500">{fmtTime(action.timestamp)}</span>
        <span className={`min-w-0 flex-1 truncate font-mono text-xs font-semibold ${blocked ? 'text-crit line-through decoration-crit/50' : 'text-slate-200'}`}>
          {action.action_type}
        </span>
        <span className="hidden shrink-0 font-mono text-[10px] text-slate-500 md:block" title="intent alignment with the task">
          align {action.task_relevance.toFixed(2)}
        </span>
        <span className="hidden shrink-0 md:block"><AnomalyPill score={action.anomaly_score} /></span>
        {action.action_status === 'BYPASSED' ? <StatusBadge status="BYPASSED" /> : <DecisionBadge decision={action.decision} />}
        <RiskBadge level={action.risk_level} score={action.risk_score} />
      </button>
      {open && (
        <div className="border-t border-white/[0.06] px-3 py-3 pl-9">
          {action.action_status === 'BYPASSED' && (
            <p className="mb-3 rounded-lg border border-warn/30 bg-warn/[0.07] px-3 py-2 text-xs text-warn">
              Recovery drill: the safety layer was bypassed for this step to simulate damage that slipped through
              (e.g. a monitoring outage). Detection still ran, after the fact.
            </p>
          )}
          <ActionDetail action={action} />
        </div>
      )}
    </li>
  )
}

export function ActionStream({ actions, emptyHint }: { actions: AgentAction[]; emptyHint?: string }) {
  if (!actions.length) {
    return <p className="py-10 text-center text-sm text-slate-600">{emptyHint ?? 'No actions yet.'}</p>
  }
  return (
    <ul className="space-y-2">
      {actions.map((a, i) => (
        <ActionRow key={a.id} action={a} defaultOpen={i === 0 && (a.decision === 'TERMINATE' || a.decision === 'BLOCK')} />
      ))}
    </ul>
  )
}

/** Behavioural sequence: the learned profile against what actually happened. */
export function SequenceDeviation({ actual, prevented = [] }: { actual: AgentAction[]; prevented?: string[] }) {
  return (
    <div className="space-y-3">
      <div>
        <p className="label">Normal sequence for this agent</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {['CHECK', 'READ', 'MAINTAIN', 'REPORT'].map((s, i, arr) => (
            <span key={s} className="flex items-center gap-1">
              <span className="rounded bg-safe/10 px-2 py-1 font-mono text-[10px] font-semibold text-safe ring-1 ring-inset ring-safe/20">{s}</span>
              {i < arr.length - 1 && <span className="text-slate-700">→</span>}
            </span>
          ))}
        </div>
      </div>
      <div>
        <p className="label">Actual sequence observed</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {actual.map((a, i) => {
            const bad = a.risk_level === 'HIGH' || a.risk_level === 'CRITICAL' || a.decision === 'REQUIRE_APPROVAL'
            return (
              <span key={a.id} className="flex items-center gap-1">
                <span
                  className={`rounded px-2 py-1 font-mono text-[10px] font-semibold ring-1 ring-inset ${
                    bad ? 'bg-crit/12 text-crit ring-crit/30 animate-pulse-ring' : 'bg-safe/10 text-safe ring-safe/20'
                  }`}
                  title={`risk ${a.risk_score} · anomaly ${a.anomaly_score.toFixed(2)} · ${a.decision}`}
                >
                  {a.action_type}
                </span>
                {(i < actual.length - 1 || prevented.length > 0) && <span className="text-slate-700">→</span>}
              </span>
            )
          })}
          {prevented.map((p, i) => (
            <span key={p + i} className="flex items-center gap-1">
              <span className="rounded border border-dashed border-slate-600 px-2 py-1 font-mono text-[10px] text-slate-500 line-through" title="planned but never attempted: the agent was halted">
                {p}
              </span>
              {i < prevented.length - 1 && <span className="text-slate-800">→</span>}
            </span>
          ))}
        </div>
        {prevented.length > 0 && (
          <p className="mt-2 text-[11px] text-slate-500">Dashed steps were PREVENTED: the agent was halted before attempting them.</p>
        )}
        {actual.some((a) => a.risk_level === 'HIGH' || a.risk_level === 'CRITICAL') && (
          <p className="mt-1 text-[11px] text-crit">Highlighted steps deviate from the learned behavioural profile.</p>
        )}
      </div>
    </div>
  )
}
