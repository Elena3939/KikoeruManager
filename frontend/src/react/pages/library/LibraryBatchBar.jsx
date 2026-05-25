import { Captions, FilterX, FolderInput, HardDrive, Trash2, UploadCloud, Wand2, X } from 'lucide-react'
import { Button, Card } from '../../components/Primitives'
import { canApiRenameRow, isDirectory } from './libraryUtils'

export function LibraryBatchBar({
  selectedRows,
  busy,
  onMove,
  onBatchSubtitle,
  onBatchApiRename,
  onFilterDelete,
  onComputeFolderSize,
  onUpload,
  onBatchDelete,
  onClear
}) {
  if (!selectedRows.length) return null

  const apiRenameCount = selectedRows.filter(canApiRenameRow).length
  const directoryCount = selectedRows.filter(isDirectory).length

  return (
    <Card className="library-batch-bar">
      <span>已选 <b>{selectedRows.length}</b> 项</span>
      <Button size="sm" onClick={onMove}><FolderInput size={15} />移动</Button>
      <Button size="sm" onClick={onBatchSubtitle} disabled={!directoryCount || busy}>
        <Captions size={15} />批量抓字幕
        {directoryCount ? <em className="library-button-badge">{directoryCount}</em> : null}
      </Button>
      <Button size="sm" onClick={onBatchApiRename} disabled={!apiRenameCount || busy}>
        <Wand2 size={15} />批量 API 命名
        {apiRenameCount ? <em className="library-button-badge">{apiRenameCount}</em> : null}
      </Button>
      <Button size="sm" onClick={onFilterDelete} disabled={!directoryCount || busy}>
        <FilterX size={15} />删过滤预审
      </Button>
      <Button size="sm" onClick={onComputeFolderSize} disabled={!directoryCount || busy}>
        <HardDrive size={15} />计算目录大小
      </Button>
      <Button size="sm" onClick={onUpload} disabled={busy}>
        <UploadCloud size={15} />上传到服务器
      </Button>
      <Button size="sm" variant="danger" loading={busy} onClick={onBatchDelete}><Trash2 size={15} />批量删除</Button>
      <Button size="sm" onClick={onClear}><X size={14} />清空</Button>
    </Card>
  )
}
