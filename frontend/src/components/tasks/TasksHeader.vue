<template>
  <header class="relative flex flex-shrink-0 items-center justify-between gap-3 border-b border-slate-100 bg-white px-3 py-2">

    <div class="relative flex items-center gap-2 min-w-0">
      <div
        class="group flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[8px] bg-slate-900 text-white shadow-[0_2px_6px_-2px_rgba(15,23,42,0.18)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5"
      >
        <ListTodo
          :size="13"
          :stroke-width="2.1"
          class="transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:scale-110 group-hover:-rotate-[6deg]"
        />
      </div>
      <div class="min-w-0">
        <h1 class="m-0 text-[15px] font-bold leading-tight tracking-tight text-slate-900">
          任务中心
        </h1>
        <p class="m-0 mt-px text-[10.5px] leading-snug text-slate-500 truncate">
          导入处理、RJ 字幕、字幕补配、ASMR 同步与系统任务的统一视图
        </p>
      </div>
    </div>

    <div class="relative flex flex-shrink-0 items-center gap-2">
      <span class="inline-flex h-7 items-center gap-1.5 rounded-[8px] border border-slate-200 bg-white px-2.5 text-[11.5px] font-medium text-slate-500">
        <span class="relative flex h-1.5 w-1.5 items-center justify-center">
          <span class="absolute h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span class="relative inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
        </span>
        实时同步
      </span>
    </div>
  </header>
</template>

<script setup>
import { ListTodo } from 'lucide-vue-next'
</script>
