import { ChevronDown, ChevronRight, File, FileText, Folder, ListFilter, Music, XCircle } from 'lucide-react'

function getTreeIcon(entry) {
  if (entry?.type === 'dir') return Folder
  const label = String(entry?.label || '').toLowerCase()
  if (/\.(wav|flac|mp3|m4a|ogg|aac|wma)$/.test(label)) return Music
  if (/\.(txt|md|json|cue|srt|ass|ssa|vtt|lrc)$/.test(label)) return FileText
  return File
}

function iconTone(entry) {
  if (entry?.status === 'removed') return 'removed'
  if (entry?.type === 'dir') return 'folder'
  const label = String(entry?.label || '').toLowerCase()
  if (/\.(wav|flac)$/.test(label)) return 'audio-lossless'
  if (/\.(mp3|m4a|ogg|aac|wma)$/.test(label)) return 'audio'
  if (/\.(txt|md|json|cue|srt|ass|ssa|vtt|lrc)$/.test(label)) return 'text'
  return 'file'
}

export function TaskFileTree({ sections = [], filterMode = 'all', onFilterModeChange, onExpandSection, onToggleNode }) {
  if (!sections.length) return null

  return (
    <>
      {sections.map(section => (
        <section className="task-detail-section" key={section.key}>
          <div className="task-section-title-row">
            <span className="task-section-title">文件列表</span>
            <div className="task-tree-actions">
              <button
                type="button"
                className={filterMode === 'all' || !section.removedCount ? 'is-active' : ''}
                onClick={() => onFilterModeChange?.('all')}
              >
                <ListFilter size={12} strokeWidth={2.4} />
                全部
              </button>
              {section.removedCount ? (
                <button
                  type="button"
                  className={filterMode === 'removed' ? 'is-active' : ''}
                  onClick={() => onFilterModeChange?.('removed')}
                >
                  <XCircle size={12} strokeWidth={2.4} />
                  被过滤
                </button>
              ) : null}
            </div>
          </div>

          <div className="task-tree-summary">
            <div>
              {section.totalCount ? <span>文件 {section.totalCount}</span> : null}
              {section.removedCount ? <span data-tone="danger">被过滤 {section.removedCount}</span> : null}
            </div>
            <button type="button" onClick={() => onExpandSection?.(section, !section.allExpanded)}>
              {section.allExpanded ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
              {section.allExpanded ? '收起全部' : '展开全部'}
            </button>
          </div>

          <div className="task-file-tree">
            {section.rows.map(row => {
              const Icon = getTreeIcon(row)
              return (
                <div
                  key={`${section.key}-${row.key}`}
                  className={`task-file-tree-row ${row.status === 'removed' ? 'is-removed' : ''}`}
                  style={{ paddingLeft: `${row.depth * 16 + 8}px` }}
                >
                  <div className="task-file-tree-main">
                    {row.hasChildren ? (
                      <button type="button" className="task-tree-expander" onClick={() => onToggleNode?.(row.pathKey)}>
                        {row.expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </button>
                    ) : (
                      <span className="task-tree-spacer" />
                    )}
                    <Icon className="task-file-tree-icon" data-tone={iconTone(row)} size={19} strokeWidth={2.2} />
                    <span className="task-file-tree-name">{row.label}</span>
                  </div>
                  {row.sizeText ? <span className="task-file-tree-size">{row.sizeText}</span> : null}
                </div>
              )
            })}
          </div>
        </section>
      ))}
    </>
  )
}
