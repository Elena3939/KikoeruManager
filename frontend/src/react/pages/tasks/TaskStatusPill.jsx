import { getStatusMeta } from './taskUtils'

export function TaskStatusPill({ status, label }) {
  const meta = getStatusMeta(status, label)
  const Icon = meta.icon
  return (
    <span className="task-status-pill" data-tone={meta.tone}>
      <Icon size={12} strokeWidth={2.4} />
      <span>{meta.label}</span>
    </span>
  )
}
