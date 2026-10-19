<template>
  <div class="download-resource-tree">
    <div v-if="!isArchive" class="tree-row plan-node-header flex items-center gap-2 px-2 py-2 rounded-md cursor-pointer" @click.stop="emit('toggle-root')">
      <ChevronRight v-if="plan.rootExpanded === false" :size="16" class="text-blue-400" />
      <ChevronDown v-else :size="16" class="text-blue-400" />
      <button v-if="!readonly && !isArchive" type="button" class="tree-checkbox size-4 shrink-0 rounded border" :class="allSelected ? 'tree-checkbox-on' : plan.selected_resource_count ? 'tree-checkbox-partial' : 'tree-checkbox-off'" aria-label="选择全部文件" @click.stop="emit('toggle-all')"><Check v-if="allSelected" :size="14" /><span v-else-if="plan.selected_resource_count" class="checkbox-minus" /></button>
      <Folder :size="20" class="tree-icon shrink-0" :style="iconStyle(LIBRARY_ENTRY_KIND_META.dir)" />
      <span class="tree-name min-w-0 flex-1 truncate text-sm font-medium">{{ plan.rjcode }} <span class="node-title-muted">{{ plan.title }}</span></span>
      <span class="tree-size text-xs shrink-0">{{ formatSize(plan.total_size_bytes) }}</span>
    </div>
    <div v-for="row in !isArchive && plan.rootExpanded === false ? [] : plan.flatRows" :key="row.id" class="tree-node">
      <div class="tree-row resource-file-row flex items-center gap-2 px-2 py-2 rounded-md"
        :class="{ 'tree-row-selected': !readonly && (row.checked || row.indeterminate), 'is-unavailable': row.resource?.complete === false }"
        :style="{ paddingLeft: `${isArchive ? 8 : (row.depth + 1) * 16 + 12}px` }"
        @click="row.type === 'dir' ? emit('toggle-expand', row) : !readonly && row.resource?.complete !== false && emit('toggle-row', row)">
        <button v-if="row.type === 'dir'" type="button" class="tree-expander" aria-label="展开目录" @click.stop="emit('toggle-expand', row)"><ChevronDown v-if="plan.expandedIds.has(row.id)" :size="16" /><ChevronRight v-else :size="16" /></button>
        <button v-if="!readonly" type="button" class="tree-checkbox size-4 shrink-0 rounded border"
          :class="row.checked ? 'tree-checkbox-on' : row.indeterminate ? 'tree-checkbox-partial' : 'tree-checkbox-off'"
          :disabled="row.resource?.complete === false" :aria-label="`选择 ${row.name}`" :aria-pressed="row.checked"
          @click.stop="emit('toggle-row', row)"><Check v-if="row.checked" :size="14" /><span v-else-if="row.indeterminate" class="checkbox-minus" /></button>
        <component :is="iconMeta(row).icon" :size="20" class="tree-icon shrink-0" :class="{ 'archive-package-icon': isArchive && row.type !== 'dir' }" :style="iconStyle(iconMeta(row))" />
        <div class="min-w-0 flex-1">
          <span class="tree-name block truncate text-sm font-medium" :title="row.name">{{ row.name }}</span>
          <span v-if="isArchive" class="resource-file-meta"><span class="version-tag">{{ row.resource.language_tag || '未知语言' }}</span> {{ row.resource.rjcode }} · {{ row.resource.files?.length || 0 }} 个文件{{ row.resource.complete ? '' : ' · 分卷不完整' }}</span>
        </div>
        <span class="tree-size text-xs shrink-0">{{ formatSize(row.size_bytes) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Check, ChevronDown, ChevronRight, Folder } from 'lucide-vue-next'
import { LIBRARY_ENTRY_KIND_META, libraryEntryMetaFor } from '../library/_libraryFileKind'

const props = defineProps({ plan: { type: Object, required: true }, readonly: Boolean })
const emit = defineEmits(['toggle-root', 'toggle-all', 'toggle-expand', 'toggle-row'])
const isArchive = computed(() => props.plan.source_provider === 'imoutoheaven')
const allSelected = computed(() => props.plan.selectable_resources.length > 0 && props.plan.selected_resource_count === props.plan.selectable_resources.length)
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
