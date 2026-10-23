<template>
  <UploadTaskWorkbenchDialog
    :visible="Boolean(workbench.visible)" :tasks="tasks"
    @update:visible="hide" @background="hide" @close="hide"
  >
    <template #transfer-content>
      <BrowserUploadBatch v-for="session in browserUploads" :key="session.id" :session="session" />
      <div v-if="!browserUploads.length" class="browser-upload-empty">拖动文件夹到库存目录即可上传</div>
    </template>
  </UploadTaskWorkbenchDialog>
</template>

<script setup>
import { computed } from 'vue'
import UploadTaskWorkbenchDialog from './UploadTaskWorkbenchDialog.vue'
import BrowserUploadBatch from './BrowserUploadBatch.vue'
import { browserUploads, initializeBrowserUploads, UPLOAD_WORKBENCH } from '../../composables/useBrowserUploads'
import { useBackgroundWorkbenchManager } from '../../composables/useBackgroundWorkbenchManager'

const manager = useBackgroundWorkbenchManager()
initializeBrowserUploads()
const workbench = manager.getWorkbenchState(UPLOAD_WORKBENCH)
const hide = () => manager.backgroundWorkbench(UPLOAD_WORKBENCH)
const tasks = computed(() => browserUploads.value.map(s => ({
  id: s.id, status: s.status === 'receiving' ? 'processing' : s.status,
  source_path: s.source_label, output_path: s.target_path,
  task_metadata: { source_label: s.source_label, target_path: s.target_path },
  upload_runtime: { total_bytes: s.total_bytes, transferred_bytes: s.liveReceived, frontend_speed_bytes_per_sec: s.speed },
})))
</script>

<style>
.library-external-upload-target { outline: 2px solid var(--el-color-primary) !important; background: var(--el-color-primary-light-9) !important; }
.library-external-upload-hint { position: fixed; z-index: 4500; left: 50%; bottom: 48px; transform: translateX(-50%); max-width: 90vw; padding: 14px 22px; border: 1px solid var(--el-color-primary); border-radius: 14px; background: var(--el-bg-color-overlay); color: var(--el-text-color-primary); box-shadow: var(--el-box-shadow); pointer-events: none; overflow-wrap: anywhere; }
.browser-upload-empty { padding: 48px; text-align: center; color: var(--el-text-color-secondary); }
</style>
