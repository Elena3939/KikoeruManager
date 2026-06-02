<template>
  <div class="ai-subtitle-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">模式策略</div>
        <div class="field-stack">
          <div class="mini-grid two">
            <SettingsToggleRow
              v-model="config.ai_subtitle_matching.enabled"
              title="启用 AI 配对"
              subtitle="配对请求只发送音频/字幕文件名和短 ID。"
            />
            <SettingsToggleRow
              v-model="config.ai_subtitle_matching.auto_apply_enabled"
              title="允许自动应用"
              subtitle="整单高置信且无冲突才直接写入。"
              :disabled="!config.ai_subtitle_matching.enabled"
            />
          </div>
          <div class="mini-grid two">
            <SettingsToggleRow
              v-model="config.ai_subtitle_matching.manual_assist_enabled"
              title="允许辅助草稿"
              subtitle="配对台自动预配对按钮可生成 AI 草稿。"
              :disabled="!config.ai_subtitle_matching.enabled"
            />
            <SettingsFieldCard label="默认模式">
              <AppDropdown v-model="config.ai_subtitle_matching.default_mode" :options="aiModeOptions" class="settings-field-dd" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="置信阈值">
              <SettingsNumberStepper v-model="config.ai_subtitle_matching.confidence_threshold" :min="0" :max="100" />
            </SettingsFieldCard>
            <SettingsFieldCard label="单次最大项数">
              <SettingsNumberStepper v-model="config.ai_subtitle_matching.max_items_per_request" :min="1" :max="500" />
            </SettingsFieldCard>
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">连接配置</div>
        <div class="field-stack">
          <div class="mini-grid two">
            <SettingsFieldCard label="模型">
              <div class="model-combo">
                <div class="model-platform-badge" :title="aiProviderIconTitle">
                  <img
                    v-if="aiProviderIconUrl"
                    :src="aiProviderIconUrl"
                    :alt="aiProviderIconLabel"
                    class="model-platform-img"
                    draggable="false"
                    @error="handleAIProviderIconError"
                  >
                  <Bot v-else :size="16" :stroke-width="2.25" />
                </div>
                <input v-model="config.ai_subtitle_matching.model" class="field-input model-combo-input" type="text" placeholder="openai/gpt-4o-mini">
                <AppDropdown
                  v-model="config.ai_subtitle_matching.model"
                  :options="aiSubtitleModelOptions"
                  placeholder="无模型列表"
                  class="model-combo-dd"
                  menu-class="ai-model-menu"
                  :menu-min-width="320"
                  :disabled="!aiSubtitleModelOptions.length"
                  >
                  <template #trigger="{ toggle, open }">
                    <button
                      type="button"
                      class="model-combo-trigger"
                      :class="{ 'is-open': open }"
                      :disabled="!aiSubtitleModelOptions.length"
                      title="选择已获取的模型"
                      @click="toggle"
                    >
                      <ChevronDown :size="15" :stroke-width="2.4" :class="{ 'is-open': open }" />
                    </button>
                  </template>
                </AppDropdown>
              </div>
            </SettingsFieldCard>
            <SettingsFieldCard label="API Key">
              <AnimatedPasswordInput
                v-model="config.ai_subtitle_matching.api_key"
                :reveal-value="aiSubtitleRevealedApiKey"
                placeholder="sk-..."
                autocomplete="new-password"
                @visibility-change="handleAISubtitleApiKeyVisibility"
              />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="Base URL">
              <input v-model="config.ai_subtitle_matching.api_base" class="field-input" type="text" placeholder="https://api.openai.com/v1">
            </SettingsFieldCard>
            <SettingsFieldCard label="代理">
              <input v-model="config.ai_subtitle_matching.proxy_url" class="field-input" type="text" placeholder="http://127.0.0.1:7890">
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="API Version">
              <input v-model="config.ai_subtitle_matching.api_version" class="field-input" type="text" placeholder="Azure 可选">
            </SettingsFieldCard>
            <SettingsFieldCard label="Organization">
              <input v-model="config.ai_subtitle_matching.organization" class="field-input" type="text" placeholder="OpenAI 组织 ID，可选">
            </SettingsFieldCard>
          </div>
          <div class="mini-grid three">
            <SettingsFieldCard label="超时秒数">
              <SettingsNumberStepper v-model="config.ai_subtitle_matching.timeout_seconds" :min="1" :max="300" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最大重试">
              <SettingsNumberStepper v-model="config.ai_subtitle_matching.max_retries" :min="0" :max="10" />
            </SettingsFieldCard>
            <SettingsFieldCard label="Temperature">
              <SettingsNumberStepper v-model="config.ai_subtitle_matching.temperature" :min="0" :max="2" :step="0.1" />
            </SettingsFieldCard>
          </div>
          <div class="model-fetch-row">
            <button type="button" class="ai-action-btn" :disabled="aiSubtitleModelsLoading" @click="fetchAISubtitleModels">
              <RefreshCw :size="14" :stroke-width="2.4" :class="{ 'spin-once': aiSubtitleModelsLoading }" />
              {{ aiSubtitleModelsButtonLabel }}
            </button>
          </div>
          <transition name="fade-up">
            <div
              v-if="aiSubtitleModelsResult"
              class="model-fetch-result"
              :class="aiSubtitleModelsResult.success ? 'is-success' : 'is-error'"
            >
              <template v-if="aiSubtitleModelsResult.success">
                {{ aiSubtitleModelsResult.message || `已获取 ${aiSubtitleModelOptions.length} 个模型` }}
              </template>
              <template v-else>
                {{ aiSubtitleModelsResult.error?.title || '获取模型失败' }}：{{ aiSubtitleModelsResult.error?.message || '模型服务未返回可用列表' }}
              </template>
            </div>
          </transition>
        </div>
      </div>
    </div>

    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">提示词</div>
        <div class="field-stack">
          <SettingsFieldCard label="Prompt Template">
            <textarea v-model="config.ai_subtitle_matching.prompt_template" class="field-input ai-subtitle-prompt" rows="8" />
          </SettingsFieldCard>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">连接测试</div>
        <div class="field-stack">
          <div class="ai-test-copy">
            测试会使用当前表单草稿，不需要先保存；返回结果会按固定错误码归一化。
          </div>
          <div class="service-action-row">
            <button type="button" class="ai-action-btn" :disabled="aiSubtitleTesting" @click="testAISubtitleMatching">
              <Wifi :size="14" :stroke-width="2.4" :class="{ 'spin-once': aiSubtitleTesting }" />
              测试连接
            </button>
          </div>
          <transition name="fade-up">
            <div v-if="aiSubtitleTestResult" class="service-result-card" :class="aiSubtitleTestResult.success ? 'is-success' : 'is-error'">
              <div class="service-result-grid">
                <div><span class="service-result-key">状态</span><strong>{{ aiSubtitleTestResult.success ? '可用' : '失败' }}</strong></div>
                <div><span class="service-result-key">模型</span><strong>{{ aiSubtitleTestResult.model || '-' }}</strong></div>
                <div><span class="service-result-key">耗时</span><strong>{{ aiSubtitleTestResult.duration_ms ?? 0 }} ms</strong></div>
                <div><span class="service-result-key">JSON</span><strong>{{ aiSubtitleTestResult.capabilities?.json_output ? '可用' : '-' }}</strong></div>
              </div>
              <div v-if="aiSubtitleTestResult.message" class="service-result-line">{{ aiSubtitleTestResult.message }}</div>
              <template v-if="aiSubtitleTestResult.error">
                <div class="service-result-line ai-result-error">{{ aiSubtitleTestResult.error.title }}：{{ aiSubtitleTestResult.error.message }}</div>
                <div class="service-result-line">{{ aiSubtitleTestResult.error.suggestion }}</div>
                <div v-if="aiSubtitleTestResult.error.code" class="service-result-line">错误码：{{ aiSubtitleTestResult.error.code }}</div>
                <div v-if="aiSubtitleTestResult.error.raw_summary" class="service-result-line">原始摘要：{{ aiSubtitleTestResult.error.raw_summary }}</div>
              </template>
            </div>
          </transition>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Bot, ChevronDown, RefreshCw, Wifi } from 'lucide-vue-next'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import AppDropdown from '../common/AppDropdown.vue'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import { getAIModelPlatformMeta } from '../common/aiModelPlatformMeta'
import { aiSubtitleMatchApi, API_BASE, configApi } from '../../api'

const props = defineProps({
  config: { type: Object, required: true }
})

const aiModeOptions = [
  { value: 'rule', label: '规则模式' },
  { value: 'ai_auto', label: 'AI 自动应用' },
  { value: 'rule_ai_auto', label: '规则 + AI 自动补全' },
  { value: 'ai_assist', label: 'AI 辅助草稿' }
]

const AI_SUBTITLE_MODELS_CACHE_KEY = 'kikoerumanager.ai_subtitle_models_cache.v1'
const AI_SUBTITLE_MODELS_CACHE_LIMIT = 12

const aiSubtitleTesting = ref(false)
const aiSubtitleTestResult = ref(null)
const aiSubtitleModelsLoading = ref(false)
const aiSubtitleModelsResult = ref(null)
const aiSubtitleRevealedApiKey = ref('')
const aiSubtitleRevealLoading = ref(false)
const aiProviderIconInfo = ref(null)
const aiProviderIconBroken = ref(false)
let aiProviderIconTimer = null
let aiProviderIconRequestId = 0

const aiSubtitleConfig = computed(() => props.config.ai_subtitle_matching || {})
const aiProviderLocalMeta = computed(() => getAIModelPlatformMeta(
  aiSubtitleConfig.value.model,
  aiSubtitleConfig.value.api_base
))
const aiProviderIconLabel = computed(() => aiProviderLocalMeta.value.label || aiProviderIconInfo.value?.label || 'AI 模型')
const aiProviderIconTitle = computed(() => {
  const host = aiProviderIconInfo.value?.host || aiProviderLocalMeta.value.host
  return host ? `${aiProviderIconLabel.value} · ${host}` : aiProviderIconLabel.value
})
const aiProviderIconUrl = computed(() => {
  if (aiProviderIconBroken.value) return ''
  return aiProviderLocalMeta.value.iconSrc || normalizeProviderIconUrl(aiProviderIconInfo.value?.icon_url || aiProviderIconInfo.value?.icon_path || '')
})
const aiSubtitleModelsCacheSignature = computed(() => buildAISubtitleModelsCacheSignature(aiSubtitleConfig.value))
const aiSubtitleModelsButtonLabel = computed(() => aiSubtitleModelOptions.value.length ? '刷新模型' : '获取模型')

const aiSubtitleModelOptions = computed(() => {
  const rows = Array.isArray(aiSubtitleModelsResult.value?.models) ? aiSubtitleModelsResult.value.models : []
  const currentModel = String(aiSubtitleConfig.value.model || '').trim()
  const normalizedRows = [...rows]
  if (currentModel && !normalizedRows.some(item => sameModelValue(item.value || item.id, currentModel))) {
    normalizedRows.unshift({
      id: modelLabelFromValue(currentModel),
      value: currentModel,
      owned_by: '当前',
      source: 'manual',
    })
  }
  return normalizedRows.map((item) => {
    const value = item.value || item.id
    const meta = getAIModelPlatformMeta(value, aiSubtitleConfig.value.api_base)
    return {
      value,
      label: item.id || item.value,
      description: item.value && item.value !== item.id ? `写入：${item.value}` : meta.label,
      suffix: item.owned_by || '',
      icon: meta.icon || undefined,
    }
  })
})

function normalizeCachePart(value) {
  return String(value || '').trim().replace(/\/+$/, '').toLowerCase()
}

function buildAISubtitleModelsCacheSignature(config) {
  const cfg = config || {}
  return [
    normalizeCachePart(cfg.api_base),
    normalizeCachePart(cfg.api_version),
    normalizeCachePart(cfg.organization),
    normalizeCachePart(cfg.proxy_url),
  ].join('|')
}

function readAISubtitleModelsCacheStore() {
  if (typeof window === 'undefined') return { version: 1, entries: {} }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(AI_SUBTITLE_MODELS_CACHE_KEY) || '{}')
    return parsed && typeof parsed === 'object' && parsed.entries
      ? parsed
      : { version: 1, entries: {} }
  } catch {
    return { version: 1, entries: {} }
  }
}

function writeAISubtitleModelsCacheStore(store) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(AI_SUBTITLE_MODELS_CACHE_KEY, JSON.stringify(store))
  } catch {
    // localStorage 满了不影响设置页本身使用。
  }
}

function normalizeModelsForCache(models) {
  return (Array.isArray(models) ? models : [])
    .map((item) => ({
      id: String(item?.id || item?.value || '').trim(),
      value: String(item?.value || item?.id || '').trim(),
      owned_by: String(item?.owned_by || '').trim(),
    }))
    .filter(item => item.id || item.value)
    .slice(0, 1200)
}

function loadCachedAISubtitleModels() {
  const signature = aiSubtitleModelsCacheSignature.value
  if (!signature.trim()) {
    aiSubtitleModelsResult.value = null
    return
  }
  const store = readAISubtitleModelsCacheStore()
  const entry = store.entries?.[signature]
  const models = normalizeModelsForCache(entry?.models || [])
  aiSubtitleModelsResult.value = models.length
    ? {
        success: true,
        status: 'ok',
        cached: true,
        cached_at: entry.cached_at || null,
        message: `已从本地缓存载入 ${models.length} 个模型`,
        models,
      }
    : null
}

function saveAISubtitleModelsCache(result) {
  const models = normalizeModelsForCache(result?.models || [])
  if (!result?.success || !models.length) return
  const signature = aiSubtitleModelsCacheSignature.value
  const store = readAISubtitleModelsCacheStore()
  const entries = { ...(store.entries || {}) }
  entries[signature] = {
    cached_at: new Date().toISOString(),
    model: String(aiSubtitleConfig.value.model || '').trim(),
    api_base: String(aiSubtitleConfig.value.api_base || '').trim(),
    models,
  }
  const trimmedEntries = Object.fromEntries(
    Object.entries(entries)
      .sort((a, b) => String(b[1]?.cached_at || '').localeCompare(String(a[1]?.cached_at || '')))
      .slice(0, AI_SUBTITLE_MODELS_CACHE_LIMIT)
  )
  writeAISubtitleModelsCacheStore({ version: 1, entries: trimmedEntries })
}

function sameModelValue(left, right) {
  return String(left || '').trim().toLowerCase() === String(right || '').trim().toLowerCase()
}

function modelLabelFromValue(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.split('/').filter(Boolean).pop() || text
}

function normalizeProviderIconUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  if (/^https?:\/\//i.test(raw) || raw.startsWith('data:')) return raw
  const suffix = raw.startsWith('/api/') ? raw.slice(4) : raw
  return `${API_BASE}${suffix.startsWith('/') ? suffix : `/${suffix}`}`
}

function handleAIProviderIconError() {
  aiProviderIconBroken.value = true
}

function scheduleAIProviderIconFetch() {
  if (aiProviderIconTimer) {
    window.clearTimeout(aiProviderIconTimer)
    aiProviderIconTimer = null
  }
  if (aiProviderLocalMeta.value.iconSrc) {
    aiProviderIconRequestId += 1
    aiProviderIconInfo.value = null
    aiProviderIconBroken.value = false
    return
  }
  aiProviderIconTimer = window.setTimeout(() => {
    aiProviderIconTimer = null
    fetchAIProviderIcon()
  }, 450)
}

async function fetchAIProviderIcon() {
  const requestId = ++aiProviderIconRequestId
  const model = aiSubtitleConfig.value.model || ''
  const apiBase = aiSubtitleConfig.value.api_base || ''
  const proxyUrl = aiSubtitleConfig.value.proxy_url || ''
  if (aiProviderLocalMeta.value.iconSrc) {
    aiProviderIconInfo.value = null
    aiProviderIconBroken.value = false
    return
  }
  aiProviderIconBroken.value = false
  try {
    const result = await aiSubtitleMatchApi.providerIcon({ model, apiBase, proxyUrl })
    if (requestId !== aiProviderIconRequestId) return
    aiProviderIconInfo.value = result || null
  } catch {
    if (requestId !== aiProviderIconRequestId) return
    aiProviderIconInfo.value = null
  }
}

async function handleAISubtitleApiKeyVisibility(visible) {
  if (!visible) return
  const current = aiSubtitleConfig.value.api_key
  if (current !== '********' || aiSubtitleRevealedApiKey.value || aiSubtitleRevealLoading.value) return
  aiSubtitleRevealLoading.value = true
  try {
    const result = await configApi.revealAISubtitleSecret({ key: 'api_key' })
    aiSubtitleRevealedApiKey.value = result?.value || ''
    if (!result?.value) {
      ElMessage.warning('配置文件里没有可显示的原始 API Key')
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '读取已保存 API Key 失败')
  } finally {
    aiSubtitleRevealLoading.value = false
  }
}

watch(
  () => [aiSubtitleConfig.value.model, aiSubtitleConfig.value.api_base, aiSubtitleConfig.value.proxy_url],
  scheduleAIProviderIconFetch,
  { immediate: true }
)

watch(
  aiSubtitleModelsCacheSignature,
  loadCachedAISubtitleModels,
  { immediate: true }
)

onBeforeUnmount(() => {
  if (aiProviderIconTimer) {
    window.clearTimeout(aiProviderIconTimer)
    aiProviderIconTimer = null
  }
})

async function fetchAISubtitleModels() {
  if (aiSubtitleModelsLoading.value) return
  aiSubtitleModelsLoading.value = true
  const previousResult = aiSubtitleModelsResult.value
  try {
    const result = await aiSubtitleMatchApi.models({ ...(props.config.ai_subtitle_matching || {}) })
    aiSubtitleModelsResult.value = result
    if (result?.success) {
      saveAISubtitleModelsCache(result)
      ElMessage.success(result.message || `已获取 ${result.models?.length || 0} 个模型`)
    } else {
      ElMessage.error(result?.error?.title || result?.error?.message || '获取模型失败')
    }
  } catch (e) {
    aiSubtitleModelsResult.value = {
      success: false,
      status: 'failed',
      error: {
        code: 'unknown_error',
        title: '获取模型失败',
        message: e.response?.data?.detail || e.message || '获取模型失败',
        suggestion: '检查 Base URL、API Key、代理和模型服务是否支持 /models'
      },
      models: Array.isArray(previousResult?.models) ? previousResult.models : []
    }
    ElMessage.error(aiSubtitleModelsResult.value.error.message)
  } finally {
    aiSubtitleModelsLoading.value = false
  }
}

async function testAISubtitleMatching() {
  if (aiSubtitleTesting.value) return
  aiSubtitleTesting.value = true
  aiSubtitleTestResult.value = null
  try {
    const result = await aiSubtitleMatchApi.test({ ...(props.config.ai_subtitle_matching || {}) })
    aiSubtitleTestResult.value = result
    if (result?.success) {
      ElMessage.success(result.message || 'AI 字幕配对模型可用')
    } else {
      ElMessage.error(result?.error?.title || result?.error?.message || 'AI 字幕配对测试失败')
    }
  } catch (e) {
    aiSubtitleTestResult.value = {
      success: false,
      status: 'failed',
      error: {
        code: 'unknown_error',
        title: '测试失败',
        message: e.response?.data?.detail || e.message || 'AI 字幕配对测试失败',
        suggestion: '检查后端日志和 AI 配置'
      }
    }
    ElMessage.error(aiSubtitleTestResult.value.error.message)
  } finally {
    aiSubtitleTesting.value = false
  }
}
</script>

<style scoped>
.ai-subtitle-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-grid,
.settings-card,
.mini-grid,
.field-stack {
  overflow: visible;
}

.settings-grid {
  display: grid;
  gap: 24px;
  align-items: start;
}

.settings-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.mini-grid { display: grid; gap: 10px; }
.mini-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.mini-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }

.field-stack {
  display: grid;
  gap: 12px;
}

.settings-card {
  padding: 0;
  border: none;
  background: transparent;
  box-shadow: none;
  min-height: 0;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 14px;
  color: var(--set-text-strong);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  background: var(--set-field-bg);
  color: var(--set-text-strong);
  font-size: 13.5px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:hover { border-color: var(--set-border-strong); }

.field-input:focus {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.field-input::placeholder { color: var(--set-text-subtle); }

.ai-subtitle-prompt {
  min-height: 220px;
  padding-top: 10px;
  padding-bottom: 10px;
  line-height: 1.55;
  resize: vertical;
}

.model-combo {
  position: relative;
  width: 100%;
  min-width: 0;
}

.model-platform-badge {
  position: absolute;
  top: 50%;
  left: 10px;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.82);
  color: var(--set-text-muted);
  box-shadow:
    inset 0 0 0 1px rgba(148, 163, 184, 0.2),
    0 1px 2px rgba(15, 23, 42, 0.08);
  transform: translateY(-50%);
  pointer-events: none;
}

.model-platform-img {
  width: 16px;
  height: 16px;
  object-fit: contain;
  border-radius: 4px;
}

.model-combo-input {
  padding-left: 40px;
  padding-right: 46px;
}

.model-combo-dd {
  position: absolute;
  top: 1px;
  right: 1px;
  display: block;
  width: 40px;
  height: calc(100% - 2px);
  background: transparent;
}

.model-combo-dd :deep(.app-dd-trigger-anchor) {
  display: block;
  width: 100%;
  height: 100%;
}

.model-combo-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border: 0;
  border-left: 1px solid var(--set-border);
  border-radius: 0 9px 9px 0;
  background: transparent;
  color: var(--set-text-muted);
  cursor: pointer;
  transition: color 0.2s ease, background 0.2s ease;
}

.model-combo-trigger:not(:disabled):hover {
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
}

.model-combo-trigger:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.model-combo-trigger svg {
  transition: transform 0.25s ease;
}

.model-combo-trigger svg.is-open {
  transform: rotate(180deg);
}

.model-combo :deep(.ai-model-option-icon) {
  width: 16px;
  height: 16px;
  object-fit: contain;
  border-radius: 4px;
}

:global(.ai-model-menu .ai-model-option-icon) {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  padding: 3px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.92);
  object-fit: contain;
  box-shadow:
    inset 0 0 0 1px rgba(148, 163, 184, 0.18),
    0 1px 2px rgba(15, 23, 42, 0.1);
  opacity: 1;
  filter: none;
}

:global(html.kikoerumanager-dark .ai-model-menu .ai-model-option-icon) {
  background: rgba(255, 255, 255, 0.94);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.16),
    0 1px 3px rgba(0, 0, 0, 0.3);
  opacity: 1;
  filter: none;
}

.settings-field-dd { display: block; width: 100%; }
.settings-field-dd :deep(.app-dd-root) { display: block; width: 100%; }

.settings-field-dd :deep(.app-dd-trigger) {
  width: 100%;
  min-height: 38px;
  height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  background: var(--set-field-bg);
  border: 1px solid var(--set-border);
  font-size: 13.5px;
  justify-content: space-between;
}

.settings-field-dd :deep(.app-dd-trigger:hover) { border-color: var(--set-border-strong); }
.settings-field-dd :deep(.app-dd-trigger.is-open) {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.ai-test-copy {
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--set-border);
  background: var(--set-surface-soft);
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.6;
}

.model-fetch-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
}

.model-fetch-result {
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid var(--set-border);
  background: var(--set-surface-soft);
  color: var(--set-text);
  font-size: 12.5px;
  line-height: 1.55;
}

.model-fetch-result.is-success {
  border-color: var(--set-success-border);
  background: var(--set-success-bg);
  color: var(--set-success-text);
}

.model-fetch-result.is-error {
  border-color: var(--set-danger-border);
  background: var(--set-danger-bg);
  color: var(--set-danger-text);
}

.service-action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.ai-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
  color: var(--set-text);
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.ai-action-btn:not(:disabled):hover {
  transform: translateY(-1px);
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
}

.ai-action-btn:hover:not(:disabled) svg:not(.spin-once) {
  transform: rotate(-360deg);
  transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.ai-action-btn:active:not(:disabled) { transform: scale(0.96); }
.ai-action-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.service-result-card {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid var(--set-border);
  background: var(--set-surface-soft);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(15, 23, 42, 0.04);
}

.service-result-card.is-success {
  border-color: var(--set-success-border);
  background: var(--set-success-bg);
}

.service-result-card.is-error {
  border-color: var(--set-danger-border);
  background: var(--set-danger-bg);
}

.service-result-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 8px;
}

.service-result-key {
  display: block;
  margin-bottom: 3px;
  color: var(--set-text-muted);
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
}

.service-result-line {
  color: var(--set-text-strong);
  font-size: 13px;
  line-height: 1.6;
  letter-spacing: -0.05px;
}

.ai-result-error {
  margin-top: 8px;
  color: var(--set-danger-text);
}

.fade-up-enter-active,
.fade-up-leave-active { transition: all 0.24s ease; }
.fade-up-enter-from,
.fade-up-leave-to { opacity: 0; transform: translateY(5px); }

@keyframes spin-once { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.spin-once { animation: spin-once 0.7s linear infinite; }

:global(html.kikoerumanager-dark .model-platform-badge) {
  background: rgba(255, 255, 255, 0.94);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.16),
    0 1px 3px rgba(0, 0, 0, 0.28);
}

@media (max-width: 1200px) {
  .settings-grid.two,
  .mini-grid.two,
  .mini-grid.three,
  .service-result-grid { grid-template-columns: 1fr; }

  .model-fetch-row {
    grid-template-columns: 1fr;
  }
}
</style>
