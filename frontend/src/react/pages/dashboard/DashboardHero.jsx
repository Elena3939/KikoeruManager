import { ArrowUpRight, House, RefreshCw, RotateCw } from 'lucide-react'
import { Button, PageHeader } from '../../components/Primitives'
import { DashboardFileUploader } from './DashboardFileUploader'

export function DashboardHero({ watcherRunning, loading, kpiCards, onRefresh, onKpiClick, onUploadSuccess }) {
  return (
    <header className="dashboard-hero" data-section="dashboard-hero">
      <PageHeader
        eyebrow="处理队列、入库入口和最近归档"
        title="概览"
        description="活跃任务、问题作品和归档记录会在这里持续刷新。"
        actions={(
          <>
            <span className="dashboard-watch-pill" data-on={watcherRunning ? 'true' : 'false'}>
              <i />
              {watcherRunning ? '监视中' : '已停止'}
            </span>
            <Button onClick={onRefresh} disabled={loading}>
              {loading ? <RefreshCw size={15} className="km-spin" /> : <RotateCw size={15} />}
              刷新
            </Button>
          </>
        )}
      />
      <div className="dashboard-hero-grid">
        <section className="dashboard-kpi-strip">
          {kpiCards.map((item, index) => {
            const Icon = item.icon || House
            return (
              <button
                type="button"
                key={item.key}
                className="dashboard-kpi"
                data-tone={item.key}
                style={{ animationDelay: `${index * 38}ms` }}
                onClick={() => onKpiClick?.(item)}
              >
                <span className="dashboard-kpi-icon"><Icon size={14} /></span>
                <b>{item.label}</b>
                <em>{item.value}</em>
                <ArrowUpRight size={13} className="dashboard-kpi-arrow" />
              </button>
            )
          })}
        </section>
        <DashboardFileUploader onUploadSuccess={onUploadSuccess} />
      </div>
    </header>
  )
}
