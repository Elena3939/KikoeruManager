<template>
  <button
    type="button"
    class="lib-mobile-card"
    :class="{
      'is-located': isLocated,
      'is-context-active': isContextActive,
      'is-operating': isOperating,
      'is-directory': row?.is_directory,
    }"
    @click="onClick"
    @contextmenu="onContextMenu"
  >
    <span class="lib-mobile-card-icon-shell">
      <component
        :is="iconComponent"
        class="lib-mobile-card-icon"
        :class="iconClass"
        :size="22"
        :stroke-width="2.2"
      />
    </span>

    <div class="lib-mobile-card-main">
      <div class="lib-mobile-card-title-row">
        <!-- v-html 用来支持 renderLibrarySearchHighlight 输出的 <mark> 标签 -->
        <span class="lib-mobile-card-name" v-html="nameHtml"></span>
        <span v-if="row?.rjcode" class="lib-mobile-card-rj">{{ row.rjcode }}</span>
      </div>

      <div class="lib-mobile-card-meta">
        <span v-if="sizeText" class="lib-mobile-card-meta-size">{{ sizeText }}</span>
        <span v-if="sizeText && timeText" class="lib-mobile-card-meta-divider">·</span>
        <span v-if="timeText" class="lib-mobile-card-meta-time">{{ timeText }}</span>
      </div>

      <div v-if="searchSourceLabel" class="lib-mobile-card-source">
        <Database :size="11" :stroke-width="2.4" class="lib-mobile-card-source-icon" />
        <span>来源库：{{ searchSourceLabel }}</span>
      </div>
    </div>

    <span
      role="button"
      class="lib-mobile-card-menu"
      :title="row?.is_directory ? '更多操作' : '更多操作'"
      @click.stop="onMenuClick"
      @contextmenu.stop.prevent="onMenuClick"
    >
      <MoreVertical :size="16" :stroke-width="2.2" />
    </span>
  </button>
</template>

<script setup>
import { Database, MoreVertical } from 'lucide-vue-next'

defineOptions({ name: 'LibraryMobileCard' })

const props = defineProps({
  row: { type: Object, required: true },
  iconComponent: { type: [Object, Function], required: true },
  iconClass: { type: String, default: '' },
  // 父组件已经过 renderLibrarySearchHighlight 处理的 HTML 字符串
  nameHtml: { type: String, default: '' },
  sizeText: { type: String, default: '' },
  timeText: { type: String, default: '' },
  searchSourceLabel: { type: String, default: '' },
  isLocated: { type: Boolean, default: false },
  isContextActive: { type: Boolean, default: false },
  isOperating: { type: Boolean, default: false },
})

const emit = defineEmits(['card-click', 'card-contextmenu', 'menu-click'])

function onClick(event) {
  emit('card-click', { row: props.row, event })
}

function onContextMenu(event) {
  emit('card-contextmenu', { row: props.row, event })
}

function onMenuClick(event) {
  // 把 click 转成 contextmenu 一样的语义，由父级用 ⋮ 按钮的位置弹菜单
  emit('menu-click', { row: props.row, event })
}
</script>

<style scoped>
/*
 * 库存移动端卡片
 * 桌面零改动：本组件只在 ≤640 由 Library.vue v-if 切入；样式自带，桌面不会渲染。
 * 视觉：图标 + 名称 / RJ + 大小·时间 + 右上角 ⋮，整张卡片可点（hover 上浮 + 边框轻染）。
 */
.lib-mobile-card {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) 28px;
  align-items: start;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: 1px solid rgb(226 232 240);
  border-radius: 12px;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.lib-mobile-card:hover {
  border-color: rgb(203 213 225);
  background: rgb(248 250 252);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}

.lib-mobile-card:active {
  transform: scale(0.99);
}

/* 状态态：搜索定位（与 el-table 保持一致的浅蓝） */
.lib-mobile-card.is-located {
  border-color: rgb(147 197 253);
  background: linear-gradient(180deg, #eef7ff 0%, #ffffff 100%);
}

/* 右键菜单激活态 */
.lib-mobile-card.is-context-active {
  border-color: rgb(148 163 184);
  background: rgb(241 245 249);
}

/* 操作执行中：流光（与 el-table 的 library-row-operating 呼应） */
.lib-mobile-card.is-operating {
  background:
    linear-gradient(
      105deg,
      rgba(239, 246, 255, 0.98) 0%,
      rgba(219, 234, 254, 0.92) 24%,
      rgba(96, 165, 250, 0.45) 42%,
      rgba(191, 219, 254, 0.86) 58%,
      rgba(147, 197, 253, 0.42) 72%,
      rgba(239, 246, 255, 0.98) 100%
    );
  background-size: 300% 100%;
  animation: lib-mobile-card-flow 1.25s linear infinite;
}

@keyframes lib-mobile-card-flow {
  0% { background-position: 0% 0; }
  100% { background-position: 300% 0; }
}

/* 图标格 */
.lib-mobile-card-icon-shell {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  border-radius: 10px;
  background: rgb(248 250 252);
  color: rgb(100 116 139);
  margin-top: 2px;
}

/*
 * lucide-vue-next 输出的 <svg> 用 currentColor，需要把 .file-icon.icon-* 的颜色规则同步过来。
 * 这些 class 由 Library.vue 的 getLibraryRowIconClass(row) 输出，与桌面 .file-icon 共用。
 */
.lib-mobile-card-icon { transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.lib-mobile-card-icon.icon-dir,
.lib-mobile-card-icon.icon-folder { color: #f6b73c; fill: currentColor; stroke: currentColor; }
.lib-mobile-card-icon.icon-audio-lossless { color: #2563eb; }
.lib-mobile-card-icon.icon-audio { color: #7c3aed; }
.lib-mobile-card-icon.icon-image { color: #f97316; }
.lib-mobile-card-icon.icon-video { color: #6366f1; }
.lib-mobile-card-icon.icon-pdf { color: #dc2626; }
.lib-mobile-card-icon.icon-archive { color: #d97706; }
.lib-mobile-card-icon.icon-text { color: #64748b; }
.lib-mobile-card-icon.icon-file { color: #94a3b8; }

.lib-mobile-card.is-operating .lib-mobile-card-icon {
  transform: rotate(-8deg) scale(1.08);
  filter: drop-shadow(0 4px 8px rgba(37, 99, 235, 0.18));
}

/* 主区 */
.lib-mobile-card-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.lib-mobile-card-title-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.lib-mobile-card-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  white-space: normal;
  word-break: break-all;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  color: #1d1d1f;
}

.lib-mobile-card-rj {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.02em;
  font-feature-settings: 'tnum' 1;
  color: #1d4ed8;
  background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%);
  border: 1px solid rgba(29, 78, 216, 0.18);
  border-radius: 999px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.4);
}

.lib-mobile-card-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 6px;
  font-size: 11px;
  color: rgb(100 116 139);
  font-feature-settings: 'tnum' 1;
}

.lib-mobile-card-meta-divider {
  color: rgb(203 213 225);
  user-select: none;
}

.lib-mobile-card-source {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 2px;
  padding: 2px 8px;
  align-self: flex-start;
  border-radius: 999px;
  background: rgb(241 245 249);
  color: rgb(71 85 105);
  font-size: 10.5px;
  line-height: 1.4;
}

.lib-mobile-card-source-icon {
  flex: 0 0 11px;
}

/* 右上角 ⋮ 按钮（用 span+role 避免 button 套 button） */
.lib-mobile-card-menu {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  margin-top: 2px;
  border-radius: 8px;
  background: transparent;
  color: rgb(100 116 139);
  cursor: pointer;
  transition: background-color 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

.lib-mobile-card-menu:hover {
  background: rgb(241 245 249);
  color: rgb(15 23 42);
}

.lib-mobile-card-menu:active {
  transform: scale(0.92);
}

/* 高亮 mark（来自 renderLibrarySearchHighlight） */
.lib-mobile-card-name :deep(mark),
.lib-mobile-card-name :deep(.library-search-mark) {
  background: #fff1a8;
  color: #7a4b00;
  padding: 0 2px;
  border-radius: 4px;
}
</style>
