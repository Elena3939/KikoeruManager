<template>
  <DownloadTaskWorkbenchDialog
    :visible="visible"
    :tasks="mappedTasks"
    :refreshing="refreshing"
    :retrying-keys="[]"
    title="Upload Manager"
    subtitle="库存上传任务"
    empty-title="暂无符合筛选的上传任务"
    source-path-label="来源目录"
    :show-download-metrics="false"
    :show-upload-eta="true"
    :prefer-upload-icon="true"
    @update:visible="emit('update:visible', $event)"
    @refresh="emit('refresh')"
    @background="emit('background')"
    @close="emit('close')"
  />
</template>

<script setup>
import { computed } from 'vue'
import DownloadTaskWorkbenchDialog from '../download/DownloadTaskWorkbenchDialog.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  tasks: { type: Array, default: () => [] },
  refreshing: { type: Boolean, default: false },
})

const emit = defineEmits(['update:visible', 'refresh', 'background', 'close'])

const mappedTasks = computed(() => {
  return (Array.isArray(props.tasks) ? props.tasks : []).map((task) => {
    const metadata = task?.task_metadata || {}
    const selectedPaths = Array.isArray(metadata.selected_paths) ? metadata.selected_paths : []
    const sourceBasePath = String(metadata.source_base_path || task?.source_path || '').trim()
    const selectedDirCount = Number(metadata.selected_dir_count || selectedPaths.length || 0)
    const targetPath = String(metadata.target_path || '').trim()
    const finalOutputPath = String(metadata.final_output_path || task?.output_path || '').trim()
    const uploadRuntime = task?.upload_runtime || {}
    const currentRelativePath = String(uploadRuntime.current_relative_path || '').trim()
    const currentSpeed = Number(uploadRuntime.speed_bytes_per_sec || uploadRuntime.last_non_zero_speed_bytes_per_sec || 0)
    const currentUploadedBytes = Number(uploadRuntime.current_file_uploaded_bytes || 0)
    const totalBytes = Number(uploadRuntime.total_bytes || 0)
    const transferredBytes = Number(uploadRuntime.transferred_bytes || 0)

    const uploadFiles = (Array.isArray(task?.upload_files) ? task.upload_files : []).map((file) => {
      const relativePath = String(file?.relative_path || '').trim()
      const sizeBytes = Number(file?.size || file?.size_bytes || 0)
      const isCurrent = relativePath && relativePath === currentRelativePath
      const isCompleted = String(file?.status || '') === 'completed' || Number(file?.progress || 0) >= 100
      return {
        relative_path: relativePath,
        name: String(file?.name || relativePath || '').trim(),
        size_bytes: sizeBytes,
        progress: isCompleted
          ? 100
          : Math.max(0, Math.min(100, Number(file?.progress || 0))),
        uploaded: isCompleted
          ? sizeBytes
          : (isCurrent ? Math.min(sizeBytes, currentUploadedBytes) : Number(file?.uploaded_bytes || 0)),
        speed_bytes_per_sec: isCurrent ? currentSpeed : 0,
        status: isCompleted ? 'completed' : (isCurrent ? 'processing' : 'pending'),
      }
    })

    const uploadedFiles = (Array.isArray(task?.uploaded_files) ? task.uploaded_files : []).map((file) => ({
      relative_path: String(file?.relative_path || '').trim(),
      name: String(file?.name || file?.relative_path || '').trim(),
      size_bytes: Number(file?.size || file?.size_bytes || file?.uploaded_bytes || 0),
      status: 'completed',
    }))

    const title = selectedPaths.length === 1
      ? getBaseName(selectedPaths[0])
      : (String(metadata.source_label || '').trim() || getBaseName(sourceBasePath) || '上传任务')

    const subtitle = selectedDirCount > 0 ? `${selectedDirCount}个目录` : '上传任务'

    return {
      id: task?.id,
      status: task?.status,
      display_status: task?.display_status || task?.status,
      progress: totalBytes > 0
        ? Math.max(0, Math.min(100, Math.round((transferredBytes / totalBytes) * 100)))
        : Number(task?.progress || 0),
      current_step: task?.current_step,
      error_message: task?.error_message,
      created_at: task?.created_at,
      started_at: task?.started_at,
      completed_at: task?.completed_at,
      work_title: title,
      source_label: title,
      rjcode: subtitle,
      output_path: finalOutputPath || targetPath,
      progress_log: Array.isArray(task?.progress_log) ? task.progress_log : [],
      upload_files: uploadFiles,
      uploaded_files: uploadedFiles,
      upload_runtime: uploadRuntime,
      task_metadata: {
        ...metadata,
        source_action: 'local_library_upload',
        download_root: sourceBasePath,
        target_path: targetPath,
        final_output_path: finalOutputPath || targetPath,
        selected_resources: uploadFiles.map((file) => ({
          relative_path: file.relative_path,
          file_name: file.name,
          size: file.size_bytes,
        })),
      },
    }
  })
})

function getBaseName(value) {
  const normalized = String(value || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
  if (!normalized) return ''
  const parts = normalized.split('/')
  return parts[parts.length - 1] || ''
}
</script>
