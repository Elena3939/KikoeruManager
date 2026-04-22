<template>
  <component
    :is="immersive ? 'div' : 'el-card'"
    :shadow="immersive ? undefined : 'never'"
    :class="immersive ? 'subtitle-task-card subtitle-task-card-immersive' : 'subtitle-task-card'"
  >
    <template v-if="!immersive" #header>
      <div class="subtitle-section-header">
        <div>
          <div>最近字幕任务</div>
          <div class="subtitle-section-tip">上面展示当前选中任务的详情，下面保留完整任务队列。运行中任务也会留在队列里，当前查看项会高亮。</div>
        </div>
        <div class="subtitle-task-toolbar">
          <span class="subtitle-mini-chip">总任务 {{ ctx.subtitleQueueTasks.length }}</span>
          <span class="subtitle-mini-chip">可清理 {{ ctx.subtitleClearableTaskCounts.finished }}</span>
          <el-dropdown
            trigger="click"
            :disabled="!ctx.subtitleClearableTaskCounts.finished || Boolean(ctx.subtitleBulkClearingScope)"
            @command="ctx.clearSubtitleTasksByScope"
          >
            <el-button size="small" plain :loading="Boolean(ctx.subtitleBulkClearingScope)">
              一键清空任务
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="completed" :disabled="!ctx.subtitleClearableTaskCounts.completed">清空成功 {{ ctx.subtitleClearableTaskCounts.completed }}</el-dropdown-item>
                <el-dropdown-item command="failed" :disabled="!ctx.subtitleClearableTaskCounts.failed">清空失败 {{ ctx.subtitleClearableTaskCounts.failed }}</el-dropdown-item>
                <el-dropdown-item command="finished" :disabled="!ctx.subtitleClearableTaskCounts.finished">清空全部已结束 {{ ctx.subtitleClearableTaskCounts.finished }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </template>

    <AppEmptyState v-if="showOverview && !ctx.visibleSubtitleTasks.length" description="暂无字幕任务" size="sm" />
    <div v-else class="subtitle-task-list">
      <div
        v-if="showOverview && ctx.activeSubtitleTask"
        :key="ctx.activeSubtitleTask.id"
        class="subtitle-task-log-only"
      >
        <div class="subtitle-task-log-headline">
          <div class="subtitle-task-log-title-wrap">
            <div class="subtitle-task-log-title">当前任务执行日志</div>
            <div class="subtitle-task-log-subtitle">{{ ctx.getTaskDisplayRJCode(ctx.activeSubtitleTask) }}</div>
          </div>
          <span class="subtitle-task-log-state">{{ ctx.getRJSubtitleTaskStatusLabel(ctx.activeSubtitleTask) }}</span>
        </div>
        <div class="subtitle-task-log-panel">
          <div class="subtitle-collapse-title subtitle-task-log-head">
            <span>执行日志</span>
            <span class="subtitle-box-meta">{{ ctx.activeSubtitleTask.progress_log?.length || 0 }} 条</span>
          </div>
          <div v-if="ctx.activeSubtitleTaskProgressLogs.length" class="subtitle-task-box subtitle-task-box-log">
            <div class="subtitle-log-list">
              <div v-for="(entry, idx) in ctx.activeSubtitleTaskProgressLogs" :key="`${ctx.activeSubtitleTask.id}-progress-log-${idx}`" class="subtitle-log-row">
                <span class="subtitle-log-time">{{ ctx.formatProgressLogTime(entry.time) }}</span>
                <span class="subtitle-log-level" :class="`level-${entry.level || 'info'}`">{{ ctx.getProgressLogLevelLabel(entry.level) }}</span>
                <span class="subtitle-inline-primary">{{ entry.message }}</span>
              </div>
            </div>
          </div>
          <div v-else class="subtitle-task-box subtitle-task-box-log subtitle-task-log-empty">
            当前任务还没有日志
          </div>
        </div>
      </div>

      <div v-if="showQueue && !immersive" class="subtitle-task-queue-head">
        <div>
          <div class="subtitle-task-box-title">任务队列</div>
          <div class="subtitle-card-tip">包含正在处理中的任务和历史任务，当前查看项会高亮。</div>
        </div>
        <div class="subtitle-task-queue-filters">
          <button
            v-for="item in ctx.subtitleTaskManualOverview"
            :key="`manual-${item.key}`"
            type="button"
            class="subtitle-mini-chip subtitle-chip-button"
            :class="{ active: ctx.subtitleTaskManualFilter === item.key }"
            @click="ctx.setSubtitleTaskManualFilter(item.key)"
          >
            {{ item.label }} {{ item.value }}
          </button>
        </div>
      </div>

      <div v-if="showQueue && ctx.subtitleQueueTasks.length" class="subtitle-task-rail subtitle-task-queue-rail" :class="{ 'subtitle-task-queue-rail-immersive': immersive }">
        <button
          v-for="task in ctx.subtitleQueueTasks"
          :key="`queue-${task.id}`"
          type="button"
          class="subtitle-task-compact"
          :class="{ active: ctx.isSubtitleTaskSelected(task), processing: task.status === 'processing', finished: task.manual_match_completed }"
          @click="ctx.selectSubtitleTask(task)"
        >
          <div class="subtitle-task-compact-head">
            <span class="subtitle-task-compact-rj">{{ ctx.getTaskDisplayRJCode(task) }}</span>
            <span class="subtitle-task-compact-status" :class="`status-${ctx.getRJSubtitleTaskStatusClass(task)}`">{{ ctx.getRJSubtitleTaskStatusLabel(task) }}</span>
          </div>
          <div class="subtitle-task-compact-folder">{{ task.folder_name || ctx.getFileName(task.folder_path) }}</div>
          <div v-if="ctx.getTaskSourceRJCode(task)" class="subtitle-task-compact-source">来源 {{ ctx.getTaskSourceRJCode(task) }}</div>
          <div class="subtitle-task-compact-step">{{ task.current_step || task.error_message || '等待中' }}</div>
          <div class="subtitle-task-compact-meta">
            <template v-if="ctx.isHistoryRestoredSubtitleTask(task)">
              <span>历史记录恢复</span>
              <span v-if="task.manual_match_completed" class="subtitle-task-meta-chip is-success">已匹配完成 {{ task.manual_match_applied_pairs || 0 }}</span>
              <span v-else-if="task.awaiting_manual_match">待手动配对</span>
              <span v-if="task.subtitle_dir">可打开字幕树</span>
            </template>
            <template v-else>
              <span>下载 {{ task.downloaded_count || ctx.getSubtitleDownloadFiles(task).length }}</span>
              <span>匹配组 {{ task.match_result?.matched_group_count || 0 }}</span>
              <span>写入 {{ task.written_files?.length || 0 }}</span>
              <span v-if="task.manual_match_completed" class="subtitle-task-meta-chip is-success">已匹配完成 {{ task.manual_match_applied_pairs || 0 }}</span>
              <span v-else>未匹配 {{ task.match_result?.unmatched_audio?.length || 0 }}</span>
            </template>
          </div>
          <div class="subtitle-task-compact-actions">
            <el-button size="small" text :disabled="!task.subtitle_dir" @click.stop="ctx.inspectSubtitleTask(task)">{{ ctx.getSubtitleTaskInspectLabel(task) }}</el-button>
          </div>
        </button>
      </div>
    </div>
  </component>
</template>

<script setup>
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import AppEmptyState from '../../common/AppEmptyState.vue'

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  },
  mode: {
    type: String,
    default: 'full'
  },
  immersive: {
    type: Boolean,
    default: false
  }
})

const showOverview = computed(() => ['full', 'overview'].includes(props.mode))
const showQueue = computed(() => ['full', 'queue'].includes(props.mode))
</script>

<style scoped>
.subtitle-task-card {
  --panel-border: #dbe5ef;
  --panel-surface: linear-gradient(180deg, #ffffff 0%, #f7fafc 100%);
  --panel-shadow: 0 16px 28px rgba(15, 23, 42, 0.06);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  display: grid;
  gap: 12px;
  min-width: 0;
}

.subtitle-task-card :deep(.el-card__header) {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.24);
}

.subtitle-task-card :deep(.el-card__body) {
  display: grid;
  gap: 12px;
  padding: 0;
}

.subtitle-section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.subtitle-section-tip,
.subtitle-card-tip {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.55;
  color: #64748b;
}

.subtitle-task-toolbar,
.subtitle-task-meta,
.subtitle-task-inline-meta,
.subtitle-task-queue-filters,
.subtitle-box-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.subtitle-mini-chip,
.subtitle-inline-chip,
.subtitle-task-meta-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 6px 11px;
  border: 1px solid #dbe4ee;
  border-radius: 999px;
  background: linear-gradient(180deg, #ffffff 0%, #f6f9fc 100%);
  color: #526277;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: -0.01em;
  box-shadow: 0 8px 14px rgba(15, 23, 42, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.75);
  transition: all 0.3s var(--ease-spring);
}

.subtitle-inline-chip,
.subtitle-task-meta-chip {
  color: #315f9f;
  border-color: #c8daf7;
  background: linear-gradient(180deg, #f6faff 0%, #edf4ff 100%);
}

.subtitle-task-meta-chip.is-success,
.subtitle-inline-chip.is-success {
  color: #257548;
  border-color: #bfe2cb;
  background: linear-gradient(180deg, #f4fcf7 0%, #ebf8ef 100%);
}

.subtitle-mini-chip:hover,
.subtitle-inline-chip:hover,
.subtitle-task-meta-chip:hover {
  transform: translateY(-2px) scale(1.02);
}

.subtitle-mini-chip:active,
.subtitle-inline-chip:active,
.subtitle-task-meta-chip:active {
  transform: scale(0.96);
}

.subtitle-task-list {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.subtitle-task-detail {
  border: 1px solid var(--panel-border);
  border-radius: 16px;
  background:
    radial-gradient(circle at top right, rgba(133, 175, 232, 0.12), transparent 30%),
    linear-gradient(180deg, #ffffff 0%, #f7fafc 100%);
  padding: 16px 18px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.subtitle-task-detail.active {
  border-color: #6fa2df;
  background:
    radial-gradient(circle at top right, rgba(110, 168, 255, 0.2), transparent 32%),
    linear-gradient(180deg, #f7fbff 0%, #eef5ff 100%);
  box-shadow:
    0 0 0 2px rgba(103, 160, 241, 0.88),
    0 0 0 5px rgba(166, 204, 255, 0.26),
    var(--panel-shadow);
}

.subtitle-task-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px 18px;
  align-items: start;
}

.subtitle-task-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.subtitle-task-side {
  min-width: 0;
  display: grid;
  gap: 10px;
  justify-items: end;
}

.subtitle-task-meta-top {
  justify-content: flex-end;
  gap: 6px;
}

.subtitle-task-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  max-width: 620px;
}

.subtitle-task-rj {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: #16325c;
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.8);
}

.subtitle-task-folder {
  margin-top: 4px;
  color: #30445f;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.55;
  word-break: break-word;
}

.subtitle-task-source,
.subtitle-task-lang {
  font-size: 12px;
  color: #6a7d97;
}

.subtitle-task-step {
  font-size: 13px;
  color: #4f6481;
  line-height: 1.6;
}

.subtitle-task-error {
  padding: 10px 12px;
  border: 1px solid #f3c5c2;
  border-radius: 12px;
  background: #fff4f3;
  color: #b5332d;
  font-size: 13px;
}

.subtitle-task-finish-alert {
  margin-top: 2px;
}

.subtitle-task-detail-collapse {
  margin-top: 4px;
  border-top: none;
}

.subtitle-task-detail :deep(.el-tag) {
  border-radius: 999px;
  font-weight: 700;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.subtitle-task-detail-collapse :deep(.el-collapse-item__header) {
  background: transparent;
  border-bottom: 1px solid #e5edf6;
  color: #334155;
  font-weight: 700;
  padding: 2px 0;
}

.subtitle-task-detail-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: none;
  background: transparent;
}

.subtitle-task-detail-collapse :deep(.el-collapse-item__content) {
  padding: 10px 0 4px;
}

.subtitle-collapse-title,
.subtitle-box-head,
.subtitle-task-compact-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.subtitle-task-box {
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid #e2eaf3;
  background: #ffffff;
}

.subtitle-inline-row,
.subtitle-log-row {
  display: grid;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
}

.subtitle-inline-row {
  grid-template-columns: 120px 80px minmax(0, 1fr);
}

.subtitle-inline-primary {
  color: #334155;
  font-weight: 700;
  word-break: break-word;
}

.subtitle-log-list,
.subtitle-download-list,
.subtitle-issue-list,
.subtitle-written-list,
.subtitle-task-rail {
  display: grid;
  gap: 8px;
}

.subtitle-task-rail {
  grid-auto-flow: column;
  grid-auto-columns: minmax(236px, 280px);
  overflow-x: auto;
  padding: 6px 8px 10px;
  margin: -6px -8px -2px;
}

.subtitle-task-rail::-webkit-scrollbar {
  height: 8px;
}

.subtitle-task-rail::-webkit-scrollbar-thumb {
  background: #d6e1ec;
  border-radius: 999px;
}

.subtitle-task-compact {
  width: 100%;
  text-align: left;
  border: 1px solid #dbe5ef;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbfe 100%);
  padding: 12px;
  cursor: pointer;
  transition: all 0.3s var(--ease-spring);
}

.subtitle-task-compact:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: #c3d4e5;
  box-shadow: 0 14px 22px rgba(15, 23, 42, 0.08);
}

.subtitle-task-compact:active {
  transform: scale(0.96);
}

.subtitle-task-compact.active {
  border-color: #6fa2df;
  background:
    radial-gradient(circle at top right, rgba(110, 168, 255, 0.2), transparent 38%),
    linear-gradient(180deg, #f6faff 0%, #edf5ff 100%);
  box-shadow:
    0 0 0 2px rgba(103, 160, 241, 0.88),
    0 0 0 5px rgba(166, 204, 255, 0.28),
    0 14px 24px rgba(49, 96, 168, 0.14);
}

.subtitle-task-compact.processing {
  background: linear-gradient(180deg, #fffdf6 0%, #ffffff 100%);
}

.subtitle-task-compact.finished {
  background: linear-gradient(180deg, #f4fbf6 0%, #ffffff 100%);
}

.subtitle-task-compact-rj {
  font-size: 18px;
  font-weight: 800;
  color: #0f172a;
}

.subtitle-task-compact-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 26px;
  padding: 5px 11px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid transparent;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
  transition: all 0.3s var(--ease-spring);
}

.subtitle-task-compact-status.status-pending,
.subtitle-task-compact-status.status-cancelled {
  background: #f2f6fb;
  border-color: #d8e1ec;
  color: #475569;
}

.subtitle-task-compact-status.status-processing,
.subtitle-task-compact-status.status-awaiting_manual_match {
  background: #fff7ed;
  border-color: #f2d4ad;
  color: #c2410c;
}

.subtitle-task-compact-status.status-completed,
.subtitle-task-compact-status.status-manual_match_completed {
  background: #ecfdf3;
  border-color: #bfe3ca;
  color: #15803d;
}

.subtitle-task-compact-status.status-failed {
  background: #fef2f2;
  border-color: #f4c6c6;
  color: #dc2626;
}

.subtitle-task-compact-folder,
.subtitle-task-compact-step,
.subtitle-task-compact-source {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: #475569;
  word-break: break-word;
}

.subtitle-task-compact-meta {
  margin-top: 8px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
  font-size: 12px;
  color: #64748b;
}

.subtitle-task-compact-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}

.subtitle-chip-button {
  cursor: pointer;
  transition: all 0.3s var(--ease-spring);
}

.subtitle-chip-button:hover {
  transform: translateY(-2px) scale(1.02);
}

.subtitle-chip-button.active {
  border-color: #bfcfe0;
  background: linear-gradient(180deg, #eef5fd 0%, #e4eef8 100%);
  color: #1e3a56;
}

.subtitle-task-card :deep(.el-progress-bar__outer) {
  background: #e9f0f7;
}

.subtitle-task-card :deep(.el-button) {
  border-radius: 10px;
}

.subtitle-task-actions :deep(.el-button) {
  min-height: 34px;
  padding-inline: 12px;
  border-radius: 10px;
  border-color: #d6e2ef;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbfe 100%);
  color: #475569;
  font-weight: 700;
  transition: all 0.3s var(--ease-spring);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.subtitle-task-actions :deep(.el-button--danger.is-plain) {
  border-color: #f2c4bf;
  background: linear-gradient(180deg, #fff8f7 0%, #ffefed 100%);
  color: #d14b42;
}

.subtitle-task-actions :deep(.el-button--warning.is-plain) {
  border-color: #f3d5a9;
  background: linear-gradient(180deg, #fffaf1 0%, #fff1dc 100%);
  color: #c87911;
}

.subtitle-task-actions :deep(.el-button:not(.el-button--danger):not(.el-button--warning).is-plain) {
  border-color: #cadbf4;
  background: linear-gradient(180deg, #f7faff 0%, #edf4ff 100%);
  color: #2f5f9f;
}

.subtitle-task-actions :deep(.el-button:not(.is-disabled):not(:disabled):not(.is-loading):hover) {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 12px 22px rgba(15, 23, 42, 0.08);
}

.subtitle-task-actions :deep(.el-button:not(.is-disabled):not(:disabled):not(.is-loading):active) {
  transform: scale(0.96);
}

.subtitle-inline-chip.is-info {
  color: #24558f;
  border-color: #c7daf5;
  background: linear-gradient(180deg, #f5f9ff 0%, #eaf2ff 100%);
}

.subtitle-inline-chip.is-warning {
  color: #b96a12;
  border-color: #f3d6a8;
  background: linear-gradient(180deg, #fffaf0 0%, #fff3df 100%);
}

.subtitle-inline-chip.is-success {
  color: #23724a;
  border-color: #c4e3ce;
  background: linear-gradient(180deg, #f4fcf7 0%, #eaf8ef 100%);
}

@media (max-width: 1280px) {
  .subtitle-task-head {
    grid-template-columns: minmax(0, 1fr);
  }

  .subtitle-task-side {
    justify-items: start;
  }

  .subtitle-task-meta-top,
  .subtitle-task-actions {
    justify-content: flex-start;
  }

  .subtitle-task-compact-meta {
    grid-template-columns: 1fr;
  }
}
</style>
