<template>
  <el-dialog v-model="visible" width="1100px" class="fm-dialog folder-dialog" destroy-on-close>
    <template #header>
      <div class="fm-header">
        <div class="fm-title">
          <span>{{ folderContentsInfo.folderName || '文件管理' }}</span>
          <span class="fm-badge">{{ formatFileSize(folderContentsInfo.totalSize) }}</span>
        </div>
        <div class="fm-count">{{ visibleFileCount }} / {{ folderContentsInfo.totalFiles }} 个文件</div>
      </div>
    </template>

    <div class="fm-body" v-loading="folderLoading" element-loading-text="正在加载目录内容...">
      <div class="fm-toolbar">
        <div class="fm-toolbar-left">
          <button
            class="fm-btn fm-btn-danger"
            :disabled="!folderSelectedDeletePaths.length || folderDeleting"
            @click="batchDeleteSubFiles"
          >
            批量删除
          </button>
          <button class="fm-btn fm-btn-ghost" :disabled="folderLoading || folderDeleting" @click="reload">刷新</button>
          <button class="fm-btn fm-btn-ghost" :disabled="folderLoading" @click="expandAll">展开全部</button>
          <button class="fm-btn fm-btn-ghost" :disabled="folderLoading" @click="collapseAll">折叠全部</button>
        </div>
        <div class="fm-search">
          <input
            v-model="folderSearch"
            class="fm-search-input"
            placeholder="搜索文件名或路径..."
            :disabled="folderLoading || folderDeleting"
            @input="onSearchInput"
          >
        </div>
      </div>

      <div v-if="folderSelectedDeleteRoots.length" class="fm-selection-bar">
        <span>已选 {{ folderSelectedDeleteRoots.length }} 项待删</span>
        <span>预计大小 {{ formatFileSize(folderSelectedDeleteSize) }}</span>
      </div>

      <div class="fm-head">
        <div class="fm-col-check">
          <input
            type="checkbox"
            class="fm-check"
            :checked="allFilesSelected"
            :indeterminate.prop="someFilesSelected"
            :disabled="folderLoading || folderDeleting"
            @click="toggleAllFiles"
          >
        </div>
        <div class="fm-col-name">文件名</div>
        <div class="fm-col-size">大小</div>
        <div class="fm-col-time">修改时间</div>
        <div class="fm-col-action">操作</div>
      </div>

      <div class="fm-scroll">
        <div v-if="!folderLoading && flatTree.length === 0" class="fm-empty">
          {{ folderSearch ? '没有匹配项' : '当前目录为空' }}
        </div>

        <div
          v-for="row in flatTree"
          :key="row.id"
          class="fm-row"
          :class="{ 'fm-row-dir': row.type === 'dir', 'fm-row-selected': selectedFileIds.has(row.id) }"
          @click="handleFolderRowClick(row, $event)"
        >
          <div class="fm-col-check" @click.stop>
            <input
              type="checkbox"
              class="fm-check"
              :checked="selectedFileIds.has(row.id)"
              :disabled="folderDeleting"
              @click.stop="toggleFileSelect(row, $event)"
            >
          </div>
          <div class="fm-col-name">
            <div class="fm-name-cell" :style="{ paddingLeft: `${row.depth * 18 + 4}px` }">
              <button
                v-if="row.type === 'dir'"
                type="button"
                class="fm-arrow-btn"
                :class="{ open: expandedIds.has(row.id) }"
                @click.stop="toggleExpand(row)"
              >
                &gt;
              </button>
              <span v-else class="fm-arrow-placeholder"></span>
              <span class="fm-file-icon">
                <el-icon><component :is="resolveTreeIcon(row)" /></el-icon>
              </span>
              <span class="fm-name-text">{{ row.name }}</span>
            </div>
          </div>
          <div class="fm-col-size">{{ formatFileSize(row.size) }}</div>
          <div class="fm-col-time">{{ formatDate(row.modified_time) }}</div>
          <div class="fm-col-action" @click.stop>
            <button class="fm-link-danger" :disabled="folderDeleting" @click="deleteEntry(row)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Folder, FolderOpened, Headset, Picture, Tickets, VideoPlay } from '@element-plus/icons-vue'
import { libraryApi } from '../../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  libraryId: { type: String, default: '' },
  folderPath: { type: String, default: '' },
  folderName: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue', 'mutated'])

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value)
})

const folderLoading = ref(false)
const folderDeleting = ref(false)
const folderSearch = ref('')
const folderContentsInfo = ref({
  folderName: '',
  folderPath: '',
  totalFiles: 0,
  totalSize: 0
})
const folderItems = ref([])
const selectedFileIds = ref(new Set())
const expandedIds = ref(new Set())
const folderLastSelectedId = ref('')

const treeRoot = computed(() => buildTree(folderItems.value, folderContentsInfo.value.folderPath))
const folderNodeById = computed(() => {
  const map = new Map()
  const walk = nodes => {
    for (const node of nodes) {
      map.set(node.id, node)
      if (node.children?.length) walk(node.children)
    }
  }
  walk(treeRoot.value)
  return map
})
const filteredRoot = computed(() => {
  const keyword = folderSearch.value.trim().toLowerCase()
  return keyword ? filterTree(treeRoot.value, keyword) : treeRoot.value
})
const flatTree = computed(() => flattenTree(filteredRoot.value, 0, expandedIds.value))
const visibleFileCount = computed(() => flatTree.value.filter(item => item.type === 'file').length)
const allSelectableIds = computed(() => flatTree.value.map(item => item.id))
const allFilesSelected = computed(() => allSelectableIds.value.length > 0 && allSelectableIds.value.every(id => selectedFileIds.value.has(id)))
const someFilesSelected = computed(() => !allFilesSelected.value && allSelectableIds.value.some(id => selectedFileIds.value.has(id)))
const folderSelectedRows = computed(() => [...selectedFileIds.value].map(id => folderNodeById.value.get(id)).filter(Boolean))
const folderSelectedDeleteRoots = computed(() => {
  const rows = [...folderSelectedRows.value].sort((left, right) => String(left.relative_path || '').length - String(right.relative_path || '').length)
  const roots = []
  for (const row of rows) {
    const rowPath = normalizeAnyPath(resolveNodePath(row))
    if (!rowPath) continue
    if (roots.some(existing => isDescendantPath(rowPath, normalizeAnyPath(resolveNodePath(existing))))) continue
    roots.push(row)
  }
  return roots
})
const folderSelectedDeletePaths = computed(() => folderSelectedDeleteRoots.value.map(row => resolveNodePath(row)).filter(Boolean))
const folderSelectedDeleteSize = computed(() => folderSelectedDeleteRoots.value.reduce((sum, row) => sum + Number(row?.size || 0), 0))

watch(visible, async value => {
  if (value) {
    window.addEventListener('keydown', handleDialogKeydown)
    await reload()
    return
  }
  window.removeEventListener('keydown', handleDialogKeydown)
})

watch(() => props.folderPath, async (nextPath, prevPath) => {
  if (!visible.value || !nextPath || nextPath === prevPath) return
  await reload()
})

function handleDialogKeydown (event) {
  if (!visible.value || folderLoading.value || folderDeleting.value || isTextInputElement(event.target)) return
  const key = String(event.key || '').toLowerCase()
  if ((event.ctrlKey || event.metaKey) && key === 'a') {
    event.preventDefault()
    selectedFileIds.value = new Set(getFolderSelectableIds())
    folderLastSelectedId.value = allSelectableIds.value.at(-1) || ''
  }
}

async function reload () {
  if (!props.folderPath || !props.libraryId) return
  folderLoading.value = true
  try {
    const previousExpanded = new Set([...expandedIds.value].map(id => String(id).replace(/^dir:/, '')))
    const previousSelected = new Set(selectedFileIds.value)
    const data = await libraryApi.browserFolderContents(props.libraryId, props.folderPath)
    const items = Array.isArray(data.items) ? data.items : []
    folderItems.value = items
    folderContentsInfo.value = {
      folderName: data.folder_name || props.folderName || '',
      folderPath: data.folder_path || props.folderPath || '',
      totalFiles: Number(data.total_files || items.length || 0),
      totalSize: items.reduce((sum, item) => sum + Number(item?.size || 0), 0)
    }

    const directories = []
    const walk = nodes => nodes.forEach(node => {
      if (node.type === 'dir') {
        directories.push(node)
        walk(node.children || [])
      }
    })
    walk(treeRoot.value)

    if (previousExpanded.size) {
      expandedIds.value = new Set(directories.filter(node => previousExpanded.has(node.relative_path)).map(node => node.id))
    } else {
      expandedIds.value = new Set(directories.map(node => node.id))
    }

    const validIds = new Set(folderNodeById.value.keys())
    selectedFileIds.value = new Set([...previousSelected].filter(id => validIds.has(id)))
    if (folderLastSelectedId.value && !validIds.has(folderLastSelectedId.value)) {
      folderLastSelectedId.value = ''
    }
  } catch (error) {
    visible.value = false
    ElMessage.error('加载文件夹内容失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    folderLoading.value = false
  }
}

async function deleteEntry (row) {
  const path = resolveNodePath(row)
  if (!path) return
  await deletePaths([path], { previewRow: row })
}

async function batchDeleteSubFiles () {
  if (!folderSelectedDeletePaths.value.length) return
  await deletePaths(folderSelectedDeletePaths.value, { previewRows: folderSelectedDeleteRoots.value })
}

async function deletePaths (paths, options = {}) {
  const { previewRow = null, previewRows = [] } = options
  const effectivePreviewRow = previewRow || (paths.length === 1 && previewRows.length === 1 ? previewRows[0] : null)
  folderDeleting.value = true
  try {
    if (paths.length === 1) {
      const preview = await libraryApi.browserDelete(props.libraryId, paths[0], false)
      await ElMessageBox.confirm(
        buildDeletePreviewMessage(preview, effectivePreviewRow),
        '删除确认',
        {
          confirmButtonText: '确定删除',
          cancelButtonText: '取消',
          type: 'warning',
          confirmButtonClass: 'el-button--danger'
        }
      )
      await libraryApi.browserDelete(props.libraryId, paths[0], true)
      ElMessage.success('删除成功')
      const previewCounts = getRowDeleteCounts(effectivePreviewRow)
      emit('mutated', {
        deletedBytes: resolveDeletePreviewSize(preview?.size, effectivePreviewRow?.size),
        deletedFolderCount: Number(preview?.folder_count ?? previewCounts.folderCount)
      })
    } else {
      const preview = await libraryApi.browserBatchDelete(props.libraryId, paths, false)
      await ElMessageBox.confirm(
        buildBatchDeletePreviewMessage(preview, previewRows),
        '批量删除确认',
        {
          confirmButtonText: '确定删除',
          cancelButtonText: '取消',
          type: 'warning',
          confirmButtonClass: 'el-button--danger'
        }
      )
      const result = await libraryApi.browserBatchDelete(props.libraryId, paths, true)
      const failedCount = Number(result?.failed_paths?.length || 0)
      if (failedCount) {
        ElMessage.warning(`批量删除完成：成功 ${result.success_count || 0} 项，失败 ${failedCount} 项`)
      } else {
        ElMessage.success(`批量删除完成：成功 ${result.success_count || 0} 项`)
      }
      const previewCounts = getRowsDeleteCounts(previewRows)
      emit('mutated', {
        deletedBytes: resolveDeletePreviewSize(preview?.total_size, previewRows.reduce((sum, row) => sum + Number(row?.size || 0), 0)),
        deletedFolderCount: Number(preview?.total_folder_count ?? previewCounts.folderCount)
      })
    }
    selectedFileIds.value = new Set()
    folderLastSelectedId.value = ''
    await reload()
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    folderDeleting.value = false
  }
}

function buildTree (items, basePath) {
  const root = []
  const dirMap = new Map()
  const sorted = [...items].sort((a, b) => String(a.relative_path || '').localeCompare(String(b.relative_path || '')))

  for (const item of sorted) {
    const parts = String(item.relative_path || item.name || '').split('/').filter(Boolean)
    if (!parts.length) continue
    let children = root
    let path = ''

    for (let index = 0; index < parts.length - 1; index++) {
      path = path ? `${path}/${parts[index]}` : parts[index]
      const key = `dir:${path}`
      if (!dirMap.has(key)) {
        const node = {
          id: key,
          name: parts[index],
          type: 'dir',
          relative_path: path,
          resolved_path: joinFolderPath(basePath, path),
          size: 0,
          modified_time: null,
          children: []
        }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }

    children.push({
      ...item,
      id: `file:${item.path}`,
      type: 'file',
      resolved_path: item.path
    })
  }

  const walk = node => {
    let total = 0
    let latest = null
    for (const child of node.children || []) {
      if (child.type === 'dir') walk(child)
      total += Number(child.size || 0)
      if (child.modified_time && (!latest || child.modified_time > latest)) latest = child.modified_time
    }
    node.size = total
    node.modified_time = latest
  }

  root.forEach(node => {
    if (node.type === 'dir') walk(node)
  })
  return root
}

function filterTree (nodes, keyword) {
  const result = []
  for (const node of nodes) {
    const matched = String(node.name || '').toLowerCase().includes(keyword) || String(node.relative_path || '').toLowerCase().includes(keyword)
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
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) {
      result.push(...flattenTree(node.children, depth + 1, openIds))
    }
  }
  return result
}

function toggleExpand (node) {
  if (node?.type !== 'dir') return
  const next = new Set(expandedIds.value)
  if (next.has(node.id)) next.delete(node.id)
  else next.add(node.id)
  expandedIds.value = next
}

function expandAll () {
  const next = new Set()
  const walk = nodes => nodes.forEach(node => {
    if (node.type === 'dir') {
      next.add(node.id)
      walk(node.children || [])
    }
  })
  walk(filteredRoot.value)
  expandedIds.value = next
}

function collapseAll () {
  expandedIds.value = new Set()
}

function onSearchInput () {
  if (folderSearch.value.trim()) expandAll()
}

function getFolderSelectableIds () {
  return flatTree.value.map(row => row.id)
}

function selectFolderRange (targetId, preserveExisting = true) {
  const rowIds = getFolderSelectableIds()
  const targetIndex = rowIds.indexOf(targetId)
  if (targetIndex === -1) return
  const anchorId = folderLastSelectedId.value && rowIds.includes(folderLastSelectedId.value) ? folderLastSelectedId.value : rowIds[0]
  const anchorIndex = rowIds.indexOf(anchorId)
  const [start, end] = [anchorIndex, targetIndex].sort((left, right) => left - right)
  const next = preserveExisting ? new Set(selectedFileIds.value) : new Set()
  rowIds.slice(start, end + 1).forEach(id => next.add(id))
  selectedFileIds.value = next
  folderLastSelectedId.value = targetId
}

function toggleFileSelect (row, event = null) {
  if (!row?.id) return
  if (event?.shiftKey) {
    selectFolderRange(row.id, true)
    return
  }
  const next = new Set(selectedFileIds.value)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  selectedFileIds.value = next
  folderLastSelectedId.value = row.id
}

function toggleAllFiles () {
  const checked = !allFilesSelected.value
  selectedFileIds.value = checked ? new Set(allSelectableIds.value) : new Set()
  folderLastSelectedId.value = checked ? allSelectableIds.value.at(-1) || '' : ''
}

function handleFolderRowClick (row, event) {
  if (!row?.id) return
  if (event?.shiftKey) {
    selectFolderRange(row.id, true)
    return
  }
  toggleFileSelect(row, event)
}

function resolveNodePath (row) {
  return row?.resolved_path || row?.path || ''
}

function normalizeAnyPath (value) {
  return String(value || '').replace(/\\/g, '/').replace(/\/+$/, '')
}

function isDescendantPath (candidate, parent) {
  if (!candidate || !parent) return false
  return candidate === parent || candidate.startsWith(`${parent}/`)
}

function fileIcon (name = '') {
  const lower = String(name || '').toLowerCase()
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(lower)) return Headset
  if (/\.(png|jpg|jpeg|webp|bmp|gif)$/i.test(lower)) return Picture
  if (/\.(mp4|mkv|avi|mov|wmv|webm)$/i.test(lower)) return VideoPlay
  if (/\.(lrc|srt|ass|ssa|vtt)$/i.test(lower)) return Tickets
  return Document
}

function resolveTreeIcon (row) {
  if (row?.type === 'dir') return expandedIds.value.has(row.id) ? FolderOpened : Folder
  return fileIcon(row?.name || '')
}

function joinFolderPath (basePath, relativePath) {
  if (!relativePath) return basePath
  const base = String(basePath || '').replace(/[\\/]+$/, '')
  const relative = String(relativePath || '').replace(/^[/\\]+/, '')
  return `${base}/${relative}`
}

function formatFileSize (bytes) {
  if (bytes === null || bytes === undefined) return '-'
  const value = Number(bytes || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(2)} ${units[index]}`
}

function formatDate (value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function getRowDeleteCounts (row) {
  if (!row) return { folderCount: 0, fileCount: 0 }
  if (row.type === 'file') return { folderCount: 0, fileCount: 1 }

  let folderCount = row.type === 'dir' ? 1 : 0
  let fileCount = 0
  const walk = nodes => {
    for (const child of nodes || []) {
      if (child?.type === 'dir') {
        folderCount += 1
        walk(child.children || [])
      } else if (child?.type === 'file') {
        fileCount += 1
      }
    }
  }
  walk(row.children || [])
  return { folderCount, fileCount }
}

function getRowsDeleteCounts (rows = []) {
  return rows.reduce((result, row) => {
    const counts = getRowDeleteCounts(row)
    result.folderCount += counts.folderCount
    result.fileCount += counts.fileCount
    return result
  }, { folderCount: 0, fileCount: 0 })
}

function resolveDeletePreviewSize (previewSize, fallbackSize = 0) {
  const normalizedPreviewSize = Number(previewSize)
  const normalizedFallbackSize = Number(fallbackSize || 0)
  if (Number.isFinite(normalizedPreviewSize) && normalizedPreviewSize > 0) return normalizedPreviewSize
  if (Number.isFinite(normalizedFallbackSize) && normalizedFallbackSize > 0) return normalizedFallbackSize
  return 0
}

function buildDeletePreviewMessage (preview, row = null) {
  const itemType = preview?.type || (row?.type === 'dir' ? 'folder' : 'file')
  const rowCounts = getRowDeleteCounts(row)
  const fileCount = Number(preview?.file_count ?? rowCounts.fileCount ?? (itemType === 'file' ? 1 : 0))
  const folderCount = Number(preview?.folder_count ?? rowCounts.folderCount ?? (itemType === 'folder' || itemType === 'dir' ? 1 : 0))
  const size = resolveDeletePreviewSize(preview?.size, row?.size)
  const lines = ['删除后将移除以下内容：']
  if (itemType === 'folder' || itemType === 'dir') {
    lines.push(`文件夹：${Math.max(folderCount, 1)} 个`)
    if (fileCount) lines.push(`文件：${fileCount} 个`)
  } else {
    lines.push(`文件：${Math.max(fileCount, 1)} 个`)
  }
  lines.push(`大小：${formatFileSize(size)}`)
  lines.push('')
  lines.push('此操作不可恢复，是否继续？')
  return lines.join('\n')
}

function buildBatchDeletePreviewMessage (preview, rows = []) {
  const totalCount = rows.length
  const rowCounts = getRowsDeleteCounts(rows)
  const folderCount = Number(preview?.total_folder_count ?? rowCounts.folderCount)
  const fileCount = Number(preview?.total_file_count ?? rowCounts.fileCount)
  const size = resolveDeletePreviewSize(preview?.total_size, rows.reduce((sum, row) => sum + Number(row?.size || 0), 0))
  return [
    `已选择 ${totalCount} 项待删除`,
    `文件夹：${folderCount} 个`,
    `文件：${fileCount} 个`,
    `大小：${formatFileSize(size)}`,
    '',
    '此操作不可恢复，是否继续？'
  ].join('\n')
}

function isTextInputElement (target) {
  if (!target) return false
  const tagName = String(target.tagName || '').toUpperCase()
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(tagName) || Boolean(target.isContentEditable)
}

defineExpose({ reload })

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleDialogKeydown)
})
</script>

<style scoped>
.folder-dialog :deep(.el-dialog) { border-radius: 8px; overflow: hidden; box-shadow: 0 16px 48px rgba(0, 0, 0, 0.18); }
.folder-dialog :deep(.el-dialog__header) { padding: 0; margin: 0; }
.folder-dialog :deep(.el-dialog__body) { padding: 0; }
.fm-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px 12px 20px; border-bottom: 1px solid #e4e7ed; }
.fm-title { display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600; color: #303133; min-width: 0; }
.fm-badge { font-size: 12px; color: #909399; background: #f5f7fa; border: 1px solid #e4e7ed; border-radius: 10px; padding: 2px 8px; }
.fm-count { font-size: 12px; color: #606266; background: #f0f7ff; border: 1px solid #c6e2ff; border-radius: 12px; padding: 2px 10px; }
.fm-body { display: flex; flex-direction: column; height: 540px; background: #fff; }
.fm-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 9px 16px; background: #f8f9fa; border-bottom: 1px solid #e4e7ed; }
.fm-toolbar-left { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.fm-btn { padding: 4px 11px; font-size: 12px; border-radius: 5px; border: 1px solid #dcdfe6; background: #fff; cursor: pointer; transition: color .18s ease, border-color .18s ease, background-color .18s ease, box-shadow .18s ease, transform .12s ease; }
.fm-btn:disabled { opacity: .55; cursor: not-allowed; box-shadow: none; transform: none; }
.fm-btn-danger { color: #f56c6c; background: #fff0f0; border-color: #fbc4c4; }
.fm-btn-danger:hover:not(:disabled) { color: #fff; background: #f56c6c; border-color: #f56c6c; box-shadow: 0 8px 18px rgba(245, 108, 108, 0.22); }
.fm-btn-danger:active:not(:disabled) { transform: translateY(1px); background: #e25757; border-color: #e25757; }
.fm-btn-ghost:hover:not(:disabled) { color: #409eff; border-color: #a0cfff; background: #ecf5ff; box-shadow: 0 6px 14px rgba(64, 158, 255, 0.12); }
.fm-btn-ghost:active:not(:disabled) { transform: translateY(1px); box-shadow: none; }
.fm-search-input { width: 260px; height: 30px; padding: 0 10px; font-size: 12px; border: 1px solid #dcdfe6; border-radius: 5px; outline: none; }
.fm-selection-bar { display: flex; gap: 16px; align-items: center; padding: 10px 16px; border-bottom: 1px solid #f1d4d0; background: #fff7f6; font-size: 12px; color: #a14d47; }
.fm-head, .fm-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 120px 190px 90px; align-items: center; padding: 0 16px; }
.fm-head { height: 36px; background: #f4f5f7; border-bottom: 1px solid #e4e7ed; font-size: 12px; font-weight: 600; color: #606266; }
.fm-scroll { flex: 1; overflow: auto; contain: strict; }
.fm-row { min-height: 36px; border-bottom: 1px solid #ebeef5; font-size: 13px; contain: layout paint style; }
.fm-row-dir { background: #fafbfc; }
.fm-row-selected { background: #ecf5ff !important; }
.fm-empty { display: flex; align-items: center; justify-content: center; height: 180px; color: #c0c4cc; font-size: 13px; }
.fm-name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.fm-arrow-btn { width: 16px; height: 16px; border: none; background: transparent; color: #909399; cursor: pointer; padding: 0; transition: transform .16s; }
.fm-arrow-btn.open { transform: rotate(90deg); color: #409eff; }
.fm-arrow-placeholder { width: 16px; flex: 0 0 16px; }
.fm-file-icon { width: 22px; flex: 0 0 22px; display: inline-flex; align-items: center; justify-content: center; color: #409eff; }
.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-link-danger { background: #fff0f0; color: #f56c6c; border: 1px solid #fbc4c4; border-radius: 4px; padding: 2px 8px; cursor: pointer; transition: color .18s ease, border-color .18s ease, background-color .18s ease, box-shadow .18s ease, transform .12s ease; }
.fm-link-danger:hover:not(:disabled) { color: #fff; background: #f56c6c; border-color: #f56c6c; box-shadow: 0 6px 14px rgba(245, 108, 108, 0.2); }
.fm-link-danger:active:not(:disabled) { transform: translateY(1px); background: #e25757; border-color: #e25757; box-shadow: none; }
.fm-link-danger:disabled { opacity: .55; cursor: not-allowed; box-shadow: none; transform: none; }
.fm-check { width: 14px; height: 14px; cursor: pointer; accent-color: #409eff; }
</style>
