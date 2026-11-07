// 使用真实视口和虚拟器检查搜索定位，不连接业务 API。
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0}#app{height:100vh;overflow:auto}.test-panel{height:680px;padding:16px;display:flex;flex-direction:column}</style>
</head><body><div id="app"></div><script type="module">
import {createApp,h,reactive,nextTick} from 'vue'
import '/src/index.css'
import '/src/dark-mode.css'
import Viewport from '/src/components/circle/CircleWorksViewport.vue'
const makePage=page=>Array.from({length:100},(_,index)=>({
  canonical_rjcode:'RJ'+(page*100000+index),title:'定位测试作品 '+index,
  image_url:'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
}))
const state=reactive({items:makePage(1),currentPage:1,totalItems:200,mode:'card',pageSize:100,serverPaging:true,locatedCodes:new Set()})
createApp({setup:()=>()=>h('main',{class:'test-panel'},[
  h('header',{style:'height:80px;flex-shrink:0'},'社团作品搜索定位验证'),
  h(Viewport,state)
])}).mount('#app')
window.locate=async(mode,page,delayed)=>{
  state.mode=mode;state.locatedCodes=new Set();state.currentPage=page
  if(delayed)await new Promise(resolve=>setTimeout(resolve,80))
  state.items=makePage(page);await nextTick()
  state.locatedCodes=new Set(['RJ'+(page*100000+90)])
}
window.ready=true
</script></body></html>`

const server = await createServer({
  root: resolve(root, 'frontend'),
  configFile: resolve(root, 'frontend/vite.config.js'),
  server: { host: '127.0.0.1', port: 0, hmr: false },
  plugins: [{
    name: 'circle-work-location-check',
    configureServer(server) {
      server.middlewares.use('/location-check', async (req, res) => {
        res.setHeader('Content-Type', 'text/html; charset=utf-8')
        res.end(await server.transformIndexHtml('/location-check', html))
      })
    },
  }],
})
let browser
try {
  await server.listen()
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const out = resolve(root, 'data/circle-location-check')
  await mkdir(out, { recursive: true })
  for (const width of [1200, 390]) {
    await page.setViewportSize({ width, height: 900 })
    for (const mode of ['card', 'list']) {
      for (const delayed of [false, true]) {
        await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/location-check`)
        await page.waitForFunction(() => window.ready)
        if (width > 640) assert.equal(await page.locator('[data-work-index="90"]').count(), 0)
        await page.evaluate(({ mode, delayed }) => window.locate(mode, delayed ? 2 : 1, delayed), { mode, delayed })
        const target = page.locator('[data-work-index="90"]')
        await target.waitFor()
        await page.waitForFunction(() => !document.querySelector('.is-motion-active'))
        await page.waitForFunction(() => {
          const target = document.querySelector('[data-work-index="90"]')
          if (!target) return false
          const box = target.getBoundingClientRect()
          const scroller = target.closest('.circle-work-scroll') || document.querySelector('#app')
          const bounds = scroller.getBoundingClientRect()
          return box.top >= Math.max(0, bounds.top) - 1
            && box.bottom <= Math.min(innerHeight, bounds.bottom) + 1
            && box.left >= Math.max(0, bounds.left) - 1
            && box.right <= Math.min(innerWidth, bounds.right) + 1
        })
        assert.equal(await target.locator('.locate-flash').count(), 1)
        const result = await target.evaluate(element => {
          const box = element.getBoundingClientRect()
          return { top: Math.round(box.top), bottom: Math.round(box.bottom), scrollTop: document.querySelector('.circle-work-scroll')?.scrollTop }
        })
        console.log(JSON.stringify({ width, mode, delayed, ...result }))
        await page.screenshot({ path: resolve(out, `${width}-${mode}-${delayed ? 'cross-page' : 'same-page'}.png`) })
      }
    }
  }
  assert.deepEqual(errors, [])
} finally {
  await browser?.close()
  await server.close()
}
