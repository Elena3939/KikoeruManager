<template>
  <div class="task-center-page">
    <section class="task-center-hero">
      <div>
        <span class="hero-eyebrow">Task Center</span>
        <h1 class="hero-title">任务中心</h1>
        <p class="hero-description">把导入处理、RJ 字幕、字幕补配、ASMR 同步和系统任务放到同一个视图里看。</p>
      </div>

      <el-button class="refresh-button" :loading="loading" @click="refreshTaskCenter">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </section>

    <section class="summary-strip">
      <div class="summary-tile">
        <span class="summary-label">处理中</span>
        <span class="summary-value">{{ summaryCounts.processing }}</span>
      </div>
      <div class="summary-tile">
        <span class="summary-label">等待人工</span>
        <span class="summary-value">{{ summaryCounts.waiting_manual }}</span>
      </div>
      <div class="summary-tile">
        <span class="summary-label">等待重试</span>
        <span class="summary-value">{{ summaryCounts.waiting_retry }}</span>
      </div>
      <div class="summary-tile">
        <span class="summary-label">失败</span>
        <span class="summary-value">{{ summaryCounts.failed }}</span>
      </div>
    </section>

    <el-card class="filters-card" shadow="never">
      <div class="filters-row">
        <div class="filter-group">
          <span class="filter-label">任务类型</span>
          <div class="filter-chips">
            <button
              v-for="option in domainOptions"
              :key="option.value"
              type="button"
              class="filter-chip"
              :class="{ active: currentDomain === option.value }"
              @click="currentDomain = option.value"
            >
              {{ option.label }}
            </button>
          </div>
        </div>

        <div class="filter-group">
          <span class="filter-label">任务状态</span>
          <div class="filter-chips">
            <button
              v-for="option in statusOptions"
              :key="option.value"
              type="button"
              class="filter-chip"
              :class="{ active: currentStatus === option.value }"
              @click="currentStatus = option.value"
            >
              {{ option.label }}
            </button>
          </div>
        </div>

        <el-input
          v-model="searchQuery"
          class="task-search"
          placeholder="搜索标题、RJ、路径、当前步骤"
          clearable
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>
    </el-card>

    <div class="task-center-layout">
      <el-card class="task-list-card" shadow="never">
        <template #header>
          <div class="list-header">
            <span>任务列表</span>
            <span class="list-count">{{ filteredItems.length }} 项</span>
          </div>
        </template>

        <div v-if="filteredItems.length" class="task-list">
          <button
            v-for="item in filteredItems"
            :key="item.id"
            type="button"
            class="task-list-item"
            :class="{ active: selectedItem?.id === item.id }"
            @click="selectedItemId = item.id"
          >
            <div class="task-list-item-head">
              <div class="task-list-main">
                <span class="task-title">{{ item.title }}</span>
                <span v-if="item.subtitle" class="task-subtitle">{{ item.subtitle }}</span>
              </div>
            <div class="task-list-badges">
              <el-tag size="small" effect="plain">{{ item.domain_label }}</el-tag>
              <el-tag size="small" :type="getStatusTagType(item.status)" class="task-status-tag" :class="getStatusTagClass(item.status)">{{ item.status_label }}</el-tag>
            </div>
            </div>

            <div class="task-list-meta">
              <span>{{ item.source_label }}</span>
              <span v-if="shouldShowTaskMetaStep(item)">{{ item.current_step }}</span>
            </div>

            <div v-if="getRecoveredNotice(item)" class="recovered-banner">
              <div class="recovered-banner-icon">
                <el-icon><CircleCheckFilled /></el-icon>
              </div>
              <div class="recovered-banner-content">
                <div class="recovered-banner-title">已恢复</div>
                <div class="recovered-banner-text">{{ getRecoveredNotice(item) }}</div>
              </div>
            </div>

            <div v-if="getOutputPath(item)" class="task-output-row">
              <span class="task-output-label">输出路径</span>
              <code class="task-output-value">{{ getOutputPath(item) }}</code>
            </div>

            <div v-if="showProgress(item)" class="task-progress-row">
              <el-progress :percentage="item.progress" :show-text="false" :stroke-width="8" />
              <span class="task-progress-value">{{ item.progress }}%</span>
            </div>

            <div v-if="getTaskSummary(item).length" class="task-metrics">
              <span v-for="(piece, index) in getTaskSummary(item)" :key="`${item.id}-summary-${index}`" class="metric-pill">
                {{ piece }}
              </span>
            </div>
          </button>
        </div>

        <AppEmptyState v-else description="当前筛选条件下没有任务" size="default" />
      </el-card>

      <el-card class="task-detail-card" shadow="never">
        <template #header>
          <div class="detail-header">
            <span>任务详情</span>
            <el-button v-if="selectedItem?.route_hint" link @click="openTaskRoute(selectedItem)">
              打开关联页面
            </el-button>
          </div>
        </template>

        <template v-if="selectedItem">
          <div class="detail-hero">
            <div class="detail-title-wrap">
              <h2 class="detail-title">{{ selectedItem.title }}</h2>
              <p v-if="selectedItem.subtitle" class="detail-subtitle">{{ selectedItem.subtitle }}</p>
            </div>
            <div class="detail-tags">
              <el-tag effect="plain">{{ selectedItem.domain_label }}</el-tag>
              <el-tag :type="getStatusTagType(selectedItem.status)" class="task-status-tag" :class="getStatusTagClass(selectedItem.status)">{{ selectedItem.status_label }}</el-tag>
            </div>
          </div>

          <div class="detail-grid">
            <div class="detail-block">
              <span class="detail-block-label">来源</span>
              <span class="detail-block-value">{{ selectedItem.source_label || '-' }}</span>
            </div>
            <div class="detail-block">
              <span class="detail-block-label">RJ</span>
              <span class="detail-block-value">{{ formatRJCode(selectedItem.rjcode) || '-' }}</span>
            </div>
            <div class="detail-block">
              <span class="detail-block-label">创建时间</span>
              <span class="detail-block-value">{{ formatDateTime(selectedItem.created_at) }}</span>
            </div>
            <div class="detail-block">
              <span class="detail-block-label">完成时间</span>
              <span class="detail-block-value">{{ formatDateTime(selectedItem.completed_at) }}</span>
            </div>
          </div>

          <div class="detail-section">
            <span class="detail-section-label">当前状态</span>
            <div v-if="getRecoveredNotice(selectedItem)" class="detail-recovered-banner">
              <div class="recovered-banner-icon">
                <el-icon><CircleCheckFilled /></el-icon>
              </div>
              <div class="recovered-banner-content">
                <div class="recovered-banner-title">已恢复</div>
                <div class="recovered-banner-text">{{ getRecoveredNotice(selectedItem) }}</div>
              </div>
            </div>
            <div class="detail-step">{{ selectedItem.current_step }}</div>
            <div v-if="showProgress(selectedItem)" class="detail-progress">
              <el-progress :percentage="selectedItem.progress" :show-text="false" :stroke-width="10" />
              <span class="detail-progress-text">{{ selectedItem.progress }}%</span>
            </div>
            <div v-if="selectedItem.error_message" class="detail-error">{{ selectedItem.error_message }}</div>
            <div v-if="getDLsiteFailureReason(selectedItem)" class="detail-error">
              DLsite 抓取失败原因：{{ getDLsiteFailureReason(selectedItem) }}
            </div>
          </div>

          <div v-if="selectedItem.metrics?.length" class="detail-section">
            <span class="detail-section-label">关键指标</span>
            <div class="detail-metrics-grid">
              <div v-for="metric in selectedItem.metrics" :key="`${selectedItem.id}-${metric.label}`" class="detail-metric-card">
                <span class="detail-metric-label">{{ metric.label }}</span>
                <span class="detail-metric-value">{{ metric.value }}</span>
              </div>
            </div>
          </div>

          <div v-if="getCircleIndexMetaEntries(selectedItem).length" class="detail-section">
            <span class="detail-section-label">进度元信息</span>
            <div class="detail-metrics-grid">
              <div v-for="entry in getCircleIndexMetaEntries(selectedItem)" :key="`${selectedItem.id}-${entry.label}`" class="detail-metric-card">
                <span class="detail-metric-label">{{ entry.label }}</span>
                <span class="detail-metric-value">{{ entry.value }}</span>
              </div>
            </div>
          </div>

          <div v-if="getCircleIndexProgressLog(selectedItem).length" class="detail-section">
            <span class="detail-section-label">进度日志</span>
            <div class="detail-progress-log">
              <div v-for="(entry, index) in getCircleIndexProgressLog(selectedItem)" :key="`${selectedItem.id}-progress-${index}`" class="detail-progress-log-row">
                <span class="detail-progress-log-time">{{ formatDateTime(entry.time) }}</span>
                <span class="detail-progress-log-progress">{{ entry.progress }}%</span>
                <span class="detail-progress-log-message">{{ entry.message }}</span>
              </div>
            </div>
          </div>

          <div v-if="filterRemovedTreeRows(selectedItem).length" class="detail-section">
            <span class="detail-section-label">过滤移除清单</span>
            <div class="detail-entry-tree-box">
              <div
                v-for="entry in filterRemovedTreeRows(selectedItem)"
                :key="`${selectedItem.id}-${entry.key}`"
                class="detail-tree-row"
                :style="{ paddingLeft: `${12 + entry.depth * 18}px` }"
              >
                <div class="detail-tree-main">
                  <span class="detail-tree-branch" aria-hidden="true">{{ entry.depth ? '└' : '•' }}</span>
                  <span class="detail-tree-icon" :class="`is-${entry.type || 'file'}`">
                    <el-icon><component :is="entry.type === 'dir' ? Folder : Document" /></el-icon>
                  </span>
                  <span class="detail-tree-name">{{ entry.label }}</span>
                </div>
                <span v-if="entry.sizeText" class="detail-tree-size">{{ entry.sizeText }}</span>
              </div>
            </div>
          </div>

          <div v-if="uploadedFileTreeRows(selectedItem).length" class="detail-section">
            <span class="detail-section-label">上传文件树</span>
            <div class="detail-entry-tree-box">
              <div
                v-for="entry in uploadedFileTreeRows(selectedItem)"
                :key="`${selectedItem.id}-${entry.key}`"
                class="detail-tree-row"
                :style="{ paddingLeft: `${12 + entry.depth * 18}px` }"
              >
                <div class="detail-tree-main">
                  <span class="detail-tree-branch" aria-hidden="true">{{ entry.depth ? '└' : '•' }}</span>
                  <span class="detail-tree-icon" :class="`is-${entry.type || 'file'}`">
                    <el-icon><component :is="entry.type === 'dir' ? Folder : Document" /></el-icon>
                  </span>
                  <span class="detail-tree-name">{{ entry.label }}</span>
                </div>
                <span v-if="entry.sizeText" class="detail-tree-size">{{ entry.sizeText }}</span>
              </div>
            </div>
          </div>

          <div class="detail-section">
            <span class="detail-section-label">路径信息</span>
            <div class="detail-path-row">
              <span class="detail-path-label">源路径</span>
              <code class="detail-path-value">{{ selectedItem.source_path || '-' }}</code>
            </div>
            <div class="detail-path-row">
              <span class="detail-path-label">输出路径</span>
              <code class="detail-path-value">{{ getOutputPath(selectedItem) || '-' }}</code>
            </div>
          </div>

          <div class="detail-actions">
            <el-button
              v-for="action in selectedItem.actions"
              :key="`${selectedItem.id}-${action}`"
              :type="getActionButtonType(action)"
              :plain="action !== 'cancel'"
              @click="handleTaskAction(selectedItem, action)"
            >
              {{ getActionLabel(action) }}
            </el-button>
          </div>
        </template>

        <AppEmptyState v-else description="选择左侧任务查看详情" size="sm" />
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CircleCheckFilled, Refresh, Search, Folder, Document } from '@element-plus/icons-vue'
import { taskCenterApi } from '../api'
import AppEmptyState from '../components/common/AppEmptyState.vue'

const router = useRouter()

const loading = ref(false)
const refreshing = ref(false)
const items = ref([])
const selectedItemId = ref('')
const currentDomain = ref('all')
const currentStatus = ref('all')
const searchQuery = ref('')

let intervalId = null
let queuedRefresh = false

const domainOptions = [
  { value: 'all', label: '全部' },
  { value: 'import', label: '导入处理' },
  { value: 'rj_subtitle', label: 'RJ 字幕' },
  { value: 'subtitle_import', label: '字幕补配' },
  { value: 'asmr_sync', label: 'ASMR 同步' },
  { value: 'system', label: '系统任务' }
]

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'processing', label: '处理中' },
  { value: 'waiting_manual', label: '等待人工' },
  { value: 'waiting_retry', label: '等待重试' },
  { value: 'pending', label: '待处理' },
  { value: 'paused', label: '已暂停' },
  { value: 'failed', label: '失败' },
  { value: 'completed', label: '已完成' }
]

const filteredItems = computed(() => {
  const query = String(searchQuery.value || '').trim().toLowerCase()
  return items.value.filter((item) => {
    if (currentDomain.value !== 'all' && item.domain !== currentDomain.value) {
      return false
    }
    if (currentStatus.value !== 'all' && item.status !== currentStatus.value) {
      return false
    }
    if (!query) {
      return true
    }
    const haystack = [
      item.title,
      item.subtitle,
      item.source_path,
      item.target_path,
      item.rjcode,
      item.current_step,
      item.source_label
    ].join(' ').toLowerCase()
    return haystack.includes(query)
  })
})

const summaryCounts = computed(() => {
  const counts = {
    processing: 0,
    waiting_manual: 0,
    waiting_retry: 0,
    failed: 0
  }

  for (const item of items.value) {
    const status = String(item?.status || '').trim()
    if (status in counts) {
      counts[status] += 1
    }
  }

  return counts
})

const selectedItem = computed(() => {
  if (!filteredItems.value.length) {
    return null
  }
  return filteredItems.value.find((item) => item.id === selectedItemId.value) || filteredItems.value[0]
})

watch(filteredItems, (nextItems) => {
  if (!nextItems.length) {
    selectedItemId.value = ''
    return
  }
  if (!nextItems.some((item) => item.id === selectedItemId.value)) {
    selectedItemId.value = nextItems[0].id
  }
}, { immediate: true })

onMounted(async () => {
  await refreshTaskCenter(false, { silent: false })
  intervalId = setInterval(() => {
    refreshTaskCenter(false, { silent: true }).catch((error) => {
      console.error('任务中心轮询失败:', error)
    })
  }, 5000)
})

onUnmounted(() => {
  if (intervalId) {
    clearInterval(intervalId)
    intervalId = null
  }
})

async function refreshTaskCenter(showMessage = false, options = {}) {
  const { silent = false } = options
  if (refreshing.value) {
    queuedRefresh = true
    return
  }
  try {
    refreshing.value = true
    if (!silent) {
      loading.value = true
    }
    const cacheBust = Date.now()
    const listData = await taskCenterApi.list({ limit: 300, _t: cacheBust })
    items.value = Array.isArray(listData) ? listData : []
    if (showMessage) {
      ElMessage.success('任务中心已刷新')
    }
  } catch (error) {
    console.error('获取任务中心失败:', error)
    if (!silent) {
      ElMessage.error('获取任务中心失败: ' + (error.response?.data?.detail || error.message))
    }
  } finally {
    refreshing.value = false
    if (!silent) {
      loading.value = false
    }
    if (queuedRefresh) {
      queuedRefresh = false
      refreshTaskCenter(false, { silent: true }).catch((error) => {
        console.error('任务中心补偿刷新失败:', error)
      })
    }
  }
}

function showProgress(item) {
  return ['processing', 'pending', 'paused', 'waiting_retry'].includes(item?.status)
}

function getFileName(path) {
  if (!path) {
    return ''
  }
  return String(path).split(/[\\/]/).pop()
}

function pickMetricValue(item, label) {
  const metrics = Array.isArray(item?.metrics) ? item.metrics : []
  return metrics.find(metric => metric?.label === label)?.value || ''
}

function containsRJ(value) {
  return /[RVB]J(?:\d{8}|\d{6})(?!\d)/i.test(String(value || ''))
}

function formatRJCode(value) {
  const raw = String(value || '').trim().toUpperCase()
  if (!raw) return ''
  const match = raw.match(/(?:RJ)+\s*(\d{6,8})/i)
  if (match) {
    return `RJ${match[1]}`
  }
  const fallback = raw.match(/[RVB]J\s*(\d{6,8})/i)
  if (fallback) {
    return `RJ${fallback[1]}`
  }
  return raw
}

function formatBytes(value) {
  const size = Number(value || 0)
  if (!size || Number.isNaN(size)) return ''
  if (size < 1024) return `${Math.round(size)} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let current = size / 1024
  let unitIndex = 0
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024
    unitIndex += 1
  }
  return `${current.toFixed(2)} ${units[unitIndex]}`
}

function buildTreeRows(items = []) {
  const roots = []
  const nodeMap = new Map()

  const ensureNode = (key, label, type, parentKey = '') => {
    if (nodeMap.has(key)) return nodeMap.get(key)
    const node = { key, label, type, sizeText: '', children: [] }
    nodeMap.set(key, node)
    if (parentKey && nodeMap.has(parentKey)) nodeMap.get(parentKey).children.push(node)
    else roots.push(node)
    return node
  }

  for (const item of items) {
    const rawPath = String(item?.relative_path || item?.name || item?.path || '').replace(/^\/+|\/+$/g, '')
    if (!rawPath) continue
    const parts = rawPath.split('/').filter(Boolean)
    let parentKey = ''
    let joined = ''
    parts.forEach((part, index) => {
      joined = joined ? `${joined}/${part}` : part
      const isLeaf = index === parts.length - 1
      const node = ensureNode(joined, part, isLeaf ? (item?.type || 'file') : 'dir', parentKey)
      if (isLeaf) {
        node.type = item?.type || 'file'
        node.sizeText = formatBytes(item?.size)
      }
      parentKey = joined
    })
  }

  const rows = []
  const walk = (nodes, depth = 0) => {
    const sorted = [...nodes].sort((a, b) => {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
      return a.label.localeCompare(b.label, 'zh-Hans-CN-u-kn-true')
    })
    for (const node of sorted) {
      rows.push({ key: node.key, label: node.label, type: node.type, sizeText: node.sizeText, depth })
      if (node.children.length) walk(node.children, depth + 1)
    }
  }

  walk(roots)
  return rows
}

function getImportFailureStageLabel(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const stage = String(metadata.failure_stage || '').trim().toLowerCase()
  const stageMap = {
    extract: '解压失败',
    metadata: '元数据失败',
    rename: '重命名失败',
    filter: '过滤失败',
    classify: '分类失败',
    archive: '归档失败',
    process: '处理失败'
  }
  if (stageMap[stage]) {
    return stageMap[stage]
  }
  if (String(item?.status || '') === 'failed') {
    return '处理失败'
  }
  return ''
}

function getOutputPath(item) {
  if (!item) {
    return ''
  }
  const details = item.details || {}
  const metadata = details.metadata || {}
  const preview = details.preview || {}
  return item.target_path ||
    metadata.subtitle_dir ||
    metadata.target_folder_path ||
    metadata.folder_path ||
    preview.selected_candidate?.folder_path ||
    ''
}

function normalizeRJ(value) {
  const text = String(value || '').trim().toUpperCase()
  const repeated = text.match(/(?:RJ)+(\d{4,})/i)
  if (repeated) return `RJ${repeated[1]}`
  const standard = text.match(/RJ\d{4,}/i)
  return standard ? standard[0].toUpperCase() : ''
}

function dedupeSummaryPieces(pieces) {
  const out = []
  const seen = new Set()
  for (const piece of pieces) {
    const text = String(piece || '').trim()
    if (!text) continue
    const normalizedRJ = normalizeRJ(text)
    const key = normalizedRJ ? `RJ:${normalizedRJ}` : text
    if (seen.has(key)) continue
    seen.add(key)
    out.push(text)
  }
  return out
}

function getTaskSummary(item) {
  if (!item) {
    return []
  }

  const details = item.details || {}
  const metadata = details.metadata || {}
  const preview = details.preview || {}
  const pieces = []
  const recoveredFailureCount = pickMetricValue(item, '此前失败')
  const recoveredConflictCount = pickMetricValue(item, '问题作品')

  if (item.domain === 'import') {
    const targetLibrary = pickMetricValue(item, '目标库')
    const failureStage = getImportFailureStageLabel(item)
    if (failureStage) pieces.push(failureStage)
    if (targetLibrary) pieces.push(`目标库 ${targetLibrary}`)
    const normalizedRJ = formatRJCode(item.rjcode)
    if (!pieces.length && normalizedRJ && !containsRJ(item.title) && !containsRJ(item.subtitle)) {
      pieces.push(normalizedRJ)
    }
  } else if (item.domain === 'rj_subtitle') {
    const downloadCount = pickMetricValue(item, '下载')
    const writtenCount = pickMetricValue(item, '写入')
    const subtitleDir = item.target_path || metadata.subtitle_dir || ''
    const normalizedRJ = formatRJCode(item.rjcode)
    if (normalizedRJ) pieces.push(`RJ ${normalizedRJ}`)
    if (downloadCount) pieces.push(`下载 ${downloadCount}`)
    if (writtenCount) pieces.push(`写入 ${writtenCount}`)
    if (subtitleDir) pieces.push(`目录 ${getFileName(subtitleDir)}`)
  } else if (item.domain === 'subtitle_import') {
    const subtitleCount = pickMetricValue(item, '来源字幕') || preview.subtitle_count
    const candidateCount = pickMetricValue(item, '可执行候选') || pickMetricValue(item, '候选目录')
    const targetFolder = item.target_path || preview.selected_candidate?.folder_path || ''
    const normalizedRJ = formatRJCode(item.rjcode)
    if (normalizedRJ) pieces.push(`目标 ${normalizedRJ}`)
    if (subtitleCount) pieces.push(`候选字幕 ${subtitleCount}`)
    if (candidateCount) pieces.push(`候选目录 ${candidateCount}`)
    if (targetFolder) pieces.push(`目标目录 ${getFileName(targetFolder)}`)
  } else if (item.domain === 'asmr_sync') {
    const downloadFiles = pickMetricValue(item, '下载文件')
    const failedFiles = pickMetricValue(item, '失败文件')
    const uploadedCount = pickMetricValue(item, '已上传')
    const uploadedBytes = pickMetricValue(item, '上传大小')
    const averageUpload = pickMetricValue(item, '平均上传')
    const duration = pickMetricValue(item, '耗时')
    const normalizedRJ = formatRJCode(item.rjcode)
    if (normalizedRJ) pieces.push(`RJ ${normalizedRJ}`)
    if (downloadFiles) pieces.push(`文件 ${downloadFiles}`)
    if (uploadedCount) pieces.push(`上传 ${uploadedCount}`)
    if (uploadedBytes) pieces.push(uploadedBytes)
    if (averageUpload) pieces.push(averageUpload)
    if (duration) pieces.push(duration)
    if (failedFiles) pieces.push(`失败 ${failedFiles}`)
    if (item.subtitle) pieces.push(`来源 ${getFileName(item.subtitle)}`)
  } else if (item.domain === 'circle_completion') {
    const candidateCount = pickMetricValue(item, '候选')
    const dlsiteCount = pickMetricValue(item, 'DLsite')
    const downloadableCount = pickMetricValue(item, '可下载')
    if (item.title) pieces.push(item.title)
    if (candidateCount) pieces.push(`候选 ${candidateCount}`)
    if (dlsiteCount) pieces.push(`DLsite ${dlsiteCount}`)
    if (downloadableCount) pieces.push(`可下载 ${downloadableCount}`)
  } else {
    const outputName = pickMetricValue(item, '输出') || item.target_path
    const targetLibrary = pickMetricValue(item, '目标库')
    const normalizedRJ = formatRJCode(item.rjcode)
    if (normalizedRJ) pieces.push(`RJ ${normalizedRJ}`)
    if (outputName) pieces.push(`输出 ${getFileName(outputName)}`)
    if (targetLibrary) pieces.push(`目标库 ${targetLibrary}`)
  }

  if (recoveredFailureCount) pieces.push(`已恢复 ${recoveredFailureCount}`)
  if (recoveredConflictCount) pieces.push(recoveredConflictCount)

  return dedupeSummaryPieces(pieces).slice(0, 4)
}

function mapFilteredItems(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const rawItems = [
    ...(Array.isArray(metadata.filtered_items) ? metadata.filtered_items : []),
    ...(Array.isArray(metadata.filtered_files) ? metadata.filtered_files : []),
    ...(Array.isArray(metadata.filtered_dirs) ? metadata.filtered_dirs : [])
  ]

  const mapped = []
  const seen = new Set()
  for (const current of rawItems) {
    if (!current) continue
    const asObject = typeof current === 'object' ? current : { path: String(current) }
    const relativePath = String(asObject.relative_path || asObject.path || asObject.name || '').replace(/^[/\\]+|[/\\]+$/g, '')
    if (!relativePath || seen.has(relativePath)) continue
    seen.add(relativePath)
    mapped.push({
      key: relativePath,
      path: relativePath,
      type: asObject.type === 'dir' || asObject.is_dir ? 'dir' : 'file',
      sizeText: asObject.size !== undefined && asObject.size !== null ? formatBytes(asObject.size) : ''
    })
  }
  return mapped
}

function filterRemovedTreeRows(item) {
  return buildTreeRows(mapFilteredItems(item))
}

function mapUploadedFiles(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  const uploadedFiles = Array.isArray(metadata.uploaded_files) ? metadata.uploaded_files : []
  return uploadedFiles.map((current, index) => ({
    key: String(current?.relative_path || current?.name || current?.upload_path || `${index}`),
    relative_path: String(current?.relative_path || current?.name || current?.upload_path || ''),
    name: String(current?.name || current?.relative_path || current?.upload_path || '未命名文件'),
    type: 'file',
    size: Number(current?.size_bytes || 0),
  })).filter(item => item.relative_path || item.name)
}

function uploadedFileTreeRows(item) {
  return buildTreeRows(mapUploadedFiles(item))
}

function getRecoveredNotice(item) {
  const details = item?.details || {}
  const metadata = details.metadata || {}
  return String(metadata.recovered_notice || '').trim()
}

function getDLsiteFailureReason(item) {
  if (!item) return ''
  const details = item.details || {}
  const metadata = details.metadata || {}
  const indexMeta = metadata.index_meta || {}
  return String(indexMeta.dlsite_failure_reason || metadata.dlsite_failure_reason || '').trim()
}

function getCircleIndexMetaEntries(item) {
  if (item?.kind !== 'circle_completion_index') {
    return []
  }
  const metadata = item?.details?.metadata || {}
  const indexMeta = metadata.index_meta || {}
  const indexedCounts = metadata.indexed_counts || {}
  const entries = [
    ['社团', metadata.circle_name || metadata.circle_query || ''],
    ['Maker ID', indexMeta.maker_id || ''],
    ['来源模式', indexMeta.dlsite_source_mode || ''],
    ['DLsite失败原因', getDLsiteFailureReason(item)],
    ['本地候选', indexMeta.local_candidates_count],
    ['Kikoeru', indexMeta.kikoeru_candidates_count],
    ['DLsite原作', indexMeta.dlsite_profile_total || indexMeta.dlsite_candidates_count],
    ['合并候选', indexMeta.combined_candidates_count || indexMeta.aggregated_count],
    ['已检查下载', indexMeta.asmr_checked_count],
    ['可下载', indexMeta.asmr_available_count || indexedCounts.downloadable_count],
    ['最终作品', indexedCounts.works],
    ['服务器缺失', indexedCounts.missing_count],
  ]
  return entries
    .filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
    .map(([label, value]) => ({ label, value: String(value) }))
}

function getCircleIndexProgressLog(item) {
  if (item?.kind !== 'circle_completion_index') {
    return []
  }
  const metadata = item?.details?.metadata || {}
  const logs = Array.isArray(metadata.progress_log) ? metadata.progress_log : []
  return logs.slice().reverse()
}

function shouldShowTaskMetaStep(item) {
  const step = String(item?.current_step || '').trim()
  const statusLabel = String(item?.status_label || '').trim()
  if (!step) return false
  if (step === statusLabel) return false
  if (['完成', '已完成', '处理中', '等待中', '待处理', '已暂停', '失败', '等待重试', '等待人工'].includes(step)) {
    return false
  }
  return true
}

function getStatusTagType(status) {
  const types = {
    pending: 'info',
    processing: 'warning',
    paused: 'info',
    waiting_manual: 'warning',
    waiting_retry: 'danger',
    completed: 'success',
    failed: 'danger'
  }
  return types[status] || 'info'
}

function getStatusTagClass(status) {
  const normalized = String(status || '').trim()
  if (!normalized) return 'is-default'
  return `is-${normalized}`
}

function getActionLabel(action) {
  const labels = {
    pause: '暂停',
    resume: '恢复',
    cancel: '取消',
    retry_waiting: '立即重试',
    delete_waiting_retry: '移除等待重试',
    open_subtitle_import: '前往字幕补配'
  }
  return labels[action] || action
}

function getActionButtonType(action) {
  const types = {
    pause: 'warning',
    resume: 'primary',
    cancel: 'danger',
    retry_waiting: 'primary',
    delete_waiting_retry: 'danger',
    open_subtitle_import: 'primary'
  }
  return types[action] || 'info'
}

async function handleTaskAction(item, action) {
  try {
    const result = await taskCenterApi.action(item.id, action)
    if (result?.route_hint) {
      await router.push(result.route_hint)
    }
    ElMessage.success(result?.message || '操作成功')
    await refreshTaskCenter()
  } catch (error) {
    console.error('执行任务动作失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  }
}

function openTaskRoute(item) {
  if (!item?.route_hint) {
    return
  }
  router.push(item.route_hint)
}

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}
</script>

<style scoped>
.task-center-page {
  max-width: 1480px;
  margin: 0 auto;
  color: #1d1d1f;
}

.task-center-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 20px;
}

.hero-eyebrow {
  display: inline-block;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #0066cc;
}

.hero-title {
  margin: 0;
  font-size: 38px;
  font-weight: 600;
  line-height: 1.08;
  letter-spacing: -0.28px;
}

.hero-description {
  max-width: 760px;
  margin: 10px 0 0;
  font-size: 15px;
  line-height: 1.5;
  color: rgba(29, 29, 31, 0.62);
}

.refresh-button {
  min-width: 112px;
  height: 40px;
  border-radius: 999px;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.summary-tile {
  padding: 18px 20px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.06);
}

.summary-label {
  display: block;
  font-size: 13px;
  color: rgba(29, 29, 31, 0.56);
}

.summary-value {
  display: block;
  margin-top: 10px;
  font-size: 34px;
  font-weight: 600;
  line-height: 1;
}

.filters-card,
.task-list-card,
.task-detail-card {
  border: none;
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.06);
}

.filters-card {
  margin-bottom: 20px;
}

.filters-card :deep(.el-card__body),
.task-list-card :deep(.el-card__body),
.task-detail-card :deep(.el-card__body) {
  padding: 22px 24px 24px;
}

.filters-row {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  align-items: flex-start;
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.filter-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(29, 29, 31, 0.44);
}

.filter-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-chip {
  padding: 9px 14px;
  border: 0;
  border-radius: 999px;
  background: #f3f3f6;
  color: rgba(29, 29, 31, 0.72);
  font-size: 13px;
  cursor: pointer;
}

.filter-chip.active {
  background: #eaf3ff;
  color: #0066cc;
  font-weight: 600;
}

.task-search {
  width: 280px;
  margin-left: auto;
}

.task-center-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr);
  gap: 20px;
}

.list-header,
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 20px;
  font-weight: 600;
}

.list-count {
  font-size: 13px;
  font-weight: 500;
  color: rgba(29, 29, 31, 0.5);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-list-item {
  width: 100%;
  padding: 16px 18px;
  border: 0;
  border-radius: 22px;
  background: #f7f7fa;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.05);
  text-align: left;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}

.task-list-item:hover {
  transform: translateY(-1px);
  box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.08);
}

.task-list-item.active {
  background: #eef5ff;
  box-shadow: inset 0 0 0 1px rgba(0, 113, 227, 0.14);
}

.task-list-item-head {
  display: flex;
  gap: 14px;
  justify-content: space-between;
  align-items: flex-start;
}

.task-list-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.task-title {
  font-size: 17px;
  font-weight: 600;
  color: #1d1d1f;
}

.task-subtitle {
  font-size: 13px;
  color: rgba(29, 29, 31, 0.62);
}

.task-list-badges {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-wrap: nowrap;
  justify-content: flex-end;
  align-items: flex-end;
}

.task-list-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 10px;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.54);
}

.recovered-banner,
.detail-recovered-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.14), rgba(187, 247, 208, 0.22));
  box-shadow: inset 0 0 0 1px rgba(34, 197, 94, 0.16);
  color: #166534;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.55;
}

.recovered-banner-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.76);
  color: #16a34a;
  flex-shrink: 0;
}

.recovered-banner-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.recovered-banner-title {
  font-size: 12px;
  font-weight: 700;
  line-height: 1.2;
}

.recovered-banner-text {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.55;
}

.detail-recovered-banner {
  margin-bottom: 12px;
}

.task-progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}

.task-output-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
}

.task-output-label {
  font-size: 12px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.48);
}

.task-output-value {
  display: block;
  padding: 8px 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.88);
  color: #1d1d1f;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}

.task-progress-row :deep(.el-progress) {
  flex: 1;
}

.task-progress-value {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.5);
}

.task-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  align-items: center;
}

.metric-pill {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  max-width: 100%;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  color: rgba(29, 29, 31, 0.72);
  font-size: 12px;
  line-height: 1.4;
}

.detail-hero {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.detail-title {
  margin: 0;
  font-size: 28px;
  font-weight: 600;
  line-height: 1.12;
  letter-spacing: -0.24px;
}

.detail-subtitle {
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 1.5;
  color: rgba(29, 29, 31, 0.62);
}

.detail-tags {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex-wrap: nowrap;
  justify-content: flex-end;
  align-items: flex-end;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.detail-block {
  padding: 14px 16px;
  border-radius: 18px;
  background: #f7f7fa;
}

.detail-block-label {
  display: block;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.48);
}

.detail-block-value {
  display: block;
  margin-top: 8px;
  font-size: 15px;
  font-weight: 600;
}

.detail-section {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid rgba(29, 29, 31, 0.08);
}

.detail-entry-tree-box {
  max-height: 360px;
  overflow: auto;
  overflow-x: hidden;
  padding: 8px;
  border-radius: 14px;
  background: #f7f8fb;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, 0.06);
}

.detail-tree-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  padding-top: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.05);
}

.detail-tree-row:last-child {
  border-bottom: none;
}

.detail-tree-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.detail-tree-branch {
  color: rgba(29, 29, 31, 0.35);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  flex: 0 0 auto;
}

.detail-tree-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  font-size: 13px;
  flex: 0 0 auto;
}

.detail-tree-icon.is-dir {
  background: rgba(10, 132, 255, 0.12);
  color: #0a84ff;
}

.detail-tree-icon.is-file {
  background: rgba(120, 120, 128, 0.12);
  color: #4b5563;
}

.detail-tree-name {
  min-width: 0;
  color: #1d1d1f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.detail-tree-size {
  color: rgba(29, 29, 31, 0.55);
  font-size: 12px;
  white-space: nowrap;
}

.detail-section-label {
  display: block;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  color: rgba(29, 29, 31, 0.56);
}

.detail-step {
  font-size: 15px;
  line-height: 1.5;
  color: #1d1d1f;
}

.detail-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}

.detail-progress :deep(.el-progress) {
  flex: 1;
}

.detail-progress-text {
  font-size: 13px;
  color: rgba(29, 29, 31, 0.5);
}

.detail-error {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 16px;
  background: #fff1f0;
  color: #c03d2e;
  font-size: 13px;
  line-height: 1.5;
}

.detail-metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.detail-progress-log {
  display: grid;
  gap: 10px;
  max-height: 320px;
  overflow: auto;
  padding: 4px 2px 2px;
}

.detail-progress-log-row {
  display: grid;
  grid-template-columns: 132px 52px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 10px 12px;
  border: 1px solid #e8eef7;
  border-radius: 12px;
  background: #fbfdff;
}

.detail-progress-log-time,
.detail-progress-log-progress {
  font-size: 12px;
  font-weight: 700;
  color: #6d8199;
}

.detail-progress-log-message {
  font-size: 13px;
  line-height: 1.6;
  color: #243b5e;
  word-break: break-word;
}


.detail-metric-card {
  padding: 14px 16px;
  border-radius: 18px;
  background: #f7f7fa;
}

.detail-metric-label {
  display: block;
  font-size: 12px;
  color: rgba(29, 29, 31, 0.48);
}

.detail-metric-value {
  display: block;
  margin-top: 8px;
  font-size: 20px;
  font-weight: 600;
}

.detail-path-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.detail-path-label {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.48);
}

.detail-path-value {
  padding: 10px 12px;
  border-radius: 14px;
  background: #f7f7fa;
  color: #1d1d1f;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}

.detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 20px;
}

:deep(.el-card__header) {
  padding: 22px 24px 0;
  border-bottom: none;
}

:deep(.el-input__wrapper) {
  border-radius: 14px;
  box-shadow: 0 0 0 1px rgba(29, 29, 31, 0.08) inset;
}

:deep(.el-tag) {
  border-radius: 999px;
}

:deep(.task-status-tag.el-tag) {
  height: 24px;
  padding: 0 10px;
  border-radius: 10px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 600;
  line-height: 22px;
  letter-spacing: 0.01em;
}

:deep(.task-status-tag.is-completed.el-tag) {
  color: #2f7d32;
  background: linear-gradient(180deg, #eef9ef 0%, #e4f6e6 100%);
  border-color: #c8ebcf;
}

:deep(.task-status-tag.is-processing.el-tag) {
  color: #b86a00;
  background: linear-gradient(180deg, #fff6e8 0%, #ffedd2 100%);
  border-color: #ffd7a0;
}

:deep(.task-status-tag.is-pending.el-tag),
:deep(.task-status-tag.is-paused.el-tag) {
  color: #51606f;
  background: linear-gradient(180deg, #f4f6f8 0%, #eceff3 100%);
  border-color: #dde3ea;
}

:deep(.task-status-tag.is-waiting_manual.el-tag),
:deep(.task-status-tag.is-waiting_retry.el-tag) {
  color: #8f5a17;
  background: linear-gradient(180deg, #fff5df 0%, #ffe8bf 100%);
  border-color: #f3d39a;
}

:deep(.task-status-tag.is-failed.el-tag),
:deep(.task-status-tag.is-cancelled.el-tag),
:deep(.task-status-tag.is-canceled.el-tag) {
  color: #a63f3f;
  background: linear-gradient(180deg, #fff0f0 0%, #ffe3e3 100%);
  border-color: #f3c4c4;
}

:deep(.el-progress-bar__outer) {
  background: #e9e9ed;
}

:deep(.el-progress-bar__inner) {
  background: linear-gradient(90deg, #0071e3 0%, #2a8cff 100%);
}

@media (max-width: 1280px) {
  .task-center-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .detail-grid,
  .detail-metrics-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .task-center-hero {
    flex-direction: column;
    align-items: flex-start;
  }

  .hero-title {
    font-size: 32px;
  }

  .summary-strip {
    grid-template-columns: 1fr;
  }

  .filters-row {
    flex-direction: column;
  }

  .task-search {
    width: 100%;
    margin-left: 0;
  }

  .task-list-item-head,
  .detail-hero {
    flex-direction: column;
  }
}
</style>
