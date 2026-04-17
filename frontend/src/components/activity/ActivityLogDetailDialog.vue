<template>
  <el-dialog
    :model-value="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal activity-detail-dialog"
    align-center
    modal-class="custom-preview-overlay activity-detail-overlay"
    @update:model-value="emit('close')"
  >
      <div
      v-if="row"
      class="window panel-enter glass-shell activity-window"
    >
      <div class="window-header flex items-center justify-between px-8 py-6">
        <div class="activity-header-main">
          <div class="activity-header-icon">
            <component :is="statusConfig.icon" :size="20" :stroke-width="2.6" />
          </div>
          <div class="min-w-0">
            <h1 class="title activity-title">{{ humanAction(row) }}</h1>
            <div class="activity-header-badge-row">
              <span class="activity-review-badge">Review Required</span>
            </div>
          </div>
        </div>
        <button
          type="button"
          class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700"
          @click="emit('close')"
        >
          <X :size="20" :stroke-width="2" />
        </button>
      </div>

      <div class="top-meta-shell px-8 pb-2">
        <div class="summary-meta-grid summary-meta-grid-top">
          <div class="meta-pill-card">
            <div class="meta-pill-icon">
              <component :is="categoryConfig.icon" :size="14" :stroke-width="2.5" />
            </div>
            <div>
              <div class="meta-pill-label">Category</div>
              <div class="meta-pill-value">{{ row.category }}</div>
            </div>
          </div>
          <div class="meta-pill-card">
            <div class="meta-pill-icon">
              <component :is="statusConfig.icon" :size="14" :stroke-width="2.5" />
            </div>
            <div>
              <div class="meta-pill-label">Status</div>
              <div class="meta-pill-value">{{ statusConfig.label }}</div>
            </div>
          </div>
          <div class="meta-pill-card">
            <div class="meta-pill-icon">
              <Clock3 :size="14" :stroke-width="2.5" />
            </div>
            <div>
              <div class="meta-pill-label">Time</div>
              <div class="meta-pill-value">{{ formatDateTime(row.created_at) }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="activity-scroll-shell no-scrollbar">
        <div class="content-stack flex flex-col gap-6 px-8 py-2">
            <section class="glass-panel glass-card summary-panel rounded-2xl p-5">
          <div class="space-y-4">
            <section class="space-y-4">
              <div class="summary-callout">
                <div class="summary-callout-text">
                  {{ summaryText || '—' }}
                </div>
              </div>

              <div class="summary-meta-grid">
                <div class="meta-pill-card">
                  <div class="meta-pill-label">分类</div>
                  <div class="meta-pill-value">{{ row.category_label || '—' }}</div>
                </div>
                <div class="meta-pill-card">
                  <div class="meta-pill-label">时间</div>
                  <div class="meta-pill-value">{{ formatDateTime(row.created_at) }}</div>
                </div>
                <div class="info-block summary-span-2">
                  <div class="info-label">源路径</div>
                  <div class="info-value mono">{{ row.source_path || '—' }}</div>
                </div>
                <div class="info-block">
                  <div class="info-label">任务 ID</div>
                  <div class="info-value mono">{{ row.task_id || '—' }}</div>
                </div>
                <div class="info-block">
                  <div class="info-label">RJ</div>
                  <div class="info-value mono">{{ displayRjcode(row) }}</div>
                </div>
              </div>

              <div class="summary-tag-row">
                <span
                  v-for="tag in rowTags"
                  :key="`${row.id}-${tag}`"
                  class="tab-chip px-2.5 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center border"
                  :class="tagClass(tag)"
                >
                  {{ tag }}
                </span>
                <span v-if="isRerun" class="tab-chip px-2.5 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center border tab-chip-warn">
                  重新爬取
                </span>
                <span
                  v-if="finalStatusLabel"
                  class="tab-chip px-2.5 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center border"
                  :class="finalStatusChipClass"
                >
                  {{ finalStatusLabel }}
                </span>
                <span v-if="isRecoveredFailure" class="tab-chip px-2.5 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center border tab-chip-success">
                  已修复
                </span>
                <span class="detail-rj-chip">{{ displayRjcode(row) }}</span>
              </div>
            </section>

            <section v-if="pathCompare" class="space-y-4">
              <div class="section-head compact-head">
                <h2>{{ pathCompare.title }}</h2>
                <p>{{ pathCompare.reason || pathCompareDefaultReason }}</p>
              </div>
              <div class="path-board">
                <div class="path-card">
                  <div class="path-card-label">OLD PATH</div>
                  <div class="path-card-value mono">{{ pathCompare.beforePath || '—' }}</div>
                </div>
                <div class="path-arrow">→</div>
                <div class="path-card">
                  <div class="path-card-label">NEW PATH</div>
                  <div class="path-card-value mono">{{ pathCompare.afterPath || '—' }}</div>
                </div>
              </div>
            </section>

            <section v-if="$slots.sidebar" class="space-y-4">
              <slot name="sidebar" />
            </section>
          </div>
            </section>

            <section class="glass-panel glass-card tree-panel flex flex-col overflow-hidden">
              <div class="detail-main-head">
                <div>
                  <div class="detail-main-title">任务详情</div>
                  <div class="detail-main-desc">按任务类型展开更细的业务信息。字幕链路、删除预审、社团补全、上传同步等会显示不同模块。</div>
                </div>
              </div>
              <div class="detail-section-body">
                <slot />
              </div>
            </section>
        </div>
      </div>

      <div class="footer-row px-8 py-6 flex items-center justify-between">
        <div></div>
        <div class="footer-actions flex items-center gap-3">
          <button type="button" class="secondary-cta interactive-button px-10 h-11 rounded-xl font-bold" @click="emit('close')">关闭</button>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { Clock3, X } from 'lucide-vue-next'

const props = defineProps({
  visible: { type: Boolean, default: false },
  row: { type: Object, default: null },
  getCategoryConfig: { type: Function, required: true },
  getStatusConfig: { type: Function, required: true },
  humanAction: { type: Function, required: true },
  formatDateTime: { type: Function, required: true },
  displayRjcode: { type: Function, required: true },
  rowTags: { type: Array, default: () => [] },
  actionTagClass: { type: Function, required: true },
  isRerun: { type: Boolean, default: false },
  finalStatusLabel: { type: String, default: '' },
  finalStatusClass: { type: String, default: '' },
  isRecoveredFailure: { type: Boolean, default: false },
  pathCompare: { type: Object, default: null },
  pathCompareReasonClass: { type: String, default: '' },
  pathCompareDefaultReason: { type: String, default: '' },
  summaryText: { type: String, default: '' },
})

const emit = defineEmits(['close'])

const categoryConfig = computed(() => props.getCategoryConfig(props.row?.category))
const statusConfig = computed(() => props.getStatusConfig(props.row?.status))

const statusChipClass = computed(() => {
  if (props.row?.status === 'success') return 'tab-chip-success'
  if (props.row?.status === 'partial_success') return 'tab-chip-warn'
  if (props.row?.status === 'failed') return 'tab-chip-danger'
  return 'tab-chip-idle'
})

const finalStatusChipClass = computed(() => {
  if (props.finalStatusClass === 'is-final-success') return 'tab-chip-success'
  if (props.finalStatusClass === 'is-final-failed') return 'tab-chip-danger'
  return 'tab-chip-warn'
})

function tagClass(tag) {
  const actionClass = props.actionTagClass(props.row, tag)
  if (actionClass === 'is-api-rename') return 'tab-chip-blue'
  if (actionClass === 'is-manual-rename') return 'tab-chip-violet'
  if (actionClass === 'is-delete') return 'tab-chip-danger'
  if (actionClass === 'is-updated') return 'tab-chip-warn'
  if (actionClass === 'is-unchanged') return 'tab-chip-idle'
  if (tag === '未命中') return 'tab-chip-idle'
  return 'tab-chip-success'
}
</script>

<style scoped>
.activity-detail-dialog :deep(.el-dialog) {
  width: min(1840px, 92vw);
  height: 80vh;
  margin: 0;
  background: transparent;
  box-shadow: none;
}

.activity-detail-dialog :deep(.el-dialog__header) {
  display: none;
}

.activity-detail-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.activity-window {
  width: 100%;
  max-width: 1840px;
  height: 80vh;
  min-height: 800px;
  max-height: 84vh;
  border-radius: 28px;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.custom-preview-modal :deep(.el-dialog__header) { display: none; }
.glass-shell { background: rgba(255,255,255,.7); backdrop-filter: blur(8px); border: 1px solid rgba(15,23,42,.06); }
.tabs-row { min-height: 44px; }
.tabs-scroll { min-height: 34px; padding-top: 2px; padding-bottom: 2px; overflow-y: visible; }
.tabs-actions { min-height: 34px; padding-top: 2px; }
.tab-chip { transition: all .15s ease; color: #475569; }

.mask-edge-right {
  -webkit-mask-image: linear-gradient(to right, black calc(100% - 16px), transparent 100%);
  mask-image: linear-gradient(to right, black calc(100% - 16px), transparent 100%);
}

.tab-chip-active { background: #1e293b; border-color: #1e293b; color: #f8fafc; box-shadow: 0 8px 18px rgba(15, 23, 42, 0.16); }
.tab-chip-success { background: #ecfdf5; border-color: #a7f3d0; color: #047857; }
.tab-chip-warn { background: #fffbeb; border-color: #fde68a; color: #b45309; }
.tab-chip-danger { background: #fff1f2; border-color: #fecdd3; color: #be123c; }
.tab-chip-idle { background: rgba(255,255,255,.92); border-color: #cbd5e1; color: #475569; }
.tab-chip-blue { background: #eff6ff; border-color: #bfdbfe; color: #2563eb; }
.tab-chip-violet { background: #f5f3ff; border-color: #ddd6fe; color: #7c3aed; }
.primary-cta { background: #111827; transition: background-color .18s ease, box-shadow .18s ease, transform .18s ease; box-shadow: 0 12px 24px rgba(15, 23, 42, 0.16); }
.secondary-cta { background: rgba(17,24,39,.06); color: #334155; transition: background-color .18s ease, color .18s ease, transform .18s ease; }
.secondary-cta:hover { background: rgba(15,23,42,.1); color: #0f172a; transform: translateY(-1px); }

.activity-header-main {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}

.activity-header-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 999px;
  background: #eef5ff;
  color: #3b82f6;
  flex: 0 0 auto;
}

.activity-title {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  line-height: 1.1;
  color: #0f172a;
}

.activity-header-badge-row {
  margin-top: 6px;
}

.activity-review-badge {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 8px;
  border-radius: 999px;
  background: #eef5ff;
  color: #2563eb;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.detail-rj-chip {
  display: inline-flex;
  align-items: center;
  height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  background: #0f172a;
  color: #f8fafc;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.activity-scroll-shell {
  overflow-y: auto;
  overflow-x: hidden;
  min-height: 0;
  padding: 0 32px 20px;
  scrollbar-width: thin;
  scrollbar-color: rgba(203, 213, 225, 0.95) rgba(241, 245, 249, 0.92);
}

.top-meta-shell {
  padding-top: 2px;
}

.activity-scroll-shell::-webkit-scrollbar {
  width: 10px;
}

.activity-scroll-shell::-webkit-scrollbar-track {
  background: rgba(241, 245, 249, 0.92);
  border-radius: 999px;
}

.activity-scroll-shell::-webkit-scrollbar-thumb {
  background: rgba(203, 213, 225, 0.96);
  border-radius: 999px;
  border: 2px solid rgba(241, 245, 249, 0.92);
}

.section-head h2,
.detail-main-title {
  margin: 0;
  font-size: 16px;
  font-weight: 800;
  color: #0f172a;
}

.detail-main-desc {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: #64748b;
}

.detail-main-head {
  padding: 16px 18px 10px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.8);
  background: rgba(255, 255, 255, 0.88);
}

.info-block {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(226, 232, 240, 0.82);
}

.info-label,
.mini-stat-label,
.path-card-label {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #94a3b8;
}

.info-value,
.mini-stat-value {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.55;
  color: #0f172a;
  word-break: break-word;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.content-stack {
  min-height: min-content;
}

.summary-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.summary-meta-grid-top {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: 6px;
}

.meta-pill-card {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 56px;
  padding: 0 18px;
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.94);
  border: 1px solid rgba(226, 232, 240, 0.85);
}

.meta-pill-label {
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #94a3b8;
}

.meta-pill-value {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.meta-pill-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.9);
  color: #94a3b8;
  flex: 0 0 auto;
}

.summary-callout {
  position: relative;
  padding: 18px 20px 18px 22px;
  border-radius: 24px;
  background: rgba(248, 250, 252, 0.94);
  border: 1px solid rgba(226, 232, 240, 0.88);
}

.summary-callout::before {
  content: '';
  position: absolute;
  left: 0;
  top: 16px;
  bottom: 16px;
  width: 3px;
  border-radius: 999px;
  background: #3b82f6;
}

.summary-callout-text {
  font-size: 15px;
  line-height: 1.7;
  color: #334155;
}

.summary-span-2 {
  grid-column: span 2;
}

.mini-stat {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.92);
  border: 1px solid rgba(226, 232, 240, 0.82);
}

.path-board {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}

.path-card {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(226, 232, 240, 0.82);
}

.path-card-value {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.55;
  color: #0f172a;
  word-break: break-all;
}

.path-arrow {
  color: #94a3b8;
  font-size: 24px;
  font-weight: 700;
}

.detail-section-body {
  padding: 14px;
}

@media (max-width: 1100px) {
  .activity-detail-dialog :deep(.el-dialog) {
    width: 92vw;
    height: 90vh;
  }

  .activity-window {
    height: 90vh;
    min-height: 0;
    max-height: 90vh;
  }

  .path-board {
    grid-template-columns: 1fr;
  }

  .path-arrow {
    display: none;
  }

  .summary-grid,
  .summary-meta-grid,
  .summary-meta-grid-top {
    grid-template-columns: 1fr;
  }

  .activity-scroll-shell {
    padding-left: 18px;
    padding-right: 18px;
    padding-bottom: 18px;
  }
}

@media (max-width: 720px) {
  .summary-span-2 {
    grid-column: span 1;
  }
}
</style>
