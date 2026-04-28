<template>
  <teleport to="body">
    <div
      v-if="visible"
      class="btp-mask"
      @click.self="close"
      @keydown.esc.stop="close"
    >
      <div
        class="btp-panel"
        :style="panelStyle"
        @click.stop
      >
        <div class="btp-search-wrap">
          <Search :size="13" :stroke-width="2.2" class="btp-search-icon" />
          <input
            ref="searchRef"
            v-model="query"
            class="btp-search"
            type="text"
            placeholder="搜索积木类型..."
            @keydown.down.prevent="moveSel(1)"
            @keydown.up.prevent="moveSel(-1)"
            @keydown.enter.prevent="commitSel"
            @keydown.esc.stop.prevent="close"
          >
        </div>

        <div v-if="!filtered.length" class="btp-empty">
          没有匹配的积木类型
        </div>

        <div
          v-for="group in groupedFiltered"
          v-else
          :key="group.key"
          class="btp-group"
        >
          <p class="btp-group-label">{{ group.label }}</p>
          <button
            v-for="item in group.items"
            :key="item.type"
            type="button"
            class="btp-item"
            :class="{ 'is-active': item.type === activeType }"
            @click="select(item.type)"
            @mouseenter="activeType = item.type"
          >
            <span class="btp-item-dot" :style="{ background: item.meta.color }" />
            <div class="btp-item-text">
              <span class="btp-item-label">{{ item.meta.label }}</span>
              <span class="btp-item-desc">{{ item.meta.description }}</span>
            </div>
          </button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import { BLOCK_TYPES, BLOCK_GROUPS } from './blockTypes.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  /** 触发按钮的 DOMRect（用于定位）。建议传 element.getBoundingClientRect() */
  anchor:  { type: Object, default: null },
  /** 'top' | 'bottom'，相对触发按钮的展开方向 */
  placement: { type: String, default: 'bottom' },
})
const emit = defineEmits(['select', 'close'])

const query = ref('')
const activeType = ref('')
const searchRef = ref(null)

const allItems = computed(() =>
  Object.entries(BLOCK_TYPES).map(([type, meta]) => ({ type, meta })),
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return allItems.value
  return allItems.value.filter(it =>
    it.meta.label.toLowerCase().includes(q)
    || it.type.toLowerCase().includes(q)
    || (it.meta.description || '').toLowerCase().includes(q),
  )
})

const groupedFiltered = computed(() => {
  const map = {}
  for (const g of BLOCK_GROUPS) map[g.key] = { ...g, items: [] }
  for (const it of filtered.value) {
    const g = it.meta.group
    if (!map[g]) map[g] = { key: g, label: g, items: [] }
    map[g].items.push(it)
  }
  return Object.values(map).filter(g => g.items.length)
})

watch(() => props.visible, (v) => {
  if (v) {
    query.value = ''
    activeType.value = filtered.value[0]?.type || ''
    nextTick(() => searchRef.value?.focus())
  }
})

watch(filtered, (list) => {
  if (!list.find(x => x.type === activeType.value)) {
    activeType.value = list[0]?.type || ''
  }
})

const panelStyle = computed(() => {
  if (!props.anchor) {
    return { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }
  }
  const r = props.anchor
  const W = 280
  const H = 360
  // 优先按 placement，超出视口再翻转
  const spaceBelow = window.innerHeight - r.bottom
  const spaceAbove = r.top
  let top
  if (props.placement === 'bottom' && spaceBelow >= H + 12) top = r.bottom + 6
  else if (props.placement === 'top' && spaceAbove >= H + 12) top = r.top - H - 6
  else if (spaceBelow >= spaceAbove) top = r.bottom + 6
  else top = r.top - H - 6

  // 水平居中于触发按钮，但不超出视口
  let left = r.left + (r.width / 2) - (W / 2)
  left = Math.max(12, Math.min(left, window.innerWidth - W - 12))
  return {
    top:  `${top}px`,
    left: `${left}px`,
    width: `${W}px`,
    maxHeight: `${H}px`,
  }
})

function close() {
  emit('close')
}

function select(type) {
  emit('select', type)
}

function moveSel(delta) {
  const list = filtered.value
  if (!list.length) return
  const idx = list.findIndex(x => x.type === activeType.value)
  const next = list[(idx + delta + list.length) % list.length]
  if (next) activeType.value = next.type
}

function commitSel() {
  if (activeType.value) select(activeType.value)
}
</script>

<style scoped>
.btp-mask {
  position: fixed;
  inset: 0;
  z-index: 100050;
  /* 不全屏遮罩，只用作 click outside 捕获 */
  background: transparent;
}
.btp-panel {
  position: fixed;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-size: 12.5px;
  animation: btp-pop 0.14s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes btp-pop {
  from { opacity: 0; transform: translateY(-4px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
.btp-search-wrap {
  position: relative;
  padding: 8px 10px 6px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.06);
}
.btp-search-icon {
  position: absolute;
  left: 18px;
  top: 50%;
  transform: translateY(-50%);
  color: rgba(29, 29, 31, 0.4);
}
.btp-search {
  width: 100%;
  padding: 6px 10px 6px 28px;
  font-size: 12.5px;
  border: 1px solid rgba(29, 29, 31, 0.1);
  border-radius: 8px;
  outline: none;
  font-family: inherit;
  color: #1d1d1f;
  background: #fafafa;
  transition: border-color 0.15s, background 0.15s;
}
.btp-search:focus {
  border-color: rgba(0, 113, 227, 0.5);
  background: #fff;
}
.btp-empty {
  padding: 24px 14px;
  text-align: center;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.4);
}
.btp-group {
  padding: 8px 6px 4px;
  overflow-y: auto;
}
.btp-group + .btp-group {
  border-top: 1px solid rgba(29, 29, 31, 0.05);
}
.btp-group-label {
  margin: 0 0 4px;
  padding: 0 8px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.4);
}
.btp-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 8px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  margin-bottom: 1px;
  transition: background 0.12s;
}
.btp-item:hover,
.btp-item.is-active {
  background: rgba(0, 113, 227, 0.08);
}
.btp-item-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.btp-item-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.btp-item-label {
  font-size: 12.5px;
  font-weight: 600;
  color: #1d1d1f;
}
.btp-item-desc {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.5);
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
