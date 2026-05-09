<template>
  <div ref="rootRef" class="app-dd-root">
    <!-- Trigger -->
    <slot name="trigger" :open="open" :selected="selectedOption" :toggle="toggle">
      <button
        ref="triggerRef"
        type="button"
        class="app-dd-trigger"
        :class="{ 'is-open': open, 'is-placeholder': !selectedOption }"
        :style="triggerWidthStyle"
        @click="toggle"
      >
        <component
          v-if="selectedOption?.icon"
          :is="selectedOption.icon"
          :size="14"
          :stroke-width="2.2"
          class="app-dd-trigger-icon"
        />
        <span v-if="label" class="app-dd-trigger-label">{{ label }}</span>
        <span class="app-dd-trigger-value" :title="triggerText">{{ triggerText }}</span>
        <span
          v-if="selectedOption?.badge && showTriggerBadge"
          class="app-dd-badge"
          :class="badgeToneClass(selectedOption.badge.tone)"
        >{{ selectedOption.badge.label }}</span>
        <ChevronDown
          :size="13"
          :stroke-width="2.4"
          class="app-dd-trigger-caret"
          :class="{ 'is-open': open }"
        />
      </button>
    </slot>

    <!-- Menu -->
    <Teleport to="body">
      <Transition name="app-dd-menu">
        <div
          v-if="open"
          ref="menuRef"
          class="app-dd-menu"
          :class="`app-dd-menu--${placement}`"
          :style="menuStyle"
          @click.stop
        >
          <button
            v-for="option in options"
            :key="option.value"
            type="button"
            class="app-dd-item"
            :class="{ 'is-active': option.value === modelValue }"
            @click="handleSelect(option)"
          >
            <slot name="option" :option="option" :is-active="option.value === modelValue">
              <component
                v-if="option.icon"
                :is="option.icon"
                :size="14"
                :stroke-width="2.2"
                class="app-dd-item-icon"
              />
              <div class="app-dd-item-text">
                <div class="app-dd-item-label">{{ option.label }}</div>
                <div v-if="option.description" class="app-dd-item-description">{{ option.description }}</div>
              </div>
              <span
                v-if="option.badge"
                class="app-dd-badge"
                :class="badgeToneClass(option.badge.tone)"
              >{{ option.badge.label }}</span>
              <span v-else-if="option.suffix" class="app-dd-item-suffix">{{ option.suffix }}</span>
              <Check
                v-if="option.value === modelValue"
                :size="13"
                :stroke-width="2.6"
                class="app-dd-item-check"
              />
            </slot>
          </button>

          <div v-if="!options.length" class="app-dd-empty">
            {{ emptyText }}
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  // [{ value, label, description?, suffix?, badge?: { label, tone }, icon? }]
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  label: { type: String, default: '' },
  width: { type: [Number, String], default: 0 },
  menuMinWidth: { type: [Number, String], default: 0 },
  emptyText: { type: String, default: '暂无选项' },
  showTriggerBadge: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'change'])

const rootRef = ref(null)
const triggerRef = ref(null)
const menuRef = ref(null)
const open = ref(false)
const menuStyle = ref({})

const selectedOption = computed(() =>
  props.options.find((opt) => opt.value === props.modelValue) || null,
)

const triggerText = computed(() =>
  selectedOption.value ? selectedOption.value.label : props.placeholder,
)

const triggerWidthStyle = computed(() => {
  const w = Number(props.width)
  return w > 0 ? { width: `${w}px` } : {}
})

function badgeToneClass(tone) {
  switch (tone) {
    case 'emerald':
    case 'success':
      return 'tone-emerald'
    case 'amber':
    case 'warning':
      return 'tone-amber'
    case 'sky':
    case 'info':
      return 'tone-sky'
    case 'rose':
    case 'danger':
      return 'tone-rose'
    case 'violet':
      return 'tone-violet'
    case 'slate':
    default:
      return 'tone-slate'
  }
}

const placement = ref('bottom')

function updateMenuPosition() {
  const trigger = triggerRef.value
  if (!trigger) return
  const rect = trigger.getBoundingClientRect()
  const minWidth = Number(props.menuMinWidth) || rect.width
  const menuWidth = Math.max(rect.width, minWidth)
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const padding = 8
  const gap = 6

  // 水平：默认居中对齐 trigger，即 menu.center = trigger.center；
  // 当宽度超出视口时回密到左右边缘。
  let left = rect.left + rect.width / 2 - menuWidth / 2
  if (left + menuWidth > viewportWidth - padding) {
    left = viewportWidth - padding - menuWidth
  }
  if (left < padding) left = padding

  // 垂直：优先放在 trigger 下方；如果下方空间不足且上方更宽敷，翻到上方显示。
  const menuMaxHeight = 360 // 跟 CSS .app-dd-menu max-height 同步
  const spaceBelow = viewportHeight - rect.bottom - padding
  const spaceAbove = rect.top - padding
  const needBelow = Math.min(menuMaxHeight, 200) // 至少要 200px 下沿空间，否则考虑翻

  let top
  if (spaceBelow >= needBelow || spaceBelow >= spaceAbove) {
    // 空间够 或 下方比上方宽 → 正常下方
    top = rect.bottom + gap
    placement.value = 'bottom'
  } else {
    // 翻到上方
    top = rect.top - gap
    placement.value = 'top'
  }

  menuStyle.value = placement.value === 'top'
    ? {
        left: `${left}px`,
        top: `${top}px`,
        minWidth: `${menuWidth}px`,
        transform: 'translateY(-100%)',
      }
    : {
        left: `${left}px`,
        top: `${top}px`,
        minWidth: `${menuWidth}px`,
      }
}

async function toggle() {
  if (open.value) {
    open.value = false
    return
  }
  open.value = true
  await nextTick()
  updateMenuPosition()
}

function handleSelect(option) {
  if (option.value !== props.modelValue) {
    emit('update:modelValue', option.value)
    emit('change', option)
  }
  open.value = false
}

function handleDocumentClick(event) {
  if (!open.value) return
  const target = event.target
  if (
    rootRef.value && !rootRef.value.contains(target)
    && menuRef.value && !menuRef.value.contains(target)
  ) {
    open.value = false
  }
}

function handleKeydown(event) {
  if (!open.value) return
  if (event.key === 'Escape') {
    open.value = false
  }
}

function handleScroll() {
  if (open.value) updateMenuPosition()
}

watch(open, (next) => {
  if (next) {
    document.addEventListener('mousedown', handleDocumentClick)
    document.addEventListener('keydown', handleKeydown)
    window.addEventListener('scroll', handleScroll, true)
    window.addEventListener('resize', updateMenuPosition)
  } else {
    document.removeEventListener('mousedown', handleDocumentClick)
    document.removeEventListener('keydown', handleKeydown)
    window.removeEventListener('scroll', handleScroll, true)
    window.removeEventListener('resize', updateMenuPosition)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleDocumentClick)
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('scroll', handleScroll, true)
  window.removeEventListener('resize', updateMenuPosition)
})

defineExpose({ close: () => (open.value = false) })
</script>

<style scoped>
/* ============================================================
 * 通用 Dropdown
 * - Teleport 到 body 避免被父级 overflow 裁剪
 * - 入场: ease-out-expo 曲线 + scale + translateY + 选项 stagger
 * - active 态: 黑底白字 + ✓ 弹出
 * - 支持 trigger / option slot 完全覆盖
 * ============================================================ */

.app-dd-root {
  display: inline-block;
  position: relative;
}

/* ---- Trigger ---- */
.app-dd-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 10px 0 12px;
  border: 1px solid rgb(226 232 240);
  border-radius: 10px;
  background: rgb(248 250 252);
  color: rgb(15 23 42);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition:
    background-color 0.28s cubic-bezier(0.22, 1, 0.36, 1),
    border-color 0.28s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.28s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1),
    color 0.2s ease;
}

.app-dd-trigger:hover {
  background: #fff;
  border-color: rgb(203 213 225);
  transform: translateY(-1px);
  box-shadow: 0 6px 14px -10px rgba(15, 23, 42, 0.22);
}
.app-dd-trigger:active {
  transform: translateY(0) scale(0.98);
  transition-duration: 0.12s;
}

.app-dd-trigger.is-open {
  background: #fff;
  border-color: rgb(148 163 184);
  box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.14);
  transform: translateY(0);
}

.app-dd-trigger.is-placeholder .app-dd-trigger-value {
  color: rgba(100, 116, 139, 0.78);
  font-weight: 500;
}

.app-dd-trigger-icon {
  flex-shrink: 0;
  color: rgb(100 116 139);
}

.app-dd-trigger-label {
  color: rgb(100 116 139);
  font-size: 12px;
  font-weight: 500;
  margin-right: 2px;
  white-space: nowrap;
}

.app-dd-trigger-value {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.app-dd-trigger-caret {
  flex-shrink: 0;
  color: rgb(100 116 139);
  margin-left: 2px;
  transition:
    transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1),
    color 0.2s ease;
}
.app-dd-trigger:hover .app-dd-trigger-caret {
  color: #0f172a;
  transform: translateY(1px);
}
.app-dd-trigger-caret.is-open,
.app-dd-trigger:hover .app-dd-trigger-caret.is-open {
  transform: rotate(180deg);
  color: #0f172a;
}

/* ---- Menu ---- */
.app-dd-menu {
  position: fixed;
  /* z-index 提高到 9999，高于 Element Plus 的对话框/弹层/固定工具栏，
   * 防止被视口里任何布局全局元素遮挡。*/
  z-index: 9999;
  max-height: 360px;
  overflow-y: auto;
  padding: 5px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 12px;
  box-shadow:
    0 18px 38px -14px rgba(15, 23, 42, 0.22),
    0 6px 14px -8px rgba(15, 23, 42, 0.12);
  will-change: transform, opacity;
  backface-visibility: hidden;
}

/* placement 对应的 transform-origin，让 scale 动画从正确的错开点开始 */
.app-dd-menu--bottom {
  transform-origin: top center;
}
.app-dd-menu--top {
  transform-origin: bottom center;
}

.app-dd-menu::-webkit-scrollbar {
  width: 6px;
}
.app-dd-menu::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.4);
  border-radius: 999px;
}
.app-dd-menu::-webkit-scrollbar-thumb:hover {
  background: rgba(100, 116, 139, 0.55);
}

/* 入场动画 */
.app-dd-menu-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.94);
}
.app-dd-menu-enter-to {
  opacity: 1;
  transform: translateY(0) scale(1);
}
.app-dd-menu-enter-active {
  transition:
    opacity 0.24s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.32s cubic-bezier(0.22, 1, 0.36, 1);
}

/* 退场 */
.app-dd-menu-leave-from {
  opacity: 1;
  transform: translateY(0) scale(1);
}
.app-dd-menu-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.97);
}
.app-dd-menu-leave-active {
  transition:
    opacity 0.18s cubic-bezier(0.4, 0, 1, 1),
    transform 0.20s cubic-bezier(0.4, 0, 1, 1);
}

/* ---- 选项 ---- */
.app-dd-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 32px;
  padding: 6px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: rgb(30 41 59);
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition:
    background-color 0.18s cubic-bezier(0.22, 1, 0.36, 1),
    color 0.18s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.18s cubic-bezier(0.22, 1, 0.36, 1);
}

/* stagger 入场 */
.app-dd-menu-enter-active .app-dd-item {
  animation: app-dd-item-in 0.32s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.app-dd-menu-enter-active .app-dd-item:nth-child(1)  { animation-delay: 30ms;  }
.app-dd-menu-enter-active .app-dd-item:nth-child(2)  { animation-delay: 54ms;  }
.app-dd-menu-enter-active .app-dd-item:nth-child(3)  { animation-delay: 78ms;  }
.app-dd-menu-enter-active .app-dd-item:nth-child(4)  { animation-delay: 102ms; }
.app-dd-menu-enter-active .app-dd-item:nth-child(5)  { animation-delay: 126ms; }
.app-dd-menu-enter-active .app-dd-item:nth-child(6)  { animation-delay: 150ms; }
.app-dd-menu-enter-active .app-dd-item:nth-child(7)  { animation-delay: 170ms; }
.app-dd-menu-enter-active .app-dd-item:nth-child(8)  { animation-delay: 188ms; }
.app-dd-menu-enter-active .app-dd-item:nth-child(n + 9) { animation-delay: 204ms; }

@keyframes app-dd-item-in {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.app-dd-item:hover {
  background: rgb(241 245 249);
  color: #0f172a;
}
.app-dd-item:active {
  transform: scale(0.985);
  transition-duration: 0.08s;
}

/* active 项：淮灰底 + 加粗（Linear / Notion 风格） */
.app-dd-item.is-active {
  background: rgb(241 245 249);
  color: #0f172a;
  font-weight: 600;
}
.app-dd-item.is-active:hover {
  background: rgb(226 232 240);
}

.app-dd-item-icon {
  flex-shrink: 0;
  color: rgb(100 116 139);
}
.app-dd-item.is-active .app-dd-item-icon {
  color: #0f172a;
}

.app-dd-item-text {
  flex: 1 1 auto;
  min-width: 0;
}

.app-dd-item-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.app-dd-item.is-active .app-dd-item-label {
  font-weight: 600;
}

.app-dd-item-description {
  margin-top: 2px;
  font-size: 11px;
  font-weight: 400;
  color: rgb(148 163 184);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.app-dd-item.is-active .app-dd-item-description {
  color: rgb(100 116 139);
}

.app-dd-item-suffix {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: rgb(148 163 184);
}
.app-dd-item.is-active .app-dd-item-suffix {
  color: rgb(71 85 105);
}

.app-dd-item-check {
  flex-shrink: 0;
  margin-left: 2px;
  color: rgb(37 99 235); /* sky-600 调性色，active 项的“勾选” */
  animation: app-dd-check-pop 0.36s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes app-dd-check-pop {
  0%   { opacity: 0; transform: scale(0.4) rotate(-12deg); }
  60%  { opacity: 1; transform: scale(1.18) rotate(4deg); }
  100% { opacity: 1; transform: scale(1) rotate(0); }
}

/* ---- Badge tones ---- */
.app-dd-badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  border-radius: 999px;
  border: 1px solid;
  flex-shrink: 0;
  white-space: nowrap;
}

.app-dd-badge.tone-emerald {
  color: rgb(5 150 105);
  background: rgb(236 253 245);
  border-color: rgb(167 243 208);
}
.app-dd-badge.tone-amber {
  color: rgb(180 83 9);
  background: rgb(255 251 235);
  border-color: rgb(253 230 138);
}
.app-dd-badge.tone-sky {
  color: rgb(2 132 199);
  background: rgb(240 249 255);
  border-color: rgb(186 230 253);
}
.app-dd-badge.tone-rose {
  color: rgb(190 18 60);
  background: rgb(255 241 242);
  border-color: rgb(254 205 211);
}
.app-dd-badge.tone-violet {
  color: rgb(124 58 237);
  background: rgb(245 243 255);
  border-color: rgb(221 214 254);
}
.app-dd-badge.tone-slate {
  color: rgb(71 85 105);
  background: rgb(248 250 252);
  border-color: rgb(226 232 240);
}

/* ---- 空态 ---- */
.app-dd-empty {
  padding: 16px 12px;
  text-align: center;
  font-size: 12px;
  color: rgb(148 163 184);
}
</style>
