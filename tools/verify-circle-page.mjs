// 在本机开发页注入固定作品，验证真实布局中的异步加载和滚动。
import { chromium } from '../data/circle-bench-tools/node_modules/playwright/index.mjs'
import { preview } from '../frontend/node_modules/vite/dist/node/index.js'
import { fileURLToPath } from 'node:url'

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
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/circle-completion/**', async route => {
    const url = route.request().url()
    const items = Array.from({ length: 100 }, (_, index) => ({
      canonical_rjcode: `RJ${10000000 + index}`,
      display_rjcode: `RJ${10000000 + index}`,
      title: `性能验证作品 ${index}`,
      has_dlsite: true,
      has_asmr_one: true,
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
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(500)
  const mobile = await page.evaluate(() => ({
    cards: document.querySelectorAll('.circle-work-plain .work-card').length,
    overflow: document.documentElement.scrollWidth > innerWidth,
  }))
  if (mobile.cards !== 100 || mobile.overflow) throw new Error(`移动端布局异常：${JSON.stringify(mobile)}`)
  await page.screenshot({ path: 'data/circle-bench-tools/mobile-page.png' })
  console.log(JSON.stringify({ desktop, selected, listRows, preferences, mobile, errors }))
  if (errors.length) throw new Error('页面存在运行异常')
} finally {
  await browser.close()
  await new Promise(resolve => server.httpServer.close(resolve))
}
