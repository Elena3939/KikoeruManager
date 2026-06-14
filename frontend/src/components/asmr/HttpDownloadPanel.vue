<template>
  <section class="asmr-card http-download-panel" :class="{ 'is-baidu-netdisk': isBaidu }">
    <header class="asmr-card-head">
      <div class="asmr-card-head-title">
        <CloudDownload :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
        <div>
          <h2>{{ panelTitle }}</h2>
          <p class="asmr-card-head-subtitle">{{ panelSubtitle }}</p>
        </div>
      </div>
      <div class="asmr-card-head-actions">
        <StatefulButton
          class="asmr-mini-btn"
          unstyled
          :show-default-icons="false"
          :success-hold="1000"
          @click="loadHealth"
        >
          <template #prefix="{ state }">
            <span class="asmr-health-action-icon" :class="`is-${state}`" aria-hidden="true">
              <Loader2 v-if="state === 'loading'" :size="12" :stroke-width="2.4" />
              <RefreshCw v-else-if="state === 'idle'" :size="12" :stroke-width="2.4" />
              <Check v-else-if="state === 'success'" :size="12" :stroke-width="2.4" />
              <X v-else :size="12" :stroke-width="2.4" />
            </span>
          </template>
          {{ healthActionLabel }}
        </StatefulButton>
        <button v-if="hasTasks" class="asmr-mini-btn is-primary" type="button" @click="$emit('open-workbench')">
          <Download :size="12" :stroke-width="2.4" />
          下载工作台
        </button>
      </div>
    </header>

    <div class="asmr-card-body http-download-body">
      <div class="http-download-health" :class="{ ok: health?.ok, bad: health && !health.ok }">
        <span class="http-health-dot"></span>
        <span>{{ healthText }}</span>
        <span v-if="health?.download_root" class="http-health-path">{{ health.download_root }}</span>
      </div>

      <textarea
        v-model="urlText"
        class="http-url-input"
        rows="5"
        :placeholder="inputPlaceholder"
      ></textarea>

      <div class="http-download-options">
        <label class="http-field">
          <span>目标子目录</span>
          <input v-model.trim="targetSubdir" class="http-input" type="text" placeholder="可选，例如 gofile/RJ123456">
        </label>
        <label v-if="isBaidu" class="http-field">
          <span>保存为文件夹名</span>
          <input v-model.trim="outputFolderName" class="http-input" type="text" placeholder="可选，例如 RJ123456 完整版">
        </label>
        <label class="http-field">
          <span>冲突策略</span>
          <AppDropdown
            v-model="conflictPolicy"
            :options="conflictOptions"
            class="http-policy-dd"
            :width="150"
          />
        </label>
        <label class="http-field grow">
          <span>批次名</span>
          <input v-model.trim="batchName" class="http-input" type="text" placeholder="可选，任务中心和工作台显示用">
        </label>
      </div>

      <div class="http-actions">
        <button class="asmr-mini-btn" type="button" :class="{ 'is-querying': previewing }" :disabled="previewing || !parsedUrls.length" @click="preview">
          <Search :size="12" :stroke-width="2.4" :class="{ 'is-querying': previewing }" />
          {{ previewing ? '预览中...' : `预览 ${parsedUrls.length || ''}` }}
        </button>
        <button class="asmr-mini-btn is-primary" type="button" :disabled="starting || !selectedOkCount" @click="start">
          <Download :size="12" :stroke-width="2.4" />
          {{ starting ? '创建中...' : `开始下载 (${selectedDownloadFileCount})` }}
        </button>
      </div>
    </div>

    <el-dialog
      v-model="previewDialogVisible"
      :show-close="false"
      destroy-on-close
      class="custom-preview-modal http-download-preview-modal"
      align-center
      :append-to-body="false"
      modal-class="custom-preview-overlay http-download-preview-overlay"
    >
      <div class="window http-preview-window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden">
        <div class="window-header flex items-center justify-between px-7 py-4">
          <h1 class="title text-2xl font-bold text-slate-900 tracking-tight">创建{{ panelTitle }}任务</h1>
          <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="previewDialogVisible = false">
            <X :size="20" :stroke-width="2" />
          </button>
        </div>

        <div class="tabs-row px-7 pt-1 pb-2 flex items-center gap-1.5 overflow-x-auto no-scrollbar">
          <button
            type="button"
            class="tab-chip px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center gap-1 border"
            :class="allPreviewSelectionState === 'all' ? 'tab-chip-active' : (allPreviewSelectionState === 'partial' ? 'tab-chip-partial' : 'tab-chip-idle')"
            :disabled="!okPreviewCount"
            @click="toggleAllPreviewSelection"
          >
            <span>全部</span>
            <span class="tab-count">{{ selectedOkCount }}/{{ okPreviewCount }}</span>
          </button>
          <button
            v-for="chip in previewSourceChips"
            :key="chip.key"
            type="button"
            class="tab-chip px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center gap-1 border"
            :class="chip.state === 'all' ? 'tab-chip-active' : (chip.state === 'partial' ? 'tab-chip-partial' : 'tab-chip-idle')"
            @click="togglePreviewSource(chip)"
          >
            <span>{{ chip.label }}</span>
            <span class="tab-count">{{ chip.selected }}/{{ chip.total }}</span>
          </button>
          <button
            type="button"
            class="preview-selection-toggle ml-auto"
            :class="{ 'is-clear': allPreviewSelectionState === 'all' }"
            :disabled="!okPreviewCount"
            @click="toggleAllPreviewSelection"
          >
            <X v-if="allPreviewSelectionState === 'all'" :size="12" :stroke-width="2.6" />
            <Check v-else :size="12" :stroke-width="2.6" />
            <span>{{ allPreviewSelectionState === 'all' ? '清空' : '全选' }}</span>
          </button>
        </div>

        <div class="http-preview-content content-grid flex-1 flex gap-4 px-7 py-2 min-h-0">
          <div class="left-column w-[350px] flex flex-col gap-4">
            <section class="glass-panel glass-card http-preview-settings-card flex-1 rounded-2xl p-5 overflow-y-auto no-scrollbar">
              <div class="space-y-6">
                <section class="space-y-4">
                  <div class="section-head space-y-1">
                    <h2>下载设置</h2>
                    <p>{{ previewStatusText }}</p>
                  </div>
                  <div class="http-preview-status-card">
                    <div>
                      <div class="http-preview-status-title">{{ previewStatusTitle }}</div>
                      <div class="http-preview-status-sub">{{ previewing ? '正在连接源站' : '当前预览状态' }}</div>
                    </div>
                    <span class="http-preview-status-count">{{ selectedOkCount }}/{{ okPreviewCount }}</span>
                  </div>
                  <div class="http-preview-progress">
                    <div class="http-preview-progress-fill" :style="{ width: `${previewProgress}%` }"></div>
                  </div>
                </section>

                <section class="space-y-4">
                  <div class="section-head compact-head">
                    <h2>落盘信息</h2>
                  </div>
                  <div class="summary-stack space-y-2 text-sm text-slate-600">
                    <div>目标子目录 <span>{{ targetSubdir || '下载根目录' }}</span></div>
                    <div v-if="isBaidu">保存文件夹 <span>{{ outputFolderName || '按分享标题' }}</span></div>
                    <div>冲突策略 <span>{{ conflictPolicyLabel }}</span></div>
                    <div>批次名 <span>{{ batchName || '自动生成' }}</span></div>
                    <div>源链接 <span>{{ parsedUrls.length }} 个</span></div>
                    <div v-if="isBaidu && health?.svip_speed">传输模式 <span>SVIP 高速</span></div>
                  </div>
                </section>

                <section v-if="previewLogs.length" class="space-y-4">
                  <div class="section-head compact-head">
                    <h2>解析日志</h2>
                  </div>
                  <div class="http-preview-log">
                    <div v-for="entry in previewLogs" :key="entry.id" class="http-preview-log-row" :class="`is-${entry.level}`">
                      <span class="http-preview-log-time">{{ entry.time }}</span>
                      <span class="http-preview-log-text">{{ entry.message }}</span>
                    </div>
                  </div>
                </section>
              </div>
            </section>
          </div>

          <section class="glass-panel glass-card download-list-panel flex-1 rounded-2xl flex flex-col overflow-hidden">
            <div class="download-list-head">
              <div>
                <h2>下载列表</h2>
              </div>
              <span>{{ previewDownloadFileCount }} 文件 / {{ previewItems.length }} 分享</span>
            </div>
            <div class="download-list-scroll flex-1 overflow-auto no-scrollbar" @click="closePreviewContextMenu">
              <div v-if="previewing && !previewItems.length" class="http-preview-empty">
                <AppLoadingAnimation label="正在生成预览" variant="block" :size="118" :min-height="180" />
              </div>
              <div v-else-if="!previewItems.length" class="http-preview-empty">
                <FileIcon :size="22" :stroke-width="2.2" />
                <span>还没有预览结果</span>
              </div>
              <div v-else class="download-tree">
                <div
                  v-for="row in previewTreeRows"
                  :key="row.key"
                  class="download-tree-row"
                  :class="{
                    bad: !row.ok,
                    selected: isPreviewTreeRowSelected(row),
                    'is-dir': row.isDir,
                    'is-file': !row.isDir,
                    'is-root-leaf': !row.isDir && row.depth <= 0,
                    'is-context': previewContextMenu.rowKey === row.key,
                    'is-volume-group': Boolean(row.volumeGroup),
                  }"
                  :style="{ '--tree-depth': row.depth }"
                  @click.stop="handlePreviewTreeRowClick(row)"
                  @contextmenu.prevent.stop="openPreviewContextMenu($event, row)"
                >
                  <span class="download-tree-indent" aria-hidden="true"></span>
                  <button
                    v-if="row.isDir"
                    type="button"
                    class="download-tree-toggle"
                    :class="{ expanded: isPreviewTreeNodeExpanded(row.key) }"
                    @click.stop="togglePreviewTreeNode(row)"
                  >
                    <ChevronRight :size="13" :stroke-width="2.6" />
                  </button>
                  <span v-else class="download-tree-toggle placeholder" aria-hidden="true"></span>

                  <button
                    v-if="row.selectable || !row.ok"
                    type="button"
                    class="download-list-check relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border"
                    :class="previewTreeSelectionClass(row)"
                    :disabled="!row.ok"
                    @click.stop="togglePreviewTreeRowSelection(row)"
                  >
                    <Check v-if="previewTreeSelectionClass(row) !== 'is-off'" :size="14" />
                  </button>
                  <span v-else class="download-tree-check-placeholder" aria-hidden="true"></span>

                  <span v-if="!row.ok" class="http-preview-error-icon">
                    <AlertTriangle :size="16" :stroke-width="2.4" />
                  </span>
                  <span v-else class="http-preview-error-placeholder" aria-hidden="true"></span>

                  <Folder v-if="row.isDir" class="download-tree-kind-icon" :size="18" :stroke-width="2.35" />
                  <FileIcon v-else class="download-tree-kind-icon" :size="18" :stroke-width="2.35" />

                  <div class="download-tree-main">
                    <div class="download-tree-name-line">
                      <span
                        class="http-source-icon"
                        :class="`is-${sourceKey(row.source)}`"
                        :title="sourceLabel(row.source)"
                        :aria-label="sourceLabel(row.source)"
                      >
                        <img
                          v-if="sourceIcon(row.source) && !isSourceIconFailed(row.source)"
                          :src="sourceIcon(row.source)"
                          alt=""
                          loading="lazy"
                          decoding="async"
                          @error="markSourceIconFailed(row.source)"
                        >
                        <svg
                          v-else-if="sourceKey(row.source) === 'gofile'"
                          class="http-source-fallback-gofile"
                          viewBox="0 0 32 32"
                          aria-hidden="true"
                        >
                          <path d="M2 19.2h10.7l-.5 2.2H2z" fill="#f2b705" opacity=".88" />
                          <path d="M5.2 14.6h11.5l-.5 2.2H5.2z" fill="#f2b705" opacity=".92" />
                          <path d="M9.8 10h12l-.5 2.2H9.8z" fill="#f2b705" />
                          <path d="M14.1 5.8h8.9l3 3v13.5H14.1z" fill="#f8fafc" />
                          <path d="M22.9 5.8v3.1H26z" fill="#cbd5e1" />
                          <path d="M8.5 12.7h12.7l2-2.4h6.2l-3.6 15.9H10.4z" fill="#f3b51b" />
                        </svg>
                        <Globe2 v-else :size="15" :stroke-width="2.2" />
                      </span>
                      <span class="download-list-name http-preview-name">{{ row.name }}</span>
                      <span v-if="row.customPreview" class="baidu-custom-preview">{{ row.customPreview }}</span>
                    </div>
                    <div class="http-preview-meta">
                      <span v-if="row.isDir" class="http-preview-pass-chip">{{ row.fileCount }} 文件</span>
                      <span v-if="row.volumeGroup" class="http-preview-pass-chip">连续分卷 {{ row.volumeGroup.files.length }}</span>
                      <span v-if="!row.ok" class="http-preview-reason">{{ row.reason }}</span>
                      <span v-else-if="row.warning" class="warn">{{ row.warning }}</span>
                      <span v-if="row.passCodeText" class="http-preview-pass-chip" :class="{ warn: row.passCodeWarn }">{{ row.passCodeText }}</span>
                    </div>
                    <div v-if="row.passCodeEditable" class="baidu-pass-code-row" :class="{ invalid: row.item?.pass_code_invalid }" @click.stop>
                      <input
                        v-model.trim="row.item.pass_code"
                        class="baidu-pass-code-input"
                        type="text"
                        maxlength="12"
                        placeholder="重新输入提取码"
                        @keyup.enter.stop="applyPassCodeAndPreview(row.item)"
                      >
                      <button type="button" class="baidu-pass-code-btn" :disabled="previewing || !row.item?.pass_code" @click.stop="applyPassCodeAndPreview(row.item)">验证并重新预览</button>
                    </div>
                  </div>

                  <span v-if="!row.isDir && row.size" class="download-list-size text-xs text-slate-400 ml-4 tabular-nums">{{ formatSize(row.size) }}</span>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div
          v-if="previewContextMenu.visible"
          class="preview-context-menu"
          :style="{ left: `${previewContextMenu.x}px`, top: `${previewContextMenu.y}px` }"
          @click.stop
          @contextmenu.prevent.stop
        >
          <button
            type="button"
            :disabled="!canRefreshPreviewContextRow"
            @click="refreshPreviewContextRow"
          >
            <RefreshCw :size="13" :stroke-width="2.4" />
            <span>重新解析</span>
          </button>
          <button
            type="button"
            :disabled="!canRenamePreviewContextRow"
            @click="renamePreviewContextRow"
          >
            <PencilLine :size="13" :stroke-width="2.4" />
            <span>重命名</span>
          </button>
          <button
            type="button"
            :disabled="!canSetPasswordPreviewContextRow"
            @click="setPasswordPreviewContextRow"
          >
            <KeyRound :size="13" :stroke-width="2.4" />
            <span>设置密码</span>
          </button>
        </div>

        <div class="footer-row px-7 py-3 flex items-center justify-between">
          <div class="summary text-sm text-slate-500 font-medium">
            已选 <span class="summary-strong text-slate-900">{{ selectedDownloadFileCount }}</span> 个文件，共 <span class="summary-strong text-slate-900">{{ formatSize(selectedTotalBytes) }}</span>
          </div>
          <div class="footer-actions flex items-center gap-3">
            <button type="button" class="primary-cta px-10 h-11 rounded-xl font-bold text-white" :disabled="starting || !selectedOkCount" @click="start">
              {{ starting ? '创建中...' : '开始下载' }}
            </button>
            <button type="button" class="secondary-cta interactive-button px-10 h-11 rounded-xl font-bold" @click="previewDialogVisible = false">取消</button>
          </div>
        </div>
      </div>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { AlertTriangle, Check, ChevronRight, CloudDownload, Download, FileIcon, Folder, Globe2, KeyRound, Loader2, PencilLine, RefreshCw, Search, X } from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'
import AppLoadingAnimation from '../common/AppLoadingAnimation.vue'
import StatefulButton from '../ui/stateful-button.vue'
import { baiduNetdiskApi, httpDownloadApi } from '../../api'
import { showSystemPrompt } from '../../composables/useSystemPrompt'
import {
  getHttpDownloadPlatformMeta,
  httpDownloadPlatformsFromUrl,
} from '../common/httpDownloadPlatformMeta.js'

const DOWNLOAD_PANEL_CONFLICT_POLICIES = ['resume', 'rename', 'skip']
const DOWNLOAD_PREVIEW_CACHE_VERSION = 2
const DOWNLOAD_PREVIEW_CACHE_TTL_MS = 30 * 60 * 1000
const DOWNLOAD_PREVIEW_CACHE_SESSION_ID = getDownloadPreviewCacheSessionId()

function getDownloadPreviewCacheSessionId() {
  const key = '__KIKOERUMANAGER_DOWNLOAD_PREVIEW_CACHE_SESSION_ID__'
  if (typeof window === 'undefined') return 'server'
  if (!window[key]) window[key] = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return window[key]
}

const props = defineProps({
  provider: { type: String, default: 'http' },
  hasTasks: { type: Boolean, default: false },
  draft: { type: Object, default: () => ({}) }
})

const emit = defineEmits(['started', 'open-workbench', 'update:draft'])

const initialDraft = normalizeDownloadPanelDraft(props.draft)
const urlText = ref(initialDraft.urlText)
const targetSubdir = ref(initialDraft.targetSubdir)
const outputFolderName = ref(initialDraft.outputFolderName)
const batchName = ref(initialDraft.batchName)
const conflictPolicy = ref(initialDraft.conflictPolicy)
const previewing = ref(false)
const starting = ref(false)
const healthLoading = ref(false)
const health = ref(null)
const previewDialogVisible = ref(false)
const previewItems = ref([])
const previewNeedsMaterialize = ref(false)
const previewLogs = ref([])
const previewProgress = ref(0)
const selectedPreviewKeys = ref(new Set())
const failedSourceIcons = ref(new Set())
const expandedPreviewTreeKeys = ref(new Set())
const previewCacheInputSignature = ref('')
const previewContextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  rowKey: '',
  row: null,
})

const conflictOptions = [
  { value: 'resume', label: '断点续传' },
  { value: 'rename', label: '自动改名' },
  { value: 'skip', label: '已存在跳过' }
]

const isBaidu = computed(() => String(props.provider || '').trim() === 'baidu')
const activeApi = computed(() => isBaidu.value ? baiduNetdiskApi : httpDownloadApi)
const panelTitle = computed(() => isBaidu.value ? '百度网盘下载' : 'HTTP 外链下载')
const panelSubtitle = computed(() => isBaidu.value ? '百度分享链接 / 提取码 / 官方登录态直下' : 'HTTP 直链 / Gofile / Transfer.it / OneDrive / Google Drive / PikPak')
const inputPlaceholder = computed(() => isBaidu.value
  ? '粘贴百度网盘分享链接，一行一个。支持链接----提取码、提取码下一行，或带 ?pwd= 的分享链接。'
  : '粘贴 HTTP/HTTPS 直链或分享链接，一行一个。支持 Gofile、Transfer.it、OneDrive、Google Drive、PikPak。'
)
const healthActionLabel = computed(() => isBaidu.value ? '检测百度登录态' : '检测 aria2')
const BAIDU_SHARE_CODE_SEPARATOR = '----'
const START_TIMEOUT_RECOVERY_WINDOW_MS = 10 * 1000
const HTTP_DIRECT_PREVIEW_TIMEOUT_MS = 45 * 1000
const HTTP_SHARE_PREVIEW_TIMEOUT_MS = 120 * 1000

function normalizeDownloadPanelDraft(value = {}) {
  const policy = String(value?.conflictPolicy || '').trim()
  return {
    urlText: String(value?.urlText || ''),
    targetSubdir: String(value?.targetSubdir || ''),
    outputFolderName: String(value?.outputFolderName || ''),
    batchName: String(value?.batchName || ''),
    conflictPolicy: DOWNLOAD_PANEL_CONFLICT_POLICIES.includes(policy) ? policy : 'resume',
    previewCache: normalizePreviewCache(value?.previewCache)
  }
}

function normalizePreviewCache(value = {}) {
  if (!value || typeof value !== 'object') return null
  const version = Number(value.version || 0)
  if (version !== DOWNLOAD_PREVIEW_CACHE_VERSION) return null
  if (String(value.sessionId || '') !== DOWNLOAD_PREVIEW_CACHE_SESSION_ID) return null
  const cachedAt = Number(value.cachedAt || 0)
  if (!Number.isFinite(cachedAt) || cachedAt <= 0) return null
  const age = Date.now() - cachedAt
  if (age < -60 * 1000 || age > DOWNLOAD_PREVIEW_CACHE_TTL_MS) return null
  const items = Array.isArray(value.items) ? value.items.filter(item => item && typeof item === 'object') : []
  if (!items.length) return null
  return {
    version: DOWNLOAD_PREVIEW_CACHE_VERSION,
    sessionId: DOWNLOAD_PREVIEW_CACHE_SESSION_ID,
    provider: String(value.provider || ''),
    inputSignature: String(value.inputSignature || ''),
    items,
    selectedKeys: Array.isArray(value.selectedKeys) ? value.selectedKeys.map(key => String(key || '')).filter(Boolean) : [],
    needsMaterialize: Boolean(value.needsMaterialize),
    logs: Array.isArray(value.logs) ? value.logs.slice(-80) : [],
    progress: Number(value.progress || 100),
    expandedKeys: Array.isArray(value.expandedKeys) ? value.expandedKeys.map(key => String(key || '')).filter(Boolean) : [],
    cachedAt,
  }
}

function previewCacheSignature(cache) {
  const normalized = normalizePreviewCache(cache)
  if (!normalized) return ''
  return JSON.stringify({
    version: normalized.version,
    sessionId: normalized.sessionId,
    provider: normalized.provider,
    inputSignature: normalized.inputSignature,
    items: normalized.items,
    selectedKeys: normalized.selectedKeys,
    needsMaterialize: normalized.needsMaterialize,
    logs: normalized.logs,
    progress: normalized.progress,
    expandedKeys: normalized.expandedKeys,
  })
}

function previewInputSignature() {
  return JSON.stringify({
    provider: isBaidu.value ? 'baidu' : 'http',
    urls: parsedUrls.value,
    targetSubdir: String(targetSubdir.value || ''),
    outputFolderName: String(outputFolderName.value || ''),
    conflictPolicy: String(conflictPolicy.value || ''),
  })
}

function currentPreviewCache() {
  if (!previewItems.value.length) return null
  const signature = previewInputSignature()
  if (previewCacheInputSignature.value && previewCacheInputSignature.value !== signature) return null
  return {
    version: DOWNLOAD_PREVIEW_CACHE_VERSION,
    sessionId: DOWNLOAD_PREVIEW_CACHE_SESSION_ID,
    provider: isBaidu.value ? 'baidu' : 'http',
    inputSignature: signature,
    items: sanitizePreviewItemsForCache(previewItems.value),
    selectedKeys: [...selectedPreviewKeys.value],
    needsMaterialize: Boolean(previewNeedsMaterialize.value),
    logs: previewLogs.value.slice(-80),
    progress: Number(previewProgress.value || 100),
    expandedKeys: [...expandedPreviewTreeKeys.value],
    cachedAt: Date.now(),
  }
}

function sanitizePreviewItemsForCache(items) {
  return JSON.parse(JSON.stringify(items || []))
}

function restorePreviewCache(cache) {
  const normalized = normalizePreviewCache(cache)
  if (!normalized) return false
  if (normalized.provider !== (isBaidu.value ? 'baidu' : 'http')) return false
  if (normalized.inputSignature !== previewInputSignature()) return false
  previewItems.value = sanitizePreviewItemsForCache(normalized.items)
  selectedPreviewKeys.value = new Set(normalized.selectedKeys)
  previewNeedsMaterialize.value = Boolean(normalized.needsMaterialize)
  previewLogs.value = normalized.logs || []
  previewProgress.value = Number(normalized.progress || 100)
  expandedPreviewTreeKeys.value = new Set(normalized.expandedKeys || [])
  previewCacheInputSignature.value = normalized.inputSignature
  if (!expandedPreviewTreeKeys.value.size) expandDefaultPreviewTreeRows(previewItems.value)
  return true
}

function restoreOrClearPreviewCache(cache) {
  if (restorePreviewCache(cache)) return true
  if (previewItems.value.length) clearPreviewCacheState()
  return false
}

function persistPreviewCacheFromState() {
  const draft = currentDownloadPanelDraft()
  if (isSameDownloadPanelDraft(draft, props.draft)) return
  emit('update:draft', draft)
}

function clearPreviewCacheState() {
  previewItems.value = []
  previewNeedsMaterialize.value = false
  previewLogs.value = []
  previewProgress.value = 0
  selectedPreviewKeys.value = new Set()
  expandedPreviewTreeKeys.value = new Set()
  previewCacheInputSignature.value = ''
  closePreviewContextMenu()
}

function currentDownloadPanelDraft() {
  const cache = currentPreviewCache()
  return normalizeDownloadPanelDraft({
    urlText: urlText.value,
    targetSubdir: targetSubdir.value,
    outputFolderName: outputFolderName.value,
    batchName: batchName.value,
    conflictPolicy: conflictPolicy.value,
    previewCache: cache
  })
}

function isSameDownloadPanelDraft(left, right) {
  const a = normalizeDownloadPanelDraft(left)
  const b = normalizeDownloadPanelDraft(right)
  return a.urlText === b.urlText
    && a.targetSubdir === b.targetSubdir
    && a.outputFolderName === b.outputFolderName
    && a.batchName === b.batchName
    && a.conflictPolicy === b.conflictPolicy
    && previewCacheSignature(a.previewCache) === previewCacheSignature(b.previewCache)
}

const parsedUrls = computed(() => {
  const rows = String(urlText.value || '')
    .split(/[\r\n]+/)
    .map(item => item.trim())
    .filter(Boolean)
  return isBaidu.value ? normalizeBaiduInputRows(rows) : [...new Set(rows)]
})

function normalizeBaiduInputRows(rows) {
  const result = []
  const seen = new Map()
  let lastBaiduIndex = null
  for (const row of rows || []) {
    const value = String(row || '').trim()
    if (!value) continue
    const normalized = normalizeBaiduShareLine(value)
    if (isBaiduShareUrl(normalized)) {
      const key = baiduShareIdentity(normalized)
      if (seen.has(key)) {
        const existingIndex = seen.get(key)
        if (!baiduShareHasCode(result[existingIndex]) && baiduShareHasCode(normalized)) {
          result[existingIndex] = normalized
        }
        lastBaiduIndex = existingIndex
        continue
      }
      result.push(normalized)
      seen.set(key, result.length - 1)
      lastBaiduIndex = result.length - 1
      continue
    }
    const code = baiduPassCodeFromText(value)
    if (code && lastBaiduIndex !== null) {
      if (!baiduShareHasCode(result[lastBaiduIndex])) {
        result[lastBaiduIndex] = appendBaiduPassCode(result[lastBaiduIndex], code)
      }
      continue
    }
    result.push(value)
  }
  return result
}

function normalizeBaiduShareLine(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.includes(BAIDU_SHARE_CODE_SEPARATOR)) {
    const separatorIndex = text.lastIndexOf(BAIDU_SHARE_CODE_SEPARATOR)
    const left = text.slice(0, separatorIndex).trim()
    const right = text.slice(separatorIndex + BAIDU_SHARE_CODE_SEPARATOR.length).trim()
    const code = baiduPassCodeFromText(right)
    if (code && isBaiduShareUrl(left)) {
      return appendBaiduPassCode(left, code)
    }
  }
  const inline = text.match(
    /^(https?:\/\/\S+?)\s+(?:提取码|访问码|密码|密碼|pwd|passcode|pass_code|code)?\s*[:：= ]?\s*([A-Za-z0-9]{4,12})\s*$/i,
  )
  if (inline && isBaiduShareUrl(inline[1])) {
    return appendBaiduPassCode(inline[1].trim(), inline[2].trim())
  }
  return text
}

function isBaiduShareUrl(value) {
  const text = String(value || '').trim().toLowerCase()
  return text.startsWith('http://') || text.startsWith('https://')
    ? (
        text.includes('pan.baidu.com')
        || text.includes('yun.baidu.com')
        || text.includes('eyun.baidu.com')
      )
    : false
}

function baiduPassCodeFromText(value) {
  const match = String(value || '').trim().match(
    /(?:提取码|访问码|密码|密碼|pwd|passcode|pass_code|code)?\s*[:：= ]?\s*([A-Za-z0-9]{4,12})$/i,
  )
  return match ? match[1].trim() : ''
}

function baiduShareHasCode(value) {
  return /[?&](?:pwd|password|passcode|pass_code|code)=/i.test(String(value || ''))
}

function appendBaiduPassCode(shareUrl, code) {
  const normalizedCode = String(code || '').trim()
  const normalizedUrl = String(shareUrl || '').trim()
  if (!normalizedUrl || !normalizedCode || baiduShareHasCode(normalizedUrl)) return normalizedUrl
  return `${normalizedUrl}${normalizedUrl.includes('?') ? '&' : '?'}pwd=${encodeURIComponent(normalizedCode)}`
}

function stripBaiduPassCode(shareUrl) {
  return String(shareUrl || '').trim()
    .replace(/([?&])(?:pwd|password|passcode|pass_code|code)=[^&#]*/ig, '$1')
    .replace(/\?&/g, '?')
    .replace(/[?&](#|$)/g, '$1')
    .replace(/[?&]+$/g, '')
}

function replaceBaiduPassCode(shareUrl, code) {
  return appendBaiduPassCode(stripBaiduPassCode(shareUrl), code)
}

function baiduShareIdentity(value) {
  return stripBaiduPassCode(value)
}

function isBaiduPassCodeLine(value) {
  const text = String(value || '').trim()
  return Boolean(text && !isBaiduShareUrl(text) && baiduPassCodeFromText(text))
}

const okPreviewItems = computed(() => previewItems.value.filter(item => item.ok))
const okPreviewCount = computed(() => okPreviewItems.value.length)
const previewDownloadFileCount = computed(() => okPreviewItems.value.reduce((sum, item) => sum + previewItemFileCount(item), 0))
const selectedOkItems = computed(() => okPreviewItems.value.filter(item => selectedPreviewKeys.value.has(previewItemKey(item))))
const selectedOkCount = computed(() => selectedOkItems.value.length)
const selectedDownloadFileCount = computed(() => selectedOkItems.value.reduce((sum, item) => sum + previewItemFileCount(item), 0))
const selectedTotalBytes = computed(() => selectedOkItems.value.reduce((sum, item) => sum + Number(item.size_bytes || item.size || 0), 0))
const allPreviewSelectionState = computed(() => {
  if (!okPreviewCount.value || !selectedOkCount.value) return 'none'
  return selectedOkCount.value === okPreviewCount.value ? 'all' : 'partial'
})
const previewSourceChips = computed(() => {
  const map = new Map()
  okPreviewItems.value.forEach(item => {
    const key = sourceKey(item.source)
    if (!map.has(key)) {
      map.set(key, {
        key,
        label: sourceLabel(item.source),
        items: [],
        total: 0,
        selected: 0,
        state: 'none'
      })
    }
    const chip = map.get(key)
    chip.items.push(item)
    chip.total += 1
    if (isPreviewItemSelected(item)) chip.selected += 1
  })
  return [...map.values()].map(chip => ({
    ...chip,
    state: chip.selected === 0 ? 'none' : (chip.selected === chip.total ? 'all' : 'partial')
  }))
})
const conflictPolicyLabel = computed(() => conflictOptions.find(item => item.value === conflictPolicy.value)?.label || conflictPolicy.value)
const previewTreeRoots = computed(() => buildPreviewTreeRoots(previewItems.value))
const previewTreeRows = computed(() => flattenPreviewTreeRows(previewTreeRoots.value))
const canRefreshPreviewContextRow = computed(() => Boolean(previewContextMenu.row) && !previewing.value)
const canRenamePreviewContextRow = computed(() => canRenamePreviewTreeRow(previewContextMenu.row))
const canSetPasswordPreviewContextRow = computed(() => canSetPasswordPreviewTreeRow(previewContextMenu.row))

const previewStatusTitle = computed(() => {
  if (previewing.value) return '生成预览中'
  if (!previewItems.value.length) return '等待预览'
  if (okPreviewCount.value) return `已解析 ${okPreviewCount.value} 个可下载项`
  return '没有可下载项'
})

const previewStatusText = computed(() => {
  if (previewing.value) return `正在整理 ${parsedUrls.value.length} 个来源`
  if (!previewItems.value.length) return isBaidu.value ? '分享链接和提取码可分行粘贴，先预览再勾选下载。' : '粘贴多个链接后一行一个，先预览再勾选下载。'
  const failed = previewItems.value.length - okPreviewCount.value
  return failed ? `${failed} 项解析失败或不可直接下载` : '解析完成，可以勾选需要下载的项目。'
})

const healthText = computed(() => {
  if (healthLoading.value) return isBaidu.value ? '正在检测百度登录态...' : '正在检测 aria2...'
  if (!health.value) return isBaidu.value ? '尚未检测百度登录态' : '尚未检测 aria2'
  if (health.value.ok) {
    if (isBaidu.value) {
      const account = health.value.account || {}
      const accountText = account.name || account.netdisk_name ? ` · ${account.name || account.netdisk_name}` : ''
      const svip = health.value.svip_speed ? ' · SVIP 高速' : ''
      return `百度登录态可用${accountText}${svip}`
    }
    const pikpak = health.value.pikpak_enabled ? (health.value.pikpak_ready ? ' · PikPak 已配置' : ' · PikPak 缺配置') : ''
    const gofile = health.value.gofile_ready ? ` · ${health.value.gofile_token_configured ? 'Gofile Token 已配置' : 'Gofile 临时账号'}` : ''
    return `aria2 可用${health.value.version?.version ? ` · ${health.value.version.version}` : ''}${gofile}${pikpak}`
  }
  return health.value.message || (isBaidu.value ? '百度登录态不可用' : 'aria2 不可用')
})

async function loadHealth() {
  const targetName = isBaidu.value ? '百度登录态' : 'aria2'
  healthLoading.value = true
  try {
    health.value = await activeApi.value.health()
    if (health.value?.ok) {
      ElMessage.success(`${targetName} 可用`)
    } else {
      ElMessage.warning(health.value?.message || `${targetName} 不可用`)
    }
  } catch (error) {
    health.value = { ok: false, message: error.response?.data?.detail || error.message || '检测失败' }
    ElMessage.error(health.value.message)
  } finally {
    healthLoading.value = false
  }
}

async function preview(options = {}) {
  const forceRefresh = Boolean(options?.forceRefresh)
  if (!parsedUrls.value.length) return ElMessage.warning('先粘贴至少一个下载链接')
  if (!forceRefresh && restorePreviewCache(props.draft?.previewCache)) {
    previewDialogVisible.value = true
    addPreviewLog('已使用缓存预览结果', 'success')
    persistPreviewCacheFromState()
    return
  }
  previewDialogVisible.value = true
  previewing.value = true
  clearPreviewCacheState()
  previewProgress.value = 8
  previewLogs.value = []
  addPreviewLog(forceRefresh ? `跳过缓存，重新解析 ${parsedUrls.value.length} 个来源` : `开始生成 ${parsedUrls.value.length} 个来源的预览`, forceRefresh ? 'warning' : 'info')
  parsedUrls.value.forEach((url, index) => {
    addPreviewLog(`[${index + 1}/${parsedUrls.value.length}] 处理 ${sourceLabel(sourceFromUrl(url))}`)
  })
  try {
    const urls = parsedUrls.value
    if (isBaidu.value) {
      const result = await baiduNetdiskApi.preview({
        urls,
        targetSubdir: targetSubdir.value,
        outputFolderName: outputFolderName.value,
        conflictPolicy: conflictPolicy.value,
        timeout: 60000
      })
      previewItems.value = result.items || []
      previewCacheInputSignature.value = previewInputSignature()
      previewNeedsMaterialize.value = true
      selectedPreviewKeys.value = new Set((result.selected_keys || []).filter(Boolean))
      expandDefaultPreviewTreeRows(previewItems.value)
      previewProgress.value = 100
      const failedCount = Number(result.failed_count ?? Math.max(0, previewItems.value.length - okPreviewCount.value))
      const needsPassCodeCount = Number(result.needs_pass_code_count || 0)
      addPreviewLog(
        `解析完成，可下载 ${okPreviewCount.value} 项，失败 ${failedCount} 项，需补提取码 ${needsPassCodeCount} 项`,
        okPreviewCount.value ? 'success' : 'warning',
      )
      previewItems.value
        .filter(item => !item.ok)
        .slice(0, 5)
        .forEach((item, index) => {
          addPreviewLog(`[失败 ${index + 1}] ${previewItemReason(item)}`, item.requires_pass_code ? 'warning' : 'error')
        })
      if (result.svip_speed) addPreviewLog('当前百度账号为 SVIP，将使用官方登录态直接下载', 'success')
      if (okPreviewCount.value) ElMessage.success(`可下载 ${okPreviewCount.value} 个分享`)
      if (needsPassCodeCount) ElMessage.warning(`${needsPassCodeCount} 个分享需要补提取码`)
      else if (!okPreviewCount.value && failedCount) ElMessage.error(previewItemReason(previewItems.value.find(item => !item.ok)) || '百度网盘预览失败')
      persistPreviewCacheFromState()
      return
    }
    for (let index = 0; index < urls.length; index += 1) {
      const url = urls[index]
      previewProgress.value = Math.max(8, Math.round((index / urls.length) * 92))
      try {
        const result = await httpDownloadApi.preview({
          urls: [url],
          targetSubdir: targetSubdir.value,
          conflictPolicy: conflictPolicy.value,
          timeout: previewTimeoutForUrl(url)
        })
        const nextItems = result.items || []
        previewItems.value = [...previewItems.value, ...nextItems]
        if (result.needs_materialize) previewNeedsMaterialize.value = true
        const nextKeys = new Set(selectedPreviewKeys.value)
        nextItems.filter(item => item.ok).forEach(item => nextKeys.add(previewItemKey(item)))
        selectedPreviewKeys.value = nextKeys
        const okCount = nextItems.filter(item => item.ok).length
        addPreviewLog(`[${index + 1}/${urls.length}] ${okCount ? `解析出 ${okCount} 项` : '没有可下载项'}`, okCount ? 'success' : 'warning')
      } catch (error) {
        const reason = error.response?.data?.detail || error.message || '预览失败'
        previewItems.value = [
          ...previewItems.value,
          {
            ok: false,
            source: sourceFromUrl(url),
            masked_url: url,
            reason
          }
        ]
        addPreviewLog(`[${index + 1}/${urls.length}] ${reason}`, 'error')
      }
    }
    previewProgress.value = 100
    previewCacheInputSignature.value = previewInputSignature()
    expandDefaultPreviewTreeRows(previewItems.value)
    addPreviewLog(`解析完成，可下载 ${okPreviewCount.value} 项，失败 ${previewItems.value.length - okPreviewCount.value} 项`, okPreviewCount.value ? 'success' : 'warning')
    if (previewNeedsMaterialize.value) addPreviewLog('部分分享链接会在开始下载时通过官方接口解析直链', 'warning')
    if (okPreviewCount.value) ElMessage.success(`可下载 ${okPreviewCount.value} 个链接`)
    if (previewNeedsMaterialize.value) ElMessage.info('部分分享链接会在开始下载时通过官方接口解析直链')
    if (previewItems.value.length - okPreviewCount.value) ElMessage.warning(`${previewItems.value.length - okPreviewCount.value} 个链接不可直接下载`)
    persistPreviewCacheFromState()
  } finally {
    previewing.value = false
  }
}

async function start() {
  if (!selectedOkCount.value) return ElMessage.warning('先勾选至少一个下载项')
  starting.value = true
  const startedAtMs = Date.now()
  try {
    addPreviewLog(`提交 ${selectedOkCount.value} 个选中下载项`)
    const result = await activeApi.value.start({
      urls: parsedUrls.value,
      targetSubdir: targetSubdir.value,
      outputFolderName: outputFolderName.value,
      conflictPolicy: conflictPolicy.value,
      batchName: batchName.value,
      selectedKeys: [...selectedPreviewKeys.value],
      selectedItems: syncBaiduCustomNamingPayload(selectedOkItems.value)
    })
    const ids = (result.tasks || []).map(item => item.task_id || item.id).filter(Boolean)
    emit('started', ids)
    previewNeedsMaterialize.value = false
    addPreviewLog(result.message || `${panelTitle.value}任务已创建`, 'success')
    ElMessage.success(result.message || `${panelTitle.value}任务已创建`)
    previewDialogVisible.value = false
  } catch (error) {
    if (isRequestTimeout(error)) {
      try {
        const recoveredIds = await recoverStartedTasksAfterTimeout(startedAtMs)
        if (recoveredIds.length) {
          emit('started', recoveredIds)
          previewNeedsMaterialize.value = false
          addPreviewLog(`请求超时，但已接回 ${recoveredIds.length} 个已创建任务`, 'warning')
          ElMessage.warning('请求超时，但任务已创建，已打开下载工作台')
          previewDialogVisible.value = false
          return
        }
      } catch (recoverError) {
        console.warn('接回超时创建任务失败:', recoverError)
      }
    }
    addPreviewLog(error.response?.data?.detail || '创建下载任务失败', 'error')
    ElMessage.error(error.response?.data?.detail || '创建下载任务失败')
  } finally {
    starting.value = false
  }
}

function formatSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '未知大小'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size.toFixed(index ? 2 : 0)} ${units[index]}`
}

function sourceLabel(source) {
  if (isBaidu.value) return '百度网盘'
  return getHttpDownloadPlatformMeta(source).label
}

function sourceKey(source) {
  if (isBaidu.value) return 'baidu_netdisk'
  return getHttpDownloadPlatformMeta(source).key
}

function sourceIcon(source) {
  return getHttpDownloadPlatformMeta(sourceKey(source)).iconSrc || getHttpDownloadPlatformMeta(source).iconSrc || ''
}

function isSourceIconFailed(source) {
  return failedSourceIcons.value.has(sourceKey(source))
}

function markSourceIconFailed(source) {
  const next = new Set(failedSourceIcons.value)
  next.add(sourceKey(source))
  failedSourceIcons.value = next
}

function sourceFromUrl(url) {
  if (isBaidu.value) return 'baidu_netdisk'
  return httpDownloadPlatformsFromUrl(url)
}

function isGofileShareUrl(url) {
  try {
    const parsed = new URL(String(url || '').trim())
    return ['gofile.io', 'www.gofile.io'].includes(parsed.hostname.toLowerCase())
  } catch {
    return false
  }
}

function previewTimeoutForUrl(url) {
  const source = sourceFromUrl(url)
  if (source === 'gofile') return isGofileShareUrl(url) ? HTTP_SHARE_PREVIEW_TIMEOUT_MS : HTTP_DIRECT_PREVIEW_TIMEOUT_MS
  return ['transferit', 'onedrive', 'google_drive', 'pikpak'].includes(source) ? HTTP_SHARE_PREVIEW_TIMEOUT_MS : HTTP_DIRECT_PREVIEW_TIMEOUT_MS
}

function isRequestTimeout(error) {
  const code = String(error?.code || '').toUpperCase()
  const message = String(error?.message || '').toLowerCase()
  return code === 'ECONNABORTED' || message.includes('timeout')
}

function taskTimestamp(task) {
  const value = task?.created_at || task?.started_at || ''
  const timestamp = value ? new Date(value).getTime() : 0
  return Number.isFinite(timestamp) ? timestamp : 0
}

function taskPlatform(task) {
  if (isBaidu.value) return 'baidu_netdisk'
  return sourceKey(task?.task_metadata?.download_mode || task?.download_mode || task?.platform || task?.platform_label || '')
}

function expectedStartPlatforms() {
  if (isBaidu.value) return new Set(['baidu_netdisk'])
  const values = selectedOkItems.value.map(item => sourceKey(item?.source || item?.download_mode || sourceFromUrl(item?.url || item?.masked_url || '')))
  return new Set(values.filter(Boolean))
}

async function recoverStartedTasksAfterTimeout(startedAtMs) {
  const result = await activeApi.value.status()
  const platforms = expectedStartPlatforms()
  const threshold = Number(startedAtMs || 0) - START_TIMEOUT_RECOVERY_WINDOW_MS
  return (Array.isArray(result?.tasks) ? result.tasks : [])
    .filter(task => taskTimestamp(task) >= threshold)
    .filter(task => {
      const platform = taskPlatform(task)
      return !platforms.size || platforms.has(platform)
    })
    .map(task => task.id)
    .filter(Boolean)
}

function previewItemTitle(item) {
  if (item?.ok) return item.filename || item.name || '未命名文件'
  return `${sourceLabel(item?.source)} 预览失败`
}

function previewItemReason(item) {
  const reason = String(item?.reason || '').trim()
  const warning = String(item?.warning || '').trim()
  if (reason && warning && (warning.includes(reason) || reason.includes(warning))) return warning
  if (reason && warning && reason !== warning) return `${reason}：${warning}`
  return reason || warning || '未读取到可下载文件'
}

function createPreviewTreeNode({
  key,
  name,
  depth = 0,
  isDir = false,
  item = null,
  file = null,
  source = '',
  path = '',
  parent = null,
  ok = true,
  reason = '',
  warning = '',
  size = 0,
  fileCount = 0,
  customPreview = '',
  passCodeText = '',
  passCodeWarn = false,
  passCodeEditable = false,
  volumeGroup = null,
}) {
  return {
    key,
    name: String(name || '').trim() || (isDir ? '未命名目录' : '未命名文件'),
    depth,
    isDir,
    item,
    file,
    source: source || item?.source || 'http',
    path: String(path || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, ''),
    parent,
    children: [],
    selectable: false,
    ok,
    reason,
    warning,
    size,
    fileCount,
    customPreview,
    passCodeText,
    passCodeWarn,
    passCodeEditable,
    volumeGroup,
  }
}

function buildPreviewTreeRoots(items) {
  if (!isBaidu.value) return buildHttpPreviewForest(items)
  const roots = []
  ;(items || []).forEach((item, index) => {
    if (!item || !item.ok) {
      roots.push(buildFailedPreviewTreeRoot(item, index))
      return
    }
    roots.push(...buildOkPreviewTreeRoots(item, index))
  })
  return roots
}

function buildHttpPreviewForest(items) {
  const roots = []
  const dirRoots = []
  ;(items || []).forEach((item, index) => {
    if (!item || !item.ok) {
      roots.push(buildFailedPreviewTreeRoot(item, index))
      return
    }
    const pathParts = previewPathParts(item?.relative_path || item?.filename || item?.name || previewItemTitle(item))
    const source = item?.source || sourceFromUrl(item?.url || item?.masked_url || '')
    if (pathParts.length <= 1) {
      const node = createPreviewTreeNode({
        key: `http:${previewItemKey(item) || index}`,
        name: pathParts[0] || previewItemTitle(item),
        item,
        source,
        path: pathParts[0] || '',
        warning: item?.warning || '',
      })
      decoratePreviewFileNode(node)
      roots.push(node)
      return
    }

    const rootName = pathParts[0]
    const sourceKeyPart = sourceKey(source)
    const rootKey = `http-dir:${sourceKeyPart}:${rootName}`
    let root = dirRoots.find(node => node.key === rootKey)
    if (!root) {
      root = createPreviewTreeNode({
        key: rootKey,
        name: rootName,
        isDir: true,
        item,
        source,
        path: rootName,
      })
      dirRoots.push(root)
      roots.push(root)
    }
    addFilePathToPreviewTree(root, pathParts.slice(1), item, null, `http:${previewItemKey(item) || index}`, source)
  })
  dirRoots.forEach(root => decoratePreviewDirNode(root))
  return roots
}

function buildFailedPreviewTreeRoot(item, index) {
  return createPreviewTreeNode({
    key: `failed:${index}:${previewItemKey(item) || item?.masked_url || item?.url || index}`,
    name: previewItemTitle(item),
    item,
    source: item?.source || sourceFromUrl(item?.url || item?.masked_url || ''),
    ok: false,
    reason: previewItemReason(item),
    warning: item?.warning || '',
    passCodeText: isBaidu.value && item?.requires_pass_code
      ? (item.pass_code ? `提取码 ${item.pass_code}` : '缺提取码')
      : '',
    passCodeWarn: Boolean(item?.requires_pass_code || item?.pass_code_invalid),
    passCodeEditable: Boolean(isBaidu.value && item?.requires_pass_code),
  })
}

function buildOkPreviewTreeRoots(item, index) {
  return buildBaiduPreviewTreeRoots(item, index)
}

function buildBaiduPreviewTreeRoots(item, index) {
  const files = baiduPreviewFiles(item)
  const rootKey = `baidu:${previewItemKey(item) || index}`
  if (!files.length) {
    const node = createPreviewTreeNode({
      key: rootKey,
      name: previewItemTitle(item),
      item,
      source: item?.source || 'baidu_netdisk',
      warning: item?.warning || '',
      passCodeText: item?.pass_code ? `提取码 ${item.pass_code}` : '',
      passCodeWarn: Boolean(item?.requires_pass_code || item?.pass_code_invalid),
      passCodeEditable: Boolean(item?.requires_pass_code),
    })
    decoratePreviewFileNode(node)
    return [node]
  }

  const entries = normalizeBaiduPreviewTreeEntries(item, files)
    .filter(entry => entry.parts.length)
    .sort(sortPreviewTreeEntries)
  const shouldWrap = item.preview_root_is_folder || entries.some(entry => entry.parts.length > 1 || entry.isDir)
  if (!shouldWrap && entries.length === 1 && !entries[0].isDir) {
    const entry = entries[0]
    const node = createPreviewTreeNode({
      key: `${rootKey}:file:${baiduPreviewFileKey(entry.file) || entry.parts.join('/')}`,
      name: entry.parts[entry.parts.length - 1] || previewItemTitle(item),
      item,
      file: entry.file,
      source: item?.source || 'baidu_netdisk',
      path: entry.parts.join('/'),
      warning: item?.warning || '',
    })
    decoratePreviewFileNode(node)
    return [node]
  }

  const root = createPreviewTreeNode({
    key: `${rootKey}:share`,
    name: previewItemTitle(item),
    isDir: true,
    item,
    source: item?.source || 'baidu_netdisk',
    path: previewItemTitle(item),
    warning: item?.warning || '',
    passCodeText: item?.pass_code ? `提取码 ${item.pass_code}` : '',
    passCodeWarn: Boolean(item?.requires_pass_code || item?.pass_code_invalid),
    passCodeEditable: Boolean(item?.requires_pass_code),
  })
  entries.forEach((entry, entryIndex) => {
    addFilePathToPreviewTree(root, entry.parts, item, entry.file, `${rootKey}:${entryIndex}`, item?.source)
  })
  decoratePreviewDirNode(root)
  return [root]
}

function addFilePathToPreviewTree(root, parts, item, file, keyBase, source) {
  let current = root
  const cleanParts = (parts || []).map(part => String(part || '').trim()).filter(Boolean)
  cleanParts.forEach((part, index) => {
    const isLeaf = index === cleanParts.length - 1
    const childPath = [...previewPathParts(current.path), part].join('/')
    if (!isLeaf || file?.is_dir) {
      let dir = current.children.find(child => child.isDir && child.name === part)
      if (!dir) {
        dir = createPreviewTreeNode({
          key: `${keyBase}:dir:${childPath}`,
          name: part,
          depth: current.depth + 1,
          isDir: true,
          item,
          source,
          path: childPath,
          parent: current,
        })
        current.children.push(dir)
      }
      current = dir
      return
    }
    const node = createPreviewTreeNode({
      key: `${keyBase}:file:${baiduPreviewFileKey(file) || previewItemKey(item) || childPath}`,
      name: part,
      depth: current.depth + 1,
      item,
      file: file || item,
      source,
      path: childPath,
      parent: current,
      warning: item?.warning || '',
    })
    decoratePreviewFileNode(node)
    current.children.push(node)
  })
}

function decoratePreviewFileNode(node) {
  const item = node.item || {}
  const file = node.file || item
  node.isDir = false
  node.selectable = Boolean(item.ok)
  node.ok = Boolean(item.ok)
  node.reason = node.ok ? '' : previewItemReason(item)
  node.warning = String(node.warning || item.warning || '').trim()
  node.size = Number(file?.size_bytes || file?.size || item?.size_bytes || item?.size || 0)
  node.fileCount = node.ok ? 1 : 0
  node.customPreview = customPreviewForTreeRow(node)
  node.passCodeText = isBaidu.value && (item.requires_pass_code || item.pass_code)
    ? (item.pass_code ? `提取码 ${item.pass_code}` : '缺提取码')
    : ''
  node.passCodeWarn = Boolean(isBaidu.value && (item.requires_pass_code || item.pass_code_invalid))
  node.passCodeEditable = Boolean(isBaidu.value && item.requires_pass_code)
  node.volumeGroup = null
  return node
}

function decoratePreviewDirNode(node) {
  node.children.sort(sortPreviewTreeNodes)
  node.children.forEach(child => {
    child.depth = node.depth + 1
    child.parent = node
    if (child.isDir) decoratePreviewDirNode(child)
    else decoratePreviewFileNode(child)
  })
  node.selectable = node.children.some(child => child.selectable)
  node.ok = node.children.every(child => child.ok)
  node.size = node.children.reduce((sum, child) => sum + Number(child.size || 0), 0)
  node.fileCount = node.children.reduce((sum, child) => sum + Number(child.fileCount || 0), 0)
  node.volumeGroup = detectContinuousVolumeGroup(collectDirectPreviewFileRows(node))
  node.customPreview = customPreviewForTreeRow(node)
  node.warning = node.warning || ''
  return node
}

function sortPreviewTreeEntries(a, b) {
  const aPath = (a.parts || []).join('/').toLowerCase()
  const bPath = (b.parts || []).join('/').toLowerCase()
  const aDir = Boolean(a.isDir || a.file?.is_dir)
  const bDir = Boolean(b.isDir || b.file?.is_dir)
  if (aDir !== bDir) return aDir ? -1 : 1
  return aPath.localeCompare(bPath, 'zh-CN')
}

function sortPreviewTreeNodes(a, b) {
  if (Boolean(a.isDir) !== Boolean(b.isDir)) return a.isDir ? -1 : 1
  return String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN')
}

function previewPathParts(value) {
  return String(value || '')
    .replace(/\\/g, '/')
    .split('/')
    .map(part => part.trim())
    .filter(Boolean)
}

function flattenPreviewTreeRows(nodes) {
  const rows = []
  const visit = node => {
    rows.push(node)
    if (!node.isDir || !isPreviewTreeNodeExpanded(node.key)) return
    node.children.forEach(visit)
  }
  ;(nodes || []).forEach(visit)
  return rows
}

function isPreviewTreeNodeExpanded(key) {
  return expandedPreviewTreeKeys.value.has(String(key || ''))
}

function togglePreviewTreeNode(row) {
  if (!row?.isDir) return
  const next = new Set(expandedPreviewTreeKeys.value)
  if (next.has(row.key)) next.delete(row.key)
  else next.add(row.key)
  expandedPreviewTreeKeys.value = next
  persistPreviewCacheFromState()
}

function expandDefaultPreviewTreeRows(items) {
  const next = new Set()
  buildPreviewTreeRoots(items).forEach(root => {
    if (root.isDir) next.add(root.key)
    root.children?.forEach(child => {
      if (child.isDir && root.children.length <= 4) next.add(child.key)
    })
  })
  expandedPreviewTreeKeys.value = next
}

function collectPreviewFileRows(row) {
  if (!row) return []
  if (!row.isDir) return row.ok ? [row] : []
  return (row.children || []).flatMap(child => collectPreviewFileRows(child))
}

function collectDirectPreviewFileRows(row) {
  if (!row?.isDir) return []
  return (row.children || []).filter(child => child && !child.isDir && child.ok)
}

function previewRowSelectionItems(row) {
  if (!row?.ok) return []
  if (!row.isDir) return row.item ? [row.item] : []
  const items = []
  const seen = new Set()
  collectPreviewFileRows(row).forEach(fileRow => {
    const item = fileRow.item
    const key = previewItemKey(item)
    if (!item || !key || seen.has(key)) return
    seen.add(key)
    items.push(item)
  })
  return items
}

function previewTreeSelectionClass(row) {
  if (row && !row.ok) return 'is-disabled'
  const items = previewRowSelectionItems(row)
  if (!items.length) return 'is-off'
  const selected = items.filter(item => selectedPreviewKeys.value.has(previewItemKey(item))).length
  if (!selected) return 'is-off'
  return selected === items.length ? 'is-on' : 'is-partial'
}

function isPreviewTreeRowSelected(row) {
  return previewTreeSelectionClass(row) !== 'is-off'
}

function togglePreviewTreeRowSelection(row) {
  if (!row?.ok) return
  const items = previewRowSelectionItems(row)
  if (!items.length) return
  const next = new Set(selectedPreviewKeys.value)
  const shouldSelect = previewTreeSelectionClass(row) !== 'is-on'
  items.forEach(item => {
    const key = previewItemKey(item)
    if (!key) return
    if (shouldSelect) next.add(key)
    else next.delete(key)
  })
  selectedPreviewKeys.value = next
  persistPreviewCacheFromState()
}

function handlePreviewTreeRowClick(row) {
  closePreviewContextMenu()
  if (!row?.ok) return
  if (row.isDir) {
    togglePreviewTreeNode(row)
    return
  }
  togglePreviewTreeRowSelection(row)
}

function detectContinuousVolumeGroup(rows) {
  const entries = (rows || [])
    .filter(row => row && !row.isDir && row.ok)
    .map(row => ({ row, info: previewArchiveVolumeInfo(row.file || row.item || row) }))
    .filter(entry => entry.info && entry.info.base)
  if (entries.length < 2) return null

  const groups = new Map()
  entries.forEach(entry => {
    const base = String(entry.info.base || '').trim().toLowerCase()
    if (!base) return
    const parentKey = String(entry.row?.parent?.path || '').trim().toLowerCase()
    const key = `${parentKey}::${entry.info.type}::${base}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(entry)
  })

  const validGroups = []
  groups.forEach(groupEntries => {
    const sorted = sortContinuousVolumeEntries(groupEntries)
    if (!isContinuousVolumeEntries(sorted)) return
    validGroups.push({
      base: sorted[0].info.base,
      type: sorted[0].info.type,
      displayPattern: sorted[0].info.displayPattern,
      files: sorted,
    })
  })
  return validGroups.length === 1 ? validGroups[0] : null
}

function sortContinuousVolumeEntries(entries) {
  return (entries || []).slice().sort((a, b) => {
    if (a.info.order !== b.info.order) return a.info.order - b.info.order
    if (a.info.index !== b.info.index) return a.info.index - b.info.index
    return String(a.row?.name || '').localeCompare(String(b.row?.name || ''), 'zh-CN')
  })
}

function isContinuousVolumeEntries(entries) {
  if (!Array.isArray(entries) || entries.length < 2) return false
  const type = entries[0]?.info?.type
  if (!type || !entries.every(entry => entry.info?.type === type)) return false
  const indexed = entries.filter(entry => entry.info?.isNumbered && Number.isFinite(entry.info.index))
  if (indexed.length < 2 && !['zip_z', 'rar_old', 'exe_e'].includes(type)) return false
  if (['zip_z', 'rar_old', 'exe_e'].includes(type)) {
    const mainSuffix = type === 'zip_z' ? '.zip' : (type === 'rar_old' ? '.rar' : '.exe')
    if (!entries.some(entry => entry.info.suffix === mainSuffix)) return false
  }
  if (indexed.length) {
    const indexes = indexed.map(entry => entry.info.index).sort((a, b) => a - b)
    const expectedStart = type === 'rar_old' ? 0 : 1
    if (indexes[0] !== expectedStart) return false
    for (let index = 0; index < indexes.length; index += 1) {
      if (indexes[index] !== expectedStart + index) return false
    }
  }
  return true
}

function customPreviewForTreeRow(row) {
  if (!row?.ok) return ''
  if (row.isDir) {
    if (!row.volumeGroup) return ''
    const first = row.volumeGroup.files.find(entry => entry.row)
    const item = first?.row?.item || row.item
    const customName = String(item?.custom_name || '').trim()
    const customPassword = String(item?.custom_extract_password || '').trim()
    if (!customName && !customPassword) return ''
    const base = customName || row.volumeGroup.base || row.name
    return `${base}${customPassword ? `(${customPassword})` : ''}${volumeGroupDisplayPattern(row.volumeGroup)}`
  }
  const item = row.item || {}
  const file = row.file || item
  const customName = String(file.custom_name || item.custom_name || '').trim()
  const customPassword = String(file.custom_extract_password || item.custom_extract_password || '').trim()
  if (!customName && !customPassword) return ''
  const base = customName || defaultPreviewRowCustomName(row)
  const ext = splitFilename(String(file.name || file.filename || item.filename || row.name || '')).ext
  return `${base}${customPassword ? `(${customPassword})` : ''}${ext}`
}

function defaultPreviewRowCustomName(row) {
  if (!row) return '下载文件'
  if (row.isDir && row.volumeGroup?.base) return row.volumeGroup.base
  if (isBaidu.value && row.file) return defaultBaiduPreviewFileName(row.file)
  return splitFilename(String(row.item?.filename || row.item?.name || row.name || '下载文件')).name || row.name || '下载文件'
}

function canRenamePreviewTreeRow(row) {
  if (!row?.ok) return false
  if (!row.isDir) return true
  return Boolean(row.volumeGroup)
}

function canSetPasswordPreviewTreeRow(row) {
  if (!row?.ok) return false
  if (!row.isDir) return true
  return Boolean(row.volumeGroup)
}

function openPreviewContextMenu(event, row) {
  if (!row) return
  previewContextMenu.visible = true
  previewContextMenu.rowKey = row.key
  previewContextMenu.row = row
  const bounds = event?.currentTarget?.closest?.('.http-preview-window')?.getBoundingClientRect?.()
  const viewportWidth = bounds?.width || window.innerWidth || 1200
  const viewportHeight = bounds?.height || window.innerHeight || 800
  const leftBase = bounds ? event.clientX - bounds.left : event.clientX
  const topBase = bounds ? event.clientY - bounds.top : event.clientY
  previewContextMenu.x = Math.min(Math.max(8, leftBase), Math.max(8, viewportWidth - 184))
  previewContextMenu.y = Math.min(Math.max(8, topBase), Math.max(8, viewportHeight - 132))
}

function closePreviewContextMenu() {
  previewContextMenu.visible = false
  previewContextMenu.rowKey = ''
  previewContextMenu.row = null
}

async function refreshPreviewContextRow() {
  const row = previewContextMenu.row
  closePreviewContextMenu()
  if (!row || previewing.value) return
  addPreviewLog(`准备重新解析 ${row.name || '当前预览'}`, 'warning')
  await preview({ forceRefresh: true })
}

async function renamePreviewContextRow() {
  const row = previewContextMenu.row
  closePreviewContextMenu()
  if (!canRenamePreviewTreeRow(row)) {
    ElMessage.warning('这个目录下没有可连续识别的分卷组')
    return
  }
  const current = defaultPreviewRowCustomName(row)
  try {
    const value = await showSystemPrompt({
      title: row.isDir ? '重命名连续分卷' : '重命名文件',
      message: row.isDir ? '只会作用到这个目录下识别出的同一组连续分卷。' : '只会修改这个文件的保存名称。',
      placeholder: current,
      modelValue: current,
      confirmText: '保存',
      cancelText: '取消',
      width: 520,
      validator: input => String(input || '').trim() ? true : '名称不能为空',
    })
    const nextName = String(value || '').trim()
    if (!nextName) return
    applyTreeRowRename(row, nextName)
    persistPreviewCacheFromState()
  } catch (_) {}
}

async function setPasswordPreviewContextRow() {
  const row = previewContextMenu.row
  closePreviewContextMenu()
  if (!canSetPasswordPreviewTreeRow(row)) {
    ElMessage.warning('这个目录下没有可连续识别的分卷组')
    return
  }
  const current = currentTreeRowPassword(row)
  try {
    const value = await showSystemPrompt({
      title: row.isDir ? '设置连续分卷密码' : '设置解压密码',
      message: row.isDir ? '只会作用到这个目录下识别出的同一组连续分卷。' : '密码会按密码嗅探模板写入保存文件名。',
      placeholder: '留空可清除密码',
      modelValue: current,
      confirmText: '保存',
      cancelText: '取消',
      width: 520,
    })
    applyTreeRowPassword(row, String(value || '').trim())
    persistPreviewCacheFromState()
  } catch (_) {}
}

function currentTreeRowPassword(row) {
  if (!row) return ''
  if (row.isDir && row.volumeGroup) {
    const first = row.volumeGroup.files.find(entry => entry.row)
    return String(first?.row?.item?.custom_extract_password || '').trim()
  }
  const file = row.file || {}
  const item = row.item || {}
  return String(file.custom_extract_password || item.custom_extract_password || '').trim()
}

function applyTreeRowRename(row, name) {
  const cleanName = String(name || '').trim()
  if (!row || !cleanName) return
  if (row.isDir && row.volumeGroup) {
    applyVolumeGroupNaming(row, { name: cleanName, keepPassword: true })
    addPreviewLog(`已重命名连续分卷为 ${cleanName}${volumeGroupDisplayPattern(row.volumeGroup)}`, 'success')
    return
  }
  if (isBaidu.value && row.file && row.file !== row.item) {
    row.file.custom_name = cleanName
  } else if (row.item) {
    row.item.custom_name = cleanName
  }
  addPreviewLog(`已重命名 ${row.name}`, 'success')
}

function applyTreeRowPassword(row, password) {
  const cleanPassword = String(password || '').trim()
  if (!row) return
  if (row.isDir && row.volumeGroup) {
    applyVolumeGroupNaming(row, { password: cleanPassword, keepName: true })
    addPreviewLog(cleanPassword ? `已为连续分卷设置密码` : '已清除连续分卷密码', cleanPassword ? 'success' : 'warning')
    return
  }
  if (isBaidu.value && row.file && row.file !== row.item) {
    row.file.custom_extract_password = cleanPassword
  } else if (row.item) {
    row.item.custom_extract_password = cleanPassword
  }
  addPreviewLog(cleanPassword ? `已为 ${row.name} 设置密码` : `已清除 ${row.name} 的密码`, cleanPassword ? 'success' : 'warning')
}

function applyVolumeGroupNaming(row, { name = '', password = '', keepName = false, keepPassword = false } = {}) {
  if (!row?.volumeGroup) return
  const currentName = String(row.volumeGroup.files[0]?.row?.item?.custom_name || row.volumeGroup.base || row.name || '').trim()
  const currentPassword = String(row.volumeGroup.files[0]?.row?.item?.custom_extract_password || '').trim()
  const base = keepName ? currentName : (String(name || '').trim() || currentName)
  const nextPassword = keepPassword ? currentPassword : String(password || '').trim()
  row.volumeGroup.files.forEach(({ row: fileRow, info }) => {
    const item = fileRow?.item
    const file = fileRow?.file
    if (!item) return
    item.custom_name = isBaidu.value ? base : volumeFileCustomName(base, info)
    item.custom_extract_password = nextPassword
    item.custom_group_folder = isBaidu.value
      ? true
      : Boolean(nextPassword && shouldUseGroupFolderForVolumeRow(row))
    if (isBaidu.value && file && file !== item) {
      file.custom_name = baiduVolumeFileCustomName(base, info)
      file.custom_extract_password = ''
      file._batch_selected = true
    }
  })
}

function baiduVolumeFileCustomName(base, info) {
  if (info?.type === 'zip_z' && !info?.needsFullName) return String(base || '').trim()
  return volumeFileCustomName(base, info)
}

function volumeFileCustomName(base, info) {
  const cleanBase = String(base || '').trim()
  const suffix = String(info?.suffix || '').trim()
  if (!cleanBase || !suffix) return cleanBase
  return `${cleanBase}${suffix}`
}

function shouldUseGroupFolderForVolumeRow(row) {
  if (!row?.isDir) return false
  if (isBaidu.value) return true
  const groupKeys = new Set((row.volumeGroup?.files || []).map(entry => entry.row?.key).filter(Boolean))
  const groupParents = new Set((row.volumeGroup?.files || []).map(entry => entry.row?.parent?.key).filter(Boolean))
  return collectPreviewFileRows(row).some(fileRow => (
    fileRow
    && !groupKeys.has(fileRow.key)
    && groupParents.has(fileRow.parent?.key)
  ))
}

function splitFilename(value) {
  const filename = String(value || '').split(/[\\/]/).filter(Boolean).pop() || ''
  const lower = filename.toLowerCase()
  for (const suffix of ['.tar.gz', '.tar.bz2', '.tar.xz']) {
    if (lower.endsWith(suffix)) {
      return { name: filename.slice(0, -suffix.length), ext: filename.slice(-suffix.length) }
    }
  }
  const index = filename.lastIndexOf('.')
  if (index > 0) return { name: filename.slice(0, index), ext: filename.slice(index) }
  return { name: filename, ext: '' }
}

function volumeGroupDisplayPattern(group) {
  return group?.displayPattern || '.z01 / .zip'
}

function previewArchiveVolumeInfo(file) {
  const sourceName = String(file?.name || file?.filename || file?.relative_path || '').split(/[\\/]/).filter(Boolean).pop() || ''
  const trimmed = sourceName.trim()
  if (!trimmed) return null
  let match = trimmed.match(/^(.*?)\.z(\d{2})$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'zip_z',
      index: Number(match[2]),
      order: 1,
      suffix: `.z${match[2].padStart(2, '0')}`,
      isNumbered: true,
      needsFullName: false,
      displayPattern: '.z01 / .zip',
    }
  }
  match = trimmed.match(/^(.*?)([._\-\s]+z)(\d{2})$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'zip_z',
      index: Number(match[3]),
      order: 1,
      suffix: `.z${match[3].padStart(2, '0')}`,
      isNumbered: true,
      needsFullName: true,
      displayPattern: '.z01 / .zip',
    }
  }
  match = trimmed.match(/^(.*?)\.zip$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'zip_z',
      index: 10000,
      order: 2,
      suffix: '.zip',
      isNumbered: false,
      needsFullName: false,
      displayPattern: '.z01 / .zip',
    }
  }
  match = trimmed.match(/^(.*?)\.7z\.(\d{3})$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: '7z',
      index: Number(match[2]),
      order: 1,
      suffix: `.7z.${match[2].padStart(3, '0')}`,
      isNumbered: true,
      needsFullName: false,
      displayPattern: '.7z.001',
    }
  }
  match = trimmed.match(/^(.*?)\.zip\.(\d{3})$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'zip_numeric',
      index: Number(match[2]),
      order: 1,
      suffix: `.zip.${match[2].padStart(3, '0')}`,
      isNumbered: true,
      needsFullName: false,
      displayPattern: '.zip.001',
    }
  }
  match = trimmed.match(/^(.*?)\.part(\d+)\.(rar|zip|7z|exe)$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'part',
      index: Number(match[2]),
      order: 1,
      suffix: `.part${match[2]}.${match[3]}`,
      isNumbered: true,
      needsFullName: false,
      displayPattern: `.part1.${match[3].toLowerCase()}`,
    }
  }
  match = trimmed.match(/^(.*?)\.part(\d+)$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'part_no_ext',
      index: Number(match[2]),
      order: 1,
      suffix: `.part${match[2]}`,
      isNumbered: true,
      needsFullName: false,
      displayPattern: '.part1',
    }
  }
  match = trimmed.match(/^(.*?)\.r(\d{2})$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'rar_old',
      index: Number(match[2]),
      order: 1,
      suffix: `.r${match[2].padStart(2, '0')}`,
      isNumbered: true,
      needsFullName: false,
      displayPattern: '.rar / .r00',
    }
  }
  match = trimmed.match(/^(.*?)\.rar$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'rar_old',
      index: 10000,
      order: 2,
      suffix: '.rar',
      isNumbered: false,
      needsFullName: false,
      displayPattern: '.rar / .r00',
    }
  }
  match = trimmed.match(/^(.*?)\.e(\d{2})$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'exe_e',
      index: Number(match[2]),
      order: 1,
      suffix: `.e${match[2].padStart(2, '0')}`,
      isNumbered: true,
      needsFullName: false,
      displayPattern: '.exe / .e01',
    }
  }
  match = trimmed.match(/^(.*?)\.exe$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'exe_e',
      index: 10000,
      order: 2,
      suffix: '.exe',
      isNumbered: false,
      needsFullName: false,
      displayPattern: '.exe / .e01',
    }
  }
  match = trimmed.match(/^(.*?)\.(\d{3})$/i)
  if (match) {
    return {
      base: match[1].trim(),
      type: 'numeric',
      index: Number(match[2]),
      order: 1,
      suffix: `.${match[2].padStart(3, '0')}`,
      isNumbered: true,
      needsFullName: false,
      displayPattern: '.001',
    }
  }
  return null
}

function baiduPreviewFiles(item) {
  return Array.isArray(item?.preview_files) ? item.preview_files.filter(Boolean) : []
}

function baiduPreviewFileKey(file) {
  return String(file?.fs_id || file?.path || file?.relative_path || file?.name || '').trim()
}

function normalizeBaiduPreviewTreeEntries(item, files) {
  const entries = files.map(file => ({
    file,
    parts: baiduPreviewPathParts(file),
    isDir: Boolean(file?.is_dir),
  }))
  if (item?.preview_root_is_folder) return entries

  const fileEntries = entries.filter(entry => !entry.isDir && entry.parts.length > 1)
  if (fileEntries.length <= 1) return entries

  const commonRoot = fileEntries[0].parts[0]
  if (!commonRoot || !fileEntries.every(entry => entry.parts[0] === commonRoot)) return entries
  if (!entries.every(entry => !entry.parts.length || entry.parts[0] === commonRoot)) return entries
  const explicitRootDir = entries.some(entry => entry.isDir && entry.parts.length === 1 && entry.parts[0] === commonRoot)
  if (explicitRootDir) return entries

  return entries.map(entry => {
    if (entry.parts.length <= 1 || entry.parts[0] !== commonRoot) return entry
    return { ...entry, parts: entry.parts.slice(1) }
  })
}

function baiduPreviewPathParts(file) {
  const path = String(file?.relative_path || file?.name || '').replace(/\\/g, '/').trim()
  return path.split('/').map(part => part.trim()).filter(Boolean)
}

function defaultBaiduPreviewFileName(file) {
  const sourceName = String(file?.name || file?.relative_path || '').split(/[\\/]/).filter(Boolean).pop() || ''
  return splitFilename(sourceName).name || sourceName || '百度网盘文件'
}

function previewItemFileCount(item) {
  if (!isBaidu.value) return item?.ok ? 1 : 0
  const previewFiles = baiduPreviewFiles(item)
  const directFiles = previewFiles.filter(file => file && !file.is_dir).length
  if (directFiles) return directFiles
  const previewCount = Number(item?.preview_file_count || 0)
  const folderCount = Number(item?.preview_folder_count || 0)
  if (previewCount > folderCount) return previewCount - folderCount
  return item?.ok ? 1 : 0
}

function applyPassCodeAndPreview(item) {
  const code = String(item?.pass_code || '').trim()
  const shareUrl = String(item?.share_url || item?.url || item?.masked_url || '').trim()
  if (!shareUrl || !code) return
  const lines = String(urlText.value || '').split(/\r?\n/)
  const shareIdentity = baiduShareIdentity(shareUrl)
  const fixedShareUrl = replaceBaiduPassCode(shareUrl, code)
  let matched = false
  const nextLines = []
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index]
    const trimmed = raw.trim()
    const normalizedLine = normalizeBaiduShareLine(trimmed)
    if (!matched && trimmed && isBaiduShareUrl(normalizedLine) && baiduShareIdentity(normalizedLine) === shareIdentity) {
      const indent = raw.match(/^\s*/)?.[0] || ''
      nextLines.push(`${indent}${fixedShareUrl}`)
      if (isBaiduPassCodeLine(lines[index + 1])) {
        index += 1
      }
      matched = true
      continue
    }
    nextLines.push(raw)
  }
  if (!matched) {
    nextLines.push(fixedShareUrl)
  }
  urlText.value = nextLines.join('\n')
  addPreviewLog('已更新提取码，重新预览该分享', 'warning')
  preview({ forceRefresh: true })
}

function syncBaiduCustomNamingPayload(items) {
  return (items || []).map(item => ({
    ...item,
    custom_name: String(item?.custom_name || '').trim(),
    custom_extract_password: String(item?.custom_extract_password || '').trim(),
    custom_group_folder: Boolean(item?.custom_group_folder),
    custom_file_names: buildBaiduCustomFileOverrides(item),
  }))
}

function buildBaiduCustomFileOverrides(item) {
  const overrides = {}
  baiduPreviewFiles(item).forEach(file => {
    if (!file || file.is_dir) return
    const key = baiduPreviewFileKey(file)
    if (!key) return
    const customName = String(file.custom_name || '').trim()
    const customPassword = String(file.custom_extract_password || '').trim()
    if (!customName && !customPassword) return
    overrides[key] = {
      custom_name: customName,
      custom_extract_password: customPassword,
      fs_id: String(file.fs_id || '').trim(),
      path: String(file.path || '').trim(),
      relative_path: String(file.relative_path || '').trim(),
      name: String(file.name || '').trim(),
    }
  })
  return overrides
}

function previewItemKey(item) {
  if (!item) return ''
  if (item.selection_key) return String(item.selection_key)
  return [
    item.source || 'http',
    item.share_url || '',
    item.masked_url || item.url || '',
    item.relative_path || '',
    item.filename || item.name || '',
    item.size_bytes || item.size || ''
  ].join('|')
}

function isPreviewItemSelected(item) {
  return selectedPreviewKeys.value.has(previewItemKey(item))
}

function selectAllPreviewItems() {
  selectedPreviewKeys.value = new Set(okPreviewItems.value.map(item => previewItemKey(item)))
  persistPreviewCacheFromState()
}

function clearPreviewSelection() {
  selectedPreviewKeys.value = new Set()
  persistPreviewCacheFromState()
}

function toggleAllPreviewSelection() {
  if (allPreviewSelectionState.value === 'all') {
    clearPreviewSelection()
    return
  }
  selectAllPreviewItems()
}

function togglePreviewSource(chip) {
  const items = Array.isArray(chip?.items) ? chip.items : []
  const next = new Set(selectedPreviewKeys.value)
  const shouldSelect = chip?.state !== 'all'
  items.forEach(item => {
    const key = previewItemKey(item)
    if (shouldSelect) next.add(key)
    else next.delete(key)
  })
  selectedPreviewKeys.value = next
  persistPreviewCacheFromState()
}

function addPreviewLog(message, level = 'info') {
  const now = new Date()
  previewLogs.value = [
    ...previewLogs.value,
    {
      id: `${Date.now()}-${previewLogs.value.length}`,
      time: now.toLocaleTimeString('zh-CN', { hour12: false }),
      message,
      level
    }
  ].slice(-80)
}

watch(() => props.draft, (value) => {
  if (isSameDownloadPanelDraft(currentDownloadPanelDraft(), value)) return
  const draft = normalizeDownloadPanelDraft(value)
  urlText.value = draft.urlText
  targetSubdir.value = draft.targetSubdir
  outputFolderName.value = draft.outputFolderName
  batchName.value = draft.batchName
  conflictPolicy.value = draft.conflictPolicy
  restoreOrClearPreviewCache(draft.previewCache)
}, { deep: true })

watch([urlText, targetSubdir, outputFolderName, batchName, conflictPolicy], () => {
  if (previewCacheInputSignature.value && previewCacheInputSignature.value !== previewInputSignature()) {
    clearPreviewCacheState()
  }
  const draft = currentDownloadPanelDraft()
  if (isSameDownloadPanelDraft(draft, props.draft)) return
  emit('update:draft', draft)
})

watch([previewItems, previewLogs, previewProgress], () => {
  if (!previewItems.value.length) return
  persistPreviewCacheFromState()
}, { deep: true })

onMounted(() => {
  restoreOrClearPreviewCache(props.draft?.previewCache)
  loadHealth()
})

onBeforeUnmount(() => {
  closePreviewContextMenu()
})
</script>

<style scoped>
.http-download-panel {
  border-radius: 16px;
  border: 1px solid var(--asmr-border);
  background: var(--asmr-surface);
  box-shadow: var(--asmr-card-shadow);
  overflow: hidden;
}
.asmr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--asmr-border);
  background: var(--asmr-surface-soft);
}
.asmr-card-head-title {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
.asmr-card-head-title h2 {
  margin: 0;
  color: var(--asmr-text-strong);
  font-size: 14px;
  font-weight: 750;
}
.asmr-card-head-subtitle {
  margin: 1px 0 0;
  color: var(--asmr-text-muted);
  font-size: 12px;
}
.asmr-card-head-icon { color: var(--asmr-accent); flex-shrink: 0; }
.asmr-card-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.asmr-card-body { padding: 14px 18px 18px; }
.asmr-mini-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 30px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--asmr-border-strong);
  background: var(--asmr-surface);
  color: var(--asmr-text);
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.asmr-mini-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--asmr-border-strong);
  background: var(--asmr-surface-hover);
  color: var(--asmr-text-strong);
}
.asmr-mini-btn:active:not(:disabled) { transform: scale(0.96); }
.asmr-mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.asmr-mini-btn :deep(svg) { transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.asmr-mini-btn:hover:not(:disabled) :deep(svg) { transform: rotate(-8deg) scale(1.08); }
.asmr-mini-btn.is-primary {
  background: var(--asmr-primary-bg);
  border-color: transparent;
  color: var(--asmr-primary-text);
  box-shadow: var(--asmr-control-shadow);
}
.asmr-mini-btn.is-primary:hover:not(:disabled) {
  background: var(--asmr-primary-bg-hover);
  color: var(--asmr-primary-text);
  box-shadow: var(--asmr-control-shadow);
}
.asmr-health-action-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.asmr-health-action-icon.is-loading :deep(svg) {
  animation: asmr-health-spin 0.4s linear infinite;
}
.asmr-health-action-icon.is-success :deep(svg) {
  animation: asmr-health-pop 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.asmr-health-action-icon.is-error :deep(svg) {
  animation: asmr-health-pop 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.http-download-body { display: grid; gap: 12px; }
.http-download-health {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid var(--asmr-border);
  background: var(--asmr-surface-soft);
  color: var(--asmr-text);
  font-size: 12px;
}
.http-download-health.ok { border-color: var(--asmr-success-border); background: var(--asmr-success-bg); color: var(--asmr-success-text); }
.http-download-health.bad { border-color: var(--asmr-danger-border); background: var(--asmr-danger-bg); color: var(--asmr-danger-text); }
.http-health-dot { width: 7px; height: 7px; border-radius: 999px; background: currentColor; opacity: .82; }
.http-health-path { margin-left: auto; max-width: 46%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; opacity: .78; }
.http-url-input,
.http-input {
  width: 100%;
  border: 1px solid var(--asmr-border);
  background: var(--asmr-field-bg);
  color: var(--asmr-text-strong);
  outline: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.http-url-input { resize: vertical; min-height: 118px; padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.55; }
.http-input { height: 36px; padding: 0 10px; border-radius: 8px; font-size: 13px; }
.http-url-input::placeholder,
.http-input::placeholder {
  color: var(--asmr-field-placeholder);
}
.http-url-input:focus,
.http-input:focus { border-color: var(--asmr-border-strong); background: var(--asmr-field-bg-focus); box-shadow: 0 0 0 3px var(--asmr-focus-ring); }
.http-download-options { display: flex; align-items: end; gap: 10px; flex-wrap: wrap; }
.http-field { display: grid; gap: 5px; min-width: 180px; color: var(--asmr-text); font-size: 12px; font-weight: 600; }
.http-field.grow { flex: 1 1 240px; }
.baidu-pass-code-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}
.download-tree-row.bad .baidu-pass-code-row {
  padding-top: 1px;
}
.baidu-custom-preview {
  min-width: 0;
  max-width: min(420px, 100%);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgb(37, 99, 235);
  font-size: 11px;
  font-weight: 700;
}
.baidu-pass-code-input {
  width: 124px;
  height: 26px;
  padding: 0 8px;
  border: 1px solid rgba(203, 213, 225, 0.92);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.92);
  color: rgb(30, 41, 59);
  font-size: 11px;
  outline: none;
}
.baidu-pass-code-input:focus {
  border-color: rgba(59, 130, 246, 0.72);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}
.baidu-pass-code-btn {
  height: 26px;
  padding: 0 10px;
  border: 1px solid rgba(203, 213, 225, 0.86);
  border-radius: 7px;
  background: rgba(248, 250, 252, 0.9);
  color: rgb(51, 65, 85);
  font-size: 11px;
  font-weight: 650;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.baidu-pass-code-btn:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.02);
  border-color: rgba(148, 163, 184, 0.82);
  background: #ffffff;
}
.baidu-pass-code-btn:active:not(:disabled) { transform: scale(0.96); }
.baidu-pass-code-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.http-actions { display: flex; gap: 8px; justify-content: flex-end; }
.http-actions .asmr-mini-btn {
  position: relative;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 10px;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.08);
  cursor: pointer;
}
.http-actions .asmr-mini-btn:disabled { cursor: not-allowed; }
.http-actions .asmr-mini-btn.is-querying:disabled { cursor: progress; }
.http-actions .asmr-mini-btn:hover:not(:disabled) {
  transform: translateY(-3px) scale(1.035);
  box-shadow: 0 14px 26px rgba(15, 23, 42, 0.14);
}
.http-actions .asmr-mini-btn:active:not(:disabled) {
  transform: translateY(1px) scale(0.94);
  box-shadow: 0 5px 12px rgba(15, 23, 42, 0.12);
}
.http-actions .asmr-mini-btn:hover:not(:disabled) :deep(svg) {
  animation: http-action-icon-pop 0.55s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
.http-actions .asmr-mini-btn.is-primary:hover:not(:disabled) :deep(svg) {
  animation-name: http-action-icon-drop;
}
.http-actions .asmr-mini-btn :deep(svg.is-querying) {
  animation: http-query-spin 0.86s linear infinite, http-query-pulse 1.2s ease-in-out infinite;
}
@keyframes http-action-icon-pop {
  0%, 100% { transform: rotate(0deg) scale(1); }
  45% { transform: rotate(-14deg) scale(1.22); }
}
@keyframes http-action-icon-drop {
  0%, 100% { transform: translateY(0) scale(1); }
  42% { transform: translateY(3px) scale(1.18); }
}
@keyframes http-query-spin {
  to { transform: rotate(360deg); }
}
@keyframes http-query-pulse {
  0%, 100% { opacity: 0.72; }
  50% { opacity: 1; }
}
.http-preview-status-title {
  color: rgb(15, 23, 42);
  font-size: 13px;
  font-weight: 800;
}
.http-preview-status-count {
  flex-shrink: 0;
  color: rgb(51, 65, 85);
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.http-preview-progress {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.64);
  border: 1px solid rgba(226, 232, 240, 0.7);
}
.http-preview-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: rgb(59, 130, 246);
  transition: width 0.36s ease;
}
.http-preview-log {
  display: grid;
  gap: 4px;
  max-height: 92px;
  overflow-y: auto;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(226, 232, 240, 0.82);
  background: rgba(248, 250, 252, 0.72);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.http-preview-log-row {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: 8px;
  color: rgb(71, 85, 105);
  font-size: 11px;
  line-height: 1.45;
}
.http-preview-log-row.is-success { color: rgb(22, 101, 52); }
.http-preview-log-row.is-warning { color: rgb(180, 83, 9); }
.http-preview-log-row.is-error { color: rgb(185, 28, 28); }
.http-preview-log-time {
  color: rgb(148, 163, 184);
  font-variant-numeric: tabular-nums;
}
.http-preview-log-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.http-preview-window {
  color: rgb(30, 41, 59);
}
.http-preview-window .window-header {
  min-height: 66px;
}
.http-preview-content {
  flex: 1;
  min-height: 0;
}
.http-preview-settings-card {
  scrollbar-width: none;
}
.http-preview-settings-card::-webkit-scrollbar {
  display: none;
}
.http-preview-status-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 62px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.76);
  background: rgba(255, 255, 255, 0.44);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}
.http-preview-status-sub {
  margin-top: 3px;
  color: rgb(100, 116, 139);
  font-size: 11px;
}
.summary-stack span {
  float: right;
  max-width: 190px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgb(30, 41, 59);
  font-weight: 650;
}
.download-list-panel {
  min-width: 0;
  overflow: hidden;
  flex: 1 1 auto;
}
.download-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 44px;
  padding: 10px 14px 8px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.72);
}
.download-list-head h2 {
  margin: 0;
  color: rgb(15, 23, 42);
  font-size: 14px;
  font-weight: 800;
  line-height: 1.2;
}
.download-list-head p {
  margin: 4px 0 0;
  color: rgb(100, 116, 139);
  font-size: 11.5px;
  line-height: 1.35;
}
.download-list-head > span {
  flex: 0 0 auto;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.72);
  color: rgb(71, 85, 105);
  font-size: 11px;
  font-weight: 750;
  font-variant-numeric: tabular-nums;
}
.download-list-scroll {
  height: 100%;
  overflow: auto;
  padding: 8px 10px 10px;
  scrollbar-width: thin;
  scrollbar-color: rgba(119, 129, 141, 0.58) transparent;
}
.download-list-scroll::-webkit-scrollbar {
  width: 8px;
}
.download-list-scroll::-webkit-scrollbar-thumb {
  background: rgba(119, 129, 141, 0.48);
  border-radius: 999px;
}
.download-tree {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.download-tree-row {
  --tree-depth: 0;
  min-height: 34px;
  display: grid;
  grid-template-columns: calc(var(--tree-depth) * 18px) 18px 16px 22px minmax(0, 1fr) auto;
  align-items: center;
  column-gap: 8px;
  row-gap: 4px;
  padding: 5px 8px;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
  transition: background-color 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}
.download-tree-row.is-root-leaf {
  grid-template-columns: 16px 22px minmax(0, 1fr) auto;
  column-gap: 8px;
}
.download-tree-row.bad {
  grid-template-columns: calc(var(--tree-depth) * 18px) 18px 16px 20px 22px minmax(0, 1fr) auto;
}
.download-tree-row.is-root-leaf.bad {
  grid-template-columns: 16px 20px 22px minmax(0, 1fr) auto;
}
.download-tree-row.is-root-leaf .download-tree-indent,
.download-tree-row.is-root-leaf .download-tree-toggle.placeholder {
  display: none;
}
.download-tree-row.is-root-leaf .download-list-check {
  grid-column: 1;
}
.download-tree-row.is-root-leaf .http-preview-error-icon {
  grid-column: 2;
}
.download-tree-row.is-root-leaf .download-tree-kind-icon {
  grid-column: 2;
}
.download-tree-row.is-root-leaf.bad .download-tree-kind-icon {
  grid-column: 3;
}
.download-tree-row.is-root-leaf .download-tree-main {
  grid-column: 3;
}
.download-tree-row.is-root-leaf.bad .download-tree-main {
  grid-column: 4;
}
.download-tree-row.is-root-leaf .download-list-size {
  grid-column: 4;
}
.download-tree-row.is-root-leaf.bad .download-list-size {
  grid-column: 5;
}
.download-tree-row:not(.bad) .http-preview-error-placeholder {
  display: none;
}
.download-tree-row:hover {
  background: rgba(248, 250, 252, 0.72);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.84);
}
.download-tree-row.selected {
  background: rgba(239, 246, 255, 0.7);
  box-shadow: inset 0 0 0 1px rgba(219, 234, 254, 0.8);
}
.download-tree-row.is-context {
  background: rgba(239, 246, 255, 0.86);
  box-shadow: inset 0 0 0 1px rgba(147, 197, 253, 0.58);
}
.download-tree-row.is-volume-group .download-tree-kind-icon {
  color: rgb(37, 99, 235);
}
.download-tree-indent {
  width: 100%;
  height: 100%;
  min-height: 22px;
}
.download-tree-toggle {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: rgb(100, 116, 139);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.download-tree-toggle:hover {
  background: rgba(226, 232, 240, 0.68);
  transform: translateY(-1px) scale(1.04);
}
.download-tree-toggle :deep(svg) {
  transition: transform 0.22s ease;
}
.download-tree-toggle.expanded :deep(svg) {
  transform: rotate(90deg);
}
.download-tree-toggle.placeholder {
  pointer-events: none;
}
.download-tree-check-placeholder {
  width: 16px;
  height: 16px;
  display: block;
}
.download-tree-kind-icon {
  width: 18px;
  height: 18px;
  color: rgb(14, 165, 233);
  flex-shrink: 0;
}
.download-tree-row.is-dir .download-tree-kind-icon {
  color: rgb(245, 158, 11);
}
.download-tree-row.is-file .download-tree-kind-icon {
  color: rgb(14, 165, 233);
}
.download-tree-row.bad .download-tree-kind-icon {
  color: rgb(248, 113, 113);
}
.download-list-check {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 16px;
  border: 1px solid rgb(203, 213, 225);
  background: rgba(255, 255, 255, 0.9);
  color: transparent;
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease;
}
.download-list-check.is-on {
  border-color: rgb(59, 130, 246);
  background: rgb(59, 130, 246);
  color: #ffffff;
}
.download-list-check.is-partial {
  border-color: rgb(59, 130, 246);
  background: rgba(59, 130, 246, 0.18);
  color: rgb(37, 99, 235);
}
.download-list-check.is-off {
  border-color: rgb(203, 213, 225);
  background: rgba(255, 255, 255, 0.95);
}
.download-list-check.is-disabled {
  border-color: rgba(248, 113, 113, 0.36);
  background: rgba(254, 242, 242, 0.42);
  color: transparent;
  cursor: not-allowed;
}
.download-tree-row:hover .download-list-check.is-off {
  border-color: rgba(148, 163, 184, 0.48);
  background: rgba(255, 255, 255, 0.98);
}
.download-list-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  line-height: 1.25;
  font-weight: 650;
  color: rgb(30, 41, 59);
}
.download-list-size {
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  min-width: 68px;
  text-align: right;
  font-size: 11px;
  color: rgb(148, 163, 184);
  margin-left: 8px;
  font-variant-numeric: tabular-nums;
}
.download-tree-row.bad {
  color: rgb(185, 28, 28);
  background: rgba(254, 242, 242, 0.72);
  box-shadow: inset 0 0 0 1px rgba(254, 202, 202, 0.8);
  cursor: default;
}
.http-preview-error-icon {
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 20px;
  color: rgb(239, 68, 68);
}
.http-preview-error-placeholder {
  width: 20px;
  height: 20px;
  display: block;
}
.http-preview-empty {
  height: 100%;
  min-height: 220px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 8px;
  color: rgb(148, 163, 184);
  font-size: 13px;
  font-weight: 650;
}
.http-source-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  border: 0;
  background: transparent;
  color: var(--asmr-text-muted);
}
.http-source-icon.is-gofile {
  width: 20px;
}
.http-source-fallback-gofile {
  width: 18px;
  height: 18px;
  display: block;
}
.http-source-icon img {
  width: 18px;
  height: 18px;
  object-fit: contain;
  border-radius: 3px;
  display: block;
}
.http-preview-main {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 4px;
}
.download-tree-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}
.download-tree-name-line {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.http-preview-name {
  color: rgb(30, 41, 59);
  font-size: 13px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.download-tree-row.bad .http-preview-name {
  white-space: normal;
  overflow: visible;
  line-height: 1.3;
}
.http-preview-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 8px;
  color: rgb(100, 116, 139);
  font-size: 10.5px;
  line-height: 1.25;
}
.http-preview-pass-chip {
  display: inline-flex;
  align-items: center;
  min-height: 16px;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid transparent;
}
.http-preview-reason {
  flex: 1 1 100%;
  min-width: 0;
  color: rgb(185, 28, 28);
  font-size: 11px;
  font-weight: 620;
  line-height: 1.35;
  white-space: normal;
  word-break: break-word;
}
.http-preview-pass-chip {
  background: rgba(254, 243, 199, 0.7);
  border-color: rgba(251, 191, 36, 0.3);
  color: rgb(180, 83, 9);
}
.http-preview-meta .warn { color: rgb(180, 83, 9); }
.download-tree-row.bad .http-preview-meta {
  color: rgb(153, 27, 27);
}
.download-tree-row.bad .http-preview-meta .warn {
  color: rgb(185, 28, 28);
}
.download-tree-row.bad .http-preview-pass-chip {
  background: rgba(254, 226, 226, 0.72);
  border-color: rgba(252, 165, 165, 0.32);
}
.download-tree-row.bad .http-preview-pass-chip {
  color: rgb(185, 83, 0);
}
.preview-context-menu {
  position: absolute;
  z-index: 25;
  width: 176px;
  padding: 6px;
  border-radius: 10px;
  border: 1px solid rgba(203, 213, 225, 0.86);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(10px);
}
.preview-context-menu button {
  width: 100%;
  height: 32px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 9px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: rgb(51, 65, 85);
  font-size: 12px;
  font-weight: 750;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.preview-context-menu button:hover:not(:disabled) {
  background: rgba(239, 246, 255, 0.92);
  color: rgb(29, 78, 216);
  transform: translateY(-1px) scale(1.01);
}
.preview-context-menu button:hover:not(:disabled) svg {
  transform: rotate(-8deg) scale(1.08);
}
.preview-context-menu button:active:not(:disabled) {
  transform: scale(0.96);
}
.preview-context-menu button:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}
.preview-selection-toggle {
  height: 30px;
  min-width: 68px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 12px;
  border: 1px solid rgba(203, 213, 225, 0.82);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.82);
  color: rgb(71, 85, 105);
  font-size: 12px;
  font-weight: 750;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.preview-selection-toggle.is-clear {
  background: rgba(248, 250, 252, 0.88);
  color: rgb(100, 116, 139);
}
.preview-selection-toggle:hover:not(:disabled) {
  border-color: rgba(147, 197, 253, 0.72);
  background: rgba(239, 246, 255, 0.92);
  color: rgb(29, 78, 216);
  transform: translateY(-1px) scale(1.02);
}
.preview-selection-toggle:hover:not(:disabled) svg {
  transform: rotate(-8deg) scale(1.08);
}
.preview-selection-toggle:active:not(:disabled) {
  transform: scale(0.96);
}
.preview-selection-toggle:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}
.tab-count {
  padding: 2px 5px;
  border-radius: 999px;
  font-size: 10px;
  line-height: 1;
  font-weight: 500;
  background: rgba(248, 250, 252, 0.4);
  color: rgb(156, 163, 175);
}
.tab-chip-active .tab-count {
  background: rgba(255, 255, 255, 0.25);
  color: #ffffff;
}
.tab-chip-partial .tab-count {
  background: rgba(59, 130, 246, 0.15);
  color: #2563eb;
}
.http-policy-dd :deep(.app-dd-trigger) {
  background: var(--asmr-field-bg);
  border-color: var(--asmr-border);
  color: var(--asmr-text-strong);
}
.http-policy-dd :deep(.app-dd-trigger:hover),
.http-policy-dd :deep(.app-dd-trigger.is-open) {
  background: var(--asmr-field-bg-focus);
  border-color: var(--asmr-border-strong);
  box-shadow: 0 0 0 3px var(--asmr-focus-ring);
}
.http-policy-dd :deep(.app-dd-trigger-value),
.http-policy-dd :deep(.app-dd-trigger-caret) {
  color: var(--asmr-text-strong);
}
@keyframes asmr-health-spin { to { transform: rotate(360deg); } }
@keyframes asmr-health-pop {
  0% { transform: scale(0.82); opacity: 0.6; }
  100% { transform: scale(1); opacity: 1; }
}

:global(html.kikoerumanager-dark .http-download-preview-modal.el-dialog) {
  background: transparent !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-window),
:global(html.kikoerumanager-dark .http-download-preview-modal .glass-shell) {
  background: #101010 !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  color: #eeeeee !important;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.62), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .window-header),
:global(html.kikoerumanager-dark .http-download-preview-modal .tabs-row),
:global(html.kikoerumanager-dark .http-download-preview-modal .footer-row) {
  background: #131313 !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .glass-card),
:global(html.kikoerumanager-dark .http-download-preview-modal .glass-panel) {
  background: #181818 !important;
  border-color: rgba(255, 255, 255, 0.09) !important;
  color: #eeeeee !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .title),
:global(html.kikoerumanager-dark .http-download-preview-modal h1),
:global(html.kikoerumanager-dark .http-download-preview-modal h2),
:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-status-title),
:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-name),
:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-name),
:global(html.kikoerumanager-dark .http-download-preview-modal .summary-strong),
:global(html.kikoerumanager-dark .http-download-preview-modal .summary-stack span) {
  color: #f5f5f5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal p),
:global(html.kikoerumanager-dark .http-download-preview-modal .summary),
:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-status-sub),
:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-status-count),
:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-meta),
:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-size),
:global(html.kikoerumanager-dark .http-download-preview-modal .summary-stack) {
  color: #a3a3a3 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-status-card) {
  background: #121212 !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .baidu-pass-code-input) {
  background: #111111 !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .baidu-custom-preview) {
  color: #93c5fd !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .baidu-pass-code-btn) {
  background: #1c1c1c !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: #d4d4d4 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-progress) {
  background: #252525 !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-progress-fill) {
  background: #9ca3af !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-log) {
  background: #111111 !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-log-row) {
  color: #d4d4d4 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-log-time) {
  color: #737373 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-log-row.is-success) {
  color: #e5e7eb !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-log-row.is-warning),
:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-meta .warn) {
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-pass-chip) {
  background: #22242a !important;
  color: #e5e7eb !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-reason) {
  color: #fecaca !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .http-preview-log-row.is-error),
:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row.bad),
:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row.bad .http-preview-meta) {
  color: #fca5a5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-head) {
  background: #171717 !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-head > span),
:global(html.kikoerumanager-dark .http-download-preview-modal .tab-count) {
  background: #242424 !important;
  color: #d4d4d4 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-scroll) {
  background: #181818 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row) {
  color: #eeeeee !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row:hover) {
  background: rgba(255, 255, 255, 0.045) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row.selected) {
  background: #242424 !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.18) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row.is-context) {
  background: rgba(59, 130, 246, 0.16) !important;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.28) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row.bad) {
  background: rgba(127, 29, 29, 0.18) !important;
  box-shadow: inset 0 0 0 1px rgba(248, 113, 113, 0.2) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-toggle) {
  color: #a1a1aa !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row.is-dir .download-tree-kind-icon) {
  color: #fbbf24 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row.is-file .download-tree-kind-icon) {
  color: #7dd3fc !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-row.bad .download-tree-kind-icon) {
  color: #fca5a5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-tree-toggle:hover) {
  background: rgba(255, 255, 255, 0.08) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-check.is-off) {
  background: #111111 !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-check.is-on) {
  background: #d4d4d8 !important;
  border-color: #d4d4d8 !important;
  color: #111111 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-check.is-partial) {
  background: rgba(212, 212, 216, 0.18) !important;
  border-color: #d4d4d8 !important;
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .download-list-check.is-disabled) {
  background: rgba(127, 29, 29, 0.18) !important;
  border-color: rgba(248, 113, 113, 0.28) !important;
  color: transparent !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .preview-context-menu) {
  background: #1c1c1c !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.42) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .preview-context-menu button) {
  color: #d4d4d4 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .preview-context-menu button:hover:not(:disabled)) {
  background: rgba(255, 255, 255, 0.08) !important;
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .tab-chip) {
  background: #1b1b1b !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: #d4d4d4 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .tab-chip-active),
:global(html.kikoerumanager-dark .http-download-preview-modal .tab-chip-partial) {
  background: #2a2a2a !important;
  border-color: rgba(255, 255, 255, 0.22) !important;
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .preview-selection-toggle) {
  background: #1b1b1b !important;
  border-color: rgba(255, 255, 255, 0.12) !important;
  color: #d4d4d4 !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .preview-selection-toggle.is-clear) {
  background: #202020 !important;
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .preview-selection-toggle:hover:not(:disabled)) {
  background: rgba(255, 255, 255, 0.08) !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  color: #f4f4f5 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .primary-cta) {
  background: #2f2f2f !important;
  border-color: rgba(255, 255, 255, 0.14) !important;
  color: #f4f4f5 !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .primary-cta:hover:not(:disabled)) {
  background: #3a3a3a !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .secondary-cta),
:global(html.kikoerumanager-dark .http-download-preview-modal .interactive-chip) {
  background: #1c1c1c !important;
  border-color: rgba(255, 255, 255, 0.1) !important;
  color: #d4d4d4 !important;
}

:global(html.kikoerumanager-dark .http-download-preview-modal .app-loading-animation__label),
:global(html.kikoerumanager-dark .http-download-preview-modal .app-loading-animation__description) {
  color: #d4d4d4 !important;
}

:global(.http-download-preview-modal .footer-row) {
  min-height: 56px !important;
}

:global(.http-download-preview-modal .summary) {
  font-size: 12px !important;
}

:global(.http-download-preview-modal .primary-cta),
:global(.http-download-preview-modal .secondary-cta) {
  height: 38px !important;
  padding-inline: 28px !important;
  border-radius: 10px !important;
}

@media (max-width: 960px) {
  .http-preview-content {
    flex-direction: column;
    gap: 16px;
    padding: 6px 18px;
  }
  .left-column {
    width: auto;
    flex-basis: auto;
    gap: 16px;
  }
}
@media (max-width: 720px) {
  .http-health-path { display: none; }
  .http-actions { justify-content: stretch; }
  .http-actions .asmr-mini-btn { flex: 1; justify-content: center; }
  .summary-stack span { float: none; display: block; max-width: 100%; margin-top: 2px; }
  .http-preview-log-row {
    grid-template-columns: 1fr;
    gap: 2px;
  }
}
</style>









