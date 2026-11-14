<template>
  <section class="library-text-reader" aria-label="文本阅读器">
    <div class="text-reader-toolbar">
      <AppDropdown v-model="selectedEncoding" :options="TEXT_ENCODING_OPTIONS" :width="188" label="编码" :show-trigger-badge="false" />
      <span class="text-reader-detection" role="status">{{ detectionLabel }}</span>
      <AppDropdown v-model="font" :options="fontOptions" :width="154" label="字体" :show-trigger-badge="false" />
      <div class="text-reader-font-size">
        <button type="button" aria-label="缩小字号" :disabled="fontSize <= 14" @click="fontSize -= 1"><Minus :size="15" /></button>
        <span>{{ fontSize }}px</span>
        <button type="button" aria-label="放大字号" :disabled="fontSize >= 28" @click="fontSize += 1"><Plus :size="15" /></button>
      </div>
    </div>
    <div class="text-reader-scroll" ref="scrollRef" :aria-busy="loading">
      <div v-if="loading" class="app-loading-mask">正在读取文本…</div>
      <p v-else-if="error" class="text-reader-error" role="alert">{{ error }}</p>
      <pre v-else class="text-reader-content" :class="`text-reader-font-${font}`" :style="{ fontSize: `${fontSize}px` }">{{ content || '（空文本）' }}</pre>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { Minus, Plus } from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'
import { apiFetchOptions } from '../../api'
import { decodeTextBytes, detectTextEncoding, TEXT_ENCODING_OPTIONS } from '../../utils/libraryTextEncoding'

const props = defineProps({ src: { type: String, required: true }, fileKey: { type: String, required: true } })
const preferenceKey = 'kikoerumanager.reader.text'
function readPreferences () {
  try { return JSON.parse(localStorage.getItem(preferenceKey) || '{}') || {} } catch { return {} }
}
const saved = readPreferences()
const fontOptions = [{ value: 'sans', label: '清晰黑体' }, { value: 'serif', label: '阅读宋体' }, { value: 'mono', label: '等宽字体' }]
const font = ref(fontOptions.some(item => item.value === saved.font) ? saved.font : 'sans')
const fontSize = ref(Math.min(28, Math.max(14, Number(saved.fontSize) || 17)))
const selectedEncoding = ref('auto')
const bytes = shallowRef(null)
const detected = shallowRef(null)
const loading = ref(false)
const error = ref('')
const scrollRef = ref(null)
let request = null
const decoded = computed(() => {
  if (!bytes.value) return { text: '', error: '' }
  try {
    const encoding = selectedEncoding.value === 'auto' ? detected.value?.encoding : selectedEncoding.value
    if (!encoding) return { text: '', error: '未能识别文本编码，请手动选择编码' }
    return { text: decodeTextBytes(bytes.value, encoding), error: '' }
  } catch { return { text: '', error: '当前编码无法解码，请切换编码' } }
})
const content = computed(() => decoded.value.text)
const detectionLabel = computed(() => {
  const result = detected.value
  if (!result) return '可手动选择编码'
  const confidence = `${Math.round(result.confidence * 100)}%`
  return `识别：${result.encoding.toUpperCase()} · ${confidence}${result.confidence < 0.8 ? '（建议核对）' : ''}${selectedEncoding.value !== 'auto' ? ' · 手动编码已应用' : ''}`
})
watch(() => decoded.value.error, value => { error.value = value })
watch([font, fontSize, selectedEncoding], () => {
  const current = readPreferences()
  const encodings = Object.entries(current.encodings || {}).filter(([key]) => key !== props.fileKey).slice(-99)
  encodings.push([props.fileKey, selectedEncoding.value])
  try { localStorage.setItem(preferenceKey, JSON.stringify({ font: font.value, fontSize: fontSize.value, encodings: Object.fromEntries(encodings) })) } catch { /* 存储不可用时仍可阅读。 */ }
})
watch([() => props.src, () => props.fileKey], async ([src]) => {
  request?.abort()
  const controller = new AbortController()
  request = controller
  bytes.value = null
  detected.value = null
  error.value = ''
  loading.value = true
  const encoding = readPreferences().encodings?.[props.fileKey]
  selectedEncoding.value = TEXT_ENCODING_OPTIONS.some(item => item.value === encoding) ? encoding : 'auto'
  if (scrollRef.value) scrollRef.value.scrollTop = 0
  try {
    const response = await fetch(src, apiFetchOptions({ signal: controller.signal }))
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}))
      throw new Error(detail.detail || `文本加载失败（HTTP ${response.status}）`)
    }
    const buffer = new Uint8Array(await response.arrayBuffer())
    if (controller.signal.aborted) return
    try { detected.value = detectTextEncoding(buffer) } catch { /* 保留原始字节，允许手动解码。 */ }
    bytes.value = buffer
  } catch (cause) {
    if (!controller.signal.aborted) error.value = cause.message || '文本加载失败'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>

<style scoped>
.library-text-reader { display: flex; flex-direction: column; width: 100%; height: 100%; min-height: 0; color: #263244; background: #faf9f6; user-select: text; }
.text-reader-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 10px 18px; border-bottom: 1px solid #e4e5e7; background: #fff; user-select: none; }
.text-reader-detection { flex: 1; min-width: 160px; font-size: 12px; color: #64748b; }
.text-reader-font-size { display: flex; align-items: center; gap: 8px; font-size: 12px; font-variant-numeric: tabular-nums; }
.text-reader-font-size button { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; color: inherit; transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.text-reader-font-size button:hover:not(:disabled) { transform: translateY(-2px) scale(1.02); background: #e8edf3; }
.text-reader-font-size button:hover svg { transform: rotate(5deg); }
.text-reader-font-size button:active:not(:disabled) { transform: scale(0.96); }
.text-reader-font-size button:disabled { opacity: .35; }
.library-text-reader :deep(:is(button, input, [tabindex]):is(:focus, :focus-visible)) { outline: none; box-shadow: none; }
.text-reader-scroll { position: relative; min-height: 0; flex: 1; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
.text-reader-content { box-sizing: border-box; max-width: 88ch; min-height: 100%; margin: 0 auto; padding: 30px 40px 64px; white-space: pre-wrap; overflow-wrap: anywhere; tab-size: 4; line-height: 1.95; letter-spacing: .025em; font-weight: 400; text-rendering: optimizeLegibility; -webkit-font-smoothing: antialiased; }
.text-reader-font-sans { font-family: 'Segoe UI', 'Microsoft YaHei', 'Yu Gothic UI', 'Meiryo', 'PingFang SC', sans-serif; }
.text-reader-font-serif { font-family: 'Noto Serif CJK SC', 'Source Han Serif SC', 'Songti SC', 'SimSun', 'Yu Mincho', serif; }
.text-reader-font-mono { font-family: 'Cascadia Code', Consolas, 'Microsoft YaHei', 'Meiryo', monospace; letter-spacing: 0; }
.text-reader-error { padding: 28px; color: #b45309; }
:global(html.kikoerumanager-dark .library-text-reader) { background: var(--km-dark-bg, #141922); color: var(--km-dark-text, #e0e6ef); }
:global(html.kikoerumanager-dark .text-reader-toolbar) { background: var(--km-dark-surface, #1b2230); border-color: #334155; }
:global(html.kikoerumanager-dark .text-reader-detection) { color: #a8b6c9; }
:global(html.kikoerumanager-dark .text-reader-font-size button:hover:not(:disabled)) { background: #334155; }
@media (max-width: 640px) { .text-reader-toolbar { padding: 8px; gap: 6px; } .text-reader-detection { order: 4; flex-basis: 100%; } .text-reader-content { padding: 18px 18px 40px; line-height: 1.85; } }
</style>
