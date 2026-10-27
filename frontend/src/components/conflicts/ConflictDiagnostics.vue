<template>
  <details class="conflict-diagnostics" @toggle="handleToggle">
    <summary>诊断明细</summary>
    <div class="diagnostics-toolbar">
      <span v-if="loading">读取中...</span>
      <span v-else-if="error" role="alert">{{ error }}</span>
      <StatefulButton unstyled class="page-head-btn" :disabled="loading" @click="load">
        <RefreshCw :size="14" />
        刷新
      </StatefulButton>
    </div>
    <pre v-if="content">{{ content }}</pre>
  </details>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import { conflictApi } from '../../api'
import StatefulButton from '../ui/stateful-button.vue'

const props = defineProps({ conflictId: { type: String, required: true } })
const loading = ref(false)
const error = ref('')
const content = ref('')
let controller

async function load() {
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = true
  error.value = ''
  try {
    const result = await conflictApi.diagnostics(props.conflictId, { signal: request.signal })
    if (request.signal.aborted) return
    content.value = JSON.stringify(result.metadata || {}, null, 2)
  } catch (err) {
    if (!request.signal.aborted) error.value = err?.response?.data?.detail || err.message || '读取诊断失败'
  } finally {
    if (controller === request) loading.value = false
  }
}

function handleToggle(event) {
  if (event.target.open) void load()
  else {
    controller?.abort()
    content.value = ''
  }
}

onBeforeUnmount(() => controller?.abort())
</script>

<style scoped>
.conflict-diagnostics {
  min-width: 0;
  margin-top: 16px;
  color: #475569;
}
summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}
.diagnostics-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin: 8px 0;
  font-size: 12px;
}
pre {
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  background: #f1f5f9;
  border-radius: 6px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
}
</style>
