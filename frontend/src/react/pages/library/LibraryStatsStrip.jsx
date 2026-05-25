import { BarChart3, HardDrive, Layers, Loader2 } from 'lucide-react'
import { Button, Card } from '../../components/Primitives'
import { formatBytes, formatDateTime } from '../../utils/format'

export function LibraryStatsStrip({
  currentLibrary,
  currentStats,
  aggregateStats,
  statsLoading,
  canCancelStats,
  onStatsAction
}) {
  const remote = currentLibrary?.type === 'synology_filestation'
  return (
    <Card className="lib-info-strip">
      <InfoItem
        icon={<HardDrive size={16} />}
        label="当前库存"
        value={currentLibrary?.name || '-'}
        meta={remote ? '远程服务器库存' : '本地库存'}
        sub={currentLibrary?.path || currentLibrary?.root_path || '-'}
        tone={remote ? 'warning' : 'success'}
      />
      <InfoItem
        icon={statsLoading ? <Loader2 size={16} className="km-spin" /> : <BarChart3 size={16} />}
        label="当前库统计"
        value={statsSizeText(currentStats)}
        meta={statsStatusText(currentStats)}
        sub={currentStats?.last_completed_at ? `更新于 ${formatDateTime(currentStats.last_completed_at)}` : ''}
      />
      <InfoItem
        icon={<Layers size={16} />}
        label="全部库存"
        value={aggregateSizeText(aggregateStats)}
        meta={aggregateSummaryText(aggregateStats)}
        sub={aggregateStats?.last_completed_at ? `更新于 ${formatDateTime(aggregateStats.last_completed_at)}` : ''}
      />
      <div className="lib-info-actions">
        <Button size="sm" onClick={onStatsAction} loading={statsLoading}>
          {canCancelStats ? '取消统计' : '刷新统计'}
        </Button>
      </div>
    </Card>
  )
}

function InfoItem({ icon, label, value, meta, sub, tone = 'info' }) {
  return (
    <div className={`lib-info-item is-${tone}`}>
      <span className="lib-info-icon">{icon}</span>
      <div className="lib-info-body">
        <div className="lib-info-label">{label}</div>
        <div className="lib-info-value"><b>{value}</b>{meta ? <span> · {meta}</span> : null}</div>
        {sub ? <div className="lib-info-sub" title={sub}>{sub}</div> : null}
      </div>
    </div>
  )
}

function statsSizeText(stats) {
  if (!stats) return '-'
  const bytes = Number(stats.total_size_bytes ?? stats.total_size ?? 0)
  if (bytes > 0) return formatBytes(bytes)
  const gb = Number(stats.total_size_gb || 0)
  if (gb > 0) return `${gb.toFixed(gb >= 10 ? 1 : 2)} GB`
  return '0 B'
}

function statsStatusText(stats) {
  const status = String(stats?.status || '').trim()
  if (status === 'pending') return `统计中 ${Math.round(Number(stats?.progress_percent || 0))}%`
  if (status === 'ready') return `${Number(stats?.folder_count || 0).toLocaleString()} 个目录`
  if (status === 'error') return stats?.error || '统计失败'
  return `${Number(stats?.folder_count || 0).toLocaleString()} 个目录`
}

function aggregateSizeText(stats) {
  if (!stats) return '-'
  return statsSizeText(stats)
}

function aggregateSummaryText(stats) {
  if (!stats) return '等待统计'
  return `${Number(stats.folder_count || 0).toLocaleString()} 个目录`
}
