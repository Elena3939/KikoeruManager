<template>
  <HttpDownloadPanel
    provider="baidu"
    :has-tasks="hasTasks"
    :draft="draft"
    @update:draft="$emit('update:draft', $event)"
    @started="$emit('started', $event)"
    @open-workbench="$emit('open-workbench')"
  />
</template>

<script setup>
import HttpDownloadPanel from './HttpDownloadPanel.vue'

defineProps({
  hasTasks: { type: Boolean, default: false },
  draft: { type: Object, default: () => ({}) }
})

defineEmits(['started', 'open-workbench', 'update:draft'])
</script>
