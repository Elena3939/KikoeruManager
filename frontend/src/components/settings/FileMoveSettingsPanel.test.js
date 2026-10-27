import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import FileMoveSettingsPanel from './FileMoveSettingsPanel.vue'
import AppDropdown from '../common/AppDropdown.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import { fileMoveApi } from '../../api'

vi.mock('../../api', () => ({ fileMoveApi: { status: vi.fn(), probe: vi.fn() } }))

let wrapper
let config
const running = () => ({
  enabled: false, online: true, ready: true,
  settings: { host_enabled: false, filter_verify_hashes: false, socket_path: '/socket', request_timeout_seconds: 30, journal_path: '' },
  roots: [{ path: '/source' }, { path: '/target' }],
  service: { mapping_version: 'v1' },
  journal: { sampled: 0, states: {} }
})

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  config = reactive({ file_move: { ...running().settings } })
  fileMoveApi.status.mockResolvedValue(running())
})
afterEach(() => { wrapper?.unmount(); vi.useRealTimers() })

async function openPanel() {
  wrapper = mount(FileMoveSettingsPanel, {
    props: { config },
    global: { stubs: { StatefulButton: { template: '<button v-bind="$attrs"><slot /></button>' } } }
  })
  await flushPromises()
}

describe('文件移动设置运行态', () => {
  it('复制和克隆共用过滤哈希开关并记录未保存变更', async () => {
    await openPanel()
    const toggle = wrapper.findAllComponents(SettingsToggleRow)
      .find(row => row.props('title') === '过滤文件搬运 SHA-256 校验')
    expect(toggle.props('modelValue')).toBe(false)
    toggle.vm.$emit('update:modelValue', true)
    await flushPromises()
    expect(config.file_move.filter_verify_hashes).toBe(true)
    expect(wrapper.text()).toContain('参数有未保存变更')
    expect(wrapper.text()).toContain('流式复制和快速克隆共用此开关')
  })

  it('展示并允许选择未被当前业务配置选中的挂载目录', async () => {
    const status = running()
    status.roots.push({ path: '/anime_dowm', configured: false, mapped: true, available: true, exists: true })
    fileMoveApi.status.mockResolvedValue(status)
    fileMoveApi.probe.mockResolvedValue({ method: '快速克隆', mapping_version: 'v1' })
    await openPanel()
    expect(wrapper.text()).toContain('/anime_dowm')
    expect(wrapper.findAllComponents(AppDropdown)[0].props('options'))
      .toContainEqual({ value: '/anime_dowm', label: '/anime_dowm' })
    wrapper.findAllComponents(AppDropdown)[0].vm.$emit('update:modelValue', '/anime_dowm')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('检查文件系统')).trigger('click')
    await flushPromises()
    expect(fileMoveApi.probe).toHaveBeenCalledWith('/anime_dowm', '/target')
  })

  it('区分服务在线、应用关闭与未保存开关', async () => {
    await openPanel()
    expect(wrapper.text()).toContain('当前配置：未启用')
    expect(wrapper.text()).toContain('执行器：在线')
    config.file_move.host_enabled = true
    await flushPromises()
    expect(wrapper.text()).toContain('参数有未保存变更')
    expect(wrapper.text()).toContain('当前配置：未启用')
  })

  it('目录改变后清除旧诊断，失败显示服务错误', async () => {
    fileMoveApi.probe.mockResolvedValue({ method: '快速克隆', mapping_version: 'v1' })
    await openPanel()
    await wrapper.findAll('button').find(button => button.text().includes('检查文件系统')).trigger('click')
    await flushPromises()
    expect(fileMoveApi.probe).toHaveBeenCalledWith('/source', '/target')
    expect(wrapper.text()).toContain('跨挂载时预计使用：快速克隆')
    wrapper.findAllComponents(AppDropdown)[1].vm.$emit('update:modelValue', '/source')
    await flushPromises()
    expect(wrapper.text()).not.toContain('跨挂载时预计使用')
    await wrapper.findAll('button').find(button => button.text().includes('检查文件系统')).trigger('click')
    await flushPromises()
    expect(fileMoveApi.probe).toHaveBeenLastCalledWith('/source', '/source')
    fileMoveApi.status.mockRejectedValue(new Error('服务无法连接'))
    await wrapper.findAll('button').find(button => button.text().includes('刷新状态')).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('服务无法连接')
  })

  it('卸载后停止轮询', async () => {
    await openPanel()
    wrapper.unmount()
    wrapper = null
    await vi.advanceTimersByTimeAsync(30000)
    expect(fileMoveApi.status).toHaveBeenCalledTimes(1)
  })
})
