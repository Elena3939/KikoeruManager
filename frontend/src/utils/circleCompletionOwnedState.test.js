import { describe, expect, it } from 'vitest'
import { reconcileCircleCompletionOwnedState } from './circleCompletionOwnedState'

describe('reconcileCircleCompletionOwnedState', () => {
  it('作品刷新为已拥有后从缺失页移除', () => {
    const result = reconcileCircleCompletionOwnedState(
      [{ canonical_rjcode: 'RJ01000001', owned: false }],
      [{ canonical_rjcode: 'RJ01000001', local_owned: true, has_kikoeru: true }],
      'missing',
    )

    expect(result.items).toEqual([])
    expect(result.gainedCodes).toEqual(['RJ01000001'])
    expect(result.lostCodes).toEqual([])
  })

  it('附属特典刷新为已拥有后整个作品组进入已满足语义', () => {
    const group = {
      canonical_rjcode: 'RJ01000001',
      owned: false,
      bonus_works: [{ canonical_rjcode: 'RJ01000002', owned: false }],
    }
    const refreshed = [{ canonical_rjcode: 'RJ01000002', local_owned: true }]

    expect(reconcileCircleCompletionOwnedState([group], refreshed, 'missing').items).toEqual([])
    const owned = reconcileCircleCompletionOwnedState([group], refreshed, 'owned')
    expect(owned.items).toHaveLength(1)
    expect(owned.items[0].bonus_works[0].owned).toBe(true)
  })
})
