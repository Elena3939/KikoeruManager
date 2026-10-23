import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import DownloadResourceTree from './DownloadResourceTree.vue'

const plan = { rjcode: '原根目录', rootExpanded: true, expandedIds: new Set(), flatRows: [{id:'f',type:'file',name:'文件.txt',depth:0,size_bytes:12}] }
describe('共享文件树展示模式', () => {
  it('隐藏额外根节点时直接平铺文件且支持传输详情', () => {
    const wrapper = mount(DownloadResourceTree, {props:{plan,readonly:true,hideRoot:true},slots:{'row-detail':'传输详情','row-action':'已完成'}})
    expect(wrapper.find('.plan-node-header').exists()).toBe(false)
    expect(wrapper.get('.resource-file-row').attributes('style')).toContain('padding-left: 8px')
    expect(wrapper.text()).toContain('传输详情')
    expect(wrapper.text()).toContain('已完成')
    wrapper.unmount()
  })
  it('默认模式保持根目录和文件大小', () => {
    const wrapper = mount(DownloadResourceTree,{props:{plan,readonly:true}})
    expect(wrapper.get('.plan-node-header').text()).toContain('原根目录')
    expect(wrapper.get('.resource-file-row').text()).toContain('12 B')
    wrapper.unmount()
  })
})
