import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import CircleDownloadPreviewDialog from './CircleDownloadPreviewDialog.vue'

vi.mock('../../api', () => ({ configApi: { get: vi.fn().mockResolvedValue({}) }, libraryApi: {} }))
vi.mock('../common/AppLoadingAnimation.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../common/RemoteFolderPickerDialog.vue', () => ({ default: { template: '<div />' } }))

const resource = id => ({ id, rjcode: 'RJ123456', name: id, download_name: `${id}(south-plus).rar`, path: '/资源站/隐藏目录', relative_path: `${id}.rar`, size_bytes: 10, complete: true, files: [{}], selected: false })
const yaas = () => ({ download_root: 'D:/http-downloads', source_provider: 'imoutoheaven', rjcode: 'RJ123456', selectable_resources: [resource('包甲'), resource('包乙')] })
const asmr = () => ({ source_provider: 'asmr.one', session_id: '原会话', rjcode: 'RJ123456', selectable_resources: [{ id: 'audio', relative_path: 'a.wav', selected: true }] })
function dialog(plans) {
  return mount(CircleDownloadPreviewDialog, {
    props: { plans, settings: {}, visible: true },
    global: { stubs: { ElDialog: { template: '<div><slot /></div>' }, RemoteFolderPickerDialog: true, AppLoadingAnimation: true } }
  })
}

describe('资源站下载预览', () => {
  it('关联语言版本可切换且仍展示对应音轨', async () => {
    const original = { ...asmr(), language_label: '日文原版' }
    const translation = { ...asmr(), rjcode: 'RJ234567', session_id: '翻译会话', language_label: '简体中文',
      selectable_resources: [{ id: 'translated', relative_path: '中文音轨.wav', selected: true }] }
    const wrapper = dialog([{ ...original, version_options: [original, translation] }])
    expect(wrapper.findAll('.version-select-chip')).toHaveLength(2)
    expect(wrapper.find('.plan-node-header').exists()).toBe(true)
    await wrapper.findAll('.version-select-chip')[1].trigger('click')
    expect(wrapper.find('.version-select-chip.is-selected').text()).toContain('简体中文')
    expect(wrapper.text()).toContain('中文音轨.wav')
    expect(wrapper.find('.plan-node-header').exists()).toBe(true)
    wrapper.unmount()
  })

  it('多来源必须选择，再互斥选择一个压缩包且无需库存', async () => {
    const wrapper = dialog([{ ...asmr(), canonical_rjcode: 'RJ100000', source_selection_required: true, source_options: [asmr(), yaas()] }])
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.source-preview-pane')).toHaveLength(2)
    expect(wrapper.find('.download-source-comparison').exists()).toBe(true)
    expect(wrapper.find('.left-column').exists()).toBe(false)
    expect(wrapper.find('.tabs-row').exists()).toBe(false)
    expect(wrapper.findAll('.source-preview-pane')[0].text()).toContain('a.wav')
    expect(wrapper.findAll('.source-preview-pane')[1].text()).toContain('包甲(south-plus).rar')
    expect(wrapper.text()).not.toContain('/资源站/隐藏目录')
    expect(wrapper.findAll('.source-preview-pane')[1].find('.plan-node-header').exists()).toBe(false)
    await wrapper.findAll('.source-preview-pane')[1].find('.resource-file-row').trigger('click')
    expect(wrapper.find('.download-source-comparison').exists()).toBe(false)
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeDefined()
    expect(wrapper.find('input[readonly]').element.value).toBe('D:/http-downloads')
    await wrapper.findAll('.resource-file-row')[0].trigger('click')
    await wrapper.findAll('.resource-file-row')[1].trigger('click')
    expect(wrapper.findAll('.resource-file-row.tree-row-selected')).toHaveLength(1)
    expect(wrapper.find('.resource-file-row.tree-row-selected button').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('.resource-file-row.tree-row-selected').text()).toContain('包乙(south-plus).rar')
    expect(wrapper.find('.archive-package-icon').exists()).toBe(true)
    expect(wrapper.find('.archive-package-icon').attributes('style')).toContain('color: rgb(217, 119, 6)')
    expect(wrapper.text()).not.toContain('/资源站/隐藏目录')
    expect(wrapper.text()).toContain('asmr.one')
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeUndefined()
    await wrapper.find('.primary-cta').trigger('click')
    expect(wrapper.emitted('submit')[0][0].items).toEqual([{
      source_provider: 'imoutoheaven', rjcode: 'RJ123456', canonical_rjcode: 'RJ100000', selected_resources: [{ id: '包乙' }]
    }])
    wrapper.unmount()
  })

  it('切回 asmr.one 继续要求原库存配置', async () => {
    const wrapper = dialog([{ ...yaas(), source_selection_required: true, source_options: [asmr(), yaas()] }])
    await wrapper.findAll('.source-preview-pane')[0].trigger('click')
    expect(wrapper.find('.primary-cta').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})
