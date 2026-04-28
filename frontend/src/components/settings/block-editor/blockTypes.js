/**
 * Block 编辑器公共配置
 * - BLOCK_TYPES：E1 支持的块类型定义
 * - VARIABLES：可注入的变量列表
 * - createBlock(type)：工厂函数
 */

export const BLOCK_TYPES = {
  header_status: {
    label: '状态头部',
    icon: 'LayoutTemplate',
    description: '顶部状态颜色区块，包含标题和摘要',
    group: 'layout',
    color: '#0071e3',
    defaultProps: {
      titleKey:    '任务标题',
      summaryKey:  '摘要',
      severityKey: '严重程度',
    },
    propSchema: [
      { key: 'titleKey',    label: '标题变量', type: 'variable', default: '任务标题' },
      { key: 'summaryKey',  label: '摘要变量', type: 'variable', default: '摘要' },
      { key: 'severityKey', label: '颜色变量', type: 'variable', default: '严重程度' },
    ],
  },
  summary_card: {
    label: '摘要卡片',
    icon: 'FileText',
    description: '带侧边颜色条的摘要信息卡片',
    group: 'content',
    color: '#34c759',
    defaultProps: {
      label:       '任务摘要',
      valueKey:    '摘要',
      accentColor: '#0071e3',
    },
    propSchema: [
      { key: 'label',       label: '标签文字', type: 'text',     default: '任务摘要' },
      { key: 'valueKey',    label: '内容变量', type: 'variable', default: '摘要' },
      { key: 'accentColor', label: '强调色',   type: 'color',    default: '#0071e3' },
    ],
  },
  rich_text: {
    label: '富文本',
    icon: 'Type',
    description: '支持格式化的文本内容，可插入 {变量}',
    group: 'content',
    color: '#ff9500',
    defaultProps: {
      contentJson: null,
      htmlCache:   '',
    },
    propSchema: [
      { key: 'contentJson', label: '富文本内容', type: 'richtext' },
      { key: 'htmlCache',   label: 'HTML 缓存',  type: 'hidden' },
    ],
  },
  divider: {
    label: '分割线',
    icon: 'Minus',
    description: '水平分割线',
    group: 'layout',
    color: '#8e8e93',
    defaultProps: {
      color:  '#e5e5ea',
      margin: 16,
    },
    propSchema: [
      { key: 'color',  label: '颜色',        type: 'color',  default: '#e5e5ea' },
      { key: 'margin', label: '上下间距(px)', type: 'number', min: 0, max: 64, default: 16 },
    ],
  },
  spacer: {
    label: '间距块',
    icon: 'AlignJustify',
    description: '空白间距占位',
    group: 'layout',
    color: '#c7c7cc',
    defaultProps: {
      height: 16,
    },
    propSchema: [
      { key: 'height', label: '高度(px)', type: 'number', min: 4, max: 120, default: 16 },
    ],
  },

  // ─── 业务数据块 ───────────────────────────────────────────
  stats_grid: {
    label: '统计网格',
    icon: 'LayoutGrid',
    description: '多列数字统计（总文件数 / 总大小 / 耗时等）',
    group: 'data',
    color: '#5856d6',
    defaultProps: {
      columns: 3,
      items: [
        { key: 'total_files', label: '总文件数', icon: '📁' },
        { key: 'total_size',  label: '总大小',   icon: '💾' },
        { key: 'duration',    label: '耗时',     icon: '⏱' },
      ],
    },
    propSchema: [
      { key: 'columns', label: '每行列数', type: 'number', min: 1, max: 4, default: 3 },
      { key: 'items',   label: '字段配置', type: 'stats_items' },
    ],
  },
  file_tree: {
    label: '文件树',
    icon: 'FolderTree',
    description: '文件 / 目录树（上下载、解压过滤场景）',
    group: 'data',
    color: '#34c759',
    defaultProps: {
      title:     '文件清单',
      sourceKey: 'file_tree',
      maxItems:  30,
    },
    propSchema: [
      { key: 'title',     label: '标题',         type: 'text',   default: '文件清单' },
      { key: 'sourceKey', label: '数据来源',     type: 'data_source', default: 'file_tree',
        options: [
          { value: 'file_tree',       label: '通用文件树' },
          { value: 'download_files',  label: '下载文件列表' },
          { value: 'upload_files',    label: '上传文件列表' },
          { value: 'filtered_files',  label: '过滤前后对比' },
          { value: 'extracted_files', label: '解压结果' },
        ] },
      { key: 'maxItems',  label: '最多显示行数', type: 'number', min: 5, max: 200, default: 30 },
    ],
  },
  diff_view: {
    label: '差异对比',
    icon: 'GitCompare',
    description: '新旧值对比（社团补全 / 字幕匹配场景）',
    group: 'data',
    color: '#ff9500',
    defaultProps: {
      title:     '数据差异',
      sourceKey: 'diff_items',
    },
    propSchema: [
      { key: 'title',     label: '标题',     type: 'text', default: '数据差异' },
      { key: 'sourceKey', label: '数据来源', type: 'data_source', default: 'diff_items',
        options: [
          { value: 'diff_items',    label: '通用差异' },
          { value: 'circle_diff',   label: '社团补全差异' },
          { value: 'subtitle_diff', label: '字幕配对差异' },
          { value: 'metadata_diff', label: '元数据差异' },
        ] },
    ],
  },
  task_log: {
    label: '执行日志',
    icon: 'Terminal',
    description: '最近 N 行任务执行日志（黑底等宽字体）',
    group: 'data',
    color: '#1d1d1f',
    defaultProps: {
      title:     '执行日志',
      sourceKey: 'recent_logs',
      maxLines:  30,
    },
    propSchema: [
      { key: 'title',     label: '标题',     type: 'text',   default: '执行日志' },
      { key: 'sourceKey', label: '数据来源', type: 'data_source', default: 'recent_logs',
        options: [
          { value: 'recent_logs',  label: '通用最近日志' },
          { value: 'error_logs',   label: '错误日志' },
          { value: 'warning_logs', label: '警告日志' },
        ] },
      { key: 'maxLines',  label: '最多行数', type: 'number', min: 3, max: 50, default: 30 },
    ],
  },
}

export const BLOCK_GROUPS = [
  { key: 'layout',  label: '布局' },
  { key: 'content', label: '内容' },
  { key: 'data',    label: '业务数据' },
]

/**
 * 变量列表 — 给业务用户用的中文 key
 *
 * - `key` 是用户在模板里看到 / 写入的占位名（{任务标题}）
 * - `aliasEn` 是后端识别的英文别名，老模板兼容用
 * - `example` 是预览时填充的示例值
 */
export const VARIABLES = [
  { key: '任务标题',  aliasEn: 'title',            example: '示例任务标题' },
  { key: '摘要',      aliasEn: 'summary',          example: '批量任务结束，3/3 个完成' },
  { key: '任务类型',  aliasEn: 'domain_label',     example: '导入处理' },
  { key: 'RJ号',      aliasEn: 'rjcode',           example: 'RJ123456' },
  { key: '事件名称',  aliasEn: 'event_label',      example: '任务完成' },
  { key: '事件图标',  aliasEn: 'event_icon',       example: '✅' },
  { key: '时间',      aliasEn: 'created_at',       example: '2024-01-01 12:00:00' },
  { key: '严重程度',  aliasEn: 'severity',         example: 'success' },
  { key: '总文件数',  aliasEn: 'stats.total_files',example: '10' },
  { key: '总大小',    aliasEn: 'stats.total_size', example: '256 MB' },
  { key: '业务数据块', aliasEn: 'payload_sections', example: '自动渲染统计 / 文件树 / 日志' },
  { key: '统计网格',  aliasEn: 'stats_grid_section', example: '自动渲染统计网格' },
  { key: '文件树',    aliasEn: 'file_tree_section',  example: '自动渲染文件清单' },
  { key: '差异对比',  aliasEn: 'diff_section',       example: '自动渲染差异列表' },
  { key: '执行日志',  aliasEn: 'task_log_section',   example: '自动渲染执行日志' },
]

// 向下兼容：老组件用 v.label 拿展示文本，统一指向 key 自身
VARIABLES.forEach(v => { v.label = v.key })

/**
 * 生成唯一的 block id（nanoid 的简单替代）
 */
function uid() {
  return 'blk_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
}

/**
 * 创建新 Block 对象
 * @param {string} type
 * @returns {object}
 */
export function createBlock(type) {
  const meta = BLOCK_TYPES[type]
  if (!meta) throw new Error(`Unknown block type: ${type}`)
  return {
    id:            uid(),
    type,
    enabled:       true,
    schemaVersion: 1,
    props:         { ...(meta.defaultProps || {}) },
  }
}

/**
 * 深拷贝一个 block 并赋予新 id
 */
export function cloneBlock(block) {
  return {
    ...JSON.parse(JSON.stringify(block)),
    id: uid(),
  }
}
