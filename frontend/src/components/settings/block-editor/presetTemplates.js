import { DEFAULT_EMAIL_HTML, DEFAULT_SUBJECT, buildDefaultEmailBlocks } from './defaultEmailTemplate.js'

export const PRESET_TEMPLATES = [
  {
    id: 'preset-universal-white',
    name: '通用通知 · 极简白',
    description: '一个模板覆盖完成、失败、等待人工和所有任务类型',
    icon: 'Mail',
    event_types: ['completed', 'failed', 'waiting_manual'],
    task_domains: [],
    // 默认进入积木编辑器（已拆分为多个独立块），用户也可在编辑器内一键切回 HTML 模式
    editor_mode: 'blocks',
    subject_template: DEFAULT_SUBJECT,
    html_template: DEFAULT_EMAIL_HTML,
    text_template: '{事件名称}\n{任务标题}\n{摘要}',
    // 函数式：每次打开预设都生成全新 ID，避免多次保存出现重复块 id
    buildBlocks: buildDefaultEmailBlocks,
  },
]
