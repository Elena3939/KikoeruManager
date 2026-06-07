<template>
  <section class="asmr-card">
    <header class="asmr-card-head">
      <div class="asmr-card-head-title">
        <Sparkles :size="14" :stroke-width="2.2" class="asmr-card-head-icon" />
        <div>
          <h2>增强下载工作台</h2>
          <p class="asmr-card-head-subtitle">手动输入 RJ 号直接查询并下载</p>
        </div>
      </div>
      <div class="asmr-card-head-actions">
        <button
          class="asmr-mini-btn"
          type="button"
          :disabled="planning"
          @click="$emit('query')"
        >
          <Search :size="12" :stroke-width="2.4" />
          {{ planning ? '查询中...' : '查询 RJ' }}
        </button>
        <button
          v-if="hasWorkbenchTasks"
          class="asmr-mini-btn"
          type="button"
          @click="$emit('open-workbench')"
        >
          <DownloadIcon :size="12" :stroke-width="2.4" />
          下载工作台
        </button>
      </div>
    </header>
    <div class="asmr-card-body">
      <el-input
        :model-value="input"
        type="textarea"
        :rows="3"
        placeholder="支持粘贴 RJ123456、RJ234567，空格 / 换行 / 逗号分隔"
        class="enhanced-rj-input"
        @update:model-value="$emit('update:input', $event)"
      />

      <Transition name="asmr-section">
        <div v-if="plans.length > 0" class="enhanced-plan-section">
          <div class="asmr-batch-toolbar">
            <div class="asmr-batch-toolbar-info">
              <span class="asmr-batch-toolbar-title">批量操作</span>
              <span class="lib-chip lib-chip-info">已选 {{ selectedRjcodes.length }} / {{ plans.length }}</span>
            </div>
            <div class="asmr-batch-toolbar-actions">
              <button class="asmr-mini-btn" type="button" @click="$emit('select-all')">全选</button>
              <button class="asmr-mini-btn" type="button" @click="$emit('clear-selection')">清空</button>
              <button
                class="asmr-mini-btn is-primary"
                type="button"
                :disabled="starting || selectedRjcodes.length === 0"
                @click="$emit('download-selected')"
              >
                <DownloadIcon :size="12" :stroke-width="2.4" />
                {{ starting ? '创建中...' : `下载选中 (${selectedRjcodes.length})` }}
              </button>
            </div>
          </div>

          <TransitionGroup
            tag="div"
            name="asmr-grid"
            class="enhanced-plan-grid"
          >
            <WorkCard
              v-for="(plan, idx) in plans"
              :key="plan.rjcode"
              :item="plan"
              :card-index="idx"
              :selected="selectedSet.has(plan.rjcode)"
              image-field="cover_url"
              code-field="rjcode"
              size="default"
              :show-release-badge="false"
              class="enhanced-plan-card"
              :style="{ '--asmr-grid-delay': `${Math.min(idx, 12) * 35}ms` }"
              @select="(p) => $emit('toggle-plan', p.rjcode)"
            >
              <template #cover-placeholder>
                <div class="enhanced-plan-cover-placeholder">
                  <DownloadIcon class="enhanced-plan-cover-icon" />
                </div>
              </template>
              <template #meta>
                <div class="enhanced-plan-meta">
                  <span class="enhanced-plan-meta-pill is-code">{{ plan.rjcode }}</span>
                  <span class="enhanced-plan-meta-pill is-downloadable">{{ plan.summary?.selectable_total || 0 }} 个可下载</span>
                </div>
              </template>
              <template #tags>
                <div class="enhanced-plan-tags">
                  <span class="enhanced-plan-tag is-primary">资源构成</span>
                  <span v-for="group in (plan.grouped_resources || []).slice(0, 3)" :key="group.group_key" class="enhanced-plan-tag is-soft">
                    {{ getResourceTypeLabel(group.resource_type) }} x{{ group.count }}
                  </span>
                  <span v-if="(plan.grouped_resources || []).length > 3" class="enhanced-plan-tag is-muted">
                    +{{ (plan.grouped_resources || []).length - 3 }}
                  </span>
                </div>
              </template>
              <template #actions><span /></template>
            </WorkCard>
          </TransitionGroup>
        </div>
      </Transition>
    </div>
  </section>
</template>

<script setup>
import { Download as DownloadIcon, Search, Sparkles } from 'lucide-vue-next'
import WorkCard from '../circle/WorkCard.vue'

defineProps({
  input: { type: String, default: '' },
  plans: { type: Array, default: () => [] },
  selectedRjcodes: { type: Array, default: () => [] },
  selectedSet: { type: Object, required: true },
  planning: { type: Boolean, default: false },
  starting: { type: Boolean, default: false },
  hasWorkbenchTasks: { type: Boolean, default: false },
  getResourceTypeLabel: { type: Function, required: true }
})

defineEmits([
  'update:input',
  'query',
  'open-workbench',
  'select-all',
  'clear-selection',
  'download-selected',
  'toggle-plan'
])
</script>

<style scoped>
.asmr-card {
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: var(--asmr-surface);
  border: 1px solid var(--asmr-border);
  box-shadow: var(--asmr-card-shadow);
  overflow: hidden;
}
.asmr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-bottom: 1px solid var(--asmr-border);
  background: var(--asmr-surface-soft);
}
.asmr-card-head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.asmr-card-head-title h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0;
  color: var(--asmr-text-strong);
}
.asmr-card-head-subtitle {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--asmr-text-muted);
  letter-spacing: 0.01em;
}
.asmr-card-head-icon {
  color: var(--asmr-accent);
  flex-shrink: 0;
}
.asmr-card-head-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.asmr-card-body {
  padding: 16px 18px;
}
.enhanced-rj-input {
  margin-bottom: 16px;
}
.enhanced-rj-input :deep(.el-textarea__inner) {
  background: var(--asmr-field-bg);
  border: 1px solid var(--asmr-border);
  box-shadow: none;
  color: var(--asmr-text-strong);
}
.enhanced-rj-input :deep(.el-textarea__inner::placeholder) {
  color: var(--asmr-field-placeholder);
}
.enhanced-rj-input :deep(.el-textarea__inner:hover),
.enhanced-rj-input :deep(.el-textarea__inner:focus) {
  background: var(--asmr-field-bg-focus);
  border-color: var(--asmr-border-strong);
  box-shadow: 0 0 0 3px var(--asmr-focus-ring);
}
.enhanced-plan-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.asmr-mini-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--asmr-border-strong);
  background: var(--asmr-surface);
  color: var(--asmr-text);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.15s ease, box-shadow 0.18s ease;
}
.asmr-mini-btn:hover:not(:disabled) {
  background: var(--asmr-surface-hover);
  border-color: var(--asmr-border-strong);
  color: var(--asmr-text-strong);
}
.asmr-mini-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.asmr-mini-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.asmr-mini-btn.is-primary {
  background: var(--asmr-primary-bg);
  color: var(--asmr-primary-text);
  border-color: transparent;
  box-shadow: var(--asmr-control-shadow);
}
.asmr-mini-btn.is-primary:hover:not(:disabled) {
  background: var(--asmr-primary-bg-hover);
  box-shadow: var(--asmr-control-shadow);
}
.asmr-batch-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--asmr-surface-soft);
  border: 1px solid var(--asmr-border);
}
.asmr-batch-toolbar-info,
.asmr-batch-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.asmr-batch-toolbar-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--asmr-text-strong);
}
.lib-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.lib-chip-info {
  background: var(--asmr-info-bg);
  color: var(--asmr-info-text);
  border: 1px solid var(--asmr-info-border);
}
.enhanced-plan-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
@media (min-width: 768px) {
  .enhanced-plan-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (min-width: 1280px) {
  .enhanced-plan-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.enhanced-plan-card {
  max-width: none;
  width: 100%;
  min-height: 0;
  height: auto;
}
.enhanced-plan-card :deep(.work-cover-wrapper) {
  height: clamp(148px, 18vw, 206px);
  aspect-ratio: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(circle at 50% 38%, rgba(255, 255, 255, 0.82), transparent 42%),
    var(--circle-work-cover-bg, linear-gradient(135deg, rgba(241, 245, 249, 0.96), rgba(248, 250, 252, 0.82)));
}
.enhanced-plan-card :deep(.work-cover) {
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center;
}
.enhanced-plan-card :deep(.work-card-body) {
  display: grid;
  grid-template-rows: minmax(34px, auto) auto auto;
  gap: 8px;
  min-height: 132px;
  padding: 10px 12px 12px;
}
.enhanced-plan-card :deep(.work-title) {
  font-size: 12.5px;
  line-height: 1.35;
  height: auto;
  min-height: calc(1.35em * 2);
  max-height: calc(1.35em * 2);
  word-break: break-all;
}
.enhanced-plan-card :deep(.work-rj),
.enhanced-plan-card :deep(.work-cv) {
  display: none;
}
.enhanced-plan-cover-placeholder {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: var(--asmr-info-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--asmr-info-border);
  box-shadow: var(--asmr-control-shadow);
}
.enhanced-plan-cover-icon {
  width: 20px;
  height: 20px;
  color: var(--asmr-info-text);
}
.enhanced-plan-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  min-width: 0;
}
.enhanced-plan-meta-pill,
.enhanced-plan-tag {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 650;
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.enhanced-plan-meta-pill.is-code {
  background: var(--asmr-chip-muted-bg);
  color: var(--asmr-chip-muted-text);
}
.enhanced-plan-meta-pill.is-downloadable {
  background: var(--asmr-success-bg);
  color: var(--asmr-success-text);
}
.enhanced-plan-tags {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  min-width: 0;
  max-height: 45px;
  overflow: hidden;
}
.enhanced-plan-tag.is-primary {
  background: var(--asmr-info-bg);
  color: var(--asmr-info-text);
}
.enhanced-plan-tag.is-soft {
  background: var(--asmr-chip-muted-bg);
  color: var(--asmr-chip-muted-text);
}
.enhanced-plan-tag.is-muted {
  background: var(--asmr-surface-muted);
  color: var(--asmr-text-muted);
}
.asmr-section-enter-active {
  transition:
    opacity 0.45s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1),
    max-height 0.5s cubic-bezier(0.22, 1, 0.36, 1);
  overflow: hidden;
}
.asmr-section-leave-active {
  transition:
    opacity 0.25s ease,
    transform 0.3s ease,
    max-height 0.35s cubic-bezier(0.4, 0, 0.6, 1);
  overflow: hidden;
}
.asmr-section-enter-from {
  opacity: 0;
  transform: translateY(-14px) scale(0.985);
}
.asmr-section-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.99);
}
.asmr-grid-enter-active {
  transition:
    opacity 0.45s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.55s cubic-bezier(0.34, 1.56, 0.64, 1);
  transition-delay: var(--asmr-grid-delay, 0ms);
}
.asmr-grid-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
  position: absolute;
}
.asmr-grid-enter-from {
  opacity: 0;
  transform: translateY(20px) scale(0.92);
}
.asmr-grid-leave-to {
  opacity: 0;
  transform: translateY(-10px) scale(0.95);
}
.asmr-grid-move {
  transition: transform 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}
@media (max-width: 640px) {
  .asmr-card {
    border-radius: 12px;
  }
  .asmr-card-head,
  .asmr-card-body {
    padding-left: 12px;
    padding-right: 12px;
  }
  .asmr-card-head-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }
  .asmr-card-head-actions > .asmr-mini-btn {
    justify-content: center;
    width: 100%;
  }
  .asmr-batch-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .asmr-batch-toolbar-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }
  .asmr-batch-toolbar-actions > .asmr-mini-btn {
    justify-content: center;
    width: 100%;
  }
  .asmr-batch-toolbar-actions > .asmr-mini-btn:nth-child(3) {
    grid-column: 1 / -1;
  }
  .enhanced-plan-grid {
    grid-template-columns: 1fr;
  }
  .enhanced-plan-card :deep(.work-cover-wrapper) {
    height: clamp(160px, 52vw, 220px);
  }
}
</style>
