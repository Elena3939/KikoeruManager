import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { libraryApi } from '../api'
import {
  SYNOLOGY_PROFILE_FIELDS,
  createDefaultLibrary,
  createDefaultSynologyProfile,
  normalizeLibraryConfig,
  normalizeSynologyProfile
} from './useSettingsDraft'

function pickProfileFields(source = {}) {
  return SYNOLOGY_PROFILE_FIELDS.reduce((result, key) => {
    result[key] = source?.[key]
    return result
  }, {})
}

function mergeSynologyFields(profile = {}, local = {}) {
  const merged = {}
  for (const key of SYNOLOGY_PROFILE_FIELDS) {
    const profileValue = profile?.[key]
    const localValue = local?.[key]
    if (typeof profileValue === 'boolean' || typeof localValue === 'boolean') {
      merged[key] = profileValue ?? localValue
      continue
    }
    const normalizedProfile = String(profileValue ?? '').trim()
    if (normalizedProfile) {
      merged[key] = profileValue
      continue
    }
    merged[key] = localValue
  }
  return merged
}

export function useSynologyProfiles(config) {
  const testingProfileId = ref('')
  const testingLibraryId = ref('')

  const profiles = computed(() => config.value.storage?.synology_profiles || [])
  const libraries = computed(() => config.value.storage?.libraries || [])

  function ensurePrimaryProfile() {
    const current = [...profiles.value]
    if (!current.length) {
      const primary = normalizeSynologyProfile({
        ...createDefaultSynologyProfile(1),
        id: 'synology-main',
        name: '主群晖连接'
      }, 1)
      config.value.storage.synology_profiles = [primary]
      for (const library of libraries.value) {
        if (library?.type === 'synology_filestation') {
          library.synology_profile_id = primary.id
        }
      }
      return profiles.value[0] || primary
    }

    const mergedSeed = current.reduce((acc, item, index) => {
      const normalized = normalizeSynologyProfile(item, index + 1)
      for (const key of SYNOLOGY_PROFILE_FIELDS) {
        const value = normalized[key]
        if (acc[key] === undefined || acc[key] === '' || acc[key] === false) {
          if (value !== undefined && value !== '') acc[key] = value
        }
      }
      return acc
    }, {})

    const primary = normalizeSynologyProfile({
      ...current[0],
      ...mergedSeed,
      id: String(current[0]?.id || 'synology-main').trim() || 'synology-main',
      name: String(current[0]?.name || '主群晖连接').trim() || '主群晖连接'
    }, 1)

    config.value.storage.synology_profiles = [primary]
    for (const library of libraries.value) {
      if (library?.type === 'synology_filestation') {
        library.synology_profile_id = primary.id
      }
    }
    return profiles.value[0] || primary
  }

  function getSynologyProfileById(profileId) {
    const normalizedId = String(profileId || '').trim()
    if (!normalizedId) return null
    const index = profiles.value.findIndex(item => item.id === normalizedId)
    if (index === -1) return null
    return normalizeSynologyProfile(profiles.value[index], index + 1)
  }

  function getSynologyProfileName(profileId) {
    return getSynologyProfileById(profileId)?.name || ''
  }

  function getEffectiveSynologyConfig(library) {
    const normalized = normalizeLibraryConfig(library)
    const profile = normalized.synology_profile_id ? getSynologyProfileById(normalized.synology_profile_id) : null
    const localSynology = normalized.synology || {}
    const merged = {
      ...createDefaultLibrary('synology_filestation', 1).synology,
      ...mergeSynologyFields(profile ? pickProfileFields(profile) : {}, localSynology)
    }
    merged.root_path = localSynology.root_path || normalized.path || '/'
    if (!merged.device_name) merged.device_name = localSynology.device_name || normalized.name || normalized.id || 'KikoeruManager'
    return merged
  }

  function buildEffectiveLibraryConfig(library) {
    const normalized = normalizeLibraryConfig(library)
    if (normalized.type !== 'synology_filestation') return normalized
    return {
      ...normalized,
      path: getEffectiveSynologyConfig(normalized).root_path,
      synology: getEffectiveSynologyConfig(normalized)
    }
  }

  function syncRemoteLibraryPath(library) {
    if (library?.type !== 'synology_filestation') return
    library.synology = {
      root_path: library?.synology?.root_path || library.path || '/'
    }
    library.path = library.synology.root_path
  }

  function getPrimaryProfile() {
    return ensurePrimaryProfile()
  }

  function sameSynologyProfileFields(left = {}, right = {}) {
    return SYNOLOGY_PROFILE_FIELDS.every(key => {
      const leftValue = left?.[key]
      const rightValue = right?.[key]
      if (typeof leftValue === 'boolean' || typeof rightValue === 'boolean') {
        return Boolean(leftValue) === Boolean(rightValue)
      }
      return String(leftValue ?? '') === String(rightValue ?? '')
    })
  }

  function assignSynologyProfileToMatchingLibraries(profileId, effectiveSynology) {
    let affected = 0
    for (const library of libraries.value) {
      if (library?.type !== 'synology_filestation') continue
      const currentEffective = getEffectiveSynologyConfig(library)
      if (!sameSynologyProfileFields(currentEffective, effectiveSynology)) continue
      library.synology_profile_id = profileId
      library.synology = {
        root_path: currentEffective.root_path || library.synology?.root_path || library.path || '/'
      }
      library.path = library.synology.root_path
      affected += 1
    }
    return affected
  }

  function extractSynologyProfileFromLibrary(library) {
    if (library?.type !== 'synology_filestation') return null
    syncRemoteLibraryPath(library)
    const effective = getEffectiveSynologyConfig(library)
    const primary = ensurePrimaryProfile()
    Object.assign(primary, {
      ...primary,
      ...pickProfileFields(effective),
      name: primary.name || '主群晖连接'
    })
    config.value.storage.synology_profiles = [normalizeSynologyProfile(primary, 1)]
    const affected = assignSynologyProfileToMatchingLibraries(primary.id, effective)
    ElMessage.success(`已收敛到主群晖连接，并同步到 ${affected} 个远程库存`)
    return primary
  }

  function handleLibraryProfileChange(library) {
    syncRemoteLibraryPath(library)
    if (!library?.synology_profile_id) return
    const effective = getEffectiveSynologyConfig(library)
    library.synology = {
      root_path: effective.root_path || library.synology?.root_path || library.path || '/'
    }
    library.path = library.synology.root_path
  }

  function addStorageLibrary(type = 'local') {
    const nextIndex = libraries.value.length + 1
    const nextLibrary = createDefaultLibrary(type, nextIndex)
    if (type === 'local' && !nextLibrary.path) {
      nextLibrary.path = config.value.storage.library_path || ''
    }
    if (type === 'synology_filestation') {
      const firstProfile = ensurePrimaryProfile()
      if (firstProfile?.id) nextLibrary.synology_profile_id = firstProfile.id
      nextLibrary.path = nextLibrary.synology.root_path
    }
    config.value.storage.libraries = [...libraries.value, nextLibrary]
    if (!config.value.storage.default_library_id) config.value.storage.default_library_id = nextLibrary.id
    if (!config.value.storage.default_extract_library_id) config.value.storage.default_extract_library_id = nextLibrary.id
    return nextLibrary
  }

  function removeStorageLibrary(index) {
    const next = [...libraries.value]
    const removed = next[index]
    next.splice(index, 1)
    config.value.storage.libraries = next
    if (removed?.id && config.value.storage.default_library_id === removed.id) {
      config.value.storage.default_library_id = next[0]?.id || ''
    }
    if (removed?.id && config.value.storage.default_extract_library_id === removed.id) {
      config.value.storage.default_extract_library_id = config.value.storage.default_library_id || next[0]?.id || ''
    }
  }

  function buildSynologyWebUrl(library) {
    const effective = buildEffectiveLibraryConfig(library)
    const baseUrl = effective?.synology?.base_url?.replace(/\/+$/, '') || ''
    const rootPath = effective?.synology?.root_path || effective?.path || '/'
    if (!baseUrl || !rootPath) return ''
    const normalizedPath = rootPath.startsWith('/') ? rootPath : `/${rootPath}`
    return `${baseUrl}//file/?launchApp=SYNO.SDS.App.FileStation3.Instance&launchParam=${encodeURIComponent(`path=${normalizedPath}`)}`
  }

  async function testProfileConnection(profile) {
    try {
      testingProfileId.value = profile.id || `profile-${Date.now()}`
      const probeLibrary = buildEffectiveLibraryConfig({
        id: `profile-probe-${profile.id || Date.now()}`,
        name: profile.name || '群晖模板探测',
        type: 'synology_filestation',
        synology_profile_id: '',
        synology: {
          ...createDefaultLibrary('synology_filestation', 1).synology,
          ...pickProfileFields(profile),
          root_path: '/'
        }
      })
      const response = await libraryApi.testConnection(probeLibrary)
      if (response.device_id) {
        profile.device_id = response.device_id
      }
      ElMessage.success(response.message || '模板连接成功')
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || error.message || '模板连接失败')
    } finally {
      testingProfileId.value = ''
    }
  }

  async function testStorageLibrary(library) {
    try {
      syncRemoteLibraryPath(library)
      testingLibraryId.value = library.id || `library-${Date.now()}`
      const response = await libraryApi.testConnection(buildEffectiveLibraryConfig(library))
      if (response.device_id) {
        if (library.synology_profile_id) {
          const profile = getSynologyProfileById(library.synology_profile_id)
          const index = profiles.value.findIndex(item => item.id === library.synology_profile_id)
          if (profile && index !== -1) {
            profile.device_id = response.device_id
            config.value.storage.synology_profiles.splice(index, 1, profile)
          }
        } else {
          library.synology.device_id = response.device_id
        }
      }
      ElMessage.success(response.message || '目录访问成功')
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || error.message || '目录访问失败')
    } finally {
      testingLibraryId.value = ''
    }
  }

  function updateProfileFlag({ key, value }) {
    ensurePrimaryProfile()
    if (!key || !profiles.value.length) return
    const current = normalizeSynologyProfile(profiles.value[0], 1)
    config.value.storage.synology_profiles = [
      normalizeSynologyProfile({
        ...current,
        [key]: value
      }, 1)
    ]
  }

  function updateLibraryFlag({ libraryId, key, value }) {
    if (!libraryId || !key) return
    const index = libraries.value.findIndex(item => item.id === libraryId)
    if (index === -1) return
    const current = normalizeLibraryConfig(libraries.value[index], index + 1)
    const next = normalizeLibraryConfig({
      ...current,
      [key]: value
    }, index + 1)
    config.value.storage.libraries.splice(index, 1, next)
  }

  function getProfileSummary(profile, index = 1) {
    const normalized = normalizeSynologyProfile(profile, index)
    const linkedLibraries = libraries.value.filter(item => item.synology_profile_id === normalized.id)
    return {
      ...normalized,
      linkedCount: linkedLibraries.length,
      hasDeviceToken: Boolean(normalized.device_id),
      statusText: normalized.device_id ? '已记住设备' : (normalized.otp_code ? '等待首次验证' : '可能需要 OTP')
    }
  }

  function getLibraryViewModel(library, index = 1) {
    const normalized = normalizeLibraryConfig(library, index)
    return {
      ...normalized,
      effectiveSynology: normalized.type === 'synology_filestation' ? getEffectiveSynologyConfig(normalized) : null,
      isRemote: normalized.type === 'synology_filestation',
      profileName: normalized.synology_profile_id ? getSynologyProfileName(normalized.synology_profile_id) : '',
      statusText: normalized.enabled ? '启用中' : '已停用',
      missingProfile: normalized.type === 'synology_filestation' && !normalized.synology_profile_id
    }
  }

  const primaryProfile = computed(() => {
    ensurePrimaryProfile()
    return profiles.value[0] || null
  })

  const profileSummaries = computed(() => profiles.value.map((profile, index) => {
    return getProfileSummary(profile, index + 1)
  }))

  const libraryViewModels = computed(() => libraries.value.map((library, index) => {
    return getLibraryViewModel(library, index + 1)
  }))

  ensurePrimaryProfile()

  return {
    profiles,
    getPrimaryProfile,
    primaryProfile,
    libraries,
    profileSummaries,
    libraryViewModels,
    testingProfileId,
    testingLibraryId,
    getSynologyProfileById,
    getSynologyProfileName,
    getEffectiveSynologyConfig,
    buildEffectiveLibraryConfig,
    syncRemoteLibraryPath,
    extractSynologyProfileFromLibrary,
    handleLibraryProfileChange,
    addStorageLibrary,
    removeStorageLibrary,
    buildSynologyWebUrl,
    testProfileConnection,
    testStorageLibrary,
    getProfileSummary,
    getLibraryViewModel,
    updateProfileFlag,
    updateLibraryFlag
  }
}
