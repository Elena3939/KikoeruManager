<template>
  <div
    class="system-prompt-overlay fixed inset-0 z-[4000] flex items-center justify-center p-4"
    @click="handleOverlayClick"
  >
    <div
      class="sp-shell relative w-full"
      :style="{ maxWidth: `${dialogWidth}px` }"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      @click.stop
    >
      <div class="sp-card" :class="[toneClass, { 'has-body': hasBody, 'is-confirm-focusable': isConfirmDialog }]">
        <header class="sp-header">
          <div class="sp-header-main">
            <div class="sp-title-row">
              <h3 :id="titleId" class="sp-title">{{ options.title || fallbackTitle }}</h3>
              <span v-if="options.badge" class="sp-badge">{{ options.badge }}</span>
            </div>
            <p
              v-if="headerDescription"
              :id="descriptionId"
              class="sp-description is-preline"
            >
              {{ headerDescription }}
            </p>
          </div>
          <button
            v-if="options.showClose"
            type="button"
            class="sp-close"
            title="关闭"
            @click="emit('close')"
          >
            <X :size="18" :stroke-width="2" />
          </button>
        </header>

        <section v-if="hasBody" class="sp-body">
          <div v-if="options.message && options.html" class="sp-message" v-html="options.message" />
          <div v-else-if="options.message" class="sp-message">
            <template
              v-for="line in messageLines"
              :key="line.key"
            >
              <span
                v-if="line.text"
                class="sp-message-line"
                :class="`is-${line.variant}`"
              >
                {{ line.text }}
              </span>
              <span v-else class="sp-message-gap" aria-hidden="true" />
            </template>
          </div>

          <div v-if="options.currentValue" class="sp-info-block">
            <span class="sp-info-label">{{ options.currentLabel || '当前项' }}</span>
            <span class="sp-info-value">{{ options.currentValue }}</span>
          </div>

          <div v-if="options.details?.length" class="sp-details">
            <div
              v-for="detail in options.details"
              :key="`${detail.label}-${detail.value}`"
              class="sp-info-block"
            >
              <span class="sp-info-label">{{ detail.label || '信息' }}</span>
              <span class="sp-info-value">{{ detail.value || '-' }}</span>
            </div>
          </div>

          <div v-if="options.mode === 'prompt'" class="sp-field">
            <textarea
              v-if="options.inputType === 'textarea'"
              ref="inputRef"
              v-model="draftValue"
              class="sp-input sp-textarea"
              style="resize: vertical; will-change: auto;"
              :placeholder="options.placeholder"
              rows="5"
              @keydown.stop
            />
            <input
              v-else
              ref="inputRef"
              v-model="draftValue"
              class="sp-input"
              :type="normalizedInputType"
              :placeholder="options.placeholder"
              @keydown.enter.prevent="handleConfirm"
              @keydown.stop
            />
            <p v-if="validationMessage" class="sp-validation">{{ validationMessage }}</p>
          </div>
        </section>

        <footer class="sp-footer">
          <button
            v-if="options.mode !== 'alert'"
            type="button"
            class="sp-btn sp-btn-secondary"
            @click="emit('cancel')"
          >
            {{ options.cancelText }}
          </button>
          <button
            type="button"
            class="sp-btn sp-btn-primary"
            :class="confirmBtnClass"
            :disabled="confirmDisabled"
            @click="handleConfirm"
          >
            {{ options.confirmLoading ? '处理中...' : options.confirmText }}
          </button>
        </footer>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = defineProps({
  prompt: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['confirm', 'cancel', 'close'])

const inputRef = ref(null)
const validationMessage = ref('')
const options = computed(() => props.prompt?.options || {})
const titleId = computed(() => `${props.prompt?.id || 'sp'}-title`)
const descriptionId = computed(() => `${props.prompt?.id || 'sp'}-desc`)
const draftValue = ref('')
const dialogWidth = computed(() => {
  const width = Number(options.value.width || 580)
  return Math.max(420, Math.min(width, 960))
})

const fallbackTitle = computed(() => {
  if (options.value.mode === 'alert') return '系统提示'
  if (options.value.mode === 'prompt') return '请输入'
  return '确认操作'
})

const toneClass = computed(() => `is-${options.value.tone || 'info'}`)
const isConfirmDialog = computed(() => options.value.mode === 'confirm')
const headerDescription = computed(() => {
  if (options.value.description) return options.value.description
  return ''
})
function getMessageLineVariant(text) {
  if (/^(名称|大小|总大小)\s*[:：]/.test(text)) return 'meta'
  if (/不可恢复/.test(text)) return 'danger'
  if (/^(确定|确认|是否)/.test(text)) return 'lead'
  return 'normal'
}

const messageLines = computed(() => {
  if (!options.value.message || options.value.html) return []
  return String(options.value.message)
    .split(/\r?\n/)
    .flatMap((line, index) => {
      const text = line.trim()
      if (!text) {
        return [{ key: `${index}-blank`, text, variant: 'normal' }]
      }

      const dangerSuffix = text.match(/^(.*?)(此操作不可恢复[。.!！]*)$/)
      if (dangerSuffix?.[1]?.trim()) {
        const leadText = dangerSuffix[1].trim()
        const dangerText = dangerSuffix[2].trim()
        return [
          { key: `${index}-lead`, text: leadText, variant: getMessageLineVariant(leadText) },
          { key: `${index}-danger`, text: dangerText, variant: 'danger' }
        ]
      }

      return {
        key: `${index}-${text || 'blank'}`,
        text,
        variant: getMessageLineVariant(text)
      }
    })
})
const hasBody = computed(() => {
  return Boolean(
    (options.value.message && options.value.html) ||
      options.value.message ||
      options.value.currentValue ||
      options.value.details?.length ||
      options.value.mode === 'prompt'
  )
})

const confirmBtnClass = computed(() => {
  const t = options.value.tone
  if (t === 'success') return 'is-success'
  if (t === 'warning') return 'is-warning'
  if (t === 'danger') return 'is-danger'
  return 'is-info'
})

const normalizedInputType = computed(() => options.value.inputType === 'password' ? 'password' : 'text')
const confirmDisabled = computed(() => Boolean(options.value.confirmLoading || options.value.confirmDisabled))

watch(options, value => {
  draftValue.value = value.modelValue || ''
  validationMessage.value = ''
  nextTick(() => { inputRef.value?.focus?.(); inputRef.value?.select?.() })
}, { immediate: true })

onMounted(() => {
  nextTick(() => { inputRef.value?.focus?.(); inputRef.value?.select?.() })
})

function handleOverlayClick() {
  if (options.value.closeOnClickModal === false) return
  emit('close')
}

function validatePromptValue() {
  if (options.value.mode !== 'prompt' || !options.value.validator) return true
  const result = options.value.validator(draftValue.value)
  if (result === true || result === undefined) { validationMessage.value = ''; return true }
  validationMessage.value = typeof result === 'string' && result.trim() ? result : '输入内容不符合要求'
  return false
}

function handleConfirm() {
  if (confirmDisabled.value) return
  if (!validatePromptValue()) return
  emit('confirm', options.value.mode === 'prompt' ? draftValue.value : true)
}
</script>

<style scoped>
.system-prompt-fade-enter-active,
.system-prompt-fade-leave-active { transition: opacity 0.22s ease; }
.system-prompt-fade-enter-active .sp-shell,
.system-prompt-fade-leave-active .sp-shell {
  transition: transform 0.24s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.24s ease;
}
.system-prompt-fade-enter-from,
.system-prompt-fade-leave-to { opacity: 0; }
.system-prompt-fade-enter-from .sp-shell,
.system-prompt-fade-leave-to .sp-shell { transform: translateY(6px) scale(0.985); opacity: 0; }

.system-prompt-overlay {
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

.sp-card {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 22px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.84), rgba(255, 255, 255, 0.72)),
    rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(20px) saturate(126%);
  -webkit-backdrop-filter: blur(20px) saturate(126%);
  box-shadow:
    0 28px 76px rgba(15, 23, 42, 0.16),
    0 10px 26px rgba(15, 23, 42, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.68);
}

.sp-card::before {
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  content: '';
  background: linear-gradient(120deg, rgba(255, 255, 255, 0.34), rgba(255, 255, 255, 0) 40%);
}

.sp-header,
.sp-body,
.sp-footer {
  position: relative;
  z-index: 1;
}

.sp-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 0;
  padding: 30px 40px 18px;
  background: transparent;
}

.sp-card.has-body .sp-header {
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.sp-header-main {
  min-width: 0;
  flex: 1;
}

.sp-title-row {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: 8px;
}

.sp-title {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: #0f172a;
  font-size: 24px;
  font-weight: 800;
  letter-spacing: 0;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sp-badge {
  display: inline-flex;
  flex: none;
  align-items: center;
  min-height: 22px;
  border: 1px solid rgba(203, 213, 225, 0.85);
  border-radius: 999px;
  background: #f8fafc;
  padding: 0 8px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}

.sp-close {
  display: inline-flex;
  flex: none;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.sp-close:hover {
  background: rgba(241, 245, 249, 0.72);
  color: #334155;
  transform: translateY(-2px) scale(1.02);
}

.sp-close:active {
  transform: scale(0.96);
}

.sp-card.is-confirm-focusable .sp-close:focus-visible {
  background: rgba(241, 245, 249, 0.88);
  color: #1e293b;
  outline: none;
  box-shadow:
    0 0 0 2px rgba(255, 255, 255, 0.72),
    0 0 0 4px rgba(245, 158, 11, 0.28);
}

.sp-card.is-confirm-focusable .sp-message {
  max-width: 100%;
  color: #475569;
}

.sp-close svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.sp-close:hover svg {
  transform: rotate(90deg);
}

.sp-body {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 12px;
  min-height: 92px;
  padding: 24px 40px 20px;
  background: transparent;
}

.sp-description,
.sp-message {
  margin: 0;
  color: #53657c;
  font-family:
    Inter,
    "SF Pro Text",
    "Segoe UI",
    "PingFang SC",
    "Microsoft YaHei",
    sans-serif;
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0;
  line-height: 1.85;
  overflow-wrap: anywhere;
  text-align: left;
}

.sp-description {
  margin-top: 6px;
}

.sp-description.is-preline,
.sp-message.is-preline {
  white-space: pre-line;
}

.sp-card.is-confirm-focusable .sp-message {
  max-width: 100%;
  color: #53657c;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.85;
  word-break: break-word;
}

.sp-message-line {
  display: block;
}

.sp-message-line.is-lead {
  color: #334155;
  font-weight: 700;
}

.sp-message-line.is-meta {
  color: #64748b;
  font-weight: 650;
}

.sp-message-line.is-danger {
  color: #be123c;
  font-weight: 800;
}

.sp-message-gap {
  display: block;
  height: 12px;
}

.sp-info-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.18);
  padding: 10px 12px;
  backdrop-filter: blur(10px) saturate(112%);
  -webkit-backdrop-filter: blur(10px) saturate(112%);
}

.sp-info-label {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  line-height: 1.2;
  text-transform: uppercase;
}

.sp-info-value {
  color: #334155;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.sp-details {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sp-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.sp-input {
  width: 100%;
  height: 42px;
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.62);
  padding: 0 12px;
  color: #1e293b;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.45;
  outline: none;
  transition: border-color 0.18s ease, background-color 0.18s ease;
}

.sp-textarea {
  min-height: 132px;
  padding: 10px 12px;
}

.sp-input::placeholder {
  color: #94a3b8;
}

.sp-input:focus {
  border-color: rgba(15, 23, 42, 0.16);
  background: rgba(255, 255, 255, 0.9);
}

.sp-validation {
  margin: 0;
  color: #dc2626;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.45;
}

.sp-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  border-top: 0;
  background: transparent;
  min-height: 64px;
  padding: 16px 40px 28px;
}

.sp-btn {
  display: inline-flex;
  min-width: 96px;
  height: 40px;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 12px;
  padding: 0 18px;
  color: inherit;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.01em;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 0.18s ease,
    border-color 0.18s ease,
    color 0.18s ease,
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.18s ease;
}

.sp-btn:hover {
  transform: translateY(-2px) scale(1.02);
}

.sp-btn:active {
  transform: scale(0.96);
}

.sp-btn:disabled {
  opacity: 0.52;
  cursor: not-allowed;
  transform: none;
}

.sp-card.is-confirm-focusable .sp-btn:focus-visible {
  outline: none;
  box-shadow:
    0 0 0 2px rgba(255, 255, 255, 0.76),
    0 0 0 4px rgba(245, 158, 11, 0.36),
    0 12px 24px rgba(15, 23, 42, 0.14);
}

.sp-btn-secondary {
  background: rgba(17, 24, 39, 0.06);
  color: #334155;
}

.sp-btn-secondary:hover {
  background: rgba(15, 23, 42, 0.1);
  color: #0f172a;
}

.sp-btn-primary {
  background: #111827;
  color: #ffffff;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.16);
}

.sp-btn-primary:hover {
  background: #0f172a;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22);
}

.sp-btn-primary.is-danger {
  background: #f10819;
}

.sp-btn-primary.is-danger:hover {
  background: #dc0817;
}

.sp-btn-primary.is-warning {
  background: #f59e0b;
}

.sp-btn-primary.is-warning:hover {
  background: #d97706;
}

.sp-btn-primary.is-success {
  background: #059669;
}

.sp-btn-primary.is-success:hover {
  background: #047857;
}

@media (max-width: 640px) {
  .system-prompt-overlay {
    align-items: flex-end;
    padding: 12px;
  }

  .sp-card {
    border-radius: 20px 20px 18px 18px;
  }

  .sp-header {
    padding: 24px 22px 16px;
  }

  .sp-title {
    font-size: 20px;
  }

  .sp-body {
    min-height: 84px;
    padding: 20px 22px 18px;
  }

  .sp-description,
  .sp-message {
    font-size: 13px;
  }

  .sp-footer {
    min-height: auto;
    padding: 2px 22px 22px;
  }

  .sp-btn {
    height: 40px;
    min-width: 92px;
    font-size: 13px;
  }
}

:global(html.kikoerumanager-dark .sp-card) {
  border-color: rgba(255, 255, 255, 0.12);
  background:
    linear-gradient(180deg, rgba(35, 36, 42, 0.72), rgba(14, 15, 18, 0.62)),
    rgba(13, 14, 18, 0.58);
  box-shadow:
    0 34px 90px rgba(0, 0, 0, 0.32),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(18px) saturate(112%);
  -webkit-backdrop-filter: blur(18px) saturate(112%);
}

:global(html.kikoerumanager-dark .sp-card::before) {
  display: none;
  background: none;
}

:global(html.kikoerumanager-dark .sp-header),
:global(html.kikoerumanager-dark .sp-body),
:global(html.kikoerumanager-dark .sp-footer) {
  border-color: rgba(255, 255, 255, 0.1);
  background: transparent;
}

:global(html.kikoerumanager-dark .sp-title) {
  color: var(--km-dark-text-strong);
}

:global(html.kikoerumanager-dark .sp-description),
:global(html.kikoerumanager-dark .sp-message),
:global(html.kikoerumanager-dark .sp-info-value) {
  color: var(--km-dark-text);
}

:global(html.kikoerumanager-dark .sp-card.is-danger .sp-message) {
  color: rgba(226, 232, 240, 0.78);
}

:global(html.kikoerumanager-dark .sp-card.is-danger .sp-message-line.is-lead) {
  color: #f8fafc;
  font-weight: 750;
}

:global(html.kikoerumanager-dark .sp-card.is-danger .sp-message-line.is-meta) {
  color: rgba(203, 213, 225, 0.78);
}

:global(html.kikoerumanager-dark .sp-card.is-danger .sp-message-line.is-danger) {
  color: #fecdd3;
}

:global(html.kikoerumanager-dark .sp-info-label) {
  color: var(--km-dark-text-muted);
}

:global(html.kikoerumanager-dark .sp-badge),
:global(html.kikoerumanager-dark .sp-info-block),
:global(html.kikoerumanager-dark .sp-input) {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(24, 26, 31, 0.46);
  color: var(--km-dark-text);
}

:global(html.kikoerumanager-dark .sp-input::placeholder) {
  color: var(--km-dark-text-subtle);
}

:global(html.kikoerumanager-dark .sp-input:focus) {
  border-color: var(--km-dark-border-strong);
  background: var(--km-dark-field);
}

:global(html.kikoerumanager-dark .sp-close) {
  color: var(--km-dark-text-muted);
}

:global(html.kikoerumanager-dark .sp-close:hover) {
  background: var(--km-dark-button-bg-hover);
  color: var(--km-dark-text-strong);
}

:global(html.kikoerumanager-dark .sp-card.is-confirm-focusable .sp-close:focus-visible) {
  background: var(--km-dark-button-bg-hover);
  color: var(--km-dark-text-strong);
  box-shadow:
    0 0 0 2px rgba(24, 26, 31, 0.86),
    0 0 0 4px rgba(245, 158, 11, 0.32);
}

:global(html.kikoerumanager-dark .sp-btn-secondary) {
  color: var(--km-dark-text);
}

:global(html.kikoerumanager-dark .sp-btn-secondary:hover) {
  background: var(--km-dark-button-bg-hover);
  color: var(--km-dark-text-strong);
}

:global(html.kikoerumanager-dark .sp-shell .sp-btn-primary) {
  border-color: rgba(255, 255, 255, 0.28) !important;
  background: var(--km-dark-primary-button-bg) !important;
  background-image: none !important;
  color: var(--km-dark-primary-button-text) !important;
}

:global(html.kikoerumanager-dark .sp-shell .sp-btn-primary:hover) {
  background: var(--km-dark-button-bg-hover) !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .sp-shell .sp-btn-primary.is-danger) {
  border-color: rgba(243, 162, 168, 0.34) !important;
  background: #8f1d2b !important;
  background-image: none !important;
  color: #ffe1e4 !important;
}

:global(html.kikoerumanager-dark .sp-shell .sp-btn-primary.is-danger:hover) {
  background: #a62433 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .sp-shell .sp-btn-primary.is-warning) {
  border-color: rgba(244, 206, 117, 0.34) !important;
  background: #8a5d10 !important;
  background-image: none !important;
  color: #fff1c2 !important;
}

:global(html.kikoerumanager-dark .sp-shell .sp-btn-primary.is-warning:hover) {
  background: #9c6a13 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .sp-shell .sp-btn-primary.is-success) {
  border-color: rgba(141, 223, 187, 0.34) !important;
  background: #176346 !important;
  background-image: none !important;
  color: #d9fbe8 !important;
}

:global(html.kikoerumanager-dark .sp-shell .sp-btn-primary.is-success:hover) {
  background: #1d7252 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .sp-card.is-confirm-focusable .sp-btn:focus-visible) {
  box-shadow:
    0 0 0 2px rgba(24, 26, 31, 0.9),
    0 0 0 4px rgba(245, 158, 11, 0.34),
    0 12px 24px rgba(0, 0, 0, 0.26);
}
</style>
