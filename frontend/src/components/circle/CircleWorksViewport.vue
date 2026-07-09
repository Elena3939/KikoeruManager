<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { Calendar, Gift, PackageCheck } from 'lucide-vue-next'
import WorkCard from './WorkCard.vue'
import WorkListRow from './WorkListRow.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  mode: { type: String, default: 'card', validator: value => ['card', 'list'].includes(value) },
  currentPage: { type: Number, default: 1 },
  pageSize: { type: Number, default: 10 },
  pageSizes: { type: Array, default: () => [10, 20, 50, 100] },
  totalItems: { type: Number, default: null },
  serverPaging: { type: Boolean, default: false },
  selectedCodes: { type: Object, default: () => new Set() },
  flashedCodes: { type: Object, default: () => new Set() },
  locatedCodes: { type: Object, default: () => new Set() },
  imageField: { type: String, default: 'image_url' },
  cornerLabel: { type: String, default: '' },
  pagerLabel: { type: String, default: '作品' },
  emptyText: { type: String, default: '没有找到符合条件的作品' },
})

const emit = defineEmits([
  'update:currentPage',
  'update:pageSize',
  'select',
  'preview',
  'reimport',
])

const scrollRef = ref(null)
const viewportRef = ref(null)
const viewportWidth = ref(0)
const motionActive = ref(false)
const activeImageKeys = ref(new Set())
const loadingImageKeys = ref(new Set())
const queuedImageKeys = ref([])
const activeBonusDetail = ref(null)

let resizeObserver = null
let motionTimer = null
const imageLoadTimers = new Map()
const MAX_ACTIVE_IMAGES = 8

const safeItems = computed(() => Array.isArray(props.items) ? props.items : [])
const totalItems = computed(() => {
  const value = Number(props.totalItems)
  return props.serverPaging && Number.isFinite(value) && value >= 0 ? value : displayGroups.value.length
})
const normalizedPageSize = computed(() => {
  const size = Number(props.pageSize || 10)
  return Number.isFinite(size) && size > 0 ? size : 10
})
const pageCount = computed(() => Math.max(1, Math.ceil(totalItems.value / normalizedPageSize.value)))
const normalizedPage = computed(() => {
  const page = Number(props.currentPage || 1)
  if (!Number.isFinite(page)) return 1
  return Math.min(Math.max(1, page), pageCount.value)
})
function isStrictTrue(value) {
  if (value === true || value === 1 || value === '1') return true
  if (typeof value === 'string') return value.trim().toLowerCase() === 'true'
  return false
}

function normalizeRjcode(value) {
  const text = String(value || '').trim().toUpperCase()
  const match = text.match(/[RVB]J(\d{6}|\d{8})(?!\d)/i)
  return match ? match[0] : text
}

function itemCodes(item) {
  return [
    item?.canonical_rjcode,
    item?.display_rjcode,
    item?.rjcode,
    item?.download_plan?.rjcode,
    item?.asmr_available_rjcode,
    item?.source_compare?.work_rjcode,
    ...(Array.isArray(item?.linked_rjcodes) ? item.linked_rjcodes : []),
  ].map(normalizeRjcode).filter(Boolean)
}

function ownBonusCodes(item) {
  return [
    item?.display_rjcode,
    item?.rjcode,
    item?.download_plan?.rjcode,
    item?.asmr_available_rjcode,
    item?.source_compare?.work_rjcode,
  ].map(normalizeRjcode).filter(Boolean)
}

function bonusParentCode(item, availableCodes = new Set()) {
  if (!isStrictTrue(item?.is_bonus_work)) return ''
  const selfCodes = new Set(ownBonusCodes(item))
  const explicitParent = normalizeRjcode(item?.bonus_parent_rjcode)
  if (explicitParent && !selfCodes.has(explicitParent) && availableCodes.has(explicitParent)) return explicitParent
  const canonical = normalizeRjcode(item?.canonical_rjcode)
  if (canonical && !selfCodes.has(canonical) && availableCodes.has(canonical)) return canonical

  const linked = Array.isArray(item?.linked_rjcodes) ? item.linked_rjcodes : []
  for (const code of linked) {
    const normalized = normalizeRjcode(code)
    if (normalized && !selfCodes.has(normalized) && availableCodes.has(normalized)) return normalized
  }
  return ''
}

function canDownloadBonus(bonus) {
  const members = bonusMembers(bonus)
  if (members.length > 1) return members.some(canDownloadBonus)
  return isStrictTrue(bonus?.has_asmr_one) || Boolean(bonus?.download_plan?.rjcode || bonus?.asmr_available_rjcode)
}

const activeBonusDetailCover = computed(() => activeBonusDetail.value ? bonusMainCoverUrl(activeBonusDetail.value) : '')

function isActiveBonus(bonus) {
  const active = activeBonusDetail.value
  if (!active || !bonus) return false
  if (active === bonus) return true
  const activeCodes = new Set(bonusCodeList(active))
  return bonusCodeList(bonus).some(code => activeCodes.has(code))
}

function hasActiveBonus(bonuses = []) {
  return Array.isArray(bonuses) && bonuses.some(isActiveBonus)
}

function isCompletionOwned(item) {
  const members = bonusMembers(item)
  if (members.length > 1) return members.some(isCompletionOwned)
  return isStrictTrue(item?.server_owned) || isStrictTrue(item?.owned) || isStrictTrue(item?.completion_owned) || isStrictTrue(item?.local_owned)
}

function bonusOwnedLabel(bonus) {
  return isCompletionOwned(bonus) ? '已收录' : '未收录'
}

function bonusOwnedTagClass(bonus) {
  return bonusOwnedLabel(bonus) === '已收录' ? 'is-primary' : 'is-danger'
}

function bonusDownloadLabel(bonus) {
  return hasLocalDownloadReadyBonus(bonus) || canDownloadBonus(bonus) ? '可下载' : '无源'
}

function bonusDownloadTagClass(bonus) {
  return bonusDownloadLabel(bonus) === '可下载' ? 'is-success' : 'is-disabled'
}

function bonusCvLabel(bonus) {
  const target = bonusActionItem(bonus)
  const cvs = Array.isArray(target?.cvs) ? target.cvs.map(value => String(value || '').trim()).filter(Boolean) : []
  if (cvs.length) return cvs.join(' / ')
  const makerName = String(target?.maker_name || '').trim()
  if (!makerName) return ''
  return makerName.split('/').map(value => value.trim()).filter(Boolean).pop() || ''
}

function isItemSelected(item) {
  const code = String(item?.canonical_rjcode || '').trim()
  return Boolean(code && props.selectedCodes?.has?.(code))
}

function hasRenderedBonuses(bonuses) {
  return Array.isArray(bonuses) && bonuses.length > 0
}

function groupHasOwnedWork(item, bonuses) {
  return isCompletionOwned(item) || (Array.isArray(bonuses) && bonuses.some(isCompletionOwned))
}

function shouldDimWorkCard(viewModel) {
  return Boolean(viewModel?.completionDimmed)
}

function shouldDimBonusCard(bonusViewModel) {
  return Boolean(bonusViewModel?.dimmed)
}

function openBonusDetail(bonus) {
  activeBonusDetail.value = bonus
  const target = bonusActionItem(bonus, 'select')
  if (!isItemSelected(target)) emit('select', target)
}

function closeBonusDetail() {
  const bonus = activeBonusDetail.value
  activeBonusDetail.value = null
  const target = bonusActionItem(bonus, 'deselect')
  if (isItemSelected(target)) emit('select', target)
}

function handleBonusAction(bonus) {
  emit('reimport', bonusActionItem(bonus, 'import'))
}

function previewBonus(bonus) {
  const target = bonusActionItem(bonus, 'preview')
  emit('preview', target?.canonical_rjcode || bonusCode(target))
}

function forwardRowSelect(item) {
  emit('select', bonusActionItem(item, 'select'))
}

function forwardRowPreview(payload, fallbackItem = null) {
  if (payload && typeof payload === 'object') {
    previewBonus(payload)
    return
  }
  if (fallbackItem?._bonus_members?.length) {
    previewBonus(fallbackItem)
    return
  }
  emit('preview', payload)
}

function forwardRowReimport(item) {
  emit('reimport', bonusActionItem(item, 'import'))
}

function normalizeBonusGroupTitle(value) {
  return String(value || '')
    .trim()
    .replace(/[＿_][\s　]*(?:\d+|[０-９]+)\s*$/u, '')
    .trim()
}

function bonusDisplayTitle(item) {
  return String(item?._bonus_display_title || item?.title || '未命名特典').trim()
}

function bonusMembers(item) {
  return Array.isArray(item?._bonus_members) && item._bonus_members.length ? item._bonus_members : [item].filter(Boolean)
}

function bonusCodeList(item) {
  return bonusMembers(item)
    .map(member => bonusCode(member))
    .filter(Boolean)
    .filter((code, index, array) => array.indexOf(code) === index)
}

function hasLocalDownloadReadyBonus(item) {
  return bonusMembers(item).some(member => Boolean(member?.local_download_ready))
}

function bonusActionItem(item, action = '') {
  const members = bonusMembers(item)
  if (action === 'import') return members.find(member => member?.local_download_ready) || members[0] || item
  if (action === 'preview') return members.find(canDownloadBonus) || members[0] || item
  if (action === 'select') return members.find(member => !isItemSelected(member)) || members[0] || item
  if (action === 'deselect') return members.find(isItemSelected) || members[0] || item
  return members[0] || item
}

function aggregateBonusWorks(bonuses = []) {
  if (!Array.isArray(bonuses) || bonuses.length <= 1) return Array.isArray(bonuses) ? bonuses : []
  const buckets = new Map()
  const result = []
  for (const bonus of bonuses) {
    if (!bonus) continue
    const title = bonusDisplayTitle(bonus)
    const baseTitle = normalizeBonusGroupTitle(title)
    const key = baseTitle || title || bonusCode(bonus)
    if (!key) {
      result.push(bonus)
      continue
    }
    let bucket = buckets.get(key)
    if (!bucket) {
      bucket = {
        ...bonus,
        title: baseTitle || title,
        _bonus_display_title: baseTitle || title,
        _bonus_members: [bonus],
      }
      buckets.set(key, bucket)
      result.push(bucket)
      continue
    }
    bucket._bonus_members.push(bonus)
    bucket.linked_rjcodes = bonusCodeList(bucket)
    bucket.local_download_ready = hasLocalDownloadReadyBonus(bucket)
    bucket.has_asmr_one = bucket.has_asmr_one || bonus.has_asmr_one
    bucket.owned = isCompletionOwned(bucket)
    bucket.server_owned = bucket.server_owned || bonus.server_owned
    bucket.completion_owned = bucket.completion_owned || bonus.completion_owned
    bucket.local_owned = bucket.local_owned || bonus.local_owned
    if (!bucket.image_url && bonus.image_url) bucket.image_url = bonus.image_url
    if (!bucket.thumb_image_url && bonus.thumb_image_url) bucket.thumb_image_url = bonus.thumb_image_url
  }
  return result
}

const groupedItems = computed(() => {
  const items = safeItems.value
  const directGroups = items.map((item, index) => {
    const bonuses = aggregateBonusWorks(Array.isArray(item?.bonus_works) ? item.bonus_works : [])
    return { item, bonuses, sourceIndex: index }
  })
  if (directGroups.some(group => group.bonuses.length)) {
    const attachedBonusCodes = new Set()
    for (const group of directGroups) {
      for (const bonus of group.bonuses || []) {
        for (const code of bonusCodeList(bonus)) {
          if (code) attachedBonusCodes.add(code)
        }
      }
    }
    return directGroups.filter(group => {
      if (!isStrictTrue(group.item?.is_bonus_work)) return true
      const code = bonusCode(group.item)
      return !code || !attachedBonusCodes.has(code)
    })
  }

  const codeToItem = new Map()
  for (const item of items) {
    for (const code of itemCodes(item)) {
      const existing = codeToItem.get(code)
      if (!existing || (isStrictTrue(existing?.is_bonus_work) && !isStrictTrue(item?.is_bonus_work))) {
        codeToItem.set(code, item)
      }
    }
  }

  const availableCodes = new Set(codeToItem.keys())
  const bonusBuckets = new Map()
  const hiddenBonusItems = new Set()
  for (const item of items) {
    const parentCode = bonusParentCode(item, availableCodes)
    const parentItem = parentCode ? codeToItem.get(parentCode) : null
    if (!parentItem || parentItem === item || isStrictTrue(parentItem?.is_bonus_work)) continue
    const parentKey = itemKey(parentItem, items.indexOf(parentItem))
    if (!bonusBuckets.has(parentKey)) bonusBuckets.set(parentKey, [])
    bonusBuckets.get(parentKey).push(item)
    hiddenBonusItems.add(item)
  }

  return items
    .filter(item => !hiddenBonusItems.has(item))
    .map((item, index) => {
      const key = itemKey(item, index)
      return { item, bonuses: aggregateBonusWorks(bonusBuckets.get(key) || []), sourceIndex: index }
    })
})

watch(groupedItems, groups => {
  const activeCodes = new Set(bonusCodeList(activeBonusDetail.value))
  if (!activeCodes.size) return
  for (const group of groups) {
    for (const bonus of group.bonuses || []) {
      if (bonusCodeList(bonus).some(code => activeCodes.has(code))) {
        if (activeBonusDetail.value !== bonus) activeBonusDetail.value = bonus
        return
      }
    }
  }
})

const displayGroups = computed(() => {
  if (props.mode === 'card') return groupedItems.value

  return groupedItems.value.flatMap(group => {
    const groups = [{ ...group, bonuses: [] }]
    for (const [index, bonus] of (group.bonuses || []).entries()) {
      groups.push({
        item: bonus,
        bonuses: [],
        sourceIndex: `${group.sourceIndex}:bonus:${index}`,
      })
    }
    return groups
  })
})
const pagedGroups = computed(() => {
  if (props.serverPaging) return displayGroups.value
  const start = (normalizedPage.value - 1) * normalizedPageSize.value
  return displayGroups.value.slice(start, start + normalizedPageSize.value)
})
const isCardMode = computed(() => props.mode === 'card')
const gridGap = computed(() => isCardMode.value ? 10 : 6)
const columnCount = computed(() => {
  if (!isCardMode.value) return 1
  const width = Number(viewportWidth.value || 0)
  if (width <= 0) return 1
  const minCardWidth = width <= 640 ? 152 : 156
  return Math.max(1, Math.floor((width + gridGap.value) / (minCardWidth + gridGap.value)))
})
const columnWidth = computed(() => {
  if (!isCardMode.value) return Number(viewportWidth.value || 0)
  const width = Number(viewportWidth.value || 0)
  const columns = Math.max(1, columnCount.value)
  if (width <= 0) return 156
  return Math.max(152, (width - gridGap.value * (columns - 1)) / columns)
})
const bonusShelfStyle = computed(() => {
  if (!isCardMode.value) return {}
  const width = Math.max(152, Number(columnWidth.value || 156))
  const coverHeight = width * 0.75
  const maxGiftWidth = viewportWidth.value <= 640 ? 76 : 88
  const giftWidth = Math.min(width * 0.39, maxGiftWidth)
  const inset = viewportWidth.value <= 640 ? 7 : 8
  return {
    '--bonus-shelf-top': `${Math.max(inset, Math.round(coverHeight - giftWidth * 0.75 - inset))}px`,
  }
})
const rowCount = computed(() => {
  if (!pagedGroups.value.length) return 0
  return Math.ceil(pagedGroups.value.length / columnCount.value)
})
const itemViewModels = computed(() => pagedGroups.value.map((group, index) => {
  const item = group.item
  const bonuses = Array.isArray(group.bonuses) ? group.bonuses : []
  const itemCodes = bonusCodeList(item)
  const code = String(itemCodes[0] || item?.canonical_rjcode || '').trim()
  const key = itemKey(item, group.sourceIndex ?? index)
  const itemOwned = isCompletionOwned(item)
  const groupOwned = itemOwned || bonuses.some(isCompletionOwned)
  const completionDimmed = props.mode === 'card' && bonuses.length
    ? groupOwned && !itemOwned
    : isStrictTrue(item?.completion_card_dimmed)
  const bonusViewModels = bonuses.map((bonus, bonusIndex) => {
    const bonusKey = itemKey(bonus, `${key}:bonus:${bonusIndex}`)
    const bonusCodes = bonusCodeList(bonus)
    const bonusCodeValue = bonusCodes[0] || ''
    const bonusOwned = isCompletionOwned(bonus)
    return {
      item: bonus,
      index: bonusIndex,
      key: bonusKey,
      code: bonusCodeValue,
      owned: bonusOwned,
      dimmed: groupOwned && !bonusOwned,
      selected: bonusCodes.some(code => props.selectedCodes?.has?.(code)),
      flashed: bonusCodes.some(code => props.flashedCodes?.has?.(code)),
      located: bonusCodes.some(code => props.locatedCodes?.has?.(code)),
    }
  })
  return {
    item,
    bonuses,
    bonusViewModels,
    index,
    key,
    code,
    itemOwned,
    groupOwned,
    completionDimmed,
    selected: itemCodes.some(value => props.selectedCodes?.has?.(value)) || Boolean(code && props.selectedCodes?.has?.(code)),
    flashed: itemCodes.some(value => props.flashedCodes?.has?.(value)) || Boolean(code && props.flashedCodes?.has?.(code)),
    located: itemCodes.some(value => props.locatedCodes?.has?.(value)) || Boolean(code && props.locatedCodes?.has?.(code)),
  }
}))
const rowViewModels = computed(() => {
  const columns = Math.max(1, columnCount.value)
  const rows = []
  for (let start = 0; start < itemViewModels.value.length; start += columns) {
    rows.push(itemViewModels.value.slice(start, start + columns).map((viewModel, offset) => ({
      ...viewModel,
      columnIndex: offset,
    })))
  }
  return rows
})
const usePlainRender = computed(() => viewportWidth.value > 0 && viewportWidth.value <= 640)
const virtualRowHeight = computed(() => {
  if (!isCardMode.value) return viewportWidth.value <= 640 ? 58 : 60
  const coverHeight = Math.round(columnWidth.value * 0.75)
  const bodyHeight = viewportWidth.value <= 640 ? 150 : 164
  return coverHeight + bodyHeight + gridGap.value
})
const virtualOverscan = computed(() => isCardMode.value ? 2 : 10)
const gridTemplateColumns = computed(() => `repeat(${columnCount.value}, minmax(0, 1fr))`)

const rowVirtualizer = useVirtualizer(computed(() => ({
  count: rowCount.value,
  getScrollElement: () => scrollRef.value,
  estimateSize: () => virtualRowHeight.value,
  overscan: virtualOverscan.value,
})))

const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const visibleImageKeys = computed(() => {
  if (usePlainRender.value) {
    return itemViewModels.value.flatMap(item => [
      item.key,
      ...item.bonusViewModels.map(bonus => bonus.key),
    ])
  }
  const keys = []
  for (const virtualRow of virtualRows.value) {
    for (const cell of getRowItems(virtualRow.index)) {
      keys.push(cell.key)
      for (const bonus of cell.bonusViewModels) {
        keys.push(bonus.key)
      }
    }
  }
  return keys
})
const virtualCanvasStyle = computed(() => ({
  height: `${rowVirtualizer.value.getTotalSize()}px`,
}))
const currentPageModel = computed({
  get: () => normalizedPage.value,
  set: value => {
    const next = Math.min(Math.max(1, Number(value || 1)), pageCount.value)
    if (next !== props.currentPage) emit('update:currentPage', next)
  },
})
const pageSizeModel = computed({
  get: () => normalizedPageSize.value,
  set: value => {
    const next = Number(value)
    if (!Number.isFinite(next) || next <= 0 || next === props.pageSize) return
    emit('update:pageSize', next)
    emit('update:currentPage', 1)
  },
})

function updateViewportWidth() {
  const el = scrollRef.value || viewportRef.value
  viewportWidth.value = Math.max(0, Math.round(el?.clientWidth || 0))
}

function itemKey(item, fallbackIndex) {
  return String(
    item?.canonical_rjcode ||
    item?.source_compare?.work_rjcode ||
    item?.rjcode ||
    fallbackIndex
  )
}

function viewModelForBonus(item, fallbackIndex) {
  const codes = bonusCodeList(item)
  const code = codes[0] || ''
  return {
    item,
    key: itemKey(item, fallbackIndex),
    code,
    selected: codes.some(value => props.selectedCodes?.has?.(value)),
    flashed: codes.some(value => props.flashedCodes?.has?.(value)),
    located: codes.some(value => props.locatedCodes?.has?.(value)),
  }
}

function bonusCode(item) {
  return String(item?.display_rjcode || item?.canonical_rjcode || item?.rjcode || '').trim()
}

function bonusTitle(item) {
  return bonusDisplayTitle(item)
}

function bonusCodeLabel(item) {
  const codes = bonusCodeList(item)
  if (!codes.length) return bonusCode(item)
  return codes.length > 1 ? `${codes[0]} 等 ${codes.length} 个` : codes[0]
}

function bonusReleaseLabel(item) {
  const value = String(item?.release_date || item?.date || item?.release_at || '').trim()
  if (!value) return ''
  const match = value.match(/(\d{4})[-/年](\d{1,2})(?:[-/月](\d{1,2}))?/)
  if (!match) return value
  const month = String(match[2]).padStart(2, '0')
  if (!match[3]) return `${match[1]}/${month}`
  return `${match[1]}/${month}/${String(match[3]).padStart(2, '0')}`
}

function bonusCoverUrl(item) {
  return String(item?.[props.imageField] || item?.image_url || item?.thumb_image_url || '').trim()
}

function buildDlsiteImageUrl(rjcode, variant = 'main') {
  const normalized = normalizeRjcode(rjcode)
  const match = normalized.match(/^RJ(\d{6}|\d{8})$/)
  if (!match) return ''
  const number = Number(match[1])
  const folderUpper = (Math.floor(number / 1000) + 1) * 1000
  const folder = match[1].length === 8
    ? `RJ${String(folderUpper).padStart(8, '0')}`
    : `RJ${String(folderUpper).padStart(6, '0')}`
  const suffix = variant === 'sam' ? '_img_sam.jpg' : '_img_main.jpg'
  return `https://img.dlsite.jp/modpub/images2/work/doujin/${folder}/${normalized}${suffix}`
}

function normalizeDlsiteMainImageUrl(value) {
  const url = String(value || '').trim()
  if (!url) return ''
  if (url.includes('/resize/images2/') && url.endsWith('_img_main_240x240.jpg')) {
    return url
      .replace('https://img.dlsite.jp/resize/images2/', 'https://img.dlsite.jp/modpub/images2/')
      .replace('_img_main_240x240.jpg', '_img_main.jpg')
  }
  if (url.includes('/modpub/images2/') && url.endsWith('_img_sam.jpg')) {
    return url.replace('_img_sam.jpg', '_img_main.jpg')
  }
  return url
}

function bonusMainCoverUrl(item) {
  const storedMain = normalizeDlsiteMainImageUrl(item?.image_url)
  if (storedMain) return storedMain
  const storedThumb = normalizeDlsiteMainImageUrl(item?.thumb_image_url || item?.[props.imageField])
  if (storedThumb) return storedThumb
  return buildDlsiteImageUrl(bonusCode(item), 'main')
}

function getRowItems(rowIndex) {
  return rowViewModels.value[rowIndex] || []
}

function isImageActive(key) {
  return activeImageKeys.value.has(String(key || ''))
}

function releaseImageSlot(key) {
  const normalized = String(key || '')
  const timer = imageLoadTimers.get(normalized)
  if (timer) {
    window.clearTimeout(timer)
    imageLoadTimers.delete(normalized)
  }
  if (loadingImageKeys.value.has(normalized)) {
    const next = new Set(loadingImageKeys.value)
    next.delete(normalized)
    loadingImageKeys.value = next
  }
  pumpImageQueue()
}

function markImageSettled(key) {
  releaseImageSlot(key)
}

function pumpImageQueue() {
  const activeVisible = new Set(visibleImageKeys.value.map(key => String(key || '')))
  const queued = queuedImageKeys.value.filter(key => activeVisible.has(key))
  const loading = new Set([...loadingImageKeys.value].filter(key => activeVisible.has(key)))
  const active = new Set([...activeImageKeys.value].filter(key => activeVisible.has(key)))
  while (queued.length && loading.size < MAX_ACTIVE_IMAGES) {
    const key = queued.shift()
    if (!key || active.has(key)) continue
    active.add(key)
    loading.add(key)
    const timer = window.setTimeout(() => releaseImageSlot(key), 1600)
    imageLoadTimers.set(key, timer)
  }
  queuedImageKeys.value = queued
  activeImageKeys.value = active
  loadingImageKeys.value = loading
}

function enqueueVisibleImages(keys = []) {
  const active = activeImageKeys.value
  const loading = loadingImageKeys.value
  const queued = [...queuedImageKeys.value]
  for (const rawKey of keys) {
    const key = String(rawKey || '')
    if (!key || active.has(key) || loading.has(key) || queued.includes(key)) continue
    queued.push(key)
  }
  queuedImageKeys.value = queued
  pumpImageQueue()
}

function triggerViewportMotion() {
  motionActive.value = false
  if (motionTimer) {
    window.clearTimeout(motionTimer)
    motionTimer = null
  }
  requestAnimationFrame(() => {
    motionActive.value = true
    motionTimer = window.setTimeout(() => {
      motionActive.value = false
      motionTimer = null
    }, 360)
  })
}

function scrollToTop(options = {}) {
  nextTick(() => {
    rowVirtualizer.value.scrollToOffset(0)
    if (options.measure !== false) rowVirtualizer.value.measure()
  })
}

watch(pageCount, (count) => {
  if (props.currentPage > count) emit('update:currentPage', count)
})

watch(
  () => [props.mode, props.pageSize, columnCount.value, totalItems.value].join(':'),
  () => {
    scrollToTop()
    triggerViewportMotion()
  },
)

watch(
  () => props.currentPage,
  () => {
    scrollToTop({ measure: !props.serverPaging })
    triggerViewportMotion()
  },
)

watch(virtualRowHeight, () => {
  nextTick(() => rowVirtualizer.value.measure())
})

watch(visibleImageKeys, keys => {
  enqueueVisibleImages(keys)
}, { immediate: true })

onMounted(() => {
  updateViewportWidth()
  triggerViewportMotion()
  resizeObserver = new ResizeObserver(() => {
    const previousWidth = viewportWidth.value
    updateViewportWidth()
    if (viewportWidth.value !== previousWidth) nextTick(() => rowVirtualizer.value.measure())
  })
  if (scrollRef.value) resizeObserver.observe(scrollRef.value)
})

onBeforeUnmount(() => {
  if (motionTimer) {
    window.clearTimeout(motionTimer)
    motionTimer = null
  }
  for (const timer of imageLoadTimers.values()) {
    window.clearTimeout(timer)
  }
  imageLoadTimers.clear()
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <section ref="viewportRef" class="circle-work-viewport" :class="[`is-${mode}`]">
    <div v-if="!totalItems" class="circle-work-empty">
      <slot name="empty">
        <span>{{ emptyText }}</span>
      </slot>
    </div>
    <template v-else>
      <div v-if="usePlainRender" class="circle-work-plain" :class="[`is-${mode}`]" :style="{ gridTemplateColumns }">
        <div
          v-for="viewModel in itemViewModels"
          :key="viewModel.key"
          class="circle-work-plain-cell"
          :class="[`is-${mode}`, {
            'is-motion-active': motionActive,
            'is-detail-active': hasActiveBonus(viewModel.bonuses),
            'is-left-edge': viewModel.index % Math.max(1, columnCount) === 0,
            'is-right-edge': viewModel.index % Math.max(1, columnCount) === Math.max(1, columnCount) - 1,
            'is-right-half': viewModel.index % Math.max(1, columnCount) >= Math.floor(Math.max(1, columnCount) / 2),
          }]"
          :style="{ '--cell-index': viewModel.index % Math.max(1, columnCount) }"
        >
          <div
            class="circle-work-bundle"
            :class="[`is-${mode}`, { 'has-bonus': viewModel.bonuses.length, 'is-detail-active': hasActiveBonus(viewModel.bonuses) }]"
            :style="bonusShelfStyle"
          >
            <WorkCard
              v-if="mode === 'card'"
              :item="viewModel.item"
              :card-index="0"
              :selected="viewModel.selected"
              :status-flash="viewModel.flashed"
              :locate-flash="viewModel.located"
              :completion-dimmed="shouldDimWorkCard(viewModel)"
              :corner-label="cornerLabel"
              :image-active="isImageActive(viewModel.key)"
              @select="emit('select', $event)"
              @preview="emit('preview', $event)"
              @reimport="emit('reimport', $event)"
              @image-settled="markImageSettled(viewModel.key)"
            />
            <div v-if="viewModel.bonuses.length && mode === 'card'" class="circle-bonus-shelf is-card">
              <button
                v-for="bonusViewModel in viewModel.bonusViewModels"
                :key="bonusViewModel.key"
                type="button"
                class="circle-bonus-gift"
                :class="{
                  'is-selected': bonusViewModel.selected,
                  'status-flash': bonusViewModel.flashed,
                  'locate-flash': bonusViewModel.located,
                  'is-dimmed': shouldDimBonusCard(bonusViewModel),
                }"
                :title="bonusTitle(bonusViewModel.item)"
                @click.stop="openBonusDetail(bonusViewModel.item)"
              >
                <span class="circle-bonus-gift-cover">
                  <img
                    v-if="isImageActive(bonusViewModel.key) && bonusCoverUrl(bonusViewModel.item)"
                    :src="bonusCoverUrl(bonusViewModel.item)"
                    loading="lazy"
                    decoding="async"
                    fetchpriority="low"
                    referrerpolicy="no-referrer"
                    @load="markImageSettled(bonusViewModel.key)"
                    @error="markImageSettled(bonusViewModel.key)"
                  />
                  <Gift v-else :size="16" />
                </span>
                <span class="circle-bonus-gift-badge">特典</span>
              </button>
            </div>
            <article
              v-if="mode === 'card' && activeBonusDetail && hasActiveBonus(viewModel.bonuses)"
              class="circle-bonus-detail-card is-card-inline"
              @click.stop
            >
              <button type="button" class="circle-bonus-detail-close" title="关闭" @click.stop="closeBonusDetail">×</button>
              <div class="circle-bonus-detail-media">
                <div class="circle-bonus-detail-cover">
                  <img
                    v-if="activeBonusDetailCover"
                    :src="activeBonusDetailCover"
                    loading="eager"
                    decoding="async"
                    referrerpolicy="no-referrer"
                  />
                  <Gift v-else :size="38" />
                  <span class="circle-bonus-detail-badge">特典</span>
                </div>
                <div class="circle-bonus-detail-tags">
                  <span class="circle-bonus-detail-tag" :class="bonusOwnedTagClass(activeBonusDetail)">{{ bonusOwnedLabel(activeBonusDetail) }}</span>
                  <span class="circle-bonus-detail-tag" :class="bonusDownloadTagClass(activeBonusDetail)">{{ bonusDownloadLabel(activeBonusDetail) }}</span>
                </div>
                <div class="circle-bonus-detail-linked">
                  <span>特典 · {{ bonusCodeLabel(activeBonusDetail) }}</span>
                  <span v-if="bonusReleaseLabel(activeBonusDetail)" class="circle-bonus-detail-release">
                    <Calendar :size="11" />{{ bonusReleaseLabel(activeBonusDetail) }}
                  </span>
                </div>
              </div>
              <div class="circle-bonus-detail-body">
                <h3 class="circle-bonus-detail-title">{{ bonusTitle(activeBonusDetail) }}</h3>
                <div class="circle-bonus-detail-cv" :class="{ 'is-empty': !bonusCvLabel(activeBonusDetail) }">{{ bonusCvLabel(activeBonusDetail) }}</div>
                <div v-if="hasLocalDownloadReadyBonus(activeBonusDetail) || canDownloadBonus(activeBonusDetail)" class="circle-bonus-detail-actions">
                  <button
                    v-if="hasLocalDownloadReadyBonus(activeBonusDetail)"
                    type="button"
                    class="circle-bonus-detail-action import"
                    @click.stop="handleBonusAction(activeBonusDetail)"
                  >
                    入库
                  </button>
                  <button
                    v-if="canDownloadBonus(activeBonusDetail)"
                    type="button"
                    class="circle-bonus-detail-action preview"
                    @click.stop="previewBonus(activeBonusDetail)"
                  >
                    预览
                  </button>
                </div>
              </div>
            </article>
            <template v-if="mode === 'list'">
              <WorkListRow
                :item="viewModel.item"
                :row-index="0"
                :selected="viewModel.selected"
                :status-flash="viewModel.flashed"
                :locate-flash="viewModel.located"
                :image-field="imageField"
                :corner-label="cornerLabel"
                :image-active="isImageActive(viewModel.key)"
                @select="forwardRowSelect($event)"
                @preview="forwardRowPreview($event, viewModel.item)"
                @reimport="forwardRowReimport($event)"
                @image-settled="markImageSettled(viewModel.key)"
              />
              <div v-if="viewModel.bonuses.length" class="circle-bonus-shelf is-list">
                <div
                  v-for="(bonus, bonusIndex) in viewModel.bonuses"
                  :key="itemKey(bonus, `${viewModel.key}:bonus:${bonusIndex}`)"
                  role="button"
                  tabindex="0"
                  class="circle-bonus-gift is-row"
                  :class="{
                    'is-selected': viewModelForBonus(bonus, `${viewModel.key}:bonus:${bonusIndex}`).selected,
                    'status-flash': viewModelForBonus(bonus, `${viewModel.key}:bonus:${bonusIndex}`).flashed,
                    'locate-flash': viewModelForBonus(bonus, `${viewModel.key}:bonus:${bonusIndex}`).located,
                  }"
                  @click.stop="openBonusDetail(bonus)"
                  @keydown.enter.stop.prevent="openBonusDetail(bonus)"
                  @keydown.space.stop.prevent="openBonusDetail(bonus)"
                >
                  <span class="circle-bonus-gift-cover">
                    <img
                      v-if="isImageActive(itemKey(bonus, `${viewModel.key}:bonus:${bonusIndex}`)) && bonusCoverUrl(bonus)"
                      :src="bonusCoverUrl(bonus)"
                      loading="lazy"
                      decoding="async"
                      fetchpriority="low"
                      referrerpolicy="no-referrer"
                      @load="markImageSettled(itemKey(bonus, `${viewModel.key}:bonus:${bonusIndex}`))"
                      @error="markImageSettled(itemKey(bonus, `${viewModel.key}:bonus:${bonusIndex}`))"
                    />
                    <Gift v-else :size="15" />
                  </span>
                  <span class="circle-bonus-gift-main">
                    <span class="circle-bonus-gift-kicker"><Gift :size="10" />特典</span>
                    <span class="circle-bonus-gift-title">{{ bonusTitle(bonus) }}</span>
                    <span class="circle-bonus-gift-code">{{ bonusCodeLabel(bonus) }}</span>
                  </span>
                  <span class="circle-bonus-gift-actions">
                    <button
                      v-if="hasLocalDownloadReadyBonus(bonus)"
                      type="button"
                      class="circle-bonus-mini-action import"
                      title="入库"
                      @click.stop="handleBonusAction(bonus)"
                    >
                      <PackageCheck :size="12" />
                    </button>
                    <button
                      v-else-if="canDownloadBonus(bonus)"
                      type="button"
                      class="circle-bonus-mini-action download"
                      title="下载"
                      @click.stop="handleBonusAction(bonus)"
                    >
                      下载
                    </button>
                  </span>
                </div>
              </div>
              <article
                v-if="activeBonusDetail && hasActiveBonus(viewModel.bonuses)"
                class="circle-bonus-detail-card is-list-inline"
                @click.stop
              >
                <button type="button" class="circle-bonus-detail-close" title="关闭" @click.stop="closeBonusDetail">×</button>
                <div class="circle-bonus-detail-media">
                  <div class="circle-bonus-detail-cover">
                    <img
                      v-if="activeBonusDetailCover"
                      :src="activeBonusDetailCover"
                      loading="eager"
                      decoding="async"
                      referrerpolicy="no-referrer"
                    />
                    <Gift v-else :size="38" />
                    <span class="circle-bonus-detail-badge">特典</span>
                  </div>
                  <div class="circle-bonus-detail-tags">
                    <span class="circle-bonus-detail-tag" :class="bonusOwnedTagClass(activeBonusDetail)">{{ bonusOwnedLabel(activeBonusDetail) }}</span>
                    <span class="circle-bonus-detail-tag" :class="bonusDownloadTagClass(activeBonusDetail)">{{ bonusDownloadLabel(activeBonusDetail) }}</span>
                  </div>
                  <div class="circle-bonus-detail-linked">
                    <span>特典 · {{ bonusCodeLabel(activeBonusDetail) }}</span>
                    <span v-if="bonusReleaseLabel(activeBonusDetail)" class="circle-bonus-detail-release">
                      <Calendar :size="11" />{{ bonusReleaseLabel(activeBonusDetail) }}
                    </span>
                  </div>
                </div>
                <div class="circle-bonus-detail-body">
                  <h3 class="circle-bonus-detail-title">{{ bonusTitle(activeBonusDetail) }}</h3>
                  <div class="circle-bonus-detail-cv" :class="{ 'is-empty': !bonusCvLabel(activeBonusDetail) }">{{ bonusCvLabel(activeBonusDetail) }}</div>
                  <div v-if="hasLocalDownloadReadyBonus(activeBonusDetail) || canDownloadBonus(activeBonusDetail)" class="circle-bonus-detail-actions">
                    <button
                      v-if="hasLocalDownloadReadyBonus(activeBonusDetail)"
                      type="button"
                      class="circle-bonus-detail-action import"
                      @click.stop="handleBonusAction(activeBonusDetail)"
                    >
                      入库
                    </button>
                    <button
                      v-if="canDownloadBonus(activeBonusDetail)"
                      type="button"
                      class="circle-bonus-detail-action preview"
                      @click.stop="previewBonus(activeBonusDetail)"
                    >
                      预览
                    </button>
                  </div>
                </div>
              </article>
            </template>
          </div>
        </div>
      </div>

      <div v-else ref="scrollRef" class="circle-work-scroll">
        <div class="circle-work-virtual-canvas" :style="virtualCanvasStyle">
          <div
            v-for="virtualRow in virtualRows"
            :key="virtualRow.key"
            class="circle-work-virtual-row"
            :class="[`is-${mode}`, { 'is-detail-active': getRowItems(virtualRow.index).some(cell => hasActiveBonus(cell.bonuses)) }]"
            :style="{
              height: `${virtualRow.size}px`,
              transform: `translateY(${virtualRow.start}px)`,
              gridTemplateColumns,
              gap: `${gridGap}px`,
            }"
          >
            <div
              v-for="cell in getRowItems(virtualRow.index)"
              :key="cell.key"
              class="circle-work-virtual-cell"
              :class="[`is-${mode}`, {
                'is-motion-active': motionActive,
                'is-detail-active': hasActiveBonus(cell.bonuses),
                'is-left-edge': cell.columnIndex === 0,
                'is-right-edge': cell.columnIndex === Math.max(1, columnCount) - 1,
                'is-right-half': cell.columnIndex >= Math.floor(Math.max(1, columnCount) / 2),
              }]"
              :style="{ '--cell-index': cell.columnIndex }"
            >
              <div
                class="circle-work-bundle"
                :class="[`is-${mode}`, { 'has-bonus': cell.bonuses.length, 'is-detail-active': hasActiveBonus(cell.bonuses) }]"
                :style="bonusShelfStyle"
              >
                <WorkCard
                  v-if="mode === 'card'"
                  :item="cell.item"
                  :card-index="0"
                  :selected="cell.selected"
                  :status-flash="cell.flashed"
                  :locate-flash="cell.located"
                  :completion-dimmed="shouldDimWorkCard(cell)"
                  :corner-label="cornerLabel"
                  :image-active="isImageActive(cell.key)"
                  @select="emit('select', $event)"
                  @preview="emit('preview', $event)"
                  @reimport="emit('reimport', $event)"
                  @image-settled="markImageSettled(cell.key)"
                />
                <div v-if="cell.bonuses.length && mode === 'card'" class="circle-bonus-shelf is-card">
                  <button
                    v-for="bonusViewModel in cell.bonusViewModels"
                    :key="bonusViewModel.key"
                    type="button"
                    class="circle-bonus-gift"
                    :class="{
                      'is-selected': bonusViewModel.selected,
                      'status-flash': bonusViewModel.flashed,
                      'locate-flash': bonusViewModel.located,
                      'is-dimmed': shouldDimBonusCard(bonusViewModel),
                    }"
                    :title="bonusTitle(bonusViewModel.item)"
                    @click.stop="openBonusDetail(bonusViewModel.item)"
                  >
                    <span class="circle-bonus-gift-cover">
                      <img
                        v-if="isImageActive(bonusViewModel.key) && bonusCoverUrl(bonusViewModel.item)"
                        :src="bonusCoverUrl(bonusViewModel.item)"
                        loading="lazy"
                        decoding="async"
                        fetchpriority="low"
                        referrerpolicy="no-referrer"
                        @load="markImageSettled(bonusViewModel.key)"
                        @error="markImageSettled(bonusViewModel.key)"
                      />
                      <Gift v-else :size="16" />
                    </span>
                    <span class="circle-bonus-gift-badge">特典</span>
                  </button>
                </div>
                <article
                  v-if="mode === 'card' && activeBonusDetail && hasActiveBonus(cell.bonuses)"
                  class="circle-bonus-detail-card is-card-inline"
                  @click.stop
                >
                  <button type="button" class="circle-bonus-detail-close" title="关闭" @click.stop="closeBonusDetail">×</button>
                  <div class="circle-bonus-detail-media">
                    <div class="circle-bonus-detail-cover">
                      <img
                        v-if="activeBonusDetailCover"
                        :src="activeBonusDetailCover"
                        loading="eager"
                        decoding="async"
                        referrerpolicy="no-referrer"
                      />
                      <Gift v-else :size="38" />
                      <span class="circle-bonus-detail-badge">特典</span>
                    </div>
                    <div class="circle-bonus-detail-tags">
                      <span class="circle-bonus-detail-tag" :class="bonusOwnedTagClass(activeBonusDetail)">{{ bonusOwnedLabel(activeBonusDetail) }}</span>
                      <span class="circle-bonus-detail-tag" :class="bonusDownloadTagClass(activeBonusDetail)">{{ bonusDownloadLabel(activeBonusDetail) }}</span>
                    </div>
                    <div class="circle-bonus-detail-linked">
                      <span>特典 · {{ bonusCodeLabel(activeBonusDetail) }}</span>
                      <span v-if="bonusReleaseLabel(activeBonusDetail)" class="circle-bonus-detail-release">
                        <Calendar :size="11" />{{ bonusReleaseLabel(activeBonusDetail) }}
                      </span>
                    </div>
                  </div>
                  <div class="circle-bonus-detail-body">
                    <h3 class="circle-bonus-detail-title">{{ bonusTitle(activeBonusDetail) }}</h3>
                    <div class="circle-bonus-detail-cv" :class="{ 'is-empty': !bonusCvLabel(activeBonusDetail) }">{{ bonusCvLabel(activeBonusDetail) }}</div>
                    <div v-if="hasLocalDownloadReadyBonus(activeBonusDetail) || canDownloadBonus(activeBonusDetail)" class="circle-bonus-detail-actions">
                      <button
                        v-if="hasLocalDownloadReadyBonus(activeBonusDetail)"
                        type="button"
                        class="circle-bonus-detail-action import"
                        @click.stop="handleBonusAction(activeBonusDetail)"
                      >
                        入库
                      </button>
                      <button
                        v-if="canDownloadBonus(activeBonusDetail)"
                        type="button"
                        class="circle-bonus-detail-action preview"
                        @click.stop="previewBonus(activeBonusDetail)"
                      >
                        预览
                      </button>
                    </div>
                  </div>
                </article>
                <template v-if="mode === 'list'">
                  <WorkListRow
                    :item="cell.item"
                    :row-index="0"
                    :selected="cell.selected"
                    :status-flash="cell.flashed"
                    :locate-flash="cell.located"
                    :image-field="imageField"
                    :corner-label="cornerLabel"
                    :image-active="isImageActive(cell.key)"
                    @select="forwardRowSelect($event)"
                    @preview="forwardRowPreview($event, cell.item)"
                    @reimport="forwardRowReimport($event)"
                    @image-settled="markImageSettled(cell.key)"
                  />
                  <div v-if="cell.bonuses.length" class="circle-bonus-shelf is-list">
                    <div
                      v-for="(bonus, bonusIndex) in cell.bonuses"
                      :key="itemKey(bonus, `${cell.key}:bonus:${bonusIndex}`)"
                      role="button"
                      tabindex="0"
                      class="circle-bonus-gift is-row"
                      :class="{
                        'is-selected': viewModelForBonus(bonus, `${cell.key}:bonus:${bonusIndex}`).selected,
                        'status-flash': viewModelForBonus(bonus, `${cell.key}:bonus:${bonusIndex}`).flashed,
                        'locate-flash': viewModelForBonus(bonus, `${cell.key}:bonus:${bonusIndex}`).located,
                      }"
                      @click.stop="openBonusDetail(bonus)"
                      @keydown.enter.stop.prevent="openBonusDetail(bonus)"
                      @keydown.space.stop.prevent="openBonusDetail(bonus)"
                    >
                      <span class="circle-bonus-gift-cover">
                        <img
                          v-if="isImageActive(itemKey(bonus, `${cell.key}:bonus:${bonusIndex}`)) && bonusCoverUrl(bonus)"
                          :src="bonusCoverUrl(bonus)"
                          loading="lazy"
                          decoding="async"
                          fetchpriority="low"
                          referrerpolicy="no-referrer"
                          @load="markImageSettled(itemKey(bonus, `${cell.key}:bonus:${bonusIndex}`))"
                          @error="markImageSettled(itemKey(bonus, `${cell.key}:bonus:${bonusIndex}`))"
                        />
                        <Gift v-else :size="15" />
                      </span>
                      <span class="circle-bonus-gift-main">
                        <span class="circle-bonus-gift-kicker"><Gift :size="10" />特典</span>
                        <span class="circle-bonus-gift-title">{{ bonusTitle(bonus) }}</span>
                        <span class="circle-bonus-gift-code">{{ bonusCodeLabel(bonus) }}</span>
                      </span>
                      <span class="circle-bonus-gift-actions">
                        <button
                          v-if="hasLocalDownloadReadyBonus(bonus)"
                          type="button"
                          class="circle-bonus-mini-action import"
                          title="入库"
                          @click.stop="handleBonusAction(bonus)"
                        >
                          <PackageCheck :size="12" />
                        </button>
                        <button
                          v-else-if="canDownloadBonus(bonus)"
                          type="button"
                          class="circle-bonus-mini-action download"
                          title="下载"
                          @click.stop="handleBonusAction(bonus)"
                        >
                          下载
                        </button>
                      </span>
                    </div>
                  </div>
                  <article
                    v-if="activeBonusDetail && hasActiveBonus(cell.bonuses)"
                    class="circle-bonus-detail-card is-list-inline"
                    @click.stop
                  >
                    <button type="button" class="circle-bonus-detail-close" title="关闭" @click.stop="closeBonusDetail">×</button>
                    <div class="circle-bonus-detail-media">
                      <div class="circle-bonus-detail-cover">
                        <img
                          v-if="activeBonusDetailCover"
                          :src="activeBonusDetailCover"
                          loading="eager"
                          decoding="async"
                          referrerpolicy="no-referrer"
                        />
                        <Gift v-else :size="38" />
                        <span class="circle-bonus-detail-badge">特典</span>
                      </div>
                      <div class="circle-bonus-detail-tags">
                        <span class="circle-bonus-detail-tag" :class="bonusOwnedTagClass(activeBonusDetail)">{{ bonusOwnedLabel(activeBonusDetail) }}</span>
                        <span class="circle-bonus-detail-tag" :class="bonusDownloadTagClass(activeBonusDetail)">{{ bonusDownloadLabel(activeBonusDetail) }}</span>
                      </div>
                      <div class="circle-bonus-detail-linked">
                        <span>特典 · {{ bonusCodeLabel(activeBonusDetail) }}</span>
                        <span v-if="bonusReleaseLabel(activeBonusDetail)" class="circle-bonus-detail-release">
                          <Calendar :size="11" />{{ bonusReleaseLabel(activeBonusDetail) }}
                        </span>
                      </div>
                    </div>
                    <div class="circle-bonus-detail-body">
                      <h3 class="circle-bonus-detail-title">{{ bonusTitle(activeBonusDetail) }}</h3>
                      <div class="circle-bonus-detail-cv" :class="{ 'is-empty': !bonusCvLabel(activeBonusDetail) }">{{ bonusCvLabel(activeBonusDetail) }}</div>
                      <div v-if="hasLocalDownloadReadyBonus(activeBonusDetail) || canDownloadBonus(activeBonusDetail)" class="circle-bonus-detail-actions">
                        <button
                          v-if="hasLocalDownloadReadyBonus(activeBonusDetail)"
                          type="button"
                          class="circle-bonus-detail-action import"
                          @click.stop="handleBonusAction(activeBonusDetail)"
                        >
                          入库
                        </button>
                        <button
                          v-if="canDownloadBonus(activeBonusDetail)"
                          type="button"
                          class="circle-bonus-detail-action preview"
                          @click.stop="previewBonus(activeBonusDetail)"
                        >
                          预览
                        </button>
                      </div>
                    </div>
                  </article>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="works-pager km-pagination-wrap">
        <el-pagination
          v-model:current-page="currentPageModel"
          v-model:page-size="pageSizeModel"
          :page-sizes="pageSizes"
          :total="totalItems"
          :aria-label="`${pagerLabel}分页`"
          layout="total, sizes, prev, pager, next, jumper"
          popper-class="km-pagination-size-popper"
          background
        />
      </div>
    </template>
  </section>
</template>

<style scoped>
.circle-work-viewport {
  position: relative;
  z-index: 0;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  gap: 10px;
}

.circle-work-scroll {
  flex: 1;
  min-height: 280px;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: none;
  -ms-overflow-style: none;
  contain: layout paint;
}

.circle-work-scroll::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

.circle-work-virtual-canvas {
  position: relative;
  width: 100%;
}

.circle-work-virtual-row {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  display: grid;
  box-sizing: border-box;
  z-index: 0;
}

.circle-work-virtual-row.is-detail-active {
  z-index: 30;
}

.circle-work-virtual-row.is-card {
  align-items: stretch;
}

.circle-work-virtual-row.is-list {
  display: block;
}

.circle-work-virtual-cell,
.circle-work-plain-cell {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: visible;
  z-index: 0;
}

.circle-work-virtual-cell.is-detail-active,
.circle-work-plain-cell.is-detail-active {
  z-index: 40;
}

.circle-work-virtual-cell.is-motion-active,
.circle-work-plain-cell.is-motion-active {
  animation: viewportCellEntrance 260ms cubic-bezier(.22, 1, .36, 1) both;
  animation-delay: calc(var(--cell-index, 0) * 24ms);
}

.circle-work-virtual-cell.is-card {
  height: calc(100% - 10px);
}

.circle-work-virtual-cell.is-list {
  height: calc(100% - 6px);
}

.circle-work-plain {
  flex: 0 0 auto;
  min-height: 0;
}

.circle-work-plain.is-card {
  display: grid;
  gap: 8px;
  align-items: stretch;
}

.circle-work-plain.is-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.circle-work-plain-cell.is-card {
  min-height: 278px;
}

.circle-work-bundle {
  position: relative;
  min-width: 0;
  overflow: visible;
  z-index: 0;
}

.circle-work-bundle.is-detail-active {
  z-index: 50;
}

.circle-work-bundle.is-card {
  height: 100%;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 0;
}

.circle-work-bundle.is-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.circle-bonus-shelf {
  position: relative;
  min-width: 0;
}

.circle-bonus-shelf.is-card {
  position: absolute;
  top: var(--bonus-shelf-top, 72px);
  right: 9px;
  z-index: 8;
  width: min(39%, 88px);
  display: grid;
  gap: 5px;
  padding: 0;
  pointer-events: none;
}

.circle-bonus-shelf.is-list {
  margin: -3px 0 4px 50px;
  display: grid;
  gap: 4px;
}

.circle-bonus-gift {
  min-width: 0;
  position: relative;
  display: block;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--circle-tag-primary, #3478f6) 34%, transparent);
  border-radius: 12px;
  background: color-mix(in srgb, var(--circle-surface, #ffffff) 88%, transparent);
  color: var(--circle-text, #334155);
  cursor: pointer;
  overflow: hidden;
  aspect-ratio: 4 / 3;
  box-shadow:
    0 10px 24px color-mix(in srgb, var(--circle-shadow, rgba(31, 53, 84, 0.20)) 72%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.42);
  pointer-events: auto;
  transition:
    transform .2s cubic-bezier(.34, 1.56, .64, 1),
    border-color .18s ease,
    box-shadow .18s ease,
    background .18s ease;
}

.circle-bonus-gift:hover {
  transform: translateY(-2px) scale(1.035);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 52%, transparent);
  box-shadow:
    0 16px 28px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 18%, transparent),
    0 8px 18px color-mix(in srgb, var(--circle-shadow, rgba(31, 53, 84, 0.20)) 52%, transparent);
}

.circle-bonus-shelf.is-card .circle-bonus-gift {
  overflow: visible;
  isolation: isolate;
  border-color: color-mix(in srgb, #f6d365 26%, transparent);
  background: transparent;
  box-shadow:
    0 0 7px rgba(251, 191, 36, 0.20),
    0 0 12px rgba(251, 191, 36, 0.08),
    0 10px 24px color-mix(in srgb, var(--circle-shadow, rgba(31, 53, 84, 0.20)) 60%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.42);
  animation: bonusGiftCardBreath 2.8s ease-in-out infinite;
}

.circle-bonus-shelf.is-card .circle-bonus-gift::before {
  content: '';
  position: absolute;
  inset: -2px;
  z-index: -1;
  border-radius: 14px;
  pointer-events: none;
  border: 0;
  background:
    radial-gradient(ellipse at 78% 8%, rgba(255, 236, 153, 0.42), rgba(250, 204, 21, 0.22) 22%, transparent 54%),
    radial-gradient(ellipse at 16% 92%, rgba(250, 204, 21, 0.26), transparent 58%),
    radial-gradient(circle at 54% 18%, rgba(255, 255, 255, 0.30), transparent 13%);
  background-size: 120% 120%, 120% 120%, 100% 100%;
  box-shadow: 0 0 10px rgba(250, 204, 21, 0.18);
  opacity: 0.62;
  filter: blur(0.5px);
  animation: bonusGiftRareHalo 2.8s ease-in-out infinite;
}

.circle-bonus-shelf.is-card .circle-bonus-gift::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 2;
  border-radius: inherit;
  pointer-events: none;
  background:
    radial-gradient(circle at 82% 18%, rgba(255, 244, 179, 0.28), transparent 22%),
    linear-gradient(115deg, transparent 0%, rgba(255, 236, 153, 0.00) 35%, rgba(255, 236, 153, 0.28) 49%, rgba(255, 236, 153, 0.00) 63%, transparent 100%);
  opacity: 0.62;
  animation: bonusGiftSoftGleam 2.9s ease-in-out infinite;
}

.circle-bonus-shelf.is-card .circle-bonus-gift:hover {
  border-color: color-mix(in srgb, #facc15 42%, transparent);
  animation-play-state: paused;
  box-shadow:
    0 0 10px rgba(251, 191, 36, 0.28),
    0 0 16px rgba(251, 191, 36, 0.12),
    0 14px 26px color-mix(in srgb, var(--circle-shadow, rgba(31, 53, 84, 0.20)) 55%, transparent);
}

.circle-bonus-shelf.is-card .circle-bonus-gift.is-dimmed {
  filter: grayscale(1) saturate(0.28) brightness(0.86) contrast(1.04);
  opacity: 1;
  border-color: color-mix(in srgb, var(--circle-border, #94a3b8) 44%, transparent);
  box-shadow:
    0 6px 14px rgba(15, 23, 42, 0.16),
    inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.circle-bonus-shelf.is-card .circle-bonus-gift.is-dimmed::before {
  opacity: 0.16;
  filter: grayscale(1) blur(0.5px);
}

.circle-bonus-shelf.is-card .circle-bonus-gift.is-dimmed::after {
  opacity: 0.18;
  filter: grayscale(1);
}

.circle-bonus-shelf.is-card .circle-bonus-gift.is-dimmed:hover {
  filter: grayscale(1) saturate(0.34) brightness(0.9) contrast(1.04);
  box-shadow:
    0 8px 16px rgba(15, 23, 42, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.24);
}

.circle-bonus-gift:active {
  transform: scale(0.985);
}

.circle-bonus-gift.is-row {
  width: 100%;
  height: 40px;
  aspect-ratio: auto;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  grid-template-rows: none;
  align-items: center;
  padding: 4px 5px;
  border-radius: 7px;
  box-shadow: none;
}

.circle-bonus-gift.is-selected {
  border-color: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 46%, transparent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 10%, transparent);
}

.circle-bonus-shelf.is-card .circle-bonus-gift.is-selected {
  border-color: color-mix(in srgb, #facc15 46%, var(--circle-tag-primary, #3478f6) 10%);
  box-shadow:
    0 0 16px rgba(251, 191, 36, 0.32),
    0 0 26px rgba(251, 191, 36, 0.16);
}

.circle-bonus-gift.status-flash {
  animation: bonusGiftFlash .5s ease;
}

.circle-bonus-gift.locate-flash {
  animation: bonusGiftLocateFlash 2.4s cubic-bezier(.22, 1, .36, 1);
}

.circle-bonus-gift-cover {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: inherit;
  border: 0;
  background: color-mix(in srgb, var(--circle-surface-soft, #f8fafc) 92%, transparent);
  color: var(--circle-text-muted, #6d8bb5);
}

.circle-bonus-gift.is-row .circle-bonus-gift-cover {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, var(--circle-border, #e2e8f0) 90%, transparent);
}

.circle-bonus-shelf.is-card .circle-bonus-gift-cover {
  position: absolute;
  inset: 0;
  width: auto;
  height: auto;
  background: transparent;
}

.circle-bonus-gift-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.circle-bonus-gift-badge {
  position: absolute;
  right: 5px;
  bottom: 5px;
  z-index: 3;
  max-width: calc(100% - 10px);
  padding: 0;
  border-radius: 999px;
  background: transparent;
  color: rgba(255, 255, 255, 0.98);
  font-size: 9px;
  font-weight: 900;
  line-height: 1.15;
  letter-spacing: 0;
  -webkit-text-stroke: 0.35px rgba(15, 23, 42, 0.72);
  text-shadow:
    0 1px 2px rgba(15, 23, 42, 0.88),
    0 0 6px rgba(15, 23, 42, 0.45);
  box-shadow: none;
}

.circle-bonus-gift-main {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: auto auto;
  align-items: start;
  gap: 3px 5px;
}

.circle-bonus-gift.is-row .circle-bonus-gift-main {
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: none;
  align-items: center;
}

.circle-bonus-gift-kicker {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  width: fit-content;
  max-width: 100%;
  padding: 0 4px;
  border-radius: 5px;
  background: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 8%, transparent);
  color: var(--circle-tag-primary, #3478f6);
  font-size: 9px;
  font-weight: 900;
  line-height: 15px;
  white-space: nowrap;
}

.circle-bonus-gift-title {
  grid-column: 1 / -1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--circle-text-strong, #1f3554);
  font-size: 10px;
  font-weight: 800;
  line-height: 16px;
}

.circle-bonus-gift.is-row .circle-bonus-gift-title {
  grid-column: auto;
}

.circle-bonus-gift-code {
  display: none;
  color: var(--circle-text-muted, #6d8bb5);
  font-size: 9px;
  font-weight: 700;
  line-height: 12px;
}

.circle-bonus-gift-actions {
  grid-column: 2;
  grid-row: 1;
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}

.circle-bonus-gift.is-row .circle-bonus-gift-actions {
  grid-column: auto;
  grid-row: auto;
}

.circle-bonus-mini-action {
  min-width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 5px;
  border: 1px solid color-mix(in srgb, var(--circle-border, #e2e8f0) 82%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--circle-surface-soft, #f8fafc) 88%, transparent);
  color: var(--circle-text-muted, #6d8bb5);
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  transition:
    transform .2s cubic-bezier(.34, 1.56, .64, 1),
    border-color .18s ease,
    background .18s ease;
}

.circle-bonus-mini-action:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 30%, transparent);
  background: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 8%, transparent);
  color: var(--circle-tag-primary, #3478f6);
}

.circle-bonus-mini-action:active {
  transform: scale(0.96);
}

.circle-bonus-mini-action.import {
  border-color: color-mix(in srgb, var(--circle-tag-success, #16a34a) 24%, transparent);
  background: color-mix(in srgb, var(--circle-tag-success, #16a34a) 8%, transparent);
  color: var(--circle-tag-success, #16a34a);
}

.circle-bonus-mini-action.download {
  border-color: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 24%, transparent);
  background: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 8%, transparent);
  color: var(--circle-tag-primary, #3478f6);
}

.circle-bonus-detail-card {
  position: absolute;
  z-index: 60;
  top: 10px;
  left: 10px;
  width: min(360px, calc(100% + 210px), calc(100vw - 42px));
  display: grid;
  grid-template-columns: minmax(132px, 1.06fr) minmax(118px, .94fr);
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--circle-border, #e2e8f0) 72%, transparent);
  border-radius: 14px;
  background: color-mix(in srgb, var(--circle-surface, #ffffff) 96%, transparent);
  color: var(--circle-text, #334155);
  box-shadow:
    0 18px 46px rgba(15, 23, 42, 0.22),
    0 5px 18px rgba(15, 23, 42, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.50);
  transform-origin: top left;
  animation: bonusDetailIn .18s cubic-bezier(.22, 1, .36, 1) both;
}

.circle-work-virtual-cell.is-right-half .circle-bonus-detail-card.is-card-inline,
.circle-work-plain-cell.is-right-half .circle-bonus-detail-card.is-card-inline {
  right: 10px;
  left: auto;
  transform-origin: top right;
}

.circle-bonus-detail-card.is-list-inline {
  position: relative;
  top: auto;
  right: auto;
  left: auto;
  width: min(520px, calc(100% - 50px));
  margin: 0 0 8px 50px;
  grid-template-columns: 180px minmax(0, 1fr);
  transform-origin: top left;
}

.circle-bonus-detail-close {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(148, 163, 184, 0.34);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.62);
  color: #fff;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition: all .2s cubic-bezier(.34, 1.56, .64, 1);
}

.circle-bonus-detail-close:hover {
  transform: translateY(-1px) scale(1.04);
}

.circle-bonus-detail-media {
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--circle-surface-soft, #f8fafc) 94%, transparent);
}

.circle-bonus-detail-cover {
  position: relative;
  aspect-ratio: 4 / 3;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: color-mix(in srgb, var(--circle-surface-soft, #f8fafc) 94%, transparent);
  color: var(--circle-text-muted, #6d8bb5);
}

.circle-bonus-detail-cover img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.circle-bonus-detail-badge {
  position: absolute;
  left: 9px;
  bottom: 9px;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.70);
  color: #fff;
  font-size: 11px;
  font-weight: 900;
}

.circle-bonus-detail-tags {
  min-height: 32px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 10px 5px;
}

.circle-bonus-detail-tag {
  height: 19px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 0 7px;
  border: 1px solid var(--circle-chip-border, rgba(226, 232, 240, 0.86));
  border-radius: 5px;
  background: var(--circle-chip-bg, rgba(248, 250, 252, 0.72));
  color: var(--circle-text-subtle, #8a97a8);
  font-size: 9px;
  font-weight: 750;
  line-height: 1;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.circle-bonus-detail-tag.is-primary {
  border-color: color-mix(in srgb, var(--circle-tag-primary, #416fae) 22%, transparent);
  background: color-mix(in srgb, var(--circle-tag-primary, #416fae) 8%, transparent);
  color: var(--circle-tag-primary, #416fae);
}

.circle-bonus-detail-tag.is-success {
  border-color: color-mix(in srgb, var(--circle-tag-success, #247348) 22%, transparent);
  background: color-mix(in srgb, var(--circle-tag-success, #247348) 8%, transparent);
  color: var(--circle-tag-success, #247348);
}

.circle-bonus-detail-tag.is-danger {
  border-color: color-mix(in srgb, var(--circle-tag-danger, #c2412d) 22%, transparent);
  background: color-mix(in srgb, var(--circle-tag-danger, #c2412d) 8%, transparent);
  color: var(--circle-tag-danger, #c2412d);
}

.circle-bonus-detail-tag.is-disabled {
  border-color: var(--circle-chip-border, rgba(226, 232, 240, 0.86));
  background: var(--circle-chip-bg, rgba(248, 250, 252, 0.72));
  color: var(--circle-text-subtle, #8a97a8);
}

.circle-bonus-detail-linked {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  padding: 0 10px 10px;
  color: var(--circle-text-muted, #6d8bb5);
  font-size: 10px;
  font-weight: 800;
  line-height: 1.2;
}

.circle-bonus-detail-linked > span:first-child {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.circle-bonus-detail-release {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-width: 0;
  white-space: nowrap;
}

.circle-bonus-detail-body {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 25px 14px 13px;
}

.circle-bonus-detail-title {
  margin: 0;
  color: var(--circle-text-strong, #1f3554);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.38;
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
}

.circle-bonus-detail-cv {
  height: 14px;
  color: #0ea5e9;
  -webkit-text-fill-color: currentColor;
  font-size: 9px;
  font-weight: 500;
  line-height: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.circle-bonus-detail-cv.is-empty {
  visibility: hidden;
}

.circle-bonus-detail-actions {
  display: flex;
  align-items: center;
  justify-content: stretch;
  gap: 6px;
  width: 100%;
  margin-top: auto;
}

.circle-bonus-detail-action {
  flex: 1;
  min-width: 0;
  height: 30px;
  padding: 0 10px;
  border: 1px solid color-mix(in srgb, var(--circle-text-muted, #64748b) 26%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--circle-surface, #ffffff) 58%, transparent);
  color: var(--circle-text, #334155);
  font-size: 12px;
  font-weight: 900;
  cursor: pointer;
  transition: all .2s cubic-bezier(.34, 1.56, .64, 1);
}

.circle-bonus-detail-action:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: color-mix(in srgb, var(--circle-text, #334155) 32%, transparent);
  background: color-mix(in srgb, var(--circle-text, #334155) 7%, var(--circle-surface, #ffffff));
  color: var(--circle-text-strong, #1f2937);
}

.circle-bonus-detail-action:active {
  transform: scale(0.96);
}

.circle-bonus-detail-action.import {
  border-color: color-mix(in srgb, var(--circle-success, #247348) 24%, transparent);
  background: color-mix(in srgb, var(--circle-success, #247348) 7%, var(--circle-surface, #ffffff));
  color: var(--circle-success, #247348);
}

.circle-bonus-detail-action.import:hover {
  border-color: color-mix(in srgb, var(--circle-success, #16653d) 34%, transparent);
  background: color-mix(in srgb, var(--circle-success, #247348) 10%, var(--circle-surface, #ffffff));
  color: var(--circle-success, #16653d);
}

@keyframes bonusGiftFlash {
  0%, 100% { background: color-mix(in srgb, var(--circle-surface, #ffffff) 86%, transparent); }
  45% {
    background: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 8%, var(--circle-surface, #ffffff));
    border-color: color-mix(in srgb, var(--circle-tag-primary, #3478f6) 40%, transparent);
  }
}

@keyframes bonusGiftLocateFlash {
  0% {
    transform: translateX(-3px);
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--circle-tag-primary, #3478f6) 24%, transparent);
  }
  28% {
    transform: translateX(0);
    box-shadow:
      0 0 0 5px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 12%, transparent),
      0 10px 20px color-mix(in srgb, var(--circle-tag-primary, #3478f6) 12%, transparent);
  }
  100% {
    transform: translateX(0);
  }
}

@keyframes bonusDetailIn {
  from {
    opacity: 0;
    transform: translateY(-4px) scale(0.96);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes bonusGiftSoftGleam {
  0%,
  100% {
    opacity: 0.36;
    transform: translateX(-16%) rotate(-1deg);
  }
  50% {
    opacity: 0.84;
    transform: translateX(16%) rotate(1deg);
  }
}

@keyframes bonusGiftCardBreath {
  0%,
  100% {
    border-color: color-mix(in srgb, #f6d365 22%, transparent);
    box-shadow:
      0 0 6px rgba(251, 191, 36, 0.16),
      0 0 10px rgba(251, 191, 36, 0.06),
      0 10px 24px color-mix(in srgb, var(--circle-shadow, rgba(31, 53, 84, 0.20)) 60%, transparent),
      inset 0 1px 0 rgba(255, 255, 255, 0.42);
  }
  48% {
    border-color: color-mix(in srgb, #facc15 46%, transparent);
    box-shadow:
      0 0 11px rgba(251, 191, 36, 0.32),
      0 0 18px rgba(251, 191, 36, 0.14),
      0 10px 24px color-mix(in srgb, var(--circle-shadow, rgba(31, 53, 84, 0.20)) 60%, transparent),
      inset 0 1px 0 rgba(255, 255, 255, 0.52);
  }
}

@keyframes bonusGiftRareHalo {
  0%,
  100% {
    opacity: 0.50;
    transform: scale(0.998);
    background-position:
      50% 50%,
      50% 50%,
      45% 18%;
  }
  50% {
    opacity: 0.82;
    transform: scale(1.004);
    background-position:
      54% 46%,
      46% 54%,
      62% 14%;
  }
}

:global(html.kikoerumanager-dark .circle-bonus-shelf.is-card),
:global(body.kikoerumanager-dark .circle-bonus-shelf.is-card),
:global(html.kikoerumanager-dark .circle-bonus-shelf.is-list),
:global(body.kikoerumanager-dark .circle-bonus-shelf.is-list) {
  border-color: rgba(148, 163, 184, 0.20);
  background: transparent;
}

:global(html.kikoerumanager-dark .circle-bonus-gift-kicker),
:global(body.kikoerumanager-dark .circle-bonus-gift-kicker) {
  background: rgba(37, 99, 235, 0.20);
  color: #93c5fd;
}

:global(html.kikoerumanager-dark .circle-bonus-gift),
:global(body.kikoerumanager-dark .circle-bonus-gift) {
  border-color: rgba(148, 163, 184, 0.20);
  background: rgba(15, 23, 42, 0.84);
  color: rgba(226, 232, 240, 0.88);
}

:global(html.kikoerumanager-dark .circle-bonus-shelf.is-card .circle-bonus-gift),
:global(body.kikoerumanager-dark .circle-bonus-shelf.is-card .circle-bonus-gift) {
  border-color: rgba(250, 204, 21, 0.30);
  box-shadow:
    0 0 8px rgba(250, 204, 21, 0.22),
    0 0 14px rgba(250, 204, 21, 0.10),
    0 10px 24px rgba(0, 0, 0, 0.34);
}

:global(html.kikoerumanager-dark .circle-bonus-shelf.is-card .circle-bonus-gift::before),
:global(body.kikoerumanager-dark .circle-bonus-shelf.is-card .circle-bonus-gift::before) {
  background:
    radial-gradient(ellipse at 78% 8%, rgba(254, 240, 138, 0.46), rgba(250, 204, 21, 0.24) 22%, transparent 54%),
    radial-gradient(ellipse at 16% 92%, rgba(250, 204, 21, 0.30), transparent 58%),
    radial-gradient(circle at 54% 18%, rgba(255, 255, 255, 0.32), transparent 13%);
  background-size: 120% 120%, 120% 120%, 100% 100%;
  box-shadow: 0 0 11px rgba(250, 204, 21, 0.20);
}

:global(html.kikoerumanager-dark .circle-bonus-shelf.is-card .circle-bonus-gift),
:global(body.kikoerumanager-dark .circle-bonus-shelf.is-card .circle-bonus-gift),
:global(html.kikoerumanager-dark .circle-bonus-shelf.is-card .circle-bonus-gift-cover),
:global(body.kikoerumanager-dark .circle-bonus-shelf.is-card .circle-bonus-gift-cover) {
  background: transparent;
}

:global(html.kikoerumanager-dark .circle-bonus-gift-title),
:global(body.kikoerumanager-dark .circle-bonus-gift-title) {
  color: rgba(248, 250, 252, 0.92);
}

:global(html.kikoerumanager-dark .circle-bonus-gift-code),
:global(body.kikoerumanager-dark .circle-bonus-gift-code) {
  color: rgba(203, 213, 225, 0.74);
}

:global(html.kikoerumanager-dark .circle-bonus-gift-cover),
:global(body.kikoerumanager-dark .circle-bonus-gift-cover),
:global(html.kikoerumanager-dark .circle-bonus-mini-action),
:global(body.kikoerumanager-dark .circle-bonus-mini-action) {
  border-color: rgba(148, 163, 184, 0.20);
  background: rgba(30, 41, 59, 0.74);
  color: rgba(203, 213, 225, 0.78);
}

:global(html.kikoerumanager-dark .circle-bonus-mini-action.import),
:global(body.kikoerumanager-dark .circle-bonus-mini-action.import) {
  border-color: rgba(52, 211, 153, 0.42);
  background: rgba(5, 150, 105, 0.20);
  color: #6ee7b7;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-card),
:global(body.kikoerumanager-dark .circle-bonus-detail-card) {
  border-color: rgba(255, 255, 255, 0.14);
  background: linear-gradient(180deg, rgba(34, 36, 40, 0.98) 0%, rgba(24, 25, 29, 0.98) 100%);
  color: rgba(226, 232, 240, 0.88);
  box-shadow:
    0 18px 46px rgba(0, 0, 0, 0.34),
    0 5px 18px rgba(0, 0, 0, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

:global(html.kikoerumanager-dark .circle-bonus-detail-cover),
:global(body.kikoerumanager-dark .circle-bonus-detail-cover) {
  background: #141519;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-media),
:global(body.kikoerumanager-dark .circle-bonus-detail-media) {
  background: #18191d;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-tag.is-primary),
:global(body.kikoerumanager-dark .circle-bonus-detail-tag.is-primary) {
  background: rgba(37, 99, 235, 0.22);
  border-color: rgba(96, 165, 250, 0.46);
  color: #93c5fd;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-tag.is-success),
:global(body.kikoerumanager-dark .circle-bonus-detail-tag.is-success) {
  background: rgba(5, 150, 105, 0.22);
  border-color: rgba(52, 211, 153, 0.46);
  color: #6ee7b7;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-tag.is-danger),
:global(body.kikoerumanager-dark .circle-bonus-detail-tag.is-danger) {
  background: rgba(220, 38, 38, 0.22);
  border-color: rgba(248, 113, 113, 0.48);
  color: #fca5a5;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-tag.is-disabled),
:global(body.kikoerumanager-dark .circle-bonus-detail-tag.is-disabled) {
  background: rgba(248, 250, 252, 0.12);
  border-color: rgba(226, 232, 240, 0.22);
  color: #cbd5e1;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-linked),
:global(body.kikoerumanager-dark .circle-bonus-detail-linked) {
  color: rgba(203, 213, 225, 0.76);
}

:global(html.kikoerumanager-dark .circle-bonus-detail-title),
:global(body.kikoerumanager-dark .circle-bonus-detail-title) {
  color: rgba(248, 250, 252, 0.94);
}

:global(html.kikoerumanager-dark .circle-bonus-detail-cv),
:global(body.kikoerumanager-dark .circle-bonus-detail-cv) {
  color: #38bdf8;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-action),
:global(body.kikoerumanager-dark .circle-bonus-detail-action) {
  border-color: rgba(226, 232, 240, 0.18);
  background: rgba(255, 255, 255, 0.075);
  color: rgba(244, 244, 245, 0.88);
}

:global(html.kikoerumanager-dark .circle-bonus-detail-action:hover),
:global(body.kikoerumanager-dark .circle-bonus-detail-action:hover) {
  border-color: rgba(226, 232, 240, 0.28);
  background: rgba(255, 255, 255, 0.12);
  color: #ffffff;
}

:global(html.kikoerumanager-dark .circle-bonus-detail-action.import),
:global(body.kikoerumanager-dark .circle-bonus-detail-action.import) {
  border-color: rgba(52, 211, 153, 0.42);
  background: rgba(5, 150, 105, 0.18);
  color: #6ee7b7;
}

@media (max-width: 640px) {
  .circle-bonus-shelf.is-card {
    right: 7px;
    width: min(38%, 76px);
  }

  .circle-bonus-detail-card {
    top: 8px;
    right: 8px;
    left: 8px;
    grid-template-columns: 1fr;
    width: calc(100% - 16px);
  }

  .circle-work-virtual-cell.is-right-half .circle-bonus-detail-card.is-card-inline,
  .circle-work-plain-cell.is-right-half .circle-bonus-detail-card.is-card-inline {
    right: 8px;
    left: 8px;
    transform-origin: top left;
  }

  .circle-bonus-detail-card.is-list-inline {
    width: 100%;
    margin: 0 0 8px 0;
    grid-template-columns: 1fr;
  }

  .circle-bonus-detail-body {
    padding-top: 12px;
  }

  .circle-bonus-detail-actions {
    gap: 5px;
  }
}

.circle-work-viewport :deep(.work-card) {
  height: 100%;
  animation: none;
}

.circle-work-viewport :deep(.work-actions) {
  opacity: 0;
  transform: translateY(3px);
  pointer-events: none;
}

.circle-work-viewport :deep(.work-card:hover .work-actions) {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

.circle-work-viewport :deep(.work-list-row) {
  height: 100%;
  box-sizing: border-box;
  animation: none;
}

.circle-work-empty {
  flex: 1;
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--circle-border-soft, rgba(203, 213, 225, 0.88));
  border-radius: 16px;
  background: var(--circle-surface-muted, rgba(255, 255, 255, 0.54));
  color: var(--circle-text-muted, #94a3b8);
  font-size: 13px;
  font-weight: 700;
}

.works-pager {
  display: flex;
  justify-content: flex-end;
  flex-shrink: 0;
  margin-top: auto;
  padding-top: 16px;
}

.works-pager :deep(.el-pagination) {
  width: 100%;
  justify-content: flex-end;
}

@keyframes viewportCellEntrance {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.985);
    filter: saturate(0.92);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: saturate(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .circle-work-virtual-cell.is-motion-active {
    animation: none;
  }
}

@media (max-width: 760px) {
  .works-pager {
    justify-content: center;
  }

  .works-pager :deep(.el-pagination) {
    justify-content: center;
  }
}

@media (max-width: 420px) {
  .circle-work-scroll {
    min-height: 330px;
  }
}

@media (max-width: 640px) {
  .circle-work-viewport :deep(.work-actions) {
    opacity: 1;
    transform: translateY(0);
    pointer-events: auto;
  }

}
</style>
