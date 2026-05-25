import { useEffect, useState } from 'react'
import { Pause, Play, RefreshCcw, RotateCcw } from 'lucide-react'
import { backupApi } from '../../api'
import { Button, Card, PageHeader } from '../components/Primitives'
import { formatDateTime } from '../utils/format'

export function LibraryBackupPage() {
  const [status, setStatus] = useState(null)
  const [checkpoint, setCheckpoint] = useState(null)
  const [history, setHistory] = useState([])

  async function refresh() {
    const [statusData, checkpointData, historyData] = await Promise.all([
      backupApi.status().catch(() => null),
      backupApi.checkpoint().catch(() => null),
      backupApi.history().catch(() => [])
    ])
    setStatus(statusData)
    setCheckpoint(checkpointData)
    setHistory(Array.isArray(historyData) ? historyData : historyData?.items || [])
  }

  useEffect(() => {
    refresh()
  }, [])

  async function run(action) {
    if (action === 'start') await backupApi.start()
    if (action === 'cancel') await backupApi.cancel()
    if (action === 'resume') await backupApi.resume()
    await refresh()
  }

  return (
    <div className="km-page">
      <PageHeader
        eyebrow="库存维护"
        title="库存打包"
        description="管理库存打包任务、断点和历史。"
        actions={<Button variant="primary" onClick={refresh}><RefreshCcw size={16} />刷新</Button>}
      />
      <div className="km-action-grid">
        <Button variant="primary" onClick={() => run('start')}><Play size={16} />开始打包</Button>
        <Button onClick={() => run('resume')}><RotateCcw size={16} />恢复</Button>
        <Button variant="danger" onClick={() => run('cancel')}><Pause size={16} />取消</Button>
      </div>
      <div className="km-two-col">
        <Card>
          <h2>当前状态</h2>
          <pre className="km-json">{JSON.stringify(status || {}, null, 2)}</pre>
        </Card>
        <Card>
          <h2>断点</h2>
          <pre className="km-json">{JSON.stringify(checkpoint || {}, null, 2)}</pre>
        </Card>
      </div>
      <Card>
        <h2>历史</h2>
        <div className="km-list">
          {history.map((item, index) => <div key={item.id || index}><strong>{item.name || item.status || '记录'}</strong><span>{formatDateTime(item.created_at || item.updated_at)}</span></div>)}
          {!history.length ? <span className="km-muted">暂无历史</span> : null}
        </div>
      </Card>
    </div>
  )
}
