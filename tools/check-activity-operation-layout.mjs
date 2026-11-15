import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mkdir, writeFile } from 'node:fs/promises'

const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;padding:16px;background:#f6f7f9}html.kikoerumanager-dark body{background:#101113}#app{min-height:calc(100dvh - 32px)}</style>
</head><body><div id="app"></div><script type="module">
import {createApp} from 'vue'
import {createRouter,createMemoryHistory} from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '/src/index.css'
import '/src/dark-mode.css'
import Page from '/src/views/ActivityHistory.vue'
import api from '/src/api'
const files=Array.from({length:251},(_,index)=>({relative_path:'RJ01067908/音声/'+index+'-'.repeat(90)+'.flac',size_bytes:1024*1024*60,phase:'download',execution_id:'attempt-1'}))
const event={id:'failure',status:'failed',summary:'下载失败，用户重试后已修复',created_at:'2026-11-11T12:00:00',detail:{error:'连接中断：原始失败原因应始终可见',retry_task_id:'retry-1',retry_batch_id:'retry-batch-1'}}
const row={id:'fixture',operation_id:'operation-1',category:'asmr_sync',category_label:'ASMR 同步',
action:'task_finished',status:'repaired',current_result:'repaired',original_status:'failed',
revision:3,created_at:'2026-11-11T10:00:00',latest_activity_at:'2026-11-11T13:00:00',
summary:'RJ01067908 下载与入库完成，保留原始失败及重试关系',rjcode:'RJ01067908',integrity:[],
chips:[{label:'完成',value:'251',tone:'neutral'}],
detail:{operation_counts:{success:1},phase_metrics:{
download:{files:251,bytes:15791554560,duration_ms:4179562,average_speed_bytes:3778279},
local_import:{files:251,bytes:15791554560,average_speed_bytes:null}},
files_page:{items:files.slice(0,100),total:251,has_more:true,next_cursor:'file-100'},
child_rows:[event,{...event,id:'repaired',status:'success',summary:'手动重试完成',detail:{retry_projection:true}}],
children_page:{total:2,has_more:false,next_cursor:null}}}
api.activityLog.list=async()=>({generation:2,items:[row],total:1,window:{source:'activity_log_operations',search_backend:'postgresql_pg_trgm'}})
api.activityLog.stats=async()=>({generation:2,source:'activity_log_operations',days:14,total_in_range:1,event_count:3,
by_day:[{date:'2026-11-11',count:1}],by_category:[{category:'asmr_sync',label:'ASMR 同步',count:1}],by_status:{repaired:1},
metrics:{phases:row.detail.phase_metrics}})
api.activityLog.detail=async()=>({row})
api.activityLog.searchStatus=async()=>({fts_enabled:true,trigram_supported:true,rebuild:{running:false}})
api.activityLog.compactEstimate=async()=>({})
api.activityLog.files=async(id,{cursor})=>({items:files.slice(cursor==='file-100'?100:200,cursor==='file-100'?200:251),total:251,has_more:cursor==='file-100',next_cursor:cursor==='file-100'?'file-200':null})
api.activityLog.event=async()=>({event})
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:Page}]})
const app=createApp(Page)
app.use(router).use(ElementPlus).directive('app-loading',{})
app.mount('#app')
window.ready=true
</script></body></html>`
const server = await createServer({
  root: resolve(root, 'frontend'),
  configFile: resolve(root, 'frontend/vite.config.js'),
  server: { host: '127.0.0.1', port: 0, hmr: false },
  plugins: [{
    name: 'activity-operation-layout',
    configureServer(server) {
      server.middlewares.use('/activity-operation-layout', async (req, res) => {
        res.setHeader('Content-Type', 'text/html; charset=utf-8')
        res.end(await server.transformIndexHtml('/activity-operation-layout', html))
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
  const evidence = []
  page.on('pageerror', error => errors.push(error.message))
  const output = resolve(root, 'outputs/activity-layout')
  await mkdir(output, { recursive: true })
  for (const width of [2560, 390]) {
    for (const dark of [false, true]) {
      await page.setViewportSize({ width, height: width === 2560 ? 1440 : 844 })
      await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/activity-operation-layout`)
      await page.waitForFunction(() => window.ready)
      await page.evaluate(dark => {
        document.documentElement.classList.toggle('dark', dark)
        document.documentElement.classList.toggle('kikoerumanager-dark', dark)
      }, dark)
      const row = page.locator('.activity-log-row').first()
      await row.waitFor()
      await page.screenshot({ path: resolve(output, `${width}-${dark ? 'dark' : 'light'}-list.png`) })
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      await row.click()
      await page.locator('.operation-details').waitFor()
      await page.waitForFunction(() => !document.querySelector('.activity-overlay-enter-active'))
      await page.evaluate(async () => {
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        await Promise.all(document.getAnimations()
          .filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity)
          .map(animation => animation.finished.catch(() => {})))
      })
      await page.getByText('连接中断：原始失败原因应始终可见', { exact: true }).waitFor()
      await page.screenshot({ path: resolve(output, `${width}-${dark ? 'dark' : 'light'}-detail.png`) })
      const geometry = await page.locator('.activity-detail-panel').evaluate(element => {
        const box = element.getBoundingClientRect()
        return { left: box.left, right: box.right, scrollWidth: element.scrollWidth, width: element.clientWidth }
      })
      assert.ok(geometry.left >= -1 && geometry.right <= width + 1, JSON.stringify({ width, dark, geometry }))
      assert.ok(geometry.scrollWidth <= geometry.width + 1)
      const nextFiles = page.locator('.operation-pagination').first().getByRole('button', { name: '下一页' })
      await nextFiles.click()
      await page.getByText('当前 101–200／总计 251', { exact: true }).waitFor()
      await page.waitForFunction(() => !document.querySelector('.operation-pagination button[aria-busy="true"]'))
      await nextFiles.click()
      await page.getByText('当前 201–251／总计 251', { exact: true }).waitFor()
      assert.equal(await nextFiles.isDisabled(), true)
      await page.getByText('连接中断：原始失败原因应始终可见', { exact: true }).scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(output, `${width}-${dark ? 'dark' : 'light'}-retry.png`) })
      evidence.push({ width, dark, geometry })
    }
  }
  assert.deepEqual(errors, [])
  await writeFile(resolve(output, 'evidence.json'), JSON.stringify({ errors, evidence }, null, 2))
  console.log(JSON.stringify({ output, errors, evidence }, null, 2))
} finally {
  await browser?.close()
  await server.close()
}
