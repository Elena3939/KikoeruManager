<template>
  <section class="browser-upload-batch">
    <div v-if="terminal" class="upload-result" :class="`is-${session.status}`" role="status">
      <CheckCircle2 v-if="session.status === 'completed'" :size="20" />
      <AlertCircle v-else :size="20" />
      <div><strong>{{ stage }}</strong><p>完成 {{ session.counts?.completed || 0 }} · 失败 {{ failureCount }} · 跳过 {{ session.counts?.skipped || 0 }} · 共 {{ bytes(session.total_bytes) }}</p></div>
    </div>
    <div class="upload-path-grid">
      <div class="upload-path-card"><span>目标库存</span><strong>{{ session.library_name }}</strong></div>
      <div class="upload-path-card"><span>上传到</span><strong class="upload-destination">{{ session.target_path }}</strong></div>
    </div>
    <p class="upload-started"><Clock3 :size="12" />开始时间：{{ session.created_at ? new Date(session.created_at).toLocaleString() : '恢复中' }}</p>
    <p v-if="!session.enumerated && !terminal" class="upload-enumerating">读取目录：已发现 {{ session.discoveredFiles || session.total_files || 0 }} 个文件，共 {{ bytes(session.discoveredBytes || session.total_bytes) }}；总量尚未确定</p>
    <div v-else-if="!terminal" class="upload-phases">
      <div class="upload-phase"><span>上传至服务</span><span>{{ bytes(session.liveReceived) }} / {{ bytes(session.total_bytes) }} · {{ bytes(session.speed) }}/s</span></div>
      <AppLottieProgressBar :percentage="phasePercent(session.liveReceived)" size="sm" />
      <div class="upload-phase"><span>{{ session.target_type === 'synology_filestation' ? '写入群晖' : '写入库存' }}</span><span>{{ bytes(session.liveWritten) }} / {{ bytes(session.total_bytes) }} · {{ bytes(session.backendSpeed) }}/s</span></div>
      <AppLottieProgressBar :percentage="phasePercent(session.liveWritten)" size="sm" />
      <p class="upload-phase-summary">{{ stage }}<span v-if="eta"> · 预计剩余 {{ eta }}</span></p>
    </div>
    <p v-if="session.connectionError || session.enumerationError" class="upload-error upload-session-error"><AlertCircle :size="14" />{{ session.enumerationError || session.connectionError }}</p>
    <div v-if="canRestore" class="upload-restore">
      <FileUploader selection-only compact @sources-selected="restoreSources" />
    </div>
    <div class="upload-list-tools">
      <strong>文件明细 <span>{{ files.length }} 项</span></strong>
      <div class="upload-list-filters">
        <el-checkbox v-model="onlyProblems" size="small">只看失败／冲突</el-checkbox>
        <el-checkbox v-if="session.counts?.conflict" v-model="applyAll" size="small">应用至后续同类冲突</el-checkbox>
      </div>
    </div>
    <AppEmptyState v-if="!files.length" size="sm" :description="onlyProblems ? '没有失败或冲突的文件' : '正在读取上传来源'" />
    <div v-else ref="scroll" class="upload-file-scroll" :style="{ height: `${Math.min(files.length * 104, 320)}px` }">
      <div :style="{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }">
        <div v-for="row in virtualizer.getVirtualItems()" :key="row.key" class="upload-file-row"
          :style="{ transform: `translateY(${row.start}px)` }">
          <template v-if="files[row.index]">
            <div class="upload-file-name"><component :is="entryMeta(files[row.index]).icon" :size="16" :style="{ color: entryMeta(files[row.index]).color }" /><span :title="files[row.index].relative_path">{{ files[row.index].relative_path }}</span><span class="upload-status-chip" :class="`is-${files[row.index].status}`">{{ fileStage(files[row.index]) }}</span></div>
            <div class="upload-file-info">
              <span>{{ files[row.index].is_directory ? '文件夹' : `${bytes(fileBytes(files[row.index]))} / ${bytes(files[row.index].size)} · ${filePercent(files[row.index])}%` }}</span>
              <span v-if="files[row.index].speed">{{ bytes(files[row.index].speed) }}/s</span>
              <template v-if="files[row.index].status === 'conflict'">
                <StatefulButton size="sm" @click="() => decide(files[row.index], 'skip')">跳过</StatefulButton>
                <StatefulButton v-if="!files[row.index].type_conflict" size="sm" @click="() => decide(files[row.index], 'replace')">替换</StatefulButton>
                <StatefulButton size="sm" @click="() => decide(files[row.index], 'keep_both')">保留两份</StatefulButton>
              </template>
              <StatefulButton v-if="files[row.index].status === 'failed' && files[row.index].retryable" size="sm" tone="neutral" @click="() => control('retry', files[row.index].id)">重试该文件</StatefulButton>
            </div>
            <p v-if="files[row.index].reason" class="upload-error" :title="files[row.index].reason">{{ files[row.index].stage }}：{{ files[row.index].reason }}{{ files[row.index].retryable ? '（可重试）' : '' }}</p>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { AlertCircle, CheckCircle2, Clock3 } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import StatefulButton from '../ui/stateful-button.vue'
import AppLottieProgressBar from '../common/AppLottieProgressBar.vue'
import AppEmptyState from '../common/AppEmptyState.vue'
import FileUploader from '../FileUploader.vue'
import { libraryEntryMetaFor } from '../library/_libraryFileKind.js'
import { controlBrowserUpload, restoreBrowserUploadSource, formatUploadBytes as bytes } from '../../composables/useBrowserUploads'

const props = defineProps({ session: { type: Object, required: true } })
const scroll = ref(null), onlyProblems = ref(false), applyAll = ref(false)
const files = computed(() => Array.from(props.session.files.values()).filter(f => !onlyProblems.value || ['failed', 'conflict'].includes(f.status)))
const virtualizer = useVirtualizer(computed(() => ({ count: files.value.length, getScrollElement: () => scroll.value, estimateSize: () => 104, overscan: 4, getItemKey: i => files.value[i]?.id || i })))
const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(props.session.status))
const failureCount = computed(() => props.session.counts?.failed || Array.from(props.session.files.values()).filter(f => f.status === 'failed').length)
const canRestore = computed(() => !['completed', 'cancelled'].includes(props.session.status) && (props.session.needsSource || props.session.enumerationError))
const entryMeta = file => libraryEntryMetaFor({ name: file.relative_path, is_directory: file.is_directory })
const phasePercent = value => Math.max(0, Math.min(100, Number(value || 0) / Math.max(1, props.session.total_bytes) * 100))
const stage = computed(() => props.session.status === 'paused' ? '暂停' : props.session.status === 'cancelled' ? '已取消，已落地文件保留' : props.session.status === 'completed' ? '完成' : props.session.status === 'failed' ? '存在失败文件' : !props.session.enumerated ? '读取目录／上传接收' : props.session.counts?.conflict ? '等待冲突，其他文件继续传输' : '上传接收／写入库存')
const eta = computed(() => {
  const s = props.session
  if (!s.enumerated || s.status !== 'receiving' || !s.speedStable) return ''
  const remaining = (s.total_bytes || 0) - (s.liveReceived || 0)
  if (s.speed <= 0 || remaining <= 0) return ''
  const seconds = Math.ceil(remaining / s.speed)
  return seconds < 60 ? `${seconds} 秒（接收阶段）` : `${Math.ceil(seconds / 60)} 分钟（接收阶段）`
})
const fileStage = f => ({ completed: '完成', failed: '失败', conflict: '等待冲突', skipped: '已跳过', cancelled: '已取消', writing: f.stage, ready: '等待写入', receiving: '上传接收' }[f.status] || f.status)
const fileBytes = f => f.status === 'completed' ? f.size : f.status === 'writing' ? f.written || 0 : Math.min(f.size, (f.received || 0) + (f.liveBytes || 0))
const filePercent = f => f.status === 'completed' ? 100 : Math.min(99, Math.floor(fileBytes(f) / Math.max(1, f.size) * 100))
async function control(action, fileId, decision) {
  try { await controlBrowserUpload(props.session.id, action, fileId, decision, applyAll.value) } catch (e) { ElMessage.error(e.message) }
}
const decide = (file, decision) => control('conflict', file.id, decision)
async function restoreSources(sources) {
  try { await restoreBrowserUploadSource(props.session.id, sources) } catch (error) { ElMessage.error(error.message) }
}
</script>

<style scoped>
.browser-upload-batch { --upload-text: #27272a; --upload-muted: #71717a; --upload-panel: rgba(255,255,255,.76); --upload-border: rgba(148,163,184,.2); padding-top: 12px; color: var(--upload-text); font-size: 12px; }
:global(html.kikoerumanager-dark .browser-upload-batch) { --upload-text: var(--km-dark-text); --upload-muted: var(--km-dark-text-muted); --upload-panel: var(--km-dark-elevated); --upload-border: var(--km-dark-border-soft); }
.upload-path-grid { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(0, 2fr); gap: 10px; }
.upload-path-card { min-width: 0; padding: 10px 12px; border: 1px solid var(--upload-border); border-radius: 12px; background: var(--upload-panel); }
.upload-path-card > span { display: block; color: var(--upload-muted); font-size: 10px; font-weight: 700; }
.upload-path-card strong { display: block; margin-top: 4px; font-size: 12px; font-weight: 600; overflow-wrap: anywhere; line-height: 1.5; }
.upload-started,.upload-phase,.upload-file-name,.upload-file-info,.upload-list-tools,.upload-list-filters { display: flex; align-items: center; gap: 8px; }
.upload-started { margin: 10px 0 14px; color: var(--upload-muted); font-size: 11px; }
.upload-phases { padding: 12px 14px; border: 1px solid var(--upload-border); border-radius: 12px; background: var(--upload-panel); }
.upload-phase { justify-content: space-between; margin-bottom: 10px; gap: 12px; font-size: 11px; font-variant-numeric: tabular-nums; }
.upload-phase > span:last-child { color: var(--upload-muted); text-align: right; }
.upload-phases :deep(.app-lottie-progress) { min-height: 10px; margin-bottom: 14px; }
.upload-phase-summary { margin: 4px 0 0; color: var(--upload-muted); font-size: 11px; }
.upload-result { display: flex; gap: 10px; align-items: center; padding: 12px 14px; margin-bottom: 12px; border: 1px solid var(--upload-border); background: var(--upload-panel); border-radius: 12px; }
.upload-result > svg { flex-shrink: 0; }
.upload-result strong { font-size: 12px; }
.upload-result p { margin: 4px 0 0; color: var(--upload-muted); font-size: 11px; }
.upload-result.is-failed { border-color: rgba(220,38,38,.24); }
.upload-result.is-failed > svg { color: var(--el-color-danger); }
.upload-error { color: var(--el-color-danger); overflow-wrap: anywhere; margin: 5px 0 0; font-size: 11px; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.upload-session-error { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px; border: 1px solid rgba(220,38,38,.24); border-radius: 10px; }
.upload-session-error > svg { flex-shrink: 0; }
.upload-restore { margin-top: 12px; border: 1px dashed var(--upload-border); border-radius: 12px; padding: 12px; background: var(--upload-panel); }
.upload-list-tools { flex-wrap: wrap; justify-content: space-between; margin: 14px 0 8px; }
.upload-list-tools strong { font-size: 11px; }
.upload-list-tools strong span { font-weight: 400; margin-left: 6px; color: var(--upload-muted); }
.upload-list-filters { flex-wrap: wrap; gap: 12px; }
.upload-list-filters :deep(.el-checkbox) { margin-right: 0; color: var(--upload-muted); }
.upload-list-filters :deep(.el-checkbox__label) { font-size: 11px; }
.upload-file-scroll { max-height: 320px; overflow: auto; contain: strict; border: 1px solid var(--upload-border); border-radius: 10px; background: var(--upload-panel); }
.upload-file-row { position: absolute; top: 0; left: 0; width: 100%; height: 104px; padding: 12px; box-sizing: border-box; border-bottom: 1px solid var(--upload-border); }
.upload-file-name > svg { flex-shrink: 0; }
.upload-file-name > span:first-of-type { min-width: 0; flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-weight: 600; }
.upload-status-chip { flex-shrink: 0; padding: 2px 7px; border-radius: 5px; background: var(--upload-border); font-size: 10px; color: var(--upload-muted); }
.upload-status-chip.is-failed,.upload-status-chip.is-conflict { color: var(--el-color-danger); }
.upload-file-info { margin-top: 8px; flex-wrap: wrap; color: var(--upload-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.browser-upload-batch :deep(button) { transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.browser-upload-batch :deep(button:hover) { transform: translateY(-2px) scale(1.02); }
.browser-upload-batch :deep(button:active) { transform: scale(0.96); }
.browser-upload-batch button:hover :deep(svg) { transform: rotate(-6deg); }
.browser-upload-batch :is(button,input):focus-visible { outline: none; box-shadow: none; }
@media(max-width:640px) { .upload-path-grid { grid-template-columns: minmax(0,1fr); } .upload-phase { align-items: flex-start; flex-direction: column; gap: 4px; } .upload-file-row { padding: 10px; } }
</style>
