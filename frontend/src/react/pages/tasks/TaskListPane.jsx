import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Circle,
  CloudDownload,
  Database,
  Download,
  HardDrive,
  Hash,
  Search,
  XCircle
} from 'lucide-react'
import { motion } from 'motion/react'
import { EmptyState, IconButton, LoadingState } from '../../components/Primitives'
import {
  formatRJCode,
  getDomainMeta,
  getRecoveredNotice,
  getTaskId,
  getTaskSummary,
  getTaskTitle,
  shouldShowTaskStep,
  showProgress
} from './taskUtils'
import { TaskStatusPill } from './TaskStatusPill'

function extractSummaryValue(piece) {
  const text = String(piece || '').trim()
  const match = text.match(/(-?\d[\d,.\s%]*)\s*$/)
  return match ? match[1].trim() : text
}

function extractSummaryLabel(piece) {
  const text = String(piece || '').trim()
  const match = text.match(/(-?\d[\d,.\s%]*)\s*$/)
  return match ? text.slice(0, match.index).trim() : ''
}

function summaryIcon(piece) {
  const text = String(piece || '').toLowerCase()
  if (text.includes('dlsite') || text.includes('dl')) return Database
  if (text.includes('可下载')) return CloudDownload
  if (text.includes('下载')) return Download
  if (text.includes('本地')) return HardDrive
  if (text.includes('缺失')) return AlertCircle
  if (text.includes('候选') || text.includes('搜索')) return Search
  if (text.includes('完成') || text.includes('成功') || text.includes('恢复')) return CheckCircle2
  if (text.includes('失败') || text.includes('错误')) return XCircle
  if (text.includes('总') || text.includes('合计')) return Hash
  return Circle
}

export function TaskListPane({
  items = [],
  totalItems = 0,
  currentOffset = 0,
  pageSize = 80,
  selectedId = '',
  loading = false,
  onSelect,
  onPrevPage,
  onNextPage
}) {
  const pageIndex = Math.floor(currentOffset / pageSize) + 1
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))

  return (
    <aside className="task-list-pane">
      <header className="task-pane-head">
        <div>
          <strong>任务列表</strong>
          <span>{totalItems} 个任务</span>
        </div>
      </header>

      {loading ? (
        <LoadingState label="正在读取任务中心..." />
      ) : items.length ? (
        <div className="task-list-scroll">
          {items.map((item, index) => {
            const id = getTaskId(item)
            const meta = getDomainMeta(item.domain)
            const Icon = meta.icon
            const recoveredNotice = getRecoveredNotice(item)
            const summary = getTaskSummary(item)
            return (
              <motion.button
                key={id || `${item.title}-${index}`}
                type="button"
                className={`task-card ${selectedId === id ? 'is-active' : ''}`}
                data-domain={meta.tone}
                onClick={() => onSelect?.(id)}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(index, 12) * 0.018, duration: 0.22 }}
              >
                <Icon className="task-card-domain-icon" size={17} strokeWidth={2.2} />
                <div className="task-card-body">
                  <div className="task-card-title-row">
                    <span className="task-card-title">{getTaskTitle(item)}</span>
                    <span className="task-domain-chip">{item.domain_label || meta.label}</span>
                    <TaskStatusPill status={item.status} label={item.status_label} />
                  </div>

                  <div className="task-card-subtitle-row">
                    {formatRJCode(item.rjcode) ? <b>{formatRJCode(item.rjcode)}</b> : null}
                    {item.subtitle ? <span>{item.subtitle}</span> : null}
                    {item.source_label && item.source_label !== item.title && item.source_label !== item.subtitle ? (
                      <span className="task-source-label">· {item.source_label}</span>
                    ) : null}
                    {shouldShowTaskStep(item) ? (
                      <span className="task-step-inline">
                        <Activity size={10} strokeWidth={2.5} />
                        {item.current_step}
                      </span>
                    ) : null}
                  </div>

                  {showProgress(item) ? (
                    <div className="task-progress-row">
                      <div className="task-progress-track">
                        <span style={{ width: `${Math.max(0, Math.min(Number(item.progress || 0), 100))}%` }} />
                      </div>
                      <em>{Number(item.progress || 0)}%</em>
                    </div>
                  ) : null}

                  {recoveredNotice ? (
                    <div className="task-recovered-note">
                      <CheckCircle2 size={12} strokeWidth={2.4} />
                      <span>{recoveredNotice}</span>
                    </div>
                  ) : null}

                  {summary.length ? (
                    <div className="task-summary-strip">
                      {summary.map((piece, summaryIndex) => {
                        const SummaryIcon = summaryIcon(piece)
                        return (
                          <span key={`${id}-summary-${summaryIndex}`} title={extractSummaryLabel(piece) || piece}>
                            <SummaryIcon size={12} strokeWidth={2.4} />
                            {extractSummaryValue(piece)}
                          </span>
                        )
                      })}
                    </div>
                  ) : null}
                </div>
              </motion.button>
            )
          })}
        </div>
      ) : (
        <EmptyState title="没有任务" description="当前筛选条件下没有任务" />
      )}

      {totalItems > pageSize ? (
        <footer className="task-list-pagination">
          <IconButton title="上一页" disabled={currentOffset <= 0} onClick={onPrevPage}>
            <ChevronLeft size={15} strokeWidth={2.4} />
          </IconButton>
          <span>{pageIndex} / {totalPages}</span>
          <IconButton title="下一页" disabled={currentOffset + pageSize >= totalItems} onClick={onNextPage}>
            <ChevronRight size={15} strokeWidth={2.4} />
          </IconButton>
        </footer>
      ) : null}
    </aside>
  )
}
