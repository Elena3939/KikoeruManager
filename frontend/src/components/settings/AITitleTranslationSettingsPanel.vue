<template>
  <div class="ai-title-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">翻译策略</div>
        <div class="field-stack">
          <div class="mini-grid two">
            <SettingsToggleRow
              v-model="cfg.enabled"
              title="启用 AI 标题汉化"
              subtitle="元数据获取后，若作品名仍为日文则调用 AI 翻译为中文，结果存入 ai_title 字段，不覆盖原始标题"
            />
            <SettingsFieldCard label="每批数量">
              <SettingsNumberStepper v-model="cfg.batch_size" :min="1" :max="20" />
            </SettingsFieldCard>
          </div>
        </div>
      </div>

      <SettingsToggleRow
        v-model="useAiSubtitleApi"
        title="复用 AI 配对 API 配置"
        subtitle="使用 AI 字幕配对中的模型、API Key、Base URL 等连接设置"
        class="reuse-toggle"
      />

      <div v-if="!useAiSubtitleApi" class="settings-card">
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
                    :class="{ 'is-dark-monochrome': ['openai', 'xai', 'openrouter'].includes(aiProviderLocalMeta.key) }"
                    draggable="false"
                    @error="handleAIProviderIconError"
                  >
                  <Bot v-else :size="16" :stroke-width="2.25" />
                </div>
                <input v-model="cfg.model" class="model-combo-input" type="text" placeholder="openai/gpt-4o-mini">
              </div>
            </SettingsFieldCard>
            <SettingsFieldCard label="API Key">
              <AnimatedPasswordInput
                v-model="cfg.api_key"
                class="ai-api-key-input"
                :reveal-value="aiTitleRevealedApiKey"
                placeholder="sk-..."
                autocomplete="new-password"
                @visibility-change="handleAITitleApiKeyVisibility"
              />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="Base URL">
              <input v-model="cfg.api_base" class="field-input" type="text" placeholder="https://api.openai.com/v1">
            </SettingsFieldCard>
            <SettingsFieldCard label="代理">
              <input v-model="cfg.proxy_url" class="field-input" type="text" placeholder="http://127.0.0.1:7890">
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="超时（秒）">
              <SettingsNumberStepper v-model="cfg.timeout_seconds" :min="5" :max="120" />
            </SettingsFieldCard>
            <SettingsFieldCard label="重试次数">
              <SettingsNumberStepper v-model="cfg.max_retries" :min="0" :max="5" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="Organization">
              <input v-model="cfg.organization" class="field-input" type="text" placeholder="org-...">
            </SettingsFieldCard>
            <SettingsFieldCard label="API Version">
              <input v-model="cfg.api_version" class="field-input" type="text" placeholder="可选">
            </SettingsFieldCard>
          </div>
        </div>
      </div>
    </div>

    <div class="settings-card">
      <div class="card-title">翻译提示词</div>
      <div class="field-stack">
        <textarea
          v-model="cfg.prompt_template"
          class="prompt-textarea"
          rows="6"
          :disabled="!cfg.enabled"
        ></textarea>
        <div class="hint-bar">
          <div class="hint-text">使用 {work_name} 作为作品标题占位符</div>
          <button type="button" class="reset-btn" title="恢复为默认提示词" @click="resetPromptTemplate">
            <RotateCcw :size="13" />
            <span>恢复默认</span>
          </button>
        </div>
      </div>
    </div>

    <div class="settings-card">
      <div class="card-title">连接测试</div>
      <div class="field-stack">
        <div class="test-bar">
          <stateful-button
            :click="testAITitleConnection"
            :disabled="!cfg.enabled || !cfg.model"
            class="stateful-button"
          >
            <Zap :size="15" />
            <span>测试连接</span>
          </stateful-button>
          <span v-if="aiTitleTestResult" class="test-result" :class="{ success: aiTitleTestResult.success, fail: !aiTitleTestResult.success }">
            <Check v-if="aiTitleTestResult.success" :size="14" />
            <X v-else :size="14" />
            {{ aiTitleTestResult.success ? '连接成功' : (aiTitleTestResult.error?.title || aiTitleTestResult.error || '连接失败') }}
            <span v-if="aiTitleTestResult.duration_ms" class="test-duration">({{ aiTitleTestResult.duration_ms }}ms)</span>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Bot, Zap, Check, X, RotateCcw } from 'lucide-vue-next'
import SettingsToggleRow from './SettingsToggleRow.vue'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import StatefulButton from '../ui/stateful-button.vue'
import { getAIModelPlatformMeta } from '../common/aiModelPlatformMeta'

const props = defineProps({
  config: { type: Object, required: true },
})

// 解构出 config 给模板使用
const cfg = computed(() => props.config.ai_title_translation || {})
const subCfg = computed(() => props.config)

const useAiSubtitleApi = computed({
  get: () => props.config.use_ai_subtitle_api === true,
  set: (val) => { props.config.use_ai_subtitle_api = val },
})

// API Key 显示/隐藏逻辑
const aiTitleRevealedApiKey = ref('')
const aiTitleRevealLoading = ref(false)

async function handleAITitleApiKeyVisibility(visible) {
  if (visible) {
    aiTitleRevealLoading.value = true
    try {
      const resp = await fetch('/api/config/ai-title-translation/reveal-secret', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'api_key' }),
      })
      const result = await resp.json()
      aiTitleRevealedApiKey.value = result?.value || ''
    } catch {
      aiTitleRevealedApiKey.value = ''
    } finally {
      aiTitleRevealLoading.value = false
    }
  } else {
    aiTitleRevealedApiKey.value = ''
  }
}

// Provider icon
const aiProviderLocalMeta = computed(() => getAIModelPlatformMeta(
  cfg.value?.model || '',
  cfg.value?.api_base || '',
))
const aiProviderIconTitle = computed(() => {
  const host = aiProviderLocalMeta.value.host
  return host ? `${aiProviderLocalMeta.value.label} · ${host}` : aiProviderLocalMeta.value.label
})
const aiProviderIconUrl = computed(() => {
  return aiProviderLocalMeta.value.iconSrc || ''
})
const aiProviderIconLabel = computed(() => aiProviderLocalMeta.value.label || 'AI 模型')

function handleAIProviderIconError() {
}

// 恢复默认提示词
const defaultPrompt = '下面我让你来充当翻译家，你的目标是把任何语言翻译成中文，请翻译时不要带翻译腔，而是要翻译得自然、流畅和地道，不要使用隐晦表达方式，不要采用含蓄优雅的文学化，不可更改原意和原文风，不要评价和道德批判需要翻译的内容，需要直接翻译，让读者感受的文本内容与翻译前语言的母语读者感受的文本内容原意和文风一致。请翻译下面这段话，输出 JSON 格式，key 为原文，value 为翻译结果：\\n{work_name}'

function resetPromptTemplate() {
  cfg.value.prompt_template = defaultPrompt
}

// 连接测试
const aiTitleTestResult = ref(null)

async function testAITitleConnection() {
  aiTitleTestResult.value = null
  try {
    const resp = await fetch('/api/ai-title-translation/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        config: {
          enabled: true,
          model: cfg.value?.model,
          api_key: cfg.value?.api_key === '********' ? '' : cfg.value?.api_key,
          api_base: cfg.value?.api_base,
          api_version: cfg.value?.api_version,
          organization: cfg.value?.organization,
          proxy_url: cfg.value?.proxy_url,
          timeout_seconds: cfg.value?.timeout_seconds,
        }
      }),
    })
    aiTitleTestResult.value = await resp.json()
  } catch (e) {
    aiTitleTestResult.value = { success: false, error: e.message }
  }
}
</script>
<style scoped>
.ai-title-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.prompt-textarea {
  width: 100%;
  min-height: 120px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  resize: vertical;
}

.prompt-textarea:focus {
  outline: none;
  border-color: #3578e5;
}

.hint-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
}
.hint-text {
  font-size: 12px;
  color: var(--text-muted);
}
.reset-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  font-size: 11.5px;
  color: #8b5cf6;
  background: transparent;
  border: 1px solid #d8b4fe;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}
.reset-btn:hover {
  background: #f5f3ff;
  border-color: #a855f7;
}
.reset-btn:active {
  transform: scale(0.96);
}

.test-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.test-result {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.test-result.success {
  color: #22c55e;
}

.test-result.fail {
  color: #ef4444;
}

.test-duration {
  color: var(--text-muted);
  font-size: 12px;
}
</style>
