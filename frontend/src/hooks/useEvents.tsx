import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ReactNode,
} from 'react'
import { wsUrl } from '../services/api'
import { useAuth } from './useAuth'
import type { LiveEvent } from '../types'

type Status = 'connecting' | 'open' | 'closed'
type Handler = (e: LiveEvent) => void

interface EventsContext {
  status: Status
  events: LiveEvent[]
  /** Subscribe to the live stream. Returns an unsubscribe function. */
  subscribe: (fn: Handler) => () => void
}

const Ctx = createContext<EventsContext>({
  status: 'closed',
  events: [],
  subscribe: () => () => {},
})

const MAX_EVENTS = 300

/**
 * One WebSocket for the whole app, with automatic reconnect. Components
 * subscribe rather than opening their own sockets.
 */
export function EventsProvider({ children }: { children: ReactNode }) {
  const { token, authorised } = useAuth()
  const [status, setStatus] = useState<Status>('connecting')
  const [events, setEvents] = useState<LiveEvent[]>([])
  const handlers = useRef(new Set<Handler>())
  const socket = useRef<WebSocket | null>(null)
  const retry = useRef<number | null>(null)
  const attempts = useRef(0)

  const subscribe = useCallback((fn: Handler) => {
    handlers.current.add(fn)
    return () => {
      handlers.current.delete(fn)
    }
  }, [])

  useEffect(() => {
    let disposed = false

    const connect = () => {
      if (disposed) return
      setStatus('connecting')
      let ws: WebSocket
      try {
        ws = new WebSocket(wsUrl())
      } catch {
        schedule()
        return
      }
      socket.current = ws

      ws.onopen = () => {
        attempts.current = 0
        setStatus('open')
      }

      ws.onmessage = (msg) => {
        let event: LiveEvent
        try {
          event = JSON.parse(msg.data)
        } catch {
          return
        }
        if (event.type === 'connected') {
          const history: LiveEvent[] = event.data?.history ?? []
          if (history.length) setEvents((prev) => [...prev, ...history].slice(-MAX_EVENTS))
          return
        }
        setEvents((prev) => [...prev, event].slice(-MAX_EVENTS))
        handlers.current.forEach((fn) => {
          try {
            fn(event)
          } catch {
            /* a broken subscriber must not kill the stream */
          }
        })
      }

      ws.onclose = () => {
        setStatus('closed')
        schedule()
      }
      ws.onerror = () => ws.close()
    }

    const schedule = () => {
      if (disposed || retry.current !== null) return
      const delay = Math.min(1000 * 2 ** attempts.current, 10000)
      attempts.current += 1
      retry.current = window.setTimeout(() => {
        retry.current = null
        connect()
      }, delay)
    }

    if (authorised) connect()
    return () => {
      disposed = true
      if (retry.current !== null) window.clearTimeout(retry.current)
      socket.current?.close()
    }
  }, [token, authorised])

  const value = useMemo(() => ({ status, events, subscribe }), [status, events, subscribe])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useEvents = () => useContext(Ctx)

/** Run `fn` for every live event of the given types. */
export function useEventListener(types: string[], fn: Handler) {
  const { subscribe } = useEvents()
  const ref = useRef(fn)
  ref.current = fn
  const key = types.join(',')
  useEffect(
    () =>
      subscribe((e) => {
        if (types.includes(e.type)) ref.current(e)
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subscribe, key],
  )
}
