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
.repair-target-group { padding: 10px 0; border-bottom: 1px solid var(--km-dark-border, #dce3e8); }
.repair-target-group h3 { font-size: 14px; margin: 0 0 8px; }
.repair-target { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; }
.repair-target label { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1; }
.repair-target-text { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.repair-target-text small { overflow-wrap: anywhere; opacity: .8; }
.repair-target input { flex: 0 0 auto; width: 16px; height: 16px; accent-color: #18886e; }
.repair-target input:focus { outline: none; box-shadow: none; }
.repair-target-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
.page-head-btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; padding: 6px 12px; border: 1px solid var(--el-border-color); border-radius: 6px; background: var(--el-fill-color-blank); color: var(--el-text-color-primary); font-size: 13px; cursor: pointer; transition: all .3s cubic-bezier(.34,1.56,.64,1); }
.page-head-btn.is-primary { color: var(--el-color-primary); border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.page-head-btn:disabled { opacity: .5; cursor: not-allowed; }
.page-head-btn:hover:not(:disabled) { transform: translateY(-2px) scale(1.02); }
.page-head-btn:active:not(:disabled) { transform: scale(.96); }
.page-head-btn:hover:not(:disabled) :deep(svg) { transform: rotate(6deg); }
.page-head-btn :deep(.stateful-button__label) { display: inline-flex; align-items: center; gap: 6px; }
.repair-target button { flex-shrink: 0; transition: all .3s cubic-bezier(.34,1.56,.64,1); }
.repair-target button:hover { transform: translateY(-2px) scale(1.02); }
.repair-target button:active { transform: scale(.96); }
:global(html.kikoerumanager-dark .repair-targets) { color: var(--km-dark-text, #dce5ed); }
@media (max-width: 640px) {
  :global(.circle-subtitle-targets-dialog.el-dialog) { display: flex; flex-direction: column; }
  :global(.circle-subtitle-targets-dialog .el-dialog__body) { flex: 1; min-height: 0; height: auto !important; }
  .repair-targets { max-height: none; overflow: visible; }
  .repair-target { flex-wrap: wrap; }
  .repair-target label { flex-basis: 100%; }
}
</style>
