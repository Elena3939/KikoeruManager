import { describe, expect, it } from 'vitest'
import { buildTaskProgress, parseTaskProgressPayload, TASK_PROGRESS_PREFIX } from './logProgress.js'

function parseProgress(status, step, progress = 100) {
  const taskProgressPayload = parseTaskProgressPayload(TASK_PROGRESS_PREFIX + JSON.stringify({
    version: 1, task_id: 'task-1234', status, step, progress, phase: '下载',
  }))
  return buildTaskProgress({ taskProgressPayload })
}

describe('日志使用后端任务状态和进度', () => {
  it('成功状态不受失败、异常等文案影响', () => {
    const result = parseProgress('completed', '下载完成，成功 1 个，失败 0 个；此前发生异常')
    expect(result.tone).toBe('success')
    expect(result.active).toBe(false)
    expect(result.progress).toBe(100)
    expect(result.detail).toContain('失败 0 个')
  })

  it.each(['failed', 'partial_failed'])('真实失败状态不受成功文案和百分比影响：%s', (status) => {
    expect(parseProgress(status, '下载成功', 100).tone).toBe('error')
  })

  it('后端尚在处理时，100% 和完成字样不能决定任务成功', () => {
    const result = parseProgress('processing', '下载完成，正在后处理', 100)
    expect(result.tone).toBe('processing')
    expect(result.active).toBe(true)
  })

  it('进度直接取后端数值，不解析文字里的百分比', () => {
    expect(parseProgress('processing', '下载完成 100%', 37).progress).toBe(37)
  })

  it.each([
    ['pending', 'waiting'], ['paused', 'paused'], ['waiting_retry', 'waiting'],
    ['waiting_manual', 'waiting'], ['cancelled', 'paused'],
  ])('状态完全由后端字段决定：%s', (status, tone) => {
    const result = parseProgress(status, '成功或异常', 50)
    expect(result.tone).toBe(tone)
    expect(result.active).toBe(false)
  })

  it.each([
    '任务 task-1234: 下载完成，成功 1 个，失败 0 个 (100%)',
    TASK_PROGRESS_PREFIX + '{',
    TASK_PROGRESS_PREFIX + JSON.stringify({ version: 1, task_id: 'a', status: 'unknown', progress: 100 }),
    TASK_PROGRESS_PREFIX + JSON.stringify({ version: 1, task_id: 'a', status: 'completed', progress: '100' }),
  ])('旧日志和无效结构只展示原文，不猜测状态：%s', (message) => {
    expect(parseTaskProgressPayload(message)).toBeNull()
  })
})
