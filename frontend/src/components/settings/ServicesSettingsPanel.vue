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
              <SettingsNumberStepper v-model="config.kikoeru_server.timeout" :min="1" :max="60" />
            </SettingsFieldCard>
            <SettingsFieldCard label="缓存秒数">
              <SettingsNumberStepper v-model="config.kikoeru_server.cache_ttl" :min="0" :max="3600" />
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
              <StatefulButton
                type="button"
                class="ghost-inline-btn service-duplicate-test-btn"
                unstyled
                :show-default-icons="false"
                :success-hold="900"
                :disabled="(kikoeruBusy && !kikoeruDuplicateTesting) || !kikoeruTestRJCode.trim()"
                @click="runKikoeruDuplicateTest"
              >
                <template #prefix="{ state }">
                  <span class="service-duplicate-test-icon" :class="`is-${state}`" aria-hidden="true">
                    <Loader2 v-if="state === 'loading' || kikoeruDuplicateTesting" :size="14" :stroke-width="2.5" class="animate-spin" />
                    <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.5" />
                    <AlertCircle v-else-if="state === 'error'" :size="14" :stroke-width="2.5" />
                    <SearchCheck v-else :size="14" :stroke-width="2.5" />
                  </span>
                </template>
                <span>
                  {{ kikoeruDuplicateTesting ? '查询中' : '测试查重' }}
                </span>
              </StatefulButton>
            </div>
          </SettingsFieldCard>
          <div v-if="kikoeruStatusMessage || kikoeruCheckResult" class="service-result-card">
            <template v-if="kikoeruCheckResult">
              <div class="kikoeru-result-layout">
                <div class="kikoeru-result-main">
                  <figure v-if="kikoeruCheckResult.cover_url" class="kikoeru-result-cover">
                    <img
                      :key="kikoeruCheckResult.cover_url"
                      :src="kikoeruCheckResult.cover_url"
                      :alt="kikoeruCheckResult.title || kikoeruCheckResult.requested_rjcode || 'DLsite 主图'"
                      :data-rjcode="kikoeruCheckResult.cover_rjcode"
                      loading="lazy"
                      @error="handleKikoeruCoverError"
                    >
                  </figure>
                  <div class="kikoeru-result-copy">
                    <div v-if="kikoeruStatusMessage" class="service-result-line kikoeru-owned-line">{{ kikoeruStatusMessage }}</div>
                    <div v-if="kikoeruCheckResult.linked_labels?.length" class="kikoeru-rj-chip-row">
                      <span class="service-result-key kikoeru-chip-label">本次检查</span>
                      <span
                        v-for="label in kikoeruCheckResult.linked_labels"
                        :key="label"
                        class="kikoeru-rj-chip"
                        :class="kikoeruLinkedLabelClass(label)"
                      >
                        {{ label }}
                      </span>
                    </div>
                    <div v-if="kikoeruCheckResult.title" class="service-result-line">标题：{{ kikoeruCheckResult.title }}</div>
                    <div v-if="kikoeruCheckResult.message" class="service-result-line">{{ kikoeruCheckResult.message }}</div>
                  </div>
                </div>
                <div class="kikoeru-result-meta">
                  <div><span class="service-result-key">请求 RJ</span><strong>{{ kikoeruCheckResult.requested_rjcode || kikoeruTestRJCode }}</strong></div>
                  <div><span class="service-result-key">命中结果</span><strong>{{ kikoeruCheckResult.hit_summary }}</strong></div>
                  <div><span class="service-result-key">服务器已有</span><strong>{{ kikoeruCheckResult.matched_label || '-' }}</strong></div>
                  <div class="kikoeru-result-meta-wide"><span class="service-result-key">检查范围</span><strong>{{ kikoeruCheckResult.scope_label }}</strong></div>
                </div>
              </div>
            </template>
            <div v-else-if="kikoeruStatusMessage" class="service-result-line">{{ kikoeruStatusMessage }}</div>
          </div>
        </div>
      </div>

      <!-- ASMR 同步下载 -->
      <div class="settings-card">
        <div class="card-title">ASMR 同步下载</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="config.asmr_sync.enabled" title="启用 ASMR 同步" subtitle="允许从 asmr.one 拉音频与字幕。" />
          <div class="mini-grid two">
            <SettingsFieldCard label="全局文件并发下载数" hint="所有 RJ 合计最多同时下载这些文件，优先填满较早进入队列的 RJ。">
              <SettingsNumberStepper v-model="config.asmr_sync.max_concurrent_downloads" :min="1" :max="10" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最大重试次数">
              <SettingsNumberStepper v-model="config.asmr_sync.max_retry_count" :min="1" :max="100" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="增强会话并发" hint="任务启动数至少覆盖全局文件槽位，避免空槽。">
              <SettingsNumberStepper v-model="config.asmr_sync.enhanced_max_parallel_sessions" :min="1" :max="10" />
            </SettingsFieldCard>
            <SettingsFieldCard label="单会话处理并发" hint="文件下载仍受全局文件并发上限约束。">
              <SettingsNumberStepper v-model="config.asmr_sync.enhanced_per_session_concurrency" :min="1" :max="10" />
            </SettingsFieldCard>
          </div>
          <SettingsFieldCard label="重试 Cron">
            <input v-model="config.asmr_sync.retry_cron" class="field-input" type="text" placeholder="0 */1 * * *">
          </SettingsFieldCard>
          <div class="mini-grid two">
            <SettingsFieldCard label="HTTP 代理" hint="用于 asmr.one 音频下载。">
              <input v-model="config.asmr_sync.http_proxy" class="field-input" type="text" placeholder="127.0.0.1:7890">
            </SettingsFieldCard>
            <SettingsFieldCard label="元数据代理" hint="用于 DLsite 元数据、社团作品列表、封面抓取，以及 Kikoeru 查重前的 DLsite 关联链查询。">
              <div class="service-inline-row metadata-proxy-row">
                <input v-model="config.metadata.http_proxy" class="field-input" type="text" placeholder="127.0.0.1:7890">
                <StatefulButton
                  type="button"
                  class="ghost-inline-btn dlsite-test-btn"
                  unstyled
                  :show-default-icons="false"
                  :success-hold="900"
                  :disabled="dlsiteBusy"
                  @click="runDlsiteConnectionTest"
                >
                  <template #prefix="{ state }">
                    <span class="service-duplicate-test-icon" :class="`is-${state}`" aria-hidden="true">
                      <Loader2 v-if="state === 'loading' || dlsiteBusy" :size="12" :stroke-width="2.4" class="animate-spin" />
                      <CheckCircle2 v-else-if="state === 'success'" :size="12" :stroke-width="2.4" />
                      <AlertCircle v-else-if="state === 'error'" :size="12" :stroke-width="2.4" />
                      <Wifi v-else :size="12" :stroke-width="2.4" />
                    </span>
                  </template>
                  <span>{{ dlsiteBusy ? '测试中' : '测试 DL 连接' }}</span>
                </StatefulButton>
              </div>
            </SettingsFieldCard>
          </div>
          <transition name="fade-up">
            <div v-if="dlsiteMessage || dlsiteResult" class="service-result-card">
              <div v-if="dlsiteMessage" class="service-result-line">{{ dlsiteMessage }}</div>
              <div v-if="dlsiteResult" class="service-result-grid">
                <div><span class="service-result-key">代理</span><strong>{{ dlsiteResult.proxy_enabled ? (dlsiteResult.proxy_url || '已启用') : '直连' }}</strong></div>
                <div><span class="service-result-key">HTTP</span><strong>{{ dlsitePrimaryCheck?.http_status || '-' }}</strong></div>
                <div><span class="service-result-key">延迟</span><strong>{{ dlsitePrimaryCheck?.latency_ms ?? '-' }} ms</strong></div>
                <div><span class="service-result-key">测试 RJ</span><strong>{{ dlsitePrimaryCheck?.workno || '-' }}</strong></div>
              </div>
              <div v-if="dlsitePrimaryCheck?.title" class="service-result-line">标题：{{ dlsitePrimaryCheck.title }}</div>
            </div>
          </transition>
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
      <div class="settings-card">
        <div class="card-title">社团补全外部搜索</div>
        <div class="field-stack">
          <SettingsToggleRow v-model="circleExternalSearch.anime_share_enabled" title="启用 AnimeShare 探测" subtitle="作品页异步探测精确 RJ 命中的帖子，仅命中时显示跳转标签。" />
          <SettingsToggleRow v-model="circleExternalSearch.south_plus_enabled" title="启用南+探测" subtitle="使用登录态精确搜索 RJ；请求严格串行且至少间隔 10 秒。" />
          <SettingsFieldCard label="南+ Cookie" hint="从已登录的南+浏览器复制完整 Cookie。保存后会脱敏，只有后端探测请求使用。">
            <AnimatedPasswordInput
              v-model="circleExternalSearch.south_plus_cookie"
              :reveal-value="southPlusRevealedCookie"
              placeholder="例如：bbs_lastvisit=...; ..."
              autocomplete="off"
              @visibility-change="handleSouthPlusCookieVisibility"
            />
          </SettingsFieldCard>
          <SettingsFieldCard label="南+ HTTP 代理" hint="只作用于南+搜索请求；留空则直连。支持 http://127.0.0.1:7890。">
            <input v-model="circleExternalSearch.south_plus_proxy" class="field-input" type="text" placeholder="http://127.0.0.1:7890">
          </SettingsFieldCard>
          <div class="service-action-row">
            <StatefulButton
              type="button"
              class="ghost-inline-btn"
              unstyled
              :show-default-icons="false"
              :disabled="southPlusTestBusy"
              @click="testSouthPlusConnection"
            >
              <template #prefix="{ state }">
                <Loader2 v-if="state === 'loading' || southPlusTestBusy" :size="14" :stroke-width="2.4" class="animate-spin" />
                <CheckCircle2 v-else-if="state === 'success'" :size="14" :stroke-width="2.4" />
                <AlertCircle v-else-if="state === 'error'" :size="14" :stroke-width="2.4" />
                <Wifi v-else :size="14" :stroke-width="2.4" />
              </template>
              {{ southPlusTestBusy ? '测试中' : '测试南+连接' }}
            </StatefulButton>
          </div>
          <div v-if="southPlusTestMessage" class="service-result-card">
            <div class="service-result-line">{{ southPlusTestMessage }}</div>
          </div>
        </div>
      </div>

      <div class="settings-card">
        <div class="card-title">搜索标签规则</div>
        <div class="field-stack">
          <div class="email-watcher-guide-item">
            <div class="email-watcher-guide-label"><SearchCheck :size="13" :stroke-width="2.5" /> 不干扰补全统计</div>
            <p>AnimeShare 与南+只提供外部搜索跳转，不会进入缺失数量、下载来源、库存收录或任务中心统计。</p>
          </div>
          <div class="email-watcher-guide-item">
            <div class="email-watcher-guide-label"><Languages :size="13" :stroke-width="2.5" /> 关联语言聚合</div>
            <p>同一作品的原作、简中、繁中会按现有关联链汇总。单个结果直接打开，多个帖子或语言版本会在社团页内选择。</p>
          </div>
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
      <!-- 社团特典补全 -->
      <div class="settings-card bonus-probe-card">
        <div class="card-title">社团特典补全</div>
        <div class="field-stack">
          <div class="bonus-probe-summary">
            <span>普通 {{ bonusProbe.normal_concurrency }} 并发</span>
            <span>深度 {{ bonusProbe.deep_concurrency }} 并发</span>
            <span>新作 {{ bonusProbe.new_release_concurrency }} 并发</span>
            <span>上限 {{ bonusProbe.max_concurrency }}</span>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="同时运行任务" hint="同一时间允许几个特典探测任务进入执行；过高会叠加 DLsite 请求压力。">
              <SettingsNumberStepper v-model="bonusProbe.max_active_jobs" :min="1" :max="6" />
            </SettingsFieldCard>
            <SettingsFieldCard label="最大并发上限" hint="普通、深度、新作并发都会被这个上限截断。">
              <SettingsNumberStepper v-model="bonusProbe.max_concurrency" :min="1" :max="3" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="普通补全批次" hint="社团页点“特典补全”时，每批查询的 RJ 数量。">
              <SettingsNumberStepper v-model="bonusProbe.normal_batch_size" :min="1" :max="bonusProbe.max_batch_size || 1000" />
            </SettingsFieldCard>
            <SettingsFieldCard label="普通补全并发">
              <SettingsNumberStepper v-model="bonusProbe.normal_concurrency" :min="1" :max="bonusProbe.max_concurrency || 20" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="深度补全批次" hint="深度模式会查更大的候选范围，批次和并发建议比普通模式更谨慎。">
              <SettingsNumberStepper v-model="bonusProbe.deep_batch_size" :min="1" :max="bonusProbe.max_batch_size || 1000" />
            </SettingsFieldCard>
            <SettingsFieldCard label="深度补全并发">
              <SettingsNumberStepper v-model="bonusProbe.deep_concurrency" :min="1" :max="bonusProbe.max_concurrency || 20" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="新作探测批次" hint="邮件监听触发新作特典探测时使用。">
              <SettingsNumberStepper v-model="bonusProbe.new_release_batch_size" :min="1" :max="bonusProbe.max_batch_size || 1000" />
            </SettingsFieldCard>
            <SettingsFieldCard label="新作探测并发">
              <SettingsNumberStepper v-model="bonusProbe.new_release_concurrency" :min="1" :max="bonusProbe.max_concurrency || 20" />
            </SettingsFieldCard>
          </div>
          <div class="mini-grid two">
            <SettingsFieldCard label="最大批次上限" hint="保存时后端会把各模式批次限制在这个值以内。">
              <SettingsNumberStepper v-model="bonusProbe.max_batch_size" :min="1" :max="500" />
            </SettingsFieldCard>
            <SettingsFieldCard label="缓存查询批次" hint="从 Redis / PostgreSQL 批量读取特典探测缓存的窗口。">
              <SettingsNumberStepper v-model="bonusProbe.cache_lookup_batch_size" :min="100" :max="5000" :step="50" />
            </SettingsFieldCard>
          </div>
          <SettingsFieldCard label="缓存写回批次" hint="特典探测缓存脏数据批量回写 PostgreSQL 的窗口。">
            <SettingsNumberStepper v-model="bonusProbe.cache_write_batch_size" :min="50" :max="5000" :step="50" />
          </SettingsFieldCard>
        </div>
      </div>

      <div class="settings-card bonus-probe-note-card">
        <div class="card-title">特典探测限流说明</div>
        <div class="field-stack">
          <div class="bonus-probe-note-item">
            <div class="bonus-probe-note-label"><Zap :size="13" :stroke-width="2.5" /> 并发不是固定写死</div>
            <p>任务启动时后端会读取这里的配置：普通补全走普通并发，新作邮件触发走新作并发，深度补全走深度并发。</p>
          </div>
          <div class="bonus-probe-note-item">
            <div class="bonus-probe-note-label"><SearchCheck :size="13" :stroke-width="2.5" /> 上限会统一截断</div>
            <p>如果某个模式填 10，但最大并发上限是 6，实际执行仍是 6。修改后需保存配置，新启动的任务才会使用新值。</p>
          </div>
          <div class="bonus-probe-note-item">
            <div class="bonus-probe-note-label"><AlertCircle :size="13" :stroke-width="2.5" /> DLsite 请求压力</div>
            <p>并发过高可能触发远端限流或短时间失败。默认 6 用来恢复原设计吞吐；网络不稳时建议先降到 2-4。</p>
          </div>
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
              <SettingsNumberStepper v-model="config.email_watcher.imap_port" :min="1" :max="65535" />
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
              <SettingsNumberStepper v-model="config.email_watcher.idle_timeout_minutes" :min="5" :max="28" />
            </SettingsFieldCard>
            <SettingsFieldCard label="降级轮询间隔（秒）">
              <SettingsNumberStepper v-model="config.email_watcher.fallback_poll_interval_seconds" :min="60" :max="3600" />
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
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { AlertCircle, BookOpen, CheckCircle2, FolderOpen, Languages, Loader2, Mail, Plus, RefreshCw, SearchCheck, Trash2, Wifi, Zap } from 'lucide-vue-next'
import SettingsFieldCard from './SettingsFieldCard.vue'
import SettingsNumberStepper from './SettingsNumberStepper.vue'
import SettingsToggleRow from './SettingsToggleRow.vue'
import SettingsToggleChip from './SettingsToggleChip.vue'
import AppDropdown from '../common/AppDropdown.vue'
import AnimatedPasswordInput from '../common/AnimatedPasswordInput.vue'
import StatefulButton from '../ui/stateful-button.vue'
import { circleCompletionApi, configApi, kikoeruApi, emailWatcherApi } from '../../api'

const props = defineProps({
  config: { type: Object, required: true }
})

const defaultCircleExternalSearchConfig = {
  anime_share_enabled: true,
  south_plus_enabled: true,
  south_plus_cookie: '',
  south_plus_proxy: ''
}

const circleExternalSearch = computed(() => {
  if (!props.config.circle_external_search || typeof props.config.circle_external_search !== 'object') {
    props.config.circle_external_search = { ...defaultCircleExternalSearchConfig }
  }
  for (const [key, value] of Object.entries(defaultCircleExternalSearchConfig)) {
    if (props.config.circle_external_search[key] == null) props.config.circle_external_search[key] = value
  }
  return props.config.circle_external_search
})

const southPlusTestBusy = ref(false)
const southPlusTestMessage = ref('')
const southPlusRevealedCookie = ref('')
const southPlusCookieRevealLoading = ref(false)

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

const defaultBonusProbeConfig = {
  max_active_jobs: 1,
  normal_batch_size: 100,
  normal_concurrency: 3,
  deep_batch_size: 200,
  deep_concurrency: 3,
  new_release_batch_size: 100,
  new_release_concurrency: 2,
  max_batch_size: 500,
  max_concurrency: 3,
  cache_lookup_batch_size: 500,
  cache_write_batch_size: 100
}

const bonusProbe = computed(() => {
  if (!props.config.bonus_probe || typeof props.config.bonus_probe !== 'object') {
    props.config.bonus_probe = { ...defaultBonusProbeConfig }
  }
  for (const [key, value] of Object.entries(defaultBonusProbeConfig)) {
    if (props.config.bonus_probe[key] == null) props.config.bonus_probe[key] = value
  }
  return props.config.bonus_probe
})

// ---- Kikoeru 测试链路 ----
const kikoeruBusy = ref(false)
const kikoeruStatusMessage = ref('')
const kikoeruTestRJCode = ref('')
const kikoeruCheckResult = ref(null)
const kikoeruDuplicateTesting = ref(false)
const dlsiteBusy = ref(false)
const dlsiteMessage = ref('')
const dlsiteResult = ref(null)
const dlsitePrimaryCheck = computed(() => {
  const checks = Array.isArray(dlsiteResult.value?.checks) ? dlsiteResult.value.checks : []
  return checks[0] || null
})

function normalizeRJCode(value = '') {
  const raw = String(value || '').trim().toUpperCase()
  if (!raw) return ''
  const match = raw.match(/RJ\s*(\d{4,})/i) || raw.match(/(\d{4,})/)
  return match ? `RJ${match[1]}` : raw
}

function normalizeLinkedWorkLang(value = '') {
  const lang = String(value || '').trim().toUpperCase()
  const map = {
    CHI_HANS: '简中',
    CHI_SIMP: '简中',
    CHN: '简中',
    CHI_HANT: '繁中',
    CHI_TRAD: '繁中',
    TWN: '繁中',
    ENG: '英文',
    JPN: ''
  }
  return map[lang] ?? ''
}

function formatLinkedWorkLabel(rjcode = '', work = {}) {
  const code = normalizeRJCode(rjcode)
  if (!code) return ''
  const type = String(work?.work_type || '').trim().toLowerCase()
  const lang = normalizeLinkedWorkLang(work?.lang)
  if ((type === 'translation' || type === 'child_translation') && lang) return `${code}(${lang})`
  return code
}

function linkedWorkVariantFromLabel(label = '') {
  const text = String(label || '').trim()
  const match = text.match(/\(([^)]+)\)$/)
  if (!match) return { short: '原作', summary: '有原作' }
  return { short: match[1], summary: `有翻译作(${match[1]})` }
}

function kikoeruLinkedLabelClass(label = '') {
  const text = String(label || '')
  if (text.includes('简中')) return 'is-zh-hans'
  if (text.includes('繁中')) return 'is-zh-hant'
  if (text.includes('英文')) return 'is-english'
  return 'is-original'
}

function normalizeKikoeruTags(tags = []) {
  if (!Array.isArray(tags)) return []
  return tags.map(tag => String(tag || '').trim()).filter(Boolean)
}

function detectKikoeruLanguage(payload = {}) {
  const haystack = [
    payload.title,
    payload.circle_name,
    ...normalizeKikoeruTags(payload.tags)
  ].join(' ').toUpperCase()
  if (/(CHI_HANS|CHI_SIMP|ZH_CN|ZH-HANS|简体|簡体|简中|简体中文|簡体中文)/i.test(haystack)) return '简中'
  if (/(CHI_HANT|CHI_TRAD|ZH_TW|ZH-HANT|繁体|繁體|繁中|繁体中文|繁體中文)/i.test(haystack)) return '繁中'
  if (/(ENG|ENGLISH|英文)/i.test(haystack)) return '英文'
  if (/(JPN|JAP|JAPANESE|日本語|日文|原作|原版)/i.test(haystack)) return '日文'
  return ''
}

function kikoeruVariantLabel(payload = {}) {
  const lang = detectKikoeruLanguage(payload)
  if (!lang || lang === '日文') return '有原作'
  return `有翻译作(${lang})`
}

function kikoeruVariantShortLabel(variantLabel = '') {
  const label = String(variantLabel || '').trim()
  if (label === '有原作') return '原作'
  const match = label.match(/^有翻译作\((.+)\)$/)
  return match ? match[1] : label
}

function formatKikoeruOwnedLabel(hitRows = []) {
  const first = hitRows.find(item => item?.rjcode)
  if (!first) return ''
  return `${first.rjcode}(${kikoeruVariantShortLabel(first.variant_label)})`
}

function buildDlsiteCoverUrl(rjcode = '', variant = 'main') {
  const normalized = normalizeRJCode(rjcode)
  const match = normalized.match(/^RJ(\d{6}|\d{8})$/)
  if (!match) return ''
  const folderUpper = (Math.floor(Number(match[1]) / 1000) + 1) * 1000
  const folder = match[1].length === 8
    ? `RJ${String(folderUpper).padStart(8, '0')}`
    : `RJ${String(folderUpper).padStart(6, '0')}`
  const suffix = variant === 'sam' ? '_img_sam.jpg' : '_img_main.jpg'
  return `https://img.dlsite.jp/modpub/images2/work/doujin/${folder}/${normalized}${suffix}`
}

function pickKikoeruCoverRJCode(result = {}, requestedRJCode = '') {
  return normalizeRJCode(
    result?.requested_rjcode
    || requestedRJCode
    || result?.matched_rjcode
    || result?.linked_rjcodes?.[0]
    || ''
  )
}

function handleKikoeruCoverError(event) {
  const img = event?.target
  if (!img) return
  if (!img.dataset.fallbackTried) {
    img.dataset.fallbackTried = '1'
    const rjcode = img.dataset.rjcode || kikoeruCheckResult.value?.cover_rjcode || ''
    const fallback = buildDlsiteCoverUrl(rjcode, 'sam')
    if (fallback && fallback !== img.src) {
      img.src = fallback
      return
    }
  }
  img.closest('.kikoeru-result-cover')?.classList.add('is-hidden')
}

function applyLinkedWorkDisplayLabels(result = {}, linkedWorksForDisplay = []) {
  if (!result?.found) return result
  const matchedRJCode = normalizeRJCode(result.matched_rjcode || '')
  if (!matchedRJCode) return result
  const linkedHit = linkedWorksForDisplay.find(item => item.rjcode === matchedRJCode)
  if (!linkedHit?.label) return result
  const variant = linkedWorkVariantFromLabel(linkedHit.label)
  result.matched_label = `${matchedRJCode}(${variant.short})`
  result.hit_summary = variant.summary
  result.owned_sentence = `服务器已有拥有${result.matched_label}`
  return result
}

function normalizeKikoeruCheckResult(result = {}, requestedRJCode = '') {
  const primary = result?.primary_result || result?.result || result || {}
  const foundLinkedWorks = Array.isArray(result?.linked_works_found)
    ? result.linked_works_found.filter(Boolean)
    : []
  const fallbackMatchedRJCode = String(primary?.matched_rjcode || result?.matched_rjcode || primary?.rjcode || '').trim()
  const primaryHit = (primary?.is_found || result?.is_found || result?.found || result?.exists) && fallbackMatchedRJCode
    ? [{ ...primary, rjcode: primary?.rjcode || requestedRJCode, matched_rjcode: fallbackMatchedRJCode }]
    : []
  const hitRows = [...primaryHit, ...foundLinkedWorks]
    .map(item => {
      const rjcode = String(item?.matched_rjcode || item?.rjcode || '').trim().toUpperCase()
      if (!rjcode) return null
      return {
        rjcode,
        variant_label: kikoeruVariantLabel(item),
        title: String(item?.title || '').trim()
      }
    })
    .filter(Boolean)
    .filter((item, index, list) => list.findIndex(other => other.rjcode === item.rjcode && other.variant_label === item.variant_label) === index)
  const mergedFound = Boolean(
    result?.is_found
    || result?.found
    || result?.exists
    || primary?.is_found
    || hitRows.length > 0
  )
  const matchedLabel = formatKikoeruOwnedLabel(hitRows)
  const coverRJCode = pickKikoeruCoverRJCode(result, requestedRJCode)
  return {
    requested_rjcode: String(result?.rjcode || requestedRJCode || '').trim(),
    found: mergedFound,
    matched_rjcode: fallbackMatchedRJCode,
    matched_label: matchedLabel,
    owned_sentence: mergedFound ? (matchedLabel ? `服务器已有拥有${matchedLabel}` : '服务器已有该作品') : '服务器未拥有',
    hit_summary: mergedFound ? (hitRows[0]?.variant_label || '服务器已有') : '未命中',
    scope_label: '请求 RJ + DL 关联 RJ',
    title: String(primary?.title || result?.title || '').trim(),
    source: String(primary?.source || result?.source || '').trim(),
    message: String(result?.message || '').trim(),
    linked_rjcodes: [],
    linked_labels: [],
    cover_rjcode: coverRJCode,
    cover_url: buildDlsiteCoverUrl(coverRJCode, 'main'),
    linked_works_total: Number(result?.total_checked || 0),
    hit_rows: hitRows
  }
}

function extractLinkedWorksForDisplay(linkedWorksPayload = {}, requestedRJCode = '') {
  const linkedWorks = linkedWorksPayload?.linked_works && typeof linkedWorksPayload.linked_works === 'object'
    ? linkedWorksPayload.linked_works
    : {}
  const normalizedRequested = String(requestedRJCode || '').trim().toUpperCase()
  return Object.entries(linkedWorks)
    .map(([code, work]) => ({
      rjcode: normalizeRJCode(code),
      label: formatLinkedWorkLabel(code, work)
    }))
    .filter(item => item.rjcode && item.label)
    .sort((a, b) => {
      if (a.rjcode === normalizedRequested) return -1
      if (b.rjcode === normalizedRequested) return 1
      return a.rjcode.localeCompare(b.rjcode)
    })
}

async function withKikoeruAction(action, successMessage = '') {
  kikoeruBusy.value = true
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
  if (kikoeruBusy.value && !kikoeruDuplicateTesting.value) return false
  const rjcode = normalizeRJCode(kikoeruTestRJCode.value)
  if (!rjcode) {
    ElMessage.warning('先填一个 RJ 号')
    return false
  }
  if (kikoeruDuplicateTesting.value) return false
  kikoeruTestRJCode.value = rjcode
  kikoeruDuplicateTesting.value = true
  kikoeruCheckResult.value = null
  try {
    const [linkedWorksResult, checkResult] = await withKikoeruAction(() => Promise.all([
      kikoeruApi.linkedWorks(rjcode, { includeFullLinkage: true, cueLanguages: 'CHI_HANS,CHI_HANT,ENG,JPN' }),
      kikoeruApi.check(rjcode, true)
    ]))
    const normalizedResult = normalizeKikoeruCheckResult(checkResult, rjcode)
    const linkedWorksForDisplay = extractLinkedWorksForDisplay(linkedWorksResult, rjcode)
    normalizedResult.linked_rjcodes = linkedWorksForDisplay.map(item => item.rjcode)
    normalizedResult.linked_labels = linkedWorksForDisplay.map(item => item.label)
    normalizedResult.linked_works_total = normalizedResult.linked_rjcodes.length || normalizedResult.linked_works_total
    applyLinkedWorkDisplayLabels(normalizedResult, linkedWorksForDisplay)
    kikoeruCheckResult.value = normalizedResult
    kikoeruStatusMessage.value = kikoeruCheckResult.value.found
      ? kikoeruCheckResult.value.owned_sentence
      : `服务器未拥有 ${rjcode}`
    return true
  } catch {
    return false
  } finally {
    kikoeruDuplicateTesting.value = false
  }
}

async function runDlsiteConnectionTest() {
  if (dlsiteBusy.value) return false
  dlsiteBusy.value = true
  dlsiteMessage.value = '正在测试 DLsite 连接...'
  dlsiteResult.value = null
  try {
    const result = await configApi.testDlsiteConnection({
      http_proxy: props.config?.metadata?.http_proxy || ''
    })
    dlsiteResult.value = result
    const check = Array.isArray(result?.checks) ? result.checks[0] : null
    const message = result?.success
      ? (check?.message || 'DLsite 连接正常')
      : (check?.message || result?.detail || 'DLsite 连接失败')
    dlsiteMessage.value = result?.success ? `✓ ${message}` : `✗ ${message}`
    if (result?.success) {
      ElMessage.success(message)
      return true
    }
    ElMessage.error(message)
    throw new Error(message)
  } catch (e) {
    if (!dlsiteResult.value) {
      const message = e.response?.data?.detail || e.message || 'DLsite 连接失败'
      dlsiteMessage.value = `✗ ${message}`
      ElMessage.error(message)
    }
    throw e
  } finally {
    dlsiteBusy.value = false
  }
}

async function testSouthPlusConnection() {
  if (southPlusTestBusy.value) return false
  southPlusTestBusy.value = true
  southPlusTestMessage.value = '正在测试南+搜索连接...'
  try {
    const result = await circleCompletionApi.testSouthPlusConnection({
      south_plus_cookie: circleExternalSearch.value.south_plus_cookie,
      south_plus_proxy: circleExternalSearch.value.south_plus_proxy,
    })
    const message = String(result?.message || '南+ 连接测试完成')
    southPlusTestMessage.value = result?.success ? `✓ ${message}` : `✗ ${message}`
    if (!result?.success) {
      ElMessage.error(message)
      throw new Error(message)
    }
    ElMessage.success(message)
    return true
  } catch (error) {
    if (!southPlusTestMessage.value.startsWith('✗')) {
      const message = error.response?.data?.detail || error.message || '南+ 连接失败'
      southPlusTestMessage.value = `✗ ${message}`
      ElMessage.error(message)
    }
    throw error
  } finally {
    southPlusTestBusy.value = false
  }
}

async function handleSouthPlusCookieVisibility(visible) {
  if (!visible || southPlusCookieRevealLoading.value) return
  if (circleExternalSearch.value.south_plus_cookie !== '********') return

  southPlusCookieRevealLoading.value = true
  try {
    const result = await configApi.revealCircleExternalSearchSecret({ key: 'south_plus_cookie' })
    southPlusRevealedCookie.value = String(result?.value || '')
    if (!southPlusRevealedCookie.value) {
      ElMessage.warning('配置文件里没有可显示的原始南+ Cookie')
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '读取已保存的南+ Cookie 失败')
  } finally {
    southPlusCookieRevealLoading.value = false
  }
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
  color: var(--set-text-strong);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.1px;
}

/* SettingsFieldCard slot 内的统一 input 视觉 */
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

.settings-field-dd { display: block; width: 100%; }
.settings-field-dd :deep(.app-dd-root) { display: block; width: 100%; }

.settings-field-dd :deep(.app-dd-trigger) {
  width: 100%;
  min-height: 38px;
  height: 38px;
  padding: 0 12px;
  border-radius: 10px;
  background: var(--set-field-bg);
  border: 1px solid var(--set-border);
  font-size: 13.5px;
  justify-content: space-between;
}

.settings-field-dd :deep(.app-dd-trigger:hover) { border-color: var(--set-border-strong); }
.settings-field-dd :deep(.app-dd-trigger.is-open) {
  border-color: var(--set-border-strong);
  box-shadow: 0 0 0 3px var(--set-focus-ring);
}

/* 规则行 */
.rule-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
  transition: border-color 0.18s ease, background 0.18s ease;
}

.rule-row:hover {
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
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
  border: 1px solid var(--set-border);
  background: var(--set-surface);
  color: var(--set-text);
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
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  color: var(--set-text-strong);
}

.email-watcher-action-btn:hover:not(:disabled) svg:not(.spin-once) {
  transform: rotate(-360deg);
  transition: transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1);
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

.bonus-probe-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.bonus-probe-summary span {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--set-border);
  background: var(--set-surface-soft);
  color: var(--set-text-strong);
  font-size: 12px;
  font-weight: 650;
  letter-spacing: -0.05px;
}

.bonus-probe-note-item {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--set-surface);
  border: 1px solid var(--set-border);
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.bonus-probe-note-item:hover {
  transform: translateY(-1px);
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  box-shadow: 0 4px 12px -4px rgba(15, 23, 42, 0.08);
}

.bonus-probe-note-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: -0.05px;
  margin-bottom: 6px;
}

.bonus-probe-note-item p {
  margin: 0;
  color: var(--set-text-muted);
  font-size: 12.5px;
  line-height: 1.65;
}

.metadata-proxy-row {
  flex-wrap: nowrap;
}

.metadata-proxy-row .field-input {
  width: auto;
  min-width: 0;
  flex: 1 1 auto;
}

.dlsite-test-btn {
  height: 28px;
  min-width: 0;
  padding: 0 8px;
  border-radius: 8px;
  font-size: 10.5px;
  white-space: nowrap;
  letter-spacing: 0;
}

.dlsite-test-btn :deep(.stateful-button__content),
.dlsite-test-btn :deep(.stateful-button__label) {
  gap: 3px;
  font-size: 10.5px;
  line-height: 1;
}

.dlsite-test-btn .service-duplicate-test-icon {
  width: 12px;
  height: 12px;
  flex-basis: 12px;
}

.service-duplicate-test-btn {
  min-width: 108px;
  flex: 0 0 auto;
}

.service-duplicate-test-btn[data-state="loading"] {
  opacity: 1;
  color: var(--set-text-strong);
}

.service-duplicate-test-btn :deep(.stateful-button__content),
.service-duplicate-test-btn :deep(.stateful-button__label) {
  gap: 6px;
}

.service-duplicate-test-icon {
  display: inline-flex;
  width: 14px;
  height: 14px;
  flex: 0 0 14px;
  align-items: center;
  justify-content: center;
}

.service-duplicate-test-icon.is-success svg,
.service-duplicate-test-icon.is-error svg {
  animation: service-duplicate-test-pop 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes service-duplicate-test-pop {
  0% {
    transform: scale(0.55) rotate(-10deg);
  }
  70% {
    transform: scale(1.12) rotate(4deg);
  }
  100% {
    transform: scale(1) rotate(0deg);
  }
}

/* 结果卡 */
.service-result-card {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid var(--set-border);
  background: var(--set-surface-soft);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
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
  color: var(--set-text-muted);
  font-size: 11.5px;
  font-weight: 500;
  letter-spacing: -0.05px;
}

.service-result-line { color: var(--set-text-strong); font-size: 13px; line-height: 1.6; letter-spacing: -0.05px; }

.kikoeru-result-layout {
  display: grid;
  gap: 12px;
}

.kikoeru-result-main {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  min-width: 0;
}

.kikoeru-result-copy {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 4px;
}

.kikoeru-result-cover {
  width: 100%;
  aspect-ratio: 4 / 3;
  margin: 0;
  overflow: hidden;
  border-radius: 10px;
  border: 1px solid var(--set-border);
  background: rgba(15, 23, 42, 0.08);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.12);
}

.kikoeru-result-cover img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
}

.kikoeru-result-cover.is-hidden {
  display: none;
}

.kikoeru-result-meta {
  display: grid;
  grid-template-columns: minmax(108px, 0.9fr) minmax(98px, 0.82fr) minmax(170px, 1.35fr) minmax(170px, 1.45fr);
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--set-border);
}

.kikoeru-result-meta > div {
  min-width: 0;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.12);
}

.kikoeru-result-meta strong {
  display: block;
  color: var(--set-text-strong);
  font-size: 13.5px;
  line-height: 1.3;
  word-break: normal;
  overflow-wrap: anywhere;
}

.kikoeru-result-meta-wide strong {
  white-space: nowrap;
  overflow-wrap: normal;
}

.kikoeru-owned-line {
  display: inline-flex;
  width: fit-content;
  max-width: 100%;
  padding: 5px 9px;
  border-radius: 8px;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.26);
  color: var(--set-success-text);
  font-weight: 700;
}

.kikoeru-rj-chip-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.kikoeru-chip-label {
  margin: 0 2px 0 0;
}

.kikoeru-rj-chip {
  display: inline-flex;
  align-items: center;
  min-height: 23px;
  padding: 3px 8px;
  border-radius: 7px;
  border: 1px solid var(--set-border);
  background: var(--set-surface);
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 650;
  line-height: 1.2;
  white-space: nowrap;
}

.kikoeru-rj-chip.is-original {
  border-color: rgba(96, 165, 250, 0.32);
  background: rgba(59, 130, 246, 0.12);
  color: #bfdbfe;
}

.kikoeru-rj-chip.is-zh-hans {
  border-color: rgba(45, 212, 191, 0.34);
  background: rgba(20, 184, 166, 0.12);
  color: #99f6e4;
}

.kikoeru-rj-chip.is-zh-hant {
  border-color: rgba(251, 191, 36, 0.36);
  background: rgba(245, 158, 11, 0.12);
  color: #fde68a;
}

.kikoeru-rj-chip.is-english {
  border-color: rgba(167, 139, 250, 0.34);
  background: rgba(139, 92, 246, 0.13);
  color: #ddd6fe;
}

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
  background: var(--set-success-bg);
  color: var(--set-success-text);
  border: 1px solid var(--set-success-border);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(16, 185, 129, 0.1);
}

.email-watcher-badge.is-disabled {
  background: var(--set-chip-bg);
  color: var(--set-chip-text);
  border: 1px solid var(--set-border);
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
  background: var(--set-success-bg);
  border: 1px solid var(--set-success-border);
  color: var(--set-success-text);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(16, 185, 129, 0.1);
}

.email-watcher-msg.is-error {
  background: var(--set-danger-bg);
  border: 1px solid var(--set-danger-border);
  color: var(--set-danger-text);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(239, 68, 68, 0.1);
}

.email-watcher-msg.is-info {
  background: var(--set-surface-soft);
  border: 1px solid var(--set-border);
  color: var(--set-text);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.7),
    0 1px 2px rgba(15, 23, 42, 0.04);
}

.email-watcher-error { margin-top: 8px; color: var(--el-color-danger); }

.email-watcher-guide-item {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--set-surface);
  border: 1px solid var(--set-border);
  transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.email-watcher-guide-item:hover {
  transform: translateY(-1px);
  border-color: var(--set-border-strong);
  background: var(--set-surface-hover);
  box-shadow: 0 4px 12px -4px rgba(15, 23, 42, 0.08);
}

.email-watcher-guide-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--set-text-strong);
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: -0.05px;
  margin-bottom: 6px;
}

.email-watcher-guide-item p { font-size: 12.5px; line-height: 1.65; color: var(--set-text-muted); margin: 0; }
.email-watcher-guide-extra { margin-top: 6px !important; }

.email-watcher-guide-item p code {
  background: var(--set-surface-soft);
  border: 1px solid var(--set-border);
  border-radius: 6px;
  padding: 1px 5px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: var(--set-text-strong);
}

.email-watcher-hint {
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--set-warning-bg);
  border: 1px solid var(--set-warning-border);
  color: var(--set-warning-text);
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
  .kikoeru-result-main { grid-template-columns: 200px minmax(0, 1fr); }
  .kikoeru-result-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .kikoeru-result-meta-wide { grid-column: 1 / -1; }
}

@media (max-width: 640px) {
  .kikoeru-result-main { grid-template-columns: 1fr; }
  .kikoeru-result-cover {
    width: min(220px, 100%);
  }
  .kikoeru-result-meta { grid-template-columns: 1fr; }
  .kikoeru-result-meta-wide strong { white-space: normal; }
}
</style>
