<script setup>
import { computed, inject } from 'vue'
import { ListChecks, Subtitles } from 'lucide-vue-next'
import StatefulButton from '../ui/stateful-button.vue'
const props = defineProps({ item: { type: Object, required: true }, compact: Boolean })
const repair = inject('circleSubtitleRepair', null)
const tasks = computed(() => repair?.tasks(props.item) || [])
const label = computed(() => {
  const list = tasks.value
  if (list.some(task => task.awaiting_manual_match || task.status === 'waiting_manual')) return '待配对'
  if (list.some(task => task.status === 'processing')) return '爬取中'
  if (list.some(task => ['pending', 'paused', 'waiting_retry'].includes(task.status))) return '已加入'
  if (list.some(task => task.status === 'failed')) return '失败'
  if (list.some(task => task.skipped_reason)) return '已跳过'
  if (list.some(task => task.status === 'cancelled')) return '已取消'
  return list.length ? '查看任务' : ''
})
const evidence = computed(() => (props.item.subtitle_repair_sources || []).map(source =>
  `${source.label} ${source.provider || ''} ${source.rjcode || ''}${source.is_ai ? ' · AI' : ''}`).join('\n'))
</script>

<template>
  <div v-if="repair && (item.subtitle_repairable || tasks.length)" class="circle-subtitle-actions" :class="{ 'is-compact': compact }" @click.stop @dblclick.stop @pointerdown.stop>
    <StatefulButton v-if="item.subtitle_repairable" unstyled class="circle-subtitle-action" :title="evidence" :disabled="repair.busy()" :show-default-icons="false" @click="() => repair.create(item)">
      <Subtitles :size="12" /><span class="circle-subtitle-action-text">可补配</span>
    </StatefulButton>
    <button v-if="tasks.length" type="button" class="circle-subtitle-action is-task" :title="`查看字幕任务（${tasks.length}）`" @click="repair.view(item)">
      <ListChecks :size="12" /><span class="circle-subtitle-action-text">{{ label }}</span>
    </button>
  </div>
</template>

<style scoped>
.circle-subtitle-actions { display: flex; flex-wrap: nowrap; gap: 4px; min-width: 0; flex-shrink: 0; font-size: 11px; line-height: 1; }
.circle-subtitle-action { display: inline-flex; align-items: center; justify-content: center; gap: 4px; min-height: 24px; border: 1px solid #b8dfcf; border-radius: 5px; padding: 2px 6px; color: #087658; background: #eaf7ef; font-size: 11px; line-height: 1; cursor: pointer; transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.circle-subtitle-action.is-task { color: #4658a2; background: #eff2ff; border-color: #cdd4ef; }
.circle-subtitle-action:hover:not(:disabled) { transform: translateY(-2px) scale(1.02); }
.circle-subtitle-action:hover svg { transform: rotate(6deg); }
.circle-subtitle-action:active:not(:disabled) { transform: scale(.96); }
.circle-subtitle-action:disabled { opacity: .6; cursor: wait; }
.circle-subtitle-action { flex-shrink: 0; white-space: nowrap; }
.circle-subtitle-action :deep(.stateful-button__content),
.circle-subtitle-action :deep(.stateful-button__label),
.circle-subtitle-action .circle-subtitle-action-text { display: inline-flex; align-items: center; gap: 4px; font-size: inherit; line-height: inherit; font-weight: 500; letter-spacing: 0; }
.circle-subtitle-actions.is-compact .circle-subtitle-action { min-height: 22px; padding: 1px 4px; font-size: 10px; }
.circle-subtitle-actions.is-compact { font-size: 10px; }
.circle-subtitle-actions.is-compact svg { width: 10px; height: 10px; }
.circle-subtitle-action:focus, .circle-subtitle-action:focus-visible { outline: none; box-shadow: none; }
:global(html.kikoerumanager-dark .circle-subtitle-action) { color: #81d5b6; background: var(--km-dark-surface, #202525); border-color: var(--km-dark-border, #394446); }
:global(html.kikoerumanager-dark .circle-subtitle-action.is-task) { color: #c2caf8; background: var(--km-dark-surface, #202525); border-color: var(--km-dark-border, #394446); }
</style>
