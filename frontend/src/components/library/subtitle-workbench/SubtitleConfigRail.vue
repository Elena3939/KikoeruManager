<template>
  <div class="subtitle-config-card">
    <template v-if="mode === 'settings'">
      <div class="subtitle-option-stack">
        <section class="subtitle-settings-block">
          <div class="subtitle-block-head">
            <div class="subtitle-block-title">抓取行为</div>
            <div class="subtitle-block-tip">建任务和扫描命中策略。</div>
          </div>

          <div class="subtitle-setting-list">
            <div class="subtitle-setting-item">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">覆盖已有字幕</div>
                <div class="subtitle-card-tip">同名字幕直接覆盖，适合重抓和修正。</div>
              </div>
              <el-switch :model-value="ctx.subtitleOptions.overwriteExisting" @update:model-value="ctx.setSubtitleOption('overwriteExisting', $event)" />
            </div>

            <div class="subtitle-setting-item subtitle-setting-item-stack">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">扫描深度</div>
                <div class="subtitle-card-tip">递归查找 RJ 文件夹，默认 3 层。</div>
              </div>
              <el-input-number
                :model-value="ctx.subtitleOptions.scanDepth"
                :min="1"
                :max="10"
                :step="1"
                controls-position="right"
                @update:model-value="ctx.setSubtitleOption('scanDepth', $event)"
              />
            </div>

            <div class="subtitle-setting-item">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">启用 metadata 匹配</div>
                <div class="subtitle-card-tip">读取音频标签，提高文件名配对准确度。</div>
              </div>
              <el-switch :model-value="ctx.subtitleOptions.enableMetadataMatch" @update:model-value="ctx.setSubtitleOption('enableMetadataMatch', $event)" />
            </div>

            <div class="subtitle-setting-item">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">已有字幕时跳过</div>
                <div class="subtitle-card-tip">已存在字幕就不进抓取队列。</div>
              </div>
              <el-switch :model-value="ctx.subtitleOptions.skipIfExistingSubtitles" @update:model-value="ctx.setSubtitleOption('skipIfExistingSubtitles', $event)" />
            </div>
          </div>
        </section>

        <section class="subtitle-settings-block">
          <div class="subtitle-block-head">
            <div class="subtitle-block-title">命名与筛选</div>
            <div class="subtitle-block-tip">配对后的命名口径和候选字幕过滤。</div>
          </div>

          <div class="subtitle-setting-list">
            <div class="subtitle-setting-item subtitle-setting-item-stack">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">同名依据</div>
                <div class="subtitle-card-tip">一键应用后，以谁的名字为准。</div>
              </div>
              <el-radio-group :model-value="ctx.subtitleOptions.namingStrategy" size="small" @update:model-value="ctx.setSubtitleOption('namingStrategy', $event)">
                <el-radio-button label="audio">以音频名为准</el-radio-button>
                <el-radio-button label="subtitle">以字幕名为准</el-radio-button>
              </el-radio-group>
            </div>

            <div class="subtitle-setting-item">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">启用字幕过滤</div>
                <div class="subtitle-card-tip">只筛字幕候选，不影响解压过滤配置。</div>
              </div>
              <el-switch :model-value="ctx.subtitleOptions.useFilterRules" @update:model-value="ctx.setSubtitleOption('useFilterRules', $event)" />
            </div>
          </div>

          <div v-if="ctx.subtitleOptions.useFilterRules" class="subtitle-filter-editor">
            <div class="subtitle-filter-editor-head">
              <div>
                <div class="subtitle-option-title subtitle-option-title-sm">字幕过滤规则</div>
                <div class="subtitle-card-tip">按文件名、路径或全文本匹配候选字幕。</div>
              </div>
              <el-button size="small" class="subtitle-inline-btn" @click="ctx.addSubtitleFilterRule()">添加规则</el-button>
            </div>

            <div v-if="!ctx.subtitleOptions.subtitleFilterRules.length" class="subtitle-filter-empty">
              还没有规则，先加一条。
            </div>

            <div v-else class="subtitle-filter-list">
              <div v-for="rule in ctx.subtitleOptions.subtitleFilterRules" :key="rule.id" class="subtitle-filter-row">
                <div class="subtitle-filter-row-top">
                  <el-select v-model="rule.target" size="small" class="subtitle-filter-target">
                    <el-option label="文件名" value="name" />
                    <el-option label="路径" value="path" />
                    <el-option label="全部" value="all" />
                  </el-select>
                  <el-switch v-model="rule.enabled" size="small" />
                </div>
                <el-input v-model="rule.name" size="small" placeholder="规则名称" />
                <el-input v-model="rule.pattern" size="small" placeholder="正则，例如 (反转|reverse|无SE)" />
                <div class="subtitle-filter-row-actions">
                  <el-button size="small" text type="danger" @click="ctx.removeSubtitleFilterRule(rule.id)">删除</el-button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="subtitle-settings-block">
          <div class="subtitle-block-head">
            <div class="subtitle-block-title">任务展示</div>
            <div class="subtitle-block-tip">只控制面板显示，不影响执行和日志写入。</div>
          </div>

          <div class="subtitle-pill-grid">
            <button type="button" class="subtitle-toggle-pill" :class="{ active: ctx.subtitleOptions.showSourceSearch }" @click="ctx.setSubtitleOption('showSourceSearch', !ctx.subtitleOptions.showSourceSearch)">
              来源搜索
            </button>
            <button type="button" class="subtitle-toggle-pill" :class="{ active: ctx.subtitleOptions.showWrittenFiles }" @click="ctx.setSubtitleOption('showWrittenFiles', !ctx.subtitleOptions.showWrittenFiles)">
              写入结果
            </button>
            <button type="button" class="subtitle-toggle-pill" :class="{ active: ctx.subtitleOptions.showDownloadedFiles }" @click="ctx.setSubtitleOption('showDownloadedFiles', !ctx.subtitleOptions.showDownloadedFiles)">
              下载进度
            </button>
            <button type="button" class="subtitle-toggle-pill" :class="{ active: ctx.subtitleOptions.showIssues }" @click="ctx.setSubtitleOption('showIssues', !ctx.subtitleOptions.showIssues)">
              问题项
            </button>
          </div>
        </section>
      </div>
    </template>

    <template v-else-if="mode === 'pairing'">
      <div class="subtitle-config-mode-title">配对助手</div>
      <div class="subtitle-config-mode-copy">顺序点选、配对数量和关键动作都集中在这里。</div>
      <div class="subtitle-option-stack">
        <div class="subtitle-help-card">
          <div class="subtitle-option-title">选中快照</div>
          <div class="subtitle-help-stats">
            <span class="subtitle-help-stat">
              <em>音频轨</em>
              <strong>{{ ctx.pairingAudioSelectedCount || 0 }}</strong>
            </span>
            <span class="subtitle-help-stat">
              <em>字幕轨</em>
              <strong>{{ ctx.pairingSubtitleSelectedCount || 0 }}</strong>
            </span>
            <span class="subtitle-help-stat">
              <em>配对组</em>
              <strong>{{ ctx.pairingPairCount || 0 }}</strong>
            </span>
          </div>
        </div>

        <div class="subtitle-help-card">
          <div class="subtitle-option-title">快捷动作</div>
          <div class="subtitle-card-tip">先点音频，再点字幕，生成顺序预配对。</div>
          <div class="subtitle-help-actions">
            <el-button size="small" plain :disabled="!ctx.canClearSequenceSelection" @click="ctx.clearSubtitleSequenceSelection">清空顺序</el-button>
            <el-button size="small" plain :disabled="!ctx.canClearManualPairs" @click="ctx.clearSubtitleManualPairs">清空配对</el-button>
          </div>
        </div>

        <div class="subtitle-help-card subtitle-help-card-danger">
          <div class="subtitle-danger-row">
            <div>
              <div class="subtitle-option-title">删除预审</div>
              <div class="subtitle-card-tip">已移出主流程，避免和配对动作混用。</div>
            </div>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!ctx.canOpenSubtitleInspectorFilterDeleteDialog"
              @click="ctx.openSubtitleInspectorFilterDeleteDialog"
            >
              执行
            </el-button>
          </div>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="subtitle-config-mode-title">文件工具</div>
      <div class="subtitle-config-mode-copy">搜索范围、选中规模和删除风险集中查看。</div>
      <div class="subtitle-option-stack">
        <div class="subtitle-help-card">
          <div class="subtitle-option-title">文件快照</div>
          <div class="subtitle-help-stats subtitle-help-stats-2">
            <span class="subtitle-help-stat">
              <em>已选</em>
              <strong>{{ ctx.treeSelectedCount || 0 }}</strong>
            </span>
            <span class="subtitle-help-stat">
              <em>可见</em>
              <strong>{{ ctx.treeVisibleCount || 0 }}</strong>
            </span>
          </div>
          <div class="subtitle-tree-search-line">
            <span class="subtitle-tree-search-label">搜索词</span>
            <span class="subtitle-tree-search-val">{{ ctx.treeSearchText || '—' }}</span>
          </div>
        </div>

        <div class="subtitle-help-card subtitle-help-card-danger">
          <div class="subtitle-option-title">删除风险</div>
          <div class="subtitle-card-tip">操作直接作用于字幕目录，批量前先确认范围。</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
defineProps({
  ctx: {
    type: Object,
    required: true
  },
  mode: {
    type: String,
    default: 'settings'
  }
})
</script>

<style scoped>
.subtitle-config-card {
  display: grid;
  gap: 12px;
}

.subtitle-config-card :deep(.el-switch) {
  --el-switch-on-color: #0f172a;
  --el-switch-off-color: #e2e8f0;
}

.subtitle-config-card :deep(.el-switch__core) {
  border-color: #e2e8f0 !important;
  box-shadow: none;
}

.subtitle-config-card :deep(.el-input-number) {
  width: 120px;
}

.subtitle-config-card :deep(.el-input-number .el-input__wrapper),
.subtitle-config-card :deep(.el-select__wrapper),
.subtitle-config-card :deep(.el-input__wrapper) {
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 0 0 1px #e2e8f0;
  transition: all 0.2s ease;
}

.subtitle-config-card :deep(.el-input-number .el-input__wrapper:hover),
.subtitle-config-card :deep(.el-select__wrapper:hover),
.subtitle-config-card :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #cbd5e1;
}

.subtitle-config-card :deep(.el-input-number .el-input__wrapper.is-focus),
.subtitle-config-card :deep(.el-select__wrapper.is-focused),
.subtitle-config-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1.5px #0f172a;
}

.subtitle-config-card :deep(.el-radio-group) {
  display: inline-flex;
  gap: 6px;
  flex-wrap: wrap;
}

.subtitle-config-card :deep(.el-radio-button__inner) {
  min-width: 118px;
  border-radius: 8px !important;
  border: 1px solid #e2e8f0 !important;
  background: #ffffff !important;
  color: #0f172a !important;
  box-shadow: none !important;
  padding: 7px 12px !important;
  font-size: 12px !important;
  font-weight: 500;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-config-card :deep(.el-radio-button__inner:hover) {
  border-color: #cbd5e1 !important;
  background: #f8fafc !important;
  transform: translateY(-1px);
}

.subtitle-config-card :deep(.el-radio-button:first-child .el-radio-button__inner),
.subtitle-config-card :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 8px !important;
}

.subtitle-config-card :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: #0f172a !important;
  border-color: #0f172a !important;
  color: #ffffff !important;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18) !important;
}

.subtitle-config-card :deep(.el-button) {
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-config-card :deep(.el-button:hover) {
  transform: translateY(-1px) scale(1.02);
}

.subtitle-config-card :deep(.el-button:active) {
  transform: scale(0.96);
}

.subtitle-config-mode-title {
  font-size: 14px;
  line-height: 1.2;
  font-weight: 600;
  color: #0f172a;
  letter-spacing: -0.015em;
}

.subtitle-config-mode-copy {
  font-size: 11px;
  line-height: 1.6;
  color: #64748b;
}

.subtitle-option-stack {
  display: grid;
  gap: 12px;
}

.subtitle-settings-block,
.subtitle-help-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.subtitle-help-card-danger {
  background: linear-gradient(180deg, #fef2f2 0%, #ffffff 100%);
  border-color: #fecaca;
}

.subtitle-block-head {
  display: grid;
  gap: 3px;
}

.subtitle-block-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #0f172a;
  text-transform: uppercase;
}

.subtitle-block-tip {
  font-size: 11px;
  line-height: 1.55;
  color: #64748b;
}

.subtitle-setting-list,
.subtitle-filter-list {
  display: grid;
  gap: 10px;
}

.subtitle-setting-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
}

.subtitle-setting-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.subtitle-setting-item:first-child {
  padding-top: 0;
}

.subtitle-setting-item-stack {
  grid-template-columns: 1fr;
  align-items: start;
}

.subtitle-setting-main {
  display: grid;
  gap: 3px;
}

.subtitle-option-title {
  font-size: 13px;
  font-weight: 500;
  color: #0f172a;
  letter-spacing: -0.005em;
}

.subtitle-option-title-sm {
  font-size: 12px;
}

.subtitle-card-tip {
  font-size: 11px;
  line-height: 1.6;
  color: #64748b;
}

.subtitle-filter-editor {
  display: grid;
  gap: 10px;
  margin-top: 2px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #f8fafc;
}

.subtitle-filter-editor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.subtitle-inline-btn {
  flex-shrink: 0;
}

.subtitle-filter-row {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-filter-row:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}

.subtitle-filter-row-top,
.subtitle-filter-row-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.subtitle-filter-target {
  min-width: 108px;
  max-width: 132px;
}

.subtitle-filter-empty {
  padding: 12px;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  background: #f8fafc;
  font-size: 11px;
  color: #64748b;
  text-align: center;
}

.subtitle-pill-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.subtitle-toggle-pill {
  min-height: 34px;
  padding: 7px 11px;
  border-radius: 8px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #0f172a;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-toggle-pill:hover {
  transform: translateY(-1px) scale(1.02);
  border-color: #cbd5e1;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}

.subtitle-toggle-pill.active {
  background: #0f172a;
  color: #ffffff;
  border-color: #0f172a;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.18);
}

.subtitle-help-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.subtitle-help-stats-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.subtitle-help-stat {
  display: grid;
  gap: 2px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.subtitle-help-stat:hover {
  border-color: #cbd5e1;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}

.subtitle-help-stat em {
  font-style: normal;
  font-size: 10px;
  font-weight: 500;
  color: #64748b;
  letter-spacing: 0.02em;
}

.subtitle-help-stat strong {
  font-size: 22px;
  line-height: 1;
  font-weight: 600;
  color: #0f172a;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.subtitle-help-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.subtitle-danger-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.subtitle-tree-search-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.subtitle-tree-search-label {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  color: #64748b;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.subtitle-tree-search-val {
  min-width: 0;
  font-size: 11px;
  font-weight: 500;
  color: #0f172a;
  word-break: break-all;
}

@media (max-width: 960px) {
  .subtitle-setting-item {
    grid-template-columns: 1fr;
    align-items: start;
  }

  .subtitle-help-stats,
  .subtitle-pill-grid {
    grid-template-columns: 1fr;
  }

  .subtitle-danger-row,
  .subtitle-filter-editor-head {
    flex-direction: column;
    align-items: stretch;
  }

  .subtitle-filter-target {
    min-width: 0;
    max-width: none;
  }
}
</style>
