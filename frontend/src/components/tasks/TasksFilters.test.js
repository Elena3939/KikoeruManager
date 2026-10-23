import { describe, expect, it } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import TasksFilters from './TasksFilters.vue'
import { TASK_SUBTYPE_META, getTaskSubtypeMeta } from '../common/taskDomainMeta.js'

const mountFilters = (props = {}) => shallowMount(TasksFilters, {
  props: { getDomainCount: () => 0, ...props },
})

describe('社团任务二级筛选', () => {
  it('只在社团补全域显示并保留五种类型', async () => {
    const wrapper = mountFilters()
    expect(wrapper.findAllComponents({ name: 'AppDropdown' })).toHaveLength(3)
    await wrapper.setProps({ currentDomain: 'circle_completion' })
    const dropdowns = wrapper.findAllComponents({ name: 'AppDropdown' })
    expect(dropdowns).toHaveLength(4)
    expect(dropdowns[1].props('options').map(option => option.label)).toEqual([
      '全部任务', '社团索引', '作品状态刷新', '本地收录核对', '特典探测', '作品下载',
    ])
    dropdowns[1].vm.$emit('update:modelValue', 'owned_check')
    expect(wrapper.emitted('update:currentSubtype')).toEqual([['owned_check']])
    await wrapper.setProps({ currentDomain: 'http_download' })
    expect(wrapper.findAllComponents({ name: 'AppDropdown' })).toHaveLength(3)
  })

  it('三处任务展示共用同一类型与图标映射', () => {
    for (const [subtype, meta] of Object.entries(TASK_SUBTYPE_META)) {
      expect(getTaskSubtypeMeta({ subtype })).toBe(meta)
      expect(meta.icon).toBeTruthy()
    }
    expect(getTaskSubtypeMeta({ domain: 'http_download' })).toBeNull()
  })
})
