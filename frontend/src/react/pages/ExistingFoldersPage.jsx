import { useEffect, useMemo, useState } from 'react'
import { Play, RefreshCcw, Search, Trash2 } from 'lucide-react'
import { existingFolderApi } from '../../api'
import { Button, Card, PageHeader } from '../components/Primitives'
import { DataTable } from '../components/DataTable'
import { showSystemConfirm, showSystemAlert } from '../stores/systemPromptStore'
import { formatDateTime, normalizeListPayload } from '../utils/format'

export function ExistingFoldersPage() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      setRows(normalizeListPayload(await existingFolderApi.list()))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function scan(forceRefresh = false) {
    await existingFolderApi.scan(true, forceRefresh)
    await showSystemAlert({ title: '扫描已启动', tone: 'success' })
    await refresh()
  }

  async function process(item) {
    await existingFolderApi.process([item.path || item.folder_path], true)
    await refresh()
  }

  async function remove(item) {
    await showSystemConfirm({ title: '删除已有文件夹记录', currentValue: item.path || item.folder_path, tone: 'danger' })
    await existingFolderApi.delete(item.path || item.folder_path)
    await refresh()
  }

  const columns = useMemo(() => [
    { header: '路径', accessorFn: row => row.path || row.folder_path, cell: info => <strong>{info.getValue()}</strong> },
    { header: 'RJ', accessorFn: row => row.rjcode || '-' },
    { header: '状态', accessorFn: row => row.status || row.state || '-' },
    { header: '时间', accessorFn: row => row.updated_at || row.created_at, cell: info => formatDateTime(info.getValue()) },
    {
      header: '操作',
      cell: ({ row }) => (
        <div className="km-row-actions">
          <Button size="xs" onClick={() => process(row.original)}><Play size={13} />入库</Button>
          <Button size="xs" variant="danger" onClick={() => remove(row.original)}><Trash2 size={13} />删除</Button>
        </div>
      )
    }
  ], [])

  return (
    <div className="km-page">
      <PageHeader
        eyebrow="预检工作台"
        title="已有文件夹"
        description="扫描输入目录中的已有作品文件夹，执行重复检查后再入库。"
        actions={<><Button onClick={() => scan(false)}><Search size={16} />扫描</Button><Button variant="primary" onClick={() => scan(true)}><RefreshCcw size={16} />强制刷新</Button></>}
      />
      <DataTable data={rows} columns={columns} loading={loading} emptyTitle="暂无已有文件夹" rowKey={row => row.id || row.path || row.folder_path} />
    </div>
  )
}
