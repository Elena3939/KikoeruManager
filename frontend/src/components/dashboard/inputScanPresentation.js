const skipLabels = {
  deferred_archive: '归档占用',
  problem: '问题作品占用',
  task: '已有任务占用',
  task_waiting_retry: '等待重试占用',
  task_waiting_manual: '等待人工占用',
  task_pending: '排队任务占用',
  task_processing: '处理中任务占用',
  task_paused: '已暂停任务占用',
}

export function skipReasonLabel(key) {
  return skipLabels[key] || '其他占用或跳过原因'
}

export function describeCandidate(item) {
  if (item.state === 'skipped') return skipReasonLabel(String(item.reason || '').split(':')[0])
  if (item.state === 'failed') return `失败：${item.reason === 'source_not_stable' ? '文件稳定等待超时' : item.reason || '未知原因'}`
  if (item.state === 'routed') return ({ problem: '已转入问题作品', subtitle: '已转入字幕流程' })[item.destination] || '已转入其他流程'
  return ({ submitted: '已交接', cancelled: '已取消', waiting_stable: '等待文件稳定', ready: '等待交接', preflight: '预检中', discovered: '待预检' })[item.state] || '待处理'
}
