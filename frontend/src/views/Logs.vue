<template>
  <div class="logs-page max-w-[1480px] mx-auto flex flex-col gap-0">
    <AppPageHeader
      :icon="Terminal"
      icon-color="var(--km-nav-logs-icon)"
      title="系统日志"
      subtitle="实时监控应用运行输出，支持级别过滤、模块筛选与关键词搜索。"
    >
        <span class="logs-count-chip inline-flex items-center gap-1 px-3 py-1 border border-slate-200 rounded-full bg-slate-50 text-xs text-slate-500">
          <span class="font-bold text-blue-500">{{ filteredLogs.length }}</span>
          <span class="text-slate-300">/</span>
          <span class="font-semibold text-slate-600">{{ logs.length }}</span> 条
        </span>

        <button
          type="button"
          class="logs-toolbar-btn"
          :class="isPaused ? 'is-success' : 'is-warning'"
          @click="togglePause"
        >
          <component :is="isPaused ? Play : PauseCircle" :size="13" />
          {{ isPaused ? '恢复刷新' : '暂停刷新' }}
        </button>

        <button type="button" class="logs-toolbar-btn is-default" @click="refreshCurrentLogs">
          <RefreshCw :size="13" />
          刷新
        </button>

        <button type="button" class="logs-toolbar-btn is-default" @click="exportFilteredLogs">
          <Download :size="13" />
          导出筛选结果
        </button>

        <button type="button" class="logs-toolbar-btn is-default" @click="copyVisibleLogs">
          <Copy :size="13" />
          复制可见窗口
        </button>

        <button type="button" class="logs-toolbar-btn is-default" @click="openLogManager">
          <Settings2 :size="13" />
          日志管理
        </button>

        <button type="button" class="logs-toolbar-btn is-danger" @click="clearLogs">
          <AppLottieIcon :src="deleteIconAnimation" :size="26" tone="danger" />
          清空视图
        </button>
    </AppPageHeader>

    <div class="logs-toolbar flex flex-wrap items-center gap-3 px-4 py-3 mb-3.5 border border-slate-200 rounded-2xl bg-white shadow-sm">
      <div class="flex items-center gap-2">
        <span class="logs-toolbar-label text-[12.5px] font-semibold text-slate-500 whitespace-nowrap">级别</span>
        <div class="flex gap-1.5">
          <button
            v-for="level in allLevels"
            :key="level"
            type="button"
            class="log-level-pill"
            :class="[`is-${level.toLowerCase()}`, { 'is-active': isLevelSelected(level) }]"
            @click="toggleLevel(level)"
          >
            <span class="log-level-dot" />
            {{ level }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <span class="logs-toolbar-label text-[12.5px] font-semibold text-slate-500 whitespace-nowrap">模块</span>
        <el-select
          v-model="selectedModules"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="全部模块"
          clearable
          size="small"
          style="min-width: 150px; max-width: 220px"
        >
          <el-option v-for="mod in availableModules" :key="mod" :label="mod" :value="mod" />
        </el-select>
      </div>

      <div class="relative flex-1 min-w-[300px] max-w-[540px] flex items-center">
        <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
        <input
          ref="searchInputRef"
          v-model="searchKeyword"
          type="text"
          class="logs-search-input w-full h-[32px] pl-7 border border-slate-200 rounded-lg bg-white text-[13px] text-slate-800 outline-none placeholder-slate-400 transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
          :class="isFullSearch ? 'pr-[134px]' : 'pr-20'"
          :placeholder="isFullSearch ? '全历史检索关键词（回车立即检索）' : '搜索当前日志内容…'"
          @input="onSearchInput"
          @keydown.enter.prevent="doFullSearch(true)"
        />
        <button
          v-if="searchKeyword"
          type="button"
          class="logs-search-clear absolute right-[86px] top-1/2 -translate-y-1/2 text-[11px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 hover:bg-slate-200 transition"
          @click="clearSearchKeyword"
        >清空</button>
        <button
          v-if="isFullSearch"
          type="button"
          class="logs-search-submit absolute right-1 top-1/2 inline-flex h-[26px] min-w-[58px] -translate-y-1/2 items-center justify-center gap-1 whitespace-nowrap rounded-md border px-3 text-[12px] font-semibold leading-none transition active:-translate-y-1/2 active:scale-95"
          @click="doFullSearch(true)"
        >检索</button>
      </div>

      <div class="flex items-center gap-2 ml-auto" :class="{ 'opacity-50 pointer-events-none': isFullSearch }">
        <span class="logs-toolbar-label text-[12.5px] font-semibold text-slate-500 whitespace-nowrap">条数</span>
        <AppDropdown
          v-model="logLimit"
          :options="logLimitOptions"
          :width="110"
          :menu-min-width="130"
          :show-trigger-badge="false"
          @update:model-value="onLimitChange"
        />
      </div>

      <button
        type="button"
        class="logs-toggle-btn"
        :class="{ 'is-active': isFullSearch }"
        @click="toggleFullSearch"
      >
        <FileSearch :size="12" />
        {{ isSearchLoading ? '检索中…' : isFullSearch ? '全历史模式' : '搜索全历史' }}
        <span v-if="fullSearchTotal > 0" class="text-[10px] text-indigo-400">{{ fullSearchTotal }}</span>
      </button>

      <button
        type="button"
        class="logs-toggle-btn"
        :class="{ 'is-active is-compact': compactProcessLogs }"
        @click="toggleCompactProcessLogs"
      >
        <SlidersHorizontal :size="12" />
        {{ compactProcessLogs ? '精简过程已开' : '精简过程' }}
        <span v-if="compactProcessLogs && hiddenProcessNoiseCount > 0" class="text-[10px] text-emerald-500">{{ hiddenProcessNoiseCount }}</span>
      </button>

      <div class="logs-status-row w-full flex flex-wrap items-center gap-2">
        <span class="logs-status-chip is-info">模式 {{ lastFetchMode }}</span>
        <span class="logs-status-chip is-success">本次 {{ lastFetchMs }}ms</span>
        <span
          v-if="lastSearchScanMb > 0"
          class="logs-status-chip is-warning"
          title="后端实际扫描的字节数（MB），跨主日志 + 备份"
        >扫描 {{ lastSearchScanMb }}MB</span>
        <span
          v-if="lastSearchStoppedEarly"
          class="logs-status-chip is-warning"
          title="本次搜索触顶（5 万匹配 / 96MB 扫描预算 / 单页 1000 条），未扫到全部历史"
        >已截断</span>
        <span class="logs-status-chip is-muted">快捷键 Ctrl+K 搜索 · Ctrl+R 刷新 · Ctrl+Shift+C 复制可见</span>
      </div>
    </div>

    <div class="system-log-shell" :class="{ 'is-search-mode': isFullSearch }">
      <SystemLogTerminal
        title="system.log"
        :subtitle="terminalSubtitle"
        :lines="terminalLines"
        :status="terminalStatus"
        :error-message="terminalErrorMessage"
        :max-height="terminalMaxHeight"
        @clear="clearLogs"
        @reconnect="reconnectLogStream"
      />

      <div v-if="isFullSearch" class="border-t border-white/10 px-4 py-2 bg-black/20 flex items-center gap-2">
        <button
          type="button"
          class="px-3 py-1.5 rounded border border-slate-400/40 bg-slate-500/10 text-slate-200 text-xs font-semibold hover:bg-slate-500/20 transition disabled:opacity-40 disabled:cursor-not-allowed"
          :disabled="isSearchLoading || fullSearchPageStart <= 0"
          @click="loadPrevFullSearchPage"
        >上一页</button>
        <button
          type="button"
          class="px-3 py-1.5 rounded border border-indigo-400/50 bg-indigo-400/10 text-indigo-200 text-xs font-semibold hover:bg-indigo-400/20 transition disabled:opacity-40 disabled:cursor-not-allowed"
          :disabled="isSearchLoading || !fullSearchHasMore"
          @click="loadNextFullSearchPage"
        >下一页</button>
        <span class="text-[11px] text-slate-400 ml-1">页起点 {{ fullSearchPageStart }} / 总匹配 {{ fullSearchTotal }}</span>
      </div>
    </div>

    <el-dialog
      v-model="logManagerVisible"
      class="log-manager-dialog"
      modal-class="log-manager-overlay"
      width="680px"
      :close-on-click-modal="false"
      :z-index="2200"
      :show-close="false"
      append-to-body
    >
      <div class="log-manager-shell">
        <div class="log-manager-header">
          <div class="flex min-w-0 items-center gap-3">
            <div class="log-manager-icon">
              <Settings2 :size="18" />
            </div>
            <div class="min-w-0">
              <h3 class="truncate text-[15px] font-bold text-slate-950">日志管理</h3>
              <p class="mt-0.5 truncate text-[12px] text-slate-500">查看日志占用，执行轮转、清理和应急瘦身。</p>
            </div>
          </div>
          <button type="button" class="log-manager-close" @click="logManagerVisible = false" title="关闭">
            <X :size="16" />
          </button>
        </div>

        <div class="log-manager-body">
          <div class="grid grid-cols-3 gap-3">
            <div class="log-stat-card">
              <div class="text-[11px] font-semibold text-slate-500">主日志大小</div>
              <div class="mt-1 text-[18px] font-extrabold text-slate-900">{{ formatLogBytes(logInfo?.main_bytes) }}</div>
            </div>
            <div class="log-stat-card">
              <div class="text-[11px] font-semibold text-slate-500">备份合计</div>
              <div class="mt-1 text-[18px] font-extrabold text-slate-900">{{ formatLogBytes(logInfo?.backup_bytes) }}</div>
            </div>
            <div class="log-stat-card">
              <div class="text-[11px] font-semibold text-slate-500">总占用</div>
              <div class="mt-1 text-[18px] font-extrabold text-slate-900">{{ formatLogBytes(logInfo?.total_bytes) }}</div>
            </div>
          </div>

          <div class="log-file-panel">
            <div class="log-file-head">
              <span>文件</span>
              <span>大小</span>
              <span>最后修改</span>
            </div>
            <div class="max-h-[260px] overflow-auto">
              <div v-if="logInfoLoading" class="px-4 py-8 text-center text-[13px] text-slate-400">加载中…</div>
              <div
                v-for="file in (logInfo?.files || [])"
                :key="file.path"
                class="log-file-row"
              >
                <div class="min-w-0 font-mono text-[12px] font-semibold text-slate-700">
                  <span class="inline-flex min-w-0 items-center gap-1.5">
                    <HardDrive :size="13" class="shrink-0 text-slate-400" />
                    <span class="truncate">{{ file.name }}</span>
                    <span v-if="file.is_main" class="log-file-badge is-main">主</span>
                    <span v-else-if="file.is_backup" class="log-file-badge is-backup">备份</span>
                  </span>
                </div>
                <div class="text-right font-semibold text-slate-700">{{ formatLogBytes(file.size_bytes) }}</div>
                <div class="text-right text-slate-500">{{ formatLogTime(file.modified_ts) }}</div>
              </div>
              <div v-if="!logInfoLoading && !(logInfo?.files || []).length" class="px-4 py-8 text-center text-[13px] text-slate-400">暂无日志文件</div>
            </div>
          </div>

          <div class="log-policy-card text-[12px] leading-5 text-slate-600">
            <div class="mb-1 font-bold text-slate-800">轮转策略</div>
            单文件上限 <span class="font-bold">{{ logInfo?.max_mb_per_file ?? 20 }} MB</span>，最多保留
            <span class="font-bold">{{ logInfo?.backup_count ?? 5 }}</span> 份备份，理论上限
            <span class="font-bold">{{ ((logInfo?.max_mb_per_file ?? 20) * ((logInfo?.backup_count ?? 5) + 1)).toFixed(0) }} MB</span>。
            可通过环境变量 <code>KIKOERUMANAGER_LOG_MAX_MB</code> / <code>KIKOERUMANAGER_LOG_BACKUPS</code> 调整。
          </div>

          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="log-manager-action-btn is-default"
              :disabled="cleanupLoading"
              @click="loadLogInfo"
            >
              <RefreshCw :size="13" />刷新
            </button>
            <button
              type="button"
              class="log-manager-action-btn is-success"
              :disabled="cleanupLoading"
              @click="runLogCleanup('rotate')"
              title="把当前 app.log 滚到 .1，新日志写入空文件；不删除任何内容"
            >
              <RefreshCw :size="13" />立即轮转
            </button>
            <button
              type="button"
              class="log-manager-action-btn is-warning"
              :disabled="cleanupLoading"
              @click="runLogCleanup('purge_backups')"
              title="删除所有 app.log.N 备份文件"
            >
              <Trash2 :size="13" />清理所有备份
            </button>
            <button
              type="button"
              class="log-manager-action-btn is-warning"
              :disabled="cleanupLoading"
              @click="runLogCleanup('truncate')"
              title="把主日志保留最近 2MB，丢弃前面所有内容（应急救急）"
            >
              <Trash2 :size="13" />截断主日志到 2MB
            </button>
            <button
              type="button"
              class="log-manager-action-btn is-danger"
              :disabled="cleanupLoading"
              @click="runLogCleanup('rotate_and_purge')"
              title="先轮转再清理全部备份；当前 app.log 会被清空，旧日志将无法恢复"
            >
              <Trash2 :size="13" />一键瘦身
            </button>
          </div>
        </div>

        <div class="log-manager-footer">
          <button
            type="button"
            class="log-manager-action-btn is-default"
            @click="logManagerVisible = false"
          >关闭</button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import {
  Terminal,
  Copy,
  Download,
  FileSearch,
  HardDrive,
  PauseCircle,
  Play,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import { logApi, redirectIfSecurityGateExpired } from '../api'
import AppLottieIcon from '../components/common/AppLottieIcon.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppDropdown from '../components/common/AppDropdown.vue'
import SystemLogTerminal from '../components/common/SystemLogTerminal.vue'
import deleteIconAnimation from '../assets/anime/Delete icon animation.lottie'

const LOG_FLUSH_INTERVAL = 48
const LOG_STREAM_RECONNECT_MS = 2500
const COMPACT_PROCESS_LOGS_KEY = 'kikoerumanager.logs.compact_process_noise'
const LOG_BLOCK_PREFIX = '__KIKOERUMANAGER_LOG_BLOCK__'
const TASK_PROGRESS_STALE_MS = 2 * 60 * 1000

const logs = shallowRef([])
const isPaused = ref(false)
const logLimit = ref(300)

// 「条数」下拉选项。1000 条对实际排查日志足够，需要更多请用"搜索全历史"或"导出筛选结果"。
const logLimitOptions = [
  { value: 100, label: '100 条' },
  { value: 300, label: '300 条' },
  { value: 500, label: '500 条' },
  { value: 1000, label: '1000 条' },
]
const selectedLevels = ref(['INFO', 'WARNING', 'ERROR'])
const selectedModules = ref([])
const searchKeyword = ref('')
const searchInputRef = ref(null)
const compactProcessLogs = ref(localStorage.getItem(COMPACT_PROCESS_LOGS_KEY) !== '0')

const allLevels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']

let lastLogSignature = ''
let nextOffset = -1
let logIdCounter = 0
let searchDebounceTimer = null
let logEventSource = null
let reconnectTimer = null
let streamFlushTimer = null
let pendingStreamLines = []

const incrementalCount = ref(0)
const lastFetchMs = ref(0)
const lastFetchMode = ref('idle')
const terminalStatus = ref('idle')
const terminalErrorMessage = ref('')
const isFullSearch = ref(false)
const fullSearchTotal = ref(0)
const fullSearchCursor = ref(0)
const fullSearchHasMore = ref(false)
const fullSearchPageStart = ref(0)
const FULL_SEARCH_PAGE_SIZE = 500
const MIN_FULL_SEARCH_KEYWORD_LENGTH = 2
const isSearchLoading = ref(false)
let fullSearchRequestSeq = 0

const parseCache = new Map()
// 后端搜索状态（用于头部小标签展示，不进入 render path 修改）
const lastSearchScanMb = ref(0)
const lastSearchStoppedEarly = ref(false)

const availableModules = computed(() => {
  const modules = new Set()
  for (const log of logs.value) {
    if (log.module) modules.add(log.module)
  }
  return Array.from(modules).sort()
})

const filteredLogs = computed(() => {
  const terms = searchTerms.value
  const lvlSet = new Set(selectedLevels.value)
  const moduleSet = selectedModules.value.length
    ? new Set(selectedModules.value)
    : null
  const termCount = terms.length
  // 全历史搜索模式下，logs.value 已经是后端按整行匹配过滤过的结果。
  // 前端如果再用 messageLower / moduleLower 过滤，会把后端命中但解析后
  // message 部分不含关键字的行（例如关键字命中在时间戳 / 路径 / access log）
  // 重新过滤掉，导致出现"X 总计 0 匹配"。这里在全历史模式下放行 keyword，
  // 仅保留级别 / 模块过滤，避免二次过滤造成搜索失效。
  const skipKeywordFilter = isFullSearch.value
  const taskEndById = collectTaskEndState(logs.value)
  const newestLogMs = getNewestLogTimeMs(logs.value)
  const candidates = []
  const latestProgressByTask = new Map()
  const firstProgressMsByTask = new Map()

  logs.value.forEach((log, index) => {
    if (!lvlSet.has(log.level)) return false
    if (moduleSet && !moduleSet.has(log.module)) return false
    const taskProgress = parseTaskProgressLog(log, index)
    if (taskProgress) {
      if (taskProgress.timestampMs && !firstProgressMsByTask.has(taskProgress.taskId)) {
        firstProgressMsByTask.set(taskProgress.taskId, taskProgress.timestampMs)
      }
      latestProgressByTask.set(taskProgress.taskId, taskProgress)
      candidates.push({ type: 'task-progress', log, taskProgress })
      return false
    }
    if (compactProcessLogs.value && isProcessNoiseLog(log)) return false
    if (!termCount || skipKeywordFilter) {
      candidates.push({ type: 'log', log })
      return true
    }
    // 消费解析阶段预先缓存的 lower-case（messageLower / moduleLower / rawLineLower），
    // 这里不再 toLowerCase，单次过滤开销从 O(n·m) 降到 O(n·k)。
    if (!matchesSearchTerms(log, terms)) {
      return false
    }
    candidates.push({ type: 'log', log })
    return true
  })

  for (const progress of latestProgressByTask.values()) {
    const startedMs = firstProgressMsByTask.get(progress.taskId) || progress.timestampMs || 0
    const endedMs = progress.timestampMs || startedMs
    progress.startedMs = startedMs
    progress.durationMs = Math.max(0, endedMs - startedMs)
    progress.durationLabel = formatProgressDuration(progress.durationMs)
  }

  return candidates.flatMap((entry) => {
    if (entry.type !== 'task-progress') return [entry.log]

    const latest = latestProgressByTask.get(entry.taskProgress.taskId)
    if (!latest || latest.order !== entry.taskProgress.order) return []
    if (isTaskProgressEnded(entry.taskProgress, taskEndById)) return []
    if (isTaskProgressStale(entry.taskProgress, newestLogMs)) return []
    return [buildTaskProgressTerminalLog(entry.log, entry.taskProgress)]
  })
})

const hiddenProcessNoiseCount = computed(() => {
  if (!compactProcessLogs.value) return 0
  const lvlSet = new Set(selectedLevels.value)
  const moduleSet = selectedModules.value.length
    ? new Set(selectedModules.value)
    : null
  let count = 0
  for (const log of logs.value) {
    if (!lvlSet.has(log.level)) continue
    if (moduleSet && !moduleSet.has(log.module)) continue
    if (parseTaskProgressLog(log)) continue
    if (isProcessNoiseLog(log)) count += 1
  }
  return count
})

const terminalLines = computed(() => filteredLogs.value.map((log) => ({
  id: log.key,
  time: log.time,
  level: log.level,
  source: log.module || inferSourceFromLevel(log.level),
  kind: log.kind || 'log',
  progress: log.progress ?? null,
  taskProgress: log.taskProgress || null,
  message: log.displayMessage || log.message,
  fullMessage: log.fullMessage || log.message,
  rawLine: log.rawLine,
  isTruncated: Boolean(log.isTruncated),
})))

const terminalSubtitle = computed(() => {
  if (isFullSearch.value) {
    return `全历史检索 · ${fullSearchPageStart.value} / ${fullSearchTotal.value || filteredLogs.value.length}`
  }
  if (isPaused.value) return `已暂停 · ${filteredLogs.value.length} 条匹配 / ${logs.value.length} 条`
  return `${lastFetchMode.value} · ${filteredLogs.value.length} 条匹配 / ${logs.value.length} 条 · offset ${nextOffset >= 0 ? nextOffset : 0}`
})

const terminalMaxHeight = computed(() => {
  if (typeof window === 'undefined') return 620
  return Math.max(420, Math.min(760, window.innerHeight - 330))
})

const searchTerms = computed(() =>
  searchKeyword.value
    .toLowerCase()
    .split(/[\s,，]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 8)
)

// 缓存上限大幅缩小（OOM 修复）：
// 旧值 logLimit*8 / logLimit*4 在 logLimit=2000 时上限 16000 / 8000 条目，
// 单条 parsed 含 4 份字符串副本（含 4096 字节 rawLineLower），峰值可达数百 MB。
// 新值按 1.5x 冗余足够覆盖滚动 + 切刷新带来的旧条目重用，超出立即 trim。
const parseCacheMax = computed(() => Math.max(1500, Math.floor(logLimit.value * 1.5)))

function inferSourceFromLevel(level) {
  const normalized = String(level || '').toUpperCase()
  if (normalized === 'ERROR') return 'error'
  if (normalized === 'WARNING') return 'warn'
  if (normalized === 'DEBUG') return 'debug'
  return 'system'
}

function isLevelSelected(level) {
  return selectedLevels.value.includes(level)
}

function toggleLevel(level) {
  if (selectedLevels.value.includes(level)) {
    if (selectedLevels.value.length === 1) return
    selectedLevels.value = selectedLevels.value.filter((l) => l !== level)
  } else {
    selectedLevels.value = [...selectedLevels.value, level]
  }
  if (isFullSearch.value) onSearchInput()
}

function toggleCompactProcessLogs() {
  compactProcessLogs.value = !compactProcessLogs.value
  localStorage.setItem(COMPACT_PROCESS_LOGS_KEY, compactProcessLogs.value ? '1' : '0')
}

function clampPercent(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 0
  return Math.max(0, Math.min(100, Math.round(numeric)))
}

function matchesSearchTerms(log, terms) {
  const msg = log.messageLower || ''
  const mod = log.moduleLower || ''
  const raw = log.rawLineLower || ''
  for (let i = 0; i < terms.length; i += 1) {
    const term = terms[i]
    if (!msg.includes(term) && !mod.includes(term) && !raw.includes(term)) return false
  }
  return true
}

function formatProgressTime(value) {
  const text = String(value || '')
  if (!text) return '--:--:--'
  const dateMatch = text.match(/\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2}:\d{2})/)
  if (dateMatch) return dateMatch[1]
  return text.length > 8 ? text.slice(0, 8) : text
}

function formatProgressDuration(value) {
  const ms = Math.max(0, Number(value) || 0)
  const totalSeconds = Math.floor(ms / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const pad = (part) => String(part).padStart(2, '0')
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
}

function parseLogTimeMs(value) {
  const text = String(value || '').trim()
  if (!text) return 0
  const normalized = text.includes('T') ? text : text.replace(' ', 'T')
  const date = new Date(normalized)
  const ms = date.getTime()
  return Number.isFinite(ms) ? ms : 0
}

function getNewestLogTimeMs(list) {
  let newest = 0
  for (const log of Array.isArray(list) ? list : []) {
    const ms = parseLogTimeMs(log?.time)
    if (ms > newest) newest = ms
  }
  return newest
}

function classifyProgressTone(text, progress, level) {
  const normalizedLevel = String(level || '').toUpperCase()
  if (normalizedLevel === 'ERROR' || /失败|错误|异常|Traceback|Exception|RuntimeError/.test(text)) return 'error'
  if (/暂停|已暂停|等待/.test(text)) return 'waiting'
  if (/取消|已取消|cancel/i.test(text)) return 'paused'
  if (progress >= 100 || /完成|成功|已归档|已移动/.test(text)) return 'success'
  return 'processing'
}

function classifyProgressPhase(text, moduleName) {
  if (/解压|7z|unar|压缩包解压/.test(text)) return '解压'
  if (/归档|已处理目录|processed/i.test(text)) return '归档'
  if (/移动|搬移|move/i.test(text)) return '移动'
  if (/上传|写入远端|群晖/.test(text)) return '上传'
  if (/下载|拉取|同步/.test(text)) return '下载'
  if (/重命名|改名/.test(text)) return '重命名'
  if (/分类|整理/.test(text)) return '整理'
  if (/清理|删除/.test(text)) return '清理'
  if (/扫描|检查|验证|预检/.test(text)) return '检查'
  return moduleName || '任务'
}

function buildProgressDetail(step) {
  const text = String(step || '').replace(/\s+/g, ' ').trim()
  return text
}

function parseTaskProgressLog(log, order = 0) {
  const message = String(log?.message || '')
  const match = message.match(/任务\s+([0-9a-fA-F-]{8,36})\s*[:：]\s*(.+?)\s*[（(]\s*(\d{1,3})\s*%\s*[)）]\s*$/)
  if (!match) return null

  const taskId = match[1]
  const step = match[2].trim()
  const progress = clampPercent(match[3])
  const context = `${log?.module || ''} ${step}`
  const tone = classifyProgressTone(context, progress, log?.level)
  const phase = classifyProgressPhase(context, log?.module || '')

  return {
    id: taskId,
    taskId,
    shortId: taskId.slice(0, 8),
    title: `任务 ${taskId.slice(0, 8)}`,
    phase,
    detail: buildProgressDetail(step),
    progress,
    tone,
    timestampMs: parseLogTimeMs(log?.time),
    updatedAt: log?.time || '',
    updatedLabel: formatProgressTime(log?.time),
    order,
  }
}

function parseTaskEndLog(log, order = 0) {
  const message = String(log?.message || '')
  const patterns = [
    { re: /任务\s+([0-9a-fA-F-]{8,36})\s+已被用户取消/, tone: 'paused' },
    { re: /任务\s+([0-9a-fA-F-]{8,36}).*(?:已取消|取消完成|被取消)/, tone: 'paused' },
    { re: /任务\s+([0-9a-fA-F-]{8,36}).*(?:任务失败|处理失败|失败)/, tone: 'error' },
    { re: /任务\s+([0-9a-fA-F-]{8,36}).*(?:任务完成|处理完成|成功完成)/, tone: 'success' },
    { re: /任务\s+([0-9a-fA-F-]{8,36})\s+状态更新为:\s*(completed|failed|cancelled|canceled|paused)/i, tone: '' },
  ]
  for (const item of patterns) {
    const match = message.match(item.re)
    if (!match) continue
    let tone = item.tone
    if (!tone) {
      const status = String(match[2] || '').toLowerCase()
      if (status === 'completed') tone = 'success'
      else if (status === 'failed') tone = 'error'
      else tone = 'paused'
    }
    return {
      taskId: match[1],
      tone,
      order,
      timestampMs: parseLogTimeMs(log?.time),
    }
  }
  return null
}

function collectTaskEndState(list) {
  const result = new Map()
  ;(Array.isArray(list) ? list : []).forEach((log, index) => {
    const state = parseTaskEndLog(log, index)
    if (!state) return
    const previous = result.get(state.taskId)
    if (!previous || state.order >= previous.order) {
      result.set(state.taskId, state)
    }
  })
  return result
}

function isTaskProgressEnded(progress, taskEndById) {
  const endState = taskEndById.get(progress.taskId)
  return Boolean(endState && endState.order > progress.order)
}

function isTaskProgressStale(progress, newestLogMs) {
  if (!newestLogMs || !progress.timestampMs) return false
  return newestLogMs - progress.timestampMs > TASK_PROGRESS_STALE_MS
}

function buildTaskProgressTerminalLog(log, progress) {
  return {
    ...log,
    key: `${log.key}-task-progress`,
    kind: 'task-progress',
    module: progress.phase,
    message: progress.detail,
    displayMessage: progress.detail,
    progress: progress.progress,
    taskProgress: progress,
  }
}

function isProcessNoiseLog(log) {
  const level = String(log?.level || '').toUpperCase()
  if (level === 'WARNING' || level === 'ERROR') return false

  const moduleName = String(log?.module || '')
  const message = String(log?.message || '')
  const raw = String(log?.rawLine || '')
  const text = `${moduleName}\n${message}\n${raw}`

  if (/任务失败|失败原因|Traceback|Exception|RuntimeError|解压失败|归档失败|无正确密码|密码错误|磁盘空间不足|文件乱码/.test(text)) {
    return false
  }

  return [
    /执行7z命令/,
    /解压中\s*\d+%/,
    /准备解压|开始解压|解压子进程已启动|验证解压完整性|解压完整性验证完成/,
    /检查嵌套压缩包|发现嵌套压缩包|解压嵌套压缩包|嵌套解压密码候选|成功解压嵌套压缩包|嵌套压缩包解压成功|已删除嵌套压缩包/,
    /外层压缩包解压成功|解压成功，使用|解压了\s*\d+\s*个嵌套压缩包/,
    /密码.*探测通过|密码候选|尝试.*密码|使用.*密码|密码来源|指定密码/,
    /归档压缩包|压缩包已归档|检测到.*分卷.*归档|已记录压缩包归档信息|更新压缩包归档记录/,
    /移动到媒体库|移动到:|字幕文件夹已移动|开始移动|移动完成/,
    /准备创建处理任务|任务已调度|\[Watcher\]\s*开始处理文件|开始处理文件|等待文件稳定|文件已稳定|规范化后路径|文件规范化/,
    /目录文件列表|匹配分卷|最终分卷列表|魔数检测命中|可能为分卷|等待后检测|孤立分卷|分卷模式|找到分卷/,
    /远程搜索(绕过缓存|命中缓存|写入缓存|开始轮询等待|状态轮询|复用进行中的请求|开始:|任务已创建|结果:|耗时.*真空|秒回空结果|秒回空结果.*重试)/,
    /远程库存搜索:\s*library=|远程 RJ 搜索提前命中/,
    /完整配置内容|原始配置|用户配置路径|分类规则\d+|过滤规则\d+|路径映射规则\d+|Kikoeru服务器配置|ASMR配置/,
    /接收到配置保存请求|保存配置请求: path=|配置已成功保存并原子更新|配置已保存: keys=\[/,
    /\[Kikoeru\].*(登录URL|响应Content-Type|登录响应keys|请求 URL|请求头|响应状态|响应数据)/,
    /\[ASMR\].*(获取文件列表|第一个项目结构|第一个文件夹名称|第一个子项目结构|第一个子项目摘要|第一个文件摘要|解析后第一个文件|构建下载链接|下载文件 \(\d+\/)/,
    /\[筛选\].*(共有 \d+ 条筛选规则|规则\d+|前5个文件名示例|文件被规则|title=|path=)/,
    /作品 .* 共有 \d+ 个文件|筛选后剩余 \d+ 个文件/,
    /\[SynologyUpload\].*(命中已缓存成功变体|尝试变体|变体失败|检测到可恢复网络中断)/,
    /\[\/api\/conflicts\].*(解析参数完成|数据查询完成|详情组装完成|请求完成|db_query|phase1|phase2|items)/,
    /\[字幕补配\].*(目标目录候选收敛到最里层 RJ 目录|目标目录搜索库存列表|开始搜索目标目录|目标目录搜索结果|目标目录搜索完成|远程目标目录未命中，等待后重试|命中目录规则直查:.*path=)/,
  ].some((pattern) => pattern.test(text))
}

function onSearchInput() {
  if (!isFullSearch.value) return
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    doFullSearch()
  }, 500)
}

function clearSearchKeyword() {
  searchKeyword.value = ''
  if (isFullSearch.value) {
    doFullSearch(true)
  }
}

function parseModule(message, rawLine) {
  const bracketMatch = rawLine.match(/\[([^\]]+)\]/)
  if (bracketMatch) {
    const tag = bracketMatch[1]
    if (tag.includes('KikoeruManager') || tag.includes('CONFIG') || tag.includes('RENAME') || tag.includes('RJ字幕')) {
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

function trimMapByOldest(map, maxSize, trimCount) {
  if (map.size <= maxSize) return
  let removed = 0
  for (const key of map.keys()) {
    map.delete(key)
    removed += 1
    if (removed >= trimCount) break
  }
}

function buildDisplayMessage(message) {
  const text = String(message || '')
  return { displayMessage: text, isTruncated: false }
}

function parseLogLine(line) {
  if (parseCache.has(line)) {
    return parseCache.get(line)
  }
  // OOM 修复：trim 一次清掉一半（之前 1/4 太保守，map 长期贴着 ceil 触发频繁
  // micro-trim 但实际没腾出足够空间）。
  trimMapByOldest(parseCache, parseCacheMax.value, Math.max(300, Math.floor(parseCacheMax.value / 2)))

  // 统一构造解析对象；预先缓存 lower-case 版本，避免 filteredLogs 过滤时每帧
  // 都重复 toLowerCase（此前是主要的 filter 卡点）。
  // rawLineLower 用于"关键字命中时间戳 / 模块短标记 / access log 路径"的兜底匹配。
  //
  // OOM 修复：rawLineLower 长度阈值从 4096 收紧到 1024 字节。
  // 长 traceback 日志（典型 2-5 KB）不再缓存 lower 副本——这种长行也几乎不可能
  // 用作"raw 兜底搜索目标"（搜索关键词通常匹配在 message 部分），而 messageLower
  // 一直保留，普通搜索仍然命中。这里直接砍 lower 副本能省掉 logLimit 条 × 平均 2KB
  // = 几 MB 内存。
  const RAW_LOWER_LIMIT = 1024
  const buildParsed = (time, level, message, extra = {}) => {
    const rawSource = extra.rawLine ?? line
    const fullSource = extra.fullMessage ?? ''
    const mod = parseModule(message, String(rawSource || line || ''))
    const levelUpper = (level || 'INFO').toUpperCase()
    const safeRaw = typeof rawSource === 'string' ? rawSource : String(rawSource || '')
    const rawLower = safeRaw.length && safeRaw.length <= RAW_LOWER_LIMIT ? safeRaw.toLowerCase() : ''
    const parsed = {
      rawLine: safeRaw,
      fullMessage: fullSource || message,
      rawLineLower: rawLower,
      time: time || '',
      level: levelUpper,
      module: mod,
      message,
      messageLower: (message || '').toLowerCase(),
      moduleLower: (mod || '').toLowerCase(),
      ...buildDisplayMessage(message),
    }
    parseCache.set(line, parsed)
    return parsed
  }

  if (typeof line === 'string' && line.startsWith(LOG_BLOCK_PREFIX)) {
    try {
      const payload = JSON.parse(line.slice(LOG_BLOCK_PREFIX.length))
      return buildParsed(
        payload.time || '',
        payload.level || 'ERROR',
        payload.message || '异常堆栈已折叠，点击查看完整',
        {
          rawLine: payload.raw_line || payload.full_message || line,
          fullMessage: payload.full_message || payload.raw_line || '',
        },
      )
    } catch {
      // 块格式异常时按普通日志展示，避免日志页被单条坏数据打断。
    }
  }

  let match = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+\S+\s+-\s+(.+)$/)
  if (match) return buildParsed(match[1], match[2], match[3])

  match = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+-\s+\S+\s+-\s+(\w+)\s+-\s+(.+)$/)
  if (match) return buildParsed(match[1], match[2], match[3])

  return buildParsed('', 'INFO', line)
}

function parseLogLines(lines, keyPrefix = '') {
  // 改用"键前缀 + 单调自增 id"作为 Vue :key，干掉原先 FNV 哈希的逐字符计算。
  // 同时避免长消息生成几百字节的 key，让 virtual-list diff 更轻。
  return lines.map((line) => {
    const parsed = parseLogLine(line)
    const id = ++logIdCounter
    return {
      ...parsed,
      id,
      key: `${keyPrefix}${id}`,
    }
  })
}

function togglePause() {
  isPaused.value = !isPaused.value
  if (isPaused.value) {
    ElMessage.info('已暂停自动刷新')
    closeLogStream()
    terminalStatus.value = 'disconnected'
  } else {
    ElMessage.success('已恢复实时日志')
    connectLogStream({ reset: false })
  }
}

function refreshCurrentLogs() {
  if (isFullSearch.value) {
    doFullSearch(true)
    return
  }
  isPaused.value = false
  connectLogStream({ reset: true })
}

async function refreshLogs(force = false) {
  if (!force && (isPaused.value || document.visibilityState === 'hidden' || isFullSearch.value)) return

  try {
    const t0 = performance.now()
    const useIncremental = !force && nextOffset >= 0
    lastFetchMode.value = useIncremental ? 'delta' : force ? 'full(force)' : 'full'
    const data = await logApi.get(logLimit.value, useIncremental ? nextOffset : -1)
    const logLines = Array.isArray(data.logs) ? data.logs : []

    if (typeof data.next_offset === 'number') nextOffset = data.next_offset

    if (!data.is_full && !force) {
      if (logLines.length === 0) return
      const parsed = parseLogLines(logLines, `delta-${nextOffset}-`)
      incrementalCount.value += parsed.length
      const combined = [...logs.value, ...parsed]
      logs.value = combined.length > logLimit.value ? combined.slice(combined.length - logLimit.value) : combined
    } else {
      const lastLine = logLines[logLines.length - 1] || ''
      const signature = `${logLines.length}::${lastLine}`
      if (!force && signature === lastLogSignature) return
      lastLogSignature = signature
      incrementalCount.value = 0
      logs.value = parseLogLines(logLines, 'full-')
    }

    // OOM 修复：每次刷新后兜底瘦身，一次清 1/2 而不是 1/6，避免每 4 秒触发的
    // 刷新回调让 map 长期贴顶。
    trimMapByOldest(parseCache, parseCacheMax.value, Math.max(200, Math.floor(parseCacheMax.value / 2)))
    lastFetchMs.value = Math.round(performance.now() - t0)
  } catch (error) {
    console.error('获取日志失败:', error)
    terminalStatus.value = 'error'
    terminalErrorMessage.value = error?.response?.data?.detail || error.message || '获取日志失败'
  }
}

function resetLiveLogState() {
  logs.value = []
  logIdCounter = 0
  lastLogSignature = ''
  nextOffset = -1
  incrementalCount.value = 0
  parseCache.clear()
  pendingStreamLines = []
  if (streamFlushTimer) {
    clearTimeout(streamFlushTimer)
    streamFlushTimer = null
  }
}

function appendParsedLogs(lines, keyPrefix = 'stream-', { reset = false } = {}) {
  const logLines = Array.isArray(lines) ? lines.filter(Boolean) : []
  if (reset) {
    logs.value = parseLogLines(logLines, keyPrefix)
    incrementalCount.value = 0
  } else if (logLines.length) {
    const parsed = parseLogLines(logLines, keyPrefix)
    incrementalCount.value += parsed.length
    const combined = [...logs.value, ...parsed]
    logs.value = combined.length > logLimit.value ? combined.slice(combined.length - logLimit.value) : combined
  }
  trimMapByOldest(parseCache, parseCacheMax.value, Math.max(200, Math.floor(parseCacheMax.value / 2)))
}

function flushPendingStreamLines() {
  streamFlushTimer = null
  if (!pendingStreamLines.length || isPaused.value || isFullSearch.value) return
  const lines = pendingStreamLines
  pendingStreamLines = []
  appendParsedLogs(lines, `stream-${nextOffset}-`)
}

function queueStreamLines(lines) {
  if (!Array.isArray(lines) || !lines.length) return
  pendingStreamLines.push(...lines)
  if (streamFlushTimer) return
  streamFlushTimer = setTimeout(flushPendingStreamLines, LOG_FLUSH_INTERVAL)
}

function closeLogStream({ keepStatus = false, discardPending = false } = {}) {
  const wasPaused = isPaused.value
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (streamFlushTimer) {
    clearTimeout(streamFlushTimer)
    streamFlushTimer = null
  }
  if (discardPending) {
    pendingStreamLines = []
  } else if (pendingStreamLines.length && !isPaused.value && !isFullSearch.value) {
    const lines = pendingStreamLines
    pendingStreamLines = []
    appendParsedLogs(lines, `stream-${nextOffset}-`)
  }
  if (logEventSource) {
    try { logEventSource.close() } catch {}
    logEventSource = null
  }
  if (!keepStatus && !wasPaused && !isFullSearch.value) {
    terminalStatus.value = 'disconnected'
  }
}

function scheduleReconnect() {
  if (isPaused.value || isFullSearch.value || reconnectTimer) return
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connectLogStream()
  }, LOG_STREAM_RECONNECT_MS)
}

function handleStreamPayload(event, { reset = false } = {}) {
  let payload = {}
  try {
    payload = JSON.parse(event.data || '{}')
  } catch {
    payload = {}
  }
  if (typeof payload.next_offset === 'number') nextOffset = payload.next_offset
  const lines = Array.isArray(payload.logs) ? payload.logs : []
  const signature = `${lines.length}::${lines[lines.length - 1] || ''}`
  lastFetchMode.value = reset || payload.is_full ? 'sse(full)' : 'sse'
  lastFetchMs.value = 0
  terminalErrorMessage.value = ''
  terminalStatus.value = 'connected'
  if (reset || payload.is_full) {
    lastLogSignature = signature
    appendParsedLogs(lines, 'sse-full-', { reset: true })
    return
  }
  if (lines.length) {
    lastLogSignature = signature
    queueStreamLines(lines)
  }
}

function connectLogStream({ reset = false } = {}) {
  if (typeof EventSource === 'undefined') {
    terminalStatus.value = 'error'
    terminalErrorMessage.value = '当前浏览器不支持 SSE'
    refreshLogs(true)
    return
  }
  const blocked = isPaused.value || isFullSearch.value
  closeLogStream()
  if (reset) resetLiveLogState()
  if (blocked) return

  terminalStatus.value = 'connecting'
  terminalErrorMessage.value = ''
  const url = logApi.streamUrl({ lines: logLimit.value, sinceOffset: reset ? -1 : nextOffset })
  const resetOnConnected = reset || nextOffset < 0
  logEventSource = new EventSource(url, { withCredentials: true })

  logEventSource.addEventListener('connected', (event) => handleStreamPayload(event, { reset: resetOnConnected }))
  logEventSource.addEventListener('reset', (event) => handleStreamPayload(event, { reset: true }))
  logEventSource.addEventListener('log', (event) => handleStreamPayload(event))
  logEventSource.addEventListener('heartbeat', (event) => {
    terminalStatus.value = 'connected'
    try {
      const payload = JSON.parse(event.data || '{}')
      if (typeof payload.next_offset === 'number') nextOffset = payload.next_offset
    } catch {}
  })
  logEventSource.addEventListener('stream_error', (event) => {
    terminalStatus.value = 'error'
    try {
      const payload = JSON.parse(event.data || '{}')
      terminalErrorMessage.value = payload.message || '日志流异常'
    } catch {
      terminalErrorMessage.value = '日志流异常'
    }
  })
  logEventSource.onerror = async () => {
    if (isPaused.value || isFullSearch.value) return
    if (await redirectIfSecurityGateExpired()) return
    terminalStatus.value = 'error'
    terminalErrorMessage.value = '日志流连接中断，正在重连'
    closeLogStream({ keepStatus: true })
    scheduleReconnect()
  }
}

function reconnectLogStream() {
  isPaused.value = false
  if (isFullSearch.value) {
    isFullSearch.value = false
  }
  connectLogStream({ reset: false })
}

async function clearLogs() {
  try {
    await showSystemConfirm({
      title: '确认',
      message: '确定要清空当前页面的日志显示吗？这不会删除后端日志文件。',
      tone: 'warning'
    })
    logs.value = []
    parseCache.clear()
    pendingStreamLines = []
    if (fullSearchAbortController) {
      try { fullSearchAbortController.abort() } catch {}
      fullSearchAbortController = null
    }
    const resumeOffset = nextOffset
    closeLogStream({ discardPending: true })
    lastLogSignature = ''
    nextOffset = resumeOffset
    incrementalCount.value = 0
    fullSearchCursor.value = 0
    fullSearchHasMore.value = false
    fullSearchTotal.value = 0
    fullSearchPageStart.value = 0
    lastSearchScanMb.value = 0
    lastSearchStoppedEarly.value = false
    isSearchLoading.value = false
    if (!isPaused.value && !isFullSearch.value) {
      connectLogStream({ reset: false })
    }
    ElMessage.success('日志视图已清空')
  } catch (_) {}
}

function onLimitChange() {
  nextOffset = -1
  // OOM 修复：从大 limit 切到小 limit 时主动清空缓存，避免旧条目要等下次刷新
  // 触发 trim 才被释放（中间窗口内 GC 难以回收，是切换刷条数后内存继续涨的根因）。
  parseCache.clear()
  if (isFullSearch.value) {
    doFullSearch(true)
  } else {
    connectLogStream({ reset: true })
  }
}

function exportFilteredLogs() {
  if (!filteredLogs.value.length) {
    ElMessage.warning('没有可导出的日志')
    return
  }

  const lines = filteredLogs.value.map((log) =>
    [log.time || '--', log.level, log.module || '-', log.message].join(' | ')
  )
  const content = lines.join('\n')
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const ts = new Date().toISOString().replace(/[:.]/g, '-')
  a.href = url
  a.download = `logs-export-${ts}.txt`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出筛选结果')
}

async function copyVisibleLogs() {
  if (!filteredLogs.value.length) {
    ElMessage.warning('当前没有可复制日志')
    return
  }
  const lines = filteredLogs.value.map((log) =>
    [log.time || '--', log.level, log.module || '-', log.message].join(' | ')
  )
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    ElMessage.success(`已复制 ${filteredLogs.value.length} 条日志`)
  } catch {
    ElMessage.warning('复制失败，请手动选中')
  }
}

function onWindowKeydown(e) {
  if (e.ctrlKey && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    searchInputRef.value?.focus()
    return
  }
  if (e.ctrlKey && e.key.toLowerCase() === 'r') {
    e.preventDefault()
    refreshCurrentLogs()
    return
  }
  if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'c') {
    e.preventDefault()
    copyVisibleLogs()
  }
}

async function doFullSearch(reset = true) {
  const keyword = searchKeyword.value.trim()
  const broadLevelFilter = selectedLevels.value.length > 2
  if (!keyword && broadLevelFilter) {
    ElMessage.info('请输入关键词，或只选择 1-2 个日志级别后再检索')
    return
  }
  if (keyword && keyword.length < MIN_FULL_SEARCH_KEYWORD_LENGTH) {
    ElMessage.warning(`检索关键词至少 ${MIN_FULL_SEARCH_KEYWORD_LENGTH} 个字符`)
    return
  }
  const cursor = reset ? 0 : fullSearchPageStart.value
  await gotoFullSearchPage(cursor)
}

// 全历史搜索的取消控制：用户连续输入或翻页时，旧请求立即 abort，
// 后端 streaming 扫描在 socket 关闭时 asyncio.to_thread 仍会跑完一轮，
// 但前端不会再被旧响应覆盖（串号 + signal 双保险）。
let fullSearchAbortController = null

async function gotoFullSearchPage(cursor) {
  const keyword = searchKeyword.value.trim()
  const broadLevelFilter = selectedLevels.value.length > 2
  if (!keyword && broadLevelFilter) return
  if (keyword && keyword.length < MIN_FULL_SEARCH_KEYWORD_LENGTH) return

  // 取消上一次未完请求
  if (fullSearchAbortController) {
    try { fullSearchAbortController.abort() } catch {}
  }
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null
  fullSearchAbortController = controller
  const requestSeq = ++fullSearchRequestSeq
  isSearchLoading.value = true
  try {
    const t0 = performance.now()
    lastFetchMode.value = 'search'
    const data = await logApi.search(
      keyword,
      selectedLevels.value,
      FULL_SEARCH_PAGE_SIZE,
      cursor,
      { maxScanMb: 32, signal: controller ? controller.signal : undefined },
    )
    if (requestSeq !== fullSearchRequestSeq) return
    const lines = Array.isArray(data.logs) ? data.logs : []
    fullSearchTotal.value = data.total_matched ?? lines.length
    fullSearchCursor.value = typeof data.next_cursor === 'number' ? data.next_cursor : (cursor + lines.length)
    fullSearchHasMore.value = !!data.has_more
    fullSearchPageStart.value = cursor
    // 后端透传的扫描预算 / 触顶状态：用于头部小标签
    const scanBytes = Number(data?.scan_bytes || 0)
    lastSearchScanMb.value = scanBytes > 0 ? Number((scanBytes / 1024 / 1024).toFixed(1)) : 0
    lastSearchStoppedEarly.value = !!data?.stopped_early
    logIdCounter = 0
    logs.value = parseLogLines(lines, `search-${cursor}-`)
    lastFetchMs.value = Math.round(performance.now() - t0)
  } catch (err) {
    // 用户取消的旧请求（AbortController.abort）：静默
    if (err?.name === 'CanceledError' || err?.code === 'ERR_CANCELED') return
    if (requestSeq !== fullSearchRequestSeq) return
    const detail = err?.response?.data?.detail || ''
    if (detail) {
      ElMessage.error(`检索失败：${detail}`)
    } else {
      ElMessage.error('全历史检索失败')
    }
  } finally {
    if (requestSeq === fullSearchRequestSeq) {
      isSearchLoading.value = false
    }
  }
}

async function loadNextFullSearchPage() {
  if (!isFullSearch.value || !fullSearchHasMore.value) return
  await gotoFullSearchPage(fullSearchCursor.value)
}

async function loadPrevFullSearchPage() {
  if (!isFullSearch.value) return
  const prev = Math.max(0, fullSearchPageStart.value - FULL_SEARCH_PAGE_SIZE)
  await gotoFullSearchPage(prev)
}

async function toggleFullSearch() {
  // 切换 mode 时取消上一未完搜索请求，避免老响应覆盖新状态
  if (fullSearchAbortController) {
    try { fullSearchAbortController.abort() } catch {}
    fullSearchAbortController = null
  }
  if (isFullSearch.value) {
    isFullSearch.value = false
    fullSearchTotal.value = 0
    fullSearchCursor.value = 0
    fullSearchHasMore.value = false
    fullSearchPageStart.value = 0
    lastSearchScanMb.value = 0
    lastSearchStoppedEarly.value = false
    isSearchLoading.value = false
    nextOffset = -1
    connectLogStream({ reset: true })
  } else {
    closeLogStream()
    isFullSearch.value = true
    await doFullSearch(true)
  }
}

// ========== 日志管理（/api/logs/info、/api/logs/cleanup） ==========

const logManagerVisible = ref(false)
const logInfo = ref(null)
const logInfoLoading = ref(false)
const cleanupLoading = ref(false)

function formatLogBytes(bytes) {
  const n = Number(bytes || 0)
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let idx = 0
  let value = n
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  return idx === 0 ? `${value.toFixed(0)} ${units[idx]}` : `${value.toFixed(2)} ${units[idx]}`
}

function formatLogTime(ts) {
  if (!ts) return '--'
  try {
    return new Date(Number(ts) * 1000).toLocaleString()
  } catch {
    return '--'
  }
}

async function loadLogInfo() {
  logInfoLoading.value = true
  try {
    logInfo.value = await logApi.info()
  } catch (err) {
    ElMessage.error('获取日志信息失败，请确认后端已启动')
  } finally {
    logInfoLoading.value = false
  }
}

async function openLogManager() {
  logManagerVisible.value = true
  await loadLogInfo()
}

async function runLogCleanup(action) {
  let confirmMessage = ''
  let payload = {}
  switch (action) {
    case 'rotate':
      confirmMessage = '立即对主日志进行一次轮转？\n\n当前 app.log 会被改名为 app.log.1，之后新日志写入空文件。'
      payload = { rotate: true }
      break
    case 'purge_backups':
      confirmMessage = '删除所有 app.log.N 备份文件？\n\n该操作不可恢复。'
      payload = { purgeBackups: true }
      break
    case 'truncate':
      confirmMessage = '把主日志截断到最近 2MB？\n\n现有文件超出尾部 2MB 的内容会被丢弃。'
      payload = { truncateMain: true, keepTailMb: 2 }
      break
    case 'rotate_and_purge':
      confirmMessage = '先轮转再清理全部备份？\n\n当前 app.log 会先滚到 app.log.1，然后所有 .1~.N 备份全部删除。'
      payload = { rotate: true, purgeBackups: true }
      break
    default:
      return
  }

  try {
    await showSystemConfirm({ title: '确认日志清理', message: confirmMessage, tone: 'warning' })
  } catch {
    return
  }

  cleanupLoading.value = true
  try {
    const result = await logApi.cleanup(payload)
    const cleanupSummary = result?.cleanup || {}
    const purgedBytes = Number(cleanupSummary.purged_bytes || 0)
    const truncatedFrom = Number(cleanupSummary.truncated_from_bytes || 0)
    const truncatedTo = Number(cleanupSummary.truncated_to_bytes || 0)
    const parts = []
    if (action === 'rotate' || action === 'rotate_and_purge') parts.push('已触发轮转')
    if (purgedBytes > 0) parts.push(`清理备份 ${formatLogBytes(purgedBytes)}`)
    if (cleanupSummary.truncated_main) {
      parts.push(`主日志 ${formatLogBytes(truncatedFrom)} → ${formatLogBytes(truncatedTo)}`)
    }
    ElMessage.success(parts.length ? parts.join('；') : '清理完成')
    await loadLogInfo()
    // 清理后本地视图还指向旧 byte offset，强制全量刷新避免读不到数据
    nextOffset = -1
    if (isFullSearch.value) await doFullSearch(true)
    else connectLogStream({ reset: true })
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '清理失败')
  } finally {
    cleanupLoading.value = false
  }
}

onMounted(() => {
  connectLogStream({ reset: true })
  window.addEventListener('keydown', onWindowKeydown)
})

onUnmounted(() => {
  closeLogStream()
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  // 取消未完搜索请求，避免页面销毁后老响应仍试图写 reactive
  if (fullSearchAbortController) {
    try { fullSearchAbortController.abort() } catch {}
    fullSearchAbortController = null
  }
  // 离开页面时主动释放缓存，回到列表 / 库存等其他页面后内存能立即降下来
  parseCache.clear()
  window.removeEventListener('keydown', onWindowKeydown)
})
</script>

<style scoped>
.logs-toolbar-btn,
.log-manager-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid #dbe4f0;
  border-radius: 8px;
  background: #ffffff;
  color: #334155;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.logs-toolbar-btn:hover,
.log-manager-action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.1);
}

.logs-toolbar-btn:hover svg,
.log-manager-action-btn:hover svg {
  transform: rotate(-8deg) scale(1.08);
}

.logs-toolbar-btn svg,
.log-manager-action-btn svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.logs-toolbar-btn:active,
.log-manager-action-btn:active { transform: scale(0.96); }

.logs-toolbar-btn:focus,
.logs-toolbar-btn:focus-visible,
.log-manager-action-btn:focus,
.log-manager-action-btn:focus-visible {
  outline: none;
  box-shadow: none;
}

.logs-toolbar-btn:disabled,
.log-manager-action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
  transform: none;
}

.logs-toolbar-btn.is-success,
.log-manager-action-btn.is-success {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #16a34a;
}

.logs-toolbar-btn.is-warning,
.log-manager-action-btn.is-warning {
  border-color: #fde68a;
  background: #fffbeb;
  color: #b45309;
}

.logs-toolbar-btn.is-danger,
.log-manager-action-btn.is-danger {
  border-color: #fecaca;
  background: #fef2f2;
  color: #b91c1c;
}

.logs-toolbar-btn.is-default:hover,
.log-manager-action-btn.is-default:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}

.logs-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 12px;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #ffffff;
  color: #64748b;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.logs-toggle-btn:hover {
  border-color: #cbd5e1;
  transform: translateY(-1px);
}

.logs-toggle-btn.is-active {
  border-color: #c7d2fe;
  background: #eef2ff;
  color: #4f46e5;
}

.logs-toggle-btn.is-compact {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #047857;
}

.logs-toggle-btn:focus,
.logs-toggle-btn:focus-visible,
.logs-search-submit:focus,
.logs-search-submit:focus-visible {
  outline: none;
  box-shadow: none;
}

.logs-search-submit {
  border-color: #c7d2fe;
  background: #eef2ff;
  color: #4f46e5;
}

.logs-search-submit:hover {
  background: #e0e7ff;
}

.logs-status-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 2px 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 650;
}

.logs-status-chip.is-info { color: #0369a1; background: #f0f9ff; border-color: #bae6fd; }
.logs-status-chip.is-success { color: #047857; background: #ecfdf5; border-color: #a7f3d0; }
.logs-status-chip.is-warning { color: #b45309; background: #fffbeb; border-color: #fde68a; }
.logs-status-chip.is-muted { color: #475569; background: #f8fafc; border-color: #e2e8f0; }

.logs-status-row {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px solid #f1f5f9;
  color: #475569;
  font-size: 11px;
}

.system-log-shell {
  overflow: hidden;
  border-radius: 14px;
  background: #09090b;
  box-shadow: 0 18px 44px -30px rgba(15, 23, 42, 0.72);
}

.system-log-shell.is-search-mode {
  border: 1px solid rgba(39, 39, 42, 0.96);
}

.log-manager-shell {
  overflow: hidden;
  border: 1px solid rgba(203, 213, 225, 0.72);
  border-radius: 14px;
  background: #ffffff;
  box-shadow:
    0 24px 70px rgba(15, 23, 42, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.log-manager-header,
.log-manager-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-color: rgba(226, 232, 240, 0.78);
  background: rgba(255, 255, 255, 0.58);
}

.log-manager-header {
  padding: 16px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.78);
}

.log-manager-footer {
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 1px solid rgba(226, 232, 240, 0.78);
}

.log-manager-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
}

.log-manager-icon,
.log-manager-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid rgba(203, 213, 225, 0.76);
  background: rgba(255, 255, 255, 0.72);
  color: #475569;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86);
}

.log-manager-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
}

.log-manager-close {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.log-manager-close:hover {
  transform: translateY(-1px) scale(1.04);
  border-color: rgba(248, 113, 113, 0.34);
  background: rgba(254, 242, 242, 0.78);
  color: #dc2626;
}

.log-manager-close:active {
  transform: scale(0.94);
}

.log-stat-card,
.log-policy-card,
.log-file-panel {
  border: 1px solid rgba(203, 213, 225, 0.72);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.62);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.86),
    0 10px 24px rgba(15, 23, 42, 0.06);
}

.log-stat-card {
  min-width: 0;
  padding: 12px 14px;
}

.log-policy-card {
  padding: 12px 14px;
}

.log-file-panel {
  overflow: hidden;
}

.log-file-head,
.log-file-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 104px 172px;
  align-items: center;
  gap: 12px;
}

.log-file-head {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.82);
  background: rgba(248, 250, 252, 0.88);
  color: #64748b;
  font-size: 11.5px;
  font-weight: 800;
}

.log-file-head span:nth-child(2),
.log-file-head span:nth-child(3) {
  text-align: right;
}

.log-file-row {
  min-height: 40px;
  padding: 9px 14px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.72);
  font-size: 12.5px;
}

.log-file-row:last-child {
  border-bottom: none;
}

.log-file-row:hover {
  background: rgba(248, 250, 252, 0.7);
}

.log-file-badge {
  flex-shrink: 0;
  padding: 1px 7px;
  border-radius: 5px;
  font-family: var(--font-body);
  font-size: 10px;
  font-weight: 800;
  line-height: 16px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.74);
}

.log-file-badge.is-main {
  border: 1px solid rgba(52, 211, 153, 0.32);
  background: #ecfdf5;
  color: #047857;
}

.log-file-badge.is-backup {
  border: 1px solid rgba(129, 140, 248, 0.36);
  background: #eef2ff;
  color: #4f46e5;
}

.log-policy-card code {
  border: 1px solid rgba(203, 213, 225, 0.72);
  border-radius: 6px;
  background: rgba(241, 245, 249, 0.9);
  padding: 1px 5px;
  color: #334155;
  font-size: 11px;
}

:global(.log-manager-overlay) {
  background: rgba(15, 23, 42, 0.34) !important;
}

:global(.log-manager-overlay .el-overlay-dialog) {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  padding: 16px !important;
}

:global(.log-manager-dialog.el-dialog) {
  margin: auto !important;
  max-width: min(680px, calc(100vw - 32px)) !important;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  overflow: visible !important;
  --el-dialog-bg-color: transparent;
}

:global(.log-manager-dialog .el-dialog__header),
:global(.log-manager-dialog .el-dialog__footer) {
  display: none !important;
}

:global(.log-manager-dialog .el-dialog__body) {
  padding: 0 !important;
  background: transparent !important;
}

:global(html.kikoerumanager-dark body .log-manager-overlay) {
  background: rgba(0, 0, 0, 0.58) !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

:global(html.kikoerumanager-dark body .log-manager-dialog.el-dialog) {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell),
:global(html.kikoerumanager-dark body .log-manager-shell) {
  border-color: rgba(255, 255, 255, 0.08) !important;
  background: #0b0f14 !important;
  background-image: none !important;
  color: #d7dde7 !important;
  box-shadow: 0 22px 52px rgba(0, 0, 0, 0.46) !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-header),
:global(html.kikoerumanager-dark body #app .log-manager-footer),
:global(html.kikoerumanager-dark body .log-manager-header),
:global(html.kikoerumanager-dark body .log-manager-footer) {
  border-color: rgba(255, 255, 255, 0.07) !important;
  background: #0b0f14 !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-body),
:global(html.kikoerumanager-dark body .log-manager-body) {
  background: #0b0f14 !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-icon),
:global(html.kikoerumanager-dark body #app .log-manager-close),
:global(html.kikoerumanager-dark body .log-manager-icon),
:global(html.kikoerumanager-dark body .log-manager-close) {
  border-color: rgba(255, 255, 255, 0.1) !important;
  background: #131820 !important;
  background-image: none !important;
  color: #c9d1dd !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-close:hover),
:global(html.kikoerumanager-dark body .log-manager-close:hover) {
  border-color: rgba(255, 255, 255, 0.16) !important;
  background: #1a202a !important;
  color: #f2f6fb !important;
  transform: none !important;
}

:global(html.kikoerumanager-dark body #app .log-stat-card),
:global(html.kikoerumanager-dark body #app .log-policy-card),
:global(html.kikoerumanager-dark body #app .log-file-panel),
:global(html.kikoerumanager-dark body .log-stat-card),
:global(html.kikoerumanager-dark body .log-policy-card),
:global(html.kikoerumanager-dark body .log-file-panel) {
  border-color: rgba(255, 255, 255, 0.08) !important;
  background: #11161d !important;
  background-image: none !important;
  color: #d7dde7 !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .text-slate-950),
:global(html.kikoerumanager-dark body #app .log-manager-shell .text-slate-900),
:global(html.kikoerumanager-dark body #app .log-manager-shell .text-slate-800),
:global(html.kikoerumanager-dark body #app .log-manager-shell .text-slate-700),
:global(html.kikoerumanager-dark body .log-manager-shell .text-slate-950),
:global(html.kikoerumanager-dark body .log-manager-shell .text-slate-900),
:global(html.kikoerumanager-dark body .log-manager-shell .text-slate-800),
:global(html.kikoerumanager-dark body .log-manager-shell .text-slate-700) {
  color: #f1f5f9 !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .text-slate-600),
:global(html.kikoerumanager-dark body #app .log-manager-shell .text-slate-500),
:global(html.kikoerumanager-dark body #app .log-manager-shell .text-slate-400),
:global(html.kikoerumanager-dark body .log-manager-shell .text-slate-600),
:global(html.kikoerumanager-dark body .log-manager-shell .text-slate-500),
:global(html.kikoerumanager-dark body .log-manager-shell .text-slate-400) {
  color: #8b96a8 !important;
}

:global(html.kikoerumanager-dark body #app .log-file-head),
:global(html.kikoerumanager-dark body .log-file-head) {
  border-color: rgba(255, 255, 255, 0.07) !important;
  background: #0f1319 !important;
  color: #8b96a8 !important;
}

:global(html.kikoerumanager-dark body #app .log-file-row),
:global(html.kikoerumanager-dark body .log-file-row) {
  border-color: rgba(255, 255, 255, 0.06) !important;
}

:global(html.kikoerumanager-dark body #app .log-file-row:hover),
:global(html.kikoerumanager-dark body .log-file-row:hover) {
  background: #151b24 !important;
}

:global(html.kikoerumanager-dark body #app .log-policy-card code),
:global(html.kikoerumanager-dark body .log-policy-card code) {
  border-color: rgba(255, 255, 255, 0.1) !important;
  background: #080b10 !important;
  color: #cbd5e1 !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-file-badge),
:global(html.kikoerumanager-dark body .log-manager-shell .log-file-badge) {
  border-color: rgba(255, 255, 255, 0.12) !important;
  background: #171d26 !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-file-badge.is-main),
:global(html.kikoerumanager-dark body .log-manager-shell .log-file-badge.is-main) {
  color: #7dd3fc !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-file-badge.is-backup),
:global(html.kikoerumanager-dark body .log-manager-shell .log-file-badge.is-backup) {
  color: #cbd5e1 !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-action-btn),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-action-btn) {
  border-color: rgba(255, 255, 255, 0.1) !important;
  background: #141a22 !important;
  background-image: none !important;
  color: #d7dde7 !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-action-btn:hover),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-action-btn:hover) {
  border-color: rgba(255, 255, 255, 0.16) !important;
  background: #1a202a !important;
  background-image: none !important;
  box-shadow: none !important;
  transform: none !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-action-btn.is-success),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-action-btn.is-success) {
  color: #86efac !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-action-btn.is-warning),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-action-btn.is-warning) {
  color: #fde047 !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-action-btn.is-danger),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-action-btn.is-danger) {
  color: #f87171 !important;
}

:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-action-btn:focus),
:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-action-btn:focus-visible),
:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-close:focus),
:global(html.kikoerumanager-dark body #app .log-manager-shell .log-manager-close:focus-visible),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-action-btn:focus),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-action-btn:focus-visible),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-close:focus),
:global(html.kikoerumanager-dark body .log-manager-shell .log-manager-close:focus-visible) {
  outline: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-toolbar) {
  border-color: rgba(255, 255, 255, 0.08) !important;
  background: #0d1117 !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-status-row) {
  border-top-color: rgba(255, 255, 255, 0.07) !important;
  background: transparent !important;
  background-image: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-count-chip),
:global(html.kikoerumanager-dark body #app .logs-page .logs-status-chip),
:global(html.kikoerumanager-dark body #app .logs-page .logs-search-clear) {
  border-color: rgba(255, 255, 255, 0.1) !important;
  background: #141a22 !important;
  background-image: none !important;
  color: #cbd5e1 !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-toolbar-label),
:global(html.kikoerumanager-dark body #app .logs-page .text-slate-500),
:global(html.kikoerumanager-dark body #app .logs-page .text-slate-600) {
  color: #8b96a8 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-search-input) {
  border-color: rgba(255, 255, 255, 0.1) !important;
  background: #080b10 !important;
  background-image: none !important;
  color: #e5e7eb !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-search-input::placeholder) {
  color: #667085 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-search-input:focus) {
  border-color: rgba(255, 255, 255, 0.18) !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-search-submit),
:global(html.kikoerumanager-dark body #app .logs-page .logs-toggle-btn),
:global(html.kikoerumanager-dark body #app .logs-page .logs-toolbar-btn),
:global(html.kikoerumanager-dark body #app .logs-page .log-level-pill),
:global(html.kikoerumanager-dark body #app .logs-page .logs-search-submit .text-indigo-400),
:global(html.kikoerumanager-dark body #app .logs-page .logs-count-chip .text-blue-500) {
  border-color: rgba(255, 255, 255, 0.1) !important;
  background: #141a22 !important;
  background-image: none !important;
  color: #d7dde7 !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-search-submit:hover),
:global(html.kikoerumanager-dark body #app .logs-page .logs-toggle-btn:hover),
:global(html.kikoerumanager-dark body #app .logs-page .logs-toolbar-btn:hover),
:global(html.kikoerumanager-dark body #app .logs-page .log-level-pill:hover) {
  border-color: rgba(255, 255, 255, 0.16) !important;
  background: #1a202a !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-toolbar-btn.is-success),
:global(html.kikoerumanager-dark body #app .logs-page .logs-toggle-btn.is-compact),
:global(html.kikoerumanager-dark body #app .logs-page .logs-status-chip.is-success) {
  color: #86efac !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-toolbar-btn.is-warning),
:global(html.kikoerumanager-dark body #app .logs-page .logs-status-chip.is-warning) {
  color: #fde047 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-toolbar-btn.is-danger) {
  color: #f87171 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-search-submit),
:global(html.kikoerumanager-dark body #app .logs-page .logs-toggle-btn.is-active),
:global(html.kikoerumanager-dark body #app .logs-page .logs-status-chip.is-info) {
  color: #d7dde7 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-count-chip .text-blue-500),
:global(html.kikoerumanager-dark body #app .logs-page .logs-search-submit .text-indigo-400) {
  color: #d7dde7 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .logs-status-chip.is-muted) {
  color: #a3adbd !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .log-level-pill.is-active) {
  border-color: rgba(255, 255, 255, 0.18) !important;
  background: #1d2430 !important;
  color: #f1f5f9 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .log-level-pill.is-warning.is-active) {
  color: #fde047 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .log-level-pill.is-error.is-active) {
  color: #f87171 !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .log-level-pill.is-info.is-active) {
  color: #7dd3fc !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .log-level-pill.is-debug.is-active) {
  color: #c4b5fd !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .el-select__wrapper) {
  border-color: rgba(255, 255, 255, 0.1) !important;
  background: #141a22 !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .logs-page .el-select__placeholder),
:global(html.kikoerumanager-dark body #app .logs-page .el-select__selected-item) {
  color: #cbd5e1 !important;
}

@media (max-width: 720px) {
  .log-manager-body {
    padding: 12px;
  }

  .log-manager-body > .grid {
    grid-template-columns: 1fr;
  }

  .log-file-head,
  .log-file-row {
    grid-template-columns: minmax(0, 1fr) 86px;
  }

  .log-file-head span:nth-child(3),
  .log-file-row > div:nth-child(3) {
    display: none;
  }
}

.log-level-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid #dbe4f0;
  border-radius: 999px;
  background: #ffffff;
  color: #64748b;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition: all 0.16s ease;
}

.log-level-pill:hover { box-shadow: 0 3px 8px rgba(15, 23, 42, 0.06); }

.log-level-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.4;
}

.log-level-pill.is-active .log-level-dot { opacity: 1; }
.log-level-pill.is-debug.is-active  { border-color: #cbd5e1; background: #f1f5f9; color: #475569; }
.log-level-pill.is-info.is-active   { border-color: #bfdbfe; background: #eff6ff; color: #1d4ed8; }
.log-level-pill.is-warning.is-active{ border-color: #fcd34d; background: #fffbeb; color: #b45309; }
.log-level-pill.is-error.is-active  { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
</style>
