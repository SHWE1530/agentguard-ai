import { AlertTriangle, CheckCircle2, Loader2, MinusCircle, RotateCcw, XCircle } from 'lucide-react'
import type { RecoveryStep, Verification } from '../types'
import { VerifyBadge } from './ui'

const STEP_LABEL: Record<string, string> = {
  PAUSE_AGENT: 'Agent paused',
  REVERT_PERMISSIONS: 'Unauthorized permission reverted',
  RESTORE_RESOURCES: 'Resource state restored',
  INTEGRITY_VERIFICATION: 'Integrity verified (state + checksum)',
}
const ORDER = Object.keys(STEP_LABEL)

/**
 * Recovery as a checklist of real steps. Nothing here is decorative: each row is
 * a step the recovery engine executed and each status is what it reported.
 */
export function RecoveryChecklist({
  steps, running = false, outcome, verification, residual = [], attempt, onRetry, retrying = false,
}: {
  steps: RecoveryStep[]
  running?: boolean
  outcome?: 'SUCCESS' | 'PARTIAL' | 'FAILED'
  verification?: Verification | null
  residual?: string[]
  attempt?: number
  onRetry?: () => void
  retrying?: boolean
}) {
  const done = new Map(steps.map((s) => [s.step, s]))
  return (
    <div className="space-y-3">
      <ul className="space-y-2">
        {ORDER.map((key) => {
          const s = done.get(key)
          const pending = !s
          const Icon = s
            ? s.status === 'OK' ? CheckCircle2 : s.status === 'PARTIAL' ? AlertTriangle : s.status === 'SKIPPED' ? MinusCircle : XCircle
            : running ? Loader2 : MinusCircle
          const color = s
            ? s.status === 'OK' ? 'text-safe' : s.status === 'PARTIAL' ? 'text-warn' : 'text-crit'
            : 'text-slate-600'
          return (
            <li key={key} className="flex gap-2.5">
              <Icon size={17} className={`mt-0.5 shrink-0 ${color} ${pending && running ? 'animate-spin' : ''}`} />
              <div className="min-w-0">
                <p className={`text-sm ${pending ? 'text-slate-600' : 'text-slate-200'}`}>
                  {STEP_LABEL[key]}
                  {s && s.status !== 'OK' && <span className={`ml-2 text-[10px] font-bold uppercase ${color}`}>{s.status}</span>}
                </p>
                {s && <p className="text-[11px] leading-relaxed text-slate-500">{s.detail}</p>}
              </div>
            </li>
          )
        })}
      </ul>

      {outcome && (
        <div className={`rounded-lg border p-3 ${
          outcome === 'SUCCESS' ? 'border-safe/25 bg-safe/[0.06]' : outcome === 'PARTIAL' ? 'border-warn/30 bg-warn/[0.07]' : 'border-crit/30 bg-crit/[0.07]'
        }`}>
          <div className="flex flex-wrap items-center gap-2">
            {outcome === 'SUCCESS' ? <VerifyBadge verified /> : <VerifyBadge verified={false} />}
            <span className="chip bg-white/[0.05] text-slate-300 ring-1 ring-inset ring-white/10">
              {outcome === 'PARTIAL' ? 'Partial recovery' : outcome === 'FAILED' ? 'Recovery failed' : 'Fully recovered'}
              {attempt ? ` · attempt ${attempt}` : ''}
            </span>
            {outcome !== 'SUCCESS' && onRetry && (
              <button className="btn-safe ml-auto !py-1.5 text-xs" onClick={onRetry} disabled={retrying}>
                {retrying ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />} Retry recovery
              </button>
            )}
          </div>
          {verification && (
            <>
              <p className="mt-2 text-xs leading-relaxed text-slate-400">{verification.summary}</p>
              <ul className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2">
                {verification.checks.map((c) => (
                  <li key={c.resource} className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="truncate font-mono text-slate-500">{c.resource}</span>
                    <span className={c.passed ? 'text-safe' : 'text-crit'}>
                      {c.passed ? 'PASS' : c.state_ok ? 'FAIL (integrity)' : `FAIL (${c.observed})`}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {residual.length > 0 && (
            <div className="mt-2 border-t border-white/[0.08] pt-2">
              <p className="label">Residual risk (a rollback cannot fix this)</p>
              {residual.map((r) => (
                <p key={r} className="mt-1 text-[11px] leading-relaxed text-warn">{r}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
