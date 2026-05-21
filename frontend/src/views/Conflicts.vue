<template>
  <div class="conflicts-page">
    <!-- 页头走共享组件 AppPageHeader，保持与其他页面一致 -->
    <AppPageHeader
      :icon="ShieldAlert"
      icon-color="#b45309"
      title="问题作品"
      subtitle="重复作品、解压失败、处理失败的集中处理站"
    >
      <span v-if="batchRunning" class="lib-chip lib-chip-info">
        <AppLoadingAnimation variant="inline" :size="14" />
        {{ batchActionLabel || '批量处理中' }}
      </span>
      <button
        type="button"
        class="conflicts-refresh-btn"
        :disabled="loading || batchRunning"
        @click="fetchConflicts"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
        刷新
      </button>
    </AppPageHeader>

    <!-- 状态信息条：替代原顶部 inline chip -->
    <section class="lib-info-strip conflicts-info-strip">
      <div class="lib-info-item">
        <Hourglass :size="15" :stroke-width="2.2" class="lib-info-icon text-amber-500" />
        <div class="lib-info-body">
          <div class="lib-info-label">待处理</div>
          <div class="lib-info-value">
            <b>{{ pendingConflicts.length }}</b>
            <span class="lib-info-meta">/ 共 {{ conflicts.length }}</span>
          </div>
          <div class="lib-info-sub">需要人工决定的重复 / 失败作品</div>
        </div>
      </div>
      <div class="lib-info-divider"></div>
      <div class="lib-info-item">
        <RotateCcw :size="15" :stroke-width="2.2" class="lib-info-icon text-emerald-500" />
        <div class="lib-info-body">
          <div class="lib-info-label">重试中</div>
          <div class="lib-info-value"><b>{{ retryingConflicts.length }}</b></div>
          <div class="lib-info-sub">指定密码或一键重试触发的后台任务</div>
        </div>
      </div>
      <div class="lib-info-divider"></div>
      <div class="lib-info-item">
        <Loader2 :size="15" :stroke-width="2.2" class="lib-info-icon text-blue-500" />
        <div class="lib-info-body">
          <div class="lib-info-label">处理中</div>
          <div class="lib-info-value"><b>{{ processingConflicts.length }}</b></div>
          <div class="lib-info-sub">保留新版 / 合并 / 跳过 正在执行</div>
        </div>
      </div>
    </section>

    <!-- 错误提示 -->
    <div v-if="errorMessage" class="conflicts-error-alert">
      <AlertCircle class="w-5 h-5 flex-shrink-0 mt-0.5 text-red-500" />
      <div>
        <h3 class="font-medium">获取问题作品失败</h3>
        <p class="text-sm mt-1 opacity-90">{{ errorMessage }}</p>
      </div>
    </div>

    <!-- 主工作区：整体没有问题作品时显示大空态，否则永远渲染左侧 pane（含筛选条），避免筛选为空时用户找不回筛选按钮 -->
    <div class="conflicts-main" v-if="!loading || conflicts.length > 0">
      <template v-if="conflicts.length === 0">
        <div class="conflicts-empty">
          <CheckCircle2 class="w-14 h-14 mb-3 text-emerald-400" stroke-width="1.5" />
          <p class="text-base font-medium text-slate-700">当前没有待处理的问题作品</p>
          <p class="text-sm text-slate-400 mt-1.5">所有作品都在正常导入或库中已处于良好状态</p>
        </div>
      </template>

      <template v-else>
        <!-- 左侧列表 -->
        <aside class="conflicts-list-pane">
          <div class="conflicts-list-header">
            <div class="flex items-center justify-between">
              <h3 class="conflicts-list-title">待处理列表</h3>
              <span class="lib-chip lib-chip-info">已选 {{ selectedCount }} / {{ filteredConflicts.length }}</span>
            </div>
            <div class="conflicts-segmented">
              <button
                v-for="option in filterOptions"
                :key="option.value"
                type="button"
                class="conflicts-segmented-item"
                :class="{ 'is-active': conflictFilter === option.value }"
                @click="conflictFilter = option.value"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="conflicts-list-actions">
              <button
                type="button"
                class="conflicts-mini-btn"
                :class="{ 'is-active': isAllSelected }"
                :disabled="batchRunning"
                @click="toggleSelectAll"
              >
                <CheckSquare class="w-3.5 h-3.5" />
                {{ isAllSelected ? '取消全选' : '全选' }}
              </button>
              <button
                type="button"
                class="conflicts-mini-btn"
                :disabled="batchRunning || !selectedCount"
                @click="clearSelection"
              >
                <XSquare class="w-3.5 h-3.5" />
                清空选择
              </button>
            </div>
            <!-- 批量动作 -->
            <div v-if="selectedCount > 0" class="conflicts-batch-actions">
              <button
                v-if="selectedActionCount('RETRY') > 0"
                type="button"
                class="conflicts-batch-btn is-emerald"
                :disabled="batchRunning"
                @click="handleBatchRetry"
              >
                <RotateCcw class="w-3.5 h-3.5" />
                {{ batchButtonLabel('RETRY', '一键重试') }}
              </button>
              <button
                v-if="selectedActionCount('SKIP') > 0"
                type="button"
                class="conflicts-batch-btn is-slate"
                :disabled="batchRunning"
                @click="handleBatchSkip"
              >
                <SkipForward class="w-3.5 h-3.5" />
                {{ batchButtonLabel('SKIP', '批量跳过') }}
              </button>
            </div>
            <p class="conflicts-list-hint">单击聚焦，Ctrl/⌘ 多选，Shift 连选</p>
          </div>

          <div class="conflicts-list-scroll">
            <!-- 筛选结果为空时的小空态（仍保留左侧筛选按钮，允许用户切回其他 tab） -->
            <div v-if="filteredConflicts.length === 0" class="conflicts-list-empty">
              <CheckCircle2 class="w-8 h-8 mb-2 text-emerald-300" stroke-width="1.5" />
              <p class="text-sm font-medium text-slate-600">
                {{ conflictFilter === 'processing' ? '当前没有处理中项' : conflictFilter === 'pending' ? '没有待处理项' : '没有匹配项' }}
              </p>
              <p class="text-xs text-slate-400 mt-1">切换上方筛选查看其他分类</p>
            </div>
            <button
              v-for="conflict in filteredConflicts"
              :key="conflict.id"
              :disabled="isConflictRetrying(conflict)"
              type="button"
              class="conflicts-list-card group"
              :class="[
                isConflictSelected(conflict.id) ? 'is-selected' : '',
                conflict.id === activeConflictId ? 'is-active' : '',
                isConflictProcessing(conflict) ? 'processing-conflict-card' : '',
                isKeepNewProcessing(conflict) ? 'keep-new-conflict-card' : '',
                isConflictRetrying(conflict) ? 'retry-conflict-card' : ''
              ]"
              @click="handleConflictCardClick(conflict, $event)"
            >
              <span v-if="isKeepNewProcessing(conflict)" class="keep-new-card-orbit" aria-hidden="true">
                <Save class="w-3.5 h-3.5" />
              </span>
              <span v-if="isConflictRetrying(conflict)" class="retry-card-orbit" aria-hidden="true">
                <RotateCcw class="w-3.5 h-3.5" />
              </span>
              <div class="conflicts-list-card-row">
                <strong class="conflicts-list-card-title">
                  {{ conflict.rjcode || conflict.new_metadata?.work_name || conflict.new_path || '未识别项目' }}
                  <ChevronRight class="w-3.5 h-3.5 opacity-0 -translate-x-2 transition-all duration-300 group-hover:opacity-100 group-hover:translate-x-0 text-indigo-500" />
                </strong>
                <span class="lib-chip" :class="conflict.context?.existing?.is_remote ? 'lib-chip-warning' : 'lib-chip-info'">
                  <Cloud v-if="conflict.context?.existing?.is_remote" :size="11" :stroke-width="2.4" />
                  <HardDrive v-else :size="11" :stroke-width="2.4" />
                  {{ conflict.context?.existing?.is_remote ? '远程' : '本地' }}
                </span>
              </div>
              <div class="conflicts-list-card-meta">
                <span class="conflicts-list-card-type">
                  <FileWarning v-if="isFailureConflict(conflict)" :size="13" :stroke-width="2.2" class="text-red-400" />
                  <Copy v-else :size="13" :stroke-width="2.2" class="text-indigo-400" />
                  {{ getConflictTypeDetail(conflict) }}
                </span>
                <span class="lib-chip" :class="getConflictStatusChipClass(conflict)">
                  {{ getConflictStatusLabel(conflict) }}
                </span>
                <span class="conflicts-list-card-date">{{ formatDate(conflict.created_at).split(' ')[0] }}</span>
              </div>
              <div v-if="isConflictRetrying(conflict)" class="conflicts-list-card-progress">
                <div class="conflicts-list-progress-track">
                  <div class="conflicts-list-progress-bar" :style="{ width: `${getConflictRetryProgress(conflict)}%` }" />
                </div>
                <span class="conflicts-list-progress-num">{{ getConflictRetryProgress(conflict) }}%</span>
              </div>
            </button>
          </div>
        </aside>

        <!-- 右侧详情 -->
        <section class="conflicts-detail-pane" v-if="activeConflict">
          <!-- 详情顶栏 -->
          <div class="conflicts-detail-header">
            <div class="conflicts-detail-bg-glyph">
              <FileWarning v-if="isFailureConflict(activeConflict)" :size="220" :stroke-width="1.4" />
              <Copy v-else :size="220" :stroke-width="1.4" />
            </div>
            <div class="conflicts-detail-header-inner">
              <div class="conflicts-detail-title-block">
                <div class="flex items-center gap-3">
                  <h2 class="conflicts-detail-title">{{ activeConflict.rjcode || '未识别项目' }}</h2>
                  <span v-if="isConflictSelected(activeConflict.id)" class="lib-chip lib-chip-info">
                    <CheckSquare :size="12" :stroke-width="2.4" />已选入批量
                  </span>
                </div>
                <p class="conflicts-detail-subtitle">
                  <span class="conflicts-detail-dot" :class="isFailureConflict(activeConflict) ? 'is-danger' : 'is-info'"></span>
                  {{ getConflictTypeDetail(activeConflict) }}
                </p>
              </div>

              <div class="conflicts-detail-actions">
                <button
                  v-if="canUseAction(activeConflict, 'KEEP_NEW')"
                  type="button"
                  class="conflicts-action-btn is-primary"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id)"
                  @click="handleKeepNewDispatch(activeConflict)"
                >
                  <Loader2 v-if="isActionLoading(activeConflict.id, 'KEEP_NEW')" class="conflicts-action-spinner" />
                  <Save v-else class="w-4 h-4" />
                  {{ keepNewDispatchLabel(activeConflict) }}
                </button>
                <button
                  v-if="canPreviewFilenames(activeConflict)"
                  type="button"
                  class="conflicts-action-btn is-slate is-preview"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id) || isActionLoading(activeConflict.id, 'PREVIEW_FILENAME')"
                  @click="handleFilenamePreview(activeConflict)"
                >
                  <Loader2 v-if="isActionLoading(activeConflict.id, 'PREVIEW_FILENAME')" class="conflicts-action-spinner" />
                  <FileSearch v-else class="w-4 h-4" />
                  预览文件名
                </button>
                <button
                  v-if="canUseAction(activeConflict, 'RETRY')"
                  type="button"
                  class="conflicts-action-btn is-emerald"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id)"
                  @click="handleRetryDispatch(activeConflict)"
                >
                  <Loader2 v-if="isConflictRetrying(activeConflict)" class="conflicts-action-spinner" />
                  <RotateCcw v-else class="w-4 h-4" />
                  {{ retryDispatchLabel(activeConflict) }}
                </button>
                <button
                  v-if="canUseAction(activeConflict, 'SKIP')"
                  type="button"
                  class="conflicts-action-btn is-slate"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id)"
                  @click="handleSkipDispatch(activeConflict)"
                >
                  <Loader2 v-if="isActionLoading(activeConflict.id, 'SKIP')" class="conflicts-action-spinner" />
                  <SkipForward v-else class="w-4 h-4" />
                  {{ skipDispatchLabel(activeConflict) }}
                </button>
                <button
                  v-if="canUseAction(activeConflict, 'MERGE')"
                  type="button"
                  class="conflicts-action-btn is-amber"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id)"
                  @click="openMergeWorkbench(activeConflict)"
                >
                  <Loader2 v-if="mergeLoading && mergeConflictId === activeConflict.id" class="conflicts-action-spinner" />
                  <GitMerge v-else class="w-4 h-4" />
                  合并
                </button>
              </div>
            </div>
          </div>

          <div class="conflicts-detail-body no-scrollbar">
            <!-- 失败提醒 -->
            <div
              v-if="isFailureConflict(activeConflict)"
              class="conflicts-detail-alert"
              :class="isExtractFailed(activeConflict) ? 'is-warning' : 'is-danger'"
            >
              <AlertTriangle class="w-5 h-5 flex-shrink-0 mt-0.5" :class="isExtractFailed(activeConflict) ? 'text-amber-500' : 'text-red-500'" />
              <div>
                <h4 class="font-semibold mb-1">
                  {{ isExtractFailed(activeConflict) ? '解压阶段失败，非重复冲突' : '处理中途失败，非重复冲突' }}
                </h4>
                <p class="text-sm opacity-90 leading-relaxed">
                  {{ activeConflict.new_metadata?.error_message || (isExtractFailed(activeConflict) ? '请检查密码、分卷完整性或压缩包本身是否损坏。' : '请按失败原因修复后重试。') }}
                </p>
              </div>
            </div>

            <div v-if="getGarbledMeta(activeConflict)" class="conflicts-garbled-card">
              <div class="conflicts-garbled-head">
                <AlertTriangle class="w-4 h-4 text-amber-600" />
                <div>
                  <h4>文件名乱码诊断</h4>
                  <p>
                    样本：{{ formatPreviewName(getGarbledMeta(activeConflict).sample, getFilenamePreviewEncoding(activeConflict)) || '—' }}
                  </p>
                </div>
              </div>
              <div class="conflicts-garbled-toolbar">
                <div class="conflicts-garbled-select">
                  <span>压缩包文件名编码</span>
                  <AppDropdown
                    :model-value="getFilenamePreviewEncoding(activeConflict)"
                    :options="filenameEncodingOptions"
                    placeholder="选择编码"
                    :width="220"
                    :menu-min-width="260"
                    @update:model-value="value => setFilenamePreviewEncoding(activeConflict, value)"
                  />
                </div>
                <button
                  type="button"
                  class="conflicts-garbled-preview-btn"
                  :disabled="isActionLoading(activeConflict.id, 'PREVIEW_FILENAME')"
                  @click="handleFilenamePreview(activeConflict)"
                >
                  <Loader2 v-if="isActionLoading(activeConflict.id, 'PREVIEW_FILENAME')" class="conflicts-action-spinner" />
                  <FileSearch v-else class="w-4 h-4" />
                  刷新预览
                </button>
              </div>
              <div class="conflicts-garbled-grid">
                <div>
                  <span>评分</span>
                  <b>{{ getGarbledMeta(activeConflict).scoreBefore }} → {{ getGarbledMeta(activeConflict).scoreAfter }}</b>
                </div>
                <div>
                  <span>修复 / 编码尝试</span>
                  <b>{{ getGarbledMeta(activeConflict).repairedCount }} / {{ getGarbledMeta(activeConflict).codecPairsTried }}</b>
                </div>
                <div>
                  <span>触发位置</span>
                  <b>{{ getGarbledMeta(activeConflict).origin || '—' }}</b>
                </div>
                <div>
                  <span>命中数量</span>
                  <b>{{ getGarbledMeta(activeConflict).garbledCount }} / {{ getGarbledMeta(activeConflict).totalNames || '—' }}</b>
                </div>
                <div
                  v-if="getGarbledMeta(activeConflict).surrogateRepairedCount || getGarbledMeta(activeConflict).surrogateEscapedCount"
                  class="conflicts-garbled-grid-wide"
                >
                  <span>非 UTF-8 文件名</span>
                  <b>
                    反解 {{ getGarbledMeta(activeConflict).surrogateRepairedCount }}
                    / 字面转义 {{ getGarbledMeta(activeConflict).surrogateEscapedCount }}
                  </b>
                </div>
              </div>
              <div v-if="getGarbledMeta(activeConflict).topSamples.length" class="conflicts-garbled-samples">
                <div
                  v-for="entry in getGarbledMeta(activeConflict).topSamples"
                  :key="`${entry.name}-${entry.score}`"
                  class="conflicts-garbled-row"
                >
                  <span>{{ formatPreviewName(entry.name, getFilenamePreviewEncoding(activeConflict)) }}</span>
                  <b>{{ entry.score }}</b>
                </div>
              </div>
              <div v-if="getFilenamePreviewState(activeConflict).preview" class="conflicts-filename-preview">
                <div class="conflicts-filename-preview-head">
                  <span>
                    编码：{{ getFilenamePreviewState(activeConflict).preview.encoding || 'auto' }}
                    / codepage={{ getFilenamePreviewState(activeConflict).preview.codepage || 'auto' }}
                    / 密码来源={{ getFilenamePreviewState(activeConflict).preview.password_source || '未指定' }}
                  </span>
                  <span class="conflicts-filename-preview-badges">
                    <span
                      v-if="Number(getFilenamePreviewState(activeConflict).preview.repaired_count || 0) > 0"
                      class="fp-repaired-badge"
                      title="后端按 surrogate / mojibake 反解，已直接展示真实文件名"
                    >
                      <CheckCircle2 class="w-3 h-3" />
                      已自动反解 {{ Number(getFilenamePreviewState(activeConflict).preview.repaired_count || 0) }} 项
                    </span>
                    <b>{{ getFilenamePreviewState(activeConflict).preview.file_count || 0 }} 项</b>
                  </span>
                </div>
                <div class="conflicts-filename-preview-tree fp-detail-scroll">
                  <div
                    v-for="row in fpBuildTreeRows(getFilenamePreviewState(activeConflict).preview, getFilenamePreviewEncoding(activeConflict))"
                    :key="row.key"
                    class="fp-tree-row"
                    :class="{ 'is-dir': row.type === 'dir', 'is-garbled': row.isGarbled }"
                    :style="{ paddingLeft: `${row.depth * 16 + 12}px` }"
                  >
                    <div class="fp-tree-main">
                      <span class="fp-tree-expander-spacer" />
                      <span class="fp-tree-icon-wrap">
                        <Folder v-if="row.type === 'dir'" :size="18" :stroke-width="2" class="fp-tree-icon is-folder" />
                        <FileWarning v-else-if="row.isGarbled" :size="18" :stroke-width="2.2" class="fp-tree-icon is-warn" />
                        <Archive v-else-if="row.isArchive" :size="17" :stroke-width="2" class="fp-tree-icon is-archive" />
                        <Music v-else-if="fpIsAudio(row.displayName)" :size="17" :stroke-width="2" class="fp-tree-icon is-audio" />
                        <FileText v-else-if="fpIsText(row.displayName)" :size="17" :stroke-width="2" class="fp-tree-icon is-text" />
                        <File v-else :size="17" :stroke-width="2" class="fp-tree-icon is-file" />
                      </span>
                      <span class="fp-tree-name">{{ row.displayName }}</span>
                      <span v-if="row.isGarbled" class="fp-garbled-tag">乱码</span>
                    </div>
                    <span v-if="row.sizeText && row.type !== 'dir'" class="fp-tree-size">{{ row.sizeText }}</span>
                  </div>
                </div>
              </div>
            </div>

            <div class="conflicts-detail-grid">
              <!-- 当前新内容 -->
              <div class="conflicts-info-card">
                <div class="conflicts-info-card-header">
                  <FolderOpen class="w-4 h-4 text-slate-400" />
                  <h3>{{ isFailureConflict(activeConflict) ? '失败来源' : '当前新内容' }}</h3>
                </div>
                <div class="conflicts-info-card-body">
                  <div class="conflicts-info-section">
                    <span class="conflicts-info-label">来源路径</span>
                    <div class="conflicts-info-path">{{ getConflictSourcePath(activeConflict) }}</div>
                  </div>

                  <div class="conflicts-info-cols">
                    <div>
                      <span class="conflicts-info-label">类型</span>
                      <p class="conflicts-info-value">{{ activeConflict.context?.new_path_kind === 'archive' ? '压缩包' : '目录' }}</p>
                    </div>
                    <div>
                      <span class="conflicts-info-label">大小</span>
                      <p class="conflicts-info-value">{{ displayStatSize(activeConflict.context?.source?.stats) }}</p>
                    </div>
                  </div>

                  <div class="conflicts-info-section">
                    <span class="conflicts-info-label">创建时间</span>
                    <p class="conflicts-info-value-muted">{{ displayStatTime(activeConflict.context?.source?.stats) }}</p>
                  </div>

                  <div v-if="activeConflict.new_metadata" class="conflicts-info-block">
                    <span class="conflicts-info-label">{{ isFailureConflict(activeConflict) ? '附带信息' : '作品信息' }}</span>
                    <div class="conflicts-info-meta-list">
                      <div v-if="activeConflict.new_metadata.work_name" class="conflicts-info-meta-row">
                        <span class="conflicts-info-meta-key">名称</span>
                        <span class="conflicts-info-meta-val break-all">{{ activeConflict.new_metadata.work_name }}</span>
                      </div>
                      <div v-if="activeConflict.new_metadata.maker_name" class="conflicts-info-meta-row">
                        <span class="conflicts-info-meta-key">社团</span>
                        <span class="conflicts-info-meta-val">{{ activeConflict.new_metadata.maker_name }}</span>
                      </div>
                      <div v-if="activeConflict.new_metadata.cvs?.length" class="conflicts-info-meta-row">
                        <span class="conflicts-info-meta-key">声优</span>
                        <span class="conflicts-info-meta-val">{{ activeConflict.new_metadata.cvs.join(' / ') }}</span>
                      </div>
                    </div>
                  </div>

                  <div v-if="activeConflict.new_metadata?.error_message" class="conflicts-info-block">
                    <span class="conflicts-info-label">失败原因</span>
                    <p class="text-sm text-red-600 font-medium">{{ activeConflict.new_metadata.error_message }}</p>
                  </div>
                </div>
              </div>

              <!-- 已存在目录 -->
              <div class="conflicts-info-card">
                <div class="conflicts-info-card-header">
                  <Archive class="w-4 h-4 text-slate-400" />
                  <h3>{{ isFailureConflict(activeConflict) ? '处理建议' : '已存在目录' }}</h3>
                </div>
                <div class="conflicts-info-card-body">
                  <div class="conflicts-info-section">
                    <span class="conflicts-info-label">{{ isFailureConflict(activeConflict) ? '建议动作' : '目标路径' }}</span>
                    <div v-if="!isFailureConflict(activeConflict)" class="conflicts-info-path is-target">
                      {{ getExistingConflictPath(activeConflict) }}
                    </div>
                    <p v-else class="conflicts-info-suggest">
                      {{ isExtractFailed(activeConflict) ? '可直接跳过并删除当前失败来源；如果你已经补充了正确密码或完整分卷，建议回到任务列表重新处理。' : '可先根据失败原因修复来源内容后重试；如果确认不再处理，也可以直接跳过删除当前失败来源。' }}
                    </p>
                  </div>

                  <div v-if="!isFailureConflict(activeConflict)" class="conflicts-info-cols">
                    <div>
                      <span class="conflicts-info-label">落地位置</span>
                      <p class="conflicts-info-value flex items-center gap-1.5">
                        {{ activeConflict.context?.existing?.library_name || '默认库存' }}
                        <span class="lib-chip" :class="activeConflict.context?.existing?.is_remote ? 'lib-chip-warning' : 'lib-chip-info'">
                          {{ activeConflict.context?.existing?.is_remote ? '远程' : '本地' }}
                        </span>
                      </p>
                    </div>
                    <div>
                      <span class="conflicts-info-label">大小</span>
                      <p class="conflicts-info-value">{{ displayStatSize(activeConflict.context?.existing?.stats) }}</p>
                    </div>
                  </div>

                  <div class="conflicts-info-block conflicts-info-cols">
                    <div>
                      <span class="conflicts-info-label">{{ isFailureConflict(activeConflict) ? '记录时间' : '检测时间' }}</span>
                      <p class="conflicts-info-value-muted">{{ formatDate(activeConflict.created_at) }}</p>
                    </div>
                    <div v-if="!isFailureConflict(activeConflict)">
                      <span class="conflicts-info-label">目标创建时间</span>
                      <p class="conflicts-info-value-muted">{{ displayStatTime(activeConflict.context?.existing?.stats) }}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 帮助说明 -->
            <div class="conflicts-help-card">
              <h4 class="conflicts-help-title">
                <Info class="w-4 h-4 text-slate-400" />
                {{ isFailureConflict(activeConflict) ? '失败说明' : '动作说明' }}
              </h4>
              <ul v-if="!isFailureConflict(activeConflict)" class="conflicts-help-list">
                <li><strong>保留新版：</strong>先经过删除审查，再安全替换已有目录，失败时走最小化破坏路径。</li>
                <li><strong>跳过：</strong>不解压，直接删除当前压缩包或待处理目录，原有目录保持不变。</li>
                <li><strong>合并：</strong>进入组件文件夹对比视图，逐文件决定保留新文件、旧文件或删除。</li>
              </ul>
              <ul v-else class="conflicts-help-list">
                <li>{{ isExtractFailed(activeConflict) ? '当前问题发生在解压阶段，不代表库存中已经有重复作品。' : '当前问题发生在导入处理链路中，不代表库存中已经有重复作品。' }}</li>
                <li>{{ isExtractFailed(activeConflict) ? '如果错误是密码不正确、分卷缺失或压缩包损坏，修复后重新处理通常更合适。' : '如果错误发生在元数据、重命名、过滤或分类阶段，优先按当前失败原因排查对应链路。' }}</li>
                <li>如果确认不再处理这个包，可以直接点击"跳过"删除失败来源。</li>
              </ul>
            </div>
          </div>
        </section>

        <!-- 未选中时的右侧占位：鼓励用户从左侧挑选 -->
        <section v-else class="conflicts-detail-pane conflicts-detail-placeholder">
          <div class="conflicts-detail-placeholder-inner">
            <FileWarning class="w-10 h-10 mb-3 text-slate-300" stroke-width="1.4" />
            <p class="text-sm font-medium text-slate-500">请从左侧选择一个问题作品</p>
            <p class="text-xs text-slate-400 mt-1">点击列表项查看详情并处理</p>
          </div>
        </section>
      </template>
    </div>

    <div v-else class="flex-1 flex flex-col items-center justify-center">
      <AppLoadingAnimation label="加载问题作品中..." :size="140" :min-height="220" />
    </div>

    <ConflictMergeWorkbench
      v-model="mergeDialogVisible"
      :conflict="mergeConflict"
      :preview="mergePreview"
      :decisions="mergeDecisions"
      :loading="mergeLoading"
      :loading-progress="mergePreviewProgress"
      :submitting="mergeSubmitting"
      @update:decisions="handleDecisionUpdate"
      @refresh="refreshMergePreview"
      @submit="submitMerge"
      @close="cancelMergePreviewPolling"
    />

    <BatchRetryPasswordDialog
      v-model="batchRetryDialogVisible"
      :conflicts="batchRetryTargets"
      @confirm="handleBatchRetryConfirm"
    />

    <!--
      文件名预览弹窗：完全对齐库存页 mediaPreviewDialog 的"系统自定义弹窗"风格
      Teleport + 全屏遮罩 + 圆角 22 玻璃面板 + backdrop-blur-2xl + 内嵌高光投影
      头部 hero (gradient + 玻璃 icon)；主体 chip + 系统文件树；footer 玻璃带 + 主次按钮
    -->
    <Teleport to="body">
      <Transition name="fp-dlg-fade">
        <section
          v-if="fpDlgVisible"
          class="pointer-events-none fixed inset-0 z-[4000] flex items-center justify-center p-6 max-[900px]:p-3"
        >
          <!-- 半透明遮罩（点击=取消） -->
          <div
            class="pointer-events-auto absolute inset-0 bg-slate-900/30 backdrop-blur-[3px]"
            @click="fpDlgClose"
          />
          <!-- 玻璃面板（pointer-events-auto 让面板可交互） -->
          <div
            class="fp-dlg-panel pointer-events-auto relative flex max-h-[calc(100vh-48px)] w-[min(720px,calc(100vw-48px))] flex-col overflow-hidden rounded-[22px] border border-white/70 bg-white/72 shadow-[0_22px_70px_rgba(15,23,42,0.18),inset_0_1px_0_rgba(255,255,255,0.82)] backdrop-blur-2xl backdrop-saturate-150 max-[900px]:max-h-[calc(100vh-24px)] max-[900px]:max-w-[calc(100vw-24px)]"
            role="dialog"
            aria-modal="true"
            aria-labelledby="fp-dlg-title"
          >
            <!-- Header：hero band (gradient + 玻璃 icon + 标签 + 关闭键) -->
            <header class="flex flex-shrink-0 items-start justify-between gap-3 border-b border-white/55 bg-gradient-to-br from-amber-50/76 via-white/40 to-sky-50/56 px-5 py-4 backdrop-blur-xl">
              <div class="flex min-w-0 flex-1 items-center gap-3">
                <span class="inline-flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-[14px] border border-white/70 bg-white/56 shadow-sm backdrop-blur-xl">
                  <FileSearch class="h-5 w-5 text-slate-700" :stroke-width="2" />
                </span>
                <div class="min-w-0 flex-1">
                  <h3 id="fp-dlg-title" class="m-0 truncate text-[15px] font-bold text-slate-900">文件名预览</h3>
                  <p class="mt-0.5 truncate text-[12px] leading-tight text-slate-500">
                    {{ fpDlgGarbledCount
                      ? `检测到 ${fpDlgGarbledCount} 项疑似乱码，确认是否继续按当前编码重试`
                      : '检查指定编码下压缩包文件名是否仍然乱码' }}
                  </p>
                </div>
                <div v-if="fpDlgGarbledCount || Number(fpDlgData?.repaired_count || 0) > 0" class="flex flex-shrink-0 items-center gap-2 max-[640px]:hidden">
                  <span v-if="fpDlgGarbledCount" class="fp-dlg-tag is-amber">
                    <AlertTriangle class="h-3 w-3" />
                    {{ fpDlgGarbledCount }} 项乱码
                  </span>
                  <span
                    v-if="Number(fpDlgData?.repaired_count || 0) > 0"
                    class="fp-dlg-tag is-emerald"
                    title="后端已按 surrogate / mojibake 反解，直接展示真实文件名"
                  >
                    <CheckCircle2 class="h-3 w-3" />
                    自动反解 {{ Number(fpDlgData?.repaired_count || 0) }} 项
                  </span>
                </div>
              </div>
              <button
                type="button"
                class="group inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-[10px] border border-white/50 bg-white/30 text-slate-500 shadow-sm transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] hover:-translate-y-0.5 hover:scale-[1.04] hover:bg-white/70 hover:text-slate-900 active:translate-y-0 active:scale-[0.94]"
                title="关闭"
                @click="fpDlgClose"
              >
                <X class="h-[15px] w-[15px] transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] group-hover:rotate-90" :stroke-width="2.4" />
              </button>
            </header>

            <!-- Body：meta chips + 文件树卡片 -->
            <div v-if="fpDlgData" class="flex min-h-0 flex-1 flex-col gap-3 px-5 pb-4 pt-4">
              <div class="flex flex-wrap items-center gap-2">
                <span class="fp-dlg-meta-chip">
                  <span class="fp-dlg-meta-chip-label">编码</span>
                  <b>{{ fpDlgData.encoding || 'auto' }}</b>
                </span>
                <span class="fp-dlg-meta-chip">
                  <span class="fp-dlg-meta-chip-label">codepage</span>
                  <b>{{ fpDlgData.codepage || 'auto' }}</b>
                </span>
                <span class="fp-dlg-meta-chip">
                  <span class="fp-dlg-meta-chip-label">密码</span>
                  <b>{{ fpDlgData.password_source || '未指定' }}</b>
                </span>
                <span class="fp-dlg-meta-chip">
                  <span class="fp-dlg-meta-chip-label">文件数</span>
                  <b>{{ fpDlgData.file_count || 0 }}</b>
                </span>
              </div>
              <div class="fp-dlg-tree-shell">
                <div class="fp-dlg-tree-scroll fp-detail-scroll">
                  <div
                    v-for="row in fpDlgTreeRows"
                    :key="row.key"
                    class="fp-tree-row"
                    :class="{ 'is-dir': row.type === 'dir', 'is-garbled': row.isGarbled }"
                    :style="{ paddingLeft: `${row.depth * 16 + 12}px` }"
                  >
                    <div class="fp-tree-main">
                      <span class="fp-tree-expander-spacer" />
                      <span class="fp-tree-icon-wrap">
                        <Folder v-if="row.type === 'dir'" :size="18" :stroke-width="2" class="fp-tree-icon is-folder" />
                        <FileWarning v-else-if="row.isGarbled" :size="18" :stroke-width="2.2" class="fp-tree-icon is-warn" />
                        <Archive v-else-if="row.isArchive" :size="17" :stroke-width="2" class="fp-tree-icon is-archive" />
                        <Music v-else-if="fpIsAudio(row.displayName)" :size="17" :stroke-width="2" class="fp-tree-icon is-audio" />
                        <FileText v-else-if="fpIsText(row.displayName)" :size="17" :stroke-width="2" class="fp-tree-icon is-text" />
                        <File v-else :size="17" :stroke-width="2" class="fp-tree-icon is-file" />
                      </span>
                      <span class="fp-tree-name">{{ row.displayName }}</span>
                      <span v-if="row.isGarbled" class="fp-garbled-tag">乱码</span>
                    </div>
                    <span v-if="row.sizeText && row.type !== 'dir'" class="fp-tree-size">{{ row.sizeText }}</span>
                  </div>
                  <div v-if="!fpDlgTreeRows.length" class="fp-dlg-tree-empty">压缩包内未读取到文件清单</div>
                </div>
              </div>
            </div>

            <!-- Footer：玻璃带 + 主次按钮 -->
            <footer class="flex flex-shrink-0 items-center justify-end gap-2 border-t border-white/55 bg-white/24 px-5 py-3 backdrop-blur-xl">
              <button
                v-if="fpDlgCancelText"
                type="button"
                class="conflicts-action-btn is-slate"
                @click="fpDlgCancel"
              >
                {{ fpDlgCancelText }}
              </button>
              <button
                type="button"
                :class="['conflicts-action-btn', fpDlgGarbledCount ? 'is-amber' : 'is-emerald']"
                @click="fpDlgConfirm"
              >
                {{ fpDlgConfirmText || '确认' }}
              </button>
            </footer>
          </div>
        </section>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onActivated, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  RefreshCw, AlertCircle, CheckCircle2, Cloud, HardDrive,
  FileWarning, Copy, Save, RotateCcw, SkipForward,
  GitMerge, AlertTriangle, FolderOpen, Archive, Info,
  CheckSquare, XSquare, ChevronRight, FileSearch,
  ShieldAlert, Hourglass, Loader2, FileText,
  Folder, Music, File, X,
} from 'lucide-vue-next'
import ConflictMergeWorkbench from '../components/conflicts/ConflictMergeWorkbench.vue'
import BatchRetryPasswordDialog from '../components/conflicts/BatchRetryPasswordDialog.vue'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppDropdown from '../components/common/AppDropdown.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import { conflictApi, taskCenterApi } from '../api'
import { showSystemAlert, showSystemConfirm, showSystemPrompt } from '../composables/useSystemPrompt'

const ACTIVE_CONFLICT_STORAGE_KEY = 'kikoerumanager-conflicts-active-id'

const conflicts = ref([])
const loading = ref(false)
const errorMessage = ref('')
// stats 后台补齐进行中：阶段 1 拿到列表后会立即变 true，阶段 2 完成后变 false。
// 模板里详情区的"大小 / 创建时间"字段在 stats 缺失 + statsBackfilling 时显示"统计中…"。
const statsBackfilling = ref(false)
// 防止 backfill 请求乱序：用户连续点刷新或快速切换页面时，只保留最新一次的结果。
let backfillRequestId = 0
// AbortController 主动取消上一次未完成的 backfill：避免后端跑多遍（即使有缓存也要 DB 查询 +
// Semaphore 排队），减轻群晖 NAS / 慢盘 / Python ThreadPoolExecutor 的负担。
let backfillAbortController = null
// in-flight promise 复用：retry 轮询 / SSE 推送 / 用户手动刷新可能并发触发 fetchConflicts，
// 这里让所有调用方共享同一个 promise，确保后端只跑一次完整列表查询 + 状态恢复。
let pendingFetchPromise = null
const activeConflictId = ref(localStorage.getItem(ACTIVE_CONFLICT_STORAGE_KEY) || '')
const selectedConflictIds = ref([])
const selectionAnchorId = ref('')
const actionState = reactive({})

const batchRunning = ref(false)
const batchActionLabel = ref('')

const mergeDialogVisible = ref(false)
const mergeLoading = ref(false)
const mergeSubmitting = ref(false)
const mergeConflictId = ref('')
const mergePreview = ref(null)
const mergeDecisions = ref({})
const mergePreviewCache = reactive({})
const mergeDecisionCache = reactive({})
// 合并预览异步 job 实时进度：来自 GET /api/conflicts/{id}/preview-job/{job_id}，
// loading 卡片直接渲染 stage_label / message / percent，不再靠前端计时器估算。
const mergePreviewProgress = ref({
  status: 'idle',          // idle | running | completed | failed
  stage: '',
  stage_label: '',
  message: '',
  percent: 0,
})
// 取消正在 polling 的 job：关弹窗 / 切换 conflict 时调用，避免后端 worker 完成后 stale 写状态。
let mergePreviewPollingAbort = null
const conflictFilter = ref('all')
const retryPollers = new Map()
const localRetryingConflictIds = reactive({})
const filenamePreviewState = reactive({})

const batchRetryDialogVisible = ref(false)
const batchRetryTargets = ref([])

// 文件名预览弹窗状态
const fpDlgVisible = ref(false)
const fpDlgData = ref(null)
const fpDlgConfirmText = ref('')
const fpDlgCancelText = ref('')
let fpDlgResolveFn = null
let fpDlgRejectFn = null

const fpDlgEncoding = computed(() => fpDlgData.value?.requested_encoding || fpDlgData.value?.encoding || 'shift_jis')
const fpDlgGarbledCount = computed(() => {
  const diags = Array.isArray(fpDlgData.value?.diagnostics) ? fpDlgData.value.diagnostics : []
  return diags.filter(d => d.garbled).length
})

function fpBuildTreeRows(preview, encoding) {
  const items = []
  const diagMap = new Map()
  if (Array.isArray(preview?.diagnostics)) {
    for (const d of preview.diagnostics) diagMap.set(String(d.name || ''), d)
  }
  const rawList = Array.isArray(preview?.items) ? preview.items : []
  for (const item of rawList) {
    const rawName = String(item?.name || item?.path || '')
    if (!rawName) continue
    const diag = diagMap.get(rawName)
    // 优先采纳后端反解出的合法 UTF-8 路径（surrogate / mojibake 都能覆盖），
    // 后端没给（即 7zz 出来本身就是干净 UTF-8）才退回客户端 TextDecoder。
    const repairedPath = String(item?.repaired_path || diag?.repaired_path || '')
    const displayPath = repairedPath || rawName
    const repairedLeaf = String(item?.repaired_name || diag?.repaired_name || '')
    const displayName = repairedLeaf || formatPreviewName(rawName, encoding)
    const wasRepaired = Boolean(repairedPath || repairedLeaf)
    const isDir = item?.is_dir === true || item?.type === 'dir'
    const size = Number(item?.size || 0)
    const sizeText = !isDir && size ? fpFormatBytes(size) : ''
    const archiveExts = /\.(zip|rar|7z|tar|gz|bz2|xz|iso|lzh)$/i
    items.push({
      rawPath: rawName,
      displayPath,
      displayName,
      wasRepaired,
      type: isDir ? 'dir' : 'file',
      isGarbled: Boolean(diag?.garbled),
      isArchive: !isDir && archiveExts.test(rawName),
      sizeText,
      score: diag?.score ?? null,
    })
  }
  // 建树
  const roots = []
  const nodeMap = new Map()
  const ensureNode = (key, label, type, parentKey = '') => {
    if (nodeMap.has(key)) return nodeMap.get(key)
    const node = { key, label, type, isGarbled: false, isArchive: false, isRepaired: false, sizeText: '', score: null, children: [] }
    nodeMap.set(key, node)
    if (parentKey && nodeMap.has(parentKey)) nodeMap.get(parentKey).children.push(node)
    else roots.push(node)
    return node
  }
  for (const item of items) {
    // 后端反解出的 displayPath 已经是合法 UTF-8 + 标准分隔符，再分段时优先用它，
    // 既保证树形结构按真实文件层级展开，也让每一段中间目录名都展示为日文/中文真实名。
    const sourcePath = item.displayPath || item.rawPath
    const parts = sourcePath.replace(/^[/\\]+|[/\\]+$/g, '').split(/[/\\]/).filter(Boolean)
    let parentKey = ''
    let joined = ''
    parts.forEach((part, index) => {
      joined = joined ? `${joined}/${part}` : part
      const isLeaf = index === parts.length - 1
      const leafType = isLeaf ? item.type : 'dir'
      // 中间目录段：repaired displayPath 已经是干净 UTF-8，无需 TextDecoder；
      // 仅当走到 rawPath fallback（无反解）时才用 formatPreviewName 试一次客户端编码。
      const labelText = sourcePath === item.rawPath
        ? formatPreviewName(part, encoding)
        : part
      const node = ensureNode(joined, labelText, leafType, parentKey)
      if (isLeaf) {
        node.isGarbled = item.isGarbled
        node.isArchive = item.isArchive
        node.sizeText = item.sizeText
        node.score = item.score
        node.displayName = item.displayName
        node.isRepaired = item.wasRepaired
      }
      parentKey = joined
    })
  }
  // 展开成平铺行
  const rows = []
  const walk = (nodes, depth) => {
    const sorted = [...nodes].sort((a, b) => {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
      return (a.label || '').localeCompare(b.label || '', 'zh-Hans-CN-u-kn-true')
    })
    for (const n of sorted) {
      rows.push({ key: n.key, displayName: n.displayName || n.label, type: n.type, depth, isGarbled: n.isGarbled, isArchive: n.isArchive, sizeText: n.sizeText, score: n.score })
      if (n.children.length) walk(n.children, depth + 1)
    }
  }
  walk(roots, 0)
  return rows
}

function fpFormatBytes(bytes) {
  if (!bytes || bytes <= 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const fpDlgTreeRows = computed(() => fpDlgData.value ? fpBuildTreeRows(fpDlgData.value, fpDlgEncoding.value) : [])

// Teleport 自绘弹窗：关闭流程统一走 cancel/confirm 两个出口，主动 hide + 清掉 data，
// 不再依赖 el-dialog 的 @closed 回调。Promise 必须在 hide 之前 resolve，确保连续
// 重试场景下连环调用不会卡在 stale resolver 上。
function _fpDlgFinish(kind) {
  const resolveFn = fpDlgResolveFn
  const rejectFn = fpDlgRejectFn
  fpDlgResolveFn = null
  fpDlgRejectFn = null
  fpDlgVisible.value = false
  fpDlgData.value = null
  if (kind === 'confirm') resolveFn?.()
  else rejectFn?.(kind)
}
function fpDlgConfirm() { _fpDlgFinish('confirm') }
function fpDlgCancel() { _fpDlgFinish('cancel') }
// overlay 点击 / 右上角关闭键 / ESC：行为统一等同 cancel，让 promise reject('close')。
function fpDlgClose() { _fpDlgFinish('close') }

// ESC 键：仅在弹窗显示时拦截并关闭，避免和别的弹窗 / 全局快捷键串台。
function _onFpDlgKeydown(event) {
  if (!fpDlgVisible.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    fpDlgClose()
  }
}

// 文件树 icon 分类：与 TaskDetailPane.task-file-tree 的图标语义保持一致，
// 不同类型给不同色系（音频 violet/blue、文本 slate、folder amber、archive indigo）。
const FP_AUDIO_LOSSLESS_RE = /\.(flac|wav|ape|tta|wv|alac|aif|aiff)$/i
const FP_AUDIO_RE = /\.(mp3|aac|m4a|m4b|ogg|opus|wma|caf)$/i
const FP_TEXT_RE = /\.(txt|md|lrc|ass|ssa|srt|vtt|json|xml|csv|cue|log|html?|nfo|ini)$/i
function fpIsAudio(name) {
  const v = String(name || '')
  return FP_AUDIO_RE.test(v) || FP_AUDIO_LOSSLESS_RE.test(v)
}
function fpIsText(name) {
  return FP_TEXT_RE.test(String(name || ''))
}

function openFilenamePreviewDialog(preview, { confirmText = '确认', cancelText = '取消' } = {}) {
  fpDlgData.value = preview
  fpDlgConfirmText.value = confirmText
  fpDlgCancelText.value = cancelText
  fpDlgVisible.value = true
  return new Promise((resolve, reject) => {
    fpDlgResolveFn = resolve
    fpDlgRejectFn = reject
  })
}

const filenameEncodingOptions = [
  { value: 'shift_jis', label: 'Shift_JIS / CP932', description: '日文 ZIP 最常见，7z codepage 932' },
  { value: 'gbk', label: 'GBK / CP936', description: '中文 Windows 压缩包，7z codepage 936' },
  { value: 'big5', label: 'Big5 / CP950', description: '繁体中文压缩包，7z codepage 950' },
  { value: 'euc_kr', label: 'EUC-KR / CP949', description: '韩文压缩包，7z codepage 949' },
  { value: 'utf-8', label: 'UTF-8', description: '标准 UTF-8 文件名' },
  { value: 'auto', label: '自动嗅探', description: '不强制 -mcp，由后端自动判断' },
]

const activeConflict = computed(() => conflicts.value.find(conflict => conflict.id === activeConflictId.value) || null)
const mergeConflict = computed(() => conflicts.value.find(conflict => conflict.id === mergeConflictId.value) || null)
const pendingConflicts = computed(() => conflicts.value.filter(conflict => !isConflictProcessing(conflict)))
const retryingConflicts = computed(() => conflicts.value.filter(conflict => isConflictRetrying(conflict)))
const processingConflicts = computed(() => conflicts.value.filter(conflict => isConflictProcessing(conflict) && !isConflictRetrying(conflict)))
const filterOptions = computed(() => ([
  { value: 'all', label: `全部 ${conflicts.value.length}` },
  { value: 'pending', label: `待处理 ${pendingConflicts.value.length}` },
  { value: 'processing', label: `处理中 ${processingConflicts.value.length}` }
]))
const filteredConflicts = computed(() => {
  if (conflictFilter.value === 'pending') return pendingConflicts.value
  if (conflictFilter.value === 'processing') return processingConflicts.value
  return conflicts.value
})
const selectedConflicts = computed(() => filteredConflicts.value.filter(conflict => selectedConflictIds.value.includes(conflict.id)))
const selectedCount = computed(() => selectedConflicts.value.length)
const hasSelection = computed(() => selectedCount.value > 0)
const isAllSelected = computed(() => filteredConflicts.value.length > 0 && selectedCount.value === filteredConflicts.value.length)

watch(activeConflictId, value => {
  if (value) {
    localStorage.setItem(ACTIVE_CONFLICT_STORAGE_KEY, value)
  } else {
    localStorage.removeItem(ACTIVE_CONFLICT_STORAGE_KEY)
  }
})

watch(conflictFilter, () => {
  syncSelectedConflicts()
  syncActiveConflict()
})

onMounted(() => {
  fetchConflicts()
  // ESC 关闭文件名预览弹窗（Teleport 自绘，没有 el-dialog 自动接管）
  window.addEventListener('keydown', _onFpDlgKeydown)
})

// 路由启用了 keep-alive（router/index.js 中 cache: true），切走再切回来组件不会重新 mount，
// 只会触发 onActivated。这里兜底：每次激活都刷新一次数据，避免用户看到老缓存误以为没数据。
onActivated(() => {
  // 避免和首次 mount 的 fetchConflicts 重复：首次挂载时 loading 已为 true 或刚结束，这里只在空闲时触发。
  if (!loading.value) {
    fetchConflicts()
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', _onFpDlgKeydown)
  for (const timerId of retryPollers.values()) {
    clearTimeout(timerId)
  }
  retryPollers.clear()
  for (const key of Object.keys(localRetryingConflictIds)) {
    delete localRetryingConflictIds[key]
  }
  // 防御：组件被真正销毁（而非 keep-alive 缓存）时取消未完成的 backfill。
  if (backfillAbortController) {
    backfillAbortController.abort()
    backfillAbortController = null
  }
})


async function fetchConflicts() {
  // in-flight 复用：已有 fetch 在跑则共享同一个 promise，避免重复 list 请求 / DB 查询 / Semaphore 排队。
  if (pendingFetchPromise) {
    return pendingFetchPromise
  }
  pendingFetchPromise = (async () => {
    loading.value = true
    errorMessage.value = ''
    try {
      // 阶段 1：不带 stats 立即拿列表（远程 stat 跳过，秒回），保证界面先渲染出来。
      const data = await conflictApi.list({ includeStats: false })
      const incoming = data.conflicts || []
      // 关键合并：阶段 1 不带 stats，但前一次 backfill 已经填好的 stats 必须保留下来，
      // 否则模板里的 `displayStatSize` 在 statsBackfilling=true 时会瞬间回退到"统计中…"，
      // 再被阶段 2 覆盖回真实大小 → 详情区"大小 / 创建时间"反复闪烁。
      const previousMap = new Map(conflicts.value.map(item => [item.id, item]))
      conflicts.value = incoming.map(next => {
        const prev = previousMap.get(next.id)
        if (!prev) return next
        const nextSrcStats = next.context?.source?.stats ?? prev.context?.source?.stats ?? null
        const nextExistingStats = next.context?.existing?.stats ?? prev.context?.existing?.stats ?? null
        return {
          ...next,
          context: {
            ...(next.context || {}),
            source: { ...(next.context?.source || {}), stats: nextSrcStats },
            existing: { ...(next.context?.existing || {}), stats: nextExistingStats },
          },
        }
      })
      reconcileLocalRetryingConflicts()
      syncSelectedConflicts()
      syncActiveConflict()
    } catch (error) {
      console.error('获取问题作品失败:', error)
      errorMessage.value = resolveErrorMessage(error, '获取问题作品失败')
      return
    } finally {
      loading.value = false
    }
    // 阶段 2：后台异步补齐 stats（目录大小 / 创建时间），不阻塞 UI、失败不打扰。
    // 注意 backfill 不 await，它内部有 abort + requestId 双重去重机制，自我管理；
    // 并且只在确实缺 stats 的项存在时才请求，避免重复跑空。
    void backfillConflictStats()
  })()
  try {
    await pendingFetchPromise
  } finally {
    pendingFetchPromise = null
  }
}

async function backfillConflictStats() {
  if (!conflicts.value.length) return
  // 短路 1：所有项的 stats 都已齐全（前一次 backfill 已写入 + fetchConflicts 阶段 1
  // 已正确合并保留）就直接跳过，避免重试轮询 / SSE 推送 / 切回页面时反复 list 出空 stats
  // 又重新触发"统计中…"占位符闪烁。EXTRACT_FAILED 项可能只有 source 没 existing，
  // existing 不存在不视为缺 stats。
  const needsStats = conflicts.value.some(item => {
    const srcStats = item.context?.source?.stats
    if (!srcStats || srcStats.size == null) return true
    const existing = item.context?.existing
    if (existing && (!existing.stats || existing.stats.size == null)) return true
    return false
  })
  if (!needsStats) return
  // 主动 abort 上一次未完成的 backfill，避免后端跑多遍 + 浪费 NAS IO + 占线程池。
  if (backfillAbortController) {
    backfillAbortController.abort()
  }
  const controller = new AbortController()
  backfillAbortController = controller
  const requestId = ++backfillRequestId
  statsBackfilling.value = true
  try {
    const data = await conflictApi.list({ includeStats: true, signal: controller.signal })
    // 期间用户可能又点了刷新，本次结果已过时则丢弃，避免覆盖更新的数据。
    if (requestId !== backfillRequestId) return
    const incomingMap = new Map((data.conflicts || []).map(item => [item.id, item]))
    // 只 merge context（含 stats），保持其他字段引用不变，最大限度避免列表 re-render 闪烁。
    conflicts.value = conflicts.value.map(existing => {
      const incoming = incomingMap.get(existing.id)
      if (!incoming) return existing
      return { ...existing, context: incoming.context }
    })
  } catch (error) {
    // 主动 abort 走的是 axios 'CanceledError'（code 'ERR_CANCELED'），属于正常流程，静默丢弃。
    if (error?.name === 'CanceledError' || error?.code === 'ERR_CANCELED') {
      return
    }
    // 阶段 2 失败不影响列表展示，只在 console 留痕，下一次刷新会再试。
    console.warn('后台补齐问题作品 stats 失败（不影响列表展示）:', error)
  } finally {
    if (requestId === backfillRequestId) {
      statsBackfilling.value = false
      backfillAbortController = null
    }
  }
}

function syncActiveConflict() {
  if (!filteredConflicts.value.length) {
    activeConflictId.value = ''
    return
  }
  if (!filteredConflicts.value.some(conflict => conflict.id === activeConflictId.value)) {
    activeConflictId.value = filteredConflicts.value[0].id
  }
}

function syncSelectedConflicts() {
  const existingIds = new Set(filteredConflicts.value.filter(conflict => !isConflictRetrying(conflict)).map(conflict => conflict.id))
  selectedConflictIds.value = selectedConflictIds.value.filter(id => existingIds.has(id))
}

function markAction(conflictId, action, value) {
  const key = `${conflictId}:${action}`
  if (value) {
    actionState[key] = true
  } else {
    delete actionState[key]
  }
}

function isActionLoading(conflictId, action) {
  return Boolean(actionState[`${conflictId}:${action}`])
}

function isConflictBusy(conflictId) {
  const conflict = conflicts.value.find(item => item.id === conflictId)
  return isConflictProcessing(conflict) ||
    Object.keys(actionState).some(key => key.startsWith(`${conflictId}:`)) ||
    (mergeSubmitting.value && mergeConflictId.value === conflictId)
}

function canUseAction(conflict, action) {
  return Array.isArray(conflict?.available_actions) && conflict.available_actions.includes(action)
}

function isExtractFailed(conflict) {
  return conflict?.conflict_type === 'EXTRACT_FAILED'
}

function isFailureConflict(conflict) {
  return ['EXTRACT_FAILED', 'PROCESS_FAILED'].includes(conflict?.conflict_type)
}

function canPreviewFilenames(conflict) {
  // 只有"文件名乱码"类失败才需要展示预览按钮：getGarbledMeta 已经按
  // extract_failure_reason === 'garbled_filename' 或 garbled_filename_sample/top_samples
  // 有值判定。密码错 / 一般解压失败 / 群晖错误等不暴露该入口，避免和重试流程不一致。
  return isFailureConflict(conflict) && Boolean(conflict?.id) && Boolean(getGarbledMeta(conflict))
}

function ensureFilenamePreviewState(conflict) {
  const id = conflict?.id || '_'
  if (!filenamePreviewState[id]) {
    filenamePreviewState[id] = {
      encoding: 'shift_jis',
      preview: null,
    }
  }
  return filenamePreviewState[id]
}

function getFilenamePreviewState(conflict) {
  return ensureFilenamePreviewState(conflict)
}

function getFilenamePreviewEncoding(conflict) {
  return ensureFilenamePreviewState(conflict).encoding || 'shift_jis'
}

function setFilenamePreviewEncoding(conflict, value) {
  const state = ensureFilenamePreviewState(conflict)
  state.encoding = String(value || 'auto')
  state.preview = null
}

function getEncodingLabel(value) {
  return filenameEncodingOptions.find(item => item.value === value)?.label || '自动嗅探'
}

function textDecoderEncoding(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (['932', 'cp932', 'shift_jis', 'shift-jis', 'sjis'].includes(normalized)) return 'shift_jis'
  if (['936', 'cp936', 'gbk', 'gb2312'].includes(normalized)) return 'gbk'
  if (['950', 'cp950', 'big5'].includes(normalized)) return 'big5'
  if (['949', 'cp949', 'euc_kr', 'euc-kr'].includes(normalized)) return 'euc-kr'
  if (['utf8', 'utf-8'].includes(normalized)) return 'utf-8'
  return 'shift_jis'
}

function escapedSurrogateBytes(value) {
  const text = String(value || '')
  const bytes = []
  let matched = false
  for (let i = 0; i < text.length;) {
    const literal = text.slice(i, i + 6)
    const literalMatch = /^\\udc([0-9a-fA-F]{2})$/.exec(literal)
    if (literalMatch) {
      bytes.push(parseInt(literalMatch[1], 16))
      matched = true
      i += 6
      continue
    }
    const code = text.charCodeAt(i)
    if (code >= 0xdc80 && code <= 0xdcff) {
      bytes.push(code - 0xdc00)
      matched = true
      i += 1
      continue
    }
    if (code <= 0xff) {
      bytes.push(code)
      i += 1
      continue
    }
    const encoded = new TextEncoder().encode(text[i])
    bytes.push(...encoded)
    i += 1
  }
  return matched ? new Uint8Array(bytes) : null
}

function decodeEscapedSurrogateName(value, encoding) {
  const bytes = escapedSurrogateBytes(value)
  if (!bytes) return String(value || '')
  try {
    return new TextDecoder(textDecoderEncoding(encoding), { fatal: false }).decode(bytes)
  } catch (error) {
    return String(value || '')
  }
}

function formatPreviewName(value, encoding) {
  const raw = String(value || '')
  const decoded = decodeEscapedSurrogateName(raw, encoding)
  return decoded || raw
}

function getFilenamePreviewRows(preview, encoding) {
  const diagList = Array.isArray(preview?.diagnostics) ? preview.diagnostics : []
  if (diagList.length) {
    return diagList.slice(0, 40).map(item => ({
      ...item,
      displayName: formatPreviewName(item.name, encoding),
    }))
  }
  return (preview?.items || []).slice(0, 40).map(item => ({
    name: item.name || '',
    displayName: formatPreviewName(item.name || '', encoding),
    score: 0,
    garbled: false,
  }))
}

function isPasswordFailureConflict(conflict) {
  const metadata = conflict?.new_metadata || {}
  const reason = String(metadata.extract_failure_reason || '').trim()
  const message = [
    metadata.error_message,
    metadata.resolution_error,
    conflict?.error_message,
  ].map(value => String(value || '')).join(' ')
  if (reason === 'wrong_password' || reason === 'missing_password') return true
  return /无正确密码|密码错误|密码不正确|wrong password|incorrect password|password required|missing password/i.test(message)
}

function getGarbledMeta(conflict) {
  const metadata = conflict?.new_metadata || {}
  const sample = metadata.garbled_filename_sample || ''
  const topSamples = Array.isArray(metadata.garbled_filename_top_samples)
    ? metadata.garbled_filename_top_samples
    : []
  const reason = String(metadata.extract_failure_reason || '').trim()
  if (isPasswordFailureConflict(conflict)) return null
  if (reason !== 'garbled_filename') return null
  if (!sample && !topSamples.length) return null
  return {
    sample,
    scoreBefore: Number(metadata.garbled_filename_score_before ?? metadata.garbled_filename_score ?? 0).toFixed(1),
    scoreAfter: Number(metadata.garbled_filename_score_after ?? metadata.garbled_filename_score ?? 0).toFixed(1),
    repairedCount: Number(metadata.garbled_filename_repaired_count || 0),
    codecPairsTried: Number(metadata.garbled_filename_codec_pairs_tried || 0),
    origin: metadata.garbled_filename_guard_origin || '',
    totalNames: Number(metadata.garbled_filename_total_names || 0),
    garbledCount: Number(metadata.garbled_filename_garbled_count || 0),
    // surrogate 修复指标：repaired = 已经反解为合法 UTF-8（强信号）；
    // escaped = 反解失败、用 \udcXX 字面量保命，需要在编码下拉里手动确认。
    surrogateRepairedCount: Number(metadata.garbled_filename_surrogate_repaired_count || 0),
    surrogateEscapedCount: Number(metadata.garbled_filename_surrogate_escaped_count || 0),
    topSamples,
  }
}

function isConflictProcessing(conflict) {
  return String(conflict?.status || '').trim().toUpperCase() === 'PROCESSING'
}

function isRetryProcessing(conflict) {
  return isConflictProcessing(conflict) && isRetryConflict(conflict)
}

function getConflictResolutionAction(conflict) {
  const metadata = conflict?.new_metadata || {}
  return String(metadata.resolution_action || metadata.conflict_resolution_action || '').trim().toUpperCase()
}

function isKeepNewProcessing(conflict) {
  return isConflictProcessing(conflict) && getConflictResolutionAction(conflict) === 'KEEP_NEW'
}

function isConflictRetrying(conflict) {
  if (!conflict?.id) return false
  return Boolean(
    localRetryingConflictIds[conflict.id] ||
    isRetryProcessing(conflict) ||
    isActiveRetryLinkedTask(conflict) ||
    isActionLoading(conflict.id, 'RETRY')
  )
}

function isRetryConflict(conflict) {
  const metadata = conflict?.new_metadata || {}
  return getConflictResolutionAction(conflict) === 'RETRY' ||
    Boolean(metadata.retry_from_conflicts || metadata.retry_conflict_id || metadata.retry_task_id)
}

function isActiveRetryLinkedTask(conflict) {
  if (!isRetryConflict(conflict)) return false
  const status = String(conflict?.linked_task?.status || '').trim().toLowerCase()
  return ['pending', 'processing', 'paused', 'waiting_retry'].includes(status)
}

function markConflictRetrying(conflictId, value) {
  if (!conflictId) return
  if (value) {
    localRetryingConflictIds[conflictId] = true
    return
  }
  delete localRetryingConflictIds[conflictId]
}

function reconcileLocalRetryingConflicts() {
  for (const conflictId of Object.keys(localRetryingConflictIds)) {
    const conflict = conflicts.value.find(item => item.id === conflictId)
    if (!shouldKeepLocalRetrying(conflict)) {
      delete localRetryingConflictIds[conflictId]
    }
  }
}

function shouldKeepLocalRetrying(conflict) {
  if (!conflict) return false
  const status = String(conflict.status || '').trim().toUpperCase()
  const linkedStatus = String(conflict.linked_task?.status || '').trim().toLowerCase()
  if (['completed', 'failed', 'cancelled', 'canceled'].includes(linkedStatus)) return false
  if (['pending', 'processing', 'paused', 'waiting_retry'].includes(linkedStatus)) return true
  return status === 'PROCESSING' && isRetryConflict(conflict)
}

function getConflictRetryProgress(conflict) {
  const value = Number(conflict?.linked_task?.progress ?? conflict?.new_metadata?.resolution_progress ?? 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

function getConflictStatusLabel(conflict) {
  if (isConflictRetrying(conflict)) return '重试中'
  if (isKeepNewProcessing(conflict)) return '保留新版中'
  if (isConflictProcessing(conflict)) return '处理中'
  return '待处理'
}

function getConflictStatusClass(conflict) {
  if (isConflictRetrying(conflict)) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (isConflictProcessing(conflict)) return 'bg-blue-50 text-blue-600 border-blue-200'
  return 'bg-slate-100 text-slate-500 border-slate-200'
}

function getConflictStatusChipClass(conflict) {
  if (isConflictRetrying(conflict)) return 'lib-chip-success'
  if (isConflictProcessing(conflict)) return 'lib-chip-info'
  return 'lib-chip-info'
}

function isConflictSelected(conflictId) {
  return selectedConflictIds.value.includes(conflictId)
}

function setConflictSelected(conflictId, selected) {
  if (selected && !selectedConflictIds.value.includes(conflictId)) {
    selectedConflictIds.value = [...selectedConflictIds.value, conflictId]
    selectionAnchorId.value = conflictId
    return
  }
  if (!selected) {
    selectedConflictIds.value = selectedConflictIds.value.filter(id => id !== conflictId)
  }
}

function handleConflictCardClick(conflict, event) {
  if (!conflict?.id || batchRunning.value || isConflictRetrying(conflict)) {
    return
  }

  const conflictId = conflict.id
  const useRange = Boolean(event?.shiftKey) && selectionAnchorId.value
  const toggleMode = Boolean(event?.ctrlKey || event?.metaKey)

  if (useRange) {
    const ids = filteredConflicts.value.map(item => item.id)
    const startIndex = ids.indexOf(selectionAnchorId.value)
    const endIndex = ids.indexOf(conflictId)
    if (startIndex !== -1 && endIndex !== -1) {
      const [from, to] = startIndex < endIndex ? [startIndex, endIndex] : [endIndex, startIndex]
      selectedConflictIds.value = ids.slice(from, to + 1)
    } else {
      selectedConflictIds.value = [conflictId]
    }
  } else if (toggleMode) {
    if (isConflictSelected(conflictId)) {
      selectedConflictIds.value = selectedConflictIds.value.filter(id => id !== conflictId)
    } else {
      selectedConflictIds.value = [...selectedConflictIds.value, conflictId]
    }
  } else {
    selectedConflictIds.value = [conflictId]
  }

  activeConflictId.value = conflictId
  selectionAnchorId.value = conflictId
}

function toggleSelectAll() {
  if (isAllSelected.value) {
    clearSelection()
    return
  }
  selectedConflictIds.value = filteredConflicts.value.filter(conflict => !isConflictRetrying(conflict)).map(conflict => conflict.id)
  selectionAnchorId.value = selectedConflictIds.value[selectedConflictIds.value.length - 1] || ''
}

function clearSelection() {
  selectedConflictIds.value = []
  selectionAnchorId.value = ''
}

function selectedActionCount(action) {
  return selectedConflicts.value.filter(conflict => !isConflictRetrying(conflict) && canUseAction(conflict, action)).length
}

function getSelectedConflictsForAction(action) {
  return selectedConflicts.value.filter(conflict => !isConflictRetrying(conflict) && canUseAction(conflict, action))
}

function batchButtonLabel(action, label) {
  const count = selectedActionCount(action)
  return count ? `${label} (${count})` : label
}

function resolveErrorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

function formatConflictLabel(conflict) {
  return conflict?.rjcode || conflict?.new_metadata?.work_name || conflict?.new_path || '未识别问题项'
}

function getConflictSourcePath(conflict) {
  return conflict?.context?.source?.resolved_path || conflict?.context?.source?.path || conflict?.new_path || '-'
}

function getExistingConflictPath(conflict) {
  return conflict?.context?.existing?.path || conflict?.existing_path || '-'
}

function setBatchState(label, value) {
  batchRunning.value = value
  batchActionLabel.value = value ? label : ''
}

function buildPathPreview(paths) {
  const lines = paths.slice(0, 5)
  if (paths.length > lines.length) {
    lines.push(`以及另外 ${paths.length - lines.length} 项`)
  }
  return lines.join('\n')
}

function startRetryPoller(taskId, conflictId) {
  if (retryPollers.has(taskId)) return
  let attempts = 0
  const maxAttempts = 120
  const scheduleNext = () => {
    const delay = attempts < 10 ? 1500 : 5000
    const timerId = setTimeout(poll, delay)
    retryPollers.set(taskId, timerId)
  }

  const poll = async () => {
    attempts++
    try {
      const task = await taskCenterApi.getItem({ engine_task_id: taskId })
      if (task) {
        const taskStatus = String(task.status || '').trim().toLowerCase()
        if (taskStatus === 'completed') {
          retryPollers.delete(taskId)
          markConflictRetrying(conflictId, false)
          await fetchConflicts()
          if (!conflicts.value.some(item => item.id === conflictId)) {
            ElMessage.success('重试成功，已移出问题作品')
          } else {
            ElMessage.warning('重试任务已完成，但问题项仍在列表，请手动刷新确认')
          }
          return
        }
        if (taskStatus === 'failed') {
          retryPollers.delete(taskId)
          markConflictRetrying(conflictId, false)
          await fetchConflicts()
          ElMessage.warning(task.error_message ? `重试失败：${task.error_message}` : '重试失败，请查看任务详情')
          return
        }
      } else {
        await fetchConflicts()
        const conflict = conflicts.value.find(item => item.id === conflictId)
        if (!shouldKeepLocalRetrying(conflict)) {
          retryPollers.delete(taskId)
          markConflictRetrying(conflictId, false)
          return
        }
      }
      if (attempts % 4 === 0) {
        await fetchConflicts()
      }
    } catch (_) {
    }
    if (attempts < maxAttempts && retryPollers.has(taskId)) {
      scheduleNext()
    } else {
      retryPollers.delete(taskId)
      markConflictRetrying(conflictId, false)
      await fetchConflicts()
    }
  }

  const timerId = setTimeout(poll, 1000)
  retryPollers.set(taskId, timerId)
}

async function loadKeepNewPreview(conflict) {
  const response = await conflictApi.preview(conflict.id, 'KEEP_NEW')
  return response.preview || {}
}

function buildKeepNewSummary(conflict, preview) {
  return [
    `将删除目标目录：${preview.path || conflict.existing_path || '-'}`,
    `文件夹数：${preview.folder_count ?? 0}`,
    `文件数：${preview.file_count ?? 0}`,
    `大小：${formatFileSize(preview.size)}`
  ].join('\n')
}

async function resolveKeepNew(conflict, preview = null) {
  const effectivePreview = preview || await loadKeepNewPreview(conflict)
  const result = await conflictApi.resolve(conflict.id, {
    action: 'KEEP_NEW',
    confirmed: true
  })
  return {
    ...effectivePreview,
    ...result
  }
}

async function resolveSkip(conflict) {
  await conflictApi.resolve(conflict.id, {
    action: 'SKIP'
  })
  removeConflict(conflict.id)
}

async function startRetry(conflict, payload = {}) {
  return conflictApi.retry(conflict.id, payload)
}

async function askRetryPassword(conflict, batchCount = 1) {
  const isBatch = batchCount > 1
  // 仅当 conflict.new_metadata.extract_failure_reason === 'garbled_filename' 或带有
  // garbled_filename_sample / top_samples 时，才认定为乱码错误。其它失败原因（密码错、
  // 通用解压失败、SynologyError 等）不应该被强制走"指定编码 + 文件树预览"流程，
  // 否则会让大多数 EXTRACT_FAILED 用户多看一个无关弹窗。
  const isGarbledConflict = !isBatch && Boolean(getGarbledMeta(conflict))
  const titleLabel = isBatch
    ? `批量重试 ${batchCount} 个问题项`
    : `重试 ${conflict.rjcode || '当前问题项'}`
  const messageText = isBatch
    ? `可选：指定一个密码用于全部 ${batchCount} 项重试。如各项需要不同密码，请关闭后单独逐项重试。留空则各项按原逻辑走密码库、RJ 推导和默认密码。`
    : isGarbledConflict
      ? `可选：指定密码 + 文件名编码（当前：${getEncodingLabel(getFilenamePreviewEncoding(conflict))}），下一步会预览压缩包目录确认是否仍然乱码。留空密码按密码库 / RJ 推导继续。`
      : `可选：为这一条指定明文密码再重试；留空表示按密码库、RJ 推导、默认密码继续。当前问题项不是文件名乱码错误，无需指定 ZIP 文件名编码。`
  const confirmText = isBatch
    ? `开始批量重试 (${batchCount} 项)`
    : isGarbledConflict
      ? '下一步：编码预览'
      : '开始重试'
  try {
    const passwordValue = await showSystemPrompt({
      title: titleLabel,
      message: messageText,
      confirmText,
      cancelText: '取消',
      inputType: 'text',
      placeholder: '直接输入明文密码；留空表示正常重试',
      closeOnClickModal: false
    })
    const result = {
      cancelled: false,
      password: String(passwordValue || '').trim(),
      filenameEncoding: '',
      ignoreGarbled: false,
    }
    // 批量重试 / 非乱码错误：跳过编码预览弹窗，直接返回，让上层走纯密码重试。
    if (isBatch || !isGarbledConflict) return result
    result.filenameEncoding = getFilenamePreviewEncoding(conflict)
    const preview = await previewArchiveFilenames(conflict, {
      filenameEncoding: result.filenameEncoding,
      password: result.password,
    })
    preview.requested_encoding = result.filenameEncoding
    ensureFilenamePreviewState(conflict).preview = preview
    await showFilenamePreviewConfirm(preview, {
      confirmText: preview.garbled_sample ? '仍然重试并忽略乱码' : '按该编码重试',
      cancelText: '取消',
    })
    result.ignoreGarbled = Boolean(preview.garbled_sample)
    return result
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return { cancelled: true, password: '', filenameEncoding: '', ignoreGarbled: false }
    }
    throw error
  }
}

async function previewArchiveFilenames(conflict, { filenameEncoding = '', password = '' } = {}) {
  const normalizedEncoding = String(filenameEncoding || '').trim()
  const previewResponse = await conflictApi.filenamePreview(conflict.id, {
    filename_encoding: normalizedEncoding === 'auto' ? '' : normalizedEncoding,
    password: String(password || '').trim(),
    limit: 80,
  })
  return previewResponse.preview || {}
}

function buildFilenamePreviewLines(preview) {
  const diagList = Array.isArray(preview.diagnostics) ? preview.diagnostics : []
  const encoding = preview.requested_encoding || preview.encoding || 'shift_jis'
  const fileLines = diagList.slice(0, 20).map(d => {
    const icon = d.garbled ? '[疑似乱码]' : '[正常]'
    const scoreStr = d.score != null ? ` [${d.score}]` : ''
    return `${icon} ${formatPreviewName(d.name, encoding) || '—'}${scoreStr}`
  })
  if (!fileLines.length) {
    const names = (preview.items || []).slice(0, 20).map(item => formatPreviewName(item.name, encoding)).filter(Boolean)
    fileLines.push(...names)
  }
  const garbledCount = diagList.filter(d => d.garbled).length
  return [
    `编码：${preview.encoding || 'auto'} / codepage=${preview.codepage || 'auto'}`,
    `密码来源：${preview.password_source || '未指定'}`,
    `文件总数：${preview.file_count || 0}${garbledCount ? `，仍疑似乱码：${garbledCount} 个` : '，未检测到乱码文件名'}`,
    '',
    ...fileLines,
  ]
}

async function showFilenamePreviewConfirm(preview, options = {}) {
  if (!options.confirmText) {
    // 纯信息展示，无需确认
    fpDlgCancelText.value = ''
    await openFilenamePreviewDialog(preview, { confirmText: '关闭', cancelText: '' })
    return
  }
  await openFilenamePreviewDialog(preview, {
    confirmText: options.confirmText,
    cancelText: options.cancelText || '取消',
  })
}

async function handleFilenamePreview(conflict) {
  markAction(conflict.id, 'PREVIEW_FILENAME', true)
  try {
    const state = ensureFilenamePreviewState(conflict)
    const preview = await previewArchiveFilenames(conflict, {
      filenameEncoding: state.encoding,
    })
    preview.requested_encoding = state.encoding
    state.preview = preview
    ElMessage.success('文件名预览已刷新')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('预览压缩包文件名失败:', error)
      ElMessage.error(resolveErrorMessage(error, '预览文件名失败'))
    }
  } finally {
    markAction(conflict.id, 'PREVIEW_FILENAME', false)
  }
}

async function getMergePreview(conflict, forceRefresh = false, onProgress = null) {
  let preview = mergePreviewCache[conflict.id]
  if (preview && !forceRefresh) return preview
  // 后端 POST /preview 在 action=MERGE 时立即返回 {async: true, job_id, status: 'running', ...}，
  // KEEP_NEW 仍然同步返回 preview。这里兼容两种返回：
  // - 老 sync 路径：直接拿 preview 缓存
  // - 新 async 路径：轮询 /preview-job/{job_id} 直到 status=completed/failed
  const initial = await conflictApi.preview(conflict.id, 'MERGE')
  if (!initial?.async || !initial?.job_id) {
    // 兼容老接口（或后端未启用 async）：当成完整 preview 处理
    preview = initial
    mergePreviewCache[conflict.id] = preview
    return preview
  }
  // 先把首帧 progress 推给 caller，让弹窗的 loading 卡立刻有内容
  if (typeof onProgress === 'function') {
    onProgress({
      status: initial.status || 'running',
      stage: initial.stage || 'init',
      stage_label: initial.stage_label || '初始化',
      message: initial.message || '启动合并预览任务',
      percent: Math.max(0, Math.min(100, Number(initial.percent) || 0)),
    })
  }
  // 取消上一个 polling 句柄，避免快速点击合并产生竞态
  if (mergePreviewPollingAbort) {
    mergePreviewPollingAbort()
    mergePreviewPollingAbort = null
  }
  let cancelled = false
  mergePreviewPollingAbort = () => { cancelled = true }
  const jobId = initial.job_id
  const startedAt = Date.now()
  // 自适应轮询节奏：前 6s 每 600ms；之后 1.2s。总等待上限 15min（大压缩包 + 嵌套）。
  const MAX_WAIT_MS = 15 * 60 * 1000
  while (true) {
    if (cancelled) {
      const err = new Error('合并预览已取消')
      err.code = 'MERGE_PREVIEW_CANCELLED'
      throw err
    }
    if (Date.now() - startedAt > MAX_WAIT_MS) {
      throw new Error('合并预览超时（已等待 15 分钟）。后端 worker 可能仍在跑，可重新打开窗口查看。')
    }
    const interval = (Date.now() - startedAt < 6000) ? 600 : 1200
    await new Promise(resolve => setTimeout(resolve, interval))
    if (cancelled) continue
    let snapshot
    try {
      snapshot = await conflictApi.mergePreviewJob(conflict.id, jobId)
    } catch (error) {
      // 单次轮询失败不致命（可能网络抖动），但 404 表示 job 过期，直接抛错让 UI 处理
      if (error?.response?.status === 404) {
        throw new Error('合并预览任务已过期，请重新发起合并')
      }
      // 其它错误（网络抖动）静默重试
      continue
    }
    if (typeof onProgress === 'function') {
      onProgress({
        status: snapshot.status || 'running',
        stage: snapshot.stage || '',
        stage_label: snapshot.stage_label || '',
        message: snapshot.message || '',
        percent: Math.max(0, Math.min(100, Number(snapshot.percent) || 0)),
      })
    }
    if (snapshot.status === 'completed' && snapshot.result) {
      preview = snapshot.result
      mergePreviewCache[conflict.id] = preview
      mergePreviewPollingAbort = null
      return preview
    }
    if (snapshot.status === 'failed') {
      mergePreviewPollingAbort = null
      const err = new Error(snapshot.error || snapshot.message || '合并预览失败')
      err.code = 'MERGE_PREVIEW_FAILED'
      err.stage = snapshot.stage
      throw err
    }
    // status === 'running' 继续 loop
  }
}

function resetMergePreviewProgress() {
  mergePreviewProgress.value = {
    status: 'idle',
    stage: '',
    stage_label: '',
    message: '',
    percent: 0,
  }
}

function cancelMergePreviewPolling() {
  if (mergePreviewPollingAbort) {
    mergePreviewPollingAbort()
    mergePreviewPollingAbort = null
  }
}

async function resolveMerge(conflict, preview = null, decisions = null) {
  const effectivePreview = preview || await getMergePreview(conflict)
  const effectiveDecisions = decisions || mergeDecisionCache[conflict.id] || effectivePreview.default_decisions || {}
  await conflictApi.resolve(conflict.id, {
    action: 'MERGE',
    merge_session_id: effectivePreview.session_id,
    merge_decisions: effectiveDecisions
  })
  removeConflict(conflict.id)
  return effectivePreview
}

async function presentBatchResult(actionLabel, successes, failures, extraMessage = '') {
  const summary = `${actionLabel}完成：成功 ${successes.length} 项${failures.length ? `，失败 ${failures.length} 项` : ''}`

  if (!successes.length && failures.length) {
    ElMessage.error(summary)
  } else if (failures.length) {
    ElMessage.warning(summary)
  } else {
    ElMessage.success(summary)
  }

  if (!failures.length) {
    return
  }

  const detailLines = failures.slice(0, 8).map(item => `${formatConflictLabel(item.conflict)}：${item.message}`)
  if (failures.length > detailLines.length) {
    detailLines.push(`另有 ${failures.length - detailLines.length} 项失败`)
  }
  if (extraMessage) {
    detailLines.unshift(extraMessage)
  }

  await showSystemAlert({
    title: `${actionLabel}详情`,
    message: detailLines.join('\n'),
    tone: 'warning',
    confirmText: '知道了'
  })
}

async function handleRetry(conflict) {
  markAction(conflict.id, 'RETRY', true)
  try {
    const retryInput = await askRetryPassword(conflict)
    if (retryInput.cancelled) return
    const retryPayload = {}
    if (retryInput.password) retryPayload.password = retryInput.password
    if (retryInput.filenameEncoding) retryPayload.filename_encoding = retryInput.filenameEncoding
    if (retryInput.ignoreGarbled) retryPayload.ignore_garbled = true
    const result = await startRetry(conflict, retryPayload)
    markConflictRetrying(conflict.id, true)
    ElMessage.success(
      result.already_running
        ? (retryInput.password ? '已将指定密码应用到现有重试任务，后台持续跟踪结果' : '已存在重试任务，后台持续跟踪结果')
        : (retryInput.password ? '已开始使用指定密码重试，后台轮询中' : '已开始重试，后台轮询中')
    )
    await fetchConflicts()
    startRetryPoller(result.task_id, conflict.id)
  } catch (error) {
    console.error('重试问题作品失败:', error)
    ElMessage.error(resolveErrorMessage(error, '重试失败'))
  } finally {
    markAction(conflict.id, 'RETRY', false)
  }
}

async function handleKeepNew(conflict) {
  markAction(conflict.id, 'KEEP_NEW', true)
  try {
    const preview = await loadKeepNewPreview(conflict)
    await showSystemConfirm({
      title: '删除审查确认',
      message: buildKeepNewSummary(conflict, preview),
      tone: 'danger',
      confirmText: '确认删除并写入新内容',
      cancelText: '取消'
    })

    const result = await resolveKeepNew(conflict, preview)
    await fetchConflicts()
    ElMessage.success(result?.message || '已提交保留新版后台任务')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('保留新版失败:', error)
      ElMessage.error(resolveErrorMessage(error, '保留新版失败'))
    }
  } finally {
    markAction(conflict.id, 'KEEP_NEW', false)
  }
}

async function handleSkip(conflict) {
  markAction(conflict.id, 'SKIP', true)
  try {
    await showSystemConfirm({
      title: '跳过当前压缩包',
      message: `将直接删除待处理来源：${getConflictSourcePath(conflict)}`,
      tone: 'warning',
      confirmText: '确认跳过',
      cancelText: '取消'
    })

    await resolveSkip(conflict)
    ElMessage.success('已跳过当前包')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('跳过失败:', error)
      ElMessage.error(resolveErrorMessage(error, '跳过失败'))
    }
  } finally {
    markAction(conflict.id, 'SKIP', false)
  }
}

async function handleBatchKeepNew() {
  const targets = getSelectedConflictsForAction('KEEP_NEW')
  if (!targets.length) {
    ElMessage.warning('请先勾选可执行"保留新版"的问题项')
    return
  }

  setBatchState('保留新版', true)
  try {
    const previewEntries = []
    const failures = []

    for (const conflict of targets) {
      try {
        const preview = await loadKeepNewPreview(conflict)
        previewEntries.push({ conflict, preview })
      } catch (error) {
        failures.push({ conflict, message: resolveErrorMessage(error, '生成删除审查失败') })
      }
    }

    if (!previewEntries.length) {
      await presentBatchResult('批量保留新版', [], failures)
      return
    }

    const totalFiles = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.file_count || 0), 0)
    const totalFolders = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.folder_count || 0), 0)
    const totalSize = previewEntries.reduce((sum, entry) => sum + Number(entry.preview.size || 0), 0)
    const previewPaths = previewEntries.map(entry => entry.preview.path || entry.conflict.existing_path || '-')

    await showSystemConfirm({
      title: '批量删除审查确认',
      message: [
        `将批量保留新版 ${previewEntries.length} 项`,
        `待删除文件夹数：${totalFolders}`,
        `待删除文件数：${totalFiles}`,
        `待删除总大小：${formatFileSize(totalSize)}`,
        '',
        buildPathPreview(previewPaths)
      ].join('\n'),
      tone: 'danger',
      confirmText: '确认批量执行',
      cancelText: '取消'
    })

    const successes = []
    for (const entry of previewEntries) {
      try {
        await resolveKeepNew(entry.conflict, entry.preview)
        successes.push(entry.conflict)
      } catch (error) {
        failures.push({ conflict: entry.conflict, message: resolveErrorMessage(error, '保留新版失败') })
      }
    }

    await presentBatchResult('批量保留新版', successes, failures)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('批量保留新版失败:', error)
      ElMessage.error(resolveErrorMessage(error, '批量保留新版失败'))
    }
  } finally {
    setBatchState('', false)
  }
}

async function handleBatchSkip() {
  const targets = getSelectedConflictsForAction('SKIP')
  if (!targets.length) {
    ElMessage.warning('请先勾选可执行"跳过"的问题项')
    return
  }

  setBatchState('跳过', true)
  try {
    await showSystemConfirm({
      title: '批量跳过确认',
      message: [
        `将批量跳过 ${targets.length} 项，并删除它们的待处理来源。`,
        '',
        buildPathPreview(targets.map(conflict => getConflictSourcePath(conflict)))
      ].join('\n'),
      tone: 'warning',
      confirmText: '确认批量跳过',
      cancelText: '取消'
    })

    const successes = []
    const failures = []
    for (const conflict of targets) {
      try {
        await resolveSkip(conflict)
        successes.push(conflict)
      } catch (error) {
        failures.push({ conflict, message: resolveErrorMessage(error, '跳过失败') })
      }
    }

    await presentBatchResult('批量跳过', successes, failures)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('批量跳过失败:', error)
      ElMessage.error(resolveErrorMessage(error, '批量跳过失败'))
    }
  } finally {
    setBatchState('', false)
  }
}

async function handleBatchMerge() {
  const targets = getSelectedConflictsForAction('MERGE')
  if (!targets.length) {
    ElMessage.warning('请先勾选可执行"合并"的问题项')
    return
  }

  setBatchState('合并', true)
  try {
    await showSystemConfirm({
      title: '批量合并确认',
      message: [
        `将批量合并 ${targets.length} 项。`,
        '未单独打开工作台的项目会按默认合并决策直接执行。',
        '如果某项已经在工作台调整过决策，将优先沿用已保存的决策。'
      ].join('\n'),
      tone: 'warning',
      confirmText: '确认批量合并',
      cancelText: '取消'
    })

    const successes = []
    const failures = []
    for (const conflict of targets) {
      try {
        const preview = await getMergePreview(conflict)
        const decisions = mergeDecisionCache[conflict.id] || preview.default_decisions || {}
        await resolveMerge(conflict, preview, decisions)
        successes.push(conflict)
      } catch (error) {
        failures.push({ conflict, message: resolveErrorMessage(error, '合并失败') })
      }
    }

    await presentBatchResult('批量合并', successes, failures)
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('批量合并失败:', error)
      ElMessage.error(resolveErrorMessage(error, '批量合并失败'))
    }
  } finally {
    setBatchState('', false)
  }
}

function handleBatchRetry() {
  const targets = getSelectedConflictsForAction('RETRY')
  if (!targets.length) {
    ElMessage.warning('请先勾选可执行"重试"的问题项')
    return
  }
  batchRetryTargets.value = targets
  batchRetryDialogVisible.value = true
}

async function handleBatchRetryConfirm(entries) {
  const targets = batchRetryTargets.value
  if (!targets.length) return
  setBatchState('重试', true)
  const passwordMap = Object.fromEntries(entries.map(e => [e.conflictId, e.password]))
  const successes = []
  const failures = []
  try {
    for (const conflict of targets) {
      try {
        const pw = passwordMap[conflict.id] || ''
        const result = await startRetry(conflict, pw ? { password: pw } : {})
        markConflictRetrying(conflict.id, true)
        successes.push(conflict)
        startRetryPoller(result.task_id, conflict.id)
      } catch (error) {
        failures.push({ conflict, message: resolveErrorMessage(error, '提交重试失败') })
      }
    }
    await fetchConflicts()
    await presentBatchResult(
      '批量重试',
      successes,
      failures,
      `${successes.length} 项重试已提交，后台轮询结果中，可到任务列表跟踪进度。`
    )
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('批量重试失败:', error)
      ElMessage.error(resolveErrorMessage(error, '批量重试失败'))
    }
  } finally {
    setBatchState('', false)
  }
}

// ---- 详情区按钮 batch-aware dispatch ----
// 之前模板上 SKIP / KEEP_NEW / RETRY 三个按钮直接调单条 handler，导致用户多选后
// 在详情区按按钮"只跳过一个"——按钮只对 activeConflict 生效。这一组 dispatch
// 把当前 active 是否在多选集合里的判断包装起来：
//   - 在多选集合里且 selectedCount > 1 → 走 batch handler（一次跳掉/重试/保留所有勾选）
//   - 否则维持原单条行为
// 配套的 *DispatchLabel 让按钮文案在多选状态下变成 "批量跳过 (N)" 之类，
// 用户能一眼看出来这是一次批量操作。
function isBatchableActive(conflict, action) {
  if (!conflict?.id) return false
  if (selectedCount.value <= 1) return false
  if (!isConflictSelected(conflict.id)) return false
  return selectedActionCount(action) > 1
}

function handleSkipDispatch(conflict) {
  if (isBatchableActive(conflict, 'SKIP')) return handleBatchSkip()
  return handleSkip(conflict)
}

function handleKeepNewDispatch(conflict) {
  if (isBatchableActive(conflict, 'KEEP_NEW')) return handleBatchKeepNew()
  return handleKeepNew(conflict)
}

function handleRetryDispatch(conflict) {
  if (isBatchableActive(conflict, 'RETRY')) return handleBatchRetry()
  return handleRetry(conflict)
}

function skipDispatchLabel(conflict) {
  if (isActionLoading(conflict?.id, 'SKIP')) return '跳过中'
  if (isBatchableActive(conflict, 'SKIP')) {
    return `批量跳过 (${selectedActionCount('SKIP')})`
  }
  return '跳过'
}

function keepNewDispatchLabel(conflict) {
  if (isActionLoading(conflict?.id, 'KEEP_NEW')) return '保留新版中'
  if (isBatchableActive(conflict, 'KEEP_NEW')) {
    return `批量保留新版 (${selectedActionCount('KEEP_NEW')})`
  }
  return '保留新版'
}

function retryDispatchLabel(conflict) {
  if (isConflictRetrying(conflict)) return '重试中'
  if (isBatchableActive(conflict, 'RETRY')) {
    return `批量重试 (${selectedActionCount('RETRY')})`
  }
  return '重试'
}

async function openMergeWorkbench(conflict, forceRefresh = false) {
  mergeConflictId.value = conflict.id
  mergeDialogVisible.value = true
  mergeLoading.value = true
  // 重置 progress，让弹窗 loading 卡从"初始化"开始而不是上一次的残值
  resetMergePreviewProgress()
  mergePreviewProgress.value = {
    status: 'running',
    stage: 'init',
    stage_label: '初始化',
    message: '准备生成合并预览',
    percent: 1,
  }
  try {
    // 把后端 job 实时进度写到 mergePreviewProgress.value，工作台 loading panel 监听这个 state
    const preview = await getMergePreview(conflict, forceRefresh, (snapshot) => {
      mergePreviewProgress.value = snapshot
    })
    mergePreview.value = preview
    mergeDecisions.value = {
      ...(mergeDecisionCache[conflict.id] || preview.default_decisions || {})
    }
    mergePreviewProgress.value = {
      status: 'completed',
      stage: 'done',
      stage_label: '完成',
      message: `已生成 ${preview.items?.length || 0} 项差异`,
      percent: 100,
    }
  } catch (error) {
    // 用户主动取消（关闭弹窗 / 重新打开触发上一个 abort）不弹错
    if (error?.code === 'MERGE_PREVIEW_CANCELLED') {
      return
    }
    console.error('生成合并预览失败:', error)
    ElMessage.error(resolveErrorMessage(error, '生成合并预览失败'))
    mergeDialogVisible.value = false
  } finally {
    mergeLoading.value = false
  }
}

function handleDecisionUpdate(value) {
  mergeDecisions.value = value
  if (mergeConflictId.value) {
    mergeDecisionCache[mergeConflictId.value] = { ...value }
  }
}

function refreshMergePreview() {
  if (!mergeConflict.value) {
    return
  }
  openMergeWorkbench(mergeConflict.value, true)
}

async function submitMerge() {
  if (!mergeConflict.value || !mergePreview.value) {
    return
  }

  mergeSubmitting.value = true
  try {
    await resolveMerge(mergeConflict.value, mergePreview.value, mergeDecisions.value)
    ElMessage.success('合并结果已提交')
    mergeDialogVisible.value = false
    mergePreview.value = null
    mergeConflictId.value = ''
    mergeDecisions.value = {}
  } catch (error) {
    console.error('提交合并失败:', error)
    ElMessage.error(resolveErrorMessage(error, '提交合并失败'))
  } finally {
    mergeSubmitting.value = false
  }
}

function removeConflict(conflictId) {
  conflicts.value = conflicts.value.filter(conflict => conflict.id !== conflictId)
  selectedConflictIds.value = selectedConflictIds.value.filter(id => id !== conflictId)
  delete mergePreviewCache[conflictId]
  delete mergeDecisionCache[conflictId]
  if (mergeConflictId.value === conflictId) {
    mergeConflictId.value = ''
    mergePreview.value = null
    mergeDecisions.value = {}
  }
  syncActiveConflict()
}

function getConflictTypeLabel(type) {
  return {
    DUPLICATE: '完全重复',
    LANGUAGE_VARIANT: '多语言版本',
    MULTIPLE_VERSIONS: '多版本冲突',
    LINKED_WORK_ORIGINAL: '原作已入库',
    LINKED_WORK_TRANSLATION: '翻译版已入库',
    LINKED_WORK_CHILD: '子版本已入库',
    LINKED_WORK: '关联作品',
    EXTRACT_FAILED: '解压失败',
    PROCESS_FAILED: '处理失败'
  }[type] || type || '未知冲突'
}

// 比 getConflictTypeLabel 更细：根据 analysis_info / linked_works_info 拆出具体子类型，
// 让用户看到"为什么算关联冲突"。后端有两个写入点：
//   1) duplicate_service.py 按 DLsite 关联链 + 本地命中的 work_type 给出
//      LINKED_WORK_ORIGINAL / LINKED_WORK_TRANSLATION / LINKED_WORK_CHILD / LINKED_WORK
//   2) linked_subtitle_import_service.py 把 conflict_type 直接写成 LINKED_WORK，
//      但 analysis_info.source_mode 里会带 "existing_subtitle" 字样（原作已含字幕，
//      翻译版没有补配价值的场景）
// 这里把这两类都给出比"关联作品"更明确的描述。
function getConflictTypeDetail(conflict) {
  const type = String(conflict?.conflict_type || '').toUpperCase()
  const analysis = conflict?.analysis_info || {}
  const linked = Array.isArray(conflict?.linked_works_info) ? conflict.linked_works_info : []

  if (type === 'LINKED_WORK_ORIGINAL') {
    const rj = linked[0]?.rjcode
    return rj ? `原作已入库（${rj}）` : '原作已入库'
  }
  if (type === 'LINKED_WORK_TRANSLATION') {
    const rj = linked[0]?.rjcode
    return rj ? `翻译版已入库（${rj}）` : '翻译版已入库'
  }
  if (type === 'LINKED_WORK_CHILD') {
    const rj = linked[0]?.rjcode
    return rj ? `子版本已入库（${rj}）` : '子版本已入库'
  }

  if (type === 'LINKED_WORK') {
    // linked_subtitle_import_service：原作已含字幕场景
    const sourceMode = String(analysis?.source_mode || '').toLowerCase()
    if (sourceMode.includes('existing_subtitle')) {
      return '原作已含字幕，翻译版无需补配'
    }

    // 兜底用 linked_works_info 给出更具体说明
    if (linked.length === 1) {
      const work = linked[0]
      const wtype = String(work?.work_type || '').toLowerCase()
      const rj = work?.rjcode || ''
      if (wtype === 'original') return rj ? `原作已入库（${rj}）` : '原作已入库'
      if (wtype === 'translation' || wtype === 'child_translation') {
        return rj ? `翻译版已入库（${rj}）` : '翻译版已入库'
      }
      return rj ? `关联作品已入库（${rj}）` : '关联作品已入库'
    }
    if (linked.length > 1) {
      return `已入库 ${linked.length} 个关联作品`
    }
    return '关联作品已入库'
  }

  return getConflictTypeLabel(type)
}

function formatDate(value) {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '-'
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

function formatTimestamp(value) {
  if (value === null || value === undefined) {
    return '-'
  }
  return formatDate(new Date(Number(value) * 1000).toISOString())
}

function formatFileSize(size) {
  if (size === null || size === undefined) return '-'
  const value = Number(size)
  if (!Number.isFinite(value) || value < 0) return '-'
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let current = value / 1024
  let unitIndex = 0
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024
    unitIndex += 1
  }
  return `${current.toFixed(current >= 10 ? 1 : 2)} ${units[unitIndex]}`
}

// 详情区 stats 字段展示器：stats 缺失 + 后台正在补齐 → "统计中…"，否则按原格式化走。
// 把"未知"和"正在算"区分开，避免用户看到 "-" 误以为没数据。
function displayStatSize(stats) {
  if (stats?.size != null) return formatFileSize(stats.size)
  return statsBackfilling.value ? '统计中…' : '-'
}
function displayStatTime(stats) {
  if (stats?.created_at != null) return formatTimestamp(stats.created_at)
  return statsBackfilling.value ? '统计中…' : '-'
}
</script>

<style scoped>
button:not(:disabled) {
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
}

/* ==============================================================
 * 页面整体布局
 * ============================================================ */
.conflicts-page {
  display: flex;
  flex-direction: column;
  /* 用 height: 100% + min-height: 0 锁定到 .content-shell 视口高度，让
     左侧列表 .conflicts-list-scroll 的 flex: 1 + overflow-y: auto 真正生效。
     原来用 min-height: 100% 时，列表项目过多会撑高 page，由 .content-shell
     接管整页滚动，视觉上左侧列表会无限向下延伸。 */
  height: 100%;
  min-height: 0;
  padding: 18px 24px 24px;
  /* App.vue 已有 #fbfbfd → #f2f2f5 全局渐变，这里不要再叠灰，避免双层灰过度 */
  background: transparent;
}

/* 页面头部现在走共享组件 components/common/AppPageHeader.vue，这里不再重复定义 */

/* 刷新按钮：纯白底 + hover 上浮动画 + 图标旋转 */
.conflicts-refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #fff;
  color: #475569;
  font-size: 12.5px;
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
              box-shadow 0.25s ease,
              border-color 0.18s ease,
              background-color 0.18s ease,
              color 0.18s ease;
}
.conflicts-refresh-btn :deep(svg) {
  transition: transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.conflicts-refresh-btn:hover {
  border-color: rgba(15, 23, 42, 0.18);
  background: #fff;
  color: #0f172a;
  transform: translateY(-1px);
  box-shadow: 0 6px 16px -6px rgba(15, 23, 42, 0.18);
}
.conflicts-refresh-btn:hover:not(:disabled) :deep(svg) {
  transform: rotate(180deg);
}
.conflicts-refresh-btn:active:not(:disabled) { transform: translateY(0) scale(0.97); }
.conflicts-refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* 信息条：纯白 + 极淡黑灰边 + 一层柔阴影 */
.lib-info-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr);
  align-items: stretch;
  gap: 0;
  margin-bottom: 18px;
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
/* 数字加重：更大字号 + tabular-nums 避免跳动 */
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

/* ============================================================
 * 移动端 (≤1024)：整页 stream 模式
 * 桌面端零改动：仅 @media 内覆盖
 * 痛点：桌面是 flex h-full + main 双栏 list/detail 各自滚，
 *      移动端 list 360px 撑死 + detail 没空间。
 * 解法：双栏 → flex-col stack；内部滚动区松绑；整页 .content-shell 滚。
 * ============================================================ */
@media (max-width: 1024px) {
  .conflicts-page {
    /* 移动端走整页 stream 滚动：放开 desktop 的 height: 100% 锁定，
       让 .content-shell 重新接管页面级滚动，否则 list/detail 上下堆叠
       会被强行压在视口高度里。 */
    height: auto !important;
    min-height: auto !important;
    overflow: visible !important;
  }
  .conflicts-main {
    flex: 0 0 auto !important;
    flex-direction: column !important;
    overflow: visible !important;
    min-height: 0 !important;
    gap: 12px;
  }
  .conflicts-list-pane,
  .conflicts-detail-pane {
    width: 100% !important;
    flex: 0 0 auto !important;
    height: auto !important;
    min-height: 0 !important;
    overflow: visible !important;
  }
  /* 内部滚动区松绑：让内容自然撑开 */
  .conflicts-list-scroll,
  .conflicts-detail-body {
    overflow: visible !important;
    flex: 0 0 auto !important;
    max-height: none !important;
  }
  /* 批量动作按钮 wrap + 50% 等宽 */
  .conflicts-batch-actions {
    flex-wrap: wrap;
  }
  .conflicts-batch-actions > button {
    flex: 1 1 calc(50% - 3px);
    min-width: 0;
    justify-content: center;
  }
}

@media (max-width: 640px) {
  .conflicts-page {
    padding-left: 10px !important;
    padding-right: 10px !important;
  }
  .conflicts-list-pane,
  .conflicts-detail-pane {
    border-radius: 14px;
  }
  /* detail-header padding 紧凑 */
  .conflicts-detail-header {
    padding: 16px !important;
  }
  .conflicts-detail-body {
    padding: 14px !important;
  }
}

/* 小 chip */
.lib-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;
}
.lib-chip-success { background: rgba(220, 252, 231, 0.8); color: #047857; border: 1px solid rgba(134, 239, 172, 0.5); }
.lib-chip-warning { background: rgba(254, 243, 199, 0.8); color: #b45309; border: 1px solid rgba(253, 224, 71, 0.5); }
.lib-chip-danger { background: rgba(254, 226, 226, 0.8); color: #b91c1c; border: 1px solid rgba(252, 165, 165, 0.5); }
.lib-chip-info { background: rgba(224, 231, 255, 0.8); color: #4338ca; border: 1px solid rgba(165, 180, 252, 0.5); }

/* 错误提示：纯色红底 */
.conflicts-error-alert {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 16px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #fef2f2;
  border: 1px solid rgba(239, 68, 68, 0.18);
  color: #991b1b;
}

/* ==============================================================
 * 主工作区
 * ============================================================ */
.conflicts-main {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 18px;
  overflow: hidden;
}

.conflicts-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: #fff;
  border: 1px dashed rgba(15, 23, 42, 0.12);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  padding: 60px 20px;
  text-align: center;
}

/* ==============================================================
 * 左侧列表
 * ============================================================ */
.conflicts-list-pane {
  width: 360px;
  flex-shrink: 0;
  /* min-height: 0 兜底：作为 .conflicts-main flex row 子项，stretch 拿到的高度
     依赖父容器；显式 min-height: 0 保证内部 flex column 的 list-scroll 不被
     卡片内容反向撑大它本身的高度，让 overflow: hidden 真正生效。 */
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}
@media (min-width: 1280px) {
  .conflicts-list-pane { width: 400px; }
}

.conflicts-list-header {
  flex-shrink: 0;
  padding: 14px 16px 12px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(248, 250, 252, 0.45);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.conflicts-list-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  letter-spacing: -0.2px;
}

/* 分段筛选 */
.conflicts-segmented {
  display: flex;
  padding: 3px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid rgba(15, 23, 42, 0.06);
}
.conflicts-segmented-item {
  flex: 1;
  height: 28px;
  padding: 0 10px;
  border-radius: 7px;
  border: none;
  background: transparent;
  font-size: 11.5px;
  font-weight: 500;
  color: #64748b;
  transition: all 0.2s ease;
}
.conflicts-segmented-item:hover { color: #334155; }
.conflicts-segmented-item.is-active {
  background: #fff;
  color: #0f172a;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
  font-weight: 600;
}

/* 列表小动作按钮 */
.conflicts-list-actions {
  display: flex;
  gap: 6px;
}
.conflicts-mini-btn {
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
.conflicts-mini-btn:hover {
  background: #f8fafc;
  border-color: rgba(15, 23, 42, 0.18);
  color: #0f172a;
}
.conflicts-mini-btn.is-active {
  background: #e0f2fe;
  border-color: rgba(2, 132, 199, 0.3);
  color: #0c4a6e;
}
.conflicts-mini-btn:disabled { opacity: 0.5; }

/* 批量动作按钮：列表区紧凑型 */
.conflicts-batch-actions {
  display: flex;
  gap: 6px;
  animation: conflicts-fade-in 0.2s ease;
}
.conflicts-batch-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 30px;
  padding: 0 10px;
  border-radius: 9px;
  border: 1px solid transparent;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: #fff;
  position: relative;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.conflicts-batch-btn :deep(svg) {
  transition: transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}
/* disabled：仅 opacity + cursor，不重置 transform/shadow，避免 hover 中点击瞬间塌回闪烁 */
.conflicts-batch-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.conflicts-batch-btn:hover { transform: translateY(-2px); }
.conflicts-batch-btn:active:not(:disabled) {
  transform: translateY(0) scale(0.96);
  transition: all 0.12s ease;
}

/* 批量重试：扁平克制风 → emerald 单色面 + 1px 实色边 + 极浅阴影 */
/* 取消三段渐变与双层 glow：30px 高的小按钮下多层渐变会被挤压成斜条、"塑料"感明显。 */
.conflicts-batch-btn.is-emerald {
  background: #10b981;
  border-color: #059669;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.16),
    0 1px 2px rgba(15, 23, 42, 0.05);
}
.conflicts-batch-btn.is-emerald:hover:not(:disabled) {
  background: #059669;
  border-color: #047857;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.2),
    0 4px 12px -4px rgba(16, 185, 129, 0.45);
}
.conflicts-batch-btn.is-emerald:hover:not(:disabled) :deep(svg) {
  transform: rotate(-180deg);
}

/* 批量跳过：白底 ghost → 保持原风格，与主操作拉开权重 */
.conflicts-batch-btn.is-slate {
  background: #ffffff;
  color: #475569;
  border-color: rgba(15, 23, 42, 0.12);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.conflicts-batch-btn.is-slate:hover:not(:disabled) {
  background: #f8fafc;
  color: #0f172a;
  border-color: rgba(15, 23, 42, 0.22);
  box-shadow: 0 4px 12px -4px rgba(15, 23, 42, 0.12);
}
.conflicts-batch-btn.is-slate:hover:not(:disabled) :deep(svg) {
  transform: translateX(2px);
}

.conflicts-list-hint {
  margin: 0;
  font-size: 10.5px;
  color: #94a3b8;
  text-align: center;
}

/* 列表滚动区 */
.conflicts-list-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 筛选为空时的列表内嵌空态（保留上方筛选按钮可见）*/
.conflicts-list-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
  color: #94a3b8;
}

/* 列表卡片：中性灰选中态，macOS Finder / Notion 风格 —— 克制、不刺眼、不加竖条 */
.conflicts-list-card {
  position: relative;
  width: 100%;
  text-align: left;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: transparent;
  transition: background-color 0.18s ease, border-color 0.18s ease;
  overflow: hidden;
}
.conflicts-list-card:hover {
  background: rgba(15, 23, 42, 0.04);
  border-color: rgba(15, 23, 42, 0.06);
}
/* 多选勾选（非焦点项）：最浅的灰底 */
.conflicts-list-card.is-selected {
  background: #f1f5f9;
  border-color: rgba(15, 23, 42, 0.1);
}
/* 当前查看项（焦点）：稍深灰底 + 加深边 + 标题加粗更重 */
.conflicts-list-card.is-active {
  background: #e2e8f0;
  border-color: rgba(15, 23, 42, 0.18);
}
.conflicts-list-card.is-active .conflicts-list-card-title {
  color: #0f172a;
}

.conflicts-list-card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.conflicts-list-card-title {
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
.conflicts-list-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
}
.conflicts-list-card-type {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #64748b;
  font-weight: 500;
}
.conflicts-list-card-date {
  color: #94a3b8;
  font-size: 11px;
  margin-left: auto;
}

.conflicts-list-card-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.conflicts-list-progress-track {
  flex: 1;
  height: 4px;
  border-radius: 999px;
  background: rgba(220, 252, 231, 0.6);
  overflow: hidden;
}
.conflicts-list-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #10b981, #14b8a6);
  border-radius: 999px;
  transition: width 0.5s ease;
}
.conflicts-list-progress-num {
  font-size: 10.5px;
  font-weight: 700;
  color: #047857;
  font-variant-numeric: tabular-nums;
}

/* ==============================================================
 * 右侧详情
 * ============================================================ */
.conflicts-detail-pane {
  flex: 1;
  /* min-height: 0 兜底：理由同 .conflicts-list-pane，避免详情内容过长反向
     撑大 pane 破坏 .conflicts-detail-body 的 overflow-y 链。 */
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px -16px rgba(15, 23, 42, 0.08);
  overflow: hidden;
}

.conflicts-detail-header {
  position: relative;
  flex-shrink: 0;
  padding: 22px 26px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
  background: #f8fafc;
  overflow: hidden;
}
.conflicts-detail-bg-glyph {
  position: absolute;
  top: -20px;
  right: -20px;
  color: #cbd5e1;
  opacity: 0.08;
  pointer-events: none;
}
.conflicts-detail-header-inner {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
@media (min-width: 1280px) {
  .conflicts-detail-header-inner { flex-direction: row; align-items: center; justify-content: space-between; gap: 20px; }
}

.conflicts-detail-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.4px;
  color: #0f172a;
  line-height: 1.2;
}
.conflicts-detail-subtitle {
  margin: 6px 0 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
  color: #64748b;
}
.conflicts-detail-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 999px;
}
.conflicts-detail-dot.is-info { background: #0284c7; box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15); }
.conflicts-detail-dot.is-danger { background: #ef4444; box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.15); }

/* 顶部操作按钮：详情区主变量 */
.conflicts-detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.conflicts-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  border-radius: 10px;
  border: 1px solid transparent;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: #fff;
  position: relative;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.conflicts-action-btn :deep(svg) {
  flex-shrink: 0;
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.conflicts-action-spinner {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
  animation: conflicts-action-spin 0.85s linear infinite;
  filter: drop-shadow(0 0 7px rgba(255, 255, 255, 0.48));
}

@keyframes conflicts-action-spin {
  to { transform: rotate(360deg); }
}
/* disabled：仅 opacity + cursor，不重置 transform/shadow，避免 hover 中点击瞬间塌回闪烁 */
.conflicts-action-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.conflicts-action-btn:hover { transform: translateY(-2px); }
.conflicts-action-btn:active:not(:disabled) {
  transform: translateY(0) scale(0.97);
  transition: all 0.12s ease;
}

/* 主操作按钮统一采用扁平克制风： */
/* 单色面 + 1px 同色系边 + 极浅 inset 顶高光 + hover 加深一档颜色 + 轻微抬起。 */
/* 去掉三段渐变 / 双层 glow / 底部 inset 暗影 / text-shadow，避免"塑料"感。 */

/* 保留新版：blue 主色 */
.conflicts-action-btn.is-primary {
  background: #2563eb;
  border-color: #1d4ed8;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 1px 2px rgba(15, 23, 42, 0.06);
}
.conflicts-action-btn.is-primary:hover:not(:disabled) {
  background: #1d4ed8;
  border-color: #1e40af;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 4px 14px -4px rgba(37, 99, 235, 0.5);
}
.conflicts-action-btn.is-primary:hover:not(:disabled) :deep(svg) {
  transform: scale(1.08) rotate(-3deg);
}

/* 重试：emerald */
.conflicts-action-btn.is-emerald {
  background: #10b981;
  border-color: #059669;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 1px 2px rgba(15, 23, 42, 0.06);
}
.conflicts-action-btn.is-emerald:hover:not(:disabled) {
  background: #059669;
  border-color: #047857;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 4px 14px -4px rgba(16, 185, 129, 0.5);
}
.conflicts-action-btn.is-emerald:hover:not(:disabled) :deep(svg) {
  transform: rotate(-180deg);
}

/* 跳过：白底 ghost，与主操作拉开视觉权重 */
.conflicts-action-btn.is-slate {
  background: #ffffff;
  color: #475569;
  border-color: rgba(15, 23, 42, 0.12);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    0 1px 2px rgba(15, 23, 42, 0.04);
}
.conflicts-action-btn.is-slate:hover:not(:disabled) {
  background: #f8fafc;
  color: #0f172a;
  border-color: rgba(15, 23, 42, 0.22);
  box-shadow: 0 4px 14px -4px rgba(15, 23, 42, 0.14);
}
.conflicts-action-btn.is-slate:hover:not(:disabled) :deep(svg) {
  transform: translateX(3px);
}

/* 合并：sober amber */
.conflicts-action-btn.is-amber {
  background: #d97706;
  border-color: #b45309;
  color: #ffffff;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.18),
    0 1px 2px rgba(15, 23, 42, 0.06);
}
.conflicts-action-btn.is-amber:hover:not(:disabled) {
  background: #b45309;
  border-color: #92400e;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 4px 14px -4px rgba(217, 119, 6, 0.5);
}
.conflicts-action-btn.is-amber:hover:not(:disabled) :deep(svg) {
  transform: scale(1.08) rotate(8deg);
}

/* 详情正文：透明，让外层 pane 的半透明白透出来 */
.conflicts-detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 22px 26px 28px;
  background: transparent;
}

/* 未选中时的右侧占位（复用 detail-pane 容器样式）*/
.conflicts-detail-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.conflicts-detail-placeholder-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 28px;
}

/* 失败提示框 */
.conflicts-detail-alert {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 18px;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid;
}
.conflicts-detail-alert.is-warning {
  background: rgba(254, 243, 199, 0.55);
  border-color: rgba(245, 158, 11, 0.2);
  color: #92400e;
}
.conflicts-detail-alert.is-danger {
  background: rgba(254, 226, 226, 0.55);
  border-color: rgba(239, 68, 68, 0.18);
  color: #991b1b;
}

.conflicts-garbled-card {
  margin-bottom: 18px;
  padding: 14px 16px;
  border: 1px solid rgba(245, 158, 11, 0.22);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 12px 28px -22px rgba(217, 119, 6, 0.35);
}
.conflicts-garbled-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.conflicts-garbled-head h4 {
  margin: 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 800;
}
.conflicts-garbled-head p {
  margin: 3px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}
.conflicts-garbled-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  margin-top: 12px;
  padding: 10px;
  border: 1px solid #f1f5f9;
  border-radius: 10px;
  background: #f8fafc;
}
.conflicts-garbled-select {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.conflicts-garbled-select > span {
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
}
.conflicts-garbled-preview-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  padding: 0 13px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 10px;
  background: #fff;
  color: #334155;
  font-size: 12px;
  font-weight: 800;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.conflicts-garbled-preview-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: rgba(15, 23, 42, 0.22);
  box-shadow: 0 8px 18px -12px rgba(15, 23, 42, 0.28);
}
.conflicts-garbled-preview-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.conflicts-garbled-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}
.conflicts-garbled-grid div {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid #f1f5f9;
  border-radius: 9px;
  background: #f8fafc;
}
.conflicts-garbled-grid span {
  display: block;
  color: #94a3b8;
  font-size: 10.5px;
  font-weight: 700;
}
.conflicts-garbled-grid b {
  display: block;
  margin-top: 3px;
  color: #334155;
  font-size: 12px;
  word-break: break-all;
}
/* 当出现非 UTF-8 文件名修复条目时占满整行，避免标签被强行挤窄 */
.conflicts-garbled-grid .conflicts-garbled-grid-wide {
  grid-column: 1 / -1;
}
.conflicts-garbled-samples {
  max-height: 150px;
  overflow-y: auto;
  margin-top: 10px;
  border: 1px solid #f1f5f9;
  border-radius: 10px;
}
.conflicts-garbled-row {
  display: grid;
  grid-template-columns: 1fr 52px;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 11.5px;
}
.conflicts-garbled-row:last-child { border-bottom: 0; }
.conflicts-garbled-row span {
  min-width: 0;
  color: #475569;
  font-weight: 600;
  word-break: break-all;
}
.conflicts-garbled-row b {
  color: #b45309;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.conflicts-filename-preview {
  margin-top: 10px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 14px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.04);
}
.conflicts-filename-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(29, 29, 31, 0.06);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.92) 0%, rgba(241, 245, 249, 0.86) 100%);
  color: #475569;
  font-size: 12px;
}
.conflicts-filename-preview-head b {
  color: #0f172a;
  white-space: nowrap;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
/* 内联预览 head 右侧徽章群（已自动反解 N 项 + 文件总数） */
.conflicts-filename-preview-badges {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
}
/* 后端反解徽章：与 garbled 警告色互补，绿色表示"已自动修复" */
.fp-repaired-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border-radius: 999px;
  background: linear-gradient(180deg, #ecfdf5 0%, #d1fae5 100%);
  border: 1px solid rgba(167, 243, 208, 0.9);
  color: #047857;
  font-weight: 700;
  font-size: 11px;
  white-space: nowrap;
}
/* 内联文件树（问题作品详情页 - 文件名乱码诊断卡里的 inline 预览）：
   贴齐 task-file-tree-card 卡片视觉，带顶底 fade mask + 滚动条统一风格 */
.conflicts-filename-preview-tree {
  position: relative;
  max-height: 280px;
  overflow-y: auto;
  padding: 8px 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.65) transparent;
}
.conflicts-filename-preview-tree::-webkit-scrollbar { width: 8px; height: 8px; }
.conflicts-filename-preview-tree::-webkit-scrollbar-track { background: transparent; margin: 6px 0; }
.conflicts-filename-preview-tree::-webkit-scrollbar-thumb {
  border: 2px solid rgba(255, 255, 255, 0.92);
  background: rgba(148, 163, 184, 0.52);
  border-radius: 999px;
}
.conflicts-filename-preview-tree::-webkit-scrollbar-thumb:hover {
  background: rgba(100, 116, 139, 0.68);
}

/* --- 文件名预览文件树通用行（与 TaskDetailPane.tree-row 视觉对齐） --- */
.fp-tree-row {
  position: relative;
  display: flex;
  min-height: 30px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
  padding: 5px 12px 5px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: rgb(30, 41, 59);
  cursor: default;
  transition: background-color 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}
.fp-tree-row:last-child { margin-bottom: 0; }
.fp-tree-row:hover {
  background: rgba(248, 250, 252, 0.7);
  box-shadow: inset 0 0 0 1px rgba(226, 232, 240, 0.84);
}
.fp-tree-main {
  position: relative;
  z-index: 1;
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 8px;
}
.fp-tree-expander-spacer {
  display: inline-block;
  width: 14px;
  flex: 0 0 14px;
}
.fp-tree-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  border-radius: 7px;
  background: rgba(241, 245, 249, 0.72);
  border: 1px solid rgba(226, 232, 240, 0.7);
}
.fp-tree-row:hover .fp-tree-icon-wrap {
  background: rgba(255, 255, 255, 0.86);
  border-color: rgba(203, 213, 225, 0.9);
}
.fp-tree-row.is-dir .fp-tree-icon-wrap {
  background: linear-gradient(180deg, rgba(254, 243, 199, 0.68) 0%, rgba(253, 230, 138, 0.45) 100%);
  border-color: rgba(252, 211, 77, 0.65);
}
.fp-tree-row.is-garbled .fp-tree-icon-wrap {
  background: linear-gradient(180deg, rgba(254, 226, 226, 0.7) 0%, rgba(252, 165, 165, 0.5) 100%);
  border-color: rgba(248, 113, 113, 0.6);
}
.fp-tree-icon { flex: 0 0 auto; }
.fp-tree-icon.is-folder { color: #f6b73c; fill: rgba(251, 191, 36, 0.22); }
.fp-tree-icon.is-warn { color: #dc2626; }
.fp-tree-icon.is-archive { color: #6366f1; }
.fp-tree-icon.is-audio { color: #7c3aed; }
.fp-tree-icon.is-text { color: #64748b; }
.fp-tree-icon.is-file { color: #94a3b8; }
.fp-tree-row.is-dir .fp-tree-name { font-weight: 700; color: #1e293b; }
.fp-tree-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  color: rgb(30, 41, 59);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.35;
  text-overflow: ellipsis;
  word-break: break-all;
}
.fp-tree-row.is-garbled .fp-tree-name { color: #b45309; }
.fp-tree-size {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
  min-width: 64px;
  margin-left: 12px;
  color: rgb(148, 163, 184);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.fp-garbled-tag {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #f59e0b, #d97706);
  border-radius: 999px;
  padding: 2px 8px;
  letter-spacing: 0.02em;
  box-shadow: 0 1px 4px rgba(217, 119, 6, 0.32);
}

/* ============================================================
   文件名预览弹窗（Teleport 自绘）
   - 视觉对齐库存页 Library.mediaPreviewDialog：圆角 22 / bg-white/72 / backdrop-blur-2xl
   - 头部 hero gradient + 玻璃 icon；底部 footer 玻璃带
   - 文件树沿用 fp-tree-row（已对齐 TaskDetailPane.task-file-tree）
   ============================================================ */

/* 1. 入场 / 出场过渡：fade + scale，遮罩同步淡入淡出 */
.fp-dlg-fade-enter-active,
.fp-dlg-fade-leave-active { transition: opacity 0.22s ease; }
.fp-dlg-fade-enter-from,
.fp-dlg-fade-leave-to { opacity: 0; }
.fp-dlg-fade-enter-active .fp-dlg-panel,
.fp-dlg-fade-leave-active .fp-dlg-panel { transition: transform 0.26s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease, filter 0.22s ease; }
.fp-dlg-fade-enter-from .fp-dlg-panel,
.fp-dlg-fade-leave-to .fp-dlg-panel { transform: translateY(8px) scale(0.97); opacity: 0; filter: blur(1px); }

/* 2. 标签 chip（hero 区右侧的 "N 项乱码 / 自动反解 N 项"） */
.fp-dlg-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
  letter-spacing: 0.01em;
}
.fp-dlg-tag.is-amber {
  background: linear-gradient(180deg, rgba(254, 243, 199, 0.92) 0%, rgba(253, 230, 138, 0.86) 100%);
  border: 1px solid rgba(252, 211, 77, 0.7);
  color: #92400e;
  box-shadow: 0 1px 3px rgba(217, 119, 6, 0.16);
}
.fp-dlg-tag.is-emerald {
  background: linear-gradient(180deg, rgba(236, 253, 245, 0.92) 0%, rgba(209, 250, 229, 0.88) 100%);
  border: 1px solid rgba(167, 243, 208, 0.9);
  color: #047857;
  box-shadow: 0 1px 3px rgba(5, 150, 105, 0.12);
}

/* 3. Meta chip（body 顶部一排 "编码 / codepage / 密码 / 文件数"） */
.fp-dlg-meta-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 11px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(226, 232, 240, 0.85);
  font-size: 12px;
  color: #334155;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.fp-dlg-meta-chip-label {
  color: rgba(29, 29, 31, 0.54);
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.fp-dlg-meta-chip b {
  color: #0f172a;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

/* 4. 文件树外壳（半透明白卡 + 顶底 fade mask + 内嵌高光） */
.fp-dlg-tree-shell {
  position: relative;
  flex: 1;
  min-height: 200px;
  max-height: 420px;
  overflow: hidden;
  border-radius: 16px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: rgba(255, 255, 255, 0.62);
  box-shadow:
    0 10px 28px rgba(15, 23, 42, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.96);
}
.fp-dlg-tree-shell::before,
.fp-dlg-tree-shell::after {
  position: absolute;
  right: 0;
  left: 0;
  z-index: 2;
  height: 18px;
  pointer-events: none;
  content: '';
}
.fp-dlg-tree-shell::before {
  top: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.86) 0%, rgba(255, 255, 255, 0));
}
.fp-dlg-tree-shell::after {
  bottom: 0;
  background: linear-gradient(0deg, rgba(255, 255, 255, 0.86) 0%, rgba(255, 255, 255, 0));
}
.fp-dlg-tree-scroll {
  height: 100%;
  max-height: 420px;
  overflow: auto;
  padding: 12px;
  scrollbar-width: thin;
  scrollbar-color: rgba(148, 163, 184, 0.65) transparent;
}
.fp-dlg-tree-empty {
  padding: 36px 12px;
  text-align: center;
  color: #94a3b8;
  font-size: 12.5px;
}

/* 5. 滚动条贴 detail-scroll 风格（与 TaskDetailPane 一致） */
.fp-detail-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
.fp-detail-scroll::-webkit-scrollbar-track { background: transparent; }
.fp-detail-scroll::-webkit-scrollbar-thumb {
  border: 2px solid rgba(255, 255, 255, 0.92);
  background: rgba(148, 163, 184, 0.52);
  border-radius: 999px;
}
.fp-detail-scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(100, 116, 139, 0.68);
}

@media (max-width: 1100px) {
  .conflicts-garbled-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

/* 双卡网格 */
.conflicts-detail-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}
@media (min-width: 1280px) {
  .conflicts-detail-grid { grid-template-columns: 1fr 1fr; }
}

/* 信息卡片：纯白 + 极淡黑灰边 */
.conflicts-info-card {
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
  overflow: hidden;
}
.conflicts-info-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  background: #f8fafc;
}
.conflicts-info-card-header h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  letter-spacing: -0.2px;
}
.conflicts-info-card-body {
  flex: 1;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.conflicts-info-section { display: flex; flex-direction: column; gap: 6px; }
.conflicts-info-block {
  padding-top: 12px;
  border-top: 1px solid rgba(15, 23, 42, 0.05);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.conflicts-info-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.conflicts-info-label {
  display: block;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #94a3b8;
  margin-bottom: 4px;
}
.conflicts-info-value {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
  color: #0f172a;
}
.conflicts-info-value-muted {
  margin: 0;
  font-size: 12.5px;
  color: #64748b;
}
.conflicts-info-suggest {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.05);
  font-size: 12.5px;
  color: #475569;
  line-height: 1.6;
}

/* 路径展示框 */
.conflicts-info-path {
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid rgba(15, 23, 42, 0.05);
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
  font-size: 11.5px;
  color: #334155;
  line-height: 1.6;
  word-break: break-all;
  max-height: 96px;
  overflow-y: auto;
}
.conflicts-info-path::-webkit-scrollbar { width: 4px; }
.conflicts-info-path::-webkit-scrollbar-thumb { background: rgba(148, 163, 184, 0.4); border-radius: 4px; }
.conflicts-info-path.is-target {
  background: #e0f2fe;
  border-color: rgba(2, 132, 199, 0.18);
  color: #0c4a6e;
}

/* 元数据 */
.conflicts-info-meta-list { display: flex; flex-direction: column; gap: 6px; }
.conflicts-info-meta-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12.5px;
}
.conflicts-info-meta-key {
  flex-shrink: 0;
  width: 36px;
  color: #94a3b8;
  font-size: 11.5px;
}
.conflicts-info-meta-val { color: #1e293b; flex: 1; }

/* 帮助卡：纯白 */
.conflicts-help-card {
  margin-top: 16px;
  padding: 16px 20px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.06);
}
.conflicts-help-title {
  margin: 0 0 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}
.conflicts-help-list {
  margin: 0;
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;
  color: #475569;
  line-height: 1.7;
}
.conflicts-help-list li::marker { color: #cbd5e1; }
.conflicts-help-list strong { color: #0f172a; font-weight: 600; }

@keyframes conflicts-fade-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ==============================================================
 * 已有动画（处理中 / 重试中）保留
 * ============================================================ */
.processing-conflict-card {
  border-color: rgba(74, 222, 128, 0.72) !important;
  box-shadow:
    0 0 0 1px rgba(74, 222, 128, 0.26),
    0 0 18px rgba(74, 222, 128, 0.18),
    0 0 32px rgba(34, 197, 94, 0.12);
  animation: processing-conflict-glow 1.9s ease-in-out infinite;
}

.processing-conflict-card::after {
  content: "";
  position: absolute;
  inset: -2px;
  border-radius: 14px;
  pointer-events: none;
  box-shadow:
    0 0 0 1px rgba(134, 239, 172, 0.28),
    0 0 22px rgba(74, 222, 128, 0.22),
    0 0 42px rgba(34, 197, 94, 0.18);
  opacity: 0.78;
  animation: processing-conflict-aura 1.9s ease-in-out infinite;
}

.keep-new-conflict-card {
  border-color: rgba(59, 130, 246, 0.78) !important;
  background:
    linear-gradient(100deg, rgba(239, 246, 255, 0.92), rgba(255, 255, 255, 0.98) 42%, rgba(219, 234, 254, 0.78)) !important;
  box-shadow:
    0 0 0 1px rgba(59, 130, 246, 0.26),
    0 0 20px rgba(59, 130, 246, 0.2),
    0 0 38px rgba(37, 99, 235, 0.14) !important;
  animation: keep-new-conflict-glow 1.7s ease-in-out infinite;
}

.keep-new-conflict-card::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(115deg, transparent 0%, rgba(255, 255, 255, 0.9) 44%, transparent 60%);
  transform: translateX(-120%);
  animation: keep-new-card-sheen 1.35s cubic-bezier(0.34, 1.56, 0.64, 1) infinite;
}

.keep-new-conflict-card::after {
  box-shadow:
    0 0 0 1px rgba(147, 197, 253, 0.34),
    0 0 24px rgba(59, 130, 246, 0.25),
    0 0 46px rgba(37, 99, 235, 0.18) !important;
  animation: keep-new-conflict-aura 1.7s ease-in-out infinite;
}

.keep-new-card-orbit {
  position: absolute;
  right: 10px;
  bottom: 10px;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 999px;
  background: rgba(239, 246, 255, 0.96);
  color: #2563eb;
  box-shadow: 0 8px 18px rgba(59, 130, 246, 0.2);
  animation: keep-new-card-float 1.15s ease-in-out infinite;
}

.keep-new-card-orbit svg {
  animation: keep-new-card-pulse 1.2s ease-in-out infinite;
}

.retry-conflict-card {
  border-color: rgba(16, 185, 129, 0.82) !important;
  background:
    linear-gradient(100deg, rgba(236, 253, 245, 0.86), rgba(255, 255, 255, 0.98) 38%, rgba(209, 250, 229, 0.72)) !important;
  cursor: not-allowed !important;
}

.retry-conflict-card:hover {
  transform: none !important;
}

.retry-conflict-card::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(115deg, transparent 0%, rgba(255, 255, 255, 0.85) 42%, transparent 58%);
  transform: translateX(-120%);
  animation: retry-card-sheen 1.45s cubic-bezier(0.34, 1.56, 0.64, 1) infinite;
}

.retry-card-orbit {
  position: absolute;
  right: 10px;
  bottom: 10px;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px solid rgba(16, 185, 129, 0.28);
  border-radius: 999px;
  background: rgba(236, 253, 245, 0.92);
  color: #059669;
  box-shadow: 0 8px 18px rgba(16, 185, 129, 0.18);
  animation: retry-card-float 1.2s ease-in-out infinite;
}

.retry-card-orbit svg {
  animation: retry-card-spin 1s linear infinite;
}

@keyframes processing-conflict-glow {
  0%, 100% {
    box-shadow:
      0 0 0 1px rgba(74, 222, 128, 0.22),
      0 0 14px rgba(74, 222, 128, 0.12),
      0 0 26px rgba(34, 197, 94, 0.08);
  }
  50% {
    box-shadow:
      0 0 0 1px rgba(74, 222, 128, 0.34),
      0 0 24px rgba(74, 222, 128, 0.22),
      0 0 44px rgba(34, 197, 94, 0.16);
  }
}

@keyframes processing-conflict-aura {
  0%, 100% {
    opacity: 0.48;
    transform: scale(0.995);
  }
  50% {
    opacity: 0.92;
    transform: scale(1.01);
  }
}

@keyframes keep-new-conflict-glow {
  0%, 100% {
    box-shadow:
      0 0 0 1px rgba(59, 130, 246, 0.22),
      0 0 16px rgba(59, 130, 246, 0.14),
      0 0 30px rgba(37, 99, 235, 0.1);
  }
  50% {
    box-shadow:
      0 0 0 1px rgba(59, 130, 246, 0.36),
      0 0 28px rgba(59, 130, 246, 0.25),
      0 0 50px rgba(37, 99, 235, 0.18);
  }
}

@keyframes keep-new-conflict-aura {
  0%, 100% {
    opacity: 0.54;
    transform: scale(0.995);
  }
  50% {
    opacity: 0.96;
    transform: scale(1.012);
  }
}

@keyframes keep-new-card-sheen {
  from { transform: translateX(-120%); }
  to { transform: translateX(120%); }
}

@keyframes keep-new-card-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.14); }
}

@keyframes keep-new-card-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-2px); }
}

@keyframes retry-card-sheen {
  from { transform: translateX(-120%); }
  to { transform: translateX(120%); }
}

@keyframes retry-card-spin {
  to { transform: rotate(-360deg); }
}

@keyframes retry-card-float {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-2px) scale(1.06); }
}
</style>

<style>
/* ============================================================
 * 深色模式覆盖（Conflicts.vue 全局 unscoped）
 * ============================================================ */
html.kikoerumanager-dark .conflicts-page .lib-info-strip {
  background: rgba(15, 23, 42, 0.92);
  border-color: rgba(148, 163, 184, 0.16);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
html.kikoerumanager-dark .conflicts-page .lib-info-label,
html.kikoerumanager-dark .conflicts-page .lib-info-meta,
html.kikoerumanager-dark .conflicts-page .lib-info-sub {
  color: #94a3b8;
}
html.kikoerumanager-dark .conflicts-page .lib-info-value {
  color: #cbd5e1;
}
html.kikoerumanager-dark .conflicts-page .lib-info-value b {
  color: #f8fafc;
}
html.kikoerumanager-dark .conflicts-page .lib-info-divider {
  background: linear-gradient(180deg, transparent, rgba(148, 163, 184, 0.14), transparent);
}

html.kikoerumanager-dark .conflicts-refresh-btn {
  background: rgba(30, 41, 59, 0.82);
  border-color: rgba(148, 163, 184, 0.16);
  color: #cbd5e1;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
}
html.kikoerumanager-dark .conflicts-refresh-btn:hover {
  background: rgba(51, 65, 85, 0.92);
  border-color: rgba(148, 163, 184, 0.28);
  color: #f8fafc;
  box-shadow: 0 6px 16px -6px rgba(0, 0, 0, 0.3);
}

html.kikoerumanager-dark .conflicts-error-alert {
  background: rgba(127, 29, 29, 0.25);
  border-color: rgba(239, 68, 68, 0.25);
  color: #fca5a5;
}

html.kikoerumanager-dark .conflicts-empty {
  background: rgba(15, 23, 42, 0.92);
  border-color: rgba(148, 163, 184, 0.16);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

html.kikoerumanager-dark .conflicts-list-pane {
  background: rgba(15, 23, 42, 0.92);
  border-color: rgba(148, 163, 184, 0.16);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
html.kikoerumanager-dark .conflicts-list-header {
  background: rgba(30, 41, 59, 0.55);
  border-color: rgba(148, 163, 184, 0.12);
}
html.kikoerumanager-dark .conflicts-list-title {
  color: #f8fafc;
}
html.kikoerumanager-dark .conflicts-segmented {
  background: rgba(30, 41, 59, 0.6);
  border-color: rgba(148, 163, 184, 0.14);
}
html.kikoerumanager-dark .conflicts-segmented-item {
  color: #94a3b8;
}
html.kikoerumanager-dark .conflicts-segmented-item:hover {
  color: #e2e8f0;
}
html.kikoerumanager-dark .conflicts-segmented-item.is-active {
  background: rgba(51, 65, 85, 0.85);
  color: #f8fafc;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}
html.kikoerumanager-dark .conflicts-mini-btn {
  background: rgba(30, 41, 59, 0.72);
  border-color: rgba(148, 163, 184, 0.16);
  color: #cbd5e1;
}
html.kikoerumanager-dark .conflicts-mini-btn:hover {
  background: rgba(51, 65, 85, 0.82);
  border-color: rgba(148, 163, 184, 0.26);
  color: #f8fafc;
}
html.kikoerumanager-dark .conflicts-mini-btn.is-active {
  background: rgba(37, 99, 235, 0.22);
  border-color: rgba(59, 130, 246, 0.35);
  color: #93c5fd;
}
html.kikoerumanager-dark .conflicts-batch-btn.is-slate {
  background: rgba(30, 41, 59, 0.72);
  color: #cbd5e1;
  border-color: rgba(148, 163, 184, 0.18);
}
html.kikoerumanager-dark .conflicts-batch-btn.is-slate:hover {
  background: rgba(51, 65, 85, 0.82);
  color: #f8fafc;
  border-color: rgba(148, 163, 184, 0.28);
}
html.kikoerumanager-dark .conflicts-list-hint {
  color: #64748b;
}

html.kikoerumanager-dark .conflicts-list-card:hover {
  background: rgba(51, 65, 85, 0.35);
  border-color: rgba(148, 163, 184, 0.14);
}
html.kikoerumanager-dark .conflicts-list-card.is-selected {
  background: rgba(51, 65, 85, 0.55);
  border-color: rgba(148, 163, 184, 0.22);
}
html.kikoerumanager-dark .conflicts-list-card.is-active {
  background: rgba(59, 130, 246, 0.14);
  border-color: rgba(59, 130, 246, 0.28);
}
html.kikoerumanager-dark .conflicts-list-card.is-active .conflicts-list-card-title {
  color: #f8fafc;
}
html.kikoerumanager-dark .conflicts-list-card-title {
  color: #e2e8f0;
}
html.kikoerumanager-dark .conflicts-list-card-type {
  color: #94a3b8;
}
html.kikoerumanager-dark .conflicts-list-card-date {
  color: #64748b;
}
html.kikoerumanager-dark .conflicts-list-progress-track {
  background: rgba(30, 41, 59, 0.6);
}
html.kikoerumanager-dark .conflicts-list-progress-num {
  color: #34d399;
}

html.kikoerumanager-dark .conflicts-detail-pane {
  background: rgba(15, 23, 42, 0.92);
  border-color: rgba(148, 163, 184, 0.16);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.04);
}
html.kikoerumanager-dark .conflicts-detail-header {
  background: rgba(30, 41, 59, 0.72);
  border-color: rgba(148, 163, 184, 0.12);
}
html.kikoerumanager-dark .conflicts-detail-bg-glyph {
  color: #475569;
  opacity: 0.06;
}
html.kikoerumanager-dark .conflicts-detail-title {
  color: #f8fafc;
}
html.kikoerumanager-dark .conflicts-detail-subtitle {
  color: #94a3b8;
}

html.kikoerumanager-dark .conflicts-action-btn.is-slate {
  background: rgba(30, 41, 59, 0.72);
  color: #cbd5e1;
  border-color: rgba(148, 163, 184, 0.18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 1px 2px rgba(0, 0, 0, 0.1);
}
html.kikoerumanager-dark .conflicts-action-btn.is-slate:hover {
  background: rgba(51, 65, 85, 0.85);
  color: #f8fafc;
  border-color: rgba(148, 163, 184, 0.28);
  box-shadow: 0 4px 14px -4px rgba(0, 0, 0, 0.25);
}

html.kikoerumanager-dark .conflicts-detail-alert.is-warning {
  background: rgba(146, 64, 14, 0.18);
  border-color: rgba(245, 158, 11, 0.25);
  color: #fcd34d;
}
html.kikoerumanager-dark .conflicts-detail-alert.is-danger {
  background: rgba(127, 29, 29, 0.18);
  border-color: rgba(239, 68, 68, 0.22);
  color: #fca5a5;
}

html.kikoerumanager-dark .conflicts-garbled-card {
  background: rgba(15, 23, 42, 0.72);
  border-color: rgba(245, 158, 11, 0.25);
  box-shadow: 0 12px 28px -22px rgba(217, 119, 6, 0.25);
}
html.kikoerumanager-dark .conflicts-garbled-head h4 {
  color: #f8fafc;
}
html.kikoerumanager-dark .conflicts-garbled-head p {
  color: #94a3b8;
}
html.kikoerumanager-dark .conflicts-garbled-toolbar {
  background: rgba(30, 41, 59, 0.6);
  border-color: rgba(148, 163, 184, 0.12);
}
html.kikoerumanager-dark .conflicts-garbled-select > span {
  color: #94a3b8;
}
html.kikoerumanager-dark .conflicts-garbled-preview-btn {
  background: rgba(30, 41, 59, 0.72);
  border-color: rgba(148, 163, 184, 0.16);
  color: #e2e8f0;
}
html.kikoerumanager-dark .conflicts-garbled-preview-btn:hover {
  border-color: rgba(148, 163, 184, 0.28);
  box-shadow: 0 8px 18px -12px rgba(0, 0, 0, 0.35);
}
html.kikoerumanager-dark .conflicts-garbled-grid div {
  background: rgba(30, 41, 59, 0.55);
  border-color: rgba(148, 163, 184, 0.12);
}
html.kikoerumanager-dark .conflicts-garbled-grid span {
  color: #64748b;
}
html.kikoerumanager-dark .conflicts-garbled-grid b {
  color: #e2e8f0;
}
html.kikoerumanager-dark .conflicts-garbled-samples {
  background: rgba(30, 41, 59, 0.4);
  border-color: rgba(148, 163, 184, 0.12);
}
html.kikoerumanager-dark .conflicts-garbled-row {
  border-color: rgba(148, 163, 184, 0.1);
}
html.kikoerumanager-dark .conflicts-garbled-row span {
  color: #cbd5e1;
}
html.kikoerumanager-dark .conflicts-garbled-row b {
  color: #fbbf24;
}

html.kikoerumanager-dark .conflicts-filename-preview {
  background: rgba(15, 23, 42, 0.72);
  border-color: rgba(148, 163, 184, 0.14);
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.15);
}
html.kikoerumanager-dark .conflicts-filename-preview-head {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.92) 0%, rgba(30, 41, 59, 0.72) 100%);
  border-color: rgba(148, 163, 184, 0.1);
  color: #94a3b8;
}
html.kikoerumanager-dark .conflicts-filename-preview-head b {
  color: #f8fafc;
}
html.kikoerumanager-dark .fp-repaired-badge {
  background: linear-gradient(180deg, rgba(6, 78, 59, 0.45) 0%, rgba(5, 150, 105, 0.35) 100%);
  border-color: rgba(52, 211, 153, 0.3);
  color: #6ee7b7;
}

html.kikoerumanager-dark .conflicts-info-card {
  background: rgba(15, 23, 42, 0.72);
  border-color: rgba(148, 163, 184, 0.14);
}
html.kikoerumanager-dark .conflicts-info-card-header {
  background: rgba(30, 41, 59, 0.55);
  border-color: rgba(148, 163, 184, 0.1);
}
html.kikoerumanager-dark .conflicts-info-card-header h3 {
  color: #e2e8f0;
}
html.kikoerumanager-dark .conflicts-info-label {
  color: #64748b;
}
html.kikoerumanager-dark .conflicts-info-value {
  color: #f8fafc;
}
html.kikoerumanager-dark .conflicts-info-value-muted {
  color: #94a3b8;
}
html.kikoerumanager-dark .conflicts-info-suggest {
  background: rgba(30, 41, 59, 0.55);
  border-color: rgba(148, 163, 184, 0.1);
  color: #cbd5e1;
}
html.kikoerumanager-dark .conflicts-info-path {
  background: rgba(30, 41, 59, 0.55);
  border-color: rgba(148, 163, 184, 0.1);
  color: #cbd5e1;
}
html.kikoerumanager-dark .conflicts-info-path.is-target {
  background: rgba(12, 74, 110, 0.25);
  border-color: rgba(56, 189, 248, 0.2);
  color: #7dd3fc;
}
html.kikoerumanager-dark .conflicts-info-meta-key {
  color: #64748b;
}
html.kikoerumanager-dark .conflicts-info-meta-val {
  color: #e2e8f0;
}

html.kikoerumanager-dark .conflicts-help-card {
  background: rgba(15, 23, 42, 0.72);
  border-color: rgba(148, 163, 184, 0.14);
}
html.kikoerumanager-dark .conflicts-help-title {
  color: #e2e8f0;
}
html.kikoerumanager-dark .conflicts-help-list {
  color: #94a3b8;
}
html.kikoerumanager-dark .conflicts-help-list strong {
  color: #f8fafc;
}
html.kikoerumanager-dark .conflicts-help-list li::marker {
  color: #475569;
}

/* 文件名预览弹窗 */
html.kikoerumanager-dark .fp-dlg-panel {
  background: rgba(15, 23, 42, 0.92) !important;
  border-color: rgba(148, 163, 184, 0.2) !important;
  box-shadow: 0 22px 70px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}
html.kikoerumanager-dark .fp-dlg-panel header {
  background: linear-gradient(180deg, rgba(30, 41, 59, 0.85) 0%, rgba(30, 41, 59, 0.6) 100%) !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
}
html.kikoerumanager-dark .fp-dlg-panel footer {
  background: rgba(30, 41, 59, 0.55) !important;
  border-color: rgba(148, 163, 184, 0.14) !important;
}
html.kikoerumanager-dark .fp-dlg-panel #fp-dlg-title {
  color: #f8fafc !important;
}
html.kikoerumanager-dark .fp-dlg-panel header p {
  color: #94a3b8 !important;
}
html.kikoerumanager-dark .fp-dlg-tree-shell {
  background: rgba(15, 23, 42, 0.55);
  border-color: rgba(148, 163, 184, 0.14);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.03);
}
html.kikoerumanager-dark .fp-dlg-tree-shell::before {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.75) 0%, rgba(15, 23, 42, 0));
}
html.kikoerumanager-dark .fp-dlg-tree-shell::after {
  background: linear-gradient(0deg, rgba(15, 23, 42, 0.75) 0%, rgba(15, 23, 42, 0));
}
html.kikoerumanager-dark .fp-dlg-tree-empty {
  color: #64748b;
}
html.kikoerumanager-dark .fp-dlg-meta-chip {
  background: rgba(30, 41, 59, 0.6);
  border-color: rgba(148, 163, 184, 0.14);
  color: #cbd5e1;
}
html.kikoerumanager-dark .fp-dlg-meta-chip-label {
  color: rgba(148, 163, 184, 0.7);
}
html.kikoerumanager-dark .fp-dlg-meta-chip b {
  color: #f8fafc;
}

/* 文件树 */
html.kikoerumanager-dark .fp-tree-row {
  color: #cbd5e1;
}
html.kikoerumanager-dark .fp-tree-row:hover {
  background: rgba(51, 65, 85, 0.45);
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.14);
}
html.kikoerumanager-dark .fp-tree-icon-wrap {
  background: rgba(30, 41, 59, 0.6);
  border-color: rgba(148, 163, 184, 0.14);
}
html.kikoerumanager-dark .fp-tree-row:hover .fp-tree-icon-wrap {
  background: rgba(51, 65, 85, 0.7);
  border-color: rgba(148, 163, 184, 0.22);
}
html.kikoerumanager-dark .fp-tree-name {
  color: #e2e8f0;
}
html.kikoerumanager-dark .fp-tree-row.is-dir .fp-tree-name {
  color: #f8fafc;
}
html.kikoerumanager-dark .fp-tree-size {
  color: #64748b;
}

html.kikoerumanager-dark .conflicts-detail-placeholder-inner p {
  color: #94a3b8;
}

/* 处理中 / 重试中 卡片深色适配 */
html.kikoerumanager-dark .keep-new-conflict-card {
  background: linear-gradient(100deg, rgba(30, 58, 138, 0.35), rgba(15, 23, 42, 0.55) 42%, rgba(37, 99, 235, 0.25)) !important;
}
html.kikoerumanager-dark .retry-conflict-card {
  background: linear-gradient(100deg, rgba(6, 78, 59, 0.3), rgba(15, 23, 42, 0.5) 38%, rgba(5, 150, 105, 0.22)) !important;
}
html.kikoerumanager-dark .keep-new-card-orbit {
  background: rgba(30, 58, 138, 0.55);
  border-color: rgba(59, 130, 246, 0.35);
  color: #93c5fd;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.2);
}
html.kikoerumanager-dark .retry-card-orbit {
  background: rgba(6, 78, 59, 0.5);
  border-color: rgba(16, 185, 129, 0.3);
  color: #34d399;
  box-shadow: 0 8px 18px rgba(16, 185, 129, 0.18);
}
</style>
