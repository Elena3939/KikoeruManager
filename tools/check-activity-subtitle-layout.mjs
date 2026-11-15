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
const changes=Array.from({length:9},(_,i)=>({audio_before:'原音频'+i+'.wav',audio_after:'第'+i+'项_'+ '长文件名称'.repeat(30)+'.wav',subtitle_before:'原字幕'+i+'.vtt',subtitle_after:'字幕'+i+'.vtt'}))
const pair={id:'pair',category:'subtitle_pair',relation:'pair',status:'success',summary:'已应用 9 组配对',created_at:'2026-11-14T16:12:42',detail:{applied_pairs:9,naming_strategy:'subtitle',pair_changes:changes,pairing_mode:'ai',ai_diagnostics:{model:'test-model',reasoning:'接口返回的标题语义解释。'.repeat(50),raw_output:JSON.stringify({matches:changes}),duration_ms:1234,request_duration_ms:1200,first_event_ms:100,first_content_ms:300,prompt_tokens:100,completion_tokens:80,total_tokens:180,cached_tokens:0,reasoning_tokens:10,stream_used:true}}}
const row=ref({id:'crawl',task_id:'task',category:'subtitle_crawl',category_label:'字幕爬取',action:'task_finished',status:'success',summary:'已应用 9 组配对',created_at:'2026-11-14T15:44:01',detail:{manual_match_completed:true,awaiting_manual_match:false,downloaded_count:9,written_files_count:9,child_rows:[pair]}})
window.layoutRow=row
window.pairFixture=pair
window.crawlFixture=row.value
createApp({setup:()=>()=>h('div',{class:'activity-detail-panel'},h(Detail,{row:row.value}))}).directive('app-loading',{}).mount('#app')
window.ready=true
</script></body></html>`
const server = await createServer({
  root: resolve(root, 'frontend'),
  configFile: resolve(root, 'frontend/vite.config.js'),
  server: { host: '127.0.0.1', port: 0, hmr: false },
  plugins: [{
    name: 'activity-subtitle-layout',
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
  const output = resolve(root, 'data/activity-subtitle-layout')
  await mkdir(output, { recursive: true })
  for (const scenario of ['crawl', 'import-archive', 'import-folder']) {
  for (const width of [390, 480, 639, 640, 800, 960]) {
    await page.setViewportSize({ width, height: 1200 })
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/layout-check`)
    await page.waitForFunction(() => window.ready)
    await page.evaluate(scenario => {
      if (scenario === 'import-archive') {
        window.layoutRow.value = { id: 'standalone-import', task_id: 'task', category: 'subtitle_import', category_label: '字幕补配',
          action: 'archive_import', status: 'success', summary: '字幕补配完成，共导入 9 个字幕文件',
          detail: { ...window.pairFixture.detail, manual_match_completed: true, manual_match_applied_pairs: 9,
            final_file_count: 9, target_folder_path: '/库存/RJ100001', library_id: 'test' } }
      } else if (scenario === 'import-folder') {
        window.layoutRow.value = { ...window.crawlFixture, category: 'subtitle_import', category_label: '字幕补配', action: 'folder_import' }
      }
    }, scenario)
    for (const dark of [false, true]) {
      await page.evaluate(dark => {
        document.documentElement.classList.toggle('dark', dark)
        document.documentElement.classList.toggle('kikoerumanager-dark', dark)
      }, dark)
      const result = await page.evaluate(() => {
        const bad = []
        const rect = el => el.getBoundingClientRect()
        for (const row of document.querySelectorAll('.pair-change-row')) {
          if (row.scrollWidth > row.clientWidth + 1) bad.push(row.textContent)
        }
        const scroll = document.querySelector('.detail-scroll')
        const clippedPanels = [...scroll.children].filter(el => el.classList.contains('panel') && el.scrollHeight > el.clientHeight + 2).map(el => el.className)
        return { bad, clippedPanels, overflow: scroll.scrollWidth > scroll.clientWidth + 1 || document.documentElement.scrollWidth > innerWidth + 1 }
      })
      assert.deepEqual(result, { bad: [], clippedPanels: [], overflow: false }, JSON.stringify({ width, dark, result }))
      assert.equal(await page.locator('.pair-change-row').count(), 9)
      assert.match(await page.locator('.pair-change-row > span').first().textContent(), /原音频0/)
      assert.match(await page.locator('.pair-metric-grid').first().textContent(), /AI 配对/)
      assert.match(await page.locator('.pair-ai-diagnostics').textContent(), /输入 token.*100/s)
      await page.locator('.pair-ai-section').last().locator('summary').click()
      assert.match(await page.locator('.pair-ai-section').last().textContent(), /audio_before/)
      assert.match(await page.locator('.pair-change-row').last().textContent(), /第8项/)
      if (scenario === 'crawl') assert.match(await page.locator('.detail-scroll').textContent(), /处理过程/)
      if (scenario !== 'crawl') assert.match(await page.locator('.pair-metric-grid').first().textContent(), /导入字幕/)
      await page.locator('.pair-change-row').last().scrollIntoViewIfNeeded()
      await page.screenshot({ path: resolve(output, `${scenario}-${width}-${dark ? 'dark' : 'light'}.png`) })
      console.log(JSON.stringify({ scenario, width, dark, ...result }))
    }
  }
  }
  assert.deepEqual(errors, [])
} finally {
  await browser?.close()
  await server.close()
}
