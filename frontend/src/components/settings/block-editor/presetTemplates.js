import { DEFAULT_EMAIL_HTML, DEFAULT_SUBJECT } from './defaultEmailTemplate.js'

export const PRESET_TEMPLATES = [
  {
    id: 'preset-universal-white',
    name: '通用通知 · 极简白',
    description: '一个模板覆盖完成、失败、等待人工和所有任务类型',
    icon: 'Mail',
    event_types: ['completed', 'failed', 'waiting_manual'],
    task_domains: [],
    editor_mode: 'html',
    subject_template: DEFAULT_SUBJECT,
    html_template: DEFAULT_EMAIL_HTML,
    text_template: '{事件名称}\n{任务标题}\n{摘要}',
    blocks: null,
  },
]
