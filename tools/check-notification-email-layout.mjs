import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { readFile, mkdir } from 'node:fs/promises'
const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const output = resolve(root, 'data/notification-email-check')
const fixture = JSON.parse(await readFile(resolve(output, 'preview.json'), 'utf8'))
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}#app{height:100vh;display:flex;--set-surface:#fff;--set-border:#ddd;--set-text-strong:#222}.kikoerumanager-dark #app{--set-surface:#171719;--set-border:#444;--set-text-strong:#eee}</style></head><body><div id="app"></div><script type="module">
import {createApp,h} from 'vue'
import '/src/index.css'
import '/src/dark-mode.css'
import Editor from '/src/components/settings/block-editor/NotificationBlockEditor.vue'
import {buildDefaultEmailBlocks} from '/src/components/settings/block-editor/defaultEmailTemplate.js'
createApp({render:()=>h(Editor,{initialBlocks:buildDefaultEmailBlocks()})}).mount('#app')
window.ready=true
</script></body></html>`
const server = await createServer({root:resolve(root,'frontend'),configFile:resolve(root,'frontend/vite.config.js'),server:{host:'127.0.0.1',port:0,hmr:false},plugins:[{name:'email-layout',configureServer(server){server.middlewares.use('/email-layout',async(req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/email-layout',html))})}}]})
let browser
try {
  await mkdir(output,{recursive:true})
  await server.listen()
  browser=await chromium.launch({channel:'msedge',headless:true})
  const page=await browser.newPage()
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/api/notifications/templates/preview-blocks',route=>route.fulfill({json:fixture}))
  for(const width of [1391,1920,390]) {
    await page.setViewportSize({width,height:900})
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/email-layout`)
    await page.waitForFunction(()=>window.ready)
    for(const dark of [false,true]) {
      await page.evaluate(dark=>{document.documentElement.classList.toggle('dark',dark);document.documentElement.classList.toggle('kikoerumanager-dark',dark)},dark)
      const bg=await page.locator('.blk-canvas-paper').evaluate(el=>getComputedStyle(el).backgroundColor)
      assert.equal(bg,'rgb(255, 255, 255)')
      await page.locator('.blk-prev-mask').waitFor({state:'detached'})
      await page.screenshot({path:resolve(output,`${width}-${dark?'dark':'light'}-editor.png`)})
      await page.getByRole('button',{name:'预览邮件',exact:true}).click()
      await page.locator('.blk-preview-frame').waitFor()
      await page.waitForTimeout(250)
      const bounds=await page.locator('.blk-preview-frame').boundingBox()
      assert.ok(bounds.height>500,JSON.stringify(bounds))
      await page.screenshot({path:resolve(output,`${width}-${dark?'dark':'light'}-preview.png`)})
      await page.getByRole('button',{name:'关闭',exact:true}).click()
      await page.locator('.blk-prev-mask').waitFor({state:'detached'})
      console.log(JSON.stringify({width,dark,paper:bg,iframeHeight:bounds.height}))
    }
  }
  assert.deepEqual(errors,[])
} finally {await browser?.close();await server.close()}
