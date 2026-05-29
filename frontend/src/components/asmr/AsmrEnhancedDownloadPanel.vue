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
                  <span class="enhanced-plan-meta-pill is-code">RJ {{ plan.rjcode }}</span>
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
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}
.asmr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  background: linear-gradient(180deg, #fbfcfe 0%, #f8fafc 100%);
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
  color: #0f172a;
}
.asmr-card-head-subtitle {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: #94a3b8;
  letter-spacing: 0.01em;
}
.asmr-card-head-icon {
  color: #2563eb;
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
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.15s ease, box-shadow 0.18s ease;
}
.asmr-mini-btn:hover:not(:disabled) {
  background: #f8fafc;
  border-color: rgba(15, 23, 42, 0.22);
  color: #0f172a;
}
.asmr-mini-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.asmr-mini-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.asmr-mini-btn.is-primary {
  background: linear-gradient(135deg, #111827, #1e293b);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.18);
}
.asmr-mini-btn.is-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, #1e293b, #334155);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.22);
}
.asmr-batch-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.06);
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
  color: #334155;
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
  background: rgba(224, 231, 255, 0.85);
  color: #4338ca;
  border: 1px solid rgba(165, 180, 252, 0.5);
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
}
.enhanced-plan-card :deep(.work-cover-wrapper) {
  height: 134px;
}
.enhanced-plan-card :deep(.work-card-body) {
  padding: 10px;
}
.enhanced-plan-card :deep(.work-title) {
  font-size: 12px;
  line-height: 1.35;
}
.enhanced-plan-card :deep(.work-rj) {
  display: none;
}
.enhanced-plan-cover-placeholder {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 10px 20px rgba(37, 99, 235, 0.22);
}
.enhanced-plan-cover-icon {
  width: 20px;
  height: 20px;
  color: #fff;
}
.enhanced-plan-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.enhanced-plan-meta-pill,
.enhanced-plan-tag {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 650;
  line-height: 1;
  white-space: nowrap;
}
.enhanced-plan-meta-pill.is-code {
  background: rgba(15, 23, 42, 0.06);
  color: #334155;
}
.enhanced-plan-meta-pill.is-downloadable {
  background: rgba(220, 252, 231, 0.8);
  color: #047857;
}
.enhanced-plan-tags {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.enhanced-plan-tag.is-primary {
  background: rgba(219, 234, 254, 0.9);
  color: #1d4ed8;
}
.enhanced-plan-tag.is-soft {
  background: rgba(241, 245, 249, 0.92);
  color: #475569;
}
.enhanced-plan-tag.is-muted {
  background: rgba(226, 232, 240, 0.7);
  color: #64748b;
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
}
</style>
