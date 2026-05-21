<template>
  <div class="detail-body" :class="row ? `tone-${statusTone(effectiveRowStatus(row))}` : ''">
    <!-- 顶部：分类 / 状态 / 关闭 -->
    <header class="detail-head">
      <button class="detail-close" type="button" @click="$emit('close')">
        <X :size="16" :stroke-width="2.6" />
      </button>
      <div class="detail-head-row">
        <div class="detail-icon" :class="`tone-${statusTone(effectiveRowStatus(row))}`">
          <component
            :is="categoryConfig.icon"
            :size="18"
            :stroke-width="2.6"
          />
        </div>
        <div class="detail-titles">
          <div class="detail-eyebrow">
            <span class="eyebrow-cat">{{ row?.category_label || '—' }}</span>
            <span
              v-if="row?.compacted"
              class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-medium tracking-wide text-slate-500 bg-slate-50/70 ring-1 ring-inset ring-slate-200/70"
            >已归档</span>
            <span
              v-if="row?.__isLite"
              class="inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-medium tracking-wide text-sky-600 bg-sky-50/70 ring-1 ring-inset ring-sky-200/70"
            >详情加载中…</span>
          </div>
          <h2 class="detail-title">{{ row ? humanAction(row) : '—' }}</h2>
          <div class="detail-subtitle">
            <span
              class="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-semibold leading-none ring-1 ring-inset"
              :class="subtitleStatusClasses(statusTone(effectiveRowStatus(row)))"
            >
              <component :is="statusConfig.icon" :size="12" :stroke-width="2.6" />
              <span>{{ statusConfig.label }}</span>
            </span>
            <!-- 后续完成的修复 / 重新爬取 / 最终状态徽章 —— 把原版的状态修复指示器还原回来 -->
            <span
              v-if="isRerun"
              class="inline-flex items-center px-1.5 py-[3px] rounded-md text-[11px] font-semibold leading-none tracking-tight ring-1 ring-inset bg-amber-50 text-amber-700 ring-amber-200/70"
              title="该任务被重新爬取过"
            >重新爬取</span>
            <span
              v-if="finalLabel"
              class="inline-flex items-center px-1.5 py-[3px] rounded-md text-[11px] font-semibold leading-none tracking-tight ring-1 ring-inset"
              :class="finalBadgeClasses(finalCls)"
              :title="finalLabel"
            >{{ finalLabel }}</span>
            <span
              v-if="isRecovered && finalLabel !== '已修复✔'"
              class="inline-flex items-center px-1.5 py-[3px] rounded-md text-[11px] font-semibold leading-none tracking-tight ring-1 ring-inset bg-emerald-50 text-emerald-700 ring-emerald-200/70"
              title="此次失败后被人工处理或重试修复"
            >已修复</span>
            <span
              v-if="row?.rjcode || displayRj"
              class="inline-flex items-center px-1.5 py-[3px] rounded-md text-[11px] font-mono font-semibold leading-none tracking-tight bg-slate-100/70 text-slate-700 ring-1 ring-inset ring-slate-200/60"
            >{{ row?.rjcode || displayRj }}</span>
            <span v-if="row?.created_at" class="subtitle-time">{{ formatDateTime(row.created_at) }}</span>
          </div>
        </div>
      </div>
    </header>

    <!-- 主滚动区 -->
    <div
      class="detail-scroll"
      v-app-loading="{ loading: loading && !hasContent, text: '正在加载详情…', size: 96, minHeight: 240, delay: 80 }"
    >
      <template v-if="!row?.__isLite">
      <!-- 摘要 -->
      <section v-if="row?.summary" class="panel">
        <div class="panel-head">
          <FileText :size="13" :stroke-width="2.4" />
          <span>摘要</span>
        </div>
        <div class="summary-text">{{ row.summary }}</div>
      </section>

      <!-- chips -->
      <section v-if="chipList.length" class="panel">
        <div class="panel-head">
          <Layers :size="13" :stroke-width="2.4" />
          <span>关键指标</span>
        </div>
        <div class="chip-grid">
          <div
            v-for="chip in chipList"
            :key="chip.label"
            class="rounded-xl px-3 py-2.5 ring-1 ring-inset transition-colors"
            :class="metricChipClasses(chip.tone)"
          >
            <div class="text-[10px] font-semibold uppercase tracking-[0.08em] opacity-60">{{ chip.label }}</div>
            <div class="text-[15px] font-bold tabular-nums tracking-tight mt-0.5">{{ chip.value }}</div>
          </div>
        </div>
      </section>

      <!-- 元数据 -->
      <section class="panel">
        <div class="panel-head">
          <Database :size="13" :stroke-width="2.4" />
          <span>元数据</span>
        </div>
        <dl class="meta-grid">
          <div v-if="row?.id" class="meta-row">
            <dt>记录 ID</dt>
            <dd class="mono">{{ row.id }}</dd>
          </div>
          <div v-if="row?.task_id" class="meta-row">
            <dt>任务 ID</dt>
            <dd class="mono">{{ row.task_id }}</dd>
          </div>
          <div v-if="row?.batch_id" class="meta-row">
            <dt>批次</dt>
            <dd class="mono">{{ row.batch_id }}</dd>
          </div>
          <div v-if="row?.session_key" class="meta-row">
            <dt>Session</dt>
            <dd class="mono">{{ row.session_key }}</dd>
          </div>
          <div v-if="sourcePathDisplay" class="meta-row">
            <dt>源路径</dt>
            <dd>
              <span class="mono path">{{ compactPath(sourcePathDisplay) }}</span>
              <button
                v-if="sourcePathDisplay"
                class="copy-btn"
                type="button"
                title="复制"
                @click="copyText(sourcePathDisplay)"
              >
                <Copy :size="11" :stroke-width="2.6" />
              </button>
            </dd>
          </div>
          <div v-if="outputPathDisplay" class="meta-row">
            <dt>输出路径</dt>
            <dd>
              <span class="mono path">{{ compactPath(outputPathDisplay) }}</span>
              <button class="copy-btn" type="button" title="复制" @click="copyText(outputPathDisplay)">
                <Copy :size="11" :stroke-width="2.6" />
              </button>
            </dd>
          </div>
        </dl>
      </section>

      <!-- 子任务时间线 -->
      <section v-if="childRows.length" class="panel">
        <div class="panel-head">
          <GitBranch :size="13" :stroke-width="2.4" />
          <span>关联事件</span>
          <span class="ml-1 inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-semibold tabular-nums tracking-tight text-slate-600 bg-slate-100/80 ring-1 ring-inset ring-slate-200/60 normal-case">{{ childRows.length }}</span>
          <button
            v-if="childRows.length > childPreview.length"
            class="panel-toggle"
            type="button"
            @click="childExpanded = !childExpanded"
          >
            <ChevronDown
              :size="12"
              :stroke-width="2.6"
              :class="{ 'is-open': childExpanded }"
            />
            {{ childExpanded ? '收起' : `展开全部` }}
          </button>
        </div>
        <ul class="child-list">
          <li
            v-for="child in childPreview"
            :key="childKey(child)"
            class="child-item"
            :class="[`tone-${statusTone(child.status)}`, { 'is-expanded': isChildExpanded(child) }]"
          >
            <div class="child-row" @click="toggleChildExpansion(child)">
              <span class="child-dot" :class="`tone-${statusTone(child.status)}`"></span>
              <div class="child-body">
                <div class="child-head">
                  <span class="child-rel">{{ humanActionFn(child) || relationLabel(child) }}</span>
                  <span
                    v-if="childRj(child)"
                    class="inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-mono font-semibold leading-none tracking-tight bg-slate-100/80 text-slate-700 ring-1 ring-inset ring-slate-200/60"
                  >{{ childRj(child) }}</span>
                  <span
                    v-if="finalStatusLabel(child)"
                    class="inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-semibold leading-none tracking-tight ring-1 ring-inset"
                    :class="finalBadgeClasses(finalStatusClass(child))"
                  >{{ finalStatusLabel(child) }}</span>
                  <span
                    v-if="isRecoveredFailure(child) && finalStatusLabel(child) !== '已修复✔'"
                    class="inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-semibold leading-none tracking-tight bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200/70"
                  >已修复</span>
                  <span class="child-time">{{ formatDateTime(child.created_at) }}</span>
                </div>
                <div class="child-summary">{{ child.summary || humanActionFn(child) || '—' }}</div>
              </div>
              <ChevronDown
                class="child-chevron"
                :size="14"
                :stroke-width="2.6"
                :class="{ 'is-open': isChildExpanded(child) }"
              />
              <button
                v-if="child.id && child.id !== row?.id"
                class="child-jump-btn"
                type="button"
                title="跳转到该子任务详情"
                @click.stop="onChildClick(child)"
              >
                <ArrowUpRight :size="13" :stroke-width="2.6" />
              </button>
            </div>
            <!-- 内联展开：展示该子任务的完整文件树 / 配对结果 / 解压产物等业务面板 -->
            <div v-if="isChildExpanded(child)" class="child-detail">
              <ActivityRichBlock
                :row="child"
                :status-tone="statusTone"
                :format-date-time="formatDateTime"
                :compact-path="compactPath"
                @navigate="(payload) => $emit('navigate', payload)"
              />
            </div>
          </li>
        </ul>
      </section>

      <!-- 业务专属面板 -->
      <ActivityRichBlock
        v-if="row && hasContent"
        :row="row"
        :status-tone="statusTone"
        :format-date-time="formatDateTime"
        :compact-path="compactPath"
        @navigate="(payload) => $emit('navigate', payload)"
      />

      <!-- 完整 detail JSON 折叠 -->
      <section v-if="rawDetailString" class="panel">
        <div class="panel-head clickable" @click="rawExpanded = !rawExpanded">
          <Code2 :size="13" :stroke-width="2.4" />
          <span>原始 detail JSON</span>
          <span class="ml-1 inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-semibold tabular-nums tracking-tight text-slate-600 bg-slate-100/80 ring-1 ring-inset ring-slate-200/60 normal-case">{{ rawDetailLines }} 行</span>
          <ChevronDown
            class="panel-toggle-icon"
            :size="14"
            :stroke-width="2.6"
            :class="{ 'is-open': rawExpanded }"
          />
        </div>
        <div v-show="rawExpanded" class="raw-json-wrap">
          <pre class="raw-json"><code>{{ rawDetailString }}</code></pre>
        </div>
      </section>

      <!-- 兜底空态 -->
      <AppEmptyState
        v-if="!hasContent && !loading"
        description="暂无更多详情"
        size="sm"
      />
      </template>
    </div>

    <!-- 底部操作 -->
    <footer class="detail-foot">
      <button
        v-if="row?.task_id"
        class="foot-btn ghost"
        type="button"
        :title="`复制任务 ID ${row.task_id}`"
        @click="copyText(row.task_id)"
      >
        <Copy :size="13" :stroke-width="2.4" />
        复制任务 ID
      </button>
      <button class="foot-btn primary" type="button" @click="$emit('close')">关闭</button>
    </footer>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowUpRight,
  ChevronDown,
  Code2,
  Copy,
  Database,
  FileText,
  GitBranch,
  Layers,
  X
} from 'lucide-vue-next'
import AppEmptyState from '../common/AppEmptyState.vue'
import ActivityRichBlock from './ActivityRichBlock.vue'
import {
  finalStatusLabel,
  finalStatusClass,
  isRecoveredFailure,
  isRerunRow,
  displayRjcode,
  humanAction as humanActionFn,
  effectiveRowStatus
} from '../../composables/useActivityDetailModels'

const props = defineProps({
  row: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  categoryConfig: { type: Object, default: () => ({ icon: null, label: '', tone: 'neutral' }) },
  statusConfig: { type: Object, default: () => ({ icon: null, label: '', tone: 'neutral' }) },
  statusTone: { type: Function, default: () => 'neutral' },
  formatDateTime: { type: Function, default: (v) => String(v || '') },
  compactPath: { type: Function, default: (v) => String(v || '') },
  humanAction: { type: Function, default: () => '' }
})
const emit = defineEmits(['close', 'open-row', 'navigate'])

// ===== Tailwind tone class 映射 =====
const SUBTITLE_STATUS_TONE_CLASS = {
  success: 'bg-emerald-50/70 text-emerald-700 ring-emerald-200/60',
  warn: 'bg-amber-50/70 text-amber-700 ring-amber-200/60',
  danger: 'bg-rose-50/70 text-rose-700 ring-rose-200/60',
  info: 'bg-sky-50/70 text-sky-700 ring-sky-200/60',
  neutral: 'bg-slate-50/70 text-slate-600 ring-slate-200/60'
}

const METRIC_CHIP_TONE_CLASS = {
  success: 'bg-emerald-50/70 ring-emerald-200/40 text-emerald-700',
  warn: 'bg-amber-50/70 ring-amber-200/40 text-amber-700',
  danger: 'bg-rose-50/70 ring-rose-200/40 text-rose-700',
  info: 'bg-sky-50/70 ring-sky-200/40 text-sky-700',
  neutral: 'bg-slate-50/70 ring-slate-200/40 text-slate-700'
}

function subtitleStatusClasses(tone) {
  return SUBTITLE_STATUS_TONE_CLASS[tone] || SUBTITLE_STATUS_TONE_CLASS.neutral
}

function metricChipClasses(tone) {
  return METRIC_CHIP_TONE_CLASS[tone] || METRIC_CHIP_TONE_CLASS.neutral
}

// ===== final-status / 已修复 / 重新爬取 徽章配色 =====
const FINAL_BADGE_CLASS = {
  'is-final-success': 'bg-emerald-50 text-emerald-700 ring-emerald-200/70',
  'is-final-partial': 'bg-amber-50 text-amber-700 ring-amber-200/70',
  'is-final-failed': 'bg-rose-50 text-rose-700 ring-rose-200/70'
}
function finalBadgeClasses(cls) {
  return FINAL_BADGE_CLASS[cls] || FINAL_BADGE_CLASS['is-final-failed']
}

const finalLabel = computed(() => (props.row ? finalStatusLabel(props.row) : ''))
const finalCls = computed(() => (props.row ? finalStatusClass(props.row) : ''))
const isRecovered = computed(() => (props.row ? isRecoveredFailure(props.row) : false))
const isRerun = computed(() => (props.row ? isRerunRow(props.row) : false))
// 兜底从 detail / source_path 推断 RJ：解决「问题作品连 RJ 都不显示」
const displayRj = computed(() => {
  if (!props.row) return ''
  const rj = displayRjcode(props.row)
  return rj && rj !== '—' ? rj : ''
})

const childExpanded = ref(false)
const rawExpanded = ref(false)
// 关联事件每一项的内联展开状态：key → 展开 ActivityRichBlock
const expandedChildIds = ref(new Set())

watch(
  () => props.row?.id,
  () => {
    childExpanded.value = false
    rawExpanded.value = false
    expandedChildIds.value = new Set()
  }
)

function childKey(child) {
  if (!child) return ''
  return String(child.id || `${child.relation || ''}-${child.created_at || ''}-${child.action || ''}`)
}
function isChildExpanded(child) {
  return expandedChildIds.value.has(childKey(child))
}
function toggleChildExpansion(child) {
  const k = childKey(child)
  if (!k) return
  const next = new Set(expandedChildIds.value)
  if (next.has(k)) next.delete(k)
  else next.add(k)
  expandedChildIds.value = next
}
function childRj(child) {
  if (!child) return ''
  const rj = displayRjcode(child)
  return rj && rj !== '—' ? rj : ''
}

// ====== 子任务行 ======
function gatherChildRows(detail) {
  const out = []
  const seen = new Set()
  const walk = (rows, depth = 0) => {
    if (!Array.isArray(rows)) return
    for (const r of rows) {
      if (!r || typeof r !== 'object') continue
      const key = String(r.id || `${r.relation || ''}-${r.created_at || ''}`)
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ ...r, __depth: depth })
      const inner = r.detail && typeof r.detail === 'object' ? r.detail : {}
      if (Array.isArray(inner.child_rows) && inner.child_rows.length) {
        walk(inner.child_rows, depth + 1)
      }
      if (Array.isArray(r.child_rows) && r.child_rows.length) {
        walk(r.child_rows, depth + 1)
      }
    }
  }
  if (Array.isArray(detail?.child_rows)) walk(detail.child_rows, 0)
  return out
}

const childRows = computed(() => {
  const detail = props.row?.detail && typeof props.row.detail === 'object' ? props.row.detail : {}
  return gatherChildRows(detail)
})

const childPreview = computed(() => {
  if (childExpanded.value) return childRows.value
  return childRows.value.slice(0, 6)
})

function relationLabel(child) {
  const relation = String(child?.relation || '').trim()
  const status = String(child?.status || '').trim()
  const map = {
    rerun: '重试',
    pair: '字幕配对',
    subtitle_import: '字幕补配',
    delete_apply: '删除执行',
    retry_apply: '失败项重试',
    retry_preview: '失败项重试',
    asmr_resource: '资源下载',
    asmr_upload: '资源上传',
    asmr_verify_failed: '校验失败',
    asmr_plan: '下载计划',
    asmr_session: '下载会话'
  }
  if (map[relation]) return map[relation]
  // 不再 fallback 到 raw action（如 task_finished），改用 status 中文兜底
  const statusLabel = ({
    success: '完成',
    completed: '完成',
    failed: '失败',
    error: '失败',
    cancelled: '已取消',
    aborted: '已取消',
    partial_success: '部分成功',
    waiting: '等待中',
    queued: '排队中',
    running: '执行中',
    incomplete: '未完成'
  })[status]
  if (statusLabel) return statusLabel
  return '关联事件'
}

function onChildClick(child) {
  if (child?.id) {
    emit('open-row', String(child.id))
  }
}

// ====== chips ======
const chipList = computed(() => {
  if (!props.row) return []
  const arr = Array.isArray(props.row.chips) ? props.row.chips : []
  return arr.filter(Boolean)
})

// ====== 路径 ======
const sourcePathDisplay = computed(() => {
  const detail = props.row?.detail && typeof props.row.detail === 'object' ? props.row.detail : {}
  return (
    props.row?.source_path
    || detail.archive_path
    || detail.source_path
    || detail.folder_path
    || ''
  )
})

const outputPathDisplay = computed(() => {
  const detail = props.row?.detail && typeof props.row.detail === 'object' ? props.row.detail : {}
  return (
    detail.output_path
    || detail.target_path
    || ''
  )
})

// ====== 原始 JSON ======
const rawDetailString = computed(() => {
  const detail = props.row?.detail
  if (!detail || typeof detail !== 'object') return ''
  try {
    return JSON.stringify(detail, jsonReplacer, 2)
  } catch {
    return ''
  }
})

function jsonReplacer(_key, value) {
  // 大列表只保留前 30 项 + 标注省略数量，避免抽屉炸开
  if (Array.isArray(value) && value.length > 30) {
    return [...value.slice(0, 30), `... (省略 ${value.length - 30} 项)`]
  }
  return value
}

const rawDetailLines = computed(() => {
  if (!rawDetailString.value) return 0
  return rawDetailString.value.split('\n').length
})

const hasContent = computed(() => {
  if (!props.row) return false
  if (props.row.summary) return true
  if (chipList.value.length) return true
  if (childRows.value.length) return true
  if (sourcePathDisplay.value) return true
  if (outputPathDisplay.value) return true
  if (rawDetailString.value) return true
  return false
})

// ====== 工具 ======
async function copyText(value) {
  const text = String(value || '').trim()
  if (!text) return
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text)
    } else {
      const el = document.createElement('textarea')
      el.value = text
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
    }
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败')
  }
}
</script>

<style scoped>
.detail-body {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  height: 100vh;
  background: #ffffff;
  font-family:
    -apple-system,
    BlinkMacSystemFont,
    'SF Pro Text',
    'Segoe UI',
    Roboto,
    'Helvetica Neue',
    Arial,
    sans-serif;
  color: #0f172a;
}

/* ===== 顶部 ===== */
.detail-head {
  position: relative;
  padding: 22px 28px 18px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.7), #ffffff);
}

.detail-close {
  position: absolute;
  top: 16px;
  right: 18px;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #ffffff;
  color: #64748b;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.detail-close:hover {
  color: #0f172a;
  background: #f1f5f9;
  transform: translateY(-1px);
}

.detail-close:active {
  transform: scale(0.95);
}

.detail-head-row {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  padding-right: 36px;
}

.detail-icon {
  width: 44px;
  height: 44px;
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: rgba(15, 23, 42, 0.05);
  color: #475569;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.detail-icon.tone-success {
  background: rgba(52, 199, 89, 0.12);
  color: #047857;
  border-color: rgba(52, 199, 89, 0.22);
}

.detail-icon.tone-warn {
  background: rgba(255, 149, 0, 0.12);
  color: #b45309;
  border-color: rgba(255, 149, 0, 0.22);
}

.detail-icon.tone-danger {
  background: rgba(255, 59, 48, 0.1);
  color: #b91c1c;
  border-color: rgba(255, 59, 48, 0.2);
}

.detail-icon.tone-info {
  background: rgba(10, 132, 255, 0.1);
  color: #0a3a8a;
  border-color: rgba(10, 132, 255, 0.22);
}

.detail-titles {
  flex: 1;
  min-width: 0;
}

.detail-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.eyebrow-cat {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: rgba(15, 23, 42, 0.5);
  text-transform: uppercase;
}

/* eyebrow-flag 已迁移到 Tailwind 内联类 */

.detail-title {
  margin: 0 0 4px;
  font-size: 20px;
  line-height: 1.3;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #0f172a;
}

.detail-subtitle {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.55);
}

/* subtitle-status / subtitle-rj 已迁移到 Tailwind 内联类 */

.subtitle-time {
  font-variant-numeric: tabular-nums;
}

/* ===== 主滚动区 ===== */
.detail-scroll {
  position: relative;
  padding: 18px 28px 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.detail-scroll::-webkit-scrollbar {
  width: 8px;
}

.detail-scroll::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.12);
  border-radius: 4px;
}

.detail-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.22);
}

/* ===== Panels ===== */
.panel {
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: #ffffff;
  padding: 14px 16px;
  box-shadow: 0 1px 1px rgba(15, 23, 42, 0.02);
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(15, 23, 42, 0.62);
  text-transform: uppercase;
  margin-bottom: 10px;
}

.panel-head.clickable {
  cursor: pointer;
  user-select: none;
}

.panel-head.clickable:hover {
  color: #0f172a;
}

/* panel-count 已迁移到 Tailwind 内联类 */

.panel-toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  text-transform: none;
  letter-spacing: 0;
  transition: all 0.2s ease;
}

.panel-toggle:hover {
  background: #fff;
  color: #0f172a;
  transform: translateY(-1px);
}

.panel-toggle .is-open {
  transform: rotate(180deg);
}

.panel-toggle-icon {
  margin-left: auto;
  transition: transform 0.2s ease;
}

.panel-toggle-icon.is-open {
  transform: rotate(180deg);
}

/* ===== Summary ===== */
.summary-text {
  font-size: 13px;
  line-height: 1.6;
  color: #1e293b;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ===== 指标 chip 网格 ===== */
.chip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
}

/* metric-chip 已迁移到 Tailwind 内联类 */

/* ===== 元数据 ===== */
.meta-grid {
  margin: 0;
  display: grid;
  gap: 8px;
}

.meta-row {
  display: grid;
  grid-template-columns: 84px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.meta-row dt {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(15, 23, 42, 0.5);
  text-transform: uppercase;
  padding-top: 2px;
}

.meta-row dd {
  margin: 0;
  font-size: 12px;
  color: #1e293b;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.meta-row .mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.path {
  word-break: break-all;
  flex: 1;
  min-width: 0;
}

.copy-btn {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.18s ease;
}

.copy-btn:hover {
  background: #fff;
  color: #0f172a;
  transform: translateY(-1px);
}

/* ===== 子任务列表 ===== */
.child-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.child-item {
  display: flex;
  flex-direction: column;
  border-radius: 10px;
  border: 1px solid transparent;
  transition: background-color 0.18s ease, border-color 0.18s ease;
}

.child-item:hover {
  background: rgba(15, 23, 42, 0.03);
  border-color: rgba(15, 23, 42, 0.06);
}

.child-item.is-expanded {
  background: rgba(240, 249, 255, 0.45);
  border-color: rgba(186, 230, 253, 0.6);
}

.child-row {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto auto;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  cursor: pointer;
}

.child-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  margin-top: 2px;
}

.child-dot.tone-success { background: #34c759; }
.child-dot.tone-warn { background: #ff9500; }
.child-dot.tone-danger { background: #ff3b30; }
.child-dot.tone-info { background: #0a84ff; }

.child-body {
  min-width: 0;
}

.child-head {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  font-size: 11px;
  margin-bottom: 2px;
}

.child-rel {
  font-weight: 700;
  color: #0f172a;
  letter-spacing: 0.02em;
}

.child-time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: rgba(15, 23, 42, 0.45);
}

.child-summary {
  font-size: 12px;
  line-height: 1.5;
  color: #475569;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.child-chevron {
  color: rgba(15, 23, 42, 0.4);
  align-self: center;
  transition: transform 0.18s ease, color 0.18s ease;
  flex: 0 0 auto;
}

.child-chevron.is-open {
  transform: rotate(180deg);
  color: #0284c7;
}

.child-jump-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: rgba(15, 23, 42, 0.4);
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease;
  flex: 0 0 auto;
}

.child-jump-btn:hover {
  background: rgba(15, 23, 42, 0.06);
  color: #0f172a;
}

/* 内联展开的子任务 RichBlock 容器 */
.child-detail {
  padding: 4px 12px 12px 30px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.child-detail :deep(.panel) {
  border-radius: 12px;
}

/* ===== 原始 JSON ===== */
.raw-json-wrap {
  margin-top: 10px;
  border-radius: 10px;
  background: #0f172a;
  padding: 12px 14px;
  max-height: 400px;
  overflow: auto;
}

.raw-json {
  margin: 0;
  font-size: 11px;
  line-height: 1.55;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: #cbd5e1;
  white-space: pre;
  word-break: keep-all;
}

.raw-json::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.raw-json::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
}

/* ===== 底部操作 ===== */
.detail-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 28px;
  border-top: 1px solid rgba(15, 23, 42, 0.06);
  background: linear-gradient(0deg, rgba(248, 250, 252, 0.7), #ffffff);
}

.foot-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  border-radius: 12px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: #fff;
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.foot-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}

.foot-btn:active {
  transform: scale(0.96);
}

.foot-btn.ghost {
  background: rgba(15, 23, 42, 0.04);
  color: #475569;
  border-color: transparent;
}

.foot-btn.primary {
  background: linear-gradient(135deg, #111827, #1e293b);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}

.foot-btn.primary:hover {
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22);
}

@media (max-width: 640px) {
  .detail-body {
    width: 100vw;
    max-width: 100vw;
    min-width: 0;
    height: 100dvh;
    grid-template-rows: auto minmax(0, 1fr) auto;
    overflow: hidden;
  }
  .detail-head {
    padding: 14px 14px 12px;
  }
  .detail-close {
    top: 12px;
    right: 12px;
    width: 34px;
    height: 34px;
  }
  .detail-head-row {
    align-items: flex-start;
    gap: 10px;
    min-width: 0;
    padding-right: 42px;
  }
  .detail-icon {
    width: 36px;
    height: 36px;
    border-radius: 12px;
  }
  .detail-titles,
  .detail-eyebrow,
  .detail-subtitle {
    min-width: 0;
    max-width: 100%;
  }
  .detail-eyebrow {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .eyebrow-cat {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .detail-title {
    font-size: 17px;
    line-height: 1.32;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
  .detail-subtitle {
    display: flex;
    gap: 5px;
    line-height: 1.35;
  }
  .subtitle-time {
    flex: 1 1 100%;
    font-size: 11px;
  }
  .detail-scroll {
    min-width: 0;
    max-width: 100%;
    padding: 12px 12px 16px;
    gap: 10px;
    overflow-x: hidden;
    -webkit-overflow-scrolling: touch;
  }
  .panel {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    padding: 12px;
    border-radius: 14px;
    overflow: hidden;
  }
  .panel-head {
    flex-wrap: wrap;
    min-width: 0;
    gap: 6px;
  }
  .summary-text {
    font-size: 12.5px;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
  .chip-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .meta-row {
    grid-template-columns: 1fr;
    gap: 4px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  }
  .meta-row:last-child {
    border-bottom: 0;
  }
  .meta-row dd {
    width: 100%;
    min-width: 0;
    display: flex;
    align-items: flex-start;
  }
  .meta-row .mono,
  .path {
    min-width: 0;
    max-width: 100%;
    white-space: normal;
    word-break: break-all;
    overflow-wrap: anywhere;
  }
  .child-row {
    grid-template-columns: 10px minmax(0, 1fr) auto;
    gap: 8px;
    padding: 8px;
  }
  .child-jump-btn {
    grid-column: 2 / -1;
    justify-self: end;
  }
  .child-time {
    flex: 1 1 100%;
    margin-left: 0;
  }
  .child-detail {
    padding: 4px 8px 10px 18px;
  }
  .raw-json-wrap {
    max-width: 100%;
    max-height: 300px;
    padding: 10px;
  }
  .raw-json {
    white-space: pre-wrap;
    word-break: break-all;
    overflow-wrap: anywhere;
  }
  .detail-foot {
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  }
  .foot-btn {
    width: 100%;
    justify-content: center;
  }
}
</style>
