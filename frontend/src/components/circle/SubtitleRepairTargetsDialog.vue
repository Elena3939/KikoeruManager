<script setup>
import { Subtitles, ListChecks } from 'lucide-vue-next'
import StatefulButton from '../ui/stateful-button.vue'
defineProps({ model: { type: Object, required: true } })
</script>

<template>
  <el-dialog v-model="model.visible.value" :title="model.viewOnly.value ? '字幕任务' : '选择原作位置'" width="720px" class="mobile-full-dialog circle-subtitle-targets-dialog" :close-on-click-modal="false">
    <div class="repair-targets">
      <section v-for="group in model.groups.value" :key="group.canonical_rjcode" class="repair-target-group">
        <h3>{{ group.canonical_rjcode }}</h3>
        <p v-if="group.reason">{{ group.reason }}</p>
        <div v-for="target in group.targets" :key="model.keyOf(target)" class="repair-target">
          <label>
            <input v-if="!model.viewOnly.value" v-model="model.selected.value" type="checkbox" :value="`${group.canonical_rjcode}:${model.keyOf(target)}`" :disabled="!target.eligible || Boolean(target.task && (target.task.status !== 'completed' || target.task.awaiting_manual_match))" />
            <span class="repair-target-text"><strong>{{ target.library_name || target.library_id }}</strong><small>{{ target.folder_path }}</small><small v-if="!model.viewOnly.value">{{ target.subtitle_count ? `已有 ${target.subtitle_count} 个字幕` : target.reason || '无字幕' }} · {{ target.audio_count }} 个音频</small></span>
          </label>
          <button v-if="target.task" type="button" class="page-head-btn" @click="model.openTask(target.task)"><ListChecks :size="14" />{{ model.statusLabel(target.task) }} · 查看</button>
        </div>
      </section>
    </div>
    <template #footer>
      <div class="repair-target-footer">
      <button type="button" class="page-head-btn" @click="model.visible.value = false">关闭</button>
      <StatefulButton v-if="!model.viewOnly.value" unstyled class="page-head-btn is-primary" :show-default-icons="false" :disabled="!model.canConfirm.value" @click="model.confirm"><Subtitles :size="14" />创建字幕任务</StatefulButton>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.repair-targets { max-height: 60vh; overflow: auto; }
.repair-target-group { padding: 12px 0; border-bottom: 1px solid var(--circle-border-soft, #e2e8f0); }
.repair-target-group:first-child { padding-top: 0; }
.repair-target-group:last-child { border-bottom: 0; }
.repair-target-group h3 { margin: 0 0 8px; color: var(--circle-text-strong, #111827); font-size: 14px; line-height: 1.35; }
.repair-target-group > p { margin: 0 0 8px; color: var(--circle-text-muted, #64748b); font-size: 12px; line-height: 1.5; }
.repair-target { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border: 1px solid var(--circle-border-soft, #e2e8f0); border-radius: 8px; background: var(--circle-surface-soft, #f8fafc); }
.repair-target + .repair-target { margin-top: 8px; }
.repair-target label { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1; }
.repair-target-text { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.repair-target-text strong { color: var(--circle-text, #334155); font-size: 13px; line-height: 1.35; }
.repair-target-text small { overflow-wrap: anywhere; color: var(--circle-text-muted, #64748b); font-size: 11px; line-height: 1.35; }
.repair-target input { flex: 0 0 auto; width: 16px; height: 16px; accent-color: var(--circle-tag-success, #059669); }
.repair-target input:focus { outline: none; box-shadow: none; }
.repair-target-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
.page-head-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; padding: 6px 12px; border: 1px solid var(--circle-border-strong, #cbd5e1); border-radius: 6px; background: var(--circle-surface, #fff); color: var(--circle-text, #334155); font-size: 13px; cursor: pointer; transition: all .3s cubic-bezier(.34,1.56,.64,1); }
.page-head-btn.is-primary { color: var(--circle-tag-primary, #2563eb); border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 45%, transparent); background: color-mix(in srgb, var(--circle-tag-primary-soft, #eff6ff) 78%, var(--circle-surface, #fff)); }
.page-head-btn:disabled { opacity: .5; cursor: not-allowed; }
.page-head-btn:hover:not(:disabled) { transform: translateY(-2px) scale(1.02); border-color: var(--circle-primary, #2563eb); }
.page-head-btn:active:not(:disabled) { transform: scale(.96); }
.page-head-btn:hover:not(:disabled) :deep(svg) { transform: rotate(6deg); }
.page-head-btn :deep(.stateful-button__label) { display: inline-flex; align-items: center; gap: 6px; }
.repair-target button { flex-shrink: 0; transition: all .3s cubic-bezier(.34,1.56,.64,1); }
.repair-target button:hover { transform: translateY(-2px) scale(1.02); }
.repair-target button:active { transform: scale(.96); }
:global(.circle-subtitle-targets-dialog.el-dialog) {
  --circle-surface: #fff;
  --circle-surface-soft: #f8fafc;
  --circle-border-soft: #e2e8f0;
  --circle-border-strong: #cbd5e1;
  --circle-text: #334155;
  --circle-text-strong: #111827;
  --circle-text-muted: #64748b;
  --circle-primary: #2563eb;
  --circle-tag-primary: #2563eb;
  --circle-tag-primary-soft: #eff6ff;
  --circle-tag-success: #059669;
  border: 1px solid var(--circle-border-soft);
  border-radius: 12px;
  background: var(--circle-surface);
  color: var(--circle-text);
  box-shadow: 0 18px 48px rgb(15 23 42 / 16%);
}
:global(.circle-subtitle-targets-dialog .el-dialog__header) { margin-right: 0; padding: 18px 20px 14px; border-bottom: 1px solid var(--circle-border-soft); }
:global(.circle-subtitle-targets-dialog .el-dialog__title) { color: var(--circle-text-strong); font-size: 16px; font-weight: 700; }
:global(.circle-subtitle-targets-dialog .el-dialog__headerbtn) { top: 15px; right: 16px; }
:global(.circle-subtitle-targets-dialog .el-dialog__body) { padding: 16px 20px; background: var(--circle-surface); }
:global(.circle-subtitle-targets-dialog .el-dialog__footer) { padding: 12px 20px 16px; border-top: 1px solid var(--circle-border-soft); background: var(--circle-surface); }
:global(html.kikoerumanager-dark .circle-subtitle-targets-dialog.el-dialog),
:global(body.kikoerumanager-dark .circle-subtitle-targets-dialog.el-dialog) {
  --circle-surface: #17191d;
  --circle-surface-soft: #202226;
  --circle-border-soft: rgba(255, 255, 255, 0.10);
  --circle-border-strong: rgba(148, 163, 184, 0.36);
  --circle-text: rgba(244, 244, 245, 0.88);
  --circle-text-strong: #fff;
  --circle-text-muted: rgba(212, 212, 216, 0.68);
  --circle-primary: #d4d4d8;
  --circle-tag-primary: #60a5fa;
  --circle-tag-primary-soft: rgba(59, 130, 246, 0.13);
  --circle-tag-success: #34d399;
  border-color: var(--circle-border-soft);
  box-shadow: 0 18px 48px rgb(0 0 0 / 42%);
}
:global(html.kikoerumanager-dark .circle-subtitle-targets-dialog .el-dialog__header),
:global(html.kikoerumanager-dark .circle-subtitle-targets-dialog .el-dialog__body),
:global(html.kikoerumanager-dark .circle-subtitle-targets-dialog .el-dialog__footer),
:global(body.kikoerumanager-dark .circle-subtitle-targets-dialog .el-dialog__header),
:global(body.kikoerumanager-dark .circle-subtitle-targets-dialog .el-dialog__body),
:global(body.kikoerumanager-dark .circle-subtitle-targets-dialog .el-dialog__footer) { background: var(--circle-surface); border-color: var(--circle-border-soft); }
:global(html.kikoerumanager-dark .circle-subtitle-targets-dialog .el-dialog__close),
:global(body.kikoerumanager-dark .circle-subtitle-targets-dialog .el-dialog__close) { color: var(--circle-text-muted); }
:global(html.kikoerumanager-dark .circle-subtitle-targets-dialog .repair-target),
:global(body.kikoerumanager-dark .circle-subtitle-targets-dialog .repair-target) { background: var(--circle-surface-soft); }
@media (max-width: 640px) {
  :global(.circle-subtitle-targets-dialog.el-dialog) { display: flex; flex-direction: column; }
  :global(.circle-subtitle-targets-dialog .el-dialog__body) { flex: 1; min-height: 0; height: auto !important; }
  .repair-targets { max-height: none; overflow: visible; }
  .repair-target { flex-wrap: wrap; }
  .repair-target label { flex-basis: 100%; }
}
</style>
