<template>
  <div class="operation-details">
    <dl class="operation-meta">
      <div><dt>发起时间（北京）</dt><dd>{{ formatTime(row.created_at) }}</dd></div>
      <div><dt>最新活动（北京）</dt><dd>{{ formatTime(row.latest_activity_at) }}</dd></div>
      <div><dt>原始结果</dt><dd>{{ statusLabel(row.original_status) }}</dd></div>
      <div><dt>当前结果</dt><dd>{{ statusLabel(row.current_result) }}</dd></div>
      <div v-for="(count, key) in row.detail?.operation_counts" :key="key">
        <dt>{{ statusLabel(key) }}</dt><dd>{{ count }}</dd>
      </div>
      <div v-for="(label, key) in batchLabels" v-show="row.detail?.[key] != null" :key="key">
        <dt>{{ label }}</dt><dd>{{ row.detail?.[key] }}</dd>
      </div>
    </dl>
    <p v-if="['failed', 'partial_success'].includes(row.original_status)" class="operation-warning">
      原操作曾有失败，以下事件保留失败原因与重试关系。
    </p>
    <p v-if="row.integrity?.length" class="operation-warning">
      {{ row.integrity.map(flag => integrityLabels[flag] || '记录信息不完整').join('；') }}
    </p>
    <section v-for="(values, phase) in row.detail?.phase_metrics" :key="phase">
      <h3>{{ phaseLabels[phase] || phase }}</h3>
      <dl class="operation-meta">
        <div v-for="(value, key) in values" :key="key">
          <dt>{{ metricLabels[key] || key }}</dt><dd>{{ metricValue(key, value) }}</dd>
        </div>
      </dl>
    </section>
    <section>
      <h3>文件清单 <small>当前 {{ pageRange(files, fileCursors) }}／总计 {{ files.total }}</small></h3>
      <p v-if="!files.total">没有保留的文件明细</p>
      <ol class="operation-list">
        <li v-for="(file, index) in files.items" :key="`${file.execution_id}-${file.phase}-${index}`">
          <details>
            <summary>{{ phaseLabels[file.phase] || file.phase }} · {{ file.relative_path || file.path || file.name }}</summary>
            <dl class="operation-meta">
              <div><dt>路径</dt><dd>{{ file.relative_path || file.path || file.name }}</dd></div>
              <div v-if="file.new_path || file.target_path"><dt>目标路径</dt><dd>{{ file.new_path || file.target_path }}</dd></div>
              <div v-if="file.status"><dt>结果</dt><dd>{{ statusLabel(file.status) }}</dd></div>
              <div><dt>大小</dt><dd>{{ metricValue('bytes', file.size_bytes ?? file.size) }}</dd></div>
              <div v-if="file.library_id"><dt>库存</dt><dd>{{ file.library_id }}</dd></div>
              <div v-if="file.error || file.reason"><dt>原因</dt><dd>{{ file.error || file.reason }}</dd></div>
            </dl>
          </details>
        </li>
      </ol>
      <div class="operation-pagination">
        <StatefulButton :disabled="!fileCursors.length" size="sm" @click="() => changeFiles(-1)"><ChevronLeft :size="14" />上一页</StatefulButton>
        <StatefulButton :disabled="!files.has_more" size="sm" @click="() => changeFiles(1)">下一页<ChevronRight :size="14" /></StatefulButton>
      </div>
    </section>
    <section>
      <h3>执行事件与重试 <small>当前 {{ pageRange(events, eventCursors) }}／总计 {{ events.total }}</small></h3>
      <ol class="operation-list">
        <li v-for="event in events.items" :key="event.id">
          <div class="operation-event-title"><strong>{{ statusLabel(event.status) }}</strong><time>{{ formatTime(event.created_at) }}</time></div>
          <p>{{ event.summary }}</p>
          <p v-if="event.detail?.error || event.detail?.error_message || event.detail?.failed_reason" class="operation-warning">
            {{ event.detail.error || event.detail.error_message || event.detail.failed_reason }}
          </p>
          <dl v-if="event.detail?.retry_task_id || event.detail?.retry_batch_id" class="operation-meta">
            <div><dt>重试任务</dt><dd>{{ event.detail.retry_task_id }}</dd></div>
            <div><dt>重试批次</dt><dd>{{ event.detail.retry_batch_id }}</dd></div>
          </dl>
          <details @toggle="eventToggle($event, event.id)">
            <summary>原始审计数据</summary>
            <pre v-if="raw[event.id]">{{ JSON.stringify(raw[event.id], null, 2) }}</pre>
            <StatefulButton v-else size="sm" @click="() => loadRaw(event.id)"><RefreshCw :size="13" />加载原始数据</StatefulButton>
          </details>
        </li>
      </ol>
      <div class="operation-pagination">
        <StatefulButton :disabled="!eventCursors.length" size="sm" @click="() => changeEvents(-1)"><ChevronLeft :size="14" />上一页</StatefulButton>
        <StatefulButton :disabled="!events.has_more" size="sm" @click="() => changeEvents(1)">下一页<ChevronRight :size="14" /></StatefulButton>
      </div>
    </section>
    <p v-if="error" role="alert" class="operation-warning">{{ error }}</p>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-vue-next'
import StatefulButton from '../ui/stateful-button.vue'
import api from '../../api'

const props = defineProps({ row: { type: Object, required: true } })
const emptyPage = () => ({ items: [], total: 0, next_cursor: null, has_more: false })
const files = ref(emptyPage())
const events = ref(emptyPage())
const raw = ref({})
const error = ref('')
const fileCursors = ref([])
const eventCursors = ref([])
let epoch = 0
let fileRequest = 0
let eventRequest = 0
const rawInflight = new Map()
const pageRange = (page, cursors) => page.items.length
  ? `${cursors.length * 100 + 1}–${cursors.length * 100 + page.items.length}` : '0'
const phaseLabels = { download: '下载', upload: '远程上传', local_import: '入库', extract: '解压', subtitle: '字幕', delete: '删除', rename: '重命名' }
const batchLabels = { requested_count: '请求', discovered_count: '发现', skipped_count: '跳过',
  skipped_total: '跳过总数', submitted_count: '提交', created_count: '创建任务' }
const metricLabels = { files: '文件数', bytes: '有效字节', duration_ms: '阶段耗时', average_speed_bytes: '平均速度',
  executions: '实际执行次数', archive_bytes: '压缩包大小', output_bytes: '解压产物大小', items: '项目数',
  applied_pairs: '实际配对', imported_count: '导入数', downloaded_count: '下载数', deleted_subtitles: '删除字幕',
  folders: '文件夹数', unknown_size_count: '大小未知的文件数', unknown_type_count: '类型未知的项目数' }
const integrityLabels = { historical_detail_compacted: '历史明细曾被压缩，已丢弃部分无法恢复',
  identity_missing: '缺少可靠操作身份，单独保留', parent_cycle: '父子关联存在循环',
  parent_missing: '父记录缺失，关联信息不完整',
  member_identity_missing: '部分成员缺少库存身份，无法确认完整结果',
  download_manifest_incomplete: '下载清单不完整', upload_manifest_incomplete: '上传清单不完整',
  local_import_manifest_incomplete: '入库清单不完整' }
const statusLabel = status => ({ success: '成功', failed: '失败', repaired: '已修复', cancelled: '取消',
  partial_success: '部分成功', waiting: '待处理', pending: '等待执行', processing: '执行中',
  incomplete: '结果未收齐', paused: '已暂停' }[status] || status || '未知')
function formatTime(value) {
  if (!value) return '未知'
  const input = String(value)
  // 审计库无时区时间固定存北京时间；带偏移的值转换为同一展示时区。
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(input) ? input : `${input.replace(' ', 'T')}+08:00`)
  return Number.isNaN(date.getTime()) ? '未知' : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date)
}
function metricValue(key, value) {
  if (value == null) return '未知'
  if (key === 'duration_ms') return `${(Number(value) / 1000).toFixed(2)} 秒`
  if (key.includes('bytes')) {
    const number = Number(value)
    const unit = number >= 1024 ** 3 ? 'GiB' : number >= 1024 ** 2 ? 'MiB' : number >= 1024 ? 'KiB' : 'B'
    const divisor = { GiB: 1024 ** 3, MiB: 1024 ** 2, KiB: 1024, B: 1 }[unit]
    return `${(number / divisor).toFixed(2)} ${unit}${key === 'average_speed_bytes' ? '/s' : ''}`
  }
  return value
}
watch(() => [props.row.operation_id, props.row.revision, props.row.detail], () => {
  epoch++
  fileRequest++
  eventRequest++
  files.value = props.row.detail?.files_page || emptyPage()
  events.value = { ...emptyPage(), ...props.row.detail?.children_page, items: props.row.detail?.child_rows || [] }
  fileCursors.value = []
  eventCursors.value = []
  raw.value = {}
  rawInflight.clear()
  error.value = ''
}, { immediate: true })

async function changePage(kind, direction) {
  const page = kind === 'files' ? files : events
  const cursors = kind === 'files' ? fileCursors : eventCursors
  const snapshot = epoch
  const request = kind === 'files' ? ++fileRequest : ++eventRequest
  const next = direction > 0 ? [...cursors.value, page.value.next_cursor] : cursors.value.slice(0, -1)
  try {
    const data = await api.activityLog[kind === 'files' ? 'files' : 'children'](props.row.operation_id,
      { limit: 100, cursor: next.at(-1) || undefined })
    if (snapshot !== epoch || request !== (kind === 'files' ? fileRequest : eventRequest)) return
    page.value = data
    cursors.value = next
    error.value = ''
  } catch (cause) {
    if (snapshot === epoch && request === (kind === 'files' ? fileRequest : eventRequest)) {
      error.value = '明细更新失败，当前页已保留，请重试翻页'
      throw cause
    }
  }
}
const changeFiles = direction => changePage('files', direction)
const changeEvents = direction => changePage('events', direction)
async function loadRaw(eventId) {
  if (rawInflight.has(eventId)) return rawInflight.get(eventId)
  const request = fetchRaw(eventId)
  rawInflight.set(eventId, request)
  try {
    return await request
  } finally {
    if (rawInflight.get(eventId) === request) rawInflight.delete(eventId)
  }
}
async function fetchRaw(eventId) {
  const snapshot = epoch
  try {
    const result = await api.activityLog.event(props.row.operation_id, eventId)
    if (snapshot === epoch) {
      raw.value = { ...raw.value, [eventId]: result.event }
      error.value = ''
    }
  } catch (cause) {
    if (snapshot === epoch) {
      error.value = '原始事件加载失败，请重试'
      throw cause
    }
  }
}
function eventToggle(event, eventId) {
  if (event.target.open && !raw.value[eventId]) loadRaw(eventId).catch(() => {})
}
</script>

<style scoped>
.operation-details { color: inherit; min-width: 0; }
.operation-details section { border-top: 1px solid var(--km-dark-border, #dfe3e8); padding: 16px 0; }
.operation-details h3 { font-size: 14px; margin: 0 0 12px; }
.operation-details small, .operation-details time { font-size: 11px; font-weight: 400; opacity: .7; }
.operation-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 8px 0; }
.operation-meta div { min-width: 0; }
.operation-meta dt { font-size: 11px; opacity: .7; }
.operation-meta dd { margin: 4px 0 0; font-size: 12px; overflow-wrap: anywhere; }
.operation-warning { color: var(--km-dark-warning, #b45309); font-size: 12px; overflow-wrap: anywhere; }
.operation-list { list-style: none; margin: 0; padding: 0; }
.operation-list li { padding: 10px 0; border-bottom: 1px solid var(--km-dark-border, #e5e7eb); min-width: 0; }
.operation-list p { font-size: 12px; overflow-wrap: anywhere; }
.operation-list summary { cursor: pointer; font-size: 12px; overflow-wrap: anywhere; }
.operation-event-title, .operation-pagination { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.operation-event-title { font-size: 12px; flex-wrap: wrap; }
.operation-pagination { justify-content: flex-end; margin-top: 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; max-height: 420px; overflow: auto; }
@media (max-width: 640px) { .operation-meta { grid-template-columns: minmax(0, 1fr); } }
</style>
