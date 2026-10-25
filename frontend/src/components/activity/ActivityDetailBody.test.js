import { expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ActivityDetailBody from './ActivityDetailBody.vue'

vi.mock('./ActivityRichBlock.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../common/AppEmptyState.vue', () => ({ default: { template: '<div />' } }))

it('父记录重试后显示最新活动时间，旧记录仍使用创建时间', async () => {
  const row = {
    id: 'parent', category: 'auto_import', created_at: '2026-10-19T10:00:00',
    latest_activity_at: '2026-10-20T12:00:00', detail: {},
  }
  const wrapper = mount(ActivityDetailBody, {
    props: { row, formatDateTime: (value) => value },
    global: { directives: { 'app-loading': {} } },
  })
  try {
    expect(wrapper.get('.subtitle-time').text()).toBe(row.latest_activity_at)
    await wrapper.setProps({ row: { ...row, latest_activity_at: null } })
    expect(wrapper.get('.subtitle-time').text()).toBe(row.created_at)
  } finally {
    wrapper.unmount()
  }
})

it('返回入口透传事件，恢复父级时保留关联事件展开和滚动位置', async () => {
  const parent = {
    id: 'batch', category: 'auto_import', detail: {
      child_rows: Array.from({ length: 8 }, (_, index) => ({
        id: `package-${index}`, action: 'task_finished', detail: {},
      })),
    },
  }
  const wrapper = mount(ActivityDetailBody, {
    props: { row: parent },
    global: {
      stubs: { ActivityRichBlock: true },
      directives: { 'app-loading': {} },
    },
  })
  try {
    expect(wrapper.find('.detail-back').exists()).toBe(false)
    await wrapper.get('.panel-toggle').trigger('click')
    await wrapper.get('.child-row').trigger('click')
    wrapper.get('.detail-scroll').element.scrollTop = 480
    const state = wrapper.vm.captureView()
    await wrapper.setProps({ row: { id: 'package-0', detail: {} }, canGoBack: true })
    await wrapper.get('.detail-back').trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)
    await wrapper.setProps({ row: parent, canGoBack: false })
    await wrapper.vm.restoreView(state)
    expect(wrapper.findAll('.child-item')).toHaveLength(8)
    expect(wrapper.get('.panel-toggle').text()).toContain('收起')
    expect(wrapper.find('.child-item.is-expanded').exists()).toBe(true)
    expect(wrapper.get('.detail-scroll').element.scrollTop).toBe(480)
    await wrapper.get('.panel-toggle').trigger('click')
    expect(wrapper.findAll('.child-item')).toHaveLength(6)
    expect(wrapper.get('.panel-toggle').text()).toContain('展开全部')
  } finally {
    wrapper.unmount()
  }
})

it('直接展示后端筛选结果与计数，返回父级保留筛选条件', async () => {
  const children = [
    { id: 'ok', summary: '正常入库', status: 'success', outcome: 'success', outcome_label: '解压入库成功', detail: {} },
    { id: 'duplicate', summary: '已转入问题作品', outcome: 'duplicate', outcome_label: '重复待处理', status: 'waiting', detail: {} },
  ]
  const parent = { id: 'root', detail: {
    child_rows: children,
    related_event_groups: [
      { key: 'all', label: '全部', count: 2, paths: [['detail', 'child_rows', 0], ['detail', 'child_rows', 1]] },
      { key: 'duplicate', label: '重复', count: 1, paths: [['detail', 'child_rows', 1]] },
    ],
  } }
  const wrapper = mount(ActivityDetailBody, {
    props: { row: parent },
    global: { directives: { 'app-loading': {} } },
  })
  try {
    expect(wrapper.findAll('.child-item')).toHaveLength(2)
    expect(wrapper.findAll('.child-rel')[0].text()).toBe('解压入库成功')
    await wrapper.findAll('.child-filter')[1].trigger('click')
    expect(wrapper.findAll('.child-item')).toHaveLength(1)
    expect(wrapper.get('.child-rel').text()).toBe('重复待处理')
    const state = wrapper.vm.captureView()
    await wrapper.setProps({ row: children[1] })
    await wrapper.setProps({ row: parent })
    await wrapper.vm.restoreView(state)
    expect(wrapper.get('.child-filter.is-active').text()).toContain('重复 1')
    expect(wrapper.findAll('.child-item')).toHaveLength(1)
  } finally {
    wrapper.unmount()
  }
})
