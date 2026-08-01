import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useLibraryIndexStateStore } from '../../stores/libraryIndexState'

const { browserNavigationSnapshot, browserListFolders, searchIndex, searchIndexGlobalStream } = vi.hoisted(() => ({
  browserNavigationSnapshot: vi.fn(),
  browserListFolders: vi.fn(),
  searchIndex: vi.fn(),
  searchIndexGlobalStream: vi.fn(),
}))

vi.mock('../../api', () => ({
  libraryApi: {
    browserNavigationSnapshot,
    browserListFolders,
    browserMovePreview: vi.fn(),
    computeFolderSizes: vi.fn().mockResolvedValue({ results: [] }),
    getIndexStatus: vi.fn().mockResolvedValue({
      library_id: 'local-a',
      status: 'ready',
      total_entries: 3,
      active_generation: 2,
      view_revision: 4,
      accepted_seq: 0,
      materialized_seq: 0,
      state_revision: 1,
    }),
    searchIndex,
    searchIndexGlobalStream,
  },
}))

vi.mock('../common/AppEmptyState.vue', () => ({
  default: {
    template: '<div><slot /></div>',
  },
}))

import LibraryMoveDialog from './LibraryMoveDialog.vue'

describe('LibraryMoveDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    browserNavigationSnapshot.mockReset()
    browserListFolders.mockReset()
    searchIndex.mockReset()
    searchIndexGlobalStream.mockReset()
    searchIndexGlobalStream.mockImplementation(async function * () {})
    browserNavigationSnapshot.mockResolvedValue({
      index_available: true,
      browse_via_index: true,
      library_id: 'local-a',
      current_path: 'D:\\Library\\Circle',
      browse_root_path: 'D:\\Library',
      folders: [{
        name: 'RJ01000001',
        path: 'D:\\Library\\Circle\\RJ01000001',
        is_directory: true,
        size: 10,
        size_status: 'ready',
      }],
      tree_children: [
        {
          path: 'D:\\Library',
          relative_path: '',
          folders: [{ name: 'Circle', path: 'D:\\Library\\Circle', is_directory: true }],
        },
        {
          path: 'D:\\Library\\Circle',
          relative_path: 'Circle',
          folders: [{ name: 'RJ01000001', path: 'D:\\Library\\Circle\\RJ01000001', is_directory: true }],
        },
      ],
      index_view: {
        library_id: 'local-a',
        index_generation: 2,
        view_revision: 4,
        accepted_seq: 0,
        materialized_seq: 0,
      },
      view_token: 'local-a:2:4',
    })
  })

  it('打开深路径时使用一次版本化索引快照而不是磁盘目录接口', async () => {
    const wrapper = mount(LibraryMoveDialog, {
      props: {
        visible: false,
        sourceLibraryId: 'local-a',
        initialPath: 'D:\\Library\\Circle',
        items: [{
          name: 'RJ02000002',
          path: 'D:\\Library\\Source\\RJ02000002',
          is_directory: true,
        }],
        libraries: [{
          id: 'local-a',
          name: '本地库存',
          type: 'local',
          root_path: 'D:\\Library',
          writable: true,
        }],
      },
      global: {
        stubs: {
          ElDialog: {
            props: ['modelValue'],
            template: '<div v-if="modelValue"><slot /></div>',
          },
          LibraryMoveNavNode: true,
        },
      },
    })

    await wrapper.setProps({ visible: true })
    await flushPromises()

    expect(browserNavigationSnapshot).toHaveBeenCalledWith(
      'local-a',
      'D:\\Library\\Circle',
      expect.objectContaining({ includeFiles: true, includeAncestors: true }),
    )
    expect(browserListFolders).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('RJ01000001')
    wrapper.unmount()
  })

  it('拒绝晚到的旧索引快照并降级读取当前目录', async () => {
    const store = useLibraryIndexStateStore()
    store.recordIndexViews({
      index_view: {
        library_id: 'local-a',
        index_generation: 2,
        view_revision: 5,
      },
    })
    browserListFolders.mockResolvedValue({
      library_id: 'local-a',
      current_path: 'D:\\Library\\Circle',
      browse_root_path: 'D:\\Library',
      folders: [{
        name: 'RJ02000002',
        path: 'D:\\Library\\Circle\\RJ02000002',
        is_directory: true,
      }],
    })

    const wrapper = mount(LibraryMoveDialog, {
      props: {
        visible: false,
        sourceLibraryId: 'local-a',
        initialPath: 'D:\\Library\\Circle',
        items: [{
          name: 'RJ03000003',
          path: 'D:\\Library\\Source\\RJ03000003',
          is_directory: true,
        }],
        libraries: [{
          id: 'local-a',
          name: '本地库存',
          type: 'local',
          root_path: 'D:\\Library',
          writable: true,
        }],
      },
      global: {
        stubs: {
          ElDialog: {
            props: ['modelValue'],
            template: '<div v-if="modelValue"><slot /></div>',
          },
          LibraryMoveNavNode: true,
        },
      },
    })

    await wrapper.setProps({ visible: true })
    await flushPromises()

    expect(browserListFolders).toHaveBeenCalledWith(
      'local-a',
      'D:\\Library\\Circle',
      expect.objectContaining({ includeFiles: true }),
    )
    expect(wrapper.text()).toContain('RJ02000002')
    expect(wrapper.text()).not.toContain('RJ01000001')
    wrapper.unmount()
  })

  it('本地库存搜索直接使用索引并只提交防抖后的最终关键词', async () => {
    vi.useFakeTimers()
    searchIndex.mockResolvedValue({
      items: [{
        library_id: 'local-a',
        entry_type: 'dir',
        name: '目标社团',
        relative_path: '分类/目标社团',
        absolute_path: 'D:\\Library\\分类\\目标社团',
        source: 'index',
      }],
    })

    const wrapper = mount(LibraryMoveDialog, {
      props: {
        visible: false,
        sourceLibraryId: 'local-a',
        initialPath: 'D:\\Library\\Circle',
        items: [{
          name: 'RJ02000002',
          path: 'D:\\Library\\Source\\RJ02000002',
          is_directory: true,
        }],
        libraries: [{
          id: 'local-a',
          name: '本地库存',
          type: 'local',
          root_path: 'D:\\Library',
          writable: true,
        }],
      },
      global: {
        stubs: {
          ElDialog: {
            props: ['modelValue'],
            template: '<div v-if="modelValue"><slot /></div>',
          },
          LibraryMoveNavNode: true,
        },
      },
    })

    try {
      await wrapper.setProps({ visible: true })
      await flushPromises()
      await wrapper.find('.search-input').setValue('目')
      await vi.advanceTimersByTimeAsync(200)
      await wrapper.find('.search-input').setValue('目标社团')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()

      expect(searchIndex).toHaveBeenCalledTimes(1)
      expect(searchIndex).toHaveBeenCalledWith(expect.objectContaining({
        libraryId: 'local-a',
        name: '目标社团',
        entryType: 'dir',
        limit: 200,
      }))
      expect(searchIndexGlobalStream).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('目标社团')
      expect(wrapper.text()).toContain('分类')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('群晖库存搜索走真实远程搜索并显示跨目录结果', async () => {
    vi.useFakeTimers()
    browserNavigationSnapshot.mockResolvedValueOnce({
      index_available: false,
      browse_via_index: false,
    })
    browserListFolders.mockResolvedValueOnce({
      library_id: 'remote-library-4',
      current_path: '/ANIME/temp/asmr',
      browse_root_path: '/ANIME/temp/asmr',
      folders: [{
        name: '当前目录已有项',
        path: '/ANIME/temp/asmr/当前目录已有项',
        is_directory: true,
      }],
    })
    searchIndexGlobalStream.mockImplementation(async function * (options) {
      yield {
        type: 'initial',
        items: [],
        will_run_fallback: true,
      }
      yield {
        type: 'library',
        library_id: options.libraryIds[0],
        items: [{
          library_id: 'remote-library-4',
          library_type: 'synology_filestation',
          entry_type: 'dir',
          name: 'すいーとみるく',
          relative_path: '社团/すいーとみるく',
          absolute_path: '/ANIME/temp/asmr/社团/すいーとみるく',
          source: 'fallback',
        }],
        error: null,
      }
      yield { type: 'done', fallback_used: true, fallback_failed: [] }
    })

    const wrapper = mount(LibraryMoveDialog, {
      props: {
        visible: false,
        sourceLibraryId: 'remote-library-4',
        initialPath: '/ANIME/temp/asmr',
        items: [{
          name: 'RJ02000002',
          path: '/ASMR/RJ02000002',
          is_directory: true,
        }],
        libraries: [{
          id: 'remote-library-4',
          name: '群晖ANIME',
          type: 'synology_filestation',
          root_path: '/ANIME/temp/asmr',
          writable: true,
        }],
      },
      global: {
        stubs: {
          ElDialog: {
            props: ['modelValue'],
            template: '<div v-if="modelValue"><slot /></div>',
          },
          LibraryMoveNavNode: true,
        },
      },
    })

    try {
      await wrapper.setProps({ visible: true })
      await flushPromises()
      await wrapper.find('.search-input').setValue('すいーとみるく')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()

      expect(searchIndex).not.toHaveBeenCalled()
      expect(searchIndexGlobalStream).toHaveBeenCalledWith(expect.objectContaining({
        keyword: 'すいーとみるく',
        libraryIds: ['remote-library-4'],
        entryType: 'dir',
        limit: 200,
      }))
      expect(wrapper.text()).toContain('すいーとみるく')
      expect(wrapper.text()).toContain('社团')
      expect(wrapper.text()).not.toContain('没有匹配')
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })
})
