import { useMemo, useState } from 'react'
import {
  ArrowRight,
  ChevronDown,
  Clipboard,
  Code2,
  Copy,
  Database,
  FileText,
  GitBranch,
  Layers,
  X
} from 'lucide-react'
import { motion } from 'motion/react'
import { Button, IconButton, LoadingState } from '../../components/Primitives'
import {
  childRows,
  compactPath,
  detailHighlights,
  displayRjcode,
  displaySummary,
  effectiveStatus,
  entryIcon,
  entryLabel,
  entryMeta,
  fileSections,
  formatFullDateTime,
  getCategoryConfig,
  getStatusConfig,
  humanAction,
  safeDetail,
  splitMetric,
  stringifyDetail
} from './activityUtils'

export function ActivityDetailDrawer({ row, loading, onClose, onOpenRow }) {
  const [rawOpen, setRawOpen] = useState(false)
  const [childrenOpen, setChildrenOpen] = useState(true)
  const [openSections, setOpenSections] = useState(() => new Set(['download_files', 'upload_files', 'uploaded_files', 'entries', 'files']))

  const status = effectiveStatus(row)
  const category = getCategoryConfig(row?.category)
  const statusConfig = getStatusConfig(status)
  const CategoryIcon = category.icon
  const StatusIcon = statusConfig.icon
  const highlights = useMemo(() => detailHighlights(row), [row])
  const children = useMemo(() => childRows(row), [row])
  const sections = useMemo(() => fileSections(row), [row])
  const detail = safeDetail(row)
  const rawDetail = useMemo(() => stringifyDetail(detail), [detail])

  function toggleSection(key) {
    setOpenSections(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function copyText(value) {
    const text = String(value || '').trim()
    if (!text) return
    try {
      await navigator.clipboard?.writeText(text)
    } catch {
      const textarea = document.createElement('textarea')
      textarea.value = text
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
  }

  return (
    <div className="activity-drawer-layer">
      <button type="button" className="activity-drawer-backdrop" aria-label="关闭详情" onClick={onClose} />
      <motion.aside
        className="activity-detail-drawer glass-panel"
        initial={{ x: 42, opacity: 0, filter: 'blur(8px)' }}
        animate={{ x: 0, opacity: 1, filter: 'blur(0px)' }}
        exit={{ x: 28, opacity: 0, filter: 'blur(6px)' }}
        transition={{ type: 'spring', stiffness: 380, damping: 36 }}
      >
        <header className="activity-detail-head">
          <div className={`activity-detail-icon tone-${statusConfig.tone}`}>
            {CategoryIcon ? <CategoryIcon size={19} strokeWidth={2.5} /> : null}
          </div>
          <div className="activity-detail-title-block">
            <div className="activity-detail-eyebrow">
              <span>{category.label}</span>
              {row?.compacted ? <em>已归档</em> : null}
              {row?.__isLite || loading ? <em>详情加载中</em> : null}
            </div>
            <h2>{row ? humanAction(row) : '-'}</h2>
            <div className="activity-detail-subtitle">
              <span className={`activity-status-chip tone-${statusConfig.tone}`}>
                <StatusIcon size={12} strokeWidth={2.6} />
                {statusConfig.label}
              </span>
              {displayRjcode(row) ? <span className="activity-rj-chip">{displayRjcode(row)}</span> : null}
              {row?.created_at ? <time>{formatFullDateTime(row.created_at)}</time> : null}
            </div>
          </div>
          <IconButton title="关闭" className="activity-detail-close" onClick={onClose}>
            <X size={17} strokeWidth={2.6} />
          </IconButton>
        </header>

        <div className="activity-detail-scroll">
          {loading && !row?.detail ? <LoadingState label="正在加载详情..." /> : null}

          {row?.summary ? (
            <section className="activity-detail-section">
              <SectionTitle icon={FileText} title="摘要" />
              <p className="activity-summary-text">{displaySummary(row)}</p>
            </section>
          ) : null}

          {highlights.length ? (
            <section className="activity-detail-section">
              <SectionTitle icon={Layers} title={`关键字段 · ${highlights.length}`} />
              <dl className="activity-highlight-grid">
                {highlights.map(item => {
                  const metric = splitMetric(item.value)
                  return (
                    <div key={item.key} className="activity-highlight-row">
                      <dt>{item.label}</dt>
                      <dd>
                        <span>{metric.num}</span>
                        {metric.unit ? <em>{metric.unit}</em> : null}
                      </dd>
                    </div>
                  )
                })}
              </dl>
            </section>
          ) : null}

          <section className="activity-detail-section">
            <SectionTitle icon={Database} title="元数据" />
            <dl className="activity-meta-grid">
              <MetaRow label="记录 ID" value={row?.id} mono onCopy={copyText} />
              <MetaRow label="任务 ID" value={row?.task_id} mono onCopy={copyText} />
              <MetaRow label="批次" value={row?.batch_id} mono onCopy={copyText} />
              <MetaRow label="Session" value={row?.session_key} mono onCopy={copyText} />
              <MetaRow label="源路径" value={row?.source_path || detail.source_path || detail.archive_path || detail.folder_path} mono path onCopy={copyText} />
              <MetaRow label="输出路径" value={detail.output_path || detail.target_path || detail.final_output_path} mono path onCopy={copyText} />
            </dl>
          </section>

          {children.length ? (
            <section className="activity-detail-section">
              <button type="button" className="activity-section-toggle" onClick={() => setChildrenOpen(value => !value)}>
                <SectionTitle icon={GitBranch} title={`关联事件 · ${children.length}`} compact />
                <ChevronDown size={15} className={childrenOpen ? 'is-open' : ''} />
              </button>
              {childrenOpen ? (
                <div className="activity-child-list">
                  {children.slice(0, 120).map(child => {
                    const childStatus = effectiveStatus(child)
                    const childStatusConfig = getStatusConfig(childStatus)
                    return (
                      <article key={child.id || `${child.relation}-${child.created_at}-${child.action}`} className={`activity-child-row tone-${childStatusConfig.tone}`}>
                        <i />
                        <div>
                          <strong>{humanAction(child) || child.relation || child.action || '关联事件'}</strong>
                          <p>{displaySummary(child)}</p>
                          <span>{formatFullDateTime(child.created_at)}</span>
                        </div>
                        {child.id && child.id !== row?.id ? (
                          <button type="button" title="打开该事件" onClick={() => onOpenRow?.(child.id)}>
                            <ArrowRight size={14} />
                          </button>
                        ) : null}
                      </article>
                    )
                  })}
                  {children.length > 120 ? <div className="activity-more-note">还有 {children.length - 120} 条关联事件已折叠</div> : null}
                </div>
              ) : null}
            </section>
          ) : null}

          {sections.map(section => (
            <section className="activity-detail-section" key={section.key}>
              <button type="button" className="activity-section-toggle" onClick={() => toggleSection(section.key)}>
                <SectionTitle icon={Clipboard} title={`${section.title} · ${section.rows.length}`} compact />
                <ChevronDown size={15} className={openSections.has(section.key) ? 'is-open' : ''} />
              </button>
              {openSections.has(section.key) ? <ActivityEntryList rows={section.rows} /> : null}
            </section>
          ))}

          {rawDetail ? (
            <section className="activity-detail-section">
              <button type="button" className="activity-section-toggle" onClick={() => setRawOpen(value => !value)}>
                <SectionTitle icon={Code2} title={`原始 detail JSON · ${rawDetail.split('\n').length} 行`} compact />
                <ChevronDown size={15} className={rawOpen ? 'is-open' : ''} />
              </button>
              {rawOpen ? <pre className="activity-raw-json">{rawDetail}</pre> : null}
            </section>
          ) : null}
        </div>

        <footer className="activity-detail-foot">
          {row?.task_id ? (
            <Button onClick={() => copyText(row.task_id)}>
              <Copy size={14} />
              复制任务 ID
            </Button>
          ) : null}
          <Button variant="primary" onClick={onClose}>关闭</Button>
        </footer>
      </motion.aside>
    </div>
  )
}

function SectionTitle({ icon: Icon, title, compact = false }) {
  return (
    <div className={`activity-section-title ${compact ? 'is-compact' : ''}`}>
      {Icon ? <Icon size={14} strokeWidth={2.4} /> : null}
      <span>{title}</span>
    </div>
  )
}

function MetaRow({ label, value, mono, path, onCopy }) {
  const text = String(value || '').trim()
  if (!text) return null
  return (
    <div className="activity-meta-row">
      <dt>{label}</dt>
      <dd className={mono ? 'is-mono' : ''} title={text}>
        {path ? compactPath(text, 26, 54) : text}
        <button type="button" title="复制" onClick={() => onCopy?.(text)}>
          <Copy size={11} strokeWidth={2.6} />
        </button>
      </dd>
    </div>
  )
}

function ActivityEntryList({ rows }) {
  return (
    <div className="activity-entry-list">
      {rows.map((item, index) => {
        const Icon = entryIcon(item)
        const label = entryLabel(item)
        const meta = entryMeta(item)
        return (
          <div className="activity-entry-row" key={`${label}-${index}`}>
            <Icon size={15} strokeWidth={2.2} />
            <div>
              <strong title={label}>{label}</strong>
              {meta ? <span title={meta}>{meta}</span> : null}
            </div>
          </div>
        )
      })}
    </div>
  )
}
