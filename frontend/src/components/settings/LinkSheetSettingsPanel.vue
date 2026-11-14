<template>
  <div class="link-sheet-settings">
    <div class="sheet-toolbar sheet-import-toolbar">
      <div class="sheet-file-picker">
        <input ref="fileInput" class="sheet-file-input" type="file" accept=".xlsx" aria-label="选择 Excel 链接表" tabindex="-1" @change="file = $event.target.files?.[0] || null" />
        <button type="button" class="sheet-file-trigger" @click="fileInput?.click()"><FolderOpen :size="16" />选择文件</button>
        <span class="sheet-file-name" :class="{ 'has-file': file }" :title="file?.name || ''">
          <FileSpreadsheet v-if="file" class="sheet-file-type" :size="16" aria-hidden="true" />
          <span class="sheet-file-text">{{ file?.name || '未选择文件' }}</span>
        </span>
      </div>
      <StatefulButton class="sheet-action-primary" :disabled="!file" size="sm" @click="upload"><Upload :size="16" />上传并解析</StatefulButton>
      <StatefulButton class="sheet-action-icon sheet-refresh" :show-default-icons="false" :success-hold="0" size="sm" tone="neutral" title="刷新" aria-label="刷新链接库" @click="refreshWithFeedback">
        <template #prefix="{ loading }"><span class="sheet-refresh-glyph" :class="{ 'sheet-refresh-spinning': loading }"><RefreshCw :size="16" /></span></template>
      </StatefulButton>
      <AppDropdown
        class="sheet-version-picker"
        :model-value="batch?.id || ''"
        :options="versionOptions"
        :menu-min-width="300"
        label="版本"
        @change="switchVersion"
      />
    </div>
    <p v-if="error" role="alert" class="sheet-error">{{ error }}</p>

    <section v-if="batch" class="sheet-section">
      <div class="sheet-toolbar">
        <strong class="sheet-name">{{ batch.file_name }}</strong>
        <span>{{ statusLabels[batch.status] || batch.status }}</span>
        <StatefulButton v-if="batch.status === 'ready'" class="sheet-action-primary" size="sm" @click="confirm">确认发布正常作品</StatefulButton>
        <StatefulButton v-if="['queued', 'parsing', 'ready'].includes(batch.status)" class="sheet-action-quiet" size="sm" tone="neutral" @click="cancel">取消导入</StatefulButton>
      </div>
      <dl v-if="!isParsing" class="sheet-statistics">
        <div v-for="[key, label] in statisticFields" :key="key"><dt>{{ label }}</dt><dd>{{ batch.statistics?.[key] || 0 }}</dd></div>
      </dl>
      <p v-if="batch.error" class="sheet-error">{{ batch.error }}</p>
      <p v-if="batch.status === 'published'">清单已生效 · 社团视图{{ { ready: '已更新', updating: '更新中', failed: '更新失败' }[batch.materialization_status] }}</p>
      <p v-if="!isParsing && batch.statistics?.error">异常作品跳过并保留旧清单</p>
    </section>

    <section class="sheet-section">
      <div class="sheet-toolbar">
        <h3>{{ batch ? '批次明细' : '当前链接库' }}</h3>
        <input v-model="search" type="search" placeholder="RJ / 标题" aria-label="搜索链接库" @keydown.enter="loadWorks(1)" />
        <label v-if="batch"><input v-model="errorsOnly" type="checkbox" @change="loadWorks(1)" />仅异常</label>
        <StatefulButton class="sheet-action-quiet" size="sm" tone="neutral" @click="loadWorks(1)">查询</StatefulButton>
      </div>
      <div class="sheet-table-scroll" :aria-busy="isParsing">
        <table class="sheet-table">
          <colgroup><col class="sheet-col-work" /><col class="sheet-col-status" /><col class="sheet-col-actions" /></colgroup>
          <thead><tr><th>RJ / 标题</th><th>状态 / 异常</th><th>操作</th></tr></thead>
          <tbody v-if="!isParsing">
            <tr v-for="row in works.items" :key="row.id">
              <td><strong>{{ row.rjcode }}</strong><span class="sheet-work-title" :title="row.title">{{ row.title }}</span></td>
              <td><span>{{ changeLabels[row.change_kind] || row.change_kind }}</span><div v-for="message in row.errors" :key="message" class="sheet-error">{{ message }}</div></td>
              <td><div class="sheet-row-actions">
                <StatefulButton class="sheet-action-quiet" size="sm" tone="neutral" @click="inspect(row.id)">详情</StatefulButton>
                <StatefulButton class="sheet-action-quiet sheet-get-links" size="sm" tone="neutral" @click="inspect(row.id, true)"><Link2 :size="14" />获取下载链接</StatefulButton>
              </div></td>
            </tr>
          </tbody>
        </table>
        <div v-if="isParsing" class="sheet-parsing" role="status">
          <AppLoadingAnimation :size="96" :label="batch.status === 'queued' ? '等待解析' : importProgress.total === null ? '正在统计入库总数' : '正在解析并写入数据库'" />
          <div class="sheet-parsing-progress">
            <span>已入库</span>
            <strong>{{ importProgress.current.toLocaleString() }} / {{ importProgress.total === null ? '—' : importProgress.total.toLocaleString() }}</strong>
            <span class="sheet-parsing-percent">{{ importProgress.percent === null ? '统计中' : `${importProgress.percent}%` }}</span>
          </div>
          <div v-if="importProgress.percent !== null" class="sheet-parsing-track" role="progressbar" aria-label="RJ 行入库进度" :aria-valuenow="importProgress.current" :aria-valuemin="0" :aria-valuemax="importProgress.total || 1">
            <div :style="{ width: `${importProgress.percent}%` }" />
          </div>
        </div>
        <AppEmptyState v-else-if="!works.items.length" class="sheet-empty" :description="search || errorsOnly ? '没有匹配的作品' : '暂无记录'" />
      </div>
      <div v-if="!isParsing" class="sheet-pager km-pagination-wrap">
        <el-pagination
          :current-page="works.page"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="works.total"
          :pager-count="5"
          layout="total, sizes, prev, pager, next, jumper"
          popper-class="km-pagination-size-popper"
          background
          @update:current-page="loadWorks"
          @update:page-size="changePageSize"
        />
      </div>
    </section>

    <Transition name="sheet-dialog">
      <div v-if="detailVisible && detail" class="sheet-dialog-overlay" @click.self="detailVisible = false">
        <section class="sheet-dialog-panel" role="dialog" aria-modal="true" :aria-label="linksOnly ? '获取下载链接' : '作品属性'">
          <button type="button" class="sheet-dialog-close sheet-dialog-close-floating" aria-label="关闭" @click="detailVisible = false">×</button>
          <div class="sheet-dialog-content">
        <strong v-if="linksOnly">{{ detail.rjcode }} · {{ detail.metadata?.标题 }}</strong>
        <dl v-if="!linksOnly" class="sheet-metadata">
          <template v-for="(value, key) in detail.metadata" :key="key">
            <dt>{{ key }}</dt><dd>{{ displayMetadata(value) }}</dd>
          </template>
        </dl>
        <template v-if="linksOnly">
          <p v-for="message in detail.errors" :key="message" class="sheet-error">{{ message }}</p>
        </template>
        <div v-if="linksOnly && displayedFiles.length" class="sheet-link-actions">
          <span class="sheet-link-count">{{ displayedFiles.length }} 个可下载链接</span>
          <button v-if="displayedFiles.length > 1" type="button" class="sheet-link-button is-copy-all" title="复制全部链接" @click="copyLinks(displayedFiles, 'all')">
            <Transition name="sheet-icon-swap" mode="out-in"><Check v-if="copiedLinks.all" key="check" :size="14" /><Copy v-else key="copy" :size="14" /></Transition>
            {{ copiedLinks.all ? '已复制' : '复制全部' }}
          </button>
        </div>
        <template v-if="linksOnly">
          <div v-for="entry in displayedFiles" :key="entry.id" class="sheet-detail-file">
          <div class="sheet-detail-file-head">
            <strong>{{ entry.name }}</strong>
            <div v-if="linksOnly && entry.url" class="sheet-link-actions">
              <button type="button" class="sheet-link-button is-copy" title="复制链接" @click="copyLinks([entry], entry.id)">
                <Transition name="sheet-icon-swap" mode="out-in"><Check v-if="copiedLinks[entry.id]" key="check" :size="13" /><Copy v-else key="copy" :size="13" /></Transition>
                <span>{{ copiedLinks[entry.id] ? '已复制' : '复制' }}</span>
              </button>
              <button type="button" class="sheet-link-button is-download" title="提交到 HTTP 下载" @click="startDownload(entry.group_id)">
                <Download :size="13" />下载
              </button>
            </div>
          </div>
          <span :title="`原始大小（S）：${displayMetadata(entry.raw_size)}`">文件大小：{{ entry.size_bytes > 0 ? formatBytes(entry.size_bytes) : '大小待核实（下载时获取）' }}</span>
          <span v-if="entry.excluded">PAR2 · 不参与下载</span>
          <code v-if="linksOnly">{{ entry.url || '未提供链接' }}</code>
          </div>
        </template>
        <AppEmptyState v-if="linksOnly && !displayedFiles.length" description="没有可用的下载链接" />
          </div>
        </section>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { Upload, RefreshCw, ChevronLeft, ChevronRight, FolderOpen, FileSpreadsheet, Database, Link2, Copy, Download, Check } from 'lucide-vue-next'
import StatefulButton from '../ui/stateful-button.vue'
import AppEmptyState from '../common/AppEmptyState.vue'
import AppLoadingAnimation from '../common/AppLoadingAnimation.vue'
import AppDropdown from '../common/AppDropdown.vue'
import { linkSheetApi } from '../../api/linkSheet'
import { showSystemAlert } from '../../composables/useSystemPrompt'
import { formatBytes } from '../../composables/useActivityDetailModels'

const file = ref(null)
function displayMetadata(value) {
  return value == null || (typeof value === 'string' && !value.trim()) ? '未提供' : value
}
const fileInput = ref(null)
const batch = ref(null)
const isParsing = computed(() => ['queued', 'parsing'].includes(batch.value?.status))
const importProgress = computed(() => {
  const stats = batch.value?.statistics || {}
  const total = Number.isFinite(stats.total_works) ? stats.total_works : null
  const current = stats.stored_works || 0
  const percent = total === null ? null : total > 0 ? Math.min(100, Math.floor(current / total * 1000) / 10) : 0
  return { total, current, percent }
})
const notifiedBatches = new Set()
const history = ref([])
const historyPage = ref(1)
const works = ref({ items: [], total: 0, page: 1 })
const pageSize = ref(10)
const search = ref('')
const errorsOnly = ref(false)
const error = ref('')
const linksOnly = ref(false)
const copiedLinks = ref({})
const displayedFiles = computed(() => (detail.value?.files || []).filter(entry => !linksOnly.value || (!entry.excluded && entry.url)))
const copyTimers = new Map()
async function copyLinks(entries, key = 'all') {
  const links = entries.map(entry => String(entry.url || '').trim()).filter(Boolean)
  if (!links.length) return
  try {
    await navigator.clipboard.writeText(links.join('\n'))
    copiedLinks.value = { ...copiedLinks.value, [key]: true }
    clearTimeout(copyTimers.get(key))
    copyTimers.set(key, setTimeout(() => {
      const next = { ...copiedLinks.value }
      delete next[key]
      copiedLinks.value = next
    }, 1600))
  } catch {
    showSystemAlert({ title: '复制失败', message: '浏览器未授予剪贴板权限，请手动复制链接', type: 'warning' })
  }
}
async function startDownload(groupId = '') {
  if (!detail.value?.id) return
  await safe(async () => {
    const result = await linkSheetApi.download(detail.value.id, groupId)
    showSystemAlert({
      title: '已提交 HTTP 下载',
      message: `已创建 ${result.tasks?.length || 0} 个 MEGA 下载任务，请在 HTTP 下载工作台查看`,
      type: 'success',
    })
  })
}
const detail = ref(null)
const detailVisible = ref(false)
let timer, disposed = false, request = 0, batchRequest = 0, historyRequest = 0, detailRequest = 0
const statusLabels = { queued: '等待解析', parsing: '解析中', ready: '待确认', published: '已发布', cancelled: '已取消', failed: '失败', interrupted: '已中断' }
const versionOptions = computed(() => {
  const entries = [...history.value]
  if (batch.value && !entries.some(entry => entry.id === batch.value.id)) entries.unshift(batch.value)
  const options = [
    { value: '', label: '当前链接库', description: '已生效的作品清单', icon: Database },
    ...entries.map(entry => ({
      value: entry.id, label: entry.file_name, icon: FileSpreadsheet,
      description: (entry.created_at || '').replace('T', ' ').slice(0, 19),
      badge: { label: statusLabels[entry.status] || entry.status, tone: entry.status === 'published' ? 'emerald' : 'neutral' },
    })),
  ]
  if (historyPage.value > 1) options.push({ value: '__newer', label: '较新记录', icon: ChevronLeft })
  if (history.value.length === 20) options.push({ value: '__older', label: '更早记录', icon: ChevronRight })
  return options
})
function switchVersion({ value }) {
  if (value === '__newer') return loadHistory(historyPage.value - 1)
  if (value === '__older') return loadHistory(historyPage.value + 1)
  errorsOnly.value = false
  return value ? openBatch(value) : showLibrary()
}
const changeLabels = { added: '新增', updated: '更新', unchanged: '未变', error: '异常', pending: '暂存' }
const statisticFields = [['rows', '已读取行'], ['rj_rows', 'RJ 行'], ['files', '文件记录'], ['par2', 'PAR2'], ['added', '新增'], ['updated', '更新'], ['unchanged', '未变'], ['error', '异常'], ['skipped', '非 RJ']]

function updateBatch(next, notifyCompleted = false) {
  const wasParsing = batch.value?.id === next.id && isParsing.value
  batch.value = next
  if (next.status !== 'ready' || !(wasParsing || notifyCompleted) || notifiedBatches.has(next.id)) return
  notifiedBatches.add(next.id)
  const stats = next.statistics || {}
  const count = key => (stats[key] || 0).toLocaleString()
  void showSystemAlert({
    title: 'Excel 解析完成',
    message: next.file_name,
    description: '清单已暂存，确认发布后生效。异常作品会跳过并保留旧清单。',
    tone: stats.error ? 'warning' : 'success',
    details: [
      { label: '读取行数', value: `${count('rows')} 行 · RJ ${count('rj_rows')} · 非 RJ ${count('skipped')}` },
      { label: 'RJ 入库', value: `${count('stored_works')} / ${count('total_works')} · 重复行 ${count('duplicate_rows')}` },
      { label: '变更结果', value: `新增 ${count('added')} · 更新 ${count('updated')} · 未变 ${count('unchanged')} · 异常 ${count('error')}` },
      { label: '文件记录', value: `${count('files')} 条 · PAR2 ${count('par2')} 条` },
      { label: '解析耗时', value: `${stats.elapsed_seconds ?? '—'} 秒` },
    ],
    confirmText: '查看解析明细',
  }).catch(() => {})
}

async function safe(action) {
  error.value = ''
  try { return await action() } catch (e) {
    error.value = e.response?.data?.detail || e.message || '操作失败'
    return false
  }
}
async function loadWorks(page = 1) {
  if (isParsing.value) return
  const revision = ++request
  return safe(async () => {
    const result = await linkSheetApi.works({ page, page_size: pageSize.value, search: search.value, batch_id: batch.value?.id || '', errors_only: errorsOnly.value })
    if (!disposed && revision === request) works.value = result
  })
}
function changePageSize(size) {
  pageSize.value = size
  return loadWorks(1)
}
async function loadHistory(page = historyPage.value) {
  const revision = ++historyRequest
  return safe(async () => {
    const result = await linkSheetApi.history(page)
    if (!disposed && revision === historyRequest) { history.value = result; historyPage.value = page }
  })
}
function schedule() {
  clearTimeout(timer)
  if (disposed || !batch.value || !(['queued', 'parsing'].includes(batch.value.status) || batch.value.materialization_status === 'updating')) return
  const id = batch.value.id
  timer = setTimeout(async () => {
    await safe(async () => {
      const next = await linkSheetApi.status(id)
      if (disposed || batch.value?.id !== id) return
      const changed = next.status !== batch.value.status
      updateBatch(next)
      if (changed) { await loadWorks(1); await loadHistory() }
    })
    schedule()
  }, 1500)
}
async function openBatch(id, notifyCompleted = false) {
  const revision = ++batchRequest
  return safe(async () => {
    const result = await linkSheetApi.status(id)
    if (disposed || revision !== batchRequest) return
    updateBatch(result, notifyCompleted)
    await loadWorks(1)
    schedule()
  })
}
async function upload() {
  return safe(async () => {
    const result = await linkSheetApi.upload(file.value)
    await openBatch(result.id, true)
    await loadHistory()
  })
}
async function confirm() {
  return safe(async () => { batch.value = await linkSheetApi.confirm(batch.value.id); await loadWorks(1); await loadHistory(); schedule() })
}
async function cancel() {
  return safe(async () => { await linkSheetApi.cancel(batch.value.id); await openBatch(batch.value.id); await loadHistory() })
}
async function showLibrary() { batchRequest++; batch.value = null; errorsOnly.value = false; clearTimeout(timer); return loadWorks(1) }
async function refresh() { await loadHistory(); if (batch.value) return openBatch(batch.value.id); return loadWorks(works.value.page) }
async function refreshWithFeedback() {
  // 请求立即执行；快速响应时也保留一圈可见反馈，数据不等待动画。
  const duration = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 0 : 650
  const [result] = await Promise.all([refresh(), new Promise(resolve => setTimeout(resolve, duration))])
  return result
}
async function inspect(id, downloadLinks = false) {
  const revision = ++detailRequest
  return safe(async () => {
    const result = await linkSheetApi.detail(id)
    if (!disposed && revision === detailRequest) { linksOnly.value = downloadLinks; detail.value = result; detailVisible.value = true }
  })
}
onMounted(refresh)
onBeforeUnmount(() => {
  disposed = true
  request++
  clearTimeout(timer)
  copyTimers.forEach(timerId => clearTimeout(timerId))
  copyTimers.clear()
})
</script>

<style scoped>
.link-sheet-settings {
  --sheet-line: color-mix(in srgb, currentColor 14%, transparent);
  --sheet-line-soft: color-mix(in srgb, currentColor 9%, transparent);
  --sheet-surface: var(--set-surface, #ffffff);
  --sheet-surface-strong: var(--set-surface-hover, #ffffff);
  --sheet-action-bg: var(--set-surface, #ffffff);
  --sheet-action-text: var(--set-text-strong, #111827);
  --sheet-action-border: var(--sheet-line);
  --sheet-muted: color-mix(in srgb, currentColor 62%, transparent);
  display: flex;
  flex-direction: column;
  gap: 24px;
  min-width: 0;
  color: inherit;
}
.sheet-section { border-top: 1px solid var(--sheet-line); padding-top: 18px; min-width: 0; }
.sheet-toolbar, .sheet-row-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.sheet-version-picker { margin-left: auto; min-width: 0; max-width: 300px; }
.sheet-version-picker :deep(.app-dd-trigger) { max-width: 100%; }
.sheet-import-toolbar { padding-bottom: 2px; }
.sheet-toolbar input[type=search] {
  width: min(100%, 260px);
  height: 34px;
  border: 1px solid var(--sheet-line);
  background: var(--sheet-surface);
  border-radius: 8px;
  padding: 0 11px;
  color: inherit;
  min-width: 120px;
  transition: border-color .2s ease, background-color .2s ease;
}
.sheet-toolbar input[type=search]:focus {
  outline: none;
  border-color: color-mix(in srgb, currentColor 38%, transparent);
  background: var(--sheet-surface-strong);
}
.sheet-file-picker {
  display: flex;
  align-items: center;
  width: 320px;
  max-width: 100%;
  min-width: 0;
  height: 36px;
  border: 1px solid var(--sheet-line);
  border-radius: 8px;
  background: var(--sheet-surface);
  font-size: 12px;
}
.sheet-file-input { display: none; }
.sheet-file-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  flex: none;
  height: 100%;
  border: 0;
  border-right: 1px solid var(--sheet-line);
  border-radius: 7px 0 0 7px;
  padding: 0 12px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: transform 140ms ease-out, background-color 140ms ease-out;
}
.sheet-file-trigger:hover { background: var(--sheet-surface-strong); transform: translateY(-2px) scale(1.02); }
.sheet-file-trigger:active { transform: scale(.96); transition-duration: 60ms; }
.sheet-file-trigger svg { flex: none; transition: transform 140ms ease-out; }
.sheet-file-trigger:hover svg { transform: rotate(-6deg); }
.sheet-file-name {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 0 12px;
  overflow: hidden;
  color: var(--sheet-muted);
}
.sheet-file-text {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.sheet-file-type { flex: none; color: #16a34a; }
:global(html.kikoerumanager-dark .link-sheet-settings .sheet-file-type) { color: #4ade80; }
.sheet-file-name.has-file { color: inherit; }
.link-sheet-settings :deep(.stateful-button.sheet-action-primary),
.link-sheet-settings :deep(.stateful-button.sheet-action-quiet),
.link-sheet-settings :deep(.stateful-button.sheet-action-icon) {
  height: 36px;
  min-height: 36px;
  border-radius: 8px;
  box-shadow: none;
  --tw-translate-y: 0px;
  --tw-scale-x: 1;
  --tw-scale-y: 1;
  translate: none;
  scale: none;
  transform: none;
  transition: transform 140ms ease-out, background-color 140ms ease-out, border-color 140ms ease-out, opacity 140ms ease-out;
  will-change: auto;
}
.link-sheet-settings :deep(.stateful-button.sheet-action-primary) {
  min-width: 132px;
  border: 1px solid var(--sheet-action-border);
  background: var(--sheet-action-bg);
  color: var(--sheet-action-text);
}
.link-sheet-settings :deep(.stateful-button.sheet-action-quiet) {
  min-width: 72px;
  border: 1px solid var(--sheet-line);
  background: var(--sheet-surface);
  color: inherit;
}
.link-sheet-settings :deep(.stateful-button.sheet-action-icon) {
  width: 36px;
  min-width: 36px;
  padding-inline: 0;
  border: 1px solid var(--sheet-line);
  background: var(--sheet-surface);
  color: inherit;
}
.link-sheet-settings :deep(.stateful-button:not(:disabled):hover) {
  box-shadow: none;
  transform: translateY(-2px) scale(1.02);
}
.link-sheet-settings :deep(.stateful-button:not(:disabled):active) {
  transform: translateY(0) scale(.96);
  transition-duration: 60ms;
}
.link-sheet-settings :deep(.sheet-action-quiet:not(:disabled):hover),
.link-sheet-settings :deep(.sheet-action-icon:not(:disabled):hover) {
  background: var(--sheet-surface-strong);
}
/* 状态图标覆盖原内容，避免加载和完成时撑宽按钮或挤偏图标。 */
.link-sheet-settings :deep(.stateful-button__content) {
  position: relative;
  min-height: 20px;
  gap: 0;
}
.link-sheet-settings :deep(.stateful-button__state) {
  position: absolute;
  inset: 0;
  gap: 0;
  pointer-events: none;
}
.link-sheet-settings :deep(.stateful-button__label) { gap: 8px; }
.link-sheet-settings :deep(.stateful-button:is([data-state=loading], [data-state=success]) .stateful-button__label) { visibility: hidden; }
.link-sheet-settings :deep(.stateful-button__icon) { transition: opacity 100ms ease; }
.link-sheet-settings :deep(.stateful-button__icon.is-visible) { --stateful-button-icon-size: 16px; transform: none; }
.link-sheet-settings :deep(.stateful-button__icon--check svg) { animation: none; }
.link-sheet-settings :deep(.stateful-button__icon--loader svg) { animation-duration: .8s; }
.link-sheet-settings :deep(.sheet-refresh .stateful-button__content) { width: 16px; height: 16px; min-height: 16px; }
.link-sheet-settings :deep(.sheet-refresh .stateful-button__label) { display: none; }
.link-sheet-settings :deep(.sheet-refresh svg) {
  display: block;
  flex: none;
  transform: none !important;
  transition: none;
}
.link-sheet-settings :deep(.sheet-refresh-glyph) {
  display: inline-flex;
  transition: transform 400ms ease-out;
}
@media (hover: hover) {
  .link-sheet-settings :deep(.sheet-refresh[data-state=idle]:hover .sheet-refresh-glyph) {
    transform: rotate(180deg);
  }
}
.link-sheet-settings :deep(.sheet-refresh-spinning) {
  animation: sheet-refresh-spin .65s linear infinite;
  transition: none;
}
@keyframes sheet-refresh-spin {
  to { transform: rotate(360deg); }
}
@media (prefers-reduced-motion: reduce) {
  .link-sheet-settings :deep(.stateful-button) { transition: none; }
  .link-sheet-settings :deep(.sheet-refresh-glyph) { transition: none; animation: none; }
}
.link-sheet-settings :deep(.stateful-button:focus),
.link-sheet-settings :deep(.stateful-button:focus-visible) {
  outline: none;
  box-shadow: none;
}
.sheet-name { overflow-wrap: anywhere; min-width: 0; flex: 1; }
h3 { font-size: 15px; margin: 0; }
.sheet-statistics { display: grid; grid-template-columns: repeat(auto-fit, minmax(92px, 1fr)); gap: 8px; margin: 16px 0; }
.sheet-statistics > div { min-width: 0; padding: 10px 12px; border: 1px solid var(--sheet-line-soft); border-radius: 9px; background: var(--sheet-surface); }
.sheet-statistics dt { font-size: 11px; color: var(--sheet-muted); }
.sheet-statistics dd { font-size: 17px; margin: 4px 0 0; font-variant-numeric: tabular-nums; }
.sheet-error { color: #dc2626; font-size: 12px; overflow-wrap: anywhere; }
.sheet-table-scroll { position: relative; min-height: 360px; overflow: visible; margin-top: 12px; }
.sheet-parsing { min-height: 320px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 24px; padding: 24px 12px; }
.sheet-parsing :deep(.app-loading-animation__label) { color: inherit; }
.sheet-parsing-progress { display: flex; flex-wrap: wrap; justify-content: center; align-items: baseline; gap: 8px 12px; font-size: 13px; font-variant-numeric: tabular-nums; }
.sheet-parsing-progress strong { font-size: 18px; font-weight: 600; }
.sheet-parsing-percent { min-width: 48px; text-align: right; }
.sheet-parsing-track { width: min(100%, 320px); height: 4px; overflow: hidden; border-radius: 2px; background: var(--sheet-line); }
.sheet-parsing-track > div { height: 100%; background: #16a34a; transition: width 200ms ease-out; }
:global(html.kikoerumanager-dark .link-sheet-settings .sheet-parsing),
:global(html.kikoerumanager-dark .link-sheet-settings .sheet-table th),
:global(html.kikoerumanager-dark .link-sheet-settings .sheet-statistics dt) { color: #fff; }
:global(html.kikoerumanager-dark .link-sheet-settings .sheet-parsing-track > div) { background: #4ade80; }
.sheet-empty { position: absolute; inset: 40px 0 0; }
.sheet-table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12px; }
.sheet-table th, .sheet-table td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--sheet-line-soft); vertical-align: middle; overflow-wrap: anywhere; }
.sheet-table th { background: var(--set-panel-bg, #fff); color: var(--sheet-muted); font-size: 11px; font-weight: 600; white-space: nowrap; }
.sheet-col-status { width: 22%; }
.sheet-col-actions { width: 240px; }
.sheet-table th:last-child, .sheet-table td:last-child { text-align: center; }
.sheet-table .sheet-row-actions { justify-content: center; }
.sheet-row-actions label { white-space: nowrap; }
.sheet-table tbody tr:last-child td { border-bottom: 0; }
.sheet-table tbody tr:hover { background: var(--sheet-surface); }
.sheet-work-title { display: block; margin-top: 3px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; line-height: 18px; }
.sheet-pager { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--sheet-line-soft); }
.sheet-pager :deep(.el-pagination) { flex-wrap: wrap; justify-content: flex-end; row-gap: 12px; }
.sheet-dialog-overlay { position: fixed; inset: 0; z-index: 3000; display: flex; align-items: center; justify-content: center; padding: 24px; background: rgba(5, 7, 12, .72); }
.sheet-dialog-panel { position: relative; width: min(800px, 100%); max-height: min(760px, calc(100vh - 48px)); display: flex; flex-direction: column; overflow: hidden; border: 1px solid color-mix(in srgb, currentColor 14%, transparent); border-radius: 18px; background: var(--set-panel-bg, #111318); color: inherit; box-shadow: 0 18px 56px rgba(0, 0, 0, .36); }
.sheet-dialog-close { width: 32px; height: 32px; border: 0; border-radius: 8px; background: transparent; color: var(--sheet-muted); font-size: 24px; line-height: 1; cursor: pointer; transition: all .3s cubic-bezier(.34, 1.56, .64, 1); }
.sheet-dialog-close:hover { transform: rotate(90deg) scale(1.08); color: inherit; background: var(--sheet-surface-strong); }
.sheet-dialog-close-floating { position: absolute; top: 12px; right: 14px; z-index: 1; }
.sheet-dialog-close:focus, .sheet-dialog-close:focus-visible { outline: none; box-shadow: none; }
.sheet-dialog-content { min-width: 0; overflow: auto; padding: 16px 20px 20px; }
.sheet-detail { min-width: 0; max-width: 100%; }
.sheet-icon-swap-enter-active, .sheet-icon-swap-leave-active { transition: opacity .16s ease, transform .16s ease; }
.sheet-icon-swap-enter-from { opacity: 0; transform: scale(.55) rotate(-25deg); }
.sheet-icon-swap-leave-to { opacity: 0; transform: scale(.55) rotate(25deg); }
.sheet-dialog-enter-active, .sheet-dialog-leave-active { transition: opacity .2s ease; }
.sheet-dialog-enter-active .sheet-dialog-panel, .sheet-dialog-leave-active .sheet-dialog-panel { transition: transform .24s cubic-bezier(.34, 1.56, .64, 1), opacity .2s ease; }
.sheet-dialog-enter-from, .sheet-dialog-leave-to { opacity: 0; }
.sheet-dialog-enter-from .sheet-dialog-panel, .sheet-dialog-leave-to .sheet-dialog-panel { opacity: 0; transform: translateY(12px) scale(.98); }
@media (max-width: 640px) {
  .sheet-dialog-overlay { align-items: flex-end; padding: 0; }
  .sheet-dialog-panel { max-height: 92vh; border-radius: 18px 18px 0 0; }
  .sheet-dialog-content { padding-left: 16px; padding-right: 16px; }
}
.sheet-metadata { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: 8px 12px; font-size: 12px; }
.sheet-metadata dt { color: #71717a; }
.sheet-metadata dd { margin: 0; overflow-wrap: anywhere; }
.sheet-detail-file { display: flex; flex-direction: column; gap: 6px; border-bottom: 1px solid var(--sheet-line-soft); padding: 12px 0; overflow-wrap: anywhere; }
.sheet-detail-file code { font-size: 11px; white-space: normal; }
.sheet-detail { min-width: 0; max-width: 100%; overflow: hidden; }
.sheet-detail-file code { display: block; max-width: 100%; overflow-wrap: anywhere; word-break: break-word; }
.sheet-detail-file-head, .sheet-link-actions { display: flex; align-items: center; gap: 8px; }
.sheet-detail-file-head { justify-content: space-between; gap: 12px; }
.sheet-link-actions { flex-wrap: wrap; }
.sheet-link-count { color: var(--sheet-muted); font-size: 12px; margin-right: auto; }
.sheet-link-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 32px; border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 8px; padding: 5px 10px; color: var(--set-text, inherit); background: color-mix(in srgb, currentColor 5%, transparent); font-size: 12px; font-weight: 550; line-height: 1; white-space: nowrap; text-decoration: none; cursor: pointer; transition: all .3s cubic-bezier(.34, 1.56, .64, 1); }
.sheet-link-button:hover { transform: translateY(-2px) scale(1.02); border-color: color-mix(in srgb, currentColor 32%, transparent); background: color-mix(in srgb, currentColor 10%, transparent); }
.sheet-link-button:active { transform: scale(.96); }
.sheet-link-button:focus, .sheet-link-button:focus-visible { outline: none; box-shadow: none; }
.sheet-link-button.is-copy-all { min-width: 104px; color: #dbeafe; border-color: #60a5fa66; background: #2563eb24; }
.sheet-link-button.is-copy-all:hover { color: #eff6ff; border-color: #93c5fd; background: #2563eb3d; }
.sheet-link-button.is-copy { min-width: 68px; }
.sheet-link-button.is-download { min-width: 68px; color: #bbf7d0; border-color: #4ade8066; background: #16a34a24; }
.sheet-link-button.is-download:hover { color: #f0fdf4; border-color: #86efac; background: #16a34a3d; }
:global(html.kikoerumanager-dark .sheet-statistics dt) { color: var(--km-dark-text-muted); }
:global(html.kikoerumanager-dark .sheet-metadata dt) { color: var(--km-dark-text-muted); }
:global(html.kikoerumanager-dark .sheet-error) { color: #f87171; }
:global(html.kikoerumanager-dark .link-sheet-settings) {
  --sheet-surface: color-mix(in srgb, currentColor 4%, transparent);
  --sheet-surface-strong: color-mix(in srgb, currentColor 8%, transparent);
  --sheet-action-bg: var(--set-primary-bg, #1f2937);
  --sheet-action-text: var(--set-primary-text, #fff);
  --sheet-action-border: var(--set-primary-border, transparent);
}
:global(html.kikoerumanager-dark .link-sheet-settings .sheet-table th) { background: var(--km-dark-surface, #18181b); }
@media (max-width: 640px) {
  .sheet-table th, .sheet-table td { padding: 8px 4px; }
  .sheet-col-status { width: 24%; }
  .sheet-col-actions { width: 120px; }
  .sheet-row-actions { flex-direction: column; align-items: center; gap: 4px; }
  .sheet-pager :deep(.el-pagination) { gap: 6px; justify-content: center; }
  .sheet-pager :deep(.el-pagination__total) { flex-basis: 100%; text-align: center; }
  .sheet-table-scroll { min-height: 300px; }
  .sheet-parsing { min-height: 260px; }
  .sheet-version-picker { max-width: 100%; }
  .sheet-toolbar > input[type=search],
  .sheet-file-picker { width: 100%; }
  .sheet-statistics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
