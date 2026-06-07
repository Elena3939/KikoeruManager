<template>
  <div class="backup-page max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
    <AppPageHeader
      :icon="Archive"
      icon-color="var(--km-nav-backup-icon)"
      title="库存打包"
      subtitle="将当前库存完整打包为压缩文件，支持目录结构快照和自动加密。"
    >
      <button
        class="page-head-btn ghost btn-save"
        type="button"
        :disabled="saving"
        @click="saveBackupConfig"
      >
        <Loader2 v-if="saving" :size="13" :stroke-width="2.4" class="animate-spin" />
        <Save v-else :size="13" :stroke-width="2.4" class="page-head-btn-icon" />
        <span class="page-head-btn-label">{{ saving ? '保存中…' : '保存配置' }}</span>
      </button>

      <button
        class="page-head-btn primary is-primary btn-pack"
        type="button"
        :disabled="status.running || actionLoading"
        @click="startBackup"
      >
        <Loader2 v-if="actionLoading && !status.running" :size="13" :stroke-width="2.6" class="animate-spin" />
        <Play v-else :size="13" :stroke-width="2.6" class="page-head-btn-icon" />
        <span class="page-head-btn-label">{{ actionLoading && !status.running ? '启动中…' : '开始打包' }}</span>
      </button>

      <button
        class="page-head-btn ghost is-blue btn-baidu-upload"
        type="button"
        :disabled="status.running || actionLoading || !backupConfig.baidu_upload_enabled"
        @click="startBackupAndUpload"
      >
        <Loader2 v-if="actionLoading && !status.running" :size="13" :stroke-width="2.4" class="animate-spin" />
        <CloudUpload v-else :size="13" :stroke-width="2.4" class="page-head-btn-icon" />
        <span class="page-head-btn-label">打包并上传</span>
      </button>

      <button
        class="page-head-btn ghost is-amber btn-resume"
        type="button"
        :disabled="!status.has_checkpoint || status.running || actionLoading"
        @click="resumeBackup"
      >
        <Loader2 v-if="actionLoading && !status.running" :size="13" :stroke-width="2.4" class="animate-spin" />
        <RotateCcw v-else :size="13" :stroke-width="2.4" class="page-head-btn-icon" />
        <span class="page-head-btn-label">恢复任务</span>
      </button>

      <button
        class="page-head-btn ghost is-danger btn-cancel"
        type="button"
        :disabled="!status.running || actionLoading"
        @click="cancelBackup"
      >
        <XCircle :size="13" :stroke-width="2.4" class="page-head-btn-icon" />
        <span class="page-head-btn-label">取消任务</span>
      </button>

      <button
        class="page-head-btn ghost btn-refresh icon-only"
        type="button"
        title="刷新状态"
        @click="fetchBackupStatus"
      >
        <RefreshCw :size="13" :stroke-width="2.6" class="page-head-btn-icon" />
      </button>
    </AppPageHeader>

    <!-- Main Layout: 上下流式 -->
    <div class="flex flex-col gap-6">
      
      <!-- Config Card -->
      <section class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden transition-all duration-300">
        <div class="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h2 class="text-base font-semibold text-slate-900">打包配置</h2>
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-slate-600">启用功能</span>
            <el-switch v-model="backupConfig.enabled" />
          </div>
        </div>
        <div class="p-6 transition-opacity duration-300" :class="{ 'opacity-50 pointer-events-none grayscale-[0.5]': !backupConfig.enabled }">
          <el-form :model="backupConfig" label-position="top" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-2">
            <el-form-item label="库存源路径">
              <div class="flex items-center gap-2 w-full">
                <Folder class="w-[18px] h-[18px] text-slate-500 shrink-0" />
                <el-input v-model="backupConfig.source_path" placeholder="留空时默认使用库存目录" />
              </div>
            </el-form-item>
            
            <el-form-item label="压缩包输出路径">
              <div class="flex items-center gap-2 w-full">
                <FolderOpen class="w-[18px] h-[18px] text-slate-500 shrink-0" />
                <el-input v-model="backupConfig.output_dir" placeholder="留空时默认输出到库存目录" />
              </div>
            </el-form-item>

            <el-form-item label="目录结构复制目标路径">
              <div class="flex items-center gap-2 w-full">
                <Folder class="w-[18px] h-[18px] text-slate-500 shrink-0" />
                <el-input v-model="backupConfig.path_copy_target" placeholder="不再创建日期子目录，直接复制到此目录" />
              </div>
            </el-form-item>
            
            <el-form-item label="压缩密码">
              <div class="flex items-center gap-2 w-full">
                <KeyRound class="w-[18px] h-[18px] text-slate-500 shrink-0" />
                <AnimatedPasswordInput v-model="backupConfig.password" placeholder="必填，压缩时启用加密" autocomplete="new-password" />
              </div>
            </el-form-item>

            <el-form-item label="压缩后缀格式">
              <AppDropdown
                v-model="backupConfig.archive_format"
                :options="archiveFormatOptions"
                class="backup-format-dd"
              />
            </el-form-item>
            
            <el-form-item label="压缩强度">
              <el-slider v-model="backupConfig.compression_level" :min="1" :max="9" :step="1" show-input />
            </el-form-item>
            
            <el-form-item label="压缩线程数">
              <div class="w-full">
                <el-input-number v-model="backupConfig.compression_threads" :min="0" :max="64" class="w-full" />
                <div class="text-[13px] text-slate-500 mt-1.5 leading-tight">0 表示自动线程数</div>
              </div>
            </el-form-item>
            
            <el-form-item label="先复制目录结构">
              <div class="w-full flex flex-col items-start gap-1">
                <el-switch v-model="backupConfig.copy_structure_before_zip" />
                <div class="text-[13px] text-slate-500 mt-1 leading-tight">复制时直接把目录层级还原到目标目录</div>
              </div>
            </el-form-item>
          </el-form>

          <div class="backup-upload-section">
            <div class="backup-upload-section-head">
              <div>
                <h3 class="backup-upload-section-title">百度网盘上传</h3>
                <p class="backup-upload-section-desc">打包完成后创建任务中心里的百度网盘上传任务</p>
              </div>
              <el-switch v-model="backupConfig.baidu_upload_enabled" />
            </div>
            <el-form :model="backupConfig" label-position="top" class="backup-upload-section-form" :class="{ 'opacity-50 pointer-events-none grayscale-[0.5]': !backupConfig.baidu_upload_enabled }">
              <el-form-item label="远端目录">
                <el-input v-model="backupConfig.baidu_upload_remote_dir" placeholder="/KikoeruManager" />
              </el-form-item>
              <el-form-item label="创建子目录">
                <el-input v-model="backupConfig.baidu_upload_create_subdir" placeholder="可选，例如 2026-06" />
              </el-form-item>
              <el-form-item label="同名策略">
                <AppDropdown
                  v-model="backupConfig.baidu_upload_conflict_policy"
                  :options="baiduUploadPolicyOptions"
                  class="backup-format-dd"
                />
              </el-form-item>
              <el-form-item label="上传后清理本地压缩包">
                <div class="w-full flex items-center h-10">
                  <el-switch v-model="backupConfig.baidu_upload_cleanup_local_archive" />
                </div>
              </el-form-item>
            </el-form>
          </div>
        </div>
      </section>

      <!-- Status Card -->
      <section class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div class="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h2 class="text-base font-semibold text-slate-900">任务状态</h2>
          <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border" :class="{
            'bg-amber-50 text-amber-700 border-amber-200': status.running,
            'bg-emerald-50 text-emerald-700 border-emerald-200': status.state === 'completed',
            'bg-red-50 text-red-700 border-red-200': status.state === 'failed',
            'bg-slate-50 text-slate-700 border-slate-200': !status.running && status.state !== 'completed' && status.state !== 'failed'
          }">
            <span v-if="status.running" class="w-1.5 h-1.5 bg-amber-500 rounded-full mr-1.5 animate-pulse"></span>
            {{ status.step || '待机' }}
          </span>
        </div>
        
        <div class="p-6">
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <!-- Progress -->
            <div class="md:col-span-2 lg:col-span-4">
              <AppLottieProgressBar :percentage="status.progress || 0" size="sm" />
            </div>

            <!-- Metrics -->
            <div class="bg-slate-50 rounded-xl p-3 border border-slate-100" v-if="status.running && status.speed">
              <div class="text-xs text-slate-500 mb-1">速度</div>
              <div class="text-[13px] font-semibold text-slate-700 font-mono">{{ status.speed || '-' }}</div>
            </div>
            <div class="bg-slate-50 rounded-xl p-3 border border-slate-100" v-if="status.running && status.eta">
              <div class="text-xs text-slate-500 mb-1">剩余时间</div>
              <div class="text-[13px] font-semibold text-slate-700 font-mono">{{ status.eta || '-' }}</div>
            </div>
            <div class="bg-slate-50 rounded-xl p-3 border border-slate-100" v-if="status.running && status.total_bytes > 0">
              <div class="text-xs text-slate-500 mb-1">数据量</div>
              <div class="text-[13px] font-semibold text-slate-700 font-mono flex items-baseline gap-1.5">
                <span class="text-blue-600">{{ formatSize(status.processed_bytes) }}</span>
                <span class="text-slate-400 text-[11px]">/</span>
                <span>{{ formatSize(status.total_bytes) }}</span>
              </div>
            </div>

            <!-- Meta Info -->
            <div v-if="status.output_zip_path" class="md:col-span-2 lg:col-span-4 flex flex-col gap-1.5">
              <span class="text-xs text-slate-500 font-medium">输出文件</span>
              <div class="text-slate-700 break-all bg-slate-50 px-3 py-2 rounded-lg border border-slate-100 font-mono text-[11px] leading-relaxed">{{ status.output_zip_path }}</div>
            </div>
            <div v-if="status.path_snapshot_dir" class="md:col-span-2 lg:col-span-4 flex flex-col gap-1.5">
              <span class="text-xs text-slate-500 font-medium">目录结构复制目标</span>
              <div class="text-slate-700 break-all bg-slate-50 px-3 py-2 rounded-lg border border-slate-100 font-mono text-[11px] leading-relaxed">{{ status.path_snapshot_dir }}</div>
            </div>
            <div v-if="status.error" class="md:col-span-2 lg:col-span-4 flex flex-col gap-1.5">
              <span class="text-xs text-red-500 font-medium">错误</span>
              <div class="text-red-700 break-all bg-red-50 px-3 py-2 rounded-lg border border-red-100 text-[12px]">{{ status.error }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- History Card -->
      <section class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        <div class="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50 shrink-0">
          <h2 class="text-base font-semibold text-slate-900">历史记录</h2>
          <button
            class="lib-refresh-btn"
            :class="{ 'is-loading': historyRefreshing }"
            type="button"
            :disabled="historyRefreshing"
            @click="fetchBackupHistory"
          >
            <RefreshCw
              :size="13"
              :stroke-width="2.4"
              class="lib-refresh-btn-icon"
              :class="{ 'animate-spin': historyRefreshing }"
            />
            <span class="lib-refresh-btn-label">{{ historyRefreshing ? '刷新中…' : '刷新历史' }}</span>
          </button>
        </div>
        <div class="overflow-hidden p-0" style="min-height: 280px; max-height: 400px;">
          <div v-if="!backupHistory.length" class="flex min-h-[280px] items-center justify-center px-6 py-8">
            <AppEmptyState description="暂无备份记录" size="default" />
          </div>
          <el-table v-else :data="backupHistory" style="width: 100%" class="custom-table" :row-class-name="() => ''">
            <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="font-mono text-[13px] text-slate-700">{{ row.filename }}</span>
              </template>
            </el-table-column>
            <el-table-column label="大小变化" width="160">
              <template #default="{ row }">
                <div class="flex items-center gap-1.5">
                  <span class="text-[13px] text-slate-500">{{ formatSize(row.pre_size_bytes) }}</span>
                  <span class="text-slate-300 text-xs">→</span>
                  <span class="text-[13px] font-medium text-slate-700">{{ formatSize(row.post_size_bytes) }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="压缩率" width="80" align="right">
              <template #default="{ row }">
                <span class="text-[13px] font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">{{ (row.compression_ratio * 100).toFixed(1) }}%</span>
              </template>
            </el-table-column>
            <el-table-column prop="speed_avg" label="平均速度" width="100">
              <template #default="{ row }">
                <span class="text-[13px] text-slate-600">{{ row.speed_avg }}</span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="90">
              <template #default="{ row }">
                <span class="text-[13px] text-slate-500">{{ formatDuration(row.duration_seconds) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="备份日期" width="150">
              <template #default="{ row }">
                <span class="text-[13px] text-slate-500">{{ formatDate(row.created_at) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Archive,
  Folder,
  FolderOpen,
  KeyRound,
  Save,
  Play,
  RotateCcw,
  XCircle,
  RefreshCw,
  Loader2,
  CloudUpload
} from 'lucide-vue-next'
import { configApi, backupApi, baiduNetdiskApi } from '../api'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppLottieProgressBar from '../components/common/AppLottieProgressBar.vue'
import AnimatedPasswordInput from '../components/common/AnimatedPasswordInput.vue'
import AppDropdown from '../components/common/AppDropdown.vue'

const archiveFormatOptions = [
  { value: 'zip', label: '.zip' },
  { value: '7z', label: '.7z' }
]

const baiduUploadPolicyOptions = [
  { value: 'skip', label: '跳过同名' },
  { value: 'overwrite', label: '覆盖同名' },
  { value: 'rsync', label: '增量同步' }
]

const saving = ref(false)
const actionLoading = ref(false)
const historyRefreshing = ref(false)
const status = ref({
  state: 'idle',
  running: false,
  progress: 0,
  step: '待机',
  error: null,
  output_zip_path: '',
  path_snapshot_dir: '',
  logs: [],
  processed_bytes: 0,
  total_bytes: 0,
  has_checkpoint: false
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
  compression_threads: 0,
  dictionary_size_mb: 0,
  solid_archive: true,
  baidu_upload_enabled: false,
  baidu_upload_remote_dir: '/KikoeruManager',
  baidu_upload_create_subdir: '',
  baidu_upload_conflict_policy: 'skip',
  baidu_upload_cleanup_local_archive: false
})
const backupHistory = ref([])



let timer = null
let libraryBackupInitialized = false
let libraryBackupViewActive = false
const BACKUP_STATUS_POLL_INTERVAL_MS = 1000
const BACKUP_STATUS_POLL_MAX_INTERVAL_MS = 120000
let backupStatusPollDelayMs = BACKUP_STATUS_POLL_INTERVAL_MS

function stopPolling() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

function startPolling() {
  stopPolling()
  if (!libraryBackupViewActive || isDocumentHidden()) return
  timer = setTimeout(async () => {
    timer = null
    if (!libraryBackupViewActive || isDocumentHidden()) return
    await fetchBackupStatus(false)
  }, backupStatusPollDelayMs)
}

function isDocumentHidden() {
  return typeof document !== 'undefined' && document.hidden
}

function handleVisibilityChange() {
  if (isDocumentHidden()) {
    stopPolling()
    return
  }
  if (!libraryBackupViewActive) return
  backupStatusPollDelayMs = BACKUP_STATUS_POLL_INTERVAL_MS
  fetchBackupStatus(false)
}

async function loadConfig() {
  const data = await configApi.get()
  backupConfig.value = {
    ...backupConfig.value,
    ...(data?.backup_zip || {})
  }
}

async function fetchBackupHistory() {
  if (historyRefreshing.value) return
  try {
    historyRefreshing.value = true
    const data = await backupApi.history()
    backupHistory.value = data || []
  } catch (error) {
    console.error('获取备份历史失败:', error)
  } finally {
    historyRefreshing.value = false
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
        compression_threads: backupConfig.value.compression_threads ?? 0,
        dictionary_size_mb: backupConfig.value.dictionary_size_mb ?? 0,
        solid_archive: backupConfig.value.solid_archive ?? true,
        baidu_upload_enabled: backupConfig.value.baidu_upload_enabled ?? false,
        baidu_upload_remote_dir: backupConfig.value.baidu_upload_remote_dir || '/KikoeruManager',
        baidu_upload_create_subdir: backupConfig.value.baidu_upload_create_subdir || '',
        baidu_upload_conflict_policy: backupConfig.value.baidu_upload_conflict_policy || 'skip',
        baidu_upload_cleanup_local_archive: backupConfig.value.baidu_upload_cleanup_local_archive ?? false
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
    backupStatusPollDelayMs = BACKUP_STATUS_POLL_INTERVAL_MS
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
    backupStatusPollDelayMs = Math.min(backupStatusPollDelayMs * 2, BACKUP_STATUS_POLL_MAX_INTERVAL_MS)
    if (status.value.running) startPolling()
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

async function startBackupAndUpload() {
  if (!backupConfig.value.enabled) {
    ElMessage.warning('请先启用库存打包功能')
    return
  }
  if (!backupConfig.value.baidu_upload_enabled) {
    ElMessage.warning('请先启用百度网盘上传')
    return
  }
  if (!backupConfig.value.password?.trim()) {
    ElMessage.warning('请先填写压缩密码')
    return
  }
  try {
    actionLoading.value = true
    await saveBackupConfig(false)
    const sourcePath = backupConfig.value.source_path || ''
    const result = await baiduNetdiskApi.startUpload({
      sourcePaths: [sourcePath].filter(Boolean),
      remoteDir: backupConfig.value.baidu_upload_remote_dir || '/KikoeruManager',
      createRemoteSubdir: backupConfig.value.baidu_upload_create_subdir || '',
      compressEnabled: true,
      backupZipOptions: {
        source_path: backupConfig.value.source_path || '',
        output_dir: backupConfig.value.output_dir || '',
        password: backupConfig.value.password || '',
        archive_format: backupConfig.value.archive_format || 'zip',
        compression_level: backupConfig.value.compression_level ?? 9,
        compression_threads: backupConfig.value.compression_threads ?? 0,
        dictionary_size_mb: backupConfig.value.dictionary_size_mb ?? 0,
        solid_archive: backupConfig.value.solid_archive ?? true
      },
      conflictPolicy: backupConfig.value.baidu_upload_conflict_policy || 'skip',
      cleanupLocalArchive: backupConfig.value.baidu_upload_cleanup_local_archive ?? false,
      batchName: '库存打包上传'
    })
    ElMessage.success(result?.message || '百度网盘上传任务已创建')
  } catch (error) {
    ElMessage.error('创建百度网盘上传任务失败：' + (error.response?.data?.detail || error.message))
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

async function resumeBackup() {
  try {
    actionLoading.value = true
    const result = await backupApi.resume()
    status.value = { ...status.value, ...(result || {}) }
    startPolling()
    ElMessage.success('库存打包任务已恢复')
  } catch (error) {
    ElMessage.error('恢复库存打包失败：' + (error.response?.data?.detail || error.message))
  } finally {
    actionLoading.value = false
  }
}

onMounted(async () => {
  if (!libraryBackupInitialized) {
    await loadConfig()
    await fetchBackupStatus(false)
    await fetchBackupHistory()
    libraryBackupInitialized = true
  }
  libraryBackupViewActive = true
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityChange)
  }
  if (status.value.running) startPolling()
})

onActivated(async () => {
  if (libraryBackupViewActive) return
  libraryBackupViewActive = true
  await fetchBackupStatus(false)
  await fetchBackupHistory()
})

onDeactivated(() => {
  libraryBackupViewActive = false
  stopPolling()
})

onBeforeUnmount(() => {
  libraryBackupViewActive = false
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
  }
  stopPolling()
})
</script>

<style scoped>
button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; }

/* ==============================================================
 * 页头按钮：page-head-btn 规范（对齐 ASMRSync.vue / ActivityHistory.vue）
 *  - 基础 ghost 白底
 *  - .primary 黑灰渐变 + shimmer 扫光
 *  - .is-amber / .is-danger 为状态色 ghost 变体
 *  - .icon-only 仅图标圆形按钮
 * ============================================================ */
.page-head-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden; /* 容纳 shimmer ::before */
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background 0.35s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
  will-change: transform, opacity;
}
.page-head-btn :deep(.page-head-btn-icon) {
  flex-shrink: 0;
  transition: transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
}
.page-head-btn :deep(svg) { flex-shrink: 0; }

.page-head-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}
.page-head-btn:active:not(:disabled) {
  transform: scale(0.96);
  transition:
    transform 0.12s ease,
    box-shadow 0.18s ease,
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    opacity 0.2s ease;
}
.page-head-btn:active:not(:disabled) :deep(.page-head-btn-icon) {
  transform: scale(0.82);
  transition: transform 0.12s ease;
}
/* disabled：仅 opacity + cursor，不重置 transform/shadow，避免 hover 中点击瞬间塌回闪烁 */
.page-head-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* === Primary 黑灰渐变按钮 + shimmer 高光扫光 === */
.page-head-btn.primary {
  background: linear-gradient(135deg, #111827, #1e293b);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}
.page-head-btn.primary::before {
  content: '';
  position: absolute;
  top: 0;
  left: -120%;
  width: 60%;
  height: 100%;
  background: linear-gradient(
    100deg,
    transparent 0%,
    rgba(255, 255, 255, 0.05) 30%,
    rgba(255, 255, 255, 0.28) 50%,
    rgba(255, 255, 255, 0.05) 70%,
    transparent 100%
  );
  transform: skewX(-18deg);
  transition: left 0.7s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}
.page-head-btn.primary:hover {
  background: linear-gradient(135deg, #1e293b, #334155);
  box-shadow:
    0 14px 28px rgba(15, 23, 42, 0.28),
    0 0 0 4px rgba(15, 23, 42, 0.05);
}
.page-head-btn.primary:hover::before {
  left: 130%;
}

/* === Ghost 白底按钮 hover：纯色 transition（gradient 不能 transition）=== */
.page-head-btn.ghost {
  background-color: #fff;
}
.page-head-btn.ghost:hover {
  background-color: #f8fafc;
  border-color: rgba(15, 23, 42, 0.2);
}

/* === Ghost amber 状态色变体（恢复任务） === */
.page-head-btn.ghost.is-amber {
  color: #b45309;
  border-color: rgba(245, 158, 11, 0.35);
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
}
.page-head-btn.ghost.is-amber:hover {
  background: linear-gradient(180deg, #fef3c7 0%, #fde68a 100%);
  border-color: rgba(217, 119, 6, 0.55);
  color: #92400e;
  box-shadow: 0 10px 22px rgba(217, 119, 6, 0.18);
}

/* === Ghost danger 状态色变体（取消任务） === */
.page-head-btn.ghost.is-danger {
  color: #b91c1c;
  border-color: rgba(239, 68, 68, 0.32);
  background: linear-gradient(180deg, #fef2f2 0%, #fee2e2 100%);
}
.page-head-btn.ghost.is-danger:hover {
  background: linear-gradient(180deg, #fee2e2 0%, #fecaca 100%);
  border-color: rgba(220, 38, 38, 0.5);
  color: #991b1b;
  box-shadow: 0 10px 22px rgba(220, 38, 38, 0.16);
}

/* === icon-only：仅图标的圆形按钮（刷新） === */
.page-head-btn.icon-only {
  padding: 0;
  width: 36px;
  justify-content: center;
}

/* === 各按钮专属图标动效 === */
/* 保存：Save 图标 hover 时轻微下沉 + 缩放（模拟落盘动作） */
.page-head-btn.btn-save:hover:not(:disabled) :deep(.page-head-btn-icon) {
  transform: translateY(1px) scale(1.12);
  filter: drop-shadow(0 2px 4px rgba(15, 23, 42, 0.24));
  color: #334155;
}

/* 开始打包：Play 三角 hover 时右移 + 放大（模拟启动） */
.page-head-btn.btn-pack:hover:not(:disabled) :deep(.page-head-btn-icon) {
  transform: translateX(2px) scale(1.18);
  filter: drop-shadow(0 2px 5px rgba(255, 255, 255, 0.45));
  animation: pack-icon-bob 1.2s ease-in-out infinite;
}
@keyframes pack-icon-bob {
  0%, 100% { transform: translateX(2px) scale(1.18); }
  50% { transform: translateX(4px) scale(1.18); }
}

/* 恢复任务：RotateCcw hover 时反向旋转一圈 */
.page-head-btn.btn-resume:hover:not(:disabled) :deep(.page-head-btn-icon:not(.animate-spin)) {
  transform: rotate(-360deg) scale(1.1);
  transition: transform 0.65s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 取消任务：XCircle hover 时旋转 90° + 缩放（模拟"叉掉"） */
.page-head-btn.btn-cancel:hover:not(:disabled) :deep(.page-head-btn-icon) {
  transform: rotate(90deg) scale(1.15);
}

/* 刷新：RefreshCw hover 时旋转一整圈（非 loading 态） */
.page-head-btn.btn-refresh:hover:not(:disabled) :deep(.page-head-btn-icon:not(.animate-spin)) {
  transform: rotate(-360deg) scale(1.1);
  transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 文本 label：min-width + 居中，避免「保存」→「保存中…」宽度跳变 */
.page-head-btn-label {
  display: inline-block;
  text-align: center;
  transition: opacity 0.2s ease, letter-spacing 0.3s ease;
}
.page-head-btn.primary .page-head-btn-label { min-width: 70px; }
.page-head-btn.ghost .page-head-btn-label { min-width: 56px; }
.page-head-btn:hover .page-head-btn-label {
  letter-spacing: 0.04em;
}

/* ==============================================================
 * AppDropdown 在 el-form-item 内的全宽适配（压缩后缀格式）
 * ============================================================ */
.backup-format-dd {
  display: block;
  width: 100%;
}
.backup-format-dd :deep(.app-dd-root) {
  display: block;
  width: 100%;
}
.backup-format-dd :deep(.app-dd-trigger) {
  width: 100%;
  min-height: 40px;
  height: 40px;
  border-radius: 8px;
  background: #fff;
  border-color: rgb(220 226 235);
  font-size: 14px;
  font-weight: 500;
  padding: 0 12px;
  justify-content: space-between;
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}
.backup-format-dd :deep(.app-dd-trigger:hover) {
  border-color: #94a3b8;
  box-shadow: 0 0 0 1px #94a3b8 inset;
}
.backup-format-dd :deep(.app-dd-trigger.is-open) {
  border-color: rgba(51, 65, 85, 0.42);
  box-shadow: 0 0 0 2px rgba(51, 65, 85, 0.16) inset;
}

.backup-upload-section {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid rgb(226 232 240);
}

.backup-upload-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.backup-upload-section-title {
  color: rgb(15 23 42);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.35;
}

.backup-upload-section-desc {
  margin-top: 4px;
  color: rgb(100 116 139);
  font-size: 12px;
  line-height: 1.45;
}

.backup-upload-section-form {
  display: grid;
  grid-template-columns: repeat(1, minmax(0, 1fr));
  column-gap: 20px;
  row-gap: 8px;
}

@media (min-width: 768px) {
  .backup-upload-section-form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (min-width: 1024px) {
  .backup-upload-section-form {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .backup-upload-section-head {
    align-items: center;
  }
}

/* ==============================================================
 * 历史记录刷新按钮 lib-refresh-btn
 *  - 28px 高 ghost 小按钮
 *  - hover：translateY 抬起 + 边框加深 + 字间距展开 + RefreshCw 反向旋转 360°
 *  - is-loading 时图标走 animate-spin（无限旋转）
 * ============================================================ */
.lib-refresh-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 28px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background 0.25s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
}
.lib-refresh-btn:hover {
  transform: translateY(-1px);
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  border-color: rgba(15, 23, 42, 0.22);
  color: #0f172a;
  box-shadow: 0 6px 14px -8px rgba(15, 23, 42, 0.18);
}
.lib-refresh-btn:active:not(:disabled) {
  transform: translateY(0) scale(0.96);
  transition: transform 0.12s ease;
}
.lib-refresh-btn:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.lib-refresh-btn-icon {
  flex-shrink: 0;
  color: #94a3b8;
  transition:
    transform 0.6s cubic-bezier(0.4, 0, 0.2, 1),
    color 0.25s ease;
}
/* hover 时图标变蓝 + 反向旋转 360°（loading 中由 animate-spin 接管，避免冲突） */
.lib-refresh-btn:hover:not(:disabled) .lib-refresh-btn-icon:not(.animate-spin) {
  color: #334155;
  transform: rotate(-360deg) scale(1.08);
}

.lib-refresh-btn-label {
  display: inline-block;
  transition: letter-spacing 0.3s ease;
}
.lib-refresh-btn:hover .lib-refresh-btn-label {
  letter-spacing: 0.04em;
}

/* loading 中按钮整体微微淡化 + 高亮蓝色边框，提示用户正在刷新 */
.lib-refresh-btn.is-loading {
  background: linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
  border-color: rgba(51, 65, 85, 0.3);
  color: #334155;
}
.lib-refresh-btn.is-loading .lib-refresh-btn-icon {
  color: #334155;
}

/* 进度条平滑过渡 */
:deep(.el-progress-bar__inner) {
  transition: width 0.8s ease-out;
}

/* 自定义表格样式调整 */
:deep(.custom-table .el-table__header-wrapper th) {
  background-color: rgb(248 250 252) !important;
  color: rgb(71 85 105);
  font-weight: 600;
  font-size: 13px;
  border-bottom: 1px solid rgb(226 232 240);
}
:deep(.custom-table .el-table__body-wrapper td) {
  border-bottom: 1px solid rgb(241 245 249);
}

/* 输入框全局样式优化 */
:deep(.el-input__wrapper),
:deep(.el-textarea__wrapper) {
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05) !important;
  transition: all 0.3s ease !important;
  border-radius: 8px !important;
}
:deep(.el-input__inner) {
  color: rgb(30 41 59) !important;
  font-weight: 500 !important;
}
:deep(.el-input__inner::placeholder) {
  color: rgb(148 163 184) !important;
  font-weight: 400 !important;
}

:deep(.el-input__wrapper:hover),
:deep(.el-textarea__wrapper:hover) {
  box-shadow: 0 0 0 1px #94a3b8 inset !important;
}

:deep(.el-input__wrapper.is-focus),
:deep(.el-textarea__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(51, 65, 85, 0.18) inset !important;
}

/* 密码框眼睛图标特效 */
:deep(.el-input__password) {
  transition: all 0.3s ease !important;
}
:deep(.el-input__password:hover) {
  transform: scale(1.15) rotate(5deg) !important;
  color: #334155 !important;
}

:global(html.kikoerumanager-dark .backup-page .page-head-btn.primary) {
  background: var(--km-dark-primary-button-bg) !important;
  background-image: none !important;
  border-color: rgba(255, 255, 255, 0.28) !important;
  color: var(--km-dark-primary-button-text) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .backup-page .page-head-btn.primary:hover) {
  background: var(--km-dark-button-bg-hover) !important;
  background-image: none !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .backup-page .backup-format-dd .app-dd-trigger.is-open),
:global(html.kikoerumanager-dark .backup-page :is(.el-input__wrapper.is-focus, .el-textarea__wrapper.is-focus)) {
  border-color: var(--km-dark-border-strong) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .backup-page .backup-upload-section) {
  border-top-color: var(--km-dark-border) !important;
}

:global(html.kikoerumanager-dark .backup-page .backup-upload-section-title) {
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark .backup-page .backup-upload-section-desc) {
  color: var(--km-dark-text-muted) !important;
}

:global(html.kikoerumanager-dark .backup-page .el-slider) {
  --el-slider-main-bg-color: #e5e5e8;
  --el-slider-runway-bg-color: #252529;
  --el-color-primary: #e5e5e8;
  --el-color-primary-light-3: #f5f5f5;
}

:global(html.kikoerumanager-dark .backup-page :is(.el-slider__runway, .el-input-number, .el-input-number__decrease, .el-input-number__increase)) {
  background: #242427 !important;
  background-image: none !important;
  border-color: var(--km-dark-border) !important;
  color: var(--km-dark-text) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .backup-page .el-slider__runway) {
  background: #252529 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .backup-page .el-slider__bar) {
  background: #e5e5e8 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark .backup-page .el-slider__button) {
  background: #f5f5f5 !important;
  border-color: var(--km-dark-border-strong) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .backup-page .el-slider__button:hover),
:global(html.kikoerumanager-dark .backup-page .el-slider__button-wrapper:hover .el-slider__button),
:global(html.kikoerumanager-dark .backup-page :is(.el-input-number__decrease, .el-input-number__increase):hover) {
  background: #2f2f34 !important;
  border-color: var(--km-dark-border-strong) !important;
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark .backup-page .el-slider__button:hover),
:global(html.kikoerumanager-dark .backup-page .el-slider__button-wrapper:hover .el-slider__button) {
  background: #ffffff !important;
}

:global(html.kikoerumanager-dark .backup-page .el-switch.is-checked .el-switch__core) {
  background: var(--km-dark-button-bg-hover) !important;
  background-image: none !important;
  border-color: var(--km-dark-border-strong) !important;
}

</style>
