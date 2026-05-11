<template>
  <section class="mb-3 grid grid-cols-2 items-stretch gap-2 sm:flex sm:flex-wrap sm:items-center" data-section="dashboard-command">
      <!-- 主操作：扫描 -->
      <button
        type="button"
        class="dash-cmd-btn group inline-flex h-9 w-full cursor-pointer items-center justify-center gap-1.5 rounded-[9px] bg-blue-600 px-3.5 text-[13px] font-semibold text-white shadow-[0_1px_4px_rgba(37,99,235,0.3)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:bg-blue-700 active:translate-y-0 active:scale-95 disabled:pointer-events-none disabled:opacity-60 sm:w-auto sm:justify-start"
        :disabled="scanning"
        @click="$emit('scan')"
      >
        <span class="dash-icon-swap relative inline-flex h-[15px] w-[15px] items-center justify-center">
          <Search
            v-if="!scanning"
            :size="15"
            :stroke-width="2"
            class="dash-icon-default"
          />
          <Search
            v-else
            :size="15"
            :stroke-width="2"
            class="animate-spin"
          />
          <SearchCheck v-if="!scanning" :size="15" :stroke-width="2" class="dash-icon-hover" />
        </span>
        <span>{{ scanning ? '扫描中' : '扫描处理' }}</span>
      </button>

      <!-- 监视器开关 -->
      <button
        type="button"
        class="dash-cmd-btn group inline-flex h-9 w-full cursor-pointer items-center justify-center gap-1.5 rounded-[9px] border border-slate-200 bg-white px-3.5 text-[13px] font-medium text-slate-700 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:translate-y-0 active:scale-95 sm:w-auto sm:justify-start"
        @click="$emit('toggle-watcher')"
      >
        <span class="dash-icon-swap relative inline-flex h-[15px] w-[15px] items-center justify-center">
          <component
            :is="watcherRunning ? PauseCircle : PlayCircle"
            :size="15"
            :stroke-width="2"
            :class="['dash-icon-default', watcherRunning ? 'text-emerald-600' : 'text-slate-500']"
          />
          <component
            :is="watcherRunning ? StopCircle : Play"
            :size="15"
            :stroke-width="2"
            :class="['dash-icon-hover', watcherRunning ? 'text-rose-600' : 'text-emerald-600']"
          />
        </span>
        <span>{{ watcherRunning ? '停止监视' : '启动监视' }}</span>
      </button>

      <div class="mx-1 hidden h-5 w-px bg-slate-200 sm:block" aria-hidden="true" />

      <!-- 问题作品 -->
      <button
        type="button"
        class="dash-cmd-btn group inline-flex h-9 w-full cursor-pointer items-center justify-center gap-1.5 rounded-[9px] border border-slate-200 bg-white px-3.5 text-[13px] font-medium text-slate-700 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:translate-y-0 active:scale-95 sm:w-auto sm:justify-start"
        @click="$emit('go', '/conflicts')"
      >
        <span class="dash-icon-swap relative inline-flex h-[15px] w-[15px] items-center justify-center">
          <AlertTriangle :size="15" :stroke-width="2" class="dash-icon-default text-rose-500" />
          <ShieldAlert :size="15" :stroke-width="2" class="dash-icon-hover text-rose-600" />
        </span>
        <span>问题作品</span>
      </button>

      <!-- 任务中心 -->
      <button
        type="button"
        class="dash-cmd-btn group inline-flex h-9 w-full cursor-pointer items-center justify-center gap-1.5 rounded-[9px] border border-slate-200 bg-white px-3.5 text-[13px] font-medium text-slate-700 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:translate-y-0 active:scale-95 sm:w-auto sm:justify-start"
        @click="$emit('go', '/tasks')"
      >
        <span class="dash-icon-swap relative inline-flex h-[15px] w-[15px] items-center justify-center">
          <ListChecks :size="15" :stroke-width="2" class="dash-icon-default text-indigo-500" />
          <ListTodo :size="15" :stroke-width="2" class="dash-icon-hover text-indigo-600" />
        </span>
        <span>任务中心</span>
      </button>
  </section>
</template>

<script setup>
import {
  AlertTriangle,
  ListChecks,
  ListTodo,
  PauseCircle,
  Play,
  PlayCircle,
  Search,
  SearchCheck,
  ShieldAlert,
  StopCircle,
} from 'lucide-vue-next'

defineProps({
  scanning: { type: Boolean, default: false },
  watcherRunning: { type: Boolean, default: false },
})

defineEmits(['scan', 'toggle-watcher', 'go'])
</script>

<style scoped>
/* hover 切图标动画 */
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
  transform: translateY(0) rotate(0deg) scale(1);
}
.dash-icon-swap > .dash-icon-hover {
  opacity: 0;
  transform: translateY(8px) rotate(-12deg) scale(0.9);
}
.group:hover .dash-icon-swap > .dash-icon-default {
  opacity: 0;
  transform: translateY(-8px) rotate(12deg) scale(0.9);
}
.group:hover .dash-icon-swap > .dash-icon-hover {
  opacity: 1;
  transform: translateY(0) rotate(0deg) scale(1.1);
}
</style>
