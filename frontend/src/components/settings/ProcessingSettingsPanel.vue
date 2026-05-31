<template>
  <div class="processing-stack">
    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">文件夹监视器</div>
        <div class="toggle-stack">
          <SettingsToggleRow v-model="config.watcher.enabled" title="启用监视器" subtitle="后台定期扫描待处理目录。" />
          <SettingsToggleRow v-model="config.watcher.auto_start" title="自动开始处理" subtitle="发现新项目后直接进入处理链路。" />
          <SettingsToggleRow v-model="config.watcher.auto_classify" title="自动分类" subtitle="监视链路里跟随分类规则落盘。" />
          <SettingsToggleRow v-model="config.watcher.delete_after_process" title="处理后删除原文件" subtitle="谨慎开启，适合完全托管的目录。" />
        </div>
        <SettingsFieldCard label="扫描间隔（秒）">
          <SettingsRangeStepper v-model="config.watcher.scan_interval" :min="10" :max="300" :step="10" />
        </SettingsFieldCard>
      </div>

      <div class="settings-card">
        <div class="card-title">处理与解压</div>
        <div class="field-stack">
          <SettingsFieldCard label="最大任务并发数">
            <SettingsRangeStepper v-model="config.processing.max_workers" :min="1" :max="10" />
          </SettingsFieldCard>
          <SettingsFieldCard label="解压并发数（7z 子进程）">
            <div class="extract-concurrency-row">
              <AppDropdown
                :model-value="config.extract.max_concurrent_extractions"
                @update:model-value="v => (config.extract.max_concurrent_extractions = v)"
                :options="concurrencyOptions"
                :width="220"
              />
              <span
                v-if="storageChip"
                class="storage-chip"
                :class="storageChip.tone"
                :title="storageChip.tooltip"
              >
                <HardDrive v-if="storageChip.icon === 'hdd'" :size="12" :stroke-width="2.2" />
                <Zap v-else-if="storageChip.icon === 'ssd'" :size="12" :stroke-width="2.2" />
                <HelpCircle v-else :size="12" :stroke-width="2.2" />
                {{ storageChip.label }}
              </span>
            </div>
            <template #hint>
              <span v-if="storageInfoLoading">正在探测存储类型…</span>
              <span v-else-if="storageHintText">{{ storageHintText }}</span>
              <span v-else>auto 模式下后端会自动根据存储类型选择并发数，HDD=1、SSD 最多 3。</span>
            </template>
          </SettingsFieldCard>
          <SettingsFieldCard label="单个解压进程线程数">
            <AppDropdown
              v-model="config.extract.seven_zip_threads"
              :options="sevenZipThreadOptions"
              :width="260"
            />
            <template #hint>
              控制 7-Zip 的 -mmt 参数。并发数管“同时几个包”，这里管“每个包吃多少线程”；HDD 建议 1-2，SSD / NVMe 可用自动或 4+。
            </template>
          </SettingsFieldCard>
          <SettingsFieldCard label="7-Zip 路径">
            <input v-model="config.extract.seven_zip_path" class="field-input" type="text" placeholder="例如 C:\Program Files\7-Zip\7z.exe">
          </SettingsFieldCard>
          <SettingsFieldCard label="ZIP 文件名编码">
            <AppDropdown
              v-model="config.extract.zip_encoding"
              :options="zipEncodingOptions"
              :width="260"
            />
            <template #hint>
              后端会先嗅探 ZIP 中央目录；嗅探不到时再使用这里的兜底代码页。
            </template>
          </SettingsFieldCard>
          <SettingsToggleRow v-model="config.extract.auto_repair_extension" title="自动修复后缀名" subtitle="针对异常扩展名做兼容修复。" />
          <SettingsToggleRow v-model="config.extract.verify_after_extract" title="解压后验证" subtitle="解压后再做结果校验，降低脏目录风险。" />
          <SettingsToggleRow v-model="config.extract.prefer_unar_for_rar" title="RAR 优先使用 unar" subtitle="对日文 / 中文 RAR 文件名更稳，unar 不可用时自动回退 7-Zip。" />
          <SettingsToggleRow v-model="config.extract.filename_password_sniff_enabled" title="文件名密码嗅探" subtitle="从压缩包文件名模板里提取密码，命中后跳过逐个试密码。" />
          <SettingsFieldCard v-if="config.extract.filename_password_sniff_enabled" label="密码嗅探模板">
            <textarea
              v-model="filenamePasswordSniffTemplatesText"
              class="field-input template-textarea"
              rows="3"
              spellcheck="false"
              placeholder="{name}({password})"
            />
            <template #hint>
              每行一个模板，必须包含 {password}；例如 RJ01381271(SOUTH+).zip 会由 {name}({password}) 提取 SOUTH+。
            </template>
          </SettingsFieldCard>
          <SettingsToggleRow v-model="config.extract.extract_nested_archives" title="自动解压嵌套压缩包" subtitle="适合复杂包结构，但会增加处理时长。" />
          <SettingsFieldCard v-if="config.extract.extract_nested_archives" label="最大嵌套深度">
            <SettingsRangeStepper v-model="config.extract.max_nested_depth" :min="1" :max="10" />
          </SettingsFieldCard>
        </div>
      </div>
    </div>

    <div class="settings-grid two">
      <div class="settings-card">
        <div class="card-title">正常解压流程</div>
        <div class="pill-switch-grid">
          <SettingsToggleChip v-for="item in autoProcessItems" :key="item.key" v-model="config.auto_process[item.key]" :label="item.label" />
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">已有文件夹流程</div>
        <div class="pill-switch-grid">
          <SettingsToggleChip v-for="item in processExistingItems" :key="item.key" v-model="config.process_existing[item.key]" :label="item.label" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { HardDrive, HelpCircle, Zap } from 'lucide-vue-next'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import SettingsToggleChip from './SettingsToggleChip.vue'
import SettingsRangeStepper from './SettingsRangeStepper.vue'
import AppDropdown from '../common/AppDropdown.vue'
import { systemApi } from '../../api'

const props = defineProps({
  config: { type: Object, required: true }
})

const autoProcessItems = [
  { key: 'check_duplicate', label: '预检重复' },
  { key: 'import_linked_translation_subtitles', label: '字幕补配预检' },
  { key: 'extract', label: '解压文件' },
  { key: 'fetch_metadata', label: '获取元数据' },
  { key: 'rename', label: '重命名' },
  { key: 'filter', label: '文件过滤' },
  { key: 'classify', label: '智能分类' },
  { key: 'archive', label: '归档压缩包' }
]

const processExistingItems = [
  { key: 'check_duplicate', label: '预检重复' },
  { key: 'fetch_metadata', label: '获取元数据' },
  { key: 'rename', label: '重命名' },
  { key: 'filter', label: '文件过滤' },
  { key: 'import_lrc', label: '导入 LRC' },
  { key: 'classify', label: '智能分类' }
]

const zipEncodingOptions = [
  { value: 932, label: 'Shift-JIS / CP932（日文）', description: 'DLsite 日文 ZIP 的常见兜底' },
  { value: 936, label: 'GBK / CP936（中文）', description: '中文 Windows ZIP 的常见兜底' },
  { value: 950, label: 'Big5 / CP950（繁中）', description: '繁体中文旧 ZIP 的兜底' },
  { value: 0, label: '不强制代码页', description: '只依赖 7-Zip 默认行为' }
]

const filenamePasswordSniffTemplatesText = computed({
  get() {
    const templates = props.config?.extract?.filename_password_sniff_templates
    return Array.isArray(templates) ? templates.join('\n') : ''
  },
  set(value) {
    props.config.extract.filename_password_sniff_templates = String(value || '')
      .split(/\r?\n/)
      .map(item => item.trim())
      .filter(Boolean)
  }
})

// ---- 解压并发下拉 + 存储类型探测 ----
const concurrencyOptions = [
  {
    value: 0,
    label: '自动（推荐）',
    description: '后端探测 temp_path 所在盘：SSD → 3，HDD / 未知 → 1'
  },
  { value: 1, label: '1（HDD 保守）', description: '串行解压，机械盘寿命最友好' },
  { value: 2, label: '2', description: '中档 SSD 或 HDD 抢吞吐（不推荐）' },
  { value: 3, label: '3（SSD 推荐）', description: 'SSD / NVMe 推荐，吃满多核' },
  { value: 4, label: '4（高端 NVMe）', description: 'NVMe + 高核心 CPU 才适合' }
]

const sevenZipThreadOptions = [
  { value: 'on', label: '自动（7-Zip 默认）', description: '等价 -mmt=on，由 7-Zip 按格式和 CPU 自己调度' },
  { value: 'off', label: '1（单线程）', description: '最保守，HDD 或低功耗机器适合' },
  { value: '2', label: '2 线程', description: '机械盘或轻负载保守加速' },
  { value: '4', label: '4 线程', description: '普通 SSD 推荐起点' },
  { value: '6', label: '6 线程', description: '多核 CPU + SSD' },
  { value: '8', label: '8 线程', description: 'NVMe / 高性能 CPU' },
  { value: '12', label: '12 线程', description: '高端桌面 CPU，注意温度和 IO' },
  { value: '16', label: '16 线程', description: '只建议 NVMe 和高核心机器' },
  { value: '', label: '不传 -mmt', description: '完全使用 7-Zip 内部默认值' }
]

const storageInfo = ref(null)
const storageInfoLoading = ref(false)

async function loadStorageInfo() {
  storageInfoLoading.value = true
  try {
    storageInfo.value = await systemApi.storageInfo()
  } catch (err) {
    console.warn('[settings] 加载存储类型探测结果失败', err)
    storageInfo.value = null
  } finally {
    storageInfoLoading.value = false
  }
}

onMounted(loadStorageInfo)

// 配置里 storage.temp_path 改变时，重新探测
watch(
  () => props.config?.storage?.temp_path,
  (next, prev) => {
    if (next && next !== prev) {
      loadStorageInfo()
    }
  }
)

// 当前选值变化（从 auto 切到固定，或反之）时刷新 hint 里的 resolved_limit 说明
watch(
  () => props.config?.extract?.max_concurrent_extractions,
  () => {
    // 这里不重新请求后端（并发值不影响存储类型探测），只是触发 hint 计算。
  }
)

const storageChip = computed(() => {
  if (!storageInfo.value) return null
  const primary = storageInfo.value.primary_type
  if (primary === 'ssd') {
    return {
      icon: 'ssd',
      label: 'SSD',
      tone: 'tone-emerald',
      tooltip: (storageInfo.value.probes?.[0]?.path) || 'temp_path 所在盘是 SSD'
    }
  }
  if (primary === 'hdd') {
    return {
      icon: 'hdd',
      label: 'HDD',
      tone: 'tone-amber',
      tooltip: (storageInfo.value.probes?.[0]?.path) || 'temp_path 所在盘是 HDD'
    }
  }
  return {
    icon: 'unknown',
    label: '未知',
    tone: 'tone-slate',
    tooltip: '未能探测存储类型，后端会保守退到并发 1（HDD 安全默认）'
  }
})

const storageHintText = computed(() => {
  const info = storageInfo.value
  if (!info) return ''
  const configured = Number(props.config?.extract?.max_concurrent_extractions ?? 0)
  const typeLabel = info.primary_type === 'ssd' ? 'SSD' : info.primary_type === 'hdd' ? 'HDD' : '未知存储'
  const probePath = info.probes?.[0]?.path || ''

  if (configured === 0) {
    return `auto 模式：检测到 ${typeLabel}${probePath ? `（${probePath}）` : ''}，实际并发 ${info.resolved_limit}`
  }
  // 用户固定值：提示实际会生效的是 configured，但对比 auto 推荐值
  const autoHint = info.primary_type === 'ssd'
    ? `auto 模式会推荐 ${Math.min(info.max_workers || 3, 3)}`
    : 'auto 模式会推荐 1'
  return `当前固定并发 ${configured}（检测到 ${typeLabel}，${autoHint}；若想让后端自动适配，请改回"自动"）`
})
</script>

<style scoped>
.processing-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-grid,
.settings-card,
.pill-switch-grid,
.field-stack,
.toggle-stack {
  overflow: visible;
}

.settings-grid {
  display: grid;
  gap: 24px;
  align-items: start;
}

.settings-grid.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.settings-card {
  padding: 0;
  border: none;
  background: transparent;
  box-shadow: none;
  min-height: 0;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 14px;
  color: var(--set-text-strong);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

.field-stack,
.toggle-stack {
  display: grid;
  gap: 12px;
}

.pill-switch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

/* SettingsFieldCard 默认 slot 里裸 input 的统一外观 */
.field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--set-border);
  border-radius: 10px;
  background: var(--set-field-bg);
  color: var(--set-text-strong);
  font-size: 13.5px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:hover { border-color: var(--set-border-strong); }

.field-input:focus {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

.field-input::placeholder { color: var(--set-text-subtle); }

.template-textarea {
  min-height: 86px;
  padding: 10px 12px;
  resize: vertical;
  line-height: 1.55;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}

/* 解压并发：下拉 + 存储类型 chip */
.extract-concurrency-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.storage-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px 3px 7px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.1px;
  border: 1px solid transparent;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.storage-chip:hover {
  transform: translateY(-1px) scale(1.04);
}

.storage-chip.tone-emerald {
  background: linear-gradient(180deg, rgba(209, 250, 229, 0.95), rgba(167, 243, 208, 0.85));
  border-color: rgba(16, 185, 129, 0.25);
  color: #065f46;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 1px 2px rgba(16, 185, 129, 0.14);
}

.storage-chip.tone-amber {
  background: linear-gradient(180deg, rgba(254, 243, 199, 0.95), rgba(253, 230, 138, 0.85));
  border-color: rgba(217, 119, 6, 0.25);
  color: #92400e;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 1px 2px rgba(217, 119, 6, 0.14);
}

.storage-chip.tone-slate {
  background: linear-gradient(180deg, rgba(241, 245, 249, 0.95), rgba(226, 232, 240, 0.85));
  border-color: rgba(100, 116, 139, 0.22);
  color: #475569;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6), 0 1px 2px rgba(100, 116, 139, 0.12);
}

@media (max-width: 1200px) {
  .settings-grid.two,
  .pill-switch-grid {
    grid-template-columns: 1fr;
  }
}
</style>
