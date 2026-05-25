import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { securityGateApi } from '../../api'
import { Button, Card, Field, PageHeader, TextInput } from '../components/Primitives'

export function VerifyGatePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function verify() {
    setLoading(true)
    setError('')
    try {
      await securityGateApi.verify({ code, remember })
      navigate(params.get('next') || '/', { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail || err.message || '验证失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="km-gate-page">
      <Card className="km-gate-card">
        <PageHeader eyebrow="安全验证" title="输入验证码" description="当前访问需要通过安全验证。" />
        <Field label="验证码">
          <TextInput value={code} onChange={event => setCode(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') verify() }} autoFocus />
        </Field>
        <label className="km-check"><input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)} />记住此设备</label>
        {error ? <div className="km-error">{error}</div> : null}
        <Button variant="primary" loading={loading} onClick={verify}><ShieldCheck size={16} />验证</Button>
      </Card>
    </div>
  )
}
