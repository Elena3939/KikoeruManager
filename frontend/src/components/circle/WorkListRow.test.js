import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorkListRow from './WorkListRow.vue'

const item = {
  canonical_rjcode: 'RJ01486845',
  display_rjcode: 'RJ01486845',
  image_url: '/api/circle-completion/cover/RJ01486845.jpg',
  thumb_image_url: '/api/circle-completion/cover/RJ01486845_sam.jpg',
}
function mountRow(props = {}) {
  return mount(WorkListRow, {
    props: { item, imageField: 'thumb_image_url', ...props },
    global: { stubs: { SubtitleRepairActions: true, ExternalSearchSourceChips: true } },
  })
}

describe('WorkListRow 本地封面', () => {
  it('旧 CDN 地址只用于提取图片 RJ，实际请求本地缩略图 API', () => {
    const wrapper = mountRow({
      item: {
        canonical_rjcode: 'RJ01669824',
        thumb_image_url: 'https://img.dlsite.jp/modpub/images2/work/doujin/RJ01487000/RJ01486845_img_sam.jpg',
      },
    })
    expect(wrapper.get('img').attributes('src')).toBe(item.thumb_image_url)
    wrapper.unmount()
  })

  it('没有图片地址时也通过本地 API 获取并持久化列表图', () => {
    const wrapper = mountRow({ item: { canonical_rjcode: 'RJ01486845' } })
    expect(wrapper.get('img').attributes('src')).toBe(item.thumb_image_url)
    wrapper.unmount()
  })

  it('已有绝对缓存地址统一使用当前服务的本地 API', () => {
    const wrapper = mountRow({ coverUrlOverride: `https://old.example${item.thumb_image_url}?v=123` })
    expect(wrapper.get('img').attributes('src')).toBe(`${item.thumb_image_url}?v=123`)
    wrapper.unmount()
  })

  it('即使作品字段给出大图，列表仍只请求本地小图', () => {
    const wrapper = mountRow({
      item: { ...item, thumb_image_url: '/api/circle-completion/cover/RJ01486845.jpg' },
    })
    expect(wrapper.get('img').attributes('src')).toBe(item.thumb_image_url)
    wrapper.unmount()
  })

  it('本地列表小图失败后显示重新获取按钮，不切换请求大图', async () => {
    const wrapper = mountRow()
    await wrapper.get('img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.emitted('image-failed')).toHaveLength(1)
    await wrapper.get('.wlr-thumb-retry').trigger('click')
    expect(wrapper.emitted('retry-cover')[0][0]).toEqual(item)
    wrapper.unmount()
  })

  it('缓存覆盖地址指向大图时也规范为列表小图', () => {
    const wrapper = mountRow({
      coverUrlOverride: '/api/circle-completion/cover/RJ01486845.jpg?v=123',
    })
    expect(wrapper.get('img').attributes('src')).toBe(`${item.thumb_image_url}?v=123`)
    wrapper.unmount()
  })
})
