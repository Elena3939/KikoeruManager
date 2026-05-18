<script setup>
import { computed } from 'vue'
import { LibraryBig, Server, X, PackageCheck, Layers, ExternalLink, Calendar } from 'lucide-vue-next'
import { useViewport } from '../../composables/useViewport'

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

const { isMobile } = useViewport()

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

// "新作"判定：直接用后端 build_circle_completion_view 算好的 is_new_work。
// 后端口径 = email_watcher 来源 + 48h 窗口 + email_watcher_first_seen_at（fallback created_at）。
// 不再前端自己算时间窗口，避免左右两侧出现"左边没有新作但右边还在闪新作"的不一致。
const isNewWork = computed(() => Boolean(props.item?.is_new_work))

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

// 发售日期文本：年/月（/日）+ 上中下旬。与 WorkCard.releaseLabel 口径一致。
const releaseLabel = computed(() => {
  const value = String(props.item.release_date || props.item.date || props.item.release_at || '').trim()
  if (!value) return ''
  const match = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
  if (!match) return value
  const month = String(match[2]).padStart(2, '0')
  let day = ''
  if (match[3]) {
    day = `/${String(match[3]).padStart(2, '0')}`
  } else if (value.includes('下旬')) {
    day = ' 下旬'
  } else if (value.includes('中旬')) {
    day = ' 中旬'
  } else if (value.includes('上旬')) {
    day = ' 上旬'
  }
  return `${match[1]}/${month}${day}`
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
  const normalized = String(rjcode || '').trim().toUpperCase()
  const m = normalized.match(/^RJ(\d{6}|\d{8})$/)
  if (!m) return null
  const digits = m[1]
  const num = Number(digits)
  // DLsite 规则：folder = 下一个千位边界（floor(n/1000)+1）*1000，
  // 保留原始位数（6 或 8）零填充，整千数也要进位。
  const folderNum = (Math.floor(num / 1000) + 1) * 1000
  const folder = `RJ${String(folderNum).padStart(digits.length, '0')}`
  return `https://img.dlsite.jp/modpub/images2/work/doujin/${folder}/${normalized}${suffix}`
}

const coverUrl = computed(() => {
  const stored = String(props.item[props.imageField] || '').trim()
  if (stored && (stored.startsWith('/api/') || stored.includes('/api/circle-completion/cover/'))) return stored
  if (stored && stored.includes('img.dlsite.jp') && stored.includes('_img_main')) return stored.replace('_img_main', '_img_sam')
  if (stored) return stored
  const code = props.item.display_rjcode || props.item.canonical_rjcode || props.item.rjcode || ''
  return dlsiteUrl(code, '_img_sam.jpg') || null
})

function onImgError(e) {
  const src = e.target.src || ''
  const tried = Number(e.target.dataset.fallbackIndex || 0)

  // 回退链: _img_sam → _img_main_240x240 → _img_main → 隐藏
  if (src.includes('_img_sam.jpg')) {
    if (tried === 0) {
      const fallback = src.replace('_img_sam.jpg', '_img_main_240x240.jpg')
        .replace('img.dlsite.jp/modpub/images2/', 'img.dlsite.jp/resize/images2/')
      e.target.dataset.fallbackIndex = '1'
      e.target.src = fallback
      return
    }
    if (tried === 1) {
      const fallback = src.replace('_img_main_240x240.jpg', '_img_main.jpg')
        .replace('img.dlsite.jp/resize/images2/', 'img.dlsite.jp/modpub/images2/')
      e.target.dataset.fallbackIndex = '2'
      e.target.src = fallback
      return
    }
  } else if (src.includes('_img_main_240x240.jpg')) {
    if (tried === 0) {
      const fallback = src.replace('_img_main_240x240.jpg', '_img_main.jpg')
        .replace('img.dlsite.jp/resize/images2/', 'img.dlsite.jp/modpub/images2/')
      e.target.dataset.fallbackIndex = '1'
      e.target.src = fallback
      return
    }
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
      'is-mobile': isMobile,
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
    </div>

    <!-- 主信息区 -->
    <div class="wlr-main">
      <div class="wlr-title" :title="item.title">
        <span class="wlr-title-text">{{ item.title || '未命名作品' }}</span>
        <span v-if="isNewWork" class="wlr-new-badge">✦ 新作</span>
        <span v-if="isUnreleased" class="wlr-unreleased-badge"><Calendar :size="10" />未发售</span>
      </div>
      <div class="wlr-subtitle">
        <span class="wlr-code">{{ displayCode }}</span>
        <template v-if="cvLabel">
          <span class="wlr-sep"> / </span>
          <span class="wlr-cv">{{ cvLabel }}</span>
        </template>
        <template v-if="releaseLabel">
          <span class="wlr-sep"> / </span>
          <span class="wlr-release"><Calendar :size="10" />{{ releaseLabel }}</span>
        </template>
      </div>
    </div>

    <!-- 来源/变体（移动端隐藏） -->
    <div v-if="!isMobile" class="wlr-meta">
      <span class="wlr-variant"><Layers :size="11" />{{ variantLabel }}</span>
      <span v-if="downloadRjcode !== displayCode" class="wlr-linked-code">{{ downloadRjcode }}</span>
    </div>

    <!-- 状态 pills（移动端隐藏） -->
    <div v-if="!isMobile" class="wlr-status">
      <slot name="tags">
        <span class="wlr-pill" :class="item.server_owned ? 'pill-owned' : 'pill-missing'">
          <component :is="item.server_owned ? Server : X" :size="10" />{{ item.server_owned ? '已收录' : '未收录' }}
        </span>
        <span class="wlr-pill" :class="item.has_asmr_one ? 'pill-ok' : 'pill-none'">
          <LibraryBig :size="10" />{{ item.has_asmr_one ? '可下载' : '无源' }}
        </span>
      </slot>
    </div>

    <!-- 操作区（移动端始终可见） -->
    <div class="wlr-actions" :class="{ 'is-mobile-visible': isMobile }" @click.stop>
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


/* ── 主信息 ── */
.wlr-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
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
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.wlr-title-text {
  display: inline;
}

.wlr-new-badge {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 7px;
  margin-left: 6px;
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
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 18px;
  padding: 0 7px;
  margin-left: 6px;
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

.wlr-release {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  font-weight: 500;
  color: #6b7280;
  flex-shrink: 0;
}
.wlr-release :first-child {
  color: #94a3b8;
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
  width: 72px;
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
  justify-content: flex-end;
  width: 74px;
  opacity: 0;
  transform: translateX(10px);
  transition: opacity .2s ease, transform .24s cubic-bezier(.34, 1.56, .64, 1);
}

@media (hover: hover) {
  .work-list-row:hover .wlr-actions {
    opacity: 1;
    transform: translateX(0);
  }
}

/* 触摸屏（移动端）：操作按钮始终可见 */
@media (hover: none) {
  .wlr-actions {
    opacity: 1;
    transform: translateX(0);
    width: auto;
  }
  /* 移动端隐藏 meta（变体/关联码）节省空间 */
  .wlr-meta {
    display: none;
  }
  /* 状态 pills 只保留第一个（服务器收录状态），隐藏 has_asmr_one */
  .wlr-status .wlr-pill:not(:first-child) {
    display: none;
  }
}

/* 移动端通过 isMobile class 控制（比媒体查询更可靠）*/
.work-list-row.is-mobile {
  gap: 8px;
  padding: 7px 10px 7px 8px;
}
.work-list-row.is-mobile .wlr-thumb {
  width: 36px;
  height: 36px;
}
.work-list-row.is-mobile .wlr-title {
  font-size: 12px;
}
.wlr-actions.is-mobile-visible {
  opacity: 1;
  transform: translateX(0);
  width: auto;
  flex-shrink: 0;
}
.wlr-btn.is-mobile-compact {
  height: 24px;
  padding: 0 7px;
  font-size: 11px;
}
.work-list-row.is-mobile .wlr-btn {
  height: 24px;
  padding: 0 7px;
  font-size: 11px;
}

/* 窄屏紧凑处理（含桌面浏览器模拟移动端场景）*/
@media (max-width: 640px) {
  .work-list-row {
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    padding: 8px 10px;
    gap: 8px;
    max-width: 100%;
    overflow: hidden;
  }
  .wlr-thumb {
    width: 36px;
    height: 36px;
  }
  .wlr-title {
    font-size: 12px;
    max-width: 100%;
    white-space: normal;
    overflow: hidden;
    text-overflow: clip;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
  .wlr-main {
    flex: 1 1 0;
    min-width: 0;
    max-width: calc(100% - 44px);
    overflow: hidden;
  }
  .wlr-title-text {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .wlr-subtitle {
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
  }
  .wlr-code {
    min-width: 0;
    max-width: 92px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .wlr-cv {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* 640px 以下隐藏 meta 和 status，节省横向空间 */
  .wlr-meta,
  .wlr-status {
    display: none;
  }
  /* 操作按钮始终可见（无论 hover 能力）*/
  .wlr-actions {
    opacity: 1 !important;
    transform: translateX(0) !important;
    width: auto;
    max-width: 100%;
    flex-shrink: 0;
    overflow: hidden;
  }
  .wlr-btn {
    height: 24px !important;
    max-width: 100%;
    padding: 0 7px !important;
    font-size: 11px !important;
    overflow: hidden;
    text-overflow: ellipsis;
  }
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
