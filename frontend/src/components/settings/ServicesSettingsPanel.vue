<template>
  <div class="services-stack">
    <div class="settings-grid two">
      <!-- Kikoeru 服务器查重 -->
      <div class="settings-card">
        <div class="card-title">Kikoeru 服务器查重</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.kikoeru_server.enabled" title="启用 Kikoeru 查重" subtitle="预检时同时查询远端服务器。" />
          <SettingsFieldCard label="服务器地址">
            <input v-model="config.kikoeru_server.server_url" class="field-input" type="text" placeholder="http://192.168.1.100:8088">
          </SettingsFieldCard>
          <SettingsFieldCard label="用户名">
            <input v-model="config.kikoeru_server.username" class="field-input" type="text" placeholder="登录用户名">
          </SettingsFieldCard>
          <SettingsFieldCard label="密码">
            <AnimatedPasswordInput v-model="config.kikoeru_server.password" placeholder="登录密码" autocomplete="current-password" />
          </SettingsFieldCard>
          <div class="mini-grid two">
            <SettingsFieldCard label="请求超时">
              <el-input-number v-model="config.kikoeru_server.timeout" :min="1" :max="60" class="field-number" />
            </SettingsFieldCard>
            <SettingsFieldCard label="缓存秒数">
              <el-input-number v-model="config.kikoeru_server.cache_ttl" :min="0" :max="3600" class="field-number" />
            </SettingsFieldCard>
          </div>
          <SettingsToggleRow v-model="config.kikoeru_server.check_in_preextract" title="预检查重" subtitle="在解压预检阶段就使用远端查重。" />
          <div class="service-action-row">
            <button type="button" class="ghost-inline-btn" :disabled="kikoeruBusy" @click="runKikoeruConnectionTest">测试连接</button>
            <button type="button" class="ghost-inline-btn" :disabled="kikoeruBusy" @click="runKikoeruTokenFetch">获取 Token</button>
            <button type="button" class="ghost-inline-btn" :disabled="kikoeruBusy" @click="runKikoeruCacheClear">清缓存</button>
          </div>
          <SettingsFieldCard label="测试查重 RJ" hint="实际链路：先从 DL 侧取关联作品，再把主 RJ 和关联 RJ 逐个送到 Kikoeru 查重。">
            <div class="service-inline-row">
              <input v-model="kikoeruTestRJCode" class="field-input" type="text" placeholder="输入作品号，例如 123456" @keyup.enter="runKikoeruDuplicateTest">
              <button
                type="button"
                class="service-lottie-trigger"
                :class="[`is-${kikoeruButtonState}`, { 'is-busy': kikoeruBusy }]"
                :disabled="kikoeruBusy || !kikoeruTestRJCode.trim()"
                @click="runKikoeruDuplicateTest"
              >
                <span class="service-lottie-trigger__animation">
                  <DotLottieVue
                    :key="kikoeruButtonState"
                    ref="kikoeruButtonLottieRef"
                    class="service-lottie-trigger__player"
                    :src="kikoeruButtonLottieSrc"
                    :autoplay="kikoeruButtonState !== 'idle'"
                    :loop="kikoeruButtonState === 'loading'"
                    :speed="kikoeruButtonState === 'loading' ? 0.9 : 1"
                    mode="forward"
                    :use-frame-interpolation="true"
                    :render-config="{ autoResize: true }"
                  />
                </span>
                <span class="service-lottie-trigger__label">{{ kikoeruButtonLabel }}</span>
              </button>
            </div>
          </SettingsFieldCard>
          <div v-if="kikoeruStatusMessage || kikoeruCheckResult" class="service-result-card">
            <div v-if="kikoeruStatusMessage" class="service-result-line">{{ kikoeruStatusMessage }}</div>
            <template v-if="kikoeruCheckResult">
              <div class="service-result-grid">
                <div><span class="service-result-key">请求 RJ</span><strong>{{ kikoeruCheckResult.requested_rjcode || kikoeruTestRJCode }}</strong></div>
                <div><span class="service-result-key">命中结果</span><strong>{{ kikoeruCheckResult.found ? '关联链路命中' : '整条链路未命中' }}</strong></div>
                <div><span class="service-result-key">主命中 RJ</span><strong>{{ kikoeruCheckResult.matched_rjcode || '-' }}</strong></div>
                <div><span class="service-result-key">来源</span><strong>{{ kikoeruCheckResult.source || '-' }}</strong></div>
              </div>
              <div v-if="kikoeruCheckResult.linked_works_total" class="service-result-line">DL 关联作品数：{{ kikoeruCheckResult.linked_works_total }}</div>
              <div v-if="kikoeruCheckResult.linked_rjcodes?.length" class="service-result-line">DL 关联 RJ：{{ kikoeruCheckResult.linked_rjcodes.join(', ') }}</div>
              <div v-if="kikoeruCheckResult.title" class="service-result-line">标题：{{ kikoeruCheckResult.title }}</div>
              <div v-if="kikoeruCheckResult.message" class="service-result-line">{{ kikoeruCheckResult.message }}</div>
              <div v-if="kikoeruCheckResult.linked_hits?.length" class="service-result-line">关联命中：{{ kikoeruCheckResult.linked_hits.join(', ') }}</div>
            </template>
          </div>
        </div>
      </div>

      <!-- ASMR 同步下载 -->
      <div class="settings-card">
        <div class="card-title">ASMR 同步下载</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.asmr_sync.enabled" title="启用 ASMR 同步" subtitle="允许从 asmr.one 拉音频与字幕。" />
          <div class="mini-grid two">
            <SettingsFieldCard label="最大并发下载数">
              <el-input-number v-model="config.asmr_sync.max_concurrent_downloads" :min="1" :max="10" class="field-number" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最大重试次数">
              <el-input-number v-model="config.asmr_sync.max_retry_count" :min="1" :max="100" class="field-number" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="增强会话并发">
              <el-input-number v-model="config.asmr_sync.enhanced_max_parallel_sessions" :min="1" :max="10" class="field-number" />
            </SettingsFieldCard>
            <SettingsFieldCard label="单会话并发">
              <el-input-number v-model="config.asmr_sync.enhanced_per_session_concurrency" :min="1" :max="10" class="field-number" />
            </SettingsFieldCard>
          </div>
          <SettingsFieldCard label="重试 Cron">
            <input v-model="config.asmr_sync.retry_cron" class="field-input" type="text" placeholder="0 */1 * * *">
          </SettingsFieldCard>
          <div class="mini-grid two">
            <SettingsFieldCard label="HTTP 代理" hint="用于 asmr.one 音频下载。">
              <input v-model="config.asmr_sync.http_proxy" class="field-input" type="text" placeholder="127.0.0.1:7890">
            </SettingsFieldCard>
            <SettingsFieldCard label="元数据代理" hint="用于 DLsite 社团作品列表、封面等信息抓取；服务器在中国大陆时务必填写，否则社团补全可能少作品。">
              <input v-model="config.metadata.http_proxy" class="field-input" type="text" placeholder="127.0.0.1:7890">
            </SettingsFieldCard>
          </div>
          <SettingsToggleRow v-model="config.asmr_sync.auto_upload_enabled" title="自动上传" subtitle="增强下载完成后按默认模式直传库存。" />
          <div class="mini-grid two" v-if="config.asmr_sync.auto_upload_enabled">
            <SettingsFieldCard label="上传模式">
              <AppDropdown
                v-model="config.asmr_sync.auto_upload_mode"
                :options="uploadModeOptions"
                class="settings-field-dd"
              />
            </SettingsFieldCard>
            <SettingsFieldCard label="默认群晖库存 ID">
              <input v-model="config.asmr_sync.auto_upload_library_id" class="field-input" type="text" placeholder="例如 synology-main">
            </SettingsFieldCard>
          </div>
          <SettingsFieldCard v-if="config.asmr_sync.auto_upload_enabled" label="默认目标路径">
            <input v-model="config.asmr_sync.auto_upload_target_path" class="field-input" type="text" placeholder="本地目录或远程目录">
          </SettingsFieldCard>
        </div>
      </div>
    </div>

    <div class="settings-grid two">
      <!-- ASMR 字幕处理 -->
      <div class="settings-card">
        <div class="card-title">ASMR 字幕处理</div>
        <div class="toggle-stack">
          <SettingsToggleRow v-model="config.asmr_sync.lrc_clean_enabled" title="启用 LRC 广告清理" subtitle="下载后自动剔除常见引流信息。" />
          <SettingsToggleRow v-model="config.asmr_sync.simplify_chinese_enabled" title="字幕繁体转简体" subtitle="统一工作台里字幕文本的简体口径。" />
        </div>
        <div v-if="config.asmr_sync.lrc_clean_enabled" class="rule-stack">
          <div v-for="(_pattern, index) in config.asmr_sync.lrc_clean_patterns" :key="`lrc-${index}`" class="rule-row">
            <input v-model="config.asmr_sync.lrc_clean_patterns[index]" class="field-input" type="text" placeholder="正则表达式">
            <button type="button" class="icon-btn danger" @click="config.asmr_sync.lrc_clean_patterns.splice(index, 1)"><Trash2 :size="15" :stroke-width="2.4" /></button>
          </div>
          <button type="button" class="ghost-inline-btn" @click="config.asmr_sync.lrc_clean_patterns.push('')"><Plus :size="14" :stroke-width="2.4" /> 添加清理规则</button>
        </div>
      </div>

      <!-- RJ 字幕抓取 -->
      <div class="settings-card">
        <div class="card-title">RJ 字幕抓取</div>
        <div class="pill-switch-grid">
          <SettingsToggleChip v-for="item in subtitleItems" :key="item.key" v-model="config.rj_subtitle[item.key]" :label="item.label" />
        </div>
        <div class="mini-grid two">
          <SettingsFieldCard label="命名策略">
            <AppDropdown
              v-model="config.rj_subtitle.naming_strategy"
              :options="namingStrategyOptions"
              class="settings-field-dd"
            />
          </SettingsFieldCard>
          <SettingsToggleRow v-model="config.rj_subtitle.use_filter_rules" title="抓取阶段复用过滤规则" subtitle="让字幕工作台预过滤规则直接复用设置页。" />
        </div>
      </div>
    </div>

    <div class="settings-grid two">
      <!-- DLsite 邮件监听 -->
      <div class="settings-card">
        <div class="card-title">
          DLsite 邮件监听
          <span v-if="config.email_watcher.enabled" class="email-watcher-badge is-enabled">已启用</span>
          <span v-else class="email-watcher-badge is-disabled">未启用</span>
        </div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.email_watcher.enabled" title="启用邮件监听" subtitle="IMAP IDLE 长连接实时监听 DLsite 新作通知，自动触发社团索引。" />
          <div class="mini-grid two">
            <SettingsFieldCard label="快速预设">
              <AppDropdown
                v-model="emailImapPreset"
                :options="emailImapPresetOptions"
                placeholder="选择邮件服务"
                class="settings-field-dd"
              />
            </SettingsFieldCard>
            <SettingsFieldCard label="端口">
              <el-input-number v-model="config.email_watcher.imap_port" :min="1" :max="65535" class="field-number" />
            </SettingsFieldCard>
          </div>
          <SettingsFieldCard label="IMAP 地址">
            <input v-model="config.email_watcher.imap_host" class="field-input" type="text" placeholder="例如 imap.gmail.com">
          </SettingsFieldCard>
          <SettingsToggleRow v-model="config.email_watcher.imap_ssl" title="使用 SSL" subtitle="绝大多数 IMAP 服务器需要 SSL（推荐开启）。" />
          <SettingsFieldCard label="邮箱账号">
            <input v-model="config.email_watcher.username" class="field-input" type="text" placeholder="例如 yourname@gmail.com" autocomplete="username">
          </SettingsFieldCard>
          <SettingsFieldCard label="密码 / 授权码">
            <AnimatedPasswordInput v-model="config.email_watcher.password" placeholder="Gmail 填应用专用密码；QQ/163 填 IMAP 授权码" autocomplete="new-password" />
          </SettingsFieldCard>
          <div v-if="emailImapPasswordHint" class="email-watcher-hint">
            <span>{{ emailImapPasswordHint }}</span>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="监听文件夹">
              <input v-model="config.email_watcher.mailbox" class="field-input" type="text" placeholder="INBOX">
            </SettingsFieldCard>
            <SettingsFieldCard label="移入文件夹（可选）">
              <input v-model="config.email_watcher.move_to_folder" class="field-input" type="text" placeholder="留空则不移动">
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="发件人关键词">
              <input v-model="config.email_watcher.sender_filter" class="field-input" type="text" placeholder="dlsite.com">
            </SettingsFieldCard>
            <SettingsFieldCard label="主题关键词">
              <input v-model="config.email_watcher.subject_filter" class="field-input" type="text" placeholder="新着作品">
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsToggleRow v-model="config.email_watcher.mark_as_read" title="处理后标记已读" />
            <SettingsToggleRow v-model="config.email_watcher.auto_index_new_circles" title="新社团自动全量索引" subtitle="首次出现的社团建立索引。" />
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="IDLE 超时（分钟）">
              <el-input-number v-model="config.email_watcher.idle_timeout_minutes" :min="5" :max="28" class="field-number" />
            </SettingsFieldCard>
            <SettingsFieldCard label="降级轮询间隔（秒）">
              <el-input-number v-model="config.email_watcher.fallback_poll_interval_seconds" :min="60" :max="3600" class="field-number" />
            </SettingsFieldCard>
          </div>
          <div class="service-action-row">
            <button type="button" class="email-watcher-action-btn" :disabled="emailWatcherBusy" @click="testEmailWatcherConnection">
              <Wifi :size="14" :stroke-width="2.4" />
              测试连接
            </button>
            <button type="button" class="email-watcher-action-btn" :disabled="emailWatcherBusy || !config.email_watcher.enabled" @click="pollEmailWatcherNow">
              <RefreshCw :size="14" :stroke-width="2.4" :class="{ 'spin-once': emailWatcherBusy }" />
              立即检查邮件
            </button>
          </div>
          <transition name="fade-up">
            <div v-if="emailWatcherMessage" class="email-watcher-msg" :class="emailWatcherMessage.startsWith('✓') ? 'is-success' : emailWatcherMessage.startsWith('✗') ? 'is-error' : 'is-info'">
              {{ emailWatcherMessage }}
            </div>
          </transition>
          <transition name="fade-up">
            <div v-if="emailWatcherStatus" class="service-result-card">
              <div class="service-result-grid">
                <div><span class="service-result-key">运行模式</span><strong>{{ emailWatcherStatus.mode }}</strong></div>
                <div><span class="service-result-key">上次检查</span><strong>{{ emailWatcherStatus.last_check_at || '—' }}</strong></div>
                <div><span class="service-result-key">处理邮件数</span><strong>{{ emailWatcherStatus.total_mails_processed ?? '—' }}</strong></div>
                <div><span class="service-result-key">触发索引数</span><strong>{{ emailWatcherStatus.total_rjcodes_triggered ?? '—' }}</strong></div>
              </div>
              <div v-if="emailWatcherStatus.last_error" class="service-result-line email-watcher-error">错误：{{ emailWatcherStatus.last_error }}</div>
            </div>
          </transition>
        </div>
      </div>

      <!-- 配置说明 -->
      <div class="settings-card">
        <div class="card-title">配置说明</div>
        <div class="field-stack">
          <div class="email-watcher-guide-item">
            <div class="email-watcher-guide-label"><Mail :size="13" :stroke-width="2.5" /> Gmail</div>
            <p>开启两步验证后，在 <strong>Google 账号 → 安全 → 应用专用密码</strong> 中生成专用密码（非 Gmail 登录密码）填入密码栏。IMAP 地址 <code>imap.gmail.com</code>，端口 993。</p>
          </div>
          <div class="email-watcher-guide-item">
            <div class="email-watcher-guide-label"><Mail :size="13" :stroke-width="2.5" /> QQ / 163 邮箱</div>
            <p>邮箱设置 → POP3/IMAP/SMTP → 开启 IMAP 服务后生成<strong>授权码</strong>（非 QQ 密码）。QQ 地址 <code>imap.qq.com</code>，163 地址 <code>imap.163.com</code>，端口均 993。</p>
          </div>
          <div class="email-watcher-guide-item">
            <div class="email-watcher-guide-label"><Zap :size="13" :stroke-width="2.5" /> IDLE vs 降级 Polling</div>
            <p>默认使用 IMAP IDLE 长连接（<strong>近实时推送</strong>）。连续失败 3 次后自动降级为定期轮询，网络恢复后自动回升。IDLE 超时默认 25 分钟（RFC 允许最长 29 分钟）。</p>
          </div>
          <div class="email-watcher-guide-item">
            <div class="email-watcher-guide-label"><BookOpen :size="13" :stroke-width="2.5" /> DLsite 订阅设置</div>
            <p>在 DLsite 个人中心 → お気に入りサークル → 「新着作品メール通知」开启后，有新作品时 DLsite 将发送邮件通知，系统监听到后自动触发社团补全索引。</p>
          </div>
          <div class="email-watcher-guide-item">
            <div class="email-watcher-guide-label"><FolderOpen :size="13" :stroke-width="2.5" /> 监听文件夹 vs 移入文件夹</div>
            <p><strong>监听文件夹</strong>：从哪个文件夹检查新邮件，默认 <code>INBOX</code>。若你用过滤规则把 DLsite 邮件归入子文件夹（如 <code>DLsite</code>），改成对应名称即可。</p>
            <p class="email-watcher-guide-extra"><strong>移入文件夹</strong>：处理完邮件后自动把它搬到该文件夹（需提前在邮箱里创建好），留空则邮件原地不动。配合「标记已读」使用可保持收件箱整洁。</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import { BookOpen, FolderOpen, Mail, Plus, RefreshCw, Trash2, Wifi, Zap } from 'lucide-vue-next'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import SettingsToggleChip from './SettingsToggleChip.vue'
import AppDropdown from '../common/AppDropdown.vue'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import { kikoeruApi, emailWatcherApi } from '../../api'
import insiderLoadingAnimation from '../../assets/anime/Insider-loading.lottie'
import successConfettiAnimation from '../../assets/anime/success confetti.lottie'

const props = defineProps({
  config: { type: Object, required: true }
})

// ---- AppDropdown options ----
const uploadModeOptions = [
  { value: 'local', label: '本地复制' },
  { value: 'synology', label: '群晖上传' }
]
const namingStrategyOptions = [
  { value: 'audio', label: '按音频' },
  { value: 'subtitle', label: '按字幕' }
]
const emailImapPresetOptions = [
  { value: 'gmail', label: 'Gmail' },
  { value: 'qq', label: 'QQ 邮箱' },
  { value: '163', label: '163 邮箱' },
  { value: 'outlook', label: 'Outlook' },
  { value: 'custom', label: '自定义' }
]

// RJ 字幕开关项
const subtitleItems = [
  { key: 'overwrite_existing', label: '覆盖已有字幕' },
  { key: 'scan_one_level_only', label: '只扫一层目录' },
  { key: 'enable_metadata_match', label: '启用元数据匹配' },
  { key: 'show_source_search', label: '显示来源搜索' },
  { key: 'show_written_files', label: '显示落盘文件' },
  { key: 'show_download_progress', label: '显示下载进度' },
  { key: 'show_issues', label: '显示问题项' }
]

// ---- Kikoeru 测试链路 ----
const kikoeruBusy = ref(false)
const kikoeruStatusMessage = ref('')
const kikoeruTestRJCode = ref('')
const kikoeruCheckResult = ref(null)
const kikoeruButtonState = ref('idle')
const kikoeruButtonLottieRef = ref(null)
const kikoeruButtonLottieReady = ref(false)
let kikoeruButtonResetTimer = null

const kikoeruButtonLottieSrc = computed(() => {
  if (kikoeruButtonState.value === 'loading') return insiderLoadingAnimation
  if (kikoeruButtonState.value === 'success') return successConfettiAnimation
  return insiderLoadingAnimation
})

const kikoeruButtonLabel = computed(() => {
  if (kikoeruButtonState.value === 'loading') return '查询中'
  if (kikoeruButtonState.value === 'success') return '已命中'
  return '测试查重'
})

function normalizeRJCode(value = '') {
  const raw = String(value || '').trim().toUpperCase()
  if (!raw) return ''
  const match = raw.match(/RJ\s*(\d{4,})/i) || raw.match(/(\d{4,})/)
  return match ? `RJ${match[1]}` : raw
}

function getKikoeruButtonLottieInstance() {
  return kikoeruButtonLottieRef.value?.getDotLottieInstance?.() || null
}

async function setKikoeruButtonLottieStaticFrame(frame = 0) {
  const instance = getKikoeruButtonLottieInstance()
  if (!instance) return
  await instance.pause()
  await instance.setFrame(frame)
  await instance.freeze()
}

function handleKikoeruButtonLottieReady() {
  kikoeruButtonLottieReady.value = true
  if (kikoeruButtonState.value === 'idle') {
    setKikoeruButtonLottieStaticFrame(0)
  }
}

async function handleKikoeruButtonLottieComplete() {
  await nextTick()
  if (kikoeruButtonState.value === 'success') {
    if (kikoeruButtonResetTimer) clearTimeout(kikoeruButtonResetTimer)
    kikoeruButtonResetTimer = window.setTimeout(() => {
      kikoeruButtonState.value = 'idle'
      kikoeruButtonResetTimer = null
    }, 900)
  }
}

function normalizeKikoeruCheckResult(result = {}, requestedRJCode = '') {
  const primary = result?.primary_result || result?.result || result || {}
  const foundLinkedWorks = Array.isArray(result?.linked_works_found)
    ? result.linked_works_found.filter(Boolean)
    : []
  const mergedFound = Boolean(
    result?.is_found
    || result?.found
    || result?.exists
    || primary?.is_found
    || foundLinkedWorks.length > 0
  )
  return {
    requested_rjcode: String(result?.rjcode || requestedRJCode || '').trim(),
    found: mergedFound,
    matched_rjcode: String(primary?.matched_rjcode || result?.matched_rjcode || primary?.rjcode || '').trim(),
    title: String(primary?.title || result?.title || '').trim(),
    source: String(primary?.source || result?.source || '').trim(),
    message: String(result?.message || '').trim(),
    linked_rjcodes: [],
    linked_works_total: Number(result?.total_checked || 0),
    linked_hits: foundLinkedWorks.map(item => String(item?.rjcode || '').trim()).filter(Boolean)
  }
}

function extractLinkedRJCodes(linkedWorksPayload = {}, requestedRJCode = '') {
  const linkedWorks = linkedWorksPayload?.linked_works && typeof linkedWorksPayload.linked_works === 'object'
    ? linkedWorksPayload.linked_works
    : {}
  const normalizedRequested = String(requestedRJCode || '').trim().toUpperCase()
  return Object.keys(linkedWorks)
    .map(code => String(code || '').trim().toUpperCase())
    .filter(Boolean)
    .sort((a, b) => {
      if (a === normalizedRequested) return -1
      if (b === normalizedRequested) return 1
      return a.localeCompare(b)
    })
}

async function withKikoeruAction(action, successMessage = '') {
  kikoeruBusy.value = true
  kikoeruButtonState.value = 'loading'
  try {
    const result = await action()
    if (successMessage) {
      kikoeruStatusMessage.value = successMessage
      ElMessage.success(successMessage)
    }
    return result
  } catch (error) {
    const detail = error.response?.data?.detail || error.message || '请求失败'
    kikoeruStatusMessage.value = detail
    ElMessage.error(detail)
    throw error
  } finally {
    kikoeruBusy.value = false
    if (kikoeruButtonState.value === 'loading') {
      kikoeruButtonState.value = 'idle'
    }
  }
}

async function runKikoeruConnectionTest() {
  kikoeruCheckResult.value = null
  const result = await withKikoeruAction(() => kikoeruApi.testConnection())
  const message = String(result?.message || result?.detail || 'Kikoeru 连接测试完成')
  kikoeruStatusMessage.value = message
  ElMessage.success(message)
}

async function runKikoeruTokenFetch() {
  kikoeruCheckResult.value = null
  const result = await withKikoeruAction(() => kikoeruApi.getToken())
  const token = String(result?.token || '').trim()
  kikoeruStatusMessage.value = token ? `Token 获取成功：${token.slice(0, 12)}...` : String(result?.message || 'Token 获取成功')
  ElMessage.success('Kikoeru Token 获取成功')
}

async function runKikoeruCacheClear() {
  kikoeruCheckResult.value = null
  const result = await withKikoeruAction(() => kikoeruApi.clearCache())
  const message = String(result?.message || 'Kikoeru 缓存已清除')
  kikoeruStatusMessage.value = message
  ElMessage.success(message)
}

async function runKikoeruDuplicateTest() {
  const rjcode = normalizeRJCode(kikoeruTestRJCode.value)
  if (!rjcode) {
    ElMessage.warning('先填一个 RJ 号')
    return
  }
  kikoeruTestRJCode.value = rjcode
  const [linkedWorksResult, checkResult] = await withKikoeruAction(() => Promise.all([
    kikoeruApi.linkedWorks(rjcode, { includeFullLinkage: true, cueLanguages: 'CHI_HANS,CHI_HANT,ENG,JPN' }),
    kikoeruApi.check(rjcode, true)
  ]))
  const normalizedResult = normalizeKikoeruCheckResult(checkResult, rjcode)
  normalizedResult.linked_rjcodes = extractLinkedRJCodes(linkedWorksResult, rjcode)
  normalizedResult.linked_works_total = normalizedResult.linked_rjcodes.length || normalizedResult.linked_works_total
  kikoeruCheckResult.value = normalizedResult
  if (normalizedResult.found) {
    kikoeruButtonState.value = 'success'
  }
  kikoeruStatusMessage.value = kikoeruCheckResult.value.found
    ? `查重完成：${kikoeruCheckResult.value.matched_rjcode || rjcode} 已命中`
    : `查重完成：${rjcode} 未命中`
}

// ---- 邮件监听 ----
const emailWatcherBusy = ref(false)
const emailWatcherMessage = ref('')
const emailWatcherStatus = ref(null)
const emailImapPreset = ref('custom')
const emailImapPasswordHint = computed(() => {
  if (emailImapPreset.value === 'gmail') return '⚠ Gmail 需填「应用专用密码」（非登录密码）：Google账号 → 安全 → 应用专用密码 → 生成'
  if (emailImapPreset.value === 'qq') return '⚠ QQ邮箱需填「授权码」（非QQ密码）：邮箱设置 → 账户 → IMAP/SMTP服务 → 生成授权码'
  if (emailImapPreset.value === '163') return '⚠ 163邮箱需填「客户端授权密码」：邮箱设置 → POP3/SMTP/IMAP → 开启IMAP → 生成授权密码'
  if (emailImapPreset.value === 'outlook') return '⚠ Outlook 直接填登录密码即可（如启用二步验证则需应用密码）'
  return ''
})
watch(emailImapPreset, (val) => {
  if (!props.config) return
  if (val === 'gmail') { props.config.email_watcher.imap_host = 'imap.gmail.com'; props.config.email_watcher.imap_port = 993; props.config.email_watcher.imap_ssl = true }
  else if (val === 'qq') { props.config.email_watcher.imap_host = 'imap.qq.com'; props.config.email_watcher.imap_port = 993; props.config.email_watcher.imap_ssl = true }
  else if (val === '163') { props.config.email_watcher.imap_host = 'imap.163.com'; props.config.email_watcher.imap_port = 993; props.config.email_watcher.imap_ssl = true }
  else if (val === 'outlook') { props.config.email_watcher.imap_host = 'outlook.office365.com'; props.config.email_watcher.imap_port = 993; props.config.email_watcher.imap_ssl = true }
})

async function testEmailWatcherConnection() {
  if (emailWatcherBusy.value) return
  emailWatcherBusy.value = true
  emailWatcherMessage.value = '正在测试连接...'
  emailWatcherStatus.value = null
  try {
    const result = await emailWatcherApi.test({
      imap_host: props.config.email_watcher.imap_host,
      imap_port: props.config.email_watcher.imap_port,
      imap_ssl: props.config.email_watcher.imap_ssl,
      username: props.config.email_watcher.username,
      password: props.config.email_watcher.password,
      mailbox: props.config.email_watcher.mailbox
    })
    emailWatcherMessage.value = result.success ? `✓ ${result.message || '连接成功'}` : `✗ ${result.message || result.detail || result.error || '连接失败'}`
  } catch (e) {
    emailWatcherMessage.value = `✗ ${e.response?.data?.detail || e.message || '连接失败'}`
  } finally {
    emailWatcherBusy.value = false
  }
}

async function pollEmailWatcherNow() {
  if (emailWatcherBusy.value) return
  emailWatcherBusy.value = true
  emailWatcherMessage.value = '正在检查邮件...'
  try {
    const result = await emailWatcherApi.pollNow()
    emailWatcherMessage.value = result.success
      ? `✓ ${result.message || '检查完成'}`
      : `✗ ${result.message || result.detail || '检查失败'}`
    const status = await emailWatcherApi.status()
    emailWatcherStatus.value = status
  } catch (e) {
    emailWatcherMessage.value = `✗ ${e.response?.data?.detail || e.message || '检查失败'}`
  } finally {
    emailWatcherBusy.value = false
  }
}

onMounted(() => {
  const bind = () => {
    const instance = getKikoeruButtonLottieInstance()
    if (!instance) return false
    instance.addEventListener('ready', handleKikoeruButtonLottieReady)
    instance.addEventListener('load', handleKikoeruButtonLottieReady)
    instance.addEventListener('complete', handleKikoeruButtonLottieComplete)
    return true
  }

  if (!bind()) {
    window.setTimeout(bind, 60)
  }
})

onBeforeUnmount(() => {
  if (kikoeruButtonResetTimer) {
    clearTimeout(kikoeruButtonResetTimer)
    kikoeruButtonResetTimer = null
  }
  const instance = getKikoeruButtonLottieInstance()
  if (!instance) return
  instance.removeEventListener('ready', handleKikoeruButtonLottieReady)
  instance.removeEventListener('load', handleKikoeruButtonLottieReady)
  instance.removeEventListener('complete', handleKikoeruButtonLottieComplete)
})
</script>

<style scoped>
.services-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-grid,
.settings-card,
.mini-grid,
.pill-switch-grid,
.field-stack,
.toggle-stack,
.rule-stack {
  overflow: visible;
}

.settings-grid {
  display: grid;
  gap: 24px;
  align-items: start;
}

.settings-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.mini-grid { display: grid; gap: 10px; }
.mini-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.pill-switch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.field-stack,
.toggle-stack,
.rule-stack {
  display: grid;
  gap: 12px;
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
  color: #1d1d1f;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

/* SettingsFieldCard slot 内的统一 input 视觉 */
.field-input {
  width: 100%;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 10px;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 13.5px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-input:hover { border-color: rgba(148, 163, 184, 0.75); }

.field-input:focus {
  border-color: rgba(79, 70, 229, 0.5);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

.field-input::placeholder { color: #94a3b8; }

.field-number :deep(.el-input__wrapper) {
  min-height: 38px;
  border-radius: 10px;
  background: #ffffff;
  box-shadow: none;
  border: 1px solid rgba(226, 232, 240, 0.85) !important;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.field-number :deep(.el-input__wrapper:hover) {
  border-color: rgba(148, 163, 184, 0.75) !important;
  box-shadow: none;
}

.field-number :deep(.el-input__wrapper.is-focus) {
  border-color: rgba(79, 70, 229, 0.5) !important;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1) !important;
}

.settings-field-dd { display: block; width: 100%; }
.settings-field-dd :deep(.app-dd-root) { display: block; width: 100%; }

.settings-field-dd :deep(.app-dd-trigger) {
  width: 100%;
  min-height: 38px;
  height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.85);
  font-size: 13.5px;
  justify-content: space-between;
}

.settings-field-dd :deep(.app-dd-trigger:hover) { border-color: rgba(148, 163, 184, 0.75); }
.settings-field-dd :deep(.app-dd-trigger.is-open) {
  border-color: rgba(79, 70, 229, 0.55);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
}

/* 规则行 */
.rule-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  transition: border-color 0.18s ease, background 0.18s ease;
}

.rule-row:hover {
  border-color: rgba(148, 163, 184, 0.75);
  background: rgba(248, 250, 252, 0.5);
}

/* ghost / icon / 邮件监听按钮 */
.ghost-inline-btn,
.icon-btn,
.email-watcher-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #475569;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.ghost-inline-btn { padding: 0 14px; }
.email-watcher-action-btn { padding: 0 14px; }

.ghost-inline-btn:not(:disabled):hover,
.icon-btn:not(:disabled):hover,
.email-watcher-action-btn:not(:disabled):hover {
  transform: translateY(-1px);
  border-color: rgba(148, 163, 184, 0.75);
  background: rgba(248, 250, 252, 0.85);
  color: #1d1d1f;
}

.ghost-inline-btn:disabled,
.icon-btn:disabled,
.email-watcher-action-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.icon-btn { width: 36px; padding: 0; }
.icon-btn.danger { color: #e11d48; border-color: rgba(244, 63, 94, 0.4); }
.icon-btn.danger:hover {
  background: linear-gradient(135deg, rgba(254, 226, 226, 0.6) 0%, #ffffff 100%);
  border-color: rgba(244, 63, 94, 0.7);
  color: #be123c;
}

/* 服务行布局 */
.service-action-row,
.service-inline-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.service-inline-row .field-input { flex: 1 1 220px; }

/* Lottie 触发按钮 */
.service-lottie-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  padding: 0 14px 0 8px;
  height: 38px;
  border-radius: 10px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: #ffffff;
  color: #1d1d1f;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.service-lottie-trigger__animation {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.service-lottie-trigger__player {
  width: 24px;
  height: 24px;
  pointer-events: none;
}

.service-lottie-trigger__label {
  color: #1d1d1f;
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
  white-space: nowrap;
}

.service-lottie-trigger:not(:disabled):hover {
  transform: translateY(-2px);
  border-color: rgba(148, 163, 184, 0.85);
  box-shadow: 0 10px 22px -8px rgba(15, 23, 42, 0.18), 0 2px 4px rgba(15, 23, 42, 0.04);
}

.service-lottie-trigger:not(:disabled):active { transform: translateY(0) scale(0.97); }

.service-lottie-trigger.is-busy,
.service-lottie-trigger:disabled { cursor: not-allowed; opacity: 0.55; }

.service-lottie-trigger.is-loading .service-lottie-trigger__player {
  filter: grayscale(1) brightness(0.72);
}

/* 结果卡 */
.service-result-card {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid rgba(191, 219, 254, 0.55);
  background: linear-gradient(180deg, #f5f8ff 0%, #eff6ff 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(37, 99, 235, 0.06);
}

.service-result-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 8px;
}

.service-result-key {
  display: block;
  margin-bottom: 3px;
  color: rgba(29, 29, 31, 0.55);
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
}

.service-result-line { color: #1d1d1f; font-size: 13px; line-height: 1.6; letter-spacing: -0.05px; }

/* 邮件监听 badge */
.email-watcher-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.email-watcher-badge.is-enabled {
  background: linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%);
  color: #047857;
  border: 1px solid rgba(110, 231, 183, 0.55);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(16, 185, 129, 0.1);
}

.email-watcher-badge.is-disabled {
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
  color: #64748b;
  border: 1px solid rgba(226, 232, 240, 0.85);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(15, 23, 42, 0.04);
}

.email-watcher-msg {
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1.5;
  letter-spacing: -0.05px;
}

.email-watcher-msg.is-success {
  background: linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%);
  border: 1px solid rgba(110, 231, 183, 0.55);
  color: #047857;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(16, 185, 129, 0.1);
}

.email-watcher-msg.is-error {
  background: linear-gradient(180deg, #fff1f2 0%, #fee2e2 100%);
  border: 1px solid rgba(252, 165, 165, 0.55);
  color: #b91c1c;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(239, 68, 68, 0.1);
}

.email-watcher-msg.is-info {
  background: linear-gradient(180deg, #f5f8ff 0%, #eff6ff 100%);
  border: 1px solid rgba(191, 219, 254, 0.55);
  color: #1d4ed8;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(37, 99, 235, 0.08);
}

.email-watcher-error { margin-top: 8px; color: var(--el-color-danger); }

.email-watcher-guide-item {
  padding: 12px 14px;
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid rgba(226, 232, 240, 0.85);
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.email-watcher-guide-item:hover {
  transform: translateY(-1px);
  border-color: rgba(148, 163, 184, 0.75);
  background: linear-gradient(135deg, rgba(248, 250, 252, 0.6) 0%, #ffffff 100%);
  box-shadow: 0 4px 12px -4px rgba(15, 23, 42, 0.08);
}

.email-watcher-guide-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #1d1d1f;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: -0.05px;
  margin-bottom: 6px;
}

.email-watcher-guide-item p { font-size: 12.5px; line-height: 1.65; color: rgba(29, 29, 31, 0.55); margin: 0; }
.email-watcher-guide-extra { margin-top: 6px !important; }

.email-watcher-guide-item p code {
  background: linear-gradient(180deg, #f5f8ff 0%, #eff6ff 100%);
  border: 1px solid rgba(191, 219, 254, 0.55);
  border-radius: 6px;
  padding: 1px 5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: #1d4ed8;
}

.email-watcher-hint {
  padding: 8px 12px;
  border-radius: 10px;
  background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
  border: 1px solid rgba(251, 191, 36, 0.55);
  color: #b45309;
  font-size: 12px;
  line-height: 1.55;
  letter-spacing: -0.05px;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(245, 158, 11, 0.1);
}

/* 过渡 */
.fade-up-enter-active,
.fade-up-leave-active { transition: all 0.24s ease; }
.fade-up-enter-from,
.fade-up-leave-to { opacity: 0; transform: translateY(5px); }

@keyframes spin-once { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.spin-once { animation: spin-once 0.7s linear infinite; }

@media (max-width: 1200px) {
  .settings-grid.two,
  .mini-grid.two,
  .pill-switch-grid { grid-template-columns: 1fr; }
  .service-result-grid { grid-template-columns: 1fr; }
}
</style>
