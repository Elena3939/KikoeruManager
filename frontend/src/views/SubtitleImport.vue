<template>
  <div class="subtitle-page">
    <!-- 页头：和库存页 / 问题作品页保持一致的 AppPageHeader 共享组件 -->
    <AppPageHeader
      :icon="Captions"
      icon-color="var(--km-nav-subtitle-icon)"
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

    <section class="subtitle-dashboard" aria-label="字幕补配状态">
      <article class="subtitle-dashboard-item is-pending">
        <div class="subtitle-dashboard-icon">
          <Inbox :size="16" :stroke-width="2.2" />
        </div>
        <div class="subtitle-dashboard-copy">
          <span>预检单</span>
          <strong>{{ pendingItems.length }}</strong>
          <p>自动检测后等待确认的压缩包来源</p>
        </div>
      </article>
      <article class="subtitle-dashboard-item is-running">
        <div class="subtitle-dashboard-icon">
          <Loader2 :size="16" :stroke-width="2.2" />
        </div>
        <div class="subtitle-dashboard-copy">
          <span>进行中</span>
          <strong>{{ workbenchBackgroundSummary.processing || 0 }}</strong>
          <p>正在匹配、清理或应用字幕的任务</p>
        </div>
      </article>
      <article class="subtitle-dashboard-item is-total">
        <div class="subtitle-dashboard-icon">
          <History :size="16" :stroke-width="2.2" />
        </div>
        <div class="subtitle-dashboard-copy">
          <span>本会话</span>
          <strong>{{ workbenchBackgroundSummary.total || 0 }}</strong>
          <p>本次打开后进入工作台的补配任务</p>
        </div>
      </article>
    </section>

    <div v-show="!workbenchDialogVisible" class="subtitle-shell">
      <div class="subtitle-shell-head">
        <div class="subtitle-shell-copy">
          <span>补配入口</span>
          <strong>先确认来源，再把字幕送进库存原作目录</strong>
        </div>
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
                :disabled="!canClearActivePending || pendingClearLoading"
                @click="clearPendingImports(false)"
              >
                <Eraser class="w-3.5 h-3.5" />
                清除当前
              </button>
              <button
                type="button"
                class="subtitle-mini-btn is-danger"
                :disabled="!clearablePendingCount || pendingClearLoading"
                @click="clearPendingImports(true)"
              >
                <Trash2 class="w-3.5 h-3.5" />
                清空
              </button>
            </div>
            <p class="subtitle-list-hint">
              {{ clearablePendingCount ? `可清理记录 ${clearablePendingCount} 条` : '当前列表没有可清理记录' }}
            </p>
          </div>
          <div class="subtitle-list-scroll no-scrollbar">
            <AppLoadingAnimation
              v-if="pendingLoading && !pendingItems.length"
              label="加载预检单"
              description="正在同步字幕补配列表"
              :size="88"
              :min-height="260"
              class="subtitle-list-loading"
            />
            <AppEmptyState
              v-else-if="pendingLoadedOnce && !pendingItems.length"
              description="没有待处理的预检单"
              size="sm"
              class="my-auto"
            />
            <TransitionGroup
              v-else
              :key="pendingListPage"
              name="subtitle-list-page"
              tag="div"
              class="subtitle-list-page-stack"
              :class="`is-${pendingListPageDirection}`"
            >
              <button
                v-for="item in pagedPendingItems"
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
                  <span class="lib-chip" :class="getArchiveItemStateClass(item)">
                    {{ getArchiveItemStateLabel(item) }}
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
            </TransitionGroup>
          </div>
          <div
            v-if="pendingListTotalPages > 1"
            class="subtitle-list-pager"
          >
            <button
              type="button"
              class="subtitle-list-page-btn"
              :disabled="pendingListPage <= 1"
              @click="setPendingListPage(pendingListPage - 1)"
            >
              上一页
            </button>
            <span class="subtitle-list-page-indicator">
              {{ pendingListPage }} / {{ pendingListTotalPages }}
            </span>
            <button
              type="button"
              class="subtitle-list-page-btn"
              :disabled="pendingListPage >= pendingListTotalPages"
              @click="setPendingListPage(pendingListPage + 1)"
            >
              下一页
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
                <button
                  v-if="isImportedPendingItem(activePendingItem) && getPendingItemWorkbenchTaskId(activePendingItem)"
                  type="button"
                  class="subtitle-action-btn is-primary"
                  @click="openPendingItemWorkbench(activePendingItem)"
                >
                  <Sparkles class="w-3.5 h-3.5" />
                  打开工作台
                </button>
                <span
                  class="lib-chip"
                  :class="getArchiveItemStateClass(activePendingItem)"
                >
                  {{ getArchiveItemStateLabel(activePendingItem) }}
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
                {{ getArchiveItemReason(activePendingItem) }}
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
                v-if="isImportedPendingItem(activePendingItem) && getPendingItemWorkbenchTaskId(activePendingItem)"
                type="button"
                class="subtitle-action-btn is-primary lg"
                @click="openPendingItemWorkbench(activePendingItem)"
              >
                <Sparkles class="w-4 h-4" />
                打开对应工作台
              </button>
              <button
                v-else
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
          <AppLoadingAnimation
            v-if="pendingLoading && !pendingItems.length"
            label="加载预检单"
            description="同步完成后会在这里显示预检详情"
            :size="96"
            :min-height="320"
          />
          <div v-else class="subtitle-detail-placeholder-inner">
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

    <Teleport to="body">
      <transition name="subtitle-import-workbench-fade">
        <div
          v-if="workbenchDialogVisible"
          class="subtitle-import-workbench-overlay"
          role="presentation"
        >
          <section
          class="subtitle-import-workbench-modal subtitle-workbench-dialog subtitle-import-workbench-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="字幕补配工作台"
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
          </section>
        </div>
      </transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
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
const PENDING_LIST_PAGE_SIZE = 6

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
  const raw = typeof entry === 'object' && entry !== null
    ? (entry.relative_path || entry.path || entry.name || '')
    : entry
  const normalized = String(raw || '').replace(/\\/g, '/')
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

function getPagedItems(items = [], page = 1, pageSize = PENDING_LIST_PAGE_SIZE) {
  const source = Array.isArray(items) ? items : []
  const safePageSize = Math.max(1, Number(pageSize) || PENDING_LIST_PAGE_SIZE)
  const totalPages = Math.max(1, Math.ceil(source.length / safePageSize))
  const safePage = Math.min(Math.max(1, Number(page) || 1), totalPages)
  const start = (safePage - 1) * safePageSize
  return source.slice(start, start + safePageSize)
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

function getArchiveItemStateLabel(item) {
  const status = String(item?.status || '').trim().toUpperCase()
  if (status === 'IMPORTED') return '已入工作台'
  if (item?.can_execute) return '可执行'
  return '不可执行'
}

function getArchiveItemStateClass(item) {
  const status = String(item?.status || '').trim().toUpperCase()
  if (status === 'IMPORTED') return 'lib-chip-info'
  if (item?.can_execute) return 'lib-chip-success'
  return 'lib-chip-warning'
}

function getArchiveItemReason(item) {
  if (!item) return ''
  const status = String(item.status || '').trim().toUpperCase()
  if (status === 'IMPORTED') {
    return '这条来源已经导入字幕补配工作台；清除会废弃对应补配上下文，不会删除原始压缩包。'
  }
  return item.preview?.reason || (item.can_execute ? '目标原作已定位，可以继续导入。' : '当前这条来源暂时无法执行。')
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
  clearablePendingCount,
  canClearActivePending,
  archiveCandidateSelection,
  activePendingItem,
  selectedArchiveCandidate,
  canRetryActivePendingPreview,
  
  isImportedPendingItem,
  getPendingItemWorkbenchTaskId,
  loadPendingImports,
  clearPendingImports,
  openPendingItemWorkbench,
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

const pendingListPage = ref(1)
const pendingListPageDirection = ref('next')
const pendingListTotalPages = computed(() => (
  Math.max(1, Math.ceil(pendingItems.value.length / PENDING_LIST_PAGE_SIZE))
))
const pagedPendingItems = computed(() => (
  getPagedItems(pendingItems.value, pendingListPage.value, PENDING_LIST_PAGE_SIZE)
))

function setPendingListPage(page) {
  const next = Math.min(Math.max(1, Number(page) || 1), pendingListTotalPages.value)
  pendingListPageDirection.value = next >= pendingListPage.value ? 'next' : 'prev'
  pendingListPage.value = next
  const currentPageIds = new Set(pagedPendingItems.value.map(item => item.id))
  if (!currentPageIds.has(activePendingId.value)) {
    activePendingId.value = pagedPendingItems.value[0]?.id || ''
  }
}

function syncPendingListPageForActive() {
  const index = pendingItems.value.findIndex(item => item.id === activePendingId.value)
  if (index < 0) return
  const targetPage = Math.floor(index / PENDING_LIST_PAGE_SIZE) + 1
  if (targetPage !== pendingListPage.value) {
    pendingListPageDirection.value = targetPage >= pendingListPage.value ? 'next' : 'prev'
    pendingListPage.value = targetPage
  }
}

watch(pendingListTotalPages, total => {
  if (pendingListPage.value > total) pendingListPage.value = total
  if (pendingListPage.value < 1) pendingListPage.value = 1
})

watch(activePendingId, () => {
  syncPendingListPageForActive()
})

watch(() => pendingItems.value.map(item => item.id).join('|'), () => {
  syncPendingListPageForActive()
})
</script>
<style scoped>
button:not(:disabled) { cursor: pointer; }
button:disabled { cursor: not-allowed; }

.subtitle-page :is(button, input):focus,
.subtitle-page :is(button, input):focus-visible {
  outline: none;
  box-shadow: none;
}

/* ==============================================================
 * 页面整体布局：和问题作品 / 库存页一致
 * ============================================================ */
.subtitle-page {
  --subtitle-panel: #ffffff;
  --subtitle-panel-soft: #ffffff;
  --subtitle-panel-muted: #ffffff;
  --subtitle-border: rgba(15, 23, 42, 0.08);
  --subtitle-border-strong: rgba(15, 23, 42, 0.14);
  --subtitle-text: #0f172a;
  --subtitle-text-muted: #64748b;
  --subtitle-text-soft: #94a3b8;
  --subtitle-primary: #111827;
  --subtitle-primary-soft: rgba(15, 23, 42, 0.035);
  --subtitle-success: #047857;
  --subtitle-warning: #b45309;
  --subtitle-danger: #b91c1c;
  --subtitle-shadow: none;
  --subtitle-control-motion: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 18px 24px 22px;
  background: #ffffff;
}

.subtitle-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  padding: 12px 0 0;
  border-radius: 0;
  border: 0;
  background: #ffffff;
  box-shadow: var(--subtitle-shadow);
  overflow: hidden;
}

.subtitle-shell-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-shrink: 0;
}

.subtitle-shell-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.subtitle-shell-copy span {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--subtitle-text-soft);
}

.subtitle-shell-copy strong {
  font-size: 13px;
  font-weight: 650;
  color: var(--subtitle-text);
  line-height: 1.35;
}

.subtitle-dashboard {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.subtitle-dashboard-item {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid var(--subtitle-border);
  background: var(--subtitle-panel);
  box-shadow: none;
}

.subtitle-dashboard-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 10px;
  border: 0;
  background: transparent;
  color: var(--subtitle-text-muted);
}

.subtitle-dashboard-item.is-pending .subtitle-dashboard-icon { color: #b45309; }
.subtitle-dashboard-item.is-running .subtitle-dashboard-icon { color: #475569; }
.subtitle-dashboard-item.is-total .subtitle-dashboard-icon { color: #047857; }

.subtitle-dashboard-copy {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: baseline;
  column-gap: 8px;
  row-gap: 2px;
  min-width: 0;
}

.subtitle-dashboard-copy span {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--subtitle-text-soft);
}

.subtitle-dashboard-copy strong {
  color: var(--subtitle-text);
  font-size: 21px;
  font-weight: 750;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.subtitle-dashboard-copy p {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--subtitle-text-muted);
  font-size: 11.5px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 980px) {
  .subtitle-dashboard { grid-template-columns: 1fr; }
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
.lib-chip-success { background: rgba(220, 252, 231, 0.8); color: var(--subtitle-success); border: 1px solid rgba(134, 239, 172, 0.5); }
.lib-chip-warning { background: rgba(254, 243, 199, 0.8); color: var(--subtitle-warning); border: 1px solid rgba(253, 224, 71, 0.5); }
.lib-chip-danger  { background: rgba(254, 226, 226, 0.8); color: var(--subtitle-danger); border: 1px solid rgba(252, 165, 165, 0.5); }
.lib-chip-info    { background: #ffffff; color: var(--subtitle-text-muted); border: 1px solid var(--subtitle-border); }
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
  border: 1px solid var(--subtitle-border-strong);
  background: var(--subtitle-panel);
  color: var(--subtitle-text);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition: var(--subtitle-control-motion);
  will-change: transform, opacity;
}
.subtitle-refresh-btn :deep(svg),
.subtitle-action-btn :deep(svg) {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  transition: var(--subtitle-control-motion);
}
.subtitle-refresh-btn:hover,
.subtitle-action-btn:hover {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--subtitle-border-strong);
  background: #ffffff;
  box-shadow: none;
}
.subtitle-refresh-btn:hover :deep(svg),
.subtitle-action-btn:hover :deep(svg) {
  transform: rotate(-8deg) scale(1.08);
}
.subtitle-refresh-btn:active:not(:disabled),
.subtitle-action-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.subtitle-refresh-btn:disabled,
.subtitle-action-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.subtitle-action-btn.lg { height: 40px; padding: 0 18px; font-size: 13.5px; }

/* is-primary：黑灰渐变（操作记录页 primary 同款）*/
.subtitle-action-btn.is-primary {
  background: linear-gradient(135deg, #111827, #27272a);
  color: #fff;
  border-color: transparent;
  box-shadow: none;
}
.subtitle-action-btn.is-primary:hover {
  box-shadow: none;
}

/* is-slate：保持白底 ghost（基础形态即可，这里仅作语义占位）*/
.subtitle-action-btn.is-slate {
  background: var(--subtitle-panel);
  color: var(--subtitle-text);
}

/* ==============================================================
 * Tabs segmented：白底 active + 软背景
 * ============================================================ */
.subtitle-segmented {
  display: inline-flex;
  align-self: flex-end;
  gap: 2px;
  padding: 4px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid var(--subtitle-border);
}
.subtitle-segmented-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 15px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  font-size: 12.5px;
  font-weight: 650;
  color: var(--subtitle-text-muted);
  transition: var(--subtitle-control-motion);
}
.subtitle-segmented-item:hover {
  color: var(--subtitle-text);
  transform: translateY(-1px);
}
.subtitle-segmented-item.is-active {
  border-color: var(--subtitle-border-strong);
  background: #ffffff;
  color: var(--subtitle-text);
  box-shadow: none;
  font-weight: 750;
}
.subtitle-segmented-item.is-active :deep(svg) { color: var(--subtitle-text); }

/* ==============================================================
 * 双栏主工作区
 * ============================================================ */
.subtitle-main {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 16px;
  border-top: 1px solid var(--subtitle-border);
  padding-top: 12px;
}

/* 左侧 list-pane / source-pane */
.subtitle-list-pane {
  width: 332px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-radius: 16px;
  background: var(--subtitle-panel);
  border: 1px solid var(--subtitle-border);
  box-shadow: none;
  overflow: hidden;
}
@media (min-width: 1280px) {
  .subtitle-list-pane { width: 352px; }
}

.subtitle-list-header {
  flex-shrink: 0;
  padding: 14px 14px 12px;
  border-bottom: 1px solid var(--subtitle-border);
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 9px;
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
  font-weight: 700;
  color: var(--subtitle-text);
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
  border-radius: 9px;
  border: 1px solid var(--subtitle-border);
  background: var(--subtitle-panel);
  color: var(--subtitle-text-muted);
  font-size: 11.5px;
  font-weight: 650;
  transition: var(--subtitle-control-motion);
}
.subtitle-mini-btn:hover {
  background: #ffffff;
  border-color: var(--subtitle-border-strong);
  color: var(--subtitle-text);
  transform: translateY(-2px) scale(1.02);
}
.subtitle-mini-btn:hover :deep(svg) {
  transform: rotate(-8deg) scale(1.08);
}
.subtitle-mini-btn.is-danger {
  color: var(--subtitle-danger);
  border-color: rgba(252, 165, 165, 0.6);
}
.subtitle-mini-btn.is-danger:hover {
  background: rgba(254, 226, 226, 0.5);
  border-color: rgba(248, 113, 113, 0.7);
  color: var(--subtitle-danger);
}
.subtitle-mini-btn:disabled { opacity: 0.5; }
.subtitle-list-hint {
  margin: 0;
  font-size: 10.5px;
  color: var(--subtitle-text-soft);
  text-align: center;
}

/* 列表滚动区 */
.subtitle-list-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 240px;
}
.subtitle-list-page-stack {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
}
.subtitle-list-page-stack .subtitle-list-card:nth-child(1) { transition-delay: 0ms; }
.subtitle-list-page-stack .subtitle-list-card:nth-child(2) { transition-delay: 18ms; }
.subtitle-list-page-stack .subtitle-list-card:nth-child(3) { transition-delay: 36ms; }
.subtitle-list-page-stack .subtitle-list-card:nth-child(4) { transition-delay: 54ms; }
.subtitle-list-page-stack .subtitle-list-card:nth-child(5) { transition-delay: 72ms; }
.subtitle-list-page-stack .subtitle-list-card:nth-child(6) { transition-delay: 90ms; }
.subtitle-list-page-enter-active {
  transition:
    opacity 0.26s ease,
    transform 0.34s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.subtitle-list-page-leave-active {
  position: absolute;
  inset-inline: 0;
  transition:
    opacity 0.16s ease,
    transform 0.2s ease;
}
.subtitle-list-page-stack.is-next .subtitle-list-page-enter-from {
  opacity: 0;
  transform: translateX(22px) scale(0.985);
}
.subtitle-list-page-stack.is-prev .subtitle-list-page-enter-from {
  opacity: 0;
  transform: translateX(-22px) scale(0.985);
}
.subtitle-list-page-stack.is-next .subtitle-list-page-leave-to {
  opacity: 0;
  transform: translateX(-16px) scale(0.985);
}
.subtitle-list-page-stack.is-prev .subtitle-list-page-leave-to {
  opacity: 0;
  transform: translateX(16px) scale(0.985);
}
.subtitle-list-page-move {
  transition: transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.subtitle-list-pager {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--subtitle-border);
  background: var(--subtitle-panel);
}
.subtitle-list-page-btn {
  min-height: 30px;
  border: 1px solid var(--subtitle-border);
  border-radius: 9px;
  background: var(--subtitle-panel);
  color: var(--subtitle-text-muted);
  padding: 0 11px;
  font-size: 11.5px;
  font-weight: 700;
  transition: var(--subtitle-control-motion);
}
.subtitle-list-page-btn:hover:not(:disabled) {
  border-color: var(--subtitle-border-strong);
  color: var(--subtitle-text);
  transform: translateY(-2px) scale(1.02);
}
.subtitle-list-page-btn:active:not(:disabled) {
  transform: scale(0.96);
}
.subtitle-list-page-btn:disabled {
  opacity: 0.45;
}
.subtitle-list-page-indicator {
  min-width: 62px;
  border: 1px solid var(--subtitle-border);
  border-radius: 9px;
  background: var(--subtitle-primary-soft);
  color: var(--subtitle-text-muted);
  padding: 7px 9px;
  text-align: center;
  font-size: 11.5px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
}

/* 列表卡片：和 conflicts-list-card 同款 */
.subtitle-list-card {
  position: relative;
  width: 100%;
  text-align: left;
  padding: 11px 12px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: transparent;
  transition: var(--subtitle-control-motion);
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: hidden;
}
.subtitle-list-card:hover {
  background: var(--subtitle-primary-soft);
  border-color: var(--subtitle-border);
  transform: translateY(-1px);
}
.subtitle-list-card.is-active {
  background: #ffffff;
  border-color: var(--subtitle-border-strong);
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
  color: var(--subtitle-text);
  letter-spacing: -0.2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.subtitle-list-card-chev {
  opacity: 0;
  transform: translateX(-4px);
  transition: opacity 0.25s ease, transform 0.25s ease;
  color: var(--subtitle-text-muted);
  flex-shrink: 0;
}
.subtitle-list-card:hover .subtitle-list-card-chev,
.subtitle-list-card.is-active .subtitle-list-card-chev {
  opacity: 1;
  transform: translateX(0);
}
.subtitle-list-card-source {
  font-size: 11.5px;
  color: var(--subtitle-text-muted);
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
  color: var(--subtitle-text-soft);
}
.subtitle-list-card-arrow {
  display: inline-flex;
  align-items: center;
  color: var(--subtitle-text-muted);
  font-weight: 500;
}
.subtitle-list-card-count {
  color: var(--subtitle-text);
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
  border-radius: 0;
  background: var(--subtitle-panel);
  border: 0;
  border-left: 1px solid var(--subtitle-border);
  box-shadow: none;
  overflow: hidden;
}

.subtitle-detail-header {
  position: relative;
  flex-shrink: 0;
  padding: 8px 20px 16px;
  border-bottom: 1px solid var(--subtitle-border);
  background: #ffffff;
  overflow: hidden;
}
.subtitle-detail-bg-glyph {
  position: absolute;
  top: -20px;
  right: -20px;
  color: var(--subtitle-text-muted);
  opacity: 0.08;
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
  color: var(--subtitle-text);
  line-height: 1.2;
}
.subtitle-detail-subtitle {
  margin: 6px 0 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--subtitle-text-muted);
  word-break: break-all;
}
.subtitle-detail-dot {
  display: inline-block;
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  border-radius: 999px;
}
.subtitle-detail-dot.is-info { background: #64748b; box-shadow: 0 0 0 3px rgba(100, 116, 139, 0.18); }
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
  padding: 14px 20px 20px;
  display: flex;
  flex-direction: column;
  gap: 0;
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
  padding: 36px 28px;
  color: var(--subtitle-text-muted);
}

/* ==============================================================
 * 状态提示框
 * ============================================================ */
.subtitle-detail-alert {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 0 14px;
  border-radius: 0;
  border: 0;
  border-bottom: 1px solid var(--subtitle-border);
  font-size: 12.5px;
  line-height: 1.6;
}
.subtitle-detail-alert p { margin: 0; }
.subtitle-detail-alert.is-info {
  background: transparent;
  color: var(--subtitle-text-muted);
}
.subtitle-detail-alert.is-warning {
  background: transparent;
  border-color: rgba(245, 158, 11, 0.28);
  color: #92400e;
}

/* ==============================================================
 * info-card：信息卡片（和 conflicts-info-card 同款）
 * ============================================================ */
.subtitle-info-card {
  display: flex;
  flex-direction: column;
  border-radius: 0;
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--subtitle-border);
  overflow: visible;
}
.subtitle-info-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 15px 0 10px;
  border-bottom: 0;
  background: transparent;
}
.subtitle-info-card-header h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--subtitle-text);
  letter-spacing: -0.2px;
}
.subtitle-info-card-body {
  padding: 0 0 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 字段网格 */
.subtitle-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0;
  border: 1px solid var(--subtitle-border);
  border-radius: 12px;
  overflow: hidden;
}
@media (min-width: 720px) {
  .subtitle-meta-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
}
.subtitle-meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 11px 13px;
  border-radius: 0;
  background: transparent;
  border: 0;
  border-right: 1px solid var(--subtitle-border);
  border-bottom: 1px solid var(--subtitle-border);
  min-width: 0;
}
.subtitle-meta-item.is-wide { grid-column: 1 / -1; }
.subtitle-meta-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--subtitle-text-soft);
}
.subtitle-meta-value {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--subtitle-text);
}
.subtitle-meta-value.mono {
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
  font-size: 12.5px;
  font-weight: 700;
}
.subtitle-meta-value.is-strong { color: var(--subtitle-text); }
.subtitle-meta-value-muted {
  margin: 0;
  font-size: 12px;
  color: var(--subtitle-text-muted);
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
  padding: 8px 0;
  border-radius: 0;
  background: transparent;
  border: 0;
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
  background: var(--subtitle-primary-soft);
}
.subtitle-tree-bullet {
  flex-shrink: 0;
  color: var(--subtitle-text-soft);
  font-weight: 600;
}
.subtitle-tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.subtitle-tree-name.is-dir { color: var(--subtitle-text); font-weight: 600; }
.subtitle-tree-name.is-file { color: var(--subtitle-text-muted); }

/* ==============================================================
 * 候选目录卡片
 * ============================================================ */
.subtitle-candidate-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid var(--subtitle-border);
  border-radius: 12px;
  overflow: hidden;
}
.subtitle-candidate-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 13px 14px;
  border-radius: 0;
  border: 0;
  border-bottom: 1px solid var(--subtitle-border);
  background: transparent;
  text-align: left;
  transition: var(--subtitle-control-motion);
}
.subtitle-candidate-card:last-child {
  border-bottom: 0;
}
.subtitle-candidate-card:hover {
  border-color: var(--subtitle-border-strong);
  background: var(--subtitle-primary-soft);
  transform: none;
  box-shadow: none;
}
.subtitle-candidate-card.is-selected {
  border-color: var(--subtitle-border);
  background: rgba(15, 23, 42, 0.035);
  box-shadow: none;
}
.subtitle-candidate-radio {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  border-radius: 999px;
  border: 2px solid var(--subtitle-border-strong);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--subtitle-panel);
  transition: var(--subtitle-control-motion);
}
.subtitle-candidate-radio.is-checked {
  border-color: var(--subtitle-success);
  background: var(--subtitle-success);
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
  color: var(--subtitle-text);
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
  color: var(--subtitle-text-soft);
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
  padding-top: 16px;
}

/* ==============================================================
 * 字幕文件夹补配 - 表单
 * ============================================================ */
.subtitle-form-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 14px;
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
  color: var(--subtitle-text-muted);
  text-transform: uppercase;
}
.subtitle-form-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  height: 36px;
  border-radius: 11px;
  background: var(--subtitle-panel);
  border: 1px solid var(--subtitle-border-strong);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}
.subtitle-form-input-wrap:focus-within {
  border-color: var(--subtitle-border-strong);
  background: var(--subtitle-panel);
  box-shadow: none;
}
.subtitle-form-input {
  flex: 1;
  height: 100%;
  padding: 0 36px 0 14px;
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 13px;
  color: var(--subtitle-text);
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
}
.subtitle-form-input::placeholder { color: var(--subtitle-text-soft); font-family: inherit; }
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
  color: var(--subtitle-text-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: var(--subtitle-control-motion);
}
.subtitle-form-clear:hover {
  background: var(--subtitle-panel-muted);
  color: var(--subtitle-text);
  transform: translateY(-50%) scale(1.06);
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
  background: #ffffff;
  border: 1px solid var(--subtitle-border);
  font-size: 12px;
  line-height: 1.6;
  color: var(--subtitle-text-muted);
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

/* 工作台弹窗壳由本页自定义，不再走 Element Plus dialog。 */
.subtitle-import-workbench-overlay {
  position: fixed;
  inset: 0;
  z-index: 2500;
  display: grid;
  place-items: center;
  padding: 16px;
  background: transparent !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

.subtitle-import-workbench-modal {
  width: min(1760px, calc(100vw - 16px));
  max-height: calc(100dvh - 32px);
  overflow: hidden;
  border-radius: 24px;
  background: #ffffff;
  border: 1px solid var(--subtitle-border);
  box-shadow: none;
}

.subtitle-import-workbench-modal :deep(.subtitle-workbench-shell) {
  min-height: min(78vh, 820px);
  max-height: calc(100dvh - 32px);
}

.subtitle-import-workbench-fade-enter-active,
.subtitle-import-workbench-fade-leave-active {
  transition: opacity 0.2s ease;
}

.subtitle-import-workbench-fade-enter-active .subtitle-import-workbench-modal,
.subtitle-import-workbench-fade-leave-active .subtitle-import-workbench-modal {
  transition: opacity 0.18s ease;
}

.subtitle-import-workbench-fade-enter-from,
.subtitle-import-workbench-fade-leave-to {
  opacity: 0;
}

.subtitle-import-workbench-fade-enter-from .subtitle-import-workbench-modal,
.subtitle-import-workbench-fade-leave-to .subtitle-import-workbench-modal {
  opacity: 0;
}

:global(html.kikoerumanager-dark) .subtitle-page {
  --subtitle-panel: var(--km-dark-surface);
  --subtitle-panel-soft: #15161b;
  --subtitle-panel-muted: #1c1d22;
  --subtitle-border: var(--km-dark-border-soft);
  --subtitle-border-strong: var(--km-dark-border-strong);
  --subtitle-text: var(--km-dark-text-strong);
  --subtitle-text-muted: var(--km-dark-text-muted);
  --subtitle-text-soft: var(--km-dark-text-subtle);
  --subtitle-primary-soft: rgba(255, 255, 255, 0.08);
  --subtitle-success: var(--km-dark-green);
  --subtitle-warning: var(--km-dark-amber);
  --subtitle-danger: var(--km-dark-red);
  --subtitle-shadow: none;
}

:global(body.kikoerumanager-dark .subtitle-page),
:global(html.kikoerumanager-dark body .subtitle-page) {
  --subtitle-panel: var(--km-dark-surface);
  --subtitle-panel-soft: #15161b;
  --subtitle-panel-muted: #1c1d22;
  --subtitle-border: var(--km-dark-border-soft);
  --subtitle-border-strong: var(--km-dark-border-strong);
  --subtitle-text: var(--km-dark-text-strong);
  --subtitle-text-muted: var(--km-dark-text-muted);
  --subtitle-text-soft: var(--km-dark-text-subtle);
  --subtitle-primary-soft: rgba(255, 255, 255, 0.08);
  --subtitle-success: var(--km-dark-green);
  --subtitle-warning: var(--km-dark-amber);
  --subtitle-danger: var(--km-dark-red);
  --subtitle-shadow: none;
}

:global(html.kikoerumanager-dark) .subtitle-shell,
:global(html.kikoerumanager-dark) .subtitle-dashboard-item,
:global(body.kikoerumanager-dark .subtitle-shell),
:global(body.kikoerumanager-dark .subtitle-dashboard-item) {
  background: var(--subtitle-panel);
  border-color: var(--subtitle-border);
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .subtitle-dashboard-icon,
:global(html.kikoerumanager-dark) .subtitle-segmented,
:global(html.kikoerumanager-dark) .subtitle-list-header,
:global(html.kikoerumanager-dark) .subtitle-detail-header,
:global(html.kikoerumanager-dark) .subtitle-info-card-header,
:global(html.kikoerumanager-dark) .subtitle-meta-item,
:global(html.kikoerumanager-dark) .subtitle-tree,
:global(html.kikoerumanager-dark) .subtitle-form-hint-card,
:global(body.kikoerumanager-dark .subtitle-dashboard-icon),
:global(body.kikoerumanager-dark .subtitle-segmented),
:global(body.kikoerumanager-dark .subtitle-list-header),
:global(body.kikoerumanager-dark .subtitle-detail-header),
:global(body.kikoerumanager-dark .subtitle-info-card-header),
:global(body.kikoerumanager-dark .subtitle-meta-item),
:global(body.kikoerumanager-dark .subtitle-tree),
:global(body.kikoerumanager-dark .subtitle-form-hint-card) {
  background: transparent;
  border-color: var(--subtitle-border);
}

:global(html.kikoerumanager-dark) .subtitle-dashboard-item.is-pending .subtitle-dashboard-icon {
  background: transparent;
  border-color: rgba(244, 206, 117, 0.26);
  color: var(--km-dark-amber);
}

:global(html.kikoerumanager-dark) .subtitle-dashboard-item.is-running .subtitle-dashboard-icon {
  background: transparent;
  border-color: var(--km-dark-border);
  color: var(--km-dark-info);
}

:global(html.kikoerumanager-dark) .subtitle-dashboard-item.is-total .subtitle-dashboard-icon {
  background: transparent;
  border-color: rgba(141, 223, 187, 0.26);
  color: var(--km-dark-green);
}

:global(html.kikoerumanager-dark) .subtitle-list-pane,
:global(html.kikoerumanager-dark) .subtitle-detail-pane,
:global(html.kikoerumanager-dark) .subtitle-info-card,
:global(html.kikoerumanager-dark) .subtitle-candidate-card,
:global(html.kikoerumanager-dark) .subtitle-refresh-btn,
:global(html.kikoerumanager-dark) .subtitle-action-btn,
:global(html.kikoerumanager-dark) .subtitle-mini-btn,
:global(html.kikoerumanager-dark) .subtitle-form-input-wrap,
:global(body.kikoerumanager-dark .subtitle-list-pane),
:global(body.kikoerumanager-dark .subtitle-detail-pane),
:global(body.kikoerumanager-dark .subtitle-info-card),
:global(body.kikoerumanager-dark .subtitle-candidate-card),
:global(body.kikoerumanager-dark .subtitle-refresh-btn),
:global(body.kikoerumanager-dark .subtitle-action-btn),
:global(body.kikoerumanager-dark .subtitle-mini-btn),
:global(body.kikoerumanager-dark .subtitle-form-input-wrap) {
  background: var(--subtitle-panel);
  border-color: var(--subtitle-border);
  color: var(--subtitle-text);
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .subtitle-segmented-item.is-active,
:global(html.kikoerumanager-dark) .subtitle-list-card.is-active,
:global(html.kikoerumanager-dark) .subtitle-candidate-card.is-selected {
  background: var(--subtitle-panel-muted);
  border-color: var(--subtitle-border-strong);
  color: var(--subtitle-text);
}

:global(html.kikoerumanager-dark) .subtitle-refresh-btn:hover,
:global(html.kikoerumanager-dark) .subtitle-action-btn:hover,
:global(html.kikoerumanager-dark) .subtitle-mini-btn:hover,
:global(html.kikoerumanager-dark) .subtitle-list-page-btn:hover,
:global(html.kikoerumanager-dark) .subtitle-list-card:hover,
:global(html.kikoerumanager-dark) .subtitle-candidate-card:hover {
  background: var(--km-dark-surface-hover);
  border-color: var(--subtitle-border-strong);
  box-shadow: none;
}

:global(html.kikoerumanager-dark body #app .subtitle-page .subtitle-shell),
:global(body.kikoerumanager-dark #app .subtitle-page .subtitle-shell) {
  background: transparent !important;
  background-image: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .subtitle-page .subtitle-detail-pane),
:global(html.kikoerumanager-dark body #app .subtitle-page .subtitle-detail-header),
:global(body.kikoerumanager-dark #app .subtitle-page .subtitle-detail-pane),
:global(body.kikoerumanager-dark #app .subtitle-page .subtitle-detail-header) {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-list-pager,
:global(html.kikoerumanager-dark) .subtitle-list-page-btn {
  background: var(--subtitle-panel);
  border-color: var(--subtitle-border);
}

:global(html.kikoerumanager-dark) .subtitle-list-page-indicator {
  background: var(--subtitle-primary-soft);
  border-color: var(--subtitle-border);
  color: var(--subtitle-text-muted);
}

:global(html.kikoerumanager-dark) .subtitle-action-btn.is-primary {
  background: var(--km-dark-primary-button-bg);
  color: var(--km-dark-primary-button-text);
  border-color: transparent;
}

:global(html.kikoerumanager-dark) .lib-chip-info {
  background: var(--km-dark-info-bg);
  color: var(--km-dark-info);
  border-color: var(--km-dark-border);
}

:global(html.kikoerumanager-dark) .lib-chip-success {
  background: var(--km-dark-green-bg);
  color: var(--km-dark-green);
  border-color: rgba(141, 223, 187, 0.28);
}

:global(html.kikoerumanager-dark) .lib-chip-warning {
  background: var(--km-dark-amber-bg);
  color: var(--km-dark-amber);
  border-color: rgba(244, 206, 117, 0.28);
}

:global(html.kikoerumanager-dark) .lib-chip-danger {
  background: var(--km-dark-red-bg);
  color: var(--km-dark-red);
  border-color: rgba(243, 162, 168, 0.28);
}

:global(html.kikoerumanager-dark) .subtitle-detail-alert.is-info {
  background: transparent !important;
  border-color: var(--subtitle-border);
  color: var(--km-dark-text-muted);
  box-shadow: none !important;
}

:global(body.kikoerumanager-dark .subtitle-detail-alert),
:global(body.kikoerumanager-dark .subtitle-detail-alert.is-info),
:global(body.kikoerumanager-dark .subtitle-detail-alert.is-warning),
:global(html.kikoerumanager-dark body .subtitle-detail-alert),
:global(html.kikoerumanager-dark body .subtitle-detail-alert.is-info),
:global(html.kikoerumanager-dark body .subtitle-detail-alert.is-warning) {
  background: transparent !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-detail-alert.is-warning {
  background: transparent !important;
  border-color: rgba(244, 206, 117, 0.28);
  color: var(--km-dark-amber);
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark) .subtitle-detail-pane,
:global(body.kikoerumanager-dark .subtitle-detail-pane) {
  background: transparent;
}

:global(html.kikoerumanager-dark) .subtitle-detail-header,
:global(body.kikoerumanager-dark .subtitle-detail-header) {
  overflow: visible;
}

:global(html.kikoerumanager-dark .subtitle-detail-bg-glyph),
:global(body.kikoerumanager-dark .subtitle-detail-bg-glyph) {
  display: none;
}

:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-info-card,
:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-info-card-header,
:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-meta-item,
:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-tree,
:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-candidate-card,
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-info-card),
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-info-card-header),
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-meta-item),
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-tree),
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-candidate-card) {
  background: transparent !important;
  box-shadow: none;
}

:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-info-card {
  border-color: var(--subtitle-border);
}

:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-meta-grid,
:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-candidate-list,
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-meta-grid),
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-candidate-list) {
  background: transparent;
  border-color: var(--subtitle-border);
}

:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-candidate-card:hover,
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-candidate-card:hover) {
  background: var(--km-dark-surface-hover) !important;
}

:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-candidate-card.is-selected,
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-candidate-card.is-selected),
:global(html.kikoerumanager-dark body #app .subtitle-page .subtitle-detail-body .subtitle-candidate-card.is-selected),
:global(body.kikoerumanager-dark #app .subtitle-page .subtitle-detail-body .subtitle-candidate-card.is-selected) {
  background: rgba(141, 223, 187, 0.12) !important;
  border-color: rgba(141, 223, 187, 0.34) !important;
}

:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-candidate-radio,
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-candidate-radio) {
  background: var(--km-dark-bg);
  border-color: var(--subtitle-border-strong);
}

:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-candidate-radio.is-checked,
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-candidate-radio.is-checked) {
  background: #34d399;
  border-color: #34d399;
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.16);
}

:global(html.kikoerumanager-dark) .subtitle-detail-body .subtitle-candidate-radio-dot,
:global(body.kikoerumanager-dark .subtitle-detail-body .subtitle-candidate-radio-dot) {
  background: #06291f;
}

:global(html.kikoerumanager-dark) .subtitle-import-workbench-overlay {
  background: transparent !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal) {
  background: var(--km-dark-bg);
  border: 1px solid var(--km-dark-border);
  box-shadow: none;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-shell),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-shell) {
  background: var(--km-dark-surface);
  border-color: var(--km-dark-border);
  box-shadow: none;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-header),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-header) {
  background: var(--km-dark-surface);
  border-color: var(--km-dark-border);
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-body),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-body) {
  background: var(--km-dark-bg);
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-brand),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-brand) {
  background: var(--km-dark-primary-button-bg);
  color: var(--km-dark-primary-button-text);
  border-color: transparent;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-btn),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-btn) {
  background: var(--km-dark-button-bg);
  color: var(--km-dark-text);
  border-color: var(--km-dark-border);
  box-shadow: none;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-btn:hover),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .subtitle-workbench-btn:hover) {
  background: var(--km-dark-button-bg-hover);
  color: var(--km-dark-text-strong);
  border-color: var(--km-dark-border-strong);
  box-shadow: none;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-900),
:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-800),
:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-700),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-900),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-800),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-700) {
  color: var(--km-dark-text-strong) !important;
}

:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-600),
:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-500),
:global(html.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-400),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-600),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-500),
:global(body.kikoerumanager-dark .subtitle-import-workbench-modal .text-slate-400) {
  color: var(--km-dark-text-muted) !important;
}

/* 屏幕较窄时双栏退化为单列 */
@media (max-width: 1080px) {
  .subtitle-main { flex-direction: column; }
  .subtitle-list-pane { width: 100%; }
}

/* ============================================================
 * 移动端 (≤1024)：整页 stream 模式（Phase 2.4）
 * 桌面端零改动：仅 @media 内覆盖
 * 痛点：桌面是 .subtitle-shell flex 双栏（list 360px / detail 1fr）各自滚，
 *      移动端 list 360px 撑死 + detail 没空间。
 * 解法：双栏 → flex-col stack；内部滚动区松绑；整页 .subtitle-shell 自然撑开后由
 *       外层 .content-shell 滚（与 Conflicts.vue / ActivityHistory.vue 一致）。
 * ============================================================ */
@media (max-width: 1024px) {
  .subtitle-page {
    min-height: auto !important;
    overflow: visible !important;
  }
  .subtitle-shell {
    flex: 0 0 auto !important;
    min-height: 0 !important;
  }
  .subtitle-main {
    flex: 0 0 auto !important;
    flex-direction: column !important;
    overflow: visible !important;
    min-height: 0 !important;
    gap: 12px;
  }
  .subtitle-list-pane,
  .subtitle-detail-pane {
    width: 100% !important;
    flex: 0 0 auto !important;
    height: auto !important;
    min-height: 0 !important;
    overflow: visible !important;
  }
  /* 内部滚动区松绑：让内容自然撑开，整页滚 */
  .subtitle-list-scroll,
  .subtitle-detail-body {
    overflow: visible !important;
    flex: 0 0 auto !important;
    max-height: none !important;
    min-height: 0 !important;
  }
  /* Tab segmented：窄屏占满一整行，按钮平均分 */
  .subtitle-segmented {
    align-self: stretch;
    width: 100%;
  }
  .subtitle-segmented-item {
    flex: 1 1 50%;
    justify-content: center;
  }
  /* 列表头部 actions（清除当前 / 清空）窄屏 wrap，避免挤窄 */
  .subtitle-list-actions {
    flex-wrap: wrap;
  }
  /* 字幕文件夹补配 - 表单操作按钮 wrap + 50% 等宽 */
  .subtitle-form-actions {
    flex-wrap: wrap;
    gap: 6px;
  }
  .subtitle-form-actions .subtitle-action-btn {
    flex: 1 1 calc(50% - 3px);
    min-width: 0;
  }
}

/* ============================================================
 * 移动端 (≤640)：内边距收紧 + 卡片视觉紧凑
 * ============================================================ */
@media (max-width: 640px) {
  .subtitle-page {
    width: 100%;
    max-width: 100vw;
    min-width: 0;
    padding: 8px 10px 16px !important;
    overflow-x: hidden !important;
  }
  .subtitle-dashboard {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    gap: 12px !important;
  }
  .subtitle-dashboard-copy {
    min-width: 0;
    max-width: 100%;
    overflow-wrap: anywhere;
  }
  .subtitle-shell,
  .subtitle-main,
  .subtitle-list-pane,
  .subtitle-detail-pane {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    overflow-x: hidden !important;
  }
  .subtitle-segmented {
    padding: 4px;
    border-radius: 14px;
  }
  .subtitle-segmented-item {
    min-width: 0;
    padding: 9px 6px;
    font-size: 12px;
    line-height: 1.2;
  }
  .subtitle-list-pane,
  .subtitle-detail-pane {
    border-radius: 14px;
  }
  .subtitle-list-header {
    padding: 14px !important;
  }
  .subtitle-list-header-row {
    align-items: flex-start;
    gap: 8px;
  }
  .subtitle-list-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
    gap: 8px;
  }
  .subtitle-mini-btn {
    min-width: 0;
    width: 100%;
    justify-content: center;
    padding-left: 8px;
    padding-right: 8px;
  }
  /* detail-header / body padding 紧凑 */
  .subtitle-detail-header {
    padding: 16px !important;
  }
  .subtitle-detail-body {
    padding: 14px !important;
    gap: 14px;
  }
  /* 大标题字号下调 */
  .subtitle-detail-title {
    font-size: 18px !important;
    letter-spacing: -0.3px;
  }
  /* form 内边距收紧 */
  .subtitle-form-body {
    padding: 14px !important;
    gap: 12px;
  }
  /* 提交栏改全宽（导入按钮 100%） */
  .subtitle-detail-footer {
    justify-content: stretch;
  }
  .subtitle-detail-footer .subtitle-action-btn {
    flex: 1 1 100%;
    width: 100%;
  }
  /* 字幕文件树 max-height 收紧，避免吃满首屏 */
  .subtitle-tree {
    max-height: 200px;
  }
  /* meta-grid 改 1 列（避免横向挤压数字 / RJ 码） */
  .subtitle-meta-grid {
    grid-template-columns: 1fr;
  }
  .subtitle-meta-item.is-wide {
    grid-column: 1 / -1;
  }
  .subtitle-import-workbench-overlay {
    padding: 0;
    background: transparent !important;
    backdrop-filter: none !important;
  }
  .subtitle-import-workbench-modal {
    width: 100vw;
    max-width: 100vw;
    height: 100dvh;
    max-height: 100dvh;
    border-radius: 0;
  }
  .subtitle-import-workbench-modal :deep(.subtitle-workbench-shell) {
    min-height: 100dvh !important;
    max-height: 100dvh !important;
    height: 100dvh !important;
    border-radius: 0 !important;
    border: 0 !important;
    box-shadow: none !important;
  }
}
</style>
