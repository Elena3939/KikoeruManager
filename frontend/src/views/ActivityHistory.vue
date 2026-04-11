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
        :data="displayItems"
        v-loading="loading"
        class="ios-table"
        stripe
        size="small"
        empty-text="暂无记录"
        :row-class-name="rowClassName"
        table-layout="fixed"
        row-key="id"
        @row-click="openDetail"
      >
        <el-table-column prop="created_at" label="时间" width="168">
          <template #default="{ row }">
            <span class="time-cell-wrap" :style="row.is_tree_child ? childIndentStyle(row, 0) : undefined">
              <button
                v-if="!row.is_tree_child && rowHasChildren(row)"
                type="button"
                class="tree-toggle-btn"
                :class="{ expanded: isTreeRowExpanded(row) }"
                @click.stop="toggleTreeRow(row)"
              >
                ▶
              </button>
              <span v-else class="tree-toggle-placeholder"></span>
              <span class="cell-time">{{ formatDateTime(displayRowTime(row)) }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="category_label" label="分类" width="212">
          <template #default="{ row }">
            <span class="category-cell-wrap">
              <template v-if="row.is_tree_child">
                <span class="tree-cell-content child-row-label" :style="childIndentStyle(row)">
                  <span class="tree-guides" :style="treeGuideStyle(row)" aria-hidden="true"></span>
                  <span :class="['child-type-dot', childTypeDotClass(row)]"></span>
                  <span>{{ childRowCategoryLabel(row) }}</span>
                </span>
              </template>
              <template v-else>
                <span :class="['cell-pill', categoryClass(row.category)]">{{ row.category_label }}</span>
              </template>
              <span
                v-for="tag in rowCategoryTags(row)"
                :key="`${row.id}-${tag}`"
                :class="['action-pill', actionTagClass(row, tag), { 'is-muted': tag === '未命中' }]"
              >{{ tag }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="126">
          <template #default="{ row }">
            <div class="status-cell">
              <span :class="['status-tag', statusClass(row.status)]">{{ statusLabel(row.status) }}</span>
              <template v-if="!row.is_tree_child">
                <span v-if="isRerunRow(row)" class="status-fixed-pill is-rerun">重新爬取</span>
                <span v-if="isFilterDeleteRetriedSuccess(row)" class="status-fixed-pill">重试✔</span>
                <span v-else-if="isFilterDeleteRetriedPartial(row)" class="status-fixed-pill is-partial">重新执行部分成功</span>
                <span v-if="finalStatusLabel(row)" :class="['status-fixed-pill', 'is-final', finalStatusClass(row)]">{{ finalStatusLabel(row) }}</span>
                <span v-if="isRecoveredFailure(row)" class="status-fixed-pill">已修复</span>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="rjcode" label="RJ" width="110">
          <template #default="{ row }">
            <span class="mono">{{ displayRjcode(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <span :class="['tree-cell-content', { 'child-summary': row.is_tree_child }]" :style="row.is_tree_child ? childIndentStyle(row) : undefined">
              <span class="tree-guides" v-if="row.is_tree_child" :style="treeGuideStyle(row)" aria-hidden="true"></span>
              <span>{{ displaySummary(row) }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="action" label="动作" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="action-wrap" :class="{ 'child-action-wrap': row.is_tree_child }" :style="row.is_tree_child ? childIndentStyle(row) : undefined">
              <span class="tree-guides" v-if="row.is_tree_child" :style="treeGuideStyle(row)" aria-hidden="true"></span>
              <span v-if="row.is_tree_child" :class="['child-type-dot', childTypeDotClass(row)]"></span>
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
              <span
                v-for="tag in rowCategoryTags(selectedRow)"
                :key="`drawer-${selectedRow.id}-${tag}`"
                :class="['action-pill', actionTagClass(selectedRow, tag), { 'is-muted': tag === '未命中' }]"
              >{{ tag }}</span>
              <span :class="['status-tag', statusClass(selectedRow.status)]">{{ statusLabel(selectedRow.status) }}</span>
              <span v-if="isRerunRow(selectedRow)" class="status-fixed-pill is-rerun">重新爬取</span>
              <span v-if="isFilterDeleteRetriedSuccess(selectedRow)" class="status-fixed-pill">重试✔</span>
              <span v-else-if="isFilterDeleteRetriedPartial(selectedRow)" class="status-fixed-pill is-partial">重新执行部分成功</span>
              <span v-if="isRecoveredFailure(selectedRow)" class="status-fixed-pill">已修复</span>
            </div>
          </div>
          <div class="detail-topbar-rj mono">{{ displayRjcode(selectedRow) }}</div>
        </div>

        <div v-if="pathCompareModel(selectedRow)" class="path-compare-card" :class="[`is-${pathCompareModel(selectedRow).kind}`, `is-status-${pathCompareReasonClass(selectedRow)}`]">
          <div class="path-compare-head">
            <span class="path-compare-title">{{ pathCompareModel(selectedRow).title }}</span>
            <div class="path-compare-head-right">
              <span
                v-if="pathCompareModel(selectedRow).opTag"
                :class="['path-op-tag', pathCompareModel(selectedRow).opTagClass]"
              >{{ pathCompareModel(selectedRow).opTag }}</span>
              <span :class="['path-compare-status', pathCompareReasonClass(selectedRow)]">{{ statusLabel(selectedRow.status) }}</span>
            </div>
          </div>
          <div class="path-compare-body">
            <div class="path-compare-col old">
              <div class="path-compare-label">OLD PATH</div>
              <div class="path-compare-path mono break">{{ pathCompareModel(selectedRow).beforePath || '—' }}</div>
            </div>
            <div class="path-compare-arrow">→</div>
            <div class="path-compare-col new">
              <div class="path-compare-label">NEW PATH</div>
              <div class="path-compare-path mono break">{{ pathCompareModel(selectedRow).afterPath || '—' }}</div>
            </div>
          </div>
          <div
            class="path-compare-reason"
            :class="[pathCompareReasonClass(selectedRow), { 'is-empty': !pathCompareModel(selectedRow).reason }]"
          >
            {{ pathCompareModel(selectedRow).reason || pathCompareDefaultReason(selectedRow) }}
          </div>
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
              <span v-if="isFilterDeleteRetriedSuccess(selectedRow)" class="status-fixed-pill">重试✔</span>
              <span v-else-if="isFilterDeleteRetriedPartial(selectedRow)" class="status-fixed-pill is-partial">重新执行部分成功</span>
              <span v-if="isRecoveredFailure(selectedRow)" class="status-fixed-pill">已修复</span>
            </div>
          </div>
          <div class="expand-item">
            <div class="ek">时间</div>
            <div class="ev mono">{{ formatDateTime(selectedRow.created_at) }}</div>
          </div>
          <div class="expand-item span-2">
            <div class="ek">摘要</div>
            <div class="ev">{{ displaySummary(selectedRow) }}</div>
          </div>
          <div v-if="pairSummaryText(selectedRow)" class="expand-item span-2">
            <div class="ek">配对结果</div>
            <div class="ev">{{ pairSummaryText(selectedRow) }}</div>
          </div>
          <div v-if="pairChangeRows(selectedRow).length" class="expand-item span-2">
            <div class="ek">配对重命名</div>
            <div class="pair-change-table">
              <div class="pair-change-row pair-change-head">
                <span>音频</span>
                <span>字幕</span>
              </div>
              <div
                v-for="(item, index) in pairChangeRows(selectedRow)"
                :key="`${index}-${item.audio_before}`"
                class="pair-change-row"
              >
                <span class="pair-change-cell mono">{{ item.audio_before }} → {{ item.audio_after }}</span>
                <span class="pair-change-cell mono">{{ item.subtitle_before }} → {{ item.subtitle_after }}</span>
              </div>
            </div>
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

          <div v-if="activityEntrySections(selectedRow).length" class="expand-item span-2">
            <div class="ek">{{ activityEntrySectionTitle(selectedRow) }}</div>
            <div class="entry-section-list">
              <div
                v-for="section in activityEntrySections(selectedRow)"
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
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
const expandedTreeRowIds = ref(new Set())
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
  { value: 'pipeline_delete', label: '删除' },
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

const displayItems = computed(() => {
  const rows = []
  for (const row of items.value) {
    rows.push(row)
    rows.push(...buildChildDisplayRows(row))
  }
  return rows
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
    case 'pipeline_delete':
      return 'cat-pipeline-delete'
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

function filterDeleteRetryStatus(row) {
  return String(row?.detail?.retry_status || '').trim()
}

function isFilterDeleteRetriedSuccess(row) {
  return filterDeleteRetryStatus(row) === 'success'
}

function isFilterDeleteRetriedPartial(row) {
  return filterDeleteRetryStatus(row) === 'partial_success'
}

function hasFilterDeleteRetryChild(row) {
  return Boolean(row?.merged_filter_retry || row?.detail?.retry_linked)
}

function isApiRenameAction(row) {
  const action = String(row?.action || '').trim()
  return action === 'api_rename' || action === 'batch_api_rename' || action === 'batch_api_rename_item'
}

function isManualRenameAction(row) {
  const action = String(row?.action || '').trim()
  if (!action) return false
  return action === 'rename' || action === 'manual_rename' || action === 'batch_rename_item'
}

function renameOpTag(row) {
  if (isApiRenameAction(row)) return 'API重命名'
  if (isManualRenameAction(row)) return '重命名'
  return '重命名'
}

function renameOpTagClass(row) {
  if (isApiRenameAction(row)) return 'is-api-rename'
  if (isManualRenameAction(row)) return 'is-manual-rename'
  return 'is-rename'
}

function humanAction(row) {
  if (row?.is_tree_child) {
    if (row.relation === 'rerun') {
      if (row.status === 'success') return '重试完成'
      if (row.status === 'failed') return '重试失败'
      return '重试'
    }
    if (row.relation === 'subtitle_import') {
      if (row.status === 'success') return '字幕补配完成'
      if (row.status === 'failed') return '字幕补配失败'
      return '字幕补配'
    }
    if (row.relation === 'pair') {
      return row.status === 'success' ? '字幕手动配对完成' : '字幕手动配对'
    }
    if (row.relation === 'delete_apply') {
      if (row.status === 'success') return '删除执行完成'
      if (row.status === 'partial_success') return '删除执行部分成功'
      if (row.status === 'cancelled') return '删除执行已停止'
      if (row.status === 'failed') return '删除执行失败'
      return '删除执行'
    }
    if (row.action === 'filter_delete_preview_retry') {
      if (row.status === 'success') return '失败项重试成功'
      if (row.status === 'partial_success') return '失败项重试部分成功'
      if (row.status === 'failed') return '失败项重试失败'
      return '失败项重试'
    }
  }
  const category = row.category
  const status = row.status
  const action = row.action

  if (category === 'pipeline_filter') {
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
    if (action === 'filter_delete_preview_retry') {
      if (status === 'success') return '删除过滤失败项重试完成'
      if (status === 'partial_success') return '删除过滤失败项重试部分成功'
      if (status === 'failed') return '删除过滤失败项重试失败'
      return '删除过滤失败项重试'
    }
  }
  if (category === 'subtitle_crawl') {
    if (action === 'batch_start') {
      if (status === 'success') return '批量字幕任务创建完成'
      if (status === 'partial_success') return '批量字幕任务创建部分成功'
      if (status === 'failed') return '批量字幕任务创建失败'
      return '批量字幕任务创建'
    }
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
    if (action === 'batch_api_rename') {
      if (status === 'success') return '批量 API 重命名完成'
      if (status === 'partial_success') return '批量 API 重命名部分成功'
      if (status === 'failed') return '批量 API 重命名失败'
      return '批量 API 重命名'
    }
    if (isApiRenameAction(row)) {
      if (status === 'success') return 'API重命名完成'
      if (status === 'failed') return 'API重命名失败'
      return 'API重命名'
    }
    if (isManualRenameAction(row)) {
      if (status === 'success') return '重命名完成'
      if (status === 'failed') return '重命名失败'
      return '重命名'
    }
    return '重命名处理'
  }
  if (category === 'pipeline_delete') {
    if (action === 'batch_api_delete') {
      if (status === 'success') return '批量删除完成'
      if (status === 'partial_success') return '批量删除部分成功'
      if (status === 'failed') return '批量删除失败'
      return '批量删除'
    }
    if (action === 'delete' || action === 'batch_delete_item') {
      if (status === 'success') return '删除完成'
      if (status === 'failed') return '删除失败'
      return '删除'
    }
    return '删除处理'
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

function hasChildRelation(row, relation) {
  return collectChildRowsFromParent(row).some((child) => child?.relation === relation)
}

function hasMergedFilterDelete(row) {
  return Boolean(row?.merged_filter_delete || row?.detail?.preview_linked)
}

function isBatchChildCrawlRow(row) {
  if (!row || !row.is_tree_child) return false
  if (row.category !== 'subtitle_crawl' || row.action === 'batch_start') return false
  return row?.parent_row?.category === 'subtitle_crawl' && row?.parent_row?.action === 'batch_start'
}

function collectDescendantRows(row) {
  const rows = []
  const walk = (node) => {
    for (const child of collectChildRowsFromParent(node)) {
      rows.push(child)
      walk(child)
    }
  }
  walk(row)
  return rows
}

function latestPairRow(row) {
  const pairRows = collectDescendantRows(row)
    .filter((item) => item?.relation === 'pair' || item?.category === 'subtitle_pair')
    .sort((left, right) => String(left.created_at || '').localeCompare(String(right.created_at || '')))
  return pairRows.at(-1) || null
}

function isBatchChildPaired(row) {
  if (!isBatchChildCrawlRow(row)) return false
  const pairRow = latestPairRow(row)
  return Boolean(pairRow && pairRow.status === 'success')
}

function pairSummaryText(row) {
  if (!row) return ''
  const detailSummary = String(row?.detail?.pair_summary || '').trim()
  if (detailSummary) return detailSummary
  const pairRow = latestPairRow(row)
  return String(pairRow?.summary || '').trim()
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

function isSubtitleBatchMiss(row) {
  if (!row || row.category !== 'subtitle_crawl' || row.action !== 'batch_start') return false
  const recognizedCount = Number(row?.detail?.recognized_rj_count || 0)
  const createdCount = Number(row?.detail?.created_count || 0)
  const skippedTotal = Number(row?.detail?.skipped_total || 0)
  const hitCount = Math.max(recognizedCount, createdCount + skippedTotal)
  return hitCount <= 0
}

function mergedCategoryTags(row) {
  const tags = []
  if (hasMergedSubtitleImport(row) && !hasChildRelation(row, 'subtitle_import')) tags.push(mergedSubtitleImportTag(row))
  if (isSubtitleBatchMiss(row)) tags.push('未命中')
  if (hasFilterDeleteRetryChild(row)) tags.push('附带重试')
  if (isFilterDeleteRetriedSuccess(row)) tags.push('重试✔')
  else if (isFilterDeleteRetriedPartial(row)) tags.push('重新执行部分成功')
  return tags
}

function rowCategoryTags(row) {
  const tags = row?.is_tree_child ? [] : mergedCategoryTags(row)
  if (row?.category === 'pipeline_rename') tags.unshift(renameOpTag(row))
  if (isBatchChildPaired(row)) tags.push('已配对')
  return tags
}

function subtitleImportSourceSuffix(row) {
  const detail = row?.detail
  const sourceRj = String(
    detail?.source_rjcode ||
    detail?.preview_source_rjcode ||
    ''
  ).trim().toUpperCase()
  if (!sourceRj) return ''
  return `，来源于 ${sourceRj}`
}

function displaySummary(row) {
  if (isBatchChildPaired(row)) return pairSummaryText(row) || row?.summary || '—'
  if (row?.category === 'subtitle_import' || row?.relation === 'subtitle_import') {
    const base = String(row?.summary || '—').trim() || '—'
    const suffix = subtitleImportSourceSuffix(row)
    if (suffix && !base.includes(`来源于 ${String(row?.detail?.source_rjcode || row?.detail?.preview_source_rjcode || '').trim().toUpperCase()}`)) {
      return `${base}${suffix}`
    }
    return base
  }
  return row?.summary || '—'
}

function compactPath(p) {
  if (!p) return '—'
  const s = String(p)
  if (s.length <= 60) return s
  const prefix = s.slice(0, 28)
  const suffix = s.slice(-26)
  return `${prefix}…${suffix}`
}

function normalizeRjcode(value) {
  const text = String(value || '').trim().toUpperCase()
  if (!text) return ''
  const repeated = text.match(/(?:RJ)+(\d{4,})/i)
  if (repeated) return `RJ${repeated[1]}`
  const match = text.match(/RJ\d{4,}/i)
  if (match) return match[0].toUpperCase()
  return text
}

function extractRjFromText(value) {
  const text = String(value || '')
  if (!text) return ''
  const match = text.match(/RJ\d{4,}/i)
  return match ? match[0].toUpperCase() : ''
}

function inferRjcodeFromRow(row) {
  if (!row) return ''
  const detail = row.detail && typeof row.detail === 'object' ? row.detail : {}
  const candidates = [
    row.rjcode,
    detail.rjcode,
    detail.source_rjcode,
    detail.preview_source_rjcode,
    detail.target_rjcode,
    detail.old_name,
    detail.new_name,
    detail.old_path,
    detail.new_path,
    row.source_path,
    row.summary,
    row.task_id
  ]
  for (const item of candidates) {
    const byValue = normalizeRjcode(item)
    if (byValue.startsWith('RJ')) return byValue
    const byText = extractRjFromText(item)
    if (byText) return byText
  }
  return ''
}

function pairChangeRows(row) {
  const detail = row?.detail
  const changes = Array.isArray(detail?.pair_changes) ? detail.pair_changes : []
  return changes
    .map(item => ({
      audio_before: String(item?.audio_before || '').trim(),
      audio_after: String(item?.audio_after || '').trim(),
      subtitle_before: String(item?.subtitle_before || '').trim(),
      subtitle_after: String(item?.subtitle_after || '').trim()
    }))
    .filter(item => item.audio_before || item.audio_after || item.subtitle_before || item.subtitle_after)
}

function displayRjcode(row) {
  const inferred = inferRjcodeFromRow(row)
  return inferred || '—'
}

function pathCompareModel(row) {
  if (!row) return null
  const detail = row.detail && typeof row.detail === 'object' ? row.detail : {}
  const sourcePath = String(row.source_path || detail.path || '').trim()

  if (row.category === 'pipeline_rename') {
    const beforePath = String(sourcePath || detail.old_path || '').trim()
    const afterPath = String(detail.new_path || '').trim()
    const oldName = String(detail.old_name || '').trim()
    const newName = String(detail.new_name || '').trim()
    const reason = String(detail.error || detail.reason || '').trim()
    if (!beforePath && !afterPath && !oldName && !newName && !reason) return null
    return {
      kind: 'rename',
      title: '重命名前后路径对比',
      beforePath: beforePath || oldName,
      afterPath: afterPath || newName,
      reason,
      opTag: renameOpTag(row),
      opTagClass: renameOpTagClass(row)
    }
  }

  if (row.category === 'pipeline_delete') {
    const beforePath = String(sourcePath || detail.path || '').trim()
    const afterPath = row.status === 'success' ? '（已删除）' : '（删除失败，原路径保留）'
    const reason = String(detail.error || detail.reason || '').trim()
    if (!beforePath && !reason) return null
    return {
      kind: 'delete',
      title: '删除前后路径对比',
      beforePath,
      afterPath,
      reason,
      opTag: '删除',
      opTagClass: 'is-delete'
    }
  }

  return null
}

function pathCompareReasonClass(row) {
  const status = String(row?.status || '').trim()
  if (status === 'success') return 'is-success'
  if (status === 'partial_success') return 'is-warn'
  return 'is-fail'
}

function pathCompareDefaultReason(row) {
  const status = String(row?.status || '').trim()
  if (row?.category === 'pipeline_rename') {
    if (status === 'success') return '重命名成功：新路径已生效'
    if (status === 'partial_success') return '重命名部分成功：请检查失败项原因'
    return '重命名失败：原路径保持不变'
  }
  if (row?.category === 'pipeline_delete') {
    if (status === 'success') return '删除成功：目标已移除'
    if (status === 'partial_success') return '删除部分成功：请检查失败项原因'
    return '删除失败：目标仍保留在原路径'
  }
  return '执行完成'
}

function actionTagClass(row, tag) {
  if (tag === 'API重命名') return 'is-api-rename'
  if (tag === '重命名') return 'is-manual-rename'
  if (tag === '删除') return 'is-delete'
  return ''
}

function rowClassName({ row }) {
  if (!row) return ''
  const cls = []
  if (row.is_tree_child) cls.push('activity-row-child')
  if (row.status) cls.push(`row-status-${row.status}`)
  if (isRecoveredFailure(row)) cls.push('row-recovered')
  cls.push('activity-row')
  return cls.join(' ')
}

function openDetail(row) {
  selectedRow.value = row || null
  detailDrawerVisible.value = true
}

function treeRowId(row) {
  return String(row?.id || '')
}

function rowHasChildren(row) {
  if (!row) return false
  return collectChildRowsFromParent(row).length > 0
}

function isTreeRowExpanded(row) {
  return expandedTreeRowIds.value.has(treeRowId(row))
}

function toggleTreeRow(row) {
  const id = treeRowId(row)
  if (!id || !rowHasChildren(row)) return
  const next = new Set(expandedTreeRowIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedTreeRowIds.value = next
}

function buildChildDisplayRows(parentRow, children = null, depth = 1) {
  const sourceChildren = Array.isArray(children)
    ? children
    : collectChildRowsFromParent(parentRow)
  if (!isTreeRowExpanded(parentRow)) return []
  const rows = []
  for (const child of sourceChildren) {
    const childRow = {
      ...child,
      parent_id: parentRow.id,
      parent_row: parentRow,
      is_tree_child: true,
      tree_depth: depth
    }
    rows.push(childRow)
    rows.push(...buildChildDisplayRows(parentRow, child.child_rows || [], depth + 1))
  }
  return rows
}

function collectChildRowsFromParent(row) {
  const childRows = []
  const seenIds = new Set()
  const directChildren = Array.isArray(row?.child_rows) ? row.child_rows : []
  const detailChildren = Array.isArray(row?.detail?.child_rows) ? row.detail.child_rows : []
  for (const child of [...directChildren, ...detailChildren]) {
    const id = String(child?.id || '')
    if (id && seenIds.has(id)) continue
    if (id) seenIds.add(id)
    childRows.push(child)
  }
  return childRows.sort((left, right) => String(left.created_at || '').localeCompare(String(right.created_at || '')))
}

function childRowCategoryLabel(row) {
  if (row?.relation === 'rerun') return '重试'
  if (row?.relation === 'subtitle_import') return '字幕补配'
  if (row?.relation === 'rename_item') return '子重命名'
  if (row?.relation === 'delete_item') return '子删除'
  if (row?.relation === 'pair') return '字幕配对'
  if (row?.relation === 'delete_apply') return '删除执行'
  if (row?.relation === 'retry_preview') return '失败重试'
  if (row?.action === 'filter_delete_preview_retry') return '失败重试'
  return row?.category_label || row?.category || '子任务'
}

function childIndentStyle(row) {
  return {}
}

function treeGuideStyle(row) {
  const depth = Math.max(1, Number(row?.tree_depth || 1))
  return {
    '--tree-depth': depth
  }
}

function collectDescendantStatuses(row) {
  const statuses = []
  const walk = (nodes = []) => {
    for (const node of nodes) {
      statuses.push(String(node?.status || ''))
      if (Array.isArray(node?.child_rows) && node.child_rows.length) {
        walk(node.child_rows)
      }
    }
  }
  walk(collectChildRowsFromParent(row))
  return statuses
}

function finalStatusLabel(row) {
  if (!row || row.is_tree_child || !rowHasChildren(row)) return ''
  const statuses = [String(row.status || ''), ...collectDescendantStatuses(row)]
  if (statuses[0] === 'failed' && (statuses.includes('success') || statuses.includes('partial_success'))) return '已修复'
  if (statuses.includes('failed') && !statuses.includes('success') && !statuses.includes('partial_success')) return '异常'
  if (!statuses.includes('waiting')) return '终了'
  return ''
}

function finalStatusClass(row) {
  const label = finalStatusLabel(row)
  if (label === '已修复') return 'is-final-success'
  if (label === '终了') return 'is-final-success'
  if (label.includes('部分')) return 'is-final-partial'
  return 'is-final-failed'
}

function childTypeDotClass(row) {
  if (row?.relation === 'rerun') return 'is-rerun'
  if (row?.relation === 'subtitle_import') return 'is-subtitle-import'
  if (row?.relation === 'rename_item') return 'is-rename-item'
  if (row?.relation === 'delete_item') return 'is-delete-item'
  if (row?.relation === 'pair') return 'is-pair'
  if (row?.relation === 'delete_apply') return 'is-delete-apply'
  if (row?.category === 'subtitle_crawl') return 'is-crawl'
  if (row?.relation === 'retry_preview') return 'is-filter-retry'
  if (row?.action === 'filter_delete_preview_retry') return 'is-filter-retry'
  return 'is-default'
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
    'rjcode',
    'source_rjcode',
    'target_rjcode',
    'linked_source_rjcode',
    'linked_target_rjcode',
    'downloaded_count',
    'written_files_count',
    'awaiting_manual_match',
    'output_path',
    'source_basename',
    'archive_size_bytes',
    'extract_output_bytes',
    'filtered_count',
    'filtered_size',
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
    , 'retry_target_count'
    , 'retry_success_count'
    , 'retry_failed_count'
    , 'retry_recovered_item_count'
    , 'recovered_item_count'
    , 'recovered_selected_size'
    , 'scan_directory_count'
    , 'recognized_rj_count'
    , 'created_count'
    , 'skipped_total'
    , 'skipped_existing'
    , 'skipped_duplicate'
    , 'skipped_no_subtitle'
  ]
  const out = []
  for (const k of pickKeys) {
    if (d[k] === undefined || d[k] === null) continue
    let value = d[k]
    if (k === 'duration_ms') value = formatDurationMs(value)
    if (['selected_size', 'deleted_bytes', 'archive_size_bytes', 'extract_output_bytes', 'recovered_selected_size', 'filtered_size'].includes(k)) value = formatBytes(value)
    if (k.includes('rjcode')) value = normalizeRjcode(value)
    if (!String(value || '').trim()) continue
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
  if (d.retry_target_count !== undefined) items.push({ k: '重试目录', v: String(d.retry_target_count) })
  if (d.retry_success_count !== undefined) items.push({ k: '重试成功', v: String(d.retry_success_count) })
  if (d.retry_failed_count !== undefined) items.push({ k: '重试失败', v: String(d.retry_failed_count) })
  if (d.recovered_item_count !== undefined) items.push({ k: '补回项数', v: String(d.recovered_item_count) })
  if (d.recovered_selected_size !== undefined) items.push({ k: '补回大小', v: formatBytes(d.recovered_selected_size) })
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
  if (Array.isArray(d.retry_targets) && d.retry_targets.length) {
    const items = mapFilterDeleteItems(d.retry_targets)
    sections.push({ key: 'retry-targets', title: `重试目录（${d.retry_target_count || d.retry_targets.length}）`, rows: buildFilterDeleteTreeRows(items) })
  }
  if (Array.isArray(d.recovered_items) && d.recovered_items.length) {
    const items = mapFilterDeleteItems(d.recovered_items)
    sections.push({ key: 'recovered-items', title: `重试补回项（${d.recovered_item_count || d.recovered_items.length}）`, rows: buildFilterDeleteTreeRows(items) })
  }
  if (Array.isArray(d.failed_targets) && d.failed_targets.length) {
    const items = mapFilterDeleteItems(d.failed_targets)
    sections.push({ key: 'retry-failed-targets', title: `重试后仍失败目录（${d.retry_failed_count || d.failed_targets.length}）`, rows: buildFilterDeleteTreeRows(items) })
  }
  return sections
}

function importFilteredEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (!['auto_import', 'process_existing'].includes(String(row?.category || '').trim())) return []

  const rawItems = Array.isArray(d.filtered_items) ? d.filtered_items : []
  if (!rawItems.length) return []

  const items = mapFilterDeleteItems(rawItems)
  const total = Number(d.filtered_count || rawItems.length || 0)
  return [{
    key: 'import-filtered-items',
    title: `过滤移除项（${total}）`,
    rows: buildFilterDeleteTreeRows(items)
  }]
}

function subtitleBatchEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object' || d.mode !== 'subtitle_batch_start') return []
  const sections = []
  if (Array.isArray(d.source_directories) && d.source_directories.length) {
    sections.push({
      key: 'batch-source-directories',
      title: `扫描目录（${d.source_directories.length}）`,
      rows: d.source_directories.slice(0, 120).map((item, index) => ({
        key: `${index}-${item.folder_path || item.path || item.folder_name || ''}`,
        label: item.folder_name || item.name || item.folder_path || item.path || '未命名目录',
        type: 'dir',
        sizeText: item.folder_path || item.path || '',
        error: '',
        depth: 0
      }))
    })
  }
  if (Array.isArray(d.scan_targets) && d.scan_targets.length) {
    sections.push({
      key: 'batch-scan-targets',
      title: `扫描结果（${d.scan_targets.length}）`,
      rows: d.scan_targets.slice(0, 160).map((item, index) => ({
        key: `${index}-${item.path || item.name || ''}`,
        label: `${item.name || item.path || '未命名目录'}${item.message ? ` · ${item.message}` : ''}`,
        type: 'dir',
        sizeText: item.path || '',
        error: '',
        depth: 0
      }))
    })
  }
  if (Array.isArray(d.created_tasks) && d.created_tasks.length) {
    sections.push({
      key: 'batch-created-tasks',
      title: `已创建爬取（${d.created_tasks.length}）`,
      rows: d.created_tasks.slice(0, 160).map((item, index) => ({
        key: `${index}-${item.task_id || item.folder_path || item.rjcode || ''}`,
        label: `${item.rjcode ? `[${item.rjcode}] ` : ''}${item.folder_name || item.folder_path || '未命名目录'}`,
        type: 'dir',
        sizeText: item.folder_path || '',
        error: '',
        depth: 0
      }))
    })
  }
  if (Array.isArray(d.skipped_items) && d.skipped_items.length) {
    sections.push({
      key: 'batch-skipped-items',
      title: `跳过项（${d.skipped_items.length}）`,
      rows: d.skipped_items.slice(0, 160).map((item, index) => ({
        key: `${index}-${item.folder_path || item.rjcode || item.folder_name || ''}`,
        label: `${item.rjcode ? `[${item.rjcode}] ` : ''}${item.folder_name || item.folder_path || '未命名目录'}`,
        type: 'dir',
        sizeText: item.folder_path || '',
        error: item.queue_message || '',
        depth: 0
      }))
    })
  }
  return sections
}

function activityEntrySections(row) {
  return [
    ...importFilteredEntrySections(row),
    ...subtitleBatchEntrySections(row),
    ...filterDeleteEntrySections(row)
  ]
}

function activityEntrySectionTitle(row) {
  const d = row?.detail
  if (d && typeof d === 'object' && d.mode === 'subtitle_batch_start') return '批量详情'
  if (['auto_import', 'process_existing'].includes(String(row?.category || '').trim())) return '处理清单'
  return '删除清单'
}

function formatDateTime(iso) {
  if (!iso) return '—'
  return dayjs(iso).format('YYYY-MM-DD HH:mm')
}

function displayRowTime(row) {
  if (!row) return ''
  return row.latest_activity_at || row.created_at
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

watch(items, (nextItems) => {
  const validIds = new Set()
  const walk = (rows) => {
    for (const row of rows || []) {
      if (rowHasChildren(row)) validIds.add(treeRowId(row))
      const childRows = Array.isArray(row?.detail?.child_rows) ? row.detail.child_rows : []
      walk(childRows)
    }
  }
  walk(nextItems)
  expandedTreeRowIds.value = new Set(
    [...expandedTreeRowIds.value].filter((id) => validIds.has(id))
  )
}, { immediate: true, deep: true })
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

.time-cell-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.tree-toggle-btn {
  width: 18px;
  height: 18px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: rgba(10, 132, 255, 0.08);
  color: #0a84ff;
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
  transition: transform 0.16s ease, background-color 0.16s ease, color 0.16s ease;
}

.tree-toggle-btn.expanded {
  transform: rotate(90deg);
}

.tree-toggle-btn:hover {
  background: rgba(10, 132, 255, 0.14);
}

.tree-toggle-placeholder {
  display: inline-block;
  width: 18px;
  height: 18px;
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

.cat-pipeline-delete {
  background: rgba(255, 59, 48, 0.1);
  color: #d70015;
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
  display: inline-flex;
  align-items: center;
  min-height: 16px;
  padding: 0 4px;
  border-radius: 4px;
  border: 1px solid rgba(52, 199, 89, 0.18);
  background: rgba(52, 199, 89, 0.1);
  color: #187d34;
  font-size: 9px;
  line-height: 1;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.status-fixed-pill.is-rerun {
  border-color: rgba(255, 159, 10, 0.18);
  background: rgba(255, 159, 10, 0.1);
  color: #c56a00;
}

.status-fixed-pill.is-partial {
  border-color: rgba(255, 159, 10, 0.18);
  background: rgba(255, 159, 10, 0.1);
  color: #c56a00;
}

.status-fixed-pill.is-final {
  border-radius: 3px;
}

.status-fixed-pill.is-final-success {
  border-color: rgba(52, 199, 89, 0.16);
  background: rgba(52, 199, 89, 0.08);
  color: #187d34;
}

.status-fixed-pill.is-final-partial {
  border-color: rgba(255, 159, 10, 0.16);
  background: rgba(255, 159, 10, 0.08);
  color: #c56a00;
}

.status-fixed-pill.is-final-failed {
  border-color: rgba(215, 0, 21, 0.16);
  background: rgba(215, 0, 21, 0.08);
  color: #b0001a;
}

.action-text {
  display: inline-block;
  white-space: nowrap;
  font-weight: 600;
}

.action-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  position: relative;
}

.child-action-wrap {
  padding-left: 0;
}

.category-cell-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  position: relative;
}

.child-row-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding-left: 0;
  color: rgba(29, 29, 31, 0.62);
  font-size: 12px;
  font-weight: 600;
}

.action-pill {
  display: inline-flex;
  align-items: center;
  min-height: 15px;
  padding: 0 4px;
  border-radius: 4px;
  border: 1px solid rgba(52, 199, 89, 0.16);
  background: rgba(52, 199, 89, 0.08);
  color: #248a3d;
  font-size: 9px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.action-pill.is-muted {
  border-color: rgba(142, 142, 147, 0.18);
  background: rgba(142, 142, 147, 0.08);
  color: #6b7280;
}

.action-pill.is-api-rename {
  border-color: rgba(10, 132, 255, 0.2);
  background: rgba(10, 132, 255, 0.12);
  color: #005fcc;
}

.action-pill.is-manual-rename {
  border-color: rgba(88, 86, 214, 0.2);
  background: rgba(88, 86, 214, 0.12);
  color: #4b3db8;
}

.action-pill.is-delete {
  border-color: rgba(215, 0, 21, 0.22);
  background: rgba(215, 0, 21, 0.1);
  color: #b0001a;
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

.child-summary {
  display: inline-block;
  padding-left: 0;
  color: rgba(29, 29, 31, 0.76);
  position: relative;
}

.tree-cell-content {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.tree-guides {
  position: absolute;
  left: 0;
  top: -10px;
  bottom: -10px;
  width: calc(var(--tree-depth, 1) * 14px);
  pointer-events: none;
  background-image:
    repeating-linear-gradient(
      to right,
      rgba(10, 132, 255, 0.08) 0 1px,
      transparent 1px 14px
    );
}

.tree-guides::after {
  content: '';
  position: absolute;
  left: calc((var(--tree-depth, 1) - 1) * 14px);
  top: 50%;
  width: 8px;
  height: 1px;
  background: rgba(10, 132, 255, 0.12);
}

.child-type-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: 0 0 auto;
}

.child-type-dot.is-rerun {
  background: #ff9500;
}

.child-type-dot.is-crawl {
  background: #0a84ff;
}

.child-type-dot.is-subtitle-import {
  background: #ff9f0a;
}

.child-type-dot.is-rename-item {
  background: #64d2ff;
}

.child-type-dot.is-pair {
  background: #5856d6;
}

.child-type-dot.is-filter-retry {
  background: #ffcc00;
}

.child-type-dot.is-delete-apply {
  background: #ff3b30;
}

.child-type-dot.is-delete-item {
  background: #ff453a;
}

.child-type-dot.is-default {
  background: #8e8e93;
}

:deep(.ios-table .activity-row-child td) {
  background: linear-gradient(180deg, rgba(52, 199, 89, 0.03), rgba(52, 199, 89, 0.06)) !important;
}

:deep(.ios-table .activity-row-child:hover > td) {
  background: linear-gradient(180deg, rgba(52, 199, 89, 0.06), rgba(52, 199, 89, 0.09)) !important;
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

.pair-change-table {
  display: grid;
  gap: 6px;
}

.pair-change-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  padding: 8px 10px;
  border-radius: 10px;
  background: #f7f7fa;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
}

.pair-change-head {
  background: #eef5ff;
  font-size: 12px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.68);
}

.pair-change-cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.path-compare-card {
  margin-bottom: 14px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(29, 29, 31, 0.08);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.94), rgba(248, 251, 255, 0.92));
}

.path-compare-card.is-rename {
  border-color: rgba(10, 132, 255, 0.25);
}

.path-compare-card.is-delete {
  border-color: rgba(215, 0, 21, 0.26);
}

.path-compare-card.is-status-is-success {
  box-shadow: inset 0 0 0 1px rgba(52, 199, 89, 0.12);
}

.path-compare-card.is-status-is-warn {
  box-shadow: inset 0 0 0 1px rgba(255, 159, 10, 0.14);
}

.path-compare-card.is-status-is-fail {
  box-shadow: inset 0 0 0 1px rgba(215, 0, 21, 0.15);
}

.path-compare-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.path-compare-head-right {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.path-compare-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.path-op-tag {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid transparent;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.path-op-tag.is-api-rename {
  border-color: rgba(10, 132, 255, 0.22);
  background: rgba(10, 132, 255, 0.12);
  color: #005fcc;
}

.path-op-tag.is-manual-rename {
  border-color: rgba(88, 86, 214, 0.22);
  background: rgba(88, 86, 214, 0.12);
  color: #4b3db8;
}

.path-op-tag.is-rename {
  border-color: rgba(64, 132, 255, 0.2);
  background: rgba(64, 132, 255, 0.1);
  color: #0a5ac2;
}

.path-op-tag.is-delete {
  border-color: rgba(215, 0, 21, 0.24);
  background: rgba(215, 0, 21, 0.11);
  color: #b0001a;
}

.path-compare-status {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.path-compare-status.is-success {
  background: rgba(52, 199, 89, 0.12);
  color: #187d34;
}

.path-compare-status.is-warn {
  background: rgba(255, 159, 10, 0.12);
  color: #c56a00;
}

.path-compare-status.is-fail {
  background: rgba(215, 0, 21, 0.11);
  color: #b0001a;
}

.path-compare-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 10px;
  align-items: stretch;
}

.path-compare-col {
  min-width: 0;
  border-radius: 12px;
  padding: 10px;
}

.path-compare-col.old {
  background: rgba(255, 149, 0, 0.08);
}

.path-compare-col.new {
  background: rgba(10, 132, 255, 0.08);
}

.path-compare-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(29, 29, 31, 0.52);
  margin-bottom: 6px;
}

.path-compare-path {
  font-size: 12px;
  line-height: 1.5;
  color: #1d1d1f;
}

.path-compare-arrow {
  align-self: center;
  color: rgba(29, 29, 31, 0.4);
  font-size: 16px;
  font-weight: 700;
}

.path-compare-reason {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  font-size: 12px;
  line-height: 1.45;
  border: 1px solid transparent;
}

.path-compare-reason.is-success {
  border-color: rgba(52, 199, 89, 0.2);
  background: rgba(52, 199, 89, 0.08);
  color: #187d34;
}

.path-compare-reason.is-warn {
  border-color: rgba(255, 159, 10, 0.2);
  background: rgba(255, 159, 10, 0.1);
  color: #c56a00;
}

.path-compare-reason.is-fail {
  border-color: rgba(215, 0, 21, 0.2);
  background: rgba(215, 0, 21, 0.09);
  color: #b0001a;
}

.path-compare-reason.is-empty {
  opacity: 0.9;
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
