<template>
  <el-dialog
    :model-value="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal lib-move-modal"
    align-center
    modal-class="custom-preview-overlay lib-move-overlay"
    @update:model-value="handleVisibleUpdate"
  >
    <div
      class="window panel-enter glass-shell relative w-full rounded-3xl flex flex-col overflow-hidden"
      :class="{ 'is-resizing': isResizingNav }"
    >
      <!-- 顶部：标题 + 关闭 -->
      <div class="window-header flex items-center justify-between px-7 py-4">
        <div class="min-w-0">
          <h1 class="title text-[20px] font-bold text-slate-900 tracking-tight">移动到...</h1>
          <p class="mt-0.5 text-[12px] text-slate-500">
            <span class="font-semibold text-slate-700">{{ items.length }}</span> 项待移动 · {{ sourceTypeText }}
            <span v-if="sourceLibraryName"> · 来自 <span class="text-slate-700">{{ sourceLibraryName }}</span></span>
          </p>
        </div>
        <button
          type="button"
          class="interactive-chip close-button inline-flex size-9 items-center justify-center rounded-full text-slate-400 hover:text-slate-700"
          :disabled="submitting"
          @click="handleCancel"
          aria-label="关闭"
        >
          <X :size="18" :stroke-width="2" />
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
          :disabled="loading || submitting || !currentLibraryId"
          @click="reload"
          title="刷新"
        >
          <RefreshCw :size="14" :stroke-width="2.2" :class="{ 'animate-spin': loading }" />
        </button>

        <!-- 面包屑路径栏 -->
        <div class="path-bar flex items-center gap-0.5 flex-1 min-w-0 overflow-x-auto no-scrollbar">
          <template v-if="currentLibrary">
            <button
              type="button"
              class="crumb-btn crumb-btn-disk"
              :disabled="loading || submitting"
              @click="navigateToPath(rootPath)"
              :title="rootPath"
            >
              <HardDrive :size="13" :stroke-width="2.2" class="text-amber-500" />
              <span class="ml-1 truncate crumb-text crumb-text-disk">{{ currentLibrary.name }}</span>
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
          </template>
          <span v-else class="path-empty text-[12px] text-slate-400 px-2">请在左侧选择一个本地库存</span>
        </div>

        <!-- 搜索框 -->
        <div class="search-wrap">
          <Search :size="12" :stroke-width="2.2" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          <input
            v-model="searchKeyword"
            type="text"
            class="search-input"
            :placeholder="currentLibrary ? `在「${currentLibrary.name}」中搜索` : '搜索'"
            :disabled="!currentLibraryId || submitting"
            spellcheck="false"
          />
        </div>
      </div>

      <!-- 主区：左 nav + 拖拽分割线 + 右 list -->
      <div class="explorer-main flex-1 flex min-h-0">
        <!-- 左侧：库存 / 目录树 -->
        <aside
          class="explorer-nav flex flex-col min-w-0"
          :style="{ width: navWidth + 'px' }"
        >
          <div class="nav-section-title px-4 pt-3 pb-1">本地库存</div>
          <div class="nav-scroll flex-1 min-h-0 overflow-y-auto no-scrollbar pb-3">
            <div v-if="!localLibraries.length" class="px-4 py-6 text-[12px] text-slate-400">
              没有可用的本地库存
            </div>
            <ul v-else class="nav-tree">
              <li v-for="lib in localLibraries" :key="lib.id" class="nav-item">
                <div
                  class="nav-row"
                  :class="{
                    'nav-row-active': lib.id === currentLibraryId && normalizePath(currentPath) === normalizePath(lib.root_path || lib.path),
                    'nav-row-source': lib.id === sourceLibraryId
                  }"
                  :style="{ paddingLeft: '12px' }"
                  @click="selectLibraryRoot(lib)"
                  :title="lib.id === sourceLibraryId ? `源所在库：${lib.root_path || lib.path}` : (lib.root_path || lib.path)"
                >
                  <button
                    type="button"
                    class="nav-expander"
                    :disabled="loading || submitting"
                    @click.stop="toggleLibraryExpand(lib)"
                  >
                    <ChevronDown
                      v-if="isLibraryExpanded(lib.id)"
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
                  <span class="nav-row-name">{{ lib.name }}</span>
                </div>

                <!-- 子目录递归 -->
                <ul v-if="isLibraryExpanded(lib.id)" class="nav-children">
                  <LibraryMoveNavNode
                    v-for="child in getLibraryChildren(lib.id)"
                    :key="child.path"
                    :node="child"
                    :depth="1"
                    :library-id="lib.id"
                    :tree-state="navTreeState"
                    :current-path="currentPath"
                    :current-library-id="currentLibraryId"
                    :loading="loading"
                    :submitting="submitting"
                    @navigate="navigateToPath"
                    @toggle="toggleNodeExpand"
                  />
                </ul>
              </li>
            </ul>
          </div>
        </aside>

        <!-- 拖拽分割条：左右拉伸左侧导航宽度，双击重置 -->
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

        <!-- 右侧：当前目录文件列表 -->
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
            <div class="fm-cell fm-cell-size">大小</div>
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
            <div v-if="inIndexSearchMode && indexLoading" class="fm-state fm-state-col fm-loading-state">
              <Loader2 :size="48" :stroke-width="2" class="fm-loading-icon" />
              <span class="fm-loading-title">正在搜索</span>
              <span class="fm-loading-desc">「{{ searchKeyword }}」</span>
            </div>
            <div v-else-if="inIndexSearchMode && indexError" class="fm-state fm-state-col">
              <AlertCircle :size="22" :stroke-width="2" class="text-rose-500" />
              <span class="text-rose-600">{{ indexError }}</span>
            </div>
            <div v-else-if="loading && !inIndexSearchMode" class="fm-state fm-state-col fm-loading-state">
              <Loader2 :size="48" :stroke-width="2" class="fm-loading-icon" />
              <span class="fm-loading-title">正在读取目录</span>
              <span class="fm-loading-desc">同步库存子项中…</span>
            </div>
            <div v-else-if="error && !inIndexSearchMode" class="fm-state fm-state-col">
              <AlertCircle :size="22" :stroke-width="2" class="text-rose-500" />
              <span class="text-rose-600">{{ error }}</span>
              <button type="button" class="fm-retry-btn" @click="reload">重试</button>
            </div>
            <div v-else-if="!filteredFolders.length" class="fm-empty-wrap">
              <AppEmptyState
                :description="inIndexSearchMode ? `没有匹配「${searchKeyword}」的目录` : (searchKeyword ? '没有匹配的子目录' : '此目录下没有子目录')"
                size="default"
              >
                <span class="text-[11px] text-slate-400">点击"移动到此处"将移到当前目录</span>
              </AppEmptyState>
            </div>
            <div
              v-for="(folder, idx) in filteredFolders"
              v-else
              :key="folder.path"
              :data-folder-index="idx"
              class="fm-row"
              :class="{
                'fm-row-selected': selectedFolderPath === folder.path,
                'fm-row-self': isSourceFolder(folder.path),
                'fm-row-conflict': isFolderEntry(folder) && conflictNameSet.has(folder.name),
                'fm-row-file': !isFolderEntry(folder)
              }"
              :title="folderRowTitle(folder)"
              @click="selectFolder(folder)"
              @dblclick="isFolderEntry(folder) && navigateToPath(folder.path)"
            >
              <div class="fm-cell fm-cell-name">
                <span class="fm-icon-shell">
                  <component
                    :is="folderIconComponent(folder)"
                    :size="16"
                    :stroke-width="2.2"
                    :class="folderIconClass(folder)"
                  />
                </span>
                <span class="fm-name">{{ folder.name }}</span>
                <!-- 源不再用文字 chip 标识，依靠左侧 2px 琥珀色细条 + opacity 表达 -->
                <span v-if="isFolderEntry(folder) && !isSourceFolder(folder.path) && conflictNameSet.has(folder.name)" class="fm-tag fm-tag-conflict">同名</span>
              </div>
              <div class="fm-cell fm-cell-size">{{ formatFolderSize(folder) }}</div>
              <div class="fm-cell fm-cell-time">{{ formatFolderTime(folder.modified_time) }}</div>
            </div>
          </div>
        </section>
      </div>

      <!-- 底部：待移动条目 chips + 目标 + CTA -->
      <div class="footer-row flex items-center justify-between gap-4 px-7 py-4">
        <div class="footer-left flex items-center gap-3 min-w-0 flex-1">
          <div class="src-chip-stack flex flex-wrap gap-1.5 min-w-0">
            <span
              v-for="item in displayItems"
              :key="item.path"
              class="src-chip"
              :title="item.path"
            >
              <Folder
                v-if="item.is_directory"
                :size="11"
                :stroke-width="2.2"
                class="src-chip-folder"
              />
              <FileIcon v-else :size="11" :stroke-width="2.2" class="src-chip-file" />
              <span class="max-w-[150px] truncate">{{ item.name }}</span>
            </span>
            <span v-if="items.length > MAX_ITEMS_PREVIEW" class="src-chip src-chip-more">
              +{{ items.length - MAX_ITEMS_PREVIEW }} 项
            </span>
          </div>
          <div class="target-chip" :title="effectiveTargetPath">
            <ArrowRight :size="13" :stroke-width="2.4" class="text-slate-400 shrink-0" />
            <span class="text-[11.5px] text-slate-500 shrink-0">移动到</span>
            <span class="target-chip-path truncate">{{ effectiveTargetPath || '-' }}</span>
            <span v-if="conflictCount > 0" class="conflict-pill" :title="conflictNamesText">
              <AlertCircle :size="11" :stroke-width="2.4" />
              <span>{{ conflictCount }} 同名</span>
            </span>
          </div>
        </div>
        <div class="footer-actions flex items-center gap-2.5 shrink-0">
          <button
            type="button"
            class="secondary-cta interactive-button px-6 h-10 rounded-lg font-semibold"
            :disabled="submitting"
            @click="handleCancel"
          >取消</button>
          <button
            type="button"
            class="primary-cta px-6 h-10 rounded-lg font-bold text-white"
            :disabled="!canSubmit"
            @click="handleSubmit"
          >
            <span v-if="submitting" class="inline-flex items-center gap-1.5"><Loader2 :size="14" class="animate-spin" />移动中</span>
            <span v-else>移动到此处</span>
          </button>
        </div>
      </div>

      <!-- 同名冲突子面板 -->
      <transition name="conflict-fade">
        <div v-if="conflictDialogOpen" class="conflict-overlay" @click.self="cancelConflict">
          <div class="conflict-panel" role="dialog" aria-modal="true">
            <header class="conflict-panel-head">
              <span class="conflict-panel-icon">
                <AlertCircle :size="16" :stroke-width="2.2" />
              </span>
              <div class="min-w-0">
                <h4 class="conflict-panel-title">目标目录已存在 {{ conflictCount }} 个同名项</h4>
                <p class="conflict-panel-sub">请选择处理方式</p>
              </div>
            </header>
            <ul class="conflict-list">
              <li v-for="name in conflictNamesPreview" :key="name">
                <Folder :size="12" :stroke-width="2.2" class="src-chip-folder" />
                <span class="truncate">{{ name }}</span>
              </li>
              <li v-if="conflictCount > conflictNamesPreview.length" class="conflict-list-more">
                +{{ conflictCount - conflictNamesPreview.length }} 项
              </li>
            </ul>
            <div class="conflict-actions">
              <button type="button" class="conflict-btn conflict-btn-primary" @click="confirmConflict('suffix')">
                <Plus :size="13" :stroke-width="2.4" />
                <span>追加序号</span>
              </button>
              <button type="button" class="conflict-btn conflict-btn-danger" @click="confirmConflict('overwrite')">
                <RefreshCw :size="13" :stroke-width="2.4" />
                <span>覆盖现有</span>
              </button>
              <button type="button" class="conflict-btn conflict-btn-ghost" @click="confirmConflict('skip')">
                <SkipForward :size="13" :stroke-width="2.4" />
                <span>跳过同名</span>
              </button>
              <button type="button" class="conflict-btn conflict-btn-cancel" @click="cancelConflict">取消</button>
            </div>
          </div>
        </div>
      </transition>
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
  File as FileIcon,
  FileText,
  Folder,
  HardDrive,
  Loader2,
  Music,
  Plus,
  RefreshCw,
  Search,
  SkipForward,
  X
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'

import { libraryApi } from '../../api'
import LibraryMoveNavNode from './LibraryMoveNavNode.vue'
import AppEmptyState from '../common/AppEmptyState.vue'

const MAX_ITEMS_PREVIEW = 12

// 左侧导航宽度（可拖拽）：默认 280，区间 [200, 520]，双击恢复默认
const NAV_DEFAULT_WIDTH = 280
const NAV_MIN_WIDTH = 200
const NAV_MAX_WIDTH = 520
// 进入子目录时一次性算大小的上限，避免一次扫数千个 RJ 把磁盘 IO 打满
const FOLDER_SIZE_COMPUTE_CAP = 256

const props = defineProps({
  visible: { type: Boolean, default: false },
  sourceLibraryId: { type: String, default: '' },
  items: { type: Array, default: () => [] },
  libraries: { type: Array, default: () => [] },
  submitting: { type: Boolean, default: false }
})

const emit = defineEmits(['update:visible', 'submit', 'close'])

const currentLibraryId = ref('')
const currentPath = ref('')
const rootPath = ref('')
const folders = ref([])
const loading = ref(false)
const error = ref('')
const selectedFolderPath = ref('')
const searchKeyword = ref('')
const pathInput = ref('')
const listScrollRef = ref(null)

const conflictDialogOpen = ref(false)
const pendingTargetSnapshot = ref(null)

// 左侧导航宽度 + 拖拽状态
const navWidth = ref(NAV_DEFAULT_WIDTH)
const isResizingNav = ref(false)
const navResizeStart = { x: 0, width: NAV_DEFAULT_WIDTH }

// 库存导航树状态： navTreeState[libraryId] = { rootExpanded, rootChildren, rootLoading, rootError, nodes: { [path]: { expanded, children, loading, error } } }
const navTreeState = reactive({})

const CONFLICT_PREVIEW_MAX = 8

const sourceNameSet = computed(() => {
  const set = new Set()
  for (const item of props.items || []) {
    const name = String(item?.name || '').trim().toLowerCase()
    if (name) set.add(name)
  }
  return set
})

// 当前层目录中与源同名的（小写名集合，仅做提示用）
const conflictNameSet = computed(() => {
  const set = new Set()
  if (!sourceNameSet.value.size) return set
  for (const folder of folders.value) {
    const lower = String(folder?.name || '').toLowerCase()
    if (sourceNameSet.value.has(lower)) set.add(folder.name)
  }
  return set
})

const conflictCount = computed(() => conflictNameSet.value.size)

const conflictNamesPreview = computed(() => Array.from(conflictNameSet.value).slice(0, CONFLICT_PREVIEW_MAX))

const conflictNamesText = computed(() => Array.from(conflictNameSet.value).join('、'))

const localLibraries = computed(() =>
  (Array.isArray(props.libraries) ? props.libraries : []).filter(lib => lib?.type === 'local' && lib?.id && lib?.writable !== false)
)

const currentLibrary = computed(() => localLibraries.value.find(item => item.id === currentLibraryId.value) || null)

const rootLabel = computed(() => currentLibrary.value?.name || '本地库')

const displayItems = computed(() => (Array.isArray(props.items) ? props.items.slice(0, MAX_ITEMS_PREVIEW) : []))

const hasDirectorySource = computed(() => (props.items || []).some(item => item?.is_directory))

const hasFileSource = computed(() => (props.items || []).some(item => !item?.is_directory))

const sourceTypeText = computed(() => {
  if (hasDirectorySource.value && hasFileSource.value) return '包含目录与文件'
  if (hasDirectorySource.value) return '全部为目录'
  if (hasFileSource.value) return '全部为文件'
  return '未选中条目'
})

const sourceLibraryName = computed(() => {
  const libs = Array.isArray(props.libraries) ? props.libraries : []
  const found = libs.find(item => item?.id === props.sourceLibraryId)
  return found?.name || ''
})

const sourcePathSet = computed(() => {
  const set = new Set()
  for (const item of props.items || []) {
    const value = String(item?.path || '').trim()
    if (value) set.add(normalizePath(value))
  }
  return set
})

const sourceParentSet = computed(() => {
  const set = new Set()
  for (const item of props.items || []) {
    const path = String(item?.path || '').trim()
    if (!path) continue
    const parent = parentOf(path)
    if (parent) set.add(normalizePath(parent))
  }
  return set
})

const breadcrumbs = computed(() => {
  if (!currentLibraryId.value || !currentPath.value || !rootPath.value) return []
  const root = normalizePath(rootPath.value)
  const cur = normalizePath(currentPath.value)
  if (root === cur) return []
  // 在 rootPath 之下取相对路径
  const sep = detectSeparator(currentPath.value)
  const rel = currentPath.value.slice(rootPath.value.length).replace(/^[\\/]+/, '')
  if (!rel) return []
  const parts = rel.split(/[\\/]+/).filter(Boolean)
  const accumulated = []
  let cursor = rootPath.value.replace(/[\\/]+$/, '')
  for (const segment of parts) {
    cursor = `${cursor}${sep}${segment}`
    accumulated.push({ name: segment, path: cursor })
  }
  return accumulated
})

const canGoUp = computed(() => {
  if (!currentLibraryId.value || !currentPath.value || !rootPath.value) return false
  return normalizePath(currentPath.value) !== normalizePath(rootPath.value)
})

// 列头排序
const sortBy = ref('name')
const sortDir = ref('asc')

// 索引搜索状态
const indexResults = ref([])
const indexLoading = ref(false)
const indexError = ref('')
let indexSearchToken = 0
let indexSearchTimer = null
let indexSearchAbort = null

// 是否处于索引搜索模式（搜索框非空）
const inIndexSearchMode = computed(() => String(searchKeyword.value || '').trim().length > 0)

const filteredFolders = computed(() => {
  const source = inIndexSearchMode.value ? indexResults.value : folders.value
  const list = Array.isArray(source) ? [...source] : []
  return sortFolderList(list)
})

function sortFolderList (list) {
  const dir = sortDir.value === 'desc' ? -1 : 1
  const by = sortBy.value
  list.sort((a, b) => {
    const aDir = a?.is_directory !== false
    const bDir = b?.is_directory !== false
    if (aDir !== bDir) return aDir ? -1 : 1
    if (by === 'mtime') {
      const at = Number(a?.modified_time || 0)
      const bt = Number(b?.modified_time || 0)
      if (at !== bt) return (at - bt) * dir
      return String(a?.name || '').localeCompare(String(b?.name || ''), 'zh-Hans-CN', { numeric: true }) * dir
    }
    return String(a?.name || '').localeCompare(String(b?.name || ''), 'zh-Hans-CN', { numeric: true }) * dir
  })
  return list
}

function onColumnSort (field) {
  if (sortBy.value === field) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = field
    sortDir.value = 'asc'
  }
}

function mapIndexEntry (entry) {
  return {
    name: entry?.name || '',
    path: entry?.absolute_path || '',
    relative_path: entry?.relative_path || '',
    modified_time: entry?.mtime || null,
    is_directory: entry?.entry_type === 'dir',
    rjcode: entry?.rjcode || '',
    source: 'index',
  }
}

// watch searchKeyword：debounce 300ms 触发索引搜索
watch(searchKeyword, (keyword) => {
  const trimmed = String(keyword || '').trim()
  if (indexSearchTimer) { clearTimeout(indexSearchTimer); indexSearchTimer = null }
  if (!trimmed) {
    indexResults.value = []
    indexLoading.value = false
    indexError.value = ''
    indexSearchToken += 1
    return
  }
  indexResults.value = []
  indexError.value = ''
  indexLoading.value = true
  indexSearchTimer = setTimeout(() => { runIndexSearch(trimmed) }, 300)
})

async function runIndexSearch (keyword) {
  if (!currentLibraryId.value) return
  if (indexSearchAbort) { try { indexSearchAbort.abort() } catch (_) {} }
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  indexSearchAbort = controller
  const token = ++indexSearchToken
  indexLoading.value = true
  indexError.value = ''
  let accumulated = []
  try {
    for await (const event of libraryApi.searchIndexGlobalStream({
      keyword,
      libraryIds: [currentLibraryId.value],
      entryType: 'dir',
      mode: 'full',
      limit: 200,
      signal: controller ? controller.signal : undefined,
    })) {
      if (token !== indexSearchToken) return
      if (event?.type === 'initial') {
        accumulated = Array.isArray(event.items) ? event.items.map(mapIndexEntry).filter(i => i.path) : []
        indexResults.value = accumulated
        if (!event.will_run_fallback) indexLoading.value = false
      } else if (event?.type === 'library') {
        const newItems = Array.isArray(event.items) ? event.items.map(mapIndexEntry).filter(i => i.path) : []
        accumulated = [...accumulated, ...newItems]
        indexResults.value = accumulated
      } else if (event?.type === 'done') {
        indexLoading.value = false
      }
    }
  } catch (err) {
    if (err?.name === 'CanceledError' || err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return
    if (token !== indexSearchToken) return
    indexError.value = err?.response?.data?.detail || err?.message || '搜索失败，请稍后重试'
    indexResults.value = []
  } finally {
    if (token === indexSearchToken) indexLoading.value = false
  }
}

const effectiveTargetPath = computed(() => {
  if (selectedFolderPath.value) return selectedFolderPath.value
  return currentPath.value
})

const targetEqualsSourceParent = computed(() => {
  const target = normalizePath(effectiveTargetPath.value)
  if (!target) return false
  return sourceParentSet.value.has(target)
})

const targetIsSourceOrChild = computed(() => {
  const target = normalizePath(effectiveTargetPath.value)
  if (!target) return false
  for (const src of sourcePathSet.value) {
    if (target === src) return true
    if (target.startsWith(src + detectSeparator(src))) return true
  }
  return false
})

const canSubmit = computed(() => {
  if (props.submitting || loading.value) return false
  if (!currentLibraryId.value || !effectiveTargetPath.value) return false
  if (targetEqualsSourceParent.value) return false
  if (targetIsSourceOrChild.value) return false
  if (!props.items.length) return false
  return true
})

watch(() => props.visible, async (next) => {
  if (next) {
    await initFromProps()
  } else {
    resetState()
  }
})

watch(() => props.sourceLibraryId, async () => {
  if (!props.visible) return
  await initFromProps()
})

watch(() => props.libraries, async () => {
  if (!props.visible) return
  if (!localLibraries.value.length) return
  if (!currentLibraryId.value) {
    await initFromProps()
  }
})

async function initFromProps () {
  resetState()
  // 默认选中源所在库（若属于本地库列表）；否则选第一个本地库
  const wantId = String(props.sourceLibraryId || '').trim()
  let initial = localLibraries.value.find(item => item.id === wantId)
  if (!initial) initial = localLibraries.value[0] || null
  if (!initial) return
  currentLibraryId.value = initial.id
  await loadFolders('')
}

function resetState () {
  currentLibraryId.value = ''
  currentPath.value = ''
  rootPath.value = ''
  folders.value = []
  loading.value = false
  error.value = ''
  selectedFolderPath.value = ''
  searchKeyword.value = ''
  pathInput.value = ''
  // 重置索引搜索状态
  indexResults.value = []
  indexLoading.value = false
  indexError.value = ''
  indexSearchToken += 1
  if (indexSearchTimer) { clearTimeout(indexSearchTimer); indexSearchTimer = null }
  // 清空导航树
  for (const key of Object.keys(navTreeState)) delete navTreeState[key]
}

function ensureLibraryEntry (libraryId) {
  if (!navTreeState[libraryId]) {
    navTreeState[libraryId] = {
      rootExpanded: false,
      rootChildren: null,
      rootLoading: false,
      rootError: '',
      nodes: {}
    }
  }
  return navTreeState[libraryId]
}

function ensureNodeEntry (libraryId, path) {
  const lib = ensureLibraryEntry(libraryId)
  if (!lib.nodes[path]) {
    lib.nodes[path] = { expanded: false, children: null, loading: false, error: '' }
  }
  return lib.nodes[path]
}

function getLibraryChildren (libraryId) {
  return navTreeState[libraryId]?.rootChildren || []
}

function isLibraryExpanded (libraryId) {
  return Boolean(navTreeState[libraryId]?.rootExpanded)
}

async function loadNavChildrenForRoot (lib) {
  const entry = ensureLibraryEntry(lib.id)
  if (entry.rootLoading) return
  entry.rootLoading = true
  entry.rootError = ''
  try {
    const data = await libraryApi.browserListFolders(lib.id, '')
    const baseRoot = data?.browse_root_path || data?.library_root_path || lib.root_path || lib.path || ''
    entry.rootChildren = (data?.folders || []).map(item => ({ name: item.name, path: item.path }))
    if (baseRoot && lib.id === currentLibraryId.value && !rootPath.value) {
      rootPath.value = baseRoot
    }
  } catch (err) {
    entry.rootError = err?.response?.data?.detail || err?.message || '读取目录失败'
    entry.rootChildren = []
  } finally {
    entry.rootLoading = false
  }
}

async function loadNavChildrenForPath (libraryId, path) {
  const node = ensureNodeEntry(libraryId, path)
  if (node.loading) return
  node.loading = true
  node.error = ''
  try {
    const data = await libraryApi.browserListFolders(libraryId, path)
    node.children = (data?.folders || []).map(item => ({ name: item.name, path: item.path }))
  } catch (err) {
    node.error = err?.response?.data?.detail || err?.message || '读取目录失败'
    node.children = []
  } finally {
    node.loading = false
  }
}

async function toggleLibraryExpand (lib) {
  if (loading.value || props.submitting) return
  const entry = ensureLibraryEntry(lib.id)
  entry.rootExpanded = !entry.rootExpanded
  if (entry.rootExpanded && entry.rootChildren === null) {
    await loadNavChildrenForRoot(lib)
  }
}

async function toggleNodeExpand ({ libraryId, path }) {
  if (loading.value || props.submitting) return
  const node = ensureNodeEntry(libraryId, path)
  node.expanded = !node.expanded
  if (node.expanded && node.children === null) {
    await loadNavChildrenForPath(libraryId, path)
  }
}

async function selectLibraryRoot (lib) {
  if (loading.value || props.submitting) return
  if (currentLibraryId.value !== lib.id) {
    currentLibraryId.value = lib.id
    rootPath.value = ''
    currentPath.value = ''
  }
  // 推入根跳转
  await loadFolders('')
  // 默认展开该库的根节点
  const entry = ensureLibraryEntry(lib.id)
  entry.rootExpanded = true
  if (entry.rootChildren === null) await loadNavChildrenForRoot(lib)
}

async function loadFolders (path) {
  if (!currentLibraryId.value) return
  loading.value = true
  error.value = ''
  selectedFolderPath.value = ''
  try {
    // 进入"非根目录"（即用户点进了某个社团/合集子目录，下一层通常就是 RJ 作品）后，
    // 才让后端按需统计 size。避免在 root 顶层一次性扫几千个社团目录把磁盘 IO 打满。
    const targetPath = path || ''
    const knownRoot = rootPath.value || ''
    const isAtRoot = !targetPath || (knownRoot && normalizePath(targetPath) === normalizePath(knownRoot))
    const data = await libraryApi.browserListFolders(
      currentLibraryId.value,
      targetPath,
      {
        computeSize: !isAtRoot,
        computeSizeCap: FOLDER_SIZE_COMPUTE_CAP,
        // 右侧文件列表既显示子目录也显示文件（参考库存页风格），文件不可作为目标
        includeFiles: true
      }
    )
    rootPath.value = data?.browse_root_path || data?.library_root_path || ''
    currentPath.value = data?.current_path || rootPath.value
    pathInput.value = currentPath.value
    folders.value = Array.isArray(data?.folders) ? data.folders : []
    searchKeyword.value = ''
    // 同步进导航树缓存
    syncNavTreeFromLoad(currentLibraryId.value, currentPath.value, rootPath.value, folders.value)
    await nextTick()
    listScrollRef.value?.scrollTo?.({ top: 0 })
  } catch (err) {
    folders.value = []
    error.value = err?.response?.data?.detail || err?.message || '读取目录失败'
  } finally {
    loading.value = false
  }
}

function syncNavTreeFromLoad (libraryId, path, root, list) {
  if (!libraryId) return
  const entry = ensureLibraryEntry(libraryId)
  // 导航树只展示目录：过滤掉 is_directory=false 的文件项；旧数据没有该字段时按目录处理
  const simplified = (list || [])
    .filter(item => item?.is_directory !== false)
    .map(item => ({ name: item.name, path: item.path }))
  // 是否在根
  if (!root || normalizePath(path) === normalizePath(root)) {
    entry.rootChildren = simplified
    entry.rootExpanded = true
  } else {
    const node = ensureNodeEntry(libraryId, path)
    node.children = simplified
    node.expanded = true
    // 路径上面的所有祖先都设为 expanded（不重新拉取 children）
    let cursor = parentOf(path)
    while (cursor && normalizePath(cursor) !== normalizePath(root) && cursor.length > 0) {
      const ancestor = ensureNodeEntry(libraryId, cursor)
      ancestor.expanded = true
      const next = parentOf(cursor)
      if (next === cursor) break
      cursor = next
    }
    entry.rootExpanded = true
  }
}

async function switchLibrary (libraryId) {
  if (!libraryId || libraryId === currentLibraryId.value || loading.value) return
  currentLibraryId.value = libraryId
  rootPath.value = ''
  currentPath.value = ''
  await loadFolders('')
}

async function reload () {
  if (!currentLibraryId.value) return
  await loadFolders(currentPath.value || '')
}

async function goUp () {
  if (!canGoUp.value) return
  const parent = parentOf(currentPath.value)
  await loadFolders(parent || '')
}

async function navigateToPath (path) {
  if (!path || loading.value || props.submitting) return
  await loadFolders(path)
}

async function navigateToInput () {
  const value = String(pathInput.value || '').trim()
  if (!value) return
  await loadFolders(value)
}

// 是否为目录条目：旧数据没有 is_directory 字段时按目录处理（兼容性）
function isFolderEntry (item) {
  return item?.is_directory !== false
}

// 库存页风格的图标选择：目录 → Folder（琥珀填充），音频/文本/其他文件用对应 lucide 图标
function folderIconComponent (item) {
  if (isFolderEntry(item)) return Folder
  const name = String(item?.name || '').toLowerCase()
  if (/\.(wav|flac|mp3|m4a|ogg|aac|wma|opus)$/.test(name)) return Music
  if (/\.(txt|md|json|cue|srt|ass|ssa|vtt|lrc|xml|yaml|yml|log)$/.test(name)) return FileText
  return FileIcon
}

function folderIconClass (item) {
  if (isFolderEntry(item)) return 'fm-folder-icon'
  const name = String(item?.name || '').toLowerCase()
  if (/\.(wav|flac|alac|aiff)$/.test(name)) return 'fm-file-icon-audio-lossless'
  if (/\.(mp3|m4a|ogg|aac|wma|opus)$/.test(name)) return 'fm-file-icon-audio'
  if (/\.(txt|md|json|cue|srt|ass|ssa|vtt|lrc|xml|yaml|yml|log)$/.test(name)) return 'fm-file-icon-text'
  return 'fm-file-icon-default'
}

function selectFolder (folder) {
  if (!folder) return
  // 文件不能作为移动目标，点击文件不改变选中态
  if (!isFolderEntry(folder)) return
  const path = folder.path
  if (!path) return
  selectedFolderPath.value = path === selectedFolderPath.value ? '' : path
}

function handleListKeydown (event) {
  if (loading.value || !filteredFolders.value.length) return
  // 方向键 / 回车只在"目录条目"上跳转，跳过文件
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

function isSourceFolder (path) {
  return sourcePathSet.value.has(normalizePath(path))
}

function folderRowTitle (folder) {
  // 把"是否是源 / 是否同名 / 完整路径"合并到一个 title 提示里，
  // 替代之前在行内放"源"文字 chip 的方案，视觉更克制。
  if (!folder) return ''
  const path = folder.path || ''
  if (isSourceFolder(path)) return `当前的待移动项 · ${path}`
  if (conflictNameSet.value.has(folder.name)) return `与源同名 · ${path}`
  return path
}

function handleCancel () {
  if (props.submitting) return
  conflictDialogOpen.value = false
  pendingTargetSnapshot.value = null
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
    if (targetEqualsSourceParent.value) {
      ElMessage.warning('目标目录就是源所在目录，无需移动')
    } else if (targetIsSourceOrChild.value) {
      ElMessage.warning('不能移动到所选目录自身或其子目录')
    }
    return
  }
  const snapshot = {
    targetLibraryId: currentLibraryId.value,
    targetPath: effectiveTargetPath.value
  }
  // 同名检测：仅基于已加载的当前层 folders（精确度有限，但能覆盖主要场景）
  if (conflictCount.value > 0 && normalizePath(effectiveTargetPath.value) === normalizePath(currentPath.value)) {
    pendingTargetSnapshot.value = snapshot
    conflictDialogOpen.value = true
    return
  }
  emit('submit', { ...snapshot, conflictStrategy: 'suffix' })
}

function confirmConflict (strategy) {
  const snapshot = pendingTargetSnapshot.value
  conflictDialogOpen.value = false
  pendingTargetSnapshot.value = null
  if (!snapshot) return
  emit('submit', { ...snapshot, conflictStrategy: strategy })
}

function cancelConflict () {
  conflictDialogOpen.value = false
  pendingTargetSnapshot.value = null
}

function formatFolderSize (folder) {
  if (!folder) return '—'
  const status = String(folder.size_status || '')
  if (status === 'pending' || folder.size === null || folder.size === undefined) return '—'
  const formatted = formatBytes(folder.size)
  return status === 'stale' ? `${formatted} *` : formatted
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

function formatBytes (bytes) {
  const value = Number(bytes)
  if (!Number.isFinite(value) || value < 0) return '—'
  if (value === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const exp = Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024)))
  const num = value / Math.pow(1024, exp)
  const fixed = num >= 100 ? num.toFixed(0) : num >= 10 ? num.toFixed(1) : num.toFixed(2)
  return `${fixed} ${units[exp]}`
}

function detectSeparator (path) {
  return /\\/.test(String(path || '')) ? '\\' : '/'
}

function parentOf (path) {
  const value = String(path || '')
  if (!value) return ''
  const sep = detectSeparator(value)
  const trimmed = value.replace(/[\\/]+$/, '')
  const idx = trimmed.lastIndexOf(sep)
  if (idx <= 0) return trimmed
  return trimmed.slice(0, idx)
}

function normalizePath (path) {
  return String(path || '').replace(/[\\/]+$/, '').toLowerCase()
}

// ----- 左侧导航宽度拖拽 -----
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
    document.body.dataset.libMoveResizing = '1'
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
    delete document.body.dataset.libMoveResizing
  }
}

function resetNavWidth () {
  navWidth.value = NAV_DEFAULT_WIDTH
}

onBeforeUnmount(() => {
  // 兜底卸载时清理拖拽监听，避免泄漏
  if (typeof window !== 'undefined') {
    window.removeEventListener('pointermove', onSplitterPointerMove)
    window.removeEventListener('pointerup', onSplitterPointerUp)
    window.removeEventListener('pointercancel', onSplitterPointerUp)
  }
  if (typeof document !== 'undefined' && document.body) {
    delete document.body.dataset.libMoveResizing
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
  /* 弹框主体进一步透明：让背后页面尽量"看穿"，再用 backdrop blur 把穿过来的内容糊掉，
     这才是真正的毛玻璃质感（弹框区域内糊，弹框区域外清晰）。 */
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.42), rgba(255, 255, 255, 0.24)),
    rgba(255, 255, 255, 0.32);
  border: 1px solid rgba(255, 255, 255, 0.5);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.55),
    0 22px 50px rgba(15, 23, 42, 0.12),
    0 38px 110px rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(38px) saturate(190%);
  -webkit-backdrop-filter: blur(38px) saturate(190%);
}

/* 拖拽时禁用文本选中和过渡，避免抖动 */
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

/* 顶部 ---------------------------------------------------------- */
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

/* 路径栏 / 面包屑 ------------------------------------------------- */
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

.crumb-btn-root { color: #475569; font-weight: 600; }

.crumb-btn-disk { color: #1e293b; font-weight: 600; }

.crumb-btn-current {
  color: #0f172a;
  font-weight: 600;
  background: rgba(15, 23, 42, 0.06);
}

.crumb-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* 面包屑文本宽度：默认中间级 280px，库存名 260px，当前级（最末一级）放宽到 460px。
   path-bar 已经 overflow-x scroll，超长会滚，不会挤掉搜索框。 */
.crumb-text {
  display: inline-block;
  max-width: 280px;
  vertical-align: middle;
}

.crumb-text-disk {
  max-width: 260px;
}

.crumb-btn-current .crumb-text {
  max-width: 460px;
}

/* 搜索框 -------------------------------------------------------- */
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

/* 主区：左侧导航 + 右侧文件 -------------------------------------- */
.explorer-main {
  background: rgba(255, 255, 255, 0.4);
}

.explorer-nav {
  /* 宽度由 navWidth ref 通过 inline :style 控制；此处只定边框与背景 */
  flex-shrink: 0;
  border-right: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(248, 250, 252, 0.5);
}

/* 拖拽分割条：视觉始终是一根 1px 细线，命中区域用透明伪元素扩到 ~9px 方便鼠标抓取，
   hover/拖拽只换颜色不变粗，避免看起来像一条粗带子。 */
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

/* 透明命中区域：左右各扩 4px，让鼠标更容易抓到，但视觉宽度仍是 1px */
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

.nav-splitter:hover .nav-splitter-line {
  background: rgba(14, 165, 233, 0.55);
}

.nav-splitter-active .nav-splitter-line,
.nav-splitter:active .nav-splitter-line {
  background: rgba(14, 165, 233, 0.9);
}

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
  transition: background-color 0.15s ease;
}

.nav-row:hover { background: rgba(15, 23, 42, 0.05); }

.nav-row-active {
  background: rgba(186, 230, 253, 0.55);
  color: #0c4a6e;
  font-weight: 600;
}

.nav-row-active:hover { background: rgba(186, 230, 253, 0.7); }

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

.nav-row-active .nav-disk-icon { color: #0284c7; }

.nav-row-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 源所在库存：行最左侧嵌入一道 2px 琥珀色细条（替代原来"源"字胶囊），
   视觉更克制；hover/active 时色条略加深 */
.nav-row-source {
  box-shadow: inset 2px 0 0 rgba(245, 158, 11, 0.55);
}

.nav-row-source:hover {
  box-shadow: inset 2px 0 0 rgba(245, 158, 11, 0.7);
}

.nav-row-active.nav-row-source,
.nav-row-active.nav-row-source:hover {
  /* 选中态以蓝色高亮为主，保留少量琥珀提示但让位给主色 */
  box-shadow: inset 2px 0 0 rgba(245, 158, 11, 0.85);
}

.nav-children {
  list-style: none;
  margin: 0;
  padding: 0;
}

/* 右侧：表头 / 行 ---------------------------------------------- */
.explorer-list {
  background: white;
}

.fm-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 110px 160px;
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

.fm-head .fm-cell-size,
.fm-head .fm-cell-time {
  border-left: 1px solid rgba(15, 23, 42, 0.05);
  padding-left: 12px;
}

/* 可点击列头排序按鈕 */
.fm-head-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  color: inherit;
  font-size: inherit;
  font-weight: inherit;
  letter-spacing: inherit;
  transition: color 0.15s;
  text-align: left;
}
.fm-head-cell:hover {
  color: #334155;
}
.fm-head-cell-active {
  color: #3b82f6;
}
.fm-head-arrow {
  flex-shrink: 0;
  transform: rotate(180deg);
  transition: transform 0.2s ease;
}
.fm-head-arrow-asc {
  transform: rotate(0deg);
}

/* fm-body 改成 flex column，让"加载中 / 错误 / 空态"等单行子元素能 flex:1 撑满剩余高度并垂直居中 */
.fm-body {
  display: flex;
  flex-direction: column;
  padding: 4px 0;
  outline: none;
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
  color: #0284c7;
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

/* 空目录容器：撑满 fm-body 剩余高度，把 AppEmptyState 居中 */
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
  grid-template-columns: minmax(0, 1fr) 110px 160px;
  align-items: center;
  padding: 0 18px;
  height: 32px;
  cursor: pointer;
  user-select: none;
  font-size: 12.5px;
  color: #1e293b;
  transition: background-color 0.15s ease;
}

.fm-row:hover { background: rgba(15, 23, 42, 0.04); }

.fm-cell {
  display: flex;
  align-items: center;
  min-width: 0;
}

.fm-cell-name {
  gap: 8px;
  padding-right: 12px;
}

.fm-cell-size,
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

/* 库存页风格：目录琥珀色填充，文件按类型用语义色（无填充） */
.fm-folder-icon {
  color: #f59e0b;
  fill: currentColor;
  stroke: currentColor;
}

.fm-file-icon-audio-lossless { color: #0f766e; }
.fm-file-icon-audio { color: #0ea5e9; }
.fm-file-icon-text { color: #8b5cf6; }
.fm-file-icon-default { color: #94a3b8; }

.fm-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.fm-tag {
  flex-shrink: 0;
  padding: 0 7px;
  height: 16px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.4px;
  margin-left: 6px;
}

/* 同名标签：低饱和红 + 细描边（保留这个文字提示，因为表达"同名冲突"用图形不易理解） */
.fm-tag-conflict {
  background: rgba(239, 68, 68, 0.10);
  color: #b91c1c;
  border-color: rgba(239, 68, 68, 0.30);
}

.fm-row-selected {
  background: rgba(186, 230, 253, 0.45);
  box-shadow: inset 2px 0 0 rgba(2, 132, 199, 0.7);
}

.fm-row-selected:hover { background: rgba(186, 230, 253, 0.6); }

.fm-row-selected .fm-cell-size,
.fm-row-selected .fm-cell-time {
  color: #0c4a6e;
}

/* 源所在行：用左侧 2px 琥珀色细条 + 轻度 opacity 表达"这是待移动项"，
   不再依赖"源"文字 chip，视觉更克制；hover 时恢复对比度方便阅读 */
.fm-row-self {
  opacity: 0.82;
  box-shadow: inset 2px 0 0 rgba(245, 158, 11, 0.55);
}

.fm-row-self:hover { opacity: 0.96; }

/* 同时选中且为源时，主选中蓝色优先，保证选中态可识别 */
.fm-row-selected.fm-row-self {
  opacity: 1;
  box-shadow: inset 2px 0 0 rgba(2, 132, 199, 0.7);
}

.fm-row-conflict { background: rgba(254, 215, 170, 0.18); }

.fm-row-conflict:hover { background: rgba(254, 215, 170, 0.32); }

/* 文件行：不能作为移动目标，光标改成默认；hover 反馈做轻一点表示"看得见但不可选" */
.fm-row-file {
  cursor: default;
  color: #475569;
}

.fm-row-file:hover { background: rgba(15, 23, 42, 0.025); }

.fm-row-file .fm-cell-size,
.fm-row-file .fm-cell-time {
  color: #94a3b8;
}

/* 待移动条目 chip ----------------------------------------------- */
.src-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  font-size: 11px;
  color: #334155;
  border: 1px solid rgba(15, 23, 42, 0.08);
  white-space: nowrap;
}

.src-chip-folder {
  color: #f59e0b;
  fill: currentColor;
  stroke: currentColor;
}

.src-chip-file { color: #94a3b8; }

.src-chip-more {
  background: rgba(15, 23, 42, 0.05);
  color: #64748b;
  border-color: transparent;
}

.src-chip-stack {
  max-width: 480px;
  overflow: hidden;
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
}

.target-chip-path {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px;
  color: #1e293b;
  font-weight: 500;
  min-width: 0;
}

.conflict-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(254, 215, 170, 0.55);
  border: 1px solid rgba(253, 186, 116, 0.55);
  color: #b45309;
  font-size: 10.5px;
  font-weight: 600;
  flex-shrink: 0;
}

/* 底部 footer ---------------------------------------------------- */
.footer-row {
  border-top: 1px solid rgba(15, 23, 42, 0.06);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.4));
}

/* 同名冲突子面板 -------------------------------------------------- */
.conflict-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.32);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  z-index: 10;
}

.conflict-panel {
  width: 100%;
  max-width: 460px;
  background: white;
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 20px 50px -16px rgba(15, 23, 42, 0.45);
  padding: 20px 22px 18px;
}

.conflict-panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.conflict-panel-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: #fef3c7;
  color: #d97706;
  flex-shrink: 0;
}

.conflict-panel-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.3;
}

.conflict-panel-sub {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: #64748b;
}

.conflict-list {
  list-style: none;
  margin: 0 0 14px;
  padding: 8px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #f1f5f9;
  max-height: 140px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.conflict-list li {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: #334155;
  white-space: nowrap;
}

.conflict-list-more {
  font-size: 11px;
  color: #64748b;
  padding-left: 4px;
}

.conflict-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.conflict-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 12px;
  border-radius: 9px;
  border: 1px solid #e5e7eb;
  background: white;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
  cursor: pointer;
  transition: all 0.15s ease;
}

.conflict-btn:hover { transform: translateY(-1px); }

.conflict-btn:active { transform: scale(0.97); }

.conflict-btn-primary {
  background: #111827;
  color: white;
  border-color: #111827;
  box-shadow: 0 6px 14px -6px rgba(15, 23, 42, 0.5);
}

.conflict-btn-primary:hover { background: #0f172a; }

.conflict-btn-danger {
  background: #fef2f2;
  border-color: #fecaca;
  color: #991b1b;
}

.conflict-btn-danger:hover {
  background: #fee2e2;
  border-color: #fca5a5;
}

.conflict-btn-ghost {
  border-color: #e5e7eb;
  color: #475569;
}

.conflict-btn-ghost:hover {
  background: #f8fafc;
  border-color: #cbd5e1;
}

.conflict-btn-cancel {
  grid-column: span 3;
  color: #64748b;
}

.conflict-btn-cancel:hover { background: rgba(15, 23, 42, 0.05); }

.conflict-fade-enter-active,
.conflict-fade-leave-active {
  transition: opacity 0.18s ease;
}

.conflict-fade-enter-from,
.conflict-fade-leave-to {
  opacity: 0;
}

/* 滚动条 --------------------------------------------------------- */
.fm-body::-webkit-scrollbar,
.nav-scroll::-webkit-scrollbar,
.conflict-list::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.fm-body::-webkit-scrollbar-track,
.nav-scroll::-webkit-scrollbar-track,
.conflict-list::-webkit-scrollbar-track {
  background: transparent;
}

.fm-body::-webkit-scrollbar-thumb,
.nav-scroll::-webkit-scrollbar-thumb,
.conflict-list::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.12);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}

.fm-body::-webkit-scrollbar-thumb:hover,
.nav-scroll::-webkit-scrollbar-thumb:hover,
.conflict-list::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.24);
  background-clip: content-box;
}
</style>

<!--
  非 scoped 全局样式：el-dialog 通过 teleport 把根元素挂到 body 下，
  scoped 选择器 + :deep 对它不可靠；这里通过 .lib-move-modal / .lib-move-overlay
  这种弹框独占的 class 局部覆盖，保证不会污染其他弹框。
-->
<style>
/* 弹框尺寸：原 1100×640，按用户要求整体放大 ~20% 到 1320×768，并随 viewport 自适应 */
.lib-move-modal.el-dialog {
  width: min(1320px, calc(100vw - 32px)) !important;
  max-width: min(1320px, calc(100vw - 32px)) !important;
}

.lib-move-modal .window {
  height: min(768px, calc(100vh - 64px));
  max-height: calc(100vh - 64px);
}

/* 弹框外的页面保持清晰：不再做暗色衬底，也不对页面做 blur，
   毛玻璃感只由弹框自身的 backdrop-filter 提供（弹框区域内糊，外部清晰）。 */
.lib-move-overlay.custom-preview-overlay,
.lib-move-overlay {
  background: transparent !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

/* 拖拽过程中给整个 body 设置 col-resize，避免鼠标移出 splitter 时光标抖动 */
body[data-lib-move-resizing="1"] {
  cursor: col-resize !important;
  user-select: none !important;
}

@media (max-width: 640px) {
  .lib-move-modal.el-dialog {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
  .lib-move-modal .window {
    width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    border-radius: 0 !important;
  }
  .lib-move-modal .window-header {
    padding: 12px 14px !important;
    align-items: flex-start !important;
    gap: 10px !important;
  }
  .lib-move-modal .explorer-toolbar {
    display: grid !important;
    grid-template-columns: auto auto minmax(0, 1fr);
    gap: 8px !important;
    padding: 9px 12px !important;
  }
  .lib-move-modal .path-bar {
    grid-column: 1 / -1;
    order: 3;
    min-width: 0;
  }
  .lib-move-modal .search-wrap {
    grid-column: 1 / -1;
    order: 4;
    width: 100% !important;
  }
  .lib-move-modal .explorer-main {
    flex-direction: column !important;
    overflow: hidden;
  }
  .lib-move-modal .explorer-nav {
    width: 100% !important;
    max-height: 34dvh;
    border-right: 0 !important;
    border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  }
  .lib-move-modal .nav-splitter {
    display: none !important;
  }
  .lib-move-modal .explorer-list {
    min-height: 0;
  }
}
</style>
