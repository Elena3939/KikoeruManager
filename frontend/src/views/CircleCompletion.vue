<template>
  <div class="circle-page">
    <section class="circle-hero">
      <div class="hero-copy">
        <div class="hero-eyebrow">Circle Completion</div>
        <h1>社团补全</h1>
        <p>按社团建立索引，以 Kikoeru 服务器是否已收录作为缺失判断，再结合 DLsite 关联链和 asmr.one 下载能力，把真正缺的作品批量送进下载队列。</p>
        <div class="hero-inline-metrics">
          <span class="hero-inline-pill">索引优先复用现有社团</span>
          <span class="hero-inline-pill">下载后自动按社团入库</span>
          <span class="hero-inline-pill">仅蓝色操作可交互</span>
        </div>
      </div>
      <div class="hero-actions">
        <el-input
          v-model="circleQuery"
          class="hero-search-input"
          placeholder="输入社团名，例如 こぐま座 / C_Realization"
          clearable
          @keyup.enter="handleIndexCircle"
        />
        <el-button class="hero-search-button" type="primary" :loading="indexing" @click="handleIndexCircle">建立 / 刷新索引</el-button>
      </div>
    </section>

    <section v-if="indexJob.visible" class="index-progress-card">
      <div class="index-progress-head">
        <div>
          <div class="index-progress-title">索引进度</div>
          <div class="index-progress-subtitle">
            {{ indexJob.circle_query || circleQuery || '当前社团' }} · {{ indexJob.current_step || '处理中' }}
          </div>
        </div>
        <div class="index-progress-head-actions">
          <el-button
            v-if="canCancelIndexJob"
            size="small"
            class="index-cancel-button"
            :loading="cancellingIndexJob"
            @click="cancelIndexJob"
          >
            取消索引
          </el-button>
          <div class="index-progress-status" :class="indexJob.status">{{ indexJobStatusText }}</div>
        </div>
      </div>

      <el-progress
        :percentage="indexJob.progress || 0"
        :status="indexJob.status === 'failed' ? 'exception' : (indexJob.status === 'completed' ? 'success' : '')"
        :stroke-width="12"
      />

      <div class="index-progress-meta">
        <span class="progress-meta-pill">耗时 {{ formatElapsed(indexJob.elapsed_seconds) }}</span>
        <span class="progress-meta-pill">本地 {{ indexJob.meta.local_candidates_count || 0 }}</span>
        <span class="progress-meta-pill">Kikoeru {{ indexJob.meta.kikoeru_candidates_count || 0 }}</span>
        <span class="progress-meta-pill">DLsite {{ indexJob.meta.dlsite_candidates_count || 0 }}</span>
        <span class="progress-meta-pill">候选 {{ indexJob.meta.combined_candidates_count || indexJob.meta.aggregated_count || 0 }}</span>
        <span class="progress-meta-pill ok">可下载 {{ indexJob.meta.asmr_available_count || 0 }}</span>
      </div>

      <div v-if="indexJob.error_message" class="index-progress-error">{{ indexJob.error_message }}</div>
    </section>

    <section class="circle-shell">
      <aside class="circle-sidebar">
        <div class="sidebar-card">
          <div class="sidebar-head">
            <div>
              <div class="sidebar-overline">社团目录</div>
              <div class="sidebar-title">最近索引</div>
            </div>
            <el-button text class="sidebar-refresh-button" @click="loadRecentCircles">刷新</el-button>
          </div>
          <div class="sidebar-search">
            <el-input v-model="circleSearch" placeholder="筛选已缓存社团" clearable @input="searchCachedCircles" />
          </div>
          <div v-if="circleList.length" class="circle-list">
            <button
              v-for="circle in circleList"
              :key="circle.circle_id"
              type="button"
              class="circle-list-item"
              :class="{ active: activeCircleId === circle.circle_id }"
              @click="selectCircle(circle.circle_id)"
            >
              <div class="circle-list-topline">{{ circle.circle_id }}</div>
              <div class="circle-list-name">{{ circle.circle_name || circle.circle_id }}</div>
              <div class="circle-list-meta">
                <span>{{ formatDateTime(circle.last_indexed_at) }}</span>
                <span>{{ circle.source_mask || '未标记来源' }}</span>
              </div>
            </button>
          </div>
          <el-empty v-else description="还没有社团索引" :image-size="74" />
        </div>
      </aside>

      <main class="circle-main">
        <section class="toolbar-card">
          <div class="toolbar-main">
            <div class="toolbar-copy">
              <div class="toolbar-overline">当前社团</div>
              <div class="toolbar-title">{{ detail.circle_name || '未选择社团' }}</div>
              <div class="toolbar-subtitle">
                <span>{{ detail.source_mask || '等待建立索引' }}</span>
                <span v-if="detail.last_indexed_at">最近刷新 {{ formatDateTime(detail.last_indexed_at) }}</span>
              </div>
            </div>
            <div class="toolbar-metrics">
              <span class="metric-pill owned">服务器已有 {{ detail.owned_count || 0 }}</span>
              <span class="metric-pill warn">服务器缺失 {{ detail.missing_count || 0 }}</span>
              <span class="metric-pill ok">可下载 {{ detail.downloadable_count || 0 }}</span>
              <span class="metric-pill muted">暂不可下载 {{ detail.dl_only_count || 0 }}</span>
            </div>
          </div>

          <div class="toolbar-filters">
            <el-checkbox v-model="filters.onlyMissing" @change="refreshActiveCircle">仅看缺失</el-checkbox>
            <el-checkbox v-model="filters.onlyDownloadable" @change="refreshActiveCircle">仅看可下载</el-checkbox>
            <el-checkbox v-model="filters.includeDlOnly" @change="refreshActiveCircle">包含仅DL</el-checkbox>
          </div>
        </section>

        <section v-if="detail.works?.length" class="works-card">
          <div class="batch-bar">
            <div class="batch-bar-copy">
              <div class="batch-overline">批量下载</div>
              <div class="batch-count">已选 {{ selectedCanonicalRJCodes.length }} 个作品，可下载 {{ selectedDownloadableRJCodes.length }} 个</div>
              <div class="batch-hint">支持单选 / 多选 / 全选。批量刷新会更新选中作品的索引状态，创建下载任务仍只会使用其中 asmr.one 可下载的作品。</div>
            </div>
            <div class="batch-bar-actions">
              <el-button class="batch-action-button" @click="selectAllVisibleWorks">全选当前列表</el-button>
              <el-button class="batch-action-button ghost" @click="clearSelection">清空</el-button>
              <el-button
                class="batch-action-button refresh"
                :disabled="!activeCircleId || indexing || selectedCanonicalRJCodes.length === 0 || isRefreshJobActive"
                :loading="refreshingCurrentCircle"
                @click="refreshSelectedCircleIndex"
              >
                批量刷新选中
              </el-button>
              <el-button class="batch-action-button primary" type="primary" :disabled="selectedDownloadableRJCodes.length === 0" :loading="previewing" @click="openBatchPreview()">创建下载任务</el-button>
            </div>
          </div>

          <section v-if="refreshJob.visible" class="index-progress-card refresh-progress-card">
            <div class="index-progress-head">
              <div>
                <div class="index-progress-title">批量刷新进度</div>
                <div class="index-progress-subtitle">
                  {{ refreshJob.circle_name || detail.circle_name || '当前社团' }} · {{ refreshJob.current_step || '处理中' }}
                </div>
              </div>
              <div class="index-progress-head-actions">
                <el-button
                  v-if="canCancelRefreshJob"
                  size="small"
                  class="index-cancel-button"
                  :loading="cancellingRefreshJob"
                  @click="cancelRefreshJob"
                >
                  取消刷新
                </el-button>
                <div class="index-progress-status" :class="refreshJob.status">{{ refreshJobStatusText }}</div>
              </div>
            </div>

            <el-progress
              :percentage="refreshJob.progress || 0"
              :status="refreshJob.status === 'failed' ? 'exception' : (refreshJob.status === 'completed' ? 'success' : '')"
              :stroke-width="12"
            />

            <div class="index-progress-meta">
              <span class="progress-meta-pill">耗时 {{ formatElapsed(refreshJob.elapsed_seconds) }}</span>
              <span class="progress-meta-pill">总数 {{ refreshJob.selected_count || refreshJob.meta.total_count || 0 }}</span>
              <span class="progress-meta-pill">已处理 {{ refreshJob.meta.processed_count || 0 }}</span>
              <span class="progress-meta-pill ok">有变化 {{ refreshJob.meta.changed_count || 0 }}</span>
              <span class="progress-meta-pill">Kikoeru {{ refreshJob.meta.kikoeru_owned_count || 0 }}</span>
              <span class="progress-meta-pill">asmr.one {{ refreshJob.meta.asmr_available_count || 0 }}</span>
              <span v-if="refreshJob.meta.current_rjcode" class="progress-meta-pill">当前 {{ refreshJob.meta.current_rjcode }}</span>
            </div>

            <div v-if="refreshJob.progress_log?.length" class="refresh-progress-log-list">
              <div
                v-for="entry in refreshJob.progress_log.slice(-6)"
                :key="`${refreshJob.job_id}-${entry.time}-${entry.message}`"
                class="refresh-progress-log-item"
                :class="entry.level || 'info'"
              >
                <span class="refresh-progress-log-time">{{ formatLogTime(entry.time) }}</span>
                <span class="refresh-progress-log-message">{{ entry.message }}</span>
              </div>
            </div>

            <div v-if="refreshJob.error_message" class="index-progress-error">{{ refreshJob.error_message }}</div>
          </section>

          <el-tabs v-model="activeTab" class="circle-tabs">
            <el-tab-pane label="缺失作品" name="missing">
              <div class="work-grid">
                <article
                  v-for="item in pagedMissingWorks"
                  :key="item.canonical_rjcode"
                  class="work-card"
                  :class="{ selected: selectedCanonicals.has(item.canonical_rjcode), 'is-downloaded': item.local_download_ready, 'status-flash': flashedWorkCodes.has(item.canonical_rjcode) }"
                  @click="toggleSelection(item)"
                >
                  <div class="work-card-head">
                    <div v-if="item.local_download_ready" class="work-corner-flag">已下载</div>
                    <div class="work-card-copy">
                      <div class="work-rj">{{ item.source_compare?.work_rjcode || item.canonical_rjcode }}</div>
                      <div class="work-title">{{ item.title || '未命名作品' }}</div>
                    </div>
                  </div>

                  <div class="work-linked">优先版本 {{ item.preferred_variant?.group_short_label || '原作' }} · {{ item.download_plan?.rjcode || item.display_rjcode || item.canonical_rjcode }}</div>

                  <div class="work-tags">
                    <span v-if="item.local_download_ready" class="tag-chip local-ready">本地已下载</span>
                    <span class="tag-chip" :class="{ owned: item.server_owned }">{{ formatServerOwnedLabel(item) }}</span>
                    <span class="tag-chip">DLsite {{ item.has_dlsite ? '有' : '未知' }}</span>
                    <span class="tag-chip" :class="{ ok: item.has_asmr_one }">asmr.one {{ item.has_asmr_one ? '可下载' : '无资源' }}</span>
                  </div>

                  <div v-if="item.has_asmr_one || item.local_download_ready" class="work-actions">
                    <el-button v-if="item.local_download_ready" size="small" class="work-action-button upload" @click.stop="openReimportDialogForWork(item)">直接入库</el-button>
                    <el-button size="small" class="work-action-button" @click.stop="openBatchPreview(item.canonical_rjcode)">预览下载</el-button>
                  </div>
                </article>
              </div>
              <div class="works-pager">
                <el-pagination
                  v-model:current-page="missingPage"
                  :page-size="worksPageSize"
                  layout="total, prev, pager, next"
                  :total="missingWorks.length"
                  background
                />
              </div>
            </el-tab-pane>

            <el-tab-pane label="服务器已拥有" name="owned">
              <div class="owned-list">
                <article v-for="item in pagedOwnedWorks" :key="item.canonical_rjcode" class="owned-card">
                  <div class="owned-card-top">
                    <span class="owned-state-pill">已收录</span>
                    <span class="owned-rj-pill">{{ item.source_compare?.work_rjcode || item.canonical_rjcode }}</span>
                  </div>
                  <div class="owned-title">{{ item.title || item.canonical_rjcode }}</div>
                  <div class="owned-card-bottom">
                    <span class="owned-meta">{{ item.preferred_variant?.group_short_label || '原作' }}</span>
                    <span class="owned-separator">·</span>
                    <span class="owned-path">服务器已收录</span>
                  </div>
                </article>
              </div>
              <div class="works-pager">
                <el-pagination
                  v-model:current-page="ownedPage"
                  :page-size="worksPageSize"
                  layout="total, prev, pager, next"
                  :total="ownedWorks.length"
                  background
                />
              </div>
            </el-tab-pane>

            <el-tab-pane label="来源对比" name="compare">
              <div class="compare-board">
                <div class="compare-head">
                  <div class="compare-col work">作品</div>
                  <div class="compare-col source kikoeru">Kikoeru</div>
                  <div class="compare-col source dlsite">DLsite</div>
                  <div class="compare-col source asmr">asmr.one</div>
                </div>
                <div
                  v-for="item in pagedCompareWorks"
                  :key="`compare-${item.workRjcode}`"
                  class="compare-row"
                >
                  <div class="compare-col work">
                    <div class="compare-work-top">
                      <span class="compare-work-rj">{{ item.workRjcode || '—' }}</span>
                      <span :class="['compare-status-pill', `is-${item.statusKey}`]">{{ item.statusLabel }}</span>
                    </div>
                    <div class="compare-work-title">{{ item.title || item.workRjcode || '未命名作品' }}</div>
                  </div>
                  <div class="compare-col source kikoeru">
                    <div v-if="item.sourceCompare.kikoeru.primary_rjcode" class="compare-chip-list">
                      <span class="compare-chip">{{ item.sourceCompare.kikoeru.primary_rjcode }}</span>
                      <span v-for="badge in item.sourceCompare.kikoeru.variantBadges" :key="`kb-${item.workRjcode}-${badge}`" class="compare-chip is-kikoeru-tag">{{ badge }}</span>
                      <span v-for="tag in normalizeKikoeruTags(item.sourceCompare.kikoeru.tags)" :key="`k-${item.workRjcode}-${tag}`" class="compare-chip is-kikoeru-tag" :class="{ 'has-icon': tag === '字幕' }">
                        <svg v-if="tag === '字幕'" class="kikoeru-tag-icon" viewBox="0 0 16 16" aria-hidden="true">
                          <path d="M6.5 11.2 3.7 8.4l-1.1 1.1 3.9 3.9 7-7-1.1-1.1z" />
                        </svg>
                        <span>{{ tag }}</span>
                      </span>
                    </div>
                    <span v-else class="compare-empty">未收录</span>
                  </div>
                  <div class="compare-col source dlsite">
                    <div v-if="item.sourceCompare.dlsite.all_rjcodes.length" class="compare-chip-list">
                      <span v-for="code in item.sourceCompare.dlsite.all_rjcodes" :key="`d-${item.workRjcode}-${code}`" class="compare-chip">{{ code }}</span>
                    </div>
                    <span v-else class="compare-empty">未发现</span>
                  </div>
                  <div class="compare-col source asmr">
                    <div v-if="item.sourceCompare.asmr_one.primary_rjcode" class="compare-chip-list">
                      <span class="compare-chip is-asmr">{{ item.sourceCompare.asmr_one.primary_rjcode }}</span>
                      <span v-if="item.sourceCompare.asmr_one.primaryBadge" class="compare-chip is-asmr-badge">{{ item.sourceCompare.asmr_one.primaryBadge }}</span>
                    </div>
                    <span v-else class="compare-empty">暂无来源</span>
                  </div>
                </div>
              </div>
              <div class="works-pager">
                <el-pagination
                  v-model:current-page="comparePage"
                  :page-size="comparePageSize"
                  layout="total, prev, pager, next"
                  :total="compareWorks.length"
                  background
                />
              </div>
            </el-tab-pane>

            <el-tab-pane label="索引信息" name="info">
              <div class="info-grid">
                <div class="info-card">
                  <div class="info-label">社团ID</div>
                  <div class="info-value">{{ detail.circle_id || '—' }}</div>
                </div>
                <div class="info-card">
                  <div class="info-label">最近索引</div>
                  <div class="info-value">{{ formatDateTime(detail.last_indexed_at) }}</div>
                </div>
                <div class="info-card">
                  <div class="info-label">来源标记</div>
                  <div class="info-value">{{ detail.source_mask || '—' }}</div>
                </div>
                <div class="info-card">
                  <div class="info-label">可见作品</div>
                  <div class="info-value">{{ detail.works?.length || 0 }}</div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </section>

        <el-empty v-else description="先建立一个社团索引" :image-size="86" />
      </main>
    </section>

    <el-dialog v-model="previewDialogVisible" width="1080px" title="创建下载任务" class="circle-preview-dialog">
      <div v-if="previewLoading" class="dialog-loading">正在生成下载计划...</div>
      <template v-else>
        <div class="preview-toolbar">
          <div class="preview-presets">
            <button type="button" class="preset-chip" @click="applyPreset('wav')">wav</button>
            <button type="button" class="preset-chip" @click="applyPreset('flac')">flac</button>
            <button type="button" class="preset-chip" @click="applyPreset('mp3')">mp3</button>
            <button type="button" class="preset-chip" @click="applyPreset('pdf')">pdf</button>
            <button type="button" class="preset-chip" @click="applyPreset('image')">图片</button>
            <button type="button" class="preset-chip" @click="applyPreset('subtitle')">字幕</button>
            <button type="button" class="preset-chip ghost" @click="applyPreset('audio')">仅音频</button>
            <button type="button" class="preset-chip ghost" @click="resetRecommended">恢复推荐</button>
          </div>
          <div class="preview-stats">{{ selectedFileCount }} 已选，共 {{ formatSize(selectedTotalBytes) }}</div>
        </div>

        <section class="download-settings-card">
          <div class="download-settings-head">
            <div class="download-settings-title">落地设置</div>
            <div class="download-settings-subtitle">社团补全下载会先落到临时目录，再自动按社团名入库，作品目录使用 API 命名后的文件夹名。</div>
          </div>
          <div class="download-settings-grid">
            <label class="setting-field setting-field-wide">
              <span class="setting-label">下载临时目录</span>
              <el-input v-model="downloadSettings.downloadBasePath" placeholder="留空则使用默认临时目录" clearable />
            </label>
            <label class="setting-field">
              <span class="setting-label">目标库存</span>
              <el-select v-model="downloadSettings.targetLibraryId" placeholder="默认媒体库根目录" clearable filterable>
                <el-option
                  v-for="library in targetLibraries"
                  :key="library.id"
                  :label="`${library.name} (${library.type === 'local' ? '本地' : '远程'})`"
                  :value="library.id"
                />
              </el-select>
            </label>
            <label class="setting-field">
              <span class="setting-label">库存内前缀目录</span>
              <el-select v-model="downloadSettings.targetSubdir" placeholder="选择库存内前缀目录" clearable filterable>
                <el-option label="直接按社团名入库 / API 命名后的文件" value="" />
                <el-option
                  v-for="option in targetSubdirOptions"
                  :key="option"
                  :label="option"
                  :value="option"
                />
              </el-select>
            </label>
            <div class="setting-field setting-field-wide setting-static">
              <span class="setting-label">最终行为</span>
              <div class="setting-static-value">
                <span class="setting-pill ok">直接按社团名入库</span>
                <span class="setting-pill">API 命名后的文件</span>
                <span v-if="resolvedTargetRoot" class="setting-hint">目标根目录：{{ resolvedTargetRoot }}</span>
              </div>
            </div>
          </div>
        </section>

        <div class="preview-plan-list">
          <section v-for="plan in previewPlans" :key="plan.session_id" class="preview-plan">
            <div class="preview-plan-head">
              <div>
                <div class="preview-plan-rj">{{ plan.rjcode }}</div>
                <div class="preview-plan-title">{{ plan.title || plan.canonical_rjcode }}</div>
              </div>
              <div class="preview-plan-meta">
                <span>{{ plan.selected_resource_count }} 已选</span>
                <span>{{ formatSize(plan.selected_size_bytes) }}</span>
              </div>
            </div>

            <div class="tree-shell">
              <div class="tree-head">
                <div class="tree-col-check">
                  <input
                    type="checkbox"
                    class="tree-check"
                    :checked="isPlanAllSelected(plan)"
                    :indeterminate.prop="isPlanPartiallySelected(plan)"
                    @click="togglePlanAll(plan)"
                  >
                </div>
                <div class="tree-col-name">文件名</div>
                <div class="tree-col-size">大小</div>
                <div class="tree-col-note">推荐状态</div>
              </div>

              <div class="tree-body">
                <div v-for="row in plan.flatRows" :key="row.id" class="tree-row" :class="{ dir: row.type === 'dir', selected: row.checked }" @click="handleTreeRowClick(plan, row)">
                  <div class="tree-col-check" @click.stop>
                    <input
                      type="checkbox"
                      class="tree-check"
                      :checked="row.checked"
                      :indeterminate.prop="row.indeterminate"
                      @click.stop="toggleTreeRow(plan, row, $event)"
                    >
                  </div>
                  <div class="tree-col-name">
                    <div class="tree-name-cell" :style="{ paddingLeft: `${row.depth * 18 + 6}px` }">
                      <button v-if="row.type === 'dir'" type="button" class="tree-arrow" :class="{ open: plan.expandedIds.has(row.id) }" @click.stop="toggleExpand(plan, row)">
                        &gt;
                      </button>
                      <span v-else class="tree-arrow-placeholder"></span>
                      <span class="tree-name">{{ row.name }}</span>
                    </div>
                  </div>
                  <div class="tree-col-size">{{ formatSize(row.size_bytes) }}</div>
                  <div class="tree-col-note">
                    <template v-if="row.type === 'file'">
                      <span v-for="reason in row.recommended_skip_reasons" :key="reason" class="reason-pill">{{ reason }}</span>
                      <span v-if="!row.recommended_skip_reasons?.length" class="reason-pill ok">推荐下载</span>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </template>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="previewDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="starting" :disabled="selectedFileCount === 0" @click="startBatchDownload">下载</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog
      v-model="downloadWorkbenchVisible"
      width="980px"
      title="社团补全下载任务"
      class="circle-download-workbench"
      :close-on-click-modal="false"
    >
      <div class="workbench-toolbar">
        <div class="workbench-summary">
          <div class="workbench-stat">
            <span class="workbench-stat-label">任务</span>
            <strong class="workbench-stat-value">{{ trackedDownloadTasks.length }}</strong>
          </div>
          <div class="workbench-stat">
            <span class="workbench-stat-label">进行中</span>
            <strong class="workbench-stat-value">{{ processingDownloadTasks.length }}</strong>
          </div>
          <div class="workbench-stat">
            <span class="workbench-stat-label">等待中</span>
            <strong class="workbench-stat-value">{{ pendingDownloadTasks.length }}</strong>
          </div>
          <div class="workbench-stat">
            <span class="workbench-stat-label">完成</span>
            <strong class="workbench-stat-value">{{ completedDownloadTasks.length }}</strong>
          </div>
          <div class="workbench-stat danger">
            <span class="workbench-stat-label">失败</span>
            <strong class="workbench-stat-value">{{ failedDownloadTasks.length }}</strong>
          </div>
        </div>
        <div class="workbench-actions">
          <el-button size="small" class="workbench-action-btn is-refresh" @click="refreshDownloadWorkbench({ silent: true })">刷新</el-button>
          <el-button size="small" class="workbench-action-btn is-background" @click="hideDownloadWorkbenchToBackground">隐藏到后台</el-button>
          <el-button size="small" class="workbench-action-btn is-close" @click="closeDownloadWorkbench">关闭</el-button>
        </div>
      </div>

      <div v-if="trackedDownloadTasks.length" class="download-task-list">
        <article v-for="task in trackedDownloadTasks" :key="task.id" class="download-task-card">
          <div class="download-task-head">
            <div class="download-task-heading">
              <div class="download-task-rj-row">
                <div class="download-task-rj">{{ task.rjcode || '未知 RJ' }}</div>
                <span v-if="isTaskDownloaded(task)" class="download-state-chip is-downloaded">已下载</span>
              </div>
              <div class="download-task-title">{{ task.work_title || task.source_label || '未命名任务' }}</div>
            </div>
            <div class="download-task-status">
              <span class="setting-pill" :class="getDownloadTaskStatusClass(task)">{{ getDownloadTaskStatusLabel(task) }}</span>
            </div>
          </div>
          <el-progress
            :percentage="Number(task.progress || 0)"
            :status="getDownloadTaskProgressStatus(task)"
            :stroke-width="10"
            :show-text="false"
          />
          <div class="download-task-step">{{ task.current_step || '等待处理' }}</div>
          <div v-if="getTaskFailureText(task)" class="download-task-error">
            <span class="download-task-error-label">失败原因</span>
            <span class="download-task-error-text">{{ getTaskFailureText(task) }}</span>
          </div>
          <div v-if="canRetryDownloadTask(task) || isTaskDownloaded(task)" class="download-task-actions">
            <el-button v-if="canRetryDownloadTask(task)" size="small" class="download-task-action-btn is-primary" :loading="retryingTaskIds.has(task.id)" @click="retryDownloadTask(task)">重试失败项</el-button>
            <el-button v-if="String(task.status || '') === 'waiting_retry'" size="small" class="download-task-action-btn" :loading="retryingTaskIds.has(`${task.id}:waiting`)" @click="retryWaitingDownloadTask(task)">立即重试</el-button>
            <el-button v-if="isTaskDownloaded(task)" size="small" class="download-task-action-btn is-upload" @click="openReimportDialog(task)">直接入库</el-button>
          </div>
          <div v-if="getRetryableFailedFiles(task).length" class="download-failed-list">
            <div class="download-file-title">失败文件</div>
            <div v-for="file in getRetryableFailedFiles(task)" :key="`${task.id}-failed-${file.relative_path || file.name}`" class="download-failed-item">
              <div class="download-failed-main">
                <div class="download-file-name">{{ file.name || file.relative_path || '未知文件' }}</div>
                <div class="download-failed-reason">{{ file.reason || file.exception_type || '失败' }}</div>
              </div>
              <el-button
                size="small"
                class="download-task-action-btn is-primary"
                :loading="retryingTaskIds.has(`${task.id}:${file.relative_path || file.name}`)"
                @click="retrySingleFailedFile(task, file)"
              >
                重试这个文件
              </el-button>
            </div>
          </div>
          <div class="download-task-meta-grid">
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">下载目录</span>
              <span class="download-task-meta-value">{{ task.task_metadata?.local_download_root || task.session_state?.local_download_root || task.task_metadata?.download_root || task.task_metadata?.download_base_path || '默认临时目录' }}</span>
            </div>
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">最终路径</span>
              <span class="download-task-meta-value">{{ task.task_metadata?.final_output_path || task.output_path || task.task_metadata?.target_path || '处理中' }}</span>
            </div>
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">{{ getTaskTransferLabel(task) }}</span>
              <span class="download-task-meta-value">{{ formatSize(getTaskTransferBytes(task)) }}</span>
            </div>
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">上传文件</span>
              <span class="download-task-meta-value">{{ getUploadedCount(task) }} 个</span>
            </div>
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">耗时</span>
              <span class="download-task-meta-value">{{ formatDurationMs(task.performance_metrics?.duration_ms || task.task_metadata?.performance_metrics?.duration_ms || 0) }}</span>
            </div>
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">失败统计</span>
              <span class="download-task-meta-value">{{ getFailureSummary(task) }}</span>
            </div>
          </div>
          <div v-if="task.download_files?.length" class="download-file-list">
            <div class="download-file-title">文件进度</div>
            <div v-for="file in task.download_files.slice(0, 8)" :key="`${task.id}-${file.name}`" class="download-file-item">
              <div class="download-file-row">
                <div class="download-file-name">{{ file.name }}</div>
                <div class="download-file-size">{{ formatSize(file.downloaded) }} / {{ formatSize(file.total) }}</div>
              </div>
              <el-progress :percentage="Number(file.progress || 0)" :stroke-width="6" :show-text="false" />
            </div>
          </div>
          <div v-if="task.upload_files?.length" class="download-file-list upload-stage">
            <div class="download-file-title">上传 / 入库进度</div>
            <div v-for="file in task.upload_files.slice(0, 8)" :key="`${task.id}-upload-${file.name}`" class="download-file-item">
              <div class="download-file-row">
                <div class="download-file-name">{{ file.name }}</div>
                <div class="download-file-size">{{ formatSize(file.uploaded) }} / {{ formatSize(file.total) }}</div>
              </div>
              <el-progress :percentage="Number(file.progress || 0)" :stroke-width="6" :show-text="false" color="#31b26d" />
            </div>
          </div>
          <div v-if="task.uploaded_files?.length" class="download-result-list">
            <div class="download-file-title">已上传 / 已入库</div>
            <div v-for="file in task.uploaded_files.slice(0, 6)" :key="`${task.id}-uploaded-${file.name}`" class="download-result-item">
              <span class="download-result-name">{{ file.name }}</span>
              <span class="download-result-path">{{ file.upload_path }}</span>
            </div>
          </div>
          <div v-if="task.progress_log?.length" class="download-log-list">
            <div class="download-file-title">过程日志</div>
            <div v-for="entry in task.progress_log.slice(-8)" :key="`${task.id}-${entry.time}-${entry.message}`" class="download-log-item" :class="entry.level || 'info'">
              <span class="download-log-time">{{ formatLogTime(entry.time) }}</span>
              <span class="download-log-message">{{ entry.message }}</span>
            </div>
          </div>
        </article>
      </div>
      <el-empty v-else description="暂无社团补全下载任务" :image-size="72" />
    </el-dialog>

    <el-dialog v-model="reimportDialogVisible" width="860px" title="从已下载内容直接入库" class="circle-reimport-dialog">
      <div class="reimport-dialog-body">
          <div v-if="reimportTrackedTask" class="reimport-progress-card">
            <div class="reimport-progress-head">
              <span class="reimport-progress-title">入库进度</span>
              <span class="reimport-progress-status">{{ getDownloadTaskStatusLabel(reimportTrackedTask) }}</span>
            </div>
            <div class="reimport-progress-metrics">
              <span class="reimport-progress-metric">资源 {{ getTaskResourceCount(reimportTrackedTask) }} 个</span>
              <span class="reimport-progress-metric">{{ getTaskTransferLabel(reimportTrackedTask) }} {{ formatSize(getTaskTransferBytes(reimportTrackedTask)) }}</span>
              <span class="reimport-progress-metric">已上传 {{ getUploadedCount(reimportTrackedTask) }} 个</span>
              <span class="reimport-progress-metric">上传速度 {{ formatSpeed(getUploadSpeedBytes(reimportTrackedTask)) }}</span>
              <span class="reimport-progress-metric">预计剩余 {{ formatTaskEta(reimportTrackedTask) }}</span>
            </div>
            <el-progress
              :percentage="getReimportOverallPercent(reimportTrackedTask)"
              :status="getDownloadTaskProgressStatus(reimportTrackedTask)"
              :stroke-width="10"
              :show-text="false"
            />
            <div class="reimport-progress-step">{{ reimportTrackedTask.current_step || '处理中' }}</div>
            <div class="reimport-summary-grid">
              <div class="reimport-summary-item">
                <span class="reimport-summary-label">字节进度</span>
                <span class="reimport-summary-value">{{ formatSize(getUploadTransferredBytes(reimportTrackedTask)) }} / {{ formatSize(getUploadTotalBytes(reimportTrackedTask)) }}</span>
              </div>
              <div class="reimport-summary-item">
                <span class="reimport-summary-label">上传阶段</span>
                <span class="reimport-summary-value">{{ getUploadStageLabel(reimportTrackedTask) }}</span>
              </div>
              <div class="reimport-summary-item">
                <span class="reimport-summary-label">已运行</span>
                <span class="reimport-summary-value">{{ formatDurationMs(getTaskElapsedMs(reimportTrackedTask)) }}</span>
              </div>
              <div class="reimport-summary-item">
                <span class="reimport-summary-label">当前文件</span>
                <span class="reimport-summary-value">{{ getCurrentUploadSequenceLabel(reimportTrackedTask) }}</span>
              </div>
            </div>
            <div v-if="reimportTrackedTask.upload_files?.length" class="reimport-file-progress-list">
              <div class="reimport-file-progress-title">单文件上传进度</div>
              <div
                v-for="file in reimportTrackedTask.upload_files.slice(0, 12)"
                :key="`reimport-upload-${file.name}`"
                class="reimport-file-progress-item"
              >
                <div class="reimport-file-progress-row">
                  <div class="reimport-file-progress-name">{{ file.name }}</div>
                  <div class="reimport-file-progress-size">{{ formatSize(file.uploaded) }} / {{ formatSize(file.total) }}</div>
                </div>
                <div class="reimport-file-progress-meta">
                  <span>{{ formatSpeed(file.speed_bytes_per_sec) }}</span>
                  <span>剩余 {{ formatFileEta(file) }}</span>
                  <span>{{ Number(file.progress || 0) }}%</span>
                </div>
                <el-progress
                  :percentage="Number(file.progress || 0)"
                  :stroke-width="6"
                  :show-text="false"
                  color="#31b26d"
                />
              </div>
            </div>
            <div v-if="reimportTrackedTask.uploaded_files?.length" class="reimport-file-result-list">
              <div class="reimport-file-progress-title">已完成上传</div>
              <div
                v-for="file in reimportTrackedTask.uploaded_files.slice(-8)"
                :key="`reimport-uploaded-${file.name}`"
                class="reimport-file-result-item"
              >
                <div class="reimport-file-result-copy">
                  <span class="reimport-file-result-name">{{ file.name }}</span>
                  <span class="reimport-file-result-path">{{ file.upload_path }}</span>
                </div>
              </div>
            </div>
          </div>
        <label class="setting-field">
          <span class="setting-label">目标库存</span>
          <el-select v-model="reimportForm.targetLibraryId" placeholder="选择目标库存" clearable filterable>
            <el-option
              v-for="library in targetLibraries"
              :key="library.id"
              :label="`${library.name} (${library.type === 'local' ? '本地' : '远程'})`"
              :value="library.id"
            />
          </el-select>
        </label>
        <label class="setting-field">
          <span class="setting-label">库存内前缀目录</span>
          <el-select v-model="reimportForm.targetSubdir" placeholder="选择库存内前缀目录" clearable filterable>
            <el-option label="直接按社团名入库 / API 命名后的文件" value="" />
            <el-option
              v-for="option in targetSubdirOptions"
              :key="option"
              :label="option"
              :value="option"
            />
          </el-select>
        </label>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="reimportDialogVisible = false">取消</el-button>
          <el-button
            v-if="reimportTrackedTask && ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(reimportTrackedTask.status || ''))"
            @click="hideReimportDialogToBackground"
          >
            挂到后台
          </el-button>
          <el-button
            v-if="!isReimportTaskActive(reimportTrackedTask)"
            type="primary"
            :loading="reimportSubmitting"
            :disabled="!reimportForm.targetLibraryId"
            @click="submitReimportDownloaded"
          >
            开始入库
          </el-button>
        </span>
      </template>
    </el-dialog>

    <div v-if="showDownloadBackgroundCard" class="circle-download-floating-card">
      <div class="circle-download-floating-head">
        <div>
          <div class="circle-download-floating-title">社团补全下载正在后台运行</div>
          <div class="circle-download-floating-mode">
            {{ activeBackgroundDownloadTask ? `${activeBackgroundDownloadTask.rjcode || 'RJ'} · ${activeBackgroundDownloadTask.work_title || activeBackgroundDownloadTask.source_label || '-'}` : '保留当前下载队列与进度状态' }}
          </div>
        </div>
        <div class="circle-download-floating-count">{{ trackedDownloadTasks.length }}</div>
      </div>
      <el-progress
        :percentage="backgroundDownloadPercent"
        :status="failedDownloadTasks.length && !processingDownloadTasks.length && !pendingDownloadTasks.length ? 'exception' : (completedDownloadTasks.length === trackedDownloadTasks.length && trackedDownloadTasks.length ? 'success' : '')"
        :stroke-width="8"
        :show-text="false"
      />
      <div class="circle-download-floating-chip-row">
        <span class="circle-download-floating-chip">进行中 {{ processingDownloadTasks.length }}</span>
        <span class="circle-download-floating-chip">等待中 {{ pendingDownloadTasks.length }}</span>
        <span class="circle-download-floating-chip">完成 {{ completedDownloadTasks.length }}</span>
        <span class="circle-download-floating-chip danger">失败 {{ failedDownloadTasks.length }}</span>
      </div>
      <div class="circle-download-floating-text">
        {{ activeBackgroundDownloadTask?.current_step || '隐藏后继续保留下载队列和进度。' }}
      </div>
      <div class="circle-download-floating-actions">
        <el-button size="small" type="primary" @click="resumeDownloadWorkbenchFromBackground">恢复工作台</el-button>
        <el-button size="small" @click="closeDownloadWorkbench">关闭</el-button>
      </div>
    </div>

    <div v-if="showReimportBackgroundCard" class="circle-download-floating-card reimport-floating-card">
      <div class="circle-download-floating-head">
        <div>
          <div class="circle-download-floating-title">直接入库正在后台运行</div>
          <div class="circle-download-floating-mode">
            {{ reimportTrackedTask ? `${reimportTrackedTask.rjcode || 'RJ'} · ${reimportTrackedTask.work_title || reimportTrackedTask.source_label || '-'}` : '保留当前入库进度与单文件上传状态' }}
          </div>
        </div>
        <div class="circle-download-floating-count">{{ getReimportOverallPercent(reimportTrackedTask) }}%</div>
      </div>
      <el-progress
        :percentage="getReimportOverallPercent(reimportTrackedTask)"
        :status="getDownloadTaskProgressStatus(reimportTrackedTask)"
        :stroke-width="8"
        :show-text="false"
      />
      <div class="circle-download-floating-chip-row">
        <span class="circle-download-floating-chip">资源 {{ getTaskResourceCount(reimportTrackedTask) }}</span>
        <span class="circle-download-floating-chip">已上传 {{ getUploadedCount(reimportTrackedTask) }}</span>
        <span class="circle-download-floating-chip">速度 {{ formatSpeed(getUploadSpeedBytes(reimportTrackedTask)) }}</span>
        <span class="circle-download-floating-chip">剩余 {{ formatTaskEta(reimportTrackedTask) }}</span>
        <span class="circle-download-floating-chip">{{ getDownloadTaskStatusLabel(reimportTrackedTask) }}</span>
      </div>
      <div class="circle-download-floating-text">
        {{ reimportTrackedTask?.current_step || '隐藏后继续保留入库进度。' }}
      </div>
      <div class="circle-download-floating-actions">
        <el-button size="small" type="primary" @click="resumeReimportDialogFromBackground">恢复面板</el-button>
        <el-button size="small" @click="closeReimportBackgroundCard">关闭</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api, { asmrSyncApi, circleCompletionApi, libraryApi } from '../api'

const CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY = 'prekikoeru.circleCompletion.targetSubdirs'
const CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY = 'prekikoeru.circleCompletion.downloadWorkbench'
const CIRCLE_COMPLETION_REFRESH_JOB_KEY = 'prekikoeru.circleCompletion.refreshJob'

const circleQuery = ref('')
const circleSearch = ref('')
const indexing = ref(false)
const previewing = ref(false)
const previewLoading = ref(false)
const starting = ref(false)
const activeCircleId = ref('')
const circleList = ref([])
const detail = reactive({
  circle_id: '',
  circle_name: '',
  source_mask: '',
  last_indexed_at: '',
  owned_count: 0,
  missing_count: 0,
  downloadable_count: 0,
  dl_only_count: 0,
  works: []
})
const filters = reactive({
  onlyMissing: false,
  onlyDownloadable: false,
  includeDlOnly: false
})
const activeTab = ref('missing')
const selectedCanonicals = ref(new Set())
const flashedWorkCodes = ref(new Set())
const previewDialogVisible = ref(false)
const previewPlans = ref([])
const libraries = ref([])
const trackedDownloadTaskIds = ref([])
const downloadWorkbenchVisible = ref(false)
const downloadWorkbenchBackgroundActive = ref(false)
const downloadWorkbenchRefreshing = ref(false)
const trackedDownloadTasks = ref([])
const retryingTaskIds = ref(new Set())
const reimportDialogVisible = ref(false)
const reimportSubmitting = ref(false)
const reimportTargetTask = ref(null)
const reimportTrackingTaskId = ref('')
const reimportBackgroundActive = ref(false)
const reimportForm = reactive({
  targetLibraryId: '',
  targetSubdir: '',
})
const worksPageSize = 24
const comparePageSize = 10
const missingPage = ref(1)
const ownedPage = ref(1)
const comparePage = ref(1)
const indexJob = reactive({
  visible: false,
  job_id: '',
  status: '',
  progress: 0,
  current_step: '',
  circle_query: '',
  elapsed_seconds: 0,
  error_message: '',
  meta: {}
})
let indexJobTimer = null
const cancellingIndexJob = ref(false)
const refreshingCurrentCircle = ref(false)
const refreshJob = reactive({
  visible: false,
  job_id: '',
  status: '',
  progress: 0,
  current_step: '',
  circle_id: '',
  circle_name: '',
  selected_count: 0,
  elapsed_seconds: 0,
  auto_hide_at: '',
  changed_codes: [],
  error_message: '',
  meta: {},
  result: {},
  progress_log: []
})
let refreshJobTimer = null
let refreshJobAutoHideTimer = null
const cancellingRefreshJob = ref(false)
const downloadSettings = reactive({
  downloadBasePath: '',
  targetLibraryId: '',
  targetSubdir: '',
  namingMode: 'api',
  classifyMode: 'circle'
})
const cachedTargetSubdirs = ref([])
let flashedWorkTimer = null

const missingWorks = computed(() => (detail.works || []).filter(item => !item.owned))
const ownedWorks = computed(() => (detail.works || []).filter(item => item.owned))
const pagedMissingWorks = computed(() => {
  const start = (missingPage.value - 1) * worksPageSize
  return missingWorks.value.slice(start, start + worksPageSize)
})
const pagedOwnedWorks = computed(() => {
  const start = (ownedPage.value - 1) * worksPageSize
  return ownedWorks.value.slice(start, start + worksPageSize)
})
const compareWorks = computed(() => (detail.works || []).map(item => ({
  workRjcode: String(item?.source_compare?.work_rjcode || item?.canonical_rjcode || '').trim(),
  title: String(item?.title || '').trim(),
  preferredVariantLabel: String(item?.preferred_variant?.label || '优先版本 未标记').trim(),
  statusLabel: item?.server_owned
    ? formatServerOwnedLabel(item)
    : (item?.has_asmr_one ? '可下载' : '暂无来源'),
  statusKey: item?.server_owned
    ? 'owned'
    : (item?.has_asmr_one ? 'downloadable' : 'dl_only'),
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
    },
  }
})))

function formatServerOwnedLabel(item) {
  if (!item?.server_owned) return '服务器缺失'
  const matched = String(
    item?.server_match_primary_rjcode ||
    item?.source_compare?.kikoeru?.matched_rjcode ||
    item?.source_compare?.kikoeru?.primary_rjcode ||
    ''
  ).trim()
  return matched ? `服务器已有 · ${matched}` : '服务器已有'
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

function flashChangedWorks(codes = []) {
  const normalized = [...new Set((codes || []).map(code => String(code || '').trim()).filter(Boolean))]
  if (!normalized.length) return
  flashedWorkCodes.value = new Set(normalized)
  if (flashedWorkTimer) {
    window.clearTimeout(flashedWorkTimer)
    flashedWorkTimer = null
  }
  flashedWorkTimer = window.setTimeout(() => {
    flashedWorkCodes.value = new Set()
    flashedWorkTimer = null
  }, 3000)
}

function prioritizeChangedWorks(codes = []) {
  const normalized = [...new Set((codes || []).map(code => String(code || '').trim()).filter(Boolean))]
  if (!normalized.length || !Array.isArray(detail.works) || !detail.works.length) return
  const order = new Map(normalized.map((code, index) => [code, index]))
  detail.works = [...detail.works].sort((left, right) => {
    const leftIndex = order.has(left?.canonical_rjcode) ? order.get(left.canonical_rjcode) : Number.POSITIVE_INFINITY
    const rightIndex = order.has(right?.canonical_rjcode) ? order.get(right.canonical_rjcode) : Number.POSITIVE_INFINITY
    if (leftIndex !== rightIndex) return leftIndex - rightIndex
    return 0
  })
}

const pagedCompareWorks = computed(() => {
  const start = (comparePage.value - 1) * comparePageSize
  return compareWorks.value.slice(start, start + comparePageSize)
})
const selectedCanonicalRJCodes = computed(() => [...selectedCanonicals.value])
const selectedDownloadableRJCodes = computed(() => selectedCanonicalRJCodes.value.filter(code => {
  const item = (detail.works || []).find(work => work.canonical_rjcode === code)
  return Boolean(item?.has_asmr_one)
}))
const selectedFileCount = computed(() => previewPlans.value.reduce((sum, plan) => sum + (plan.selected_resource_count || 0), 0))
const selectedTotalBytes = computed(() => previewPlans.value.reduce((sum, plan) => sum + (plan.selected_size_bytes || 0), 0))
const targetLibraries = computed(() => (libraries.value || []).filter(item => item?.enabled !== false))
const selectedTargetLibrary = computed(() => targetLibraries.value.find(item => item.id === downloadSettings.targetLibraryId) || null)
const targetSubdirOptions = computed(() => [...new Set((cachedTargetSubdirs.value || []).filter(Boolean))])
const resolvedTargetRoot = computed(() => {
  const root = String(selectedTargetLibrary.value?.root_path || '').trim()
  const prefix = String(downloadSettings.targetSubdir || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  if (root && prefix) return `${root}${root.includes('/') ? '/' : '\\'}${prefix}`
  return root || prefix || ''
})
const processingDownloadTasks = computed(() => trackedDownloadTasks.value.filter(task => ['processing'].includes(String(task.status || ''))))
const pendingDownloadTasks = computed(() => trackedDownloadTasks.value.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task.status || ''))))
const completedDownloadTasks = computed(() => trackedDownloadTasks.value.filter(task => String(task.status || '') === 'completed'))
const failedDownloadTasks = computed(() => trackedDownloadTasks.value.filter(task => String(task.status || '') === 'failed'))
const showDownloadBackgroundCard = computed(() => downloadWorkbenchBackgroundActive.value && !downloadWorkbenchVisible.value && trackedDownloadTaskIds.value.length > 0)
const activeBackgroundDownloadTask = computed(() => processingDownloadTasks.value[0] || pendingDownloadTasks.value[0] || trackedDownloadTasks.value[0] || null)
const reimportTrackedTask = computed(() => trackedDownloadTasks.value.find(task => String(task.id || '') === String(reimportTrackingTaskId.value || '').trim()) || null)
const showReimportBackgroundCard = computed(() =>
  reimportBackgroundActive.value
  && !reimportDialogVisible.value
  && Boolean(reimportTrackedTask.value)
  && ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(reimportTrackedTask.value?.status || ''))
)
const backgroundDownloadPercent = computed(() => {
  if (!trackedDownloadTasks.value.length) return 0
  const total = trackedDownloadTasks.value.reduce((sum, task) => sum + Number(task.progress || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total / trackedDownloadTasks.value.length)))
})
const indexJobStatusText = computed(() => {
  if (indexJob.error_message === '用户取消' || indexJob.current_step === '已取消') return '已取消'
  if (indexJob.status === 'completed') return '已完成'
  if (indexJob.status === 'failed') return '失败'
  if (indexJob.status === 'processing') return '进行中'
  return '等待中'
})
const canCancelIndexJob = computed(() =>
  Boolean(indexJob.job_id) && ['pending', 'processing'].includes(String(indexJob.status || ''))
)
const refreshJobStatusText = computed(() => {
  if (refreshJob.error_message === '用户取消' || refreshJob.current_step === '已取消') return '已取消'
  if (refreshJob.status === 'completed') return '已完成'
  if (refreshJob.status === 'failed') return '失败'
  if (refreshJob.status === 'processing') return '进行中'
  return '等待中'
})
const isRefreshJobActive = computed(() =>
  Boolean(refreshJob.job_id) && ['pending', 'processing'].includes(String(refreshJob.status || ''))
)
const canCancelRefreshJob = computed(() => isRefreshJobActive.value)

onMounted(async () => {
  hydrateRefreshJobState()
  hydrateDownloadWorkbenchState()
  loadCachedTargetSubdirs()
  await Promise.all([loadRecentCircles(), loadLibraries()])
  if (trackedDownloadTaskIds.value.length) await refreshDownloadWorkbench()
  if (isRefreshJobActive.value) await pollRefreshJob(refreshJob.job_id, { silentFinish: true })
  else if (refreshJob.job_id && refreshJob.status === 'completed') {
    if (refreshJob.changed_codes?.length) {
      await refreshActiveCircle()
      prioritizeChangedWorks(refreshJob.changed_codes)
      flashChangedWorks(refreshJob.changed_codes)
    }
    resumeRefreshJobAutoHide()
  }
})

onActivated(() => {
  if (indexJob.job_id && !['completed', 'failed'].includes(indexJob.status)) {
    indexing.value = true
    pollIndexJob(indexJob.job_id)
  }
  if (isRefreshJobActive.value) {
    refreshingCurrentCircle.value = true
    pollRefreshJob(refreshJob.job_id, { silentFinish: true })
  } else if (refreshJob.job_id && refreshJob.status === 'completed') {
    if (refreshJob.changed_codes?.length && activeCircleId.value) {
      refreshActiveCircle().then(() => {
        prioritizeChangedWorks(refreshJob.changed_codes)
        flashChangedWorks(refreshJob.changed_codes)
      }).catch(() => {})
    }
    resumeRefreshJobAutoHide()
  }
  if (trackedDownloadTaskIds.value.length) {
    refreshDownloadWorkbench()
  }
})

onBeforeUnmount(() => {
  stopIndexJobPolling()
  stopRefreshJobPolling()
  stopRefreshJobAutoHide()
  stopDownloadWorkbenchPolling()
})

watch(activeTab, (tab) => {
  if (tab === 'missing') missingPage.value = 1
  if (tab === 'owned') ownedPage.value = 1
  if (tab === 'compare') comparePage.value = 1
})

watch(() => detail.works, () => {
  missingPage.value = 1
  ownedPage.value = 1
  comparePage.value = 1
}, { deep: true })

watch(downloadWorkbenchVisible, (visible) => {
  persistDownloadWorkbenchState()
  if (visible || downloadWorkbenchBackgroundActive.value) startDownloadWorkbenchPolling()
  else stopDownloadWorkbenchPolling()
})

watch(downloadWorkbenchBackgroundActive, () => {
  persistDownloadWorkbenchState()
  if (downloadWorkbenchVisible.value || downloadWorkbenchBackgroundActive.value) startDownloadWorkbenchPolling()
  else stopDownloadWorkbenchPolling()
})

watch(trackedDownloadTaskIds, () => {
  persistDownloadWorkbenchState()
}, { deep: true })

watch(
  () => [refreshJob.job_id, refreshJob.status, refreshJob.progress, refreshJob.current_step, refreshJob.elapsed_seconds].join(':'),
  () => {
    persistRefreshJobState()
  }
)

watch(() => downloadSettings.targetSubdir, (value) => {
  if (value) rememberTargetSubdir(value)
})

watch(
  () => [reimportTrackedTask.value?.id, reimportTrackedTask.value?.status, reimportTrackedTask.value?.completed_at].join(':'),
  async (value, previousValue) => {
    if (!value || value === previousValue) return
    if (!reimportTrackedTask.value || !isTaskFinished(reimportTrackedTask.value)) return
    try {
      await Promise.all([
        refreshDownloadWorkbench({ silent: true }),
        activeCircleId.value ? refreshActiveCircle() : Promise.resolve()
      ])
    } catch (_) {}
  }
)

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index === 0 ? 0 : 2)} ${units[index]}`
}

function formatElapsed(seconds) {
  const total = Math.max(0, Math.round(Number(seconds || 0)))
  const mins = Math.floor(total / 60)
  const secs = total % 60
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

function formatLogTime(value) {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString()
}

function formatDurationMs(durationMs) {
  const totalSeconds = Math.max(0, Math.round(Number(durationMs || 0) / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60
  if (hours > 0) return `${hours}时${mins}分${secs}秒`
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

function formatEtaSeconds(seconds) {
  const totalSeconds = Math.max(0, Math.round(Number(seconds || 0)))
  if (!totalSeconds) return '—'
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  if (hours > 0) return `${hours}时${Math.floor((totalSeconds % 3600) / 60)}分`
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

function formatSpeed(bytesPerSec) {
  const value = Number(bytesPerSec || 0)
  return value > 0 ? `${formatSize(value)}/s` : '—'
}

function isReimportTaskActive(task) {
  return ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task?.status || ''))
}

function isTaskFinished(task) {
  return ['completed', 'failed'].includes(String(task?.status || ''))
}

function formatTaskEta(task) {
  if (isTaskFinished(task) || getReimportOverallPercent(task) >= 100) return '完成'
  return formatEtaSeconds(getUploadEtaSeconds(task))
}

function formatFileEta(file) {
  if (Number(file?.progress || 0) >= 100) return '完成'
  return formatEtaSeconds(file?.eta_seconds)
}

function getUploadRuntime(task) {
  const runtime = task?.upload_runtime || task?.performance_metrics?.upload_runtime || task?.task_metadata?.performance_metrics?.upload_runtime || {}
  return runtime && typeof runtime === 'object' ? runtime : {}
}

function getUploadTransferredBytes(task) {
  const runtimeBytes = Number(getUploadRuntime(task)?.transferred_bytes || 0)
  if (runtimeBytes > 0) return runtimeBytes
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  return uploadFiles.reduce((sum, item) => sum + Number(item?.uploaded || 0), 0)
}

function getUploadTotalBytes(task) {
  const runtimeBytes = Number(getUploadRuntime(task)?.total_bytes || 0)
  if (runtimeBytes > 0) return runtimeBytes
  const uploadFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  const totalBytes = uploadFiles.reduce((sum, item) => sum + Number(item?.total || 0), 0)
  if (totalBytes > 0) return totalBytes
  return getTaskTransferBytes(task)
}

function getUploadSpeedBytes(task) {
  const runtimeSpeed = Number(getUploadRuntime(task)?.speed_bytes_per_sec || 0)
  if (runtimeSpeed > 0) return runtimeSpeed
  if (isTaskFinished(task)) {
    const details = task?.performance_metrics || task?.task_metadata?.performance_metrics || {}
    return Number(details?.average_upload_speed_bytes || 0)
  }
  return 0
}

function getUploadEtaSeconds(task) {
  return Number(getUploadRuntime(task)?.eta_seconds || 0)
}

function getTaskElapsedMs(task) {
  const runtime = getUploadRuntime(task)
  const startValue = runtime?.started_at || task?.started_at || task?.created_at
  const endValue = runtime?.ended_at || task?.completed_at || runtime?.updated_at
  if (!startValue) return 0
  const start = new Date(startValue)
  const end = endValue ? new Date(endValue) : new Date()
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return 0
  return Math.max(0, end.getTime() - start.getTime())
}

function getReimportOverallPercent(task) {
  const runtimeProgress = Number(getUploadRuntime(task)?.progress || 0)
  if (runtimeProgress > 0) return Math.min(100, runtimeProgress)
  if (isTaskFinished(task) && getUploadedCount(task) > 0) return 100
  return Math.min(100, Number(task?.progress || 0))
}

function getCurrentUploadSequenceLabel(task) {
  const runtime = getUploadRuntime(task)
  const current = Number(runtime?.current_file_index || 0)
  const total = Number(runtime?.total_files || getTaskResourceCount(task) || 0)
  if (current > 0 && total > 0) return `${current} / ${total}`
  if (total > 0) return `0 / ${total}`
  return '—'
}

function getUploadStageLabel(task) {
  const runtime = getUploadRuntime(task)
  const stage = String(runtime?.stage || '').trim()
  if (stage === 'library_upload') return '远程入库上传'
  if (stage === 'upload') return '自动上传'
  if (isReimportTask(task)) return '准备入库'
  return '处理中'
}

function hasTaskFailures(task) {
  if (!task) return false
  const failedFiles = Array.isArray(task.failed_files) ? task.failed_files : []
  const verificationFailures = Array.isArray(task.verification_failures) ? task.verification_failures : []
  return Boolean(failedFiles.length || verificationFailures.length || String(task.task_metadata?.failure_reason || '').trim() || String(task.error_message || '').trim())
}

function getDownloadTaskStatusLabel(taskOrStatus) {
  const task = typeof taskOrStatus === 'object' && taskOrStatus !== null ? taskOrStatus : null
  const status = task ? (task.display_status || task.status) : taskOrStatus
  if (task && String(status || '') === 'completed' && hasTaskFailures(task)) {
    return '部分失败'
  }
  const map = {
    pending: '等待中',
    processing: '处理中',
    completed: '已完成',
    partial_failed: '部分失败',
    failed: '失败',
    paused: '已暂停',
    waiting_retry: '等待重试'
  }
  return map[String(status || '')] || String(status || '未知')
}

function getDownloadTaskStatusClass(task) {
  const status = String(task?.display_status || task?.status || '')
  return {
    ok: status === 'completed' && !hasTaskFailures(task),
    warning: status === 'partial_failed' || (status === 'completed' && hasTaskFailures(task)),
    danger: status === 'failed'
  }
}

function getDownloadTaskProgressStatus(task) {
  const status = String(task?.display_status || task?.status || '')
  if (status === 'failed') return 'exception'
  if (status === 'partial_failed' || (status === 'completed' && hasTaskFailures(task))) return 'warning'
  if (status === 'completed') return 'success'
  return ''
}

function getTaskFailureText(task) {
  if (!task) return ''
  const fromMeta = String(task.task_metadata?.failure_reason || '').trim()
  if (fromMeta) return fromMeta
  const errorMessage = String(task.error_message || '').trim()
  if (errorMessage) return errorMessage
  const failedFiles = Array.isArray(task.failed_files) ? task.failed_files : []
  if (failedFiles.length) {
    return failedFiles
      .slice(0, 3)
      .map(item => `${item.name || '未知文件'}: ${item.reason || item.exception_type || '失败'}`)
      .join(' / ')
  }
  const verificationFailures = Array.isArray(task.verification_failures) ? task.verification_failures : []
  if (verificationFailures.length) {
    return verificationFailures
      .slice(0, 2)
      .map(item => `${item.name || item.relative_path || '文件'} MD5 校验失败`)
      .join(' / ')
  }
  return ''
}

function getUploadedCount(task) {
  const uploaded = Array.isArray(task?.uploaded_files) ? task.uploaded_files.length : 0
  if (uploaded) return uploaded
  const summaryUploaded = Number(task?.task_metadata?.upload_summary?.uploaded || task?.upload_summary?.uploaded || 0)
  if (summaryUploaded) return summaryUploaded
  const progressFiles = Array.isArray(task?.upload_files) ? task.upload_files : []
  return progressFiles.filter(item => Number(item?.progress || 0) >= 100).length
}

function isReimportTask(task) {
  const action = String(task?.task_metadata?.source_action || '').trim()
  return action === 'reimport_local_download_root' || action === 'reimport_downloaded_session'
}

function getTaskResourceCount(task) {
  const explicit = Number(task?.task_metadata?.selected_resource_count || task?.session_state?.selected_resource_count || 0)
  if (explicit > 0) return explicit
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources.length : 0
  if (selectedResources > 0) return selectedResources
  return getDownloadedCount(task)
}

function getTaskTransferBytes(task) {
  const metricBytes = Number(task?.performance_metrics?.downloaded_bytes || task?.task_metadata?.performance_metrics?.downloaded_bytes || 0)
  if (metricBytes > 0) return metricBytes
  const selectedResources = Array.isArray(task?.task_metadata?.selected_resources) ? task.task_metadata.selected_resources : []
  const selectedBytes = selectedResources.reduce((sum, item) => sum + Number(item?.size_bytes || 0), 0)
  if (selectedBytes > 0) return selectedBytes
  const uploadedFiles = Array.isArray(task?.uploaded_files) ? task.uploaded_files : []
  return uploadedFiles.reduce((sum, item) => sum + Number(item?.size_bytes || 0), 0)
}

function getTaskTransferLabel(task) {
  return isReimportTask(task) ? '资源大小' : '下载大小'
}

function getFailureSummary(task) {
  const failedFiles = Array.isArray(task?.failed_files) ? task.failed_files.length : 0
  const verifyFailures = Array.isArray(task?.verification_failures) ? task.verification_failures.length : 0
  if (!failedFiles && !verifyFailures) return '0'
  const parts = []
  if (failedFiles) parts.push(`下载失败 ${failedFiles}`)
  if (verifyFailures) parts.push(`校验失败 ${verifyFailures}`)
  return parts.join(' / ')
}

function getDownloadedCount(task) {
  const persistedCount = Number(task?.task_metadata?.local_downloaded_count || task?.session_state?.local_downloaded_count || 0)
  if (persistedCount > 0) return persistedCount
  const downloadedResources = Array.isArray(task?.task_metadata?.downloaded_resources) ? task.task_metadata.downloaded_resources.length : 0
  if (downloadedResources) return downloadedResources
  const downloadFiles = Array.isArray(task?.download_files) ? task.download_files : []
  return downloadFiles.filter(item => Number(item?.progress || 0) >= 100).length
}

function isTaskDownloaded(task) {
  const persistedReady = Boolean(task?.task_metadata?.local_download_ready || task?.session_state?.local_download_ready)
  const downloadRoot = String(
    task?.task_metadata?.local_download_root
    || task?.session_state?.local_download_root
    || task?.task_metadata?.download_root
    || ''
  ).trim()
  return Boolean((persistedReady || getDownloadedCount(task) > 0) && downloadRoot)
}

function getRetryableFailedFiles(task) {
  const failedFiles = Array.isArray(task?.failed_files) ? task.failed_files : []
  return failedFiles
    .map(item => ({
      name: String(item?.name || '').trim(),
      relative_path: String(item?.relative_path || '').trim(),
      reason: String(item?.reason || '').trim(),
      exception_type: String(item?.exception_type || '').trim(),
      stage: String(item?.stage || '').trim(),
    }))
    .filter(item => item.relative_path || item.name)
}

function loadCachedTargetSubdirs() {
  try {
    const raw = localStorage.getItem(CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY)
    const parsed = JSON.parse(raw || '[]')
    cachedTargetSubdirs.value = Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, 20) : []
  } catch (_) {
    cachedTargetSubdirs.value = []
  }
}

function rememberTargetSubdir(value = '') {
  const normalized = String(value || '').trim().replace(/^[\\/]+|[\\/]+$/g, '')
  if (!normalized) return
  const next = [normalized, ...cachedTargetSubdirs.value.filter(item => item !== normalized)].slice(0, 20)
  cachedTargetSubdirs.value = next
  try {
    localStorage.setItem(CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY, JSON.stringify(next))
  } catch (_) {}
}

let downloadWorkbenchTimer = null

function persistDownloadWorkbenchState() {
  try {
    localStorage.setItem(CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY, JSON.stringify({
      taskIds: trackedDownloadTaskIds.value,
      visible: downloadWorkbenchVisible.value,
      background: downloadWorkbenchBackgroundActive.value
    }))
  } catch (_) {}
}

function hydrateDownloadWorkbenchState() {
  try {
    const raw = JSON.parse(localStorage.getItem(CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY) || '{}')
    trackedDownloadTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    downloadWorkbenchVisible.value = Boolean(raw.visible && trackedDownloadTaskIds.value.length)
    downloadWorkbenchBackgroundActive.value = Boolean(raw.background && trackedDownloadTaskIds.value.length)
  } catch (_) {
    trackedDownloadTaskIds.value = []
    downloadWorkbenchVisible.value = false
    downloadWorkbenchBackgroundActive.value = false
  }
}

function clearDownloadWorkbenchState() {
  trackedDownloadTaskIds.value = []
  trackedDownloadTasks.value = []
  downloadWorkbenchVisible.value = false
  downloadWorkbenchBackgroundActive.value = false
  stopDownloadWorkbenchPolling()
  try {
    localStorage.removeItem(CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY)
  } catch (_) {}
}

function persistRefreshJobState() {
  try {
    if (!refreshJob.job_id) {
      localStorage.removeItem(CIRCLE_COMPLETION_REFRESH_JOB_KEY)
      return
    }
    localStorage.setItem(CIRCLE_COMPLETION_REFRESH_JOB_KEY, JSON.stringify({
      job_id: refreshJob.job_id,
      status: refreshJob.status,
      circle_id: refreshJob.circle_id,
      circle_name: refreshJob.circle_name,
      selected_count: refreshJob.selected_count,
      auto_hide_at: refreshJob.auto_hide_at,
      changed_codes: Array.isArray(refreshJob.changed_codes) ? refreshJob.changed_codes : [],
    }))
  } catch (_) {}
}

function hydrateRefreshJobState() {
  try {
    const raw = JSON.parse(localStorage.getItem(CIRCLE_COMPLETION_REFRESH_JOB_KEY) || '{}')
    refreshJob.visible = Boolean(raw.job_id)
    refreshJob.job_id = String(raw.job_id || '').trim()
    refreshJob.status = String(raw.status || '').trim()
    refreshJob.circle_id = String(raw.circle_id || '').trim()
    refreshJob.circle_name = String(raw.circle_name || '').trim()
    refreshJob.selected_count = Number(raw.selected_count || 0)
    refreshJob.auto_hide_at = String(raw.auto_hide_at || '').trim()
    refreshJob.changed_codes = Array.isArray(raw.changed_codes) ? raw.changed_codes.filter(Boolean) : []
  } catch (_) {
    clearRefreshJobState()
  }
}

function clearRefreshJobState() {
  refreshJob.visible = false
  refreshJob.job_id = ''
  refreshJob.status = ''
  refreshJob.progress = 0
  refreshJob.current_step = ''
  refreshJob.circle_id = ''
  refreshJob.circle_name = ''
  refreshJob.selected_count = 0
  refreshJob.elapsed_seconds = 0
  refreshJob.auto_hide_at = ''
  refreshJob.changed_codes = []
  refreshJob.error_message = ''
  refreshJob.meta = {}
  refreshJob.result = {}
  refreshJob.progress_log = []
  stopRefreshJobPolling()
  stopRefreshJobAutoHide()
  try {
    localStorage.removeItem(CIRCLE_COMPLETION_REFRESH_JOB_KEY)
  } catch (_) {}
}

function stopRefreshJobAutoHide() {
  if (refreshJobAutoHideTimer) {
    window.clearTimeout(refreshJobAutoHideTimer)
    refreshJobAutoHideTimer = null
  }
}

function scheduleRefreshJobAutoHide(delayMs = 10000) {
  stopRefreshJobAutoHide()
  const targetAt = new Date(Date.now() + Math.max(0, Number(delayMs || 0))).toISOString()
  refreshJob.auto_hide_at = targetAt
  persistRefreshJobState()
  refreshJobAutoHideTimer = window.setTimeout(() => {
    clearRefreshJobState()
  }, Math.max(0, Number(delayMs || 0)))
}

function resumeRefreshJobAutoHide() {
  if (!refreshJob.auto_hide_at || refreshJob.status !== 'completed') return
  const remainMs = new Date(refreshJob.auto_hide_at).getTime() - Date.now()
  if (!Number.isFinite(remainMs) || remainMs <= 0) {
    clearRefreshJobState()
    return
  }
  stopRefreshJobAutoHide()
  refreshJobAutoHideTimer = window.setTimeout(() => {
    clearRefreshJobState()
  }, remainMs)
}

function stopDownloadWorkbenchPolling() {
  if (downloadWorkbenchTimer) {
    window.clearTimeout(downloadWorkbenchTimer)
    downloadWorkbenchTimer = null
  }
}

function startDownloadWorkbenchPolling() {
  if (!trackedDownloadTaskIds.value.length) return
  stopDownloadWorkbenchPolling()
  downloadWorkbenchTimer = window.setTimeout(() => {
    refreshDownloadWorkbench()
  }, 2000)
}

async function refreshDownloadWorkbench(options = {}) {
  const silent = Boolean(options?.silent)
  if (!trackedDownloadTaskIds.value.length) {
    trackedDownloadTasks.value = []
    stopDownloadWorkbenchPolling()
    return
  }
  if (!silent) downloadWorkbenchRefreshing.value = true
  try {
    const result = await asmrSyncApi.status()
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    trackedDownloadTasks.value = trackedDownloadTaskIds.value
      .map(id => allTasks.find(task => task.id === id))
      .filter(Boolean)
    trackedDownloadTaskIds.value = trackedDownloadTasks.value.map(task => task.id)
    const stillActive = trackedDownloadTasks.value.some(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task.status || '')))
    if (stillActive || downloadWorkbenchVisible.value || downloadWorkbenchBackgroundActive.value) startDownloadWorkbenchPolling()
    else stopDownloadWorkbenchPolling()
  } catch (error) {
    console.error('刷新社团补全下载工作台失败:', error)
    startDownloadWorkbenchPolling()
  } finally {
    if (!silent) downloadWorkbenchRefreshing.value = false
  }
}

function canRetryDownloadTask(task) {
  const status = String(task?.status || '')
  return ['failed', 'partial_failed', 'waiting_retry'].includes(status)
}

async function retryDownloadTask(task) {
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  const taskId = String(task?.id || '').trim()
  const next = new Set(retryingTaskIds.value)
  next.add(taskId)
  retryingTaskIds.value = next
  try {
    if (sessionId) await asmrSyncApi.retryFailedSession(sessionId)
    else if (taskId) await asmrSyncApi.retry(taskId)
    else throw new Error('缺少任务标识')
    ElMessage.success('已提交重试')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交重试失败')
  } finally {
    const done = new Set(retryingTaskIds.value)
    done.delete(taskId)
    retryingTaskIds.value = done
  }
}

async function retryWaitingDownloadTask(task) {
  const taskId = String(task?.id || '').trim()
  if (!taskId) return
  const next = new Set(retryingTaskIds.value)
  next.add(`${taskId}:waiting`)
  retryingTaskIds.value = next
  try {
    await asmrSyncApi.retryWaiting(taskId)
    ElMessage.success('已立即重试')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '立即重试失败')
  } finally {
    const done = new Set(retryingTaskIds.value)
    done.delete(`${taskId}:waiting`)
    retryingTaskIds.value = done
  }
}

async function retrySingleFailedFile(task, file) {
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  const relativePath = String(file?.relative_path || '').trim()
  const key = `${task?.id}:${relativePath || file?.name || 'file'}`
  const next = new Set(retryingTaskIds.value)
  next.add(key)
  retryingTaskIds.value = next
  try {
    if (!sessionId || !relativePath) throw new Error('缺少会话或文件路径')
    await asmrSyncApi.retrySessionFiles(sessionId, [relativePath])
    ElMessage.success('已提交该文件重试')
    await refreshDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交单文件重试失败')
  } finally {
    const done = new Set(retryingTaskIds.value)
    done.delete(key)
    retryingTaskIds.value = done
  }
}

function openReimportDialog(task) {
  reimportTargetTask.value = task
  reimportTrackingTaskId.value = ''
  reimportBackgroundActive.value = false
  reimportForm.targetLibraryId = downloadSettings.targetLibraryId || ''
  reimportForm.targetSubdir = downloadSettings.targetSubdir || ''
  reimportDialogVisible.value = true
}

async function submitReimportDownloaded() {
  const task = reimportTargetTask.value
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  const downloadRoot = String(task?.task_metadata?.local_download_root || '').trim()
  const rjcode = String(task?.rjcode || task?.task_metadata?.rjcode || '').trim()
  const circleName = String(task?.circle_name || task?.task_metadata?.circle_name || detail.circle_name || '').trim()
  if (!sessionId && !downloadRoot) return ElMessage.error('当前任务缺少可复用来源')
  if (!reimportForm.targetLibraryId) return ElMessage.warning('先选目标库存')
  reimportSubmitting.value = true
  try {
    const targetLibrary = targetLibraries.value.find(item => item.id === reimportForm.targetLibraryId)
    if (targetLibrary?.type === 'synology_filestation') {
      const connection = await libraryApi.testConnection(targetLibrary)
      if (!connection?.ok) {
        throw new Error(connection?.message || '目标远程库存连接失败')
      }
    }
    let nextTaskId = ''
    if (sessionId) {
      const response = await asmrSyncApi.reimportDownloadedSession(sessionId, {
        targetLibraryId: reimportForm.targetLibraryId,
        targetSubdir: reimportForm.targetSubdir,
      })
      nextTaskId = String(response?.session?.task_id || '').trim()
    } else {
      const response = await asmrSyncApi.reimportLocalDownload({
        downloadRoot,
        rjcode,
        circleName,
        targetLibraryId: reimportForm.targetLibraryId,
        targetSubdir: reimportForm.targetSubdir,
      })
      nextTaskId = String(response?.result?.task_id || '').trim()
    }
    if (nextTaskId && !trackedDownloadTaskIds.value.includes(nextTaskId)) {
      trackedDownloadTaskIds.value = [...trackedDownloadTaskIds.value, nextTaskId]
    }
    reimportTrackingTaskId.value = nextTaskId
    reimportBackgroundActive.value = false
    ElMessage.success('已提交直接入库任务')
    await Promise.all([
      refreshDownloadWorkbench({ silent: true }),
      activeCircleId.value ? refreshActiveCircle() : Promise.resolve()
    ])
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '重新入库失败')
  } finally {
    reimportSubmitting.value = false
  }
}

function hideReimportDialogToBackground() {
  if (!reimportTrackedTask.value) return
  reimportDialogVisible.value = false
  reimportBackgroundActive.value = true
}

function resumeReimportDialogFromBackground() {
  if (!reimportTrackedTask.value) return
  reimportDialogVisible.value = true
  reimportBackgroundActive.value = false
}

function closeReimportBackgroundCard() {
  reimportBackgroundActive.value = false
}

function hideDownloadWorkbenchToBackground() {
  downloadWorkbenchVisible.value = false
  downloadWorkbenchBackgroundActive.value = true
}

function resumeDownloadWorkbenchFromBackground() {
  downloadWorkbenchVisible.value = true
  downloadWorkbenchBackgroundActive.value = false
}

function closeDownloadWorkbench() {
  clearDownloadWorkbenchState()
}

function stopRefreshJobPolling() {
  if (refreshJobTimer) {
    window.clearTimeout(refreshJobTimer)
    refreshJobTimer = null
  }
}

function stopIndexJobPolling() {
  if (indexJobTimer) {
    window.clearTimeout(indexJobTimer)
    indexJobTimer = null
  }
}

function applyIndexJob(payload = {}) {
  indexJob.visible = true
  indexJob.job_id = payload.job_id || ''
  indexJob.status = payload.status || ''
  indexJob.progress = Number(payload.progress || 0)
  indexJob.current_step = payload.current_step || ''
  indexJob.circle_query = payload.circle_query || ''
  indexJob.elapsed_seconds = Number(payload.elapsed_seconds || 0)
  indexJob.error_message = payload.error_message || ''
  indexJob.meta = payload.meta || {}
}

function applyRefreshJob(payload = {}) {
  refreshJob.visible = true
  refreshJob.job_id = payload.job_id || refreshJob.job_id || ''
  refreshJob.status = payload.status || ''
  refreshJob.progress = Number(payload.progress || 0)
  refreshJob.current_step = payload.current_step || ''
  refreshJob.circle_id = payload.circle_id || ''
  refreshJob.circle_name = payload.circle_name || ''
  refreshJob.selected_count = Number(payload.selected_count || 0)
  refreshJob.elapsed_seconds = Number(payload.elapsed_seconds || 0)
  refreshJob.auto_hide_at = payload.auto_hide_at || refreshJob.auto_hide_at || ''
  refreshJob.changed_codes = Array.isArray(payload.changed_codes) ? payload.changed_codes.filter(Boolean) : (Array.isArray(refreshJob.changed_codes) ? refreshJob.changed_codes : [])
  refreshJob.error_message = payload.error_message || ''
  refreshJob.meta = payload.meta || {}
  refreshJob.result = payload.result || {}
  refreshJob.progress_log = Array.isArray(payload.progress_log) ? payload.progress_log : []
  if (refreshJob.status !== 'completed') {
    stopRefreshJobAutoHide()
    refreshJob.auto_hide_at = ''
  }
  persistRefreshJobState()
}

async function pollIndexJob(jobId) {
  stopIndexJobPolling()
  try {
    const result = await circleCompletionApi.getIndexJobStatus(jobId)
    applyIndexJob(result)
    if (result.status === 'completed') {
      indexing.value = false
      activeCircleId.value = result.circle_id || result.result?.circle_id || ''
      await Promise.all([loadRecentCircles(), refreshActiveCircle()])
      ElMessage.success('社团索引已刷新')
      return
    }
    if (result.status === 'failed') {
      indexing.value = false
      if (result.error_message === '用户取消' || result.current_step === '已取消') {
        ElMessage.info('社团索引已取消')
      } else {
        ElMessage.error(result.error_message || '社团索引失败')
      }
      return
    }
    indexJobTimer = window.setTimeout(() => {
      pollIndexJob(jobId)
    }, 800)
  } catch (error) {
    indexing.value = false
    ElMessage.error(error.response?.data?.detail || '查询社团索引进度失败')
  }
}

async function pollRefreshJob(jobId, options = {}) {
  stopRefreshJobPolling()
  const silentFinish = Boolean(options?.silentFinish)
  try {
    const result = await circleCompletionApi.getRefreshSelectedJobStatus(jobId)
    applyRefreshJob(result)
    if (result.status === 'completed') {
      refreshingCurrentCircle.value = false
      await Promise.all([refreshActiveCircle(), loadRecentCircles()])
      const changedCodes = (Array.isArray(result.result?.items) ? result.result.items : [])
        .filter(item => item?.changed)
        .map(item => item.canonical_rjcode)
      prioritizeChangedWorks(changedCodes)
      flashChangedWorks(changedCodes)
      refreshJob.current_step = `批量刷新完成，${changedCodes.length} 个状态变更，10 秒后自动隐藏`
      refreshJob.status = 'completed'
      refreshJob.progress = 100
      refreshJob.error_message = ''
      refreshJob.meta = {
        ...(refreshJob.meta || {}),
        changed_count: changedCodes.length,
      }
      refreshJob.changed_codes = changedCodes
      scheduleRefreshJobAutoHide(10000)
      if (!silentFinish) {
        ElMessage.success(`已刷新 ${result.result?.refreshed_count || result.meta?.processed_count || refreshJob.selected_count || 0} 个作品`)
      }
      return
    }
    if (result.status === 'failed') {
      refreshingCurrentCircle.value = false
      if (result.error_message === '用户取消' || result.current_step === '已取消') {
        ElMessage.info('批量刷新已取消')
      } else if (!silentFinish) {
        ElMessage.error(result.error_message || '批量刷新失败')
      }
      clearRefreshJobState()
      return
    }
    refreshJobTimer = window.setTimeout(() => {
      pollRefreshJob(jobId, { silentFinish: true })
    }, 1000)
  } catch (error) {
    refreshingCurrentCircle.value = false
    if (!silentFinish) {
      ElMessage.error(error.response?.data?.detail || '查询批量刷新进度失败')
    }
    refreshJobTimer = window.setTimeout(() => {
      pollRefreshJob(jobId, { silentFinish: true })
    }, 2000)
  }
}

async function cancelIndexJob() {
  if (!indexJob.job_id || cancellingIndexJob.value) return
  cancellingIndexJob.value = true
  try {
    await api.task.cancel(indexJob.job_id)
    stopIndexJobPolling()
    indexJob.status = 'failed'
    indexJob.current_step = '已取消'
    indexJob.error_message = '用户取消'
    indexing.value = false
    ElMessage.success('已发送取消请求')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '取消社团索引失败')
  } finally {
    cancellingIndexJob.value = false
  }
}

async function cancelRefreshJob() {
  if (!refreshJob.job_id || cancellingRefreshJob.value) return
  cancellingRefreshJob.value = true
  try {
    await api.task.cancel(refreshJob.job_id)
    stopRefreshJobPolling()
    refreshJob.status = 'failed'
    refreshJob.current_step = '已取消'
    refreshJob.error_message = '用户取消'
    refreshingCurrentCircle.value = false
    persistRefreshJobState()
    ElMessage.success('已发送取消请求')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '取消批量刷新失败')
  } finally {
    cancellingRefreshJob.value = false
  }
}

async function loadRecentCircles() {
  const result = await circleCompletionApi.listRecentIndexes(24)
  circleList.value = result.circles || []
}

async function loadLibraries() {
  try {
    const result = await libraryApi.listLibraries()
    libraries.value = result.libraries || []
    if (!downloadSettings.targetLibraryId) {
      const preferred = libraries.value.find(item => item?.is_default) || libraries.value[0]
      downloadSettings.targetLibraryId = preferred?.id || ''
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载库存列表失败')
  }
}

async function searchCachedCircles() {
  const result = await circleCompletionApi.searchCircles(circleSearch.value || '', 24)
  circleList.value = result.circles || []
}

async function handleIndexCircle() {
  if (!circleQuery.value.trim()) {
    ElMessage.warning('先输入社团名')
    return
  }
  indexing.value = true
  try {
    const result = await circleCompletionApi.startIndexCircle({
      circle_query: circleQuery.value.trim(),
      force_refresh: true,
      include_dlsite: true,
      include_kikoeru: true
    })
    applyIndexJob(result)
    await pollIndexJob(result.job_id)
  } catch (error) {
    indexing.value = false
    ElMessage.error(error.response?.data?.detail || '启动社团索引失败')
  }
}

async function refreshSelectedCircleIndex() {
  const circleId = String(activeCircleId.value || detail.circle_id || '').trim()
  if (!circleId) {
    ElMessage.warning('当前还没有选中社团')
    return
  }
  const codes = selectedCanonicalRJCodes.value
  if (!codes.length) {
    ElMessage.warning('先选中要刷新的作品')
    return
  }
  if (isRefreshJobActive.value) {
    ElMessage.warning('已有批量刷新任务在跑')
    return
  }
  refreshingCurrentCircle.value = true
  try {
    const result = await circleCompletionApi.startRefreshSelectedWorks({
      circle_id: circleId,
      circle_name: detail.circle_name || '',
      canonical_rjcodes: codes
    })
    applyRefreshJob(result)
    await pollRefreshJob(result.job_id)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '批量刷新选中作品失败')
  } finally {
    if (!isRefreshJobActive.value) {
      refreshingCurrentCircle.value = false
    }
  }
}

async function selectCircle(circleId) {
  activeCircleId.value = circleId
  selectedCanonicals.value = new Set()
  await refreshActiveCircle()
}

async function refreshActiveCircle() {
  if (!activeCircleId.value) return
  try {
    const result = await circleCompletionApi.getCircleDetail(activeCircleId.value, {
      onlyMissing: filters.onlyMissing,
      onlyDownloadable: filters.onlyDownloadable,
      includeDlOnly: filters.includeDlOnly
    })
    Object.assign(detail, {
      circle_id: result.circle_id || '',
      circle_name: result.circle_name || '',
      source_mask: result.source_mask || '',
      last_indexed_at: result.last_indexed_at || '',
      owned_count: result.owned_count || 0,
      missing_count: result.missing_count || 0,
      downloadable_count: result.downloadable_count || 0,
      dl_only_count: result.dl_only_count || 0,
      works: result.works || []
    })
    selectedCanonicals.value = new Set(
      [...selectedCanonicals.value].filter(code => (result.works || []).some(item => item.canonical_rjcode === code))
    )
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载社团详情失败')
  }
}

function toggleSelection(item) {
  if (!item?.canonical_rjcode) return
  const next = new Set(selectedCanonicals.value)
  if (next.has(item.canonical_rjcode)) next.delete(item.canonical_rjcode)
  else next.add(item.canonical_rjcode)
  selectedCanonicals.value = next
}

function selectAllVisibleWorks() {
  selectedCanonicals.value = new Set(
    missingWorks.value.map(item => item.canonical_rjcode).filter(Boolean)
  )
}

function clearSelection() {
  selectedCanonicals.value = new Set()
}

function openReimportDialogForWork(item) {
  const sessionId = String(item?.local_download_session_id || '').trim()
  const downloadRoot = String(item?.local_download_root || '').trim()
  if (!sessionId && !downloadRoot) {
    ElMessage.error('当前作品缺少可复用的下载目录')
    return
  }
  reimportTargetTask.value = {
    id: `work:${item?.canonical_rjcode || sessionId}`,
    session_id: sessionId,
    rjcode: String(item?.canonical_rjcode || item?.display_rjcode || '').trim(),
    circle_name: String(item?.circle_name || detail.circle_name || '').trim(),
    task_metadata: {
      session_id: sessionId,
      local_download_root: downloadRoot,
      local_download_ready: Boolean(item?.local_download_ready),
      local_downloaded_count: Number(item?.local_downloaded_count || 0),
    },
  }
  reimportTrackingTaskId.value = ''
  reimportForm.targetLibraryId = downloadSettings.targetLibraryId || ''
  reimportForm.targetSubdir = downloadSettings.targetSubdir || ''
  reimportDialogVisible.value = true
}

async function openBatchPreview(singleCanonical = '') {
  const codes = singleCanonical ? [singleCanonical] : selectedDownloadableRJCodes.value
  if (!codes.length) {
    ElMessage.warning(singleCanonical ? '当前作品没有可下载资源' : '选中的作品里没有可下载项')
    return
  }
  previewing.value = true
  previewDialogVisible.value = true
  previewLoading.value = true
  try {
    const result = await circleCompletionApi.previewBatchDownload({
      circle_id: detail.circle_id,
      canonical_rjcodes: codes
    })
    previewPlans.value = (result.plans || []).map(buildPlanState)
    downloadSettings.downloadBasePath = result.download_base_path || downloadSettings.downloadBasePath || ''
    if (!downloadSettings.targetLibraryId) {
      downloadSettings.targetLibraryId = result.default_target_library_id || downloadSettings.targetLibraryId
    }
    if (!downloadSettings.targetSubdir) {
      downloadSettings.targetSubdir = result.default_target_subdir || ''
    }
  } catch (error) {
    previewDialogVisible.value = false
    ElMessage.error(error.response?.data?.detail || '生成下载预览失败')
  } finally {
    previewing.value = false
    previewLoading.value = false
  }
}

function buildPlanState(plan) {
  const resources = (plan.selectable_resources || []).map(item => ({
    ...item,
    selected: Boolean(item.selected),
    recommended: Boolean(item.selected),
    recommended_skip_reasons: item.recommended_skip_reasons || []
  }))
  const tree = buildTree(resources)
  const expandedIds = new Set(tree.map(node => node.id))
  const state = {
    ...plan,
    selectable_resources: resources,
    tree,
    expandedIds,
    flatRows: []
  }
  refreshPlanTree(state)
  return state
}

function buildTree(resources) {
  const roots = []
  const dirMap = new Map()
  for (const resource of resources) {
    const path = String(resource.relative_path || resource.file_name || '')
    const parts = path.split('/').filter(Boolean)
    let children = roots
    let parentPath = ''
    for (let i = 0; i < parts.length; i += 1) {
      const name = parts[i]
      const currentPath = parentPath ? `${parentPath}/${name}` : name
      const isFile = i === parts.length - 1
      if (isFile) {
        children.push({
          id: currentPath,
          name,
          path: currentPath,
          type: 'file',
          resource,
          size_bytes: Number(resource.size_bytes || 0),
          children: []
        })
      } else {
        if (!dirMap.has(currentPath)) {
          const node = {
            id: currentPath,
            name,
            path: currentPath,
            type: 'dir',
            size_bytes: 0,
            children: []
          }
          dirMap.set(currentPath, node)
          children.push(node)
        }
        children = dirMap.get(currentPath).children
      }
      parentPath = currentPath
    }
  }
  return roots
}

function flattenTree(nodes, expandedIds, depth = 0, out = []) {
  for (const node of nodes || []) {
    out.push({ ...node, depth })
    if (node.type === 'dir' && expandedIds.has(node.id)) flattenTree(node.children, expandedIds, depth + 1, out)
  }
  return out
}

function collectLeafResources(node) {
  if (!node) return []
  if (node.type === 'file') return [node.resource]
  return (node.children || []).flatMap(child => collectLeafResources(child))
}

function annotateSelection(node) {
  if (node.type === 'file') {
    return {
      ...node,
      checked: Boolean(node.resource.selected),
      indeterminate: false,
      recommended_skip_reasons: node.resource.recommended_skip_reasons || []
    }
  }
  const children = (node.children || []).map(annotateSelection)
  const leafResources = children.flatMap(child => child.type === 'file' ? [child.resource] : collectLeafResources(child))
  const checkedCount = leafResources.filter(item => item.selected).length
  return {
    ...node,
    children,
    size_bytes: children.reduce((sum, child) => sum + Number(child.size_bytes || 0), 0),
    checked: checkedCount > 0 && checkedCount === leafResources.length,
    indeterminate: checkedCount > 0 && checkedCount < leafResources.length
  }
}

function refreshPlanTree(plan) {
  plan.tree = (plan.tree || []).map(annotateSelection)
  plan.flatRows = flattenTree(plan.tree, plan.expandedIds, 0, [])
  plan.selected_resource_count = plan.selectable_resources.filter(item => item.selected).length
  plan.selected_size_bytes = plan.selectable_resources.filter(item => item.selected).reduce((sum, item) => sum + Number(item.size_bytes || 0), 0)
}

function toggleExpand(plan, row) {
  const next = new Set(plan.expandedIds)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  plan.expandedIds = next
  refreshPlanTree(plan)
}

function updateResourceSelection(plan, row, nextSelected) {
  const targetIds = new Set(collectLeafResources(row).map(item => item.relative_path))
  plan.selectable_resources.forEach(item => {
    if (targetIds.has(item.relative_path)) item.selected = nextSelected
  })
  refreshPlanTree(plan)
}

function toggleTreeRow(plan, row) {
  const nextSelected = row.indeterminate ? true : !row.checked
  updateResourceSelection(plan, row, nextSelected)
}

function handleTreeRowClick(plan, row) {
  if (!row) return
  if (row.type === 'dir') {
    toggleExpand(plan, row)
    return
  }
  toggleTreeRow(plan, row)
}

function isPlanAllSelected(plan) {
  return plan.selectable_resources.length > 0 && plan.selectable_resources.every(item => item.selected)
}

function isPlanPartiallySelected(plan) {
  const checkedCount = plan.selectable_resources.filter(item => item.selected).length
  return checkedCount > 0 && checkedCount < plan.selectable_resources.length
}

function togglePlanAll(plan) {
  const next = !isPlanAllSelected(plan)
  plan.selectable_resources.forEach(item => {
    item.selected = next
  })
  refreshPlanTree(plan)
}

function matchPreset(item, preset) {
  const ext = String(item.file_ext || '').toLowerCase()
  if (preset === 'subtitle') return item.resource_type === 'subtitle'
  if (preset === 'audio') return item.resource_type === 'audio'
  if (preset === 'image') return item.resource_type === 'cover'
  return ext === `.${preset}`
}

function applyPreset(preset) {
  previewPlans.value.forEach(plan => {
    plan.selectable_resources.forEach(item => {
      item.selected = matchPreset(item, preset)
    })
    refreshPlanTree(plan)
  })
}

function resetRecommended() {
  previewPlans.value.forEach(plan => {
    plan.selectable_resources.forEach(item => {
      item.selected = Boolean(item.recommended)
    })
    refreshPlanTree(plan)
  })
}

async function startBatchDownload() {
  const items = previewPlans.value
    .map(plan => ({
      session_id: plan.session_id,
      rjcode: plan.rjcode,
      canonical_rjcode: plan.canonical_rjcode,
      display_rjcodes: plan.display_rjcodes || [],
      work_title: plan.title,
      folder_path: plan.folder_path || '',
      selected_resources: plan.selectable_resources.filter(item => item.selected),
      upload_options: {
        enabled: false,
        mode: 'disabled',
        target_path: '',
        library_id: ''
      },
      postprocess_options: {
        enabled: true,
        target_library_id: downloadSettings.targetLibraryId || '',
        target_subdir: downloadSettings.targetSubdir || '',
        naming_mode: downloadSettings.namingMode,
        classify_mode: downloadSettings.classifyMode,
        circle_name: detail.circle_name || ''
      },
      resource_filter_snapshot: {},
      verify_md5_after_download: true
    }))
    .filter(item => item.selected_resources.length > 0)

  if (!items.length) {
    ElMessage.warning('没有选中任何文件')
    return
  }

  starting.value = true
  try {
    const result = await circleCompletionApi.startBatchDownload({
      circle_id: detail.circle_id,
      circle_name: detail.circle_name,
      batch_options: {
        download_base_path: downloadSettings.downloadBasePath || '',
        target_library_id: downloadSettings.targetLibraryId || '',
        target_subdir: downloadSettings.targetSubdir || '',
        naming_mode: downloadSettings.namingMode,
        classify_mode: downloadSettings.classifyMode
      },
      items
    })
    rememberTargetSubdir(downloadSettings.targetSubdir || '')
    trackedDownloadTaskIds.value = (result.tasks || []).map(item => item.task_id).filter(Boolean)
    downloadWorkbenchVisible.value = trackedDownloadTaskIds.value.length > 0
    downloadWorkbenchBackgroundActive.value = false
    persistDownloadWorkbenchState()
    await refreshDownloadWorkbench()
    ElMessage.success(result.message || '下载任务已创建')
    previewDialogVisible.value = false
    await refreshActiveCircle()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '创建下载任务失败')
  } finally {
    starting.value = false
  }
}
</script>

<style scoped>
.circle-page {
  display: grid;
  gap: 16px;
  padding: 6px;
}
.download-settings-card {
  display: grid;
  gap: 14px;
  margin-bottom: 16px;
  padding: 16px 18px;
  border: 1px solid #dfe8f6;
  border-radius: 18px;
  background: linear-gradient(180deg, #fbfdff 0%, #f5f8fc 100%);
}
.download-settings-head {
  display: grid;
  gap: 4px;
}
.download-settings-title {
  font-size: 15px;
  font-weight: 800;
  color: #1f3759;
}
.download-settings-subtitle {
  font-size: 12px;
  color: #6b7f98;
}
.download-settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
}
.setting-field {
  display: grid;
  gap: 6px;
}
.setting-field-wide {
  grid-column: 1 / -1;
}
.setting-label {
  font-size: 12px;
  font-weight: 700;
  color: #55708f;
}
.setting-static {
  align-content: start;
}
.setting-static-value {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  min-height: 40px;
}
.setting-pill,
.setting-hint {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}
.setting-pill {
  color: #35577f;
  background: #edf4ff;
  border: 1px solid #d7e4fb;
}
.setting-pill.ok {
  color: #11754f;
  background: #eefaf3;
  border-color: #ccefd8;
}
.setting-pill.warning {
  color: #9a5a07;
  background: #fff6e8;
  border-color: #f4dfb0;
}
.setting-pill.danger {
  color: #b44535;
  background: #fff1ef;
  border-color: #f4cbc4;
}
.setting-hint {
  color: #4f6684;
  background: #f4f6fa;
  border: 1px solid #e3e8f0;
}
.workbench-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-bottom: 18px;
}
.workbench-summary {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.workbench-stat {
  display: grid;
  gap: 4px;
  min-width: 92px;
  padding: 10px 12px;
  border-radius: 14px;
  background: linear-gradient(180deg, #fbfdff 0%, #f3f8ff 100%);
  border: 1px solid #dce9fb;
  box-shadow: 0 8px 18px rgba(62, 102, 168, 0.08);
}
.workbench-stat.danger {
  background: linear-gradient(180deg, #fff8f7 0%, #fff1ef 100%);
  border-color: #ffd8d4;
}
.workbench-stat-label {
  font-size: 11px;
  font-weight: 700;
  color: #71839c;
}
.workbench-stat-value {
  font-size: 22px;
  line-height: 1;
  color: #1f3759;
}
.workbench-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.workbench-action-btn {
  min-height: 34px;
  padding: 0 14px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.01em;
  border: 1px solid transparent;
  position: relative;
  overflow: hidden;
  transition: transform .16s ease, box-shadow .2s ease, background .2s ease, border-color .2s ease, color .2s ease;
}
.workbench-action-btn::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, rgba(255,255,255,0) 18%, rgba(255,255,255,0.28) 50%, rgba(255,255,255,0) 82%);
  opacity: 0;
  transform: translateX(-24%);
  transition: opacity .18s ease, transform .28s ease;
  pointer-events: none;
}
.workbench-action-btn:hover {
  transform: translateY(-1px);
}
.workbench-action-btn:hover::after {
  opacity: 1;
  transform: translateX(14%);
}
.workbench-action-btn:active {
  transform: translateY(0) scale(0.985);
}
.workbench-action-btn.is-refresh {
  background: linear-gradient(180deg, #f5f9ff 0%, #e7f0ff 100%);
  border-color: #c4d8fb;
  color: #1d5fbc;
  box-shadow: 0 8px 16px rgba(39, 101, 190, 0.10);
}
.workbench-action-btn.is-refresh:hover {
  background: linear-gradient(180deg, #e8f3ff 0%, #d6e8ff 100%);
  border-color: #9fc4ff;
  color: #0f56b8;
  box-shadow: 0 12px 22px rgba(28, 95, 188, 0.16);
}
.workbench-action-btn.is-background {
  background: linear-gradient(180deg, #ffffff 0%, #f3f6fb 100%);
  border-color: #d5dfeb;
  color: #5a6f89;
  box-shadow: 0 6px 14px rgba(83, 101, 132, 0.08);
}
.workbench-action-btn.is-background:hover {
  background: linear-gradient(180deg, #f8fbff 0%, #e9eff7 100%);
  border-color: #b9cde3;
  color: #425977;
  box-shadow: 0 10px 18px rgba(83, 101, 132, 0.12);
}
.workbench-action-btn.is-close {
  background: linear-gradient(180deg, #fff9f8 0%, #ffefec 100%);
  border-color: #efc8c2;
  color: #b84d40;
  box-shadow: 0 6px 14px rgba(184, 77, 64, 0.08);
}
.workbench-action-btn.is-close:hover {
  background: linear-gradient(180deg, #fff1ee 0%, #ffe2dd 100%);
  border-color: #e2aea6;
  color: #a33a2e;
  box-shadow: 0 10px 18px rgba(184, 77, 64, 0.14);
}
.download-task-list {
  display: grid;
  gap: 14px;
  max-height: 68vh;
  overflow: auto;
  padding-right: 4px;
}
.download-task-card {
  display: grid;
  gap: 12px;
  padding: 18px;
  border-radius: 20px;
  border: 1px solid #dfebfb;
  background:
    radial-gradient(circle at top right, rgba(92, 154, 255, 0.12), transparent 24%),
    linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  box-shadow: 0 14px 28px rgba(45, 86, 145, 0.08);
}
.download-task-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.download-task-heading {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.download-task-rj {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
  color: #3070d8;
}
.download-task-rj-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.download-state-chip {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .02em;
}
.download-state-chip.is-downloaded {
  background: linear-gradient(180deg, #effcf3 0%, #e4f7eb 100%);
  border: 1px solid #bfe7cb;
  color: #22824d;
}
.download-task-title {
  font-size: 19px;
  line-height: 1.4;
  font-weight: 800;
  color: #1d3557;
  word-break: break-word;
}
.download-task-step {
  font-size: 13px;
  font-weight: 700;
  color: #51657f;
}
.download-task-error {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 14px;
  background: linear-gradient(180deg, #fff7f5 0%, #fff1ee 100%);
  border: 1px solid #ffd8d1;
}
.download-task-error-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .04em;
  color: #b94a3a;
}
.download-task-error-text {
  font-size: 13px;
  line-height: 1.6;
  color: #8f3427;
  word-break: break-word;
}
.download-task-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: -2px;
}
.download-failed-list {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid #f2d7d2;
  background: linear-gradient(180deg, #fffaf9 0%, #fff4f2 100%);
}
.download-failed-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(232, 191, 182, 0.58);
}
.download-failed-main {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.download-failed-reason {
  font-size: 12px;
  color: #9b4a40;
  line-height: 1.5;
  word-break: break-word;
}
.download-task-action-btn {
  min-height: 32px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid #d4dfec;
  background: linear-gradient(180deg, #ffffff 0%, #f4f7fb 100%);
  color: #566b86;
  font-size: 12px;
  font-weight: 800;
  transition: transform .16s ease, box-shadow .2s ease, border-color .2s ease, background .2s ease, color .2s ease;
}
.download-task-action-btn:hover {
  transform: translateY(-1px);
  background: linear-gradient(180deg, #fbfdff 0%, #ebf1f8 100%);
  border-color: #c0d2e6;
  color: #425b79;
  box-shadow: 0 10px 18px rgba(77, 100, 132, 0.10);
}
.download-task-action-btn.is-primary {
  border-color: #c6d9fb;
  background: linear-gradient(180deg, #f4f9ff 0%, #e7f0ff 100%);
  color: #1b60c3;
}
.download-task-action-btn.is-primary:hover {
  background: linear-gradient(180deg, #e9f3ff 0%, #d9e9ff 100%);
  border-color: #aac8fa;
  color: #0f56b8;
  box-shadow: 0 12px 20px rgba(27, 96, 195, 0.14);
}
.download-task-action-btn.is-upload {
  border-color: #bfe2cb;
  background: linear-gradient(180deg, #f1fbf4 0%, #e6f7eb 100%);
  color: #21814c;
}
.download-task-action-btn.is-upload:hover {
  background: linear-gradient(180deg, #e8f7ed 0%, #d9f1e1 100%);
  border-color: #9fd3b1;
  color: #186e3f;
  box-shadow: 0 12px 20px rgba(33, 129, 76, 0.14);
}
.download-task-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.download-task-meta-item {
  display: grid;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(244, 248, 254, 0.9);
  border: 1px solid #e1eaf7;
}
.download-task-meta-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .04em;
  color: #7486a0;
}
.download-task-meta-value {
  font-size: 13px;
  line-height: 1.5;
  color: #294563;
  word-break: break-all;
}
.download-file-list {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 16px;
  background: #f6f9fd;
  border: 1px solid #e3ebf6;
}
.download-file-list.upload-stage {
  background: #f4fcf7;
  border-color: #d9efe1;
}
.download-file-title {
  font-size: 12px;
  font-weight: 800;
  color: #526983;
}
.download-result-list,
.download-log-list {
  display: grid;
  gap: 8px;
  padding: 14px;
  border-radius: 16px;
  background: #fbfcfe;
  border: 1px solid #e6edf7;
}
.download-result-item {
  display: grid;
  gap: 4px;
}
.download-result-name {
  font-size: 13px;
  font-weight: 700;
  color: #294563;
}
.download-result-path {
  font-size: 12px;
  color: #69809a;
  word-break: break-all;
}
.download-log-item {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
  font-size: 12px;
  line-height: 1.6;
}
.download-log-time {
  color: #7a8ca4;
  font-weight: 700;
}
.download-log-message {
  color: #4f6684;
  word-break: break-word;
}
.download-log-item.error .download-log-message {
  color: #b44535;
}
.download-log-item.success .download-log-message {
  color: #17704a;
}
.download-file-item {
  display: grid;
  gap: 8px;
}
.download-file-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.download-file-name {
  min-width: 0;
  font-size: 13px;
  color: #294563;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.download-file-size {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 700;
  color: #6a7e97;
}
.circle-download-floating-card {
  position: fixed;
  right: 18px;
  bottom: 18px;
  width: min(420px, calc(100vw - 32px));
  z-index: 90;
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid #d7e6fb;
  background:
    radial-gradient(circle at top right, rgba(87, 149, 255, 0.16), transparent 28%),
    linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(246,250,255,0.98) 100%);
  box-shadow: 0 18px 40px rgba(32, 62, 105, 0.18);
  backdrop-filter: blur(12px);
}
.circle-download-floating-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.circle-download-floating-title {
  font-size: 14px;
  font-weight: 800;
  color: #203d61;
}
.circle-download-floating-mode {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.5;
  color: #6a7f98;
  word-break: break-all;
}
.circle-download-floating-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  height: 36px;
  padding: 0 10px;
  border-radius: 999px;
  background: #edf4ff;
  color: #2458a6;
  border: 1px solid #d3e2ff;
  font-size: 13px;
  font-weight: 800;
}
.circle-download-floating-chip-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.circle-download-floating-chip {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  border-radius: 999px;
  background: #f3f7fd;
  border: 1px solid #dde7f4;
  font-size: 12px;
  font-weight: 700;
  color: #536a84;
}
.circle-download-floating-chip.danger {
  background: #fff3f1;
  border-color: #ffd7d2;
  color: #bf4636;
}
.circle-download-floating-text {
  font-size: 12px;
  line-height: 1.6;
  color: #51657f;
  word-break: break-all;
}
.circle-download-floating-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
:deep(.circle-download-workbench .el-dialog) {
  border-radius: 24px;
  overflow: hidden;
}
:deep(.circle-download-workbench .el-dialog__header) {
  margin-right: 0;
  padding: 22px 24px 14px;
  border-bottom: 1px solid #e6eef8;
  background: linear-gradient(180deg, #fbfdff 0%, #f5f9ff 100%);
}
:deep(.circle-download-workbench .el-dialog__title) {
  font-size: 20px;
  font-weight: 800;
  color: #1d3557;
}
:deep(.circle-download-workbench .el-dialog__body) {
  padding: 20px 24px 24px;
  background: #f8fbff;
}
:deep(.circle-reimport-dialog .el-dialog) {
  border-radius: 22px;
  overflow: hidden;
  max-width: calc(100vw - 32px);
}
:deep(.circle-reimport-dialog .el-dialog__header) {
  margin-right: 0;
  padding: 20px 22px 12px;
  border-bottom: 1px solid #e7eef8;
  background: linear-gradient(180deg, #fcfdff 0%, #f6f9ff 100%);
}
:deep(.circle-reimport-dialog .el-dialog__title) {
  font-size: 18px;
  font-weight: 800;
  color: #193455;
}
:deep(.circle-reimport-dialog .el-dialog__body) {
  padding: 18px 22px 10px;
  background: #f8fbff;
}
:deep(.circle-reimport-dialog .el-dialog__footer) {
  padding: 0 22px 20px;
  background: #f8fbff;
}
.reimport-dialog-body {
  display: grid;
  gap: 16px;
}
.circle-reimport-dialog .setting-field {
  margin-top: 2px;
}
.reimport-progress-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid #d7e6fb;
  background:
    radial-gradient(circle at top right, rgba(87, 149, 255, 0.12), transparent 34%),
    linear-gradient(180deg, #fcfdff 0%, #f3f8ff 100%);
  box-shadow: 0 12px 24px rgba(39, 72, 118, 0.08);
}
.reimport-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.reimport-progress-metrics {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.reimport-progress-metric {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid #d9e5f5;
  font-size: 12px;
  font-weight: 700;
  color: #4d6888;
}
.reimport-progress-title {
  font-size: 14px;
  font-weight: 800;
  color: #24415f;
}
.reimport-progress-status {
  font-size: 12px;
  font-weight: 700;
  color: #3f628a;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #d8e5f7;
}
.reimport-progress-step {
  font-size: 12px;
  line-height: 1.6;
  color: #5d7390;
  word-break: break-word;
}
.reimport-file-progress-list,
.reimport-file-result-list {
  display: grid;
  gap: 10px;
  padding-top: 4px;
}
.reimport-file-progress-title {
  font-size: 12px;
  font-weight: 800;
  color: #35506f;
}
.reimport-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.reimport-summary-item {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.84);
  border: 1px solid rgba(214, 229, 246, 0.96);
}
.reimport-summary-label {
  font-size: 11px;
  font-weight: 700;
  color: #7287a1;
}
.reimport-summary-value {
  font-size: 13px;
  font-weight: 800;
  color: #284767;
  word-break: break-word;
}
.reimport-file-progress-item {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid #dce8f7;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}
.reimport-file-progress-row,
.reimport-file-result-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.reimport-file-progress-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11px;
  color: #6a8099;
}
.reimport-file-progress-name,
.reimport-file-result-name {
  min-width: 0;
  flex: 1;
  font-size: 12px;
  font-weight: 700;
  color: #32516f;
  overflow-wrap: anywhere;
}
.reimport-file-progress-size,
.reimport-file-result-path {
  min-width: 0;
  font-size: 11px;
  color: #6b809a;
  text-align: right;
  overflow-wrap: anywhere;
}
.reimport-file-result-item {
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(243, 251, 246, 0.92);
  border: 1px solid #d6ecd8;
}
.reimport-file-result-copy {
  min-width: 0;
  display: grid;
  gap: 4px;
}
.reimport-file-result-path {
  text-align: left;
}
.circle-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 420px);
  gap: 20px;
  padding: 30px 34px;
  border-radius: 28px;
  background: linear-gradient(180deg, #fbfcfe 0%, #f5f6f8 100%);
  border: 1px solid rgba(29, 29, 31, 0.08);
  box-shadow: 0 12px 28px rgba(29, 29, 31, 0.05);
}
.hero-eyebrow {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: #0071e3;
}
.circle-hero h1 {
  margin: 6px 0 8px;
  font-size: 34px;
  line-height: 1.08;
  letter-spacing: -0.03em;
  color: #1d1d1f;
}
.circle-hero p {
  margin: 0;
  max-width: 720px;
  color: rgba(29, 29, 31, 0.7);
  line-height: 1.62;
}
.hero-actions {
  display: grid;
  gap: 12px;
  align-content: center;
  padding: 16px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(29, 29, 31, 0.06);
}
.hero-search-input :deep(.el-input__wrapper) {
  min-height: 46px;
  border-radius: 14px;
  box-shadow: 0 0 0 1px rgba(29, 29, 31, 0.08) inset;
  background: rgba(255, 255, 255, 0.96);
}
.hero-search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(0, 113, 227, 0.18) inset;
}
.hero-search-button,
.batch-action-button,
.work-action-button {
  border-radius: 12px;
  font-weight: 800;
  position: relative;
  overflow: hidden;
  transition: transform .18s ease, box-shadow .22s ease, border-color .18s ease, background .22s ease, color .22s ease, filter .18s ease;
}
.hero-search-button {
  min-height: 46px;
  border: 1px solid #0071e3;
  background: linear-gradient(135deg, #0a84ff 0%, #0071e3 100%);
  box-shadow: 0 10px 22px rgba(0, 113, 227, 0.24);
}
.hero-search-button::after,
.batch-action-button::after,
.work-action-button::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(120deg, rgba(255,255,255,0) 20%, rgba(255,255,255,0.22) 50%, rgba(255,255,255,0) 80%);
  opacity: 0;
  transform: translateX(-18%);
  transition: opacity .2s ease, transform .28s ease;
  pointer-events: none;
}
.hero-search-button:hover,
.batch-action-button:hover,
.work-action-button:hover {
  transform: translateY(-2px);
  filter: saturate(1.05);
}
.hero-search-button:hover::after,
.batch-action-button:hover::after,
.work-action-button:hover::after {
  opacity: 1;
  transform: translateX(12%);
}
.hero-search-button:active,
.batch-action-button:active,
.work-action-button:active {
  transform: translateY(0) scale(0.985);
  box-shadow: 0 6px 14px rgba(0, 113, 227, 0.14);
}
.sidebar-refresh-button {
  font-weight: 800;
  color: #4f73ab;
}
.index-progress-card {
  display: grid;
  gap: 12px;
  padding: 16px 18px;
  border-radius: 20px;
  border: 1px solid #d8e6fb;
  background: linear-gradient(135deg, rgba(244, 249, 255, 0.96) 0%, rgba(255, 254, 250, 0.96) 100%);
  box-shadow: 0 14px 28px rgba(55, 93, 152, 0.08);
}
.index-progress-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.index-progress-head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.refresh-progress-card {
  margin: 0 20px 18px;
}
.index-cancel-button {
  border-radius: 999px;
}
.index-progress-title {
  font-size: 16px;
  font-weight: 800;
  color: #1f3759;
}
.index-progress-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #637892;
}
.index-progress-status,
.progress-meta-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}
.index-progress-status {
  background: #edf4ff;
  color: #265aa7;
  border: 1px solid #d4e5ff;
}
.index-progress-status.completed {
  background: #ecfaf1;
  color: #19744b;
  border-color: #cdeedb;
}
.index-progress-status.failed {
  background: #fff1f0;
  color: #c0392b;
  border-color: #ffd4d1;
}
.index-progress-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.progress-meta-pill {
  background: rgba(255, 255, 255, 0.82);
  color: #556b86;
  border: 1px solid #e0e8f4;
}
.progress-meta-pill.ok {
  background: #ecfaf1;
  color: #19744b;
  border-color: #cdeedb;
}
.index-progress-error {
  font-size: 13px;
  color: #bb3f33;
  line-height: 1.6;
}
.refresh-progress-log-list {
  display: grid;
  gap: 8px;
}
.refresh-progress-log-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 9px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid #dfe8f4;
  color: #506784;
  font-size: 12px;
}
.refresh-progress-log-item.success {
  background: rgba(236, 250, 241, 0.9);
  border-color: #cdeedb;
  color: #1f7a52;
}
.refresh-progress-log-item.warning {
  background: rgba(255, 248, 233, 0.9);
  border-color: #f3dfb0;
  color: #8c641a;
}
.refresh-progress-log-item.error {
  background: rgba(255, 241, 240, 0.9);
  border-color: #ffd4d1;
  color: #b74237;
}
.refresh-progress-log-time {
  flex: 0 0 auto;
  color: #8092a9;
  font-variant-numeric: tabular-nums;
}
.refresh-progress-log-message {
  min-width: 0;
  overflow-wrap: anywhere;
}
.circle-shell {
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr);
  gap: 16px;
  min-height: 0;
}
.sidebar-card,
.toolbar-card,
.works-card {
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e3edf9;
  box-shadow: 0 14px 30px rgba(46, 74, 120, 0.07);
}
.sidebar-card {
  padding: 22px 20px;
  display: grid;
  gap: 14px;
}
.sidebar-head,
.toolbar-main,
.batch-bar,
.preview-toolbar,
.preview-plan-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.sidebar-title,
.toolbar-title {
  font-size: 18px;
  font-weight: 800;
  color: #1d1d1f;
}
.toolbar-card {
  padding: 20px 20px 16px;
  display: grid;
  gap: 14px;
}
.toolbar-subtitle {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.58);
  margin-top: 4px;
}
.toolbar-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.metric-pill,
.tag-chip,
.reason-pill {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 7px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
}
.metric-pill {
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  background: linear-gradient(180deg, #ffffff 0%, #f6faff 100%);
  color: #48617d;
  border: 1px solid rgba(72, 97, 125, 0.16);
}
.metric-pill.owned {
  background: linear-gradient(180deg, #f7fbff 0%, #eef5ff 100%);
  color: #245ea6;
  border-color: rgba(0, 113, 227, 0.2);
}
.metric-pill.warn {
  background: linear-gradient(180deg, #fff9f0 0%, #fff2df 100%);
  color: #9a5809;
  border-color: rgba(214, 145, 31, 0.26);
}
.metric-pill.ok,
.tag-chip.ok,
.reason-pill.ok {
  background: linear-gradient(180deg, #f3fcf6 0%, #e8f7ee 100%);
  color: #1c7a4d;
  border: 1px solid rgba(68, 162, 104, 0.24);
}
.metric-pill.muted {
  background: linear-gradient(180deg, #fbfcfe 0%, #f3f6fa 100%);
  color: #5f6f83;
  border-color: rgba(95, 111, 131, 0.16);
}
.toolbar-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding-top: 2px;
}
.toolbar-filters :deep(.el-checkbox__label) {
  font-weight: 700;
  color: #546b87;
}
.circle-list {
  display: grid;
  gap: 8px;
  padding: 4px 2px 2px;
  max-height: calc(100vh - 320px);
  overflow: auto;
}
.circle-list-item {
  width: 100%;
  padding: 14px 12px;
  border: 1px solid rgba(29, 29, 31, 0.07);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.84);
  text-align: left;
  cursor: pointer;
  transition: border-color .18s ease, box-shadow .18s ease, background .18s ease, transform .18s ease;
}
.circle-list-item:hover {
  border-color: rgba(0, 113, 227, 0.16);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 8px 18px rgba(29, 29, 31, 0.05);
  transform: translateY(-1px);
}
.circle-list-item.active {
  border-color: rgba(0, 113, 227, 0.18);
  background: linear-gradient(180deg, #f8fbff 0%, #eff5fc 100%);
  box-shadow: 0 0 0 1px rgba(0, 113, 227, 0.12), 0 8px 18px rgba(29, 29, 31, 0.04);
  transform: none;
}
.circle-list-name {
  font-size: 15px;
  font-weight: 700;
  color: #1d1d1f;
}
.circle-list-meta {
  margin-top: 4px;
  display: grid;
  gap: 2px;
  font-size: 11px;
  color: rgba(29, 29, 31, 0.5);
}
.works-card {
  padding: 18px;
  display: grid;
  gap: 14px;
}
.batch-bar {
  padding: 14px 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, #f7f9fb 0%, #ffffff 100%);
  border: 1px solid rgba(29, 29, 31, 0.06);
}
.batch-count {
  font-size: 15px;
  font-weight: 800;
  color: #1d1d1f;
}
.batch-hint {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.56);
}
.batch-bar-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.batch-action-button {
  min-width: 112px;
  min-height: 38px;
  border: 1px solid rgba(0, 113, 227, 0.16);
  background: linear-gradient(180deg, #ffffff 0%, #f6faff 100%);
  color: #235ea8;
}
.batch-action-button.ghost {
  border-color: rgba(29, 29, 31, 0.08);
  background: #fff;
  color: rgba(29, 29, 31, 0.6);
}
.batch-action-button.refresh {
  border-color: rgba(35, 93, 126, 0.18);
  background: linear-gradient(180deg, #f3fbff 0%, #e7f5fb 100%);
  color: #1f6a86;
}
.batch-action-button.primary {
  border-color: #0071e3;
  background: linear-gradient(135deg, #0a84ff 0%, #0071e3 100%);
  color: #fff;
  box-shadow: 0 10px 20px rgba(0, 113, 227, 0.18);
}
.batch-action-button:hover {
  background: linear-gradient(180deg, #f3f8ff 0%, #e7f1ff 100%);
  border-color: rgba(0, 113, 227, 0.24);
  color: #0c5ec2;
}
.batch-action-button.primary:hover {
  background: linear-gradient(135deg, #2997ff 0%, #0077ed 100%);
  border-color: #0077ed;
  color: #fff;
}
.batch-action-button.refresh:hover {
  background: linear-gradient(180deg, #eaf8ff 0%, #dceff7 100%);
  border-color: rgba(31, 106, 134, 0.26);
  color: #155a73;
}
.work-action-button:hover {
  background: linear-gradient(180deg, #f2f7ff 0%, #e9f2ff 100%);
  border-color: rgba(0, 113, 227, 0.24);
  color: #0f63c8;
}
.work-action-button.primary:hover {
  background: linear-gradient(180deg, #dcecff 0%, #cfe3ff 100%);
  border-color: rgba(0, 113, 227, 0.28);
  color: #005ecb;
}
.work-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}
.work-card,
.owned-card,
.info-card,
.preview-plan {
  border-radius: 18px;
  border: 1px solid rgba(29, 29, 31, 0.07);
  background: #fcfcfd;
}
.work-card {
  position: relative;
  overflow: hidden;
  padding: 12px 12px 11px;
  display: grid;
  gap: 8px;
  align-content: start;
  min-height: 164px;
  cursor: pointer;
  transition: border-color .18s ease, box-shadow .22s ease, transform .18s ease, background .18s ease, filter .18s ease, opacity .18s ease;
}
.work-card.is-downloaded {
  border-color: rgba(67, 160, 94, 0.22);
  background:
    radial-gradient(circle at top right, rgba(93, 193, 122, 0.16), transparent 28%),
    linear-gradient(180deg, #fbfefb 0%, #f3fbf5 100%);
  box-shadow:
    0 14px 28px rgba(53, 102, 72, 0.08),
    inset 0 0 0 1px rgba(93, 193, 122, 0.08);
}
.work-card.is-downloaded:hover {
  border-color: rgba(67, 160, 94, 0.3);
  box-shadow:
    0 18px 30px rgba(53, 102, 72, 0.10),
    inset 0 0 0 1px rgba(93, 193, 122, 0.1);
  background:
    radial-gradient(circle at top right, rgba(93, 193, 122, 0.2), transparent 30%),
    linear-gradient(180deg, #ffffff 0%, #f1fbf4 100%);
}
.work-card:hover {
  transform: translateY(-2px);
  border-color: rgba(52, 120, 246, 0.16);
  box-shadow: 0 12px 24px rgba(38, 74, 134, 0.08);
  background: #ffffff;
}
.work-card.selected {
  border-color: rgba(52, 120, 246, 0.36);
  box-shadow: 0 0 0 2px rgba(52, 120, 246, 0.14), 0 16px 30px rgba(52, 120, 246, 0.12);
  background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
}
.work-card.status-flash {
  animation: workStatusFlash 2.4s ease;
  border-color: rgba(82, 170, 103, 0.54);
  box-shadow:
    0 0 0 2px rgba(82, 170, 103, 0.18),
    0 18px 32px rgba(73, 137, 91, 0.16);
  background:
    radial-gradient(circle at top right, rgba(115, 205, 134, 0.22), transparent 32%),
    linear-gradient(180deg, #fcfffb 0%, #eefaf0 100%);
}
.work-card.status-flash.selected {
  border-color: rgba(82, 170, 103, 0.6);
  box-shadow:
    0 0 0 2px rgba(82, 170, 103, 0.22),
    0 18px 32px rgba(73, 137, 91, 0.18);
}
.work-card.disabled {
  opacity: .96;
  filter: saturate(0.56) grayscale(0.12);
  background: linear-gradient(180deg, #fafbfd 0%, #f1f3f6 100%);
  border-color: rgba(29, 29, 31, 0.07);
  cursor: default;
}
.work-card.disabled:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 16px rgba(29, 29, 31, 0.05);
  background: linear-gradient(180deg, #fafbfd 0%, #f1f3f6 100%);
  border-color: rgba(29, 29, 31, 0.08);
}
@keyframes workStatusFlash {
  0% {
    transform: translateY(0) scale(0.992);
    box-shadow:
      0 0 0 0 rgba(82, 170, 103, 0.34),
      0 8px 18px rgba(73, 137, 91, 0.10);
  }
  18% {
    transform: translateY(-2px) scale(1.008);
    box-shadow:
      0 0 0 6px rgba(82, 170, 103, 0.16),
      0 18px 30px rgba(73, 137, 91, 0.18);
  }
  100% {
    transform: translateY(0) scale(1);
    box-shadow:
      0 0 0 0 rgba(82, 170, 103, 0),
      0 12px 22px rgba(73, 137, 91, 0.10);
  }
}
.work-card-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}
.work-corner-flag {
  position: absolute;
  top: 0;
  right: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 78px;
  height: 26px;
  padding: 0 12px;
  border-bottom-left-radius: 14px;
  background: linear-gradient(180deg, #57c271 0%, #309e57 100%);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .04em;
  box-shadow: 0 8px 16px rgba(48, 158, 87, 0.22);
}
.work-corner-flag::after {
  content: '';
  position: absolute;
  left: -10px;
  top: 0;
  width: 16px;
  height: 100%;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.34) 0%, rgba(255, 255, 255, 0.02) 100%);
  transform: skewX(-28deg);
  opacity: 0.72;
}
.work-card-copy {
  min-height: 72px;
}
.work-rj {
  font-size: 11px;
  font-weight: 700;
  color: #5d7caa;
}
.work-card.disabled .work-rj,
.work-card.disabled .work-title,
.work-card.disabled .work-linked {
  color: rgba(29, 29, 31, 0.4);
}
.work-title,
.owned-title {
  font-size: 13px;
  font-weight: 800;
  color: #1f3554;
  line-height: 1.42;
}
.work-title {
  display: -webkit-box;
  min-height: calc(1.42em * 3);
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.work-linked,
.owned-meta,
.owned-path {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.46);
  line-height: 1.5;
  word-break: break-word;
}
.work-linked {
  min-height: 17px;
}
.work-tags,
.work-actions,
.preview-presets,
.preview-plan-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.work-tags {
  display: flex;
  gap: 4px;
  align-items: center;
  flex-wrap: wrap;
}
.work-actions {
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
  gap: 0;
  flex-wrap: nowrap;
  width: 100%;
  margin-top: auto;
}
.tag-chip {
  height: 20px;
  min-height: 20px;
  width: auto;
  max-width: 100%;
  justify-content: center;
  padding: 0 8px;
  background: #f5f7fa;
  color: #62748a;
  border: 1px solid #dbe3ee;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-sizing: border-box;
  border-radius: 999px;
  font-size: 10px;
  line-height: 1;
  letter-spacing: 0;
  flex: 0 0 auto;
}
.tag-chip.accent {
  background: #edf4ff;
  color: #4c7ed0;
  border-color: #d3e1fb;
}
.tag-chip.owned {
  background: #eef6ff;
  color: #5a7698;
  border-color: #d8e1ef;
}
.tag-chip.local-ready {
  background: #edf8f1;
  color: #2f8b54;
  border-color: #cfe7d7;
}
.work-tags .tag-chip:nth-child(1) {
  background: #fff4f2;
  color: #b86a5e;
  border-color: #f3ddd8;
}
.work-tags .tag-chip.local-ready:nth-child(1) {
  background: #edf8f1;
  color: #2f8b54;
  border-color: #cfe7d7;
}
.work-tags .tag-chip:nth-child(1).owned {
  background: #edf8f1;
  color: #458467;
  border-color: #d2e8da;
}
.work-tags .tag-chip:nth-child(2) {
  background: #edf4ff;
  color: #557fc1;
  border-color: #d4e0f8;
}
.work-tags .tag-chip:nth-child(3) {
  background: #f4f6f9;
  color: #7f8c9b;
  border-color: #e1e6ed;
}
.work-tags .tag-chip:nth-child(3).ok {
  background: #edf9f1;
  color: #468568;
  border-color: #d0e8d8;
}
.work-card.disabled .work-tags .tag-chip:nth-child(3) {
  background: #edf1f5;
  color: #97a2af;
  border-color: #dbe2ea;
}
.work-card.disabled .work-tags .tag-chip:nth-child(1) {
  background: #f4efee;
  color: #9d8c88;
  border-color: #e8dfdc;
}
.work-card.disabled .work-tags .tag-chip:nth-child(2) {
  background: #eef1f5;
  color: #92a0b1;
  border-color: #dde3eb;
}
.work-card.disabled .work-tags .tag-chip.local-ready {
  background: #eef3ef;
  color: #7f9b87;
  border-color: #dde7df;
}
.work-action-button {
  border: 1px solid #b9d7ff;
  background: #ffffff;
  color: #1f6fd6;
  width: auto;
  min-width: 84px;
  min-height: 26px;
  padding: 0 12px;
  justify-content: center;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 2px 6px rgba(31, 111, 214, 0.08);
}
.work-action-button:hover {
  background: linear-gradient(180deg, #2997ff 0%, #0077ed 100%);
  border-color: #0077ed;
  color: #fff;
  box-shadow: 0 8px 16px rgba(31, 111, 214, 0.18);
}
.work-action-button.upload {
  border-color: #cde4d4;
  background: #edf8f1;
  color: #237849;
  box-shadow: 0 2px 6px rgba(35, 120, 73, 0.08);
}
.work-action-button.upload:hover {
  background: linear-gradient(180deg, #45b36a 0%, #2f8b54 100%);
  border-color: #2f8b54;
  color: #fff;
  box-shadow: 0 8px 16px rgba(35, 120, 73, 0.18);
}
.owned-list,
.info-grid,
.preview-plan-list {
  display: grid;
  gap: 10px;
}
.works-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}
.owned-card,
.info-card,
.preview-plan {
  padding: 14px;
}
.owned-list {
  grid-template-columns: 1fr;
}
.owned-card {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 16px;
  background:
    radial-gradient(circle at top right, rgba(10, 132, 255, 0.08), transparent 26%),
    linear-gradient(180deg, #fbfdff 0%, #f5f9ff 100%);
  border: 1px solid rgba(184, 207, 235, 0.62);
  box-shadow: 0 8px 18px rgba(44, 88, 147, 0.06);
}
.owned-card-top,
.owned-card-bottom {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.owned-state-pill,
.owned-rj-pill {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
}
.owned-state-pill {
  background: linear-gradient(180deg, #eef7ff 0%, #e3f0ff 100%);
  border: 1px solid rgba(89, 141, 214, 0.22);
  color: #2f68b7;
}
.owned-rj-pill {
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(177, 198, 224, 0.76);
  color: #48698f;
}
.owned-title {
  font-size: 15px;
  line-height: 1.36;
  color: #18385e;
  display: -webkit-box;
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.owned-meta,
.owned-path {
  font-size: 12px;
  line-height: 1.4;
  color: #667b94;
}
.owned-separator {
  color: #9cafc5;
  font-size: 12px;
  line-height: 1;
}
.info-grid {
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}
.info-label {
  font-size: 12px;
  color: #70819b;
}
.info-value {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: #233d60;
  line-height: 1.6;
  word-break: break-all;
}
.circle-tabs :deep(.el-tabs__header) {
  margin: 0 0 12px;
  padding-top: 2px;
}
.circle-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: #e7eef8;
}
.circle-tabs :deep(.el-tabs__item) {
  height: 38px;
  font-weight: 800;
  color: #60748d;
}
.circle-tabs :deep(.el-tabs__item.is-active) {
  color: #2d6ec0;
}
.circle-tabs :deep(.el-tabs__content) {
  padding-top: 2px;
}
.preview-toolbar {
  margin-bottom: 14px;
}
.preset-chip {
  border: 1px solid #cfe0ff;
  background: #f0f6ff;
  color: #2256a6;
  border-radius: 10px;
  padding: 5px 10px;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
  transition: transform .18s ease, box-shadow .18s ease, background .18s ease;
}
.preset-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 14px rgba(76, 134, 220, 0.12);
}
.preset-chip:active {
  transform: scale(0.98);
}
.preset-chip.ghost {
  background: #fff;
  color: #536a86;
  border-color: #dde5f1;
}
.preview-stats {
  font-size: 13px;
  color: #5d728d;
  font-weight: 700;
}
.preview-plan-rj {
  font-size: 12px;
  font-weight: 800;
  color: #4b70aa;
}
.preview-plan-title {
  margin-top: 4px;
  font-size: 15px;
  font-weight: 800;
  color: #1f3759;
}
.tree-shell {
  margin-top: 12px;
  border: 1px solid #e6edf7;
  border-radius: 14px;
  overflow: hidden;
}
.tree-head,
.tree-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 120px 220px;
  align-items: center;
  padding: 0 12px;
}
.tree-head {
  min-height: 38px;
  background: #f5f8fd;
  border-bottom: 1px solid #e8eef6;
  font-size: 12px;
  font-weight: 800;
  color: #61748d;
}
.tree-body {
  max-height: 420px;
  overflow: auto;
}
.tree-row {
  min-height: 38px;
  border-bottom: 1px solid #eff3f8;
  cursor: pointer;
}
.tree-row.dir {
  background: #fbfcfe;
}
.tree-row.selected {
  background: #eef6ff;
}
.tree-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.tree-arrow,
.tree-arrow-placeholder {
  width: 16px;
  flex: 0 0 16px;
}
.tree-arrow {
  border: none;
  background: transparent;
  color: #7e95b4;
  cursor: pointer;
  transition: transform .18s ease;
}
.tree-arrow.open {
  transform: rotate(90deg);
}
.tree-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #2a3f60;
}
.tree-check {
  width: 14px;
  height: 14px;
  accent-color: #409eff;
}
.reason-pill {
  min-height: 22px;
  background: #fff6ea;
  color: #975a17;
  border: 1px solid #f4d8b1;
}
.dialog-loading {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6c7d95;
}
.compare-board {
  border: 1px solid #e6edf7;
  border-radius: 18px;
  overflow: auto;
  background: #fff;
}
.compare-head,
.compare-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.4fr) repeat(3, minmax(180px, 1fr));
}
.compare-head {
  background: #f5f8fd;
  border-bottom: 1px solid #e8eef6;
  font-size: 12px;
  font-weight: 800;
  color: #61748d;
}
.compare-row + .compare-row {
  border-top: 1px solid #eff3f8;
}
.compare-col {
  padding: 14px 16px;
  min-width: 0;
}
.compare-col + .compare-col {
  border-left: 1px solid #eff3f8;
}
.compare-col.source.kikoeru {
  background: rgba(239, 246, 255, 0.56);
}
.compare-col.source.dlsite {
  background: rgba(255, 247, 237, 0.62);
}
.compare-col.source.asmr {
  background: rgba(236, 253, 245, 0.66);
}
.compare-work-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.compare-work-rj {
  font-weight: 800;
  color: #223754;
}
.compare-work-title {
  margin-top: 6px;
  color: #24364f;
  line-height: 1.55;
}
.compare-work-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #7b8797;
}
.compare-status-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
}
.compare-status-pill.is-owned {
  background: rgba(10, 132, 255, 0.12);
  color: #005fcc;
}
.compare-status-pill.is-downloadable {
  background: rgba(52, 199, 89, 0.12);
  color: #248a3d;
}
.compare-status-pill.is-dl_only {
  background: rgba(255, 59, 48, 0.10);
  color: #c2410c;
}
.compare-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.compare-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #d8e4f2;
  color: #23406f;
  font-size: 12px;
  line-height: 1.2;
}
.compare-chip.is-kikoeru-tag {
  border-color: rgba(10, 132, 255, 0.16);
  background: rgba(239, 246, 255, 0.96);
  color: #005fcc;
  font-weight: 800;
}
.compare-chip.has-icon {
  gap: 4px;
}
.kikoeru-tag-icon {
  width: 12px;
  height: 12px;
  display: inline-block;
  fill: currentColor;
  flex: 0 0 auto;
}
.compare-chip.is-asmr {
  border-color: rgba(52, 199, 89, 0.16);
  background: rgba(236, 253, 245, 0.98);
  color: #248a3d;
  font-weight: 800;
}
.compare-chip.is-asmr-badge {
  border-color: rgba(52, 199, 89, 0.14);
  background: rgba(220, 252, 231, 0.94);
  color: #1f8f51;
  font-weight: 800;
}
.compare-empty {
  color: #8a97aa;
  font-size: 12px;
}
@media (max-width: 1100px) {
  .circle-shell,
  .circle-hero {
    grid-template-columns: 1fr;
  }
  .index-progress-head {
    flex-direction: column;
    align-items: stretch;
  }
  .workbench-toolbar,
  .download-task-head,
  .download-file-row,
  .circle-download-floating-head {
    flex-direction: column;
    align-items: stretch;
  }
  .download-task-meta-grid,
  .download-settings-grid,
  .reimport-summary-grid {
    grid-template-columns: 1fr;
  }
  .compare-head,
  .compare-row {
    grid-template-columns: minmax(220px, 1.2fr) repeat(3, minmax(150px, 1fr));
  }
  .circle-download-floating-card {
    right: 12px;
    left: 12px;
    bottom: 12px;
    width: auto;
  }
}
</style>
