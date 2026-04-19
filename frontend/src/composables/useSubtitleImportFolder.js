import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { subtitleImportApi } from '../api'

export function useSubtitleImportFolder({
  getSubtitleWorkbenchFilterOptions,
  openImportedTask,
  candidateKey
}) {
  const folderPath = ref('')
  const folderPreviewLoading = ref(false)
  const folderImporting = ref(false)
  const folderPreview = ref(null)
  const folderCandidateSelection = ref('')

  const selectedFolderCandidate = computed(() => {
    return (folderPreview.value?.candidates || []).find(candidate => candidateKey(candidate) === folderCandidateSelection.value) || null
  })

  const canExecuteFolderImport = computed(() => {
    if (!folderPreview.value) return false
    const readyCount = Number(folderPreview.value.ready_candidate_count || 0)
    if (readyCount <= 0) return false
    return Boolean(selectedFolderCandidate.value)
  })

  const canRetryFolderPreview = computed(() => {
    if (!folderPreview.value || folderPreviewLoading.value) return false
    return !canExecuteFolderImport.value || Number(folderPreview.value?.candidate_count || 0) <= 0
  })

  watch(folderPreview, (preview) => {
    if (!preview) {
      folderCandidateSelection.value = ''
      return
    }
    const selected = preview.selected_candidate
    if (selected) {
      folderCandidateSelection.value = candidateKey(selected)
      return
    }
    const readyCandidates = (preview.candidates || []).filter(candidate => candidate?.ready_for_import)
    folderCandidateSelection.value = readyCandidates.length === 1 ? candidateKey(readyCandidates[0]) : ''
  }, { immediate: true })

  async function previewFolderImport() {
    const path = folderPath.value.trim()
    if (!path) {
      ElMessage.warning('请先输入字幕文件夹路径')
      return
    }

    folderPreviewLoading.value = true
    try {
      const data = await subtitleImportApi.previewFolder(path)
      folderPreview.value = data.preview || data
      ElMessage.success('字幕文件夹预检完成')
    } catch (error) {
      folderPreview.value = null
      ElMessage.error('字幕文件夹预检失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      folderPreviewLoading.value = false
    }
  }

  async function executeFolderImport() {
    const path = folderPath.value.trim()
    const candidate = selectedFolderCandidate.value
    if (!path || !candidate) return

    folderImporting.value = true
    try {
      const filterOptions = getSubtitleWorkbenchFilterOptions()
      const data = await subtitleImportApi.importFolder(path, {
        targetLibraryId: candidate.library_id,
        targetFolderPath: candidate.folder_path,
        useFilterRules: filterOptions.useFilterRules,
        subtitleFilterRules: filterOptions.subtitleFilterRules
      })
      ElMessage.success(data.import_result?.awaiting_manual_match ? '字幕文件夹补配成功，已自动加入工作台' : '字幕文件夹补配成功')
      if (data.task?.id) {
        openImportedTask(data.task.id)
      }
    } catch (error) {
      ElMessage.error('执行字幕文件夹补配失败: ' + (error.response?.data?.detail || error.message))
    } finally {
      folderImporting.value = false
    }
  }

  return {
    folderPath,
    folderPreviewLoading,
    folderImporting,
    folderPreview,
    folderCandidateSelection,
    selectedFolderCandidate,
    canExecuteFolderImport,
    canRetryFolderPreview,

    previewFolderImport,
    executeFolderImport
  }
}
