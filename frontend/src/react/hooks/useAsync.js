import { useCallback, useEffect, useRef, useState } from 'react'

export function useAsyncTask(task, deps = [], options = {}) {
  const mountedRef = useRef(false)
  const [state, setState] = useState({
    data: options.initialData ?? null,
    error: null,
    loading: Boolean(options.immediate ?? true)
  })

  const run = useCallback(async (...args) => {
    setState(prev => ({ ...prev, loading: true, error: null }))
    try {
      const data = await task(...args)
      if (mountedRef.current) {
        setState({ data, error: null, loading: false })
      }
      return data
    } catch (error) {
      if (mountedRef.current) {
        setState(prev => ({ ...prev, error, loading: false }))
      }
      throw error
    }
  }, deps)

  useEffect(() => {
    mountedRef.current = true
    if (options.immediate !== false) {
      run()
    }
    return () => {
      mountedRef.current = false
    }
  }, [run, options.immediate])

  return { ...state, run, setState }
}

export function useInterval(callback, delay, enabled = true) {
  const callbackRef = useRef(callback)

  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  useEffect(() => {
    if (!enabled || !delay) return undefined
    const id = window.setInterval(() => callbackRef.current(), delay)
    return () => window.clearInterval(id)
  }, [delay, enabled])
}
