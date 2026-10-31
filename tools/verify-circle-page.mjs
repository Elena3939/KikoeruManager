// 在本机开发页注入固定作品，验证真实布局中的异步加载和滚动。
import { mkdir } from 'node:fs/promises'
import { preview } from '../frontend/node_modules/vite/dist/node/index.js'
import { fileURLToPath, pathToFileURL } from 'node:url'

const { chromium } = await import(process.env.KM_PLAYWRIGHT_MODULE
  ? pathToFileURL(process.env.KM_PLAYWRIGHT_MODULE).href
  : '../data/circle-bench-tools/node_modules/playwright/index.mjs')
await mkdir('data/circle-bench-tools', { recursive: true })

const server = await preview({
  root: fileURLToPath(new URL('../frontend', import.meta.url)),
  configFile: false,
  preview: { host: '127.0.0.1', port: 5190, strictPort: true },
})
const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
})
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  const worksRequests = []
  const repairStarts = []
  const repairTasks = {}
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', request => {
    if (/\/api\/circle-completion\/circles\/[^/]+\/works\?/.test(request.url())) worksRequests.push(request.url())
  })
  await page.route('**/api/circle-completion/**', async route => {
    const url = route.request().url()
    if (url.includes('/subtitle-repair/')) {
      const body = route.request().postDataJSON()
      if (url.endsWith('/targets')) return route.fulfill({ json: {
        items: body.canonical_rjcodes.map(code => ({ canonical_rjcode: code, targets: [
          { library_id: 'local', folder_path: `/ASMR/${code}`, library_name: '测试库存',
            subtitle_count: 0, audio_count: 6, eligible: true },
        ] })),
      } })
      if (url.endsWith('/start')) {
        repairStarts.push(body)
        for (const code of body.canonical_rjcodes) repairTasks[code] = [
          { task_id: `subtitle-${code}`, rjcode: code, status: 'pending',
            library_id: 'local', folder_path: `/ASMR/${code}` },
        ]
        return route.fulfill({ json: { created_count: body.canonical_rjcodes.length,
          reused_count: 0, skipped_count: 0, items: [] } })
      }
      return route.fulfill({ json: { items: repairTasks } })
    }
    const items = Array.from({ length: 100 }, (_, index) => ({
      canonical_rjcode: `RJ${10000000 + index}`,
      display_rjcode: `RJ${10000000 + index}`,
      title: `性能验证作品 ${index}`,
      has_dlsite: true,
      has_asmr_one: true,
      subtitle_repairable: true,
      subtitle_missing_target_count: 1,
      subtitle_repair_sources: [{ label: '发现字幕包', provider: 'yaas', rjcode: `RJ${10000000 + index}`, is_ai: true }],
      image_url: 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=',
      thumb_image_url: 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=',
    }))
    await route.fulfill({
      json: url.includes('/recent')
        ? { circles: [{ circle_id: 'RG10001', circle_name: '性能验证', total_works: 100, missing: 100 }] }
        : url.includes('/works')
          ? { items, tab: 'missing', total: 100, page: 1, page_size: 100, page_count: 1, missing_count: 100, total_works: 100, downloadable_count: 100 }
          : {},
    })
  })
  await page.route('**/api/**', async route => {
    if (route.request().url().includes('/api/circle-completion/')) return route.fallback()
    return route.fulfill({ json: {} })
  })
  await page.goto('http://127.0.0.1:5190/circle-completion')
  await page.locator('.circle-list-name-text').getByText('性能验证', { exact: true }).click()
  await page.waitForTimeout(1500)
  if (worksRequests.length !== 1) throw new Error(`首屏出现额外作品请求：${worksRequests.length}`)
  const emit = detail => page.evaluate(value => {
    window.dispatchEvent(new CustomEvent('kikoerumanager:events:message', { detail: value }))
  }, detail)
  await emit({ type: 'task.center.changed', payload: { domain: 'rj_subtitle', status: 'processing', entity_id: 'unrelated' } })
  await emit({ type: 'circle.subtitle.synced', payload: { circle_ids: ['other-circle'] } })
  await page.waitForTimeout(1000)
  if (worksRequests.length !== 1) throw new Error('无关任务或其它社团事件刷新了当前作品')
  await emit({ type: 'circle.subtitle.synced', payload: { circle_ids: ['RG10001'] } })
  await page.waitForTimeout(1500)
  if (worksRequests.length !== 2) throw new Error(`字幕落盘后应仅更新一次：${worksRequests.length}`)
  const requestsAfterSync = worksRequests.length
  const readRepairSize = () => page.locator('.circle-subtitle-action:not(.is-task)').first().evaluate(button => {
    const label = button.querySelector('.circle-subtitle-action-text')
    const box = button.getBoundingClientRect()
    const text = label.getBoundingClientRect()
    return { font: getComputedStyle(label).fontSize, height: box.height,
      fits: text.left >= box.left && text.right <= box.right && text.top >= box.top && text.bottom <= box.bottom }
  })
  const cardRepairSize = await readRepairSize()
  if (cardRepairSize.font !== '10px' || !cardRepairSize.fits) throw new Error(`卡片字幕标签尺寸异常：${JSON.stringify(cardRepairSize)}`)
  const beforeCreateUrl = page.url()
  await page.locator('.work-card .circle-subtitle-action:not(.is-task)').first().click()
  await page.getByRole('button', { name: '已加入', exact: true }).first().waitFor()
  if (repairStarts.length !== 1 || page.url() !== beforeCreateUrl || await page.locator('.el-dialog:visible').count()) {
    throw new Error('字幕创建未保持当前页面，或意外弹出工作台')
  }
  if (worksRequests.length !== requestsAfterSync) throw new Error('创建字幕任务触发了作品资源刷新')
  await page.screenshot({ path: 'data/circle-bench-tools/full-page.png' })
  await page.locator('.el-pagination:visible .el-select').click()
  await page.getByRole('option', { name: '100/page', exact: true }).click()
  await page.waitForTimeout(800)
  const desktop = await page.evaluate(async () => {
    const scroll = document.querySelector('.circle-work-scroll')
    const frames = []
    let previous = performance.now()
    for (let index = 0; index < 100; index++) {
      scroll.scrollTop = (scroll.scrollHeight - scroll.clientHeight) * index / 99
      await new Promise(requestAnimationFrame)
      const now = performance.now()
      frames.push(now - previous)
      previous = now
    }
    frames.sort((a, b) => a - b)
    return { cards: scroll.querySelectorAll('.work-card').length, height: scroll.clientHeight, total: scroll.scrollHeight, scroll_p95_ms: frames[94], reachedLast: scroll.textContent.includes('性能验证作品 99') }
  })
  if (!desktop.cards || desktop.cards >= 100 || !desktop.reachedLast) throw new Error(`桌面虚拟视口异常：${JSON.stringify(desktop)}`)
  await page.locator('.work-card').first().click()
  const selected = await page.locator('.work-card.selected').count()
  if (!selected) throw new Error('点击后选择态没有更新')
  await page.screenshot({ path: 'data/circle-bench-tools/full-page.png' })
  await page.getByTitle('列表视图', { exact: true }).click()
  await page.waitForTimeout(800)
  const listRows = await page.locator('.work-list-row').count()
  if (!listRows || listRows >= 100) throw new Error(`列表视图未虚拟化：${listRows}`)
  const listRepairSize = await readRepairSize()
  if (listRepairSize.font !== '11px' || !listRepairSize.fits) throw new Error(`列表字幕标签尺寸异常：${JSON.stringify(listRepairSize)}`)
  await page.locator('.release-sort-button:visible').click()
  await page.reload()
  await page.locator('.work-list-row').first().waitFor()
  const preferences = await page.evaluate(() => JSON.parse(localStorage.getItem('kikoerumanager.circleCompletion.viewPreferences')))
  if (preferences.worksPageSize !== 100 || preferences.viewMode !== 'list' || preferences.worksReleaseSort !== 'asc') {
    throw new Error(`显示偏好未保存：${JSON.stringify(preferences)}`)
  }
  if (!await page.getByTitle('列表视图', { exact: true }).evaluate(element => element.classList.contains('active'))
    || !await page.locator('.el-pagination:visible .el-select').innerText().then(text => text.includes('100/page'))
    || !await page.getByTitle('按发售时间正序', { exact: true }).count()) {
    throw new Error('刷新后没有恢复每页条数、列表视图或排序')
  }
  await page.getByTitle('卡片视图', { exact: true }).click()
  await page.waitForTimeout(800)
  await page.evaluate(() => document.documentElement.classList.add('dark', 'kikoerumanager-dark'))
  await page.screenshot({ path: 'data/circle-bench-tools/dark-page.png' })
  const darkRepairSize = await readRepairSize()
  if (darkRepairSize.font !== '10px' || !darkRepairSize.fits) throw new Error('深色字幕标签布局异常')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(500)
  const mobile = await page.evaluate(() => ({
    cards: document.querySelectorAll('.circle-work-plain .work-card').length,
    overflow: document.documentElement.scrollWidth > innerWidth,
  }))
  if (mobile.cards !== 100 || mobile.overflow) throw new Error(`移动端布局异常：${JSON.stringify(mobile)}`)
  const mobileRepairSize = await readRepairSize()
  if (mobileRepairSize.font !== '10px' || !mobileRepairSize.fits) throw new Error('移动端字幕标签布局异常')
  await page.screenshot({ path: 'data/circle-bench-tools/mobile-page.png' })
  console.log(JSON.stringify({ requestsAfterSync, desktop, selected, listRows, preferences, mobile,
    repairStarts: repairStarts.length, cardRepairSize, listRepairSize, darkRepairSize, mobileRepairSize, errors }))
  if (errors.length) throw new Error('页面存在运行异常')
} finally {
  await browser.close()
  await new Promise(resolve => server.httpServer.close(resolve))
}
