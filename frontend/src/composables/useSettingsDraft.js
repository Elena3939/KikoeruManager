import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { showSystemConfirm } from './useSystemPrompt'
import { useConfigStore } from '../stores'
import { configApi } from '../api'

export const SYNOLOGY_PROFILE_FIELDS = [
  'base_url',
  'username',
  'password',
  'otp_code',
  'device_name',
  'device_id',
  'enable_device_token',
  'session_name',
  'timeout',
  'verify_ssl'
]

export function createDefaultSynologyProfile(index = 1) {
  return {
    id: `synology-profile-${index}`,
    name: `群晖连接 ${index}`,
    base_url: '',
    username: '',
    password: '',
    otp_code: '',
    device_name: '',
    device_id: '',
    enable_device_token: true,
    session_name: 'FileStation',
    timeout: 30,
    verify_ssl: true
  }
}

export function normalizeSynologyProfile(profile, index = 1) {
  return {
    ...createDefaultSynologyProfile(index),
    ...(profile || {})
  }
}

export function createDefaultLibrary(type = 'local', index = 1) {
  return {
    id: type === 'synology_filestation' ? `remote-library-${index}` : `local-library-${index}`,
    name: type === 'synology_filestation' ? `远程库存 ${index}` : `本地库存 ${index}`,
    type,
    path: '',
    browse_path: '',
    enabled: true,
    writable: true,
    description: '',
    tags: [],
    synology_profile_id: '',
    synology: {
      base_url: '',
      username: '',
      password: '',
      root_path: '/',
      otp_code: '',
      device_name: '',
      device_id: '',
      enable_device_token: true,
      session_name: 'FileStation',
      timeout: 30,
      verify_ssl: true
    }
  }
}

export function normalizeLibraryConfig(library, index = 1) {
  const base = createDefaultLibrary(library?.type || 'local', index)
  const normalized = {
    ...base,
    ...(library || {}),
    synology: {
      ...base.synology,
      ...(library?.synology || {})
    }
  }
  if (normalized.type === 'synology_filestation') {
    normalized.synology.root_path = normalized.synology.root_path || normalized.path || '/'
    normalized.path = normalized.synology.root_path
    if (!normalized.synology_profile_id) {
      normalized.synology.device_name = normalized.synology.device_name || normalized.name || normalized.id
    }
  }
  return normalized
}

export const defaultConfig = {
  storage: {
    input_path: '/input',
    temp_path: '/temp',
    library_path: '/library',
    processed_archives_path: '/processed',
    existing_folders_path: '/existing',
    asmr_subtitle_path: '',
    synology_profiles: [],
    libraries: [],
    default_library_id: '',
    default_extract_library_id: '',
    health_warning_free_gb: 200,
    stats_cache_ttl_seconds: 300
  },
  processing: {
    max_workers: 4
  },
  watcher: {
    enabled: true,
    scan_interval: 30,
    auto_start: true,
    auto_classify: true,
    delete_after_process: false
  },
  extract: {
    seven_zip_path: '7z',
    auto_repair_extension: true,
    verify_after_extract: true,
    password_list: [],
    filename_password_sniff_enabled: true,
    filename_password_sniff_templates: ['{name}({password})', '{name}（{password}）'],
    extract_nested_archives: true,
    max_nested_depth: 5,
    zip_encoding: 932,
    // 0 = auto：后端启动时探测 temp_path 所在盘，SSD → 最多并发 3，HDD / 未知 → 1
    max_concurrent_extractions: 0,
    seven_zip_threads: 'on',
    prefer_unar_for_rar: true
  },
  filter: {
    enabled: true,
    filter_dir: true,
    rules: [
      { name: '过滤无 SE 的文件', pattern: '(?:SE|音 | 音效)(?:[な無] し|CUT)|(?:無 | なし)(?:SE|音 | 音效)', target: 'file', action: 'exclude', enabled: true },
      { name: '过滤无 SE 的文件夹', pattern: '(?:SE|音 | 音效)(?:[な無] し|CUT)|(?:無 | なし)(?:SE|音 | 音效)', target: 'folder', action: 'exclude', enabled: true },
      { name: '过滤 MP3 文件', pattern: '\\.mp3$', target: 'file', action: 'exclude', enabled: false }
    ]
  },
  metadata: {
    locale: 'zh_cn',
    cache_enabled: true,
    fetch_cover: true,
    make_folder_icon: true,
    http_proxy: ''
  },
  rename: {
    template: '{rjcode} {work_name}',
    date_format: '%y%m%d',
    exclude_square_brackets: false,
    illegal_char_to_full_width: true,
    api_rename_follow_template: true,
    use_japanese_metadata: false,
    flatten_single_subfolder: false,
    flatten_depth: 3,
    remove_empty_folders: true
  },
  password_cleanup: {
    enabled: false,
    max_use_count: 2,
    preserve_days: 30,
    cron_expression: '0 0 * * 0',
    exclude_sources: []
  },
  archive_cleanup: {
    enabled: false,
    preserve_days: 7,
    min_keep_count: 10,
    cron_expression: '0 0 * * 0'
  },
  backup_zip: {
    enabled: false,
    source_path: '',
    output_dir: '',
    path_copy_target: '',
    copy_structure_before_zip: true,
    password: '',
    archive_format: 'zip',
    compression_level: 9,
    compression_threads: 0
  },
  path_mappings: [],
  path_mapping_enabled: false,
  kikoeru_server: {
    enabled: false,
    server_url: '',
    username: '',
    password: '',
    api_token: '',
    token_expires: 0,
    timeout: 10,
    cache_ttl: 300,
    enable_fuzzy_rj_match: false,
    http_proxy: '',
    check_in_preextract: true,
    retry_count: 3,
    retry_delay: 1.0
  },
  asmr_sync: {
    enabled: true,
    api_base_url: 'https://api.asmr-200.com/api',
    max_concurrent_downloads: 3,
    enhanced_max_parallel_sessions: 5,
    enhanced_per_session_concurrency: 3,
    http_proxy: '',
    retry_interval_hours: 1.0,
    max_retry_count: 10,
    retry_cron: '0 */1 * * *',
    retry_count: 3,
    retry_delay: 5,
    download_timeout_seconds: 60,
    md5_verify_required: true,
    auto_upload_enabled: false,
    auto_upload_mode: 'local',
    auto_upload_library_id: '',
    auto_upload_target_path: '',
    match_duration_tolerance_seconds: 3.0,
    match_size_tolerance_ratio: 0.08,
    lrc_clean_enabled: true,
    lrc_clean_patterns: ['@[\\w]{3,}', 'Telegram', 'telegram', '电报', 'tg群', 'TG群', 'QQ群[：:]\\s*\\d+', '群号[：:]\\s*\\d+'],
    simplify_chinese_enabled: true
  },
  http_downloader: {
    enabled: true,
    engine: 'aria2',
    download_root: '',
    aria2_path: 'aria2c',
    proxy_url: '',
    max_concurrent_downloads: 3,
    split: 8,
    max_connection_per_server: 8,
    min_split_size: '1M',
    retry_count: 5,
    retry_wait_seconds: 5,
    connect_timeout_seconds: 15,
    timeout_seconds: 60,
    allow_private_network: false,
    conflict_policy: 'resume',
    gofile_token: '',
    pikpak_enabled: false,
    pikpak_default_enabled: true,
    pikpak_label: '',
    pikpak_username: '',
    pikpak_password: '',
    pikpak_encoded_token: '',
    pikpak_device_id: '',
    pikpak_transfer_dir: '/KikoeruManager',
    pikpak_auto_save_share: true,
    pikpak_accounts: []
  },
  auto_process: {
    check_duplicate: true,
    import_linked_translation_subtitles: true,
    extract: true,
    fetch_metadata: true,
    rename: true,
    filter: true,
    classify: true,
    archive: true
  },
  process_existing: {
    check_duplicate: true,
    fetch_metadata: true,
    rename: true,
    filter: true,
    import_lrc: true,
    classify: true
  },
  asmr_sync_step: {
    download: true,
    sync_subtitle: true,
    rename: true,
    classify: true,
    move_subtitle_folder: true
  },
  rj_subtitle: {
    overwrite_existing: false,
    scan_one_level_only: true,
    enable_metadata_match: true,
    naming_strategy: 'audio',
    use_filter_rules: false,
    show_source_search: true,
    show_written_files: true,
    show_download_progress: true,
    show_issues: true
  },
  email_watcher: {
    enabled: false,
    imap_host: 'imap.gmail.com',
    imap_port: 993,
    imap_ssl: true,
    username: '',
    password: '',
    mailbox: 'INBOX',
    sender_filter: 'dlsite.com',
    subject_filter: '',
    mark_as_read: true,
    move_to_folder: '',
    auto_index_new_circles: true,
    idle_timeout_minutes: 25,
    fallback_poll_interval_seconds: 300
  },
  notification_email: {
    enabled: false,
    smtp_host: '',
    smtp_port: 465,
    smtp_ssl: true,
    smtp_starttls: false,
    username: '',
    password: '',
    from_email: '',
    from_name: 'KikoeruManager',
    to_email: '',
    connect_timeout_seconds: 10,
    send_timeout_seconds: 30,
    max_retry_count: 3,
    retry_interval_seconds: 60,
    send_on_completed: true,
    send_on_failed: true,
    send_on_waiting_manual: true,
    send_on_cancelled: false
  },
  notification_center: {
    enabled: true,
    retain_days: 30,
    max_items: 200,
    poll_interval_seconds: 20,
    unread_highlight_enabled: true
  },
  security_gate: {
    enabled: false,
    secret: '',
    pending_secret: '',
    bound: false,
    has_pending_setup: false,
    allow_remember_device: true,
    session_hours: 8,
    remember_days: 30,
    blacklist_enabled: true,
    failure_window_minutes: 10,
    max_failures: 5,
    trust_proxy_headers: false,
    email_alert_enabled: true,
    email_alert_on_failure: false,
    email_alert_on_blacklist: true,
    email_alert_on_blocked_visit: false,
    email_alert_on_reset: true,
    email_alert_min_interval_seconds: 300
  },
  classification: [
    {
      id: Date.now(),
      type: 'none',
      path_template: '',
      custom_name: '',
      rjcode_range: '',
      enabled: true
    }
  ]
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value))
}

const MASKED_PASSWORD = '********'

function sanitizeSynologyProfileForSave(profile = {}, index = 1) {
  const normalized = normalizeSynologyProfile(profile, index)
  return {
    id: normalized.id,
    name: normalized.name,
    ...pickFields(normalized, SYNOLOGY_PROFILE_FIELDS)
  }
}

function sanitizeLibraryForSave(library = {}, index = 1) {
  const normalized = normalizeLibraryConfig(library, index)
  return {
    id: normalized.id,
    name: normalized.name,
    type: normalized.type,
    path: normalized.path,
    browse_path: normalized.browse_path,
    enabled: normalized.enabled,
    writable: normalized.writable,
    description: normalized.description,
    tags: Array.isArray(normalized.tags) ? [...normalized.tags] : [],
    synology_profile_id: normalized.synology_profile_id || '',
    synology: normalized.type === 'synology_filestation'
      ? sanitizeSynologyLibraryConfig(normalized.synology)
      : null
  }
}

function sanitizeSynologyLibraryConfig(synology = {}) {
  const base = createDefaultLibrary('synology_filestation', 1).synology
  return {
    root_path: synology?.root_path || base.root_path,
    base_url: synology?.base_url || base.base_url,
    username: synology?.username || base.username,
    password: synology?.password || base.password,
    otp_code: synology?.otp_code || base.otp_code,
    device_name: synology?.device_name || base.device_name,
    device_id: synology?.device_id || base.device_id,
    enable_device_token: synology?.enable_device_token ?? base.enable_device_token,
    session_name: synology?.session_name || base.session_name,
    timeout: synology?.timeout ?? base.timeout,
    verify_ssl: synology?.verify_ssl ?? base.verify_ssl
  }
}

function pickFields(source = {}, keys = []) {
  return keys.reduce((result, key) => {
    result[key] = source?.[key]
    return result
  }, {})
}

function hydrateConfig(data = {}) {
  const next = {
    storage: {
      ...defaultConfig.storage,
      ...(data?.storage || {}),
      synology_profiles: (data?.storage?.synology_profiles || defaultConfig.storage.synology_profiles).map((profile, index) => normalizeSynologyProfile(profile, index + 1)),
      libraries: (data?.storage?.libraries || defaultConfig.storage.libraries).map((library, index) => normalizeLibraryConfig(library, index + 1)),
      default_library_id: data?.storage?.default_library_id || '',
      default_extract_library_id: data?.storage?.default_extract_library_id || '',
      health_warning_free_gb: data?.storage?.health_warning_free_gb ?? defaultConfig.storage.health_warning_free_gb,
      stats_cache_ttl_seconds: data?.storage?.stats_cache_ttl_seconds ?? defaultConfig.storage.stats_cache_ttl_seconds
    },
    processing: { ...defaultConfig.processing, ...(data?.processing || {}) },
    watcher: { ...defaultConfig.watcher, ...(data?.watcher || {}) },
    extract: { ...defaultConfig.extract, ...(data?.extract || {}) },
    filter: { ...defaultConfig.filter, ...(data?.filter || {}), rules: data?.filter?.rules || defaultConfig.filter.rules },
    metadata: { ...defaultConfig.metadata, ...(data?.metadata || {}) },
    rename: { ...defaultConfig.rename, ...(data?.rename || {}) },
    password_cleanup: { ...defaultConfig.password_cleanup, ...(data?.password_cleanup || {}) },
    archive_cleanup: { ...defaultConfig.archive_cleanup, ...(data?.processed_archive_cleanup || {}), min_keep_count: data?.processed_archive_cleanup?.min_keep_count ?? defaultConfig.archive_cleanup.min_keep_count },
    backup_zip: { ...defaultConfig.backup_zip, ...(data?.backup_zip || {}) },
    path_mappings: data?.path_mapping?.rules || defaultConfig.path_mappings,
    path_mapping_enabled: data?.path_mapping?.enabled ?? defaultConfig.path_mapping_enabled,
    kikoeru_server: { ...defaultConfig.kikoeru_server, ...(data?.kikoeru_server || {}) },
    asmr_sync: { ...defaultConfig.asmr_sync, ...(data?.asmr_sync || {}), lrc_clean_patterns: data?.asmr_sync?.lrc_clean_patterns || defaultConfig.asmr_sync.lrc_clean_patterns },
    http_downloader: { ...defaultConfig.http_downloader, ...(data?.http_downloader || {}) },
    auto_process: { ...defaultConfig.auto_process, ...(data?.auto_process || {}) },
    process_existing: { ...defaultConfig.process_existing, ...(data?.process_existing || {}) },
    asmr_sync_step: { ...defaultConfig.asmr_sync_step, ...(data?.asmr_sync_step || {}) },
    rj_subtitle: { ...defaultConfig.rj_subtitle, ...(data?.rj_subtitle || {}) },
    email_watcher: { ...defaultConfig.email_watcher, ...(data?.email_watcher || {}) },
    notification_email: { ...defaultConfig.notification_email, ...(data?.notification_email || {}) },
    notification_center: { ...defaultConfig.notification_center, ...(data?.notification_center || {}) },
    security_gate: { ...defaultConfig.security_gate, ...(data?.security_gate || {}) },
    classification: data?.classification || defaultConfig.classification
  }

  if (!next.storage.libraries.length) {
    next.storage.libraries = [normalizeLibraryConfig({ id: 'default-local', name: '默认库存', type: 'local', path: next.storage.library_path || '' }, 1)]
  }
  if (!next.storage.default_library_id) next.storage.default_library_id = next.storage.libraries[0]?.id || ''
  if (!next.storage.default_extract_library_id) next.storage.default_extract_library_id = next.storage.default_library_id
  return next
}

function serializeConfig(config) {
  const payload = deepClone(config)
  payload.storage.synology_profiles = (payload.storage.synology_profiles || [])
    .map((profile, index) => sanitizeSynologyProfileForSave(profile, index + 1))
  payload.storage.libraries = (payload.storage.libraries || [])
    .map((library, index) => sanitizeLibraryForSave(library, index + 1))
  return {
    storage: payload.storage,
    processing: payload.processing,
    watcher: payload.watcher,
    extract: payload.extract,
    filter: payload.filter,
    metadata: payload.metadata,
    rename: payload.rename,
    classification: payload.classification,
    password_cleanup: payload.password_cleanup,
    processed_archive_cleanup: payload.archive_cleanup,
    backup_zip: payload.backup_zip,
    path_mapping: {
      enabled: payload.path_mapping_enabled,
      rules: (payload.path_mappings || []).map(rule => ({
        remote_path: rule.original || rule.remote_path,
        local_path: rule.mapped || rule.local_path,
        enabled: rule.enabled ?? true
      }))
    },
    kikoeru_server: payload.kikoeru_server,
    asmr_sync: payload.asmr_sync,
    http_downloader: payload.http_downloader,
    auto_process: payload.auto_process,
    process_existing: payload.process_existing,
    asmr_sync_step: payload.asmr_sync_step,
    rj_subtitle: payload.rj_subtitle,
    email_watcher: payload.email_watcher,
    notification_email: payload.notification_email,
    notification_center: payload.notification_center,
    security_gate: payload.security_gate
  }
}

function stripMaskedPikPakAccountSecrets(payload, snapshotConfig) {
  const accounts = payload.http_downloader?.pikpak_accounts
  if (!Array.isArray(accounts)) return
  const snapshotAccounts = Array.isArray(snapshotConfig?.http_downloader?.pikpak_accounts)
    ? snapshotConfig.http_downloader.pikpak_accounts
    : []
  const snapshotById = new Map(
    snapshotAccounts
      .filter(account => account && account.id)
      .map(account => [String(account.id), account])
  )
  accounts.forEach((account, index) => {
    const snapshotAccount = snapshotById.get(String(account?.id || '')) || snapshotAccounts[index] || {}
    if (account?.password === MASKED_PASSWORD && snapshotAccount?.password === MASKED_PASSWORD) {
      delete account.password
    }
    if (account?.encoded_token === MASKED_PASSWORD && snapshotAccount?.encoded_token === MASKED_PASSWORD) {
      delete account.encoded_token
    }
  })
}

function pickSectionState(source = {}, keys = []) {
  const result = {}
  for (const key of keys) {
    result[key] = source?.[key]
  }
  return result
}

export function useSettingsDraft(options = {}) {
  const configStore = useConfigStore()
  const config = ref(deepClone(defaultConfig))
  const snapshot = ref(deepClone(defaultConfig))
  const loading = ref(false)
  const saving = ref(false)
  const reloading = ref(false)
  const lastSavedAt = ref(null)

  // 为避免每次按键都跑一次全量 JSON.stringify(serializeConfig(...)) 导致输入卡顿，
  // 这里把 digest 节流到 120ms：按键期间不算，停手后再算。
  // snapshot 只在 load/save/reset 时整体替换，digest 立即同步（不需要节流）。
  const sectionKeyMap = options.sectionKeyMap || {}
  const debounceMs = Number.isFinite(options.debounceMs) ? options.debounceMs : 120

  const draftDigest = ref('')
  const snapshotDigest = ref('')
  const sectionDraftDigests = shallowRef({})
  const sectionSnapshotDigests = shallowRef({})

  function computeDraftDigest() {
    draftDigest.value = JSON.stringify(serializeConfig(config.value))
    const nextSection = {}
    for (const [sectionId, keys] of Object.entries(sectionKeyMap)) {
      nextSection[sectionId] = JSON.stringify(pickSectionState(config.value, keys))
    }
    sectionDraftDigests.value = nextSection
  }

  function computeSnapshotDigest() {
    snapshotDigest.value = JSON.stringify(serializeConfig(snapshot.value))
    const nextSection = {}
    for (const [sectionId, keys] of Object.entries(sectionKeyMap)) {
      nextSection[sectionId] = JSON.stringify(pickSectionState(snapshot.value, keys))
    }
    sectionSnapshotDigests.value = nextSection
  }

  // 初始化基线（config === snapshot 都是 defaultConfig），此刻 hasChanges = false。
  computeDraftDigest()
  computeSnapshotDigest()

  let draftDigestTimer = null
  const draftWatchStop = watch(
    config,
    () => {
      if (draftDigestTimer) clearTimeout(draftDigestTimer)
      draftDigestTimer = setTimeout(() => {
        draftDigestTimer = null
        computeDraftDigest()
      }, debounceMs)
    },
    { deep: true }
  )

  const snapshotWatchStop = watch(
    snapshot,
    () => {
      computeSnapshotDigest()
    },
    { deep: true }
  )

  onBeforeUnmount(() => {
    if (draftDigestTimer) {
      clearTimeout(draftDigestTimer)
      draftDigestTimer = null
    }
    draftWatchStop()
    snapshotWatchStop()
  })

  const hasChanges = computed(() => draftDigest.value !== snapshotDigest.value)

  const dirtyMap = computed(() => {
    const result = {}
    for (const sectionId of Object.keys(sectionKeyMap)) {
      result[sectionId] = sectionDraftDigests.value[sectionId] !== sectionSnapshotDigests.value[sectionId]
    }
    return result
  })

  function syncDigestsNow() {
    if (draftDigestTimer) {
      clearTimeout(draftDigestTimer)
      draftDigestTimer = null
    }
    computeDraftDigest()
    computeSnapshotDigest()
  }

  async function loadConfig() {
    const hadLoadedConfig = !!(snapshot.value && Object.keys(snapshot.value || {}).length)
    try {
      loading.value = true
      const data = await configStore.fetchConfig()
      const hydrated = hydrateConfig(data)
      config.value = hydrated
      snapshot.value = deepClone(hydrated)
    } catch (error) {
      console.error('加载配置失败:', error)
      ElMessage.error('加载配置失败：' + (error.response?.data?.detail || error.message))
      if (!hadLoadedConfig) {
        config.value = deepClone(defaultConfig)
        snapshot.value = deepClone(defaultConfig)
      }
    } finally {
      loading.value = false
      syncDigestsNow()
    }
  }

  async function reloadConfigFromServer() {
    try {
      reloading.value = true
      if (hasChanges.value) {
        await showSystemConfirm({
          title: '不保存此次变更',
          message: '从文件刷新会丢失当前未保存的改动，是否继续？',
          confirmText: '不保存并刷新',
          cancelText: '取消',
          tone: 'warning'
        })
      }
      await configApi.reload()
      await loadConfig()
      ElMessage.success('配置已从配置文件重新加载')
    } catch (error) {
      console.error('重新加载配置失败:', error)
      ElMessage.error('重新加载配置失败：' + (error.response?.data?.detail || error.message))
    } finally {
      reloading.value = false
    }
  }

  async function saveConfig() {
    try {
      saving.value = true
      const payload = serializeConfig(config.value)
      if (
        payload.notification_email?.password === MASKED_PASSWORD &&
        snapshot.value?.notification_email?.password === MASKED_PASSWORD
      ) {
        delete payload.notification_email.password
      }
      if (
        payload.http_downloader?.pikpak_password === MASKED_PASSWORD &&
        snapshot.value?.http_downloader?.pikpak_password === MASKED_PASSWORD
      ) {
        delete payload.http_downloader.pikpak_password
      }
      if (
        payload.http_downloader?.pikpak_encoded_token === MASKED_PASSWORD &&
        snapshot.value?.http_downloader?.pikpak_encoded_token === MASKED_PASSWORD
      ) {
        delete payload.http_downloader.pikpak_encoded_token
      }
      if (
        payload.http_downloader?.gofile_token === MASKED_PASSWORD &&
        snapshot.value?.http_downloader?.gofile_token === MASKED_PASSWORD
      ) {
        delete payload.http_downloader.gofile_token
      }
      stripMaskedPikPakAccountSecrets(payload, snapshot.value)
      await configStore.saveConfig(payload)
      snapshot.value = deepClone(config.value)
      lastSavedAt.value = Date.now()
      ElMessage.success('配置保存成功')
    } catch (error) {
      console.error('保存配置失败:', error)
      ElMessage.error('保存配置失败：' + (error.response?.data?.detail || error.message))
      throw error
    } finally {
      saving.value = false
      syncDigestsNow()
    }
  }

  async function resetAllConfig() {
    await showSystemConfirm({
      title: '不保存此次变更',
      message: '确定要放弃当前未保存的改动吗？',
      confirmText: '放弃变更',
      cancelText: '取消',
      tone: 'warning'
    })
    config.value = deepClone(snapshot.value)
    syncDigestsNow()
  }

  function resetSection(sectionKeys = []) {
    const keys = Array.isArray(sectionKeys) ? sectionKeys : [sectionKeys]
    for (const key of keys) {
      if (!(key in defaultConfig)) continue
      config.value[key] = deepClone(defaultConfig[key])
    }
  }

  return {
    config,
    defaultConfig,
    snapshot,
    loading,
    saving,
    reloading,
    lastSavedAt,
    hasChanges,
    dirtyMap,
    loadConfig,
    saveConfig,
    reloadConfigFromServer,
    resetAllConfig,
    resetSection,
    serializeConfig
  }
}
