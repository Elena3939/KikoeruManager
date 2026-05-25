import { useEffect, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { securityGateApi } from '../../api'
import { LoadingState } from './Primitives'

export function RequireGate({ children }) {
  const location = useLocation()
  const [state, setState] = useState({ loading: true, blocked: false, gateRequired: false })

  useEffect(() => {
    let cancelled = false
    async function check() {
      setState({ loading: true, blocked: false, gateRequired: false })
      try {
        const data = await securityGateApi.status()
        if (!cancelled) {
          setState({
            loading: false,
            blocked: Boolean(data?.blocked),
            gateRequired: Boolean(data?.enforced && !data?.authenticated)
          })
        }
      } catch (error) {
        const data = error.response?.data || {}
        if (!cancelled) {
          setState({
            loading: false,
            blocked: Boolean(data.blocked),
            gateRequired: Boolean(data.gate_required)
          })
        }
      }
    }
    check()
    return () => {
      cancelled = true
    }
  }, [location.pathname, location.search])

  if (state.loading) return <LoadingState label="正在确认访问状态..." />
  if (state.blocked) return <Navigate to="/blocked" replace />
  if (state.gateRequired) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`)
    return <Navigate to={`/verify?next=${next}`} replace />
  }
  return children
}
