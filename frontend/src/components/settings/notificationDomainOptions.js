import {
  Activity,
  Captions,
  Cloud,
  Database,
  Download,
  FileArchive,
  FolderOpen,
  Sparkles,
  Upload,
  UploadCloud,
} from 'lucide-vue-next'

export const NOTIFICATION_TASK_DOMAINS = [
  { value: 'import', label: '导入处理', icon: FileArchive },
  { value: 'existing_folder', label: '已有文件夹', icon: FolderOpen },
  { value: 'rj_subtitle', label: 'RJ 字幕', icon: Captions },
  { value: 'subtitle_import', label: '字幕补配', icon: Sparkles },
  { value: 'asmr_sync', label: 'ASMR 同步', icon: UploadCloud },
  { value: 'http_download', label: 'HTTP 下载', icon: Download },
  { value: 'baidu_netdisk', label: '百度网盘', icon: Cloud },
  { value: 'upload', label: '库存上传', icon: Upload },
  { value: 'circle_completion', label: '社团补全', icon: Database },
  { value: 'system', label: '系统任务', icon: Activity },
]

export const NOTIFICATION_TASK_DOMAIN_LABELS = Object.fromEntries(
  NOTIFICATION_TASK_DOMAINS.map(item => [item.value, item.label])
)

export const NOTIFICATION_TASK_DOMAIN_OPTIONS = NOTIFICATION_TASK_DOMAINS.map(({ value, label }) => ({
  value,
  label,
}))
