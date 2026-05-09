<template>
  <div class="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
    <AppPageHeader
      :icon="Archive"
      icon-color="#9333ea"
      title="库存打包"
      subtitle="将当前库存完整打包为压缩文件，支持目录结构快照和自动加密。"
    >
        <button 
          class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg shadow-sm hover:bg-slate-50 hover:text-slate-900 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-1 active:scale-95 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100"
          :disabled="saving"
          @click="saveBackupConfig"
        >
          <svg v-if="saving" class="w-4 h-4 animate-spin text-slate-500" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <svg v-else class="w-4 h-4 text-slate-500 group-hover:text-blue-500 group-hover:scale-110 transition-all duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"></path></svg>
          保存配置
        </button>

        <button 
          class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-emerald-600 border border-transparent rounded-lg shadow-sm hover:bg-emerald-500 hover:shadow-emerald-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1 active:scale-95 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 disabled:hover:shadow-none"
          :disabled="status.running || actionLoading"
          @click="startBackup"
        >
          <svg v-if="actionLoading && !status.running" class="w-4 h-4 animate-spin text-emerald-200" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <svg v-else class="w-4 h-4 group-hover:rotate-12 group-hover:scale-110 transition-all duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
          开始打包
        </button>

        <button 
          class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-500 border border-transparent rounded-lg shadow-sm hover:bg-amber-400 hover:shadow-amber-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-amber-400 focus:ring-offset-1 active:scale-95 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 disabled:hover:shadow-none"
          :disabled="!status.has_checkpoint || status.running || actionLoading"
          @click="resumeBackup"
        >
          <svg v-if="actionLoading && !status.running" class="w-4 h-4 animate-spin text-amber-200" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <svg v-else class="w-4 h-4 group-hover:-translate-y-0.5 group-hover:scale-110 transition-all duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
          恢复任务
        </button>

        <button 
          class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-red-700 bg-red-50 border border-red-200 rounded-lg shadow-sm hover:bg-red-100 hover:text-red-800 hover:border-red-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-red-200 focus:ring-offset-1 active:scale-95 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 disabled:hover:shadow-none"
          :disabled="!status.running || actionLoading"
          @click="cancelBackup"
        >
          <svg class="w-4 h-4 text-red-600 group-hover:scale-110 group-hover:rotate-90 transition-all duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"></path></svg>
          取消任务
        </button>

        <button 
          class="group relative inline-flex items-center justify-center p-2 text-slate-500 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:text-slate-700 hover:shadow-sm hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-1 active:scale-95 transition-all duration-200"
          title="刷新状态"
          @click="fetchBackupStatus"
        >
          <svg class="w-5 h-5 group-hover:rotate-180 transition-transform duration-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
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
              <el-select v-model="backupConfig.archive_format" class="w-full">
                <el-option label=".zip" value="zip" />
                <el-option label=".7z" value="7z" />
              </el-select>
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
            class="group relative inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-md hover:bg-slate-50 hover:text-slate-900 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-1 active:scale-95 transition-all duration-200"
            @click="fetchBackupHistory"
          >
            <svg class="w-3.5 h-3.5 text-slate-400 group-hover:text-blue-500 group-hover:-rotate-180 transition-all duration-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
            刷新历史
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
import { Archive, Folder, FolderOpen, KeyRound } from 'lucide-vue-next'
import { configApi, backupApi } from '../api'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppLottieProgressBar from '../components/common/AppLottieProgressBar.vue'
import AnimatedPasswordInput from '../components/common/AnimatedPasswordInput.vue'

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
  compression_threads: 0
})
const backupHistory = ref([])



let timer = null
let libraryBackupInitialized = false
let libraryBackupViewActive = false

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
  }, 1000)
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
        compression_threads: backupConfig.value.compression_threads ?? 0,
        dictionary_size_mb: backupConfig.value.dictionary_size_mb ?? 0,
        solid_archive: backupConfig.value.solid_archive ?? true
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
  stopPolling()
})
</script>

<style scoped>
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
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5) inset !important;
}

/* 密码框眼睛图标特效 */
:deep(.el-input__password) {
  transition: all 0.3s ease !important;
}
:deep(.el-input__password:hover) {
  transform: scale(1.15) rotate(5deg) !important;
  color: #3b82f6 !important;
}

/* 选择器优化 */
:deep(.el-select .el-input__wrapper) {
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05) !important;
  border-radius: 8px !important;
}
:deep(.el-select .el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #94a3b8 inset !important;
}
:deep(.el-select .el-input.is-focus .el-input__wrapper) {
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5) inset !important;
}
</style>
