<template>
  <UploadTaskWorkbenchDialog
    :visible="Boolean(workbench.visible)" :tasks="tasks" :show-upload-eta="false"
    @pause-task="task => controlBrowserUpload(task.id, 'pause')"
    @resume-task="task => controlBrowserUpload(task.id, 'resume')"
    @cancel-task="task => controlBrowserUpload(task.id, 'cancel')"
    @refresh="refreshBrowserUploads"
    @update:visible="hide" @background="hide" @close="hide"
  >
    <template #task-detail="{ task }">
      <BrowserUploadBatch v-if="sessionsById.has(task.id)" :session="sessionsById.get(task.id)" />
    </template>
  </UploadTaskWorkbenchDialog>
</template>

<script setup>
import { computed } from 'vue'
import UploadTaskWorkbenchDialog from './UploadTaskWorkbenchDialog.vue'
import BrowserUploadBatch from './BrowserUploadBatch.vue'
import { browserUploads, controlBrowserUpload, refreshBrowserUploads, initializeBrowserUploads, UPLOAD_WORKBENCH } from '../../composables/useBrowserUploads'
import { useBackgroundWorkbenchManager } from '../../composables/useBackgroundWorkbenchManager'

const manager = useBackgroundWorkbenchManager()
initializeBrowserUploads()
const workbench = manager.getWorkbenchState(UPLOAD_WORKBENCH)
const hide = () => manager.backgroundWorkbench(UPLOAD_WORKBENCH)
const sessionsById = computed(() => new Map(browserUploads.value.map(session => [session.id, session])))
const tasks = computed(() => browserUploads.value.map(s => ({
  id: s.id, status: s.status === 'receiving' ? 'processing' : s.status,
  source_path: s.source_label, output_path: s.target_path,
  current_step: !s.enumerated ? `读取目录 · 已发现 ${s.discoveredFiles || s.total_files || 0} 个文件` : s.counts?.conflict ? '等待冲突，其他文件继续传输' : s.status === 'cancelled' ? '已完成文件保留' : '',
  created_at: s.created_at,
  task_metadata: {
    source_label: s.source_label, target_path: s.target_path,
    file_progress_label: `完成 ${s.counts?.completed || 0} · 失败 ${s.counts?.failed || 0} · 跳过 ${s.counts?.skipped || 0} · 共 ${s.total_files || 0} 个文件`,
  },
  upload_runtime: { total_bytes: s.total_bytes, transferred_bytes: s.liveReceived, frontend_speed_bytes_per_sec: s.speed, speed_bytes_per_sec: s.speed, active_file_count: s.activeFileCount },
})))
</script>

<style>
.library-external-upload-target { outline: none !important; box-shadow: inset 0 0 0 2px #38bdf8 !important; background: var(--el-color-primary-light-9) !important; }
html.kikoerumanager-dark .library-external-upload-target { background: var(--km-dark-surface-soft) !important; }
.browser-upload-empty { padding: 48px; text-align: center; color: var(--el-text-color-secondary); }
</style>
