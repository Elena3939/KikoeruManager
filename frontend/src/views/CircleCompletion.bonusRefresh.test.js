import { describe, expect, it, vi } from 'vitest'
import source from './CircleCompletion.vue?raw'

function functionSource(name) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`))
  return source.slice(start, source.indexOf('\n}', start) + 2)
}

function harness() {
  const rows = [
    { canonical_rjcode: 'RJ01709662', release_date: '2026-09-22' },
    { canonical_rjcode: 'RJ01709000', release_date: '2026-09-22', has_bonus: true },
    { canonical_rjcode: 'RJ01709680', release_date: '2026-09-22', is_bonus_work: true },
    { canonical_rjcode: 'RJ01709999', release_date: '2098-10-01', original_release_date: '2026-09-22', is_unreleased: true },
  ]
  const api = {
    getCircleWorkCodes: vi.fn().mockResolvedValue({
      no_bonus_rjcodes: ['RJ01709662'],
      has_bonus_rjcodes: ['RJ01709000'],
      bonus_rjcodes: ['RJ01709680'],
      release_dates_by_rjcode: Object.fromEntries(rows.map(row => [
        row.canonical_rjcode, row.original_release_date || row.release_date,
      ])),
    }),
    startBonusProbe: vi.fn().mockResolvedValue({ job_id: 'probe' }),
  }
  const bindings = {
    selectedActiveCanonicalRJCodes: { value: rows.map(row => row.canonical_rjcode) },
    activeSelectableWorksByCanonical: { value: new Map(rows.map(row => [row.canonical_rjcode, row])) },
    activeCircleId: { value: 'circle' },
    isBonusDisplayWork: row => row.is_bonus_work,
    hasAttachedBonusWorks: row => row.has_bonus,
    circleCompletionApi: api,
    buildCircleWorksQuery: () => ({}),
    ElMessage: { warning: vi.fn() },
  }
  const names = [
    'isWorkUnreleased', 'normalizeReleaseDateForBonusProbe', 'getWorkBonusProbeDate',
    'getSelectedBonusProbeDates', 'startBonusProbeForCircle',
  ]
  const handlers = new Function(
    ...Object.keys(bindings),
    `${names.map(functionSource).join('\n')}\nreturn { getSelectedBonusProbeDates, startBonusProbeForCircle }`,
  )(...Object.values(bindings))
  return { ...handlers, api }
}

describe('特典结论永久复用与选中作品重查', () => {
  it('普通查询跳过已确认有特典、无特典、特典本体和未发售作品', async () => {
    const result = await harness().getSelectedBonusProbeDates()
    expect(result.dates).toEqual([])
    expect(result.skippedNoBonusCount).toBe(1)
    expect(result.skippedHasBonusCount).toBe(1)
    expect(result.skippedBonusCount).toBe(1)
  })

  it('强制查询只重查选中原作，保留未发售与特典本体过滤', async () => {
    const app = harness()
    const result = await app.getSelectedBonusProbeDates({ forceRefresh: true })
    expect(result.selectedRjcodesByDate).toEqual({
      '2026-09-22': ['RJ01709662', 'RJ01709000'],
    })
    await app.startBonusProbeForCircle('circle', {
      forceRefresh: true,
      releaseDates: result.dates,
      selectedRjcodesByDate: result.selectedRjcodesByDate,
    })
    expect(app.api.startBonusProbe).toHaveBeenCalledWith(expect.objectContaining({
      force_refresh: true,
      selected_rjcodes_by_date: result.selectedRjcodesByDate,
    }))
  })
})
