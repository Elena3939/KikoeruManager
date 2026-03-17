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
        <el-table-column prop="name" label="文件名" show-overflow-tooltip sortable>
          <template #default="{ row }">
            <el-icon class="file-icon"><Folder /></el-icon>
            <span class="file-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="rjcode" label="RJ 号" width="120" sortable>
          <template #default="{ row }">
            <el-tag v-if="row.rjcode" type="primary" size="small" effect="light">{{ row.rjcode }}</el-tag>
            <span v-else class="empty-text">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="size" label="大小" width="100" sortable>
          <template #default="{ row }">{{ formatFileSize(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="unzip_time" label="解压时间" width="180" sortable>
          <template #default="{ row }">{{ formatDate(row.unzip_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <div class="action-grid">
              <div class="action-grid-row">
                <el-button size="small" type="primary" @click="openFolder(row)" class="action-btn">
                  <el-icon><Folder /></el-icon>打开
                </el-button>
                <el-button size="small" type="info" @click="openFolderDirect(row)" class="action-btn">直接打开</el-button>
              </div>
              <div class="action-grid-row">
                <el-button size="small" type="warning" @click="renameItem(row)" :loading="renamingId === row.id" class="action-btn">重命名</el-button>
                <el-button size="small" type="success" @click="apiRenameItem(row)" :loading="apiRenamingId === row.id" class="action-btn">API 重命名</el-button>
              </div>
              <div class="action-grid-row">
                <el-button size="small" type="info" plain @click="openFolderContentsDialog(row)" class="action-btn">
                  <el-icon><Files /></el-icon>文件管理
                </el-button>
                <el-button size="small" type="danger" @click="deleteItem(row)" class="action-btn">删除</el-button>
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
            <el-button size="small" type="danger" plain @click="handleBatchDelete" :loading="batchDeleting">
              <el-icon><Delete /></el-icon>批量删除
            </el-button>
            <el-button size="small" type="warning" plain @click="handleBatchApiRename" :loading="batchRenaming">
              <el-icon><Edit /></el-icon>批量 API重命名
            </el-button>
          </el-button-group>
          <el-button size="small" @click="clearSelection">取消选择</el-button>
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

    <!-- 重命名对话框 -->
    <el-dialog v-model="renameDialogVisible" title="重命名" width="500px" destroy-on-close>
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
        <el-button @click="renameDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmRename" :loading="isRenaming">确认重命名</el-button>
      </template>
    </el-dialog>

    <!-- 路径映射对话框 -->
    <el-dialog v-model="mappedPathDialogVisible" title="跨设备访问 - 路径映射" width="600px">
      <el-alert title="检测到跨设备部署环境" type="info" :closable="false" show-icon style="margin-bottom: 20px;">
        <template #default>由于应用部署在远程服务器/Docker中，无法直接打开本地文件夹。请使用下方映射后的路径手动打开。</template>
      </el-alert>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="远程路径">
          <code class="path-code">{{ mappedPathInfo.originalPath }}</code>
        </el-descriptions-item>
        <el-descriptions-item label="本地映射路径">
          <div class="mapped-path-container">
            <code class="path-code mapped-path">{{ mappedPathInfo.mappedPath }}</code>
            <div class="path-actions">
              <el-button type="primary" size="small" @click="copyMappedPath">复制路径</el-button>
              <el-button type="success" size="small" @click="openWithBrowser">尝试打开</el-button>
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
        <p class="help-tip">提示：如果路径无法访问，请检查网络驱动器映射是否正确配置。</p>
      </div>
      <template #footer>
        <el-button @click="mappedPathDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="copyMappedPath">复制路径</el-button>
      </template>
    </el-dialog>

    <!-- ★ 文件管理对话框 -->
    <el-dialog
      v-model="folderContentsDialogVisible"
      width="1100px"
      destroy-on-close
      class="fm-dialog"
      :show-close="true"
    >
      <template #header>
        <div class="fm-header">
          <div class="fm-header-left">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">
              <path d="M1.5 3.5C1.5 2.67 2.17 2 3 2H5.88C6.27 2 6.64 2.16 6.9 2.44L7.72 3.33C7.84 3.46 8 3.5 8.12 3.5H13C13.83 3.5 14.5 4.17 14.5 5V12.5C14.5 13.33 13.83 14 13 14H3C2.17 14 1.5 13.33 1.5 12.5V3.5Z" fill="rgba(64,158,255,0.12)" stroke="#409eff" stroke-width="1.2"/>
            </svg>
            <span class="fm-header-name">{{ folderContentsInfo.folderName || '文件管理' }}</span>
          </div>
          <div class="fm-header-right">
            <span class="fm-header-count">
              <b>{{ visibleFileCount }}</b>&nbsp;/&nbsp;{{ folderContentsInfo.totalFiles }} 个文件
            </span>
          </div>
        </div>
      </template>

      <div class="fm-body" v-loading="folderContentsLoading">
        <!-- 工具栏 -->
        <div class="fm-toolbar">
          <div class="fm-toolbar-left">
            <button
              class="fm-btn fm-btn--danger"
              :class="{ 'fm-btn--disabled': folderSelectedFiles.length === 0 }"
              :disabled="folderSelectedFiles.length === 0"
              @click="batchDeleteSubFiles"
            >
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M5.333 4V2.667A1.333 1.333 0 016.667 1.333h2.666A1.333 1.333 0 0110.667 2.667V4m2 0l-.667 9.333A1.333 1.333 0 0110.667 14.667H5.333A1.333 1.333 0 014 13.333L3.333 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
              批量删除
              <span v-if="folderSelectedFiles.length > 0" class="fm-badge">{{ folderSelectedFiles.length }}</span>
            </button>
            <button class="fm-btn fm-btn--ghost" @click="expandAll">
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M3 5l5 5 5-5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
              展开全部
            </button>
            <button class="fm-btn fm-btn--ghost" @click="collapseAll">
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M3 11l5-5 5 5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
              折叠全部
            </button>
          </div>
          <div class="fm-toolbar-right">
            <div class="fm-search">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" class="fm-search-ico"><circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.4"/><path d="M10 10l3.5 3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
              <input
                v-model="folderContentsSearch"
                class="fm-search-input"
                placeholder="搜索文件名或路径…"
                @input="onSearchInput"
              />
              <button v-if="folderContentsSearch" class="fm-search-clear" @click="folderContentsSearch = ''">✕</button>
            </div>
          </div>
        </div>

        <!-- 列头 -->
        <div class="fm-thead">
          <div class="fm-th fm-col-check">
            <input
              type="checkbox"
              class="fm-check"
              :checked="allFilesSelected"
              :indeterminate.prop="someFilesSelected"
              @change="toggleAllFiles"
            />
          </div>
          <div class="fm-th fm-col-name">文件名</div>
          <div class="fm-th fm-col-path">相对路径</div>
          <div class="fm-th fm-col-size">大小</div>
          <div class="fm-th fm-col-time">修改时间</div>
          <div class="fm-th fm-col-action">操作</div>
        </div>

        <!-- 文件树（扁平化渲染） -->
        <div class="fm-scroll">
          <div v-if="!folderContentsLoading && flatTree.length === 0" class="fm-empty">
            <svg width="36" height="36" viewBox="0 0 48 48" fill="none"><rect x="4" y="12" width="40" height="30" rx="3" stroke="#c0c4cc" stroke-width="2"/><path d="M4 18h40M4 12l9-8h12l4 8" stroke="#c0c4cc" stroke-width="2" stroke-linejoin="round"/></svg>
            <span>{{ folderContentsSearch ? '无匹配文件' : '文件夹为空' }}</span>
          </div>

          <div
            v-for="row in flatTree"
            :key="row.id"
            class="fm-row"
            :class="{
              'fm-row--dir': row.type === 'dir',
              'fm-row--file': row.type === 'file',
              'fm-row--selected': selectedFileIds.has(row.id),
            }"
            @click="row.type === 'dir' ? toggleExpand(row) : null"
          >
            <!-- 勾选 -->
            <div class="fm-td fm-col-check" @click.stop>
              <input
                v-if="row.type === 'file'"
                type="checkbox"
                class="fm-check"
                :checked="selectedFileIds.has(row.id)"
                @change="toggleFileSelect(row)"
              />
            </div>

            <!-- 文件名 -->
            <div class="fm-td fm-col-name">
              <div class="fm-name-cell" :style="{ paddingLeft: (row.depth * 20 + 4) + 'px' }">
                <!-- 缩进竖引导线 -->
                <span
                  v-for="d in row.depth"
                  :key="d"
                  class="fm-guide"
                  :style="{ left: ((d - 1) * 20 + 12) + 'px' }"
                />
                <!-- 折叠箭头 / 占位 -->
                <span v-if="row.type === 'dir'" class="fm-arrow-wrap" @click.stop="toggleExpand(row)">
                  <svg
                    class="fm-arrow"
                    :class="{ 'fm-arrow--open': expandedIds.has(row.id) }"
                    width="12" height="12" viewBox="0 0 12 12" fill="none"
                  >
                    <path d="M4 2.5l4 3.5-4 3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </span>
                <span v-else class="fm-arrow-placeholder" />

                <!-- 类型图标 -->
                <span class="fm-icon">
                  <!-- 文件夹 -->
                  <svg v-if="row.type === 'dir'" width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M1.5 3.5C1.5 2.67 2.17 2 3 2H5.88C6.27 2 6.64 2.16 6.9 2.44L7.5 3.1A.84.84 0 008.07 3.3H13C13.83 3.3 14.5 3.97 14.5 4.8V12.5C14.5 13.33 13.83 14 13 14H3C2.17 14 1.5 13.33 1.5 12.5V3.5Z"
                      :fill="expandedIds.has(row.id) ? 'rgba(232,160,33,0.35)' : 'rgba(232,160,33,0.15)'"
                      stroke="#e8a021" stroke-width="1.2"/>
                  </svg>
                  <!-- 音频 -->
                  <svg v-else-if="getFileType(row.name) === 'audio'" width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <rect x="1.5" y="2" width="13" height="12" rx="2" fill="rgba(77,156,248,0.12)" stroke="#4d9cf8" stroke-width="1.2"/>
                    <path d="M5.5 6v4m2-5.5v7m2-5v3m2-4.5v6" stroke="#4d9cf8" stroke-width="1.2" stroke-linecap="round"/>
                  </svg>
                  <!-- 图片 -->
                  <svg v-else-if="getFileType(row.name) === 'image'" width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <rect x="1.5" y="2" width="13" height="12" rx="2" fill="rgba(74,222,128,0.12)" stroke="#4ade80" stroke-width="1.2"/>
                    <circle cx="5.5" cy="6.5" r="1.2" fill="#4ade80"/>
                    <path d="M2 12l3.5-3.5 2.5 2.5 2-2L14 12" stroke="#4ade80" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  <!-- 视频 -->
                  <svg v-else-if="getFileType(row.name) === 'video'" width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <rect x="1.5" y="2" width="13" height="12" rx="2" fill="rgba(167,139,250,0.12)" stroke="#a78bfa" stroke-width="1.2"/>
                    <path d="M6 5.5l5 2.5-5 2.5V5.5z" fill="#a78bfa"/>
                  </svg>
                  <!-- 字幕 -->
                  <svg v-else-if="getFileType(row.name) === 'subtitle'" width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <rect x="1.5" y="2" width="13" height="12" rx="2" fill="rgba(251,146,60,0.12)" stroke="#fb923c" stroke-width="1.2"/>
                    <path d="M4 7h8M4 10h5" stroke="#fb923c" stroke-width="1.2" stroke-linecap="round"/>
                  </svg>
                  <!-- 通用 -->
                  <svg v-else width="14" height="14" viewBox="0 0 16 16" fill="none">
                    <path d="M3 2h7l3 3v9a1 1 0 01-1 1H3a1 1 0 01-1-1V3a1 1 0 011-1z" fill="rgba(148,163,184,0.15)" stroke="#94a3b8" stroke-width="1.2"/>
                    <path d="M10 2v3h3" stroke="#94a3b8" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </span>

                <span
                  class="fm-name-text"
                  :class="{ 'fm-name-text--dir': row.type === 'dir' }"
                  :title="row.name"
                >{{ row.name }}</span>
              </div>
            </div>

            <!-- 相对路径 -->
            <div class="fm-td fm-col-path">
              <span class="fm-mono-sm" :title="row.relative_path">{{ row.relative_path }}</span>
            </div>

            <!-- 大小 -->
            <div class="fm-td fm-col-size">
              <span class="fm-size-text">{{ row.type === 'file' ? formatFileSize(row.size) : '—' }}</span>
            </div>

            <!-- 修改时间 -->
            <div class="fm-td fm-col-time">
              <span class="fm-mono-sm">{{ row.type === 'file' ? formatDate(row.modified_time) : '—' }}</span>
            </div>

            <!-- 操作 -->
            <div class="fm-td fm-col-action" @click.stop>
              <template v-if="row.type === 'file'">
                <button class="fm-link fm-link--primary" @click="openSubFile(row)">打开</button>
                <button class="fm-link fm-link--danger" @click="deleteSubFile(row)">删除</button>
              </template>
              <template v-else-if="row.type === 'dir'">
                <button class="fm-link fm-link--danger" @click="deleteSubDir(row)">删除</button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { Refresh, Search, Folder, Delete, Edit, Files } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { libraryApi } from '../api'

// ─── 持久化分页 ──────────────────────────────────────────────
const PAGE_SIZES = [10, 20, 50, 100]
const PAGE_SIZE_KEY = 'kikoeru.ui.library.pageSize'
function loadPageSize (fb) {
  try { const n = Number(localStorage.getItem(PAGE_SIZE_KEY)); if (PAGE_SIZES.includes(n)) return n } catch (_) {}
  return fb
}

// ─── 库列表状态 ───────────────────────────────────────────────
const loading = ref(false)
const files = ref([])
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = ref(loadPageSize(20))
const renamingId = ref(null)
const apiRenamingId = ref(null)
const selectedRows = ref([])
const batchDeleting = ref(false)
const batchRenaming = ref(false)
const isAllSelected = ref(false)
const tableRef = ref(null)

const renameDialogVisible = ref(false)
const renameForm = ref({ id: '', currentName: '', newName: '', path: '' })
const isRenaming = ref(false)

const mappedPathDialogVisible = ref(false)
const mappedPathInfo = ref({ originalPath: '', mappedPath: '', isMapped: false })
const tampermonkeyLoaded = ref(false)

// ─── 文件管理对话框状态 ───────────────────────────────────────
const folderContentsDialogVisible = ref(false)
const folderContentsLoading = ref(false)
const folderContentsSearch = ref('')
const folderContentsInfo = ref({ folderName: '', folderPath: '', totalFiles: 0 })
const folderContentsFiles = ref([])
const selectedFileIds = ref(new Set())
const expandedIds = ref(new Set())

// ─── 库列表计算 ───────────────────────────────────────────────
const filteredFiles = computed(() => {
  if (!searchQuery.value) return files.value
  const q = searchQuery.value.toLowerCase()
  return files.value.filter(f => f.name.toLowerCase().includes(q) || (f.rjcode && f.rjcode.toLowerCase().includes(q)))
})
const totalFiles = computed(() => filteredFiles.value.length)
const paginatedFiles = computed(() => {
  const s = (currentPage.value - 1) * pageSize.value
  return filteredFiles.value.slice(s, s + pageSize.value)
})
watch(pageSize, v => { try { localStorage.setItem(PAGE_SIZE_KEY, String(v)) } catch (_) {}; currentPage.value = 1 })

// ─── 文件管理 - 树构建 ────────────────────────────────────────
function buildTree (items) {
  const root = []
  const dirMap = new Map()
  const sorted = [...items].sort((a, b) => a.relative_path.localeCompare(b.relative_path))
  for (const item of sorted) {
    const parts = (item.relative_path || item.name).split('/').filter(Boolean)
    if (!parts.length) continue
    let children = root
    let curPath = ''
    for (let i = 0; i < parts.length - 1; i++) {
      const seg = parts[i]
      curPath = curPath ? `${curPath}/${seg}` : seg
      const key = `dir:${curPath}`
      if (!dirMap.has(key)) {
        const node = { id: key, name: seg, type: 'dir', relative_path: curPath, children: [] }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }
    children.push({ ...item, id: `file:${item.path}`, type: 'file' })
  }
  return root
}

function filterTree (nodes, q) {
  const result = []
  for (const n of nodes) {
    const match = (n.name || '').toLowerCase().includes(q) || (n.relative_path || '').toLowerCase().includes(q)
    if (n.type === 'file') { if (match) result.push(n) }
    else {
      const children = filterTree(n.children || [], q)
      if (match || children.length) result.push({ ...n, children })
    }
  }
  return result
}

function flattenTree (nodes, depth, openIds) {
  const result = []
  for (const n of nodes) {
    result.push({ ...n, depth })
    if (n.type === 'dir' && openIds.has(n.id) && n.children?.length)
      result.push(...flattenTree(n.children, depth + 1, openIds))
  }
  return result
}

const treeRoot = computed(() => buildTree(folderContentsFiles.value))
const filteredRoot = computed(() => {
  const q = folderContentsSearch.value.trim().toLowerCase()
  return q ? filterTree(treeRoot.value, q) : treeRoot.value
})
const flatTree = computed(() => flattenTree(filteredRoot.value, 0, expandedIds.value))
const visibleFileCount = computed(() => flatTree.value.filter(r => r.type === 'file').length)
const allSelectableIds = computed(() => flatTree.value.filter(r => r.type === 'file').map(r => r.id))
const allFilesSelected = computed(() =>
  allSelectableIds.value.length > 0 && allSelectableIds.value.every(id => selectedFileIds.value.has(id))
)
const someFilesSelected = computed(() =>
  !allFilesSelected.value && allSelectableIds.value.some(id => selectedFileIds.value.has(id))
)
const folderSelectedFiles = computed(() =>
  folderContentsFiles.value.filter(f => selectedFileIds.value.has(`file:${f.path}`))
)

// ─── 树交互 ───────────────────────────────────────────────────
function toggleExpand (node) {
  const s = new Set(expandedIds.value)
  s.has(node.id) ? s.delete(node.id) : s.add(node.id)
  expandedIds.value = s
}

function expandAll () {
  const s = new Set()
  const walk = (nodes) => { for (const n of nodes) { if (n.type === 'dir') { s.add(n.id); walk(n.children || []) } } }
  walk(filteredRoot.value)
  expandedIds.value = s
}

function collapseAll () { expandedIds.value = new Set() }

function toggleFileSelect (row) {
  const s = new Set(selectedFileIds.value)
  s.has(row.id) ? s.delete(row.id) : s.add(row.id)
  selectedFileIds.value = s
}

function toggleAllFiles () {
  selectedFileIds.value = allFilesSelected.value ? new Set() : new Set(allSelectableIds.value)
}

function onSearchInput () { if (folderContentsSearch.value) expandAll() }

function getFileType (name) {
  const ext = (name.split('.').pop() || '').toLowerCase()
  if (['mp3','wav','flac','m4a','ogg','aac','opus'].includes(ext)) return 'audio'
  if (['jpg','jpeg','png','gif','webp','bmp','avif'].includes(ext)) return 'image'
  if (['mp4','mkv','avi','mov','wmv','webm'].includes(ext)) return 'video'
  if (['srt','lrc','ass','ssa','vtt','sub'].includes(ext)) return 'subtitle'
  return 'generic'
}

// ─── 工具函数 ─────────────────────────────────────────────────
function formatFileSize (bytes) {
  if (!bytes) return '-'
  const k = 1024, sizes = ['B','KB','MB','GB','TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function formatDate (dateStr) {
  if (!dateStr) return '-'
  let d = new Date(dateStr)
  if (typeof dateStr === 'string' && dateStr.includes('T') && !/[zZ]|[+-]\d{2}:\d{2}$/.test(dateStr))
    d = new Date(dateStr.replace('T', ' '))
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleString('zh-CN', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12: false })
}

// ─── 生命周期 ─────────────────────────────────────────────────
onMounted(() => {
  refreshLibrary()
  if (window.kikoeruHelperLoaded) tampermonkeyLoaded.value = true
  window.addEventListener('kikoeru-helper-ready', () => { tampermonkeyLoaded.value = true })
  setTimeout(() => { if (!tampermonkeyLoaded.value && window.kikoeruHelperLoaded) tampermonkeyLoaded.value = true }, 5000)
})

// ─── API ──────────────────────────────────────────────────────
async function refreshLibrary () {
  loading.value = true
  try {
    const data = await libraryApi.listFiles()
    files.value = data.files || []
    ElMessage.success(`已加载 ${files.value.length} 个文件`)
  } catch (e) { ElMessage.error('获取库文件失败: ' + (e.response?.data?.detail || e.message))
  } finally { loading.value = false }
}

function handleSelectionChange (sel) {
  selectedRows.value = sel
  isAllSelected.value = sel.length === paginatedFiles.value.length && paginatedFiles.value.length > 0
}
function toggleAllSelection () {
  if (isAllSelected.value) tableRef.value?.clearSelection()
  else paginatedFiles.value.forEach(r => tableRef.value?.toggleRowSelection(r, true))
}
function clearSelection () { tableRef.value?.clearSelection() }

async function openFolder (row) {
  try {
    const data = await libraryApi.openFolder(row.path)
    if (data.mode === 'mapped') { mappedPathInfo.value = { originalPath: data.original_path, mappedPath: data.mapped_path, isMapped: data.is_mapped }; mappedPathDialogVisible.value = true; return }
    ElMessage.success('已打开文件夹')
  } catch (e) { ElMessage.error(e.response?.data?.detail || '打开文件夹失败') }
}

async function openFolderDirect (row) {
  try {
    const data = await libraryApi.openFolder(row.path)
    let path
    if (data.mode === 'mapped') path = data.mapped_path
    else { ElMessage.success('已打开文件夹'); return }
    const hasTM = window.kikoeruHelperLoaded || tampermonkeyLoaded.value
    window.dispatchEvent(new CustomEvent('kikoeru-open-folder', { detail: { path } }))
    hasTM ? ElMessage.success('正在打开文件夹...') : ElMessage.info('正在尝试打开文件夹...')
    if (!hasTM) setTimeout(() => { if (!window.kikoeruHelperLoaded) showTMDialog(path) }, 2000)
  } catch (e) { ElMessage.error(e.response?.data?.detail || '打开文件夹失败') }
}

async function showTMDialog (path) {
  ElMessage.warning('Tampermonkey 脚本未安装')
  try { await navigator.clipboard.writeText(path); ElMessage.success('路径已复制') } catch (_) {}
  ElMessageBox.confirm(`需要安装 Tampermonkey 脚本。<br><code>${path}</code><br>是否查看安装教程？`, '需要 Tampermonkey', { confirmButtonText: '查看教程', cancelButtonText: '手动打开', type: 'warning', dangerouslyUseHTMLString: true })
    .then(() => window.open('https://github.com/canforgive/KikoeruTool/blob/main/tampermonkey/kikoeru-folder-opener.js', '_blank'))
}

async function copyMappedPath () {
  try { await navigator.clipboard.writeText(mappedPathInfo.value.mappedPath); ElMessage.success('已复制') }
  catch { ElMessage.error('复制失败') }
}

function openWithBrowser () {
  const p = mappedPathInfo.value.mappedPath
  if (window.kikoeruHelperLoaded || tampermonkeyLoaded.value) { window.dispatchEvent(new CustomEvent('kikoeru-open-folder', { detail: { path: p } })); ElMessage.success('已发送打开请求'); return }
  let url = p.replace(/\\/g, '/'); url = /^[a-zA-Z]:/.test(url) ? `file:///${url}` : `file://${url}`
  try { if (window.open(url, '_blank')) { ElMessage.success('已尝试打开'); return } } catch (_) {}
  ElMessage.warning('浏览器阻止了打开操作')
}

function renameItem (row) { renameForm.value = { id: row.id, currentName: row.name, newName: row.name, path: row.path }; renameDialogVisible.value = true }

async function confirmRename () {
  if (!renameForm.value.newName || renameForm.value.newName === renameForm.value.currentName) { ElMessage.warning('请输入不同的新名称'); return }
  isRenaming.value = true
  try { await libraryApi.rename(renameForm.value.path, renameForm.value.newName); ElMessage.success('重命名成功'); renameDialogVisible.value = false; await refreshLibrary() }
  catch (e) { ElMessage.error('重命名失败: ' + (e.response?.data?.detail || e.message)) }
  finally { isRenaming.value = false }
}

async function apiRenameItem (row) {
  try { await ElMessageBox.confirm(`确定重新获取DLsite元数据并重命名吗？\n\n当前: ${row.name}`, 'API重命名确认', { confirmButtonText: '确定', cancelButtonText: '取消', type: 'info' }) } catch { return }
  apiRenamingId.value = row.id
  try { const data = await libraryApi.apiRename(row.path); ElMessage.success(data.message); if (data.new_name) ElMessage.info(`新名称: ${data.new_name}`); await refreshLibrary() }
  catch (e) { ElMessage.error('API重命名失败: ' + (e.response?.data?.detail || e.message)) }
  finally { apiRenamingId.value = null }
}

async function deleteItem (row) {
  try {
    const c = await libraryApi.delete(row.path, false)
    if (c.need_confirm) {
      await ElMessageBox.confirm(`确定删除此${c.type === 'folder' ? '文件夹' : '文件'}吗？\n名称: ${c.name}\n\n此操作不可恢复！`, '删除确认', { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' })
      await libraryApi.delete(row.path, true); ElMessage.success('删除成功'); await refreshLibrary()
    }
  } catch (e) { if (e === 'cancel' || e?.message === 'cancel') return; ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message)) }
}

async function openFolderContentsDialog (row) {
  if (!row?.is_directory) { ElMessage.warning('只有文件夹支持文件管理'); return }
  folderContentsDialogVisible.value = true
  folderContentsSearch.value = ''
  selectedFileIds.value = new Set()
  expandedIds.value = new Set()
  await loadFolderContents(row.path, row.name)
}

async function loadFolderContents (path, name = '') {
  folderContentsLoading.value = true
  try {
    const data = await libraryApi.folderContents(path)
    folderContentsInfo.value = { folderName: data.folder_name || name, folderPath: data.folder_path || path, totalFiles: data.total_files || 0 }
    folderContentsFiles.value = data.items || []
    selectedFileIds.value = new Set()
    // 默认展开第一层目录
    const s = new Set()
    for (const n of buildTree(folderContentsFiles.value)) { if (n.type === 'dir') s.add(n.id) }
    expandedIds.value = s
  } catch (e) {
    if (e.code === 'FOLDER_CONTENTS_UNSUPPORTED') ElMessage.error('后端版本过旧，请更新')
    else ElMessage.error('加载失败: ' + (e.response?.data?.detail || e.message))
    folderContentsDialogVisible.value = false
  } finally { folderContentsLoading.value = false }
}

async function openSubFile (row) {
  try {
    const data = await libraryApi.openFolder(row.path)
    if (data.mode === 'mapped') { mappedPathInfo.value = { originalPath: data.original_path, mappedPath: data.mapped_path, isMapped: data.is_mapped }; mappedPathDialogVisible.value = true; return }
    ElMessage.success('已打开文件位置')
  } catch (e) { ElMessage.error('打开失败: ' + (e.response?.data?.detail || e.message)) }
}

async function deleteSubFile (row) {
  try {
    const c = await libraryApi.delete(row.path, false)
    await ElMessageBox.confirm(`确定删除该文件吗？\n名称: ${c.name}\n大小: ${formatFileSize(c.size)}\n\n此操作不可恢复！`, '删除确认', { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' })
    await libraryApi.delete(row.path, true); ElMessage.success('删除成功')
    await loadFolderContents(folderContentsInfo.value.folderPath, folderContentsInfo.value.folderName)
    await refreshLibrary()
  } catch (e) { if (e === 'cancel' || e?.message === 'cancel') return; ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message)) }
}

async function deleteSubDir (row) {
  // row 是虚拟目录节点（来自 buildTree），需要从原始文件列表推算目录的路径
  // 约定：目录路径 = folderContentsInfo.folderPath + '/' + row.relative_path
  const dirPath = [folderContentsInfo.value.folderPath, row.relative_path].filter(Boolean).join('/')
  try {
    await ElMessageBox.confirm(
      `确定删除文件夹「${row.name}」及其所有内容吗？\n\n此操作不可恢复！`,
      '删除文件夹确认',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' }
    )
    await libraryApi.delete(dirPath, true)
    ElMessage.success('文件夹删除成功')
    await loadFolderContents(folderContentsInfo.value.folderPath, folderContentsInfo.value.folderName)
    await refreshLibrary()
  } catch (e) { if (e === 'cancel' || e?.message === 'cancel') return; ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message)) }
}

async function batchDeleteSubFiles () {
  if (!folderSelectedFiles.value.length) { ElMessage.warning('请先选择文件'); return }
  const paths = folderSelectedFiles.value.map(f => f.path)
  try {
    const prev = await libraryApi.batchDelete(paths, false)
    await ElMessageBox.confirm(`确定删除 ${prev.total_count || paths.length} 个文件？总大小: ${formatFileSize(prev.total_size || 0)}\n\n此操作不可恢复！`, '批量删除确认', { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' })
    const res = await libraryApi.batchDelete(paths, true); ElMessage.success(`批量删除完成：成功 ${res.success_count || 0} 个`)
    await loadFolderContents(folderContentsInfo.value.folderPath, folderContentsInfo.value.folderName)
    await refreshLibrary()
  } catch (e) { if (e === 'cancel' || e?.message === 'cancel') return; ElMessage.error('批量删除失败: ' + (e.response?.data?.detail || e.message)) }
}

async function handleBatchDelete () {}
async function handleBatchApiRename () {}
</script>

<style scoped>
/* ─── 原库列表样式 ──────────────────────────────────────────── */
.library { max-width: 1400px; margin: 0 auto; padding: 16px; }
.page-title { font-size: 24px; font-weight: 600; color: #303133; margin: 0 0 20px; }
.main-card { border-radius: 8px; border: 1px solid #e4e7ed; box-shadow: 0 2px 12px rgba(0,0,0,.02) !important; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.header-title { font-size: 16px; font-weight: 600; color: #303133; }
.header-actions { display: flex; align-items: center; gap: 12px; }
:deep(.el-table) { --el-table-header-bg-color: #f8f9fa; }
:deep(.el-table th.el-table__cell) { font-weight: 600; }
.file-icon { margin-right: 6px; color: #409eff; vertical-align: middle; }
.file-name { vertical-align: middle; font-weight: 500; color: #303133; }
.empty-text { color: #c0c4cc; }
.action-grid { display: flex; flex-direction: column; gap: 5px; }
.action-grid-row { display: flex; gap: 5px; }
.action-btn { flex: 1; margin: 0 !important; border-radius: 4px; font-weight: 500; transition: all .2s; }
.action-btn:hover { transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,.1); }
.batch-actions { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; background: #f8f9fa; border: 1px solid #ebeef5; border-radius: 6px; margin: 12px 0; }
.batch-left { display: flex; align-items: center; }
.batch-right { display: flex; align-items: center; gap: 10px; }
.selected-count { font-weight: 600; color: #409eff; font-size: 13px; background: #ecf5ff; padding: 3px 10px; border-radius: 10px; }
.pagination-container { margin-top: 20px; display: flex; justify-content: flex-end; }
.name-preview { padding: 8px 12px; background: #f8f9fa; border: 1px solid #e4e7ed; border-radius: 4px; font-family: monospace; font-size: 13px; color: #606266; word-break: break-all; }
.path-code { font-family: monospace; font-size: 13px; color: #303133; word-break: break-all; }
.mapped-path-container { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.mapped-path { flex: 1; min-width: 0; background: #f8f9fa; padding: 4px 8px; border-radius: 4px; border: 1px solid #ebeef5; }
.path-actions { display: flex; gap: 6px; }
.path-mapping-help { margin-top: 16px; padding: 14px 16px; background: #f8f9fa; border: 1px solid #ebeef5; border-radius: 6px; }
.path-mapping-help h4 { margin: 0 0 10px; color: #303133; font-size: 13px; }
.path-mapping-help ol { margin: 0; padding-left: 18px; color: #606266; line-height: 1.8; font-size: 13px; }
.help-tip { margin: 10px 0 0; color: #909399; font-size: 12px; }

/* ─── 文件管理对话框 ────────────────────────────────────────── */
:deep(.fm-dialog .el-dialog) { border-radius: 8px; overflow: hidden; box-shadow: 0 16px 48px rgba(0,0,0,.18); }
:deep(.fm-dialog .el-dialog__header) { padding: 0; margin: 0; border-bottom: none; }
:deep(.fm-dialog .el-dialog__body) { padding: 0; }
:deep(.fm-dialog .el-dialog__headerbtn) { top: 12px; right: 14px; z-index: 10; }
:deep(.fm-dialog .el-dialog__headerbtn .el-dialog__close) { color: #909399; }
:deep(.fm-dialog .el-dialog__headerbtn:hover .el-dialog__close) { color: #f56c6c; }

/* header — light theme */
.fm-header { display: flex; align-items: center; justify-content: space-between; padding: 11px 48px 11px 16px; background: #fff; border-bottom: 1px solid #e4e7ed; min-height: 44px; box-sizing: border-box; }
.fm-header-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.fm-header-name { font-size: 13px; font-weight: 600; color: #303133; font-family: 'JetBrains Mono', Consolas, monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 680px; }
.fm-header-right { flex-shrink: 0; }
.fm-header-count { font-size: 12px; color: #606266; background: #f0f7ff; border: 1px solid #c6e2ff; border-radius: 12px; padding: 2px 10px; }
.fm-header-count b { color: #409eff; }

/* body */
.fm-body { display: flex; flex-direction: column; height: 540px; background: #fff; }

/* toolbar */
.fm-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 8px 14px; background: #f8f9fa; border-bottom: 1px solid #e4e7ed; flex-shrink: 0; }
.fm-toolbar-left { display: flex; align-items: center; gap: 6px; }
.fm-btn { display: inline-flex; align-items: center; gap: 5px; padding: 4px 11px; font-size: 12px; font-weight: 500; border-radius: 5px; border: 1px solid transparent; cursor: pointer; transition: all .15s; white-space: nowrap; line-height: 1.5; }
.fm-btn--danger { color: #f56c6c; background: #fff0f0; border-color: #fbc4c4; }
.fm-btn--danger:not(.fm-btn--disabled):hover { background: #f56c6c; color: #fff; border-color: #f56c6c; }
.fm-btn--ghost { color: #606266; background: #fff; border-color: #dcdfe6; }
.fm-btn--ghost:hover { color: #409eff; border-color: #a0cfff; background: #ecf5ff; }
.fm-btn--disabled { opacity: .4; cursor: not-allowed; }
.fm-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 16px; height: 16px; padding: 0 4px; border-radius: 8px; background: #f56c6c; color: #fff; font-size: 10px; font-weight: 700; }

/* search */
.fm-search { position: relative; display: flex; align-items: center; }
.fm-search-ico { position: absolute; left: 9px; color: #adb5bd; pointer-events: none; }
.fm-search-input { width: 260px; height: 30px; padding: 0 28px; font-size: 12px; border: 1px solid #dcdfe6; border-radius: 5px; outline: none; color: #303133; background: #fff; transition: border-color .15s, box-shadow .15s; }
.fm-search-input::placeholder { color: #c0c4cc; }
.fm-search-input:focus { border-color: #409eff; box-shadow: 0 0 0 2px rgba(64,158,255,.12); }
.fm-search-clear { position: absolute; right: 8px; background: none; border: none; cursor: pointer; color: #c0c4cc; font-size: 13px; line-height: 1; padding: 0; }
.fm-search-clear:hover { color: #909399; }

/* thead */
.fm-thead { display: flex; align-items: center; height: 34px; padding: 0 14px; background: #f4f5f7; border-bottom: 1px solid #e4e7ed; flex-shrink: 0; user-select: none; }
.fm-th { font-size: 12px; font-weight: 600; color: #606266; display: flex; align-items: center; }

/* scroll */
.fm-scroll { flex: 1; overflow-y: auto; overflow-x: hidden; }
.fm-scroll::-webkit-scrollbar { width: 5px; }
.fm-scroll::-webkit-scrollbar-track { background: transparent; }
.fm-scroll::-webkit-scrollbar-thumb { background: #dcdfe6; border-radius: 3px; }
.fm-scroll::-webkit-scrollbar-thumb:hover { background: #bcc0cc; }

/* empty */
.fm-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; height: 180px; color: #c0c4cc; font-size: 13px; }

/* ─── 列宽（thead + row 共享） ───────────────────────────────── */
.fm-col-check  { width: 42px;  flex-shrink: 0; justify-content: center; }
.fm-col-name   { flex: 0 0 300px; min-width: 0; overflow: hidden; }
.fm-col-path   { flex: 1; min-width: 0; overflow: hidden; padding: 0 10px; }
.fm-col-size   { width: 88px;  flex-shrink: 0; justify-content: flex-end; padding-right: 14px; }
.fm-col-time   { width: 155px; flex-shrink: 0; }
.fm-col-action { width: 110px; flex-shrink: 0; justify-content: center; gap: 4px; }

/* row */
.fm-row { display: flex; align-items: center; padding: 0 14px; height: 32px; border-bottom: 1px solid #ebeef5; transition: background .1s; }
.fm-row--dir { background: #fafbfc; cursor: pointer; }
.fm-row--dir:hover { background: #ecf5ff; }
.fm-row--file:hover { background: #f5f7ff; }
.fm-row--selected { background: #ecf5ff !important; }
.fm-td { display: flex; align-items: center; overflow: hidden; }

/* name cell */
.fm-name-cell { position: relative; display: flex; align-items: center; gap: 3px; width: 100%; overflow: hidden; }
.fm-guide { position: absolute; top: 0; bottom: 0; width: 1px; background: #e8eaf0; }
.fm-arrow-wrap { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; flex-shrink: 0; border-radius: 3px; color: #909399; cursor: pointer; transition: color .12s, background .12s; }
.fm-arrow-wrap:hover { background: #dde4ff; color: #409eff; }
.fm-arrow-placeholder { display: inline-block; width: 16px; flex-shrink: 0; }
.fm-arrow { transition: transform .16s cubic-bezier(.25,.8,.25,1); color: #909399; }
.fm-arrow--open { transform: rotate(90deg); color: #409eff; }
.fm-icon { display: inline-flex; align-items: center; flex-shrink: 0; margin: 0 3px; }
.fm-name-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: #303133; font-family: 'JetBrains Mono', Consolas, monospace; }
.fm-name-text--dir { font-weight: 600; color: #1c1f2e; }
.fm-mono-sm { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: #909399; font-family: 'JetBrains Mono', Consolas, monospace; width: 100%; }
.fm-size-text { display: block; font-size: 12px; color: #606266; font-variant-numeric: tabular-nums; text-align: right; }
.fm-link { background: none; border: none; padding: 2px 5px; font-size: 12px; font-weight: 500; cursor: pointer; border-radius: 3px; transition: background .1s; white-space: nowrap; }
.fm-link--primary { color: #409eff; }
.fm-link--primary:hover { background: #ecf5ff; }
.fm-link--danger { color: #f56c6c; }
.fm-link--danger:hover { background: #fef0f0; }
.fm-check { width: 14px; height: 14px; cursor: pointer; accent-color: #409eff; }
</style>