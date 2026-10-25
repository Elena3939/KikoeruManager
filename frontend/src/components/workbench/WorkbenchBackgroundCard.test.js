import { describe, expect, it } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import WorkbenchBackgroundCard from './WorkbenchBackgroundCard.vue'

describe('各类工作台与小窗状态交互', () => {
  it.each(['upload', 'download', 'subtitle', 'generic'])('%s 状态切换同步进度、元信息和操作', async type => {
    const workbench = { id: type, type, title: '任务', status: { key: 'processing' }, progress: { percentage: 42 }, metrics: [{ key: 'speed', label: '速度', value: '12 MiB/s' }], actions: ['resume', 'close'] }
    const wrapper = shallowMount(WorkbenchBackgroundCard, { props: { workbench } })
    const card = () => wrapper.findComponent({ name: 'BackgroundFloatingCard' })
    expect(card().props('percentage')).toBe(42)
    expect(card().props('metrics')[0].value).toBe('12 MiB/s')
    for (const [key, suffix, completed] of [['completed', '已完成', true], ['cancelled', '已取消', false], ['paused', '已暂停', false], ['failed', '需要处理', false], ['awaiting', '等待处理', false]]) {
      await wrapper.setProps({ workbench: { ...workbench, status: { key, label: suffix }, progress: { percentage: completed ? 100 : 42 } } })
      expect(card().props('title')).toBe(`任务${suffix}`)
      expect(card().props('completed')).toBe(completed)
      expect(card().props('metaText')).toContain(suffix)
    }
    card().vm.$emit('action', 'resume')
    card().vm.$emit('action', 'close')
    expect(wrapper.emitted('action')).toEqual([['resume'], ['close']])
    wrapper.unmount()
  })
})
