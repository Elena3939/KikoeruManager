<template>
  <div class="subtitle-page">
    <!-- 页头：和库存页 / 问题作品页保持一致的 AppPageHeader 共享组件 -->
    <AppPageHeader
      :icon="Captions"
      icon-color="#1d4ed8"
      title="字幕补配"
      subtitle="自动检测的压缩包来源进入预检单；手动字幕目录也可以在这里补进库存"
    >
      <span v-if="(workbenchBackgroundSummary.processing || 0) > 0" class="lib-chip lib-chip-info">
        <AppLoadingAnimation variant="inline" :size="14" />
        {{ workbenchBackgroundSummary.processing }} 进行中
      </span>
      <button
        type="button"
        class="subtitle-refresh-btn"
        :disabled="pendingLoading"
        @click="loadPendingImports"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': pendingLoading }" />
        刷新
      </button>
      <button type="button" class="subtitle-action-btn is-primary" @click="openImportWorkbench()">
        <Sparkles class="w-3.5 h-3.5" />
        打开工作台
      </button>
    </AppPageHeader>

    <!-- 状态条：3 列，对齐库存页 / 问题作品页 lib-info-strip -->
    <section class="lib-info-strip subtitle-info-strip">
      <div class="lib-info-item">
        <Inbox :size="15" :stroke-width="2.2" class="lib-info-icon text-indigo-500" />
        <div class="lib-info-body">
          <div class="lib-info-label">预检单</div>
          <div class="lib-info-value">
            <b>{{ pendingItems.length }}</b>
            <span class="lib-info-meta">条待处理</span>
          </div>
          <div class="lib-info-sub">压缩包来源经自动检测后进入预检</div>
        </div>
      </div>
      <div class="lib-info-divider"></div>
      <div class="lib-info-item">
        <Loader2 :size="15" :stroke-width="2.2" class="lib-info-icon text-blue-500" />
        <div class="lib-info-body">
          <div class="lib-info-label">工作台进行中</div>
          <div class="lib-info-value"><b>{{ workbenchBackgroundSummary.processing || 0 }}</b></div>
          <div class="lib-info-sub">字幕匹配 / 应用任务实时数</div>
        </div>
      </div>
      <div class="lib-info-divider"></div>
      <div class="lib-info-item">
        <History :size="15" :stroke-width="2.2" class="lib-info-icon text-emerald-500" />
        <div class="lib-info-body">
          <div class="lib-info-label">本会话累计</div>
          <div class="lib-info-value"><b>{{ workbenchBackgroundSummary.total || 0 }}</b></div>
          <div class="lib-info-sub">已完成 / 处理过的任务总数</div>
        </div>
      </div>
    </section>

    <!-- 主工作区：tabs + 双栏。工作台 dialog 打开时整体隐藏 -->
    <div v-show="!workbenchDialogVisible" class="subtitle-shell">
      <!-- Tab segmented：和问题作品页 conflicts-segmented 一致 -->
      <div class="subtitle-segmented" role="tablist">
        <button
          type="button"
          role="tab"
          class="subtitle-segmented-item"
          :class="{ 'is-active': activeTab === 'archive' }"
          @click="activeTab = 'archive'"
        >
          <Archive :size="13" :stroke-width="2.2" />
          压缩包补配
        </button>
        <button
          type="button"
          role="tab"
          class="subtitle-segmented-item"
          :class="{ 'is-active': activeTab === 'folder' }"
          @click="activeTab = 'folder'"
        >
          <FolderOpen :size="13" :stroke-width="2.2" />
          字幕文件夹补配
        </button>
      </div>

      <!-- ==================== 压缩包补配 ==================== -->
      <div v-if="activeTab === 'archive'" class="subtitle-main">
        <!-- 左侧：预检单列表 -->
        <aside class="subtitle-list-pane">
          <div class="subtitle-list-header">
            <div class="subtitle-list-header-row">
              <h3 class="subtitle-list-title">预检单</h3>
              <span class="lib-chip lib-chip-info">{{ pendingItems.length }} 条</span>
            </div>
            <div class="subtitle-list-actions">
              <button
                type="button"
                class="subtitle-mini-btn"
                :disabled="!activePendingItem || pendingClearLoading"
                @click="clearPendingImports(false)"
              >
                <Eraser class="w-3.5 h-3.5" />
                清除当前
              </button>
              <button
                type="button"
                class="subtitle-mini-btn is-danger"
                :disabled="!pendingItems.length || pendingClearLoading"
                @click="clearPendingImports(true)"
              >
                <Trash2 class="w-3.5 h-3.5" />
                清空
              </button>
            </div>
            <p class="subtitle-list-hint">单击查看详情，可重试候选搜索</p>
          </div>
          <div class="subtitle-list-scroll no-scrollbar">
            <AppEmptyState
              v-if="pendingLoadedOnce && !pendingItems.length"
              description="没有待处理的预检单"
              size="sm"
              class="my-auto"
            />
            <button
              v-for="item in pendingItems"
              :key="item.id"
              type="button"
              class="subtitle-list-card"
              :class="{ 'is-active': item.id === activePendingId }"
              @click="activePendingId = item.id"
            >
              <div class="subtitle-list-card-row">
                <strong class="subtitle-list-card-title">
                  {{ getDisplayRJCode(item.preview?.target_rjcode || item.preview?.source_rjcode) || '未识别 RJ' }}
                  <ChevronRight class="w-3.5 h-3.5 subtitle-list-card-chev" />
                </strong>
                <span class="lib-chip" :class="item.can_execute ? 'lib-chip-success' : 'lib-chip-warning'">
                  {{ item.can_execute ? '可执行' : '仅查看' }}
                </span>
              </div>
              <div class="subtitle-list-card-source">
                {{ item.preview?.source_label || getFileName(item.source_path) }}
              </div>
              <div class="subtitle-list-card-meta">
                <span class="subtitle-list-card-arrow">
                  <span class="font-mono">{{ getDisplayRJCode(item.preview?.source_rjcode) || '-' }}</span>
                  <ArrowRight class="w-3 h-3 mx-1 inline" />
                  <span class="font-mono">{{ getDisplayRJCode(item.preview?.target_rjcode) || '-' }}</span>
                </span>
                <span class="subtitle-list-card-count">{{ item.preview?.subtitle_count ?? 0 }} 字幕</span>
              </div>
            </button>
          </div>
        </aside>

        <!-- 右侧：详情 -->
        <section v-if="activePendingItem" class="subtitle-detail-pane" :key="activePendingItem.id">
          <div class="subtitle-detail-header">
            <div class="subtitle-detail-bg-glyph" aria-hidden="true">
              <Captions :size="220" :stroke-width="1.4" />
            </div>
            <div class="subtitle-detail-header-inner">
              <div class="subtitle-detail-title-block">
                <h2 class="subtitle-detail-title">
                  {{ getDisplayRJCode(activePendingItem.preview?.target_rjcode || activePendingItem.preview?.source_rjcode) || '预检结果' }}
                </h2>
                <p class="subtitle-detail-subtitle">
                  <span
                    class="subtitle-detail-dot"
                    :class="activePendingItem.can_execute ? 'is-info' : 'is-warning'"
                  ></span>
                  {{ activePendingItem.preview?.source_label || '-' }}
                </p>
              </div>
              <div class="subtitle-detail-actions">
                <button
                  v-if="canRetryActivePendingPreview"
                  type="button"
                  class="subtitle-action-btn is-slate"
                  :disabled="retryingPendingId === activePendingItem.id"
                  @click="retryActivePendingPreview"
                >
                  <RotateCw
                    class="w-3.5 h-3.5"
                    :class="{ 'animate-spin': retryingPendingId === activePendingItem.id }"
                  />
                  重试搜索
                </button>
                <span
                  class="lib-chip"
                  :class="activePendingItem.can_execute ? 'lib-chip-success' : 'lib-chip-warning'"
                >
                  {{ activePendingItem.can_execute ? '可以补配' : '不可执行' }}
                </span>
              </div>
            </div>
          </div>

          <div class="subtitle-detail-body no-scrollbar">
            <!-- 状态提示框 -->
            <div
              class="subtitle-detail-alert"
              :class="activePendingItem.can_execute ? 'is-info' : 'is-warning'"
            >
              <CheckCircle2
                v-if="activePendingItem.can_execute"
                class="w-5 h-5 flex-shrink-0 mt-0.5 text-emerald-500"
              />
              <AlertTriangle v-else class="w-5 h-5 flex-shrink-0 mt-0.5 text-amber-500" />
              <p>
                {{ activePendingItem.preview?.reason || (activePendingItem.can_execute ? '目标原作已定位，可以继续导入。' : '当前这条来源暂时无法执行。') }}
              </p>
            </div>

            <!-- 预检概览卡片 -->
            <article class="subtitle-info-card">
              <div class="subtitle-info-card-header">
                <Hash class="w-4 h-4 text-slate-400" />
                <h3>预检概览</h3>
              </div>
              <div class="subtitle-info-card-body">
                <div class="subtitle-meta-grid">
                  <div class="subtitle-meta-item">
                    <span class="subtitle-meta-label">来源 RJ</span>
                    <p class="subtitle-meta-value mono">
                      {{ getDisplayRJCode(activePendingItem.preview?.source_rjcode) || '-' }}
                    </p>
                  </div>
                  <div class="subtitle-meta-item">
                    <span class="subtitle-meta-label">目标 RJ</span>
                    <p class="subtitle-meta-value mono is-strong">
                      {{ getDisplayRJCode(activePendingItem.preview?.target_rjcode) || '-' }}
                    </p>
                  </div>
                  <div class="subtitle-meta-item">
                    <span class="subtitle-meta-label">字幕数</span>
                    <p class="subtitle-meta-value">{{ activePendingItem.preview?.subtitle_count ?? 0 }}</p>
                  </div>
                  <div class="subtitle-meta-item">
                    <span class="subtitle-meta-label">Kikoeru</span>
                    <p class="subtitle-meta-value">
                      {{ activePendingItem.preview?.kikoeru_has_work ? '已命中' : '未命中' }}
                    </p>
                  </div>
                  <div class="subtitle-meta-item is-wide">
                    <span class="subtitle-meta-label">预检时间</span>
                    <p class="subtitle-meta-value-muted">{{ formatDate(activePendingItem.created_at) }}</p>
                  </div>
                </div>
              </div>
            </article>

            <!-- 字幕文件树卡片 -->
            <article
              v-if="activePendingItem.preview?.subtitle_entries?.length"
              class="subtitle-info-card"
            >
              <div class="subtitle-info-card-header">
                <FileText class="w-4 h-4 text-slate-400" />
                <h3>字幕候选文件树</h3>
                <span class="lib-chip lib-chip-info ml-auto">
                  {{ activePendingItem.preview.subtitle_entries.length }} 项
                </span>
              </div>
              <div class="subtitle-info-card-body">
                <div class="subtitle-tree">
                  <div
                    v-for="node in buildSubtitleEntryTreeRows(activePendingItem.preview.subtitle_entries)"
                    :key="node.key"
                    class="subtitle-tree-row"
                    :style="{ paddingLeft: `${node.depth * 16 + 10}px` }"
                  >
                    <span class="subtitle-tree-bullet">{{ node.isDir ? '▸' : '└' }}</span>
                    <span
                      class="subtitle-tree-name"
                      :class="node.isDir ? 'is-dir' : 'is-file'"
                    >
                      {{ node.name }}
                    </span>
                  </div>
                </div>
              </div>
            </article>

            <!-- 候选目录卡片 -->
            <article class="subtitle-info-card">
              <div class="subtitle-info-card-header">
                <FolderTree class="w-4 h-4 text-slate-400" />
                <h3>目标目录候选</h3>
                <span class="lib-chip lib-chip-info ml-auto">
                  {{ activePendingItem.preview?.candidate_count ?? 0 }} 个
                </span>
              </div>
              <div class="subtitle-info-card-body">
                <AppEmptyState
                  v-if="!activePendingItem.preview?.candidates?.length"
                  description="没有可用的目标目录候选"
                  size="sm"
                />
                <div v-else class="subtitle-candidate-list">
                  <button
                    v-for="candidate in activePendingItem.preview.candidates"
                    :key="candidateKey(candidate)"
                    type="button"
                    class="subtitle-candidate-card"
                    :class="{ 'is-selected': archiveCandidateSelection[activePendingItem.id] === candidateKey(candidate) }"
                    @click="archiveCandidateSelection[activePendingItem.id] = candidateKey(candidate)"
                  >
                    <span
                      class="subtitle-candidate-radio"
                      :class="{ 'is-checked': archiveCandidateSelection[activePendingItem.id] === candidateKey(candidate) }"
                    >
                      <span
                        v-if="archiveCandidateSelection[activePendingItem.id] === candidateKey(candidate)"
                        class="subtitle-candidate-radio-dot"
                      ></span>
                    </span>
                    <div class="subtitle-candidate-body">
                      <h4 class="subtitle-candidate-name">{{ candidate.folder_name || candidate.folder_path }}</h4>
                      <div class="subtitle-candidate-chips">
                        <span class="lib-chip lib-chip-info">{{ candidate.library_name }}</span>
                        <span
                          class="lib-chip"
                          :class="candidate.library_type === 'synology_filestation' ? 'lib-chip-warning' : 'lib-chip-success'"
                        >
                          {{ candidate.library_type === 'synology_filestation' ? '远程' : '本地' }}
                        </span>
                        <span class="lib-chip lib-chip-info">音频 {{ candidate.audio_count ?? 0 }}</span>
                        <span class="lib-chip lib-chip-info">字幕 {{ candidate.existing_subtitle_count ?? 0 }}</span>
                        <span class="lib-chip lib-chip-info">{{ formatSize(candidate.total_size) }}</span>
                      </div>
                      <div class="subtitle-candidate-path mono">{{ candidate.folder_path }}</div>
                    </div>
                  </button>
                </div>
              </div>
            </article>

            <!-- 提交栏 -->
            <div class="subtitle-detail-footer">
              <button
                type="button"
                class="subtitle-action-btn is-primary lg"
                :disabled="!activePendingItem.can_execute || !selectedArchiveCandidate || executingPendingId === activePendingItem.id"
                @click="executePendingImport()"
              >
                <AppLoadingAnimation
                  v-if="executingPendingId === activePendingItem.id"
                  variant="inline"
                  :size="20"
                />
                <Sparkles v-else class="w-4 h-4" />
                {{ executingPendingId === activePendingItem.id ? '导入中…' : '导入并加入工作台' }}
              </button>
            </div>
          </div>
        </section>

        <!-- 右侧未选中占位 -->
        <section v-else class="subtitle-detail-pane subtitle-detail-placeholder">
          <div class="subtitle-detail-placeholder-inner">
            <Captions class="w-10 h-10 mb-3 text-slate-300" stroke-width="1.4" />
            <p class="text-sm font-medium text-slate-500">请从左侧选择一条预检单</p>
            <p class="text-xs text-slate-400 mt-1">点击列表项查看详情并执行补配</p>
          </div>
        </section>
      </div>

      <!-- ==================== 字幕文件夹补配 ==================== -->
      <div v-if="activeTab === 'folder'" class="subtitle-main">
        <!-- 左侧：手动表单 -->
        <aside class="subtitle-list-pane">
          <div class="subtitle-list-header">
            <div class="subtitle-list-header-row">
              <h3 class="subtitle-list-title">手动字幕来源</h3>
              <span class="lib-chip lib-chip-warning">手动</span>
            </div>
            <p class="subtitle-list-hint">输入字幕目录后做一次预检，再补进库存</p>
          </div>
          <div class="subtitle-form-body">
            <div class="subtitle-form-field">
              <label class="subtitle-form-label">字幕文件夹路径</label>
              <div class="subtitle-form-input-wrap">
                <input
                  v-model="folderPath"
                  type="text"
                  class="subtitle-form-input"
                  placeholder="例如 D:\Temp\RJ123456"
                  @keyup.enter="previewFolderImport"
                />
                <button
                  v-if="folderPath"
                  type="button"
                  class="subtitle-form-clear"
                  @click="folderPath = ''"
                  aria-label="清空输入"
                >
                  <X :size="13" :stroke-width="2.6" />
                </button>
              </div>
            </div>
            <div class="subtitle-form-actions">
              <button
                type="button"
                class="subtitle-action-btn is-slate"
                :disabled="folderPreviewLoading"
                @click="previewFolderImport"
              >
                <Eye class="w-3.5 h-3.5" :class="{ 'animate-pulse': folderPreviewLoading }" />
                {{ folderPreviewLoading ? '预检中…' : '预检' }}
              </button>
              <button
                type="button"
                class="subtitle-action-btn is-primary"
                :disabled="!canExecuteFolderImport || folderImporting"
                @click="executeFolderImport"
              >
                <AppLoadingAnimation v-if="folderImporting" variant="inline" :size="20" />
                <Sparkles v-else class="w-3.5 h-3.5" />
                {{ folderImporting ? '导入中…' : '导入' }}
              </button>
            </div>
            <div class="subtitle-form-hint-card">
              <Info class="w-4 h-4 flex-shrink-0 mt-0.5 text-slate-400" />
              <p>手头有字幕目录时，直接补进原作目录，再回库存页做筛选、配对和应用。</p>
            </div>
          </div>
        </aside>

        <!-- 右侧：预检结果 -->
        <section
          v-if="folderPreview"
          class="subtitle-detail-pane"
          :key="`${folderPreview.source_path || folderPreview.source_label || 'fp'}`"
        >
          <div class="subtitle-detail-header">
            <div class="subtitle-detail-bg-glyph" aria-hidden="true">
              <FolderOpen :size="220" :stroke-width="1.4" />
            </div>
            <div class="subtitle-detail-header-inner">
              <div class="subtitle-detail-title-block">
                <h2 class="subtitle-detail-title">
                  {{ getDisplayRJCode(folderPreview.target_rjcode) || '预检结果' }}
                </h2>
                <p class="subtitle-detail-subtitle">
                  <span
                    class="subtitle-detail-dot"
                    :class="canExecuteFolderImport ? 'is-info' : 'is-warning'"
                  ></span>
                  {{ folderPreview.source_label || folderPath || '-' }}
                </p>
              </div>
              <div class="subtitle-detail-actions">
                <button
                  v-if="canRetryFolderPreview"
                  type="button"
                  class="subtitle-action-btn is-slate"
                  :disabled="folderPreviewLoading"
                  @click="previewFolderImport"
                >
                  <RotateCw class="w-3.5 h-3.5" :class="{ 'animate-spin': folderPreviewLoading }" />
                  重新检查
                </button>
                <span
                  class="lib-chip"
                  :class="canExecuteFolderImport ? 'lib-chip-success' : 'lib-chip-warning'"
                >
                  {{ canExecuteFolderImport ? '可以补配' : '不可执行' }}
                </span>
              </div>
            </div>
          </div>

          <div class="subtitle-detail-body no-scrollbar">
            <div
              class="subtitle-detail-alert"
              :class="canExecuteFolderImport ? 'is-info' : 'is-warning'"
            >
              <CheckCircle2
                v-if="canExecuteFolderImport"
                class="w-5 h-5 flex-shrink-0 mt-0.5 text-emerald-500"
              />
              <AlertTriangle v-else class="w-5 h-5 flex-shrink-0 mt-0.5 text-amber-500" />
              <p>
                {{ folderPreview.reason || (canExecuteFolderImport ? '目标原作已定位，可以继续导入。' : '当前这份字幕文件夹暂时无法执行。') }}
              </p>
            </div>

            <article class="subtitle-info-card">
              <div class="subtitle-info-card-header">
                <Hash class="w-4 h-4 text-slate-400" />
                <h3>预检概览</h3>
              </div>
              <div class="subtitle-info-card-body">
                <div class="subtitle-meta-grid">
                  <div class="subtitle-meta-item">
                    <span class="subtitle-meta-label">来源 RJ</span>
                    <p class="subtitle-meta-value mono">{{ getDisplayRJCode(folderPreview.source_rjcode) || '-' }}</p>
                  </div>
                  <div class="subtitle-meta-item">
                    <span class="subtitle-meta-label">目标 RJ</span>
                    <p class="subtitle-meta-value mono is-strong">{{ getDisplayRJCode(folderPreview.target_rjcode) || '-' }}</p>
                  </div>
                  <div class="subtitle-meta-item">
                    <span class="subtitle-meta-label">字幕数</span>
                    <p class="subtitle-meta-value">{{ folderPreview.subtitle_count ?? 0 }}</p>
                  </div>
                  <div class="subtitle-meta-item is-wide">
                    <span class="subtitle-meta-label">来源目录</span>
                    <p class="subtitle-meta-value-muted truncate">{{ folderPreview.source_label || '-' }}</p>
                  </div>
                </div>
              </div>
            </article>

            <article v-if="folderPreview.subtitle_entries?.length" class="subtitle-info-card">
              <div class="subtitle-info-card-header">
                <FileText class="w-4 h-4 text-slate-400" />
                <h3>字幕候选文件树</h3>
                <span class="lib-chip lib-chip-info ml-auto">
                  {{ folderPreview.subtitle_entries.length }} 项
                </span>
              </div>
              <div class="subtitle-info-card-body">
                <div class="subtitle-tree">
                  <div
                    v-for="node in buildSubtitleEntryTreeRows(folderPreview.subtitle_entries)"
                    :key="node.key"
                    class="subtitle-tree-row"
                    :style="{ paddingLeft: `${node.depth * 16 + 10}px` }"
                  >
                    <span class="subtitle-tree-bullet">{{ node.isDir ? '▸' : '└' }}</span>
                    <span class="subtitle-tree-name" :class="node.isDir ? 'is-dir' : 'is-file'">
                      {{ node.name }}
                    </span>
                  </div>
                </div>
              </div>
            </article>

            <article class="subtitle-info-card">
              <div class="subtitle-info-card-header">
                <FolderTree class="w-4 h-4 text-slate-400" />
                <h3>目标目录候选</h3>
                <span class="lib-chip lib-chip-info ml-auto">{{ folderPreview.candidate_count ?? 0 }} 个</span>
              </div>
              <div class="subtitle-info-card-body">
                <AppEmptyState
                  v-if="!folderPreview.candidates?.length"
                  description="没有找到目标目录候选"
                  size="sm"
                />
                <div v-else class="subtitle-candidate-list">
                  <button
                    v-for="candidate in folderPreview.candidates"
                    :key="candidateKey(candidate)"
                    type="button"
                    class="subtitle-candidate-card"
                    :class="{ 'is-selected': folderCandidateSelection === candidateKey(candidate) }"
                    @click="folderCandidateSelection = candidateKey(candidate)"
                  >
                    <span
                      class="subtitle-candidate-radio"
                      :class="{ 'is-checked': folderCandidateSelection === candidateKey(candidate) }"
                    >
                      <span
                        v-if="folderCandidateSelection === candidateKey(candidate)"
                        class="subtitle-candidate-radio-dot"
                      ></span>
                    </span>
                    <div class="subtitle-candidate-body">
                      <h4 class="subtitle-candidate-name">{{ candidate.folder_name || candidate.folder_path }}</h4>
                      <div class="subtitle-candidate-chips">
                        <span class="lib-chip lib-chip-info">{{ candidate.library_name }}</span>
                        <span
                          class="lib-chip"
                          :class="candidate.library_type === 'synology_filestation' ? 'lib-chip-warning' : 'lib-chip-success'"
                        >
                          {{ candidate.library_type === 'synology_filestation' ? '远程' : '本地' }}
                        </span>
                        <span class="lib-chip lib-chip-info">音频 {{ candidate.audio_count ?? 0 }}</span>
                        <span class="lib-chip lib-chip-info">字幕 {{ candidate.existing_subtitle_count ?? 0 }}</span>
                        <span class="lib-chip lib-chip-info">{{ formatSize(candidate.total_size) }}</span>
                      </div>
                      <div class="subtitle-candidate-path mono">{{ candidate.folder_path }}</div>
                    </div>
                  </button>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section v-else class="subtitle-detail-pane subtitle-detail-placeholder">
          <div class="subtitle-detail-placeholder-inner">
            <FolderOpen class="w-10 h-10 mb-3 text-slate-300" stroke-width="1.4" />
            <p class="text-sm font-medium text-slate-500">输入字幕文件夹路径后做一次预检</p>
            <p class="text-xs text-slate-400 mt-1">预检通过后即可补进库存原作目录</p>
          </div>
        </section>
      </div>
    </div>

    <el-dialog
      v-model="workbenchDialogVisible"
      class="subtitle-workbench-dialog subtitle-import-workbench-dialog"
      append-to-body
      :destroy-on-close="false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :before-close="closeImportWorkbench"
      :show-close="false"
      :z-index="2500"
      align-center
      modal-class="subtitle-workbench-overlay"
      top="2vh"
      width="96vw"
    >
      <SubtitleImportWorkbench
        v-if="workbenchDialogInitialized"
        :task-id="activeWorkbenchTaskId"
        :visible="workbenchDialogVisible"
        :background-active="workbenchBackgroundActive"
        @close="closeImportWorkbench"
        @hide-background="hideImportWorkbenchToBackground"
        @select-task="openImportedTask"
        @state-change="handleWorkbenchStateChange"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { subtitleImportApi } from '../api'
import SubtitleImportWorkbench from '../components/subtitle-import/SubtitleImportWorkbench.vue'
import { useBackgroundWorkbenchManager } from '../composables/useBackgroundWorkbenchManager'

import { useSubtitleImportArchive } from '../composables/useSubtitleImportArchive'
import { useSubtitleImportFolder } from '../composables/useSubtitleImportFolder'
import { useSubtitleImportWorkbench } from '../composables/useSubtitleImportWorkbench'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import {
  Captions,
  RefreshCw,
  Sparkles,
  Inbox,
  Loader2,
  History,
  Archive,
  FolderOpen,
  FolderTree,
  FileText,
  Hash,
  Eraser,
  Trash2,
  ChevronRight,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  RotateCw,
  X,
  Eye,
  Info,
} from 'lucide-vue-next'

const route = useRoute()
const LEGACY_SUBTITLE_OPTIONS_KEY = 'kikoeru.ui.library.rjSubtitleOptions'
const SUBTITLE_IMPORT_OPTIONS_KEY = 'kikoeru.ui.subtitleImport.workbenchOptions'
const SUBTITLE_IMPORT_WORKBENCH_ID = 'subtitle-import-workbench'

const workbenchManager = useBackgroundWorkbenchManager()

function loadJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch (_) {
    return fallback
  }
}

function normalizeSubtitleFilterRule(rule = {}) {
  return {
    target: ['name', 'path', 'all'].includes(rule.target) ? rule.target : 'name',
    name: String(rule.name || ''),
    pattern: String(rule.pattern || ''),
    enabled: rule.enabled !== false
  }
}

function sanitizeSubtitleFilterRules(rules = []) {
  return (rules || [])
    .map(rule => normalizeSubtitleFilterRule(rule))
    .filter(rule => rule.pattern.trim())
    .map(rule => ({
      target: rule.target,
      name: rule.name.trim(),
      pattern: rule.pattern.trim(),
      enabled: rule.enabled !== false
    }))
}

function loadSubtitleImportOptions() {
  const saved = loadJson(SUBTITLE_IMPORT_OPTIONS_KEY, null)
  if (saved && typeof saved === 'object') return saved
  const legacy = loadJson(LEGACY_SUBTITLE_OPTIONS_KEY, {})
  if (legacy && typeof legacy === 'object') {
    try {
      localStorage.setItem(SUBTITLE_IMPORT_OPTIONS_KEY, JSON.stringify(legacy))
    } catch (_) {}
  }
  return legacy
}

function stripTrailingAudioExtension(value = '') {
  let current = String(value || '')
  while (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(current)) {
    current = current.replace(/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i, '')
  }
  return current
}

function formatSubtitleEntryDisplay(entry = '') {
  const normalized = String(entry || '').replace(/\\/g, '/')
  if (!normalized) return ''
  const parts = normalized.split('/')
  const fileName = parts.pop() || ''
  const extMatch = fileName.match(/\.[^.]+$/)
  const subtitleExt = extMatch?.[0] || ''
  const baseName = subtitleExt ? fileName.slice(0, -subtitleExt.length) : fileName
  const cleanedFileName = `${stripTrailingAudioExtension(baseName)}${subtitleExt}`
  return [...parts, cleanedFileName].filter(Boolean).join('/')
}

function buildSubtitleEntryTreeRows(entries = []) {
  const nodeMap = new Map()
  const rows = []
  for (const entry of entries || []) {
    const normalized = formatSubtitleEntryDisplay(entry)
    if (!normalized) continue
    const parts = normalized.split('/').filter(Boolean)
    parts.forEach((part, index) => {
      const path = parts.slice(0, index + 1).join('/')
      if (nodeMap.has(path)) return
      const isDir = index < parts.length - 1
      const node = {
        key: `${isDir ? 'dir' : 'file'}:${path}`,
        name: part,
        depth: index,
        isDir
      }
      nodeMap.set(path, node)
      rows.push(node)
    })
  }
  return rows
}

function getDisplayRJCode(value = '') {
  const normalized = String(value || '').trim().toUpperCase()
  if (!normalized) return ''
  const match = normalized.match(/[RVB]J(?:\d{8}|\d{6})(?!\d)/)
  return match ? match[0] : normalized
}

function getSubtitleWorkbenchFilterOptions() {
  const saved = loadSubtitleImportOptions()
  return {
    useFilterRules: saved?.useFilterRules ?? false,
    subtitleFilterRules: sanitizeSubtitleFilterRules(saved?.subtitleFilterRules || [])
  }
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatSize(size) {
  const value = Number(size || 0)
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const exponent = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  const result = value / (1024 ** exponent)
  return `${result >= 100 || exponent === 0 ? result.toFixed(0) : result.toFixed(1)} ${units[exponent]}`
}

const activeTab = ref('archive')

const {
  workbenchDialogVisible,
  workbenchBackgroundActive,
  workbenchDialogInitialized,
  workbenchBackgroundSummary,
  activeWorkbenchTaskId,
  
  restoreActiveWorkbenchTask,
  openImportedTask,
  openImportWorkbench,
  hideImportWorkbenchToBackground,
  closeImportWorkbench,
  handleWorkbenchStateChange
} = useSubtitleImportWorkbench({
  route,
  workbenchManager,
  SUBTITLE_IMPORT_WORKBENCH_ID
})

const {
  pendingLoading,
  pendingLoadedOnce,
  pendingItems,
  activePendingId,
  executingPendingId,
  retryingPendingId,
  pendingClearLoading,
  archiveCandidateSelection,
  activePendingItem,
  selectedArchiveCandidate,
  canRetryActivePendingPreview,
  
  loadPendingImports,
  clearPendingImports,
  retryActivePendingPreview,
  executePendingImport,
  candidateKey,
  getFileName
} = useSubtitleImportArchive({
  workbenchDialogVisible,
  workbenchBackgroundActive,
  getSubtitleWorkbenchFilterOptions,
  openImportedTask,
  route
})

const {
  folderPath,
  folderPreviewLoading,
  folderImporting,
  folderPreview,
  folderCandidateSelection,
  selectedFolderCandidate,
  canExecuteFolderImport,
  canRetryFolderPreview,

  previewFolderImport,
  executeFolderImport
} = useSubtitleImportFolder({
  getSubtitleWorkbenchFilterOptions,
  openImportedTask,
  candidateKey
})
</script>
<style scoped>
button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; }

/* ==============================================================
 * 页面整体布局：和问题作品 / 库存页一致
 * ============================================================ */
.subtitle-page {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 18px 24px 24px;
  background: transparent;
}

.subtitle-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

/* ==============================================================
 * 顶部 lib-info-strip 状态条（与 Conflicts.vue 同款）
 * ============================================================ */
.lib-info-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr);
  align-items: stretch;
  gap: 0;
  margin-bottom: 14px;
  padding: 16px 20px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
}
.lib-info-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
  padding: 0 18px;
}
.lib-info-item:first-child { padding-left: 0; }
.lib-info-item:last-child { padding-right: 0; }
.lib-info-icon { flex-shrink: 0; margin-top: 3px; }
.lib-info-body { min-width: 0; flex: 1 1 auto; }
.lib-info-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #94a3b8;
  margin-bottom: 4px;
}
.lib-info-value {
  font-size: 13.5px;
  color: #475569;
  line-height: 1.3;
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}
.lib-info-value :deep(b),
.lib-info-value b {
  font-weight: 700;
  font-size: 20px;
  letter-spacing: -0.4px;
  color: #0f172a;
  font-variant-numeric: tabular-nums;
}
.lib-info-meta { color: #94a3b8; font-size: 12px; }
.lib-info-sub {
  margin-top: 4px;
  font-size: 11.5px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lib-info-divider {
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(15, 23, 42, 0.1), transparent);
  align-self: stretch;
}
@media (max-width: 980px) {
  .lib-info-strip { grid-template-columns: 1fr; gap: 14px; padding: 16px 18px; }
  .lib-info-divider { display: none; }
  .lib-info-item { padding: 0; }
}

/* ==============================================================
 * 通用 lib-chip：success / warning / danger / info
 * ============================================================ */
.lib-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.lib-chip-success { background: rgba(220, 252, 231, 0.8); color: #047857; border: 1px solid rgba(134, 239, 172, 0.5); }
.lib-chip-warning { background: rgba(254, 243, 199, 0.8); color: #b45309; border: 1px solid rgba(253, 224, 71, 0.5); }
.lib-chip-danger  { background: rgba(254, 226, 226, 0.8); color: #b91c1c; border: 1px solid rgba(252, 165, 165, 0.5); }
.lib-chip-info    { background: rgba(224, 231, 255, 0.85); color: #4338ca; border: 1px solid rgba(165, 180, 252, 0.5); }
.ml-auto { margin-left: auto; }

/* ==============================================================
 * 页头 / 详情区操作按钮：对齐 ActivityHistory.vue 的 page-head-btn 规范
 *  - 基础形态：白底 ghost（hover 上浮 + 软阴影）
 *  - is-primary：黑灰渐变 + 软阴影（操作记录页同款）
 * ============================================================ */
.subtitle-refresh-btn,
.subtitle-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: #fff;
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
  will-change: transform, opacity;
}
.subtitle-refresh-btn :deep(svg),
.subtitle-action-btn :deep(svg) {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.subtitle-refresh-btn:hover,
.subtitle-action-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}
.subtitle-refresh-btn:active:not(:disabled),
.subtitle-action-btn:active:not(:disabled) {
  transform: scale(0.96);
  transition:
    transform 0.12s ease,
    box-shadow 0.18s ease,
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    opacity 0.2s ease;
}
/* disabled：仅 opacity + cursor，不重置 transform/shadow，避免 hover 中点击瞬间塌回闪烁 */
.subtitle-refresh-btn:disabled,
.subtitle-action-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.subtitle-action-btn.lg { height: 40px; padding: 0 18px; font-size: 13.5px; }

/* is-primary：黑灰渐变（操作记录页 primary 同款）*/
.subtitle-action-btn.is-primary {
  background: linear-gradient(135deg, #111827, #1e293b);
  color: #fff;
  border-color: transparent;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}
.subtitle-action-btn.is-primary:hover {
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.22);
}

/* is-slate：保持白底 ghost（基础形态即可，这里仅作语义占位）*/
.subtitle-action-btn.is-slate {
  background: #fff;
  color: #1e293b;
}

/* ==============================================================
 * Tabs segmented：白底 active + 软背景
 * ============================================================ */
.subtitle-segmented {
  display: inline-flex;
  align-self: flex-start;
  gap: 0;
  padding: 4px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid rgba(15, 23, 42, 0.06);
}
.subtitle-segmented-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  border: 0;
  background: transparent;
  font-size: 12.5px;
  font-weight: 500;
  color: #64748b;
  transition: all 0.2s ease;
}
.subtitle-segmented-item:hover { color: #334155; }
.subtitle-segmented-item.is-active {
  background: #fff;
  color: #0f172a;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  font-weight: 600;
}
.subtitle-segmented-item.is-active :deep(svg) { color: #2563eb; }

/* ==============================================================
 * 双栏主工作区
 * ============================================================ */
.subtitle-main {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 18px;
}

/* 左侧 list-pane / source-pane */
.subtitle-list-pane {
  width: 360px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}
@media (min-width: 1280px) {
  .subtitle-list-pane { width: 380px; }
}

.subtitle-list-header {
  flex-shrink: 0;
  padding: 14px 16px 12px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(248, 250, 252, 0.45);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.subtitle-list-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.subtitle-list-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  letter-spacing: -0.2px;
}
.subtitle-list-actions {
  display: flex;
  gap: 6px;
}
.subtitle-mini-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #fff;
  color: #475569;
  font-size: 11.5px;
  font-weight: 500;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.subtitle-mini-btn:hover {
  background: #f8fafc;
  border-color: rgba(15, 23, 42, 0.18);
  color: #0f172a;
}
.subtitle-mini-btn.is-danger {
  color: #b91c1c;
  border-color: rgba(252, 165, 165, 0.6);
}
.subtitle-mini-btn.is-danger:hover {
  background: rgba(254, 226, 226, 0.5);
  border-color: rgba(248, 113, 113, 0.7);
  color: #991b1b;
}
.subtitle-mini-btn:disabled { opacity: 0.5; }
.subtitle-list-hint {
  margin: 0;
  font-size: 10.5px;
  color: #94a3b8;
  text-align: center;
}

/* 列表滚动区 */
.subtitle-list-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 280px;
}

/* 列表卡片：和 conflicts-list-card 同款 */
.subtitle-list-card {
  position: relative;
  width: 100%;
  text-align: left;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  transition: background-color 0.18s ease, border-color 0.18s ease;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: hidden;
}
.subtitle-list-card:hover {
  background: rgba(15, 23, 42, 0.04);
  border-color: rgba(15, 23, 42, 0.06);
}
.subtitle-list-card.is-active {
  background: #e2e8f0;
  border-color: rgba(15, 23, 42, 0.18);
}
.subtitle-list-card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.subtitle-list-card-title {
  flex: 1;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  letter-spacing: -0.2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.subtitle-list-card-chev {
  opacity: 0;
  transform: translateX(-4px);
  transition: opacity 0.25s ease, transform 0.25s ease;
  color: #2563eb;
  flex-shrink: 0;
}
.subtitle-list-card:hover .subtitle-list-card-chev,
.subtitle-list-card.is-active .subtitle-list-card-chev {
  opacity: 1;
  transform: translateX(0);
}
.subtitle-list-card-source {
  font-size: 11.5px;
  color: #64748b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.subtitle-list-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: #94a3b8;
}
.subtitle-list-card-arrow {
  display: inline-flex;
  align-items: center;
  color: #64748b;
  font-weight: 500;
}
.subtitle-list-card-count {
  color: #2563eb;
  font-weight: 600;
}

/* ==============================================================
 * 右侧 detail-pane
 * ============================================================ */
.subtitle-detail-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

.subtitle-detail-header {
  position: relative;
  flex-shrink: 0;
  padding: 22px 26px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: linear-gradient(180deg, #f8fafc 0%, #eff6ff 100%);
  overflow: hidden;
}
.subtitle-detail-bg-glyph {
  position: absolute;
  top: -20px;
  right: -20px;
  color: #3b82f6;
  opacity: 0.07;
  pointer-events: none;
}
.subtitle-detail-header-inner {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
@media (min-width: 1280px) {
  .subtitle-detail-header-inner {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
  }
}
.subtitle-detail-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.4px;
  color: #0f172a;
  line-height: 1.2;
}
.subtitle-detail-subtitle {
  margin: 6px 0 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
  color: #64748b;
  word-break: break-all;
}
.subtitle-detail-dot {
  display: inline-block;
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 999px;
}
.subtitle-detail-dot.is-info { background: #2563eb; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18); }
.subtitle-detail-dot.is-warning { background: #f59e0b; box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.15); }
.subtitle-detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.subtitle-detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: transparent;
}

/* 占位：未选中状态 */
.subtitle-detail-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.subtitle-detail-placeholder-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 28px;
}

/* ==============================================================
 * 状态提示框
 * ============================================================ */
.subtitle-detail-alert {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid;
  font-size: 12.5px;
  line-height: 1.6;
}
.subtitle-detail-alert p { margin: 0; }
.subtitle-detail-alert.is-info {
  background: rgba(219, 234, 254, 0.55);
  border-color: rgba(96, 165, 250, 0.3);
  color: #1e40af;
}
.subtitle-detail-alert.is-warning {
  background: rgba(254, 243, 199, 0.55);
  border-color: rgba(245, 158, 11, 0.2);
  color: #92400e;
}

/* ==============================================================
 * info-card：信息卡片（和 conflicts-info-card 同款）
 * ============================================================ */
.subtitle-info-card {
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  overflow: hidden;
}
.subtitle-info-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  background: #f8fafc;
}
.subtitle-info-card-header h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  letter-spacing: -0.2px;
}
.subtitle-info-card-body {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 字段网格 */
.subtitle-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
@media (min-width: 720px) {
  .subtitle-meta-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
.subtitle-meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.05);
  min-width: 0;
}
.subtitle-meta-item.is-wide { grid-column: 1 / -1; }
.subtitle-meta-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #94a3b8;
}
.subtitle-meta-value {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
}
.subtitle-meta-value.mono {
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
  font-size: 12.5px;
  font-weight: 700;
}
.subtitle-meta-value.is-strong { color: #2563eb; }
.subtitle-meta-value-muted {
  margin: 0;
  font-size: 12px;
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.subtitle-meta-value-muted.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 字幕文件树 */
.subtitle-tree {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.05);
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
  font-size: 11.5px;
  max-height: 240px;
  overflow-y: auto;
}
.subtitle-tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  border-radius: 6px;
  transition: background-color 0.15s ease;
}
.subtitle-tree-row:hover {
  background: rgba(37, 99, 235, 0.06);
}
.subtitle-tree-bullet {
  flex-shrink: 0;
  color: #94a3b8;
  font-weight: 600;
}
.subtitle-tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.subtitle-tree-name.is-dir { color: #0f172a; font-weight: 600; }
.subtitle-tree-name.is-file { color: #475569; }

/* ==============================================================
 * 候选目录卡片
 * ============================================================ */
.subtitle-candidate-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.subtitle-candidate-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #fff;
  text-align: left;
  transition: border-color 0.18s ease, background-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}
.subtitle-candidate-card:hover {
  border-color: rgba(37, 99, 235, 0.3);
  background: rgba(239, 246, 255, 0.5);
  transform: translateY(-1px);
  box-shadow: 0 6px 14px -8px rgba(37, 99, 235, 0.18);
}
.subtitle-candidate-card.is-selected {
  border-color: rgba(37, 99, 235, 0.55);
  background: rgba(219, 234, 254, 0.45);
  box-shadow: 0 1px 2px rgba(37, 99, 235, 0.1), 0 8px 18px -10px rgba(37, 99, 235, 0.32);
}
.subtitle-candidate-radio {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  border-radius: 999px;
  border: 2px solid rgba(15, 23, 42, 0.2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  transition: border-color 0.18s ease, background-color 0.18s ease;
}
.subtitle-candidate-radio.is-checked {
  border-color: #2563eb;
  background: #2563eb;
}
.subtitle-candidate-radio-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #fff;
}
.subtitle-candidate-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.subtitle-candidate-name {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  letter-spacing: -0.2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.subtitle-candidate-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.subtitle-candidate-path {
  font-size: 10.5px;
  color: #94a3b8;
  word-break: break-all;
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
  line-height: 1.5;
}
.subtitle-candidate-path.mono { font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace; }

/* ==============================================================
 * 详情底部提交栏
 * ============================================================ */
.subtitle-detail-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

/* ==============================================================
 * 字幕文件夹补配 - 表单
 * ============================================================ */
.subtitle-form-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
}
.subtitle-form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.subtitle-form-label {
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #475569;
  text-transform: uppercase;
}
.subtitle-form-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  height: 36px;
  border-radius: 10px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.12);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}
.subtitle-form-input-wrap:focus-within {
  border-color: rgba(37, 99, 235, 0.45);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}
.subtitle-form-input {
  flex: 1;
  height: 100%;
  padding: 0 36px 0 14px;
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 13px;
  color: #0f172a;
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
}
.subtitle-form-input::placeholder { color: rgba(15, 23, 42, 0.4); font-family: inherit; }
.subtitle-form-clear {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: 0;
  background: transparent;
  color: rgba(15, 23, 42, 0.45);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.18s ease, color 0.18s ease;
}
.subtitle-form-clear:hover {
  background: rgba(15, 23, 42, 0.06);
  color: #0f172a;
}
.subtitle-form-actions {
  display: flex;
  gap: 8px;
}
.subtitle-form-actions .subtitle-action-btn { flex: 1; justify-content: center; }
.subtitle-form-hint-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(219, 234, 254, 0.4);
  border: 1px solid rgba(147, 197, 253, 0.4);
  font-size: 12px;
  line-height: 1.6;
  color: #1e40af;
}
.subtitle-form-hint-card p { margin: 0; }

/* ==============================================================
 * 滚动条：和项目其他页面一致
 * ============================================================ */
.no-scrollbar::-webkit-scrollbar { width: 6px; }
.no-scrollbar::-webkit-scrollbar-track { background: transparent; }
.no-scrollbar::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.32); border-radius: 999px; }
.no-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(100, 116, 139, 0.5); }
.subtitle-tree::-webkit-scrollbar { width: 4px; }
.subtitle-tree::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.4); border-radius: 4px; }

/* ==============================================================
 * 工作台 dialog 全局样式（保留）
 * ============================================================ */
:global(.subtitle-import-workbench-dialog) {
  padding: 0;
  border-radius: 24px;
  overflow: hidden;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  box-shadow: 0 26px 80px rgba(15, 23, 42, 0.16);
}
:global(.subtitle-import-workbench-dialog .el-dialog__header) { display: none; }
:global(.subtitle-import-workbench-dialog .el-dialog__body) { padding: 0; max-height: calc(100vh - 18px); overflow: hidden; }
:global(.subtitle-workbench-overlay) { background: rgba(15, 23, 42, 0.58); backdrop-filter: blur(2px); }

/* 屏幕较窄时双栏退化为单列 */
@media (max-width: 1080px) {
  .subtitle-main { flex-direction: column; }
  .subtitle-list-pane { width: 100%; }
}
</style>
