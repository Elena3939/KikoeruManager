export function TasksMetricsBar({ metrics = [], onFilter }) {
  return (
    <section className="tasks-metrics" aria-label="任务状态摘要">
      {metrics.map((metric, index) => (
        <button
          key={metric.key}
          type="button"
          className="tasks-metric-pill"
          data-tone={metric.tone || metric.key}
          style={{ animationDelay: `${index * 35}ms` }}
          onClick={() => onFilter?.(metric.domain || 'all', metric.status || 'all')}
        >
          <span className="tasks-metric-dot" />
          <span className="tasks-metric-label">{metric.label}</span>
          <span className="tasks-metric-count">{metric.value}</span>
        </button>
      ))}
    </section>
  )
}
