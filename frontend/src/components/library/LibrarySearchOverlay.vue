<template>
  <Teleport to="body">
    <!-- overlay 容器：透明背景，仅捕获 click 用于关闭。绝不模糊 / 暗化背景 -->
    <transition name="lib-overlay-fade">
      <div
        v-if="visible"
        class="lib-search-overlay"
        @mousedown.self="handleClose"
      >
        <transition name="lib-panel-slide" appear @after-enter="handleOpened">
          <div
            ref="panelRef"
            v-if="visible"
            class="lib-search-panel"
            @mousedown.stop
          >
            <!-- 顶部：单一搜索框（筛选按钮 + 输入 + 关闭），不放任何多余元素 -->
            <div class="lib-panel-input-row">
              <!-- filter 按钮：菜单已 Teleport 到 body，避免被 .lib-search-panel 的 overflow:hidden 裁切 -->
              <button
                ref="filterButtonRef"
                type="button"
                class="lib-panel-filter"
                :class="{ 'is-active': kindFilter !== 'all', 'is-open': isFilterMenuOpen }"
                :title="filterButtonTitle"
                :style="{ color: currentFilterMeta.color }"
                @mousedown.prevent
                @click="toggleFilterMenu"
              >
                <component
                  :is="currentFilterMeta.icon"
                  :size="18"
                  :stroke-width="2.4"
                  :class="{ 'lib-panel-row-icon-fill': currentFilterMeta.fillIcon }"
                />
                <span v-if="kindFilter !== 'all'" class="lib-panel-filter-dot" />
              </button>

              <input
                ref="inputRef"
                v-model="keyword"
                type="text"
                class="lib-panel-input"
                placeholder="跨库索引搜索 · 输入文件名或 RJ 号"
                spellcheck="false"
                autocomplete="off"
                @input="onKeywordInput"
                @keydown="onJumboKeydown"
              />
              <Loader2
                v-if="loading"
                :size="14"
                :stroke-width="2.4"
                class="animate-spin lib-panel-input-loader"
              />
              <button
                type="button"
                class="lib-panel-input-close"
                aria-label="关闭"
                title="关闭（Esc）"
                @click="handleClose"
              >
                <X :size="15" :stroke-width="2.2" />
              </button>
            </div>

            <!-- 横幅式结果区：从搜索框下方平滑展开 -->
            <transition name="lib-results-reveal">
              <div v-if="hasResultsArea" class="lib-panel-results">
                <!-- 软降级 / 错误细条 -->
                <div
                  v-if="errorMessage"
                  class="lib-panel-banner"
                  :class="{ 'is-warning': errorIsSoft, 'is-error': !errorIsSoft }"
                >
                  <AlertCircle :size="13" :stroke-width="2.4" />
                  <span class="lib-panel-banner-text">{{ errorMessage }}</span>
                  <button type="button" class="lib-panel-banner-retry" @click="onRetrySearch">
                    <RefreshCcw :size="11" :stroke-width="2.4" />
                    <span>重试</span>
                  </button>
                </div>

                <!-- 结果行列表 -->
                <TransitionGroup
                  v-if="items.length"
                  ref="listRef"
                  tag="ul"
                  name="row-stagger"
                  class="lib-panel-list"
                >
                  <li
                    v-for="(item, index) in items"
                    :key="`${item.library_id}|${item.relative_path}|${item.absolute_path || ''}`"
                    class="lib-panel-row"
                    :class="{ 'is-active': index === activeIndex, 'is-rj-hit': isRjHit(item) }"
                    :style="{ '--row-i': Math.min(index, 14) }"
                    :title="item.absolute_path || item.relative_path"
                    @mouseenter="activeIndex = index"
                    @click="onSelectRow(item)"
                    @dblclick="onSelectRow(item)"
                  >
                    <span
                      class="lib-panel-row-icon"
                      :style="{ color: rowIconMeta(item).color }"
                    >
                      <component
                        :is="rowIconMeta(item).icon"
                        :size="15"
                        :stroke-width="2.2"
                        :class="{ 'lib-panel-row-icon-fill': rowIconMeta(item).fillIcon }"
                      />
                    </span>
                    <div class="lib-panel-row-main">
                      <div class="lib-panel-row-title">
                        <span class="lib-panel-row-name" v-html="renderHighlightedName(item)"></span>
                        <span v-if="item.rjcode" class="lib-panel-row-rj">{{ item.rjcode }}</span>
                      </div>
                      <div class="lib-panel-row-sub">
                        <span
                          class="lib-panel-row-lib"
                          :class="item.library_type === 'synology_filestation' ? 'is-remote' : 'is-local'"
                        >
                          <component :is="item.library_type === 'synology_filestation' ? Cloud : HardDrive" :size="10" :stroke-width="2.4" />
                          <span class="truncate">{{ item.library_name || item.library_id }}</span>
                        </span>
                        <span class="lib-panel-row-path" :title="item.relative_path">{{ formatPath(item) }}</span>
                      </div>
                    </div>
                    <div class="lib-panel-row-meta">
                      <span v-if="item.size" class="lib-panel-row-size">{{ formatSize(item.size) }}</span>
                      <CornerDownLeft v-if="index === activeIndex" :size="12" :stroke-width="2.4" class="lib-panel-row-enter" />
                    </div>
                  </li>
                </TransitionGroup>

                <!-- loading 占位 -->
                <div
                  v-else-if="loading"
                  class="lib-panel-state"
                >
                  <Loader2 :size="14" :stroke-width="2.4" class="animate-spin" />
                  <span>查询索引中…</span>
                </div>

                <!-- keyword 非空 + 无结果 + 无错误 -->
                <div
                  v-else-if="!errorMessage"
                  class="lib-panel-state"
                >
                  <SearchX :size="14" :stroke-width="2.2" />
                  <span>没找到「{{ keyword.trim() }}」相关项</span>
                </div>
              </div>
            </transition>
          </div>
        </transition>
      </div>
    </transition>
  </Teleport>

  <!-- Filter menu：独立 Teleport 到 body，避免被 .lib-search-panel 的 overflow:hidden 裁切 -->
  <Teleport to="body">
    <transition name="panel-filter-fade">
      <div
        v-if="visible && isFilterMenuOpen"
        class="lib-panel-filter-menu"
        :style="filterMenuStyle"
        @mousedown.prevent
      >
        <header class="lib-panel-filter-menu-head">
          <FilterIcon :size="12" :stroke-width="2.4" />
          <span>按文件类型筛选</span>
        </header>
        <ul class="lib-panel-filter-menu-list">
          <li
            v-for="opt in LIBRARY_FILTER_OPTIONS"
            :key="opt.value"
            class="lib-panel-filter-menu-row"
            :class="{ 'is-active': kindFilter === opt.value }"
            @mousedown.prevent
            @click="onSelectFilter(opt.value)"
          >
            <span class="lib-panel-filter-menu-icon" :style="{ color: opt.color }">
              <component
                :is="opt.icon"
                :size="15"
                :stroke-width="2.2"
                :class="{ 'lib-panel-row-icon-fill': opt.fillIcon }"
              />
            </span>
            <span class="lib-panel-filter-menu-label">{{ opt.label }}</span>
            <CheckIcon
              v-if="kindFilter === opt.value"
              :size="14"
              :stroke-width="2.4"
              class="lib-panel-filter-menu-check"
            />
          </li>
        </ul>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertCircle,
  Check as CheckIcon,
  Cloud,
  CornerDownLeft,
  Filter as FilterIcon,
  HardDrive,
  Loader2,
  RefreshCcw,
  SearchX,
  X,
} from 'lucide-vue-next'

import { libraryApi } from '../../api'
import {
  LIBRARY_FILTER_OPTIONS,
  applyLibraryFrontendFilter,
  libraryEntryMetaFor,
  libraryFilterToEntryType,
} from './_libraryFileKind'

const props = defineProps({
  visible: { type: Boolean, default: false },
  initialKeyword: { type: String, default: '' },
  libraries: { type: Array, default: () => [] },
  // 父组件初始化时可以传一个默认的 scope，例如刚从某个库点的"在该库内搜索"
  initialScopeMode: { type: String, default: 'all' },
  initialSingleLibraryId: { type: String, default: '' },
  // 从 LibrarySearchBox 顶层有选不同文件类型筛选进来时，这里也能继承那个 kindFilter。
  // 取值集合参 _libraryFileKind.js 的 LIBRARY_FILTER_OPTIONS
  initialKindFilter: { type: String, default: 'all' },
  fullLimit: { type: Number, default: 200 },
})

const emit = defineEmits(['update:visible', 'locate', 'close'])

const inputRef = ref(null)
const listRef = ref(null)
const panelRef = ref(null)
const filterButtonRef = ref(null)
const filterMenuStyle = ref({})
const keyword = ref('')
const items = ref([])
const totalCount = ref(0)
const truncated = ref(false)
const matchedRjcode = ref(null)
const elapsedMs = ref(null)
const loading = ref(false)
const errorMessage = ref('')
// errorIsSoft：true → 索引层降级（200+error 字段），warning 提示；false → 网络/接口本身异常，error 提示
const errorIsSoft = ref(false)
const activeIndex = ref(-1)
const libraryStatusMap = ref({})
// scopeMode / singleLibraryId / entryType：保留 state 以保持父组件 API 兼容，
// 当前 UI 没有暴露切换入口（用户要求"默认只要一个搜索框"），后端按 scopeMode 走全部库
const scopeMode = ref('all')
const singleLibraryId = ref('')
// kindFilter 同时决定后端 entry_type 参数与前端二次过滤（audio / text 这种细分靠扩展名）
const kindFilter = ref('all')
const isFilterMenuOpen = ref(false)

let debounceTimer = null
let activeAbort = null
let activeRequestId = 0

const DEBOUNCE_MS = 280

const scopedLibraryIds = computed(() => {
  if (scopeMode.value === 'single') {
    return singleLibraryId.value ? [singleLibraryId.value] : []
  }
  if (scopeMode.value === 'local') {
    return props.libraries.filter(item => item.type !== 'synology_filestation').map(item => item.id)
  }
  if (scopeMode.value === 'remote') {
    return props.libraries.filter(item => item.type === 'synology_filestation').map(item => item.id)
  }
  return [] // all → 不传 library_ids，让后端默认全部
})

// 结果区只在有 keyword 或有错误信息时展开。
// Overlay 默认就是"一个搜索框 + 点前面图标弹下拉"的极简交互。
const hasResultsArea = computed(() => Boolean(keyword.value.trim()) || Boolean(errorMessage.value))

watch(() => props.visible, (next) => {
  if (next) {
    keyword.value = props.initialKeyword || ''
    scopeMode.value = props.initialScopeMode || 'all'
    singleLibraryId.value = props.initialSingleLibraryId || ''
    kindFilter.value = props.initialKindFilter || 'all'
    isFilterMenuOpen.value = false
    libraryStatusMap.value = {}
    activeIndex.value = -1
    elapsedMs.value = null
    if (keyword.value.trim()) {
      scheduleSearch(true)
    } else {
      items.value = []
      totalCount.value = 0
      truncated.value = false
      matchedRjcode.value = null
      errorMessage.value = ''
    }
  } else {
    cleanupRequests()
    isFilterMenuOpen.value = false
  }
})

watch(scopeMode, () => {
  if (props.visible && keyword.value.trim()) scheduleSearch(true)
})
watch(singleLibraryId, () => {
  if (props.visible && keyword.value.trim() && scopeMode.value === 'single') scheduleSearch(true)
})
watch(kindFilter, () => {
  if (props.visible && keyword.value.trim()) scheduleSearch(true)
})

function handleClose () {
  cleanupRequests()
  emit('update:visible', false)
  emit('close')
}

function handleOpened () {
  nextTick(() => inputRef.value?.focus?.())
}

function onKeywordInput () {
  scheduleSearch(false)
}

function onJumboKeydown (event) {
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      moveActive(1)
      break
    case 'ArrowUp':
      event.preventDefault()
      moveActive(-1)
      break
    case 'Enter':
      // 只有“手动上下选中”了某一行才跳转。
      // 不再在没选中时默认拿首行，避免粘贴/输入法提交带出的 Enter 误跳。
      if (activeIndex.value >= 0 && items.value[activeIndex.value]) {
        event.preventDefault()
        onSelectRow(items.value[activeIndex.value])
      }
      break
    case 'Escape':
      event.preventDefault()
      handleClose()
      break
    default:
      break
  }
}

function moveActive (delta) {
  if (!items.value.length) return
  let next = (activeIndex.value === -1 ? 0 : activeIndex.value + delta)
  if (next < 0) next = items.value.length - 1
  if (next >= items.value.length) next = 0
  activeIndex.value = next
  nextTick(() => {
    // listRef 是 TransitionGroup 实例，需要走 $el 拿真实 DOM；类名跟新模板对齐
    const root = listRef.value?.$el || listRef.value
    const el = root?.querySelector?.('.lib-panel-row.is-active')
    if (el?.scrollIntoView) el.scrollIntoView({ block: 'nearest' })
  })
}

function onSelectRow (row) {
  if (!row) return
  emit('locate', row)
  // overlay 由父组件决定是否关闭；通常 locate 即关闭
}

// 行图标 / 颜色 与库存页主文件树保持同一套色盘（参 _libraryFileKind.js）：
// 文件夹 / 无损音频 / 普通音频 / 文档-字幕 / 其他文件 五类。
// 不再使用原来的十几种扩展名色块，避免"主文件树一套 / 搜索结果另一套"的割裂。
function rowIconMeta (item) {
  return libraryEntryMetaFor(item)
}

// 顶部输入框左侧的“按文件类型筛选”下拉触发器：跟 LibrarySearchBox 用同一套状态与菜单逻辑
const currentFilterMeta = computed(() => {
  return LIBRARY_FILTER_OPTIONS.find(opt => opt.value === kindFilter.value) || LIBRARY_FILTER_OPTIONS[0]
})

const filterButtonTitle = computed(() => {
  const label = currentFilterMeta.value.label
  return kindFilter.value === 'all'
    ? `按文件类型筛选（当前：${label}）`
    : `已筛选：${label}（点击切换）`
})

function updateFilterMenuPosition () {
  const btn = filterButtonRef.value
  if (!btn) return
  const rect = btn.getBoundingClientRect()
  const padding = 8
  const menuMinWidth = 240 // 跟 CSS .lib-panel-filter-menu min-width 同步
  const viewportWidth = window.innerWidth

  // 水平：默认以 filter button 左边缘对齐；超出视口右边界时回密
  let left = rect.left
  if (left + menuMinWidth > viewportWidth - padding) {
    left = viewportWidth - padding - menuMinWidth
  }
  if (left < padding) left = padding

  filterMenuStyle.value = {
    left: `${left}px`,
    top: `${rect.bottom + 8}px`,
    minWidth: `${menuMinWidth}px`,
  }
}

async function toggleFilterMenu () {
  if (isFilterMenuOpen.value) {
    isFilterMenuOpen.value = false
    return
  }
  isFilterMenuOpen.value = true
  await nextTick()
  updateFilterMenuPosition()
}

function onSelectFilter (value) {
  const next = String(value || 'all')
  kindFilter.value = next
  isFilterMenuOpen.value = false
  // kindFilter 上面已经有 watch 启动重搜，这里只需重新聚焦输入框
  inputRef.value?.focus?.()
}

function handleDocumentMousedown (event) {
  if (!isFilterMenuOpen.value) return
  const target = event.target
  if (!target?.closest) return
  // 点击在筛选触发按钮 / 菜单本体内 → 不关；其余位置（包括 panel 内的输入框 / 结果列表 / overlay 空白处）→ 关闭菜单
  if (target.closest('.lib-panel-filter') || target.closest('.lib-panel-filter-menu')) return
  isFilterMenuOpen.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', handleDocumentMousedown, true)
})

// filter menu 打开期间跟踪窗口变化，确保 Teleport 后的 fixed 菜单位置
// 在 viewport 变化（滚动 / 缩放 / DPR 变化）时保持跟 filter 按钮对齐。
function handleFilterMenuReflow () {
  if (isFilterMenuOpen.value) updateFilterMenuPosition()
}

watch(isFilterMenuOpen, (next) => {
  if (next) {
    window.addEventListener('scroll', handleFilterMenuReflow, true)
    window.addEventListener('resize', handleFilterMenuReflow)
  } else {
    window.removeEventListener('scroll', handleFilterMenuReflow, true)
    window.removeEventListener('resize', handleFilterMenuReflow)
  }
})

function isRjHit (item) {
  if (!matchedRjcode.value || !item) return false
  return (item.rjcode || '').toUpperCase() === matchedRjcode.value
}

function formatPath (item) {
  if (!item) return ''
  const rel = String(item.relative_path || '').replace(/\\/g, '/')
  if (!rel) return '/'
  const parent = (item.parent_path || '').replace(/\\/g, '/')
  if (parent) return parent
  const idx = rel.lastIndexOf('/')
  return idx > 0 ? rel.slice(0, idx) : ''
}

function formatSize (bytes) {
  const num = Number(bytes || 0)
  if (!num) return '-'
  if (num < 1024) return `${num} B`
  if (num < 1024 ** 2) return `${(num / 1024).toFixed(1)} KB`
  if (num < 1024 ** 3) return `${(num / (1024 ** 2)).toFixed(1)} MB`
  return `${(num / (1024 ** 3)).toFixed(2)} GB`
}

function formatTime (mtime) {
  if (!mtime) return '-'
  try {
    const d = new Date(Number(mtime))
    if (Number.isNaN(d.getTime())) return '-'
    const yy = d.getFullYear()
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    return `${yy}-${mm}-${dd} ${hh}:${mi}`
  } catch (_e) {
    return '-'
  }
}

function escapeHtml (text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderHighlightedName (item) {
  const name = String(item?.name || '')
  const safe = escapeHtml(name)
  const trimmed = keyword.value.trim()
  if (!trimmed) return safe
  const safeKeyword = trimmed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  try {
    return safe.replace(new RegExp(safeKeyword, 'ig'), match => `<mark>${match}</mark>`)
  } catch (_err) {
    return safe
  }
}

function summarizeIndexStatus (statusList) {
  // 只在兜底搜索失败的库上提醒；索引未就绪但兜底成功的库静默处理
  if (!Array.isArray(statusList) || !statusList.length) return ''
  const failed = statusList.filter(item => item?.search_mode === 'fallback_failed')
  if (!failed.length) return ''
  const sample = failed.slice(0, 2).map(item => item.library_name || item.library_id).filter(Boolean).join('、')
  const allFailed = failed.length === statusList.length
  const hint = allFailed ? '请检查网络 / 群晖凭据，或先重建索引' : '其它库结果已正常返回'
  return `部分库未能搜索：${sample}${failed.length > 2 ? ' 等' : ''} · ${hint}`
}

function scheduleSearch (immediate = false) {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  const trimmed = keyword.value.trim()
  if (!trimmed) {
    items.value = []
    totalCount.value = 0
    truncated.value = false
    matchedRjcode.value = null
    elapsedMs.value = null
    errorMessage.value = ''
    errorIsSoft.value = false
    return
  }
  if (immediate) runSearch(trimmed)
  else debounceTimer = setTimeout(() => runSearch(trimmed), DEBOUNCE_MS)
}

function onRetrySearch () {
  const trimmed = keyword.value.trim()
  if (!trimmed) return
  errorMessage.value = ''
  errorIsSoft.value = false
  runSearch(trimmed)
}

async function runSearch (kw) {
  // 取消上一次飞行的流，避免新旧结果交错
  if (activeAbort) {
    try { activeAbort.abort() } catch (_e) {}
  }
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  activeAbort = controller
  const requestId = ++activeRequestId
  loading.value = true
  errorMessage.value = ''
  errorIsSoft.value = false

  // 内部状态由本次请求独占，所有事件落到这些 buffer 上，
  // 中途若 requestId 失效就直接 return，不会污染 UI
  const localStatusMap = {}
  const fallbackFailedSet = new Set()
  let sawAnyEvent = false

  // 后端 、 前端联合筛选：后端只负责 dir / file / all 粗范围；audio / text 这种细分类靠前端。
  // applyLibraryFrontendFilter 同时会干掉"name 不含 keyword 但路径含的兜底子文件误命中"。
  const filterArgs = (extraKeyword) => ({
    filter: kindFilter.value,
    keyword: extraKeyword,
    matchedRjcode: matchedRjcode.value,
  })

  try {
    for await (const evt of libraryApi.searchIndexGlobalStream({
      keyword: kw,
      libraryIds: scopedLibraryIds.value,
      entryType: libraryFilterToEntryType(kindFilter.value),
      mode: 'full',
      limit: props.fullLimit,
      signal: controller ? controller.signal : undefined,
    })) {
      if (requestId !== activeRequestId) return  // 用户已经又输入了
      sawAnyEvent = true

      if (evt.type === 'initial') {
        // 第一波：索引结果。这里先记下 matched_rjcode，后续子文件过滤会靠它放过 RJ 命中。
        const initialItems = Array.isArray(evt.items) ? evt.items : []
        matchedRjcode.value = evt.matched_rjcode || null
        items.value = applyLibraryFrontendFilter(initialItems, filterArgs(kw))
        totalCount.value = items.value.length
        truncated.value = Boolean(evt.truncated)
        elapsedMs.value = Number.isFinite(Number(evt.elapsed_ms)) ? Number(evt.elapsed_ms) : null
        // 不默认高亮首行。原因同 LibrarySearchBox：默认高亮 + Enter
        // 跳转会让粘贴/输入法场景下出现意外导航。
        activeIndex.value = -1
        if (Array.isArray(evt.library_status)) {
          for (const s of evt.library_status) {
            if (s?.library_id) localStatusMap[s.library_id] = s.index_status || ''
          }
          libraryStatusMap.value = { ...localStatusMap }
        }
        // 索引整段挂了 → 软警告
        if (evt.error) {
          errorIsSoft.value = true
          errorMessage.value = evt.error.message
            ? `索引暂不可用：${evt.error.message}`
            : '索引暂不可用'
        }
      } else if (evt.type === 'library') {
        // 兜底库逐个返回：增量追加 —— 这里也走二次过滤。
        const libItems = Array.isArray(evt.items) ? evt.items : []
        const filtered = applyLibraryFrontendFilter(libItems, filterArgs(kw))
        if (filtered.length) {
          items.value = [...items.value, ...filtered]
          totalCount.value = items.value.length
          // 同样不再自动选中第一行。需要手动高亮才能回车跳转。
        }
        if (evt.library_id && evt.library_status) {
          localStatusMap[evt.library_id] = evt.library_status.index_status || ''
          libraryStatusMap.value = { ...localStatusMap }
        }
        if (evt.error && evt.library_id) {
          fallbackFailedSet.add(evt.library_id)
        }
        elapsedMs.value = Number.isFinite(Number(evt.elapsed_ms)) ? Number(evt.elapsed_ms) : elapsedMs.value
      } else if (evt.type === 'done') {
        elapsedMs.value = Number.isFinite(Number(evt.elapsed_ms)) ? Number(evt.elapsed_ms) : elapsedMs.value
        // 收口阶段把 library_status 全量回填一次（覆盖期间可能漏掉的库）
        if (Array.isArray(evt.library_status)) {
          const finalMap = {}
          for (const s of evt.library_status) {
            if (s?.library_id) finalMap[s.library_id] = s.index_status || ''
          }
          libraryStatusMap.value = finalMap
        }
        // 部分库兜底失败的话，给个中性 warning
        const failed = Array.from(fallbackFailedSet)
        if (failed.length && !errorMessage.value) {
          errorIsSoft.value = true
          const sample = failed.slice(0, 2).join('、')
          errorMessage.value = `部分库未能搜索：${sample}${failed.length > 2 ? ' 等' : ''}`
        }
      }
    }

    // 流正常结束但一个事件都没收到（不应发生）→ 视作空结果
    if (!sawAnyEvent && requestId === activeRequestId) {
      items.value = []
      totalCount.value = 0
      truncated.value = false
      matchedRjcode.value = null
    }
  } catch (error) {
    if (error?.name === 'AbortError' || error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') return
    if (requestId !== activeRequestId) return
    // 网络/HTTP 异常：保留已渲染的 items 让用户感知不到 flash
    if (!items.value.length) {
      totalCount.value = 0
      truncated.value = false
      matchedRjcode.value = null
      elapsedMs.value = null
    }
    errorIsSoft.value = false
    const baseMsg = error?.message || '未知错误'
    errorMessage.value = `跨库索引暂时连不上（${baseMsg}）`
  } finally {
    if (requestId === activeRequestId) loading.value = false
  }
}

function cleanupRequests () {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  if (activeAbort) {
    try { activeAbort.abort() } catch (_e) {}
    activeAbort = null
  }
}

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleDocumentMousedown, true)
  cleanupRequests()
})
</script>

<style scoped>
/* ===== overlay 容器：透明 click 捕获，绝不模糊背景 ===== */
.lib-search-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  align-items: center;
  /* 锚定到原搜索框稍微上方一点的位置（库内文件列表卡片的 toolbar 实际偏靠下，
     画面里大约 y≈190 左右）。180px 让面板压在搜索框正上沿位置，
     视觉上像"原搜索框被放大了一档"。 */
  padding: 180px 24px 24px;
  background: transparent;
  pointer-events: auto;
}

/* 紧凑视口下 toolbar 整体上移，所以面板顶距也跟着收 */
@media (max-height: 720px) {
  .lib-search-overlay { padding-top: 130px; }
}
@media (max-height: 560px) {
  .lib-search-overlay { padding-top: 88px; }
}

/* ===== 玻璃面板：纯白磨砂 ===== */
/* 设计要点：
   - 颜色绝对纯白 (255,255,255)，不掺任何色调
   - 不透明度 75%：保留磨砂的"半透"质感
   - 强 blur(48px) + saturate(180%)：把底下糊成均匀的奶白
   - 与白底背景的区分完全交给"边框 + 阴影"：
       * 中性灰描边（rgba(15,23,42, .08)）→ 边缘清晰
       * 多层下投影 → 浮起感 */
.lib-search-panel {
  position: relative; /* 让 .lib-panel-filter-menu 的 absolute 以面板为锚点 */
  width: min(920px, 100%);
  max-height: calc(100vh - 96px);
  display: flex;
  flex-direction: column;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(15, 23, 42, 0.09);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    inset 0 -1px 0 rgba(15, 23, 42, 0.03),
    0 32px 72px -24px rgba(15, 23, 42, 0.28),
    0 14px 36px -18px rgba(15, 23, 42, 0.18),
    0 2px 8px rgba(15, 23, 42, 0.06);
  backdrop-filter: blur(48px) saturate(180%);
  -webkit-backdrop-filter: blur(48px) saturate(180%);
  overflow: hidden;
}

/* 浏览器/插件禁用 backdrop-filter 时的兜底：还是纯白，只是把不透明度提到 92%，
   阴影靠多层描边 + 投影撑住"浮起"观感，决不掺色调 */
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .lib-search-panel {
    background: rgba(255, 255, 255, 0.92);
    border-color: rgba(15, 23, 42, 0.12);
  }
}

/* ===== 顶部输入行 ===== */
/* 输入行不另上色，跟面板同体；下方分割线靠 .lib-panel-results 的 border-top 体现 */
.lib-panel-input-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  background: transparent;
}

/* 顶部：可点击的"按文件类型筛选"下拉触发按钮，
   占用原 Search 装饰的位置；hover / active / open 都有动效。 */
.lib-panel-filter {
  position: relative;
  flex: 0 0 auto;
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border: 0;
  background: transparent;
  border-radius: 10px;
  cursor: pointer;
  color: #64748b;
  transition: all 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-panel-filter:hover {
  background: rgba(99, 102, 241, 0.10);
  transform: scale(1.08);
}

.lib-panel-filter:active {
  background: rgba(99, 102, 241, 0.18);
  transform: scale(0.94);
}

.lib-panel-filter.is-active {
  background: rgba(99, 102, 241, 0.08);
}

.lib-panel-filter.is-open {
  background: rgba(99, 102, 241, 0.18);
  transform: rotate(-4deg) scale(1.06);
}

.lib-panel-filter-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #ef4444;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.96);
}

.lib-panel-input {
  flex: 1;
  min-width: 0;
  height: 30px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #0f172a;
  font-size: 16px;
  font-weight: 500;
  letter-spacing: 0.2px;
}

.lib-panel-input::placeholder {
  color: #94a3b8;
  font-weight: 400;
}

.lib-panel-input-loader {
  flex: 0 0 auto;
  color: #6366f1;
}

.lib-panel-input-close {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border: 0;
  background: rgba(148, 163, 184, 0.16);
  color: #64748b;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-panel-input-close:hover {
  background: rgba(248, 113, 113, 0.18);
  color: #dc2626;
  transform: rotate(90deg) scale(1.06);
}

.lib-panel-input-close:active {
  transform: rotate(90deg) scale(0.94);
}

/* 顶部"按文件类型筛选"下拉菜单：
 * Teleport 到 body + position: fixed，逃离 .lib-search-panel 的 overflow:hidden。
 * 位置由 inline style（filterMenuStyle）控制，跟随 filter 按钮 rect。 */
.lib-panel-filter-menu {
  position: fixed;
  z-index: 9999;
  min-width: 240px;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.86));
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow:
    0 18px 36px -18px rgba(15, 23, 42, 0.32),
    0 28px 56px -28px rgba(15, 23, 42, 0.36);
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  overflow: hidden;
  transform-origin: top left;
}

.lib-panel-filter-menu-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.85), rgba(248, 250, 252, 0.4));
  font-size: 11px;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  color: #475569;
  font-weight: 700;
}

.lib-panel-filter-menu-list {
  list-style: none;
  margin: 0;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.lib-panel-filter-menu-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: #1f2937;
  transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-panel-filter-menu-row:hover {
  background: rgb(241 245 249);
  color: #0f172a;
}

.lib-panel-filter-menu-row.is-active {
  background: rgb(241 245 249);
  color: #0f172a;
  font-weight: 600;
}

.lib-panel-filter-menu-icon {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.lib-panel-filter-menu-label {
  flex: 1;
  min-width: 0;
}

.lib-panel-filter-menu-check {
  flex-shrink: 0;
  color: rgb(37 99 235); /* sky-600，与 AppDropdown 的 ✓ 一致 */
}

.panel-filter-fade-enter-active,
.panel-filter-fade-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  transform-origin: top left;
}

.panel-filter-fade-enter-from,
.panel-filter-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}

/* ===== 结果区：从输入行下方平滑展开的横幅 ===== */
.lib-panel-results {
  border-top: 1px solid rgba(15, 23, 42, 0.06);
  padding: 6px 6px 10px;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
  /* will-change 给浏览器一个动画的提示，过渡更顺滑 */
  will-change: max-height, opacity, transform;
}

/* 结果区 banner（软警告 / 错误） */
.lib-panel-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 6px 8px;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 500;
  animation: banner-fade-in 0.32s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes banner-fade-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.lib-panel-banner.is-warning {
  background: rgba(250, 204, 21, 0.18);
  color: #92400e;
  border: 1px solid rgba(250, 204, 21, 0.34);
}

.lib-panel-banner.is-error {
  background: rgba(248, 113, 113, 0.16);
  color: #991b1b;
  border: 1px solid rgba(248, 113, 113, 0.34);
}

.lib-panel-banner-text {
  flex: 1;
  min-width: 0;
}

.lib-panel-banner-retry {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 0;
  background: rgba(15, 23, 42, 0.08);
  color: inherit;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-panel-banner-retry:hover {
  background: rgba(15, 23, 42, 0.18);
  transform: translateY(-1px) scale(1.04);
}

.lib-panel-banner-retry:active { transform: scale(0.94); }

/* ===== 结果列表 ===== */
.lib-panel-list {
  list-style: none;
  margin: 0;
  padding: 0 4px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.lib-panel-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition:
    background 0.22s ease,
    transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.22s ease;
}

.lib-panel-row:hover {
  background: rgba(99, 102, 241, 0.07);
  transform: translateX(2px);
}

.lib-panel-row.is-active {
  /* 选中态只用更浓的紫色背景区分，不再加左侧的深色条 */
  background: rgba(99, 102, 241, 0.13);
  transform: translateX(2px);
}

.lib-panel-row.is-rj-hit .lib-panel-row-rj {
  background: rgba(168, 85, 247, 0.2);
  color: #6b21a8;
}

/* 行图标：扁平彩色图标（颜色由 inline :style 控制，与主文件树色盘对齐） */
.lib-panel-row-icon {
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-panel-row:hover .lib-panel-row-icon,
.lib-panel-row.is-active .lib-panel-row-icon {
  transform: rotate(-4deg) scale(1.08);
}

/* lucide 默认 fill="none"，文件夹要呈现"实心橙"得显式 fill currentColor */
.lib-panel-row-icon-fill {
  fill: currentColor;
}

/* 行主区 */
.lib-panel-row-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.lib-panel-row-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.lib-panel-row-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #0f172a;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  letter-spacing: 0.2px;
}

.lib-panel-row-name :deep(mark) {
  background: linear-gradient(transparent 60%, rgba(250, 204, 21, 0.55) 60%);
  color: inherit;
  padding: 0 1px;
}

.lib-panel-row-rj {
  flex: 0 0 auto;
  font-size: 10.5px;
  font-weight: 700;
  color: #4338ca;
  background: rgba(99, 102, 241, 0.16);
  padding: 1px 7px;
  border-radius: 999px;
  letter-spacing: 0.4px;
  font-feature-settings: 'tnum';
  transition: background 0.22s ease, color 0.22s ease;
}

.lib-panel-row-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #64748b;
  min-width: 0;
}

.lib-panel-row-lib {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 240px;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.lib-panel-row-lib.is-local {
  background: rgba(34, 197, 94, 0.16);
  color: #15803d;
}

.lib-panel-row-lib.is-remote {
  background: rgba(56, 189, 248, 0.18);
  color: #0369a1;
}

.lib-panel-row-lib .truncate {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.lib-panel-row-path {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: 'JetBrains Mono', 'Cascadia Code', ui-monospace, Menlo, Consolas, monospace;
  letter-spacing: 0.1px;
}

/* 行右侧 meta */
.lib-panel-row-meta {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #94a3b8;
  font-feature-settings: 'tnum';
}

.lib-panel-row-size {
  font-weight: 600;
  color: #64748b;
}

.lib-panel-row-enter {
  color: #6366f1;
  animation: enter-pulse 1.2s ease-in-out infinite;
}

@keyframes enter-pulse {
  0%, 100% { transform: translateY(0); opacity: 1; }
  50% { transform: translateY(1px); opacity: 0.7; }
}

/* 空 / 加载状态 */
.lib-panel-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 28px 16px;
  color: #94a3b8;
  font-size: 12.5px;
}

/* ===== 动画 ===== */

/* overlay 整体淡入淡出（不挡光） */
.lib-overlay-fade-enter-active,
.lib-overlay-fade-leave-active {
  transition: opacity 0.2s ease;
}
.lib-overlay-fade-enter-from,
.lib-overlay-fade-leave-to { opacity: 0; }

/* 面板从顶部滑下 + 微缩放 */
.lib-panel-slide-enter-active {
  transition:
    opacity 0.32s cubic-bezier(0.16, 1, 0.3, 1),
    transform 0.42s cubic-bezier(0.16, 1, 0.3, 1);
}
.lib-panel-slide-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.22s ease;
}
.lib-panel-slide-enter-from {
  opacity: 0;
  transform: translateY(-32px) scale(0.97);
}
.lib-panel-slide-leave-to {
  opacity: 0;
  transform: translateY(-12px) scale(0.99);
}

/* 结果区从搜索框下方平滑展开（max-height + opacity + 轻微 translateY） */
.lib-results-reveal-enter-active {
  transition:
    opacity 0.34s cubic-bezier(0.16, 1, 0.3, 1),
    transform 0.4s cubic-bezier(0.16, 1, 0.3, 1),
    max-height 0.42s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}
.lib-results-reveal-leave-active {
  transition:
    opacity 0.22s ease,
    transform 0.22s ease,
    max-height 0.26s ease;
  overflow: hidden;
}
.lib-results-reveal-enter-from,
.lib-results-reveal-leave-to {
  opacity: 0;
  transform: translateY(-6px);
  max-height: 0 !important;
}
.lib-results-reveal-enter-to,
.lib-results-reveal-leave-from {
  max-height: calc(100vh - 200px);
}

/* 列表项错位淡入：每行根据 --row-i 延迟一点点，形成涟漪式平滑感 */
.row-stagger-enter-active {
  transition:
    opacity 0.34s cubic-bezier(0.16, 1, 0.3, 1),
    transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  transition-delay: calc(var(--row-i, 0) * 22ms);
}
.row-stagger-leave-active {
  transition: opacity 0.18s ease, transform 0.22s ease;
  position: absolute;
  width: calc(100% - 8px);
}
.row-stagger-enter-from {
  opacity: 0;
  transform: translateX(-10px);
}
.row-stagger-leave-to {
  opacity: 0;
  transform: translateX(8px);
}
.row-stagger-move {
  transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

/* 旋转图标（用于 loader） */
.animate-spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 滚动条：克制的 hairline */
.lib-panel-results::-webkit-scrollbar { width: 8px; }
.lib-panel-results::-webkit-scrollbar-track { background: transparent; }
.lib-panel-results::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.14);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}
.lib-panel-results::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.26);
  background-clip: content-box;
}

/* 响应式：紧凑视口下 toolbar 也会换行/收紧，把面板顶距同步收下来 */
@media (max-width: 720px) {
  .lib-search-overlay { padding: 88px 12px 12px; }
  .lib-search-panel { width: 100%; }
  .lib-panel-row-meta { display: none; }
  .lib-panel-row-sub { font-size: 10.5px; }
}

:global(html.kikoerumanager-dark) .lib-search-panel,
:global(html.kikoerumanager-dark) .lib-panel-filter-menu {
  background: #08090d !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow:
    0 24px 58px rgba(0, 0, 0, 0.56),
    inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-input-row,
:global(html.kikoerumanager-dark) .lib-panel-results,
:global(html.kikoerumanager-dark) .lib-panel-filter-menu-head {
  background: #08090d !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-input {
  background: #090a0f !important;
  border: 1px solid rgba(255, 255, 255, 0.24) !important;
  border-radius: 0 !important;
  padding: 0 8px !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.08),
    0 0 0 3px rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-input::placeholder {
  color: var(--km-dark-text-muted) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-filter,
:global(html.kikoerumanager-dark) .lib-panel-input-close,
:global(html.kikoerumanager-dark) .lib-panel-banner-retry {
  background: var(--km-dark-button-bg) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-filter:hover,
:global(html.kikoerumanager-dark) .lib-panel-filter.is-active,
:global(html.kikoerumanager-dark) .lib-panel-filter.is-open,
:global(html.kikoerumanager-dark) .lib-panel-input-close:hover,
:global(html.kikoerumanager-dark) .lib-panel-banner-retry:hover {
  background: var(--km-dark-button-bg-hover) !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-filter-menu-row,
:global(html.kikoerumanager-dark) .lib-panel-row {
  background: #08090d !important;
  color: var(--km-dark-text) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-filter-menu-row:hover,
:global(html.kikoerumanager-dark) .lib-panel-filter-menu-row.is-active,
:global(html.kikoerumanager-dark) .lib-panel-row:hover,
:global(html.kikoerumanager-dark) .lib-panel-row.is-active {
  background: rgba(255, 255, 255, 0.16) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow:
    inset 3px 0 0 rgba(255, 255, 255, 0.78),
    inset 0 0 0 1px rgba(255, 255, 255, 0.14) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-filter-menu-head,
:global(html.kikoerumanager-dark) .lib-panel-row-sub,
:global(html.kikoerumanager-dark) .lib-panel-row-path,
:global(html.kikoerumanager-dark) .lib-panel-row-meta,
:global(html.kikoerumanager-dark) .lib-panel-row-size,
:global(html.kikoerumanager-dark) .lib-panel-state {
  color: var(--km-dark-text-muted) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-row-name,
:global(html.kikoerumanager-dark) .lib-panel-filter-menu-label {
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-list {
  background: #08090d !important;
}

:global(html.kikoerumanager-dark) .lib-panel-row-rj,
:global(html.kikoerumanager-dark) .lib-panel-row-lib {
  background: var(--km-dark-field) !important;
  color: var(--km-dark-text) !important;
  border: 1px solid var(--km-dark-border) !important;
}

:global(html.kikoerumanager-dark) .lib-panel-banner.is-warning {
  background: rgba(245, 158, 11, 0.14) !important;
  border-color: rgba(245, 158, 11, 0.34) !important;
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark) .lib-panel-banner.is-warning .lib-panel-banner-retry {
  background: rgba(0, 0, 0, 0.24) !important;
  border: 1px solid rgba(245, 158, 11, 0.28) !important;
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark) .lib-panel-banner.is-error {
  background: rgba(244, 63, 94, 0.14) !important;
  border-color: rgba(251, 113, 133, 0.34) !important;
  color: #fda4af !important;
}

:global(html.kikoerumanager-dark) .lib-panel-results::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.18);
  background-clip: content-box;
}

/* 注：之前有 prefers-color-scheme: dark 暗色覆盖；明确按需求保持白色磨砂，
   不跟随系统暗色主题。如果未来要做应用级暗色，统一在 App.vue 主题切换里走。 */
</style>

<style>
html.kikoerumanager-dark .lib-search-overlay .lib-search-panel {
  background: rgba(8, 9, 13, 0.78) !important;
  border: 1px solid rgba(255, 255, 255, 0.16) !important;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    inset 0 -1px 0 rgba(0, 0, 0, 0.42),
    0 28px 76px rgba(0, 0, 0, 0.58) !important;
  backdrop-filter: blur(34px) saturate(135%) !important;
  -webkit-backdrop-filter: blur(34px) saturate(135%) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-input-row {
  background: rgba(8, 9, 13, 0.36) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-input {
  background: rgba(4, 5, 8, 0.92) !important;
  border: 1px solid rgba(255, 255, 255, 0.28) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.08),
    0 0 0 1px rgba(0, 0, 0, 0.72) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-filter,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-input-close {
  background: rgba(255, 255, 255, 0.08) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-filter:hover,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-filter.is-active,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-filter.is-open,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-input-close:hover {
  background: rgba(255, 255, 255, 0.14) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-input-loader {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-results,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-list,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-row {
  background: rgba(8, 9, 13, 0.74) !important;
  color: var(--km-dark-text) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-row:hover,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-row.is-active {
  background: rgba(255, 255, 255, 0.14) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-row-name {
  color: #f8fafc !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-row-sub,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-row-path,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-row-meta,
html.kikoerumanager-dark .lib-search-overlay .lib-panel-row-size {
  color: rgba(226, 232, 240, 0.72) !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-row-rj {
  background: rgba(99, 102, 241, 0.24) !important;
  color: #c7d2fe !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-row-lib {
  background: rgba(255, 255, 255, 0.1) !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #d1fae5 !important;
}

html.kikoerumanager-dark .lib-search-overlay .lib-panel-state {
  color: var(--km-dark-text-muted) !important;
}
</style>
