<template>
  <section class="flex flex-shrink-0 flex-col gap-3 px-5 pb-4 pt-0">
    <!-- 第一行：任务类型 + 操作工具 -->
    <div class="flex flex-wrap items-center gap-3">
      <el-radio-group
        :model-value="currentDomain"
        size="small"
        class="tasks-domain-tabs flex flex-wrap gap-1"
        @update:model-value="$emit('update:currentDomain', $event)"
      >
        <el-radio-button
          v-for="option in domainOptions"
          :key="option.value"
          :value="option.value"
          class="tasks-domain-tab"
        >
          <span class="inline-flex items-center gap-1.5">
            <component
              :is="option.icon"
              :size="12"
              :stroke-width="2.2"
              :class="domainIconClass(option.value)"
            />
            <span>{{ option.label }}</span>
            <span
              v-if="option.value !== 'all' && getDomainCount(option.value)"
              class="tasks-domain-count inline-flex h-4 min-w-[16px] items-center justify-center rounded-[4px] px-1 text-[10px] font-bold tabular-nums"
              :class="currentDomain === option.value ? 'tasks-domain-count--on' : 'tasks-domain-count--off'"
            >
              {{ getDomainCount(option.value) }}
            </span>
          </span>
        </el-radio-button>
      </el-radio-group>

      <div class="ml-auto flex flex-shrink-0 items-center gap-2">
        <el-input
          :model-value="searchQuery"
          size="small"
          placeholder="搜索标题、RJ、路径、当前步骤"
          clearable
          class="tasks-search"
          @update:model-value="$emit('update:searchQuery', $event)"
        >
          <template #prefix>
            <Search :size="13" :stroke-width="2.2" class="text-slate-400" />
          </template>
        </el-input>

        <el-select
          :model-value="sortKey"
          size="small"
          class="tasks-sort"
          @update:model-value="$emit('update:sortKey', $event)"
        >
          <el-option label="最近更新" value="updated_desc" />
          <el-option label="最近创建" value="created_desc" />
          <el-option label="进度优先" value="progress_desc" />
          <el-option label="状态优先" value="status_priority" />
        </el-select>

        <el-button
          :class="['tasks-active-btn', activeOnly ? 'is-on' : '']"
          size="small"
          @click="$emit('update:activeOnly', !activeOnly)"
        >
          <template #icon>
            <span class="relative flex h-2 w-2 items-center justify-center">
              <span
                v-if="activeOnly"
                class="absolute h-full w-full animate-ping rounded-full bg-white/50"
              />
              <span class="relative inline-block h-2 w-2 rounded-full" :class="activeOnly ? 'bg-emerald-400' : 'bg-slate-400'" />
            </span>
          </template>
          {{ activeOnly ? '仅活跃' : '全部' }}
        </el-button>

        <el-button
          class="tasks-reset-btn"
          plain
          size="small"
          title="清空所有筛选条件"
          @click="$emit('reset')"
        >
          <template #icon>
            <FilterX :size="13" :stroke-width="2.2" />
          </template>
          重置
        </el-button>
      </div>
    </div>

    <!-- 第二行：任务状态 -->
    <div class="flex flex-wrap items-center gap-3">
      <el-radio-group
        :model-value="currentStatus"
        size="small"
        class="tasks-status-tabs flex flex-wrap gap-1"
        @update:model-value="$emit('update:currentStatus', $event)"
      >
        <el-radio-button
          v-for="option in statusOptions"
          :key="option.value"
          :value="option.value"
          class="tasks-status-tab"
        >
          {{ option.label }}
        </el-radio-button>
      </el-radio-group>
    </div>
  </section>
</template>

<script setup>
import { FilterX, Search } from 'lucide-vue-next'
import { getTaskDomainMeta } from '../common/taskDomainMeta.js'

const props = defineProps({
  domainOptions: { type: Array, default: () => [] },
  statusOptions: { type: Array, default: () => [] },
  currentDomain: { type: String, default: 'all' },
  currentStatus: { type: String, default: 'all' },
  searchQuery: { type: String, default: '' },
  sortKey: { type: String, default: 'updated_desc' },
  activeOnly: { type: Boolean, default: false },
  getDomainCount: { type: Function, required: true },
})

defineEmits([
  'update:currentDomain',
  'update:currentStatus',
  'update:searchQuery',
  'update:sortKey',
  'update:activeOnly',
  'reset',
])

function domainIconClass(value) {
  const isActive = props.currentDomain === value
  if (isActive) {
    return 'text-white'
  }
  if (value === 'all') return 'text-slate-500'
  return getTaskDomainMeta(value).chipIcon || 'text-slate-500'
}
</script>

<style scoped>
/* domain / status tabs：chip 风格 */
.tasks-domain-tabs :deep(.el-radio-button),
.tasks-status-tabs :deep(.el-radio-button) {
  margin: 0;
}

.tasks-domain-tabs :deep(.el-radio-button__inner),
.tasks-status-tabs :deep(.el-radio-button__inner) {
  height: 26px;
  padding: 0 10px;
  font-size: 11.5px;
  font-weight: 500;
  line-height: 24px;
  border-radius: 8px !important;
  border: 1px solid rgb(226 232 240);
  background: #fff;
  color: rgb(71 85 105);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.tasks-domain-tabs :deep(.el-radio-button__inner:hover),
.tasks-status-tabs :deep(.el-radio-button__inner:hover) {
  transform: translateY(-1px);
  color: rgb(15 23 42);
  border-color: rgb(203 213 225);
  background: rgb(248 250 252);
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.18);
}

.tasks-domain-tabs :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner),
.tasks-status-tabs :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  color: #fff;
  background: rgb(15 23 42);
  border-color: rgb(15 23 42);
  box-shadow: 0 2px 6px -2px rgba(15, 23, 42, 0.35);
}

.tasks-domain-tabs :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner:hover),
.tasks-status-tabs :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner:hover) {
  background: rgb(30 41 59);
}

/* domain 计数 */
.tasks-domain-count--on {
  background: rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.92);
}
.tasks-domain-count--off {
  background: rgb(241 245 249);
  color: rgb(71 85 105);
}

/* 搜索框 */
.tasks-search {
  width: 240px;
}
.tasks-search :deep(.el-input__wrapper) {
  height: 28px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 0 0 1px rgb(226 232 240) inset, 0 1px 2px rgba(15, 23, 42, 0.04);
  padding: 0 10px;
  transition: box-shadow 0.3s ease;
}
.tasks-search :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgb(203 213 225) inset, 0 1px 2px rgba(15, 23, 42, 0.04);
}
.tasks-search :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px rgb(148 163 184) inset, 0 0 0 3px rgb(241 245 249);
}
.tasks-search :deep(.el-input__inner) {
  height: 26px;
  font-size: 11.5px;
  color: rgb(30 41 59);
}
.tasks-search :deep(.el-input__inner::placeholder) {
  color: rgb(148 163 184);
}
.tasks-search :deep(.el-input__prefix) {
  margin-right: 4px;
}

/* 排序选择 */
.tasks-sort {
  width: 120px;
}
.tasks-sort :deep(.el-select__wrapper) {
  min-height: 28px;
  height: 28px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 0 0 1px rgb(226 232 240) inset, 0 1px 2px rgba(15, 23, 42, 0.04);
  padding: 0 10px;
  font-size: 11.5px;
  font-weight: 500;
  color: rgb(51 65 85);
  transition: box-shadow 0.3s ease;
}
.tasks-sort :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px rgb(203 213 225) inset, 0 1px 2px rgba(15, 23, 42, 0.04);
}
.tasks-sort :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px rgb(148 163 184) inset, 0 0 0 3px rgb(241 245 249);
}

/* 仅活跃 / 全部 */
.tasks-active-btn {
  --el-button-size: 28px;
  height: 28px;
  padding: 0 10px;
  margin: 0 !important;
  border-radius: 8px;
  border: 1px solid rgb(226 232 240);
  background: #fff;
  color: rgb(51 65 85);
  font-size: 11.5px;
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.tasks-active-btn :deep(.el-icon) {
  margin-right: 4px;
}
.tasks-active-btn:hover {
  transform: translateY(-1px);
  color: rgb(15 23 42);
  border-color: rgb(203 213 225);
  background: rgb(248 250 252);
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.18);
}
.tasks-active-btn:active {
  transform: translateY(0) scale(0.96);
}
.tasks-active-btn.is-on {
  border-color: rgb(15 23 42);
  background: rgb(15 23 42);
  color: #fff;
  box-shadow: 0 2px 6px -2px rgba(15, 23, 42, 0.35);
}
.tasks-active-btn.is-on:hover {
  background: rgb(30 41 59);
}

/* 重置 */
.tasks-reset-btn {
  --el-button-size: 28px;
  height: 28px;
  min-height: 28px;
  padding: 0 10px;
  margin: 0 !important;
  border-radius: 8px;
  border: 1px solid rgb(226 232 240);
  color: rgb(71 85 105);
  background: #fff;
  font-size: 11.5px;
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.tasks-reset-btn :deep(.el-icon) {
  margin-right: 4px;
}
.tasks-reset-btn:hover {
  transform: translateY(-1px);
  color: rgb(15 23 42);
  border-color: rgb(203 213 225);
  background: rgb(248 250 252);
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.18);
}
.tasks-reset-btn:active {
  transform: translateY(0) scale(0.96);
}
</style>
