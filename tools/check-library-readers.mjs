import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mkdir } from 'node:fs/promises'
const root = resolve(import.meta.dirname, '..')
const load = path => import(pathToFileURL(resolve(root, path)).href)
const { createServer } = await load('frontend/node_modules/vite/dist/node/index.js')
const { chromium } = await load('data/circle-bench-tools/node_modules/playwright/index.mjs')
const html = `<!doctype html><html><head><style>body{margin:0}#host{height:100vh;width:100vw}*{box-sizing:border-box}</style></head><body><div id=host></div><script type=module>
import {createApp,h,ref} from 'vue'
import Pdf from '/src/components/library/LibraryPdfReader.vue'
import Text from '/src/components/library/LibraryTextReader.vue'
import {initializeTheme,useTheme} from '/src/composables/useTheme.ts'
initializeTheme()
const kind=ref('text'),src=ref('/reader-fixture.txt'),fileKey=ref('fixture')
const visible=ref(true)
createApp({setup:()=>()=>visible.value?h(kind.value==='pdf'?Pdf:Text,{src:src.value,fileKey:fileKey.value,title:'阅读器验证.pdf',onClose:()=>visible.value=false}):null}).mount('#host')
window.reader={kind,src,fileKey,visible,setTheme:useTheme().setTheme}
</script></body></html>`
const server = await createServer({root:resolve(root,'frontend'),configFile:resolve(root,'frontend/vite.config.js'),server:{host:'127.0.0.1',port:18574,hmr:false},plugins:[{name:'reader-check',configureServer(server){server.middlewares.use('/reader-check',async(req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(await server.transformIndexHtml('/reader-check',html))})}}]})
let browser
try {
  await server.listen()
  browser = await chromium.launch({channel:'msedge',headless:true})
  const page = await browser.newPage({viewport:{width:1280,height:900}})
  const errors=[], external=[], workers=[]
  page.on('pageerror', error=>errors.push(error.message))
  page.on('console', message=>{if(message.type()==='error')console.log('浏览器错误:',message.text().slice(0,700))})
  page.on('worker', worker=>{workers.push(worker.url());worker.evaluate(()=>{addEventListener('error',event=>console.error('worker error',event.message));addEventListener('unhandledrejection',event=>console.error('worker rejection',String(event.reason))) }).catch(()=>{})})
  await page.route('**/*', async route=>{
    const url=new URL(route.request().url())
    if(url.hostname!=='127.0.0.1'&&url.protocol!=='data:'){external.push(url.href);await route.abort();return}
    if(url.pathname==='/reader-fixture.txt'){await route.fulfill({contentType:'application/octet-stream',body:Buffer.from('grGC6oLNk/qWe4zqgsyQ4Ja+lbaCxYK3gUKN7JVpgvCKeYK1gvGCxYKtgr6Cs4KigUIK','base64')});return}
    await route.continue()
  })
  await page.goto('http://127.0.0.1:'+server.httpServer.address().port+'/reader-check')
  await page.waitForFunction(()=>document.querySelector('.text-reader-content')?.textContent.includes('これは日本語'))
  assert.match(await page.locator('.text-reader-detection').textContent(), /SHIFT_JIS/)
  await page.getByRole('button',{name:'放大字号'}).click()
  assert.equal(await page.locator('.text-reader-content').evaluate(el=>getComputedStyle(el).fontSize),'18px')
  await page.locator('.app-dd-trigger').first().click()
  await page.locator('.app-dd-item').filter({hasText:'UTF-8 / UTF-8 BOM'}).click()
  await page.waitForFunction(()=>document.querySelector('.text-reader-content')?.textContent.includes('�'))
  await page.locator('.app-dd-trigger').first().click()
  await page.locator('.app-dd-item').filter({hasText:'Shift-JIS / CP932'}).click()
  await page.waitForFunction(()=>document.querySelector('.text-reader-content')?.textContent.includes('これは日本語'))
  await page.evaluate(()=>window.reader.setTheme('dark'))
  await page.setViewportSize({width:390,height:844})
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await mkdir(resolve(root,'data/reader-validation'),{recursive:true})
  await page.screenshot({path:resolve(root,'data/reader-validation/text-mobile-dark.png')})
  await page.reload()
  await page.waitForFunction(()=>document.querySelector('.text-reader-content')?.textContent.includes('これは日本語'))
  assert.match(await page.locator('.text-reader-detection').textContent(), /手动编码已应用/)
  assert.equal(await page.locator('.text-reader-content').evaluate(el=>getComputedStyle(el).fontSize),'18px')
  await page.setViewportSize({width:1280,height:900})
  await page.evaluate(()=>{window.reader.src.value='/node_modules/@embedpdf/snippet/dist/demo.pdf';window.reader.kind.value='pdf'})
  try {
    await page.waitForFunction(()=>{const viewer=document.querySelector('embedpdf-container');return [...(viewer?.shadowRoot?.querySelectorAll('img')||[])].some(image=>image.complete&&image.naturalWidth>0)},{},{timeout:30000})
  } catch (error) {
    await page.screenshot({path:resolve(root,'data/reader-validation/pdf-failure.png')})
    console.log(JSON.stringify({errors,external,workers,dom:await page.evaluate(()=>document.querySelector('embedpdf-container')?.shadowRoot?.innerHTML.slice(-6000))}))
    throw error
  }
  await page.screenshot({path:resolve(root,'data/reader-validation/pdf-desktop.png')})
  const viewer=page.locator('embedpdf-container')
  const controls=await viewer.locator('button').allTextContents()
  assert.ok(controls.length>5,'PDF 工具栏未加载')
  assert.equal(await page.locator('.media-preview-dialog').count(),0,'PDF 不应套用媒体弹窗外壳')
  assert.ok(await viewer.getByText('阅读器验证.pdf',{exact:true}).isVisible(),'未显示官方文档标签栏')
  assert.deepEqual(await page.locator('.library-pdf-reader').evaluate(el=>{const rect=el.getBoundingClientRect();return [rect.x,rect.y,rect.width,rect.height]}),[80,40,1120,820])
  const readRect=()=>page.locator('.library-pdf-reader').evaluate(el=>{const r=el.getBoundingClientRect();return {left:r.left,top:r.top,width:r.width,height:r.height,right:r.right,bottom:r.bottom}})
  const dragWindow=async(area,dx,dy)=>{
    const box=area==='title'?await viewer.getByText('阅读器验证.pdf',{exact:true}).boundingBox():await readRect()
    const x=area==='title'?box.x+box.width/2:box.right-80
    const y=area==='title'?box.y+box.height/2:box.top+20
    await page.mouse.move(x,y)
    await page.mouse.down()
    await page.mouse.move(x+dx,y+dy,{steps:5})
    await page.mouse.up()
  }
  const initialRect=await readRect()
  const workersBeforeDrag=workers.length
  for(const area of ['blank','title']){
    await dragWindow(area,24,16)
    assert.deepEqual(await readRect(),{left:104,top:56,width:1120,height:820,right:1224,bottom:876},`${area} 区域未正确移动窗口`)
    await dragWindow(area,-24,-16)
    assert.deepEqual(await readRect(),initialRect,'反向拖动未恢复位置')
  }
  await dragWindow('blank',2000,2000)
  assert.equal((await readRect()).right,1268,'拖动窗口右侧越界')
  assert.equal((await readRect()).bottom,888,'拖动窗口底部越界')
  await dragWindow('blank',-2000,-2000)
  assert.equal((await readRect()).left,12,'拖动窗口左侧越界')
  assert.equal((await readRect()).top,12,'拖动窗口顶部越界')
  await dragWindow('blank',68,28)
  assert.deepEqual(await readRect(),initialRect)
  const chooserPromise=page.waitForEvent('filechooser')
  await viewer.getByRole('button',{name:'Open File',exact:true}).click()
  await chooserPromise
  assert.deepEqual(await readRect(),initialRect,'新增文档按钮不应拖动窗口')
  assert.equal(workers.length,workersBeforeDrag,'移动不应重新初始化 PDF 引擎')
  const resizeWindow=async(direction,dx,dy)=>{
    const handle=await page.locator(`.library-pdf-resize-${direction}`).boundingBox()
    const x=handle.x+handle.width/2,y=handle.y+handle.height/2
    await page.mouse.move(x,y)
    await page.mouse.down()
    await page.mouse.move(x+dx,y+dy,{steps:5})
    await page.mouse.up()
  }
  const workersBeforeResize=workers.length
  for(const direction of ['n','s','e','w','ne','nw','se','sw']){
    const before=await readRect()
    const dx=direction.includes('w')?32:direction.includes('e')?-32:0
    const dy=direction.includes('n')?24:direction.includes('s')?-24:0
    await resizeWindow(direction,dx,dy)
    const after=await readRect()
    assert.equal(after.width,before.width-Math.abs(dx),`${direction} 宽度未正确改变`)
    assert.equal(after.height,before.height-Math.abs(dy),`${direction} 高度未正确改变`)
    if(direction.includes('w'))assert.equal(after.right,before.right,'拖左边时右边应固定')
    if(direction.includes('n'))assert.equal(after.bottom,before.bottom,'拖上边时下边应固定')
    await resizeWindow(direction,-dx,-dy)
    assert.deepEqual(await readRect(),before,'反向拖动未恢复原尺寸')
  }
  await resizeWindow('se',-2000,-2000)
  assert.equal((await readRect()).width,480,'未限制最小宽度')
  assert.equal((await readRect()).height,320,'未限制最小高度')
  await resizeWindow('se',2000,2000)
  assert.equal((await readRect()).right,1268,'窗口右边越界')
  assert.equal((await readRect()).bottom,888,'窗口下边越界')
  assert.equal(workers.length,workersBeforeResize,'缩放不应重新初始化 PDF 引擎')
  await page.setViewportSize({width:800,height:600})
  await page.waitForFunction(()=>{const r=document.querySelector(".library-pdf-reader").getBoundingClientRect();return r.left>=12&&r.top>=12&&r.right<=innerWidth-12&&r.bottom<=innerHeight-12})
  const fitted=await readRect()
  assert.ok(fitted.left>=12&&fitted.top>=12&&fitted.right<=788&&fitted.bottom<=588,'浏览器缩小时窗口应保持可见')
  await page.setViewportSize({width:1280,height:900})
  await page.evaluate(()=>window.reader.setTheme('light'))
  await page.waitForFunction(()=>document.querySelector('embedpdf-container')?.getAttribute('data-color-scheme')==='light')
  for(let i=0;i<3;i++){
    if(i===0){
      // 官方 UI 插件的内部弹窗优先消费 Escape，不能直接退出阅读器。
      await page.evaluate(async()=>{const registry=await document.querySelector('embedpdf-container').registry;const manager=registry.getPlugin('document-manager').provides();const ui=registry.getPlugin('ui').provides().forDocument(manager.getActiveDocumentId());const modal=Object.values(ui.getSchema().modals)[0];ui.openModal(modal.id)})
      await page.keyboard.press('Escape')
      assert.ok(await page.locator('embedpdf-container').count(),'Escape 错误关闭了整个阅读器')
      await page.keyboard.press('Escape')
    }else if(i===1){
      await page.getByRole('button',{name:'关闭 PDF 窗口',exact:true}).click()
    }else{
      // 点击 EmbedPDF 官方标签上的关闭按钮，验证宿主收到关闭事件。
      await viewer.getByRole('button',{name:'Close 阅读器验证.pdf',exact:true}).click()
    }
    await page.waitForFunction(()=>!document.querySelector('embedpdf-container'))
    const closedAt=Date.now()
    while(page.workers().length&&Date.now()-closedAt<5000)await new Promise(resolve=>setTimeout(resolve,50))
    assert.equal(page.workers().length,0,'关闭后 PDF Worker 未释放')
    await page.evaluate(()=>window.reader.visible.value=true)
    await page.waitForFunction(()=>[...(document.querySelector('embedpdf-container')?.shadowRoot?.querySelectorAll('img')||[])].some(image=>image.complete&&image.naturalWidth>0),{},{timeout:30000})
  }
  await page.setViewportSize({width:390,height:844})
  assert.deepEqual(await page.locator('.library-pdf-reader').evaluate(el=>{const rect=el.getBoundingClientRect();return [rect.x,rect.y,rect.width,rect.height]}),[12,12,366,820])
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await page.screenshot({path:resolve(root,'data/reader-validation/pdf-mobile.png')})
  assert.ok(await page.getByRole('button',{name:'关闭 PDF 窗口',exact:true}).isVisible(),'手机端缺少窗口关闭按钮')
  assert.deepEqual(external,[],'阅读器不应访问外部 CDN')
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({text:'自动识别、手动切换、持久化、字号、暗色和移动端通过',pdf:'真实 WASM 渲染、无项目外壳、官方标签关闭、Escape 内部弹窗优先、主题切换、3 轮关闭重开、移动端通过',workersCreated:workers.length,external,errors}))
} finally { await browser?.close();await server.close() }
