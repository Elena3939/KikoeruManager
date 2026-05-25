import { useMemo, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Download,
  FileText,
  Minimize2,
  PackageCheck,
  Pause,
  Play,
  RefreshCw,
  Search,
  Upload,
  X,
  XCircle,
  Zap
} from 'lucide-react'
import { Button, Modal, TextInput } from '../../components/Primitives'
import { cx, formatBytes } from '../../utils/format'
import {
  formatEtaSeconds,
  formatLogTime,
  formatSpeed,
  getDownloadEtaSeconds,
  getDownloadSpeedBytes,
  getTaskStatusLabel,
  getUploadSpeedBytes
} from './circleUtils'

export function TaskWorkbenchDialog({
  type = 'download',
  title,
  tasks,
  refreshing,
  retryingKeys,
  onRefresh,
  onBackground,
  onClose,
  onRetry,
  onRetryWaiting,
  onPause,
  onResume,
  onCancel,
  onReimport
}) {
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [expandedIds, setExpandedIds] = useState(() => new Set())
  const safeTasks = useMemo(() => normalizeTasks(tasks), [tasks])
  const retryingSet = useMemo(() => new Set((retryingKeys || []).map(String)), [retryingKeys])
  const tabs = useMemo(() => buildTabs(safeTasks), [safeTasks])
  const filteredTasks = useMemo(() => {
    let list = safeTasks
    if (filter !== 'all') list = list.filter(task => getTaskGroup(task) === filter)
    const keyword = query.trim().toLowerCase()
    if (keyword) {
      list = list.filter(task => [
        task.id,
        task.rjcode,
        task.work_title,
        task.source_label,
        getTaskDownloadRoot(task),
        getTaskFinalPath(task)
      ].map(item => String(item || '').toLowerCase()).join(' ').includes(keyword))
    }
    return list
  }, [safeTasks, filter, query])
  const isUpload = type === 'upload'
  const totalDownloadSpeed = safeTasks.reduce((sum, task) => sum + getDownloadSpeedBytes(task), 0)
  const totalUploadSpeed = safeTasks.reduce((sum, task) => sum + getUploadSpeedBytes(task), 0)

  function toggleExpanded(taskId) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(taskId)) next.delete(taskId)
      else next.add(taskId)
      return next
    })
  }

  return (
    <Modal
      title={title || (isUpload ? '上传工作台' : '下载工作台')}
      width={1160}
      onClose={onClose}
      footer={(
        <>
          <div className="circle-task-footer-metrics">
            <span><Download size={13} />下载 {formatSpeed(totalDownloadSpeed)}</span>
            <span><Upload size={13} />上传 {formatSpeed(totalUploadSpeed)}</span>
          </div>
          <Button onClick={onBackground}><Minimize2 size={14} />隐藏到后台</Button>
          <Button onClick={onClose}>关闭</Button>
        </>
      )}
    >
      <div className="circle-task-workbench">
        <header className="circle-task-tools">
          <div className="circle-task-tabs">
            {tabs.map(tab => (
              <button key={tab.value} type="button" className={cx(filter === tab.value && 'is-active')} onClick={() => setFilter(tab.value)}>
                {tab.label}<span>{tab.count}</span>
              </button>
            ))}
          </div>
          <div className="circle-task-search">
            <Search size={14} />
            <TextInput value={query} placeholder="搜索任务、RJ 或路径" onChange={event => setQuery(event.target.value)} />
          </div>
          <Button loading={refreshing} onClick={onRefresh}><RefreshCw size={14} />刷新</Button>
        </header>

        <div className="circle-task-list">
          {filteredTasks.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              type={type}
              expanded={expandedIds.has(task.id)}
              retrying={retryingSet.has(String(task.id))}
              onToggle={() => toggleExpanded(task.id)}
              onRetry={onRetry}
              onRetryWaiting={onRetryWaiting}
              onPause={onPause}
              onResume={onResume}
              onCancel={onCancel}
              onReimport={onReimport}
            />
          ))}
          {!filteredTasks.length ? (
            <div className="circle-task-empty">
              <Clock3 size={28} />
              <strong>暂无符合条件的任务</strong>
            </div>
          ) : null}
        </div>
      </div>
    </Modal>
  )
}

export function BackgroundTaskCard({ tone = 'primary', title, badge, tasks, type = 'download', stacked = false, onResume, onClose }) {
  const safeTasks = Array.isArray(tasks) ? tasks : []
  const processing = safeTasks.filter(task => String(task?.status || task?.display_status || '') === 'processing').length
  const failed = safeTasks.filter(task => ['failed', 'partial_failed'].includes(String(task?.status || task?.display_status || ''))).length
  const completed = safeTasks.filter(task => String(task?.status || task?.display_status || '') === 'completed').length
  const progress = safeTasks.length ? Math.round(safeTasks.reduce((sum, task) => sum + getTaskOverallPercent(task), 0) / safeTasks.length) : 0
  const Icon = type === 'upload' ? Upload : Download

  return (
    <aside className={cx('circle-background-task-card', tone, stacked && 'is-stacked')}>
      <div className="circle-background-task-head">
        <span><Icon size={15} /></span>
        <button type="button" title="关闭" onClick={onClose}><X size={14} /></button>
      </div>
      <strong>{title}</strong>
      <p>{badge} · 进行中 {processing} · 完成 {completed} · 异常 {failed}</p>
      <div className="circle-background-progress"><div style={{ width: `${progress}%` }} /></div>
      <Button size="xs" variant="primary" onClick={onResume}>打开工作台</Button>
    </aside>
  )
}

function TaskCard({
  task,
  type,
  expanded,
  retrying,
  onToggle,
  onRetry,
  onRetryWaiting,
  onPause,
  onResume,
  onCancel,
  onReimport
}) {
  const status = String(task?.display_status || task?.status || '')
  const tone = getTaskTone(task)
  const isUpload = type === 'upload'
  const fileRows = getUnifiedFileRows(task)
  const progress = getTaskOverallPercent(task)
  const downloadSpeed = getDownloadSpeedBytes(task)
  const uploadSpeed = getUploadSpeedBytes(task)
  const eta = getDownloadEtaSeconds(task)
  const canReimport = !isUpload && Boolean(getTaskDownloadRoot(task)) && ['completed', 'failed', 'partial_failed'].includes(status)

  return (
    <article className={cx('circle-task-card', tone, expanded && 'is-expanded')} onClick={onToggle}>
      <div className="circle-task-summary">
        <div className="circle-task-icon">{getTaskIcon(task, isUpload)}</div>
        <div className="circle-task-main">
          <div className="circle-task-title-row">
            <h3>{task.work_title || task.source_label || task.rjcode || task.id}</h3>
            <span className={cx('circle-task-status', tone)}>{getTaskStatusLabel(task)}</span>
          </div>
          <div className="circle-task-meta">
            <span>{task.rjcode || task.task_metadata?.rjcode || '未知 RJ'}</span>
            <span>{getPrimaryFileProgressLabel(task)}</span>
            {downloadSpeed > 0 ? <span><Zap size={12} />下载 {formatSpeed(downloadSpeed)}</span> : null}
            {uploadSpeed > 0 ? <span><Zap size={12} />上传 {formatSpeed(uploadSpeed)}</span> : null}
            {eta > 0 ? <span>剩余 {formatEtaSeconds(eta)}</span> : null}
          </div>
          <div className="circle-task-progress"><div style={{ width: `${progress}%` }} /></div>
        </div>
        <div className="circle-task-actions" onClick={event => event.stopPropagation()}>
          {status === 'processing' && onPause ? <button type="button" onClick={() => onPause(task)}><Pause size={13} />暂停</button> : null}
          {status === 'paused' && onResume ? <button type="button" onClick={() => onResume(task)}><Play size={13} />恢复</button> : null}
          {status === 'waiting_retry' && onRetryWaiting ? <button type="button" onClick={() => onRetryWaiting(task)}><RefreshCw size={13} />立即重试</button> : null}
          {status === 'failed' && onRetry ? <button type="button" disabled={retrying} onClick={() => onRetry(task)}><RefreshCw size={13} />{retrying ? '重试中' : '重试'}</button> : null}
          {canReimport && onReimport ? <button type="button" onClick={() => onReimport(task)}><PackageCheck size={13} />入库</button> : null}
          {['processing', 'pending', 'paused', 'waiting_retry'].includes(status) && onCancel ? <button type="button" className="danger" onClick={() => onCancel(task)}><XCircle size={13} />取消</button> : null}
        </div>
      </div>

      {expanded ? (
        <div className="circle-task-detail" onClick={event => event.stopPropagation()}>
          {task.error_message || task.task_metadata?.failure_reason ? (
            <div className="circle-task-error"><AlertCircle size={15} />{task.error_message || task.task_metadata?.failure_reason}</div>
          ) : null}
          <div className="circle-task-path-grid">
            <div><span>{isUpload ? '来源目录' : '下载目录'}</span><strong>{getTaskDownloadRoot(task)}</strong></div>
            <div><span>最终路径</span><strong>{getTaskFinalPath(task)}</strong></div>
          </div>
          {fileRows.length ? (
            <div className="circle-task-file-list">
              {fileRows.map(file => (
                <div key={`${task.id}-${file.relative_path || file.name}`} className={cx('circle-task-file-row', file.tone)}>
                  <FileText size={13} />
                  <strong title={file.relative_path || file.name}>{file.name || file.relative_path}</strong>
                  <span>{file.progress}%</span>
                  <em>{file.sizeText}</em>
                  <div><i style={{ width: `${file.progress}%` }} /></div>
                </div>
              ))}
            </div>
          ) : null}
          {Array.isArray(task.progress_log) && task.progress_log.length ? (
            <div className="circle-task-log">
              {task.progress_log.slice(-6).map((entry, index) => (
                <div key={`${entry.time || index}-${entry.message}`}>
                  <span>{formatLogTime(entry.time)}</span>
                  <strong>{entry.message}</strong>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}

function normalizeTasks(tasks) {
  return (Array.isArray(tasks) ? tasks : [])
    .filter(Boolean)
    .map(task => ({ ...task, id: String(task.id || task.task_id || task.active_task_id || '') }))
    .sort((left, right) => getTaskSortScore(right) - getTaskSortScore(left))
}

function buildTabs(tasks) {
  return [
    { value: 'all', label: '全部', count: tasks.length },
    { value: 'active', label: '进行中', count: tasks.filter(task => getTaskGroup(task) === 'active').length },
    { value: 'pending', label: '等待中', count: tasks.filter(task => getTaskGroup(task) === 'pending').length },
    { value: 'failed', label: '异常', count: tasks.filter(task => getTaskGroup(task) === 'failed').length },
    { value: 'completed', label: '完成', count: tasks.filter(task => getTaskGroup(task) === 'completed').length }
  ]
}

function getTaskGroup(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'processing') return 'active'
  if (['pending', 'paused', 'waiting_retry', 'waiting_manual'].includes(status)) return 'pending'
  if (['failed', 'partial_failed'].includes(status)) return 'failed'
  if (status === 'completed') return getTaskTone(task) === 'warning' ? 'failed' : 'completed'
  return 'pending'
}

function getTaskTone(task) {
  const status = String(task?.display_status || task?.status || '')
  if (['failed', 'partial_failed'].includes(status)) return 'danger'
  if (status === 'completed' && hasTaskFailures(task)) return 'warning'
  if (status === 'completed') return 'success'
  if (['pending', 'paused', 'waiting_retry', 'waiting_manual'].includes(status)) return 'pending'
  return 'processing'
}

function getTaskIcon(task, isUpload) {
  const tone = getTaskTone(task)
  if (tone === 'success') return <CheckCircle2 size={22} />
  if (tone === 'danger' || tone === 'warning') return <AlertCircle size={22} />
  if (String(task?.status || '') === 'paused') return <Pause size={22} />
  if (String(task?.display_status || task?.status || '') === 'pending') return <Clock3 size={22} />
  if (isUpload) return <Upload size={22} />
  return <Download size={22} />
}

function getTaskSortScore(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'processing') return 500
  if (status === 'pending') return 400
  if (status === 'waiting_retry') return 350
  if (status === 'paused') return 300
  if (status === 'failed' || status === 'partial_failed') return 200
  if (status === 'completed') return 100
  return 0
}

function getTaskOverallPercent(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'completed') return 100
  const rows = getUnifiedFileRows(task)
  if (rows.length) return Math.max(0, Math.min(99, Math.round(rows.reduce((sum, row) => sum + Number(row.progress || 0), 0) / rows.length)))
  return Math.max(0, Math.min(status === 'processing' ? 99 : 100, Math.round(Number(task?.progress || 0))))
}

function getPrimaryFileProgressLabel(task) {
  const rows = getUnifiedFileRows(task)
  if (!rows.length) return `${getTaskOverallPercent(task)}%`
  const finished = rows.filter(row => Number(row.progress || 0) >= 100).length
  return `${finished}/${rows.length} 文件`
}

function getUnifiedFileRows(task) {
  const rows = []
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources : []
  selectedResources.forEach(resource => {
    rows.push({
      relative_path: resource.relative_path || resource.file_name || resource.name,
      name: String(resource.file_name || resource.relative_path || resource.name || '').split('/').pop().split('\\').pop(),
      progress: 0,
      total: Number(resource.size_bytes || resource.size || 0),
      sizeText: formatBytes(resource.size_bytes || resource.size || 0),
      tone: 'neutral'
    })
  })
  ;['download_files', 'upload_files', 'uploaded_files'].forEach(key => {
    const files = Array.isArray(task?.[key]) ? task[key] : []
    files.forEach(file => upsertFileRow(rows, file, key))
  })
  if (!rows.length && Array.isArray(task?.files)) task.files.forEach(file => upsertFileRow(rows, file, 'files'))
  return rows
}

function upsertFileRow(rows, file, key) {
  const relativePath = String(file?.relative_path || file?.path || file?.name || '').trim()
  const name = String(file?.name || relativePath.split('/').pop().split('\\').pop() || '').trim()
  const found = rows.find(row => row.relative_path === relativePath || row.name === name)
  const progress = Math.max(0, Math.min(100, Math.round(Number(file?.progress || (key === 'uploaded_files' ? 100 : 0)))))
  const total = Number(file?.size_bytes || file?.size || file?.total || file?.total_bytes || 0)
  const next = {
    relative_path: relativePath,
    name,
    progress,
    total,
    sizeText: formatBytes(total),
    tone: progress >= 100 ? (key.includes('upload') ? 'upload-success' : 'success') : key.includes('upload') ? 'upload' : 'processing'
  }
  if (found) Object.assign(found, next)
  else rows.push(next)
}

function hasTaskFailures(task) {
  const errorMessage = String(task?.error_message || task?.task_metadata?.failure_reason || '').trim()
  if (errorMessage) return true
  const rows = [...(Array.isArray(task?.download_files) ? task.download_files : []), ...(Array.isArray(task?.upload_files) ? task.upload_files : [])]
  return rows.some(file => ['failed', 'error'].includes(String(file?.status || file?.state || '')))
}

function getTaskDownloadRoot(task) {
  return String(
    task?.task_metadata?.local_download_root ||
    task?.session_state?.local_download_root ||
    task?.task_metadata?.download_root ||
    task?.task_metadata?.download_base_path ||
    task?.task_metadata?.source_base_path ||
    task?.source_path ||
    ''
  ).trim() || '处理中'
}

function getTaskFinalPath(task) {
  return String(
    task?.task_metadata?.final_output_path ||
    task?.final_output_path ||
    task?.output_path ||
    task?.task_metadata?.target_path ||
    ''
  ).trim() || '处理中'
}
