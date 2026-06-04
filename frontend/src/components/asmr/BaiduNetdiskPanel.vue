<template>
  <HttpDownloadPanel provider="baidu" :has-tasks="hasTasks" @started="$emit('started', $event)" @open-workbench="$emit('open-workbench')" />
</template>

<script setup>
import HttpDownloadPanel from './HttpDownloadPanel.vue'

defineProps({
  hasTasks: { type: Boolean, default: false }
})

defineEmits(['started', 'open-workbench'])
</script>
