import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

vi.mock('../../api', () => ({
  libraryApi: {
    getIndexStatus: vi.fn(() => new Promise(() => {})),
    rebuildIndex: vi.fn(),
  },
}))

vi.mock('../../composables/useSystemPrompt', () => ({
  showSystemAlert: vi.fn(),
  showSystemConfirm: vi.fn(),
}))

import LibraryIndexBadge from './LibraryIndexBadge.vue'
import { useLibraryIndexStateStore } from '../../stores/libraryIndexState'

describe('LibraryIndexBadge', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('accepted 水位领先时展示后台追赶而不是 ready', () => {
    const store = useLibraryIndexStateStore()
    store.applyStatusSnapshot({
      library_id: 'A',
      state_revision: 2,
      status: 'ready',
      accepted_seq: 8,
      materialized_seq: 5,
      total_entries: 12,
    }, 'sse')

    const wrapper = mount(LibraryIndexBadge, {
      props: { library: { id: 'A', name: '库存 A', type: 'local' } },
      global: {
        stubs: {
          Badge: { template: '<div><slot /></div>' },
          IconDatabase: true,
          IconRefreshCw: true,
        },
      },
    })

    expect(wrapper.text()).toContain('后台追赶')
    expect(wrapper.text()).toContain('3 项')
    expect(wrapper.text()).not.toContain('索引就绪')
  })
})
