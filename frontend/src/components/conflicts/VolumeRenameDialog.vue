<template>
  <Teleport to="body">
    <Transition name="vrd-fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-[4000] flex items-center justify-center p-4 bg-black/20 backdrop-blur-[1.5px]"
        @click.self="handleCancel"
      >
        <div class="vrd-shell relative w-full max-w-[680px] max-h-[calc(100vh-2rem)] flex flex-col">
          <div class="relative overflow-hidden rounded-[26px] bg-white/98 border border-slate-100 shadow-2xl shadow-slate-900/10 flex flex-col max-h-[calc(100vh-2rem)]">
            <!-- Head -->
            <div class="flex items-start gap-3.5 px-6 pt-6 flex-none">
              <div class="w-11 h-11 flex-shrink-0 flex items-center justify-center rounded-2xl border bg-amber-50/92 text-amber-700 border-amber-200/48">
                <FileEdit :size="20" />
              </div>
              <div class="flex-1 min-w-0 pt-0.5">
                <h3 class="text-xl font-bold leading-tight text-slate-900">
                  手动重命名分卷
                </h3>
                <p class="mt-1.5 text-slate-500 text-[13px] leading-relaxed">
                  系统识别到 <b class="text-amber-700">{{ detectedKindLabel }}</b> 伪装分卷，共 <b>{{ rows.length }}</b> 个文件。逐行确认目标名后提交，将原子重命名并自动重试解压。
                </p>
              </div>
              <button
                type="button"
                class="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100 hover:rotate-90 transition-all duration-200"
                @click="handleCancel"
              >
                <X :size="18" />
              </button>
            </div>

            <!-- Hint -->
            <div class="px-6 pt-3 flex-none">
              <p class="text-xs text-slate-400 leading-relaxed">
                <Sparkles :size="12" class="inline-block mr-1 -mt-0.5 text-amber-500" />
                目录：<code class="px-1 py-0.5 rounded bg-slate-100 text-slate-700">{{ directory }}</code>
              </p>
              <p class="mt-1 text-xs text-slate-400 leading-relaxed">
                目标名只能是单独的文件名（不带路径），全部必须落在同一目录、不重名、不与现有非候选文件冲突。
              </p>
            </div>

            <!-- Rename rows -->
            <div class="flex-1 min-h-0 overflow-y-auto px-6 pt-3 pb-2">
              <div class="flex flex-col gap-2.5">
                <div
                  v-for="(row, index) in rows"
                  :key="row.key"
                  class="vrd-row"
                  :class="{ 'is-error': !!row.error }"
                >
                  <span class="vrd-row-index">{{ index + 1 }}</span>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 min-w-0">
                      <span class="vrd-row-old" :title="row.oldName">{{ row.oldName }}</span>
                      <span class="vrd-row-arrow"><MoveRight :size="13" /></span>
                      <input
                        :ref="el => bindInput(el, index)"
                        v-model="row.newName"
                        type="text"
                        class="vrd-row-input"
                        placeholder="新文件名（含后缀）"
                        autocomplete="off"
                        spellcheck="false"
                        @input="row.touched = true"
                        @keydown.enter.prevent="handleEnter(index)"
                        @keydown.stop
                      />
                    </div>
                    <div class="flex items-center gap-3 mt-1 text-[11.5px] text-slate-400">
                      <span class="tabular-nums">{{ formatSize(row.size) }}</span>
                      <span v-if="row.error" class="text-rose-500">{{ row.error }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Actions -->
            <div class="flex-none flex items-center justify-between gap-3 px-6 pb-6 pt-3 border-t border-slate-100">
              <label class="flex items-center gap-2 text-xs text-slate-500 select-none cursor-pointer">
                <input
                  v-model="autoRetry"
                  type="checkbox"
                  class="w-3.5 h-3.5 rounded border-slate-300 text-indigo-500 focus:ring-indigo-200"
                />
                重命名后立即重试解压
              </label>
              <div class="flex items-center gap-2.5">
                <button
                  type="button"
                  class="px-4 py-2 text-sm text-slate-500 hover:text-slate-800 rounded-xl hover:bg-slate-100 transition-all duration-150 font-medium"
                  @click="handleCancel"
                >
                  取消
                </button>
                <button
                  type="button"
                  class="vrd-confirm-btn"
                  :disabled="!canSubmit"
                  @click="handleConfirm"
                >
                  <FileEdit :size="14" />
                  确认重命名
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { FileEdit, MoveRight, Sparkles, X } from 'lucide-vue-next'

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
.vrd-fade-enter-active, .vrd-fade-leave-active { transition: opacity 0.22s ease; }
.vrd-fade-enter-active .vrd-shell, .vrd-fade-leave-active .vrd-shell { transition: transform 0.24s ease, opacity 0.24s ease, filter 0.24s ease; }
.vrd-fade-enter-from, .vrd-fade-leave-to { opacity: 0; }
.vrd-fade-enter-from .vrd-shell, .vrd-fade-leave-to .vrd-shell { transform: translateY(6px) scale(0.985); opacity: 0; filter: blur(1px); }

.vrd-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  transition: all 0.2s ease;
}
.vrd-row:hover {
  border-color: rgba(245, 158, 11, 0.45);
  background: linear-gradient(180deg, #ffffff 0%, #fffbeb 100%);
}
.vrd-row.is-error {
  border-color: rgba(244, 63, 94, 0.55);
  background: linear-gradient(180deg, #ffffff 0%, #fef2f2 100%);
}

.vrd-row-index {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: 9999px;
  background: rgba(241, 245, 249, 0.85);
  color: #64748b;
  font-size: 11.5px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-variant-numeric: tabular-nums;
  margin-top: 4px;
}

.vrd-row-old {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  color: #475569;
  font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  background: rgba(241, 245, 249, 0.8);
  padding: 4px 8px;
  border-radius: 8px;
}

.vrd-row-arrow {
  color: #cbd5e1;
  flex-shrink: 0;
}

.vrd-row-input {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid rgba(203, 213, 225, 0.85);
  color: #0f172a;
  font-size: 12.5px;
  font-family: ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  outline: none;
  transition: all 0.2s ease;
}
.vrd-row-input:focus {
  border-color: rgba(245, 158, 11, 0.65);
  box-shadow: 0 0 0 2px rgba(254, 215, 170, 0.5);
}

/* 主操作按钮：琥珀语义色，轻量边框质感，不做实心塑料块。 */
.vrd-confirm-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 18px;
  border-radius: 12px;
  border: 1px solid rgba(251, 191, 36, 0.72);
  background: linear-gradient(180deg, #fffdfa 0%, #fff4d6 100%);
  color: #92400e;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 4px 10px rgba(217, 119, 6, 0.08);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.vrd-confirm-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(245, 158, 11, 0.78);
  background: linear-gradient(180deg, #fff9eb 0%, #fdecc0 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    0 6px 14px rgba(217, 119, 6, 0.12);
}
.vrd-confirm-btn:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  transition: all 0.12s ease;
}
.vrd-confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
