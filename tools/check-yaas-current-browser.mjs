import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mkdir } from 'node:fs/promises'

const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="app"></div><script type="module">
import {createApp,h,ref} from 'vue'
import {createPinia} from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '/src/index.css'
import '/src/dark-mode.css'
import Stage from '/src/components/library/subtitle-workbench/SubtitleTaskStage.vue'
import Settings from '/src/components/settings/HttpDownloadSettingsPanel.vue'
import {useSettingsDraft} from '/src/composables/useSettingsDraft'
import {useCircleSubtitleRepair} from '/src/composables/useCircleSubtitleRepair'
import RepairActions from '/src/components/circle/SubtitleRepairActions.vue'
import {createRouter,createMemoryHistory} from 'vue-router'
const task={id:'display-task',active_task_id:'real-task',status:'waiting_manual',task_metadata:{browser_verification_required:true}}
const work={canonical_rjcode:'RJ01168542',subtitle_repairable:true,subtitle_repair_sources:[{provider:'yaas',label:'字幕包'}]}
createApp({setup(){
  useCircleSubtitleRepair(ref('RG38133'),ref([work]))
  const rows=ref([task])
  const {config}=useSettingsDraft()
  config.value.http_downloader.pikpak_enabled=false
  config.value.http_downloader.proxy_platforms=['imoutoheaven']
  return ()=>h('main',{style:'padding:16px'},[
    h('div',{'data-testid':'circle-repair'},[h(RepairActions,{item:work})]),
    h(Stage,{mode:'overview',immersive:true,ctx:{
      activeSubtitleTask:rows.value[0],visibleSubtitleTasks:rows.value,
      refreshBrowserDownloadTasks:()=>{rows.value=[];window.refreshed=true}
    }}),
    h(Settings,{config:config.value})
  ])
}}).use(createPinia()).use(createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]})).use(ElementPlus).mount('#app')
window.ready=true
</script></body></html>`
const server = await createServer({
  root: resolve(root, 'frontend'),
  configFile: resolve(root, 'frontend/vite.config.js'),
  server: { host: '127.0.0.1', port: 0, hmr: false },
  plugins: [{
    name: 'yaas-popup-check',
    configureServer(server) {
      server.middlewares.use('/yaas-popup-check', async (req, res) => {
        res.setHeader('Content-Type', 'text/html; charset=utf-8')
        res.end(await server.transformIndexHtml('/yaas-popup-check', html))
      })
    },
  }],
})
let browser
try {
  await server.listen()
  browser = await chromium.launch({ channel: 'msedge', headless: true, ignoreDefaultArgs: ['--disable-popup-blocking'] })
  const output = resolve(root, 'data/yaas-current-browser-check')
  await mkdir(output, { recursive: true })
  for (const width of [1440, 390]) for (const dark of [false, true]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, acceptDownloads: true })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    let opens = 0, handoffs = 0, files = 0
    let created = false, handed = false, checks = 0
    await context.route('**/api/circle-completion/subtitle-repair/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/targets')) {
        // 超过普通浏览器的用户激活有效期，证明异步就绪后没有再次调用 window.open。
        await new Promise(done => setTimeout(done, 5500))
        return route.fulfill({ json: { items: [{ canonical_rjcode: 'RJ01168542', targets: [{ library_id: 'local', folder_path: '/RJ01168542', eligible: true }] }] } })
      }
      if (path.endsWith('/start')) {
        created = true
        return route.fulfill({ json: { created_count: 1, items: [{ task_id: 'created-task', state: 'created', status: 'pending' }] } })
      }
      const waiting = created && !handed
      if (waiting) checks++
      return route.fulfill({ json: { items: { RJ01168542: waiting ? [{
        task_id: 'created-task', status: checks > 1 ? 'waiting_manual' : 'processing', browser_verification_required: checks > 1,
      }] : [] } } })
    })
    await context.route('**/api/browser-verification/**', async route => {
      const path = new URL(route.request().url()).pathname
      assert.ok(path.includes('/task/real-task/') || path.includes('/task/created-task/'))
      if (path.endsWith('/open')) {
        opens++
        assert.equal(new URL(route.request().url()).searchParams.has('presentation'), false)
        await new Promise(done => setTimeout(done, 80))
        await route.fulfill({ json: { presentation: 'current_browser', verification_url: 'https://cdn.imoutoheaven.org/popup-fixture.zip' } })
      } else {
        assert.ok(path.endsWith('/handoff'))
        handoffs++
        if (path.includes('/task/created-task/')) handed = true
        await route.fulfill({ json: { success: true } })
      }
    })
    await context.route('https://cdn.imoutoheaven.org/popup-fixture.zip', route => {
      files++
      return route.fulfill({ contentType: 'application/zip', headers: { 'Content-Disposition': 'attachment; filename="popup-fixture.zip"' }, body: Buffer.from('browser-download-fixture') })
    })
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/yaas-popup-check`)
    await page.waitForFunction(() => window.ready)
    await page.evaluate(dark => {
      document.documentElement.classList.toggle('dark', dark)
      document.documentElement.classList.toggle('kikoerumanager-dark', dark)
    }, dark)
    await page.getByRole('button', { name: '浏览器下载' }).waitFor()
    assert.equal(opens, 0)
    assert.equal(await page.locator('.el-dialog').count(), 0)
    const popupPromise = page.waitForEvent('popup')
    const downloadPromise = new Promise(done => context.once('page', popup => popup.once('download', done)))
    await page.getByRole('button', { name: '浏览器下载' }).click()
    const popup = await popupPromise
    const download = await downloadPromise
    assert.equal(popup.context(), context)
    assert.equal(download.suggestedFilename(), 'popup-fixture.zip')
    const stream = await download.createReadStream()
    const chunks = []
    for await (const chunk of stream) chunks.push(chunk)
    assert.equal(Buffer.concat(chunks).toString(), 'browser-download-fixture')
    await page.waitForFunction(() => window.refreshed)
    assert.deepEqual({ opens, handoffs, files }, { opens: 1, handoffs: 1, files: 1 })
    assert.equal(await page.locator('.el-dialog').count(), 0)
    const createdPopupPromise = page.waitForEvent('popup')
    const createdDownloadPromise = new Promise(done => context.once('page', popup => popup.once('download', done)))
    await page.getByTestId('circle-repair').getByRole('button', { name: '可补配' }).click()
    const createdPopup = await createdPopupPromise
    assert.equal(created, false)
    assert.equal(createdPopup.context(), context)
    assert.equal(await createdPopup.title(), '正在准备下载')
    const createdDownload = await createdDownloadPromise
    assert.equal(createdDownload.suggestedFilename(), 'popup-fixture.zip')
    await page.waitForFunction(() => !document.querySelector('[data-testid="circle-repair"]').textContent.includes('浏览器下载'))
    assert.deepEqual({ opens, handoffs, files }, { opens: 2, handoffs: 2, files: 2 })
    await page.locator('.http-proxy-trigger').click()
    const option = page.locator('.app-dd-item').filter({ hasText: 'Cloudflare Turnstile' })
    await option.waitFor()
    assert.equal(await option.locator('img').getAttribute('alt'), 'Cloudflare')
    assert.ok(await option.locator('img').evaluate(img => img.complete && img.naturalWidth > 0))
    await page.screenshot({ path: resolve(output, `${width}-${dark ? 'dark' : 'light'}.png`) })
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ width, dark, popupBlockingEnabled: true, createToPopup: true, sameBrowserPopup: true, browserDownload: true, cleanedTask: true, officialIcon: true }))
    await context.close()
  }
} finally {
  await browser?.close()
  await server.close()
}
