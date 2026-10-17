import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { reactive } from 'vue'
import ServicesSettingsPanel from './ServicesSettingsPanel.vue'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import { configApi } from '../../api'

vi.mock('../../assets/anime/Visibility.lottie', () => ({ default: '' }))
vi.mock('../../assets/anime/VisibilityDark.lottie', () => ({ default: '' }))
vi.mock('@lottiefiles/dotlottie-vue', () => ({ DotLottieVue: { template: '<span />' } }))

vi.mock('../../api', () => ({
  configApi: { revealEmailWatcherSecret: vi.fn() },
  circleCompletionApi: {},
  kikoeruApi: {},
  emailWatcherApi: {},
}))

let wrapper
afterEach(() => wrapper?.unmount())

function setup(password = '********') {
  const config = reactive({
    kikoeru_server: {}, metadata: {}, bonus_probe: {},
    asmr_sync: { lrc_clean_patterns: [] }, rj_subtitle: {},
    email_watcher: { username: 'test@example.com', password, proxy_url: 'socks5h://proxy.example:7890' },
  })
  wrapper = shallowMount(ServicesSettingsPanel, {
    props: { config },
    global: {
      renderStubDefaultSlot: true,
      stubs: { AnimatedPasswordInput: false },
    },
  })
  const input = wrapper.findAllComponents(AnimatedPasswordInput)
    .find((item) => item.props('placeholder').startsWith('Gmail'))
  return { config, input }
}

describe('邮件监听凭据展示', () => {
  it('代理明文展示，已保存授权码点击眼睛后读取并可重新隐藏', async () => {
    configApi.revealEmailWatcherSecret.mockResolvedValue({ value: 'saved-app-code' })
    const { config, input } = setup()
    const proxy = wrapper.get('input[placeholder^="例如 socks5h"]')
    expect(proxy.attributes('type')).toBe('text')
    expect(proxy.element.value).toBe(config.email_watcher.proxy_url)
    await input.get('button').trigger('click')
    await flushPromises()
    expect(configApi.revealEmailWatcherSecret).toHaveBeenCalledWith({ key: 'password' })
    expect(input.get('input').element.value).toBe('saved-app-code')
    expect(config.email_watcher.password).toBe('********')
    await input.get('button').trigger('click')
    expect(input.get('input').attributes('type')).toBe('password')
    expect(input.get('input').element.value).toBe('********')
  })

  it('新输入的授权码直接展示，不被磁盘值覆盖', async () => {
    const { input } = setup('new-app-code')
    await input.get('button').trigger('click')
    expect(input.get('input').element.value).toBe('new-app-code')
    expect(configApi.revealEmailWatcherSecret).not.toHaveBeenCalled()
  })

  it('切换账号后丢弃尚未返回的旧授权码', async () => {
    let resolve
    configApi.revealEmailWatcherSecret.mockReturnValue(new Promise((done) => { resolve = done }))
    const { config, input } = setup()
    await input.get('button').trigger('click')
    config.email_watcher.username = 'other@example.com'
    resolve({ value: 'old-account-code' })
    await flushPromises()
    expect(input.get('input').element.value).toBe('********')
  })
})
