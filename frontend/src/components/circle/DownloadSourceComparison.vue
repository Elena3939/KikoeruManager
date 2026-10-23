<template>
  <section class="site-source-comparison">
    <div class="site-comparison-heading">
      <strong>选择下载来源</strong>
      <span class="site-heading-hint">按站点查看文件，可整批选择或为作品单独选择</span>
      <AppDropdown class="site-picker" :model-value="activeSite?.id || modelValue"
        :options="sites.map(site => ({ value: site.id, label: site.label }))" :width="136" :menu-min-width="136"
        @update:model-value="emit('update:modelValue', $event)" />
    </div>
    <div class="site-comparison-columns">
      <Transition name="source-panel" mode="out-in">
      <section v-if="activeSite" :key="activeSite.id" class="site-comparison-column">
        <template v-for="site in [activeSite]" :key="site.id">
        <header class="site-comparison-header">
          <div class="site-heading-copy">
            <strong>{{ site.label }}</strong>
            <span>已选 {{ site.selectedWorks }}/{{ site.entries.length }} 部作品 · {{ site.selectedCount }}/{{ site.count }} {{ site.id === 'imoutoheaven' ? '个压缩包' : '个文件' }} · {{ formatSize(site.selectedBytes) }}/{{ formatSize(site.bytes) }}</span>
          </div>
          <button type="button" class="site-select-button" :aria-pressed="isSiteSelected(site)" @click="chooseSite(site)">{{ isSiteSelected(site) ? '取消全选' : '全选' }}</button>
        </header>
        <slot name="toolbar" />
        <div class="site-comparison-files">
          <DownloadResourceTree v-for="entry in site.entries" :key="`${entry.plan.canonical_rjcode}:${entry.plan.rjcode}`"
            :plan="entry.option" :readonly="!entry.selected && site.id === 'imoutoheaven'" :source-selected="entry.selected"
            @toggle-root="emit('toggle-root', entry.option)" @toggle-expand="emit('toggle-expand', entry.option, $event)"
            @toggle-all="entry.selected ? emit('toggle-all', entry.plan) : emit('choose-source', entry.plan, entry.option)" @toggle-row="emit('choose-row', entry.plan, entry.option, $event)">
            <template #root-select="{ row }">
              <button v-if="!entry.selected && site.id === 'imoutoheaven'" type="button" class="tree-checkbox tree-checkbox-off size-4 shrink-0 rounded border"
                :disabled="row?.resource?.complete === false"
                :aria-label="`为 ${entry.plan.rjcode} 选择 ${site.label}`" title="选择此来源"
                @click.stop="emit('choose-source', entry.plan, entry.option, row?.resource)" />
            </template>
          </DownloadResourceTree>
        </div>
        </template>
      </section>
      </Transition>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import DownloadResourceTree from './DownloadResourceTree.vue'
import AppDropdown from '../common/AppDropdown.vue'
const props = defineProps({ plans: { type: Array, required: true }, modelValue: { type: String, default: 'asmr.one' } })
const emit = defineEmits(['update:modelValue', 'select-site', 'choose-row', 'choose-source', 'toggle-root', 'toggle-expand', 'toggle-all', 'toggle-row'])
const sites = computed(() => [
  { id: 'asmr.one', label: 'asmr.one' }, { id: 'imoutoheaven', label: 'YAAS' },
].map(site => {
  const entries = props.plans.flatMap(plan => (plan.sourcePreviews?.length ? plan.sourcePreviews : [plan])
    .filter(option => (option.source_provider || 'asmr.one') === site.id)
    .map(option => {
      const selected = !plan.source_selection_required
        && (plan.source_provider || 'asmr.one') === (option.source_provider || 'asmr.one')
      return { plan, option: selected ? plan : option, selected }
    }))
  const selectedEntries = entries.filter(({ selected }) => selected)
  return { ...site, entries,
    selectedWorks: selectedEntries.filter(({ option }) => option.selected_resource_count > 0).length,
    selectedCount: selectedEntries.reduce((sum, { option }) => sum + Number(option.selected_resource_count || 0), 0),
    selectedBytes: selectedEntries.reduce((sum, { option }) => sum + Number(option.selected_size_bytes || 0), 0),
    count: entries.reduce((sum, { option }) => sum + option.selectable_resources.length, 0),
    bytes: entries.reduce((sum, { option }) => sum + Number(option.total_size_bytes || 0), 0) }
}).filter(site => site.entries.length))
const activeSite = computed(() => sites.value.find(site => site.id === props.modelValue) || sites.value[0])
function isSiteSelected(site) {
  return site.entries.length > 0 && site.entries.every(({ plan, selected }) => selected && (
    site.id === 'imoutoheaven' ? plan.selected_resource_count > 0
      : plan.selectable_resources.filter(item => item.complete !== false).every(item => item.selected)))
}
function chooseSite(site) {
  emit('select-site', site.entries, !isSiteSelected(site))
}
function formatSize(bytes) {
  const size = Number(bytes || 0)
  if (!size) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), 4)
  return `${(size / 1024 ** index).toFixed(index ? 2 : 0)} ${units[index]}`
}
</script>

<style scoped>
.site-source-comparison { display: flex; flex-direction: column; flex: 1; min-height: 0; gap: 16px; }
.site-comparison-heading { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 2px 8px; }
.site-comparison-heading strong { font-size: 14px; }
.site-comparison-heading span { font-size: 12px; color: #64748b; }
.site-comparison-columns { display: flex; gap: 16px; flex: 1; min-height: 0; overflow: hidden; }
.site-comparison-column { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; }
.site-comparison-header { display: flex; align-items: center; gap: 12px; padding: 10px 8px; }
.site-heading-copy { display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 0; }
.site-heading-copy strong { font-size: 16px; }
.site-heading-copy > span { font-size: 11px; color: #64748b; }
.site-comparison-files { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; scrollbar-width: none; overscroll-behavior: contain; padding: 0 0 8px; }
.site-comparison-files::-webkit-scrollbar { display: none; }
.site-comparison-files :deep(.resource-file-row .tree-name) { white-space: normal; overflow-wrap: anywhere; }

.site-comparison-header { flex-shrink: 0; }
.site-select-button { border: 1px solid #a1a1aa66; background: #71717a12; color: inherit; border-radius: 8px; padding: 8px 10px; font-size: 12px; white-space: nowrap; }
button { cursor: pointer; transition: all .3s cubic-bezier(.34, 1.56, .64, 1); }
button:hover { transform: translateY(-2px) scale(1.02); }
button:active { transform: scale(.96); }
button:focus, button:focus-visible { outline: none; box-shadow: none; }
:global(html.kikoerumanager-dark .site-comparison-heading span),
:global(html.kikoerumanager-dark .site-heading-copy > span) { color: var(--km-dark-text-muted); }
:global(html.kikoerumanager-dark .site-select-button) { background: #ffffff0d; border-color: #ffffff33; color: #e4e4e7; }
.site-picker { margin-left: auto; flex-shrink: 0; }
.site-picker :deep(.app-dd-trigger) { height: 32px; min-height: 32px; padding: 0 10px; color: inherit; background: #71717a12; border-color: #a1a1aa66; box-shadow: none; }
.source-panel-enter-active, .source-panel-leave-active { transition: opacity 140ms ease, transform 140ms ease; }
.source-panel-enter-from { opacity: 0; transform: translateY(5px); }
.source-panel-leave-to { opacity: 0; transform: translateY(-3px); }
@media (prefers-reduced-motion: reduce) { .source-panel-enter-active, .source-panel-leave-active { transition: none; } }
@media (max-width: 640px) {
  .site-comparison-header { padding: 10px 12px; }
  .site-comparison-heading { gap: 8px; }
  .site-heading-hint { display: none; }
}
</style>
