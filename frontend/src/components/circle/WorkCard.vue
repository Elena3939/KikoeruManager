<script setup>
import { computed, ref, watch } from 'vue'
import { LibraryBig, Calendar, Gift, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import ExternalSearchSourceChips from './ExternalSearchSourceChips.vue'

const props = defineProps({
  /** 作品数据对象 */
  item: { type: Object, required: true },
  /** 卡片在列表中的索引，用于入场动画延迟 */
  cardIndex: { type: Number, default: 0 },
  /** 是否选中 */
  selected: { type: Boolean, default: false },
  /** 选中光环的错峰序号，避免批量选择时同帧触发大量脉冲 */
  selectionPulseIndex: { type: Number, default: 0 },
  /** 是否处于状态闪烁中 */
  statusFlash: { type: Boolean, default: false },
  /** 是否处于搜索定位高亮中 */
  locateFlash: { type: Boolean, default: false },
  /** 是否禁用 */
  disabled: { type: Boolean, default: false },
  /** 外层可覆盖补全灰态；不传则沿用 item.completion_card_dimmed */
  completionDimmed: { type: Boolean, default: null },
  /** 封面图字段名 */
  imageField: { type: String, default: 'image_url' },
  /** 标识字段名（用于 RJ 号显示） */
  codeField: { type: String, default: '' },
  /** 角标文字，空则不显示 */
  cornerLabel: { type: String, default: '' },
  /** 是否允许挂载真实图片 src，由外层虚拟视口调度 */
  imageActive: { type: Boolean, default: true },
  /** 由社团补全封面缓存返回的本地地址，优先于作品字段 */
  coverUrlOverride: { type: String, default: '' },
  /** 当前封面是否正在下载到本地缓存 */
  coverFetching: { type: Boolean, default: false },
  /** 尺寸变体 */
  size: { type: String, default: 'default', validator: v => ['default', 'lg'].includes(v) },
  showReleaseBadge: { type: Boolean, default: true },
})

const emit = defineEmits(['select', 'preview', 'reimport', 'image-settled', 'image-failed', 'retry-cover', 'contextmenu', 'external-search'])

const rawCoverUrl = computed(() => String(props.coverUrlOverride || props.item[props.imageField] || '').trim())
const remoteCoverUrl = computed(() => String(props.item?.remote_image_url || '').trim())
const selectionPulseDelay = computed(() => `${Math.min(Math.max(Number(props.selectionPulseIndex || 0), 0), 12) * 40}ms`)
const imageFailed = ref(false)
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
  if (!props.showReleaseBadge) return false
  if (props.item.is_unreleased) return true
  const value = String(props.item.release_date || props.item.date || props.item.release_at || '').trim()
  if (!value) return false
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

// "新作"判定：直接用后端 build_circle_completion_view 算好的 is_new_work。
// 后端口径 = email_watcher 来源 + 48h 窗口 + email_watcher_first_seen_at（fallback created_at）。
// 早期版本前端自己用 email_watcher_first_seen_at + 48h 单独算，会和左侧
// search_circles 的 new_works_48h_count 出现口径漂移（左侧已不显示"新作"
// 但右侧卡片还在闪"新作"特效）。这里改成统一读后端字段，左右两侧永远一致。
function isStrictTrue(value) {
  if (value === true || value === 1 || value === '1') return true
  if (typeof value === 'string') return value.trim().toLowerCase() === 'true'
  return false
}

const isNewWork = computed(() => isStrictTrue(props.item?.is_new_work))
const isBonusWork = computed(() => isStrictTrue(props.item?.is_bonus_work))
const isCompletionDimmed = computed(() => props.completionDimmed ?? isStrictTrue(props.item?.completion_card_dimmed))
const displayVariant = computed(() =>
  isBonusWork.value ? '' :
  props.item?.owned ? (props.item.owned_variant?.group_short_label || '原作') : (props.item.preferred_variant?.group_short_label || '原作')
)
const displayVariantRjcode = computed(() =>
  props.item?.owned
    ? (props.item.owned_variant?.rjcode || props.item.server_match_primary_rjcode || props.item.display_rjcode || props.item.canonical_rjcode)
    : (props.item.download_plan?.rjcode || props.item.display_rjcode || props.item.canonical_rjcode)
)
const canRepairSubtitle = computed(() => Boolean(props.item?.subtitle_repairable))
const showOriginalSubtitleState = computed(() =>
  Boolean(props.item?.owned)
  && (props.item?.owned_variant?.group_key || 'original') === 'original'
)
const originalSubtitleLabel = computed(() => {
  if (canRepairSubtitle.value) return '可补配'
  return props.item?.subtitle_present ? '有字幕' : '无字幕'
})

const bonusFlagClass = computed(() => {
  if (isUnreleased.value && isNewWork.value) return 'work-bonus-flag--double-below'
  if (isUnreleased.value || isNewWork.value) return 'work-bonus-flag--below'
  return ''
})

const coverUrl = computed(() => {
  const value = rawCoverUrl.value
  const rjcode = imageRjcode(remoteCoverUrl.value) || props.item.display_rjcode || displayCode.value || props.item.canonical_rjcode || props.item.rjcode
  if (isUnreleased.value && value.includes('/modpub/images2/work/doujin/')) {
    return buildDlsiteCoverUrl(rjcode, true, 'sam')
  }
  if (value.includes('/modpub/images2/') && value.endsWith('_img_main.jpg')) {
    return value
      .replace('https://img.dlsite.jp/modpub/images2/', 'https://img.dlsite.jp/resize/images2/')
      .replace('_img_main.jpg', '_img_main_240x240.jpg')
  }
  return value || remoteCoverUrl.value || buildDlsiteCoverUrl(rjcode, isUnreleased.value, 'sam')
})
const showCoverRetry = computed(() => props.imageActive && (imageFailed.value || !coverUrl.value))

watch(coverUrl, () => {
  imageFailed.value = false
})

function imageRjcode(value) {
  const matches = String(value || '').match(/[RVB]J\d{6,8}/gi)
  return matches?.length ? matches[matches.length - 1].toUpperCase() : ''
}

function comparableUrl(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  try {
    return new URL(text, globalThis.location?.origin || 'http://localhost').href
  } catch {
    return text
  }
}

function uniqueImageUrls(values) {
  const seen = new Set()
  return values.filter(value => {
    const normalized = comparableUrl(value)
    if (!normalized || seen.has(normalized)) return false
    seen.add(normalized)
    return true
  })
}

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
  const current = String(event?.currentTarget?.currentSrc || event?.currentTarget?.src || '')
  if (!current.includes('/api/circle-completion/cover/')) {
    const rjcode = imageRjcode(remoteCoverUrl.value) || props.item.display_rjcode || displayCode.value || props.item.canonical_rjcode || props.item.rjcode
    const fallbacks = uniqueImageUrls([
      remoteCoverUrl.value,
      buildDlsiteCoverUrl(rjcode, false, 'resized'),
      buildDlsiteCoverUrl(rjcode, false, 'main'),
    ])
    let index = Number(event.currentTarget.dataset.fallbackIndex || 0)
    while (index < fallbacks.length) {
      const fallback = fallbacks[index]
      index += 1
      if (comparableUrl(fallback) === comparableUrl(current)) continue
      event.currentTarget.dataset.fallbackIndex = String(index)
      event.currentTarget.src = fallback
      return
    }
  }
  imageFailed.value = true
  emit('image-failed', props.item)
  emit('image-settled', displayCode.value)
}

function onCoverLoad(event) {
  imageFailed.value = false
  delete event.currentTarget.dataset.fallbackIndex
  emit('image-settled', displayCode.value)
}

function preventNativeShiftSelection(event) {
  if (event.shiftKey) event.preventDefault()
}

</script>

<template>
  <article
    class="work-card group"
    :class="{
      selected: props.selected,
      'is-downloaded': item.local_download_ready && !cornerLabel,
      'is-unreleased': isUnreleased,
      'is-new-work': isNewWork,
      'status-flash': props.statusFlash,
      'locate-flash': props.locateFlash,
      'is-completion-dimmed': isCompletionDimmed,
      disabled: props.disabled,
      'work-card--lg': props.size === 'lg',
    }"
    :style="{ '--card-index': props.cardIndex, '--selection-pulse-delay': selectionPulseDelay }"
    @mousedown.capture="preventNativeShiftSelection"
    @click="emit('select', item, $event)"
    @contextmenu.prevent="emit('contextmenu', item, $event)"
  >
    <!-- 选中指示器光环 -->
    <div class="work-card-select-ring" />

    <div class="work-cover-wrapper">
      <img
        v-if="imageActive && coverUrl && !imageFailed"
        :src="coverUrl"
        class="work-cover"
        loading="eager"
        decoding="async"
        fetchpriority="auto"
        referrerpolicy="no-referrer"
        @load="onCoverLoad"
        @error="onCoverError"
      />
      <div v-else class="work-cover-placeholder">
        <slot name="cover-placeholder">
          <LibraryBig :size="props.size === 'lg' ? 28 : 22" class="opacity-40" />
        </slot>
        <button
          v-if="showCoverRetry"
          type="button"
          class="work-cover-retry"
          :class="{ 'is-loading': coverFetching }"
          :disabled="coverFetching"
          title="重新下载封面到本地缓存"
          aria-label="重新下载封面到本地缓存"
          @click.stop="emit('retry-cover', item)"
        >
          <LoaderCircle v-if="coverFetching" :size="props.size === 'lg' ? 21 : 18" class="cover-retry-spin" />
          <RefreshCw v-else :size="props.size === 'lg' ? 21 : 18" />
        </button>
      </div>
      <div v-if="showCorner" class="work-corner-flag">{{ cornerText }}</div>
      <div v-if="isUnreleased" class="work-unreleased-flag">
        <Calendar :size="12" />
        <span>未发售</span>
      </div>
      <div v-if="isNewWork" :class="['work-new-flag', isUnreleased ? 'work-new-flag--below' : '']">
        <span>✦ 新作</span>
      </div>
      <div v-if="isBonusWork" :class="['work-bonus-flag', bonusFlagClass]" title="特典作品">
        <Gift :size="12" />
        <span>特典</span>
      </div>

      <div class="work-cover-shine" />
    </div>

    <div class="work-card-body">
      <div class="work-rj">{{ displayCode }}</div>
      <div class="work-title" :title="item.title">{{ item.title || '未命名作品' }}</div>
      <slot name="meta">
        <div class="work-linked">
          <span>{{ displayVariant ? `${displayVariant} · ${displayVariantRjcode}` : displayVariantRjcode }}</span>
          <span v-if="!isUnreleased && releaseLabel && releaseLabel !== '待定'" class="work-release-inline">
            <Calendar :size="11" />{{ releaseLabel }}
          </span>
        </div>
      </slot>
      <div class="work-cv" :class="{ 'is-empty': !cvLabel }">{{ cvLabel }}</div>

      <slot name="tags">
        <div class="work-tags">
          <span v-if="isUnreleased" class="work-release-chip">
            <Calendar :size="13" class="flex-shrink-0" />
            发售 {{ releaseLabel }}
          </span>
          <template v-else>
            <span class="tag-chip" :class="item.server_owned ? 'is-primary' : 'is-danger'">{{ item.server_owned ? '已收录' : '未收录' }}</span>
            <span v-if="showOriginalSubtitleState" class="tag-chip" :class="canRepairSubtitle ? 'is-repair' : (item.subtitle_present ? 'is-subtitle' : 'is-subtitle-none')">{{ originalSubtitleLabel }}</span>
            <span class="tag-chip" :class="item.has_asmr_one ? 'is-success' : 'is-disabled'">{{ item.has_asmr_one ? '可下载' : '无源' }}</span>
            <ExternalSearchSourceChips :item="item" @open="emit('external-search', $event)" />
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
  border: 1px solid var(--circle-work-card-border, rgba(148, 163, 184, 0.22));
  background: var(--circle-work-card-bg, linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(248, 251, 255, 0.94) 100%));
  color: var(--circle-text, #334155);
  position: relative;
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  transition:
    border-color .2s cubic-bezier(.4,0,.2,1),
    box-shadow .28s cubic-bezier(.4,0,.2,1),
    transform .22s cubic-bezier(.34,1.56,.64,1),
    background-color .2s ease;
  will-change: transform, box-shadow;
  transform: translateZ(0);
  contain: layout paint;
  height: max-content;
  box-shadow: var(--circle-work-card-shadow, inset 0 1px 0 rgba(255, 255, 255, 0.88), 0 8px 20px rgba(15, 23, 42, 0.045));
  animation: workCardEntrance .38s cubic-bezier(.22,1,.36,1) both;
  animation-delay: calc(var(--card-index, 0) * 28ms);
}

/* ── 选中指示器光环 ── */
.work-card-select-ring {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  border: 3px solid transparent;
  pointer-events: none;
  z-index: 12;
  transition: border-color .22s ease, box-shadow .28s ease;
}
.work-card.selected .work-card-select-ring {
  border-color: color-mix(in srgb, var(--circle-primary, #2563eb) 86%, transparent);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--circle-surface, #ffffff) 92%, transparent),
    0 0 0 3px color-mix(in srgb, var(--circle-primary, #2563eb) 20%, transparent);
  animation: selectRingPulse .5s cubic-bezier(.4,0,.2,1);
  animation-delay: var(--selection-pulse-delay, 0ms);
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
  background: var(--circle-work-cover-bg, linear-gradient(135deg, rgba(241, 245, 249, 0.96), rgba(248, 250, 252, 0.82)));
  border-bottom: 1px solid var(--circle-border-soft, rgba(148, 163, 184, 0.16));
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
.work-card.is-completion-dimmed .work-cover {
  filter: grayscale(1) saturate(0.22) brightness(0.74);
}
.work-card.is-completion-dimmed .work-cover-wrapper::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  background: rgba(15, 23, 42, 0.22);
}

/* ── 封面占位 ── */
.work-cover-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--circle-text-subtle, #c1c8d1);
  background: var(--circle-surface-muted, #f5f6f8);
}
.work-cover-retry {
  position: absolute;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid color-mix(in srgb, var(--circle-primary, #2563eb) 34%, transparent);
  border-radius: 50%;
  color: var(--circle-primary, #2563eb);
  background: color-mix(in srgb, var(--circle-surface, #fff) 88%, transparent);
  box-shadow: 0 3px 10px rgba(37, 99, 235, 0.12);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.work-cover-retry:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.08);
  border-color: var(--circle-primary, #2563eb);
  background: var(--circle-surface, #fff);
}
.work-cover-retry:active:not(:disabled) { transform: scale(.96); }
.work-cover-retry.is-loading svg { animation: workCoverRetrySpin .85s linear infinite; }
.work-cover-retry:disabled { cursor: wait; opacity: .72; }
@keyframes workCoverRetrySpin { to { transform: rotate(360deg); } }

/* ── 已下载态 ── */
.work-card.is-downloaded {
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 26%, transparent);
  background:
    radial-gradient(circle at top right, color-mix(in srgb, var(--circle-tag-success, #059669) 14%, transparent), transparent 40%),
    var(--circle-work-card-bg, linear-gradient(180deg, #fbfefb 0%, #f3fbf5 100%));
}
.work-card.is-downloaded:hover {
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 38%, transparent);
  box-shadow: var(--circle-work-card-hover-shadow, 0 10px 20px rgba(53, 102, 72, 0.09));
}
.work-card.is-unreleased {
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 28%, transparent);
  background:
    radial-gradient(circle at top left, color-mix(in srgb, var(--circle-tag-primary, #2563eb) 12%, transparent), transparent 42%),
    var(--circle-work-card-bg, linear-gradient(180deg, #fbfcff 0%, #f5f8ff 100%));
}
.work-card.is-unreleased:hover {
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 42%, transparent);
  box-shadow: var(--circle-work-card-hover-shadow, 0 10px 20px rgba(38, 74, 134, 0.08));
}

/* ── hover / selected / flash ── */
.work-card:hover {
  transform: translateY(-3px) scale(1.012);
  border-color: var(--circle-work-card-hover-border, rgba(52, 120, 246, 0.28));
  box-shadow: var(--circle-work-card-hover-shadow, inset 0 1px 0 rgba(255, 255, 255, 0.92), 0 14px 30px rgba(38, 74, 134, 0.12));
  background: var(--circle-work-card-hover-bg, linear-gradient(180deg, rgba(255, 255, 255, 1) 0%, rgba(246, 250, 255, 0.98) 100%));
}
.work-card.selected {
  border-color: color-mix(in srgb, var(--circle-primary, #2563eb) 76%, transparent);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--circle-primary, #2563eb) 16%, transparent),
    0 0 0 2px color-mix(in srgb, var(--circle-primary, #2563eb) 24%, transparent),
    0 10px 24px color-mix(in srgb, var(--circle-primary, #2563eb) 18%, transparent);
  transform: translateY(-1px);
}
.work-card.selected::after {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  z-index: 13;
  border-radius: 14px 14px 0 0;
  background: var(--circle-primary, #2563eb);
  pointer-events: none;
}
.work-card.selected:hover {
  transform: translateY(-3px) scale(1.01);
}
.work-card.status-flash {
  animation: workStatusFlash 2.4s ease;
  border-color: color-mix(in srgb, var(--circle-tag-success, #059669) 58%, transparent);
  box-shadow:
    0 0 0 2px rgba(82, 170, 103, 0.16),
    0 12px 24px rgba(73, 137, 91, 0.12);
  background:
    radial-gradient(circle at top right, color-mix(in srgb, var(--circle-tag-success, #059669) 18%, transparent), transparent 36%),
    var(--circle-work-card-bg, linear-gradient(180deg, #fcfffb 0%, #eefaf0 100%));
}
.work-card.status-flash.selected {
  border-color: rgba(82, 170, 103, 0.6);
}
.work-card.locate-flash {
  animation: workLocateFlash 2.8s cubic-bezier(0.22, 1, 0.36, 1);
  border-color: color-mix(in srgb, var(--circle-tag-warning, #f59e0b) 70%, transparent);
  box-shadow:
    0 0 0 2px color-mix(in srgb, var(--circle-tag-warning, #f59e0b) 28%, transparent),
    0 0 0 8px color-mix(in srgb, var(--circle-primary, #2563eb) 12%, transparent),
    0 18px 32px rgba(37, 99, 235, 0.18);
  background:
    radial-gradient(circle at 16% 18%, color-mix(in srgb, var(--circle-tag-warning, #f59e0b) 24%, transparent), transparent 34%),
    radial-gradient(circle at top right, color-mix(in srgb, var(--circle-primary, #2563eb) 18%, transparent), transparent 42%),
    var(--circle-work-card-bg, linear-gradient(180deg, #fffdf5 0%, #f4f8ff 100%));
}
.work-card.disabled {
  opacity: .94;
  filter: saturate(0.5) grayscale(0.14);
  background: var(--circle-surface-muted, linear-gradient(180deg, #fafbfd 0%, #f1f3f6 100%));
  border-color: var(--circle-border-soft, rgba(29, 29, 31, 0.06));
  cursor: default;
}
.work-card.disabled:hover {
  transform: translateY(-1px);
  box-shadow: var(--circle-shadow-soft, 0 6px 12px rgba(29, 29, 31, 0.04));
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
  0% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.24); }
  60% { box-shadow: 0 0 0 6px rgba(37, 99, 235, 0); }
  100% {
    box-shadow:
      inset 0 0 0 1px rgba(255, 255, 255, 0.88),
      0 0 0 3px rgba(37, 99, 235, 0.08);
  }
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
@keyframes workLocateFlash {
  0% {
    transform: translateY(-2px) scale(0.98);
    filter: saturate(1.15);
    box-shadow:
      0 0 0 0 color-mix(in srgb, var(--circle-tag-warning, #f59e0b) 46%, transparent),
      0 8px 18px rgba(37, 99, 235, 0.1);
  }
  22% {
    transform: translateY(-5px) scale(1.025);
    filter: saturate(1.3);
    box-shadow:
      0 0 0 5px color-mix(in srgb, var(--circle-tag-warning, #f59e0b) 28%, transparent),
      0 0 0 12px color-mix(in srgb, var(--circle-primary, #2563eb) 12%, transparent),
      0 20px 34px rgba(37, 99, 235, 0.2);
  }
  58% {
    transform: translateY(-2px) scale(1.01);
  }
  100% {
    transform: translateY(0) scale(1);
    filter: saturate(1);
    box-shadow:
      0 0 0 0 color-mix(in srgb, var(--circle-tag-warning, #f59e0b) 0%, transparent),
      0 8px 20px rgba(15, 23, 42, 0.045);
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
  border: 1px solid color-mix(in srgb, var(--circle-tag-primary, #2563eb) 24%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--circle-surface, #ffffff) 64%, transparent);
  backdrop-filter: blur(12px) saturate(1.6);
  color: var(--circle-tag-primary, #2563eb);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: .02em;
  box-shadow: 0 2px 8px rgba(38, 74, 134, 0.08);
  transition: transform .2s cubic-bezier(.34,1.56,.64,1), border-color .2s ease, background .2s ease;
}
.work-card:hover .work-unreleased-flag {
  transform: translateY(-1px) scale(1.03);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 34%, transparent);
  background: color-mix(in srgb, var(--circle-surface, #ffffff) 78%, transparent);
}
.work-new-flag {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, var(--circle-tag-orange, #ea580c) 24%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--circle-tag-orange-soft, rgba(255, 248, 240, 0.45)) 72%, transparent);
  backdrop-filter: blur(12px) saturate(1.6);
  color: var(--circle-tag-orange, #ea580c);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: .02em;
  box-shadow: 0 2px 8px rgba(249, 115, 22, 0.10);
  transition: transform .2s cubic-bezier(.34,1.56,.64,1), border-color .2s ease, background .2s ease;
}
.work-new-flag--below {
  top: 38px;
}
.work-card:hover .work-new-flag {
  transform: translateY(-1px) scale(1.03);
  border-color: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 36%, transparent);
  background: color-mix(in srgb, var(--circle-tag-orange-soft, rgba(255, 248, 240, 0.62)) 88%, transparent);
}
.work-bonus-flag {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 24%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--circle-tag-violet-soft, rgba(250, 245, 255, 0.74)) 86%, transparent);
  backdrop-filter: blur(12px) saturate(1.4);
  color: var(--circle-tag-violet, #7e22ce);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  box-shadow: 0 3px 10px rgba(126, 34, 206, 0.14);
  transition: transform .2s cubic-bezier(.34,1.56,.64,1), background .2s ease, top .2s ease;
}
.work-bonus-flag--below {
  top: 38px;
}
.work-bonus-flag--double-below {
  top: 68px;
}
.work-card:hover .work-bonus-flag {
  transform: translateY(-1px) scale(1.03);
  background: color-mix(in srgb, var(--circle-tag-violet-soft, rgba(250, 245, 255, 0.9)) 96%, transparent);
}
/* ── 新作边框光圈 ── */
.work-card.is-new-work {
  border-color: color-mix(in srgb, var(--circle-tag-orange, #f97316) 55%, transparent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--circle-tag-orange, #f97316) 12%, transparent), 0 0 22px color-mix(in srgb, var(--circle-tag-orange, #f97316) 20%, transparent);
}
.work-card.is-new-work:hover {
  border-color: color-mix(in srgb, var(--circle-tag-orange, #f97316) 72%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--circle-tag-orange, #f97316) 16%, transparent), 0 0 30px color-mix(in srgb, var(--circle-tag-orange, #f97316) 28%, transparent);
}
.work-card.is-new-work .work-card-select-ring {
  border-color: color-mix(in srgb, var(--circle-tag-orange, #f97316) 70%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--circle-tag-orange, #f97316) 14%, transparent), 0 0 24px color-mix(in srgb, var(--circle-tag-orange, #f97316) 22%, transparent);
}
/* ── 未发售边框光圈 ── */
.work-card.is-unreleased {
  border-color: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 45%, transparent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 10%, transparent), 0 0 18px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 16%, transparent);
}
.work-card.is-unreleased:hover {
  border-color: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 65%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 14%, transparent), 0 0 26px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 22%, transparent);
}
.work-card.is-unreleased .work-card-select-ring {
  border-color: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 60%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 12%, transparent), 0 0 20px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 18%, transparent);
}
.work-release-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 18px;
  padding: 0 6px;
  border: 1px solid color-mix(in srgb, var(--circle-tag-primary, #2563eb) 22%, transparent);
  border-radius: 5px;
  background: color-mix(in srgb, var(--circle-tag-primary, #2563eb) 8%, transparent);
  color: var(--circle-tag-primary, #2f66c0);
  font-size: 9px;
  font-weight: 800;
  line-height: 1;
}

/* ── 卡片内容 ── */
.work-card-body {
  display: grid;
  grid-template-rows: 12px 34px 16px 14px 24px 28px;
  gap: 3px;
  padding: 8px 9px 9px;
  flex: 1;
  min-height: 0;
}
.work-rj {
  font-size: 9px;
  font-weight: 700;
  color: var(--circle-text-muted, #6d8bb5);
  letter-spacing: .03em;
  line-height: 12px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color .2s ease;
}
.work-card:hover .work-rj {
  color: var(--circle-primary, #3478f6);
}
.work-card.disabled .work-rj,
.work-card.disabled .work-title,
.work-card.disabled .work-linked {
  color: var(--circle-text-subtle, rgba(29, 29, 31, 0.36));
}

/* ── 标题 ── */
.work-title {
  font-size: 11px;
  font-weight: 800;
  color: var(--circle-text-strong, #1f3554);
  line-height: 1.38;
  display: -webkit-box;
  height: calc(1.38em * 2);
  min-height: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  transition: color .2s ease;
}
.work-card:hover .work-title {
  color: var(--circle-primary, #2563eb);
}

/* ── 关联信息 ── */
.work-linked {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 6px;
  font-size: 9px;
  color: var(--circle-text-muted, rgba(29, 29, 31, 0.40));
  line-height: 16px;
  min-width: 0;
  height: 16px;
  overflow: hidden;
  white-space: nowrap;
}
.work-linked > span:first-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 已发售日期内联小段 ── */
.work-release-inline {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex: 0 0 auto;
  font-size: 9px;
  font-weight: 500;
  color: var(--circle-text-muted, rgba(71, 85, 105, 0.85));
}
.work-release-inline :first-child {
  color: var(--circle-text-subtle, rgba(148, 163, 184, 0.95));
}
.work-card--lg .work-release-inline {
  font-size: 10px;
}

/* ── CV 名 ── */
.work-cv {
  font-size: 9px;
  color: #0ea5e9;
  -webkit-text-fill-color: currentColor;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 14px;
  height: 14px;
}
.work-cv.is-empty {
  visibility: hidden;
}

/* ── 标签区 ── */
.work-tags {
  display: flex;
  gap: 4px;
  align-items: center;
  flex-wrap: nowrap;
  min-width: 0;
  overflow: hidden;
  height: 24px;
  padding-top: 3px;
}

/* ── 操作区 ── */
.work-actions {
  display: flex;
  justify-content: stretch;
  gap: 4px;
  width: 100%;
  height: 28px;
  padding-top: 2px;
  box-sizing: border-box;
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
  overflow: visible;
  transition:
    opacity .22s ease,
    transform .24s cubic-bezier(.34,1.56,.64,1);
  margin-top: 0;
}
.work-card:hover .work-actions {
  pointer-events: auto;
}

/* ── 状态标签 ── */
.tag-chip {
  height: 19px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 1 auto;
  min-width: 0;
  padding: 0 7px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-radius: 5px;
  font-size: 9px;
  font-weight: 750;
  line-height: 1;
  letter-spacing: 0.02em;
  background: var(--circle-chip-bg, rgba(248, 250, 252, 0.72));
  border: 1px solid var(--circle-chip-border, rgba(203, 213, 225, 0.72));
  color: var(--circle-text-muted, #64748b);
  box-shadow: none;
  transition:
    transform .18s cubic-bezier(.34,1.56,.64,1),
    background-color .18s ease,
    border-color .18s ease;
}
.work-card:hover .tag-chip {
  transform: translateY(-1px);
}
.tag-chip.is-primary {
  background: color-mix(in srgb, var(--circle-tag-primary, #416fae) 8%, transparent);
  color: var(--circle-tag-primary, #416fae);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #416fae) 22%, transparent);
}
.tag-chip.is-success {
  background: color-mix(in srgb, var(--circle-tag-success, #247348) 8%, transparent);
  color: var(--circle-tag-success, #247348);
  border-color: color-mix(in srgb, var(--circle-tag-success, #247348) 22%, transparent);
}
.tag-chip.is-danger {
  background: color-mix(in srgb, var(--circle-tag-danger, #c2412d) 8%, transparent);
  color: var(--circle-tag-danger, #c2412d);
  border-color: color-mix(in srgb, var(--circle-tag-danger, #c2412d) 22%, transparent);
}
.tag-chip.is-warning {
  background: color-mix(in srgb, var(--circle-tag-warning, #b06f13) 8%, transparent);
  color: var(--circle-tag-warning, #b06f13);
  border-color: color-mix(in srgb, var(--circle-tag-warning, #b06f13) 22%, transparent);
}
.tag-chip.is-info {
  background: var(--circle-chip-bg, rgba(244, 246, 249, 0.76));
  color: var(--circle-text-muted, #5d6d81);
  border-color: var(--circle-chip-border, rgba(226, 232, 240, 0.86));
}
.tag-chip.is-subtitle {
  background: color-mix(in srgb, var(--circle-tag-indigo, #4f46e5) 8%, transparent);
  color: var(--circle-tag-indigo, #4f46e5);
  border-color: color-mix(in srgb, var(--circle-tag-indigo, #4f46e5) 22%, transparent);
}
.tag-chip.is-subtitle-none {
  background: var(--circle-chip-bg, rgba(248, 250, 252, 0.78));
  color: var(--circle-text-muted, #64748b);
  border-color: var(--circle-chip-border, rgba(226, 232, 240, 0.86));
}
.tag-chip.is-repair {
  background: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 8%, transparent);
  color: var(--circle-tag-orange, #ea580c);
  border-color: color-mix(in srgb, var(--circle-tag-orange, #ea580c) 22%, transparent);
}
.tag-chip.is-bonus {
  max-width: 100%;
  justify-content: flex-start;
  gap: 3px;
  background: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 8%, transparent);
  color: var(--circle-tag-violet, #7e22ce);
  border-color: color-mix(in srgb, var(--circle-tag-violet, #7e22ce) 22%, transparent);
}
.tag-chip.is-disabled {
  background: var(--circle-chip-bg, rgba(248, 250, 252, 0.72));
  color: var(--circle-text-subtle, #8a97a8);
  border-color: var(--circle-chip-border, rgba(226, 232, 240, 0.86));
}

:global(html.kikoerumanager-dark .work-card),
:global(body.kikoerumanager-dark .work-card) {
  --circle-text: rgba(226, 232, 240, 0.88);
  --circle-text-strong: rgba(248, 250, 252, 0.94);
  --circle-text-muted: rgba(203, 213, 225, 0.74);
  --circle-text-subtle: rgba(148, 163, 184, 0.72);
  --circle-tag-primary: #2563eb;
  --circle-tag-success: #059669;
  --circle-tag-danger: #dc2626;
  --circle-tag-warning: #d97706;
  --circle-tag-orange: #ea580c;
  --circle-tag-violet: #7e22ce;
  --circle-tag-indigo: #4f46e5;
  --circle-chip-bg: rgba(248, 250, 252, 0.10);
  --circle-chip-border: rgba(226, 232, 240, 0.18);
  color: rgba(226, 232, 240, 0.88);
}

:global(html.kikoerumanager-dark .work-card.selected),
:global(body.kikoerumanager-dark .work-card.selected) {
  border-color: rgba(96, 165, 250, 0.82);
  box-shadow:
    inset 0 0 0 1px rgba(96, 165, 250, 0.18),
    0 0 0 2px rgba(96, 165, 250, 0.24),
    0 0 24px rgba(96, 165, 250, 0.18),
    0 18px 36px rgba(0, 0, 0, 0.36);
}

:global(html.kikoerumanager-dark .work-card.selected .work-card-select-ring),
:global(body.kikoerumanager-dark .work-card.selected .work-card-select-ring) {
  border-color: rgba(96, 165, 250, 0.92);
  box-shadow:
    inset 0 0 0 1px rgba(15, 23, 42, 0.48),
    0 0 0 3px rgba(96, 165, 250, 0.16),
    0 0 18px rgba(96, 165, 250, 0.22);
}

:global(html.kikoerumanager-dark .work-card.selected::after),
:global(body.kikoerumanager-dark .work-card.selected::after) {
  background: rgba(96, 165, 250, 0.95);
}

:global(html.kikoerumanager-dark .work-card .work-title),
:global(body.kikoerumanager-dark .work-card .work-title) {
  color: rgba(248, 250, 252, 0.92);
}

:global(html.kikoerumanager-dark .work-card .work-rj),
:global(html.kikoerumanager-dark .work-card .work-linked),
:global(html.kikoerumanager-dark .work-card .work-release-inline),
:global(body.kikoerumanager-dark .work-card .work-rj),
:global(body.kikoerumanager-dark .work-card .work-linked),
:global(body.kikoerumanager-dark .work-card .work-release-inline) {
  color: rgba(203, 213, 225, 0.78);
}

:global(html.kikoerumanager-dark .tag-chip),
:global(body.kikoerumanager-dark .tag-chip) {
  background: rgba(248, 250, 252, 0.12) !important;
  border-color: rgba(226, 232, 240, 0.22) !important;
  color: #cbd5e1 !important;
  box-shadow: none;
}

:global(html.kikoerumanager-dark .tag-chip.is-primary),
:global(body.kikoerumanager-dark .tag-chip.is-primary) {
  background: rgba(37, 99, 235, 0.22) !important;
  border-color: rgba(96, 165, 250, 0.46) !important;
  color: #93c5fd !important;
}

:global(html.kikoerumanager-dark .tag-chip.is-success),
:global(body.kikoerumanager-dark .tag-chip.is-success) {
  background: rgba(5, 150, 105, 0.22) !important;
  border-color: rgba(52, 211, 153, 0.46) !important;
  color: #6ee7b7 !important;
}

:global(html.kikoerumanager-dark .tag-chip.is-danger),
:global(body.kikoerumanager-dark .tag-chip.is-danger) {
  background: rgba(220, 38, 38, 0.22) !important;
  border-color: rgba(248, 113, 113, 0.48) !important;
  color: #fca5a5 !important;
}

:global(html.kikoerumanager-dark .tag-chip.is-disabled),
:global(html.kikoerumanager-dark .tag-chip.is-subtitle-none),
:global(body.kikoerumanager-dark .tag-chip.is-disabled),
:global(body.kikoerumanager-dark .tag-chip.is-subtitle-none) {
  background: rgba(248, 250, 252, 0.12) !important;
  border-color: rgba(226, 232, 240, 0.22) !important;
  color: #cbd5e1 !important;
}

:global(html.kikoerumanager-dark .tag-chip.is-repair),
:global(body.kikoerumanager-dark .tag-chip.is-repair) {
  background: rgba(234, 88, 12, 0.22) !important;
  border-color: rgba(251, 146, 60, 0.46) !important;
  color: #fdba74 !important;
}

:global(html.kikoerumanager-dark .tag-chip.is-subtitle),
:global(body.kikoerumanager-dark .tag-chip.is-subtitle) {
  background: rgba(79, 70, 229, 0.22) !important;
  border-color: rgba(129, 140, 248, 0.46) !important;
  color: #c7d2fe !important;
}

:global(html.kikoerumanager-dark .tag-chip.is-bonus),
:global(body.kikoerumanager-dark .tag-chip.is-bonus) {
  background: rgba(126, 34, 206, 0.22) !important;
  border-color: rgba(192, 132, 252, 0.46) !important;
  color: #d8b4fe !important;
}

:global(html.kikoerumanager-dark .work-release-chip),
:global(body.kikoerumanager-dark .work-release-chip) {
  background: rgba(37, 99, 235, 0.24) !important;
  border-color: rgba(96, 165, 250, 0.52) !important;
  color: #bfdbfe !important;
  box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.10);
}

:global(html.kikoerumanager-dark .work-unreleased-flag),
:global(body.kikoerumanager-dark .work-unreleased-flag) {
  background: rgba(15, 23, 42, 0.72) !important;
  border-color: rgba(96, 165, 250, 0.58) !important;
  color: #bfdbfe !important;
  box-shadow: none;
}

:global(html.kikoerumanager-dark .work-card:hover .work-unreleased-flag),
:global(body.kikoerumanager-dark .work-card:hover .work-unreleased-flag) {
  background: rgba(30, 41, 59, 0.78) !important;
  border-color: rgba(147, 197, 253, 0.68) !important;
}

:global(html.kikoerumanager-dark .work-cv),
:global(body.kikoerumanager-dark .work-cv) {
  color: #38bdf8 !important;
  -webkit-text-fill-color: #38bdf8 !important;
  text-shadow: 0 0 0.5px rgba(14, 165, 233, 0.45), 0 0 8px rgba(14, 165, 233, 0.16);
  font-weight: 700;
}

/* ── 迷你操作按钮 ── */
.work-action-btn {
  flex: 1;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid color-mix(in srgb, var(--circle-text-muted, #64748b) 26%, transparent);
  background: color-mix(in srgb, var(--circle-surface, #ffffff) 58%, transparent);
  color: var(--circle-text, #334155);
  height: 24px;
  min-height: 0;
  padding: 0 6px;
  border-radius: 8px;
  font-size: 9px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  transition:
    transform .22s cubic-bezier(.34,1.56,.64,1),
    background-color .18s ease,
    border-color .18s ease,
    color .18s ease,
    box-shadow .18s ease;
  box-shadow: none;
}
.work-action-btn:hover {
  background: color-mix(in srgb, var(--circle-text, #334155) 7%, var(--circle-surface, #ffffff));
  border-color: color-mix(in srgb, var(--circle-text, #334155) 32%, transparent);
  color: var(--circle-text-strong, #1f2937);
  box-shadow: none;
  transform: translateY(-2px);
}
.work-action-btn:active {
  transform: scale(0.96);
}
.work-action-btn.upload {
  border-color: color-mix(in srgb, var(--circle-success, #247348) 24%, transparent);
  background: color-mix(in srgb, var(--circle-success, #247348) 7%, var(--circle-surface, #ffffff));
  color: var(--circle-success, #247348);
}
.work-action-btn.upload:hover {
  background: color-mix(in srgb, var(--circle-success, #247348) 10%, var(--circle-surface, #ffffff));
  border-color: color-mix(in srgb, var(--circle-success, #16653d) 34%, transparent);
  color: var(--circle-success, #16653d);
  box-shadow: none;
}

/* ── lg 尺寸变体 ── */
.work-card--lg {
  border-radius: 16px;
}
.work-card--lg .work-card-select-ring {
  border-radius: inherit;
}
.work-card--lg .work-cover-wrapper {
  aspect-ratio: 4 / 3;
}
.work-card--lg .work-card-body {
  grid-template-rows: 14px 36px 17px 15px 26px 30px;
  gap: 4px;
  padding: 10px 12px 12px;
}
.work-card--lg .work-rj {
  font-size: 11px;
  line-height: 14px;
}
.work-card--lg .work-title {
  font-size: 13px;
  height: calc(1.38em * 2);
  min-height: 0;
}
.work-card--lg .work-linked {
  font-size: 10px;
  height: 17px;
  line-height: 17px;
}
.work-card--lg .work-cv {
  height: 15px;
  line-height: 15px;
}
.work-card--lg .tag-chip {
  height: 22px;
  padding: 0 7px;
  font-size: 10px;
  border-radius: 6px;
}
.work-card--lg .work-action-btn {
  height: 28px;
  min-height: 0;
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

@media (max-width: 640px) {
  .work-card {
    width: 100%;
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
  }
  .work-cover-wrapper,
  .work-card-body,
  .work-tags,
  .work-actions {
    min-width: 0;
    max-width: 100%;
  }
  .work-card-body {
    grid-template-rows: 12px 32px 15px 13px 23px 28px;
    gap: 3px;
    padding: 7px 7px 8px;
  }
  .work-rj,
  .work-title,
  .work-linked,
  .work-cv {
    min-width: 0;
    max-width: 100%;
    overflow-wrap: anywhere;
  }
  .work-title {
    font-size: 10.5px;
    word-break: break-word;
  }
  .work-linked,
  .work-cv {
    font-size: 8.5px;
  }
  .work-linked {
    height: 15px;
    line-height: 15px;
  }
  .work-cv {
    height: 13px;
    line-height: 13px;
  }
  .work-tags {
    gap: 2px;
    overflow: hidden;
    height: 23px;
  }
  .tag-chip {
    min-width: 0;
    max-width: 100%;
    padding: 0 4px;
    font-size: 8.5px;
  }
  .work-actions {
    opacity: 1;
    transform: translateY(0);
    pointer-events: auto;
  }
  .work-action-btn {
    min-width: 0;
    padding: 0 4px;
    font-size: 8.5px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
</style>
