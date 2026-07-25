import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLibraryIndexStateStore } from './libraryIndexState'

describe('useLibraryIndexStateStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('旧 HTTP 状态不能覆盖更新的 SSE 完整快照', () => {
    const store = useLibraryIndexStateStore()
    expect(store.applyStatusSnapshot({
      library_id: 'A',
      state_revision: 8,
      view_revision: 4,
      status: 'catching_up',
      accepted_seq: 12,
      materialized_seq: 10,
    }, 'sse')).toBe(true)

    expect(store.applyStatusSnapshot({
      library_id: 'A',
      state_revision: 7,
      view_revision: 3,
      status: 'ready',
      accepted_seq: 9,
      materialized_seq: 9,
    }, 'http')).toBe(false)
    expect(store.statusFor('A').state_revision).toBe(8)
    expect(store.statusFor('A').status).toBe('catching_up')
  })

  it('目录 tombstone 过滤自身和全部后代但不误伤同前缀目录', () => {
    const store = useLibraryIndexStateStore()
    store.addTombstone('A', {
      operationId: 'op-delete',
      acceptedSeq: 3,
      releaseSeq: 3,
      path: 'voice/RJ000001',
      scope: 'subtree',
    })

    const rows = store.filterRows('A', [
      { path: 'voice/RJ000001' },
      { path: 'voice/RJ000001/audio.wav' },
      { path: 'voice/RJ000001-extra/audio.wav' },
    ])

    expect(rows.map(item => item.path)).toEqual([
      'voice/RJ000001-extra/audio.wav',
    ])
  })

  it('materialized_seq 达到 fence 水位前不释放遮罩', () => {
    const store = useLibraryIndexStateStore()
    store.registerMutationResponse({
      operation_id: 'op-1',
      operation_state: 'committed',
      index_fences: [{
        library_id: 'A',
        accepted_seq: 5,
        view_revision: 2,
        active_generation: 1,
        effects: [{ seq: 5, kind: 'delete', relative_path: 'old', scope: 'subtree' }],
      }],
    })

    store.applyStatusSnapshot({ library_id: 'A', state_revision: 3, materialized_seq: 4 }, 'sse')
    expect(store.isPathTombstoned('A', 'old/child.txt')).toBe(true)

    store.applyStatusSnapshot({ library_id: 'A', state_revision: 4, materialized_seq: 5 }, 'sse')
    expect(store.isPathTombstoned('A', 'old/child.txt')).toBe(false)
  })

  it('普通目录响应达到 materialized_seq 时也释放重命名路径遮罩', () => {
    const store = useLibraryIndexStateStore()
    store.registerMutationResponse({
      operation_id: 'op-rename',
      operation_state: 'committed',
      index_fences: [{
        library_id: 'A',
        accepted_seq: 9,
        view_revision: 2,
        active_generation: 1,
        effects: [
          { seq: 9, kind: 'move', relative_path: 'old', scope: 'subtree' },
          { seq: 9, kind: 'reconcile', relative_path: 'new', scope: 'subtree' },
        ],
      }],
    })

    expect(store.isPathTombstoned('A', 'old/item.wav')).toBe(true)
    expect(store.isPathTombstoned('A', 'new/item.wav')).toBe(true)

    store.recordIndexViews({
      index_view: {
        library_id: 'A',
        view_revision: 3,
        active_generation: 1,
        materialized_seq: 9,
      },
    })

    expect(store.isPathTombstoned('A', 'old/item.wav')).toBe(false)
    expect(store.isPathTombstoned('A', 'new/item.wav')).toBe(false)
  })
})
