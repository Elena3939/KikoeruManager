<script setup>
import { computed } from 'vue'
import { LibraryBig, Calendar } from 'lucide-vue-next'

const props = defineProps({
  /** 作品数据对象 */
  item: { type: Object, required: true },
  /** 卡片在列表中的索引，用于入场动画延迟 */
  cardIndex: { type: Number, default: 0 },
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
  /** 尺寸变体 */
  size: { type: String, default: 'default', validator: v => ['default', 'lg'].includes(v) },
})

const emit = defineEmits(['select', 'preview', 'reimport'])

const rawCoverUrl = computed(() => String(props.item[props.imageField] || '').trim())
const displayCode = computed(() => {
  if (props.codeField) return props.item[props.codeField]
  return props.item.source_compare?.work_rjcode || props.item.canonical_rjcode || props.item.rjcode || ''
})
const showCorner = computed(() => {
  if (props.cornerLabel) return true
  return props.item.local_download_ready
})
const cornerText = computed(() => props.cornerLabel || '已下载')
const cvLabel = computed(() => {
  const cvs = props.item.cvs
  if (!Array.isArray(cvs) || cvs.length === 0) return ''
  return cvs.join(' / ')
})
const releaseLabel = computed(() => {
  const value = String(props.item.release_date || props.item.date || props.item.release_at || '').trim()
  if (!value) return '待定'
  const match = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
  if (!match) return value
  const month = String(match[2]).padStart(2, '0')
  // 有具体日则显示日，有旬则显示旬，否则只显示月
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
const isUnreleased = computed(() => {
  if (props.item.is_unreleased) return true
  const value = String(props.item.release_date || props.item.date || props.item.release_at || '').trim()
  if (!value) return true
  // 日期在今天之后也算预售（未发售）
  const match = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
  if (!match) return false
  const year = Number(match[1])
  const month = Number(match[2]) - 1
  // 处理「下旬/中旬/上旬」——不取默认 1 日，避免误判为已发售
  let day
  if (match[3]) {
    day = Number(match[3])
  } else if (value.includes('下旬')) {
    day = 28
  } else if (value.includes('中旬')) {
    day = 20
  } else if (value.includes('上旬')) {
    day = 10
  } else {
    day = 1
  }
  const releaseDate = new Date(year, month, day)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return releaseDate > today
})
const coverUrl = computed(() => {
  const value = rawCoverUrl.value
  const rjcode = props.item.display_rjcode || displayCode.value || props.item.canonical_rjcode || props.item.rjcode
  if (isUnreleased.value && value.includes('/modpub/images2/work/doujin/')) {
    return buildDlsiteCoverUrl(rjcode, true, 'sam')
  }
  if (value.includes('/modpub/images2/') && value.endsWith('_img_main.jpg')) {
    return value
      .replace('https://img.dlsite.jp/modpub/images2/', 'https://img.dlsite.jp/resize/images2/')
      .replace('_img_main.jpg', '_img_main_240x240.jpg')
  }
  return value || buildDlsiteCoverUrl(rjcode, isUnreleased.value, 'sam')
})

function buildDlsiteCoverUrl(rjcode, unreleased = false, variant = 'sam') {
  const normalized = String(rjcode || '').trim().toUpperCase()
  const match = normalized.match(/^RJ(\d{6}|\d{8})$/)
  if (!match) return ''
  const number = Number(match[1])
  const folderUpper = (Math.floor(number / 1000) + 1) * 1000
  const folder = match[1].length === 8
    ? `RJ${String(folderUpper).padStart(8, '0')}`
    : `RJ${String(folderUpper).padStart(6, '0')}`
  const pathType = unreleased ? 'announce' : 'work'
  if (variant === 'sam') {
    if (unreleased) {
      return `https://img.dlsite.jp/modpub/images2/ana/doujin/${folder}/${normalized}_ana_img_main.jpg`
    }
    return `https://img.dlsite.jp/modpub/images2/${pathType}/doujin/${folder}/${normalized}_img_sam.jpg`
  }
  if (variant === 'resized') {
    return `https://img.dlsite.jp/resize/images2/${pathType}/doujin/${folder}/${normalized}_img_main_240x240.jpg`
  }
  return `https://img.dlsite.jp/modpub/images2/${pathType}/doujin/${folder}/${normalized}_img_main.jpg`
}

function onCoverError(event) {
  const rjcode = props.item.display_rjcode || displayCode.value || props.item.canonical_rjcode || props.item.rjcode
  const fallbacks = isUnreleased.value
    ? [
        buildDlsiteCoverUrl(rjcode, true, 'sam'),
        buildDlsiteCoverUrl(rjcode, true, 'resized'),
        buildDlsiteCoverUrl(rjcode, true, 'main'),
        buildDlsiteCoverUrl(rjcode, false, 'sam'),
        buildDlsiteCoverUrl(rjcode, false, 'resized'),
        buildDlsiteCoverUrl(rjcode, false, 'main'),
      ]
    : [
        buildDlsiteCoverUrl(rjcode, false, 'resized'),
        buildDlsiteCoverUrl(rjcode, false, 'main'),
      ]
  const tried = Number(event.currentTarget.dataset.fallbackIndex || 0)
  const fallback = fallbacks[tried]
  if (!fallback) return
  event.currentTarget.dataset.fallbackIndex = String(tried + 1)
  event.currentTarget.src = fallback
}
</script>

<template>
  <article
    class="work-card group"
    :class="{
      selected: props.selected,
      'is-downloaded': item.local_download_ready && !cornerLabel,
      'is-unreleased': isUnreleased,
      'status-flash': props.statusFlash,
      disabled: props.disabled,
      'work-card--lg': props.size === 'lg',
    }"
    :style="{ '--card-index': props.cardIndex }"
    @click="emit('select', item)"
  >
    <!-- 选中指示器光环 -->
    <div class="work-card-select-ring" />

    <div class="work-cover-wrapper">
      <img v-if="coverUrl" :src="coverUrl" class="work-cover" @error="onCoverError" />
      <div v-else class="work-cover-placeholder">
        <slot name="cover-placeholder">
          <LibraryBig :size="props.size === 'lg' ? 28 : 22" class="opacity-40" />
        </slot>
      </div>
      <div v-if="showCorner" class="work-corner-flag">{{ cornerText }}</div>
      <div v-if="isUnreleased" class="work-unreleased-flag">
        <Calendar :size="12" />
        <span>未发售</span>
      </div>
      <div class="work-cover-shine" />
    </div>

    <div class="work-card-body">
      <div class="work-rj">{{ displayCode }}</div>
      <div class="work-title" :title="item.title">{{ item.title || '未命名作品' }}</div>
      <slot name="meta">
        <div class="work-linked">{{ item.preferred_variant?.group_short_label || '原作' }} · {{ item.download_plan?.rjcode || item.display_rjcode || item.canonical_rjcode }}</div>
      </slot>
      <div v-if="cvLabel" class="work-cv">{{ cvLabel }}</div>

      <slot name="tags">
        <div class="work-tags">
          <span v-if="isUnreleased" class="work-release-chip">
            <Calendar :size="13" class="flex-shrink-0" />
            发售 {{ releaseLabel }}
          </span>
          <template v-else>
            <span class="tag-chip" :class="item.server_owned ? 'is-primary' : 'is-danger'">{{ item.server_owned ? '已收录' : '未收录' }}</span>
            <span class="tag-chip" :class="item.has_asmr_one ? 'is-success' : 'is-disabled'">{{ item.has_asmr_one ? '可下载' : '无源' }}</span>
          </template>
        </div>
      </slot>

      <slot name="actions">
        <div v-if="item.has_asmr_one || item.local_download_ready" class="work-actions">
          <button v-if="item.local_download_ready" class="work-action-btn upload" @click.stop="emit('reimport', item)">入库</button>
          <button class="work-action-btn" @click.stop="emit('preview', item.canonical_rjcode)">预览</button>
        </div>
      </slot>
    </div>
  </article>
</template>

<style scoped>
/* ── 卡片共用圆角 ── */
.work-card {
  border-radius: 14px;
  border: 1px solid rgba(29, 29, 31, 0.06);
  background: #fcfcfd;
  position: relative;
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition:
    border-color .2s cubic-bezier(.4,0,.2,1),
    box-shadow .28s cubic-bezier(.4,0,.2,1),
    transform .22s cubic-bezier(.34,1.56,.64,1),
    background-color .2s ease;
  will-change: transform, box-shadow;
  transform: translateZ(0);
  animation: workCardEntrance .38s cubic-bezier(.22,1,.36,1) both;
  animation-delay: calc(var(--card-index, 0) * 28ms);
}

/* ── 选中指示器光环 ── */
.work-card-select-ring {
  position: absolute;
  inset: -2px;
  border-radius: 16px;
  border: 2px solid transparent;
  pointer-events: none;
  z-index: 12;
  transition: border-color .22s ease, box-shadow .28s ease;
}
.work-card.selected .work-card-select-ring {
  border-color: rgba(52, 120, 246, 0.55);
  box-shadow: 0 0 0 3px rgba(52, 120, 246, 0.10);
  animation: selectRingPulse .5s cubic-bezier(.4,0,.2,1);
}

/* ── 封面闪光 ── */
.work-cover-shine {
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, transparent 40%, rgba(255,255,255,0.45) 50%, transparent 60%);
  opacity: 0;
  transform: translateX(-100%);
  pointer-events: none;
  transition: none;
}
.work-card:hover .work-cover-shine {
  opacity: 1;
  transform: translateX(100%);
  transition: transform .6s ease, opacity .15s ease;
}

/* ── 封面容器 ── */
.work-cover-wrapper {
  position: relative;
  width: 100%;
  /* DLsite 主封面默认 4:3，按原图比例预留容器，避免 contain 模式下出现大块空白 */
  aspect-ratio: 4 / 3;
  /* 不允许被父级 flex/grid 拉伸或压缩，防止刷新进度卡占用空间时封面被挤成扁条 */
  flex-shrink: 0;
  flex-grow: 0;
  overflow: hidden;
  background: #f5f6f8;
  border-bottom: 1px solid rgba(29,29,31,0.04);
}

/* ── 封面图 ── */
.work-cover {
  width: 100%;
  height: 100%;
  /* contain：按原图比例缩小，不裁切；进度条压缩空间时也能完整看到封面 */
  object-fit: contain;
  object-position: center;
  transition: transform .45s cubic-bezier(.4,0,.2,1), filter .3s ease;
}
.work-card:hover .work-cover {
  transform: scale(1.08);
}
.work-card.selected .work-cover {
  filter: brightness(1.04) saturate(1.1);
}

/* ── 封面占位 ── */
.work-cover-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c1c8d1;
  background: #f5f6f8;
}

/* ── 已下载态 ── */
.work-card.is-downloaded {
  border-color: rgba(67, 160, 94, 0.18);
  background:
    radial-gradient(circle at top right, rgba(93, 193, 122, 0.12), transparent 40%),
    linear-gradient(180deg, #fbfefb 0%, #f3fbf5 100%);
}
.work-card.is-downloaded:hover {
  border-color: rgba(67, 160, 94, 0.28);
  box-shadow:
    0 10px 20px rgba(53, 102, 72, 0.09),
    inset 0 0 0 1px rgba(93, 193, 122, 0.08);
}
.work-card.is-unreleased {
  border-color: rgba(52, 120, 246, 0.16);
  background:
    radial-gradient(circle at top left, rgba(52, 120, 246, 0.08), transparent 42%),
    linear-gradient(180deg, #fbfcff 0%, #f5f8ff 100%);
}
.work-card.is-unreleased:hover {
  border-color: rgba(52, 120, 246, 0.24);
  box-shadow: 0 10px 20px rgba(38, 74, 134, 0.08);
}

/* ── hover / selected / flash ── */
.work-card:hover {
  transform: translateY(-3px) scale(1.015);
  border-color: rgba(52, 120, 246, 0.14);
  box-shadow: 0 10px 22px rgba(38, 74, 134, 0.10);
  background: #ffffff;
}
.work-card.selected {
  border-color: rgba(52, 120, 246, 0.42);
  box-shadow: 0 0 0 2.5px rgba(52, 120, 246, 0.12), 0 12px 24px rgba(52, 120, 246, 0.10);
  background: linear-gradient(180deg, #f6faff 0%, #ebf2ff 100%);
  transform: scale(0.975);
}
.work-card.selected:hover {
  transform: translateY(-2px) scale(0.99);
}
.work-card.status-flash {
  animation: workStatusFlash 2.4s ease;
  border-color: rgba(82, 170, 103, 0.5);
  box-shadow:
    0 0 0 2px rgba(82, 170, 103, 0.16),
    0 12px 24px rgba(73, 137, 91, 0.12);
  background:
    radial-gradient(circle at top right, rgba(115, 205, 134, 0.18), transparent 36%),
    linear-gradient(180deg, #fcfffb 0%, #eefaf0 100%);
}
.work-card.status-flash.selected {
  border-color: rgba(82, 170, 103, 0.6);
}
.work-card.disabled {
  opacity: .94;
  filter: saturate(0.5) grayscale(0.14);
  background: linear-gradient(180deg, #fafbfd 0%, #f1f3f6 100%);
  border-color: rgba(29, 29, 31, 0.06);
  cursor: default;
}
.work-card.disabled:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 12px rgba(29, 29, 31, 0.04);
}

/* ── 入场 + 选中脉冲 ── */
@keyframes workCardEntrance {
  from {
    opacity: 0;
    transform: translateY(12px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
@keyframes selectRingPulse {
  0% { box-shadow: 0 0 0 0 rgba(52, 120, 246, 0.3); }
  60% { box-shadow: 0 0 0 6px rgba(52, 120, 246, 0); }
  100% { box-shadow: 0 0 0 3px rgba(52, 120, 246, 0.10); }
}
@keyframes workStatusFlash {
  0% {
    transform: scale(0.99);
    box-shadow:
      0 0 0 0 rgba(82, 170, 103, 0.34),
      0 6px 14px rgba(73, 137, 91, 0.08);
  }
  18% {
    transform: scale(1.01);
    box-shadow:
      0 0 0 5px rgba(82, 170, 103, 0.12),
      0 12px 22px rgba(73, 137, 91, 0.14);
  }
  100% {
    transform: scale(1);
    box-shadow:
      0 0 0 0 rgba(82, 170, 103, 0),
      0 8px 18px rgba(73, 137, 91, 0.08);
  }
}

/* ── 角标 ── */
.work-corner-flag {
  position: absolute;
  top: 0;
  right: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  height: 20px;
  padding: 0 7px;
  border-bottom-left-radius: 10px;
  background: rgba(34, 197, 94, 0.92);
  backdrop-filter: blur(6px);
  color: #fff;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .04em;
  box-shadow: 0 3px 8px rgba(34, 197, 94, 0.22);
  z-index: 10;
  transition: transform .2s ease;
}
.work-card:hover .work-corner-flag {
  transform: scale(1.06);
}
.work-corner-flag::after {
  content: '';
  position: absolute;
  left: -6px;
  top: 0;
  width: 10px;
  height: 100%;
  background: linear-gradient(180deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0.05) 100%);
  transform: skewX(-20deg);
  opacity: 0.7;
}
.work-unreleased-flag {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 8px;
  border: 1px solid rgba(52, 120, 246, 0.18);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(10px);
  color: #2563eb;
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: .02em;
  box-shadow: 0 6px 14px rgba(38, 74, 134, 0.10);
  transition: transform .2s cubic-bezier(.34,1.56,.64,1), border-color .2s ease, background .2s ease;
}
.work-card:hover .work-unreleased-flag {
  transform: translateY(-1px) scale(1.03);
  border-color: rgba(52, 120, 246, 0.28);
  background: rgba(255, 255, 255, 0.9);
}
.work-release-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 18px;
  padding: 0 6px;
  border: 1px solid rgba(52, 120, 246, 0.14);
  border-radius: 6px;
  background: rgba(237, 244, 255, 0.88);
  color: #2f66c0;
  font-size: 9px;
  font-weight: 800;
  line-height: 1;
}

/* ── 卡片内容 ── */
.work-card-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 7px 8px 8px;
  flex: 1;
}
.work-rj {
  font-size: 9px;
  font-weight: 700;
  color: #6d8bb5;
  letter-spacing: .03em;
  transition: color .2s ease;
}
.work-card:hover .work-rj {
  color: #3478f6;
}
.work-card.disabled .work-rj,
.work-card.disabled .work-title,
.work-card.disabled .work-linked {
  color: rgba(29, 29, 31, 0.36);
}

/* ── 标题 ── */
.work-title {
  font-size: 11px;
  font-weight: 800;
  color: #1f3554;
  line-height: 1.38;
  display: -webkit-box;
  min-height: calc(1.38em * 2);
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  transition: color .2s ease;
}
.work-card:hover .work-title {
  color: #2563eb;
}

/* ── 关联信息 ── */
.work-linked {
  font-size: 9px;
  color: rgba(29, 29, 31, 0.40);
  line-height: 1.4;
  word-break: break-word;
  min-height: 13px;
}

/* ── CV 名 ── */
.work-cv {
  font-size: 9px;
  color: #0ea5e9;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.4;
}

/* ── 标签区 ── */
.work-tags {
  display: flex;
  gap: 3px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 2px;
}

/* ── 操作区 ── */
.work-actions {
  display: flex;
  justify-content: stretch;
  gap: 4px;
  width: 100%;
  opacity: 0;
  max-height: 0;
  overflow: hidden;
  transition: opacity .22s ease, max-height .26s cubic-bezier(.4,0,.2,1), margin .22s ease;
  margin-top: 0;
}
.work-card:hover .work-actions {
  opacity: 1;
  max-height: 40px;
  margin-top: 4px;
}

/* ── 标签胶囊 ── */
.tag-chip {
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-radius: 5px;
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: 0.02em;
  transition: transform .18s ease, box-shadow .18s ease;
}
.work-card:hover .tag-chip {
  transform: scale(1.04);
}
.tag-chip.is-primary {
  background: #edf4ff;
  color: #3b70c4;
  border: 1px solid #cce0ff;
}
.tag-chip.is-success {
  background: #edf9f1;
  color: #2b804e;
  border: 1px solid #cdeedb;
}
.tag-chip.is-danger {
  background: #fff4f2;
  color: #c44733;
  border: 1px solid #fbd8d3;
}
.tag-chip.is-warning {
  background: #fff8eb;
  color: #b06f13;
  border: 1px solid #fbe6c4;
}
.tag-chip.is-info {
  background: #f4f6f9;
  color: #5d6d81;
  border: 1px solid #e2e8f0;
}
.tag-chip.is-disabled {
  background: #fafafa;
  color: #94a3b8;
  border: 1px solid #e2e8f0;
}

/* ── 迷你操作按钮 ── */
.work-action-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #c5daff;
  background: #ffffff;
  color: #2570d4;
  min-height: 22px;
  padding: 0 6px;
  border-radius: 8px;
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  transition: all .2s cubic-bezier(.4,0,.2,1);
  box-shadow: 0 1px 4px rgba(31, 111, 214, 0.06);
}
.work-action-btn:hover {
  background: linear-gradient(180deg, #2997ff 0%, #0077ed 100%);
  border-color: #0077ed;
  color: #fff;
  box-shadow: 0 6px 14px rgba(31, 111, 214, 0.20);
  transform: translateY(-1px);
}
.work-action-btn:active {
  transform: scale(0.95);
}
.work-action-btn.upload {
  border-color: #c4e0cd;
  background: #eef8f1;
  color: #237849;
}
.work-action-btn.upload:hover {
  background: linear-gradient(180deg, #45b36a 0%, #2f8b54 100%);
  border-color: #2f8b54;
  color: #fff;
  box-shadow: 0 6px 14px rgba(35, 120, 73, 0.20);
}

/* ── lg 尺寸变体 ── */
.work-card--lg {
  border-radius: 16px;
}
.work-card--lg .work-card-select-ring {
  border-radius: 18px;
}
.work-card--lg .work-cover-wrapper {
  aspect-ratio: 4 / 3;
}
.work-card--lg .work-card-body {
  gap: 4px;
  padding: 10px 12px 12px;
}
.work-card--lg .work-rj {
  font-size: 11px;
}
.work-card--lg .work-title {
  font-size: 13px;
  min-height: calc(1.38em * 2);
}
.work-card--lg .work-linked {
  font-size: 10px;
}
.work-card--lg .tag-chip {
  height: 20px;
  padding: 0 7px;
  font-size: 10px;
  border-radius: 6px;
}
.work-card--lg .work-action-btn {
  min-height: 26px;
  padding: 0 8px;
  font-size: 10px;
  border-radius: 8px;
}
.work-card--lg .work-corner-flag {
  min-width: 54px;
  height: 22px;
  font-size: 10px;
  border-bottom-left-radius: 12px;
}
.work-card--lg .work-unreleased-flag {
  height: 24px;
  padding: 0 9px;
  font-size: 11px;
}
.work-card--lg .work-release-chip {
  min-height: 20px;
  padding: 0 7px;
  font-size: 10px;
}
</style>
