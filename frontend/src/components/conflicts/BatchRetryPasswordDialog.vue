<template>
  <Teleport to="body">
    <Transition name="brp-fade">
      <div
        v-if="visible"
        class="brp-overlay fixed inset-0 z-[4000] flex items-center justify-center p-4"
        @click.self="handleCancel"
      >
        <div class="brp-shell relative flex max-h-[calc(100vh-2rem)] w-full max-w-[920px] flex-col">
          <div class="brp-window relative flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-3xl">
            <header class="brp-header flex flex-none items-center justify-between gap-4 px-6 py-4">
              <div class="min-w-0 flex-1">
                <div class="brp-title-row">
                  <span class="brp-title-icon">
                    <RotateCcw :size="20" :stroke-width="2.1" />
                  </span>
                  <h3 class="m-0 truncate text-lg font-bold tracking-tight text-slate-900">批量重试</h3>
                  <span class="brp-badge">{{ conflicts.length }} 项</span>
                </div>
                <p class="mt-1 truncate text-sm text-slate-500">选中的失败压缩包</p>
              </div>
              <div class="brp-count-pill">密码 {{ specifiedCount }} / {{ conflicts.length }}</div>
              <button
                type="button"
                class="brp-close inline-flex size-10 flex-shrink-0 items-center justify-center rounded-full text-slate-400 hover:text-slate-700"
                @click="handleCancel"
              >
                <X :size="20" :stroke-width="2" />
              </button>
            </header>

            <div class="brp-body flex min-h-0 flex-1 flex-col px-6 pb-5">
              <div class="brp-toolbar flex items-center justify-between gap-3 border-b border-slate-200/70 py-3">
                <div class="flex min-w-0 items-center gap-2 text-[12px] font-semibold text-slate-500">
                  <FileArchive :size="15" class="text-slate-400" />
                  <span class="truncate">逐包编码</span>
                </div>
                <span v-if="customEncodingCount" class="brp-soft-pill">{{ customEncodingCount }} 项手动编码</span>
              </div>

              <section class="brp-list-panel mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl">
                <div class="brp-grid brp-list-head items-center gap-3 border-b border-slate-200/70 px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
                  <span>问题项</span>
                  <span>密码</span>
                  <span>文件名编码</span>
                </div>

                <div class="brp-list-scroll flex-1 overflow-auto px-4 py-2">
                  <div v-for="item in items" :key="item.id" class="brp-grid brp-row items-center gap-3 rounded-md px-3 py-2">
                    <div class="flex min-w-0 items-center gap-2">
                      <span class="brp-row-icon" :class="item.hasGarbled ? 'is-warn' : 'is-normal'">
                        <AlertTriangle v-if="item.hasGarbled" :size="15" :stroke-width="2.2" />
                        <FileArchive v-else :size="15" :stroke-width="2" />
                      </span>
                      <div class="min-w-0 flex-1">
                        <div class="truncate text-[13px] font-semibold text-slate-800">{{ item.label }}</div>
                        <div class="truncate text-[11px] text-slate-400">{{ item.conflictType || '问题作品' }}</div>
                      </div>
                    </div>

                    <label class="brp-input-shell flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2">
                      <KeyRound :size="14" class="flex-shrink-0 text-slate-400" />
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
              </section>

              <footer class="brp-footer flex flex-none items-center justify-end gap-2 border-t border-slate-200/70 pt-4">
                <button type="button" class="brp-action-card" @click="handleCancel">取消</button>
                <button type="button" class="brp-action-card brp-action-card-primary" @click="handleConfirm">
                  <RotateCcw :size="15" class="brp-action-icon" />
                  <span>开始批量重试</span>
                </button>
              </footer>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { AlertTriangle, FileArchive, KeyRound, RotateCcw, X } from 'lucide-vue-next'
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
.brp-fade-enter-active,
.brp-fade-leave-active { transition: opacity 0.22s ease; }
.brp-fade-enter-active .brp-shell,
.brp-fade-leave-active .brp-shell { transition: transform 0.24s ease, opacity 0.24s ease, filter 0.24s ease; }
.brp-fade-enter-from,
.brp-fade-leave-to { opacity: 0; }
.brp-fade-enter-from .brp-shell,
.brp-fade-leave-to .brp-shell { transform: translateY(6px) scale(0.985); opacity: 0; filter: blur(1px); }

.brp-overlay {
  background:
    radial-gradient(circle at 18% 16%, rgba(191, 219, 254, 0.26), transparent 28%),
    radial-gradient(circle at 82% 14%, rgba(186, 230, 253, 0.22), transparent 24%),
    radial-gradient(circle at 82% 82%, rgba(221, 239, 255, 0.2), transparent 26%),
    rgba(241, 245, 249, 0.34);
  backdrop-filter: blur(20px) saturate(130%);
  -webkit-backdrop-filter: blur(20px) saturate(130%);
}

.brp-window {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.58), rgba(255, 255, 255, 0.34)),
    radial-gradient(circle at top left, rgba(191, 219, 254, 0.18), transparent 34%),
    radial-gradient(circle at top right, rgba(186, 230, 253, 0.14), transparent 28%);
  border: 1px solid rgba(255, 255, 255, 0.42);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.56),
    0 28px 80px rgba(15, 23, 42, 0.14);
  backdrop-filter: blur(28px) saturate(155%);
  -webkit-backdrop-filter: blur(28px) saturate(155%);
}

.brp-window::before {
  position: absolute;
  inset: 0;
  pointer-events: none;
  content: '';
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.22), transparent 30%, rgba(255, 255, 255, 0.08) 65%, transparent 100%);
  opacity: 0.9;
}

.brp-header,
.brp-body {
  position: relative;
  z-index: 1;
}

.brp-header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.4);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.22), rgba(255, 255, 255, 0.06));
}

.brp-title-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.brp-title-icon {
  display: inline-flex;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  align-items: center;
  justify-content: center;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.58);
  background: rgba(255, 255, 255, 0.42);
  color: #334155;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.42),
    0 8px 22px rgba(15, 23, 42, 0.06);
}

.brp-badge,
.brp-count-pill,
.brp-soft-pill {
  flex: 0 0 auto;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.brp-badge {
  border: 1px solid rgba(255, 255, 255, 0.56);
  background: rgba(255, 255, 255, 0.46);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.38);
  padding: 3px 10px;
  color: #475569;
}

.brp-count-pill {
  border: 1px solid rgba(147, 197, 253, 0.56);
  background: rgba(239, 246, 255, 0.4);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.44),
    0 10px 28px rgba(59, 130, 246, 0.12);
  padding: 4px 12px;
  color: #1d4ed8;
}

.brp-soft-pill {
  border: 1px solid rgba(252, 211, 77, 0.58);
  background: rgba(254, 243, 199, 0.48);
  color: #92400e;
  padding: 4px 10px;
}

.brp-close {
  cursor: pointer;
  background: rgba(255, 255, 255, 0.34);
  border: 1px solid rgba(255, 255, 255, 0.52);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.34),
    0 6px 18px rgba(15, 23, 42, 0.05);
  transition: transform 0.16s ease, background-color 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}

.brp-close:hover {
  background: rgba(255, 255, 255, 0.58);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.brp-toolbar,
.brp-footer {
  border-color: rgba(255, 255, 255, 0.34) !important;
}

.brp-list-panel {
  border: 1px solid rgba(255, 255, 255, 0.54);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.46), rgba(255, 255, 255, 0.26));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.42),
    0 20px 48px rgba(15, 23, 42, 0.07);
  backdrop-filter: blur(20px) saturate(140%);
  -webkit-backdrop-filter: blur(20px) saturate(140%);
}

.brp-list-head {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.28), rgba(255, 255, 255, 0.12));
  border-bottom-color: rgba(255, 255, 255, 0.34) !important;
}

.brp-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(170px, 220px) 190px;
  column-gap: 8px;
}

.brp-list-scroll {
  min-height: 260px;
  max-height: min(54vh, 520px);
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.65) transparent;
}

.brp-list-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
.brp-list-scroll::-webkit-scrollbar-track { background: transparent; }
.brp-list-scroll::-webkit-scrollbar-thumb {
  border: 2px solid rgba(255, 255, 255, 0.9);
  background: rgba(148, 163, 184, 0.52);
  border-radius: 999px;
}

.brp-row {
  min-height: 52px;
  transition: background-color 0.15s ease, transform 0.15s ease;
}

.brp-row:hover {
  background: rgba(255, 255, 255, 0.24);
}

.brp-row-icon {
  display: inline-flex;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
}

.brp-row-icon.is-normal {
  color: #d97706;
  background: rgba(254, 243, 199, 0.48);
  border: 1px solid rgba(252, 211, 77, 0.42);
}

.brp-row-icon.is-warn {
  color: #92400e;
  background: rgba(254, 243, 199, 0.66);
  border: 1px solid rgba(252, 211, 77, 0.62);
}

.brp-input-shell {
  height: 36px;
  border-color: rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.34);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.34),
    0 8px 24px rgba(15, 23, 42, 0.04);
  backdrop-filter: blur(18px) saturate(135%);
}

.brp-input {
  min-width: 0;
  width: 100%;
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

.brp-action-card {
  display: inline-flex;
  height: 34px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 14px;
  cursor: pointer;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.52);
  background: rgba(255, 255, 255, 0.42);
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.34),
    0 6px 18px rgba(15, 23, 42, 0.05);
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease, background-color 0.16s ease, color 0.16s ease;
}

.brp-action-card:hover {
  border-color: rgba(255, 255, 255, 0.72);
  background: rgba(255, 255, 255, 0.58);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.brp-action-card:active {
  transform: translateY(0) scale(0.97);
}

.brp-action-card-primary {
  border-color: rgba(147, 197, 253, 0.78);
  background: linear-gradient(180deg, #f8fbff 0%, #edf4ff 100%);
  color: #1d4ed8;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 4px 10px rgba(37, 99, 235, 0.08);
}

.brp-action-card-primary:hover {
  border-color: rgba(96, 165, 250, 0.82);
  background: linear-gradient(180deg, #f3f8ff 0%, #dfeeff 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    0 6px 14px rgba(37, 99, 235, 0.12);
}

.brp-action-icon {
  transition: transform 0.2s ease;
}

.brp-action-card:hover .brp-action-icon {
  transform: rotate(180deg) scale(1.06);
}

@media (max-width: 820px) {
  .brp-count-pill { display: none; }
  .brp-grid {
    grid-template-columns: minmax(0, 1fr);
    row-gap: 8px;
  }
  .brp-list-head { display: none; }
  .brp-row {
    align-items: stretch;
    padding-top: 10px;
    padding-bottom: 10px;
  }
}
</style>
