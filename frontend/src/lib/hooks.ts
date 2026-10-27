import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"

/** Load data, and optionally poll it while the tab is visible. `deps` reload it. */
export function useData<T>(load: () => Promise<T>, pollMs?: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const loadRef = useRef(load)
  loadRef.current = load

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setData(await loadRef.current())
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    if (!pollMs) return
    const id = setInterval(() => {
      if (document.visibilityState === "visible") refresh()
    }, pollMs)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, pollMs, ...deps])

  return { data, error, loading, refresh, setData }
}

/** Current time in seconds, ticking once a second. */
export function useNow(everyMs = 1000) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), everyMs)
    return () => clearInterval(id)
  }, [everyMs])
  return now
}

/** Width of an element, kept in sync with ResizeObserver. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches

/** Ease a number from its previous value to `target` (first load counts up from 0). */
export function useCountUp(target: number | null, ms = 700) {
  const [v, setV] = useState(target === null ? null : reduced() ? target : 0)
  const from = useRef(0)
  useEffect(() => {
    if (target === null) return setV(null)
    if (reduced()) return setV(target)
    const start = performance.now()
    const a = from.current
    let raf = 0
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms)
      const e = 1 - Math.pow(1 - k, 3)
      setV(a + (target - a) * e)
      if (k < 1) raf = requestAnimationFrame(step)
      else from.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return v
}
