<template>
  <div class="password-vault">
    <h1 class="page-title">密码库</h1>
    
    <el-card class="main-card">
      <div class="stats-bar" v-if="cleanupStatus">
        <el-alert
          :title="cleanupStatus.enabled ? '智能清理已启用' : '智能清理已禁用'"
          :type="cleanupStatus.enabled ? 'success' : 'info'"
          :closable="false"
          show-icon
        >
          <template #default>
            <span v-if="cleanupStatus.enabled">
              下次清理时间: {{ formatNextCleanupTime(cleanupStatus.next_cleanup_time) }} |
              清理规则: 使用次数 ≤ {{ cleanupStatus.max_use_count }}, 保留 {{ cleanupStatus.preserve_days }} 天
            </span>
            <span v-else>
              前往设置页面启用密码库智能清理功能
            </span>
          </template>
        </el-alert>
      </div>

      <div class="toolbar">
        <el-button type="primary" @click="showAddDialog = true">
          <el-icon><Plus /></el-icon>
          添加密码
        </el-button>
        <el-button @click="showImportDialog = true">
          <el-icon><Document /></el-icon>
          批量导入
        </el-button>
        <el-button type="danger" plain @click="handleBatchDelete" :disabled="selectedRows.length === 0">
          <el-icon><Delete /></el-icon>
          批量删除
        </el-button>
        <el-button @click="showCleanupDialog = true">
          <el-icon><Timer /></el-icon>
          智能清理
        </el-button>

        <el-select v-model="passwordSortBy" style="width: 140px; margin-left: 12px;" @change="handlePasswordSortChange">
          <el-option label="添加时间" value="created_at" />
          <el-option label="更新时间" value="updated_at" />
          <el-option label="RJ号" value="rjcode" />
          <el-option label="文件名" value="filename" />
          <el-option label="使用次数" value="use_count" />
        </el-select>

        <el-button
          link
          @click="togglePasswordSortOrder"
          :title="passwordSortOrder === 'desc' ? '降序' : '升序'"
        >
          <el-icon>
            <SortDown v-if="passwordSortOrder === 'desc'" />
            <SortUp v-else />
          </el-icon>
        </el-button>

        <el-input
          v-model="searchQuery"
          placeholder="搜索RJ号、文件名或密码"
          style="width: 280px; margin-left: auto;"
          clearable
          @input="handleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>

      <el-table
        ref="passwordTableRef"
        :data="tablePasswords"
        style="width: 100%"
        row-key="id"
        v-loading="loading"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column prop="rjcode" label="RJ号" width="120" sortable align="center" header-align="center">
          <template #default="{ row }">
            <div class="table-cell-content table-cell-content-center">
              <el-tag v-if="row.rjcode" type="info" size="small">{{ row.rjcode }}</el-tag>
              <span v-else class="text-gray placeholder-text">-</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="filename" label="文件名" min-width="200" align="center" header-align="center">
          <template #default="{ row }">
            <div class="table-cell-content table-cell-content-center">
              <span v-if="row.filename">{{ row.filename }}</span>
              <span v-else class="text-gray placeholder-text">-</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="password" label="密码" width="200" align="center" header-align="center">
          <template #default="{ row }">
            <div class="password-cell table-cell-content-center">
              <span class="password-text">{{ row.password }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="备注" min-width="150" align="center" header-align="center">
          <template #default="{ row }">
            <div class="table-cell-content table-cell-content-center">
              <span v-if="row.description">{{ row.description }}</span>
              <span v-else class="text-gray placeholder-text">-</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="use_count" label="使用次数" width="120" sortable label-class-name="usage-count-header" align="center" header-align="center">
          <template #default="{ row }">
            <div class="table-cell-content table-cell-content-center">
              <el-tag :type="row.use_count > 0 ? 'success' : 'info'" size="small">
                {{ row.use_count }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="last_used_at" label="最后使用" width="150" align="center" header-align="center">
          <template #default="{ row }">
            <div class="table-cell-content table-cell-content-center">
              <span v-if="row._formatted_last_used">{{ row._formatted_last_used }}</span>
              <span v-else class="text-gray">未使用</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" align="center" header-align="center">
          <template #default="{ row }">
            <div class="table-cell-content table-cell-content-center">
              {{ row._formatted_created_at }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button link type="primary" size="small" @click="handleEdit(row)">
                编辑
              </el-button>
              <el-button link type="danger" size="small" @click="handleDelete(row)">
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top: 16px; display: flex; justify-content: flex-end;">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="totalCount"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handlePageSizeChange"
          @current-change="handlePageChange"
        />
      </div>

      <el-empty v-if="!loading && tablePasswords.length === 0" description="暂无密码记录">
        <el-button type="primary" @click="showAddDialog = true">添加第一个密码</el-button>
      </el-empty>
    </el-card>

    <el-dialog
      v-model="showAddDialog"
      :title="isEditing ? '编辑密码' : '添加密码'"
      width="500px"
    >
      <el-form :model="form" label-width="100px" :rules="rules" ref="formRef">
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" placeholder="输入解压密码" show-password />
          <div class="form-tip">必填：解压密码</div>
        </el-form-item>
        <el-form-item label="RJ号">
          <el-input v-model="form.rjcode" placeholder="例如: RJ123456（可选）" />
          <div class="form-tip">可选：如果密码与特定作品关联，请填写RJ号</div>
        </el-form-item>
        <el-form-item label="文件名">
          <el-input v-model="form.filename" placeholder="例如: RJ123456.zip（可选）" />
          <div class="form-tip">可选：如果密码与特定文件关联，请填写文件名</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选：添加描述信息，如" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          {{ isEditing ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showCleanupDialog"
      title="密码库智能清理"
      width="800px"
    >
      <div v-loading="cleanupLoading">
        <el-row :gutter="20" style="margin-bottom: 20px;">
          <el-col :span="8">
            <el-card shadow="hover">
              <template #header>
                <span>清理状态</span>
              </template>
              <div style="text-align: center;">
                <el-tag :type="cleanupStatus?.enabled ? 'success' : 'info'" size="large">
                  {{ cleanupStatus?.enabled ? '已启用' : '已禁用' }}
                </el-tag>
                <div style="margin-top: 10px; font-size: 12px; color: #909399;">
                  {{ cleanupStatus?.is_running ? '服务运行中' : '服务未运行' }}
                </div>
              </div>
            </el-card>
          </el-col>
          <el-col :span="8">
            <el-card shadow="hover">
              <template #header>
                <span>下次清理</span>
              </template>
              <div style="text-align: center;">
                <div style="font-size: 18px; font-weight: 600; color: #409eff;">
                  {{ formatNextCleanupTime(cleanupStatus?.next_cleanup_time) }}
                </div>
                <div style="margin-top: 10px; font-size: 12px; color: #909399;">
                  Cron: {{ cleanupStatus?.cron_expression }}
                </div>
              </div>
            </el-card>
          </el-col>
          <el-col :span="8">
            <el-card shadow="hover">
              <template #header>
                <span>清理规则</span>
              </template>
              <div style="text-align: center; font-size: 14px;">
                <div>使用次数 ≤ {{ cleanupStatus?.max_use_count }}</div>
                <div style="margin-top: 5px; color: #909399;">
                  保留 {{ cleanupStatus?.preserve_days }} 天
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>

        <div style="margin-bottom: 20px; display: flex; gap: 10px;">
          <el-button type="primary" @click="previewCleanup" :disabled="!cleanupStatus?.enabled">
            <el-icon><View /></el-icon>
            预览清理
          </el-button>
          <el-button type="danger" @click="runCleanup" :disabled="!cleanupStatus?.enabled">
            <el-icon><Delete /></el-icon>
            立即清理
          </el-button>
          <el-button @click="loadCleanupHistory">
            <el-icon><Refresh /></el-icon>
            刷新历史
          </el-button>
          <el-button style="margin-left: auto;" @click="$router.push('/settings')">
            <el-icon><Setting /></el-icon>
            前往设置
          </el-button>
        </div>

        <el-divider>清理历史</el-divider>
        <el-table :data="cleanupHistory" style="width: 100%" max-height="300" row-key="id">
          <el-table-column prop="created_at" label="清理时间" width="180">
            <template #default="{ row }">
              {{ row._formatted_created_at }}
            </template>
          </el-table-column>
          <el-table-column prop="deleted_count" label="删除数量" width="100">
            <template #default="{ row }">
              <el-tag type="danger">{{ row.deleted_count }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="config_snapshot" label="配置快照">
            <template #default="{ row }">
              <div style="font-size: 12px; color: #606266;">
                使用次数≤{{ row.config_snapshot?.max_use_count }},
                保留{{ row.config_snapshot?.preserve_days }}天
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="deleted_passwords_summary" label="删除详情" min-width="200">
            <template #default="{ row }">
              <div v-if="row.deleted_passwords_summary && row.deleted_passwords_summary.length > 0"
                   style="font-size: 12px;">
                <div v-for="(pwd, idx) in row.deleted_passwords_summary.slice(0, 3)" :key="idx">
                  {{ pwd.rjcode || pwd.filename || '通用密码' }} ({{ pwd.use_count }}次)
                </div>
                <div v-if="row.deleted_passwords_summary.length > 3" style="color: #909399;">
                  等 {{ row.deleted_passwords_summary.length }} 个密码...
                </div>
              </div>
              <span v-else style="color: #909399;">-</span>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="cleanupHistory.length === 0" description="暂无清理记录" />
      </div>
    </el-dialog>

    <el-dialog
      v-model="showImportDialog"
      title="批量导入密码"
      width="600px"
    >
      <el-alert
        title="导入格式说明"
        type="info"
        :closable="false"
        style="margin-bottom: 20px;"
      >
        <div style="font-size: 12px; line-height: 1.8;">
          <p>每行一个密码，系统会尝试解压时使用这些密码</p>
          <p>系统会自动匹配RJ号，无需在导入时指定</p>
        </div>
      </el-alert>

      <el-input
        v-model="importText"
        type="textarea"
        :rows="10"
        placeholder="在此粘贴密码列表（每行一个）...&#10;例如：&#10;password123&#10;password456&#10;password789"
      />

      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button type="primary" @click="handleImport" :loading="importing">
          导入 {{ importText.trim() ? importText.trim().split('\n').filter(l => l.trim()).length : 0 }} 个密码
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
// 【优化】：引入 shallowRef。这是提升巨量数据表格性能的关键。
import { ref, shallowRef, computed, onMounted, watch, nextTick } from 'vue'
import { Plus, Delete, Document, Search, View, Hide, Timer, Refresh, Setting, SortDown, SortUp } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { passwordApi, cleanupApi } from '../api'

const PAGE_SIZES = [10, 20, 50, 100]
const PAGE_SIZE_STORAGE_KEY = 'kikoeru.ui.passwordVault.pageSize'

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
// 【优化】：对于单纯展示不发生深度变更的大数组，使用 shallowRef，跳过 Vue 递归劫持所有对象深层级属性的操作，极大减少页面卡顿
const passwords = shallowRef([])
const passwordTableRef = ref(null)
const selectedRows = ref([])
const searchQuery = ref('')
const passwordSortBy = ref('created_at')
const passwordSortOrder = ref('desc')
const currentPage = ref(1)
const pageSize = ref(loadPersistedPageSize(50))
const totalCount = ref(0)
const isServerPaginated = ref(false)
const showAddDialog = ref(false)
const showImportDialog = ref(false)
const showCleanupDialog = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const importing = ref(false)
const cleanupLoading = ref(false)
const showPassword = ref({})
const importText = ref('')
const formRef = ref(null)
const cleanupStatus = ref(null)

// 【优化】：同样针对表格数据使用 shallowRef
const cleanupHistory = shallowRef([])

const form = ref({
  id: null,
  rjcode: '',
  filename: '',
  password: '',
  description: ''
})

const rules = {
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 1, max: 255, message: '密码长度应在1-255个字符之间', trigger: 'blur' }
  ]
}

const tablePasswords = computed(() => {
  if (isServerPaginated.value) {
    return passwords.value
  }
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return passwords.value.slice(start, end)
})

onMounted(() => {
  loadPasswords()
  loadCleanupStatus()
})

watch(pageSize, (size) => {
  persistPageSize(size)
})

async function loadPasswords() {
  loading.value = true
  try {
    const params = {
      sort_by: passwordSortBy.value,
      sort_order: passwordSortOrder.value,
      page: currentPage.value,
      page_size: pageSize.value
    }
    if (searchQuery.value) {
      params.search = searchQuery.value
    }
    const response = await passwordApi.list(params)
    const rawData = Array.isArray(response) ? response : response.items || []
    isServerPaginated.value = !Array.isArray(response)
    totalCount.value = Array.isArray(response) ? rawData.length : (response.total || 0)

    // 【优化】：数据预处理，直接把 format 后计算的字符串绑定在对象上。
    // 去除 template 中极其耗费 CPU 的遍历日期格式化计算。
    passwords.value = rawData.map(item => ({
      ...item,
      _formatted_last_used: item.last_used_at ? formatDate(item.last_used_at) : null,
      _formatted_created_at: formatDate(item.created_at)
    }))
    selectedRows.value = []
    await nextTick()
    passwordTableRef.value?.clearSelection?.()
    const maxPage = Math.max(1, Math.ceil(totalCount.value / pageSize.value))
    if (currentPage.value > maxPage) {
      currentPage.value = maxPage
      await loadPasswords()
    }
  } catch (error) {
    console.error('加载密码列表失败:', error)
    ElMessage.error('加载密码列表失败')
  } finally {
    loading.value = false
  }
}

function handlePasswordSortChange() {
  currentPage.value = 1
  loadPasswords()
}

function togglePasswordSortOrder() {
  passwordSortOrder.value = passwordSortOrder.value === 'desc' ? 'asc' : 'desc'
  currentPage.value = 1
  loadPasswords()
}

// 【优化】：为搜索框增加防抖变量，避免用户连贯打字时发出密集的高频请求和密集重绘
let searchTimeout = null
function handleSearch() {
  if (searchTimeout) {
    clearTimeout(searchTimeout)
  }
  searchTimeout = setTimeout(() => {
    currentPage.value = 1
    loadPasswords()
  }, 300)
}

function handleSelectionChange(selection) {
  selectedRows.value = selection
}

function togglePassword(id) {
  showPassword.value[id] = !showPassword.value[id]
}

function handleEdit(row) {
  isEditing.value = true
  form.value = {
    id: row.id,
    rjcode: row.rjcode || '',
    filename: row.filename || '',
    password: row.password,
    description: row.description || ''
  }
  showAddDialog.value = true
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (isEditing.value) {
      await passwordApi.update(form.value.id, {
        rjcode: form.value.rjcode || null,
        filename: form.value.filename || null,
        password: form.value.password,
        description: form.value.description || null
      })
      ElMessage.success('密码已更新')
    } else {
      await passwordApi.create({
        rjcode: form.value.rjcode || null,
        filename: form.value.filename || null,
        password: form.value.password,
        description: form.value.description || null,
        source: 'manual'
      })
      ElMessage.success('密码已添加')
    }
    showAddDialog.value = false
    resetForm()
    loadPasswords()
  } catch (error) {
    console.error('保存密码失败:', error)
    ElMessage.error('保存失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定要删除这个密码吗？${row.rjcode ? `（RJ号: ${row.rjcode}）` : ''}`,
      '确认删除',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    await passwordApi.delete(row.id)
    ElMessage.success('密码已删除')
    loadPasswords()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除密码失败:', error)
      ElMessage.error('删除失败')
    }
  }
}

async function handleBatchDelete() {
  const rowsToDelete = [...selectedRows.value]
  if (rowsToDelete.length === 0) {
    ElMessage.warning('请先选择要删除的密码')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${rowsToDelete.length} 个密码吗？`,
      '确认批量删除',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    let successCount = 0
    for (const row of rowsToDelete) {
      try {
        await passwordApi.delete(row.id)
        successCount += 1
      } catch (error) {
        if (error?.response?.status !== 404) {
          throw error
        }
      }
    }

    ElMessage.success(`已删除 ${successCount} 个密码`)
    selectedRows.value = []
    await nextTick()
    passwordTableRef.value?.clearSelection?.()
    await loadPasswords()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('批量删除失败:', error)
      ElMessage.error('删除失败')
    }
  }
}

async function handleImport() {
  const trimmedText = importText.value.trim()
  if (!trimmedText) {
    ElMessage.warning('请输入要导入的密码')
    return
  }

  const passwordsCount = trimmedText.split('\n').filter(line => line.trim()).length
  if (passwordsCount === 0) {
    ElMessage.warning('请输入有效的密码')
    return
  }

  importing.value = true
  try {
    const { message, imported, skipped } = await passwordApi.importFromText(trimmedText)
    if (skipped > 0) {
      ElMessage.success(`${message}`)
    } else {
      ElMessage.success(`成功导入 ${imported} 个密码`)
    }

    showImportDialog.value = false
    importText.value = ''
    loadPasswords()
  } catch (error) {
    console.error('导入失败:', error)
    ElMessage.error('导入失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    importing.value = false
  }
}

function resetForm() {
  form.value = {
    id: null,
    rjcode: '',
    filename: '',
    password: '',
    description: ''
  }
  isEditing.value = false
  formRef.value?.resetFields()
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  // 处理不同的日期格式
  let date
  if (typeof dateStr === 'string') {
    if (dateStr.includes('T')) {
      // 如果是ISO 8601格式，它是UTC时间，添加'Z'以正确解析为本地时间
      date = new Date(dateStr + 'Z')
    } else {
      date = new Date(dateStr)
    }
  } else {
    date = new Date(dateStr)
  }
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

async function loadCleanupStatus() {
  try {
    cleanupStatus.value = await cleanupApi.password.status()
  } catch (error) {
    console.error('加载清理状态失败:', error)
  }
}

async function loadCleanupHistory() {
  cleanupLoading.value = true
  try {
    const data = await cleanupApi.password.history(50)
    // 【优化】：预先处理好历史表的时间
    cleanupHistory.value = (data.history || []).map(row => ({
      ...row,
      _formatted_created_at: formatDate(row.created_at)
    }))
  } catch (error) {
    console.error('加载清理历史失败:', error)
    ElMessage.error('加载清理历史失败')
  } finally {
    cleanupLoading.value = false
  }
}

async function previewCleanup() {
  cleanupLoading.value = true
  try {
    const data = await cleanupApi.password.preview()

    if (data.deleted_count === 0) {
      ElMessage.info('没有需要清理的密码')
      return
    }

    const passwordList = data.deleted_passwords.map(p =>
      `• ${p.rjcode || p.filename || '通用密码'} (${p.use_count}次使用, ${p.source})`
    ).join('\n')

    await ElMessageBox.confirm(
      `将清理 ${data.deleted_count} 个密码：\n\n${passwordList}\n\n确定要立即清理吗？`,
      '清理预览',
      {
        confirmButtonText: '立即清理',
        cancelButtonText: '取消',
        type: 'warning',
        dangerouslyUseHTMLString: false
      }
    )

    await runCleanup()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('预览清理失败:', error)
      ElMessage.error('预览清理失败: ' + (error.response?.data?.detail || error.message))
    }
  } finally {
    cleanupLoading.value = false
  }
}

async function runCleanup() {
  cleanupLoading.value = true
  try {
    const data = await cleanupApi.password.run()

    if (data.deleted_count === 0) {
      ElMessage.info('没有需要清理的密码')
    } else {
      ElMessage.success(`成功清理 ${data.deleted_count} 个密码`)
      loadPasswords()
      loadCleanupHistory()
    }
  } catch (error) {
    console.error('执行清理失败:', error)
    ElMessage.error('执行清理失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    cleanupLoading.value = false
  }
}

function formatNextCleanupTime(timeStr) {
  if (!timeStr) return '未设置'
  const date = new Date(timeStr)
  const now = new Date()
  const diff = date - now

  if (diff < 0) return '即将执行'

  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
  const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))

  if (days > 0) return `${days}天${hours}小时后`
  if (hours > 0) return `${hours}小时${minutes}分钟后`
  return `${minutes}分钟后`
}

function handlePageChange(page) {
  currentPage.value = page
  if (isServerPaginated.value) {
    loadPasswords()
  }
}

function handlePageSizeChange(size) {
  pageSize.value = size
  currentPage.value = 1
  if (isServerPaginated.value) {
    loadPasswords()
  }
}

// 监听对话框打开事件
watch(showCleanupDialog, (newVal) => {
  if (newVal) {
    loadCleanupStatus()
    loadCleanupHistory()
  }
})
</script>

<style scoped>
.password-vault {
  max-width: 1400px;
  margin: 0 auto;
}

.page-title {
  font-size: 28px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 24px;
}

.main-card {
  min-height: 600px;
}
.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
  gap: 12px;
}

.password-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
}

.table-cell-content {
  display: flex;
  align-items: center;
  min-height: 24px;
}

.table-cell-content-center {
  justify-content: center;
}

.table-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  min-height: 24px;
  width: 100%;
}

.placeholder-text {
  letter-spacing: 0.04em;
}

.text-gray {
  color: #909399;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

:deep(.el-table) {
  margin-top: 10px;
}



.stats-bar {
  margin-bottom: 16px;
}

:deep(.usage-count-header .cell) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
}
</style>

