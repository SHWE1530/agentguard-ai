import {
  ArrowRight, BrainCircuit, Eye, Gauge, Github, RotateCcw, ShieldCheck,
  Siren, Sparkles, UserCheck,
} from 'lucide-react'
import { Link } from 'react-router-dom'

const FLOW = [
  { label: 'Observe', icon: Eye, color: '#0284c7' },
  { label: 'Detect', icon: BrainCircuit, color: '#7c3aed' },
  { label: 'Assess', icon: Gauge, color: '#ca8a04' },
  { label: 'Intervene', icon: Siren, color: '#ea580c' },
  { label: 'Recover', icon: RotateCcw, color: '#16a34a' },
  { label: 'Verify', icon: ShieldCheck, color: '#16a34a' },
]

const BENEFITS = [
  {
    icon: BrainCircuit,
    title: 'Behavioural fingerprint, not just rules',
    body: 'Each agent gets a learned fingerprint (sequences, tools, resources, timing). An Isolation Forest scores every action against it, kill-chain and privilege-escalation detectors read the whole sequence, and drift shows when behaviour slowly moves away.',
    color: 'text-ai',
  },
  {
    icon: Gauge,
    title: 'Intent-aware, explainable enforcement',
    body: 'Actions are scored against the assigned task, not just a deny-list. Eight risk signals are fused, configurable policy rules decide ALLOW to TERMINATE, and every decision shows what would have happened if it were allowed.',
    color: 'text-high',
  },
  {
    icon: RotateCcw,
    title: 'Verified recovery, honest evaluation',
    body: 'Recovery is a step-by-step procedure that verifies state and integrity, and can fail or partly fail. The evaluation runs four detector configurations on held-out sessions and reports where each one breaks.',
    color: 'text-safe',
  },
]

export default function Landing() {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-gradient-to-br from-beam to-ai text-ink-950">
            <ShieldCheck size={19} />
          </span>
          <span className="text-sm font-bold tracking-tight">Agent Sentinel</span>
        </div>
        <Link to="/app" className="btn-ghost">
          Open Console <ArrowRight size={14} />
        </Link>
      </header>

      <main className="mx-auto max-w-6xl px-6 pb-20">
        {/* Hero */}
        <section className="py-14 text-center sm:py-20">
          <span className="chip mx-auto bg-ai/10 text-ai ring-1 ring-inset ring-ai/25">
            <Sparkles size={12} /> Controlled safety simulation
          </span>
          <h1 className="mx-auto mt-5 max-w-4xl text-4xl font-extrabold leading-[1.1] tracking-tight text-white sm:text-6xl">
            AI Agent Misbehavior
            <br />
            <span className="bg-gradient-to-r from-beam via-ai to-crit bg-clip-text text-transparent">
              Detection &amp; Recovery
            </span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-slate-400 sm:text-lg">
            Making autonomous AI systems safer, explainable, controllable, and recoverable.
          </p>
          <p className="mx-auto mt-3 max-w-2xl text-sm text-slate-500">
            The agent can act autonomously. This system makes sure those actions stay inside
            safe boundaries — and puts the world back when they don't.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link to="/app/judge" className="btn-primary px-6 py-2.5">
              Start Judge Mode <ArrowRight size={15} />
            </Link>
            <Link to="/app/lab" className="btn-ghost px-6 py-2.5">
              Launch Simulation
            </Link>
            <a href="#architecture" className="btn-ghost px-6 py-2.5">
              View Architecture
            </a>
          </div>
        </section>

        {/* Flow */}
        <section className="card card-pad">
          <div className="flex flex-wrap items-center justify-center gap-x-1 gap-y-4">
            {FLOW.map(({ label, icon: Icon, color }, i) => (
              <div key={label} className="flex items-center gap-1">
                <div className="flex w-24 flex-col items-center gap-2 sm:w-28">
                  <span
                    className="grid h-11 w-11 place-items-center rounded-xl ring-1 ring-inset"
                    style={{
                      color,
                      backgroundColor: `${color}18`,
                      borderColor: `${color}40`,
                      boxShadow: `inset 0 0 0 1px ${color}30`,
                    }}
                  >
                    <Icon size={19} />
                  </span>
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-300">
                    {label}
                  </span>
                </div>
                {i < FLOW.length - 1 && (
                  <ArrowRight size={14} className="hidden shrink-0 text-slate-700 sm:block" />
                )}
              </div>
            ))}
          </div>
        </section>

        {/* Benefits */}
        <section className="mt-6 grid gap-4 md:grid-cols-3">
          {BENEFITS.map(({ icon: Icon, title, body, color }) => (
            <div key={title} className="card card-pad">
              <Icon size={22} className={color} />
              <h3 className="mt-3 text-sm font-semibold text-slate-100">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-400">{body}</p>
            </div>
          ))}
        </section>

        {/* Architecture */}
        <section id="architecture" className="mt-14 scroll-mt-6">
          <h2 className="text-2xl font-bold tracking-tight text-white">Architecture</h2>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
            No single mechanism decides whether an agent is safe. The model reports how{' '}
            <em>unusual</em> an action is; policy reports whether it is <em>permitted</em>; the
            risk engine fuses both with context; humans gate the consequential middle ground;
            and recovery closes the loop when something gets through.
          </p>

          <div className="card mt-5 overflow-x-auto p-5">
            <pre className="min-w-[640px] font-mono text-[11px] leading-relaxed text-slate-400">
{`  ┌──────────────────────── React Dashboard ────────────────────────┐
  │  Simulation Lab · Agent Monitor · Incidents · Approvals · Audit  │
  └───────────────▲──────────────────────────────▲──────────────────┘
        REST /api │                              │ WebSocket /ws/events
  ┌───────────────┴──────────────────────────────┴──────────────────┐
  │                        FastAPI  ·  Agent Sentinel                │
  │                                                                  │
  │   Agent Simulator ──► attempted action ──► SAFETY PIPELINE       │
  │                                                │                 │
  │        ┌───────────────────────────────────────┤                 │
  │        ▼                                       ▼                 │
  │  Fingerprint · Intent · Sequence          Policy Engine           │
  │  (24 behavioural features)               (agent_policy.json)     │
  │        ▼                                       │                 │
  │  Isolation Forest ──► anomaly 0–1 ─────────────┤                 │
  │                                                ▼                 │
  │                                        Risk Engine (0–100)       │
  │                                                ▼                 │
  │                                     Explanation Engine           │
  │                                                ▼                 │
  │      ALLOW │ MONITOR │ REQUIRE_APPROVAL │ BLOCK │ BLOCK+STOP     │
  │                                                ▼                 │
  │        Incident ──► Recovery ──► State Verification              │
  │                                                ▼                 │
  │                       Audit Logger  (SQLite, append-only)        │
  └──────────────────────────────────────────────────────────────────┘`}
            </pre>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div className="card card-pad">
              <p className="label">Layered, not model-only</p>
              <ul className="mt-3 space-y-2 text-sm text-slate-400">
                <li className="flex gap-2">
                  <BrainCircuit size={15} className="mt-0.5 shrink-0 text-ai" />
                  ML behaviour detection — catches drift policy can't enumerate
                </li>
                <li className="flex gap-2">
                  <ShieldCheck size={15} className="mt-0.5 shrink-0 text-beam" />
                  Policy enforcement — hard rules the model cannot be talked out of
                </li>
                <li className="flex gap-2">
                  <Gauge size={15} className="mt-0.5 shrink-0 text-warn" />
                  Risk scoring — weights consequence, not just strangeness
                </li>
                <li className="flex gap-2">
                  <UserCheck size={15} className="mt-0.5 shrink-0 text-high" />
                  Human oversight — for legitimate but consequential actions
                </li>
                <li className="flex gap-2">
                  <RotateCcw size={15} className="mt-0.5 shrink-0 text-safe" />
                  Recovery + verification — because prevention is never perfect
                </li>
              </ul>
            </div>
            <div className="card card-pad">
              <p className="label">Safety boundary</p>
              <p className="mt-3 text-sm leading-relaxed text-slate-400">
                Every "dangerous" action in this project is simulated. <code className="rounded bg-ink-800 px-1 font-mono text-xs text-crit">DELETE_DATABASE</code>{' '}
                flips a string in a SQLite row from <code className="font-mono text-xs">HEALTHY</code>{' '}
                to <code className="font-mono text-xs">DELETED</code> — it never touches a real
                database, file, service or permission. No credentials, cloud accounts or
                production systems are required or used.
              </p>
              <p className="mt-3 text-xs text-slate-600">
                The behavioural dataset is synthetic and generated locally; it is labelled as
                such throughout the application and is not real-world telemetry. Agents are
                scripted simulators, not live LLMs.
              </p>
            </div>
          </div>
        </section>

        <footer className="mt-14 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-6 text-xs text-slate-600">
          <span className="flex items-center gap-1.5">
            <Github size={13} /> Agent Sentinel — hackathon prototype
          </span>
          <Link to="/app/lab" className="text-beam hover:underline">
            Start the demo →
          </Link>
        </footer>
      </main>
    </div>
  )
}
