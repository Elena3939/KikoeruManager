<template>
  <div class="settings">
    <div class="page-header">
      <h1 class="page-title">设置</h1>
      <el-button 
        type="success" 
        size="small" 
        @click="reloadConfigFromServer"
        :loading="reloading"
        title="从配置文件重新加载"
      >
        <el-icon><Refresh /></el-icon> 从配置文件刷新
      </el-button>
    </div>
    
    <el-form :model="config" label-position="top" v-loading="loading">
      <!-- 可折叠面板容器 -->
      <el-collapse accordion>
        <!-- 存储路径设置 -->
        <el-collapse-item name="storage">
          <template #title>
            <span class="collapse-title">存储路径</span>
          </template>
          <el-card class="setting-card">
        
            <el-alert
              title="提示：请输入完整的绝对路径，例如 D:\\MyFiles\\Input 或 /home/user/input"
              type="info"
              :closable="false"
              style="margin-bottom: 20px;"
            />
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="待处理文件夹">
                  <el-input 
                    v-model="config.storage.input_path" 
                    placeholder="例如：D:\\prekikoeru\\test_data\\input"
                  >
                    <template #prefix>
                      <el-icon><Folder /></el-icon>
                    </template>
                  </el-input>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="临时文件夹">
                  <el-input 
                    v-model="config.storage.temp_path" 
                    placeholder="例如：D:\\prekikoeru\\test_data\\temp"
                  >
                    <template #prefix>
                      <el-icon><Folder /></el-icon>
                    </template>
                  </el-input>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="库存文件夹">
                  <el-input 
                    v-model="config.storage.library_path" 
                    placeholder="例如：D:\\prekikoeru\\test_data\\library"
                  >
                    <template #prefix>
                      <el-icon><Folder /></el-icon>
                    </template>
                  </el-input>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="已处理压缩包存放文件夹">
                  <el-input 
                    v-model="config.storage.processed_archives_path" 
                    placeholder="例如：D:\\prekikoeru\\test_data\\processed"
                  >
                    <template #prefix>
                      <el-icon><Folder /></el-icon>
                    </template>
                  </el-input>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="已存在文件夹目录">
                  <el-input 
                    v-model="config.storage.existing_folders_path" 
                    placeholder="例如：D:\\prekikoeru\\test_data\\existing"
                  >
                    <template #prefix>
                      <el-icon><Folder /></el-icon>
                    </template>
                  </el-input>
                  <div class="form-tip">
                    存放已解压的文件夹（非软件处理的压缩包），也以 {RJCode} {work_name} 格式命名
                  </div>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="ASMR 字幕文件夹">
                  <el-input
                    v-model="config.storage.asmr_subtitle_path"
                    placeholder="例如：D:\\prekikoeru\\subtitles"
                  >
                    <template #prefix>
                      <el-icon><Folder /></el-icon>
                    </template>
                  </el-input>
                  <div class="form-tip">
                    ASMR 同步下载功能使用的字幕文件夹路径
                  </div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-divider>多库存配置</el-divider>

            <el-alert
              title="这里新增的是多库存配置，不会替换或删除你原来的单库存字段。旧字段仍然保留用于兼容老功能。"
              type="warning"
              :closable="false"
              style="margin-bottom: 16px;"
            />

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="默认浏览库存">
                  <el-select v-model="config.storage.default_library_id" style="width: 100%;">
                    <el-option
                      v-for="library in (config.storage.libraries || []).filter(item => item.enabled)"
                      :key="library.id"
                      :label="`${library.name} (${library.id})`"
                      :value="library.id"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="默认解压目标库存">
                  <el-select v-model="config.storage.default_extract_library_id" style="width: 100%;">
                    <el-option
                      v-for="library in (config.storage.libraries || []).filter(item => item.enabled)"
                      :key="`extract-${library.id}`"
                      :label="`${library.name} (${library.id})`"
                      :value="library.id"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="剩余空间预警阈值（GB）">
                  <el-input-number v-model="config.storage.health_warning_free_gb" :min="0" :step="10" style="width: 100%;" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="统计缓存秒数">
                  <el-input-number v-model="config.storage.stats_cache_ttl_seconds" :min="30" :step="30" style="width: 100%;" />
                </el-form-item>
              </el-col>
            </el-row>

            <div v-for="(library, index) in config.storage.libraries" :key="`${library.id}-${index}`" class="rule-item">
              <el-card shadow="never">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                  <strong>{{ library.name || `库存 ${index + 1}` }}</strong>
                  <el-button type="danger" link size="small" @click="removeStorageLibrary(index)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>

                <el-row :gutter="12">
                  <el-col :span="12">
                    <el-form-item label="浏览起始路径">
                      <el-input
                        v-model="library.browse_path"
                        :placeholder="library.type === 'synology_filestation' ? '例如 /ASMR，留空则从远程根目录开始' : '留空则从库存路径开始'"
                      />
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-row :gutter="12">
                  <el-col :span="8">
                    <el-form-item label="库存 ID">
                      <el-input v-model="library.id" placeholder="例如 local-main" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="库存名称">
                      <el-input v-model="library.name" placeholder="显示名称" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="库存类型">
                      <el-select v-model="library.type" style="width: 100%;" @change="syncRemoteLibraryPath(library)">
                        <el-option label="本地库存" value="local" />
                        <el-option label="群晖 FileStation" value="synology_filestation" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-row :gutter="12">
                  <el-col :span="12">
                    <el-form-item v-if="library.type !== 'synology_filestation'" label="库存路径">
                      <el-input v-model="library.path" placeholder="本地填写目录，远程填写根路径" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="说明">
                      <el-input v-model="library.description" placeholder="可选说明" />
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-row :gutter="12">
                  <el-col :span="8">
                    <el-form-item label="启用">
                      <el-switch v-model="library.enabled" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="允许写入">
                      <el-switch v-model="library.writable" />
                    </el-form-item>
                  </el-col>
                </el-row>

                <template v-if="library.type === 'synology_filestation'">
                  <el-divider>群晖连接参数</el-divider>
                  <el-row :gutter="12">
                    <el-col :span="12">
                      <el-form-item label="群晖地址">
                        <el-input v-model="library.synology.base_url" placeholder="例如 https://nas.example.com:5001" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="远程根目录">
                        <el-input v-model="library.synology.root_path" placeholder="/music/asmr" @input="syncRemoteLibraryPath(library)" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-row :gutter="12">
                    <el-col :span="8">
                      <el-form-item label="用户名">
                        <el-input v-model="library.synology.username" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="密码">
                        <el-input v-model="library.synology.password" type="password" show-password />
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="会话名">
                        <el-input v-model="library.synology.session_name" placeholder="FileStation" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-row :gutter="12">
                    <el-col :span="8">
                      <el-form-item label="OTP 动态码">
                        <el-input v-model="library.synology.otp_code" placeholder="首次验证时填写" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="设备名称">
                        <el-input v-model="library.synology.device_name" :placeholder="library.name || library.id || 'Codex'" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="设备令牌 ID">
                        <el-input v-model="library.synology.device_id" placeholder="测试连接成功后会自动回填" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-row :gutter="12">
                    <el-col :span="8">
                      <el-form-item label="超时（秒）">
                        <el-input-number v-model="library.synology.timeout" :min="5" :step="5" style="width: 100%;" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="记住设备">
                        <el-switch v-model="library.synology.enable_device_token" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="8">
                      <el-form-item label="校验证书">
                        <el-switch v-model="library.synology.verify_ssl" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 8px;">
                    <el-button size="small" type="primary" :loading="testingLibraryId === library.id" @click="testStorageLibrary(library)">测试连接</el-button>
                    <el-link v-if="buildSynologyWebUrl(library)" :href="buildSynologyWebUrl(library)" target="_blank" type="primary">打开群晖目录</el-link>
                  </div>
                  <div class="form-tip">
                    首次测试如果启用了二步验证，请填写当前 OTP 动态码。测试成功后如果回填了“设备令牌 ID”，后续浏览通常就不需要重复输入 OTP。
                  </div>
                </template>
              </el-card>
            </div>

            <div style="display: flex; gap: 8px; margin-bottom: 16px;">
              <el-button type="primary" size="small" @click="addStorageLibrary('local')">
                <el-icon><Plus /></el-icon> 添加本地库存
              </el-button>
              <el-button type="warning" size="small" @click="addStorageLibrary('synology_filestation')">
                <el-icon><Plus /></el-icon> 添加群晖库存
              </el-button>
            </div>

            <el-row>
              <el-col :span="24">
                <el-button type="primary" size="small" @click="createTestDirs">
                  <el-icon><Plus /></el-icon>
                  创建默认测试目录
                </el-button>
              </el-col>
            </el-row>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('storage')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>
        <!-- 监视器设置 -->
        <el-collapse-item name="watcher">
          <template #title>
            <span class="collapse-title">文件夹监视器</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="启用监视器">
              <el-switch v-model="config.watcher.enabled" />
            </el-form-item>
            
            <el-form-item label="扫描间隔（秒）">
              <el-slider v-model="config.watcher.scan_interval" :min="10" :max="300" :step="10" show-input />
            </el-form-item>
            
            <el-form-item label="自动开始处理">
              <el-switch v-model="config.watcher.auto_start" />
            </el-form-item>
            
            <el-form-item label="自动分类">
              <el-switch v-model="config.watcher.auto_classify" />
            </el-form-item>
            
            <el-form-item label="处理后删除原文件">
              <el-switch v-model="config.watcher.delete_after_process" />
            </el-form-item>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('watcher')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>
        
        <!-- 处理设置 -->
        <el-collapse-item name="processing">
          <template #title>
            <span class="collapse-title">处理配置</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="最大并发数">
              <el-slider v-model="config.processing.max_workers" :min="1" :max="10" show-input />
            </el-form-item>
            
            <el-form-item label="自动修复后缀名">
              <el-switch v-model="config.extract.auto_repair_extension" />
            </el-form-item>
            
            <el-form-item label="解压后验证">
              <el-switch v-model="config.extract.verify_after_extract" />
            </el-form-item>
            
            <el-form-item label="自动解压嵌套压缩包">
              <el-switch v-model="config.extract.extract_nested_archives" />
              <div class="form-tip">
                启用后，系统会自动检测并解压嵌套在压缩包内的其他压缩文件
              </div>
            </el-form-item>
            
            <el-form-item label="最大嵌套深度" v-if="config.extract.extract_nested_archives">
              <el-slider 
                v-model="config.extract.max_nested_depth" 
                :min="1" 
                :max="10" 
                :step="1" 
                show-input 
              />
              <div class="form-tip">
                限制嵌套压缩包的解压深度，防止无限循环。建议设置为 3-5 层
              </div>
            </el-form-item>
            
            <el-form-item label="7-Zip 路径">
              <el-input 
                v-model="config.extract.seven_zip_path" 
                placeholder="例如：C:\\Program Files\\7-Zip\\7z.exe"
              >
                <template #prefix>
                  <el-icon><Tools /></el-icon>
                </template>
              </el-input>
              <div class="form-tip">留空或填入"7z"将自动检测，Windows 用户建议填写完整路径</div>
            </el-form-item>
            
            <el-form-item label="默认密码列表">
              <el-select
                v-model="config.extract.password_list"
                multiple
                filterable
                allow-create
                default-first-option
                placeholder="输入密码后按回车添加"
                style="width: 100%"
              />
            </el-form-item>
            
            <el-divider>正常解压缩流程步骤</el-divider>
            
            <el-alert
              title="步骤开关说明"
              type="info"
              :closable="false"
              style="margin-bottom: 15px;"
            >
              <div style="font-size: 12px; line-height: 1.6;">
                <p>• 控制正常解压流程中各步骤的执行</p>
                <p>• 解压后的文件会经过这些步骤依次处理</p>
              </div>
            </el-alert>

            <el-row :gutter="20">
              <el-col :span="6">
                <el-form-item label="预检重复">
                  <el-switch v-model="config.auto_process.check_duplicate" />
                  <div class="form-tip">处理前检查是否已存在</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="解压文件">
                  <el-switch v-model="config.auto_process.extract" />
                  <div class="form-tip">解压压缩包（不建议关闭）</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="获取元数据">
                  <el-switch v-model="config.auto_process.fetch_metadata" />
                  <div class="form-tip">从 DLsite 获取作品信息</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="重命名">
                  <el-switch v-model="config.auto_process.rename" />
                  <div class="form-tip">按模板重命名文件夹</div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="20">
              <el-col :span="6">
                <el-form-item label="文件过滤">
                  <el-switch v-model="config.auto_process.filter" />
                  <div class="form-tip">按规则过滤文件</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="智能分类">
                  <el-switch v-model="config.auto_process.classify" />
                  <div class="form-tip">按规则分类到子目录</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="归档压缩包">
                  <el-switch v-model="config.auto_process.archive" />
                  <div class="form-tip">处理后移动压缩包到指定目录</div>
                </el-form-item>
              </el-col>
            </el-row>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('processing')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>
        
        <!-- 过滤设置 -->
        <el-collapse-item name="filter">
          <template #title>
            <span class="collapse-title">过滤配置</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="过滤文件夹">
              <el-switch v-model="config.filter.filter_dir" />
            </el-form-item>
            
            <el-divider>过滤规则</el-divider>
            
            <el-alert
              title="过滤规则说明"
              type="info"
              :closable="false"
              style="margin-bottom: 15px;"
            >
              <div style="font-size: 12px; line-height: 1.6;">
                <p>• 匹配正则表达式的文件/文件夹将被<strong>删除</strong></p>
                <p>• <strong>目标</strong>：决定删除范围（文件=删单个文件，文件夹=删整个文件夹及内容！）</p>
                <p>• 处理流程：解压 → 重命名 → <strong>过滤</strong> → 扁平化 → 移动到库存</p>
              </div>
            </el-alert>
            
            <el-card shadow="never" style="margin-bottom: 15px; background-color: #f5f7fa;">
              <template #header>
                <span style="font-size: 13px; font-weight: 600;">正则示例</span>
              </template>
              <div style="font-size: 12px;">
                <p style="margin: 5px 0;"><strong>文件示例：</strong></p>
                <ul style="margin: 5px 0; padding-left: 20px;">
                  <li><code>\.mp3$</code> - 删除所有 MP3 文件</li>
                  <li><code>(?i)\.wav$</code> - 删除所有 WAV 文件（不区分大小写）</li>
                  <li><code>^\._</code> - 删除 macOS 隐藏文件（以._开头）</li>
                </ul>
                <p style="margin: 10px 0 5px;"><strong>文件夹示例：</strong></p>
                <ul style="margin: 5px 0; padding-left: 20px;">
                  <li><code>^__MACOSX$</code> - 删除__MACOSX 文件夹</li>
                  <li><code>^temp$</code> - 删除名为 temp 的文件夹</li>
                  <li><code>sample</code> - 删除名称包含 sample 的文件夹</li>
                </ul>
                <p style="margin: 10px 0 5px;"><strong>全部示例：</strong></p>
                <ul style="margin: 5px 0; padding-left: 20px;">
                  <li><code>thumb</code> - 删除所有包含 thumb 的文件和文件夹</li>
                </ul>
              </div>
            </el-card>

            <div v-for="(rule, index) in config.filter.rules" :key="index" class="rule-item">
              <el-card shadow="never">
                <el-row :gutter="10" align="middle">
                  <el-col :span="4">
                    <el-select v-model="rule.target" size="small" placeholder="目标" style="width: 100%;">
                      <el-option label="文件" value="file" />
                      <el-option label="文件夹" value="folder" />
                      <el-option label="全部" value="all" />
                    </el-select>
                  </el-col>
                  <el-col :span="5">
                    <el-input v-model="rule.name" placeholder="规则名称" size="small" />
                  </el-col>
                  <el-col :span="9">
                    <el-input v-model="rule.pattern" placeholder="正则表达式" size="small" />
                  </el-col>
                  <el-col :span="3">
                    <el-switch v-model="rule.enabled" size="small" />
                  </el-col>
                  <el-col :span="3" style="text-align: right;">
                    <el-button type="danger" link size="small" @click="removeFilterRule(index)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </el-col>
                </el-row>
                <el-row v-if="rule.pattern" style="margin-top: 5px;">
                  <el-col :span="24">
                    <span class="form-tip">
                      将删除{{ getTargetLabel(rule.target) }}名称匹配 "{{ rule.pattern }}" 的内容
                      <span v-if="rule.target === 'folder'" style="color: #f56c6c; margin-left: 8px;">
                        <el-icon><Warning /></el-icon> 注意：会删除整个文件夹及其所有内容！
                      </span>
                    </span>
                  </el-col>
                </el-row>
              </el-card>
            </div>

            <el-button type="primary" size="small" @click="addFilterRule" style="margin-top: 10px;">
              <el-icon><Plus /></el-icon> 添加过滤规则
            </el-button>

            <el-divider />

            <el-form-item label="自动扁平化单层文件夹">
              <el-switch v-model="config.rename.flatten_single_subfolder" />
              <div class="form-tip">
                如果文件夹内只有一个子文件夹，自动将内容移出并删除外层空文件夹。<br>
                <strong>注意：</strong>此功能在过滤完成后执行，可以处理因过滤而产生的单层文件夹结构
              </div>
            </el-form-item>

            <el-form-item label="扁平化深度" v-if="config.rename.flatten_single_subfolder">
              <el-input-number v-model="config.rename.flatten_depth" :min="1" :max="10" />
              <div class="form-tip">
                最多处理多少层嵌套的单子文件夹。例如：如果设置为 3，<br>
                主文件夹 → 文件夹 A → 文件夹 B（B 是唯一子文件夹）→ 内容，将被扁平化为主文件夹 → 内容
              </div>
            </el-form-item>

            <el-form-item label="自动移除空文件夹">
              <el-switch v-model="config.rename.remove_empty_folders" />
              <div class="form-tip">
                过滤完成后自动移除所有空文件夹（不包括根文件夹）<br>
                <strong>注意：</strong>此功能在扁平化之后执行，可以清理因过滤而产生的空文件夹
              </div>
            </el-form-item>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('filter')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>

        <!-- 元数据设置 -->
        <el-collapse-item name="metadata">
          <template #title>
            <span class="collapse-title">元数据配置</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="语言区域">
              <el-select v-model="config.metadata.locale" style="width: 200px">
                <el-option label="简体中文" value="zh_cn" />
                <el-option label="繁体中文" value="zh_tw" />
                <el-option label="日本語" value="ja_jp" />
                <el-option label="English" value="en_us" />
              </el-select>
            </el-form-item>

            <el-form-item label="启用缓存">
              <el-switch v-model="config.metadata.cache_enabled" />
            </el-form-item>

            <el-form-item label="下载封面">
              <el-switch v-model="config.metadata.fetch_cover" />
            </el-form-item>

            <el-form-item label="制作文件夹图标">
              <el-switch v-model="config.metadata.make_folder_icon" />
            </el-form-item>

            <el-form-item label="HTTP 代理">
              <el-input v-model="config.metadata.http_proxy" placeholder="127.0.0.1:7890" />
            </el-form-item>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('metadata')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>

        <!-- 重命名设置 -->
        <el-collapse-item name="rename">
          <template #title>
            <span class="collapse-title">重命名配置</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="重命名模板">
              <el-input v-model="config.rename.template" placeholder="{rjcode} {work_name}">
                <template #append>
                  <el-tooltip content="可用变量：{rjcode}, {work_name}, {maker_name}, {cvs}, {release_date}, {tags}">
                    <el-icon><QuestionFilled /></el-icon>
                  </el-tooltip>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item label="日期格式">
              <el-input v-model="config.rename.date_format" placeholder="%y%m%d" style="width: 200px" />
            </el-form-item>

            <el-form-item label="移除方括号内容">
              <el-switch v-model="config.rename.exclude_square_brackets" />
            </el-form-item>

            <el-form-item label="非法字符转全角">
              <el-switch v-model="config.rename.illegal_char_to_full_width" />
            </el-form-item>

            <el-form-item label="API 重命名遵循模板">
              <el-switch v-model="config.rename.api_rename_follow_template" />
              <div class="form-tip">
                开启后，库存管理中的"API 重命名"将使用上方的重命名模板；关闭则使用简单格式"RJ 号 作品名"
              </div>
            </el-form-item>

            <el-form-item label="使用日语元数据">
              <el-switch v-model="config.rename.use_japanese_metadata" />
              <div class="form-tip">
                开启后，重命名模板中的 {maker_name}、{cvs}、{tags} 等字段将使用日语版本的元数据，而 {rjcode} 和 {work_name} 仍使用当前语言的元数据。适用于非日语版本元数据不准确的情况
              </div>
            </el-form-item>
            
            <el-divider>已有文件夹处理流程步骤</el-divider>
            
            <el-alert
              title="步骤开关说明"
              type="info"
              :closable="false"
              style="margin-bottom: 15px;"
            >
              <div style="font-size: 12px; line-height: 1.6;">
                <p>• 控制已有文件夹处理流程中各步骤的执行</p>
                <p>• 用于处理已解压但未整理的文件夹</p>
                <p>• <strong>注意：</strong>LRC 广告清理和繁简转换在"ASMR 同步下载"配置中设置</p>
              </div>
            </el-alert>

            <el-row :gutter="20">
              <el-col :span="6">
                <el-form-item label="预检重复">
                  <el-switch v-model="config.process_existing.check_duplicate" />
                  <div class="form-tip">处理前检查是否已存在</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="获取元数据">
                  <el-switch v-model="config.process_existing.fetch_metadata" />
                  <div class="form-tip">从 DLsite 获取作品信息</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="重命名">
                  <el-switch v-model="config.process_existing.rename" />
                  <div class="form-tip">按模板重命名文件夹</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="文件过滤">
                  <el-switch v-model="config.process_existing.filter" />
                  <div class="form-tip">按规则过滤文件</div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="20">
              <el-col :span="6">
                <el-form-item label="导入 LRC">
                  <el-switch v-model="config.process_existing.import_lrc" />
                  <div class="form-tip">从字幕文件夹导入 LRC 文件</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="智能分类">
                  <el-switch v-model="config.process_existing.classify" />
                  <div class="form-tip">按规则分类到子目录</div>
                </el-form-item>
              </el-col>
            </el-row>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('rename')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>

        <!-- 密码库智能清理 -->
        <el-collapse-item name="passwordCleanup">
          <template #title>
            <span class="collapse-title">密码库智能清理</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="启用自动清理">
              <el-switch v-model="config.password_cleanup.enabled" />
              <span style="margin-left: 10px; color: #606266;">启用后系统将按计划自动清理密码库</span>
            </el-form-item>

            <el-alert
              title="清理说明"
              type="info"
              :closable="false"
              style="margin-bottom: 15px;"
            >
              <div style="font-size: 12px; line-height: 1.6;">
                <p>• 系统会自动清理使用次数较少的密码，避免密码库无限膨胀</p>
                <p>• <strong>使用次数阈值</strong>：使用次数 ≤ 此值的密码将被清理</p>
                <p>• <strong>保留天数</strong>：密码创建超过此天数且使用次数 ≤ 阈值才删除</p>
                <p>• 可以使用 Cron 表达式自定义执行时间</p>
              </div>
            </el-alert>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="使用次数阈值">
                  <el-slider
                    v-model="config.password_cleanup.max_use_count"
                    :min="0"
                    :max="10"
                    :step="1"
                    show-input
                    :disabled="!config.password_cleanup.enabled"
                  />
                  <div class="form-tip">
                    使用次数 ≤ {{ config.password_cleanup.max_use_count }} 的密码将被清理
                  </div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="保留天数">
                  <el-slider
                    v-model="config.password_cleanup.preserve_days"
                    :min="1"
                    :max="90"
                    :step="1"
                    show-input
                    :disabled="!config.password_cleanup.enabled"
                  />
                  <div class="form-tip">
                    密码创建后超过 {{ config.password_cleanup.preserve_days }} 天且使用次数 ≤ 阈值才删除
                  </div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="Cron 表达式">
              <el-input
                v-model="config.password_cleanup.cron_expression"
                placeholder="例如：0 0 * * 0"
                :disabled="!config.password_cleanup.enabled"
                style="width: 300px"
              >
                <template #append>
                  <el-tooltip content="Cron 格式：分 时 日 月 周。默认 0 0 * * 0 表示每周日午夜">
                    <el-icon><QuestionFilled /></el-icon>
                  </el-tooltip>
                </template>
              </el-input>
              <div class="form-tip">
                示例：0 0 * * 0（每周日午夜）、0 2 * * *（每天凌晨 2 点）、0 0 1 * *（每月 1 号）
              </div>
            </el-form-item>

            <el-form-item label="排除来源">
              <el-select
                v-model="config.password_cleanup.exclude_sources"
                multiple
                placeholder="选择要排除的密码来源"
                :disabled="!config.password_cleanup.enabled"
                style="width: 100%"
              >
                <el-option label="手动添加 (manual)" value="manual" />
                <el-option label="批量导入 (batch)" value="batch" />
                <el-option label="自动提取 (auto)" value="auto" />
              </el-select>
              <div class="form-tip">
                选中的来源类型的密码不会被清理
              </div>
            </el-form-item>

            <el-divider />

            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
              <el-button
                type="primary"
                size="small"
                @click="previewPasswordCleanup"
                :disabled="!config.password_cleanup.enabled"
              >
                <el-icon><View /></el-icon> 预览清理结果
              </el-button>
              <el-button
                type="success"
                size="small"
                @click="runPasswordCleanup"
                :disabled="!config.password_cleanup.enabled"
              >
                <el-icon><Check /></el-icon> 立即执行清理
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>

        <!-- 已处理压缩包智能清理 -->
        <el-collapse-item name="archiveCleanup">
          <template #title>
            <span class="collapse-title">已处理压缩包智能清理</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="启用自动清理">
              <el-switch v-model="config.archive_cleanup.enabled" />
              <span style="margin-left: 10px; color: #606266;">启用后系统将按计划自动清理已处理的压缩包</span>
            </el-form-item>

            <el-alert
              title="清理说明"
              type="info"
              :closable="false"
              style="margin-bottom: 15px;"
            >
              <div style="font-size: 12px; line-height: 1.6;">
                <p>• 系统会自动清理已处理完成的压缩包，释放磁盘空间</p>
                <p>• <strong>保留天数</strong>：压缩包处理完成后保留的天数</p>
                <p>• <strong>最小保留数量</strong>：无论保留天数如何，至少保留最近的 N 个压缩包</p>
                <p>• 可以使用 Cron 表达式自定义执行时间</p>
              </div>
            </el-alert>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="保留天数">
                  <el-slider
                    v-model="config.archive_cleanup.preserve_days"
                    :min="1"
                    :max="90"
                    :step="1"
                    show-input
                    :disabled="!config.archive_cleanup.enabled"
                  />
                  <div class="form-tip">
                    处理完成超过 {{ config.archive_cleanup.preserve_days }} 天的压缩包将被清理
                  </div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="最小保留数量">
                  <el-input-number
                    v-model="config.archive_cleanup.min_keep_count"
                    :min="0"
                    :max="100"
                    :step="1"
                    :disabled="!config.archive_cleanup.enabled"
                  />
                  <div class="form-tip">
                    至少保留最近 {{ config.archive_cleanup.min_keep_count }} 个已处理的压缩包
                  </div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="Cron 表达式">
              <el-input
                v-model="config.archive_cleanup.cron_expression"
                placeholder="例如：0 0 * * 0"
                :disabled="!config.archive_cleanup.enabled"
                style="width: 300px"
              >
                <template #append>
                  <el-tooltip content="Cron 格式：分 时 日 月 周。默认 0 0 * * 0 表示每周日午夜">
                    <el-icon><QuestionFilled /></el-icon>
                  </el-tooltip>
                </template>
              </el-input>
              <div class="form-tip">
                示例：0 0 * * 0（每周日午夜）、0 2 * * *（每天凌晨 2 点）、0 0 1 * *（每月 1 号）
              </div>
            </el-form-item>

            <el-divider />

            <div style="display: flex; gap: 10px; flex-wrap: wrap;">
              <el-button
                type="primary"
                size="small"
                @click="previewArchiveCleanup"
                :disabled="!config.archive_cleanup.enabled"
              >
                <el-icon><View /></el-icon> 预览清理结果
              </el-button>
              <el-button
                type="success"
                size="small"
                @click="runArchiveCleanup"
                :disabled="!config.archive_cleanup.enabled"
              >
                <el-icon><Check /></el-icon> 立即执行清理
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>

        <!-- 路径映射设置 -->
        <el-collapse-item name="pathMapping">
          <template #title>
            <span class="collapse-title">路径映射（跨设备访问）</span>
          </template>
          <el-card class="setting-card">
        
            <el-alert
              title="路径映射说明"
              type="info"
              :closable="false"
              style="margin-bottom: 15px;"
            >
              <div style="font-size: 12px; line-height: 1.6;">
                <p>• 用于在不同设备间转换路径，例如 Windows 路径转换为 Linux 路径</p>
                <p>• <strong>原始路径</strong>：系统中存储的实际路径</p>
                <p>• <strong>映射路径</strong>：在其他设备中访问时使用的路径</p>
                <p>• 系统会根据映射规则自动转换路径</p>
              </div>
            </el-alert>

            <div v-for="(mapping, index) in config.path_mappings" :key="index" class="rule-item">
              <el-card shadow="never">
                <el-row :gutter="10" align="middle">
                  <el-col :span="10">
                    <el-input 
                      v-model="mapping.original" 
                      placeholder="原始路径，如 D:\\Library" 
                      size="small"
                    >
                      <template #prepend>原始路径</template>
                    </el-input>
                  </el-col>
                  <el-col :span="10">
                    <el-input 
                      v-model="mapping.mapped" 
                      placeholder="映射路径，如 /mnt/library" 
                      size="small"
                    >
                      <template #prepend>映射路径</template>
                    </el-input>
                  </el-col>
                  <el-col :span="4" style="text-align: right;">
                    <el-button type="danger" link size="small" @click="removePathMapping(index)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </el-col>
                </el-row>
              </el-card>
            </div>

            <el-button type="primary" size="small" @click="addPathMapping" style="margin-top: 10px;">
              <el-icon><Plus /></el-icon> 添加映射规则
            </el-button>

            <el-divider />

            <el-form-item label="启用路径映射">
              <el-switch v-model="config.path_mapping_enabled" />
            </el-form-item>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('pathMapping')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>

        <!-- Kikoeru 服务器查重 -->
        <el-collapse-item name="kikoeruServer">
          <template #title>
            <span class="collapse-title">Kikoeru 服务器查重</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="启用 Kikoeru 服务器查重">
              <el-switch v-model="config.kikoeru_server.enabled" />
            </el-form-item>

            <el-form-item label="服务器地址">
              <el-input
                v-model="config.kikoeru_server.server_url"
                placeholder="例如: http://192.168.1.100:8088"
                :disabled="!config.kikoeru_server.enabled"
              >
                <template #prefix>
                  <el-icon><Link /></el-icon>
                </template>
              </el-input>
              <div class="form-tip">Kikoeru 服务器的完整 URL 地址</div>
            </el-form-item>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="用户名">
                  <el-input
                    v-model="config.kikoeru_server.username"
                    placeholder="登录用户名"
                    :disabled="!config.kikoeru_server.enabled"
                  />
                  <div class="form-tip">Kikoeru 登录用户名</div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="密码">
                  <el-input
                    v-model="config.kikoeru_server.password"
                    placeholder="登录密码"
                    type="password"
                    show-password
                    :disabled="!config.kikoeru_server.enabled"
                  />
                  <div class="form-tip">Kikoeru 登录密码</div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="请求超时（秒）">
                  <el-input-number
                    v-model="config.kikoeru_server.timeout"
                    :min="1"
                    :max="60"
                    :disabled="!config.kikoeru_server.enabled"
                    style="width: 100%;"
                  />
                  <div class="form-tip">查询请求的超时时间</div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="缓存时间（秒）">
                  <el-input-number
                    v-model="config.kikoeru_server.cache_ttl"
                    :min="0"
                    :max="3600"
                    :disabled="!config.kikoeru_server.enabled"
                    style="width: 100%;"
                  />
                  <div class="form-tip">查询结果的缓存时间</div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="HTTP 代理">
                  <el-input
                    v-model="config.kikoeru_server.http_proxy"
                    placeholder="远程服务器连接不使用代理，此配置已禁用"
                    :disabled="true"
                    clearable
                  />
                  <div class="form-tip">远程 Kikoeru 服务器连接使用直连模式，不通过代理</div></el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="重试次数">
                  <el-input-number
                    v-model="config.kikoeru_server.retry_count"
                    :min="1"
                    :max="10"
                    :disabled="!config.kikoeru_server.enabled"
                    style="width: 100%;"
                  />
                  <div class="form-tip">网络请求失败时的重试次数</div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="预检查重">
              <el-switch
                v-model="config.kikoeru_server.check_in_preextract"
                :disabled="!config.kikoeru_server.enabled"
              />
              <span style="margin-left: 10px; color: #606266;">在解压预检中启用远程查重</span>
            </el-form-item>

            <el-divider />

            <el-form-item label="测试连接">
              <div style="display: flex; gap: 10px;">
                <el-button
                  type="primary"
                  size="small"
                  @click="getKikoeruToken"
                  :loading="gettingToken"
                  :disabled="!config.kikoeru_server.enabled || !config.kikoeru_server.server_url || !config.kikoeru_server.username"
                >
                  <el-icon><Key /></el-icon> 获取 Token
                </el-button>
                <el-button
                  type="success"
                  size="small"
                  @click="testKikoeruConnection"
                  :loading="testingKikoeru"
                  :disabled="!config.kikoeru_server.enabled || !config.kikoeru_server.server_url"
                >
                  <el-icon><Connection /></el-icon> 测试连接
                </el-button>
              </div>
            </el-form-item>

            <el-form-item label="测试查重">
              <div style="display: flex; gap: 10px; width: 100%;">
                <el-input
                  v-model="kikoeruTestRj"
                  placeholder="输入 RJ号进行测试，例如: RJ123456"
                  :disabled="!config.kikoeru_server.enabled"
                  style="flex: 1;"
                />
                <el-button
                  type="primary"
                  size="small"
                  @click="testKikoeruDuplicate"
                  :loading="testingDuplicate"
                  :disabled="!config.kikoeru_server.enabled || !kikoeruTestRj"
                >
                  <el-icon><Search /></el-icon> 测试查重
                </el-button>
              </div>
            </el-form-item>

            <el-alert
              type="info"
              :closable="false"
              style="margin-top: 15px;"
            >
              <template #title>
                <span style="font-weight: 600;">关于 Kikoeru 服务器查重</span>
              </template>
              <div style="font-size: 12px; line-height: 1.8;">
                <p>• 启用后，系统在查重时会同时查询本地库和远程 Kikoeru 服务器。</p>
                <p>• 适用于多个设备/服务器共享同一个 Kikoeru 库的场景。</p>
                <p>• 配置用户名和密码后，系统会自动获取 Token，Token 过期后会自动重新获取。</p>
                <p>• 支持的 URL 格式: http://ip:port 或 https://domain</p>
              </div>
            </el-alert>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('kikoeruServer')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>

        <!-- ASMR 同步下载 -->
        <el-collapse-item name="asmrSync">
          <template #title>
            <span class="collapse-title">ASMR 同步下载</span>
          </template>
          <el-card class="setting-card">
        
            <el-form-item label="启用 ASMR 同步下载">
              <el-switch v-model="config.asmr_sync.enabled" />
              <span style="margin-left: 10px; color: #606266;">启用后可以自动从 asmr.one 下载音频文件</span>
            </el-form-item>

            <el-row :gutter="20">
              <el-col :span="8">
                <el-form-item label="重试Cron">
                  <el-input
                    v-model="config.asmr_sync.retry_cron"
                    placeholder="0 */1 * * *"
                    :disabled="!config.asmr_sync.enabled"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="并发下载数">
                  <el-input-number
                    v-model="config.asmr_sync.max_concurrent_downloads"
                    :min="1"
                    :max="10"
                    style="width: 100%;"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="最大重试次数">
                  <el-input-number
                    v-model="config.asmr_sync.max_retry_count"
                    :min="1"
                    :max="100"
                    style="width: 100%;"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <div class="form-tip" style="margin-top: -10px; margin-bottom: 15px;">
              达到最大次数后任务将标记为失败
            </div>

            <el-form-item label="HTTP代理">
              <el-input
                v-model="config.asmr_sync.http_proxy"
                placeholder="127.0.0.1:7890"
              />
              <div class="form-tip">可选，用于访问 asmr.one</div>
            </el-form-item>

            <el-divider> LRC 广告清理 </el-divider>

            <el-form-item label="启用广告清理">
              <el-switch v-model="config.asmr_sync.lrc_clean_enabled" />
            </el-form-item>

            <el-form-item label="清理规则" v-if="config.asmr_sync.lrc_clean_enabled">
              <el-input
                v-model="newLrcPattern"
                placeholder="输入正则表达式，如 @[\w]{3,}"
                @keyup.enter="addLrcPattern"
                style="margin-bottom: 10px;"
              >
                <template #append>
                  <el-button @click="addLrcPattern">添加</el-button>
                </template>
              </el-input>
              
              <div class="pattern-list">
                <el-tag
                  v-for="(pattern, index) in config.asmr_sync.lrc_clean_patterns"
                  :key="index"
                  closable
                  @close="removeLrcPattern(index)"
                  style="margin-right: 8px; margin-bottom: 8px;"
                >
                  {{ pattern }}
                </el-tag>
              </div>
            </el-form-item>

            <el-card shadow="never" style="margin-bottom: 15px; background-color: #f5f7fa;" v-if="config.asmr_sync.lrc_clean_enabled">
              <template #header>
                <span style="font-size: 13px; font-weight: 600;">正则示例</span>
              </template>
              <div style="font-size: 12px;">
                <p style="margin: 5px 0;"><code>@[\w]{3,}.*</code> → 匹配 Telegram 账号名（如 @Telegram账号）</p>
                <p style="margin: 5px 0;"><code>Telegram</code> → 匹配关键词 "Telegram"</p>
                <p style="margin: 5px 0;"><code>QQ群[：:]\s*\d+</code> → 匹配 QQ 群号</p>
              </div>
            </el-card>

            <el-divider />

            <el-form-item label="字幕繁体转简体">
              <el-switch v-model="config.asmr_sync.simplify_chinese_enabled" />
              <div class="form-tip">启用后，系统会自动将字幕中的繁体中文转换为简体中文</div>
            </el-form-item>
            
            <el-divider>ASMR 同步下载流程步骤</el-divider>
            
            <el-alert
              title="步骤开关说明"
              type="info"
              :closable="false"
              style="margin-bottom: 15px;"
            >
              <div style="font-size: 12px; line-height: 1.6;">
                <p>• 控制 ASMR 同步下载流程中各步骤的执行</p>
                <p>• <strong>注意：</strong>LRC 广告清理和繁简转换已在上方配置</p>
              </div>
            </el-alert>

            <el-row :gutter="20">
              <el-col :span="6">
                <el-form-item label="下载文件">
                  <el-switch v-model="config.asmr_sync_step.download" :disabled="!config.asmr_sync.enabled" />
                  <div class="form-tip">从 asmr.one 下载音频文件</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="同步字幕">
                  <el-switch v-model="config.asmr_sync_step.sync_subtitle" :disabled="!config.asmr_sync.enabled" />
                  <div class="form-tip">将 LRC 字幕同步到下载目录</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="重命名">
                  <el-switch v-model="config.asmr_sync_step.rename" :disabled="!config.asmr_sync.enabled" />
                  <div class="form-tip">按模板重命名文件夹</div>
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="智能分类">
                  <el-switch v-model="config.asmr_sync_step.classify" :disabled="!config.asmr_sync.enabled" />
                  <div class="form-tip">按规则分类到子目录</div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-row :gutter="20">
              <el-col :span="6">
                <el-form-item label="移动字幕文件夹">
                  <el-switch v-model="config.asmr_sync_step.move_subtitle_folder" :disabled="!config.asmr_sync.enabled" />
                  <div class="form-tip">完成后移动字幕文件夹到 Finished 目录</div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-alert
              type="info"
              :closable="false"
              style="margin-top: 15px;"
            >
              <template #title>
                <span style="font-weight: 600;">关于 ASMR 同步下载</span>
              </template>
              <div style="font-size: 12px; line-height: 1.8;">
                <p>• ASMR 同步功能会根据字幕文件自动从 asmr.one 下载对应的音频文件。</p>
                <p>• 当作品在 asmr.one 上找不到时，任务会进入"等待重试"状态，系统会根据 Cron 表达式定期重试。</p>
              </div>
            </el-alert>
          </el-card>
        </el-collapse-item>

        <!-- 分类规则 -->
        <el-collapse-item name="classification">
          <template #title>
            <span class="collapse-title">分类规则</span>
          </template>
          <el-card class="setting-card">
        
            <el-alert
              title="分类规则说明"
              type="info"
              :closable="false"
              style="margin-bottom: 20px;"
            >
              <div style="font-size: 12px; line-height: 1.6;">
                <p>• <strong>无</strong>：作品直接存入库存根目录</p>
                <p>• <strong>社团</strong>：按社团名称分类，可使用 {maker_name} 变量</p>
                <p>• <strong>RJ 号范围</strong>：按 RJ 号范围分类，需设置范围和目录名称</p>
                <p>• <strong>系列</strong>：按系列名称分类，可使用 {series_name} 变量</p>
              </div>
            </el-alert>

            <div v-for="(rule, index) in config.classification" :key="index" class="rule-item">
              <el-card shadow="never">
                <!-- 基础路径显示 -->
                <div class="base-path-display" style="margin-bottom: 15px;">
                  <span class="path-label">库存基础路径：</span>
                  <span class="path-value">{{ config.storage.library_path }}\</span>
                </div>

                <!-- 分类类型和配置在同一行 -->
                <div class="classification-row">
                  <div class="classification-type">
                    <el-select v-model="rule.type" placeholder="子目录类别" @change="onRuleTypeChange(rule)" style="width: 100%;">
                      <el-option label="无" value="none" />
                      <el-option label="社团" value="maker" />
                      <el-option label="RJ 号范围" value="rjcode" />
                      <el-option label="系列" value="series" />
                    </el-select>
                  </div>

                  <!-- 不同分类类型的子目录输入 -->
                  <div class="classification-input" v-if="rule.type === 'none'">
                    <el-input disabled placeholder="无子目录" />
                    <div class="form-tip">作品将直接存入库存根目录</div>
                  </div>

                  <div class="classification-input" v-else-if="rule.type === 'maker'">
                    <el-input v-model="rule.path_template" placeholder="子目录名称，留空使用社团名">
                      <template #append>
                        <el-tooltip content="使用 {maker_name} 自动替换为社团名称">
                          <el-icon><QuestionFilled /></el-icon>
                        </el-tooltip>
                      </template>
                    </el-input>
                    <div class="form-tip">使用 {maker_name} 变量或自定义名称</div>
                  </div>

                  <div class="classification-input" v-else-if="rule.type === 'rjcode'">
                    <el-input v-model="rule.custom_name" placeholder="目录名称，如：RJ011 系列">
                      <template #prepend>目录名</template>
                    </el-input>
                    <div class="form-tip">设置此 RJ 号范围的目录显示名称</div>
                  </div>

                  <div class="classification-input" v-else-if="rule.type === 'series'">
                    <el-input v-model="rule.path_template" placeholder="子目录名称，留空使用系列名">
                      <template #append>
                        <el-tooltip content="使用 {series_name} 自动替换为系列名称">
                          <el-icon><QuestionFilled /></el-icon>
                        </el-tooltip>
                      </template>
                    </el-input>
                    <div class="form-tip">使用 {series_name} 变量或自定义名称</div>
                  </div>

                  <div class="classification-actions">
                    <el-switch v-model="rule.enabled" active-text="启用" />
                    <el-button type="danger" link @click="removeRule(index)" style="margin-left: 10px;">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                </div>

                <!-- RJ 号范围详细设置 -->
                <div v-if="rule.type === 'rjcode'" class="rjcode-config">
                  <el-card shadow="never" size="small">
                    <template #header>
                      <span style="font-size: 12px;">RJ 号范围配置</span>
                    </template>
                    <el-input
                      v-model="rule.rjcode_range"
                      placeholder="例如：RJ01100000-RJ01199999"
                      size="small"
                    >
                      <template #prepend>RJ 号范围</template>
                    </el-input>
                    <div class="form-tip">格式：RJ01100000-RJ01199999</div>
                  </el-card>
                </div>

                <!-- 路径预览 -->
                <div class="path-preview">
                  <span class="preview-label">路径预览：</span>
                  <span class="preview-value">{{ getPathPreview(rule) }}</span>
                </div>
              </el-card>
            </div>

            <div style="margin-top: 15px;">
              <el-button type="primary" size="small" @click="addRule">
                <el-icon><Plus /></el-icon> 添加规则
              </el-button>
            </div>
            
            <!-- 操作按钮 -->
            <div class="card-actions">
              <el-button type="primary" size="small" @click="saveConfig">
                <el-icon><Check /></el-icon> 保存
              </el-button>
              <el-button size="small" @click="resetSection('classification')">
                <el-icon><RefreshLeft /></el-icon> 重置
              </el-button>
            </div>
          </el-card>
        </el-collapse-item>
      </el-collapse>

      <!-- 保存按钮 -->
      <div class="actions">
        <el-button type="primary" size="large" @click="saveConfig">
          <el-icon><Check /></el-icon> 保存配置
        </el-button>
        <el-button size="large" @click="resetConfig">重置</el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Folder, FolderOpened, Plus, Delete, Check, QuestionFilled, Tools, Warning, View, ArrowRight, Document, Connection, Key, Link, Search, User, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useConfigStore } from '../stores'
import { configApi, kikoeruApi, pathMappingApi, cleanupApi, libraryApi } from '../api'

const configStore = useConfigStore()
const loading = ref(false)
const testingLibraryId = ref('')

function createDefaultLibrary(type = 'local', index = 1) {
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

function normalizeLibraryConfig(library, index = 1) {
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
    normalized.synology.device_name = normalized.synology.device_name || normalized.name || normalized.id
  }
  return normalized
}

const defaultConfig = {
  storage: {
    input_path: '/input',
    temp_path: '/temp',
    library_path: '/library',
    processed_archives_path: '/processed',
    existing_folders_path: '/existing',
    asmr_subtitle_path: '',
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
    extract_nested_archives: true,
    max_nested_depth: 5
  },
  filter: {
    enabled: true,
    filter_dir: true,
    rules: [
      {
        name: '过滤无 SE 的文件',
        pattern: '(?:SE|音 | 音效)(?:[な無] し|CUT)|(?:無 | なし)(?:SE|音 | 音效)',
        target: 'file',
        action: 'exclude',
        enabled: true
      },
      {
        name: '过滤无 SE 的文件夹',
        pattern: '(?:SE|音 | 音效)(?:[な無] し|CUT)|(?:無 | なし)(?:SE|音 | 音效)',
        target: 'folder',
        action: 'exclude',
        enabled: true
      },
      {
        name: '过滤 MP3 文件',
        pattern: '\.mp3$',
        target: 'file',
        action: 'exclude',
        enabled: false
      }
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
  // Kikoeru 服务器查重配置
  kikoeru_server: {
    enabled: false,
    server_url: '',
    username: '',
    password: '',
    api_token: '',
    token_expires: 0,
    timeout: 10,
    cache_ttl: 300,
    http_proxy: '',
    check_in_preextract: true,
    retry_count: 3,
    retry_delay: 1.0
  },
  // ASMR 同步下载配置
  asmr_sync: {
    enabled: true,
    api_base_url: 'https://api.asmr-200.com/api',
    max_concurrent_downloads: 3,
    http_proxy: '',
    retry_interval_hours: 1.0,
    max_retry_count: 10,
    retry_cron: '0 */1 * * *',
    retry_count: 3,
    retry_delay: 5,
    lrc_clean_enabled: true,
    lrc_clean_patterns: [
      '@[\\w]{3,}',
      'Telegram',
      'telegram',
      '电报',
      'tg群',
      'TG群',
      'QQ群[：:]\\s*\\d+',
      '群号[：:]\\s*\\d+'
    ],
    simplify_chinese_enabled: true
  },
  // 正常解压缩流程步骤配置
  auto_process: {
    check_duplicate: true,
    extract: true,
    fetch_metadata: true,
    rename: true,
    filter: true,
    classify: true,
    archive: true
  },
  // 已有文件夹处理流程步骤配置
  process_existing: {
    check_duplicate: true,
    fetch_metadata: true,
    rename: true,
    filter: true,
    import_lrc: true,
    classify: true
  },
  // ASMR 同步下载流程步骤配置
  asmr_sync_step: {
    download: true,
    sync_subtitle: true,
    rename: true,
    classify: true,
    move_subtitle_folder: true
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

const config = ref({ ...defaultConfig })
const reloading = ref(false)

/**
 * 从服务器重新加载配置文件
 */
async function reloadConfigFromServer() {
  try {
    reloading.value = true
    console.log('[Settings] 开始重新加载配置...')
    
    const reloadResult = await configApi.reload()
    console.log('[Settings] 后端重载结果:', reloadResult)
    
    // 重新加载配置到前端
    await loadConfig()
    
    console.log('[Settings] 配置重新加载完成，当前 storage:', config.value.storage)
    ElMessage.success('配置已从配置文件重新加载')
  } catch (error) {
    console.error('重新加载配置失败:', error)
    ElMessage.error('重新加载配置失败：' + (error.response?.data?.detail || error.message))
  } finally {
    reloading.value = false
  }
}

async function loadConfig() {
  try {
    loading.value = true
    const data = await configStore.fetchConfig()
    
    console.log('从后端获取的原始配置:', data)
    console.log('存储路径配置:', data?.storage)
    
    // 深度合并配置，确保嵌套对象正确合并
    // 注意：不要在顶层展开 defaultConfig 和 data，否则嵌套对象会被覆盖
    config.value = {
      // 存储路径配置（深度合并）
      storage: {
        ...defaultConfig.storage,
        ...(data?.storage || {}),
        libraries: (data?.storage?.libraries || defaultConfig.storage.libraries).map((library, index) => normalizeLibraryConfig(library, index + 1)),
        default_library_id: data?.storage?.default_library_id || '',
        default_extract_library_id: data?.storage?.default_extract_library_id || '',
        health_warning_free_gb: data?.storage?.health_warning_free_gb ?? defaultConfig.storage.health_warning_free_gb,
        stats_cache_ttl_seconds: data?.storage?.stats_cache_ttl_seconds ?? defaultConfig.storage.stats_cache_ttl_seconds
      },
      // 处理配置（深度合并）
      processing: {
        ...defaultConfig.processing,
        ...(data?.processing || {})
      },
      // 监视器配置（深度合并）
      watcher: {
        ...defaultConfig.watcher,
        ...(data?.watcher || {})
      },
      // 解压配置（深度合并）
      extract: {
        ...defaultConfig.extract,
        ...(data?.extract || {})
      },
      // 过滤配置（深度合并）
      filter: {
        ...defaultConfig.filter,
        ...(data?.filter || {}),
        rules: data?.filter?.rules || defaultConfig.filter.rules
      },
      // 元数据配置（深度合并）
      metadata: {
        ...defaultConfig.metadata,
        ...(data?.metadata || {})
      },
      // 重命名配置（深度合并）
      rename: {
        ...defaultConfig.rename,
        ...(data?.rename || {})
      },
      // 密码清理配置（深度合并）
      password_cleanup: {
        ...defaultConfig.password_cleanup,
        ...(data?.password_cleanup || {})
      },
      // 压缩包清理配置（深度合并）
      archive_cleanup: {
        ...defaultConfig.archive_cleanup,
        ...(data?.processed_archive_cleanup || {}),
        min_keep_count: data?.processed_archive_cleanup?.min_keep_count ?? defaultConfig.archive_cleanup.min_keep_count
      },
      backup_zip: {
        ...defaultConfig.backup_zip,
        ...(data?.backup_zip || {})
      },
      classification: data?.classification || defaultConfig.classification,
      path_mappings: data?.path_mapping?.rules || defaultConfig.path_mappings,
      path_mapping_enabled: data?.path_mapping?.enabled ?? defaultConfig.path_mapping_enabled,
      // Kikoeru 服务器配置映射
      kikoeru_server: {
        enabled: data?.kikoeru_server?.enabled ?? false,
        server_url: data?.kikoeru_server?.server_url || '',
        username: data?.kikoeru_server?.username || '',
        password: data?.kikoeru_server?.password || '',
        api_token: data?.kikoeru_server?.api_token || '',
        token_expires: data?.kikoeru_server?.token_expires || 0,
        timeout: data?.kikoeru_server?.timeout ?? 10,
        cache_ttl: data?.kikoeru_server?.cache_ttl ?? 300,
        http_proxy: data?.kikoeru_server?.http_proxy || '',
        check_in_preextract: data?.kikoeru_server?.check_in_preextract ?? true,
        retry_count: data?.kikoeru_server?.retry_count ?? 3,
        retry_delay: data?.kikoeru_server?.retry_delay ?? 1.0
      },
      // ASMR 同步配置映射
      asmr_sync: {
        enabled: data?.asmr_sync?.enabled ?? true,
        api_base_url: data?.asmr_sync?.api_base_url || 'https://api.asmr-200.com/api',
        max_concurrent_downloads: data?.asmr_sync?.max_concurrent_downloads ?? 3,
        http_proxy: data?.asmr_sync?.http_proxy || '',
        retry_interval_hours: data?.asmr_sync?.retry_interval_hours ?? 1.0,
        max_retry_count: data?.asmr_sync?.max_retry_count ?? 10,
        retry_cron: data?.asmr_sync?.retry_cron || '0 */1 * * *',
        retry_count: data?.asmr_sync?.retry_count ?? 3,
        retry_delay: data?.asmr_sync?.retry_delay ?? 5,
        lrc_clean_enabled: data?.asmr_sync?.lrc_clean_enabled ?? true,
        lrc_clean_patterns: data?.asmr_sync?.lrc_clean_patterns || defaultConfig.asmr_sync.lrc_clean_patterns,
        simplify_chinese_enabled: data?.asmr_sync?.simplify_chinese_enabled ?? true
      },
      // 正常解压缩流程步骤配置
      auto_process: {
        check_duplicate: data?.auto_process?.check_duplicate ?? true,
        extract: data?.auto_process?.extract ?? true,
        fetch_metadata: data?.auto_process?.fetch_metadata ?? true,
        rename: data?.auto_process?.rename ?? true,
        filter: data?.auto_process?.filter ?? true,
        classify: data?.auto_process?.classify ?? true,
        archive: data?.auto_process?.archive ?? true
      },
      // 已有文件夹处理流程步骤配置
      process_existing: {
        check_duplicate: data?.process_existing?.check_duplicate ?? true,
        fetch_metadata: data?.process_existing?.fetch_metadata ?? true,
        rename: data?.process_existing?.rename ?? true,
        filter: data?.process_existing?.filter ?? true,
        import_lrc: data?.process_existing?.import_lrc ?? true,
        classify: data?.process_existing?.classify ?? true
      },
      // ASMR 同步下载流程步骤配置
      asmr_sync_step: {
        download: data?.asmr_sync_step?.download ?? true,
        sync_subtitle: data?.asmr_sync_step?.sync_subtitle ?? true,
        rename: data?.asmr_sync_step?.rename ?? true,
        classify: data?.asmr_sync_step?.classify ?? true,
        move_subtitle_folder: data?.asmr_sync_step?.move_subtitle_folder ?? true
      }
    }
    if (!config.value.storage.libraries.length) {
      config.value.storage.libraries = [
        normalizeLibraryConfig({
          id: 'default-local',
          name: '默认库存',
          type: 'local',
          path: config.value.storage.library_path || ''
        }, 1)
      ]
    }
    if (!config.value.storage.default_library_id) {
      config.value.storage.default_library_id = config.value.storage.libraries[0]?.id || ''
    }
    if (!config.value.storage.default_extract_library_id) {
      config.value.storage.default_extract_library_id = config.value.storage.default_library_id
    }
    console.log('配置加载成功:', config.value)
    console.log('存储路径:', config.value.storage)
  } catch (error) {
    console.error('加载配置失败:', error)
    ElMessage.error('加载配置失败：' + (error.response?.data?.detail || error.message))
    // 加载失败时使用默认配置
    config.value = JSON.parse(JSON.stringify(defaultConfig))
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  try {
    loading.value = true
    
    console.log('当前 config.value.storage:', config.value.storage)
    if (!config.value.storage.libraries.length) {
      config.value.storage.libraries = [
        normalizeLibraryConfig({
          id: 'default-local',
          name: '默认库存',
          type: 'local',
          path: config.value.storage.library_path || ''
        }, 1)
      ]
    }
    if (!config.value.storage.default_library_id) {
      config.value.storage.default_library_id = config.value.storage.libraries[0]?.id || ''
    }
    if (!config.value.storage.default_extract_library_id) {
      config.value.storage.default_extract_library_id = config.value.storage.default_library_id
    }
    
    // 构建要保存的配置数据，将前端配置映射到后端格式
    const configToSave = {
      storage: {
        input_path: config.value.storage.input_path || '',
        temp_path: config.value.storage.temp_path || '',
        library_path: config.value.storage.library_path || '',
        processed_archives_path: config.value.storage.processed_archives_path || '',
        existing_folders_path: config.value.storage.existing_folders_path || '',
        asmr_subtitle_path: config.value.storage.asmr_subtitle_path || '',
        libraries: (config.value.storage.libraries || []).map((library, index) => {
          const normalized = normalizeLibraryConfig(library, index + 1)
          syncRemoteLibraryPath(normalized)
          return {
            id: normalized.id,
            name: normalized.name,
            type: normalized.type,
            path: normalized.type === 'synology_filestation' ? normalized.synology.root_path : normalized.path,
            browse_path: normalized.browse_path || '',
            enabled: normalized.enabled,
            writable: normalized.writable,
            description: normalized.description || '',
            tags: normalized.tags || [],
            synology: normalized.type === 'synology_filestation'
              ? {
                  base_url: normalized.synology.base_url || '',
                  username: normalized.synology.username || '',
                  password: normalized.synology.password || '',
                  root_path: normalized.synology.root_path || '/',
                  otp_code: normalized.synology.otp_code || '',
                  device_name: normalized.synology.device_name || normalized.name || normalized.id,
                  device_id: normalized.synology.device_id || '',
                  enable_device_token: normalized.synology.enable_device_token ?? true,
                  session_name: normalized.synology.session_name || 'FileStation',
                  timeout: normalized.synology.timeout ?? 30,
                  verify_ssl: normalized.synology.verify_ssl ?? true
                }
              : null
          }
        }),
        default_library_id: config.value.storage.default_library_id || '',
        default_extract_library_id: config.value.storage.default_extract_library_id || config.value.storage.default_library_id || '',
        health_warning_free_gb: config.value.storage.health_warning_free_gb ?? 200,
        stats_cache_ttl_seconds: config.value.storage.stats_cache_ttl_seconds ?? 300
      },
      processing: config.value.processing,
      watcher: config.value.watcher,
      extract: config.value.extract,
      filter: config.value.filter,
      metadata: config.value.metadata,
      rename: config.value.rename,
      classification: config.value.classification.map(rule => ({
        type: rule.type,
        enabled: rule.enabled,
        path_template: rule.path_template || '',
        custom_name: rule.custom_name || null,
        rjcode_range: rule.rjcode_range || null
      })),
      password_cleanup: config.value.password_cleanup,
      processed_archive_cleanup: {
        ...config.value.archive_cleanup,
        min_keep_count: config.value.archive_cleanup.min_keep_count ?? 10
      },
      backup_zip: {
        enabled: config.value.backup_zip?.enabled ?? false,
        source_path: config.value.backup_zip?.source_path || '',
        output_dir: config.value.backup_zip?.output_dir || '',
        path_copy_target: config.value.backup_zip?.path_copy_target || '',
        copy_structure_before_zip: config.value.backup_zip?.copy_structure_before_zip ?? true,
        password: config.value.backup_zip?.password || '',
        archive_format: config.value.backup_zip?.archive_format || 'zip',
        compression_level: config.value.backup_zip?.compression_level ?? 9,
        compression_threads: config.value.backup_zip?.compression_threads ?? 0
      },
      path_mapping: {
        enabled: config.value.path_mapping_enabled,
        rules: (config.value.path_mappings || []).map(rule => ({
          remote_path: rule.original || rule.remote_path,
          local_path: rule.mapped || rule.local_path,
          enabled: true
        }))
      },
      kikoeru_server: {
        enabled: config.value.kikoeru_server?.enabled || false,
        server_url: config.value.kikoeru_server?.server_url || '',
        username: config.value.kikoeru_server?.username || '',
        password: config.value.kikoeru_server?.password || '',
        api_token: config.value.kikoeru_server?.api_token || '',
        token_expires: config.value.kikoeru_server?.token_expires || 0,
        timeout: config.value.kikoeru_server?.timeout ?? 10,
        cache_ttl: config.value.kikoeru_server?.cache_ttl ?? 300,
        http_proxy: config.value.kikoeru_server?.http_proxy || '',
        check_in_preextract: config.value.kikoeru_server?.check_in_preextract ?? true,
        retry_count: config.value.kikoeru_server?.retry_count ?? 3,
        retry_delay: config.value.kikoeru_server?.retry_delay ?? 1.0
      },
      asmr_sync: {
        enabled: config.value.asmr_sync?.enabled ?? true,
        api_base_url: config.value.asmr_sync?.api_base_url || 'https://api.asmr-200.com/api',
        max_concurrent_downloads: config.value.asmr_sync?.max_concurrent_downloads ?? 3,
        http_proxy: config.value.asmr_sync?.http_proxy || '',
        retry_interval_hours: config.value.asmr_sync?.retry_interval_hours ?? 1.0,
        max_retry_count: config.value.asmr_sync?.max_retry_count ?? 10,
        retry_cron: config.value.asmr_sync?.retry_cron || '0 */1 * * *',
        retry_count: config.value.asmr_sync?.retry_count ?? 3,
        retry_delay: config.value.asmr_sync?.retry_delay ?? 5,
        lrc_clean_enabled: config.value.asmr_sync?.lrc_clean_enabled ?? true,
        lrc_clean_patterns: config.value.asmr_sync?.lrc_clean_patterns || [],
        simplify_chinese_enabled: config.value.asmr_sync?.simplify_chinese_enabled ?? true
      },
      auto_process: {
        check_duplicate: config.value.auto_process?.check_duplicate ?? true,
        extract: config.value.auto_process?.extract ?? true,
        fetch_metadata: config.value.auto_process?.fetch_metadata ?? true,
        rename: config.value.auto_process?.rename ?? true,
        filter: config.value.auto_process?.filter ?? true,
        classify: config.value.auto_process?.classify ?? true,
        archive: config.value.auto_process?.archive ?? true
      },
      process_existing: {
        check_duplicate: config.value.process_existing?.check_duplicate ?? true,
        fetch_metadata: config.value.process_existing?.fetch_metadata ?? true,
        rename: config.value.process_existing?.rename ?? true,
        filter: config.value.process_existing?.filter ?? true,
        import_lrc: config.value.process_existing?.import_lrc ?? true,
        classify: config.value.process_existing?.classify ?? true
      },
      asmr_sync_step: {
        download: config.value.asmr_sync_step?.download ?? true,
        sync_subtitle: config.value.asmr_sync_step?.sync_subtitle ?? true,
        rename: config.value.asmr_sync_step?.rename ?? true,
        classify: config.value.asmr_sync_step?.classify ?? true,
        move_subtitle_folder: config.value.asmr_sync_step?.move_subtitle_folder ?? true
      }
    }
    
    console.log('保存配置:', configToSave)
    await configStore.saveConfig(configToSave)
    ElMessage.success('配置保存成功')
    
    // 重新加载配置确保显示最新数据
    await loadConfig()
  } catch (error) {
    console.error('保存配置失败:', error)
    ElMessage.error('保存配置失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

function resetConfig() {
  ElMessageBox.confirm('确定要重置所有配置吗？', '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(async () => {
    config.value = JSON.parse(JSON.stringify(defaultConfig))
    await saveConfig()
  }).catch(() => {})
}

function addStorageLibrary(type = 'local') {
  const nextIndex = (config.value.storage.libraries?.length || 0) + 1
  const nextLibrary = createDefaultLibrary(type, nextIndex)
  if (type === 'local' && !nextLibrary.path) {
    nextLibrary.path = config.value.storage.library_path || ''
  }
  if (type === 'synology_filestation') {
    nextLibrary.synology.device_name = nextLibrary.name
    nextLibrary.path = nextLibrary.synology.root_path
  }
  config.value.storage.libraries = [...(config.value.storage.libraries || []), nextLibrary]
  if (!config.value.storage.default_library_id) {
    config.value.storage.default_library_id = nextLibrary.id
  }
  if (!config.value.storage.default_extract_library_id) {
    config.value.storage.default_extract_library_id = nextLibrary.id
  }
}

function removeStorageLibrary(index) {
  const libraries = [...(config.value.storage.libraries || [])]
  const removed = libraries[index]
  libraries.splice(index, 1)
  config.value.storage.libraries = libraries
  if (removed?.id && config.value.storage.default_library_id === removed.id) {
    config.value.storage.default_library_id = libraries[0]?.id || ''
  }
  if (removed?.id && config.value.storage.default_extract_library_id === removed.id) {
    config.value.storage.default_extract_library_id = config.value.storage.default_library_id || libraries[0]?.id || ''
  }
}

function syncRemoteLibraryPath(library) {
  if (library?.type === 'synology_filestation') {
    library.synology = {
      ...createDefaultLibrary('synology_filestation', 1).synology,
      ...(library.synology || {})
    }
    library.synology.root_path = library.synology.root_path || library.path || '/'
    library.synology.device_name = library.synology.device_name || library.name || library.id
    library.path = library.synology.root_path
  }
}

function buildSynologyWebUrl(library) {
  const baseUrl = library?.synology?.base_url?.replace(/\/+$/, '') || ''
  const rootPath = library?.synology?.root_path || library?.path || '/'
  if (!baseUrl || !rootPath) return ''
  const normalizedPath = rootPath.startsWith('/') ? rootPath : `/${rootPath}`
  return `${baseUrl}//file/?launchApp=SYNO.SDS.App.FileStation3.Instance&launchParam=${encodeURIComponent(`path=${normalizedPath}`)}`
}

async function testStorageLibrary(library) {
  try {
    syncRemoteLibraryPath(library)
    testingLibraryId.value = library.id || `library-${Date.now()}`
    const response = await libraryApi.testConnection(normalizeLibraryConfig(library))
    if (response.device_id) {
      library.synology.device_id = response.device_id
    }
    ElMessage.success(response.message || '连接成功')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '连接测试失败')
  } finally {
    testingLibraryId.value = ''
  }
}

/**
 * 重置指定部分的配置
 * @param {string} section - 配置部分名称
 */
function resetSection(section) {
  const sectionNames = {
    'storage': '存储路径',
    'watcher': '文件夹监视器',
    'processing': '处理配置',
    'filter': '过滤配置',
    'metadata': '元数据配置',
    'rename': '重命名配置',
    'passwordCleanup': '密码库智能清理',
    'archiveCleanup': '已处理压缩包智能清理',
    'pathMapping': '路径映射',
    'kikoeruServer': 'Kikoeru 服务器查重',
    'asmrSync': 'ASMR 同步下载',
    'classification': '分类规则'
  }
  
  ElMessageBox.confirm(`确定要重置"${sectionNames[section] || section}"的配置吗？`, '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(async () => {
    // 根据 section 重置对应的配置
    switch(section) {
      case 'storage':
        config.value.storage = JSON.parse(JSON.stringify(defaultConfig.storage))
        break
      case 'watcher':
        config.value.watcher = JSON.parse(JSON.stringify(defaultConfig.watcher))
        break
      case 'processing':
        config.value.processing = JSON.parse(JSON.stringify(defaultConfig.processing))
        config.value.extract = JSON.parse(JSON.stringify(defaultConfig.extract))
        config.value.auto_process = JSON.parse(JSON.stringify(defaultConfig.auto_process))
        break
      case 'filter':
        config.value.filter = JSON.parse(JSON.stringify(defaultConfig.filter))
        config.value.rename.flatten_single_subfolder = defaultConfig.rename.flatten_single_subfolder
        config.value.rename.flatten_depth = defaultConfig.rename.flatten_depth
        config.value.rename.remove_empty_folders = defaultConfig.rename.remove_empty_folders
        break
      case 'metadata':
        config.value.metadata = JSON.parse(JSON.stringify(defaultConfig.metadata))
        break
      case 'rename':
        config.value.rename = JSON.parse(JSON.stringify(defaultConfig.rename))
        config.value.process_existing = JSON.parse(JSON.stringify(defaultConfig.process_existing))
        break
      case 'passwordCleanup':
        config.value.password_cleanup = JSON.parse(JSON.stringify(defaultConfig.password_cleanup))
        break
      case 'archiveCleanup':
        config.value.archive_cleanup = JSON.parse(JSON.stringify(defaultConfig.archive_cleanup))
        break
      case 'pathMapping':
        config.value.path_mappings = JSON.parse(JSON.stringify(defaultConfig.path_mappings))
        config.value.path_mapping_enabled = defaultConfig.path_mapping_enabled
        break
      case 'kikoeruServer':
        config.value.kikoeru_server = JSON.parse(JSON.stringify(defaultConfig.kikoeru_server))
        break
      case 'asmrSync':
        config.value.asmr_sync = JSON.parse(JSON.stringify(defaultConfig.asmr_sync))
        config.value.asmr_sync_step = JSON.parse(JSON.stringify(defaultConfig.asmr_sync_step))
        break
      case 'classification':
        config.value.classification = JSON.parse(JSON.stringify(defaultConfig.classification))
        break
    }
    
    // 重置后立即保存
    await saveConfig()
    ElMessage.success('配置已重置并保存')
  }).catch(() => {})
}

function addFilterRule() {
  if (!config.value.filter.rules) {
    config.value.filter.rules = []
  }
  config.value.filter.rules.push({
    name: '新规则',
    pattern: '',
    target: 'file',
    action: 'exclude',
    enabled: true
  })
}

function removeFilterRule(index) {
  config.value.filter.rules.splice(index, 1)
}

function getTargetLabel(target) {
  const labels = {
    file: '文件',
    folder: '文件夹',
    all: '文件和文件夹'
  }
  return labels[target] || target
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

function removeRule(index) {
  config.value.classification.splice(index, 1)
}

function onRuleTypeChange(rule) {
  // 根据类型重置规则属性
  if (rule.type === 'none') {
    rule.path_template = ''
    rule.custom_name = ''
    rule.rjcode_range = ''
  } else if (rule.type === 'maker') {
    rule.custom_name = ''
    rule.rjcode_range = ''
  } else if (rule.type === 'rjcode') {
    rule.path_template = ''
  } else if (rule.type === 'series') {
    rule.custom_name = ''
    rule.rjcode_range = ''
  }
}

function getPathPreview(rule) {
  const basePath = config.value.storage.library_path || '未设置'
  
  if (rule.type === 'none') {
    return basePath
  } else if (rule.type === 'maker') {
    const subDir = rule.path_template || '{maker_name}'
    return `${basePath}\\${subDir}`
  } else if (rule.type === 'rjcode') {
    const subDir = rule.custom_name || '未命名'
    return `${basePath}\\${subDir}`
  } else if (rule.type === 'series') {
    const subDir = rule.path_template || '{series_name}'
    return `${basePath}\\${subDir}`
  }
  
  return basePath
}

function addPathMapping() {
  if (!config.value.path_mappings) {
    config.value.path_mappings = []
  }
  config.value.path_mappings.push({
    original: '',
    mapped: ''
  })
}

function removePathMapping(index) {
  config.value.path_mappings.splice(index, 1)
}

// Kikoeru 服务器相关变量和函数
const testingKikoeru = ref(false)
const gettingToken = ref(false)
const testingDuplicate = ref(false)
const kikoeruTestRj = ref('')

async function testKikoeruConnection() {
  try {
    testingKikoeru.value = true
    const result = await kikoeruApi.testConnection()
    if (result.success) {
      ElMessage.success(result.message || '连接成功')
    } else {
      ElMessage.error(result.message || '连接失败')
    }
  } catch (error) {
    console.error('连接失败:', error)
    ElMessage.error('连接失败：' + (error.response?.data?.detail || error.message))
  } finally {
    testingKikoeru.value = false
  }
}

async function getKikoeruToken() {
  try {
    gettingToken.value = true
    const result = await kikoeruApi.getToken()
    if (result.success) {
      config.value.kikoeru_server.api_token = result.token
      config.value.kikoeru_server.token_expires = result.expires
      ElMessage.success(result.message || 'Token 获取成功')
      await saveConfig()
    } else {
      ElMessage.error(result.message || '获取 Token 失败')
    }
  } catch (error) {
    console.error('获取 Token 失败:', error)
    ElMessage.error('获取 Token 失败：' + (error.response?.data?.detail || error.message))
  } finally {
    gettingToken.value = false
  }
}

async function testKikoeruDuplicate() {
  try {
    testingDuplicate.value = true
    const result = await kikoeruApi.check(
      kikoeruTestRj.value,
      true,
      'CHI_HANS CHI_HANT ENG JPN'
    )
    if (result.is_found) {
      let message = `作品 ${kikoeruTestRj.value} 已存在于服务器`
      if (result.title) {
        message += `：${result.title}`
      }
      if (result.linked_works_found && result.linked_works_found.length > 0) {
        message += `\n关联作品: ${result.linked_works_found.map(w => w.rjcode).join(', ')}`
      }
      ElMessage.info(message)
    } else {
      ElMessage.success(`作品 ${kikoeruTestRj.value} 不存在于服务器`)
    }
  } catch (error) {
    console.error('查重测试失败:', error)
    ElMessage.error('查重测试失败：' + (error.response?.data?.detail || error.message))
  } finally {
    testingDuplicate.value = false
  }
}

// LRC 清理规则相关函数
const newLrcPattern = ref('')

function addLrcPattern() {
  if (!newLrcPattern.value.trim()) return
  if (!config.value.asmr_sync.lrc_clean_patterns) {
    config.value.asmr_sync.lrc_clean_patterns = []
  }
  config.value.asmr_sync.lrc_clean_patterns.push(newLrcPattern.value.trim())
  newLrcPattern.value = ''
}

function removeLrcPattern(index) {
  config.value.asmr_sync.lrc_clean_patterns.splice(index, 1)
}

async function syncAsmrNow() {
  try {
    loading.value = true
    await kikoeruApi.syncAsmr()
    ElMessage.success('同步任务已启动')
  } catch (error) {
    console.error('同步失败:', error)
    ElMessage.error('同步失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

async function createTestDirs() {
  try {
    loading.value = true
    await configApi.createTestDirs()
    ElMessage.success('测试目录创建成功')
    // 刷新配置获取新路径
    await loadConfig()
  } catch (error) {
    console.error('创建测试目录失败:', error)
    ElMessage.error('创建测试目录失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

async function previewPasswordCleanup() {
  try {
    loading.value = true
    const data = await cleanupApi.password.preview()

    if (data.to_delete_count === 0) {
      ElMessage.info('没有需要清理的密码')
    } else {
      ElMessage.success(`预计清理 ${data.to_delete_count} 个密码，释放 ${data.freed_space_mb.toFixed(2)} MB 空间`)
    }
  } catch (error) {
    console.error('预览清理失败:', error)
    ElMessage.error('预览清理失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

async function runPasswordCleanup() {
  try {
    loading.value = true
    const data = await cleanupApi.password.run()

    if (data.deleted_count === 0) {
      ElMessage.info('没有需要清理的密码')
    } else {
      ElMessage.success(`成功清理 ${data.deleted_count} 个密码，释放 ${data.freed_space_mb.toFixed(2)} MB 空间`)
    }
  } catch (error) {
    console.error('执行清理失败:', error)
    ElMessage.error('执行清理失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

async function previewArchiveCleanup() {
  try {
    loading.value = true
    const data = await cleanupApi.archive.preview()

    if (data.to_delete_count === 0) {
      ElMessage.info('没有需要清理的压缩包')
    } else {
      ElMessage.success(`预计清理 ${data.to_delete_count} 个压缩包，释放 ${data.freed_space_mb.toFixed(2)} MB 空间`)
    }
  } catch (error) {
    console.error('预览清理失败:', error)
    ElMessage.error('预览清理失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

async function runArchiveCleanup() {
  try {
    loading.value = true
    const data = await cleanupApi.archive.run()

    if (data.deleted_count === 0) {
      ElMessage.info('没有需要清理的压缩包')
    } else {
      ElMessage.success(`成功清理 ${data.deleted_count} 个压缩包，释放 ${data.freed_space_mb.toFixed(2)} MB 空间`)
    }
  } catch (error) {
    console.error('执行清理失败:', error)
    ElMessage.error('执行清理失败：' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadConfig()
})
</script>

<style scoped>
.settings {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 28px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.setting-card {
  margin-bottom: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.rule-item {
  margin-bottom: 12px;
}

.actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  padding: 24px 0;
}

.card-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  padding: 15px 0 0;
  border-top: 1px solid #f0f0f0;
  margin-top: 15px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.text-gray {
  color: #909399;
}

.base-path-display {
  background-color: #f5f7fa;
  padding: 8px 12px;
  border-radius: 4px;
  border-left: 4px solid #409eff;
}

.base-path-display .path-label {
  color: #606266;
  font-weight: 500;
}

.base-path-display .path-value {
  color: #409eff;
  font-family: monospace;
  font-weight: 600;
}

.path-preview {
  background-color: #f0f9ff;
  padding: 8px 12px;
  border-radius: 4px;
  border: 1px dashed #409eff;
}

.path-preview .preview-label {
  color: #606266;
  font-weight: 500;
}

.path-preview .preview-value {
  color: #67c23a;
  font-family: monospace;
  font-weight: 600;
}

/* 折叠面板标题样式 */
.collapse-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  flex: 1;
}

/* 调整折叠面板间距 */
:deep(.el-collapse-item) {
  margin-bottom: 16px;
  border: none;
}

:deep(.el-collapse-item__header) {
  background-color: #f5f7fa;
  border-radius: 8px;
  padding: 12px 20px;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  transition: all 0.3s;
  border: 1px solid #e4e7ed;
}

:deep(.el-collapse-item__header:hover) {
  background-color: #ecf5ff;
  border-color: #409eff;
}

:deep(.el-collapse-item__header.is-active) {
  background-color: #ecf5ff;
  border-color: #409eff;
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
}

:deep(.el-collapse-item__wrap) {
  border: none;
  padding: 0;
  background-color: #fff;
  border: 1px solid #e4e7ed;
  border-top: none;
  border-bottom-left-radius: 8px;
  border-bottom-right-radius: 8px;
}

:deep(.el-collapse-item__content) {
  padding: 16px;
}

/* 分类规则布局 */
.classification-row {
  display: flex;
  align-items: flex-start;
  gap: 15px;
  flex-wrap: wrap;
}

.classification-type {
  width: 140px;
  flex-shrink: 0;
}

.classification-input {
  flex: 1;
  min-width: 300px;
}

.classification-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.rjcode-config {
  margin-top: 15px;
  margin-left: 155px;
}

@media (max-width: 768px) {
  .classification-row {
    flex-direction: column;
  }

  .classification-type {
    width: 100%;
  }

  .classification-input {
    min-width: 100%;
  }

  .rjcode-config {
    margin-left: 0;
  }
}

/* 确保下拉框宽度正确 */
.classification-type :deep(.el-select) {
  width: 100%;
}

.classification-type :deep(.el-input__wrapper) {
  width: 100%;
}

/* 过滤规则下拉框样式 */
.rule-item :deep(.el-select) {
  width: 100%;
}

.rule-item :deep(.el-input__wrapper) {
  width: 100%;
}
</style>
