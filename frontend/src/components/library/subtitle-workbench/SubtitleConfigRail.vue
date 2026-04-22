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
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  display: grid;
  gap: 12px;
}

.subtitle-config-card :deep(.el-switch) {
  --el-switch-on-color: #1677d8;
  --el-switch-off-color: #dbe3ee;
}

.subtitle-config-card :deep(.el-switch__core) {
  border-color: #d6deea !important;
  box-shadow: none;
}

.subtitle-config-card :deep(.el-input-number) {
  width: 120px;
}

.subtitle-config-card :deep(.el-input-number .el-input__wrapper),
.subtitle-config-card :deep(.el-select__wrapper),
.subtitle-config-card :deep(.el-input__wrapper) {
  border-radius: 12px;
  background: #fff;
  box-shadow: inset 0 0 0 1px #d8e1ec;
}

.subtitle-config-card :deep(.el-input-number .el-input__wrapper.is-focus),
.subtitle-config-card :deep(.el-select__wrapper.is-focused),
.subtitle-config-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: inset 0 0 0 1px #7ea8d8, 0 0 0 3px rgba(114, 157, 208, 0.16);
}

.subtitle-config-card :deep(.el-radio-group) {
  display: inline-flex;
  gap: 8px;
  flex-wrap: wrap;
}

.subtitle-config-card :deep(.el-radio-button__inner) {
  min-width: 118px;
  border-radius: 12px !important;
  border: 1px solid #d7e0ea !important;
  background: #fff !important;
  color: #44576d !important;
  box-shadow: none !important;
  padding: 8px 12px !important;
  font-size: 12px !important;
  font-weight: 700;
}

.subtitle-config-card :deep(.el-radio-button:first-child .el-radio-button__inner),
.subtitle-config-card :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 12px !important;
}

.subtitle-config-card :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: linear-gradient(180deg, #1c2b43 0%, #101b2e 100%) !important;
  border-color: #142238 !important;
  color: #ffffff !important;
  box-shadow: 0 12px 24px rgba(16, 27, 46, 0.22) !important;
}

.subtitle-config-card :deep(.el-button) {
  border-radius: 14px;
  font-size: 12px;
  font-weight: 800;
  transition: all 0.3s var(--ease-spring);
}

.subtitle-config-card :deep(.el-button:hover) {
  transform: translateY(-2px) scale(1.02);
}

.subtitle-config-card :deep(.el-button:active) {
  transform: scale(0.96);
}

.subtitle-config-mode-title {
  font-size: 15px;
  line-height: 1.1;
  font-weight: 900;
  color: #132335;
  letter-spacing: -0.03em;
}

.subtitle-config-mode-copy {
  font-size: 11px;
  line-height: 1.6;
  color: #70839a;
}

.subtitle-option-stack {
  display: grid;
  gap: 14px;
}

.subtitle-settings-block,
.subtitle-help-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e1e8f0;
  border-radius: 18px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
}

.subtitle-help-card-danger {
  border-color: #f0d6d5;
  background: linear-gradient(180deg, #fffafa 0%, #ffffff 100%);
}

.subtitle-block-head {
  display: grid;
  gap: 3px;
}

.subtitle-block-title {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.03em;
  color: #5f738b;
}

.subtitle-block-tip {
  font-size: 11px;
  line-height: 1.55;
  color: #8a9aad;
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
  padding: 12px 0;
  border-bottom: 1px solid #edf2f7;
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
  font-weight: 800;
  color: #213244;
  letter-spacing: -0.02em;
}

.subtitle-option-title-sm {
  font-size: 12px;
}

.subtitle-card-tip {
  font-size: 11px;
  line-height: 1.6;
  color: #74869d;
}

.subtitle-filter-editor {
  display: grid;
  gap: 10px;
  margin-top: 2px;
  padding: 12px;
  border: 1px solid #e4ebf4;
  border-radius: 16px;
  background: #f8fbfe;
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
  border: 1px solid #e1e8f0;
  border-radius: 14px;
  background: #fff;
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
  border: 1px dashed #d6e0ea;
  border-radius: 14px;
  background: #fff;
  font-size: 11px;
  color: #7b8da2;
}

.subtitle-pill-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.subtitle-toggle-pill {
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid #d8e1ec;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%);
  color: #41546b;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.3s var(--ease-spring);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.subtitle-toggle-pill:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: #c4d2e0;
  background: #ffffff;
  color: #12273d;
  box-shadow: 0 10px 18px rgba(15, 23, 42, 0.06);
}

.subtitle-toggle-pill.active {
  border-color: #142238;
  background: linear-gradient(180deg, #1c2b43 0%, #101b2e 100%);
  color: #ffffff;
  box-shadow: 0 12px 24px rgba(16, 27, 46, 0.22);
}

.subtitle-help-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.subtitle-help-stats-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.subtitle-help-stat {
  display: grid;
  gap: 2px;
  padding: 12px;
  border: 1px solid #e1e8f0;
  border-radius: 16px;
  background: #fbfcfe;
}

.subtitle-help-stat em {
  font-style: normal;
  font-size: 10px;
  font-weight: 700;
  color: #7b8ba0;
}

.subtitle-help-stat strong {
  font-size: 26px;
  line-height: 1;
  font-weight: 900;
  color: #132335;
  letter-spacing: -0.04em;
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
  border-radius: 12px;
  background: #f6f9fc;
  border: 1px solid #e1e8f0;
}

.subtitle-tree-search-label {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  color: #92a2b4;
}

.subtitle-tree-search-val {
  min-width: 0;
  font-size: 11px;
  font-weight: 700;
  color: #52667d;
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
