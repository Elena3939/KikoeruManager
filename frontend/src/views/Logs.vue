<template>
  <div class="logs">
    <h1 class="page-title">日志</h1>

    <el-card>
      <template #header>
        <div class="card-header">
          <span>系统日志</span>
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
              <el-icon><Delete /></el-icon>
              清空视图
            </el-button>
          </div>
        </div>
      </template>

      <div class="filter-section">
        <div class="filter-group">
          <span class="filter-label">日志级别：</span>
          <el-checkbox-group v-model="selectedLevels" size="small">
            <el-checkbox-button v-for="level in allLevels" :key="level" :value="level">
              <span :class="`level-badge level-${level.toLowerCase()}`">{{ level }}</span>
            </el-checkbox-button>
          </el-checkbox-group>
        </div>
        <div class="filter-group">
          <span class="filter-label">模块筛选：</span>
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
          <span class="filter-label">搜索：</span>
          <el-input
            v-model="searchKeyword"
            placeholder="搜索日志内容"
            clearable
            size="small"
            style="width: 220px"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>
        <div class="filter-group">
          <span class="filter-label">显示条数：</span>
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
          <span v-else-if="!autoFollowLogs" class="log-status-indicator">正在查看历史日志</span>
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
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Refresh, Delete, VideoPlay, VideoPause, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { logApi } from '../api'

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
  Prekikoeru: '#8b5cf6',
  '关联查询': '#a855f7',
  '字幕抓取': '#7c3aed',
  CONFIG: '#06b6d4',
  'CONFIG SAVE': '#0891b2',
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
  logs.value.forEach(log => {
    if (log.module) modules.add(log.module)
  })
  return Array.from(modules).sort()
})

const filteredLogs = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  return logs.value.filter(log => {
    if (!selectedLevels.value.includes(log.level)) return false
    if (selectedModules.value.length > 0 && !selectedModules.value.includes(log.module)) return false
    if (!keyword) return true
    return (
      String(log.message || '').toLowerCase().includes(keyword) ||
      String(log.module || '').toLowerCase().includes(keyword)
    )
  })
})

function getModuleColor(moduleName) {
  return moduleColors[moduleName] || '#6b7280'
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
    await ElMessageBox.confirm('确定要清空当前页面日志显示吗？这不会删除后端日志文件。', '确认', {
      type: 'warning'
    })
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
  max-width: 1400px;
  margin: 0 auto;
}

.page-title {
  margin: 0 0 24px;
  font-size: 28px;
  font-weight: 600;
  color: #1e293b;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-section {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  padding: 12px 16px;
  background-color: #f8fafc;
  border-radius: 8px;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-label {
  font-size: 14px;
  color: #64748b;
  white-space: nowrap;
}

.filter-stats {
  margin-left: auto;
  font-size: 13px;
  color: #94a3b8;
}

.level-badge {
  padding: 2px 6px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 4px;
}

.level-debug { background-color: #e2e8f0; color: #475569; }
.level-info { background-color: #dbeafe; color: #1d4ed8; }
.level-warning { background-color: #fef3c7; color: #b45309; }
.level-error { background-color: #fee2e2; color: #b91c1c; }

.log-container {
  height: 620px;
  overflow-y: auto;
  padding: 12px 16px 16px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: #e2e8f0;
  background-color: #1e293b;
  border-radius: 8px;
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
  padding-bottom: 8px;
  background: linear-gradient(to bottom, rgba(30, 41, 59, 0.98), rgba(30, 41, 59, 0.86));
}

.log-status-indicator {
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background-color: #3b82f6;
  border-radius: 4px;
}

.log-status-indicator.paused {
  background-color: #f59e0b;
}

.log-status-indicator.active {
  background-color: #10b981;
}

.log-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 3px 0;
}

.log-time {
  flex-shrink: 0;
  color: #64748b;
  white-space: nowrap;
}

.log-level {
  min-width: 50px;
  padding: 0 4px;
  font-size: 11px;
  font-weight: 700;
  text-align: center;
  white-space: nowrap;
  border-radius: 3px;
  flex-shrink: 0;
}

.log-debug .log-level { background-color: #374151; color: #9ca3af; }
.log-info .log-level { background-color: #1e3a5f; color: #60a5fa; }
.log-warning .log-level { background-color: #78350f; color: #fbbf24; }
.log-error .log-level { background-color: #7f1d1d; color: #f87171; }

.log-module {
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 500;
  color: #fff;
  border-radius: 3px;
  flex-shrink: 0;
}

.log-message {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

.log-debug { opacity: 0.72; }
.log-warning { background-color: rgba(245, 158, 11, 0.1); }
.log-error { background-color: rgba(239, 68, 68, 0.1); }
</style>
