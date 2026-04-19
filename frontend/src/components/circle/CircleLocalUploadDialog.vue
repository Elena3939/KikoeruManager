<template>
  <el-dialog
    :model-value="visible"
    :show-close="false"
    destroy-on-close
    class="custom-preview-modal"
    align-center
    modal-class="custom-preview-overlay"
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-if="loading" class="window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden dialog-loading-overlay">
      <AppLoadingAnimation label="正在加载本地库存文件树..." description="同步目录结构和可上传文件" :size="168" :min-height="260" />
    </div>
    <div v-else class="window panel-enter glass-shell relative w-full max-w-[1210px] aspect-[16/9] rounded-3xl flex flex-col overflow-hidden">
      <div class="window-header flex items-center justify-between px-8 py-6">
        <h1 class="title text-2xl font-bold text-slate-900 tracking-tight">上传到服务器</h1>
        <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="emit('update:visible', false)">
          <X :size="20" :stroke-width="2" />
        </button>
      </div>
      <div class="tabs-row px-8 pt-1 pb-3 flex items-center gap-1.5 overflow-x-auto no-scrollbar">
        <button
          type="button"
          class="tab-chip px-3 py-1 rounded-full text-[12px] font-medium tracking-[0.005em] whitespace-nowrap flex items-center gap-1 border"
          :class="allSelectionState === 'all' ? 'tab-chip-active' : (allSelectionState === 'partial' ? 'tab-chip-partial' : 'tab-chip-idle')"
          @click="toggleAllSelection"
        >
          <span>全部</span>
          <span class="tab-count">{{ selectedCount }}/{{ flatRows.length }}</span>
        </button>
      </div>
      <div class="content-grid flex-1 flex gap-6 px-8 py-2 min-h-0">
        <div class="left-column w-[380px] flex flex-col gap-6">
          <section ref="selectRoot" class="glass-panel glass-card settings-card flex-1 rounded-2xl p-6 overflow-y-auto no-scrollbar">
            <div class="space-y-6">
              <section class="space-y-4">
                <div class="section-head space-y-1">
                  <h2>目标库存</h2>
                  <p>选择群晖库存与可选前缀目录</p>
                </div>
                <div class="select-grid grid grid-cols-2 gap-4">
                  <div class="field-group space-y-2">
                    <label>目标库存</label>
                    <div class="select-wrap relative">
                      <button type="button" class="interactive-field field-input select-button flex h-9 w-full items-center justify-between rounded-lg border border-slate-200/70 bg-white/55 py-2 pr-2 pl-2.5 text-sm text-slate-800" @click.stop="openSelect = openSelect === 'inventory' ? null : 'inventory'">
                        <span class="line-clamp-1 text-left">{{ inventoryLabel }}</span>
                        <ChevronDown :size="18" class="select-arrow size-4 text-slate-400" />
                      </button>
                      <div v-if="openSelect === 'inventory'" class="dropdown-panel dropdown-menu absolute z-50 mt-1 w-full min-w-36 origin-top rounded-lg bg-white/88 border border-white/80 text-slate-800 shadow-lg ring-1 ring-slate-200/80 p-1">
                        <button
                          v-for="option in targetLibraries"
                          :key="option.id"
                          type="button"
                          class="dropdown-item relative flex w-full items-center rounded-md py-1 pr-8 pl-1.5 text-sm transition-colors hover:bg-slate-100/80"
                          @click.stop="chooseTargetLibrary(option.id)"
                        >
                          <span class="truncate">{{ option.name }}</span>
                          <span v-if="settings.targetLibraryId === option.id" class="pointer-events-none absolute right-2 flex size-4 items-center justify-center">
                            <Check :size="16" />
                          </span>
                        </button>
                      </div>
                    </div>
                  </div>
                  <div class="field-group space-y-2">
                    <label>库存内前缀目录</label>
                    <input v-model="settings.targetSubdir" type="text" class="field-input h-9 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-sm text-slate-800 outline-none" placeholder="可留空" />
                  </div>
                </div>
                <div class="space-y-1">
                  <p class="target-path text-xs text-slate-500 leading-relaxed">
                    最终路径: <span class="text-slate-700 break-all">{{ resolvedTargetRoot || '-' }}</span>
                    <span class="text-slate-400"> / {社团名 / 作品目录}</span>
                  </p>
                </div>
              </section>
            </div>
          </section>
        </div>
        <section class="glass-panel glass-card tree-panel flex-1 rounded-2xl flex flex-col overflow-hidden">
          <div class="tree-scroll flex-1 p-4 overflow-auto no-scrollbar">
            <div class="tree-list space-y-1">
              <div
                v-for="row in flatRows"
                :key="row.id"
                class="tree-node"
              >
                <div class="tree-row flex items-center py-1.5 px-2 rounded-md group cursor-pointer" :class="row.checked ? 'tree-row-selected' : ''" :style="{ paddingLeft: `${(row.depth + 1) * 16}px` }" @click="toggleRow(row)">
                  <div class="tree-main flex items-center gap-2 flex-1 min-w-0">
                    <button
                      v-if="row.type === 'dir'"
                      type="button"
                      class="tree-expander p-0.5 rounded"
                      @click.stop="toggleExpand(row)"
                    >
                      <ChevronDown v-if="expandedIds.has(row.id)" :size="17" class="text-slate-400" />
                      <ChevronRight v-else :size="17" class="text-slate-400" />
                    </button>
                    <span v-else class="expander-spacer" />
                    <button type="button" class="tree-checkbox relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border" :class="row.checked ? 'tree-checkbox-on' : 'tree-checkbox-off'" @click.stop="toggleRow(row)">
                      <Check v-if="row.checked" :size="14" />
                    </button>
                    <component :is="row.type === 'dir' ? Folder : File" :size="20" class="tree-icon" />
                    <span class="tree-name text-sm text-slate-800 truncate font-medium">{{ row.name }}</span>
                  </div>
                  <span v-if="row.size_bytes" class="tree-size text-xs text-slate-400 ml-4 tabular-nums">{{ formatSize(row.size_bytes) }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
      <div class="footer-row px-8 py-6 flex items-center justify-between">
        <div class="summary text-sm text-slate-500 font-medium"><span class="summary-strong text-slate-900">{{ selectedCount }}</span> 已选，共 <span class="summary-strong text-slate-900">{{ formatSize(selectedTotalBytes) }}</span></div>
        <div class="footer-actions flex items-center gap-3">
          <button type="button" class="primary-cta px-10 h-11 rounded-xl font-bold text-white" :disabled="selectedCount === 0 || starting || !settings.targetLibraryId" @click="emitSubmit">
            <span v-if="starting" class="inline-flex items-center"><AppLoadingAnimation variant="inline" :size="30" class="mr-1" />处理中</span>
            <span v-else>开始上传</span>
          </button>
          <button type="button" class="secondary-cta interactive-button px-10 h-11 rounded-xl font-bold" @click="emit('update:visible', false)">取消</button>
        </div>
      </div>
    </div>
  </el-dialog>
</template>
<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import { ChevronDown, ChevronRight, X, Folder, File } from 'lucide-vue-next'
import api, { localUploadApi } from '../../api'
import AppLoadingAnimation from '../common/AppLoadingAnimation.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  circleName: { type: String, default: '' },
  sourceLibraryId: { type: String, default: '' },
  sourceBasePath: { type: String, default: '' }
})
const emit = defineEmits(['update:visible', 'submitted'])

const loading = ref(false)
const starting = ref(false)
const openSelect = ref(null)
const settings = reactive({
  targetLibraryId: '',
  targetSubdir: ''
})

const inventoryLabel = computed(() => {
  const lib = (targetLibraries.value || []).find(item => item.id === settings.targetLibraryId)
  return lib ? lib.name : '选择目标库存'
})

const targetLibraries = computed(() => (api.library ? awaitableLibraries.value : []).filter(item => item?.type === 'synology_filestation' && item?.enabled !== false))
const awaitableLibraries = ref([])

const sourceTree = ref({ id: '', name: '', type: 'dir', depth: 0, size_bytes: 0, path: props.sourceBasePath, children: [] })
const expandedIds = ref(new Set())
const flatRows = ref([])

function formatSize(bytes) {
  const b = Number(bytes || 0)
  if (b <= 0) return '0 B'
  const k = 1024
  const sizes = ['B','KB','MB','GB','TB']
  const i = Math.floor(Math.log(b)/Math.log(k))
  return `${(b/Math.pow(k,i)).toFixed(2)} ${sizes[i]}`
}

const selectedMap = ref(new Set())
const selectedCount = computed(() => selectedMap.value.size)
const selectedTotalBytes = computed(() => {
  return flatRows.value.filter(r => selectedMap.value.has(r.id)).reduce((sum, r) => sum + Number(r.size_bytes || 0), 0)
})
const allSelectionState = computed(() => {
  if (selectedCount.value === 0) return 'none'
  if (selectedCount.value === flatRows.value.length) return 'all'
  return 'partial'
})

function toggleAllSelection() {
  if (selectedCount.value === flatRows.value.length) {
    selectedMap.value = new Set()
  } else {
    selectedMap.value = new Set(flatRows.value.map(r => r.id))
  }
  flatRows.value.forEach(r => r.checked = selectedMap.value.has(r.id))
}

function toggleRow(row) {
  const next = new Set(selectedMap.value)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  selectedMap.value = next
  row.checked = next.has(row.id)
}

function toggleExpand(row) {
  const next = new Set(expandedIds.value)
  if (next.has(row.id)) next.delete(row.id)
  else next.add(row.id)
  expandedIds.value = next
  rebuildFlat()
}

function chooseTargetLibrary(id) {
  settings.targetLibraryId = id
  openSelect.value = null
}

const resolvedTargetRoot = computed(() => {
  const lib = (awaitableLibraries.value || []).find(item => item.id === settings.targetLibraryId)
  const base = String((lib?.synology?.root_path || lib?.path || '')).replace(/\\/g, '/')
  const prefix = String(settings.targetSubdir || '').trim()
  if (!base) return ''
  return prefix ? `${base}/${prefix}`.replace(/\/+/g, '/') : base
})

async function loadLibraries() {
  const data = await api.library.listLibraries()
  awaitableLibraries.value = Array.isArray(data?.libraries) ? data.libraries : []
  if (!settings.targetLibraryId) {
    const syno = awaitableLibraries.value.find(item => item.type === 'synology_filestation' && item.enabled !== false)
    settings.targetLibraryId = syno?.id || ''
  }
}

async function loadSourceTree() {
  loading.value = true
  try {
    const data = await api.library.folderContents(props.sourceBasePath)
    const items = Array.isArray(data?.items) ? data.items : (Array.isArray(data?.files) ? data.files : [])
    const root = { id: props.sourceBasePath || 'root', name: props.circleName || '本地库存', path: props.sourceBasePath, type: 'dir', depth: 0, size_bytes: 0, children: [] }
    const rows = []
    const stack = []
    items.forEach((it, idx) => {
      const id = `${it.path || it.real_path || it.name || idx}`
      const isDir = Boolean(it.is_directory || it.isdir)
      const row = {
        id,
        name: it.name || it.relative_path || '',
        path: it.path || it.real_path || '',
        type: isDir ? 'dir' : 'file',
        size_bytes: Number(it.size || 0),
        depth: 0,
        checked: isDir
      }
      rows.push(row)
    })
    sourceTree.value = { ...root, children: rows }
    expandedIds.value = new Set(rows.filter(r => r.type === 'dir').map(r => r.id))
    selectedMap.value = new Set(rows.filter(r => r.type === 'dir').map(r => r.id))
    rebuildFlat()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '加载本地库存失败')
  } finally {
    loading.value = false
  }
}

function rebuildFlat() {
  const out = []
  function visit(node, depth) {
    if (!node) return
    if (node !== sourceTree.value) {
      out.push({ ...node, depth, checked: selectedMap.value.has(node.id) })
    }
    if (node.type === 'dir' && (node === sourceTree.value || expandedIds.value.has(node.id))) {
      ;(node.children || []).forEach(child => visit(child, depth + (node === sourceTree.value ? 0 : 1)))
    }
  }
  visit(sourceTree.value, 0)
  flatRows.value = out
}

async function emitSubmit() {
  if (!settings.targetLibraryId) {
    ElMessage.warning('请选择目标库存')
    return
  }
  const selectedDirs = flatRows.value.filter(r => r.type === 'dir' && selectedMap.value.has(r.id)).map(r => r.path).filter(Boolean)
  if (!selectedDirs.length) {
    ElMessage.warning('请选择要上传的目录')
    return
  }
  starting.value = true
  try {
    const payload = {
      source_library_id: props.sourceLibraryId || '',
      source_base_path: props.sourceBasePath || '',
      selected_paths: selectedDirs,
      target_library_id: settings.targetLibraryId,
      target_subdir: settings.targetSubdir || '',
      circle_name: props.circleName || ''
    }
    const result = await localUploadApi.start(payload)
    if (result?.success) {
      ElMessage.success(`已提交 ${result.count || selectedDirs.length} 个目录上传`)
      emit('submitted', result)
      emit('update:visible', false)
    } else {
      ElMessage.error(result?.message || '上传启动失败')
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error.message || '上传启动失败')
  } finally {
    starting.value = false
  }
}

watch(() => props.visible, (v) => {
  if (!v) return
  Promise.resolve().then(async () => {
    await loadLibraries()
    await loadSourceTree()
  })
})

function handleDocumentClick(e) {
  if (!e) return
  if (!e.target) return
}
onMounted(() => document.addEventListener('click', handleDocumentClick))
onBeforeUnmount(() => document.removeEventListener('click', handleDocumentClick))
</script>
<style scoped>
.custom-preview-modal :deep(.el-dialog__header) { display: none; }
.loader-icon { font-size: 28px; color: #64748b; }
.loading-text { margin-top: 12px; color: #334155; font-weight: 600; letter-spacing: .2px; }
.glass-shell { background: rgba(255,255,255,.7); backdrop-filter: blur(8px); border: 1px solid rgba(15,23,42,.06); }
.dropdown-menu { backdrop-filter: blur(8px); }
.tab-chip { transition: all .15s ease; }
.tab-chip-active { background: rgba(15,23,42,.06); border-color: rgba(15,23,42,.12); }
.tab-chip-partial { background: rgba(15,23,42,.04); border-color: rgba(15,23,42,.08); }
.tab-chip-idle { background: rgba(255,255,255,.75); border-color: rgba(15,23,42,.08); }
.tree-row-selected { background: rgba(15,23,42,.04); }
.primary-cta { background: #111827; }
.secondary-cta { background: rgba(17,24,39,.06); }
.field-input { transition: border-color .15s ease; }
.field-input:focus { border-color: rgba(17,24,39,.45); }
.tree-icon { color: #64748b; }
.checkbox-minus { width: 10px; height: 2px; background: #111827; display: inline-block; border-radius: 1px; }
</style>
