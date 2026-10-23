<template>
  <div v-if="plans" class="download-resource-tree download-resource-forest">
    <div v-for="entry in plans" :key="`${entry.canonical_rjcode}:${entry.rjcode}`" class="resource-tree-entry">
      <DownloadResourceTree :plan="entry" :readonly="readonly"
        @toggle-root="emit('toggle-root', entry)" @toggle-all="emit('toggle-all', entry)"
        @toggle-expand="emit('toggle-expand', { plan: entry, row: $event })"
        @toggle-row="emit('toggle-row', { plan: entry, row: $event })">
        <template #root-action>
          <button v-if="entry.source_options?.length > 1" type="button" class="source-switch-link shrink-0" @click.stop="emit('change-source', entry)">点击更换来源</button>
        </template>
      </DownloadResourceTree>
    </div>
  </div>
  <template v-else>
  <div class="download-resource-tree">
    <div v-if="!isArchive && !hideRoot" class="tree-row plan-node-header flex items-center gap-2 px-2 py-2 rounded-md cursor-pointer" @click.stop="emit('toggle-root')">
      <ChevronRight v-if="plan.rootExpanded === false" :size="16" class="text-blue-400" />
      <ChevronDown v-else :size="16" class="text-blue-400" />
      <slot name="root-select" />
      <button v-if="!readonly" type="button" class="tree-checkbox size-4 shrink-0 rounded border"
        :class="sourceSelected && allSelected ? 'tree-checkbox-on' : sourceSelected && plan.selected_resource_count ? 'tree-checkbox-partial' : 'tree-checkbox-off'"
        :aria-label="`选择 ${plan.rjcode} 的全部文件`" @click.stop="emit('toggle-all')">
        <Check v-if="sourceSelected && allSelected" :size="14" /><span v-else-if="sourceSelected && plan.selected_resource_count" class="checkbox-minus" />
      </button>
      <Folder :size="20" class="tree-icon shrink-0" :style="iconStyle(LIBRARY_ENTRY_KIND_META.dir)" />
      <span class="tree-name min-w-0 flex-1 truncate text-sm font-medium">{{ plan.rjcode }}</span>
      <span v-if="plan.language_label" class="version-tag">{{ languageLabel(plan.language_label) }}</span>
      <span class="tree-size text-xs shrink-0">{{ formatSize(plan.total_size_bytes) }}</span>
      <slot name="root-action" />
    </div>
    <div v-for="row in !isArchive && plan.rootExpanded === false ? [] : plan.flatRows" :key="row.id" class="tree-node">
      <div class="tree-row resource-file-row flex items-center gap-2 px-2 py-2 rounded-md"
        :class="{ 'tree-row-selected': !readonly && sourceSelected && (row.checked || row.indeterminate), 'is-unavailable': row.resource?.complete === false }"
        :style="{ paddingLeft: `${(row.depth + (isArchive || hideRoot ? 0 : 1)) * 16 + 8}px` }"
        @click="row.type === 'dir' ? emit('toggle-expand', row) : !readonly && row.resource?.complete !== false && emit('toggle-row', row)">
        <button v-if="row.type === 'dir'" type="button" class="tree-expander" aria-label="展开目录" @click.stop="emit('toggle-expand', row)"><ChevronDown v-if="plan.expandedIds.has(row.id)" :size="16" /><ChevronRight v-else :size="16" /></button>
        <slot v-if="isArchive && row.depth === 0" name="root-select" :row="row" />
        <button v-if="!readonly" type="button" class="tree-checkbox size-4 shrink-0 rounded border"
          :class="sourceSelected && row.checked ? 'tree-checkbox-on' : sourceSelected && row.indeterminate ? 'tree-checkbox-partial' : 'tree-checkbox-off'"
          :disabled="row.resource?.complete === false" :aria-label="`选择 ${row.name}`" :aria-pressed="sourceSelected && row.checked"
          @click.stop="emit('toggle-row', row)"><Check v-if="sourceSelected && row.checked" :size="14" /><span v-else-if="sourceSelected && row.indeterminate" class="checkbox-minus" /></button>
        <component :is="iconMeta(row).icon" :size="20" class="tree-icon shrink-0" :class="{ 'archive-package-icon': isArchive && row.type !== 'dir' }" :style="iconStyle(iconMeta(row))" />
        <div class="min-w-0 flex-1">
          <span class="tree-name block truncate text-sm font-medium" :title="row.name">{{ row.name }}</span>
          <span v-if="isArchive" class="resource-file-meta"><span class="version-tag">{{ archiveLanguage(row) }}</span> {{ row.resource.rjcode }} · {{ row.resource.files?.length || 0 }} 个文件{{ row.resource.complete ? '' : ' · 分卷不完整' }}</span>
          <slot name="row-detail" :row="row" />
        </div>
        <slot name="row-action" :row="row"><span class="tree-size text-xs shrink-0">{{ formatSize(row.size_bytes) }}</span></slot>
        <slot v-if="isArchive && row.depth === 0" name="root-action" />
      </div>
    </div>
  </div>
  </template>
</template>

<script setup>
import { computed } from 'vue'
import { Check, ChevronDown, ChevronRight, Folder } from 'lucide-vue-next'
import { LIBRARY_ENTRY_KIND_META, libraryEntryMetaFor } from '../library/_libraryFileKind'

const props = defineProps({ plan: { type: Object, default: null }, plans: { type: Array, default: null }, readonly: Boolean, hideRoot: Boolean, sourceSelected: { type: Boolean, default: true } })
const emit = defineEmits(['toggle-root', 'toggle-all', 'toggle-expand', 'toggle-row', 'change-source'])
const isArchive = computed(() => props.plan?.source_provider === 'imoutoheaven')
const allSelected = computed(() => props.plan?.selectable_resources?.length > 0
  && props.plan.selected_resource_count === props.plan.selectable_resources.length)
function archiveLanguage(row) {
  const label = (row.resource.rjcode === props.plan.rjcode && props.plan.language_label)
    || row.resource.language_tag || row.resource.language || '未知语言'
  return languageLabel(label)
}
function languageLabel(label) {
  return ({ CHI_HANS: '简体中文', CHI_HANT: '繁体中文', JPN: '日语', JA_JP: '日语', KO_KR: '韩语', KOR: '韩语', ENG: '英语', EN_US: '英语' })[String(label).toUpperCase()] || label
}
function iconMeta(row) {
  if (isArchive.value && row.type !== 'dir') return LIBRARY_ENTRY_KIND_META.archive
  return libraryEntryMetaFor(row)
}
function iconStyle(meta) {
  return { color: meta.color, fill: meta.fillIcon ? `${meta.color}26` : 'none' }
}
function formatSize(bytes) {
  const size = Number(bytes || 0)
  if (!size) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), 4)
  return `${(size / 1024 ** index).toFixed(index ? 2 : 0)} ${units[index]}`
}
</script>
