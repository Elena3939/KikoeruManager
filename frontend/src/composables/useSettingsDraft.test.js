import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { useSettingsDraft } from './useSettingsDraft'

const store = vi.hoisted(() => ({ fetchConfig: vi.fn(), saveConfig: vi.fn() }))
vi.mock('../stores', () => ({ useConfigStore: () => store }))
vi.mock('../api', () => ({ configApi: { reload: vi.fn() } }))
vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn(), error: vi.fn() } }))

let wrapper
let draft
const copy = value => JSON.parse(JSON.stringify(value))
function setup() {
  wrapper = mount(defineComponent({
    setup() {
      draft = useSettingsDraft({ sectionKeyMap: { httpDownload: ['http_downloader'] }, debounceMs: 0 })
      return () => null
    }
  }))
}
beforeEach(() => vi.resetAllMocks())
afterEach(() => wrapper?.unmount())

describe('HTTP 代理范围保存', () => {
  it('保留服务端已有 YAAS 勾选', async () => {
    store.fetchConfig.mockResolvedValue({ http_downloader: { proxy_platforms: ['http', 'imoutoheaven'] } })
    setup()
    await draft.loadConfig()
    expect(draft.config.value.http_downloader.proxy_platforms).toEqual(['http', 'imoutoheaven'])
    expect(draft.hasChanges.value).toBe(false)
  })

  it('仅修改 YAAS 时标记已改，保存后重新加载仍然勾选', async () => {
    let persisted = { http_downloader: { proxy_platforms: ['http'] } }
    store.fetchConfig.mockImplementation(async () => copy(persisted))
    store.saveConfig.mockImplementation(async payload => { persisted = copy(payload); return { success: true } })
    setup()
    await draft.loadConfig()
    draft.config.value.http_downloader.proxy_platforms.push('imoutoheaven')
    await vi.waitFor(() => expect(draft.hasChanges.value).toBe(true))
    expect(draft.dirtyMap.value.httpDownload).toBe(true)
    await draft.saveConfig()
    expect(store.saveConfig.mock.calls[0][0].http_downloader.proxy_platforms).toEqual(['http', 'imoutoheaven'])
    expect(draft.hasChanges.value).toBe(false)
    await draft.loadConfig()
    expect(draft.config.value.http_downloader.proxy_platforms).toEqual(['http', 'imoutoheaven'])
    expect(draft.dirtyMap.value.httpDownload).toBe(false)
  })

  it('显式取消全部代理来源后保持空数组，不恢复默认勾选', async () => {
    store.fetchConfig.mockResolvedValue({ http_downloader: { proxy_platforms: [] } })
    setup()
    await draft.loadConfig()
    await draft.saveConfig()
    await flushPromises()
    expect(store.saveConfig.mock.calls[0][0].http_downloader.proxy_platforms).toEqual([])
  })
})
