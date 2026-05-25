import { useEffect, useMemo, useState } from 'react'
import {
  Check,
  Download,
  FileText,
  Folder,
  FolderOpen,
  PackageCheck,
  Settings2
} from 'lucide-react'
import { libraryApi } from '../../../api'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, Field, LoadingState, Modal, TextInput } from '../../components/Primitives'
import { cx, formatBytes } from '../../utils/format'

export function DownloadPreviewDialog({
  loading,
  starting,
  plans,
  libraries,
  targetSubdirOptions,
  settings,
  circleName,
  onSettingsChange,
  onClose,
  onSubmit
}) {
  const [planStates, setPlanStates] = useState([])

  useEffect(() => {
    setPlanStates(Array.isArray(plans) ? plans.map(buildPlanState) : [])
  }, [plans])

  const targetLibraries = useMemo(() => (libraries || []).filter(item => item?.enabled !== false), [libraries])
  const selectedLibrary = targetLibraries.find(item => String(item.id) === String(settings.targetLibraryId)) || null
  const selectedResources = useMemo(() => planStates.flatMap(plan => plan.resources.filter(item => item.selected)), [planStates])
  const selectableCount = useMemo(() => planStates.reduce((sum, plan) => sum + plan.resources.length, 0), [planStates])
  const selectedSize = useMemo(() => selectedResources.reduce((sum, item) => sum + Number(item.size_bytes || item.size || 0), 0), [selectedResources])
  const typeChips = useMemo(() => buildTypeChips(planStates), [planStates])
  const allSelectedState = selectedResources.length === 0 ? 'none' : selectedResources.length === selectableCount ? 'all' : 'partial'
  const finalPath = buildFinalPathPreview(selectedLibrary, settings, circleName)
  const canSubmit = selectedResources.length > 0 && !starting && Boolean(settings.targetLibraryId)

  function patchSettings(patch) {
    onSettingsChange(prev => ({ ...prev, ...patch }))
  }

  function updatePlanResource(planKey, resourceKey, selected) {
    setPlanStates(prev => prev.map(plan => {
      if (plan.key !== planKey) return plan
      return {
        ...plan,
        resources: plan.resources.map(item => item.key === resourceKey ? { ...item, selected } : item)
      }
    }))
  }

  function togglePlan(planKey) {
    setPlanStates(prev => prev.map(plan => {
      if (plan.key !== planKey) return plan
      const nextSelected = !plan.resources.every(item => item.selected)
      return { ...plan, resources: plan.resources.map(item => ({ ...item, selected: nextSelected })) }
    }))
  }

  function toggleAll() {
    const nextSelected = allSelectedState !== 'all'
    setPlanStates(prev => prev.map(plan => ({
      ...plan,
      resources: plan.resources.map(item => ({ ...item, selected: nextSelected }))
    })))
  }

  function toggleType(typeKey) {
    const chip = typeChips.find(item => item.key === typeKey)
    const nextSelected = chip?.selected !== chip?.total
    setPlanStates(prev => prev.map(plan => ({
      ...plan,
      resources: plan.resources.map(item => getResourceExtKey(item) === typeKey ? { ...item, selected: nextSelected } : item)
    })))
  }

  function submit() {
    const flattenFiles = Boolean(settings.flattenFiles)
    const namingMode = flattenFiles ? 'preserve' : (settings.namingMode === 'api' ? 'api' : 'preserve')
    const classifyMode = flattenFiles ? 'none' : (settings.classifyMode === 'circle' ? 'circle' : 'none')
    const targetSubdir = String(settings.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
    const useImmediateUpload = selectedLibrary?.type === 'synology_filestation' && String(settings.targetLibraryId || '').trim()
    const items = planStates
      .map(plan => {
        const rawSelected = plan.resources.filter(item => item.selected)
        const selected = flattenFiles
          ? rawSelected.map(item => ({
              ...item.raw,
              selected: true,
              relative_path: String(item.file_name || item.relative_path || '').split('/').pop().split('\\').pop()
            }))
          : rawSelected.map(item => ({ ...item.raw, selected: true }))
        if (!selected.length) return null
        return {
          session_id: plan.session_id,
          rjcode: plan.rjcode,
          canonical_rjcode: plan.canonical_rjcode,
          display_rjcodes: plan.display_rjcodes,
          work_title: plan.title,
          cover_url: plan.cover_url,
          image_url: plan.image_url,
          folder_path: plan.folder_path,
          selected_resources: selected,
          resource_filter_snapshot: {},
          verify_md5_after_download: true,
          download_base_path: settings.downloadBasePath || '',
          upload_options: {
            enabled: Boolean(useImmediateUpload),
            mode: useImmediateUpload ? 'synology' : 'disabled',
            target_path: '',
            library_id: useImmediateUpload ? String(settings.targetLibraryId || '') : ''
          },
          postprocess_options: {
            enabled: true,
            target_library_id: settings.targetLibraryId || '',
            target_subdir: targetSubdir,
            naming_mode: namingMode,
            classify_mode: classifyMode,
            flatten_files: flattenFiles,
            circle_name: circleName || ''
          }
        }
      })
      .filter(Boolean)

    onSubmit({
      items,
      batchOptions: {
        download_base_path: settings.downloadBasePath || '',
        target_library_id: settings.targetLibraryId || '',
        target_subdir: targetSubdir,
        naming_mode: namingMode,
        classify_mode: classifyMode,
        flatten_files: flattenFiles,
        mode: 'classify'
      }
    })
  }

  return (
    <Modal
      title="创建下载任务"
      width={1180}
      onClose={onClose}
      footer={(
        <>
          <div className="circle-preview-summary">
            <strong>{selectedResources.length}</strong>
            <span>已选 / {selectableCount}，共 {formatBytes(selectedSize)}</span>
          </div>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" loading={starting} disabled={!canSubmit} onClick={submit}>
            <Download size={15} />创建下载任务
          </Button>
        </>
      )}
    >
      {loading ? (
        <LoadingState label="正在分析资源结构并生成下载计划..." />
      ) : (
        <div className="circle-preview-dialog">
          <div className="circle-preview-chips">
            <button type="button" className={cx('circle-preview-chip', allSelectedState)} onClick={toggleAll}>
              全部 <span>{selectedResources.length}/{selectableCount}</span>
            </button>
            {typeChips.map(chip => (
              <button key={chip.key} type="button" className={cx('circle-preview-chip', chip.state)} onClick={() => toggleType(chip.key)}>
                {chip.label} <span>{chip.selected}/{chip.total}</span>
              </button>
            ))}
          </div>

          <div className="circle-preview-grid">
            <aside className="circle-preview-settings">
              <div className="circle-preview-section-title"><Settings2 size={14} />落地设置</div>
              <Field label="下载临时目录">
                <TextInput value={settings.downloadBasePath || ''} placeholder="留空使用默认临时路径" onChange={event => patchSettings({ downloadBasePath: event.target.value })} />
              </Field>
              <Field label="目标库存">
                <AppDropdown
                  value={settings.targetLibraryId || ''}
                  onChange={value => patchSettings({ targetLibraryId: value })}
                  options={targetLibraries.map(item => ({ value: String(item.id), label: item.name || item.id }))}
                  placeholder="选择库存"
                  width="100%"
                />
              </Field>
              <Field label="指定目录">
                <TextInput
                  list="circle-target-subdirs"
                  value={settings.targetSubdir || ''}
                  placeholder="可留空，默认按社团归类"
                  onChange={event => patchSettings({ targetSubdir: event.target.value })}
                />
                <datalist id="circle-target-subdirs">
                  {(targetSubdirOptions || []).map(item => <option key={item} value={item} />)}
                </datalist>
              </Field>
              <div className="circle-preview-toggle-grid">
                <button type="button" className={cx(settings.classifyMode === 'circle' && !settings.flattenFiles && 'is-active')} disabled={settings.flattenFiles} onClick={() => patchSettings({ classifyMode: settings.classifyMode === 'circle' ? 'none' : 'circle' })}>按社团归类</button>
                <button type="button" className={cx(settings.namingMode === 'api' && !settings.flattenFiles && 'is-active')} disabled={settings.flattenFiles} onClick={() => patchSettings({ namingMode: settings.namingMode === 'api' ? 'preserve' : 'api' })}>API 命名</button>
                <button type="button" className={cx(settings.flattenFiles && 'is-active')} onClick={() => patchSettings({ flattenFiles: !settings.flattenFiles })}>直放目录</button>
              </div>
              <div className="circle-preview-final-path">
                <span>最终路径</span>
                <strong>{finalPath || '-'}</strong>
              </div>
            </aside>

            <section className="circle-preview-plan-list">
              {planStates.map(plan => {
                const selectedCount = plan.resources.filter(item => item.selected).length
                return (
                  <article key={plan.key} className="circle-preview-plan-card">
                    <header>
                      <button type="button" className={cx('circle-check', selectedCount === plan.resources.length && 'is-checked', selectedCount > 0 && selectedCount < plan.resources.length && 'is-partial')} onClick={() => togglePlan(plan.key)}>
                        {selectedCount ? <Check size={13} /> : null}
                      </button>
                      <div>
                        <h3>{plan.title || plan.rjcode}</h3>
                        <p>{plan.requested_rjcode || plan.canonical_rjcode} → {plan.rjcode}</p>
                      </div>
                      <span>{selectedCount}/{plan.resources.length}</span>
                    </header>
                    <div className="circle-preview-resource-list">
                      {plan.resources.map(resource => (
                        <button key={resource.key} type="button" className={cx('circle-preview-resource-row', resource.selected && 'is-selected')} onClick={() => updatePlanResource(plan.key, resource.key, !resource.selected)}>
                          <span className={cx('circle-check', resource.selected && 'is-checked')}>{resource.selected ? <Check size={12} /> : null}</span>
                          <FileText size={14} />
                          <strong title={resource.relative_path}>{resource.relative_path || resource.file_name || '未命名资源'}</strong>
                          <em>{formatBytes(resource.size_bytes || resource.size || 0)}</em>
                        </button>
                      ))}
                      {!plan.resources.length ? <div className="circle-preview-empty">没有可下载资源</div> : null}
                    </div>
                  </article>
                )
              })}
              {!planStates.length ? <div className="circle-preview-empty">没有生成可下载计划</div> : null}
            </section>
          </div>
        </div>
      )}
    </Modal>
  )
}

export function LocalUploadDialog({
  title = '直接入库',
  sources,
  libraries,
  form,
  starting,
  circleName,
  onFormChange,
  onClose,
  onSubmit
}) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedPaths, setSelectedPaths] = useState(() => new Set())
  const targetLibraries = useMemo(() => (libraries || []).filter(item => item?.enabled !== false), [libraries])
  const selectedRows = rows.filter(row => row.type === 'dir' && selectedPaths.has(row.path))
  const selectedSize = selectedRows.reduce((sum, row) => sum + Number(row.size_bytes || 0), 0)
  const canSubmit = selectedRows.length > 0 && !starting && Boolean(form.targetLibraryId)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const nextRows = []
      for (const source of sources || []) {
        const rootPath = String(source?.path || '').trim()
        if (!rootPath) continue
        nextRows.push({
          id: rootPath,
          path: rootPath,
          name: source?.name || rootPath.split(/[\\/]/).filter(Boolean).pop() || rootPath,
          type: 'dir',
          depth: 0,
          size_bytes: 0,
          sourceName: source?.circle_name || circleName || ''
        })
        try {
          const data = await libraryApi.folderContents(rootPath)
          const items = Array.isArray(data?.items) ? data.items : (Array.isArray(data?.files) ? data.files : [])
          items.forEach((item, index) => {
            const isDir = Boolean(item.is_directory || item.isdir || item.type === 'dir')
            nextRows.push({
              id: `${rootPath}:${item.path || item.real_path || item.name || index}`,
              path: item.path || item.real_path || '',
              name: item.name || item.relative_path || '',
              type: isDir ? 'dir' : 'file',
              depth: 1,
              size_bytes: Number(item.size || item.size_bytes || 0),
              sourceName: source?.circle_name || circleName || ''
            })
          })
        } catch (_) {}
      }
      if (cancelled) return
      setRows(nextRows)
      setSelectedPaths(new Set(nextRows.filter(row => row.type === 'dir' && row.depth === 0).map(row => row.path)))
      setLoading(false)
    }
    load()
    return () => { cancelled = true }
  }, [sources, circleName])

  function patchForm(patch) {
    onFormChange(prev => ({ ...prev, ...patch }))
  }

  function toggleRow(row) {
    if (row.type !== 'dir') return
    setSelectedPaths(prev => {
      const next = new Set(prev)
      if (next.has(row.path)) next.delete(row.path)
      else next.add(row.path)
      return next
    })
  }

  function toggleAll() {
    const dirPaths = rows.filter(row => row.type === 'dir').map(row => row.path)
    setSelectedPaths(prev => prev.size === dirPaths.length ? new Set() : new Set(dirPaths))
  }

  function submit() {
    onSubmit({
      selected_paths: selectedRows.map(row => row.path),
      target_library_id: form.targetLibraryId || '',
      target_subdir: form.targetSubdir || ''
    })
  }

  return (
    <Modal
      title={title}
      width={920}
      onClose={onClose}
      footer={(
        <>
          <div className="circle-preview-summary">
            <strong>{selectedRows.length}</strong>
            <span>已选目录，共 {formatBytes(selectedSize)}</span>
          </div>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" loading={starting} disabled={!canSubmit} onClick={submit}>
            <PackageCheck size={15} />开始入库
          </Button>
        </>
      )}
    >
      <div className="circle-upload-dialog">
        <aside className="circle-upload-settings">
          <Field label="目标库存">
            <AppDropdown
              value={form.targetLibraryId || ''}
              onChange={value => patchForm({ targetLibraryId: value })}
              options={targetLibraries.map(item => ({ value: String(item.id), label: item.name || item.id }))}
              placeholder="选择目标库存"
              width="100%"
            />
          </Field>
          <Field label="目标子目录">
            <TextInput value={form.targetSubdir || ''} placeholder="可留空" onChange={event => patchForm({ targetSubdir: event.target.value })} />
          </Field>
          <div className="circle-preview-final-path">
            <span>社团</span>
            <strong>{circleName || '当前社团'}</strong>
          </div>
        </aside>
        <section className="circle-upload-tree">
          <div className="circle-upload-tree-head">
            <button type="button" className={cx('circle-preview-chip', selectedRows.length ? 'partial' : 'none')} onClick={toggleAll}>
              全选目录 <span>{selectedRows.length}/{rows.filter(row => row.type === 'dir').length}</span>
            </button>
          </div>
          {loading ? <LoadingState label="正在读取下载目录..." /> : null}
          {!loading ? rows.map(row => (
            <button key={row.id} type="button" className={cx('circle-upload-row', row.type !== 'dir' && 'is-file', selectedPaths.has(row.path) && 'is-selected')} style={{ paddingLeft: 12 + row.depth * 18 }} onClick={() => toggleRow(row)}>
              <span className={cx('circle-check', selectedPaths.has(row.path) && 'is-checked')}>{selectedPaths.has(row.path) ? <Check size={12} /> : null}</span>
              {row.type === 'dir' ? <FolderOpen size={15} /> : <FileText size={15} />}
              <strong title={row.path}>{row.name || row.path}</strong>
              <em>{row.type === 'dir' ? '目录' : formatBytes(row.size_bytes || 0)}</em>
            </button>
          )) : null}
          {!loading && !rows.length ? <div className="circle-preview-empty"><Folder size={24} />没有可入库目录</div> : null}
        </section>
      </div>
    </Modal>
  )
}

function buildPlanState(plan, index) {
  const resources = (Array.isArray(plan?.selectable_resources) ? plan.selectable_resources : []).map((item, resourceIndex) => normalizeResource(item, resourceIndex))
  return {
    key: `${plan?.session_id || plan?.rjcode || index}`,
    session_id: plan?.session_id || '',
    rjcode: plan?.resolved_rjcode || plan?.rjcode || '',
    canonical_rjcode: plan?.canonical_rjcode || plan?.rjcode || '',
    requested_rjcode: plan?.requested_rjcode || '',
    display_rjcodes: Array.isArray(plan?.display_rjcodes) ? plan.display_rjcodes : [],
    title: plan?.title || plan?.work_info?.title || plan?.source_label || '',
    cover_url: plan?.cover_url || plan?.image_url || '',
    image_url: plan?.image_url || plan?.cover_url || '',
    folder_path: plan?.folder_path || '',
    resources
  }
}

function normalizeResource(item, index) {
  const relativePath = String(item?.relative_path || item?.path || item?.file_name || item?.name || '').trim()
  const fileName = String(item?.file_name || relativePath.split('/').pop().split('\\').pop() || '').trim()
  return {
    ...item,
    key: `${relativePath || fileName || index}`,
    relative_path: relativePath,
    file_name: fileName,
    size_bytes: Number(item?.size_bytes || item?.size || 0),
    selected: item?.selected !== false,
    raw: { ...item, selected: item?.selected !== false }
  }
}

function buildTypeChips(plans) {
  const groups = new Map()
  plans.flatMap(plan => plan.resources).forEach(item => {
    const key = getResourceExtKey(item)
    const current = groups.get(key) || { key, label: getResourceTypeLabel(item), total: 0, selected: 0 }
    current.total += 1
    if (item.selected) current.selected += 1
    groups.set(key, current)
  })
  return [...groups.values()]
    .map(item => ({ ...item, state: item.selected === 0 ? 'none' : item.selected === item.total ? 'all' : 'partial' }))
    .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
}

function getResourceExtKey(item) {
  const name = String(item?.relative_path || item?.file_name || '').toLowerCase()
  const match = name.match(/(\.[a-z0-9]+)$/)
  return match ? match[1] : '__no_ext__'
}

function getResourceTypeLabel(item) {
  const ext = getResourceExtKey(item)
  if (ext === '__no_ext__') return '无扩展名'
  return ext.replace('.', '').toUpperCase()
}

function buildFinalPathPreview(library, settings, circleName) {
  const base = String(library?.root_path || library?.path || '').trim()
  if (!base) return ''
  const sep = base.includes('/') ? '/' : '\\'
  const parts = [base]
  const subdir = String(settings.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  if (subdir) parts.push(subdir.replace(/[\\/]+/g, sep))
  if (settings.flattenFiles) return parts.join(sep)
  if (settings.classifyMode === 'circle') parts.push(String(circleName || '').trim() || '{社团名}')
  parts.push(settings.namingMode === 'api' ? '{API命名作品目录}' : '{作品目录}')
  return parts.join(sep)
}
