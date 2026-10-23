import { shallowRef, markRaw } from 'vue'
import { ElNotification } from 'element-plus'
import { apiUrl, redirectIfSecurityGateExpired } from '../api'
import { enumerateUploadEntries, yieldUploadThread } from '../utils/browserUploadEntries'
import { useBackgroundWorkbenchManager } from './useBackgroundWorkbenchManager'
import { showSystemConfirm } from './useSystemPrompt'

const STORAGE = 'kikoerumanager.browserUploads'
export const UPLOAD_WORKBENCH = 'library-browser-uploads'
const CHUNK = 8 * 1024 * 1024
const runtime = new Map()
export const browserUploads = shallowRef([])
const queue = []
let activeFiles = 0
let initialized = false
let worker, hashId = 0
const hashes = new Map()
const manager = useBackgroundWorkbenchManager()
const stopped = new Set(['completed', 'failed', 'cancelled'])

function remember() {
  localStorage.setItem(STORAGE, JSON.stringify(Array.from(runtime.values(), s => ({ id: s.id, token: s.token }))))
}

function hash(buffer) {
  if (!worker) {
    worker = new Worker(new URL('../workers/browserUploadHash.worker.js', import.meta.url), { type: 'module' })
    worker.onmessage = ({ data }) => {
      const pending = hashes.get(data.id)
      hashes.delete(data.id)
      if (pending) data.error ? pending.reject(new Error(data.error)) : pending.resolve(data)
    }
    worker.onerror = () => {
      for (const pending of hashes.values()) pending.reject(new Error('摘要计算线程异常'))
      hashes.clear()
      worker.terminate()
      worker = null
    }
  }
  return new Promise((resolve, reject) => {
    const id = ++hashId
    hashes.set(id, { resolve, reject })
    worker.postMessage({ id, buffer }, [buffer])
  })
}

async function request(session, suffix = '', options = {}) {
  const response = await fetch(apiUrl('/library/browser/uploads' + (session?.id ? '/' + session.id : '') + suffix), {
    credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(session?.token ? { 'X-Upload-Token': session.token } : {}), ...options.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    if (response.status === 401 || response.status === 403) await redirectIfSecurityGateExpired()
    const error = new Error(typeof body.detail === 'string' ? body.detail : `上传请求失败 HTTP ${response.status}`)
    error.status = response.status
    throw error
  }
  return response.json()
}

async function gate(session) {
  while (session.status === 'paused') await new Promise(resolve => setTimeout(resolve, 100))
  if (session.status === 'cancelled' || session.enumerationStopped) throw new DOMException('已停止读取来源', 'AbortError')
}

function schedule(session, file, source) {
  if (file.is_directory || file.status !== 'receiving' || file.busy) return
  if (!source) { session.needsSource = true; return }
  file.busy = true
  queue.push({ session, file, source })
  pump()
}

function pump() {
  while (activeFiles < 3 && queue.length) {
    const index = queue.findIndex(item => item.session.status !== 'paused')
    if (index < 0) break
    const item = queue.splice(index, 1)[0]
    activeFiles++
    transfer(item).catch(async error => {
      if (error.name !== 'AbortError') {
        item.file.status = 'failed'
        item.file.reason = error.message
        item.file.stage = '上传接收'
        item.file.clientFailed = true
        try {
          await request(item.session, '/actions', { method: 'POST', body: JSON.stringify({ action: 'receive_failed', file_id: item.file.id, reason: error.message.slice(0, 2000) }) })
        } catch (_) { /* 断网时保留本地失败，连接恢复后补报 */ }
      }
    }).finally(() => {
      item.file.busy = false
      item.file.speed = 0
      item.file.liveBytes = 0
      activeFiles--
      pump()
    })
  }
}

function sendChunk(session, file, offset, buffer, digest, signal) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', apiUrl(`/library/browser/uploads/${session.id}/files/${file.id}/chunks?offset=${offset}`))
    xhr.withCredentials = true
    xhr.timeout = 120000
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.setRequestHeader('X-Upload-Token', session.token)
    xhr.setRequestHeader('X-Chunk-SHA256', digest)
    const abort = () => xhr.abort()
    signal.addEventListener('abort', abort, { once: true })
    xhr.upload.onprogress = event => { file.liveBytes = event.loaded }
    xhr.onload = () => {
      let body = {}
      try { body = JSON.parse(xhr.responseText) } catch (_) { /* 代理可能返回非 JSON 错误 */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body)
      else {
        const error = new Error(typeof body.detail === 'string' ? body.detail : `上传请求失败 HTTP ${xhr.status}`)
        error.status = xhr.status
        if (xhr.status === 401 || xhr.status === 403) void redirectIfSecurityGateExpired()
        reject(error)
      }
    }
    xhr.onerror = () => reject(new Error('网络连接中断，已保留确认断点'))
    xhr.ontimeout = () => reject(new Error('上传超时，已保留确认断点'))
    xhr.onabort = () => reject(new DOMException('传输中止', 'AbortError'))
    xhr.onloadend = () => { signal.removeEventListener('abort', abort); file.liveBytes = 0 }
    if (signal.aborted) reject(new DOMException('传输中止', 'AbortError'))
    else xhr.send(buffer)
  })
}

async function transfer({ session, file, source }) {
  await gate(session)
  if (!source || source.size !== file.size || source.lastModified !== file.last_modified) throw new Error('来源文件信息已改变，请重新选择原来源')
  const checkpoint = await request(session, `/files/${file.id}/checkpoint`)
  // 浏览器重选来源时核验所有已确认分块，避免同名同大小的新内容接到旧文件上。
  for (const chunk of checkpoint.chunks) {
    await gate(session)
    const result = await hash(await source.slice(chunk.offset, chunk.offset + chunk.size).arrayBuffer())
    if (result.digest !== chunk.sha256) throw new Error(`来源分块摘要不匹配：${file.relative_path} @ ${chunk.offset}`)
  }
  let offset = checkpoint.offset
  file.received = offset
  while (offset < source.size) {
    await gate(session)
    const { digest, buffer } = await hash(await source.slice(offset, offset + CHUNK).arrayBuffer())
    await gate(session)
    let done = false
    for (let attempt = 0; attempt < 4 && !done; attempt++) {
      await gate(session)
      const controller = new AbortController()
      file.controller = controller
      const timeout = setTimeout(() => controller.abort(), 120000)
      try {
        file.stage = '上传至服务'
        const result = await sendChunk(session, file, offset, buffer, digest, controller.signal)
        offset = result.offset
        file.received = offset
        file.reason = ''
        file.status = 'receiving'
        done = true
      } catch (error) {
        if (session.status === 'paused') {
          await gate(session)
          attempt--
        } else if (session.status === 'cancelled') throw new DOMException('已取消', 'AbortError')
        else if ((error.status && error.status < 500) || attempt === 3) throw error
        else {
          file.reason = `网络重试 ${attempt + 1}/3：${error.message}`
          await new Promise(resolve => setTimeout(resolve, 500 * 2 ** attempt))
        }
      } finally {
        clearTimeout(timeout)
        file.controller = null
      }
    }
  }
  await gate(session)
  const completed = await request(session, `/files/${file.id}/complete`, { method: 'POST' })
  Object.assign(file, completed)
}

async function discover(session, sources, restore = false) {
  session.enumerationStopped = false
  session.reading = true
  let batch = []
  async function flush() {
    if (!batch.length) return
    await gate(session)
    const current = batch
    batch = []
    const result = await request(session, '/manifest', { method: 'POST', body: JSON.stringify({ entries: current.map(({ file, ...entry }) => entry) }) })
    for (let i = 0; i < current.length; i++) {
      const file = session.files.get(result.files[i].id) || result.files[i]
      Object.assign(file, result.files[i])
      session.files.set(file.id, file)
      if (current[i].file) {
        session.sources.set(file.id, current[i].file)
        if (restore && file.status === 'failed') {
          await controlBrowserUpload(session.id, 'retry', file.id)
        }
        schedule(session, file, current[i].file)
      }
    }
    while (queue.length >= 24) {
      await gate(session)
      await new Promise(resolve => setTimeout(resolve, 25))
    }
    await yieldUploadThread()
  }
  try {
    for await (const entry of enumerateUploadEntries(sources, () => gate(session))) {
      batch.push(entry)
      if (!restore) {
        session.discoveredFiles += entry.is_directory ? 0 : 1
        session.discoveredBytes += entry.size
      }
      if (batch.length >= 32) await flush()
    }
    await flush()
    await request(session, '/manifest', { method: 'POST', body: JSON.stringify({ entries: [], finished: true }) })
    session.enumerated = true
    session.needsSource = false
    session.enumerationError = ''
  } catch (error) {
    if (error.name !== 'AbortError') {
      session.enumerationError = error.message
      session.needsSource = true
      try {
        await request(session, '/actions', { method: 'POST', body: JSON.stringify({ action: 'enumeration_failed', reason: error.message.slice(0, 2000) }) })
      } catch (_) { /* 网络恢复后仍保留本地读取错误与来源重选入口 */ }
    }
  } finally {
    session.reading = false
  }
}

function makeSession(data) {
  return markRaw({ ...data, files: new Map(), sources: new Map(), cursor: 0,
    discoveredFiles: 0, discoveredBytes: 0, speed: 0, backendSpeed: 0, sample: null, notified: '', needsSource: false })
}

export async function startBrowserUpload(target, sources) {
  initializeBrowserUploads()
  const created = await request(null, '', { method: 'POST', body: JSON.stringify({
    library_id: target.libraryId, target_path: target.path,
    source_label: sources.map(s => s.name).join('、').slice(0, 500),
  }) })
  const session = makeSession(created)
  runtime.set(session.id, session)
  remember()
  manager.openWorkbench(UPLOAD_WORKBENCH)
  refreshView()
  void discover(session, sources)
  return session
}

export async function restoreBrowserUploadSource(id, sources) {
  const session = runtime.get(id)
  if (!session || session.reading) return
  if (session.status === 'paused') await controlBrowserUpload(id, 'resume')
  await discover(session, sources, true)
}

export async function controlBrowserUpload(id, action, fileId, decision, applyAll = false) {
  const session = runtime.get(id)
  if (!session) return
  if (action === 'cancel') {
    try {
      await showSystemConfirm({ title: '取消上传', message: '停止读取和传输未完成文件？',
        description: '已写入库存的文件会保留，未完成的暂存内容会清理。', tone: 'warning', confirmText: '取消上传', cancelText: '继续上传' })
    } catch (_) { return }
  }
  if (action === 'pause' || action === 'cancel') {
    session.status = action === 'pause' ? 'paused' : 'cancelled'
    for (const file of session.files.values()) { file.controller?.abort(); file.speed = 0 }
  }
  const file = session.files.get(fileId)
  try {
    if (action === 'retry' && file?.clientFailed) {
      await request(session, '/actions', { method: 'POST', body: JSON.stringify({ action: 'receive_failed', file_id: fileId, reason: file.reason }) })
    }
    const response = await request(session, '/actions', { method: 'POST', body: JSON.stringify({ action, file_id: fileId, decision, apply_all: applyAll }) })
    Object.assign(session, response)
  } catch (error) {
    session.connectionError = `${action === 'cancel' ? '取消' : '操作'}尚未获服务端确认：${error.message}`
    session.snapshotNeeded = true
    throw error
  }
  if (action === 'retry' && file) {
    file.status = file.sha256 ? 'ready' : 'receiving'
    file.clientFailed = false
    file.reason = ''
    schedule(session, file, session.sources.get(fileId))
    if (!session.sources.has(fileId)) session.needsSource = true
  }
  if (action === 'resume') { session.startedSampleAt = performance.now(); session.sample = null; pump() }
  refreshView()
}

async function poll(session) {
  if (session.polling || (stopped.has(session.status) && session.notified === session.status && !session.snapshotNeeded)) return
  session.polling = true
  try {
    if (session.snapshotNeeded) {
      let offset = 0, revision
      do {
        const result = await request(session, `?offset=${offset}&limit=200`)
        if (revision === undefined) revision = result.revision
        for (const incoming of result.files) session.files.set(incoming.id, { ...session.files.get(incoming.id), ...incoming })
        offset += result.files.length
        if (offset >= result.total_entries) break
      } while (true)
      session.cursor = revision || 0
      session.snapshotNeeded = false
    }
    for (const file of session.files.values()) {
      if (file.clientFailed && file.status === 'failed') {
        await request(session, '/actions', { method: 'POST', body: JSON.stringify({ action: 'receive_failed', file_id: file.id, reason: file.reason.slice(0, 2000) }) })
        file.clientFailed = false
      }
    }
    let more = true
    for (let page = 0; page < 4 && more; page++) {
      const result = await request(session, `/changes?cursor=${session.cursor}`)
      const { files, cursor, has_more, ...summary } = result
      Object.assign(session, summary, { cursor })
      for (const incoming of files) {
        const existing = session.files.get(incoming.id)
        if (existing) {
          const localFailed = existing.clientFailed
          if (!existing.busy && !localFailed) Object.assign(existing, incoming)
          else if (incoming.status === 'completed') Object.assign(existing, incoming)
        } else session.files.set(incoming.id, incoming)
      }
      more = has_more
    }
    session.connectionError = ''
    if (!more && !session.index_pending && stopped.has(session.status) && session.notified !== session.status) {
      session.notified = session.status
      const completed = session.counts?.completed || 0
      ElNotification({ title: session.status === 'completed' ? '上传完成' : session.status === 'cancelled' ? '上传已取消' : completed ? '上传部分失败' : '上传失败',
        message: `${session.source_label}：完成 ${completed}，失败 ${session.counts?.failed || 0}，跳过 ${session.counts?.skipped || 0}`,
        type: session.status === 'completed' ? 'success' : 'warning' })
      window.dispatchEvent(new CustomEvent('library-browser-upload-finished', { detail: { libraryId: session.library_id, path: session.target_path } }))
    }
  } catch (error) {
    session.connectionError = error.message
    if (error.status === 409) {
      session.snapshotNeeded = true
    }
  } finally {
    session.polling = false
  }
}

function refreshView() {
  const now = performance.now()
  for (const session of runtime.values()) {
    let received = 0, written = 0, activeFileCount = 0
    for (const file of session.files.values()) {
      if (file.busy && session.status === 'receiving') activeFileCount++
      const live = Math.min(file.size, (file.received || 0) + (file.liveBytes || 0))
      received += live
      written += file.written || 0
      if (file.sample) {
        const elapsed = (now - file.sample.time) / 1000
        const rate = Math.max(0, live - file.sample.bytes) / Math.max(.001, elapsed)
        file.speed = (file.speed || 0) + (1 - Math.exp(-elapsed / 2)) * (rate - (file.speed || 0))
      }
      if (!file.busy || session.status !== 'receiving') file.speed = 0
      file.sample = { time: now, bytes: live }
    }
    if (!session.startedSampleAt) session.startedSampleAt = now
    if (session.sample) {
      const elapsed = (now - session.sample.time) / 1000
      const smoothing = 1 - Math.exp(-elapsed / 2)
      const rate = Math.max(0, received - session.sample.received) / elapsed
      const backend = Math.max(0, written - session.sample.written) / elapsed
      const rates = session.rates || (session.rates = [])
      rates.push(rate)
      if (rates.length > 16) rates.shift()
      const mean = rates.reduce((n, x) => n + x, 0) / rates.length
      session.speedStable = rates.length === 16 && mean > 0 && Math.sqrt(rates.reduce((n, x) => n + (x - mean) ** 2, 0) / rates.length) / mean < .4
      session.speed += smoothing * (rate - session.speed)
      session.backendSpeed += smoothing * (backend - session.backendSpeed)
      if (rate) session.lastBytesAt = now
      if (backend) session.lastWrittenAt = now
    }
    session.sample = { time: now, received, written }
    if (session.status !== 'receiving' || now - (session.lastBytesAt || 0) > 3000) session.speed = 0
    if (session.status !== 'receiving' || now - (session.lastWrittenAt || 0) > 3000) session.backendSpeed = 0
    session.liveReceived = received
    session.liveWritten = written
    session.activeFileCount = activeFileCount
  }
  browserUploads.value = Array.from(runtime.values(), session => ({ ...session }))
}

export async function refreshBrowserUploads() {
  await Promise.all(Array.from(runtime.values(), session => poll(session)))
  refreshView()
}

export function initializeBrowserUploads() {
  if (initialized) return
  initialized = true
  manager.registerWorkbench({ id: UPLOAD_WORKBENCH, type: 'upload', title: '库存拖拽上传',
    onAction: action => { if (action === 'resume') manager.openWorkbench(UPLOAD_WORKBENCH) },
    onClose: () => manager.backgroundWorkbench(UPLOAD_WORKBENCH) })
  let saved = []
  try { saved = JSON.parse(localStorage.getItem(STORAGE) || '[]') } catch (_) { /* 无历史会话 */ }
  for (const item of saved) {
    if (!item.id || !item.token) continue
    const session = makeSession({ ...item, status: 'receiving', source_label: '恢复上传', needsSource: true, snapshotNeeded: true })
    session.needsSource = true
    runtime.set(item.id, session)
    void poll(session)
  }
  let polling = false
  setInterval(async () => {
    if (polling) return
    polling = true
    try { await Promise.all(Array.from(runtime.values(), session => poll(session))) } finally { polling = false }
    if (runtime.size) manager.patchWorkbenchState(UPLOAD_WORKBENCH, {
      summary: { subtitle: `${runtime.size} 个上传批次`, text: Array.from(runtime.values()).filter(s => s.status === 'receiving').length + ' 个传输中' },
      metrics: [{ key: 'speed', label: '上传速度', value: formatUploadBytes(Array.from(runtime.values()).reduce((n, s) => n + s.speed, 0)) + '/s' }],
    })
  }, 1500)
  setInterval(refreshView, 250)
}

export function formatUploadBytes(value) {
  let size = Number(value || 0), unit = 0
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit++ }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`
}
