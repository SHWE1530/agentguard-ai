import { Eye, EyeOff, Loader2, LockKeyhole, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function Login() {
  const { ready, config, authorised, login } = useAuth()
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string } }
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (ready && authorised) return <Navigate to={loc.state?.from ?? '/app/judge'} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
      nav(loc.state?.from ?? '/app/judge', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="grid h-12 w-12 place-items-center rounded-xl bg-gradient-to-br from-beam to-ai text-ink-950 shadow-md shadow-slate-900/10">
            <ShieldCheck size={26} />
          </span>
          <h1 className="mt-4 text-2xl font-extrabold tracking-tight text-white">Agent Sentinel</h1>
          <p className="mt-1 text-sm text-slate-500">Safety layer for autonomous AI agents</p>
        </div>

        <form onSubmit={submit} className="card card-pad space-y-4" aria-label="Sign in">
          <div>
            <label htmlFor="user" className="label">Username</label>
            <input id="user" className="input mt-1" autoComplete="username" autoFocus value={username}
                   onChange={(e) => setUsername(e.target.value)} maxLength={64} required />
          </div>
          <div>
            <label htmlFor="pw" className="label">Password</label>
            <div className="relative mt-1">
              <input id="pw" className="input pr-10" type={show ? 'text' : 'password'} autoComplete="current-password"
                     value={password} onChange={(e) => setPassword(e.target.value)} maxLength={256} required />
              <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide password' : 'Show password'}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                {show ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {error && (
            <p role="alert" className="rounded-lg border border-crit/25 bg-crit/[0.07] px-3 py-2 text-sm text-crit">{error}</p>
          )}

          <button className="btn-primary w-full py-2.5" disabled={busy || !ready}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <LockKeyhole size={16} />} Sign in
          </button>

          {config?.demo_accounts && (
            <div className="rounded-lg border border-white/[0.09] bg-ink-850 p-3">
              <p className="label">Demo accounts</p>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                Built-in demo users, active because <code className="font-mono">SENTINEL_USERS</code> is not set. Click to fill.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {config.demo_hint.map((d) => (
                  <button key={d.user} type="button" onClick={() => { setUsername(d.user); setPassword(d.password); setError(null) }}
                          className="rounded-md border border-white/[0.14] bg-ink-900 px-2.5 py-1.5 text-left text-xs hover:bg-ink-800">
                    <span className="block font-mono font-semibold text-slate-200">{d.user}</span>
                    <span className="block text-[10px] text-slate-500">{d.role === 'operator' ? 'operator · can act' : 'viewer · read-only'}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </form>

        <p className="mt-4 text-center text-[11px] leading-relaxed text-slate-600">
          Controlled simulation. Every agent action is sandboxed; no real system is ever affected.
        </p>
      </div>
    </div>
  )
}
