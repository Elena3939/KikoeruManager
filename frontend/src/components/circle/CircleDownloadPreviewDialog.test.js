import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import CircleDownloadPreviewDialog from './CircleDownloadPreviewDialog.vue'
import DownloadSourceComparison from './DownloadSourceComparison.vue'

vi.mock('../../api', () => ({ configApi: { get: vi.fn().mockResolvedValue({}) }, libraryApi: {} }))
vi.mock('../common/AppLoadingAnimation.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../common/RemoteFolderPickerDialog.vue', () => ({ default: { template: '<div />' } }))

const resource = id => ({
  id, rjcode: 'RJ123456', name: id, download_name: `${id}(south-plus).rar`,
  relative_path: `${id}.rar`, size_bytes: 10, complete: true, files: [{}], selected: false
})
const yaas = () => ({
  download_root: 'D:/http-downloads', source_provider: 'imoutoheaven', rjcode: 'RJ123456',
  selectable_resources: [resource('包甲'), resource('包乙')]
})
const asmr = (rjcode = 'RJ123456') => ({
  source_provider: 'asmr.one', session_id: `会话-${rjcode}`, rjcode, canonical_rjcode: 'RJ123456',
  language_label: rjcode === 'RJ123456' ? '日语' : '简体中文',
  selectable_resources: [{ id: `${rjcode}-audio`, relative_path: `${rjcode}.wav`, size_bytes: 10, selected: true }]
})
const multipleSources = (rjcode = 'RJ123456') => ({
  ...asmr(rjcode), source_selection_required: true, source_options: [asmr(rjcode), { ...yaas(), rjcode }]
})
function dialog(plans, settings = { targetLibraryId: 'library' }) {
  return mount(CircleDownloadPreviewDialog, {
    props: { plans, settings, visible: true },
    global: { stubs: {
      ElDialog: { template: '<div><slot /></div>' },
      AppDropdown: true, RemoteFolderPickerDialog: true, AppLoadingAnimation: true
    } }
  })
}

describe('资源站下载预览', () => {
  it.each([0, 1])('只选语言版本 %i 即可下载，未选来源的关联版本不阻塞提交', async index => {
    const wrapper = dialog([multipleSources(), multipleSources('RJ234567')])
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeDefined()
    await wrapper.findAll('.plan-node-header .tree-checkbox')[index].trigger('click')
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.summary').text()).not.toContain('待选择来源')
    await wrapper.find('.primary-cta').trigger('click')
    const items = wrapper.emitted('submit')[0][0].items
    expect(items).toHaveLength(1)
    expect(items[0].rjcode).toBe(index ? 'RJ234567' : 'RJ123456')
    expect(items[0].session_id).toBe(`会话-${items[0].rjcode}`)
    expect(items[0].selected_resources.map(item => item.id)).toEqual([`${items[0].rjcode}-audio`])
    wrapper.unmount()
  })

  it('两个语言可分别勾选，取消一个版本后仅提交另一个', async () => {
    const wrapper = dialog([multipleSources(), multipleSources('RJ234567')])
    await wrapper.findAll('.plan-node-header .tree-checkbox')[0].trigger('click')
    await wrapper.findAll('.plan-node-header .tree-checkbox')[1].trigger('click')
    expect(wrapper.find('.work-language-count').text()).toContain('已选 2')
    await wrapper.findAll('.plan-node-header .tree-checkbox')[0].trigger('click')
    expect(wrapper.find('.work-language-count').text()).toContain('已选 1')
    await wrapper.find('.primary-cta').trigger('click')
    expect(wrapper.emitted('submit')[0][0].items.map(item => item.rjcode)).toEqual(['RJ234567'])
    await wrapper.findAll('.plan-node-header .tree-checkbox')[1].trigger('click')
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('交错排列的语言按原作归组，统计作品数而非语言数量', () => {
    const wrapper = dialog([
      asmr(), { ...asmr('RJ345678'), canonical_rjcode: 'RJ345678' }, asmr('RJ234567')
    ])
    const groups = wrapper.findAll('.work-language-group')
    expect(groups).toHaveLength(2)
    expect(groups[0].findAll('.plan-node-header').map(row => row.text())).toEqual([
      expect.stringContaining('RJ123456'), expect.stringContaining('RJ234567')
    ])
    expect(groups[0].classes()).toContain('is-linked')
    expect(groups[0].classes()).toContain('has-selection')
    expect(groups[1].find('.work-language-heading').exists()).toBe(false)
    expect(wrapper.find('.site-heading-copy').text()).toContain('已选 2/2 部作品')
    wrapper.unmount()
  })

  it('文件级选择可以直接激活一个语言版本', async () => {
    const wrapper = dialog([multipleSources(), multipleSources('RJ234567')])
    await wrapper.findAll('.resource-file-row .tree-checkbox')[1].trigger('click')
    await wrapper.find('.primary-cta').trigger('click')
    expect(wrapper.emitted('submit')[0][0].items.map(item => item.rjcode)).toEqual(['RJ234567'])
    wrapper.unmount()
  })

  it('YAAS 只选一个完整压缩包，不要求选择另一语言或库存', async () => {
    const wrapper = dialog([multipleSources(), multipleSources('RJ234567')], {})
    wrapper.findComponent(DownloadSourceComparison).vm.$emit('update:modelValue', 'imoutoheaven')
    await wrapper.vm.$nextTick()
    await wrapper.findAll('.resource-file-row .tree-checkbox')[0].trigger('click')
    await wrapper.findAll('.resource-file-row .tree-checkbox')[1].trigger('click')
    expect(wrapper.findAll('.resource-file-row.tree-row-selected')).toHaveLength(1)
    expect(wrapper.find('.primary-cta').text()).toBe('下载原压缩包')
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeUndefined()
    await wrapper.find('.primary-cta').trigger('click')
    expect(wrapper.emitted('submit')[0][0].items).toEqual([{
      source_provider: 'imoutoheaven', rjcode: 'RJ123456', canonical_rjcode: 'RJ123456',
      download_base_path: '', selected_resources: [{ id: '包乙' }]
    }])
    wrapper.unmount()
  })

  it.each(['checkbox', 'row'])('YAAS 同名压缩包通过 %s 点击仍选择对应资源，切换和取消不串行', async target => {
    const name = 'RJ01407305(south-plus).rar'
    const plan = {
      ...yaas(),
      selectable_resources: [
        { ...resource('small'), download_name: name, size_bytes: 20677918 },
        { ...resource('large'), download_name: name, size_bytes: 158544691 }
      ]
    }
    const wrapper = dialog([plan], {})
    const clickPackage = async index => {
      const row = wrapper.findAll('.resource-file-row')[index]
      await (target === 'checkbox' ? row.find('.tree-checkbox') : row).trigger('click')
    }
    await clickPackage(1)
    expect(wrapper.findAll('.resource-file-row').map(row => row.classes().includes('tree-row-selected'))).toEqual([false, true])
    await wrapper.find('.primary-cta').trigger('click')
    expect(wrapper.emitted('submit')[0][0].items[0].selected_resources).toEqual([{ id: 'large' }])
    await clickPackage(0)
    expect(wrapper.findAll('.resource-file-row').map(row => row.classes().includes('tree-row-selected'))).toEqual([true, false])
    await clickPackage(1)
    await clickPackage(1)
    expect(wrapper.findAll('.resource-file-row.tree-row-selected')).toHaveLength(0)
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('asmr.one 已选文件仍要求配置目标库存', async () => {
    const wrapper = dialog([multipleSources()], {})
    await wrapper.find('.plan-node-header .tree-checkbox').trigger('click')
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('全选来源可提交全部语言版本', async () => {
    const wrapper = dialog([multipleSources(), multipleSources('RJ234567')])
    await wrapper.find('.site-select-button').trigger('click')
    await wrapper.find('.primary-cta').trigger('click')
    expect(wrapper.emitted('submit')[0][0].items.map(item => item.rjcode)).toEqual(['RJ123456', 'RJ234567'])
    await wrapper.find('.site-select-button').trigger('click')
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})
