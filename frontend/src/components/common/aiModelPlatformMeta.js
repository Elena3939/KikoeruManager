import { defineComponent, h } from 'vue'
import alibabacloudIconUrl from '../../assets/ai-platforms/alibabacloud.svg'
import anthropicIconUrl from '../../assets/ai-platforms/anthropic-official.ico'
import azureIconUrl from '../../assets/ai-platforms/azure.svg'
import baichuanIconUrl from '../../assets/ai-platforms/baichuan.ico'
import baiduIconUrl from '../../assets/ai-platforms/baidu.ico'
import cohereIconUrl from '../../assets/ai-platforms/cohere.ico'
import deepseekIconUrl from '../../assets/ai-platforms/deepseek.ico'
import geminiIconUrl from '../../assets/ai-platforms/gemini.svg'
import groqIconUrl from '../../assets/ai-platforms/groq.ico'
import hunyuanIconUrl from '../../assets/ai-platforms/hunyuan.ico'
import iflytekIconUrl from '../../assets/ai-platforms/iflytek.ico'
import internlmIconUrl from '../../assets/ai-platforms/internlm.ico'
import mimoIconUrl from '../../assets/ai-platforms/mimo.png'
import minimaxIconUrl from '../../assets/ai-platforms/minimax.ico'
import mistralIconUrl from '../../assets/ai-platforms/mistral.svg'
import moonshotIconUrl from '../../assets/ai-platforms/moonshot.ico'
import ollamaIconUrl from '../../assets/ai-platforms/ollama.svg'
import openaiIconUrl from '../../assets/ai-platforms/openai.svg'
import openbmbIconUrl from '../../assets/ai-platforms/openbmb.ico'
import openrouterIconUrl from '../../assets/ai-platforms/openrouter.svg'
import perplexityIconUrl from '../../assets/ai-platforms/perplexity.svg'
import qwenIconUrl from '../../assets/ai-platforms/qwen.ico'
import sensenovaIconUrl from '../../assets/ai-platforms/sensenova.ico'
import siliconflowIconUrl from '../../assets/ai-platforms/siliconflow.png'
import stepfunIconUrl from '../../assets/ai-platforms/stepfun-ai.ico'
import volcengineIconUrl from '../../assets/ai-platforms/volcengine.png'
import xIconUrl from '../../assets/ai-platforms/x.svg'
import yiIconUrl from '../../assets/ai-platforms/yi.ico'
import zhipuIconUrl from '../../assets/ai-platforms/zhipu.png'

const AI_PLATFORM_ICON_URLS = {
  alibabacloud: alibabacloudIconUrl,
  anthropic: anthropicIconUrl,
  azure: azureIconUrl,
  baichuan: baichuanIconUrl,
  baidu: baiduIconUrl,
  cohere: cohereIconUrl,
  deepseek: deepseekIconUrl,
  gemini: geminiIconUrl,
  google: geminiIconUrl,
  groq: groqIconUrl,
  hunyuan: hunyuanIconUrl,
  iflytek: iflytekIconUrl,
  internlm: internlmIconUrl,
  mimo: mimoIconUrl,
  minimax: minimaxIconUrl,
  mistral: mistralIconUrl,
  moonshot: moonshotIconUrl,
  ollama: ollamaIconUrl,
  openai: openaiIconUrl,
  openbmb: openbmbIconUrl,
  openrouter: openrouterIconUrl,
  perplexity: perplexityIconUrl,
  qwen: qwenIconUrl,
  sensenova: sensenovaIconUrl,
  siliconflow: siliconflowIconUrl,
  stepfun: stepfunIconUrl,
  volcengine: volcengineIconUrl,
  x: xIconUrl,
  yi: yiIconUrl,
  zhipu: zhipuIconUrl,
}

function createAIPlatformIconComponent(src, label, key = '') {
  if (!src) return null
  return defineComponent({
    name: `${String(label || 'AIPlatform').replace(/[^a-z0-9]+/gi, '') || 'AIPlatform'}Icon`,
    setup() {
      const iconKey = String(key || '').replace(/[^a-z0-9_-]+/gi, '-').toLowerCase()
      return () => h('img', {
        src,
        alt: label,
        draggable: 'false',
        class: ['ai-model-option-icon', iconKey ? `ai-model-option-icon--${iconKey}` : ''],
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
    iconSrc: AI_PLATFORM_ICON_URLS.gemini,
    aliases: ['google', 'google-ai', 'google_ai', 'gemini', 'vertex_ai', 'vertex-ai', 'palm'],
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
    iconSrc: AI_PLATFORM_ICON_URLS.groq,
    aliases: ['groq'],
    hosts: ['groq.com'],
  },
  mimo: {
    key: 'mimo',
    label: 'MiMo',
    title: 'MiMo',
    iconSrc: AI_PLATFORM_ICON_URLS.mimo,
    aliases: ['mimo'],
    hosts: ['mimo.mi.com'],
  },
  xai: {
    key: 'xai',
    label: 'xAI',
    title: 'xAI',
    iconSrc: AI_PLATFORM_ICON_URLS.x,
    aliases: ['xai', 'x-ai', 'x_ai', 'grok'],
    hosts: ['x.ai'],
  },
  siliconflow: {
    key: 'siliconflow',
    label: 'SiliconFlow',
    title: 'SiliconFlow',
    iconSrc: AI_PLATFORM_ICON_URLS.siliconflow,
    aliases: ['siliconflow'],
    hosts: ['siliconflow.cn'],
  },
  moonshot: {
    key: 'moonshot',
    label: 'Moonshot',
    title: 'Moonshot',
    iconSrc: AI_PLATFORM_ICON_URLS.moonshot,
    aliases: ['moonshot', 'kimi'],
    hosts: ['moonshot.cn'],
  },
  zhipu: {
    key: 'zhipu',
    label: '智谱 AI',
    title: '智谱 AI',
    iconSrc: AI_PLATFORM_ICON_URLS.zhipu,
    aliases: ['zhipu', 'glm', 'bigmodel'],
    hosts: ['bigmodel.cn'],
  },
  dashscope: {
    key: 'dashscope',
    label: '通义千问',
    title: '通义千问 / 阿里云百炼',
    iconSrc: AI_PLATFORM_ICON_URLS.qwen,
    aliases: ['dashscope', 'bailian', 'qwen', 'qwen2', 'qwen2.5', 'qwen3', 'qwq', 'qvq', 'tongyi'],
    hosts: ['dashscope.aliyuncs.com', 'bailian.aliyun.com', 'aliyun.com', 'qwen.ai'],
  },
  baidu: {
    key: 'baidu',
    label: '百度千帆',
    title: '百度千帆 / 文心一言',
    iconSrc: AI_PLATFORM_ICON_URLS.baidu,
    aliases: ['baidu', 'qianfan', 'wenxin', 'ernie', 'yiyan'],
    hosts: ['qianfan.cloud.baidu.com', 'cloud.baidu.com', 'baidubce.com', 'wenxin.baidu.com'],
  },
  hunyuan: {
    key: 'hunyuan',
    label: '腾讯混元',
    title: '腾讯混元',
    iconSrc: AI_PLATFORM_ICON_URLS.hunyuan,
    aliases: ['hunyuan', 'tencent'],
    hosts: ['hunyuan.tencent.com', 'cloud.tencent.com', 'tencent.com'],
  },
  minimax: {
    key: 'minimax',
    label: 'MiniMax',
    title: 'MiniMax',
    iconSrc: AI_PLATFORM_ICON_URLS.minimax,
    aliases: ['minimax', 'abab', 'abab5', 'abab5.5', 'abab6', 'abab6.5', 'abab6.5s'],
    hosts: ['minimaxi.com', 'minimax.io'],
  },
  yi: {
    key: 'yi',
    label: '零一万物',
    title: '零一万物 / 01.AI',
    iconSrc: AI_PLATFORM_ICON_URLS.yi,
    aliases: ['yi', '01ai', '01-ai', 'lingyi', 'lingyiwanwu'],
    hosts: ['01.ai', 'lingyiwanwu.com'],
  },
  stepfun: {
    key: 'stepfun',
    label: '阶跃星辰',
    title: '阶跃星辰 StepFun',
    iconSrc: AI_PLATFORM_ICON_URLS.stepfun,
    aliases: ['stepfun', 'step'],
    hosts: ['stepfun.ai', 'stepfun.com'],
  },
  baichuan: {
    key: 'baichuan',
    label: '百川智能',
    title: '百川智能',
    iconSrc: AI_PLATFORM_ICON_URLS.baichuan,
    aliases: ['baichuan'],
    hosts: ['baichuan-ai.com'],
  },
  volcengine: {
    key: 'volcengine',
    label: '火山引擎',
    title: '火山引擎',
    iconSrc: AI_PLATFORM_ICON_URLS.volcengine,
    aliases: ['volcengine', 'doubao', 'ark'],
    hosts: ['volcengine.com', 'volces.com'],
  },
  iflytek: {
    key: 'iflytek',
    label: '讯飞星火',
    title: '讯飞星火',
    iconSrc: AI_PLATFORM_ICON_URLS.iflytek,
    aliases: ['iflytek', 'xinghuo', 'spark', 'sparkdesk'],
    hosts: ['xfyun.cn', 'sparkdesk.iflytek.com'],
  },
  sensenova: {
    key: 'sensenova',
    label: '商汤日日新',
    title: '商汤日日新 SenseNova',
    iconSrc: AI_PLATFORM_ICON_URLS.sensenova,
    aliases: ['sensenova', 'sensechat', 'sensetime'],
    hosts: ['sensenova.cn', 'sensetime.com'],
  },
  internlm: {
    key: 'internlm',
    label: '书生浦语',
    title: '书生浦语 InternLM',
    iconSrc: AI_PLATFORM_ICON_URLS.internlm,
    aliases: ['internlm', 'intern-s1', 'internvl', 'intern'],
    hosts: ['intern-ai.org.cn'],
  },
  openbmb: {
    key: 'openbmb',
    label: 'OpenBMB',
    title: 'OpenBMB / MiniCPM',
    iconSrc: AI_PLATFORM_ICON_URLS.openbmb,
    aliases: ['openbmb', 'minicpm', 'cpm'],
    hosts: ['openbmb.cn'],
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
    iconSrc: AI_PLATFORM_ICON_URLS.cohere,
    aliases: ['cohere', 'command-r', 'command'],
    hosts: ['cohere.com'],
  },
}

Object.values(AI_MODEL_PLATFORM_META).forEach((meta) => {
  meta.icon = createAIPlatformIconComponent(meta.iconSrc, meta.label, meta.key)
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
    if (
      id === alias
      || id.startsWith(`${alias}-`)
      || id.startsWith(`${alias}_`)
      || id.startsWith(`${alias}.`)
      || (alias.length >= 4 && id.startsWith(alias))
      || id.includes(`-${alias}-`)
    ) {
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
