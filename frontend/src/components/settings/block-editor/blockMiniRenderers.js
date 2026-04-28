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
  out.file_tree = [
    { name: '新作品', status: 'kept', children: [
      { path: 'RJ123456/track01.flac', size_text: '42.1 MB', status: 'kept' },
      { path: 'RJ123456/track02.flac', size_text: '38.6 MB', status: 'kept' },
      { path: 'RJ123456/cover.jpg',    size_text: '1.2 MB',  status: 'kept' },
    ]},
    { path: 'RJ123456/sample.mp3', size_text: '3.4 MB',  status: 'filtered' },
    { path: 'RJ123456/readme.txt', size_text: '256 B',   status: 'filtered' },
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
  kept:     { color: '#1f8f4e', marker: '✓' },
  filtered: { color: '#d97706', marker: '✕' },
  new:      { color: '#0071e3', marker: '+' },
  removed:  { color: '#d93025', marker: '−' },
}

function renderFileTree(props, payload) {
  const sourceKey = props.sourceKey || 'file_tree'
  const title = htmlEscape(props.title || '文件清单')
  const maxItems = Math.max(0, Number(props.maxItems) || 30)
  const items = payload[sourceKey] || []
  if (!items.length) {
    return `<div style="padding:12px 14px;background:#fafafa;border:1px solid #ececef;border-radius:8px;font-size:12px;color:#8e8e93;margin:8px 0;">${title}：（无数据）</div>`
  }
  const flat = []
  const walk = (nodes, depth) => {
    for (const n of nodes) {
      if (n && typeof n === 'object' && Array.isArray(n.children)) {
        flat.push({ label: n.name || n.path || '', size: n.size_text || '', status: n.status || 'kept', depth, isDir: true })
        walk(n.children, depth + 1)
      } else {
        const o = (n && typeof n === 'object') ? n : { path: String(n) }
        flat.push({ label: o.path || o.name || '', size: o.size_text || '', status: o.status || 'kept', depth, isDir: false })
      }
    }
  }
  walk(items, 0)
  const truncated = flat.length > maxItems
  const visible = truncated ? flat.slice(0, maxItems) : flat

  const rows = visible.map(it => {
    const { color, marker } = FILE_STATUS_STYLE[it.status] || { color: '#48484a', marker: '·' }
    const indent = 16 + it.depth * 18
    const weight = it.isDir ? 600 : 400
    return `<tr>
      <td style="padding:5px 12px 5px ${indent}px;font-size:12.5px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#1d1d1f;border-bottom:1px solid #f5f5f7;font-weight:${weight};">
        <span style="color:${color};display:inline-block;width:14px;font-weight:600;">${marker}</span>${htmlEscape(it.label)}
      </td>
      <td align="right" style="padding:5px 12px;font-size:11px;color:#8e8e93;border-bottom:1px solid #f5f5f7;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">${htmlEscape(it.size)}</td>
    </tr>`
  })
  if (truncated) {
    rows.push(`<tr><td colspan="2" style="padding:8px 14px;font-size:11px;color:#8e8e93;text-align:center;font-style:italic;">... 还有 ${flat.length - maxItems} 项未显示</td></tr>`)
  }
  return `<div style="margin:10px 0;">
    <div style="font-size:11px;font-weight:600;color:#8e8e93;letter-spacing:0.06em;text-transform:uppercase;margin-bottom:8px;padding:0 4px;">${title}</div>
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border:1px solid #ececef;border-radius:10px;overflow:hidden;border-collapse:separate;">${rows.join('')}</table>
  </div>`
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
