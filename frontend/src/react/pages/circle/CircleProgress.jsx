import { RefreshCw } from 'lucide-react'
import { Button } from '../../components/Primitives'
import { cx } from '../../utils/format'
import { getJobProgressPercent } from './circleUtils'

export function JobProgressCard({ title, job, statusText, meta = [], onCancel, cancelling = false, compact = false, children }) {
  const progress = getJobProgressPercent(job)
  return (
    <section className={cx('circle-job-card', compact && 'is-compact')}>
      <div className="circle-job-head">
        <div>
          <div className="circle-job-title">{title}</div>
          <div className="circle-job-subtitle">{job.circle_query || job.circle_name || '当前社团'} · {job.current_step || '处理中'}</div>
        </div>
        <div className="circle-job-actions">
          {onCancel ? <Button size="xs" loading={cancelling} onClick={onCancel}><RefreshCw size={12} />取消</Button> : null}
          <span className={cx('circle-job-status', job.status)}>{statusText}</span>
        </div>
      </div>
      <div className="circle-job-progress">
        <div style={{ width: `${progress}%` }} />
      </div>
      <div className="circle-job-meta">
        {meta.filter(Boolean).map(([tone, icon, text], index) => (
          <span key={`${tone}-${index}`} className={cx('circle-job-pill', tone)}>
            {icon}
            {text}
          </span>
        ))}
      </div>
      {job.error_message ? <div className="circle-job-error">{job.error_message}</div> : null}
      {children}
    </section>
  )
}
