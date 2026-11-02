// 使用真实组件和固定任务检查布局，不连接业务 API 或改动任务数据。
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mkdir } from 'node:fs/promises'
const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}#app{display:flex;justify-content:center;padding:12px}html.dark body{background:#0b0c0e}</style></head><body><div id="app"></div><script type="module">
import {createApp,h,reactive} from 'vue'
import '/src/index.css'
import '/src/dark-mode.css'
import Shell from '/src/components/library/subtitle-workbench/SubtitleWorkbenchShell.vue'
import Stage from '/src/components/library/subtitle-workbench/SubtitleWorkbenchStage.vue'
const noop=()=>{}
const task={id:'layout-task',rjcode:'RJ01581759',status:'completed',folder_name:'字幕工作台测试任务'}
const options=reactive({scanDepth:3,overwriteExisting:false,enableMetadataMatch:true,skipIfExistingSubtitles:false,subtitleIndexQueryMode:'exact',namingStrategy:'subtitle',useFilterRules:true,subtitleFilterRules:[],aiMatchMode:'rule_ai_auto',aiConfidenceThreshold:85})
const ctx=reactive({railMode:'tasks',railModes:[{key:'scan',label:'扫描命中'},{key:'tasks',label:'执行队列'}],stageTabs:[{key:'overview',label:'任务总览'},{key:'pairing',label:'筛选与配对'},{key:'tree',label:'字幕文件树'}],activeStage:'overview',contextMode:'settings',setRailMode:noop,setActiveStage:key=>ctx.activeStage=key,taskNavigatorCtx:{subtitleTaskManualOverview:[{key:'all',label:'全部',value:1},{key:'queued',label:'已入任务',value:1}],subtitleQueueTasks:[task],visibleSubtitleTasks:[task],setSubtitleTaskManualFilter:noop},taskOverviewCtx:{activeSubtitleTask:task,activeSubtitleTaskProgressLogs:Array.from({length:60},(_,i)=>({time:'10:24:26',level:'info',message:'下载字幕 '+(i+1)+'/60：这是检查执行日志长文件名换行和滚动的测试内容.vtt'}))},configCtx:{subtitleOptions:options,setSubtitleOption:(key,value)=>options[key]=value},contextDrawerCtx:{drawerCollapsed:false,modeTitle:'参数面板',modeTip:'',contextMode:'settings',contextModes:[{key:'settings',label:'参数'},{key:'pairing',label:'配对'},{key:'tree',label:'文件'}],setContextMode:key=>{ctx.contextMode=key;ctx.contextDrawerCtx.contextMode=key}},workbenchCtx:{}})
ctx.contextDrawerCtx.modeOptions=ctx.contextDrawerCtx.contextModes
ctx.contextDrawerCtx.toggleDrawer=()=>ctx.contextDrawerCtx.drawerCollapsed=!ctx.contextDrawerCtx.drawerCollapsed
const audio=Array.from({length:20},(_,i)=>({path:'/audio/'+i,name:(i+1)+' 原音频文件名测试.wav'}))
const subtitles=Array.from({length:26},(_,i)=>({path:'/subtitles/'+i,name:(i+1)+' 字幕文件名测试.vtt'}))
Object.assign(ctx.workbenchCtx,{subtitleInspectorInfo:{subtitleDir:'/subtitles',folderName:'字幕工作台测试任务',totalFiles:26},activeSubtitleInspectTask:task,subtitleInspectorAudioFiles:audio,subtitleInspectorSubtitleFiles:subtitles,filteredSubtitleInspectorAudioFiles:audio,filteredSubtitleInspectorSubtitleFiles:subtitles})
Object.assign(ctx.workbenchCtx,{activeSubtitleTaskProgressLogs:ctx.taskOverviewCtx.activeSubtitleTaskProgressLogs,formatProgressLogTime:value=>value,getProgressLogLevelLabel:()=> '信息',subtitleManualPairs:[{id:'pair-1',audio_name:audio[0].name,subtitle_name:subtitles[0].name,target_subtitle_name:'配对结果.vtt',confidenceLevel:'high'}]})
ctx.taskOverviewCtx.visibleSubtitleTasks=[task]
Object.assign(ctx.taskNavigatorCtx,{getTaskDisplayRJCode:task=>task.rjcode,getSubtitleDownloadFiles:()=>[],getSubtitleAppliedWrittenFiles:()=>[]})
createApp({setup:()=>()=>h('div',{class:'subtitle-workbench-dialog'},h(Shell,{title:'RJ 字幕抓取工作台',focusCode:'RJ01581759',focusName:'布局检查'},()=>h(Stage,{ctx})))}).mount('#app')
window.layoutCtx=ctx;window.ready=true
</script></body></html>`
const server = await createServer({root:resolve(root,'frontend'),configFile:resolve(root,'frontend/vite.config.js'),server:{host:'127.0.0.1',port:0,hmr:false},plugins:[{name:'subtitle-layout-check',configureServer(server){server.middlewares.use('/layout-check',async(req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/layout-check',html))})}}]})
let browser
try {
  await server.listen()
  browser = await chromium.launch({channel:'msedge',headless:true})
  const page = await browser.newPage()
  const errors=[]
  page.on('pageerror',error=>{errors.push(error.message);console.error(error.message)})
  page.on('console',message=>{if(message.type()==='error')console.error(message.text())})
  const out=resolve(root,'data/subtitle-layout-check')
  await mkdir(out,{recursive:true})
  for(const width of [1560,1920,2048,1000,390]) {
    await page.setViewportSize({width,height:960})
    await page.goto('http://127.0.0.1:'+server.httpServer.address().port+'/layout-check')
    await page.waitForFunction(()=>window.ready)
    for(const dark of [false,true]) {
      await page.evaluate(dark=>document.documentElement.classList.toggle('kikoerumanager-dark',dark),dark)
      await page.waitForTimeout(100)
      const result=await page.evaluate(()=>{
        const log=document.querySelector('.subtitle-log-stream-scroll')
        const config=document.querySelector('.subtitle-config-card')
        const labels=[...document.querySelectorAll('.subtitle-quick-label,.subtitle-queue-label')]
        const clipped=labels.filter(el=>el.scrollWidth>el.clientWidth+1||el.scrollHeight>el.clientHeight+1).map(el=>el.textContent)
        log.scrollTop=log.scrollHeight;config.scrollTop=config.scrollHeight
        return {clipped,logBackground:getComputedStyle(log).backgroundColor,logScrolled:log.scrollTop>0,configOverflow:getComputedStyle(config).overflowY,pageOverflow:document.documentElement.scrollWidth>innerWidth+1}
      })
      if(result.clipped.length||!result.logScrolled||result.pageOverflow)throw new Error(JSON.stringify({width,dark,...result}))
      console.log(JSON.stringify({width,dark,...result}))
      await page.screenshot({path:resolve(out,width+'-'+(dark?'dark':'light')+'.png')})
      await page.evaluate(()=>{window.layoutCtx.activeStage='pairing';window.layoutCtx.contextMode='pairing'})
      await page.waitForTimeout(100)
      const pairing=await page.evaluate(()=>{
        const grid=document.querySelector('.subtitle-pairing-grid')
        const root=document.querySelector('.subtitle-inspector-workbench-scroll')
        const scrollable=[...root.querySelectorAll('*')].filter(el=>['auto','scroll'].includes(getComputedStyle(el).overflowY)&&el.scrollHeight>el.clientHeight+1)
        const details=document.querySelector('.subtitle-pairing-progress-log')
        const subtitleList=document.querySelector('.subtitle-pairing-subtitle-row').parentElement
        subtitleList.scrollTop=subtitleList.scrollHeight
        const last=document.querySelector('.subtitle-pairing-subtitle-row:last-child')
        const rect=last.getBoundingClientRect()
        const bounds=subtitleList.getBoundingClientRect()
        return {columns:grid.children.length,overflow:document.documentElement.scrollWidth>innerWidth+1,nestedScrollers:scrollable.length,internalScroll:subtitleList.scrollTop>0,hiddenScrollbar:getComputedStyle(subtitleList).scrollbarWidth==='none'&&getComputedStyle(subtitleList,'::-webkit-scrollbar').display==='none',lastRowReachable:rect.bottom<=bounds.bottom+1&&rect.top>=bounds.top,logCollapsed:!details.open,lists:[...document.querySelectorAll('.subtitle-pairing-list')].map(el=>({width:el.clientWidth,height:el.clientHeight,scrollHeight:el.scrollHeight}))}
      })
      if(pairing.columns!==3||pairing.overflow||pairing.nestedScrollers!==2||!pairing.internalScroll||!pairing.hiddenScrollbar||!pairing.lastRowReachable||!pairing.logCollapsed||pairing.lists.some(list=>!list.width||!list.height))throw new Error(JSON.stringify({width,dark,pairing}))
      console.log(JSON.stringify({width,dark,pairing}))
      await page.locator('.subtitle-pairing-progress-log summary').click()
      if(!await page.locator('.subtitle-pairing-progress-log').evaluate(el=>el.open))throw new Error('过程日志未展开')
      await page.locator('.subtitle-pairing-progress-log summary').click()
      await page.locator('.subtitle-inspector-workbench-scroll').evaluate(el=>el.scrollTop=0)
      await page.screenshot({path:resolve(out,width+'-'+(dark?'dark':'light')+'-pairing.png')})
      await page.evaluate(()=>{window.layoutCtx.activeStage='overview';window.layoutCtx.contextMode='settings'})
    }
  }
  if(errors.length)throw new Error(errors.join('\n'))
} finally {
  await browser?.close()
  await server.close()
}
