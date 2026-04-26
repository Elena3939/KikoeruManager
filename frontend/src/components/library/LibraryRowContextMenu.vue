<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="panelRef"
      data-library-row-menu="1"
      class="menu-panel fixed z-[2400] w-[180px] overflow-hidden rounded-md border border-slate-300/90 bg-white p-1 shadow-[0_10px_24px_rgba(15,23,42,0.18)]"
      :style="{ left: `${x}px`, top: `${y}px` }"
      @click.stop
      @contextmenu.stop
    >
        <div class="mb-1 flex items-center gap-1.5 border-b border-slate-200 px-2 py-1 text-slate-500">
          <MoreHorizontal :size="12" :stroke-width="2.2" class="text-slate-400" />
          <span class="min-w-0 truncate text-[11px]" :title="row?.name || ''">{{ row?.name || '操作菜单' }}</span>
        </div>

        <button
          v-if="showLocate"
          type="button"
          class="menu-item"
          @click="emit('action', 'locate')"
        >
          <MapPin :size="14" :stroke-width="2.2" class="menu-item-icon text-blue-600" />
          <span>定位</span>
        </button>

        <button
          v-if="showOpen"
          type="button"
          class="menu-item"
          @click="emit('action', 'open')"
        >
          <FolderOpen :size="14" :stroke-width="2.2" class="menu-item-icon text-emerald-600" />
          <span>打开</span>
        </button>

        <button
          v-if="showOpenDirect"
          type="button"
          class="menu-item"
          @click="emit('action', 'open_direct')"
        >
          <ExternalLink :size="14" :stroke-width="2.2" class="menu-item-icon text-indigo-600" />
          <span>直接打开</span>
        </button>

        <div class="my-1 border-t border-slate-200"></div>

        <button
          type="button"
          class="menu-item"
          :disabled="disableRename"
          @click="emit('action', 'rename')"
        >
          <Pencil :size="14" :stroke-width="2.2" class="menu-item-icon text-violet-600" />
          <span>重命名</span>
        </button>

        <button
          type="button"
          class="menu-item"
          :class="{ 'bg-amber-50/70': apiBatchTarget }"
          :disabled="disableApiRename"
          @click="emit('action', 'api_rename')"
        >
          <Sparkles :size="14" :stroke-width="2.2" class="menu-item-icon text-amber-600" />
          <span>API 重命名</span>
          <span v-if="apiRenameRunning" class="ml-auto text-[10px] text-amber-700">运行中</span>
        </button>

        <button
          type="button"
          class="menu-item"
          :disabled="disableSubtitle"
          @click="emit('action', 'subtitle')"
        >
          <Captions :size="14" :stroke-width="2.2" class="menu-item-icon text-emerald-700" />
          <span>识别抓字幕</span>
        </button>

        <button
          type="button"
          class="menu-item"
          :disabled="disableManage"
          @click="emit('action', 'manage')"
        >
          <FolderCog :size="14" :stroke-width="2.2" class="menu-item-icon text-cyan-700" />
          <span>文件管理</span>
        </button>

        <div class="my-1 border-t border-slate-200"></div>

        <button
          type="button"
          class="menu-item menu-item-danger"
          :disabled="disableDelete"
          @click="emit('action', 'delete')"
        >
          <Trash2 :size="14" :stroke-width="2.2" class="menu-item-icon text-rose-600" />
          <span>删除</span>
        </button>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Captions, ExternalLink, FolderCog, FolderOpen, MapPin, MoreHorizontal, Pencil, Sparkles, Trash2 } from 'lucide-vue-next'

const props = defineProps({
  visible: { type: Boolean, default: false },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  row: { type: Object, default: null },
  showLocate: { type: Boolean, default: false },
  showOpen: { type: Boolean, default: false },
  showOpenDirect: { type: Boolean, default: false },
  disableRename: { type: Boolean, default: false },
  disableApiRename: { type: Boolean, default: false },
  apiRenameRunning: { type: Boolean, default: false },
  apiBatchTarget: { type: Boolean, default: false },
  disableSubtitle: { type: Boolean, default: false },
  disableManage: { type: Boolean, default: false },
  disableDelete: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'action'])

const panelRef = ref(null)

function handleOutsidePointerDown (event) {
  if (!props.visible) return
  if (panelRef.value && !panelRef.value.contains(event.target)) emit('close')
}

function handleOutsideContextMenu (event) {
  if (!props.visible) return
  if (panelRef.value && !panelRef.value.contains(event.target)) emit('close')
}

function handleWindowScroll () {
  if (!props.visible) return
  emit('close')
}

function bindGlobalListeners () {
  document.addEventListener('mousedown', handleOutsidePointerDown, true)
  document.addEventListener('click', handleOutsidePointerDown, true)
  document.addEventListener('contextmenu', handleOutsideContextMenu, true)
  window.addEventListener('scroll', handleWindowScroll, true)
}

function unbindGlobalListeners () {
  document.removeEventListener('mousedown', handleOutsidePointerDown, true)
  document.removeEventListener('click', handleOutsidePointerDown, true)
  document.removeEventListener('contextmenu', handleOutsideContextMenu, true)
  window.removeEventListener('scroll', handleWindowScroll, true)
}

watch(() => props.visible, visible => {
  if (visible) {
    nextTick(() => {
      unbindGlobalListeners()
      bindGlobalListeners()
    })
    return
  }
  unbindGlobalListeners()
})

onBeforeUnmount(() => {
  unbindGlobalListeners()
})
</script>

<style scoped>
.menu-item {
  width: 100%;
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 7px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #334155;
  font-size: 12px;
  font-weight: 500;
  text-align: left;
  transition: background-color 0.16s ease, color 0.16s ease;
  cursor: pointer;
}

.menu-item:hover:not(:disabled) {
  background: #f1f5f9;
  color: #0f172a;
}

.menu-item-icon {
  transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.menu-item:hover:not(:disabled) .menu-item-icon {
  transform: translateY(-1px) scale(1.05);
}

.menu-item:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.menu-item-danger:hover:not(:disabled) {
  background: #ffe4e6;
  color: #be123c;
}

.menu-panel {
  animation: menu-enter 0.16s cubic-bezier(0.34, 1.56, 0.64, 1);
  transform-origin: top left;
}

@keyframes menu-enter {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
</style>
