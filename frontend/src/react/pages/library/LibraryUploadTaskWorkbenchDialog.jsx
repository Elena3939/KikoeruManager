import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileText,
  Folder,
  Minimize2,
  Pause,
  Play,
  RefreshCcw,
  Search,
  UploadCloud,
  XCircle,
  Zap
} from 'lucide-react'
import { Button, Modal, TextInput } from '../../components/Primitives'
import { formatBytes, formatDateTime } from '../../utils/format'

const taskFilters = [
  ['all', '全部'],
  ['processing', '进行中'],
  ['pending', '等待中'],
  ['partial_failed', '部分失败'],
  ['completed', '已完成']
]

export function LibraryUploadTaskWorkbenchDialog({
  visible,
  tasks,
  refreshing,
  onClose,
  onBackground,
  onRefresh,
  onPause,
  onResume,
  onCancel
}) {
  const rows = useMemo(() => (Array.isArray(tasks) ? tasks : []).map(normalizeUploadTask), [tasks])
  const [activeFilter, setActiveFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [expandedIds, setExpandedIds] = useState(new Set())

  const filterCounts = useMemo(() => ({
    all: rows.length,
    processing: rows.filter(isTaskProcessing).length,
    pending: rows.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task.status || ''))).length,
    partial_failed: rows.filter(task => uploadTaskTone(task) === 'warning').length,
    completed: rows.filter(task => uploadTaskTone(task) === 'success').length
  }), [rows])

  const filteredRows = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return rows.filter(task => {
      if (activeFilter === 'processing' && !isTaskProcessing(task)) return false
      if (activeFilter === 'pending' && !['pending', 'paused', 'waiting_retry'].includes(String(task.status || ''))) return false
      if (activeFilter === 'partial_failed' && uploadTaskTone(task) !== 'warning') return false
      if (activeFilter === 'completed' && uploadTaskTone(task) !== 'success') return false
      if (!keyword) return true
      return [
        task.work_title,
        task.source_label,
        task.source_root,
        task.final_output_path,
        task.target_path,
        task.id
      ].join(' ').toLowerCase().includes(keyword)
    })
  }, [rows, activeFilter, query])

  const aggregate = useMemo(() => buildUploadAggregate(rows), [rows])

  useEffect(() => {
    if (!visible) return
    setExpandedIds(prev => {
      if (prev.size) return prev
      const firstActive = rows.find(task => isTaskProcessing(task) || ['pending', 'paused', 'waiting_retry'].includes(String(task.status || '')))
      return firstActive?.id ? new Set([firstActive.id]) : new Set(rows[0]?.id ? [rows[0].id] : [])
    })
  }, [visible, rows.map(task => task.id).join('|')])

  if (!visible) return null

  function toggleExpanded(taskId) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      next.has(taskId) ? next.delete(taskId) : next.add(taskId)
      return next
    })
  }

  return (
    <Modal
      title="上传任务工作台"
      width={1320}
      onClose={onClose}
      footer={
        <div className="library-upload-workbench-footer">
          <div>
            <span>上传速度 <b>{aggregate.speedText}</b></span>
            <span>剩余大小 <b>{aggregate.remainingText}</b></span>
            <span>预计时间 <b>{aggregate.etaText}</b></span>
            <span>剩余任务 <b>{aggregate.remainingTaskText}</b></span>
          </div>
          <div>
            <Button loading={refreshing} onClick={onRefresh}><RefreshCcw size={15} />刷新</Button>
            <Button onClick={onBackground}><Minimize2 size={15} />后台运行</Button>
            <Button onClick={onClose}>关闭</Button>
          </div>
        </div>
      }
    >
      <div className="library-upload-workbench library-upload-workbench-v2">
        <header className="library-upload-workbench-head">
          <div>
            <strong>Upload Manager</strong>
            <span>库存上传任务 · {rows.length} 个任务</span>
            <nav>
              {taskFilters.map(([value, label]) => (
                <button
                  type="button"
                  key={value}
                  className={activeFilter === value ? 'is-active' : ''}
                  onClick={() => setActiveFilter(value)}
                >
                  {label}
                  <em>{filterCounts[value] ?? 0}</em>
                </button>
              ))}
            </nav>
          </div>
          <label className="library-upload-workbench-search">
            <Search size={15} />
            <TextInput value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索任务 / 来源 / 目标路径..." />
          </label>
        </header>

        {!filteredRows.length ? <div className="km-empty"><UploadCloud size={34} /><strong>暂无符合筛选的上传任务</strong></div> : null}
        <div className="library-upload-task-list">
          {filteredRows.map(task => (
            <UploadTaskCard
              key={task.id}
              task={task}
              expanded={expandedIds.has(task.id)}
              onToggle={() => toggleExpanded(task.id)}
              onPause={onPause}
              onResume={onResume}
              onCancel={onCancel}
            />
          ))}
        </div>
      </div>
    </Modal>
  )
}

export function LibraryUploadBackgroundCard({ tasks, onOpen, onDismiss }) {
  const mapped = (tasks || []).map(normalizeUploadTask)
  const active = mapped.find(task => ['processing', 'pending', 'paused', 'waiting_retry'].includes(String(task?.status || ''))) || mapped[0]
  if (!active) return null
  const percent = clampPercent(active.progress)
  const aggregate = buildUploadAggregate(mapped)
  return (
    <div className="library-upload-background-card">
      <button type="button" className="library-upload-background-main" onClick={onOpen}>
        <UploadCloud size={18} />
        <span>
          <b>{active.work_title || taskTitle(active)}</b>
          <small>{statusLabel(active.status)} · {percent}% · {aggregate.speedText}</small>
        </span>
        <em style={{ '--upload-percent': `${percent}%` }} />
      </button>
      <button type="button" title="收起" onClick={() => onDismiss?.()}>×</button>
    </div>
  )
}

function UploadTaskCard({ task, expanded, onToggle, onPause, onResume, onCancel }) {
  const active = ['processing', 'pending', 'paused', 'waiting_retry'].includes(String(task.status || ''))
  const paused = String(task.status || '') === 'paused'
  const tone = uploadTaskTone(task)
  const percent = clampPercent(task.progress)
  const fileRows = buildUnifiedUploadFileRows(task)
  const logs = normalizeTaskLogs(task)
  return (
    <article className={`library-upload-task-card-v2 is-${tone} ${expanded ? 'is-expanded' : ''}`} onClick={onToggle}>
      <div className="library-upload-task-summary">
        <span className="library-upload-task-icon"><UploadCloud size={24} /></span>
        <div className="library-upload-task-main">
          <header>
            <div>
              <strong>{task.work_title || taskTitle(task)}</strong>
              <small>{task.task_metadata?.workbench_subtitle || task.source_label || '上传任务'}</small>
            </div>
            <div className="library-upload-task-actions" onClick={event => event.stopPropagation()}>
              {active && !paused ? <Button size="xs" onClick={() => onPause?.(task.id)}><Pause size={13} />暂停</Button> : null}
              {paused ? <Button size="xs" variant="primary" onClick={() => onResume?.(task.id)}><Play size={13} />恢复</Button> : null}
              {active ? <Button size="xs" variant="danger" onClick={() => onCancel?.(task.id)}><XCircle size={13} />取消</Button> : null}
            </div>
          </header>
          <div className="library-upload-task-meta">
            <span className={`is-${tone}`}><StatusIcon task={task} />{statusLabel(task.display_status || task.status)}</span>
            <span>{getPrimarySizeText(task)}</span>
            <span>{getPrimaryFileProgressLabel(task)}</span>
            <span><Zap size={12} />上传 {formatSpeed(task.upload_speed)}</span>
            {task.upload_speed > 0 ? <span><Clock3 size={12} />剩余 {formatEtaSeconds(getUploadEtaSeconds(task))}</span> : null}
            {task.current_step ? <span>{task.current_step}</span> : null}
          </div>
          <div className="library-upload-summary-progress">
            <span><i style={{ width: `${percent}%` }} /></span>
            <b>{percent}%</b>
          </div>
        </div>
        <ChevronDown size={18} className={expanded ? 'is-open' : ''} />
      </div>

      {expanded ? (
        <div className="library-upload-task-detail" onClick={event => event.stopPropagation()}>
          {task.error_message || task.failure_reason ? (
            <div className="library-upload-detail-error">
              <AlertCircle size={16} />
              <span>{task.error_message || task.failure_reason}</span>
            </div>
          ) : null}
          <div className="library-upload-path-grid">
            <div>
              <span>来源目录</span>
              <b>{task.source_root || task.source_path || '-'}</b>
            </div>
            <div>
              <span>最终路径</span>
              <b>{task.final_output_path || task.target_path || '处理中'}</b>
            </div>
          </div>

          {fileRows.length ? (
            <section className="library-upload-detail-section">
              <header><strong><FileText size={14} />文件明细</strong><span>{fileRows.length} 项</span></header>
              <div className="library-upload-detail-files">
                {fileRows.map(file => (
                  <div key={file.relative_path || file.name} className={`is-${file.tone}`}>
                    <div>
                      <span>{file.name}</span>
                      <em>{file.statusText}</em>
                      <small>{file.progress}% · {file.sizeText}{file.uploadSpeedVisible ? ` · ${formatSpeed(file.uploadSpeed)}/s` : ''}</small>
                    </div>
                    <b><i style={{ width: `${file.progress}%` }} /></b>
                    {file.reason ? <p>{file.reason}</p> : null}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {logs.length ? (
            <section className="library-upload-detail-section">
              <header><strong><Activity size={14} />最近日志</strong><span>{logs.length} 条</span></header>
              <div className="library-upload-detail-logs">
                {logs.slice(-8).map((entry, index) => (
                  <p key={`${entry.time || index}-${entry.message || index}`} className={`is-${entry.level || 'info'}`}>
                    <time>{formatLogTime(entry.time)}</time>
                    <span>{entry.message || entry.text || '-'}</span>
                  </p>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}

function StatusIcon({ task }) {
  const tone = uploadTaskTone(task)
  if (tone === 'success') return <CheckCircle2 size={12} />
  if (tone === 'danger' || tone === 'warning') return <AlertCircle size={12} />
  return <UploadCloud size={12} />
}

function normalizeUploadTask(task) {
  const metadata = task?.task_metadata || {}
  const selectedPaths = Array.isArray(metadata.selected_paths) ? metadata.selected_paths : []
  const sourceBasePath = String(metadata.source_base_path || metadata.source_root || task?.source_path || '').trim()
  const targetPath = String(metadata.target_path || '').trim()
  const finalOutputPath = String(metadata.final_output_path || task?.final_output_path || task?.output_path || '').trim()
  const runtime = task?.upload_runtime || {}
  const totalBytes = Number(runtime.total_bytes || metadata.total_bytes || 0)
  const transferredBytes = Number(runtime.transferred_bytes || metadata.transferred_bytes || 0)
  const uploadSpeed = Number(runtime.frontend_speed_bytes_per_sec || runtime.speed_bytes_per_sec || task?.frontend_speed_bytes_per_sec || 0)
  const title = selectedPaths.length === 1
    ? basename(selectedPaths[0])
    : (String(metadata.source_label || task?.source_label || '').trim() || basename(sourceBasePath) || '上传任务')

  return {
    ...task,
    work_title: task?.work_title || title,
    source_label: task?.source_label || title,
    source_root: sourceBasePath,
    target_path: targetPath,
    final_output_path: finalOutputPath || targetPath,
    upload_runtime: runtime,
    upload_speed: uploadSpeed,
    progress: clampActiveUploadPercent(transferredBytes, totalBytes, task?.display_status || task?.status, task?.progress || 0),
    task_metadata: {
      ...metadata,
      selected_paths: selectedPaths,
      source_root: sourceBasePath,
      target_path: targetPath,
      final_output_path: finalOutputPath || targetPath,
      total_bytes: totalBytes
    }
  }
}

function buildUnifiedUploadFileRows(task) {
  const runtime = task?.upload_runtime || {}
  const currentRelativePath = String(runtime.current_relative_path || '').trim()
  const currentSpeed = Number(runtime.frontend_speed_bytes_per_sec || runtime.speed_bytes_per_sec || 0)
  const currentUploadedBytes = Number(runtime.current_file_uploaded_bytes || 0)
  const rows = new Map()

  ;(Array.isArray(task?.upload_files) ? task.upload_files : []).forEach((file, index) => {
    const relativePath = String(file?.relative_path || file?.path || file?.name || '').trim()
    const size = Number(file?.size || file?.size_bytes || 0)
    const isCurrent = relativePath && relativePath === currentRelativePath
    const completed = String(file?.status || '') === 'completed' || Number(file?.progress || 0) >= 100
    const uploaded = completed ? size : (isCurrent ? Math.min(size, currentUploadedBytes) : Number(file?.uploaded_bytes || file?.uploaded || 0))
    rows.set(relativePath || `file-${index}`, {
      index,
      relative_path: relativePath,
      name: basename(file?.name || relativePath),
      total: size,
      uploadedBytes: uploaded,
      progress: completed ? 100 : clampPercent(file?.progress || (size > 0 ? (uploaded / size) * 100 : 0)),
      uploadSpeed: isCurrent ? currentSpeed : 0,
      uploadSpeedVisible: isCurrent && currentSpeed > 0,
      statusText: completed ? '已上传' : (isCurrent ? '上传中' : '等待上传'),
      tone: completed ? 'success' : (isCurrent ? 'processing' : 'neutral'),
      reason: file?.reason || file?.error || ''
    })
  })

  ;(Array.isArray(task?.uploaded_files) ? task.uploaded_files : []).forEach((file, index) => {
    const relativePath = String(file?.relative_path || file?.path || file?.name || '').trim()
    const key = relativePath || `uploaded-${index}`
    const size = Number(file?.size || file?.size_bytes || file?.uploaded_bytes || rows.get(key)?.total || 0)
    rows.set(key, {
      ...(rows.get(key) || {}),
      index: rows.get(key)?.index ?? index,
      relative_path: relativePath,
      name: basename(file?.name || relativePath),
      total: size,
      uploadedBytes: size,
      progress: 100,
      uploadSpeed: 0,
      uploadSpeedVisible: false,
      statusText: '已上传',
      tone: 'success',
      reason: ''
    })
  })

  const failedFiles = [
    ...(Array.isArray(task?.failed_files) ? task.failed_files : []),
    ...(Array.isArray(task?.task_metadata?.failed_files) ? task.task_metadata.failed_files : [])
  ]
  failedFiles.forEach((file, index) => {
    const relativePath = String(file?.relative_path || file?.path || file?.name || '').trim()
    const key = relativePath || `failed-${index}`
    const previous = rows.get(key) || {}
    const size = Number(file?.size || file?.size_bytes || previous.total || 0)
    rows.set(key, {
      ...previous,
      index: previous.index ?? index,
      relative_path: relativePath,
      name: basename(file?.name || relativePath),
      total: size,
      uploadedBytes: Number(file?.uploaded || file?.uploaded_bytes || previous.uploadedBytes || 0),
      progress: clampPercent(previous.progress || 0),
      uploadSpeed: 0,
      uploadSpeedVisible: false,
      statusText: '上传失败',
      tone: 'danger',
      reason: String(file?.reason || file?.exception_type || file?.error || '上传失败').trim()
    })
  })

  return [...rows.values()]
    .map(row => ({
      ...row,
      sizeText: `上传 ${formatBytes(row.uploadedBytes || 0)} / ${formatBytes(row.total || 0)}`
    }))
    .sort((left, right) => (left.index || 0) - (right.index || 0))
}

function buildUploadAggregate(tasks) {
  const active = tasks.filter(isTaskProcessing)
  const paused = tasks.filter(task => String(task.status || '') === 'paused')
  const speed = active.reduce((sum, task) => sum + Number(task.upload_speed || 0), 0)
  const remaining = tasks.reduce((sum, task) => {
    const runtime = task.upload_runtime || {}
    const total = Number(runtime.total_bytes || task.task_metadata?.total_bytes || 0)
    const transferred = Number(runtime.transferred_bytes || 0)
    return sum + Math.max(0, total - transferred)
  }, 0)
  const remainingTasks = tasks.filter(task => ['processing', 'pending', 'paused', 'waiting_retry'].includes(String(task.status || ''))).length
  return {
    speed,
    remaining,
    speedText: speed > 0 ? `${formatBytes(speed)}/s` : (!active.length && paused.length ? '已暂停' : '0 B/s'),
    remainingText: formatBytes(remaining),
    etaText: speed > 0 ? formatEtaSeconds(Math.ceil(remaining / speed)) : '—',
    remainingTaskText: remainingTasks ? `${remainingTasks} 个` : '0 个'
  }
}

function normalizeTaskLogs(task) {
  const metadata = task?.task_metadata || {}
  const value = Array.isArray(task?.progress_log) ? task.progress_log : Array.isArray(metadata.progress_log) ? metadata.progress_log : []
  return value.filter(Boolean)
}

function taskTitle(task) {
  const metadata = task?.task_metadata || {}
  const selected = Array.isArray(metadata.selected_paths) ? metadata.selected_paths : []
  return metadata.source_label || basename(selected[0]) || basename(task?.source_path) || task?.id || '上传任务'
}

function basename(value) {
  const normalized = String(value || '').replace(/\\/g, '/').replace(/\/+$/, '')
  return normalized.split('/').filter(Boolean).pop() || normalized || ''
}

function clampActiveUploadPercent(transferredBytes, totalBytes, status, fallbackProgress = 0) {
  const normalizedStatus = String(status || '')
  const total = Math.max(0, Number(totalBytes || 0))
  const transferred = Math.max(0, Number(transferredBytes || 0))
  if (normalizedStatus === 'completed') return 100
  if (total <= 0) return Math.max(0, Math.min(99, Math.floor(Number(fallbackProgress || 0))))
  const rawPercent = Math.max(0, Math.min(100, Math.floor((Math.min(transferred, total) / total) * 100)))
  return transferred < total ? Math.min(rawPercent, 99) : Math.min(rawPercent, 99)
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value || 0))))
}

function isTaskProcessing(task) {
  return String(task?.display_status || task?.status || '') === 'processing'
}

function uploadTaskTone(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'completed' && !(task?.error_message || task?.failure_reason)) return 'success'
  if (status === 'failed' || status === 'error' || status === 'canceled' || status === 'cancelled') return 'danger'
  if (status === 'partial_failed' || task?.error_message || task?.failure_reason) return 'warning'
  if (status === 'processing') return 'processing'
  return 'pending'
}

function getPrimarySizeText(task) {
  const runtime = task.upload_runtime || {}
  const total = Number(runtime.total_bytes || task.task_metadata?.total_bytes || 0)
  const transferred = Number(runtime.transferred_bytes || 0)
  if (!total) return '大小未知'
  return `${formatBytes(transferred)} / ${formatBytes(total)}`
}

function getPrimaryFileProgressLabel(task) {
  const files = Array.isArray(task.upload_files) ? task.upload_files : []
  const uploaded = Array.isArray(task.uploaded_files) ? task.uploaded_files.length : 0
  const runtimeCurrent = task.upload_runtime?.current_relative_path
  if (!files.length) return uploaded ? `${uploaded} 文件已上传` : '无文件明细'
  const completed = files.filter(file => String(file?.status || '') === 'completed' || Number(file?.progress || 0) >= 100).length
  const current = runtimeCurrent ? ` · ${basename(runtimeCurrent)}` : ''
  return `${Math.max(completed, uploaded)} / ${files.length} 文件${current}`
}

function getUploadEtaSeconds(task) {
  const runtime = task.upload_runtime || {}
  const total = Number(runtime.total_bytes || task.task_metadata?.total_bytes || 0)
  const transferred = Number(runtime.transferred_bytes || 0)
  const speed = Number(task.upload_speed || 0)
  if (speed <= 0) return 0
  return Math.ceil(Math.max(0, total - transferred) / speed)
}

function formatEtaSeconds(seconds) {
  const value = Math.max(0, Number(seconds || 0))
  if (!value) return '—'
  if (value < 60) return `${Math.ceil(value)} 秒`
  if (value < 3600) return `${Math.ceil(value / 60)} 分钟`
  const hours = Math.floor(value / 3600)
  const minutes = Math.ceil((value % 3600) / 60)
  return `${hours} 小时 ${minutes} 分钟`
}

function formatSpeed(value) {
  const speed = Number(value || 0)
  return speed > 0 ? formatBytes(speed) : '0 B'
}

function formatLogTime(value) {
  if (!value) return '--:--'
  const date = new Date(typeof value === 'number' && value < 10_000_000_000 ? value * 1000 : value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function statusLabel(status) {
  const map = {
    processing: '上传中',
    pending: '等待中',
    paused: '已暂停',
    waiting_retry: '等待重试',
    completed: '已完成',
    failed: '失败',
    partial_failed: '部分失败',
    canceled: '已取消',
    cancelled: '已取消'
  }
  return map[String(status || '')] || status || '未知'
}
