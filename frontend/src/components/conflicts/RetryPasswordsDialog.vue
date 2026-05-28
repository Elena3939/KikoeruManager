<template>
  <Teleport to="body">
    <Transition name="rpd-fade">
      <div
        v-if="visible"
        class="rpd-overlay fixed inset-0 z-[4000] flex items-center justify-center p-6 max-[640px]:p-3"
        @click.self="handleCancel"
      >
        <div class="rpd-window relative w-full max-w-[620px] max-h-[calc(100vh-3rem)] flex flex-col rounded-3xl overflow-hidden" @mousedown.stop>
          <!-- Header -->
          <header class="rpd-header flex items-start justify-between gap-4 px-7 pt-6 pb-4 flex-none">
            <div class="min-w-0 flex-1">
              <h1 class="rpd-title text-2xl font-bold tracking-tight">{{ title }}</h1>
              <p class="rpd-subtitle text-sm m-0 mt-1.5">{{ description }}</p>
            </div>
            <button
              type="button"
              class="rpd-close inline-flex size-9 items-center justify-center rounded-full flex-shrink-0"
              title="关闭"
              @click="handleCancel"
            >
              <X :size="18" :stroke-width="2" />
            </button>
          </header>

          <!-- Body：密码队列面板 -->
          <div class="rpd-body flex-1 min-h-0 overflow-y-auto px-7 py-4">
            <section class="rpd-password-panel">
              <div class="rpd-panel-head">
                <div>
                  <p class="rpd-panel-kicker">尝试顺序</p>
                  <h2>指定密码队列</h2>
                </div>
                <span class="rpd-count-chip">{{ effectiveCount }}/{{ items.length }} 已填写</span>
              </div>

              <div class="rpd-rows flex flex-col">
                <div
                  v-for="(item, index) in items"
                  :key="item.key"
                  class="rpd-row"
                >
                  <span class="rpd-row-index">{{ index + 1 }}</span>
                  <div class="rpd-input-wrap">
                    <span class="rpd-input-label">{{ index === 0 ? '首选密码' : `备用密码 ${index + 1}` }}</span>
                    <input
                      :ref="el => bindInput(el, index)"
                      v-model="item.value"
                      type="text"
                      class="rpd-input"
                      :placeholder="index === 0 ? '留空则使用密码库 / RJ 推导' : '命中失败后继续尝试'"
                      autocomplete="off"
                      @keydown.enter.prevent="handleEnter(index)"
                      @keydown.stop
                    />
                  </div>
                  <button
                    type="button"
                    class="rpd-row-del inline-flex size-9 items-center justify-center rounded-full flex-shrink-0"
                    :disabled="items.length <= 1"
                    :title="items.length <= 1 ? '至少保留一行' : '删除该行'"
                    @click="removeRow(index)"
                  >
                    <X :size="15" :stroke-width="2.4" />
                  </button>
                </div>
              </div>

              <button
                type="button"
                class="rpd-add inline-flex items-center gap-1.5"
                @click="addRow"
              >
                <Plus :size="14" :stroke-width="2.4" />
                添加备用密码
              </button>
            </section>
          </div>

          <!-- Footer -->
          <footer class="rpd-footer flex items-center justify-between gap-4 px-7 py-5 flex-none">
            <p class="rpd-summary text-sm m-0">
              {{ effectiveCount ? `将尝试 ${effectiveCount} 个指定密码` : '未指定密码，将走密码库 / RJ 推导 / 默认密码' }}
            </p>
            <div class="flex items-center gap-3">
              <button
                type="button"
                class="rpd-btn-secondary px-6 h-10 rounded-xl font-bold"
                @click="handleCancel"
              >取消</button>
              <button
                type="button"
                class="rpd-btn-primary px-7 h-10 rounded-xl font-bold text-white"
                @click="handleConfirm"
              >{{ confirmText }}</button>
            </div>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Plus, X } from 'lucide-vue-next'

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
/* ============================================================
   RetryPasswordsDialog 玻璃壳风格
   ----------------------------------------------------------------
   单层半透白 backdrop-blur shell + 直接平铺密码行（不嵌卡片）+
   主操作 #111827 深色实心 / 次操作半透灰，对齐社团补全下载预览。
============================================================ */

.rpd-fade-enter-active,
.rpd-fade-leave-active { transition: opacity 0.22s ease; }
.rpd-fade-enter-active .rpd-window,
.rpd-fade-leave-active .rpd-window {
  transition: transform 0.26s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease, filter 0.22s ease;
}
.rpd-fade-enter-from,
.rpd-fade-leave-to { opacity: 0; }
.rpd-fade-enter-from .rpd-window,
.rpd-fade-leave-to .rpd-window {
  transform: translateY(8px) scale(0.97);
  opacity: 0;
  filter: blur(1px);
}

/* Overlay：只承载点击关闭，不压暗、不虚化背景 */
.rpd-overlay {
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

/* Shell：对齐社团补全预览的白色毛玻璃壳 */
.rpd-window {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow:
    0 30px 80px rgba(15, 23, 42, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.3);
}

/* Header */
.rpd-header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.16);
}

.rpd-title {
  margin: 0;
  color: #0f172a;
  letter-spacing: -0.02em;
  line-height: 1.15;
}

.rpd-subtitle {
  color: #64748b;
  line-height: 1.5;
}

.rpd-close {
  border: 0;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.rpd-close:hover {
  background: rgba(241, 245, 249, 0.72);
  color: #334155;
}

.rpd-close svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.rpd-close:hover svg {
  transform: rotate(90deg);
}

/* Body */
.rpd-body {
  background: rgba(255, 255, 255, 0.06);
}

.rpd-password-panel {
  border: 1px solid rgba(255, 255, 255, 0.34);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.22);
  padding: 14px;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.56),
    0 12px 30px rgba(15, 23, 42, 0.06);
  backdrop-filter: blur(16px) saturate(135%);
  -webkit-backdrop-filter: blur(16px) saturate(135%);
}

.rpd-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 2px 2px 12px;
}

.rpd-panel-kicker {
  margin: 0 0 3px;
  color: #94a3b8;
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.rpd-panel-head h2 {
  margin: 0;
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.rpd-count-chip {
  display: inline-flex;
  flex: none;
  align-items: center;
  height: 28px;
  border: 1px solid rgba(255, 255, 255, 0.36);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.28);
  padding: 0 10px;
  color: #475569;
  font-size: 11.5px;
  font-weight: 800;
}

.rpd-rows {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0;
}

.rpd-row {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 36px;
  align-items: center;
  gap: 10px;
  min-height: 58px;
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.2);
  padding: 8px 10px;
}

.rpd-row-index {
  display: inline-flex;
  width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.28);
  font-size: 11.5px;
  font-weight: 800;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

.rpd-input-wrap {
  display: grid;
  min-width: 0;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
}

.rpd-input-label {
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.rpd-input {
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border: 1px solid rgba(255, 255, 255, 0.34);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.34);
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
  outline: none;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  transition: background-color 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.rpd-input::placeholder { color: #94a3b8; }

.rpd-input:focus {
  background: rgba(255, 255, 255, 0.62);
  border-color: rgba(15, 23, 42, 0.16);
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.045);
}

.rpd-row-del {
  border: 1px solid rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.18);
  color: #94a3b8;
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease;
}

.rpd-row-del:hover:not(:disabled) {
  background: rgba(225, 29, 72, 0.08);
  color: #be123c;
}

.rpd-row-del:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.rpd-add {
  align-self: flex-start;
  height: 34px;
  margin-top: 12px;
  padding: 0 15px;
  border: 1px solid rgba(255, 255, 255, 0.34);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.24);
  color: #475569;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  letter-spacing: 0.01em;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.rpd-add:hover {
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(15, 23, 42, 0.18);
  color: #0f172a;
  transform: translateY(-2px) scale(1.02);
}

/* Footer */
.rpd-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.28);
  background: rgba(255, 255, 255, 0.14);
}

.rpd-summary {
  color: #64748b;
}

/* Buttons：与社团预览 primary-cta / secondary-cta 同款 */
.rpd-btn-primary,
.rpd-btn-secondary {
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

.rpd-btn-secondary {
  background: rgba(17, 24, 39, 0.06);
  color: #334155;
}

.rpd-btn-secondary:hover {
  background: rgba(15, 23, 42, 0.1);
  color: #0f172a;
  transform: translateY(-2px) scale(1.02);
}

.rpd-btn-primary {
  background: #111827;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.16);
}

.rpd-btn-primary:hover {
  background: #0f172a;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22);
  transform: translateY(-2px) scale(1.02);
}

.rpd-btn-primary:active,
.rpd-btn-secondary:active { transform: scale(0.96); }

@media (max-width: 640px) {
  .rpd-header,
  .rpd-body,
  .rpd-footer {
    padding-left: 18px;
    padding-right: 18px;
  }

  .rpd-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .rpd-footer > div {
    justify-content: flex-end;
  }

  .rpd-row {
    grid-template-columns: 30px minmax(0, 1fr) 34px;
    gap: 8px;
  }

  .rpd-input-wrap {
    grid-template-columns: 1fr;
    gap: 6px;
  }
}
</style>
