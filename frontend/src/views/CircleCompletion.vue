<template>
  <div class="circle-page">
    <section class="circle-hero">
      <div class="hero-copy">
        <div class="hero-eyebrow">Circle Completion</div>
        <h1>社团补全</h1>
        <p>按社团建立索引，以 Kikoeru 服务器是否已收录作为缺失判断，再结合 DLsite 关联链和 asmr.one 下载能力，把真正缺的作品批量送进下载队列。</p>
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
            <div class="sidebar-title">最近索引</div>
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
            <div>
              <div class="toolbar-title">{{ detail.circle_name || '未选择社团' }}</div>
              <div class="toolbar-subtitle">{{ detail.source_mask || '等待建立索引' }}</div>
            </div>
            <div class="toolbar-metrics">
              <span class="metric-pill">服务器已有 {{ detail.owned_count || 0 }}</span>
              <span class="metric-pill warn">服务器缺失 {{ detail.missing_count || 0 }}</span>
              <span class="metric-pill ok">可下载 {{ detail.downloadable_count || 0 }}</span>
              <span class="metric-pill">{{ detail.dl_only_count || 0 }} 个暂不可下</span>
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
              <div class="batch-count">已选 {{ selectedCanonicalRJCodes.length }} 个作品</div>
              <div class="batch-hint">这里只看服务器缺失项。进入下载器的仍然只会是 asmr.one 可下载作品。</div>
            </div>
            <div class="batch-bar-actions">
              <el-button class="batch-action-button" @click="selectAllDownloadable">全选可下载</el-button>
              <el-button class="batch-action-button ghost" @click="clearSelection">清空</el-button>
              <el-button class="batch-action-button primary" type="primary" :disabled="selectedCanonicalRJCodes.length === 0" :loading="previewing" @click="openBatchPreview()">创建下载任务</el-button>
            </div>
          </div>

          <el-tabs v-model="activeTab" class="circle-tabs">
            <el-tab-pane label="缺失作品" name="missing">
              <div class="work-grid">
                <article
                  v-for="item in pagedMissingWorks"
                  :key="item.canonical_rjcode"
                  class="work-card"
                  :class="{ selected: selectedCanonicals.has(item.canonical_rjcode), disabled: !item.has_asmr_one }"
                >
                  <div class="work-card-head">
                    <div>
                      <div class="work-rj">{{ item.display_rjcode || item.canonical_rjcode }}</div>
                      <div class="work-title">{{ item.title || '未命名作品' }}</div>
                    </div>
                    <el-checkbox
                      :model-value="selectedCanonicals.has(item.canonical_rjcode)"
                      :disabled="!item.has_asmr_one"
                      @change="toggleSelection(item)"
                    />
                  </div>

                  <div class="work-linked">{{ item.display_rjcode || item.canonical_rjcode }}</div>

                  <div class="work-tags">
                    <span class="tag-chip" :class="{ owned: item.server_owned }">服务器 {{ item.server_owned ? '已有' : '缺失' }}</span>
                    <span class="tag-chip">DLsite {{ item.has_dlsite ? '有' : '未知' }}</span>
                    <span class="tag-chip" :class="{ ok: item.has_asmr_one }">asmr.one {{ item.has_asmr_one ? '可下载' : '无资源' }}</span>
                  </div>

                  <div v-if="item.has_asmr_one" class="work-actions">
                    <el-button size="small" class="work-action-button" @click="openBatchPreview(item.canonical_rjcode)">预览下载</el-button>
                    <el-button size="small" class="work-action-button primary" type="primary" plain @click="toggleSelection(item)">
                      {{ selectedCanonicals.has(item.canonical_rjcode) ? '移出批量' : '加入批量' }}
                    </el-button>
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
                  <div class="owned-title">{{ item.title || item.canonical_rjcode }}</div>
                  <div class="owned-meta">{{ item.display_rjcode || item.canonical_rjcode }}</div>
                  <div class="owned-path">服务器已收录</div>
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
          <el-button size="small" @click="refreshDownloadWorkbench" :loading="downloadWorkbenchRefreshing">刷新</el-button>
          <el-button size="small" @click="hideDownloadWorkbenchToBackground">隐藏到后台</el-button>
          <el-button size="small" @click="closeDownloadWorkbench">关闭</el-button>
        </div>
      </div>

      <div v-if="trackedDownloadTasks.length" class="download-task-list">
        <article v-for="task in trackedDownloadTasks" :key="task.id" class="download-task-card">
          <div class="download-task-head">
            <div class="download-task-heading">
              <div class="download-task-rj">{{ task.rjcode || '未知 RJ' }}</div>
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
          <div class="download-task-meta-grid">
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">下载目录</span>
              <span class="download-task-meta-value">{{ task.task_metadata?.download_root || task.task_metadata?.download_base_path || '默认临时目录' }}</span>
            </div>
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">最终路径</span>
              <span class="download-task-meta-value">{{ task.task_metadata?.final_output_path || task.output_path || task.task_metadata?.target_path || '处理中' }}</span>
            </div>
            <div class="download-task-meta-item">
              <span class="download-task-meta-label">下载大小</span>
              <span class="download-task-meta-value">{{ formatSize(task.performance_metrics?.downloaded_bytes || task.task_metadata?.performance_metrics?.downloaded_bytes || 0) }}</span>
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
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api, { asmrSyncApi, circleCompletionApi, libraryApi } from '../api'

const CIRCLE_COMPLETION_TARGET_SUBDIRS_KEY = 'prekikoeru.circleCompletion.targetSubdirs'
const CIRCLE_COMPLETION_DOWNLOAD_WORKBENCH_KEY = 'prekikoeru.circleCompletion.downloadWorkbench'

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
  onlyMissing: true,
  onlyDownloadable: false,
  includeDlOnly: true
})
const activeTab = ref('missing')
const selectedCanonicals = ref(new Set())
const previewDialogVisible = ref(false)
const previewPlans = ref([])
const libraries = ref([])
const trackedDownloadTaskIds = ref([])
const downloadWorkbenchVisible = ref(false)
const downloadWorkbenchBackgroundActive = ref(false)
const downloadWorkbenchRefreshing = ref(false)
const trackedDownloadTasks = ref([])
const worksPageSize = 24
const missingPage = ref(1)
const ownedPage = ref(1)
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
const downloadSettings = reactive({
  downloadBasePath: '',
  targetLibraryId: '',
  targetSubdir: '',
  namingMode: 'api',
  classifyMode: 'circle'
})
const cachedTargetSubdirs = ref([])

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
const selectedCanonicalRJCodes = computed(() => [...selectedCanonicals.value])
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

onMounted(async () => {
  hydrateDownloadWorkbenchState()
  loadCachedTargetSubdirs()
  await Promise.all([loadRecentCircles(), loadLibraries()])
  if (trackedDownloadTaskIds.value.length) await refreshDownloadWorkbench()
})

onActivated(() => {
  if (indexJob.job_id && !['completed', 'failed'].includes(indexJob.status)) {
    indexing.value = true
    pollIndexJob(indexJob.job_id)
  }
  if (trackedDownloadTaskIds.value.length) {
    refreshDownloadWorkbench()
  }
})

onBeforeUnmount(() => {
  stopIndexJobPolling()
  stopDownloadWorkbenchPolling()
})

watch(activeTab, (tab) => {
  if (tab === 'missing') missingPage.value = 1
  if (tab === 'owned') ownedPage.value = 1
})

watch(() => detail.works, () => {
  missingPage.value = 1
  ownedPage.value = 1
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

watch(() => downloadSettings.targetSubdir, (value) => {
  if (value) rememberTargetSubdir(value)
})

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
  const mins = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
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

function getFailureSummary(task) {
  const failedFiles = Array.isArray(task?.failed_files) ? task.failed_files.length : 0
  const verifyFailures = Array.isArray(task?.verification_failures) ? task.verification_failures.length : 0
  if (!failedFiles && !verifyFailures) return '0'
  const parts = []
  if (failedFiles) parts.push(`下载失败 ${failedFiles}`)
  if (verifyFailures) parts.push(`校验失败 ${verifyFailures}`)
  return parts.join(' / ')
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

async function refreshDownloadWorkbench() {
  if (!trackedDownloadTaskIds.value.length) {
    trackedDownloadTasks.value = []
    stopDownloadWorkbenchPolling()
    return
  }
  downloadWorkbenchRefreshing.value = true
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
    downloadWorkbenchRefreshing.value = false
  }
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
      [...selectedCanonicals.value].filter(code => (result.works || []).some(item => item.canonical_rjcode === code && item.has_asmr_one))
    )
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载社团详情失败')
  }
}

function toggleSelection(item) {
  if (!item?.has_asmr_one) return
  const next = new Set(selectedCanonicals.value)
  if (next.has(item.canonical_rjcode)) next.delete(item.canonical_rjcode)
  else next.add(item.canonical_rjcode)
  selectedCanonicals.value = next
}

function selectAllDownloadable() {
  selectedCanonicals.value = new Set(
    missingWorks.value.filter(item => item.has_asmr_one).map(item => item.canonical_rjcode)
  )
}

function clearSelection() {
  selectedCanonicals.value = new Set()
}

async function openBatchPreview(singleCanonical = '') {
  const codes = singleCanonical ? [singleCanonical] : selectedCanonicalRJCodes.value
  if (!codes.length) {
    ElMessage.warning('先选中要下载的作品')
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
.circle-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(280px, 420px);
  gap: 16px;
  padding: 24px 26px;
  border-radius: 24px;
  background:
    radial-gradient(circle at top right, rgba(0, 113, 227, 0.16), transparent 28%),
    linear-gradient(135deg, #f7fbff 0%, #eef5ff 48%, #fdfefe 100%);
  border: 1px solid #dde9fb;
  box-shadow: 0 18px 34px rgba(45, 86, 145, 0.08);
}
.hero-eyebrow {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: #5d7baa;
}
.circle-hero h1 {
  margin: 8px 0 10px;
  font-size: 32px;
  line-height: 1.05;
  color: #1d3557;
}
.circle-hero p {
  margin: 0;
  max-width: 760px;
  color: #5c6f86;
  line-height: 1.7;
}
.hero-actions {
  display: grid;
  gap: 10px;
  align-content: center;
}
.hero-search-input :deep(.el-input__wrapper) {
  min-height: 44px;
  border-radius: 14px;
  box-shadow: 0 0 0 1px rgba(190, 213, 247, 0.95) inset;
  background: rgba(255, 255, 255, 0.94);
}
.hero-search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px rgba(77, 136, 226, 0.22) inset;
}
.hero-search-button,
.batch-action-button,
.work-action-button {
  border-radius: 12px;
  font-weight: 800;
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease, color .18s ease;
}
.hero-search-button {
  min-height: 44px;
  border: 1px solid #82b7f8;
  background: linear-gradient(135deg, #79b8ff 0%, #5fa4f3 100%);
  box-shadow: 0 12px 24px rgba(76, 134, 220, 0.22);
}
.hero-search-button:hover,
.batch-action-button:hover,
.work-action-button:hover {
  transform: translateY(-1px);
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
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
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
  padding: 18px;
  display: grid;
  gap: 12px;
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
  color: #223a5d;
}
.toolbar-card {
  padding: 18px 18px 14px;
  display: grid;
  gap: 12px;
}
.toolbar-subtitle {
  font-size: 12px;
  color: #6b809d;
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
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}
.metric-pill {
  background: #edf4ff;
  color: #265aa7;
  border: 1px solid #d4e5ff;
}
.metric-pill.warn {
  background: #fff6ea;
  color: #a05c16;
  border-color: #f6d8a8;
}
.metric-pill.ok,
.tag-chip.ok,
.reason-pill.ok {
  background: #ecfaf1;
  color: #19744b;
  border: 1px solid #cdeedb;
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
  padding: 12px;
  border: 1px solid #e6eef7;
  border-radius: 14px;
  background: #fbfdff;
  text-align: left;
  cursor: pointer;
  transition: border-color .18s ease, box-shadow .18s ease, background .18s ease, transform .18s ease;
}
.circle-list-item:hover {
  border-color: #b8d3ff;
  background: #f4f8ff;
  box-shadow: 0 10px 20px rgba(69, 122, 195, 0.10);
  transform: translateY(-1px);
}
.circle-list-item.active {
  border-color: #9ec3ff;
  background: linear-gradient(180deg, #f7faff 0%, #edf4ff 100%);
  box-shadow: 0 0 0 1px rgba(120, 171, 244, 0.22), 0 10px 20px rgba(69, 122, 195, 0.08);
  transform: none;
}
.circle-list-name {
  font-size: 14px;
  font-weight: 700;
  color: #274064;
}
.circle-list-meta {
  margin-top: 4px;
  display: grid;
  gap: 2px;
  font-size: 11px;
  color: #7a8ca4;
}
.works-card {
  padding: 16px;
  display: grid;
  gap: 16px;
}
.batch-bar {
  padding: 12px 14px;
  border-radius: 16px;
  background: linear-gradient(135deg, #f5f9ff 0%, #fffdf8 100%);
  border: 1px solid #e5eefc;
}
.batch-count {
  font-size: 14px;
  font-weight: 800;
  color: #21426d;
}
.batch-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #6d7f98;
}
.batch-bar-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.batch-action-button {
  min-width: 116px;
  min-height: 36px;
  border: 1px solid #d6e3f7;
  background: linear-gradient(180deg, #ffffff 0%, #f5f9ff 100%);
  color: #335276;
}
.batch-action-button.ghost {
  background: #fff;
  color: #637892;
}
.batch-action-button.primary {
  border-color: #82b7f8;
  background: linear-gradient(135deg, #79b8ff 0%, #5fa4f3 100%);
  color: #fff;
  box-shadow: 0 10px 20px rgba(76, 134, 220, 0.18);
}
.work-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 14px;
}
.work-card,
.owned-card,
.info-card,
.preview-plan {
  border-radius: 18px;
  border: 1px solid #e8eef7;
  background: #fcfdff;
}
.work-card {
  padding: 14px;
  display: grid;
  gap: 10px;
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.work-card.selected {
  border-color: #9bc1ff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.08);
  background: #f7fbff;
}
.work-card.disabled {
  opacity: .82;
}
.work-card-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}
.work-rj {
  font-size: 12px;
  font-weight: 800;
  color: #4f73ab;
}
.work-title,
.owned-title {
  font-size: 15px;
  font-weight: 800;
  color: #22395a;
  line-height: 1.5;
}
.work-linked,
.owned-meta,
.owned-path {
  font-size: 12px;
  color: #70839a;
  line-height: 1.6;
  word-break: break-all;
}
.work-tags,
.work-actions,
.preview-presets,
.preview-plan-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.tag-chip {
  min-height: 24px;
  background: #f2f6fb;
  color: #516882;
  border: 1px solid #e1e9f3;
}
.tag-chip.accent {
  background: #eef4ff;
  color: #3564a6;
  border-color: #cfe0ff;
}
.tag-chip.owned {
  background: #eefaf3;
  color: #1d7d50;
  border-color: #d2eedc;
}
.work-action-button {
  border: 1px solid #d5e2f5;
  background: #fff;
  color: #38587c;
}
.work-action-button.primary {
  border-color: #b8d3ff;
  background: #eef5ff;
  color: #2f69b6;
}
.owned-list,
.info-grid,
.preview-plan-list {
  display: grid;
  gap: 12px;
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
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
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
  .download-settings-grid {
    grid-template-columns: 1fr;
  }
  .circle-download-floating-card {
    right: 12px;
    left: 12px;
    bottom: 12px;
    width: auto;
  }
}
</style>
