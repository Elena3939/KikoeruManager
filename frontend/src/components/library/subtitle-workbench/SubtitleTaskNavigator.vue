<template>
  <div class="subtitle-task-navigator">
    <div class="subtitle-task-navigator-head">
      <div>
        <div class="subtitle-task-navigator-title">执行队列</div>
        <div class="subtitle-task-navigator-tip">活跃任务会自动置顶，点击任意卡片可直达中央工位。</div>
      </div>
      <el-dropdown
        trigger="click"
        @command="ctx.clearSubtitleTasksByScope"
      >
        <el-button size="small" plain :loading="Boolean(ctx.subtitleBulkClearingScope)" class="subtitle-bulk-clear-btn">
          批量清理
          <el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="completed" :disabled="!ctx.subtitleClearableTaskCounts.completed">清理成功 {{ ctx.subtitleClearableTaskCounts.completed }}</el-dropdown-item>
            <el-dropdown-item command="failed" :disabled="!ctx.subtitleClearableTaskCounts.failed">清理失败 {{ ctx.subtitleClearableTaskCounts.failed }}</el-dropdown-item>
            <el-dropdown-item command="finished" :disabled="!ctx.subtitleClearableTaskCounts.finished">清理全部已结束 {{ ctx.subtitleClearableTaskCounts.finished }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div class="subtitle-task-navigator-filters">
      <button
        v-for="item in ctx.subtitleTaskManualOverview"
        :key="item.key"
        type="button"
        class="subtitle-task-filter-pill"
        :class="{ active: ctx.subtitleTaskManualFilter === item.key }"
        @click="ctx.setSubtitleTaskManualFilter(item.key)"
      >
        <span class="pill-count">{{ item.value }}</span>
        <span class="pill-label">{{ item.label }}</span>
      </button>
    </div>

    <AppEmptyState v-if="!ctx.subtitleQueueTasks.length" description="暂无字幕任务" size="sm" />
    <div v-else class="subtitle-task-navigator-list">
      <button
        v-for="task in pagedTasks"
        :key="task.id"
        type="button"
        class="subtitle-task-nav-card"
        :class="{ active: ctx.isSubtitleTaskSelected(task), processing: task.status === 'processing', finished: task.manual_match_completed }"
        @click="ctx.selectSubtitleTask(task)"
      >
        <div class="subtitle-task-nav-card-head">
          <span class="subtitle-task-nav-rj">{{ ctx.getTaskDisplayRJCode(task) }}</span>
          <transition name="subtitle-status-flip" mode="out-in">
            <span
              :key="`${task.id}-${ctx.getRJSubtitleTaskStatusClass(task)}`"
              class="subtitle-task-nav-status"
              :class="`status-${ctx.getRJSubtitleTaskStatusClass(task)}`"
            >
              {{ ctx.getRJSubtitleTaskStatusLabel(task) }}
            </span>
          </transition>
        </div>
        <div class="subtitle-task-nav-folder">{{ task.folder_name || ctx.getFileName(task.folder_path) }}</div>
        <div class="subtitle-task-nav-step">{{ task.current_step || task.error_message || '等待中' }}</div>
        <div class="subtitle-task-nav-meta">
          <span>下载 {{ task.downloaded_count || ctx.getSubtitleDownloadFiles(task).length }}</span>
          <span>写入 {{ task.written_files?.length || 0 }}</span>
          <span v-if="task.manual_match_completed" class="is-success">已匹配 {{ task.manual_match_applied_pairs || 0 }}</span>
          <span v-else-if="task.awaiting_manual_match" class="is-warning">待手动配对</span>
        </div>
      </button>
    </div>

    <div v-if="totalPages > 1" class="subtitle-task-navigator-pager">
      <el-button size="small" plain :disabled="currentPage <= 1" @click="currentPage -= 1">上一页</el-button>
      <span class="subtitle-task-navigator-page-text">{{ currentPage }} / {{ totalPages }}</span>
      <el-button size="small" plain :disabled="currentPage >= totalPages" @click="currentPage += 1">下一页</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import AppEmptyState from '../../common/AppEmptyState.vue'

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  }
})

const PAGE_SIZE = 6
const currentPage = ref(1)

const totalPages = computed(() => Math.max(1, Math.ceil((props.ctx?.subtitleQueueTasks?.length || 0) / PAGE_SIZE)))
const pagedTasks = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return (props.ctx?.subtitleQueueTasks || []).slice(start, start + PAGE_SIZE)
})

watch(() => props.ctx?.subtitleTaskManualFilter, () => {
  currentPage.value = 1
})

watch(() => props.ctx?.subtitleQueueTasks?.length, () => {
  if (currentPage.value > totalPages.value) currentPage.value = totalPages.value
})
</script>

<style scoped>
.subtitle-task-navigator {
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  display: grid;
  gap: 14px;
  height: 100%;
}

.subtitle-task-navigator-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.subtitle-task-navigator-title {
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.02em;
}

.subtitle-task-navigator-tip {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.6;
  color: #64748b;
  max-width: 22ch;
}

.subtitle-task-navigator-filters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.subtitle-task-filter-pill {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 72px;
  padding: 12px 14px;
  border: 1px solid #dbe4ee;
  border-radius: 18px;
  background:
    radial-gradient(circle at top right, rgba(221, 232, 246, 0.22), transparent 42%),
    linear-gradient(180deg, #ffffff 0%, #f8fbfe 100%);
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
  text-align: left;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82), 0 8px 20px rgba(15, 23, 42, 0.04);
}

.subtitle-task-filter-pill .pill-count {
  font-size: 38px;
  font-weight: 900;
  color: #162033;
  line-height: 0.88;
  letter-spacing: -0.04em;
}

.subtitle-task-filter-pill .pill-label {
  font-size: 12px;
  font-weight: 800;
  color: #607084;
  line-height: 1.2;
}

.subtitle-task-filter-pill:hover {
  border-color: #c6d4e3;
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 14px 24px rgba(15, 23, 42, 0.08);
}

.subtitle-task-filter-pill:active {
  transform: scale(0.96);
}

.subtitle-task-filter-pill.active {
  border-color: #a9c3e4;
  background:
    radial-gradient(circle at top right, rgba(138, 176, 226, 0.18), transparent 40%),
    linear-gradient(180deg, #f7fbff 0%, #edf4fd 100%);
  box-shadow: 0 16px 28px rgba(60, 99, 160, 0.12);
}

.subtitle-task-filter-pill.active .pill-count {
  color: #2356a8;
}

.subtitle-task-filter-pill.active .pill-label {
  color: #315178;
}

.subtitle-bulk-clear-btn {
  min-height: 36px;
  padding-inline: 12px;
  border-radius: 12px;
  border-color: #cfe0f4;
  background: linear-gradient(180deg, #ffffff 0%, #f5f9ff 100%);
  color: #2f65ad;
  font-size: 12px;
  font-weight: 800;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86);
}

.subtitle-task-navigator-list {
  display: grid;
  gap: 10px;
  align-content: start;
}

.subtitle-task-nav-card {
  display: grid;
  gap: 7px;
  width: 100%;
  min-height: 112px;
  padding: 12px 13px;
  border: 1px solid #d7e2ee;
  border-radius: 20px;
  background:
    radial-gradient(circle at top right, rgba(222, 233, 246, 0.22), transparent 42%),
    linear-gradient(180deg, #ffffff 0%, #f7fafe 100%);
  text-align: left;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.subtitle-task-nav-card:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: #c3d3e4;
  box-shadow: 0 18px 28px rgba(15, 23, 42, 0.09);
}

.subtitle-task-nav-card:active {
  transform: scale(0.96);
}

.subtitle-task-nav-card.active {
  border-color: #6fa2df;
  background:
    radial-gradient(circle at top right, rgba(110, 168, 255, 0.22), transparent 40%),
    linear-gradient(180deg, #f6faff 0%, #edf5ff 100%);
  box-shadow:
    0 0 0 2px rgba(103, 160, 241, 0.88),
    0 0 0 5px rgba(166, 204, 255, 0.34),
    0 18px 30px rgba(49, 96, 168, 0.16);
}

.subtitle-task-nav-card.processing {
  background:
    radial-gradient(circle at top right, rgba(255, 215, 153, 0.2), transparent 42%),
    linear-gradient(180deg, #fffdf7, #ffffff);
}

.subtitle-task-nav-card.finished {
  background:
    radial-gradient(circle at top right, rgba(163, 230, 181, 0.18), transparent 42%),
    linear-gradient(180deg, #f7fbf8, #ffffff);
}

.subtitle-task-nav-card-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.subtitle-task-nav-rj {
  font-size: 15px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.03em;
}

.subtitle-task-nav-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 4px 9px;
  border-radius: 999px;
  font-size: 9px;
  font-weight: 700;
  border: 1px solid transparent;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
  transition: all 0.28s var(--ease-spring);
}

.subtitle-task-nav-status.status-pending,
.subtitle-task-nav-status.status-cancelled {
  background: #f2f6fb;
  border-color: #d8e1ec;
  color: #475569;
}

.subtitle-task-nav-status.status-processing,
.subtitle-task-nav-status.status-awaiting_manual_match {
  background: #fff7ed;
  border-color: #f2d4ad;
  color: #c2410c;
  animation: subtitleStatusPulse 1.2s ease-in-out infinite;
}

.subtitle-task-nav-status.status-completed,
.subtitle-task-nav-status.status-manual_match_completed {
  background: #ecfdf3;
  border-color: #bfe3ca;
  color: #15803d;
  animation: subtitleStatusGlow 1.35s ease-in-out infinite;
}

.subtitle-task-nav-status.status-failed {
  background: #fef2f2;
  border-color: #f4c6c6;
  color: #dc2626;
}

.subtitle-task-nav-folder {
  font-size: 11px;
  font-weight: 700;
  line-height: 1.35;
  color: #334155;
  word-break: break-word;
}

.subtitle-task-nav-step {
  font-size: 10px;
  line-height: 1.45;
  color: #5f6f84;
}

.subtitle-task-nav-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 9px;
  color: #5f6f84;
}

.subtitle-task-nav-meta span {
  display: inline-flex;
  align-items: center;
  min-height: 21px;
  padding: 3px 8px;
  border: 1px solid #dbe5ef;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.subtitle-task-nav-meta .is-success {
  border-color: #bfdfca;
  background: linear-gradient(180deg, #f1fbf4 0%, #ebf8ef 100%);
  color: #15803d;
  font-weight: 700;
}

.subtitle-task-nav-meta .is-warning {
  border-color: #efd5ae;
  background: linear-gradient(180deg, #fff8ee 0%, #fff2e2 100%);
  color: #c2410c;
  font-weight: 700;
}

.subtitle-task-navigator-pager {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding-top: 6px;
  padding-inline: 2px;
}

.subtitle-task-navigator-page-text {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
  padding: 7px 10px;
  border: 1px solid #d7e0ea;
  border-radius: 10px;
  background: linear-gradient(180deg, #ffffff 0%, #f3f6fb 100%);
}

.subtitle-task-navigator :deep(.el-button) {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-task-navigator :deep(.el-button:not(.is-disabled):not(:disabled):not(.is-loading):hover) {
  transform: translateY(-2px) scale(1.02);
}

.subtitle-task-navigator :deep(.el-button:not(.is-disabled):not(:disabled):not(.is-loading):active) {
  transform: scale(0.96);
}

@media (max-width: 1280px) {
  .subtitle-task-navigator-head {
    flex-direction: column;
    align-items: stretch;
  }

  .subtitle-task-navigator-filters {
    grid-template-columns: 1fr 1fr;
  }
}

.subtitle-status-flip-enter-active,
.subtitle-status-flip-leave-active {
  transition: transform 0.25s ease, opacity 0.25s ease;
}

.subtitle-status-flip-enter-from,
.subtitle-status-flip-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.92);
}

@keyframes subtitleStatusPulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(194, 65, 12, 0.08);
  }
  50% {
    box-shadow: 0 0 0 6px rgba(194, 65, 12, 0.14);
  }
}

@keyframes subtitleStatusGlow {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(21, 128, 61, 0.08);
  }
  50% {
    box-shadow: 0 0 0 6px rgba(21, 128, 61, 0.14);
  }
}
</style>
