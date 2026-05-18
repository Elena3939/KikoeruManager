<template>
  <div
    class="group relative w-full cursor-pointer transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
    :class="[
      compact
        ? ['rounded-[8px]', isDragOver ? 'bg-slate-50' : 'hover:bg-slate-50']
        : [
            'rounded-[10px] border border-dashed bg-white px-4 py-3 shadow-[0_1px_3px_rgba(15,23,42,0.04)] hover:-translate-y-0.5 hover:shadow-[0_4px_12px_-6px_rgba(15,23,42,0.15)]',
            isDragOver ? 'border-slate-900 bg-slate-50' : 'border-slate-300 hover:border-slate-400',
          ],
    ]"
    @dragover.prevent="handleDragOver"
    @dragleave.prevent="handleDragLeave"
    @drop.prevent="handleDrop"
    @click="triggerFileInput"
  >
    <input
      ref="fileInput"
      type="file"
      multiple
      class="hidden"
      @change="handleFileSelect"
    />

    <div class="flex flex-col gap-2.5">
      <div class="flex items-center gap-2.5 min-w-0">
        <span
          class="inline-flex flex-shrink-0 items-center justify-center rounded-[10px] border border-slate-200 bg-white text-blue-600 transition-all duration-300 group-hover:scale-110 group-hover:-rotate-[6deg]"
          :class="compact ? 'h-9 w-9' : 'h-10 w-10'"
        >
          <Upload :size="compact ? 16 : 20" :stroke-width="1.7" />
        </span>
        <div class="min-w-0 flex-1">
          <h3
            class="m-0 truncate font-bold tracking-tight text-slate-900"
            :class="compact ? 'text-[11.5px]' : 'text-[13px]'"
          >
            {{ compact ? '拖拽或点击上传文件' : '拖拽文件到此处或点击上传' }}
          </h3>
          <p class="m-0 mt-px text-[10.5px] leading-snug text-slate-500">
            支持多种压缩格式，自动识别分卷
          </p>
        </div>
      </div>

      <div
        v-if="displayFiles.length > 0"
        class="flex flex-col gap-2 border-t border-dashed border-neutral-200 pt-2.5"
        :class="compact ? 'max-h-[220px] overflow-auto pr-0.5' : ''"
        @click.stop
      >
        <div class="flex flex-col gap-1.5">
          <span class="text-[10.5px] font-bold uppercase tracking-[0.06em] text-slate-400">解压目标库</span>
          <div class="relative">
            <select
              v-model="targetLibraryId"
              class="w-full appearance-none rounded-[8px] border border-slate-200 bg-white px-3 pr-8 text-[12.5px] font-medium text-slate-800 outline-none shadow-[0_1px_3px_rgba(15,23,42,0.04)] transition-all duration-300 hover:border-slate-300 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100"
              :class="compact ? 'h-8' : 'h-9'"
            >
              <option value="" disabled>选择目标库存</option>
              <option
                v-for="library in libraries"
                :key="library.id"
                :value="library.id"
              >
                {{ library.name }}
              </option>
            </select>
            <ChevronDown
              :size="13"
              :stroke-width="2.2"
              class="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400"
            />
          </div>
        </div>

        <div class="flex flex-col gap-1">
          <div
            v-for="group in displayFiles"
            :key="group._uid"
            class="flex items-center gap-2 rounded-[8px] border border-slate-200 bg-white px-2.5 py-1.5 transition-all duration-300 hover:border-slate-300 hover:shadow-[0_2px_8px_-4px_rgba(15,23,42,0.1)]"
          >
            <FileText :size="12" :stroke-width="2.2" class="flex-shrink-0 text-slate-500" />
            <span class="flex-1 min-w-0 truncate text-left text-[12.5px] text-slate-800">
              {{ group.displayName }}
              <span
                v-if="group.isVolumeGroup"
                class="ml-1.5 inline-flex items-center rounded-md border border-amber-200 bg-amber-50 px-1.5 py-px align-middle text-[10.5px] font-bold text-amber-700"
              >
                {{ group.fileCount }} 个分卷
              </span>
            </span>
            <span class="flex-shrink-0 text-[11px] tabular-nums text-slate-500">
              {{ formatFileSize(group.totalSize) }}
            </span>
          </div>
        </div>

        <button
          type="button"
          class="group/btn mt-1 inline-flex h-9 w-full items-center justify-center gap-2 rounded-[10px] bg-slate-900 px-4 text-[13px] font-bold text-white shadow-[0_4px_14px_-4px_rgba(15,23,42,0.4)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:bg-slate-800 hover:shadow-[0_8px_22px_-6px_rgba(15,23,42,0.5)] active:translate-y-0 active:scale-[0.97] disabled:pointer-events-none disabled:opacity-60"
          :disabled="uploading"
          @click.stop="startUpload"
        >
          <Loader2
            v-if="uploading"
            :size="14"
            :stroke-width="2.4"
            class="animate-spin"
          />
          <Play
            v-else
            :size="13"
            :stroke-width="2.4"
            class="transition-transform duration-300 group-hover/btn:rotate-6"
          />
          <span>开始处理 ({{ displayFiles.length }} 个任务)</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ChevronDown, FileText, Loader2, Play, Upload } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { apiFetchOptions, apiUrl, libraryApi } from '../api'

defineProps({
  compact: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['upload-success'])

const fileInput = ref(null)
const isDragOver = ref(false)
const selectedFiles = ref([])
const uploading = ref(false)
const libraries = ref([])
const targetLibraryId = ref('')

onMounted(async () => {
  try {
    const data = await libraryApi.listLibraries()
    libraries.value = data.libraries || []
    targetLibraryId.value =
      data.default_extract_library_id ||
      data.default_library_id ||
      libraries.value[0]?.id ||
      ''
  } catch (error) {
    console.error('failed to load libraries', error)
  }
})

function getVolumeBaseName(filename) {
  const zipMatch = filename.match(/^(.+)\.z\d{2}$/i)
  if (zipMatch) return zipMatch[1]
  const rarLegacyMatch = filename.match(/^(.+)\.r\d{2}$/i)
  if (rarLegacyMatch) return rarLegacyMatch[1]
  const rarMatch = filename.match(/^(.+)\.part\d+\.(rar|7z|zip|exe)$/i)
  if (rarMatch) return rarMatch[1]
  const sevenZMatch = filename.match(/^(.+\.(7z|zip|rar))\.\d{3}$/i)
  if (sevenZMatch) return sevenZMatch[1]
  return null
}

const displayFiles = computed(() => {
  const groups = new Map()
  const singles = []
  const allFiles = selectedFiles.value

  const volumeBaseNames = new Set()
  allFiles.forEach((file) => {
    const baseName = getVolumeBaseName(file.name)
    if (baseName) {
      volumeBaseNames.add(baseName.toLowerCase())
    }
  })

  allFiles.forEach((file) => {
    if (file.name.toLowerCase().endsWith('.zip')) {
      const nameWithoutExt = file.name.slice(0, -4)
      if (volumeBaseNames.has(nameWithoutExt.toLowerCase())) {
        volumeBaseNames.add(file.name.toLowerCase())
      }
    }
  })

  allFiles.forEach((file) => {
    const nameLower = file.name.toLowerCase()
    let baseName = getVolumeBaseName(file.name)

    if (!baseName && nameLower.endsWith('.zip')) {
      const nameWithoutExt = file.name.slice(0, -4)
      if (volumeBaseNames.has(nameWithoutExt.toLowerCase())) {
        baseName = nameWithoutExt
      }
    }

    if (baseName) {
      const groupKey = baseName.toLowerCase()
      if (!groups.has(groupKey)) {
        groups.set(groupKey, {
          _uid: `group_${baseName}_${Date.now()}`,
          displayName: baseName,
          isVolumeGroup: true,
          fileCount: 0,
          totalSize: 0,
          files: [],
        })
      }
      const group = groups.get(groupKey)
      group.files.push(file)
      group.totalSize += file.size
      group.fileCount = group.files.length
    } else {
      singles.push({
        _uid: file._uid,
        displayName: file.name,
        isVolumeGroup: false,
        fileCount: 1,
        totalSize: file.size,
        files: [file],
      })
    }
  })

  return [...groups.values(), ...singles]
})

function triggerFileInput() {
  fileInput.value?.click()
}

function handleDragOver() {
  isDragOver.value = true
}

function handleDragLeave() {
  isDragOver.value = false
}

function handleDrop(e) {
  e.stopPropagation()
  isDragOver.value = false
  const files = Array.from(e.dataTransfer.files)
  addFiles(files)
}

function handleFileSelect(e) {
  const files = Array.from(e.target.files)
  addFiles(files)
}

let uidCounter = 0

function addFiles(files) {
  const validFiles = files
  if (validFiles.length === 0) {
    ElMessage.warning('没有可添加的文件')
    return
  }

  const filesWithUid = validFiles.map((file) => ({
    _file: file,
    name: file.name,
    size: file.size,
    lastModified: file.lastModified,
    _uid: `file_${Date.now()}_${uidCounter++}`,
  }))

  const newFiles = filesWithUid.filter(
    (newFile) =>
      !selectedFiles.value.some(
        (existingFile) =>
          existingFile.name === newFile.name && existingFile.size === newFile.size
      )
  )

  if (newFiles.length > 0) {
    selectedFiles.value = [...selectedFiles.value, ...newFiles]
    ElMessage.success(`添加了 ${newFiles.length} 个文件`)
  } else {
    ElMessage.info('所有文件都已在列表中')
  }
}

function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
}

async function startUpload() {
  if (selectedFiles.value.length === 0) return
  uploading.value = true
  try {
    const formData = new FormData()
    for (const file of selectedFiles.value) {
      formData.append('files', file._file)
    }
    if (targetLibraryId.value) {
      formData.append('target_library_id', targetLibraryId.value)
    }
    const response = await fetch(apiUrl('/upload'), apiFetchOptions({ method: 'POST', body: formData }))
    if (!response.ok) {
      throw new Error(`上传失败: ${response.statusText}`)
    }
    const result = await response.json()
    ElMessage.success(result.message)
    selectedFiles.value = []
    emit('upload-success')
  } catch (error) {
    ElMessage.error('处理失败: ' + error.message)
  } finally {
    uploading.value = false
  }
}
</script>
