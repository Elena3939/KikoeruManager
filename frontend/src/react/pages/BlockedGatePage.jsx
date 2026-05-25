import { Ban } from 'lucide-react'
import { Card, PageHeader } from '../components/Primitives'

export function BlockedGatePage() {
  return (
    <div className="km-gate-page">
      <Card className="km-gate-card">
        <Ban size={40} />
        <PageHeader
          eyebrow="访问阻止"
          title="当前访问已被阻止"
          description="安全网关已拒绝当前请求，请在设置或后端安全日志中解除限制。"
        />
      </Card>
    </div>
  )
}
