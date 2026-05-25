import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertCircle,
  Captions,
  Check,
  CheckCircle2,
  ChevronRight,
  ChevronsDown,
  ChevronsUp,
  Clock3,
  Database,
  FileText,
  Folder,
  FolderOpen,
  Info,
  Link2,
  ListOrdered,
  Music,
  Pencil,
  RefreshCcw,
  Trash2,
  Wand2,
  X
} from 'lucide-react'
import { libraryApi, rjSubtitleApi } from '../../../api'
import { Button, LoadingState, Modal, TextInput } from '../../components/Primitives'
import { showSystemAlert, showSystemConfirm, showSystemPrompt } from '../../stores/systemPromptStore'
import { formatBytes, formatDateTime, normalizeListPayload } from '../../utils/format'
import { extractRJCode, itemName, normalizePath, parentPath } from './libraryUtils'

const AUDIO_RE = /\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i
const SUBTITLE_RE = /\.(srt|ass|ssa|vtt|lrc|txt)$/i
const filterModes = [
  ['all', '全部'],
  ['paired', '已配对'],
  ['unpaired', '未配对']
]

export function LibrarySubtitleInspectorWorkbench({
  visible,
  task,
  fallbackLibraryId = '',
  onClose,
  onTaskMutated
}) {
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [audioItems, setAudioItems] = useState([])
  const [subtitleItems, setSubtitleItems] = useState([])
  const [info, setInfo] = useState(null)
  const [expandedIds, setExpandedIds] = useState(new Set())
  const [selectedTreeIds, setSelectedTreeIds] = useState(new Set())
  const [lastSelectedTreeId, setLastSelectedTreeId] = useState('')
  const [treeSearch, setTreeSearch] = useState('')
  const [audioSearch, setAudioSearch] = useState('')
  const [subtitleSearch, setSubtitleSearch] = useState('')
  const [audioFilter, setAudioFilter] = useState('all')
  const [subtitleFilter, setSubtitleFilter] = useState('all')
  const [namingStrategy, setNamingStrategy] = useState('audio')
  const [sequenceMode, setSequenceMode] = useState(false)
  const [sequenceSelection, setSequenceSelection] = useState({ audioPaths: [], subtitlePaths: [] })
  const [matchSelection, setMatchSelection] = useState({ audioPath: '', subtitlePath: '' })
  const [pairs, setPairs] = useState([])
  const [selectedPairId, setSelectedPairId] = useState('')
  const [contextOpen, setContextOpen] = useState(true)

  const audioLibraryId = info?.audioLibraryId || task?.library_id || fallbackLibraryId
  const subtitleLibraryId = info?.subtitleLibraryId || task?.subtitle_library_id || task?.library_id || fallbackLibraryId
  const subtitleDir = info?.subtitleDir || task?.subtitle_dir || ''
  const folderPath = info?.folderPath || task?.folder_path || task?.source_path || ''
  const taskLogs = useMemo(() => normalizeProgressLogs(task), [task])

  const audioFiles = useMemo(
    () => audioItems.filter(item => AUDIO_RE.test(item.name || item.path || '') && !isSubtitleRelativePath(item.relative_path || item.name)),
    [audioItems]
  )
  const subtitleFiles = useMemo(
    () => subtitleItems.filter(item => SUBTITLE_RE.test(item.name || item.path || '')),
    [subtitleItems]
  )
  const pairedAudioPaths = useMemo(() => new Set(pairs.map(pair => pair.audio_path)), [pairs])
  const pairedSubtitlePaths = useMemo(() => new Set(pairs.map(pair => pair.subtitle_path)), [pairs])
  const filteredAudioFiles = useMemo(
    () => filterPairingList(audioFiles, audioSearch, audioFilter, item => pairedAudioPaths.has(item.path)),
    [audioFiles, audioSearch, audioFilter, pairedAudioPaths]
  )
  const filteredSubtitleFiles = useMemo(
    () => filterPairingList(subtitleFiles, subtitleSearch, subtitleFilter, item => pairedSubtitlePaths.has(item.path)),
    [subtitleFiles, subtitleSearch, subtitleFilter, pairedSubtitlePaths]
  )
  const treeRoot = useMemo(() => buildTree(subtitleItems), [subtitleItems])
  const filteredTreeRoot = useMemo(
    () => treeSearch.trim() ? filterTree(treeRoot, treeSearch.trim().toLowerCase()) : treeRoot,
    [treeRoot, treeSearch]
  )
  const flatTree = useMemo(() => flattenTree(filteredTreeRoot, 0, expandedIds), [filteredTreeRoot, expandedIds])
  const selectableTreeRows = useMemo(() => flatTree.filter(row => row.type === 'dir' || row.type === 'file'), [flatTree])
  const selectedTreeRows = useMemo(() => flatTree.filter(row => selectedTreeIds.has(row.id)), [flatTree, selectedTreeIds])
  const allTreeSelected = selectableTreeRows.length > 0 && selectableTreeRows.every(row => selectedTreeIds.has(row.id))
  const canAddPair = Boolean(matchSelection.audioPath && matchSelection.subtitlePath)
  const totalSubtitleSize = subtitleItems.reduce((sum, item) => sum + Number(item.size || 0), 0)
  const selectedPair = useMemo(() => pairs.find(pair => pair.id === selectedPairId) || null, [pairs, selectedPairId])
  const sequenceReady = sequenceSelection.audioPaths.length > 0 && sequenceSelection.audioPaths.length === sequenceSelection.subtitlePaths.length

  useEffect(() => {
    if (!visible || !task) return
    reload()
  }, [visible, task?.id, task?.subtitle_dir])

  useEffect(() => {
    setPairs(current => current.map(pair => ({
      ...pair,
      ...buildSubtitlePairTargets(
        { name: pair.audio_name },
        { name: pair.subtitle_name },
        namingStrategy
      )
    })))
  }, [namingStrategy])

  if (!visible) return null

  async function reload() {
    if (!task?.subtitle_dir) {
      await showSystemAlert({ title: '当前任务还没有字幕目录', tone: 'warning' })
      return
    }
    const nextAudioLibraryId = task.library_id || fallbackLibraryId
    const nextSubtitleLibraryId = task.subtitle_library_id || nextAudioLibraryId
    if (!nextAudioLibraryId || !nextSubtitleLibraryId || !task.folder_path) {
      await showSystemAlert({ title: '任务缺少库存或音频目录信息', tone: 'warning' })
      return
    }
    setLoading(true)
    try {
      const [subtitleData, audioData] = await Promise.all([
        libraryApi.browserFolderContents(nextSubtitleLibraryId, task.subtitle_dir),
        libraryApi.browserFolderContents(nextAudioLibraryId, task.folder_path)
      ])
      const nextSubtitleItems = normalizeListPayload(subtitleData)
      const nextAudioItems = normalizeListPayload(audioData)
      setSubtitleItems(nextSubtitleItems)
      setAudioItems(nextAudioItems)
      const root = buildTree(nextSubtitleItems)
      setExpandedIds(new Set(root.filter(node => node.type === 'dir').map(node => node.id)))
      setSelectedTreeIds(new Set())
      setLastSelectedTreeId('')
      setTreeSearch('')
      setAudioSearch('')
      setSubtitleSearch('')
      setAudioFilter('all')
      setSubtitleFilter('all')
      setMatchSelection({ audioPath: '', subtitlePath: '' })
      setSequenceMode(false)
      setSequenceSelection({ audioPaths: [], subtitlePaths: [] })
      setInfo({
        taskId: task.id,
        libraryId: nextAudioLibraryId,
        audioLibraryId: nextAudioLibraryId,
        subtitleLibraryId: nextSubtitleLibraryId,
        folderPath: task.folder_path || '',
        subtitleDir: subtitleData?.folder_path || task.subtitle_dir,
        totalFiles: Number(subtitleData?.total_files || nextSubtitleItems.length),
        totalSize: nextSubtitleItems.reduce((sum, item) => sum + Number(item.size || 0), 0)
      })
      const autoPairs = buildAutoPairs(
        nextAudioItems.filter(item => AUDIO_RE.test(item.name || item.path || '') && !isSubtitleRelativePath(item.relative_path || item.name)),
        nextSubtitleItems.filter(item => SUBTITLE_RE.test(item.name || item.path || '')),
        namingStrategy
      )
      setPairs(autoPairs)
      setSelectedPairId(autoPairs[0]?.id || '')
    } finally {
      setLoading(false)
    }
  }

  function toggleTreeExpand(row) {
    if (row?.type !== 'dir') return
    setExpandedIds(prev => {
      const next = new Set(prev)
      next.has(row.id) ? next.delete(row.id) : next.add(row.id)
      return next
    })
  }

  function expandAllTree() {
    const next = new Set()
    const walk = nodes => nodes.forEach(node => {
      if (node.type === 'dir') {
        next.add(node.id)
        walk(node.children || [])
      }
    })
    walk(filteredTreeRoot)
    setExpandedIds(next)
  }

  function collapseAllTree() {
    setExpandedIds(new Set())
  }

  function toggleTreeRow(row, event) {
    if (!row?.id || busy) return
    if (event?.shiftKey && lastSelectedTreeId) {
      const ids = selectableTreeRows.map(item => item.id)
      const targetIndex = ids.indexOf(row.id)
      const anchorIndex = ids.indexOf(lastSelectedTreeId)
      if (targetIndex >= 0 && anchorIndex >= 0) {
        const [start, end] = targetIndex > anchorIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex]
        setSelectedTreeIds(prev => {
          const next = new Set(prev)
          ids.slice(start, end + 1).forEach(id => next.add(id))
          return next
        })
        setLastSelectedTreeId(row.id)
        return
      }
    }
    setSelectedTreeIds(prev => {
      const additive = event?.ctrlKey || event?.metaKey || event?.target?.type === 'checkbox'
      const next = new Set(additive ? prev : [])
      next.has(row.id) ? next.delete(row.id) : next.add(row.id)
      return next
    })
    setLastSelectedTreeId(row.id)
  }

  function toggleAllTreeRows() {
    setSelectedTreeIds(allTreeSelected ? new Set() : new Set(selectableTreeRows.map(row => row.id)))
    setLastSelectedTreeId(allTreeSelected ? '' : selectableTreeRows.at(-1)?.id || '')
  }

  function selectAudio(audio) {
    if (sequenceMode) {
      setSequenceSelection(prev => toggleSequencePath(prev, 'audioPaths', audio.path))
      return
    }
    setMatchSelection(prev => ({ ...prev, audioPath: audio.path }))
  }

  function selectSubtitle(subtitle) {
    if (sequenceMode) {
      setSequenceSelection(prev => toggleSequencePath(prev, 'subtitlePaths', subtitle.path))
      return
    }
    setMatchSelection(prev => ({ ...prev, subtitlePath: subtitle.path }))
  }

  function addManualPair() {
    const audio = audioFiles.find(item => item.path === matchSelection.audioPath)
    const subtitle = subtitleFiles.find(item => item.path === matchSelection.subtitlePath)
    if (!audio || !subtitle) return
    const nextPair = createSubtitlePair(audio, subtitle, namingStrategy, {
      confidenceLevel: 'medium',
      matchReason: '手动指定'
    })
    setPairs(current => [
      ...current.filter(pair => pair.audio_path !== audio.path && pair.subtitle_path !== subtitle.path),
      nextPair
    ])
    setSelectedPairId(nextPair.id)
    setMatchSelection({ audioPath: '', subtitlePath: '' })
  }

  function rebuildAutoPairs() {
    const nextPairs = buildAutoPairs(audioFiles, subtitleFiles, namingStrategy)
    if (!nextPairs.length) {
      showSystemAlert({ title: '没有生成可用的自动预配对结果', tone: 'warning' })
      return
    }
    setPairs(nextPairs)
    setSelectedPairId(nextPairs[0]?.id || '')
  }

  function buildOrderedPairs() {
    const audioList = sequenceMode
      ? sequenceSelection.audioPaths.map(path => audioFiles.find(item => item.path === path)).filter(Boolean)
      : filteredAudioFiles
    const subtitleList = sequenceMode
      ? sequenceSelection.subtitlePaths.map(path => subtitleFiles.find(item => item.path === path)).filter(Boolean)
      : filteredSubtitleFiles
    if (!audioList.length || (sequenceMode && audioList.length !== subtitleList.length)) {
      showSystemAlert({ title: '请先选择数量一致的音频和字幕', tone: 'warning' })
      return
    }
    const count = Math.min(audioList.length, subtitleList.length)
    const nextPairs = []
    for (let index = 0; index < count; index += 1) {
      nextPairs.push(createSubtitlePair(audioList[index], subtitleList[index], namingStrategy, {
        confidenceLevel: sequenceMode ? 'medium' : 'low',
        matchReason: sequenceMode ? '点选顺序' : '当前列表顺序'
      }))
    }
    setPairs(nextPairs)
    setSelectedPairId(nextPairs[0]?.id || '')
    setSequenceMode(false)
    setSequenceSelection({ audioPaths: [], subtitlePaths: [] })
  }

  async function renameSubtitle(row) {
    if (row?.type !== 'file') return
    const nextName = await showSystemPrompt({
      title: '字幕文件重命名',
      modelValue: row.name,
      currentValue: row.path,
      placeholder: '新文件名'
    })
    if (!nextName) return
    setBusy(true)
    try {
      await libraryApi.browserRename(subtitleLibraryId, resolveSubtitleEntryPath(row, subtitleDir), nextName)
      await reload()
      await onTaskMutated?.()
    } finally {
      setBusy(false)
    }
  }

  async function deleteSubtitleRows(rows) {
    const targetRows = rows.filter(Boolean)
    if (!targetRows.length) return
    const paths = targetRows
      .map(row => resolveSubtitleEntryPath(row, subtitleDir))
      .filter(Boolean)
      .sort((left, right) => right.length - left.length)
    await showSystemConfirm({
      title: targetRows.length === 1 ? '删除字幕条目' : '批量删除字幕条目',
      message: `将删除 ${paths.length} 个字幕目录内条目。`,
      currentValue: paths.join('\n'),
      inputType: 'textarea',
      confirmText: '删除',
      tone: 'danger',
      width: 620
    })
    setBusy(true)
    try {
      const batchId = `subtitle-delete-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      for (const path of paths) {
        await libraryApi.browserDelete(subtitleLibraryId, path, true, { batchId })
      }
      setSelectedTreeIds(new Set())
      await reload()
      await onTaskMutated?.()
    } finally {
      setBusy(false)
    }
  }

  async function applyPairs() {
    if (!pairs.length) {
      await showSystemAlert({ title: '请先添加至少一组配对', tone: 'warning' })
      return
    }
    const conflict = findRenameConflict(pairs, audioFiles, subtitleFiles)
    if (conflict) {
      await showSystemAlert({ title: '存在目标文件名冲突', message: conflict, tone: 'warning' })
      return
    }
    const unusedSubtitles = subtitleFiles.filter(item => !pairs.some(pair => pair.subtitle_path === item.path))
    await showSystemConfirm({
      title: '应用配对确认',
      message: `确定处理 ${pairs.length} 组配对结果吗？${unusedSubtitles.length ? `\n未使用的 ${unusedSubtitles.length} 个原始字幕会一并删除。` : ''}`,
      confirmText: '确定应用',
      tone: 'warning'
    })

    const phaseOneCompleted = []
    const phaseTwoCompleted = []
    setBusy(true)
    try {
      const operations = pairs.flatMap(pair => {
        const next = []
        if (pair.audio_name !== pair.target_audio_name) {
          next.push({
            kind: 'audio',
            source_path: pair.audio_path,
            current_name: pair.audio_name,
            target_name: pair.target_audio_name
          })
        }
        if (pair.subtitle_name !== pair.target_subtitle_name) {
          next.push({
            kind: 'subtitle',
            source_path: pair.subtitle_path,
            current_name: pair.subtitle_name,
            target_name: pair.target_subtitle_name
          })
        }
        return next
      })
      const phaseOne = operations.map((item, index) => ({
        ...item,
        temp_name: `__manual_match_${item.kind}_${String(index + 1).padStart(3, '0')}_${Date.now()}.tmp${item.current_name.match(/\.[^.]+$/)?.[0] || ''}`
      }))

      for (const operation of phaseOne) {
        const operationLibraryId = operation.kind === 'audio' ? audioLibraryId : subtitleLibraryId
        const result = await libraryApi.browserRename(operationLibraryId, operation.source_path, operation.temp_name, {
          skipActivityLog: true,
          renameContext: 'subtitle_manual_match_pair'
        })
        operation.temp_path = result?.new_path || joinPath(parentPath(operation.source_path), operation.temp_name)
        phaseOneCompleted.push(operation)
      }
      for (const operation of phaseOne) {
        const operationLibraryId = operation.kind === 'audio' ? audioLibraryId : subtitleLibraryId
        const result = await libraryApi.browserRename(operationLibraryId, operation.temp_path, operation.target_name, {
          skipActivityLog: true,
          renameContext: 'subtitle_manual_match_pair'
        })
        operation.final_path = result?.new_path || joinPath(parentPath(operation.temp_path), operation.target_name)
        phaseTwoCompleted.push(operation)
      }
      for (const subtitle of unusedSubtitles) {
        await libraryApi.browserDelete(subtitleLibraryId, resolveSubtitleEntryPath(subtitle, subtitleDir), true)
      }
      if (task?.id) {
        await rjSubtitleApi.completeManual(task.id, {
          appliedPairs: pairs.length,
          deletedSubtitles: unusedSubtitles.length,
          namingStrategy,
          pairChanges: pairs.map(pair => ({
            audio_before: pair.audio_name || '',
            audio_after: pair.target_audio_name || '',
            subtitle_before: pair.subtitle_name || '',
            subtitle_after: pair.target_subtitle_name || ''
          })),
          folderPath,
          libraryId: audioLibraryId,
          rjcode: task.rjcode || extractRJCode(folderPath)
        })
      }
      await showSystemAlert({
        title: '字幕配对已应用',
        message: `已处理 ${pairs.length} 组配对${unusedSubtitles.length ? `，删除 ${unusedSubtitles.length} 个未使用字幕` : ''}。`,
        tone: 'success'
      })
      setPairs([])
      await reload()
      await onTaskMutated?.()
    } catch (error) {
      const rollbackPairs = [
        ...phaseTwoCompleted,
        ...phaseOneCompleted.filter(item => !phaseTwoCompleted.includes(item))
      ]
      if (rollbackPairs.length) {
        await rollbackRenamePairs(rollbackPairs, audioLibraryId, subtitleLibraryId)
      }
      await showSystemAlert({
        title: '应用配对失败',
        message: error?.response?.data?.detail || error?.message || String(error),
        tone: 'danger'
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="字幕筛选与人工配对"
      width={1240}
      onClose={onClose}
      footer={
        <>
          <Button onClick={reload} disabled={loading || busy}><RefreshCcw size={15} />刷新</Button>
          <Button variant="primary" loading={busy} disabled={!pairs.length || loading} onClick={applyPairs}>
            <CheckCircle2 size={15} />一键应用同名
          </Button>
          <Button onClick={onClose}>关闭</Button>
        </>
      }
    >
      <div className="library-subtitle-inspector">
        <header className="library-subtitle-inspector-head">
          <div>
            <strong>{task?.rjcode || extractRJCode(folderPath) || itemName({ path: folderPath })}</strong>
            <span>{folderPath || task?.folder_name || '-'}</span>
          </div>
          <div>
            <em><Music size={12} />{audioFiles.length} 音频</em>
            <em><Captions size={12} />{subtitleFiles.length} 字幕</em>
            <em><FileText size={12} />{formatBytes(totalSubtitleSize)}</em>
            <button
              type="button"
              className={`library-subtitle-context-toggle ${contextOpen ? 'is-active' : ''}`}
              onClick={() => setContextOpen(value => !value)}
            >
              <Info size={12} />任务上下文
            </button>
          </div>
        </header>

        <div className={`library-subtitle-inspector-shell ${contextOpen ? 'has-context' : ''}`}>
          <div className="library-subtitle-inspector-main">
            {loading ? <LoadingState label="正在加载字幕目录和音频目录..." /> : null}
            {!loading && !subtitleDir ? <div className="km-empty"><strong>当前任务没有字幕目录</strong></div> : null}

            {!loading && subtitleDir ? (
              <>
                <div className="library-subtitle-pair-toolbar">
                  <div className="library-subtitle-segment">
                    <button type="button" className={namingStrategy === 'audio' ? 'is-active' : ''} onClick={() => setNamingStrategy('audio')}>以音频名为准</button>
                    <button type="button" className={namingStrategy === 'subtitle' ? 'is-active' : ''} onClick={() => setNamingStrategy('subtitle')}>以字幕名为准</button>
                  </div>
                  <div className="library-subtitle-pair-actions">
                    <Button size="sm" onClick={rebuildAutoPairs}><Wand2 size={14} />自动预配对</Button>
                    <Button size="sm" variant={sequenceMode ? 'primary' : 'ghost'} onClick={() => setSequenceMode(value => !value)}><Link2 size={14} />{sequenceMode ? '退出顺序点选' : '顺序点选'}</Button>
                    <Button size="sm" disabled={sequenceMode && !sequenceReady} onClick={buildOrderedPairs}><ListOrdered size={14} />{sequenceMode ? '生成顺序配对' : '按当前列表配对'}</Button>
                    {sequenceMode ? (
                      <Button size="sm" onClick={() => setSequenceSelection({ audioPaths: [], subtitlePaths: [] })}><X size={14} />清空顺序</Button>
                    ) : null}
                  </div>
                </div>

                {sequenceMode ? (
                  <div className={`library-subtitle-sequence-tip ${sequenceReady ? 'is-ready' : ''}`}>
                    <Wand2 size={14} />
                    <span>
                      顺序点选进行中：音频 {sequenceSelection.audioPaths.length} 项，字幕 {sequenceSelection.subtitlePaths.length} 项。
                      {sequenceReady ? '数量一致，可以生成顺序预配对。' : '左右数量需要一致。'}
                    </span>
                  </div>
                ) : null}

                <div className="library-subtitle-pair-grid">
                  <PairListColumn
                    title="原音频目录"
                    icon={<Music size={14} />}
                    rows={filteredAudioFiles}
                    search={audioSearch}
                    onSearchChange={setAudioSearch}
                    filterMode={audioFilter}
                    onFilterModeChange={setAudioFilter}
                    pairedPaths={pairedAudioPaths}
                    selectedPath={matchSelection.audioPath}
                    sequencePaths={sequenceSelection.audioPaths}
                    sequenceMode={sequenceMode}
                    onSelect={selectAudio}
                  />
                  <section className="library-subtitle-pair-column">
                    <header>
                      <strong><Link2 size={14} />配对结果<small>{pairs.length} 组</small></strong>
                      <button type="button" disabled={!pairs.length || busy} onClick={() => { setPairs([]); setSelectedPairId('') }}>清空</button>
                    </header>
                    <button type="button" className="library-subtitle-add-pair" disabled={!canAddPair || busy} onClick={addManualPair}>
                      <Check size={14} />加入手动配对
                    </button>
                    {selectedPair ? (
                      <div className="library-subtitle-pair-focus">
                        <span>当前配对</span>
                        <b>{formatSubtitleName(selectedPair.audio_name)} → {formatSubtitleName(selectedPair.subtitle_name)}</b>
                        <small>{selectedPair.target_audio_name} / {selectedPair.target_subtitle_name}</small>
                      </div>
                    ) : null}
                    <div className="library-subtitle-pair-list">
                      {!pairs.length ? <div className="km-empty"><strong>暂无配对</strong><span>可自动生成，也可左右各选一项后加入</span></div> : null}
                      {pairs.map((pair, index) => (
                        <button
                          type="button"
                          key={pair.id}
                          className={`${selectedPairId === pair.id ? 'is-selected' : ''} ${pair.confidenceLevel === 'low' ? 'is-low-confidence' : ''}`}
                          onClick={() => setSelectedPairId(pair.id)}
                        >
                          <span>
                            <small>配对 {index + 1} · {pair.matchReason}</small>
                            <b>{formatSubtitleName(pair.audio_name)}</b>
                            <small>{pair.audio_name !== pair.target_audio_name ? `→ ${formatSubtitleName(pair.target_audio_name)}` : '音频名保持'}</small>
                          </span>
                          <span>
                            <small>{confidenceLabel(pair.confidenceLevel)}置信</small>
                            <b>{formatSubtitleName(pair.subtitle_name)}</b>
                            <small>{pair.subtitle_name !== pair.target_subtitle_name ? `→ ${formatSubtitleName(pair.target_subtitle_name)}` : '字幕名保持'}</small>
                          </span>
                          <em>{confidenceLabel(pair.confidenceLevel)}</em>
                          <i onClick={event => { event.stopPropagation(); setPairs(current => current.filter(item => item.id !== pair.id)) }}><X size={13} /></i>
                        </button>
                      ))}
                    </div>
                  </section>
                  <PairListColumn
                    title="原字幕目录"
                    icon={<Captions size={14} />}
                    rows={filteredSubtitleFiles}
                    search={subtitleSearch}
                    onSearchChange={setSubtitleSearch}
                    filterMode={subtitleFilter}
                    onFilterModeChange={setSubtitleFilter}
                    pairedPaths={pairedSubtitlePaths}
                    selectedPath={matchSelection.subtitlePath}
                    sequencePaths={sequenceSelection.subtitlePaths}
                    sequenceMode={sequenceMode}
                    onSelect={selectSubtitle}
                  />
                </div>

                {taskLogs.length ? (
                  <section className="library-subtitle-log-panel">
                    <header>
                      <strong><Activity size={14} />过程日志</strong>
                      <span>{taskLogs.length} 条</span>
                    </header>
                    <div>
                      {taskLogs.slice(-8).map((entry, index) => (
                        <p key={`${entry.time || index}-${entry.message || index}`} className={`is-${entry.level || 'info'}`}>
                          <time>{formatProgressLogTime(entry.time)}</time>
                          <em>{progressLevelLabel(entry.level)}</em>
                          <span>{entry.message || entry.text || '-'}</span>
                        </p>
                      ))}
                    </div>
                  </section>
                ) : null}

                <section className="library-subtitle-tree-panel">
                  <header>
                    <strong><FolderOpen size={15} />字幕目录树<small>{selectedTreeRows.length ? `已选 ${selectedTreeRows.length}` : ''}</small></strong>
                    <div>
                      <TextInput value={treeSearch} onChange={event => { setTreeSearch(event.target.value); if (event.target.value.trim()) expandAllTree() }} placeholder="搜索字幕目录..." />
                      <Button size="xs" onClick={expandAllTree}><ChevronsDown size={13} />展开</Button>
                      <Button size="xs" onClick={collapseAllTree}><ChevronsUp size={13} />折叠</Button>
                      <Button size="xs" onClick={toggleAllTreeRows}>{allTreeSelected ? '取消全选' : '全选可见'}</Button>
                      <Button size="xs" variant="danger" disabled={!selectedTreeRows.length || busy} onClick={() => deleteSubtitleRows(selectedTreeRows)}><Trash2 size={13} />删除选中</Button>
                    </div>
                  </header>
                  <div className="library-subtitle-tree">
                    <div className="library-subtitle-tree-head">
                      <span />
                      <span>文件名</span>
                      <span>大小</span>
                      <span>修改时间</span>
                      <span>操作</span>
                    </div>
                    {!flatTree.length ? <div className="km-empty"><strong>{treeSearch ? '没有匹配项' : '字幕目录为空'}</strong></div> : null}
                    {flatTree.map(row => (
                      <div
                        key={row.id}
                        className={`library-subtitle-tree-row ${selectedTreeIds.has(row.id) ? 'is-selected' : ''}`}
                        onClick={event => toggleTreeRow(row, event)}
                      >
                        <span><input type="checkbox" checked={selectedTreeIds.has(row.id)} onChange={event => toggleTreeRow(row, event)} onClick={event => event.stopPropagation()} /></span>
                        <span style={{ paddingLeft: row.depth * 16 }}>
                          {row.type === 'dir' ? (
                            <button type="button" onClick={event => { event.stopPropagation(); toggleTreeExpand(row) }}>
                              <ChevronRight size={13} className={expandedIds.has(row.id) ? 'is-open' : ''} />
                            </button>
                          ) : <i />}
                          {row.type === 'dir' ? <Folder size={14} /> : <FileText size={14} />}
                          <b>{row.name}</b>
                        </span>
                        <em>{formatBytes(row.size)}</em>
                        <time>{formatDateTime(row.modified_time)}</time>
                        <span className="library-subtitle-tree-actions">
                          {row.type === 'file' ? <button type="button" onClick={event => { event.stopPropagation(); renameSubtitle(row) }}><Pencil size={13} /></button> : null}
                          <button type="button" onClick={event => { event.stopPropagation(); deleteSubtitleRows([row]) }}><Trash2 size={13} /></button>
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              </>
            ) : null}
          </div>

          {contextOpen ? (
            <SubtitleContextDrawer
              task={task}
              info={info}
              logs={taskLogs}
              pairs={pairs}
              audioCount={audioFiles.length}
              subtitleCount={subtitleFiles.length}
              selectedTreeRows={selectedTreeRows}
              sequenceMode={sequenceMode}
              sequenceSelection={sequenceSelection}
              folderPath={folderPath}
              subtitleDir={subtitleDir}
            />
          ) : null}
        </div>
      </div>
    </Modal>
  )
}

function SubtitleContextDrawer({
  task,
  info,
  logs,
  pairs,
  audioCount,
  subtitleCount,
  selectedTreeRows,
  sequenceMode,
  sequenceSelection,
  folderPath,
  subtitleDir
}) {
  const metadata = task?.task_metadata || {}
  const rows = [
    ['任务状态', subtitleTaskStatusLabel(task?.display_status || task?.status)],
    ['来源动作', metadata.source_action || task?.source_action || '-'],
    ['任务阶段', task?.current_step || metadata.current_step || '-'],
    ['音频目录', folderPath || '-'],
    ['字幕目录', subtitleDir || '-'],
    ['字幕库存', info?.subtitleLibraryId || task?.subtitle_library_id || task?.library_id || '-'],
    ['创建时间', formatDateTime(task?.created_at)],
    ['完成时间', formatDateTime(task?.completed_at)]
  ]
  const failure = task?.failure_reason || task?.error_message || metadata.failure_reason || ''
  return (
    <aside className="library-subtitle-context-drawer">
      <header>
        <strong><Info size={15} />任务上下文</strong>
        <span>{task?.id || '-'}</span>
      </header>
      <div className="library-subtitle-context-metrics">
        <span><Music size={13} /><b>{audioCount}</b><small>音频</small></span>
        <span><Captions size={13} /><b>{subtitleCount}</b><small>字幕</small></span>
        <span><Link2 size={13} /><b>{pairs.length}</b><small>配对</small></span>
        <span><Check size={13} /><b>{selectedTreeRows.length}</b><small>已选</small></span>
      </div>
      {sequenceMode ? (
        <div className="library-subtitle-context-callout">
          <ListOrdered size={14} />
          <span>顺序模式：音频 {sequenceSelection.audioPaths.length} / 字幕 {sequenceSelection.subtitlePaths.length}</span>
        </div>
      ) : null}
      {failure ? (
        <div className="library-subtitle-context-error">
          <AlertCircle size={14} />
          <span>{failure}</span>
        </div>
      ) : null}
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value || '-'}</dd>
          </div>
        ))}
      </dl>
      <section>
        <h4><Activity size={14} />最近日志</h4>
        {!logs.length ? <p className="library-subtitle-context-empty">暂无过程日志</p> : null}
        {logs.slice(-10).map((entry, index) => (
          <p key={`${entry.time || index}-${entry.message || index}`} className={`is-${entry.level || 'info'}`}>
            <time><Clock3 size={11} />{formatProgressLogTime(entry.time)}</time>
            <em>{progressLevelLabel(entry.level)}</em>
            <span>{entry.message || entry.text || '-'}</span>
          </p>
        ))}
      </section>
      <section>
        <h4><Database size={14} />任务原始上下文</h4>
        <pre>{JSON.stringify(compactTaskContext(task), null, 2)}</pre>
      </section>
    </aside>
  )
}

function PairListColumn({
  title,
  icon,
  rows,
  search,
  onSearchChange,
  filterMode,
  onFilterModeChange,
  pairedPaths,
  selectedPath,
  sequencePaths,
  sequenceMode,
  onSelect
}) {
  return (
    <section className="library-subtitle-pair-column">
      <header>
        <strong>{icon}{title}<small>{rows.length} 项</small></strong>
        <div className="library-subtitle-mini-tabs">
          {filterModes.map(([value, label]) => (
            <button type="button" key={value} className={filterMode === value ? 'is-active' : ''} onClick={() => onFilterModeChange(value)}>{label}</button>
          ))}
        </div>
      </header>
      <TextInput value={search} onChange={event => onSearchChange(event.target.value)} placeholder={`搜索${title}...`} />
      <div className="library-subtitle-source-list">
        {!rows.length ? <div className="km-empty"><strong>没有可用条目</strong></div> : null}
        {rows.map(row => {
          const paired = pairedPaths.has(row.path)
          const sequenceIndex = sequencePaths.indexOf(row.path) + 1
          return (
            <button
              type="button"
              key={row.path || row.name}
              className={`${selectedPath === row.path ? 'is-selected' : ''} ${paired ? 'is-paired' : ''} ${sequenceIndex ? 'is-sequence' : ''}`}
              onClick={() => onSelect(row)}
            >
              <span>
                {sequenceMode && sequenceIndex ? <em>#{sequenceIndex}</em> : null}
                {paired ? <i>已配对</i> : null}
              </span>
              <b>{formatSubtitleName(row.name)}</b>
              <small>{row.relative_path || row.path || row.name}</small>
            </button>
          )
        })}
      </div>
    </section>
  )
}

function filterPairingList(items, keyword, mode, isPaired) {
  const query = String(keyword || '').trim().toLowerCase()
  return [...items]
    .filter(item => {
      if (mode === 'paired' && !isPaired(item)) return false
      if (mode === 'unpaired' && isPaired(item)) return false
      if (!query) return true
      return `${item.name || ''} ${item.relative_path || ''}`.toLowerCase().includes(query)
    })
    .sort((left, right) => compareNatural(left.name || left.path, right.name || right.path))
}

function buildTree(items) {
  const root = []
  const dirMap = new Map()
  const sorted = [...items].sort((left, right) => String(left.relative_path || '').localeCompare(String(right.relative_path || ''), 'zh-CN'))
  for (const item of sorted) {
    const parts = String(item.relative_path || item.name || '').split('/').filter(Boolean)
    if (!parts.length) continue
    let children = root
    let path = ''
    for (let index = 0; index < parts.length - 1; index += 1) {
      path = path ? `${path}/${parts[index]}` : parts[index]
      const key = `dir:${path}`
      if (!dirMap.has(key)) {
        const node = { id: key, name: parts[index], type: 'dir', relative_path: path, size: 0, modified_time: null, children: [] }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }
    children.push({ ...item, id: `file:${item.path || item.relative_path || item.name}`, type: 'file' })
  }
  const walk = node => {
    let total = 0
    let latest = ''
    for (const child of node.children || []) {
      if (child.type === 'dir') walk(child)
      total += Number(child.size || 0)
      if (child.modified_time && (!latest || child.modified_time > latest)) latest = child.modified_time
    }
    node.size = total
    node.modified_time = latest
  }
  root.forEach(node => { if (node.type === 'dir') walk(node) })
  return root
}

function filterTree(nodes, keyword) {
  const result = []
  for (const node of nodes) {
    const matched = `${node.name || ''} ${node.relative_path || ''}`.toLowerCase().includes(keyword)
    if (node.type === 'file') {
      if (matched) result.push(node)
      continue
    }
    const children = filterTree(node.children || [], keyword)
    if (matched || children.length) result.push({ ...node, children })
  }
  return result
}

function flattenTree(nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    result.push({ ...node, depth })
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) {
      result.push(...flattenTree(node.children, depth + 1, openIds))
    }
  }
  return result
}

function buildAutoPairs(audioList, subtitleList, namingStrategy) {
  const usedSubtitlePaths = new Set()
  const subtitleByExact = new Map()
  const subtitleByNormalized = new Map()
  const subtitleByTrack = new Map()

  for (const subtitle of subtitleList) {
    const name = String(subtitle.name || '')
    const baseName = stripTrailingAudioExtension(name.replace(/\.[^.]+$/, '')).toLowerCase()
    const normalized = normalizeSubtitleMatchName(name)
    const trackNumber = extractSubtitleTrackNumber(name)
    addMapItem(subtitleByExact, baseName, subtitle)
    if (normalized) addMapItem(subtitleByNormalized, normalized, subtitle)
    if (trackNumber !== null) addMapItem(subtitleByTrack, trackNumber, subtitle)
  }

  function consume(candidates = []) {
    for (const item of candidates) {
      if (usedSubtitlePaths.has(item.path)) continue
      usedSubtitlePaths.add(item.path)
      return item
    }
    return null
  }

  const pairs = []
  for (const audio of audioList) {
    const audioName = String(audio.name || '')
    const audioBase = audioName.replace(/\.[^.]+$/, '').toLowerCase()
    const audioNormalized = normalizeSubtitleMatchName(audioName)
    const audioTrack = extractSubtitleTrackNumber(audioName)
    let subtitle = consume(subtitleByExact.get(audioBase))
    let confidenceLevel = 'high'
    let matchReason = '精确文件名'
    if (!subtitle && audioTrack !== null) {
      subtitle = consume(subtitleByTrack.get(audioTrack))
      if (subtitle) matchReason = `轨道号 ${audioTrack}`
    }
    if (!subtitle && audioNormalized) {
      subtitle = consume(subtitleByNormalized.get(audioNormalized))
      if (subtitle) {
        confidenceLevel = 'medium'
        matchReason = '规范化标题'
      }
    }
    if (subtitle) pairs.push(createSubtitlePair(audio, subtitle, namingStrategy, { confidenceLevel, matchReason }))
  }
  return pairs
}

function createSubtitlePair(audio, subtitle, namingStrategy, options = {}) {
  const targets = buildSubtitlePairTargets(audio, subtitle, namingStrategy)
  return {
    id: `${audio.path}::${subtitle.path}`,
    audio_path: audio.path,
    audio_name: audio.name,
    audio_relative_path: audio.relative_path || audio.name,
    subtitle_path: subtitle.path,
    subtitle_name: subtitle.name,
    subtitle_relative_path: subtitle.relative_path || subtitle.name,
    target_base: targets.targetBase,
    target_audio_name: targets.targetAudioName,
    target_subtitle_name: targets.targetSubtitleName,
    confidenceLevel: options.confidenceLevel || 'medium',
    matchReason: options.matchReason || '手动配对'
  }
}

function buildSubtitlePairTargets(audio, subtitle, namingStrategy = 'audio') {
  const audioExt = String(audio?.name || '').match(/\.[^.]+$/)?.[0] || ''
  const subtitleExt = String(subtitle?.name || '').match(/\.[^.]+$/)?.[0] || '.vtt'
  const subtitleBase = stripTrailingAudioExtension(String(subtitle?.name || '').replace(/\.[^.]+$/, ''))
  const audioBase = String(audio?.name || '').replace(/\.[^.]+$/, '')
  const targetBase = namingStrategy === 'subtitle' ? subtitleBase : audioBase
  return {
    targetBase,
    targetAudioName: `${targetBase}${audioExt}`,
    targetSubtitleName: `${targetBase}${subtitleExt}`
  }
}

function findRenameConflict(pairs, audioFiles, subtitleFiles) {
  const audioKeys = new Map()
  const subtitleKeys = new Map()
  for (const pair of pairs) {
    addCount(audioKeys, buildRenameConflictKey(pair.audio_path, pair.target_audio_name))
    addCount(subtitleKeys, buildRenameConflictKey(pair.subtitle_path, pair.target_subtitle_name))
  }
  for (const pair of pairs) {
    const audioKey = buildRenameConflictKey(pair.audio_path, pair.target_audio_name)
    if ((audioKeys.get(audioKey) || 0) > 1) return pair.target_audio_name
    const existingAudio = audioFiles.find(item => item.name === pair.target_audio_name && buildRenameConflictKey(item.path, item.name) === audioKey)
    if (existingAudio && existingAudio.path !== pair.audio_path) return pair.target_audio_name
    const subtitleKey = buildRenameConflictKey(pair.subtitle_path, pair.target_subtitle_name)
    if ((subtitleKeys.get(subtitleKey) || 0) > 1) return pair.target_subtitle_name
    const existingSubtitle = subtitleFiles.find(item => item.name === pair.target_subtitle_name && buildRenameConflictKey(item.path, item.name) === subtitleKey)
    if (existingSubtitle && existingSubtitle.path !== pair.subtitle_path && !pairs.every(next => next.subtitle_path !== existingSubtitle.path)) return pair.target_subtitle_name
  }
  return ''
}

async function rollbackRenamePairs(pairs, audioLibraryId, subtitleLibraryId) {
  for (const pair of [...pairs].reverse()) {
    const libraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
    const rollbackSourcePath = pair.final_path || pair.temp_path
    if (!rollbackSourcePath || !pair.current_name) continue
    try {
      await libraryApi.browserRename(libraryId, rollbackSourcePath, pair.current_name, {
        skipActivityLog: true,
        renameContext: 'subtitle_manual_match_pair'
      })
    } catch (_) {}
  }
}

function resolveSubtitleEntryPath(row, subtitleDir) {
  const rowPath = normalizePath(row?.path || '')
  const dir = normalizePath(subtitleDir || '')
  if (rowPath && dir && rowPath.startsWith(dir)) return row.path
  return joinPath(subtitleDir, row.relative_path || row.name || '')
}

function joinPath(basePath, name) {
  const base = String(basePath || '').replace(/[\\/]+$/, '')
  const child = String(name || '').replace(/^[/\\]+/, '')
  if (!base) return child
  if (!child) return base
  return `${base}/${child}`
}

function buildRenameConflictKey(path, targetName) {
  return `${normalizePath(parentPath(path)).toLowerCase()}::${String(targetName || '').trim().toLowerCase()}`
}

function toggleSequencePath(current, key, path) {
  const set = new Set(current[key] || [])
  set.has(path) ? set.delete(path) : set.add(path)
  return { ...current, [key]: [...set] }
}

function isSubtitleRelativePath(value = '') {
  return String(value || '').split(/[\\/]/).some(part => part.toLowerCase() === 'subtitles')
}

function stripTrailingAudioExtension(value = '') {
  let current = String(value || '')
  while (AUDIO_RE.test(current)) current = current.replace(AUDIO_RE, '')
  return current
}

function normalizeSubtitleMatchName(value = '') {
  return stripTrailingAudioExtension(String(value || '').replace(/\.[^.]+$/, ''))
    .toLowerCase()
    .replace(/^(track|trk|tr)[_\-\s]*/i, '')
    .replace(/[\s_\-]+/g, '')
    .replace(/[^\w\u4e00-\u9fff\u3040-\u30ff]+/g, '')
}

function extractSubtitleTrackNumber(value = '') {
  const match = String(value || '').match(/(?:^|[^0-9])(?:tr|track)?[_\-\s]*0*([0-9]{1,3})(?![0-9])/i)
  return match ? Number(match[1]) : null
}

function formatSubtitleName(name = '') {
  const raw = String(name || '')
  const ext = raw.match(/\.[^.]+$/)?.[0] || ''
  const base = ext ? raw.slice(0, -ext.length) : raw
  return `${stripTrailingAudioExtension(base)}${ext}`
}

function confidenceLabel(value) {
  if (value === 'high') return '高'
  if (value === 'low') return '低'
  return '中'
}

function addMapItem(map, key, item) {
  map.set(key, map.get(key) || [])
  map.get(key).push(item)
}

function addCount(map, key) {
  map.set(key, (map.get(key) || 0) + 1)
}

function compareNatural(left, right) {
  return String(left || '').localeCompare(String(right || ''), 'zh-CN', { numeric: true, sensitivity: 'base' })
}

function normalizeProgressLogs(task) {
  const metadata = task?.task_metadata || {}
  const candidates = [
    task?.progress_log,
    task?.progress_logs,
    metadata.progress_log,
    metadata.progress_logs
  ]
  for (const value of candidates) {
    if (Array.isArray(value)) return value.filter(Boolean)
  }
  return []
}

function progressLevelLabel(level) {
  const value = String(level || 'info').toLowerCase()
  if (value === 'success') return '成功'
  if (value === 'error' || value === 'danger') return '错误'
  if (value === 'warning' || value === 'warn') return '警告'
  return '信息'
}

function formatProgressLogTime(value) {
  if (!value) return '--:--'
  const date = new Date(typeof value === 'number' && value < 10_000_000_000 ? value * 1000 : value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function subtitleTaskStatusLabel(status) {
  const map = {
    pending: '等待中',
    processing: '处理中',
    completed: '已完成',
    failed: '失败',
    paused: '已暂停',
    waiting_manual: '等待人工处理',
    waiting_retry: '等待重试',
    canceled: '已取消',
    cancelled: '已取消'
  }
  return map[String(status || '')] || status || '未知'
}

function compactTaskContext(task) {
  if (!task) return {}
  const metadata = task.task_metadata || {}
  return {
    id: task.id,
    rjcode: task.rjcode || metadata.rjcode,
    status: task.display_status || task.status,
    source_page: metadata.source_page || task.source_page,
    source_action: metadata.source_action || task.source_action,
    source_label: metadata.source_label || task.source_label,
    folder_path: task.folder_path || metadata.folder_path,
    subtitle_dir: task.subtitle_dir || metadata.subtitle_dir,
    final_output_path: task.final_output_path || metadata.final_output_path,
    failure_reason: task.failure_reason || task.error_message || metadata.failure_reason
  }
}
