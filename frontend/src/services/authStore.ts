/** Holds the signed-in session for the API client. sessionStorage: cleared when the tab closes. */
export interface Session {
  token: string
  user: string
  role: string
}

const KEY = 'sentinel.session'
const listeners = new Set<() => void>()

function read(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

let current: Session | null = read()

export const authStore = {
  get: () => current,
  token: () => current?.token ?? null,
  set(s: Session) {
    current = s
    try { sessionStorage.setItem(KEY, JSON.stringify(s)) } catch { /* private mode: memory only */ }
  },
  clear() {
    current = null
    try { sessionStorage.removeItem(KEY) } catch { /* ignore */ }
  },
  /** Called by the API client on any 401. Returns an unsubscribe function. */
  onUnauthorized(fn: () => void) {
    listeners.add(fn)
    return () => { listeners.delete(fn) }
  },
  notifyUnauthorized() {
    authStore.clear()
    listeners.forEach((fn) => fn())
  },
}
