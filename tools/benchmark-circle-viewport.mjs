// 固定百条分页，在真实 Edge 中比较改前/改后的刷新与主线程长任务。
// 依赖：frontend/node_modules，以及 data/circle-bench-tools 内临时安装的 playwright。
import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { default: vue } = await load('frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const baseline = process.argv[2]
if (!baseline) throw new Error('请传入修改前 Git 提交号')
const source = execFileSync('git', ['show', `${baseline}:frontend/src/components/circle/CircleWorksViewport.vue`], { cwd: root, encoding: 'utf8' })
const virtualPath = resolve(root, 'frontend/src/components/circle/CircleWorksViewport.baseline.vue').replaceAll('\\', '/')
const html = `<!doctype html><html><head><style>body{margin:0}#app{width:1200px;height:800px}.circle-works-scroll{height:700px}</style></head><body><div id="app"></div><script type="module">
import {createApp,h,shallowRef,nextTick} from 'vue'
import Viewport from '/src/components/circle/CircleWorksViewport.VARIANT.vue'
const blank='data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs='
function dataset(tick){return Array.from({length:100},(_,i)=>{
 const bonuses=Array.from({length:30},(_,j)=>({canonical_rjcode:'RJ'+(20000000+i*30+j),display_rjcode:'RJ'+(20000000+i*30+j),title:'【特典音声 '+j+'】_'+j,is_bonus_work:true,cover_available:true,has_asmr_one:true,image_url:blank}))
 return {canonical_rjcode:'RJ'+(10000000+i),display_rjcode:'RJ'+(10000000+i),title:'固定作品 '+i+' 更新 '+tick,image_url:blank,has_dlsite:true,bonus_works:bonuses,bonus_display_works:bonuses.map(b=>({...b,_bonus_members:[b],bonus_owned_label:'未收录',bonus_download_label:'可下载'}))}
})}
const items=shallowRef(dataset(0))
const stub={setup:()=>()=>null}
const app=createApp({setup:()=>()=>h(Viewport,{items:items.value,mode:'card',serverPaging:true,totalItems:5000,pageSize:100})})
app.component('ElPagination',stub); app.component('ElDialog',stub);app.mount('#app')
const frame=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))
await frame();await new Promise(r=>setTimeout(r,500))
window.run=async()=>{
 const tasks=[];const observer=new PerformanceObserver(list=>tasks.push(...list.getEntries().map(e=>e.duration)))
 observer.observe({type:'longtask'})
 const times=[]
 for(let i=1;i<=25;i++){
  const data=dataset(i);const start=performance.now();items.value=data;await nextTick();times.push(performance.now()-start);await frame()
 }
 await new Promise(r=>setTimeout(r,100));observer.disconnect();times.sort((a,b)=>a-b)
 return {median_ms:times[12],p95_ms:times[23],long_tasks:tasks.length,max_long_task_ms:tasks.length?Math.max(...tasks):0}
};window.ready=true
</script></body></html>`
const server = await createServer({
  root: resolve(root, 'frontend'), configFile: false, plugins: [{
    name: 'circle-benchmark', enforce: 'pre',
    resolveId(id) { if (id.endsWith('/CircleWorksViewport.baseline.vue')) return virtualPath },
    load(id) { if (id === virtualPath) return source },
    configureServer(server) {
      server.middlewares.use('/bench', (req, res) => {
        res.setHeader('Content-Type', 'text/html; charset=utf-8')
        const content = html.replace('.VARIANT', req.url.includes('before') ? '.baseline' : '')
        server.transformIndexHtml(`/bench${req.url}`, content).then(result => res.end(result))
      })
    },
  }, vue()],
  resolve: { alias: { '@': resolve(root, 'frontend/src') } },
  server: { host: '127.0.0.1', port: 5189, strictPort: true },
})
let browser
try {
  await server.listen()
  browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true })
  const result = { baseline, dataset: '百条分页，每条30个特典，25次刷新；不含初始加载与网络' }
  for (const variant of ['before', 'after']) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    page.on('pageerror', error => console.error(error.message))
    await page.goto(`http://127.0.0.1:5189/bench/${variant}`)
    await page.waitForFunction(() => window.ready, { timeout: 60000 })
    result[variant] = await page.evaluate(() => window.run())
    await page.close()
  }
  console.log(JSON.stringify(result, null, 2))
} finally {
  await browser?.close()
  await server.close()
}
