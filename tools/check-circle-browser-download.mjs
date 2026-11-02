import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { mkdir } from 'node:fs/promises'

// 通过真实社团页面创建验收任务，会把等待任务交给浏览器并清理系统记录。
assert.ok(process.argv.includes('--real'), '真实任务验收需要显式传入 --real')
const root = resolve(import.meta.dirname, '..')
const { chromium } = await import(pathToFileURL(resolve(root, 'data/circle-bench-tools/node_modules/playwright/index.mjs')).href)
const browser = await chromium.launch({
  channel: 'msedge', headless: true, ignoreDefaultArgs: ['--disable-popup-blocking'],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
const page = await context.newPage()
let taskId, createdCount, opened = 0, handed = 0
const responses = []
page.on('response', response => {
  const path = new URL(response.url()).pathname
  if (path.endsWith('/subtitle-repair/start')) {
    responses.push(response.json().then(result => {
      createdCount = result.created_count
      taskId = result.items?.find(item => item.canonical_rjcode === 'RJ01168542')?.task_id
    }))
  }
  if (/\/browser-verification\/task\/[^/]+\/open$/.test(path)) {
    responses.push(response.json().then(result => {
      assert.equal(result.presentation, 'current_browser')
      opened++
    }))
  }
  if (/\/browser-verification\/task\/[^/]+\/handoff$/.test(path)) {
    responses.push(response.json().then(result => {
      assert.equal(result.success, true)
      handed++
    }))
  }
})
try {
  await page.goto('http://localhost:5556/circle-completion?circle_id=RG38133&rjcode=RJ01168542')
  const button = page.locator('.circle-subtitle-action').filter({ hasText: '可补配' })
  await button.waitFor({ timeout: 30000 })
  const popupPromise = page.waitForEvent('popup')
  const handoffPromise = page.waitForResponse(response => /\/browser-verification\/task\/[^/]+\/handoff$/.test(new URL(response.url()).pathname), { timeout: 120000 })
  await button.click()
  const popup = await popupPromise
  assert.equal(popup.context(), context)
  let navigationError = ''
  await Promise.all([
    popup.waitForURL(url => url.protocol === 'https:' && url.hostname.endsWith('.imoutoheaven.org'), {
      waitUntil: 'domcontentloaded', timeout: 120000,
    }).catch(error => { navigationError = error.message.match(/net::ERR_[A-Z_]+/)?.[0] || error.name }),
    handoffPromise,
  ])
  if (!navigationError) {
    await popup.locator('body').filter({ hasText: /\S/ }).waitFor({ timeout: 30000 })
  }
  await Promise.all(responses)
  assert.ok(taskId)
  assert.equal(createdCount, 1)
  assert.equal(opened, 1)
  assert.equal(handed, 1)
  const status = await (await context.request.get('http://127.0.0.1:5555/api/rj-subtitle/status')).json()
  assert.ok(!(status.tasks || []).some(task => (task.id || task.task_id) === taskId))
  const output = resolve(root, 'data/yaas-current-browser-check')
  await mkdir(output, { recursive: true })
  await page.screenshot({ path: resolve(output, 'real-circle-after.png') })
  await popup.screenshot({ path: resolve(output, navigationError ? 'real-browser-navigation-error.png' : 'real-browser-verification.png'), timeout: 15000 })
  console.log(JSON.stringify({
    rjcode: 'RJ01168542', createdCount, popupBlockingEnabled: true,
    sameBrowserPopup: true, opened, handed, systemTaskRemoved: true,
    navigationError,
    verificationPageTitle: await popup.title(),
  }))
  assert.equal(navigationError, '', '验证站页面加载失败，弹窗与交接成功不代表验证成功')
} finally {
  await browser.close()
}
