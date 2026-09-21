import { Pause, Play, RotateCcw, SkipBack, SkipForward } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Replay } from '../types'
import { AgentStatusPill, RiskMeter } from './ui'

const EVENT_COLOR: Record<string, string> = {
  ACTION_BLOCKED: '#dc2626', AGENT_PAUSED: '#dc2626', INCIDENT_CREATED: '#dc2626', RECOVERY_FAILED: '#dc2626',
  POLICY_VIOLATION: '#ea580c', PRIVILEGE_ESCALATION_DETECTED: '#ea580c', SEQUENCE_PATTERN_DETECTED: '#ea580c',
  ANOMALY_DETECTED: '#7c3aed', APPROVAL_REQUESTED: '#7c3aed', INJECTION_INDICATOR_DETECTED: '#7c3aed',
  RISK_CALCULATED: '#ca8a04', DRIFT_DETECTED: '#ca8a04', RECOVERY_PARTIAL: '#ca8a04',
  RECOVERY_STARTED: '#0284c7', RECOVERY_STEP: '#0284c7',
  RECOVERY_VERIFIED: '#16a34a', INCIDENT_RESOLVED: '#16a34a', HUMAN_APPROVAL: '#16a34a', TRUST_CHANGED: '#94a3b8',
}
const HIDE = new Set(['RISK_CALCULATED', 'TRUST_CHANGED'])     // shown as state, not as rows, in compact mode

const fmtT = (s: number) => {
  const m = Math.floor(s / 60)
  const r = Math.floor(s % 60)
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
}

/**
 * Interactive incident replay. Every frame comes from the recorded audit trail;
 * agent status and environment state are reconstructed from what was recorded.
 */
export function ReplayPlayer({ replay }: { replay: Replay }) {
  const frames = useMemo(() => replay.frames.filter((f) => !HIDE.has(f.event_type)), [replay])
  const [idx, setIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const listRef = useRef<HTMLOListElement>(null)

  useEffect(() => {
    if (!playing) return
    if (idx >= frames.length - 1) {
      setPlaying(false)
      return
    }
    const t = setTimeout(() => setIdx((i) => Math.min(frames.length - 1, i + 1)), 900 / speed)
    return () => clearTimeout(t)
  }, [playing, idx, frames.length, speed])

  useEffect(() => {
    listRef.current?.querySelector('[data-current="true"]')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [idx])

  if (!frames.length) return <p className="py-8 text-center text-sm text-slate-600">No recorded events.</p>
  const f = frames[idx]
  // last known risk up to this frame
  const lastRisk = [...replay.frames].filter((x) => x.t <= f.t && x.risk_score !== null).at(-1)
  const level = (lastRisk?.risk_level ?? 'LOW') as any
  const envBad = Object.entries(f.environment).filter(([, s]) => s !== 'HEALTHY')

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-ghost !px-3 !py-1.5" onClick={() => { setIdx(0); setPlaying(false) }} title="Restart"><RotateCcw size={14} /></button>
        <button className="btn-ghost !px-3 !py-1.5" onClick={() => setIdx((i) => Math.max(0, i - 1))} title="Step back"><SkipBack size={14} /></button>
        <button className="btn-primary !px-4 !py-1.5" onClick={() => { if (idx >= frames.length - 1) setIdx(0); setPlaying((p) => !p) }}>
          {playing ? <Pause size={14} /> : <Play size={14} />} {playing ? 'Pause' : 'Play'}
        </button>
        <button className="btn-ghost !px-3 !py-1.5" onClick={() => setIdx((i) => Math.min(frames.length - 1, i + 1))} title="Step forward"><SkipForward size={14} /></button>
        <div className="ml-1 flex gap-1">
          {[0.5, 1, 2, 4].map((s) => (
            <button key={s} onClick={() => setSpeed(s)}
                    className={`rounded-md px-2 py-1 text-[11px] font-semibold ${speed === s ? 'bg-beam/15 text-beam' : 'text-slate-500 hover:bg-white/[0.04]'}`}>
              {s}×
            </button>
          ))}
        </div>
        <span className="ml-auto font-mono text-xs text-slate-500">{fmtT(f.t)} / {fmtT(replay.duration_s)} · event {idx + 1}/{frames.length}</span>
      </div>

      <input type="range" min={0} max={frames.length - 1} value={idx} onChange={(e) => { setIdx(Number(e.target.value)); setPlaying(false) }}
             className="w-full accent-sky-400" aria-label="Replay position" />

      <div className="grid gap-4 lg:grid-cols-5">
        <ol ref={listRef} className="max-h-80 space-y-1 overflow-y-auto pr-1 lg:col-span-3">
          {frames.map((fr, i) => {
            const c = EVENT_COLOR[fr.event_type] ?? '#475569'
            const cur = i === idx
            return (
              <li key={i} data-current={cur}>
                <button onClick={() => { setIdx(i); setPlaying(false) }}
                        className={`flex w-full gap-2.5 rounded-lg border px-2.5 py-1.5 text-left transition-colors ${
                          cur ? 'border-white/20 bg-white/[0.06]' : i > idx ? 'border-transparent opacity-40 hover:opacity-70' : 'border-transparent hover:bg-white/[0.03]'}`}>
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: c }} />
                  <span className="w-11 shrink-0 font-mono text-[11px] text-slate-500">{fmtT(fr.t)}</span>
                  <span className="min-w-0">
                    <span className="block text-xs font-semibold" style={{ color: c }}>{fr.event_type.replace(/_/g, ' ')}</span>
                    <span className="block truncate text-[11px] text-slate-500">{fr.reason}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ol>

        <div className="space-y-3 rounded-xl border border-white/[0.06] bg-ink-850/60 p-3 lg:col-span-2">
          <div className="flex items-center gap-4">
            <RiskMeter score={lastRisk?.risk_score ?? 0} level={level} size={96} />
            <div className="space-y-2">
              <p className="label">Agent status</p>
              <AgentStatusPill status={f.agent_status} />
              {f.decision && <p className="font-mono text-[11px] text-slate-400">decision: {f.decision}</p>}
            </div>
          </div>
          <div>
            <p className="label">Simulated environment at this moment</p>
            {envBad.length === 0 ? (
              <p className="mt-1 text-[11px] text-safe">All resources match baseline.</p>
            ) : (
              <ul className="mt-1 space-y-0.5">
                {envBad.map(([n, s]) => (
                  <li key={n} className="flex justify-between gap-2 text-[11px]">
                    <span className="truncate font-mono text-slate-400">{n}</span>
                    <span className="font-mono font-semibold text-crit">{s}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {f.action && (
            <p className="border-t border-white/[0.06] pt-2 text-[11px] leading-relaxed text-slate-500">
              <span className="font-mono text-slate-300">{f.action.action_type}</span> — anomaly {f.action.anomaly_score.toFixed(2)},
              risk {f.action.risk_score}, alignment {f.action.task_relevance.toFixed(2)}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
