<template>
  <div class="subtitle-config-card">
    <template v-if="mode === 'settings'">
      <div class="subtitle-option-stack">
        <!-- 抓取行为 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <SlidersHorizontal class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">抓取行为</div>
              <div class="subtitle-block-tip">建任务和扫描命中策略。</div>
            </div>
          </div>

          <div class="subtitle-setting-list">
            <div class="subtitle-setting-item">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">覆盖已有字幕</div>
                <div class="subtitle-card-tip">同名字幕直接覆盖，适合重抓和修正。</div>
              </div>
              <el-switch :model-value="ctx.subtitleOptions.overwriteExisting" @update:model-value="ctx.setSubtitleOption('overwriteExisting', $event)" />
            </div>

            <div class="subtitle-setting-item subtitle-setting-item-stack">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">扫描深度</div>
                <div class="subtitle-card-tip">递归查找 RJ 文件夹，默认 3 层。</div>
              </div>
              <el-input-number
                :model-value="ctx.subtitleOptions.scanDepth"
                :min="1"
                :max="10"
                :step="1"
                controls-position="right"
                @update:model-value="ctx.setSubtitleOption('scanDepth', $event)"
              />
            </div>

            <div class="subtitle-setting-item">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">启用 metadata 匹配</div>
                <div class="subtitle-card-tip">读取音频标签，提高文件名配对准确度。</div>
              </div>
              <el-switch :model-value="ctx.subtitleOptions.enableMetadataMatch" @update:model-value="ctx.setSubtitleOption('enableMetadataMatch', $event)" />
            </div>

            <div class="subtitle-setting-item">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">已有字幕时跳过</div>
                <div class="subtitle-card-tip">已存在字幕就不进抓取队列。</div>
              </div>
              <el-switch :model-value="ctx.subtitleOptions.skipIfExistingSubtitles" @update:model-value="ctx.setSubtitleOption('skipIfExistingSubtitles', $event)" />
            </div>
          </div>
        </section>

        <!-- 命名与筛选 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <Filter class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[-8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">命名与筛选</div>
              <div class="subtitle-block-tip">配对后的命名口径和候选字幕过滤。</div>
            </div>
          </div>

          <div class="subtitle-setting-list">
            <div class="subtitle-setting-item subtitle-setting-item-stack">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">同名依据</div>
                <div class="subtitle-card-tip">一键应用后，以谁的名字为准。</div>
              </div>
              <div class="subtitle-naming-switch" role="radiogroup" aria-label="同名依据">
                <button
                  v-for="option in namingOptions"
                  :key="option.value"
                  type="button"
                  class="group/naming subtitle-naming-option"
                  :class="{ active: ctx.subtitleOptions.namingStrategy === option.value }"
                  role="radio"
                  :aria-checked="ctx.subtitleOptions.namingStrategy === option.value"
                  @click="ctx.setSubtitleOption('namingStrategy', option.value)"
                >
                  <component
                    :is="option.icon"
                    :class="['h-[13px] w-[13px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/naming:scale-110 group-hover/naming:rotate-[8deg]', option.color]"
                    :stroke-width="2.4"
                  />
                  <span>{{ option.label }}</span>
                </button>
              </div>
            </div>

            <div class="subtitle-setting-item">
              <div class="subtitle-setting-main">
                <div class="subtitle-option-title">启用字幕过滤</div>
                <div class="subtitle-card-tip">只筛字幕候选，不影响解压过滤配置。</div>
              </div>
              <el-switch :model-value="ctx.subtitleOptions.useFilterRules" @update:model-value="ctx.setSubtitleOption('useFilterRules', $event)" />
            </div>
          </div>

          <div v-if="ctx.subtitleOptions.useFilterRules" class="subtitle-filter-editor">
            <div class="subtitle-filter-editor-head">
              <div>
                <div class="subtitle-option-title subtitle-option-title-sm">字幕过滤规则</div>
                <div class="subtitle-card-tip">按文件名、路径或全文本匹配候选字幕。</div>
              </div>
              <button
                type="button"
                class="group/btn inline-flex shrink-0 items-center gap-1.5 rounded-[10px] border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-semibold text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-slate-300 hover:text-slate-900 active:scale-[0.96]"
                @click="handleAddSubtitleFilterRule"
              >
                <Plus class="h-[13px] w-[13px] text-sky-600 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:rotate-[90deg] group-hover/btn:scale-110" :stroke-width="2.4" />
                <span>添加规则</span>
              </button>
            </div>

            <div v-if="!ctx.subtitleOptions.subtitleFilterRules.length" class="subtitle-filter-empty">
              <Inbox class="h-[14px] w-[14px] text-slate-400" :stroke-width="2.2" />
              <span>还没有规则，先加一条。</span>
            </div>

            <div v-else class="subtitle-filter-list">
              <button
                v-for="(rule, index) in ctx.subtitleOptions.subtitleFilterRules"
                :key="rule.id"
                type="button"
                class="subtitle-filter-row"
                :class="{ active: activeFilterRuleKey === getFilterRuleKey(rule, index) }"
                @click="activeFilterRuleKey = getFilterRuleKey(rule, index)"
              >
                <span class="subtitle-filter-index">{{ index + 1 }}</span>
                <span class="min-w-0 flex-1">
                  <span class="subtitle-filter-summary-title">{{ String(rule.name || '').trim() || `规则 ${index + 1}` }}</span>
                  <span class="subtitle-filter-summary-pattern">{{ String(rule.pattern || '').trim() || '尚未填写正则' }}</span>
                </span>
                <span class="subtitle-filter-state" :class="{ off: rule.enabled === false }">{{ rule.enabled === false ? '停用' : '启用' }}</span>
              </button>
            </div>

            <div v-if="activeSubtitleFilterRule" class="subtitle-filter-detail">
              <div class="subtitle-filter-detail-head">
                <div>
                  <div class="subtitle-filter-detail-title">编辑 {{ activeSubtitleFilterRuleIndex + 1 }} 号规则</div>
                  <div class="subtitle-card-tip">完整填写规则名和正则，列表只保留摘要。</div>
                </div>
                <el-switch v-model="activeSubtitleFilterRule.enabled" size="small" />
              </div>
              <div class="subtitle-filter-form-grid">
                <label class="subtitle-filter-field">
                  <span>匹配范围</span>
                  <AppDropdown
                    v-model="activeSubtitleFilterRule.target"
                    :options="subtitleFilterTargetOptions"
                    class="subtitle-filter-target"
                    :width="110"
                    :menu-min-width="130"
                    :show-trigger-badge="false"
                  />
                </label>
                <label class="subtitle-filter-field">
                  <span>规则名称</span>
                  <el-input v-model="activeSubtitleFilterRule.name" size="small" placeholder="例如：反转版" />
                </label>
                <label class="subtitle-filter-field subtitle-filter-field-full">
                  <span>正则表达式</span>
                  <el-input
                    v-model="activeSubtitleFilterRule.pattern"
                    size="small"
                    type="textarea"
                    :autosize="{ minRows: 2, maxRows: 4 }"
                    placeholder="例如 (反转|reverse|無SE)"
                  />
                </label>
              </div>
              <div class="subtitle-filter-row-actions">
                <span class="subtitle-filter-target-badge">{{ getFilterRuleTargetLabel(activeSubtitleFilterRule.target) }}</span>
                <button
                  type="button"
                  class="group/btn inline-flex items-center gap-1 rounded-[8px] border border-rose-200 bg-white px-2.5 py-1 text-[11.5px] font-semibold text-rose-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.02] hover:border-rose-300 active:scale-[0.96]"
                  @click="removeActiveSubtitleFilterRule"
                >
                  <Trash2 class="h-[12px] w-[12px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/btn:rotate-[-12deg] group-hover/btn:scale-110" :stroke-width="2.4" />
                  <span>删除当前规则</span>
                </button>
              </div>
            </div>
          </div>
        </section>

        <!-- 任务展示 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <LayoutPanelLeft class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">任务展示</div>
              <div class="subtitle-block-tip">只控制面板显示，不影响执行和日志写入。</div>
            </div>
          </div>

          <div class="subtitle-pill-grid">
            <button
              v-for="pill in displayPills"
              :key="pill.key"
              type="button"
              class="group/pill subtitle-toggle-pill"
              :class="{ active: ctx.subtitleOptions[pill.key] }"
              @click="ctx.setSubtitleOption(pill.key, !ctx.subtitleOptions[pill.key])"
            >
              <component
                :is="pill.icon"
                :class="['h-[13px] w-[13px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/pill:scale-110 group-hover/pill:rotate-[8deg]', ctx.subtitleOptions[pill.key] ? '' : pill.color]"
                :stroke-width="2.4"
              />
              <span>{{ pill.label }}</span>
            </button>
          </div>
        </section>
      </div>
    </template>

    <template v-else-if="mode === 'pairing'">
      <div class="subtitle-option-stack">
        <!-- 选中快照 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <Gauge class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">选中快照</div>
              <div class="subtitle-block-tip">顺序点选、配对数量，一目了然。</div>
            </div>
          </div>
          <div class="stat-trio">
            <div
              v-for="row in pairingRows"
              :key="row.key"
              class="stat-cell group/stat"
            >
              <div class="flex items-center gap-1.5 text-slate-500">
                <component
                  :is="row.icon"
                  :class="['h-[14px] w-[14px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/stat:scale-110 group-hover/stat:rotate-[12deg]', row.color]"
                  :stroke-width="2.2"
                />
                <span class="text-[11.5px] font-semibold tracking-[-0.005em] truncate">{{ row.label }}</span>
              </div>
              <div class="mt-1 text-[30px] font-black leading-none text-slate-900 tabular-nums tracking-[-0.04em] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/stat:-translate-y-0.5">{{ row.value }}</div>
            </div>
          </div>
        </section>

        <!-- 快捷动作 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <Zap class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[-12deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">快捷动作</div>
              <div class="subtitle-block-tip">先点音频，再点字幕，生成顺序预配对。</div>
            </div>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              class="group/btn flex items-center justify-center gap-1.5 rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 text-[12px] font-semibold text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:hover:-translate-y-0.5 enabled:hover:scale-[1.02] enabled:hover:border-slate-300 enabled:hover:bg-slate-50 enabled:hover:shadow-[0_8px_16px_rgba(15,23,42,0.08)] enabled:active:scale-[0.96] disabled:opacity-40 disabled:cursor-not-allowed disabled:bg-slate-50/40"
              :disabled="!ctx.canClearSequenceSelection"
              @click="ctx.clearSubtitleSequenceSelection"
            >
              <Eraser class="h-[14px] w-[14px] text-slate-500 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:group-hover/btn:rotate-[-12deg] enabled:group-hover/btn:scale-110" :stroke-width="2.2" />
              <span>清空顺序</span>
            </button>
            <button
              type="button"
              class="group/btn flex items-center justify-center gap-1.5 rounded-[12px] border border-slate-200 bg-white px-3 py-2.5 text-[12px] font-semibold text-slate-700 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:hover:-translate-y-0.5 enabled:hover:scale-[1.02] enabled:hover:border-slate-300 enabled:hover:bg-slate-50 enabled:hover:shadow-[0_8px_16px_rgba(15,23,42,0.08)] enabled:active:scale-[0.96] disabled:opacity-40 disabled:cursor-not-allowed disabled:bg-slate-50/40"
              :disabled="!ctx.canClearManualPairs"
              @click="ctx.clearSubtitleManualPairs"
            >
              <Unlink class="h-[14px] w-[14px] text-slate-500 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:group-hover/btn:rotate-[12deg] enabled:group-hover/btn:scale-110" :stroke-width="2.2" />
              <span>清空配对</span>
            </button>
          </div>
        </section>

        <!-- 删除预审 -->
        <section class="subtitle-settings-block subtitle-help-card-danger group/card">
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-3 min-w-0">
              <span class="header-badge header-badge-danger">
                <ShieldAlert class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
              </span>
              <div class="min-w-0">
                <div class="subtitle-block-title">删除预审</div>
                <div class="subtitle-block-tip">已移出主流程，避免和配对动作混用。</div>
              </div>
            </div>
            <button
              type="button"
              class="group/btn inline-flex shrink-0 items-center gap-1.5 rounded-[10px] border border-rose-200 bg-white px-3 py-2 text-[12px] font-bold text-rose-600 transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:hover:-translate-y-0.5 enabled:hover:scale-[1.02] enabled:hover:border-rose-500 enabled:hover:bg-rose-500 enabled:hover:text-white enabled:hover:shadow-[0_10px_18px_rgba(244,63,94,0.28)] enabled:active:scale-[0.96] disabled:opacity-40 disabled:cursor-not-allowed"
              :disabled="!ctx.canOpenSubtitleInspectorFilterDeleteDialog"
              @click="ctx.openSubtitleInspectorFilterDeleteDialog"
            >
              <Trash2 class="h-[13px] w-[13px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] enabled:group-hover/btn:rotate-[-12deg] enabled:group-hover/btn:scale-110" :stroke-width="2.4" />
              <span>执行</span>
            </button>
          </div>
        </section>
      </div>
    </template>

    <template v-else>
      <div class="subtitle-option-stack">
        <!-- 文件快照 -->
        <section class="subtitle-settings-block group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge">
              <FolderTree class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">文件快照</div>
              <div class="subtitle-block-tip">搜索范围与选中规模一览。</div>
            </div>
          </div>
          <div class="stat-trio stat-trio-2">
            <div
              v-for="row in treeRows"
              :key="row.key"
              class="stat-cell group/stat"
            >
              <div class="flex items-center gap-1.5 text-slate-500">
                <component
                  :is="row.icon"
                  :class="['h-[14px] w-[14px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/stat:scale-110 group-hover/stat:rotate-[12deg]', row.color]"
                  :stroke-width="2.2"
                />
                <span class="text-[11.5px] font-semibold tracking-[-0.005em] truncate">{{ row.label }}</span>
              </div>
              <div class="mt-1 text-[30px] font-black leading-none text-slate-900 tabular-nums tracking-[-0.04em] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/stat:-translate-y-0.5">{{ row.value }}</div>
            </div>
          </div>
          <div class="search-row group/search">
            <span class="search-chip">
              <Search class="h-[11px] w-[11px] shrink-0 text-slate-400 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/search:rotate-[-10deg] group-hover/search:scale-[1.18] group-hover/search:text-slate-700" :stroke-width="2.6" />
              <span>搜索词</span>
            </span>
            <span
              class="min-w-0 flex-1 truncate text-[12px] font-semibold"
              :class="ctx.treeSearchText ? 'text-slate-900' : 'text-slate-400'"
              :title="ctx.treeSearchText || ''"
            >{{ ctx.treeSearchText || '未搜索' }}</span>
          </div>
        </section>

        <!-- 删除风险 -->
        <section class="subtitle-settings-block subtitle-help-card-danger group/card">
          <div class="flex items-center gap-3">
            <span class="header-badge header-badge-danger">
              <AlertTriangle class="h-[16px] w-[16px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover/card:scale-110 group-hover/card:rotate-[8deg]" :stroke-width="2.4" />
            </span>
            <div class="min-w-0">
              <div class="subtitle-block-title">删除风险</div>
              <div class="subtitle-block-tip">操作直接作用于字幕目录，批量前先确认范围。</div>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import {
  Gauge,
  Zap,
  Eraser,
  Unlink,
  Trash2,
  ShieldAlert,
  AlertTriangle,
  FolderTree,
  Search,
  Music,
  FileText,
  Link2,
  CheckSquare,
  Eye,
  SlidersHorizontal,
  Filter,
  LayoutPanelLeft,
  Plus,
  Inbox,
  Globe,
  PenLine,
  Download,
  AlertCircle
} from 'lucide-vue-next'
import AppDropdown from '../../common/AppDropdown.vue'

// 字幕过滤规则匹配范围选项
const subtitleFilterTargetOptions = [
  { value: 'name', label: '文件名' },
  { value: 'path', label: '路径' },
  { value: 'all', label: '全部' },
]

const props = defineProps({
  ctx: {
    type: Object,
    required: true
  },
  mode: {
    type: String,
    default: 'settings'
  }
})

const activeFilterRuleKey = ref('')

const pairingRows = computed(() => [
  { key: 'audio', label: '音频轨', icon: Music, color: 'text-sky-600', value: props.ctx?.pairingAudioSelectedCount || 0 },
  { key: 'subtitle', label: '字幕轨', icon: FileText, color: 'text-violet-600', value: props.ctx?.pairingSubtitleSelectedCount || 0 },
  { key: 'pairs', label: '配对组', icon: Link2, color: 'text-emerald-600', value: props.ctx?.pairingPairCount || 0 }
])

const treeRows = computed(() => [
  { key: 'selected', label: '已选', icon: CheckSquare, color: 'text-emerald-600', value: props.ctx?.treeSelectedCount || 0 },
  { key: 'visible', label: '可见', icon: Eye, color: 'text-sky-600', value: props.ctx?.treeVisibleCount || 0 }
])

const displayPills = [
  { key: 'showSourceSearch', label: '来源搜索', icon: Globe, color: 'text-sky-600' },
  { key: 'showWrittenFiles', label: '写入结果', icon: PenLine, color: 'text-emerald-600' },
  { key: 'showDownloadedFiles', label: '下载进度', icon: Download, color: 'text-indigo-600' },
  { key: 'showIssues', label: '问题项', icon: AlertCircle, color: 'text-amber-600' }
]

const namingOptions = [
  { value: 'audio', label: '以音频名为准', icon: Music, color: 'text-sky-600' },
  { value: 'subtitle', label: '以字幕名为准', icon: FileText, color: 'text-violet-600' }
]

const activeSubtitleFilterRuleIndex = computed(() => {
  const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
  if (!rules.length) return -1
  const index = rules.findIndex((rule, idx) => getFilterRuleKey(rule, idx) === activeFilterRuleKey.value)
  return index >= 0 ? index : 0
})

const activeSubtitleFilterRule = computed(() => {
  const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
  return activeSubtitleFilterRuleIndex.value >= 0 ? rules[activeSubtitleFilterRuleIndex.value] : null
})

function getFilterRuleKey(rule, index) {
  return rule?.id || `rule-${index}`
}

function getFilterRuleTargetLabel(target) {
  if (target === 'path') return '路径'
  if (target === 'all') return '全部'
  return '文件名'
}

function handleAddSubtitleFilterRule() {
  props.ctx?.addSubtitleFilterRule?.()
  nextTick(() => {
    const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
    const lastIndex = rules.length - 1
    if (lastIndex >= 0) activeFilterRuleKey.value = getFilterRuleKey(rules[lastIndex], lastIndex)
  })
}

function removeActiveSubtitleFilterRule() {
  const rule = activeSubtitleFilterRule.value
  if (!rule?.id) return
  props.ctx?.removeSubtitleFilterRule?.(rule.id)
  nextTick(() => {
    const rules = props.ctx?.subtitleOptions?.subtitleFilterRules || []
    const nextIndex = Math.min(activeSubtitleFilterRuleIndex.value, rules.length - 1)
    activeFilterRuleKey.value = nextIndex >= 0 ? getFilterRuleKey(rules[nextIndex], nextIndex) : ''
  })
}
</script>

<style scoped>
.subtitle-config-card {
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  display: grid;
  gap: 14px;
}

.subtitle-config-card :deep(.el-switch) {
  --el-switch-on-color: #0f172a;
  --el-switch-off-color: #e2e8f0;
}

.subtitle-config-card :deep(.el-switch__core) {
  background-color: #e2e8f0 !important;
  border-color: #e2e8f0 !important;
  box-shadow: none;
  transition: background-color 0.28s var(--ease-spring),
              border-color 0.28s var(--ease-spring),
              box-shadow 0.28s var(--ease-spring) !important;
}

.subtitle-config-card :deep(.el-switch__core .el-switch__action) {
  background-color: #ffffff !important;
}

.subtitle-config-card :deep(.el-switch.is-checked .el-switch__core) {
  background-color: #0f172a !important;
  border-color: #0f172a !important;
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.22) !important;
}

.subtitle-config-card :deep(.el-input-number) {
  width: 120px;
}

.subtitle-config-card :deep(.el-input-number .el-input__wrapper),
.subtitle-config-card :deep(.el-select__wrapper),
.subtitle-config-card :deep(.el-input__wrapper) {
  border-radius: 12px;
  background: #fff;
  box-shadow: inset 0 0 0 1px #d8e1ec;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-config-card :deep(.el-input-number .el-input__wrapper:hover),
.subtitle-config-card :deep(.el-select__wrapper:hover),
.subtitle-config-card :deep(.el-input__wrapper:hover) {
  box-shadow: inset 0 0 0 1px #c3d4e5;
}

.subtitle-config-card :deep(.el-input-number .el-input__wrapper.is-focus),
.subtitle-config-card :deep(.el-select__wrapper.is-focused),
.subtitle-config-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: inset 0 0 0 1px #7ea8d8, 0 0 0 3px rgba(114, 157, 208, 0.16);
}

.subtitle-naming-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
  width: 100%;
  padding: 5px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: none;
}

.subtitle-naming-option {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 0;
  min-height: 32px;
  padding: 7px 8px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-naming-option:hover {
  transform: translateY(-1px) scale(1.01);
  color: #0f172a;
  background: #ffffff;
  border-color: #e2e8f0;
}

.subtitle-naming-option:active {
  transform: scale(0.96);
}

.subtitle-naming-option.active {
  border-color: #bfdbfe;
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.08);
}

.subtitle-config-card :deep(.el-button) {
  border-radius: 12px;
  font-size: 12px;
  font-weight: 800;
  transition: all 0.28s var(--ease-spring);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.subtitle-config-card :deep(.el-button:not(.is-disabled):not(:disabled):not(.is-loading):hover) {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 12px 22px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.subtitle-config-card :deep(.el-button:active) {
  transform: scale(0.96);
}

.subtitle-config-mode-title {
  font-size: 15px;
  line-height: 1.1;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.02em;
}

.subtitle-config-mode-copy {
  font-size: 11px;
  line-height: 1.6;
  color: #64748b;
  max-width: 24ch;
}

.subtitle-option-stack {
  display: grid;
  gap: 14px;
}

.subtitle-settings-block,
.subtitle-help-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: none;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-settings-block:hover,
.subtitle-help-card:hover {
  border-color: #cbd5e1;
  box-shadow: none;
}

.subtitle-help-card-danger {
  background: linear-gradient(180deg, #fff5f5 0%, #ffffff 60%);
  border-color: #fecaca;
}

.subtitle-help-card-danger:hover {
  border-color: #fca5a5;
  box-shadow: 0 8px 20px rgba(244, 63, 94, 0.08);
}


.stat-trio {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: end;
}

.stat-trio-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.stat-cell {
  position: relative;
  min-width: 0;
  padding: 0 12px;
}

.stat-cell:first-child {
  padding-left: 0;
}

.stat-cell:last-child {
  padding-right: 0;
}

.stat-cell + .stat-cell::before {
  content: '';
  position: absolute;
  left: 0;
  top: 12%;
  bottom: 12%;
  width: 1px;
  background: linear-gradient(180deg, transparent 0%, #e2e8f0 28%, #e2e8f0 72%, transparent 100%);
}

.search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  transition: all 0.28s var(--ease-spring);
}

.search-row:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.search-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  font-size: 10.5px;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.01em;
  flex-shrink: 0;
  transition: all 0.28s var(--ease-spring);
}

.search-row:hover .search-chip {
  border-color: #cbd5e1;
  color: #0f172a;
}

.subtitle-block-head {
  display: grid;
  gap: 3px;
}

.subtitle-block-title {
  font-size: 13px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: #1f2d3d;
}

.subtitle-block-tip {
  font-size: 11px;
  line-height: 1.55;
  color: #74869d;
}

.subtitle-setting-list,
.subtitle-filter-list {
  display: grid;
  gap: 10px;
}

.subtitle-setting-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
}

.subtitle-setting-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.subtitle-setting-item:first-child {
  padding-top: 0;
}

.subtitle-setting-item-stack {
  grid-template-columns: 1fr;
  align-items: start;
}

.subtitle-setting-main {
  display: grid;
  gap: 3px;
}

.subtitle-option-title {
  font-size: 13px;
  font-weight: 800;
  color: #1f2d3d;
  letter-spacing: -0.01em;
}

.subtitle-option-title-sm {
  font-size: 12px;
}

.subtitle-card-tip {
  font-size: 11px;
  line-height: 1.6;
  color: #64748b;
}

.subtitle-filter-editor {
  display: grid;
  gap: 10px;
  margin-top: 4px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: #ffffff;
}

.subtitle-filter-editor-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.subtitle-inline-btn {
  flex-shrink: 0;
}

.subtitle-filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 48px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 13px;
  background: #ffffff;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
  box-shadow: none;
}

.subtitle-filter-row:hover {
  border-color: #cbd5e1;
  transform: translateY(-1px) scale(1.01);
  box-shadow: none;
}

.subtitle-filter-row.active {
  border-color: #bfdbfe;
  background: #ffffff;
  box-shadow: inset 3px 0 0 #3b82f6, 0 0 0 2px rgba(59, 130, 246, 0.08);
}

.subtitle-filter-list {
  display: grid;
  gap: 8px;
  max-height: 166px;
  overflow-y: auto;
  padding-right: 2px;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #cbd5e1 transparent;
}

.subtitle-filter-list::-webkit-scrollbar {
  width: 6px;
}

.subtitle-filter-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #cbd5e1;
}

.subtitle-filter-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  font-size: 10.5px;
  font-weight: 800;
  color: #475569;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-filter-row:hover .subtitle-filter-index,
.subtitle-filter-row.active .subtitle-filter-index {
  transform: scale(1.06);
  border-color: #bfdbfe;
  background: #ffffff;
  color: #2563eb;
}

.subtitle-filter-row:hover .subtitle-filter-summary-title,
.subtitle-filter-row.active .subtitle-filter-summary-title {
  color: #0f172a;
}

.subtitle-filter-summary-title,
.subtitle-filter-summary-pattern {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subtitle-filter-summary-title {
  font-size: 12px;
  font-weight: 800;
  color: #1e293b;
  letter-spacing: -0.01em;
}

.subtitle-filter-summary-pattern {
  margin-top: 2px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 10.5px;
  line-height: 1.25;
  color: #64748b;
}

.subtitle-filter-target-badge,
.subtitle-filter-state {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 38px;
  height: 22px;
  border-radius: 999px;
  border: 1px solid #dbeafe;
  background: #ffffff;
  padding: 0 8px;
  font-size: 10.5px;
  font-weight: 800;
  color: #2563eb;
}

.subtitle-filter-state {
  min-width: 34px;
  border-color: #dcfce7;
  background: #ffffff;
  color: #16a34a;
}

.subtitle-filter-state.off {
  border-color: #e2e8f0;
  background: #ffffff;
  color: #94a3b8;
}

.subtitle-filter-detail {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid #dbe4ee;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: none;
}

.subtitle-filter-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.subtitle-filter-detail-title {
  font-size: 12.5px;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.subtitle-filter-form-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 9px;
}

.subtitle-filter-field {
  display: grid;
  gap: 5px;
}

.subtitle-filter-field > span {
  font-size: 10.5px;
  font-weight: 800;
  color: #64748b;
}

.subtitle-filter-detail :deep(.el-textarea__inner),
.subtitle-filter-detail :deep(.el-input__wrapper),
.subtitle-filter-detail :deep(.el-select__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px #dbe4ee inset;
}

.subtitle-filter-detail :deep(.el-textarea__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 11px;
  line-height: 1.45;
}

.subtitle-filter-row-top,
.subtitle-filter-row-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.subtitle-filter-target {
  min-width: 108px;
  max-width: 132px;
}

.subtitle-filter-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 14px 12px;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
  background: #ffffff;
  font-size: 11.5px;
  font-weight: 600;
  color: #64748b;
}

.subtitle-pill-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.subtitle-toggle-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 40px;
  padding: 8px 12px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.28s var(--ease-spring);
}

.subtitle-toggle-pill:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: #cbd5e1;
  color: #0f172a;
  box-shadow: 0 8px 16px rgba(15, 23, 42, 0.06);
}

.subtitle-toggle-pill:active {
  transform: scale(0.96);
}

.subtitle-toggle-pill.active {
  border-color: #0f172a;
  background: #0f172a;
  color: #ffffff;
  box-shadow: 0 10px 18px rgba(15, 23, 42, 0.22);
}

.header-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  flex-shrink: 0;
  color: #ffffff;
  background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
  border: 1px solid #0b1324;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.08);
  transition: all 0.3s var(--ease-spring);
}

.header-badge-amber {
  background: linear-gradient(180deg, #f59e0b 0%, #d97706 100%);
  border-color: #b45309;
  box-shadow: 0 6px 14px rgba(217, 119, 6, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.2);
}

.header-badge-danger {
  background: linear-gradient(180deg, #f43f5e 0%, #e11d48 100%);
  border-color: #be123c;
  box-shadow: 0 6px 14px rgba(244, 63, 94, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.2);
}

.group\/card:hover .header-badge {
  transform: scale(1.06);
  box-shadow: 0 10px 20px rgba(15, 23, 42, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.12);
}

.group\/card:hover .header-badge-amber {
  box-shadow: 0 10px 20px rgba(217, 119, 6, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.group\/card:hover .header-badge-danger {
  box-shadow: 0 10px 20px rgba(244, 63, 94, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

@keyframes danger-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.08); }
}

@media (max-width: 960px) {
  .subtitle-setting-item {
    grid-template-columns: 1fr;
    align-items: start;
  }

  .subtitle-pill-grid {
    grid-template-columns: 1fr;
  }

  .subtitle-filter-editor-head {
    flex-direction: column;
    align-items: stretch;
  }

  .subtitle-filter-target {
    min-width: 0;
    max-width: none;
  }
}
</style>
