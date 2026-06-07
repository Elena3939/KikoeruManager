<template>
  <div class="existing-page">
    <AppPageHeader
      :icon="FolderInput"
      icon-color="var(--km-nav-folders-icon)"
      title="已有文件夹"
      subtitle="把已解压的 RJ 文件夹放入已有目录，支持社团分层识别、抓取元数据、重命名并按分类规则入库"
    >
      <div class="hero-search-wrap">
        <Search :size="13" class="hero-search-icon" />
        <input v-model="searchQuery" class="hero-search-input" type="text" placeholder="搜索文件夹名、路径或 RJ 号" />
      </div>
      <StatefulButton
        class="ef-head-btn primary btn-refresh"
        unstyled
        :show-default-icons="false"
        :disabled="loading"
        :success-hold="900"
        @click="refreshWithCache"
      >
        <template #prefix="{ state }">
          <span class="ef-head-btn-icon-wrap ef-stateful-icon" :class="`is-${state}`" aria-hidden="true">
            <Loader2 v-if="state === 'loading' || loading" :size="13" :stroke-width="2.6" class="ef-head-state-icon animate-spin" />
            <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.6" class="ef-head-state-icon" />
            <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.6" class="ef-head-state-icon" />
            <RefreshCw v-else :size="13" :stroke-width="2.6" class="ef-head-state-icon ef-head-btn-icon" />
          </span>
        </template>
        <span class="ef-head-btn-label">{{ loading ? '刷新中…' : '刷新列表' }}</span>
      </StatefulButton>
      <StatefulButton
        class="ef-head-btn ghost btn-rescan"
        unstyled
        :show-default-icons="false"
        :disabled="loading"
        :success-hold="900"
        @click="refreshForce"
      >
        <template #prefix="{ state }">
          <span class="ef-head-btn-icon-wrap ef-stateful-icon" :class="`is-${state}`" aria-hidden="true">
            <Loader2 v-if="state === 'loading'" :size="13" :stroke-width="2.6" class="ef-head-state-icon animate-spin" />
            <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.6" class="ef-head-state-icon" />
            <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.6" class="ef-head-state-icon" />
            <RotateCcw v-else :size="13" :stroke-width="2.6" class="ef-head-state-icon ef-head-btn-icon" />
          </span>
        </template>
        <span class="ef-head-btn-label">重新抓取</span>
      </StatefulButton>
    </AppPageHeader>

    <section class="existing-shell">
      <aside class="existing-sidebar">
        <div class="sidebar-card">
          <div class="strategy-hero">
            <div class="strategy-hero-main">
              <div class="strategy-eyebrow">
                <span class="strategy-eyebrow-icon"><FolderTree :size="16" :stroke-width="2.4" /></span>
                <span>处理策略</span>
              </div>
              <div class="sidebar-title">入库流水线</div>
            </div>
            <div class="strategy-score">
              <span class="strategy-score-value">{{ readyCount }}</span>
              <span class="strategy-score-label">可处理</span>
            </div>
          </div>

          <div class="strategy-meter" :style="{ '--ready-percent': `${readyRatio}%` }">
            <div class="strategy-meter-track"><span></span></div>
            <div class="strategy-meter-meta">
              <span>{{ readyRatio }}%</span>
              <span>{{ selectedFolders.length }} 已选</span>
            </div>
          </div>

          <div class="strategy-stats">
            <div class="strategy-stat">
              <span>总数</span>
              <strong>{{ folders.length }}</strong>
            </div>
            <div class="strategy-stat">
              <span>冲突</span>
              <strong>{{ conflictCount }}</strong>
            </div>
            <div class="strategy-stat">
              <span>可查重</span>
              <strong>{{ checkableCount }}</strong>
            </div>
          </div>

          <div class="pipeline-list" aria-label="处理流水线">
            <div v-for="(step, index) in pipelineSteps" :key="step.label" class="pipeline-item">
              <div class="pipeline-rail">
                <div class="pipeline-dot" :class="step.tone"><component :is="step.icon" :size="16" :stroke-width="2.35" /></div>
              </div>
              <div class="pipeline-copy">
                <div class="pipeline-title-row">
                  <span class="pipeline-title">{{ step.label }}</span>
                  <span class="pipeline-index">0{{ index + 1 }}</span>
                </div>
                <div class="pipeline-desc">{{ step.desc }}</div>
              </div>
            </div>
          </div>

          <div class="strategy-section-head">
            <span>执行选项</span>
            <span>{{ autoClassify && checkDuplicates ? '双策略' : '自定义' }}</span>
          </div>

          <div class="option-stack">
            <button
              type="button"
              class="option-row"
              :class="{ checked: autoClassify }"
              role="switch"
              :aria-checked="autoClassify"
              aria-label="自动分类入库"
              @click="autoClassify = !autoClassify"
            >
              <div class="option-row-main">
                <span class="option-icon classify"><MoveRight :size="16" :stroke-width="2.35" /></span>
                <div>
                  <div class="option-row-title">自动分类入库</div>
                  <div class="option-row-desc">处理完成后移动到库存分类目录</div>
                </div>
              </div>
              <span class="option-state">{{ autoClassify ? '开' : '关' }}</span>
              <span class="ef-switch" :class="{ checked: autoClassify }" aria-hidden="true">
                <span class="ef-switch-thumb"></span>
              </span>
            </button>
            <button
              type="button"
              class="option-row"
              :class="{ checked: checkDuplicates }"
              role="switch"
              :aria-checked="checkDuplicates"
              aria-label="扫描时查重"
              @click="checkDuplicates = !checkDuplicates"
            >
              <div class="option-row-main">
                <span class="option-icon duplicate"><ShieldCheck :size="16" :stroke-width="2.35" /></span>
                <div>
                  <div class="option-row-title">扫描时查重</div>
                  <div class="option-row-desc">刷新列表时检查重复与关联作品</div>
                </div>
              </div>
              <span class="option-state">{{ checkDuplicates ? '开' : '关' }}</span>
              <span class="ef-switch" :class="{ checked: checkDuplicates }" aria-hidden="true">
                <span class="ef-switch-thumb"></span>
              </span>
            </button>
          </div>

          <div class="sidebar-actions">
            <div class="action-summary">
              <span>已选 {{ selectedFolders.length }}</span>
              <span>可入库 {{ allProcessableFolders.length }}</span>
            </div>
            <StatefulButton
              class="side-ep-action primary"
              unstyled
              :show-default-icons="false"
              :success-hold="900"
              :disabled="selectedProcessableFolders.length === 0 || processing"
              @click="handleProcessSelected"
            >
              <template #prefix="{ state }">
                <span class="side-button-icon-wrap" :class="`is-${state}`" aria-hidden="true">
                  <Loader2 v-if="state === 'loading' || processing" :size="13" :stroke-width="2.5" class="side-button-icon animate-spin" />
                  <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.5" class="side-button-icon" />
                  <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.5" class="side-button-icon" />
                  <Play v-else :size="13" :stroke-width="2.5" class="side-button-icon" />
                </span>
              </template>
              <span class="side-action-label">入库选中</span>
              <span v-if="selectedProcessableFolders.length" class="side-action-count">{{ selectedProcessableFolders.length }}</span>
            </StatefulButton>
            <StatefulButton
              class="side-ep-action accent"
              unstyled
              :show-default-icons="false"
              :success-hold="900"
              :disabled="allProcessableFolders.length === 0 || processing"
              @click="handleProcessAll"
            >
              <template #prefix="{ state }">
                <span class="side-button-icon-wrap" :class="`is-${state}`" aria-hidden="true">
                  <Loader2 v-if="state === 'loading' || processing" :size="13" :stroke-width="2.5" class="side-button-icon animate-spin" />
                  <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.5" class="side-button-icon" />
                  <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.5" class="side-button-icon" />
                  <MoveRight v-else :size="13" :stroke-width="2.5" class="side-button-icon" />
                </span>
              </template>
              <span class="side-action-label">入库全部可处理</span>
              <span v-if="allProcessableFolders.length" class="side-action-count">{{ allProcessableFolders.length }}</span>
            </StatefulButton>
            <StatefulButton
              class="side-ep-action"
              unstyled
              :show-default-icons="false"
              :success-hold="900"
              :disabled="selectedCheckableFolders.length === 0 || checkingDuplicates"
              @click="checkSelectedDuplicates"
            >
              <template #prefix="{ state }">
                <span class="side-button-icon-wrap" :class="`is-${state}`" aria-hidden="true">
                  <Loader2 v-if="state === 'loading' || checkingDuplicates" :size="13" :stroke-width="2.5" class="side-button-icon animate-spin" />
                  <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.5" class="side-button-icon" />
                  <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.5" class="side-button-icon" />
                  <SearchCheck v-else :size="13" :stroke-width="2.5" class="side-button-icon" />
                </span>
              </template>
              <span class="side-action-label">检查选中项</span>
              <span v-if="selectedCheckableFolders.length" class="side-action-count">{{ selectedCheckableFolders.length }}</span>
            </StatefulButton>
          </div>
        </div>
      </aside>

      <main class="existing-main">
        <!-- 顶部状态条：4 列指标（lib-info-strip 风格，对齐其他页面） -->
        <section class="ef-info-strip">
          <div class="ef-info-item">
            <Folder :size="15" :stroke-width="2.2" class="ef-info-icon ef-info-icon-blue" />
            <div class="ef-info-body">
              <div class="ef-info-label">总数</div>
              <div class="ef-info-value">
                <Transition name="ef-num-flip" mode="out-in">
                  <b :key="String(folders.length)">{{ folders.length }}</b>
                </Transition>
                <span class="ef-info-meta">个文件夹</span>
              </div>
            </div>
          </div>
          <div class="ef-info-divider"></div>
          <div class="ef-info-item">
            <CheckCircle2 :size="15" :stroke-width="2.2" class="ef-info-icon ef-info-icon-emerald" />
            <div class="ef-info-body">
              <div class="ef-info-label">可处理</div>
              <div class="ef-info-value">
                <Transition name="ef-num-flip" mode="out-in">
                  <b :key="String(readyCount)">{{ readyCount }}</b>
                </Transition>
                <span class="ef-info-meta">个就绪</span>
              </div>
            </div>
          </div>
          <div class="ef-info-divider"></div>
          <div class="ef-info-item">
            <AlertTriangle :size="15" :stroke-width="2.2" class="ef-info-icon ef-info-icon-amber" />
            <div class="ef-info-body">
              <div class="ef-info-label">冲突</div>
              <div class="ef-info-value">
                <Transition name="ef-num-flip" mode="out-in">
                  <b :key="String(conflictCount)">{{ conflictCount }}</b>
                </Transition>
                <span class="ef-info-meta">个待解决</span>
              </div>
            </div>
          </div>
          <div class="ef-info-divider"></div>
          <div class="ef-info-item">
            <Hash :size="15" :stroke-width="2.2" class="ef-info-icon ef-info-icon-slate" />
            <div class="ef-info-body">
              <div class="ef-info-label">已选</div>
              <div class="ef-info-value">
                <Transition name="ef-num-flip" mode="out-in">
                  <b :key="String(selectedFolders.length)">{{ selectedFolders.length }}</b>
                </Transition>
                <span class="ef-info-meta">个已选项</span>
              </div>
            </div>
          </div>
        </section>

        <section ref="folderViewportHostRef" class="folders-card">
          <Transition name="ef-section">
            <div v-if="loading" class="scan-banner">
              <AppLoadingAnimation variant="inline" :size="34" />
              <div>
                <div class="scan-title">正在扫描文件夹</div>
                <div class="scan-desc">已发现 {{ folders.length }} 个目录，查重结果会分批更新</div>
              </div>
            </div>
          </Transition>

          <div v-if="filteredFolders.length" class="folder-bulkbar">
            <div class="folder-bulkbar-copy">
              <strong>{{ allProcessableFolders.length }}</strong>
              <span>个目录可直接入库，冲突项会留在列表里单独处理</span>
            </div>
            <div class="folder-bulkbar-actions">
              <button type="button" class="bulk-action" :disabled="allProcessableFolders.length === 0" @click="selectAllProcessableFolders">
                <Check :size="13" /> 选择可入库
              </button>
              <button type="button" class="bulk-action" :disabled="selectedFolders.length === 0" @click="clearSelectedFolders">
                <XCircle :size="13" /> 清空
              </button>
              <StatefulButton
                class="bulk-action primary"
                unstyled
                :show-default-icons="false"
                :success-hold="900"
                :disabled="allProcessableFolders.length === 0 || processing"
                @click="handleProcessAll"
              >
                <template #prefix="{ state }">
                  <Loader2 v-if="state === 'loading' || processing" :size="13" :stroke-width="2.5" class="bulk-action-icon animate-spin" />
                  <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.5" class="bulk-action-icon" />
                  <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.5" class="bulk-action-icon" />
                  <MoveRight v-else :size="13" :stroke-width="2.5" class="bulk-action-icon" />
                </template>
                全部入库
              </StatefulButton>
            </div>
          </div>

          <div v-if="useVirtualFolders" ref="folderVirtualScrollRef" class="folder-virtual-scroll">
            <div class="folder-virtual-canvas" :style="folderVirtualCanvasStyle">
              <div
                v-for="virtualRow in folderVirtualRows"
                :key="virtualRow.key"
                class="folder-virtual-row"
                :style="{
                  transform: `translateY(${virtualRow.start}px)`,
                  gridTemplateColumns: folderVirtualGridTemplateColumns
                }"
              >
                <article
                  v-for="folder in getVirtualFolderRowItems(virtualRow.index)"
                  :key="folder.path"
                  class="folder-card"
                  :class="{ selected: isSelected(folder), conflict: isConflict(folder), unrecognized: isUnrecognized(folder) }"
                >
                  <div class="folder-card-head">
                    <button
                      type="button"
                      class="select-toggle"
                      :class="{ active: isSelected(folder) }"
                      :disabled="!canSelectFolder(folder)"
                      :aria-label="isSelected(folder) ? '取消选择' : '选择文件夹'"
                      @click="toggleFolderSelection(folder)"
                    >
                      <Check :size="13" />
                    </button>
                    <div class="folder-main-info">
                      <div class="folder-name-row">
                        <div class="folder-name" :title="folder.name">{{ folder.name }}</div>
                        <span v-if="folder.is_nested" class="folder-depth-chip">社团分层</span>
                      </div>
                      <div class="folder-path" :title="folder.path">{{ getFolderDisplayPath(folder) }}</div>
                      <div v-if="folder.is_nested" class="folder-root" :title="folder.path">
                        源目录：{{ folder.source_root_name || '上级目录' }}
                      </div>
                    </div>
                    <span class="status-pill" :class="getFolderState(folder).tone">
                      <AlertTriangle v-if="getFolderState(folder).icon === 'alert'" :size="11" />
                      <RefreshCw v-else-if="getFolderState(folder).icon === 'refresh'" :size="11" class="animate-spin" />
                      <Clock3 v-else-if="getFolderState(folder).icon === 'clock'" :size="11" />
                      <XCircle v-else-if="getFolderState(folder).icon === 'x'" :size="11" />
                      <ShieldCheck v-else-if="getFolderState(folder).icon === 'shield'" :size="11" />
                      <CheckCircle2 v-else :size="11" />
                      {{ getFolderState(folder).label }}
                    </span>
                  </div>

                  <div class="folder-meta-row">
                    <span class="folder-meta rj" :class="{ missing: isUnrecognized(folder) }"><Hash :size="11" /> {{ folder.rjcode || '未识别 RJ' }}</span>
                    <span v-if="folder.is_nested" class="folder-meta route"><FolderTree :size="11" /> {{ folder.relative_path }}</span>
                    <span class="folder-meta"><HardDrive :size="11" /> 大小 {{ formatFileSize(folder.folder_size || folder.size) }}</span>
                    <span class="folder-meta"><Clock3 :size="11" /> 修改 {{ formatDate(folder.modified_time) }}</span>
                  </div>

                  <Transition name="ef-section">
                    <div v-if="isConflict(folder)" class="conflict-box">
                      <AlertTriangle :size="14" />
                      <div>
                        <div class="conflict-title">{{ getConflictTypeLabel(folder.duplicate_info?.conflict_type) }}</div>
                        <div class="conflict-desc">库中已有相同或关联作品，请查看冲突后选择处理方案</div>
                      </div>
                    </div>
                  </Transition>

                  <div class="folder-actions">
                    <button v-if="isConflict(folder)" type="button" class="card-action warning" @click="showDuplicateDetail(folder)">
                      <Eye :size="13" /> 查看冲突
                    </button>
                    <StatefulButton
                      v-else
                      class="card-action primary"
                      unstyled
                      :show-default-icons="false"
                      :success-hold="900"
                      :disabled="processing || !isProcessable(folder)"
                      @click="handleProcessSingle(folder)"
                    >
                      <template #prefix="{ state }">
                        <Loader2 v-if="state === 'loading'" :size="13" :stroke-width="2.5" class="card-action-icon animate-spin" />
                        <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.5" class="card-action-icon" />
                        <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.5" class="card-action-icon" />
                      <Play v-else :size="13" :stroke-width="2.5" class="card-action-icon" />
                    </template>
                      {{ getProcessButtonLabel(folder) }}
                    </StatefulButton>
                    <StatefulButton
                      class="card-action"
                      unstyled
                      :show-default-icons="false"
                      :success-hold="900"
                      :disabled="checkingDuplicates || !isCheckable(folder)"
                      @click="handleRefreshFolder(folder)"
                    >
                      <template #prefix="{ state }">
                        <Loader2 v-if="state === 'loading' || folder.status === 'checking'" :size="13" :stroke-width="2.5" class="card-action-icon animate-spin" />
                        <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.5" class="card-action-icon" />
                        <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.5" class="card-action-icon" />
                        <RefreshCw v-else :size="13" :stroke-width="2.5" class="card-action-icon" />
                      </template>
                      查重
                    </StatefulButton>
                    <button type="button" class="card-action danger" @click="handleDeleteFolder(folder)">
                      <Trash2 :size="13" /> 删除
                    </button>
                  </div>
                </article>
              </div>
            </div>
          </div>

          <TransitionGroup
            v-else-if="filteredFolders.length"
            tag="div"
            name="ef-grid"
            class="folder-grid"
          >
            <article
              v-for="(folder, idx) in filteredFolders"
              :key="folder.path"
              class="folder-card"
              :class="{ selected: isSelected(folder), conflict: isConflict(folder), unrecognized: isUnrecognized(folder) }"
              :style="{ '--ef-grid-delay': `${Math.min(idx, 14) * 30}ms` }"
            >
              <div class="folder-card-head">
                <button
                  type="button"
                  class="select-toggle"
                  :class="{ active: isSelected(folder) }"
                  :disabled="!canSelectFolder(folder)"
                  :aria-label="isSelected(folder) ? '取消选择' : '选择文件夹'"
                  @click="toggleFolderSelection(folder)"
                >
                  <Check :size="13" />
                </button>
                <div class="folder-main-info">
                  <div class="folder-name-row">
                    <div class="folder-name" :title="folder.name">{{ folder.name }}</div>
                    <span v-if="folder.is_nested" class="folder-depth-chip">社团分层</span>
                  </div>
                  <div class="folder-path" :title="folder.path">{{ getFolderDisplayPath(folder) }}</div>
                  <div v-if="folder.is_nested" class="folder-root" :title="folder.path">
                    源目录：{{ folder.source_root_name || '上级目录' }}
                  </div>
                </div>
                <span class="status-pill" :class="getFolderState(folder).tone">
                  <AlertTriangle v-if="getFolderState(folder).icon === 'alert'" :size="11" />
                  <RefreshCw v-else-if="getFolderState(folder).icon === 'refresh'" :size="11" class="animate-spin" />
                  <Clock3 v-else-if="getFolderState(folder).icon === 'clock'" :size="11" />
                  <XCircle v-else-if="getFolderState(folder).icon === 'x'" :size="11" />
                  <ShieldCheck v-else-if="getFolderState(folder).icon === 'shield'" :size="11" />
                  <CheckCircle2 v-else :size="11" />
                  {{ getFolderState(folder).label }}
                </span>
              </div>

              <div class="folder-meta-row">
                <span class="folder-meta rj" :class="{ missing: isUnrecognized(folder) }"><Hash :size="11" /> {{ folder.rjcode || '未识别 RJ' }}</span>
                <span v-if="folder.is_nested" class="folder-meta route"><FolderTree :size="11" /> {{ folder.relative_path }}</span>
                <span class="folder-meta"><HardDrive :size="11" /> 大小 {{ formatFileSize(folder.folder_size || folder.size) }}</span>
                <span class="folder-meta"><Clock3 :size="11" /> 修改 {{ formatDate(folder.modified_time) }}</span>
              </div>

              <Transition name="ef-section">
                <div v-if="isConflict(folder)" class="conflict-box">
                  <AlertTriangle :size="14" />
                  <div>
                    <div class="conflict-title">{{ getConflictTypeLabel(folder.duplicate_info?.conflict_type) }}</div>
                    <div class="conflict-desc">库中已有相同或关联作品，请查看冲突后选择处理方案</div>
                  </div>
                </div>
              </Transition>

              <div class="folder-actions">
                <button v-if="isConflict(folder)" type="button" class="card-action warning" @click="showDuplicateDetail(folder)">
                  <Eye :size="13" /> 查看冲突
                </button>
                <StatefulButton
                  v-else
                  class="card-action primary"
                  unstyled
                  :show-default-icons="false"
                  :success-hold="900"
                  :disabled="processing || !isProcessable(folder)"
                  @click="handleProcessSingle(folder)"
                >
                  <template #prefix="{ state }">
                    <Loader2 v-if="state === 'loading'" :size="13" :stroke-width="2.5" class="card-action-icon animate-spin" />
                    <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.5" class="card-action-icon" />
                    <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.5" class="card-action-icon" />
                  <Play v-else :size="13" :stroke-width="2.5" class="card-action-icon" />
                </template>
                  {{ getProcessButtonLabel(folder) }}
                </StatefulButton>
                <StatefulButton
                  class="card-action"
                  unstyled
                  :show-default-icons="false"
                  :success-hold="900"
                  :disabled="checkingDuplicates || !isCheckable(folder)"
                  @click="handleRefreshFolder(folder)"
                >
                  <template #prefix="{ state }">
                    <Loader2 v-if="state === 'loading' || folder.status === 'checking'" :size="13" :stroke-width="2.5" class="card-action-icon animate-spin" />
                    <Check v-else-if="state === 'success'" :size="13" :stroke-width="2.5" class="card-action-icon" />
                    <XCircle v-else-if="state === 'error'" :size="13" :stroke-width="2.5" class="card-action-icon" />
                    <RefreshCw v-else :size="13" :stroke-width="2.5" class="card-action-icon" />
                  </template>
                  查重
                </StatefulButton>
                <button type="button" class="card-action danger" @click="handleDeleteFolder(folder)">
                  <Trash2 :size="13" /> 删除
                </button>
              </div>
            </article>
          </TransitionGroup>

          <AppEmptyState v-else :description="loading ? '正在读取已有文件夹目录' : '暂无可处理文件夹，请把 RJ 文件夹放入已存在文件夹目录后刷新'" />
        </section>
      </main>
    </section>

    <Teleport to="body">
      <Transition name="ef-result-dialog">
        <div v-if="resultDialogVisible" class="ef-result-overlay" role="presentation" @click.self="closeResultDialog">
          <section class="ef-result-dialog" role="dialog" aria-modal="true" aria-labelledby="ef-result-title">
            <header class="ef-result-header">
              <div class="dialog-title-wrap">
                <div class="dialog-icon" :class="resultData.success ? 'success' : 'warning'">
                  <CheckCircle2 v-if="resultData.success" :size="18" />
                  <AlertTriangle v-else :size="18" />
                </div>
                <div>
                  <div id="ef-result-title" class="dialog-title">任务创建结果</div>
                  <div class="dialog-subtitle">{{ resultData.success ? '任务已进入队列，可在任务中心查看进度' : '请检查错误信息后重试' }}</div>
                </div>
              </div>
              <button type="button" class="dialog-close" title="关闭" @click="closeResultDialog">
                <XCircle :size="18" />
              </button>
            </header>

            <div class="ef-result-body">
              <div class="result-panel" :class="resultData.success ? 'success' : 'warning'">
                <div class="result-title">{{ resultData.success ? '已创建处理任务' : '创建失败' }}</div>
                <div class="result-message">{{ resultData.message }}</div>
              </div>

              <div v-if="resultData.tasks?.length" class="task-list">
                <div class="task-list-title">任务明细</div>
                <div class="task-list-scroll">
                  <div v-for="task in resultData.tasks" :key="task.task_id" class="task-row">
                    <span class="task-id">{{ task.task_id.substring(0, 8) }}</span>
                    <span class="task-path">{{ getFolderName(task.folder_path) }}</span>
                    <span class="task-status">已排队</span>
                  </div>
                </div>
              </div>
            </div>

            <footer class="dialog-footer ef-result-footer">
              <button type="button" class="dialog-ep-btn" @click="closeResultDialog">关闭</button>
              <button type="button" class="dialog-ep-btn primary" @click="goToTasks">查看任务队列</button>
            </footer>
          </section>
        </div>
      </Transition>
    </Teleport>

    <el-dialog
      v-model="duplicateDetailVisible"
      width="880px"
      class="existing-dialog duplicate-detail-dialog"
      :show-close="false"
      custom-class="mobile-full-dialog"
    >
      <template #header>
        <div class="dialog-header duplicate-dialog-header">
          <div class="dialog-title-wrap">
            <div class="dialog-icon warning">
              <AlertTriangle :size="18" />
            </div>
            <div>
              <div class="dialog-title">冲突详情</div>
              <div class="dialog-subtitle">{{ duplicateDetailSummary.title }}</div>
            </div>
          </div>
          <button type="button" class="dialog-close" @click="duplicateDetailVisible = false">
            <XCircle :size="18" />
          </button>
        </div>
      </template>

      <div v-if="duplicateDetailData" class="duplicate-panel">
        <div class="conflict-box large duplicate-alert">
          <AlertTriangle :size="16" />
          <div>
            <div class="conflict-title">{{ getConflictTypeLabel(duplicateDetailData.conflict_type) }}</div>
            <div class="conflict-desc">{{ duplicateDetailSummary.description }}</div>
          </div>
        </div>

        <div class="duplicate-compare-grid">
          <section class="duplicate-side-card current">
            <div class="duplicate-side-head">
              <span class="duplicate-side-badge">待入库</span>
              <strong>{{ duplicateCompare.current.name }}</strong>
            </div>
            <div class="duplicate-rj-line">
              <span>{{ duplicateCompare.current.rjcode || '未识别 RJ' }}</span>
              <span v-if="duplicateCompare.current.lang">{{ duplicateCompare.current.lang }}</span>
            </div>
            <div class="duplicate-metric-grid">
              <div class="duplicate-metric">
                <span>大小</span>
                <strong>{{ formatFileSize(duplicateCompare.current.size) }}</strong>
              </div>
              <div class="duplicate-metric">
                <span>文件数</span>
                <strong>{{ duplicateCompare.current.fileCount || '未知' }}</strong>
              </div>
              <div class="duplicate-metric">
                <span>修改</span>
                <strong>{{ formatDate(duplicateCompare.current.modifiedTime) }}</strong>
              </div>
            </div>
            <div class="duplicate-path" :title="duplicateCompare.current.path">{{ duplicateCompare.current.path }}</div>
          </section>

          <section class="duplicate-side-card library">
            <div class="duplicate-side-head">
              <span class="duplicate-side-badge">库内命中</span>
              <strong>{{ duplicateCompare.library.name }}</strong>
            </div>
            <div class="duplicate-rj-line">
              <span>{{ duplicateCompare.library.rjcode || '未知 RJ' }}</span>
              <span v-if="duplicateCompare.library.lang">{{ duplicateCompare.library.lang }}</span>
              <span v-if="duplicateCompare.library.workType">{{ getWorkTypeLabel(duplicateCompare.library.workType) }}</span>
            </div>
            <div class="duplicate-metric-grid">
              <div class="duplicate-metric">
                <span>大小</span>
                <strong>{{ formatFileSize(duplicateCompare.library.size) }}</strong>
              </div>
              <div class="duplicate-metric">
                <span>文件数</span>
                <strong>{{ duplicateCompare.library.fileCount || '未知' }}</strong>
              </div>
              <div class="duplicate-metric">
                <span>大小差异</span>
                <strong :class="duplicateCompare.sizeDiffClass">{{ duplicateCompare.sizeDiffLabel }}</strong>
              </div>
            </div>
            <div class="duplicate-path" :title="duplicateCompare.library.path">{{ duplicateCompare.library.path }}</div>
          </section>
        </div>

        <div class="duplicate-diff-strip">
          <div class="duplicate-diff-item">
            <span>大小差</span>
            <strong :class="duplicateCompare.sizeDiffClass">{{ duplicateCompare.sizeDiffLabel }}</strong>
          </div>
          <div class="duplicate-diff-item">
            <span>文件数差</span>
            <strong :class="duplicateCompare.fileDiffClass">{{ duplicateCompare.fileDiffLabel }}</strong>
          </div>
          <div class="duplicate-diff-item">
            <span>语言判断</span>
            <strong>{{ duplicateCompare.langDiffLabel }}</strong>
          </div>
        </div>

        <div v-if="duplicateDetailData.linked_works_found?.length" class="detail-card">
          <div class="detail-title">关联作品</div>
          <div v-for="work in duplicateDetailData.linked_works_found" :key="work.rjcode" class="linked-row">
            <span>{{ work.rjcode }}</span>
            <span>{{ work.work_name }}</span>
            <span>{{ formatFileSize(work.size) }} / {{ work.file_count || '未知' }} 个文件 / {{ work.lang || '-' }}</span>
          </div>
        </div>

        <div v-if="duplicateDetailData.resolution_options?.length" class="resolution-list">
          <button
            v-for="option in duplicateDetailData.resolution_options"
            :key="option.action"
            type="button"
            class="resolution-option"
            :class="{ active: selectedResolution === option.action, recommend: option.recommend }"
            @click="selectedResolution = option.action"
          >
            <span class="resolution-title">{{ option.label }}</span>
            <span class="resolution-desc">{{ option.description }}</span>
          </button>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer duplicate-footer">
          <button type="button" class="dialog-btn" @click="duplicateDetailVisible = false">关闭</button>
          <button type="button" class="dialog-btn primary" @click="handleProcessWithResolution">确认处理</button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onBeforeUnmount, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useVirtualizer } from '@tanstack/vue-virtual'
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock3,
  Eye,
  FileSearch,
  Folder,
  FolderInput,
  FolderTree,
  HardDrive,
  Hash,
  Loader2,
  MoveRight,
  PencilLine,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  SearchCheck,
  ShieldCheck,
  Tags,
  Trash2,
  XCircle
} from 'lucide-vue-next'
import { apiFetchOptions, apiUrl, existingFolderApi } from '../api'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import StatefulButton from '../components/ui/stateful-button.vue'
import { showSystemConfirm } from '../composables/useSystemPrompt'

const router = useRouter()

const loading = ref(false)
const processing = ref(false)
const checkingDuplicates = ref(false)
const folders = ref([])
const selectedFolderPaths = ref([])
const folderViewportHostRef = ref(null)
const folderVirtualScrollRef = ref(null)
const folderViewportWidth = ref(0)
const searchQuery = ref('')
const autoClassify = ref(true)
const checkDuplicates = ref(true)
const conflictCount = ref(0)
const resultDialogVisible = ref(false)
const resultData = ref({ success: true, message: '', tasks: [] })
const duplicateDetailVisible = ref(false)
const duplicateDetailData = ref(null)
const selectedResolution = ref('')
const currentConflictFolder = ref(null)

const duplicateDetailSummary = computed(() => {
  const data = duplicateDetailData.value || {}
  const current = data.analysis_info?.current_work
  const typeLabel = getConflictTypeLabel(data.conflict_type)
  const lang = current?.lang ? ` / ${current.lang}` : ''
  return {
    title: current ? `${typeLabel} · ${current.work_type || '当前作品'}${lang}` : typeLabel,
    description: current ? `当前作品类型：${current.work_type || '未知'}${lang}` : '库中已有相同或关联作品，请对比后选择处理方案'
  }
})

const duplicateCompare = computed(() => {
  const current = buildCurrentCompareItem(currentConflictFolder.value, duplicateDetailData.value)
  const library = buildLibraryCompareItem(duplicateDetailData.value)
  const sizeDiff = getNumberDiff(current.size, library.size)
  const fileDiff = getNumberDiff(current.fileCount, library.fileCount)
  return {
    current,
    library,
    sizeDiffLabel: formatDiffSize(sizeDiff),
    sizeDiffClass: getDiffClass(sizeDiff),
    fileDiffLabel: formatDiffNumber(fileDiff),
    fileDiffClass: getDiffClass(fileDiff),
    langDiffLabel: getLangDiffLabel(current.lang, library.lang)
  }
})

const pipelineSteps = [
  { label: '识别 RJ', desc: '从文件夹名提取作品编号', icon: Tags, tone: 'info' },
  { label: '抓取元数据', desc: '补齐标题、社团与发售日', icon: FileSearch, tone: 'ok' },
  { label: '重命名', desc: '按模板规范化目录名', icon: PencilLine, tone: 'warn' },
  { label: '分类入库', desc: '移动到库存分类目录', icon: MoveRight, tone: 'done' }
]

const folderIndexByPath = new Map()
let pendingFolderAdds = []
let pendingFolderUpdates = []
let pendingFlushHandle = 0
let folderResizeObserver = null

const FOLDER_VIRTUAL_THRESHOLD = 100
const FOLDER_GRID_GAP = 13

const filteredFolders = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return folders.value
  return folders.value.filter((folder) =>
    String(folder.name || '').toLowerCase().includes(query) ||
    String(folder.rjcode || '').toLowerCase().includes(query) ||
    String(folder.relative_path || '').toLowerCase().includes(query) ||
    String(folder.source_root_name || '').toLowerCase().includes(query) ||
    String(folder.path || '').toLowerCase().includes(query)
  )
})

const selectedPathSet = computed(() => new Set(selectedFolderPaths.value))
const selectedFolders = computed(() => selectedFolderPaths.value.map((path) => folders.value[folderIndexByPath.get(path)]).filter(Boolean))
const selectedProcessableFolders = computed(() => selectedFolders.value.filter(isProcessable))
const selectedCheckableFolders = computed(() => selectedFolders.value.filter(isCheckable))
const folderStats = computed(() => {
  const stats = {
    processableFolders: [],
    readyCount: 0,
    checkableCount: 0,
    conflictCount: 0
  }
  for (const folder of folders.value) {
    if (isProcessable(folder)) {
      stats.readyCount += 1
      stats.processableFolders.push(folder)
    }
    if (isCheckable(folder)) stats.checkableCount += 1
    if (isConflict(folder)) stats.conflictCount += 1
  }
  return stats
})
const allProcessableFolders = computed(() => folderStats.value.processableFolders)
const readyCount = computed(() => folderStats.value.readyCount)
const checkableCount = computed(() => folderStats.value.checkableCount)
const useVirtualFolders = computed(() => filteredFolders.value.length >= FOLDER_VIRTUAL_THRESHOLD)
const folderVirtualColumnCount = computed(() => {
  const width = Number(folderViewportWidth.value || 0)
  if (width <= 0) return 1
  if (width <= 640) return 1
  return Math.max(1, Math.floor((width + FOLDER_GRID_GAP) / (330 + FOLDER_GRID_GAP)))
})
const folderVirtualRowCount = computed(() => Math.ceil(filteredFolders.value.length / folderVirtualColumnCount.value))
const folderVirtualRowHeight = computed(() => {
  const width = Number(folderViewportWidth.value || 0)
  if (width <= 640) return 300
  return 246
})
const folderVirtualGridTemplateColumns = computed(() => `repeat(${folderVirtualColumnCount.value}, minmax(0, 1fr))`)
const readyRatio = computed(() => {
  const total = folders.value.length
  if (!total) return 0
  return Math.round((readyCount.value / total) * 100)
})

const folderRowVirtualizer = useVirtualizer(computed(() => ({
  count: folderVirtualRowCount.value,
  getScrollElement: () => folderVirtualScrollRef.value,
  estimateSize: () => folderVirtualRowHeight.value,
  overscan: 4
})))
const folderVirtualRows = computed(() => folderRowVirtualizer.value.getVirtualItems())
const folderVirtualCanvasStyle = computed(() => ({
  height: `${folderRowVirtualizer.value.getTotalSize()}px`
}))

onMounted(() => {
  updateFolderViewportWidth()
  folderResizeObserver = new ResizeObserver(() => {
    updateFolderViewportWidth()
    nextTick(() => folderRowVirtualizer.value.measure())
  })
  if (folderViewportHostRef.value) folderResizeObserver.observe(folderViewportHostRef.value)
  refreshWithCache()
})

onBeforeUnmount(() => {
  cancelPendingFolderFlush()
  folderResizeObserver?.disconnect()
  folderResizeObserver = null
})

watch(
  () => [searchQuery.value, folderVirtualColumnCount.value, filteredFolders.value.length].join(':'),
  () => {
    nextTick(() => {
      folderRowVirtualizer.value.scrollToOffset(0)
      folderRowVirtualizer.value.measure()
    })
  }
)

watch(folderVirtualRowHeight, () => {
  nextTick(() => folderRowVirtualizer.value.measure())
})

async function consumeNdjsonResponse(response, { forceRefresh = false, silent = false } = {}) {
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      const data = JSON.parse(line)
      if (data.type === 'folder') {
        queueFolderAdd(data.folder)
      } else if (data.type === 'folder_update') {
        queueFolderUpdate(data.folder)
      } else if (data.type === 'complete') {
        flushPendingFolderChanges()
        conflictCount.value = folderStats.value.conflictCount
        let msg = data.message || `扫描完成，找到 ${folders.value.length} 个文件夹`
        if (forceRefresh) msg += '，已重新抓取'
        if (!silent) ElMessage.success(msg)
      } else if (data.type === 'error') {
        ElMessage.error(data.error || '扫描失败')
      }
    }
  }
  flushPendingFolderChanges()
}

async function refreshFoldersWithOptions(forceRefresh = false, { silent = false } = {}) {
  loading.value = true
  cancelPendingFolderFlush()
  folderIndexByPath.clear()
  folders.value = []
  selectedFolderPaths.value = []
  conflictCount.value = 0
  try {
    const url = apiUrl(`/existing-folders/scan?check_duplicates=${checkDuplicates.value}&force_refresh=${forceRefresh}`)
    const response = await fetch(url, apiFetchOptions({ method: 'POST', headers: { Accept: 'application/x-ndjson' } }))
    await consumeNdjsonResponse(response, { forceRefresh, silent })
    return true
  } catch (error) {
    console.error('获取文件夹列表失败:', error)
    ElMessage.error('获取失败: ' + (error.message || '未知错误'))
    return false
  } finally {
    loading.value = false
  }
}

function refreshWithCache() {
  return refreshFoldersWithOptions(false)
}

function closeResultDialog() {
  resultDialogVisible.value = false
}

async function refreshForce() {
  try {
    await showSystemConfirm({
      title: '重新抓取已有文件夹',
      message: '将清除已有文件夹缓存并重新查询查重信息，目录较多时会更慢。',
      tone: 'warning',
      confirmText: '重新抓取'
    })
    await existingFolderApi.refreshCache()
    return await refreshFoldersWithOptions(true)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('刷新失败: ' + (error.message || '未知错误'))
    return error === 'cancel' ? undefined : false
  }
}

function isConflict(folder) {
  return Boolean(folder?.duplicate_info?.is_duplicate)
}

function isUnrecognized(folder) {
  return !folder?.rjcode || folder.status === 'unrecognized'
}

function isCheckable(folder) {
  return Boolean(folder?.rjcode) && folder.status !== 'checking'
}

function isProcessable(folder) {
  return Boolean(folder?.rjcode) && !isConflict(folder) && folder.status !== 'unrecognized'
}

function canSelectFolder(folder) {
  return isCheckable(folder)
}

function isSelected(folder) {
  return selectedPathSet.value.has(folder.path)
}

function toggleFolderSelection(folder) {
  if (!canSelectFolder(folder)) {
    ElMessage.warning('这个目录还没有识别到 RJ 号，不能加入处理队列')
    return
  }
  if (isSelected(folder)) {
    selectedFolderPaths.value = selectedFolderPaths.value.filter((path) => path !== folder.path)
  } else {
    selectedFolderPaths.value = [...selectedFolderPaths.value, folder.path]
  }
}

function selectAllProcessableFolders() {
  selectedFolderPaths.value = allProcessableFolders.value.map((folder) => folder.path)
}

function clearSelectedFolders() {
  selectedFolderPaths.value = []
}

function getFolderState(folder) {
  if (isConflict(folder)) return { label: getConflictTypeLabel(folder.duplicate_info?.conflict_type), tone: 'danger', icon: 'alert' }
  if (isUnrecognized(folder)) return { label: '未识别 RJ', tone: 'muted', icon: 'x' }
  if (folder.status === 'checking') return { label: '检查中', tone: 'warning', icon: 'refresh' }
  if (folder.status === 'pending') return { label: '待检查', tone: 'muted', icon: 'clock' }
  if (folder.status === 'error') return { label: '检查失败', tone: 'danger', icon: 'x' }
  if (folder.status === 'cached') return { label: '已检查', tone: 'info', icon: 'shield' }
  return { label: '可处理', tone: 'success', icon: 'check' }
}

async function submitProcessFolders(targets, { title, message, confirmText = '开始处理', clearSelection = false, refreshDelay = 1000 } = {}) {
  const processableTargets = Array.isArray(targets) ? targets.filter(isProcessable) : []
  if (!processableTargets.length) {
    ElMessage.warning('没有可处理的目录')
    return false
  }
  try {
    if (title || message) {
      await showSystemConfirm({
        title: title || '处理已有文件夹',
        message: message || buildProcessConfirmMessage(processableTargets),
        tone: 'info',
        confirmText
      })
    }
    processing.value = true
    const data = await existingFolderApi.process(processableTargets.map((folder) => folder.path), autoClassify.value)
    resultData.value = { success: true, message: data.message, tasks: data.tasks || [] }
    resultDialogVisible.value = true
    if (clearSelection) selectedFolderPaths.value = []
    if (refreshDelay) setTimeout(() => refreshFoldersWithOptions(false, { silent: true }), refreshDelay)
    return true
  } catch (error) {
    if (error !== 'cancel') {
      resultData.value = { success: false, message: error.response?.data?.detail || error.message, tasks: [] }
      resultDialogVisible.value = true
      return false
    }
    return undefined
  } finally {
    processing.value = false
  }
}

async function handleProcessSelected() {
  if (!selectedProcessableFolders.value.length) {
    ElMessage.warning('没有可处理的选中目录')
    return false
  }
  return submitProcessFolders(selectedProcessableFolders.value, {
    title: '入库选中目录',
    message: buildProcessConfirmMessage(selectedProcessableFolders.value),
    confirmText: '开始入库',
    clearSelection: true
  })
}

async function handleProcessAll() {
  if (!allProcessableFolders.value.length) {
    ElMessage.warning('没有可入库的目录')
    return false
  }
  return submitProcessFolders(allProcessableFolders.value, {
    title: '入库全部可处理目录',
    message: `将创建 ${allProcessableFolders.value.length} 个已有文件夹处理任务，冲突目录会被跳过。${autoClassify.value ? '任务完成后会自动分类移动到库存。' : '当前已关闭自动分类，只会完成抓取、重命名和过滤。'}`,
    confirmText: '全部入库',
    clearSelection: true
  })
}

async function checkSelectedDuplicates() {
  if (!selectedCheckableFolders.value.length) {
    ElMessage.warning('没有可查重的选中目录')
    return false
  }
  checkingDuplicates.value = true
  try {
    const data = await existingFolderApi.checkDuplicates(selectedCheckableFolders.value.map((folder) => folder.path), { checkLinkedWorks: true })
    applyDuplicateResults(data.results || [])
    ElMessage[data.duplicate_count > 0 ? 'warning' : 'success'](data.message || '查重完成')
    return true
  } catch (error) {
    ElMessage.error('查重检查失败: ' + (error.response?.data?.detail || error.message))
    return false
  } finally {
    checkingDuplicates.value = false
  }
}

function applyDuplicateResults(results) {
  if (!Array.isArray(results) || !results.length) return
  const nextFolders = folders.value.slice()
  let changed = false
  results.forEach((result) => {
    const index = folderIndexByPath.get(result.folder_path)
    if (index === -1) return
    if (typeof index !== 'number') return
    nextFolders[index] = {
      ...nextFolders[index],
      status: result.error && !result.rjcode ? 'unrecognized' : (result.error ? 'error' : 'checked'),
      duplicate_info: result.error ? { error: result.error } : {
        is_duplicate: result.is_duplicate,
        conflict_type: result.conflict_type,
        direct_duplicate: result.direct_duplicate,
        linked_works_found: result.linked_works_found,
        related_rjcodes: result.related_rjcodes,
        analysis_info: result.analysis_info,
        resolution_options: result.resolution_options
      }
    }
    changed = true
  })
  if (changed) folders.value = nextFolders
  conflictCount.value = folderStats.value.conflictCount
}

function showDuplicateDetail(row) {
  currentConflictFolder.value = row
  duplicateDetailData.value = row.duplicate_info
  const options = row.duplicate_info?.resolution_options || []
  selectedResolution.value = options.find((option) => option.recommend)?.action || options[0]?.action || ''
  duplicateDetailVisible.value = true
}

async function handleProcessWithResolution() {
  if (!selectedResolution.value) {
    ElMessage.warning('请先选择一个处理方案')
    return
  }
  const selectedOption = duplicateDetailData.value?.resolution_options?.find((option) => option.action === selectedResolution.value)
  try {
    await showSystemConfirm({
      title: '确认处理冲突',
      message: `确定要执行「${selectedOption?.label || selectedResolution.value}」吗？`,
      tone: selectedResolution.value === 'SKIP' ? 'danger' : 'info',
      confirmText: '确认处理'
    })
    const data = await existingFolderApi.processWithResolution(currentConflictFolder.value?.path, selectedResolution.value, autoClassify.value)
    ElMessage.success(data.message || '操作成功')
    duplicateDetailVisible.value = false
    await refreshWithCache()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('处理失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function handleDeleteFolder(row) {
  try {
    await showSystemConfirm({
      title: '删除待处理目录',
      description: '只会移除已有文件夹目录中的这份待处理内容，不会删除库存里的作品。',
      message: '删除后无法从本页面恢复；如果还需要入库，请先取消操作。',
      currentLabel: '目录',
      currentValue: row.name || getFolderName(row.path) || row.path,
      details: [
        { label: '路径', value: row.path },
        { label: 'RJ', value: row.rjcode || '未识别' }
      ],
      tone: 'danger',
      confirmText: '删除目录'
    })
    await existingFolderApi.delete(row.path)
    ElMessage.success('待处理目录已删除')
    await refreshWithCache()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function handleRefreshFolder(row) {
  if (!isCheckable(row)) {
    ElMessage.warning('这个目录还没有识别到 RJ 号，不能查重')
    return false
  }
  checkingDuplicates.value = true
  try {
    updateFolderByPath(row.path, { status: 'checking' })
    const data = await existingFolderApi.checkDuplicates([row.path], { checkLinkedWorks: true })
    applyDuplicateResults(data.results || [])
    ElMessage[data.duplicate_count > 0 ? 'warning' : 'success'](data.duplicate_count > 0 ? '发现冲突' : '查重完成，无冲突')
    return true
  } catch (error) {
    ElMessage.error('刷新失败: ' + (error.response?.data?.detail || error.message))
    return false
  } finally {
    checkingDuplicates.value = false
  }
}

function queueFolderAdd(folder) {
  pendingFolderAdds.push(folder)
  scheduleFolderFlush()
}

function updateFolderViewportWidth() {
  const el = folderViewportHostRef.value || folderVirtualScrollRef.value
  folderViewportWidth.value = Math.max(0, Math.round(el?.clientWidth || 0))
}

function getVirtualFolderRowItems(rowIndex) {
  const start = rowIndex * folderVirtualColumnCount.value
  return filteredFolders.value.slice(start, start + folderVirtualColumnCount.value)
}

function queueFolderUpdate(folder) {
  pendingFolderUpdates.push(folder)
  scheduleFolderFlush()
}

function scheduleFolderFlush() {
  if (pendingFlushHandle) return
  const run = () => {
    pendingFlushHandle = 0
    flushPendingFolderChanges()
  }
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    pendingFlushHandle = window.requestAnimationFrame(run)
  } else {
    pendingFlushHandle = window.setTimeout(run, 16)
  }
}

function cancelPendingFolderFlush() {
  if (pendingFlushHandle && typeof window !== 'undefined') {
    if (typeof window.cancelAnimationFrame === 'function') window.cancelAnimationFrame(pendingFlushHandle)
    else window.clearTimeout(pendingFlushHandle)
  }
  pendingFlushHandle = 0
  pendingFolderAdds = []
  pendingFolderUpdates = []
}

function flushPendingFolderChanges() {
  if (!pendingFolderAdds.length && !pendingFolderUpdates.length) return
  const nextFolders = folders.value.slice()
  const adds = pendingFolderAdds
  const updates = pendingFolderUpdates
  pendingFolderAdds = []
  pendingFolderUpdates = []

  for (const folder of adds) {
    const path = folder?.path
    if (!path) continue
    const existingIndex = folderIndexByPath.get(path)
    if (typeof existingIndex === 'number') {
      nextFolders[existingIndex] = { ...nextFolders[existingIndex], ...folder }
      continue
    }
    folderIndexByPath.set(path, nextFolders.length)
    nextFolders.push(folder)
  }

  for (const folder of updates) {
    const path = folder?.path
    const index = folderIndexByPath.get(path)
    if (typeof index !== 'number') continue
    nextFolders[index] = { ...nextFolders[index], ...folder }
  }

  folders.value = nextFolders
  pruneSelectedFolderPaths()
}

function updateFolderByPath(path, patch) {
  const index = folderIndexByPath.get(path)
  if (typeof index !== 'number') return
  const nextFolders = folders.value.slice()
  nextFolders[index] = { ...nextFolders[index], ...patch }
  folders.value = nextFolders
}

function pruneSelectedFolderPaths() {
  const currentPaths = selectedFolderPaths.value
  if (!currentPaths.length) return
  const nextPaths = currentPaths.filter((path) => folderIndexByPath.has(path))
  if (nextPaths.length !== currentPaths.length) selectedFolderPaths.value = nextPaths
}

async function handleProcessSingle(row) {
  if (!isProcessable(row)) {
    ElMessage.warning(isConflict(row) ? '这个目录有冲突，请先查看冲突详情' : '这个目录还没有识别到 RJ 号')
    return false
  }
  return submitProcessFolders([row], {
    title: autoClassify.value ? '移动到库存' : '处理已有文件夹',
    message: buildProcessConfirmMessage([row]),
    confirmText: autoClassify.value ? '开始入库' : '开始处理'
  })
}

function buildProcessConfirmMessage(targets) {
  const count = Array.isArray(targets) ? targets.length : 0
  const first = targets?.[0]
  const subject = count === 1 ? `「${first?.name || getFolderName(first?.path) || '当前目录'}」` : `${count} 个目录`
  const classifyText = autoClassify.value ? '并自动分类移动到库存目录' : '但不会自动移动到库存分类目录'
  return `将对${subject}执行元数据抓取、重命名和过滤，${classifyText}。已检查无冲突的目录会跳过重复预检。`
}

function getProcessButtonLabel(folder) {
  if (isUnrecognized(folder)) return '等待识别'
  return autoClassify.value ? '移动到库存' : '处理目录'
}

function getFolderName(path) {
  if (!path) return ''
  const parts = path.split(/[\\/]/)
  return parts[parts.length - 1]
}

function getFolderDisplayPath(folder) {
  if (folder?.relative_path) return folder.relative_path
  return folder?.path || ''
}

function goToTasks() {
  resultDialogVisible.value = false
  router.push('/tasks')
}

function formatFileSize(bytes) {
  const value = Number(bytes || 0)
  if (!value) return '未知'
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(value) / Math.log(1024))
  return `${parseFloat((value / Math.pow(1024, i)).toFixed(2))} ${sizes[i]}`
}

function formatDate(dateStr) {
  if (!dateStr) return '时间未知'
  const date = new Date(String(dateStr).trim().replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return '时间未知'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

function buildCurrentCompareItem(folder, detail) {
  const currentWork = detail?.analysis_info?.current_work || {}
  return {
    name: folder?.name || getFolderName(folder?.path) || '当前目录',
    rjcode: folder?.rjcode || currentWork.rjcode || '',
    lang: currentWork.lang || '',
    workType: currentWork.work_type || '',
    size: Number(folder?.folder_size ?? folder?.size ?? 0),
    fileCount: Number(folder?.file_count || 0),
    modifiedTime: folder?.modified_time || '',
    path: folder?.path || ''
  }
}

function buildLibraryCompareItem(detail) {
  const duplicate = detail?.direct_duplicate
  const linked = Array.isArray(detail?.linked_works_found) ? detail.linked_works_found[0] : null
  const item = duplicate || linked || {}
  return {
    name: item.work_name || getFolderName(item.path) || '库内作品',
    rjcode: item.rjcode || '',
    lang: item.lang || '',
    workType: item.work_type || (duplicate ? 'duplicate' : ''),
    size: Number(item.size || item.folder_size || 0),
    fileCount: Number(item.file_count || 0),
    path: item.path || item.folder_path || ''
  }
}

function getNumberDiff(current, library) {
  if (!Number(current) || !Number(library)) return null
  return Number(current) - Number(library)
}

function formatDiffSize(diff) {
  if (diff === null) return '未知'
  if (diff === 0) return '相同'
  return `${diff > 0 ? '+' : '-'}${formatFileSize(Math.abs(diff))}`
}

function formatDiffNumber(diff) {
  if (diff === null) return '未知'
  if (diff === 0) return '相同'
  return `${diff > 0 ? '+' : ''}${diff}`
}

function getDiffClass(diff) {
  if (diff === null || diff === 0) return 'neutral'
  return diff > 0 ? 'positive' : 'negative'
}

function getLangDiffLabel(currentLang, libraryLang) {
  if (!currentLang && !libraryLang) return '未知'
  if (!currentLang) return `库内 ${libraryLang}`
  if (!libraryLang) return `新版 ${currentLang}`
  return currentLang === libraryLang ? `同语言 ${currentLang}` : `${currentLang} → ${libraryLang}`
}

function getWorkTypeLabel(type) {
  const labels = {
    duplicate: '同 RJ',
    original: '原作',
    parent: '父级',
    child: '子版本'
  }
  return labels[type] || type || ''
}

function getConflictTypeLabel(conflictType) {
  const labels = {
    DUPLICATE: '直接重复',
    LINKED_WORK_ORIGINAL: '原作已存在',
    LINKED_WORK_TRANSLATION: '翻译版已存在',
    LINKED_WORK_CHILD: '子版本已存在',
    LINKED_WORK: '关联作品',
    LANGUAGE_VARIANT: '语言变体',
    MULTIPLE_VERSIONS: '多版本'
  }
  return labels[conflictType] || '冲突'
}
</script>

<style scoped>
.existing-page,
:global(.existing-dialog) {
  --ef-page-bg: transparent;
  --ef-surface: #ffffff;
  --ef-surface-soft: #f8fafc;
  --ef-surface-muted: #f1f5f9;
  --ef-surface-hover: #fafbfc;
  --ef-text: #0f172a;
  --ef-text-soft: #334155;
  --ef-muted: #64748b;
  --ef-faint: #94a3b8;
  --ef-border: #e2e8f0;
  --ef-border-soft: rgba(15, 23, 42, 0.08);
  --ef-border-strong: rgba(15, 23, 42, 0.18);
  --ef-primary: #111827;
  --ef-primary-hover: #1f2937;
  --ef-primary-soft: rgba(15, 23, 42, 0.06);
  --ef-shadow: 0 10px 26px rgba(15, 23, 42, 0.04);
  --ef-shadow-hover: 0 18px 36px rgba(15, 23, 42, 0.1);
  --ef-conflict-bg: #fff7ed;
  --ef-conflict-border: #fed7aa;
  --ef-conflict-text: #9a3412;
  --ef-conflict-muted: #b45309;
  --ef-success-bg: #ecfdf5;
  --ef-success-text: #047857;
  --ef-success-border: #bbf7d0;
  --ef-warning-bg: #fffbeb;
  --ef-warning-bg-hover: #fef3c7;
  --ef-warning-text: #b45309;
  --ef-warning-border: #fde68a;
  --ef-danger-bg: #fef2f2;
  --ef-danger-text: #dc2626;
  --ef-danger-border: #fca5a5;
  --ef-positive-text: #047857;
  --ef-negative-text: #b45309;
  --ef-accent-bg: #111827;
  --ef-accent-bg-hover: #020617;
  --ef-accent-text: #ffffff;
  --ef-switch-on: #111827;
  --ef-switch-on-hover: #020617;
  --ef-recommend-bg: linear-gradient(180deg, #f0fdf4 0%, #ffffff 100%);
  --ef-recommend-border: #bbf7d0;
  --ef-recommend-active: #047857;
  color: var(--ef-text);
  background: var(--ef-page-bg);
}

:global(html.kikoerumanager-dark .existing-page),
:global(html.kikoerumanager-dark .existing-dialog) {
  --ef-page-bg: transparent;
  --ef-surface: #101012;
  --ef-surface-soft: #17181b;
  --ef-surface-muted: #222328;
  --ef-surface-hover: #1d1e22;
  --ef-text: #f8fafc;
  --ef-text-soft: #e2e8f0;
  --ef-muted: #cbd5e1;
  --ef-faint: #94a3b8;
  --ef-border: rgba(255, 255, 255, 0.12);
  --ef-border-soft: rgba(255, 255, 255, 0.08);
  --ef-border-strong: rgba(255, 255, 255, 0.2);
  --ef-primary: #2a2b30;
  --ef-primary-hover: #34363c;
  --ef-primary-soft: rgba(255, 255, 255, 0.1);
  --ef-shadow: 0 18px 42px rgba(0, 0, 0, 0.34);
  --ef-shadow-hover: 0 24px 54px rgba(0, 0, 0, 0.44);
  --ef-conflict-bg: rgba(127, 29, 29, 0.16);
  --ef-conflict-border: rgba(248, 113, 113, 0.28);
  --ef-conflict-text: #fca5a5;
  --ef-conflict-muted: #f87171;
  --ef-success-bg: rgba(5, 150, 105, 0.16);
  --ef-success-text: #34d399;
  --ef-success-border: rgba(52, 211, 153, 0.38);
  --ef-warning-bg: rgba(245, 158, 11, 0.16);
  --ef-warning-bg-hover: rgba(245, 158, 11, 0.22);
  --ef-warning-text: #fbbf24;
  --ef-warning-border: rgba(251, 191, 36, 0.4);
  --ef-danger-bg: rgba(225, 29, 72, 0.16);
  --ef-danger-text: #fb7185;
  --ef-danger-border: rgba(251, 113, 133, 0.38);
  --ef-positive-text: #34d399;
  --ef-negative-text: #fbbf24;
  --ef-accent-bg: #2a2b30;
  --ef-accent-bg-hover: #34363c;
  --ef-accent-text: #f8fafc;
  --ef-switch-on: #2a2b30;
  --ef-switch-on-hover: #34363c;
  --ef-recommend-bg: linear-gradient(180deg, rgba(5, 150, 105, 0.18) 0%, rgba(16, 16, 18, 0.9) 100%);
  --ef-recommend-border: rgba(52, 211, 153, 0.38);
  --ef-recommend-active: #34d399;
}

.existing-page {
  max-width: 1480px;
  margin: 0 auto;
  padding: 22px;
}

/* ============================================================
 * 页头搜索框 + page-head-btn 规范按钮（对齐 ASMR 同步页 / 操作记录页）
 * ============================================================ */
.hero-search-wrap { position: relative; width: min(360px, 42vw); }
.hero-search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: var(--ef-faint); pointer-events: none; transition: color 0.2s ease; }
.hero-search-input { width: 100%; height: 36px; padding: 0 14px 0 34px; border: 1px solid var(--ef-border-soft); border-radius: 10px; outline: none; background: var(--ef-surface); font-size: 13px; color: var(--ef-text); transition: border-color 0.25s ease, box-shadow 0.25s ease, background-color 0.25s ease; }
.hero-search-input::placeholder { color: var(--ef-faint); }
.hero-search-input:hover { border-color: var(--ef-border-strong); background: var(--ef-surface-soft); }
.hero-search-input:focus { border-color: var(--ef-primary); background: var(--ef-surface); box-shadow: 0 0 0 3px var(--ef-primary-soft); }
.hero-search-wrap:focus-within .hero-search-icon { color: var(--ef-primary); }

.ef-head-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid var(--ef-border-soft);
  background: var(--ef-surface);
  color: var(--ef-text-soft);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  overflow: hidden;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
  will-change: transform, opacity;
}
.ef-head-btn :deep(.ef-head-btn-icon) {
  flex-shrink: 0;
  transition: transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1), filter 0.3s ease;
}
.ef-head-btn :deep(.stateful-button__content),
.side-ep-action :deep(.stateful-button__content),
.card-action :deep(.stateful-button__content) {
  gap: inherit;
}
.ef-head-btn :deep(.stateful-button__state),
.side-ep-action :deep(.stateful-button__state),
.card-action :deep(.stateful-button__state) {
  min-width: 0;
}
.ef-head-btn :deep(svg) { flex-shrink: 0; }
.ef-head-btn-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  position: relative;
}
.ef-head-btn:hover {
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
}
.ef-head-btn:active:not(:disabled) {
  transform: scale(0.96);
  transition:
    transform 0.12s ease,
    box-shadow 0.18s ease,
    background-color 0.2s ease,
    border-color 0.2s ease,
    color 0.2s ease,
    opacity 0.2s ease;
}
.ef-head-btn:active:not(:disabled) :deep(.ef-head-btn-icon) {
  transform: scale(0.82);
  transition: transform 0.12s ease;
}
/* disabled：仅改 opacity / cursor，不重置 transform / shadow，避免点击瞬间塌回闪烁 */
.ef-head-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* primary：黑灰渐变 + shimmer 高光（对齐 ASMR 同步页 page-head-btn.primary） */
.ef-head-btn.primary {
  background: linear-gradient(135deg, var(--ef-primary), var(--ef-primary-hover));
  color: var(--ef-surface);
  border-color: transparent;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.18);
}
.ef-head-btn.primary::before {
  content: '';
  position: absolute;
  top: 0;
  left: -120%;
  width: 60%;
  height: 100%;
  background: linear-gradient(100deg, transparent 0%, rgba(255,255,255,0.05) 30%, rgba(255,255,255,0.28) 50%, rgba(255,255,255,0.05) 70%, transparent 100%);
  transform: skewX(-18deg);
  transition: left 0.7s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}
.ef-head-btn.primary:hover {
  background: linear-gradient(135deg, var(--ef-primary-hover), var(--ef-primary));
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.28), 0 0 0 4px rgba(15, 23, 42, 0.05);
}
.ef-head-btn.primary:hover::before { left: 130%; }

/* ghost：白底纯色 transition（gradient 不能 transition 会瞬切） */
.ef-head-btn.ghost { background-color: var(--ef-surface); }
.ef-head-btn.ghost:hover { background-color: var(--ef-surface-soft); border-color: var(--ef-border-strong); }

/* 各按钮专属图标动效 */
.ef-head-btn.btn-refresh:hover :deep(.ef-head-btn-icon:not(.animate-spin)) {
  transform: rotate(-360deg) scale(1.1);
  transition: transform 0.7s cubic-bezier(0.4, 0, 0.2, 1);
}
.ef-head-btn.btn-rescan:hover :deep(.ef-head-btn-icon) {
  transform: rotate(-180deg) scale(1.12);
}
.ef-head-state-icon {
  flex: 0 0 auto;
  transition: transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.2s ease;
}

.ef-head-btn-label {
  display: inline-block;
  text-align: center;
  transition: opacity 0.2s ease, letter-spacing 0.3s ease;
}
.ef-head-btn.primary .ef-head-btn-label { min-width: 56px; }
.ef-head-btn.ghost .ef-head-btn-label { min-width: 56px; }
.ef-head-btn:hover .ef-head-btn-label { letter-spacing: 0.04em; }

/* ============================================================
 * 顶部状态条 ef-info-strip（对齐 lib-info-strip 风格）
 * ============================================================ */
.ef-info-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr) 1px minmax(0, 1fr);
  align-items: stretch;
  gap: 0;
  margin-bottom: 14px;
  padding: 16px 20px;
  border-radius: 14px;
  background: var(--ef-surface);
  border: 1px solid var(--ef-border-soft);
  box-shadow: var(--ef-shadow);
}
.ef-info-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-width: 0;
  padding: 0 18px;
}
.ef-info-item:first-child { padding-left: 0; }
.ef-info-item:last-child { padding-right: 0; }
.ef-info-icon { flex-shrink: 0; margin-top: 3px; }
.ef-info-icon-blue { color: #3b82f6; }
.ef-info-icon-emerald { color: #10b981; }
.ef-info-icon-amber { color: #f59e0b; }
.ef-info-icon-slate { color: var(--ef-muted); }
.ef-info-body { min-width: 0; flex: 1 1 auto; }
.ef-info-label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ef-faint);
  margin-bottom: 4px;
}
.ef-info-value {
  font-size: 13.5px;
  color: var(--ef-muted);
  line-height: 1.3;
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  min-height: 1.5em;
  position: relative;
}
.ef-info-value > b {
  font-weight: 700;
  font-size: 20px;
  letter-spacing: -0.4px;
  color: var(--ef-text);
  font-variant-numeric: tabular-nums;
  display: inline-block;
  transform-origin: center;
}
.ef-info-meta { color: var(--ef-faint); font-size: 12px; }
.ef-info-divider {
  width: 1px;
  background: linear-gradient(180deg, transparent, var(--ef-border-strong), transparent);
  align-self: stretch;
}
@media (max-width: 980px) {
  .ef-info-strip { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); padding: 12px 14px; gap: 12px 0; }
  .ef-info-divider { display: none; }
  .ef-info-item { padding: 0 8px; }
}

/* 数字 fade flip（mode="out-in"） */
.ef-num-flip-enter-active {
  transition:
    opacity 0.28s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.ef-num-flip-leave-active {
  transition: opacity 0.18s ease, transform 0.2s ease;
}
.ef-num-flip-enter-from { opacity: 0; transform: translateY(-8px) scale(0.85); }
.ef-num-flip-leave-to   { opacity: 0; transform: translateY(8px) scale(0.85); }

/* ============================================================
 * 主体布局：左侧栏 + 右侧主区
 * ============================================================ */
.existing-shell { display: grid; grid-template-columns: 292px minmax(0,1fr); gap: 18px; margin-top: 18px; }
.existing-sidebar { min-width: 0; }
.sidebar-card, .folders-card { border: 1px solid var(--ef-border); border-radius: 20px; background: var(--ef-surface); box-shadow: var(--ef-shadow); }
.sidebar-card {
  position: sticky;
  top: 18px;
  overflow: hidden;
  padding: 14px;
  border-color: var(--ef-border);
  background: var(--ef-surface);
  box-shadow: none;
}
.folder-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.strategy-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 2px 0;
}
.strategy-hero-main { min-width: 0; }
.strategy-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--ef-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.strategy-eyebrow-icon {
  width: auto;
  height: auto;
  display: inline-grid;
  place-items: center;
  color: #0891b2;
  background: transparent;
  transform: translateY(-1px);
}
.sidebar-title {
  margin-top: 8px;
  font-size: 22px;
  font-weight: 950;
  line-height: 1;
  letter-spacing: -0.04em;
}
.strategy-score {
  min-width: 60px;
  border-radius: 14px;
  padding: 8px 10px;
  border: 1px solid var(--ef-border-soft);
  background: var(--ef-surface);
  color: var(--ef-text);
  text-align: right;
  box-shadow: none;
}
.strategy-score-value {
  display: block;
  color: #0891b2;
  font-size: 20px;
  font-weight: 900;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.strategy-score-label {
  display: block;
  margin-top: 4px;
  color: var(--ef-muted);
  font-size: 10px;
  font-weight: 800;
}
.strategy-meter {
  margin-top: 14px;
  padding: 0 2px 12px;
  border: 0;
  border-bottom: 1px solid var(--ef-border-soft);
  border-radius: 0;
  background: var(--ef-surface);
}
.strategy-meter-track {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  border: 1px solid var(--ef-border-soft);
  background: transparent;
}
.strategy-meter-track span {
  display: block;
  width: var(--ready-percent);
  height: 100%;
  border-radius: inherit;
  background: #0891b2;
  transition: width 0.45s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.strategy-meter-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-top: 9px;
  color: var(--ef-muted);
  font-size: 11px;
  font-weight: 800;
}
.strategy-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  margin-top: 12px;
  padding-bottom: 12px;
  border: 0;
  border-bottom: 1px solid var(--ef-border-soft);
  border-radius: 0;
  overflow: visible;
}
.strategy-stat {
  min-width: 0;
  padding: 0 9px;
  border: 0;
  border-right: 1px solid var(--ef-border-soft);
  border-radius: 0;
  background: var(--ef-surface);
}
.strategy-stat:first-child { padding-left: 2px; }
.strategy-stat:last-child { border-right: 0; }
.strategy-stat span {
  display: block;
  overflow: hidden;
  color: var(--ef-faint);
  font-size: 10px;
  font-weight: 800;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.strategy-stat strong {
  display: block;
  margin-top: 5px;
  color: var(--ef-text);
  font-size: 18px;
  font-weight: 900;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.pipeline-list {
  margin-top: 14px;
  display: grid;
  gap: 0;
  padding: 0 2px 14px;
  border: 0;
  border-bottom: 1px solid var(--ef-border-soft);
  border-radius: 0;
  background: var(--ef-surface);
}
.pipeline-item {
  position: relative;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 9px;
  min-height: 48px;
}
.pipeline-item:last-child { min-height: 26px; }
.pipeline-rail {
  position: relative;
  display: flex;
  justify-content: center;
}
.pipeline-item:not(:last-child) .pipeline-rail::after {
  content: '';
  position: absolute;
  top: 24px;
  bottom: 2px;
  width: 1px;
  background: var(--ef-border-soft);
}
.pipeline-dot {
  position: relative;
  z-index: 1;
  width: 18px;
  height: 22px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 0;
  background: transparent;
  box-shadow: none;
  transform: translateY(-1px);
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.25s ease;
}
.pipeline-item:hover .pipeline-dot { transform: translateY(-2px) scale(1.08); }
.pipeline-dot.info { color: #0284c7; }
.pipeline-dot.ok { color: #059669; }
.pipeline-dot.warn { color: #d97706; }
.pipeline-dot.done { color: #4f46e5; }
.pipeline-copy { min-width: 0; padding-top: 2px; }
.pipeline-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.pipeline-title {
  min-width: 0;
  color: var(--ef-text);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.2;
}
.pipeline-index {
  color: var(--ef-faint);
  font-size: 10px;
  font-weight: 900;
  font-variant-numeric: tabular-nums;
}
.pipeline-desc { margin-top: 3px; font-size: 11px; color: var(--ef-muted); line-height: 1.45; }
.strategy-section-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin: 12px 2px 8px;
  color: var(--ef-faint);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.option-stack { display: grid; grid-template-columns: 1fr; gap: 8px; }
.option-row {
  width: 100%;
  min-height: 58px;
  border: 1px solid var(--ef-border-soft);
  border-radius: 12px;
  background: var(--ef-surface);
  color: var(--ef-text);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  padding: 10px;
  text-align: left;
  cursor: pointer;
  box-shadow: none;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    border-color 0.25s ease,
    background-color 0.25s ease;
}
.option-row:hover {
  transform: translateY(-2px) scale(1.01);
  border-color: var(--ef-border-strong);
  background: var(--ef-surface);
  box-shadow: none;
}
.option-row:active { transform: scale(0.97); transition: transform 0.12s ease; }
.option-row.checked {
  border-color: var(--ef-border-strong);
  background: var(--ef-surface);
}
.option-row-main { min-width: 0; display: flex; align-items: center; gap: 10px; color: var(--ef-muted); }
.option-icon {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  display: inline-grid;
  place-items: center;
  color: var(--ef-text-soft);
  background: transparent;
  transform: translateY(-1px);
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.25s ease, color 0.25s ease;
}
.option-icon.classify { color: var(--ef-text-soft); }
.option-icon.duplicate { color: var(--ef-text-soft); }
.option-row:hover .option-icon { transform: translateY(-2px) rotate(-8deg) scale(1.08); }
.option-row.checked .option-icon.classify,
.option-row.checked .option-icon.duplicate { color: var(--ef-text); background: transparent; }
.option-row-title { color: var(--ef-text); font-size: 13px; font-weight: 900; line-height: 1.2; }
.option-row-desc { margin-top: 3px; color: var(--ef-faint); font-size: 11px; line-height: 1.35; }
.option-state {
  min-width: 22px;
  color: var(--ef-faint);
  font-size: 11px;
  font-weight: 900;
  text-align: center;
}
.option-row.checked .option-state { color: var(--ef-text); }
.ef-switch {
  width: 32px;
  height: 20px;
  flex: 0 0 auto;
  border: 1px solid var(--ef-border-soft);
  border-radius: 999px;
  background: transparent;
  padding: 2px;
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  cursor: pointer;
  box-shadow: none;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease;
}
.option-row:hover .ef-switch { transform: scale(1.04); border-color: var(--ef-border-strong); }
.ef-switch.checked {
  justify-content: flex-end;
  background: var(--ef-switch-on);
  border-color: var(--ef-switch-on);
  box-shadow: none;
}
.ef-switch-thumb {
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: var(--ef-surface);
  box-shadow: none;
  transition:
    background-color 0.25s ease,
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.option-row:hover .ef-switch-thumb { transform: scale(1.04); }
.ef-switch.checked .ef-switch-thumb { background: #ffffff; }
:global(html.kikoerumanager-dark) .ef-switch.checked .ef-switch-thumb { background: #111827; }

/* ============================================================
 * 侧边栏按钮（应用防闪烁规则）
 * ============================================================ */
.sidebar-actions {
  margin-top: 14px;
  display: grid;
  gap: 8px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.action-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 2px 4px;
  color: var(--ef-muted);
  font-size: 11px;
  font-weight: 850;
}
.side-ep-action {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--ef-border-soft);
  border-radius: 13px;
  background: var(--ef-surface);
  color: var(--ef-text-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 12px;
  font-weight: 800;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  box-shadow: none;
  transition:
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1),
    background-color 0.25s ease,
    border-color 0.25s ease,
    color 0.25s ease,
    opacity 0.25s ease;
}
.side-ep-action:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--ef-border-strong);
  background: var(--ef-surface);
  box-shadow: none;
}
.side-ep-action:active:not(:disabled) {
  transform: scale(0.96);
  transition: transform 0.12s ease;
}
.side-ep-action:disabled {
  background: #222328;
  border-color: rgba(255, 255, 255, 0.18);
  color: #e2e8f0;
  cursor: not-allowed;
  opacity: 1;
  box-shadow: none;
}
.side-ep-action.primary {
  background: var(--ef-accent-bg);
  border-color: var(--ef-accent-bg);
  color: var(--ef-accent-text);
  box-shadow: none;
}
.side-ep-action.primary:hover:not(:disabled) {
  background: var(--ef-accent-bg-hover);
  border-color: var(--ef-accent-bg-hover);
  box-shadow: none;
}
.side-ep-action.accent {
  background: var(--ef-accent-bg);
  border-color: var(--ef-accent-bg);
  color: var(--ef-accent-text);
}
.side-ep-action.accent:hover:not(:disabled) {
  background: var(--ef-accent-bg-hover);
  border-color: var(--ef-accent-bg-hover);
}
.side-ep-action.primary:disabled {
  background: #2f3036;
  border-color: rgba(255, 255, 255, 0.2);
  color: #f8fafc;
  box-shadow: none;
}
.side-ep-action.accent:disabled {
  background: #2f3036;
  border-color: rgba(255, 255, 255, 0.2);
  color: #f8fafc;
  box-shadow: none;
}
.side-ep-action:disabled svg,
.side-ep-action:disabled .side-button-icon {
  color: currentColor;
  stroke: currentColor;
  opacity: 0.92;
}
.side-button-icon-wrap {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  display: inline-grid;
  place-items: center;
}
.side-button-icon {
  transition: transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.25s ease;
}
.side-ep-action:hover:not(:disabled) .side-button-icon { transform: rotate(-8deg) scale(1.08); }
.side-ep-action :deep(.stateful-button__label) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 0;
}
.side-action-label { min-width: 0; white-space: nowrap; }
.side-action-count {
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  display: inline-grid;
  place-items: center;
  background: color-mix(in srgb, currentColor 12%, transparent);
  color: currentColor;
  font-size: 11px;
  font-weight: 900;
  line-height: 1;
}

/* ============================================================
 * 主区：扫描横幅 + 文件夹网格
 * ============================================================ */
.folders-card { padding: 16px; min-height: 420px; }
.scan-banner { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; padding: 12px; border-radius: 14px; background: var(--ef-surface-soft); border: 1px dashed var(--ef-border-strong); }
.scan-title { font-weight: 900; font-size: 13px; }
.scan-desc { color: var(--ef-muted); font-size: 12px; margin-top: 2px; }
.folder-bulkbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  padding: 10px 12px;
  border: 1px solid var(--ef-border);
  border-radius: 14px;
  background: var(--ef-surface-soft);
}
.folder-bulkbar-copy {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: var(--ef-muted);
  font-size: 12px;
  line-height: 1.4;
}
.folder-bulkbar-copy strong {
  color: var(--ef-text);
  font-size: 18px;
  font-weight: 950;
  font-variant-numeric: tabular-nums;
}
.folder-bulkbar-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
.bulk-action {
  height: 32px;
  border: 1px solid var(--ef-border-soft);
  border-radius: 10px;
  background: var(--ef-surface);
  color: var(--ef-text-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 850;
  white-space: nowrap;
  cursor: pointer;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.25s ease, background-color 0.25s ease, color 0.25s ease;
}
.bulk-action:hover:not(:disabled) {
  transform: translateY(-2px) scale(1.02);
  border-color: var(--ef-border-strong);
  background: var(--ef-surface);
}
.bulk-action:active:not(:disabled) { transform: scale(0.96); transition: transform 0.12s ease; }
.bulk-action:disabled {
  background: #222328;
  border-color: rgba(255, 255, 255, 0.18);
  color: #e2e8f0;
  opacity: 1;
  cursor: not-allowed;
}
.bulk-action.primary {
  background: var(--ef-accent-bg);
  border-color: var(--ef-accent-bg);
  color: var(--ef-accent-text);
}
.bulk-action.primary:hover:not(:disabled) {
  background: var(--ef-accent-bg-hover);
  border-color: var(--ef-accent-bg-hover);
}
.bulk-action.primary:disabled {
  background: #2f3036;
  border-color: rgba(255, 255, 255, 0.2);
  color: #f8fafc;
}
.bulk-action:disabled svg,
.bulk-action:disabled .bulk-action-icon {
  color: currentColor;
  stroke: currentColor;
  opacity: 0.92;
}
.bulk-action:hover:not(:disabled) svg,
.bulk-action:hover:not(:disabled) .bulk-action-icon {
  transform: rotate(-8deg) scale(1.08);
}
.bulk-action svg,
.bulk-action-icon {
  flex: 0 0 auto;
  transition: transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.folder-virtual-scroll {
  height: clamp(520px, 68vh, 880px);
  overflow: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
}
.folder-virtual-canvas {
  position: relative;
  width: 100%;
}
.folder-virtual-row {
  position: absolute;
  inset: 0 0 auto 0;
  display: grid;
  gap: 13px;
  align-items: start;
  will-change: transform;
}
.folder-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 13px; }
.folder-card { border: 1px solid var(--ef-border); border-radius: 16px; padding: 14px; background: var(--ef-surface); transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.25s ease, background-color 0.25s ease; }
.folder-card:hover { transform: translateY(-3px); box-shadow: var(--ef-shadow-hover); border-color: var(--ef-border-strong); }
.folder-card.selected { border-color: var(--ef-primary); box-shadow: inset 0 0 0 1px var(--ef-primary), var(--ef-shadow); }
.folder-card.conflict { background: var(--ef-conflict-bg); border-color: var(--ef-conflict-border); }
.folder-card.conflict.selected { border-color: var(--ef-conflict-text); box-shadow: inset 0 0 0 1px var(--ef-conflict-text), var(--ef-shadow); }
.folder-card.unrecognized {
  background: var(--ef-surface);
  border-style: dashed;
  border-color: var(--ef-border);
}
.folder-card.unrecognized:hover {
  background: var(--ef-surface);
  border-color: var(--ef-border-strong);
}

/* select-toggle 选择按钮：防闪烁 + 平滑 */
.select-toggle { width: 26px; height: 26px; border-radius: 8px; border: 1px solid var(--ef-border-strong); background: var(--ef-surface); color: var(--ef-faint); display: grid; place-items: center; flex: 0 0 auto; cursor: pointer; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, box-shadow 0.25s ease; }
.select-toggle:hover { border-color: var(--ef-primary); color: var(--ef-primary); background: var(--ef-surface-soft); transform: scale(1.06); }
.select-toggle:active { transform: scale(0.92); transition: transform 0.1s ease; }
.select-toggle.active { background: var(--ef-primary); color: var(--ef-surface); border-color: var(--ef-primary); box-shadow: 0 4px 10px rgba(15,23,42,0.2); }
.select-toggle.active:hover { background: var(--ef-primary-hover); }
.select-toggle:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }

.folder-main-info { min-width: 0; flex: 1; }
.folder-name-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.folder-name { min-width: 0; color: var(--ef-text); font-weight: 900; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.folder-depth-chip { flex: 0 0 auto; height: 20px; display: inline-flex; align-items: center; padding: 0 7px; border-radius: 999px; border: 1px solid var(--ef-border); background: var(--ef-surface-muted); color: var(--ef-muted); font-size: 10.5px; font-weight: 700; }
.folder-path { margin-top: 3px; color: var(--ef-faint); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.folder-root { margin-top: 4px; color: var(--ef-muted); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* status-pill：和 lib-chip 一致的视觉规范 */
.status-pill { height: 22px; border-radius: 999px; display: inline-flex; align-items: center; gap: 4px; padding: 0 9px; font-size: 11px; font-weight: 600; white-space: nowrap; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1); }
.folder-card:hover .status-pill { transform: scale(1.04); }
.status-pill.success { background: rgba(16, 185, 129, 0.12); color: #059669; border: 1px solid rgba(16, 185, 129, 0.24); }
.status-pill.warning { background: var(--ef-warning-bg); color: var(--ef-warning-text); border: 1px solid var(--ef-warning-border); }
.status-pill.danger { background: var(--ef-danger-bg); color: var(--ef-danger-text); border: 1px solid var(--ef-danger-border); }
.status-pill.info { background: rgba(100, 116, 139, 0.12); color: var(--ef-text-soft); border: 1px solid rgba(100, 116, 139, 0.24); }
.status-pill.muted { background: var(--ef-surface-muted); color: var(--ef-muted); border: 1px solid var(--ef-border); }

.folder-meta-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.folder-meta { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; height: 22px; border-radius: 999px; background: var(--ef-surface-soft); border: 1px solid var(--ef-border-soft); padding: 0 8px; color: var(--ef-muted); font-size: 11px; font-weight: 500; transition: background-color 0.25s ease, border-color 0.25s ease; }
.folder-meta:hover { background: var(--ef-surface-muted); border-color: var(--ef-border-strong); }
.folder-meta.rj { color: var(--ef-text); font-weight: 700; font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.folder-meta.rj.missing { color: var(--ef-faint); }
.folder-meta.route { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-radius: 8px; }

.conflict-box { margin-top: 12px; display: flex; gap: 9px; padding: 10px; border-radius: 12px; background: var(--ef-conflict-bg); border: 1px solid var(--ef-conflict-border); color: var(--ef-conflict-text); }
.conflict-box.large { margin-top: 0; }
.conflict-title { font-size: 13px; font-weight: 900; }
.conflict-desc { margin-top: 2px; font-size: 12px; color: var(--ef-conflict-muted); }

/* ============================================================
 * 卡片操作按钮（防闪烁 + 微动效）
 * ============================================================ */
.folder-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.card-action {
  height: 28px;
  border: 1px solid var(--ef-border-soft);
  border-radius: 8px;
  background: var(--ef-surface);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 10px;
  color: var(--ef-muted);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, opacity 0.2s ease;
  will-change: transform;
}
.card-action:hover { transform: translateY(-1px) scale(1.03); background: var(--ef-surface-soft); border-color: var(--ef-border-strong); box-shadow: var(--ef-shadow); }
.card-action:active:not(:disabled) { transform: scale(0.96); transition: transform 0.12s ease; }
.card-action:disabled {
  background: #222328;
  border-color: rgba(255, 255, 255, 0.18);
  color: #e2e8f0;
  opacity: 1;
  cursor: not-allowed;
}
.card-action.primary { background: var(--ef-primary); color: var(--ef-surface); border-color: var(--ef-primary); box-shadow: var(--ef-shadow); }
.card-action.primary:hover { background: var(--ef-primary-hover); box-shadow: var(--ef-shadow-hover); }
.card-action.primary:disabled {
  background: #2f3036;
  border-color: rgba(255, 255, 255, 0.2);
  color: #f8fafc;
  box-shadow: none;
}
.card-action.warning { background: var(--ef-warning-bg); color: var(--ef-warning-text); border-color: var(--ef-warning-border); }
.card-action.warning:hover { background: var(--ef-warning-bg-hover); border-color: var(--ef-warning-border); }
.card-action.danger { background: var(--ef-surface); color: var(--ef-danger-text); border-color: var(--ef-danger-border); }
.card-action.danger:hover { background: var(--ef-danger-bg); border-color: var(--ef-danger-border); box-shadow: 0 4px 10px rgba(220,38,38,0.12); }
.card-action:disabled svg,
.card-action:disabled .card-action-icon {
  color: currentColor;
  stroke: currentColor;
  opacity: 0.92;
}
.card-action-icon {
  flex: 0 0 auto;
  transition: transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.2s ease;
}

/* ============================================================
 * 进出过渡：section / 网格 / 卡片
 * ============================================================ */
.ef-section-enter-active {
  transition:
    opacity 0.4s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.45s cubic-bezier(0.34, 1.56, 0.64, 1),
    max-height 0.5s cubic-bezier(0.22, 1, 0.36, 1);
  overflow: hidden;
}
.ef-section-leave-active {
  transition: opacity 0.22s ease, transform 0.28s ease, max-height 0.3s cubic-bezier(0.4, 0, 0.6, 1);
  overflow: hidden;
}
.ef-section-enter-from { opacity: 0; transform: translateY(-10px) scale(0.99); }
.ef-section-leave-to   { opacity: 0; transform: translateY(-6px) scale(0.99); }

.ef-grid-enter-active {
  transition:
    opacity 0.45s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.55s cubic-bezier(0.34, 1.56, 0.64, 1);
  transition-delay: var(--ef-grid-delay, 0ms);
}
.ef-grid-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
  position: absolute;
}
.ef-grid-enter-from { opacity: 0; transform: translateY(20px) scale(0.94); }
.ef-grid-leave-to   { opacity: 0; transform: translateY(-10px) scale(0.96); }
.ef-grid-move { transition: transform 0.45s cubic-bezier(0.22, 1, 0.36, 1); }
.ef-result-dialog-enter-active,
.ef-result-dialog-leave-active {
  transition: opacity 0.22s ease;
}
.ef-result-dialog-enter-active .ef-result-dialog,
.ef-result-dialog-leave-active .ef-result-dialog {
  transition: transform 0.26s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease;
}
.ef-result-dialog-enter-from,
.ef-result-dialog-leave-to {
  opacity: 0;
}
.ef-result-dialog-enter-from .ef-result-dialog,
.ef-result-dialog-leave-to .ef-result-dialog {
  opacity: 0;
  transform: translateY(8px) scale(0.985);
}
.ef-result-overlay {
  position: fixed;
  inset: 0;
  z-index: 3600;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.48);
}
.ef-result-dialog {
  width: min(560px, calc(100vw - 32px));
  max-height: min(82vh, 680px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 22px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(248, 250, 252, 0.9)),
    var(--ef-surface);
  box-shadow: 0 28px 76px rgba(15, 23, 42, 0.22), 0 10px 26px rgba(15, 23, 42, 0.1);
}
.ef-result-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 20px 20px 16px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}
.ef-result-body {
  min-height: 0;
  overflow: auto;
  padding: 16px 20px;
}
.ef-result-footer {
  flex: 0 0 auto;
  padding: 0 20px 20px;
}
.ef-result-dialog :is(button, [tabindex]):focus,
.ef-result-dialog :is(button, [tabindex]):focus-visible,
.ef-result-dialog :focus-within {
  outline: none !important;
  box-shadow: none;
}
.dialog-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.dialog-title-wrap { display: flex; align-items: center; gap: 12px; }
.dialog-icon { width: 38px; height: 38px; border-radius: 14px; display: grid; place-items: center; }
.dialog-icon.success { background: var(--ef-success-bg); color: var(--ef-success-text); } .dialog-icon.warning { background: var(--ef-warning-bg); color: var(--ef-warning-text); }
.dialog-title { color: var(--ef-text); font-size: 17px; font-weight: 900; letter-spacing: -.03em; }
.dialog-subtitle { margin-top: 3px; color: var(--ef-muted); font-size: 12px; }
/* ============================================================
 * 对话框：标题 / 关闭按钮 / 结果面板 / 任务列表 / 解决方案选项
 *  - 所有交互元素加防闪烁规则（hover 不依赖 :not(:disabled)）
 * ============================================================ */
.dialog-close {
  width: 32px; height: 32px;
  border: 1px solid var(--ef-border);
  border-radius: 10px;
  background: var(--ef-surface);
  color: var(--ef-faint);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.25s ease, border-color 0.25s ease, background-color 0.25s ease, box-shadow 0.25s ease;
}
.dialog-close:hover { color: var(--ef-text); border-color: var(--ef-border-strong); background: var(--ef-surface-soft); transform: scale(1.06) rotate(90deg); }
.dialog-close:active { transform: scale(0.92) rotate(90deg); transition: transform 0.1s ease; }

.result-panel { padding: 14px; border-radius: 14px; margin-bottom: 12px; border: 1px solid; }
.result-panel.success { background: var(--ef-success-bg); color: var(--ef-success-text); border-color: var(--ef-success-border); }
.result-panel.warning { background: var(--ef-warning-bg); color: var(--ef-warning-text); border-color: var(--ef-warning-border); }
.result-title { font-weight: 900; }
.result-message { font-size: 13px; margin-top: 4px; line-height: 1.6; }
.task-list, .duplicate-panel { display: grid; gap: 10px; }
.duplicate-detail-dialog :deep(.el-dialog) {
  border-radius: 22px;
  overflow: hidden;
  background: var(--ef-surface);
  border: 1px solid var(--ef-border);
  box-shadow: 0 24px 70px rgba(15,23,42,.2);
}
.duplicate-detail-dialog :deep(.el-dialog__header) { margin: 0; padding: 18px 18px 0; }
.duplicate-detail-dialog :deep(.el-dialog__body) { padding: 14px 18px; max-height: min(68vh, 720px); overflow: auto; }
.duplicate-detail-dialog :deep(.el-dialog__footer) { padding: 0 18px 18px; }
.duplicate-dialog-header { align-items: center; }
.duplicate-alert { align-items: flex-start; }
.duplicate-compare-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
}
.duplicate-side-card {
  min-width: 0;
  display: grid;
  gap: 9px;
  padding: 14px;
  border: 1px solid var(--ef-border);
  border-radius: 16px;
  background: var(--ef-surface);
  transition: border-color 0.25s ease, background-color 0.25s ease, transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.duplicate-side-card:hover {
  border-color: var(--ef-border-strong);
  background: var(--ef-surface);
  transform: translateY(-1px);
}
.duplicate-side-card.current { border-left: 3px solid #0ea5e9; }
.duplicate-side-card.library { border-left: 3px solid #f59e0b; }
.duplicate-side-head {
  display: grid;
  gap: 7px;
  min-width: 0;
}
.duplicate-side-head strong {
  color: var(--ef-text);
  font-size: 14px;
  line-height: 1.45;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.duplicate-side-badge {
  width: fit-content;
  height: 22px;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  border-radius: 999px;
  color: var(--ef-text-soft);
  background: var(--ef-surface-soft);
  border: 1px solid var(--ef-border);
  font-size: 11px;
  font-weight: 900;
}
.duplicate-rj-line {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.duplicate-rj-line span {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  border-radius: 999px;
  background: var(--ef-surface-soft);
  border: 1px solid var(--ef-border);
  color: var(--ef-text-soft);
  font-size: 12px;
  font-weight: 800;
}
.duplicate-metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.duplicate-metric {
  min-width: 0;
  padding: 9px 10px;
  border-radius: 12px;
  background: var(--ef-surface-soft);
  border: 1px solid var(--ef-border-soft);
}
.duplicate-metric span,
.duplicate-diff-item span {
  display: block;
  color: var(--ef-muted);
  font-size: 11px;
  font-weight: 700;
}
.duplicate-metric strong,
.duplicate-diff-item strong {
  display: block;
  margin-top: 4px;
  color: var(--ef-text);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.35;
  word-break: break-word;
}
.duplicate-metric strong.positive,
.duplicate-diff-item strong.positive { color: var(--ef-positive-text); }
.duplicate-metric strong.negative,
.duplicate-diff-item strong.negative { color: var(--ef-negative-text); }
.duplicate-metric strong.neutral,
.duplicate-diff-item strong.neutral { color: var(--ef-text-soft); }
.duplicate-path {
  color: var(--ef-muted);
  font-size: 12px;
  line-height: 1.55;
  word-break: break-all;
  border-top: 1px dashed var(--ef-border);
  padding-top: 9px;
}
.duplicate-diff-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.duplicate-diff-item {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--ef-border);
  border-radius: 14px;
  background: var(--ef-surface-soft);
}
.duplicate-footer { width: 100%; }
.task-list-title { color: var(--ef-text); font-size: 12px; font-weight: 900; }
.task-list-scroll {
  display: grid;
  gap: 8px;
  max-height: min(280px, 42vh);
  overflow: auto;
  padding-right: 2px;
}
.task-row, .linked-row { display: grid; grid-template-columns: 92px 1fr auto; gap: 10px; align-items: center; padding: 10px 12px; border-radius: 12px; background: var(--ef-surface-soft); border: 1px solid var(--ef-border); color: var(--ef-muted); font-size: 12px; transition: border-color 0.25s ease, background-color 0.25s ease; }
.task-row:hover, .linked-row:hover { border-color: var(--ef-border-strong); background: var(--ef-surface-hover); }
.task-id { font-weight: 900; color: var(--ef-text); font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.task-path { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-status { height: 22px; border-radius: 999px; display: inline-flex; align-items: center; padding: 0 9px; background: var(--ef-surface-muted); color: var(--ef-text-soft); border: 1px solid var(--ef-border); font-size: 11px; font-weight: 600; }

.dialog-footer { display: flex; justify-content: flex-end; gap: 9px; }
.dialog-ep-btn { height: 34px; border: 1px solid var(--ef-border-soft); border-radius: 10px; background: var(--ef-surface); color: var(--ef-muted); padding: 0 14px; font-weight: 700; cursor: pointer; transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, opacity 0.25s ease, background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease; }
.dialog-ep-btn:hover { transform: translateY(-2px) scale(1.02); }
.dialog-ep-btn:active { transform: scale(0.96); transition: transform 0.12s ease; }
.dialog-ep-btn.primary { background: #111827; border-color: #111827; color: #fff; box-shadow: 0 6px 14px rgba(15,23,42,0.18); }
.dialog-ep-btn.primary:hover { box-shadow: 0 10px 22px rgba(15,23,42,0.26); }

.detail-card { border: 1px solid var(--ef-border); border-radius: 14px; padding: 12px; background: var(--ef-surface-soft); transition: border-color 0.25s ease, background-color 0.25s ease; }
.detail-card:hover { border-color: var(--ef-border-strong); background: var(--ef-surface-hover); }
.detail-title { font-weight: 900; margin-bottom: 8px; }
.detail-line { font-size: 12px; color: var(--ef-muted); line-height: 1.7; word-break: break-all; }

/* 解决方案选项卡：选中状态加 ring + 推荐项 emerald 高亮 */
.resolution-list { display: grid; gap: 9px; }
.resolution-option {
  text-align: left;
  border: 1px solid var(--ef-border);
  border-radius: 14px;
  padding: 12px;
  background: var(--ef-surface-soft);
  display: grid;
  gap: 4px;
  cursor: pointer;
  transition:
    transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
    box-shadow 0.25s ease,
    border-color 0.25s ease,
    background-color 0.25s ease;
}
.resolution-option:hover { transform: translateY(-1px); border-color: var(--ef-border-strong); box-shadow: var(--ef-shadow); }
.resolution-option:active { transform: scale(0.99); transition: transform 0.1s ease; }
.resolution-option.active {
  border-color: var(--ef-primary);
  box-shadow: inset 0 0 0 1px var(--ef-primary), var(--ef-shadow);
  background: var(--ef-surface);
}
.resolution-option.recommend { background: var(--ef-recommend-bg); border-color: var(--ef-recommend-border); }
.resolution-option.recommend.active { border-color: var(--ef-recommend-active); box-shadow: inset 0 0 0 1px var(--ef-recommend-active), 0 6px 14px rgba(5,150,105,0.12); }
.resolution-title { font-weight: 900; color: var(--ef-text); }
.resolution-desc { color: var(--ef-muted); font-size: 12px; }

/* 冲突详情对话框页脚按钮 */
.dialog-btn {
  height: 34px;
  border: 1px solid var(--ef-border-soft);
  border-radius: 10px;
  background: var(--ef-surface);
  padding: 0 14px;
  font-weight: 700;
  color: var(--ef-muted);
  font-size: 13px;
  cursor: pointer;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, opacity 0.25s ease;
}
.dialog-btn:hover { transform: translateY(-2px) scale(1.02); background: var(--ef-surface-soft); border-color: var(--ef-border-strong); box-shadow: var(--ef-shadow); }
.dialog-btn:active { transform: scale(0.96); transition: transform 0.12s ease; }
.dialog-btn:disabled { opacity: 0.65; cursor: not-allowed; }
.dialog-btn.primary { background: var(--ef-primary); color: var(--ef-surface); border-color: var(--ef-primary); box-shadow: var(--ef-shadow); }
.dialog-btn.primary:hover { background: var(--ef-primary-hover); border-color: var(--ef-primary-hover); box-shadow: var(--ef-shadow-hover); }

/* lucide animate-spin 全局已存在（Tailwind utility），此处保留兼容 */
.animate-spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 980px) {
  .existing-shell { grid-template-columns: 1fr; }
  .sidebar-card { position: static; }
  .hero-search-wrap { width: 100%; }
}

/* 手机 ≤640 紧凑边距 + 内部按钮收紧 */
@media (max-width: 640px) {
  .existing-page { padding-left: 10px; padding-right: 10px; }
  .existing-shell { gap: 12px; margin-top: 12px; }
  .sidebar-card { padding: 12px; border-radius: 14px; }
  .ef-head-btn { height: 32px; padding: 0 10px; }
  .ef-head-btn-label { font-size: 12px; }
  .duplicate-detail-dialog :deep(.el-dialog__body) {
    max-height: calc(100vh - 132px);
    padding: 12px;
  }
  .duplicate-detail-dialog :deep(.el-dialog__header),
  .duplicate-detail-dialog :deep(.el-dialog__footer) {
    padding-left: 12px;
    padding-right: 12px;
  }
  .ef-result-overlay {
    align-items: flex-end;
    padding: 12px;
  }
  .ef-result-dialog {
    width: 100%;
    max-height: calc(100dvh - 24px);
    border-radius: 18px;
  }
  .ef-result-header,
  .ef-result-body,
  .ef-result-footer {
    padding-left: 14px;
    padding-right: 14px;
  }
  .task-row {
    grid-template-columns: 78px minmax(0, 1fr);
  }
  .task-status {
    grid-column: 1 / -1;
    width: fit-content;
  }
  .ef-result-footer {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .duplicate-compare-grid,
  .duplicate-diff-strip {
    grid-template-columns: 1fr;
  }
  .folder-bulkbar {
    align-items: stretch;
    flex-direction: column;
  }
  .folder-bulkbar-actions {
    width: 100%;
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .folder-bulkbar-actions .bulk-action.primary {
    grid-column: 1 / -1;
  }
  .duplicate-metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .duplicate-side-head strong {
    white-space: normal;
  }
  /* sidebar 内的 actions row 改为 2 列等分 */
  .sidebar-actions {
    display: grid !important;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }
  .action-summary { grid-column: 1 / -1; }
}

:global(html.kikoerumanager-dark) .ef-result-overlay,
:global(html.dark) .ef-result-overlay {
  background: rgba(0, 0, 0, 0.52);
}

:global(html.kikoerumanager-dark) .ef-result-dialog,
:global(html.dark) .ef-result-dialog {
  border-color: rgba(148, 163, 184, 0.2);
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(2, 6, 23, 0.94)),
    var(--km-dark-card);
  box-shadow: 0 28px 76px rgba(0, 0, 0, 0.42), 0 10px 26px rgba(0, 0, 0, 0.26);
}

:global(html.kikoerumanager-dark) .ef-result-header,
:global(html.dark) .ef-result-header {
  border-bottom-color: rgba(148, 163, 184, 0.16);
}
</style>
