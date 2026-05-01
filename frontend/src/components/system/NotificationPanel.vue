<template>
    <div class="notif-panel" :class="{ 'notif-panel--visible': visible }" :style="panelStyle" @click.stop>
      <div class="notif-panel-header">
        <span class="notif-panel-title">通知</span>
        <div class="notif-panel-actions">
          <button v-if="hasUnread" class="notif-action-btn" @click="onMarkAllRead">全部已读</button>
          <button class="notif-close-btn" @click="$emit('close')">
            <X :size="16" :stroke-width="2.2" />
          </button>
        </div>
      </div>

      <div v-if="loading" class="notif-empty">
        <Loader2 :size="24" :stroke-width="1.8" class="notif-spin" />
        <span>加载中...</span>
      </div>

      <div v-else-if="items.length === 0" class="notif-empty">
        <Bell :size="32" :stroke-width="1.4" style="opacity:0.3" />
        <span>暂无通知</span>
      </div>

      <div v-else-if="displayedItems.length === 0" class="notif-empty">
        <Bell :size="32" :stroke-width="1.4" style="opacity:0.3" />
        <span>近3天内无通知</span>
      </div>

      <div v-else class="notif-list">
        <div
          v-for="(item, index) in displayedItems"
          :key="item.id"
          class="notif-item"
          :class="[`notif-item--${item.severity}`, { 'notif-item--unread': !item.is_read, 'notif-item--read': item.is_read }]"
          :style="item.is_read ? { transitionDelay: `${index * 45}ms` } : {}"
          @click="onItemClick(item)"
        >
          <div class="notif-item-icon">
            <component :is="severityIcon(item.severity)" :size="16" :stroke-width="2.2" />
          </div>
          <div class="notif-item-body">
            <div class="notif-item-title">{{ item.title }}</div>
            <div class="notif-item-summary">{{ item.summary }}</div>
            <div class="notif-item-meta">
              <span class="notif-meta-tag notif-meta-domain">{{ domainLabel(item) }}</span>
              <span v-if="item.rjcode" class="notif-meta-tag notif-meta-rj">{{ item.rjcode }}</span>
              <span class="notif-item-time">{{ formatTime(item.created_at) }}</span>
            </div>
          </div>
          <button class="notif-item-del" @click.stop="onDelete(item.id)" title="删除">
            <X :size="12" :stroke-width="2" />
          </button>
        </div>

        <!-- 加载更多 -->
        <div v-if="hasMore || loadingMore" class="notif-load-more">
          <button v-if="!loadingMore" class="notif-load-more-btn" @click="onLoadMore">
            <ChevronDown :size="13" :stroke-width="2.2" />
            查看更多
          </button>
          <div v-else class="notif-load-more-spin">
            <Loader2 :size="14" :stroke-width="2" class="notif-spin" />
            <span>加载中...</span>
          </div>
        </div>
      </div>
    </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Bell, CheckCircle2, XCircle, AlertTriangle, Info, X, Loader2, ChevronDown } from 'lucide-vue-next'
import { useNotifications } from '../../composables/useNotifications'
import { getTaskDomainMeta } from '../common/taskDomainMeta'

const props = defineProps({
  visible: { type: Boolean, default: false },
  panelStyle: { type: Object, default: () => ({}) }
})

const emit = defineEmits(['close'])
const router = useRouter()
const { items, loading, loadingMore, hasMore, markAllRead, deleteItem, loadMore } = useNotifications()

const THREE_DAYS_MS = 3 * 24 * 60 * 60 * 1000
const displayedItems = computed(() => {
  const cutoff = Date.now() - THREE_DAYS_MS
  return items.value.filter(i => new Date(i.created_at).getTime() >= cutoff)
})

const hasUnread = computed(() => displayedItems.value.some(i => !i.is_read))

function domainLabel(item) {
  if (item.domain_label) return item.domain_label
  if (item.task_domain) return getTaskDomainMeta(item.task_domain).label
  return '任务'
}

function severityIcon(severity) {
  const map = {
    success: CheckCircle2,
    danger: XCircle,
    warning: AlertTriangle,
    info: Info,
  }
  return map[severity] || Info
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

async function onMarkAllRead() {
  await markAllRead()
}

async function onDelete(id) {
  await deleteItem(id)
}

async function onLoadMore() {
  await loadMore()
}

function onItemClick(item) {
  emit('close')
  if (item.route_path) {
    router.push({ path: item.route_path, query: item.route_query || {} })
  }
}
</script>

<style scoped>
.notif-panel {
  position: fixed;
  top: 72px;
  left: 8px;
  width: 360px;
  max-height: 520px;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(29, 29, 31, 0.08);
  border-radius: 20px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.14), 0 4px 16px rgba(0, 0, 0, 0.06);
  backdrop-filter: blur(20px);
  z-index: 99999;
  overflow: hidden;
  /* 默认隐藏，通过 --visible class 显示 */
  opacity: 0;
  transform: translateY(-10px) scale(0.97);
  pointer-events: none;
  transition: opacity 0.22s cubic-bezier(0.34, 1.56, 0.64, 1),
              transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.notif-panel--visible {
  opacity: 1;
  transform: none;
  pointer-events: all;
}

.notif-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 12px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.06);
}

.notif-panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #1d1d1f;
}

.notif-panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notif-action-btn {
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  color: #0071e3;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}

.notif-action-btn:hover {
  background: rgba(0, 113, 227, 0.08);
}

.notif-close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: rgba(29, 29, 31, 0.05);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  color: rgba(29, 29, 31, 0.54);
  transition: all 0.15s;
}

.notif-close-btn:hover {
  background: rgba(29, 29, 31, 0.1);
  color: #1d1d1f;
}

.notif-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  font-size: 14px;
  color: rgba(29, 29, 31, 0.4);
}

.notif-spin {
  animation: spin 1.2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.notif-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
  scrollbar-width: thin;
  scrollbar-color: rgba(29, 29, 31, 0.18) transparent;
  scroll-behavior: smooth;
  overscroll-behavior: contain;
}

.notif-list::-webkit-scrollbar {
  width: 6px;
}

.notif-list::-webkit-scrollbar-track {
  background: transparent;
  margin: 6px 0;
}

.notif-list::-webkit-scrollbar-thumb {
  background: rgba(29, 29, 31, 0.14);
  border-radius: 999px;
  transition: background 0.2s ease;
}

.notif-list:hover::-webkit-scrollbar-thumb {
  background: rgba(29, 29, 31, 0.28);
}

.notif-list::-webkit-scrollbar-thumb:hover {
  background: rgba(29, 29, 31, 0.4);
}

.notif-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 10px 10px 12px;
  border-radius: 12px;
  margin-bottom: 4px;
  cursor: pointer;
  transition: background 0.15s;
  position: relative;
}

.notif-item:hover {
  background: rgba(29, 29, 31, 0.04);
}

.notif-item--unread {
  background: rgba(0, 113, 227, 0.04);
}

.notif-item--unread::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 50%;
  transform: translateY(-50%);
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #0071e3;
}

.notif-item-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

.notif-item--success .notif-item-icon { color: #1f8f4e; }
.notif-item--danger .notif-item-icon { color: #d93025; }
.notif-item--warning .notif-item-icon { color: #d97706; }
.notif-item--info .notif-item-icon { color: #0071e3; }

.notif-item-body {
  flex: 1;
  min-width: 0;
}

.notif-item-title {
  font-size: 13px;
  font-weight: 600;
  color: #1d1d1f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.notif-item-summary {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.56);
  margin-top: 2px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.notif-item-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 5px;
  flex-wrap: wrap;
}

.notif-meta-tag {
  display: inline-block;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 6px;
}

.notif-meta-domain {
  background: rgba(29, 29, 31, 0.06);
  color: rgba(29, 29, 31, 0.54);
}

.notif-meta-rj {
  background: rgba(0, 113, 227, 0.08);
  color: #0055b3;
}

.notif-item-time {
  font-size: 11px;
  color: rgba(29, 29, 31, 0.38);
  margin-left: auto;
}

.notif-item-del {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  color: rgba(29, 29, 31, 0.3);
  opacity: 0;
  transition: all 0.15s;
  margin-top: 1px;
}

.notif-item:hover .notif-item-del {
  opacity: 1;
}

.notif-item-del:hover {
  background: rgba(217, 48, 37, 0.08);
  color: #d93025;
}

/* ── 加载更多 ── */
.notif-load-more {
  display: flex;
  justify-content: center;
  padding: 6px 0 4px;
}

.notif-load-more-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 14px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(29, 29, 31, 0.5);
  background: rgba(29, 29, 31, 0.04);
  border: none;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.notif-load-more-btn:hover {
  background: rgba(0, 113, 227, 0.07);
  color: #0071e3;
  transform: translateY(-1px) scale(1.02);
}

.notif-load-more-btn:active {
  transform: scale(0.96);
}

.notif-load-more-spin {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.4);
  padding: 5px 0;
}

/* ── 已读状态：整体变灰 ── */
.notif-item--read {
  opacity: 0.55;
  transition: opacity 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), background 0.15s;
}

.notif-item--read .notif-item-title {
  color: rgba(29, 29, 31, 0.5);
  font-weight: 500;
}

.notif-item--read .notif-item-icon {
  color: rgba(29, 29, 31, 0.3) !important;
}

.notif-item--read .notif-meta-rj {
  background: rgba(29, 29, 31, 0.06);
  color: rgba(29, 29, 31, 0.4);
}

.notif-item--read:hover {
  opacity: 0.75;
  background: rgba(29, 29, 31, 0.03);
}

</style>
