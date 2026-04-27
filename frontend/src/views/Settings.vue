<template>
  <div class="settings-page">
    <SettingsWorkbench
      :sections="sections"
      :active-section="activeSection"
      :search-query="searchQuery"
      :has-changes="hasChanges"
      :saving="saving"
      :reloading="reloading"
      :dirty-map="dirtyMap"
      :config-path="config?.db_path || configStore.config?.db_path || ''"
      :last-saved-label="lastSavedLabel"
      @navigate="activeSection = $event"
      @save="saveConfig"
      @reload="reloadConfigFromServer"
      @reset-all="resetAllConfig"
      @update:searchQuery="searchQuery = $event"
    >
      <SettingsSectionPanel
        v-if="activeSection === 'storage'"
        kicker="Storage & Inventory"
        title="存储与库存"
        description="把本地路径、多库存和群晖模板都收进一个工作台。连接信息只维护一次，共享目录库存直接复用。"
      >
        <StorageSettingsPanel
          :model-value="config"
          :profiles="profiles"
          :libraries="libraries"
          :primary-profile="primaryProfile"
          :profile-summaries="profileSummaries"
          :library-view-models="libraryViewModels"
          :get-profile-summary="getProfileSummary"
          :get-library-view-model="getLibraryViewModel"
          :selected-library-id="selectedLibraryId"
          :testing-profile-id="testingProfileId"
          :testing-library-id="testingLibraryId"
          :build-synology-web-url="buildSynologyWebUrl"
          @select-library="selectedLibraryId = $event"
          @test-profile="testProfileConnection"
          @create-library="handleCreateLibrary"
          @remove-library="removeStorageLibrary"
          @test-library="testStorageLibrary"
          @extract-profile="extractSynologyProfileFromLibrary"
          @update-profile-flag="updateProfileFlag"
          @update-library-flag="updateLibraryFlag"
          @profile-change="handleLibraryProfileChange"
          @sync-path="syncRemoteLibraryPath"
        />
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'processing'"
        kicker="Pipeline"
        title="处理流程"
        description="把扫描、解压、自动处理和已有文件夹链路放在一组里看，避免到处来回找开关。"
      >
        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">文件夹监视器</div>
            <div class="toggle-stack">
              <label class="toggle-card"><span><strong>启用监视器</strong><small>后台定期扫描待处理目录。</small></span><el-switch v-model="config.watcher.enabled" /></label>
              <label class="toggle-card"><span><strong>自动开始处理</strong><small>发现新项目后直接进入处理链路。</small></span><el-switch v-model="config.watcher.auto_start" /></label>
              <label class="toggle-card"><span><strong>自动分类</strong><small>监视链路里跟随分类规则落盘。</small></span><el-switch v-model="config.watcher.auto_classify" /></label>
              <label class="toggle-card"><span><strong>处理后删除原文件</strong><small>谨慎开启，适合完全托管的目录。</small></span><el-switch v-model="config.watcher.delete_after_process" /></label>
            </div>
            <label class="metric-card">
              <span class="metric-label">扫描间隔（秒）</span>
              <el-slider v-model="config.watcher.scan_interval" :min="10" :max="300" :step="10" show-input />
            </label>
          </div>

          <div class="settings-card">
            <div class="card-title">处理与解压</div>
            <div class="field-stack">
              <label class="field-card">
                <span class="field-label">最大并发数</span>
                <el-slider v-model="config.processing.max_workers" :min="1" :max="10" show-input />
              </label>
              <label class="field-card">
                <span class="field-label">7-Zip 路径</span>
                <input v-model="config.extract.seven_zip_path" class="field-input" type="text" placeholder="例如 C:\Program Files\7-Zip\7z.exe">
              </label>
              <label class="toggle-card"><span><strong>自动修复后缀名</strong><small>针对异常扩展名做兼容修复。</small></span><el-switch v-model="config.extract.auto_repair_extension" /></label>
              <label class="toggle-card"><span><strong>解压后验证</strong><small>解压后再做结果校验，降低脏目录风险。</small></span><el-switch v-model="config.extract.verify_after_extract" /></label>
              <label class="toggle-card"><span><strong>自动解压嵌套压缩包</strong><small>适合复杂包结构，但会增加处理时长。</small></span><el-switch v-model="config.extract.extract_nested_archives" /></label>
              <label v-if="config.extract.extract_nested_archives" class="field-card">
                <span class="field-label">最大嵌套深度</span>
                <el-slider v-model="config.extract.max_nested_depth" :min="1" :max="10" show-input />
              </label>
            </div>
          </div>
        </div>

        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">正常解压流程</div>
            <div class="pill-switch-grid">
              <label v-for="item in autoProcessItems" :key="item.key" class="toggle-chip">
                <span>{{ item.label }}</span>
                <el-switch v-model="config.auto_process[item.key]" />
              </label>
            </div>
          </div>

          <div class="settings-card">
            <div class="card-title">已有文件夹流程</div>
            <div class="pill-switch-grid">
              <label v-for="item in processExistingItems" :key="item.key" class="toggle-chip">
                <span>{{ item.label }}</span>
                <el-switch v-model="config.process_existing[item.key]" />
              </label>
            </div>
          </div>
        </div>
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'rules'"
        kicker="Rules"
        title="内容规则"
        description="把过滤、重命名、分类和路径映射放到一组里，专注控制最终落盘形态。"
      >
        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">过滤规则</div>
            <div class="toggle-stack compact">
              <label class="toggle-card"><span><strong>过滤文件夹</strong><small>把规则同时应用到目录名。</small></span><el-switch v-model="config.filter.filter_dir" /></label>
            </div>
            <div class="rule-stack">
              <div v-for="(rule, index) in config.filter.rules" :key="`filter-${index}`" class="rule-row">
                <el-select v-model="rule.target" class="rule-target">
                  <el-option label="文件" value="file" />
                  <el-option label="文件夹" value="folder" />
                  <el-option label="全部" value="all" />
                </el-select>
                <input v-model="rule.name" class="field-input" type="text" placeholder="规则名称">
                <input v-model="rule.pattern" class="field-input" type="text" placeholder="正则表达式">
                <el-switch v-model="rule.enabled" />
                <button type="button" class="icon-btn danger" @click="config.filter.rules.splice(index, 1)"><Trash2 :size="15" :stroke-width="2.4" /></button>
              </div>
              <button type="button" class="ghost-inline-btn" @click="addFilterRule"><Plus :size="14" :stroke-width="2.4" /> 添加过滤规则</button>
            </div>
          </div>

          <div class="settings-card">
            <div class="card-title">重命名与落盘</div>
            <div class="field-stack">
              <label class="field-card">
                <span class="field-label">重命名模板</span>
                <input v-model="config.rename.template" class="field-input" type="text" placeholder="{rjcode} {work_name}">
              </label>
              <label class="field-card">
                <span class="field-label">日期格式</span>
                <input v-model="config.rename.date_format" class="field-input" type="text" placeholder="%y%m%d">
              </label>
              <label class="toggle-card"><span><strong>API 重命名遵循模板</strong><small>库存里的 API 重命名也统一走模板。</small></span><el-switch v-model="config.rename.api_rename_follow_template" /></label>
              <label class="toggle-card"><span><strong>使用日语元数据</strong><small>让 maker、CV、tags 等优先取日语元数据。</small></span><el-switch v-model="config.rename.use_japanese_metadata" /></label>
              <label class="toggle-card"><span><strong>移除方括号内容</strong><small>重命名前先剔除方括号片段。</small></span><el-switch v-model="config.rename.exclude_square_brackets" /></label>
              <label class="toggle-card"><span><strong>非法字符转全角</strong><small>降低 Windows 文件名报错概率。</small></span><el-switch v-model="config.rename.illegal_char_to_full_width" /></label>
              <label class="toggle-card"><span><strong>自动扁平化单层文件夹</strong><small>过滤之后顺手把单层嵌套压平。</small></span><el-switch v-model="config.rename.flatten_single_subfolder" /></label>
              <label v-if="config.rename.flatten_single_subfolder" class="field-card">
                <span class="field-label">扁平化深度</span>
                <el-input-number v-model="config.rename.flatten_depth" :min="1" :max="10" class="field-number" />
              </label>
              <label class="toggle-card"><span><strong>自动移除空文件夹</strong><small>过滤和扁平化后清理空目录。</small></span><el-switch v-model="config.rename.remove_empty_folders" /></label>
            </div>
          </div>
        </div>

        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">分类规则</div>
            <div class="rule-stack">
              <div v-for="(rule, index) in config.classification" :key="rule.id || index" class="classification-row">
                <el-select v-model="rule.type" class="rule-target">
                  <el-option label="不分类" value="none" />
                  <el-option label="按社团" value="maker" />
                  <el-option label="按系列" value="series" />
                  <el-option label="按 RJ 段" value="rjcode" />
                </el-select>
                <input v-model="rule.path_template" class="field-input" type="text" placeholder="路径模板">
                <input v-model="rule.custom_name" class="field-input" type="text" placeholder="自定义目录名">
                <input v-model="rule.rjcode_range" class="field-input" type="text" placeholder="RJ 段，例如 RJ01000000-RJ01999999">
                <el-switch v-model="rule.enabled" />
                <button type="button" class="icon-btn danger" @click="config.classification.splice(index, 1)"><Trash2 :size="15" :stroke-width="2.4" /></button>
              </div>
              <button type="button" class="ghost-inline-btn" @click="addRule"><Plus :size="14" :stroke-width="2.4" /> 添加分类规则</button>
            </div>
          </div>

          <div class="settings-card">
            <div class="card-title">路径映射</div>
            <label class="toggle-card"><span><strong>启用路径映射</strong><small>跨设备打开路径时自动换算。</small></span><el-switch v-model="config.path_mapping_enabled" /></label>
            <div class="rule-stack">
              <div v-for="(mapping, index) in config.path_mappings" :key="`mapping-${index}`" class="rule-row">
                <input v-model="mapping.original" class="field-input" type="text" placeholder="原始路径">
                <input v-model="mapping.mapped" class="field-input" type="text" placeholder="映射路径">
                <button type="button" class="icon-btn danger" @click="config.path_mappings.splice(index, 1)"><Trash2 :size="15" :stroke-width="2.4" /></button>
              </div>
              <button type="button" class="ghost-inline-btn" @click="addPathMapping"><Plus :size="14" :stroke-width="2.4" /> 添加映射规则</button>
            </div>
          </div>
        </div>
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'services'"
        kicker="External Services"
        title="外部服务"
        description="集中维护 Kikoeru、ASMR 下载和 RJ 字幕抓取等远程链路。"
      >
        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">Kikoeru 服务器查重</div>
            <div class="field-stack">
              <label class="toggle-card"><span><strong>启用 Kikoeru 查重</strong><small>预检时同时查询远端服务器。</small></span><el-switch v-model="config.kikoeru_server.enabled" /></label>
              <label class="field-card"><span class="field-label">服务器地址</span><input v-model="config.kikoeru_server.server_url" class="field-input" type="text" placeholder="http://192.168.1.100:8088"></label>
              <label class="field-card"><span class="field-label">用户名</span><input v-model="config.kikoeru_server.username" class="field-input" type="text" placeholder="登录用户名"></label>
              <label class="field-card"><span class="field-label">密码</span><AnimatedPasswordInput v-model="config.kikoeru_server.password" placeholder="登录密码" autocomplete="current-password" /></label>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">请求超时</span><el-input-number v-model="config.kikoeru_server.timeout" :min="1" :max="60" class="field-number" /></label>
                <label class="field-card"><span class="field-label">缓存秒数</span><el-input-number v-model="config.kikoeru_server.cache_ttl" :min="0" :max="3600" class="field-number" /></label>
              </div>
              <label class="toggle-card"><span><strong>预检查重</strong><small>在解压预检阶段就使用远端查重。</small></span><el-switch v-model="config.kikoeru_server.check_in_preextract" /></label>
              <div class="service-action-row">
                <button type="button" class="ghost-inline-btn" :disabled="kikoeruBusy" @click="runKikoeruConnectionTest">测试连接</button>
                <button type="button" class="ghost-inline-btn" :disabled="kikoeruBusy" @click="runKikoeruTokenFetch">获取 Token</button>
                <button type="button" class="ghost-inline-btn" :disabled="kikoeruBusy" @click="runKikoeruCacheClear">清缓存</button>
              </div>
              <div class="field-card">
                <span class="field-label">测试查重 RJ</span>
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
                <small class="service-field-tip">实际链路：先从 DL 侧取关联作品，再把主 RJ 和关联 RJ 逐个送到 Kikoeru 查重。</small>
              </div>
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

          <div class="settings-card">
            <div class="card-title">ASMR 同步下载</div>
            <div class="field-stack">
              <label class="toggle-card"><span><strong>启用 ASMR 同步</strong><small>允许从 asmr.one 拉音频与字幕。</small></span><el-switch v-model="config.asmr_sync.enabled" /></label>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">最大并发下载数</span><el-input-number v-model="config.asmr_sync.max_concurrent_downloads" :min="1" :max="10" class="field-number" /></label>
                <label class="field-card"><span class="field-label">最大重试次数</span><el-input-number v-model="config.asmr_sync.max_retry_count" :min="1" :max="100" class="field-number" /></label>
              </div>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">增强会话并发</span><el-input-number v-model="config.asmr_sync.enhanced_max_parallel_sessions" :min="1" :max="10" class="field-number" /></label>
                <label class="field-card"><span class="field-label">单会话并发</span><el-input-number v-model="config.asmr_sync.enhanced_per_session_concurrency" :min="1" :max="10" class="field-number" /></label>
              </div>
              <label class="field-card"><span class="field-label">重试 Cron</span><input v-model="config.asmr_sync.retry_cron" class="field-input" type="text" placeholder="0 */1 * * *"></label>
              <label class="field-card"><span class="field-label">HTTP 代理</span><input v-model="config.asmr_sync.http_proxy" class="field-input" type="text" placeholder="127.0.0.1:7890"></label>
              <label class="toggle-card"><span><strong>自动上传</strong><small>增强下载完成后按默认模式直传库存。</small></span><el-switch v-model="config.asmr_sync.auto_upload_enabled" /></label>
              <div class="mini-grid two" v-if="config.asmr_sync.auto_upload_enabled">
                <label class="field-card"><span class="field-label">上传模式</span><el-select v-model="config.asmr_sync.auto_upload_mode" class="field-select"><el-option label="本地复制" value="local" /><el-option label="群晖上传" value="synology" /></el-select></label>
                <label class="field-card"><span class="field-label">默认群晖库存 ID</span><input v-model="config.asmr_sync.auto_upload_library_id" class="field-input" type="text" placeholder="例如 synology-main"></label>
              </div>
              <label class="field-card" v-if="config.asmr_sync.auto_upload_enabled"><span class="field-label">默认目标路径</span><input v-model="config.asmr_sync.auto_upload_target_path" class="field-input" type="text" placeholder="本地目录或远程目录"></label>
            </div>
          </div>
        </div>

        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">ASMR 字幕处理</div>
            <div class="toggle-stack">
              <label class="toggle-card"><span><strong>启用 LRC 广告清理</strong><small>下载后自动剔除常见引流信息。</small></span><el-switch v-model="config.asmr_sync.lrc_clean_enabled" /></label>
              <label class="toggle-card"><span><strong>字幕繁体转简体</strong><small>统一工作台里字幕文本的简体口径。</small></span><el-switch v-model="config.asmr_sync.simplify_chinese_enabled" /></label>
            </div>
            <div v-if="config.asmr_sync.lrc_clean_enabled" class="rule-stack">
              <div v-for="(pattern, index) in config.asmr_sync.lrc_clean_patterns" :key="`lrc-${index}`" class="rule-row">
                <input v-model="config.asmr_sync.lrc_clean_patterns[index]" class="field-input" type="text" placeholder="正则表达式">
                <button type="button" class="icon-btn danger" @click="config.asmr_sync.lrc_clean_patterns.splice(index, 1)"><Trash2 :size="15" :stroke-width="2.4" /></button>
              </div>
              <button type="button" class="ghost-inline-btn" @click="config.asmr_sync.lrc_clean_patterns.push('')"><Plus :size="14" :stroke-width="2.4" /> 添加清理规则</button>
            </div>
          </div>

          <div class="settings-card">
            <div class="card-title">RJ 字幕抓取</div>
            <div class="pill-switch-grid">
              <label v-for="item in subtitleItems" :key="item.key" class="toggle-chip">
                <span>{{ item.label }}</span>
                <el-switch v-model="config.rj_subtitle[item.key]" />
              </label>
            </div>
            <div class="mini-grid two">
              <label class="field-card"><span class="field-label">命名策略</span><el-select v-model="config.rj_subtitle.naming_strategy" class="field-select"><el-option label="按音频" value="audio" /><el-option label="按字幕" value="subtitle" /></el-select></label>
              <label class="toggle-card"><span><strong>抓取阶段复用过滤规则</strong><small>让字幕工作台预过滤规则直接复用设置页。</small></span><el-switch v-model="config.rj_subtitle.use_filter_rules" /></label>
            </div>
          </div>
        </div>

        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">
              DLsite 邮件监听
              <span v-if="config.email_watcher.enabled" class="email-watcher-badge is-enabled">已启用</span>
              <span v-else class="email-watcher-badge is-disabled">未启用</span>
            </div>
            <div class="field-stack">
              <label class="toggle-card">
                <span><strong>启用邮件监听</strong><small>IMAP IDLE 长连接实时监听 DLsite 新作通知，自动触发社团索引。</small></span>
                <el-switch v-model="config.email_watcher.enabled" />
              </label>
              <div class="mini-grid two">
                <label class="field-card">
                  <span class="field-label">快速预设</span>
                  <el-select v-model="emailImapPreset" class="field-select" placeholder="选择邮件服务">
                    <el-option label="Gmail" value="gmail" />
                    <el-option label="QQ 邮箱" value="qq" />
                    <el-option label="163 邮箱" value="163" />
                    <el-option label="Outlook" value="outlook" />
                    <el-option label="自定义" value="custom" />
                  </el-select>
                </label>
                <label class="field-card">
                  <span class="field-label">端口</span>
                  <el-input-number v-model="config.email_watcher.imap_port" :min="1" :max="65535" class="field-number" />
                </label>
              </div>
              <label class="field-card">
                <span class="field-label">IMAP 地址</span>
                <input v-model="config.email_watcher.imap_host" class="field-input" type="text" placeholder="例如 imap.gmail.com">
              </label>
              <label class="toggle-card">
                <span><strong>使用 SSL</strong><small>绝大多数 IMAP 服务器需要 SSL（推荐开启）。</small></span>
                <el-switch v-model="config.email_watcher.imap_ssl" />
              </label>
              <label class="field-card">
                <span class="field-label">邮箱账号</span>
                <input v-model="config.email_watcher.username" class="field-input" type="text" placeholder="例如 yourname@gmail.com" autocomplete="username">
              </label>
              <label class="field-card">
                <span class="field-label">密码 / 授权码</span>
                <AnimatedPasswordInput v-model="config.email_watcher.password" placeholder="Gmail 填应用专用密码；QQ/163 填 IMAP 授权码" autocomplete="new-password" />
              </label>
              <div v-if="emailImapPasswordHint" class="email-watcher-hint">
                <span>{{ emailImapPasswordHint }}</span>
              </div>
              <div class="mini-grid two">
                <label class="field-card">
                  <span class="field-label">监听文件夹</span>
                  <input v-model="config.email_watcher.mailbox" class="field-input" type="text" placeholder="INBOX">
                </label>
                <label class="field-card">
                  <span class="field-label">移入文件夹（可选）</span>
                  <input v-model="config.email_watcher.move_to_folder" class="field-input" type="text" placeholder="留空则不移动">
                </label>
              </div>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">发件人关键词</span><input v-model="config.email_watcher.sender_filter" class="field-input" type="text" placeholder="dlsite.com"></label>
                <label class="field-card"><span class="field-label">主题关键词</span><input v-model="config.email_watcher.subject_filter" class="field-input" type="text" placeholder="新着作品"></label>
              </div>
              <div class="mini-grid two">
                <label class="toggle-card"><span><strong>处理后标记已读</strong></span><el-switch v-model="config.email_watcher.mark_as_read" /></label>
                <label class="toggle-card"><span><strong>新社团自动全量索引</strong><small>首次出现的社团建立索引。</small></span><el-switch v-model="config.email_watcher.auto_index_new_circles" /></label>
              </div>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">IDLE 超时（分钟）</span><el-input-number v-model="config.email_watcher.idle_timeout_minutes" :min="5" :max="28" class="field-number" /></label>
                <label class="field-card"><span class="field-label">降级轮询间隔（秒）</span><el-input-number v-model="config.email_watcher.fallback_poll_interval_seconds" :min="60" :max="3600" class="field-number" /></label>
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
                  <div v-if="emailWatcherStatus.last_error" class="service-result-line" style="margin-top:8px;color:var(--el-color-danger)">错误：{{ emailWatcherStatus.last_error }}</div>
                </div>
              </transition>
            </div>
          </div>

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
                <p style="margin-top:6px"><strong>移入文件夹</strong>：处理完邮件后自动把它搬到该文件夹（需提前在邮箱里创建好），留空则邮件原地不动。配合「标记已读」使用可保持收件箱整洁。</p>
              </div>
            </div>
          </div>
        </div>
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else-if="activeSection === 'maintenance'"
        kicker="Maintenance"
        title="维护与清理"
        description="自动清理、备份打包等维护项集中放在一起，避免日常配置区被危险操作打断。"
      >
        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">密码库智能清理</div>
            <div class="field-stack">
              <label class="toggle-card"><span><strong>启用自动清理</strong><small>按使用次数和保留天数自动清理密码库。</small></span><el-switch v-model="config.password_cleanup.enabled" /></label>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">使用次数阈值</span><el-slider v-model="config.password_cleanup.max_use_count" :min="0" :max="10" show-input /></label>
                <label class="field-card"><span class="field-label">保留天数</span><el-slider v-model="config.password_cleanup.preserve_days" :min="1" :max="90" show-input /></label>
              </div>
              <label class="field-card"><span class="field-label">Cron 表达式</span><input v-model="config.password_cleanup.cron_expression" class="field-input" type="text" placeholder="0 0 * * 0"></label>
            </div>
          </div>

          <div class="settings-card">
            <div class="card-title">已处理压缩包清理</div>
            <div class="field-stack">
              <label class="toggle-card"><span><strong>启用自动清理</strong><small>按天数和保底数量控制已处理压缩包规模。</small></span><el-switch v-model="config.archive_cleanup.enabled" /></label>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">保留天数</span><el-slider v-model="config.archive_cleanup.preserve_days" :min="1" :max="90" show-input /></label>
                <label class="field-card"><span class="field-label">最小保留数量</span><el-input-number v-model="config.archive_cleanup.min_keep_count" :min="0" :max="100" class="field-number" /></label>
              </div>
              <label class="field-card"><span class="field-label">Cron 表达式</span><input v-model="config.archive_cleanup.cron_expression" class="field-input" type="text" placeholder="0 0 * * 0"></label>
            </div>
          </div>
        </div>

        <div class="settings-card">
          <div class="card-title">库存打包</div>
          <div class="settings-grid two">
            <div class="field-stack">
              <label class="toggle-card"><span><strong>启用库存打包</strong><small>按压缩参数把指定目录输出为发布包。</small></span><el-switch v-model="config.backup_zip.enabled" /></label>
              <label class="field-card"><span class="field-label">源目录</span><input v-model="config.backup_zip.source_path" class="field-input" type="text" placeholder="要打包的目录"></label>
              <label class="field-card"><span class="field-label">输出目录</span><input v-model="config.backup_zip.output_dir" class="field-input" type="text" placeholder="打包结果输出目录"></label>
            </div>
            <div class="field-stack">
              <label class="field-card"><span class="field-label">临时复制目录</span><input v-model="config.backup_zip.path_copy_target" class="field-input" type="text" placeholder="可选中转目录"></label>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">压缩格式</span><el-select v-model="config.backup_zip.archive_format" class="field-select"><el-option label="zip" value="zip" /><el-option label="7z" value="7z" /></el-select></label>
                <label class="field-card"><span class="field-label">压缩级别</span><el-input-number v-model="config.backup_zip.compression_level" :min="0" :max="9" class="field-number" /></label>
              </div>
              <label class="toggle-card"><span><strong>复制结构后再压缩</strong><small>先生成中转目录再做归档，更适合复杂结构。</small></span><el-switch v-model="config.backup_zip.copy_structure_before_zip" /></label>
            </div>
          </div>
        </div>
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else
        kicker="Notifications"
        title="通知中心"
        description="任务完成、失败或需要人工处理时，站内铃铛实时提醒；配置 SMTP 还可收到邮件推送。"
      >
        <div class="settings-grid two">
          <div class="settings-card">
            <div class="card-title">站内通知</div>
            <div class="toggle-stack">
              <label class="toggle-card"><span><strong>启用通知中心</strong><small>任务状态变化时写入站内铃铛。</small></span><el-switch v-model="config.notification_center.enabled" /></label>
              <label class="toggle-card"><span><strong>未读高亮提示</strong><small>铃铛图标显示未读数量徽章。</small></span><el-switch v-model="config.notification_center.unread_highlight_enabled" /></label>
            </div>
            <div class="field-stack" style="margin-top:10px">
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">通知保留天数</span><el-input-number v-model="config.notification_center.retain_days" :min="1" :max="365" class="field-number" /></label>
                <label class="field-card"><span class="field-label">最大保留条数</span><el-input-number v-model="config.notification_center.max_items" :min="20" :max="2000" class="field-number" /></label>
              </div>
            </div>
          </div>

          <div class="settings-card">
            <div class="card-title">邮件推送触发规则</div>
            <div class="toggle-stack">
              <label class="toggle-card"><span><strong>启用邮件推送</strong><small>通过 SMTP 发送任务通知邮件。</small></span><el-switch v-model="config.notification_email.enabled" /></label>
              <label class="toggle-card"><span><strong>任务完成时发送</strong></span><el-switch v-model="config.notification_email.send_on_completed" :disabled="!config.notification_email.enabled" /></label>
              <label class="toggle-card"><span><strong>任务失败时发送</strong></span><el-switch v-model="config.notification_email.send_on_failed" :disabled="!config.notification_email.enabled" /></label>
              <label class="toggle-card"><span><strong>等待人工处理时发送</strong></span><el-switch v-model="config.notification_email.send_on_waiting_manual" :disabled="!config.notification_email.enabled" /></label>
              <label class="toggle-card"><span><strong>任务取消时发送</strong><small>默认关闭，取消通知噪音较多。</small></span><el-switch v-model="config.notification_email.send_on_cancelled" :disabled="!config.notification_email.enabled" /></label>
            </div>
          </div>
        </div>

        <div class="settings-card" v-if="config.notification_email.enabled">
          <div class="card-title">SMTP 发件配置</div>
          <div class="smtp-preset-row">
            <span class="smtp-preset-label">快速填入：</span>
            <button v-for="p in smtpPresets" :key="p.name" class="smtp-preset-btn" type="button" @click="applySmtpPreset(p)">{{ p.name }}</button>
            <a class="smtp-help-link" href="https://service.mail.qq.com/detail/0/75" target="_blank" rel="noopener">QQ 如何开启 SMTP？</a>
          </div>
          <div class="settings-grid two">
            <div class="field-stack">
              <label class="field-card">
                <span class="field-label">SMTP 主机 <small style="color:#8e8e93;font-weight:400">（填服务器地址，如 smtp.qq.com）</small></span>
                <input v-model="config.notification_email.smtp_host" class="field-input" type="text" placeholder="smtp.qq.com">
              </label>
              <div class="mini-grid two">
                <label class="field-card"><span class="field-label">端口</span><el-input-number v-model="config.notification_email.smtp_port" :min="1" :max="65535" class="field-number" /></label>
                <div class="field-card" style="gap:8px">
                  <label class="toggle-mini"><el-switch v-model="config.notification_email.smtp_ssl" @change="v => { if(v) config.notification_email.smtp_starttls = false }" /><span>SSL</span></label>
                  <label class="toggle-mini"><el-switch v-model="config.notification_email.smtp_starttls" @change="v => { if(v) config.notification_email.smtp_ssl = false }" /><span>STARTTLS</span></label>
                </div>
              </div>
              <label class="field-card"><span class="field-label">发件账号</span><input v-model="config.notification_email.username" class="field-input" type="text" placeholder="your@qq.com"></label>
              <label class="field-card"><span class="field-label">发件密码 / 授权码</span><AnimatedPasswordInput v-model="config.notification_email.password" placeholder="QQ 邮箱需填授权码" /></label>
            </div>
            <div class="field-stack">
              <label class="field-card"><span class="field-label">发件显示名</span><input v-model="config.notification_email.from_name" class="field-input" type="text" placeholder="Prekikoeru"></label>
              <label class="field-card"><span class="field-label">发件地址</span><input v-model="config.notification_email.from_email" class="field-input" type="text" placeholder="留空使用账号地址"></label>
              <label class="field-card"><span class="field-label">收件地址</span><input v-model="config.notification_email.to_email" class="field-input" type="text" placeholder="接收通知的邮箱"></label>
              <div class="field-card" style="flex-direction:row;align-items:center;gap:8px">
                <button class="action-btn action-btn--secondary" :disabled="emailTestBusy" @click="doTestEmail">
                  <Mail :size="14" />
                  {{ emailTestBusy ? '发送中...' : '发送测试邮件' }}
                </button>
                <span v-if="emailTestResult" :class="['email-test-result', emailTestResult.ok ? 'ok' : 'err']" style="white-space:pre-line">{{ emailTestResult.message }}</span>
              </div>
            </div>
          </div>
        </div>
      </SettingsSectionPanel>
    </SettingsWorkbench>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import { Boxes, HardDrive, LifeBuoy, ScanSearch, Workflow, Plus, Trash2, Wifi, RefreshCw, Mail, Zap, BookOpen, FolderOpen, Bell } from 'lucide-vue-next'
import SettingsSectionPanel from '../components/settings/SettingsSectionPanel.vue'
import SettingsWorkbench from '../components/settings/SettingsWorkbench.vue'
import StorageSettingsPanel from '../components/settings/StorageSettingsPanel.vue'
import AnimatedPasswordInput from '../components/common/AnimatedPasswordInput.vue'
import { useSettingsDraft } from '../composables/useSettingsDraft'
import { useSynologyProfiles } from '../composables/useSynologyProfiles'
import { kikoeruApi, emailWatcherApi, notificationApi } from '../api'
import { useConfigStore } from '../stores'
import insiderLoadingAnimation from '../assets/anime/Insider-loading.lottie'
import successConfettiAnimation from '../assets/anime/success confetti.lottie'

const configStore = useConfigStore()
const {
  config,
  snapshot,
  loading,
  saving,
  reloading,
  lastSavedAt,
  hasChanges,
  loadConfig,
  saveConfig,
  reloadConfigFromServer,
  resetAllConfig
} = useSettingsDraft()

const {
  profiles,
  libraries,
  primaryProfile,
  profileSummaries,
  libraryViewModels,
  testingProfileId,
  testingLibraryId,
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
  updateLibraryFlag,
  syncRemoteLibraryPath
} = useSynologyProfiles(config)

const activeSection = ref('storage')
const searchQuery = ref('')
const selectedLibraryId = ref('')
const kikoeruBusy = ref(false)
const kikoeruStatusMessage = ref('')
const kikoeruTestRJCode = ref('')
const kikoeruCheckResult = ref(null)
const kikoeruButtonState = ref('idle')
const kikoeruButtonLottieRef = ref(null)
const kikoeruButtonLottieReady = ref(false)
let kikoeruButtonResetTimer = null

// 邮件监听
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
  if (!config.value) return
  if (val === 'gmail') { config.value.email_watcher.imap_host = 'imap.gmail.com'; config.value.email_watcher.imap_port = 993; config.value.email_watcher.imap_ssl = true }
  else if (val === 'qq') { config.value.email_watcher.imap_host = 'imap.qq.com'; config.value.email_watcher.imap_port = 993; config.value.email_watcher.imap_ssl = true }
  else if (val === '163') { config.value.email_watcher.imap_host = 'imap.163.com'; config.value.email_watcher.imap_port = 993; config.value.email_watcher.imap_ssl = true }
  else if (val === 'outlook') { config.value.email_watcher.imap_host = 'outlook.office365.com'; config.value.email_watcher.imap_port = 993; config.value.email_watcher.imap_ssl = true }
})

async function testEmailWatcherConnection() {
  if (emailWatcherBusy.value) return
  emailWatcherBusy.value = true
  emailWatcherMessage.value = '正在测试连接...'
  emailWatcherStatus.value = null
  try {
    const result = await emailWatcherApi.test({
      imap_host: config.value.email_watcher.imap_host,
      imap_port: config.value.email_watcher.imap_port,
      imap_ssl: config.value.email_watcher.imap_ssl,
      username: config.value.email_watcher.username,
      password: config.value.email_watcher.password,
      mailbox: config.value.email_watcher.mailbox
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

// SMTP 服务商预设
const smtpPresets = [
  { name: 'QQ 邮箱', smtp_host: 'smtp.qq.com', smtp_port: 465, smtp_ssl: true, smtp_starttls: false },
  { name: '163 邮箱', smtp_host: 'smtp.163.com', smtp_port: 465, smtp_ssl: true, smtp_starttls: false },
  { name: '126 邮箱', smtp_host: 'smtp.126.com', smtp_port: 465, smtp_ssl: true, smtp_starttls: false },
  { name: 'Gmail', smtp_host: 'smtp.gmail.com', smtp_port: 587, smtp_ssl: false, smtp_starttls: true },
  { name: 'Outlook', smtp_host: 'smtp.office365.com', smtp_port: 587, smtp_ssl: false, smtp_starttls: true },
]

function applySmtpPreset(preset) {
  config.value.notification_email.smtp_host = preset.smtp_host
  config.value.notification_email.smtp_port = preset.smtp_port
  config.value.notification_email.smtp_ssl = preset.smtp_ssl
  config.value.notification_email.smtp_starttls = preset.smtp_starttls
}

// 通知邮件测试
const emailTestBusy = ref(false)
const emailTestResult = ref(null)
async function doTestEmail() {
  if (emailTestBusy.value) return
  emailTestBusy.value = true
  emailTestResult.value = null
  try {
    const cfg = { ...config.value.notification_email }
    const result = await notificationApi.testEmail(cfg)
    emailTestResult.value = result
  } catch (e) {
    emailTestResult.value = { ok: false, message: e.response?.data?.detail || e.message || '发送失败' }
  } finally {
    emailTestBusy.value = false
  }
}

const sections = [
  { id: 'storage', title: '存储与库存', short: '路径、本地库存、群晖模板', icon: HardDrive, keywords: ['storage', 'library', 'synology', '群晖', '库存'] },
  { id: 'processing', title: '处理流程', short: '监视、解压、自动处理', icon: Workflow, keywords: ['watcher', 'processing', 'extract', '自动处理'] },
  { id: 'rules', title: '内容规则', short: '过滤、重命名、分类、路径映射', icon: Boxes, keywords: ['filter', 'rename', 'classification', 'path'] },
  { id: 'services', title: '外部服务', short: 'Kikoeru、ASMR、RJ 字幕', icon: ScanSearch, keywords: ['kikoeru', 'asmr', 'subtitle', '外部服务'] },
  { id: 'maintenance', title: '维护与清理', short: '清理、备份、压缩包', icon: LifeBuoy, keywords: ['cleanup', 'backup', 'archive', '维护'] },
  { id: 'notification', title: '通知中心', short: 'SMTP 邮件、站内铃铛', icon: Bell, keywords: ['notification', 'smtp', 'email', '通知', '邮件', '铃铛'] }
]

const sectionKeyMap = {
  storage: ['storage'],
  processing: ['watcher', 'processing', 'extract', 'auto_process', 'process_existing'],
  rules: ['filter', 'rename', 'classification', 'path_mappings', 'path_mapping_enabled'],
  services: ['kikoeru_server', 'asmr_sync', 'asmr_sync_step', 'rj_subtitle', 'email_watcher'],
  maintenance: ['password_cleanup', 'archive_cleanup', 'backup_zip'],
  notification: ['notification_email', 'notification_center']
}

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

const subtitleItems = [
  { key: 'overwrite_existing', label: '覆盖已有字幕' },
  { key: 'scan_one_level_only', label: '只扫一层目录' },
  { key: 'enable_metadata_match', label: '启用元数据匹配' },
  { key: 'show_source_search', label: '显示来源搜索' },
  { key: 'show_written_files', label: '显示落盘文件' },
  { key: 'show_download_progress', label: '显示下载进度' },
  { key: 'show_issues', label: '显示问题项' }
]

function pickSectionState(source = {}, keys = []) {
  return keys.reduce((result, key) => {
    result[key] = source?.[key]
    return result
  }, {})
}

const dirtyMap = computed(() => {
  return Object.fromEntries(
    Object.entries(sectionKeyMap).map(([sectionId, keys]) => {
      const draft = JSON.stringify(pickSectionState(config.value, keys))
      const snapshotState = JSON.stringify(pickSectionState(snapshot.value, keys))
      return [sectionId, draft !== snapshotState]
    })
  )
})

const lastSavedLabel = computed(() => {
  if (!lastSavedAt.value) return '尚未保存'
  const date = new Date(lastSavedAt.value)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
})

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

function handleCreateLibrary(type) {
  const created = addStorageLibrary(type)
  selectedLibraryId.value = created.id
}

function addFilterRule() {
  config.value.filter.rules.push({
    name: '新规则',
    pattern: '',
    target: 'file',
    action: 'exclude',
    enabled: true
  })
}

function addRule() {
  config.value.classification.push({
    id: Date.now(),
    type: 'none',
    path_template: '',
    custom_name: '',
    rjcode_range: '',
    enabled: true
  })
}

function addPathMapping() {
  config.value.path_mappings.push({
    original: '',
    mapped: ''
  })
}

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

  return {
    requested_rjcode: String(result?.rjcode || requestedRJCode || '').trim(),
    found: Boolean(primary?.is_found ?? result?.found ?? result?.exists),
    matched_rjcode: String(primary?.rjcode || primary?.matched_rjcode || result?.matched_rjcode || '').trim(),
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

watch(libraryViewModels, (list) => {
  if (!selectedLibraryId.value && list.length) selectedLibraryId.value = list[0].id
  if (selectedLibraryId.value && !list.some(item => item.id === selectedLibraryId.value)) {
    selectedLibraryId.value = list[0]?.id || ''
  }
}, { immediate: true, deep: true })

onMounted(() => {
  loadConfig()

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
.settings-page {
  min-height: 100%;
  padding: 18px;
  background: #fff;
}

.settings-grid,
.field-stack,
.toggle-stack,
.pill-switch-grid,
.mini-grid,
.rule-stack {
  display: grid;
  gap: 16px;
}

.settings-grid.two,
.mini-grid.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.settings-card {
  padding: 20px;
  border-radius: 24px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.05);
}

.card-title {
  margin-bottom: 16px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
}

.field-card,
.toggle-card,
.toggle-chip {
  display: flex;
  gap: 14px;
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.92);
  background: rgba(248, 250, 252, 0.88);
}

.field-card {
  flex-direction: column;
  padding: 16px;
}

.field-label,
.metric-label {
  color: #94a3b8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.field-input {
  width: 100%;
  min-height: 42px;
  padding: 0 12px;
  border: none;
  outline: none;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.95);
  color: #0f172a;
  font-size: 14px;
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.92);
}

.field-number :deep(.el-input__wrapper),
.field-select :deep(.el-select__wrapper) {
  min-height: 42px;
  border-radius: 12px;
}

.toggle-card {
  justify-content: space-between;
  align-items: center;
  padding: 16px 18px;
}

.toggle-card strong {
  display: block;
  color: #0f172a;
  font-size: 14px;
}

.toggle-card small {
  display: block;
  margin-top: 5px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.pill-switch-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.toggle-chip {
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}

.rule-row,
.classification-row {
  display: grid;
  grid-template-columns: 140px minmax(0, 1fr) minmax(0, 1.1fr) auto auto;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(248, 250, 252, 0.88);
}

.classification-row {
  grid-template-columns: 140px minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.2fr) auto auto;
}

.rule-target :deep(.el-select__wrapper) {
  min-height: 42px;
  border-radius: 12px;
}

.ghost-inline-btn,
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 38px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(255, 255, 255, 0.94);
  color: #334155;
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}

.ghost-inline-btn {
  justify-self: flex-start;
  padding: 0 14px;
}

.service-action-row,
.service-inline-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.service-inline-row .field-input {
  flex: 1 1 220px;
}

.service-lottie-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  min-width: 122px;
  height: 44px;
  padding: 0 14px 0 10px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
  flex-shrink: 0;
  cursor: pointer;
  transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease, opacity .18s ease;
}

.service-lottie-trigger__animation {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  flex-shrink: 0;
}

.service-lottie-trigger__player {
  width: 24px;
  height: 24px;
  pointer-events: none;
  filter: drop-shadow(0 2px 6px rgba(148, 163, 184, 0.18));
}

.service-lottie-trigger__label {
  color: #334155;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.01em;
  pointer-events: none;
  white-space: nowrap;
}

.service-lottie-trigger:not(:disabled):hover {
  cursor: pointer;
  transform: translateY(-1px);
  border-color: rgba(148, 163, 184, 0.9);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
}

.service-lottie-trigger.is-busy,
.service-lottie-trigger:disabled {
  cursor: not-allowed;
}

.service-lottie-trigger.is-busy .service-lottie-trigger__label {
  color: #0f172a;
}

.service-lottie-trigger.is-loading .service-lottie-trigger__player {
  filter: grayscale(1) brightness(0.72) contrast(1.05);
}

.service-lottie-trigger.is-loading {
  border-color: rgba(203, 213, 225, 0.95);
  background: linear-gradient(180deg, rgba(255,255,255,.96), rgba(248,250,252,.96));
}

.service-lottie-trigger.is-success .service-lottie-trigger__player {
  filter: drop-shadow(0 2px 8px rgba(74, 222, 128, 0.24));
}

.service-result-card {
  padding: 16px 18px;
  border-radius: 18px;
  border: 1px solid rgba(191, 219, 254, 0.9);
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.96), rgba(248, 250, 252, 0.96));
}

.service-result-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}

.service-result-key {
  display: block;
  margin-bottom: 4px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.service-result-line {
  color: #0f172a;
  font-size: 13px;
  line-height: 1.6;
}

.service-field-tip {
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.icon-btn {
  width: 38px;
  padding: 0;
}

.icon-btn.danger {
  color: #be123c;
}

@media (max-width: 1200px) {
  .settings-grid.two,
  .mini-grid.two,
  .pill-switch-grid {
    grid-template-columns: 1fr;
  }

  .rule-row,
  .classification-row,
  .service-result-grid {
    grid-template-columns: 1fr;
  }
}
/* ---- 邮件监听 ---- */
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.email-watcher-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.email-watcher-badge.is-enabled {
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.12), rgba(16, 185, 129, 0.10));
  color: #15803d;
  border: 1px solid rgba(34, 197, 94, 0.3);
}

.email-watcher-badge.is-disabled {
  background: rgba(148, 163, 184, 0.1);
  color: #94a3b8;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.email-watcher-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 16px;
  height: 36px;
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: rgba(255, 255, 255, 0.92);
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.email-watcher-action-btn:not(:disabled):hover {
  transform: translateY(-2px) scale(1.02);
  border-color: rgba(99, 102, 241, 0.35);
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.12);
  color: #4f46e5;
}

.email-watcher-action-btn:not(:disabled):active {
  transform: scale(0.96);
  box-shadow: none;
}

.email-watcher-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.email-watcher-msg {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.5;
}

.email-watcher-msg.is-success {
  background: rgba(34, 197, 94, 0.08);
  border: 1px solid rgba(34, 197, 94, 0.25);
  color: #15803d;
}

.email-watcher-msg.is-error {
  background: rgba(239, 68, 68, 0.07);
  border: 1px solid rgba(239, 68, 68, 0.22);
  color: #b91c1c;
}

.email-watcher-msg.is-info {
  background: rgba(99, 102, 241, 0.07);
  border: 1px solid rgba(99, 102, 241, 0.18);
  color: #4338ca;
}

.email-watcher-guide-item {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.9);
  border: 1px solid rgba(226, 232, 240, 0.7);
}

.email-watcher-guide-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 800;
  color: #475569;
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}

.email-watcher-guide-item p {
  font-size: 12.5px;
  line-height: 1.75;
  color: #64748b;
  margin: 0;
}

.email-watcher-guide-item p code {
  background: rgba(99, 102, 241, 0.08);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 11.5px;
  color: #4338ca;
  font-family: ui-monospace, monospace;
}

.fade-up-enter-active, .fade-up-leave-active {
  transition: all 0.28s ease;
}
.fade-up-enter-from, .fade-up-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

@keyframes spin-once {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.spin-once {
  animation: spin-once 0.7s linear infinite;
}

.email-watcher-hint {
  padding: 9px 13px;
  border-radius: 10px;
  background: rgba(250, 204, 21, 0.08);
  border: 1px solid rgba(250, 204, 21, 0.3);
  color: #92400e;
  font-size: 12px;
  line-height: 1.6;
}

.toggle-mini {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(29, 29, 31, 0.7);
  cursor: pointer;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 10px;
  border: none;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.action-btn:hover {
  transform: translateY(-2px) scale(1.02);
}

.action-btn:active {
  transform: scale(0.96);
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.action-btn--secondary {
  background: rgba(0, 113, 227, 0.08);
  color: #0071e3;
  border: 1px solid rgba(0, 113, 227, 0.18);
}

.action-btn--secondary:hover {
  background: rgba(0, 113, 227, 0.14);
}

.email-test-result {
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 8px;
}

.email-test-result.ok {
  background: rgba(31, 143, 78, 0.08);
  color: #1f8f4e;
  border: 1px solid rgba(31, 143, 78, 0.18);
}

.email-test-result.err {
  background: rgba(217, 48, 37, 0.08);
  color: #d93025;
  border: 1px solid rgba(217, 48, 37, 0.18);
}

.smtp-preset-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.smtp-preset-label {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.5);
}

.smtp-preset-btn {
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 500;
  color: #0071e3;
  background: rgba(0, 113, 227, 0.06);
  border: 1px solid rgba(0, 113, 227, 0.15);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.smtp-preset-btn:hover {
  background: rgba(0, 113, 227, 0.12);
  border-color: rgba(0, 113, 227, 0.3);
}

.smtp-help-link {
  font-size: 12px;
  color: rgba(29, 29, 31, 0.4);
  text-decoration: underline;
  text-underline-offset: 2px;
  margin-left: auto;
  transition: color 0.15s;
}

.smtp-help-link:hover {
  color: #0071e3;
}

</style>
