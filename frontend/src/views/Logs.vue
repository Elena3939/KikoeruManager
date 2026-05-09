<template>
  <div class="max-w-[1480px] mx-auto flex flex-col gap-0">
    <AppPageHeader
      :icon="Terminal"
      icon-color="#475569"
      title="系统日志"
      subtitle="实时监控应用运行输出，支持级别过滤、模块筛选与关键词搜索。"
    >
        <span class="inline-flex items-center gap-1 px-3 py-1 border border-slate-200 rounded-full bg-slate-50 text-xs text-slate-500">
          <span class="font-bold text-blue-500">{{ filteredLogs.length }}</span>
          <span class="text-slate-300">/</span>
          <span class="font-semibold text-slate-600">{{ logs.length }}</span> 条
        </span>

        <button
          type="button"
          class="log-action-btn"
          :class="isPaused ? 'log-action-btn--success' : 'log-action-btn--warning'"
          @click="togglePause"
        >
          <component :is="isPaused ? Play : PauseCircle" :size="13" />
          {{ isPaused ? '恢复刷新' : '暂停刷新' }}
        </button>

        <button type="button" class="log-action-btn log-action-btn--default" @click="refreshLogs(true)">
          <RefreshCw :size="13" />
          刷新
        </button>

        <button type="button" class="log-action-btn log-action-btn--default" @click="exportFilteredLogs">
          <Download :size="13" />
          导出筛选结果
        </button>

        <button type="button" class="log-action-btn log-action-btn--default" @click="copyVisibleLogs">
          <Copy :size="13" />
          复制可见窗口
        </button>

        <button type="button" class="log-action-btn log-action-btn--default" @click="openLogManager">
          <Settings2 :size="13" />
          日志管理
        </button>

        <button type="button" class="log-action-btn log-action-btn--danger" @click="clearLogs">
          <AppLottieIcon :src="deleteIconAnimation" :size="26" tone="danger" />
          清空视图
        </button>
    </AppPageHeader>

    <div class="flex flex-wrap items-center gap-3 px-4 py-3 mb-3.5 border border-slate-200 rounded-2xl bg-white shadow-sm">
      <div class="flex items-center gap-2">
        <span class="text-[12.5px] font-semibold text-slate-500 whitespace-nowrap">级别</span>
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
        <span class="text-[12.5px] font-semibold text-slate-500 whitespace-nowrap">模块</span>
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

      <div class="relative flex-1 min-w-[220px] max-w-[420px] flex items-center gap-2">
        <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
        <input
          ref="searchInputRef"
          v-model="searchKeyword"
          type="text"
          class="w-full h-[32px] pl-7 pr-20 border border-slate-200 rounded-lg bg-white text-[13px] text-slate-800 outline-none placeholder-slate-400 transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
          :placeholder="isFullSearch ? '全历史检索关键词（回车立即检索）' : '搜索当前日志内容…'"
          @input="onSearchInput"
          @keydown.enter.prevent="doFullSearch(true)"
        />
        <button
          v-if="searchKeyword"
          type="button"
          class="absolute right-[86px] top-1/2 -translate-y-1/2 text-[11px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 hover:bg-slate-200 transition"
          @click="clearSearchKeyword"
        >清空</button>
        <button
          v-if="isFullSearch"
          type="button"
          class="h-[32px] px-3 rounded-lg border border-indigo-300 bg-indigo-50 text-indigo-600 text-[12px] font-semibold hover:bg-indigo-100 transition"
          @click="doFullSearch(true)"
        >检索</button>
      </div>

      <div class="flex items-center gap-2 ml-auto" :class="{ 'opacity-50 pointer-events-none': isFullSearch }">
        <span class="text-[12.5px] font-semibold text-slate-500 whitespace-nowrap">条数</span>
        <el-select v-model="logLimit" size="small" style="width: 100px" @change="onLimitChange">
          <el-option :value="100" label="100 条" />
          <el-option :value="300" label="300 条" />
          <el-option :value="500" label="500 条" />
          <el-option :value="1000" label="1000 条" />
          <el-option :value="2000" label="2000 条" />
        </el-select>
      </div>

      <button
        type="button"
        class="flex items-center gap-1.5 h-[28px] px-3 border rounded-full text-[11.5px] font-semibold cursor-pointer transition"
        :class="isFullSearch
          ? 'border-indigo-300 bg-indigo-50 text-indigo-600'
          : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'"
        @click="toggleFullSearch"
      >
        <FileSearch :size="12" />
        {{ isSearchLoading ? '检索中…' : isFullSearch ? '全历史模式' : '搜索全历史' }}
        <span v-if="fullSearchTotal > 0" class="text-[10px] text-indigo-400">{{ fullSearchTotal }}</span>
      </button>

      <div class="w-full flex flex-wrap items-center gap-2 text-[11px] text-slate-600 pt-1 border-t border-slate-100 mt-1">
        <span class="px-2 py-0.5 rounded bg-sky-50 border border-sky-100 text-sky-700">模式 {{ lastFetchMode }}</span>
        <span class="px-2 py-0.5 rounded bg-emerald-50 border border-emerald-100 text-emerald-700">本次 {{ lastFetchMs }}ms</span>
        <span class="px-2 py-0.5 rounded bg-white border border-slate-200">均值 {{ avgFetchMs }}ms</span>
        <span class="px-2 py-0.5 rounded bg-white border border-slate-200">峰值 {{ maxFetchMs }}ms</span>
        <span class="px-2 py-0.5 rounded bg-white border border-slate-200">parse 命中 {{ parseCacheHitRate }}%</span>
        <span class="px-2 py-0.5 rounded bg-white border border-slate-200">highlight 命中 {{ highlightCacheHitRate }}%</span>
        <span class="px-2 py-0.5 rounded bg-indigo-50 border border-indigo-100 text-indigo-700">快捷键 Ctrl+K 搜索 · Ctrl+R 刷新 · Ctrl+Shift+C 复制可见</span>
      </div>
    </div>

    <div class="flex flex-col border border-slate-800 rounded-2xl overflow-hidden bg-[#0f172a] shadow-[0_20px_50px_rgba(15,23,42,0.24)]">
      <div class="flex items-center gap-2 px-4 py-2 bg-[#111c31] border-b border-slate-700 text-xs text-slate-300">
        <span
          class="w-[7px] h-[7px] rounded-full flex-shrink-0"
          :class="isFullSearch ? 'bg-indigo-400' : isPaused ? 'bg-amber-400' : 'bg-emerald-400 shadow-[0_0_6px_#22c55e]'"
        />
        <span class="font-bold text-slate-200">{{ isFullSearch ? '全历史检索' : isPaused ? '已暂停' : autoFollowLogs ? '实时跟随' : '查看历史' }}</span>
        <span v-if="isFullSearch" class="ml-1 px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[10px] font-bold">全历史</span>
        <span class="text-slate-400">{{ filteredLogs.length }} 条匹配 · {{ logs.length }} 条总计</span>
        <span class="text-cyan-300 text-[11px]">{{ lastFetchMode }} {{ lastFetchMs }}ms</span>
        <span v-if="incrementalCount > 0" class="text-emerald-300">+{{ incrementalCount }} 新增</span>
        <span v-if="isFullSearch && fullSearchHasMore" class="text-amber-400/80 text-[11px]">可继续加载更多</span>
        <span v-if="isSearchLoading" class="text-indigo-300 text-[11px]">检索中…</span>
        <button
          v-if="!autoFollowLogs && !isPaused"
          type="button"
          class="ml-auto px-2.5 py-0.5 border border-indigo-400/40 rounded-md bg-indigo-400/10 text-indigo-300 text-[11px] font-semibold hover:bg-indigo-400/20 transition cursor-pointer"
          @click="scrollToBottom"
        >
          <ArrowDown :size="10" class="inline mr-0.5" />跳到底部
        </button>
      </div>

      <div
        ref="logContainer"
        class="log-viewer"
        :class="{ 'is-paused': isPaused }"
        @scroll.passive="onScroll"
      >
        <div :style="{ height: paddingTop + 'px' }" aria-hidden="true" />

        <div
          v-for="log in visibleLogs"
          :key="log.key"
          class="log-line"
          :class="[`is-${log.level.toLowerCase()}`, { 'is-selected': selectedLogKey === log.key }]"
        >
          <span class="log-ts">{{ log.time || '--:--:--' }}</span>
          <span class="log-lvl" :class="`lvl-${log.level.toLowerCase()}`">{{ log.level }}</span>
          <span
            v-if="log.module"
            class="log-mod"
            :style="{ background: getModuleColor(log.module) }"
            v-html="highlightModuleName(log.module)"
          />
          <span
            class="log-msg"
            :title="log.isTruncated ? '内容过长，点击下方详情查看完整文本' : log.message"
            @click="showLogDetail(log)"
            @dblclick.stop="copyLogLine(log)"
            v-html="highlightLogMessage(log.displayMessage || log.message)"
          />
        </div>

        <div :style="{ height: paddingBottom + 'px' }" aria-hidden="true" />
      </div>

      <div v-if="selectedLog" class="border-t border-white/10 bg-black/20 px-4 py-3 text-xs text-slate-200">
        <div class="flex items-center justify-between gap-2 mb-2">
          <div class="font-semibold text-slate-100">日志详情</div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="px-2.5 py-1 rounded border border-indigo-400/40 bg-indigo-400/10 text-indigo-200 hover:bg-indigo-400/25 transition inline-flex items-center gap-1"
              @click="copyLogLine(selectedLog)"
              title="复制包含时间戳 / 级别 / 模块的完整单行（不截断）"
            >
              <ClipboardCopy :size="12" />复制原文
            </button>
            <button
              type="button"
              class="px-2.5 py-1 rounded border border-slate-500/40 text-slate-200 hover:bg-slate-700/40 transition inline-flex items-center gap-1"
              @click="copyLogWithContext(selectedLog, 15)"
              title="复制前后各 15 行（共 31 行）上下文"
            >
              <ClipboardList :size="12" />复制上下文 ±15
            </button>
            <button
              type="button"
              class="px-2 py-1 rounded border border-slate-500/40 text-slate-300 hover:bg-slate-700/40 transition"
              @click="clearSelectedLog"
            >关闭</button>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-2 mb-2 text-[11px] text-slate-400">
          <span>{{ selectedLog.time || '--:--:--' }}</span>
          <span class="px-1.5 py-0.5 rounded bg-slate-700/60">{{ selectedLog.level }}</span>
          <span v-if="selectedLog.module" class="px-1.5 py-0.5 rounded bg-slate-700/60">{{ selectedLog.module }}</span>
          <span class="text-slate-500">提示：下方文本可鼠标直接选中复制，不受虚拟滚动影响</span>
        </div>
        <pre
          class="m-0 max-h-[240px] overflow-auto whitespace-pre-wrap break-all leading-5 text-slate-100 no-scrollbar select-text"
        >{{ selectedLog.message }}</pre>
      </div>

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

      <AppEmptyState
        v-if="filteredLogs.length === 0 && logs.length > 0"
        description="没有匹配的日志"
        size="default"
        class="py-8"
      />
      <AppEmptyState
        v-if="logs.length === 0"
        description="暂无日志"
        size="default"
        class="py-8"
      />
    </div>

    <el-dialog
      v-model="logManagerVisible"
      title="日志管理"
      width="640px"
      :close-on-click-modal="false"
      :z-index="2200"
      append-to-body
    >
      <div class="text-[13px] text-slate-700">
        <div class="grid grid-cols-3 gap-3 mb-4">
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
            <div class="text-[11px] text-slate-500">主日志大小</div>
            <div class="text-[16px] font-bold text-slate-800">{{ formatLogBytes(logInfo?.main_bytes) }}</div>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
            <div class="text-[11px] text-slate-500">备份合计</div>
            <div class="text-[16px] font-bold text-slate-800">{{ formatLogBytes(logInfo?.backup_bytes) }}</div>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5">
            <div class="text-[11px] text-slate-500">总占用</div>
            <div class="text-[16px] font-bold text-slate-800">{{ formatLogBytes(logInfo?.total_bytes) }}</div>
          </div>
        </div>

        <div class="rounded-xl border border-slate-200 mb-4 max-h-[260px] overflow-auto">
          <table class="w-full text-[12.5px]">
            <thead class="bg-slate-50 text-slate-500">
              <tr>
                <th class="text-left px-3 py-2 font-semibold">文件</th>
                <th class="text-right px-3 py-2 font-semibold">大小</th>
                <th class="text-right px-3 py-2 font-semibold">最后修改</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="logInfoLoading">
                <td colspan="3" class="text-center text-slate-400 px-3 py-4">加载中…</td>
              </tr>
              <tr
                v-for="file in (logInfo?.files || [])"
                :key="file.path"
                class="border-t border-slate-100"
              >
                <td class="px-3 py-2 text-slate-700 font-mono text-[12px]">
                  <span class="inline-flex items-center gap-1">
                    <HardDrive :size="12" class="text-slate-400" />
                    {{ file.name }}
                    <span v-if="file.is_main" class="ml-1 text-[10px] text-emerald-600 bg-emerald-50 border border-emerald-100 rounded-full px-1.5">主</span>
                    <span v-else-if="file.is_backup" class="ml-1 text-[10px] text-indigo-600 bg-indigo-50 border border-indigo-100 rounded-full px-1.5">备份</span>
                  </span>
                </td>
                <td class="px-3 py-2 text-right text-slate-700">{{ formatLogBytes(file.size_bytes) }}</td>
                <td class="px-3 py-2 text-right text-slate-500">{{ formatLogTime(file.modified_ts) }}</td>
              </tr>
              <tr v-if="!logInfoLoading && !(logInfo?.files || []).length">
                <td colspan="3" class="text-center text-slate-400 px-3 py-4">暂无日志文件</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 mb-4 text-[12px] text-slate-600 leading-5">
          <div class="font-semibold text-slate-700 mb-1">轮转策略</div>
          单文件上限 <span class="font-bold">{{ logInfo?.max_mb_per_file ?? 20 }} MB</span>，最多保留
          <span class="font-bold">{{ logInfo?.backup_count ?? 5 }}</span> 份备份，理论上限
          <span class="font-bold">{{ ((logInfo?.max_mb_per_file ?? 20) * ((logInfo?.backup_count ?? 5) + 1)).toFixed(0) }} MB</span>。
          可通过环境变量 <code>PREKIKOERU_LOG_MAX_MB</code> / <code>PREKIKOERU_LOG_BACKUPS</code> 调整。
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="log-action-btn log-action-btn--default"
            :disabled="cleanupLoading"
            @click="loadLogInfo"
          >
            <RefreshCw :size="13" />刷新
          </button>
          <button
            type="button"
            class="log-action-btn log-action-btn--success"
            :disabled="cleanupLoading"
            @click="runLogCleanup('rotate')"
            title="把当前 app.log 滚到 .1，新日志写入空文件；不删除任何内容"
          >
            <RefreshCw :size="13" />立即轮转
          </button>
          <button
            type="button"
            class="log-action-btn log-action-btn--warning"
            :disabled="cleanupLoading"
            @click="runLogCleanup('purge_backups')"
            title="删除所有 app.log.N 备份文件"
          >
            <Trash2 :size="13" />清理所有备份
          </button>
          <button
            type="button"
            class="log-action-btn log-action-btn--warning"
            :disabled="cleanupLoading"
            @click="runLogCleanup('truncate')"
            title="把主日志保留最近 2MB，丢弃前面所有内容（应急救急）"
          >
            <Trash2 :size="13" />截断主日志到 2MB
          </button>
          <button
            type="button"
            class="log-action-btn log-action-btn--danger"
            :disabled="cleanupLoading"
            @click="runLogCleanup('rotate_and_purge')"
            title="先轮转再清理全部备份；当前 app.log 会被清空，旧日志将无法恢复"
          >
            <Trash2 :size="13" />一键瘦身
          </button>
        </div>
      </div>

      <template #footer>
        <button
          type="button"
          class="log-action-btn log-action-btn--default"
          @click="logManagerVisible = false"
        >关闭</button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, triggerRef } from 'vue'
import {
  ArrowDown,
  Terminal,
  ClipboardCopy,
  ClipboardList,
  Copy,
  Download,
  FileSearch,
  HardDrive,
  PauseCircle,
  Play,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
} from 'lucide-vue-next'
import { ElDialog, ElMessage } from 'element-plus'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import { logApi } from '../api'
import AppLottieIcon from '../components/common/AppLottieIcon.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import deleteIconAnimation from '../assets/anime/Delete icon animation.lottie'

const LOG_POLL_INTERVAL = 5000
const ITEM_HEIGHT = 28
const OVERSCAN = 25
const LOG_PREVIEW_LIMIT = 900

const logs = shallowRef([])
const logContainer = ref(null)
const isPaused = ref(false)
const autoFollowLogs = ref(true)
const logLimit = ref(300)
const selectedLevels = ref(['INFO', 'WARNING', 'ERROR'])
const selectedModules = ref([])
const searchKeyword = ref('')
const selectedLog = ref(null)
const selectedLogKey = ref('')
const searchInputRef = ref(null)

const scrollTop = ref(0)
const viewerHeight = ref(600)

const allLevels = ['DEBUG', 'INFO', 'WARNING', 'ERROR']

let intervalId = null
let resizeObserver = null
let lastLogSignature = ''
let nextOffset = -1
let logIdCounter = 0
let searchDebounceTimer = null
let scrollRafId = null
let smoothScrollRafId = null
let latestScrollTop = 0
const fetchHistory = ref([])

const incrementalCount = ref(0)
const lastFetchMs = ref(0)
const lastFetchMode = ref('idle')
const isFullSearch = ref(false)
const fullSearchTotal = ref(0)
const fullSearchCursor = ref(0)
const fullSearchHasMore = ref(false)
const fullSearchPageStart = ref(0)
const FULL_SEARCH_PAGE_SIZE = 500
const MIN_FULL_SEARCH_KEYWORD_LENGTH = 2
const isSearchLoading = ref(false)
const smoothScrollInertia = ref(0.22)
let fullSearchRequestSeq = 0

const parseCache = new Map()
const highlightCache = new Map()
const parseCacheHits = ref(0)
const parseCacheMisses = ref(0)
const highlightCacheHits = ref(0)
const highlightCacheMisses = ref(0)

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

  return logs.value.filter((log) => {
    if (!lvlSet.has(log.level)) return false
    if (moduleSet && !moduleSet.has(log.module)) return false
    if (!termCount) return true
    // 消费解析阶段预先缓存的 lower-case（messageLower / moduleLower），
    // 这里不再 toLowerCase，单次过滤开销从 O(n·m) 降到 O(n·k)。
    const msg = log.messageLower || ''
    const mod = log.moduleLower || ''
    for (let i = 0; i < termCount; i += 1) {
      const term = terms[i]
      if (!msg.includes(term) && !mod.includes(term)) return false
    }
    return true
  })
})

const searchTerms = computed(() =>
  searchKeyword.value
    .toLowerCase()
    .split(/[\s,，]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 8)
)

const startIndex = computed(() => Math.max(0, Math.floor(scrollTop.value / ITEM_HEIGHT) - OVERSCAN))
const endIndex = computed(() => Math.min(filteredLogs.value.length, Math.ceil((scrollTop.value + viewerHeight.value) / ITEM_HEIGHT) + OVERSCAN))
const visibleLogs = computed(() => filteredLogs.value.slice(startIndex.value, endIndex.value))
const paddingTop = computed(() => startIndex.value * ITEM_HEIGHT)
const paddingBottom = computed(() => Math.max(0, (filteredLogs.value.length - endIndex.value) * ITEM_HEIGHT))

const avgFetchMs = computed(() => {
  if (!fetchHistory.value.length) return 0
  const sum = fetchHistory.value.reduce((acc, cur) => acc + cur, 0)
  return Math.round(sum / fetchHistory.value.length)
})

const maxFetchMs = computed(() => {
  if (!fetchHistory.value.length) return 0
  return Math.max(...fetchHistory.value)
})

const parseCacheHitRate = computed(() => {
  const total = parseCacheHits.value + parseCacheMisses.value
  return total ? Math.round((parseCacheHits.value / total) * 100) : 0
})

const highlightCacheHitRate = computed(() => {
  const total = highlightCacheHits.value + highlightCacheMisses.value
  return total ? Math.round((highlightCacheHits.value / total) * 100) : 0
})

const parseCacheMax = computed(() => Math.max(6000, logLimit.value * 8))
const highlightCacheMax = computed(() => Math.max(2500, logLimit.value * 4))

function getModuleColor(moduleName) {
  return moduleColors[moduleName] || '#64748b'
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

function escapeHtml(input) {
  return String(input)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeRegExp(input) {
  return String(input).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
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

function buildHighlightMeta(terms) {
  if (!terms.length) return null
  const sorted = [...terms].sort((a, b) => b.length - a.length)
  const unique = Array.from(new Set(sorted))
  const pattern = unique.map((t) => escapeRegExp(t)).join('|')
  const regex = new RegExp(`(${pattern})`, 'ig')
  const classMap = new Map()
  unique.forEach((term, idx) => {
    classMap.set(term.toLowerCase(), `log-hit-${idx % 4}`)
  })
  return { regex, classMap }
}

function highlightText(input) {
  const safe = escapeHtml(input || '')
  const terms = searchTerms.value
  if (!terms.length) return safe
  const termsKey = terms.join('|')
  const cacheKey = `${termsKey}::${safe}`
  if (highlightCache.has(cacheKey)) {
    highlightCacheHits.value += 1
    return highlightCache.get(cacheKey)
  }
  highlightCacheMisses.value += 1
  const meta = buildHighlightMeta(terms)
  if (!meta) return safe
  const highlighted = safe.replace(meta.regex, (matched) => {
    const cls = meta.classMap.get(matched.toLowerCase()) || 'log-hit-0'
    return `<mark class="log-hit ${cls}">${matched}</mark>`
  })
  trimMapByOldest(highlightCache, highlightCacheMax.value, Math.max(500, Math.floor(highlightCacheMax.value / 4)))
  highlightCache.set(cacheKey, highlighted)
  return highlighted
}

function highlightLogMessage(message) {
  return highlightText(message)
}

function highlightModuleName(moduleName) {
  return highlightText(moduleName)
}

function buildDisplayMessage(message) {
  const text = String(message || '')
  if (text.length <= LOG_PREVIEW_LIMIT) {
    return { displayMessage: text, isTruncated: false }
  }
  return {
    displayMessage: `${text.slice(0, LOG_PREVIEW_LIMIT)}...（已截断，点击查看完整）`,
    isTruncated: true,
  }
}

function parseLogLine(line) {
  if (parseCache.has(line)) {
    parseCacheHits.value += 1
    return parseCache.get(line)
  }
  parseCacheMisses.value += 1
  trimMapByOldest(parseCache, parseCacheMax.value, Math.max(1000, Math.floor(parseCacheMax.value / 4)))

  // 统一构造解析对象；预先缓存 lower-case 版本，避免 filteredLogs 过滤时每帧
  // 都对 2000 条日志重复 toLowerCase（此前是主要的 filter 卡点）。
  const buildParsed = (time, level, message) => {
    const mod = parseModule(message, line)
    const levelUpper = (level || 'INFO').toUpperCase()
    const parsed = {
      rawLine: line,
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
    return { ...parsed, id, key: `${keyPrefix}${id}` }
  })
}

function isNearBottom() {
  if (!logContainer.value) return true
  const { scrollTop: st, scrollHeight, clientHeight } = logContainer.value
  return scrollHeight - st - clientHeight < 60
}

function onScroll(e) {
  latestScrollTop = e.target.scrollTop
  if (scrollRafId) return
  scrollRafId = requestAnimationFrame(() => {
    scrollTop.value = latestScrollTop
    autoFollowLogs.value = isNearBottom()
    scrollRafId = null
  })
}

function scrollToBottom(smooth = true) {
  if (!logContainer.value) return
  const el = logContainer.value
  const target = el.scrollHeight
  if (!smooth) {
    el.scrollTop = target
    autoFollowLogs.value = true
    return
  }

  const start = el.scrollTop
  const distance = target - start
  if (Math.abs(distance) < 8) {
    el.scrollTop = target
    autoFollowLogs.value = true
    return
  }

  // 距离太大时直接跳转，避免长时间动画占用主线程。
  if (Math.abs(distance) > 1600) {
    el.scrollTop = target
    autoFollowLogs.value = true
    return
  }

  if (smoothScrollRafId) cancelAnimationFrame(smoothScrollRafId)
  const duration = Math.min(280, Math.max(110, Math.abs(distance) * 0.08))
  const inertia = smoothScrollInertia.value
  const t0 = performance.now()
  const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3)
  const easeOutQuint = (t) => 1 - Math.pow(1 - t, 5)

  const tick = (ts) => {
    const p = Math.min(1, (ts - t0) / duration)
    const eased = easeOutCubic(p) * (1 - inertia) + easeOutQuint(p) * inertia
    el.scrollTop = start + distance * eased
    if (p < 1) {
      smoothScrollRafId = requestAnimationFrame(tick)
      return
    }
    smoothScrollRafId = null
    autoFollowLogs.value = true
  }

  smoothScrollRafId = requestAnimationFrame(tick)
  autoFollowLogs.value = true
}

function showLogDetail(log) {
  selectedLog.value = log
  selectedLogKey.value = log?.key || ''
}

function clearSelectedLog() {
  selectedLog.value = null
  selectedLogKey.value = ''
}

function restoreSelectedLog() {
  if (!selectedLogKey.value) return
  const matched = logs.value.find((log) => log.key === selectedLogKey.value)
  if (matched) {
    selectedLog.value = matched
    return
  }
  selectedLog.value = null
  selectedLogKey.value = ''
}

function togglePause() {
  isPaused.value = !isPaused.value
  if (isPaused.value) {
    ElMessage.info('已暂停自动刷新')
  } else {
    ElMessage.success('已恢复自动刷新')
    refreshLogs(true)
  }
}

async function refreshLogs(force = false) {
  if (!force && (isPaused.value || document.visibilityState === 'hidden' || isFullSearch.value)) return

  try {
    const t0 = performance.now()
    const shouldFollow = autoFollowLogs.value || isNearBottom()
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

    triggerRef(logs)
    restoreSelectedLog()
    trimMapByOldest(parseCache, parseCacheMax.value, Math.max(500, Math.floor(parseCacheMax.value / 6)))
    trimMapByOldest(highlightCache, highlightCacheMax.value, Math.max(250, Math.floor(highlightCacheMax.value / 6)))
    lastFetchMs.value = Math.round(performance.now() - t0)
    fetchHistory.value = [...fetchHistory.value.slice(-39), lastFetchMs.value]
    await nextTick()
    if (shouldFollow && !isPaused.value) scrollToBottom(true)
  } catch (error) {
    console.error('获取日志失败:', error)
  }
}

async function clearLogs() {
  try {
    await showSystemConfirm({
      title: '确认',
      message: '确定要清空当前页面的日志显示吗？这不会删除后端日志文件。',
      tone: 'warning'
    })
    logs.value = []
    triggerRef(logs)
    highlightCache.clear()
    parseCacheHits.value = 0
    parseCacheMisses.value = 0
    highlightCacheHits.value = 0
    highlightCacheMisses.value = 0
    clearSelectedLog()
    lastLogSignature = ''
    nextOffset = -1
    incrementalCount.value = 0
    fullSearchCursor.value = 0
    fullSearchHasMore.value = false
    fullSearchTotal.value = 0
    fullSearchPageStart.value = 0
    scrollTop.value = 0
    ElMessage.success('日志视图已清空')
  } catch (_) {}
}

function onLimitChange() {
  nextOffset = -1
  refreshLogs(true)
}

function formatLogLineForCopy(log) {
  if (!log) return ''
  const parts = []
  if (log.time) parts.push(log.time)
  if (log.level) parts.push(`[${log.level}]`)
  if (log.module) parts.push(`[${log.module}]`)
  parts.push(log.message ?? '')
  return parts.join(' ')
}

async function writeToClipboard(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text)
    if (successMessage) {
      ElMessage({ message: successMessage, type: 'success', duration: 1200 })
    }
    return true
  } catch {
    // 不安全上下文（http 局域网 / 部分桌面包装）下 navigator.clipboard 不可用，
    // 回退到旧 API + 隐藏 textarea，确保能复制完整长度。
    try {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.top = '-9999px'
      document.body.appendChild(textarea)
      textarea.focus()
      textarea.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(textarea)
      if (!ok) throw new Error('execCommand failed')
      if (successMessage) {
        ElMessage({ message: successMessage, type: 'success', duration: 1200 })
      }
      return true
    } catch {
      ElMessage.warning('复制失败，请手动选中详情里的文本')
      return false
    }
  }
}

async function copyLogLine(log) {
  // 注意 log.message 是完整原文，虚拟滚动不会裁短；此处拼上时间 / 级别 / 模块，
  // 方便丢到 issue 里让团队按时间点定位问题，而不是只有一行裸消息。
  await writeToClipboard(formatLogLineForCopy(log), '已复制当前日志原文')
}

async function copyLogWithContext(log, span = 15) {
  if (!log) return
  const all = logs.value
  const idx = all.findIndex((item) => item.key === log.key)
  if (idx < 0) {
    ElMessage.warning('未找到该日志的上下文')
    return
  }
  const from = Math.max(0, idx - span)
  const to = Math.min(all.length, idx + span + 1)
  const lines = all.slice(from, to).map(formatLogLineForCopy)
  const text = lines.join('\n')
  await writeToClipboard(text, `已复制上下文共 ${lines.length} 行`)
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
  if (!visibleLogs.value.length) {
    ElMessage.warning('当前可见区没有可复制日志')
    return
  }
  const lines = visibleLogs.value.map((log) =>
    [log.time || '--', log.level, log.module || '-', log.message].join(' | ')
  )
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    ElMessage.success(`已复制 ${visibleLogs.value.length} 条可见日志`)
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
    refreshLogs(true)
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

async function gotoFullSearchPage(cursor) {
  const keyword = searchKeyword.value.trim()
  const broadLevelFilter = selectedLevels.value.length > 2
  if (!keyword && broadLevelFilter) return
  if (keyword && keyword.length < MIN_FULL_SEARCH_KEYWORD_LENGTH) return
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
      { maxScanMb: 32 },
    )
    if (requestSeq !== fullSearchRequestSeq) return
    const lines = Array.isArray(data.logs) ? data.logs : []
    fullSearchTotal.value = data.total_matched ?? lines.length
    fullSearchCursor.value = typeof data.next_cursor === 'number' ? data.next_cursor : (cursor + lines.length)
    fullSearchHasMore.value = !!data.has_more
    fullSearchPageStart.value = cursor
    logIdCounter = 0
    logs.value = parseLogLines(lines, `search-${cursor}-`)
    triggerRef(logs)
    restoreSelectedLog()
    lastFetchMs.value = Math.round(performance.now() - t0)
    fetchHistory.value = [...fetchHistory.value.slice(-39), lastFetchMs.value]
    await nextTick()
    scrollTop.value = 0
    if (logContainer.value) logContainer.value.scrollTop = 0
  } catch {
    ElMessage.error('全历史检索失败')
  } finally {
    isSearchLoading.value = false
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
  if (isFullSearch.value) {
    isFullSearch.value = false
    fullSearchTotal.value = 0
    fullSearchCursor.value = 0
    fullSearchHasMore.value = false
    fullSearchPageStart.value = 0
    highlightCache.clear()
    nextOffset = -1
    refreshLogs(true)
  } else {
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
    await refreshLogs(true)
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '清理失败')
  } finally {
    cleanupLoading.value = false
  }
}

onMounted(async () => {
  await refreshLogs(true)
  intervalId = setInterval(refreshLogs, LOG_POLL_INTERVAL)
  window.addEventListener('keydown', onWindowKeydown)

  if (logContainer.value) {
    viewerHeight.value = logContainer.value.clientHeight
    resizeObserver = new ResizeObserver(([entry]) => {
      viewerHeight.value = entry.contentRect.height
    })
    resizeObserver.observe(logContainer.value)
  }
})

onUnmounted(() => {
  if (intervalId) clearInterval(intervalId)
  if (resizeObserver) resizeObserver.disconnect()
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  if (scrollRafId) cancelAnimationFrame(scrollRafId)
  if (smoothScrollRafId) cancelAnimationFrame(smoothScrollRafId)
  window.removeEventListener('keydown', onWindowKeydown)
})
</script>

<style scoped>
.log-action-btn {
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

.log-action-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.1);
}

.log-action-btn:active { transform: scale(0.96); }
.log-action-btn--success { border-color: #bbf7d0; background: #f0fdf4; color: #16a34a; }
.log-action-btn--warning { border-color: #fde68a; background: #fffbeb; color: #b45309; }
.log-action-btn--danger  { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
.log-action-btn--default:hover { border-color: #94a3b8; background: #f8fafc; }

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

.log-viewer {
  height: calc(100vh - 320px);
  min-height: 420px;
  overflow-y: auto;
  overflow-x: auto;
  padding: 8px 0 12px;
  color: #e2e8f0;
  font-family: 'Consolas', 'JetBrains Mono', 'Monaco', monospace;
  font-size: 12.5px;
  line-height: 28px;
  scrollbar-width: thin;
  scrollbar-color: #334155 transparent;
}

.log-viewer.is-paused {
  outline: 2px solid rgba(245, 158, 11, 0.5);
  outline-offset: -2px;
}

.log-viewer::-webkit-scrollbar { width: 6px; height: 6px; }
.log-viewer::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }

.log-line {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 28px;
  padding: 0 14px;
  white-space: nowrap;
  transition: background-color 0.12s ease;
}

.log-line:hover { background: rgba(148, 163, 184, 0.07); }
.log-line.is-selected {
  background: rgba(59, 130, 246, 0.16);
  box-shadow: inset 3px 0 0 #38bdf8;
}
.log-line.is-warning { background: rgba(245, 158, 11, 0.07); }
.log-line.is-error   { background: rgba(239, 68, 68, 0.07); }
.log-line.is-debug   { opacity: 0.7; }
.log-line.is-selected.is-warning { background: rgba(245, 158, 11, 0.16); }
.log-line.is-selected.is-error { background: rgba(239, 68, 68, 0.16); }

.log-ts {
  flex-shrink: 0;
  color: #5a6a82;
  font-size: 12px;
  width: 138px;
}

.log-lvl {
  flex-shrink: 0;
  width: 52px;
  padding: 0 5px;
  border-radius: 4px;
  font-size: 10.5px;
  font-weight: 700;
  text-align: center;
  letter-spacing: 0.03em;
}

.lvl-debug { background: #2d3748; color: #a0aec0; }
.lvl-info { background: #162b4d; color: #7cc0ff; }
.lvl-warning { background: #5a3310; color: #fbbf24; }
.lvl-error { background: #5a1a1a; color: #fca5a5; }

.log-mod {
  flex-shrink: 0;
  padding: 0 7px;
  border-radius: 4px;
  color: #ffffff;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 18px;
}

.log-msg {
  flex: 1;
  min-width: 0;
  color: #cbd5e1;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.log-line.is-error .log-msg { color: #fca5a5; }
.log-line.is-warning .log-msg { color: #fde68a; }

:deep(.log-hit) {
  color: #f8fafc;
  padding: 0 2px;
  border-radius: 2px;
}

:deep(.log-hit.log-hit-0) { background: rgba(250, 204, 21, 0.38); }
:deep(.log-hit.log-hit-1) { background: rgba(34, 211, 238, 0.35); }
:deep(.log-hit.log-hit-2) { background: rgba(52, 211, 153, 0.34); }
:deep(.log-hit.log-hit-3) { background: rgba(251, 113, 133, 0.36); }
</style>
