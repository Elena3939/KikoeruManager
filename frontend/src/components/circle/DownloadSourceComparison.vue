<template>
  <section class="download-source-comparison">
    <div class="source-comparison-intro">
      <strong>选择下载来源</strong>
      <span>对比两站文件，选择后设置保存位置与下载内容</span>
    </div>
    <div class="source-comparison-works">
      <section v-for="plan in plans" :key="plan.session_id || plan.rjcode" class="source-comparison-work">
        <div class="source-comparison-work-heading">{{ plan.rjcode }}<span v-if="plan.title">{{ plan.title }}</span></div>
        <p v-for="error in plan.source_errors || []" :key="error" class="source-preview-description">{{ error }}</p>
        <div class="source-comparison-grid">
          <section v-for="option in plan.sourcePreviews" :key="option.source_provider" class="source-preview-pane"
            role="button" tabindex="0" :aria-label="`选择 ${option.source_provider === 'imoutoheaven' ? 'YAAS' : 'asmr.one'} 下载来源`"
            @click="emit('choose-source', plan, option)"
            @keydown.enter.self.prevent="emit('choose-source', plan, option)"
            @keydown.space.self.prevent="emit('choose-source', plan, option)">
            <header class="source-preview-header">
              <div>
                <strong>{{ option.source_provider === 'imoutoheaven' ? 'YAAS' : 'asmr.one' }}</strong>
                <p>{{ option.selectable_resources.length }} {{ option.source_provider === 'imoutoheaven' ? '个压缩包' : '个文件' }} · {{ formatSize(option.total_size_bytes) }}</p>
              </div>
            </header>
            <p class="source-preview-description">{{ option.source_provider === 'imoutoheaven' ? '原压缩包 · 保存到 HTTP 下载目录' : '音轨与附件 · 支持文件选择和入库' }}</p>
            <div class="source-preview-tree">
              <DownloadResourceTree :plan="option" readonly
                @toggle-root="emit('toggle-root', option)"
                @toggle-expand="emit('toggle-expand', option, $event)" />
            </div>
          </section>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import DownloadResourceTree from './DownloadResourceTree.vue'

defineProps({ plans: { type: Array, required: true } })
const emit = defineEmits(['choose-source', 'toggle-root', 'toggle-expand'])

function formatSize(bytes) {
  const size = Number(bytes || 0)
  if (!size) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), 4)
  return `${(size / 1024 ** index).toFixed(index ? 2 : 0)} ${units[index]}`
}
</script>
