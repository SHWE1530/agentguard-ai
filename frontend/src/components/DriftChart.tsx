import {
  Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import type { AgentAction } from '../types'

const tip = {
  backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 12, color: '#0f172a',
}

/**
 * Behaviour-drift score per action against the agent's fingerprint, with the
 * agent's own threshold and its "normal" reference level.
 */
export function DriftChart({
  actions, threshold, reference, height = 170,
}: {
  actions: AgentAction[]
  threshold?: number
  reference?: number
  height?: number
}) {
  const ordered = [...actions].sort((a, b) => a.step_index - b.step_index)
  const data = ordered.map((a) => ({
    step: a.step_index + 1,
    action: a.action_type,
    drift: Math.round((a.risk_factors?.drift?.score ?? 0) * 100),
  }))
  const thr = threshold ?? ordered.at(-1)?.risk_factors?.drift_threshold ?? 0.3
  const current = data.at(-1)?.drift ?? 0
  const alert = current >= thr * 100
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-slate-500">
          Normal {reference !== undefined ? `${Math.round(reference * 100)}%` : '—'} · alert at {Math.round(thr * 100)}%
        </span>
        <span className={`font-mono font-semibold ${alert ? 'text-warn' : 'text-slate-300'}`}>
          now {current}% {alert && '⚠ drift detected'}
        </span>
      </div>
      {data.length < 3 ? (
        <p className="py-8 text-center text-xs text-slate-600">Drift needs a window of at least 3 actions.</p>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          <AreaChart data={data} margin={{ left: -18, right: 6, top: 6 }}>
            <defs>
              <linearGradient id="gDrift" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ea580c" stopOpacity={0.45} />
                <stop offset="100%" stopColor="#ea580c" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="rgba(15,23,42,0.08)" vertical={false} />
            <XAxis dataKey="step" stroke="#64748b" fontSize={10} tickLine={false} />
            <YAxis stroke="#64748b" fontSize={10} domain={[0, 100]} tickLine={false} axisLine={false} unit="%" />
            <Tooltip contentStyle={tip} formatter={(v: number) => `${v}%`} labelFormatter={(l, p) => `Step ${l} · ${p?.[0]?.payload?.action ?? ''}`} />
            <ReferenceLine y={thr * 100} stroke="#ca8a04" strokeDasharray="4 3" />
            {reference !== undefined && <ReferenceLine y={reference * 100} stroke="#16a34a" strokeDasharray="2 4" />}
            <Area type="monotone" dataKey="drift" name="Drift" stroke="#ea580c" strokeWidth={2} fill="url(#gDrift)" />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
