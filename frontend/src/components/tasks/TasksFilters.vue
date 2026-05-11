<template>
  <section class="tasks-toolbar">
    <!-- 单行工具栏：搜索 + 类型 + 状态 + 排序 + 仅活跃 + 重置 -->
    <div class="tasks-toolbar-row">
      <!-- 搜索框（撑满） -->
      <div class="tasks-toolbar-search">
        <Search :size="14" :stroke-width="2.2" class="tasks-toolbar-search-icon" />
        <input
          :value="searchQuery"
          type="text"
          placeholder="搜索标题、RJ、路径、当前步骤"
          class="tasks-toolbar-search-input"
          @input="$emit('update:searchQuery', $event.target.value)"
        />
        <button
          v-if="searchQuery"
          type="button"
          class="tasks-toolbar-search-clear"
          title="清空"
          @click="$emit('update:searchQuery', '')"
        >
          <X :size="12" :stroke-width="2.6" />
        </button>
      </div>

      <!-- 类型 dropdown -->
      <AppDropdown
        :model-value="currentDomain"
        :options="domainDropdownOptions"
        label="类型"
        :width="172"
        :menu-min-width="200"
        @update:model-value="$emit('update:currentDomain', $event)"
      />

      <!-- 状态 dropdown -->
      <AppDropdown
        :model-value="currentStatus"
        :options="statusDropdownOptions"
        label="状态"
        :width="148"
        :menu-min-width="160"
        @update:model-value="$emit('update:currentStatus', $event)"
      />

      <!-- 排序 dropdown -->
      <AppDropdown
        :model-value="sortKey"
        :options="sortDropdownOptions"
        label="排序"
        :width="160"
        :menu-min-width="160"
        @update:model-value="$emit('update:sortKey', $event)"
      />

      <!-- 仅活跃 toggle -->
      <button
        type="button"
        class="tasks-toolbar-btn"
        :class="{ 'is-on': activeOnly }"
        @click="$emit('update:activeOnly', !activeOnly)"
      >
        <span class="relative flex h-1.5 w-1.5 items-center justify-center">
          <span
            v-if="activeOnly"
            class="absolute h-full w-full animate-ping rounded-full bg-emerald-400/50"
          />
          <span
            class="relative inline-block h-1.5 w-1.5 rounded-full"
            :class="activeOnly ? 'bg-emerald-500' : 'bg-slate-400'"
          />
        </span>
        {{ activeOnly ? '仅活跃' : '全部' }}
      </button>

      <!-- 重置 -->
      <button
        type="button"
        class="tasks-toolbar-btn"
        title="清空所有筛选条件"
        @click="$emit('reset')"
      >
        <FilterX :size="13" :stroke-width="2.2" />
        重置
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { FilterX, Search, X } from 'lucide-vue-next'
import AppDropdown from '../common/AppDropdown.vue'

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

const domainDropdownOptions = computed(() =>
  (props.domainOptions || []).map((opt) => {
    const count = opt.value === 'all' ? 0 : Number(props.getDomainCount(opt.value) || 0)
    return {
      value: opt.value,
      label: opt.label,
      suffix: count > 0 ? String(count) : '',
    }
  }),
)

const statusDropdownOptions = computed(() =>
  (props.statusOptions || []).map((opt) => ({
    value: opt.value,
    label: opt.label,
  })),
)

const sortDropdownOptions = [
  { value: 'updated_desc', label: '最近更新' },
  { value: 'created_desc', label: '最近创建' },
  { value: 'progress_desc', label: '进度优先' },
  { value: 'status_priority', label: '状态优先' },
]
</script>

<style scoped>
/* ============================================================
 * 任务中心工具栏：单行布局
 * 搜索 + 类型 select + 状态 select + 排序 select + 仅活跃 + 重置
 * ============================================================ */

.tasks-toolbar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  padding: 10px 12px;
  margin-bottom: 12px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.9);
  box-shadow: 0 2px 8px -6px rgba(15, 23, 42, 0.08);
}

/* ---- 单行 ：搜索撑满，右侧控件依次排列 ---- */
.tasks-toolbar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
}

.tasks-toolbar-search {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 36px 0 34px;
  border-radius: 10px;
  background: rgb(248 250 252);
  border: 1px solid rgb(226 232 240);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}

.tasks-toolbar-search:hover {
  background: #fff;
  border-color: rgb(203 213 225);
}

.tasks-toolbar-search:focus-within {
  background: #fff;
  border-color: rgb(100 116 139);
  box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.18);
}

.tasks-toolbar-search-icon {
  position: absolute;
  left: 11px;
  color: rgba(100, 116, 139, 0.85);
  pointer-events: none;
}

.tasks-toolbar-search-input {
  width: 100%;
  height: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 13px;
  color: #0f172a;
}
.tasks-toolbar-search-input::placeholder {
  color: rgba(100, 116, 139, 0.78);
}

.tasks-toolbar-search-clear {
  position: absolute;
  right: 8px;
  width: 20px;
  height: 20px;
  border: 0;
  background: transparent;
  color: rgba(100, 116, 139, 0.78);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  transition: background-color 0.2s ease, color 0.2s ease;
}
.tasks-toolbar-search-clear:hover {
  background: rgba(15, 23, 42, 0.06);
  color: #0f172a;
}


/* ---- 工具栏右侧按钮（仅活跃 / 重置）---- */
.tasks-toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid rgb(226 232 240);
  border-radius: 10px;
  background: #ffffff;
  color: rgb(51 65 85);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.tasks-toolbar-btn:hover {
  transform: translateY(-1px);
  border-color: rgb(148 163 184);
  color: #0f172a;
  background: rgb(248 250 252);
  box-shadow: 0 4px 10px -6px rgba(15, 23, 42, 0.18);
}
.tasks-toolbar-btn:active {
  transform: translateY(0) scale(0.97);
}
.tasks-toolbar-btn.is-on {
  background: #0f172a;
  color: #fff;
  border-color: #0f172a;
  box-shadow: 0 6px 14px -8px rgba(15, 23, 42, 0.42);
}
.tasks-toolbar-btn.is-on:hover {
  background: #1e293b;
}

@media (max-width: 1080px) {
  .tasks-toolbar-row {
    flex-wrap: wrap;
  }
  .tasks-toolbar-search {
    flex: 1 1 100%;
    order: -1;
  }
}

/* ≤640：4 列 grid，3 个 dropdown + 2 个按钮按 nth-child 排成 3 行
 * 行 1: 搜索 (1/-1，独占整行)
 * 行 2: 类型 (1-3) | 状态 (3-5)
 * 行 3: 排序 (1-3) | 全部 (3-4) | 重置 (4-5)
 * 桌面零改动：所有规则只在 @media 内
 */
@media (max-width: 640px) {
  .tasks-toolbar {
    padding: 6px;
    border-radius: 12px;
  }
  .tasks-toolbar-row {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 6px;
    align-items: stretch;
  }
  .tasks-toolbar-search {
    grid-column: 1 / -1;
    height: 34px;
    flex: 0 0 auto;
  }
  /* nth-child(1) 是搜索框，已经 grid-column 处理 */
  /* nth-child(2) = 类型 dropdown */
  .tasks-toolbar-row > :nth-child(2) { grid-column: 1 / 3; }
  /* nth-child(3) = 状态 dropdown */
  .tasks-toolbar-row > :nth-child(3) { grid-column: 3 / 5; }
  /* nth-child(4) = 排序 dropdown */
  .tasks-toolbar-row > :nth-child(4) { grid-column: 1 / 3; }
  /* nth-child(5) = 仅活跃 toggle */
  .tasks-toolbar-row > :nth-child(5) { grid-column: 3 / 4; }
  /* nth-child(6) = 重置 btn */
  .tasks-toolbar-row > :nth-child(6) { grid-column: 4 / 5; }

  /* 让所有 AppDropdown / 工具栏按钮强制撑满 grid 单元 */
  .tasks-toolbar-row :deep(.app-dd-root),
  .tasks-toolbar-row :deep(.app-dd-trigger),
  .tasks-toolbar-row .tasks-toolbar-btn {
    width: 100% !important;
    min-width: 0 !important;
  }
  .tasks-toolbar-row :deep(.app-dd-trigger) {
    justify-content: space-between;
  }
  .tasks-toolbar-btn {
    height: 34px;
    padding: 0 6px;
    gap: 4px;
    justify-content: center;
    font-size: 12px;
  }
}
</style>
