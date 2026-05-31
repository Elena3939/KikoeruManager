<template>
  <section class="asmr-card http-download-panel">
    <header class="asmr-card-head">
      <div class="asmr-card-head-title">
        <CloudDownload :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
        <div>
          <h2>HTTP 外链下载</h2>
          <p class="asmr-card-head-subtitle">HTTP 直链 / Gofile / Transfer.it / OneDrive / Google Drive / PikPak</p>
        </div>
      </div>
      <div class="asmr-card-head-actions">
        <button class="asmr-mini-btn" type="button" :disabled="healthLoading" @click="loadHealth">
          <RefreshCw :size="12" :stroke-width="2.4" :class="{ 'spin': healthLoading }" />
          检测 aria2
        </button>
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
        placeholder="粘贴 HTTP/HTTPS 直链或分享链接，一行一个。支持 Gofile、Transfer.it、OneDrive、Google Drive、PikPak。"
      ></textarea>

      <div class="http-download-options">
        <label class="http-field">
          <span>目标子目录</span>
          <input v-model.trim="targetSubdir" class="http-input" type="text" placeholder="可选，例如 gofile/RJ123456">
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
        <button class="asmr-mini-btn" type="button" :disabled="previewing || !parsedUrls.length" @click="preview">
          <Search :size="12" :stroke-width="2.4" />
          {{ previewing ? '预览中...' : `预览 ${parsedUrls.length || ''}` }}
        </button>
        <button class="asmr-mini-btn is-primary" type="button" :disabled="starting || !selectedOkCount" @click="start">
          <Download :size="12" :stroke-width="2.4" />
          {{ starting ? '创建中...' : `开始下载 (${selectedOkCount})` }}
        </button>
      </div>

      <Transition name="asmr-section">
        <div v-if="previewing || previewItems.length || previewLogs.length" class="http-preview-workbench">
          <div class="http-preview-status">
            <div>
              <div class="http-preview-status-title">{{ previewStatusTitle }}</div>
              <div class="http-preview-status-text">{{ previewStatusText }}</div>
            </div>
            <span class="http-preview-status-count">{{ selectedOkCount }}/{{ okPreviewCount }} 已选</span>
          </div>
          <div class="http-preview-progress">
            <div class="http-preview-progress-fill" :style="{ width: `${previewProgress}%` }"></div>
          </div>

          <div v-if="previewLogs.length" class="http-preview-log">
            <div v-for="entry in previewLogs" :key="entry.id" class="http-preview-log-row" :class="`is-${entry.level}`">
              <span class="http-preview-log-time">{{ entry.time }}</span>
              <span class="http-preview-log-text">{{ entry.message }}</span>
            </div>
          </div>

          <div v-if="previewItems.length" class="http-preview-toolbar">
            <button class="http-link-btn" type="button" :disabled="!okPreviewCount" @click="selectAllPreviewItems">全选</button>
            <button class="http-link-btn" type="button" :disabled="!selectedOkCount" @click="clearPreviewSelection">清空</button>
          </div>

          <div v-if="previewItems.length" class="http-preview-list">
            <label
              v-for="item in previewItems"
              :key="previewItemKey(item)"
              class="http-preview-row"
              :class="{ bad: !item.ok, selected: isPreviewItemSelected(item) }"
            >
              <input
                v-if="item.ok"
                class="http-preview-check"
                type="checkbox"
                :checked="isPreviewItemSelected(item)"
                @change="togglePreviewItem(item)"
              >
              <component v-else :is="AlertTriangle" :size="15" :stroke-width="2.3" />
              <span
                class="http-source-icon"
                :class="`is-${sourceKey(item.source)}`"
                :title="sourceLabel(item.source)"
                :aria-label="sourceLabel(item.source)"
              >
                <img
                  v-if="sourceIcon(item.source) && !isSourceIconFailed(item.source)"
                  :src="sourceIcon(item.source)"
                  alt=""
                  loading="lazy"
                  decoding="async"
                  @error="markSourceIconFailed(item.source)"
                >
                <svg
                  v-else-if="sourceKey(item.source) === 'gofile'"
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
              <div class="http-preview-main">
                <div class="http-preview-name">{{ item.ok ? item.filename : item.masked_url }}</div>
                <div class="http-preview-meta">
                  <span v-if="item.ok">{{ formatSize(item.size_bytes) }}</span>
                  <span v-if="item.ok">{{ item.resumable ? '支持断点' : '未声明断点' }}</span>
                  <span v-if="item.ok">{{ item.relative_path }}</span>
                  <span v-if="item.ok && item.share_url">{{ item.share_url }}</span>
                  <span v-if="item.ok && previewNeedsMaterialize" class="warn">开始时解析直链</span>
                  <span v-if="!item.ok">{{ item.reason }}</span>
                  <span v-if="item.warning" class="warn">{{ item.warning }}</span>
                </div>
              </div>
            </label>
          </div>
        </div>
      </Transition>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { AlertTriangle, CloudDownload, Download, Globe2, RefreshCw, Search } from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'
import { httpDownloadApi } from '../../api'

defineProps({
  hasTasks: { type: Boolean, default: false }
})

const emit = defineEmits(['started', 'open-workbench'])

const urlText = ref('')
const targetSubdir = ref('')
const batchName = ref('')
const conflictPolicy = ref('resume')
const previewing = ref(false)
const starting = ref(false)
const healthLoading = ref(false)
const health = ref(null)
const previewItems = ref([])
const previewNeedsMaterialize = ref(false)
const previewLogs = ref([])
const previewProgress = ref(0)
const selectedPreviewKeys = ref(new Set())
const failedSourceIcons = ref(new Set())

const SOURCE_ICONS = {
  gofile: 'https://gofile.io/favicon.ico',
  transferit: 'https://transfer.it/favicon.ico',
  onedrive: 'https://onedrive.live.com/favicon.ico',
  google_drive: 'https://ssl.gstatic.com/docs/doclist/images/drive_2022q3_32dp.png',
  pikpak: 'https://mypikpak.com/favicon.ico'
}

const conflictOptions = [
  { value: 'resume', label: '断点续传' },
  { value: 'rename', label: '自动改名' },
  { value: 'skip', label: '已存在跳过' }
]

const parsedUrls = computed(() => {
  return [...new Set(
    String(urlText.value || '')
      .split(/[\r\n]+/)
      .map(item => item.trim())
      .filter(Boolean)
  )]
})

const okPreviewItems = computed(() => previewItems.value.filter(item => item.ok))
const okPreviewCount = computed(() => okPreviewItems.value.length)
const selectedOkItems = computed(() => okPreviewItems.value.filter(item => selectedPreviewKeys.value.has(previewItemKey(item))))
const selectedOkCount = computed(() => selectedOkItems.value.length)

const previewStatusTitle = computed(() => {
  if (previewing.value) return '正在解析链接'
  if (!previewItems.value.length) return '等待预览'
  if (okPreviewCount.value) return `已解析 ${okPreviewCount.value} 个可下载项`
  return '没有可下载项'
})

const previewStatusText = computed(() => {
  if (previewing.value) return `正在按站点解析 ${parsedUrls.value.length} 个链接`
  if (!previewItems.value.length) return '粘贴多个链接后一行一个，先预览再勾选下载。'
  const failed = previewItems.value.length - okPreviewCount.value
  return failed ? `${failed} 项解析失败或不可直接下载` : '解析完成，可以勾选需要下载的项目。'
})

const healthText = computed(() => {
  if (!health.value) return '尚未检测 aria2'
  if (health.value.ok) {
    const pikpak = health.value.pikpak_enabled ? (health.value.pikpak_ready ? ' · PikPak 已配置' : ' · PikPak 缺配置') : ''
    const gofile = health.value.gofile_ready ? ' · Gofile 已配置' : ''
    return `aria2 可用${health.value.version?.version ? ` · ${health.value.version.version}` : ''}${gofile}${pikpak}`
  }
  return health.value.message || 'aria2 不可用'
})

async function loadHealth() {
  healthLoading.value = true
  try {
    health.value = await httpDownloadApi.health()
  } catch (error) {
    health.value = { ok: false, message: error.response?.data?.detail || error.message || '检测失败' }
  } finally {
    healthLoading.value = false
  }
}

async function preview() {
  if (!parsedUrls.value.length) return ElMessage.warning('先粘贴至少一个下载链接')
  previewing.value = true
  previewItems.value = []
  previewNeedsMaterialize.value = false
  selectedPreviewKeys.value = new Set()
  previewProgress.value = 8
  previewLogs.value = []
  addPreviewLog(`开始解析 ${parsedUrls.value.length} 个链接`)
  parsedUrls.value.forEach((url, index) => {
    addPreviewLog(`[${index + 1}/${parsedUrls.value.length}] ${sourceLabel(sourceFromUrl(url))} · ${url}`)
  })
  try {
    const urls = parsedUrls.value
    for (let index = 0; index < urls.length; index += 1) {
      const url = urls[index]
      previewProgress.value = Math.max(8, Math.round((index / urls.length) * 92))
      try {
        const result = await httpDownloadApi.preview({
          urls: [url],
          targetSubdir: targetSubdir.value,
          conflictPolicy: conflictPolicy.value,
          timeout: 45000
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
    addPreviewLog(`解析完成，可下载 ${okPreviewCount.value} 项，失败 ${previewItems.value.length - okPreviewCount.value} 项`, okPreviewCount.value ? 'success' : 'warning')
    if (previewNeedsMaterialize.value) addPreviewLog('部分分享链接会在开始下载时转存或调用专用下载器', 'warning')
    if (okPreviewCount.value) ElMessage.success(`可下载 ${okPreviewCount.value} 个链接`)
    if (previewNeedsMaterialize.value) ElMessage.info('部分分享链接会在开始下载时转存或调用专用下载器')
    if (previewItems.value.length - okPreviewCount.value) ElMessage.warning(`${previewItems.value.length - okPreviewCount.value} 个链接不可直接下载`)
  } finally {
    previewing.value = false
  }
}

async function start() {
  if (!selectedOkCount.value) return ElMessage.warning('先勾选至少一个下载项')
  starting.value = true
  try {
    addPreviewLog(`提交 ${selectedOkCount.value} 个选中下载项`)
    const result = await httpDownloadApi.start({
      urls: parsedUrls.value,
      targetSubdir: targetSubdir.value,
      conflictPolicy: conflictPolicy.value,
      batchName: batchName.value,
      selectedKeys: [...selectedPreviewKeys.value],
      selectedItems: selectedOkItems.value
    })
    const ids = (result.tasks || []).map(item => item.task_id || item.id).filter(Boolean)
    emit('started', ids)
    previewNeedsMaterialize.value = false
    addPreviewLog(result.message || 'HTTP 下载任务已创建', 'success')
    ElMessage.success(result.message || 'HTTP 下载任务已创建')
  } catch (error) {
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
  return {
    http: 'HTTP',
    gofile: 'Gofile',
    transferit: 'Transfer.it',
    onedrive: 'OneDrive',
    google_drive: 'Google Drive',
    pikpak: 'PikPak'
  }[source] || source
}

function sourceKey(source) {
  return String(source || 'http').replace(/[^a-z0-9_-]/gi, '_').toLowerCase()
}

function sourceIcon(source) {
  return SOURCE_ICONS[sourceKey(source)] || ''
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
  const text = String(url || '').toLowerCase()
  if (text.includes('gofile.io')) return 'gofile'
  if (text.includes('transfer.it')) return 'transferit'
  if (text.includes('1drv.ms') || text.includes('onedrive.')) return 'onedrive'
  if (text.includes('drive.google.com') || text.includes('docs.google.com')) return 'google_drive'
  if (text.includes('mypikpak.com') || text.includes('drive.mypikpak.com')) return 'pikpak'
  return 'http'
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

function togglePreviewItem(item) {
  if (!item?.ok) return
  const next = new Set(selectedPreviewKeys.value)
  const key = previewItemKey(item)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selectedPreviewKeys.value = next
}

function selectAllPreviewItems() {
  selectedPreviewKeys.value = new Set(okPreviewItems.value.map(item => previewItemKey(item)))
}

function clearPreviewSelection() {
  selectedPreviewKeys.value = new Set()
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

onMounted(loadHealth)
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
.http-actions { display: flex; gap: 8px; justify-content: flex-end; }
.http-preview-workbench {
  display: grid;
  gap: 10px;
  padding-top: 4px;
  border-top: 1px solid var(--asmr-border);
}
.http-preview-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.http-preview-status-title {
  color: var(--asmr-text-strong);
  font-size: 13px;
  font-weight: 750;
}
.http-preview-status-text {
  margin-top: 2px;
  color: var(--asmr-text-muted);
  font-size: 11.5px;
}
.http-preview-status-count {
  flex-shrink: 0;
  color: var(--asmr-text);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
.http-preview-progress {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--asmr-surface-soft);
  border: 1px solid var(--asmr-border);
}
.http-preview-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--asmr-primary-bg);
  transition: width 0.36s ease;
}
.http-preview-log {
  display: grid;
  gap: 4px;
  max-height: 128px;
  overflow-y: auto;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--asmr-border);
  background: var(--asmr-field-bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.http-preview-log-row {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: 8px;
  color: var(--asmr-text);
  font-size: 11px;
  line-height: 1.45;
}
.http-preview-log-row.is-success { color: var(--asmr-success-text); }
.http-preview-log-row.is-warning { color: var(--asmr-warning-text); }
.http-preview-log-row.is-error { color: var(--asmr-danger-text); }
.http-preview-log-time {
  color: var(--asmr-text-muted);
  font-variant-numeric: tabular-nums;
}
.http-preview-log-text {
  min-width: 0;
  word-break: break-all;
}
.http-preview-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.http-link-btn {
  border: none;
  background: transparent;
  color: var(--asmr-accent);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.http-link-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.http-preview-list { display: grid; gap: 8px; }
.http-preview-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--asmr-border);
  background: var(--asmr-surface-soft);
  color: var(--asmr-accent);
  cursor: pointer;
  transition: all 0.22s ease;
}
.http-preview-row.bad { color: var(--asmr-danger-text); background: var(--asmr-danger-bg); border-color: var(--asmr-danger-border); }
.http-preview-row.selected {
  border-color: var(--asmr-border-strong);
  background: var(--asmr-surface-hover);
}
.http-preview-check {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  accent-color: var(--asmr-accent);
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
.http-preview-main { min-width: 0; flex: 1; }
.http-preview-name { color: var(--asmr-text-strong); font-size: 13px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.http-preview-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 3px; color: var(--asmr-text); font-size: 11.5px; }
.http-preview-meta .warn { color: var(--asmr-warning-text); }
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
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) {
  .http-health-path { display: none; }
  .http-actions { justify-content: stretch; }
  .http-actions .asmr-mini-btn { flex: 1; justify-content: center; }
  .http-preview-status,
  .http-preview-row {
    align-items: flex-start;
    flex-direction: column;
  }
  .http-preview-status-count,
  .http-source-icon {
    align-self: flex-start;
  }
  .http-preview-log-row {
    grid-template-columns: 1fr;
    gap: 2px;
  }
}
</style>
