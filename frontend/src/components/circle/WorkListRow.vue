<script setup>
import { computed } from 'vue'
import { LibraryBig, Server, X, PackageCheck, Layers, ExternalLink, Calendar } from 'lucide-vue-next'

const props = defineProps({
  /** 作品数据对象 */
  item: { type: Object, required: true },
  /** 行在列表中的索引，用于入场动画延迟 */
  rowIndex: { type: Number, default: 0 },
  /** 是否选中 */
  selected: { type: Boolean, default: false },
  /** 是否处于状态闪烁中 */
  statusFlash: { type: Boolean, default: false },
  /** 是否禁用 */
  disabled: { type: Boolean, default: false },
  /** 封面图字段名 */
  imageField: { type: String, default: 'image_url' },
  /** 标识字段名（用于 RJ 号显示） */
  codeField: { type: String, default: '' },
  /** 角标文字，空则不显示 */
  cornerLabel: { type: String, default: '' },
})

const emit = defineEmits(['select', 'preview', 'reimport'])

const displayCode = computed(() => {
  if (props.codeField) return props.item[props.codeField]
  return props.item.source_compare?.work_rjcode || props.item.canonical_rjcode || props.item.rjcode || ''
})
const variantLabel = computed(() =>
  props.item.preferred_variant?.group_short_label || '原作'
)
const downloadRjcode = computed(() =>
  props.item.download_plan?.rjcode || props.item.display_rjcode || props.item.canonical_rjcode || ''
)

const isNewWork = computed(() =>
  Array.isArray(props.item.source_tags) && props.item.source_tags.includes('email_watcher')
)

const isUnreleased = computed(() => {
  if (props.item.is_unreleased) return true
  const value = String(props.item.release_date || props.item.date || props.item.release_at || '').trim()
  if (!value) return true
  const match = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
  if (!match) return false
  const releaseDate = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3] || 1))
  const today = new Date(); today.setHours(0, 0, 0, 0)
  return releaseDate > today
})

/** CV 名列表，用 / 拼接 */
const cvLabel = computed(() => {
  const cvs = props.item.cvs
  if (!Array.isArray(cvs) || cvs.length === 0) return ''
  return cvs.join(' / ')
})

/**
 * DLsite 列表小图：优先用 _img_sam.jpg（同目录小方块缩略图）
 * 来源：把已存储的 _img_main.jpg URL 替换后缀；若无存储则由 RJ 号推算
 * 错误回退顺序：_img_sam → _img_main → 隐藏
 */
function dlsiteUrl(rjcode, suffix = '_img_sam.jpg') {
  const m = String(rjcode || '').match(/RJ(\d+)/i)
  if (!m) return null
  const num = parseInt(m[1], 10)
  const folder = Math.ceil(num / 1000) * 1000
  return `https://img.dlsite.jp/modpub/images2/work/doujin/RJ${folder}/RJ${num}${suffix}`
}

const coverUrl = computed(() => {
  const stored = props.item[props.imageField]
  // 把存储的 _img_main URL 换成 _img_sam（若有）
  if (stored && stored.includes('_img_main')) return stored.replace('_img_main', '_img_sam')
  // 没有存储 URL 时由 canonical_rjcode 推算
  const code = props.item.canonical_rjcode || props.item.rjcode || ''
  return dlsiteUrl(code, '_img_sam.jpg') || stored || null
})

function onImgError(e) {
  const src = e.target.src || ''
  if (src.includes('_img_sam')) {
    // 回退到 _img_main
    const fallback = src.replace('_img_sam', '_img_main')
    if (fallback !== src) { e.target.src = fallback; return }
  }
  e.target.style.display = 'none'
}
</script>

<template>
  <article
    class="work-list-row"
    :class="{
      'is-selected': selected,
      'is-downloaded': item.local_download_ready && !cornerLabel,
      'is-new-work': isNewWork,
      'is-unreleased': isUnreleased,
      'status-flash': statusFlash,
      'is-disabled': disabled,
    }"
    :style="{ '--row-index': rowIndex }"
    @click="emit('select', item)"
  >
    <!-- 左侧缩略图 -->
    <div class="wlr-thumb">
      <img v-if="coverUrl" :src="coverUrl" class="wlr-thumb-img" referrerpolicy="no-referrer" @error="onImgError" />
      <div v-else class="wlr-thumb-placeholder">
        <LibraryBig :size="16" class="opacity-30" />
      </div>
      <div v-if="item.local_download_ready || cornerLabel" class="wlr-thumb-badge">
        {{ cornerLabel || '已下载' }}
      </div>
    </div>

    <!-- 主信息区 -->
    <div class="wlr-main">
      <div class="wlr-title" :title="item.title">
        <span v-if="isNewWork" class="wlr-new-badge">✦ 新作</span>
        <span v-if="isUnreleased" class="wlr-unreleased-badge"><Calendar :size="10" />未发售</span>
        {{ item.title || '未命名作品' }}
      </div>
      <div class="wlr-subtitle">
        <span class="wlr-code">{{ displayCode }}</span>
        <template v-if="cvLabel">
          <span class="wlr-sep"> / </span>
          <span class="wlr-cv">{{ cvLabel }}</span>
        </template>
      </div>
    </div>

    <!-- 来源/变体 -->
    <div class="wlr-meta">
      <span class="wlr-variant"><Layers :size="11" />{{ variantLabel }}</span>
      <span v-if="downloadRjcode !== displayCode" class="wlr-linked-code">{{ downloadRjcode }}</span>
    </div>

    <!-- 状态 pills -->
    <div class="wlr-status">
      <slot name="tags">
        <span class="wlr-pill" :class="item.server_owned ? 'pill-owned' : 'pill-missing'">
          <component :is="item.server_owned ? Server : X" :size="10" />{{ item.server_owned ? '已收录' : '未收录' }}
        </span>
        <span class="wlr-pill" :class="item.has_asmr_one ? 'pill-ok' : 'pill-none'">
          <LibraryBig :size="10" />{{ item.has_asmr_one ? '可下载' : '无源' }}
        </span>
      </slot>
    </div>

    <!-- 操作区 -->
    <div class="wlr-actions" @click.stop>
      <slot name="actions">
        <button
          v-if="item.local_download_ready"
          class="wlr-btn wlr-btn--import"
          title="入库"
          @click="emit('reimport', item)"
        >
          <PackageCheck :size="13" />入库
        </button>
        <button
          v-if="item.has_asmr_one || item.local_download_ready"
          class="wlr-btn"
          title="下载"
          @click="emit('preview', item.canonical_rjcode)"
        >
          <ExternalLink :size="13" />下载
        </button>
      </slot>
    </div>
  </article>
</template>

<style scoped>
.work-list-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px 8px 10px;
  border-radius: 9px;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  transition:
    background .15s ease,
    border-color .15s ease,
    box-shadow .15s ease;
  animation: rowEntrance .28s cubic-bezier(.22,1,.36,1) both;
  animation-delay: calc(var(--row-index, 0) * 18ms);
  position: relative;
}

@keyframes rowEntrance {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.work-list-row.is-new-work {
  border-color: rgba(249, 115, 22, 0.55);
  box-shadow: 0 0 0 2px rgba(249, 115, 22, 0.12), 0 0 16px rgba(249, 115, 22, 0.14);
}
.work-list-row.is-new-work:hover {
  border-color: rgba(249, 115, 22, 0.70);
  box-shadow: 0 0 0 2px rgba(249, 115, 22, 0.18), 0 0 20px rgba(249, 115, 22, 0.20);
}
.work-list-row.is-unreleased {
  border-color: rgba(52, 120, 246, 0.40);
  box-shadow: 0 0 0 2px rgba(52, 120, 246, 0.08), 0 0 14px rgba(52, 120, 246, 0.12);
}
.work-list-row.is-unreleased:hover {
  border-color: rgba(52, 120, 246, 0.60);
  box-shadow: 0 0 0 2px rgba(52, 120, 246, 0.14), 0 0 18px rgba(52, 120, 246, 0.18);
}


.work-list-row.is-selected {
  background: #eff6ff;
  border-color: #bfdbfe;
  box-shadow: 0 0 0 1px #bfdbfe;
}

.work-list-row.status-flash {
  animation: rowFlash .5s ease;
}

@keyframes rowFlash {
  0%, 100% { background: transparent; }
  40% { background: #fef9c3; border-color: #fde047; }
}

.work-list-row.is-disabled {
  opacity: .5;
  pointer-events: none;
}

/* ── 缩略图 ── */
.wlr-thumb {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  border-radius: 7px;
  overflow: hidden;
  background: #f0f0f3;
  border: 1px solid rgba(0,0,0,0.06);
  position: relative;
}

.wlr-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.wlr-thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
}

.wlr-thumb-badge {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background: rgba(16,185,129,.85);
  color: #fff;
  font-size: 9px;
  font-weight: 600;
  text-align: center;
  padding: 1px 0 2px;
  line-height: 1.3;
  backdrop-filter: blur(2px);
}

/* ── 主信息 ── */
.wlr-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.wlr-code {
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
  letter-spacing: .02em;
  line-height: 1.2;
}

.wlr-title {
  font-size: 13px;
  font-weight: 500;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
  display: flex;
  align-items: center;
  gap: 6px;
}
.wlr-new-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 7px;
  border: 1px solid rgba(249, 115, 22, 0.22);
  border-radius: 999px;
  background: rgba(255, 248, 240, 0.80);
  color: #ea580c;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .03em;
  box-shadow: 0 1px 4px rgba(249, 115, 22, 0.14);
}
.wlr-unreleased-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 18px;
  padding: 0 7px;
  border: 1px solid rgba(52, 120, 246, 0.20);
  border-radius: 999px;
  background: rgba(237, 244, 255, 0.80);
  color: #2563eb;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .03em;
  box-shadow: 0 1px 4px rgba(52, 120, 246, 0.10);
}

.wlr-subtitle {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  overflow: hidden;
}

.wlr-code {
  font-size: 11px;
  font-weight: 600;
  color: #6b7280;
  letter-spacing: .03em;
  flex-shrink: 0;
}

.wlr-sep {
  font-size: 11px;
  color: #d1d5db;
  flex-shrink: 0;
}

.wlr-cv {
  font-size: 11px;
  color: #0ea5e9;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── 来源/变体 ── */
.wlr-meta {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  min-width: 72px;
}

.wlr-variant {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: #9ca3af;
  font-weight: 500;
}

.wlr-linked-code {
  font-size: 11px;
  color: #d1d5db;
  font-family: monospace;
}

/* ── 状态 pills ── */
.wlr-status {
  flex-shrink: 0;
  display: flex;
  gap: 5px;
  align-items: center;
}

.wlr-pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1.4;
  user-select: none;
}

.wlr-pill.pill-owned  { background: #f0fdf4; color: #16a34a; }
.wlr-pill.pill-missing { background: #fef2f2; color: #dc2626; }
.wlr-pill.pill-ok     { background: #eff6ff; color: #2563eb; }
.wlr-pill.pill-none   { background: #f9fafb; color: #9ca3af; }

/* ── 操作区 ── */
.wlr-actions {
  flex-shrink: 0;
  display: flex;
  gap: 5px;
  align-items: center;
  opacity: 0;
  transform: translateX(10px);
  transition: opacity .2s ease, transform .24s cubic-bezier(.34, 1.56, .64, 1);
}

.work-list-row:hover .wlr-actions {
  opacity: 1;
  transform: translateX(0);
}

.wlr-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 9px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #374151;
  cursor: pointer;
  transition: all .13s ease;
  white-space: nowrap;
}

.wlr-btn:hover {
  border-color: #d1d5db;
  background: #f9fafb;
  color: #111827;
}

.wlr-btn--import {
  background: #111827;
  border-color: #111827;
  color: #fff;
}

.wlr-btn--import:hover {
  background: #1f2937;
  border-color: #1f2937;
}
</style>
