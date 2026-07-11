import { defineStore } from 'pinia'

function finiteRevision (value) {
  if (value === null || value === undefined || value === '') return null
  const revision = Number(value)
  return Number.isFinite(revision) && revision >= 0 ? revision : null
}

export function normalizeLibraryIndexPath (value) {
  const raw = String(value || '').trim().replace(/\\/g, '/')
  if (!raw) return ''
  const prefix = raw.startsWith('//') ? '//' : ''
  const normalized = raw.replace(/^\/+/, '').replace(/\/{2,}/g, '/').replace(/\/$/, '')
  return `${prefix}${normalized}` || prefix
}

export function libraryIndexPathMatches (candidate, root, scope = 'exact') {
  const candidatePath = normalizeLibraryIndexPath(candidate)
  const rootPath = normalizeLibraryIndexPath(root)
  if (!candidatePath || !rootPath) return false
  if (candidatePath === rootPath) return true
  return scope === 'subtree' && candidatePath.startsWith(`${rootPath}/`)
}

function normalizeScope (value) {
  return value === 'subtree' ? 'subtree' : 'exact'
}

function indexViewFromPayload (payload) {
  if (!payload || typeof payload !== 'object') return []
  if (Array.isArray(payload.index_views)) return payload.index_views.filter(Boolean)
  if (payload.index_view && typeof payload.index_view === 'object') return [payload.index_view]
  if (payload.library_id && [
    payload.view_revision,
    payload.index_generation,
    payload.active_generation,
    payload.accepted_seq,
    payload.materialized_seq,
  ].some(value => value !== undefined && value !== null)) {
    return [{
      library_id: payload.library_id,
      view_revision: payload.view_revision,
      index_generation: payload.index_generation,
      active_generation: payload.active_generation,
      accepted_seq: payload.accepted_seq,
      materialized_seq: payload.materialized_seq,
    }]
  }
  return []
}

function normalizeFenceEffects (fence) {
  const effects = []
  for (const effect of Array.isArray(fence?.effects) ? fence.effects : []) {
    const path = effect?.relative_path || effect?.path || effect?.source_path
    if (!path) continue
    effects.push({
      seq: finiteRevision(effect.seq ?? fence.accepted_seq) || 0,
      kind: String(effect.kind || effect.effect_kind || '').toLowerCase(),
      path,
      scope: normalizeScope(effect.scope),
    })
  }
  for (const path of Array.isArray(fence?.deleted_paths) ? fence.deleted_paths : []) {
    effects.push({ seq: finiteRevision(fence.accepted_seq) || 0, kind: 'delete', path, scope: 'subtree' })
  }
  for (const path of Array.isArray(fence?.upsert_paths) ? fence.upsert_paths : []) {
    effects.push({ seq: finiteRevision(fence.accepted_seq) || 0, kind: 'upsert', path, scope: 'subtree' })
  }
  return effects
}

function rowLocationList (row) {
  if (Array.isArray(row?.locations)) return row.locations
  if (Array.isArray(row?.circle_locations)) return row.circle_locations
  return null
}

const RUNTIME_STATUS_FIELDS = new Set([
  'materializer_epoch',
  'runtime_revision',
  'current_operation_id',
  'processing_rate',
  'oldest_pending_age_seconds',
  'redis_pending',
  'replay_count',
  'watcher_dirty_count',
])

function runtimeStatusPatch (snapshot) {
  const patch = {}
  for (const key of RUNTIME_STATUS_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(snapshot || {}, key)) patch[key] = snapshot[key]
  }
  return patch
}

function compareRuntimeSnapshot (current, next) {
  const currentEpoch = finiteRevision(current?.materializer_epoch) ?? 0
  const nextEpoch = finiteRevision(next?.materializer_epoch) ?? 0
  if (nextEpoch !== currentEpoch) return nextEpoch > currentEpoch ? 1 : -1
  const currentRevision = finiteRevision(current?.runtime_revision) ?? 0
  const nextRevision = finiteRevision(next?.runtime_revision) ?? 0
  if (nextRevision === currentRevision) return 0
  return nextRevision > currentRevision ? 1 : -1
}

export const useLibraryIndexStateStore = defineStore('library-index-state', {
  state: () => ({
    statusByLibrary: {},
    statusSourceByLibrary: {},
    viewByLibrary: {},
    crossLibraryViewToken: '',
    fencesByOperation: {},
    tombstonesByLibrary: {},
    temporaryOperationSequence: 0,
    libraryRootById: {},
  }),

  getters: {
    statusFor: state => libraryId => state.statusByLibrary[String(libraryId || '')] || null,
    indexViewFor: state => libraryId => state.viewByLibrary[String(libraryId || '')] || null,
    tombstonesFor: state => libraryId => state.tombstonesByLibrary[String(libraryId || '')] || [],
  },

  actions: {
    applyStatusSnapshot (snapshot, source = 'http') {
      const libraryId = String(snapshot?.library_id || '').trim()
      if (!libraryId || !snapshot || typeof snapshot !== 'object') return false

      const current = this.statusByLibrary[libraryId]
      const currentRevision = finiteRevision(current?.state_revision)
      const nextRevision = finiteRevision(snapshot.state_revision)
      const currentSource = this.statusSourceByLibrary[libraryId] || ''

      if (current) {
        if (currentRevision !== null && nextRevision !== null && nextRevision < currentRevision) return false
        if (currentRevision !== null && nextRevision === null) return false
        if (currentRevision === null && nextRevision === null && currentSource === 'sse' && source !== 'sse') return false
        if (currentRevision !== null && nextRevision === currentRevision) {
          if (compareRuntimeSnapshot(current, snapshot) <= 0) return false
          this.statusByLibrary = {
            ...this.statusByLibrary,
            [libraryId]: { ...current, ...runtimeStatusPatch(snapshot), library_id: libraryId },
          }
          this.statusSourceByLibrary = { ...this.statusSourceByLibrary, [libraryId]: source }
          return true
        }
      }

      const runtimeComparison = current ? compareRuntimeSnapshot(current, snapshot) : 0
      const retainedRuntime = current && runtimeComparison > 0 ? runtimeStatusPatch(snapshot) : runtimeStatusPatch(current)

      this.statusByLibrary = {
        ...this.statusByLibrary,
        [libraryId]: { ...snapshot, ...retainedRuntime, library_id: libraryId },
      }
      this.statusSourceByLibrary = { ...this.statusSourceByLibrary, [libraryId]: source }
      this.releaseMaterializedTombstones(libraryId, snapshot)
      return true
    },

    recordIndexViews (payload) {
      const views = indexViewFromPayload(payload)
      for (const view of views) {
        const libraryId = String(view?.library_id || '').trim()
        if (!libraryId) continue
        const current = this.viewByLibrary[libraryId]
        const currentRevision = finiteRevision(current?.view_revision)
        const nextRevision = finiteRevision(view?.view_revision)
        const currentGeneration = finiteRevision(current?.active_generation ?? current?.index_generation)
        const nextGeneration = finiteRevision(view?.active_generation ?? view?.index_generation)
        if (current && currentRevision !== null && nextRevision !== null && nextRevision < currentRevision) continue
        if (current && currentRevision !== null && nextRevision === null) continue
        if (current && currentGeneration !== null && nextGeneration !== null && nextGeneration < currentGeneration) continue
        this.viewByLibrary = {
          ...this.viewByLibrary,
          [libraryId]: { ...view, library_id: libraryId },
        }
      }
      if (payload?.view_token) this.crossLibraryViewToken = String(payload.view_token)
      return views
    },

    isIndexViewResponseCurrent (payload) {
      if (payload?.view_token && this.crossLibraryViewToken && String(payload.view_token) !== this.crossLibraryViewToken) {
        const nextViews = indexViewFromPayload(payload)
        const hasOlderRevision = nextViews.some(view => {
          const current = this.viewByLibrary[String(view?.library_id || '')]
          const currentRevision = finiteRevision(current?.view_revision)
          const nextRevision = finiteRevision(view?.view_revision)
          return currentRevision !== null && nextRevision !== null && nextRevision < currentRevision
        })
        if (hasOlderRevision) return false
      }
      for (const view of indexViewFromPayload(payload)) {
        const libraryId = String(view?.library_id || '').trim()
        const current = this.viewByLibrary[libraryId] || this.statusByLibrary[libraryId]
        if (!libraryId || !current) continue
        const currentRevision = finiteRevision(current.view_revision)
        const nextRevision = finiteRevision(view.view_revision)
        if (currentRevision !== null && nextRevision !== null && nextRevision < currentRevision) return false
        const currentGeneration = finiteRevision(current.active_generation ?? current.index_generation)
        const nextGeneration = finiteRevision(view.active_generation ?? view.index_generation ?? payload?.index_generation)
        if (currentGeneration !== null && nextGeneration !== null && nextGeneration < currentGeneration) return false
      }
      return true
    },

    registerMutationResponse (response, fallback = {}) {
      const operationId = String(response?.operation_id || fallback.operationId || `local-${Date.now()}-${++this.temporaryOperationSequence}`)
      const fences = Array.isArray(response?.index_fences) ? response.index_fences : []
      if (fences.length) {
        this.fencesByOperation = {
          ...this.fencesByOperation,
          [operationId]: {
            operation_id: operationId,
            operation_state: response?.operation_state || 'committed',
            fences: fences.map(item => ({ ...item })),
          },
        }
      }

      const fallbackByLibrary = new Map()
      for (const item of Array.isArray(fallback.deletedPaths) ? fallback.deletedPaths : []) {
        const libraryId = String(item?.libraryId || fallback.libraryId || '').trim()
        const path = item?.path || item
        if (!libraryId || !path) continue
        if (!fallbackByLibrary.has(libraryId)) fallbackByLibrary.set(libraryId, [])
        fallbackByLibrary.get(libraryId).push({ path, scope: normalizeScope(item?.scope) })
      }

      const touchedLibraries = new Set()
      for (const fence of fences) {
        const libraryId = String(fence?.library_id || '').trim()
        if (!libraryId) continue
        touchedLibraries.add(libraryId)
        this.recordIndexViews({ index_view: fence })
        const effects = normalizeFenceEffects(fence)
        for (const effect of effects) {
          if (['delete', 'move', 'replace', 'reconcile'].includes(effect.kind)) {
            this.addTombstone(libraryId, {
              operationId,
              acceptedSeq: effect.seq,
              releaseSeq: effect.seq,
              path: effect.path,
              scope: effect.scope,
              confirmed: true,
            })
          } else if (['upsert', 'create'].includes(effect.kind)) {
            this.extendMatchingTombstones(libraryId, effect.path, effect.seq)
          }
        }
      }

      for (const [libraryId, paths] of fallbackByLibrary.entries()) {
        if (touchedLibraries.has(libraryId)) continue
        for (const item of paths) {
          this.addTombstone(libraryId, {
            operationId,
            acceptedSeq: 0,
            releaseSeq: 0,
            path: item.path,
            scope: item.scope,
            confirmed: true,
          })
        }
      }
      return operationId
    },

    setLibraryRoots (libraries) {
      const next = { ...this.libraryRootById }
      for (const library of Array.isArray(libraries) ? libraries : []) {
        const libraryId = String(library?.id || library?.library_id || '').trim()
        const rootPath = normalizeLibraryIndexPath(library?.root_path || library?.path)
        if (libraryId && rootPath) next[libraryId] = rootPath
      }
      this.libraryRootById = next
    },

    relativePathFor (libraryId, path) {
      const id = String(libraryId || '').trim()
      const normalizedPath = normalizeLibraryIndexPath(path)
      const rootPath = normalizeLibraryIndexPath(this.libraryRootById[id])
      if (!normalizedPath || !rootPath) return normalizedPath
      const pathFolded = normalizedPath.toLocaleLowerCase()
      const rootFolded = rootPath.toLocaleLowerCase()
      if (pathFolded === rootFolded) return ''
      if (!pathFolded.startsWith(`${rootFolded}/`)) return normalizedPath
      return normalizedPath.slice(rootPath.length + 1)
    },

    addTombstone (libraryId, tombstone) {
      const id = String(libraryId || '').trim()
      const path = normalizeLibraryIndexPath(tombstone?.path)
      if (!id || !path) return
      const current = this.tombstonesByLibrary[id] || []
      const next = current.filter(item => !(
        item.operationId === tombstone.operationId &&
        item.path === path &&
        item.scope === normalizeScope(tombstone.scope)
      ))
      next.push({
        operationId: String(tombstone.operationId || ''),
        acceptedSeq: finiteRevision(tombstone.acceptedSeq) || 0,
        releaseSeq: finiteRevision(tombstone.releaseSeq) || 0,
        path,
        scope: normalizeScope(tombstone.scope),
        confirmed: tombstone.confirmed !== false,
      })
      this.tombstonesByLibrary = { ...this.tombstonesByLibrary, [id]: next }
    },

    extendMatchingTombstones (libraryId, path, seq) {
      const id = String(libraryId || '').trim()
      const nextSeq = finiteRevision(seq) || 0
      if (!id || !nextSeq) return
      const current = this.tombstonesByLibrary[id] || []
      const next = current.map(item => (
        libraryIndexPathMatches(path, item.path, item.scope) || libraryIndexPathMatches(item.path, path, 'subtree')
          ? { ...item, releaseSeq: Math.max(Number(item.releaseSeq || 0), nextSeq) }
          : item
      ))
      this.tombstonesByLibrary = { ...this.tombstonesByLibrary, [id]: next }
    },

    releaseMaterializedTombstones (libraryId, status) {
      const id = String(libraryId || '').trim()
      const materializedSeq = finiteRevision(status?.materialized_seq)
      if (!id || materializedSeq === null) return
      const current = this.tombstonesByLibrary[id] || []
      const next = current.filter(item => !(
        item.confirmed && Number(item.releaseSeq || 0) > 0 && materializedSeq >= Number(item.releaseSeq)
      ))
      if (next.length === current.length) return
      this.tombstonesByLibrary = { ...this.tombstonesByLibrary, [id]: next }
    },

    isPathTombstoned (libraryId, path) {
      const id = String(libraryId || '').trim()
      const relativePath = this.relativePathFor(id, path)
      return (this.tombstonesByLibrary[id] || []).some(item => (
        libraryIndexPathMatches(path, item.path, item.scope) ||
        libraryIndexPathMatches(relativePath, item.path, item.scope)
      ))
    },

    filterRows (libraryId, rows, options = {}) {
      const result = []
      for (const sourceRow of Array.isArray(rows) ? rows : []) {
        const directLibraryId = String(options.getLibraryId?.(sourceRow) || sourceRow?.library_id || libraryId || '').trim()
        const directPaths = [
          options.getPath?.(sourceRow),
          sourceRow?.absolute_path,
          sourceRow?.path,
          sourceRow?.relative_path,
        ].filter(Boolean)
        if (directLibraryId && directPaths.some(path => this.isPathTombstoned(directLibraryId, path))) continue

        const locations = rowLocationList(sourceRow)
        if (!locations) {
          result.push(sourceRow)
          continue
        }
        const visibleLocations = locations.filter(location => !this.isPathTombstoned(
          location?.library_id,
          location?.path || location?.absolute_path || location?.relative_path,
        ))
        if (!visibleLocations.length && locations.length) continue
        if (visibleLocations.length === locations.length) {
          result.push(sourceRow)
          continue
        }
        const nextRow = { ...sourceRow, locations: visibleLocations }
        if (Array.isArray(sourceRow.circle_locations)) nextRow.circle_locations = visibleLocations
        nextRow.circle_location_count = visibleLocations.length
        const primaryLocation = visibleLocations[0] || {}
        if (sourceRow.circle_real_path !== undefined) nextRow.circle_real_path = primaryLocation.path || ''
        if (sourceRow.circle_real_library_id !== undefined) nextRow.circle_real_library_id = primaryLocation.library_id || ''
        if (sourceRow.primary_path !== undefined) nextRow.primary_path = primaryLocation.path || ''
        if (sourceRow.primary_library_id !== undefined) nextRow.primary_library_id = primaryLocation.library_id || ''
        if (sourceRow.conflict !== undefined) nextRow.conflict = visibleLocations.length > 1
        result.push(nextRow)
      }
      return result
    },
  },
})
