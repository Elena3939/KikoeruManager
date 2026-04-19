<template>
  <div class="system-prompt-overlay" @click="handleOverlayClick">
    <div
      class="system-prompt-shell"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      :aria-describedby="descriptionId"
      @click.stop
    >
      <button
        v-if="options.showClose"
        type="button"
        class="system-prompt-close"
        aria-label="关闭"
        @click="emit('close')"
      >
        <X :size="18" />
      </button>

      <div class="system-prompt-panel">
        <div class="system-prompt-head">
          <div class="system-prompt-icon" :class="`is-${options.tone}`">
            <DotLottieVue
              v-if="options.tone === 'success'"
              :key="props.prompt?.id || 'system-prompt-success'"
              class="system-prompt-state-lottie"
              :src="successConfettiAnimation"
              :autoplay="true"
              :loop="false"
              :speed="1"
              :render-config="{ autoResize: true }"
            />
            <DotLottieVue
              v-else-if="options.tone === 'danger'"
              :key="props.prompt?.id || 'system-prompt-danger'"
              class="system-prompt-state-lottie"
              :src="errorAnimation"
              :autoplay="true"
              :loop="false"
              :speed="1"
              :render-config="{ autoResize: true }"
            />
            <component v-else :is="toneIcon" :size="20" />
          </div>
          <div class="system-prompt-copy">
            <div class="system-prompt-title-row">
              <h3 :id="titleId" class="system-prompt-title">{{ options.title || fallbackTitle }}</h3>
              <span v-if="options.badge" class="system-prompt-badge">{{ options.badge }}</span>
            </div>
            <p v-if="options.description" :id="descriptionId" class="system-prompt-description">
              {{ options.description }}
            </p>
          </div>
        </div>

        <div class="system-prompt-body">
          <div
            v-if="options.message && options.html"
            class="system-prompt-message is-html"
            v-html="options.message"
          ></div>
          <div v-else-if="options.message" class="system-prompt-message">
            {{ options.message }}
          </div>

          <div v-if="options.currentValue" class="system-prompt-current">
            <span class="system-prompt-current-label">{{ options.currentLabel || '当前项' }}</span>
            <span class="system-prompt-current-value">{{ options.currentValue }}</span>
          </div>

          <div v-if="options.details.length" class="system-prompt-details">
            <div
              v-for="detail in options.details"
              :key="`${detail.label}-${detail.value}`"
              class="system-prompt-detail-item"
            >
              <span class="system-prompt-detail-label">{{ detail.label || '信息' }}</span>
              <span class="system-prompt-detail-value">{{ detail.value || '-' }}</span>
            </div>
          </div>

          <div v-if="options.mode === 'prompt'" class="system-prompt-input-wrap">
            <textarea
              v-if="options.inputType === 'textarea'"
              ref="inputRef"
              v-model="draftValue"
              class="system-prompt-input is-textarea"
              :placeholder="options.placeholder"
              rows="5"
              @keydown.stop
            ></textarea>
            <input
              v-else
              ref="inputRef"
              v-model="draftValue"
              class="system-prompt-input"
              :type="normalizedInputType"
              :placeholder="options.placeholder"
              @keydown.enter.prevent="handleConfirm"
              @keydown.stop
            />
            <div v-if="validationMessage" class="system-prompt-validation">{{ validationMessage }}</div>
          </div>
        </div>

        <div class="system-prompt-actions">
          <button
            v-if="options.mode !== 'alert'"
            type="button"
            class="system-prompt-button is-secondary"
            @click="emit('cancel')"
          >
            {{ options.cancelText }}
          </button>
          <button
            type="button"
            class="system-prompt-button"
            :class="`is-${options.tone}`"
            :disabled="confirmDisabled"
            @click="handleConfirm"
          >
            {{ options.confirmLoading ? '处理中...' : options.confirmText }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import { CheckCircle2, CircleHelp, TriangleAlert, X } from 'lucide-vue-next'
import successConfettiAnimation from '../../assets/anime/success confetti.lottie'
import errorAnimation from '../../assets/anime/Error animation.lottie'

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
const titleId = computed(() => `${props.prompt?.id || 'system-prompt'}-title`)
const descriptionId = computed(() => `${props.prompt?.id || 'system-prompt'}-description`)
const draftValue = ref('')
const fallbackTitle = computed(() => {
  if (options.value.mode === 'alert') return '系统提示'
  if (options.value.mode === 'prompt') return '请输入'
  return '确认操作'
})
const toneIcon = computed(() => {
  if (options.value.tone === 'success') return CheckCircle2
  if (options.value.tone === 'warning' || options.value.tone === 'danger') return TriangleAlert
  return CircleHelp
})
const normalizedInputType = computed(() => {
  if (options.value.inputType === 'password') return 'password'
  return 'text'
})
const confirmDisabled = computed(() => Boolean(options.value.confirmLoading || options.value.confirmDisabled))

watch(
  options,
  value => {
    draftValue.value = value.modelValue || ''
    validationMessage.value = ''
    nextTick(() => {
      inputRef.value?.focus?.()
      inputRef.value?.select?.()
    })
  },
  { immediate: true }
)

onMounted(() => {
  nextTick(() => {
    inputRef.value?.focus?.()
    inputRef.value?.select?.()
  })
})

function handleOverlayClick() {
  if (options.value.closeOnClickModal === false) return
  emit('close')
}

function validatePromptValue() {
  if (options.value.mode !== 'prompt' || !options.value.validator) return true
  const result = options.value.validator(draftValue.value)
  if (result === true || result === undefined) {
    validationMessage.value = ''
    return true
  }
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
.system-prompt-state-lottie {
  width: 48px;
  height: 48px;
  pointer-events: none;
}
</style>
