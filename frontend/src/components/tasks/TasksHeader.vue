<template>
  <AppPageHeader
    :icon="ListTodo"
    icon-color="#2563eb"
    title="任务中心"
    subtitle="导入处理、RJ 字幕、字幕补配、ASMR 同步与系统任务的统一视图"
  >
    <span class="inline-flex h-8 items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 shadow-sm">
      <span class="relative flex h-1.5 w-1.5 items-center justify-center">
        <span class="absolute h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span class="relative inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
      </span>
      实时同步
    </span>
  </AppPageHeader>
</template>

<script setup>
import { ListTodo } from 'lucide-vue-next'
import AppPageHeader from '../common/AppPageHeader.vue'
</script>
