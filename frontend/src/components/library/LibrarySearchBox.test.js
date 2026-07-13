import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('../../api', () => ({
  libraryApi: {
    searchIndexGlobal: vi.fn(() => new Promise(() => {})),
  },
}))

import LibrarySearchBox from './LibrarySearchBox.vue'

describe('LibrarySearchBox', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('鼠标进入搜索区域后失焦不会提前收起建议', async () => {
    const wrapper = mount(LibrarySearchBox, {
      props: { modelValue: 'RJ01624471' },
    })
    const input = wrapper.get('input')

    await input.trigger('focus')
    await wrapper.trigger('mouseenter')
    await input.trigger('blur')
    await vi.advanceTimersByTimeAsync(300)

    expect(wrapper.find('.lib-suggest-pop').exists()).toBe(true)

    await wrapper.trigger('mouseleave')
    await vi.advanceTimersByTimeAsync(280)

    expect(wrapper.find('.lib-suggest-pop').exists()).toBe(false)
    wrapper.unmount()
  })
})
