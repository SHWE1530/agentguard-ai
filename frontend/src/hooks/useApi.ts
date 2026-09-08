import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../services/api'

interface State<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
}

/**
 * Fetch-on-mount with a manual reload, and friendly error text instead of
 * a thrown stack trace.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): State<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetcher()
      .then((d) => {
        if (cancelled) return
        setData(d)
        setError(null)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof ApiError ? e.message : 'Something went wrong loading this view.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, error, loading, reload }
}
