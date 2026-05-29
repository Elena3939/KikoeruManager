<template>
  <el-dialog
    :model-value="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal remote-folder-picker-modal"
    align-center
    modal-class="custom-preview-overlay remote-folder-picker-overlay"
    @update:model-value="handleVisibleUpdate"
  >
    <div
      class="window panel-enter glass-shell relative w-full rounded-3xl flex flex-col overflow-hidden"
      :class="{ 'is-resizing': isResizingNav }"
    >
      <!-- 顶部：标题 + 关闭 -->
      <div class="window-header flex items-center justify-between px-8 py-5">
        <div class="min-w-0">
          <h1 class="title text-[22px] font-bold text-slate-900 tracking-tight">{{ title }}</h1>
          <p class="mt-1 text-[12.5px] text-slate-500">
            <span>目标库存：</span>
            <span class="text-slate-700 font-semibold">{{ library?.name || '-' }}</span>
            <span v-if="rootPath" class="ml-2 text-slate-400">·</span>
            <span v-if="rootPath" class="ml-2 font-mono text-slate-500 break-all">{{ rootPath }}</span>
          </p>
        </div>
        <button
          type="button"
          class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700"
          :disabled="submitting"
          @click="handleCancel"
          aria-label="关闭"
        >
          <X :size="20" :stroke-width="2" />
        </button>
      </div>

      <!-- 资源管理器工具栏 -->
      <div class="explorer-toolbar flex items-center gap-2 px-5 py-2.5">
        <button
          type="button"
          class="fm-icon-btn"
          :disabled="!canGoUp || loading || submitting"
          @click="goUp"
          title="上一层"
        >
          <ArrowUp :size="14" :stroke-width="2.2" />
        </button>
        <button
          type="button"
          class="fm-icon-btn"
          :disabled="loading || submitting"
          @click="reload"
          title="刷新"
        >
          <RefreshCw :size="14" :stroke-width="2.2" :class="{ 'animate-spin': loading }" />
        </button>

        <!-- 面包屑 -->
        <div class="path-bar flex items-center gap-0.5 flex-1 min-w-0 overflow-x-auto no-scrollbar">
          <button
            type="button"
            class="crumb-btn crumb-btn-disk"
            :disabled="loading || submitting"
            @click="navigateToPath(rootPath)"
            :title="rootPath"
          >
            <HardDrive :size="13" :stroke-width="2.2" class="text-amber-500" />
            <span class="ml-1 truncate crumb-text crumb-text-disk">{{ library?.name || '库存根' }}</span>
          </button>
          <template v-for="(crumb, idx) in breadcrumbs" :key="crumb.path">
            <ChevronRight :size="13" :stroke-width="2.4" class="text-slate-300 shrink-0" />
            <button
              type="button"
              class="crumb-btn"
              :disabled="loading || submitting"
              :class="{ 'crumb-btn-current': idx === breadcrumbs.length - 1 }"
              @click="navigateToPath(crumb.path)"
              :title="crumb.path"
            >
              <span class="truncate crumb-text">{{ crumb.name }}</span>
            </button>
          </template>
        </div>

        <!-- 搜索框 -->
        <div class="search-wrap">
          <Search :size="12" :stroke-width="2.2" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          <input
            v-model="searchKeyword"
            type="text"
            class="search-input"
            :placeholder="`在「${library?.name || '库存'}」中搜索`"
            :disabled="!library?.id || submitting"
            spellcheck="false"
          />
        </div>
      </div>

      <!-- 主区：左 nav + 拖拽分割线 + 右 list -->
      <div class="explorer-main flex-1 flex min-h-0">
        <!-- 左侧：库存根 / 目录树 -->
        <aside
          class="explorer-nav flex flex-col min-w-0"
          :style="{ width: navWidth + 'px' }"
        >
          <div class="nav-section-title px-4 pt-3 pb-1">远程库存目录</div>
          <div class="nav-scroll flex-1 min-h-0 overflow-y-auto no-scrollbar pb-3">
            <ul class="nav-tree">
              <li class="nav-item">
                <div
                  class="nav-row"
                  :class="{
                    'nav-row-active': normalizePath(currentPath) === normalizePath(rootPath)
                  }"
                  :style="{ paddingLeft: '12px' }"
                  @click="navigateToPath(rootPath)"
                  :title="rootPath"
                >
                  <button
                    type="button"
                    class="nav-expander"
                    :disabled="loading || submitting"
                    @click.stop="toggleRootExpand"
                  >
                    <ChevronDown
                      v-if="navTreeState.rootExpanded"
                      :size="14"
                      :stroke-width="2.2"
                      class="text-slate-400"
                    />
                    <ChevronRight
                      v-else
                      :size="14"
                      :stroke-width="2.2"
                      class="text-slate-400"
                    />
                  </button>
                  <HardDrive :size="14" :stroke-width="2.2" class="nav-disk-icon" />
                  <span class="nav-row-name">{{ library?.name || '库存根' }}</span>
                </div>

                <ul v-if="navTreeState.rootExpanded" class="nav-children">
                  <li
                    v-if="navTreeState.rootLoading"
                    class="nav-row-meta"
                    style="padding-left: 32px"
                  >
                    <Loader2 :size="12" :stroke-width="2.2" class="animate-spin text-slate-400" />
                    <span>加载中...</span>
                  </li>
                  <li
                    v-else-if="navTreeState.rootError"
                    class="nav-row-meta nav-row-meta-error"
                    style="padding-left: 32px"
                  >
                    {{ navTreeState.rootError }}
                  </li>
                  <template v-else>
                    <RemoteFolderPickerNavNode
                      v-for="child in (navTreeState.rootChildren || [])"
                      :key="child.path"
                      :node="child"
                      :depth="1"
                      :tree-state="navTreeState"
                      :current-path="currentPath"
                      :loading="loading"
                      :submitting="submitting"
                      @navigate="navigateToPath"
                      @toggle="toggleNodeExpand"
                    />
                    <li
                      v-if="navTreeState.rootChildren && !navTreeState.rootChildren.length"
                      class="nav-row-meta"
                      style="padding-left: 32px"
                    >
                      <span>（空）</span>
                    </li>
                  </template>
                </ul>
              </li>
            </ul>
          </div>
        </aside>

        <!-- 拖拽分割条 -->
        <div
          class="nav-splitter"
          :class="{ 'nav-splitter-active': isResizingNav }"
          role="separator"
          aria-orientation="vertical"
          :aria-valuenow="navWidth"
          :aria-valuemin="NAV_MIN_WIDTH"
          :aria-valuemax="NAV_MAX_WIDTH"
          aria-label="拖动调整左侧导航宽度"
          tabindex="-1"
          @pointerdown="onSplitterPointerDown"
          @dblclick="resetNavWidth"
        >
          <span class="nav-splitter-line" />
        </div>

        <!-- 右侧：子目录列表 -->
        <section class="explorer-list flex-1 flex flex-col min-w-0">
          <div class="fm-head">
            <button
              type="button"
              class="fm-cell fm-cell-name fm-head-cell"
              :class="{ 'fm-head-cell-active': sortBy === 'name' }"
              @click="onColumnSort('name')"
              title="按名称排序"
            >
              <span>名称</span>
              <ChevronDown
                v-if="sortBy === 'name'"
                :size="13"
                :stroke-width="2.4"
                class="fm-head-arrow"
                :class="{ 'fm-head-arrow-asc': sortDir === 'asc' }"
              />
            </button>
            <button
              type="button"
              class="fm-cell fm-cell-time fm-head-cell"
              :class="{ 'fm-head-cell-active': sortBy === 'mtime' }"
              @click="onColumnSort('mtime')"
              title="按修改时间排序"
            >
              <span>修改时间</span>
              <ChevronDown
                v-if="sortBy === 'mtime'"
                :size="13"
                :stroke-width="2.4"
                class="fm-head-arrow"
                :class="{ 'fm-head-arrow-asc': sortDir === 'asc' }"
              />
            </button>
          </div>
          <div
            ref="listScrollRef"
            class="fm-body flex-1 overflow-y-auto"
            tabindex="0"
            @keydown="handleListKeydown"
          >
            <div v-if="inIndexSearchMode && indexSoftHint" class="fm-soft-hint">
              <AlertCircle :size="13" :stroke-width="2.2" />
              <span>{{ indexSoftHint }}</span>
            </div>
            <div v-if="loading && !inIndexSearchMode" class="fm-state fm-state-col fm-loading-state">
              <Loader2 :size="48" :stroke-width="2" class="fm-loading-icon" />
              <span class="fm-loading-title">正在读取目录</span>
              <span class="fm-loading-desc">同步远程库存子项中…</span>
            </div>
            <div v-else-if="inIndexSearchMode && indexLoading" class="fm-state fm-state-col fm-loading-state">
              <Loader2 :size="48" :stroke-width="2" class="fm-loading-icon" />
              <span class="fm-loading-title">正在搜索</span>
              <span class="fm-loading-desc">「{{ searchKeyword }}」</span>
            </div>
            <div v-else-if="inIndexSearchMode && indexError" class="fm-state fm-state-col">
              <AlertCircle :size="22" :stroke-width="2" class="text-rose-500" />
              <span class="text-rose-600">{{ indexError }}</span>
              <span class="text-[11px] text-slate-400">请稍后重试，或检查网络与凭据</span>
            </div>
            <div v-else-if="error && !inIndexSearchMode" class="fm-state fm-state-col">
              <AlertCircle :size="22" :stroke-width="2" class="text-rose-500" />
              <span class="text-rose-600">{{ error }}</span>
              <button type="button" class="fm-retry-btn" @click="reload">重试</button>
            </div>
            <div v-else-if="!filteredFolders.length" class="fm-empty-wrap">
              <AppEmptyState
                :description="inIndexSearchMode ? `没有匹配「${searchKeyword}」的目录` : '此目录下没有子目录'"
                size="default"
              >
                <span class="text-[11px] text-slate-400">点击"选择此目录"将选中当前目录</span>
              </AppEmptyState>
            </div>
            <template v-else>
              <div
                v-for="(folder, idx) in filteredFolders"
                :key="folder.path"
                :data-folder-index="idx"
                class="fm-row"
                :class="{
                  'fm-row-selected': selectedFolderPath === folder.path,
                  'fm-row-file': !isFolderEntry(folder),
                  'fm-row-search': inIndexSearchMode
                }"
                :title="folder.path"
                @click="selectFolder(folder)"
                @dblclick="isFolderEntry(folder) && navigateToPath(folder.path)"
              >
                <div class="fm-cell fm-cell-name">
                  <span class="fm-icon-shell">
                    <component
                      :is="iconMetaForFolder(folder).icon"
                      :size="16"
                      :stroke-width="2.2"
                      class="fm-kind-icon"
                      :class="[`fm-kind-icon-${classifyFolderKind(folder)}`, { 'fm-kind-icon-fill': iconMetaForFolder(folder).fillIcon }]"
                      :style="{ color: iconMetaForFolder(folder).color }"
                    />
                  </span>
                  <div class="fm-name-wrap min-w-0 flex flex-col">
                    <span class="fm-name truncate" v-html="highlightKeyword(folder.name)"></span>
                    <span v-if="inIndexSearchMode && folder.relative_path" class="fm-name-rel truncate" v-html="highlightKeyword(folder.relative_path)"></span>
                  </div>
                </div>
                <div class="fm-cell fm-cell-time">{{ formatFolderTime(folder.modified_time) }}</div>
              </div>
            </template>
          </div>
        </section>
      </div>

      <!-- 底部：当前选择 + CTA -->
      <div class="footer-row flex items-center justify-between gap-4 px-7 py-4">
        <div class="footer-left flex items-center gap-3 min-w-0 flex-1">
          <div class="target-chip" :title="effectiveAbsolutePath">
            <ArrowRight :size="13" :stroke-width="2.4" class="text-slate-400 shrink-0" />
            <span class="text-[11.5px] text-slate-500 shrink-0">上传到</span>
            <span class="target-chip-path truncate">{{ effectiveAbsolutePath || '-' }}</span>
          </div>
          <div v-if="effectiveRelativePath" class="rel-chip">
            <span class="rel-chip-label">子目录</span>
            <span class="rel-chip-value">{{ effectiveRelativePath }}</span>
          </div>
          <div v-else class="rel-chip rel-chip-default">
            <span class="rel-chip-label">默认</span>
            <span class="rel-chip-value">库存根目录</span>
          </div>
        </div>
        <div class="footer-actions flex items-center gap-2.5 shrink-0">
          <button
            type="button"
            class="primary-cta px-10 h-11 rounded-xl font-bold text-white"
            :disabled="!canSubmit"
            @click="handleSubmit"
          >
            <span v-if="submitting" class="inline-flex items-center gap-1.5"><Loader2 :size="16" class="animate-spin" />处理中</span>
            <span v-else>选择此目录</span>
          </button>
          <button
            type="button"
            class="secondary-cta interactive-button px-10 h-11 rounded-xl font-bold"
            :disabled="submitting"
            @click="handleCancel"
          >取消</button>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import {
  AlertCircle,
  ArrowRight,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  HardDrive,
  Loader2,
  RefreshCw,
  Search,
  X
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'

import { libraryApi } from '../../api'
import RemoteFolderPickerNavNode from './RemoteFolderPickerNavNode.vue'
import AppEmptyState from './AppEmptyState.vue'
import { classifyLibraryEntryKind, libraryEntryMetaFor } from '../library/_libraryFileKind.js'

defineOptions({ name: 'RemoteFolderPickerDialog' })

// 左侧导航宽度（可拖拽）：默认 280，区间 [200, 520]，双击恢复默认
const NAV_DEFAULT_WIDTH = 280
const NAV_MIN_WIDTH = 200
const NAV_MAX_WIDTH = 520

const props = defineProps({
  visible: { type: Boolean, default: false },
  // 目标库存对象，需含 id / name / root_path（或 browse_root_path）/ type
  library: { type: Object, default: null },
  // 进入时已有的相对路径（相对于库根，去除前后斜杠）
  initialRelativePath: { type: String, default: '' },
  title: { type: String, default: '指定上传目录' },
  submitting: { type: Boolean, default: false }
})

const emit = defineEmits(['update:visible', 'submit', 'close'])

const currentPath = ref('')
const rootPath = ref('')
const folders = ref([])
// loading 初始值为 true：dialog 首次 paint 时避免 folders=[] + loading=false 同帧出现，造成 No Data 闪屏。
// loadFolders 完成后会在 finally 块翻 false。
const loading = ref(true)
const error = ref('')
const selectedFolderPath = ref('')
const searchKeyword = ref('')
const listScrollRef = ref(null)

// 索引搜索状态：keyword 非空时改用全库搜索（索引 + 文件系统兜底）替代当前目录的 folders
const indexResults = ref([])
const indexLoading = ref(false)
const indexError = ref('')
// 索引层异常 / 部分库 fallback 失败时的软提示（不阻断结果展示）
const indexSoftHint = ref('')
let indexSearchTimer = null
let indexSearchToken = 0
let indexSearchAbort = null

// 列头排序：sortBy ∈ { 'name', 'mtime' }，sortDir ∈ { 'asc', 'desc' }
const sortBy = ref('name')
const sortDir = ref('asc')

// 左侧导航状态
const navWidth = ref(NAV_DEFAULT_WIDTH)
const isResizingNav = ref(false)
const navResizeStart = { x: 0, width: NAV_DEFAULT_WIDTH }

const navTreeState = reactive({
  rootExpanded: false,
  rootChildren: null,
  rootLoading: false,
  rootError: '',
  nodes: {} // path -> { expanded, children, loading, error }
})

// ---------------- 计算属性 ----------------

const library = computed(() => props.library || null)

const canGoUp = computed(() => {
  if (!currentPath.value || !rootPath.value) return false
  return normalizePath(currentPath.value) !== normalizePath(rootPath.value)
})

const breadcrumbs = computed(() => {
  if (!currentPath.value || !rootPath.value) return []
  const root = normalizePath(rootPath.value)
  const cur = normalizePath(currentPath.value)
  if (root === cur) return []
  // 远程库一律 posix 分隔
  const rootRaw = stripTrailingSlash(rootPath.value)
  const curRaw = stripTrailingSlash(currentPath.value)
  if (!curRaw.startsWith(`${rootRaw}/`)) return []
  const rel = curRaw.slice(rootRaw.length + 1)
  const parts = rel.split('/').filter(Boolean)
  const result = []
  let accum = rootRaw
  for (const part of parts) {
    accum = `${accum}/${part}`
    result.push({ name: part, path: accum })
  }
  return result
})

// 是否处于「索引搜索」模式（搜索框非空）。
// 此时 list 数据源切换为索引返回的全库结果（含深层目录），不再只看当前目录子项。
const inIndexSearchMode = computed(() => String(searchKeyword.value || '').trim().length > 0)

const filteredFolders = computed(() => {
  const source = inIndexSearchMode.value ? indexResults.value : folders.value
  const list = Array.isArray(source) ? [...source] : []
  return sortFolderList(list)
})

function sortFolderList(list) {
  const dir = sortDir.value === 'desc' ? -1 : 1
  const by = sortBy.value
  // 目录优先于文件；同类内按 sortBy 排
  list.sort((a, b) => {
    const aDir = a?.is_directory !== false
    const bDir = b?.is_directory !== false
    if (aDir !== bDir) return aDir ? -1 : 1
    if (by === 'mtime') {
      const at = folderTimeValue(a?.modified_time)
      const bt = folderTimeValue(b?.modified_time)
      if (at !== bt) return (at - bt) * dir
      // 时间相同时回落到名字次级稳定排序
      return String(a?.name || '').localeCompare(String(b?.name || ''), 'zh-Hans-CN', { numeric: true })
    }
    return String(a?.name || '').localeCompare(String(b?.name || ''), 'zh-Hans-CN', { numeric: true }) * dir
  })
  return list
}

function folderTimeValue(value) {
  if (value === null || value === undefined || value === '') return 0
  if (typeof value === 'number') {
    return Number.isFinite(value) ? normalizeTimestamp(value) : 0
  }
  const raw = String(value).trim()
  if (!raw) return 0
  const numeric = Number(raw)
  if (Number.isFinite(numeric)) return normalizeTimestamp(numeric)
  const parsed = Date.parse(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

function normalizeTimestamp(value) {
  // 后端搜索索引给毫秒，群晖原始值常是秒；统一成毫秒再比较。
  return value > 0 && value < 100000000000 ? value * 1000 : value
}

function onColumnSort(field) {
  if (sortBy.value === field) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = field
    sortDir.value = 'asc'
  }
}

const effectiveAbsolutePath = computed(() => {
  const selected = selectedFolderPath.value && isPathInsideRoot(selectedFolderPath.value)
    ? selectedFolderPath.value
    : ''
  return selected || currentPath.value || rootPath.value || ''
})

// targetSubdir 的基准必须是 library.root_path（后端上传拼接用），而不是 browse_root_path。
// 当远程库配置了 browse_path（即 browse_root_path != root_path）时，二者会不同；
// 浏览界面以 browse_root_path 为边界，相对路径仍要从 root_path 起算才能让后端正确拼出最终路径。
const effectiveRelativePath = computed(() => {
  const baseForRelative = stripTrailingSlash(String(library.value?.root_path || '')) || rootPath.value
  return toRelativePath(effectiveAbsolutePath.value, baseForRelative)
})

const canSubmit = computed(() => {
  if (props.submitting) return false
  if (!library.value?.id) return false
  if (!effectiveAbsolutePath.value) return false
  if (!isPathInsideRoot(effectiveAbsolutePath.value)) return false
  return true
})

// ---------------- 监听 ----------------

watch(() => props.visible, async (next) => {
  if (!next) return
  await initFromProps()
})

watch(() => props.library?.id, async (next, prev) => {
  if (!props.visible) return
  if (next === prev) return
  await initFromProps()
})

// 搜索框 debounce 300ms 触发索引搜索（library_id 全库内模糊 name 匹配）。
// 清空搜索框 → 清空索引结果回到当前目录浏览模式。
watch(searchKeyword, (keyword) => {
  const trimmed = String(keyword || '').trim()
  if (indexSearchTimer) {
    clearTimeout(indexSearchTimer)
    indexSearchTimer = null
  }
  if (!trimmed) {
    indexResults.value = []
    indexLoading.value = false
    indexError.value = ''
    indexSearchToken += 1 // 取消任何正在 inflight 的请求
    return
  }
  // 进入搜索态时立即翻 loading=true，遮蔽 debounce + 请求期 No Data 闪屏。
  // 注意：先清旧 results 再翻 loading，确保 template 命中 indexLoading 分支而非 No Data。
  indexResults.value = []
  indexError.value = ''
  indexSoftHint.value = ''
  indexLoading.value = true
  indexSearchTimer = setTimeout(() => {
    runIndexSearch(trimmed)
  }, 300)
})

// 流式索引搜索（本地库用）返回的统一形态 → picker 列表 row
function mapSearchEntry (entry) {
  return {
    name: entry?.name || '',
    path: entry?.absolute_path || '',
    relative_path: entry?.relative_path || '',
    modified_time: entry?.mtime || null,
    is_directory: entry?.entry_type === 'dir',
    rjcode: entry?.rjcode || '',
    source: entry?.source || 'index',
  }
}

// XSS 安全的 HTML 转义：v-html 渲染前必须 escape 原文本，再把 keyword 包成 <mark>。
function escapeHtml (text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeRegExp (text) {
  return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// 搜索模式下把命中的 keyword（不区分大小写）用 <mark> 包起来。非搜索模式直接返回 escape 后的文本。
function highlightKeyword (text) {
  const raw = String(text || '')
  const safe = escapeHtml(raw)
  if (!inIndexSearchMode.value) return safe
  const kw = String(searchKeyword.value || '').trim()
  if (!kw) return safe
  const escapedKw = escapeRegExp(escapeHtml(kw))
  try {
    return safe.replace(new RegExp(escapedKw, 'gi'), m => `<mark class="fm-mark">${m}</mark>`)
  } catch (_) {
    return safe
  }
}

// browseFiles（/api/library/browser/files）返回的远程库 entry → picker 列表 row
// 字段名差异：path / modified_time(ISO) / is_directory，直接对齐 picker 内部约定
// 注意保留 library_id，用于过滤掉「跨库搜索」混入的非当前库结果（global_search_files 会跨所有远程库）。
function mapBrowseEntry (entry) {
  return {
    name: entry?.name || '',
    path: entry?.path || '',
    relative_path: entry?.relative_path || '',
    modified_time: entry?.modified_time || null,
    is_directory: Boolean(entry?.is_directory),
    rjcode: entry?.rjcode || '',
    library_id: entry?.library_id || '',
    source: 'remote',
  }
}

// 搜索分支：
//   - 远程库（synology_filestation）：直接调 browseFiles（后端会转 SYNO.Search），单次返回；
//     不走索引兜底流，因为远程库通常没有索引，stream 协议徒增延迟。
//   - 本地库：走索引流式搜索（initial+library+done），命中后立即可见，未命中静默兜底扫描。
// 任何文案都不暴露「索引 / 兜底 / SYNO.Search / os.walk」等技术词。
async function runIndexSearch(keyword) {
  if (!library.value?.id) return
  if (indexSearchAbort) {
    try { indexSearchAbort.abort() } catch (_) { /* ignore */ }
  }
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  indexSearchAbort = controller
  const token = ++indexSearchToken
  indexLoading.value = true
  indexError.value = ''
  indexSoftHint.value = ''

  const isRemote = library.value?.type === 'synology_filestation'

  // === 远程库分支：直接调 browseFiles ===
  if (isRemote) {
    try {
      const data = await libraryApi.browseFiles({
        libraryId: library.value.id,
        page: 1,
        pageSize: 200,
        search: keyword,
        sortBy: 'name',
        sortOrder: 'asc',
        searchResultKind: 'folder',
        // scope=current：让后端只搜当前库，不再跨所有远程库并发等最慢的那个，显著提速。
        // 顺带也避免了别库 path（如 /ANIME/...）混入结果导致点击越界。
        scope: 'current',
      })
      if (token !== indexSearchToken) return
      const files = Array.isArray(data?.files) ? data.files : []
      indexResults.value = files.map(mapBrowseEntry).filter(item => item.path)
      if (data?.search_truncated) {
        indexSoftHint.value = `结果较多，已仅展示前 ${indexResults.value.length} 条，请输入更精确的关键字`
      }
    } catch (err) {
      if (err?.name === 'CanceledError' || err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return
      if (token !== indexSearchToken) return
      indexError.value = err?.response?.data?.detail || err?.message || '搜索失败，请稍后重试'
      indexResults.value = []
    } finally {
      if (token === indexSearchToken) {
        indexLoading.value = false
      }
    }
    return
  }

  // === 本地库分支：流式索引搜索（命中立显，未命中自动兜底） ===
  let accumulated = []
  let willRunFallback = false

  try {
    for await (const event of libraryApi.searchIndexGlobalStream({
      keyword,
      libraryIds: [library.value.id],
      entryType: 'dir',
      mode: 'full',
      limit: 200,
      signal: controller ? controller.signal : undefined,
    })) {
      if (token !== indexSearchToken) return

      if (event?.type === 'initial') {
        const items = Array.isArray(event.items) ? event.items : []
        accumulated = items.map(mapSearchEntry).filter(item => item.path)
        indexResults.value = accumulated
        willRunFallback = Boolean(event.will_run_fallback)
        if (!willRunFallback) {
          indexLoading.value = false
        }
      } else if (event?.type === 'library') {
        const items = Array.isArray(event.items) ? event.items : []
        const newItems = items.map(mapSearchEntry).filter(item => item.path)
        accumulated = [...accumulated, ...newItems]
        indexResults.value = accumulated
      } else if (event?.type === 'done') {
        indexLoading.value = false
        const failed = Array.isArray(event.fallback_failed) ? event.fallback_failed : []
        if (failed.length && !accumulated.length) {
          indexSoftHint.value = '搜索失败，请稍后重试'
        }
      }
    }
  } catch (err) {
    if (err?.name === 'CanceledError' || err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return
    if (token !== indexSearchToken) return
    indexError.value = err?.response?.data?.detail || err?.message || '搜索失败，请稍后重试'
    indexResults.value = []
  } finally {
    if (token === indexSearchToken) {
      indexLoading.value = false
    }
  }
}

// ---------------- 初始化 ----------------

async function initFromProps () {
  resetState()
  if (!library.value?.id) {
    // 异常 case：picker 被打开但没传 library；不调 loadFolders，需要手动收掉 spinner。
    loading.value = false
    return
  }
  const initialAbsolute = resolveInitialAbsolutePath()
  await loadFolders(initialAbsolute || '')
  // 加载左侧根节点子项
  navTreeState.rootExpanded = true
  await loadNavRoot()
}

function resolveInitialAbsolutePath () {
  // initialRelativePath 是相对 library.root_path 的相对路径（与 effectiveRelativePath 对称），
  // 拼回 absolute 时也要用 root_path 做基准；但浏览只能落在 browse_root_path 内，
  // 当 root_path 比 browse_root_path 浅（即配了 browse_path）时，候选 absolute 会越过
  // browse 边界，此时回退到 browse_root_path 作为浏览起点。
  const root = stripTrailingSlash(String(library.value?.root_path || '').trim())
  const browseRoot = stripTrailingSlash(String(library.value?.browse_root_path || '').trim())
  const rel = String(props.initialRelativePath || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  const baseRoot = root || browseRoot
  if (!baseRoot) return ''
  const candidate = rel ? joinPosix(baseRoot, rel) : baseRoot
  if (browseRoot && !pathIsInside(candidate, browseRoot)) {
    return browseRoot
  }
  return candidate
}

function pathIsInside (target, root) {
  const targetNorm = stripTrailingSlash(String(target || '')).toLowerCase()
  const rootNorm = stripTrailingSlash(String(root || '')).toLowerCase()
  if (!targetNorm || !rootNorm) return false
  if (targetNorm === rootNorm) return true
  return targetNorm.startsWith(`${rootNorm}/`)
}

function resetState () {
  currentPath.value = ''
  rootPath.value = ''
  folders.value = []
  // 保持 true：resetState 后逻辑上总会调 loadFolders，Vue 未及渲染中间状态以避免 No Data 闪屏。
  loading.value = true
  error.value = ''
  selectedFolderPath.value = ''
  searchKeyword.value = ''
  indexResults.value = []
  indexLoading.value = false
  indexError.value = ''
  indexSoftHint.value = ''
  indexSearchToken += 1
  if (indexSearchTimer) {
    clearTimeout(indexSearchTimer)
    indexSearchTimer = null
  }
  if (indexSearchAbort) {
    try { indexSearchAbort.abort() } catch (_) { /* ignore */ }
    indexSearchAbort = null
  }
  sortBy.value = 'name'
  sortDir.value = 'asc'
  navTreeState.rootExpanded = false
  navTreeState.rootChildren = null
  navTreeState.rootLoading = false
  navTreeState.rootError = ''
  for (const key of Object.keys(navTreeState.nodes)) delete navTreeState.nodes[key]
}

// ---------------- 加载 ----------------

async function loadFolders (path) {
  if (!library.value?.id) return
  loading.value = true
  error.value = ''
  selectedFolderPath.value = ''
  try {
    const data = await libraryApi.browserListFolders(
      library.value.id,
      path || '',
      // 远程库忽略 computeSize；这里同时取文件 + 目录方便用户在右侧看到完整内容
      { includeFiles: true }
    )
    rootPath.value = data?.browse_root_path || data?.library_root_path || rootPath.value || ''
    currentPath.value = data?.current_path || rootPath.value
    folders.value = Array.isArray(data?.folders) ? data.folders : []
    syncNavTreeFromLoad(currentPath.value, rootPath.value, folders.value)
    await nextTick()
    listScrollRef.value?.scrollTo?.({ top: 0 })
  } catch (err) {
    folders.value = []
    error.value = err?.response?.data?.detail || err?.message || '读取目录失败'
  } finally {
    loading.value = false
  }
}

async function loadNavRoot () {
  if (!library.value?.id) return
  if (navTreeState.rootChildren !== null && !navTreeState.rootError) return
  navTreeState.rootLoading = true
  navTreeState.rootError = ''
  try {
    const data = await libraryApi.browserListFolders(library.value.id, '', { includeFiles: false })
    if (data?.browse_root_path) rootPath.value = data.browse_root_path
    navTreeState.rootChildren = (data?.folders || []).map(item => ({ name: item.name, path: item.path }))
  } catch (err) {
    navTreeState.rootError = err?.response?.data?.detail || err?.message || '读取目录失败'
    navTreeState.rootChildren = []
  } finally {
    navTreeState.rootLoading = false
  }
}

async function loadNavChildrenForPath (path) {
  const node = ensureNodeEntry(path)
  if (node.loading) return
  node.loading = true
  node.error = ''
  try {
    const data = await libraryApi.browserListFolders(library.value.id, path, { includeFiles: false })
    node.children = (data?.folders || []).map(item => ({ name: item.name, path: item.path }))
  } catch (err) {
    node.error = err?.response?.data?.detail || err?.message || '读取目录失败'
    node.children = []
  } finally {
    node.loading = false
  }
}

function ensureNodeEntry (path) {
  if (!navTreeState.nodes[path]) {
    navTreeState.nodes[path] = { expanded: false, children: null, loading: false, error: '' }
  }
  return navTreeState.nodes[path]
}

function syncNavTreeFromLoad (path, root, list) {
  if (!path || !root) return
  const dirsOnly = (list || [])
    .filter(item => item?.is_directory !== false)
    .map(item => ({ name: item.name, path: item.path }))
  if (normalizePath(path) === normalizePath(root)) {
    navTreeState.rootChildren = dirsOnly
    navTreeState.rootExpanded = true
    return
  }
  const node = ensureNodeEntry(path)
  node.children = dirsOnly
  node.expanded = true
  // 把祖先全部展开
  let cursor = parentOfPosix(path)
  const rootNormalized = normalizePath(root)
  while (cursor && normalizePath(cursor) !== rootNormalized) {
    const ancestor = ensureNodeEntry(cursor)
    ancestor.expanded = true
    const next = parentOfPosix(cursor)
    if (next === cursor) break
    cursor = next
  }
  navTreeState.rootExpanded = true
}

// ---------------- 交互 ----------------

async function toggleRootExpand () {
  if (loading.value || props.submitting) return
  navTreeState.rootExpanded = !navTreeState.rootExpanded
  if (navTreeState.rootExpanded && navTreeState.rootChildren === null) {
    await loadNavRoot()
  }
}

async function toggleNodeExpand (path) {
  if (loading.value || props.submitting || !path) return
  const node = ensureNodeEntry(path)
  node.expanded = !node.expanded
  if (node.expanded && node.children === null) {
    await loadNavChildrenForPath(path)
  }
}

async function navigateToPath (path) {
  if (!path || loading.value || props.submitting) return
  // 双击搜索结果跳转时，需要主动退出搜索模式：
  // 否则 inIndexSearchMode=true 会让 filteredFolders 继续锁定旧 indexResults，
  // 用户视觉上看不到新目录的子项 → 误以为"点不到下一级目录"。
  if (inIndexSearchMode.value) {
    searchKeyword.value = ''
  }
  await loadFolders(path)
}

async function reload () {
  if (!library.value?.id) return
  await loadFolders(currentPath.value || '')
}

async function goUp () {
  if (!canGoUp.value) return
  const parent = parentOfPosix(currentPath.value)
  await loadFolders(parent || rootPath.value || '')
}

function selectFolder (folder) {
  if (!folder) return
  if (!isFolderEntry(folder)) return
  const path = folder.path
  if (!path) return
  selectedFolderPath.value = path === selectedFolderPath.value ? '' : path
}

function handleListKeydown (event) {
  if (loading.value || !filteredFolders.value.length) return
  const dirList = filteredFolders.value.filter(isFolderEntry)
  if (!dirList.length) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    const idx = dirList.findIndex(f => f.path === selectedFolderPath.value)
    selectedFolderPath.value = dirList[Math.min(dirList.length - 1, idx + 1)].path
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    const idx = dirList.findIndex(f => f.path === selectedFolderPath.value)
    selectedFolderPath.value = dirList[Math.max(0, idx - 1)].path
  } else if (event.key === 'Enter') {
    if (!selectedFolderPath.value) return
    event.preventDefault()
    navigateToPath(selectedFolderPath.value)
  }
}

function handleCancel () {
  if (props.submitting) return
  emit('update:visible', false)
  emit('close')
}

function handleVisibleUpdate (next) {
  if (next === false) {
    handleCancel()
  } else {
    emit('update:visible', Boolean(next))
  }
}

function handleSubmit () {
  if (!canSubmit.value) {
    if (!effectiveAbsolutePath.value) {
      ElMessage.warning('请选择一个目录')
    }
    return
  }
  emit('submit', {
    targetSubdir: effectiveRelativePath.value,
    targetAbsolutePath: effectiveAbsolutePath.value,
    libraryId: library.value?.id || ''
  })
}

// ---------------- 工具 ----------------

function isFolderEntry (item) {
  return item?.is_directory !== false
}

// 图标与颜色全部委托给库存页共享 helper（8 类 + dir 9 类），与 Library.vue / LibrarySearchOverlay
// / ActivityRichBlock 使用同一套 kind 划分，避免这里重复手写决策表。
function normalizeFolderEntry (item) {
  return { is_directory: isFolderEntry(item), name: item?.name || '' }
}

function iconMetaForFolder (item) {
  return libraryEntryMetaFor(normalizeFolderEntry(item))
}

function classifyFolderKind (item) {
  return classifyLibraryEntryKind(normalizeFolderEntry(item))
}

function formatFolderTime (value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
}

function normalizePath (path) {
  return stripTrailingSlash(String(path || '')).toLowerCase()
}

function stripTrailingSlash (path) {
  return String(path || '').replace(/[\\/]+$/, '')
}

function parentOfPosix (path) {
  const value = stripTrailingSlash(String(path || ''))
  if (!value) return ''
  const idx = value.lastIndexOf('/')
  if (idx <= 0) return '/'
  return value.slice(0, idx) || '/'
}

function joinPosix (base, relative) {
  const b = stripTrailingSlash(String(base || '')) || '/'
  const r = String(relative || '').replace(/^[\\/]+/, '').replace(/\\/g, '/')
  if (!r) return b
  if (b === '/') return `/${r}`
  return `${b}/${r}`
}

function isPathInsideRoot (path) {
  const root = stripTrailingSlash(String(rootPath.value || ''))
  const target = stripTrailingSlash(String(path || ''))
  if (!root || !target) return false
  if (target === root) return true
  return target.toLowerCase().startsWith(`${root.toLowerCase()}/`)
}

function toRelativePath (absolutePath, root) {
  const rootRaw = stripTrailingSlash(String(root || ''))
  const target = stripTrailingSlash(String(absolutePath || ''))
  if (!rootRaw || !target) return ''
  if (target.toLowerCase() === rootRaw.toLowerCase()) return ''
  if (target.toLowerCase().startsWith(`${rootRaw.toLowerCase()}/`)) {
    return target.slice(rootRaw.length + 1)
  }
  return ''
}

// ---------------- 左侧导航宽度拖拽 ----------------

function clampNavWidth (value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return NAV_DEFAULT_WIDTH
  return Math.max(NAV_MIN_WIDTH, Math.min(NAV_MAX_WIDTH, num))
}

function onSplitterPointerDown (event) {
  if (!event || event.button !== 0) return
  event.preventDefault()
  isResizingNav.value = true
  navResizeStart.x = event.clientX
  navResizeStart.width = navWidth.value
  if (typeof window !== 'undefined') {
    window.addEventListener('pointermove', onSplitterPointerMove, { passive: false })
    window.addEventListener('pointerup', onSplitterPointerUp, { passive: false })
    window.addEventListener('pointercancel', onSplitterPointerUp, { passive: false })
  }
  if (typeof document !== 'undefined' && document.body) {
    document.body.dataset.remoteFolderPickerResizing = '1'
  }
}

function onSplitterPointerMove (event) {
  if (!isResizingNav.value) return
  event.preventDefault()
  const delta = event.clientX - navResizeStart.x
  navWidth.value = clampNavWidth(navResizeStart.width + delta)
}

function onSplitterPointerUp () {
  if (!isResizingNav.value) return
  isResizingNav.value = false
  if (typeof window !== 'undefined') {
    window.removeEventListener('pointermove', onSplitterPointerMove)
    window.removeEventListener('pointerup', onSplitterPointerUp)
    window.removeEventListener('pointercancel', onSplitterPointerUp)
  }
  if (typeof document !== 'undefined' && document.body) {
    delete document.body.dataset.remoteFolderPickerResizing
  }
}

function resetNavWidth () {
  navWidth.value = NAV_DEFAULT_WIDTH
}

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('pointermove', onSplitterPointerMove)
    window.removeEventListener('pointerup', onSplitterPointerUp)
    window.removeEventListener('pointercancel', onSplitterPointerUp)
  }
  if (typeof document !== 'undefined' && document.body) {
    delete document.body.dataset.remoteFolderPickerResizing
  }
})
</script>

<style scoped>
/* el-dialog 适配 ---------------------------------------------------- */
:deep(.el-dialog__header) { display: none; }
:deep(.el-dialog__body) { padding: 0; }
:deep(.el-dialog) {
  background: transparent;
  box-shadow: none;
  border-radius: 24px;
}

/* 玻璃外壳 -------------------------------------------------------- */
.glass-shell {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.62), rgba(255, 255, 255, 0.36)),
    rgba(255, 255, 255, 0.34);
  border: 1px solid rgba(255, 255, 255, 0.5);
  outline: 1px solid rgba(255, 255, 255, 0.52);
  outline-offset: -2px;
  box-shadow: none;
  backdrop-filter: blur(34px) saturate(145%);
  -webkit-backdrop-filter: blur(34px) saturate(145%);
}

.is-resizing,
.is-resizing * {
  user-select: none !important;
  cursor: col-resize !important;
}

.panel-enter {
  animation: panel-enter 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes panel-enter {
  from { opacity: 0; transform: translateY(10px) scale(0.985); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.window-header {
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.4), rgba(255, 255, 255, 0.05));
}

.no-scrollbar { scrollbar-width: none; -ms-overflow-style: none; }
.no-scrollbar::-webkit-scrollbar { display: none; }

/* 顶部工具栏 ------------------------------------------------------ */
.explorer-toolbar {
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(248, 250, 252, 0.55);
}

.fm-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.9);
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.fm-icon-btn:hover {
  background: white;
  color: #0f172a;
  border-color: rgba(15, 23, 42, 0.18);
}

.fm-icon-btn:active:not(:disabled) { transform: scale(0.96); }

.fm-icon-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 面包屑 -------------------------------------------------------- */
.path-bar {
  height: 28px;
  padding: 0 6px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.crumb-btn {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 6px;
  border: 0;
  background: transparent;
  color: #475569;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.crumb-btn:hover {
  background: rgba(15, 23, 42, 0.06);
  color: #0f172a;
}

.crumb-btn-disk { color: #1e293b; font-weight: 600; }

.crumb-btn-current {
  color: #0f172a;
  font-weight: 600;
  background: rgba(15, 23, 42, 0.06);
}

.crumb-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.crumb-text {
  display: inline-block;
  max-width: 280px;
  vertical-align: middle;
}

.crumb-text-disk { max-width: 260px; }

.crumb-btn-current .crumb-text { max-width: 460px; }

/* 搜索 -------------------------------------------------------- */
.search-wrap {
  position: relative;
  width: 200px;
  flex-shrink: 0;
}

.search-input {
  width: 100%;
  padding: 5px 10px 5px 26px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.95);
  font-size: 12px;
  color: #1e293b;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.search-input:focus {
  border-color: rgba(15, 23, 42, 0.32);
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.08);
}

.search-input:disabled { background: rgba(248, 250, 252, 0.7); }

/* 主区 ---------------------------------------------------------- */
.explorer-main {
  background: rgba(255, 255, 255, 0.4);
}

.explorer-nav {
  flex-shrink: 0;
  border-right: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(248, 250, 252, 0.5);
}

.nav-splitter {
  position: relative;
  flex: 0 0 auto;
  width: 1px;
  align-self: stretch;
  cursor: col-resize;
  background: transparent;
  display: flex;
  align-items: stretch;
  justify-content: center;
  user-select: none;
  touch-action: none;
  z-index: 2;
}

.nav-splitter::before {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  left: -4px;
  right: -4px;
  background: transparent;
}

.nav-splitter-line {
  display: block;
  width: 1px;
  height: 100%;
  background: rgba(15, 23, 42, 0.08);
  transition: background-color 0.18s ease;
}

.nav-splitter:hover .nav-splitter-line { background: rgba(71, 85, 105, 0.38); }
.nav-splitter-active .nav-splitter-line,
.nav-splitter:active .nav-splitter-line { background: rgba(51, 65, 85, 0.62); }

.nav-section-title {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.6px;
  text-transform: uppercase;
  color: #94a3b8;
}

.nav-tree {
  list-style: none;
  margin: 0;
  padding: 0 6px;
}

.nav-item { list-style: none; }

.nav-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px 6px 0;
  cursor: pointer;
  user-select: none;
  font-size: 12.5px;
  color: #1e293b;
  border-radius: 6px;
  border: 1px solid transparent;
  transition:
    background-color 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
    border-color 0.22s ease,
    transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
    color 0.22s ease;
}

.nav-row:hover {
  background: rgba(15, 23, 42, 0.05);
  border-color: rgba(15, 23, 42, 0.06);
  transform: translate3d(0, -1px, 0);
}

.nav-row-active {
  background: rgba(100, 116, 139, 0.14);
  border-color: rgba(100, 116, 139, 0.2);
  color: #1e293b;
  font-weight: 600;
}

.nav-row-active:hover { background: rgba(100, 116, 139, 0.18); }

.nav-expander {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  flex-shrink: 0;
  transition: background-color 0.15s ease;
}

.nav-expander:hover { background: rgba(15, 23, 42, 0.08); }
.nav-expander:disabled { opacity: 0.4; cursor: not-allowed; }

.nav-disk-icon {
  color: #64748b;
  flex-shrink: 0;
}

.nav-row-active .nav-disk-icon { color: #475569; }

.nav-row-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-children {
  list-style: none;
  margin: 0;
  padding: 0;
}

.nav-row-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: #94a3b8;
  padding: 4px 12px 4px 0;
  list-style: none;
}

.nav-row-meta-error { color: #be123c; }

/* 右侧：表头 / 行 ---------------------------------------------- */
.explorer-list {
  background: white;
}

.fm-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px;
  align-items: center;
  padding: 0 18px;
  height: 32px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(248, 250, 252, 0.65);
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  letter-spacing: 0.3px;
}

.fm-head .fm-cell-time {
  border-left: 1px solid rgba(15, 23, 42, 0.05);
  padding-left: 12px;
}

.fm-head-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: 0;
  padding: 0;
  font: inherit;
  color: inherit;
  letter-spacing: inherit;
  cursor: pointer;
  height: 100%;
  user-select: none;
  transition: color 0.15s ease;
}

.fm-head .fm-head-cell.fm-cell-name {
  padding-left: 0;
  padding-right: 8px;
}

.fm-head .fm-head-cell.fm-cell-time {
  padding-left: 12px;
}

.fm-head-cell:hover {
  color: #1f2937;
}

.fm-head-cell-active {
  color: #1e293b;
}

.fm-head-arrow {
  color: #64748b;
  transform: rotate(0deg);
  transition: transform 0.18s ease;
}

.fm-head-arrow-asc {
  transform: rotate(180deg);
}

.fm-body {
  display: flex;
  flex-direction: column;
  padding: 4px 0;
  outline: none;
}

.fm-soft-hint {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 8px 12px 4px;
  padding: 8px 10px;
  border-radius: 8px;
  background: linear-gradient(180deg, rgba(254, 243, 199, 0.62), rgba(254, 240, 138, 0.42));
  border: 1px solid rgba(245, 158, 11, 0.25);
  color: #a16207;
  font-size: 11.5px;
  line-height: 1.5;
}

.fm-soft-hint > svg {
  flex-shrink: 0;
  margin-top: 1px;
}

.fm-body:focus-visible {
  box-shadow: inset 0 0 0 2px rgba(125, 211, 252, 0.6);
}

.fm-state {
  flex: 1 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 36px 0;
  color: #64748b;
  font-size: 12.5px;
}

.fm-state-col {
  flex-direction: column;
  gap: 6px;
}

/* 加载态：只保留旋转 icon + 错落入场文字（无玻璃球、无外圈） ----- */
.fm-loading-state {
  gap: 14px;
  padding: 48px 0;
  animation: fm-loading-fade-in 0.36s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes fm-loading-fade-in {
  from { opacity: 0; transform: translateY(8px) scale(0.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

.fm-loading-icon {
  color: #475569;
  animation: fm-loading-spin 1.1s linear infinite;
}

@keyframes fm-loading-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.fm-loading-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #0f172a;
  letter-spacing: 0.01em;
  animation: fm-loading-text-in 0.4s 0.1s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

.fm-loading-desc {
  font-size: 11.5px;
  color: #64748b;
  animation: fm-loading-text-in 0.4s 0.18s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes fm-loading-text-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.fm-empty-wrap {
  flex: 1 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  min-height: 240px;
}

.fm-retry-btn {
  margin-top: 4px;
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.92);
  font-size: 12px;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
}

.fm-retry-btn:hover { background: white; color: #0f172a; }

.fm-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px;
  align-items: center;
  padding: 0 18px;
  min-height: 32px;
  cursor: pointer;
  user-select: none;
  font-size: 12.5px;
  color: #1e293b;
  transition:
    background-color 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
    border-color 0.22s ease,
    box-shadow 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
    transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
    color 0.22s ease;
  border: 1px solid transparent;
}

/* 搜索模式下 row 多一行 relative_path，需要撑高并把内容对齐到顶部，
   否则 fm-name-rel 会溢出 32px 边界落到 row 之外，导致点击副行无法触发 row click。 */
.fm-row-search {
  align-items: flex-start;
  padding: 8px 18px;
  min-height: 48px;
}

.fm-row:hover {
  background: rgba(15, 23, 42, 0.04);
  border-color: rgba(15, 23, 42, 0.06);
  box-shadow: none;
  transform: translate3d(0, -1px, 0);
}

/* 搜索关键字高亮：用 <mark> 渲染，命中部分轻量 chip 风格不抢眼。 */
.fm-row .fm-mark {
  background: linear-gradient(180deg, rgba(254, 240, 138, 0.95) 0%, rgba(253, 224, 71, 0.85) 100%);
  color: #713f12;
  padding: 0 3px;
  border-radius: 4px;
  font-weight: 600;
  box-shadow: inset 0 -1px 0 rgba(202, 138, 4, 0.25);
}

.fm-row-selected .fm-mark {
  background: linear-gradient(180deg, rgba(254, 215, 170, 0.95) 0%, rgba(253, 186, 116, 0.9) 100%);
  color: #7c2d12;
  box-shadow: inset 0 -1px 0 rgba(194, 65, 12, 0.35);
}

.fm-cell {
  display: flex;
  align-items: center;
  min-width: 0;
}

.fm-cell-name {
  gap: 8px;
  padding-right: 12px;
}

.fm-cell-time {
  padding-left: 12px;
  font-size: 11.5px;
  color: #64748b;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.fm-icon-shell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

/* 颜色现在都由 helper meta.color 通过 inline :style 赋值，这里只保留过渡动画。 */
.fm-kind-icon { transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
/* lucide 默认 fill="none"，dir 这些需要填充色的 kind 走 helper meta.fillIcon -> fm-kind-icon-fill。 */
.fm-kind-icon-fill { fill: currentColor; stroke: currentColor; }

.fm-name-wrap {
  flex: 1 1 auto;
  min-width: 0;
  line-height: 1.25;
}

.fm-name {
  display: block;
  font-weight: 500;
}

.fm-name-rel {
  display: block;
  margin-top: 1px;
  font-size: 11px;
  font-weight: 400;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.fm-row-selected {
  background: rgba(100, 116, 139, 0.14);
  border-color: rgba(100, 116, 139, 0.22);
  box-shadow: none;
}

.fm-row-selected:hover {
  background: rgba(100, 116, 139, 0.18);
  box-shadow: none;
}

.fm-row-selected .fm-cell-time { color: #334155; }

.fm-row-file {
  cursor: default;
  color: #475569;
}

.fm-row-file:hover { background: rgba(15, 23, 42, 0.025); }

.fm-row-file .fm-cell-time { color: #94a3b8; }

/* 底部 footer ---------------------------------------------------- */
.footer-row {
  border-top: 1px solid rgba(15, 23, 42, 0.06);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.4));
}

/* 目标 chip ------------------------------------------------------ */
.target-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px 4px 8px;
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(15, 23, 42, 0.08);
  min-width: 0;
  max-width: 520px;
}

.target-chip-path {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  color: #1e293b;
  font-weight: 500;
  min-width: 0;
}

.rel-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(186, 230, 253, 0.45);
  border: 1px solid rgba(2, 132, 199, 0.18);
  font-size: 11px;
  min-width: 0;
  max-width: 360px;
}

.rel-chip-default {
  background: rgba(241, 245, 249, 0.85);
  border-color: rgba(15, 23, 42, 0.08);
}

.rel-chip-label {
  font-weight: 600;
  color: #0c4a6e;
  letter-spacing: 0.3px;
  flex-shrink: 0;
}

.rel-chip-default .rel-chip-label { color: #475569; }

.rel-chip-value {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 500;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 滚动条 --------------------------------------------------------- */
.fm-body::-webkit-scrollbar,
.nav-scroll::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.fm-body::-webkit-scrollbar-track,
.nav-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.fm-body::-webkit-scrollbar-thumb,
.nav-scroll::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.12);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}

.fm-body::-webkit-scrollbar-thumb:hover,
.nav-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.24);
  background-clip: content-box;
}
</style>

<!--
  非 scoped 全局样式：el-dialog teleport 到 body 下，
  通过弹框独占的 class 局部覆盖尺寸 / overlay。
-->
<style>
.remote-folder-picker-modal.el-dialog {
  width: min(1320px, calc(100vw - 32px)) !important;
  max-width: min(1320px, calc(100vw - 32px)) !important;
}

.remote-folder-picker-modal .window {
  height: min(768px, calc(100vh - 64px));
  max-height: calc(100vh - 64px);
}

.remote-folder-picker-overlay.custom-preview-overlay,
.remote-folder-picker-overlay {
  background: transparent !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

body[data-remote-folder-picker-resizing="1"] {
  cursor: col-resize !important;
  user-select: none !important;
}

@media (max-width: 640px) {
  .remote-folder-picker-modal.el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
  .remote-folder-picker-modal .el-dialog__body {
    height: 100dvh !important;
    max-height: 100dvh !important;
    overflow: hidden !important;
    padding: 0 !important;
  }
  .remote-folder-picker-modal .window {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    height: 100% !important;
    max-height: 100% !important;
    border-radius: 0 !important;
  }
  .remote-folder-picker-modal .window-header {
    position: relative;
    padding: 14px 52px 12px 16px !important;
    align-items: flex-start !important;
  }
  .remote-folder-picker-modal .window-header > div:first-child {
    min-width: 0;
    max-width: 100%;
  }
  .remote-folder-picker-modal .title {
    font-size: 20px !important;
    line-height: 1.2;
  }
  .remote-folder-picker-modal .window-header p {
    display: flex;
    flex-wrap: wrap;
    gap: 3px 6px;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }
  .remote-folder-picker-modal .window-header p span {
    margin-left: 0 !important;
  }
  .remote-folder-picker-modal .close-button {
    position: absolute;
    top: 12px;
    right: 12px;
    width: 34px !important;
    height: 34px !important;
  }
  .remote-folder-picker-modal .explorer-toolbar {
    display: grid !important;
    grid-template-columns: auto auto minmax(0, 1fr);
    gap: 8px !important;
    padding: 10px 12px !important;
  }
  .remote-folder-picker-modal .path-bar {
    grid-column: 1 / -1;
    order: 3;
    width: 100%;
    min-width: 0;
  }
  .remote-folder-picker-modal .search-wrap {
    grid-column: 1 / -1;
    order: 4;
    width: 100% !important;
  }
  .remote-folder-picker-modal .explorer-main {
    flex: 1 1 auto;
    min-height: 0;
    flex-direction: column !important;
    overflow: hidden;
  }
  .remote-folder-picker-modal .explorer-nav {
    width: 100% !important;
    max-height: 32dvh;
    flex: 0 0 auto;
    border-right: 0 !important;
    border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  }
  .remote-folder-picker-modal .nav-splitter {
    display: none !important;
  }
  .remote-folder-picker-modal .nav-scroll {
    max-height: calc(32dvh - 26px);
    overflow-y: auto !important;
  }
  .remote-folder-picker-modal .explorer-list {
    flex: 1 1 auto;
    min-height: 0;
    width: 100%;
    min-width: 0;
    overflow: hidden;
  }
  .remote-folder-picker-modal .fm-head {
    display: none !important;
  }
  .remote-folder-picker-modal .fm-body {
    min-width: 0;
    overflow-x: hidden !important;
    overflow-y: auto !important;
    padding: 8px 10px;
  }
  .remote-folder-picker-modal .fm-row {
    display: flex !important;
    grid-template-columns: none !important;
    align-items: center;
    width: 100%;
    min-width: 0;
    min-height: 40px;
    padding: 8px 10px !important;
    border-radius: 12px;
  }
  .remote-folder-picker-modal .fm-cell-name {
    flex: 1 1 auto;
    min-width: 0;
    padding-right: 0 !important;
  }
  .remote-folder-picker-modal .fm-cell-time {
    display: none !important;
  }
  .remote-folder-picker-modal .fm-name {
    min-width: 0;
    white-space: normal !important;
    overflow-wrap: anywhere;
    line-height: 1.35;
  }
  .remote-folder-picker-modal .footer-row {
    flex: 0 0 auto;
    flex-direction: column !important;
    align-items: stretch !important;
    gap: 10px !important;
    padding: 10px 14px calc(12px + env(safe-area-inset-bottom)) !important;
  }
  .remote-folder-picker-modal .footer-left {
    display: grid !important;
    grid-template-columns: 1fr;
    width: 100%;
    gap: 8px !important;
  }
  .remote-folder-picker-modal .target-chip,
  .remote-folder-picker-modal .rel-chip {
    max-width: none !important;
    width: 100%;
  }
  .remote-folder-picker-modal .target-chip-path,
  .remote-folder-picker-modal .rel-chip-value {
    min-width: 0;
    white-space: normal !important;
    overflow-wrap: anywhere;
  }
  .remote-folder-picker-modal .footer-actions {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    width: 100%;
    gap: 10px !important;
  }
  .remote-folder-picker-modal .primary-cta,
  .remote-folder-picker-modal .secondary-cta {
    width: 100%;
    min-width: 0;
    height: 48px !important;
    padding-left: 12px !important;
    padding-right: 12px !important;
  }
}
</style>
