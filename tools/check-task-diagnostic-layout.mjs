import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mkdir } from 'node:fs/promises'
const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:12px}#app{height:calc(100dvh - 24px)}html.kikoerumanager-dark body{background:#08090c}.tasks-page,.tasks-main{height:100%;min-height:0}.tasks-main{display:grid}</style></head><body><div id="app"></div><script type="module">
import {createApp,h} from 'vue'
import '/src/index.css'
import '/src/dark-mode.css'
import Detail from '/src/components/tasks/TaskDetailPane.vue'
const item={id:'fixture',domain:'import',status:'completed',title:'RJ01634209.zip',current_step:'入库完成，源压缩包已归档',details:{metadata:{garbled_filename_sample:'診断サンプル',garbled_filename_score_before:100,garbled_filename_score_after:0,garbled_filename_repaired_count:22,garbled_filename_total_names:22,garbled_filename_check_passed:true,garbled_filename_top_samples:Array.from({length:8},(_,i)=>({name:'sample-'+i+'-'.repeat(90),score:100}))}}}
createApp({render:()=>h('div',{class:'tasks-page'},h('div',{class:'tasks-main'},h(Detail,{item,formatRJCode:v=>v,formatDateTime:v=>v,showProgress:()=>false,getRecoveredNotice:()=>'',getDLsiteFailureReason:()=>'',getOutputPath:()=>''})))}).mount('#app')
window.ready=true
</script></body></html>`
const server = await createServer({root:resolve(root,'frontend'),configFile:resolve(root,'frontend/vite.config.js'),server:{host:'127.0.0.1',port:0,hmr:false},plugins:[{name:'task-diagnostic-layout',configureServer(server){server.middlewares.use('/task-diagnostic-layout',async(req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/task-diagnostic-layout',html))})}}]})
let browser
try {
  await server.listen()
  browser=await chromium.launch({channel:'msedge',headless:true})
  const page=await browser.newPage()
  const errors=[]
  page.on('pageerror',e=>errors.push(e.message))
  const output=resolve(root,'data/task-diagnostic-layout')
  await mkdir(output,{recursive:true})
  for(const width of [390,1792]) {
    await page.setViewportSize({width,height:960})
    await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/task-diagnostic-layout`)
    await page.waitForFunction(()=>window.ready)
    for(const dark of [false,true]) {
      await page.evaluate(dark=>{document.documentElement.classList.toggle('dark',dark);document.documentElement.classList.toggle('kikoerumanager-dark',dark)},dark)
      await page.waitForTimeout(300)
      const styles=await page.locator('.filename-diagnostic-samples').evaluate(el=>({background:getComputedStyle(el).backgroundColor,row:getComputedStyle(el.firstElementChild).backgroundColor,scroll:el.scrollHeight>el.clientHeight,overflow:document.documentElement.scrollWidth>innerWidth}))
      assert.equal(styles.overflow,false)
      assert.equal(styles.scroll,false)
      if(dark){assert.equal(styles.background,'rgba(0, 0, 0, 0)');assert.equal(styles.row,'rgba(0, 0, 0, 0)')}
      await page.screenshot({path:resolve(output,`${width}-${dark?'dark':'light'}.png`)})
      console.log(JSON.stringify({width,dark,...styles}))
    }
  }
  assert.deepEqual(errors,[])
} finally {await browser?.close();await server.close()}
