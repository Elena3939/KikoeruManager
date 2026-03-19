<template>
  <div class="library">
            <h1 class="page-title">{{ labels.pageTitle }}</h1>

    <div class="summary-grid">
      <el-card shadow="never" class="summary-card">
        <template #header>{{ labels.currentLibrary }}</template>
        <div class="summary-value">{{ currentLibrary?.name || '-' }}</div>
        <div class="summary-meta">{{ currentLibraryTypeLabel }}</div>
        <div class="summary-meta path-text">{{ currentLibrary?.path || '-' }}</div>
        <div class="summary-tags" v-if="currentLibrary">
          <el-tag size="small" :type="isRemoteCurrentLibrary ? 'warning' : 'success'">{{ currentLibraryScopeLabel }}</el-tag>
          <el-tag size="small" :type="healthTagType(currentLibrary.health?.status)">{{ healthStatusLabel(currentLibrary.health?.status) }}</el-tag>
        </div>
        <div class="summary-caption">{{ healthDetailText(currentLibrary?.health) }}</div>
      </el-card>

      <el-card shadow="never" class="summary-card">
        <template #header>{{ labels.currentLibraryStats }}</template>
        <div class="summary-value">{{ (currentStats?.folder_count ?? 0) + ' ' + labels.folderCountUnit }}</div>
        <div class="summary-meta">{{ statsSizeCardText(currentStats) }}</div>
        <div v-if="showCurrentStatsProgress" class="summary-progress">
          <el-progress :percentage="currentStatsProgress" :stroke-width="8" :show-text="false" />
        </div>
        <div class="summary-caption">{{ statsStatusCardText(currentStats) }}</div>
      </el-card>

      <el-card shadow="never" class="summary-card">
        <template #header>{{ labels.allLibraries }}</template>
        <div class="summary-value">{{ (aggregateStats.folder_count || 0) + ' ' + labels.folderCountUnit }}</div>
        <div class="summary-meta">{{ aggregateSizeText }}</div>
        <div v-if="showAggregateProgress" class="summary-progress">
          <el-progress :percentage="aggregateProgress" :stroke-width="8" :show-text="false" />
        </div>
        <div class="summary-caption">{{ aggregateSummary }}</div>
        <div class="summary-caption" v-if="aggregateDetail">{{ aggregateDetail }}</div>
      </el-card>
    </div>

    <el-card shadow="never" class="main-card">
      <template #header>
        <div class="card-header">
          <span class="header-title">库内文件列表</span>
          <div class="header-actions">
            <el-select v-model="selectedLibraryId" style="width: 240px">
              <el-option v-for="library in libraries" :key="library.id" :label="library.name" :value="library.id">
                <div class="library-option">
                  <span>{{ library.name }}</span>
                  <el-tag size="small" :type="library.type === 'synology_filestation' ? 'warning' : 'success'">
                    {{ library.type === 'synology_filestation' ? '远程' : '本地' }}
                  </el-tag>
                </div>
              </el-option>
            </el-select>
            <el-button :loading="loading" @click="refreshLibrary"><el-icon><Refresh /></el-icon>刷新</el-button>
            <el-button :loading="statsLoading" @click="handleStatsAction">{{ canCancelStats ? '取消统计' : '刷新统计' }}</el-button>
            <el-button @click="toggleAllSelection">{{ isAllSelected ? '取消全选' : '全选' }}</el-button>
            <el-input v-model="searchQuery" clearable placeholder="搜索文件名或RJ号" style="width: 250px" @keyup.enter="handleSearch" @clear="handleSearch">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-button type="primary" plain @click="handleSearch">查询</el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="currentLibrary?.health?.warnings?.length || currentLibrary?.health?.errors?.length"
        :title="healthDetailText(currentLibrary?.health)"
        :type="currentLibrary?.health?.errors?.length ? 'error' : 'warning'"
        :closable="false"
        show-icon
        style="margin-bottom: 14px"
      />

      <div class="path-toolbar">
        <div class="path-toolbar-left">
          <el-button size="small" :disabled="!canGoParent" @click="goToParent">返回上级</el-button>
          <span class="path-label">当前层级</span>
          <code class="path-code">{{ currentPathDisplay }}</code>
        </div>
      </div>

      <el-table ref="tableRef" :data="files" v-loading="loading" row-key="id" empty-text="暂无文件" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="55" />
        <el-table-column prop="name" label="文件名" show-overflow-tooltip>
          <template #default="{ row }">
            <el-icon class="file-icon"><Folder v-if="row.is_directory" /><Files v-else /></el-icon>
            <button v-if="row.is_directory" type="button" class="file-link-btn" @click="openFolder(row)">{{ row.name }}</button>
            <span v-else class="file-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="rjcode" label="RJ 号" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.rjcode" size="small" type="primary" effect="light">{{ row.rjcode }}</el-tag>
            <span v-else class="empty-text">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="size" label="大小" width="120">
          <template #default="{ row }">{{ formatRowSize(row) }}</template>
        </el-table-column>
        <el-table-column prop="unzip_time" label="时间" width="180">
          <template #default="{ row }">{{ formatDate(row.unzip_time || row.modified_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <div class="action-grid">
              <div class="action-row">
                <template v-if="!isRemoteCurrentLibrary">
                  <el-button size="small" type="primary" plain class="action-btn" @click="openFolder(row)">打开</el-button>
                  <el-button size="small" type="primary" plain class="action-btn" @click="openFolderDirect(row)">直接打开</el-button>
                </template>
                <template v-else>
                  <el-button size="small" type="warning" plain class="action-btn" :disabled="!isWritableCurrentLibrary" @click="renameItem(row)">重命名</el-button>
                  <el-button size="small" type="warning" plain class="action-btn" :disabled="!row.is_directory" :loading="apiRenamingId === row.id" @click="apiRenameItem(row)">API 重命名</el-button>
                </template>
              </div>
              <div class="action-row" v-if="!isRemoteCurrentLibrary">
                <el-button size="small" type="warning" plain class="action-btn" :disabled="!isWritableCurrentLibrary" @click="renameItem(row)">重命名</el-button>
                <el-button size="small" type="warning" plain class="action-btn" :disabled="!row.is_directory" :loading="apiRenamingId === row.id" @click="apiRenameItem(row)">API 重命名</el-button>
              </div>
              <div class="action-row">
                <el-button size="small" plain class="action-btn action-btn-neutral" :disabled="!row.is_directory" @click="openFolderContentsDialog(row)">文件管理</el-button>
                <el-button size="small" type="danger" plain class="action-btn" :disabled="!isWritableCurrentLibrary" @click="deleteItem(row)">删除</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="batch-bar" v-if="selectedRows.length">
        <span class="selected-count">已选择 {{ selectedRows.length }} 项</span>
        <div class="batch-actions">
          <el-button size="small" type="danger" plain :disabled="!isWritableCurrentLibrary" :loading="batchDeleting" @click="handleBatchDelete"><el-icon><Delete /></el-icon>批量删除</el-button>
          <el-button size="small" type="warning" plain :disabled="isRemoteCurrentLibrary" :loading="batchRenaming" @click="handleBatchApiRename"><el-icon><Edit /></el-icon>批量 API重命名</el-button>
          <el-button size="small" @click="clearSelection">取消选择</el-button>
        </div>
      </div>

      <div class="pagination-wrap">
        <el-pagination v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="PAGE_SIZES" :total="totalFiles" layout="total, sizes, prev, pager, next" background />
      </div>
    </el-card>

    <el-dialog v-model="renameDialogVisible" title="重命名" width="500px">
      <el-form :model="renameForm" label-width="80px">
        <el-form-item label="当前名称"><el-input v-model="renameForm.currentName" disabled /></el-form-item>
        <el-form-item label="新名称"><el-input v-model="renameForm.newName" placeholder="输入新名称" /></el-form-item>
        <el-form-item label="预览"><div class="name-preview">{{ renameForm.newName || renameForm.currentName }}</div></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isRenaming" @click="confirmRename">确认重命名</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mappedPathDialogVisible" title="跨设备访问 - 路径映射" width="620px">
      <el-alert title="检测到跨设备部署环境" type="info" :closable="false" show-icon style="margin-bottom: 16px">
        <template #default>后端无法直接替你打开本地路径，请使用下面的映射路径手动访问。</template>
      </el-alert>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="远程路径"><code class="path-code">{{ mappedPathInfo.originalPath }}</code></el-descriptions-item>
        <el-descriptions-item label="本地映射路径">
          <div class="mapped-path-box">
            <code class="path-code">{{ mappedPathInfo.mappedPath }}</code>
            <div class="path-actions">
              <el-button size="small" type="primary" @click="copyMappedPath">复制路径</el-button>
              <el-button size="small" type="success" @click="openWithBrowser">尝试打开</el-button>
            </div>
          </div>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog v-model="folderDialogVisible" width="1100px" class="fm-dialog" destroy-on-close>
      <template #header>
        <div class="fm-header">
          <div class="fm-title">
            <span>{{ folderContentsInfo.folderName || '文件管理' }}</span>
            <span class="fm-badge">{{ formatFileSize(folderContentsInfo.totalSize) }}</span>
          </div>
          <div class="fm-count">{{ visibleFileCount }} / {{ folderContentsInfo.totalFiles }} 个文件</div>
        </div>
      </template>

      <div class="fm-body" v-loading="folderLoading">
        <div class="fm-toolbar">
          <div class="fm-toolbar-left">
            <button class="fm-btn fm-btn-danger" :disabled="!folderSelectedFiles.length" @click="batchDeleteSubFiles">批量删除</button>
            <button class="fm-btn fm-btn-ghost" @click="expandAll">展开全部</button>
            <button class="fm-btn fm-btn-ghost" @click="collapseAll">折叠全部</button>
          </div>
          <div class="fm-search">
            <input v-model="folderSearch" class="fm-search-input" placeholder="搜索文件名或路径…" @input="onSearchInput" />
          </div>
        </div>

        <div class="fm-head">
          <div class="fm-col-check">
            <input type="checkbox" class="fm-check" :checked="allFilesSelected" :indeterminate.prop="someFilesSelected" @change="toggleAllFiles" />
          </div>
          <div class="fm-col-name">文件名</div>
          <div class="fm-col-size">大小</div>
          <div class="fm-col-time">修改时间</div>
          <div class="fm-col-action">操作</div>
        </div>

        <div class="fm-scroll">
          <div v-if="!folderLoading && flatTree.length === 0" class="fm-empty">{{ folderSearch ? '无匹配文件' : '文件夹为空' }}</div>
          <div v-for="row in flatTree" :key="row.id" class="fm-row" :class="{ 'fm-row-dir': row.type === 'dir', 'fm-row-selected': selectedFileIds.has(row.id) }" @click="row.type === 'dir' ? toggleExpand(row) : null">
            <div class="fm-col-check" @click.stop>
              <input v-if="row.type === 'file'" type="checkbox" class="fm-check" :checked="selectedFileIds.has(row.id)" @change="toggleFileSelect(row)" />
            </div>
            <div class="fm-col-name">
              <div class="fm-name-cell" :style="{ paddingLeft: `${row.depth * 18 + 4}px` }">
                <span v-if="row.type === 'dir'" class="fm-arrow" :class="{ open: expandedIds.has(row.id) }">▶</span>
                <span v-else class="fm-arrow-placeholder"></span>
                <span class="fm-file-icon">
                  <el-icon>
                    <component :is="resolveTreeIcon(row)" />
                  </el-icon>
                </span>
                <span class="fm-name-text">{{ row.name }}</span>
              </div>
            </div>
            <div class="fm-col-size">{{ formatFileSize(row.size) }}</div>
            <div class="fm-col-time">{{ formatDate(row.modified_time) }}</div>
            <div class="fm-col-action" @click.stop><button class="fm-link-danger" @click="row.type === 'dir' ? deleteSubDir(row) : deleteSubFile(row)">删除</button></div>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Refresh, Search, Folder, FolderOpened, Delete, Edit, Files, Document, Picture, VideoPlay, Headset, Tickets } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { libraryApi } from '../api'

const PAGE_SIZES = [10, 20, 50, 100]
const PAGE_SIZE_KEY = 'kikoeru.ui.library.pageSize'
const loading = ref(false)
const statsLoading = ref(false)
const listPolling = ref(false)
const statsPolling = ref(false)
const files = ref([])
const totalFiles = ref(0)
const libraries = ref([])
const selectedLibraryId = ref('')
const searchQuery = ref('')
const currentPage = ref(loadNumber('kikoeru.ui.library.page', 1))
const pageSize = ref(loadNumber(PAGE_SIZE_KEY, 20))
const selectedRows = ref([])
const batchDeleting = ref(false)
const batchRenaming = ref(false)
const tableRef = ref(null)
const apiRenamingId = ref(null)
const currentPath = ref('')
const browseRootPath = ref('')
const parentPath = ref('')
const renameDialogVisible = ref(false)
const renameForm = ref({ currentName: '', newName: '', path: '' })
const isRenaming = ref(false)
const mappedPathDialogVisible = ref(false)
const mappedPathInfo = ref({ originalPath: '', mappedPath: '', isMapped: false })
const tampermonkeyLoaded = ref(false)
const statsMap = ref({})
const aggregateStats = ref({ folder_count: 0, total_size_gb: 0, total_size_bytes: 0 })
const libraryState = ref({})
const labels = {
  pageTitle: '\u5e93\u5b58\u6587\u4ef6\u7ba1\u7406',
  currentLibrary: '\u5f53\u524d\u5e93',
  currentLibraryStats: '\u5f53\u524d\u5e93\u7edf\u8ba1',
  allLibraries: '\u5168\u90e8\u5e93\u5b58',
  folderCountUnit: '\u4e2a\u6587\u4ef6\u5939'
}
let statsPollTimer = null
let listPollTimer = null
const folderDialogVisible = ref(false)
const folderLoading = ref(false)
const folderSearch = ref('')
const folderContentsInfo = ref({ folderName: '', folderPath: '', totalFiles: 0, totalSize: 0 })
const folderItems = ref([])
const selectedFileIds = ref(new Set())
const expandedIds = ref(new Set())

const currentLibrary = computed(() => libraries.value.find(item => item.id === selectedLibraryId.value) || null)
const currentStats = computed(() => statsMap.value[selectedLibraryId.value] || null)
const isRemoteCurrentLibrary = computed(() => currentLibrary.value?.type === 'synology_filestation')
const currentLibraryTypeLabel = computed(() => isRemoteCurrentLibrary.value ? '\u8fdc\u7a0b\u670d\u52a1\u5668\u5e93\u5b58' : '\u672c\u5730\u5e93\u5b58')
const currentLibraryScopeLabel = computed(() => isRemoteCurrentLibrary.value ? '\u8fdc\u7a0b' : '\u672c\u5730')
const isWritableCurrentLibrary = computed(() => !!currentLibrary.value?.writable)
const isAllSelected = computed(() => files.value.length > 0 && selectedRows.value.length === files.value.length)
const aggregatePending = computed(() => Object.values(statsMap.value).some(item => item?.status === 'pending'))
const remoteIdleLibraries = computed(() => libraries.value.filter(item => item.type === 'synology_filestation' && ['idle', undefined].includes(statsMap.value[item.id]?.status)).length)
const countedLibraries = computed(() => libraries.value.filter(item => {
  const status = statsMap.value[item.id]?.status
  return status && status !== 'idle'
}).length)
const currentStatsProgress = computed(() => Math.max(0, Math.min(100, Number(currentStats.value?.progress_percent || 0))))
const showCurrentStatsProgress = computed(() => currentStats.value?.status === 'pending' && currentStatsProgress.value > 0)
const canCancelStats = computed(() => currentStats.value?.status === 'pending')
const aggregateProgress = computed(() => {
  const relevant = libraries.value
    .map(item => statsMap.value[item.id])
    .filter(item => item && ['ready', 'pending'].includes(item.status))
  if (!relevant.length) return 0
  const total = relevant.reduce((sum, item) => sum + (item.status === 'ready' ? 100 : Number(item.progress_percent || 0)), 0)
  return Math.max(0, Math.min(100, Number((total / relevant.length).toFixed(2))))
})
const showAggregateProgress = computed(() => aggregatePending.value && aggregateProgress.value > 0)
const aggregateLastCompletedAt = computed(() => {
  const timestamps = Object.values(statsMap.value)
    .map(item => Number(item?.last_completed_at || item?.updated_at || 0))
    .filter(value => Number.isFinite(value) && value > 0)
  return timestamps.length ? Math.max(...timestamps) : null
})
const aggregateSizeText = computed(() => {
  const base = formatGB(aggregateStats.value.total_size_gb)
  return remoteIdleLibraries.value > 0 ? `${base}\uff08\u4ec5\u5df2\u7edf\u8ba1\u5e93\uff09` : base
})
const aggregateSummary = computed(() => {
  if (aggregatePending.value) return `\u7edf\u8ba1\u8fdb\u884c\u4e2d\uff0c\u5df2\u5b8c\u6210 ${aggregateProgress.value.toFixed(0)}%`
  if (remoteIdleLibraries.value > 0) return `\u5f53\u524d\u4ec5\u5305\u542b ${countedLibraries.value}/${libraries.value.length} \u4e2a\u5df2\u7edf\u8ba1\u5e93`
  return `\u5171 ${libraries.value.length} \u4e2a\u5e93`
})
const aggregateDetail = computed(() => {
  if (aggregatePending.value) {
    const ts = aggregateLastCompletedAt.value
    return ts
      ? `\u540e\u53f0\u7ee7\u7eed\u66f4\u65b0\u4e2d\uff0c\u5f53\u524d\u4f18\u5148\u663e\u793a\u5df2\u4fdd\u5b58\u7ed3\u679c\uff0c\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}`
      : '\u540e\u53f0\u7ee7\u7eed\u66f4\u65b0\u4e2d\uff0c\u7edf\u8ba1\u7ed3\u679c\u4f1a\u81ea\u52a8\u5237\u65b0'
  }
  if (remoteIdleLibraries.value > 0) return '\u672a\u624b\u52a8\u7edf\u8ba1\u7684\u8fdc\u7a0b\u5e93\u4e0d\u4f1a\u8ba1\u5165\u603b\u6587\u4ef6\u5939\u6570\u548c\u603b\u5927\u5c0f'
  const ts = aggregateLastCompletedAt.value
  return ts ? `\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : ''
})
const canGoParent = computed(() => !!parentPath.value && currentPath.value && currentPath.value !== browseRootPath.value)
const currentPathDisplay = computed(() => {
  const normalizedCurrent = (currentPath.value || '').replace(/\\/g, '/')
  const normalizedRoot = (browseRootPath.value || '').replace(/\\/g, '/')
  if (!normalizedCurrent) return '/'
  if (!normalizedRoot) return normalizedCurrent
  if (normalizedCurrent === normalizedRoot) return '/'
  if (normalizedCurrent.startsWith(`${normalizedRoot}/`)) return normalizedCurrent.slice(normalizedRoot.length)
  return normalizedCurrent
})

const treeRoot = computed(() => buildTree(folderItems.value))
const filteredRoot = computed(() => {
  const keyword = folderSearch.value.trim().toLowerCase()
  return keyword ? filterTree(treeRoot.value, keyword) : treeRoot.value
})
const flatTree = computed(() => flattenTree(filteredRoot.value, 0, expandedIds.value))
const visibleFileCount = computed(() => flatTree.value.filter(item => item.type === 'file').length)
const allSelectableIds = computed(() => flatTree.value.filter(item => item.type === 'file').map(item => item.id))
const allFilesSelected = computed(() => allSelectableIds.value.length > 0 && allSelectableIds.value.every(id => selectedFileIds.value.has(id)))
const someFilesSelected = computed(() => !allFilesSelected.value && allSelectableIds.value.some(id => selectedFileIds.value.has(id)))
const folderSelectedFiles = computed(() => folderItems.value.filter(item => selectedFileIds.value.has(`file:${item.path}`)))

onMounted(async () => {
  await loadLibraries()
  await refreshLibrary()
  refreshStats(false, { silent: true })
})

onBeforeUnmount(() => {
  clearStatsPoll()
  clearListPoll()
})

watch(pageSize, async value => {
  storeNumber(PAGE_SIZE_KEY, value)
  currentPage.value = 1
  if (selectedLibraryId.value) await refreshLibrary()
})

watch(currentPage, async (value, oldValue) => {
  if (value === oldValue || !selectedLibraryId.value) return
  storeNumber('kikoeru.ui.library.page', value)
  await refreshLibrary()
})

watch(selectedLibraryId, async (newId, oldId) => {
  if (!newId) return
  if (oldId) saveLibraryState(oldId)
  restoreLibraryState(newId)
  clearSelection()
  await refreshLibrary()
  refreshStats(false, { silent: true })
})

function loadNumber (key, fallback) {
  try {
    const value = Number(localStorage.getItem(key))
    return Number.isFinite(value) && value > 0 ? value : fallback
  } catch (_) {
    return fallback
  }
}

function storeNumber (key, value) {
  try { localStorage.setItem(key, String(value)) } catch (_) {}
}

async function loadLibraries () {
  const data = await libraryApi.listLibraries()
  libraries.value = data.libraries || []
  const validIds = new Set(libraries.value.map(item => item.id))
  const fallbackId = data.default_library_id || libraries.value[0]?.id || ''
  if (!selectedLibraryId.value || !validIds.has(selectedLibraryId.value)) {
    selectedLibraryId.value = fallbackId
    restoreLibraryState(selectedLibraryId.value)
  }
}

function saveLibraryState (libraryId) {
  libraryState.value[libraryId] = {
    searchQuery: searchQuery.value,
    currentPage: currentPage.value,
    currentPath: currentPath.value,
    browseRootPath: browseRootPath.value
  }
}

function restoreLibraryState (libraryId) {
  const state = libraryState.value[libraryId] || {}
  searchQuery.value = state.searchQuery || ''
  currentPage.value = state.currentPage || 1
  currentPath.value = state.currentPath || ''
  browseRootPath.value = state.browseRootPath || ''
}

function clearStatsPoll () {
  if (statsPollTimer) {
    clearTimeout(statsPollTimer)
    statsPollTimer = null
  }
}

function scheduleStatsPoll (items) {
  clearStatsPoll()
  if ((items || []).some(item => item?.status === 'pending')) {
    statsPollTimer = setTimeout(() => refreshStats(false, { silent: true }), 1500)
  }
}

function clearListPoll () {
  if (listPollTimer) {
    clearTimeout(listPollTimer)
    listPollTimer = null
  }
}

function scheduleListPoll (items) {
  clearListPoll()
  if ((items || []).some(item => item?.size_status && item.size_status !== 'ready')) {
    listPollTimer = setTimeout(() => refreshLibrary({ silent: true }), 2000)
  }
}

async function refreshStats (forceRefresh = false, options = {}) {
  const { silent = false, refreshLibraryId = null } = options
  clearStatsPoll()
  if (silent) statsPolling.value = true
  else statsLoading.value = true
  try {
    const data = await libraryApi.getStats(forceRefresh, refreshLibraryId)
    const nextMap = {}
    for (const item of data.libraries || []) nextMap[item.library_id] = item
    statsMap.value = nextMap
    aggregateStats.value = data.all_libraries || { folder_count: 0, total_size_gb: 0, total_size_bytes: 0 }
    scheduleStatsPoll(data.libraries || [])
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '获取统计失败')
  } finally {
    if (silent) statsPolling.value = false
    else statsLoading.value = false
  }
}

async function handleStatsAction () {
  if (canCancelStats.value) {
    await cancelStats()
    return
  }
  await refreshStats(true, { refreshLibraryId: selectedLibraryId.value })
}

async function cancelStats () {
  if (!selectedLibraryId.value) return
  statsLoading.value = true
  try {
    const data = await libraryApi.cancelStats(selectedLibraryId.value)
    ElMessage.success(data.message || '统计任务已取消')
    await refreshStats(false, { silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '取消统计失败')
  } finally {
    statsLoading.value = false
  }
}

async function refreshLibrary (options = {}) {
  const { silent = false } = options
  if (!selectedLibraryId.value) return
  clearListPoll()
  if (silent) listPolling.value = true
  else loading.value = true
  try {
    const data = await libraryApi.browseFiles({
      libraryId: selectedLibraryId.value,
      page: currentPage.value,
      pageSize: pageSize.value,
      search: searchQuery.value.trim(),
      currentPath: currentPath.value
    })
    files.value = data.files || []
    totalFiles.value = data.total || 0
    if (data.libraries?.length) libraries.value = data.libraries
    if (data.library_id && data.library_id !== selectedLibraryId.value) {
      selectedLibraryId.value = data.library_id
      return
    }
    currentPath.value = data.current_path || currentPath.value || data.browse_root_path || ''
    browseRootPath.value = data.browse_root_path || browseRootPath.value || currentPath.value
    parentPath.value = data.parent_path || ''
    scheduleListPoll(files.value)
    const maxPage = Math.max(1, Math.ceil(Math.max(totalFiles.value, 1) / pageSize.value))
    if (currentPage.value > maxPage) currentPage.value = maxPage
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '获取库存文件失败')
  } finally {
    if (silent) listPolling.value = false
    else loading.value = false
  }
}

async function handleSearch () {
  currentPage.value = 1
  await refreshLibrary()
}

function handleSelectionChange (selection) {
  selectedRows.value = selection
}

function toggleAllSelection () {
  if (!files.value.length) return
  if (isAllSelected.value) return clearSelection()
  files.value.forEach(row => tableRef.value?.toggleRowSelection(row, true))
}

function clearSelection () {
  tableRef.value?.clearSelection()
  selectedRows.value = []
}

async function navigateToPath (path) {
  const shouldRefreshNow = currentPage.value === 1
  currentPath.value = path || browseRootPath.value || currentPath.value
  currentPage.value = 1
  clearSelection()
  if (shouldRefreshNow) await refreshLibrary()
}

async function goToParent () {
  if (!canGoParent.value) return
  await navigateToPath(parentPath.value)
}

async function openFolder (row) {
  if (row?.is_directory) {
    await navigateToPath(row.path)
    return
  }
  if (isRemoteCurrentLibrary.value) {
    const data = await libraryApi.browserOpenFolder(selectedLibraryId.value, row.path)
    await ElMessageBox.alert(`请在群晖 FileStation 中打开以下路径：<br><br>${data.path || row.path}<br><br>${data.remote_url || ''}`, '远程库存', { confirmButtonText: '知道了', dangerouslyUseHTMLString: true })
    return
  }
  const data = await libraryApi.openFolder(row.path)
  if (data.mode === 'mapped') {
    mappedPathInfo.value = { originalPath: data.original_path, mappedPath: data.mapped_path, isMapped: data.is_mapped }
    mappedPathDialogVisible.value = true
    return
  }
  ElMessage.success('已打开文件夹')
}

async function openFolderDirect (row) {
  if (isRemoteCurrentLibrary.value) {
    try {
      const data = await libraryApi.browserOpenFolder(selectedLibraryId.value, row.path)
      if (data.web_url) {
        window.open(data.web_url, '_blank', 'noopener')
        ElMessage.success('已打开群晖目录')
        return
      }
      await ElMessageBox.alert(`请在群晖 FileStation 中打开以下路径：<br><br>${data.path || row.path}`, '远程库存', { confirmButtonText: '知道了', dangerouslyUseHTMLString: true })
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || error.message || '打开群晖目录失败')
    }
    return
  }
  const data = await libraryApi.openFolder(row.path)
  if (data.mode !== 'mapped') {
    ElMessage.success('已打开文件夹')
    return
  }
  const path = data.mapped_path
  const hasHelper = window.kikoeruHelperLoaded || tampermonkeyLoaded.value
  window.dispatchEvent(new CustomEvent('kikoeru-open-folder', { detail: { path } }))
  hasHelper ? ElMessage.success('正在打开文件夹...') : ElMessage.info('正在尝试打开文件夹...')
}

async function copyMappedPath () {
  try {
    await navigator.clipboard.writeText(mappedPathInfo.value.mappedPath)
    ElMessage.success('已复制')
  } catch (_) {
    ElMessage.error('复制失败')
  }
}

function openWithBrowser () {
  const path = mappedPathInfo.value.mappedPath
  if (window.kikoeruHelperLoaded || tampermonkeyLoaded.value) {
    window.dispatchEvent(new CustomEvent('kikoeru-open-folder', { detail: { path } }))
    return
  }
  let url = path.replace(/\\/g, '/')
  url = /^[a-zA-Z]:/.test(url) ? `file:///${url}` : `file://${url}`
  try { window.open(url, '_blank') } catch (_) {}
}

function renameItem (row) {
  renameForm.value = { currentName: row.name, newName: row.name, path: row.path }
  renameDialogVisible.value = true
}

async function confirmRename () {
  if (!renameForm.value.newName || renameForm.value.newName === renameForm.value.currentName) {
    ElMessage.warning('请输入不同的新名称')
    return
  }
  isRenaming.value = true
  try {
    await libraryApi.browserRename(selectedLibraryId.value, renameForm.value.path, renameForm.value.newName)
    renameDialogVisible.value = false
    ElMessage.success('重命名成功')
    await Promise.all([refreshLibrary(), refreshStats(true, { refreshLibraryId: selectedLibraryId.value })])
  } catch (error) {
    ElMessage.error('重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    isRenaming.value = false
  }
}

async function apiRenameItem (row) {
  try {
    await ElMessageBox.confirm(`确定重新获取 DLsite 元数据并重命名吗？\n\n当前: ${row.name}`, 'API重命名确认', { confirmButtonText: '确定', cancelButtonText: '取消', type: 'info' })
  } catch (_) { return }
  apiRenamingId.value = row.id
  try {
    const data = await libraryApi.apiRename(row.path, selectedLibraryId.value)
    ElMessage.success(data.message || 'API 重命名成功')
    await Promise.all([refreshLibrary(), refreshStats(true, { refreshLibraryId: selectedLibraryId.value })])
  } catch (error) {
    ElMessage.error('API重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    apiRenamingId.value = null
  }
}

async function deleteItem (row) {
  try {
    const preview = await libraryApi.browserDelete(selectedLibraryId.value, row.path, false)
    await ElMessageBox.confirm(`确定删除此${preview.type === 'folder' ? '文件夹' : '文件'}吗？\n名称: ${preview.name}\n大小: ${formatFileSize(preview.size)}\n\n此操作不可恢复！`, '删除确认', { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' })
    await libraryApi.browserDelete(selectedLibraryId.value, row.path, true)
    ElMessage.success('删除成功')
    await Promise.all([refreshLibrary(), refreshStats(true, { refreshLibraryId: selectedLibraryId.value })])
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function handleBatchDelete () {
  if (!selectedRows.value.length) return
  batchDeleting.value = true
  try {
    const paths = selectedRows.value.map(row => row.path)
    const preview = await libraryApi.browserBatchDelete(selectedLibraryId.value, paths, false)
    await ElMessageBox.confirm(`确定删除 ${preview.total_count || paths.length} 项？总大小: ${formatFileSize(preview.total_size || 0)}\n\n此操作不可恢复！`, '批量删除确认', { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' })
    const result = await libraryApi.browserBatchDelete(selectedLibraryId.value, paths, true)
    ElMessage.success(`批量删除完成：成功 ${result.success_count || 0} 项`)
    clearSelection()
    await Promise.all([refreshLibrary(), refreshStats(true, { refreshLibraryId: selectedLibraryId.value })])
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('批量删除失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    batchDeleting.value = false
  }
}

async function handleBatchApiRename () {
  if (!selectedRows.value.length) return
  batchRenaming.value = true
  try {
    const data = await libraryApi.batchApiRename(selectedRows.value.map(row => row.path))
    ElMessage.success(data.message || '已提交批量 API 重命名')
    await Promise.all([refreshLibrary(), refreshStats(true, { refreshLibraryId: selectedLibraryId.value })])
  } catch (error) {
    ElMessage.error('批量 API重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    batchRenaming.value = false
  }
}

async function openFolderContentsDialog (row) {
  if (!row?.is_directory) return
  folderDialogVisible.value = true
  folderSearch.value = ''
  selectedFileIds.value = new Set()
  expandedIds.value = new Set()
  await loadFolderContents(row.path, row.name)
}

async function loadFolderContents (path, name = '') {
  folderLoading.value = true
  try {
    const data = await libraryApi.browserFolderContents(selectedLibraryId.value, path)
    const items = data.items || []
    folderItems.value = items
    folderContentsInfo.value = { folderName: data.folder_name || name, folderPath: data.folder_path || path, totalFiles: data.total_files || 0, totalSize: items.reduce((sum, item) => sum + (item.size || 0), 0) }
    const opened = new Set()
    buildTree(folderItems.value).forEach(node => { if (node.type === 'dir') opened.add(node.id) })
    expandedIds.value = opened
  } catch (error) {
    folderDialogVisible.value = false
    ElMessage.error('加载文件夹内容失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    folderLoading.value = false
  }
}

async function deleteSubFile (row) {
  await deletePath(row.path)
}

async function deleteSubDir (row) {
  await deletePath(joinFolderPath(folderContentsInfo.value.folderPath, row.relative_path))
}

async function deletePath (path) {
  try {
    const preview = await libraryApi.browserDelete(selectedLibraryId.value, path, false)
    await ElMessageBox.confirm(`确定删除 ${preview.name} 吗？\n大小: ${formatFileSize(preview.size)}\n\n此操作不可恢复！`, '删除确认', { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' })
    await libraryApi.browserDelete(selectedLibraryId.value, path, true)
    ElMessage.success('删除成功')
    await Promise.all([loadFolderContents(folderContentsInfo.value.folderPath, folderContentsInfo.value.folderName), refreshLibrary(), refreshStats(true, { refreshLibraryId: selectedLibraryId.value })])
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function batchDeleteSubFiles () {
  if (!folderSelectedFiles.value.length) return
  try {
    const paths = folderSelectedFiles.value.map(item => item.path)
    const preview = await libraryApi.browserBatchDelete(selectedLibraryId.value, paths, false)
    await ElMessageBox.confirm(`确定删除 ${preview.total_count || paths.length} 个文件？总大小: ${formatFileSize(preview.total_size || 0)}\n\n此操作不可恢复！`, '批量删除确认', { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' })
    const result = await libraryApi.browserBatchDelete(selectedLibraryId.value, paths, true)
    ElMessage.success(`批量删除完成：成功 ${result.success_count || 0} 个`)
    await Promise.all([loadFolderContents(folderContentsInfo.value.folderPath, folderContentsInfo.value.folderName), refreshLibrary(), refreshStats(true, { refreshLibraryId: selectedLibraryId.value })])
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('批量删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

function joinFolderPath (basePath, relativePath) {
  if (!relativePath) return basePath
  return `${basePath.replace(/[\\/]+$/, '')}/${relativePath.replace(/^[/\\]+/, '')}`
}

function buildTree (items) {
  const root = []
  const dirMap = new Map()
  const sorted = [...items].sort((a, b) => (a.relative_path || '').localeCompare(b.relative_path || ''))
  for (const item of sorted) {
    const parts = (item.relative_path || item.name).split('/').filter(Boolean)
    let children = root
    let path = ''
    for (let index = 0; index < parts.length - 1; index++) {
      path = path ? `${path}/${parts[index]}` : parts[index]
      const key = `dir:${path}`
      if (!dirMap.has(key)) {
        const node = { id: key, name: parts[index], type: 'dir', relative_path: path, size: 0, modified_time: null, children: [] }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }
    children.push({ ...item, id: `file:${item.path}`, type: 'file' })
  }
  const walk = node => {
    let total = 0
    let latest = null
    for (const child of node.children || []) {
      if (child.type === 'dir') walk(child)
      total += child.size || 0
      if (child.modified_time && (!latest || child.modified_time > latest)) latest = child.modified_time
    }
    node.size = total
    node.modified_time = latest
  }
  root.forEach(node => { if (node.type === 'dir') walk(node) })
  return root
}

function filterTree (nodes, keyword) {
  const result = []
  for (const node of nodes) {
    const matched = (node.name || '').toLowerCase().includes(keyword) || (node.relative_path || '').toLowerCase().includes(keyword)
    if (node.type === 'file') {
      if (matched) result.push(node)
      continue
    }
    const children = filterTree(node.children || [], keyword)
    if (matched || children.length) result.push({ ...node, children })
  }
  return result
}

function flattenTree (nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    result.push({ ...node, depth })
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) result.push(...flattenTree(node.children, depth + 1, openIds))
  }
  return result
}

function toggleExpand (node) {
  const next = new Set(expandedIds.value)
  next.has(node.id) ? next.delete(node.id) : next.add(node.id)
  expandedIds.value = next
}

function expandAll () {
  const next = new Set()
  const walk = nodes => nodes.forEach(node => { if (node.type === 'dir') { next.add(node.id); walk(node.children || []) } })
  walk(filteredRoot.value)
  expandedIds.value = next
}

function collapseAll () {
  expandedIds.value = new Set()
}

function onSearchInput () {
  if (folderSearch.value.trim()) expandAll()
}

function toggleFileSelect (row) {
  const next = new Set(selectedFileIds.value)
  next.has(row.id) ? next.delete(row.id) : next.add(row.id)
  selectedFileIds.value = next
}

function toggleAllFiles (event) {
  const checked = !!event.target.checked
  const next = new Set(selectedFileIds.value)
  allSelectableIds.value.forEach(id => (checked ? next.add(id) : next.delete(id)))
  selectedFileIds.value = next
}

function fileIcon (name = '') {
  const lower = name.toLowerCase()
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(lower)) return Headset
  if (/\.(png|jpg|jpeg|webp|bmp|gif)$/i.test(lower)) return Picture
  if (/\.(mp4|mkv|avi|mov|wmv|webm)$/i.test(lower)) return VideoPlay
  if (/\.(lrc|srt|ass|ssa|vtt)$/i.test(lower)) return Tickets
  return Document
}

function resolveTreeIcon (row) {
  if (row?.type === 'dir') {
    return expandedIds.value.has(row.id) ? FolderOpened : Folder
  }
  return fileIcon(row?.name || '')
}

function formatFileSize (bytes) {
  if (bytes === null || bytes === undefined) return '-'
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** index)).toFixed(2)} ${units[index]}`
}

function formatRowSize (row) {
  if (row?.size_status === 'pending' && (row.size === null || row.size === undefined)) return '统计中'
  if (row?.size_status === 'stale' && row.size !== null && row.size !== undefined) return `${formatFileSize(row.size)} *`
  return formatFileSize(row?.size)
}

function formatDate (value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatGB (value) {
  if (value === null || value === undefined) return '统计中'
  return `${Number(value).toFixed(2)} GB`
}

function statsSizeText (stats) {
  if (!stats || stats.status === 'pending') return '统计更新中'
  if (stats.status === 'unsupported') return '暂不支持远程容量统计'
  return formatGB(stats.total_size_gb)
}

function statsStatusText (status) {
  if (status === 'ready') return '统计已就绪'
  if (status === 'pending') return '后台正在更新'
  if (status === 'unsupported') return '当前仅显示健康状态'
  return '等待统计'
}

function statsSizeCardText (stats) {
  if (!stats) return '\u7b49\u5f85\u7edf\u8ba1'
  if (stats.status === 'pending') return '\u7edf\u8ba1\u66f4\u65b0\u4e2d'
  if (stats.status === 'idle') return '\u672a\u624b\u52a8\u7edf\u8ba1'
  if (stats.status === 'canceled') return '\u5df2\u53d6\u6d88\uff0c\u4fdd\u7559\u5f53\u524d\u8fdb\u5ea6'
  if (stats.status === 'error') return '\u7edf\u8ba1\u4e2d\u65ad\uff0c\u4fdd\u7559\u5df2\u5b8c\u6210\u6570\u636e'
  if (stats.status === 'unsupported') return '\u6682\u4e0d\u652f\u6301\u5f53\u524d\u7edf\u8ba1'
  return formatGB(stats.total_size_gb)
}

function statsStatusCardText (stats) {
  const status = stats?.status
  if (status === 'ready') {
    const ts = stats?.last_completed_at || stats?.updated_at
    return ts ? `\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : '\u7edf\u8ba1\u5df2\u5b8c\u6210'
  }
  if (status === 'pending') {
    const ts = stats?.last_completed_at
    return ts ? `\u540e\u53f0\u66f4\u65b0\u4e2d\uff0c\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : '\u540e\u53f0\u6b63\u5728\u66f4\u65b0'
  }
  if (status === 'canceled') return '\u5df2\u624b\u52a8\u53d6\u6d88\uff0c\u4ecd\u4fdd\u7559\u5df2\u7edf\u8ba1\u8fdb\u5ea6'
  if (status === 'error') return stats?.last_error || '\u7edf\u8ba1\u4e2d\u9014\u51fa\u73b0\u5f02\u5e38\uff0c\u8bf7\u67e5\u770b\u8fdc\u7a0b\u7edf\u8ba1\u65e5\u5fd7'
  if (status === 'idle') return '\u8fdc\u7a0b\u5e93\u9ed8\u8ba4\u4e0d\u81ea\u52a8\u5168\u91cf\u7edf\u8ba1\uff0c\u8bf7\u624b\u52a8\u70b9\u5237\u65b0\u7edf\u8ba1'
  if (status === 'unsupported') return '\u5f53\u524d\u4ec5\u663e\u793a\u5065\u5eb7\u72b6\u6001'
  return '\u7b49\u5f85\u7edf\u8ba1'
}

function healthStatusLabel (status) {
  if (status === 'healthy') return '\u5065\u5eb7'
  if (status === 'warning') return '\u9884\u8b66'
  return '\u5f02\u5e38'
}

function healthDetailText (health) {
  if (!health) return ''
  if (health.errors?.length) return health.errors.join('\uff1b')
  if (health.warnings?.length) return health.warnings.join('\uff1b')
  if (health.free_space_gb !== null && health.free_space_gb !== undefined) return `\u5269\u4f59\u7a7a\u95f4 ${health.free_space_gb} GB`
  return '\u8bfb\u5199\u6743\u9650\u6b63\u5e38'
}

function healthTagType (status) {
  if (status === 'healthy') return 'success'
  if (status === 'warning') return 'warning'
  return 'danger'
}

function healthText (status) {
  if (status === 'healthy') return '健康'
  if (status === 'warning') return '预警'
  return '异常'
}

function healthDetail (health) {
  if (!health) return ''
  if (health.errors?.length) return health.errors.join('；')
  if (health.warnings?.length) return health.warnings.join('；')
  if (health.free_space_gb !== null && health.free_space_gb !== undefined) return `剩余空间 ${health.free_space_gb} GB`
  return '读写权限正常'
}
function statsSizeLabel (stats) {
  if (!stats || stats.status === 'pending') return '统计更新中'
  if (stats.status === 'idle') return '未统计'
  if (stats.status === 'unsupported') return '暂不支持远程容量统计'
  return formatGB(stats.total_size_gb)
}

function statsStatusLabel (stats) {
  const status = stats?.status
  if (status === 'ready') {
    const ts = stats?.last_completed_at || stats?.updated_at
    return ts ? `统计于 ${formatDate(ts * 1000)}` : '统计已就绪'
  }
  if (status === 'pending') {
    const ts = stats?.last_completed_at
    return ts ? `后台更新中，上次统计于 ${formatDate(ts * 1000)}` : '后台正在更新'
  }
  if (status === 'idle') return '未手动统计，沿用已保存结果'
  if (status === 'unsupported') return '当前仅显示健康状态'
  return '等待统计'
}

function statsSizeTextDisplay (stats) {
  if (!stats || stats.status === 'pending') return '统计更新中'
  if (stats.status === 'idle') return '未统计'
  if (stats.status === 'unsupported') return '暂不支持远程容量统计'
  return formatGB(stats.total_size_gb)
}

function statsStatusTextDisplay (stats) {
  const status = stats?.status
  if (status === 'ready') {
    const ts = stats?.last_completed_at || stats?.updated_at
    return ts ? `统计于 ${formatDate(ts * 1000)}` : '统计已就绪'
  }
  if (status === 'pending') {
    const ts = stats?.last_completed_at
    return ts ? `后台更新中，上次统计于 ${formatDate(ts * 1000)}` : '后台正在更新'
  }
  if (status === 'idle') return '未手动统计，沿用已保存结果'
  if (status === 'unsupported') return '当前仅显示健康状态'
  return '等待统计'
}
</script>

<style scoped>
.library { max-width: 1480px; margin: 0 auto; padding: 16px; }
.page-title { margin: 0 0 20px; font-size: 24px; font-weight: 600; color: #303133; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }
.summary-card { min-height: 160px; }
.summary-value { font-size: 26px; font-weight: 700; color: #303133; line-height: 1.3; }
.summary-meta, .summary-caption { margin-top: 8px; color: #606266; font-size: 14px; }
.summary-caption { color: #909399; font-size: 13px; line-height: 1.6; }
.summary-progress { margin-top: 10px; }

.path-text { word-break: break-all; }
.summary-tags { display: flex; gap: 8px; margin-top: 12px; }
.main-card { border-radius: 8px; border: 1px solid #e4e7ed; box-shadow: 0 2px 12px rgba(0,0,0,.02) !important; }
.card-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.header-title { font-size: 16px; font-weight: 600; color: #303133; white-space: nowrap; }
.header-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: flex-end; }
.library-option { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.path-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; padding: 10px 12px; background: #f8f9fa; border: 1px solid #ebeef5; border-radius: 6px; }
.path-toolbar-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.path-label { font-size: 13px; color: #909399; white-space: nowrap; }
:deep(.el-table) { --el-table-header-bg-color: #f8f9fa; }
:deep(.el-table th.el-table__cell) { font-weight: 600; }
.file-icon { margin-right: 6px; color: #409eff; vertical-align: middle; }
.file-name { vertical-align: middle; font-weight: 500; color: #303133; }
.file-link-btn { padding: 0; border: none; background: transparent; color: #303133; font: inherit; font-weight: 500; cursor: pointer; }
.file-link-btn:hover { color: #409eff; }
.empty-text { color: #c0c4cc; }
.action-grid { display: inline-flex; flex-direction: column; gap: 4px; align-items: center; width: 100%; }
.action-row { display: flex; gap: 4px; width: 228px; }
.action-btn { flex: 1; margin: 0 !important; border-radius: 5px; font-size: 12px; font-weight: 500; padding: 5px 0; }
.action-btn-neutral { color: #606266 !important; border-color: #dcdfe6 !important; }
.batch-bar { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; padding: 10px 16px; background: #f8f9fa; border: 1px solid #ebeef5; border-radius: 6px; }
.batch-actions { display: flex; align-items: center; gap: 8px; }
.selected-count { font-weight: 600; color: #409eff; font-size: 13px; background: #ecf5ff; padding: 3px 10px; border-radius: 10px; }
.pagination-wrap { margin-top: 20px; display: flex; justify-content: flex-end; }
.name-preview, .path-code { font-family: monospace; font-size: 13px; word-break: break-all; }
.name-preview { padding: 8px 12px; background: #f8f9fa; border: 1px solid #e4e7ed; border-radius: 4px; color: #606266; }
.mapped-path-box { display: flex; flex-direction: column; gap: 10px; }
.path-actions { display: flex; gap: 8px; }
:deep(.fm-dialog .el-dialog) { border-radius: 8px; overflow: hidden; box-shadow: 0 16px 48px rgba(0,0,0,.18); }
:deep(.fm-dialog .el-dialog__header) { padding: 0; margin: 0; }
:deep(.fm-dialog .el-dialog__body) { padding: 0; }
.fm-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px 12px 20px; border-bottom: 1px solid #e4e7ed; }
.fm-title { display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600; color: #303133; min-width: 0; }
.fm-badge { font-size: 12px; color: #909399; background: #f5f7fa; border: 1px solid #e4e7ed; border-radius: 10px; padding: 2px 8px; }
.fm-count { font-size: 12px; color: #606266; background: #f0f7ff; border: 1px solid #c6e2ff; border-radius: 12px; padding: 2px 10px; }
.fm-body { display: flex; flex-direction: column; height: 540px; background: #fff; }
.fm-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 9px 16px; background: #f8f9fa; border-bottom: 1px solid #e4e7ed; }
.fm-toolbar-left { display: flex; align-items: center; gap: 6px; }
.fm-btn { padding: 4px 11px; font-size: 12px; border-radius: 5px; border: 1px solid #dcdfe6; background: #fff; cursor: pointer; }
.fm-btn-danger { color: #f56c6c; background: #fff0f0; border-color: #fbc4c4; }
.fm-btn-ghost:hover { color: #409eff; border-color: #a0cfff; background: #ecf5ff; }
.fm-search-input { width: 260px; height: 30px; padding: 0 10px; font-size: 12px; border: 1px solid #dcdfe6; border-radius: 5px; outline: none; }
.fm-head, .fm-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 120px 190px 90px; align-items: center; padding: 0 16px; }
.fm-head { height: 36px; background: #f4f5f7; border-bottom: 1px solid #e4e7ed; font-size: 12px; font-weight: 600; color: #606266; }
.fm-scroll { flex: 1; overflow: auto; }
.fm-row { min-height: 36px; border-bottom: 1px solid #ebeef5; font-size: 13px; }
.fm-row-dir { background: #fafbfc; cursor: pointer; }
.fm-row-selected { background: #ecf5ff !important; }
.fm-empty { display: flex; align-items: center; justify-content: center; height: 180px; color: #c0c4cc; font-size: 13px; }
.fm-name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.fm-arrow { width: 14px; display: inline-flex; align-items: center; justify-content: center; color: #909399; transition: transform .16s; white-space: nowrap; }
.fm-arrow.open { transform: rotate(90deg); color: #409eff; }
.fm-arrow-placeholder { width: 14px; flex: 0 0 14px; }
.fm-file-icon { width: 22px; flex: 0 0 22px; display: inline-flex; align-items: center; justify-content: center; color: #409eff; }
.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-link-danger { background: #fff0f0; color: #f56c6c; border: 1px solid #fbc4c4; border-radius: 4px; padding: 2px 8px; cursor: pointer; }
.fm-check { width: 14px; height: 14px; cursor: pointer; accent-color: #409eff; }
@media (max-width: 1280px) {
  .summary-grid { grid-template-columns: 1fr; }
  .card-header { flex-direction: column; align-items: flex-start; }
  .header-actions { width: 100%; justify-content: flex-start; }
}
</style>



