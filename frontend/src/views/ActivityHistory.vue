<template>
  <div
    class="activity-page activity-page-loading-shell"
    v-app-loading="{ loading, text: '正在加载操作记录...', description: '同步树形记录、状态聚合和详情索引', size: 176, minHeight: 360, delay: 0, minVisible: 360, maskClass: 'activity-history-loading-mask' }"
  >
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
        <AppEmptyState v-if="!byDay.length" description="暂无数据" size="sm" />
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
        <AppEmptyState v-if="!stats.by_category.length" description="暂无数据" size="sm" />
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
        class="ios-table"
        stripe
        size="small"
        empty-text="暂无记录"
        :row-class-name="rowClassName"
        table-layout="fixed"
        :row-key="resolveActivityTableRowKey"
        @row-click="openDetail"
      >
        <el-table-column prop="created_at" label="时间" width="168">
          <template #default="{ row }">
            <span class="time-cell-wrap" :style="row.is_tree_child ? childIndentStyle(row, 0) : undefined">
              <button
                v-if="rowHasChildren(row)"
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
        <el-table-column prop="category_label" label="分类" width="160">
          <template #default="{ row }">
            <span class="flex items-start gap-1.5 flex-wrap">
              <template v-if="row.is_tree_child">
                <span class="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500/80" :style="childIndentStyle(row)">
                  <span class="tree-guides" :style="treeGuideStyle(row)" aria-hidden="true"></span>
                  <span :class="['size-1.5 rounded-full', childTypeDotClass(row)]"></span>
                  <span>{{ childRowCategoryLabel(row) }}</span>
                </span>
              </template>
              <template v-else>
                <div class="flex items-center gap-1.5">
                  <span
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors duration-200"
                    :class="[getCategoryConfig(row.category).color, getCategoryConfig(row.category).bg, getCategoryConfig(row.category).border]"
                  >
                    <Search v-if="row.category === 'subtitle_crawl'" :size="12" :stroke-width="2.5" />
                    <Link v-else-if="row.category === 'subtitle_pair'" :size="12" :stroke-width="2.5" />
                    <FileDown v-else-if="row.category === 'subtitle_import'" :size="12" :stroke-width="2.5" />
                    <Package v-else-if="row.category === 'extract'" :size="12" :stroke-width="2.5" />
                    <Database v-else-if="row.category === 'auto_import'" :size="12" :stroke-width="2.5" />
                    <Folder v-else-if="row.category === 'process_existing'" :size="12" :stroke-width="2.5" />
                    <Scissors v-else-if="row.category === 'pipeline_delete'" :size="12" :stroke-width="2.5" />
                    <RefreshCw v-else-if="row.category === 'asmr_sync'" :size="12" :stroke-width="2.5" />
                    <Users v-else-if="row.category === 'circle_completion'" :size="12" :stroke-width="2.5" />
                    <Tag v-else :size="12" :stroke-width="2.5" />
                    {{ row.category_label }}
                  </span>
                  <div v-if="rowCategoryTags(row).length" class="flex flex-col gap-[3px] justify-center">
                    <span
                      v-for="tag in rowCategoryTags(row)"
                      :key="`${row.id}-${tag}`"
                      class="inline-flex items-center px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-all duration-200"
                      :class="[
                        tag === '未命中'
                          ? 'bg-slate-50 text-slate-500 border-slate-200/60'
                          : 'bg-emerald-50 text-emerald-600 border-emerald-100',
                        actionTagClass(row, tag) === 'is-api-rename' && 'bg-blue-50 text-blue-600 border-blue-100',
                        actionTagClass(row, tag) === 'is-manual-rename' && 'bg-violet-50 text-violet-600 border-violet-100'
                      ]"
                    >{{ tag }}</span>
                  </div>
                </div>
              </template>
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="130">
          <template #default="{ row }">
            <div class="flex items-center gap-1.5">
              <span
                class="inline-flex items-center gap-1.5 text-xs font-bold transition-all duration-200"
                :class="getStatusConfig(row.status).color"
              >
                <CheckCircle2 v-if="row.status === 'success'" :size="14" :stroke-width="2.5" />
                <AlertCircle v-else-if="row.status === 'partial_success'" :size="14" :stroke-width="2.5" />
                <XCircle v-else-if="row.status === 'failed'" :size="14" :stroke-width="2.5" />
                <MinusCircle v-else-if="row.status === 'cancelled'" :size="14" :stroke-width="2.5" />
                <Clock v-else-if="row.status === 'waiting'" :size="14" :stroke-width="2.5" />
                <PlayCircle v-else-if="row.status === 'incomplete'" :size="14" :stroke-width="2.5" />
                <MinusCircle v-else :size="14" :stroke-width="2.5" />
                {{ getStatusConfig(row.status).label }}
              </span>
              <div v-if="showAsmrUploadBadge(row) || isRecoveredFailure(row) || (!row.is_tree_child && (isRerunRow(row) || finalStatusLabel(row)))" class="flex flex-col gap-[3px] justify-center">
                <span
                  v-if="showAsmrUploadBadge(row)"
                  class="inline-flex shrink-0 items-center gap-[3px] rounded-full border border-emerald-200/80 bg-emerald-50/90 px-1 py-[1.5px] text-[8.5px] font-bold uppercase tracking-wider leading-none text-emerald-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]"
                  title="上传成功"
                >
                  <span class="size-1 rounded-full bg-emerald-500"></span>
                  <span>上传</span>
                  <Check :size="8" :stroke-width="3" />
                </span>
                <span
                  v-if="isRecoveredFailure(row) && finalStatusLabel(row) !== '已修复✔'"
                  class="inline-flex items-center px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border border-emerald-200 bg-emerald-50 text-emerald-600 shadow-sm"
                >已修复</span>
                <template v-if="!row.is_tree_child">
                  <span
                    v-if="isRerunRow(row)"
                    class="inline-flex items-center px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border border-amber-200 bg-amber-50 text-amber-600 shadow-sm"
                  >重新爬取</span>
                  <span
                    v-if="finalStatusLabel(row)"
                    class="inline-flex items-center px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border shadow-sm"
                    :class="[
                      finalStatusClass(row) === 'is-final-success' ? 'border-emerald-200 bg-emerald-50 text-emerald-600' :
                      finalStatusClass(row) === 'is-final-failed' ? 'border-rose-200 bg-rose-50 text-rose-600' :
                      'border-amber-200 bg-amber-50 text-amber-600'
                    ]"
                  >{{ finalStatusLabel(row) }}</span>
                </template>
              </div>
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

    <ActivityLogDetailDialog
      :visible="detailDialogVisible"
      :row="selectedRow"
      :get-category-config="getCategoryConfig"
      :get-status-config="getStatusConfig"
      :human-action="humanAction"
      :format-date-time="formatDateTime"
      :display-rjcode="displayRjcode"
      :row-tags="selectedRow ? rowCategoryTags(selectedRow) : []"
      :action-tag-class="actionTagClass"
      :is-rerun="selectedRow ? isRerunRow(selectedRow) : false"
      :final-status-label="selectedRow ? finalStatusLabel(selectedRow) : ''"
      :final-status-class="selectedRow ? finalStatusClass(selectedRow) : ''"
      :is-recovered-failure="selectedRow ? isRecoveredFailure(selectedRow) : false"
      :path-compare="selectedRow ? pathCompareModel(selectedRow) : null"
      :path-compare-reason-class="selectedRow ? pathCompareReasonClass(selectedRow) : ''"
      :path-compare-default-reason="selectedRow ? pathCompareDefaultReason(selectedRow) : ''"
      :summary-text="selectedRow ? displaySummary(selectedRow) : ''"
      @close="detailDialogVisible = false"
    >
      <div v-if="selectedRow" class="expand-shell">
        <div class="expand-grid">
          <div v-if="!selectedCircleCompletionIndexModel" class="expand-item">
            <div class="ek">分类</div>
            <div class="ev flex items-center gap-2 mt-1">
              <div class="flex items-center gap-1.5">
                <span
                  class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border"
                  :class="[getCategoryConfig(selectedRow.category).color, getCategoryConfig(selectedRow.category).bg, getCategoryConfig(selectedRow.category).border]"
                >
                  <Search v-if="selectedRow.category === 'subtitle_crawl'" :size="14" :stroke-width="2.5" />
                  <Link v-else-if="selectedRow.category === 'subtitle_pair'" :size="14" :stroke-width="2.5" />
                  <FileDown v-else-if="selectedRow.category === 'subtitle_import'" :size="14" :stroke-width="2.5" />
                  <Package v-else-if="selectedRow.category === 'extract'" :size="14" :stroke-width="2.5" />
                  <Database v-else-if="selectedRow.category === 'auto_import'" :size="14" :stroke-width="2.5" />
                  <Folder v-else-if="selectedRow.category === 'process_existing'" :size="14" :stroke-width="2.5" />
                  <Scissors v-else-if="selectedRow.category === 'pipeline_delete'" :size="14" :stroke-width="2.5" />
                  <RefreshCw v-else-if="selectedRow.category === 'asmr_sync'" :size="14" :stroke-width="2.5" />
                  <Users v-else-if="selectedRow.category === 'circle_completion'" :size="14" :stroke-width="2.5" />
                  <Tag v-else :size="14" :stroke-width="2.5" />
                  {{ selectedRow.category_label }}
                </span>
                <span class="text-xs text-slate-400 font-medium">({{ selectedRow.category }})</span>
              </div>
              <div v-if="rowCategoryTags(selectedRow).length" class="flex flex-col gap-[3px] justify-center ml-1">
                <span
                  v-for="tag in rowCategoryTags(selectedRow)"
                  :key="`drawer-${selectedRow.id}-${tag}`"
                  class="inline-flex items-center px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border shadow-sm transition-all duration-200"
                  :class="[
                    tag === '未命中'
                      ? 'bg-slate-50 text-slate-500 border-slate-200/60'
                      : 'bg-emerald-50 text-emerald-600 border-emerald-100',
                    actionTagClass(selectedRow, tag) === 'is-api-rename' && 'bg-blue-50 text-blue-600 border-blue-100',
                    actionTagClass(selectedRow, tag) === 'is-manual-rename' && 'bg-violet-50 text-violet-600 border-violet-100'
                  ]"
                >{{ tag }}</span>
              </div>
            </div>
          </div>
          <div v-if="!selectedCircleCompletionIndexModel" class="expand-item">
            <div class="ek">状态</div>
            <div class="ev flex items-center gap-2 mt-1">
              <span
                class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold border"
                :class="[getStatusConfig(selectedRow.status).color, getStatusConfig(selectedRow.status).bg, getStatusConfig(selectedRow.status).border]"
              >
                <CheckCircle2 v-if="selectedRow.status === 'success'" :size="14" :stroke-width="2.5" />
                <AlertCircle v-else-if="selectedRow.status === 'partial_success'" :size="14" :stroke-width="2.5" />
                <XCircle v-else-if="selectedRow.status === 'failed'" :size="14" :stroke-width="2.5" />
                <MinusCircle v-else-if="selectedRow.status === 'cancelled'" :size="14" :stroke-width="2.5" />
                <Clock v-else-if="selectedRow.status === 'waiting'" :size="14" :stroke-width="2.5" />
                <PlayCircle v-else-if="selectedRow.status === 'incomplete'" :size="14" :stroke-width="2.5" />
                <MinusCircle v-else :size="14" :stroke-width="2.5" />
                {{ getStatusConfig(selectedRow.status).label }}
              </span>
              <div v-if="isRerunRow(selectedRow) || finalStatusLabel(selectedRow) || isRecoveredFailure(selectedRow)" class="flex flex-col gap-[3px] justify-center ml-1">
                <span
                  v-if="isRerunRow(selectedRow)"
                  class="inline-flex items-center px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border border-amber-200 bg-amber-50 text-amber-600 shadow-sm"
                >重新爬取</span>
                <span
                  v-if="finalStatusLabel(selectedRow)"
                  class="inline-flex items-center px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border shadow-sm"
                  :class="[
                    finalStatusClass(selectedRow) === 'is-final-success' ? 'border-emerald-200 bg-emerald-50 text-emerald-600' :
                    finalStatusClass(selectedRow) === 'is-final-failed' ? 'border-rose-200 bg-rose-50 text-rose-600' :
                    'border-amber-200 bg-amber-50 text-amber-600'
                  ]"
                >{{ finalStatusLabel(selectedRow) }}</span>
                <span
                  v-if="isRecoveredFailure(selectedRow) && finalStatusLabel(selectedRow) !== '已修复✔'"
                  class="inline-flex items-center px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border border-emerald-200 bg-emerald-50 text-emerald-600 shadow-sm"
                >已修复</span>
              </div>
            </div>
          </div>
          <div v-if="!selectedCircleCompletionIndexModel" class="expand-item">
            <div class="ek">时间</div>
            <div class="ev mono">{{ formatDateTime(selectedRow.created_at) }}</div>
          </div>
          <div v-if="!selectedCircleCompletionIndexModel" class="expand-item span-2">
            <div class="ek">摘要</div>
            <div class="ev">{{ displaySummary(selectedRow) }}</div>
          </div>
          <div v-if="selectedCircleCompletionIndexModel" class="expand-item span-2">
            <div class="compare-table-shell">
              <div class="compare-table-head" @click="compareExpanded = !compareExpanded">
                <div class="compare-table-title-wrap">
                  <div class="compare-table-icon">
                    <LayoutGrid :size="18" :stroke-width="2.4" />
                  </div>
                  <div>
                    <div class="compare-table-title">社团概括</div>
                    <div class="compare-table-subtitle">{{ circleIndexSummaryText }}</div>
                  </div>
                </div>
                <div class="compare-table-toolbar">
                  <label class="compare-search" @click.stop>
                    <Search :size="14" :stroke-width="2.4" />
                    <input v-model.trim="compareSearchQuery" type="text" placeholder="Filter resources...">
                  </label>
                  <label class="compare-filter" @click.stop>
                    <SlidersHorizontal :size="13" :stroke-width="2.4" />
                    <el-select
                      v-model="compareSourceFilter"
                      size="small"
                      popper-class="compare-filter-popper"
                      placeholder="全部来源"
                      @click.stop
                    >
                      <el-option value="all" label="全部来源" />
                      <el-option value="kikoeru" label="Kikoeru" />
                      <el-option value="dlsite" label="DLsite" />
                      <el-option value="asmr_one" label="asmr.one" />
                      <el-option value="missing" label="暂无来源" />
                    </el-select>
                  </label>
                </div>
              </div>

              <transition
                enter-active-class="transition-[max-height,opacity] duration-300 ease-out overflow-hidden"
                enter-from-class="max-h-0 opacity-0"
                enter-to-class="max-h-[1200px] opacity-100"
                leave-active-class="transition-[max-height,opacity] duration-200 ease-in overflow-hidden"
                leave-from-class="max-h-[1200px] opacity-100"
                leave-to-class="max-h-0 opacity-0"
              >
                <div v-if="compareExpanded">
                  <div class="compare-column-head">
                    <div class="compare-col-meta">RESOURCE METADATA</div>
                    <div class="compare-col-source">KIKOERU</div>
                    <div class="compare-col-source">DLSITE</div>
                    <div class="compare-col-source">ASMR.ONE</div>
                  </div>

                  <div class="compare-rows-wrap">
                    <div
                      v-for="item in filteredCircleIndexRows"
                      :key="item.workRjcode"
                      class="compare-row"
                    >
                      <div class="compare-meta-cell">
                        <div class="compare-thumb compare-thumb-empty">
                          <FileText :size="18" :stroke-width="2.2" />
                        </div>
                        <div class="compare-meta-copy">
                          <div class="compare-meta-title">{{ item.title || item.workRjcode || '未命名作品' }}</div>
                          <div class="compare-meta-tags">
                            <span class="compare-rj-badge mono">{{ item.workRjcode || '—' }}</span>
                            <span :class="['circle-index-status-pill', `is-${item.statusKey}`]">{{ item.statusLabel }}</span>
                            <span v-if="item.preferred_variant_label" class="compare-meta-tag">{{ item.preferred_variant_label }}</span>
                          </div>
                        </div>
                      </div>

                      <div class="compare-source-cell">
                        <div class="compare-source-status" :class="`is-${circleIndexSourceTone('kikoeru', item)}`">
                          <component :is="circleIndexSourceIcon('kikoeru', item)" :size="14" :stroke-width="2.6" />
                        </div>
                        <div class="compare-source-meta">
                          <div v-if="item.sourceCompare.kikoeru.primary_rjcode" class="compare-source-code mono">{{ item.sourceCompare.kikoeru.primary_rjcode }}</div>
                          <div v-if="item.sourceCompare.kikoeru.variantBadges.length || normalizeKikoeruTags(item.sourceCompare.kikoeru.tags).length" class="compare-source-tags">
                            <span v-for="badge in item.sourceCompare.kikoeru.variantBadges" :key="`kb-${item.workRjcode}-${badge}`" class="compare-meta-tag">{{ badge }}</span>
                            <span v-for="tag in normalizeKikoeruTags(item.sourceCompare.kikoeru.tags)" :key="`kt-${item.workRjcode}-${tag}`" class="compare-meta-tag">{{ tag }}</span>
                          </div>
                          <span v-else-if="!item.sourceCompare.kikoeru.primary_rjcode" class="circle-index-empty">未收录</span>
                        </div>
                      </div>

                      <div class="compare-source-cell">
                        <div class="compare-source-status" :class="`is-${circleIndexSourceTone('dlsite', item)}`">
                          <component :is="circleIndexSourceIcon('dlsite', item)" :size="14" :stroke-width="2.6" />
                        </div>
                        <div class="compare-source-meta">
                          <div v-if="item.sourceCompare.dlsite.all_rjcodes.length" class="compare-source-tags">
                            <span v-for="code in item.sourceCompare.dlsite.all_rjcodes" :key="`d-${item.workRjcode}-${code}`" class="compare-meta-tag mono">{{ code }}</span>
                          </div>
                          <span v-else class="circle-index-empty">未发现</span>
                        </div>
                      </div>

                      <div class="compare-source-cell">
                        <div class="compare-source-status" :class="`is-${circleIndexSourceTone('asmr_one', item)}`">
                          <component :is="circleIndexSourceIcon('asmr_one', item)" :size="14" :stroke-width="2.6" />
                        </div>
                        <div class="compare-source-meta">
                          <div v-if="item.sourceCompare.asmr_one.primary_rjcode" class="compare-source-tags">
                            <span class="compare-meta-tag mono">{{ item.sourceCompare.asmr_one.primary_rjcode }}</span>
                            <span v-if="item.sourceCompare.asmr_one.primaryBadge" class="compare-meta-tag">{{ item.sourceCompare.asmr_one.primaryBadge }}</span>
                          </div>
                          <span v-else class="circle-index-empty">暂无来源</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </transition>
            </div>
          </div>
          <div v-if="selectedCircleCompletionRefreshModel" class="expand-item span-2">
            <div class="ek">本次更新作品</div>
            <div class="circle-refresh-card">
              <div class="circle-refresh-head">
                <div>
                  <div class="circle-refresh-title">社团作品拥有状态更新</div>
                  <div class="circle-refresh-desc">只展示这次刷新后的业务状态：服务器是否命中、命中的服务器 RJ、字幕有没有，以及是否真的发生变化。</div>
                </div>
                <div class="circle-refresh-metrics">
                  <span class="circle-refresh-metric">已选 {{ selectedCircleCompletionRefreshModel.selectedCount }}</span>
                  <span class="circle-refresh-metric">已刷新 {{ selectedCircleCompletionRefreshModel.refreshedCount }}</span>
                  <span class="circle-refresh-metric is-changed">有更新 {{ selectedCircleCompletionRefreshModel.changedCount }}</span>
                  <span class="circle-refresh-metric">命中服务器 {{ selectedCircleCompletionRefreshModel.serverMatchedCount }}</span>
                </div>
              </div>
              <div class="circle-refresh-toolbar">
                <div class="circle-refresh-filter-group">
                  <button type="button" class="circle-refresh-filter-btn" :class="{ active: circleRefreshFilter === 'all' }" @click="setCircleRefreshFilter('all')">全部</button>
                  <button type="button" class="circle-refresh-filter-btn" :class="{ active: circleRefreshFilter === 'changed' }" @click="setCircleRefreshFilter('changed')">仅有更新</button>
                  <button type="button" class="circle-refresh-filter-btn" :class="{ active: circleRefreshFilter === 'unchanged' }" @click="setCircleRefreshFilter('unchanged')">仅无变化</button>
                </div>
              </div>
              <div class="circle-refresh-list">
                <div
                  v-for="item in pagedCircleCompletionRefreshItems"
                  :key="`${item.canonical_rjcode}-${item.display_rjcode}`"
                  class="circle-refresh-item"
                  :class="{ 'is-changed': item.changed }"
                >
                  <span v-if="item.changed" class="circle-refresh-new-badge">NEW</span>
                  <div class="circle-refresh-item-top">
                    <span class="circle-refresh-title-rj mono">{{ item.display_rjcode || item.canonical_rjcode }}</span>
                    <span class="circle-refresh-status" :class="`is-${item.resultStatus}`">
                      {{ item.resultLabel }}
                    </span>
                    <span class="circle-refresh-status" :class="item.changed ? 'is-updated' : 'is-unchanged'">
                      {{ item.changed ? '有更新' : '无变化' }}
                    </span>
                  </div>
                  <div class="circle-refresh-item-title">{{ item.title || item.display_rjcode || item.canonical_rjcode }}</div>
                  <div v-if="item.changeDetails.length" class="circle-refresh-change-list">
                    <div
                      v-for="change in item.changeDetails"
                      :key="`${item.canonical_rjcode}-${change.key}`"
                      class="circle-refresh-change-row"
                    >
                      <span class="circle-refresh-change-label">{{ change.label }}</span>
                      <div class="circle-refresh-change-values">
                        <span class="circle-refresh-change-before">{{ formatRefreshChangeValue(change.before) }}</span>
                        <span class="circle-refresh-change-arrow">→</span>
                        <span class="circle-refresh-change-after">{{ formatRefreshChangeValue(change.after) }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="selectedCircleCompletionRefreshModel.filteredCount > circleRefreshPageSize" class="circle-refresh-pager">
                <el-pagination
                  :current-page="circleRefreshPage"
                  :page-size="circleRefreshPageSize"
                  layout="prev, pager, next"
                  :total="selectedCircleCompletionRefreshModel.filteredCount"
                  background
                  @current-change="setCircleRefreshPage"
                />
              </div>
            </div>
          </div>
          <div v-if="pairWorkbenchModel(selectedRow)" class="expand-item span-2 pair-workbench-block">
            <div class="pair-workbench-card" :class="{ 'is-awaiting': pairWorkbenchModel(selectedRow).awaiting }">
              <div class="pair-workbench-main">
                <div class="pair-workbench-kicker">{{ pairWorkbenchModel(selectedRow).awaiting ? '待继续处理' : '可查看工作台' }}</div>
                <div class="pair-workbench-title">{{ pairWorkbenchModel(selectedRow).title }}</div>
                <div class="pair-workbench-desc">{{ pairWorkbenchModel(selectedRow).description }}</div>
                <div v-if="pairWorkbenchModel(selectedRow).chips.length" class="pair-workbench-chips">
                  <span
                    v-for="chip in pairWorkbenchModel(selectedRow).chips"
                    :key="chip"
                    class="pair-workbench-chip"
                  >{{ chip }}</span>
                </div>
              </div>
              <el-button
                type="primary"
                class="pair-workbench-btn"
                @click="openSubtitlePairWorkbench(selectedRow)"
              >
                {{ pairWorkbenchModel(selectedRow).buttonText }}
              </el-button>
            </div>
          </div>
          <div v-if="subtitleBatchWorkbenchModel(selectedRow)" class="expand-item span-2">
            <div class="ek">批量工作台</div>
            <div class="batch-workbench-shell">
              <div class="batch-workbench-summary">
                <div class="batch-workbench-title">这条批量记录包含 {{ subtitleBatchWorkbenchModel(selectedRow).items.length }} 个已执行 RJ</div>
                <div class="batch-workbench-desc">勾选要继续处理的 RJ，直接带回库存里的字幕工作台。这里只展示批量子任务，不展示单个 RJ 的配对映射。</div>
                <div class="batch-workbench-metrics">
                  <span class="inline-flex items-center gap-1 px-1.5 py-[1px] rounded bg-emerald-50 text-emerald-600 text-[8.5px] font-bold uppercase tracking-wider leading-none border border-emerald-100/60 shadow-sm">
                    <CheckCircle2 :size="10" :stroke-width="2.5" />
                    已配对 {{ subtitleBatchWorkbenchModel(selectedRow).pairedCount }}
                  </span>
                  <span class="inline-flex items-center gap-1 px-1.5 py-[1px] rounded bg-amber-50 text-amber-600 text-[8.5px] font-bold uppercase tracking-wider leading-none border border-amber-100/60 shadow-sm">
                    <Clock :size="10" :stroke-width="2.5" />
                    待配对 {{ subtitleBatchWorkbenchModel(selectedRow).awaitingCount }}
                  </span>
                  <span class="inline-flex items-center gap-1 px-1.5 py-[1px] rounded bg-slate-50 text-slate-500 text-[8.5px] font-bold uppercase tracking-wider leading-none border border-slate-200/60 shadow-sm">
                    <FileText :size="10" :stroke-width="2.5" />
                    共 {{ subtitleBatchWorkbenchModel(selectedRow).items.length }}
                  </span>
                </div>
              </div>
              <div class="batch-workbench-toolbar">
                <div class="batch-workbench-toolbar-start">
                  <label class="batch-workbench-checkall">
                    <input
                      v-model="batchWorkbenchAwaitingOnly"
                      type="checkbox"
                    >
                    <span>只看待配对</span>
                  </label>
                  <button
                    type="button"
                    class="batch-workbench-quick-btn"
                    @click="selectAwaitingBatchWorkbenchItems(selectedRow)"
                  >
                    全选未配对
                  </button>
                </div>
                <label class="batch-workbench-checkall">
                  <input
                    type="checkbox"
                    :checked="isAllBatchWorkbenchItemsSelected(selectedRow)"
                    @change="toggleAllBatchWorkbenchItems(selectedRow, $event.target.checked)"
                  >
                  <span>全选</span>
                </label>
                <el-button
                  type="primary"
                  class="pair-workbench-btn"
                  :disabled="!selectedBatchWorkbenchItems(selectedRow).length"
                  @click="openSubtitleBatchWorkbench(selectedRow)"
                >
                  将选中项带到工作台
                </el-button>
              </div>
              <div class="batch-workbench-list">
                <label
                  v-for="item in visibleBatchWorkbenchItems(selectedRow)"
                  :key="item.key"
                  class="batch-workbench-item"
                >
                  <input
                    v-model="selectedBatchWorkbenchKeys"
                    type="checkbox"
                    :value="item.key"
                  >
                  <div class="batch-workbench-item-main">
                    <div class="batch-workbench-item-head">
                      <span class="batch-workbench-item-rj">{{ item.rjcode || '未知RJ' }}</span>
                      <span
                        class="inline-flex items-center gap-1 px-1 py-[1px] rounded text-[8px] font-bold uppercase tracking-wider leading-none border shadow-sm"
                        :class="[
                          item.stateClass === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-600' :
                          item.stateClass === 'failed' ? 'border-rose-200 bg-rose-50 text-rose-600' :
                          'border-amber-200 bg-amber-50 text-amber-600'
                        ]"
                      >
                        <CheckCircle2 v-if="item.stateClass === 'success'" :size="8" :stroke-width="3" />
                        <XCircle v-else-if="item.stateClass === 'failed'" :size="8" :stroke-width="3" />
                        <Clock v-else :size="8" :stroke-width="3" />
                        {{ item.stateLabel }}
                      </span>
                    </div>
                    <div class="batch-workbench-item-name">{{ item.folderName }}</div>
                    <div class="batch-workbench-item-summary">{{ item.summary }}</div>
                  </div>
                </label>
              </div>
            </div>
          </div>
          <div v-if="pairResultModel(selectedRow)" class="expand-item span-2">
            <div class="ek">配对结果</div>
            <div class="pair-result-shell">
              <div class="pair-result-summary">
                <div class="pair-result-title-row">
                  <div class="pair-result-title">{{ pairResultModel(selectedRow).title }}</div>
                  <span
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold border"
                    :class="[
                      pairResultModel(selectedRow).status === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-600' :
                      pairResultModel(selectedRow).status === 'failed' ? 'border-rose-200 bg-rose-50 text-rose-600' :
                      'border-amber-200 bg-amber-50 text-amber-600'
                    ]"
                  >
                    <CheckCircle2 v-if="pairResultModel(selectedRow).status === 'success'" :size="14" :stroke-width="2.5" />
                    <XCircle v-else-if="pairResultModel(selectedRow).status === 'failed'" :size="14" :stroke-width="2.5" />
                    <AlertCircle v-else :size="14" :stroke-width="2.5" />
                    {{ pairResultModel(selectedRow).statusLabel }}
                  </span>
                </div>
                <div v-if="pairResultModel(selectedRow).summary" class="pair-result-summary-text">
                  {{ pairResultModel(selectedRow).summary }}
                </div>
                <div class="pair-result-metrics">
                  <div
                    v-for="metric in pairResultModel(selectedRow).metrics"
                    :key="metric.label"
                    class="pair-result-metric"
                  >
                    <div class="pair-result-metric-label">{{ metric.label }}</div>
                    <div class="pair-result-metric-value">{{ metric.value }}</div>
                  </div>
                </div>
              </div>

              <div v-if="pairResultModel(selectedRow).changes.length" class="pair-change-board">
                <div class="pair-change-board-head">
                  <span>配对映射</span>
                  <span class="pair-change-board-count">{{ pairResultModel(selectedRow).changes.length }} 组</span>
                </div>
                <div
                  v-for="(item, index) in pairResultModel(selectedRow).changes"
                  :key="`${index}-${item.audio_before}-${item.subtitle_before}`"
                  class="pair-change-card"
                >
                  <div class="pair-change-card-grid">
                    <div class="pair-change-column">
                      <div class="pair-change-label">音频</div>
                      <div class="pair-change-value mono">{{ item.audio_before || '—' }}</div>
                      <div v-if="item.audio_after && item.audio_after !== item.audio_before" class="pair-change-target mono">
                        → {{ item.audio_after }}
                      </div>
                    </div>
                    <div class="pair-change-column">
                      <div class="pair-change-label">字幕</div>
                      <div class="pair-change-value mono">{{ item.subtitle_before || '—' }}</div>
                      <div v-if="item.subtitle_after && item.subtitle_after !== item.subtitle_before" class="pair-change-target mono">
                        → {{ item.subtitle_after }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-if="!selectedCircleCompletionIndexModel" class="expand-item span-2">
            <div class="ek">源路径</div>
            <div class="ev mono break">{{ selectedRow.source_path || '—' }}</div>
          </div>
          <div v-if="!selectedCircleCompletionIndexModel" class="expand-item span-2">
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
                <div class="entry-section-head">
                  <div class="entry-section-head-copy">
                    <div class="entry-section-title">{{ section.title }}</div>
                    <div v-if="section.description" class="entry-section-desc mono">{{ section.description }}</div>
                  </div>
                  <button
                    type="button"
                    class="entry-section-toggle"
                    @click.stop="toggleEntrySection(section.key)"
                  >
                    {{ isEntrySectionExpanded(section.key) ? '收起' : '展开' }}
                  </button>
                </div>
                <div v-show="isEntrySectionExpanded(section.key)" class="entry-tree-box">
                  <div
                    v-for="item in flattenEntryRows(section.rows)"
                    :key="`${section.key}-${item.key}`"
                    class="tree-row-shell"
                  >
                    <div
                      class="tree-row"
                      :class="{ 'is-expandable': item.expandable }"
                      :style="{ paddingLeft: `${12 + item.depth * 18}px` }"
                    >
                      <div class="tree-main">
                        <button
                          v-if="item.expandable"
                          type="button"
                          class="tree-inline-toggle"
                          :class="{ expanded: isEntryTreeRowExpanded(item.key) }"
                          @click.stop="toggleEntryTreeRow(item.key)"
                          :aria-label="isEntryTreeRowExpanded(item.key) ? '收起' : '展开'"
                        >
                          <ChevronRight :size="12" :stroke-width="2.6" />
                        </button>
                        <span v-else class="tree-branch" aria-hidden="true">{{ item.depth ? '└' : '•' }}</span>
                        <span :class="['entry-icon', entryIconClass(item), { 'is-deleted': item.variant === 'deleted' }]">
                          <component :is="resolveEntryIcon(item)" :size="14" />
                        </span>
                        <div class="entry-main-copy">
                          <div class="entry-title-row">
                            <span :class="['entry-name', { 'is-deleted': item.variant === 'deleted', 'is-failed': item.variant === 'failed' }]">{{ item.label }}</span>
                            <span
                              v-for="badge in item.badges || []"
                              :key="`${item.key}-${badge}`"
                              class="entry-inline-badge"
                            >{{ badge }}</span>
                          </div>
                          <span v-if="item.metaText" class="entry-meta-text">{{ item.metaText }}</span>
                        </div>
                      </div>
                      <span v-if="item.sizeText" class="entry-size">{{ item.sizeText }}</span>
                      <span v-if="item.error" class="entry-error">{{ item.error }}</span>
                    </div>
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
    </ActivityLogDetailDialog>

  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  AlertCircle,
  Box,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  Database,
  Download,
  File as FileIcon,
  FileArchive,
  FileDown,
  FileText,
  Film,
  Folder,
  Image as ImageIcon,
  LayoutGrid,
  Link,
  MinusCircle,
  Music,
  Package,
  PlayCircle,
  RefreshCw,
  Scissors,
  Search,
  SlidersHorizontal,
  Tag,
  Users,
  XCircle
} from 'lucide-vue-next'
import dayjs from 'dayjs'
import api from '../api'
import ActivityLogDetailDialog from '../components/activity/ActivityLogDetailDialog.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'

const router = useRouter()
const loading = ref(true)

const categoryConfigs = {
  subtitle_crawl: { icon: Search, color: 'text-indigo-600', bg: 'bg-indigo-50/80', border: 'border-indigo-100/50' },
  subtitle_pair: { icon: Link, color: 'text-violet-600', bg: 'bg-violet-50/80', border: 'border-violet-100/50' },
  subtitle_import: { icon: FileDown, color: 'text-amber-600', bg: 'bg-amber-50/80', border: 'border-amber-100/50' },
  extract: { icon: Package, color: 'text-emerald-600', bg: 'bg-emerald-50/80', border: 'border-emerald-100/50' },
  auto_import: { icon: Database, color: 'text-emerald-600', bg: 'bg-emerald-50/80', border: 'border-emerald-100/50' },
  process_existing: { icon: Folder, color: 'text-slate-600', bg: 'bg-slate-50/80', border: 'border-slate-100/50' },
  pipeline_delete: { icon: Scissors, color: 'text-rose-600', bg: 'bg-rose-50/80', border: 'border-rose-100/50' },
  asmr_sync: { icon: RefreshCw, color: 'text-indigo-600', bg: 'bg-indigo-50/80', border: 'border-indigo-100/50' },
  circle_completion: { icon: Users, color: 'text-blue-600', bg: 'bg-blue-50/80', border: 'border-blue-100/50' },
  default: { icon: Tag, color: 'text-slate-600', bg: 'bg-slate-50/80', border: 'border-slate-100/50' }
}

const statusConfigs = {
  success: { icon: CheckCircle2, color: 'text-emerald-600', bg: 'bg-emerald-50/80', border: 'border-emerald-100/50', label: '成功' },
  partial_success: { icon: AlertCircle, color: 'text-amber-600', bg: 'bg-amber-50/80', border: 'border-amber-100/50', label: '部分成功' },
  failed: { icon: XCircle, color: 'text-rose-600', bg: 'bg-rose-50/80', border: 'border-rose-100/50', label: '失败' },
  cancelled: { icon: MinusCircle, color: 'text-slate-400', bg: 'bg-slate-50/80', border: 'border-slate-100/50', label: '已取消' },
  waiting: { icon: Clock, color: 'text-indigo-500', bg: 'bg-indigo-50/80', border: 'border-indigo-100/50', label: '等待' },
  incomplete: { icon: PlayCircle, color: 'text-slate-500', bg: 'bg-slate-50/80', border: 'border-slate-100/50', label: '未完成' },
  default: { icon: MinusCircle, color: 'text-slate-400', bg: 'bg-slate-50/80', border: 'border-slate-100/50', label: '—' }
}

function getCategoryConfig(c) {
  return categoryConfigs[c] || categoryConfigs.default
}

function getStatusConfig(s) {
  return statusConfigs[s] || statusConfigs.default
}

function statusLabel(status) {
  return getStatusConfig(status).label || '—'
}

const items = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(30)
const detailDialogVisible = ref(false)
const selectedRow = ref(null)
const circleRefreshFilter = ref('all')
const circleRefreshPage = ref(1)
const statsDays = ref(14)
const expandedTreeRowIds = ref(new Set())
const selectedBatchWorkbenchKeys = ref([])
const batchWorkbenchAwaitingOnly = ref(false)
const collapsedEntrySectionKeys = ref(new Set())
const collapsedEntryTreeRowKeys = ref(new Set())
const compareSearchQuery = ref('')
const compareSourceFilter = ref('all')
const compareExpanded = ref(true)
const lastLoadedAt = ref(0)
const ACTIVITY_AUTO_REFRESH_STALE_MS = 3 * 60 * 1000
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
  { value: 'asmr_sync', label: 'ASMR 同步' },
  { value: 'circle_completion', label: '社团补全' }
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

const selectedCircleCompletionIndexModel = computed(() => circleCompletionIndexModel(selectedRow.value))
const selectedCircleCompletionRefreshModel = computed(() => circleCompletionRefreshModel(selectedRow.value))
const filteredCircleIndexRows = computed(() => {
  const rows = Array.isArray(selectedCircleCompletionIndexModel.value?.rows) ? selectedCircleCompletionIndexModel.value.rows : []
  const query = String(compareSearchQuery.value || '').trim().toLowerCase()
  return rows.filter((item) => {
    const sourceMatch = compareSourceFilter.value === 'all'
      || (compareSourceFilter.value === 'kikoeru' && item?.sourceCompare?.kikoeru?.primary_rjcode)
      || (compareSourceFilter.value === 'dlsite' && Array.isArray(item?.sourceCompare?.dlsite?.all_rjcodes) && item.sourceCompare.dlsite.all_rjcodes.length)
      || (compareSourceFilter.value === 'asmr_one' && item?.sourceCompare?.asmr_one?.primary_rjcode)
      || (compareSourceFilter.value === 'missing' && !item?.sourceCompare?.kikoeru?.primary_rjcode && !(Array.isArray(item?.sourceCompare?.dlsite?.all_rjcodes) && item.sourceCompare.dlsite.all_rjcodes.length) && !item?.sourceCompare?.asmr_one?.primary_rjcode)
    if (!sourceMatch) return false
    if (!query) return true
    const haystack = [
      item?.title,
      item?.workRjcode,
      item?.display_rjcode,
      item?.preferred_variant_label,
      item?.sourceCompare?.kikoeru?.primary_rjcode,
      ...(Array.isArray(item?.sourceCompare?.dlsite?.all_rjcodes) ? item.sourceCompare.dlsite.all_rjcodes : []),
      item?.sourceCompare?.asmr_one?.primary_rjcode,
    ].map((value) => String(value || '').toLowerCase())
    return haystack.some((value) => value.includes(query))
  })
})
const circleIndexSummaryText = computed(() => {
  const model = selectedCircleCompletionIndexModel.value
  const total = Array.isArray(model?.rows) ? model.rows.length : 0
  const visible = filteredCircleIndexRows.value.length
  if (!model) return ''
  const breakdown = Array.isArray(model.sourceBreakdown) ? model.sourceBreakdown : []
  const sourceText = breakdown
    .filter((item) => Number(item.count || 0) > 0)
    .map((item) => `${item.label} ${item.count}`)
    .join(' · ')
  const scopeText = visible === total ? `共 ${total} 项作品` : `共 ${total} 项作品，当前筛出 ${visible} 项`
  return sourceText ? `${scopeText} · ${sourceText}` : scopeText
})
const circleRefreshPageSize = 10
const pagedCircleCompletionRefreshItems = computed(() => {
  const rows = Array.isArray(selectedCircleCompletionRefreshModel.value?.items) ? selectedCircleCompletionRefreshModel.value.items : []
  const start = (circleRefreshPage.value - 1) * circleRefreshPageSize
  return rows.slice(start, start + circleRefreshPageSize)
})

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

function flattenActivityRows(sourceRows, out = []) {
  for (const row of sourceRows || []) {
    if (!row || typeof row !== 'object') continue
    out.push(row)
    const detail = row.detail && typeof row.detail === 'object' ? row.detail : {}
    const childRows = Array.isArray(detail.child_rows) ? detail.child_rows : []
    if (childRows.length) flattenActivityRows(childRows, out)
  }
  return out
}

function recoveredMatchKey(row) {
  if (!row) return ''
  const rj = displayRjcode(row)
  if (rj && rj !== '—') return `rj:${rj}`
  const detail = row.detail && typeof row.detail === 'object' ? row.detail : {}
  const sourcePath = String(row.source_path || detail.archive_path || detail.source_path || '').trim().toLowerCase()
  return sourcePath ? `path:${sourcePath}` : ''
}

function isRecoveredFailure(row) {
  if (!row || row.status !== 'failed') return false
  if (!['extract', 'auto_import', 'process_existing', 'asmr_sync'].includes(String(row.category || '').trim())) return false
  if (row?.detail?.recovered_by_success) return true
  const key = recoveredMatchKey(row)
  if (!key) return false
  const allRows = flattenActivityRows(items.value)
  return allRows.some((other) => {
    if (!other || other === row) return false
    if (!['success', 'partial_success'].includes(String(other.status || '').trim())) return false
    if (!['extract', 'auto_import', 'process_existing', 'asmr_sync'].includes(String(other.category || '').trim())) return false
    if (recoveredMatchKey(other) !== key) return false
    if (!other.created_at || !row.created_at) return false
    return other.created_at > row.created_at
  })
}

function isRerunRow(row) {
  return Boolean(row?.rerun || row?.detail?.rerun_linked || Number(row?.detail?.rerun_count || 0) > 0)
}

function filterDeleteRetryStatus(row) {
  return String(row?.detail?.repair_status || row?.detail?.retry_status || '').trim()
}

function isFilterDeleteRetriedSuccess(row) {
  return filterDeleteRetryStatus(row) === 'success'
}

function isFilterDeleteRetriedPartial(row) {
  return filterDeleteRetryStatus(row) === 'partial_success'
}

function isFilterDeleteRetriedFailed(row) {
  return filterDeleteRetryStatus(row) === 'failed'
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
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const sourceAction = String(row?.source_action || detail.source_action || '').trim()
  const isReimportTask = sourceAction === 'reimport_local_download_root' || sourceAction === 'reimport_downloaded_session'
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
    if (row.relation === 'retry_apply') {
      if (row.status === 'success') return '补充删除完成'
      if (row.status === 'partial_success') return '补充删除部分成功'
      if (row.status === 'cancelled') return '补充删除已停止'
      if (row.status === 'failed') return '补充删除失败'
      return '补充删除'
    }
    if (row.relation === 'retry_preview' || row.action === 'filter_delete_preview_retry') {
      if (row.status === 'success') return '补充删除完成'
      if (row.status === 'partial_success') return '补充删除部分成功'
      if (row.status === 'failed') return '补充删除失败'
      return '补充删除'
    }
    if (row.relation === 'asmr_resource') {
      return row.status === 'success' ? '文件下载完成' : '文件下载'
    }
    if (row.relation === 'asmr_upload') {
      return row.status === 'success' ? '文件上传完成' : '文件上传'
    }
    if (row.relation === 'asmr_verify_failed') {
      return '文件校验失败'
    }
    if (row.relation === 'asmr_plan') {
      return '下载计划已生成'
    }
    if (row.relation === 'asmr_session') {
      return displaySummary(row) || '下载会话'
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
    if (status === 'partial_success') return '解压入库部分成功'
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
    if (action === 'batch_manual_rename') {
      if (status === 'success') return '批量乱码修复完成'
      if (status === 'partial_success') return '批量乱码修复部分成功'
      if (status === 'failed') return '批量乱码修复失败'
      return '批量乱码修复'
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
    if (isReimportTask) {
      if (action === 'task_retried') return '直接入库任务已创建'
      if (action === 'session_started') return '直接入库任务开始'
      if (action === 'session_partial_failed') return '直接入库部分失败'
      if (action === 'session_completed') return '直接入库完成'
      if (status === 'success') return '直接入库完成'
      if (status === 'failed') return '直接入库失败'
    }
    if (action === 'enhanced_plan_created') return '增强下载计划已生成'
    if (action === 'enhanced_plan_failed') return '增强下载计划生成失败'
    if (action === 'session_started') return 'ASMR 下载任务开始'
    if (action === 'session_partial_failed') return 'ASMR 下载任务部分失败'
    if (action === 'session_completed') return 'ASMR 下载任务完成'
    if (status === 'success') return 'ASMR 同步下载完成'
    if (status === 'failed') return 'ASMR 同步下载失败'
  }
  if (category === 'circle_completion') {
    if (action === 'index_completed') return status === 'success' ? '创建索引检索成功' : '创建索引检索失败'
    if (action === 'index_failed') return '创建索引检索失败'
    if (action === 'refresh_selected_works') return status === 'success' ? '社团作品信息更新' : '社团作品信息更新失败'
    if (action === 'download_batch_start') return '创建下载任务'
    if (action === 'download_item_queued') return '下载任务已加入队列'
    if (action === 'task_finished' || action === 'task_finished_incomplete') {
      if (sourceAction === 'refresh_selected') {
        if (status === 'success') return '社团作品信息更新完成'
        if (status === 'incomplete') return '社团作品信息更新未正常结束'
        if (status === 'failed') return '社团作品信息更新失败'
        return '社团作品信息更新'
      }
      if (sourceAction === 'index_circle' || sourceAction === 'circle_index') {
        if (status === 'success') return '社团补全完成'
        if (status === 'incomplete') return '社团补全未正常结束'
        if (status === 'failed') return '社团补全失败'
        return '社团补全'
      }
    }
    if (status === 'success') return '社团补全完成'
    if (status === 'failed') return '社团补全失败'
  }

  // 回退：用中文状态 + 英文动作描述
  if (status === 'waiting' && (action === 'task_finished' || action === 'task_finished_incomplete')) {
    return '等待处理'
  }
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

function batchPairRollup(row) {
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const pairedChildCount = Math.max(0, Number(detail.paired_child_count || 0))
  const awaitingManualChildCount = Math.max(0, Number(detail.awaiting_manual_child_count || 0))
  const unpairedChildCount = Math.max(0, Number(detail.unpaired_child_count || 0))
  const totalTrackedCount = Math.max(pairedChildCount + unpairedChildCount, Number(detail.child_row_count || 0))
  const fullyPaired = pairedChildCount > 0 && awaitingManualChildCount <= 0 && unpairedChildCount <= 0
  const partiallyPaired = pairedChildCount > 0 && !fullyPaired
  return {
    pairedChildCount,
    awaitingManualChildCount,
    unpairedChildCount,
    totalTrackedCount,
    fullyPaired,
    partiallyPaired
  }
}

function isSubtitleBatchRootRow(row) {
  return Boolean(row && !row.is_tree_child && row.category === 'subtitle_crawl' && row.action === 'batch_start')
}

function isSubtitleBatchRootPaired(row) {
  if (!isSubtitleBatchRootRow(row)) return false
  return batchPairRollup(row).fullyPaired
}

function isSubtitleBatchRootPartiallyPaired(row) {
  if (!isSubtitleBatchRootRow(row)) return false
  return batchPairRollup(row).partiallyPaired
}

function isPairCompletedRow(row) {
  if (!row) return false
  if (row?.category === 'subtitle_pair' && row?.status === 'success') return true
  if (row?.category === 'subtitle_crawl' && hasMergedPair(row) && String(row?.merged_pair_status || row?.detail?.pair_status || '') === 'success') {
    return true
  }
  if (isSubtitleBatchRootPaired(row)) return true
  return isBatchChildPaired(row)
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

function pairDetailRow(row) {
  if (!row) return null
  if (row.category === 'subtitle_pair') return row
  return latestPairRow(row)
}

function isSubtitlePairRelatedRow(row) {
  if (!row) return false
  if (['subtitle_crawl', 'subtitle_pair'].includes(String(row.category || ''))) return true
  if (['pair', 'subtitle_import'].includes(String(row.relation || ''))) return true
  return Boolean(pairDetailRow(row))
}

function pairDetailPayload(row) {
  const sourceRow = pairDetailRow(row)
  if (sourceRow?.detail && typeof sourceRow.detail === 'object') return sourceRow.detail
  if (row?.detail && typeof row.detail === 'object') return row.detail
  return {}
}

function resolveSubtitleTaskId(row) {
  const pairRow = pairDetailRow(row)
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const pairDetail = pairRow?.detail && typeof pairRow.detail === 'object' ? pairRow.detail : {}
  const candidates = [
    row?.task_id,
    detail.task_id,
    pairRow?.task_id,
    pairDetail.task_id
  ]
  for (const candidate of candidates) {
    const value = String(candidate || '').trim()
    if (value) return value
  }
  return ''
}

function resolveSubtitleFolderPath(row) {
  const pairRow = pairDetailRow(row)
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const pairDetail = pairRow?.detail && typeof pairRow.detail === 'object' ? pairRow.detail : {}
  const candidates = [
    detail.folder_path,
    pairDetail.folder_path,
    row?.source_path,
    pairRow?.source_path
  ]
  for (const candidate of candidates) {
    const value = String(candidate || '').trim()
    if (value) return value
  }
  return ''
}

function resolveSubtitleLibraryId(row) {
  const pairRow = pairDetailRow(row)
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const pairDetail = pairRow?.detail && typeof pairRow.detail === 'object' ? pairRow.detail : {}
  const candidates = [
    detail.library_id,
    detail.subtitle_library_id,
    pairDetail.library_id,
    pairDetail.subtitle_library_id
  ]
  for (const candidate of candidates) {
    const value = String(candidate || '').trim()
    if (value) return value
  }
  return ''
}

function unmatchedAudioCount(row) {
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const pairDetail = pairDetailPayload(row)
  const summary = String(row?.summary || '').trim()
  const pairSummary = pairSummaryText(row)
  const matchResult = detail.match_result && typeof detail.match_result === 'object' ? detail.match_result : {}
  const pairMatchResult = pairDetail.match_result && typeof pairDetail.match_result === 'object' ? pairDetail.match_result : {}
  const directCount = [
    detail.unmatched_audio_count,
    pairDetail.unmatched_audio_count,
    Array.isArray(matchResult.unmatched_audio) ? matchResult.unmatched_audio.length : null,
    Array.isArray(pairMatchResult.unmatched_audio) ? pairMatchResult.unmatched_audio.length : null
  ].find(value => Number.isFinite(Number(value)))
  if (Number.isFinite(Number(directCount))) return Number(directCount)
  const matched = `${summary} ${pairSummary}`.match(/未匹配音频\s*(\d+)/)
  return matched ? Number(matched[1] || 0) : 0
}

function isManualPairCompleted(row) {
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const pairDetail = pairDetailPayload(row)
  return Boolean(
    detail.manual_match_completed
    || pairDetail.manual_match_completed
    || (pairDetailRow(row)?.status === 'success')
  )
}

function isAwaitingManualPair(row) {
  if (!row) return false
  if (isManualPairCompleted(row)) return false
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const pairDetail = pairDetailPayload(row)
  if (detail.awaiting_manual_match || pairDetail.awaiting_manual_match) return true
  if (row.category === 'subtitle_crawl' && unmatchedAudioCount(row) > 0) return true
  return false
}

function pairWorkbenchModel(row) {
  if (isSubtitleBatchRootRow(row)) return null
  if (!isSubtitlePairRelatedRow(row)) return null
  const taskId = resolveSubtitleTaskId(row)
  const folderPath = resolveSubtitleFolderPath(row)
  if (!taskId && !folderPath) return null
  const awaiting = isAwaitingManualPair(row)
  const chips = []
  const unmatchedCount = unmatchedAudioCount(row)
  const downloadedCount = Number(row?.detail?.downloaded_count || pairDetailPayload(row)?.downloaded_count || 0)
  const writtenCount = Number(row?.detail?.written_files_count || pairDetailPayload(row)?.written_files_count || 0)
  if (displayRjcode(row) && displayRjcode(row) !== '—') chips.push(displayRjcode(row))
  if (downloadedCount > 0) chips.push(`抓到 ${downloadedCount}`)
  if (writtenCount > 0) chips.push(`写入 ${writtenCount}`)
  if (unmatchedCount > 0) chips.push(`未配对音频 ${unmatchedCount}`)
  return {
    awaiting,
    title: awaiting ? '这条记录还有字幕没完成配对' : '这条记录可回到字幕工作台查看',
    description: awaiting
      ? '直接打开库存里的字幕配对面板，继续处理还没来得及配对的音频和字幕。'
      : '会定位到对应字幕任务，方便复查当前配对状态和字幕目录。',
    buttonText: awaiting ? '继续配对' : '打开配对面板',
    chips
  }
}

function pairResultModel(row) {
  if (!row) return null
  if (isSubtitleBatchRootRow(row)) return null
  if (!isSubtitlePairRelatedRow(row)) return null
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const pairRow = pairDetailRow(row)
  const pairDetail = pairDetailPayload(row)
  const changes = pairChangeRows(pairRow || row)
  const appliedPairs = Number(
    pairDetail.applied_pairs
    ?? pairDetail.manual_match_applied_pairs
    ?? detail.applied_pairs
    ?? detail.manual_match_applied_pairs
    ?? changes.length
    ?? 0
  )
  const deletedSubtitles = Number(
    pairDetail.deleted_subtitles
    ?? pairDetail.manual_match_deleted_subtitles
    ?? detail.deleted_subtitles
    ?? detail.manual_match_deleted_subtitles
    ?? 0
  )
  const unmatchedCount = unmatchedAudioCount(row)
  const namingStrategy = String(pairDetail.naming_strategy || detail.naming_strategy || '').trim()
  const downloadedCount = Number(detail.downloaded_count || pairDetail.downloaded_count || 0)
  const writtenCount = Number(detail.written_files_count || pairDetail.written_files_count || 0)
  const summary = pairSummaryText(row) || String(row?.summary || '').trim()
  const hasData = Boolean(summary || changes.length || appliedPairs || deletedSubtitles || downloadedCount || writtenCount || unmatchedCount)
  if (!hasData) return null
  const awaiting = isAwaitingManualPair(row)
  const completed = isManualPairCompleted(row)
  const status = completed ? 'success' : (awaiting ? 'warning' : 'default')
  const statusLabel = completed ? '已完成配对' : (awaiting ? '待手动配对' : '已抓取未继续')
  const metrics = [
    { label: '已配对', value: `${Math.max(0, appliedPairs)} 组` },
    { label: '未配对音频', value: `${Math.max(0, unmatchedCount)} 个` },
    { label: '删除字幕', value: `${Math.max(0, deletedSubtitles)} 个` },
    { label: '抓取字幕', value: `${Math.max(0, downloadedCount)} 个` }
  ]
  if (writtenCount > 0) metrics.push({ label: '写入字幕', value: `${writtenCount} 个` })
  if (namingStrategy) metrics.push({ label: '命名策略', value: namingStrategy === 'audio' ? '按音频名' : namingStrategy })
  return {
    title: completed ? '字幕配对已落地' : '字幕配对状态',
    status,
    statusLabel,
    summary,
    metrics,
    changes
  }
}

async function openSubtitlePairWorkbench(row) {
  if (isSubtitleBatchRootRow(row)) {
    ElMessage.warning('批量根记录请使用下面的批量工作台入口')
    return
  }
  if (!isSubtitlePairRelatedRow(row)) {
    ElMessage.warning('这条记录不是字幕配对链路')
    return
  }
  const taskId = resolveSubtitleTaskId(row)
  const folderPath = resolveSubtitleFolderPath(row)
  const libraryId = resolveSubtitleLibraryId(row)
  const rjcode = displayRjcode(row)
  if (!taskId && !folderPath) {
    ElMessage.warning('这条记录没有可定位的字幕任务或目录')
    return
  }
  await router.push({
    path: '/library',
    query: {
      subtitleDialog: '1',
      ...(taskId ? { subtitleTaskId: taskId } : {}),
      ...(folderPath ? { subtitleFolderPath: folderPath } : {}),
      ...(libraryId ? { subtitleLibraryId: libraryId } : {}),
      ...(rjcode && rjcode !== '—' ? { subtitleRjcode: rjcode } : {})
    }
  })
}

function subtitleBatchWorkbenchItems(row) {
  if (!isSubtitleBatchRootRow(row)) return []
  return collectChildRowsFromParent(row)
    .filter((item) => String(item?.category || '').trim() === 'subtitle_crawl')
    .map((item) => {
      const key = String(item?.id || item?.task_id || item?.source_path || '')
      const paired = isPairCompletedRow(item)
      const awaiting = isAwaitingManualPair(item)
      return {
        key,
        taskId: resolveSubtitleTaskId(item),
        folderPath: resolveSubtitleFolderPath(item),
        libraryId: resolveSubtitleLibraryId(item),
        rjcode: displayRjcode(item),
        folderName: String(item?.detail?.folder_name || '').trim() || compactPath(item?.source_path || ''),
        summary: displaySummary(item),
        stateLabel: paired ? '配对✔' : (awaiting ? '待配对' : '已抓取'),
        stateClass: paired ? 'success' : (awaiting ? 'warning' : 'default')
      }
    })
    .filter((item) => item.key && (item.taskId || item.folderPath))
}

function subtitleBatchWorkbenchModel(row) {
  if (!isSubtitleBatchRootRow(row)) return null
  const items = subtitleBatchWorkbenchItems(row)
  if (!items.length) return null
  return {
    items,
    pairedCount: items.filter((item) => item.stateClass === 'success').length,
    awaitingCount: items.filter((item) => item.stateClass === 'warning').length
  }
}

function visibleBatchWorkbenchItems(row) {
  const items = subtitleBatchWorkbenchItems(row)
  if (!batchWorkbenchAwaitingOnly.value) return items
  return items.filter((item) => item.stateClass === 'warning')
}

function syncBatchWorkbenchSelection(row) {
  const items = subtitleBatchWorkbenchItems(row)
  const validKeys = new Set(items.map((item) => item.key))
  const next = selectedBatchWorkbenchKeys.value.filter((key) => validKeys.has(key))
  if (next.length) {
    selectedBatchWorkbenchKeys.value = next
    return
  }
  selectedBatchWorkbenchKeys.value = items.map((item) => item.key)
}

function selectedBatchWorkbenchItems(row) {
  const selectedKeys = new Set(selectedBatchWorkbenchKeys.value)
  return subtitleBatchWorkbenchItems(row).filter((item) => selectedKeys.has(item.key))
}

function isAllBatchWorkbenchItemsSelected(row) {
  const items = visibleBatchWorkbenchItems(row)
  if (!items.length) return false
  const selectedKeys = new Set(selectedBatchWorkbenchKeys.value)
  return items.every((item) => selectedKeys.has(item.key))
}

function toggleAllBatchWorkbenchItems(row, checked) {
  const items = visibleBatchWorkbenchItems(row)
  selectedBatchWorkbenchKeys.value = checked ? items.map((item) => item.key) : []
}

function selectAwaitingBatchWorkbenchItems(row) {
  const items = subtitleBatchWorkbenchItems(row).filter((item) => item.stateClass === 'warning')
  selectedBatchWorkbenchKeys.value = items.map((item) => item.key)
}

async function openSubtitleBatchWorkbench(row) {
  const pickedItems = selectedBatchWorkbenchItems(row)
  if (!pickedItems.length) {
    ElMessage.warning('先勾选至少一个 RJ')
    return
  }
  try {
    localStorage.setItem('activity-history-subtitle-batch-selection', JSON.stringify({
      items: pickedItems.map((item) => ({
        task_id: item.taskId || '',
        library_id: item.libraryId || '',
        folder_path: item.folderPath || '',
        folder_name: item.folderName || '',
        rjcode: item.rjcode || '',
        queue_message: item.summary || ''
      })),
      preferred_key: `${pickedItems[0]?.libraryId || ''}::${String(pickedItems[0]?.folderPath || '').replace(/\\/g, '/')}`
    }))
  } catch (_) {}
  await router.push({
    path: '/library',
    query: {
      subtitleBatchSelection: '1'
    }
  })
}

function mergedSubtitleImportTag(row) {
  const status = String(row?.detail?.import_status || row?.merged_subtitle_import_status || '')
  if (status === 'success') return '配对✔'
  if (status === 'failed') return '补配失败'
  return '字幕补配'
}

function mergedFilterDeleteTag(row) {
  const status = String(row?.status || '')
  if (status === 'success') return '删除✔'
  if (status === 'partial_success') return '部分删除✔'
  if (status === 'cancelled') return '已停止'
  if (status === 'failed') return '删除失败'
  return '删除✔'
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
  if (hasMergedSubtitleImport(row)) tags.push(mergedSubtitleImportTag(row))
  if (isSubtitleBatchMiss(row)) tags.push('未命中')
  if (isFilterDeleteRetriedSuccess(row)) tags.push('已修复')
  else if (isFilterDeleteRetriedPartial(row)) tags.push('部分修复')
  else if (isFilterDeleteRetriedFailed(row)) tags.push('未修复')
  return tags
}

function rowCategoryTags(row) {
  const tags = row?.is_tree_child ? [] : mergedCategoryTags(row)
  if (!row?.is_tree_child && row?.category === 'circle_completion' && row?.action === 'refresh_selected_works') {
    const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
    tags.push(Number(detail?.changed_count || 0) > 0 ? '有更新' : '无变化')
  }
  if (row?.category === 'pipeline_rename') tags.unshift(renameOpTag(row))
  if (!row?.is_tree_child && isSubtitleBatchRootPartiallyPaired(row)) tags.push('部分配对✔')
  if (!row?.is_tree_child && row?.category === 'subtitle_crawl' && isPairCompletedRow(row)) tags.push('配对✔')
  else if (isBatchChildPaired(row)) tags.push('配对✔')
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
  if (row?.category === 'pipeline_rename' && row?.action === 'batch_manual_rename') {
    const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
    const successCount = Number(detail.success_count || 0)
    const failedCount = Number(detail.failed_count || 0)
    return `修复 ${successCount} 项，失败 ${failedCount} 项`
  }
  if (isSubtitleBatchRootRow(row)) {
    const rollup = batchPairRollup(row)
    const base = String(row?.summary || '—').trim() || '—'
    if (rollup.pairedChildCount > 0) {
      return `${base}，后续已完成 ${rollup.pairedChildCount} 项配对，剩余 ${Math.max(0, rollup.awaitingManualChildCount || rollup.unpairedChildCount)} 项待处理`
    }
    return base
  }
  if (isPairCompletedRow(row)) return pairSummaryText(row) || row?.summary || '—'
  if (row?.category === 'subtitle_import' || row?.relation === 'subtitle_import') {
    const base = String(row?.summary || '—').trim() || '—'
    const suffix = subtitleImportSourceSuffix(row)
    if (suffix && !base.includes(`来源于 ${String(row?.detail?.source_rjcode || row?.detail?.preview_source_rjcode || '').trim().toUpperCase()}`)) {
      return `${base}${suffix}`
    }
    return base
  }
  if (row?.category === 'pipeline_filter') {
    const rjcode = displayRjcode(row)
    const base = String(row?.summary || '—').trim() || '—'
    if (rjcode && rjcode !== '—' && base.includes('未知RJ')) {
      return base.replace(/未知RJ号?|未知RJ/gi, rjcode)
    }
    return base
  }
  if (row?.category === 'circle_completion') {
    return String(row?.summary || '—').trim() || '—'
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
  if (tag === '有更新') return 'is-updated'
  if (tag === '无变化') return 'is-unchanged'
  return ''
}

function rowClassName({ row }) {
  if (!row) return ''
  const cls = []
  if (row.is_tree_child) cls.push('activity-row-child')
  if (row.is_tree_child && Number(row.tree_depth || 0) >= 2) cls.push('activity-row-grandchild')
  if (row.status) cls.push(`row-status-${row.status}`)
  if (isRecoveredFailure(row)) cls.push('row-recovered')
  cls.push('activity-row')
  return cls.join(' ')
}

function openDetail(row) {
  selectedRow.value = row || null
  circleRefreshFilter.value = 'all'
  circleRefreshPage.value = 1
  syncBatchWorkbenchSelection(row)
  detailDialogVisible.value = true
}

function setCircleRefreshFilter(value) {
  circleRefreshFilter.value = String(value || 'all')
  circleRefreshPage.value = 1
}

function setCircleRefreshPage(nextPage) {
  circleRefreshPage.value = Math.max(1, Number(nextPage || 1))
}

function treeRowId(row) {
  return String(row?.id || '')
}

function resolveActivityTableRowKey(row) {
  if (!row || typeof row !== 'object') return ''
  const baseId = String(row.id || '')
  if (row.is_tree_child) {
    return [
      'child',
      String(row.parent_id || row.parent_row?.id || ''),
      String(row.relation || row.category || ''),
      String(row.tree_depth || 0),
      baseId,
      String(row.task_id || ''),
      String(row.source_path || ''),
    ].join(':')
  }
  return ['parent', baseId, String(row.category || ''), String(row.task_id || '')].join(':')
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

function isAsmrDownloadChildRow(row) {
  return Boolean(row?.is_tree_child && row?.relation === 'asmr_resource')
}

function isAsmrUploadChildRow(row) {
  return Boolean(row?.is_tree_child && row?.relation === 'asmr_upload')
}

function normalizeAsmrFileKeySegment(value) {
  const raw = String(value || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '')
  if (!raw) return []
  const normalized = raw.toLowerCase()
  const baseName = normalized.split('/').filter(Boolean).pop() || ''
  return [...new Set([normalized, baseName].filter(Boolean))]
}

function extractAsmrSummaryResourceName(summary) {
  const text = String(summary || '').trim()
  if (!text) return ''
  const slashIndex = text.indexOf('/')
  if (slashIndex >= 0) {
    return text
      .slice(slashIndex + 1)
      .replace(/\s+(已上传|下载完成|上传完成|上传失败|下载失败).*$/u, '')
      .trim()
  }
  return text
    .replace(/^(文件下载完成|文件上传完成|文件下载|文件上传)\s*/u, '')
    .replace(/\s+(已上传|下载完成|上传完成|上传失败|下载失败).*$/u, '')
    .trim()
}

function collectAsmrRowMatchKeys(row) {
  const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {}
  const values = [
    detail.resource_path,
    detail.relative_path,
    detail.resource_name,
    detail.upload_path,
    detail.target_path,
    row?.source_path,
    extractAsmrSummaryResourceName(row?.summary)
  ]
  return [...new Set(values.flatMap(normalizeAsmrFileKeySegment))]
}

function buildAsmrUploadMatchMap(children) {
  const map = new Map()
  for (const child of children || []) {
    if (!isAsmrUploadChildRow({ ...child, is_tree_child: true })) continue
    const createdAt = String(child?.created_at || '')
    for (const key of collectAsmrRowMatchKeys(child)) {
      const previous = map.get(key)
      if (!previous || createdAt >= String(previous?.created_at || '')) {
        map.set(key, child)
      }
    }
  }
  return map
}

function findMergedAsmrUploadRow(downloadRow, uploadMap) {
  if (!isAsmrDownloadChildRow(downloadRow)) return null
  for (const key of collectAsmrRowMatchKeys(downloadRow)) {
    const matched = uploadMap.get(key)
    if (matched) return matched
  }
  return null
}

function buildChildDisplayRows(parentRow, children = null, depth = 1) {
  const sourceChildren = Array.isArray(children)
    ? children
    : collectChildRowsFromParent(parentRow)
  if (!isTreeRowExpanded(parentRow)) return []
  const rows = []
  const asmrUploadMap = buildAsmrUploadMatchMap(sourceChildren)
  for (const child of sourceChildren) {
    const childSeed = {
      ...child,
      is_tree_child: true
    }
    if (isAsmrUploadChildRow(childSeed)) {
      continue
    }
    const mergedUploadRow = findMergedAsmrUploadRow(childSeed, asmrUploadMap)
    const childRow = {
      ...child,
      parent_id: parentRow.id,
      parent_row: parentRow,
      is_tree_child: true,
      tree_depth: depth,
      merged_upload_row: mergedUploadRow,
    }
    rows.push(childRow)
    rows.push(...buildChildDisplayRows(childRow, null, depth + 1))
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
  if (row?.relation === 'retry_apply') return '补充删除'
  if (row?.relation === 'retry_preview') return '补充删除'
  if (row?.action === 'filter_delete_preview_retry') return '补充删除'
  if (row?.relation === 'download_batch') return '下载任务'
  if (row?.relation === 'asmr_resource') return '下载文件'
  if (row?.relation === 'asmr_upload') return '上传文件'
  if (row?.relation === 'asmr_verify_failed') return '校验失败'
  if (row?.relation === 'asmr_plan') return '下载计划'
  if (row?.relation === 'asmr_session') return '下载过程'
  return row?.category_label || row?.category || '子任务'
}

function showAsmrUploadBadge(row) {
  if (!isAsmrDownloadChildRow(row)) return false
  return String(row?.merged_upload_row?.status || '').trim() === 'success'
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
  if (isSubtitleBatchRootPaired(row)) return '配对✔'
  if (isSubtitleBatchRootPartiallyPaired(row)) return '部分配对✔'
  if (row?.category === 'pipeline_filter' && row?.action === 'filter_delete_preview') {
    if (isFilterDeleteRetriedSuccess(row)) return '删除✔'
    if (isFilterDeleteRetriedPartial(row)) return '部分删除✔'
    if (isFilterDeleteRetriedFailed(row)) return '未修复'
  }
  if (row?.category === 'subtitle_crawl' && isPairCompletedRow(row)) return '配对✔'
  const statuses = [String(row.status || ''), ...collectDescendantStatuses(row)]
  if (statuses[0] === 'failed' && (statuses.includes('success') || statuses.includes('partial_success'))) return '已修复✔'
  if (statuses.includes('failed') && !statuses.includes('success') && !statuses.includes('partial_success')) return '异常'
  if (!statuses.includes('waiting')) {
    if (row?.category === 'subtitle_crawl') return '配对✔'
    if (row?.category === 'pipeline_filter') return '删除✔'
    if (row?.category === 'subtitle_import') return '配对✔'
    if (['extract', 'auto_import', 'process_existing'].includes(String(row?.category || ''))) return '入库✔'
    return '完成✔'
  }
  return ''
}

function finalStatusClass(row) {
  const label = finalStatusLabel(row)
  if (label === '配对✔') return 'is-final-success'
  if (label === '删除✔') return 'is-final-success'
  if (label === '入库✔') return 'is-final-success'
  if (label === '完成✔') return 'is-final-success'
  if (label === '已修复✔') return 'is-final-success'
  if (label === '部分配对') return 'is-final-partial'
  if (label === '部分删除') return 'is-final-partial'
  if (label === '部分修复') return 'is-final-partial'
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
  if (row?.relation === 'retry_apply') return 'is-filter-retry'
  if (row?.category === 'subtitle_crawl') return 'is-crawl'
  if (row?.relation === 'retry_preview') return 'is-filter-retry'
  if (row?.action === 'filter_delete_preview_retry') return 'is-filter-retry'
  return 'is-default'
}

function circleCompletionIndexModel(row) {
  if (!row || row.category !== 'circle_completion' || row.action !== 'index_completed') return null
  const detail = row.detail && typeof row.detail === 'object' ? row.detail : {}
  const sourceBreakdown = Array.isArray(detail.source_breakdown)
    ? detail.source_breakdown
        .map(item => ({
          key: String(item?.key || '').trim(),
          label: String(item?.label || item?.key || '未命名'),
          count: Number(item?.count || 0)
        }))
        .filter(item => item.key)
    : []
  const workSections = Array.isArray(detail.work_sections)
    ? detail.work_sections
        .map(section => ({
          key: String(section?.key || '').trim(),
          count: Number(section?.count || 0),
          rows: Array.isArray(section?.rows)
            ? section.rows.map(item => ({
                canonical_rjcode: String(item?.canonical_rjcode || '').trim(),
                workRjcode: String(item?.work_rjcode || item?.canonical_rjcode || '').trim(),
                display_rjcode: String(item?.display_rjcode || '').trim(),
                title: String(item?.title || '').trim(),
                preferred_variant_label: String(item?.preferred_variant_label || '').trim(),
                statusLabel: String(item?.status_label || '').trim() || '未标记',
                statusKey: String(item?.status_key || '').trim() || 'unknown',
                sourceCompare: {
                  kikoeru: {
                    primary_rjcode: String(item?.source_compare?.kikoeru?.primary_rjcode || '').trim(),
                    primaryBadge: String(item?.source_compare?.kikoeru?.primary_badge || '').trim(),
                    variantBadges: Array.isArray(item?.source_compare?.kikoeru?.variant_badges) && item.source_compare.kikoeru.variant_badges.length
                      ? item.source_compare.kikoeru.variant_badges.filter(Boolean)
                      : (String(item?.source_compare?.kikoeru?.primary_badge || '').trim() ? [String(item.source_compare.kikoeru.primary_badge).trim()] : []),
                    all_rjcodes: Array.isArray(item?.source_compare?.kikoeru?.all_rjcodes) ? item.source_compare.kikoeru.all_rjcodes.filter(Boolean) : [],
                    tags: Array.isArray(item?.source_compare?.kikoeru?.tags) ? item.source_compare.kikoeru.tags.filter(Boolean) : [],
                  },
                  dlsite: {
                    all_rjcodes: Array.isArray(item?.source_compare?.dlsite?.all_rjcodes) ? item.source_compare.dlsite.all_rjcodes.filter(Boolean) : [],
                  },
                  asmr_one: {
                    primary_rjcode: String(item?.source_compare?.asmr_one?.primary_rjcode || '').trim(),
                    primaryBadge: String(item?.source_compare?.asmr_one?.primary_badge || '').trim(),
                    all_rjcodes: Array.isArray(item?.source_compare?.asmr_one?.all_rjcodes) ? item.source_compare.asmr_one.all_rjcodes.filter(Boolean) : [],
                  }
                }
              }))
            : []
        }))
        .filter(section => section.key && section.rows.length)
    : []
  const rows = workSections.flatMap(section => section.rows || [])
  if (!sourceBreakdown.length && !rows.length) return null
  return {
    priorityRule: String(detail.priority_rule || '简体 > 繁体 > 原作'),
    forceRefresh: Boolean(detail.force_refresh),
    includeDlsite: Boolean(detail.include_dlsite),
    includeKikoeru: Boolean(detail.include_kikoeru),
    sourceBreakdown,
    rows,
  }
}

function circleCompletionRefreshModel(row) {
  if (!row || row.category !== 'circle_completion' || row.action !== 'refresh_selected_works') return null
  const detail = row.detail && typeof row.detail === 'object' ? row.detail : {}
  const rawItems = Array.isArray(detail.refreshed_items)
    ? detail.refreshed_items
        .map(item => ({
          canonical_rjcode: String(item?.canonical_rjcode || '').trim(),
          title: String(item?.title || '').trim(),
          display_rjcode: String(item?.display_rjcode || item?.canonical_rjcode || '').trim(),
          preferred_variant_label: String(item?.preferred_variant_label || '').trim(),
          has_kikoeru: Boolean(item?.has_kikoeru),
          has_asmr_one: Boolean(item?.has_asmr_one),
          asmrAvailableRjcode: String(item?.asmr_available_rjcode || '').trim(),
          serverMatchPrimaryRjcode: String(item?.server_match_primary_rjcode || '').trim(),
          serverMatchRjcodes: Array.isArray(item?.server_match_rjcodes) ? item.server_match_rjcodes.map(code => String(code || '').trim()).filter(Boolean) : [],
          subtitlePresent: Boolean(item?.subtitle_present),
          changed: Boolean(item?.changed),
          resultStatus: Boolean(item?.has_kikoeru) ? 'owned' : (Boolean(item?.has_asmr_one) ? 'downloadable' : 'missing'),
          resultLabel: Boolean(item?.has_kikoeru) ? '服务器已有' : (Boolean(item?.has_asmr_one) ? 'asmr.one 可下载' : '无来源'),
          changeDetails: Array.isArray(item?.change_details)
            ? item.change_details
                .map(change => ({
                  key: String(change?.key || '').trim(),
                  label: String(change?.label || '').trim() || '状态变更',
                  before: change?.before,
                  after: change?.after,
                }))
                .filter(change => change.key)
            : []
        }))
        .filter(item => item.canonical_rjcode)
    : []
  if (!rawItems.length) return null
  const filteredItems = rawItems.filter(item => {
    if (circleRefreshFilter.value === 'changed') return item.changed
    if (circleRefreshFilter.value === 'unchanged') return !item.changed
    return true
  })
  const items = [...filteredItems].sort((left, right) => {
    const leftServerChanged = left.changeDetails.some(change => change.key === 'server_state')
    const rightServerChanged = right.changeDetails.some(change => change.key === 'server_state')
    if (left.changed !== right.changed) return left.changed ? -1 : 1
    if (leftServerChanged !== rightServerChanged) return leftServerChanged ? -1 : 1
    return String(left.display_rjcode || left.canonical_rjcode).localeCompare(String(right.display_rjcode || right.canonical_rjcode))
  })
  return {
    selectedCount: Number(detail.selected_count || rawItems.length),
    refreshedCount: Number(detail.refreshed_count || rawItems.length),
    changedCount: Number(detail.changed_count || rawItems.filter(item => item.changed).length),
    serverMatchedCount: Number(detail.kikoeru_owned_count || rawItems.filter(item => item.has_kikoeru).length),
    filteredCount: items.length,
    items,
  }
}

function formatRefreshChangeValue(value) {
  if (Array.isArray(value)) {
    const normalized = value.map(item => String(item || '').trim()).filter(Boolean)
    return normalized.length ? normalized.join(' / ') : '—'
  }
  return String(value ?? '').trim() || '—'
}

function normalizeKikoeruTags(tags) {
  const source = Array.isArray(tags) ? tags : []
  const normalized = []
  for (const tag of source) {
    const text = String(tag || '').trim()
    if (!text) continue
    const value = text.startsWith('字幕') ? '字幕' : text
    if (!normalized.includes(value)) normalized.push(value)
  }
  return normalized
}

function circleIndexSourceTone(sourceKey, item) {
  if (sourceKey === 'kikoeru') {
    return item?.sourceCompare?.kikoeru?.primary_rjcode ? 'check' : 'empty'
  }
  if (sourceKey === 'dlsite') {
    return Array.isArray(item?.sourceCompare?.dlsite?.all_rjcodes) && item.sourceCompare.dlsite.all_rjcodes.length ? 'check' : 'empty'
  }
  if (sourceKey === 'asmr_one') {
    return item?.sourceCompare?.asmr_one?.primary_rjcode ? 'check' : 'empty'
  }
  return 'empty'
}

function circleIndexSourceIcon(sourceKey, item) {
  return circleIndexSourceTone(sourceKey, item) === 'check' ? CheckCircle2 : MinusCircle
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
  const keyLabelMap = {
    rjcode: 'RJ',
    source_rjcode: '来源 RJ',
    target_rjcode: '目标 RJ',
    linked_source_rjcode: '关联来源 RJ',
    linked_target_rjcode: '关联目标 RJ',
    downloaded_count: '抓取字幕数',
    written_files_count: '写入字幕数',
    awaiting_manual_match: '待手动配对',
    output_path: '输出目录',
    source_basename: '压缩包文件',
    archive_size_bytes: '压缩包大小',
    extract_output_bytes: '解压产物大小',
    filtered_count: '过滤文件数',
    filtered_size: '过滤体积',
    final_file_count: '最终文件数',
    record_id: '记录 ID',
    import_final_file_count: '导入文件数',
    recovered_failure_count: '修复失败数',
    duration_ms: '耗时',
    selected_count: '命中数量',
    selected_size: '命中体积',
    success_count: '成功数量',
    failed_count: '失败数量',
    deleted_bytes: '删除体积',
    retry_target_count: '重试目标数',
    retry_success_count: '重试成功数',
    retry_failed_count: '重试失败数',
    retry_recovered_item_count: '重试补回项数',
    recovered_item_count: '补回项数',
    recovered_selected_size: '补回体积',
    batch_task_count: '下载任务数',
    downloaded_bytes: '下载大小',
    uploaded_bytes: '上传大小',
    average_upload_speed_bytes: '平均上传速度',
    download_root: '下载目录',
    final_output_path: '最终入库路径',
    target_path: '上传目标',
    target_library_id: '目标库存',
    target_subdir: '库存前缀目录',
    upload_mode: '上传模式',
    uploaded_count: '上传文件数',
    circle_name: '社团名',
    resource_name: '文件名',
    resource_path: '相对路径',
    local_path: '本地路径',
    upload_path: '上传路径',
    size_bytes: '文件大小',
    local_owned_count: '本地已有',
    owned_count: '服务器已有',
    missing_count: '缺失数量',
    downloadable_count: '可下载数量',
    dl_count: 'DL 数量',
    works_count: '作品总数',
    scan_directory_count: '扫描目录数',
    recognized_rj_count: '识别 RJ 数',
    created_count: '创建任务数',
    skipped_total: '跳过数量',
    skipped_existing: '已存在跳过',
    skipped_duplicate: '重复跳过',
    skipped_no_subtitle: '无字幕跳过',
    batch_duration_ms: '批量总耗时',
    archive_count: '压缩包总数',
    requested_count: '候选数量',
    extract_completed_count: '完成解压数',
    failed_child_count: '失败项数',
    partial_child_count: '部分成功项数',
    aggregate_archive_size_bytes: '批量压缩包大小',
    aggregate_extract_output_bytes: '批量解压产物大小'
  }
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
    , 'requested_count'
    , 'archive_count'
    , 'extract_completed_count'
    , 'failed_child_count'
    , 'partial_child_count'
    , 'aggregate_archive_size_bytes'
    , 'aggregate_extract_output_bytes'
    , 'batch_duration_ms'
    , 'uploaded_bytes'
    , 'average_upload_speed_bytes'
  ]
  const out = []
  for (const k of pickKeys) {
    if (d[k] === undefined || d[k] === null) continue
    let value = d[k]
    if (k === 'duration_ms' || k === 'batch_duration_ms') value = formatDurationMs(value)
    if (k === 'awaiting_manual_match') value = value ? '是' : '否'
    if (['selected_size', 'deleted_bytes', 'archive_size_bytes', 'extract_output_bytes', 'recovered_selected_size', 'filtered_size', 'aggregate_archive_size_bytes', 'aggregate_extract_output_bytes', 'uploaded_bytes'].includes(k)) value = formatBytes(value)
    if (k === 'average_upload_speed_bytes') value = `${formatBytes(value)}/s`
    if (k.includes('rjcode')) value = normalizeRjcode(value)
    if (!String(value || '').trim()) continue
    out.push({ k: keyLabelMap[k] || k, v: String(value) })
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
      metaText: '',
      error: '',
      badges: [],
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
        node.metaText = item.metaText || ''
        node.error = item.error || ''
        node.badges = Array.isArray(item.badges) ? [...item.badges] : []
        node.variant = item.variant || ''
      }
      parentKey = joined
    })
  }

  const rows = []
  const markParentVariant = (node) => {
    if (!Array.isArray(node.children) || !node.children.length) return node.variant || ''
    const childVariants = node.children.map(child => markParentVariant(child)).filter(Boolean)
    if (!childVariants.length) return node.variant || ''
    if (childVariants.every(variant => variant === 'deleted')) return 'deleted'
    if (childVariants.every(variant => variant === 'failed')) return 'failed'
    return node.variant || ''
  }

  roots.forEach(root => markParentVariant(root))

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
        metaText: node.metaText,
        error: node.error,
        badges: node.badges,
        variant: node.variant || '',
        depth,
        children: node.children.length ? [...node.children] : [],
        expandable: node.children.length > 0
      })
    }
  }

  walk(roots)
  return rows
}

function commonPathPrefix(paths) {
  const normalized = (Array.isArray(paths) ? paths : [])
    .map(path => String(path || '').trim().replace(/\\/g, '/'))
    .filter(Boolean)
  if (!normalized.length) return ''
  const splitPaths = normalized.map(path => path.split('/').filter(Boolean))
  const first = splitPaths[0]
  const prefix = []
  for (let index = 0; index < first.length; index += 1) {
    const segment = first[index]
    if (splitPaths.every(parts => parts[index] === segment)) prefix.push(segment)
    else break
  }
  const driveMatch = normalized[0].match(/^[A-Za-z]:/)
  const drive = driveMatch ? driveMatch[0] : ''
  const joined = prefix.join('/')
  if (!joined) return drive
  return drive && !joined.toLowerCase().startsWith(drive.toLowerCase()) ? `${drive}/${joined}` : joined
}

function getFileName(path) {
  const normalized = String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
  if (!normalized) return ''
  const parts = normalized.split('/').filter(Boolean)
  return parts[parts.length - 1] || normalized
}

function buildDeleteTreeRows(items) {
  const list = Array.isArray(items) ? items.filter(item => String(item?.path || '').trim()) : []
  if (!list.length) return []
  const rootPath = commonPathPrefix(list.map(item => item.path))
  const rootLabel = getFileName(rootPath) || rootPath || '删除目标'
  const normalizedItems = list.map((item) => {
    const fullPath = String(item.path || '').trim().replace(/\\/g, '/')
    const normalizedRoot = String(rootPath || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
    let relativePath = fullPath
    if (normalizedRoot && fullPath.toLowerCase().startsWith(`${normalizedRoot.toLowerCase()}/`)) {
      relativePath = fullPath.slice(normalizedRoot.length + 1)
    } else if (normalizedRoot && fullPath.toLowerCase() === normalizedRoot.toLowerCase()) {
      relativePath = ''
    }
    const displayRelative = [rootLabel, relativePath].filter(Boolean).join('/')
    return {
      ...item,
      relative_path: displayRelative || rootLabel,
    }
  })

  return buildFilterDeleteTreeRows(normalizedItems)
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
    const items = mapFilterDeleteItems(d.succeeded_items).map(item => ({ ...item, variant: 'deleted' }))
    sections.push({ key: 'success-items', title: `已删除项（${d.success_count || d.succeeded_items.length}）`, rows: buildFilterDeleteTreeRows(items) })
  }
  if (Array.isArray(d.failed_items) && d.failed_items.length) {
    const items = mapFilterDeleteItems(d.failed_items).map(item => ({ ...item, variant: 'failed' }))
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

function asmrSyncEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (String(row?.category || '').trim() !== 'asmr_sync') return []
  const mergedFiles = buildMergedAsmrSyncFileItems(row)
  if (!mergedFiles.length) return []
  const totalBytes = sumAsmrSyncFileBytes(mergedFiles)
  const uploadedCount = mergedFiles.filter(item => Array.isArray(item.badges) && item.badges.includes('已上传')).length
  const countValue = Number(d.success_count || mergedFiles.length)
  const titleParts = [String(countValue)]
  if (totalBytes > 0) titleParts.push(formatBytes(totalBytes))
  if (uploadedCount > 0) titleParts.push(`已上传 ${uploadedCount}`)
  return [{
    key: 'asmr-file-tree',
    title: `文件清单（${titleParts.join(' / ')}）`,
    description: resolveAsmrSyncSectionDescription(d),
    rows: buildFilterDeleteTreeRows(mergedFiles)
  }]
}

function deleteEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (String(row?.category || '').trim() !== 'pipeline_delete') return []

  const succeededItems = []
  const failedItems = []

  if (Array.isArray(d.results) && d.results.length) {
    for (const item of d.results) {
      const path = String(item?.path || '').trim()
      if (!path) continue
      const mapped = {
        key: path,
        path,
        relative_path: path,
        name: getFileName(path) || path,
        type: inferDeleteTreeItemType(path, ''),
        sizeText: '',
        error: String(item?.error || '').trim(),
        variant: item?.success === false || String(item?.error || '').trim() ? 'failed' : 'deleted',
      }
      if (item?.success === false || mapped.error) failedItems.push(mapped)
      else succeededItems.push(mapped)
    }
  }

  if (!succeededItems.length && !failedItems.length && Array.isArray(d.child_rows) && d.child_rows.length) {
    for (const item of d.child_rows) {
      const childDetail = item?.detail && typeof item.detail === 'object' ? item.detail : {}
      const path = String(item?.source_path || childDetail.path || '').trim()
      if (!path) continue
      const mapped = {
        key: `${item?.id || path}`,
        path,
        relative_path: path,
        name: String(childDetail.item_name || getFileName(path) || path),
        type: inferDeleteTreeItemType(path, childDetail.item_type || ''),
        sizeText: '',
        error: String(childDetail.error || '').trim(),
        variant: String(item?.status || '').trim() === 'failed' || String(childDetail.error || '').trim() ? 'failed' : 'deleted',
      }
      if (String(item?.status || '').trim() === 'failed' || mapped.error) failedItems.push(mapped)
      else succeededItems.push(mapped)
    }
  }

  if (!succeededItems.length && !failedItems.length && String(row?.action || '').trim() === 'delete') {
    const path = String(row?.source_path || d.path || '').trim()
    if (path) {
      const mapped = {
        key: path,
        path,
        relative_path: path,
        name: String(d.item_name || getFileName(path) || path),
        type: inferDeleteTreeItemType(path, d.item_type || ''),
        sizeText: '',
        error: String(d.error || '').trim(),
        variant: String(row?.status || '').trim() === 'failed' || String(d.error || '').trim() ? 'failed' : 'deleted',
      }
      if (String(row?.status || '').trim() === 'failed' || mapped.error) failedItems.push(mapped)
      else succeededItems.push(mapped)
    }
  }

  const sections = []
  if (succeededItems.length) {
    const titleSuffix = d.deleted_bytes ? ` / ${formatBytes(d.deleted_bytes)}` : ''
    sections.push({
      key: 'delete-succeeded-items',
      title: `删除文件（${succeededItems.length}${titleSuffix}）`,
      rows: buildDeleteTreeRows(succeededItems)
    })
  }
  if (failedItems.length) {
    sections.push({
      key: 'delete-failed-items',
      title: `删除失败（${failedItems.length}）`,
      rows: buildDeleteTreeRows(failedItems)
    })
  }
  return sections
}

function subtitleBatchEntrySections(row) {
  const d = row?.detail
  if (!d || typeof d !== 'object' || d.mode !== 'subtitle_batch_start') return []
  const rows = buildSubtitleBatchDirectoryRows(d)
  if (!rows.length) return []
  return [{
    key: 'batch-directory-tree',
    title: `扫描详情（${rows.length}）`,
    rows
  }]
}

function activityEntrySections(row) {
  return [
    ...asmrSyncEntrySections(row),
    ...deleteEntrySections(row),
    ...importFilteredEntrySections(row),
    ...subtitleBatchEntrySections(row),
    ...filterDeleteEntrySections(row)
  ]
}

function activityEntrySectionTitle(row) {
  const d = row?.detail
  if (d && typeof d === 'object' && d.mode === 'subtitle_batch_start') return '批量详情'
  if (String(row?.category || '').trim() === 'asmr_sync') return '文件树'
  if (String(row?.category || '').trim() === 'pipeline_delete') return '文件树'
  if (['auto_import', 'process_existing'].includes(String(row?.category || '').trim())) return '处理清单'
  return '删除清单'
}

function inferDeleteTreeItemType(path, itemType) {
  const normalizedType = String(itemType || '').trim().toLowerCase()
  if (normalizedType === 'dir' || normalizedType === 'folder') return 'dir'
  const normalizedPath = String(path || '').trim().replace(/\\/g, '/')
  const base = normalizedPath.split('/').pop() || ''
  return /\.[^./]+$/.test(base) ? 'file' : 'dir'
}

function mapAsmrSyncFileItems(items, mode) {
  return (Array.isArray(items) ? items : []).slice(0, 200).map((item, index) => {
    const path = String(
      item?.relative_path
      || item?.path
      || item?.upload_path
      || item?.resource_path
      || item?.name
      || ''
    )
    const fallbackName = path.split('/').pop() || path.split('\\').pop() || '未命名文件'
    return {
      key: `${mode}-${index}-${path || fallbackName}`,
      path,
      relative_path: path,
      name: String(item?.name || fallbackName),
      type: 'file',
      sizeText: item?.size_bytes !== undefined && item?.size_bytes !== null
        ? formatBytes(item.size_bytes)
        : (item?.size !== undefined && item?.size !== null ? formatBytes(item.size) : ''),
      error: String(item?.error || item?.failure_reason || '').trim(),
    }
  }).filter(item => item.relative_path || item.name)
}

function normalizeAsmrMatchPath(value) {
  return String(value || '')
    .trim()
    .replace(/\\/g, '/')
    .replace(/^\.\/+/, '')
    .replace(/\/+/g, '/')
    .replace(/\/+$/, '')
    .toLowerCase()
}

function collectAsmrMatchInfo(item) {
  const rawValues = [
    item?.relative_path,
    item?.path,
    item?.name
  ]
  const normalizedValues = rawValues
    .map(normalizeAsmrMatchPath)
    .filter(Boolean)
  const exact = Array.from(new Set(normalizedValues.filter(value => value.includes('/'))))
  const basenames = Array.from(new Set(normalizedValues.map(value => getFileName(value)).filter(Boolean)))
  return { exact, basenames }
}

function buildAsmrUploadedMatchIndex(items) {
  const exact = new Set()
  const basenameCount = new Map()
  for (const item of Array.isArray(items) ? items : []) {
    const info = collectAsmrMatchInfo(item)
    info.exact.forEach(value => exact.add(value))
    info.basenames.forEach((value) => {
      basenameCount.set(value, (basenameCount.get(value) || 0) + 1)
    })
  }
  return { exact, basenameCount }
}

function isAsmrFileUploaded(item, uploadedMatchIndex) {
  const info = collectAsmrMatchInfo(item)
  if (info.exact.some(value => uploadedMatchIndex.exact.has(value))) return true
  return info.basenames.some(value => uploadedMatchIndex.basenameCount.get(value) === 1)
}

function buildMergedAsmrSyncFileItems(row) {
  const downloadFiles = collectAsmrSyncFiles(row, 'download')
  const uploadedFiles = collectAsmrSyncFiles(row, 'uploaded')
  const uploadFiles = collectAsmrSyncFiles(row, 'upload')
  const baseFiles = downloadFiles.length ? downloadFiles : (uploadedFiles.length ? uploadedFiles : uploadFiles)
  if (!baseFiles.length) return []

  const uploadedMatchIndex = buildAsmrUploadedMatchIndex(uploadedFiles)
  const shouldMarkUploaded = uploadedFiles.length > 0

  return baseFiles.map((item, index) => {
    const uploaded = shouldMarkUploaded && (baseFiles === uploadedFiles || isAsmrFileUploaded(item, uploadedMatchIndex))
    return {
      ...item,
      key: item?.key || `asmr-file-${index}`,
      badges: uploaded ? ['已上传'] : [],
    }
  })
}

function resolveAsmrSyncSectionDescription(detail) {
  const finalPath = String(detail?.final_output_path || detail?.target_path || '').trim()
  return finalPath ? `最终上传目录：${finalPath}` : ''
}

function collectAsmrSyncFiles(row, mode) {
  const d = row?.detail
  if (!d || typeof d !== 'object') return []
  if (mode === 'download') {
    const direct = mapAsmrSyncFileItems(d.download_files, mode)
    if (direct.length) return direct
    return mapAsmrSyncFileItems(
      (Array.isArray(d.child_rows) ? d.child_rows : [])
        .filter(item => String(item?.relation || item?.action || '').trim() === 'asmr_resource' || String(item?.action || '').trim() === 'resource_downloaded')
        .map(item => {
          const detail = item?.detail && typeof item.detail === 'object' ? item.detail : {}
          return {
            name: detail.resource_name || detail.relative_path || extractAsmrSummaryResourceName(item?.summary),
            relative_path: detail.relative_path || detail.resource_path || detail.resource_name || extractAsmrSummaryResourceName(item?.summary),
            size_bytes: detail.size_bytes,
            error: item?.status === 'failed' ? (detail.failure_reason || item?.summary || '') : '',
          }
        }),
      mode
    )
  }
  if (mode === 'upload') {
    const direct = mapAsmrSyncFileItems(d.upload_files, mode)
    if (direct.length) return direct
    return []
  }
  const direct = mapAsmrSyncFileItems(d.uploaded_files, mode)
  if (direct.length) return direct
  return mapAsmrSyncFileItems(
    (Array.isArray(d.child_rows) ? d.child_rows : [])
      .filter(item => String(item?.relation || item?.action || '').trim() === 'asmr_upload' || String(item?.action || '').trim() === 'resource_uploaded')
      .map(item => {
        const detail = item?.detail && typeof item.detail === 'object' ? item.detail : {}
        return {
          name: detail.relative_path || detail.upload_path || detail.target_path || extractAsmrSummaryResourceName(item?.summary),
          relative_path: detail.relative_path || detail.upload_path || detail.target_path || extractAsmrSummaryResourceName(item?.summary),
          size_bytes: detail.size_bytes,
          error: item?.status === 'failed' ? (detail.failure_reason || item?.summary || '') : '',
        }
      }),
    mode
  )
}

function sumAsmrSyncFileBytes(items) {
  return (Array.isArray(items) ? items : []).reduce((sum, item) => {
    const text = String(item?.sizeText || '').trim()
    if (!text) return sum
    const matched = text.match(/^([\d.]+)\s*(B|KB|MB|GB|TB)$/i)
    if (!matched) return sum
    const value = Number(matched[1] || 0)
    const unit = matched[2].toUpperCase()
    const power = { B: 0, KB: 1, MB: 2, GB: 3, TB: 4 }[unit] ?? 0
    return sum + value * (1024 ** power)
  }, 0)
}

function resolveEntryIcon(item) {
  if (item?.icon) return item.icon
  if (String(item?.variant || '').trim() === 'warning') return AlertCircle
  if (String(item?.variant || '').trim() === 'success') return CheckCircle2
  if (String(item?.type || '').trim() === 'dir') return Folder
  const name = String(item?.label || item?.name || item?.path || '').toLowerCase()
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(name)) return Music
  if (/\.(jpg|jpeg|png|webp|gif|bmp|avif)$/i.test(name)) return ImageIcon
  if (/\.(mp4|mkv|avi|mov|wmv|webm|m4v)$/i.test(name)) return Film
  if (/\.(zip|7z|rar|tar|gz|bz2|xz)$/i.test(name)) return FileArchive
  if (/\.(srt|ass|ssa|vtt|lrc|txt|md|json)$/i.test(name)) return FileText
  return FileIcon
}

function entryIconClass(item) {
  if (String(item?.variant || '').trim() === 'warning') return 'is-warning'
  if (String(item?.variant || '').trim() === 'success') return 'is-success'
  if (String(item?.type || '').trim() === 'dir') return 'is-dir'
  const name = String(item?.label || item?.name || item?.path || '').toLowerCase()
  if (/\.(wav|flac)$/i.test(name)) return 'is-audio-blue'
  if (/\.(mp3|m4a|ogg|aac|wma|opus|cue)$/i.test(name)) return 'is-audio-purple'
  if (/\.(jpg|jpeg|png|webp|gif|bmp|avif)$/i.test(name)) return 'is-image'
  if (/\.(mp4|mkv|avi|mov|wmv|webm|m4v)$/i.test(name)) return 'is-video'
  if (/\.(pdf)$/i.test(name)) return 'is-pdf'
  if (/\.(zip|7z|rar|tar|gz|bz2|xz)$/i.test(name)) return 'is-archive'
  if (/\.(srt|ass|ssa|vtt|lrc|txt|md|json)$/i.test(name)) return 'is-text'
  return 'is-file'
}

function flattenEntryRows(rows) {
  const flattened = []
  const visit = (items, depth = 0) => {
    for (const item of Array.isArray(items) ? items : []) {
      const current = { ...item, depth }
      flattened.push(current)
      if (current.expandable && isEntryTreeRowExpanded(current.key) && current.children?.length) {
        visit(current.children, depth + 1)
      }
    }
  }
  visit(rows, 0)
  return flattened
}

function isEntrySectionExpanded(sectionKey) {
  return !collapsedEntrySectionKeys.value.has(String(sectionKey || ''))
}

function toggleEntrySection(sectionKey) {
  const key = String(sectionKey || '')
  if (!key) return
  const next = new Set(collapsedEntrySectionKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedEntrySectionKeys.value = next
}

function isEntryTreeRowExpanded(rowKey) {
  return !collapsedEntryTreeRowKeys.value.has(String(rowKey || ''))
}

function toggleEntryTreeRow(rowKey) {
  const key = String(rowKey || '')
  if (!key) return
  const next = new Set(collapsedEntryTreeRowKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedEntryTreeRowKeys.value = next
}

function normalizePathForCompare(path) {
  return String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

function findSubtitleBatchSourceDirectory(folderPath, directories) {
  const normalizedFolder = normalizePathForCompare(folderPath)
  if (!normalizedFolder) return null
  let matched = null
  let matchedLength = -1
  for (const item of directories) {
    const basePath = String(item?.folder_path || item?.path || '').trim()
    const normalizedBase = normalizePathForCompare(basePath)
    if (!normalizedBase) continue
    const isSame = normalizedFolder === normalizedBase
    const isChild = normalizedFolder.startsWith(`${normalizedBase}/`)
    if ((isSame || isChild) && normalizedBase.length > matchedLength) {
      matched = item
      matchedLength = normalizedBase.length
    }
  }
  return matched
}

function buildSubtitleBatchDirectoryRows(detail) {
  const sourceDirectories = Array.isArray(detail?.source_directories) ? detail.source_directories : []
  const scanTargets = Array.isArray(detail?.scan_targets) ? detail.scan_targets : []
  const createdTasks = Array.isArray(detail?.created_tasks) ? detail.created_tasks : []
  const skippedItems = Array.isArray(detail?.skipped_items) ? detail.skipped_items : []
  const directoryMap = new Map()

  for (const [index, item] of sourceDirectories.slice(0, 120).entries()) {
    const path = String(item?.folder_path || item?.path || '').trim()
    const key = path || `source-${index}`
    directoryMap.set(key, {
      key: `subtitle-dir-${key}`,
      path,
      label: String(item?.folder_name || item?.name || path || '未命名目录'),
      type: 'dir',
      variant: 'dir',
      sizeText: path,
      metaText: '',
      error: '',
      depth: 0,
      expandable: true,
      children: [],
      createdCount: 0,
      failedCount: 0
    })
  }

  for (const target of scanTargets.slice(0, 160)) {
    const path = String(target?.path || '').trim()
    const existing = directoryMap.get(path)
    if (existing) {
      existing.metaText = target?.message || ''
      if (String(target?.status || '').trim() === 'failed') {
        existing.variant = 'warning'
      }
    }
  }

  const ensureDirectory = (folderPath, fallbackName = '') => {
    const matchedSource = findSubtitleBatchSourceDirectory(folderPath, sourceDirectories)
    const sourcePath = String(matchedSource?.folder_path || matchedSource?.path || folderPath || '').trim()
    const key = sourcePath || folderPath || fallbackName || `other-${directoryMap.size}`
    if (!directoryMap.has(key)) {
      directoryMap.set(key, {
        key: `subtitle-dir-${key}`,
        path: sourcePath,
        label: String(matchedSource?.folder_name || matchedSource?.name || fallbackName || sourcePath || '未命名目录'),
        type: 'dir',
        variant: 'dir',
        sizeText: sourcePath,
        metaText: '',
        error: '',
        depth: 0,
        expandable: true,
        children: [],
        createdCount: 0,
        failedCount: 0
      })
    }
    return directoryMap.get(key)
  }

  for (const [index, item] of createdTasks.slice(0, 200).entries()) {
    const folderPath = String(item?.folder_path || '').trim()
    const parent = ensureDirectory(folderPath, item?.folder_name || '')
    parent.createdCount += 1
    parent.children.push({
      key: `created-${index}-${item?.task_id || folderPath || item?.rjcode || ''}`,
      label: `${item?.rjcode ? `[${item.rjcode}] ` : ''}${item?.folder_name || folderPath || '未命名 RJ'}`,
      type: 'rj',
      variant: 'success',
      depth: 1,
      metaText: '已创建爬取任务',
      sizeText: folderPath,
      error: ''
    })
  }

  for (const [index, item] of skippedItems.slice(0, 200).entries()) {
    const folderPath = String(item?.folder_path || '').trim()
    const parent = ensureDirectory(folderPath, item?.folder_name || '')
    parent.failedCount += 1
    parent.variant = 'warning'
    parent.children.push({
      key: `skipped-${index}-${folderPath || item?.rjcode || item?.folder_name || ''}`,
      label: `${item?.rjcode ? `[${item.rjcode}] ` : ''}${item?.folder_name || folderPath || '未命名 RJ'}`,
      type: 'rj',
      variant: 'warning',
      depth: 1,
      metaText: item?.queue_state === 'existing_task' ? '加入失败：任务已存在' : '加入失败',
      sizeText: folderPath,
      error: String(item?.queue_message || '').trim()
    })
  }

  return Array.from(directoryMap.values()).map(item => {
    const summaryParts = []
    if (item.metaText) summaryParts.push(item.metaText)
    if (item.createdCount) summaryParts.push(`成功 ${item.createdCount}`)
    if (item.failedCount) summaryParts.push(`失败 ${item.failedCount}`)
    return {
      ...item,
      metaText: summaryParts.join(' · '),
      children: item.children
    }
  })
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
      else detailDialogVisible.value = false
    }
  } finally {
    loading.value = false
  }
}

async function loadAll() {
  await Promise.all([loadStats(), loadList()])
  lastLoadedAt.value = Date.now()
}

function shouldSoftRefreshActivityPage() {
  const lastLoaded = Number(lastLoadedAt.value || 0)
  if (!lastLoaded) return true
  return Date.now() - lastLoaded >= ACTIVITY_AUTO_REFRESH_STALE_MS
}

function handleActivityPageVisibilityRefresh() {
  if (document.visibilityState !== 'visible') return
  if (!shouldSoftRefreshActivityPage()) return
  loadAll()
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
  document.addEventListener('visibilitychange', handleActivityPageVisibilityRefresh)
})

onActivated(() => {
  if (!shouldSoftRefreshActivityPage()) return
  loadAll()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleActivityPageVisibilityRefresh)
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

watch(selectedRow, (row) => {
  batchWorkbenchAwaitingOnly.value = false
  collapsedEntrySectionKeys.value = new Set()
  compareSearchQuery.value = ''
  compareSourceFilter.value = 'all'
  compareExpanded.value = true
  syncBatchWorkbenchSelection(row)
}, { immediate: true })
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
  gap: 8px;
  align-items: center;
}

.filter-select {
  width: 110px;
}

.table-panel {
  padding-bottom: 8px;
  overflow-x: hidden;
}

.activity-page-loading-shell {
  position: relative;
  min-height: 100%;
}

:deep(.activity-history-loading-mask) {
  inset: 0;
  border-radius: 0;
  background: rgba(250, 251, 255, 0.84);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  z-index: 50;
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

.child-row-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding-left: 0;
  color: rgba(29, 29, 31, 0.62);
  font-size: 12px;
  font-weight: 600;
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

:deep(.ios-table .activity-row-grandchild td) {
  background: linear-gradient(180deg, rgba(255, 159, 10, 0.04), rgba(255, 204, 117, 0.10)) !important;
}

:deep(.ios-table .activity-row-grandchild:hover > td) {
  background: linear-gradient(180deg, rgba(255, 159, 10, 0.08), rgba(255, 204, 117, 0.15)) !important;
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

.drawer-shell {
  position: relative;
}

.detail-drawer-resize-handle {
  position: absolute;
  left: -10px;
  top: 0;
  bottom: 0;
  width: 18px;
  cursor: ew-resize;
  z-index: 20;
}

.detail-drawer-resize-handle::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 84px;
  bottom: 20px;
  width: 2px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.42);
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

.pair-workbench-block {
  padding: 0;
  background: transparent;
  box-shadow: none;
}

.circle-index-card {
  display: grid;
  gap: 18px;
  padding: 20px;
  border-radius: 22px;
  background:
    linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(255, 255, 255, 0.98));
  box-shadow:
    0 16px 36px rgba(15, 23, 42, 0.08),
    inset 0 0 0 1px rgba(148, 163, 184, 0.16);
}

.circle-index-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.circle-index-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.circle-index-desc {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(15, 23, 42, 0.66);
}

.circle-index-flags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.circle-index-flag {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.05);
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}

.circle-index-metric-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}

.circle-index-metric {
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.14);
}

.circle-index-metric.is-kikoeru {
  background: rgba(239, 246, 255, 0.92);
}

.circle-index-metric.is-dlsite {
  background: rgba(255, 247, 237, 0.94);
}

.circle-index-metric.is-asmr_one {
  background: rgba(240, 253, 244, 0.94);
}

.circle-index-metric.is-downloadable {
  background: rgba(236, 253, 245, 0.98);
}

.circle-index-metric.is-dl_only {
  background: rgba(254, 242, 242, 0.96);
}

.circle-index-section-list {
  display: grid;
  gap: 18px;
}

.circle-index-section {
  display: grid;
  gap: 12px;
}

.circle-index-section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.circle-index-section-title {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}

.circle-index-section-desc {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(17, 24, 39, 0.62);
}

.circle-index-section-count {
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.08);
  color: #005fcc;
  font-size: 12px;
  font-weight: 700;
}

.circle-index-diff-board {
  border-radius: 18px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.16);
}

.circle-index-diff-head,
.circle-index-diff-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.4fr) repeat(3, minmax(140px, 1fr));
}

.circle-index-diff-head {
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.98), rgba(241, 245, 249, 0.98));
}

.circle-index-diff-row + .circle-index-diff-row {
  border-top: 1px solid rgba(226, 232, 240, 0.92);
}

.circle-index-col {
  padding: 12px 14px;
  min-width: 0;
}

.circle-index-col + .circle-index-col {
  border-left: 1px solid rgba(226, 232, 240, 0.92);
}

.circle-index-col.source.kikoeru {
  background: rgba(239, 246, 255, 0.52);
}

.circle-index-col.source.dlsite {
  background: rgba(255, 247, 237, 0.58);
}

.circle-index-col.source.asmr {
  background: rgba(240, 253, 244, 0.62);
}

.circle-index-diff-head .circle-index-col {
  font-size: 12px;
  font-weight: 700;
  color: rgba(15, 23, 42, 0.68);
}

.circle-index-work-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.circle-index-work-rj {
  color: #0f172a;
  font-weight: 700;
}

.circle-index-work-title {
  margin-top: 6px;
  color: #111827;
  line-height: 1.5;
}

.circle-index-work-meta {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(17, 24, 39, 0.58);
}

.circle-index-status-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}

.circle-index-status-pill.is-owned {
  background: rgba(10, 132, 255, 0.12);
  color: #005fcc;
}

.circle-index-status-pill.is-downloadable {
  background: rgba(52, 199, 89, 0.12);
  color: #248a3d;
}

.circle-index-status-pill.is-dl_only {
  background: rgba(255, 59, 48, 0.10);
  color: #c2410c;
}

.circle-index-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.circle-index-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.18);
  color: #0f172a;
  font-size: 11px;
  font-weight: 600;
}

.circle-index-chip.is-asmr {
  background: rgba(236, 253, 245, 0.96);
  box-shadow: inset 0 0 0 1px rgba(52, 199, 89, 0.18);
  color: #248a3d;
}

.circle-index-chip.is-kikoeru-tag {
  background: rgba(239, 246, 255, 0.96);
  box-shadow: inset 0 0 0 1px rgba(10, 132, 255, 0.18);
  color: #005fcc;
}
.circle-index-chip.has-icon {
  gap: 4px;
}
.kikoeru-tag-icon {
  width: 12px;
  height: 12px;
  display: inline-block;
  fill: currentColor;
  flex: 0 0 auto;
}

.circle-index-empty {
  font-size: 12px;
  color: rgba(100, 116, 139, 0.78);
}

.circle-index-pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 10px;
}

.compare-table-shell {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.compare-table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 0 14px;
  cursor: pointer;
}

.compare-table-title-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.compare-table-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 14px;
  background: rgba(241, 245, 249, 0.96);
  color: #64748b;
  flex: 0 0 auto;
}

.compare-table-title {
  font-size: 24px;
  line-height: 1;
  font-weight: 800;
  color: #1f2937;
}

.compare-table-subtitle {
  margin-top: 5px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.01em;
  text-transform: none;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.compare-table-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.compare-search {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
  height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.94);
  border: 1px solid rgba(226, 232, 240, 0.9);
  color: #94a3b8;
}

.compare-search input {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  color: #94a3b8;
  font-size: 12px;
}

.compare-filter {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 10px 0 12px;
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.94);
  border: 1px solid rgba(226, 232, 240, 0.9);
  color: #94a3b8;
}

.compare-filter :deep(.el-select) {
  width: 108px;
}

.compare-filter :deep(.el-select__wrapper) {
  min-height: 24px;
  height: 24px;
  padding: 0;
  background: transparent;
  box-shadow: none;
  border: none;
}

.compare-filter :deep(.el-select__selection) {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}

.compare-filter :deep(.el-select__placeholder),
.compare-filter :deep(.el-select__selected-item),
.compare-filter :deep(.el-select__input-wrapper) {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}

.compare-filter :deep(.el-select__caret) {
  color: #94a3b8;
  font-size: 12px;
}

:global(.compare-filter-popper.el-select__popper) {
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  box-shadow:
    0 20px 40px rgba(15, 23, 42, 0.08),
    0 6px 18px rgba(15, 23, 42, 0.04);
}

:global(.compare-filter-popper .el-select-dropdown__wrap) {
  padding: 6px;
}

:global(.compare-filter-popper .el-select-dropdown__item) {
  margin: 2px 0;
  height: 34px;
  line-height: 34px;
  border-radius: 12px;
  color: #475569;
  font-size: 12px;
  font-weight: 700;
}

:global(.compare-filter-popper .el-select-dropdown__item.is-hovering),
:global(.compare-filter-popper .el-select-dropdown__item:hover) {
  background: rgba(241, 245, 249, 0.9);
  color: #1f2937;
}

:global(.compare-filter-popper .el-select-dropdown__item.is-selected) {
  background: rgba(239, 246, 255, 0.96);
  color: #2563eb;
}

.compare-column-head {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) repeat(3, minmax(120px, 1fr));
  gap: 12px;
  padding: 12px 0 10px;
  border-top: 1px solid rgba(226, 232, 240, 0.72);
  color: #94a3b8;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.compare-col-source {
  text-align: center;
}

.compare-rows-wrap {
  max-height: 580px;
  overflow-y: auto;
  padding: 0 0 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(203, 213, 225, 0.95) rgba(241, 245, 249, 0.92);
}

.compare-rows-wrap::-webkit-scrollbar {
  width: 10px;
}

.compare-rows-wrap::-webkit-scrollbar-track {
  background: rgba(241, 245, 249, 0.92);
  border-radius: 999px;
}

.compare-rows-wrap::-webkit-scrollbar-thumb {
  background: rgba(203, 213, 225, 0.96);
  border-radius: 999px;
  border: 2px solid rgba(241, 245, 249, 0.92);
}

.compare-row {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) repeat(3, minmax(120px, 1fr));
  gap: 12px;
  align-items: center;
  padding: 14px 0;
  border-top: 1px solid rgba(241, 245, 249, 0.9);
}

.compare-meta-cell {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.compare-thumb {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  flex: 0 0 auto;
  border: 1px solid rgba(226, 232, 240, 0.92);
}

.compare-thumb-empty {
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.92));
  color: #94a3b8;
}

.compare-meta-copy {
  min-width: 0;
}

.compare-meta-title {
  font-size: 14px;
  font-weight: 700;
  color: #1f2937;
  line-height: 1.35;
}

.compare-meta-tags,
.compare-source-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 5px;
}

.compare-rj-badge,
.compare-meta-tag {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.96);
  border: 1px solid rgba(226, 232, 240, 0.9);
  color: #64748b;
  font-size: 10px;
  font-weight: 700;
}

.compare-source-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

.compare-source-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  flex: 0 0 auto;
}

.compare-source-status.is-check {
  background: rgba(236, 253, 245, 0.95);
  color: #10b981;
}

.compare-source-status.is-empty {
  background: rgba(241, 245, 249, 0.95);
  color: #cbd5e1;
}

.compare-source-meta {
  min-width: 0;
}

.compare-source-code {
  font-size: 11px;
  font-weight: 700;
  color: #334155;
}

@media (max-width: 1200px) {
  .compare-table-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .compare-table-toolbar {
    width: 100%;
    justify-content: flex-start;
  }

  .compare-column-head,
  .compare-row {
    grid-template-columns: 1fr;
  }

  .compare-col-source {
    text-align: left;
  }

  .compare-source-cell {
    justify-content: flex-start;
  }
}

.circle-refresh-card {
  display: grid;
  gap: 14px;
  padding: 18px;
  border-radius: 18px;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
  border: 1px solid rgba(73, 119, 198, 0.14);
}

.circle-refresh-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
}

.circle-refresh-title {
  font-size: 16px;
  font-weight: 800;
  color: #163961;
}

.circle-refresh-desc {
  margin-top: 4px;
  font-size: 13px;
  line-height: 1.6;
  color: #5f738d;
}

.circle-refresh-metrics {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.circle-refresh-toolbar {
  display: flex;
  justify-content: flex-end;
}

.circle-refresh-filter-group {
  display: inline-flex;
  gap: 8px;
  flex-wrap: wrap;
}

.circle-refresh-filter-btn {
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: #fff;
  color: #46627f;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.circle-refresh-filter-btn.active {
  background: #eef5ff;
  border-color: rgba(10, 132, 255, 0.18);
  color: #005fcc;
}

.circle-refresh-metric {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  background: #eef5ff;
  color: #345f9b;
  font-size: 12px;
  font-weight: 700;
}

.circle-refresh-list {
  display: grid;
  gap: 10px;
}

.circle-refresh-item {
  position: relative;
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(192, 209, 232, 0.74);
}

.circle-refresh-item.is-changed {
  border-color: rgba(52, 199, 89, 0.24);
  box-shadow: 0 12px 24px rgba(52, 199, 89, 0.08);
}

.circle-refresh-new-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  background: linear-gradient(135deg, #2dbb61, #34c759);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.circle-refresh-item-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.circle-refresh-title-rj {
  font-size: 13px;
  font-weight: 800;
  color: #21487a;
}

.circle-refresh-status {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
}

.circle-refresh-status.is-owned {
  background: rgba(10, 132, 255, 0.12);
  color: #005fcc;
}

.circle-refresh-status.is-downloadable {
  background: rgba(52, 199, 89, 0.12);
  color: #1f8f51;
}

.circle-refresh-status.is-missing {
  background: rgba(255, 95, 86, 0.10);
  color: #c2410c;
}

.circle-refresh-status.is-updated {
  background: rgba(52, 199, 89, 0.15);
  color: #17803d;
}

.circle-refresh-status.is-unchanged {
  background: rgba(255, 159, 10, 0.14);
  color: #b96b00;
}

.circle-refresh-item-title {
  font-size: 14px;
  line-height: 1.5;
  font-weight: 700;
  color: #193556;
}

.circle-refresh-change-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.circle-refresh-change-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
}

.circle-refresh-change-label {
  min-width: 88px;
  font-weight: 800;
  color: #48617f;
}

.circle-refresh-change-values {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.circle-refresh-change-before,
.circle-refresh-change-after {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  background: #f5f8fc;
  color: #26405f;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.16);
}

.circle-refresh-change-after {
  background: rgba(52, 199, 89, 0.10);
  color: #1f8f51;
  box-shadow: inset 0 0 0 1px rgba(52, 199, 89, 0.18);
}

.circle-refresh-change-arrow {
  color: #7f93ab;
  font-weight: 800;
}

.circle-refresh-variant-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.circle-refresh-meta-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.circle-refresh-variant-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.18);
  background: #f8fbff;
  color: #325074;
}

.circle-refresh-meta-chip {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.18);
  background: #f8fbff;
  color: #325074;
}

.circle-refresh-variant-chip.is-simplified {
  background: rgba(52, 199, 89, 0.12);
  box-shadow: inset 0 0 0 1px rgba(52, 199, 89, 0.18);
  color: #1f8f51;
}

.circle-refresh-variant-chip.is-traditional {
  background: rgba(255, 159, 10, 0.12);
  box-shadow: inset 0 0 0 1px rgba(255, 159, 10, 0.18);
  color: #b96b00;
}

.circle-refresh-variant-chip.is-original {
  background: rgba(10, 132, 255, 0.10);
  box-shadow: inset 0 0 0 1px rgba(10, 132, 255, 0.16);
  color: #005fcc;
}

.circle-refresh-variant-tag {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(52, 199, 89, 0.18);
  color: #17803d;
  font-size: 11px;
  font-weight: 800;
}

.circle-refresh-pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 6px;
}

@media (max-width: 1120px) {
  .circle-index-head {
    flex-direction: column;
  }

  .circle-refresh-head {
    flex-direction: column;
  }

  .circle-index-flags {
    justify-content: flex-start;
  }

  .circle-index-metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .circle-index-diff-head,
  .circle-index-diff-row {
    grid-template-columns: minmax(220px, 1.2fr) repeat(3, minmax(120px, 1fr));
  }
}

.pair-workbench-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 20px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.92), rgba(255, 255, 255, 0.98));
  box-shadow:
    0 14px 32px rgba(15, 23, 42, 0.08),
    inset 0 0 0 1px rgba(96, 165, 250, 0.18);
}

.pair-workbench-card.is-awaiting {
  background: linear-gradient(135deg, rgba(255, 247, 237, 0.96), rgba(255, 255, 255, 0.98));
  box-shadow:
    0 14px 32px rgba(245, 158, 11, 0.12),
    inset 0 0 0 1px rgba(251, 191, 36, 0.22);
}

.pair-workbench-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pair-workbench-kicker {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.48);
}

.pair-workbench-title {
  font-size: 20px;
  font-weight: 700;
  color: #111827;
}

.pair-workbench-desc {
  font-size: 13px;
  line-height: 1.6;
  color: rgba(29, 29, 31, 0.72);
}

.pair-workbench-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.pair-workbench-chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.08);
  font-size: 12px;
  font-weight: 600;
  color: #1f2937;
}

.pair-workbench-btn {
  flex: 0 0 auto;
  min-width: 112px;
  border-radius: 999px;
}

.pair-result-shell {
  display: grid;
  gap: 14px;
}

.pair-result-summary {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 250, 252, 0.96));
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
}

.pair-result-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pair-result-title {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
}

.pair-result-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.pair-result-status.is-success {
  background: rgba(52, 199, 89, 0.14);
  color: #15803d;
}

.pair-result-status.is-warning {
  background: rgba(245, 158, 11, 0.14);
  color: #b45309;
}

.pair-result-status.is-default {
  background: rgba(120, 120, 128, 0.12);
  color: #4b5563;
}

.pair-result-summary-text {
  font-size: 13px;
  line-height: 1.65;
  color: rgba(29, 29, 31, 0.78);
}

.pair-result-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
}

.pair-result-metric {
  padding: 12px 13px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.95);
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.05);
}

.pair-result-metric-label {
  margin-bottom: 5px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.42);
}

.pair-result-metric-value {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
}

.pair-change-board {
  display: grid;
  gap: 10px;
}

.pair-change-board-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  font-weight: 700;
  color: rgba(29, 29, 31, 0.52);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.pair-change-board-count {
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(10, 132, 255, 0.1);
  color: #0066cc;
}

.pair-change-card {
  padding: 14px 16px;
  border-radius: 16px;
  background: #f8fafc;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.16);
}

.pair-change-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.pair-change-column {
  min-width: 0;
}

.pair-change-label {
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.42);
}

.pair-change-value,
.pair-change-target {
  font-size: 12px;
  line-height: 1.65;
  color: #111827;
  white-space: normal;
  word-break: break-word;
  overflow-wrap: anywhere;
}

.pair-change-target {
  margin-top: 4px;
  color: #0066cc;
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

:deep(.ios-table .el-table__body tr.row-recovered) {
  opacity: 0.7;
}

:deep(.ios-table .el-table__body tr.row-recovered > td) {
  background: rgba(120, 126, 145, 0.08) !important;
  position: relative;
}

:deep(.ios-table .el-table__body tr.row-recovered > td::after) {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  border-top: 2px solid rgba(112, 119, 139, 0.52);
  transform: translateY(-50%);
  pointer-events: none;
  z-index: 2;
}

:deep(.ios-table .el-table__body tr.row-recovered .cell),
:deep(.ios-table .el-table__body tr.row-recovered .mono),
:deep(.ios-table .el-table__body tr.row-recovered .action-text),
:deep(.ios-table .el-table__body tr.row-recovered .cell-time),
:deep(.ios-table .el-table__body tr.row-recovered .status-tag),
:deep(.ios-table .el-table__body tr.row-recovered a) {
  color: rgba(88, 95, 112, 0.72) !important;
  text-decoration: none !important;
}

:deep(.ios-table .el-table__body tr.row-recovered .status-fixed-pill.is-final-success),
:deep(.ios-table .el-table__body tr.row-recovered .status-fixed-pill:not(.is-final-failed):not(.is-final-partial):not(.is-rerun)) {
  color: #187d34 !important;
  background: rgba(52, 199, 89, 0.1) !important;
  border-color: rgba(52, 199, 89, 0.18) !important;
}

:deep(.ios-table .el-table__body tr.row-recovered .recovered-leading-badge) {
  opacity: 1;
  color: #2f9e44 !important;
  background: #eef8ef !important;
  box-shadow: inset 0 0 0 1px rgba(47, 158, 68, 0.18) !important;
  text-decoration: none !important;
  position: relative;
  z-index: 5;
  filter: none !important;
}

:deep(.ios-table .el-table__body tr.row-recovered .tree-toggle-btn) {
  position: relative;
  z-index: 4;
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
  gap: 12px 10px;
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
}

.entry-section-head-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.entry-section-desc {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.46);
  line-height: 1.45;
  word-break: break-all;
}

.entry-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.entry-section-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 56px;
  height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.8);
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  position: relative;
  z-index: 2;
  transition: background-color 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}

.entry-section-toggle:hover {
  background: rgba(248, 250, 252, 0.96);
  color: #334155;
  border-color: rgba(148, 163, 184, 0.32);
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

.tree-row-shell {
  border-bottom: 1px solid rgba(29, 29, 31, 0.05);
}

.tree-row-shell:last-child {
  border-bottom: none;
}

.tree-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  padding-top: 6px;
  padding-bottom: 6px;
  cursor: default;
  transition: none;
}

.tree-row.is-expandable {
  align-items: center;
}

.tree-row-child {
  padding-top: 5px;
  padding-bottom: 5px;
}

.tree-row:hover,
.tree-row-child:hover,
.tree-row-shell:hover {
  background: transparent;
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

.tree-inline-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(255, 255, 255, 0.9);
  color: #64748b;
  flex: 0 0 auto;
  cursor: pointer;
  position: relative;
  z-index: 2;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.tree-inline-toggle:hover {
  background: rgba(255, 255, 255, 0.98);
  border-color: rgba(148, 163, 184, 0.32);
  color: #334155;
}

.tree-inline-toggle.expanded svg {
  transform: rotate(90deg);
}

.tree-inline-toggle svg {
  transition: transform 0.18s ease;
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
  background: rgba(239, 246, 255, 0.92);
  color: #60a5fa;
}

.entry-icon.is-success {
  background: rgba(236, 253, 245, 0.95);
  color: #059669;
}

.entry-icon.is-warning {
  background: rgba(255, 241, 242, 0.98);
  color: #e11d48;
}

.entry-icon.is-file {
  background: rgba(248, 250, 252, 0.92);
  color: #64748b;
}

.entry-icon.is-deleted {
  background: rgba(241, 245, 249, 0.9);
  color: rgba(71, 85, 105, 0.72);
}

.entry-icon.is-audio-blue {
  background: rgba(219, 234, 254, 0.92);
  color: #3b82f6;
}

.entry-icon.is-audio-purple {
  background: rgba(237, 233, 254, 0.92);
  color: #8b5cf6;
}

.entry-icon.is-image {
  background: rgba(254, 242, 242, 0.96);
  color: #f97316;
}

.entry-icon.is-video {
  background: rgba(238, 242, 255, 0.96);
  color: #6366f1;
}

.entry-icon.is-pdf {
  background: rgba(254, 242, 242, 0.96);
  color: #dc2626;
}

.entry-icon.is-archive {
  background: rgba(255, 247, 237, 0.96);
  color: #d97706;
}

.entry-icon.is-text {
  background: rgba(241, 245, 249, 0.96);
  color: #475569;
}

.entry-name {
  min-width: 0;
  color: #1d1d1f;
  word-break: break-word;
}

.entry-name.is-deleted {
  color: rgba(29, 29, 31, 0.5);
  text-decoration: line-through;
  text-decoration-thickness: 1.5px;
  text-decoration-color: rgba(29, 29, 31, 0.72);
}

.entry-name.is-failed {
  color: #b91c1c;
}

.entry-main-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.entry-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex-wrap: wrap;
}

.entry-meta-text {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.48);
  line-height: 1.4;
  word-break: break-word;
}

.entry-inline-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 7px;
  border-radius: 999px;
  border: 1px solid rgba(16, 185, 129, 0.18);
  background: rgba(236, 253, 245, 0.92);
  color: #047857;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
  line-height: 1;
  white-space: nowrap;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.entry-size {
  color: rgba(29, 29, 31, 0.55);
  font-size: 12px;
  white-space: normal;
  text-align: right;
  word-break: break-word;
}

.entry-error {
  grid-column: 1 / -1;
  color: #d70015;
  font-size: 12px;
  word-break: break-word;
  padding-left: 56px;
}

.tree-children {
  display: flex;
  flex-direction: column;
  padding-bottom: 4px;
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

.batch-workbench-shell {
  display: grid;
  gap: 14px;
  padding: 18px;
  border-radius: 18px;
  background: linear-gradient(180deg, #f8fbff, #ffffff);
  border: 1px solid rgba(53, 114, 239, 0.12);
}

.batch-workbench-summary {
  display: grid;
  gap: 8px;
}

.batch-workbench-title {
  font-size: 18px;
  font-weight: 700;
  color: #14213d;
}

.batch-workbench-desc {
  font-size: 13px;
  color: #5f6b7a;
  line-height: 1.6;
}

.batch-workbench-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.batch-workbench-metric {
  padding: 6px 10px;
  border-radius: 999px;
  background: #eef4ff;
  color: #31599b;
  font-size: 12px;
  font-weight: 700;
}

.batch-workbench-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.batch-workbench-toolbar-start {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.batch-workbench-checkall {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #334155;
}

.batch-workbench-quick-btn {
  padding: 0;
  border: 0;
  background: transparent;
  color: #2563eb;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.batch-workbench-quick-btn:hover {
  color: #1d4ed8;
}

.batch-workbench-list {
  display: grid;
  gap: 10px;
}

.batch-workbench-item {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: #fff;
}

.batch-workbench-item-main {
  display: grid;
  gap: 6px;
}

.batch-workbench-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.batch-workbench-item-rj {
  font-size: 14px;
  font-weight: 700;
  color: #1d4ed8;
}

.batch-workbench-item-status {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.batch-workbench-item-status.is-success {
  background: #ecfdf3;
  color: #2f855a;
}

.batch-workbench-item-status.is-warning {
  background: #fff7e6;
  color: #b7791f;
}

.batch-workbench-item-status.is-default {
  background: #f1f5f9;
  color: #475569;
}

.batch-workbench-item-name {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  word-break: break-all;
}

.batch-workbench-item-summary {
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
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

  .pair-workbench-card,
  .pair-result-title-row,
  .pair-change-card-grid,
  .batch-workbench-toolbar,
  .batch-workbench-toolbar-start {
    grid-template-columns: 1fr;
    flex-direction: column;
    align-items: stretch;
  }

  .pair-workbench-btn {
    width: 100%;
  }
}
</style>
