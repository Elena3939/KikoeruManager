import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useLibraryIndexStateStore } from '../../stores/libraryIndexState'

const { browserNavigationSnapshot, browserListFolders } = vi.hoisted(() => ({
  browserNavigationSnapshot: vi.fn(),
  browserListFolders: vi.fn(),
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
    searchIndexGlobalStream: vi.fn(),
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
})
