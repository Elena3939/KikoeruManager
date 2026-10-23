import { computed, shallowRef } from 'vue'

// 只保存已经打开的详情引用和视图位置，不复制或重新聚合批次数据。
export function useActivityDetailNavigation({ loadDetail, captureView, restoreView, onError }) {
  const row = shallowRef(null)
  const loading = shallowRef(false)
  const ancestors = shallowRef([])
  const canGoBack = computed(() => ancestors.value.length > 0)
  let revision = 0

  async function load(target, child) {
    if (!target?.id || (child && String(target.id) === String(row.value?.id))) return
    const previous = row.value ? { row: row.value, view: captureView() } : null
    const previousAncestors = ancestors.value
    ancestors.value = child && previous ? [...previousAncestors, previous] : []
    const currentRevision = ++revision
    row.value = { ...target, __isLite: true }
    loading.value = true
    restoreView(null)
    try {
      const full = await loadDetail(target.id)
      if (!full) throw new Error('未找到对应操作记录')
      if (revision === currentRevision) row.value = full
    } catch (error) {
      if (revision !== currentRevision) return
      if (child && previous) {
        ancestors.value = previousAncestors
        row.value = previous.row
        restoreView(previous.view)
      } else {
        row.value = { ...target }
      }
      onError(error)
    } finally {
      if (revision === currentRevision) loading.value = false
    }
  }

  function back() {
    const previous = ancestors.value.at(-1)
    if (!previous) return
    ++revision
    loading.value = false
    ancestors.value = ancestors.value.slice(0, -1)
    row.value = previous.row
    restoreView(previous.view)
  }

  function cancel() {
    ++revision
    loading.value = false
  }

  function reset() {
    cancel()
    row.value = null
    ancestors.value = []
  }

  return { row, loading, canGoBack, back, cancel, reset,
    open: target => load(target, false), openChild: id => load({ id }, true) }
}
