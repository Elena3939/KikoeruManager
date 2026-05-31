<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import CirclePager from './CirclePager.vue'
import WorkCard from './WorkCard.vue'
import WorkListRow from './WorkListRow.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  mode: { type: String, default: 'card', validator: value => ['card', 'list'].includes(value) },
  currentPage: { type: Number, default: 1 },
  pageSize: { type: Number, default: 10 },
  pageSizes: { type: Array, default: () => [10, 20, 50, 100] },
  selectedCodes: { type: Object, default: () => new Set() },
  flashedCodes: { type: Object, default: () => new Set() },
  imageField: { type: String, default: 'image_url' },
  cornerLabel: { type: String, default: '' },
  pagerLabel: { type: String, default: '作品' },
  emptyText: { type: String, default: '没有找到符合条件的作品' },
})

const emit = defineEmits([
  'update:currentPage',
  'update:pageSize',
  'select',
  'preview',
  'reimport',
])

const scrollRef = ref(null)
const viewportRef = ref(null)
const viewportWidth = ref(0)
const motionActive = ref(false)

let resizeObserver = null
let motionTimer = null

const safeItems = computed(() => Array.isArray(props.items) ? props.items : [])
const totalItems = computed(() => safeItems.value.length)
const normalizedPageSize = computed(() => {
  const size = Number(props.pageSize || 10)
  return Number.isFinite(size) && size > 0 ? size : 10
})
const pageCount = computed(() => Math.max(1, Math.ceil(totalItems.value / normalizedPageSize.value)))
const normalizedPage = computed(() => {
  const page = Number(props.currentPage || 1)
  if (!Number.isFinite(page)) return 1
  return Math.min(Math.max(1, page), pageCount.value)
})
const pagedItems = computed(() => {
  const start = (normalizedPage.value - 1) * normalizedPageSize.value
  return safeItems.value.slice(start, start + normalizedPageSize.value)
})
const isCardMode = computed(() => props.mode === 'card')
const gridGap = computed(() => isCardMode.value ? 10 : 6)
const columnCount = computed(() => {
  if (!isCardMode.value) return 1
  const width = Number(viewportWidth.value || 0)
  if (width <= 0) return 1
  const minCardWidth = width <= 640 ? 152 : 156
  return Math.max(1, Math.floor((width + gridGap.value) / (minCardWidth + gridGap.value)))
})
const columnWidth = computed(() => {
  if (!isCardMode.value) return Number(viewportWidth.value || 0)
  const width = Number(viewportWidth.value || 0)
  const columns = Math.max(1, columnCount.value)
  if (width <= 0) return 156
  return Math.max(152, (width - gridGap.value * (columns - 1)) / columns)
})
const rowCount = computed(() => {
  if (!pagedItems.value.length) return 0
  return Math.ceil(pagedItems.value.length / columnCount.value)
})
const usePlainRender = computed(() => viewportWidth.value > 0 && viewportWidth.value <= 640)
const virtualRowHeight = computed(() => {
  if (!isCardMode.value) return viewportWidth.value <= 640 ? 58 : 60
  const coverHeight = Math.round(columnWidth.value * 0.75)
  const bodyHeight = viewportWidth.value <= 640 ? 150 : 164
  return coverHeight + bodyHeight + gridGap.value
})
const virtualOverscan = computed(() => isCardMode.value ? 2 : 10)
const gridTemplateColumns = computed(() => `repeat(${columnCount.value}, minmax(0, 1fr))`)

const rowVirtualizer = useVirtualizer(computed(() => ({
  count: rowCount.value,
  getScrollElement: () => scrollRef.value,
  estimateSize: () => virtualRowHeight.value,
  overscan: virtualOverscan.value,
})))

const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const virtualCanvasStyle = computed(() => ({
  height: `${rowVirtualizer.value.getTotalSize()}px`,
}))
const currentPageModel = computed({
  get: () => normalizedPage.value,
  set: value => {
    const next = Math.min(Math.max(1, Number(value || 1)), pageCount.value)
    if (next !== props.currentPage) emit('update:currentPage', next)
  },
})
const pageSizeModel = computed({
  get: () => normalizedPageSize.value,
  set: value => {
    const next = Number(value)
    if (!Number.isFinite(next) || next <= 0 || next === props.pageSize) return
    emit('update:pageSize', next)
    emit('update:currentPage', 1)
  },
})

function updateViewportWidth() {
  const el = scrollRef.value || viewportRef.value
  viewportWidth.value = Math.max(0, Math.round(el?.clientWidth || 0))
}

function itemKey(item, fallbackIndex) {
  return String(
    item?.canonical_rjcode ||
    item?.source_compare?.work_rjcode ||
    item?.rjcode ||
    fallbackIndex
  )
}

function isSelected(item) {
  const code = item?.canonical_rjcode
  return Boolean(code && props.selectedCodes?.has?.(code))
}

function isFlashed(item) {
  const code = item?.canonical_rjcode
  return Boolean(code && props.flashedCodes?.has?.(code))
}

function getRowItems(rowIndex) {
  const start = rowIndex * columnCount.value
  return pagedItems.value
    .slice(start, start + columnCount.value)
    .map((item, offset) => ({
      item,
      absoluteIndex: start + offset,
      columnIndex: offset,
      key: itemKey(item, start + offset),
    }))
}

function triggerViewportMotion() {
  motionActive.value = false
  if (motionTimer) {
    window.clearTimeout(motionTimer)
    motionTimer = null
  }
  requestAnimationFrame(() => {
    motionActive.value = true
    motionTimer = window.setTimeout(() => {
      motionActive.value = false
      motionTimer = null
    }, 360)
  })
}

function scrollToTop() {
  nextTick(() => {
    rowVirtualizer.value.scrollToOffset(0)
    rowVirtualizer.value.measure()
  })
}

watch(pageCount, (count) => {
  if (props.currentPage > count) emit('update:currentPage', count)
})

watch(
  () => [props.mode, props.currentPage, props.pageSize, columnCount.value, totalItems.value].join(':'),
  () => {
    scrollToTop()
    triggerViewportMotion()
  },
)

watch(virtualRowHeight, () => {
  nextTick(() => rowVirtualizer.value.measure())
})

onMounted(() => {
  updateViewportWidth()
  triggerViewportMotion()
  resizeObserver = new ResizeObserver(() => {
    updateViewportWidth()
    nextTick(() => rowVirtualizer.value.measure())
  })
  if (scrollRef.value) resizeObserver.observe(scrollRef.value)
})

onBeforeUnmount(() => {
  if (motionTimer) {
    window.clearTimeout(motionTimer)
    motionTimer = null
  }
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <section ref="viewportRef" class="circle-work-viewport" :class="[`is-${mode}`]">
    <div v-if="!totalItems" class="circle-work-empty">
      <slot name="empty">
        <span>{{ emptyText }}</span>
      </slot>
    </div>
    <template v-else>
      <div v-if="usePlainRender" class="circle-work-plain" :class="[`is-${mode}`]" :style="{ gridTemplateColumns }">
        <div
          v-for="(item, index) in pagedItems"
          :key="itemKey(item, index)"
          class="circle-work-plain-cell"
          :class="[`is-${mode}`, { 'is-motion-active': motionActive }]"
          :style="{ '--cell-index': index % Math.max(1, columnCount) }"
        >
          <WorkCard
            v-if="mode === 'card'"
            :item="item"
            :card-index="0"
            :selected="isSelected(item)"
            :status-flash="isFlashed(item)"
            :corner-label="cornerLabel"
            @select="emit('select', $event)"
            @preview="emit('preview', $event)"
            @reimport="emit('reimport', $event)"
          />
          <WorkListRow
            v-else
            :item="item"
            :row-index="0"
            :selected="isSelected(item)"
            :status-flash="isFlashed(item)"
            :image-field="imageField"
            :corner-label="cornerLabel"
            @select="emit('select', $event)"
            @preview="emit('preview', $event)"
            @reimport="emit('reimport', $event)"
          />
        </div>
      </div>

      <div v-else ref="scrollRef" class="circle-work-scroll">
        <div class="circle-work-virtual-canvas" :style="virtualCanvasStyle">
          <div
            v-for="virtualRow in virtualRows"
            :key="virtualRow.key"
            class="circle-work-virtual-row"
            :class="[`is-${mode}`]"
            :style="{
              height: `${virtualRow.size}px`,
              transform: `translateY(${virtualRow.start}px)`,
              gridTemplateColumns,
              gap: `${gridGap}px`,
            }"
          >
            <div
              v-for="cell in getRowItems(virtualRow.index)"
              :key="cell.key"
              class="circle-work-virtual-cell"
              :class="[`is-${mode}`, { 'is-motion-active': motionActive }]"
              :style="{ '--cell-index': cell.columnIndex }"
            >
              <WorkCard
                v-if="mode === 'card'"
                :item="cell.item"
                :card-index="0"
                :selected="isSelected(cell.item)"
                :status-flash="isFlashed(cell.item)"
                :corner-label="cornerLabel"
                @select="emit('select', $event)"
                @preview="emit('preview', $event)"
                @reimport="emit('reimport', $event)"
              />
              <WorkListRow
                v-else
                :item="cell.item"
                :row-index="0"
                :selected="isSelected(cell.item)"
                :status-flash="isFlashed(cell.item)"
                :image-field="imageField"
                :corner-label="cornerLabel"
                @select="emit('select', $event)"
                @preview="emit('preview', $event)"
                @reimport="emit('reimport', $event)"
              />
            </div>
          </div>
        </div>
      </div>

      <div class="works-pager">
        <CirclePager
          v-model:current-page="currentPageModel"
          v-model:page-size="pageSizeModel"
          :page-sizes="pageSizes"
          :total="totalItems"
          :label="pagerLabel"
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
.circle-work-viewport {
  position: relative;
  z-index: 0;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 10px;
}

.circle-work-scroll {
  flex: 1;
  min-height: 280px;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: none;
  -ms-overflow-style: none;
  contain: layout paint;
}

.circle-work-scroll::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

.circle-work-virtual-canvas {
  position: relative;
  width: 100%;
}

.circle-work-virtual-row {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  display: grid;
  box-sizing: border-box;
}

.circle-work-virtual-row.is-card {
  align-items: stretch;
}

.circle-work-virtual-row.is-list {
  display: block;
}

.circle-work-virtual-cell,
.circle-work-plain-cell {
  min-width: 0;
  min-height: 0;
}

.circle-work-virtual-cell.is-motion-active,
.circle-work-plain-cell.is-motion-active {
  animation: viewportCellEntrance 260ms cubic-bezier(.22, 1, .36, 1) both;
  animation-delay: calc(var(--cell-index, 0) * 24ms);
}

.circle-work-virtual-cell.is-card {
  height: calc(100% - 10px);
}

.circle-work-virtual-cell.is-list {
  height: calc(100% - 6px);
}

.circle-work-plain {
  flex: 0 0 auto;
  min-height: 0;
}

.circle-work-plain.is-card {
  display: grid;
  gap: 8px;
  align-items: stretch;
}

.circle-work-plain.is-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.circle-work-plain-cell.is-card {
  min-height: 278px;
}

.circle-work-viewport :deep(.work-card) {
  height: 100%;
  animation: none;
}

.circle-work-viewport :deep(.work-actions) {
  opacity: 0;
  transform: translateY(3px);
  pointer-events: none;
}

.circle-work-viewport :deep(.work-card:hover .work-actions) {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

.circle-work-viewport :deep(.work-list-row) {
  height: 100%;
  box-sizing: border-box;
  animation: none;
}

.circle-work-empty {
  flex: 1;
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--circle-border-soft, rgba(203, 213, 225, 0.88));
  border-radius: 16px;
  background: var(--circle-surface-muted, rgba(255, 255, 255, 0.54));
  color: var(--circle-text-muted, #94a3b8);
  font-size: 13px;
  font-weight: 700;
}

.works-pager {
  display: flex;
  justify-content: flex-end;
  flex-shrink: 0;
  margin-top: auto;
  padding-top: 16px;
}

@keyframes viewportCellEntrance {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.985);
    filter: saturate(0.92);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: saturate(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .circle-work-virtual-cell.is-motion-active {
    animation: none;
  }
}

@media (max-width: 760px) {
  .works-pager {
    justify-content: center;
  }
}

@media (max-width: 420px) {
  .circle-work-scroll {
    min-height: 330px;
  }
}

@media (max-width: 640px) {
  .circle-work-viewport :deep(.work-actions) {
    opacity: 1;
    transform: translateY(0);
    pointer-events: auto;
  }
}
</style>
