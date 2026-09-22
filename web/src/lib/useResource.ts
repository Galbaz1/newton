import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../api/http'

export interface Resource<T> {
  data: T | null
  error: string | null
  loading: boolean
  /** Refetches without clearing current data, so lists do not flicker. */
  reload: () => Promise<void>
  setData: (value: T | null) => void
}

/**
 * Loads one server resource. Pass `null` as loader to mean "nothing selected";
 * `key` identifies the selection so stale responses are discarded.
 */
export function useResource<T>(
  key: string | null,
  loader: ((signal: AbortSignal) => Promise<T>) | null,
): Resource<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const loaderRef = useRef(loader)
  loaderRef.current = loader
  const activeKey = useRef<string | null>(null)

  const run = useCallback(async (forKey: string | null, signal: AbortSignal) => {
    const load = loaderRef.current
    if (!forKey || !load) return
    setLoading(true)
    try {
      const value = await load(signal)
      if (activeKey.current !== forKey || signal.aborted) return
      setData(value)
      setError(null)
    } catch (caught) {
      if (activeKey.current !== forKey || signal.aborted) return
      setError(errorMessage(caught))
    } finally {
      if (activeKey.current === forKey) setLoading(false)
    }
  }, [])

  useEffect(() => {
    activeKey.current = key
    setData(null)
    setError(null)
    setLoading(false)
    const controller = new AbortController()
    void run(key, controller.signal)
    return () => controller.abort()
  }, [key, run])

  const reload = useCallback(() => run(activeKey.current, new AbortController().signal), [run])
  // Selection effects run after render; old data must not seed the new selection meanwhile.
  const matchesKey = activeKey.current === key
  return {
    data: matchesKey ? data : null,
    error: matchesKey ? error : null,
    loading: matchesKey ? loading : Boolean(key && loader),
    reload,
    setData,
  }
}
