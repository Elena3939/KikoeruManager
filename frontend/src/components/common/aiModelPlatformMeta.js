import { defineComponent, h } from 'vue'
import alibabacloudIconUrl from '../../assets/ai-platforms/alibabacloud.svg'
import anthropicIconUrl from '../../assets/ai-platforms/anthropic.svg'
import azureIconUrl from '../../assets/ai-platforms/azure.svg'
import deepseekIconUrl from '../../assets/ai-platforms/deepseek.svg'
import googleIconUrl from '../../assets/ai-platforms/google.svg'
import mistralIconUrl from '../../assets/ai-platforms/mistral.svg'
import ollamaIconUrl from '../../assets/ai-platforms/ollama.svg'
import openaiIconUrl from '../../assets/ai-platforms/openai.svg'
import openrouterIconUrl from '../../assets/ai-platforms/openrouter.svg'
import perplexityIconUrl from '../../assets/ai-platforms/perplexity.svg'
import xIconUrl from '../../assets/ai-platforms/x.svg'

const AI_PLATFORM_ICON_URLS = {
  alibabacloud: alibabacloudIconUrl,
  anthropic: anthropicIconUrl,
  azure: azureIconUrl,
  deepseek: deepseekIconUrl,
  google: googleIconUrl,
  mistral: mistralIconUrl,
  ollama: ollamaIconUrl,
  openai: openaiIconUrl,
  openrouter: openrouterIconUrl,
  perplexity: perplexityIconUrl,
  x: xIconUrl,
}

function createAIPlatformIconComponent(src, label) {
  if (!src) return null
  return defineComponent({
    name: `${String(label || 'AIPlatform').replace(/[^a-z0-9]+/gi, '') || 'AIPlatform'}Icon`,
    setup() {
      return () => h('img', {
        src,
        alt: label,
        draggable: 'false',
        class: 'ai-model-option-icon',
      })
    },
  })
}

export const AI_MODEL_PLATFORM_META = {
  openai: {
    key: 'openai',
    label: 'OpenAI',
    title: 'OpenAI',
    iconSrc: AI_PLATFORM_ICON_URLS.openai,
    aliases: ['openai', 'gpt', 'o1', 'o3', 'o4'],
    hosts: ['api.openai.com', 'openai.com'],
  },
  azure: {
    key: 'azure',
    label: 'Azure OpenAI',
    title: 'Azure OpenAI',
    iconSrc: AI_PLATFORM_ICON_URLS.azure,
    aliases: ['azure', 'azure_openai', 'azure-openai'],
    hosts: ['openai.azure.com', 'azure.microsoft.com'],
  },
  anthropic: {
    key: 'anthropic',
    label: 'Anthropic',
    title: 'Anthropic',
    iconSrc: AI_PLATFORM_ICON_URLS.anthropic,
    aliases: ['anthropic', 'claude'],
    hosts: ['anthropic.com', 'claude.ai'],
  },
  google: {
    key: 'google',
    label: 'Google AI',
    title: 'Google AI',
    iconSrc: AI_PLATFORM_ICON_URLS.google,
    aliases: ['google', 'gemini', 'vertex_ai', 'vertex-ai', 'palm'],
    hosts: ['googleapis.com', 'ai.google.dev', 'cloud.google.com'],
  },
  deepseek: {
    key: 'deepseek',
    label: 'DeepSeek',
    title: 'DeepSeek',
    iconSrc: AI_PLATFORM_ICON_URLS.deepseek,
    aliases: ['deepseek'],
    hosts: ['deepseek.com'],
  },
  openrouter: {
    key: 'openrouter',
    label: 'OpenRouter',
    title: 'OpenRouter',
    iconSrc: AI_PLATFORM_ICON_URLS.openrouter,
    aliases: ['openrouter'],
    hosts: ['openrouter.ai'],
  },
  mistral: {
    key: 'mistral',
    label: 'Mistral AI',
    title: 'Mistral AI',
    iconSrc: AI_PLATFORM_ICON_URLS.mistral,
    aliases: ['mistral', 'mistralai', 'mixtral', 'codestral'],
    hosts: ['mistral.ai'],
  },
  ollama: {
    key: 'ollama',
    label: 'Ollama',
    title: 'Ollama',
    iconSrc: AI_PLATFORM_ICON_URLS.ollama,
    aliases: ['ollama'],
    hosts: ['ollama.com'],
  },
  groq: {
    key: 'groq',
    label: 'Groq',
    title: 'Groq',
    iconSrc: '',
    aliases: ['groq'],
    hosts: ['groq.com'],
  },
  xai: {
    key: 'xai',
    label: 'xAI',
    title: 'xAI',
    iconSrc: AI_PLATFORM_ICON_URLS.x,
    aliases: ['xai', 'grok'],
    hosts: ['x.ai'],
  },
  siliconflow: {
    key: 'siliconflow',
    label: 'SiliconFlow',
    title: 'SiliconFlow',
    iconSrc: '',
    aliases: ['siliconflow'],
    hosts: ['siliconflow.cn'],
  },
  moonshot: {
    key: 'moonshot',
    label: 'Moonshot',
    title: 'Moonshot',
    iconSrc: '',
    aliases: ['moonshot', 'kimi'],
    hosts: ['moonshot.cn'],
  },
  zhipu: {
    key: 'zhipu',
    label: '智谱 AI',
    title: '智谱 AI',
    iconSrc: '',
    aliases: ['zhipu', 'glm', 'bigmodel'],
    hosts: ['bigmodel.cn'],
  },
  dashscope: {
    key: 'dashscope',
    label: '阿里云百炼',
    title: '阿里云百炼',
    iconSrc: AI_PLATFORM_ICON_URLS.alibabacloud,
    aliases: ['dashscope', 'qwen', 'qwq', 'qvq', 'tongyi'],
    hosts: ['dashscope.aliyuncs.com', 'aliyun.com'],
  },
  baichuan: {
    key: 'baichuan',
    label: '百川智能',
    title: '百川智能',
    iconSrc: '',
    aliases: ['baichuan'],
    hosts: ['baichuan-ai.com'],
  },
  volcengine: {
    key: 'volcengine',
    label: '火山引擎',
    title: '火山引擎',
    iconSrc: '',
    aliases: ['volcengine', 'doubao', 'ark'],
    hosts: ['volcengine.com', 'volces.com'],
  },
  perplexity: {
    key: 'perplexity',
    label: 'Perplexity',
    title: 'Perplexity',
    iconSrc: AI_PLATFORM_ICON_URLS.perplexity,
    aliases: ['perplexity', 'sonar'],
    hosts: ['perplexity.ai'],
  },
  cohere: {
    key: 'cohere',
    label: 'Cohere',
    title: 'Cohere',
    iconSrc: '',
    aliases: ['cohere', 'command-r', 'command'],
    hosts: ['cohere.com'],
  },
}

Object.values(AI_MODEL_PLATFORM_META).forEach((meta) => {
  meta.icon = createAIPlatformIconComponent(meta.iconSrc, meta.label)
})

const ALIAS_TO_KEY = Object.values(AI_MODEL_PLATFORM_META).reduce((map, meta) => {
  meta.aliases.forEach(alias => { map[alias] = meta.key })
  return map
}, {})

function getHostname(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  try {
    return new URL(text.includes('://') ? text : `https://${text}`).hostname || ''
  } catch {
    return ''
  }
}

function labelFromHost(host) {
  const clean = String(host || '').trim().toLowerCase().replace(/^www\./, '')
  if (!clean) return '自定义模型服务'
  const first = clean.split('.', 1)[0]
  return first.length <= 4 ? first.toUpperCase() : first.replace(/-/g, ' ').replace(/\b\w/g, char => char.toUpperCase())
}

function normalizeModelToken(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/^models\//, '')
    .replace(/[^a-z0-9._/-]+/g, '-')
}

function keyFromModelId(model) {
  const raw = normalizeModelToken(model)
  if (!raw) return ''
  const segments = raw.split('/').filter(Boolean)
  const prefix = segments[0] || ''
  if (ALIAS_TO_KEY[prefix]) return ALIAS_TO_KEY[prefix]

  const id = segments[segments.length - 1] || raw
  if (ALIAS_TO_KEY[id]) return ALIAS_TO_KEY[id]
  for (const [alias, key] of Object.entries(ALIAS_TO_KEY).sort((a, b) => b[0].length - a[0].length)) {
    if (id === alias || id.startsWith(`${alias}-`) || id.startsWith(`${alias}_`) || id.includes(`-${alias}-`)) {
      return key
    }
  }
  return ''
}

function keyFromHost(apiBase) {
  const host = getHostname(apiBase).toLowerCase()
  if (!host) return ''
  for (const meta of Object.values(AI_MODEL_PLATFORM_META)) {
    if (meta.hosts.some(needle => host.includes(needle))) return meta.key
  }
  return ''
}

export function getAIModelPlatformKey(model, apiBase = '') {
  return keyFromModelId(model) || keyFromHost(apiBase) || ''
}

export function getAIModelPlatformMeta(model, apiBase = '') {
  const key = getAIModelPlatformKey(model, apiBase)
  const host = getHostname(apiBase)
  if (key && AI_MODEL_PLATFORM_META[key]) {
    return {
      ...AI_MODEL_PLATFORM_META[key],
      host,
    }
  }
  return {
    key: key || 'custom',
    label: host ? labelFromHost(host) : 'AI 模型',
    title: host ? labelFromHost(host) : 'AI 模型',
    host,
    icon: null,
    iconSrc: '',
    aliases: [],
    hosts: host ? [host] : [],
  }
}
