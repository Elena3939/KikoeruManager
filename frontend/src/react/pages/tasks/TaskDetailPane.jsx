import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Loader2,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  XCircle
} from 'lucide-react'
import { Button, EmptyState } from '../../components/Primitives'
import { formatDateTime } from '../../utils/format'
import {
  actionLabels,
  buildGarbledSummary,
  formatRJCode,
  getDLsiteFailureReason,
  getDomainMeta,
  getGarbledDiagnostic,
  getOutputPath,
  getRecoveredNotice,
  getTaskActions,
  getTaskTitle,
  showProgress
} from './taskUtils'
import { TaskFileTree } from './TaskFileTree'
import { TaskStatusPill } from './TaskStatusPill'

const actionIconMap = {
  pause: PauseCircle,
  resume: PlayCircle,
  cancel: XCircle,
  retry: RotateCcw,
  retry_waiting: RotateCcw,
  delete_waiting_retry: XCircle,
  open_subtitle_import: ArrowRight,
  open_circle_completion: ArrowRight,
  reindex_circle: RotateCcw
}

function actionTone(action) {
  if (action === 'cancel' || action === 'delete_waiting_retry') return 'danger'
  if (action === 'pause') return 'warning'
  if (action === 'resume') return 'success'
  return 'ghost'
}

function PathBlock({ label, value }) {
  return (
    <div className="task-path-block">
      <span>{label}</span>
      <code>{value || '-'}</code>
    </div>
  )
}

export function TaskDetailPane({
  item,
  detailLoading = false,
  fileTreeSections = [],
  circleMeta = [],
  circleLog = [],
  treeFilterMode = 'all',
  onOpenRoute,
  onAction,
  onTreeFilterModeChange,
  onExpandSection,
  onToggleNode
}) {
  if (!item) {
    return (
      <section className="task-detail-pane">
        <EmptyState title="选择任务" description="选择左侧任务查看完整详情" />
      </section>
    )
  }

  const meta = getDomainMeta(item.domain)
  const Icon = meta.icon
  const recoveredNotice = getRecoveredNotice(item)
  const dlsiteFailureReason = getDLsiteFailureReason(item)
  const garbled = getGarbledDiagnostic(item)
  const actions = getTaskActions(item)

  return (
    <section className="task-detail-pane">
      <header className="task-detail-head">
        <strong>任务详情</strong>
        {item.route_hint ? (
          <Button variant="ghost" size="sm" onClick={() => onOpenRoute?.(item)}>
            <ArrowRight size={14} strokeWidth={2.4} />
            打开关联页面
          </Button>
        ) : null}
      </header>

      {detailLoading ? (
        <div className="task-detail-loading">
          <Loader2 size={14} className="km-spin" />
          正在读取完整任务详情...
        </div>
      ) : null}

      <div className="task-detail-hero" data-domain={meta.tone}>
        <Icon className="task-detail-domain-icon" size={25} strokeWidth={2.1} />
        <div>
          <div className="task-detail-title-row">
            <h2>{getTaskTitle(item)}</h2>
            <TaskStatusPill status={item.status} label={item.status_label} />
          </div>
          {item.subtitle ? <p>{item.subtitle}</p> : null}
          <div className="task-detail-tags">
            <span>{item.domain_label || meta.label}</span>
            {formatRJCode(item.rjcode) ? <b>{formatRJCode(item.rjcode)}</b> : null}
          </div>
        </div>
      </div>

      <section className="task-detail-meta-grid">
        <div>
          <span>来源</span>
          <strong>{item.source_label || '-'}</strong>
        </div>
        <div>
          <span>RJ</span>
          <strong>{formatRJCode(item.rjcode) || '-'}</strong>
        </div>
        <div>
          <span>创建时间</span>
          <strong>{formatDateTime(item.created_at)}</strong>
        </div>
        <div>
          <span>完成时间</span>
          <strong>{formatDateTime(item.completed_at)}</strong>
        </div>
      </section>

      <section className="task-detail-section">
        <span className="task-section-title">当前状态</span>
        {recoveredNotice ? (
          <div className="task-alert" data-tone="success">
            <CheckCircle2 size={14} strokeWidth={2.4} />
            <div>
              <strong>已恢复</strong>
              <p>{recoveredNotice}</p>
            </div>
          </div>
        ) : null}
        <p className="task-current-step">{item.current_step || '-'}</p>
        {showProgress(item) ? (
          <div className="task-detail-progress">
            <div className="task-progress-track">
              <span style={{ width: `${Math.max(0, Math.min(Number(item.progress || 0), 100))}%` }} />
            </div>
            <em>{Number(item.progress || 0)}%</em>
          </div>
        ) : null}
        {item.error_message ? (
          <div className="task-alert" data-tone={item.status === 'completed' ? 'success' : 'danger'}>
            {item.status === 'completed' ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            <p>{item.status === 'completed' ? '已修复 · ' : ''}{item.error_message}</p>
          </div>
        ) : null}
        {dlsiteFailureReason ? (
          <div className="task-alert" data-tone={item.status === 'completed' ? 'success' : 'danger'}>
            {item.status === 'completed' ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            <p>{item.status === 'completed' ? '已修复 · ' : ''}DLsite 抓取失败原因：{dlsiteFailureReason}</p>
          </div>
        ) : null}
        {garbled ? (
          <div className="task-garbled-card">
            <AlertTriangle size={16} strokeWidth={2.4} />
            <div>
              <strong>文件名乱码诊断</strong>
              <p>{buildGarbledSummary(garbled)}</p>
              <div className="task-garbled-grid">
                <span><em>样本</em><b>{garbled.sample || '-'}</b></span>
                <span><em>评分</em><b>{garbled.scoreBefore} {'->'} {garbled.scoreAfter}</b></span>
                <span><em>修复 / 编码尝试</em><b>{garbled.repairedCount} / {garbled.codecPairsTried}</b></span>
                <span><em>触发位置</em><b>{garbled.origin || '-'}</b></span>
              </div>
            </div>
          </div>
        ) : null}
      </section>

      {circleMeta.length ? (
        <section className="task-detail-section">
          <span className="task-section-title">进度元信息</span>
          <div className="task-circle-meta-grid">
            {circleMeta.map(entry => (
              <div key={`${entry.label}-${entry.value}`}>
                <span>{entry.label}</span>
                <strong>{entry.value}</strong>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {circleLog.length ? (
        <section className="task-detail-section">
          <span className="task-section-title">进度日志</span>
          <div className="task-progress-log">
            {circleLog.map((entry, index) => (
              <div key={`${entry.time}-${index}`}>
                <span>{formatDateTime(entry.time)}</span>
                <b>{entry.progress}%</b>
                <p>{entry.message}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <TaskFileTree
        sections={fileTreeSections}
        filterMode={treeFilterMode}
        onFilterModeChange={onTreeFilterModeChange}
        onExpandSection={onExpandSection}
        onToggleNode={onToggleNode}
      />

      <section className="task-detail-section">
        <span className="task-section-title">路径信息</span>
        <PathBlock label="源路径" value={item.source_path} />
        <PathBlock label="输出路径" value={getOutputPath(item)} />
      </section>

      {actions.length ? (
        <footer className="task-detail-actions">
          {actions.map(action => {
            const ActionIcon = actionIconMap[action] || RefreshCw
            return (
              <Button key={`${item.id}-${action}`} variant={actionTone(action)} onClick={() => onAction?.(item, action)}>
                <ActionIcon size={14} strokeWidth={2.5} />
                {actionLabels[action] || action}
              </Button>
            )
          })}
        </footer>
      ) : null}
    </section>
  )
}
