<template>
  <div
    class="fixed inset-0 z-[4000] flex items-center justify-center p-4 bg-black/30 backdrop-blur-[2px]"
    @click="handleOverlayClick"
  >
    <div
      class="sp-shell relative w-full max-w-[420px]"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      @click.stop
    >
      <!-- Lottie 动画 (success/danger) -->
      <div v-if="usesLottieTone" class="flex justify-center mb-3">
        <DotLottieVue
          :key="props.prompt?.id || options.tone"
          class="w-16 h-16 pointer-events-none"
          :src="options.tone === 'success' ? successConfettiAnimation : errorAnimation"
          :autoplay="true" :loop="false" :speed="1"
          :render-config="{ autoResize: true }"
        />
      </div>

      <div class="bg-white rounded-[14px] border border-slate-200/70 shadow-lg shadow-slate-900/10 overflow-hidden">
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <div class="flex items-center gap-2 min-w-0">
            <component :is="toneIcon" class="w-4 h-4 flex-shrink-0" :class="toneIconColorClass" />
            <h3 :id="titleId" class="text-[14px] font-semibold text-slate-900 truncate">{{ options.title || fallbackTitle }}</h3>
            <span v-if="options.badge" class="flex-shrink-0 inline-flex items-center px-2 py-0.5 rounded-[6px] text-[10px] font-semibold bg-slate-100 text-slate-600 border border-slate-200">{{ options.badge }}</span>
          </div>
          <button
            v-if="options.showClose"
            type="button"
            class="flex-shrink-0 ml-3 w-6 h-6 flex items-center justify-center rounded-[6px] text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-all duration-150"
            @click="emit('close')"
          >
            <X :size="15" />
          </button>
        </div>

        <!-- Body -->
        <div class="px-5 py-4 flex flex-col gap-3">
          <p v-if="options.description" :id="titleId + '-desc'" class="text-sm text-slate-500 leading-relaxed">{{ options.description }}</p>

          <div v-if="options.message && options.html" class="text-sm text-slate-600 leading-relaxed whitespace-normal break-words" v-html="options.message" />
          <div v-else-if="options.message" class="text-sm text-slate-600 leading-relaxed whitespace-pre-line break-words">{{ options.message }}</div>

          <div v-if="options.currentValue" class="flex flex-col gap-1 px-3 py-2 rounded-[8px] bg-slate-50 border border-slate-200">
            <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">{{ options.currentLabel || '当前项' }}</span>
            <span class="text-sm text-slate-800 break-words leading-snug">{{ options.currentValue }}</span>
          </div>

          <div v-if="options.details?.length" class="flex flex-col gap-2">
            <div
              v-for="detail in options.details"
              :key="`${detail.label}-${detail.value}`"
              class="flex flex-col gap-1 px-3 py-2 rounded-[8px] bg-slate-50 border border-slate-200"
            >
              <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">{{ detail.label || '信息' }}</span>
              <span class="text-sm text-slate-800 break-words leading-snug">{{ detail.value || '-' }}</span>
            </div>
          </div>

          <div v-if="options.mode === 'prompt'" class="flex flex-col gap-1.5">
            <textarea
              v-if="options.inputType === 'textarea'"
              ref="inputRef"
              v-model="draftValue"
              class="w-full min-h-[100px] px-3 py-2 rounded-[8px] bg-slate-50 border border-slate-200 text-slate-800 placeholder-slate-400 text-sm outline-none transition-all duration-150 focus:bg-white focus:border-slate-300 focus:ring-2 focus:ring-slate-200 resize-y"
              :placeholder="options.placeholder"
              rows="4"
              @keydown.stop
            />
            <input
              v-else
              ref="inputRef"
              v-model="draftValue"
              class="w-full h-9 px-3 rounded-[8px] bg-slate-50 border border-slate-200 text-slate-800 placeholder-slate-400 text-sm outline-none transition-all duration-150 focus:bg-white focus:border-slate-300 focus:ring-2 focus:ring-slate-200"
              :type="normalizedInputType"
              :placeholder="options.placeholder"
              @keydown.enter.prevent="handleConfirm"
              @keydown.stop
            />
            <p v-if="validationMessage" class="text-[12px] text-red-600 leading-normal">{{ validationMessage }}</p>
          </div>
        </div>

        <!-- Divider + Actions -->
        <div class="flex items-center justify-end gap-2 px-4 py-3 border-t border-slate-100 bg-white">
          <button
            v-if="options.mode !== 'alert'"
            type="button"
            class="px-4 py-1.5 text-sm text-slate-600 hover:text-slate-900 rounded-[6px] hover:bg-slate-100 transition-all duration-150 font-medium"
            @click="emit('cancel')"
          >
            {{ options.cancelText }}
          </button>
          <button
            type="button"
            class="inline-flex items-center justify-center px-4 py-1.5 rounded-[6px] text-sm font-semibold text-white transition-all duration-150 hover:opacity-90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
            :class="confirmBtnClass"
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
const titleId = computed(() => `${props.prompt?.id || 'sp'}-title`)
const descriptionId = computed(() => `${props.prompt?.id || 'sp'}-desc`)
const draftValue = ref('')
const usesLottieTone = computed(() => options.value.tone === 'success')

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

const toneIconColorClass = computed(() => {
  const t = options.value.tone
  if (t === 'success') return 'text-emerald-500'
  if (t === 'warning') return 'text-amber-500'
  if (t === 'danger') return 'text-red-500'
  return 'text-blue-500'
})

const confirmBtnClass = computed(() => {
  const t = options.value.tone
  if (t === 'success') return 'bg-emerald-600 hover:bg-emerald-700'
  if (t === 'warning') return 'bg-amber-500 hover:bg-amber-600'
  if (t === 'danger') return 'bg-red-600 hover:bg-red-700'
  return 'bg-slate-900 hover:bg-slate-700'
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
.system-prompt-fade-leave-active .sp-shell { transition: transform 0.24s ease, opacity 0.24s ease, filter 0.24s ease; }
.system-prompt-fade-enter-from,
.system-prompt-fade-leave-to { opacity: 0; }
.system-prompt-fade-enter-from .sp-shell,
.system-prompt-fade-leave-to .sp-shell { transform: translateY(6px) scale(0.985); opacity: 0; filter: blur(1px); }
</style>
