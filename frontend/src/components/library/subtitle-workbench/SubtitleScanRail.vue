<template>
  <component :is="embedded ? 'div' : 'el-card'" :shadow="embedded ? undefined : 'never'" :class="embedded ? 'subtitle-selection-card subtitle-selection-card-embedded' : 'subtitle-selection-card'">
    <template v-if="!embedded" #header>
      <div class="subtitle-selection-header">
        <div class="subtitle-selection-header-main">
          <div class="subtitle-selection-header-top">
            <div class="subtitle-selection-header-title">
              <span>扫描命中目录</span>
              <span class="subtitle-selection-count-pill">{{ ctx.subtitleDialogSelection.length }}</span>
            </div>
            <span v-if="ctx.subtitleSelectionLoading && ctx.subtitleSelectionProgressText" class="subtitle-selection-progress">{{ ctx.subtitleSelectionProgressText }}</span>
          </div>
        </div>
        <div v-if="ctx.subtitleSelectionTotalPages > 1" class="subtitle-selection-pager">
          <el-button size="small" text :disabled="ctx.subtitleSelectionPage <= 1" @click="ctx.setSubtitleSelectionPage(ctx.subtitleSelectionPage - 1)">上一页</el-button>
          <span>{{ ctx.subtitleSelectionPage }} / {{ ctx.subtitleSelectionTotalPages }}</span>
          <el-button size="small" text :disabled="ctx.subtitleSelectionPage >= ctx.subtitleSelectionTotalPages" @click="ctx.setSubtitleSelectionPage(ctx.subtitleSelectionPage + 1)">下一页</el-button>
        </div>
      </div>
    </template>

    <div class="subtitle-selection-live">
      <div v-if="ctx.subtitleScanSessionSummary.length" class="subtitle-scan-result-summary subtitle-scan-result-summary-compact">
        <span v-for="item in ctx.subtitleScanSessionSummary" :key="item.key" class="subtitle-mini-chip">{{ item.label }} {{ item.value }}</span>
      </div>
      <div v-if="ctx.subtitleSelectionLoading && !ctx.subtitleDialogSelection.length" class="subtitle-selection-loading">
        <AppLoadingAnimation variant="inline" :size="36" />
        <span>{{ ctx.subtitleSelectionProgressText || '正在扫描目录…' }}</span>
      </div>
      <AppEmptyState v-else-if="!ctx.subtitleDialogSelection.length" description="没有识别到 RJ 文件夹" size="sm" />
      <template v-else>
        <div class="subtitle-selection-section">
          <div class="subtitle-selection-subhead">
            <div class="subtitle-selection-subhead-main">
              <div class="subtitle-selection-subtitle">可执行与已入任务</div>
              <span class="subtitle-selection-count-pill">{{ ctx.subtitleExecutableSelectionItems.length }}</span>
            </div>
          </div>
          <div class="subtitle-selection-subhead-actions subtitle-selection-subhead-actions-separated">
            <div v-if="ctx.subtitleSelectionFilterOptions.length" class="subtitle-selection-filter-row subtitle-selection-filter-row-workbench">
              <button
                v-for="item in ctx.subtitleSelectionFilterOptions"
                :key="item.key"
                type="button"
                class="subtitle-mini-chip subtitle-chip-button subtitle-filter-pill"
                :class="{ active: ctx.subtitleSelectionFilter === item.key }"
                @click="ctx.setSubtitleSelectionFilter(item.key)"
              >
                {{ item.label }} {{ item.value }}
              </button>
            </div>
            <button type="button" class="subtitle-section-toggle" @click="ctx.setSubtitleExecutableCollapsed(!ctx.subtitleExecutableCollapsed)">
              <span>{{ ctx.subtitleExecutableCollapsed ? '展开' : '收起' }}</span>
              <el-icon :class="{ 'is-collapsed': ctx.subtitleExecutableCollapsed }"><ArrowDown /></el-icon>
            </button>
          </div>
          <div v-if="ctx.subtitleSelectionTotalPages > 1 && !ctx.subtitleExecutableCollapsed" class="subtitle-selection-inline-pager">
            <el-button size="small" text :disabled="ctx.subtitleSelectionPage <= 1" @click="ctx.setSubtitleSelectionPage(ctx.subtitleSelectionPage - 1)">
              上一页
            </el-button>
            <span class="subtitle-selection-inline-pager-text">{{ ctx.subtitleSelectionPage }} / {{ ctx.subtitleSelectionTotalPages }}</span>
            <el-button size="small" text :disabled="ctx.subtitleSelectionPage >= ctx.subtitleSelectionTotalPages" @click="ctx.setSubtitleSelectionPage(ctx.subtitleSelectionPage + 1)">
              下一页
            </el-button>
          </div>
          <AppEmptyState v-if="!ctx.subtitleExecutableCollapsed && !ctx.subtitleExecutableDisplayItems.length" description="当前没有可执行或已入任务的 RJ 目录" size="sm" />
          <transition-group v-else-if="!ctx.subtitleExecutableCollapsed" name="subtitle-card-fade" tag="div" class="subtitle-selection-list">
            <button
              v-for="item in ctx.pagedSubtitleSelectionItems"
              :key="ctx.buildSubtitleSelectionKey(item)"
              type="button"
              class="subtitle-selection-item"
              :class="{ active: ctx.isSubtitleSelectionActive(item) }"
              :title="item.folder_path"
              @click="ctx.focusSubtitleSelectionItem(item)"
            >
              <div class="subtitle-selection-body">
                <div class="subtitle-selection-name">{{ getDisplayFolderName(item) }}</div>
                <div class="subtitle-selection-submeta">
                  <span v-if="ctx.getLibraryLabelById(item.library_id)" class="subtitle-selection-library">来源库：{{ ctx.getLibraryLabelById(item.library_id) }}</span>
                </div>
                <div class="subtitle-selection-stats">
                  <span class="subtitle-mini-chip" :class="ctx.getSubtitleSelectionQueueClass(item)">{{ ctx.getSubtitleSelectionQueueLabel(item) }}</span>
                  <span
                    v-for="chip in ctx.getSubtitleSelectionExistingChips(item)"
                    :key="`${ctx.buildSubtitleSelectionKey(item)}-${chip.key}`"
                    class="subtitle-mini-chip"
                  >
                    {{ chip.label }}
                  </span>
                </div>
                <div v-if="item.queue_message" class="subtitle-selection-note">{{ item.queue_message }}</div>
                <div v-if="item.queue_state === 'existing_task' || ctx.canInspectSubtitleSelectionFolder(item) || ctx.canRetryCreateSubtitleTaskForSelection(item)" class="subtitle-selection-actions">
                  <el-button
                    size="small"
                    text
                    type="primary"
                    v-if="item.queue_state === 'existing_task' || ctx.canInspectSubtitleSelectionFolder(item)"
                    @click.stop="ctx.focusSubtitleSelectionItem(item)"
                  >
                    {{ item.queue_state === 'existing_task' ? '打开现有任务' : '检查字幕树' }}
                  </el-button>
                  <el-button
                    v-if="ctx.canRetryCreateSubtitleTaskForSelection(item)"
                    size="small"
                    text
                    type="danger"
                    :loading="ctx.subtitleForceQueueKey === ctx.buildSubtitleSelectionKey(item)"
                    :disabled="Boolean(ctx.subtitleForceQueueKey)"
                    @click.stop="ctx.forceCreateSubtitleTaskForSelection(item)"
                  >
                    重试加入
                  </el-button>
                  <el-button
                    v-if="ctx.canForceCreateSubtitleTaskForSelection(item)"
                    size="small"
                    text
                    type="success"
                    :loading="ctx.subtitleForceQueueKey === ctx.buildSubtitleSelectionKey(item)"
                    :disabled="Boolean(ctx.subtitleForceQueueKey)"
                    @click.stop="ctx.forceCreateSubtitleTaskForSelection(item)"
                  >
                    创建一次任务
                  </el-button>
                </div>
              </div>
            </button>
          </transition-group>
        </div>

        <div v-if="ctx.subtitleSkippedSelectionItems.length" class="subtitle-selection-section subtitle-selection-section-split">
          <div class="subtitle-selection-subhead">
            <div class="subtitle-selection-subhead-main">
              <div class="subtitle-selection-subtitle">被跳过</div>
              <span class="subtitle-selection-count-pill">{{ ctx.filteredSubtitleSkippedSelectionItems.length }}</span>
            </div>
            <div class="subtitle-selection-subhead-actions">
              <div v-if="ctx.subtitleSkippedSelectionFilterOptions.length" class="subtitle-selection-filter-row">
                <button
                  v-for="item in ctx.subtitleSkippedSelectionFilterOptions"
                  :key="item.key"
                  type="button"
                  class="subtitle-mini-chip subtitle-chip-button"
                  :class="{ active: ctx.isSubtitleSkippedSelectionFilterActive(item.key) }"
                  @click="ctx.toggleSubtitleSkippedSelectionFilter(item.key)"
                >
                  {{ item.label }} {{ item.value }}
                </button>
              </div>
              <button type="button" class="subtitle-section-toggle" @click="ctx.setSubtitleSkippedCollapsed(!ctx.subtitleSkippedCollapsed)">
                <span>{{ ctx.subtitleSkippedCollapsed ? '展开' : '收起' }}</span>
                <el-icon :class="{ 'is-collapsed': ctx.subtitleSkippedCollapsed }"><ArrowDown /></el-icon>
              </button>
            </div>
          </div>
          <transition-group v-if="!ctx.subtitleSkippedCollapsed" name="subtitle-card-fade" tag="div" class="subtitle-selection-list subtitle-selection-list-skipped">
            <button
              v-for="item in ctx.filteredSubtitleSkippedSelectionItems"
              :key="`${ctx.buildSubtitleSelectionKey(item)}-skipped`"
              type="button"
              class="subtitle-selection-item skipped"
              :class="{ active: ctx.isSubtitleSelectionActive(item) }"
              :title="item.folder_path"
              @click="ctx.focusSubtitleSelectionItem(item)"
            >
              <div class="subtitle-selection-body">
                <div class="subtitle-selection-name">{{ getDisplayFolderName(item) }}</div>
                <div class="subtitle-selection-submeta">
                  <span v-if="ctx.getLibraryLabelById(item.library_id)" class="subtitle-selection-library">来源库：{{ ctx.getLibraryLabelById(item.library_id) }}</span>
                </div>
                <div class="subtitle-selection-stats">
                  <span class="subtitle-mini-chip" :class="ctx.getSubtitleSelectionQueueClass(item)">{{ ctx.getSubtitleSelectionQueueLabel(item) }}</span>
                  <span
                    v-for="chip in ctx.getSubtitleSelectionExistingChips(item)"
                    :key="`${ctx.buildSubtitleSelectionKey(item)}-${chip.key}`"
                    class="subtitle-mini-chip"
                  >
                    {{ chip.label }}
                  </span>
                </div>
                <div v-if="item.queue_message" class="subtitle-selection-note">{{ item.queue_message }}</div>
                <div class="subtitle-selection-actions">
                  <el-button
                    v-if="ctx.canInspectSubtitleSelectionFolder(item)"
                    size="small"
                    text
                    @click.stop="ctx.inspectSubtitleSelectionFolder(item)"
                  >
                    检查字幕树
                  </el-button>
                  <el-button
                    v-if="ctx.canForceCreateSubtitleTaskForSelection(item)"
                    size="small"
                    text
                    type="success"
                    :loading="ctx.subtitleForceQueueKey === ctx.buildSubtitleSelectionKey(item)"
                    :disabled="Boolean(ctx.subtitleForceQueueKey)"
                    @click.stop="ctx.forceCreateSubtitleTaskForSelection(item)"
                  >
                    创建一次任务
                  </el-button>
                </div>
              </div>
            </button>
          </transition-group>
        </div>
      </template>
    </div>

    <div v-if="ctx.subtitleScanTargetResults.length" class="subtitle-scan-result-wrap">
      <div class="subtitle-scan-skip-head">
        <div class="subtitle-selection-subhead-main">
          <div class="subtitle-scan-skip-title">扫描目标</div>
          <span class="subtitle-selection-count-pill">{{ ctx.subtitleScanTargetResults.length }}</span>
        </div>
        <button type="button" class="subtitle-section-toggle" @click="ctx.setSubtitleScanTargetsCollapsed(!ctx.subtitleScanTargetsCollapsed)">
          <span>{{ ctx.subtitleScanTargetsCollapsed ? '展开' : '收起' }}</span>
          <el-icon :class="{ 'is-collapsed': ctx.subtitleScanTargetsCollapsed }"><ArrowDown /></el-icon>
        </button>
      </div>
      <div class="subtitle-scan-result-summary">
        <span v-if="ctx.subtitleScanSummary.pending" class="subtitle-mini-chip">扫描中 {{ ctx.subtitleScanSummary.pending }}</span>
        <span class="subtitle-mini-chip">成功 {{ ctx.subtitleScanSummary.success }}</span>
        <span v-if="ctx.subtitleScanSummary.noAudio" class="subtitle-mini-chip">无音频 {{ ctx.subtitleScanSummary.noAudio }}</span>
        <span v-if="ctx.subtitleScanSummary.noMatch" class="subtitle-mini-chip">未识别 {{ ctx.subtitleScanSummary.noMatch }}</span>
        <span v-if="ctx.subtitleScanSummary.failed" class="subtitle-mini-chip">失败 {{ ctx.subtitleScanSummary.failed }}</span>
      </div>
      <transition-group v-if="!ctx.subtitleScanTargetsCollapsed" name="subtitle-card-fade" tag="div" class="subtitle-scan-result-list">
        <div v-for="item in ctx.subtitleScanTargetResults" :key="ctx.buildSubtitleScanTargetResultKey(item)" class="subtitle-scan-result-row" :class="`status-${item.status}`">
          <div class="subtitle-scan-result-main" :title="item.path">
            <span class="subtitle-scan-result-name">{{ item.name }}</span>
            <div class="subtitle-scan-result-submeta">
              <span v-if="ctx.getLibraryLabelById(item.library_id)" class="subtitle-scan-result-library">{{ ctx.getLibraryLabelById(item.library_id) }}</span>
              <span class="subtitle-scan-result-path">{{ item.path }}</span>
            </div>
          </div>
          <div class="subtitle-scan-result-meta">
            <span class="subtitle-scan-result-status" :class="`status-${item.status}`">{{ ctx.getSubtitleScanResultLabel(item.status) }}</span>
            <span class="subtitle-scan-result-message">{{ item.message }}</span>
            <el-button
              v-if="ctx.canRetrySubtitleScanResult(item)"
              size="small"
              plain
              :loading="ctx.subtitleScanRetryingPath === ctx.buildSubtitleScanTargetResultKey(item)"
              :disabled="Boolean(ctx.subtitleScanRetryingPath) && ctx.subtitleScanRetryingPath !== ctx.buildSubtitleScanTargetResultKey(item)"
              @click="ctx.rescanSubtitleSelectionTarget(item)"
            >
              重新扫描此项
            </el-button>
          </div>
        </div>
      </transition-group>
    </div>

    <div v-if="ctx.subtitleSkippedScanResults.length" class="subtitle-scan-skip-wrap">
      <div class="subtitle-scan-skip-head">
        <div class="subtitle-selection-subhead-main">
          <div class="subtitle-scan-skip-title">跳过结果</div>
          <span class="subtitle-selection-count-pill">{{ ctx.filteredSubtitleSkippedScanResults.length }}</span>
        </div>
        <div v-if="ctx.subtitleSkippedScanFilterOptions.length" class="subtitle-selection-filter-row">
          <button
            v-for="item in ctx.subtitleSkippedScanFilterOptions"
            :key="item.key"
            type="button"
            class="subtitle-mini-chip subtitle-chip-button"
            :class="{ active: ctx.subtitleScanSkipFilter === item.key }"
            @click="ctx.setSubtitleScanSkipFilter(item.key)"
          >
            {{ item.label }} {{ item.value }}
          </button>
        </div>
      </div>
      <transition-group name="subtitle-card-fade" tag="div" class="subtitle-scan-skip-list">
        <div v-for="item in ctx.filteredSubtitleSkippedScanResults" :key="`${ctx.buildSubtitleScanTargetResultKey(item)}-skipped`" class="subtitle-scan-result-row skipped" :class="`status-${item.status}`">
          <div class="subtitle-scan-result-main">
            <span class="subtitle-scan-result-name">{{ item.name }}</span>
            <div class="subtitle-scan-result-submeta">
              <span v-if="ctx.getLibraryLabelById(item.library_id)" class="subtitle-scan-result-library">{{ ctx.getLibraryLabelById(item.library_id) }}</span>
              <span class="subtitle-scan-result-path">{{ item.path }}</span>
            </div>
          </div>
          <div class="subtitle-scan-result-meta">
            <span class="subtitle-scan-result-status" :class="`status-${item.status}`">{{ ctx.getSubtitleScanResultLabel(item.status) }}</span>
            <span class="subtitle-scan-result-message">{{ item.message }}</span>
            <el-button
              v-if="ctx.canRetrySubtitleScanResult(item)"
              size="small"
              plain
              :loading="ctx.subtitleScanRetryingPath === ctx.buildSubtitleScanTargetResultKey(item)"
              :disabled="Boolean(ctx.subtitleScanRetryingPath) && ctx.subtitleScanRetryingPath !== ctx.buildSubtitleScanTargetResultKey(item)"
              @click="ctx.rescanSubtitleSelectionTarget(item)"
            >
              重新扫描此项
            </el-button>
          </div>
        </div>
      </transition-group>
    </div>
  </component>
</template>

<script setup>
import { ArrowDown } from '@element-plus/icons-vue'
import AppLoadingAnimation from '../../common/AppLoadingAnimation.vue'
import AppEmptyState from '../../common/AppEmptyState.vue'

defineProps({
  ctx: {
    type: Object,
    required: true
  },
  embedded: {
    type: Boolean,
    default: false
  }
})

function getDisplayFolderName(item) {
  const folderName = String(item?.folder_name || '').trim()
  if (folderName && !/[\\/]/.test(folderName)) return folderName

  const folderPath = String(item?.folder_path || item?.path || '').trim().replace(/[\\/]+$/, '')
  if (!folderPath) return folderName || '-'

  const parts = folderPath.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || folderName || folderPath
}
</script>

<style scoped>
.subtitle-selection-card {
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  display: grid;
  gap: 14px;
  min-width: 0;
}

.subtitle-selection-header,
.subtitle-selection-subhead,
.subtitle-scan-skip-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.subtitle-selection-header-title,
.subtitle-selection-subhead-main {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.subtitle-selection-live,
.subtitle-selection-section,
.subtitle-selection-list,
.subtitle-scan-result-list,
.subtitle-scan-skip-list {
  display: grid;
  gap: 10px;
}

.subtitle-selection-count-pill,
.subtitle-mini-chip {
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

.subtitle-selection-count-pill {
  min-width: 46px;
  height: 28px;
  padding-inline: 10px;
  border-color: #cfdcf2;
  background: linear-gradient(180deg, #f7fbff 0%, #edf4ff 100%);
  color: #315f9f;
}

.subtitle-mini-chip:hover,
.subtitle-selection-count-pill:hover {
  transform: translateY(-2px) scale(1.02);
}

.subtitle-mini-chip:active,
.subtitle-selection-count-pill:active {
  transform: scale(0.96);
}

.subtitle-mini-chip-primary,
.subtitle-mini-chip-success,
.subtitle-mini-chip-warning,
.subtitle-mini-chip-danger,
.subtitle-mini-chip-muted {
  border-width: 1px;
}

.subtitle-mini-chip-primary {
  color: #2f5f9f;
  border-color: #c8daf7;
  background: linear-gradient(180deg, #f6faff 0%, #edf4ff 100%);
}

.subtitle-mini-chip-success {
  color: #257548;
  border-color: #bfe2cb;
  background: linear-gradient(180deg, #f4fcf7 0%, #ebf8ef 100%);
}

.subtitle-mini-chip-warning {
  color: #a76620;
  border-color: #f0d7af;
  background: linear-gradient(180deg, #fffaf0 0%, #fff5e6 100%);
}

.subtitle-mini-chip-danger {
  color: #bb4141;
  border-color: #f2c5c5;
  background: linear-gradient(180deg, #fff7f7 0%, #fff0f0 100%);
}

.subtitle-mini-chip-muted {
  color: #64748b;
  border-color: #d7e0ea;
  background: linear-gradient(180deg, #f9fbfd 0%, #f2f5f9 100%);
}

.subtitle-selection-subtitle,
.subtitle-scan-skip-title {
  font-size: 15px;
  font-weight: 800;
  color: #1f2d3d;
  letter-spacing: -0.02em;
}

.subtitle-selection-progress,
.subtitle-selection-pager,
.subtitle-selection-note,
.subtitle-scan-result-message,
.subtitle-scan-result-path,
.subtitle-selection-path {
  font-size: 11px;
  line-height: 1.5;
  color: #64748b;
}

.subtitle-selection-filter-row,
.subtitle-selection-subhead-actions,
.subtitle-selection-stats,
.subtitle-selection-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.subtitle-selection-filter-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, max-content));
  gap: 8px;
}

.subtitle-selection-subhead-actions {
  justify-content: flex-end;
}

.subtitle-selection-subhead-actions-separated {
  justify-content: space-between;
  align-items: center;
}

.subtitle-selection-inline-pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.subtitle-selection-inline-pager-text {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid #d8e1ec;
  border-radius: 10px;
  background: linear-gradient(180deg, #ffffff 0%, #f7fafd 100%);
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.subtitle-chip-button {
  cursor: pointer;
  transition: all 0.3s var(--ease-spring);
  min-height: 34px;
  padding-inline: 12px;
}

.subtitle-filter-pill {
  min-height: 38px;
  padding-inline: 14px;
  border-radius: 12px;
  border-color: #d9e4ef;
  background: linear-gradient(180deg, #ffffff 0%, #f8fbfe 100%);
  color: #445a73;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.86), 0 6px 16px rgba(15, 23, 42, 0.04);
}

.subtitle-chip-button:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: #c3d4e5;
}

.subtitle-chip-button.active {
  border-color: #b8cbe1;
  background: linear-gradient(180deg, #f7fbff 0%, #edf4fb 100%);
  color: #1f3956;
  box-shadow: 0 10px 18px rgba(36, 80, 138, 0.1);
}

.subtitle-section-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 34px;
  padding: 0 2px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.subtitle-section-toggle .el-icon {
  transition: transform 0.22s ease;
}

.subtitle-section-toggle .el-icon.is-collapsed {
  transform: rotate(-90deg);
}

.subtitle-selection-item,
.subtitle-scan-result-row {
  width: 100%;
  text-align: left;
  border: 1px solid #d9e4ef;
  border-radius: 18px;
  background:
    radial-gradient(circle at top right, rgba(222, 233, 246, 0.24), transparent 42%),
    linear-gradient(180deg, #ffffff 0%, #f8fbfe 100%);
  padding: 12px;
  transition: all 0.3s var(--ease-spring);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.84);
}

.subtitle-selection-item {
  cursor: pointer;
}

.subtitle-selection-item:hover,
.subtitle-scan-result-row:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: #c3d4e5;
  box-shadow: 0 14px 22px rgba(15, 23, 42, 0.08);
}

.subtitle-selection-item:active {
  transform: scale(0.96);
}

.subtitle-selection-item.active {
  border-color: #adc6e2;
  box-shadow: 0 0 0 2px rgba(191, 213, 234, 0.72), 0 16px 28px rgba(52, 91, 145, 0.08);
}

.subtitle-selection-item.skipped,
.subtitle-scan-result-row.skipped {
  background: linear-gradient(180deg, #fffdfa 0%, #ffffff 100%);
  border-style: dashed;
}

.subtitle-selection-body,
.subtitle-selection-submeta,
.subtitle-scan-result-main,
.subtitle-scan-result-submeta,
.subtitle-scan-result-meta {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.subtitle-selection-name,
.subtitle-scan-result-name {
  font-size: 13px;
  font-weight: 800;
  color: #1f2d3d;
  line-height: 1.4;
  word-break: break-word;
  letter-spacing: -0.02em;
}

.subtitle-selection-library,
.subtitle-scan-result-library {
  font-size: 10px;
  color: #52708f;
  font-weight: 700;
}

.subtitle-selection-stats {
  gap: 6px;
}

.subtitle-selection-note {
  font-size: 10px;
  line-height: 1.45;
}

.subtitle-selection-actions {
  gap: 6px;
  padding-top: 0;
}

.subtitle-scan-result-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: start;
}

.subtitle-scan-result-meta {
  justify-items: end;
}

.subtitle-scan-result-status {
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
}

.subtitle-scan-result-status.status-pending {
  background: #f2f6fb;
  border-color: #d8e1ec;
  color: #475569;
}

.subtitle-scan-result-status.status-success {
  background: #ecfdf3;
  border-color: #bfe3ca;
  color: #15803d;
}

.subtitle-scan-result-status.status-no_audio,
.subtitle-scan-result-status.status-no_match {
  background: #fff7ed;
  border-color: #f2d4ad;
  color: #c2410c;
}

.subtitle-scan-result-status.status-failed {
  background: #fef2f2;
  border-color: #f4c6c6;
  color: #dc2626;
}

.subtitle-selection-loading {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 64px;
}

.subtitle-card-fade-enter-active,
.subtitle-card-fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.subtitle-card-fade-enter-from,
.subtitle-card-fade-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

.subtitle-selection-card :deep(.el-button) {
  min-height: 26px;
  padding-inline: 10px;
  border-radius: 12px;
  border-color: #d7e3ef;
  background: linear-gradient(180deg, #ffffff 0%, #f5f8fc 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
  font-size: 11px;
  font-weight: 700;
}

.subtitle-selection-card :deep(.el-button--primary.is-text),
.subtitle-selection-card :deep(.el-button--success.is-text),
.subtitle-selection-card :deep(.el-button--danger.is-text) {
  padding-left: 10px;
  padding-right: 10px;
  border-width: 1px;
  border-style: solid;
  background: #ffffff;
}

.subtitle-selection-card :deep(.el-button--primary.is-text) {
  color: #2d6bc8;
  border-color: #c9daf2;
}

.subtitle-selection-card :deep(.el-button--success.is-text) {
  color: #3d8a35;
  border-color: #cde6c8;
}

.subtitle-selection-card :deep(.el-button--danger.is-text) {
  color: #c75353;
  border-color: #efc8c8;
}

.subtitle-selection-card :deep(.el-button.is-text:not(.is-disabled):not(:disabled):hover) {
  background: #ffffff;
  box-shadow: 0 10px 16px rgba(15, 23, 42, 0.08);
}

.subtitle-selection-card :deep(.el-button--primary.is-text:not(.is-disabled):not(:disabled):hover) {
  color: #1f5fbf;
  border-color: #b8d0f0;
}

.subtitle-selection-card :deep(.el-button--success.is-text:not(.is-disabled):not(:disabled):hover) {
  color: #2f7a29;
  border-color: #bfe0b8;
}

@media (max-width: 1280px) {
  .subtitle-selection-header,
  .subtitle-selection-subhead,
  .subtitle-scan-skip-head {
    flex-direction: column;
  }

  .subtitle-selection-subhead-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .subtitle-selection-subhead-actions-separated {
    flex-direction: column;
    align-items: stretch;
  }

  .subtitle-selection-inline-pager {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .subtitle-selection-filter-row {
    grid-template-columns: 1fr;
    width: 100%;
  }

  .subtitle-scan-result-row {
    grid-template-columns: 1fr;
  }

  .subtitle-scan-result-meta {
    justify-items: start;
  }
}
</style>
