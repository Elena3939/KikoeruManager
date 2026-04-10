<template>
  <el-card shadow="never" class="subtitle-tree-card">
    <template #header>
      <div class="subtitle-section-header">
        <div>
          <div class="subtitle-tree-title">字幕筛选与配对</div>
          <div class="subtitle-section-tip">上半区先清理不要的原始字幕，下半区预览配对结果，最后一次性把音频和字幕处理成同名。</div>
        </div>
        <div class="subtitle-tree-actions">
          <span class="subtitle-tree-action-tip">展开 / 折叠仅对有子目录的字幕树生效</span>
          <el-button size="small" :disabled="!view.subtitleInspectorInfo.subtitleDir || view.subtitleInspectorBusy" :loading="view.subtitleInspectorLoading" @click="view.reloadSubtitleInspector">
            刷新当前页
          </el-button>
          <el-button size="small" :disabled="!view.subtitleInspectorInfo.subtitleDir || !view.subtitleInspectorHasDirectories || view.subtitleInspectorBusy" @click="view.expandSubtitleInspectorTree">
            展开目录
          </el-button>
          <el-button size="small" :disabled="!view.subtitleInspectorInfo.subtitleDir || !view.subtitleInspectorHasDirectories || view.subtitleInspectorBusy" @click="view.collapseSubtitleInspectorTree">
            折叠目录
          </el-button>
        </div>
      </div>
    </template>

    <div v-if="!view.subtitleInspectorInfo.subtitleDir" class="subtitle-inspector-empty">
      <el-empty description="从左侧任务里选择一个已生成字幕目录的任务进行检查" />
      <div class="subtitle-empty-tip">任务完成后会进入上方任务队列，点击对应卡片再进入这里做筛选和配对。</div>
    </div>

    <div v-else class="subtitle-tree-shell" v-loading="view.subtitleInspectorBusy" element-loading-text="正在处理字幕目录...">
      <div class="subtitle-tree-info">
        <div class="subtitle-tree-title">{{ view.activeSubtitleInspectTask?.folder_name || view.getFileName(view.subtitleInspectorInfo.folderPath) }}</div>
        <div class="subtitle-tree-path">{{ view.subtitleInspectorInfo.folderPath || view.subtitleInspectorInfo.subtitleDir }}</div>
        <div class="subtitle-tree-meta">
          <span class="subtitle-mini-chip">{{ view.getTaskDisplayRJCode(view.activeSubtitleInspectTask) }}</span>
          <span v-if="view.getTaskSourceRJCode(view.activeSubtitleInspectTask)" class="subtitle-mini-chip">来源 {{ view.getTaskSourceRJCode(view.activeSubtitleInspectTask) }}</span>
          <span class="subtitle-mini-chip">{{ view.subtitleInspectorAudioFiles.length }} 个音频</span>
          <span class="subtitle-mini-chip">{{ view.subtitleInspectorInfo.totalFiles }} 个字幕文件</span>
          <span class="subtitle-mini-chip">{{ view.formatFileSize(view.subtitleInspectorInfo.totalSize) }}</span>
        </div>
      </div>

      <div class="subtitle-match-shell">
        <div class="subtitle-match-header">
          <div>
            <div class="subtitle-tree-title">配对结果预览</div>
            <div class="subtitle-section-tip">先在这里筛掉不需要的原始字幕，再生成预匹配结果，确认后再一键应用同名。</div>
            <div v-if="view.subtitleSequenceMode" class="subtitle-sequence-hint">
              顺序点选进行中：先在左侧依次点音频，再在右侧依次点字幕，然后生成顺序配对。
              当前已点选 音频 {{ view.subtitleSequenceSelection.audioPaths.length }} 项 / 字幕 {{ view.subtitleSequenceSelection.subtitlePaths.length }} 项。
            </div>
          </div>
          <div class="subtitle-tree-actions">
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!view.canOpenSubtitleInspectorFilterDeleteDialog || view.subtitleInspectorBusy"
              @click="view.openSubtitleInspectorFilterDeleteDialog"
            >
              删除预审
            </el-button>
            <el-button size="small" @click="view.buildAutoSubtitlePairs">自动预配对</el-button>
            <el-button size="small" :type="view.subtitleSequenceMode ? 'primary' : 'default'" @click="view.setSubtitleSequenceMode(!view.subtitleSequenceMode)">
              {{ view.subtitleSequenceMode ? '退出顺序点选' : '顺序点选配对' }}
            </el-button>
            <el-button
              size="small"
              :disabled="view.subtitleSequenceMode ? !view.canBuildSequenceSubtitlePairs : !view.filteredSubtitleInspectorAudioFiles.length || !view.filteredSubtitleInspectorSubtitleFiles.length"
              @click="view.buildSequenceOrOrderedSubtitlePairs"
            >
              {{ view.subtitleSequenceMode ? '生成顺序预配对' : '按当前列表预配对' }}
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
                  :disabled="!view.subtitleManualPairs.length"
                  :loading="view.subtitlePairApplying"
                  @click="view.applySubtitleManualPairs"
                >
                  {{ view.subtitleManualApplyLabel || '一键应用同名' }}
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
          <div class="subtitle-match-panel">
            <div class="subtitle-match-panel-head">
              <div class="subtitle-task-box-title">原音频目录</div>
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
              <div class="subtitle-task-box-title">配对结果预览</div>
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
                <div class="subtitle-match-preview-grid">
                  <div class="subtitle-match-preview-block">
                    <span class="subtitle-match-preview-label">音频</span>
                    <span class="subtitle-match-preview-value" :title="formatSubtitleName(pair.audio_name)">{{ formatSubtitleName(pair.audio_name) }}</span>
                  </div>
                  <div class="subtitle-match-preview-block">
                    <span class="subtitle-match-preview-label">字幕</span>
                    <span class="subtitle-match-preview-value" :title="formatSubtitleName(pair.subtitle_name)">{{ formatSubtitleName(pair.subtitle_name) }}</span>
                  </div>
                  <div class="subtitle-match-preview-block subtitle-match-preview-block-wide">
                    <span class="subtitle-match-preview-label">应用后</span>
                    <div class="subtitle-match-preview-targets">
                      <span class="subtitle-match-preview-target" :title="pair.target_audio_name">{{ pair.target_audio_name }}</span>
                      <span class="subtitle-match-preview-target" :title="pair.target_subtitle_name">{{ pair.target_subtitle_name }}</span>
                    </div>
                  </div>
                </div>
                <div class="subtitle-match-row-actions">
                  <el-button size="small" text type="danger" :disabled="view.subtitleInspectorBusy" @click.stop="view.removeSubtitleManualPair(pair.id)">移除</el-button>
                </div>
              </button>
            </div>
          </div>

          <div class="subtitle-match-panel">
            <div class="subtitle-match-panel-head">
              <div class="subtitle-task-box-title">字幕目录</div>
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

      <div class="subtitle-tree-toolbar">
        <input :value="view.subtitleInspectorSearch" class="fm-search-input" placeholder="搜索字幕文件名或路径..." :disabled="view.subtitleInspectorBusy" @input="view.setSubtitleInspectorSearch($event.target.value)">
      </div>

      <div v-if="view.subtitleInspectorSelectedRows.length" class="subtitle-tree-selection-bar">
        <span class="subtitle-tree-selection-count">已选 {{ view.subtitleInspectorSelectedRows.length }} 项</span>
        <div class="subtitle-tree-selection-actions">
          <span class="subtitle-tree-selection-tip">支持 Ctrl+A、Ctrl/Command + 点击多选、Shift + 点击范围选择</span>
          <el-button size="small" type="danger" plain :loading="view.subtitleInspectorDeleting" :disabled="view.subtitleInspectorBusy && !view.subtitleInspectorDeleting" @click="view.batchDeleteSubtitleTreeEntries">删除选中</el-button>
          <el-button size="small" :disabled="view.subtitleInspectorBusy" @click="view.clearSubtitleInspectorSelection">取消选择</el-button>
        </div>
      </div>

      <div class="fm-head subtitle-tree-head">
        <div class="fm-col-check">
          <input type="checkbox" class="fm-check" :checked="view.subtitleInspectorAllSelected" :indeterminate.prop="view.subtitleInspectorSomeSelected" :disabled="view.subtitleInspectorBusy" @click="view.toggleAllSubtitleInspectorRows">
        </div>
        <div class="fm-col-name">文件名</div>
        <div class="fm-col-size">大小</div>
        <div class="fm-col-time">修改时间</div>
        <div class="fm-col-action">操作</div>
      </div>

      <div class="fm-scroll subtitle-tree-scroll">
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
  </el-card>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  }
})

const view = computed(() => props.ctx || {})

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
  --apple-blue: #0071e3;
  --apple-shadow: rgba(0, 0, 0, 0.12) 3px 5px 30px 0px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid rgba(255, 255, 255, 0.86);
  border-radius: 18px;
  background:
    radial-gradient(circle at top left, rgba(0, 113, 227, 0.07), transparent 32%),
    linear-gradient(180deg, #fbfbfd 0%, var(--apple-bg) 100%);
  box-shadow: var(--apple-shadow);
}
.subtitle-tree-card :deep(.el-card__header) {
  padding: 0;
  border-bottom: 1px solid rgba(29, 29, 31, 0.06);
}
.subtitle-tree-card :deep(.el-card__body) { display: flex; flex-direction: column; min-height: 0; }
.subtitle-section-header { display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 20px 24px; }
.subtitle-section-tip {
  margin-top: 6px;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 12px;
  font-weight: 400;
  color: var(--apple-text-soft);
  line-height: 1.5;
  letter-spacing: -0.12px;
}
.subtitle-mini-chip {
  display: inline-flex;
  align-items: center;
  padding: 7px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: -0.12px;
  background: #f4f6f9;
  color: #59697f;
  border: 1px solid #e6ebf2;
}
.subtitle-tree-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
.subtitle-btn-tooltip-wrap {
  display: inline-flex;
  vertical-align: middle;
}
.subtitle-tree-action-tip { font-size: 12px; color: var(--apple-text-faint); }
.subtitle-tree-shell { display: flex; flex-direction: column; gap: 12px; min-height: 780px; }
.subtitle-inspector-empty { display: grid; gap: 10px; padding: 18px 0 8px; }
.subtitle-empty-tip { text-align: center; font-size: 12px; color: var(--apple-text-faint); }
.subtitle-tree-info {
  display: grid;
  gap: 8px;
  padding: 16px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(250, 250, 252, 0.96));
  border: 1px solid rgba(255, 255, 255, 0.86);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
}
.subtitle-tree-title {
  font-family: 'SF Pro Display', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 24px;
  font-weight: 600;
  color: var(--apple-text);
  line-height: 1.14;
  letter-spacing: -0.24px;
}
.subtitle-tree-path {
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 12px;
  font-weight: 400;
  color: var(--apple-text-faint);
  word-break: break-all;
  line-height: 1.6;
  letter-spacing: -0.12px;
}
.subtitle-tree-meta { display: flex; gap: 8px; flex-wrap: wrap; }
.subtitle-match-shell { display: flex; flex-direction: column; gap: 10px; flex: 1; }
.subtitle-match-header { display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; }
.subtitle-sequence-hint {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px dashed rgba(0, 113, 227, 0.22);
  border-radius: 12px;
  background: rgba(0, 113, 227, 0.05);
  font-size: 12px;
  line-height: 1.6;
  color: #4c6791;
}
.subtitle-match-done-alert { margin-top: -2px; }
.subtitle-match-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr) minmax(0, 1fr); gap: 14px; }
.subtitle-match-panel, .subtitle-match-center {
  min-width: 0;
  border: 1px solid rgba(255, 255, 255, 0.86);
  border-radius: 18px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfbfd 100%);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.08);
}
.subtitle-match-panel-head { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; flex-wrap: wrap; }
.subtitle-match-preview-head { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; align-items: start; }
.subtitle-match-panel-tools, .subtitle-match-preview-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.subtitle-match-preview-actions { width: 100%; justify-content: flex-start; align-items: center; gap: 6px; }
.subtitle-task-box-title {
  font-family: 'SF Pro Display', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 21px;
  font-weight: 600;
  color: var(--apple-text);
  line-height: 1.19;
  letter-spacing: -0.22px;
}
.subtitle-box-meta { font-size: 12px; color: var(--apple-text-faint); }
.subtitle-match-filter-select { width: 120px; }
.subtitle-match-search { width: 100%; }
.subtitle-match-list, .subtitle-match-pair-list { display: grid; gap: 8px; min-height: 360px; max-height: 560px; overflow: auto; padding-right: 4px; }
.subtitle-match-item, .subtitle-match-pair {
  width: 100%;
  text-align: left;
  border: 1px solid #e6ecf5;
  border-radius: 14px;
  background: #ffffff;
  padding: 12px;
  cursor: pointer;
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease, background .18s ease;
}
.subtitle-match-item:hover, .subtitle-match-pair:hover {
  border-color: #b8cff5;
  box-shadow: 0 12px 24px rgba(59, 88, 135, 0.10);
  transform: translateY(-1px);
}
.subtitle-match-item.active, .subtitle-match-pair.active {
  border-color: #7eb1ff;
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.08);
  background: #f7fbff;
}
.subtitle-match-item.paired { border-color: #a6dbbc; background: #f5fcf7; }
.subtitle-match-item.suspicious, .subtitle-match-pair.suspicious { border-color: #f2cb90; background: #fffaf1; }
.subtitle-match-item.queued { border-color: #7bb4ff; background: #f4f9ff; box-shadow: inset 0 0 0 1px rgba(123, 180, 255, 0.18); }
.subtitle-match-name {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 14px;
  font-weight: 600;
  color: #1f2f46;
  letter-spacing: -0.18px;
}
.subtitle-match-meta {
  margin-top: 6px;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 12px;
  line-height: 1.55;
  color: #6f8098;
  word-break: break-all;
  letter-spacing: -0.12px;
}
.subtitle-match-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid transparent;
}
.badge-paired { background: #e9f7ef; color: #2f9158; border-color: #bfe3ca; }
.badge-low { background: #fff4de; color: #b97714; border-color: #f4d58d; }
.badge-seq { background: #edf4ff; color: #2d6cdf; border-color: #d6e4ff; }
.subtitle-match-empty {
  min-height: 140px;
  border: 1px dashed #d5dfed;
  border-radius: 14px;
  display: grid;
  place-items: center;
  padding: 16px 14px;
  text-align: center;
  color: #6f8198;
  line-height: 1.55;
  background: #fbfcfe;
}
.subtitle-card-tip { font-size: 12px; color: #8394aa; }
.subtitle-match-pair-head { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; flex-wrap: wrap; margin-bottom: 8px; }
.subtitle-match-pair-head-left { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.subtitle-match-pair-confidence,
.subtitle-match-pair-track {
  font-size: 11px;
  font-weight: 700;
  border-radius: 999px;
  padding: 3px 8px;
  border: 1px solid transparent;
}
.confidence-high { background: #e8f7ed; color: #2f8f57; border-color: #bfe3ca; }
.confidence-medium { background: #edf4ff; color: #2f69cb; border-color: #d6e4ff; }
.confidence-low { background: #fff4de; color: #b97714; border-color: #f4d58d; }
.subtitle-match-pair-track { color: #4c668f; background: #eef4ff; border-color: #d6e4ff; }
.subtitle-match-pair-reason { font-size: 12px; color: var(--apple-text-faint); letter-spacing: -0.12px; }
.subtitle-match-preview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.subtitle-match-preview-block {
  display: grid;
  gap: 6px;
  padding: 10px;
  border-radius: 12px;
  background: #f8fbff;
  border: 1px solid #ebf1f8;
  min-width: 0;
}
.subtitle-match-preview-block-wide { grid-column: 1 / -1; }
.subtitle-match-preview-label { font-size: 12px; color: #6f8098; letter-spacing: -0.12px; }
.subtitle-match-preview-value {
  color: #203650;
  font-weight: 600;
  line-height: 1.55;
  word-break: break-all;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.subtitle-match-preview-targets { display: grid; gap: 8px; }
.subtitle-match-preview-target { color: #203650; font-weight: 600; line-height: 1.55; word-break: break-all; display: block; }
.subtitle-match-row-actions { margin-top: 8px; display: flex; justify-content: flex-end; }
.subtitle-tree-toolbar { display: flex; justify-content: flex-end; }
.subtitle-tree-selection-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #f2d6d2;
  border-radius: 12px;
  background: #fff8f7;
}
.subtitle-tree-selection-count { font-size: 13px; font-weight: 700; color: #a24a43; }
.subtitle-tree-selection-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.subtitle-tree-selection-tip { font-size: 12px; color: #8a97aa; }
.subtitle-tree-head { margin-top: 2px; }
.subtitle-tree-scroll {
  min-height: 260px;
  max-height: 520px;
  overflow: auto;
  border: 1px solid #e9eef5;
  border-radius: 12px;
  background: #ffffff;
}
.subtitle-tree-row-actions { display: flex; gap: 8px; }
.fm-head, .fm-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 110px 170px 120px; align-items: center; }
.fm-head {
  min-height: 36px;
  padding: 0 12px;
  border-bottom: 1px solid #e8edf5;
  background: #f6f8fb;
  font-size: 12px;
  font-weight: 700;
  color: #5f7188;
}
.fm-row {
  min-height: 36px;
  padding: 0 12px;
  border-bottom: 1px solid #edf1f6;
  font-size: 13px;
  color: var(--apple-text);
}
.fm-row-dir { background: #fafbfd; }
.fm-row-selected { background: #eef6ff !important; }
.fm-empty { display: flex; align-items: center; justify-content: center; min-height: 180px; color: #a2b0c2; }
.fm-col-name, .fm-col-size, .fm-col-time, .fm-col-action { min-width: 0; }
.fm-name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.fm-arrow-toggle { width: 16px; height: 16px; border: none; background: transparent; color: #8ea0b8; cursor: pointer; padding: 0; transition: transform .18s ease; }
.fm-arrow-toggle.open { transform: rotate(90deg); color: var(--apple-blue); }
.fm-arrow-placeholder { width: 16px; flex: 0 0 16px; }
.fm-file-icon { width: 18px; display: inline-flex; justify-content: center; color: var(--apple-blue); }
.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-link-edit, .fm-link-danger {
  border: 1px solid #d7dfec;
  background: #fff;
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 12px;
  transition: border-color .18s ease, background .18s ease, color .18s ease, box-shadow .18s ease, transform .18s ease;
}
.fm-link-edit { color: #5279b8; }
.fm-link-danger { color: #d84b46; border-color: #efc1be; background: #fff7f7; }
.fm-link-edit:hover {
  color: var(--apple-blue);
  border-color: #bfd7ff;
  background: #eef6ff;
  box-shadow: 0 8px 18px rgba(64, 158, 255, 0.10);
  transform: translateY(-1px);
}
.fm-link-danger:hover {
  color: #c40017;
  border-color: #f3a8a8;
  background: #fff0f0;
  box-shadow: 0 8px 18px rgba(215, 0, 21, 0.12);
  transform: translateY(-1px);
}
.fm-check { width: 14px; height: 14px; accent-color: var(--apple-blue); }
.fm-search-input {
  width: 260px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid #d9e1ec;
  border-radius: 10px;
  outline: none;
}
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
  border-color: rgba(0, 113, 227, 0.18);
  background: #f4f8ff;
  color: var(--apple-blue);
}
.subtitle-tree-card :deep(.el-button--primary) {
  background: var(--apple-blue);
  border-color: var(--apple-blue);
  color: #ffffff;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    transform 0.2s ease,
    box-shadow 0.2s ease;
}
.subtitle-tree-card :deep(.el-button--primary:hover:not(:disabled):not(.is-loading)) {
  background: #ffffff !important;
  border-color: var(--apple-blue) !important;
  color: var(--apple-blue) !important;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 113, 227, 0.18);
}
.subtitle-tree-card :deep(.el-button--primary:active:not(:disabled):not(.is-loading)) {
  transform: translateY(0);
  box-shadow: 0 2px 6px rgba(0, 113, 227, 0.12);
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
  outline: 2px solid var(--apple-blue);
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
