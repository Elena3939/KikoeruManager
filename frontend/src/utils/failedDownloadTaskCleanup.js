import { asmrSyncApi, taskApi, taskCenterApi } from '../api'
import { getAsmrDownloadSessionId, getDownloadEngineTaskId } from './downloadTaskIdentity.js'

export async function cleanupFailedDownloadTask(task) {
  if (!['failed', 'partial_failed'].includes(String(task?.display_status || task?.status || ''))) return

  const taskIds = [...new Set(
    (task?.source_task_ids?.length ? task.source_task_ids : [getDownloadEngineTaskId(task)])
      .map(id => String(id || '').trim()).filter(Boolean),
  )]
  if (!taskIds.length) throw new Error('无法识别下载任务')

  const sessionId = getAsmrDownloadSessionId(task)
  if (sessionId) {
    await asmrSyncApi.cancelSession(sessionId, { cleanup: true })
  } else {
    const result = await taskApi.batchCancelCleanup(taskIds)
    if (result.errors?.length) throw new Error('下载缓存清理失败，请重试关闭')
  }
  // 缓存清理完成后再删除记录，失败时保留任务以便重试。
  for (const taskId of taskIds) {
    try {
      await taskCenterApi.action(`engine:${taskId}`, 'delete')
    } catch (error) {
      // 合并任务部分删除后重试时，已删除的分卷不应阻止剩余任务清理。
      if (error.response?.status !== 400 || error.response?.data?.detail !== '任务不存在') throw error
    }
  }
}
