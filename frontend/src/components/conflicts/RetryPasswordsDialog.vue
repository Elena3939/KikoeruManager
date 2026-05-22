<template>
  <Teleport to="body">
    <Transition name="rpd-fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-[4000] flex items-center justify-center p-4 bg-black/20 backdrop-blur-[1.5px]"
        @click.self="handleCancel"
      >
        <div class="rpd-shell relative w-full max-w-[560px] max-h-[calc(100vh-2rem)] flex flex-col">
          <div class="relative overflow-hidden rounded-[26px] bg-white/98 border border-slate-100 shadow-2xl shadow-slate-900/10 flex flex-col max-h-[calc(100vh-2rem)]">
            <!-- Head -->
            <div class="flex items-start gap-3.5 px-6 pt-6 flex-none">
              <div class="w-11 h-11 flex-shrink-0 flex items-center justify-center rounded-2xl border bg-indigo-50/92 text-indigo-700 border-indigo-200/48">
                <RotateCcw :size="20" />
              </div>
              <div class="flex-1 min-w-0 pt-0.5">
                <h3 class="text-xl font-bold leading-tight text-slate-900">
                  {{ title }}
                </h3>
                <p class="mt-1.5 text-slate-500 text-[13px] leading-relaxed">
                  {{ description }}
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
                <Sparkles :size="12" class="inline-block mr-1 -mt-0.5 text-indigo-500" />
                可填多个密码，按顺序依次尝试，任一命中即成功。全部留空表示走密码库 / RJ 推导 / 默认密码。
              </p>
            </div>

            <!-- Password rows -->
            <div class="flex-1 min-h-0 overflow-y-auto px-6 pt-3 pb-2">
              <div class="flex flex-col gap-2.5">
                <div
                  v-for="(item, index) in items"
                  :key="item.key"
                  class="flex items-center gap-2"
                >
                  <span class="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-full bg-slate-100 text-slate-500 text-[11.5px] font-semibold tabular-nums">
                    {{ index + 1 }}
                  </span>
                  <input
                    :ref="el => bindInput(el, index)"
                    v-model="item.value"
                    type="text"
                    class="flex-1 min-w-0 px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 placeholder-slate-400 text-sm outline-none transition-all duration-200 focus:bg-white focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-100/60"
                    :placeholder="index === 0 ? '密码（可留空走密码库）' : `密码 ${index + 1}`"
                    autocomplete="off"
                    @keydown.enter.prevent="handleEnter(index)"
                    @keydown.stop
                  />
                  <button
                    type="button"
                    class="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all duration-150"
                    :disabled="items.length <= 1"
                    :title="items.length <= 1 ? '至少保留一行' : '删除该行'"
                    @click="removeRow(index)"
                  >
                    <X :size="14" />
                  </button>
                </div>
                <button
                  type="button"
                  class="self-start inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 text-[12.5px] font-medium transition-all duration-150"
                  @click="addRow"
                >
                  <Plus :size="14" />
                  添加密码
                </button>
              </div>
            </div>

            <!-- Actions -->
            <div class="flex-none flex items-center justify-between gap-3 px-6 pb-6 pt-3 border-t border-slate-100">
              <p class="text-xs text-slate-400">
                有效密码 {{ effectiveCount }} / {{ items.length }}
              </p>
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
                  class="rpd-confirm-btn"
                  @click="handleConfirm"
                >
                  <RotateCcw :size="14" />
                  {{ confirmText }}
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
import { Plus, RotateCcw, Sparkles, X } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 用于在标题里展示"重试 RJxxx"
  conflict: { type: Object, default: null },
  // 自定义文案（可选）
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  confirmText: { type: String, default: '开始重试' },
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const visible = computed(() => props.modelValue)

// 每行一个密码输入框，初始化一行
let rowSeq = 0
function makeRow(value = '') {
  rowSeq += 1
  return { key: `pwd-${rowSeq}`, value: String(value || '') }
}

const items = ref([makeRow('')])

const inputRefs = ref([])
function bindInput(el, index) {
  inputRefs.value[index] = el || null
}

function focusRow(index) {
  nextTick(() => {
    const el = inputRefs.value[index]
    if (el && typeof el.focus === 'function') {
      el.focus()
    }
  })
}

// 弹窗打开时重置为一行空输入并 focus
watch(visible, (open) => {
  if (open) {
    items.value = [makeRow('')]
    inputRefs.value = []
    focusRow(0)
  }
})

const effectiveCount = computed(
  () => items.value.filter(row => String(row.value || '').trim()).length
)

function addRow() {
  items.value.push(makeRow(''))
  focusRow(items.value.length - 1)
}

function removeRow(index) {
  if (items.value.length <= 1) return
  items.value.splice(index, 1)
  focusRow(Math.min(index, items.value.length - 1))
}

function handleEnter(index) {
  // 最后一行 Enter：如果当前行已填，自动加一行；否则直接确认
  const isLast = index === items.value.length - 1
  const current = String(items.value[index]?.value || '').trim()
  if (isLast && current) {
    addRow()
    return
  }
  if (!isLast) {
    focusRow(index + 1)
    return
  }
  handleConfirm()
}

function handleConfirm() {
  const seen = new Set()
  const passwords = []
  for (const row of items.value) {
    const value = String(row.value || '').trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    passwords.push(value)
  }
  emit('confirm', { passwords })
  emit('update:modelValue', false)
}

function handleCancel() {
  emit('cancel')
  emit('update:modelValue', false)
}
</script>

<style scoped>
.rpd-fade-enter-active, .rpd-fade-leave-active { transition: opacity 0.22s ease; }
.rpd-fade-enter-active .rpd-shell, .rpd-fade-leave-active .rpd-shell { transition: transform 0.24s ease, opacity 0.24s ease, filter 0.24s ease; }
.rpd-fade-enter-from, .rpd-fade-leave-to { opacity: 0; }
.rpd-fade-enter-from .rpd-shell, .rpd-fade-leave-to .rpd-shell { transform: translateY(6px) scale(0.985); opacity: 0; filter: blur(1px); }

/* 确认按钮：问题作品统一轻量蓝按钮，避免实心塑料感。 */
.rpd-confirm-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 18px;
  border-radius: 12px;
  border: 1px solid rgba(147, 197, 253, 0.78);
  background: linear-gradient(180deg, #f8fbff 0%, #edf4ff 100%);
  color: #1d4ed8;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 4px 10px rgba(37, 99, 235, 0.08);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.rpd-confirm-btn:hover {
  transform: translateY(-2px);
  background: linear-gradient(180deg, #f3f8ff 0%, #dfeeff 100%);
  border-color: rgba(96, 165, 250, 0.82);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    0 6px 14px rgba(37, 99, 235, 0.12);
}
.rpd-confirm-btn:active {
  transform: translateY(0) scale(0.97);
  transition: all 0.12s ease;
}
</style>
