<script setup>
import { computed } from 'vue'
import { AlertCircle, Check, X } from 'lucide-vue-next'
import animeShareIcon from '../../assets/platforms/anime-sharing.png'
import southPlusIcon from '../../assets/platforms/south-plus.ico'

const props = defineProps({
  item: { type: Object, required: true },
})

const emit = defineEmits(['open'])

const sourceMeta = [
  { key: 'anime_share', label: 'AnimeShare', icon: animeShareIcon },
  { key: 'south_plus', label: '南+', icon: southPlusIcon },
]

function fallbackSearchResult(source) {
  const rjcode = String(
    props.item?.canonical_rjcode
      || props.item?.display_rjcode
      || props.item?.rjcode
      || '',
  ).trim().toUpperCase()
  if (!/^RJ(?:\d{6}|\d{8})$/.test(rjcode)) return null
  let url = ''
  if (source === 'anime_share') {
    url = `https://www.anime-sharing.com/search/3528560/?q=${encodeURIComponent(rjcode)}&o=relevance`
  } else {
    const params = new URLSearchParams({
      step: '2',
      keyword: rjcode,
      method: 'OR',
      pwuser: '',
      sch_area: '0',
      f_fid: 'all',
      sch_time: 'all',
      orderway: 'postdate',
      asc: 'DESC',
    })
    url = `https://bbs.white-plus.net/search.php?${params.toString()}`
  }
  return {
    source,
    rjcode,
    variant_key: 'original',
    variant_label: '原作',
    title: `搜索 ${rjcode}`,
    url,
  }
}

const sources = computed(() => sourceMeta.map(meta => {
  const payload = props.item?.external_search?.[meta.key] || {}
  const status = String(payload.status || 'loading')
  const results = Array.isArray(payload.results) ? payload.results : []
  const searchResults = Array.isArray(payload.search_results) ? payload.search_results : []
  const fallback = status !== 'loading' ? fallbackSearchResult(meta.key) : null
  const actions = status === 'hit' && results.length
    ? results
    : (searchResults.length ? searchResults : (fallback ? [fallback] : []))
  return { ...meta, status, results, actions }
}))

function statusIcon(status) {
  if (status === 'hit') return Check
  if (status === 'miss') return X
  if (status === 'unavailable' || status === 'error') return AlertCircle
  return null
}

function statusTitle(entry) {
  if (entry.status === 'hit') return `${entry.label} · 命中 ${entry.results.length} 个结果`
  if (entry.status === 'miss') return `${entry.label} · 未找到，点击打开搜索页`
  if (entry.status === 'unavailable') return `${entry.label} · 当前无法探测，点击打开搜索页`
  if (entry.status === 'error') return `${entry.label} · 查询失败，点击打开搜索页`
  return `${entry.label} · 查询中`
}

function handleOpen(entry) {
  if (!entry.actions.length) return
  emit('open', {
    item: props.item,
    source: entry.key,
    status: entry.status,
    results: entry.actions,
  })
}
</script>

<template>
  <span class="external-source-chips" @click.stop>
    <button
      v-for="entry in sources"
      :key="entry.key"
      type="button"
      class="external-source-chip"
      :class="`is-${entry.status}`"
      :title="statusTitle(entry)"
      :aria-label="statusTitle(entry)"
      :disabled="!entry.actions.length"
      @click.stop="handleOpen(entry)"
    >
      <img :src="entry.icon" :alt="entry.label" />
      <span class="external-source-status" aria-hidden="true">
        <component :is="statusIcon(entry.status)" v-if="statusIcon(entry.status)" :size="7" :stroke-width="3" />
      </span>
    </button>
  </span>
</template>

<style scoped>
.external-source-chips {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 3px;
  padding-right: 4px;
}

.external-source-chip {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 22px;
  flex: 0 0 24px;
  padding: 2px 3px;
  border: 1px solid rgba(148, 163, 184, .34);
  border-radius: 5px;
  background: rgba(248, 250, 252, .78);
  cursor: pointer;
  transition: all .2s cubic-bezier(.34,1.56,.64,1);
}

.external-source-chip img {
  display: block;
  width: 16px;
  height: 16px;
  object-fit: contain;
}

.external-source-chip:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.05);
}

.external-source-chip:active:not(:disabled) { transform: scale(.94); }

.external-source-chip.is-hit {
  border-color: rgba(34, 197, 94, .5);
  background: rgba(240, 253, 244, .92);
  box-shadow: 0 0 0 1px rgba(34, 197, 94, .08);
}

.external-source-chip.is-miss,
.external-source-chip.is-unavailable,
.external-source-chip.is-error {
  background: rgba(241, 245, 249, .78);
}

.external-source-chip.is-miss img { filter: grayscale(1); opacity: .58; }
.external-source-chip.is-unavailable img { filter: grayscale(.75); opacity: .64; }
.external-source-chip.is-error img { filter: grayscale(.45); opacity: .72; }
.external-source-chip.is-loading img { opacity: .68; }

.external-source-chip:disabled {
  cursor: default;
}

.external-source-status {
  position: absolute;
  top: -4px;
  right: -4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 11px;
  height: 11px;
  border: 1px solid #fff;
  border-radius: 999px;
  background: #94a3b8;
  color: #fff;
}

.is-hit .external-source-status { background: #22c55e; }
.is-miss .external-source-status { background: #94a3b8; }
.is-unavailable .external-source-status { background: #f59e0b; }
.is-error .external-source-status { background: #ef4444; }
.is-loading .external-source-status { animation: externalSourcePulse 1s ease-in-out infinite; }

@keyframes externalSourcePulse {
  0%, 100% { opacity: .45; transform: scale(.85); }
  50% { opacity: 1; transform: scale(1); }
}

:global(html.kikoerumanager-dark .external-source-chip),
:global(body.kikoerumanager-dark .external-source-chip) {
  border-color: rgba(148, 163, 184, .28);
  background: rgba(39, 40, 45, .92);
}

:global(html.kikoerumanager-dark .external-source-chip.is-hit),
:global(body.kikoerumanager-dark .external-source-chip.is-hit) {
  border-color: rgba(74, 222, 128, .52);
  background: rgba(22, 101, 52, .26);
}

:global(html.kikoerumanager-dark .external-source-status),
:global(body.kikoerumanager-dark .external-source-status) {
  border-color: #18181b;
}
</style>
