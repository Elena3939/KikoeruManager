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
      </SettingsSectionPanel>

      <SettingsSectionPanel
        v-else
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
    </SettingsWorkbench>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DotLottieVue } from '@lottiefiles/dotlottie-vue'
import { Boxes, HardDrive, LifeBuoy, ScanSearch, Workflow, Plus, Trash2 } from 'lucide-vue-next'
import SettingsSectionPanel from '../components/settings/SettingsSectionPanel.vue'
import SettingsWorkbench from '../components/settings/SettingsWorkbench.vue'
import StorageSettingsPanel from '../components/settings/StorageSettingsPanel.vue'
import AnimatedPasswordInput from '../components/common/AnimatedPasswordInput.vue'
import { useSettingsDraft } from '../composables/useSettingsDraft'
import { useSynologyProfiles } from '../composables/useSynologyProfiles'
import { kikoeruApi } from '../api'
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

const sections = [
  { id: 'storage', title: '存储与库存', short: '路径、本地库存、群晖模板', icon: HardDrive, keywords: ['storage', 'library', 'synology', '群晖', '库存'] },
  { id: 'processing', title: '处理流程', short: '监视、解压、自动处理', icon: Workflow, keywords: ['watcher', 'processing', 'extract', '自动处理'] },
  { id: 'rules', title: '内容规则', short: '过滤、重命名、分类、路径映射', icon: Boxes, keywords: ['filter', 'rename', 'classification', 'path'] },
  { id: 'services', title: '外部服务', short: 'Kikoeru、ASMR、RJ 字幕', icon: ScanSearch, keywords: ['kikoeru', 'asmr', 'subtitle', '外部服务'] },
  { id: 'maintenance', title: '维护与清理', short: '清理、备份、压缩包', icon: LifeBuoy, keywords: ['cleanup', 'backup', 'archive', '维护'] }
]

const sectionKeyMap = {
  storage: ['storage'],
  processing: ['watcher', 'processing', 'extract', 'auto_process', 'process_existing'],
  rules: ['filter', 'rename', 'classification', 'path_mappings', 'path_mapping_enabled'],
  services: ['kikoeru_server', 'asmr_sync', 'asmr_sync_step', 'rj_subtitle'],
  maintenance: ['password_cleanup', 'archive_cleanup', 'backup_zip']
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
  background:
    radial-gradient(circle at top left, rgba(191, 219, 254, 0.28), transparent 28%),
    radial-gradient(circle at top right, rgba(226, 232, 240, 0.42), transparent 30%),
    linear-gradient(180deg, #f8fafc, #f1f5f9 48%, #eef2f7);
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
</style>
