import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DashboardScanStatus from './DashboardScanStatus.vue'
import { scanApi } from '../../api'

vi.mock('../../api', () => ({ scanApi: { candidates: vi.fn() } }))
const snapshot = { scan_id: 'one', revision: 1, message: '扫描完成', discovered_groups: 7, found_count: 3, counts: { skipped: 4 }, skip_counts: { deferred_archive: 3, task_waiting_retry: 1 } }
const create = () => mount(DashboardScanStatus, { props: { snapshot, onCancel: vi.fn() } })

describe('扫描状态条', () => {
  it('展示跳过分类，展开前不请求明细', async () => {
    scanApi.candidates.mockReset().mockResolvedValue([{ id: 'a', state: 'skipped', reason: 'deferred_archive:job', source_path: '/input/a.zip' }])
    const wrapper = create()
    expect(wrapper.text()).toContain('归档占用 3 组')
    expect(wrapper.text()).toContain('等待重试占用 1 组')
    expect(scanApi.candidates).not.toHaveBeenCalled()
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(scanApi.candidates).toHaveBeenCalledWith('one', undefined)
    expect(wrapper.text()).toContain('/input/a.zip')
    wrapper.unmount()
  })
  it('切换扫描后忽略旧请求结果', async () => {
    let resolve
    scanApi.candidates.mockReset().mockReturnValueOnce(new Promise(done => { resolve = done })).mockResolvedValueOnce([])
    const wrapper = create()
    await wrapper.find('button').trigger('click')
    await wrapper.setProps({ snapshot: { ...snapshot, scan_id: 'two' } })
    resolve([{ id: 'old', source_path: '/old.zip' }])
    await flushPromises()
    expect(wrapper.text()).not.toContain('/old.zip')
    wrapper.unmount()
  })
  it('加载时有状态提示，按交接和等待区分颜色语义', async () => {
    let resolve
    scanApi.candidates.mockReset().mockReturnValueOnce(new Promise(done => { resolve = done }))
    const wrapper = create()
    await wrapper.find('button').trigger('click')
    expect(wrapper.text()).toContain('正在加载扫描明细')
    resolve([
      { id: 'sent', state: 'submitted', source_path: '/input/sent' },
      { id: 'wait', state: 'ready', source_path: '/input/wait' },
    ])
    await flushPromises()
    expect(wrapper.find('.is-submitted').text()).toBe('已交接')
    expect(wrapper.find('.is-waiting').text()).toBe('等待交接')
    expect(wrapper.find('.scan-details').exists()).toBe(true)
    wrapper.unmount()
  })
  it('刷新时保留原有行，并按进行中、等待、完成排序及更新颜色', async () => {
    let resolveRefresh
    scanApi.candidates.mockReset()
      .mockResolvedValueOnce([
        { id: 'done', state: 'submitted', task_status: 'completed', source_path: '/done' },
        { id: 'wait', state: 'ready', source_path: '/wait' },
        { id: 'active', state: 'submitted', task_status: 'processing', source_path: '/active' },
        { id: 'problem', state: 'routed', destination: 'problem', source_path: '/problem' },
      ])
      .mockReturnValueOnce(new Promise(done => { resolveRefresh = done }))
    const wrapper = create()
    await wrapper.find('button').trigger('click')
    await flushPromises()
    const paths = () => wrapper.findAll('.scan-file').map(node => node.text())
    expect(paths()).toEqual(['/active', '/wait', '/done', '/problem'])
    expect(wrapper.findAll('.scan-detail-row')[0].find('.is-waiting').text()).toBe('处理中')
    expect(wrapper.findAll('.scan-detail-row')[3].find('.is-failed').text()).toBe('已转入问题作品')
    const originalRow = wrapper.findAll('.scan-detail-row')[0].element
    await wrapper.setProps({ snapshot: { ...snapshot, revision: 2 } })
    expect(wrapper.text()).not.toContain('正在加载扫描明细')
    expect(wrapper.findAll('.scan-detail-row')[0].element).toBe(originalRow)
    resolveRefresh([
      { id: 'done', state: 'submitted', task_status: 'completed', source_path: '/done' },
      { id: 'wait', state: 'submitted', task_status: 'processing', source_path: '/wait' },
      { id: 'active', state: 'submitted', task_status: 'completed', source_path: '/active' },
      { id: 'problem', state: 'routed', destination: 'problem', source_path: '/problem' },
    ])
    await flushPromises()
    expect(paths()).toEqual(['/wait', '/done', '/active', '/problem'])
    expect(wrapper.findAll('.scan-detail-row')[2].find('.is-submitted').text()).toBe('已完成')
    wrapper.unmount()
  })
})
