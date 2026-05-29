<template>
  <div ref="rootRef" class="lib-search-box" :class="{ 'is-open': isPopupOpen, 'is-filter-open': isFilterMenuOpen }">
    <div class="lib-search">
      <button
        type="button"
        class="lib-search-filter"
        :class="{ 'is-active': kindFilter !== 'all', 'is-open': isFilterMenuOpen }"
        :title="filterButtonTitle"
        :style="{ color: currentFilterMeta.color }"
        @mousedown.prevent
        @click="toggleFilterMenu"
      >
        <component
          :is="currentFilterMeta.icon"
          :size="14"
          :stroke-width="2.2"
          :class="{ 'lib-search-filter-fill': currentFilterMeta.fillIcon }"
        />
        <span v-if="kindFilter !== 'all'" class="lib-search-filter-dot" />
      </button>
      <input
        ref="inputRef"
        v-model="innerKeyword"
        type="text"
        class="lib-search-input"
        :placeholder="placeholder"
        spellcheck="false"
        autocomplete="off"
        @input="onUserInput"
        @focus="onInputFocus"
        @blur="onInputBlur"
        @keydown="onInputKeydown"
      />
      <button
        v-if="innerKeyword"
        type="button"
        class="lib-search-clear"
        :title="'清除'"
        @mousedown.prevent
        @click="onClearKeyword"
      >
        <IconX :size="13" :stroke-width="2.4" />
      </button>
      <button
        type="button"
        class="lib-search-expand"
        title="展开跨库搜索面板（Shift + 回车）"
        @mousedown.prevent
        @click="onOpenOverlay"
      >
        <IconMaximize2 :size="14" :stroke-width="2.2" />
      </button>
    </div>

    <transition name="filter-menu-fade">
      <div
        v-if="isFilterMenuOpen"
        class="lib-filter-menu"
        @mousedown.prevent
      >
        <header class="lib-filter-menu-head">
          <IconFilter :size="11" :stroke-width="2.4" />
          <span>按文件类型筛选</span>
        </header>
        <ul class="lib-filter-menu-list">
          <li
            v-for="opt in LIBRARY_FILTER_OPTIONS"
            :key="opt.value"
            class="lib-filter-menu-row"
            :class="{ 'is-active': kindFilter === opt.value }"
            @mousedown.prevent
            @click="onSelectFilter(opt.value)"
          >
            <span class="lib-filter-menu-icon" :style="{ color: opt.color }">
              <component
                :is="opt.icon"
                :size="14"
                :stroke-width="2.2"
                :class="{ 'lib-search-filter-fill': opt.fillIcon }"
              />
            </span>
            <span class="lib-filter-menu-label">{{ opt.label }}</span>
            <IconCheck
              v-if="kindFilter === opt.value"
              :size="13"
              :stroke-width="2.4"
              class="lib-filter-menu-check"
            />
          </li>
        </ul>
      </div>
    </transition>

    <transition name="suggest-fade">
      <div
        v-if="isPopupOpen"
        class="lib-suggest-pop"
        @mousedown.prevent
      >
        <header class="lib-suggest-head">
          <div class="lib-suggest-head-left">
            <IconLayers :size="12" :stroke-width="2.2" class="text-slate-400" />
            <span class="lib-suggest-head-title">跨库索引建议</span>
            <span v-if="!loading && totalText" class="lib-suggest-head-count">{{ totalText }}</span>
          </div>
          <span v-if="loading" class="lib-suggest-head-loader">
            <IconLoader2 :size="11" :stroke-width="2.4" class="animate-spin" />
            <span>正在查询索引</span>
          </span>
          <span v-else-if="elapsedMs !== null" class="lib-suggest-head-meta">
            <IconZap :size="10" :stroke-width="2.4" />
            <span>{{ elapsedMs }} ms</span>
          </span>
        </header>

        <!-- 软降级 banner：索引接口异常/未就绪时不挡视图，仅折叠提示，仍允许回车走本地筛选 -->
        <div v-if="errorMessage" class="lib-suggest-banner" :class="{ 'is-warning': errorIsSoft, 'is-error': !errorIsSoft }">
          <IconAlertCircle :size="13" :stroke-width="2.4" />
          <div class="lib-suggest-banner-text">
            <span class="lib-suggest-banner-title">{{ errorMessage }}</span>
            <span class="lib-suggest-banner-hint">回车可在当前目录里精确筛选作为兜底</span>
          </div>
        </div>

        <ul
          v-if="items.length"
          ref="listRef"
          class="lib-suggest-list"
        >
          <li
            v-for="(item, index) in items"
            :key="`${item.library_id}|${item.relative_path}`"
            class="lib-suggest-row"
            :class="{ 'is-active': index === activeIndex, 'is-rj-hit': isRjHit(item) }"
            @mouseenter="activeIndex = index"
            @mousedown.prevent
            @click="onSelectRow(item)"
          >
            <span
              class="lib-suggest-row-icon"
              :style="{ color: rowIconMeta(item).color }"
            >
              <component
                :is="rowIconMeta(item).icon"
                :size="14"
                :stroke-width="2.2"
                :class="{ 'lib-search-filter-fill': rowIconMeta(item).fillIcon }"
              />
            </span>
            <div class="lib-suggest-row-main">
              <div class="lib-suggest-row-title">
                <span class="lib-suggest-row-name" v-html="renderHighlightedName(item)"></span>
                <span v-if="item.rjcode" class="lib-suggest-row-rj">{{ item.rjcode }}</span>
              </div>
              <div class="lib-suggest-row-sub">
                <span
                  class="lib-suggest-lib-chip"
                  :class="item.library_type === 'synology_filestation' ? 'is-remote' : 'is-local'"
                >
                  <component :is="item.library_type === 'synology_filestation' ? IconCloud : IconHardDrive" :size="10" :stroke-width="2.4" />
                  {{ item.library_name || item.library_id }}
                </span>
                <span class="lib-suggest-row-path">{{ formatPath(item) }}</span>
              </div>
            </div>
            <span class="lib-suggest-row-arrow">
              <IconCornerDownLeft v-if="index === activeIndex" :size="11" :stroke-width="2.4" />
            </span>
          </li>
        </ul>

        <div v-else-if="!loading && lastRequestedKeyword && !errorMessage" class="lib-suggest-state">
          <IconSearchX :size="14" :stroke-width="2.2" />
          <div class="lib-suggest-state-text">
            <div>跨库索引里没找到 <span class="font-medium text-slate-700">"{{ lastRequestedKeyword }}"</span></div>
            <div class="lib-suggest-state-hint">回车可在当前目录里精确筛选 · 或检查索引是否就绪</div>
          </div>
        </div>

        <div v-else-if="loading && !items.length" class="lib-suggest-state">
          <IconLoader2 :size="14" :stroke-width="2.4" class="animate-spin" />
          <span>正在查询跨库索引…</span>
        </div>

        <footer class="lib-suggest-foot">
          <span class="lib-suggest-foot-hint">
            <kbd>↑</kbd><kbd>↓</kbd> 选中 · <kbd>↵</kbd> 跳转 · <kbd>Esc</kbd> 收起
          </span>
          <button
            v-if="hasMoreResults || items.length"
            type="button"
            class="lib-suggest-foot-btn"
            @mousedown.prevent
            @click="onOpenOverlay"
          >
            <span>{{ moreButtonLabel }}</span>
            <IconArrowUpRight :size="12" :stroke-width="2.4" />
          </button>
        </footer>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertCircle as IconAlertCircle,
  ArrowUpRight as IconArrowUpRight,
  Check as IconCheck,
  Cloud as IconCloud,
  CornerDownLeft as IconCornerDownLeft,
  Filter as IconFilter,
  HardDrive as IconHardDrive,
  Layers as IconLayers,
  Loader2 as IconLoader2,
  Maximize2 as IconMaximize2,
  SearchX as IconSearchX,
  X as IconX,
  Zap as IconZap,
} from 'lucide-vue-next'

import { libraryApi } from '../../api'
import {
  LIBRARY_FILTER_OPTIONS,
  applyLibraryFrontendFilter,
  libraryEntryMetaFor,
  libraryFilterToEntryType,
} from './_libraryFileKind'

const props = defineProps({
  modelValue: { type: String, default: '' },
  libraryIds: { type: Array, default: () => [] },
  placeholder: { type: String, default: '搜索文件名或 RJ 号 · 默认跨库（索引）' },
  // 与 Library.vue 现有 searchExact / searchResultKind 解耦：
  // 这里 suggest 始终拉所有类型，UI 上让用户在 overlay 里再筛
  suggestLimit: { type: Number, default: 6 },
  // 输入触发的最小长度。RJ 数字短一些，名字至少 2 字符
  minQueryLength: { type: Number, default: 2 },
})

const emit = defineEmits([
  'update:modelValue',
  'legacy-search',
  'locate',
  'open-overlay',
])

// ====== 输入与建议状态 ======
const rootRef = ref(null)
const innerKeyword = ref(props.modelValue || '')
const inputRef = ref(null)
const listRef = ref(null)
const isPopupOpen = ref(false)
const items = ref([])
const totalCount = ref(0)
const truncated = ref(false)
const elapsedMs = ref(null)
const matchedRjcode = ref(null)
const lastRequestedKeyword = ref('')
const loading = ref(false)
const errorMessage = ref('')
// errorIsSoft: 后端返回 200 + error 字段（索引未就绪 / 索引层异常）—— 走 warning 浅色提示
// errorIsSoft = false: 网络/接口本身 5xx 4xx —— 走 error 深色提示，但仍允许 Enter 走本地兜底
const errorIsSoft = ref(false)
const activeIndex = ref(-1)

// 文件类型筛选：值集合见 LIBRARY_FILTER_OPTIONS。
// 这个状态同时控制：
// 1) 左侧搜索图标显示哪种文件类型图标 + 颜色
// 2) 调后端 globalSearch 时的 entry_type 参数（dir / file / all）
// 3) 拿到结果后再按扩展名做一次前端细分（audio / text）
const kindFilter = ref('all')
const isFilterMenuOpen = ref(false)

let debounceTimer = null
let activeAbort = null
let activeRequestId = 0
let blurTimer = null

const DEBOUNCE_MS = 220

watch(() => props.modelValue, (next) => {
  if ((next || '') !== innerKeyword.value) innerKeyword.value = next || ''
})

watch(innerKeyword, (next) => {
  emit('update:modelValue', next)
})

const totalText = computed(() => {
  if (loading.value) return ''
  if (!items.value.length) return ''
  if (truncated.value && totalCount.value > items.value.length) {
    return `命中 ${totalCount.value}+ · 展示前 ${items.value.length}`
  }
  if (totalCount.value > items.value.length) {
    return `命中 ${totalCount.value} · 展示前 ${items.value.length}`
  }
  return `命中 ${items.value.length}`
})

const hasMoreResults = computed(() => totalCount.value > items.value.length || truncated.value)

const moreButtonLabel = computed(() => {
  if (!innerKeyword.value.trim()) return '打开全屏搜索'
  if (hasMoreResults.value) return `展开全部结果（${totalCount.value}${truncated.value ? '+' : ''}）`
  return '在全屏面板中查看'
})

function isRjHit (item) {
  if (!matchedRjcode.value || !item) return false
  return (item.rjcode || '').toUpperCase() === matchedRjcode.value
}

// 行图标 / 颜色 / 是否 fill：与库存页主文件树同一套色盘（参见 _libraryFileKind.js）
function rowIconMeta (item) {
  return libraryEntryMetaFor(item)
}

const currentFilterMeta = computed(() => {
  return LIBRARY_FILTER_OPTIONS.find(opt => opt.value === kindFilter.value) || LIBRARY_FILTER_OPTIONS[0]
})

const filterButtonTitle = computed(() => {
  const label = currentFilterMeta.value.label
  return kindFilter.value === 'all' ? `按文件类型筛选（当前：${label}）` : `已筛选：${label}（点击切换）`
})

function toggleFilterMenu () {
  isFilterMenuOpen.value = !isFilterMenuOpen.value
  if (isFilterMenuOpen.value) {
    isPopupOpen.value = false
  }
}

function onSelectFilter (value) {
  const next = String(value || 'all')
  const changed = kindFilter.value !== next
  kindFilter.value = next
  isFilterMenuOpen.value = false
  // 切换筛选后重拉一次建议；若没在输入态就不弹出
  if (changed && innerKeyword.value.trim()) {
    isPopupOpen.value = true
    scheduleSuggestFetch(true)
  }
  inputRef.value?.focus?.()
}

function handleDocumentMousedown (event) {
  if (!isFilterMenuOpen.value) return
  const target = event.target
  if (!target) return
  const rootEl = rootRef.value
  if (rootEl && !rootEl.contains(target)) {
    isFilterMenuOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('mousedown', handleDocumentMousedown, true)
})

function formatPath (item) {
  if (!item) return ''
  const rel = String(item.relative_path || '').replace(/\\/g, '/')
  if (!rel) return '/'
  // 名字本身已展示，路径里去掉末尾的 name 段，只保留父级面包屑
  const parent = (item.parent_path || '').replace(/\\/g, '/')
  if (parent) return parent
  // 没有 parent_path（例如就在库根）回落到 relative_path 自身
  const idx = rel.lastIndexOf('/')
  return idx > 0 ? rel.slice(0, idx) : ''
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
  const keyword = innerKeyword.value.trim()
  if (!keyword) return safe
  // 简单子串高亮，case-insensitive；忽略 regex 特殊字符
  const safeKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  try {
    return safe.replace(new RegExp(safeKeyword, 'ig'), match => `<mark>${match}</mark>`)
  } catch (_err) {
    return safe
  }
}

// ====== 输入事件 ======
function onUserInput () {
  scheduleSuggestFetch()
}

function onInputFocus () {
  if (innerKeyword.value.trim()) {
    isPopupOpen.value = true
    if (!items.value.length && !loading.value) scheduleSuggestFetch(true)
  }
}

function onInputBlur () {
  // 延迟收起，让 click 事件先触发到 list row
  if (blurTimer) clearTimeout(blurTimer)
  blurTimer = setTimeout(() => {
    isPopupOpen.value = false
    blurTimer = null
  }, 120)
}

function onInputKeydown (event) {
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      if (!isPopupOpen.value) {
        isPopupOpen.value = true
        if (!items.value.length) scheduleSuggestFetch(true)
        return
      }
      moveActive(1)
      break
    case 'ArrowUp':
      if (!isPopupOpen.value) return
      event.preventDefault()
      moveActive(-1)
      break
    case 'Enter': {
      const trimmed = innerKeyword.value.trim()
      // 只有“手动上下选中”了建议行才跳转。默认 activeIndex = -1，
      // 意味着纯打字 + 意外的 Enter（粘贴/输入法）不会跳转。
      if (isPopupOpen.value && activeIndex.value >= 0 && items.value[activeIndex.value]) {
        event.preventDefault()
        onSelectRow(items.value[activeIndex.value])
        return
      }
      if (event.shiftKey && trimmed) {
        event.preventDefault()
        emit('open-overlay', { keyword: trimmed, kindFilter: kindFilter.value })
        isPopupOpen.value = false
        return
      }
      // 不再自动 emit legacy-search。
      // 老逻辑会调 handleSearch 把当前库按关键词筛选一遍，
      // 但用户需求是“只有明确点击建议行才跳转”，
      // 所以这里只收起 popup，不跳转也不筛选。
      isPopupOpen.value = false
      break
    }
    case 'Escape':
      if (isPopupOpen.value) {
        event.preventDefault()
        isPopupOpen.value = false
      }
      break
    default:
      break
  }
}

function moveActive (delta) {
  if (!items.value.length) return
  let next = activeIndex.value + delta
  if (next < 0) next = items.value.length - 1
  if (next >= items.value.length) next = 0
  activeIndex.value = next
  nextTick(() => {
    const el = listRef.value?.querySelector(`.lib-suggest-row.is-active`)
    if (el?.scrollIntoView) el.scrollIntoView({ block: 'nearest' })
  })
}

function onClearKeyword () {
  innerKeyword.value = ''
  resetState()
  isPopupOpen.value = false
  inputRef.value?.focus?.()
  // 清除时也不再自动调 legacy-search。清除不是一个跳转意图，
  // 文件列表的“退出搜索模式”走面包屑那个“退出搜索”按钮。
}

function onSelectRow (row) {
  isPopupOpen.value = false
  emit('locate', row)
}

function onOpenOverlay () {
  isPopupOpen.value = false
  emit('open-overlay', { keyword: innerKeyword.value.trim(), kindFilter: kindFilter.value })
}

// ====== 数据请求 ======
function resetState () {
  if (activeAbort) {
    try { activeAbort.abort() } catch (_e) {}
    activeAbort = null
  }
  items.value = []
  totalCount.value = 0
  truncated.value = false
  matchedRjcode.value = null
  loading.value = false
  errorMessage.value = ''
  errorIsSoft.value = false
  activeIndex.value = -1
  lastRequestedKeyword.value = ''
}

function summarizeIndexStatus (statusList) {
  // 只在兜底搜索"失败"的库上提醒，索引未就绪但兜底成功的不打扰用户
  if (!Array.isArray(statusList) || !statusList.length) return ''
  const failed = statusList.filter(item => item?.search_mode === 'fallback_failed')
  if (!failed.length) return ''
  const sample = failed.slice(0, 2).map(item => item.library_name || item.library_id).filter(Boolean).join('、')
  const hint = failed.length === statusList.length ? '请检查网络 / 群晖凭据，或先重建索引' : '其它库结果已正常返回'
  return `部分库未能搜索：${sample}${failed.length > 2 ? ' 等' : ''} · ${hint}`
}

function scheduleSuggestFetch (immediate = false) {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  const trimmed = innerKeyword.value.trim()
  if (!trimmed) {
    resetState()
    isPopupOpen.value = false
    return
  }
  // RJ 关键字（含 4-12 位数字 / RJxxx）允许更短
  const rjLike = /^[Rr][Jj]?\d{4,}$/.test(trimmed) || /^\d{4,}$/.test(trimmed)
  if (!rjLike && trimmed.length < props.minQueryLength) {
    resetState()
    isPopupOpen.value = true
    errorIsSoft.value = true
    errorMessage.value = `至少输入 ${props.minQueryLength} 个字符或一个完整 RJ 号`
    return
  }

  errorMessage.value = ''
  errorIsSoft.value = false
  isPopupOpen.value = true

  const run = () => fetchSuggestions(trimmed)
  if (immediate) run()
  else debounceTimer = setTimeout(run, DEBOUNCE_MS)
}

async function fetchSuggestions (keyword) {
  if (activeAbort) {
    try { activeAbort.abort() } catch (_e) {}
  }
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  activeAbort = controller
  const requestId = ++activeRequestId
  loading.value = true
  errorMessage.value = ''
  errorIsSoft.value = false
  try {
    const data = await libraryApi.searchIndexGlobal({
      keyword,
      libraryIds: Array.isArray(props.libraryIds) && props.libraryIds.length ? props.libraryIds : null,
      mode: 'suggest',
      limit: props.suggestLimit,
      entryType: libraryFilterToEntryType(kindFilter.value),
      signal: controller ? controller.signal : undefined,
    })
    if (requestId !== activeRequestId) return
    const rawItems = Array.isArray(data?.items) ? data.items : []
    // 前端二次过滤：把"name 不含 keyword 但路径包含 keyword 的子文件兜底命中"丢掉，
    // 同时按 audio / text 这种细分类按扩展名筛。详细规则见 _libraryFileKind.js。
    items.value = applyLibraryFrontendFilter(rawItems, {
      filter: kindFilter.value,
      keyword,
      matchedRjcode: data?.matched_rjcode,
    })
    // total 用前端过滤后的结果数；truncated 仍由后端提示，因为它代表后端"还有更多"
    totalCount.value = items.value.length
    truncated.value = Boolean(data?.truncated)
    elapsedMs.value = Number.isFinite(Number(data?.elapsed_ms)) ? Number(data.elapsed_ms) : null
    matchedRjcode.value = data?.matched_rjcode || null
    // 不再默认高亮第一行。
    // 原因：下拉默认高亮首行 + 按 Enter 跳转首行 →
    // 粘贴带换行符的 RJ、输入法提交等场景下会意外跳转。
    // 要选中必须先上下方向键手动高亮。
    activeIndex.value = -1
    lastRequestedKeyword.value = keyword
    // 软降级 banner 触发条件：
    // 1) 整个索引层挂了（data.error）
    // 2) 部分库的兜底搜索失败（data.fallback_failed 非空）
    // 索引未就绪但兜底成功的库不显示提示——用户感知不到差别。
    const hasFailedFallback = Array.isArray(data?.fallback_failed) && data.fallback_failed.length > 0
    if (data?.error || hasFailedFallback) {
      errorIsSoft.value = true
      const statusHint = summarizeIndexStatus(data?.library_status)
      if (statusHint) {
        errorMessage.value = statusHint
      } else if (data?.error?.message) {
        errorMessage.value = `索引暂不可用：${data.error.message}`
      } else {
        errorMessage.value = '索引暂不可用'
      }
    }
  } catch (error) {
    if (error?.name === 'CanceledError' || error?.name === 'AbortError' || error?.code === 'ERR_CANCELED') return
    if (requestId !== activeRequestId) return
    // 网络/接口异常：保留之前展示的 items，避免抖一下；只在没历史结果时清空
    if (!items.value.length) {
      totalCount.value = 0
      truncated.value = false
    }
    errorIsSoft.value = false
    const detail = error?.response?.data?.detail
    const baseMsg = detail || error?.message || '未知错误'
    errorMessage.value = `跨库索引暂时连不上（${baseMsg}）`
  } finally {
    if (requestId === activeRequestId) loading.value = false
  }
}

function focus () {
  inputRef.value?.focus?.()
}

defineExpose({ focus })

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (blurTimer) clearTimeout(blurTimer)
  if (activeAbort) {
    try { activeAbort.abort() } catch (_e) {}
  }
  document.removeEventListener('mousedown', handleDocumentMousedown, true)
})
</script>

<style scoped>
.lib-search-box {
  position: relative;
  flex: 1 1 240px;
  min-width: 220px;
  max-width: 360px;
}

.lib-search {
  position: relative;
  width: 100%;
}

/* 左侧：可点击的"按文件类型筛选"下拉触发按钮，
   跳动动效跟右侧 .lib-search-expand 同调。 */
.lib-search-filter {
  position: absolute;
  left: 5px;
  top: 50%;
  transform: translateY(-50%);
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 0;
  background: transparent;
  border-radius: 7px;
  cursor: pointer;
  color: #94a3b8;
  transition: all 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-search-filter:hover {
  background: rgba(99, 102, 241, 0.10);
  transform: translateY(-50%) scale(1.16);
}

.lib-search-filter:active {
  transform: translateY(-50%) scale(0.92);
  background: rgba(99, 102, 241, 0.18);
}

.lib-search-filter.is-active {
  background: rgba(99, 102, 241, 0.08);
}

.lib-search-filter.is-open {
  background: rgba(99, 102, 241, 0.18);
  transform: translateY(-50%) rotate(-4deg) scale(1.08);
}

.lib-search-filter-dot {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #ef4444;
  box-shadow: 0 0 0 2px #fff;
}

/* lucide 默认 fill="none"，需要 fill 的地方明确赋 currentColor（文件夹主调） */
.lib-search-filter-fill {
  fill: currentColor;
}

/* 文件类型筛选下拉菜单：从筛选按钮下方弹出 */
.lib-filter-menu {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  z-index: 70;
  min-width: 220px;
  border-radius: 12px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.86));
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow:
    0 16px 32px -16px rgba(15, 23, 42, 0.28),
    0 24px 48px -28px rgba(15, 23, 42, 0.32);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  overflow: hidden;
}

.lib-filter-menu-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.85), rgba(248, 250, 252, 0.4));
  font-size: 10.5px;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  color: #475569;
  font-weight: 700;
}

.lib-filter-menu-list {
  list-style: none;
  margin: 0;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.lib-filter-menu-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12.5px;
  color: #1f2937;
  transition: all 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-filter-menu-row:hover {
  background: rgba(99, 102, 241, 0.08);
  transform: translateX(2px);
}

.lib-filter-menu-row.is-active {
  background: rgba(99, 102, 241, 0.12);
  color: #312e81;
  font-weight: 600;
}

.lib-filter-menu-icon {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.lib-filter-menu-label {
  flex: 1;
  min-width: 0;
}

.lib-filter-menu-check {
  flex-shrink: 0;
  color: #6366f1;
}

.filter-menu-fade-enter-active,
.filter-menu-fade-leave-active {
  transition:
    opacity 0.18s ease,
    transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  transform-origin: top left;
}

.filter-menu-fade-enter-from,
.filter-menu-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}

.lib-search-input {
  width: 100%;
  height: 34px;
  /* 右侧预留空间：展开图标 26px + 清除 X 22px + 间距 */
  padding: 0 64px 0 34px;
  border-radius: 10px;
  border: 1px solid rgba(203, 213, 225, 0.8);
  background: rgba(248, 250, 252, 0.7);
  font-size: 13px;
  color: #0f172a;
  outline: none;
  transition: all 0.25s ease;
}

.lib-search-input::placeholder { color: #94a3b8; }

.lib-search-input:hover {
  border-color: #94a3b8;
  background: #fff;
}

.lib-search-input:focus {
  border-color: #3b82f6;
  background: #fff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
}

.lib-search-clear {
  position: absolute;
  /* 右侧预留 “展开图标” 的位置，清除 X 不跳动 */
  right: 36px;
  top: 50%;
  transform: translateY(-50%);
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border: 0;
  background: transparent;
  color: #94a3b8;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.lib-search-clear:hover {
  color: #0f172a;
  background: rgba(148, 163, 184, 0.15);
}

/* 展开按钮：纯图标、不冲击输入框调性。
   hover 轻微隐路的光済 + 放大，点击有收紧反馈。 */
.lib-search-expand {
  position: absolute;
  right: 5px;
  top: 50%;
  transform: translateY(-50%);
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 0;
  background: transparent;
  color: #94a3b8;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-search-expand:hover {
  color: #4f46e5;
  background: rgba(99, 102, 241, 0.12);
  transform: translateY(-50%) scale(1.16);
}

.lib-search-expand:active {
  transform: translateY(-50%) scale(0.92);
  background: rgba(99, 102, 241, 0.2);
}

.lib-search-expand:hover svg {
  filter: drop-shadow(0 0 6px rgba(99, 102, 241, 0.5));
}

.lib-search-expand svg {
  transition: filter 0.25s ease, transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* 建议下拉 ------------------------------------------------------ */
.lib-suggest-pop {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 60;
  min-width: 320px;
  max-width: 520px;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(255, 255, 255, 0.78));
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow:
    0 18px 36px -18px rgba(15, 23, 42, 0.32),
    0 32px 60px -32px rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  overflow: hidden;
  font-size: 12.5px;
}

.lib-suggest-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.85), rgba(248, 250, 252, 0.4));
  font-size: 11px;
  color: #64748b;
}

.lib-suggest-head-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.lib-suggest-head-title {
  font-weight: 700;
  letter-spacing: 0.4px;
  color: #475569;
  text-transform: uppercase;
  font-size: 10.5px;
}

.lib-suggest-head-count {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.08);
  color: #0c4a6e;
  font-weight: 600;
  font-size: 10.5px;
}

.lib-suggest-head-loader,
.lib-suggest-head-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: #64748b;
}

.lib-suggest-list {
  list-style: none;
  margin: 0;
  padding: 4px 0;
  max-height: 320px;
  overflow-y: auto;
}

.lib-suggest-row {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  margin: 0 6px;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.12s ease, transform 0.15s ease;
}

.lib-suggest-row:hover,
.lib-suggest-row.is-active {
  background: linear-gradient(120deg, rgba(186, 230, 253, 0.55), rgba(191, 219, 254, 0.45));
  transform: translateY(-0.5px);
}

.lib-suggest-row.is-rj-hit::before {
  content: '';
  display: block;
  position: absolute;
  width: 3px;
}

.lib-suggest-row-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

/* 行图标颜色现在由组件里的 inline :style="{ color: ... }" 控制（主文件树色盘），
   这里只保留"文件夹要 fill currentColor"这个须要仅 stroke 的表现差异。
   .lib-search-filter-fill 在 SVG 元素上赋 currentColor 填充色。 */

.lib-suggest-row-main { min-width: 0; }

.lib-suggest-row-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.lib-suggest-row-name {
  font-weight: 600;
  color: #0f172a;
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.lib-suggest-row-name :deep(mark) {
  background: rgba(250, 204, 21, 0.55);
  color: #78350f;
  border-radius: 3px;
  padding: 0 1px;
}

.lib-suggest-row-rj {
  flex-shrink: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  color: #0c4a6e;
  background: rgba(14, 165, 233, 0.08);
  padding: 0 6px;
  border-radius: 999px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.lib-suggest-row-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  margin-top: 2px;
  color: #64748b;
  font-size: 11px;
}

.lib-suggest-lib-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.95);
  border: 1px solid rgba(15, 23, 42, 0.08);
  color: #475569;
  font-size: 10.5px;
  font-weight: 600;
  flex-shrink: 0;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lib-suggest-lib-chip.is-local {
  background: rgba(34, 197, 94, 0.08);
  border-color: rgba(34, 197, 94, 0.24);
  color: #166534;
}

.lib-suggest-lib-chip.is-remote {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.28);
  color: #92400e;
}

.lib-suggest-row-path {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10.5px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.lib-suggest-row-arrow {
  width: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #0284c7;
}

.lib-suggest-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  color: #64748b;
  font-size: 12px;
}

.lib-suggest-state-text { display: flex; flex-direction: column; gap: 2px; }
.lib-suggest-state-hint { font-size: 11px; color: #94a3b8; }

/* 软降级 banner：与结果列表共存，浅色不吃掉视图，仅提醒 */
.lib-suggest-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 8px 8px 0;
  padding: 8px 10px;
  border-radius: 9px;
  border: 1px solid;
  font-size: 11.5px;
  line-height: 1.4;
  animation: banner-slide-in 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.lib-suggest-banner.is-warning {
  color: #92400e;
  background: linear-gradient(120deg, rgba(254, 243, 199, 0.7), rgba(254, 215, 170, 0.45));
  border-color: rgba(245, 158, 11, 0.32);
}

.lib-suggest-banner.is-error {
  color: #b91c1c;
  background: linear-gradient(120deg, rgba(254, 226, 226, 0.7), rgba(254, 202, 202, 0.45));
  border-color: rgba(248, 113, 113, 0.36);
}

.lib-suggest-banner > svg { flex-shrink: 0; margin-top: 2px; }

.lib-suggest-banner-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.lib-suggest-banner-title { font-weight: 600; }

.lib-suggest-banner-hint {
  font-size: 10.5px;
  font-weight: 500;
  opacity: 0.78;
}

@keyframes banner-slide-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.lib-suggest-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 12px 8px;
  border-top: 1px solid rgba(15, 23, 42, 0.05);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.4), rgba(248, 250, 252, 0.85));
}

.lib-suggest-foot-hint {
  font-size: 10.5px;
  color: #94a3b8;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.lib-suggest-foot-hint kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  padding: 0 4px;
  border-radius: 4px;
  background: rgba(15, 23, 42, 0.05);
  border: 1px solid rgba(15, 23, 42, 0.08);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
  color: #475569;
  margin: 0 1px;
}

.lib-suggest-foot-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 7px;
  border: 0;
  background: linear-gradient(120deg, #0ea5e9, #0284c7);
  color: white;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  letter-spacing: 0.2px;
  transition: transform 0.18s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.18s ease;
  box-shadow: 0 8px 18px -10px rgba(2, 132, 199, 0.6);
}

.lib-suggest-foot-btn:hover {
  transform: translateY(-1px) scale(1.02);
  box-shadow: 0 12px 22px -10px rgba(2, 132, 199, 0.7);
}

.lib-suggest-foot-btn:active { transform: scale(0.96); }

/* 进出场动效 */
.suggest-fade-enter-active,
.suggest-fade-leave-active {
  transition: opacity 0.16s ease, transform 0.18s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.suggest-fade-enter-from,
.suggest-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* 滚动条 */
.lib-suggest-list::-webkit-scrollbar { width: 8px; }
.lib-suggest-list::-webkit-scrollbar-track { background: transparent; }
.lib-suggest-list::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.12);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}
.lib-suggest-list::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.24);
  background-clip: content-box;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-pop,
:global(html.kikoerumanager-dark) .lib-search-box .lib-filter-menu {
  background: var(--km-dark-sidebar) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow:
    0 22px 54px rgba(0, 0, 0, 0.5),
    inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-head,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-foot,
:global(html.kikoerumanager-dark) .lib-search-box .lib-filter-menu-head {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text-muted) !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-head-title,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-row-name,
:global(html.kikoerumanager-dark) .lib-search-box .lib-filter-menu-label,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-state .font-medium {
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-head-loader,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-head-meta,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-state,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-state-hint,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-row-sub,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-row-path,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-foot-hint {
  color: var(--km-dark-text-muted) !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-row:hover,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-row.is-active,
:global(html.kikoerumanager-dark) .lib-search-box .lib-filter-menu-row:hover,
:global(html.kikoerumanager-dark) .lib-search-box .lib-filter-menu-row.is-active {
  background: rgba(255, 255, 255, 0.16) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow:
    inset 3px 0 0 rgba(255, 255, 255, 0.78),
    inset 0 0 0 1px rgba(255, 255, 255, 0.14) !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-head-count,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-row-rj,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-lib-chip,
:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-foot-hint kbd {
  background: var(--km-dark-field) !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-banner.is-warning {
  background: rgba(245, 158, 11, 0.14) !important;
  border-color: rgba(245, 158, 11, 0.34) !important;
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-banner.is-error {
  background: rgba(244, 63, 94, 0.14) !important;
  border-color: rgba(251, 113, 133, 0.34) !important;
  color: #fda4af !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-foot-btn {
  background: #020617 !important;
  border: 1px solid var(--km-dark-border-strong) !important;
  color: #ffffff !important;
  box-shadow: 0 10px 22px rgba(0, 0, 0, 0.38) !important;
}

:global(html.kikoerumanager-dark) .lib-search-box .lib-suggest-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.18);
  background-clip: content-box;
}
</style>

<style>
html.kikoerumanager-dark .lib-suggest-pop {
  background: #0b0c10 !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

html.kikoerumanager-dark .lib-suggest-head,
html.kikoerumanager-dark .lib-suggest-foot {
  background: #0b0c10 !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .lib-suggest-list,
html.kikoerumanager-dark .lib-suggest-row {
  background: transparent !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .lib-suggest-row:hover,
html.kikoerumanager-dark .lib-suggest-row.is-active {
  background: #2b2c30 !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .lib-suggest-head-title,
html.kikoerumanager-dark .lib-suggest-row-name {
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .lib-suggest-head-loader,
html.kikoerumanager-dark .lib-suggest-head-meta,
html.kikoerumanager-dark .lib-suggest-row-sub,
html.kikoerumanager-dark .lib-suggest-row-path,
html.kikoerumanager-dark .lib-suggest-row-size,
html.kikoerumanager-dark .lib-suggest-foot-hint {
  color: var(--km-dark-text-muted) !important;
}

html.kikoerumanager-dark .lib-suggest-head-count,
html.kikoerumanager-dark .lib-suggest-row-rj,
html.kikoerumanager-dark .lib-suggest-lib-chip,
html.kikoerumanager-dark .lib-suggest-foot-hint kbd {
  background: #2b2c30 !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: var(--km-dark-text-strong) !important;
}

html.kikoerumanager-dark .lib-suggest-banner.is-warning {
  background: rgba(245, 158, 11, 0.14) !important;
  border-color: rgba(245, 158, 11, 0.34) !important;
  color: #fbbf24 !important;
}

html.kikoerumanager-dark .lib-suggest-foot-btn {
  background: #2b2c30 !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  color: #ffffff !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .lib-suggest-foot-btn:hover {
  background: #333438 !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  box-shadow: none !important;
}

html.kikoerumanager-dark .lib-search-box,
html.kikoerumanager-dark .lib-search-box .lib-search {
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
  outline: 0 !important;
}

html.kikoerumanager-dark .lib-search-box .lib-search-input,
html.kikoerumanager-dark .lib-search-box .lib-search-input:hover,
html.kikoerumanager-dark .lib-search-box .lib-search-input:focus {
  appearance: none !important;
  -webkit-appearance: none !important;
  background: #2b2c30 !important;
  background-clip: padding-box !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  border-radius: 10px !important;
  box-shadow: none !important;
  outline: 0 !important;
}
</style>
