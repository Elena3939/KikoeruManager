<template>
  <div class="lib-search-box" :class="{ 'is-open': isPopupOpen }">
    <div class="lib-search">
      <IconSearch :size="14" :stroke-width="2.2" class="lib-search-icon" />
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
            <span class="lib-suggest-row-icon">
              <component :is="iconForItem(item)" :size="13" :stroke-width="2.4" :class="iconClassForItem(item)" />
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
                <span class="lib-suggest-row-path" :title="item.relative_path">{{ formatPath(item) }}</span>
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
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  AlertCircle as IconAlertCircle,
  ArrowUpRight as IconArrowUpRight,
  Cloud as IconCloud,
  CornerDownLeft as IconCornerDownLeft,
  File as IconFile,
  Folder as IconFolder,
  HardDrive as IconHardDrive,
  Layers as IconLayers,
  Loader2 as IconLoader2,
  Maximize2 as IconMaximize2,
  Search as IconSearch,
  SearchX as IconSearchX,
  X as IconX,
  Zap as IconZap,
} from 'lucide-vue-next'

import { libraryApi } from '../../api'

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

function iconForItem (item) {
  return item?.entry_type === 'file' ? IconFile : IconFolder
}

function iconClassForItem (item) {
  if (!item) return 'lib-suggest-row-icon-folder'
  if (item.entry_type === 'file') return 'lib-suggest-row-icon-file'
  return 'lib-suggest-row-icon-folder'
}

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
        emit('open-overlay', { keyword: trimmed })
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
  emit('open-overlay', { keyword: innerKeyword.value.trim() })
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
      entryType: 'all',
      signal: controller ? controller.signal : undefined,
    })
    if (requestId !== activeRequestId) return
    items.value = Array.isArray(data?.items) ? data.items : []
    totalCount.value = Number(data?.total ?? data?.count ?? items.value.length) || 0
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

.lib-search-icon {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
  pointer-events: none;
  transition: color 0.25s ease;
}

.lib-search:focus-within .lib-search-icon { color: #3b82f6; }

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

.lib-suggest-row-icon-folder {
  color: #f59e0b;
  fill: currentColor;
  stroke: currentColor;
}

.lib-suggest-row-icon-file { color: #94a3b8; }

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
</style>
