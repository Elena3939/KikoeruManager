<template>
  <div class="library">
    <h1 class="page-title">库存文件管理</h1>
    
    <el-card shadow="never" class="main-card">
      <template #header>
        <div class="card-header">
          <span class="header-title">库内文件列表</span>
          <div class="header-actions">
            <el-button @click="refreshLibrary" :loading="loading">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
            <el-button @click="toggleAllSelection">
              {{ isAllSelected ? '取消全选' : '全选' }}
            </el-button>
            <el-input
              v-model="searchQuery"
              placeholder="搜索文件名或RJ号"
              style="width: 250px;"
              clearable
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
          </div>
        </div>
      </template>

      <el-table
        ref="tableRef"
        :data="paginatedFiles"
        v-loading="loading"
        style="width: 100%"
        empty-text="暂无文件"
        row-key="id"
        @selection-change="handleSelectionChange"
        :default-sort="{ prop: 'unzip_time', order: 'descending' }"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column
          prop="name"
          label="文件名"
          show-overflow-tooltip
          sortable
        >
          <template #default="{ row }">
            <el-icon class="file-icon"><Folder /></el-icon>
            <span class="file-name">{{ row.name }}</span>
          </template>
        </el-table-column>

        <el-table-column
          prop="rjcode"
          label="RJ 号"
          width="120"
          sortable
        >
          <template #default="{ row }">
            <el-tag v-if="row.rjcode" type="primary" size="small" effect="light">{{ row.rjcode }}</el-tag>
            <span v-else class="empty-text">-</span>
          </template>
        </el-table-column>

        <el-table-column
          prop="size"
          label="大小"
          width="100"
          sortable
        >
          <template #default="{ row }">
            {{ formatFileSize(row.size) }}
          </template>
        </el-table-column>

        <el-table-column
          prop="unzip_time"
          label="解压时间"
          width="180"
          sortable
        >
          <template #default="{ row }">
            {{ formatDate(row.unzip_time) }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <div class="action-grid">
              <div class="action-grid-row">
                <el-button
                  size="small"
                  type="primary"
                  @click="openFolder(row)"
                  class="action-btn"
                >
                  <el-icon><Folder /></el-icon>
                  打开
                </el-button>
                <el-button
                  size="small"
                  type="info"
                  @click="openFolderDirect(row)"
                  class="action-btn"
                  title="直接打开文件夹（需安装 Tampermonkey 脚本）"
                >
                  直接打开
                </el-button>
              </div>
              <div class="action-grid-row">
                <el-button
                  size="small"
                  type="warning"
                  @click="renameItem(row)"
                  :loading="renamingId === row.id"
                  class="action-btn"
                >
                  重命名
                </el-button>
                <el-button
                  size="small"
                  type="success"
                  @click="apiRenameItem(row)"
                  :loading="apiRenamingId === row.id"
                  class="action-btn"
                  title="重新获取 DLsite 元数据并重命名"
                >
                  API 重命名
                </el-button>
              </div>
              <div class="action-grid-row">
                <el-button
                  size="small"
                  type="info"
                  plain
                  @click="openFolderContentsDialog(row)"
                  class="action-btn"
                >
                  <el-icon><Files /></el-icon>
                  文件管理
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  @click="deleteItem(row)"
                  class="action-btn btn-delete"
                  title="删除此项目"
                >
                  删除
                </el-button>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="batch-actions" v-if="selectedRows.length > 0">
        <div class="batch-left">
          <span class="selected-count">已选择 {{ selectedRows.length }} 项</span>
        </div>
        <div class="batch-right">
          <el-button-group>
            <el-button
              size="small"
              type="danger"
              plain
              @click="handleBatchDelete"
              :loading="batchDeleting"
            >
              <el-icon><Delete /></el-icon>批量删除
            </el-button>
            <el-button
              size="small"
              type="warning"
              plain
              @click="handleBatchApiRename"
              :loading="batchRenaming"
            >
              <el-icon><Edit /></el-icon>批量 API重命名
            </el-button>
          </el-button-group>
          <el-button
            size="small"
            @click="clearSelection"
          >
            取消选择
          </el-button>
        </div>
      </div>

      <div class="pagination-container">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="totalFiles"
          layout="total, sizes, prev, pager, next"
          background
        />
      </div>
    </el-card>

    <el-dialog
      v-model="renameDialogVisible"
      title="重命名"
      width="500px"
      destroy-on-close
    >
      <el-form :model="renameForm" label-width="80px">
        <el-form-item label="当前名称">
          <el-input v-model="renameForm.currentName" disabled />
        </el-form-item>
        <el-form-item label="新名称">
          <el-input v-model="renameForm.newName" placeholder="输入新名称" />
        </el-form-item>
        <el-form-item label="预览">
          <div class="name-preview">{{ renameForm.newName || renameForm.currentName }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="renameDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="confirmRename" :loading="isRenaming">
            确认重命名
          </el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog
      v-model="mappedPathDialogVisible"
      title="跨设备访问 - 路径映射"
      width="600px"
    >
      <el-alert
        title="检测到跨设备部署环境"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 20px;"
      >
        <template #default>
          由于应用部署在远程服务器/Docker中，无法直接打开本地文件夹。请使用下方映射后的路径手动打开。
        </template>
      </el-alert>

      <el-descriptions :column="1" border class="path-descriptions">
        <el-descriptions-item label="远程路径">
          <code class="path-code">{{ mappedPathInfo.originalPath }}</code>
        </el-descriptions-item>
        <el-descriptions-item label="本地映射路径">
          <div class="mapped-path-container">
            <code class="path-code mapped-path">{{ mappedPathInfo.mappedPath }}</code>
            <div class="path-actions">
              <el-button
                type="primary"
                size="small"
                @click="copyMappedPath"
              >
                复制路径
              </el-button>
              <el-button
                type="success"
                size="small"
                @click="openWithBrowser"
                title="尝试用浏览器打开（可能被安全设置阻止）"
              >
                尝试打开
              </el-button>
            </div>
          </div>
        </el-descriptions-item>
        <el-descriptions-item label="映射状态">
          <el-tag :type="mappedPathInfo.isMapped ? 'success' : 'warning'" effect="light">
            {{ mappedPathInfo.isMapped ? '已配置映射' : '未配置映射（使用原路径）' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <div class="path-mapping-help">
        <h4>如何使用：</h4>
        <ol>
          <li>点击"复制路径"按钮复制映射后的本地路径</li>
          <li>打开 Windows 文件资源管理器</li>
          <li>在地址栏粘贴路径并按回车</li>
        </ol>
        <p class="help-tip">
          提示：如果路径无法访问，请检查网络驱动器映射是否正确配置。
        </p>
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="mappedPathDialogVisible = false">关闭</el-button>
          <el-button type="primary" @click="copyMappedPath">复制路径</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog
      v-model="folderContentsDialogVisible"
      width="900px"
      :title="`文件管理 - ${folderContentsInfo.folderName || ''}`"
      destroy-on-close
    >
      <div class="folder-dialog-toolbar">
        <div class="folder-toolbar-left">
          <el-tag type="info">共 {{ visibleFileCount }} / {{ folderContentsInfo.totalFiles }} 个文件</el-tag>
          <el-button
            size="small"
            type="danger"
            plain
            :disabled="folderSelectedFiles.length === 0"
            @click="batchDeleteSubFiles"
          >
            批量删除({{ folderSelectedFiles.length }})
          </el-button>
        </div>
        <el-input
          v-model="folderContentsSearch"
          placeholder="搜索子文件名或路径"
          clearable
          style="width: 320px;"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>

      <el-table
        ref="folderTableRef"
        :data="filteredFolderFiles"
        v-loading="folderContentsLoading"
        row-key="id"
        max-height="460"
        default-expand-all
        :tree-props="{ children: 'children' }"
        @selection-change="handleFolderSelectionChange"
      >
        <el-table-column type="selection" width="45" :selectable="selectFolderRow" />
        <el-table-column label="文件" min-width="360" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="folder-file-cell">
              <el-icon class="folder-type-icon">
                <Folder v-if="row.type === 'dir'" />
                <component v-else :is="getFileIconComponent(row.name)" />
              </el-icon>
              <el-button v-if="row.type === 'file'" link type="primary" @click="openSubFile(row)">
                {{ row.name }}
              </el-button>
              <span v-else>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="relative_path" label="相对路径" min-width="260" show-overflow-tooltip />
        <el-table-column label="大小" width="120">
          <template #default="{ row }">
            {{ row.type === 'file' ? formatFileSize(row.size) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="修改时间" width="180">
          <template #default="{ row }">
            {{ row.type === 'file' ? formatDate(row.modified_time) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.type === 'file'" link type="danger" @click="deleteSubFile(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import {
  Refresh,
  Search,
  Folder,
  Delete,
  Edit,
  Files,
  VideoPlay,
  Picture,
  Headset,
  Document
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { libraryApi } from '../api'

const PAGE_SIZES = [10, 20, 50, 100]
const PAGE_SIZE_STORAGE_KEY = 'kikoeru.ui.library.pageSize'

function loadPersistedPageSize(fallback) {
  try {
    const raw = window.localStorage.getItem(PAGE_SIZE_STORAGE_KEY)
    const num = Number(raw)
    if (PAGE_SIZES.includes(num)) return num
  } catch (_) {}
  return fallback
}

function persistPageSize(size) {
  try {
    window.localStorage.setItem(PAGE_SIZE_STORAGE_KEY, String(size))
  } catch (_) {}
}

const loading = ref(false)
const files = ref([])
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = ref(loadPersistedPageSize(20))
const renamingId = ref(null)
const apiRenamingId = ref(null)
const selectedRows = ref([])
const batchDeleting = ref(false)
const batchRenaming = ref(false)
const isAllSelected = ref(false)
const tableRef = ref(null)
const folderTableRef = ref(null)

// 重命名对话框
const renameDialogVisible = ref(false)
const renameForm = ref({
  id: '',
  currentName: '',
  newName: '',
  path: ''
})
const isRenaming = ref(false)

// 路径映射对话框
const mappedPathDialogVisible = ref(false)
const mappedPathInfo = ref({
  originalPath: '',
  mappedPath: '',
  isMapped: false
})

// Tampermonkey 脚本检测
const tampermonkeyLoaded = ref(false)

const folderContentsDialogVisible = ref(false)
const folderContentsLoading = ref(false)
const folderContentsSearch = ref('')
const folderContentsInfo = ref({
  folderName: '',
  folderPath: '',
  totalFiles: 0
})
const folderContentsFiles = ref([])
const folderSelectedFiles = ref([])

// 过滤后的文件列表
const filteredFiles = computed(() => {
  let result = files.value

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(file =>
      file.name.toLowerCase().includes(query) ||
      (file.rjcode && file.rjcode.toLowerCase().includes(query))
    )
  }

  return result
})

// 总文件数
const totalFiles = computed(() => filteredFiles.value.length)

// 分页后的文件列表（排序在分页前进行）
const paginatedFiles = computed(() => {
  // Element Plus 的表格会自动处理排序，这里只需要返回过滤后的数据即可
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  const result = filteredFiles.value.slice(start, end)
  console.log(`[Library Pagination] Page ${currentPage.value}, Size ${pageSize.value}, Start ${start}, End ${end}, Total ${filteredFiles.value.length}, Result ${result.length}`)
  return result
})

const filteredFolderFiles = computed(() => {
  const query = folderContentsSearch.value.trim().toLowerCase()
  const tree = buildFolderTree(folderContentsFiles.value)
  if (!query) {
    return tree
  }
  return filterTreeByQuery(tree, query)
})

const visibleFileCount = computed(() => countFiles(filteredFolderFiles.value))

watch(pageSize, (size) => {
  persistPageSize(size)
  currentPage.value = 1
})

onMounted(() => {
  refreshLibrary()

  // 检查 Tampermonkey 脚本是否已加载（脚本可能已经在页面加载前完成）
  if (window.kikoeruHelperLoaded) {
    console.log('[Kikoeru] Tampermonkey 助手已预先加载')
    tampermonkeyLoaded.value = true
  }

  // 监听 Tampermonkey 脚本就绪事件（脚本可能在页面加载后才加载）
  window.addEventListener('kikoeru-helper-ready', (event) => {
    console.log('[Kikoeru] Tampermonkey 助手已加载', event.detail)
    tampermonkeyLoaded.value = true
  })

  // 5秒后再次检查（兜底机制）
  setTimeout(() => {
    if (!tampermonkeyLoaded.value && window.kikoeruHelperLoaded) {
      console.log('[Kikoeru] 延迟检测到 Tampermonkey')
      tampermonkeyLoaded.value = true
    }
  }, 5000)

})

async function refreshLibrary() {
  loading.value = true
  try {
    const data = await libraryApi.listFiles()
    files.value = data.files || []
    ElMessage.success(`已加载 ${files.value.length} 个文件`)
  } catch (error) {
    console.error('获取库文件失败:', error)
    ElMessage.error('获取库文件失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '-'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

// 选择处理函数
function handleSelectionChange(selection) {
  selectedRows.value = selection
  isAllSelected.value = selection.length === paginatedFiles.value.length && paginatedFiles.value.length > 0
}

function toggleAllSelection() {
  if (isAllSelected.value) {
    // 取消全选
    if (tableRef.value && tableRef.value.clearSelection) {
      tableRef.value.clearSelection()
    }
  } else {
    // 全选当前页
    paginatedFiles.value.forEach(row => {
      if (tableRef.value && tableRef.value.toggleRowSelection) {
        tableRef.value.toggleRowSelection(row, true)
      }
    })
  }
}

function clearSelection() {
  if (tableRef.value && tableRef.value.clearSelection) {
    tableRef.value.clearSelection()
  }
}

function handleMoreCommand(command, row) {
  switch (command) {
    case 'direct-open':
      openFolderDirect(row)
      break
    case 'rename':
      renameItem(row)
      break
    case 'delete':
      deleteItem(row)
      break
  }
}

function getFileIconComponent(fileName) {
  const ext = fileName.split('.').pop()?.toLowerCase() || ''
  const audioExts = ['mp3', 'wav', 'flac', 'm4a', 'ogg', 'aac', 'opus']
  const subtitleExts = ['srt', 'lrc', 'ass', 'ssa', 'vtt', 'sub']
  const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp']
  const videoExts = ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'webm']
  if (audioExts.includes(ext)) return Headset
  if (subtitleExts.includes(ext)) return Document
  if (imageExts.includes(ext)) return Picture
  if (videoExts.includes(ext)) return VideoPlay
  return Files
}

function buildFolderTree(fileItems) {
  const root = []
  const dirMap = new Map()
  const sortedFiles = [...fileItems].sort((a, b) => a.relative_path.localeCompare(b.relative_path))
  for (const file of sortedFiles) {
    const parts = (file.relative_path || file.name).split('/').filter(Boolean)
    if (parts.length === 0) continue
    let currentChildren = root
    let currentPath = ''
    for (let i = 0; i < parts.length - 1; i += 1) {
      const dirName = parts[i]
      currentPath = currentPath ? `${currentPath}/${dirName}` : dirName
      const dirId = `dir:${currentPath}`
      if (!dirMap.has(dirId)) {
        const dirNode = {
          id: dirId,
          name: dirName,
          type: 'dir',
          relative_path: currentPath,
          children: []
        }
        dirMap.set(dirId, dirNode)
        currentChildren.push(dirNode)
      }
      currentChildren = dirMap.get(dirId).children
    }
    const fileNode = {
      ...file,
      id: `file:${file.path}`,
      type: 'file'
    }
    currentChildren.push(fileNode)
  }
  return root
}

function filterTreeByQuery(nodes, query) {
  const result = []
  for (const node of nodes) {
    const selfMatched = (node.name || '').toLowerCase().includes(query) ||
      (node.relative_path || '').toLowerCase().includes(query)
    if (node.type === 'file') {
      if (selfMatched) {
        result.push(node)
      }
      continue
    }
    const children = filterTreeByQuery(node.children || [], query)
    if (selfMatched || children.length > 0) {
      result.push({
        ...node,
        children
      })
    }
  }
  return result
}

function countFiles(nodes) {
  let total = 0
  for (const node of nodes) {
    if (node.type === 'file') {
      total += 1
    } else if (node.children?.length) {
      total += countFiles(node.children)
    }
  }
  return total
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  let date = new Date(dateStr)
  if (typeof dateStr === 'string' && dateStr.includes('T') && !/[zZ]|[+-]\d{2}:\d{2}$/.test(dateStr)) {
    const localDateStr = dateStr.replace('T', ' ')
    date = new Date(localDateStr)
  }
  if (Number.isNaN(date.getTime())) return dateStr
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

async function openFolder(row) {
  try {
    const data = await libraryApi.openFolder(row.path)

    if (data.mode === 'mapped') {
      mappedPathInfo.value = {
        originalPath: data.original_path,
        mappedPath: data.mapped_path,
        isMapped: data.is_mapped
      }
      mappedPathDialogVisible.value = true
      return
    }

    ElMessage.success('已打开文件夹')
  } catch (error) {
    console.error('打开文件夹失败:', error)
    ElMessage.error(error.response?.data?.detail || '打开文件夹失败')
  }
}

// 直接打开文件夹（跳过弹窗）
async function openFolderDirect(row) {
  try {
    const data = await libraryApi.openFolder(row.path)

    let targetPath
    if (data.mode === 'mapped') {
      targetPath = data.mapped_path
    } else {
      ElMessage.success('已打开文件夹')
      return
    }

    const hasTampermonkey = window.kikoeruHelperLoaded || tampermonkeyLoaded.value

    console.log('[Kikoeru] 尝试直接打开:', targetPath, 'Tampermonkey状态:', hasTampermonkey)

    try {
      window.dispatchEvent(new CustomEvent('kikoeru-open-folder', {
        detail: { path: targetPath }
      }))

      if (hasTampermonkey) {
        ElMessage.success('正在打开文件夹...')
      } else {
        ElMessage.info('正在尝试打开文件夹...')

        setTimeout(() => {
          if (!window.kikoeruHelperLoaded && !tampermonkeyLoaded.value) {
            showTampermonkeyDialog(targetPath)
          }
        }, 2000)
      }
      return
    } catch (err) {
      console.error('[Kikoeru] 发送打开事件失败:', err)
    }

    showTampermonkeyDialog(targetPath)
  } catch (error) {
    console.error('直接打开失败:', error)
    ElMessage.error(error.response?.data?.detail || '打开文件夹失败')
  }
}

// 显示 Tampermonkey 安装提示对话框
async function showTampermonkeyDialog(targetPath) {
  ElMessage.warning('Tampermonkey 脚本未安装或加载失败，无法直接打开')

  // 复制路径并显示安装提示
  try {
    await navigator.clipboard.writeText(targetPath)
    ElMessage.success('路径已复制到剪贴板')
  } catch (err) {
    console.error('复制失败:', err)
  }

  ElMessageBox.confirm(
    `直接打开需要安装 Tampermonkey 脚本。<br><br>
    <strong>已复制路径：</strong><code>${targetPath}</code><br><br>
    是否查看安装教程？`,
    '需要 Tampermonkey',
    {
      confirmButtonText: '查看安装教程',
      cancelButtonText: '手动打开',
      type: 'warning',
      dangerouslyUseHTMLString: true
    }
  ).then(() => {
    window.open('https://github.com/canforgive/KikoeruTool/blob/main/tampermonkey/kikoeru-folder-opener.js', '_blank')
  })
}

// 复制映射路径到剪贴板
async function copyMappedPath() {
  try {
    await navigator.clipboard.writeText(mappedPathInfo.value.mappedPath)
    ElMessage.success('路径已复制到剪贴板')
  } catch (err) {
    console.error('复制失败:', err)
    ElMessage.error('复制失败，请手动复制')
  }
}

// 尝试用浏览器打开文件夹
function openWithBrowser() {
  const localPath = mappedPathInfo.value.mappedPath

  // 方法1: 尝试使用 Tampermonkey（如果已安装）
  if (window.kikoeruHelperLoaded || tampermonkeyLoaded.value) {
    console.log('[Kikoeru] 使用 Tampermonkey 打开:', localPath)
    window.dispatchEvent(new CustomEvent('kikoeru-open-folder', {
      detail: { path: localPath }
    }))
    ElMessage.success('已发送打开请求给 Tampermonkey')
    return
  }

  // 方法2: 普通浏览器方式（大概率失败）
  // 将 Windows 路径转换为 file 协议格式
  let fileUrl = localPath.replace(/\\/g, '/')

  // 如果是 Windows 驱动器路径（如 V:\...），添加 file:///
  if (/^[a-zA-Z]:/.test(fileUrl)) {
    fileUrl = 'file:///' + fileUrl
  } else {
    fileUrl = 'file://' + fileUrl
  }

  console.log('尝试打开路径:', fileUrl)

  // 尝试 window.open
  let opened = false
  try {
    const win = window.open(fileUrl, '_blank')
    if (win) {
      opened = true
      console.log('window.open 成功')
    }
  } catch (err) {
    console.log('window.open 失败:', err)
  }

  // 尝试 iframe
  if (!opened) {
    try {
      const iframe = document.createElement('iframe')
      iframe.style.display = 'none'
      iframe.src = fileUrl
      document.body.appendChild(iframe)
      setTimeout(() => document.body.removeChild(iframe), 1000)
      opened = true
    } catch (err) {
      console.log('iframe 方式失败:', err)
    }
  }

  if (opened) {
    ElMessage.success('已尝试打开文件夹')
  } else {
    // 所有方法都失败，提示安装 Tampermonkey
    ElMessage.warning('浏览器阻止了直接打开操作')

    ElMessageBox.confirm(
      `浏览器安全策略阻止了直接打开本地文件夹。<br><br>
      <strong>推荐方案：</strong>安装 Tampermonkey 脚本<br>
      安装后点击"尝试打开"即可直接打开文件夹<br><br>
      <strong>临时方案：</strong>路径已复制，请手动打开`,
      '无法直接打开',
      {
        confirmButtonText: '查看 Tampermonkey 脚本',
        cancelButtonText: '手动打开',
        type: 'warning',
        dangerouslyUseHTMLString: true
      }
    ).then(() => {
      // 打开 GitHub 上的脚本页面
      window.open('https://github.com/canforgive/KikoeruTool/blob/main/tampermonkey/kikoeru-folder-opener.js', '_blank')
    }).catch(() => {
      // 用户选择手动打开，复制路径
      copyMappedPath()
    })
  }
}

function renameItem(row) {
  renameForm.value = {
    id: row.id,
    currentName: row.name,
    newName: row.name,
    path: row.path
  }
  renameDialogVisible.value = true
}

async function confirmRename() {
  if (!renameForm.value.newName || renameForm.value.newName === renameForm.value.currentName) {
    ElMessage.warning('请输入不同的新名称')
    return
  }

  isRenaming.value = true
  try {
    await libraryApi.rename(renameForm.value.path, renameForm.value.newName)

    ElMessage.success('重命名成功')
    renameDialogVisible.value = false
    await refreshLibrary()
  } catch (error) {
    console.error('重命名失败:', error)
    ElMessage.error('重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    isRenaming.value = false
  }
}

async function apiRenameItem(row) {
  try {
    await ElMessageBox.confirm(
      `确定要重新获取DLsite元数据并重命名吗？\n\n当前: ${row.name}`,
      'API重新命名确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info'
      }
    )
  } catch {
    return
  }

  apiRenamingId.value = row.id
  try {
    const data = await libraryApi.apiRename(row.path)

    ElMessage.success(data.message)

    if (data.new_name) {
      ElMessage.info(`新名称: ${data.new_name}`)
    }

    await refreshLibrary()
  } catch (error) {
    console.error('API重命名失败:', error)
    ElMessage.error('API重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    apiRenamingId.value = null
  }
}

// 删除项目
async function deleteItem(row) {
  try {
    const confirmData = await libraryApi.delete(row.path, false)

    if (confirmData.need_confirm) {
      const type = confirmData.type === 'folder' ? '文件夹' : '文件'
      const size = formatFileSize(confirmData.size)

      await ElMessageBox.confirm(
        `确定要删除以下${type}吗？

名称: ${confirmData.name}
大小: ${size}

此操作不可恢复！`,
        '删除确认',
        {
          confirmButtonText: '确定删除',
          cancelButtonText: '取消',
          type: 'warning',
          confirmButtonClass: 'el-button--danger'
        }
      )

      await libraryApi.delete(row.path, true)

      ElMessage.success('删除成功')
      await refreshLibrary()
    }
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') {
      return
    }
    console.error('删除失败:', error)
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function openFolderContentsDialog(row) {
  if (!row?.is_directory) {
    ElMessage.warning('只有文件夹支持文件管理')
    return
  }
  folderContentsDialogVisible.value = true
  folderContentsSearch.value = ''
  await loadFolderContents(row.path, row.name)
}

async function openSubFile(fileItem) {
  if (fileItem.type !== 'file') {
    return
  }
  try {
    const data = await libraryApi.openFolder(fileItem.path)
    if (data.mode === 'mapped') {
      mappedPathInfo.value = {
        originalPath: data.original_path,
        mappedPath: data.mapped_path,
        isMapped: data.is_mapped
      }
      mappedPathDialogVisible.value = true
      return
    }
    ElMessage.success('已打开文件位置')
  } catch (error) {
    console.error('打开子文件失败:', error)
    ElMessage.error('打开失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function deleteSubFile(fileItem) {
  if (fileItem.type !== 'file') {
    return
  }
  try {
    const confirmData = await libraryApi.delete(fileItem.path, false)
    const size = formatFileSize(confirmData.size)
    await ElMessageBox.confirm(
      `确定删除该文件吗？\n\n名称: ${confirmData.name}\n大小: ${size}\n\n此操作不可恢复！`,
      '删除子文件确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )
    await libraryApi.delete(fileItem.path, true)
    ElMessage.success('子文件删除成功')
    await loadFolderContents(folderContentsInfo.value.folderPath, folderContentsInfo.value.folderName)
    await refreshLibrary()
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') {
      return
    }
    console.error('删除子文件失败:', error)
    ElMessage.error('删除子文件失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function loadFolderContents(path, folderName = '') {
  folderContentsLoading.value = true
  try {
    const data = await libraryApi.folderContents(path)
    folderContentsInfo.value = {
      folderName: data.folder_name || folderName,
      folderPath: data.folder_path || path,
      totalFiles: data.total_files || 0
    }
    folderContentsFiles.value = data.items || []
    folderSelectedFiles.value = []
    folderTableRef.value?.clearSelection?.()
  } catch (error) {
    console.error('加载文件夹内容失败:', error)
    if (error.code === 'FOLDER_CONTENTS_UNSUPPORTED') {
      ElMessage.error('加载失败：当前运行的后端版本过旧，请重启后端或使用最新 build 产物')
    } else {
      ElMessage.error('加载文件夹内容失败: ' + (error.response?.data?.detail || error.message))
    }
    folderContentsDialogVisible.value = false
  } finally {
    folderContentsLoading.value = false
  }
}

function selectFolderRow(row) {
  return row.type === 'file'
}

function handleFolderSelectionChange(selection) {
  folderSelectedFiles.value = selection.filter(item => item.type === 'file')
}

async function batchDeleteSubFiles() {
  if (folderSelectedFiles.value.length === 0) {
    ElMessage.warning('请先选择要删除的子文件')
    return
  }
  const paths = folderSelectedFiles.value.map(item => item.path)
  try {
    const preview = await libraryApi.batchDelete(paths, false)
    const sizeText = formatFileSize(preview.total_size || 0)
    await ElMessageBox.confirm(
      `确定删除选中的 ${preview.total_count || paths.length} 个子文件吗？\n\n总大小: ${sizeText}\n\n此操作不可恢复！`,
      '批量删除子文件确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )
    const result = await libraryApi.batchDelete(paths, true)
    ElMessage.success(`批量删除完成：成功 ${result.success_count || 0} 个`)
    await loadFolderContents(folderContentsInfo.value.folderPath, folderContentsInfo.value.folderName)
    await refreshLibrary()
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') {
      return
    }
    console.error('批量删除子文件失败:', error)
    ElMessage.error('批量删除失败: ' + (error.response?.data?.detail || error.message))
  }
}
</script>

<style scoped>
.library {
  max-width: 1400px;
  margin: 0 auto;
  padding: 16px;
}

/* 页面标题区 */
.page-title {
  font-size: 24px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 20px;
  letter-spacing: 0.5px;
}

/* 卡片整体微调 */
.main-card {
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.02) !important;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 表格细化 */
:deep(.el-table) {
  --el-table-header-bg-color: #f8f9fa;
  --el-table-header-text-color: #606266;
  border-radius: 4px;
}

:deep(.el-table th.el-table__cell) {
  font-weight: 600;
}

.file-icon {
  margin-right: 8px;
  color: #409eff;
  vertical-align: middle;
  font-size: 16px;
}

.file-name {
  vertical-align: middle;
  font-weight: 500;
  color: #303133;
}

.empty-text {
  color: #c0c4cc;
}

/* 操作按钮组 (精细化排版与动效) */
.action-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.action-grid-row {
  display: flex;
  gap: 6px;
}

.action-btn {
  flex: 1;
  margin: 0 !important; /* 强制去除 Element 默认兄弟间距 */
  border-radius: 4px;
  font-weight: 500;
  transition: all 0.25s cubic-bezier(0.25, 0.8, 0.25, 1);
}

.action-btn i {
  margin-right: 4px;
}

.action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

/* 独立删除按钮若有特殊需求可保留，由于原生 danger 已经很好看，这里只做宽度统一 */
.btn-delete {
  width: 100%;
}

/* 批量操作工具栏 */
.batch-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background-color: #f8f9fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 16px;
  margin-top: 16px;
}

.batch-left {
  display: flex;
  align-items: center;
}

.batch-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.selected-count {
  font-weight: 600;
  color: #409eff;
  font-size: 14px;
  background-color: #ecf5ff;
  padding: 4px 12px;
  border-radius: 12px;
}

.folder-dialog-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.folder-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.folder-file-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.folder-type-icon {
  color: #409eff;
  font-size: 16px;
}

/* 分页区 */
.pagination-container {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}

/* 对话框内元素美化 */
.name-preview {
  padding: 10px 14px;
  background-color: #f8f9fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 13px;
  color: #606266;
  word-break: break-all;
  line-height: 1.5;
}

/* 路径映射相关美化 */
.path-descriptions :deep(.el-descriptions__label) {
  width: 110px;
  justify-content: center;
}

.path-code {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 13px;
  color: #303133;
  word-break: break-all;
}

.mapped-path-container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.mapped-path {
  flex: 1;
  min-width: 0;
  background-color: #f8f9fa;
  padding: 6px 10px;
  border-radius: 4px;
  border: 1px solid #ebeef5;
  color: #606266;
}

.path-actions {
  display: flex;
  gap: 8px;
}

.path-mapping-help {
  margin-top: 20px;
  padding: 16px 20px;
  background-color: #f8f9fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}

.path-mapping-help h4 {
  margin-top: 0;
  margin-bottom: 12px;
  color: #303133;
}

.path-mapping-help ol {
  margin-bottom: 0;
  padding-left: 20px;
  color: #606266;
  line-height: 1.8;
}

.help-tip {
  margin-top: 12px;
  margin-bottom: 0;
  color: #909399;
  font-size: 12px;
}
</style>
