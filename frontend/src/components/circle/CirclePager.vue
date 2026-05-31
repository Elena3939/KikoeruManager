<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-vue-next'

const props = defineProps({
  currentPage: { type: Number, default: 1 },
  pageSize: { type: Number, default: 10 },
  pageSizes: { type: Array, default: () => [10, 20, 50, 100] },
  total: { type: Number, default: 0 },
  label: { type: String, default: '作品' },
})

const emit = defineEmits(['update:currentPage', 'update:pageSize'])

const rootRef = ref(null)
const sizeMenuOpen = ref(false)
const jumpValue = ref('1')

const normalizedPageSize = computed(() => {
  const value = Number(props.pageSize || 0)
  return Number.isFinite(value) && value > 0 ? value : Number(props.pageSizes?.[0] || 10)
})

const normalizedTotal = computed(() => {
  const value = Number(props.total || 0)
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0
})

const pageCount = computed(() => Math.max(1, Math.ceil(normalizedTotal.value / normalizedPageSize.value)))

const normalizedPage = computed(() => {
  const value = Number(props.currentPage || 1)
  if (!Number.isFinite(value)) return 1
  return Math.min(Math.max(1, Math.floor(value)), pageCount.value)
})

const totalText = computed(() => `Total ${normalizedTotal.value}`)

function setPage(page) {
  const next = Math.min(Math.max(1, Number(page || 1)), pageCount.value)
  if (next !== props.currentPage) emit('update:currentPage', next)
}

function setPageSize(size) {
  const next = Number(size)
  if (!Number.isFinite(next) || next <= 0) return
  if (next !== props.pageSize) emit('update:pageSize', next)
  if (props.currentPage !== 1) emit('update:currentPage', 1)
  sizeMenuOpen.value = false
}

function submitJump() {
  setPage(jumpValue.value)
  jumpValue.value = String(normalizedPage.value)
}

function handleRootPointerDown(event) {
  if (!rootRef.value?.contains(event.target)) sizeMenuOpen.value = false
}

watch(normalizedPage, page => {
  jumpValue.value = String(page)
})

watch(pageCount, count => {
  if (props.currentPage > count) emit('update:currentPage', count)
})

onMounted(() => {
  document.addEventListener('pointerdown', handleRootPointerDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleRootPointerDown)
})
</script>

<template>
  <nav ref="rootRef" class="circle-pager" aria-label="作品分页">
    <div class="circle-pager-total">{{ totalText }}</div>

    <div class="circle-pager-size">
      <button
        type="button"
        class="circle-pager-size-trigger"
        :class="{ 'is-open': sizeMenuOpen }"
        @click="sizeMenuOpen = !sizeMenuOpen"
      >
        <span>{{ normalizedPageSize }}/page</span>
        <ChevronDown :size="13" />
      </button>
      <Transition name="circle-pager-menu">
        <div v-if="sizeMenuOpen" class="circle-pager-size-menu">
          <button
            v-for="size in pageSizes"
            :key="size"
            type="button"
            class="circle-pager-size-option"
            :class="{ active: Number(size) === normalizedPageSize }"
            @click="setPageSize(size)"
          >
            {{ size }}/page
          </button>
        </div>
      </Transition>
    </div>

    <div class="circle-pager-controls">
      <button
        type="button"
        class="circle-pager-icon"
        :disabled="normalizedPage <= 1"
        title="上一页"
        @click="setPage(normalizedPage - 1)"
      >
        <ChevronLeft :size="14" />
      </button>

      <button type="button" class="circle-pager-page active" aria-current="page">
        {{ normalizedPage }}
      </button>

      <button
        type="button"
        class="circle-pager-icon"
        :disabled="normalizedPage >= pageCount"
        title="下一页"
        @click="setPage(normalizedPage + 1)"
      >
        <ChevronRight :size="14" />
      </button>
    </div>

    <form class="circle-pager-jump" @submit.prevent="submitJump">
      <label>Go to</label>
      <input
        v-model="jumpValue"
        type="number"
        inputmode="numeric"
        aria-label="跳转页码"
        min="1"
        :max="pageCount"
        class="circle-pager-jump-input"
        @blur="submitJump"
      />
    </form>
  </nav>
</template>

<style scoped>
.circle-pager {
  --pager-surface: var(--circle-surface-elevated, #ffffff);
  --pager-surface-soft: var(--circle-surface-soft, #f8fafc);
  --pager-surface-hover: var(--circle-hover-bg, #f1f5f9);
  --pager-border: var(--circle-border-soft, #e2e8f0);
  --pager-border-strong: var(--circle-border-strong, #94a3b8);
  --pager-text: var(--circle-text, #334155);
  --pager-muted: var(--circle-text-muted, #64748b);
  --pager-strong: var(--circle-text-strong, #0f172a);
  --pager-primary: var(--circle-primary, #2563eb);
  --pager-primary-bg: var(--circle-selected-bg, #eff6ff);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  width: 100%;
  min-height: 42px;
  color: var(--pager-text);
  font-size: 12px;
}

.circle-pager-total {
  color: var(--pager-muted);
  font-weight: 600;
  white-space: nowrap;
}

.circle-pager-size {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.circle-pager-size-trigger,
.circle-pager-icon,
.circle-pager-page,
.circle-pager-jump-input {
  height: 30px;
  border: 1px solid var(--pager-border);
  border-radius: 7px;
  background: var(--pager-surface);
  color: var(--pager-text);
  box-shadow: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.circle-pager-size-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 88px;
  padding: 0 10px;
  font-weight: 600;
}

.circle-pager-size-trigger svg,
.circle-pager-icon svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.circle-pager-size-trigger.is-open svg {
  transform: rotate(180deg);
}

.circle-pager-size-menu {
  position: absolute;
  right: 0;
  bottom: calc(100% + 8px);
  z-index: 30;
  display: grid;
  gap: 3px;
  min-width: 118px;
  padding: 6px;
  border: 1px solid var(--pager-border);
  border-radius: 9px;
  background: var(--pager-surface);
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.14);
}

.circle-pager-size-option {
  height: 30px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--pager-text);
  font-size: 12px;
  font-weight: 600;
  text-align: left;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.circle-pager-size-option:hover,
.circle-pager-size-option.active {
  background: var(--pager-surface-soft);
  border-color: var(--pager-border-strong);
  color: var(--pager-strong);
}

.circle-pager-controls {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.circle-pager-icon {
  width: 30px;
  display: inline-grid;
  place-items: center;
}

.circle-pager-page {
  min-width: 30px;
  padding: 0 9px;
  font-weight: 600;
}

.circle-pager-size-trigger:hover,
.circle-pager-icon:hover:not(:disabled),
.circle-pager-page:hover:not(.active),
.circle-pager-jump-input:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--pager-border-strong);
  background: var(--pager-surface-hover);
  color: var(--pager-strong);
}

.circle-pager-size-trigger:active,
.circle-pager-icon:active:not(:disabled),
.circle-pager-page:active,
.circle-pager-size-option:active {
  transform: scale(0.96);
}

.circle-pager-icon:disabled {
  cursor: not-allowed;
  opacity: 0.42;
  box-shadow: none;
}

.circle-pager-icon:hover:not(:disabled) svg {
  transform: scale(1.12);
}

.circle-pager-page.active {
  border-color: var(--pager-border-strong);
  background: var(--pager-surface-soft);
  color: var(--pager-strong);
  cursor: default;
  box-shadow: none;
}

.circle-pager-jump {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--pager-muted);
  font-weight: 600;
  white-space: nowrap;
}

.circle-pager-jump-input {
  width: 64px;
  padding: 0 8px;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
  background: var(--pager-surface) !important;
  border-color: var(--pager-border) !important;
  color: var(--pager-strong) !important;
  box-shadow: none !important;
  appearance: textfield;
}

.circle-pager-jump-input::-webkit-outer-spin-button,
.circle-pager-jump-input::-webkit-inner-spin-button {
  margin: 0;
  appearance: none;
}

.circle-pager-jump-input:focus {
  outline: none;
  border-color: var(--pager-primary) !important;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--pager-primary) 16%, transparent) !important;
}

:global(html.kikoerumanager-dark .circle-pager .circle-pager-jump-input),
:global(body.kikoerumanager-dark .circle-pager .circle-pager-jump-input) {
  background: var(--pager-surface) !important;
  background-image: none !important;
  border-color: var(--pager-border) !important;
  color: var(--pager-strong) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .circle-pager .circle-pager-jump-input:hover),
:global(body.kikoerumanager-dark .circle-pager .circle-pager-jump-input:hover) {
  background: var(--pager-surface-hover) !important;
  border-color: var(--pager-border-strong) !important;
}

:global(html.kikoerumanager-dark .circle-pager .circle-pager-jump-input:focus),
:global(body.kikoerumanager-dark .circle-pager .circle-pager-jump-input:focus) {
  background: var(--pager-surface) !important;
  border-color: var(--pager-primary) !important;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--pager-primary) 16%, transparent) !important;
}

.circle-pager-menu-enter-active,
.circle-pager-menu-leave-active {
  transition: opacity 0.16s ease, transform 0.18s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.circle-pager-menu-enter-from,
.circle-pager-menu-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.98);
}

@media (max-width: 760px) {
  .circle-pager {
    justify-content: center;
    flex-wrap: wrap;
  }

  .circle-pager-size,
  .circle-pager-jump {
    display: none;
  }
}

@media (max-width: 420px) {
  .circle-pager-total {
    width: 100%;
    text-align: center;
  }

}
</style>
