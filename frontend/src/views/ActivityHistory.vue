<template>
  <div class="activity-page">
    <div class="activity-hero">
      <div class="hero-copy">
        <h1 class="hero-title">操作记录</h1>
        <p class="hero-desc">
          自动记录字幕爬取、配对、补配与解压等<strong>任务队列</strong>结果，数据保存在本地 SQLite。
          <span v-if="stats.db_path" class="db-path">当前库：{{ stats.db_path }}</span>
        </p>
      </div>
      <div class="hero-actions">
        <el-button class="ios-btn secondary" :loading="loading" @click="loadAll">
          刷新
        </el-button>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">统计区间</div>
        <div class="stat-value">{{ statsDaysLabel(stats.days) }}</div>
        <div class="stat-hint">可在下方调整</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">记录条数</div>
        <div class="stat-value">{{ stats.total_in_range }}</div>
        <div class="stat-hint">含成功与失败</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">成功占比</div>
        <div class="stat-value">{{ successRatioText }}</div>
        <div class="stat-hint">基于状态字段估算</div>
      </div>
      <div class="stat-card stat-card-control">
        <div class="stat-label">图表区间</div>
        <el-select
          v-model="statsDays"
          class="ios-select"
          size="default"
          @change="loadStats"
        >
          <el-option :value="0" label="所有时间" />
          <el-option :value="7" label="最近 7 天" />
          <el-option :value="14" label="最近 14 天" />
          <el-option :value="30" label="最近 30 天" />
        </el-select>
      </div>
    </div>

    <section class="meta-board">
      <div
        v-for="item in metricCards"
        :key="item.key"
        class="meta-card"
      >
        <div class="meta-card-head">
          <span class="meta-card-label">{{ item.label }}</span>
          <span class="meta-card-accent" :style="{ background: item.accent }"></span>
        </div>
        <div class="meta-card-value">{{ item.value }}</div>
        <div class="meta-card-hint">{{ item.hint }}</div>
      </div>
    </section>

    <div class="charts-row">
      <section class="ios-panel">
        <header class="panel-header">
          <span class="panel-title">每日操作量</span>
          <span class="panel-caption">{{ statsRangeText }}</span>
        </header>
        <div v-if="!byDay.length" class="empty-hint">暂无数据</div>
        <div v-else class="bar-chart">
          <div
            v-for="row in byDayWithPct"
            :key="row.date"
            class="bar-item"
          >
            <span class="bar-label">{{ formatShortDate(row.date) }}</span>
            <div class="bar-track">
              <div
                class="bar-fill"
                :style="{ width: row.pct + '%' }"
              />
            </div>
            <span class="bar-count">{{ row.count }}</span>
          </div>
        </div>
      </section>

      <section class="ios-panel">
        <header class="panel-header">
          <span class="panel-title">分类分布</span>
          <span class="panel-caption">{{ statsRangeText }}</span>
        </header>
        <div v-if="!stats.by_category.length" class="empty-hint">暂无数据</div>
        <div v-else class="category-list">
          <div
            v-for="(row, idx) in categoryWithPct"
            :key="row.category"
            class="category-row"
          >
            <span
              class="category-dot"
              :style="{ background: categoryColor(idx) }"
            />
            <span class="category-name">{{ row.label }}</span>
            <div class="category-track">
              <div
                class="category-fill"
                :style="{
                  width: row.pct + '%',
                  background: categoryColor(idx)
                }"
              />
            </div>
            <span class="category-num">{{ row.count }}</span>
          </div>
        </div>
      </section>
    </div>

    <section class="ios-panel filters-panel">
      <div class="filters-row">
        <el-input
          v-model="filters.q"
          class="ios-input"
          clearable
          placeholder="搜索摘要、RJ、路径、任务 ID"
          @clear="applyFilters"
          @keyup.enter="applyFilters"
        />
        <el-select
          v-model="filters.category"
          class="ios-select filter-select"
          clearable
          placeholder="分类"
          @change="applyFilters"
        >
          <el-option
            v-for="opt in categoryOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-select
          v-model="filters.status"
          class="ios-select filter-select"
          clearable
          placeholder="状态"
          @change="applyFilters"
        >
          <el-option value="success" label="成功" />
          <el-option value="partial_success" label="部分成功" />
          <el-option value="failed" label="失败" />
          <el-option value="cancelled" label="已取消" />
          <el-option value="waiting" label="等待中" />
          <el-option value="incomplete" label="未完成" />
        </el-select>
        <el-button class="ios-btn primary" @click="applyFilters">筛选</el-button>
      </div>
    </section>

    <section class="ios-panel table-panel">
      <el-table
        :data="items"
        v-loading="loading"
        class="ios-table"
        stripe
        size="small"
        empty-text="暂无记录"
        :row-class-name="rowClassName"
        table-layout="fixed"
        row-key="id"
        highlight-current-row
        @row-click="openDetail"
      >
        <el-table-column prop="created_at" label="时间" width="168">
          <template #default="{ row }">
            <span class="cell-time">{{ formatDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="category_label" label="分类" width="212">
          <template #default="{ row }">
            <span class="category-cell-wrap">
              <span :class="['cell-pill', categoryClass(row.category)]">{{ row.category_label }}</span>
              <span v-for="tag in mergedCategoryTags(row)" :key="`${row.id}-${tag}`" class="action-pill">{{ tag }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="126">
          <template #default="{ row }">
            <div class="status-cell">
              <span :class="['status-tag', statusClass(row.status)]">{{ statusLabel(row.status) }}</span>
              <span v-if="isRerunRow(row)" class="status-fixed-pill is-rerun">重新爬取</span>
              <span v-if="isRecoveredFailure(row)" class="status-fixed-pill">已修复</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="rjcode" label="RJ" width="110">
          <template #default="{ row }">
            <span class="mono">{{ row.rjcode || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />
        <el-table-column prop="action" label="动作" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="action-wrap">
              <span :class="['action-text', actionClass(row)]">{{ humanAction(row) }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="source_path" label="源路径" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono truncate">{{ compactPath(row.source_path) }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager-wrap">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="limit"
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          :page-sizes="[30, 50, 100]"
          background
          class="ios-pager"
          @current-change="loadList"
          @size-change="onPageSizeChange"
        />
      </div>
    </section>

    <el-drawer
      v-model="detailDrawerVisible"
      class="activity-detail-drawer"
      size="760px"
      destroy-on-close
      append-to-body
    >
      <template #header>
        <div class="detail-drawer-head">
          <div class="detail-drawer-title">记录详情</div>
          <div v-if="selectedRow" class="detail-drawer-subtitle">
            {{ formatDateTime(selectedRow.created_at) }} · {{ selectedRow.category_label || selectedRow.category || '—' }}
          </div>
        </div>
      </template>

      <div v-if="selectedRow" class="expand-shell drawer-shell">
        <div class="detail-topbar">
          <div class="detail-topbar-main">
            <div class="detail-topbar-title">{{ humanAction(selectedRow) }}</div>
            <div class="detail-topbar-meta">
              <span :class="['cell-pill', categoryClass(selectedRow.category)]">{{ selectedRow.category_label }}</span>
              <span v-for="tag in mergedCategoryTags(selectedRow)" :key="`drawer-${selectedRow.id}-${tag}`" class="action-pill">{{ tag }}</span>
              <span :class="['status-tag', statusClass(selectedRow.status)]">{{ statusLabel(selectedRow.status) }}</span>
              <span v-if="isRerunRow(selectedRow)" class="status-fixed-pill is-rerun">重新爬取</span>
              <span v-if="isRecoveredFailure(selectedRow)" class="status-fixed-pill">已修复</span>
            </div>
          </div>
          <div class="detail-topbar-rj mono">{{ selectedRow.rjcode || '—' }}</div>
        </div>

        <div class="expand-grid">
          <div class="expand-item">
            <div class="ek">分类</div>
            <div class="ev">{{ selectedRow.category_label }}（{{ selectedRow.category }}）</div>
          </div>
          <div class="expand-item">
            <div class="ek">状态</div>
            <div class="ev">
              <span :class="['status-tag', statusClass(selectedRow.status)]">{{ statusLabel(selectedRow.status) }}</span>
              <span v-if="isRerunRow(selectedRow)" class="status-fixed-pill is-rerun">重新爬取</span>
              <span v-if="isRecoveredFailure(selectedRow)" class="status-fixed-pill">已修复</span>
            </div>
          </div>
          <div class="expand-item">
            <div class="ek">时间</div>
            <div class="ev mono">{{ formatDateTime(selectedRow.created_at) }}</div>
          </div>
          <div class="expand-item span-2">
            <div class="ek">摘要</div>
            <div class="ev">{{ selectedRow.summary }}</div>
          </div>
          <div v-if="selectedRow.detail?.pair_summary" class="expand-item span-2">
            <div class="ek">配对结果</div>
            <div class="ev">{{ selectedRow.detail.pair_summary }}</div>
          </div>
          <div class="expand-item span-2">
            <div class="ek">源路径</div>
            <div class="ev mono break">{{ selectedRow.source_path || '—' }}</div>
          </div>
          <div class="expand-item span-2">
            <div class="ek">任务 ID</div>
            <div class="ev mono break">{{ selectedRow.task_id || '—' }}</div>
          </div>

          <div v-if="detailHighlights(selectedRow).length" class="expand-item span-2">
            <div class="ek">关键字段</div>
            <div class="kv-wrap">
              <div
                v-for="item in detailHighlights(selectedRow)"
                :key="item.k"
                class="kv-pill"
              >
                <span class="kv-k">{{ item.k }}</span>
                <span class="kv-v mono">{{ item.v }}</span>
              </div>
            </div>
          </div>

          <div v-if="filterDeleteMetricCards(selectedRow).length" class="expand-item span-2">
            <div class="ek">删除概览</div>
            <div class="metric-grid">
              <div
                v-for="item in filterDeleteMetricCards(selectedRow)"
                :key="item.k"
                class="metric-card"
              >
                <div class="metric-k">{{ item.k }}</div>
                <div class="metric-v">{{ item.v }}</div>
              </div>
            </div>
          </div>

          <div v-if="filterDeleteEntrySections(selectedRow).length" class="expand-item span-2">
            <div class="ek">删除清单</div>
            <div class="entry-section-list">
              <div
                v-for="section in filterDeleteEntrySections(selectedRow)"
                :key="section.key"
                class="entry-section"
              >
                <div class="entry-section-title">{{ section.title }}</div>
                <div class="entry-tree-box">
                  <div
                    v-for="item in section.rows"
                    :key="`${section.key}-${item.key}`"
                    class="tree-row"
                    :style="{ paddingLeft: `${12 + item.depth * 18}px` }"
                  >
                    <div class="tree-main">
                      <span class="tree-branch" aria-hidden="true">{{ item.depth ? '└' : '•' }}</span>
                      <span :class="['entry-icon', `is-${item.type || 'file'}`]">
                        <el-icon><component :is="item.type === 'dir' ? Folder : Document" /></el-icon>
                      </span>
                      <span class="entry-name">{{ item.label }}</span>
                    </div>
                    <span v-if="item.sizeText" class="entry-size">{{ item.sizeText }}</span>
                    <span v-if="item.error" class="entry-error">{{ item.error }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="prettyDetail(selectedRow)" class="code-card">
          <div class="code-card-head">
            <span class="code-card-title">原始 JSON</span>
          </div>
          <pre class="expand-json"><code>{{ prettyDetail(selectedRow) }}</code></pre>
        </div>
      </div>
    </el-drawer>

  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Document, Folder } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import api from '../api'

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(30)
const detailDrawerVisible = ref(false)
const selectedRow = ref(null)
const statsDays = ref(14)
const stats = reactive({
  days: 14,
  total_in_range: 0,
  by_day: [],
  by_category: [],
  by_status: {},
  metrics: {},
  db_path: ''
})

const filters = reactive({
  q: '',
  category: '',
  status: ''
})

const categoryOptions = [
  { value: 'subtitle_crawl', label: '字幕爬取' },
  { value: 'subtitle_pair', label: '字幕配对' },
  { value: 'subtitle_import', label: '字幕补配' },
  { value: 'extract', label: '解压' },
  { value: 'auto_import', label: '解压入库' },
  { value: 'process_existing', label: '已有目录处理' },
  { value: 'pipeline_filter', label: '筛选' },
  { value: 'pipeline_metadata', label: '元数据' },
  { value: 'pipeline_rename', label: '重命名' },
  { value: 'asmr_sync', label: 'ASMR 同步' }
]

const byDay = computed(() => stats.by_day || [])

const byDayMax = computed(() => {
  const m = Math.max(0, ...byDay.value.map((d) => d.count))
  return m || 1
})

const byDayWithPct = computed(() =>
  byDay.value.map((d) => ({
    ...d,
    pct: Math.round((d.count / byDayMax.value) * 100)
  }))
)

const catMax = computed(() => {
  const m = Math.max(0, ...stats.by_category.map((c) => c.count))
  return m || 1
})

const categoryWithPct = computed(() =>
  stats.by_category.map((c) => ({
    ...c,
    pct: Math.round((c.count / catMax.value) * 100)
  }))
)

const successRatioText = computed(() => {
  const b = stats.by_status || {}
  const ok = Number(b.success || 0)
  const partial = Number(b.partial_success || 0)
  const fail = Number(b.failed || 0)
  const c = Number(b.cancelled || 0)
  const w = Number(b.waiting || 0)
  const denom = ok + partial + fail + c + w
  if (!denom) return '—'
  return `${Math.round(((ok + partial) / denom) * 100)}%`
})

function formatGb(size) {
  const value = Number(size || 0)
  if (!value) return '0.00 GB'
  const gb = value / (1024 ** 3)
  if (gb > 0 && gb < 0.01) return '<0.01 GB'
  return `${gb.toFixed(2)} GB`
}

const statsRangeText = computed(() => {
  if (!Number(stats.days || 0)) return '所有时间'
  return `${stats.days} 天内`
})

function statsDaysLabel(days) {
  if (!Number(days || 0)) return '所有时间'
  return `${days} 天`
}

function formatCount(value) {
  return String(Number(value || 0))
}

function formatMetricHint(text) {
  return Number(stats.days || 0) ? `${stats.days} 天内${text}` : `所有时间${text}`
}

const metricCards = computed(() => {
  const m = stats.metrics || {}
  return [
    {
      key: 'subtitle_download_count',
      label: '字幕下载个数',
      value: formatCount(m.subtitle_download_count),
      hint: formatMetricHint('成功抓取到的字幕文件数'),
      accent: 'linear-gradient(135deg, #0a84ff, #5ac8fa)'
    },
    {
      key: 'subtitle_match_count',
      label: '手动配对次数',
      value: formatCount(m.subtitle_match_count),
      hint: '手动配对实际应用的组数统计',
      accent: 'linear-gradient(135deg, #5856d6, #7d7aff)'
    },
    {
      key: 'subtitle_crawl_count',
      label: '匹配 RJ 个数',
      value: formatCount(m.subtitle_crawl_count),
      hint: '成功匹配并创建抓取任务的 RJ 目录数',
      accent: 'linear-gradient(135deg, #007aff, #64b5ff)'
    },
    {
      key: 'subtitle_import_count',
      label: '补配个数',
      value: formatCount(m.subtitle_import_count),
      hint: '成功补配写入的文件数',
      accent: 'linear-gradient(135deg, #ff9500, #ffb340)'
    },
    {
      key: 'extract_count',
      label: '解压个数',
      value: formatCount(m.extract_count),
      hint: '成功完成的解压任务数',
      accent: 'linear-gradient(135deg, #34c759, #6ddc6f)'
    },
    {
      key: 'delete_count',
      label: '删除个数',
      value: formatCount(m.delete_count),
      hint: '删除过滤成功删除的项数，含部分成功记录',
      accent: 'linear-gradient(135deg, #ff3b30, #ff7b72)'
    },
    {
      key: 'delete_bytes',
      label: '删除大小',
      value: formatGb(m.delete_bytes || 0),
      hint: '按删除成功项累计，统一显示为 GB',
      accent: 'linear-gradient(135deg, #ff2d55, #ff6b88)'
    },
    {
      key: 'extract_bytes',
      label: '解压大小',
      value: formatGb(m.extract_bytes || 0),
      hint: '新产生的解压记录会持续累计',
      accent: 'linear-gradient(135deg, #00c7be, #49e0d8)'
    }
  ]
})

const palette = [
  '#007aff',
  '#34c759',
  '#ff9500',
  '#af52de',
  '#ff2d55',
  '#5ac8fa',
  '#ffcc00',
  '#8e8e93',
  '#5856d6',
  '#00c7be'
]

function categoryColor(i) {
  return palette[i % palette.length]
}

function statusLabel(s) {
  const m = {
    success: '成功',
    partial_success: '部分成功',
    failed: '失败',
    cancelled: '已取消',
    waiting: '等待',
    incomplete: '未完成'
  }
  return m[s] || s || '—'
}

function categoryClass(c) {
  switch (c) {
    case 'subtitle_crawl':
      return 'cat-subtitle-crawl'
    case 'subtitle_pair':
      return 'cat-subtitle-pair'
    case 'subtitle_import':
      return 'cat-subtitle-import'
    case 'extract':
      return 'cat-extract'
    case 'auto_import':
      return 'cat-auto-import'
    case 'process_existing':
      return 'cat-process-existing'
    case 'asmr_sync':
      return 'cat-asmr-sync'
    default:
      return 'cat-default'
  }
}

function statusClass(s) {
  return {
    'is-ok': s === 'success',
    'is-warn': s === 'partial_success' || s === 'waiting' || s === 'cancelled' || s === 'incomplete',
    'is-fail': s === 'failed',
  }
}

function isRecoveredFailure(row) {
  if (!row || row.status !== 'failed' || !row.rjcode) return false
  return items.value.some((other) => {
    if (!other || other === row) return false
    if (other.status !== 'success') return false
    if (other.category !== row.category) return false
    if (String(other.rjcode || '') !== String(row.rjcode || '')) return false
    if (!other.created_at || !row.created_at) return false
    return other.created_at > row.created_at
  })
}

function isRerunRow(row) {
  return Boolean(row?.rerun || row?.detail?.rerun_linked || Number(row?.detail?.rerun_count || 0) > 0)
}

function humanAction(row) {
  const category = row.category
  const status = row.status
  const action = row.action

  if (category === 'pipeline_filter') {
    if (hasMergedFilterDelete(row)) {
      if (status === 'success') return '删除预审完成'
      if (status === 'partial_success') return '删除预审完成'
      if (status === 'cancelled') return '删除预审完成'
      if (status === 'failed') return '删除预审完成'
      return '删除预审'
    }
    if (action === 'filter_delete_preview') {
      if (status === 'success') return '删除过滤预审完成'
      if (status === 'cancelled') return '删除过滤预审已取消'
      if (status === 'failed') return '删除过滤预审失败'
      return '删除过滤预审'
    }
    if (action === 'filter_delete_apply') {
      if (status === 'success') return '删除过滤执行完成'
      if (status === 'partial_success') return '删除过滤执行部分成功'
      if (status === 'cancelled') return '删除过滤执行已停止'
      if (status === 'failed') return '删除过滤执行失败'
      return '删除过滤执行'
    }
  }
  if (category === 'subtitle_crawl') {
    if (status === 'success') return 'RJ 字幕爬取完成'
    if (status === 'failed') return 'RJ 字幕爬取失败'
    if (status === 'waiting') return 'RJ 字幕任务等待中'
  }
  if (category === 'subtitle_pair') {
    return status === 'success' ? '字幕手动配对完成' : '字幕手动配对'
  }
  if (category === 'subtitle_import') {
    if (action === 'archive_import') return status === 'success' ? '压缩包字幕补配完成' : '压缩包字幕补配失败'
    if (action === 'folder_import') return status === 'success' ? '文件夹字幕补配完成' : '文件夹字幕补配失败'
    if (action === 'pending_execute') return status === 'success' ? '预检单字幕补配完成' : '预检单字幕补配失败'
    return '字幕补配'
  }
  if (category === 'extract') {
    return status === 'success' ? '压缩包解压完成' : '压缩包解压失败'
  }
  if (category === 'auto_import') {
    if (status === 'success') return '解压入库完成'
    if (status === 'failed') return '解压入库失败'
    if (status === 'incomplete') return '解压入库未正常结束'
  }
  if (category === 'process_existing') {
    return status === 'success' ? '已有目录处理完成' : '已有目录处理失败'
  }
  if (category === 'pipeline_filter') {
    return '作品筛选处理'
  }
  if (category === 'pipeline_metadata') {
    return '元数据整理'
  }
  if (category === 'pipeline_rename') {
    return '重命名处理'
  }
  if (category === 'asmr_sync') {
    if (status === 'success') return 'ASMR 同步下载完成'
    if (status === 'failed') return 'ASMR 同步下载失败'
  }

  // 回退：用中文状态 + 英文动作描述
  const base = statusLabel(status)
  if (!action) return base
  return `${base} · ${action}`
}

function actionClass(row) {
  if (!row) return ''
  if (row.status === 'success') return 'is-success'
  if (row.status === 'failed') return 'is-fail'
  return 'is-neutral'
}

function hasMergedPair(row) {
  return Boolean(row?.merged_pair || row?.detail?.pair_linked)
}

function hasMergedSubtitleImport(row) {
  return Boolean(row?.merged_subtitle_import || row?.detail?.import_linked)
}

function hasMergedFilterDelete(row) {
  return Boolean(row?.merged_filter_delete || row?.detail?.preview_linked)
}

function mergedSubtitleImportTag(row) {
  const status = String(row?.detail?.import_status || row?.merged_subtitle_import_status || '')
  if (status === 'success') return '字幕补配完成'
  if (status === 'failed') return '字幕补配失败'
  return '字幕补配'
}

function mergedFilterDeleteTag(row) {
  const status = String(row?.status || '')
  if (status === 'success') return '已删除'
  if (status === 'partial_success') return '部分删除'
  if (status === 'cancelled') return '已停止'
  if (status === 'failed') return '删除失败'
  return '已删除'
}

function mergedCategoryTags(row) {
  const tags = []
  if (hasMergedSubtitleImport(row)) tags.push(mergedSubtitleImportTag(row))
  if (hasMergedPair(row)) tags.push('字幕配对完成')
  if (hasMergedFilterDelete(row)) tags.push(mergedFilterDeleteTag(row))
  return tags
}

function compactPath(p) {
  if (!p) return '—'
  const s = String(p)
  if (s.length <= 60) return s
  const prefix = s.slice(0, 28)
  const suffix = s.slice(-26)
  return `${prefix}…${suffix}`
}

function rowClassName({ row }) {
  if (!row) return ''
  const cls = []
  if (row.status) cls.push(`row-status-${row.status}`)
  if (isRecoveredFailure(row)) cls.push('row-recovered')
  cls.push('activity-row')
  return cls.join(' ')
}

function openDetail(row) {
  selectedRow.value = row
  detailDrawerVisible.value = true
}

function prettyDetail(row) {
  if (!row?.detail || typeof row.detail !== 'object') return ''
  if (String(row?.detail?.mode || '').startsWith('filter_delete_')) return ''
  try {
    return JSON.stringify(row.detail, null, 2)
  } catch {
    return ''
  }
}

function detailHighlights(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  const pickKeys = [
    'downloaded_count',
    'written_files_count',
    'awaiting_manual_match',
    'output_path',
    'source_basename',
    'archive_size_bytes',
    'extract_output_bytes',
    'final_file_count',
    'record_id',
    'import_final_file_count',
    'recovered_failure_count',
    'duration_ms',
    'selected_count',
    'selected_size',
    'success_count',
    'failed_count',
    'deleted_bytes'
  ]
  const out = []
  for (const k of pickKeys) {
    if (d[k] === undefined || d[k] === null) continue
    let value = d[k]
    if (k === 'duration_ms') value = formatDurationMs(value)
    if (['selected_size', 'deleted_bytes', 'archive_size_bytes', 'extract_output_bytes'].includes(k)) value = formatBytes(value)
    out.push({ k, v: String(value) })
    if (out.length >= 10) break
  }
  return out
}

function formatBytes(size) {
  const value = Number(size || 0)
  if (Number.isNaN(value) || value < 1024) return `${Math.max(0, Math.round(value || 0))} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let current = value / 1024
  let unitIndex = 0
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024
    unitIndex += 1
  }
  return `${current.toFixed(2)} ${units[unitIndex]}`
}

function formatDurationMs(ms) {
  const value = Math.max(0, Number(ms || 0))
  if (value < 1000) return `${Math.round(value)} ms`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  const minutes = Math.floor(seconds / 60)
  const remain = Math.round(seconds % 60)
  return `${minutes} 分 ${remain} 秒`
}

function filterDeleteMetricCards(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (!String(d.mode || '').startsWith('filter_delete_')) return []
  const items = []
  if (d.duration_ms !== undefined) items.push({ k: '耗时', v: formatDurationMs(d.duration_ms) })
  if (d.selected_count !== undefined) items.push({ k: '命中/选中', v: String(d.selected_count) })
  if (d.selected_size !== undefined) items.push({ k: '预计大小', v: formatBytes(d.selected_size) })
  if (d.deleted_bytes !== undefined) items.push({ k: '实际删除', v: formatBytes(d.deleted_bytes) })
  if (d.success_count !== undefined) items.push({ k: '成功', v: String(d.success_count) })
  if (d.failed_count !== undefined) items.push({ k: '失败', v: String(d.failed_count) })
  if (d.scanned_entries !== undefined) items.push({ k: '扫描数', v: String(d.scanned_entries) })
  if (d.rule_count !== undefined) items.push({ k: '规则数', v: String(d.rule_count) })
  return items.slice(0, 8)
}

function mapFilterDeleteItems(items) {
  if (!Array.isArray(items)) return []
  return items.slice(0, 120).map((item) => ({
    key: item?.relative_path || item?.path || item?.name || '',
    path: item?.path || '',
    relative_path: item?.relative_path || '',
    name: item?.name || '',
    type: item?.type || 'file',
    sizeText: item?.size !== undefined && item?.size !== null ? formatBytes(item.size) : '',
    error: item?.error || ''
  }))
}

function buildFilterDeleteTreeRows(items) {
  const roots = []
  const nodeMap = new Map()

  const ensureNode = (key, label, type, parentKey = '') => {
    if (nodeMap.has(key)) return nodeMap.get(key)
    const node = {
      key,
      label,
      type,
      sizeText: '',
      error: '',
      children: []
    }
    nodeMap.set(key, node)
    if (parentKey && nodeMap.has(parentKey)) nodeMap.get(parentKey).children.push(node)
    else roots.push(node)
    return node
  }

  for (const item of items) {
    const rawPath = String(item.relative_path || item.name || item.path || '').replace(/^\/+|\/+$/g, '')
    if (!rawPath) continue
    const parts = rawPath.split('/').filter(Boolean)
    let parentKey = ''
    let joined = ''
    parts.forEach((part, index) => {
      joined = joined ? `${joined}/${part}` : part
      const isLeaf = index === parts.length - 1
      const node = ensureNode(joined, part, isLeaf ? item.type : 'dir', parentKey)
      if (isLeaf) {
        node.type = item.type
        node.sizeText = item.sizeText || ''
        node.error = item.error || ''
      }
      parentKey = joined
    })
  }

  const rows = []
  const walk = (nodes, depth = 0) => {
    const sorted = [...nodes].sort((a, b) => {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
      return a.label.localeCompare(b.label, 'zh-Hans-CN-u-kn-true')
    })
    for (const node of sorted) {
      rows.push({
        key: node.key,
        label: node.label,
        type: node.type,
        sizeText: node.sizeText,
        error: node.error,
        depth
      })
      if (node.children.length) walk(node.children, depth + 1)
    }
  }

  walk(roots)
  return rows
}

function filterDeleteEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  const sections = []
  if (Array.isArray(d.items) && d.items.length) {
    const items = mapFilterDeleteItems(d.items)
    sections.push({ key: 'preview-items', title: `预审命中项（${d.item_total_count || d.items.length}）`, rows: buildFilterDeleteTreeRows(items) })
  }
  if (Array.isArray(d.succeeded_items) && d.succeeded_items.length) {
    const items = mapFilterDeleteItems(d.succeeded_items)
    sections.push({ key: 'success-items', title: `已删除项（${d.success_count || d.succeeded_items.length}）`, rows: buildFilterDeleteTreeRows(items) })
  }
  if (Array.isArray(d.failed_items) && d.failed_items.length) {
    const items = mapFilterDeleteItems(d.failed_items)
    sections.push({ key: 'failed-items', title: `失败项（${d.failed_count || d.failed_items.length}）`, rows: buildFilterDeleteTreeRows(items) })
  }
  return sections
}

function formatDateTime(iso) {
  if (!iso) return '—'
  return dayjs(iso).format('YYYY-MM-DD HH:mm')
}

function formatShortDate(d) {
  if (!d) return ''
  return dayjs(d).format('MM-DD')
}

async function loadStats() {
  const data = await api.activityLog.stats({ days: statsDays.value })
  stats.days = data.days
  stats.total_in_range = data.total_in_range || 0
  stats.by_day = data.by_day || []
  stats.by_category = data.by_category || []
  stats.by_status = data.by_status || {}
  stats.metrics = data.metrics || {}
  stats.db_path = data.db_path || ''
}

async function loadList() {
  loading.value = true
  try {
    const data = await api.activityLog.list({
      page: page.value,
      limit: limit.value,
      category: filters.category || undefined,
      status: filters.status || undefined,
      q: filters.q.trim() || undefined
    })
    items.value = data.items || []
    total.value = data.total || 0
    if (selectedRow.value) {
      const nextSelected = items.value.find((item) => String(item.id) === String(selectedRow.value.id))
      if (nextSelected) selectedRow.value = nextSelected
      else detailDrawerVisible.value = false
    }
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  await Promise.all([loadStats(), loadList()])
}

function applyFilters() {
  page.value = 1
  loadList()
}

function onPageSizeChange() {
  page.value = 1
  loadList()
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.activity-page {
  max-width: 1560px;
  margin: 0 auto;
  padding: 8px 16px 40px;
  font-family:
    -apple-system,
    BlinkMacSystemFont,
    'SF Pro Text',
    'Segoe UI',
    Roboto,
    'Helvetica Neue',
    Arial,
    sans-serif;
  color: #1d1d1f;
}

.activity-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.hero-title {
  margin: 0 0 6px;
  font-size: 28px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: #1d1d1f;
}

.hero-desc {
  margin: 0;
  font-size: 15px;
  line-height: 1.5;
  color: rgba(29, 29, 31, 0.55);
  max-width: 720px;
}

.db-path {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.42);
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.hero-actions {
  flex-shrink: 0;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.meta-board {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.meta-card {
  position: relative;
  overflow: hidden;
  padding: 16px 18px;
  border-radius: 20px;
  background:
    radial-gradient(circle at top right, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.82)),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(246, 247, 251, 0.94));
  border: 1px solid rgba(29, 29, 31, 0.06);
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.04),
    0 14px 34px rgba(15, 23, 42, 0.06);
}

.meta-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}

.meta-card-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(29, 29, 31, 0.52);
}

.meta-card-accent {
  width: 38px;
  height: 8px;
  border-radius: 999px;
  flex: 0 0 auto;
}

.meta-card-value {
  font-size: 30px;
  line-height: 1;
  font-weight: 700;
  letter-spacing: -0.04em;
  color: #111827;
  margin-bottom: 10px;
}

.meta-card-hint {
  font-size: 12px;
  line-height: 1.45;
  color: rgba(29, 29, 31, 0.5);
}

.stat-card {
  background: #ffffff;
  border-radius: 18px;
  padding: 16px 18px;
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.04),
    0 8px 24px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(29, 29, 31, 0.06);
}

.stat-card-control {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
}

.stat-label {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: rgba(29, 29, 31, 0.45);
  margin-bottom: 6px;
}

.stat-value {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.stat-hint {
  margin-top: 6px;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.42);
}

.charts-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 16px;
}

.ios-panel {
  background: #ffffff;
  border-radius: 20px;
  padding: 18px 20px;
  border: 1px solid rgba(29, 29, 31, 0.06);
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.04),
    0 8px 24px rgba(0, 0, 0, 0.06);
}

.panel-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 14px;
}

.panel-title {
  font-size: 17px;
  font-weight: 600;
}

.panel-caption {
  font-size: 13px;
  color: rgba(29, 29, 31, 0.45);
}

.empty-hint {
  font-size: 14px;
  color: rgba(29, 29, 31, 0.4);
  padding: 12px 0;
}

.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.bar-item {
  display: grid;
  grid-template-columns: 52px 1fr 36px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.bar-label {
  color: rgba(29, 29, 31, 0.5);
}

.bar-track {
  height: 8px;
  border-radius: 999px;
  background: #f2f2f7;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #0a84ff, #64b5ff);
  transition: width 0.35s ease;
}

.bar-count {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: #1d1d1f;
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.category-row {
  display: grid;
  grid-template-columns: 10px 1fr 2fr 40px;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.category-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.category-name {
  color: #1d1d1f;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.category-track {
  height: 8px;
  border-radius: 999px;
  background: #f2f2f7;
  overflow: hidden;
}

.category-fill {
  height: 100%;
  border-radius: 999px;
  opacity: 0.9;
  transition: width 0.35s ease;
}

.category-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.filters-panel {
  margin-bottom: 14px;
}

.filters-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.filter-select {
  width: 140px;
}

.table-panel {
  padding-bottom: 8px;
  overflow-x: hidden;
}

.pager-wrap {
  display: flex;
  justify-content: flex-end;
  padding: 12px 4px 4px;
}

.cell-time {
  font-variant-numeric: tabular-nums;
  color: rgba(29, 29, 31, 0.65);
  font-size: 13px;
}

.cell-pill {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  background: #f2f2f7;
  font-size: 12px;
  font-weight: 500;
  color: #1d1d1f;
}

.cat-subtitle-crawl {
  background: rgba(10, 132, 255, 0.08);
  color: #0a84ff;
}

.cat-subtitle-pair {
  background: rgba(88, 86, 214, 0.08);
  color: #5856d6;
}

.cat-subtitle-import {
  background: rgba(255, 149, 0, 0.08);
  color: #ff9500;
}

.cat-extract {
  background: rgba(52, 199, 89, 0.08);
  color: #34c759;
}

.cat-auto-import {
  background: rgba(48, 209, 88, 0.08);
  color: #30d158;
}

.cat-process-existing {
  background: rgba(142, 142, 147, 0.08);
  color: #8e8e93;
}

.cat-asmr-sync {
  background: rgba(94, 92, 230, 0.08);
  color: #5e5ce6;
}

.cat-default {
  background: #f2f2f7;
  color: #1d1d1f;
}

.status-tag {
  font-size: 12px;
  font-weight: 600;
}

.status-tag.is-ok {
  color: #248a3d;
}

.status-tag.is-fail {
  color: #d70015;
}

.status-tag.is-warn {
  color: #b35c00;
}

.status-cell {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.status-fixed-pill {
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(52, 199, 89, 0.1);
  color: #248a3d;
  font-size: 10px;
  font-weight: 500;
  transform: translateY(-4px);
}

.status-fixed-pill.is-rerun {
  background: rgba(255, 159, 10, 0.16);
  color: #c56a00;
}

.action-text {
  display: inline-block;
  white-space: nowrap;
  font-weight: 600;
}

.action-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.category-cell-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.action-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(52, 199, 89, 0.12);
  color: #248a3d;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.action-text.is-success {
  color: #248a3d;
}

.action-text.is-fail {
  color: #d70015;
}

.action-text.is-neutral {
  color: #4b5563;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.truncate {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.break {
  word-break: break-all;
}

.detail-body {
  font-size: 14px;
}

.detail-kv {
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 8px;
  margin-bottom: 10px;
  align-items: start;
}

.detail-kv.block {
  grid-template-columns: 1fr;
}

.detail-kv .k {
  color: rgba(29, 29, 31, 0.45);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.detail-kv .v {
  color: #1d1d1f;
  line-height: 1.45;
}

.detail-json {
  margin: 12px 0 0;
  padding: 12px;
  border-radius: 12px;
  background: #f2f2f7;
  font-size: 12px;
  overflow: auto;
  max-height: 240px;
}

.ios-btn {
  border-radius: 999px;
  padding: 10px 20px;
  font-weight: 600;
  border: none;
}

.ios-btn.primary {
  background: #007aff;
  color: #fff;
}

.ios-btn.secondary {
  background: #f2f2f7;
  color: #1d1d1f;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.08);
}

:deep(.ios-input .el-input__wrapper) {
  border-radius: 14px;
  background: #f2f2f7;
  box-shadow: none;
  padding: 4px 14px;
}

:deep(.ios-select .el-select__wrapper) {
  border-radius: 14px;
  background: #f2f2f7;
  box-shadow: none;
}

:deep(.ios-table) {
  background: transparent;
  --el-table-border-color: rgba(29, 29, 31, 0.06);
  --el-table-header-bg-color: #fafafa;
  --el-fill-color-lighter: #fbfbfc;
  border-radius: 16px;
  overflow: hidden;
  width: 100%;
}

:deep(.ios-table .el-table__body tr) {
  transition: background-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
  cursor: pointer;
}

:deep(.ios-table .el-table__body tr:hover) {
  background: #f3f4f7;
}

:deep(.ios-table .el-table__body tr:hover > td) {
  background: transparent;
}

:deep(.ios-table .el-table__body tr:hover .cell-time) {
  color: rgba(29, 29, 31, 0.82);
}

:deep(.ios-table .el-table__body tr:hover .cell-pill) {
  background: #e9ecf2;
}

:deep(.ios-table .el-table__body td) {
  padding-top: 6px;
  padding-bottom: 6px;
}

:deep(.ios-table .cell) {
  min-width: 0;
}

:deep(.ios-table .el-table__inner-wrapper::before) {
  display: none;
}

:deep(.ios-table .el-scrollbar__bar.is-horizontal) {
  display: none;
}

.expand-shell {
  padding: 18px;
  background:
    radial-gradient(circle at top right, rgba(255, 255, 255, 0.96), rgba(248, 250, 255, 0.9)),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(245, 248, 252, 0.95));
  border-radius: 22px;
  border: 1px solid rgba(29, 29, 31, 0.06);
  box-shadow:
    0 1px 2px rgba(0, 0, 0, 0.04),
    0 12px 30px rgba(15, 23, 42, 0.06);
  overflow-x: hidden;
}

.drawer-shell {
  margin: 0 4px 20px;
}

.detail-topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.08);
}

.detail-topbar-main {
  min-width: 0;
}

.detail-topbar-title {
  font-size: 20px;
  line-height: 1.2;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 10px;
}

.detail-topbar-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.detail-topbar-rj {
  flex: 0 0 auto;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(0, 122, 255, 0.08);
  color: #005fcc;
  font-size: 13px;
  font-weight: 700;
}

.expand-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
}

.expand-item {
  min-width: 0;
  padding: 14px 15px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.05);
}

.expand-item .ek {
  font-size: 11px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.45);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.expand-item .ev {
  font-size: 13px;
  line-height: 1.45;
  color: #1d1d1f;
  min-width: 0;
  white-space: normal;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.expand-item.span-2 {
  grid-column: 1 / -1;
}

.kv-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  overflow: hidden;
}

.kv-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #f2f2f7;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
  max-width: 100%;
}

.kv-k {
  font-size: 11px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.5);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.kv-v {
  color: rgba(29, 29, 31, 0.78);
  max-width: 520px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.expand-json {
  margin: 0;
  padding: 16px 18px;
  border-radius: 16px;
  background: #0f172a;
  color: #dbeafe;
  font-size: 12px;
  line-height: 1.6;
  overflow: auto;
  max-height: 360px;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.16);
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
}

.metric-card {
  padding: 10px 12px;
  border-radius: 12px;
  background: #f7f8fb;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
}

.metric-k {
  font-size: 11px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.48);
  margin-bottom: 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.metric-v {
  font-size: 14px;
  font-weight: 600;
  color: #1d1d1f;
}

.entry-section-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.entry-section-title {
  font-size: 12px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.56);
  margin-bottom: 6px;
}

.entry-tree-box {
  max-height: 360px;
  overflow: auto;
  overflow-x: hidden;
  padding: 8px;
  border-radius: 14px;
  background: #f7f8fb;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
}

.tree-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  padding-top: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.05);
}

.tree-row:last-child {
  border-bottom: none;
}

.tree-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tree-branch {
  color: rgba(29, 29, 31, 0.35);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  flex: 0 0 auto;
}

.entry-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  flex: 0 0 auto;
}

.entry-icon.is-dir {
  background: rgba(10, 132, 255, 0.12);
  color: #0a84ff;
}

.entry-icon.is-file {
  background: rgba(120, 120, 128, 0.12);
  color: #4b5563;
}

.entry-name {
  min-width: 0;
  color: #1d1d1f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.entry-size {
  color: rgba(29, 29, 31, 0.55);
  font-size: 12px;
  white-space: nowrap;
}

.entry-error {
  grid-column: 1 / -1;
  color: #d70015;
  font-size: 12px;
  word-break: break-word;
  padding-left: 56px;
}

.detail-drawer-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-drawer-title {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
}

.detail-drawer-subtitle {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.48);
}

.code-card {
  margin-top: 16px;
}

.code-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.code-card-title {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.48);
}

:deep(.ios-table th) {
  font-weight: 600;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.45);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

:deep(.ios-pager) {
  gap: 6px;
  font-size: 12px;
  --el-pagination-button-bg-color: #ffffff;
}

:deep(.ios-pager .btn-prev),
:deep(.ios-pager .btn-next),
:deep(.ios-pager .el-pager li) {
  min-width: 30px;
  height: 30px;
  line-height: 30px;
  border-radius: 10px;
  background: #f5f5f7;
}

:deep(.ios-pager .el-pager li.is-active) {
  background: #0071e3;
  color: #fff;
}

:deep(.ios-pager .el-pagination__sizes .el-select__wrapper),
:deep(.ios-pager .el-pagination__jump .el-input__wrapper) {
  min-height: 30px;
  border-radius: 10px;
  background: #f5f5f7;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
}

:deep(.ios-dialog) {
  border-radius: 20px;
}

:deep(.activity-detail-drawer) {
  --el-drawer-padding-primary: 18px;
}

:deep(.activity-detail-drawer .el-drawer__header) {
  margin-bottom: 0;
  padding-bottom: 12px;
}

:deep(.activity-detail-drawer .el-drawer__body) {
  padding-top: 8px;
  overflow-x: hidden;
  background:
    radial-gradient(circle at top, rgba(242, 248, 255, 0.78), rgba(255, 255, 255, 0.92)),
    linear-gradient(180deg, #f8fafc, #ffffff);
}

@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .meta-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .charts-row {
    grid-template-columns: 1fr;
  }

  .activity-hero {
    flex-direction: column;
  }
}
</style>
