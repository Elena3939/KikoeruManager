// 执行工作台真实函数，检查抓取未落盘时不会误读目录或覆盖运行态。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import vm from 'node:vm'

const root = resolve(import.meta.dirname, '..')
const require = createRequire(resolve(root, 'frontend/package.json'))
const { parse: parseVue } = require('@vue/compiler-sfc')
const { parse } = require('@babel/parser')
const librarySource = parseVue(readFileSync(resolve(root, 'frontend/src/views/Library.vue'), 'utf8')).descriptor.scriptSetup.content
const taskSource = readFileSync(resolve(root, 'frontend/src/composables/useSubtitleTask.js'), 'utf8')
const libraryFunctions = parse(librarySource, { sourceType: 'module' }).program.body
const taskFunctions = parse(taskSource, { sourceType: 'module' }).program.body
  .find(node => node.type === 'ExportNamedDeclaration' && node.declaration?.id?.name === 'useSubtitleTask').declaration.body.body

function load(name, context, source = librarySource, nodes = libraryFunctions) {
  const node = nodes.find(node => node.type === 'FunctionDeclaration' && node.id.name === name)
  assert.ok(node, `缺少真实函数 ${name}`)
  vm.runInContext(source.slice(node.start, node.end), context)
}

const task = { id: 'fetch-task', status: 'processing', folder_path: '/library/RJ01394137', force_rerun: false, subtitle_dir: '' }
const calls = []
const ref = value => ({ value })
const context = vm.createContext({
  matched: task,
  findSubtitleTaskBySelection: () => context.matched,
  subtitlePreferredSelectionKey: ref(''),
  selectedLibraryId: ref('library'),
  buildSubtitleSelectionKey: item => item.folder_path,
  focusSubtitleTask: id => calls.push(['focus', id]),
  syncSubtitleSelectionState: () => calls.push(['sync']),
  beginSubtitleInspectorRequest: () => { throw new Error('未落盘时不能请求目录') },
  subtitleRouteFocusKey: ref(''),
  subtitleDialogVisible: ref(false),
  subtitleDialogBackgroundActive: ref(false),
  getSubtitleRouteFocusPayload: () => ({ shouldOpen: true, taskId: task.id, folderPath: task.folder_path, libraryId: 'library', stage: 'pairing', focusKey: 'focus' }),
  looksLikeSubtitleTargetFolderPath: Boolean,
  extractRJCode: () => 'RJ01394137',
  resolveLibraryIdByPath: () => 'library',
  getFileName: path => String(path || '').split('/').pop(),
  buildSubtitleHistoryRestoreSelectionItem: value => value,
  seedSubtitleHistoryRestoreSelection: value => value,
  setSubtitleWorkbenchRailMode: mode => calls.push(['rail', mode]),
  setActiveSubtitleWorkbenchStage: stage => calls.push(['stage', stage]),
  nextTick: async () => {},
  refreshRJSubtitleStatus: async () => {},
  setSubtitleTaskFilter: () => {},
  setSubtitleTaskManualFilter: () => {},
  findSubtitleWorkbenchTaskById: () => context.matched,
  clearSubtitleRouteFocusQuery: async () => calls.push(['clear-route']),
  upsertSubtitleTaskLocal: () => { throw new Error('不能用历史恢复覆盖正在运行的任务') }
})
load('shouldDelayAutoInspectSubtitleTree', context, taskSource, taskFunctions)
vm.runInContext('function isSubtitleTaskRerunLocked(task) { return shouldDelayAutoInspectSubtitleTree(task) }', context)
for (const name of ['shouldDelayAutoInspectSelectionFolder', 'canInspectSubtitleSelectionFolder', 'inspectSubtitleSelectionFolder', 'consumeSubtitleRouteFocus']) load(name, context)
context.isActivityHistorySubtitleRestoreItem = () => true
context.joinFolderPath = (...parts) => parts.join('/')

for (const status of ['pending', 'processing', 'paused', 'waiting_retry']) {
  task.status = status
  context.subtitleRouteFocusKey.value = ''
  assert.equal(context.shouldDelayAutoInspectSubtitleTree(task), true)
  assert.equal(context.canInspectSubtitleSelectionFolder({ folder_path: task.folder_path }), false)
  await context.inspectSubtitleSelectionFolder({ folder_path: task.folder_path, source_mode: 'activity_history_restore' })
  await context.consumeSubtitleRouteFocus()
  assert.ok(calls.some(call => call[0] === 'stage' && call[1] === 'overview'))
  calls.length = 0
}
task.subtitle_dir = '/library/RJ01394137/subtitles'
assert.equal(context.shouldDelayAutoInspectSubtitleTree(task), false)
task.subtitle_dir = ''
task.status = 'completed'
assert.equal(context.shouldDelayAutoInspectSubtitleTree(task), false)
assert.equal(context.canInspectSubtitleSelectionFolder({ folder_path: task.folder_path }), true)
context.matched = null
assert.equal(context.canInspectSubtitleSelectionFolder({ folder_path: task.folder_path }), true)

// 任务中心只有作品路径时，恢复模型不能凭空生成 subtitles；已有 AI 目录保持原值。
Object.assign(context, {
  resolveTaskCenterItemMetadata: item => item.metadata || {},
  pickSubtitleRestoreText: (...values) => String(values.find(value => value !== undefined && value !== null && value !== '') || ''),
  pickSubtitleRestoreArray: value => Array.isArray(value) ? value : [],
  pickSubtitleRestoreObject: value => value || {},
  pickSubtitleRestoreNumber: value => Number(value || 0)
})
load('normalizeSubtitleTaskFromTaskCenterItem', context)
const restored = context.normalizeSubtitleTaskFromTaskCenterItem({ engine_task_id: 'task', status: 'processing', metadata: { folder_path: task.folder_path } })
assert.equal(restored.subtitle_dir, '')
assert.equal(restored.snapshot.subtitle_dir, '')
const aiPath = `${task.folder_path}/subtitles_ai`
const restoredAi = context.normalizeSubtitleTaskFromTaskCenterItem({ engine_task_id: 'task', metadata: { folder_path: task.folder_path, subtitle_dir: aiPath } })
assert.equal(restoredAi.subtitle_dir, aiPath)
console.log('通过：首次抓取、排队、暂停、等待重试、历史入口、目录发布及真实字幕路径恢复')
