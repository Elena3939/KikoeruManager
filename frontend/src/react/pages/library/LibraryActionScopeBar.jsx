import { Captions, FilterX, ListTodo, UploadCloud } from 'lucide-react'
import { Button, Card } from '../../components/Primitives'

export function LibraryActionScopeBar({
  scope,
  selectedCount,
  subtitleCount,
  filterDeleteCount,
  uploadCount,
  canSubtitle,
  canFilterDelete,
  canUpload,
  onScopeChange,
  onSubtitle,
  onFilterDelete,
  onOpenSubtitleTasks,
  onUpload
}) {
  if (selectedCount > 0) return null
  return (
    <Card className="library-action-scope-bar">
      <div className="lib-scope-switch" role="tablist" aria-label="工具栏作用范围">
        <button
          type="button"
          className={scope === 'page' ? 'is-active' : ''}
          aria-pressed={scope === 'page'}
          onClick={() => onScopeChange('page')}
        >
          当前页
        </button>
        <button
          type="button"
          className={scope === 'all' ? 'is-active' : ''}
          aria-pressed={scope === 'all'}
          onClick={() => onScopeChange('all')}
        >
          当前目录
        </button>
      </div>
      <div className="km-row-actions">
        <Button size="sm" disabled={!canSubtitle} onClick={onSubtitle}>
          <Captions size={15} />
          {scope === 'page' ? '当前页抓字幕' : '当前目录抓字幕'}
          {subtitleCount ? <em className="library-button-badge">{subtitleCount}</em> : null}
        </Button>
        <Button size="sm" disabled={!canFilterDelete} onClick={onFilterDelete}>
          <FilterX size={15} />
          {scope === 'page' ? '当前页删过滤' : '删除过滤文件'}
          {filterDeleteCount ? <em className="library-button-badge">{filterDeleteCount}</em> : null}
        </Button>
        <Button size="sm" onClick={onOpenSubtitleTasks}>
          <ListTodo size={15} />字幕任务面板
        </Button>
        <Button size="sm" disabled={!canUpload || !uploadCount} onClick={onUpload}>
          <UploadCloud size={15} />上传到服务器
          {uploadCount ? <em className="library-button-badge">{uploadCount}</em> : null}
        </Button>
      </div>
    </Card>
  )
}
