import {
  AlertTriangle, CheckCircle2, Loader2, Lock, RefreshCw, ShieldAlert,
  ShieldCheck, ShieldX, XCircle,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { Decision, RiskLevel } from '../types'

/* ------------------------------------------------------------------ colors */

export const RISK_COLOR: Record<RiskLevel, string> = {
  LOW: '#16a34a',
  MEDIUM: '#ca8a04',
  HIGH: '#ea580c',
  CRITICAL: '#dc2626',
}

const RISK_CLASS: Record<RiskLevel, string> = {
  LOW: 'bg-safe/15 text-safe ring-1 ring-inset ring-safe/30',
  MEDIUM: 'bg-warn/15 text-warn ring-1 ring-inset ring-warn/30',
  HIGH: 'bg-high/15 text-high ring-1 ring-inset ring-high/30',
  CRITICAL: 'bg-crit/15 text-crit ring-1 ring-inset ring-crit/35',
}

const STATUS_CLASS: Record<string, string> = {
  ALLOWED: 'bg-safe/15 text-safe ring-1 ring-inset ring-safe/30',
  APPROVED: 'bg-safe/15 text-safe ring-1 ring-inset ring-safe/30',
  MONITORED: 'bg-warn/15 text-warn ring-1 ring-inset ring-warn/30',
  BLOCKED: 'bg-crit/15 text-crit ring-1 ring-inset ring-crit/35',
  REJECTED: 'bg-crit/15 text-crit ring-1 ring-inset ring-crit/35',
  PENDING_APPROVAL: 'bg-ai/15 text-ai ring-1 ring-inset ring-ai/30',
  PENDING: 'bg-ai/15 text-ai ring-1 ring-inset ring-ai/30',
  BYPASSED: 'bg-warn/15 text-warn ring-1 ring-inset ring-warn/40',
}

export const AGENT_STATUS_CLASS: Record<string, string> = {
  IDLE: 'text-slate-400 bg-slate-500/15 ring-slate-400/25',
  RUNNING: 'text-beam bg-beam/15 ring-beam/30',
  SUSPICIOUS: 'text-high bg-high/15 ring-high/30',
  PAUSED: 'text-crit bg-crit/15 ring-crit/35',
  STOPPED: 'text-crit bg-crit/15 ring-crit/35',
}

/* ------------------------------------------------------------------ badges */

export function RiskBadge({ level, score }: { level: RiskLevel; score?: number }) {
  return (
    <span className={`chip ${RISK_CLASS[level]}`}>
      {level}
      {score !== undefined && <span className="font-mono normal-case">{Math.round(score)}</span>}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_CLASS[status] ?? 'bg-white/5 text-slate-300 ring-1 ring-inset ring-white/10'
  const Icon =
    status === 'BLOCKED' || status === 'REJECTED'
      ? ShieldX
      : status === 'PENDING_APPROVAL' || status === 'PENDING'
        ? Lock
        : status === 'MONITORED'
          ? ShieldAlert
          : ShieldCheck
  return (
    <span className={`chip ${cls}`}>
      <Icon size={12} />
      {status.replace(/_/g, ' ')}
    </span>
  )
}

export function AgentStatusPill({ status }: { status: string }) {
  const cls = AGENT_STATUS_CLASS[status] ?? AGENT_STATUS_CLASS.IDLE
  const live = status === 'RUNNING'
  return (
    <span className={`chip ring-1 ring-inset ${cls}`}>
      <span
        className={`h-1.5 w-1.5 rounded-full bg-current ${live ? 'animate-pulse' : ''}`}
      />
      {status}
    </span>
  )
}

/* ------------------------------------------------------------------- cards */

export function Card({
  title, subtitle, icon, action, children, className = '',
}: {
  title?: string
  subtitle?: string
  icon?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-white/[0.06] px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              {icon}
              {title}
            </h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="card-pad">{children}</div>
    </section>
  )
}

export function StatCard({
  label, value, hint, tone = 'default', icon,
}: {
  label: string
  value: ReactNode
  hint?: string
  tone?: 'default' | 'safe' | 'warn' | 'high' | 'crit' | 'ai'
  icon?: ReactNode
}) {
  const toneClass = {
    default: 'text-slate-100',
    safe: 'text-safe',
    warn: 'text-warn',
    high: 'text-high',
    crit: 'text-crit',
    ai: 'text-ai',
  }[tone]
  return (
    <div className="card card-pad">
      <div className="flex items-center justify-between">
        <p className="label">{label}</p>
        {icon && <span className="text-slate-600">{icon}</span>}
      </div>
      <p className={`mt-2 font-mono text-2xl font-bold tabular-nums ${toneClass}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ states */

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500">
      <Loader2 size={16} className="animate-spin" />
      {label}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card card-pad flex flex-col items-start gap-3 border-crit/25 bg-crit/[0.06]">
      <div className="flex items-start gap-2.5">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-crit" />
        <div>
          <p className="text-sm font-semibold text-slate-100">Something went wrong</p>
          <p className="mt-1 text-sm text-slate-400">{message}</p>
        </div>
      </div>
      {onRetry && (
        <button className="btn-ghost" onClick={onRetry}>
          <RefreshCw size={14} /> Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, hint, icon }: { title: string; hint?: string; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <span className="text-slate-700">{icon ?? <ShieldCheck size={28} />}</span>
      <p className="text-sm font-medium text-slate-400">{title}</p>
      {hint && <p className="max-w-md text-xs text-slate-600">{hint}</p>}
    </div>
  )
}

export function VerifyBadge({ verified }: { verified: boolean }) {
  return verified ? (
    <span className="chip bg-safe/15 text-safe ring-1 ring-inset ring-safe/30">
      <CheckCircle2 size={12} /> Recovery verified
    </span>
  ) : (
    <span className="chip bg-crit/15 text-crit ring-1 ring-inset ring-crit/35">
      <XCircle size={12} /> Recovery failed
    </span>
  )
}

/* ------------------------------------------------------------------ meters */

/** Animated 0–100 risk meter. */
export function RiskMeter({ score, level, size = 132 }: { score: number; level: RiskLevel; size?: number }) {
  const r = size / 2 - 10
  const c = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, score)) / 100
  const color = RISK_COLOR[level]
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e2e8f0" strokeWidth={10} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={10}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
          style={{ transition: 'stroke-dashoffset 700ms cubic-bezier(.22,1,.36,1), stroke 400ms' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-2xl font-bold tabular-nums" style={{ color }}>
          {Math.round(score)}
        </span>
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          / 100
        </span>
      </div>
    </div>
  )
}

/** Horizontal bar used for anomaly scores and risk factor breakdowns. */
export function Bar({ value, max = 100, color = '#0284c7' }: { value: number; max?: number; color?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  )
}

export function AnomalyPill({ score }: { score: number }) {
  const color = score >= 0.75 ? '#dc2626' : score >= 0.4 ? '#ca8a04' : '#16a34a'
  return (
    <span className="inline-flex items-center gap-2">
      <span className="font-mono text-xs tabular-nums" style={{ color }}>
        {score.toFixed(2)}
      </span>
      <span className="hidden w-14 sm:block">
        <Bar value={score * 100} color={color} />
      </span>
    </span>
  )
}

export const fmtTime = (iso: string) => {
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export const fmtDateTime = (iso: string) => {
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  return d.toLocaleString([], {
    month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}


/* ---------------------------------------------------------------- decisions */

const DECISION_CLASS: Record<Decision, string> = {
  ALLOW: 'bg-safe/12 text-safe ring-safe/25',
  MONITOR: 'bg-warn/12 text-warn ring-warn/25',
  REQUIRE_APPROVAL: 'bg-ai/12 text-ai ring-ai/25',
  BLOCK: 'bg-high/12 text-high ring-high/30',
  TERMINATE: 'bg-crit/15 text-crit ring-crit/35',
}

export function DecisionBadge({ decision }: { decision: Decision }) {
  return (
    <span className={`chip ring-1 ring-inset ${DECISION_CLASS[decision] ?? ''}`}>
      {decision.replace(/_/g, ' ')}
    </span>
  )
}

export const TRUST_COLOR = (score: number) =>
  score >= 80 ? '#16a34a' : score >= 60 ? '#ca8a04' : score >= 40 ? '#ea580c' : '#dc2626'

/** Agent trust score ring, 0-100. */
export function TrustRing({ score, band, size = 84 }: { score: number; band?: string; size?: number }) {
  const r = size / 2 - 7
  const c = 2 * Math.PI * r
  const color = TRUST_COLOR(score)
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} title={band}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e2e8f0" strokeWidth={7} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={7} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)}
          style={{ transition: 'stroke-dashoffset 700ms cubic-bezier(.22,1,.36,1), stroke 400ms' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-lg font-bold tabular-nums" style={{ color }}>{Math.round(score)}</span>
        <span className="text-[8px] font-semibold uppercase tracking-wider text-slate-500">trust</span>
      </div>
    </div>
  )
}

export function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="label">{label}</p>
      <div className="mt-1.5">{children}</div>
    </div>
  )
}
