<template>
  <el-dialog
    :model-value="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal activity-detail-dialog"
    :class="{ 'is-expanded': expanded }"
    align-center
    modal-class="custom-preview-overlay activity-detail-overlay"
    @update:model-value="handleDialogModelValueChange"
  >
      <div
      v-if="row"
      class="window panel-enter glass-shell activity-window"
      :class="{ 'is-expanded': expanded }"
    >
      <div class="window-header flex items-center justify-between px-8 py-6">
        <div class="activity-header-main">
          <div class="activity-header-icon" :class="headerIconClass">
            <component :is="statusConfig.icon" :size="20" :stroke-width="2.6" />
          </div>
          <div class="min-w-0">
            <h1 class="title activity-title">{{ humanAction(row) }}</h1>
            <div class="activity-header-badge-row">
              <span class="activity-review-badge">Review Required</span>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-1.5">
          <button
            type="button"
            class="interactive-chip inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-100/70 transition-colors"
            :title="expanded ? '还原大小' : '放大窗口'"
            @click="toggleExpanded"
          >
            <component :is="expanded ? Minimize2 : Maximize2" :size="18" :stroke-width="2" />
          </button>
          <button
            type="button"
            class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700"
            @click="emit('close')"
          >
            <X :size="20" :stroke-width="2" />
          </button>
        </div>
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
            <div class="meta-pill-icon" :class="statusMetaIconClass">
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
import { computed, ref, watch } from 'vue'
import { Clock3, Maximize2, Minimize2, X } from 'lucide-vue-next'

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
})

const emit = defineEmits(['close'])

// 详情弹窗放大态：用户点击右上角的放大按钮把窗口拉到接近全屏，
// 切换详情记录或关闭后自动还原，避免下一次打开时仍是放大态。
const expanded = ref(false)

function toggleExpanded() {
  expanded.value = !expanded.value
}

watch(() => props.visible, (next) => {
  if (!next) expanded.value = false
})

watch(() => props.row?.id, () => {
  expanded.value = false
})

function handleDialogModelValueChange(nextVisible) {
  if (nextVisible === false) emit('close')
}

const categoryConfig = computed(() => props.getCategoryConfig(props.row?.category))
const statusConfig = computed(() => props.getStatusConfig(props.row?.status))

const headerIconClass = computed(() => {
  if (props.row?.status === 'failed') return 'is-danger'
  if (props.row?.status === 'partial_success') return 'is-warn'
  if (props.row?.status === 'success') return 'is-success'
  return 'is-idle'
})

const statusMetaIconClass = computed(() => {
  if (props.row?.status === 'failed') return 'is-danger'
  if (props.row?.status === 'partial_success') return 'is-warn'
  if (props.row?.status === 'success') return 'is-success'
  return 'is-idle'
})

</script>

<style scoped>
.activity-detail-dialog :deep(.el-dialog) {
  width: min(1840px, 92vw);
  height: 80vh;
  margin: 0;
  background: transparent;
  box-shadow: none;
  transition: width 0.24s ease, height 0.24s ease;
}

/* 放大态：接近全屏，给用户更宽的查看区域 */
.activity-detail-dialog.is-expanded :deep(.el-dialog) {
  width: 98vw;
  height: 96vh;
  max-width: none;
}

.activity-detail-dialog :deep(.el-dialog__header) {
  display: none;
}

.activity-detail-dialog :deep(.el-dialog__body) {
  padding: 0;
  height: 100%;
}

.activity-window {
  width: 100%;
  max-width: 1840px;
  height: 80vh;
  min-height: 800px;
  max-height: 84vh;
  transition: max-width 0.24s ease, height 0.24s ease, max-height 0.24s ease;
  border-radius: 28px;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  overflow: hidden;
}

/* 放大态：和外层 .el-dialog 同步拉到 96vh，避免出现 dialog 比 window 大、四周留空 */
.activity-window.is-expanded {
  max-width: none;
  height: 96vh;
  min-height: 0;
  max-height: 96vh;
  border-radius: 20px;
}

.custom-preview-modal :deep(.el-dialog__header) { display: none; }
.glass-shell { background: rgba(255,255,255,.7); backdrop-filter: blur(8px); border: 1px solid rgba(15,23,42,.06); }
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

.activity-header-icon.is-success {
  background: #ecfdf5;
  color: #059669;
}

.activity-header-icon.is-warn {
  background: #fffbeb;
  color: #d97706;
}

.activity-header-icon.is-danger {
  background: #fff1f2;
  color: #e11d48;
}

.activity-header-icon.is-idle {
  background: #eef5ff;
  color: #3b82f6;
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

.meta-pill-icon.is-success {
  background: rgba(236, 253, 245, 0.98);
  color: #059669;
  box-shadow: inset 0 0 0 1px rgba(167, 243, 208, 0.9);
}

.meta-pill-icon.is-warn {
  background: rgba(255, 251, 235, 0.98);
  color: #d97706;
  box-shadow: inset 0 0 0 1px rgba(253, 230, 138, 0.9);
}

.meta-pill-icon.is-danger {
  background: rgba(255, 241, 242, 0.98);
  color: #e11d48;
  box-shadow: inset 0 0 0 1px rgba(254, 205, 211, 0.95);
}

.meta-pill-icon.is-idle {
  background: rgba(255, 255, 255, 0.92);
  color: #94a3b8;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.9);
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
}

/* ============================================================
 * ≤640 全屏化覆盖
 * 桌面端零改动：仅 @media 内覆盖
 * 痛点：自己定义的 .activity-detail-dialog :deep(.el-dialog) 优先级
 *      高于全局 .custom-preview-modal.el-dialog 的 ≤640 全屏规则，
 *      导致移动端仍然是 92vw 弹窗而非全屏。
 * 解法：在自身 scoped 内补一份 ≤640 全屏，保持优先级链一致。
 * ============================================================ */
@media (max-width: 640px) {
  .activity-detail-dialog :deep(.el-dialog) {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    margin: 0 !important;
    border-radius: 0 !important;
  }
  .activity-detail-dialog :deep(.el-dialog__body) {
    height: 100dvh !important;
    max-height: 100dvh !important;
    padding: 0 !important;
    overflow: hidden !important;
  }
  .activity-window {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    min-height: 0 !important;
    border-radius: 0 !important;
    overflow: hidden !important;
    display: flex !important;
    flex-direction: column !important;
  }
  /* 内部任意 wrapper 解锁固定 min-width，避免横向溢出 */
  .activity-window > *,
  .activity-window .summary-meta-grid,
  .activity-window .summary-meta-grid-top,
  .activity-window .meta-pill-card {
    min-width: 0 !important;
    max-width: 100% !important;
  }
  /* 横向溢出文本（trace id / 长 path / 长 RJ）强制 word-break */
  .activity-window {
    word-break: break-all;
  }
  /* window-header / top-meta-shell 默认 px-8 (32px) 太宽，移动端收紧 */
  .activity-window .window-header {
    padding-left: 14px !important;
    padding-right: 14px !important;
    padding-top: 14px !important;
    padding-bottom: 10px !important;
  }
  .activity-window .top-meta-shell {
    padding-left: 14px !important;
    padding-right: 14px !important;
  }
  .activity-scroll-shell {
    padding-left: 14px !important;
    padding-right: 14px !important;
    padding-bottom: 16px !important;
  }
  /* 顶栏 close + maximize 两个圆形按钮在窄屏紧凑：size-10 → size-9 */
  .activity-window .interactive-chip {
    width: 36px !important;
    height: 36px !important;
  }
  /* 大标题字号收紧 */
  .activity-window .activity-title {
    font-size: 16px !important;
    line-height: 1.3 !important;
  }
}
</style>
