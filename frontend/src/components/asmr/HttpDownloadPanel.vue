<template>
  <section class="asmr-card http-download-panel">
    <header class="asmr-card-head">
      <div class="asmr-card-head-title">
        <CloudDownload :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
        <div>
          <h2>HTTP 外链下载</h2>
          <p class="asmr-card-head-subtitle">HTTP 直链 / PikPak 分享解析后通过 aria2 下载</p>
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
        placeholder="粘贴 HTTP/HTTPS 直链或 PikPak 分享链接，一行一个。Gofile / TranFile 页面链接首版只提示人工获取直链。"
      ></textarea>

      <div class="http-download-options">
        <label class="http-field">
          <span>目标子目录</span>
          <input v-model.trim="targetSubdir" class="http-input" type="text" placeholder="可选，例如 gofile/RJ123456">
        </label>
        <label class="http-field">
          <span>冲突策略</span>
          <AppDropdown v-model="conflictPolicy" :options="conflictOptions" class="http-policy-dd" :width="150" />
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
        <button class="asmr-mini-btn is-primary" type="button" :disabled="starting || !okPreviewCount" @click="start">
          <Download :size="12" :stroke-width="2.4" />
          {{ starting ? '创建中...' : `开始下载 (${okPreviewCount})` }}
        </button>
      </div>

      <Transition name="asmr-section">
        <div v-if="previewItems.length" class="http-preview-list">
          <div v-for="item in previewItems" :key="item.masked_url || item.url" class="http-preview-row" :class="{ bad: !item.ok }">
            <component :is="item.ok ? FileDown : AlertTriangle" :size="15" :stroke-width="2.3" />
            <div class="http-preview-main">
              <div class="http-preview-name">{{ item.ok ? item.filename : item.masked_url }}</div>
              <div class="http-preview-meta">
                <span v-if="item.ok">{{ formatSize(item.size_bytes) }}</span>
                <span v-if="item.ok">{{ item.resumable ? '支持断点' : '未声明断点' }}</span>
                <span v-if="item.ok && item.source === 'pikpak'">PikPak</span>
                <span v-if="item.ok">{{ item.relative_path }}</span>
                <span v-if="item.ok && previewNeedsMaterialize" class="warn">开始时解析直链</span>
                <span v-if="!item.ok">{{ item.reason }}</span>
                <span v-if="item.warning" class="warn">{{ item.warning }}</span>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { AlertTriangle, CloudDownload, Download, FileDown, RefreshCw, Search } from 'lucide-vue-next'
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

const okPreviewCount = computed(() => previewItems.value.filter(item => item.ok).length)

const healthText = computed(() => {
  if (!health.value) return '尚未检测 aria2'
  if (health.value.ok) {
    const pikpak = health.value.pikpak_enabled ? (health.value.pikpak_ready ? ' · PikPak 已配置' : ' · PikPak 缺配置') : ''
    return `aria2 可用${health.value.version?.version ? ` · ${health.value.version.version}` : ''}${pikpak}`
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
  try {
    const result = await httpDownloadApi.preview({
      urls: parsedUrls.value,
      targetSubdir: targetSubdir.value,
      conflictPolicy: conflictPolicy.value
    })
    previewItems.value = result.items || []
    previewNeedsMaterialize.value = Boolean(result.needs_materialize)
    if (result.ok_count) ElMessage.success(`可下载 ${result.ok_count} 个链接`)
    if (result.needs_materialize) ElMessage.info('PikPak 分享会在开始下载时转存并解析直链')
    if (result.failed_count) ElMessage.warning(`${result.failed_count} 个链接不可直接下载`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '预览失败')
  } finally {
    previewing.value = false
  }
}

async function start() {
  if (!okPreviewCount.value) return ElMessage.warning('先预览并确认有可下载直链')
  starting.value = true
  try {
    const result = await httpDownloadApi.start({
      urls: parsedUrls.value,
      targetSubdir: targetSubdir.value,
      conflictPolicy: conflictPolicy.value,
      batchName: batchName.value
    })
    const ids = (result.tasks || []).map(item => item.task_id || item.id).filter(Boolean)
    emit('started', ids)
    previewNeedsMaterialize.value = false
    ElMessage.success(result.message || 'HTTP 下载任务已创建')
  } catch (error) {
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

onMounted(loadHealth)
</script>

<style scoped>
.http-download-panel {
  border-radius: 16px;
  border: 1px solid rgba(226, 232, 240, 0.86);
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.06);
  overflow: hidden;
}
.asmr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.76);
  background: rgba(248, 250, 252, 0.72);
}
.asmr-card-head-title {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
.asmr-card-head-title h2 {
  margin: 0;
  color: #0f172a;
  font-size: 14px;
  font-weight: 750;
}
.asmr-card-head-subtitle {
  margin: 1px 0 0;
  color: #64748b;
  font-size: 12px;
}
.asmr-card-head-icon { color: #2563eb; flex-shrink: 0; }
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
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(255, 255, 255, 0.92);
  color: #334155;
  font-size: 12px;
  font-weight: 650;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.asmr-mini-btn:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(37, 99, 235, 0.3);
  color: #1d4ed8;
}
.asmr-mini-btn:active:not(:disabled) { transform: scale(0.96); }
.asmr-mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.asmr-mini-btn :deep(svg) { transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.asmr-mini-btn:hover:not(:disabled) :deep(svg) { transform: rotate(-8deg) scale(1.08); }
.asmr-mini-btn.is-primary {
  background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
  border-color: rgba(15, 23, 42, 0.2);
  color: #fff;
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.16);
}
.asmr-mini-btn.is-primary:hover:not(:disabled) {
  color: #fff;
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22);
}
.http-download-body { display: grid; gap: 12px; }
.http-download-health {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(248, 250, 252, 0.82);
  color: #64748b;
  font-size: 12px;
}
.http-download-health.ok { border-color: rgba(16, 185, 129, 0.24); background: rgba(236, 253, 245, 0.72); color: #047857; }
.http-download-health.bad { border-color: rgba(239, 68, 68, 0.22); background: rgba(254, 242, 242, 0.72); color: #b91c1c; }
.http-health-dot { width: 7px; height: 7px; border-radius: 999px; background: currentColor; opacity: .82; }
.http-health-path { margin-left: auto; max-width: 46%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; opacity: .78; }
.http-url-input,
.http-input {
  width: 100%;
  border: 1px solid rgba(203, 213, 225, 0.88);
  background: rgba(248, 250, 252, 0.92);
  color: #0f172a;
  outline: none;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.http-url-input { resize: vertical; min-height: 118px; padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.55; }
.http-input { height: 36px; padding: 0 10px; border-radius: 8px; font-size: 13px; }
.http-url-input:focus,
.http-input:focus { border-color: rgba(37, 99, 235, 0.48); background: #fff; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12); }
.http-download-options { display: flex; align-items: end; gap: 10px; flex-wrap: wrap; }
.http-field { display: grid; gap: 5px; min-width: 180px; color: #64748b; font-size: 12px; font-weight: 600; }
.http-field.grow { flex: 1 1 240px; }
.http-actions { display: flex; gap: 8px; justify-content: flex-end; }
.http-preview-list { display: grid; gap: 8px; }
.http-preview-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: rgba(255, 255, 255, 0.86);
  color: #2563eb;
}
.http-preview-row.bad { color: #dc2626; background: rgba(254, 242, 242, 0.68); border-color: rgba(248, 113, 113, 0.24); }
.http-preview-main { min-width: 0; flex: 1; }
.http-preview-name { color: #0f172a; font-size: 13px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.http-preview-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 3px; color: #64748b; font-size: 11.5px; }
.http-preview-meta .warn { color: #d97706; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) {
  .http-health-path { display: none; }
  .http-actions { justify-content: stretch; }
  .http-actions .asmr-mini-btn { flex: 1; justify-content: center; }
}
</style>
