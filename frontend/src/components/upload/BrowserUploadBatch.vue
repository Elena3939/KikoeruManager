<template>
  <article class="browser-upload-batch" @dragover.prevent @drop.prevent="restoreDrop">
    <header class="upload-batch-head">
      <div class="upload-batch-title"><FolderUp :size="22" /><strong>{{ session.source_label }}</strong><span>{{ stage }}</span></div>
      <div class="upload-batch-actions">
        <StatefulButton v-if="!terminal" :key="session.status === 'paused' ? 'resume' : 'pause'" :success-hold="0" size="sm" @click="() => control(session.status === 'paused' ? 'resume' : 'pause')"><Play v-if="session.status === 'paused'" :size="14" /><Pause v-else :size="14" />{{ session.status === 'paused' ? '继续' : '暂停' }}</StatefulButton>
        <StatefulButton v-if="!terminal" size="sm" @click="() => control('cancel')"><X :size="14" />取消上传</StatefulButton>
      </div>
    </header>
    <p class="upload-destination">上传到：{{ session.library_name }} / {{ session.target_path }}</p>
    <p class="upload-started">开始时间：{{ session.created_at ? new Date(session.created_at).toLocaleString() : '恢复中' }}</p>
    <p v-if="!session.enumerated">读取目录：已发现 {{ session.discoveredFiles || session.total_files || 0 }} 个文件，共 {{ bytes(session.discoveredBytes || session.total_bytes) }}；总量尚未确定</p>
    <template v-else>
      <div class="upload-phase"><span>上传至服务</span><span>{{ bytes(session.liveReceived) }} / {{ bytes(session.total_bytes) }} · {{ bytes(session.speed) }}/s</span></div>
      <progress :value="session.liveReceived" :max="session.total_bytes || 1" />
      <div class="upload-phase"><span>{{ session.target_type === 'synology_filestation' ? '写入群晖' : '写入库存' }}</span><span>{{ bytes(session.liveWritten) }} / {{ bytes(session.total_bytes) }} · {{ bytes(session.backendSpeed) }}/s</span></div>
      <progress :value="session.liveWritten" :max="session.total_bytes || 1" />
      <p>完成 {{ session.counts?.completed || 0 }} · 失败 {{ failureCount }} · 跳过 {{ session.counts?.skipped || 0 }} · 总计 {{ session.total_files || 0 }} 个文件<span v-if="eta"> · 预计剩余 {{ eta }}</span></p>
    </template>
    <p v-if="session.connectionError || session.enumerationError" class="upload-error">{{ session.enumerationError || session.connectionError }}</p>
    <div v-if="session.needsSource || session.enumerationError" class="upload-restore">
      <p>重新拖入原文件夹／文件，或选择原来源。会核对相对路径、大小、修改时间及已传分块摘要。</p>
      <label class="upload-picker">选择原文件夹<input type="file" webkitdirectory multiple @change="restorePicked" /></label>
      <label class="upload-picker">选择原文件<input type="file" multiple @change="restorePicked" /></label>
    </div>
    <div class="upload-list-tools">
      <span>文件详情（{{ files.length }} 项，含目录）</span>
      <label><input v-model="onlyProblems" type="checkbox" /> 只看失败／冲突</label>
      <label><input v-model="applyAll" type="checkbox" /> 冲突选项用于后续同类项</label>
    </div>
    <div ref="scroll" class="upload-file-scroll">
      <div :style="{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }">
        <div v-for="row in virtualizer.getVirtualItems()" :key="row.key" class="upload-file-row"
          :style="{ transform: `translateY(${row.start}px)` }">
          <template v-if="files[row.index]">
            <div class="upload-file-name"><span :title="files[row.index].relative_path">{{ files[row.index].relative_path }}</span><span>{{ fileStage(files[row.index]) }}</span></div>
            <div class="upload-file-info">
              <span>{{ bytes(fileBytes(files[row.index])) }} / {{ bytes(files[row.index].size) }} · {{ filePercent(files[row.index]) }}%</span>
              <span v-if="files[row.index].speed">{{ bytes(files[row.index].speed) }}/s</span>
              <template v-if="files[row.index].status === 'conflict'">
                <StatefulButton size="sm" @click="() => decide(files[row.index], 'skip')">跳过</StatefulButton>
                <StatefulButton v-if="!files[row.index].type_conflict" size="sm" @click="() => decide(files[row.index], 'replace')">替换</StatefulButton>
                <StatefulButton size="sm" @click="() => decide(files[row.index], 'keep_both')">保留两份</StatefulButton>
              </template>
              <StatefulButton v-if="files[row.index].status === 'failed'" size="sm" @click="() => control('retry', files[row.index].id)">重试该文件</StatefulButton>
            </div>
            <p v-if="files[row.index].reason" class="upload-error" :title="files[row.index].reason">{{ files[row.index].stage }}：{{ files[row.index].reason }}{{ files[row.index].retryable ? '（可重试）' : '' }}</p>
          </template>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { FolderUp, Pause, Play, X } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import StatefulButton from '../ui/stateful-button.vue'
import { controlBrowserUpload, restoreBrowserUploadSource, formatUploadBytes as bytes } from '../../composables/useBrowserUploads'
import { captureUploadSources } from '../../utils/browserUploadEntries'

const props = defineProps({ session: { type: Object, required: true } })
const scroll = ref(null), onlyProblems = ref(false), applyAll = ref(false)
const files = computed(() => Array.from(props.session.files.values()).filter(f => !onlyProblems.value || ['failed', 'conflict'].includes(f.status)))
const virtualizer = useVirtualizer(computed(() => ({ count: files.value.length, getScrollElement: () => scroll.value, estimateSize: () => 104, overscan: 4, getItemKey: i => files.value[i]?.id || i })))
const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(props.session.status))
const failureCount = computed(() => files.value.filter(f => f.status === 'failed').length)
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
const fileBytes = f => f.status === 'writing' ? f.written || 0 : Math.min(f.size, (f.received || 0) + (f.liveBytes || 0))
const filePercent = f => f.status === 'completed' ? 100 : Math.min(99, Math.floor(fileBytes(f) / Math.max(1, f.size) * 100))
async function control(action, fileId, decision) {
  try { await controlBrowserUpload(props.session.id, action, fileId, decision, applyAll.value) } catch (e) { ElMessage.error(e.message) }
}
const decide = (file, decision) => control('conflict', file.id, decision)
async function restorePicked(event) {
  await restoreBrowserUploadSource(props.session.id, Array.from(event.target.files || []))
  event.target.value = ''
}
async function restoreDrop(event) {
  if (props.session.needsSource) await restoreBrowserUploadSource(props.session.id, captureUploadSources(event.dataTransfer))
}
</script>

<style scoped>
.browser-upload-batch { padding: 20px; margin-bottom: 16px; border: 1px solid var(--el-border-color); border-radius: 16px; background: var(--el-bg-color); color: var(--el-text-color-primary); font-size: 13px; }
.upload-batch-head,.upload-batch-title,.upload-batch-actions,.upload-phase,.upload-file-name,.upload-file-info,.upload-list-tools { display: flex; align-items: center; gap: 10px; }
.upload-batch-head,.upload-phase,.upload-file-name { justify-content: space-between; }
.upload-batch-title { min-width: 0; flex-wrap: wrap; }
.upload-batch-title strong { overflow-wrap: anywhere; }
.upload-batch-title span,.upload-started,.upload-file-info,.upload-list-tools { color: var(--el-text-color-secondary); }
.upload-batch-actions { flex-shrink: 0; }
.upload-destination { overflow-wrap: anywhere; margin: 12px 0 4px; }
progress { width: 100%; height: 9px; accent-color: var(--el-color-primary); margin: 6px 0 12px; }
.upload-error { color: var(--el-color-danger); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; margin: 4px 0; }
.upload-restore { padding: 12px; background: var(--el-fill-color-light); border-radius: 10px; }
.upload-picker { display: inline-block; cursor: pointer; padding: 7px 12px; margin-right: 8px; border: 1px solid var(--el-border-color); border-radius: 8px; }
.upload-picker input { display: none; }
.upload-list-tools { flex-wrap: wrap; margin: 14px 0 8px; }
.upload-list-tools label { cursor: pointer; }
.upload-file-scroll { max-height: 320px; height: 320px; overflow: auto; contain: strict; }
.upload-file-row { position: absolute; top: 0; left: 0; width: 100%; height: 104px; padding: 10px 8px; box-sizing: border-box; border-bottom: 1px solid var(--el-border-color-lighter); }
.upload-file-name > span:first-child { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.upload-file-name > span:last-child { flex-shrink: 0; }
.upload-file-info { margin-top: 7px; flex-wrap: wrap; gap: 6px; }
.browser-upload-batch :is(button,.upload-picker) { transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.browser-upload-batch :is(button,.upload-picker):hover { transform: translateY(-2px) scale(1.02); }
.browser-upload-batch :is(button,.upload-picker):active { transform: scale(0.96); }
.browser-upload-batch button:hover :deep(svg) { transform: rotate(-6deg); }
.browser-upload-batch :is(button,input):focus-visible { outline: none; box-shadow: none; }
@media(max-width:640px) { .browser-upload-batch { padding: 12px; } .upload-batch-head { align-items: flex-start; flex-direction: column; } .upload-file-row { font-size: 12px; } }
</style>
