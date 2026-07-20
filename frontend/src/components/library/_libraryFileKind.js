// 共享分类与色盘。原本只支持 5 类（folder / audio-lossless / audio / text / file），
// 现在对齐操作记录文件树（ActivityRichBlock + useActivityDetailModels.js）的 9 类：
// 多了图片 / 视频 / PDF / 压缩包，并把音频拆为蓝（无损）/ 紫（有损）两色。
//
// 这套色盘被以下地方共享：
//   - 库存页主文件列表（views/Library.vue 的 getLibraryRowIconComponent / getLibraryRowIconClass + .file-icon.icon-* 样式）
//   - LibrarySearchBox 行图标 + 筛选下拉（库存搜索框）
//   - LibrarySearchOverlay 行图标 + 筛选下拉（全屏搜索面板）
//   - FolderContentsDialog / FilterDeleteDialog / SubtitleImportWorkbench / SubtitleInspectorWorkbench 的文件树
//     （这几处原本走 element-plus 的 Document/Picture/... 或本地手写 5 类，统一替换为本 helper）
// 与操作记录 ActivityRichBlock 文件树的 .entry-icon.is-* 颜色保持一致。
//
// 色盘来源（参见 ActivityRichBlock.vue 的 .entry-icon.is-* 系列）：
//   dir              Folder        #f6b73c 黄（带 fill 半透明）
//   audio-lossless   Music         #2563eb 蓝（wav / flac）
//   audio            Music         #7c3aed 紫（mp3 / m4a / ogg / aac / wma / opus / cue）
//   image            ImageIcon     #f97316 橙（jpg / jpeg / png / webp / gif / bmp / avif）
//   video            Film          #6366f1 靛（mp4 / mkv / avi / mov / wmv / webm / m4v）
//   pdf              FileText      #dc2626 红
//   archive          FileArchive   #d97706 琥珀（zip / 7z / rar / tar / gz / bz2 / xz）
//   text             FileText      #64748b 灰（srt / ass / ssa / vtt / lrc / txt / md / json）
//   file             File          #94a3b8 浅灰（默认兜底）

import {
  File as IconFile,
  FileArchive as IconFileArchive,
  FileText as IconFileText,
  Film as IconFilm,
  Folder as IconFolder,
  Image as IconImage,
  Layers as IconLayers,
  Music as IconMusic,
} from 'lucide-vue-next'

const AUDIO_LOSSLESS_RE = /\.(wav|flac)$/i
const AUDIO_RE = /\.(mp3|m4a|ogg|aac|wma|opus|cue)$/i
const IMAGE_RE = /\.(jpg|jpeg|png|webp|gif|bmp|avif)$/i
const VIDEO_RE = /\.(mp4|mkv|avi|mov|wmv|webm|m4v)$/i
const PDF_RE = /\.pdf$/i
const ARCHIVE_RE = /\.(zip|7z|rar|tar|gz|bz2|xz)$/i
const TEXT_RE = /\.(srt|ass|ssa|vtt|lrc|txt|md|json)$/i

export const LIBRARY_ENTRY_KIND_META = {
  dir: { icon: IconFolder, color: '#f6b73c', fillIcon: true, label: '文件夹' },
  'audio-lossless': { icon: IconMusic, color: '#2563eb', fillIcon: false, label: '无损音频' },
  audio: { icon: IconMusic, color: '#7c3aed', fillIcon: false, label: '音频' },
  image: { icon: IconImage, color: '#f97316', fillIcon: false, label: '图片' },
  video: { icon: IconFilm, color: '#6366f1', fillIcon: false, label: '视频' },
  pdf: { icon: IconFileText, color: '#dc2626', fillIcon: false, label: 'PDF' },
  archive: { icon: IconFileArchive, color: '#d97706', fillIcon: false, label: '压缩包' },
  text: { icon: IconFileText, color: '#64748b', fillIcon: false, label: '文档/字幕' },
  file: { icon: IconFile, color: '#94a3b8', fillIcon: false, label: '其他文件' },
}

// 兼容多种数据形状：
//   - 库存搜索结果 / browse 行 → entry_type === 'dir' | 'file'
//   - 操作记录 / 对话框文件树 → type === 'dir' | 'file'
//   - is_directory === true 这种字段也认
function isDirectoryItem (item) {
  if (!item) return false
  if (item.is_directory === true) return true
  const t = String(item.entry_type || item.type || '').toLowerCase()
  return t === 'dir' || t === 'directory'
}

export function classifyLibraryEntryKind (item) {
  if (!item) return 'file'
  if (isDirectoryItem(item)) return 'dir'
  // 名字字段也兼容多种形状（label 是操作记录里的，path / relative_path 兜底）
  const raw = String(item.name || item.label || item.relative_path || item.path || '').toLowerCase()
  if (AUDIO_LOSSLESS_RE.test(raw)) return 'audio-lossless'
  if (AUDIO_RE.test(raw)) return 'audio'
  if (IMAGE_RE.test(raw)) return 'image'
  if (VIDEO_RE.test(raw)) return 'video'
  if (PDF_RE.test(raw)) return 'pdf'
  if (ARCHIVE_RE.test(raw)) return 'archive'
  if (TEXT_RE.test(raw)) return 'text'
  return 'file'
}

export function libraryEntryIconFor (item) {
  return LIBRARY_ENTRY_KIND_META[classifyLibraryEntryKind(item)].icon
}

export function libraryEntryMetaFor (item) {
  return LIBRARY_ENTRY_KIND_META[classifyLibraryEntryKind(item)]
}

// 搜索框左侧"文件类型筛选"下拉的菜单项。
// 7 项：全部 / 仅文件夹 / 音频 / 图片 / 视频 / 文档·字幕 / 其他文件
// PDF / 压缩包不再单独占筛选下拉一项，但行图标仍按各自 kind 着色（PDF 红、archive 琥珀）。
//   - all                  → 后端 entry_type=all，前端不做扩展名再过滤
//   - dir                  → 后端 entry_type=dir
//   - file                 → 后端 entry_type=file（前端把 archive / pdf / 未匹配 一并归入"其他文件"展示）
//   - audio / image / video / text  → 后端 entry_type=file，前端再按扩展名细分
export const LIBRARY_FILTER_OPTIONS = [
  { value: 'all', label: '全部', icon: IconLayers, color: '#64748b' },
  { value: 'dir', label: '仅文件夹', icon: IconFolder, color: '#f6b73c', fillIcon: true },
  { value: 'audio', label: '音频', icon: IconMusic, color: '#7c3aed' },
  { value: 'image', label: '图片', icon: IconImage, color: '#f97316' },
  { value: 'video', label: '视频', icon: IconFilm, color: '#6366f1' },
  { value: 'text', label: '文档 / 字幕', icon: IconFileText, color: '#64748b' },
  { value: 'file', label: '其他文件', icon: IconFile, color: '#94a3b8' },
]

export function libraryFilterToEntryType (value) {
  if (value === 'dir') return 'dir'
  // audio / image / video / text / file —— 后端只能到 file 这一级
  if (
    value === 'file' ||
    value === 'audio' ||
    value === 'image' ||
    value === 'video' ||
    value === 'text'
  ) return 'file'
  return 'all'
}

// 拿到后端结果后做最后一道前端筛选：
// 1) keyword 二次过滤：兜底搜索（list_files）按 path 子串命中时，会把
//    "name 本身不含 keyword、只是父目录含 keyword" 的子文件也带进来。
//    这里统一按 name / rjcode 严格命中再放过，避免"搜文件夹名字结果带出
//    一堆它内部的文件"这种用户感知不友好的命中。
// 2) kind 细分：audio / image / video / text 这种细类靠扩展名。
//    pdf / archive 没有独立筛选项，被归入 file（"其他文件"）。
export function applyLibraryFrontendFilter (items, options = {}) {
  const { filter = 'all', keyword = '', matchedRjcode = null } = options
  const trimmedKeyword = String(keyword || '').trim()
  const lowerKeyword = trimmedKeyword.toLowerCase()
  const rj = String(matchedRjcode || '').toUpperCase()
  const out = []

  for (const item of items || []) {
    if (!item) continue

    if (trimmedKeyword) {
      const itemName = String(item.name || '').toLowerCase()
      const itemRj = String(item.rjcode || '').toUpperCase()
      const nameHit = itemName.includes(lowerKeyword)
      const rjHit = rj && itemRj === rj
      const relatedTranslationHit = item.search_match_type === 'related_translation'
      if (!nameHit && !rjHit && !relatedTranslationHit) continue
    }

    const isDir = isDirectoryItem(item)

    if (filter === 'dir' && !isDir) continue
    if (filter === 'file' && isDir) continue
    // 细分类型筛选只针对文件，目录直接跳过
    if (filter !== 'all' && filter !== 'dir' && isDir) continue

    if (filter === 'audio') {
      const kind = classifyLibraryEntryKind(item)
      if (kind !== 'audio' && kind !== 'audio-lossless') continue
    }
    if (filter === 'image' && classifyLibraryEntryKind(item) !== 'image') continue
    if (filter === 'video' && classifyLibraryEntryKind(item) !== 'video') continue
    if (filter === 'text' && classifyLibraryEntryKind(item) !== 'text') continue

    out.push(item)
  }
  return out
}
