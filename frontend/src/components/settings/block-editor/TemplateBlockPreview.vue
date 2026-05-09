<template>
  <div class="blk-preview">
    <div class="blk-preview-head">
      <span class="blk-preview-kicker">预览</span>
      <div class="blk-preview-controls">
        <select v-model="eventType" class="blk-preview-sel" title="预览事件类型">
          <option value="completed">任务完成</option>
          <option value="failed">任务失败</option>
          <option value="waiting_manual">等待人工</option>
        </select>
        <button
          type="button"
          class="blk-preview-refresh"
          :disabled="loading"
          @click="fetchPreview"
        >
          <RefreshCw :size="12" :stroke-width="2.4" :class="{ 'spin-once': loading }" />
          {{ loading ? '渲染中' : '刷新' }}
        </button>
      </div>
    </div>

    <div v-if="subjectText" class="blk-preview-subject">
      <span class="blk-preview-subject-label">主题</span>
      <span class="blk-preview-subject-val">{{ subjectText }}</span>
    </div>

    <div class="blk-preview-frame-wrap">
      <iframe
        v-if="htmlContent"
        :srcdoc="htmlContent"
        class="blk-preview-frame"
        sandbox=""
        title="邮件预览"
      />
      <div v-else class="blk-preview-placeholder">
        <Mail :size="22" :stroke-width="1.5" />
        <span>{{ blocks.length ? '点击刷新查看邮件预览' : '添加块后预览邮件效果' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Mail, RefreshCw } from 'lucide-vue-next'
import { notificationApi } from '../../../api'

const props = defineProps({
  blocks:          { type: Array,  default: () => [] },
  eventType:       { type: String, default: 'completed' },
  domain:          { type: String, default: 'import' },
  subjectTemplate: { type: String, default: '' },
})

const eventType   = ref(props.eventType)
const htmlContent = ref('')
const subjectText = ref('')
const loading     = ref(false)
const requestId   = ref(0)

let debounceTimer = null
let abortController = null

watch(
  [() => props.blocks, eventType],
  ([newBlocks]) => {
    // blocks 为空时直接清空预览，不发请求
    if (!newBlocks?.length) {
      htmlContent.value = ''
      subjectText.value = ''
      return
    }
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(fetchPreview, 600)
  },
  { deep: true },
)

async function fetchPreview() {
  if (!props.blocks.length) {
    htmlContent.value = ''
    subjectText.value = ''
    return
  }
  abortController?.abort()
  abortController = new AbortController()
  const id = ++requestId.value
  loading.value = true
  try {
    const res = await notificationApi.previewBlocks(
      props.blocks,
      eventType.value,
      props.domain,
      props.subjectTemplate,
    )
    // 乱序保护
    if (id !== requestId.value) return
    htmlContent.value = res.html || ''
    subjectText.value = res.subject || ''
  } catch {
    // 中断请求静默处理
  } finally {
    if (id === requestId.value) loading.value = false
  }
}

defineExpose({ fetchPreview })
</script>

<style scoped>
.blk-preview {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f5f5f7;
  min-height: 0;
}
.blk-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px 6px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.07);
  background: #fff;
}
.blk-preview-kicker {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.45);
}
.blk-preview-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}
.blk-preview-sel {
  font-size: 11px;
  padding: 3px 6px;
  border: 1px solid rgba(29, 29, 31, 0.12);
  border-radius: 6px;
  background: #fff;
  color: #1d1d1f;
  outline: none;
}
.blk-preview-refresh {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 500;
  color: #1d1d1f;
  background: #fff;
  border: 1px solid rgba(29, 29, 31, 0.12);
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.2s;
}
.blk-preview-refresh:hover {
  border-color: rgba(0, 113, 227, 0.3);
  color: #0071e3;
}
.blk-preview-subject {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 14px;
  background: #fff;
  border-bottom: 1px solid rgba(29, 29, 31, 0.07);
}
.blk-preview-subject-label {
  font-size: 10px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.45);
  flex-shrink: 0;
}
.blk-preview-subject-val {
  font-size: 12px;
  color: #1d1d1f;
  line-height: 1.4;
}
.blk-preview-frame-wrap {
  flex: 1;
  overflow: hidden;
  padding: 12px;
  min-height: 0;
}
.blk-preview-frame {
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 10px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08);
  background: #fff;
}
.blk-preview-placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: rgba(29, 29, 31, 0.35);
  font-size: 12px;
}
</style>
