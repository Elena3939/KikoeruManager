<template>
  <section
    class="dashboard-archive flex min-h-0 flex-1 flex-col rounded-[14px] border border-slate-200/80 bg-white p-3.5 shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] transition-shadow duration-500 hover:shadow-[0_6px_16px_-10px_rgba(15,23,42,0.14)]"
    data-section="dashboard-archive"
  >
    <header class="dash-archive-head flex flex-shrink-0 items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2.5">
        <Archive :size="20" :stroke-width="2" class="flex-shrink-0 text-slate-700" />
        <div class="min-w-0 leading-tight">
          <h2 class="m-0 text-[14px] font-bold tracking-tight text-slate-900">归档中心</h2>
          <p class="m-0 mt-0.5 text-[11.5px] text-slate-500">
            {{ listType === 'queue' ? queueSummary : archives.length ? `共 ${archives.length} 条记录` : '暂无归档记录' }}
          </p>
        </div>
      </div>
      <StatefulButton
        unstyled
        class="dash-archive-refresh-btn group"
        :show-default-icons="false"
        :disabled="currentLoading"
        :title="listType === 'queue' ? '刷新压缩包队列' : '刷新任务归档'"
        :aria-label="listType === 'queue' ? '刷新压缩包队列' : '刷新任务归档'"
        @click="refreshCurrentList"
      >
        <template #prefix="{ state }">
          <component
            :is="state === 'success' ? Check : state === 'error' ? AlertCircle : RefreshCw"
            :size="14"
            :stroke-width="2.2"
            :class="state === 'loading' || currentLoading ? 'animate-spin' : 'transition-transform duration-300 group-hover:rotate-180 group-hover:scale-110'"
          />
        </template>
      </StatefulButton>
    </header>

    <div class="dash-archive-list-types mt-3" role="group" aria-label="归档列表类型">
      <button
        v-for="type in listTypes"
        :key="type.key"
        type="button"
        class="dash-archive-list-type"
        :class="{ 'is-active': listType === type.key }"
        :aria-pressed="listType === type.key"
        @click="listType = type.key"
      >
        <component :is="type.icon" :size="14" />
        {{ type.label }}
      </button>
    </div>

    <DeferredArchiveQueue v-show="listType === 'queue'" ref="queueRef" embedded />

    <!-- 搜索 + 类型筛选：合成一个紧凑筛选条，减少最近归档面板的纵向占用 -->
    <div v-show="listType === 'history'" class="dash-archive-filterbar mt-2">
      <div class="dash-archive-search">
        <AppDropdown
          :model-value="domainFilter"
          :options="domainDropdownOptions"
          class="dash-archive-search-filter-dd"
          menu-class="dash-archive-domain-dd-menu"
          :menu-min-width="220"
          :show-trigger-badge="false"
          @update:model-value="$emit('update:domainFilter', $event)"
        >
          <template #trigger="{ open, selected, toggle, triggerText }">
            <button
              type="button"
              class="dash-archive-search-filter-trigger"
              :class="{ 'is-open': open, 'is-filtered': domainFilter !== 'all' }"
              :title="`归档类型：${selected?.label || triggerText}`"
              aria-label="选择归档类型"
              @click="toggle"
            >
              <Search :size="14" :stroke-width="2.25" class="dash-archive-search-filter-icon" />
              <ChevronDown
                :size="10"
                :stroke-width="2.6"
                class="dash-archive-search-filter-caret"
                :class="{ 'is-open': open }"
              />
            </button>
          </template>
          <template #option="{ option, isActive }">
            <span class="dash-archive-domain-option" :class="{ 'is-active': isActive }">
              <span class="dash-archive-domain-option-label">{{ option.label }}</span>
              <span v-if="option.count > 0" class="dash-archive-domain-option-count">{{ option.count }}</span>
            </span>
          </template>
        </AppDropdown>
        <input
          class="dash-archive-search-input"
          :value="searchQuery"
          type="search"
          placeholder="搜索 RJ / 文件名"
          @input="$emit('update:searchQuery', $event.target.value)"
        />
        <button
          v-if="searchQuery"
          type="button"
          class="dash-archive-search-clear"
          title="清空搜索"
          @click="$emit('update:searchQuery', '')"
        >
          <XCircle :size="13" :stroke-width="2.2" />
        </button>
      </div>
    </div>

    <!-- 列表高度由布局确定，只渲染当前页，不产生内部滚动。 -->
    <div
      v-if="filteredArchives.length"
      v-show="listType === 'history'"
      ref="listRef"
      class="dash-archive-list mt-2 min-h-0 gap-2"
      :style="{ gridTemplateRows: `repeat(${pageSize}, minmax(0, 1fr))` }"
    >
      <article
        v-for="archive in pagedArchives"
        :key="archive.id"
        class="dash-archive-row group grid grid-cols-[22px_minmax(0,1fr)_auto] items-start gap-2.5 rounded-[10px] border border-slate-100 bg-white p-2.5 transition-colors duration-300 hover:border-slate-200 hover:bg-slate-50/50"
      >
        <component
          :is="getMeta(archive).icon"
          :size="18"
          :stroke-width="2"
          class="mt-0.5 flex-shrink-0 transition-transform duration-300 group-hover:scale-110 group-hover:rotate-[-6deg]"
          :class="getMeta(archive).chipIcon || 'text-slate-500'"
        />

        <div class="min-w-0">
          <!-- 解压入库只显示压缩包名，其它类型保留右侧 RJ 信息。 -->
          <div class="flex min-w-0 items-start gap-2">
            <div class="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
              <h3 :title="archive.filename" class="m-0 min-w-0 truncate text-[13px] font-semibold leading-tight text-slate-900">{{ archive.filename }}</h3>
            </div>
            <div class="flex flex-shrink-0 flex-col items-end gap-0.5">
              <span
                v-if="archive.rjcode && getMeta(archive).key !== 'import'"
                class="dash-archive-meta-rj"
              >{{ archive.rjcode }}</span>
              <span class="dash-archive-meta-time">{{ formatDate(archive.processed_at) }}</span>
            </div>
          </div>
          <!-- 标签行：domain（同色系无 icon，与左侧色块呼应） + status（留 icon） + 文件大小 -->
          <div class="mt-1.5 flex items-center justify-between gap-1.5">
            <div class="flex flex-wrap items-center gap-1.5">
              <span
                class="dash-archive-domain-chip"
                :class="`dash-archive-domain-chip--${getMeta(archive).key || 'default'}`"
              >
                {{ getMeta(archive).label }}
              </span>
              <span
                class="dash-archive-status-chip"
                :class="`dash-archive-status-chip--${getStatusMeta(archive).key}`"
              >
                <component :is="statusIcon(getStatusMeta(archive).key)" :size="11" :stroke-width="2" :class="statusIconColor(getStatusMeta(archive).key)" />
                {{ getStatusMeta(archive).label }}
              </span>
              <span v-if="archiveVolumeCount(archive) > 1" class="dash-archive-volume-chip">{{ archiveVolumeCount(archive) }} 分卷</span>
            </div>
            <span v-if="archive.file_size" class="dash-archive-meta-size">{{ formatFileSize(archive.file_size) }}</span>
          </div>
        </div>

        <button
          v-if="archive.source === 'processed_archive' && getStatusMeta(archive).key === 'failed'"
          type="button"
          class="group/btn inline-flex h-7 w-7 cursor-pointer items-center justify-center rounded-[7px] border border-slate-300 bg-slate-50 text-slate-600 shadow-[0_1px_0_rgba(15,23,42,0.04),inset_0_1px_0_rgba(255,255,255,0.8)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-110 hover:border-slate-400 hover:bg-white hover:text-slate-900 hover:shadow-[0_4px_10px_-4px_rgba(15,23,42,0.18)] active:scale-90 disabled:pointer-events-none disabled:opacity-50"
          :disabled="reprocessingId === archive.id"
          title="重新解压"
          @click="$emit('reprocess', archive.id)"
        >
          <RotateCcw
            :size="13"
            :stroke-width="2.4"
            :class="reprocessingId === archive.id ? 'animate-spin' : 'transition-transform duration-500 group-hover/btn:-rotate-180'"
          />
        </button>
      </article>
    </div>

    <div v-else v-show="listType === 'history'" class="mt-3 flex flex-1 items-center justify-center">
      <AppEmptyState description="暂无归档记录" size="default" />
    </div>

    <footer v-if="listType === 'history' && filteredArchives.length" class="dash-archive-pager">
      <span>共 {{ filteredArchives.length }} 条</span>
      <div class="flex items-center gap-1">
        <button type="button" class="dash-archive-page-btn" aria-label="上一页" :disabled="currentPage <= 1" @click="currentPage--">
          <ChevronLeft :size="12" />
        </button>
        <span class="dash-archive-page-number">{{ currentPage }} / {{ totalPages }}</span>
        <button type="button" class="dash-archive-page-btn" aria-label="下一页" :disabled="currentPage >= totalPages" @click="currentPage++">
          <ChevronRight :size="12" />
        </button>
      </div>
    </footer>
  </section>
</template>

<script setup>
import {
  AlertCircle,
  Archive,
  Activity,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileArchive,
  MinusCircle,
  PauseCircle,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  XCircle,
} from 'lucide-vue-next'
import { computed, onBeforeUnmount, onUpdated, ref, watch } from 'vue'
import AppDropdown from '../common/AppDropdown.vue'
import AppEmptyState from '../common/AppEmptyState.vue'
import StatefulButton from '../ui/stateful-button.vue'
import DeferredArchiveQueue from './DeferredArchiveQueue.vue'

const props = defineProps({
  archives: { type: Array, default: () => [] },
  filteredArchives: { type: Array, default: () => [] },
  tabs: { type: Array, default: () => [] },
  domainFilter: { type: String, default: 'all' },
  searchQuery: { type: String, default: '' },
  archivesLoading: { type: Boolean, default: false },
  reprocessingId: { type: [String, Number, null], default: null },
  getMeta: { type: Function, required: true },
  getStatusMeta: { type: Function, required: true },
  formatDate: { type: Function, required: true },
  formatFileSize: { type: Function, required: true },
  refreshArchives: { type: Function, required: true },
})

defineEmits(['reprocess', 'update:searchQuery', 'update:domainFilter'])

const listType = ref('queue')
const queueRef = ref(null)
const listRef = ref(null)
const currentPage = ref(1)
const pageSize = ref(10)
const totalPages = computed(() => Math.max(1, Math.ceil(props.filteredArchives.length / pageSize.value)))
const pagedArchives = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return props.filteredArchives.slice(start, start + pageSize.value)
})

// 80px 卡片和 8px 间距是布局约定。仅读取固定列表区高度，
// 在浏览器绘制前确定页容量，不遍历卡片、不读取行高、不延时补行。
function updatePageSize() {
  if (listType.value !== 'history') return
  const height = listRef.value?.clientHeight || 0
  const size = window.innerWidth <= 1024 || !height ? 10 : Math.max(1, Math.floor((height + 8) / 88))
  if (pageSize.value !== size) {
    pageSize.value = size
    currentPage.value = Math.min(currentPage.value, totalPages.value)
  }
}
let listObserver
watch(listRef, (list) => {
  listObserver?.disconnect()
  if (list) {
    listObserver = new ResizeObserver(updatePageSize)
    listObserver.observe(list)
    updatePageSize()
  }
}, { flush: 'post' })
onUpdated(updatePageSize)
watch(() => `${props.searchQuery}|${props.domainFilter}`, () => { currentPage.value = 1 })
watch(totalPages, (count) => { currentPage.value = Math.min(currentPage.value, count) })
onBeforeUnmount(() => listObserver?.disconnect())
const listTypes = [
  { key: 'queue', label: '压缩包队列', icon: FileArchive },
  { key: 'history', label: '任务归档', icon: Archive },
]
const queueSummary = computed(() => {
  const data = queueRef.value?.data
  return `${data?.pending_count || 0} 项待归档 · ${data?.counts_by_status?.waiting_retry || 0} 项等待重试`
})
const currentLoading = computed(() => listType.value === 'queue' ? queueRef.value?.loading : props.archivesLoading)

function refreshCurrentList() {
  return listType.value === 'queue' ? queueRef.value?.refresh() : props.refreshArchives()
}

const domainDropdownOptions = computed(() =>
  props.tabs.map((tab) => ({
    value: tab.key,
    label: tab.label,
    count: Number(tab.count) || 0,
    suffix: tab.count > 0 ? String(tab.count) : '',
  })),
)

function archiveVolumeCount(archive) {
  const directCount = Number(archive?.volume_count ?? archive?.volumeCount ?? archive?.volumes_count)
  if (Number.isFinite(directCount) && directCount > 1) return Math.floor(directCount)

  const volumes = Array.isArray(archive?.volumes) ? archive.volumes : []
  if (volumes.length > 1) return volumes.length

  return 1
}

const STATUS_ICON = {
  completed: Sparkles,
  partial_failed: AlertCircle,
  failed: XCircle,
  cancelled: MinusCircle,
  processing: Activity,
  pending: PauseCircle,
  unknown: Activity,
}

function statusIcon(key) {
  return STATUS_ICON[key] || Activity
}

function statusIconColor(key) {
  if (key === 'completed') return 'text-emerald-600'
  if (key === 'partial_failed') return 'text-amber-600'
  if (key === 'failed') return 'text-rose-600'
  if (key === 'cancelled') return 'text-slate-500'
  if (key === 'processing') return 'text-amber-600'
  if (key === 'pending') return 'text-slate-500'
  return 'text-slate-500'
}

</script>

<style scoped>
.dash-archive-pager {
  display: flex;
  flex: 0 0 36px;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  border-top: 1px solid var(--km-dark-border, #e2e8f0);
  font-size: 11px;
}
.dash-archive-page-btn {
  display: inline-flex;
  width: 24px;
  height: 24px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--km-dark-border, #e2e8f0);
  border-radius: 7px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-page-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
}
.dash-archive-page-btn:hover svg {
  transform: rotate(-6deg);
}
.dash-archive-page-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.dash-archive-page-btn:disabled {
  opacity: 0.35;
  cursor: default;
}
.dash-archive-page-number {
  min-width: 48px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.dash-archive-list-types {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  flex-shrink: 0;
  gap: 12px;
}
.dash-archive-list-type {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 0;
  min-height: 36px;
  padding: 6px 4px 10px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: rgb(100 116 139);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-list-type::after {
  position: absolute;
  bottom: 0;
  left: calc(50% - 12px);
  width: 24px;
  height: 2px;
  border-radius: 1px;
  background: currentColor;
  content: '';
  opacity: 0;
  transform: scaleX(0.5);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-list-type.is-active {
  color: rgb(15 23 42);
}
.dash-archive-list-type.is-active::after {
  opacity: 1;
  transform: scaleX(1);
}
.dash-archive-list-type:hover {
  transform: translateY(-2px) scale(1.02);
  color: rgb(15 23 42);
}
.dash-archive-list-type:active {
  transform: scale(0.96);
}
.dash-archive-list-type svg {
  flex-shrink: 0;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-list-type:hover svg {
  transform: rotate(-6deg);
}
.dash-archive-list {
  display: grid;
  flex: 1 1 0%;
  overflow: hidden;
}
.dash-archive-row {
  min-width: 0;
  min-height: 0;
  align-content: center;
}
@media (max-width: 1024px) {
  .dash-archive-list {
    display: flex;
    flex: 0 0 auto;
    flex-direction: column;
  }
  .dash-archive-row {
    min-height: 80px;
  }
}
.dash-archive-row h3 {
  display: block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dash-archive-row > div {
  min-width: 0;
}
.dash-archive-meta-rj,
.dash-archive-meta-time {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 刷新按钮 */
.dash-archive-refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  min-height: 28px;
  padding: 0;
  border: 1px solid rgba(148, 163, 184, 0.48);
  border-radius: 8px;
  color: rgb(71 85 105);
  background: rgba(255, 255, 255, 0.95);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-refresh-btn:hover {
  color: rgb(15 23 42);
  border-color: rgba(100, 116, 139, 0.62);
  background: rgb(255 255 255);
  transform: translateY(-2px) scale(1.02);
}
.dash-archive-refresh-btn:active {
  transform: scale(0.96);
}
.dash-archive-refresh-btn:disabled {
  cursor: wait;
  opacity: 0.55;
  transform: none;
}

.dash-archive-filterbar {
  display: block;
  box-sizing: border-box;
  height: 34px;
  min-height: 34px;
  padding: 2px;
  border: 1px solid rgb(226 232 240);
  border-radius: 8px;
  background: rgb(248 250 252);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.86),
    0 1px 2px rgba(15, 23, 42, 0.03);
  flex-shrink: 0;
  transition:
    border-color 0.3s ease,
    box-shadow 0.3s ease,
    background-color 0.3s ease;
}
.dash-archive-filterbar:hover {
  border-color: rgb(203 213 225);
  background: rgb(255 255 255);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.92);
}
.dash-archive-filterbar:focus-within {
  border-color: rgb(148 163 184);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    0 0 0 2px rgba(148, 163, 184, 0.14);
}

/* 搜索区内嵌在筛选条内，避免上下两个独立输入框抢空间 */
.dash-archive-search {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 20px;
  align-items: center;
  min-width: 0;
  height: 28px;
  padding: 0 4px 0 0;
}

.dash-archive-search-filter-dd {
  display: block;
  width: 28px;
  height: 28px;
}
.dash-archive-search-filter-dd :deep(.app-dd-trigger-anchor) {
  display: block;
  width: 28px;
  height: 28px;
}
.dash-archive-search-filter-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin: 1px 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: rgb(100 116 139);
  cursor: pointer;
  transition: color 0.2s ease, transform 0.2s ease;
}
.dash-archive-search-filter-trigger:hover {
  color: rgb(30 41 59);
  background: transparent;
}
.dash-archive-search-filter-trigger.is-open {
  color: rgb(15 23 42);
  background: transparent;
  transform: none;
}
.dash-archive-search-filter-trigger.is-filtered {
  color: rgb(30 41 59);
}
.dash-archive-search-filter-trigger.is-filtered::after {
  content: '';
  position: absolute;
  right: 2px;
  top: 5px;
  width: 4px;
  height: 4px;
  border-radius: 999px;
  background: rgb(37 99 235);
  box-shadow: 0 0 0 2px rgb(248 250 252);
}
.dash-archive-search-filter-trigger:active {
  transform: scale(0.94);
}
.dash-archive-search-filter-icon {
  flex-shrink: 0;
}
.dash-archive-search-filter-caret {
  position: absolute;
  right: 1px;
  bottom: 4px;
  color: currentColor;
  opacity: 0.74;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-search-filter-caret.is-open {
  transform: rotate(180deg);
}
.dash-archive-search-input {
  min-width: 0;
  height: 24px;
  border: 0;
  outline: none;
  background: transparent;
  appearance: none;
  -webkit-appearance: none;
  font-size: 13px;
  color: rgb(30 41 59);
}
.dash-archive-search-input::-webkit-search-decoration,
.dash-archive-search-input::-webkit-search-cancel-button {
  display: none;
}
.dash-archive-search-input::placeholder {
  color: rgb(148 163 184);
}
.dash-archive-search-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: rgb(148 163 184);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-archive-search-clear:hover {
  transform: translateY(-2px) scale(1.02);
  background: rgb(241 245 249);
  color: rgb(71 85 105);
}
.dash-archive-search-clear:active {
  transform: scale(0.96);
}

:global(.dash-archive-domain-dd-menu .app-dd-item) {
  position: relative;
  min-height: 34px;
  border-radius: 9px;
  padding: 0;
  overflow: hidden;
}
:global(.dash-archive-domain-dd-menu .app-dd-item.is-active) {
  background: transparent;
}
:global(.dash-archive-domain-dd-menu .dash-archive-domain-option) {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 34px;
  padding: 0 10px;
  border-radius: 9px;
  color: rgb(51 65 85);
  transition: background-color 0.18s ease, color 0.18s ease;
}
:global(.dash-archive-domain-dd-menu .app-dd-item:hover .dash-archive-domain-option) {
  background: rgb(241 245 249);
  color: rgb(15 23 42);
}
:global(.dash-archive-domain-dd-menu .dash-archive-domain-option.is-active) {
  background: rgb(226 232 240);
  color: rgb(15 23 42);
}
:global(.dash-archive-domain-dd-menu .dash-archive-domain-option-label) {
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
}
:global(.dash-archive-domain-dd-menu .dash-archive-domain-option.is-active .dash-archive-domain-option-label) {
  font-weight: 800;
}
:global(.dash-archive-domain-dd-menu .dash-archive-domain-option-count) {
  margin-left: auto;
  color: rgb(100 116 139);
  font-size: 12px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
:global(.dash-archive-domain-dd-menu .dash-archive-domain-option.is-active .dash-archive-domain-option-count) {
  color: rgb(30 41 59);
}

.dash-archive-domain-chip,
.dash-archive-volume-chip {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.dash-archive-domain-chip--import {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.18);
  color: rgb(146 64 14);
}

.dash-archive-domain-chip--existing_folder,
.dash-archive-domain-chip--rj_subtitle {
  background: rgba(20, 184, 166, 0.12);
  border-color: rgba(20, 184, 166, 0.18);
  color: rgb(15 118 110);
}

.dash-archive-domain-chip--subtitle_import {
  background: rgba(168, 85, 247, 0.12);
  border-color: rgba(168, 85, 247, 0.18);
  color: rgb(126 34 206);
}

.dash-archive-domain-chip--asmr_sync,
.dash-archive-domain-chip--circle_completion {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.18);
  color: rgb(4 120 87);
}

.dash-archive-domain-chip--http_download {
  background: rgba(249, 115, 22, 0.12);
  border-color: rgba(249, 115, 22, 0.18);
  color: rgb(194 65 12);
}

.dash-archive-domain-chip--baidu_netdisk,
.dash-archive-domain-chip--upload,
.dash-archive-domain-chip--system,
.dash-archive-domain-chip--default,
.dash-archive-volume-chip {
  background: rgba(100, 116, 139, 0.12);
  border-color: rgba(100, 116, 139, 0.18);
  color: rgb(51 65 85);
}

.dash-archive-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 20px;
  padding: 0 6px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.dash-archive-status-chip--completed,
.dash-archive-status-chip--success,
.dash-archive-status-chip--finished {
  background: rgba(16, 185, 129, 0.12);
  color: rgb(4 120 87);
}

.dash-archive-status-chip--partial_failed {
  background: rgba(245, 158, 11, 0.12);
  color: rgb(180 83 9);
}

.dash-archive-status-chip--failed {
  background: rgba(244, 63, 94, 0.12);
  color: rgb(190 18 60);
}

.dash-archive-status-chip--cancelled,
.dash-archive-status-chip--canceled {
  background: rgba(148, 163, 184, 0.16);
  color: rgb(71 85 105);
}

.dash-archive-status-chip--processing,
.dash-archive-status-chip--running {
  background: rgba(245, 158, 11, 0.12);
  color: rgb(180 83 9);
}

.dash-archive-status-chip--pending,
.dash-archive-status-chip--waiting_manual,
.dash-archive-status-chip--waiting_retry {
  background: rgba(100, 116, 139, 0.12);
  color: rgb(71 85 105);
}

.dash-archive-status-chip--default {
  background: rgba(148, 163, 184, 0.12);
  color: rgb(71 85 105);
}

.dash-archive-meta-rj {
  color: rgb(71 85 105);
  font-size: 11px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.dash-archive-meta-time,
.dash-archive-meta-size {
  color: rgb(71 85 105);
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.dash-archive-meta-size {
  flex-shrink: 0;
}

.dash-archive-platform-icon {
  width: 18px;
  height: 18px;
  object-fit: contain;
  border-radius: 3px;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-refresh-btn {
  background: var(--km-dark-surface-soft) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-refresh-btn:hover {
  background: var(--km-dark-surface-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: #ffffff !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-filterbar {
  background: rgba(255, 255, 255, 0.045) !important;
  border-color: var(--km-dark-border) !important;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.055),
    0 1px 2px rgba(0, 0, 0, 0.18) !important;
  color-scheme: dark;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-filterbar:focus-within {
  border-color: var(--km-dark-border-strong) !important;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.07),
    0 0 0 2px rgba(255, 255, 255, 0.055) !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-search {
  background: transparent !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-search-input {
  background: transparent !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
  -webkit-text-fill-color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-search-input::placeholder {
  color: rgba(255, 255, 255, 0.48) !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-search-clear {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-search-clear:hover {
  background: var(--km-dark-surface-hover) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger:hover,
html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger.is-open {
  background: transparent !important;
  border-color: transparent !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger.is-filtered {
  color: var(--km-dark-text-strong) !important;
}

html.dark .dashboard-archive .dash-archive-search-filter-trigger,
html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger {
  color: rgba(226, 232, 240, 0.78) !important;
}

html.dark .dashboard-archive .dash-archive-search-filter-trigger:hover,
html.dark .dashboard-archive .dash-archive-search-filter-trigger.is-open,
html.dark .dashboard-archive .dash-archive-search-filter-trigger.is-filtered,
html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger:hover,
html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger.is-open,
html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger.is-filtered {
  background: transparent !important;
  border-color: transparent !important;
  color: #f8fafc !important;
}

html.dark .dashboard-archive .dash-archive-search-filter-trigger.is-filtered::after,
html.kikoerumanager-dark .dashboard-archive .dash-archive-search-filter-trigger.is-filtered::after {
  background: #93c5fd !important;
  box-shadow: 0 0 0 2px rgba(24, 25, 29, 0.98) !important;
}

:global(html.dark .dash-archive-domain-dd-menu .dash-archive-domain-option),
:global(html.kikoerumanager-dark .dash-archive-domain-dd-menu .dash-archive-domain-option) {
  color: rgba(244, 244, 245, 0.82) !important;
}

:global(html.dark .dash-archive-domain-dd-menu .app-dd-item:hover .dash-archive-domain-option),
:global(html.kikoerumanager-dark .dash-archive-domain-dd-menu .app-dd-item:hover .dash-archive-domain-option) {
  background: rgba(255, 255, 255, 0.075) !important;
  color: #ffffff !important;
}

:global(html.dark .dash-archive-domain-dd-menu .dash-archive-domain-option.is-active),
:global(html.kikoerumanager-dark .dash-archive-domain-dd-menu .dash-archive-domain-option.is-active) {
  background: rgba(255, 255, 255, 0.105) !important;
  color: #ffffff !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
}

:global(html.dark .dash-archive-domain-dd-menu .dash-archive-domain-option-count),
:global(html.kikoerumanager-dark .dash-archive-domain-dd-menu .dash-archive-domain-option-count),
:global(html.dark .dash-archive-domain-dd-menu .dash-archive-domain-option.is-active .dash-archive-domain-option-count),
:global(html.kikoerumanager-dark .dash-archive-domain-dd-menu .dash-archive-domain-option.is-active .dash-archive-domain-option-count) {
  color: rgba(226, 232, 240, 0.8) !important;
}


html.kikoerumanager-dark .dashboard-archive .dash-archive-domain-chip,
html.kikoerumanager-dark .dashboard-archive .dash-archive-volume-chip {
  background: rgba(255, 255, 255, 0.07) !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: #f8fafc !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-domain-chip--import {
  background: rgba(245, 158, 11, 0.16) !important;
  border-color: rgba(245, 158, 11, 0.22) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-domain-chip--existing_folder,
html.kikoerumanager-dark .dashboard-archive .dash-archive-domain-chip--rj_subtitle {
  background: rgba(20, 184, 166, 0.14) !important;
  border-color: rgba(45, 212, 191, 0.2) !important;
  color: #ccfbf1 !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-domain-chip--subtitle_import {
  background: rgba(168, 85, 247, 0.14) !important;
  border-color: rgba(196, 181, 253, 0.2) !important;
  color: #ede9fe !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-domain-chip--asmr_sync,
html.kikoerumanager-dark .dashboard-archive .dash-archive-domain-chip--circle_completion {
  background: rgba(16, 185, 129, 0.14) !important;
  border-color: rgba(110, 231, 183, 0.2) !important;
  color: #d1fae5 !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-domain-chip--http_download {
  background: rgba(249, 115, 22, 0.16) !important;
  border-color: rgba(251, 146, 60, 0.22) !important;
  color: #fed7aa !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip {
  background: rgba(255, 255, 255, 0.06) !important;
  color: #cbd5e1 !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip--completed,
html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip--success,
html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip--finished {
  background: rgba(16, 185, 129, 0.14) !important;
  color: #d1fae5 !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip--partial_failed {
  background: rgba(245, 158, 11, 0.14) !important;
  color: #fde68a !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip--failed {
  background: rgba(244, 63, 94, 0.14) !important;
  color: #fecdd3 !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip--pending,
html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip--waiting_manual,
html.kikoerumanager-dark .dashboard-archive .dash-archive-status-chip--waiting_retry {
  background: rgba(255, 255, 255, 0.08) !important;
  color: #e2e8f0 !important;
}

html.kikoerumanager-dark .dashboard-archive .dash-archive-meta-rj,
html.kikoerumanager-dark .dashboard-archive .dash-archive-meta-time,
html.kikoerumanager-dark .dashboard-archive .dash-archive-meta-size {
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.22);
}

</style>
