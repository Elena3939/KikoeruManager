import { ArrowRight, MoreVertical, PauseCircle, RotateCw, XCircle } from 'lucide-react'
import { Button, EmptyState } from '../../components/Primitives'
import {
  actionLabels,
  formatRJCode,
  getDomainMeta,
  getStatusMeta,
  getTaskActions,
  getTaskId,
  getTaskSummary,
  getTaskTitle,
  shouldShowTaskStep,
  showProgress
} from '../tasks/taskUtils'
import { TaskStatusPill } from '../tasks/TaskStatusPill'

const statusIcons = {
  processing: RotateCw,
  waiting: PauseCircle,
  retry: RotateCw,
  failed: XCircle
}

export function DashboardActiveTasks({ tasks, statusCards, onGo, onAction }) {
  return (
    <section className="dashboard-task-panel" data-section="dashboard-tasks">
      <header className="dashboard-panel-head">
        <div>
          <h2>任务流</h2>
          <p>活跃任务优先，空闲时展示最近完成 / 失败</p>
        </div>
        <Button size="xs" onClick={() => onGo('/tasks')}>
          查看全部
          <ArrowRight size={13} />
        </Button>
      </header>

      {statusCards.length ? (
        <div className="dashboard-status-grid">
          {statusCards.map(item => {
            const Icon = statusIcons[item.key] || RotateCw
            return (
              <button type="button" key={item.key} data-tone={item.key} onClick={() => onGo('/tasks')}>
                <span><Icon size={13} /></span>
                <b>{item.label}</b>
                <em>{item.value}</em>
              </button>
            )
          })}
        </div>
      ) : null}

      {tasks.length ? (
        <div className="dashboard-task-list">
          {tasks.map((task, index) => {
            const domainMeta = getDomainMeta(task.domain)
            const statusMeta = getStatusMeta(task.status, task.status_label)
            const Icon = domainMeta.icon
            const actions = getTaskActions(task)
            return (
              <article
                className="dashboard-task-card"
                data-tone={domainMeta.tone}
                key={getTaskId(task) || `${task.title}-${index}`}
                style={{ animationDelay: `${index * 34}ms` }}
              >
                <span className="dashboard-task-icon"><Icon size={16} /></span>
                <div className="dashboard-task-main">
                  <div className="dashboard-task-title">
                    <strong>{getTaskTitle(task)}</strong>
                    <TaskStatusPill status={task.status} label={statusMeta.label} />
                  </div>
                  <div className="dashboard-task-meta">
                    <span>{domainMeta.label}</span>
                    {formatRJCode(task.rjcode) ? <b>{formatRJCode(task.rjcode)}</b> : null}
                    {getTaskSummary(task).map(part => <span key={part}>{part}</span>)}
                  </div>
                  {shouldShowTaskStep(task) ? <p>{task.current_step}</p> : null}
                  {showProgress(task) ? (
                    <div className="dashboard-task-progress">
                      <span><i style={{ width: `${Math.max(0, Math.min(100, Number(task.progress || 0)))}%` }} /></span>
                      <em>{Math.round(Number(task.progress || 0))}%</em>
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  className="dashboard-task-action"
                  disabled={!actions.length}
                  title={actions.length ? actionLabels[actions[0]] || actions[0] : '暂无可用动作'}
                  onClick={() => actions.length && onAction(task, actions[0])}
                >
                  <MoreVertical size={14} />
                </button>
              </article>
            )
          })}
        </div>
      ) : (
        <EmptyState title="当前没有需要关注的任务" description="新任务开始后会自动出现在这里。" />
      )}
    </section>
  )
}
