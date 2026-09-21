import { useMemo } from 'react'
import type { Decision, GraphData } from '../types'

const COLS = ['agent', 'task', 'action', 'tool', 'resource', 'permission'] as const
const COL_LABEL: Record<string, string> = {
  agent: 'Agent', task: 'Task', action: 'Actions', tool: 'Tools', resource: 'Resources', permission: 'Permissions',
}
const DECISION_COLOR: Record<Decision, string> = {
  ALLOW: '#16a34a', MONITOR: '#ca8a04', REQUIRE_APPROVAL: '#7c3aed', BLOCK: '#ea580c', TERMINATE: '#dc2626',
}
const W = 158
const NODE_W = 132
const NODE_H = 28
const GAP = 44

/**
 * Behaviour graph: Agent -> Task -> Action -> Tool -> Resource -> Permission.
 * Built from the recorded session; suspicious paths (blocked, held, or part of a
 * matched attack chain) are red, and the temporal action sequence is dashed.
 */
export function BehaviorGraph({ data }: { data: GraphData }) {
  const layout = useMemo(() => {
    const byCol: Record<string, GraphData['nodes']> = {}
    COLS.forEach((c) => (byCol[c] = []))
    data.nodes.forEach((n) => byCol[n.kind]?.push(n))
    byCol.action.sort((a, b) => (a.step ?? 0) - (b.step ?? 0))
    const rows = Math.max(...COLS.map((c) => byCol[c].length), 1)
    const pos = new Map<string, { x: number; y: number }>()
    COLS.forEach((c, ci) => {
      const list = byCol[c]
      const total = (rows - 1) * GAP
      const off = (total - (list.length - 1) * GAP) / 2
      list.forEach((n, i) => pos.set(n.id, { x: 12 + ci * W, y: 34 + off + i * GAP }))
    })
    return { pos, height: 34 + rows * GAP + 8, width: 12 + COLS.length * W }
  }, [data])

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${layout.width} ${layout.height}`} className="min-w-[760px] w-full" role="img"
           aria-label="Behaviour graph of the agent session">
        {COLS.map((c, ci) => (
          <text key={c} x={12 + ci * W + NODE_W / 2} y={16} textAnchor="middle" fill="#64748b" fontSize="10" fontWeight={600}
                style={{ letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            {COL_LABEL[c]}
          </text>
        ))}
        {data.edges.map((e) => {
          const a = layout.pos.get(e.source)
          const b = layout.pos.get(e.target)
          if (!a || !b) return null
          const seq = e.kind === 'sequence'
          const x1 = seq ? a.x + NODE_W / 2 : a.x + NODE_W
          const y1 = a.y + NODE_H / 2 + (seq ? NODE_H / 2 : 0)
          const x2 = seq ? b.x + NODE_W / 2 : b.x
          const y2 = b.y + NODE_H / 2 - (seq ? NODE_H / 2 : 0)
          const c = seq ? 0 : (x2 - x1) / 2
          const d = seq
            ? `M ${x1 + 46} ${y1 - NODE_H / 2} C ${x1 + 70} ${y1}, ${x2 + 70} ${y2}, ${x2 + 46} ${y2 + NODE_H / 2}`
            : `M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`
          return (
            <path key={e.id} d={d} fill="none"
                  stroke={e.suspicious ? '#dc2626' : '#cbd5e1'} strokeWidth={e.suspicious ? 2 : 1}
                  strokeOpacity={e.suspicious ? 0.85 : 0.7} strokeDasharray={seq ? '3 3' : undefined} />
          )
        })}
        {data.nodes.map((n) => {
          const p = layout.pos.get(n.id)
          if (!p) return null
          const isAction = n.kind === 'action'
          const stroke = n.suspicious ? '#dc2626' : isAction && n.decision ? DECISION_COLOR[n.decision] : '#cbd5e1'
          const fill = n.suspicious ? 'rgba(220,38,38,0.08)' : '#ffffff'
          return (
            <g key={n.id} transform={`translate(${p.x} ${p.y})`}>
              <title>
                {n.label}
                {isAction ? ` · ${n.decision} · risk ${n.risk} · ${n.executed ? 'executed' : 'not executed'}` : ''}
              </title>
              <rect width={NODE_W} height={NODE_H} rx={6} fill={fill} stroke={stroke} strokeWidth={n.suspicious ? 1.6 : 1} />
              {isAction && n.step !== undefined && (
                <text x={7} y={18} fill="#64748b" fontSize="9" fontFamily="monospace">{n.step + 1}</text>
              )}
              <text x={isAction ? 20 : 8} y={18} fill={n.suspicious ? '#b91c1c' : '#334155'} fontSize="10" fontFamily="monospace">
                {n.label.length > (isAction ? 17 : 19) ? n.label.slice(0, isAction ? 16 : 18) + '…' : n.label}
              </text>
            </g>
          )
        })}
      </svg>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-crit align-middle" />suspicious path</span>
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-slate-600 align-middle" />normal path</span>
        <span>dashed = order the agent attempted its actions</span>
      </p>
    </div>
  )
}
