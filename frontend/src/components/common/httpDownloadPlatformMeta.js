import { defineComponent, h } from 'vue'
import gofileIconUrl from '../../assets/platforms/gofile.png'
import googleDriveIconUrl from '../../assets/platforms/google-drive.ico'
import onedriveIconUrl from '../../assets/platforms/onedrive.ico'
import pikpakIconUrl from '../../assets/platforms/pikpak.png'
import transferitIconUrl from '../../assets/platforms/transferit.ico'

const PLATFORM_ICON_URLS = {
  gofile: gofileIconUrl,
  transferit: transferitIconUrl,
  onedrive: onedriveIconUrl,
  google_drive: googleDriveIconUrl,
  pikpak: pikpakIconUrl,
}

function createPlatformIconComponent(src, label) {
  return defineComponent({
    name: `${String(label || 'HttpPlatform').replace(/[^a-z0-9]+/gi, '') || 'HttpPlatform'}Icon`,
    setup() {
      return () => h('img', {
        src,
        alt: label,
        draggable: 'false',
        class: 'http-platform-icon',
      })
    },
  })
}

const GOFILE_ICON = createPlatformIconComponent(PLATFORM_ICON_URLS.gofile, 'Gofile')
const GOOGLE_DRIVE_ICON = createPlatformIconComponent(PLATFORM_ICON_URLS.google_drive, 'Google Drive')
const ONEDRIVE_ICON = createPlatformIconComponent(PLATFORM_ICON_URLS.onedrive, 'OneDrive')
const PIKPAK_ICON = createPlatformIconComponent(PLATFORM_ICON_URLS.pikpak, 'PikPak')
const TRANSFERIT_ICON = createPlatformIconComponent(PLATFORM_ICON_URLS.transferit, 'Transfer.it')

export const HTTP_DOWNLOAD_PLATFORM_META = {
  http: {
    key: 'http',
    label: 'HTTP',
    title: 'HTTP 下载',
    icon: '',
    iconSrc: '',
    aliases: ['http', 'https', 'direct', 'direct_link']
  },
  gofile: {
    key: 'gofile',
    label: 'Gofile',
    title: 'Gofile 下载',
    icon: GOFILE_ICON,
    iconSrc: PLATFORM_ICON_URLS.gofile,
    aliases: ['gofile', 'gofile.io']
  },
  transferit: {
    key: 'transferit',
    label: 'Transfer.it',
    title: 'Transfer.it 下载',
    icon: TRANSFERIT_ICON,
    iconSrc: PLATFORM_ICON_URLS.transferit,
    aliases: ['transferit', 'transfer.it']
  },
  onedrive: {
    key: 'onedrive',
    label: 'OneDrive',
    title: 'OneDrive 下载',
    icon: ONEDRIVE_ICON,
    iconSrc: PLATFORM_ICON_URLS.onedrive,
    aliases: ['onedrive', 'one_drive', '1drv', '1drv.ms', 'onedrive.live.com', 'onedrive.com']
  },
  google_drive: {
    key: 'google_drive',
    label: 'Google Drive',
    title: 'Google Drive 下载',
    icon: GOOGLE_DRIVE_ICON,
    iconSrc: PLATFORM_ICON_URLS.google_drive,
    aliases: ['google_drive', 'google-drive', 'googledrive', 'drive.google.com', 'docs.google.com']
  },
  pikpak: {
    key: 'pikpak',
    label: 'PikPak',
    title: 'PikPak 下载',
    icon: PIKPAK_ICON,
    iconSrc: PLATFORM_ICON_URLS.pikpak,
    aliases: ['pikpak', 'mypikpak.com', 'drive.mypikpak.com']
  }
}

const ALIAS_TO_KEY = Object.values(HTTP_DOWNLOAD_PLATFORM_META).reduce((map, meta) => {
  meta.aliases.forEach(alias => { map[alias] = meta.key })
  return map
}, {})

function extractPlatformKeysFromText(text) {
  const raw = String(text || '').trim().toLowerCase()
  if (!raw) return []
  const matched = []
  const aliasEntries = Object.entries(ALIAS_TO_KEY)
    .sort((a, b) => String(b[0]).length - String(a[0]).length)
  for (const [alias, key] of aliasEntries) {
    if (!alias) continue
    if (raw.includes(alias) && !matched.includes(key)) matched.push(key)
  }
  return matched
}

export function getHttpDownloadPlatformKey(value) {
  const raw = String(value || '').trim().toLowerCase()
  if (!raw) return 'http'
  const normalized = raw.replace(/[^a-z0-9._-]+/g, '_')
  if (ALIAS_TO_KEY[raw]) return ALIAS_TO_KEY[raw]
  if (ALIAS_TO_KEY[normalized]) return ALIAS_TO_KEY[normalized]
  if (raw.includes('gofile.io')) return 'gofile'
  if (raw.includes('transfer.it')) return 'transferit'
  if (raw.includes('1drv.ms') || raw.includes('onedrive')) return 'onedrive'
  if (raw.includes('drive.google.com') || raw.includes('docs.google.com') || raw.includes('google drive')) return 'google_drive'
  if (raw.includes('mypikpak.com') || raw.includes('drive.mypikpak.com') || raw.includes('pikpak')) return 'pikpak'
  return HTTP_DOWNLOAD_PLATFORM_META[normalized] ? normalized : 'http'
}

export function getHttpDownloadPlatformMeta(value) {
  return HTTP_DOWNLOAD_PLATFORM_META[getHttpDownloadPlatformKey(value)] || HTTP_DOWNLOAD_PLATFORM_META.http
}

function pushPlatform(list, value) {
  const text = String(value || '').trim()
  if (!text) return
  const keys = extractPlatformKeysFromText(text)
  if (keys.length) {
    keys.forEach((key) => {
      if (key && !list.includes(key)) list.push(key)
    })
    return
  }
  const key = getHttpDownloadPlatformKey(text)
  if (!key || list.includes(key)) return
  list.push(key)
}

function pushDirectPlatform(list, value) {
  const text = String(value || '').trim()
  if (!text) return
  const key = getHttpDownloadPlatformKey(text)
  if (!key || list.includes(key)) return
  list.push(key)
}

function pushUrlPlatform(list, value) {
  pushPlatform(list, value)
}

export function httpDownloadPlatformsFromUrl(url) {
  return getHttpDownloadPlatformKey(url)
}

export function httpDownloadPlatformsFromItem(item) {
  if (!item || typeof item !== 'object') return ['http']
  const platforms = []
  const directSources = Array.isArray(item.platforms)
    ? item.platforms
    : (Array.isArray(item.source_modes) ? item.source_modes : [])
  directSources.forEach(value => pushDirectPlatform(platforms, value))
  pushDirectPlatform(platforms, item.download_mode)
  pushDirectPlatform(platforms, item.source)

  const metadata = item.task_metadata || item.metadata || item.detail || item.details?.metadata || {}
  if (metadata && typeof metadata === 'object') {
    ;(Array.isArray(metadata.source_modes) ? metadata.source_modes : []).forEach(value => pushDirectPlatform(platforms, value))
    ;(Array.isArray(metadata.platforms) ? metadata.platforms : []).forEach(value => pushDirectPlatform(platforms, value))
    pushDirectPlatform(platforms, metadata.download_mode)
    pushDirectPlatform(platforms, metadata.source)
    ;(Array.isArray(metadata.download_files) ? metadata.download_files : []).forEach(file => {
      if (!file || typeof file !== 'object') return
      pushDirectPlatform(platforms, file.source)
      pushUrlPlatform(platforms, file.url)
    })
  }
  const routeQuery = item.route_query
  if (routeQuery && typeof routeQuery === 'object') {
    ;(Array.isArray(routeQuery.platforms)
      ? routeQuery.platforms
      : String(routeQuery.platforms || '').split(',')
    ).forEach(value => pushDirectPlatform(platforms, value))
    pushDirectPlatform(platforms, routeQuery.download_mode)
    pushDirectPlatform(platforms, routeQuery.platform_label)
  }

  if (platforms.some(key => key !== 'http')) {
    return platforms.filter((key, index) => key && platforms.indexOf(key) === index)
  }

  pushPlatform(platforms, item.source_action)
  pushPlatform(platforms, item.source_label)
  pushPlatform(platforms, item.platform_label)
  pushPlatform(platforms, item.domain_label)
  pushPlatform(platforms, item.title)
  pushPlatform(platforms, item.summary)
  pushPlatform(platforms, item.source_path)
  if (metadata && typeof metadata === 'object') {
    pushPlatform(platforms, metadata.source_action)
    pushPlatform(platforms, metadata.source_label)
    pushPlatform(platforms, metadata.platform_label)
  }

  if (!platforms.length) platforms.push('http')
  return platforms
}

export function uniqueHttpDownloadPlatforms(values) {
  const platforms = []
  ;(Array.isArray(values) ? values : [values]).forEach(value => pushPlatform(platforms, value))
  if (!platforms.length) platforms.push('http')
  return platforms
}

export function httpDownloadPlatformLabelFromItem(item) {
  const platforms = httpDownloadPlatformsFromItem(item).filter(key => key !== 'http')
  if (!platforms.length) return HTTP_DOWNLOAD_PLATFORM_META.http.label
  if (platforms.length === 1) return HTTP_DOWNLOAD_PLATFORM_META[platforms[0]]?.label || platforms[0]
  const labels = platforms.map(key => HTTP_DOWNLOAD_PLATFORM_META[key]?.label || key)
  return labels.length > 2 ? `${labels.slice(0, 2).join(' / ')} 等 ${labels.length} 平台` : labels.join(' / ')
}

export function getHttpDownloadDisplayMeta(item) {
  const platforms = httpDownloadPlatformsFromItem(item)
  const specificPlatforms = platforms.filter(key => key !== 'http')
  const primaryKey = specificPlatforms[0] || 'http'
  const primaryMeta = HTTP_DOWNLOAD_PLATFORM_META[primaryKey] || HTTP_DOWNLOAD_PLATFORM_META.http
  const label = httpDownloadPlatformLabelFromItem(item)
  return {
    key: primaryKey,
    label,
    title: specificPlatforms.length > 1 ? `${label} 下载` : (primaryMeta.title || 'HTTP 下载'),
    icon: primaryMeta.icon || '',
    iconSrc: primaryMeta.iconSrc || '',
    iconLabel: primaryMeta.label,
    platforms,
    platformCount: specificPlatforms.length,
    isMixed: specificPlatforms.length > 1,
  }
}

export function getHttpDownloadTaskTitle(item, fallback = 'HTTP 下载') {
  const meta = getHttpDownloadDisplayMeta(item)
  const count = Number(item?.download_files?.length || item?.selected_count || item?.url_count || 0)
  if (count > 1) return `${meta.label} 下载 ${count} 项`
  if (count === 1) return meta.title || fallback
  return meta.title || fallback
}
