import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorkCard from './WorkCard.vue'
import WorkListRow from './WorkListRow.vue'

const item = {
  canonical_rjcode: 'RJ01000001',
  display_rjcode: 'RJ01000001',
  title: '测试作品',
  cvs: [],
}

function dispatchMouseDown(wrapper, shiftKey) {
  const event = new MouseEvent('mousedown', { bubbles: true, cancelable: true, shiftKey })
  wrapper.get('article').element.dispatchEvent(event)
  return event.defaultPrevented
}

describe('社团补全范围选择', () => {
  it.each([
    ['卡片视图', WorkCard],
    ['列表视图', WorkListRow],
  ])('%s 会拦截 Shift 的浏览器文本选择', (_, component) => {
    const wrapper = mount(component, { props: { item } })

    expect(dispatchMouseDown(wrapper, true)).toBe(true)
    expect(dispatchMouseDown(wrapper, false)).toBe(false)

    wrapper.unmount()
  })
})
