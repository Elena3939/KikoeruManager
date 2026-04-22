<template>
  <component
    :is="immersive ? 'div' : 'el-card'"
    :shadow="immersive ? undefined : 'never'"
    :class="immersive ? 'subtitle-tree-card subtitle-tree-card-immersive' : 'subtitle-tree-card'"
  >
    <template v-if="!immersive" #header>
      <div class="subtitle-section-header">
        <div class="subtitle-section-heading">
          <div class="subtitle-section-heading-title">
            <span class="subtitle-section-icon"><Sparkles :size="16" :stroke-width="2" /></span>
            <span class="subtitle-tree-title">字幕筛选与配对</span>
          </div>
          <div class="subtitle-section-tip">上半区先清理不要的原始字幕，下半区预览配对结果，最后一次性把音频和字幕处理成同名。</div>
        </div>
        <div class="subtitle-tree-actions">
          <el-tooltip effect="light" placement="top" content="刷新当前页">
            <span class="subtitle-btn-tooltip-wrap">
              <el-button class="workbench-icon-btn" circle size="small" :disabled="!view.subtitleInspectorInfo.subtitleDir || view.subtitleInspectorBusy" :loading="view.subtitleInspectorLoading" @click="view.reloadSubtitleInspector">
                <RefreshCw :size="14" :stroke-width="2.2" />
              </el-button>
            </span>
          </el-tooltip>
          <el-tooltip effect="light" placement="top" content="展开所有子目录">
            <span class="subtitle-btn-tooltip-wrap">
              <el-button class="workbench-icon-btn" circle size="small" :disabled="!view.subtitleInspectorInfo.subtitleDir || !view.subtitleInspectorHasDirectories || view.subtitleInspectorBusy" @click="view.expandSubtitleInspectorTree">
                <ChevronsDown :size="14" :stroke-width="2.2" />
              </el-button>
            </span>
          </el-tooltip>
          <el-tooltip effect="light" placement="top" content="折叠所有子目录">
            <span class="subtitle-btn-tooltip-wrap">
              <el-button class="workbench-icon-btn" circle size="small" :disabled="!view.subtitleInspectorInfo.subtitleDir || !view.subtitleInspectorHasDirectories || view.subtitleInspectorBusy" @click="view.collapseSubtitleInspectorTree">
                <ChevronsUp :size="14" :stroke-width="2.2" />
              </el-button>
            </span>
          </el-tooltip>
        </div>
      </div>
    </template>

    <div
      v-if="!view.subtitleInspectorInfo.subtitleDir && pendingInProgressTask"
      class="subtitle-inspector-empty subtitle-inspector-empty--loading"
      v-app-loading="{ loading: true, text: pendingLoadingText, size: 124 }"
    ></div>
    <div v-else-if="!view.subtitleInspectorInfo.subtitleDir" class="subtitle-inspector-empty">
      <AppEmptyState description="从左侧任务里选择一个已生成字幕目录的任务进行检查" size="default">
        <div class="subtitle-empty-tip">任务完成后会进入上方任务队列，点击对应卡片再进入这里做筛选和配对。</div>
      </AppEmptyState>
    </div>

    <div v-else class="subtitle-tree-shell" v-app-loading="{ loading: view.subtitleInspectorBusy, text: '正在处理字幕目录...', size: 124 }">
      <div class="subtitle-tree-info">
        <div class="subtitle-tree-info-top">
          <div class="subtitle-tree-info-head">
            <span class="subtitle-tree-info-icon"><FolderOpen :size="18" :stroke-width="2" /></span>
            <div class="subtitle-tree-info-main">
              <div class="subtitle-tree-title">{{ getDisplayFolderTitle() }}</div>
            </div>
          </div>
        </div>
        <div class="subtitle-tree-info-bottom">
          <div class="subtitle-tree-meta">
            <span class="subtitle-mini-chip subtitle-mini-chip-accent"><Hash :size="11" :stroke-width="2.4" />{{ view.getTaskDisplayRJCode(view.activeSubtitleInspectTask) }}</span>
            <span v-if="view.getTaskSourceRJCode(view.activeSubtitleInspectTask)" class="subtitle-mini-chip"><Link :size="11" :stroke-width="2.4" />来源 {{ view.getTaskSourceRJCode(view.activeSubtitleInspectTask) }}</span>
            <span class="subtitle-mini-chip"><Music :size="11" :stroke-width="2.4" />{{ view.subtitleInspectorAudioFiles.length }} 个音频</span>
            <span class="subtitle-mini-chip"><FileText :size="11" :stroke-width="2.4" />{{ view.subtitleInspectorInfo.totalFiles }} 个字幕</span>
            <span class="subtitle-mini-chip"><Database :size="11" :stroke-width="2.4" />{{ view.formatFileSize(view.subtitleInspectorInfo.totalSize) }}</span>
          </div>
          <div v-if="view.activeSubtitleInspectTask" class="subtitle-tree-actions subtitle-tree-info-actions subtitle-tree-info-actions-bottom">
            <el-button
              size="small"
              class="workbench-pill-btn workbench-pill-danger"
              :disabled="!view.canCancelRJSubtitleTask?.(view.activeSubtitleInspectTask)"
              :loading="view.subtitleCancelingId === view.activeSubtitleInspectTask.id"
              @click="view.cancelRJSubtitleTask(view.activeSubtitleInspectTask)"
            >
              <CircleX :size="13" :stroke-width="2.2" /><span>取消任务</span>
            </el-button>
            <el-button
              size="small"
              class="workbench-pill-btn"
              :disabled="!view.canClearCurrentSubtitleTask?.(view.activeSubtitleInspectTask)"
              @click="view.clearCurrentSubtitleTask(view.activeSubtitleInspectTask)"
            >
              <Trash2 :size="13" :stroke-width="2.2" /><span>清空当前任务</span>
            </el-button>
            <el-button
              size="small"
              class="workbench-pill-btn workbench-pill-warn"
              :disabled="!view.canRerunSubtitleTask?.(view.activeSubtitleInspectTask)"
              :loading="view.subtitleTaskRerunId === view.activeSubtitleInspectTask.id"
              @click="view.rerunSubtitleTask(view.activeSubtitleInspectTask)"
            >
              <RotateCcw :size="13" :stroke-width="2.2" /><span>重新执行爬取字幕</span>
            </el-button>
          </div>
        </div>
      </div>

      <div v-if="showPairing" class="subtitle-match-shell">
        <div class="subtitle-match-header">
          <div class="subtitle-match-header-title">
            <div class="subtitle-section-heading-title">
              <span class="subtitle-section-icon subtitle-section-icon-match"><Link2 :size="15" :stroke-width="2.2" /></span>
              <span class="subtitle-tree-title subtitle-tree-title-md">配对结果预览</span>
            </div>
            <div class="subtitle-section-tip">先在这里筛掉不需要的原始字幕，再生成预匹配结果，确认后再一键应用同名。</div>
            <div v-if="view.subtitleSequenceMode" class="subtitle-sequence-hint">
              <Wand2 :size="13" :stroke-width="2.2" />
              <span>顺序点选进行中：先在左侧依次点音频，再在右侧依次点字幕，然后生成顺序配对。当前已点选 音频 {{ view.subtitleSequenceSelection.audioPaths.length }} 项 / 字幕 {{ view.subtitleSequenceSelection.subtitlePaths.length }} 项。</span>
            </div>
          </div>
          <div class="subtitle-match-header-actions">
            <el-button size="small" class="workbench-pill-btn" @click="view.buildAutoSubtitlePairs">
              <Wand2 :size="13" :stroke-width="2.2" /><span>自动预配对</span>
            </el-button>
            <el-button size="small" :class="['workbench-pill-btn', view.subtitleSequenceMode ? 'workbench-pill-active' : '']" @click="view.setSubtitleSequenceMode(!view.subtitleSequenceMode)">
              <MousePointerClick :size="13" :stroke-width="2.2" /><span>{{ view.subtitleSequenceMode ? '退出顺序点选' : '顺序点选配对' }}</span>
            </el-button>
            <el-button
              size="small"
              class="workbench-pill-btn"
              :disabled="view.subtitleSequenceMode ? !view.canBuildSequenceSubtitlePairs : !view.filteredSubtitleInspectorAudioFiles.length || !view.filteredSubtitleInspectorSubtitleFiles.length"
              @click="view.buildSequenceOrOrderedSubtitlePairs"
            >
              <ListOrdered :size="13" :stroke-width="2.2" /><span>{{ view.subtitleSequenceMode ? '生成顺序预配对' : '按当前列表预配对' }}</span>
            </el-button>
            <el-tooltip
              effect="light"
              popper-class="subtitle-inspector-tooltip"
              placement="top"
              :disabled="Boolean(view.subtitleManualPairs.length)"
              content="请先在中间区域生成或添加至少一组配对，再执行应用。"
            >
              <span class="subtitle-btn-tooltip-wrap">
                <el-button
                  size="small"
                  type="primary"
                  class="workbench-primary-btn"
                  :disabled="!view.subtitleManualPairs.length"
                  :loading="view.subtitlePairApplying"
                  @click="view.applySubtitleManualPairs"
                >
                  <CheckCircle2 :size="14" :stroke-width="2.2" /><span>{{ view.subtitleManualApplyLabel || '一键应用同名' }}</span>
                </el-button>
              </span>
            </el-tooltip>
          </div>
        </div>

        <el-alert
          v-if="view.activeSubtitleInspectTask?.manual_match_completed || view.subtitleInspectorInfo.manualMatchCompleted"
          type="success"
          :closable="false"
          show-icon
          class="subtitle-match-done-alert"
          :title="`已匹配完成，已应用 ${view.activeSubtitleInspectTask?.manual_match_applied_pairs || view.subtitleInspectorInfo.manualMatchAppliedPairs || 0} 组配对。若还要调整，可以继续重新筛选后再次应用。`"
        />

        <div class="subtitle-match-layout">
          <div class="subtitle-match-panel subtitle-match-panel-audio">
            <div class="subtitle-match-panel-head">
              <div class="subtitle-task-box-title subtitle-task-box-title-audio"><Music :size="14" :stroke-width="2.2" />原音频目录</div>
              <div class="subtitle-match-panel-tools">
                <span class="subtitle-box-meta">{{ view.filteredSubtitleInspectorAudioFiles.length }} 项</span>
                <el-select :model-value="view.subtitleAudioFilterMode" size="small" class="subtitle-match-filter-select" @update:model-value="view.setSubtitleAudioFilterMode">
                  <el-option label="全部" value="all" />
                  <el-option label="已配对" value="paired" />
                  <el-option label="未配对" value="unpaired" />
                </el-select>
              </div>
            </div>
            <input :value="view.subtitleInspectorAudioSearch" class="fm-search-input subtitle-match-search" placeholder="搜索音频名..." :disabled="view.subtitleInspectorBusy" @input="view.setSubtitleInspectorAudioSearch($event.target.value)">
            <div class="subtitle-match-list">
              <button
                v-for="audio in view.filteredSubtitleInspectorAudioFiles"
                :key="audio.path"
                type="button"
                class="subtitle-match-item"
                :class="{
                  active: view.subtitleMatchSelection.audioPath === audio.path,
                  paired: view.isAudioPaired(audio.path),
                  suspicious: view.isAudioSuspicious(audio.path),
                  queued: view.getSubtitleSequenceIndex('audio', audio.path) > 0
                }"
                @click="view.selectSubtitleAudio(audio)"
              >
                <div class="subtitle-match-name">
                  {{ formatSubtitleItemName(audio) }}
                  <span v-if="view.isAudioPaired(audio.path)" class="subtitle-match-badge badge-paired">已配对</span>
                  <span v-if="view.isAudioSuspicious(audio.path)" class="subtitle-match-badge badge-low">待确认</span>
                  <span v-if="view.getSubtitleSequenceIndex('audio', audio.path)" class="subtitle-match-badge badge-seq">#{{ view.getSubtitleSequenceIndex('audio', audio.path) }}</span>
                </div>
                <div class="subtitle-match-meta">{{ audio.relative_path || audio.name }}</div>
              </button>
            </div>
          </div>

          <div class="subtitle-match-center">
            <div class="subtitle-match-panel-head subtitle-match-preview-head">
              <div class="subtitle-task-box-title subtitle-task-box-title-center"><Link2 :size="14" :stroke-width="2.2" />配对结果预览</div>
              <div class="subtitle-match-preview-actions">
                <el-tooltip
                  effect="light"
                  popper-class="subtitle-inspector-tooltip"
                  placement="top"
                  :disabled="view.subtitleInspectorBusy || view.canAddSubtitleManualPair"
                  content="请先在左侧选一条音频，再在右侧选一条字幕，然后点此加入配对。"
                >
                  <span class="subtitle-btn-tooltip-wrap">
                    <el-button
                      size="small"
                      type="primary"
                      :disabled="!view.canAddSubtitleManualPair || view.subtitleInspectorBusy"
                      @click="view.addSubtitleManualPair"
                    >
                      加入手动配对
                    </el-button>
                  </span>
                </el-tooltip>
                <el-button size="small" text :disabled="view.subtitleInspectorBusy || (!view.subtitleSequenceSelection.audioPaths.length && !view.subtitleSequenceSelection.subtitlePaths.length)" @click="view.clearSubtitleSequenceSelection">清空顺序</el-button>
                <el-button size="small" text :disabled="view.subtitleInspectorBusy || !view.subtitleManualPairs.length" @click="view.clearSubtitleManualPairs">清空配对</el-button>
              </div>
            </div>
            <div class="subtitle-match-pair-list">
              <div v-if="!view.subtitleManualPairs.length" class="subtitle-match-empty">
                <div>还没有生成配对结果</div>
                <div class="subtitle-card-tip">可以先点“自动预配对”，也可以左右各选一项后加入手动配对。</div>
              </div>
              <button
                v-for="(pair, index) in view.subtitleManualPairs"
                :key="pair.id"
                type="button"
                class="subtitle-match-pair"
                :class="{ active: view.subtitleSelectedManualPairId === pair.id, suspicious: pair.confidenceLevel === 'low' }"
                @click="view.setSubtitleSelectedManualPairId(pair.id)"
              >
                <div class="subtitle-match-pair-head">
                  <div class="subtitle-match-pair-head-left">
                    <span class="subtitle-match-pair-confidence" :class="`confidence-${pair.confidenceLevel || 'medium'}`">{{ view.getSubtitlePairConfidenceLabel(pair.confidenceLevel) }}</span>
                    <span class="subtitle-match-pair-track">配对 {{ index + 1 }}</span>
                  </div>
                  <span class="subtitle-match-pair-reason">{{ pair.matchReason || '手动配对' }}</span>
                </div>
                <div class="subtitle-match-pair-flow">
                  <div class="subtitle-match-flow-side subtitle-match-flow-source">
                    <span class="subtitle-match-flow-label">原始</span>
                    <div class="subtitle-match-flow-line" :title="formatSubtitleName(pair.audio_name)">
                      <Music :size="12" :stroke-width="2.2" class="subtitle-match-flow-icon subtitle-match-flow-icon-audio" />
                      <span class="subtitle-match-flow-text">{{ formatSubtitleName(pair.audio_name) }}</span>
                    </div>
                    <div class="subtitle-match-flow-line" :title="formatSubtitleName(pair.subtitle_name)">
                      <FileText :size="12" :stroke-width="2.2" class="subtitle-match-flow-icon subtitle-match-flow-icon-subtitle" />
                      <span class="subtitle-match-flow-text">{{ formatSubtitleName(pair.subtitle_name) }}</span>
                    </div>
                  </div>
                  <div class="subtitle-match-flow-arrow">
                    <ArrowRight :size="16" :stroke-width="2.2" />
                  </div>
                  <div class="subtitle-match-flow-side subtitle-match-flow-target">
                    <span class="subtitle-match-flow-label">应用后</span>
                    <div class="subtitle-match-flow-line" :title="pair.target_audio_name">
                      <Music :size="12" :stroke-width="2.2" class="subtitle-match-flow-icon subtitle-match-flow-icon-audio" />
                      <span class="subtitle-match-flow-text">{{ pair.target_audio_name }}</span>
                    </div>
                    <div class="subtitle-match-flow-line" :title="pair.target_subtitle_name">
                      <FileText :size="12" :stroke-width="2.2" class="subtitle-match-flow-icon subtitle-match-flow-icon-subtitle" />
                      <span class="subtitle-match-flow-text">{{ pair.target_subtitle_name }}</span>
                    </div>
                  </div>
                </div>
                <div class="subtitle-match-row-actions">
                  <el-button size="small" text type="danger" :disabled="view.subtitleInspectorBusy" @click.stop="view.removeSubtitleManualPair(pair.id)">移除</el-button>
                </div>
              </button>
            </div>
          </div>

          <div class="subtitle-match-panel subtitle-match-panel-subtitle">
            <div class="subtitle-match-panel-head">
              <div class="subtitle-task-box-title subtitle-task-box-title-subtitle"><FileText :size="14" :stroke-width="2.2" />字幕目录</div>
              <div class="subtitle-match-panel-tools">
                <span class="subtitle-box-meta">{{ view.filteredSubtitleInspectorSubtitleFiles.length }} 项</span>
                <el-select :model-value="view.subtitleSubtitleFilterMode" size="small" class="subtitle-match-filter-select" @update:model-value="view.setSubtitleSubtitleFilterMode">
                  <el-option label="全部" value="all" />
                  <el-option label="已配对" value="paired" />
                  <el-option label="未配对" value="unpaired" />
                </el-select>
              </div>
            </div>
            <input :value="view.subtitleInspectorSubtitleSearch" class="fm-search-input subtitle-match-search" placeholder="搜索字幕名..." :disabled="view.subtitleInspectorBusy" @input="view.setSubtitleInspectorSubtitleSearch($event.target.value)">
            <div class="subtitle-match-list">
              <button
                v-for="subtitle in view.filteredSubtitleInspectorSubtitleFiles"
                :key="subtitle.path"
                type="button"
                class="subtitle-match-item"
                :class="{
                  active: view.subtitleMatchSelection.subtitlePath === subtitle.path,
                  paired: view.isSubtitlePaired(subtitle.path),
                  suspicious: view.isSubtitleSuspicious(subtitle.path),
                  queued: view.getSubtitleSequenceIndex('subtitle', subtitle.path) > 0
                }"
                @click="view.selectSubtitleFile(subtitle)"
              >
                <div class="subtitle-match-name">
                  {{ formatSubtitleItemName(subtitle) }}
                  <span v-if="view.isSubtitlePaired(subtitle.path)" class="subtitle-match-badge badge-paired">已配对</span>
                  <span v-if="view.isSubtitleSuspicious(subtitle.path)" class="subtitle-match-badge badge-low">待确认</span>
                  <span v-if="view.getSubtitleSequenceIndex('subtitle', subtitle.path)" class="subtitle-match-badge badge-seq">#{{ view.getSubtitleSequenceIndex('subtitle', subtitle.path) }}</span>
                </div>
                <div class="subtitle-match-meta">{{ subtitle.relative_path || subtitle.name }}</div>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="showPairing && view.activeSubtitleTaskProgressLogs?.length" class="subtitle-pairing-log-shell">
        <div class="subtitle-pairing-log-head">
          <div class="subtitle-task-box-title">过程日志</div>
          <div class="subtitle-box-meta">{{ view.activeSubtitleTaskProgressLogs.length }} 条</div>
        </div>
        <div class="subtitle-log-list">
          <div v-for="(entry, idx) in view.activeSubtitleTaskProgressLogs" :key="`pair-log-${idx}`" class="subtitle-log-row">
            <span class="subtitle-log-time">{{ view.formatProgressLogTime(entry.time) }}</span>
            <span class="subtitle-log-level" :class="`level-${entry.level || 'info'}`">{{ view.getProgressLogLevelLabel(entry.level) }}</span>
            <span class="subtitle-inline-primary">{{ entry.message }}</span>
          </div>
        </div>
      </div>

      <div v-if="showTree" class="subtitle-tree-toolbar">
        <input :value="view.subtitleInspectorSearch" class="fm-search-input" placeholder="搜索字幕文件名或路径..." :disabled="view.subtitleInspectorBusy" @input="view.setSubtitleInspectorSearch($event.target.value)">
      </div>

      <div v-if="showTree && view.subtitleInspectorSelectedRows.length" class="subtitle-tree-selection-bar">
        <span class="subtitle-tree-selection-count">已选 {{ view.subtitleInspectorSelectedRows.length }} 项</span>
        <div class="subtitle-tree-selection-actions">
          <span class="subtitle-tree-selection-tip">支持 Ctrl+A、Ctrl/Command + 点击多选、Shift + 点击范围选择</span>
          <el-button size="small" type="danger" plain :loading="view.subtitleInspectorDeleting" :disabled="view.subtitleInspectorBusy && !view.subtitleInspectorDeleting" @click="view.batchDeleteSubtitleTreeEntries">删除选中</el-button>
          <el-button size="small" :disabled="view.subtitleInspectorBusy" @click="view.clearSubtitleInspectorSelection">取消选择</el-button>
        </div>
      </div>

      <div v-if="showTree" class="fm-head subtitle-tree-head">
        <div class="fm-col-check">
          <input type="checkbox" class="fm-check" :checked="view.subtitleInspectorAllSelected" :indeterminate.prop="view.subtitleInspectorSomeSelected" :disabled="view.subtitleInspectorBusy" @click="view.toggleAllSubtitleInspectorRows">
        </div>
        <div class="fm-col-name">文件名</div>
        <div class="fm-col-size">大小</div>
        <div class="fm-col-time">修改时间</div>
        <div class="fm-col-action">操作</div>
      </div>

      <div v-if="showTree" class="fm-scroll subtitle-tree-scroll">
        <div v-if="!view.subtitleInspectorLoading && view.subtitleInspectorFlatTree.length === 0" class="fm-empty">
          {{ view.subtitleInspectorSearch ? '没有匹配的字幕文件' : '字幕目录为空' }}
        </div>
        <div
          v-for="row in view.subtitleInspectorFlatTree"
          :key="row.id"
          class="fm-row"
          :class="{ 'fm-row-dir': row.type === 'dir', 'fm-row-selected': view.subtitleInspectorSelectedIds.has(row.id) }"
          @click="view.handleSubtitleInspectorRowClick(row, $event)"
        >
          <div class="fm-col-check" @click.stop>
            <input type="checkbox" class="fm-check" :checked="view.subtitleInspectorSelectedIds.has(row.id)" :disabled="view.subtitleInspectorBusy" @click.stop="view.toggleSubtitleInspectorSelect(row, $event)">
          </div>
          <div class="fm-col-name">
            <div class="fm-name-cell" :style="{ paddingLeft: `${row.depth * 18 + 4}px` }">
              <button
                v-if="row.type === 'dir'"
                type="button"
                class="fm-arrow-toggle"
                :class="{ open: view.subtitleInspectorExpandedIds.has(row.id) }"
                @click.stop="view.toggleSubtitleInspectorExpand(row)"
              >
                &gt;
              </button>
              <span v-else class="fm-arrow-placeholder"></span>
              <span class="fm-file-icon">
                <el-icon><component :is="view.resolveSubtitleTreeIcon(row)" /></el-icon>
              </span>
              <span class="fm-name-text">{{ row.name }}</span>
            </div>
          </div>
          <div class="fm-col-size">{{ view.formatFileSize(row.size) }}</div>
          <div class="fm-col-time">{{ view.formatDate(row.modified_time) }}</div>
          <div class="fm-col-action subtitle-tree-row-actions" @click.stop>
            <button v-if="row.type === 'file'" class="fm-link-edit" :disabled="view.subtitleInspectorBusy" @click="view.openSubtitleRenameDialog(row)">重命名</button>
            <button class="fm-link-danger" :disabled="view.subtitleInspectorBusy" @click="view.deleteSubtitleTreeEntry(row)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </component>
</template>

<script setup>
import { computed } from 'vue'
import AppEmptyState from '../common/AppEmptyState.vue'
import {
  Sparkles,
  RefreshCw,
  ChevronsDown,
  ChevronsUp,
  FolderOpen,
  Hash,
  Link,
  Link2,
  Music,
  FileText,
  Database,
  CircleX,
  Wand2,
  MousePointerClick,
  ListOrdered,
  CheckCircle2,
  RotateCcw,
  Trash2,
  ArrowRight
} from 'lucide-vue-next'

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  },
  stageMode: {
    type: String,
    default: 'all'
  },
  showDeletePrecheck: {
    type: Boolean,
    default: true
  },
  immersive: {
    type: Boolean,
    default: false
  }
})

const view = computed(() => props.ctx || {})
const showPairing = computed(() => ['all', 'pairing'].includes(props.stageMode))
const showTree = computed(() => ['all', 'tree'].includes(props.stageMode))

const pendingInProgressTask = computed(() => {
  const candidates = [view.value.activeSubtitleTask, view.value.subtitleBackgroundActiveTask]
  for (const task of candidates) {
    if (!task) continue
    if (['pending', 'processing'].includes(task.status)) return task
  }
  const tasks = Array.isArray(view.value.inspectableSubtitleTasks) ? view.value.inspectableSubtitleTasks : []
  return tasks.find(task => ['pending', 'processing'].includes(task?.status)) || null
})

const pendingLoadingText = computed(() => {
  const task = pendingInProgressTask.value
  if (!task) return '正在执行字幕任务...'
  const step = task.current_step || '正在执行字幕任务'
  const rjcode = task.actual_rjcode || task.rjcode || ''
  return rjcode ? `${rjcode} · ${step}` : step
})

function getDisplayFolderTitle() {
  const folderName = String(view.value.activeSubtitleInspectTask?.folder_name || '').trim()
  if (folderName && !/[\\/]/.test(folderName)) return folderName
  const folderPath = String(view.value.subtitleInspectorInfo?.folderPath || view.value.subtitleInspectorInfo?.subtitleDir || '').trim()
  return view.value.getFileName?.(folderPath) || folderName || ''
}

function stripTrailingAudioExtension(value = '') {
  let current = String(value || '')
  while (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(current)) {
    current = current.replace(/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i, '')
  }
  return current
}

function formatSubtitleName(name = '') {
  const raw = String(name || '')
  const extMatch = raw.match(/\.[^.]+$/)
  const subtitleExt = extMatch?.[0] || ''
  const baseName = subtitleExt ? raw.slice(0, -subtitleExt.length) : raw
  return `${stripTrailingAudioExtension(baseName)}${subtitleExt}`
}

function formatSubtitleItemName(item = {}) {
  return formatSubtitleName(item?.display_name || item?.name || '')
}
</script>

<style scoped>
.subtitle-tree-card {
  --apple-bg: #f5f5f7;
  --apple-surface: #ffffff;
  --apple-surface-soft: #fafafc;
  --apple-border: rgba(29, 29, 31, 0.08);
  --apple-border-strong: rgba(29, 29, 31, 0.14);
  --apple-text: #1d1d1f;
  --apple-text-soft: rgba(29, 29, 31, 0.72);
  --apple-text-faint: rgba(29, 29, 31, 0.48);
  --apple-blue: #475569;
  --apple-shadow: rgba(0, 0, 0, 0.12) 3px 5px 30px 0px;
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --audio-accent: #94a3b8;
  --subtitle-accent: #cbd5e1;
  --pair-accent: #64748b;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  background: linear-gradient(180deg, #fcfdff 0%, #f7f9fc 100%);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.04);
}
.subtitle-tree-card :deep(.el-card__header) {
  padding: 0;
  border-bottom: 1px solid rgba(29, 29, 31, 0.06);
}
.subtitle-tree-card :deep(.el-card__body) { display: flex; flex-direction: column; min-height: 0; }
/* --- Header ------------------------------------------------- */
.subtitle-section-header { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding: 16px 22px; }
.subtitle-section-heading { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.subtitle-section-heading-title { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.subtitle-section-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(241, 245, 249, 0.98), rgba(226, 232, 240, 0.94));
  color: #475569;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.8);
  transition: transform .3s var(--ease-spring), box-shadow .3s var(--ease-spring);
}
.subtitle-section-icon-match { background: linear-gradient(135deg, rgba(241, 245, 249, 0.98), rgba(226, 232, 240, 0.94)); color: #475569; }
.subtitle-section-heading:hover .subtitle-section-icon { transform: rotate(-4deg) scale(1.06); }
.subtitle-section-tip {
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 12px;
  color: var(--apple-text-soft);
  line-height: 1.55;
  letter-spacing: -0.12px;
}
.subtitle-tree-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
.subtitle-btn-tooltip-wrap { display: inline-flex; vertical-align: middle; }
.subtitle-tree-action-tip { font-size: 12px; color: var(--apple-text-faint); }

/* --- Chips --------------------------------------------------- */
.subtitle-mini-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: -0.12px;
  background: #f4f6f9;
  color: #59697f;
  border: 1px solid #e2e8f0;
  transition: transform .3s var(--ease-spring), box-shadow .3s var(--ease-spring);
}
.subtitle-mini-chip :deep(svg),
.subtitle-mini-chip svg { opacity: .85; }
.subtitle-mini-chip:hover { transform: translateY(-1px); box-shadow: 0 6px 14px rgba(31, 46, 67, 0.08); }
.subtitle-mini-chip-accent {
  background: linear-gradient(180deg, #ffffff 0%, #f3f6fb 100%);
  color: #334155;
  border-color: #d7e0ea;
}

/* --- Icon action buttons ------------------------------------ */
.workbench-icon-btn.el-button {
  width: 34px;
  height: 34px;
  border-radius: 12px !important;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: var(--apple-text-soft);
  transition: all .3s var(--ease-spring);
}
.workbench-icon-btn.el-button:hover:not(:disabled) {
  background: linear-gradient(180deg, #ffffff 0%, #edf2f7 100%) !important;
  border-color: #cbd5e1;
  color: #334155 !important;
  transform: translateY(-2px) scale(1.04);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}
.workbench-icon-btn.el-button:hover:not(:disabled) svg { transform: scale(1.15); }
.workbench-icon-btn.el-button:active:not(:disabled) { transform: scale(0.94); }
.workbench-icon-btn.el-button svg { transition: transform .3s var(--ease-spring); }

/* --- Pill action buttons ----------------------------------- */
.workbench-pill-btn.el-button {
  height: 32px;
  border-radius: 10px !important;
  border: 1px solid #d7e0ea !important;
  background: linear-gradient(180deg, #ffffff 0%, #f3f6fb 100%) !important;
  color: #475569 !important;
  font-weight: 600;
  padding: 0 14px !important;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all .3s var(--ease-spring) !important;
}
.workbench-pill-btn.el-button svg { transition: transform .3s var(--ease-spring); }
.workbench-pill-btn.el-button:hover:not(:disabled) {
  border-color: #c5d0dd !important;
  color: #24364f !important;
  background: linear-gradient(180deg, #ffffff 0%, #edf2f7 100%) !important;
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}
.workbench-pill-btn.el-button:hover:not(:disabled) svg { transform: scale(1.15) rotate(-2deg); }
.workbench-pill-btn.el-button:active:not(:disabled) { transform: scale(0.96); }
.workbench-pill-btn.workbench-pill-active.el-button {
  background: linear-gradient(180deg, #f8fbff 0%, #e9eff7 100%) !important;
  border-color: #cfd8e3 !important;
  color: #1f2d3d !important;
  box-shadow: 0 8px 16px rgba(15, 23, 42, 0.05);
}
.workbench-pill-btn.workbench-pill-danger.el-button { color: #c53030 !important; }
.workbench-pill-btn.workbench-pill-danger.el-button:hover:not(:disabled) {
  background: linear-gradient(180deg, #fff7f7, #ffffff) !important;
  border-color: rgba(215, 0, 21, 0.35) !important;
  color: #b92121 !important;
  box-shadow: 0 10px 22px rgba(215, 0, 21, 0.14);
}
.workbench-primary-btn.el-button {
  height: 34px;
  border-radius: 10px !important;
  padding: 0 16px !important;
  font-weight: 600;
  letter-spacing: -0.12px;
  background: linear-gradient(180deg, #ffffff 0%, #edf2f7 100%) !important;
  border: 1px solid #d7e0ea !important;
  color: #1f2d3d !important;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
  transition: all .3s var(--ease-spring) !important;
}
.workbench-primary-btn.el-button svg { transition: transform .3s var(--ease-spring); }
.workbench-primary-btn.el-button:hover:not(:disabled):not(.is-loading) {
  transform: translateY(-2px) scale(1.03);
  border-color: #c5d0dd !important;
  background: linear-gradient(180deg, #ffffff 0%, #e8edf4 100%) !important;
  box-shadow: 0 14px 24px rgba(15, 23, 42, 0.09);
}
.workbench-primary-btn.el-button:hover:not(:disabled):not(.is-loading) svg { transform: scale(1.2) rotate(-6deg); }
.workbench-primary-btn.el-button:active:not(:disabled):not(.is-loading) { transform: scale(0.96); }

/* --- Shell --------------------------------------------------- */
.subtitle-tree-shell { display: flex; flex-direction: column; gap: 12px; min-height: 820px; padding: 0; }
.subtitle-inspector-empty { display: grid; gap: 10px; padding: 28px 0 18px; }
.subtitle-inspector-empty--loading { min-height: 320px; padding: 40px 0; position: relative; }
.subtitle-empty-tip { text-align: center; font-size: 12px; color: var(--apple-text-faint); }

/* --- Task info banner --------------------------------------- */
.subtitle-tree-info {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 249, 252, 0.96));
  border: 1px solid #e2e8f0;
  box-shadow: none;
}
.subtitle-tree-info-top { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
.subtitle-tree-info-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.subtitle-tree-info-head { display: flex; gap: 12px; align-items: flex-start; min-width: 0; }
.subtitle-tree-info-icon {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(180deg, #f8fafc, #eef2f7);
  color: #64748b;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.8);
  transition: transform .3s var(--ease-spring);
}
.subtitle-tree-info:hover .subtitle-tree-info-icon { transform: rotate(-6deg) scale(1.05); }
.subtitle-tree-info-main { min-width: 0; display: grid; gap: 4px; }
.subtitle-tree-info-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.subtitle-tree-info-actions-bottom { justify-content: flex-end; margin-left: auto; }
.subtitle-tree-title {
  font-family: 'SF Pro Display', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 19px;
  font-weight: 700;
  color: var(--apple-text);
  line-height: 1.2;
  letter-spacing: -0.24px;
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.subtitle-tree-title-md { font-size: 15px; font-weight: 700; line-height: 1.3; }
.subtitle-tree-meta { display: flex; gap: 6px; flex-wrap: wrap; }

/* --- Match shell -------------------------------------------- */
.subtitle-match-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  padding: 8px 0 0;
  border-radius: 0;
  background: transparent;
  border: none;
  box-shadow: none;
}
.subtitle-pairing-log-shell {
  display: grid;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
  border: 1px solid #e2e8f0;
  box-shadow: none;
}
.subtitle-pairing-log-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.subtitle-match-header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; flex-wrap: wrap; }
.subtitle-match-header-title { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
.subtitle-sequence-hint {
  margin-top: 6px;
  padding: 10px 12px;
  display: inline-flex;
  gap: 8px;
  align-items: flex-start;
  border: 1px dashed rgba(148, 163, 184, 0.6);
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.92));
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}
.subtitle-sequence-hint svg { flex: 0 0 auto; margin-top: 2px; color: #64748b; }
.subtitle-match-done-alert { margin-top: -2px; }
.subtitle-match-done-alert :deep(.el-alert) { border-radius: 12px; }

.subtitle-match-layout { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, 1.4fr) minmax(0, 1.08fr); gap: 16px; align-items: stretch; }
.subtitle-match-panel, .subtitle-match-center {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: none;
  transition: border-color .3s var(--ease-spring), background .3s var(--ease-spring);
}
.subtitle-match-panel:hover,
.subtitle-match-center:hover { border-color: #cbd5e1; }
.subtitle-match-panel-audio,
.subtitle-match-panel-subtitle,
.subtitle-match-center { border-top: 1px solid #e2e8f0; }
.subtitle-match-center { background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%); }

.subtitle-match-panel-head { display: flex; justify-content: space-between; gap: 10px; align-items: center; flex-wrap: wrap; }
.subtitle-match-preview-head { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; align-items: start; }
.subtitle-match-panel-tools, .subtitle-match-preview-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.subtitle-match-preview-actions { width: 100%; justify-content: flex-start; align-items: center; gap: 6px; }
.subtitle-task-box-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: 'SF Pro Display', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 14px;
  font-weight: 700;
  color: var(--apple-text);
  line-height: 1.2;
  letter-spacing: -0.18px;
}
.subtitle-task-box-title-audio { color: #334155; }
.subtitle-task-box-title-audio svg { color: var(--audio-accent); }
.subtitle-task-box-title-subtitle { color: #334155; }
.subtitle-task-box-title-subtitle svg { color: var(--subtitle-accent); }
.subtitle-task-box-title-center { color: #334155; }
.subtitle-task-box-title-center svg { color: var(--pair-accent); }
.subtitle-box-meta { font-size: 11px; color: var(--apple-text-faint); font-weight: 600; }
.subtitle-match-filter-select { width: 108px; }
.subtitle-match-search { width: 100%; }
.subtitle-match-list, .subtitle-match-pair-list {
  display: grid;
  gap: 6px;
  min-height: 360px;
  max-height: 680px;
  overflow: auto;
  padding-right: 4px;
  align-content: start;
  grid-auto-rows: max-content;
}
.subtitle-match-list::-webkit-scrollbar,
.subtitle-match-pair-list::-webkit-scrollbar { width: 6px; }
.subtitle-match-list::-webkit-scrollbar-thumb,
.subtitle-match-pair-list::-webkit-scrollbar-thumb { background: #d8e2f0; border-radius: 999px; }

.subtitle-match-item, .subtitle-match-pair {
  width: 100%;
  text-align: left;
  border: 1px solid #dbe4ec;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  padding: 7px 9px;
  cursor: pointer;
  transition: all .3s var(--ease-spring);
  position: relative;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
}
.subtitle-match-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 999px;
  background: transparent;
  transition: background .3s var(--ease-spring);
}
.subtitle-match-panel-audio .subtitle-match-item.active::before { background: var(--audio-accent); }
.subtitle-match-panel-subtitle .subtitle-match-item.active::before { background: var(--subtitle-accent); }
.subtitle-match-item:hover, .subtitle-match-pair:hover {
  border-color: #cbd5e1;
  box-shadow: 0 12px 22px rgba(15, 23, 42, 0.05);
  transform: translateY(-2px) scale(1.02);
}
.subtitle-match-item:active, .subtitle-match-pair:active { transform: scale(0.98); }
.subtitle-match-item.active, .subtitle-match-pair.active {
  border-color: #b8c6d6;
  box-shadow: 0 0 0 2px rgba(203, 213, 225, 0.8);
  background: linear-gradient(180deg, #ffffff 0%, #f5f7fa 100%);
}
.subtitle-match-item.paired { border-color: #bfe3ca; background: linear-gradient(180deg, #f5fcf7 0%, #ffffff 100%); }
.subtitle-match-item.suspicious,
.subtitle-match-pair.suspicious { border-color: #f2cb90; background: linear-gradient(180deg, #fffaf1 0%, #ffffff 100%); }
.subtitle-match-item.queued { border-color: #c5d0dd; background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%); box-shadow: inset 0 0 0 1px rgba(203, 213, 225, 0.6); }
.subtitle-match-name {
  display: flex;
  gap: 5px;
  align-items: center;
  flex-wrap: wrap;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 11px;
  font-weight: 600;
  color: #1f2f46;
  letter-spacing: -0.18px;
  line-height: 1.28;
}
.subtitle-match-meta {
  margin-top: 2px;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 9px;
  line-height: 1.3;
  color: #7b8797;
  word-break: break-all;
  letter-spacing: -0.12px;
}
.subtitle-match-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 6px;
  padding: 2px 7px;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid transparent;
  line-height: 1.3;
}
.badge-paired { background: #e9f7ef; color: #2f9158; border-color: #bfe3ca; }
.badge-low { background: #fff4de; color: #b97714; border-color: #f4d58d; }
.badge-seq { background: #eef2f7; color: #475569; border-color: #d7e0ea; }
.subtitle-match-empty {
  min-height: 220px;
  border: 1px dashed #d5dfed;
  border-radius: 14px;
  display: grid;
  place-items: center;
  gap: 6px;
  padding: 18px 16px;
  text-align: center;
  color: #6f8198;
  line-height: 1.55;
  background: linear-gradient(180deg, #fbfcfe 0%, #ffffff 100%);
}
.subtitle-card-tip { font-size: 12px; color: #8394aa; }

/* --- Pair card internal: confidence head + source->target flow --- */
.subtitle-match-pair-head { display: flex; justify-content: space-between; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.subtitle-match-pair-head-left { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.subtitle-match-pair-confidence,
.subtitle-match-pair-track {
  font-size: 10px;
  font-weight: 700;
  border-radius: 6px;
  padding: 2px 7px;
  border: 1px solid transparent;
  line-height: 1.35;
}
.confidence-high { background: #e8f7ed; color: #2f8f57; border-color: #bfe3ca; }
.confidence-medium { background: #eef2f7; color: #475569; border-color: #d7e0ea; }
.confidence-low { background: #fff4de; color: #b97714; border-color: #f4d58d; }
.subtitle-match-pair-track { color: #475569; background: #eef2f7; border-color: #d7e0ea; }
.subtitle-match-pair-reason { font-size: 10px; color: var(--apple-text-faint); letter-spacing: -0.12px; }

.subtitle-match-pair-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr);
  gap: 6px;
  align-items: center;
  padding: 6px 8px;
  border-radius: 12px;
  background: linear-gradient(180deg, #fbfcfe 0%, #f4f7fb 100%);
  border: 1px solid #e2e8f0;
}
.subtitle-match-flow-side { display: grid; gap: 3px; min-width: 0; }
.subtitle-match-flow-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #8a97aa;
}
.subtitle-match-flow-source .subtitle-match-flow-label { color: #8a97aa; }
.subtitle-match-flow-target .subtitle-match-flow-label { color: #64748b; }
.subtitle-match-flow-line {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  line-height: 1.2;
  color: #2c3e5c;
  min-width: 0;
}
.subtitle-match-flow-target .subtitle-match-flow-line { color: #334155; font-weight: 600; }
.subtitle-match-flow-icon { flex: 0 0 auto; }
.subtitle-match-flow-icon-audio { color: var(--audio-accent); }
.subtitle-match-flow-icon-subtitle { color: var(--subtitle-accent); }
.subtitle-match-flow-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.subtitle-match-flow-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  color: #64748b;
  background: #eef2f7;
  justify-self: center;
  align-self: center;
}
.subtitle-match-pair:hover .subtitle-match-flow-arrow { animation: subtitle-arrow-nudge 0.9s var(--ease-spring) infinite alternate; }
@keyframes subtitle-arrow-nudge { from { transform: translateX(0); } to { transform: translateX(3px); } }
.subtitle-match-row-actions { margin-top: 4px; display: flex; justify-content: flex-end; }

/* --- Tree (bottom file list) --------------------------------- */
.subtitle-tree-toolbar { display: flex; justify-content: flex-end; }
.subtitle-tree-selection-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid #f2d6d2;
  border-radius: 12px;
  background: linear-gradient(180deg, #fff8f7 0%, #ffffff 100%);
  box-shadow: 0 6px 16px rgba(212, 76, 70, 0.08);
}
.subtitle-tree-selection-count { font-size: 13px; font-weight: 700; color: #a24a43; }
.subtitle-tree-selection-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.subtitle-tree-selection-tip { font-size: 11px; color: #8a97aa; }
.subtitle-tree-head { margin-top: 2px; border-radius: 12px 12px 0 0; overflow: hidden; }
.subtitle-tree-scroll {
  min-height: 260px;
  max-height: 520px;
  overflow: auto;
  border: 1px solid #e9eef5;
  border-radius: 0 0 12px 12px;
  background: #ffffff;
}
.subtitle-tree-row-actions { display: flex; gap: 6px; }
.fm-head, .fm-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 110px 170px 130px; align-items: center; }
.fm-head {
  min-height: 38px;
  padding: 0 14px;
  border-bottom: 1px solid #e8edf5;
  background: linear-gradient(180deg, #f8fafc 0%, #f2f5f9 100%);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #5f7188;
}
.fm-row {
  min-height: 38px;
  padding: 0 14px;
  border-bottom: 1px solid #edf1f6;
  font-size: 13px;
  color: var(--apple-text);
  transition: background .2s ease;
}
.fm-row:hover { background: #f7fbff; }
.fm-row:last-child { border-bottom: none; }
.fm-row-dir { background: #fafbfd; }
.fm-row-selected { background: linear-gradient(90deg, rgba(226, 232, 240, 0.72), rgba(248, 250, 252, 0.96)) !important; box-shadow: inset 3px 0 0 #94a3b8; }
.fm-empty { display: flex; align-items: center; justify-content: center; min-height: 180px; color: #a2b0c2; font-size: 13px; }
.fm-col-name, .fm-col-size, .fm-col-time, .fm-col-action { min-width: 0; }
.fm-col-size, .fm-col-time { font-variant-numeric: tabular-nums; color: var(--apple-text-soft); font-size: 12px; }
.fm-name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.fm-arrow-toggle { width: 18px; height: 18px; border: none; background: transparent; color: #8ea0b8; cursor: pointer; padding: 0; font-weight: 700; transition: transform .3s var(--ease-spring), color .2s ease; }
.fm-arrow-toggle.open { transform: rotate(90deg); color: #64748b; }
.fm-arrow-placeholder { width: 18px; flex: 0 0 18px; }
.fm-file-icon { width: 20px; display: inline-flex; justify-content: center; color: #64748b; transition: transform .3s var(--ease-spring); }
.fm-row:hover .fm-file-icon { transform: scale(1.15); }
.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-link-edit, .fm-link-danger {
  border: 1px solid #d7dfec;
  background: #fff;
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  transition: all .3s var(--ease-spring);
}
.fm-link-edit { color: #475569; }
.fm-link-danger { color: #d84b46; border-color: #efc1be; background: #fff7f7; }
.fm-link-edit:hover {
  color: #1f2937;
  border-color: #cbd5e1;
  background: #f8fafc;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08);
  transform: translateY(-2px) scale(1.04);
}
.fm-link-danger:hover {
  color: #c40017;
  border-color: #f3a8a8;
  background: #fff0f0;
  box-shadow: 0 6px 14px rgba(215, 0, 21, 0.14);
  transform: translateY(-2px) scale(1.04);
}
.fm-link-edit:active, .fm-link-danger:active { transform: scale(0.95); }
.fm-check { width: 14px; height: 14px; accent-color: #64748b; cursor: pointer; }
.fm-search-input {
  width: 260px;
  height: 34px;
  padding: 0 14px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  outline: none;
  background: #ffffff;
  font-size: 13px;
  color: var(--apple-text);
  transition: border-color .2s ease, box-shadow .2s ease;
}
.fm-search-input:focus {
  border-color: rgba(148, 163, 184, 0.72);
  box-shadow: 0 0 0 3px rgba(226, 232, 240, 0.9);
}
.fm-search-input:disabled { background: #f5f6f8; color: var(--apple-text-faint); }
.subtitle-tree-card :deep(.el-button) {
  border-radius: 999px;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-weight: 500;
  letter-spacing: -0.224px;
}
.subtitle-tree-card :deep(.el-button--default) {
  background: var(--apple-surface-soft);
  color: var(--apple-text);
  border-color: rgba(29, 29, 31, 0.08);
}
.subtitle-tree-card :deep(.el-button--default:hover) {
  border-color: #cbd5e1;
  background: #edf2f7;
  color: #334155;
}
.subtitle-tree-card :deep(.el-button--primary) {
  background: linear-gradient(180deg, #ffffff 0%, #edf2f7 100%);
  border-color: #d7e0ea;
  color: #1f2d3d;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    transform 0.2s ease,
    box-shadow 0.2s ease;
}
.subtitle-tree-card :deep(.el-button--primary:hover:not(:disabled):not(.is-loading)) {
  background: linear-gradient(180deg, #ffffff 0%, #e8edf4 100%) !important;
  border-color: #c5d0dd !important;
  color: #24364f !important;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
}
.subtitle-tree-card :deep(.el-button--primary:active:not(:disabled):not(.is-loading)) {
  transform: translateY(0);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.12);
}
/* 禁用态与旁侧 text 按钮一致：灰字、无蓝底（不可点一目了然） */
.subtitle-tree-card :deep(.el-button--primary.is-disabled),
.subtitle-tree-card :deep(.el-button--primary.is-disabled:hover),
.subtitle-tree-card :deep(.el-button--primary:disabled) {
  opacity: 1 !important;
  background: transparent !important;
  border-color: transparent !important;
  color: var(--apple-text-faint) !important;
  box-shadow: none !important;
  transform: none !important;
  filter: none !important;
}
.subtitle-tree-card :deep(.el-button--danger),
.subtitle-tree-card :deep(.el-button--danger.is-plain) {
  border-color: rgba(215, 0, 21, 0.18);
  background: #fff5f5;
  color: #d70015;
}
.subtitle-tree-card :deep(.el-button--danger:hover),
.subtitle-tree-card :deep(.el-button--danger.is-plain:hover) {
  border-color: rgba(215, 0, 21, 0.28);
  background: #fff0f0;
  color: #c40017;
}
.subtitle-tree-card :deep(.el-select__wrapper) {
  min-height: 34px;
  border-radius: 12px;
  background: var(--apple-surface-soft);
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
}
.subtitle-tree-card :deep(.el-button:focus-visible),
.subtitle-tree-card :deep(.el-select__wrapper.is-focused),
.fm-search-input:focus-visible,
.fm-link-edit:focus-visible,
.fm-link-danger:focus-visible,
.subtitle-match-item:focus-visible,
.subtitle-match-pair:focus-visible,
.fm-arrow-toggle:focus-visible {
  outline: 2px solid #94a3b8;
  outline-offset: 2px;
}
@media (max-width: 1200px) {
  .subtitle-match-layout { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .subtitle-section-header,
  .subtitle-match-header,
  .subtitle-tree-selection-bar { flex-direction: column; align-items: flex-start; }
  .subtitle-match-preview-grid { grid-template-columns: 1fr; }
}
</style>

<style>
/* Tooltip 挂载到 body，需非 scoped；浅灰底替代默认深色气泡 */
.subtitle-inspector-tooltip.el-popper {
  background: #e8e8ec !important;
  border: 1px solid rgba(29, 29, 31, 0.1) !important;
  color: #1d1d1f !important;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08) !important;
  padding: 8px 12px !important;
  font-size: 13px !important;
  line-height: 1.45 !important;
  max-width: min(320px, calc(100vw - 24px));
}
.subtitle-inspector-tooltip.el-popper .el-popper__arrow::before {
  background: #e8e8ec !important;
  border: 1px solid rgba(29, 29, 31, 0.1) !important;
}
</style>
