import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authStore } from '../services/authStore'

interface AuthConfig {
  enabled: boolean
  demo_accounts: boolean
  demo_hint: { user: string; password: string; role: string }[]
}

interface AuthState {
  ready: boolean
  config: AuthConfig | null
  user: string | null
  role: string | null
  token: string | null
  /** true when the app may be used (auth disabled, or signed in) */
  authorised: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const Ctx = createContext<AuthState>({
  ready: false, config: null, user: null, role: null, token: null, authorised: false,
  login: async () => {}, logout: () => {},
})

const BASE = import.meta.env.VITE_API_BASE ?? ''

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [session, setSession] = useState(authStore.get())
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch(`${BASE}/api/auth/config`)
      .then((r) => r.json())
      .then((c: AuthConfig) => !cancelled && setConfig(c))
      // backend unreachable: fail closed only if we already held a session; the pages show their own errors
      .catch(() => !cancelled && setConfig({ enabled: false, demo_accounts: false, demo_hint: [] }))
      .finally(() => !cancelled && setReady(true))
    return () => { cancelled = true }
  }, [])

  // any 401 from the API signs the user out (expired or invalid token)
  useEffect(() => authStore.onUnauthorized(() => setSession(null)), [])

  const login = useCallback(async (username: string, password: string) => {
    let res: Response
    try {
      res = await fetch(`${BASE}/api/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }),
      })
    } catch {
      throw new Error('Cannot reach the Agent Sentinel backend. Is it running on port 8000?')
    }
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail ?? 'Sign-in failed.')
    const s = { token: body.token as string, user: body.user as string, role: body.role as string }
    authStore.set(s)
    setSession(s)
  }, [])

  const logout = useCallback(() => { authStore.clear(); setSession(null) }, [])

  const value = useMemo<AuthState>(() => ({
    ready, config, user: session?.user ?? null, role: session?.role ?? null, token: session?.token ?? null,
    authorised: Boolean(config && (!config.enabled || session)), login, logout,
  }), [ready, config, session, login, logout])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)
