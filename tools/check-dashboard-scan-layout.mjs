import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mkdir } from 'node:fs/promises'
const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:20px}html.kikoerumanager-dark body{background:#101012}</style></head><body><div id="app"></div><script type="module">
import {createApp,h} from 'vue'
import '/src/index.css'
import '/src/dark-mode.css'
import Strip from '/src/components/dashboard/DashboardCommandStrip.vue'
import Status from '/src/components/dashboard/DashboardScanStatus.vue'
const snapshot={scan_id:'sample',revision:1,message:'扫描完成',discovered_groups:7,found_count:3,counts:{skipped:4},skip_counts:{deferred_archive:3,task_waiting_retry:1}}
createApp({render:()=>h('main',{class:'dashboard-page-shell'},[h(Strip),h(Status,{snapshot,onCancel:async()=>{}})])}).mount('#app')
window.ready=true
</script></body></html>`
const server = await createServer({root:resolve(root,'frontend'),configFile:resolve(root,'frontend/vite.config.js'),server:{host:'127.0.0.1',port:0,hmr:false},plugins:[{name:'scan-layout',configureServer(server){server.middlewares.use('/scan-layout',async(req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/scan-layout',html))})}}]})
let browser
try {
  await server.listen()
  browser=await chromium.launch({channel:'msedge',headless:true})
  const page=await browser.newPage()
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/api/scan/sample/candidates*',route=>route.fulfill({json:[{id:'a',source_path:'/down_anime/百度网盘_20261101_200323/RJ01435183.7z.001',state:'skipped',reason:'task:owner'},{id:'b',source_path:'/down_anime/百度网盘_20261102_221801/RJ01606244.zip',state:'skipped',reason:'deferred_archive:owner'}]}))
  const output=resolve(root,'data/dashboard-scan-layout')
  await mkdir(output,{recursive:true})
  for(const width of [390,1280]) {
    await page.setViewportSize({width,height:720})
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/scan-layout`)
    await page.waitForFunction(()=>window.ready)
    await page.getByRole('button',{name:'扫描明细'}).click()
    await page.getByText('归档占用',{exact:true}).waitFor()
    for(const dark of [false,true]) {
      await page.evaluate(dark=>{document.documentElement.classList.toggle('dark',dark);document.documentElement.classList.toggle('kikoerumanager-dark',dark)},dark)
      await page.waitForTimeout(500)
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
      await page.screenshot({path:resolve(output,`${width}-${dark?'dark':'light'}.png`)})
      console.log(JSON.stringify({width,dark,overflow:false}))
    }
  }
  assert.deepEqual(errors,[])
} finally {await browser?.close();await server.close()}
