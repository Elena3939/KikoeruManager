import { useEffect, useMemo, useState } from 'react'
import { FolderDown, Play, RefreshCcw, Trash2 } from 'lucide-react'
import { subtitleImportApi } from '../../api'
import { Button, Card, Field, PageHeader, TextInput } from '../components/Primitives'
import { DataTable } from '../components/DataTable'
import { showSystemAlert, showSystemConfirm } from '../stores/systemPromptStore'
import { normalizeListPayload } from '../utils/format'

export function SubtitleImportPage() {
  const [pending, setPending] = useState([])
  const [archivePath, setArchivePath] = useState('')
  const [folderPath, setFolderPath] = useState('')
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      setPending(normalizeListPayload(await subtitleImportApi.listPending()))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function previewArchive() {
    if (!archivePath.trim()) return
    setPreview(await subtitleImportApi.previewArchive(archivePath.trim()))
  }

  async function importArchive() {
    if (!archivePath.trim()) return
    const result = await subtitleImportApi.importArchive(archivePath.trim())
    setPreview(result)
    await showSystemAlert({ title: '字幕压缩包导入已完成/进入工作台', tone: 'success' })
    await refresh()
  }

  async function previewFolder() {
    if (!folderPath.trim()) return
    setPreview(await subtitleImportApi.previewFolder(folderPath.trim()))
  }

  async function importFolder() {
    if (!folderPath.trim()) return
    const result = await subtitleImportApi.importFolder(folderPath.trim())
    setPreview(result)
    await showSystemAlert({ title: '字幕目录导入已完成/进入工作台', tone: 'success' })
    await refresh()
  }

  async function executePending(item) {
    await subtitleImportApi.executePending(item.id || item.record_id)
    await refresh()
  }

  async function clearPending(item = null) {
    await showSystemConfirm({ title: '清理待处理字幕记录', tone: 'warning' })
    await subtitleImportApi.clearPending(item ? { recordIds: [item.id || item.record_id] } : { clearAll: true })
    await refresh()
  }

  const columns = useMemo(() => [
    { header: '来源', accessorFn: row => row.archive_path || row.folder_path || row.source_path || row.id, cell: info => <strong>{info.getValue()}</strong> },
    { header: 'RJ', accessorFn: row => row.rjcode || row.source_rjcode || '-' },
    { header: '状态', accessorFn: row => row.status || row.state || '-' },
    {
      header: '操作',
      cell: ({ row }) => (
        <div className="km-row-actions">
          <Button size="xs" onClick={() => executePending(row.original)}><Play size={13} />执行</Button>
          <Button size="xs" variant="danger" onClick={() => clearPending(row.original)}><Trash2 size={13} />清理</Button>
        </div>
      )
    }
  ], [])

  return (
    <div className="km-page">
      <PageHeader
        eyebrow="RJ 字幕链路"
        title="字幕补配"
        description="处理待执行字幕导入、压缩包预览导入和整目录字幕导入。"
        actions={<><Button onClick={() => clearPending(null)}>清空待处理</Button><Button variant="primary" onClick={refresh}><RefreshCcw size={16} />刷新</Button></>}
      />
      <Card className="km-form-grid">
        <Field label="字幕压缩包"><TextInput value={archivePath} onChange={event => setArchivePath(event.target.value)} /></Field>
        <Button onClick={previewArchive}>预览压缩包</Button>
        <Button variant="primary" onClick={importArchive}><FolderDown size={15} />导入压缩包</Button>
        <Field label="字幕目录"><TextInput value={folderPath} onChange={event => setFolderPath(event.target.value)} /></Field>
        <Button onClick={previewFolder}>预览目录</Button>
        <Button variant="primary" onClick={importFolder}><FolderDown size={15} />导入目录</Button>
      </Card>
      {preview ? <Card><h2>预览/结果</h2><pre className="km-json">{JSON.stringify(preview, null, 2)}</pre></Card> : null}
      <DataTable data={pending} columns={columns} loading={loading} emptyTitle="暂无待处理字幕记录" rowKey={row => row.id || row.record_id || row.source_path} />
    </div>
  )
}
