import { describe, expect, it, vi } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import BrowserUploadBatch from './BrowserUploadBatch.vue'

vi.mock('../common/AppLottieProgressBar.vue', () => ({ default: { name: 'AppLottieProgressBar', template: '<div />' } }))
vi.mock('../common/AppEmptyState.vue', () => ({ default: { name: 'AppEmptyState', template: '<div />' } }))

const { restore } = vi.hoisted(() => ({ restore: vi.fn().mockResolvedValue(undefined) }))
vi.mock('../../composables/useBrowserUploads', () => ({
  controlBrowserUpload: vi.fn(), restoreBrowserUploadSource: restore,
  formatUploadBytes: value => `${value || 0} B`,
}))

function mountBatch(status, fields = {}) {
  return shallowMount(BrowserUploadBatch, {
    props: { session: {
      id: 'batch', status, source_label: '原目录', library_name: '默认库存', target_path: '/library/目标',
      enumerated: true, needsSource: true, total_files: 1, total_bytes: 100,
      liveReceived: 100, liveWritten: 100, counts: { completed: 1 }, files: new Map(), ...fields,
    } },
    global: { stubs: { ElCheckbox: true } },
  })
}

describe('浏览器上传详情', () => {
  it.each(['completed', 'cancelled'])('%s 不要求重选来源且不再显示传输进度条', status => {
    const wrapper = mountBatch(status)
    expect(wrapper.find('file-uploader-stub').exists()).toBe(false)
    expect(wrapper.find('app-lottie-progress-bar-stub').exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('完成 1')
    wrapper.unmount()
  })

  it('恢复上传复用来源选择组件，并传递原始文件', async () => {
    const wrapper = mountBatch('paused')
    const picker = wrapper.getComponent({ name: 'FileUploader' })
    expect(picker.props('selectionOnly')).toBe(true)
    const files = [new File(['abc'], '原文件.txt')]
    picker.vm.$emit('sources-selected', files)
    expect(restore).toHaveBeenCalledWith('batch', files)
    wrapper.unmount()
  })

  it('群晖传输保留两个独立阶段', () => {
    const wrapper = mountBatch('receiving', { target_type: 'synology_filestation', needsSource: false })
    expect(wrapper.text()).toContain('上传至服务')
    expect(wrapper.text()).toContain('写入群晖')
    expect(wrapper.findAll('app-lottie-progress-bar-stub')).toHaveLength(2)
    wrapper.unmount()
  })

  it('枚举期间不显示确定的百分比', () => {
    const wrapper = mountBatch('receiving', { enumerated: false, discoveredFiles: 17 })
    expect(wrapper.text()).toContain('已发现 17 个文件')
    expect(wrapper.find('app-lottie-progress-bar-stub').exists()).toBe(false)
    wrapper.unmount()
  })
})
