import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ExternalSearchSourceChips from './ExternalSearchSourceChips.vue'

describe('ExternalSearchSourceChips', () => {
  it('固定显示真实站点图标，并保留南+未命中状态和搜索动作', async () => {
    const wrapper = mount(ExternalSearchSourceChips, {
      props: {
        item: {
          canonical_rjcode: 'RJ01576821',
          external_search: {
            anime_share: { status: 'loading', results: [], search_results: [] },
            south_plus: { status: 'miss', results: [], search_results: [] },
          },
        },
      },
    })

    const buttons = wrapper.findAll('.external-source-chip')
    expect(buttons).toHaveLength(2)
    expect(buttons[0].get('img').attributes('src')).toContain('anime-sharing')
    expect(buttons[1].get('img').attributes('src')).toContain('south-plus')
    expect(buttons[1].classes()).toContain('is-miss')
    expect(buttons[1].attributes('title')).toContain('未找到')

    await buttons[1].trigger('click')
    expect(wrapper.emitted('open')?.[0]?.[0]).toMatchObject({
      source: 'south_plus',
      status: 'miss',
    })
    expect(wrapper.emitted('open')?.[0]?.[0]?.results?.[0]?.url).toContain('keyword=RJ01576821')
  })
})
