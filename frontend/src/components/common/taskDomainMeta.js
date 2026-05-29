import {
  Activity,
  Captions,
  Database,
  Download,
  FileArchive,
  Sparkles,
  Upload,
  UploadCloud,
} from 'lucide-vue-next'

// 简约高级风：标签全部用中性 slate，颜色只保留在图标上
// chip / iconWrap / iconWrapActive 都是 neutral；icon 自身用 chipIcon 上色
// 所有 class 字符串必须是字面量，给 Tailwind JIT 扫到
const NEUTRAL_CHIP = 'border-slate-200 bg-slate-50 text-slate-700'
const NEUTRAL_WRAP = 'border-slate-200 bg-white text-slate-700'
const NEUTRAL_WRAP_ACTIVE = 'border-slate-300 bg-slate-100 text-slate-900'

export const TASK_DOMAIN_META = {
  import: {
    label: '导入处理',
    icon: FileArchive,
    chip: NEUTRAL_CHIP,
    iconWrap: NEUTRAL_WRAP,
    iconWrapActive: NEUTRAL_WRAP_ACTIVE,
    chipIcon: 'text-amber-600',
    chipBg: 'bg-amber-50',
    chipText: 'text-amber-700',
    barIcon: 'text-amber-600',
    bar: 'bg-amber-500',
    badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
  },
  rj_subtitle: {
    label: 'RJ 字幕',
    icon: Captions,
    chip: NEUTRAL_CHIP,
    iconWrap: NEUTRAL_WRAP,
    iconWrapActive: NEUTRAL_WRAP_ACTIVE,
    chipIcon: 'text-sky-600',
    chipBg: 'bg-sky-50',
    chipText: 'text-sky-700',
    barIcon: 'text-sky-600',
    bar: 'bg-sky-500',
    badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
  },
  subtitle_import: {
    label: '字幕补配',
    icon: Sparkles,
    chip: NEUTRAL_CHIP,
    iconWrap: NEUTRAL_WRAP,
    iconWrapActive: NEUTRAL_WRAP_ACTIVE,
    chipIcon: 'text-violet-600',
    chipBg: 'bg-violet-50',
    chipText: 'text-violet-700',
    barIcon: 'text-violet-600',
    bar: 'bg-violet-500',
    badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
  },
  asmr_sync: {
    label: 'ASMR 同步',
    icon: UploadCloud,
    chip: NEUTRAL_CHIP,
    iconWrap: NEUTRAL_WRAP,
    iconWrapActive: NEUTRAL_WRAP_ACTIVE,
    chipIcon: 'text-emerald-600',
    chipBg: 'bg-emerald-50',
    chipText: 'text-emerald-700',
    barIcon: 'text-emerald-600',
    bar: 'bg-emerald-500',
    badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
  },
  http_download: {
    label: 'HTTP 下载',
    icon: Download,
    chip: NEUTRAL_CHIP,
    iconWrap: NEUTRAL_WRAP,
    iconWrapActive: NEUTRAL_WRAP_ACTIVE,
    chipIcon: 'text-orange-600',
    chipBg: 'bg-orange-50',
    chipText: 'text-orange-700',
    barIcon: 'text-orange-600',
    bar: 'bg-orange-500',
    badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
  },
  upload: {
    label: '库存上传',
    icon: Upload,
    chip: NEUTRAL_CHIP,
    iconWrap: NEUTRAL_WRAP,
    iconWrapActive: NEUTRAL_WRAP_ACTIVE,
    chipIcon: 'text-blue-600',
    chipBg: 'bg-blue-50',
    chipText: 'text-blue-700',
    barIcon: 'text-blue-600',
    bar: 'bg-blue-500',
    badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
  },
  circle_completion: {
    label: '社团补全',
    icon: Database,
    chip: NEUTRAL_CHIP,
    iconWrap: NEUTRAL_WRAP,
    iconWrapActive: NEUTRAL_WRAP_ACTIVE,
    chipIcon: 'text-teal-600',
    chipBg: 'bg-teal-50',
    chipText: 'text-teal-700',
    barIcon: 'text-teal-600',
    bar: 'bg-teal-500',
    badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
  },
  system: {
    label: '系统任务',
    icon: Activity,
    chip: NEUTRAL_CHIP,
    iconWrap: NEUTRAL_WRAP,
    iconWrapActive: NEUTRAL_WRAP_ACTIVE,
    chipIcon: 'text-slate-600',
    chipBg: 'bg-slate-100',
    chipText: 'text-slate-700',
    barIcon: 'text-slate-600',
    bar: 'bg-slate-700',
    badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
  },
}

export function getTaskDomainMeta(domain) {
  return TASK_DOMAIN_META[domain] || TASK_DOMAIN_META.system
}

const CONFLICTS_META = {
  label: '问题作品',
  chip: NEUTRAL_CHIP,
  iconWrap: NEUTRAL_WRAP,
  iconWrapActive: NEUTRAL_WRAP_ACTIVE,
  chipIcon: 'text-rose-600',
  barIcon: 'text-rose-600',
  bar: 'bg-rose-500',
  badgeHover: 'group-hover:bg-slate-900 group-hover:text-white',
}

export const KPI_META = {
  import: TASK_DOMAIN_META.import,
  rj: TASK_DOMAIN_META.rj_subtitle,
  subtitle: TASK_DOMAIN_META.subtitle_import,
  asmr: TASK_DOMAIN_META.asmr_sync,
  upload: TASK_DOMAIN_META.upload,
  conflicts: CONFLICTS_META,
}

export function getKpiMeta(key) {
  return KPI_META[key] || TASK_DOMAIN_META.system
}
