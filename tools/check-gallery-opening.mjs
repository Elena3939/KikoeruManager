import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><body><div id=host></div><script type=module>
import lightGallery from 'lightgallery'
import zoom from '/src/utils/libraryMediaZoom.js'
import thumbnail from 'lightgallery/plugins/thumbnail'
import fullscreen from 'lightgallery/plugins/fullscreen'
import rotate from '/src/utils/libraryMediaRotate.js'
import 'lightgallery/css/lightgallery.css'
import 'lightgallery/css/lg-thumbnail.css'
import 'lightgallery/css/lg-zoom.css'
import 'lightgallery/css/lg-fullscreen.css'
import 'lightgallery/css/lg-rotate.css'
import '/src/styles/library-media-preview.css'
import { LIGHT_GALLERY_OPEN_OPTIONS } from '/src/utils/libraryMediaPreview.js'
import { createLibraryMediaGallery } from '/src/utils/libraryMediaGallery.js'
window.checkLifecycle = async () => {
 const controller=createLibraryMediaGallery(lightGallery)
 const options={...LIGHT_GALLERY_OPEN_OPTIONS,dynamic:true,dynamicEl:[{src:'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',thumb:'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'}],plugins:[zoom,thumbnail,fullscreen,rotate],thumbnail:true}
 const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))
 for(let i=0;i<10;i++){
  await controller.open(options,0)
  await pause(100)
  document.querySelector('.lg-close').click()
  await Promise.all([controller.open(options,0),controller.open(options,0),controller.open(options,0)])
  if(document.querySelectorAll('.lg-container').length!==1) throw new Error('快速重开残留旧实例')
  await controller.close()
  if(document.querySelectorAll('.lg-container,.kikoeru-lightgallery-host').length) throw new Error('关闭后残留画廊节点')
 }
 await controller.open(options,0)
 await pause(100)
 document.querySelector('.lg-close').click()
 await pause(250)
 if(document.querySelectorAll('.lg-container,.kikoeru-lightgallery-host').length) throw new Error('正常关闭未清理实例')
 const cancelled=controller.open(options,0)
 await controller.close();await cancelled
 if(document.querySelectorAll('.lg-container,.kikoeru-lightgallery-host').length) throw new Error('取消打开后仍创建了实例')
 return {cycles:10,remainingContainers:document.querySelectorAll('.lg-container').length}
}
window.run = async optimized => {
 const canvas = document.createElement('canvas'); canvas.width=1600; canvas.height=1200
 const ctx=canvas.getContext('2d');ctx.fillStyle='#65748b';ctx.fillRect(0,0,1600,1200)
 const src=canvas.toDataURL('image/jpeg')
 const items=Array.from({length:100},(_,i)=>({src,thumb:src,alt:'图片'+i}))
 const start=performance.now()
 const gallery=lightGallery(document.getElementById('host'),{dynamic:true,dynamicEl:items,plugins:[zoom,thumbnail,fullscreen,rotate],index:50,speed:320,preload:2,virtualization:{slides:5,thumbs:2},...(optimized?LIGHT_GALLERY_OPEN_OPTIONS:{})})
 gallery.openGallery(50)
 if(optimized) gallery.getSlideItem(50).addClass('km-gallery-first')
 const syncMs=performance.now()-start
 const result=await new Promise((resolve,reject)=>{
  const tick=()=>{
   const slide=document.querySelector('.lg-current');const image=slide?.querySelector('.lg-object')
   if(slide?.classList.contains('lg-complete')&&document.querySelector('.lg-visible')&&image?.naturalWidth){resolve({syncMs,visibleMs:performance.now()-start,thumbs:document.querySelectorAll('.lg-thumb-item').length});return}
   if(performance.now()-start>5000){reject(new Error('首图未显示'));return}
   requestAnimationFrame(tick)
  };requestAnimationFrame(tick)
 })
 if(optimized){
  const wrap=document.querySelector('.lg-current .lg-img-wrap')
  const animation=wrap.getAnimations().find(item=>item.animationName==='km-media-image-reveal')
  if(!animation) throw new Error('图片未触发淡入动画')
  result.fadeMs=animation.effect.getTiming().duration
  await animation.finished
  if(getComputedStyle(wrap).opacity!=='1') throw new Error('淡入完成后图片未完全显示')
 }
 gallery.closeGallery();return result
}
window.checkWheel = async () => {
 let gallery
 const controller=createLibraryMediaGallery((host,options)=>(gallery=lightGallery(host,options)))
 const canvas=document.createElement('canvas');canvas.width=2400;canvas.height=1600
 await controller.open({...LIGHT_GALLERY_OPEN_OPTIONS,dynamic:true,dynamicEl:[{src:canvas.toDataURL()}],plugins:[zoom],zoom:true},0)
 const until=async predicate=>{const start=performance.now();while(!predicate()){if(performance.now()-start>5000)throw new Error('缩放等待超时');await new Promise(requestAnimationFrame)}}
 await until(()=>!gallery.lgBusy&&gallery.getSlideItem(0).hasClass('lg-zoomable'))
 const plugin=gallery.plugins.find(item=>typeof item.zoomImage==='function')
 const image=gallery.getSlideItem(0).get().querySelector('.lg-image')
 const rect=image.getBoundingClientRect()
 const wheel=(deltaY,deltaMode=0,target=image)=>{const event=new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY,deltaMode,clientX:rect.x+rect.width/2,clientY:rect.y+rect.height/2});target.dispatchEvent(event);return event.defaultPrevented}
 if(!wheel(-120))throw new Error('图片滚轮未被接管')
 await new Promise(requestAnimationFrame)
 const enlarged=plugin.scale
 if(!(enlarged>1))throw new Error('向上滚动未放大')
 wheel(120);await new Promise(requestAnimationFrame)
 if(Math.abs(plugin.scale-1)>0.001)throw new Error('向下滚动未恢复')
 wheel(-3,1);await new Promise(requestAnimationFrame)
 if(!(plugin.scale>1))throw new Error('行滚动单位未放大')
 for(let i=0;i<30;i++){wheel(-240);await new Promise(requestAnimationFrame)}
 if(plugin.scale!==8)throw new Error('放大上限错误')
 if(wheel(-120,0,gallery.$toolbar.get()))throw new Error('工具栏滚动被接管')
 wheel(120);await controller.close()
 if(document.querySelectorAll('.lg-container').length)throw new Error('滚轮关闭后未清理')
 return {enlarged,maxScale:8,minScale:1}
}
window.checkSwitch = async optimized => {
 const canvas=document.createElement('canvas');canvas.width=1600;canvas.height=1200
 const items=Array.from({length:15},(_,index)=>{
  const ctx=canvas.getContext('2d');ctx.fillStyle='hsl('+index*20+' 50% 50%)';ctx.fillRect(0,0,1600,1200)
  return {src:canvas.toDataURL('image/jpeg')}
 })
 let gallery
 const controller=createLibraryMediaGallery((host,options)=>(gallery=lightGallery(host,options)))
 const options={...LIGHT_GALLERY_OPEN_OPTIONS,dynamic:true,dynamicEl:items,plugins:[zoom,rotate],preload:2,virtualization:{slides:5,thumbs:2},...(optimized?{}:{speed:320})}
 if(optimized) await controller.open(options,0)
 else {gallery=lightGallery(document.getElementById('host'),options);gallery.openGallery(0)}
 const until=async predicate=>{const start=performance.now();while(!predicate()){if(performance.now()-start>5000)throw new Error('切图等待超时');await new Promise(requestAnimationFrame)}}
 await until(()=>!gallery.lgBusy&&gallery.getSlideItem(0).hasClass('lg-complete'))
 const samples=[]
 for(const index of [7,8,7]){
  const start=performance.now();gallery.slide(index)
  await until(()=>!!gallery.getSlideItem(index).get()?.querySelector('img.lg-object'))
  const loadStartMs=performance.now()-start
  await until(()=>!gallery.lgBusy&&gallery.getSlideItem(index).hasClass('lg-complete'))
  const wrap=gallery.getSlideItem(index).get().querySelector('.lg-img-wrap')
  if(optimized&&wrap.getAnimations().some(animation=>animation.animationName==='km-media-image-reveal'))throw new Error('切图重复触发首图淡入')
  samples.push({index,loadStartMs,settledMs:performance.now()-start})
 }
 if(optimized)await controller.close();else {const delay=gallery.destroy();await new Promise(resolve=>setTimeout(resolve,delay))}
 return samples
}
</script></body></html>`
const server=await createServer({root:resolve(root,'frontend'),configFile:resolve(root,'frontend/vite.config.js'),server:{host:'127.0.0.1',port:18573,hmr:false},plugins:[{name:'gallery-opening-check',configureServer(server){server.middlewares.use('/gallery-opening-check',async(req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/gallery-opening-check',html))})}}]})
let browser
try {
 await server.listen();browser=await chromium.launch({channel:'msedge',headless:true})
 const page=await browser.newPage({viewport:{width:1440,height:900}})
 const errors=[];page.on('pageerror',error=>errors.push(error.message))
 const lifecycleWarnings=[]
 page.on('console',message=>{if(message.text().includes('properly destroyed')||message.text().includes('properly initiated')) lifecycleWarnings.push(message.text())})
 const results={before:[],after:[]}
 for(const optimized of [false,true]) for(let i=0;i<3;i++){
  await page.goto('http://127.0.0.1:'+server.httpServer.address().port+'/gallery-opening-check')
  await page.waitForFunction(()=>typeof window.run==='function')
  results[optimized?'after':'before'].push(await page.evaluate(value=>window.run(value),optimized))
 }
 const median=values=>values.map(v=>v.visibleMs).sort((a,b)=>a-b)[1]
 assert.ok(median(results.after)<median(results.before),'优化后首图展示应提前')
 assert.deepEqual(errors,[])
 await page.reload()
 await page.waitForFunction(()=>typeof window.checkLifecycle==='function')
 const lifecycle=await page.evaluate(()=>window.checkLifecycle())
 const switching={}
 for(const optimized of [false,true]){
  await page.reload();await page.waitForFunction(()=>typeof window.checkSwitch==='function')
  switching[optimized?'after':'before']=await page.evaluate(value=>window.checkSwitch(value),optimized)
 }
 assert.ok(switching.after[0].loadStartMs<switching.before[0].loadStartMs/2,'未预载目标应在切图开始就加载')
 console.log(JSON.stringify({switching}))
 await page.reload();await page.waitForFunction(()=>typeof window.checkWheel==='function')
 const wheel=await page.evaluate(()=>window.checkWheel())
 console.log(JSON.stringify({wheel}))
 assert.deepEqual(lifecycleWarnings,[])
 assert.deepEqual(errors,[])
 console.log(JSON.stringify({lifecycle,lifecycleWarnings}))
 console.log(JSON.stringify(results,null,2))
} finally {await browser?.close();await server.close()}
