/**
 * Block 前端迷你渲染器
 *
 * 用于画布上"所见即所得"地预览每个块的最终样子。输出与后端 block_renderers
 * 保持视觉一致（inline-style HTML），但简化变量解析（用 sample payload）。
 *
 * 注意：渲染结果会通过 v-html 注入，已知风险：
 * - rich_text 块的 htmlCache 是用户输入的 HTML，编辑期间可能含未清洗内容。
 *   我们用一个轻量的客户端清洗去掉 <script>/<iframe>/<style>/事件属性，
 *   防止预览时执行恶意脚本。后端入库前还有 nh3 真正清洗。
 */

const SEVERITY_BG = {
  success: '#1f8f4e',
  danger:  '#d93025',
  warning: '#d97706',
  info:    '#0071e3',
}

const SAMPLE_BY_EVENT = {
  completed: {
    event_label: '任务完成',
    event_icon:  '✅',
    severity:    'success',
  },
  failed: {
    event_label: '任务失败',
    event_icon:  '❌',
    severity:    'danger',
  },
  waiting_manual: {
    event_label: '等待人工处理',
    event_icon:  '⚠️',
    severity:    'warning',
  },
}

// 中文 key → 示例值。同时也写入英文别名（兼容老模板）。
const SAMPLE_VARS = {
  '任务标题':  '示例任务标题',
  '摘要':      '批量任务结束，3/3 个完成',
  '任务类型':  '导入处理',
  'RJ号':      'RJ123456',
  '时间':      '2024-01-01 12:00:00',
  '总文件数':  '3',
  '总大小':    '256 MB',
}

// 英文别名 → 中文 key，前端解析时也支持用户写老 key
const VAR_ALIASES = {
  title:               '任务标题',
  summary:             '摘要',
  domain_label:        '任务类型',
  rjcode:              'RJ号',
  event_label:         '事件名称',
  event_icon:          '事件图标',
  created_at:          '时间',
  severity:            '严重程度',
  'stats.total_files': '总文件数',
  'stats.total_size':  '总大小',
}

/**
 * 构建预览用 sample payload。同时填充中文 key 和英文别名，
 * 让 mini-renderer 与 后端 substitute_variables 行为一致。
 */
export function buildSamplePayload(eventType = 'completed') {
  const evt = SAMPLE_BY_EVENT[eventType] || SAMPLE_BY_EVENT.completed
  const out = {
    ...SAMPLE_VARS,
    event_type:    eventType,
    '事件名称':    evt.event_label,
    '事件图标':    evt.event_icon,
    '严重程度':    evt.severity,
    // 后端 path 字段：mini-renderer 不用这些，但为了与后端 sample 对齐保留
    severity:      evt.severity,
  }
  // 英文别名同步（{title} 等老模板还能用）
  for (const [en, zh] of Object.entries(VAR_ALIASES)) {
    if (out[zh] !== undefined) out[en] = out[zh]
  }
  // ─── 业务数据块示例数据（与后端 build_sample_payload 对齐） ───
  out.stats = {
    total_files: '3',
    total_size:  '256 MB',
    duration:    '12.4s',
    succeeded:   '3',
    failed:      '0',
  }
  // 与后端 _flat_to_tree 输出一致：dir 节点带 children，叶子 path 仅文件名
  out.file_tree = [
    { name: 'RJ123456', status: 'kept', children: [
      { name: 'audio', status: 'kept', children: [
        { path: 'track01.flac', size_text: '42.1 MB', status: 'kept', badges: ['已上传'] },
        { path: 'track02.flac', size_text: '38.6 MB', status: 'kept', badges: ['已上传'] },
        { path: 'sample.mp3',   size_text: '3.4 MB',  status: 'filtered' },
      ]},
      { path: 'cover.jpg', size_text: '1.2 MB', status: 'kept', badges: ['已上传'] },
      { path: 'readme.txt', size_text: '256 B', status: 'filtered' },
    ]},
  ]
  out.download_files = out.file_tree
  out.download_work_cards = [
    {
      rjcode: 'RJ123456',
      title: '【早期購入特典付き】ひたすら“ぎゅー”してお互い「好き好き」と言わなきゃいけない、あまあまクール大好きペア',
      circle_name: '防講潤滑剤',
      cover_url: 'https://img.dlsite.jp/modpub/images2/work/doujin/RJ123000/RJ123456_img_main.jpg',
      size_text: '1.32 GB',
      file_count: 7,
    },
  ]
  out.rj_work_cards = [
    {
      rjcode: 'RJ01574313',
      title: '【简体中文版】【免费公开中--要去了要去了视频♡】超喜欢你的幼妻〇莉/哦哟♡公主〜〜新婚甜蜜调教&恩爱授孕做爱的故事♪〜',
      circle_name: 'リリムワークス',
      cover_url: 'https://img.dlsite.jp/modpub/images2/work/doujin/RJ01574000/RJ01574313_img_main.jpg',
      size_text: '有更新 / 服务器已有',
      file_count: 4,
      count_label: '4 处变化',
      changes: [
        '服务器状态: 服务器缺失 -> 服务器已有',
        '服务器RJ: 无 -> RJ01574313',
        '字幕状态: 无 -> 有',
        '来源集合: asmr_one / dlsite / local -> asmr_one / dlsite / kikoeru / local',
      ],
    },
  ]
  out.diff_items = [
    { label: '社团名',  old: 'Tsuki',    new: 'Tsuki Studio' },
    { label: '封面',    old: '',         new: 'cover_v2.jpg' },
    { label: 'RJ 编号', old: 'RJ123456', new: 'RJ123456' },
    { label: '标签',    old: 'ASMR',     new: 'ASMR / 治愈' },
  ]
  out.recent_logs = [
    { ts: '12:00:01', level: 'info', text: '开始处理任务 RJ123456' },
    { ts: '12:00:03', level: 'info', text: '下载封面：cover.jpg (1.2 MB)' },
    { ts: '12:00:05', level: 'warn', text: '检测到重复文件 sample.mp3，已过滤' },
    { ts: '12:00:08', level: 'info', text: '解压完成，共 3 个有效文件' },
    { ts: '12:00:12', level: 'info', text: '任务完成，耗时 12.4s' },
  ]
  return out
}

/**
 * 取变量值：先按 key 直接查；命中英文别名时映射到中文 key 再查；
 * 仍找不到则按点号嵌套查。
 */
function pickVar(key, payload) {
  if (key in payload) return payload[key]
  if (key in VAR_ALIASES) {
    const zh = VAR_ALIASES[key]
    if (zh in payload) return payload[zh]
  }
  const parts = key.split('.')
  let cur = payload
  for (const p of parts) {
    if (cur && typeof cur === 'object') cur = cur[p]
    else return undefined
  }
  return cur
}

function htmlEscape(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * 客户端轻量清洗（只用于预览，不替代后端 nh3）
 */
function lightSanitize(html) {
  if (!html) return ''
  return String(html)
    .replace(/<\/?(?:script|style|iframe|object|embed|form|input|textarea|select|button|link|meta|base|svg|math)\b[^>]*>/gi, '')
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
    .replace(/\son\w+\s*=\s*[^\s>]+/gi, '')
    .replace(/(href\s*=\s*["'])javascript:[^"']*(["'])/gi, '$1#$2')
}

/**
 * {var} 占位替换
 */
// {key} 占位匹配：花括号内连续非空白非花括号字符（兼容中文）
const VAR_PATTERN = /\{([^{}\s]+)\}/g

function substitute(text, payload, { escape = true } = {}) {
  if (!text) return ''
  return String(text).replace(VAR_PATTERN, (raw, key) => {
    const v = pickVar(key, payload)
    if (v === undefined || v === null) return raw
    return escape ? htmlEscape(v) : String(v)
  })
}

// 还原 <span data-var="任务标题">...</span> 为 {任务标题}
const VAR_PILL_RE = /<span\b[^>]*\bdata-var\s*=\s*"([^"]+)"[^>]*>[\s\S]*?<\/span>/gi
function unwrapVarPill(html) {
  return String(html || '').replace(VAR_PILL_RE, (_m, key) => '{' + key + '}')
}

function resolveVar(key, payload, fallback = '') {
  const v = pickVar(key, payload)
  return htmlEscape(v ?? fallback)
}

// ─── 各块渲染器 ────────────────────────────────────────────

function renderHeaderStatus(props, payload) {
  const title    = resolveVar(props.titleKey    || '任务标题', payload, '任务通知')
  const summary  = resolveVar(props.summaryKey  || '摘要',     payload, '')
  const severity = pickVar(props.severityKey || '严重程度', payload) || 'info'
  const bg = SEVERITY_BG[severity] || SEVERITY_BG.info
  return `
    <div style="background:${bg};padding:24px 28px;border-radius:10px;">
      <div style="font-size:18px;font-weight:600;color:#fff;margin-bottom:6px;">${title}</div>
      <div style="font-size:13px;color:rgba(255,255,255,0.88);line-height:1.5;">${summary}</div>
    </div>
  `
}

function renderSummaryCard(props, payload) {
  const label  = htmlEscape(props.label || '摘要')
  const value  = resolveVar(props.valueKey || '摘要', payload, '')
  const accent = htmlEscape(props.accentColor || '#0071e3')
  return `
    <div style="padding:14px 16px;background:#f5f5f7;border-radius:10px;border-left:3px solid ${accent};">
      <div style="font-size:11px;font-weight:600;color:#8e8e93;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px;">${label}</div>
      <div style="font-size:14px;color:#1d1d1f;font-weight:500;">${value}</div>
    </div>
  `
}

function renderRichText(props, payload) {
  const cache = props.htmlCache || ''
  const cleaned = lightSanitize(cache)
  // 还原变量 pill 为 {key} 后再做替换；这样画布的 mini 预览也能渲染最终值
  const unwrapped = unwrapVarPill(cleaned)
  const rendered = substitute(unwrapped, payload, { escape: true })
  if (!rendered.trim()) {
    return `<div style="padding:8px 0;font-size:13px;color:rgba(29,29,31,0.35);font-style:italic;">（富文本内容为空）</div>`
  }
  return `<div style="padding:4px 0;font-size:14px;color:#1d1d1f;line-height:1.6;">${rendered}</div>`
}

function renderDivider(props) {
  const color  = htmlEscape(props.color || '#e5e5ea')
  const margin = Math.max(0, Math.min(64, Number(props.margin) || 16))
  return `<hr style="border:none;border-top:1px solid ${color};margin:${margin}px 0;" />`
}

function renderSpacer(props) {
  const height = Math.max(0, Math.min(120, Number(props.height) || 16))
  return `<div style="height:${height}px;line-height:${height}px;font-size:1px;background:repeating-linear-gradient(45deg,#fafafa,#fafafa 4px,#f0f0f0 4px,#f0f0f0 8px);border-radius:4px;">&nbsp;</div>`
}

// ─── 业务数据块 mini renderers ──────────────────────────────

function renderStatsGrid(props, payload) {
  const items = Array.isArray(props.items) ? props.items : []
  if (!items.length) {
    return `<div style="padding:8px;font-size:12px;color:#8e8e93;font-style:italic;">（统计网格 — 请在右侧 Inspector 配置字段）</div>`
  }
  const columns = Math.max(1, Math.min(4, Number(props.columns) || 3))
  const stats = payload.stats || {}
  const cellW = (100 / columns).toFixed(2)
  const cells = items.map(it => {
    const key = it?.key || ''
    const label = htmlEscape(it?.label || key)
    const icon = htmlEscape(it?.icon || '')
    let val = stats
    for (const part of String(key).split('.')) {
      val = val?.[part]
      if (val === undefined) break
    }
    const valStr = htmlEscape(val ?? '') || '—'
    const iconHtml = icon ? `<span style="font-size:14px;margin-right:6px;">${icon}</span>` : ''
    return `<td width="${cellW}%" valign="top" style="padding:14px 16px;border-right:1px solid #ececef;">
      <div style="font-size:10px;font-weight:600;color:#8e8e93;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px;">${iconHtml}${label}</div>
      <div style="font-size:18px;color:#1d1d1f;font-weight:600;">${valStr}</div>
    </td>`
  })
  const rows = []
  for (let i = 0; i < cells.length; i += columns) {
    const row = cells.slice(i, i + columns)
    while (row.length < columns) row.push(`<td width="${cellW}%"></td>`)
    rows.push(`<tr>${row.join('')}</tr>`)
  }
  return `<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 12px;background:#fafafa;border:1px solid #ececef;border-radius:10px;border-collapse:separate;overflow:hidden;">${rows.join('')}</table>`
}

const FILE_STATUS_STYLE = {
  kept:     { color: '#1f8f4e', marker: '✓', labelExtra: 'color:#1d1d1f;' },
  filtered: { color: '#d97706', marker: '✕', labelExtra: 'color:rgba(29,29,31,0.45);' },
  new:      { color: '#0071e3', marker: '+', labelExtra: 'color:#1d1d1f;' },
  removed:  { color: '#d93025', marker: '−', labelExtra: 'color:rgba(29,29,31,0.45);' },
}

function lucideIcon(name, color, size = 15) {
  const paths = {
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
    folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9L9.6 3.9A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    folderOpen: '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.2 10H20a2 2 0 0 1 1.8 2.9l-2.2 4.4A3 3 0 0 1 16.9 19H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.7.9l.8 1.2a2 2 0 0 0 1.7.9H19a2 2 0 0 1 2 2v2"/>',
    file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
    fileText: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    archive: '<path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/>',
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-3px;flex-shrink:0;">${paths[name] || paths.file}</svg>`
}

function fileTreeIconName(label) {
  const lower = String(label || '').toLowerCase()
  if (/\.(wav|flac|mp3|m4a|ogg|aac|opus|cue)$/.test(lower)) return 'music'
  if (/\.(png|jpg|jpeg|webp|gif|bmp|avif)$/.test(lower)) return 'image'
  if (/\.(zip|7z|rar|tar|gz|bz2|xz)$/.test(lower)) return 'archive'
  if (/\.(txt|lrc|srt|vtt|ass|ssa|json|md|pdf)$/.test(lower)) return 'fileText'
  return 'file'
}

function renderFileTree(props, payload) {
  const sourceKey = props.sourceKey || 'file_tree'
  const title = htmlEscape(props.title || '文件清单')
  const maxItems = Math.max(0, Number(props.maxItems) || 30)
  if (sourceKey === 'rj_work_cards') {
    return renderDownloadWorkCards(title, payload.rj_work_cards || [], maxItems)
  }
  const items = payload[sourceKey] || []
  if (sourceKey === 'download_files' && Array.isArray(payload.download_work_cards) && payload.download_work_cards.length) {
    return renderDownloadWorkCards(title, payload.download_work_cards, maxItems)
  }
  if (!items.length) {
    return `<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">${title}：（无数据）</div>`
  }
  const BADGE_STYLE_MAP = {
    '已上传':   'background:#dcfce7;color:#166534;border:1px solid #86efac;',
    '下载失败': 'background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;',
  }
  const DEFAULT_BADGE_STYLE = 'background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;'
  const renderBadges = (badges) => {
    if (!Array.isArray(badges) || !badges.length) return ''
    return badges.map(b => {
      const text = String(b || '').trim()
      if (!text) return ''
      const extra = BADGE_STYLE_MAP[text] || DEFAULT_BADGE_STYLE
      return `<span style="display:inline-block;margin-left:6px;padding:1px 6px;border-radius:5px;font-size:10.5px;font-weight:600;line-height:1.5;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;${extra}">${htmlEscape(text)}</span>`
    }).join('')
  }

  const state = { emitted: 0, truncated: false, skipped: 0 }
  const fileRowStyle = "padding:3px 10px 3px 6px;font-size:12.5px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;line-height:1.35;display:flex;align-items:center;justify-content:space-between;gap:8px;"
  const summaryStyle = "cursor:pointer;padding:3px 10px 3px 6px;background:#fcfdff;font-size:12.5px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;font-weight:600;color:#0f172a;line-height:1.35;outline:none;display:flex;align-items:center;gap:6px;"
  const detailsStyle = 'border:none;margin:0;'

  const renderFileRow = (node) => {
    const label = String(node.path || node.name || '')
    const status = node.status || 'kept'
    const style = FILE_STATUS_STYLE[status] || { color: '#48484a', marker: '·', labelExtra: 'color:#1d1d1f;' }
    const isMuted = status === 'filtered' || status === 'removed'
    const lowerLabel = label.toLowerCase()
    const iconColor = isMuted ? '#94a3b8' : (lowerLabel.match(/\.(flac|wav)$/) ? '#2563eb' : lowerLabel.match(/\.(mp3|m4a|ogg|aac|opus)$/) ? '#7c3aed' : '#64748b')
    const iconHtml = `<span style="display:inline-block;width:18px;text-align:center;line-height:1;flex-shrink:0;">${lucideIcon(fileTreeIconName(label), iconColor, 15)}</span>`
    const sizeText = String(node.size_text || '')
    const sizeHtml = sizeText ? `<span style="color:#94a3b8;font-size:11px;white-space:nowrap;flex-shrink:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">${htmlEscape(sizeText)}</span>` : ''
    const badgeHtml = renderBadges(node.badges || [])
    const lineHtml = isMuted ? '<span style="position:absolute;left:18px;right:10px;top:50%;border-top:1.5px solid rgba(148,163,184,0.75);transform:translateY(-50%);pointer-events:none;z-index:1;"></span>' : ''
    return `<div style="position:relative;${fileRowStyle}${style.labelExtra}">${lineHtml}<span style="display:inline-flex;align-items:center;gap:6px;min-width:0;overflow:hidden;flex:1;padding-right:8px;"><span style="display:inline-block;width:18px;flex-shrink:0;"></span>${iconHtml}<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500;">${htmlEscape(label)}</span>${badgeHtml}</span>${sizeHtml}</div>`
  }

  const renderDir = (node, depth) => {
    if (state.truncated) { state.skipped += 1; return '' }
    state.emitted += 1
    const label = String(node.name || node.path || '')
    const typeIcon = `<span style="display:inline-block;width:18px;text-align:center;line-height:1;flex-shrink:0;">${lucideIcon('folderOpen', '#f59e0b', 15)}</span>`
    const sizeText = String(node.size_text || '')
    const sizeHtml = sizeText ? `<span style="margin-left:auto;color:#94a3b8;font-size:11px;font-weight:400;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">${htmlEscape(sizeText)}</span>` : ''
    const badgeHtml = renderBadges(node.badges || [])
    const children = Array.isArray(node.children) ? node.children : []
    const childChunks = []
    for (const child of children) {
      if (state.truncated) { state.skipped += 1; continue }
      if (state.emitted >= maxItems) { state.truncated = true; state.skipped += 1; continue }
      if (child && typeof child === 'object' && Array.isArray(child.children)) {
        childChunks.push(renderDir(child, depth + 1))
      } else {
        state.emitted += 1
        const safeChild = (child && typeof child === 'object') ? child : { path: String(child) }
        childChunks.push(renderFileRow(safeChild))
      }
    }
    const childrenWrapper = childChunks.length ? `<div style="padding-left:4px;margin-left:8px;background:#fff;">${childChunks.join('')}</div>` : ''
    return `<details open style="${detailsStyle}"><summary style="${summaryStyle}"><span style="display:inline-block;width:18px;text-align:center;line-height:1;flex-shrink:0;">${lucideIcon('chevronRight', '#94a3b8', 13)}</span>${typeIcon}<span style="font-weight:600;color:#334155;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${htmlEscape(label)}</span>${badgeHtml}${sizeHtml}</summary>${childrenWrapper}</details>`
  }

  const bodyChunks = []
  for (const n of items) {
    if (state.truncated) { state.skipped += 1; continue }
    if (state.emitted >= maxItems) { state.truncated = true; state.skipped += 1; continue }
    if (n && typeof n === 'object' && Array.isArray(n.children)) {
      bodyChunks.push(renderDir(n, 0))
    } else {
      state.emitted += 1
      const safe = (n && typeof n === 'object') ? n : { path: String(n) }
      bodyChunks.push(renderFileRow(safe))
    }
  }
  if (state.truncated && state.skipped > 0) {
    bodyChunks.push(`<div style="padding:8px 14px;font-size:11px;color:#8e8e93;text-align:center;font-style:italic;border-top:1px solid #f5f5f7;">... 还有 ${state.skipped} 项未显示</div>`)
  }

  return `<div style="margin:10px 0;">
    <div style="font-size:11px;font-weight:600;color:#64748b;letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;padding:0 4px;">${title}</div>
    <div style="background:linear-gradient(180deg,#ffffff 0%,#fbfdff 100%);border:1px solid #dde6f0;border-radius:12px;overflow:hidden;box-shadow:0 8px 24px rgba(15,23,42,0.06);">${bodyChunks.join('')}</div>
  </div>`
}

function renderDownloadWorkCards(title, items, maxItems) {
  const rows = []
  const limit = Math.max(0, maxItems || 30)
  for (const item of items.slice(0, limit)) {
    if (!item || typeof item !== 'object') continue
    const coverUrl = htmlEscape(item.cover_url || '')
    const rjcode = htmlEscape(item.rjcode || 'RJ')
    const workTitle = htmlEscape(item.title || item.rjcode || '下载作品')
    const circleName = htmlEscape(item.circle_name || '')
    const sizeText = htmlEscape(item.size_text || '')
    const fileCount = Number(item.file_count) || 0
    const countLabel = htmlEscape(item.count_label || (fileCount ? `${fileCount} 个文件` : ''))
    const meta = [circleName, sizeText, countLabel].filter(Boolean).join(' · ') || '下载完成'
    const changes = Array.isArray(item.changes) ? item.changes.map(change => String(change || '').trim()).filter(Boolean) : []
    const changesHtml = changes.length
      ? `<div style="margin-top:10px;padding:8px 10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;color:#334155;font-size:12px;line-height:1.6;">${changes.slice(0, 6).map(change => `<div>${htmlEscape(change)}</div>`).join('')}</div>`
      : ''
    const imageHtml = coverUrl
      ? `<img src="${coverUrl}" alt="${workTitle}" width="180" height="180" style="display:block;width:180px;height:180px;object-fit:contain;background:#fff;border:0;">`
      : `<div style="width:180px;height:180px;background:#f5f5f7;color:#8e8e93;font-size:12px;line-height:180px;text-align:center;">无封面</div>`
    rows.push(`<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 14px;border-collapse:collapse;"><tr><td width="180" valign="top" style="padding:0 16px 0 0;"><table width="180" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;"><tr><td>${imageHtml}</td></tr><tr><td style="background:#fff3cf;color:#c2410c;font-size:12px;line-height:20px;text-align:center;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">${rjcode}</td></tr></table></td><td valign="top" style="padding:2px 0 0 0;"><div style="font-size:18px;line-height:1.35;font-weight:700;color:#0f172a;margin:0 0 8px 0;">${workTitle}</div><div style="font-size:13px;line-height:1.6;color:#475569;margin:0 0 10px 0;">${meta}</div><div style="font-size:20px;line-height:1.2;font-weight:700;color:#111827;">${sizeText || '大小未知'}</div>${changesHtml}</td></tr></table>`)
  }
  if (!rows.length) {
    return `<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">${title}：（无数据）</div>`
  }
  const more = Math.max(0, items.length - rows.length)
  const moreHtml = more ? `<div style="padding:8px 14px;font-size:11px;color:#8e8e93;text-align:center;font-style:italic;border-top:1px solid #f5f5f7;">... 还有 ${more} 项未显示</div>` : ''
  return `<div style="margin:10px 0;"><div style="font-size:11px;font-weight:600;color:#8e8e93;letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;padding:0 4px;">${title}</div><div style="background:#fff;border:1px solid #ececef;border-radius:10px;padding:14px 14px 0;overflow:hidden;">${rows.join('')}${moreHtml}</div></div>`
}

function renderDiffView(props, payload) {
  const sourceKey = props.sourceKey || 'diff_items'
  const title = htmlEscape(props.title || '数据差异')
  const items = payload[sourceKey] || []
  if (!items.length) {
    return `<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">${title}：（无差异）</div>`
  }
  const rows = items.map(it => {
    if (!it || typeof it !== 'object') return ''
    const label = htmlEscape(it.label || '')
    const oldRaw = String(it.old || '')
    const newRaw = String(it.new || '')
    const oldV = htmlEscape(oldRaw) || `<span style="color:#c7c7cc;">—</span>`
    const newV = htmlEscape(newRaw) || `<span style="color:#c7c7cc;">—</span>`
    const changed = it.changed !== undefined ? !!it.changed : (oldRaw !== newRaw)
    const newBg = changed ? 'background:#e8f5ee;color:#1f8f4e;' : 'color:#1d1d1f;'
    const oldBg = changed ? 'background:#fef0e6;color:#d97706;text-decoration:line-through;' : 'color:#8e8e93;'
    return `<tr>
      <td valign="top" style="padding:10px 14px;width:120px;font-size:11.5px;color:#48484a;font-weight:500;border-bottom:1px solid #f5f5f7;">${label}</td>
      <td valign="top" style="padding:10px 8px;font-size:12.5px;border-bottom:1px solid #f5f5f7;"><span style="display:inline-block;padding:2px 7px;border-radius:4px;${oldBg}font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">${oldV}</span></td>
      <td valign="middle" style="padding:10px 4px;font-size:14px;color:#c7c7cc;border-bottom:1px solid #f5f5f7;width:20px;text-align:center;">→</td>
      <td valign="top" style="padding:10px 14px 10px 8px;font-size:12.5px;border-bottom:1px solid #f5f5f7;"><span style="display:inline-block;padding:2px 7px;border-radius:4px;${newBg}font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:500;">${newV}</span></td>
    </tr>`
  })
  return `<div style="margin:10px 0;">
    <div style="font-size:11px;font-weight:600;color:#8e8e93;letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;padding:0 4px;">${title}</div>
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border:1px solid #ececef;border-radius:10px;border-collapse:separate;overflow:hidden;">${rows.join('')}</table>
  </div>`
}

const LOG_LEVEL_COLOR = {
  info:  '#a1a1a6',
  warn:  '#d97706',
  error: '#ff6b6b',
  debug: '#6e6e73',
}

function renderTaskLog(props, payload) {
  const sourceKey = props.sourceKey || 'recent_logs'
  const title = htmlEscape(props.title || '执行日志')
  const maxLines = Math.max(1, Number(props.maxLines) || 12)
  const items = payload[sourceKey] || []
  if (!items.length) {
    return `<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">${title}：（无日志）</div>`
  }
  const visible = items.slice(-maxLines)
  const rows = visible.map(it => {
    let level, text, ts
    if (it && typeof it === 'object') {
      level = (it.level || 'info').toLowerCase()
      text = htmlEscape(it.text || '')
      ts = htmlEscape(it.ts || '')
    } else {
      level = 'info'; text = htmlEscape(String(it)); ts = ''
    }
    const color = LOG_LEVEL_COLOR[level] || '#a1a1a6'
    const tsHtml = ts ? `<span style="color:#6e6e73;margin-right:8px;">${ts}</span>` : ''
    return `<div style="padding:2px 0;color:${color};">${tsHtml}${text}</div>`
  })
  const truncatedHtml = items.length > maxLines
    ? `<div style="padding:6px 0 0 0;color:#6e6e73;font-style:italic;font-size:10.5px;">…（仅显示最后 ${maxLines} 行，共 ${items.length} 行）</div>`
    : ''
  return `<div style="margin:10px 0;">
    <div style="font-size:11px;font-weight:600;color:#8e8e93;letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;padding:0 4px;">${title}</div>
    <div style="background:#1d1d1f;border-radius:10px;padding:14px 16px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.55;color:#a1a1a6;overflow:hidden;">
      ${rows.join('')}${truncatedHtml}
    </div>
  </div>`
}

const RENDERERS = {
  header_status: renderHeaderStatus,
  summary_card:  renderSummaryCard,
  rich_text:     renderRichText,
  divider:       renderDivider,
  spacer:        renderSpacer,
  stats_grid:    renderStatsGrid,
  file_tree:     renderFileTree,
  diff_view:     renderDiffView,
  task_log:      renderTaskLog,
}

/**
 * 渲染单个块为 HTML 字符串（供 v-html 使用）
 */
export function renderBlockMini(block, payload) {
  if (!block || !block.type) return ''
  const renderer = RENDERERS[block.type]
  if (!renderer) {
    return `<div style="padding:8px;font-size:12px;color:#8e8e93;font-family:monospace;">未知块类型：${htmlEscape(block.type)}</div>`
  }
  try {
    return renderer(block.props || {}, payload)
  } catch (err) {
    return `<div style="padding:8px;font-size:12px;color:#d93025;">渲染失败：${htmlEscape(err?.message || err)}</div>`
  }
}
