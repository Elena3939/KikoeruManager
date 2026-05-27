<template>
  <Teleport to="body">
    <Transition name="brp-fade">
      <div
        v-if="visible"
        class="brp-overlay fixed inset-0 z-[4000] flex items-center justify-center p-6 max-[820px]:p-3"
        @click.self="handleCancel"
      >
        <div class="brp-window relative w-full max-w-[960px] max-h-[calc(100vh-3rem)] flex flex-col rounded-3xl overflow-hidden" @mousedown.stop>
          <!-- Header -->
          <header class="brp-header flex items-start justify-between gap-4 px-7 pt-6 pb-4 flex-none">
            <div class="min-w-0 flex-1">
              <h1 class="brp-title text-2xl font-bold tracking-tight">批量重试</h1>
              <p class="brp-subtitle text-sm m-0 mt-1.5">选中的失败压缩包，可以为每个包单独指定密码和文件名编码</p>
            </div>
            <button
              type="button"
              class="brp-close inline-flex size-9 items-center justify-center rounded-full flex-shrink-0"
              title="关闭"
              @click="handleCancel"
            >
              <X :size="18" :stroke-width="2" />
            </button>
          </header>

          <!-- Pill rail：状态总览 -->
          <div class="brp-tabs px-7 pt-1 pb-3 flex items-center flex-wrap gap-1.5 flex-none">
            <span class="brp-pill"><b>{{ conflicts.length }}</b> 项</span>
            <span class="brp-pill" :class="specifiedCount ? 'is-active' : ''">已指定密码 <b>{{ specifiedCount }}</b> / {{ conflicts.length }}</span>
            <span v-if="customEncodingCount" class="brp-pill is-amber">手动编码 <b>{{ customEncodingCount }}</b> 项</span>
          </div>

          <!-- Body：直接平铺 grid 行，无嵌套卡片 -->
          <div class="brp-body flex-1 min-h-0 overflow-y-auto px-7 py-2">
            <!-- Grid head -->
            <div class="brp-grid brp-list-head text-xs font-semibold uppercase tracking-[0.12em]">
              <span>问题项</span>
              <span>密码</span>
              <span>文件名编码</span>
            </div>
            <!-- Grid rows -->
            <div
              v-for="item in items"
              :key="item.id"
              class="brp-grid brp-row"
            >
              <div class="flex min-w-0 items-center gap-2.5">
                <span class="brp-row-icon" :class="item.hasGarbled ? 'is-warn' : 'is-normal'">
                  <AlertTriangle v-if="item.hasGarbled" :size="15" :stroke-width="2.2" />
                  <FileArchive v-else :size="15" :stroke-width="2" />
                </span>
                <div class="min-w-0 flex-1">
                  <div class="brp-row-label truncate">{{ item.label }}</div>
                  <div class="brp-row-meta truncate">{{ item.conflictType || '问题作品' }}</div>
                </div>
              </div>

              <label class="brp-input-shell flex min-w-0 items-center gap-2">
                <KeyRound :size="14" :stroke-width="2.2" class="flex-shrink-0 text-slate-400" />
                <input
                  v-model="item.password"
                  type="text"
                  class="brp-input"
                  placeholder="可留空"
                  autocomplete="off"
                  @keydown.enter.prevent="handleConfirm"
                  @keydown.stop
                >
              </label>

              <AppDropdown
                v-model="item.filenameEncoding"
                :options="resolvedEncodingOptions"
                :width="180"
                :menu-min-width="260"
                :show-trigger-badge="false"
              />
            </div>
          </div>

          <!-- Footer -->
          <footer class="brp-footer flex items-center justify-between gap-4 px-7 py-5 flex-none">
            <p class="brp-summary text-sm m-0">
              {{ specifiedCount ? `将按已指定的 ${specifiedCount} 个密码逐个重试` : '未指定密码，将走密码库 / RJ 推导 / 默认密码' }}
            </p>
            <div class="flex items-center gap-3">
              <button
                type="button"
                class="brp-btn-secondary px-6 h-10 rounded-xl font-bold"
                @click="handleCancel"
              >取消</button>
              <button
                type="button"
                class="brp-btn-primary px-7 h-10 rounded-xl font-bold text-white"
                @click="handleConfirm"
              >开始批量重试</button>
            </div>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { AlertTriangle, FileArchive, KeyRound, X } from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  conflicts: { type: Array, default: () => [] },
  encodingOptions: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const fallbackEncodingOptions = [
  { value: 'auto', label: '自动识别', description: '每个压缩包独立嗅探编码' },
  { value: 'shift_jis', label: 'Shift_JIS / CP932', description: '日文 ZIP 常见编码' },
  { value: 'gbk', label: 'GBK / CP936', description: '中文 Windows 压缩包' },
  { value: 'big5', label: 'Big5 / CP950', description: '繁体中文压缩包' },
  { value: 'euc_kr', label: 'EUC-KR / CP949', description: '韩文压缩包' },
  { value: 'utf-8', label: 'UTF-8', description: '标准 UTF-8 文件名' },
]

const visible = computed(() => props.modelValue)
const resolvedEncodingOptions = computed(() => props.encodingOptions.length ? props.encodingOptions : fallbackEncodingOptions)

const items = ref([])

watch(
  () => props.conflicts,
  (list) => {
    items.value = list.map(c => ({
      id: c.id,
      label: c.rjcode || c.new_metadata?.work_name || c.new_path || '未识别问题项',
      conflictType: conflictTypeLabel(c.conflict_type),
      password: '',
      filenameEncoding: normalizeInitialEncoding(c),
      hasGarbled: hasGarbledMeta(c),
    }))
  },
  { immediate: true }
)

const specifiedCount = computed(() => items.value.filter(i => i.password.trim()).length)
const customEncodingCount = computed(() => items.value.filter(i => String(i.filenameEncoding || '').trim() && i.filenameEncoding !== 'auto').length)

function normalizeInitialEncoding(conflict) {
  const metadata = conflict?.new_metadata || {}
  const raw = String(metadata.manual_retry_filename_encoding || metadata.filename_encoding || '').trim()
  const allowed = new Set(resolvedEncodingOptions.value.map(item => item.value))
  return allowed.has(raw) ? raw : 'auto'
}

function hasGarbledMeta(conflict) {
  const metadata = conflict?.new_metadata || {}
  if (metadata.extract_failure_reason === 'garbled_filename') return true
  if (metadata.garbled_filename_sample) return true
  if (Array.isArray(metadata.garbled_filename_top_samples) && metadata.garbled_filename_top_samples.length) return true
  return false
}

function conflictTypeLabel(type) {
  return {
    EXTRACT_FAILED: '解压失败',
    PROCESS_FAILED: '处理失败',
    DUPLICATE: '完全重复',
    LANGUAGE_VARIANT: '多语言版本',
    MULTIPLE_VERSIONS: '多版本冲突',
    LINKED_WORK: '关联作品',
  }[type] || type || ''
}

function handleConfirm() {
  emit('confirm', items.value.map(i => ({
    conflictId: i.id,
    password: i.password.trim(),
    filenameEncoding: String(i.filenameEncoding || 'auto').trim() || 'auto',
  })))
  emit('update:modelValue', false)
}

function handleCancel() {
  emit('cancel')
  emit('update:modelValue', false)
}
</script>

<style scoped>
/* ============================================================
   BatchRetryPasswordDialog 玻璃壳风格
   ----------------------------------------------------------------
   单层半透白 backdrop-blur shell + 直接平铺 grid 行（无嵌套卡片）+
   主操作 #111827 深色实心 / 次操作半透灰，对齐社团补全下载预览。
============================================================ */

.brp-fade-enter-active,
.brp-fade-leave-active { transition: opacity 0.22s ease; }
.brp-fade-enter-active .brp-window,
.brp-fade-leave-active .brp-window {
  transition: transform 0.26s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease, filter 0.22s ease;
}
.brp-fade-enter-from,
.brp-fade-leave-to { opacity: 0; }
.brp-fade-enter-from .brp-window,
.brp-fade-leave-to .brp-window {
  transform: translateY(8px) scale(0.97);
  opacity: 0;
  filter: blur(1px);
}

/* Overlay：只承载点击关闭，不压暗、不虚化背景 */
.brp-overlay {
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

/* Shell：对齐社团补全预览的白色毛玻璃壳 */
.brp-window {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(28px) saturate(135%);
  -webkit-backdrop-filter: blur(28px) saturate(135%);
  border: 1px solid rgba(255, 255, 255, 0.42);
  box-shadow:
    0 28px 70px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

/* Header */
.brp-header {
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
}

.brp-title {
  margin: 0;
  color: #0f172a;
  letter-spacing: -0.02em;
  line-height: 1.15;
}

.brp-subtitle {
  color: #64748b;
  line-height: 1.5;
}

.brp-close {
  border: 0;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.brp-close:hover {
  background: rgba(241, 245, 249, 0.72);
  color: #334155;
}

.brp-close svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.brp-close:hover svg {
  transform: rotate(90deg);
}

/* Pill rail */
.brp-tabs {
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
}

.brp-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 12px;
  border: 1px solid rgba(226, 232, 240, 0.78);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.55);
  color: #475569;
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: 0.02em;
  white-space: nowrap;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.brp-pill b {
  color: #0f172a;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.brp-pill.is-active {
  border-color: rgba(45, 212, 191, 0.5);
  background: rgba(236, 253, 245, 0.85);
  color: #0f766e;
}

.brp-pill.is-active b { color: #0f766e; }

.brp-pill.is-amber {
  border-color: rgba(252, 211, 77, 0.62);
  background: rgba(254, 243, 199, 0.85);
  color: #92400e;
}

.brp-pill.is-amber b { color: #92400e; }

/* Body grid：直接平铺，无内部卡片，无独立背景 */
.brp-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 240px) 200px;
  column-gap: 12px;
  align-items: center;
}

.brp-list-head {
  padding: 10px 4px 8px;
  color: #94a3b8;
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
}

.brp-row {
  min-height: 56px;
  padding: 10px 4px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
}

.brp-row:last-of-type {
  border-bottom: 0;
}

.brp-row-icon {
  display: inline-flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(255, 255, 255, 0.55);
  color: #475569;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.brp-row-icon.is-warn {
  border-color: rgba(252, 211, 77, 0.6);
  background: rgba(254, 243, 199, 0.65);
  color: #b45309;
}

.brp-row-label {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.brp-row-meta {
  margin-top: 1px;
  font-size: 11px;
  color: #94a3b8;
}

/* Input：半透白 backdrop-blur，无独立卡片包裹 */
.brp-input-shell {
  height: 38px;
  padding: 0 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.brp-input-shell:focus-within {
  background: rgba(255, 255, 255, 0.92);
  border-color: rgba(15, 23, 42, 0.22);
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.06);
}

.brp-input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: none;
  background: transparent;
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
}

.brp-input::placeholder {
  color: #94a3b8;
  font-weight: 500;
}

/* Footer */
.brp-footer {
  border-top: 1px solid rgba(15, 23, 42, 0.06);
}

.brp-summary {
  color: #64748b;
}

/* Buttons：与社团预览 primary-cta / secondary-cta 同款 */
.brp-btn-primary,
.brp-btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 0;
  cursor: pointer;
  letter-spacing: 0.01em;
  white-space: nowrap;
  font-size: 13px;
  transition: background-color 0.18s ease, color 0.18s ease, box-shadow 0.18s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.brp-btn-secondary {
  background: rgba(17, 24, 39, 0.06);
  color: #334155;
}

.brp-btn-secondary:hover {
  background: rgba(15, 23, 42, 0.1);
  color: #0f172a;
  transform: translateY(-2px) scale(1.02);
}

.brp-btn-primary {
  background: #111827;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.16);
}

.brp-btn-primary:hover {
  background: #0f172a;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22);
  transform: translateY(-2px) scale(1.02);
}

.brp-btn-primary:active,
.brp-btn-secondary:active { transform: scale(0.96); }

@media (max-width: 820px) {
  .brp-grid {
    grid-template-columns: minmax(0, 1fr);
    row-gap: 10px;
  }
  .brp-list-head { display: none; }
  .brp-row {
    align-items: stretch;
    padding: 12px 4px;
  }
  .brp-footer {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  .brp-footer .flex {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
