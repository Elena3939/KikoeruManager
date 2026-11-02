// 用真实详情组件检查长文件名、失败条目和窄抽屉，不读写业务数据。
import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mkdir } from 'node:fs/promises'

const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0}.activity-detail-panel{width:100%;max-width:960px;margin:auto}</style>
</head><body><div id="app"></div><script type="module">
import {createApp,h,ref} from 'vue'
import '/src/index.css'
import '/src/dark-mode.css'
import Detail from '/src/components/activity/ActivityDetailBody.vue'
const names=['RJ01741823(nan+).7z','[09] RJ01556272 (ywind130).请勿在线解压.7z','超长文件名称'.repeat(16)+'.7z']
const row=ref({id:'6bd4edfb-a350-42d0-939a-6671b5c6517f',task_id:'ac5e009e-075d-4319-8c9b-a35dc68be82b',category:'baidu_netdisk',category_label:'百度网盘',action:'download_finished',status:'success',summary:'百度网盘 下载 3 个文件 / 11.68 GB / 平均 9.32 MB/s / 耗时 7 分 14 秒',source_path:'pan.baidu.com',output_path:'/down_anime/百度网盘_20261102_223119',detail:{duration_ms:435000,success_count:3,downloaded_bytes:12541304504,download_root:'/down_anime',final_output_path:'/down_anime/百度网盘_20261102_223119',download_files:names.map((name,i)=>({name:'原始文件-'+i+'.7z',original_relative_path:'原始文件-'+i+'.7z',relative_path:name,local_path:'/down_anime/百度网盘_20261102_223119/'+name,status:'completed',size:4252017623,downloaded:4252017623,total:4252017623,has_extract_password:true})),failed_files:[{name:'失败文件.7z',relative_path:'失败文件.7z',status:'failed',size:1024,failure_reason:'远程下载失败：'+ '错误详情'.repeat(40)}]}})
window.layoutRow=row
createApp({setup:()=>()=>h('div',{class:'activity-detail-panel'},h(Detail,{row:row.value}))}).directive('app-loading',{}).mount('#app')
window.ready=true
</script></body></html>`
const server = await createServer({
  root: resolve(root, 'frontend'),
  configFile: resolve(root, 'frontend/vite.config.js'),
  server: { host: '127.0.0.1', port: 0, hmr: false },
  plugins: [{
    name: 'activity-baidu-layout',
    configureServer(server) {
      server.middlewares.use('/layout-check', async (req, res) => {
        res.setHeader('Content-Type', 'text/html; charset=utf-8')
        res.end(await server.transformIndexHtml('/layout-check', html))
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
  const output = resolve(root, 'data/activity-baidu-layout')
  await mkdir(output, { recursive: true })
  for (const width of [390, 480, 639, 640, 800, 960]) {
    await page.setViewportSize({ width, height: 1200 })
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/layout-check`)
    await page.waitForFunction(() => window.ready)
    for (const dark of [false, true]) {
      await page.evaluate(dark => {
        document.documentElement.classList.toggle('dark', dark)
        document.documentElement.classList.toggle('kikoerumanager-dark', dark)
      }, dark)
      const result = await page.evaluate(() => {
        const bad = []
        const rect = el => el.getBoundingClientRect()
        for (const row of document.querySelectorAll('.baidu-file-section .tree-row')) {
          const bounds = rect(row)
          for (const el of row.querySelectorAll('.entry-name,.entry-inline-badge,.entry-detail-field dd,.entry-size,.entry-error')) {
            const box = rect(el)
            if (box.left < bounds.left - 1 || box.right > bounds.right + 1 || el.scrollWidth > el.clientWidth + 1) bad.push(el.textContent)
          }
          const name = row.querySelector('.entry-primary-line')
          const badge = row.querySelector('.entry-inline-badge')
          if (name && badge && rect(badge).top < rect(name).bottom - 1) bad.push('名称与标签重叠')
        }
        const scroll = document.querySelector('.detail-scroll')
        const clippedPanels = [...scroll.children].filter(el => el.classList.contains('panel') && el.scrollHeight > el.clientHeight + 2).map(el => el.className)
        return { bad, clippedPanels, overflow: scroll.scrollWidth > scroll.clientWidth + 1 || document.documentElement.scrollWidth > innerWidth + 1 }
      })
      assert.deepEqual(result, { bad: [], clippedPanels: [], overflow: false }, JSON.stringify({ width, dark, result }))
      const toggle = page.locator('.baidu-file-section .entry-section-toggle').first()
      await toggle.click()
      assert.equal(await page.locator('.baidu-file-section').first().locator('.entry-name').count(), 0)
      await toggle.click()
      assert.equal(await page.locator('.baidu-file-section').first().locator('.entry-name').count(), 3)
      await page.locator('.detail-scroll').evaluate(el => { el.scrollTop = document.querySelector('.baidu-file-section').offsetTop - 250 })
      await page.screenshot({ path: resolve(output, `${width}-${dark ? 'dark' : 'light'}.png`) })
      console.log(JSON.stringify({ width, dark, ...result, collapse: true }))
    }
  }
  assert.deepEqual(errors, [])
} finally {
  await browser?.close()
  await server.close()
}
