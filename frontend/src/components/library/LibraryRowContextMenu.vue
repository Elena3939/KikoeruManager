<template>
  <Teleport to="body">
    <div
      v-show="visible"
      ref="panelRef"
      data-library-row-menu="1"
      class="menu-panel fixed z-[2400] w-[200px] overflow-hidden rounded-[10px] border border-slate-200 bg-white p-1.5"
      :style="{ left: `${x}px`, top: `${y}px` }"
      @click.stop
      @contextmenu.stop
    >
        <div class="menu-header flex items-center px-2 py-1.5">
          <span class="min-w-0 truncate text-[11px] font-semibold tracking-tight text-slate-700" :title="batchMode ? `已选 ${selectedCount} 项` : (row?.name || '')">{{ batchMode ? `批量操作 · ${selectedCount} 项` : (row?.name || '操作菜单') }}</span>
        </div>

        <button
          v-if="showLocate"
          type="button"
          class="menu-item"
          :disabled="batchMode"
          @click="emit('action', 'locate')"
        >
          <MapPin :size="14" :stroke-width="2.2" class="menu-item-icon text-blue-600" />
          <span>定位</span>
        </button>

        <button
          v-if="showView"
          type="button"
          class="menu-item"
          :disabled="batchMode"
          @click="emit('action', 'view')"
        >
          <Eye :size="14" :stroke-width="2.2" class="menu-item-icon text-orange-600" />
          <span>观看</span>
        </button>

        <button
          v-if="showOpen"
          type="button"
          class="menu-item"
          :disabled="batchMode"
          @click="emit('action', 'open')"
        >
          <FolderOpen :size="14" :stroke-width="2.2" class="menu-item-icon text-emerald-600" />
          <span>打开</span>
        </button>

        <button
          v-if="showOpenDirect"
          type="button"
          class="menu-item"
          :disabled="batchMode"
          @click="emit('action', 'open_direct')"
        >
          <ExternalLink :size="14" :stroke-width="2.2" class="menu-item-icon text-indigo-600" />
          <span>直接打开</span>
        </button>

        <button
          type="button"
          class="menu-item"
          :disabled="batchMode"
          @click="emit('action', 'copy_name')"
        >
          <Copy :size="14" :stroke-width="2.2" class="menu-item-icon text-slate-500" />
          <span>复制文件名</span>
        </button>

        <div class="my-1 border-t border-slate-200"></div>

        <button
          type="button"
          class="menu-item"
          :disabled="batchMode || disableRename"
          @click="emit('action', 'rename')"
        >
          <Pencil :size="14" :stroke-width="2.2" class="menu-item-icon text-violet-600" />
          <span>重命名</span>
        </button>

        <button
          v-if="showMove"
          type="button"
          class="menu-item"
          :disabled="disableMove"
          @click="emit('action', 'move')"
        >
          <FolderInput :size="14" :stroke-width="2.2" class="menu-item-icon text-sky-600" />
          <span>{{ batchMode ? '批量移动到...' : '移动到...' }}</span>
        </button>

        <button
          v-if="showUpload"
          type="button"
          class="menu-item"
          :disabled="disableUpload"
          @click="emit('action', 'upload')"
        >
          <UploadCloud :size="14" :stroke-width="2.2" class="menu-item-icon text-blue-600" />
          <span>{{ batchMode ? '批量上传到服务器' : '上传到服务器' }}</span>
        </button>

        <button
          v-if="showBaiduUpload"
          type="button"
          class="menu-item"
          :disabled="disableBaiduUpload"
          @click="emit('action', 'baidu_upload')"
        >
          <img :src="baiduNetdiskIcon" alt="" class="menu-item-icon menu-item-platform-icon" />
          <span>{{ batchMode ? '批量上传到百度网盘' : '上传到百度网盘' }}</span>
        </button>

        <button
          v-if="showAutoCircleGroup"
          type="button"
          class="menu-item"
          :disabled="disableAutoCircleGroup"
          @click="emit('action', 'auto_circle_group')"
        >
          <Tags :size="14" :stroke-width="2.2" class="menu-item-icon text-violet-600" />
          <span>{{ batchMode ? '批量按社团分类' : '按社团分类' }}</span>
          <span v-if="autoCircleGroupRunning" class="ml-auto text-[10px] text-violet-600">运行中</span>
        </button>

        <button
          v-if="showFolderCompletion"
          type="button"
          class="menu-item"
          :disabled="disableFolderCompletion"
          @click="emit('action', 'folder_completion')"
        >
          <FolderSync :size="14" :stroke-width="2.2" class="menu-item-icon text-sky-600" />
          <span>{{ batchMode ? '批量补全文件夹' : '补全文件夹' }}</span>
        </button>

        <button
          type="button"
          class="menu-item"
          :class="{ 'bg-amber-50/70': apiBatchTarget, 'menu-item-running menu-item-api-running': apiRenameRunning }"
          :disabled="disableApiRename"
          @click="emit('action', 'api_rename')"
        >
          <Sparkles :size="14" :stroke-width="2.2" class="menu-item-icon text-amber-600" />
          <span>{{ batchMode ? '批量 API 重命名' : 'API 重命名' }}</span>
          <span v-if="apiRenameRunning" class="menu-running-badge">
            <span class="menu-running-dot"></span>
            <span>运行中</span>
          </span>
        </button>

        <button
          type="button"
          class="menu-item"
          :disabled="disableSubtitle"
          @click="emit('action', 'subtitle')"
        >
          <Captions :size="14" :stroke-width="2.2" class="menu-item-icon text-emerald-700" />
          <span>{{ batchMode ? '批量抓字幕' : '识别抓字幕' }}</span>
        </button>

        <button
          type="button"
          class="menu-item"
          :disabled="batchMode || disableManage"
          @click="emit('action', 'manage')"
        >
          <FolderCog :size="14" :stroke-width="2.2" class="menu-item-icon text-cyan-700" />
          <span>文件管理</span>
        </button>

        <button
          v-if="showComputeSize"
          type="button"
          class="menu-item"
          :disabled="disableComputeSize || computingSizeId === row?.id"
          @click="emit('action', 'compute_size')"
        >
          <HardDrive :size="14" :stroke-width="2.2" class="menu-item-icon text-teal-600" />
          <span>{{ batchMode ? '批量计算大小' : '计算文件夹大小' }}</span>
          <span v-if="computingSizeId === row?.id" class="ml-auto text-[10px] text-teal-700">计算中</span>
        </button>

        <button
          v-if="batchMode || row?.is_directory"
          type="button"
          class="menu-item"
          :disabled="disableFilterDelete"
          @click="emit('action', 'filter_delete')"
        >
          <Trash2 :size="14" :stroke-width="2.2" class="menu-item-icon text-fuchsia-600" />
          <span>{{ batchMode ? '批量删除过滤文件' : '删除过滤文件' }}</span>
        </button>

        <div class="my-1 border-t border-slate-200"></div>

        <button
          type="button"
          class="menu-item menu-item-danger"
          :disabled="disableDelete"
          @click="emit('action', 'delete')"
        >
          <Trash2 :size="14" :stroke-width="2.2" class="menu-item-icon text-rose-600" />
          <span>{{ batchMode ? '批量删除' : '删除' }}</span>
        </button>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Captions, Copy, ExternalLink, Eye, FolderCog, FolderInput, FolderOpen, FolderSync, HardDrive, MapPin, Pencil, Sparkles, Tags, Trash2, UploadCloud } from 'lucide-vue-next'
import baiduNetdiskIcon from '../../assets/platforms/baidu-netdisk.ico'

const props = defineProps({
  visible: { type: Boolean, default: false },
  x: { type: Number, default: 0 },
  y: { type: Number, default: 0 },
  row: { type: Object, default: null },
  batchMode: { type: Boolean, default: false },
  selectedCount: { type: Number, default: 0 },
  showLocate: { type: Boolean, default: false },
  showView: { type: Boolean, default: false },
  showOpen: { type: Boolean, default: false },
  showOpenDirect: { type: Boolean, default: false },
  disableRename: { type: Boolean, default: false },
  disableApiRename: { type: Boolean, default: false },
  apiRenameRunning: { type: Boolean, default: false },
  apiBatchTarget: { type: Boolean, default: false },
  disableSubtitle: { type: Boolean, default: false },
  disableManage: { type: Boolean, default: false },
  disableDelete: { type: Boolean, default: false },
  showComputeSize: { type: Boolean, default: false },
  disableComputeSize: { type: Boolean, default: false },
  computingSizeId: { type: String, default: null },
  showMove: { type: Boolean, default: false },
  disableMove: { type: Boolean, default: false },
  showUpload: { type: Boolean, default: false },
  disableUpload: { type: Boolean, default: false },
  showBaiduUpload: { type: Boolean, default: false },
  disableBaiduUpload: { type: Boolean, default: false },
  showAutoCircleGroup: { type: Boolean, default: false },
  disableAutoCircleGroup: { type: Boolean, default: false },
  autoCircleGroupRunning: { type: Boolean, default: false },
  showFolderCompletion: { type: Boolean, default: false },
  disableFolderCompletion: { type: Boolean, default: false },
  disableFilterDelete: { type: Boolean, default: false },
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
  document.addEventListener('pointerdown', handleOutsidePointerDown, true)
  document.addEventListener('contextmenu', handleOutsideContextMenu, true)
  window.addEventListener('scroll', handleWindowScroll, true)
}

function unbindGlobalListeners () {
  document.removeEventListener('pointerdown', handleOutsidePointerDown, true)
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
.menu-panel {
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 28px -10px rgba(15, 23, 42, 0.18),
    0 6px 16px -12px rgba(15, 23, 42, 0.12);
  animation: menu-enter 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
  transform-origin: top left;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.menu-header {
  /* 不带分割线，靠下方第一组菜单项后的 border-t 做分组 */
}

.menu-item {
  position: relative;
  width: 100%;
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 0 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #334155;
  font-size: 12.5px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    color 0.2s ease,
    transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.2s ease;
}

.menu-item:hover {
  background: rgb(248 250 252);
  color: #0f172a;
  transform: translateX(2px);
  box-shadow: inset 0 0 0 1px rgb(226 232 240);
}

.menu-item:active:not(:disabled) {
  transform: translateX(2px) scale(0.98);
}

.menu-item-icon {
  flex-shrink: 0;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.2s ease;
}

.menu-item-platform-icon {
  width: 15px;
  height: 15px;
  object-fit: contain;
}

.menu-item:hover .menu-item-icon {
  transform: translateY(-1px) scale(1.12) rotate(-4deg);
}

.menu-item:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  color: #94a3b8;
}

.menu-item:disabled .menu-item-icon {
  color: #cbd5e1 !important;
}

.menu-item:disabled .menu-item-platform-icon {
  filter: grayscale(1);
}

.menu-item-danger {
  color: #be123c;
}

.menu-item-danger:hover {
  background: rgb(255 241 242);
  color: #9f1239;
  box-shadow: inset 0 0 0 1px rgb(254 205 211);
}

.menu-item-running {
  overflow: hidden;
}

.menu-item-running::before {
  content: "";
  position: absolute;
  inset: 0;
  transform: translateX(-115%);
  background: linear-gradient(90deg, transparent, rgba(251, 191, 36, 0.2), transparent);
  animation: menu-running-sweep 1.25s ease-in-out infinite;
  pointer-events: none;
}

.menu-item-api-running {
  background: rgba(254, 243, 199, 0.76);
  color: #92400e;
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.24);
}

.menu-item-api-running .menu-item-icon {
  animation: menu-running-icon 0.95s ease-in-out infinite;
}

.menu-running-badge {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  border-radius: 999px;
  padding: 2px 6px;
  background: rgba(245, 158, 11, 0.14);
  color: #92400e;
  font-size: 10px;
  font-weight: 700;
}

.menu-running-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
  animation: menu-running-dot 0.86s ease-in-out infinite;
}

@keyframes menu-enter {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes menu-running-sweep {
  0% { transform: translateX(-115%); opacity: 0; }
  20% { opacity: 1; }
  100% { transform: translateX(115%); opacity: 0; }
}

@keyframes menu-running-icon {
  0%, 100% { transform: scale(1) rotate(0deg); }
  50% { transform: scale(1.18) rotate(-10deg); }
}

@keyframes menu-running-dot {
  0%, 100% { opacity: 0.45; transform: scale(0.76); }
  50% { opacity: 1; transform: scale(1.15); }
}

:global(html.kikoerumanager-dark) .menu-panel {
  border-color: rgba(255, 255, 255, 0.14) !important;
  background: #0d0e12 !important;
  box-shadow: 0 22px 60px rgba(0, 0, 0, 0.38) !important;
}

:global(html.kikoerumanager-dark) .menu-item-api-running {
  background: rgba(245, 158, 11, 0.12) !important;
  color: #f4ce75 !important;
  box-shadow: inset 0 0 0 1px rgba(245, 158, 11, 0.26) !important;
}

:global(html.kikoerumanager-dark) .menu-item-running::before {
  background: linear-gradient(90deg, transparent, rgba(245, 158, 11, 0.24), transparent) !important;
}

:global(html.kikoerumanager-dark) .menu-running-badge {
  background: rgba(245, 158, 11, 0.16) !important;
  color: #f4ce75 !important;
}
</style>
