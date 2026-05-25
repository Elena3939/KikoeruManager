import { useEffect, useMemo, useState } from 'react'
import { RefreshCcw, Search, Trash2 } from 'lucide-react'
import { logApi } from '../../api'
import { Button, Card, Field, PageHeader, TextInput } from '../components/Primitives'
import { DataTable } from '../components/DataTable'
import { showSystemConfirm } from '../stores/systemPromptStore'
import { normalizeListPayload } from '../utils/format'

export function LogsPage() {
  const [lines, setLines] = useState(300)
  const [keyword, setKeyword] = useState('')
  const [rows, setRows] = useState([])
  const [info, setInfo] = useState(null)
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      const [logData, infoData] = await Promise.all([logApi.get(lines), logApi.info().catch(() => null)])
      const list = Array.isArray(logData?.lines) ? logData.lines : normalizeListPayload(logData)
      setRows(list.map((line, index) => typeof line === 'string' ? { id: index, line } : { id: index, ...line }))
      setInfo(infoData)
    } finally {
      setLoading(false)
    }
  }

  async function search() {
    if (!keyword.trim()) return refresh()
    setLoading(true)
    try {
      const data = await logApi.search(keyword, [], lines)
      setRows(normalizeListPayload(data).map((item, index) => typeof item === 'string' ? { id: index, line: item } : { id: index, ...item }))
    } finally {
      setLoading(false)
    }
  }

  async function cleanup() {
    await showSystemConfirm({ title: '清理日志', message: '会按当前后端策略压缩/截断日志。', tone: 'warning' })
    await logApi.cleanup({ rotate: true })
    await refresh()
  }

  useEffect(() => {
    refresh()
  }, [])

  const columns = useMemo(() => [
    { header: '行', accessorFn: row => row.line || row.message || JSON.stringify(row), cell: info => <pre className="km-log-line">{info.getValue()}</pre> }
  ], [])

  return (
    <div className="km-page">
      <PageHeader
        eyebrow="诊断"
        title="日志"
        description="查看后端运行日志、搜索关键字并执行清理。"
        actions={<><Button onClick={cleanup}><Trash2 size={16} />清理</Button><Button variant="primary" onClick={refresh}><RefreshCcw size={16} />刷新</Button></>}
      />
      <Card className="km-toolbar-card">
        <Field label="行数"><TextInput type="number" value={lines} onChange={event => setLines(Number(event.target.value || 300))} /></Field>
        <Field label="搜索"><TextInput value={keyword} onChange={event => setKeyword(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') search() }} /></Field>
        <Button onClick={search}><Search size={15} />搜索</Button>
        <span className="km-muted">{info?.log_file || info?.path || ''}</span>
      </Card>
      <DataTable data={rows} columns={columns} loading={loading} emptyTitle="暂无日志" rowKey={row => row.id} />
    </div>
  )
}
