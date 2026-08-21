/**
 * useActivityDetailModels
 * -----------------------
 * 操作记录详情抽屉所需的全部派生数据 / 辅助函数。
 * 接收 row ref（lite 或 detail merged row 都行），返回业务面板所需模型。
 */
import { computed, ref, watch } from 'vue'
import dayjs from 'dayjs'
import {
  AlertCircle, CheckCircle2, File as FileIcon, FileArchive, FileText,
  Film, Folder, Image as ImageIcon, MinusCircle, Music, RefreshCw,
} from 'lucide-vue-next'

// ===================== 通用工具 =====================
function safeDetail(row) {
  return row?.detail && typeof row.detail === 'object' ? row.detail : {}
}

export function compactPath(p) {
  if (!p) return '—'
  const s = String(p)
  if (s.length <= 60) return s
  return `${s.slice(0, 28)}…${s.slice(-26)}`
}

export function formatBytes(size) {
  const value = Number(size || 0)
  if (Number.isNaN(value) || value < 1024) return `${Math.max(0, Math.round(value || 0))} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let cur = value / 1024
  let i = 0
  while (cur >= 1024 && i < units.length - 1) { cur /= 1024; i += 1 }
  return `${cur.toFixed(2)} ${units[i]}`
}

export function formatDurationMs(ms) {
  const value = Math.max(0, Number(ms || 0))
  if (value < 1000) return `${Math.round(value)} ms`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  const minutes = Math.floor(seconds / 60)
  const remain = Math.round(seconds % 60)
  return `${minutes} 分 ${remain} 秒`
}

function formatReleaseDate(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const parsed = dayjs(raw)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : raw
}

function buildDlsiteCoverUrl(rjcode) {
  const normalized = String(rjcode || '').trim().toUpperCase()
  const m = normalized.match(/^RJ(\d{6}|\d{8})$/)
  if (!m) return ''
  const folderUpper = (Math.floor(Number(m[1]) / 1000) + 1) * 1000
  const folder = m[1].length === 8
    ? `RJ${String(folderUpper).padStart(8, '0')}`
    : `RJ${String(folderUpper).padStart(6, '0')}`
  return `https://img.dlsite.jp/modpub/images2/work/doujin/${folder}/${normalized}_img_sam.jpg`
}

function normalizeRjcode(value) {
  const text = String(value || '').trim().toUpperCase()
  if (!text) return ''
  const repeated = text.match(/(?:RJ)+(\d{4,})/i)
  if (repeated) return `RJ${repeated[1]}`
  const m = text.match(/RJ\d{4,}/i)
  return m ? m[0].toUpperCase() : text
}

function extractRjFromText(value) {
  const text = String(value || '')
  const m = text.match(/RJ\d{4,}/i)
  return m ? m[0].toUpperCase() : ''
}

function inferRjcodeFromRow(row) {
  if (!row) return ''
  const detail = safeDetail(row)
  const candidates = [
    row.rjcode, detail.rjcode, detail.source_rjcode, detail.preview_source_rjcode,
    detail.target_rjcode, detail.old_name, detail.new_name, detail.old_path, detail.new_path,
    row.source_path, row.summary, row.task_id,
  ]
  for (const item of candidates) {
    const byValue = normalizeRjcode(item)
    if (byValue.startsWith('RJ')) return byValue
    const byText = extractRjFromText(item)
    if (byText) return byText
  }
  return ''
}

export function displayRjcode(row) {
  return inferRjcodeFromRow(row) || '—'
}

// ===================== 子任务遍历 =====================
function collectChildRowsFromParent(row) {
  const out = []
  const seen = new Set()
  const direct = Array.isArray(row?.child_rows) ? row.child_rows : []
  const fromDetail = Array.isArray(row?.detail?.child_rows) ? row.detail.child_rows : []
  for (const child of [...direct, ...fromDetail]) {
    const id = String(child?.id || '')
    if (id && seen.has(id)) continue
    if (id) seen.add(id)
    out.push(child)
  }
  return out.sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
}

function rowHasChildren(row) {
  return collectChildRowsFromParent(row).length > 0
}

function collectDescendantRows(row) {
  const rows = []
  const walk = (node) => {
    for (const child of collectChildRowsFromParent(node)) {
      rows.push(child)
      walk(child)
    }
  }
  walk(row)
  return rows
}

function collectDescendantStatuses(row) {
  const statuses = []
  const walk = (nodes = []) => {
    for (const n of nodes) {
      statuses.push(String(n?.status || ''))
      if (Array.isArray(n?.child_rows) && n.child_rows.length) walk(n.child_rows)
    }
  }
  walk(collectChildRowsFromParent(row))
  return statuses
}

// ===================== 配对 / 字幕识别 =====================
function hasMergedPair(row) {
  return Boolean(row?.merged_pair || row?.detail?.pair_linked)
}

function hasMergedSubtitleImport(row) {
  return Boolean(row?.merged_subtitle_import || row?.detail?.import_linked)
}

function batchPairRollup(row) {
  const d = safeDetail(row)
  const paired = Math.max(0, Number(d.paired_child_count || 0))
  const awaiting = Math.max(0, Number(d.awaiting_manual_child_count || 0))
  const unpaired = Math.max(0, Number(d.unpaired_child_count || 0))
  return {
    pairedChildCount: paired,
    awaitingManualChildCount: awaiting,
    unpairedChildCount: unpaired,
    totalTrackedCount: Math.max(paired + unpaired, Number(d.child_row_count || 0)),
    fullyPaired: paired > 0 && awaiting <= 0 && unpaired <= 0,
    partiallyPaired: paired > 0 && (awaiting > 0 || unpaired > 0),
  }
}

export function isSubtitleBatchRootRow(row) {
  return Boolean(row && !row.is_tree_child && row.category === 'subtitle_crawl' && row.action === 'batch_start')
}

function isSubtitleBatchRootPaired(row) {
  return isSubtitleBatchRootRow(row) && batchPairRollup(row).fullyPaired
}

function isSubtitleBatchRootPartiallyPaired(row) {
  return isSubtitleBatchRootRow(row) && batchPairRollup(row).partiallyPaired
}

function isBatchChildCrawlRow(row) {
  if (!row || !row.is_tree_child) return false
  if (row.category !== 'subtitle_crawl' || row.action === 'batch_start') return false
  return row?.parent_row?.category === 'subtitle_crawl' && row?.parent_row?.action === 'batch_start'
}

function latestPairRow(row) {
  return collectDescendantRows(row)
    .filter((r) => r?.relation === 'pair' || r?.category === 'subtitle_pair')
    .sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
    .at(-1) || null
}

function isBatchChildPaired(row) {
  if (!isBatchChildCrawlRow(row)) return false
  const p = latestPairRow(row)
  return Boolean(p && p.status === 'success')
}

function isPairCompletedRow(row) {
  if (!row) return false
  if (row?.category === 'subtitle_pair' && row?.status === 'success') return true
  if (row?.category === 'subtitle_crawl' && hasMergedPair(row) &&
      String(row?.merged_pair_status || row?.detail?.pair_status || '') === 'success') return true
  if (isSubtitleBatchRootPaired(row)) return true
  return isBatchChildPaired(row)
}

function pairDetailRow(row) {
  if (!row) return null
  if (row.category === 'subtitle_pair') return row
  return latestPairRow(row)
}

function pairDetailPayload(row) {
  const p = pairDetailRow(row)
  if (p?.detail && typeof p.detail === 'object') return p.detail
  return safeDetail(row)
}

function isSubtitlePairRelatedRow(row) {
  if (!row) return false
  if (['subtitle_crawl', 'subtitle_pair'].includes(String(row.category || ''))) return true
  if (['pair', 'subtitle_import'].includes(String(row.relation || ''))) return true
  return Boolean(pairDetailRow(row))
}

function pairSummaryText(row) {
  if (!row) return ''
  const ds = String(row?.detail?.pair_summary || '').trim()
  if (ds) return ds
  return String(latestPairRow(row)?.summary || '').trim()
}

function pairChangeRows(row) {
  const d = row?.detail
  const changes = Array.isArray(d?.pair_changes) ? d.pair_changes : []
  return changes
    .map((it) => ({
      audio_before: String(it?.audio_before || '').trim(),
      audio_after: String(it?.audio_after || '').trim(),
      subtitle_before: String(it?.subtitle_before || '').trim(),
      subtitle_after: String(it?.subtitle_after || '').trim(),
    }))
    .filter((it) => it.audio_before || it.audio_after || it.subtitle_before || it.subtitle_after)
}

function unmatchedAudioCount(row) {
  const d = safeDetail(row)
  const pd = pairDetailPayload(row)
  const summary = String(row?.summary || '').trim()
  const ps = pairSummaryText(row)
  const mr = d.match_result && typeof d.match_result === 'object' ? d.match_result : {}
  const pmr = pd.match_result && typeof pd.match_result === 'object' ? pd.match_result : {}
  const direct = [
    d.unmatched_audio_count, pd.unmatched_audio_count,
    Array.isArray(mr.unmatched_audio) ? mr.unmatched_audio.length : null,
    Array.isArray(pmr.unmatched_audio) ? pmr.unmatched_audio.length : null,
  ].find((v) => Number.isFinite(Number(v)))
  if (Number.isFinite(Number(direct))) return Number(direct)
  const m = `${summary} ${ps}`.match(/未匹配音频\s*(\d+)/)
  return m ? Number(m[1] || 0) : 0
}

function isManualPairCompleted(row) {
  const d = safeDetail(row)
  const pd = pairDetailPayload(row)
  return Boolean(d.manual_match_completed || pd.manual_match_completed || pairDetailRow(row)?.status === 'success')
}

function isAwaitingManualPair(row) {
  if (!row) return false
  if (isManualPairCompleted(row)) return false
  const d = safeDetail(row)
  const pd = pairDetailPayload(row)
  if (d.awaiting_manual_match || pd.awaiting_manual_match) return true
  if (row.category === 'subtitle_crawl' && unmatchedAudioCount(row) > 0) return true
  return false
}

function pickFirstNonEmpty(...candidates) {
  for (const c of candidates) {
    const v = String(c || '').trim()
    if (v) return v
  }
  return ''
}

function resolveSubtitleTaskId(row) {
  const p = pairDetailRow(row)
  return pickFirstNonEmpty(row?.task_id, safeDetail(row).task_id, p?.task_id, safeDetail(p).task_id)
}

function resolveSubtitleFolderPath(row) {
  const p = pairDetailRow(row)
  return pickFirstNonEmpty(
    safeDetail(row).target_folder_path,
    safeDetail(row).folder_path,
    safeDetail(p).target_folder_path,
    safeDetail(p).folder_path,
    row?.source_path,
    p?.source_path,
  )
}

function resolveSubtitleLibraryId(row) {
  const p = pairDetailRow(row)
  const d = safeDetail(row), pd = safeDetail(p)
  return pickFirstNonEmpty(d.library_id, d.subtitle_library_id, pd.library_id, pd.subtitle_library_id)
}

// ===================== 标签 / 状态 =====================
function isApiRenameAction(row) {
  const a = String(row?.action || '').trim()
  return a === 'api_rename' || a === 'batch_api_rename' || a === 'batch_api_rename_item'
}

function isManualRenameAction(row) {
  const a = String(row?.action || '').trim()
  return a === 'rename' || a === 'manual_rename' || a === 'batch_rename_item'
}

function renameOpTag(row) {
  if (isApiRenameAction(row)) return 'API重命名'
  return '重命名'
}

function renameOpTagClass(row) {
  if (isApiRenameAction(row)) return 'is-api-rename'
  if (isManualRenameAction(row)) return 'is-manual-rename'
  return 'is-rename'
}

function filterDeleteRetryStatus(row) {
  return String(row?.detail?.repair_status || row?.detail?.retry_status || '').trim()
}

function isFilterDeleteRetriedSuccess(row) { return filterDeleteRetryStatus(row) === 'success' }
function isFilterDeleteRetriedPartial(row) { return filterDeleteRetryStatus(row) === 'partial_success' }
function isFilterDeleteRetriedFailed(row) { return filterDeleteRetryStatus(row) === 'failed' }

function mergedSubtitleImportTag(row) {
  const s = String(row?.detail?.import_status || row?.merged_subtitle_import_status || '')
  if (s === 'success') return '配对✔'
  if (s === 'failed') return '补配失败'
  return '字幕补配'
}

function isSubtitleBatchMiss(row) {
  if (!row || row.category !== 'subtitle_crawl' || row.action !== 'batch_start') return false
  const d = safeDetail(row)
  const hit = Math.max(Number(d.recognized_rj_count || 0), Number(d.created_count || 0) + Number(d.skipped_total || 0))
  return hit <= 0
}

function mergedCategoryTags(row) {
  const tags = []
  if (hasMergedSubtitleImport(row)) tags.push(mergedSubtitleImportTag(row))
  if (isSubtitleBatchMiss(row)) tags.push('未命中')
  if (isFilterDeleteRetriedSuccess(row)) tags.push('已修复')
  else if (isFilterDeleteRetriedPartial(row)) tags.push('部分修复')
  else if (isFilterDeleteRetriedFailed(row)) tags.push('未修复')
  return tags
}

function rowCategoryTags(row) {
  const tags = row?.is_tree_child ? [] : mergedCategoryTags(row)
  if (!row?.is_tree_child && row?.category === 'circle_completion' && row?.action === 'refresh_selected_works') {
    tags.push(Number(safeDetail(row)?.changed_count || 0) > 0 ? '有更新' : '无变化')
  }
  if (row?.category === 'pipeline_rename') tags.unshift(renameOpTag(row))
  if (!row?.is_tree_child && isSubtitleBatchRootPartiallyPaired(row)) tags.push('部分配对✔')
  if (!row?.is_tree_child && row?.category === 'subtitle_crawl' && isPairCompletedRow(row)) tags.push('配对✔')
  else if (isBatchChildPaired(row)) tags.push('配对✔')
  return tags
}

function actionTagClass(row, tag) {
  if (tag === 'API重命名') return 'is-api-rename'
  if (tag === '重命名') return 'is-manual-rename'
  if (tag === '删除') return 'is-delete'
  if (tag === '有更新') return 'is-updated'
  if (tag === '无变化') return 'is-unchanged'
  return ''
}

function isRerunRow(row) {
  return Boolean(row?.rerun || row?.detail?.rerun_linked || Number(row?.detail?.rerun_count || 0) > 0)
}

function isRecoveredFailure(row) {
  if (!row || row.status !== 'failed') return false
  if (!['extract', 'auto_import', 'process_existing', 'asmr_sync'].includes(String(row.category || '').trim())) return false
  return Boolean(row?.detail?.recovered_by_success)
}

function finalStatusLabel(row) {
  if (!row || row.is_tree_child || !rowHasChildren(row)) return ''
  if (isSubtitleBatchRootPaired(row)) return '配对✔'
  if (isSubtitleBatchRootPartiallyPaired(row)) return '部分配对✔'
  if (row?.category === 'pipeline_filter' && row?.action === 'filter_delete_preview') {
    if (isFilterDeleteRetriedSuccess(row)) return '删除✔'
    if (isFilterDeleteRetriedPartial(row)) return '部分删除✔'
    if (isFilterDeleteRetriedFailed(row)) return '未修复'
  }
  if (row?.category === 'subtitle_crawl' && isPairCompletedRow(row)) return '配对✔'
  const ss = [String(row.status || ''), ...collectDescendantStatuses(row)]
  if (ss[0] === 'failed' && (ss.includes('success') || ss.includes('partial_success'))) return '已修复✔'
  if (ss.includes('failed') && !ss.includes('success') && !ss.includes('partial_success')) return '异常'
  if (!ss.includes('waiting')) {
    if (row?.category === 'subtitle_crawl') return '配对✔'
    if (row?.category === 'pipeline_filter') return '删除✔'
    if (row?.category === 'subtitle_import') return '配对✔'
    if (['extract', 'auto_import', 'process_existing'].includes(String(row?.category || ''))) {
      if (row?.action === 'batch_start') {
        if (ss.includes('partial_success')) return '部分提交'
        if (ss.includes('failed')) return '提交异常'
        return '已提交'
      }
      // 子任务里出现 partial_success（典型：原作目录已有字幕，作品转入问题作品列表），
      // 整批不能再标成纯"入库✔"。
      // - 真实部分失败（ss 含 'failed'）→ "部分入库"
      // - 纯转入问题作品 / 软失败（无 failed）→ "转入问题作品"
      // finalStatusClass 中含"部分" / "问题" 关键字会自动落到 is-final-partial 黄色徽章。
      if (ss.includes('partial_success')) {
        return ss.includes('failed') ? '部分入库' : '转入问题作品'
      }
      return '入库✔'
    }
    return ss.includes('partial_success') ? '部分完成' : '完成✔'
  }
  return ''
}

function finalStatusClass(row) {
  const l = finalStatusLabel(row)
  if (['配对✔', '删除✔', '入库✔', '完成✔', '已修复✔', '已提交'].includes(l)) return 'is-final-success'
  // "部分..." 或"转入问题作品"都属于 partial 黄色态（语义上未完全成功，但不是失败）
  if (l.includes('部分') || l.includes('问题作品')) return 'is-final-partial'
  return 'is-final-failed'
}

// ===================== 摘要 =====================
function subtitleImportSourceSuffix(row) {
  const sr = String(row?.detail?.source_rjcode || row?.detail?.preview_source_rjcode || '').trim().toUpperCase()
  return sr ? `，来源于 ${sr}` : ''
}

export function displaySummary(row) {
  if (row?.category === 'pipeline_rename' && row?.action === 'batch_manual_rename') {
    const d = safeDetail(row)
    return `修复 ${Number(d.success_count || 0)} 项，失败 ${Number(d.failed_count || 0)} 项`
  }
  if (isSubtitleBatchRootRow(row)) {
    const r = batchPairRollup(row)
    const base = String(row?.summary || '—').trim() || '—'
    if (r.pairedChildCount > 0) {
      return `${base}，后续已完成 ${r.pairedChildCount} 项配对，剩余 ${Math.max(0, r.awaitingManualChildCount || r.unpairedChildCount)} 项待处理`
    }
    return base
  }
  if (isPairCompletedRow(row)) return pairSummaryText(row) || row?.summary || '—'
  if (row?.category === 'subtitle_import' || row?.relation === 'subtitle_import') {
    const base = String(row?.summary || '—').trim() || '—'
    const suffix = subtitleImportSourceSuffix(row)
    if (suffix) {
      const sr = String(row?.detail?.source_rjcode || row?.detail?.preview_source_rjcode || '').trim().toUpperCase()
      if (!base.includes(`来源于 ${sr}`)) return `${base}${suffix}`
    }
    return base
  }
  if (row?.category === 'pipeline_filter') {
    const rj = displayRjcode(row)
    const base = String(row?.summary || '—').trim() || '—'
    if (rj && rj !== '—' && base.includes('未知RJ')) {
      return base.replace(/未知RJ号?|未知RJ/gi, rj)
    }
    return base
  }
  return row?.summary || '—'
}

// ===================== 路径对比 =====================
function pathCompareModel(row) {
  if (!row) return null
  const d = safeDetail(row)
  const sourcePath = String(row.source_path || d.path || '').trim()
  if (row.category === 'pipeline_rename') {
    const beforePath = String(sourcePath || d.old_path || '').trim()
    const afterPath = String(d.new_path || '').trim()
    const oldName = String(d.old_name || '').trim()
    const newName = String(d.new_name || '').trim()
    const reason = String(d.error || d.reason || '').trim()
    if (!beforePath && !afterPath && !oldName && !newName && !reason) return null
    return {
      kind: 'rename', title: '重命名前后路径对比',
      beforePath: beforePath || oldName, afterPath: afterPath || newName,
      reason, opTag: renameOpTag(row), opTagClass: renameOpTagClass(row),
    }
  }
  if (row.category === 'pipeline_delete') {
    const beforePath = String(sourcePath || d.path || '').trim()
    const reason = String(d.error || d.reason || '').trim()
    if (!beforePath && !reason) return null
    return {
      kind: 'delete', title: '删除前后路径对比',
      beforePath, afterPath: row.status === 'success' ? '（已删除）' : '（删除失败，原路径保留）',
      reason, opTag: '删除', opTagClass: 'is-delete',
    }
  }
  return null
}

function pathCompareReasonClass(row) {
  const s = String(row?.status || '').trim()
  if (s === 'success') return 'is-success'
  if (s === 'partial_success') return 'is-warn'
  return 'is-fail'
}

function pathCompareDefaultReason(row) {
  const s = String(row?.status || '').trim()
  if (row?.category === 'pipeline_rename') {
    if (s === 'success') return '重命名成功：新路径已生效'
    if (s === 'partial_success') return '重命名部分成功：请检查失败项原因'
    return '重命名失败：原路径保持不变'
  }
  if (row?.category === 'pipeline_delete') {
    if (s === 'success') return '删除成功：目标已移除'
    if (s === 'partial_success') return '删除部分成功：请检查失败项原因'
    return '删除失败：目标仍保留在原路径'
  }
  return '执行完成'
}

// ===================== 关键字段 / metric =====================
const HIGHLIGHT_LABELS = {
  rjcode: 'RJ', source_rjcode: '来源 RJ', target_rjcode: '目标 RJ',
  linked_source_rjcode: '关联来源 RJ', linked_target_rjcode: '关联目标 RJ',
  downloaded_count: '抓取字幕数', written_files_count: '写入字幕数',
  staged_subtitle_count: '暂存字幕数', applied_pairs: '已配对组数',
  manual_match_applied_pairs: '已配对组数', deleted_subtitles: '删除字幕数',
  manual_match_deleted_subtitles: '删除字幕数', naming_strategy: '命名策略',
  awaiting_manual_match: '待手动配对', manual_match_completed: '配对已完成',
  task_id: '任务 ID', output_path: '输出目录',
  preview_source_path: '预检来源', source_subtitle_dir: '来源字幕目录',
  staged_subtitle_dir: '暂存字幕目录', target_folder_path: '目标作品目录',
  subtitle_dir: '字幕工作目录', library_id: '库存 ID',
  subtitle_library_id: '字幕库存 ID',
  source_basename: '压缩包文件', archive_size_bytes: '压缩包大小',
  extract_output_bytes: '解压产物大小', filtered_count: '过滤文件数',
  filtered_size: '过滤体积', final_file_count: '最终文件数', record_id: '记录 ID',
  import_final_file_count: '导入文件数', recovered_failure_count: '修复失败数',
  duration_ms: '耗时', selected_count: '命中数量', selected_size: '命中体积',
  success_count: '成功数量', failed_count: '失败数量', deleted_bytes: '删除体积',
  retry_target_count: '重试目标数', retry_success_count: '重试成功数',
  retry_failed_count: '重试失败数', retry_recovered_item_count: '重试补回项数',
  recovered_item_count: '补回项数', recovered_selected_size: '补回体积',
  batch_task_count: '下载任务数', downloaded_bytes: '下载大小', uploaded_bytes: '上传大小',
  average_upload_speed_bytes: '平均上传速度', download_root: '下载目录',
  final_output_path: '最终入库路径', target_path: '上传目标', target_library_id: '目标库存',
  target_subdir: '库存前缀目录', source_base_path: '来源根目录', upload_mode: '上传模式',
  uploaded_count: '上传文件数', selected_dir_count: '上传目录数', circle_name: '社团名',
  resource_name: '文件名', resource_path: '相对路径', local_path: '本地路径',
  upload_path: '上传路径', size_bytes: '文件大小', local_owned_count: '本地已有',
  owned_count: '库存已收录', missing_count: '缺失数量', downloadable_count: '可下载数量',
  dl_count: 'DL 数量', works_count: '作品总数', scan_directory_count: '扫描目录数',
  recognized_rj_count: '识别 RJ 数', created_count: '创建任务数', skipped_total: '跳过数量',
  skipped_existing: '已存在跳过', skipped_duplicate: '重复跳过',
  skipped_no_subtitle: '无字幕跳过', batch_duration_ms: '批量总耗时',
  archive_count: '压缩包总数', requested_count: '候选数量',
  extract_completed_count: '完成解压数', failed_child_count: '失败项数',
  partial_child_count: '部分成功项数',
  aggregate_archive_size_bytes: '批量压缩包大小',
  aggregate_extract_output_bytes: '批量解压产物大小',
  aggregate_filtered_count: '批量过滤文件数',
  aggregate_filtered_size: '批量过滤体积',
  conflict_type: '问题类型', original_failure_reason: '原失败原因',
  retry_completed_at: '重试完成时间', retry_source_path: '重试来源',
  retry_final_path: '重试最终路径', final_path: '最终入库路径', resolution_status: '处理状态',
}

const HIGHLIGHT_BYTE_KEYS = new Set([
  'selected_size', 'deleted_bytes', 'archive_size_bytes', 'extract_output_bytes',
  'recovered_selected_size', 'filtered_size', 'aggregate_archive_size_bytes',
  'aggregate_extract_output_bytes', 'aggregate_filtered_size', 'uploaded_bytes', 'downloaded_bytes', 'size_bytes',
])

const SUBTITLE_IMPORT_HIGHLIGHT_KEYS = [
  'source_rjcode',
  'target_rjcode',
  'rjcode',
  'final_file_count',
  'staged_subtitle_count',
  'downloaded_count',
  'written_files_count',
  'applied_pairs',
  'manual_match_applied_pairs',
  'deleted_subtitles',
  'manual_match_deleted_subtitles',
  'naming_strategy',
  'awaiting_manual_match',
  'manual_match_completed',
  'target_folder_path',
  'subtitle_dir',
  'preview_source_path',
  'source_subtitle_dir',
  'staged_subtitle_dir',
  'record_id',
  'task_id',
]

const CONFLICT_RESOLUTION_HIGHLIGHT_KEYS = [
  'rjcode',
  'conflict_type',
  'original_failure_reason',
  'retry_completed_at',
  'retry_source_path',
  'retry_final_path',
  'final_path',
  'resolution_status',
  'task_id',
]

function normalizeHighlightValue(key, value) {
  if (key === 'duration_ms' || key === 'batch_duration_ms') return formatDurationMs(value)
  if (key === 'awaiting_manual_match') return value ? '是' : '否'
  if (key === 'manual_match_completed') return value ? '是' : '否'
  if (key === 'naming_strategy') {
    const strategy = String(value || '').trim()
    if (strategy === 'audio') return '按音频名'
    if (strategy === 'subtitle') return '按字幕名'
    return strategy
  }
  if (key === 'conflict_type') {
    return {
      EXTRACT_FAILED: '解压失败',
      PROCESS_FAILED: '处理失败',
    }[String(value || '').trim().toUpperCase()] || value
  }
  if (key === 'resolution_status') {
    return {
      success: '已完成',
      partial_success: '部分完成',
      failed: '失败',
    }[String(value || '').trim().toLowerCase()] || value
  }
  if (key === 'retry_completed_at') {
    const parsed = dayjs(value)
    return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm:ss') : value
  }
  if (HIGHLIGHT_BYTE_KEYS.has(key)) return formatBytes(value)
  if (key === 'average_upload_speed_bytes') return `${formatBytes(value)}/s`
  if (key.includes('rjcode')) return normalizeRjcode(value)
  return value
}

function detailHighlights(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  const out = []
  const category = String(row?.category || '').trim()
  const keys = category === 'subtitle_import'
    ? [...SUBTITLE_IMPORT_HIGHLIGHT_KEYS, ...Object.keys(HIGHLIGHT_LABELS)]
    : category === 'conflict_resolution'
      ? [...CONFLICT_RESOLUTION_HIGHLIGHT_KEYS, ...Object.keys(HIGHLIGHT_LABELS)]
      : Object.keys(HIGHLIGHT_LABELS)
  const pushed = new Set()
  const pushedLabels = new Set()
  for (const k of keys) {
    if (pushed.has(k)) continue
    const label = HIGHLIGHT_LABELS[k] || k
    if (pushedLabels.has(label)) continue
    let value = d[k]
    if ((value === undefined || value === null || value === '') && k === 'rjcode') value = row?.rjcode
    if ((value === undefined || value === null || value === '') && k === 'task_id') value = row?.task_id
    if (value === undefined || value === null) continue
    value = normalizeHighlightValue(k, value)
    if (!String(value || '').trim()) continue
    pushed.add(k)
    pushedLabels.add(label)
    out.push({ k: label, v: String(value) })
    if (out.length >= 12) break
  }
  return out
}

function filterDeleteMetricCards(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (!String(d.mode || '').startsWith('filter_delete_')) return []
  const items = []
  if (d.duration_ms !== undefined) items.push({ k: '耗时', v: formatDurationMs(d.duration_ms) })
  if (d.selected_count !== undefined) items.push({ k: '命中/选中', v: String(d.selected_count) })
  if (d.selected_size !== undefined) items.push({ k: '预计大小', v: formatBytes(d.selected_size) })
  if (d.deleted_bytes !== undefined) items.push({ k: '实际删除', v: formatBytes(d.deleted_bytes) })
  if (d.success_count !== undefined) items.push({ k: '成功', v: String(d.success_count) })
  if (d.failed_count !== undefined) items.push({ k: '失败', v: String(d.failed_count) })
  if (d.retry_target_count !== undefined) items.push({ k: '重试目录', v: String(d.retry_target_count) })
  if (d.retry_success_count !== undefined) items.push({ k: '重试成功', v: String(d.retry_success_count) })
  if (d.retry_failed_count !== undefined) items.push({ k: '重试失败', v: String(d.retry_failed_count) })
  if (d.recovered_item_count !== undefined) items.push({ k: '补回项数', v: String(d.recovered_item_count) })
  if (d.recovered_selected_size !== undefined) items.push({ k: '补回大小', v: formatBytes(d.recovered_selected_size) })
  if (d.scanned_entries !== undefined) items.push({ k: '扫描数', v: String(d.scanned_entries) })
  if (d.rule_count !== undefined) items.push({ k: '规则数', v: String(d.rule_count) })
  return items.slice(0, 8)
}

function uploadMetricCards(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (String(row?.category || '').trim() !== 'upload') return []
  const items = []
  if (d.uploaded_count !== undefined) items.push({ k: '上传文件', v: String(d.uploaded_count) })
  if (d.selected_dir_count !== undefined) items.push({ k: '上传目录', v: String(d.selected_dir_count) })
  if (d.uploaded_bytes !== undefined) items.push({ k: '上传大小', v: formatBytes(d.uploaded_bytes) })
  if (d.average_upload_speed_bytes !== undefined && Number(d.average_upload_speed_bytes || 0) > 0) {
    items.push({ k: '平均速度', v: `${formatBytes(d.average_upload_speed_bytes)}/s` })
  }
  if (d.duration_ms !== undefined) items.push({ k: '耗时', v: formatDurationMs(d.duration_ms) })
  if (d.target_path) items.push({ k: '目标路径', v: String(d.target_path) })
  if (d.target_library_id) items.push({ k: '目标库存', v: String(d.target_library_id) })
  return items.slice(0, 8)
}

// ===================== 文件树 =====================
function normalizeEntryTreePath(value) {
  return String(value || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
}

function buildFilteredPathSet(items) {
  const out = new Set()
  for (const item of Array.isArray(items) ? items : []) {
    const p = normalizeEntryTreePath(item?.relative_path || item?.path || item?.name || '')
    if (p) out.add(p.toLowerCase())
  }
  return out
}

function mapFilterDeleteItems(items) {
  if (!Array.isArray(items)) return []
  return items.map((item) => {
    const path = item?.path || ''
    const name = item?.name || ''
    const relativePath = item?.relative_path || path || name || ''
    return {
      key: relativePath,
      path,
      relative_path: relativePath,
      name,
      type: item?.type || 'file',
      sizeText: item?.size !== undefined && item?.size !== null ? formatBytes(item.size) : '',
      error: item?.error || '',
    }
  })
}

function buildFilterDeleteTreeRows(items) {
  const roots = []
  const nodeMap = new Map()
  const ensureNode = (key, label, type, parentKey = '') => {
    if (nodeMap.has(key)) return nodeMap.get(key)
    const node = { key, label, type, sizeText: '', metaText: '', error: '', badges: [], children: [] }
    nodeMap.set(key, node)
    if (parentKey && nodeMap.has(parentKey)) nodeMap.get(parentKey).children.push(node)
    else roots.push(node)
    return node
  }
  for (const item of items) {
    const rawPath = String(item.relative_path || item.name || item.path || '').replace(/^\/+|\/+$/g, '')
    if (!rawPath) continue
    const parts = rawPath.split('/').filter(Boolean)
    let parentKey = ''
    let joined = ''
    parts.forEach((part, index) => {
      joined = joined ? `${joined}/${part}` : part
      const isLeaf = index === parts.length - 1
      const node = ensureNode(joined, part, isLeaf ? item.type : 'dir', parentKey)
      if (isLeaf) {
        node.type = item.type
        node.sizeText = item.sizeText || ''
        node.metaText = item.metaText || ''
        node.error = item.error || ''
        node.badges = Array.isArray(item.badges) ? [...item.badges] : []
        node.variant = item.variant || ''
      }
      parentKey = joined
    })
  }
  const markParentVariant = (node) => {
    if (!Array.isArray(node.children) || !node.children.length) return node.variant || ''
    const cv = node.children.map((c) => markParentVariant(c)).filter(Boolean)
    if (!cv.length) return node.variant || ''
    if (cv.every((v) => v === 'deleted')) return 'deleted'
    if (cv.every((v) => v === 'failed')) return 'failed'
    return node.variant || ''
  }
  roots.forEach(markParentVariant)

  // 压掉重复同名 / RJ 前缀的包装目录
  const dirKey = (n) => String(n || '').toLowerCase().replace(/rj0?/g, '').replace(/[^a-z0-9]/g, '')
  const dedupeTreeDirs = (xs, parentName = '') => {
    const out = []
    const pk = dirKey(parentName)
    for (const item of xs || []) {
      if (!item.children || !item.children.length) { out.push(item); continue }
      item.children = dedupeTreeDirs(item.children, item.label)
      const ck = dirKey(item.label)
      if (pk && ck && (ck === pk || ck.includes(pk) || pk.includes(ck))) out.push(...item.children)
      else if (item.children.length === 1 && item.children[0].children && item.children[0].children.length) {
        const cck = dirKey(item.children[0].label)
        if (cck && ck && (cck === ck || cck.includes(ck) || ck.includes(cck))) {
          out.push({ ...item.children[0], label: item.label || item.children[0].label, key: item.key })
        } else out.push(item)
      } else out.push(item)
    }
    return out
  }
  const dedupedRoots = dedupeTreeDirs(roots)

  const rows = []
  const walk = (nodes, depth = 0) => {
    const sorted = [...nodes].sort((a, b) => {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
      return a.label.localeCompare(b.label, 'zh-Hans-CN-u-kn-true')
    })
    for (const node of sorted) {
      rows.push({
        key: node.key, label: node.label, type: node.type,
        sizeText: node.sizeText, metaText: node.metaText, error: node.error,
        badges: node.badges, variant: node.variant || '',
        depth, children: node.children.length ? [...node.children] : [],
        expandable: node.children.length > 0,
      })
    }
  }
  walk(dedupedRoots)
  return rows
}

function commonPathPrefix(paths) {
  const norm = (Array.isArray(paths) ? paths : []).map((p) => String(p || '').trim().replace(/\\/g, '/')).filter(Boolean)
  if (!norm.length) return ''
  const split = norm.map((p) => p.split('/').filter(Boolean))
  const first = split[0]
  const prefix = []
  for (let i = 0; i < first.length; i += 1) {
    const seg = first[i]
    if (split.every((parts) => parts[i] === seg)) prefix.push(seg)
    else break
  }
  const drive = norm[0].match(/^[A-Za-z]:/)?.[0] || ''
  const joined = prefix.join('/')
  if (!joined) return drive
  return drive && !joined.toLowerCase().startsWith(drive.toLowerCase()) ? `${drive}/${joined}` : joined
}

function getFileName(path) {
  const norm = String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
  if (!norm) return ''
  return norm.split('/').filter(Boolean).pop() || norm
}

function normalizeDeleteTreePath(p) {
  return String(p || '').trim().replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/+$/, '')
}

function buildDeleteTreeRows(items) {
  const list = Array.isArray(items) ? items.filter((it) => String(it?.path || '').trim()) : []
  if (!list.length) return []
  const paths = list.map((it) => normalizeDeleteTreePath(it.path)).filter(Boolean)
  const rootPath = commonPathPrefix(paths)
  const rootLabel = getFileName(rootPath) || rootPath || '删除目标'
  const normalized = list.map((item) => {
    const fp = normalizeDeleteTreePath(item.path)
    const nr = normalizeDeleteTreePath(rootPath)
    let rel = fp
    if (nr && fp.toLowerCase().startsWith(`${nr.toLowerCase()}/`)) rel = fp.slice(nr.length + 1)
    else if (nr && fp.toLowerCase() === nr.toLowerCase()) rel = ''
    const display = [rootLabel, rel].filter(Boolean).join('/')
    return { ...item, relative_path: display || rootLabel }
  })
  return buildFilterDeleteTreeRows(normalized)
}

function inferDeleteTreeItemType(path, itemType) {
  const t = String(itemType || '').trim().toLowerCase()
  if (t === 'dir' || t === 'folder') return 'dir'
  const np = String(path || '').trim().replace(/\\/g, '/')
  const base = np.split('/').pop() || ''
  return /\.[^./]+$/.test(base) ? 'file' : 'dir'
}

// ===================== Entry sections （文件树面板的数据源） =====================
function filterDeleteEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  const sections = []
  if (Array.isArray(d.items) && d.items.length) {
    sections.push({
      key: 'preview-items',
      title: `预审命中项（${d.item_total_count || d.items.length}）`,
      rows: buildFilterDeleteTreeRows(mapFilterDeleteItems(d.items)),
    })
  }
  if (Array.isArray(d.succeeded_items) && d.succeeded_items.length) {
    const items = mapFilterDeleteItems(d.succeeded_items).map((it) => ({ ...it, variant: 'deleted' }))
    sections.push({
      key: 'success-items',
      title: `已删除项（${d.success_count || d.succeeded_items.length}）`,
      rows: buildFilterDeleteTreeRows(items),
    })
  }
  if (Array.isArray(d.failed_items) && d.failed_items.length) {
    const items = mapFilterDeleteItems(d.failed_items).map((it) => ({ ...it, variant: 'failed' }))
    sections.push({
      key: 'failed-items',
      title: `失败项（${d.failed_count || d.failed_items.length}）`,
      rows: buildFilterDeleteTreeRows(items),
    })
  }
  if (Array.isArray(d.retry_targets) && d.retry_targets.length) {
    sections.push({
      key: 'retry-targets',
      title: `重试目录（${d.retry_target_count || d.retry_targets.length}）`,
      rows: buildFilterDeleteTreeRows(mapFilterDeleteItems(d.retry_targets)),
    })
  }
  if (Array.isArray(d.recovered_items) && d.recovered_items.length) {
    sections.push({
      key: 'recovered-items',
      title: `重试补回项（${d.recovered_item_count || d.recovered_items.length}）`,
      rows: buildFilterDeleteTreeRows(mapFilterDeleteItems(d.recovered_items)),
    })
  }
  if (Array.isArray(d.failed_targets) && d.failed_targets.length) {
    sections.push({
      key: 'retry-failed-targets',
      title: `重试后仍失败目录（${d.retry_failed_count || d.failed_targets.length}）`,
      rows: buildFilterDeleteTreeRows(mapFilterDeleteItems(d.failed_targets)),
    })
  }
  return sections
}

function importFilteredEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (!['auto_import', 'process_existing'].includes(String(row?.category || '').trim())) return []
  const rawItems = Array.isArray(d.filtered_items) ? d.filtered_items : []
  const rawTreeItems = Array.isArray(d.file_tree_items) ? d.file_tree_items : []
  if (!rawTreeItems.length && !rawItems.length) return []
  const filteredPathSet = buildFilteredPathSet(rawItems)
  const baseItems = rawTreeItems.length ? rawTreeItems : rawItems
  const items = mapFilterDeleteItems(baseItems).map((item) => {
    const p = normalizeEntryTreePath(item.relative_path || item.path || item.name)
    return filteredPathSet.has(p.toLowerCase()) ? { ...item, variant: 'deleted' } : item
  })
  const filteredCount = items.filter((i) => i.variant === 'deleted').length
  const titleSuffix = filteredCount > 0 ? `${items.length} 项，过滤 ${filteredCount}` : `${items.length}`
  return [{
    key: 'import-file-tree',
    title: `文件树（${titleSuffix}）`,
    rows: buildFilterDeleteTreeRows(items),
  }]
}

function conflictResolutionEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (String(row?.category || '').trim() !== 'conflict_resolution') return []
  const rawItems = Array.isArray(d.file_diff_items) ? d.file_diff_items : []
  if (!rawItems.length) return []
  const items = mapFilterDeleteItems(rawItems).map((item, index) => {
    const raw = rawItems[index] || {}
    const variant = String(raw.variant || '').trim()
    const badgeMap = { added: '新增', deleted: '删除', changed: '变更' }
    const oldSize = Number(raw.old_size || 0)
    const newSize = Number(raw.new_size || raw.size || 0)
    const metaText = variant === 'changed' && (oldSize || newSize)
      ? `${formatBytes(oldSize)} -> ${formatBytes(newSize)}`
      : ''
    return {
      ...item,
      variant,
      metaText,
      badges: badgeMap[variant] ? [badgeMap[variant]] : [],
    }
  })
  const addedCount = Number(d.added_count || items.filter((it) => it.variant === 'added').length || 0)
  const deletedCount = Number(d.deleted_count || items.filter((it) => it.variant === 'deleted').length || 0)
  const changedCount = Number(d.changed_count || items.filter((it) => it.variant === 'changed').length || 0)
  const titleBits = []
  if (addedCount) titleBits.push(`新增 ${addedCount}`)
  if (deletedCount) titleBits.push(`删除 ${deletedCount}`)
  if (changedCount) titleBits.push(`变更 ${changedCount}`)
  // 把后端透传过来的 surrogate 反解 / 字面转义计数附加到 description，
  // 让用户直接在操作记录详情里看到本次有没有自动修复非 UTF-8 文件名。
  const surrogateRepaired = Number(d.garbled_filename_surrogate_repaired_count || 0)
  const surrogateEscaped = Number(d.garbled_filename_surrogate_escaped_count || 0)
  const surrogateBits = []
  if (surrogateRepaired) surrogateBits.push(`自动反解 ${surrogateRepaired} 个非 UTF-8 文件名`)
  if (surrogateEscaped) surrogateBits.push(`字面转义 ${surrogateEscaped} 个`)
  const pathDesc = [d.source_path, d.target_path || d.final_path].filter(Boolean).join(' -> ')
  const description = surrogateBits.length
    ? [pathDesc, `乱码修复：${surrogateBits.join('、')}`].filter(Boolean).join(' · ')
    : pathDesc
  return [{
    key: 'conflict-resolution-diff',
    title: `文件树变化（${titleBits.join(' / ') || items.length}）`,
    description,
    rows: buildFilterDeleteTreeRows(items),
  }]
}

function mapAsmrSyncFileItems(items, mode) {
  return (Array.isArray(items) ? items : []).slice(0, 200).map((item, index) => {
    const path = String(item?.relative_path || item?.path || item?.upload_path || item?.resource_path || item?.name || '')
    const fb = path.split('/').pop() || path.split('\\').pop() || '未命名文件'
    return {
      key: `${mode}-${index}-${path || fb}`,
      path, relative_path: path, name: String(item?.name || fb), type: 'file',
      sizeText: item?.size_bytes !== undefined && item?.size_bytes !== null
        ? formatBytes(item.size_bytes)
        : (item?.size !== undefined && item?.size !== null ? formatBytes(item.size) : ''),
      error: String(item?.error || item?.failure_reason || '').trim(),
    }
  }).filter((it) => it.relative_path || it.name)
}

function normalizeAsmrMatchPath(value) {
  return String(value || '').trim().replace(/\\/g, '/').replace(/^\.\/+/, '').replace(/\/+/g, '/').replace(/\/+$/, '').toLowerCase()
}

function collectAsmrMatchInfo(item) {
  const raw = [item?.relative_path, item?.path, item?.name].map(normalizeAsmrMatchPath).filter(Boolean)
  const exact = Array.from(new Set(raw.filter((v) => v.includes('/'))))
  const basenames = Array.from(new Set(raw.map((v) => getFileName(v)).filter(Boolean)))
  return { exact, basenames }
}

function buildAsmrUploadedMatchIndex(items) {
  const exact = new Set()
  const basenameCount = new Map()
  for (const item of Array.isArray(items) ? items : []) {
    const info = collectAsmrMatchInfo(item)
    info.exact.forEach((v) => exact.add(v))
    info.basenames.forEach((v) => basenameCount.set(v, (basenameCount.get(v) || 0) + 1))
  }
  return { exact, basenameCount }
}

function isAsmrFileUploaded(item, idx) {
  const info = collectAsmrMatchInfo(item)
  if (info.exact.some((v) => idx.exact.has(v))) return true
  return info.basenames.some((v) => idx.basenameCount.get(v) === 1)
}

function extractAsmrSummaryResourceName(summary) {
  const text = String(summary || '').trim()
  if (!text) return ''
  const i = text.indexOf('/')
  if (i >= 0) return text.slice(i + 1).replace(/\s+(已上传|下载完成|上传完成|上传失败|下载失败).*$/u, '').trim()
  return text.replace(/^(文件下载完成|文件上传完成|文件下载|文件上传)\s*/u, '').replace(/\s+(已上传|下载完成|上传完成|上传失败|下载失败).*$/u, '').trim()
}

function collectAsmrSyncFiles(row, mode) {
  const d = safeDetail(row)
  if (mode === 'download') {
    const direct = mapAsmrSyncFileItems(d.download_files, mode)
    if (direct.length) return direct
    return mapAsmrSyncFileItems(
      (Array.isArray(d.child_rows) ? d.child_rows : [])
        .filter((it) => String(it?.relation || it?.action || '').trim() === 'asmr_resource' || String(it?.action || '').trim() === 'resource_downloaded')
        .map((it) => {
          const cd = safeDetail(it)
          return {
            name: cd.resource_name || cd.relative_path || extractAsmrSummaryResourceName(it?.summary),
            relative_path: cd.relative_path || cd.resource_path || cd.resource_name || extractAsmrSummaryResourceName(it?.summary),
            size_bytes: cd.size_bytes,
            error: it?.status === 'failed' ? (cd.failure_reason || it?.summary || '') : '',
          }
        }), mode)
  }
  if (mode === 'upload') {
    return mapAsmrSyncFileItems(d.upload_files, mode)
  }
  // uploaded
  const direct = mapAsmrSyncFileItems(d.uploaded_files, mode)
  if (direct.length) return direct
  return mapAsmrSyncFileItems(
    (Array.isArray(d.child_rows) ? d.child_rows : [])
      .filter((it) => String(it?.relation || it?.action || '').trim() === 'asmr_upload' || String(it?.action || '').trim() === 'resource_uploaded')
      .map((it) => {
        const cd = safeDetail(it)
        return {
          name: cd.relative_path || cd.upload_path || cd.target_path || extractAsmrSummaryResourceName(it?.summary),
          relative_path: cd.relative_path || cd.upload_path || cd.target_path || extractAsmrSummaryResourceName(it?.summary),
          size_bytes: cd.size_bytes,
          error: it?.status === 'failed' ? (cd.failure_reason || it?.summary || '') : '',
        }
      }), mode)
}

function buildMergedAsmrSyncFileItems(row) {
  const dl = collectAsmrSyncFiles(row, 'download')
  const upd = collectAsmrSyncFiles(row, 'uploaded')
  const up = collectAsmrSyncFiles(row, 'upload')
  const base = dl.length ? dl : (upd.length ? upd : up)
  if (!base.length) return []
  const idx = buildAsmrUploadedMatchIndex(upd)
  const shouldMark = upd.length > 0
  return base.map((item, i) => {
    const uploaded = shouldMark && (base === upd || isAsmrFileUploaded(item, idx))
    return { ...item, key: item?.key || `asmr-file-${i}`, badges: uploaded ? ['已上传'] : [] }
  })
}

function sumAsmrSyncFileBytes(items) {
  return (Array.isArray(items) ? items : []).reduce((sum, it) => {
    const text = String(it?.sizeText || '').trim()
    if (!text) return sum
    const m = text.match(/^([\d.]+)\s*(B|KB|MB|GB|TB)$/i)
    if (!m) return sum
    const power = { B: 0, KB: 1, MB: 2, GB: 3, TB: 4 }[m[2].toUpperCase()] ?? 0
    return sum + Number(m[1] || 0) * (1024 ** power)
  }, 0)
}

function resolveAsmrSyncSectionDescription(detail) {
  const final = String(detail?.final_output_path || detail?.target_path || '').trim()
  const root = String(detail?.source_base_path || '').trim()
  if (root && final) return `来源根目录：${root} → 上传目标：${final}`
  if (final) return `上传目标：${final}`
  if (root) return `来源根目录：${root}`
  return ''
}

function asmrSyncEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (!['asmr_sync', 'upload'].includes(String(row?.category || '').trim())) return []
  const merged = buildMergedAsmrSyncFileItems(row)
  if (!merged.length) return []
  const totalBytes = sumAsmrSyncFileBytes(merged)
  const uploadedCount = merged.filter((it) => Array.isArray(it.badges) && it.badges.includes('已上传')).length
  const titleParts = [String(Number(d.success_count || merged.length))]
  if (totalBytes > 0) titleParts.push(formatBytes(totalBytes))
  if (uploadedCount > 0) titleParts.push(`已上传 ${uploadedCount}`)
  return [{
    key: String(row?.category || '').trim() === 'upload' ? 'upload-file-tree' : 'asmr-file-tree',
    title: `文件清单（${titleParts.join(' / ')}）`,
    description: resolveAsmrSyncSectionDescription(d),
    rows: buildFilterDeleteTreeRows(merged),
  }]
}

function firstNonEmpty(...values) {
  for (const value of values) {
    const text = String(value || '').trim()
    if (text) return text
  }
  return ''
}

function baiduCustomFileOverrideFor(item, overrides) {
  if (!item || typeof item !== 'object' || !overrides || typeof overrides !== 'object') return null
  const keys = [
    item.fs_id,
    item.fsid,
    item.path,
    item.remote_path,
    item.relative_path,
    item.name,
  ].map((value) => String(value || '').trim()).filter(Boolean)
  for (const key of keys) {
    const direct = overrides[key]
    if (direct && typeof direct === 'object') return direct
  }
  const normalizedKeys = new Set(keys.map((value) => value.replace(/\\/g, '/').toLowerCase()))
  for (const value of Object.values(overrides)) {
    if (!value || typeof value !== 'object') continue
    const candidates = [
      value.fs_id,
      value.fsid,
      value.path,
      value.remote_path,
      value.relative_path,
      value.name,
    ].map((it) => String(it || '').trim().replace(/\\/g, '/').toLowerCase()).filter(Boolean)
    if (candidates.some((candidate) => normalizedKeys.has(candidate))) return value
  }
  return null
}

function mapBaiduDownloadFileItems(items) {
  return (Array.isArray(items) ? items : []).slice(0, 200).map((item, index) => {
    if (!item || typeof item !== 'object') return null
    const overrides = item.custom_file_names && typeof item.custom_file_names === 'object' ? item.custom_file_names : {}
    const fileOverride = baiduCustomFileOverrideFor(item, overrides)
    const customName = firstNonEmpty(item.custom_name, item.custom_filename, fileOverride?.custom_name, fileOverride?.custom_filename)
    const originalName = firstNonEmpty(item.name, item.file_name, item.remote_path, item.path, item.relative_path, `文件 ${index + 1}`)
    const relativePath = firstNonEmpty(item.relative_path, item.path, item.remote_path, originalName)
    const status = String(item.status || '').trim()
    const hasPassword = Boolean(item.has_extract_password || fileOverride?.has_extract_password)
    const originalRelativePath = firstNonEmpty(item.original_relative_path, item.original_name)
    const wasRenamed = Boolean(
      customName
      || item.custom_rename_applied
      || item.custom_file_rename_applied
      || item.custom_group_folder_applied
      || (originalRelativePath && originalRelativePath !== relativePath)
    )
    const badges = []
    if (wasRenamed) badges.push(`重命名为 ${getFileName(relativePath) || customName || relativePath}`)
    if (hasPassword) badges.push('指定密码')
    if (status === 'completed') badges.push('已完成')
    else if (status === 'failed') badges.push('失败')
    const metaParts = []
    if (wasRenamed) metaParts.push(`${originalRelativePath || originalName} -> ${relativePath}`)
    const targetPath = firstNonEmpty(item.local_path, item.target_path, item.output_path)
    if (targetPath) metaParts.push(targetPath)
    const downloaded = Number(item.downloaded || 0)
    const total = Number(item.total || item.size || item.size_bytes || 0)
    if (downloaded > 0 && total > 0 && downloaded < total) metaParts.push(`${formatBytes(downloaded)} / ${formatBytes(total)}`)
    return {
      key: `baidu-download-${index}-${relativePath || originalName}`,
      path: relativePath,
      relative_path: relativePath,
      name: customName || getFileName(relativePath) || originalName,
      type: item.is_dir ? 'dir' : 'file',
      sizeText: total > 0 ? formatBytes(total) : '',
      metaText: metaParts.join(' · '),
      error: String(item.error || item.failure_reason || '').trim(),
      badges,
      variant: status === 'failed' ? 'failed' : '',
    }
  }).filter(Boolean)
}

function baiduNetdiskEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (String(row?.category || '').trim() !== 'baidu_netdisk') return []
  const allDownloadFiles = mapBaiduDownloadFileItems(d.download_files)
  const failedFiles = mapBaiduDownloadFileItems(d.failed_files).map((item) => ({ ...item, variant: 'failed' }))
  const failedFileKeys = new Set(failedFiles.map((item) => [
    String(item.relative_path || item.path || item.name || '').trim().toLowerCase(),
    String(item.sizeText || '').trim(),
  ].join('\u0000')))
  const downloadFiles = failedFileKeys.size
    ? allDownloadFiles.filter((item) => !failedFileKeys.has([
        String(item.relative_path || item.path || item.name || '').trim().toLowerCase(),
        String(item.sizeText || '').trim(),
      ].join('\u0000')))
    : allDownloadFiles
  if (!downloadFiles.length && !failedFiles.length) return []
  const totalBytes = downloadFiles.reduce((sum, item) => {
    const raw = String(item.sizeText || '').trim()
    const m = raw.match(/^([\d.]+)\s*(B|KB|MB|GB|TB)$/i)
    if (!m) return sum
    const power = { B: 0, KB: 1, MB: 2, GB: 3, TB: 4 }[m[2].toUpperCase()] ?? 0
    return sum + Number(m[1] || 0) * (1024 ** power)
  }, 0)
  const passwordCount = downloadFiles.filter((it) => (it.badges || []).includes('指定密码')).length
  const renamedCount = downloadFiles.filter((it) => (it.badges || []).some((badge) => String(badge).startsWith('重命名为 '))).length
  const titleParts = [`${downloadFiles.length || failedFiles.length} 个文件`]
  if (totalBytes > 0) titleParts.push(formatBytes(totalBytes))
  if (renamedCount > 0) titleParts.push(`重命名 ${renamedCount}`)
  if (passwordCount > 0) titleParts.push(`指定密码 ${passwordCount}`)
  const description = [
    firstNonEmpty(d.renamed_output_path, d.final_output_path, d.staging_dir, d.download_root),
    d.output_folder_name ? `保存为：${d.output_folder_name}` : '',
  ].filter(Boolean).join(' · ')
  const sections = []
  if (downloadFiles.length) {
    sections.push({
      key: 'baidu-download-files',
      title: `下载文件（${titleParts.join(' · ')}）`,
      description,
      rows: buildFilterDeleteTreeRows(downloadFiles),
    })
  }
  if (failedFiles.length) {
    sections.push({
      key: 'baidu-failed-files',
      title: `下载失败（${failedFiles.length}）`,
      rows: buildFilterDeleteTreeRows(failedFiles),
    })
  }
  return sections
}

function deleteEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (String(row?.category || '').trim() !== 'pipeline_delete') return []
  const succeeded = []
  const failed = []
  if (Array.isArray(d.results) && d.results.length) {
    for (const it of d.results) {
      const path = String(it?.path || '').trim()
      if (!path) continue
      const mapped = {
        key: path, path, relative_path: path,
        name: getFileName(path) || path,
        type: inferDeleteTreeItemType(path, ''),
        sizeText: '',
        error: String(it?.error || '').trim(),
        variant: it?.success === false || String(it?.error || '').trim() ? 'failed' : 'deleted',
      }
      if (it?.success === false || mapped.error) failed.push(mapped)
      else succeeded.push(mapped)
    }
  }
  if (!succeeded.length && !failed.length && Array.isArray(d.child_rows) && d.child_rows.length) {
    for (const it of d.child_rows) {
      const cd = safeDetail(it)
      const path = String(it?.source_path || cd.path || '').trim()
      if (!path) continue
      const mapped = {
        key: `${it?.id || path}`, path, relative_path: path,
        name: String(cd.item_name || getFileName(path) || path),
        type: inferDeleteTreeItemType(path, cd.item_type || ''),
        sizeText: '',
        error: String(cd.error || '').trim(),
        variant: String(it?.status || '').trim() === 'failed' || String(cd.error || '').trim() ? 'failed' : 'deleted',
      }
      if (String(it?.status || '').trim() === 'failed' || mapped.error) failed.push(mapped)
      else succeeded.push(mapped)
    }
  }
  if (!succeeded.length && !failed.length && String(row?.action || '').trim() === 'delete') {
    const path = String(row?.source_path || d.path || '').trim()
    if (path) {
      const mapped = {
        key: path, path, relative_path: path,
        name: String(d.item_name || getFileName(path) || path),
        type: inferDeleteTreeItemType(path, d.item_type || ''),
        sizeText: '',
        error: String(d.error || '').trim(),
        variant: String(row?.status || '').trim() === 'failed' || String(d.error || '').trim() ? 'failed' : 'deleted',
      }
      if (String(row?.status || '').trim() === 'failed' || mapped.error) failed.push(mapped)
      else succeeded.push(mapped)
    }
  }
  const out = []
  if (succeeded.length) {
    const suffix = d.deleted_bytes ? ` / ${formatBytes(d.deleted_bytes)}` : ''
    out.push({ key: 'delete-succeeded-items', title: `删除文件（${succeeded.length}${suffix}）`, rows: buildDeleteTreeRows(succeeded) })
  }
  if (failed.length) {
    out.push({ key: 'delete-failed-items', title: `删除失败（${failed.length}）`, rows: buildDeleteTreeRows(failed) })
  }
  return out
}

function normalizePathForCompare(p) {
  return String(p || '').trim().replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

function findSubtitleBatchSourceDirectory(folderPath, directories) {
  const needle = normalizePathForCompare(folderPath)
  if (!needle) return null
  let matched = null
  let matchedLen = -1
  for (const it of directories) {
    const base = String(it?.folder_path || it?.path || '').trim()
    const nb = normalizePathForCompare(base)
    if (!nb) continue
    if ((needle === nb || needle.startsWith(`${nb}/`)) && nb.length > matchedLen) {
      matched = it
      matchedLen = nb.length
    }
  }
  return matched
}

function buildSubtitleBatchDirectoryRows(detail) {
  const sourceDirs = Array.isArray(detail?.source_directories) ? detail.source_directories : []
  const scanTargets = Array.isArray(detail?.scan_targets) ? detail.scan_targets : []
  const created = Array.isArray(detail?.created_tasks) ? detail.created_tasks : []
  const skipped = Array.isArray(detail?.skipped_items) ? detail.skipped_items : []
  const dirMap = new Map()
  for (const [i, it] of sourceDirs.slice(0, 120).entries()) {
    const path = String(it?.folder_path || it?.path || '').trim()
    const key = path || `source-${i}`
    dirMap.set(key, {
      key: `subtitle-dir-${key}`, path,
      label: String(it?.folder_name || it?.name || path || '未命名目录'),
      type: 'dir', variant: 'dir', sizeText: path, metaText: '', error: '',
      depth: 0, expandable: true, children: [], createdCount: 0, failedCount: 0,
    })
  }
  for (const t of scanTargets.slice(0, 160)) {
    const path = String(t?.path || '').trim()
    const ex = dirMap.get(path)
    if (ex) {
      ex.metaText = t?.message || ''
      if (String(t?.status || '').trim() === 'failed') ex.variant = 'warning'
    }
  }
  const ensureDir = (folderPath, fb = '') => {
    const m = findSubtitleBatchSourceDirectory(folderPath, sourceDirs)
    const sp = String(m?.folder_path || m?.path || folderPath || '').trim()
    const key = sp || folderPath || fb || `other-${dirMap.size}`
    if (!dirMap.has(key)) {
      dirMap.set(key, {
        key: `subtitle-dir-${key}`, path: sp,
        label: String(m?.folder_name || m?.name || fb || sp || '未命名目录'),
        type: 'dir', variant: 'dir', sizeText: sp, metaText: '', error: '',
        depth: 0, expandable: true, children: [], createdCount: 0, failedCount: 0,
      })
    }
    return dirMap.get(key)
  }
  for (const [i, it] of created.slice(0, 200).entries()) {
    const fp = String(it?.folder_path || '').trim()
    const parent = ensureDir(fp, it?.folder_name || '')
    parent.createdCount += 1
    parent.children.push({
      key: `created-${i}-${it?.task_id || fp || it?.rjcode || ''}`,
      label: `${it?.rjcode ? `[${it.rjcode}] ` : ''}${it?.folder_name || fp || '未命名 RJ'}`,
      type: 'rj', variant: 'success', depth: 1,
      metaText: '已创建爬取任务', sizeText: fp, error: '',
    })
  }
  for (const [i, it] of skipped.slice(0, 200).entries()) {
    const fp = String(it?.folder_path || '').trim()
    const parent = ensureDir(fp, it?.folder_name || '')
    parent.failedCount += 1
    parent.variant = 'warning'
    parent.children.push({
      key: `skipped-${i}-${fp || it?.rjcode || it?.folder_name || ''}`,
      label: `${it?.rjcode ? `[${it.rjcode}] ` : ''}${it?.folder_name || fp || '未命名 RJ'}`,
      type: 'rj', variant: 'warning', depth: 1,
      metaText: it?.queue_state === 'existing_task' ? '加入失败：任务已存在' : '加入失败',
      sizeText: fp, error: String(it?.queue_message || '').trim(),
    })
  }
  return Array.from(dirMap.values()).map((it) => {
    const sp = []
    if (it.metaText) sp.push(it.metaText)
    if (it.createdCount) sp.push(`成功 ${it.createdCount}`)
    if (it.failedCount) sp.push(`失败 ${it.failedCount}`)
    return { ...it, metaText: sp.join(' · '), children: it.children }
  })
}

function subtitleBatchEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object' || d.mode !== 'subtitle_batch_start') return []
  const rows = buildSubtitleBatchDirectoryRows(d)
  if (!rows.length) return []
  return [{ key: 'batch-directory-tree', title: `扫描详情（${rows.length}）`, rows }]
}

function activityEntrySections(row) {
  return [
    ...conflictResolutionEntrySections(row),
    ...asmrSyncEntrySections(row),
    ...baiduNetdiskEntrySections(row),
    ...deleteEntrySections(row),
    ...importFilteredEntrySections(row),
    ...subtitleBatchEntrySections(row),
    ...filterDeleteEntrySections(row),
  ]
}

function activityEntrySectionTitle(row) {
  const d = row?.detail
  if (d && typeof d === 'object' && d.mode === 'subtitle_batch_start') return '批量详情'
  if (String(row?.category || '').trim() === 'conflict_resolution') return '问题作品处理'
  if (String(row?.category || '').trim() === 'baidu_netdisk') return '百度网盘'
  if (['asmr_sync', 'upload'].includes(String(row?.category || '').trim())) return '文件树'
  if (String(row?.category || '').trim() === 'pipeline_delete') return '文件树'
  if (['auto_import', 'process_existing'].includes(String(row?.category || '').trim())) return '处理清单'
  return '删除清单'
}

// ===================== 文件树图标 =====================
function entryIconLookupText(item) {
  return String(item?.label || item?.name || item?.relative_path || item?.path || item?.key || '').toLowerCase()
}

function isEntryDirectory(item) {
  const type = String(item?.type || '').trim().toLowerCase()
  return type === 'dir' || type === 'folder'
}

function resolveEntryIcon(item) {
  if (item?.icon) return item.icon
  const v = String(item?.variant || '').trim()
  if (v === 'warning') return AlertCircle
  if (v === 'changed') return RefreshCw
  if (isEntryDirectory(item)) return Folder
  const name = entryIconLookupText(item)
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(name)) return Music
  if (/\.(jpg|jpeg|png|webp|gif|bmp|avif)$/i.test(name)) return ImageIcon
  if (/\.(mp4|mkv|avi|mov|wmv|webm|m4v)$/i.test(name)) return Film
  if (/\.(zip|7z|rar|tar|gz|bz2|xz)$/i.test(name)) return FileArchive
  if (/\.(srt|ass|ssa|vtt|lrc|txt|md|json)$/i.test(name)) return FileText
  return FileIcon
}

function entryIconClass(item) {
  const v = String(item?.variant || '').trim()
  if (v === 'warning') return 'is-warning'
  if (v === 'changed') return 'is-changed'
  if (isEntryDirectory(item)) return 'is-dir'
  const name = entryIconLookupText(item)
  if (/\.(wav|flac)$/i.test(name)) return 'is-audio-blue'
  if (/\.(mp3|m4a|ogg|aac|wma|opus|cue)$/i.test(name)) return 'is-audio-purple'
  if (/\.(jpg|jpeg|png|webp|gif|bmp|avif)$/i.test(name)) return 'is-image'
  if (/\.(mp4|mkv|avi|mov|wmv|webm|m4v)$/i.test(name)) return 'is-video'
  if (/\.(pdf)$/i.test(name)) return 'is-pdf'
  if (/\.(zip|7z|rar|tar|gz|bz2|xz)$/i.test(name)) return 'is-archive'
  if (/\.(srt|ass|ssa|vtt|lrc|txt|md|json)$/i.test(name)) return 'is-text'
  return 'is-file'
}

// ===================== 配对 / 字幕批量工作台模型 =====================
function pairWorkbenchModel(row) {
  if (isSubtitleBatchRootRow(row)) return null
  if (!isSubtitlePairRelatedRow(row)) return null
  const taskId = resolveSubtitleTaskId(row)
  const folderPath = resolveSubtitleFolderPath(row)
  if (!taskId && !folderPath) return null
  const awaiting = isAwaitingManualPair(row)
  const chips = []
  const unmatched = unmatchedAudioCount(row)
  const downloaded = Number(row?.detail?.downloaded_count || pairDetailPayload(row)?.downloaded_count || 0)
  const written = Number(row?.detail?.written_files_count || pairDetailPayload(row)?.written_files_count || 0)
  const rj = displayRjcode(row)
  if (rj && rj !== '—') chips.push(rj)
  if (downloaded > 0) chips.push(`抓到 ${downloaded}`)
  if (written > 0) chips.push(`写入 ${written}`)
  if (unmatched > 0) chips.push(`未配对音频 ${unmatched}`)
  return {
    awaiting,
    title: awaiting ? '这条记录还有字幕没完成配对' : '这条记录可回到字幕工作台查看',
    description: awaiting
      ? '直接打开库存里的字幕配对面板，继续处理还没来得及配对的音频和字幕。'
      : '会定位到对应字幕任务，方便复查当前配对状态和字幕目录。',
    buttonText: awaiting ? '继续配对' : '打开配对面板',
    chips,
  }
}

function pairResultModel(row) {
  if (!row) return null
  if (isSubtitleBatchRootRow(row)) return null
  if (!isSubtitlePairRelatedRow(row)) return null
  const detail = safeDetail(row)
  const pairRow = pairDetailRow(row)
  const pairDetail = pairDetailPayload(row)
  const changes = pairChangeRows(pairRow || row)
  const appliedPairs = Number(pairDetail.applied_pairs ?? pairDetail.manual_match_applied_pairs
    ?? detail.applied_pairs ?? detail.manual_match_applied_pairs ?? changes.length ?? 0)
  const deletedSubtitles = Number(pairDetail.deleted_subtitles ?? pairDetail.manual_match_deleted_subtitles
    ?? detail.deleted_subtitles ?? detail.manual_match_deleted_subtitles ?? 0)
  const unmatched = unmatchedAudioCount(row)
  const namingStrategy = String(pairDetail.naming_strategy || detail.naming_strategy || '').trim()
  const downloaded = Number(detail.downloaded_count || pairDetail.downloaded_count || 0)
  const written = Number(detail.written_files_count || pairDetail.written_files_count || 0)
  const summary = pairSummaryText(row) || String(row?.summary || '').trim()
  const hasData = Boolean(summary || changes.length || appliedPairs || deletedSubtitles || downloaded || written || unmatched)
  if (!hasData) return null
  const awaiting = isAwaitingManualPair(row)
  const completed = isManualPairCompleted(row)
  const status = completed ? 'success' : (awaiting ? 'warning' : 'default')
  const statusLabel = completed ? '已完成配对' : (awaiting ? '待手动配对' : '已抓取未继续')
  const metrics = [
    { label: '已配对', value: `${Math.max(0, appliedPairs)} 组` },
    { label: '未配对音频', value: `${Math.max(0, unmatched)} 个` },
    { label: '删除字幕', value: `${Math.max(0, deletedSubtitles)} 个` },
    { label: '抓取字幕', value: `${Math.max(0, downloaded)} 个` },
  ]
  if (written > 0) metrics.push({ label: '写入字幕', value: `${written} 个` })
  if (namingStrategy) metrics.push({ label: '命名策略', value: namingStrategy === 'audio' ? '按音频名' : namingStrategy })
  return {
    title: completed ? '字幕配对已落地' : '字幕配对状态',
    status, statusLabel, summary, metrics, changes,
  }
}

function subtitleBatchWorkbenchItems(row) {
  if (!isSubtitleBatchRootRow(row)) return []
  return collectChildRowsFromParent(row)
    .filter((it) => String(it?.category || '').trim() === 'subtitle_crawl')
    .map((it) => {
      const key = String(it?.id || it?.task_id || it?.source_path || '')
      const paired = isPairCompletedRow(it)
      const awaiting = isAwaitingManualPair(it)
      const d = safeDetail(it)
      const pd = pairDetailPayload(it)
      return {
        key,
        activityId: String(it?.id || ''),
        taskId: resolveSubtitleTaskId(it),
        folderPath: resolveSubtitleFolderPath(it),
        libraryId: resolveSubtitleLibraryId(it),
        rjcode: displayRjcode(it),
        folderName: String(d.folder_name || '').trim() || compactPath(it?.source_path || ''),
        createdAt: String(it?.created_at || '').trim(),
        sourceLabel: String(it?.source_label || d.source_label || humanAction(it) || '操作记录').trim(),
        summary: displaySummary(it),
        awaiting, paired,
        queueState: paired ? 'manual_match_completed' : (awaiting ? 'awaiting_manual_match' : 'queued'),
        downloadedCount: Number(d.downloaded_count || pd.downloaded_count || 0),
        existingSubtitleCount: Number(d.existing_subtitle_count || pd.existing_subtitle_count || 0),
        stateLabel: paired ? '配对✔' : (awaiting ? '待配对' : '已抓取'),
        stateClass: paired ? 'success' : (awaiting ? 'warning' : 'default'),
      }
    })
    .filter((it) => it.key && (it.taskId || it.folderPath))
}

function subtitleBatchWorkbenchModel(row) {
  if (!isSubtitleBatchRootRow(row)) return null
  const items = subtitleBatchWorkbenchItems(row)
  if (!items.length) return null
  return {
    items,
    pairedCount: items.filter((it) => it.stateClass === 'success').length,
    awaitingCount: items.filter((it) => it.stateClass === 'warning').length,
  }
}

// ===================== 操作动作中文化（humanAction） =====================
// 部分场景后端把 status 写成 'success'，但 summary / detail 显示已进了问题作品列表。
// 这里和 ActivityHistory.vue 的 effectiveStatus 保持同一套兜底关键词，避免列表 / 详情
// / 子任务列表三处状态文案不一致。
const _PARTIAL_SUCCESS_KEYWORDS_DETAIL = [
  '加入问题作品列表',
  '已转入问题作品',
  '按重复作品处理',
  '转入问题作品列表',
]

// 判断一条 partial_success（或语义上等价 partial_success）的 row 是否
// 「纯粹因为转入问题作品列表 / 重复作品」才被升级——没有任何真实 failed 子任务。
// 用于把"部分入库"区分成两种文案：
//   - 真实部分失败（child_failed > 0 或子状态里有 failed）→ "部分入库"
//   - 纯转入问题作品 / 软失败（无 failed，只有 problem 关键词 / partial 子任务）→ "转入问题作品"
function isPurelyProblemListPartial(row) {
  if (!row) return false
  // 任何一处显示「真的失败了」就不是纯问题作品 partial
  const failedChildren = Number(row.child_failed_count || 0)
  if (failedChildren > 0) return false

  const summary = String(row.summary || '')
  if (_PARTIAL_SUCCESS_KEYWORDS_DETAIL.some(kw => summary.includes(kw))) return true

  const detail = row.detail || {}
  if (detail && (detail.linked_subtitle_problem || detail.existing_subtitle_problem)) return true
  const sourceMode = String((detail && detail.source_mode) || '')
  if (sourceMode.endsWith('_existing_subtitle_conflict')) return true

  // 批次父行：后端 _enrich_lite_items_with_batch_summary 把"加入问题作品列表"等
  // 等价 partial_success 的子任务计入 child_partial_count。child_partial > 0 且
  // 没有 failed → 整批都是"软失败"，文案用"转入问题作品"。
  const partialChildren = Number(row.child_partial_count || 0)
  if (partialChildren > 0) return true

  return false
}

function bonusProbeDisplayState(row) {
  if (!row || String(row.category || '') !== 'circle_completion') return ''
  const detail = row.detail && typeof row.detail === 'object' ? row.detail : {}
  const sourceAction = String(row.source_action || detail.source_action || '').trim()
  if (sourceAction !== 'bonus_probe' && sourceAction !== 'new_release_bonus_probe') return ''

  const raw = String(row.status || '').trim()
  if (raw === 'cancelled' || raw === 'aborted') return 'cancelled'

  const probeStatus = String(detail.bonus_probe_status || '').trim()
  const hitCount = Number(detail.hit_count || 0)
  const hitRjcodes = Array.isArray(detail.bonus_hit_rjcodes) ? detail.bonus_hit_rjcodes.length : 0
  if (probeStatus === 'hit' || hitCount > 0 || hitRjcodes > 0) return 'success'

  const summary = String(row.summary || '')
  const noConclusion = summary.includes('超出预算')
    || summary.includes('未产出无特典结论')
    || summary.includes('未完成结论')
  if (noConclusion) return 'incomplete'
  if (probeStatus === 'miss') return 'incomplete'

  return ''
}

function effectiveRowStatus(row) {
  if (!row) return ''
  const bonusState = bonusProbeDisplayState(row)
  if (bonusState) return bonusState

  const raw = String(row.status || '')

  // 批次父行的子任务状态感知（与 ActivityHistory.vue 的 effectiveStatus 同口径）：
  // 后端 _enrich_lite_items_with_batch_summary 把同 batch_id 的子任务 failed/success/
  // partial_success 计数挂到 row。如果父行写日志时 status="success"（创建任务那一刻
  // 成功），但子任务实际有失败 / 部分成功，就把状态升级，避免抽屉头部显示"入库完成 ✓"
  // 但关联事件里子任务"解压入库部分成功"的认知错位。
  // 只升级 success/completed/partial_success 这三种"看起来 OK"的态。
  if (raw === 'success' || raw === 'completed' || raw === 'partial_success') {
    const failedChildren = Number(row.child_failed_count || 0)
    const partialChildren = Number(row.child_partial_count || 0)
    const successChildren = Number(row.child_success_count || 0)
    if (failedChildren > 0) {
      const okChildren = successChildren + partialChildren
      return okChildren > 0 ? 'partial_success' : 'failed'
    }
    if (partialChildren > 0) {
      return 'partial_success'
    }
  }

  if (raw !== 'success') return raw
  const summary = String(row.summary || '')
  if (_PARTIAL_SUCCESS_KEYWORDS_DETAIL.some(kw => summary.includes(kw))) return 'partial_success'
  const detail = row.detail || {}
  if (detail && (detail.linked_subtitle_problem || detail.existing_subtitle_problem)) {
    return 'partial_success'
  }
  const sourceMode = String((detail && detail.source_mode) || '')
  if (sourceMode.endsWith('_existing_subtitle_conflict')) return 'partial_success'
  return raw
}

function humanAction(row) {
  const detail = safeDetail(row)
  const sourceAction = String(row?.source_action || detail.source_action || '').trim()
  const isReimport = sourceAction === 'reimport_local_download_root' || sourceAction === 'reimport_downloaded_session'
  if (row?.is_tree_child) {
    if (row.relation === 'rerun') return row.status === 'success' ? '重试完成' : (row.status === 'failed' ? '重试失败' : '重试')
    if (row.relation === 'subtitle_import') return row.status === 'success' ? '字幕补配完成' : (row.status === 'failed' ? '字幕补配失败' : '字幕补配')
    if (row.relation === 'pair') return row.status === 'success' ? '字幕手动配对完成' : '字幕手动配对'
    if (row.relation === 'delete_apply') {
      if (row.status === 'success') return '删除执行完成'
      if (row.status === 'partial_success') return '删除执行部分成功'
      if (row.status === 'cancelled') return '删除执行已停止'
      if (row.status === 'failed') return '删除执行失败'
      return '删除执行'
    }
    if (row.relation === 'retry_apply' || row.relation === 'retry_preview' || row.action === 'filter_delete_preview_retry') {
      if (row.status === 'success') return '补充删除完成'
      if (row.status === 'partial_success') return '补充删除部分成功'
      if (row.status === 'cancelled') return '补充删除已停止'
      if (row.status === 'failed') return '补充删除失败'
      return '补充删除'
    }
    if (row.relation === 'asmr_resource') return row.status === 'success' ? '文件下载完成' : '文件下载'
    if (row.relation === 'asmr_upload') return row.status === 'success' ? '文件上传完成' : '文件上传'
    if (row.relation === 'asmr_verify_failed') return '文件校验失败'
    if (row.relation === 'asmr_plan') return '下载计划已生成'
    if (row.relation === 'asmr_session') return displaySummary(row) || '下载会话'
  }
  // 父任务 / 主行：用 effectiveRowStatus 把"实际进了问题作品列表的 success"降级成 partial_success。
  // 子任务（is_tree_child）保留原 status，因为它们一般是细粒度记录，不需要兜底翻转。
  const cat = row?.category, status = effectiveRowStatus(row), action = row?.action

  // 用户在问题作品页面拍板后，原任务的 task_finished 行被回写为已跳过 / 已保留新版 / 已合并；
  // detail.conflict_resolution_action 是后端写回的标记，这里优先按它出文案，
  // 否则各 category 分支会把 cancelled 映射成笼统的"已取消"，看不出是用户主动决断的结果。
  const conflictAction = String(detail?.conflict_resolution_action || '').trim().toUpperCase()
  if (conflictAction && (action === 'task_finished' || action === 'task_finished_incomplete')) {
    if (conflictAction === 'SKIP') return '已跳过'
    if (conflictAction === 'KEEP_NEW') return '已保留新版'
    if (conflictAction === 'MERGE') return '已合并'
  }

  if (cat === 'pipeline_filter') {
    if (action === 'filter_delete_preview') {
      if (status === 'success') return '删除过滤预审完成'
      if (status === 'cancelled') return '删除过滤预审已取消'
      if (status === 'failed') return '删除过滤预审失败'
      return '删除过滤预审'
    }
    if (action === 'filter_delete_apply') {
      if (status === 'success') return '删除过滤执行完成'
      if (status === 'partial_success') return '删除过滤执行部分成功'
      if (status === 'cancelled') return '删除过滤执行已停止'
      if (status === 'failed') return '删除过滤执行失败'
      return '删除过滤执行'
    }
    if (action === 'filter_delete_preview_retry') {
      if (status === 'success') return '删除过滤失败项重试完成'
      if (status === 'partial_success') return '删除过滤失败项重试部分成功'
      if (status === 'failed') return '删除过滤失败项重试失败'
      return '删除过滤失败项重试'
    }
    return '作品筛选处理'
  }
  if (cat === 'subtitle_crawl') {
    if (action === 'batch_start') {
      if (status === 'success') return '批量字幕任务创建完成'
      if (status === 'partial_success') return '批量字幕任务创建部分成功'
      if (status === 'failed') return '批量字幕任务创建失败'
      return '批量字幕任务创建'
    }
    if (status === 'success') return 'RJ 字幕爬取完成'
    if (status === 'failed') return 'RJ 字幕爬取失败'
    if (status === 'waiting') return 'RJ 字幕任务等待中'
  }
  if (cat === 'subtitle_pair') return status === 'success' ? '字幕手动配对完成' : '字幕手动配对'
  if (cat === 'subtitle_import') {
    if (action === 'archive_import') return status === 'success' ? '压缩包字幕补配完成' : '压缩包字幕补配失败'
    if (action === 'folder_import') return status === 'success' ? '文件夹字幕补配完成' : '文件夹字幕补配失败'
    if (action === 'pending_execute') return status === 'success' ? '预检单字幕补配完成' : '预检单字幕补配失败'
    return '字幕补配'
  }
  if (cat === 'extract') return status === 'success' ? '压缩包解压完成' : '压缩包解压失败'
  if (cat === 'auto_import') {
    if (action === 'batch_start') {
      if (status === 'success' || status === 'completed') return '已提交解压任务'
      if (status === 'partial_success') return '部分提交解压任务'
      if (status === 'failed') return '提交解压任务失败'
      return '创建解压任务'
    }
    if (status === 'success') return '解压入库完成'
    if (status === 'partial_success') {
      return isPurelyProblemListPartial(row) ? '转入问题作品' : '解压入库部分成功'
    }
    if (status === 'failed') return '解压入库失败'
    if (status === 'incomplete') return '解压入库未正常结束'
  }
  if (cat === 'process_existing') {
    if (action === 'batch_start') {
      if (status === 'success' || status === 'completed') return '已提交已有目录处理'
      if (status === 'partial_success') return '部分提交已有目录处理'
      if (status === 'failed') return '提交已有目录处理失败'
      return '创建已有目录处理任务'
    }
    return status === 'success' ? '已有目录处理完成' : '已有目录处理失败'
  }
  if (cat === 'upload') {
    if (status === 'success') return '库存上传完成'
    if (status === 'failed') return '库存上传失败'
    if (status === 'cancelled') return '库存上传已取消'
    if (status === 'incomplete') return '库存上传未正常结束'
    return '库存上传'
  }
  if (cat === 'pipeline_metadata') return '元数据整理'
  if (cat === 'pipeline_rename') {
    if (action === 'batch_api_rename') {
      if (status === 'success') return '批量 API 重命名完成'
      if (status === 'partial_success') return '批量 API 重命名部分成功'
      if (status === 'failed') return '批量 API 重命名失败'
      return '批量 API 重命名'
    }
    if (action === 'batch_manual_rename') {
      if (status === 'success') return '批量乱码修复完成'
      if (status === 'partial_success') return '批量乱码修复部分成功'
      if (status === 'failed') return '批量乱码修复失败'
      return '批量乱码修复'
    }
    if (isApiRenameAction(row)) {
      if (status === 'success') return 'API重命名完成'
      if (status === 'failed') return 'API重命名失败'
      return 'API重命名'
    }
    if (isManualRenameAction(row)) {
      if (status === 'success') return '重命名完成'
      if (status === 'failed') return '重命名失败'
      return '重命名'
    }
    return '重命名处理'
  }
  if (cat === 'pipeline_delete') {
    if (action === 'batch_api_delete') {
      if (status === 'success') return '批量删除完成'
      if (status === 'partial_success') return '批量删除部分成功'
      if (status === 'failed') return '批量删除失败'
      return '批量删除'
    }
    if (action === 'delete' || action === 'batch_delete_item') {
      if (status === 'success') return '删除完成'
      if (status === 'failed') return '删除失败'
      return '删除'
    }
    return '删除处理'
  }
  if (cat === 'asmr_sync') {
    if (isReimport) {
      if (action === 'task_retried') return '直接入库任务已创建'
      if (action === 'session_started') return '直接入库任务开始'
      if (action === 'session_partial_failed') return '直接入库部分失败'
      if (action === 'session_completed') return '直接入库完成'
      if (status === 'success') return '直接入库完成'
      if (status === 'failed') return '直接入库失败'
    }
    if (action === 'enhanced_plan_created') return '增强下载计划已生成'
    if (action === 'enhanced_plan_failed') return '增强下载计划生成失败'
    if (action === 'session_started') return 'ASMR 下载任务开始'
    if (action === 'session_partial_failed') return 'ASMR 下载任务部分失败'
    if (action === 'session_completed') return 'ASMR 下载任务完成'
    if (status === 'success') return 'ASMR 同步下载完成'
    if (status === 'failed') return 'ASMR 同步下载失败'
  }
  if (cat === 'circle_completion') {
    if (sourceAction === 'bonus_probe' || sourceAction === 'new_release_bonus_probe') {
      const label = sourceAction === 'new_release_bonus_probe' ? '新作特典探测' : '特典补全'
      const bonusState = bonusProbeDisplayState(row)
      if (bonusState === 'success') return label
      if (bonusState === 'incomplete') {
        const summary = String(row.summary || '')
        return summary.includes('超出预算') || summary.includes('未产出无特典结论')
          ? `${label}未完成`
          : '未找到特典'
      }
      if (bonusState === 'cancelled') return `${label}已取消`
      if (status === 'failed') return `${label}失败`
      return label
    }
    if (action === 'index_completed') return status === 'success' ? '创建索引检索成功' : '创建索引检索失败'
    if (action === 'index_failed') return '创建索引检索失败'
    if (action === 'refresh_selected_works') return status === 'success' ? '社团作品信息更新' : '社团作品信息更新失败'
    if (action === 'download_batch_start') return '创建下载任务'
    if (action === 'download_item_queued') return '下载任务已加入队列'
    if (action === 'task_finished' || action === 'task_finished_incomplete') {
      if (sourceAction === 'refresh_selected') {
        if (status === 'success') return '社团作品信息更新完成'
        if (status === 'incomplete') return '社团作品信息更新未正常结束'
        if (status === 'failed') return '社团作品信息更新失败'
        return '社团作品信息更新'
      }
      if (sourceAction === 'index_circle' || sourceAction === 'circle_index') {
        if (status === 'success') return '社团补全完成'
        if (status === 'incomplete') return '社团补全未正常结束'
        if (status === 'failed') return '社团补全失败'
        return '社团补全'
      }
    }
    if (status === 'success') return '社团补全完成'
    if (status === 'failed') return '社团补全失败'
  }
  if (cat === 'email_watcher') {
    if (action === 'fetch_check') return '监视新作'
    if (action === 'circle_index_triggered') return status === 'success' ? '新作索引完成' : '新作索引失败'
    return '邮件监听'
  }
  if (status === 'waiting' && (action === 'task_finished' || action === 'task_finished_incomplete')) return '等待处理'
  // 兜底：用 status 转中文，绝不再 expose 像 task_finished / batch_start 这种 raw English action
  const statusLabel = ({
    success: '完成',
    completed: '完成',
    failed: '失败',
    error: '失败',
    cancelled: '已取消',
    aborted: '已取消',
    partial_success: '部分成功',
    waiting: '等待中',
    queued: '排队中',
    running: '执行中',
    incomplete: '未完成'
  })[status]
  if (statusLabel) return statusLabel
  return '关联操作'
}

// ===================== 社团补全模型 =====================
// 用户的诉求：列表里只保留对自己有用的“服务器收录类型”，
// ENG 等英语翻译版本不展示；preferred_variant_label 转成更直观的“原作 / 翻译作·简中”等。
const _ENG_VARIANT_RE = /(\bENG\b|英文|english)/i

function _isEnglishVariant(label) {
  return _ENG_VARIANT_RE.test(String(label || ''))
}

function _deriveVariantTypeTag(label) {
  const text = String(label || '').trim()
  if (!text) return ''
  if (/简中/.test(text)) return '翻译作·简中'
  if (/繁中/.test(text)) return '翻译作·繁中'
  if (/原版|日文原版|\bJPN\b/i.test(text)) return '原作'
  // 兜底：去掉“优先版本”前缀，保留语种字样
  return text.replace(/^优先版本\s*/, '') || text
}

function circleCompletionIndexModel(row) {
  if (!row || row.category !== 'circle_completion' || row.action !== 'index_completed') return null
  const d = safeDetail(row)
  const sourceBreakdown = Array.isArray(d.source_breakdown)
    ? d.source_breakdown
        .map((it) => ({
          key: String(it?.key || '').trim(),
          label: String(it?.label || it?.key || '未命名'),
          count: Number(it?.count || 0),
        }))
        .filter((it) => it.key)
    : []
  const workSections = Array.isArray(d.work_sections)
    ? d.work_sections
        .map((s) => ({
          key: String(s?.key || '').trim(),
          count: Number(s?.count || 0),
          rows: Array.isArray(s?.rows) ? s.rows
            .filter((it) => !_isEnglishVariant(it?.preferred_variant_label))
            .map((it) => {
              const rawLabel = String(it?.preferred_variant_label || '').trim()
              const kikoeruTags = Array.isArray(it?.source_compare?.kikoeru?.tags)
                ? it.source_compare.kikoeru.tags.filter(Boolean)
                : []
              const subtitleRjcodes = Array.isArray(it?.source_compare?.kikoeru?.subtitle_rjcodes)
                ? it.source_compare.kikoeru.subtitle_rjcodes.filter(Boolean)
                : []
              const originalSubtitlePresent = Boolean(it?.original_subtitle_present)
                || subtitleRjcodes.includes(String(it?.canonical_rjcode || '').trim())
              return {
                canonical_rjcode: String(it?.canonical_rjcode || '').trim(),
                workRjcode: String(it?.work_rjcode || it?.canonical_rjcode || '').trim(),
                display_rjcode: String(it?.display_rjcode || '').trim(),
                title: String(it?.title || '').trim(),
                isBonusWork: Boolean(it?.is_bonus_work),
                hasBonus: Boolean(it?.has_bonus),
                originalSubtitlePresent,
                preferred_variant_label: rawLabel,
                variantTypeTag: _deriveVariantTypeTag(rawLabel),
                hasSubtitleTag: kikoeruTags.includes('字幕') || Boolean(it?.source_compare?.kikoeru?.subtitle_present),
                statusLabel: String(it?.status_label || '').trim() || '未标记',
                statusKey: String(it?.status_key || '').trim() || 'unknown',
                sourceCompare: {
                  kikoeru: {
                    primary_rjcode: String(it?.source_compare?.kikoeru?.primary_rjcode || '').trim(),
                    primaryBadge: String(it?.source_compare?.kikoeru?.primary_badge || '').trim(),
                    variantBadges: Array.isArray(it?.source_compare?.kikoeru?.variant_badges) && it.source_compare.kikoeru.variant_badges.length
                      ? it.source_compare.kikoeru.variant_badges.filter(Boolean)
                      : (String(it?.source_compare?.kikoeru?.primary_badge || '').trim() ? [String(it.source_compare.kikoeru.primary_badge).trim()] : []),
                    all_rjcodes: Array.isArray(it?.source_compare?.kikoeru?.all_rjcodes) ? it.source_compare.kikoeru.all_rjcodes.filter(Boolean) : [],
                    tags: kikoeruTags,
                  },
                  dlsite: {
                    all_rjcodes: Array.isArray(it?.source_compare?.dlsite?.all_rjcodes) ? it.source_compare.dlsite.all_rjcodes.filter(Boolean) : [],
                  },
                  asmr_one: {
                    primary_rjcode: String(it?.source_compare?.asmr_one?.primary_rjcode || '').trim(),
                    primaryBadge: String(it?.source_compare?.asmr_one?.primary_badge || '').trim(),
                    all_rjcodes: Array.isArray(it?.source_compare?.asmr_one?.all_rjcodes) ? it.source_compare.asmr_one.all_rjcodes.filter(Boolean) : [],
                  },
                },
              }
            }) : [],
        }))
        .filter((s) => s.key && s.rows.length)
    : []
  const rows = workSections.flatMap((s) => s.rows || [])
  if (!sourceBreakdown.length && !rows.length) return null
  return {
    priorityRule: String(d.priority_rule || '简体 > 繁体 > 原作'),
    forceRefresh: Boolean(d.force_refresh),
    includeDlsite: Boolean(d.include_dlsite),
    includeKikoeru: Boolean(d.include_kikoeru),
    sourceBreakdown,
    rows,
  }
}

function buildCircleCompletionRefreshModel(row, refreshFilter) {
  if (!row || row.category !== 'circle_completion' || row.action !== 'refresh_selected_works') return null
  const d = safeDetail(row)
  const rawItems = Array.isArray(d.refreshed_items)
    ? d.refreshed_items
        .map((it) => ({
          canonical_rjcode: String(it?.canonical_rjcode || '').trim(),
          title: String(it?.title || '').trim(),
          display_rjcode: String(it?.display_rjcode || it?.canonical_rjcode || '').trim(),
          preferred_variant_label: String(it?.preferred_variant_label || '').trim(),
          has_kikoeru: Boolean(it?.has_kikoeru),
          has_asmr_one: Boolean(it?.has_asmr_one),
          asmrAvailableRjcode: String(it?.asmr_available_rjcode || '').trim(),
          serverMatchPrimaryRjcode: String(it?.server_match_primary_rjcode || '').trim(),
          serverMatchRjcodes: Array.isArray(it?.server_match_rjcodes) ? it.server_match_rjcodes.map((c) => String(c || '').trim()).filter(Boolean) : [],
          subtitlePresent: Boolean(it?.subtitle_present),
          changed: Boolean(it?.changed),
          resultStatus: it?.has_kikoeru ? 'owned' : (it?.has_asmr_one ? 'downloadable' : 'missing'),
          resultLabel: it?.has_kikoeru ? '库存已收录' : (it?.has_asmr_one ? 'asmr.one 可下载' : '无来源'),
          changeDetails: Array.isArray(it?.change_details)
            ? it.change_details
                .map((c) => ({
                  key: String(c?.key || '').trim(),
                  label: String(c?.label || '').trim() || '状态变更',
                  before: c?.before, after: c?.after,
                }))
                .filter((c) => c.key)
            : [],
        }))
        .filter((it) => it.canonical_rjcode)
    : []
  if (!rawItems.length) return null
  const filtered = rawItems.filter((it) => {
    if (refreshFilter === 'changed') return it.changed
    if (refreshFilter === 'unchanged') return !it.changed
    return true
  })
  const items = [...filtered].sort((l, r) => {
    const lc = l.changeDetails.some((c) => c.key === 'server_state')
    const rc = r.changeDetails.some((c) => c.key === 'server_state')
    if (l.changed !== r.changed) return l.changed ? -1 : 1
    if (lc !== rc) return lc ? -1 : 1
    return String(l.display_rjcode || l.canonical_rjcode).localeCompare(String(r.display_rjcode || r.canonical_rjcode))
  })
  return {
    selectedCount: Number(d.selected_count || rawItems.length),
    refreshedCount: Number(d.refreshed_count || rawItems.length),
    changedCount: Number(d.changed_count || rawItems.filter((it) => it.changed).length),
    serverMatchedCount: Number(d.kikoeru_owned_count || rawItems.filter((it) => it.has_kikoeru).length),
    filteredCount: items.length,
    items,
  }
}

function formatRefreshChangeValue(value) {
  if (Array.isArray(value)) {
    const norm = value.map((it) => String(it || '').trim()).filter(Boolean)
    return norm.length ? norm.join(' / ') : '—'
  }
  return String(value ?? '').trim() || '—'
}

function normalizeKikoeruTags(tags) {
  const source = Array.isArray(tags) ? tags : []
  const norm = []
  for (const tag of source) {
    const text = String(tag || '').trim()
    if (!text) continue
    const value = text.startsWith('字幕') ? '字幕' : text
    if (!norm.includes(value)) norm.push(value)
  }
  return norm
}

function circleIndexSourceTone(sourceKey, item) {
  if (sourceKey === 'kikoeru') return item?.sourceCompare?.kikoeru?.primary_rjcode ? 'check' : 'empty'
  if (sourceKey === 'dlsite') return Array.isArray(item?.sourceCompare?.dlsite?.all_rjcodes) && item.sourceCompare.dlsite.all_rjcodes.length ? 'check' : 'empty'
  if (sourceKey === 'asmr_one') return item?.sourceCompare?.asmr_one?.primary_rjcode ? 'check' : 'empty'
  return 'empty'
}

function circleIndexSourceIcon(sourceKey, item) {
  return circleIndexSourceTone(sourceKey, item) === 'check' ? CheckCircle2 : MinusCircle
}

function bonusProbeModel(row) {
  if (!row || String(row.category || '').trim() !== 'circle_completion') return null
  const d = safeDetail(row)
  const sourceAction = String(d.source_action || '').trim()
  const isBonusProbe = sourceAction === 'bonus_probe'
    || sourceAction === 'new_release_bonus_probe'
    || String(d.bonus_probe_status || '').trim()
  if (!isBonusProbe) return null
  const circleName = String(d.circle_name || '').trim()

  const rjcodes = Array.isArray(d.bonus_hit_rjcodes)
    ? d.bonus_hit_rjcodes.map((it) => normalizeRjcode(it)).filter(Boolean)
    : []
  const itemMap = new Map()
  for (const item of Array.isArray(d.bonus_hit_items) ? d.bonus_hit_items : []) {
    const rjcode = normalizeRjcode(item?.rjcode)
    if (!rjcode) continue
    itemMap.set(rjcode, {
      rjcode,
      title: String(item?.title || '').trim(),
      releaseDate: formatReleaseDate(item?.release_date),
      makerId: String(item?.maker_id || '').trim(),
      circleName: String(item?.circle_name || circleName || '').trim(),
      coverUrl: String(item?.cover_url || item?.image_url || buildDlsiteCoverUrl(rjcode)).trim(),
      source: String(item?.source || '').trim(),
    })
  }
  for (const rjcode of rjcodes) {
    if (!itemMap.has(rjcode)) itemMap.set(rjcode, {
      rjcode,
      title: '',
      releaseDate: '',
      makerId: '',
      circleName,
      coverUrl: buildDlsiteCoverUrl(rjcode),
      source: '',
    })
  }

  const items = Array.from(itemMap.values())
  const dateRows = (Array.isArray(d.bonus_date_results) ? d.bonus_date_results : [])
    .map((it) => ({
      releaseDate: formatReleaseDate(it?.release_date),
      probeCount: Number(it?.probe_count || 0),
      candidateCount: Number(it?.candidate_count || 0),
      cachedCandidateCount: Number(it?.cached_candidate_count || 0),
      requestCount: Number(it?.request_count || 0),
      hitCount: Number(it?.hit_count || 0),
      insertedCount: Number(it?.inserted_count || 0),
      skipped: Boolean(it?.skipped),
      skipReason: String(it?.skip_reason || '').trim(),
      hitRjcodes: Array.isArray(it?.hit_rjcodes) ? it.hit_rjcodes.map((rj) => normalizeRjcode(rj)).filter(Boolean) : [],
    }))
    .filter((it) => it.releaseDate || it.probeCount || it.hitCount || it.skipped)

  const hitCount = Number(d.hit_count || items.length || 0)
  const insertedCount = Number(d.inserted_count || 0)
  const candidateCount = Number(d.candidate_count || 0)
  const cachedCandidateCount = Number(d.cached_candidate_count || 0)
  const hasCandidateMetrics = Object.prototype.hasOwnProperty.call(d, 'candidate_count')
  const probeCount = Number(d.probe_count || 0)
  const requestCount = Number(d.request_count || 0)
  const releaseDateCount = Array.isArray(d.release_dates) ? d.release_dates.length : dateRows.length
  const summary = String(row.summary || '')
  const noConclusion = summary.includes('超出预算')
    || summary.includes('未产出无特典结论')
    || summary.includes('未完成结论')
  const rawProbeStatus = String(d.bonus_probe_status || '').trim()
  const status = noConclusion
    ? 'incomplete'
    : (items.length || rawProbeStatus === 'hit' ? 'hit' : 'miss')
  const statusLabel = status === 'hit'
    ? '已找到特典'
    : (status === 'incomplete' ? '未完成结论' : '未找到特典')
  const metrics = [
    { label: '命中', value: String(hitCount) },
    { label: '写入', value: String(insertedCount) },
    ...(hasCandidateMetrics ? [
      { label: '候选筛选', value: String(candidateCount) },
      { label: '缓存跳过', value: String(cachedCandidateCount) },
    ] : []),
    { label: '实际探测', value: String(probeCount) },
    { label: '请求', value: String(requestCount) },
    { label: '发售日', value: String(releaseDateCount) },
  ]
  return {
    status,
    statusLabel,
    sourceLabel: sourceAction === 'new_release_bonus_probe' ? '邮件新作探测' : '社团特典补全',
    circleName,
    title: status === 'hit'
      ? `找到 ${items.length} 个特典`
      : (status === 'incomplete' ? '探测未完成，未产出无特典结论' : '未找到符合条件的特典'),
    emptyText: status === 'incomplete'
      ? '本次探测未完成，没有产出无特典结论。'
      : '已完成本次特典筛选，但没有命中隐藏特典条件的 RJ。',
    items,
    dateRows,
    metrics,
  }
}

// ===================== 邮件监听新作模型 =====================
// DLsite 新作通知邮件主题里通常带「社团名」，
// 后端旧记录里 detail.items / 子任务的 circle_name 可能为空，
// 这里做前端兜底，从 mail_subject 解析社团名，避免详情里出现 “本批次未解析到社团名”。
const _SUBJECT_CIRCLE_NAME_RE = /「([^」]+)」\s*(?:から|の)\s*新(?:着|作)/

function extractCircleNameFromSubject(subject) {
  const text = String(subject || '').trim()
  if (!text) return ''
  const match = text.match(_SUBJECT_CIRCLE_NAME_RE)
  if (!match) return ''
  return String(match[1] || '').trim().slice(0, 160)
}

function emailWatcherBatchModel(row) {
  if (!row || String(row.category || '').trim() !== 'email_watcher') return null
  if (String(row.action || '').trim() !== 'fetch_check') return null
  const d = safeDetail(row)
  const childRows = collectChildRowsFromParent(row)
    .filter((it) => String(it?.category || '').trim() === 'email_watcher')

  const childItems = childRows.map((it) => {
    const cd = safeDetail(it)
    const status = String(it?.status || '').trim()
    const rawCircleName = String(cd.circle_name || cd.mail_circle_name || '').trim()
    const circleName = rawCircleName || extractCircleNameFromSubject(cd.mail_subject)
    return {
      rjcode: String(it?.rjcode || cd.rjcode || '').trim().toUpperCase(),
      title: String(cd.work_title || cd.title || '').trim(),
      circleName,
      priceText: String(cd.price_text || '').trim(),
      workType: String(cd.work_type || '').trim(),
      coverUrl: String(cd.image_url || '').trim(),
      releaseDate: formatReleaseDate(cd.release_date),
      productUrl: String(cd.product_url || '').trim(),
      indexMode: String(cd.index_mode || '').trim(),
      backfillMode: String(cd.backfill_mode || '').trim(),
      backfillTriggered: Boolean(cd.backfill_triggered),
      statusKey: status === 'success' ? 'success' : 'failed',
      statusLabel: status === 'success' ? '索引完成' : '索引失败',
      note: status === 'success'
        ? (String(cd.backfill_mode || circleName || '').trim() || '已完成社团索引')
        : (String(cd.error || it?.summary || '').trim() || '索引失败'),
    }
  })

  const fallbackItems = (Array.isArray(d.items) ? d.items : []).map((it) => {
    const rawCircleName = String(it?.circle_name || '').trim()
    return {
      rjcode: String(it?.rjcode || '').trim().toUpperCase(),
      title: String(it?.title || '').trim(),
      circleName: rawCircleName || extractCircleNameFromSubject(it?.mail_subject),
      priceText: String(it?.price_text || '').trim(),
      workType: String(it?.work_type || '').trim(),
      coverUrl: String(it?.image_url || '').trim(),
      releaseDate: formatReleaseDate(it?.release_date),
      productUrl: String(it?.product_url || '').trim(),
      indexMode: '', backfillMode: '', backfillTriggered: false,
      statusKey: 'default', statusLabel: '待处理',
      note: String(it?.mail_subject || '').trim() || '等待异步索引结果',
    }
  })

  const items = childItems.length ? childItems : fallbackItems
  if (!items.length) return null
  const mailSubjects = Array.from(new Set(
    (Array.isArray(d.mail_summaries) ? d.mail_summaries : []).map((it) => String(it?.subject || '').trim()).filter(Boolean)
  ))
  // 顶部社团名展示：合并 items 解析结果 + 邮件主题兜底，
  // 旧记录即使 item.circleName 全部为空，只要主题能解出社团名也能显示。
  const circleNamesFromItems = items.map((it) => String(it.circleName || '').trim()).filter(Boolean)
  const circleNamesFromSubjects = mailSubjects
    .map((subject) => extractCircleNameFromSubject(subject))
    .filter(Boolean)
  const circleNames = Array.from(new Set([...circleNamesFromItems, ...circleNamesFromSubjects]))
  return {
    items,
    totalCount: items.length,
    successCount: items.filter((it) => it.statusKey === 'success').length,
    failedCount: items.filter((it) => it.statusKey === 'failed').length,
    mailCount: Number(d.unseen_total || mailSubjects.length || 0),
    mailSubjects,
    circleNamesText: circleNames.join(' / '),
  }
}

function handleEmailWatchCoverError(event, item) {
  const target = event?.currentTarget
  if (!target) return
  const fallback = buildDlsiteCoverUrl(item?.rjcode)
  if (fallback && target.src !== fallback) {
    target.src = fallback
    return
  }
  item.coverUrl = ''
}

// ===================== 原始 JSON =====================
function stringifyDetailPreview(detail) {
  const seen = new WeakSet()
  const maxDepth = 4, maxArr = 80, maxObj = 80, maxStr = 1200, maxOut = 60000
  const compact = (v, depth = 0) => {
    if (v === null || typeof v !== 'object') {
      if (typeof v === 'string' && v.length > maxStr) return `${v.slice(0, maxStr)}...（已截断 ${v.length - maxStr} 字符）`
      return v
    }
    if (seen.has(v)) return '[Circular]'
    if (depth >= maxDepth) return Array.isArray(v) ? `[Array(${v.length})]` : `[Object(${Object.keys(v).length})]`
    seen.add(v)
    if (Array.isArray(v)) {
      const out = v.slice(0, maxArr).map((x) => compact(x, depth + 1))
      if (v.length > maxArr) out.push(`...（已省略 ${v.length - maxArr} 项）`)
      return out
    }
    const entries = Object.entries(v)
    const out = {}
    for (const [k, c] of entries.slice(0, maxObj)) out[k] = compact(c, depth + 1)
    if (entries.length > maxObj) out.__truncated_keys__ = `已省略 ${entries.length - maxObj} 个字段`
    return out
  }
  const text = JSON.stringify(compact(detail), null, 2)
  if (text.length <= maxOut) return text
  return `${text.slice(0, maxOut)}\n...（原始 JSON 过大，已截断 ${text.length - maxOut} 字符）`
}

function prettyDetail(row) {
  if (!row?.detail || typeof row.detail !== 'object') return ''
  if (String(row?.detail?.mode || '').startsWith('filter_delete_')) return ''
  try {
    return stringifyDetailPreview(row.detail)
  } catch {
    return ''
  }
}

// ===================== 主 composable =====================
export function useActivityDetailModels(rowRef) {
  // 受 row 影响但有自己 UI 状态的 ref
  const compareSearchQuery = ref('')
  const compareSourceFilter = ref('all')
  const compareVariantFilter = ref('all')
  const compareExpanded = ref(true)
  const circleRefreshFilter = ref('all')
  const circleRefreshPage = ref(1)
  const circleRefreshPageSize = 10
  const collapsedEntrySectionKeys = ref(new Set())
  const collapsedEntryTreeRowKeys = ref(new Set())
  const batchWorkbenchAwaitingOnly = ref(false)
  const selectedBatchWorkbenchKeys = ref([])

  // 切换 row 时重置所有 UI 状态
  watch(rowRef, (next) => {
    compareSearchQuery.value = ''
    compareSourceFilter.value = 'all'
    compareVariantFilter.value = 'all'
    compareExpanded.value = true
    circleRefreshFilter.value = 'all'
    circleRefreshPage.value = 1
    collapsedEntrySectionKeys.value = new Set()
    collapsedEntryTreeRowKeys.value = new Set()
    batchWorkbenchAwaitingOnly.value = false
    // 默认勾选所有可定位项
    const items = subtitleBatchWorkbenchItems(next)
    selectedBatchWorkbenchKeys.value = items.map((it) => it.key)
  }, { immediate: true })

  // ========= computed =========
  const summaryText = computed(() => displaySummary(rowRef.value))
  const rjText = computed(() => displayRjcode(rowRef.value))
  const tags = computed(() => rowCategoryTags(rowRef.value))
  const finalLabel = computed(() => finalStatusLabel(rowRef.value))
  const finalCls = computed(() => finalStatusClass(rowRef.value))
  const isRerun = computed(() => isRerunRow(rowRef.value))
  const isRecovered = computed(() => isRecoveredFailure(rowRef.value))

  const pathCompare = computed(() => pathCompareModel(rowRef.value))
  const pathCompareCls = computed(() => pathCompareReasonClass(rowRef.value))
  const pathCompareReason = computed(() => pathCompareDefaultReason(rowRef.value))

  const highlights = computed(() => detailHighlights(rowRef.value))
  const filterDeleteMetrics = computed(() => filterDeleteMetricCards(rowRef.value))
  const uploadMetrics = computed(() => uploadMetricCards(rowRef.value))
  const rawJson = computed(() => prettyDetail(rowRef.value))

  const entrySections = computed(() => activityEntrySections(rowRef.value))
  const entrySectionTitle = computed(() => activityEntrySectionTitle(rowRef.value))

  const pairWorkbench = computed(() => pairWorkbenchModel(rowRef.value))
  const pairResult = computed(() => pairResultModel(rowRef.value))

  const subtitleBatchModel = computed(() => subtitleBatchWorkbenchModel(rowRef.value))
  const visibleBatchItems = computed(() => {
    if (!subtitleBatchModel.value) return []
    const items = subtitleBatchModel.value.items
    return batchWorkbenchAwaitingOnly.value ? items.filter((it) => it.stateClass === 'warning') : items
  })
  const allBatchSelected = computed(() => {
    const items = visibleBatchItems.value
    if (!items.length) return false
    const sel = new Set(selectedBatchWorkbenchKeys.value)
    return items.every((it) => sel.has(it.key))
  })
  const selectedBatchItems = computed(() => {
    if (!subtitleBatchModel.value) return []
    const sel = new Set(selectedBatchWorkbenchKeys.value)
    return subtitleBatchModel.value.items.filter((it) => sel.has(it.key))
  })

  function toggleAllBatchItems(checked) {
    selectedBatchWorkbenchKeys.value = checked ? visibleBatchItems.value.map((it) => it.key) : []
  }
  function selectAwaitingBatchItems() {
    if (!subtitleBatchModel.value) return
    selectedBatchWorkbenchKeys.value = subtitleBatchModel.value.items
      .filter((it) => it.stateClass === 'warning').map((it) => it.key)
  }

  const circleIndexModel = computed(() => circleCompletionIndexModel(rowRef.value))
  const filteredCircleIndexRows = computed(() => {
    const rows = Array.isArray(circleIndexModel.value?.rows) ? circleIndexModel.value.rows : []
    const q = String(compareSearchQuery.value || '').trim().toLowerCase()
    return rows.filter((it) => {
      const sm = compareSourceFilter.value === 'all'
        || (compareSourceFilter.value === 'kikoeru' && it?.sourceCompare?.kikoeru?.primary_rjcode)
        || (compareSourceFilter.value === 'dlsite' && Array.isArray(it?.sourceCompare?.dlsite?.all_rjcodes) && it.sourceCompare.dlsite.all_rjcodes.length)
        || (compareSourceFilter.value === 'asmr_one' && it?.sourceCompare?.asmr_one?.primary_rjcode)
        || (compareSourceFilter.value === 'missing' && !it?.sourceCompare?.kikoeru?.primary_rjcode
            && !(Array.isArray(it?.sourceCompare?.dlsite?.all_rjcodes) && it.sourceCompare.dlsite.all_rjcodes.length)
            && !it?.sourceCompare?.asmr_one?.primary_rjcode)
      if (!sm) return false
      const variant = String(it?.variantTypeTag || it?.preferred_variant_label || '')
      const vm = compareVariantFilter.value === 'all'
        || (compareVariantFilter.value === 'simp' && /简中|简体/.test(variant))
        || (compareVariantFilter.value === 'trad' && /繁中|繁体/.test(variant))
        || (compareVariantFilter.value === 'original' && /原作|原版|日文原版|\bJPN\b/i.test(variant))
        || (compareVariantFilter.value === 'bonus' && it?.isBonusWork)
        || (compareVariantFilter.value === 'original_subtitle' && it?.originalSubtitlePresent)
        || (compareVariantFilter.value === 'original_no_subtitle' && /原作|原版|日文原版|\bJPN\b/i.test(variant) && !it?.originalSubtitlePresent)
      if (!vm) return false
      if (!q) return true
      const hay = [
        it?.title, it?.workRjcode, it?.display_rjcode, it?.preferred_variant_label,
        it?.sourceCompare?.kikoeru?.primary_rjcode,
        ...(Array.isArray(it?.sourceCompare?.dlsite?.all_rjcodes) ? it.sourceCompare.dlsite.all_rjcodes : []),
        it?.sourceCompare?.asmr_one?.primary_rjcode,
      ].map((v) => String(v || '').toLowerCase())
      return hay.some((v) => v.includes(q))
    })
  })
  const circleIndexSummary = computed(() => {
    const m = circleIndexModel.value
    if (!m) return ''
    const total = Array.isArray(m.rows) ? m.rows.length : 0
    const visible = filteredCircleIndexRows.value.length
    const breakdown = Array.isArray(m.sourceBreakdown) ? m.sourceBreakdown : []
    const sourceText = breakdown.filter((it) => Number(it.count || 0) > 0).map((it) => `${it.label} ${it.count}`).join(' · ')
    const scope = visible === total ? `共 ${total} 项作品` : `共 ${total} 项作品，当前筛出 ${visible} 项`
    return sourceText ? `${scope} · ${sourceText}` : scope
  })

  const circleRefreshModel = computed(() => buildCircleCompletionRefreshModel(rowRef.value, circleRefreshFilter.value))
  const pagedCircleRefreshItems = computed(() => {
    const rows = Array.isArray(circleRefreshModel.value?.items) ? circleRefreshModel.value.items : []
    const start = (circleRefreshPage.value - 1) * circleRefreshPageSize
    return rows.slice(start, start + circleRefreshPageSize)
  })
  function setCircleRefreshFilter(value) {
    circleRefreshFilter.value = String(value || 'all')
    circleRefreshPage.value = 1
  }
  function setCircleRefreshPage(next) {
    circleRefreshPage.value = Math.max(1, Number(next || 1))
  }

  const emailWatcherModel = computed(() => emailWatcherBatchModel(rowRef.value))
  const bonusProbe = computed(() => bonusProbeModel(rowRef.value))

  // entry section / row 折叠态
  const isEntrySectionExpanded = (key) => !collapsedEntrySectionKeys.value.has(String(key || ''))
  const toggleEntrySection = (key) => {
    const k = String(key || '')
    if (!k) return
    const next = new Set(collapsedEntrySectionKeys.value)
    if (next.has(k)) next.delete(k); else next.add(k)
    collapsedEntrySectionKeys.value = next
  }
  const isEntryTreeRowExpanded = (key) => !collapsedEntryTreeRowKeys.value.has(String(key || ''))
  const toggleEntryTreeRow = (key) => {
    const k = String(key || '')
    if (!k) return
    const next = new Set(collapsedEntryTreeRowKeys.value)
    if (next.has(k)) next.delete(k); else next.add(k)
    collapsedEntryTreeRowKeys.value = next
  }
  function flattenEntryRows(rows) {
    const out = []
    const visit = (xs, depth = 0) => {
      for (const item of Array.isArray(xs) ? xs : []) {
        const hasChildren = Array.isArray(item.children) && item.children.length > 0
        const cur = { ...item, depth, expandable: hasChildren }
        out.push(cur)
        if (hasChildren && isEntryTreeRowExpanded(cur.key)) visit(item.children, depth + 1)
      }
    }
    visit(rows, 0)
    return out
  }

  return {
    // refs
    compareSearchQuery, compareSourceFilter, compareVariantFilter, compareExpanded,
    circleRefreshFilter, circleRefreshPage, circleRefreshPageSize,
    batchWorkbenchAwaitingOnly, selectedBatchWorkbenchKeys,
    // basic computeds
    summaryText, rjText, tags, finalLabel, finalCls, isRerun, isRecovered,
    // path compare
    pathCompare, pathCompareCls, pathCompareReason,
    // highlights & metrics
    highlights, filterDeleteMetrics, uploadMetrics, rawJson,
    // file tree
    entrySections, entrySectionTitle, flattenEntryRows,
    isEntrySectionExpanded, toggleEntrySection,
    isEntryTreeRowExpanded, toggleEntryTreeRow,
    resolveEntryIcon, entryIconClass,
    // pair
    pairWorkbench, pairResult,
    // subtitle batch workbench
    subtitleBatchModel, visibleBatchItems, allBatchSelected, selectedBatchItems,
    toggleAllBatchItems, selectAwaitingBatchItems,
    // circle
    circleIndexModel, filteredCircleIndexRows, circleIndexSummary,
    circleRefreshModel, pagedCircleRefreshItems,
    setCircleRefreshFilter, setCircleRefreshPage,
    formatRefreshChangeValue, normalizeKikoeruTags,
    circleIndexSourceTone, circleIndexSourceIcon,
    bonusProbe,
    // email watcher
    emailWatcherModel, handleEmailWatchCoverError,
    // navigation helpers (resolvers, actually do the navigation in parent)
    resolveSubtitleTaskId, resolveSubtitleFolderPath, resolveSubtitleLibraryId,
    isSubtitlePairRelatedRow, isSubtitleBatchRootRow,
    // tag helpers
    actionTagClass, humanAction, displaySummary, displayRjcode,
  }
}

export {
  humanAction, actionTagClass, rowCategoryTags, finalStatusLabel, finalStatusClass,
  isRecoveredFailure, isRerunRow, effectiveRowStatus, isPurelyProblemListPartial,
}
