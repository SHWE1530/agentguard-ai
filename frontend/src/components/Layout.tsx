import {
  Activity, BarChart3, FlaskConical, Gauge, LayoutDashboard, Network, PlayCircle, ScrollText,
  LogOut, ShieldCheck, Siren, Sparkles, UserCheck, Wifi, WifiOff,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useEvents } from '../hooks/useEvents'

const NAV = [
  { to: '/app/judge', label: 'Judge Mode', icon: Sparkles, accent: true },
  { to: '/app', end: true, label: 'Dashboard', icon: LayoutDashboard },
  { to: '/app/lab', label: 'Simulation Lab', icon: FlaskConical },
  { to: '/app/monitor', label: 'Agent Monitor', icon: Activity },
  { to: '/app/incidents', label: 'Incident Center', icon: Siren },
  { to: '/app/replay', label: 'Incident Replay', icon: PlayCircle },
  { to: '/app/approvals', label: 'Human Approval', icon: UserCheck },
  { to: '/app/audit', label: 'Audit Trail', icon: ScrollText },
  { to: '/app/evaluation', label: 'Evaluation', icon: BarChart3 },
  { to: '/app/architecture', label: 'Architecture', icon: Network },
]

function ConnectionPill() {
  const { status } = useEvents()
  const map = {
    open: { text: 'Live', cls: 'text-safe bg-safe/10 ring-safe/25', Icon: Wifi },
    connecting: { text: 'Connecting', cls: 'text-warn bg-warn/10 ring-warn/25', Icon: Wifi },
    closed: { text: 'Offline', cls: 'text-crit bg-crit/10 ring-crit/25', Icon: WifiOff },
  }[status]
  return (
    <span className={`chip ring-1 ring-inset ${map.cls}`} title="WebSocket event stream">
      <map.Icon size={12} />
      {map.text}
    </span>
  )
}

export default function Layout() {
  const { user, role, config, logout } = useAuth()
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-white/[0.06] bg-ink-900/60 backdrop-blur lg:flex">
        <NavLink to="/" className="flex items-center gap-2.5 px-5 py-5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-beam to-ai text-ink-950">
            <ShieldCheck size={19} />
          </span>
          <span>
            <span className="block text-sm font-bold leading-tight text-slate-100">
              Agent Sentinel
            </span>
            <span className="block text-[10px] uppercase tracking-wider text-slate-500">
              Safety Layer
            </span>
          </span>
        </NavLink>

        <nav className="flex-1 space-y-1 px-3">
          {NAV.map(({ to, label, icon: Icon, end, accent }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-beam/10 text-beam ring-1 ring-inset ring-beam/20'
                    : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
                }`
              }
            >
              <Icon size={16} />
              {label}
              {accent && (
                <span className="ml-auto rounded bg-ai/20 px-1.5 py-0.5 text-[9px] font-bold uppercase text-ai">
                  Start here
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="m-3 rounded-lg border border-white/[0.06] bg-ink-850/70 p-3">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-400">
            <Gauge size={12} /> Controlled simulation
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-600">
            Every agent action is sandboxed. No real file, service, database or permission is
            ever modified.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-white/[0.06] bg-ink-950/85 px-4 py-3 backdrop-blur sm:px-6">
          <NavLink to="/" className="flex items-center gap-2 lg:hidden">
            <ShieldCheck size={18} className="text-beam" />
            <span className="text-sm font-bold">Agent Sentinel</span>
          </NavLink>
          <div className="ml-auto flex items-center gap-2">
            <ConnectionPill />
            {config?.enabled && user && (
              <>
                <span className="hidden items-center gap-2 rounded-lg border border-white/[0.09] bg-ink-850 px-2.5 py-1 text-xs sm:flex">
                  <span className="font-semibold text-slate-200">{user}</span>
                  <span className={`chip !px-1.5 !py-0 ring-1 ring-inset ${role === 'viewer' ? 'bg-warn/10 text-warn ring-warn/25' : 'bg-safe/10 text-safe ring-safe/25'}`}>{role}</span>
                </span>
                <button className="btn-ghost !px-2.5 !py-1.5 text-xs" onClick={logout} title="Sign out"><LogOut size={14} /> Sign out</button>
              </>
            )}
          </div>
        </header>

        <nav className="flex gap-1 overflow-x-auto border-b border-white/[0.06] px-3 py-2 lg:hidden">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium ${
                  isActive ? 'bg-beam/10 text-beam' : 'text-slate-400'
                }`
              }
            >
              <Icon size={13} />
              {label}
            </NavLink>
          ))}
        </nav>

        {role === 'viewer' && (
          <p className="border-b border-warn/25 bg-warn/[0.07] px-4 py-2 text-center text-xs text-warn">
            You are signed in read-only (viewer). Sign in as an operator to start runs, decide approvals or trigger recovery.
          </p>
        )}
        <main className="flex-1 px-4 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
