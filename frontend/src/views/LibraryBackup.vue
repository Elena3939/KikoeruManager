<template>
  <div class="library-backup">
    <div class="page-header">
      <h1 class="page-title">库存打包</h1>
      <div class="header-actions">
        <el-button type="primary" :loading="saving" @click="saveBackupConfig">保存配置</el-button>
        <el-button :disabled="status.running || actionLoading" type="success" :loading="actionLoading" @click="startBackup">开始打包</el-button>
        <el-button :disabled="!status.running || actionLoading" type="danger" @click="cancelBackup">取消任务</el-button>
        <el-button @click="fetchBackupStatus">刷新状态</el-button>
      </div>
    </div>

    <el-card class="setting-card">
      <el-form :model="backupConfig" label-position="top">
        <el-form-item label="启用库存打包功能">
          <el-switch v-model="backupConfig.enabled" />
        </el-form-item>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="库存源路径">
              <el-input v-model="backupConfig.source_path" placeholder="留空时默认使用库存目录" :disabled="!backupConfig.enabled">
                <template #prefix>
                  <el-icon><Folder /></el-icon>
                </template>
              </el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="压缩包输出路径">
              <el-input v-model="backupConfig.output_dir" placeholder="留空时默认输出到库存目录" :disabled="!backupConfig.enabled">
                <template #prefix>
                  <el-icon><FolderOpened /></el-icon>
                </template>
              </el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="目录结构复制目标路径">
              <el-input v-model="backupConfig.path_copy_target" placeholder="不再创建日期子目录，直接复制到此目录" :disabled="!backupConfig.enabled">
                <template #prefix>
                  <el-icon><Folder /></el-icon>
                </template>
              </el-input>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="压缩密码">
              <el-input v-model="backupConfig.password" show-password placeholder="必填，压缩时启用加密" :disabled="!backupConfig.enabled">
                <template #prefix>
                  <el-icon><Key /></el-icon>
                </template>
              </el-input>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="压缩后缀格式">
              <el-select v-model="backupConfig.archive_format" style="width: 100%" :disabled="!backupConfig.enabled">
                <el-option label=".zip" value="zip" />
                <el-option label=".7z" value="7z" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="压缩强度">
              <el-slider v-model="backupConfig.compression_level" :min="1" :max="9" :step="1" show-input :disabled="!backupConfig.enabled" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="压缩线程数">
              <el-input-number v-model="backupConfig.compression_threads" :min="0" :max="64" style="width: 100%" :disabled="!backupConfig.enabled" />
              <div class="form-tip">0 表示自动线程数</div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="先复制目录结构">
          <el-switch v-model="backupConfig.copy_structure_before_zip" :disabled="!backupConfig.enabled" />
          <div class="form-tip">复制时直接把目录层级还原到目标目录，不创建 ASMR_日期_PATHS 子目录</div>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="status-card">
      <template #header>
        <div class="card-header">
          <span>任务状态</span>
          <el-tag :type="status.running ? 'warning' : status.state === 'completed' ? 'success' : status.state === 'failed' ? 'danger' : 'info'">
            {{ status.step || '待机' }}
          </el-tag>
        </div>
      </template>
      <el-progress :percentage="status.progress || 0" :status="status.state === 'failed' ? 'exception' : status.state === 'completed' ? 'success' : ''" :stroke-width="16" />
      <div class="status-meta" v-if="status.running && (status.speed || status.eta)">
        <el-tag size="small" type="info" v-if="status.speed" class="meta-tag">速度: {{ status.speed }}</el-tag>
        <el-tag size="small" type="info" v-if="status.eta" class="meta-tag">剩余时间: {{ status.eta }}</el-tag>
      </div>
      <div class="meta-row" v-if="status.output_zip_path">输出文件：{{ status.output_zip_path }}</div>
      <div class="meta-row" v-if="status.path_snapshot_dir">目录结构复制目标：{{ status.path_snapshot_dir }}</div>
      <div class="meta-row error-row" v-if="status.error">错误：{{ status.error }}</div>
      <el-scrollbar height="220px" class="log-box">
        <div v-for="(line, idx) in status.logs || []" :key="`backup-log-${idx}`" class="log-line">
          {{ line }}
        </div>
      </el-scrollbar>
    </el-card>

    <el-card class="history-card">
      <template #header>
        <div class="card-header">
          <span>历史记录</span>
          <el-button size="small" @click="fetchBackupHistory">刷新历史</el-button>
        </div>
      </template>
      <el-table :data="backupHistory" stripe style="width: 100%" height="400px">
        <el-table-column prop="filename" label="文件名" min-width="200" />
        <el-table-column label="大小变化" width="180">
          <template #default="{ row }">
            {{ formatSize(row.pre_size_bytes) }} -> {{ formatSize(row.post_size_bytes) }}
          </template>
        </el-table-column>
        <el-table-column label="压缩率" width="100">
          <template #default="{ row }">
            {{ (row.compression_ratio * 100).toFixed(2) }}%
          </template>
        </el-table-column>
        <el-table-column prop="speed_avg" label="平均速度" width="120" />
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">
            {{ formatDuration(row.duration_seconds) }}
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="备份日期" width="160">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Folder, FolderOpened, Key } from '@element-plus/icons-vue'
import { configApi, backupApi } from '../api'

const saving = ref(false)
const actionLoading = ref(false)
const status = ref({
  state: 'idle',
  running: false,
  progress: 0,
  step: '待机',
  error: null,
  output_zip_path: '',
  path_snapshot_dir: '',
  logs: []
})
const backupConfig = ref({
  enabled: false,
  source_path: '',
  output_dir: '',
  path_copy_target: '',
  copy_structure_before_zip: true,
  password: '',
  archive_format: 'zip',
  compression_level: 9,
  compression_threads: 0
})
const backupHistory = ref([])

let timer = null

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function startPolling() {
  stopPolling()
  timer = setInterval(() => {
    fetchBackupStatus(false)
  }, 2000)
}

async function loadConfig() {
  const data = await configApi.get()
  backupConfig.value = {
    ...backupConfig.value,
    ...(data?.backup_zip || {})
  }
}

async function fetchBackupHistory() {
  try {
    const data = await backupApi.history()
    backupHistory.value = data || []
  } catch (error) {
    console.error('获取备份历史失败:', error)
  }
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

function formatDuration(seconds) {
  if (!seconds) return '0s'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString()
}

async function saveBackupConfig(showSuccess = true) {
  try {
    saving.value = true
    await configApi.save({
      backup_zip: {
        enabled: backupConfig.value.enabled ?? false,
        source_path: backupConfig.value.source_path || '',
        output_dir: backupConfig.value.output_dir || '',
        path_copy_target: backupConfig.value.path_copy_target || '',
        copy_structure_before_zip: backupConfig.value.copy_structure_before_zip ?? true,
        password: backupConfig.value.password || '',
        archive_format: backupConfig.value.archive_format || 'zip',
        compression_level: backupConfig.value.compression_level ?? 9,
        compression_threads: backupConfig.value.compression_threads ?? 0
      }
    })
    if (showSuccess) {
      ElMessage.success('库存打包配置已保存')
    }
  } catch (error) {
    ElMessage.error('保存库存打包配置失败：' + (error.response?.data?.detail || error.message))
    throw error
  } finally {
    saving.value = false
  }
}

async function fetchBackupStatus(showError = true) {
  try {
    const result = await backupApi.status()
    status.value = {
      ...status.value,
      ...(result || {})
    }
    if (status.value.running) {
      startPolling()
    } else {
      stopPolling()
      // 如果任务刚刚结束（从 running 变为 false），刷新历史记录
      fetchBackupHistory()
    }
  } catch (error) {
    if (showError) {
      ElMessage.error('获取库存打包状态失败：' + (error.response?.data?.detail || error.message))
    }
  }
}

async function startBackup() {
  if (!backupConfig.value.enabled) {
    ElMessage.warning('请先启用库存打包功能')
    return
  }
  if (!backupConfig.value.password?.trim()) {
    ElMessage.warning('请先填写压缩密码')
    return
  }
  try {
    actionLoading.value = true
    await saveBackupConfig(false)
    const result = await backupApi.start()
    status.value = { ...status.value, ...(result || {}) }
    startPolling()
    ElMessage.success('库存打包任务已启动')
  } catch (error) {
    ElMessage.error('启动库存打包失败：' + (error.response?.data?.detail || error.message))
  } finally {
    actionLoading.value = false
  }
}

async function cancelBackup() {
  try {
    actionLoading.value = true
    const result = await backupApi.cancel()
    status.value = { ...status.value, ...(result || {}) }
    stopPolling()
    ElMessage.success('库存打包任务已取消')
  } catch (error) {
    ElMessage.error('取消库存打包失败：' + (error.response?.data?.detail || error.message))
  } finally {
    actionLoading.value = false
  }
}

onMounted(async () => {
  await loadConfig()
  await fetchBackupStatus(false)
  await fetchBackupHistory()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.library-backup {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 28px;
  font-weight: 600;
  color: #1e293b;
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.setting-card,
.status-card {
  margin-bottom: 16px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.status-meta {
  margin-top: 12px;
  display: flex;
  gap: 12px;
  align-items: center;
}

.meta-tag {
  font-family: monospace;
}

.meta-row {
  margin-top: 8px;
  font-size: 12px;
  color: #606266;
  word-break: break-all;
}

.error-row {
  color: #f56c6c;
}

.log-box {
  margin-top: 10px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  background: #fafafa;
  padding: 8px;
}

.log-line {
  font-size: 12px;
  line-height: 1.6;
  color: #303133;
  word-break: break-all;
}
</style>
