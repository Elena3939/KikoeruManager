import { useMemo, useState } from 'react'
import { Captions, Play, RefreshCcw, RotateCcw, SearchCheck, Trash2, XCircle } from 'lucide-react'
import { Button, Modal } from '../../components/Primitives'
import { formatDateTime } from '../../utils/format'
import { LibrarySubtitleInspectorWorkbench } from './LibrarySubtitleInspectorWorkbench'

export function LibrarySubtitleTaskPanel({
  visible,
  status,
  refreshing,
  fallbackLibraryId,
  onClose,
  onRefresh,
  onRerun,
  onCancel,
  onClear
}) {
  const tasks = useMemo(() => Array.isArray(status?.tasks) ? status.tasks : [], [status])
  const [inspectingTask, setInspectingTask] = useState(null)
  if (!visible) return null

  return (
    <Modal
      title="字幕任务面板"
      width={1120}
      onClose={onClose}
      footer={
        <>
          <Button loading={refreshing} onClick={onRefresh}><RefreshCcw size={15} />刷新</Button>
          <Button onClick={onClose}>关闭</Button>
        </>
      }
    >
      <div className="library-subtitle-panel">
        <div className="library-subtitle-summary">
          <span>总计 <b>{status?.total_tasks || tasks.length}</b></span>
          <span>处理中 <b>{status?.processing || 0}</b></span>
          <span>等待 <b>{status?.pending || 0}</b></span>
          <span>完成 <b>{status?.completed || 0}</b></span>
          <span>失败 <b>{status?.failed || 0}</b></span>
        </div>
        {!tasks.length ? <div className="km-empty"><Captions size={34} /><strong>暂无 RJ 字幕任务</strong></div> : null}
        <div className="library-subtitle-task-list">
          {tasks.map(task => (
            <article key={task.id} className={`library-subtitle-task is-${task.status || 'unknown'}`}>
              <header>
                <div>
                  <strong>{task.rjcode || basename(task.folder_path || task.source_path) || task.id}</strong>
                  <span>{task.folder_name || task.source_label || task.folder_path || task.source_path || '-'}</span>
                </div>
                <em>{statusLabel(task.status)}</em>
              </header>
              <div className="library-subtitle-task-progress">
                <span style={{ width: `${clampPercent(task.progress)}%` }} />
              </div>
              <div className="library-subtitle-task-meta">
                <span>{clampPercent(task.progress)}%</span>
                {task.current_step ? <span>{task.current_step}</span> : null}
                {task.created_at ? <span>{formatDateTime(task.created_at)}</span> : null}
                {task.subtitle_dir ? <span>{task.subtitle_dir}</span> : null}
              </div>
              {task.error_message || task.message ? <p>{task.error_message || task.message}</p> : null}
              <div className="km-row-actions">
                {['failed', 'waiting_manual', 'waiting_retry', 'completed'].includes(String(task.status || '')) ? (
                  <Button size="xs" onClick={() => onRerun?.(task.id)}><RotateCcw size={13} />重新执行</Button>
                ) : null}
                {canInspectTask(task) ? (
                  <Button size="xs" onClick={() => setInspectingTask(task)}><SearchCheck size={13} />检查配对</Button>
                ) : null}
                {['pending', 'processing', 'paused'].includes(String(task.status || '')) ? (
                  <Button size="xs" variant="danger" onClick={() => onCancel?.(task.id)}><XCircle size={13} />取消</Button>
                ) : null}
                {String(task.status || '') === 'paused' ? (
                  <Button size="xs" onClick={() => onRerun?.(task.id)}><Play size={13} />恢复执行</Button>
                ) : null}
                <Button size="xs" onClick={() => onClear?.(task.id)}><Trash2 size={13} />清理</Button>
              </div>
            </article>
          ))}
        </div>
      </div>
      <LibrarySubtitleInspectorWorkbench
        visible={Boolean(inspectingTask)}
        task={inspectingTask}
        fallbackLibraryId={fallbackLibraryId}
        onClose={() => setInspectingTask(null)}
        onTaskMutated={onRefresh}
      />
    </Modal>
  )
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0))))
}

function basename(value) {
  const normalized = String(value || '').replace(/\\/g, '/').replace(/\/+$/, '')
  return normalized.split('/').filter(Boolean).pop() || ''
}

function statusLabel(status) {
  const map = {
    pending: '等待中',
    processing: '处理中',
    paused: '已暂停',
    waiting_manual: '等待人工',
    waiting_retry: '等待重试',
    completed: '已完成',
    failed: '失败',
    canceled: '已取消',
    cancelled: '已取消'
  }
  return map[String(status || '')] || status || '未知'
}

function canInspectTask(task) {
  if (!task?.subtitle_dir) return false
  const status = String(task.status || '')
  if (status === 'processing' || status === 'pending') return false
  return Boolean(task.folder_path || task.source_path)
}
