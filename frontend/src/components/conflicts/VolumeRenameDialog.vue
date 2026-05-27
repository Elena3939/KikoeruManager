<template>
  <Teleport to="body">
    <Transition name="vrd-fade">
      <div
        v-if="visible"
        class="vrd-overlay fixed inset-0 z-[4000] flex items-center justify-center p-6 max-[640px]:p-3"
        @click.self="handleCancel"
      >
        <div class="vrd-window relative w-full max-w-[700px] max-h-[calc(100vh-3rem)] flex flex-col rounded-3xl overflow-hidden" @mousedown.stop>
          <!-- Header -->
          <header class="vrd-header flex items-start justify-between gap-4 px-7 pt-6 pb-4 flex-none">
            <div class="min-w-0 flex-1">
              <h1 class="vrd-title text-2xl font-bold tracking-tight">手动重命名分卷</h1>
              <p class="vrd-subtitle text-sm m-0 mt-1.5">
                系统识别到伪装分卷，共 {{ rows.length }} 个文件。逐行确认目标名后提交，将原子重命名并自动重试解压。
              </p>
            </div>
            <button
              type="button"
              class="vrd-close inline-flex size-9 items-center justify-center rounded-full flex-shrink-0"
              title="关闭"
              @click="handleCancel"
            >
              <X :size="18" :stroke-width="2" />
            </button>
          </header>

          <!-- Pill rail -->
          <div class="vrd-tabs px-7 pt-1 pb-3 flex items-center flex-wrap gap-1.5 flex-none">
            <span class="vrd-pill is-amber"><b>{{ detectedKindLabel }}</b> 伪装分卷</span>
            <span class="vrd-pill"><b>{{ rows.length }}</b> 个文件</span>
            <span v-if="directory" class="vrd-pill is-mono ml-auto" :title="directory">
              <FolderOpen :size="12" :stroke-width="2.4" />
              <span class="truncate max-w-[260px]">{{ directory }}</span>
            </span>
          </div>

          <!-- Body：重命名映射直接平铺，无 14px 圆角卡套卡 -->
          <div class="vrd-body flex-1 min-h-0 overflow-y-auto px-7 py-2">
            <div
              v-for="(row, index) in rows"
              :key="row.key"
              class="vrd-row"
              :class="{ 'is-error': !!row.error }"
            >
              <span class="vrd-row-index">{{ index + 1 }}</span>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="vrd-row-old truncate" :title="row.oldName">{{ row.oldName }}</span>
                  <span class="vrd-row-arrow"><MoveRight :size="13" :stroke-width="2.4" /></span>
                  <input
                    :ref="el => bindInput(el, index)"
                    v-model="row.newName"
                    type="text"
                    class="vrd-row-input flex-1 min-w-0"
                    placeholder="新文件名（含后缀）"
                    autocomplete="off"
                    spellcheck="false"
                    @input="row.touched = true"
                    @keydown.enter.prevent="handleEnter(index)"
                    @keydown.stop
                  />
                </div>
                <div class="vrd-row-meta flex items-center gap-3 mt-1.5">
                  <span class="tabular-nums">{{ formatSize(row.size) }}</span>
                  <span v-if="row.error" class="vrd-row-error">{{ row.error }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <footer class="vrd-footer flex items-center justify-between gap-4 px-7 py-5 flex-none">
            <label class="vrd-checkbox flex items-center gap-2 text-sm select-none cursor-pointer m-0">
              <input v-model="autoRetry" type="checkbox" />
              <span>重命名后立即重试解压</span>
            </label>
            <div class="flex items-center gap-3">
              <button
                type="button"
                class="vrd-btn-secondary px-6 h-10 rounded-xl font-bold"
                @click="handleCancel"
              >取消</button>
              <button
                type="button"
                class="vrd-btn-primary px-7 h-10 rounded-xl font-bold text-white"
                :disabled="!canSubmit"
                @click="handleConfirm"
              >确认重命名</button>
            </div>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { FolderOpen, MoveRight, X } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 当前 conflict 对象（来自 Conflicts.vue），后端在 new_metadata.disguised_volume_set
  // 里塞了 detection payload：directory / detected_kind / suspect_files / suggested_renames。
  conflict: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const visible = computed(() => props.modelValue)

const autoRetry = ref(true)
const rows = ref([])
const inputRefs = ref([])

const detectedKindLabel = computed(() => {
  const kind = String(disguisedPayload.value?.detected_kind || '').toLowerCase()
  if (kind === '7z') return '7z'
  if (kind === 'rar') return 'RAR'
  if (kind === 'zip') return 'ZIP'
  return '未知格式'
})

const disguisedPayload = computed(() => {
  return props.conflict?.new_metadata?.disguised_volume_set || null
})

const directory = computed(() => String(disguisedPayload.value?.directory || ''))

function bindInput(el, index) {
  inputRefs.value[index] = el || null
}

function basenameOf(path) {
  if (!path) return ''
  const normalized = String(path).replace(/\\/g, '/')
  const idx = normalized.lastIndexOf('/')
  return idx >= 0 ? normalized.slice(idx + 1) : normalized
}

function formatSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function buildRows() {
  const payload = disguisedPayload.value
  if (!payload) return []
  const suspect = Array.isArray(payload.suspect_files) ? payload.suspect_files : []
  const suggested = Array.isArray(payload.suggested_renames) ? payload.suggested_renames : []
  const suggestedByOld = new Map()
  for (const item of suggested) {
    if (item && item.old) suggestedByOld.set(String(item.old), basenameOf(item.new))
  }
  return suspect.map((item, index) => {
    const oldPath = String(item.path || '')
    return {
      key: `vol-${index}-${oldPath}`,
      oldPath,
      oldName: basenameOf(oldPath),
      newName: suggestedByOld.get(oldPath) || basenameOf(oldPath),
      size: Number(item.size || 0),
      touched: false,
      error: '',
    }
  })
}

function focusRow(index) {
  nextTick(() => {
    const el = inputRefs.value[index]
    if (el && typeof el.focus === 'function') {
      el.focus()
      try { el.select() } catch {}
    }
  })
}

watch(
  () => [visible.value, disguisedPayload.value],
  ([open]) => {
    if (open) {
      rows.value = buildRows()
      inputRefs.value = []
      autoRetry.value = true
      nextTick(() => focusRow(0))
    }
  },
  { immediate: true },
)

const canSubmit = computed(() => {
  if (!rows.value.length) return false
  return validate(false)
})

function validate(applyErrors) {
  // 本地校验，与后端 rename_disguised_volumes 的闸门保持一致：
  // - new 不能为空、不能含路径分隔符、不能是 . / ..、不能含 ..
  // - 各行 new 必须互不相同（按大小写不敏感比较，同 Windows 行为）
  let ok = true
  const seen = new Map()
  for (const row of rows.value) {
    let err = ''
    const value = String(row.newName || '').trim()
    if (!value) {
      err = '新文件名不能为空'
    } else if (value.includes('/') || value.includes('\\')) {
      err = '不能含路径分隔符'
    } else if (value === '.' || value === '..' || value.split(/[\\/]/).includes('..')) {
      err = '不允许 .. 路径段'
    } else {
      const lowered = value.toLowerCase()
      if (seen.has(lowered)) {
        err = `与第 ${seen.get(lowered) + 1} 行重名`
      } else {
        seen.set(lowered, rows.value.indexOf(row))
      }
    }
    if (applyErrors) row.error = err
    if (err) ok = false
  }
  return ok
}

function handleEnter(index) {
  if (index < rows.value.length - 1) {
    focusRow(index + 1)
    return
  }
  if (canSubmit.value) handleConfirm()
}

function handleConfirm() {
  if (!validate(true)) return
  const renames = rows.value.map(row => ({
    old: row.oldPath,
    new: String(row.newName || '').trim(),
  }))
  emit('confirm', { renames, autoRetry: autoRetry.value })
  emit('update:modelValue', false)
}

function handleCancel() {
  emit('cancel')
  emit('update:modelValue', false)
}
</script>

<style scoped>
/* ============================================================
   VolumeRenameDialog 玻璃壳风格
   ----------------------------------------------------------------
   单层半透白 backdrop-blur shell + 直接平铺重命名行（无 14px 圆角卡套卡）
   + 主操作 #111827 深色实心 / 次操作半透灰，对齐社团补全下载预览。
============================================================ */

.vrd-fade-enter-active,
.vrd-fade-leave-active { transition: opacity 0.22s ease; }
.vrd-fade-enter-active .vrd-window,
.vrd-fade-leave-active .vrd-window {
  transition: transform 0.26s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease, filter 0.22s ease;
}
.vrd-fade-enter-from,
.vrd-fade-leave-to { opacity: 0; }
.vrd-fade-enter-from .vrd-window,
.vrd-fade-leave-to .vrd-window {
  transform: translateY(8px) scale(0.97);
  opacity: 0;
  filter: blur(1px);
}

/* Overlay：只承载点击关闭，不压暗、不虚化背景 */
.vrd-overlay {
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

/* Shell：对齐社团补全预览的白色毛玻璃壳 */
.vrd-window {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(28px) saturate(135%);
  -webkit-backdrop-filter: blur(28px) saturate(135%);
  border: 1px solid rgba(255, 255, 255, 0.42);
  box-shadow:
    0 28px 70px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

/* Header */
.vrd-header {
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
}

.vrd-title {
  margin: 0;
  color: #0f172a;
  letter-spacing: -0.02em;
  line-height: 1.15;
}

.vrd-subtitle {
  color: #64748b;
  line-height: 1.5;
}

.vrd-close {
  border: 0;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.vrd-close:hover {
  background: rgba(241, 245, 249, 0.72);
  color: #334155;
}

.vrd-close svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.vrd-close:hover svg {
  transform: rotate(90deg);
}

/* Pill rail */
.vrd-tabs {
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
}

.vrd-pill {
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

.vrd-pill b {
  color: #0f172a;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.vrd-pill.is-amber {
  border-color: rgba(252, 211, 77, 0.62);
  background: rgba(254, 243, 199, 0.85);
  color: #92400e;
}

.vrd-pill.is-amber b { color: #92400e; }

.vrd-pill.is-mono {
  font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  font-size: 11px;
  letter-spacing: 0;
  color: #64748b;
}

/* Body 行：直接平铺，无内部卡片 */
.vrd-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 4px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
  transition: background-color 0.15s ease;
}

.vrd-row:last-of-type {
  border-bottom: 0;
}

.vrd-row:hover {
  background: rgba(255, 255, 255, 0.45);
}

.vrd-row.is-error {
  background: rgba(254, 226, 226, 0.4);
}

.vrd-row-index {
  flex-shrink: 0;
  display: inline-flex;
  width: 28px;
  align-items: center;
  justify-content: center;
  margin-top: 8px;
  font-size: 11.5px;
  font-weight: 700;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
}

.vrd-row-old {
  display: inline-flex;
  align-items: center;
  max-width: 50%;
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  background: rgba(241, 245, 249, 0.7);
  color: #475569;
  font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  font-size: 12px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.vrd-row-arrow {
  flex-shrink: 0;
  color: #cbd5e1;
}

.vrd-row-input {
  height: 32px;
  padding: 0 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.6);
  color: #0f172a;
  font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  font-size: 12px;
  outline: none;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.vrd-row-input::placeholder { color: #94a3b8; }

.vrd-row-input:focus {
  background: rgba(255, 255, 255, 0.92);
  border-color: rgba(15, 23, 42, 0.22);
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.06);
}

.vrd-row.is-error .vrd-row-input {
  border-color: rgba(244, 63, 94, 0.55);
}

.vrd-row-meta {
  font-size: 11.5px;
  color: #94a3b8;
}

.vrd-row-error {
  color: #be123c;
  font-weight: 500;
}

/* Footer */
.vrd-footer {
  border-top: 1px solid rgba(15, 23, 42, 0.06);
}

.vrd-checkbox {
  color: #475569;
}

.vrd-checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  accent-color: #111827;
  cursor: pointer;
}

.vrd-btn-primary:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  box-shadow: none;
}

/* Buttons / Tags：跟随问题作品页玻璃主题 */
.vrd-pill {
  height: 28px;
  padding: 0 12px;
  border-color: rgba(255, 255, 255, 0.62);
  background: rgba(255, 255, 255, 0.56);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.72),
    0 6px 14px rgba(15, 23, 42, 0.055);
  font-weight: 700;
}

.vrd-pill.is-amber {
  border-color: rgba(251, 191, 36, 0.45);
  background: rgba(255, 247, 237, 0.78);
  color: #9a3412;
}

.vrd-pill.is-mono {
  border-color: rgba(203, 213, 225, 0.56);
  background: rgba(248, 250, 252, 0.62);
}

.vrd-btn-primary,
.vrd-btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 14px;
  cursor: pointer;
  letter-spacing: 0.01em;
  white-space: nowrap;
  font-size: 13px;
  transition:
    background-color 0.18s ease,
    color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.vrd-btn-secondary {
  border: 1px solid rgba(255, 255, 255, 0.66);
  background: rgba(255, 255, 255, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.vrd-btn-secondary:hover {
  transform: translateY(-2px) scale(1.02);
  background: rgba(255, 255, 255, 0.86);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.84),
    0 14px 28px rgba(15, 23, 42, 0.12);
}

.vrd-btn-primary {
  background: #111827;
  box-shadow:
    0 14px 28px rgba(15, 23, 42, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.vrd-btn-primary:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  background: #0f172a;
  box-shadow:
    0 18px 34px rgba(15, 23, 42, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.14);
}

.vrd-btn-primary:active:not(:disabled),
.vrd-btn-secondary:active {
  transform: scale(0.96);
}

@media (max-width: 640px) {
  .vrd-row {
    align-items: stretch;
  }
  .vrd-row > div:not(.vrd-row-index) > div:first-child {
    flex-direction: column;
    align-items: stretch;
  }
  .vrd-row-old {
    max-width: 100%;
  }
  .vrd-footer {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .vrd-footer .flex {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
