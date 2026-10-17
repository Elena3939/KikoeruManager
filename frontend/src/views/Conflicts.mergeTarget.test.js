import { expect, it, vi } from 'vitest'
import source from './Conflicts.vue?raw'

function handler(name, bindings) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`))
  const code = source.slice(start, source.indexOf('\n}', start) + 2)
  return new Function(...Object.keys(bindings), `${code}; return ${name}`)(...Object.values(bindings))
}

it('后端要求选择目标时保留候选目录，不缓存成已完成预览', async () => {
  const candidates = [{ library_id: 'one', path: '/library/RJ01731933' }]
  const bindings = {
    mergePreviewRunToken: 1,
    mergePreviewCache: {},
    mergeTargetCandidates: { value: [] },
    conflictApi: { preview: vi.fn().mockResolvedValue({ requires_target_selection: true, target_candidates: candidates }) }
  }
  const getPreview = handler('getMergePreview', bindings)
  expect(await getPreview({ id: 'conflict' }, true, null, 1)).toBeNull()
  expect(bindings.mergeTargetCandidates.value).toEqual(candidates)
  expect(bindings.mergePreviewCache).toEqual({})
})

it('选择目录后清除旧目标的预览与决策，并将选择传给预览流程', async () => {
  const item = { id: 'conflict' }
  const target = { library_id: 'two', path: '/second/RJ01731933' }
  const bindings = {
    mergeConflict: { value: item },
    mergePreviewCache: { conflict: { session_id: 'old-session' } },
    mergeDecisionCache: { conflict: { 'track.mp3': 'use_new' } },
    openMergeWorkbench: vi.fn().mockResolvedValue(undefined)
  }
  await handler('selectMergeTarget', bindings)(target)
  expect(bindings.mergePreviewCache).toEqual({})
  expect(bindings.mergeDecisionCache).toEqual({})
  expect(bindings.openMergeWorkbench).toHaveBeenCalledWith(item, true, target)
})

it('预览请求携带用户选定的库存目录', async () => {
  const target = { library_id: 'two', path: '/second/RJ01731933' }
  const preview = { session_id: 'new-session', existing_path: target.path, items: [] }
  const bindings = {
    mergePreviewRunToken: 1,
    mergePreviewCache: {},
    conflictApi: { preview: vi.fn().mockResolvedValue(preview) }
  }
  expect(await handler('getMergePreview', bindings)({ id: 'conflict' }, true, null, 1, target)).toEqual(preview)
  expect(bindings.conflictApi.preview).toHaveBeenCalledWith('conflict', 'MERGE', target)
})
