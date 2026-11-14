export const downloadSources = [
  { id: 'asmr.one', label: 'asmr.one', selection: 'file', transport: 'asmr' },
  { id: 'imoutoheaven', label: 'YAAS', selection: 'single-group', transport: 'http' },
  { id: 'link_sheet', label: '妙蛙种子', selection: 'groups', transport: 'http' },
]

export function isHttpDownloadTask(task) {
  return String(task?.type || task?.task_type || task?.task_kind || task?.task_metadata?.task_kind || '') === 'http_download'
    || downloadSources.some(source => source.transport === 'http' && source.id === task?.task_metadata?.resource_source)
}
