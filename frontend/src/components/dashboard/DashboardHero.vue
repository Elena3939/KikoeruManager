<template>
  <header class="mb-3 flex items-stretch gap-3" data-section="dashboard-hero">
    <!-- 左侧卡片：标题 + KPI -->
    <div class="relative flex min-w-0 flex-1 flex-col rounded-[12px] border border-slate-200/80 bg-white px-4 py-3 shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] transition-shadow duration-500 hover:shadow-[0_6px_16px_-10px_rgba(15,23,42,0.14)]">
      <div class="relative flex flex-wrap items-center justify-between gap-3">
        <div class="flex min-w-0 items-center gap-3">
          <div
            class="group flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[8px] bg-slate-900 text-white shadow-[0_2px_6px_-2px_rgba(15,23,42,0.18)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5"
          >
            <House
              :size="15"
              :stroke-width="2.1"
              class="transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:-rotate-[6deg] group-hover:scale-110"
            />
          </div>
          <div class="min-w-0">
            <h1 class="m-0 text-[15px] font-bold leading-tight tracking-tight text-slate-900">概览</h1>
            <p class="m-0 mt-0.5 text-[10.5px] leading-snug text-slate-500">处理队列、入库入口和最近归档</p>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <span
            class="inline-flex h-6 items-center gap-1.5 rounded-[6px] border border-slate-200 bg-white px-2 text-[10.5px] font-medium tracking-tight text-slate-600"
          >
            <span class="relative flex h-1.5 w-1.5 items-center justify-center">
              <span
                v-if="watcherRunning"
                class="absolute h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"
              />
              <span
                class="relative inline-block h-1.5 w-1.5 rounded-full"
                :class="watcherRunning ? 'bg-emerald-500' : 'bg-slate-400'"
              />
            </span>
            {{ watcherRunning ? '监视中' : '已停止' }}
          </span>

          <button
            type="button"
            class="dash-icon-btn group inline-flex h-6 w-6 cursor-pointer items-center justify-center rounded-[6px] border border-slate-200 bg-white text-slate-600 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:translate-y-0 active:scale-95 disabled:pointer-events-none disabled:opacity-50"
            :disabled="loading"
            aria-label="刷新概览"
            @click="$emit('refresh')"
          >
            <span class="dash-icon-swap relative inline-flex h-[11px] w-[11px] items-center justify-center">
              <RefreshCw
                :size="11"
                :stroke-width="2.3"
                :class="loading ? 'animate-spin' : 'dash-icon-default'"
              />
              <RotateCw v-if="!loading" :size="11" :stroke-width="2.3" class="dash-icon-hover" />
            </span>
          </button>
        </div>
      </div>

      <!-- KPI 指标栅格 -->
      <div class="relative mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-6">
        <button
          v-for="(item, index) in kpiCards"
          :key="item.key"
          type="button"
          class="dash-kpi group relative inline-flex h-9 cursor-pointer items-center gap-1.5 overflow-hidden rounded-[10px] border border-slate-200 bg-white pl-1.5 pr-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-[0_4px_10px_-4px_rgba(15,23,42,0.18)] active:translate-y-0 active:scale-95"
          :style="{ animationDelay: `${index * 40}ms` }"
          @click="$emit('kpi-click', item)"
        >
          <span
            class="inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-[7px] border border-slate-200 bg-white transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-[6deg]"
          >
            <span class="dash-icon-swap relative inline-flex h-[13px] w-[13px] items-center justify-center">
              <component :is="item.icon" :size="13" :stroke-width="1.8" :class="['dash-icon-default', kpiIconColorClass(item.key)]" />
              <ArrowUpRight :size="13" :stroke-width="2.1" class="dash-icon-hover text-slate-900" />
            </span>
          </span>
          <span class="min-w-0 flex-1 truncate text-left text-[12px] font-bold leading-none tracking-tight text-slate-800">{{ item.label }}</span>
          <span
            class="inline-flex h-5 min-w-[1.25rem] flex-shrink-0 items-center justify-center rounded-[5px] bg-slate-100 px-1.5 text-[10.5px] font-bold tabular-nums text-slate-500 transition-colors duration-300 group-hover:bg-slate-900 group-hover:text-white"
          >
            {{ item.value }}
          </span>
        </button>
      </div>
    </div>

    <!-- 右侧独立卡片：上传区域 -->
    <div class="flex w-[260px] flex-shrink-0 flex-col justify-center rounded-[12px] border border-slate-200/80 bg-white px-3 py-3 shadow-[0_2px_8px_-6px_rgba(15,23,42,0.08)] transition-shadow duration-500 hover:shadow-[0_6px_16px_-10px_rgba(15,23,42,0.14)]">
      <FileUploader compact @upload-success="$emit('upload-success')" />
    </div>
  </header>
</template>

<script setup>
import { ArrowUpRight, House, RefreshCw, RotateCw } from 'lucide-vue-next'
import FileUploader from '../FileUploader.vue'

defineProps({
  watcherRunning: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  kpiCards: { type: Array, default: () => [] },
})

defineEmits(['refresh', 'kpi-click', 'upload-success'])

function kpiIconColorClass(key) {
  if (key === 'import') return 'text-amber-600'
  if (key === 'rj') return 'text-sky-600'
  if (key === 'subtitle') return 'text-violet-600'
  if (key === 'asmr') return 'text-emerald-600'
  if (key === 'upload') return 'text-blue-600'
  if (key === 'conflicts') return 'text-rose-600'
  return 'text-slate-500'
}

function kpiIconBgClass(key) {
  if (key === 'import') return 'bg-amber-50'
  if (key === 'rj') return 'bg-sky-50'
  if (key === 'subtitle') return 'bg-violet-50'
  if (key === 'asmr') return 'bg-emerald-50'
  if (key === 'upload') return 'bg-blue-50'
  if (key === 'conflicts') return 'bg-rose-50'
  return 'bg-slate-100'
}
</script>

<style scoped>
/* hover 切图标：默认图标 fade+上滑出，hover 图标 fade+从下滑入 */
.dash-icon-swap > .dash-icon-default,
.dash-icon-swap > .dash-icon-hover {
  position: absolute;
  inset: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.28s ease, transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.dash-icon-swap > .dash-icon-default {
  opacity: 1;
  transform: translateY(0) rotate(0deg);
}
.dash-icon-swap > .dash-icon-hover {
  opacity: 0;
  transform: translateY(8px) rotate(-12deg);
}
.group:hover .dash-icon-swap > .dash-icon-default {
  opacity: 0;
  transform: translateY(-8px) rotate(12deg);
}
.group:hover .dash-icon-swap > .dash-icon-hover {
  opacity: 1;
  transform: translateY(0) rotate(0deg);
}
</style>
