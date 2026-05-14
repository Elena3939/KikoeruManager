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

      <div class="relative flex-1 min-w-[300px] max-w-[540px] flex items-center">
        <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
        <input
          ref="searchInputRef"
          v-model="searchKeyword"
          type="text"
          class="w-full h-[32px] pl-7 border border-slate-200 rounded-lg bg-white text-[13px] text-slate-800 outline-none placeholder-slate-400 transition focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
          :class="isFullSearch ? 'pr-[134px]' : 'pr-20'"
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
          class="absolute right-1 top-1/2 inline-flex h-[26px] min-w-[58px] -translate-y-1/2 items-center justify-center gap-1 whitespace-nowrap rounded-md border border-indigo-300 bg-indigo-50 px-3 text-[12px] font-semibold leading-none text-indigo-600 transition hover:-translate-y-[calc(50%+1px)] hover:bg-indigo-100 hover:shadow-sm active:-translate-y-1/2 active:scale-95"
          @click="doFullSearch(true)"
        >检索</button>
      </div>

      <div class="flex items-center gap-2 ml-auto" :class="{ 'opacity-50 pointer-events-none': isFullSearch }">
        <span class="text-[12.5px] font-semibold text-slate-500 whitespace-nowrap">条数</span>
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

      <button
        type="button"
        class="flex items-center gap-1.5 h-[28px] px-3 border rounded-full text-[11.5px] font-semibold cursor-pointer transition"
        :class="compactProcessLogs
          ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
          : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'"
        @click="toggleCompactProcessLogs"
      >
        <SlidersHorizontal :size="12" />
        {{ compactProcessLogs ? '精简过程已开' : '精简过程' }}
        <span v-if="compactProcessLogs && hiddenProcessNoiseCount > 0" class="text-[10px] text-emerald-500">{{ hiddenProcessNoiseCount }}</span>
      </button>

      <div class="w-full flex flex-wrap items-center gap-2 text-[11px] text-slate-600 pt-1 border-t border-slate-100 mt-1">
        <span class="px-2 py-0.5 rounded bg-sky-50 border border-sky-100 text-sky-700">模式 {{ lastFetchMode }}</span>
        <span class="px-2 py-0.5 rounded bg-emerald-50 border border-emerald-100 text-emerald-700">本次 {{ lastFetchMs }}ms</span>
        <span
          v-if="lastSearchScanMb > 0"
          class="px-2 py-0.5 rounded bg-amber-50 border border-amber-100 text-amber-700"
          title="后端实际扫描的字节数（MB），跨主日志 + 备份"
        >扫描 {{ lastSearchScanMb }}MB</span>
        <span
          v-if="lastSearchStoppedEarly"
          class="px-2 py-0.5 rounded bg-orange-50 border border-orange-100 text-orange-700"
          title="本次搜索触顶（5 万匹配 / 96MB 扫描预算 / 单页 1000 条），未扫到全部历史"
        >已截断</span>
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
          <!-- module 列始终渲染，没解析到时隐藏内容但保留 layout，让 message 起点严格上下齐 -->
          <span
            class="log-mod"
            :class="{ 'is-empty': !log.module }"
            :style="log.module ? { background: getModuleColor(log.module) } : null"
            :aria-hidden="!log.module"
            v-html="log.module ? highlightModuleName(log.module) : '&nbsp;'"
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

        <div class="log-manager-footer">
          <button
            type="button"
            class="log-action-btn log-action-btn--default"
            @click="logManagerVisible = false"
          >关闭</button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, triggerRef, watch } from 'vue'
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
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-vue-next'
import { ElDialog, ElMessage } from 'element-plus'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import { logApi } from '../api'
import AppLottieIcon from '../components/common/AppLottieIcon.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppDropdown from '../components/common/AppDropdown.vue'
import deleteIconAnimation from '../assets/anime/Delete icon animation.lottie'

const LOG_POLL_INTERVAL = 5000
const ITEM_HEIGHT = 28
// OVERSCAN 25→60：鼠标滚轮一下平均 200-400px，原 25 行=700px 缓冲区在快速滚动
// 时会被一下走穿，导致下一帧 visibleLogs 没跟上，用户看到的是未填充的
// padding 空白。改成 60 行=1680px 缓冲，三轮鼠标以内都不会看到空白。
const OVERSCAN = 60
// scrollTop 距离阈值：鼠标走超过半行=14px 才重算 startIndex / endIndex，
// 避免每个 pixel 都 trigger reactive 重算 visibleLogs。OVERSCAN=60 行
// 缓冲足够掩护中间未同步的帧，肉眼看不出延迟。
const SCROLL_THRESHOLD = Math.max(8, Math.floor(ITEM_HEIGHT / 2))
const LOG_PREVIEW_LIMIT = 900

const logs = shallowRef([])
const logContainer = ref(null)
const isPaused = ref(false)
const autoFollowLogs = ref(true)
const logLimit = ref(300)

// 「条数」下拉选项
//
// 上限砍到 1000：之前有 2000 选项，遇到含 traceback / 长堆栈的日志时，
// `parseCache` (logLimit*8 上限) + `highlightCache` (logLimit*4 上限)
// 加上每条 parsed 对象的 4 份字符串副本 (rawLine / rawLineLower /
// message / messageLower)，浏览器内存能膨胀到几百 MB → OOM 白屏。
// 1000 条对实际排查日志足够，需要更多请用"搜索全历史"或"导出筛选结果"。
const logLimitOptions = [
  { value: 100, label: '100 条' },
  { value: 300, label: '300 条' },
  { value: 500, label: '500 条' },
  { value: 1000, label: '1000 条' },
]
const selectedLevels = ref(['INFO', 'WARNING', 'ERROR'])
const selectedModules = ref([])
const searchKeyword = ref('')
const selectedLog = ref(null)
const selectedLogKey = ref('')
const searchInputRef = ref(null)
const compactProcessLogs = ref(localStorage.getItem('kikoerumanager.logs.compact_process_noise') === '1')

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
let fullSearchRequestSeq = 0

const parseCache = new Map()
const highlightCache = new Map()
// 不再维护命中率统计：旧版把 hits/misses 放进 ref，highlightText() 是 render-time 调用的函数，
// 每次渲染 +=1 会触发依赖计数的 computed 重算 → 视图重渲染 → 又调 highlightText → 死循环
// （Vue 'Maximum recursive updates exceeded'，对应用户截图里的红色 stack）。
// dev 体验信息删掉就彻底没问题，搜索/高亮逻辑只读 cache，永远不写 reactive。

// 后端搜索状态（用于头部小标签展示，不进入 render path 修改）
const lastSearchScanMb = ref(0)
const lastSearchStoppedEarly = ref(false)

const moduleColors = {
  KikoeruManager: '#6d8ef7',
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
  // 全历史搜索模式下，logs.value 已经是后端按整行匹配过滤过的结果。
  // 前端如果再用 messageLower / moduleLower 过滤，会把后端命中但解析后
  // message 部分不含关键字的行（例如关键字命中在时间戳 / 路径 / access log）
  // 重新过滤掉，导致出现"X 总计 0 匹配"。这里在全历史模式下放行 keyword，
  // 仅保留级别 / 模块过滤，避免二次过滤造成搜索失效。
  const skipKeywordFilter = isFullSearch.value

  return logs.value.filter((log) => {
    if (!lvlSet.has(log.level)) return false
    if (moduleSet && !moduleSet.has(log.module)) return false
    if (compactProcessLogs.value && isProcessNoiseLog(log)) return false
    if (!termCount || skipKeywordFilter) return true
    // 消费解析阶段预先缓存的 lower-case（messageLower / moduleLower / rawLineLower），
    // 这里不再 toLowerCase，单次过滤开销从 O(n·m) 降到 O(n·k)。
    const msg = log.messageLower || ''
    const mod = log.moduleLower || ''
    const raw = log.rawLineLower || ''
    for (let i = 0; i < termCount; i += 1) {
      const term = terms[i]
      if (!msg.includes(term) && !mod.includes(term) && !raw.includes(term)) return false
    }
    return true
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
    if (isProcessNoiseLog(log)) count += 1
  }
  return count
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

// 缓存上限大幅缩小（OOM 修复）：
// 旧值 logLimit*8 / logLimit*4 在 logLimit=2000 时上限 16000 / 8000 条目，
// 单条 parsed 含 4 份字符串副本（含 4096 字节 rawLineLower），峰值可达数百 MB。
// 新值按 1.5x 冗余足够覆盖滚动 + 切刷新带来的旧条目重用，超出立即 trim。
const parseCacheMax = computed(() => Math.max(1500, Math.floor(logLimit.value * 1.5)))
const highlightCacheMax = computed(() => Math.max(600, logLimit.value))
// highlight cacheKey 长度上限：超过这个长度的（典型场景：含 traceback 的长日志）
// 直接不缓存，每次现算，避免 cache key 自身吃几 KB 内存 × 上千条目 → 几十 MB 白白占着。
const HIGHLIGHT_CACHE_KEY_MAX = 280

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

function toggleCompactProcessLogs() {
  compactProcessLogs.value = !compactProcessLogs.value
  localStorage.setItem('kikoerumanager.logs.compact_process_noise', compactProcessLogs.value ? '1' : '0')
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

  // OOM 防护：safe 太长时（典型场景：traceback / 长 JSON dump），cacheKey 自身就吃几 KB，
  // 上千条目累积下来能占几十 MB；这种情况直接现算不入 cache，hit 率损失可忽略
  // （滚动时同一长日志通常只显示 1-2 帧）。
  const willCache = safe.length <= HIGHLIGHT_CACHE_KEY_MAX
  const cacheKey = willCache ? `${termsKey}::${safe}` : ''
  if (willCache && highlightCache.has(cacheKey)) {
    return highlightCache.get(cacheKey)
  }
  const meta = buildHighlightMeta(terms)
  if (!meta) return safe
  const highlighted = safe.replace(meta.regex, (matched) => {
    const cls = meta.classMap.get(matched.toLowerCase()) || 'log-hit-0'
    return `<mark class="log-hit ${cls}">${matched}</mark>`
  })
  if (willCache) {
    // 触发更激进的瘦身：超上限时一次 trim 1/2，避免 logLimit=1000 长跑时
    // map 一直贴着 ceil 触发频繁 micro-trim 但实际没腾出空间。
    trimMapByOldest(highlightCache, highlightCacheMax.value, Math.max(200, Math.floor(highlightCacheMax.value / 2)))
    highlightCache.set(cacheKey, highlighted)
  }
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
  const buildParsed = (time, level, message) => {
    const mod = parseModule(message, line)
    const levelUpper = (level || 'INFO').toUpperCase()
    const safeRaw = typeof line === 'string' ? line : String(line || '')
    const rawLower = safeRaw.length && safeRaw.length <= RAW_LOWER_LIMIT ? safeRaw.toLowerCase() : ''
    const parsed = {
      rawLine: safeRaw,
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
  // 60 → 100：原阈值一行=28px 之内在顶下一个行高的位置就会反复在
  // true/false 间跳变，导致 autoFollow 反复切换 → increment 路径重复触发
  // smoothScrollToBottom。100px 约 3.5 行，容忍一下鼠标滚轮调整仍锁住 auto follow。
  return scrollHeight - st - clientHeight < 100
}

function onScroll(e) {
  latestScrollTop = e.target.scrollTop
  if (scrollRafId) return
  scrollRafId = requestAnimationFrame(() => {
    // 距离阈值节流：快速滚轮时鼠标每帧可能只走 1-2px，避免每 1px
    // 都触发 scrollTop ref 更新 → startIndex/endIndex/visibleLogs/paddingTop
    // /paddingBottom 全量重算 + DOM diff。只有走过半行才让 reactive 跳，
    // OVERSCAN=60 行 足够掏住中间所有未同步的帧。
    if (Math.abs(latestScrollTop - scrollTop.value) >= SCROLL_THRESHOLD) {
      scrollTop.value = latestScrollTop
    }
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
  // 原来 mix 了 easeOutCubic + easeOutQuint 两条曲线，动画尾部有个“二次减
  // 速”拐点，在高频调用场景（点 跳到底部 / 手动滚动后释放）被看出是个
  // 奇怪的“双货”。只保留 easeOutCubic 后动画更贴近 macOS / iOS 滚动手感。
  const duration = Math.min(260, Math.max(120, Math.abs(distance) * 0.07))
  const t0 = performance.now()
  const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3)

  const tick = (ts) => {
    const p = Math.min(1, (ts - t0) / duration)
    el.scrollTop = start + distance * easeOutCubic(p)
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
    // OOM 修复：每次刷新后兜底瘦身，一次清 1/2 而不是 1/6，避免每 4 秒触发的
    // 刷新回调让 map 长期贴顶。
    trimMapByOldest(parseCache, parseCacheMax.value, Math.max(200, Math.floor(parseCacheMax.value / 2)))
    trimMapByOldest(highlightCache, highlightCacheMax.value, Math.max(150, Math.floor(highlightCacheMax.value / 2)))
    lastFetchMs.value = Math.round(performance.now() - t0)
    await nextTick()
    // 增量刷新后跳底不走 smooth 动画：之前每 5s 轮询新日志进来都跱 280ms
    // easing，如果用户正在手动滚动 / 选中某行，动画会把他顶走；多帧连续
    // 增量进来时连续启新动画互相打断 → 视觉抖。不走动画直接 scrollTop，
    // 才是主流 tail -f 体验。手动点头部「跳到底部」按钮仍走 smooth。
    if (shouldFollow && !isPaused.value) scrollToBottom(false)
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
    // 同时清 parseCache：之前只清 highlightCache，parseCache 残留的几千条 parsed 对象
    // 直到下次刷新触发 trim 才会被丢弃，是「点了清空但内存没下来」的常见误解。
    parseCache.clear()
    highlightCache.clear()
    if (fullSearchAbortController) {
      try { fullSearchAbortController.abort() } catch {}
      fullSearchAbortController = null
    }
    clearSelectedLog()
    lastLogSignature = ''
    nextOffset = -1
    incrementalCount.value = 0
    fullSearchCursor.value = 0
    fullSearchHasMore.value = false
    fullSearchTotal.value = 0
    fullSearchPageStart.value = 0
    lastSearchScanMb.value = 0
    lastSearchStoppedEarly.value = false
    isSearchLoading.value = false
    scrollTop.value = 0
    ElMessage.success('日志视图已清空')
  } catch (_) {}
}

function onLimitChange() {
  nextOffset = -1
  // OOM 修复：从大 limit 切到小 limit 时主动清空缓存，避免旧条目要等下次刷新
  // 触发 trim 才被释放（中间窗口内 GC 难以回收，是切换刷条数后内存继续涨的根因）。
  parseCache.clear()
  highlightCache.clear()
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
    triggerRef(logs)
    restoreSelectedLog()
    lastFetchMs.value = Math.round(performance.now() - t0)
    await nextTick()
    scrollTop.value = 0
    if (logContainer.value) logContainer.value.scrollTop = 0
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

// 搜索关键词变化时主动清 highlightCache：旧 termsKey 的条目已经永远不会再被命中
// （cacheKey 含 termsKey，新 terms 一定走新 cacheKey），但仍占内存直到下次 trim。
// 直接清掉避免内存继续涨。debounce 一下避免用户快速打字时 cache 反复清空。
let highlightCacheClearTimer = null
watch(
  () => searchKeyword.value,
  () => {
    if (highlightCacheClearTimer) clearTimeout(highlightCacheClearTimer)
    highlightCacheClearTimer = setTimeout(() => {
      highlightCache.clear()
      highlightCacheClearTimer = null
    }, 350)
  }
)

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
  if (highlightCacheClearTimer) clearTimeout(highlightCacheClearTimer)
  if (scrollRafId) cancelAnimationFrame(scrollRafId)
  if (smoothScrollRafId) cancelAnimationFrame(smoothScrollRafId)
  // 取消未完搜索请求，避免页面销毁后老响应仍试图写 reactive
  if (fullSearchAbortController) {
    try { fullSearchAbortController.abort() } catch {}
    fullSearchAbortController = null
  }
  // 离开页面时主动释放缓存，回到列表 / 库存等其他页面后内存能立即降下来
  parseCache.clear()
  highlightCache.clear()
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

.log-action-btn:hover svg {
  transform: rotate(-8deg) scale(1.08);
}

.log-action-btn svg {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.log-action-btn:active { transform: scale(0.96); }
.log-action-btn--success { border-color: #bbf7d0; background: #f0fdf4; color: #16a34a; }
.log-action-btn--warning { border-color: #fde68a; background: #fffbeb; color: #b45309; }
.log-action-btn--danger  { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
.log-action-btn--default:hover { border-color: #94a3b8; background: #f8fafc; }

.log-manager-shell {
  overflow: hidden;
  border: 1px solid rgba(203, 213, 225, 0.72);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(248, 250, 252, 0.86)),
    radial-gradient(circle at top left, rgba(99, 102, 241, 0.12), transparent 34%);
  box-shadow:
    0 24px 70px rgba(15, 23, 42, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
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
  border-radius: 999px;
  font-family: var(--font-body);
  font-size: 10px;
  font-weight: 800;
  line-height: 16px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.74);
}

.log-file-badge.is-main {
  border: 1px solid rgba(52, 211, 153, 0.32);
  background: linear-gradient(180deg, rgba(236, 253, 245, 0.98), rgba(209, 250, 229, 0.84));
  color: #047857;
}

.log-file-badge.is-backup {
  border: 1px solid rgba(129, 140, 248, 0.36);
  background: linear-gradient(180deg, rgba(238, 242, 255, 0.98), rgba(224, 231, 255, 0.86));
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
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
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

:global(html.kikoerumanager-dark .log-manager-shell) {
  border-color: rgba(148, 163, 184, 0.24);
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.91)),
    radial-gradient(circle at top left, rgba(99, 102, 241, 0.2), transparent 34%) !important;
  color: #dbeafe;
}

:global(html.kikoerumanager-dark .log-manager-header),
:global(html.kikoerumanager-dark .log-manager-footer) {
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(30, 41, 59, 0.72);
}

:global(html.kikoerumanager-dark .log-manager-icon),
:global(html.kikoerumanager-dark .log-manager-close),
:global(html.kikoerumanager-dark .log-stat-card),
:global(html.kikoerumanager-dark .log-policy-card),
:global(html.kikoerumanager-dark .log-file-panel) {
  border-color: rgba(148, 163, 184, 0.2);
  background: rgba(30, 41, 59, 0.72);
  color: #cbd5e1;
}

:global(html.kikoerumanager-dark .log-manager-shell .text-slate-950),
:global(html.kikoerumanager-dark .log-manager-shell .text-slate-900),
:global(html.kikoerumanager-dark .log-manager-shell .text-slate-800),
:global(html.kikoerumanager-dark .log-manager-shell .text-slate-700) {
  color: #f8fafc !important;
}

:global(html.kikoerumanager-dark .log-manager-shell .text-slate-600),
:global(html.kikoerumanager-dark .log-manager-shell .text-slate-500),
:global(html.kikoerumanager-dark .log-manager-shell .text-slate-400) {
  color: #94a3b8 !important;
}

:global(html.kikoerumanager-dark .log-file-head) {
  border-color: rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.76);
  color: #94a3b8;
}

:global(html.kikoerumanager-dark .log-file-row) {
  border-color: rgba(148, 163, 184, 0.14);
}

:global(html.kikoerumanager-dark .log-file-row:hover) {
  background: rgba(51, 65, 85, 0.34);
}

:global(html.kikoerumanager-dark .log-policy-card code) {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(15, 23, 42, 0.78);
  color: #bfdbfe;
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
  /* 锁住滚动不穿透到父容器：鼠标滚轮在顶部 / 底部边界不会拖动页面。 */
  overscroll-behavior: contain;
  /* 提示浏览器这是个常滚动容器，提前提升为独立 compositor layer， 
     避免滚动时反复重建 repaint layer。配合下面 .log-line 的
     content-visibility 一起吃下 5万行 list 也不卸肉。 */
  contain: layout paint;
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
  /*
   * 去掉 background-color 动画：虚拟滚动下每个进入视口的新 row 都会跳
   * 0.12s transition，鼠标连续滚轮时 上调起来是一片闪烁的 hover/选中
   * 状态跳动。hover 是拖动中一闪而过的东西，没必要上动画。
   *
   * content-visibility: auto + contain-intrinsic-size: 28px：
   * 让浏览器原生跳过不可见 row 的 layout / paint，list 上万行时才能
   * 保着滚动 60fps。OVERSCAN 以外的行被跳过，与虚拟滚动同一个思路但
   * 是在 GPU/compositor 层。
   *
   * contain: layout style paint：告诉浏览器每行是独立子树，变化不要反作用到
   * 老哥 / 兄弟。在增量插行 / 选中成色变时只重画该行，不需重取其它行 layout。
   */
  content-visibility: auto;
  contain-intrinsic-size: 28px;
  contain: layout style paint;
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
  /* 时间戳数字等宽：避免不同字体下“1”与“0”宽度不同导致上下行时间戳右侧错位。 */
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
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
  /* 固定列宽区间：之前没设 min/max，“RJ字幕”与“CONFIG SAVE” 长短不同
     会抨 message 起点 → 上下行 message 错位。锁 86px、超出 ellipsis，
     让代码里所有模块名都进同一个可预测的区域。 */
  width: 86px;
  min-width: 86px;
  max-width: 86px;
  padding: 0 7px;
  border-radius: 4px;
  color: #ffffff;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 18px;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-mod.is-empty {
  background: transparent !important;
  visibility: hidden;
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
