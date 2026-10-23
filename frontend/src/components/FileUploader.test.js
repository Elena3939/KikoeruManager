import { describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import FileUploader from './FileUploader.vue'

const { listLibraries } = vi.hoisted(() => ({ listLibraries: vi.fn().mockResolvedValue({ libraries: [] }) }))
vi.mock('../api', () => ({ libraryApi: { listLibraries }, apiFetchOptions: vi.fn(), apiUrl: vi.fn() }))

describe('上传来源选择模式', () => {
  it('选择目录不请求库存，不进入解压处理', async () => {
    const wrapper = shallowMount(FileUploader, { props: { selectionOnly: true } })
    expect(listLibraries).not.toHaveBeenCalled()
    expect(wrapper.find('input[webkitdirectory]').exists()).toBe(true)
    const input = wrapper.get('input[type="file"]')
    const files = [new File(['x'], '保留原名.7z')]
    Object.defineProperty(input.element, 'files', { value: files })
    await input.trigger('change')
    expect(wrapper.emitted('sources-selected')[0][0]).toEqual(files)
    expect(wrapper.text()).not.toContain('开始处理')
    wrapper.unmount()
  })

  it('拖入文件夹保留目录 entry，不在拖拽时枚举', async () => {
    const wrapper = shallowMount(FileUploader, { props: { selectionOnly: true } })
    const entry = { isDirectory: true, name: '原目录', createReader: vi.fn() }
    await wrapper.trigger('drop', { dataTransfer: { items: [{ kind: 'file', webkitGetAsEntry: () => entry }] } })
    expect(wrapper.emitted('sources-selected')[0][0]).toEqual([entry])
    expect(entry.createReader).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
