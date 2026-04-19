<template>
  <div class="logs">
    <div class="page-header">
      <div>
        <h1 class="page-title">系统日志</h1>
        <p class="page-subtitle">查看实时日志、筛选模块与级别，并在需要时暂停自动刷新。</p>
      </div>
      <div class="header-actions">
        <el-button :type="isPaused ? 'success' : 'warning'" @click="togglePause">
          <el-icon><component :is="isPaused ? VideoPlay : VideoPause" /></el-icon>
          {{ isPaused ? '恢复自动刷新' : '暂停自动刷新' }}
        </el-button>
        <el-button @click="refreshLogs(true)">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
        <el-button type="danger" @click="clearLogs">
          <AppLottieIcon :src="deleteIconAnimation" :size="32" tone="danger" />
          清空视图
        </el-button>
      </div>
    </div>

    <el-card class="logs-card" shadow="never">
      <div class="filter-section">
        <div class="filter-group filter-group--levels">
          <span class="filter-label">日志级别</span>
          <div class="level-filter-list">
            <button
              v-for="level in allLevels"
              :key="level"
              type="button"
              class="level-filter-chip"
              :class="[
                `is-${level.toLowerCase()}`,
                { 'is-active': isLevelSelected(level) }
              ]"
              @click="toggleLevel(level)"
            >
              <span class="level-filter-dot" />
              <span>{{ level }}</span>
            </button>
          </div>
        </div>

        <div class="filter-group">
          <span class="filter-label">模块筛选</span>
          <el-select
            v-model="selectedModules"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="全部模块"
            clearable
            size="small"
            style="width: 220px"
          >
            <el-option v-for="mod in availableModules" :key="mod" :label="mod" :value="mod" />
          </el-select>
        </div>

        <div class="filter-group">
          <span class="filter-label">搜索</span>
          <el-input
            v-model="searchKeyword"
            placeholder="搜索日志内容"
            clearable
            size="small"
            style="width: 240px"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>

        <div class="filter-group">
          <span class="filter-label">显示条数</span>
          <el-select v-model="logLimit" size="small" style="width: 110px" @change="refreshLogs(true)">
            <el-option :value="100" label="100 条" />
            <el-option :value="300" label="300 条" />
            <el-option :value="500" label="500 条" />
            <el-option :value="1000" label="1000 条" />
            <el-option :value="2000" label="2000 条" />
          </el-select>
        </div>

        <div class="filter-stats">{{ filteredLogs.length }} / {{ logs.length }} 条</div>
      </div>

      <div ref="logContainer" class="log-container" :class="{ paused: isPaused }" @scroll.passive="handleScroll">
        <div class="log-toolbar-status">
          <span v-if="isPaused" class="log-status-indicator paused">已暂停自动刷新</span>
          <span v-else-if="!autoFollowLogs" class="log-status-indicator history">正在查看历史日志</span>
          <span v-else class="log-status-indicator active">自动跟随中</span>
        </div>

        <div v-for="log in filteredLogs" :key="log.id" class="log-line" :class="`log-${log.level.toLowerCase()}`">
          <span class="log-time">{{ log.time || '--' }}</span>
          <span class="log-level" :class="`level-${log.level.toLowerCase()}`">{{ log.level }}</span>
          <span v-if="log.module" class="log-module" :style="{ backgroundColor: getModuleColor(log.module) }">
            {{ log.module }}
          </span>
          <span class="log-message">{{ log.message }}</span>
        </div>
      </div>

      <el-empty v-if="filteredLogs.length === 0 && logs.length > 0" description="没有匹配的日志" />
      <el-empty v-if="logs.length === 0" description="暂无日志" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { Delete, Refresh, Search, VideoPause, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import { logApi } from '../api'
import AppLottieIcon from '../components/common/AppLottieIcon.vue'
import deleteIconAnimation from '../assets/anime/Delete icon animation.lottie'

const LOG_POLL_INTERVAL = 5000

const logs = ref([])
const logContainer = ref(null)
const isPaused = ref(false)
const autoFollowLogs = ref(true)
const logLimit = ref(300)
const selectedLevels = ref(['INFO', 'WARNING', 'ERROR'])
const selectedModules = ref([])
const searchKeyword = ref('')

const allLevels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']

let intervalId = null
let lastLogSignature = ''

const moduleColors = {
  Prekikoeru: '#6d8ef7',
  关联查询: '#8b5cf6',
  字幕抓取: '#7c3aed',
  CONFIG: '#0ea5e9',
  'CONFIG SAVE': '#0284c7',
  RENAME: '#10b981',
  'API RENAME': '#059669',
  解压: '#f59e0b',
  分类: '#3b82f6',
  元数据: '#ec4899',
  密码: '#6366f1',
  清理: '#14b8a6',
  扫描: '#f97316',
  删除: '#ef4444'
}

const availableModules = computed(() => {
  const modules = new Set()
  logs.value.forEach((log) => {
    if (log.module) modules.add(log.module)
  })
  return Array.from(modules).sort()
})

const filteredLogs = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  return logs.value.filter((log) => {
    if (!selectedLevels.value.includes(log.level)) return false
    if (selectedModules.value.length > 0 && !selectedModules.value.includes(log.module)) return false
    if (!keyword) return true
    return (
      String(log.message || '').toLowerCase().includes(keyword) ||
      String(log.module || '').toLowerCase().includes(keyword)
    )
  })
})

function isLevelSelected(level) {
  return selectedLevels.value.includes(level)
}

function toggleLevel(level) {
  if (selectedLevels.value.includes(level)) {
    if (selectedLevels.value.length === 1) return
    selectedLevels.value = selectedLevels.value.filter((item) => item !== level)
    return
  }
  selectedLevels.value = [...selectedLevels.value, level]
}

function getModuleColor(moduleName) {
  return moduleColors[moduleName] || '#64748b'
}

function parseModule(message, rawLine) {
  const bracketMatch = rawLine.match(/\[([^\]]+)\]/)
  if (bracketMatch) {
    const tag = bracketMatch[1]
    if (tag.includes('Prekikoeru') || tag.includes('CONFIG') || tag.includes('RENAME') || tag.includes('RJ字幕')) {
      return tag
    }
  }
  if (message.includes('扫描') || message.includes('库存')) return '扫描'
  if (message.includes('解压') || message.includes('压缩')) return '解压'
  if (message.includes('分类') || message.includes('规则')) return '分类'
  if (message.includes('元数据') || message.includes('RJ')) return '元数据'
  if (message.includes('密码')) return '密码'
  if (message.includes('清理') || message.includes('删除')) return '清理'
  return null
}

function parseLogLine(line, index) {
  let match = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+\S+\s+-\s+(.+)$/)
  if (match) {
    const message = match[3]
    return {
      id: `${index}-${match[1]}-${match[2]}-${message}`,
      time: match[1],
      level: match[2].toUpperCase(),
      module: parseModule(message, line),
      message,
      raw: line
    }
  }

  match = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+-\s+\S+\s+-\s+(\w+)\s+-\s+(.+)$/)
  if (match) {
    const message = match[3]
    return {
      id: `${index}-${match[1]}-${match[2]}-${message}`,
      time: match[1],
      level: match[2].toUpperCase(),
      module: parseModule(message, line),
      message,
      raw: line
    }
  }

  return {
    id: `${index}-${line}`,
    time: '',
    level: 'INFO',
    module: parseModule(line, line),
    message: line,
    raw: line
  }
}

function isNearBottom() {
  if (!logContainer.value) return true
  const { scrollTop, scrollHeight, clientHeight } = logContainer.value
  return scrollHeight - scrollTop - clientHeight < 40
}

function handleScroll() {
  autoFollowLogs.value = isNearBottom()
}

function scrollToBottom() {
  if (!logContainer.value) return
  logContainer.value.scrollTop = logContainer.value.scrollHeight
  autoFollowLogs.value = true
}

function togglePause() {
  isPaused.value = !isPaused.value
  if (isPaused.value) {
    ElMessage.info('已暂停自动刷新，可以查看历史日志')
    return
  }
  ElMessage.success('已恢复自动刷新')
  refreshLogs(true)
}

async function refreshLogs(force = false) {
  if (!force && (isPaused.value || document.visibilityState === 'hidden')) return

  try {
    const shouldFollow = autoFollowLogs.value || isNearBottom()
    const data = await logApi.get(logLimit.value)
    const logLines = Array.isArray(data.logs) ? data.logs : []
    const signature = `${logLines.length}::${logLines[0] || ''}::${logLines[logLines.length - 1] || ''}`
    if (!force && signature === lastLogSignature) return

    lastLogSignature = signature
    logs.value = logLines.map((line, index) => parseLogLine(line, index))

    await nextTick()
    if (shouldFollow && !isPaused.value) scrollToBottom()
  } catch (error) {
    console.error('获取日志失败:', error)
  }
}

async function clearLogs() {
  try {
    await showSystemConfirm({ title: '确认', message: '确定要清空当前页面的日志显示吗？这不会删除后端日志文件。', tone: 'warning' })
    logs.value = []
    lastLogSignature = ''
    ElMessage.success('日志视图已清空')
  } catch (_) {
  }
}

onMounted(async () => {
  await refreshLogs(true)
  intervalId = setInterval(() => {
    refreshLogs()
  }, LOG_POLL_INTERVAL)
})

onUnmounted(() => {
  if (intervalId) clearInterval(intervalId)
})
</script>

<style scoped>
.logs {
  max-width: 1480px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.page-title {
  margin: 0;
  font-size: 30px;
  font-weight: 700;
  color: #0f172a;
}

.page-subtitle {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 14px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logs-card {
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
}

.filter-section {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.98) 0%, rgba(241, 245, 249, 0.92) 100%);
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-group--levels {
  align-items: flex-start;
}

.filter-label {
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  line-height: 30px;
}

.filter-stats {
  margin-left: auto;
  color: #94a3b8;
  font-size: 13px;
  font-weight: 600;
}

.level-filter-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.level-filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid #d7e0ea;
  border-radius: 999px;
  background: #ffffff;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition: border-color 0.16s ease, background-color 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}

.level-filter-chip:hover {
  border-color: #c1cfde;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.06);
}

.level-filter-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.45;
}

.level-filter-chip.is-active .level-filter-dot {
  opacity: 1;
}

.level-filter-chip.is-debug {
  color: #64748b;
}

.level-filter-chip.is-debug.is-active {
  border-color: #cbd5e1;
  background: #f1f5f9;
  color: #475569;
}

.level-filter-chip.is-info {
  color: #3b82f6;
}

.level-filter-chip.is-info.is-active {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}

.level-filter-chip.is-warning {
  color: #d97706;
}

.level-filter-chip.is-warning.is-active {
  border-color: #fcd34d;
  background: #fffbeb;
  color: #b45309;
}

.level-filter-chip.is-error {
  color: #ef4444;
}

.level-filter-chip.is-error.is-active {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.log-container {
  height: 620px;
  overflow-y: auto;
  padding: 10px 14px 16px;
  border-radius: 14px;
  background: linear-gradient(180deg, #1f2937 0%, #233047 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
  color: #e2e8f0;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.log-container.paused {
  border: 2px solid #f59e0b;
}

.log-toolbar-status {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  justify-content: flex-end;
  padding: 2px 0 10px;
  background: transparent;
}

.log-status-indicator {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border: 1px solid rgba(147, 197, 253, 0.22);
  border-radius: 999px;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}

.log-status-indicator.active {
  background: rgba(16, 185, 129, 0.94);
}

.log-status-indicator.history {
  background: rgba(59, 130, 246, 0.92);
}

.log-status-indicator.paused {
  background: rgba(245, 158, 11, 0.94);
}

.log-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background-color 0.16s ease;
}

.log-line:hover {
  background: rgba(148, 163, 184, 0.08);
}

.log-time {
  flex-shrink: 0;
  color: #7b8aa3;
  white-space: nowrap;
}

.log-level {
  min-width: 50px;
  padding: 0 4px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  text-align: center;
  white-space: nowrap;
  flex-shrink: 0;
}

.log-debug .log-level {
  background: #374151;
  color: #cbd5e1;
}

.log-info .log-level {
  background: #17355d;
  color: #7cc0ff;
}

.log-warning .log-level {
  background: #6b3f12;
  color: #fbbf24;
}

.log-error .log-level {
  background: #6f1f1f;
  color: #fca5a5;
}

.log-module {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 999px;
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
}

.log-message {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

.log-debug {
  opacity: 0.72;
}

.log-warning {
  background: rgba(245, 158, 11, 0.08);
}

.log-error {
  background: rgba(239, 68, 68, 0.08);
}
</style>
