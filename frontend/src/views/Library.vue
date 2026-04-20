<template>
  <div
    class="library library-page-loading-shell"
    v-app-loading="{ loading, text: '正在刷新库存内容...', description: '同步目录、搜索结果和当前作用域', size: 176, minHeight: 360, delay: 0, minVisible: 360, maskClass: 'library-page-loading-mask' }"
  >
    <h1 class="page-title">{{ labels.pageTitle }}</h1>

    <div class="summary-grid">
      <el-card shadow="never" class="summary-card">
        <template #header>{{ labels.currentLibrary }}</template>
        <div class="summary-value">{{ currentLibrary?.name || '-' }}</div>
        <div class="summary-meta">{{ currentLibraryTypeLabel }}</div>
        <div class="summary-meta path-text">{{ currentLibrary?.path || '-' }}</div>
        <div class="summary-tags" v-if="currentLibrary">
          <el-tag size="small" :type="isRemoteCurrentLibrary ? 'warning' : 'success'">{{ currentLibraryScopeLabel }}</el-tag>
          <el-tag size="small" :type="healthTagType(currentLibrary.health?.status)">{{ healthStatusLabel(currentLibrary.health?.status) }}</el-tag>
        </div>
        <div class="summary-caption">{{ healthDetailText(currentLibrary?.health) }}</div>
      </el-card>

      <el-card shadow="never" class="summary-card">
        <template #header>{{ labels.currentLibraryStats }}</template>
        <div class="summary-value">{{ statsSizeCardText(currentStats) }}</div>
        <div v-if="showCurrentStatsProgress" class="summary-progress">
          <el-progress :percentage="currentStatsProgress" :stroke-width="8" :show-text="false" />
        </div>
        <div class="summary-caption">{{ statsStatusCardText(currentStats) }}</div>
      </el-card>

      <el-card shadow="never" class="summary-card">
        <template #header>{{ labels.allLibraries }}</template>
        <div class="summary-value">{{ aggregateSizeText }}</div>
        <div v-if="showAggregateProgress" class="summary-progress">
          <el-progress :percentage="aggregateProgress" :stroke-width="8" :show-text="false" />
        </div>
        <div class="summary-caption">{{ aggregateSummary }}</div>
        <div class="summary-caption" v-if="aggregateDetail">{{ aggregateDetail }}</div>
      </el-card>
    </div>

    <el-card shadow="never" class="main-card">
      <template #header>
        <div class="card-header">
          <span class="header-title">库内文件列表</span>
          <div class="header-actions">
            <el-select v-model="selectedLibraryId" style="width: 240px">
              <el-option v-for="library in libraries" :key="library.id" :label="library.name" :value="library.id">
                <div class="library-option">
                  <span>{{ library.name }}</span>
                  <el-tag size="small" :type="library.type === 'synology_filestation' ? 'warning' : 'success'">
                    {{ library.type === 'synology_filestation' ? '远程' : '本地' }}
                  </el-tag>
                </div>
              </el-option>
            </el-select>
            <el-button
              class="toolbar-action-btn toolbar-refresh-btn"
              :class="{ 'is-refreshing': isRefreshingCurrentView }"
              :disabled="isRefreshingCurrentView"
              @click="refreshCurrentView"
            >
              <span class="toolbar-refresh-content">
                <el-icon class="toolbar-refresh-icon"><Refresh /></el-icon>
                <span class="toolbar-refresh-label">{{ isRefreshingCurrentView ? '刷新中' : '刷新' }}</span>
              </span>
            </el-button>
            <el-button class="toolbar-tight-btn" :loading="statsLoading" @click="handleStatsAction">{{ canCancelStats ? '取消统计' : '刷新统计' }}</el-button>
            <el-button class="toolbar-tight-btn" @click="toggleAllSelection">{{ isAllSelected ? '取消全选' : '全选' }}</el-button>
            <el-input v-model="searchQuery" clearable placeholder="搜索文件名或RJ号" style="width: 250px" @keyup.enter="handleSearch" @clear="handleSearch">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-select v-model="searchResultKind" style="width: 112px">
              <el-option label="全部" value="all" />
              <el-option label="文件夹" value="folder" />
              <el-option label="文件" value="file" />
            </el-select>
            <AppLottieSwitch v-model="searchExact" :show-text="true" active-text="精确" inactive-text="模糊" />
            <el-button class="toolbar-action-btn" type="primary" plain @click="handleSearch">查询</el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="currentLibrary?.health?.warnings?.length || currentLibrary?.health?.errors?.length"
        :title="healthDetailText(currentLibrary?.health)"
        :type="currentLibrary?.health?.errors?.length ? 'error' : 'warning'"
        :closable="false"
        show-icon
        style="margin-bottom: 14px"
      />

        <div class="path-toolbar">
        <div class="path-toolbar-left">
          <el-button size="small" :disabled="!canGoParent" @click="goToParent">{{ backButtonLabel }}</el-button>
          <span class="path-label">当前层级</span>
          <code class="path-code">{{ currentPathDisplay }}</code>
        </div>
        <div class="path-toolbar-right">
          <div class="toolbar-scope-toggle" role="tablist" aria-label="工具栏作用范围">
            <button
              type="button"
              class="toolbar-scope-option"
              :class="{ 'is-active': toolbarActionScope === 'page' }"
              :aria-pressed="toolbarActionScope === 'page'"
              @click="toolbarActionScope = 'page'"
            >
              当前页
            </button>
            <button
              type="button"
              class="toolbar-scope-option"
              :class="{ 'is-active': toolbarActionScope === 'all' }"
              :aria-pressed="toolbarActionScope === 'all'"
              @click="toolbarActionScope = 'all'"
            >
              当前目录
            </button>
          </div>
          <el-button
            class="toolbar-utility-btn toolbar-utility-btn-danger"
            size="small"
            type="danger"
            plain
            :disabled="!canFilterDeleteCurrentFolder"
            @click="openFilterDeleteDialog"
          >
            {{ toolbarActionScope === 'page' ? '当前页删过滤' : '删除过滤文件' }}
          </el-button>
          <el-button
            class="toolbar-utility-btn toolbar-utility-btn-primary"
            size="small"
            type="success"
            plain
            :disabled="!canProcessCurrentFolder"
            @click="startCurrentFolderRJSubtitle"
          >
            {{ toolbarActionScope === 'page' ? '当前页抓字幕' : '当前目录抓字幕' }}
          </el-button>
          <el-button
            v-if="!isRemoteCurrentLibrary"
            class="toolbar-utility-btn toolbar-utility-btn-neutral"
            size="small"
            plain
            :disabled="selectedUploadCount === 0 || !hasRemoteUploadLibraries"
            @click="openLocalUploadDialog"
          >
            上传到服务器
          </el-button>
          <el-button class="toolbar-utility-btn toolbar-utility-btn-neutral" size="small" plain @click="openSubtitleTaskPanel">
            字幕任务面板
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="librarySearchState.active"
        :title="librarySearchSummary"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 14px"
      />

      <el-table
        :key="libraryTableKey"
        ref="tableRef"
        :data="files"
        :row-key="libraryRowKey"
        :row-class-name="libraryRowClassName"
        empty-text="暂无文件"
        @selection-change="handleSelectionChange"
        @sort-change="handleSortChange"
      >
        <el-table-column type="selection" width="55" :selectable="isLibraryRowSelectable" />
        <el-table-column prop="name" label="文件名" sortable="custom" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="file-cell">
              <div class="file-main-line">
                <el-icon class="file-icon"><Folder v-if="row.is_directory" /><Files v-else /></el-icon>
                <button v-if="isSearchResultRow(row)" type="button" class="file-link-btn" @click="locateLibrarySearchResult(row)" v-html="renderLibrarySearchHighlight(row.name)"></button>
                <button v-else-if="row.is_directory" type="button" class="file-link-btn" @click="openFolder(row)" v-html="renderLibrarySearchHighlight(row.name)"></button>
                <span v-else class="file-name" v-html="renderLibrarySearchHighlight(row.name)"></span>
              </div>
              <div v-if="isSearchResultRow(row) && getSearchResultLibraryLabel(row)" class="search-result-library">
                来源库：{{ getSearchResultLibraryLabel(row) }}
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="rjcode" label="RJ 号" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.rjcode" size="small" type="primary" effect="light">{{ row.rjcode }}</el-tag>
            <span v-else class="empty-text">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="size" label="大小" sortable="custom" width="120">
          <template #default="{ row }">{{ formatRowSize(row) }}</template>
        </el-table-column>
        <el-table-column prop="modified_time" label="时间" sortable="custom" width="180">
          <template #default="{ row }">{{ formatDate(row.unzip_time || row.modified_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <div class="action-grid">
              <div class="action-row">
                <template v-if="!isRemoteCurrentLibrary">
                  <el-button size="small" plain class="action-btn action-btn-open" @click="openFolder(row)">打开</el-button>
                  <el-button size="small" plain class="action-btn action-btn-direct" @click="openFolderDirect(row)">直接打开</el-button>
                </template>
                <template v-else>
                  <el-button size="small" plain class="action-btn action-btn-rename" :disabled="!isWritableCurrentLibrary || apiRenameBusy" @click="renameItem(row)">重命名</el-button>
                  <el-button
                    size="small"
                    plain
                    class="action-btn action-btn-api"
                    :class="{ 'is-batch-target': isBatchApiRenameTarget(row) }"
                    :disabled="!row.is_directory || apiRenameBusy"
                    :loading="apiRenamingId === row.id || isBatchApiRenameRunning(row)"
                    @click="apiRenameItem(row)"
                  >
                    API 重命名
                  </el-button>
                </template>
              </div>
              <div class="action-row" v-if="!isRemoteCurrentLibrary">
                <el-button size="small" plain class="action-btn action-btn-rename" :disabled="!isWritableCurrentLibrary || apiRenameBusy" @click="renameItem(row)">重命名</el-button>
                <el-button
                  size="small"
                  plain
                  class="action-btn action-btn-api"
                  :class="{ 'is-batch-target': isBatchApiRenameTarget(row) }"
                  :disabled="!row.is_directory || apiRenameBusy"
                  :loading="apiRenamingId === row.id || isBatchApiRenameRunning(row)"
                  @click="apiRenameItem(row)"
                >
                  API 重命名
                </el-button>
              </div>
              <div class="action-row">
                <el-button
                  v-if="isSearchResultRow(row) && !row.is_directory"
                  size="small"
                  plain
                  class="action-btn action-btn-open"
                  @click="locateLibrarySearchResult(row)"
                >
                  定位
                </el-button>
                <el-button
                  size="small"
                  plain
                  class="action-btn action-btn-subtitle"
                  :disabled="!canFetchRJSubtitle(row)"
                  @click="startSingleRJSubtitle(toRJSubtitleItem(row))"
                >
                  识别抓字幕
                </el-button>
                <el-button size="small" plain class="action-btn action-btn-manage" :disabled="!row.is_directory" @click="openFolderContentsDialog(row)">文件管理</el-button>
                <el-button size="small" plain class="action-btn action-btn-delete" :disabled="!isWritableCurrentLibrary" @click="deleteItem(row)">删除</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="batch-bar" v-if="selectedRows.length">
        <span class="selected-count">已选择 {{ selectedRows.length }} 项</span>
        <div class="batch-actions">
          <el-button
            class="batch-action-btn batch-action-btn-primary"
            size="small"
            type="success"
            plain
            :disabled="!selectedSubtitleCandidates.length"
            :loading="subtitleSubmitting"
            @click="openRJSubtitleDialog(selectedSubtitleCandidates)"
          >
            <el-icon><Tickets /></el-icon>批量抓字幕
          </el-button>
          <el-button
            class="batch-action-btn batch-action-btn-danger"
            size="small"
            type="danger"
            plain
            :disabled="!selectedFilterDeleteRows.length || !isWritableCurrentLibrary"
            @click="openSelectedFilterDeleteDialog"
          >
            <AppLottieIcon :src="deleteIconAnimation" :size="32" tone="danger" />
            <span>批量删过滤预审</span>
          </el-button>
          <el-button
            v-if="!isRemoteCurrentLibrary"
            class="batch-action-btn batch-action-btn-neutral"
            size="small"
            plain
            :disabled="selectedUploadCount === 0 || !hasRemoteUploadLibraries"
            :loading="localUploadSubmitting"
            @click="openLocalUploadDialog"
          >
            上传到服务器
          </el-button>
          <el-button class="batch-action-btn batch-action-btn-danger" size="small" type="danger" plain :disabled="!isWritableCurrentLibrary" :loading="batchDeleting" @click="handleBatchDelete"><AppLottieIcon :src="deleteIconAnimation" :size="32" tone="danger" :disabled="!isWritableCurrentLibrary" /><span>批量删除</span></el-button>
          <el-button class="batch-action-btn batch-action-btn-neutral" size="small" type="warning" plain :disabled="!selectedApiRenameRows.length || apiRenameBusy" :loading="batchRenaming" @click="handleBatchApiRename"><AppLottieIcon :src="clipboardIconAnimation" :size="40" tone="primary" :disabled="!selectedApiRenameRows.length || apiRenameBusy" /><span>批量 API重命名</span></el-button>
          <el-button class="batch-action-btn batch-action-btn-neutral" size="small" @click="clearSelection">取消选择</el-button>
        </div>
      </div>

      <div class="pagination-wrap">
        <el-pagination v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="PAGE_SIZES" :total="totalFiles" layout="total, sizes, prev, pager, next, jumper" background />
      </div>
    </el-card>

    <el-dialog v-model="renameDialogVisible" title="重命名" width="500px">
      <el-form :model="renameForm" label-width="80px">
        <el-form-item label="当前名称"><el-input v-model="renameForm.currentName" disabled /></el-form-item>
        <el-form-item label="新名称"><el-input v-model="renameForm.newName" placeholder="输入新名称" /></el-form-item>
        <el-form-item label="预览"><div class="name-preview">{{ renameForm.newName || renameForm.currentName }}</div></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isRenaming" @click="confirmRename">确认重命名</el-button>
      </template>
    </el-dialog>

    <ServerUploadPreviewDialog
      :visible="localUploadDialogVisible"
      :starting="localUploadSubmitting"
      title="上传到服务器"
      :source-library-id="selectedLibraryId"
      :source-library-name="currentLibrary?.name || ''"
      :source-items="selectedUploadSourceItems"
      :libraries="libraries"
      :initial-target-library-id="localUploadForm.targetLibraryId"
      :initial-target-subdir="localUploadForm.targetSubdir"
      @update:visible="value => localUploadDialogVisible = value"
      @submit="submitLocalUpload"
    />

    <UploadTaskWorkbenchDialog
      v-model:visible="uploadWorkbenchVisible"
      :tasks="trackedUploadTasks"
      :refreshing="uploadWorkbenchRefreshing"
      @refresh="refreshUploadWorkbench"
      @background="hideUploadWorkbenchToBackground"
      @close="closeUploadWorkbench"
    />

    <div v-if="showUploadBackgroundCard" class="subtitle-floating-card upload-floating-card">
      <div class="subtitle-floating-head">
        <div>
          <div class="subtitle-floating-title">上传任务正在后台运行</div>
          <div class="subtitle-floating-mode">
            {{ activeBackgroundUploadTask ? `${activeBackgroundUploadTask.work_title || activeBackgroundUploadTask.source_label || '-'} · ${getUploadBackgroundTargetLabel(activeBackgroundUploadTask)}` : '保留当前上传队列与进度状态' }}
          </div>
        </div>
        <div class="subtitle-floating-count">{{ uploadBackgroundPercent }}%</div>
      </div>
      <el-progress
        :percentage="uploadBackgroundPercent"
        :stroke-width="8"
        :show-text="false"
      />
      <div class="subtitle-floating-chip-row">
        <span class="subtitle-floating-chip">进行中 {{ processingUploadTasks.length }}</span>
        <span class="subtitle-floating-chip">等待中 {{ pendingUploadTasks.length }}</span>
        <span class="subtitle-floating-chip">完成 {{ completedUploadTasks.length }}</span>
        <span class="subtitle-floating-chip" :class="{ 'subtitle-mini-chip-danger': failedUploadTasks.length > 0 }">失败 {{ failedUploadTasks.length }}</span>
        <span class="subtitle-floating-chip">速度 {{ formatSpeed(getUploadBackgroundSpeed(activeBackgroundUploadTask)) }}</span>
        <span class="subtitle-floating-chip">剩余 {{ formatUploadBackgroundEta(activeBackgroundUploadTask) }}</span>
      </div>
      <div class="subtitle-floating-text">
        {{ activeBackgroundUploadTask?.current_step || '隐藏后继续保留上传队列和进度。' }}
      </div>
      <div class="subtitle-floating-actions">
        <el-button size="small" type="primary" @click="resumeUploadWorkbenchFromBackground">恢复工作台</el-button>
        <el-button size="small" @click="closeUploadWorkbench">关闭</el-button>
      </div>
    </div>

    <el-dialog
      v-model="subtitleDialogVisible"
      width="1560px"
      class="subtitle-task-dialog"
      :destroy-on-close="false"
      :close-on-click-modal="true"
      :close-on-press-escape="false"
      :show-close="false"
      :before-close="handleSubtitleDialogBeforeClose"
    >
      <template #header>
        <div class="subtitle-dialog-header">
          <div class="subtitle-dialog-title">RJ 字幕抓取</div>
          <div class="subtitle-dialog-header-actions">
            <el-button size="small" @click="hideSubtitleTaskPanelToBackground">隐藏到后台</el-button>
            <el-button size="small" @click="closeSubtitleTaskPanel">关闭</el-button>
          </div>
        </div>
      </template>
      <div class="subtitle-workbench">
        <section class="subtitle-hero">
          <div>
            <div class="subtitle-panel-title">库存内字幕工作台</div>
            <div class="subtitle-panel-desc">直接从库存目录识别 RJ 文件夹并创建字幕任务。扫描命中后会立即尝试入任务；已有字幕的目录会保留在左侧，方便直接进入字幕检查和匹配工作台。</div>
            <div class="subtitle-hero-meta">
              <span class="subtitle-hero-chip">扫描命中 {{ subtitleDialogSelection.length }}</span>
              <span class="subtitle-hero-chip" v-if="subtitleScanSession.existingSubtitles">已有字幕跳过 {{ subtitleScanSession.existingSubtitles }}</span>
              <span class="subtitle-hero-chip" v-if="subtitleScanSession.noSubtitleTargets">远程无字幕跳过 {{ subtitleScanSession.noSubtitleTargets }}</span>
              <span class="subtitle-hero-chip" v-if="subtitleScanSession.createdTasks">加入任务成功 {{ subtitleScanSession.createdTasks }}</span>
              <span class="subtitle-hero-chip" v-if="subtitleScanSession.existingTasks">任务已存在 {{ subtitleScanSession.existingTasks }}</span>
              <span class="subtitle-hero-chip" v-if="subtitleScanSession.createFailed">加入失败 {{ subtitleScanSession.createFailed }}</span>
              <button
                v-for="item in subtitleTaskOverview"
                :key="item.key"
                type="button"
                class="subtitle-hero-chip subtitle-hero-chip-button"
                :class="{ active: subtitleTaskFilter === item.key }"
                @click="setSubtitleTaskFilter(item.key)"
              >
                {{ item.label }} {{ item.value }}
              </button>
            </div>
          </div>
          <div class="subtitle-panel-actions">
            <el-button :loading="subtitleTasksLoading" @click="refreshRJSubtitleStatus(true)">刷新状态</el-button>
          </div>
        </section>

        <div class="subtitle-layout">
          <div class="subtitle-side-column">
            <el-card shadow="never" class="subtitle-config-card subtitle-config-card-strong">
              <template #header>执行选项</template>
              <div class="subtitle-option-stack">
                <div class="subtitle-switch-row">
                  <div>
                    <div class="subtitle-option-title">覆盖已有字幕</div>
                    <div class="subtitle-card-tip">已存在同名字幕时直接覆盖，适合重新抓取和修正。</div>
                  </div>
                  <AppLottieSwitch v-model="subtitleOptions.overwriteExisting" />
                </div>
                <div class="subtitle-switch-row">
                  <div>
                    <div class="subtitle-option-title">扫描深度</div>
                    <div class="subtitle-card-tip">点击目录时递归查找 RJ 文件夹，默认 3 层，可按目录结构调整。</div>
                  </div>
                  <el-input-number v-model="subtitleOptions.scanDepth" :min="1" :max="10" :step="1" controls-position="right" />
                </div>
                <div class="subtitle-switch-row">
                  <div>
                    <div class="subtitle-option-title">启用 metadata 匹配</div>
                    <div class="subtitle-card-tip">尝试读取音频 track/title 标签，提升字幕文件名匹配准确度。</div>
                  </div>
                  <AppLottieSwitch v-model="subtitleOptions.enableMetadataMatch" />
                </div>
                <div class="subtitle-switch-row">
                  <div>
                    <div class="subtitle-option-title">已有字幕时跳过</div>
                    <div class="subtitle-card-tip">待处理目录如果已经存在字幕，创建任务时直接跳过，不再进入抓取队列。</div>
                  </div>
                  <AppLottieSwitch v-model="subtitleOptions.skipIfExistingSubtitles" />
                </div>
                <div class="subtitle-switch-row subtitle-switch-row-wrap">
                  <div>
                    <div class="subtitle-option-title">同名依据</div>
                    <div class="subtitle-card-tip">配对应用后，音频和字幕会保持同名，只保留各自后缀。这里选择最终以谁的名字为准。</div>
                  </div>
                  <el-radio-group v-model="subtitleOptions.namingStrategy" size="small">
                    <el-radio-button label="audio">以音频名为准</el-radio-button>
                    <el-radio-button label="subtitle">以字幕名为准</el-radio-button>
                  </el-radio-group>
                </div>
                <div class="subtitle-switch-row">
                  <div>
                    <div class="subtitle-option-title">启用字幕过滤</div>
                    <div class="subtitle-card-tip">使用 RJ 工作台自己的字幕过滤规则筛候选，和解压过滤配置分开维护。</div>
                  </div>
                  <AppLottieSwitch v-model="subtitleOptions.useFilterRules" />
                </div>
                <div v-if="subtitleOptions.useFilterRules" class="subtitle-filter-editor">
                  <div class="subtitle-filter-editor-head">
                    <div>
                      <div class="subtitle-option-title">字幕过滤规则</div>
                      <div class="subtitle-card-tip">规则只作用于字幕候选。可按文件名、路径或全部文本匹配，筛掉反转、无 SE 等不需要的字幕。</div>
                    </div>
                    <el-button size="small" @click="addSubtitleFilterRule">添加规则</el-button>
                  </div>
                  <div v-if="!subtitleOptions.subtitleFilterRules.length" class="subtitle-filter-empty">当前还没有字幕过滤规则，点右侧按钮添加。</div>
                  <div v-else class="subtitle-filter-list">
                    <div v-for="rule in subtitleOptions.subtitleFilterRules" :key="rule.id" class="subtitle-filter-row">
                      <el-select v-model="rule.target" size="small" class="subtitle-filter-target">
                        <el-option label="文件名" value="name" />
                        <el-option label="路径" value="path" />
                        <el-option label="全部" value="all" />
                      </el-select>
                      <el-input v-model="rule.name" size="small" class="subtitle-filter-name" placeholder="规则名称" />
                      <el-input v-model="rule.pattern" size="small" class="subtitle-filter-pattern" placeholder="正则，例如 (反转|reverse|无SE)" />
                      <AppLottieSwitch v-model="rule.enabled" compact />
                      <el-button size="small" text type="danger" @click="removeSubtitleFilterRule(rule.id)">删除</el-button>
                    </div>
                  </div>
                </div>
              </div>

              <div class="subtitle-divider-label">任务展示</div>
              <div class="subtitle-pill-grid">
                <button type="button" class="subtitle-toggle-pill" :class="{ active: subtitleOptions.showSourceSearch }" @click="subtitleOptions.showSourceSearch = !subtitleOptions.showSourceSearch">来源搜索</button>
                <button type="button" class="subtitle-toggle-pill" :class="{ active: subtitleOptions.showWrittenFiles }" @click="subtitleOptions.showWrittenFiles = !subtitleOptions.showWrittenFiles">写入结果</button>
                <button type="button" class="subtitle-toggle-pill" :class="{ active: subtitleOptions.showDownloadedFiles }" @click="subtitleOptions.showDownloadedFiles = !subtitleOptions.showDownloadedFiles">下载进度</button>
                <button type="button" class="subtitle-toggle-pill" :class="{ active: subtitleOptions.showIssues }" @click="subtitleOptions.showIssues = !subtitleOptions.showIssues">问题项</button>
              </div>
            </el-card>

            <el-card shadow="never" class="subtitle-selection-card">
              <template #header>
                <div class="subtitle-selection-header">
                  <div class="subtitle-selection-header-main">
                    <div class="subtitle-selection-header-top">
                      <div class="subtitle-selection-header-title">
                        <span>扫描命中目录</span>
                        <span class="subtitle-selection-count-pill">{{ subtitleDialogSelection.length }}</span>
                      </div>
                      <span v-if="subtitleSelectionLoading && subtitleSelectionProgressText" class="subtitle-selection-progress">{{ subtitleSelectionProgressText }}</span>
                    </div>
                  </div>
                  <div v-if="subtitleSelectionTotalPages > 1" class="subtitle-selection-pager">
                    <el-button size="small" text :disabled="subtitleSelectionPage <= 1" @click="subtitleSelectionPage--">上一页</el-button>
                    <span>{{ subtitleSelectionPage }} / {{ subtitleSelectionTotalPages }}</span>
                    <el-button size="small" text :disabled="subtitleSelectionPage >= subtitleSelectionTotalPages" @click="subtitleSelectionPage++">下一页</el-button>
                  </div>
                </div>
              </template>
              <div class="subtitle-selection-live">
                <div v-if="subtitleScanSessionSummary.length" class="subtitle-scan-result-summary subtitle-scan-result-summary-compact">
                  <span v-for="item in subtitleScanSessionSummary" :key="item.key" class="subtitle-mini-chip">{{ item.label }} {{ item.value }}</span>
                </div>
                <div v-if="subtitleSelectionLoading && !subtitleDialogSelection.length" class="subtitle-selection-loading">
                  <AppLoadingAnimation variant="inline" :size="36" />
                  <span>{{ subtitleSelectionProgressText || '正在扫描目录…' }}</span>
                </div>
                <el-empty v-else-if="!subtitleDialogSelection.length" description="没有识别到 RJ 文件夹" />
                <template v-else>
                  <div class="subtitle-selection-section">
                    <div class="subtitle-selection-subhead">
                      <div class="subtitle-selection-subhead-main">
                        <div class="subtitle-selection-subtitle">可执行与已入任务</div>
                        <span class="subtitle-selection-count-pill">{{ subtitleExecutableSelectionItems.length }}</span>
                      </div>
                      <div class="subtitle-selection-subhead-actions">
                        <div v-if="subtitleSelectionFilterOptions.length" class="subtitle-selection-filter-row">
                          <button
                            v-for="item in subtitleSelectionFilterOptions"
                            :key="item.key"
                            type="button"
                            class="subtitle-mini-chip subtitle-chip-button"
                            :class="{ active: subtitleSelectionFilter === item.key }"
                            @click="subtitleSelectionFilter = item.key"
                          >
                            {{ item.label }} {{ item.value }}
                          </button>
                        </div>
                        <button type="button" class="subtitle-section-toggle" @click="subtitleExecutableCollapsed = !subtitleExecutableCollapsed">
                          <span>{{ subtitleExecutableCollapsed ? '展开' : '收起' }}</span>
                          <el-icon :class="{ 'is-collapsed': subtitleExecutableCollapsed }"><ArrowDown /></el-icon>
                        </button>
                      </div>
                    </div>
                    <el-empty v-if="!subtitleExecutableCollapsed && !subtitleExecutableDisplayItems.length" description="当前没有可执行或已入任务的 RJ 目录" />
                    <transition-group v-else-if="!subtitleExecutableCollapsed" name="subtitle-card-fade" tag="div" class="subtitle-selection-list">
                      <button
                        v-for="item in pagedSubtitleSelectionItems"
                        :key="buildSubtitleSelectionKey(item)"
                        type="button"
                        class="subtitle-selection-item"
                        :class="{ active: isSubtitleSelectionActive(item) }"
                        :title="item.folder_path"
                        @click="focusSubtitleSelectionItem(item)"
                      >
                        <div class="subtitle-selection-body">
                          <div class="subtitle-selection-name">{{ item.folder_name }}</div>
                          <div class="subtitle-selection-submeta">
                            <span v-if="getLibraryLabelById(item.library_id)" class="subtitle-selection-library">来源库：{{ getLibraryLabelById(item.library_id) }}</span>
                            <span class="subtitle-selection-path">{{ item.folder_path }}</span>
                          </div>
                          <div class="subtitle-selection-stats">
                            <span class="subtitle-mini-chip" :class="getSubtitleSelectionQueueClass(item)">{{ getSubtitleSelectionQueueLabel(item) }}</span>
                            <span class="subtitle-mini-chip">{{ item.rjcode || '未识别 RJ' }}</span>
                            <span class="subtitle-mini-chip">音频 {{ item.audio_count ?? '-' }}</span>
                            <span
                              v-for="chip in getSubtitleSelectionExistingChips(item)"
                              :key="`${buildSubtitleSelectionKey(item)}-${chip.key}`"
                              class="subtitle-mini-chip"
                            >
                              {{ chip.label }}
                            </span>
                          </div>
                          <div v-if="item.queue_message" class="subtitle-selection-note">{{ item.queue_message }}</div>
                          <div v-if="item.queue_state === 'existing_task' || canInspectSubtitleSelectionFolder(item) || canRetryCreateSubtitleTaskForSelection(item)" class="subtitle-selection-actions">
                            <el-button
                              size="small"
                              text
                              type="primary"
                              v-if="item.queue_state === 'existing_task' || canInspectSubtitleSelectionFolder(item)"
                              @click.stop="focusSubtitleSelectionItem(item)"
                            >
                              {{ item.queue_state === 'existing_task' ? '打开现有任务' : '检查字幕树' }}
                            </el-button>
                            <el-button
                              v-if="canRetryCreateSubtitleTaskForSelection(item)"
                              size="small"
                              text
                              type="danger"
                              :loading="subtitleForceQueueKey === buildSubtitleSelectionKey(item)"
                              :disabled="Boolean(subtitleForceQueueKey)"
                              @click.stop="forceCreateSubtitleTaskForSelection(item)"
                            >
                              重试加入
                            </el-button>
                            <el-button
                              v-if="canForceCreateSubtitleTaskForSelection(item)"
                              size="small"
                              text
                              type="success"
                              :loading="subtitleForceQueueKey === buildSubtitleSelectionKey(item)"
                              :disabled="Boolean(subtitleForceQueueKey)"
                              @click.stop="forceCreateSubtitleTaskForSelection(item)"
                            >
                              创建一次任务
                            </el-button>
                          </div>
                        </div>
                      </button>
                    </transition-group>
                  </div>

                  <div v-if="subtitleSkippedSelectionItems.length" class="subtitle-selection-section subtitle-selection-section-split">
                    <div class="subtitle-selection-subhead">
                      <div class="subtitle-selection-subhead-main">
                        <div class="subtitle-selection-subtitle">被跳过</div>
                        <span class="subtitle-selection-count-pill">{{ filteredSubtitleSkippedSelectionItems.length }}</span>
                      </div>
                      <div class="subtitle-selection-subhead-actions">
                        <div v-if="subtitleSkippedSelectionFilterOptions.length" class="subtitle-selection-filter-row">
                          <button
                            v-for="item in subtitleSkippedSelectionFilterOptions"
                            :key="item.key"
                            type="button"
                            class="subtitle-mini-chip subtitle-chip-button"
                            :class="{ active: isSubtitleSkippedSelectionFilterActive(item.key) }"
                            @click="toggleSubtitleSkippedSelectionFilter(item.key)"
                          >
                            {{ item.label }} {{ item.value }}
                          </button>
                        </div>
                        <button type="button" class="subtitle-section-toggle" @click="subtitleSkippedCollapsed = !subtitleSkippedCollapsed">
                          <span>{{ subtitleSkippedCollapsed ? '展开' : '收起' }}</span>
                          <el-icon :class="{ 'is-collapsed': subtitleSkippedCollapsed }"><ArrowDown /></el-icon>
                        </button>
                      </div>
                    </div>
                    <transition-group v-if="!subtitleSkippedCollapsed" name="subtitle-card-fade" tag="div" class="subtitle-selection-list subtitle-selection-list-skipped">
                      <button
                        v-for="item in filteredSubtitleSkippedSelectionItems"
                        :key="`${buildSubtitleSelectionKey(item)}-skipped`"
                        type="button"
                        class="subtitle-selection-item skipped"
                        :class="{ active: isSubtitleSelectionActive(item) }"
                        :title="item.folder_path"
                        @click="focusSubtitleSelectionItem(item)"
                      >
                        <div class="subtitle-selection-body">
                          <div class="subtitle-selection-name">{{ item.folder_name }}</div>
                          <div class="subtitle-selection-submeta">
                            <span v-if="getLibraryLabelById(item.library_id)" class="subtitle-selection-library">来源库：{{ getLibraryLabelById(item.library_id) }}</span>
                            <span class="subtitle-selection-path">{{ item.folder_path }}</span>
                          </div>
                          <div class="subtitle-selection-stats">
                            <span class="subtitle-mini-chip" :class="getSubtitleSelectionQueueClass(item)">{{ getSubtitleSelectionQueueLabel(item) }}</span>
                            <span class="subtitle-mini-chip">{{ item.rjcode || '未识别 RJ' }}</span>
                            <span class="subtitle-mini-chip">音频 {{ item.audio_count ?? '-' }}</span>
                            <span
                              v-for="chip in getSubtitleSelectionExistingChips(item)"
                              :key="`${buildSubtitleSelectionKey(item)}-${chip.key}`"
                              class="subtitle-mini-chip"
                            >
                              {{ chip.label }}
                            </span>
                          </div>
                          <div v-if="item.queue_message" class="subtitle-selection-note">{{ item.queue_message }}</div>
                          <div class="subtitle-selection-actions">
                            <el-button
                              v-if="canInspectSubtitleSelectionFolder(item)"
                              size="small"
                              text
                              @click.stop="inspectSubtitleSelectionFolder(item)"
                            >
                              检查字幕树
                            </el-button>
                            <el-button
                              v-if="canForceCreateSubtitleTaskForSelection(item)"
                              size="small"
                              text
                              type="success"
                              :loading="subtitleForceQueueKey === buildSubtitleSelectionKey(item)"
                              :disabled="Boolean(subtitleForceQueueKey)"
                              @click.stop="forceCreateSubtitleTaskForSelection(item)"
                            >
                              创建一次任务
                            </el-button>
                          </div>
                        </div>
                      </button>
                    </transition-group>
                  </div>
                </template>
              </div>
              <div v-if="subtitleScanTargetResults.length" class="subtitle-scan-result-wrap">
                <div class="subtitle-scan-skip-head">
                  <div class="subtitle-selection-subhead-main">
                    <div class="subtitle-scan-skip-title">扫描目标</div>
                    <span class="subtitle-selection-count-pill">{{ subtitleScanTargetResults.length }}</span>
                  </div>
                  <button type="button" class="subtitle-section-toggle" @click="subtitleScanTargetsCollapsed = !subtitleScanTargetsCollapsed">
                    <span>{{ subtitleScanTargetsCollapsed ? '展开' : '收起' }}</span>
                    <el-icon :class="{ 'is-collapsed': subtitleScanTargetsCollapsed }"><ArrowDown /></el-icon>
                  </button>
                </div>
                <div class="subtitle-scan-result-summary">
                  <span v-if="subtitleScanSummary.pending" class="subtitle-mini-chip">扫描中 {{ subtitleScanSummary.pending }}</span>
                  <span class="subtitle-mini-chip">成功 {{ subtitleScanSummary.success }}</span>
                  <span v-if="subtitleScanSummary.noAudio" class="subtitle-mini-chip">无音频 {{ subtitleScanSummary.noAudio }}</span>
                  <span v-if="subtitleScanSummary.noMatch" class="subtitle-mini-chip">未识别 {{ subtitleScanSummary.noMatch }}</span>
                  <span v-if="subtitleScanSummary.failed" class="subtitle-mini-chip">失败 {{ subtitleScanSummary.failed }}</span>
                </div>
                <transition-group v-if="!subtitleScanTargetsCollapsed" name="subtitle-card-fade" tag="div" class="subtitle-scan-result-list">
                  <div v-for="item in subtitleScanTargetResults" :key="buildSubtitleScanTargetResultKey(item)" class="subtitle-scan-result-row" :class="`status-${item.status}`">
                    <div class="subtitle-scan-result-main" :title="item.path">
                      <span class="subtitle-scan-result-name">{{ item.name }}</span>
                      <div class="subtitle-scan-result-submeta">
                        <span v-if="getLibraryLabelById(item.library_id)" class="subtitle-scan-result-library">{{ getLibraryLabelById(item.library_id) }}</span>
                        <span class="subtitle-scan-result-path">{{ item.path }}</span>
                      </div>
                    </div>
                    <div class="subtitle-scan-result-meta">
                      <span class="subtitle-scan-result-status" :class="`status-${item.status}`">{{ getSubtitleScanResultLabel(item.status) }}</span>
                      <span class="subtitle-scan-result-message">{{ item.message }}</span>
                      <el-button
                        v-if="canRetrySubtitleScanResult(item)"
                        size="small"
                        plain
                        :loading="subtitleScanRetryingPath === buildSubtitleScanTargetResultKey(item)"
                        :disabled="Boolean(subtitleScanRetryingPath) && subtitleScanRetryingPath !== buildSubtitleScanTargetResultKey(item)"
                        @click="rescanSubtitleSelectionTarget(item)"
                      >
                        重新扫描此项
                      </el-button>
                    </div>
                  </div>
                </transition-group>
              </div>
                <div v-if="subtitleSkippedScanResults.length" class="subtitle-scan-skip-wrap">
                  <div class="subtitle-scan-skip-head">
                    <div class="subtitle-selection-subhead-main">
                      <div class="subtitle-scan-skip-title">跳过结果</div>
                      <span class="subtitle-selection-count-pill">{{ filteredSubtitleSkippedScanResults.length }}</span>
                    </div>
                    <div v-if="subtitleSkippedScanFilterOptions.length" class="subtitle-selection-filter-row">
                      <button
                        v-for="item in subtitleSkippedScanFilterOptions"
                        :key="item.key"
                      type="button"
                      class="subtitle-mini-chip subtitle-chip-button"
                      :class="{ active: subtitleScanSkipFilter === item.key }"
                      @click="subtitleScanSkipFilter = item.key"
                    >
                      {{ item.label }} {{ item.value }}
                    </button>
                  </div>
                </div>
                <transition-group name="subtitle-card-fade" tag="div" class="subtitle-scan-skip-list">
                  <div v-for="item in filteredSubtitleSkippedScanResults" :key="`${buildSubtitleScanTargetResultKey(item)}-skipped`" class="subtitle-scan-result-row skipped" :class="`status-${item.status}`">
                    <div class="subtitle-scan-result-main">
                      <span class="subtitle-scan-result-name">{{ item.name }}</span>
                      <div class="subtitle-scan-result-submeta">
                        <span v-if="getLibraryLabelById(item.library_id)" class="subtitle-scan-result-library">{{ getLibraryLabelById(item.library_id) }}</span>
                        <span class="subtitle-scan-result-path">{{ item.path }}</span>
                      </div>
                    </div>
                    <div class="subtitle-scan-result-meta">
                      <span class="subtitle-scan-result-status" :class="`status-${item.status}`">{{ getSubtitleScanResultLabel(item.status) }}</span>
                      <span class="subtitle-scan-result-message">{{ item.message }}</span>
                      <el-button
                        v-if="canRetrySubtitleScanResult(item)"
                        size="small"
                        plain
                        :loading="subtitleScanRetryingPath === buildSubtitleScanTargetResultKey(item)"
                        :disabled="Boolean(subtitleScanRetryingPath) && subtitleScanRetryingPath !== buildSubtitleScanTargetResultKey(item)"
                        @click="rescanSubtitleSelectionTarget(item)"
                      >
                        重新扫描此项
                      </el-button>
                    </div>
                  </div>
                </transition-group>
              </div>
            </el-card>
          </div>

          <div class="subtitle-main-column">
            <el-card shadow="never" class="subtitle-task-card">
              <template #header>
                <div class="subtitle-section-header">
                  <div>
                    <div>最近字幕任务</div>
                    <div class="subtitle-section-tip">上面展示当前选中任务的详情，下面保留完整任务队列。运行中任务也会留在队列里，当前查看项会高亮。</div>
                  </div>
                  <div class="subtitle-task-toolbar">
                    <span class="subtitle-mini-chip">总任务 {{ subtitleQueueTasks.length }}</span>
                    <span class="subtitle-mini-chip">可清理 {{ subtitleClearableTaskCounts.finished }}</span>
                    <el-dropdown
                      trigger="click"
                      :disabled="!subtitleClearableTaskCounts.finished || Boolean(subtitleBulkClearingScope)"
                      @command="clearSubtitleTasksByScope"
                    >
                      <el-button size="small" plain :loading="Boolean(subtitleBulkClearingScope)">
                        一键清空任务
                        <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                      </el-button>
                      <template #dropdown>
                        <el-dropdown-menu>
                          <el-dropdown-item command="completed" :disabled="!subtitleClearableTaskCounts.completed">清空成功 {{ subtitleClearableTaskCounts.completed }}</el-dropdown-item>
                          <el-dropdown-item command="failed" :disabled="!subtitleClearableTaskCounts.failed">清空失败 {{ subtitleClearableTaskCounts.failed }}</el-dropdown-item>
                          <el-dropdown-item command="finished" :disabled="!subtitleClearableTaskCounts.finished">清空全部已结束 {{ subtitleClearableTaskCounts.finished }}</el-dropdown-item>
                        </el-dropdown-menu>
                      </template>
                    </el-dropdown>
                  </div>
                </div>
              </template>
              <el-empty v-if="!visibleSubtitleTasks.length" description="暂无字幕任务" />
              <div v-else class="subtitle-task-list">
                <div
                  v-if="activeSubtitleTask"
                  :key="activeSubtitleTask.id"
                  class="subtitle-task-detail"
                  :class="{ active: isSubtitleTaskSelected(activeSubtitleTask) }"
                >
                  <div class="subtitle-task-head">
                    <div>
                      <div class="subtitle-task-rj">{{ getTaskDisplayRJCode(activeSubtitleTask) }}</div>
                      <div class="subtitle-task-folder">{{ activeSubtitleTask.folder_name || getFileName(activeSubtitleTask.folder_path) }}</div>
                      <div v-if="getTaskSourceRJCode(activeSubtitleTask)" class="subtitle-task-source">来源字幕 {{ getTaskSourceRJCode(activeSubtitleTask) }}</div>
                    </div>
                    <div class="subtitle-task-meta">
                      <el-tag :type="getRJSubtitleTaskBaseStatusType(activeSubtitleTask)">{{ getRJSubtitleTaskBaseStatusLabel(activeSubtitleTask) }}</el-tag>
                      <span v-if="activeSubtitleTask.source_lang" class="subtitle-task-lang">{{ getRJSubtitleLangLabel(activeSubtitleTask.source_lang) }}</span>
                      <el-button
                        v-if="canCancelRJSubtitleTask(activeSubtitleTask)"
                        size="small"
                        plain
                        type="danger"
                        :loading="subtitleCancelingId === activeSubtitleTask.id"
                        @click="cancelRJSubtitleTask(activeSubtitleTask)"
                      >
                        取消任务
                      </el-button>
                      <el-button
                        size="small"
                        plain
                        :disabled="!canClearCurrentSubtitleTask(activeSubtitleTask)"
                        @click="clearCurrentSubtitleTask(activeSubtitleTask)"
                      >
                        清空当前任务
                      </el-button>
                      <el-button
                        size="small"
                        plain
                        type="warning"
                        :loading="subtitleTaskRerunId === activeSubtitleTask.id"
                        :disabled="!canRerunSubtitleTask(activeSubtitleTask)"
                        @click="rerunSubtitleTask(activeSubtitleTask)"
                      >
                        重新执行爬取字幕
                      </el-button>
                      <el-button size="small" plain :disabled="!activeSubtitleTask.subtitle_dir" @click="inspectSubtitleTask(activeSubtitleTask)">{{ getSubtitleTaskInspectLabel(activeSubtitleTask) }}</el-button>
                    </div>
                  </div>

                  <el-progress
                    :percentage="activeSubtitleTask.progress"
                    :status="getRJSubtitleProgressStatus(activeSubtitleTask)"
                    :stroke-width="8"
                  />

                  <div class="subtitle-task-step">{{ activeSubtitleTask.current_step }}</div>
                  <div class="subtitle-task-inline-meta">
                    <span class="subtitle-inline-chip">下载 {{ activeSubtitleTask.downloaded_count || getSubtitleDownloadFiles(activeSubtitleTask).length }}</span>
                    <span class="subtitle-inline-chip">匹配组 {{ activeSubtitleTask.match_result?.matched_group_count || 0 }}</span>
                    <span class="subtitle-inline-chip">写入 {{ activeSubtitleTask.written_files?.length || 0 }}</span>
                    <span class="subtitle-inline-chip">跳过 {{ activeSubtitleTask.skipped_files?.length || 0 }}</span>
                    <span class="subtitle-inline-chip">未匹配 {{ activeSubtitleTask.match_result?.unmatched_audio?.length || 0 }}</span>
                    <span class="subtitle-inline-chip" v-if="activeSubtitleTask.subtitle_dir">字幕目录已生成</span>
                  </div>
                  <div v-if="activeSubtitleTask.error_message" class="subtitle-task-error">{{ activeSubtitleTask.error_message }}</div>
                  <el-alert
                    v-if="activeSubtitleTask.manual_match_completed"
                    type="success"
                    :closable="false"
                    show-icon
                    class="subtitle-task-finish-alert"
                    :title="`筛选和匹配已完成，已应用 ${activeSubtitleTask.manual_match_applied_pairs || 0} 组配对`"
                  />

                  <el-collapse v-model="subtitleTaskDetailPanels" class="subtitle-task-detail-collapse">
                    <el-collapse-item v-if="subtitleOptions.showSourceSearch && activeSubtitleTask.search_attempts?.length" name="source">
                      <template #title>
                        <div class="subtitle-collapse-title">
                          <span>来源搜索</span>
                          <span class="subtitle-box-meta">{{ activeSubtitleTask.search_attempts.length }} 项</span>
                        </div>
                      </template>
                      <div class="subtitle-task-box">
                        <div v-for="attempt in activeSubtitleTask.search_attempts" :key="`${activeSubtitleTask.id}-${attempt.rjcode}`" class="subtitle-inline-row">
                          <span>{{ attempt.rjcode }}</span>
                          <span>{{ getRJSubtitleLangLabel(attempt.lang) }}</span>
                          <span>{{ formatRJSubtitleAttempt(attempt) }}</span>
                        </div>
                      </div>
                    </el-collapse-item>

                    <el-collapse-item v-if="subtitleOptions.showWrittenFiles && activeSubtitleTask.written_files?.length" name="written">
                      <template #title>
                        <div class="subtitle-collapse-title">
                          <span>写入结果</span>
                          <span class="subtitle-box-meta">{{ activeSubtitleTask.written_files.length }} 项</span>
                        </div>
                      </template>
                      <div class="subtitle-task-box">
                        <div class="subtitle-written-list">
                          <div v-for="(item, idx) in activeSubtitleTask.written_files.slice(0, 8)" :key="`${activeSubtitleTask.id}-write-${idx}`" class="subtitle-written-row">
                            <span class="subtitle-inline-primary subtitle-written-name">{{ item.output_name }}</span>
                            <span class="subtitle-written-type">{{ item.match_type }}</span>
                          </div>
                        </div>
                      </div>
                    </el-collapse-item>

                    <el-collapse-item v-if="subtitleOptions.showDownloadedFiles && getSubtitleDownloadFiles(activeSubtitleTask).length" name="download">
                      <template #title>
                        <div class="subtitle-collapse-title">
                          <span>下载进度</span>
                          <span class="subtitle-box-meta">
                            {{ getSubtitleDownloadFiles(activeSubtitleTask).length }} 项
                            <template v-if="allSubtitleDownloadsCompleted(activeSubtitleTask)"> · 已全部完成</template>
                          </span>
                        </div>
                      </template>
                      <div class="subtitle-task-box">
                        <div class="subtitle-box-head">
                          <div class="subtitle-box-meta">下载文件列表</div>
                          <el-button
                            v-if="hiddenSubtitleDownloadCount(activeSubtitleTask) > 0 || isSubtitleDownloadExpanded(activeSubtitleTask.id)"
                            size="small"
                            text
                            @click="toggleSubtitleDownloadExpanded(activeSubtitleTask.id)"
                          >
                            {{ isSubtitleDownloadExpanded(activeSubtitleTask.id) ? '收起' : `展开其余 ${hiddenSubtitleDownloadCount(activeSubtitleTask)} 项` }}
                          </el-button>
                        </div>
                        <div class="subtitle-download-list">
                          <div v-for="file in visibleSubtitleDownloadFiles(activeSubtitleTask)" :key="`${activeSubtitleTask.id}-${file.display_name || file.name}-${file.index || 0}`" class="subtitle-download-row">
                            <div class="subtitle-download-head">
                              <span class="subtitle-inline-primary subtitle-download-name">{{ getSubtitleDownloadDisplayName(file) }}</span>
                              <span class="subtitle-download-percent">{{ Math.round(file.progress || 0) }}%</span>
                            </div>
                            <el-progress :percentage="file.progress || 0" :stroke-width="8" :show-text="false" />
                          </div>
                        </div>
                      </div>
                    </el-collapse-item>

                    <el-collapse-item v-if="activeSubtitleTask.progress_log?.length" name="log">
                      <template #title>
                        <div class="subtitle-collapse-title">
                          <span>过程日志</span>
                          <span class="subtitle-box-meta">{{ activeSubtitleTask.progress_log.length }} 条</span>
                        </div>
                      </template>
                      <div class="subtitle-task-box subtitle-task-box-log">
                        <div class="subtitle-log-list">
                          <div v-for="(entry, idx) in activeSubtitleTaskProgressLogs" :key="`${activeSubtitleTask.id}-progress-log-${idx}`" class="subtitle-log-row">
                            <span class="subtitle-log-time">{{ formatProgressLogTime(entry.time) }}</span>
                            <span class="subtitle-log-level" :class="`level-${entry.level || 'info'}`">{{ getProgressLogLevelLabel(entry.level) }}</span>
                            <span class="subtitle-inline-primary">{{ entry.message }}</span>
                          </div>
                        </div>
                      </div>
                    </el-collapse-item>

                    <el-collapse-item v-if="subtitleOptions.showIssues && (activeSubtitleTask.error_message || activeSubtitleTask.match_result?.unmatched_audio?.length || activeSubtitleTask.write_errors?.length || activeSubtitleTask.failed_files?.length)" name="issues">
                      <template #title>
                        <div class="subtitle-collapse-title">
                          <span>问题项</span>
                          <span class="subtitle-box-meta">
                            <template v-if="(activeSubtitleTask.write_errors?.length || 0) > 0">写入失败 {{ activeSubtitleTask.write_errors.length }}</template>
                            <template v-else-if="(activeSubtitleTask.failed_files?.length || 0) > 0">下载失败 {{ activeSubtitleTask.failed_files.length }}</template>
                            <template v-else>未匹配 {{ activeSubtitleTask.match_result?.unmatched_audio?.length || 0 }}</template>
                          </span>
                        </div>
                      </template>
                      <div class="subtitle-task-box">
                        <div class="subtitle-box-head">
                          <div class="subtitle-box-meta">问题详情</div>
                          <el-button
                            v-if="hiddenSubtitleIssueCount(activeSubtitleTask) > 0 || isSubtitleIssueExpanded(activeSubtitleTask.id)"
                            size="small"
                            text
                            @click="toggleSubtitleIssueExpanded(activeSubtitleTask.id)"
                          >
                            {{ isSubtitleIssueExpanded(activeSubtitleTask.id) ? '收起' : `展开其余 ${hiddenSubtitleIssueCount(activeSubtitleTask)} 项` }}
                          </el-button>
                        </div>
                        <div class="subtitle-issue-list">
                          <div v-if="activeSubtitleTask.error_message" class="subtitle-issue-item issue-error">
                            <div class="subtitle-issue-kind">任务错误</div>
                            <div class="subtitle-issue-content">{{ activeSubtitleTask.error_message }}</div>
                          </div>
                          <div v-for="audio in activeSubtitleTask.match_result?.unmatched_audio || []" :key="`${activeSubtitleTask.id}-audio-${audio}`" class="subtitle-issue-item">
                            <div class="subtitle-issue-kind">未匹配音频</div>
                            <div class="subtitle-issue-content">{{ audio }}</div>
                          </div>
                          <div v-for="(error, idx) in visibleSubtitleWriteErrors(activeSubtitleTask)" :key="`${activeSubtitleTask.id}-write-error-${idx}`" class="subtitle-issue-item issue-warning">
                            <div class="subtitle-issue-kind">写入失败</div>
                            <div class="subtitle-issue-title">{{ error.name }}</div>
                            <div v-if="error.detail" class="subtitle-issue-detail">{{ error.detail }}</div>
                          </div>
                          <div v-for="(file, idx) in visibleSubtitleFailedFiles(activeSubtitleTask)" :key="`${activeSubtitleTask.id}-download-failed-${idx}`" class="subtitle-issue-item issue-warning">
                            <div class="subtitle-issue-kind">下载失败</div>
                            <div class="subtitle-issue-title">{{ file.name || file.title || '字幕文件' }}</div>
                            <div class="subtitle-issue-detail">{{ file.reason || '下载失败' }}</div>
                          </div>
                        </div>
                      </div>
                    </el-collapse-item>
                  </el-collapse>
                </div>

                <div class="subtitle-task-queue-head">
                  <div>
                    <div class="subtitle-task-box-title">任务队列</div>
                    <div class="subtitle-card-tip">包含正在处理中的任务和历史任务，当前查看项会高亮。</div>
                  </div>
                  <div class="subtitle-task-queue-filters">
                    <button
                      v-for="item in subtitleTaskManualOverview"
                      :key="`manual-${item.key}`"
                      type="button"
                      class="subtitle-mini-chip subtitle-chip-button"
                      :class="{ active: subtitleTaskManualFilter === item.key }"
                      @click="setSubtitleTaskManualFilter(item.key)"
                    >
                      {{ item.label }} {{ item.value }}
                    </button>
                  </div>
                </div>

                <div v-if="subtitleQueueTasks.length" class="subtitle-task-rail subtitle-task-queue-rail">
                  <button
                    v-for="task in subtitleQueueTasks"
                    :key="`queue-${task.id}`"
                    type="button"
                    class="subtitle-task-compact"
                    :class="{ active: isSubtitleTaskSelected(task), processing: task.status === 'processing', finished: task.manual_match_completed }"
                    @click="selectSubtitleTask(task)"
                  >
                    <div class="subtitle-task-compact-head">
                      <span class="subtitle-task-compact-rj">{{ getTaskDisplayRJCode(task) }}</span>
                      <span class="subtitle-task-compact-status" :class="`status-${getRJSubtitleTaskStatusClass(task)}`">{{ getRJSubtitleTaskStatusLabel(task) }}</span>
                    </div>
                    <div class="subtitle-task-compact-folder">{{ task.folder_name || getFileName(task.folder_path) }}</div>
                    <div v-if="getTaskSourceRJCode(task)" class="subtitle-task-compact-source">来源 {{ getTaskSourceRJCode(task) }}</div>
                    <div class="subtitle-task-compact-step">{{ task.current_step || task.error_message || '等待中' }}</div>
                    <div class="subtitle-task-compact-meta">
                      <span>下载 {{ task.downloaded_count || getSubtitleDownloadFiles(task).length }}</span>
                      <span>匹配组 {{ task.match_result?.matched_group_count || 0 }}</span>
                      <span>写入 {{ task.written_files?.length || 0 }}</span>
                      <span v-if="task.manual_match_completed" class="subtitle-task-meta-chip is-success">已匹配完成 {{ task.manual_match_applied_pairs || 0 }}</span>
                      <span v-else >未匹配 {{ task.match_result?.unmatched_audio?.length || 0 }}</span>
                    </div>
                    <div class="subtitle-task-compact-actions">
                      <el-button size="small" text :disabled="!task.subtitle_dir" @click.stop="inspectSubtitleTask(task)">{{ getSubtitleTaskInspectLabel(task) }}</el-button>
                    </div>
                  </button>
                </div>
              </div>
            </el-card>

            <SubtitleInspectorWorkbench :ctx="subtitleWorkbenchCtx" />
          </div>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="subtitleRenameDialogVisible" title="重命名字幕文件" width="500px">
      <el-form :model="subtitleRenameForm" label-width="80px">
        <el-form-item label="当前名称"><el-input v-model="subtitleRenameForm.currentName" disabled /></el-form-item>
        <el-form-item label="新名称"><el-input v-model="subtitleRenameForm.newName" placeholder="输入新的字幕文件名" /></el-form-item>
        <el-form-item label="预览"><div class="name-preview">{{ subtitleRenameForm.newName || subtitleRenameForm.currentName }}</div></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="subtitleRenameDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="subtitleRenameLoading" @click="confirmSubtitleRename">确认重命名</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mappedPathDialogVisible" title="跨设备访问 - 路径映射" width="620px">
      <el-alert title="检测到跨设备部署环境" type="info" :closable="false" show-icon style="margin-bottom: 16px">
        <template #default>后端无法直接替你打开本地路径，请使用下面的映射路径手动访问。</template>
      </el-alert>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="远程路径"><code class="path-code">{{ mappedPathInfo.originalPath }}</code></el-descriptions-item>
        <el-descriptions-item label="本地映射路径">
          <div class="mapped-path-box">
            <code class="path-code">{{ mappedPathInfo.mappedPath }}</code>
            <div class="path-actions">
              <el-button size="small" type="primary" @click="copyMappedPath">复制路径</el-button>
              <el-button size="small" type="success" @click="openWithBrowser">尝试打开</el-button>
            </div>
          </div>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <FolderContentsDialog
      ref="folderDialogRef"
      v-model="folderDialogVisible"
      :library-id="folderDialogLibraryId || selectedLibraryId"
      :folder-path="folderDialogPath"
      :folder-name="folderDialogName"
      @mutated="handleFolderDialogMutated"
    />

    <FilterDeleteDialog
      ref="filterDeleteDialogRef"
      v-model="filterDeleteDialogVisible"
      :library-id="filterDeleteDialogLibraryId"
      :current-path="filterDeleteDialogPath"
      :target-paths="filterDeleteDialogTargetPaths"
      :rules="filterDeleteDialogRules"
      :scope-label="filterDeleteDialogScopeLabel"
      :is-remote="filterDeleteDialogIsRemote"
      @deleted="handleFilterDeleteDeleted"
      @dismiss-background="handleFilterDeleteDialogDismissBackground"
      @state-change="handleFilterDeleteDialogStateChange"
    />

    <div v-if="showSubtitleBackgroundCard" class="subtitle-floating-card">
      <div class="subtitle-floating-head">
        <div>
          <div class="subtitle-floating-title">RJ 字幕工作台正在后台运行</div>
          <div class="subtitle-floating-mode">
            {{ subtitleBackgroundActiveTask ? `${getTaskDisplayRJCode(subtitleBackgroundActiveTask)} · ${subtitleBackgroundActiveTask.folder_name || getFileName(subtitleBackgroundActiveTask.folder_path) || '-'}` : '保留当前扫描与任务状态' }}
          </div>
        </div>
        <div class="subtitle-floating-count">{{ subtitleTasks.length }}</div>
      </div>
      <div class="subtitle-floating-chip-row">
        <span class="subtitle-floating-chip">任务 {{ subtitleTasks.length }}</span>
        <span class="subtitle-floating-chip">执行中 {{ subtitleTasks.filter(task => task.status === 'processing').length }}</span>
        <span class="subtitle-floating-chip">等待中 {{ subtitleTasks.filter(task => task.status === 'pending').length }}</span>
        <span class="subtitle-floating-chip">扫描命中 {{ subtitleDialogSelection.length }}</span>
      </div>
      <div class="subtitle-floating-text">
        {{ subtitleBackgroundActiveTask?.current_step || subtitleSelectionProgressText || '隐藏后继续保留任务队列和当前焦点。' }}
      </div>
      <div class="subtitle-floating-actions">
        <el-button size="small" type="primary" @click="resumeSubtitleTaskPanelFromBackground">恢复工作台</el-button>
        <el-button size="small" @click="closeSubtitleTaskPanel">关闭</el-button>
      </div>
    </div>

    <div v-if="showFilterDeleteBackgroundCard" class="filter-delete-floating-card">
      <div class="filter-delete-floating-head">
        <div>
          <div class="filter-delete-floating-title">{{ filterDeleteBackgroundState.scopeLabel || '删除过滤任务' }}</div>
          <div class="filter-delete-floating-mode">{{ filterDeleteBackgroundState.mode === 'delete' ? '后台删除中' : '后台预审中' }}</div>
        </div>
        <div class="filter-delete-floating-percent">{{ filterDeleteBackgroundState.percentage }}%</div>
      </div>
      <el-progress
        :percentage="filterDeleteBackgroundState.percentage"
        :status="filterDeleteBackgroundState.progressStatus || undefined"
        :stroke-width="8"
        :show-text="false"
      />
      <div class="filter-delete-floating-text">
        {{ filterDeleteBackgroundPrimaryText }}
      </div>
      <div class="filter-delete-floating-chip-row">
        <span class="filter-delete-floating-chip">状态 {{ filterDeleteBackgroundState.statusLabel }}</span>
        <span v-if="filterDeleteBackgroundState.mode === 'preview'" class="filter-delete-floating-chip">命中 {{ filterDeleteBackgroundState.selectedCount }}</span>
        <span v-if="filterDeleteBackgroundState.mode === 'preview'" class="filter-delete-floating-chip">规则 {{ filterDeleteBackgroundState.ruleCount }}</span>
        <span v-if="filterDeleteBackgroundState.mode === 'preview' && filterDeleteBackgroundState.previewTargetTotal > 0" class="filter-delete-floating-chip">
          目录 {{ filterDeleteBackgroundState.previewTargetIndex }} / {{ filterDeleteBackgroundState.previewTargetTotal }}
        </span>
        <span v-if="filterDeleteBackgroundState.mode === 'delete' && filterDeleteBackgroundState.deleteTotal" class="filter-delete-floating-chip">
          已删 {{ filterDeleteBackgroundState.deleteDone }} / {{ filterDeleteBackgroundState.deleteTotal }}
        </span>
      </div>
      <div v-if="filterDeleteBackgroundState.currentPath" class="filter-delete-floating-path">
        {{ filterDeleteBackgroundState.currentPath }}
      </div>
      <div v-if="filterDeleteBackgroundState.mode === 'preview'" class="filter-delete-floating-stats">
        已扫描 {{ filterDeleteBackgroundState.scannedEntries }}
        <span v-if="filterDeleteBackgroundState.discoveredEntries"> / 已发现 {{ filterDeleteBackgroundState.discoveredEntries }}</span>
        <span v-if="filterDeleteBackgroundState.pendingDirectories"> / 待扫目录 {{ filterDeleteBackgroundState.pendingDirectories }}</span>
        <span v-if="filterDeleteBackgroundState.selectedSizeText"> / 预计 {{ filterDeleteBackgroundState.selectedSizeText }}</span>
      </div>
      <div v-if="filterDeleteBackgroundState.startedAt" class="filter-delete-floating-stats">
        开始 {{ filterDeleteBackgroundState.startedAtText }} / 已运行 {{ filterDeleteBackgroundElapsedText }}
      </div>
      <div v-if="filterDeleteBackgroundState.mode === 'delete' && filterDeleteBackgroundState.deleteTotal" class="filter-delete-floating-stats">
        成功 {{ filterDeleteBackgroundState.deleteDone }} / {{ filterDeleteBackgroundState.deleteTotal }}，失败 {{ filterDeleteBackgroundState.deleteFailed || 0 }}
      </div>
      <div class="filter-delete-floating-actions">
        <el-button size="small" type="primary" @click="resumeFilterDeleteDialog">{{ filterDeleteBackgroundState.reviewable ? '打开预审结果' : '打开' }}</el-button>
        <el-button v-if="filterDeleteBackgroundState.canCancelPreview" size="small" @click="cancelBackgroundFilterDeletePreview">取消预审</el-button>
        <el-button v-if="filterDeleteBackgroundState.canStopDelete" size="small" @click="stopBackgroundFilterDelete">停止删除</el-button>
        <el-button v-if="!filterDeleteBackgroundState.active && filterDeleteBackgroundState.reviewable" size="small" @click="dismissFilterDeleteBackgroundCard">收起</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh, Search, Folder, FolderOpened, Delete, Edit, Files, Document, Picture, VideoPlay, Headset, Tickets, ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { configApi, libraryApi, localUploadApi, rjSubtitleApi, taskApi } from '../api'
import { showSystemAlert, showSystemConfirm } from '../composables/useSystemPrompt'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppLottieIcon from '../components/common/AppLottieIcon.vue'
import AppLottieSwitch from '../components/common/AppLottieSwitch.vue'
import clipboardIconAnimation from '../assets/anime/Clipboard.lottie'
import deleteIconAnimation from '../assets/anime/Delete icon animation.lottie'
import ServerUploadPreviewDialog from '../components/common/ServerUploadPreviewDialog.vue'
import UploadTaskWorkbenchDialog from '../components/upload/UploadTaskWorkbenchDialog.vue'
import FilterDeleteDialog from '../components/library/FilterDeleteDialog.vue'
import FolderContentsDialog from '../components/library/FolderContentsDialog.vue'
import SubtitleInspectorWorkbench from '../components/library/SubtitleInspectorWorkbench.vue'

const PAGE_SIZES = [10, 20, 50, 100]
const PAGE_SIZE_KEY = 'kikoeru.ui.library.pageSize'
const LIBRARY_ACTION_SCOPE_KEY = 'kikoeru.ui.library.toolbarActionScope'
const SEARCH_RESULT_KIND_KEY = 'kikoeru.ui.library.searchResultKind'
const SEARCH_EXACT_KEY = 'kikoeru.ui.library.searchExact'
const SUBTITLE_OPTIONS_KEY = 'kikoeru.ui.library.rjSubtitleOptions'
const SUBTITLE_SCAN_WORKSPACE_KEY = 'kikoeru.ui.library.rjSubtitleScanWorkspace'
const DEFAULT_SORT_BY = 'size'
const DEFAULT_SORT_ORDER = 'desc'
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const statsLoading = ref(false)
const listPolling = ref(false)
const statsPolling = ref(false)
const files = ref([])
const totalFiles = ref(0)
const libraries = ref([])
const selectedLibraryId = ref('')
const searchQuery = ref('')
const searchResultKind = ref(loadString(SEARCH_RESULT_KIND_KEY, 'all'))
const searchExact = ref(loadString(SEARCH_EXACT_KEY, '0') === '1')
const currentPage = ref(loadNumber('kikoeru.ui.library.page', 1))
const pageSize = ref(loadNumber(PAGE_SIZE_KEY, 20))
const toolbarActionScope = ref(loadString(LIBRARY_ACTION_SCOPE_KEY, 'page') === 'all' ? 'all' : 'page')
const sortBy = ref(DEFAULT_SORT_BY)
const sortOrder = ref(DEFAULT_SORT_ORDER)
const selectedRows = ref([])
const batchDeleting = ref(false)
const batchRenaming = ref(false)
const tableRef = ref(null)
const filterDeleteDialogRef = ref(null)
const folderDialogRef = ref(null)
const suppressSortChange = ref(false)
const apiRenamingId = ref(null)
const batchApiRenameRunningIds = ref(new Set())
const currentPath = ref('')
const browseRootPath = ref('')
const parentPath = ref('')
function createLibrarySearchState (overrides = {}) {
  return {
    active: false,
    query: '',
    rootPath: '',
    truncated: false,
    scannedDirectories: 0,
    globalRemote: false,
    searchedLibraries: 0,
    hitLibraries: 0,
    exactSearch: false,
    resultKind: 'all',
    ...overrides
  }
}
function createSearchResultReturnState (overrides = {}) {
  return {
    active: false,
    libraryId: '',
    searchQuery: '',
    currentPath: '',
    browseRootPath: '',
    page: 1,
    sortBy: DEFAULT_SORT_BY,
    sortOrder: DEFAULT_SORT_ORDER,
    searchExact: false,
    searchResultKind: 'all',
    searchState: createLibrarySearchState(),
    ...overrides
  }
}
const librarySearchState = ref(createLibrarySearchState())
const locatedLibraryPath = ref('')
const pendingLibraryLocate = ref(null)
const pendingLibrarySearchRestore = ref(null)
const searchResultReturnState = ref(createSearchResultReturnState())
const renameDialogVisible = ref(false)
const renameForm = ref({ currentName: '', newName: '', path: '', libraryId: '' })
const isRenaming = ref(false)
const localUploadDialogVisible = ref(false)
const localUploadSubmitting = ref(false)
const localUploadForm = ref({ targetLibraryId: '', targetSubdir: '' })
const trackedUploadTaskIds = ref([])
const trackedUploadTasks = ref([])
const uploadWorkbenchVisible = ref(false)
const uploadWorkbenchBackgroundActive = ref(false)
const uploadWorkbenchRefreshing = ref(false)
const LOCAL_UPLOAD_WORKBENCH_KEY = 'prekikoeru.library.uploadWorkbench'
let uploadWorkbenchTimer = null
const processingUploadTasks = computed(() => trackedUploadTasks.value.filter(task => String(task?.status || '') === 'processing'))
const pendingUploadTasks = computed(() => trackedUploadTasks.value.filter(task => ['pending', 'paused', 'waiting_retry'].includes(String(task?.status || ''))))
const completedUploadTasks = computed(() => trackedUploadTasks.value.filter(task => String(task?.status || '') === 'completed'))
const failedUploadTasks = computed(() => trackedUploadTasks.value.filter(task => String(task?.status || '') === 'failed'))
const showUploadBackgroundCard = computed(() => uploadWorkbenchBackgroundActive.value && !uploadWorkbenchVisible.value && trackedUploadTaskIds.value.length > 0)
const activeBackgroundUploadTask = computed(() => processingUploadTasks.value[0] || pendingUploadTasks.value[0] || trackedUploadTasks.value[0] || null)
const uploadBackgroundPercent = computed(() => {
  const task = activeBackgroundUploadTask.value
  if (!task) return 0
  const runtime = task?.upload_runtime || {}
  const total = Number(runtime?.total_bytes || 0)
  const transferred = Number(runtime?.transferred_bytes || 0)
  if (total > 0) return Math.max(0, Math.min(100, Math.round((transferred / total) * 100)))
  return Math.max(0, Math.min(100, Number(task?.progress || 0)))
})
const mappedPathDialogVisible = ref(false)
const mappedPathInfo = ref({ originalPath: '', mappedPath: '', isMapped: false })
const tampermonkeyLoaded = ref(false)
const statsMap = ref({})
const aggregateStats = ref({ folder_count: 0, total_size_gb: 0, total_size_bytes: 0 })
const libraryState = ref({})

function normalizeLibraryPathKey (path) {
  return String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
}

function getLibraryPageStateKey (path = currentPath.value, rootPath = browseRootPath.value) {
  const normalizedPath = normalizeLibraryPathKey(path)
  const normalizedRootPath = normalizeLibraryPathKey(rootPath)
  return normalizedPath || normalizedRootPath || '__root__'
}

function rememberCurrentDirectoryPage () {
  const libraryId = selectedLibraryId.value
  if (!libraryId) return
  const state = libraryState.value[libraryId] || {}
  const pageByPath = { ...(state.pageByPath || {}) }
  pageByPath[getLibraryPageStateKey()] = currentPage.value
  libraryState.value[libraryId] = {
    ...state,
    pageByPath
  }
}

function getRememberedDirectoryPage (path, fallback = 1, rootPath = browseRootPath.value) {
  const libraryId = selectedLibraryId.value
  if (!libraryId) return fallback
  const state = libraryState.value[libraryId] || {}
  const pageByPath = state.pageByPath || {}
  const remembered = Number(pageByPath[getLibraryPageStateKey(path, rootPath)] || 0)
  return remembered > 0 ? remembered : fallback
}
const labels = {
  pageTitle: '\u5e93\u5b58\u6587\u4ef6\u7ba1\u7406',
  currentLibrary: '\u5f53\u524d\u5e93',
  currentLibraryStats: '\u5f53\u524d\u5e93\u7edf\u8ba1',
  allLibraries: '\u5168\u90e8\u5e93\u5b58'
}
let statsPollTimer = null
let listPollTimer = null
let subtitleStatusPollTimer = null
let libraryInitialized = false
let libraryViewActive = false
let libraryKeydownBound = false
let forceLibraryRefreshOnce = false
function createSubtitleScanSessionState () {
  return {
    scannedTargets: 0,
    foundDirectories: 0,
    existingSubtitles: 0,
    noSubtitleTargets: 0,
    createdTasks: 0,
    existingTasks: 0,
    createFailed: 0,
    noAudioTargets: 0,
    noMatchTargets: 0,
    failedTargets: 0
  }
}
const folderDialogVisible = ref(false)
const folderDialogLibraryId = ref('')
const folderDialogPath = ref('')
const folderDialogName = ref('')
const filterDeleteDialogVisible = ref(false)
const filterDeleteDialogLibraryId = ref('')
const filterDeleteDialogPath = ref('')
const filterDeleteDialogTargetPaths = ref([])
const filterDeleteDialogRules = ref([])
const filterDeleteDialogScopeLabel = ref('')
const filterDeleteDialogIsRemote = ref(false)
const filterDeleteBackgroundState = ref({
  active: false,
  mode: 'preview',
  status: 'idle',
  statusLabel: '等待中',
  scopeLabel: '',
  progressMessage: '',
  currentPath: '',
  percentage: 0,
  progressStatus: '',
  startedAt: 0,
  startedAtText: '',
  previewTargetIndex: 0,
  previewTargetTotal: 0,
  reviewable: false,
  selectedCount: 0,
  selectedSize: 0,
  selectedSizeText: '',
  scannedEntries: 0,
  discoveredEntries: 0,
  pendingDirectories: 0,
  ruleCount: 0,
  deleteDone: 0,
  deleteTotal: 0,
  deleteFailed: 0,
  canCancelPreview: false,
  canStopDelete: false
})
const filterDeleteBackgroundNow = ref(Date.now())
let filterDeleteBackgroundTimer = null
const filterDeleteBackgroundDismissed = ref(false)
const filterDeleteBackgroundSessionKey = ref('')
const showFilterDeleteBackgroundCard = computed(() => (
  !filterDeleteDialogVisible.value
  && !filterDeleteBackgroundDismissed.value
  && (filterDeleteBackgroundState.value.active || filterDeleteBackgroundState.value.reviewable)
))
const filterDeleteBackgroundElapsedText = computed(() => {
  const startedAt = Number(filterDeleteBackgroundState.value.startedAt || 0)
  if (!startedAt) return '00:00'
  const diffSeconds = Math.max(0, Math.floor((filterDeleteBackgroundNow.value - startedAt) / 1000))
  const hours = Math.floor(diffSeconds / 3600)
  const minutes = Math.floor((diffSeconds % 3600) / 60)
  const seconds = diffSeconds % 60
  if (hours > 0) return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})
const filterDeleteBackgroundPrimaryText = computed(() => {
  if (filterDeleteBackgroundState.value.reviewable && !filterDeleteBackgroundState.value.active) {
    if (filterDeleteBackgroundState.value.selectedCount > 0) {
      return `预审完成，命中 ${filterDeleteBackgroundState.value.selectedCount} 项，点“继续确认”继续删除。`
    }
    return '预审完成，没有需要删除的命中项。'
  }
  return filterDeleteBackgroundState.value.progressMessage || (filterDeleteBackgroundState.value.mode === 'delete' ? '正在后台删除…' : '正在后台预审…')
})
const subtitleDialogVisible = ref(false)
const subtitleDialogBackgroundActive = ref(false)
const subtitleSubmitting = ref(false)
const subtitleTasksLoading = ref(false)
const subtitleConnectivityLoading = ref(false)
const subtitleCancelingId = ref('')
const subtitleTasks = ref([])
const subtitleActiveTaskId = ref('')
const subtitleTaskFilter = ref('all')
const subtitleTaskManualFilter = ref('all')
const subtitlePreferredSelectionKey = ref('')
const subtitleSelectionLoading = ref(false)
const subtitleSelectionScanDone = ref(0)
const subtitleSelectionScanTotal = ref(0)
const subtitleSelectionScanCurrent = ref('')
const subtitleSelectionRequestToken = ref(0)
const subtitleSelectionSourceItems = ref([])
const subtitleScannedSelectionItems = ref([])
const subtitleScanTargetResults = ref([])
const subtitleScanRetryingPath = ref('')
const subtitleScanSession = ref(createSubtitleScanSessionState())
const isRefreshingCurrentView = ref(false)
const batchApiRenameTargetIds = ref(new Set())
const subtitleDownloadExpandedMap = ref({})
const subtitleIssueExpandedMap = ref({})
const subtitleDialogSelection = ref([])
const subtitleExecutableCollapsed = ref(false)
const subtitleSkippedCollapsed = ref(false)
const subtitleScanTargetsCollapsed = ref(true)
const subtitleInspectorLoading = ref(false)
const subtitleInspectorDeleting = ref(false)
const subtitleInspectorSearch = ref('')
const subtitleInspectorItems = ref([])
const subtitleInspectorAudioItems = ref([])
const subtitleInspectorAudioSearch = ref('')
const subtitleInspectorSubtitleSearch = ref('')
const subtitleInspectorExpandedIds = ref(new Set())
const subtitleInspectorSelectedIds = ref(new Set())
const subtitleInspectorInfo = ref({
  taskId: '',
  libraryId: '',
  audioLibraryId: '',
  subtitleLibraryId: '',
  folderPath: '',
  subtitleDir: '',
  sourceMode: '',
  manualMatchCompleted: false,
  manualMatchAppliedPairs: 0,
  manualMatchDeletedSubtitles: 0,
  manualMatchMessage: '',
  totalFiles: 0,
  totalSize: 0
})
const subtitleMatchSelection = ref({ audioPath: '', subtitlePath: '' })
const subtitleSequenceMode = ref(false)
const subtitleSequenceSelection = ref({ audioPaths: [], subtitlePaths: [] })
const subtitleLastPairBuildMode = ref('')
const subtitleManualPairs = ref([])
const subtitleSelectedManualPairId = ref('')
const subtitlePairApplying = ref(false)
const subtitleTaskDetailPanels = ref([])
const subtitleBulkClearingScope = ref('')
const subtitleRenameDialogVisible = ref(false)
const subtitleRenameForm = ref({ currentName: '', newName: '', path: '' })
const subtitleRenameLoading = ref(false)
const subtitleInspectorLastSelectedId = ref('')
const subtitleRouteFocusKey = ref('')
const subtitleOptions = ref({
  overwriteExisting: false,
  scanDepth: 3,
  enableMetadataMatch: true,
  skipIfExistingSubtitles: false,
  namingStrategy: 'audio',
  useFilterRules: false,
  subtitleFilterRules: [],
  showSourceSearch: true,
  showWrittenFiles: true,
  showDownloadedFiles: true,
  showIssues: true
})
const subtitleSelectionPage = ref(1)
const subtitleSelectionPageSize = 6
const subtitleSelectionFilter = ref('all')
const subtitleScanSkipFilter = ref('all')
const subtitleSkippedSelectionFilter = ref([])
const subtitleForceQueueKey = ref('')
const subtitleTaskRerunId = ref('')
const subtitleAudioFilterMode = ref('all')
const subtitleSubtitleFilterMode = ref('all')

const currentLibrary = computed(() => libraries.value.find(item => item.id === selectedLibraryId.value) || null)
const currentStats = computed(() => statsMap.value[selectedLibraryId.value] || null)
const isRemoteCurrentLibrary = computed(() => currentLibrary.value?.type === 'synology_filestation')
const currentLibraryTypeLabel = computed(() => isRemoteCurrentLibrary.value ? '\u8fdc\u7a0b\u670d\u52a1\u5668\u5e93\u5b58' : '\u672c\u5730\u5e93\u5b58')
const currentLibraryScopeLabel = computed(() => isRemoteCurrentLibrary.value ? '\u8fdc\u7a0b' : '\u672c\u5730')
const isWritableCurrentLibrary = computed(() => !!currentLibrary.value?.writable)
const remoteUploadLibraries = computed(() => (Array.isArray(libraries.value) ? libraries.value : []).filter(item => item?.type === 'synology_filestation' && item?.enabled !== false))
const hasRemoteUploadLibraries = computed(() => remoteUploadLibraries.value.length > 0)
const isAllSelected = computed(() => files.value.length > 0 && selectedRows.value.length === files.value.length)
const aggregatePending = computed(() => Object.values(statsMap.value).some(item => item?.status === 'pending'))
const remoteIdleLibraries = computed(() => libraries.value.filter(item => item.type === 'synology_filestation' && ['idle', undefined].includes(statsMap.value[item.id]?.status)).length)
const countedLibraries = computed(() => libraries.value.filter(item => {
  const status = statsMap.value[item.id]?.status
  return status && status !== 'idle'
}).length)
const currentStatsProgress = computed(() => Math.max(0, Math.min(100, Number(currentStats.value?.progress_percent || 0))))
const showCurrentStatsProgress = computed(() => currentStats.value?.status === 'pending' && currentStatsProgress.value > 0)
const canCancelStats = computed(() => currentStats.value?.status === 'pending')
const aggregateProgress = computed(() => {
  const relevant = libraries.value
    .map(item => statsMap.value[item.id])
    .filter(item => item && ['ready', 'pending'].includes(item.status))
  if (!relevant.length) return 0
  const total = relevant.reduce((sum, item) => sum + (item.status === 'ready' ? 100 : Number(item.progress_percent || 0)), 0)
  return Math.max(0, Math.min(100, Number((total / relevant.length).toFixed(2))))
})
const showAggregateProgress = computed(() => aggregatePending.value && aggregateProgress.value > 0)
const aggregateLastCompletedAt = computed(() => {
  const timestamps = Object.values(statsMap.value)
    .map(item => Number(item?.last_completed_at || item?.updated_at || 0))
    .filter(value => Number.isFinite(value) && value > 0)
  return timestamps.length ? Math.max(...timestamps) : null
})
const aggregateSizeText = computed(() => {
  const base = formatGB(aggregateStats.value.total_size_gb)
  return remoteIdleLibraries.value > 0 ? `${base}\uff08\u4ec5\u5df2\u7edf\u8ba1\u5e93\uff09` : base
})
const aggregateSummary = computed(() => {
  if (aggregatePending.value) return `\u7edf\u8ba1\u8fdb\u884c\u4e2d\uff0c\u5df2\u5b8c\u6210 ${aggregateProgress.value.toFixed(0)}%`
  if (remoteIdleLibraries.value > 0) return `\u5f53\u524d\u4ec5\u5305\u542b ${countedLibraries.value}/${libraries.value.length} \u4e2a\u5df2\u7edf\u8ba1\u5e93`
  return `\u5171 ${libraries.value.length} \u4e2a\u5e93`
})
const aggregateDetail = computed(() => {
  if (aggregatePending.value) {
    const ts = aggregateLastCompletedAt.value
    return ts
      ? `\u540e\u53f0\u7ee7\u7eed\u66f4\u65b0\u4e2d\uff0c\u5f53\u524d\u4f18\u5148\u663e\u793a\u5df2\u4fdd\u5b58\u7ed3\u679c\uff0c\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}`
      : '\u540e\u53f0\u7ee7\u7eed\u66f4\u65b0\u4e2d\uff0c\u7edf\u8ba1\u7ed3\u679c\u4f1a\u81ea\u52a8\u5237\u65b0'
  }
  if (remoteIdleLibraries.value > 0) return '\u672a\u624b\u52a8\u7edf\u8ba1\u7684\u8fdc\u7a0b\u5e93\u4e0d\u4f1a\u8ba1\u5165\u603b\u6587\u4ef6\u5939\u6570\u548c\u603b\u5927\u5c0f'
  const ts = aggregateLastCompletedAt.value
  return ts ? `\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : ''
})
const canGoParent = computed(() => {
  if (searchResultReturnState.value.active) return true
  return !!parentPath.value && currentPath.value && currentPath.value !== browseRootPath.value
})
const backButtonLabel = computed(() => (searchResultReturnState.value.active ? '返回搜索结果' : '返回上级'))
const currentPathDisplay = computed(() => {
  const normalizedCurrent = (currentPath.value || '').replace(/\\/g, '/')
  const normalizedRoot = (browseRootPath.value || '').replace(/\\/g, '/')
  if (!normalizedCurrent) return '/'
  if (!normalizedRoot) return normalizedCurrent
  if (normalizedCurrent === normalizedRoot) return '/'
  if (normalizedCurrent.startsWith(`${normalizedRoot}/`)) return normalizedCurrent.slice(normalizedRoot.length)
  return normalizedCurrent
})
const librarySearchSummary = computed(() => {
  if (!librarySearchState.value.active) return ''
  const query = librarySearchState.value.query || searchQuery.value.trim()
  const exactText = librarySearchState.value.exactSearch ? '精确' : '模糊'
  const kindText = librarySearchState.value.resultKind === 'folder'
    ? '文件夹'
    : librarySearchState.value.resultKind === 'file'
      ? '文件'
      : '全部'
  const suffix = librarySearchState.value.truncated ? '，结果已按上限截断' : ''
  if (librarySearchState.value.globalRemote) {
    const searchedLibraries = Number(librarySearchState.value.searchedLibraries || 0)
    const hitLibraries = Number(librarySearchState.value.hitLibraries || 0)
    return `真实搜索：跨 ${searchedLibraries} 个远程库搜索 “${query}” (${exactText} / ${kindText}，命中 ${hitLibraries} 个库)${suffix}`
  }
  const scope = currentPathDisplay.value || '/'
  return `真实搜索：在 ${scope} 下搜索 “${query}” (${exactText} / ${kindText})${suffix}`
})

const currentFolderRJCode = computed(() => extractRJCode(currentPath.value || ''))
const currentPageDirectoryRows = computed(() => files.value.filter(row => row?.is_directory))
const toolbarActionScopeLabel = computed(() => toolbarActionScope.value === 'page' ? '当前页目录' : '当前目录')
function normalizeRemoteActionPath (path = '') {
  const normalized = String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
  return normalized || '/'
}

function joinRemoteActionPath (basePath = '', name = '') {
  const normalizedBase = normalizeRemoteActionPath(basePath)
  const normalizedName = String(name || '').trim().replace(/^\/+|\/+$/g, '')
  if (!normalizedName) return normalizedBase
  if (normalizedBase === '/') return `/${normalizedName}`
  return `${normalizedBase}/${normalizedName}`
}

function resolveDirectoryActionPath (row) {
  const rawPath = String(row?.path || '').trim()
  if (!isRemoteCurrentLibrary.value) return rawPath

  const currentDir = normalizeRemoteActionPath(currentPath.value)
  const browseRoot = normalizeRemoteActionPath(browseRootPath.value)
  const parentPath = normalizeRemoteActionPath(row?.parent_path || '')
  const rowPath = normalizeRemoteActionPath(rawPath)
  const rowName = String(row?.name || getFileName(rawPath)).trim()
  const rebuiltPath = rowName ? joinRemoteActionPath(currentDir, rowName) : currentDir
  const withinBrowseRoot = browseRoot === '/' || rowPath === browseRoot || rowPath.startsWith(`${browseRoot}/`)

  if (rowName && parentPath === currentDir) {
    return rebuiltPath
  }
  if (rowName && rawPath && !withinBrowseRoot && currentDir && currentDir !== '/') {
    return rebuiltPath
  }
  return rawPath
}

const toolbarSubtitleScopeRows = computed(() => {
  if (toolbarActionScope.value === 'page') {
    if (currentPageDirectoryRows.value.length) return currentPageDirectoryRows.value
    return currentPath.value ? [{ path: currentPath.value, name: getFileName(currentPath.value), is_directory: true }] : []
  }
  return []
})
const toolbarFilterDeletePaths = computed(() => {
  if (toolbarActionScope.value === 'page') {
    const pagePaths = currentPageDirectoryRows.value.map(resolveDirectoryActionPath).filter(Boolean)
    if (pagePaths.length) return [...new Set(pagePaths)]
    return currentPath.value ? [currentPath.value] : []
  }
  return currentPath.value ? [currentPath.value] : []
})
const canProcessCurrentFolder = computed(() => {
  if (!isWritableCurrentLibrary.value) return false
  if (toolbarActionScope.value === 'page') return toolbarSubtitleScopeRows.value.length > 0
  return !!currentPath.value
})
const selectedFilterDeleteRows = computed(() => selectedRows.value.filter(row => row?.is_directory))
const selectedUploadRows = computed(() => (Array.isArray(selectedRows.value) ? selectedRows.value : []).filter(row => row?.is_directory && row?.path))
const selectedUploadCount = computed(() => selectedUploadRows.value.length)
const selectedUploadSourceItems = computed(() => selectedUploadRows.value.map(row => ({
  name: row?.name || getFileName(row?.path || ''),
  path: row?.path || '',
  size: Number(row?.size || 0),
})).filter(item => item.path))
const canFilterDeleteCurrentFolder = computed(() => {
  if (!isWritableCurrentLibrary.value) return false
  if (toolbarActionScope.value === 'page') return toolbarFilterDeletePaths.value.length > 0
  return !!currentPath.value
})
const libraryTableKey = computed(() => [
  selectedLibraryId.value || 'default',
  currentPath.value || browseRootPath.value || '/',
  currentPage.value,
  pageSize.value,
  sortBy.value,
  sortOrder.value,
  searchQuery.value.trim()
].join('::'))
function matchesSubtitleTaskFilter (task, filter = subtitleTaskFilter.value) {
  if (filter === 'all') return true
  if (filter === 'processing') return task?.status === 'processing'
  if (filter === 'pending') return task?.status === 'pending'
  if (filter === 'completed') return task?.status === 'completed' && !task?.manual_match_completed
  if (filter === 'matched') return Boolean(task?.manual_match_completed)
  if (filter === 'failed') return task?.status === 'failed' || isRJSubtitleTaskCancelled(task)
  return true
}

function isSubtitleTaskAwaitingManualWork (task) {
  if (!task || isRJSubtitleTaskCancelled(task)) return false
  if (task.manual_match_completed) return false
  return Boolean(task.awaiting_manual_match || task.status === 'completed')
}

function matchesSubtitleTaskManualFilter (task, filter = subtitleTaskManualFilter.value) {
  if (filter === 'all') return true
  if (filter === 'awaiting_manual_match') return isSubtitleTaskAwaitingManualWork(task)
  if (filter === 'manual_match_completed') return Boolean(task?.manual_match_completed)
  if (filter === 'processing') return task?.status === 'processing'
  if (filter === 'pending') return task?.status === 'pending'
  if (filter === 'failed') return task?.status === 'failed' || isRJSubtitleTaskCancelled(task)
  return true
}

function getSubtitleTaskFilterResultCount(taskFilter = subtitleTaskFilter.value, manualFilter = subtitleTaskManualFilter.value) {
  return subtitleTasks.value.filter(task => (
    matchesSubtitleTaskFilter(task, taskFilter)
    && matchesSubtitleTaskManualFilter(task, manualFilter)
  )).length
}

function normalizeSubtitleTaskFilterSelection(nextTaskFilter, nextManualFilter) {
  const taskFilter = nextTaskFilter || 'all'
  const manualFilter = nextManualFilter || 'all'
  if (!subtitleTasks.value.length) {
    return {
      taskFilter: 'all',
      manualFilter: 'all'
    }
  }
  if (getSubtitleTaskFilterResultCount(taskFilter, manualFilter) > 0) {
    return {
      taskFilter,
      manualFilter
    }
  }
  if (manualFilter !== 'all' && getSubtitleTaskFilterResultCount(taskFilter, 'all') > 0) {
    return {
      taskFilter,
      manualFilter: 'all'
    }
  }
  if (taskFilter !== 'all' && getSubtitleTaskFilterResultCount('all', manualFilter) > 0) {
    return {
      taskFilter: 'all',
      manualFilter
    }
  }
  return {
    taskFilter: 'all',
    manualFilter: 'all'
  }
}

const visibleSubtitleTasks = computed(() => subtitleTasks.value.filter(task => matchesSubtitleTaskFilter(task) && matchesSubtitleTaskManualFilter(task)))
const subtitleTaskSummary = computed(() => ({
  total: visibleSubtitleTasks.value.length,
  pending: visibleSubtitleTasks.value.filter(task => task.status === 'pending').length,
  processing: visibleSubtitleTasks.value.filter(task => task.status === 'processing').length,
  completed: visibleSubtitleTasks.value.filter(task => task.status === 'completed').length,
  failed: visibleSubtitleTasks.value.filter(task => task.status === 'failed').length
}))
const subtitleTaskOverview = computed(() => ([
  { key: 'all', label: '任务', value: subtitleTasks.value.length },
  { key: 'processing', label: '执行中', value: subtitleTasks.value.filter(task => task.status === 'processing').length },
  { key: 'pending', label: '等待中', value: subtitleTasks.value.filter(task => task.status === 'pending').length },
  { key: 'completed', label: '已完成', value: subtitleTasks.value.filter(task => task.status === 'completed' && !task.manual_match_completed).length },
  { key: 'matched', label: '已匹配完成', value: subtitleTasks.value.filter(task => task.manual_match_completed).length },
  { key: 'failed', label: '失败', value: subtitleTasks.value.filter(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task)).length }
]).filter(item => item.key === 'all' || item.value > 0))
const subtitleTaskManualOverview = computed(() => ([
  { key: 'all', label: '全部', value: subtitleTasks.value.length },
  { key: 'awaiting_manual_match', label: '待处理', value: subtitleTasks.value.filter(task => isSubtitleTaskAwaitingManualWork(task)).length },
  { key: 'processing', label: '执行中', value: subtitleTasks.value.filter(task => task.status === 'processing').length },
  { key: 'pending', label: '等待中', value: subtitleTasks.value.filter(task => task.status === 'pending').length },
  { key: 'manual_match_completed', label: '已匹配完成', value: subtitleTasks.value.filter(task => task.manual_match_completed).length },
  { key: 'failed', label: '失败', value: subtitleTasks.value.filter(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task)).length }
]))
const subtitleDialogSessionActive = computed(() => subtitleDialogVisible.value || subtitleDialogBackgroundActive.value)
const showSubtitleBackgroundCard = computed(() => subtitleDialogBackgroundActive.value && !subtitleDialogVisible.value)
const subtitleBackgroundActiveTask = computed(() => (
  activeSubtitleTask.value
  || sortSubtitleTasksForWorkbench(subtitleTasks.value).find(task => ['processing', 'pending'].includes(task?.status))
  || sortSubtitleTasksForWorkbench(subtitleTasks.value)[0]
  || null
))
function subtitleTaskTimeValue (task, field = 'created_at') {
  const raw = task?.[field]
  const value = raw ? Date.parse(raw) : NaN
  return Number.isFinite(value) ? value : 0
}
function sortSubtitleTasksByCreatedAt (tasks = []) {
  return [...tasks].sort((left, right) => subtitleTaskTimeValue(right) - subtitleTaskTimeValue(left))
}

function subtitleTaskSortWeight (task) {
  if (!task) return 99
  if (task.status === 'processing') return 0
  if (task.status === 'pending') return 1
  if (task.status === 'paused') return 2
  if (isSubtitleTaskAwaitingManualWork(task)) return 3
  if (task.status === 'failed') return 4
  if (task.manual_match_completed) return 5
  if (task.status === 'completed') return 6
  return 7
}

function sortSubtitleTasksForWorkbench (tasks = []) {
  return [...tasks].sort((left, right) => {
    const weightDiff = subtitleTaskSortWeight(left) - subtitleTaskSortWeight(right)
    if (weightDiff !== 0) return weightDiff
    return subtitleTaskTimeValue(right) - subtitleTaskTimeValue(left)
  })
}
function compareSubtitleWorkbenchNames (left, right) {
  return String(left || '').localeCompare(String(right || ''), 'zh-Hans-CN-u-kn-true')
}
function buildSubtitleSelectionKey (item) {
  if (!item?.folder_path) return ''
  return `${item.library_id || selectedLibraryId.value || ''}::${String(item.folder_path).replace(/\\/g, '/')}`
}

function buildSubtitleSelectionItemFromTask (task = {}) {
  return {
    library_id: task.library_id || selectedLibraryId.value,
    folder_path: task.folder_path || '',
    folder_name: task.folder_name || getFileName(task.folder_path),
    rjcode: task.rjcode || task.actual_rjcode || '',
    audio_count: task.audio_count ?? null,
    existing_subtitle_count: task.existing_subtitle_count ?? 0,
    status: Number(task.existing_subtitle_count || 0) > 0 ? 'existing' : 'ready'
  }
}

function createSubtitleFilterRule (overrides = {}) {
  return {
    id: `subtitle-filter-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    target: 'name',
    name: '',
    pattern: '',
    enabled: true,
    ...overrides
  }
}

function normalizeSubtitleFilterRule (rule = {}) {
  return createSubtitleFilterRule({
    id: rule.id || undefined,
    target: ['name', 'path', 'all'].includes(rule.target) ? rule.target : 'name',
    name: String(rule.name || ''),
    pattern: String(rule.pattern || ''),
    enabled: rule.enabled !== false
  })
}

function sanitizeSubtitleFilterRules (rules = []) {
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

function addSubtitleFilterRule () {
  subtitleOptions.value.subtitleFilterRules = [
    ...(subtitleOptions.value.subtitleFilterRules || []),
    createSubtitleFilterRule()
  ]
}

function removeSubtitleFilterRule (ruleId) {
  subtitleOptions.value.subtitleFilterRules = (subtitleOptions.value.subtitleFilterRules || []).filter(rule => rule.id !== ruleId)
}
function buildSubtitleTaskSelectionKey (task) {
  if (!task?.folder_path) return ''
  return `${task.library_id || selectedLibraryId.value || ''}::${String(task.folder_path).replace(/\\/g, '/')}`
}
function getTaskDisplayRJCode (task) {
  return (
    task?.rjcode ||
    task?.actual_rjcode ||
    extractRJCode(task?.folder_path || '') ||
    extractRJCode(task?.folder_name || '') ||
    '未知RJ'
  )
}
function getTaskSourceRJCode (task) {
  const sourceRJ = String(task?.actual_rjcode || '').trim()
  const folderRJ = String(task?.rjcode || '').trim()
  return sourceRJ && sourceRJ !== folderRJ ? sourceRJ : ''
}

function getSubtitleSelectionExistingChips (item) {
  const localExistingCount = Math.max(0, Number(item?.existing_subtitle_count || 0))
  const chips = [{ key: 'local-existing', label: `本地字幕 ${localExistingCount}` }]
  if (item?.kikoeru_has_existing_subtitles) {
    chips.push({ key: 'kikoeru-flag', label: 'Kikoeru 命中' })
  }
  return chips
}

function findSubtitleTaskBySelection (item, tasks = subtitleTasks.value) {
  const selectionKey = buildSubtitleSelectionKey(item)
  if (!selectionKey) return null
  return sortSubtitleTasksByCreatedAt(tasks).find(task => buildSubtitleTaskSelectionKey(task) === selectionKey) || null
}
function findTaskMatchingPreferredSelection (tasks = subtitleTasks.value) {
  if (!subtitlePreferredSelectionKey.value) return null
  return sortSubtitleTasksByCreatedAt(tasks).find(task => buildSubtitleTaskSelectionKey(task) === subtitlePreferredSelectionKey.value) || null
}
function clearSubtitleInspectorState () {
  subtitleInspectorInfo.value = {
    taskId: '',
    libraryId: '',
    audioLibraryId: '',
    subtitleLibraryId: '',
    folderPath: '',
    subtitleDir: '',
    sourceMode: '',
    manualMatchCompleted: false,
    manualMatchAppliedPairs: 0,
    manualMatchDeletedSubtitles: 0,
    manualMatchMessage: '',
    totalFiles: 0,
    totalSize: 0
  }
  subtitleInspectorItems.value = []
  subtitleInspectorAudioItems.value = []
  subtitleInspectorExpandedIds.value = new Set()
  subtitleInspectorSelectedIds.value = new Set()
  subtitleInspectorLastSelectedId.value = ''
  resetSubtitleManualMatchState()
}
function estimateSubtitleTaskAudioCount (task) {
  if (!task) return null
  const matchedGroups = Number(task.match_result?.matched_group_count || 0)
  const unmatchedAudio = Number(task.match_result?.unmatched_audio?.length || 0)
  const estimated = matchedGroups + unmatchedAudio
  return estimated > 0 ? estimated : null
}
function estimateSubtitleTaskExistingCount (task) {
  if (!task) return null
  const explicitCount = Number(task.existing_subtitle_count)
  if (Number.isFinite(explicitCount) && explicitCount > 0) return explicitCount
  const written = Number(task.written_files?.length || 0)
  const skipped = Number(task.skipped_files?.length || 0)
  const matched = Number(task.match_result?.matched_subtitle_count || 0)
  return Math.max(written + skipped, matched, 0)
}
function syncSubtitleSelectionState () {
  if (!subtitleDialogSelection.value.length) return
  const tasksBySelectionKey = new Map(sortSubtitleTasksByCreatedAt(subtitleTasks.value).map(task => [buildSubtitleTaskSelectionKey(task), task]))
  subtitleDialogSelection.value = subtitleDialogSelection.value
    .map(item => {
      const task = tasksBySelectionKey.get(buildSubtitleSelectionKey(item))
      if (!task) return item
      const nextAudioCount = item.audio_count ?? estimateSubtitleTaskAudioCount(task)
      const nextExistingCount = Math.max(
        Number(item.existing_subtitle_count || 0),
        Number(estimateSubtitleTaskExistingCount(task) || 0),
        subtitleInspectorInfo.value.folderPath === item.folder_path ? Number(subtitleInspectorInfo.value.totalFiles || 0) : 0
      )
      return {
        ...item,
        task_id: task.id,
        queue_state: item.queue_state === 'create_failed'
          ? item.queue_state
          : (task.manual_match_completed ? 'manual_match_completed' : 'queued'),
        queue_message: item.queue_state === 'create_failed'
          ? item.queue_message
          : (task.current_step || getRJSubtitleTaskStatusLabel(task)),
        rjcode: task.rjcode || item.rjcode,
        audio_count: nextAudioCount,
        existing_subtitle_count: nextExistingCount,
        manual_match_completed: Boolean(task.manual_match_completed),
        manual_match_applied_pairs: Number(task.manual_match_applied_pairs || 0),
        manual_match_deleted_subtitles: Number(task.manual_match_deleted_subtitles || 0),
        status: nextExistingCount > 0 ? 'existing' : (item.status || '')
      }
    })
  subtitleSelectionPage.value = Math.min(subtitleSelectionPage.value, subtitleSelectionTotalPages.value)
}
function resolveAutoActiveSubtitleTask (tasks = visibleSubtitleTasks.value) {
  const orderedTasks = sortSubtitleTasksForWorkbench(tasks)
  const preferredTask = findTaskMatchingPreferredSelection(orderedTasks)
  if (preferredTask) return preferredTask
  const processing = orderedTasks.find(task => task.status === 'processing')
  if (processing) return processing
  const pending = orderedTasks.find(task => task.status === 'pending')
  if (pending) return pending
  const manualMatched = orderedTasks.find(task => Boolean(task?.manual_match_completed))
  if (manualMatched) return manualMatched
  const completed = orderedTasks.find(task => task.status === 'completed')
  if (completed) return completed
  const failed = orderedTasks.find(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task))
  if (failed) return failed
  return orderedTasks[0] || null
}

function resolveCurrentSubtitleTaskId (tasks = visibleSubtitleTasks.value) {
  const orderedTasks = sortSubtitleTasksForWorkbench(tasks)
  if (subtitleActiveTaskId.value && orderedTasks.some(task => task.id === subtitleActiveTaskId.value)) {
    return subtitleActiveTaskId.value
  }
  return resolveAutoActiveSubtitleTask(orderedTasks)?.id || ''
}
const orderedSubtitleTasks = computed(() => sortSubtitleTasksForWorkbench(visibleSubtitleTasks.value))
const subtitleQueueTasks = computed(() => orderedSubtitleTasks.value)
const inspectableSubtitleTasks = computed(() => {
  const tasks = orderedSubtitleTasks.value.filter(task => task.subtitle_dir)
  const preferredTask = findTaskMatchingPreferredSelection(tasks)
  if (!preferredTask) return tasks
  return [preferredTask, ...tasks.filter(task => task.id !== preferredTask.id)]
})
const activeSubtitleTask = computed(() => {
  if (!orderedSubtitleTasks.value.length) return null
  if (subtitleActiveTaskId.value) {
    const manualTask = orderedSubtitleTasks.value.find(task => task.id === subtitleActiveTaskId.value)
    if (manualTask) return manualTask
  }
  return resolveAutoActiveSubtitleTask(orderedSubtitleTasks.value)
})
const compactSubtitleTasks = computed(() => orderedSubtitleTasks.value.filter(task => task.id !== activeSubtitleTask.value?.id))
const subtitleClearableTaskCounts = computed(() => {
  const clearable = subtitleQueueTasks.value.filter(task => canClearCurrentSubtitleTask(task))
  return {
    completed: clearable.filter(task => task.status === 'completed' && !isRJSubtitleTaskCancelled(task)).length,
    failed: clearable.filter(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task)).length,
    finished: clearable.length
  }
})
const activeSubtitleInspectTask = computed(() => subtitleTasks.value.find(task => task.id === subtitleInspectorInfo.value.taskId) || null)
const linkedSubtitleImportSourceModes = new Set(['linked_translation_archive_import', 'subtitle_folder_import'])
function normalizeSubtitleTaskSourceMode(value) {
  return String(value || '').trim().toLowerCase()
}
function isLinkedSubtitleImportSourceMode(value) {
  return linkedSubtitleImportSourceModes.has(normalizeSubtitleTaskSourceMode(value))
}
const canOpenSubtitleInspectorFilterDeleteDialog = computed(() => {
  const libraryId = subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value
  return Boolean(libraryId && String(subtitleInspectorInfo.value.folderPath || subtitleInspectorInfo.value.subtitleDir || '').trim())
})
const isLinkedSubtitleImportWorkbench = computed(() => isLinkedSubtitleImportSourceMode(activeSubtitleInspectTask.value?.source_mode || subtitleInspectorInfo.value.sourceMode || ''))
const subtitleManualApplyLabel = computed(() => isLinkedSubtitleImportWorkbench.value ? '重命名并导入' : '一键应用同名')
function matchesSubtitleExecutableFilter (item, filter = subtitleSelectionFilter.value) {
  if (filter === 'all') return true
  if (filter === 'ready') return !item?.queue_state || ['ready', 'checking_subtitle'].includes(item?.queue_state)
  if (filter === 'checking_subtitle') return item?.queue_state === 'checking_subtitle'
  if (filter === 'queued') return item?.queue_state === 'queued'
  if (filter === 'creating') return item?.queue_state === 'creating'
  if (filter === 'skipped_existing') return item?.queue_state === 'skipped_existing'
  if (filter === 'existing_task') return item?.queue_state === 'existing_task'
  if (filter === 'create_failed') return item?.queue_state === 'create_failed'
  return true
}
function isSubtitleSkippedSelectionFilterActive (key) {
  return Array.isArray(subtitleSkippedSelectionFilter.value) && subtitleSkippedSelectionFilter.value.includes(key)
}
function toggleSubtitleSkippedSelectionFilter (key) {
  const current = Array.isArray(subtitleSkippedSelectionFilter.value) ? [...subtitleSkippedSelectionFilter.value] : []
  if (current.includes(key)) {
    subtitleSkippedSelectionFilter.value = current.filter(item => item !== key)
    return
  }
  subtitleSkippedSelectionFilter.value = [...current, key]
}
function matchesSubtitleSkippedSelectionFilter (item, filter = subtitleSkippedSelectionFilter.value) {
  const activeFilters = Array.isArray(filter) ? filter : []
  if (!activeFilters.length) return true
  if (activeFilters.includes('skipped_existing') && ['skipped_existing', 'skipped_kikoeru_existing'].includes(item?.queue_state || '')) {
    return true
  }
  return activeFilters.includes(item?.queue_state || '')
}
const subtitleSelectionDisplayItems = computed(() => subtitleDialogSelection.value)
const subtitleExecutableSelectionItems = computed(() => subtitleDialogSelection.value.filter(item => !String(item?.queue_state || '').startsWith('skipped_')))
const subtitleSelectionFilterOptions = computed(() => ([
  { key: 'all', label: '全部', value: subtitleExecutableSelectionItems.value.length },
  { key: 'ready', label: '待处理', value: subtitleExecutableSelectionItems.value.filter(item => !item?.queue_state || item?.queue_state === 'ready' || item?.queue_state === 'checking_subtitle').length },
  { key: 'checking_subtitle', label: '检测中', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'checking_subtitle').length },
  { key: 'queued', label: '已入任务', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'queued').length },
  { key: 'creating', label: '加入中', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'creating').length },
  { key: 'existing_task', label: '任务已存在', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'existing_task').length },
  { key: 'create_failed', label: '加入失败', value: subtitleExecutableSelectionItems.value.filter(item => item?.queue_state === 'create_failed').length }
]).filter(item => item.key === 'all' || item.value > 0))
const subtitleExecutableDisplayItems = computed(() => subtitleExecutableSelectionItems.value.filter(item => matchesSubtitleExecutableFilter(item)))
const subtitleSkippedSelectionItems = computed(() => subtitleDialogSelection.value.filter(item => String(item?.queue_state || '').startsWith('skipped_')))
const subtitleSkippedSelectionFilterOptions = computed(() => ([
  { key: 'skipped_existing', label: '已有字幕跳过', value: subtitleSkippedSelectionItems.value.filter(item => ['skipped_existing', 'skipped_kikoeru_existing'].includes(item?.queue_state)).length },
  { key: 'skipped_no_subtitle', label: '远程无字幕', value: subtitleSkippedSelectionItems.value.filter(item => item?.queue_state === 'skipped_no_subtitle').length }
]).filter(item => item.value > 0))
const filteredSubtitleSkippedSelectionItems = computed(() => subtitleSkippedSelectionItems.value.filter(item => matchesSubtitleSkippedSelectionFilter(item)))
const subtitleSelectionTotalPages = computed(() => Math.max(1, Math.ceil(Math.max(subtitleExecutableDisplayItems.value.length, 1) / subtitleSelectionPageSize)))
const subtitleSelectionProgressText = computed(() => {
  if (!subtitleSelectionLoading.value || !subtitleSelectionScanTotal.value) return ''
  const currentName = getFileName(subtitleSelectionScanCurrent.value)
  return currentName
    ? `扫描中 ${subtitleSelectionScanDone.value}/${subtitleSelectionScanTotal.value} · ${currentName}`
    : `扫描中 ${subtitleSelectionScanDone.value}/${subtitleSelectionScanTotal.value}`
})
const subtitlePendingScanResults = computed(() => subtitleScanTargetResults.value.filter(item => item.status === 'pending'))
const subtitleSkippedScanResults = computed(() => subtitleScanTargetResults.value.filter(item => ['no_audio', 'no_match', 'failed'].includes(item.status)))
function matchesSubtitleSkipFilter (item, filter = subtitleScanSkipFilter.value) {
  if (filter === 'all') return true
  return item?.status === filter
}
const subtitleSkippedScanFilterOptions = computed(() => ([
  { key: 'all', label: '全部', value: subtitleSkippedScanResults.value.length },
  { key: 'no_audio', label: '无音频', value: subtitleSkippedScanResults.value.filter(item => item.status === 'no_audio').length },
  { key: 'no_match', label: '未识别', value: subtitleSkippedScanResults.value.filter(item => item.status === 'no_match').length },
  { key: 'failed', label: '失败', value: subtitleSkippedScanResults.value.filter(item => item.status === 'failed').length }
]).filter(item => item.key === 'all' || item.value > 0))
const filteredSubtitleSkippedScanResults = computed(() => subtitleSkippedScanResults.value.filter(item => matchesSubtitleSkipFilter(item)))
const subtitleScanSummary = computed(() => ({
  pending: subtitlePendingScanResults.value.length,
  success: subtitleScanTargetResults.value.filter(item => item.status === 'success').length,
  noAudio: subtitleScanTargetResults.value.filter(item => item.status === 'no_audio').length,
  noMatch: subtitleScanTargetResults.value.filter(item => item.status === 'no_match').length,
  failed: subtitleScanTargetResults.value.filter(item => item.status === 'failed').length
}))
const subtitleScanSessionSummary = computed(() => ([
  { key: 'found', label: '识别RJ', value: subtitleScanSession.value.foundDirectories },
  { key: 'existing', label: '已有字幕跳过', value: subtitleScanSession.value.existingSubtitles },
  { key: 'noSubtitle', label: '远程无字幕跳过', value: subtitleScanSession.value.noSubtitleTargets },
  { key: 'created', label: '加入任务成功', value: subtitleScanSession.value.createdTasks },
  { key: 'exists', label: '任务已存在', value: subtitleScanSession.value.existingTasks },
  { key: 'failed', label: '加入失败', value: subtitleScanSession.value.createFailed }
]).filter(item => item.value > 0))
const pagedSubtitleSelectionItems = computed(() => {
  const start = (subtitleSelectionPage.value - 1) * subtitleSelectionPageSize
  return subtitleExecutableDisplayItems.value.slice(start, start + subtitleSelectionPageSize)
})
const focusedSubtitleSelectionItem = computed(() => {
  if (!subtitleSelectionDisplayItems.value.length) return null
  return subtitleSelectionDisplayItems.value.find(item => buildSubtitleSelectionKey(item) === subtitlePreferredSelectionKey.value) || subtitleSelectionDisplayItems.value[0]
})
const activeSubtitleTaskProgressLogs = computed(() => {
  const entries = activeSubtitleTask.value?.progress_log || []
  return [...entries.slice(-12)].reverse()
})
const subtitleInspectorRoot = computed(() => buildTree(subtitleInspectorItems.value))
const subtitleInspectorFilteredRoot = computed(() => {
  const keyword = subtitleInspectorSearch.value.trim().toLowerCase()
  return keyword ? filterTree(subtitleInspectorRoot.value, keyword) : subtitleInspectorRoot.value
})
const subtitleInspectorFlatTree = computed(() => flattenTree(subtitleInspectorFilteredRoot.value, 0, subtitleInspectorExpandedIds.value))
const subtitleInspectorHasDirectories = computed(() => subtitleInspectorItems.value.some(item => item?.type === 'dir'))
const subtitleInspectorBusy = computed(() => subtitleInspectorLoading.value || subtitleInspectorDeleting.value || subtitlePairApplying.value)
const subtitleInspectorAudioFiles = computed(() => (
  (subtitleInspectorAudioItems.value || [])
    .filter(item => isAudioFileName(item?.name || '') && !isSubtitleRelativePath(item?.relative_path || item?.name || ''))
    .sort((left, right) => compareSubtitleWorkbenchNames(left?.name, right?.name))
))
const subtitleInspectorSubtitleFiles = computed(() => (
  (subtitleInspectorItems.value || [])
    .filter(item => isSubtitleFileName(item?.name || ''))
    .sort((left, right) => compareSubtitleWorkbenchNames(left?.name, right?.name))
))
const filteredSubtitleInspectorAudioFiles = computed(() => {
  const keyword = subtitleInspectorAudioSearch.value.trim().toLowerCase()
  const items = subtitleInspectorAudioFiles.value.filter(item => {
    if (subtitleAudioFilterMode.value === 'paired') return isAudioPaired(item.path)
    if (subtitleAudioFilterMode.value === 'unpaired') return !isAudioPaired(item.path)
    return true
  })
  return keyword ? items.filter(item => (item.name || '').toLowerCase().includes(keyword) || (item.relative_path || '').toLowerCase().includes(keyword)) : items
})
const filteredSubtitleInspectorSubtitleFiles = computed(() => {
  const keyword = subtitleInspectorSubtitleSearch.value.trim().toLowerCase()
  const items = subtitleInspectorSubtitleFiles.value.filter(item => {
    if (subtitleSubtitleFilterMode.value === 'paired') return isSubtitlePaired(item.path)
    if (subtitleSubtitleFilterMode.value === 'unpaired') return !isSubtitlePaired(item.path)
    return true
  })
  return keyword ? items.filter(item => (item.name || '').toLowerCase().includes(keyword) || (item.relative_path || '').toLowerCase().includes(keyword)) : items
})
const canAddSubtitleManualPair = computed(() => Boolean(subtitleMatchSelection.value.audioPath && subtitleMatchSelection.value.subtitlePath))
const canBuildSequenceSubtitlePairs = computed(() => {
  const audioCount = subtitleSequenceSelection.value.audioPaths.length
  const subtitleCount = subtitleSequenceSelection.value.subtitlePaths.length
  return audioCount > 0 && audioCount === subtitleCount
})
const subtitleInspectorSelectableRows = computed(() => subtitleInspectorFlatTree.value.filter(row => row?.type === 'file' || row?.type === 'dir'))
const subtitleInspectorAllSelected = computed(() => subtitleInspectorSelectableRows.value.length > 0 && subtitleInspectorSelectableRows.value.every(row => subtitleInspectorSelectedIds.value.has(row.id)))
const subtitleInspectorSomeSelected = computed(() => !subtitleInspectorAllSelected.value && subtitleInspectorSelectableRows.value.some(row => subtitleInspectorSelectedIds.value.has(row.id)))
const subtitleInspectorSelectedRows = computed(() => subtitleInspectorFlatTree.value.filter(row => subtitleInspectorSelectedIds.value.has(row.id)))
const subtitleWorkbenchCtx = computed(() => ({
  subtitleInspectorInfo: subtitleInspectorInfo.value,
  subtitleInspectorBusy: subtitleInspectorBusy.value,
  subtitleInspectorLoading: subtitleInspectorLoading.value,
  subtitleInspectorDeleting: subtitleInspectorDeleting.value,
  subtitleInspectorHasDirectories: subtitleInspectorHasDirectories.value,
  subtitleInspectorAudioFiles: subtitleInspectorAudioFiles.value,
  subtitleInspectorFlatTree: subtitleInspectorFlatTree.value,
  subtitleInspectorSelectedRows: subtitleInspectorSelectedRows.value,
  subtitleInspectorSelectedIds: subtitleInspectorSelectedIds.value,
  subtitleInspectorExpandedIds: subtitleInspectorExpandedIds.value,
  subtitleInspectorSearch: subtitleInspectorSearch.value,
  subtitleInspectorAudioSearch: subtitleInspectorAudioSearch.value,
  subtitleInspectorSubtitleSearch: subtitleInspectorSubtitleSearch.value,
  subtitleInspectorAllSelected: subtitleInspectorAllSelected.value,
  subtitleInspectorSomeSelected: subtitleInspectorSomeSelected.value,
  inspectableSubtitleTasks: inspectableSubtitleTasks.value,
  activeSubtitleInspectTask: activeSubtitleInspectTask.value,
  subtitleSequenceMode: subtitleSequenceMode.value,
  subtitleSequenceSelection: subtitleSequenceSelection.value,
  subtitleManualPairs: subtitleManualPairs.value,
  subtitleSelectedManualPairId: subtitleSelectedManualPairId.value,
  subtitlePairApplying: subtitlePairApplying.value,
  subtitleManualApplyLabel: subtitleManualApplyLabel.value,
  isLinkedSubtitleImportWorkbench: isLinkedSubtitleImportWorkbench.value,
  canOpenSubtitleInspectorFilterDeleteDialog: canOpenSubtitleInspectorFilterDeleteDialog.value,
  subtitleAudioFilterMode: subtitleAudioFilterMode.value,
  subtitleSubtitleFilterMode: subtitleSubtitleFilterMode.value,
  subtitleMatchSelection: subtitleMatchSelection.value,
  filteredSubtitleInspectorAudioFiles: filteredSubtitleInspectorAudioFiles.value,
  filteredSubtitleInspectorSubtitleFiles: filteredSubtitleInspectorSubtitleFiles.value,
  canBuildSequenceSubtitlePairs: canBuildSequenceSubtitlePairs.value,
  canAddSubtitleManualPair: canAddSubtitleManualPair.value,
  reloadSubtitleInspector,
  expandSubtitleInspectorTree,
  collapseSubtitleInspectorTree,
  inspectSubtitleTask,
  getTaskDisplayRJCode,
  getTaskSourceRJCode,
  getFileName,
  formatFileSize,
  buildAutoSubtitlePairs,
  buildSequenceOrOrderedSubtitlePairs,
  applySubtitleManualPairs,
  openSubtitleInspectorFilterDeleteDialog,
  setSubtitleSequenceMode: value => { subtitleSequenceMode.value = value },
  setSubtitleAudioFilterMode: value => { subtitleAudioFilterMode.value = value },
  setSubtitleSubtitleFilterMode: value => { subtitleSubtitleFilterMode.value = value },
  setSubtitleInspectorAudioSearch: value => { subtitleInspectorAudioSearch.value = value },
  setSubtitleInspectorSubtitleSearch: value => { subtitleInspectorSubtitleSearch.value = value },
  setSubtitleInspectorSearch: value => {
    subtitleInspectorSearch.value = value
    onSubtitleInspectorSearchInput()
  },
  setSubtitleSelectedManualPairId: value => { subtitleSelectedManualPairId.value = value },
  isAudioPaired,
  isAudioSuspicious,
  getSubtitleSequenceIndex,
  selectSubtitleAudio,
  addSubtitleManualPair,
  clearSubtitleSequenceSelection,
  clearSubtitleManualPairs,
  getSubtitlePairConfidenceLabel,
  removeSubtitleManualPair,
  isSubtitlePaired,
  isSubtitleSuspicious,
  selectSubtitleFile,
  batchDeleteSubtitleTreeEntries,
  clearSubtitleInspectorSelection,
  toggleAllSubtitleInspectorRows,
  handleSubtitleInspectorRowClick,
  toggleSubtitleInspectorSelect,
  toggleSubtitleInspectorExpand,
  resolveSubtitleTreeIcon,
  formatDate,
  openSubtitleRenameDialog,
  deleteSubtitleTreeEntry
}))
const currentFolderSubtitleItem = computed(() => {
  if (!canProcessCurrentFolder.value || !currentFolderRJCode.value) return null
  return {
    rjcode: currentFolderRJCode.value,
    folder_name: getFileName(currentPath.value),
    folder_path: currentPath.value,
    library_id: selectedLibraryId.value
  }
})
const selectedSubtitleCandidates = computed(() => selectedRows.value.filter(row => canFetchRJSubtitle(row)))
const selectedApiRenameRows = computed(() => selectedRows.value.filter(row => row?.is_directory))
const apiRenameBusy = computed(() => Boolean(apiRenamingId.value) || batchRenaming.value)

function isBatchApiRenameTarget (row) {
  return batchRenaming.value && batchApiRenameTargetIds.value.has(row?.id)
}

function isBatchApiRenameRunning (row) {
  return batchApiRenameRunningIds.value.has(row?.id)
}

function bindLibraryKeydown () {
  if (libraryKeydownBound) return
  window.addEventListener('keydown', handleSubtitleDialogKeydown)
  libraryKeydownBound = true
}

function unbindLibraryKeydown () {
  if (!libraryKeydownBound) return
  window.removeEventListener('keydown', handleSubtitleDialogKeydown)
  libraryKeydownBound = false
}

function stopLibraryPolling () {
  clearStatsPoll()
  clearListPoll()
  clearSubtitleStatusPoll()
}

async function initializeLibraryPage () {
  if (libraryInitialized) return
  restoreUploadWorkbenchState()
  await loadLibraries()
  loadRJSubtitlePreferences()
  restoreSubtitleScanWorkspace()
  if (selectedLibraryId.value) {
    await refreshStats(false, { silent: true })
  }
  if (trackedUploadTaskIds.value.length) {
    await refreshUploadWorkbench({ silent: true })
  }
  libraryInitialized = true
}

async function resumeLibraryPage () {
  bindLibraryKeydown()
  await refreshLibrary({ silent: true })
  await refreshStats(false, { silent: true })
  if (trackedUploadTaskIds.value.length) {
    await refreshUploadWorkbench({ silent: true })
  }
  if (subtitleDialogSessionActive.value) {
    await refreshRJSubtitleStatus(false, { silent: true })
  }
}

onMounted(async () => {
  bindLibraryKeydown()
  await initializeLibraryPage()
  libraryViewActive = true
  await consumeSubtitleRouteFocus()
  await consumeSubtitleBatchSelectionRoute()
})

onActivated(async () => {
  if (libraryViewActive) return
  libraryViewActive = true
  await resumeLibraryPage()
  await consumeSubtitleRouteFocus()
  await consumeSubtitleBatchSelectionRoute()
})

onDeactivated(() => {
  libraryViewActive = false
  stopLibraryPolling()
  stopUploadWorkbenchPolling()
  unbindLibraryKeydown()
  if (filterDeleteBackgroundTimer) {
    clearInterval(filterDeleteBackgroundTimer)
    filterDeleteBackgroundTimer = null
  }
})

onBeforeUnmount(() => {
  libraryViewActive = false
  stopLibraryPolling()
  stopUploadWorkbenchPolling()
  unbindLibraryKeydown()
  if (filterDeleteBackgroundTimer) {
    clearInterval(filterDeleteBackgroundTimer)
    filterDeleteBackgroundTimer = null
  }
})

watch(uploadWorkbenchVisible, () => {
  persistUploadWorkbenchState()
  if (uploadWorkbenchVisible.value || uploadWorkbenchBackgroundActive.value) startUploadWorkbenchPolling()
  else stopUploadWorkbenchPolling()
})

watch(uploadWorkbenchBackgroundActive, () => {
  persistUploadWorkbenchState()
  if (uploadWorkbenchVisible.value || uploadWorkbenchBackgroundActive.value) startUploadWorkbenchPolling()
  else stopUploadWorkbenchPolling()
})

watch(trackedUploadTaskIds, () => {
  persistUploadWorkbenchState()
}, { deep: true })

watch(pageSize, async value => {
  storeNumber(PAGE_SIZE_KEY, value)
  currentPage.value = 1
  if (selectedLibraryId.value) await refreshLibrary()
})

watch(currentPage, async (value, oldValue) => {
  if (value === oldValue || !selectedLibraryId.value) return
  storeNumber('kikoeru.ui.library.page', value)
  const forceRefresh = forceLibraryRefreshOnce
  forceLibraryRefreshOnce = false
  await refreshLibrary({ forceRefresh })
})

watch(toolbarActionScope, value => {
  storeString(LIBRARY_ACTION_SCOPE_KEY, value)
})

watch(searchResultKind, value => {
  storeString(SEARCH_RESULT_KIND_KEY, value || 'all')
})

watch(searchExact, value => {
  storeString(SEARCH_EXACT_KEY, value ? '1' : '0')
})

watch(selectedLibraryId, async (newId, oldId) => {
  if (!newId) return
  if (oldId) saveLibraryState(oldId)
  restoreLibraryState(newId)
  if (pendingLibrarySearchRestore.value?.libraryId === newId) {
    const restoreState = pendingLibrarySearchRestore.value
    searchQuery.value = restoreState.searchQuery || ''
    searchExact.value = Boolean(restoreState.searchExact)
    searchResultKind.value = restoreState.searchResultKind || 'all'
    currentPath.value = restoreState.currentPath || ''
    browseRootPath.value = restoreState.browseRootPath || ''
    currentPage.value = Number(restoreState.page || 1)
    sortBy.value = restoreState.sortBy || DEFAULT_SORT_BY
    sortOrder.value = restoreState.sortOrder || DEFAULT_SORT_ORDER
    librarySearchState.value = createLibrarySearchState({
      active: true,
      query: restoreState.searchState?.query || restoreState.searchQuery || '',
      rootPath: restoreState.searchState?.rootPath || restoreState.currentPath || '',
      truncated: Boolean(restoreState.searchState?.truncated),
      scannedDirectories: Number(restoreState.searchState?.scannedDirectories || 0),
      globalRemote: Boolean(restoreState.searchState?.globalRemote),
      searchedLibraries: Number(restoreState.searchState?.searchedLibraries || 0),
      hitLibraries: Number(restoreState.searchState?.hitLibraries || 0),
      exactSearch: Boolean(restoreState.searchState?.exactSearch ?? restoreState.searchExact),
      resultKind: restoreState.searchState?.resultKind || restoreState.searchResultKind || 'all'
    })
    locatedLibraryPath.value = ''
    pendingLibrarySearchRestore.value = null
  }
  if (pendingLibraryLocate.value?.libraryId === newId) {
    const targetPath = pendingLibraryLocate.value.path || ''
    const highlightPath = pendingLibraryLocate.value.highlightPath || targetPath
    searchQuery.value = ''
    librarySearchState.value = createLibrarySearchState()
    currentPath.value = targetPath
    currentPage.value = 1
    locatedLibraryPath.value = highlightPath
    pendingLibraryLocate.value = null
  }
  clearSelection()
  subtitlePreferredSelectionKey.value = ''
  clearSubtitleInspectorState()
  await refreshLibrary()
  refreshStats(false, { silent: true })
})

watch(subtitleTasks, () => {
  const normalized = normalizeSubtitleTaskFilterSelection(subtitleTaskFilter.value, subtitleTaskManualFilter.value)
  if (normalized.taskFilter !== subtitleTaskFilter.value) {
    subtitleTaskFilter.value = normalized.taskFilter
  }
  if (normalized.manualFilter !== subtitleTaskManualFilter.value) {
    subtitleTaskManualFilter.value = normalized.manualFilter
  }
  syncSubtitleTaskListState()
})

watch(visibleSubtitleTasks, tasks => {
  if (!subtitleDialogVisible.value) return
  if (tasks.length) return
  clearSubtitleInspectorState()
}, { deep: true })

watch(activeSubtitleTask, task => {
  subtitleTaskDetailPanels.value = buildDefaultSubtitleTaskDetailPanels(task)
}, { immediate: true })

watch(inspectableSubtitleTasks, tasks => {
  if (!subtitleDialogVisible.value) return
  if (tasks.length) return
  clearSubtitleInspectorState()
}, { deep: true })

watch(subtitleExecutableDisplayItems, items => {
  if (!items.length) {
    subtitleSelectionPage.value = 1
    return
  }
  if (subtitleSelectionPage.value > subtitleSelectionTotalPages.value) {
    subtitleSelectionPage.value = subtitleSelectionTotalPages.value
  }
})

watch(subtitleOptions, value => {
  storeJson(SUBTITLE_OPTIONS_KEY, value)
}, { deep: true })

watch([
  subtitleDialogVisible,
  subtitleDialogBackgroundActive,
  subtitleSelectionLoading,
  subtitleSelectionScanDone,
  subtitleSelectionScanTotal,
  subtitleSelectionScanCurrent,
  subtitleSelectionSourceItems,
  subtitleScannedSelectionItems,
  subtitleScanTargetResults,
  subtitleScanRetryingPath,
  subtitleScanSession,
  subtitleDialogSelection,
  subtitlePreferredSelectionKey,
  subtitleSelectionPage,
  subtitleSelectionFilter,
  subtitleScanSkipFilter,
  subtitleSkippedSelectionFilter,
  subtitleExecutableCollapsed,
  subtitleSkippedCollapsed,
  subtitleScanTargetsCollapsed
], () => {
  persistSubtitleScanWorkspace()
}, { deep: true })

watch(() => subtitleOptions.value.namingStrategy, () => {
  syncSubtitlePairTargetNames()
})

watch([subtitleDialogVisible, subtitleDialogBackgroundActive], async ([visible, backgroundActive]) => {
  if (!visible && !backgroundActive) {
    clearSubtitleStatusPoll()
    subtitleActiveTaskId.value = ''
    subtitleScanRetryingPath.value = ''
    subtitleSelectionScanCurrent.value = ''
    return
  }
  if (visible) subtitleActiveTaskId.value = ''
  await refreshRJSubtitleStatus(false, { silent: true })
})

watch(
  () => route.fullPath,
  async () => {
    if (!libraryViewActive) return
    await consumeSubtitleRouteFocus()
  }
)

function loadNumber (key, fallback) {
  try {
    const value = Number(localStorage.getItem(key))
    return Number.isFinite(value) && value > 0 ? value : fallback
  } catch (_) {
    return fallback
  }
}

function storeNumber (key, value) {
  try { localStorage.setItem(key, String(value)) } catch (_) {}
}

function loadString (key, fallback) {
  try {
    const value = localStorage.getItem(key)
    return value || fallback
  } catch (_) {
    return fallback
  }
}

function storeString (key, value) {
  try { localStorage.setItem(key, String(value)) } catch (_) {}
}

function loadJson (key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch (_) {
    return fallback
  }
}

function storeJson (key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch (_) {}
}

async function loadLibraries () {
  const data = await libraryApi.listLibraries()
  libraries.value = data.libraries || []
  const validIds = new Set(libraries.value.map(item => item.id))
  const fallbackId = data.default_library_id || libraries.value[0]?.id || ''
  if (!selectedLibraryId.value || !validIds.has(selectedLibraryId.value)) {
    selectedLibraryId.value = fallbackId
    restoreLibraryState(selectedLibraryId.value)
  }
}

function saveLibraryState (libraryId) {
  const existingState = libraryState.value[libraryId] || {}
  const pageByPath = { ...(existingState.pageByPath || {}) }
  pageByPath[getLibraryPageStateKey()] = currentPage.value
  libraryState.value[libraryId] = {
    ...existingState,
    searchQuery: searchQuery.value,
    searchExact: searchExact.value,
    searchResultKind: searchResultKind.value,
    currentPage: currentPage.value,
    currentPath: currentPath.value,
    browseRootPath: browseRootPath.value,
    sortBy: sortBy.value,
    sortOrder: sortOrder.value,
    pageByPath
  }
}

function restoreLibraryState (libraryId) {
  const state = libraryState.value[libraryId] || {}
  searchQuery.value = state.searchQuery || ''
  searchExact.value = Boolean(state.searchExact ?? (loadString(SEARCH_EXACT_KEY, '0') === '1'))
  searchResultKind.value = state.searchResultKind || loadString(SEARCH_RESULT_KIND_KEY, 'all')
  currentPath.value = state.currentPath || ''
  browseRootPath.value = state.browseRootPath || ''
  currentPage.value = getRememberedDirectoryPage(currentPath.value, state.currentPage || 1, browseRootPath.value)
  sortBy.value = state.sortBy || loadString('kikoeru.ui.library.sortBy', DEFAULT_SORT_BY)
  sortOrder.value = state.sortOrder || loadString('kikoeru.ui.library.sortOrder', DEFAULT_SORT_ORDER)
}

function clearStatsPoll () {
  if (statsPollTimer) {
    clearTimeout(statsPollTimer)
    statsPollTimer = null
  }
}

function scheduleStatsPoll (items) {
  clearStatsPoll()
  if ((items || []).some(item => item?.status === 'pending')) {
    statsPollTimer = setTimeout(() => refreshStats(false, { silent: true }), 1500)
  }
}

function clearListPoll () {
  if (listPollTimer) {
    clearTimeout(listPollTimer)
    listPollTimer = null
  }
}

function scheduleListPoll (items) {
  clearListPoll()
  if (isRemoteCurrentLibrary.value) return
  if ((items || []).some(item => item?.size_status && item.size_status !== 'ready')) {
    listPollTimer = setTimeout(() => refreshLibrary({ silent: true }), 2000)
  }
}

function clearSubtitleStatusPoll () {
  if (subtitleStatusPollTimer) {
    clearTimeout(subtitleStatusPollTimer)
    subtitleStatusPollTimer = null
  }
}

function scheduleSubtitleStatusPoll (items) {
  clearSubtitleStatusPoll()
  if (!subtitleDialogSessionActive.value) return
  if ((items || []).some(item => ['pending', 'processing'].includes(item?.status))) {
    subtitleStatusPollTimer = setTimeout(() => refreshRJSubtitleStatus(false, { silent: true }), 3000)
  }
}

async function refreshStats (forceRefresh = false, options = {}) {
  const { silent = false, refreshLibraryId = null } = options
  clearStatsPoll()
  if (silent) statsPolling.value = true
  else statsLoading.value = true
  try {
    const data = await libraryApi.getStats(forceRefresh, refreshLibraryId)
    const nextMap = {}
    for (const item of data.libraries || []) nextMap[item.library_id] = item
    statsMap.value = nextMap
    aggregateStats.value = data.all_libraries || { folder_count: 0, total_size_gb: 0, total_size_bytes: 0 }
    scheduleStatsPoll(data.libraries || [])
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '获取统计失败')
  } finally {
    if (silent) statsPolling.value = false
    else statsLoading.value = false
  }
}

async function handleStatsAction () {
  if (canCancelStats.value) {
    await cancelStats()
    return
  }
  await refreshStats(true, { refreshLibraryId: selectedLibraryId.value })
}

async function cancelStats () {
  if (!selectedLibraryId.value) return
  statsLoading.value = true
  try {
    const data = await libraryApi.cancelStats(selectedLibraryId.value)
    ElMessage.success(data.message || '统计任务已取消')
    await refreshStats(false, { silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '取消统计失败')
  } finally {
    statsLoading.value = false
  }
}

async function refreshLibrary (options = {}) {
  const { silent = false, forceRefresh = false } = options
  if (!selectedLibraryId.value) return
  clearListPoll()
  if (silent) listPolling.value = true
  else loading.value = true
  try {
    const data = await libraryApi.browseFiles({
      libraryId: selectedLibraryId.value,
      page: currentPage.value,
      pageSize: pageSize.value,
      search: searchQuery.value.trim(),
      searchExact: searchExact.value,
      searchResultKind: searchResultKind.value,
      currentPath: currentPath.value,
      sortBy: sortBy.value,
      sortOrder: sortOrder.value,
      forceRefresh
    })
    files.value = data.files || []
    totalFiles.value = data.total || 0
    if (data.libraries?.length) libraries.value = data.libraries
    if (data.library_id && data.library_id !== selectedLibraryId.value) {
      if (data.auto_locate_path) {
        pendingLibraryLocate.value = {
          libraryId: data.library_id,
          path: data.auto_locate_path,
          highlightPath: data.auto_locate_highlight_path || data.auto_locate_path
        }
      }
      selectedLibraryId.value = data.library_id
      return
    }
    currentPath.value = data.current_path || currentPath.value || data.browse_root_path || ''
    browseRootPath.value = data.browse_root_path || browseRootPath.value || currentPath.value
    parentPath.value = data.parent_path || ''
    librarySearchState.value = createLibrarySearchState({
      active: Boolean(data.search_mode),
      query: data.search_query || searchQuery.value.trim(),
      rootPath: data.search_root_path || '',
      truncated: Boolean(data.search_truncated),
      scannedDirectories: Number(data.scanned_directories || 0),
      globalRemote: Boolean(data.search_global_remote),
      searchedLibraries: Number(data.searched_library_count || 0),
      hitLibraries: Number(data.hit_library_count || 0),
      exactSearch: Boolean(data.search_exact ?? searchExact.value),
      resultKind: data.search_result_kind || searchResultKind.value || 'all'
    })
    scheduleListPoll(files.value)
    const maxPage = Math.max(1, Math.ceil(Math.max(totalFiles.value, 1) / pageSize.value))
    if (currentPage.value > maxPage) currentPage.value = maxPage
    await applyTableSortIndicator()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '获取库存文件失败')
  } finally {
    if (silent) listPolling.value = false
    else loading.value = false
  }
}

async function applyTableSortIndicator () {
  await nextTick()
  const order = sortOrder.value === 'asc' ? 'ascending' : 'descending'
  const prop = sortBy.value === 'time' ? 'modified_time' : sortBy.value
  suppressSortChange.value = true
  tableRef.value?.sort(prop, order)
  await nextTick()
  suppressSortChange.value = false
}

async function handleSearch () {
  searchResultReturnState.value = createSearchResultReturnState()
  pendingLibrarySearchRestore.value = null
  locatedLibraryPath.value = ''
  const shouldRefreshNow = currentPage.value === 1
  forceLibraryRefreshOnce = true
  currentPage.value = 1
  if (shouldRefreshNow) {
    await refreshLibrary({ forceRefresh: true })
    forceLibraryRefreshOnce = false
  }
}

async function handleSortChange ({ prop, order }) {
  if (suppressSortChange.value) return
  const nextSortBy = prop === 'modified_time' ? 'time' : (prop || DEFAULT_SORT_BY)
  const nextSortOrder = order === 'ascending' ? 'asc' : order === 'descending' ? 'desc' : DEFAULT_SORT_ORDER
  sortBy.value = nextSortBy
  sortOrder.value = nextSortOrder
  storeString('kikoeru.ui.library.sortBy', sortBy.value)
  storeString('kikoeru.ui.library.sortOrder', sortOrder.value)
  saveLibraryState(selectedLibraryId.value)
  const shouldRefreshNow = currentPage.value === 1
  currentPage.value = 1
  if (shouldRefreshNow) await refreshLibrary()
}

function handleSelectionChange (selection) {
  selectedRows.value = Array.isArray(selection) ? selection : []
}

function getFileName (path) {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop()
}

function getParentPath (path) {
  const normalized = String(path || '').replace(/[\\/]+$/, '')
  if (!normalized) return ''
  const index = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'))
  return index >= 0 ? normalized.slice(0, index) : ''
}

function normalizeConflictPathKey (path) {
  return String(path || '')
    .replace(/\\/g, '/')
    .replace(/\/+/g, '/')
    .replace(/\/$/, '')
    .toLowerCase()
}

function buildRenameConflictKey (path, targetName) {
  return `${normalizeConflictPathKey(getParentPath(path))}::${String(targetName || '').trim().toLowerCase()}`
}

function escapeLibrarySearchHtml (value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeLibrarySearchRegExp (value) {
  return String(value ?? '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function renderLibrarySearchHighlight (value) {
  const text = String(value ?? '')
  const keyword = String((librarySearchState.value.query || searchQuery.value || '').trim())
  const escaped = escapeLibrarySearchHtml(text)
  if (!librarySearchState.value.active || !keyword) return escaped
  const pattern = new RegExp(`(${escapeLibrarySearchRegExp(keyword)})`, 'ig')
  return escaped.replace(pattern, '<mark class="library-search-mark">$1</mark>')
}

function extractRJCode (value) {
  if (!value) return null
  const match = String(value).match(/[RVB]J(\d{6}|\d{8})(?!\d)/i)
  return match ? match[0].toUpperCase() : null
}

function formatSize (bytes) {
  const value = Number(bytes || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let current = value
  let index = 0
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024
    index += 1
  }
  const digits = current >= 100 || index === 0 ? 0 : current >= 10 ? 1 : 2
  return `${current.toFixed(digits)} ${units[index]}`
}

function formatSpeed (bytesPerSec) {
  const value = Number(bytesPerSec || 0)
  return value > 0 ? `${formatSize(value)}/s` : '—'
}

function formatEtaSeconds (seconds) {
  const totalSeconds = Math.max(0, Math.round(Number(seconds || 0)))
  if (!totalSeconds) return '—'
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  if (hours > 0) return `${hours}时${Math.floor((totalSeconds % 3600) / 60)}分`
  return mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`
}

function canFetchRJSubtitle (row) {
  return !!row?.is_directory && isWritableCurrentLibrary.value
}

function toRJSubtitleItem (row) {
  if (!row) return null
  return {
    rjcode: row.rjcode || extractRJCode(row.path || row.name),
    folder_name: row.name || getFileName(row.path),
    folder_path: row.path,
    library_id: row.library_id || selectedLibraryId.value,
    search_hit: Boolean(row.search_hit)
  }
}

function toggleAllSelection () {
  if (!files.value.length) return
  if (isAllSelected.value) return clearSelection()
  files.value.forEach(row => tableRef.value?.toggleRowSelection(row, true))
}

function clearSelection () {
  tableRef.value?.clearSelection()
  selectedRows.value = []
}

function openLocalUploadDialog () {
  if (isRemoteCurrentLibrary.value) {
    ElMessage.warning('请先切换到本地库存后再上传到服务器')
    return
  }
  if (!selectedUploadRows.value.length) {
    ElMessage.warning('请先选中要上传的目录')
    return
  }
  if (!remoteUploadLibraries.value.length) {
    ElMessage.warning('当前没有可用的服务器库存')
    return
  }
  localUploadForm.value = {
    targetLibraryId: localUploadForm.value.targetLibraryId || remoteUploadLibraries.value[0]?.id || '',
    targetSubdir: localUploadForm.value.targetSubdir || ''
  }
  localUploadDialogVisible.value = true
}

async function submitLocalUpload () {
  const payload = arguments[0] && typeof arguments[0] === 'object' ? arguments[0] : null
  const selectedPaths = Array.isArray(payload?.selected_paths) && payload.selected_paths.length
    ? payload.selected_paths
    : selectedUploadRows.value.map(row => row.path)
  const targetLibraryId = String(payload?.target_library_id || localUploadForm.value.targetLibraryId || '').trim()
  const targetSubdir = String(payload?.target_subdir || localUploadForm.value.targetSubdir || '').trim()

  if (!selectedPaths.length) {
    ElMessage.warning('请先选中要上传的目录')
    return
  }
  if (!targetLibraryId) {
    ElMessage.warning('请选择目标服务器库存')
    return
  }
  localUploadForm.value = {
    targetLibraryId,
    targetSubdir,
  }
  localUploadSubmitting.value = true
  try {
    const sourceBasePath = currentPath.value || browseRootPath.value || currentLibrary.value?.path || ''
    const createdTaskIds = []

    for (const selectedPath of selectedPaths) {
      const requestPayload = {
        source_library_id: selectedLibraryId.value,
        source_base_path: sourceBasePath,
        selected_paths: [selectedPath],
        target_library_id: targetLibraryId,
        target_subdir: targetSubdir,
        circle_name: ''
      }
      const result = await localUploadApi.start(requestPayload)
      if (result?.task_id) {
        createdTaskIds.push(result.task_id)
        rememberUploadTaskId(result.task_id)
      }
    }

    uploadWorkbenchVisible.value = true
    uploadWorkbenchBackgroundActive.value = false
    localUploadDialogVisible.value = false
    persistUploadWorkbenchState()
    await refreshUploadWorkbench()
    ElMessage.success(`已创建 ${createdTaskIds.length || selectedPaths.length} 个目录上传任务`)
    clearSelection()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '上传失败')
  } finally {
    localUploadSubmitting.value = false
  }
}

function persistUploadWorkbenchState () {
  try {
    localStorage.setItem(LOCAL_UPLOAD_WORKBENCH_KEY, JSON.stringify({
      taskIds: trackedUploadTaskIds.value,
      visible: uploadWorkbenchVisible.value,
      background: uploadWorkbenchBackgroundActive.value
    }))
  } catch (_) {}
}

function restoreUploadWorkbenchState () {
  try {
    const raw = JSON.parse(localStorage.getItem(LOCAL_UPLOAD_WORKBENCH_KEY) || '{}')
    trackedUploadTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    uploadWorkbenchVisible.value = Boolean(raw.visible && trackedUploadTaskIds.value.length)
    uploadWorkbenchBackgroundActive.value = Boolean(raw.background && trackedUploadTaskIds.value.length)
  } catch (_) {
    trackedUploadTaskIds.value = []
    uploadWorkbenchVisible.value = false
    uploadWorkbenchBackgroundActive.value = false
  }
}

function stopUploadWorkbenchPolling () {
  if (uploadWorkbenchTimer) {
    window.clearTimeout(uploadWorkbenchTimer)
    uploadWorkbenchTimer = null
  }
}

function startUploadWorkbenchPolling () {
  if (!trackedUploadTaskIds.value.length) return
  stopUploadWorkbenchPolling()
  uploadWorkbenchTimer = window.setTimeout(() => {
    refreshUploadWorkbench({ silent: true })
  }, 2000)
}

function rememberUploadTaskId (nextTaskId) {
  const normalized = String(nextTaskId || '').trim()
  if (!normalized) return
  if (trackedUploadTaskIds.value.includes(normalized)) return
  trackedUploadTaskIds.value = [normalized, ...trackedUploadTaskIds.value]
}

async function refreshUploadWorkbench (options = {}) {
  const silent = Boolean(options?.silent)
  if (!trackedUploadTaskIds.value.length) {
    trackedUploadTasks.value = []
    stopUploadWorkbenchPolling()
    persistUploadWorkbenchState()
    return
  }
  if (!silent) uploadWorkbenchRefreshing.value = true
  try {
    const result = await localUploadApi.status({
      task_ids: trackedUploadTaskIds.value.join(','),
      include_hidden: true
    })
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    const nextTrackedTasks = trackedUploadTaskIds.value
      .map(id => allTasks.find(task => String(task?.id || '') === String(id || '')))
      .filter(Boolean)
    trackedUploadTasks.value = nextTrackedTasks
    if (nextTrackedTasks.length) {
      trackedUploadTaskIds.value = nextTrackedTasks.map(task => task.id)
    }

    const justCompleted = trackedUploadTasks.value.some(task => {
      const status = String(task?.status || '')
      return ['completed', 'failed'].includes(status)
    })
    if (justCompleted) {
      await Promise.allSettled([refreshLibrary(), refreshStats()])
    }

    const stillActive = trackedUploadTasks.value.some(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task?.status || '')))
    if (stillActive || uploadWorkbenchVisible.value || uploadWorkbenchBackgroundActive.value) startUploadWorkbenchPolling()
    else stopUploadWorkbenchPolling()
    persistUploadWorkbenchState()
  } catch (error) {
    if (!silent) ElMessage.error(error.response?.data?.detail || error.message || '获取上传任务失败')
    if (uploadWorkbenchVisible.value || uploadWorkbenchBackgroundActive.value) startUploadWorkbenchPolling()
  } finally {
    if (!silent) uploadWorkbenchRefreshing.value = false
  }
}

function hideUploadWorkbenchToBackground () {
  uploadWorkbenchVisible.value = false
  uploadWorkbenchBackgroundActive.value = true
  persistUploadWorkbenchState()
}

function resumeUploadWorkbenchFromBackground () {
  uploadWorkbenchBackgroundActive.value = false
  uploadWorkbenchVisible.value = true
  persistUploadWorkbenchState()
}

async function closeUploadWorkbench () {
  const cancellableTaskIds = trackedUploadTasks.value
    .filter(task => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(task?.status || '')))
    .map(task => String(task?.id || '').trim())
    .filter(Boolean)

  if (cancellableTaskIds.length) {
    await Promise.allSettled(cancellableTaskIds.map(taskId => taskApi.cancel(taskId)))
  }

  uploadWorkbenchVisible.value = false
  uploadWorkbenchBackgroundActive.value = false
  trackedUploadTaskIds.value = []
  trackedUploadTasks.value = []
  stopUploadWorkbenchPolling()
  persistUploadWorkbenchState()
}

function getUploadBackgroundSpeed (task) {
  const runtime = task?.upload_runtime || {}
  return Number(runtime?.speed_bytes_per_sec || runtime?.last_non_zero_speed_bytes_per_sec || 0)
}

function formatUploadBackgroundEta (task) {
  if (!task) return '—'
  const status = String(task?.status || '')
  if (['completed', 'failed'].includes(status) || uploadBackgroundPercent.value >= 100) return '完成'
  return formatEtaSeconds(task?.upload_runtime?.eta_seconds || 0)
}

function getUploadBackgroundTargetLabel (task) {
  return String(task?.task_metadata?.final_output_path || task?.task_metadata?.target_path || task?.output_path || '目标路径处理中').trim()
}

function uniqueSubtitleItems (items) {
  const seen = new Set()
  return items.filter(item => {
    if (!item?.folder_path || !item?.rjcode) return false
    const dedupeKey = `${item.library_id || ''}::${item.folder_path}`
    if (seen.has(dedupeKey)) return false
    seen.add(dedupeKey)
    return true
  })
}

function buildSubtitleScanTargetInput (target) {
  if (!target) return null
  if (typeof target === 'string') {
    return {
      path: target,
      library_id: selectedLibraryId.value,
      name: getFileName(target)
    }
  }
  const path = String(target.scan_target_path || target.folder_path || target.path || '').trim()
  if (!path) return null
  return {
    path,
    library_id: target.library_id || selectedLibraryId.value,
    name: target.folder_name || target.name || getFileName(path)
  }
}

function uniqueSubtitleScanTargets (items) {
  const seen = new Set()
  return (Array.isArray(items) ? items : []).map(buildSubtitleScanTargetInput).filter(item => {
    if (!item?.path) return false
    const key = `${item.library_id || ''}::${item.path}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function buildSubtitleScanTargetResultKey (item = {}) {
  return `${item.library_id || ''}::${item.path || ''}`
}

function normalizeRJSubtitleScanDepth (value) {
  const normalized = Number.parseInt(value, 10)
  if (Number.isNaN(normalized)) return 3
  return Math.max(1, Math.min(normalized, 10))
}

function loadRJSubtitlePreferences () {
  const saved = loadJson(SUBTITLE_OPTIONS_KEY, {})
  subtitleOptions.value = {
    overwriteExisting: saved?.overwriteExisting ?? false,
    scanDepth: normalizeRJSubtitleScanDepth(saved?.scanDepth ?? (saved?.scanOneLevelOnly === true ? 1 : 3)),
    enableMetadataMatch: saved?.enableMetadataMatch ?? true,
    skipIfExistingSubtitles: saved?.skipIfExistingSubtitles ?? false,
    namingStrategy: ['audio', 'subtitle'].includes(saved?.namingStrategy) ? saved.namingStrategy : 'audio',
    useFilterRules: saved?.useFilterRules ?? false,
    subtitleFilterRules: Array.isArray(saved?.subtitleFilterRules) ? saved.subtitleFilterRules.map(rule => normalizeSubtitleFilterRule(rule)) : [],
    showSourceSearch: saved?.showSourceSearch ?? true,
    showWrittenFiles: saved?.showWrittenFiles ?? true,
    showDownloadedFiles: saved?.showDownloadedFiles ?? true,
    showIssues: saved?.showIssues ?? true
  }
}

function normalizeStoredSubtitleScanSession (value = {}) {
  const base = createSubtitleScanSessionState()
  return Object.keys(base).reduce((acc, key) => {
    acc[key] = Math.max(0, Number(value?.[key] || 0))
    return acc
  }, {})
}

function normalizeStoredSubtitleSkippedSelectionFilter (value = []) {
  const allowed = new Set(['skipped_existing', 'skipped_no_subtitle'])
  return Array.isArray(value) ? value.filter(item => allowed.has(String(item || ''))) : []
}

function buildSubtitleScanWorkspaceSnapshot () {
  return {
    dialogVisible: Boolean(subtitleDialogVisible.value),
    backgroundActive: Boolean(subtitleDialogBackgroundActive.value),
    subtitleSelectionLoading: Boolean(subtitleSelectionLoading.value),
    subtitleSelectionScanDone: Math.max(0, Number(subtitleSelectionScanDone.value || 0)),
    subtitleSelectionScanTotal: Math.max(0, Number(subtitleSelectionScanTotal.value || 0)),
    subtitleSelectionScanCurrent: String(subtitleSelectionScanCurrent.value || ''),
    subtitleSelectionSourceItems: uniqueSubtitleItems(subtitleSelectionSourceItems.value || []),
    subtitleScannedSelectionItems: uniqueSubtitleItems(subtitleScannedSelectionItems.value || []),
    subtitleScanTargetResults: (subtitleScanTargetResults.value || []).map(item => normalizeSubtitleScanTargetResult(item)),
    subtitleScanRetryingPath: String(subtitleScanRetryingPath.value || ''),
    subtitleScanSession: normalizeStoredSubtitleScanSession(subtitleScanSession.value),
    subtitleDialogSelection: uniqueSubtitleItems(subtitleDialogSelection.value || []),
    subtitlePreferredSelectionKey: String(subtitlePreferredSelectionKey.value || ''),
    subtitleSelectionPage: Math.max(1, Number(subtitleSelectionPage.value || 1)),
    subtitleSelectionFilter: String(subtitleSelectionFilter.value || 'all'),
    subtitleScanSkipFilter: String(subtitleScanSkipFilter.value || 'all'),
    subtitleSkippedSelectionFilter: normalizeStoredSubtitleSkippedSelectionFilter(subtitleSkippedSelectionFilter.value),
    subtitleExecutableCollapsed: Boolean(subtitleExecutableCollapsed.value),
    subtitleSkippedCollapsed: Boolean(subtitleSkippedCollapsed.value),
    subtitleScanTargetsCollapsed: Boolean(subtitleScanTargetsCollapsed.value)
  }
}

function persistSubtitleScanWorkspace () {
  storeJson(SUBTITLE_SCAN_WORKSPACE_KEY, buildSubtitleScanWorkspaceSnapshot())
}

function restoreSubtitleScanWorkspace () {
  const saved = loadJson(SUBTITLE_SCAN_WORKSPACE_KEY, null)
  if (!saved || typeof saved !== 'object') return

  subtitleSelectionLoading.value = Boolean(saved.subtitleSelectionLoading)
  subtitleSelectionScanDone.value = Math.max(0, Number(saved.subtitleSelectionScanDone || 0))
  subtitleSelectionScanTotal.value = Math.max(0, Number(saved.subtitleSelectionScanTotal || 0))
  subtitleSelectionScanCurrent.value = String(saved.subtitleSelectionScanCurrent || '')
  subtitleSelectionSourceItems.value = uniqueSubtitleItems(saved.subtitleSelectionSourceItems || [])
  subtitleScannedSelectionItems.value = uniqueSubtitleItems(saved.subtitleScannedSelectionItems || [])
  subtitleScanTargetResults.value = Array.isArray(saved.subtitleScanTargetResults)
    ? saved.subtitleScanTargetResults.map(item => normalizeSubtitleScanTargetResult(item))
    : []
  subtitleScanRetryingPath.value = String(saved.subtitleScanRetryingPath || '')
  subtitleScanSession.value = normalizeStoredSubtitleScanSession(saved.subtitleScanSession)
  subtitleDialogSelection.value = uniqueSubtitleItems(saved.subtitleDialogSelection || [])
  subtitlePreferredSelectionKey.value = String(saved.subtitlePreferredSelectionKey || '')
  subtitleSelectionPage.value = Math.max(1, Number(saved.subtitleSelectionPage || 1))
  subtitleSelectionFilter.value = String(saved.subtitleSelectionFilter || 'all')
  subtitleScanSkipFilter.value = String(saved.subtitleScanSkipFilter || 'all')
  subtitleSkippedSelectionFilter.value = normalizeStoredSubtitleSkippedSelectionFilter(saved.subtitleSkippedSelectionFilter)
  subtitleExecutableCollapsed.value = Boolean(saved.subtitleExecutableCollapsed)
  subtitleSkippedCollapsed.value = Boolean(saved.subtitleSkippedCollapsed)
  subtitleScanTargetsCollapsed.value = Boolean(saved.subtitleScanTargetsCollapsed)
  subtitleDialogBackgroundActive.value = Boolean(saved.backgroundActive)
  subtitleDialogVisible.value = Boolean(saved.dialogVisible)
  syncSubtitleSelectionState()
}

async function loadConfiguredFilterRules () {
  try {
    const data = await configApi.get()
    return Array.isArray(data?.filter?.rules)
      ? data.filter.rules.filter(rule => rule?.enabled !== false && String(rule?.pattern || '').trim())
      : []
  } catch (error) {
    console.error('加载过滤规则失败:', error)
    return []
  }
}

function buildMergedSubtitleSelection (directItems, scannedItems) {
  const scannedByKey = new Map(scannedItems.map(item => [buildSubtitleSelectionKey(item), item]))
  const mergedDirectItems = directItems.map(item => {
    const scanned = scannedByKey.get(buildSubtitleSelectionKey(item)) || null
    return {
      ...(scanned || {}),
      ...item,
      rjcode: item.rjcode || scanned?.rjcode || '',
      folder_name: item.folder_name || scanned?.folder_name || getFileName(item.folder_path),
      folder_path: item.folder_path || scanned?.folder_path || '',
      library_id: item.library_id || scanned?.library_id || selectedLibraryId.value,
      audio_count: scanned?.audio_count ?? item.audio_count,
      existing_subtitle_count: scanned?.existing_subtitle_count ?? item.existing_subtitle_count ?? 0,
      status: scanned?.status || item.status || ''
    }
  })
  const directKeys = new Set(mergedDirectItems.map(item => buildSubtitleSelectionKey(item)))
  const additionalScannedItems = scannedItems.filter(item => !directKeys.has(buildSubtitleSelectionKey(item)))
  return uniqueSubtitleItems([...mergedDirectItems, ...additionalScannedItems])
}

function mergeSubtitleSelectionRuntimeState (items, previousItems = subtitleDialogSelection.value) {
  const previousByKey = new Map((Array.isArray(previousItems) ? previousItems : []).map(item => [buildSubtitleSelectionKey(item), item]))
  return uniqueSubtitleItems((Array.isArray(items) ? items : []).map(item => {
    const previous = previousByKey.get(buildSubtitleSelectionKey(item))
    if (!previous) return item
    return {
      ...previous,
      ...item,
      rjcode: item.rjcode || previous.rjcode || '',
      folder_name: item.folder_name || previous.folder_name || getFileName(item.folder_path),
      folder_path: item.folder_path || previous.folder_path || '',
      library_id: item.library_id || previous.library_id || selectedLibraryId.value,
      audio_count: item.audio_count ?? previous.audio_count ?? null,
      existing_subtitle_count: Math.max(Number(item.existing_subtitle_count || 0), Number(previous.existing_subtitle_count || 0)),
      status: item.status || previous.status || '',
      queue_state: item.queue_state || previous.queue_state || '',
      queue_message: item.queue_message || previous.queue_message || '',
      task_id: item.task_id || previous.task_id || '',
      manual_match_completed: Boolean(item.manual_match_completed ?? previous.manual_match_completed),
      manual_match_applied_pairs: Math.max(0, Number(item.manual_match_applied_pairs ?? (previous.manual_match_applied_pairs || 0))),
      manual_match_deleted_subtitles: Math.max(0, Number(item.manual_match_deleted_subtitles ?? (previous.manual_match_deleted_subtitles || 0)))
    }
  }))
}

function updateSubtitleSelectionFromScanned (directItems, scannedItems, { sync = true } = {}) {
  const nextSelection = directItems.length
    ? buildMergedSubtitleSelection(directItems, scannedItems)
    : uniqueSubtitleItems(scannedItems)
  subtitleDialogSelection.value = mergeSubtitleSelectionRuntimeState(nextSelection)
  if (!subtitlePreferredSelectionKey.value) {
    subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(subtitleDialogSelection.value[0]) || ''
  }
  if (sync) syncSubtitleSelectionState()
  return subtitleDialogSelection.value
}

function resetSubtitleScanSession () {
  subtitleScanSession.value = createSubtitleScanSessionState()
}

function resetSubtitleScanRunIndicators () {
  subtitleSelectionScanDone.value = 0
  subtitleSelectionScanTotal.value = 0
  subtitleSelectionScanCurrent.value = ''
  subtitleScanTargetResults.value = []
  subtitleScanRetryingPath.value = ''
  resetSubtitleScanSession()
}

function clearSubtitleScanWorkspace () {
  subtitleSelectionLoading.value = false
  subtitleSelectionScanDone.value = 0
  subtitleSelectionScanTotal.value = 0
  subtitleSelectionScanCurrent.value = ''
  subtitleSelectionSourceItems.value = []
  subtitleScannedSelectionItems.value = []
  subtitleScanTargetResults.value = []
  subtitleScanRetryingPath.value = ''
  resetSubtitleScanSession()
  subtitleSelectionPage.value = 1
  subtitleSelectionFilter.value = 'all'
  subtitleScanSkipFilter.value = 'all'
  subtitleSkippedSelectionFilter.value = []
  subtitleForceQueueKey.value = ''
  subtitleDialogSelection.value = []
  subtitlePreferredSelectionKey.value = ''
}

function patchSubtitleScanSession (patch = {}) {
  subtitleScanSession.value = {
    ...subtitleScanSession.value,
    ...patch
  }
}

function incrementSubtitleScanSession (key, amount = 1) {
  subtitleScanSession.value = {
    ...subtitleScanSession.value,
    [key]: Number(subtitleScanSession.value[key] || 0) + amount
  }
}

function upsertSubtitleSelectionEntry (item = {}, patch = {}) {
  if (!item?.folder_path) return null
  const key = buildSubtitleSelectionKey(item)
  const nextItem = {
    library_id: item.library_id || selectedLibraryId.value,
    folder_path: item.folder_path,
    folder_name: item.folder_name || getFileName(item.folder_path),
    rjcode: item.rjcode || '',
    audio_count: item.audio_count ?? null,
    existing_subtitle_count: item.existing_subtitle_count ?? 0,
    status: item.status || 'ready',
    queue_state: '',
    queue_message: '',
    task_id: '',
    manual_match_completed: false,
    manual_match_applied_pairs: 0,
    manual_match_deleted_subtitles: 0,
    ...item,
    ...patch
  }
  const next = [...subtitleDialogSelection.value]
  const index = next.findIndex(entry => buildSubtitleSelectionKey(entry) === key)
  if (index >= 0) next[index] = { ...next[index], ...nextItem }
  else next.unshift(nextItem)
  subtitleDialogSelection.value = uniqueSubtitleItems(next)
  if (!subtitlePreferredSelectionKey.value) subtitlePreferredSelectionKey.value = key
  return nextItem
}

function createOptimisticSubtitleTask (item, taskId) {
  return {
    id: taskId,
    is_optimistic: true,
    optimistic_created_at: Date.now(),
    rjcode: item.rjcode || '',
    actual_rjcode: '',
    folder_name: item.folder_name || getFileName(item.folder_path),
    folder_path: item.folder_path,
    library_id: item.library_id || selectedLibraryId.value,
    status: 'pending',
    is_cancelled: false,
    progress: 0,
    current_step: '等待字幕生成',
    error_message: '',
    created_at: new Date().toISOString(),
    started_at: null,
    completed_at: null,
    source_lang: '',
    source_work_type: '',
    source_title: '',
    downloaded_count: 0,
    existing_subtitle_count: item.existing_subtitle_count || 0,
    subtitle_dir: '',
    written_files: [],
    skipped_files: [],
    write_errors: [],
    failed_files: [],
    match_result: {},
    search_attempts: [],
    download_files: [],
    content_deduped_count: 0,
    content_deduped_files: [],
    progress_log: [],
    awaiting_manual_match: false,
    manual_match_completed: false,
    manual_match_applied_pairs: 0,
    manual_match_deleted_subtitles: 0,
    naming_strategy: subtitleOptions.value.namingStrategy
  }
}

function upsertSubtitleTaskLocal (task) {
  if (!task?.id) return
  const next = [...subtitleTasks.value]
  const index = next.findIndex(item => item.id === task.id)
  if (index >= 0) next[index] = { ...next[index], ...task }
  else next.unshift(task)
  subtitleTasks.value = sortSubtitleTasksForWorkbench(next)
}

function normalizeRJSubtitleTaskPayload (task, options = {}) {
  const { preserveDetail = false } = options
  const trimTail = (items, limit) => Array.isArray(items) ? items.slice(-limit) : []
  return {
    ...task,
    is_optimistic: false,
    search_attempts: Array.isArray(task?.search_attempts) ? task.search_attempts : [],
    download_files: preserveDetail ? trimTail(task?.download_files, 24) : trimTail(task?.download_files, 8),
    progress_log: preserveDetail ? trimTail(task?.progress_log, 24) : trimTail(task?.progress_log, 8)
  }
}

function mergeSubtitleTasksWithOptimistic (remoteTasks = []) {
  const remoteIds = new Set(remoteTasks.map(task => task.id).filter(Boolean))
  const now = Date.now()
  const optimisticTasks = subtitleTasks.value.filter(task => (
    task?.id &&
    !remoteIds.has(task.id) &&
    task?.is_optimistic &&
    ['pending', 'processing'].includes(task?.status) &&
    now - Number(task.optimistic_created_at || now) < 120000
  ))
  return sortSubtitleTasksForWorkbench([...remoteTasks, ...optimisticTasks])
}

function buildSubtitleScanTargetSummary (summary = {}) {
  return {
    found: Number(summary.found || 0),
    ready: Number(summary.ready || 0),
    existing: Number(summary.existing || 0),
    noAudio: Number(summary.no_audio || summary.noAudio || 0),
    queued: Number(summary.queued || 0),
    skippedExisting: Number(summary.skipped_existing || summary.skippedExisting || 0),
    skippedNoSubtitle: Number(summary.skipped_no_subtitle || summary.skippedNoSubtitle || 0),
    existingTask: Number(summary.existing_task || summary.existingTask || 0),
    createFailed: Number(summary.create_failed || summary.createFailed || 0)
  }
}

function mergeSubtitleScanTargetSummary (current = {}, patch = {}) {
  const left = buildSubtitleScanTargetSummary(current)
  const right = buildSubtitleScanTargetSummary(patch)
  return {
    found: Math.max(left.found, right.found),
    ready: Math.max(left.ready, right.ready),
    existing: Math.max(left.existing, right.existing),
    noAudio: Math.max(left.noAudio, right.noAudio),
    queued: Math.max(left.queued, right.queued),
    skippedExisting: Math.max(left.skippedExisting, right.skippedExisting),
    skippedNoSubtitle: Math.max(left.skippedNoSubtitle, right.skippedNoSubtitle),
    existingTask: Math.max(left.existingTask, right.existingTask),
    createFailed: Math.max(left.createFailed, right.createFailed)
  }
}

function buildSubtitleScanTargetMessage (status, summary = {}, fallback = '') {
  if (status === 'pending') return fallback || '正在扫描...'
  if (status === 'failed' && !buildSubtitleScanTargetSummary(summary).found) return fallback || '扫描失败'
  const normalized = buildSubtitleScanTargetSummary(summary)
  const parts = []
  if (normalized.found) parts.push(`识别到 ${normalized.found} 个 RJ 目录`)
  if (normalized.queued) parts.push(`已入任务 ${normalized.queued} 个`)
  if (normalized.skippedExisting) parts.push(`已有字幕跳过 ${normalized.skippedExisting} 个`)
  if (normalized.skippedNoSubtitle) parts.push(`远程无字幕跳过 ${normalized.skippedNoSubtitle} 个`)
  if (normalized.existingTask) parts.push(`任务已存在 ${normalized.existingTask} 个`)
  if (normalized.createFailed) parts.push(`加入失败 ${normalized.createFailed} 个`)
  if (!parts.length && fallback) return fallback
  return parts.join('，')
}

function normalizeSubtitleScanTargetResult (result = {}) {
  const path = String(result.path || '')
  const name = String(result.name || getFileName(path) || '未命名目录')
  const status = ['pending', 'success', 'no_audio', 'no_match', 'failed'].includes(result.status) ? result.status : 'pending'
  const summary = buildSubtitleScanTargetSummary(result.summary || {})
  return {
    path,
    library_id: result.library_id || '',
    name,
    status,
    summary,
    message: String(result.message || buildSubtitleScanTargetMessage(status, summary))
  }
}

function upsertSubtitleScanTargetResult (result = {}) {
  const normalized = normalizeSubtitleScanTargetResult(result)
  const next = [...subtitleScanTargetResults.value]
  const targetKey = buildSubtitleScanTargetResultKey(normalized)
  const index = next.findIndex(item => buildSubtitleScanTargetResultKey(item) === targetKey)
  if (index >= 0) {
    const mergedSummary = mergeSubtitleScanTargetSummary(next[index].summary, normalized.summary)
    next[index] = {
      ...next[index],
      ...normalized,
      summary: mergedSummary,
      message: buildSubtitleScanTargetMessage(normalized.status || next[index].status, mergedSummary, normalized.message || next[index].message)
    }
  } else {
    next.push({
      ...normalized,
      message: buildSubtitleScanTargetMessage(normalized.status, normalized.summary, normalized.message)
    })
  }
  subtitleScanTargetResults.value = next
}

function incrementSubtitleScanTargetCounter (target, key, amount = 1, extras = {}) {
  const targetInput = buildSubtitleScanTargetInput(target)
  if (!targetInput?.path) return
  const targetKey = buildSubtitleScanTargetResultKey(targetInput)
  const current = subtitleScanTargetResults.value.find(item => buildSubtitleScanTargetResultKey(item) === targetKey)
  const currentSummary = buildSubtitleScanTargetSummary(current?.summary || {})
  const nextSummary = {
    ...currentSummary,
    [key]: Number(currentSummary[key] || 0) + amount
  }
  upsertSubtitleScanTargetResult({
    path: targetInput.path,
    library_id: extras.library_id || targetInput.library_id || current?.library_id || '',
    name: extras.name || current?.name || targetInput.name || getFileName(targetInput.path),
    status: extras.status || current?.status || 'pending',
    summary: nextSummary,
    message: buildSubtitleScanTargetMessage(extras.status || current?.status || 'pending', nextSummary, extras.message || current?.message || '')
  })
}

function removeSubtitleScanTargetResult (path) {
  const target = buildSubtitleScanTargetInput(path)
  const targetKey = buildSubtitleScanTargetResultKey(target || {})
  subtitleScanTargetResults.value = subtitleScanTargetResults.value.filter(item => buildSubtitleScanTargetResultKey(item) !== targetKey)
}

function getSubtitleScanResultLabel (status) {
  switch (status) {
    case 'success':
      return '成功'
    case 'no_audio':
      return '无音频'
    case 'no_match':
      return '未识别'
    case 'failed':
      return '扫描失败'
    default:
      return '扫描中'
  }
}

function getSubtitleSelectionStatusLabel (status) {
  if (status === 'existing') return '已有字幕'
  return '可执行'
}

function getSubtitleSelectionQueueLabel (item) {
  switch (item?.queue_state) {
    case 'manual_match_completed':
      return '已匹配完成'
    case 'checking_subtitle':
      return '检测远程字幕中'
    case 'creating':
      return '加入任务中'
    case 'queued':
      return '已入任务'
    case 'existing_task':
      return '任务已存在'
    case 'skipped_existing':
      return '已有字幕跳过'
    case 'skipped_kikoeru_existing':
      return 'Kikoeru字幕跳过'
    case 'skipped_no_subtitle':
      return '远程无字幕跳过'
    case 'create_failed':
      return '加入失败'
    default:
      return getSubtitleSelectionStatusLabel(item?.status || 'ready')
  }
}

function getSubtitleSelectionQueueClass (item) {
  switch (item?.queue_state) {
    case 'manual_match_completed':
      return 'subtitle-mini-chip-success'
    case 'queued':
    case 'existing_task':
      return 'subtitle-mini-chip-primary'
    case 'checking_subtitle':
    case 'creating':
      return 'subtitle-mini-chip-warning'
    case 'create_failed':
      return 'subtitle-mini-chip-danger'
    case 'skipped_existing':
    case 'skipped_kikoeru_existing':
    case 'skipped_no_subtitle':
      return 'subtitle-mini-chip-muted'
    default:
      return item?.status === 'existing' ? 'subtitle-mini-chip-muted' : 'subtitle-mini-chip-success'
  }
}

function canRetrySubtitleScanResult (item) {
  return Boolean(item?.path) && ['no_audio', 'no_match', 'failed', 'error'].includes(String(item?.status || ''))
}

function canInspectSubtitleSelectionFolder(item) {
  if (!item?.folder_path || item?.task_id) return false
  if (item?.status === 'existing') return true
  if (Number(item?.existing_subtitle_count || 0) > 0) return true
  return ['skipped_existing', 'manual_match_completed'].includes(String(item?.queue_state || ''))
}

function canForceCreateSubtitleTaskForSelection(item) {
  return canInspectSubtitleSelectionFolder(item)
}

function canRetryCreateSubtitleTaskForSelection(item) {
  return Boolean(item?.folder_path) && String(item?.queue_state || '') === 'create_failed'
}

async function ensureRJSubtitleAvailabilityForItem (item) {
  const rjcode = String(item?.rjcode || '').trim().toUpperCase()
  if (!rjcode) {
    return {
      hasSubtitle: false,
      message: '未识别到 RJ 号，已跳过',
      attempts: []
    }
  }

  const data = await rjSubtitleApi.checkSubtitleAvailability(rjcode)
  const selectedSource = data?.selected_source || null
  if (data?.has_subtitle && selectedSource) {
    const subtitleCount = Number(selectedSource.subtitle_count || 0)
    return {
      hasSubtitle: true,
      message: subtitleCount > 0 ? `asmr.one 检测到 ${subtitleCount} 个字幕文件` : 'asmr.one 已检测到可用字幕',
      attempts: data?.attempts || [],
      selectedSource
    }
  }

  const attempts = Array.isArray(data?.attempts) ? data.attempts : []
  const readableReason = attempts.length
    ? '远程无字幕（asmr.one 未发现可用字幕）'
    : (data?.error || '远程无字幕（asmr.one 未发现可用字幕）')
  return {
    hasSubtitle: false,
    message: readableReason,
    attempts
  }
}

async function ensureRJSubtitleExistingStateForItem (item) {
  const folderPath = String(item?.folder_path || '').trim()
  const libraryId = String(item?.library_id || selectedLibraryId.value || '').trim()
  if (!folderPath || !libraryId) {
    return {
      hasExistingSubtitles: Number(item?.existing_subtitle_count || 0) > 0,
      existingSubtitleCount: Number(item?.existing_subtitle_count || 0),
      subtitleDir: '',
      message: ''
    }
  }

  const data = await rjSubtitleApi.checkFolderSubtitleState(folderPath, {
    libraryId
  })
  const existingSubtitleCount = Number(data?.existing_subtitle_count || 0)
  return {
    hasExistingSubtitles: Boolean(data?.has_existing_subtitles),
    existingSubtitleCount,
    subtitleDir: String(data?.subtitle_dir || ''),
    message: existingSubtitleCount > 0 ? `现有字幕 ${existingSubtitleCount} 个` : ''
  }
}

async function resolveRJSubtitleItems (paths, options = {}) {
  const { onChunk, onProgress, onTargetResult } = options
  const scanTargets = uniqueSubtitleScanTargets(paths)
  const collected = []
  const total = scanTargets.length
  let done = 0
  for (const target of scanTargets) {
    const path = target.path
    const libraryId = target.library_id || selectedLibraryId.value
    onProgress?.({ done, total, currentPath: path, libraryId })
    try {
      await rjSubtitleApi.scanStream(path, {
        libraryId,
        scanDepth: normalizeRJSubtitleScanDepth(subtitleOptions.value.scanDepth),
        onEvent: async event => {
          if (!event || typeof event !== 'object') return
          if (event.type === 'progress') {
            onProgress?.({
              done,
              total,
              currentPath: event.current_path || event.path || path,
              libraryId
            })
            onTargetResult?.({
              path: event.path || path,
              library_id: libraryId,
              name: target.name || getFileName(path),
              status: 'pending',
              message: event.message || '正在扫描...'
            })
            return
          }
          if (event.type === 'target_result') {
            const result = normalizeSubtitleScanTargetResult({
              path: event.path || path,
              library_id: libraryId,
              name: event.name || target.name || getFileName(path),
              status: event.status || 'pending',
              summary: event.summary || {},
              message: event.message || ''
            })
            if (result.status === 'no_match') incrementSubtitleScanSession('noMatchTargets')
            if (result.status === 'failed') incrementSubtitleScanSession('failedTargets')
            onTargetResult?.(result)
            return
          }
          if (event.type === 'item') {
            const item = event.item || {}
            const resolvedItem = {
              rjcode: item.rjcode,
              folder_name: item.folder_name,
              folder_path: item.folder_path,
              library_id: libraryId,
              scan_target_path: path,
              audio_count: item.audio_count,
              existing_subtitle_count: item.existing_subtitle_count,
              status: item.status
            }
            if (resolvedItem.status === 'no_audio') {
              incrementSubtitleScanSession('noAudioTargets')
              return
            }
            collected.push(resolvedItem)
            await Promise.resolve(onChunk?.(resolvedItem, path))
            await nextTick()
            return
          }
          if (event.type === 'error') {
            throw new Error(event.error || '扫描失败')
          }
        }
      })
    } catch (error) {
      console.error('扫描 RJ 字幕候选失败:', path, error)
      onTargetResult?.({
        path,
        library_id: libraryId,
        name: target.name || getFileName(path),
        status: 'failed',
        message: error.response?.data?.detail || error.message || '扫描失败'
      })
    } finally {
      done += 1
      onProgress?.({ done, total, currentPath: path, libraryId })
    }
  }
  return uniqueSubtitleItems(collected)
}

async function autoQueueScannedSubtitleItem (item, options = {}) {
  const { requestToken = 0, batchContext = null } = options
  if (requestToken && subtitleSelectionRequestToken.value !== requestToken) return

  incrementSubtitleScanSession('foundDirectories')
  incrementSubtitleScanTargetCounter(item, 'found', 1, { name: getFileName(item.scan_target_path) })
  const existingTask = findSubtitleTaskBySelection(item)
  if (existingTask) {
    incrementSubtitleScanSession('existingTasks')
    incrementSubtitleScanTargetCounter(item, 'existingTask', 1)
    upsertSubtitleSelectionEntry(item, {
      task_id: existingTask.id,
      queue_state: 'existing_task',
      queue_message: '任务已存在'
    })
    return
  }

  upsertSubtitleSelectionEntry(item, {
    queue_state: 'checking_subtitle',
    queue_message: '正在检测远程字幕'
  })

  try {
    const availability = await ensureRJSubtitleAvailabilityForItem(item)
    if (requestToken && subtitleSelectionRequestToken.value !== requestToken) return
    if (!availability.hasSubtitle) {
      incrementSubtitleScanSession('noSubtitleTargets')
      incrementSubtitleScanTargetCounter(item, 'skippedNoSubtitle', 1)
      upsertSubtitleSelectionEntry(item, {
        queue_state: 'skipped_no_subtitle',
        queue_message: availability.message || '远程无字幕'
      })
      return
    }

    upsertSubtitleSelectionEntry(item, {
      queue_state: 'creating',
      queue_message: availability.message || '检测到可用字幕，正在加入任务'
    })
    const data = await submitRJSubtitleTasks([item], {
      silent: true,
      refresh: false,
      batchContext: batchContext
        ? {
            ...batchContext,
            log_parent: false
          }
        : null
    })
    if (requestToken && subtitleSelectionRequestToken.value !== requestToken) return
    const skippedItem = Array.isArray(data?.skipped_items)
      ? data.skipped_items.find(entry => buildSubtitleSelectionKey(entry) === buildSubtitleSelectionKey(item))
      : null
    if (skippedItem?.queue_state === 'skipped_existing') {
      incrementSubtitleScanSession('existingSubtitles')
      incrementSubtitleScanTargetCounter(item, 'skippedExisting', 1)
      upsertSubtitleSelectionEntry(item, {
        existing_subtitle_count: skippedItem.existing_subtitle_count ?? item.existing_subtitle_count ?? 0,
        status: 'existing',
        queue_state: 'skipped_existing',
        queue_message: skippedItem.queue_message || '已有字幕，未加入抓取任务'
      })
      return
    }
    if (skippedItem?.queue_state === 'skipped_kikoeru_existing') {
      incrementSubtitleScanSession('existingSubtitles')
      incrementSubtitleScanTargetCounter(item, 'skippedExisting', 1)
      upsertSubtitleSelectionEntry(item, {
        queue_state: 'skipped_kikoeru_existing',
        queue_message: skippedItem.queue_message || 'Kikoeru 已有字幕，未加入抓取任务'
      })
      return
    }
    if (skippedItem?.queue_state === 'skipped_no_subtitle') {
      incrementSubtitleScanSession('noSubtitleTargets')
      incrementSubtitleScanTargetCounter(item, 'skippedNoSubtitle', 1)
      upsertSubtitleSelectionEntry(item, {
        queue_state: 'skipped_no_subtitle',
        queue_message: skippedItem.queue_message || '远程无字幕'
      })
      return
    }
    if (skippedItem?.queue_state === 'existing_task') {
      incrementSubtitleScanSession('existingTasks')
      incrementSubtitleScanTargetCounter(item, 'existingTask', 1)
      upsertSubtitleSelectionEntry(item, {
        task_id: skippedItem.task_id || '',
        queue_state: 'existing_task',
        queue_message: skippedItem.queue_message || '任务已存在'
      })
      if (skippedItem.task_id && !subtitleActiveTaskId.value) subtitleActiveTaskId.value = skippedItem.task_id
      return
    }
    const createdTask = data?.tasks?.[0] || null
    if (!createdTask?.task_id) {
      incrementSubtitleScanSession('createFailed')
      incrementSubtitleScanTargetCounter(item, 'createFailed', 1)
      upsertSubtitleSelectionEntry(item, {
        queue_state: 'create_failed',
        queue_message: data?.message || '未创建任务'
      })
      return
    }
    incrementSubtitleScanSession('createdTasks')
    incrementSubtitleScanTargetCounter(item, 'queued', 1)
    upsertSubtitleTaskLocal(createOptimisticSubtitleTask(item, createdTask.task_id))
    upsertSubtitleSelectionEntry(item, {
      task_id: createdTask.task_id,
      queue_state: 'queued',
      queue_message: '已加入任务'
    })
    if (!subtitleActiveTaskId.value) subtitleActiveTaskId.value = createdTask.task_id
  } catch (error) {
    if (requestToken && subtitleSelectionRequestToken.value !== requestToken) return
    incrementSubtitleScanSession('createFailed')
    incrementSubtitleScanTargetCounter(item, 'createFailed', 1)
    upsertSubtitleSelectionEntry(item, {
      queue_state: 'create_failed',
      queue_message: error.response?.data?.detail || error.message || '加入任务失败'
    })
  }
}

function startAutoQueueScannedSubtitleItem (item, pendingJobs, options = {}, logLabel = '扫描命中目录自动入任务失败') {
  const job = Promise.resolve(autoQueueScannedSubtitleItem(item, options)).catch(error => {
    console.error(`${logLabel}:`, item?.folder_path, error)
  })
  if (Array.isArray(pendingJobs)) pendingJobs.push(job)
  return job
}

function resumeSubtitleTaskPanelFromBackground () {
  subtitleDialogBackgroundActive.value = false
  subtitleDialogVisible.value = true
}

function hideSubtitleTaskPanelToBackground () {
  subtitleDialogBackgroundActive.value = true
  subtitleDialogVisible.value = false
}

function handleSubtitleDialogBeforeClose () {
  closeSubtitleTaskPanel()
}

function closeSubtitleTaskPanel () {
  subtitleDialogBackgroundActive.value = false
  subtitleDialogVisible.value = false
  clearSubtitleStatusPoll()
  subtitleActiveTaskId.value = ''
  subtitleScanRetryingPath.value = ''
  subtitleSelectionScanCurrent.value = ''
  clearSubtitleScanWorkspace()
  clearSubtitleInspectorState()
  persistSubtitleScanWorkspace()
}

async function openSubtitleTaskPanel () {
  subtitleSelectionRequestToken.value += 1
  subtitleDialogBackgroundActive.value = false
  subtitleDialogVisible.value = true
  clearSubtitleScanWorkspace()
  await nextTick()
  await refreshRJSubtitleStatus(false, { silent: true })
}

function getSubtitleRouteFocusPayload () {
  const subtitleDialog = route.query.subtitleDialog
  const subtitleTaskId = route.query.subtitleTaskId
  const subtitleFolderPath = route.query.subtitleFolderPath
  const subtitleLibraryId = route.query.subtitleLibraryId
  const subtitleRjcode = route.query.subtitleRjcode
  const shouldOpen = subtitleDialog === '1'
  const taskId = typeof subtitleTaskId === 'string' ? subtitleTaskId.trim() : ''
  const folderPath = typeof subtitleFolderPath === 'string' ? subtitleFolderPath.trim() : ''
  const libraryId = typeof subtitleLibraryId === 'string' ? subtitleLibraryId.trim() : ''
  const rjcode = typeof subtitleRjcode === 'string' ? subtitleRjcode.trim().toUpperCase() : ''
  return {
    shouldOpen,
    taskId,
    folderPath,
    libraryId,
    rjcode,
    focusKey: shouldOpen ? `${subtitleDialog}:${taskId}:${libraryId}:${folderPath}` : ''
  }
}

function getSubtitleBatchSelectionRouteFlag () {
  return String(route.query.subtitleBatchSelection || '').trim() === '1'
}

function normalizeLibraryMatchPath(path = '', isRemote = false) {
  const value = String(path || '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
  if (!value) return ''
  return isRemote ? value : value.toLowerCase()
}

function isPathWithinLibraryRoot(targetPath = '', library = null) {
  if (!targetPath || !library) return false
  const isRemote = String(library.type || '') === 'synology_filestation'
  const rootCandidate = library.browse_root_path || library.root_path || library.path || ''
  const normalizedTarget = normalizeLibraryMatchPath(targetPath, isRemote)
  const normalizedRoot = normalizeLibraryMatchPath(rootCandidate, isRemote)
  if (!normalizedTarget || !normalizedRoot) return false
  return normalizedTarget === normalizedRoot || normalizedTarget.startsWith(`${normalizedRoot}/`)
}

function resolveLibraryIdByPath(targetPath = '', preferredLibraryId = '') {
  const normalizedPreferred = String(preferredLibraryId || '').trim()
  const preferred = normalizedPreferred ? libraries.value.find(item => item.id === normalizedPreferred) || null : null
  if (preferred && isPathWithinLibraryRoot(targetPath, preferred)) {
    return preferred.id
  }
  const matched = libraries.value.find(item => isPathWithinLibraryRoot(targetPath, item))
  return matched?.id || normalizedPreferred || ''
}

async function clearSubtitleRouteFocusQuery () {
  const nextQuery = { ...route.query }
  delete nextQuery.subtitleDialog
  delete nextQuery.subtitleTaskId
  delete nextQuery.subtitleFolderPath
  delete nextQuery.subtitleLibraryId
  delete nextQuery.subtitleRjcode
  delete nextQuery.subtitleBatchSelection
  delete nextQuery.subtitleImport
  await router.replace({
    path: route.path,
    query: nextQuery
  })
}

async function openSubtitleDialogWithPresetSelection (items = [], preferredKey = '') {
  const normalizedItems = uniqueSubtitleItems((Array.isArray(items) ? items : [])
    .map(item => ({
      library_id: item.library_id || selectedLibraryId.value,
      folder_path: item.folder_path || '',
      folder_name: item.folder_name || getFileName(item.folder_path),
      rjcode: item.rjcode || extractRJCode(item.folder_path || '') || '',
      task_id: item.task_id || '',
      queue_message: item.queue_message || '',
      manual_match_completed: Boolean(item.manual_match_completed),
      manual_match_applied_pairs: Number(item.manual_match_applied_pairs || 0),
      manual_match_deleted_subtitles: Number(item.manual_match_deleted_subtitles || 0)
    }))
    .filter(item => item.folder_path))
  if (!normalizedItems.length) return

  const firstLibraryId = normalizedItems[0]?.library_id || ''
  if (firstLibraryId && selectedLibraryId.value !== firstLibraryId) {
    selectedLibraryId.value = firstLibraryId
  }

  subtitleDialogBackgroundActive.value = false
  subtitleDialogVisible.value = true
  clearSubtitleScanWorkspace()
  subtitleSelectionLoading.value = false
  subtitleSelectionSourceItems.value = normalizedItems
  subtitleScannedSelectionItems.value = normalizedItems
  subtitleDialogSelection.value = mergeSubtitleSelectionRuntimeState(normalizedItems, normalizedItems)
  subtitlePreferredSelectionKey.value = preferredKey || buildSubtitleSelectionKey(normalizedItems[0]) || ''
  clearSubtitleInspectorState()
  await nextTick()
  await refreshRJSubtitleStatus(false, { silent: true })
}

async function consumeSubtitleBatchSelectionRoute () {
  if (!getSubtitleBatchSelectionRouteFlag()) return
  const payload = loadJson('activity-history-subtitle-batch-selection', null)
  try { localStorage.removeItem('activity-history-subtitle-batch-selection') } catch (_) {}
  if (!payload || !Array.isArray(payload.items) || !payload.items.length) {
    await clearSubtitleRouteFocusQuery()
    return
  }
  await openSubtitleDialogWithPresetSelection(payload.items, String(payload.preferred_key || '').trim())
  await clearSubtitleRouteFocusQuery()
}

async function consumeSubtitleRouteFocus () {
  const { shouldOpen, taskId, folderPath, libraryId, rjcode, focusKey } = getSubtitleRouteFocusPayload()
  if (!shouldOpen || (!taskId && !folderPath)) return
  if (subtitleRouteFocusKey.value === focusKey && subtitleDialogVisible.value) return

  subtitleRouteFocusKey.value = focusKey
  const resolvedLibraryId = resolveLibraryIdByPath(folderPath, libraryId)
  if (resolvedLibraryId && selectedLibraryId.value !== resolvedLibraryId) {
    selectedLibraryId.value = resolvedLibraryId
  }
  subtitleDialogBackgroundActive.value = false
  subtitleDialogVisible.value = true
  await nextTick()
  await refreshRJSubtitleStatus(false, { silent: true })

  const matchedTask = subtitleTasks.value.find(item => item.id === taskId)
  if (matchedTask) {
    if (matchedTask.subtitle_dir) {
      await inspectSubtitleTask(matchedTask)
    } else {
      focusSubtitleTask(matchedTask.id)
    }
    await clearSubtitleRouteFocusQuery()
    return
  }

  if (folderPath) {
    await inspectSubtitleSelectionFolder({
      library_id: resolvedLibraryId || selectedLibraryId.value,
      folder_path: folderPath,
      folder_name: getFileName(folderPath),
      rjcode: rjcode || extractRJCode(folderPath) || '',
      queue_message: '来自操作记录'
    }, { force: true, preferredTaskId: taskId })
  }

  await clearSubtitleRouteFocusQuery()
}

async function openRJSubtitleDialog (rows = [], options = {}) {
  const { scanCurrentFolder = false } = options
  const requestToken = ++subtitleSelectionRequestToken.value
  const pendingAutoQueueJobs = []
  const sourceRows = Array.isArray(rows) ? rows : []
  const directItems = sourceRows
    .map(item => item?.folder_path ? item : toRJSubtitleItem(item))
    .filter(Boolean)
  const shouldScanCurrentFolder = scanCurrentFolder && directItems.length === 0 && Boolean(currentPath.value)
  const batchContext = {
    batch_id: `subtitle-batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    source_directories: [],
    scan_targets: [],
    requested_count: 0,
    recognized_rj_count: 0,
    scan_directory_count: 0,
    summary: buildSubtitleScanTargetSummary({})
  }
  subtitleDialogBackgroundActive.value = false
  subtitleDialogVisible.value = true
  clearSubtitleScanWorkspace()
  subtitleSelectionLoading.value = true
  subtitleSelectionSourceItems.value = uniqueSubtitleItems(directItems)
  clearSubtitleInspectorState()
  await nextTick()

  try {
    await refreshRJSubtitleStatus(false, { silent: true })
    const scanTargets = uniqueSubtitleScanTargets(directItems)
    batchContext.source_directories = uniqueSubtitleItems(directItems).map(item => ({
      folder_path: item.folder_path || '',
      folder_name: item.folder_name || getFileName(item.folder_path),
      library_id: item.library_id || selectedLibraryId.value || ''
    })).filter(item => item.folder_path)
    batchContext.scan_directory_count = scanTargets.length || (shouldScanCurrentFolder ? 1 : 0)
    subtitleSelectionScanTotal.value = scanTargets.length || (shouldScanCurrentFolder ? 1 : 0)
    let scannedItems = []
    let incrementalScannedItems = []
    if (scanTargets.length) {
      scannedItems = await resolveRJSubtitleItems(scanTargets, {
        onChunk: async chunkItem => {
          if (subtitleSelectionRequestToken.value !== requestToken) return
          incrementalScannedItems = uniqueSubtitleItems([...incrementalScannedItems, chunkItem])
          subtitleScannedSelectionItems.value = incrementalScannedItems
          updateSubtitleSelectionFromScanned(subtitleSelectionSourceItems.value, incrementalScannedItems, { sync: true })
          startAutoQueueScannedSubtitleItem(chunkItem, pendingAutoQueueJobs, { requestToken, batchContext })
        },
        onTargetResult: result => {
          if (subtitleSelectionRequestToken.value !== requestToken) return
          upsertSubtitleScanTargetResult(result)
        },
        onProgress: progress => {
          if (subtitleSelectionRequestToken.value !== requestToken) return
          subtitleSelectionScanDone.value = Number(progress?.done || 0)
          subtitleSelectionScanTotal.value = Number(progress?.total || scanTargets.length)
          subtitleSelectionScanCurrent.value = progress?.currentPath || ''
          patchSubtitleScanSession({ scannedTargets: Number(progress?.done || 0) })
        }
      })
    }

    if (shouldScanCurrentFolder && !scannedItems.length) {
      scannedItems = await resolveRJSubtitleItems([currentPath.value], {
        onChunk: async chunkItem => {
          if (subtitleSelectionRequestToken.value !== requestToken) return
          subtitleScannedSelectionItems.value = uniqueSubtitleItems([...subtitleScannedSelectionItems.value, chunkItem])
          updateSubtitleSelectionFromScanned(subtitleSelectionSourceItems.value, subtitleScannedSelectionItems.value, { sync: true })
          startAutoQueueScannedSubtitleItem(chunkItem, pendingAutoQueueJobs, { requestToken, batchContext }, '当前目录扫描命中后自动入任务失败')
        },
        onTargetResult: result => {
          if (subtitleSelectionRequestToken.value !== requestToken) return
          upsertSubtitleScanTargetResult(result)
        },
        onProgress: progress => {
          if (subtitleSelectionRequestToken.value !== requestToken) return
          subtitleSelectionScanDone.value = Number(progress?.done || 0)
          subtitleSelectionScanTotal.value = Number(progress?.total || 1)
          subtitleSelectionScanCurrent.value = progress?.currentPath || currentPath.value
          patchSubtitleScanSession({ scannedTargets: Number(progress?.done || 0) })
        }
      })
    }

    if (subtitleSelectionRequestToken.value !== requestToken) return
    if (pendingAutoQueueJobs.length) {
      await Promise.allSettled(pendingAutoQueueJobs)
    }
    if (subtitleSelectionRequestToken.value !== requestToken) return
    subtitleScannedSelectionItems.value = uniqueSubtitleItems(scannedItems)
    syncSubtitleSelectionState()
    batchContext.requested_count = subtitleDialogSelection.value.length
    batchContext.recognized_rj_count = subtitleScanSession.value.foundDirectories
    batchContext.scan_targets = (subtitleScanTargetResults.value || []).map(item => ({
      path: item.path || '',
      name: item.name || getFileName(item.path),
      library_id: item.library_id || '',
      status: item.status || 'pending',
      message: item.message || '',
      summary: buildSubtitleScanTargetSummary(item.summary || {})
    })).filter(item => item.path)
    batchContext.summary = batchContext.scan_targets.reduce((acc, item) => {
      const summary = buildSubtitleScanTargetSummary(item.summary || {})
      return mergeSubtitleScanTargetSummary(acc, summary)
    }, buildSubtitleScanTargetSummary({}))
    await submitRJSubtitleTasks([], {
      silent: true,
      refresh: false,
      batchContext: {
        ...batchContext,
        log_parent: true
      }
    })
    await refreshRJSubtitleStatus(false, { silent: true })
  } finally {
    if (subtitleSelectionRequestToken.value === requestToken) {
      subtitleSelectionLoading.value = false
      subtitleSelectionScanCurrent.value = ''
    }
  }
}

async function startCurrentFolderRJSubtitle () {
  if (!canProcessCurrentFolder.value) return
  if (toolbarActionScope.value === 'page') {
    await openRJSubtitleDialog(toolbarSubtitleScopeRows.value)
    return
  }
  if (!currentPath.value) return
  await openRJSubtitleDialog([], { scanCurrentFolder: true })
}

async function rescanSubtitleSelectionTarget (target) {
  if (!canRetrySubtitleScanResult(target) || subtitleScanRetryingPath.value) return
  subtitleScanRetryingPath.value = buildSubtitleScanTargetResultKey(target)
  subtitleSelectionScanTotal.value = 1
  subtitleSelectionScanDone.value = 0
  subtitleSelectionScanCurrent.value = target.path
  upsertSubtitleScanTargetResult({
    path: target.path,
    library_id: target.library_id || selectedLibraryId.value,
    name: target.name,
    status: 'pending',
    message: '正在重新扫描...'
  })
  try {
    const rescannedItems = await resolveRJSubtitleItems([target], {
      onChunk: chunkItem => {
        subtitleScannedSelectionItems.value = uniqueSubtitleItems([
          ...subtitleScannedSelectionItems.value.filter(item => !(item.folder_path === target.path && (item.library_id || '') === (target.library_id || ''))),
          chunkItem
        ])
        updateSubtitleSelectionFromScanned(subtitleSelectionSourceItems.value, subtitleScannedSelectionItems.value, { sync: true })
      },
      onTargetResult: result => {
        upsertSubtitleScanTargetResult(result)
      },
      onProgress: progress => {
        subtitleSelectionScanDone.value = Number(progress?.done || 0)
        subtitleSelectionScanTotal.value = Number(progress?.total || 1)
        subtitleSelectionScanCurrent.value = progress?.currentPath || target.path
      }
    })
    if (rescannedItems.length) {
      subtitleScannedSelectionItems.value = uniqueSubtitleItems([
        ...subtitleScannedSelectionItems.value.filter(item => !(item.folder_path === target.path && (item.library_id || '') === (target.library_id || ''))),
        ...rescannedItems
      ])
      for (const rescannedItem of rescannedItems) {
        await autoQueueScannedSubtitleItem(rescannedItem)
      }
      removeSubtitleScanTargetResult(target)
      ElMessage.success('该目录已重新扫描并重新尝试加入任务')
      return
    }
  } catch (error) {
    upsertSubtitleScanTargetResult({
      path: target.path,
      library_id: target.library_id || selectedLibraryId.value,
      name: target.name,
      status: 'failed',
      message: error.response?.data?.detail || error.message || '重新扫描失败'
    })
  } finally {
    subtitleScanRetryingPath.value = ''
    subtitleSelectionScanCurrent.value = ''
  }
}

async function submitRJSubtitleTasks (items, options = {}) {
  const { silent = false, refresh = true, skipIfExistingSubtitlesOverride = null, forceRerun = false, batchContext: batchContextOverride = null } = options
  const rawItems = Array.isArray(items) ? items : []
  const buildBatchContext = () => {
    const sourceDirectories = uniqueSubtitleItems(subtitleSelectionSourceItems.value || []).map(item => ({
      folder_path: item.folder_path || '',
      folder_name: item.folder_name || getFileName(item.folder_path),
      library_id: item.library_id || selectedLibraryId.value || ''
    })).filter(item => item.folder_path)
    const scanTargets = (subtitleScanTargetResults.value || []).map(item => ({
      path: item.path || '',
      name: item.name || getFileName(item.path),
      library_id: item.library_id || '',
      status: item.status || 'pending',
      message: item.message || '',
      summary: buildSubtitleScanTargetSummary(item.summary || {})
    })).filter(item => item.path)
    const batchSummary = scanTargets.reduce((acc, item) => {
      const summary = buildSubtitleScanTargetSummary(item.summary || {})
      return mergeSubtitleScanTargetSummary(acc, summary)
    }, buildSubtitleScanTargetSummary({}))
    const sourceCount = sourceDirectories.length
    const scanCount = scanTargets.length
    const itemCount = rawItems.length
    const hasScanContext = sourceCount > 0 || scanCount > 0
    if (!hasScanContext && itemCount <= 1) return null
    return {
      batch_id: `subtitle-batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      requested_count: itemCount,
      recognized_rj_count: Math.max(Number(batchSummary.found || 0), itemCount),
      scan_directory_count: Math.max(sourceCount, scanCount, 0),
      source_directories: sourceDirectories,
      scan_targets: scanTargets,
      summary: batchSummary
    }
  }
  const batchContext = batchContextOverride || buildBatchContext()
  if (!Array.isArray(items) || !items.length) {
    if (!batchContext) {
      if (!silent) ElMessage.warning('没有可执行的 RJ 文件夹')
      return null
    }
  }

  const effectiveSkipIfExistingSubtitles = forceRerun
    ? false
    : typeof skipIfExistingSubtitlesOverride === 'boolean'
      ? skipIfExistingSubtitlesOverride
      : subtitleOptions.value.skipIfExistingSubtitles
  const executableItems = [...rawItems]

  subtitleSubmitting.value = true
  try {
    const data = await rjSubtitleApi.start(executableItems, {
      overwriteExisting: subtitleOptions.value.overwriteExisting,
      enableMetadataMatch: subtitleOptions.value.enableMetadataMatch,
      skipIfExistingSubtitles: effectiveSkipIfExistingSubtitles,
      forceRerun,
      namingStrategy: subtitleOptions.value.namingStrategy,
      useFilterRules: subtitleOptions.value.useFilterRules,
      subtitleFilterRules: sanitizeSubtitleFilterRules(subtitleOptions.value.subtitleFilterRules),
      batchContext
    })
    if (refresh) await refreshRJSubtitleStatus(false, { silent: true })
    const firstCreatedTaskId = data.tasks?.[0]?.task_id
    if (firstCreatedTaskId) {
      subtitleActiveTaskId.value = firstCreatedTaskId
    }
    if (!silent) {
      if (data.tasks?.length) ElMessage.success(data.message || '已创建字幕任务')
      else if (Array.isArray(data.skipped_items) && data.skipped_items.length) {
        const firstSkippedItem = data.skipped_items[0] || {}
        if (String(firstSkippedItem.queue_state || '').startsWith('skipped_')) {
          ElMessage.info(firstSkippedItem.queue_message || '该目录已跳过')
        } else {
          ElMessage.warning(firstSkippedItem.queue_message || '没有创建新任务')
        }
      }
      else ElMessage.warning('没有创建新任务，可能已存在字幕或当前目录不满足执行条件')
    }
    return data
  } catch (error) {
    if (!silent) ElMessage.error('创建字幕任务失败: ' + (error.response?.data?.detail || error.message))
    throw error
  } finally {
    subtitleSubmitting.value = false
  }
}

async function startSingleRJSubtitle (item) {
  if (!item?.folder_path) return
  const requestToken = ++subtitleSelectionRequestToken.value
  const pendingAutoQueueJobs = []
  const batchContext = {
    batch_id: `subtitle-batch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    source_directories: [{
      folder_path: item.folder_path || '',
      folder_name: item.folder_name || getFileName(item.folder_path),
      library_id: item.library_id || selectedLibraryId.value || ''
    }].filter(entry => entry.folder_path),
    scan_targets: [],
    requested_count: 0,
    recognized_rj_count: 0,
    scan_directory_count: 1,
    summary: buildSubtitleScanTargetSummary({})
  }
  subtitleDialogBackgroundActive.value = false
  subtitleDialogVisible.value = true
  resetSubtitleScanRunIndicators()
  subtitleSelectionLoading.value = true
  subtitleSelectionScanDone.value = 0
  subtitleSelectionScanTotal.value = 1
  subtitleSelectionScanCurrent.value = item.folder_path
  subtitleSelectionSourceItems.value = uniqueSubtitleItems([item])
  subtitleScannedSelectionItems.value = []
  subtitleScanTargetResults.value = []
  subtitleScanRetryingPath.value = ''
  subtitleDialogSelection.value = uniqueSubtitleItems([item])
  subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(item)
  clearSubtitleInspectorState()
  await nextTick()

  try {
    await refreshRJSubtitleStatus(false, { silent: true })
    const existingTask = findSubtitleTaskBySelection(item)
    if (existingTask) {
      subtitleActiveTaskId.value = existingTask.id
      if (existingTask.subtitle_dir) await inspectSubtitleTask(existingTask)
      ElMessage.success('已定位到现有字幕任务')
      return
    }

    const scannedItems = await resolveRJSubtitleItems([item], {
      onChunk: async chunkItem => {
        if (subtitleSelectionRequestToken.value !== requestToken) return
        subtitleScannedSelectionItems.value = uniqueSubtitleItems([...subtitleScannedSelectionItems.value, chunkItem])
        updateSubtitleSelectionFromScanned(subtitleSelectionSourceItems.value, subtitleScannedSelectionItems.value, { sync: true })
        startAutoQueueScannedSubtitleItem(chunkItem, pendingAutoQueueJobs, { requestToken, batchContext }, '单项扫描命中后自动入任务失败')
      },
      onTargetResult: result => {
        if (subtitleSelectionRequestToken.value !== requestToken) return
        upsertSubtitleScanTargetResult(result)
      },
      onProgress: progress => {
        if (subtitleSelectionRequestToken.value !== requestToken) return
        subtitleSelectionScanDone.value = Number(progress?.done || 0)
        subtitleSelectionScanTotal.value = Number(progress?.total || 1)
        subtitleSelectionScanCurrent.value = progress?.currentPath || item.folder_path
      }
    })
    if (pendingAutoQueueJobs.length) {
      await Promise.allSettled(pendingAutoQueueJobs)
    }
    if (subtitleSelectionRequestToken.value !== requestToken) return
    subtitleScannedSelectionItems.value = uniqueSubtitleItems(scannedItems)
    syncSubtitleSelectionState()
    batchContext.requested_count = subtitleDialogSelection.value.length
    batchContext.recognized_rj_count = subtitleScanSession.value.foundDirectories
    batchContext.scan_targets = (subtitleScanTargetResults.value || []).map(entry => ({
      path: entry.path || '',
      name: entry.name || getFileName(entry.path),
      library_id: entry.library_id || '',
      status: entry.status || 'pending',
      message: entry.message || '',
      summary: buildSubtitleScanTargetSummary(entry.summary || {})
    })).filter(entry => entry.path)
    batchContext.summary = batchContext.scan_targets.reduce((acc, entry) => {
      const summary = buildSubtitleScanTargetSummary(entry.summary || {})
      return mergeSubtitleScanTargetSummary(acc, summary)
    }, buildSubtitleScanTargetSummary({}))
    await submitRJSubtitleTasks([], {
      silent: true,
      refresh: false,
      batchContext: {
        ...batchContext,
        log_parent: true
      }
    })
    await refreshRJSubtitleStatus(false, { silent: true })
    const resolvedItem = scannedItems.find(candidate => buildSubtitleSelectionKey(candidate) === buildSubtitleSelectionKey(item)) || null
    if (!resolvedItem) {
      if (subtitleScanSession.value.foundDirectories || subtitleScanSession.value.existingSubtitles || subtitleScanSession.value.noSubtitleTargets || subtitleScanSession.value.noAudioTargets || subtitleScanSession.value.noMatchTargets || subtitleScanSession.value.failedTargets) {
        return
      }
      return
    }
    if (subtitleOptions.value.skipIfExistingSubtitles && (resolvedItem.status === 'existing' || Number(resolvedItem.existing_subtitle_count || 0) > 0)) {
      await inspectSubtitleSelectionFolder(resolvedItem, { force: true })
      ElMessage.info('该目录已有字幕，已打开字幕检查工作台；如需重新抓取可点“创建一次任务”')
    }
  } catch (error) {
    ElMessage.error('启动字幕任务失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    subtitleSelectionLoading.value = false
    subtitleSelectionScanCurrent.value = ''
  }
}

function isRJSubtitleTaskCancelled (taskOrStatus) {
  if (!taskOrStatus) return false
  if (typeof taskOrStatus === 'object') {
    return Boolean(taskOrStatus.is_cancelled) || taskOrStatus.error_message === '用户取消'
  }
  return false
}

function getRJSubtitleTaskStatusLabel (taskOrStatus) {
  if (isRJSubtitleTaskCancelled(taskOrStatus)) return '已取消'
  if (typeof taskOrStatus === 'object') {
    if (taskOrStatus.manual_match_completed) return '已匹配完成'
    if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) {
      return taskOrStatus.awaiting_manual_match ? '筛选并匹配' : '待处理'
    }
  }
  const status = typeof taskOrStatus === 'object' ? taskOrStatus.status : taskOrStatus
  const labels = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    failed: '失败'
  }
  return labels[status] || status
}

function getRJSubtitleTaskBaseStatusLabel (taskOrStatus) {
  if (isRJSubtitleTaskCancelled(taskOrStatus)) return '已取消'
  if (typeof taskOrStatus === 'object') {
    if (taskOrStatus.manual_match_completed) return '已完成'
    if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) return '待处理'
  }
  const status = typeof taskOrStatus === 'object' ? taskOrStatus.status : taskOrStatus
  const labels = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    failed: '失败'
  }
  return labels[status] || status
}

function getRJSubtitleTaskStatusType (taskOrStatus) {
  if (isRJSubtitleTaskCancelled(taskOrStatus)) return 'info'
  if (typeof taskOrStatus === 'object') {
    if (taskOrStatus.manual_match_completed) return 'success'
    if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) return 'warning'
  }
  const status = typeof taskOrStatus === 'object' ? taskOrStatus.status : taskOrStatus
  const types = {
    pending: 'info',
    processing: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return types[status] || 'info'
}

function getRJSubtitleTaskBaseStatusType (taskOrStatus) {
  if (isRJSubtitleTaskCancelled(taskOrStatus)) return 'info'
  if (typeof taskOrStatus === 'object') {
    if (taskOrStatus.manual_match_completed) return 'success'
    if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) return 'warning'
  }
  const status = typeof taskOrStatus === 'object' ? taskOrStatus.status : taskOrStatus
  const types = {
    pending: 'info',
    processing: 'warning',
    completed: 'success',
    failed: 'danger'
  }
  return types[status] || 'info'
}

function setSubtitleTaskFilter (filter) {
  const normalized = normalizeSubtitleTaskFilterSelection(filter || 'all', subtitleTaskManualFilter.value)
  subtitleTaskFilter.value = normalized.taskFilter
  subtitleTaskManualFilter.value = normalized.manualFilter
  syncSubtitleTaskListState()
}

function setSubtitleTaskManualFilter (filter) {
  const normalized = normalizeSubtitleTaskFilterSelection(subtitleTaskFilter.value, filter || 'all')
  subtitleTaskFilter.value = normalized.taskFilter
  subtitleTaskManualFilter.value = normalized.manualFilter
  syncSubtitleTaskListState()
}

function getRJSubtitleTaskStatusClass (taskOrStatus) {
  if (isRJSubtitleTaskCancelled(taskOrStatus)) return 'cancelled'
  if (typeof taskOrStatus === 'object') {
    if (taskOrStatus.manual_match_completed) return 'manual_match_completed'
    if (isSubtitleTaskAwaitingManualWork(taskOrStatus)) return 'awaiting_manual_match'
    return taskOrStatus.status || 'pending'
  }
  return taskOrStatus || 'pending'
}

function getRJSubtitleProgressStatus (task) {
  if (!task) return ''
  if (isRJSubtitleTaskCancelled(task)) return undefined
  if (task.status === 'failed') return 'exception'
  if (task.manual_match_completed) return 'success'
  if (isSubtitleTaskAwaitingManualWork(task)) return 'warning'
  return ''
}

function canCancelRJSubtitleTask (task) {
  if (!task?.id) return false
  if (subtitleCancelingId.value === task.id) return false
  if (isRJSubtitleTaskCancelled(task)) return false
  return ['pending', 'processing'].includes(task.status)
}

function getRJSubtitleLangLabel (lang) {
  const labels = {
    CHI_HANS: '简中',
    CHI_SIMP: '简中',
    CHI_HANT: '繁中',
    CHI_TRAD: '繁中',
    JPN: '日文',
    JAP: '日文',
    ENG: '英文'
  }
  return labels[lang] || lang || '-'
}

function getSubtitleTaskInspectLabel (task) {
  if (!task?.subtitle_dir) return '等待字幕生成'
  if (task.manual_match_completed) return '已匹配完成'
  if (isSubtitleTaskAwaitingManualWork(task)) {
    return task.awaiting_manual_match ? '筛选并匹配' : '检查字幕树'
  }
  return '检查字幕树'
}

function getSubtitleTaskManualStateText (task) {
  if (!task) return ''
  if (task.manual_match_completed) return `已匹配完成 ${task.manual_match_applied_pairs || 0}`
  if (isSubtitleTaskAwaitingManualWork(task)) {
    return task.awaiting_manual_match ? '筛选并匹配' : '待处理'
  }
  return ''
}

function getSubtitleTaskManualStateChipClass (task) {
  if (!task) return ''
  if (task.manual_match_completed) return 'is-success'
  if (isSubtitleTaskAwaitingManualWork(task)) return 'is-warning'
  return ''
}

function isSubtitleTaskSelected (task) {
  if (!task?.id) return false
  return activeSubtitleTask.value?.id === task.id || subtitleInspectorInfo.value.taskId === task.id
}

function buildDefaultSubtitleTaskDetailPanels (task) {
  if (!task) return []
  if (task.status === 'processing') return ['download', 'log']
  if (task.status === 'failed' || isRJSubtitleTaskCancelled(task)) return ['issues', 'log']
  if (task.manual_match_completed) return ['written', 'log']
  if (isSubtitleTaskAwaitingManualWork(task)) return ['written', 'download']
  if (task.status === 'completed') return ['written']
  return []
}

function formatRJSubtitleAttempt (attempt) {
  if (!attempt) return '-'
  if (attempt.reason) return attempt.reason
  return `${attempt.subtitle_count || 0} 个字幕`
}

function getProgressLogLevelLabel (level) {
  const labels = {
    info: '信息',
    success: '完成',
    warning: '注意',
    error: '错误'
  }
  return labels[level] || '信息'
}

function formatProgressLogTime (value) {
  if (!value) return '--:--:--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function normalizeSubtitleWriteError (value) {
  const raw = decodePossibleMojibake(String(value || '').trim())
  if (!raw) return { name: '未知文件', detail: '' }
  const separatorIndex = raw.indexOf(':')
  if (separatorIndex === -1) return { name: raw, detail: '' }

  const name = raw.slice(0, separatorIndex).trim() || '未知文件'
  let detail = decodePossibleMojibake(raw.slice(separatorIndex + 1).trim())
  if (detail.includes('Attempt to decode JSON with unexpected mimetype: text/plain')) {
    detail = '群晖上传接口返回了 text/plain 响应，旧版客户端把它误判成 JSON 解析失败。刷新后重新执行即可。'
  } else if (detail.includes('"code": 401') || detail.includes("'code': 401")) {
    detail = '群晖返回文件操作错误（401）。这通常不是字幕匹配失败，而是远程上传阶段对文件名编码或 multipart 参数不兼容导致的写入失败。'
  }
  return { name, detail }
}

function normalizeSubtitleWriteErrors (items) {
  return (items || []).map(normalizeSubtitleWriteError)
}

function isAudioFileName (name = '') {
  return /\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(name)
}

function isSubtitleFileName (name = '') {
  return /\.(lrc|srt|ass|ssa|vtt)$/i.test(name)
}

function isSubtitleRelativePath (relativePath = '') {
  const normalized = String(relativePath || '').replace(/\\/g, '/').toLowerCase().replace(/^\/+/, '')
  return normalized === 'subtitles' || normalized.startsWith('subtitles/')
}

function isAudioPaired (audioPath) {
  return subtitleManualPairs.value.some(pair => pair.audio_path === audioPath)
}

function isSubtitlePaired (subtitlePath) {
  return subtitleManualPairs.value.some(pair => pair.subtitle_path === subtitlePath)
}

function findSubtitlePairByAudioPath (audioPath) {
  return subtitleManualPairs.value.find(pair => pair.audio_path === audioPath) || null
}

function findSubtitlePairBySubtitlePath (subtitlePath) {
  return subtitleManualPairs.value.find(pair => pair.subtitle_path === subtitlePath) || null
}

function isAudioSuspicious (audioPath) {
  return findSubtitlePairByAudioPath(audioPath)?.confidenceLevel === 'low'
}

function isSubtitleSuspicious (subtitlePath) {
  return findSubtitlePairBySubtitlePath(subtitlePath)?.confidenceLevel === 'low'
}

function getSubtitlePairConfidenceLabel (level) {
  if (level === 'high') return '高置信'
  if (level === 'low') return '低置信'
  return '中等'
}

function clearSubtitleSequenceSelection () {
  subtitleSequenceSelection.value = { audioPaths: [], subtitlePaths: [] }
}

function toggleSubtitleSequencePath (kind, path) {
  if (!path) return
  const current = kind === 'audio'
    ? [...subtitleSequenceSelection.value.audioPaths]
    : [...subtitleSequenceSelection.value.subtitlePaths]
  const existingIndex = current.indexOf(path)
  if (existingIndex >= 0) {
    current.splice(existingIndex, 1)
  } else {
    current.push(path)
  }
  subtitleSequenceSelection.value = {
    ...subtitleSequenceSelection.value,
    [kind === 'audio' ? 'audioPaths' : 'subtitlePaths']: current
  }
}

function getSubtitleSequenceIndex (kind, path) {
  const list = kind === 'audio' ? subtitleSequenceSelection.value.audioPaths : subtitleSequenceSelection.value.subtitlePaths
  const index = list.indexOf(path)
  return index >= 0 ? index + 1 : 0
}

function selectSubtitleAudio (audio) {
  if (subtitleSequenceMode.value) {
    toggleSubtitleSequencePath('audio', audio?.path || '')
    return
  }
  subtitleMatchSelection.value = {
    ...subtitleMatchSelection.value,
    audioPath: audio?.path || ''
  }
}

function selectSubtitleFile (subtitle) {
  if (subtitleSequenceMode.value) {
    toggleSubtitleSequencePath('subtitle', subtitle?.path || '')
    return
  }
  subtitleMatchSelection.value = {
    ...subtitleMatchSelection.value,
    subtitlePath: subtitle?.path || ''
  }
}

function buildSubtitlePairTargets (audio, subtitle) {
  const audioExt = String(audio?.name || '').match(/\.[^.]+$/)?.[0] || ''
  const subtitleExt = String(subtitle?.name || '').match(/\.[^.]+$/)?.[0] || '.vtt'
  const subtitleBase = stripTrailingAudioExtension(String(subtitle?.name || '').replace(/\.[^.]+$/, ''))
  const audioBase = String(audio?.name || '').replace(/\.[^.]+$/, '')
  const targetBase = subtitleOptions.value.namingStrategy === 'subtitle' ? subtitleBase : audioBase
  return {
    targetBase,
    targetAudioName: `${targetBase}${audioExt}`,
    targetSubtitleName: `${targetBase}${subtitleExt}`
  }
}

function stripTrailingAudioExtension (value = '') {
  let current = String(value || '')
  while (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(current)) {
    current = current.replace(/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i, '')
  }
  return current
}

function normalizeSubtitleMatchName (value = '') {
  return stripTrailingAudioExtension(String(value || '').replace(/\.[^.]+$/, ''))
    .toLowerCase()
    .replace(/^(track|trk|tr)[_\-\s]*/i, '')
    .replace(/[\s_\-]+/g, '')
    .replace(/[^\w\u4e00-\u9fff\u3040-\u30ff]+/g, '')
}

function extractSubtitleTrackNumber (value = '') {
  const match = String(value || '').match(/(?:^|[^0-9])(?:tr|track)?[_\-\s]*0*([0-9]{1,3})(?![0-9])/i)
  return match ? Number(match[1]) : null
}

function createSubtitlePair (audio, subtitle, options = {}) {
  const targets = buildSubtitlePairTargets(audio, subtitle)
  return {
    id: `${audio.path}::${subtitle.path}`,
    audio_path: audio.path,
    audio_name: audio.name,
    audio_relative_path: audio.relative_path || audio.name,
    subtitle_path: subtitle.path,
    subtitle_name: subtitle.name,
    subtitle_relative_path: subtitle.relative_path || subtitle.name,
    target_base: targets.targetBase,
    target_audio_name: targets.targetAudioName,
    target_subtitle_name: targets.targetSubtitleName,
    confidenceLevel: options.confidenceLevel || 'medium',
    matchReason: options.matchReason || '手动配对'
  }
}

function syncSubtitlePairTargetNames () {
  subtitleManualPairs.value = subtitleManualPairs.value.map(pair => ({
    ...pair,
    ...buildSubtitlePairTargets(
      { name: pair.audio_name, path: pair.audio_path, relative_path: pair.audio_relative_path },
      { name: pair.subtitle_name, path: pair.subtitle_path, relative_path: pair.subtitle_relative_path }
    )
  }))
}

function cloneSubtitleManualPairsSnapshot() {
  return subtitleManualPairs.value.map(pair => ({ ...pair }))
}

function createSubtitleManualMatchSnapshot() {
  return {
    audioSearch: subtitleInspectorAudioSearch.value,
    subtitleSearch: subtitleInspectorSubtitleSearch.value,
    audioFilterMode: subtitleAudioFilterMode.value,
    subtitleFilterMode: subtitleSubtitleFilterMode.value,
    matchSelection: { ...subtitleMatchSelection.value },
    sequenceMode: Boolean(subtitleSequenceMode.value),
    sequenceSelection: {
      audioPaths: [...subtitleSequenceSelection.value.audioPaths],
      subtitlePaths: [...subtitleSequenceSelection.value.subtitlePaths]
    },
    lastPairBuildMode: subtitleLastPairBuildMode.value,
    manualPairs: cloneSubtitleManualPairsSnapshot(),
    selectedManualPairId: subtitleSelectedManualPairId.value
  }
}

function restoreSubtitleManualMatchSnapshot(snapshot) {
  if (!snapshot) return
  subtitleInspectorAudioSearch.value = snapshot.audioSearch || ''
  subtitleInspectorSubtitleSearch.value = snapshot.subtitleSearch || ''
  subtitleAudioFilterMode.value = snapshot.audioFilterMode || 'all'
  subtitleSubtitleFilterMode.value = snapshot.subtitleFilterMode || 'all'
  subtitleMatchSelection.value = {
    audioPath: snapshot.matchSelection?.audioPath || '',
    subtitlePath: snapshot.matchSelection?.subtitlePath || ''
  }
  subtitleSequenceMode.value = Boolean(snapshot.sequenceMode)
  subtitleSequenceSelection.value = {
    audioPaths: [...(snapshot.sequenceSelection?.audioPaths || [])],
    subtitlePaths: [...(snapshot.sequenceSelection?.subtitlePaths || [])]
  }
  subtitleLastPairBuildMode.value = snapshot.lastPairBuildMode || ''
  subtitleManualPairs.value = Array.isArray(snapshot.manualPairs) ? snapshot.manualPairs.map(pair => ({ ...pair })) : []
  subtitleSelectedManualPairId.value = snapshot.selectedManualPairId || subtitleManualPairs.value[0]?.id || ''
}

function resetSubtitleManualMatchState () {
  subtitleInspectorAudioSearch.value = ''
  subtitleInspectorSubtitleSearch.value = ''
  subtitleAudioFilterMode.value = 'all'
  subtitleSubtitleFilterMode.value = 'all'
  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }
  subtitleSequenceMode.value = false
  clearSubtitleSequenceSelection()
  subtitleLastPairBuildMode.value = ''
  subtitleManualPairs.value = []
  subtitleSelectedManualPairId.value = ''
}

function addSubtitleManualPair () {
  const audio = subtitleInspectorAudioFiles.value.find(item => item.path === subtitleMatchSelection.value.audioPath)
  const subtitle = subtitleInspectorSubtitleFiles.value.find(item => item.path === subtitleMatchSelection.value.subtitlePath)
  if (!audio || !subtitle) {
    ElMessage.warning('请先分别选择音频和字幕')
    return
  }

  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => pair.audio_path !== audio.path && pair.subtitle_path !== subtitle.path)
  subtitleManualPairs.value.push({
    ...createSubtitlePair(audio, subtitle, { confidenceLevel: 'medium', matchReason: '手动指定' })
  })
  subtitleLastPairBuildMode.value = 'manual'
  subtitleSelectedManualPairId.value = `${audio.path}::${subtitle.path}`
  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }
}

function removeSubtitleManualPair (pairId) {
  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => pair.id !== pairId)
  if (subtitleSelectedManualPairId.value === pairId) subtitleSelectedManualPairId.value = ''
}

function buildOrderedSubtitlePairs () {
  const audioList = filteredSubtitleInspectorAudioFiles.value
  const subtitleList = filteredSubtitleInspectorSubtitleFiles.value
  const pairCount = Math.min(audioList.length, subtitleList.length)
  if (!pairCount) {
    ElMessage.warning('当前没有可用于顺序配对的音频或字幕')
    return
  }
  const nextPairs = []
  for (let index = 0; index < pairCount; index++) {
    const audio = audioList[index]
    const subtitle = subtitleList[index]
    nextPairs.push(createSubtitlePair(audio, subtitle, { confidenceLevel: 'low', matchReason: '顺序配对' }))
  }
  subtitleManualPairs.value = nextPairs
  subtitleLastPairBuildMode.value = 'ordered'
  subtitleSelectedManualPairId.value = nextPairs[0]?.id || ''
}

function buildSequenceSubtitlePairs () {
  const audioList = subtitleSequenceSelection.value.audioPaths
    .map(path => subtitleInspectorAudioFiles.value.find(item => item.path === path))
    .filter(Boolean)
  const subtitleList = subtitleSequenceSelection.value.subtitlePaths
    .map(path => subtitleInspectorSubtitleFiles.value.find(item => item.path === path))
    .filter(Boolean)

  if (!audioList.length || audioList.length !== subtitleList.length) {
    ElMessage.warning('请先按顺序点选数量一致的音频和字幕')
    return
  }

  const nextPairs = []
  for (let index = 0; index < audioList.length; index++) {
    nextPairs.push(createSubtitlePair(audioList[index], subtitleList[index], {
      confidenceLevel: 'medium',
      matchReason: '点选顺序'
    }))
  }
  subtitleManualPairs.value = subtitleManualPairs.value.filter(pair => (
    !audioList.some(item => item.path === pair.audio_path) &&
    !subtitleList.some(item => item.path === pair.subtitle_path)
  ))
  subtitleManualPairs.value.push(...nextPairs)
  subtitleLastPairBuildMode.value = 'sequence'
  subtitleSelectedManualPairId.value = nextPairs[0]?.id || subtitleSelectedManualPairId.value
  clearSubtitleSequenceSelection()
  subtitleSequenceMode.value = false
}

function buildSequenceOrOrderedSubtitlePairs () {
  if (subtitleSequenceMode.value) {
    buildSequenceSubtitlePairs()
    return
  }
  buildOrderedSubtitlePairs()
}

function buildAutoSubtitlePairs () {
  const audioList = [...subtitleInspectorAudioFiles.value]
  const subtitleList = [...subtitleInspectorSubtitleFiles.value]
  const usedSubtitlePaths = new Set()
  const pairs = []

  const subtitleByExact = new Map()
  const subtitleByNormalized = new Map()
  const subtitleByTrack = new Map()
  for (const subtitle of subtitleList) {
    const name = String(subtitle.name || '')
    const baseName = stripTrailingAudioExtension(name.replace(/\.[^.]+$/, ''))
    const normalized = normalizeSubtitleMatchName(name)
    const trackNumber = extractSubtitleTrackNumber(name)
    subtitleByExact.set(baseName.toLowerCase(), subtitleByExact.get(baseName.toLowerCase()) || [])
    subtitleByExact.get(baseName.toLowerCase()).push(subtitle)
    if (normalized) {
      subtitleByNormalized.set(normalized, subtitleByNormalized.get(normalized) || [])
      subtitleByNormalized.get(normalized).push(subtitle)
    }
    if (trackNumber !== null) {
      subtitleByTrack.set(trackNumber, subtitleByTrack.get(trackNumber) || [])
      subtitleByTrack.get(trackNumber).push(subtitle)
    }
  }

  function consumeCandidate (candidates = []) {
    for (const item of candidates) {
      if (usedSubtitlePaths.has(item.path)) continue
      usedSubtitlePaths.add(item.path)
      return item
    }
    return null
  }

  for (const audio of audioList) {
    const audioName = String(audio.name || '')
    const audioBase = audioName.replace(/\.[^.]+$/, '')
    const audioNormalized = normalizeSubtitleMatchName(audioName)
    const audioTrack = extractSubtitleTrackNumber(audioName)
    let matchedSubtitle = consumeCandidate(subtitleByExact.get(audioBase.toLowerCase()))
    let confidenceLevel = 'high'
    let matchReason = '精确文件名'
    if (!matchedSubtitle && audioTrack !== null) {
      matchedSubtitle = consumeCandidate(subtitleByTrack.get(audioTrack))
      if (matchedSubtitle) {
        confidenceLevel = 'high'
        matchReason = `轨道号 ${audioTrack}`
      }
    }
    if (!matchedSubtitle && audioNormalized) {
      matchedSubtitle = consumeCandidate(subtitleByNormalized.get(audioNormalized))
      if (matchedSubtitle) {
        confidenceLevel = 'medium'
        matchReason = '规范化标题'
      }
    }
    if (!matchedSubtitle) continue
    pairs.push(createSubtitlePair(audio, matchedSubtitle, { confidenceLevel, matchReason }))
  }

  if (!pairs.length) {
    ElMessage.warning('没有生成可用的自动预匹配结果')
    return
  }
  subtitleManualPairs.value = pairs
  subtitleLastPairBuildMode.value = 'auto'
  subtitleSelectedManualPairId.value = pairs[0]?.id || ''
}

function clearSubtitleManualPairs () {
  subtitleManualPairs.value = []
  subtitleLastPairBuildMode.value = ''
  subtitleSelectedManualPairId.value = ''
  subtitleMatchSelection.value = { audioPath: '', subtitlePath: '' }
  clearSubtitleSequenceSelection()
}

function joinPath (basePath, name) {
  return `${String(basePath || '').replace(/[\\/]+$/, '')}/${String(name || '').replace(/^[/\\]+/, '')}`
}

async function rollbackSubtitleManualRenamePairs (pairs, audioLibraryId, subtitleLibraryId) {
  if (!Array.isArray(pairs) || !pairs.length) return { restored: 0, failed: [] }
  const failed = []
  let restored = 0

  for (const pair of [...pairs].reverse()) {
    const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
    const rollbackSourcePath = pair.final_path || pair.temp_path
    if (!rollbackSourcePath || !pair.current_name) continue
    try {
      await libraryApi.browserRename(operationLibraryId, rollbackSourcePath, pair.current_name, {
        skipActivityLog: true,
        renameContext: 'subtitle_manual_match_pair'
      })
      restored += 1
    } catch (error) {
      failed.push({
        kind: pair.kind,
        source: rollbackSourcePath,
        target: pair.current_name,
        error: error.response?.data?.detail || error.message || '回滚失败'
      })
    }
  }

  return { restored, failed }
}

async function applySubtitleManualPairs () {
  if (!subtitleManualPairs.value.length) {
    ElMessage.warning('请先添加至少一组配对')
    return
  }

  const audioLibraryId = subtitleInspectorInfo.value.audioLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value
  const subtitleLibraryId = subtitleInspectorInfo.value.subtitleLibraryId || audioLibraryId
  const isLinkedImport = isLinkedSubtitleImportWorkbench.value
  const effectiveNamingStrategy = isLinkedImport ? (subtitleOptions.value.namingStrategy || 'audio') : subtitleOptions.value.namingStrategy
  const appliedPairCount = subtitleManualPairs.value.length
  const unusedSubtitleRows = subtitleInspectorSubtitleFiles.value.filter(
    item => !subtitleManualPairs.value.some(pair => pair.subtitle_path === item.path)
  )
  const unusedSubtitlePathSet = new Set(unusedSubtitleRows.map(item => item.path).filter(Boolean))
  const audioPairConflictMap = new Map()
  const subtitlePairConflictMap = new Map()

  subtitleManualPairs.value.forEach(pair => {
    const audioKey = buildRenameConflictKey(pair.audio_path, pair.target_audio_name)
    const subtitleKey = buildRenameConflictKey(pair.subtitle_path, pair.target_subtitle_name)
    audioPairConflictMap.set(audioKey, (audioPairConflictMap.get(audioKey) || 0) + 1)
    subtitlePairConflictMap.set(subtitleKey, (subtitlePairConflictMap.get(subtitleKey) || 0) + 1)
  })

  const audioConflicts = subtitleManualPairs.value.filter(pair => {
    const targetKey = buildRenameConflictKey(pair.audio_path, pair.target_audio_name)
    if ((audioPairConflictMap.get(targetKey) || 0) > 1) return true
    const existing = subtitleInspectorAudioFiles.value.find(item => (
      item.name === pair.target_audio_name &&
      buildRenameConflictKey(item.path, item.name) === targetKey
    ))
    return existing && existing.path !== pair.audio_path
  })
  if (audioConflicts.length) {
    ElMessage.error(`存在目标音频名冲突，无法直接应用：${audioConflicts[0].target_audio_name}`)
    return
  }
  const subtitleConflicts = subtitleManualPairs.value.filter(pair => {
    const targetKey = buildRenameConflictKey(pair.subtitle_path, pair.target_subtitle_name)
    if ((subtitlePairConflictMap.get(targetKey) || 0) > 1) return true
    const existing = subtitleInspectorSubtitleFiles.value.find(item => (
      item.name === pair.target_subtitle_name &&
      buildRenameConflictKey(item.path, item.name) === targetKey
    ))
    if (existing?.path && unusedSubtitlePathSet.has(existing.path)) return false
    return existing && existing.path !== pair.subtitle_path
  })
  if (subtitleConflicts.length) {
    ElMessage.error(`存在目标字幕名冲突，无法直接应用：${subtitleConflicts[0].target_subtitle_name}`)
    return
  }

  const namingStrategyLabel = subtitleOptions.value.namingStrategy === 'subtitle' ? '以字幕名为准' : '以音频名为准'
  const applyActionLabel = isLinkedImport ? '重命名并导入' : '确定应用'
  try {
    await showSystemConfirm({
      title: '应用配对确认',
      message: `确定处理 ${subtitleManualPairs.value.length} 组配对结果吗？\n\n同名依据：${namingStrategyLabel}${unusedSubtitleRows.length ? `\n当前未使用的 ${unusedSubtitleRows.length} 个原始字幕会一并删除。` : ''}${isLinkedImport ? '\n确认后会先在本地工作区完成重命名，再导入目标库存。' : ''}`,
      tone: 'warning',
      confirmText: applyActionLabel,
      cancelText: '取消'
    })
  } catch (_) {
    return
  }

  subtitlePairApplying.value = true
  const phaseOneCompleted = []
  const phaseTwoCompleted = []
  const preApplySnapshot = createSubtitleManualMatchSnapshot()
  try {
    const currentSubtitleFiles = [...subtitleInspectorSubtitleFiles.value]
    const resolveCurrentSubtitleSourcePath = (pair) => {
      const exactMatch = currentSubtitleFiles.find(item => item.path === pair.subtitle_path)
      if (exactMatch?.path) return exactMatch.path

      const sameNameMatches = currentSubtitleFiles.filter(item => item.name === pair.subtitle_name)
      if (sameNameMatches.length === 1) return sameNameMatches[0].path

      const sameRelativeMatches = currentSubtitleFiles.filter(item => (item.relative_path || item.name) === pair.subtitle_relative_path)
      if (sameRelativeMatches.length === 1) return sameRelativeMatches[0].path

      return pair.subtitle_path
    }

    const operations = subtitleManualPairs.value.flatMap(pair => {
      const next = []
      if (pair.audio_name !== pair.target_audio_name) {
        next.push({
          kind: 'audio',
          source_path: pair.audio_path,
          current_name: pair.audio_name,
          target_name: pair.target_audio_name
        })
      }
      if (pair.subtitle_name !== pair.target_subtitle_name) {
        next.push({
          kind: 'subtitle',
          source_path: resolveCurrentSubtitleSourcePath(pair),
          current_name: pair.subtitle_name,
          target_name: pair.target_subtitle_name
        })
      }
      return next
    })
    const phaseOne = operations
      .filter(item => item.current_name !== item.target_name)
      .map((pair, index) => ({
        ...pair,
        temp_name: `__manual_match_${pair.kind}_${String(index + 1).padStart(3, '0')}_${Date.now()}.tmp${pair.current_name.match(/\.[^.]+$/)?.[0] || ''}`
      }))

    for (const pair of phaseOne) {
      const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
      const renameResult = await libraryApi.browserRename(operationLibraryId, pair.source_path, pair.temp_name, {
        skipActivityLog: true,
        renameContext: 'subtitle_manual_match_pair'
      })
      pair.temp_path = renameResult?.new_path || joinPath(String(pair.source_path || '').replace(/[\\/][^\\/]+$/, ''), pair.temp_name)
      phaseOneCompleted.push(pair)
    }

    for (const pair of phaseOne) {
      const operationLibraryId = pair.kind === 'audio' ? audioLibraryId : subtitleLibraryId
      const renameResult = await libraryApi.browserRename(operationLibraryId, pair.temp_path, pair.target_name, {
        skipActivityLog: true,
        renameContext: 'subtitle_manual_match_pair'
      })
      pair.final_path = renameResult?.new_path || joinPath(String(pair.temp_path || '').replace(/[\\/][^\\/]+$/, ''), pair.target_name)
      phaseTwoCompleted.push(pair)
    }

    for (const subtitle of unusedSubtitleRows) {
      await libraryApi.browserDelete(subtitleLibraryId, resolveSubtitleEntryPath(subtitle), true)
    }

    const currentTaskId = subtitleInspectorInfo.value.taskId
    const matchedSelectionItem = subtitleDialogSelection.value.find(item => buildSubtitleSelectionKey(item) === subtitlePreferredSelectionKey.value) || {
      library_id: subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,
      folder_path: subtitleInspectorInfo.value.folderPath,
      folder_name: getFileName(subtitleInspectorInfo.value.folderPath),
      rjcode: extractRJCode(subtitleInspectorInfo.value.folderPath || '') || ''
    }
    const fallbackTask = currentTaskId
      ? null
      : findSubtitleTaskBySelection(matchedSelectionItem)
    const effectiveTaskId = currentTaskId || fallbackTask?.id || ''
    if (effectiveTaskId) {
      const pairChanges = subtitleManualPairs.value.map(pair => ({
        audio_before: pair.audio_name || '',
        audio_after: pair.target_audio_name || '',
        subtitle_before: pair.subtitle_name || '',
        subtitle_after: pair.target_subtitle_name || ''
      }))
      await rjSubtitleApi.completeManual(effectiveTaskId, {
        appliedPairs: appliedPairCount,
        deletedSubtitles: unusedSubtitleRows.length,
        namingStrategy: effectiveNamingStrategy,
        pairChanges,
        folderPath: subtitleInspectorInfo.value.folderPath || matchedSelectionItem.folder_path || '',
        libraryId: subtitleInspectorInfo.value.libraryId || matchedSelectionItem.library_id || selectedLibraryId.value,
        rjcode: matchedSelectionItem.rjcode || extractRJCode(subtitleInspectorInfo.value.folderPath || '') || ''
      })
      markSubtitleTaskManualMatchCompleted(effectiveTaskId, {
        appliedPairs: appliedPairCount,
        deletedSubtitles: unusedSubtitleRows.length,
        namingStrategy: effectiveNamingStrategy,
        currentStep: `${buildSubtitleManualMatchSummary({ appliedPairs: appliedPairCount, deletedSubtitles: unusedSubtitleRows.length })}，可继续重新筛选后再次应用`
      })

      await Promise.all([
        refreshLibrary({ silent: true }),
        refreshRJSubtitleStatus(false, { silent: true })
      ])

      if (isLinkedImport) {
        const refreshedTask = subtitleTasks.value.find(task => task.id === effectiveTaskId)
        if (refreshedTask?.subtitle_dir) {
          await inspectSubtitleTask(refreshedTask, { force: true })
        } else {
          clearSubtitleInspectorState()
        }
      } else {
        await reloadSubtitleInspector()
      }
    } else {
      markSubtitleSelectionManualMatchCompleted(matchedSelectionItem, {
        appliedPairs: appliedPairCount,
        deletedSubtitles: unusedSubtitleRows.length
      })
      subtitleInspectorInfo.value = {
        ...subtitleInspectorInfo.value,
        manualMatchCompleted: true,
        manualMatchAppliedPairs: appliedPairCount,
        manualMatchDeletedSubtitles: unusedSubtitleRows.length,
        manualMatchMessage: `${buildSubtitleManualMatchSummary({ appliedPairs: appliedPairCount, deletedSubtitles: unusedSubtitleRows.length })}，可继续重新筛选后再次应用`
      }
      await reloadSubtitleInspector()
      await Promise.all([
        refreshLibrary({ silent: true }),
        refreshRJSubtitleStatus(false, { silent: true })
      ])
    }

    ElMessage.success(`${isLinkedImport ? '已重命名并导入' : '已应用'} ${appliedPairCount} 组配对${unusedSubtitleRows.length ? `，并删除 ${unusedSubtitleRows.length} 个未使用字幕` : ''}。当前目录已标记为已执行过配对，可继续调整后再次应用。`)
    clearSubtitleManualPairs()
  } catch (error) {
    const rollbackPairs = [
      ...phaseTwoCompleted,
      ...phaseOneCompleted.filter(pair => !phaseTwoCompleted.includes(pair))
    ]
    let rollbackSummary = ''
    if (rollbackPairs.length) {
      const rollbackResult = await rollbackSubtitleManualRenamePairs(rollbackPairs, audioLibraryId, subtitleLibraryId)
      rollbackSummary = rollbackResult.failed.length
        ? `；已回滚 ${rollbackResult.restored} 项，仍有 ${rollbackResult.failed.length} 项需要手动恢复`
        : `；已自动回滚 ${rollbackResult.restored} 项`
      if (!rollbackResult.failed.length) {
        await Promise.all([
          refreshLibrary({ silent: true }),
          refreshRJSubtitleStatus(false, { silent: true }),
          reloadSubtitleInspector()
        ])
        restoreSubtitleManualMatchSnapshot(preApplySnapshot)
      }
    }
    ElMessage.error(`${isLinkedImport ? '重命名并导入' : '应用配对'}失败: ${(error.response?.data?.detail || error.message)}${rollbackSummary}`)
  } finally {
    subtitlePairApplying.value = false
  }
}

function normalizeSubtitleDownloadKey (name) {
  let current = String(name || '')
  const subtitleExts = ['.lrc', '.vtt', '.srt', '.ass', '.ssa']
  const audioExts = ['.wav', '.mp3', '.flac', '.m4a', '.ogg', '.wma', '.aac']
  let subtitleExt = ''

  for (const ext of subtitleExts) {
    if (current.toLowerCase().endsWith(ext)) {
      subtitleExt = ext
      current = current.slice(0, -ext.length)
      break
    }
  }
  while (audioExts.some(ext => current.toLowerCase().endsWith(ext))) {
    const matchedExt = audioExts.find(ext => current.toLowerCase().endsWith(ext))
    current = current.slice(0, -matchedExt.length)
  }
  return `${current.toLowerCase()}${subtitleExt}`
}

function getSubtitleDownloadFiles (task) {
  const deduped = new Map()
  for (const file of task?.download_files || []) {
    const name = String(file?.name || '')
    const key = normalizeSubtitleDownloadKey(file?.name || '')
    const existing = deduped.get(key)
    if (!existing) {
      deduped.set(key, file)
      continue
    }

    const currentIsWav = name.toLowerCase().includes('.wav.')
    const existingIsWav = String(existing?.name || '').toLowerCase().includes('.wav.')
    if (currentIsWav && !existingIsWav) {
      deduped.set(key, file)
      continue
    }
    if (currentIsWav === existingIsWav && Number(file?.progress || 0) > Number(existing?.progress || 0)) {
      deduped.set(key, file)
    }
  }
  return Array.from(deduped.values())
}

function getSubtitleDownloadDisplayName (file) {
  const displayName = String(file?.display_name || file?.name || '字幕文件')
  const extMatch = displayName.match(/\.[^.]+$/)
  const subtitleExt = extMatch?.[0] || ''
  const baseName = subtitleExt ? displayName.slice(0, -subtitleExt.length) : displayName
  const normalizedBase = stripTrailingAudioExtension(baseName)
  return subtitleExt ? `${normalizedBase}${subtitleExt}` : normalizedBase
}

function allSubtitleDownloadsCompleted (task) {
  const files = getSubtitleDownloadFiles(task)
  return files.length > 0 && files.every(file => Number(file?.progress || 0) >= 100)
}

function isSubtitleDownloadExpanded (taskId) {
  return Boolean(subtitleDownloadExpandedMap.value[taskId])
}

function toggleSubtitleDownloadExpanded (taskId) {
  if (!taskId) return
  subtitleDownloadExpandedMap.value = {
    ...subtitleDownloadExpandedMap.value,
    [taskId]: !subtitleDownloadExpandedMap.value[taskId]
  }
}

function visibleSubtitleDownloadFiles (task) {
  const files = getSubtitleDownloadFiles(task)
  if (!files.length) return []
  if (!allSubtitleDownloadsCompleted(task) || isSubtitleDownloadExpanded(task?.id)) return files
  return files.slice(0, 6)
}

function hiddenSubtitleDownloadCount (task) {
  return Math.max(0, getSubtitleDownloadFiles(task).length - visibleSubtitleDownloadFiles(task).length)
}

function isSubtitleIssueExpanded (taskId) {
  return Boolean(subtitleIssueExpandedMap.value[taskId])
}

function toggleSubtitleIssueExpanded (taskId) {
  if (!taskId) return
  subtitleIssueExpandedMap.value = {
    ...subtitleIssueExpandedMap.value,
    [taskId]: !subtitleIssueExpandedMap.value[taskId]
  }
}

function visibleSubtitleWriteErrors (task) {
  const items = normalizeSubtitleWriteErrors(task?.write_errors)
  if (isSubtitleIssueExpanded(task?.id)) return items
  return items.slice(0, 6)
}

function visibleSubtitleFailedFiles (task) {
  const items = task?.failed_files || []
  if (isSubtitleIssueExpanded(task?.id)) return items
  const remainingSlots = Math.max(0, 6 - visibleSubtitleWriteErrors(task).length)
  return items.slice(0, remainingSlots)
}

function hiddenSubtitleIssueCount (task) {
  const writeErrorCount = normalizeSubtitleWriteErrors(task?.write_errors).length
  const failedFileCount = (task?.failed_files || []).length
  const visibleCount = visibleSubtitleWriteErrors(task).length + visibleSubtitleFailedFiles(task).length
  return Math.max(0, writeErrorCount + failedFileCount - visibleCount)
}

function escapeHtml (value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function decodePossibleMojibake (value) {
  const text = String(value || '')
  if (!/[ÃÂÐæçéèêïîöôåäüë鈥]/.test(text) && !/[鐩鍙彇瀛]/.test(text)) return text
  try {
    const bytes = Uint8Array.from(Array.from(text).map(char => char.charCodeAt(0) & 0xff))
    const decoded = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
    return decoded && /[\u4e00-\u9fff]/.test(decoded) ? decoded : text
  } catch (_) {
    return text
  }
}

function syncRemoteStatsDeletion ({ deletedBytes = 0, deletedFolderCount = 0, libraryId = selectedLibraryId.value } = {}) {
  if (!libraryId) return
  const current = statsMap.value[libraryId]
  if (!current) return

  const sizeDelta = Math.max(0, Number(deletedBytes || 0))
  const folderDelta = Math.max(0, Number(deletedFolderCount || 0))
  const nextLibraryStats = {
    ...current,
    total_size_bytes: Math.max(0, Number(current.total_size_bytes || 0) - sizeDelta),
    folder_count: Math.max(0, Number(current.folder_count || 0) - folderDelta),
    updated_at: Date.now() / 1000,
    total_size_gb: 0
  }
  nextLibraryStats.total_size_gb = Number((nextLibraryStats.total_size_bytes / (1024 ** 3)).toFixed(2))

  statsMap.value = {
    ...statsMap.value,
    [libraryId]: nextLibraryStats
  }

  aggregateStats.value = {
    ...aggregateStats.value,
    total_size_bytes: Math.max(0, Number(aggregateStats.value.total_size_bytes || 0) - sizeDelta),
    folder_count: Math.max(0, Number(aggregateStats.value.folder_count || 0) - folderDelta),
    total_size_gb: 0
  }
  aggregateStats.value.total_size_gb = Number((aggregateStats.value.total_size_bytes / (1024 ** 3)).toFixed(2))
}

async function refreshStatsAfterMutation (options = {}) {
  const { deletedBytes = 0, deletedFolderCount = 0, libraryId = selectedLibraryId.value } = options
  if (isRemoteCurrentLibrary.value) {
    syncRemoteStatsDeletion({ deletedBytes, deletedFolderCount, libraryId })
    return
  }
  await refreshStats(true, { refreshLibraryId: libraryId })
}

function syncSubtitleTaskListState () {
  const visibleTasks = visibleSubtitleTasks.value
  if (!visibleTasks.length) {
    subtitleActiveTaskId.value = ''
    return
  }
  if (subtitleActiveTaskId.value && visibleTasks.some(task => task.id === subtitleActiveTaskId.value)) return
  const preferredTask = findTaskMatchingPreferredSelection(visibleTasks)
  if (preferredTask && ['pending', 'processing'].includes(preferredTask.status)) {
    subtitleActiveTaskId.value = preferredTask.id
    return
  }
  subtitleActiveTaskId.value = ''
}

function focusSubtitleTask(taskId) {
  if (!taskId) return
  if (!visibleSubtitleTasks.value.some(task => task.id === taskId)) return
  subtitleActiveTaskId.value = taskId
}

function canClearCurrentSubtitleTask (task) {
  if (!task?.id) return false
  if (['pending', 'processing'].includes(task.status)) return false
  return true
}

function getSubtitleTasksByClearScope (scope) {
  const clearable = subtitleQueueTasks.value.filter(task => canClearCurrentSubtitleTask(task))
  if (scope === 'completed') {
    return clearable.filter(task => task.status === 'completed' && !isRJSubtitleTaskCancelled(task))
  }
  if (scope === 'failed') {
    return clearable.filter(task => task.status === 'failed' || isRJSubtitleTaskCancelled(task))
  }
  return clearable
}

async function clearSubtitleTasksByScope (scope) {
  const targets = getSubtitleTasksByClearScope(scope)
  if (!targets.length) {
    ElMessage.warning(scope === 'completed' ? '没有可清理的成功任务' : scope === 'failed' ? '没有可清理的失败任务' : '没有可清理的已结束任务')
    return
  }

  const label = scope === 'completed' ? '成功任务' : scope === 'failed' ? '失败任务' : '已结束任务'
  try {
    await showSystemConfirm({
      title: '批量清空任务确认',
      message: `确定清空 ${targets.length} 个${label}吗？运行中的任务不会被清掉。`,
      tone: 'warning',
      confirmText: '确定清空',
      cancelText: '取消'
    })
  } catch (_) {
    return
  }

  subtitleBulkClearingScope.value = scope
  try {
    let successCount = 0
    let failedCount = 0
    for (const task of targets) {
      try {
        await rjSubtitleApi.clearTask(task.id)
        successCount += 1
        if (subtitleInspectorInfo.value.taskId === task.id) clearSubtitleInspectorState()
        if (subtitleActiveTaskId.value === task.id) subtitleActiveTaskId.value = ''
      } catch (error) {
        failedCount += 1
        console.error('批量清理字幕任务失败:', task.id, error)
      }
    }
    await refreshRJSubtitleStatus(false, { silent: true })
    if (failedCount) {
      ElMessage.warning(`批量清空完成：成功 ${successCount}，失败 ${failedCount}`)
    } else {
      ElMessage.success(`已清空 ${successCount} 个${label}`)
    }
  } finally {
    subtitleBulkClearingScope.value = ''
  }
}

function markSubtitleTaskManualMatchCompleted (taskId, payload = {}) {
  if (!taskId) return
  subtitleTasks.value = subtitleTasks.value.map(task => {
    if (task.id !== taskId) return task
    return {
      ...task,
      status: 'completed',
      progress: 100,
      awaiting_manual_match: false,
      manual_match_completed: true,
      manual_match_applied_pairs: payload.appliedPairs ?? task.manual_match_applied_pairs ?? 0,
      manual_match_deleted_subtitles: payload.deletedSubtitles ?? task.manual_match_deleted_subtitles ?? 0,
      naming_strategy: payload.namingStrategy || task.naming_strategy || 'audio',
      current_step: payload.currentStep || task.current_step
    }
  })
}

function buildSubtitleManualMatchSummary (payload = {}) {
  const appliedPairs = Math.max(0, Number(payload.appliedPairs || 0))
  const deletedSubtitles = Math.max(0, Number(payload.deletedSubtitles || 0))
  let summary = `已应用 ${appliedPairs} 组配对`
  if (deletedSubtitles > 0) {
    summary += `，并删除 ${deletedSubtitles} 个未使用字幕`
  }
  return summary
}

function markSubtitleSelectionManualMatchCompleted (item, payload = {}) {
  if (!item?.folder_path) return
  const summary = `${buildSubtitleManualMatchSummary(payload)}。可继续重新筛选后再次应用。`
  upsertSubtitleSelectionEntry(item, {
    queue_state: 'manual_match_completed',
    queue_message: summary,
    manual_match_completed: true,
    manual_match_applied_pairs: Math.max(0, Number(payload.appliedPairs || 0)),
    manual_match_deleted_subtitles: Math.max(0, Number(payload.deletedSubtitles || 0)),
    status: 'existing'
  })
}

async function clearCurrentSubtitleTask (task) {
  if (!canClearCurrentSubtitleTask(task)) return
  try {
    await rjSubtitleApi.clearTask(task.id)
    if (subtitleInspectorInfo.value.taskId === task.id) clearSubtitleInspectorState()
    if (subtitleActiveTaskId.value === task.id) subtitleActiveTaskId.value = ''
    await refreshRJSubtitleStatus(false, { silent: true })
    ElMessage.success('任务已清理')
  } catch (error) {
    ElMessage.error('清理字幕任务失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function focusSubtitleSelectionItem (item) {
  if (!item?.folder_path) return
  subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(item)
  syncSubtitleTaskListState()
  const matchedTask = findSubtitleTaskBySelection(item)
  if (matchedTask?.subtitle_dir) {
    await inspectSubtitleTask(matchedTask)
    return
  }
  if (canInspectSubtitleSelectionFolder(item)) {
    await inspectSubtitleSelectionFolder(item)
    return
  }
  if (!matchedTask || subtitleInspectorInfo.value.taskId !== matchedTask.id) {
    clearSubtitleInspectorState()
  }
}

async function forceCreateSubtitleTaskForSelection (item) {
  if (!item?.folder_path) return
  const forceKey = buildSubtitleSelectionKey(item)
  subtitleForceQueueKey.value = forceKey
  resetSubtitleScanRunIndicators()
  incrementSubtitleScanSession('foundDirectories')
  try {
    upsertSubtitleSelectionEntry(item, {
      queue_state: 'checking_subtitle',
      queue_message: '正在检测远程字幕'
    })
    const availability = await ensureRJSubtitleAvailabilityForItem(item)
    if (!availability.hasSubtitle) {
      incrementSubtitleScanSession('noSubtitleTargets')
      upsertSubtitleSelectionEntry(item, {
        queue_state: 'skipped_no_subtitle',
        queue_message: availability.message || 'asmr.one 没字幕'
      })
      ElMessage.warning(availability.message || 'asmr.one 没字幕，无法创建任务')
      return
    }

    upsertSubtitleSelectionEntry(item, {
      queue_state: 'creating',
      queue_message: availability.message || '检测到可用字幕，正在加入任务'
    })
    const data = await submitRJSubtitleTasks([item], {
      silent: false,
      refresh: true,
      skipIfExistingSubtitlesOverride: true
    })
    const skippedItem = Array.isArray(data?.skipped_items)
      ? data.skipped_items.find(entry => buildSubtitleSelectionKey(entry) === buildSubtitleSelectionKey(item))
      : null
    if (skippedItem?.queue_state === 'skipped_kikoeru_existing') {
      incrementSubtitleScanSession('existingSubtitles')
      upsertSubtitleSelectionEntry(item, {
        queue_state: 'skipped_kikoeru_existing',
        queue_message: skippedItem.queue_message || 'Kikoeru 已有字幕，未加入抓取任务'
      })
      ElMessage.info(skippedItem.queue_message || 'Kikoeru 已有字幕，已跳过')
      return
    }
    if (skippedItem?.queue_state === 'existing_task') {
      incrementSubtitleScanSession('existingTasks')
      upsertSubtitleSelectionEntry(item, {
        task_id: skippedItem.task_id || '',
        queue_state: 'existing_task',
        queue_message: skippedItem.queue_message || '任务已存在'
      })
      if (skippedItem.task_id) subtitleActiveTaskId.value = skippedItem.task_id
      ElMessage.info(skippedItem.queue_message || '任务已存在')
      return
    }
    if (skippedItem?.queue_state === 'skipped_no_subtitle') {
      incrementSubtitleScanSession('noSubtitleTargets')
      upsertSubtitleSelectionEntry(item, {
        queue_state: 'skipped_no_subtitle',
        queue_message: skippedItem.queue_message || '远程无字幕'
      })
      ElMessage.warning(skippedItem.queue_message || '远程无字幕，无法创建任务')
      return
    }
    const createdTask = data?.tasks?.[0] || null
    if (createdTask?.task_id) {
      incrementSubtitleScanSession('createdTasks')
      upsertSubtitleTaskLocal(createOptimisticSubtitleTask(item, createdTask.task_id))
      upsertSubtitleSelectionEntry(item, {
        task_id: createdTask.task_id,
        queue_state: 'queued',
        queue_message: '已加入任务'
      })
      subtitleActiveTaskId.value = createdTask.task_id
      return
    }
    incrementSubtitleScanSession('createFailed')
    upsertSubtitleSelectionEntry(item, {
      queue_state: 'create_failed',
      queue_message: data?.message || '未创建任务'
    })
  } catch (error) {
    incrementSubtitleScanSession('createFailed')
    upsertSubtitleSelectionEntry(item, {
      queue_state: 'create_failed',
      queue_message: error.response?.data?.detail || error.message || '加入任务失败'
    })
  } finally {
    subtitleForceQueueKey.value = ''
  }
}

function canRerunSubtitleTask (task) {
  if (!task?.folder_path || !task?.id) return false
  if (['pending', 'processing'].includes(task.status)) return false
  return !subtitleTaskRerunId.value && !subtitleForceQueueKey.value
}

async function rerunSubtitleTask (task) {
  if (!canRerunSubtitleTask(task)) return
  subtitleTaskRerunId.value = task.id
  subtitlePreferredSelectionKey.value = buildSubtitleTaskSelectionKey(task)
  try {
    const data = await rjSubtitleApi.rerunTask(task.id, {
      overwriteExisting: subtitleOptions.value.overwriteExisting,
      enableMetadataMatch: subtitleOptions.value.enableMetadataMatch,
      namingStrategy: subtitleOptions.value.namingStrategy,
      useFilterRules: subtitleOptions.value.useFilterRules,
      subtitleFilterRules: sanitizeSubtitleFilterRules(subtitleOptions.value.subtitleFilterRules)
    })
    if (data?.task_id) {
      subtitleActiveTaskId.value = data.task_id
      upsertSubtitleTaskLocal({
        ...task,
        status: 'pending',
        progress: 0,
        current_step: data.message || '等待重新抓取字幕',
        error_message: '',
        subtitle_dir: '',
        awaiting_manual_match: false,
        manual_match_completed: false,
        manual_match_applied_pairs: 0,
        manual_match_deleted_subtitles: 0,
        written_files: [],
        skipped_files: [],
        failed_files: [],
        write_errors: [],
        match_result: {},
        download_files: [],
        downloaded_count: 0,
        force_rerun: true
      })
      await refreshRJSubtitleStatus(false, { silent: true })
      ElMessage.success(data.message || '任务已重新加入抓取队列')
      if (subtitleInspectorInfo.value.taskId === task.id) {
        clearSubtitleInspectorState()
      }
      const selectionItem = buildSubtitleSelectionItemFromTask(task)
      upsertSubtitleSelectionEntry(selectionItem, {
        task_id: task.id,
        queue_state: 'queued',
        queue_message: data.message || '已重置当前任务并重新抓取'
      })
    }
  } finally {
    if (subtitleTaskRerunId.value === task.id) subtitleTaskRerunId.value = ''
  }
}

function isSubtitleSelectionActive (item) {
  return buildSubtitleSelectionKey(item) === buildSubtitleSelectionKey(focusedSubtitleSelectionItem.value)
}

async function selectSubtitleTask (task) {
  if (!task?.id) return
  subtitleActiveTaskId.value = task.id
  subtitlePreferredSelectionKey.value = buildSubtitleTaskSelectionKey(task)
  if (task.subtitle_dir) {
    await inspectSubtitleTask(task)
    return
  }
  clearSubtitleInspectorState()
}

async function refreshRJSubtitleStatus (showMessage = false, options = {}) {
  const { silent = false } = options
  clearSubtitleStatusPoll()
  if (!silent) subtitleTasksLoading.value = true
  try {
    const data = await rjSubtitleApi.status()
    const detailTaskIds = new Set([
      subtitleActiveTaskId.value,
      subtitleInspectorInfo.value.taskId
    ].filter(Boolean))
    const remoteTasks = (data.tasks || [])
      .filter(task => !isLinkedSubtitleImportSourceMode(task?.source_mode))
      .map(task => normalizeRJSubtitleTaskPayload(task, {
        preserveDetail: detailTaskIds.has(task.id)
      }))
    subtitleTasks.value = mergeSubtitleTasksWithOptimistic(remoteTasks)
    if (!subtitleTasks.value.length) {
      clearSubtitleInspectorState()
    }
    syncSubtitleInspectorTaskState()
    syncSubtitleSelectionState()
    if (subtitleInspectorInfo.value.taskId && !subtitleTasks.value.some(task => task.id === subtitleInspectorInfo.value.taskId && task.subtitle_dir)) {
      clearSubtitleInspectorState()
    }
    await ensureSubtitleInspectorFocus()
    scheduleSubtitleStatusPoll(subtitleTasks.value)
    if (showMessage) ElMessage.success('字幕任务状态已刷新')
  } catch (error) {
    if (!silent) {
      ElMessage.error('获取字幕任务状态失败: ' + (error.response?.data?.detail || error.message))
    }
  } finally {
    if (!silent) subtitleTasksLoading.value = false
  }
}

async function refreshCurrentView () {
  if (isRefreshingCurrentView.value) return
  isRefreshingCurrentView.value = true
  try {
    const jobs = [refreshLibrary({ silent: true })]
    if (folderDialogVisible.value && folderDialogRef.value?.reload) {
      jobs.push(folderDialogRef.value.reload())
    }
    if (filterDeleteDialogVisible.value && filterDeleteDialogRef.value?.reload) {
      jobs.push(filterDeleteDialogRef.value.reload())
    }
    if (subtitleDialogSessionActive.value) {
      jobs.push(refreshRJSubtitleStatus(false, { silent: true }))
      if (subtitleInspectorInfo.value.subtitleDir && activeSubtitleInspectTask.value) {
        jobs.push(inspectSubtitleTask(activeSubtitleInspectTask.value, { force: true }))
      }
    }
    await Promise.all(jobs)
    ElMessage.success('当前页面信息已刷新')
  } catch (error) {
    ElMessage.error('刷新当前页面失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    isRefreshingCurrentView.value = false
  }
}

function resolveSubtitleAvailabilityTarget () {
  if (activeSubtitleTask.value) {
    return {
      rjcode: getTaskDisplayRJCode(activeSubtitleTask.value),
      folderName: activeSubtitleTask.value.folder_name || getFileName(activeSubtitleTask.value.folder_path)
    }
  }
  if (focusedSubtitleSelectionItem.value) {
    return {
      rjcode: focusedSubtitleSelectionItem.value.rjcode || '',
      folderName: focusedSubtitleSelectionItem.value.folder_name || getFileName(focusedSubtitleSelectionItem.value.folder_path)
    }
  }
  if (currentFolderSubtitleItem.value) {
    return {
      rjcode: currentFolderSubtitleItem.value.rjcode || '',
      folderName: currentFolderSubtitleItem.value.folder_name || getFileName(currentFolderSubtitleItem.value.folder_path)
    }
  }
  return null
}

function getSubtitleAttemptTypeLabel (value) {
  const mapping = {
    requested: '当前作品',
    original: '原作',
    parent: '母作品',
    child: '关联子作品',
    translation: '关联译版'
  }
  return mapping[String(value || '')] || '关联作品'
}

async function checkRJSubtitleAvailability () {
  subtitleConnectivityLoading.value = true
  try {
    const target = resolveSubtitleAvailabilityTarget()
    if (!target?.rjcode) {
      ElMessage.warning('请先选中一个待处理目录或字幕任务')
      return
    }
    const data = await rjSubtitleApi.checkSubtitleAvailability(target.rjcode)
    const attempts = data.attempts || []
    const found = attempts.filter(item => Number(item.subtitle_count || 0) > 0)
    const summaryBlock = `<div style="margin-bottom:12px;padding:10px 12px;border:1px solid #d9ecff;background:#f4faff;border-radius:8px;color:#245b96;">
      目标目录: ${escapeHtml(target.folderName || '-') }<br>
      检测 RJ: ${escapeHtml(data.rjcode || target.rjcode)}<br>
      结果: ${found.length ? `找到 ${found.length} 个有字幕的版本` : '未发现可用字幕版本'}
    </div>`
    const listHtml = attempts.length
      ? attempts.map(item => {
          const subtitleCount = Number(item.subtitle_count || 0)
          const hasSubtitle = subtitleCount > 0
          return `<div style="padding:10px 0;border-bottom:1px solid #ebeef5;">
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <span style="font-weight:700;color:#303133;">${escapeHtml(item.rjcode || '-')}</span>
              <span style="padding:2px 8px;border-radius:999px;background:${hasSubtitle ? '#ecfdf3' : '#f5f7fa'};color:${hasSubtitle ? '#2f855a' : '#606266'};font-size:12px;font-weight:700;">
                ${hasSubtitle ? `有字幕 ${subtitleCount}` : '无字幕'}
              </span>
              <span style="padding:2px 8px;border-radius:999px;background:#eef4ff;color:#31599b;font-size:12px;">
                ${escapeHtml(getSubtitleAttemptTypeLabel(item.work_type))}
              </span>
              <span style="padding:2px 8px;border-radius:999px;background:#fff7e6;color:#b7791f;font-size:12px;">
                ${escapeHtml(getRJSubtitleLangLabel(item.lang || 'JPN'))}
              </span>
            </div>
            <div style="margin-top:6px;color:#303133;line-height:1.5;">${escapeHtml(item.title || item.reason || '未返回作品标题')}</div>
          </div>`
        }).join('')
      : '<div>没有返回作品检测结果</div>'
    const html = `${summaryBlock}${listHtml}`

    await showSystemAlert({
      title: '作品字幕检测结果',
      message: html,
      html: true,
      confirmText: '知道了'
    })
  } catch (error) {
    ElMessage.error('字幕检测失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    subtitleConnectivityLoading.value = false
  }
}

async function cancelRJSubtitleTask (task) {
  if (!canCancelRJSubtitleTask(task)) return
  try {
    await showSystemConfirm({
      title: '取消任务确认',
      message: `确定取消任务 ${task.actual_rjcode || task.rjcode || '未知RJ'} 吗？`,
      tone: 'warning',
      confirmText: '确定取消',
      cancelText: '继续执行'
    })
  } catch (_) {
    return
  }

  subtitleCancelingId.value = task.id
  try {
    const data = await rjSubtitleApi.cancel(task.id)
    ElMessage.success(data.message || '任务已取消')
    await refreshRJSubtitleStatus(false, { silent: true })
  } catch (error) {
    ElMessage.error('取消任务失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    subtitleCancelingId.value = ''
  }
}

async function navigateToPath (path) {
  const targetPath = path || browseRootPath.value || currentPath.value
  const targetPage = getRememberedDirectoryPage(targetPath, 1)
  const shouldRefreshNow = currentPage.value === targetPage
  rememberCurrentDirectoryPage()
  locatedLibraryPath.value = ''
  currentPath.value = targetPath
  currentPage.value = targetPage
  clearSelection()
  if (shouldRefreshNow) await refreshLibrary()
}

async function goToParent () {
  if (!canGoParent.value) return
  if (searchResultReturnState.value.active) {
    const restoreState = { ...searchResultReturnState.value }
    searchResultReturnState.value = createSearchResultReturnState()
    clearSelection()
    locatedLibraryPath.value = ''
    if (restoreState.libraryId && restoreState.libraryId !== selectedLibraryId.value) {
      pendingLibrarySearchRestore.value = restoreState
      selectedLibraryId.value = restoreState.libraryId
      return
    }
    searchQuery.value = restoreState.searchQuery || ''
    searchExact.value = Boolean(restoreState.searchExact)
    searchResultKind.value = restoreState.searchResultKind || 'all'
    currentPath.value = restoreState.currentPath || ''
    browseRootPath.value = restoreState.browseRootPath || ''
    currentPage.value = Number(restoreState.page || 1)
    sortBy.value = restoreState.sortBy || DEFAULT_SORT_BY
    sortOrder.value = restoreState.sortOrder || DEFAULT_SORT_ORDER
    librarySearchState.value = createLibrarySearchState({
      active: true,
      query: restoreState.searchState?.query || restoreState.searchQuery || '',
      rootPath: restoreState.searchState?.rootPath || restoreState.currentPath || '',
      truncated: Boolean(restoreState.searchState?.truncated),
      scannedDirectories: Number(restoreState.searchState?.scannedDirectories || 0),
      globalRemote: Boolean(restoreState.searchState?.globalRemote),
      searchedLibraries: Number(restoreState.searchState?.searchedLibraries || 0),
      hitLibraries: Number(restoreState.searchState?.hitLibraries || 0),
      exactSearch: Boolean(restoreState.searchState?.exactSearch ?? restoreState.searchExact),
      resultKind: restoreState.searchState?.resultKind || restoreState.searchResultKind || 'all'
    })
    await refreshLibrary({ forceRefresh: true })
    return
  }
  await navigateToPath(parentPath.value)
}

function isSearchResultRow (row) {
  return Boolean(librarySearchState.value.active && row?.search_hit)
}

function getSearchResultLibraryLabel (row) {
  const directName = String(row?.library_name || '').trim()
  if (directName) return directName
  const libraryId = String(row?.library_id || '').trim()
  if (!libraryId) return ''
  return libraries.value.find(item => item.id === libraryId)?.name || libraryId
}

function getLibraryLabelById (libraryId) {
  const normalized = String(libraryId || '').trim()
  if (!normalized) return ''
  return libraries.value.find(item => item.id === normalized)?.name || normalized
}

async function locateLibrarySearchResult (row) {
  if (!row?.path) return
  if (librarySearchState.value.active) {
    searchResultReturnState.value = createSearchResultReturnState({
      active: true,
      libraryId: selectedLibraryId.value,
      searchQuery: searchQuery.value,
      currentPath: currentPath.value,
      browseRootPath: browseRootPath.value,
      page: currentPage.value,
      sortBy: sortBy.value,
      sortOrder: sortOrder.value,
      searchExact: searchExact.value,
      searchResultKind: searchResultKind.value,
      searchState: { ...librarySearchState.value }
    })
  }
  const targetLibraryId = row.library_id || selectedLibraryId.value
  const targetPath = row.is_directory ? row.path : (row.parent_path || row.path)
  const highlightPath = row.path
  locatedLibraryPath.value = row.path
  searchQuery.value = ''
  librarySearchState.value = createLibrarySearchState()
  clearSelection()
  if (targetLibraryId && targetLibraryId !== selectedLibraryId.value) {
    pendingLibraryLocate.value = {
      libraryId: targetLibraryId,
      path: targetPath,
      highlightPath
    }
    selectedLibraryId.value = targetLibraryId
    return
  }
  currentPath.value = targetPath
  locatedLibraryPath.value = highlightPath
  const shouldRefreshNow = currentPage.value === 1
  currentPage.value = 1
  if (shouldRefreshNow) await refreshLibrary()
}

async function openFolder (row) {
  if (isSearchResultRow(row)) {
    await locateLibrarySearchResult(row)
    return
  }
  if (row?.is_directory) {
    locatedLibraryPath.value = ''
    await navigateToPath(row.path)
    return
  }
  if (isRemoteCurrentLibrary.value) {
    const data = await libraryApi.browserOpenFolder(selectedLibraryId.value, row.path)
    await showSystemAlert({
      title: '远程库存',
      message: `请在群晖 FileStation 中打开以下路径：<br><br>${escapeHtml(data.path || row.path)}<br><br>${escapeHtml(data.remote_url || '')}`,
      html: true,
      confirmText: '知道了'
    })
    return
  }
  const data = await libraryApi.openFolder(row.path)
  if (data.mode === 'mapped') {
    mappedPathInfo.value = { originalPath: data.original_path, mappedPath: data.mapped_path, isMapped: data.is_mapped }
    mappedPathDialogVisible.value = true
    return
  }
  ElMessage.success('已打开文件夹')
}

async function openFolderDirect (row) {
  if (isRemoteCurrentLibrary.value) {
    try {
      const data = await libraryApi.browserOpenFolder(selectedLibraryId.value, row.path)
      if (data.web_url) {
        window.open(data.web_url, '_blank', 'noopener')
        ElMessage.success('已打开群晖目录')
        return
      }
      await showSystemAlert({
        title: '远程库存',
        message: `请在群晖 FileStation 中打开以下路径：<br><br>${escapeHtml(data.path || row.path)}`,
        html: true,
        confirmText: '知道了'
      })
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || error.message || '打开群晖目录失败')
    }
    return
  }
  const data = await libraryApi.openFolder(row.path)
  if (data.mode !== 'mapped') {
    ElMessage.success('已打开文件夹')
    return
  }
  const path = data.mapped_path
  const hasHelper = window.kikoeruHelperLoaded || tampermonkeyLoaded.value
  window.dispatchEvent(new CustomEvent('kikoeru-open-folder', { detail: { path } }))
  hasHelper ? ElMessage.success('正在打开文件夹...') : ElMessage.info('正在尝试打开文件夹...')
}

async function copyMappedPath () {
  try {
    await navigator.clipboard.writeText(mappedPathInfo.value.mappedPath)
    ElMessage.success('已复制')
  } catch (_) {
    ElMessage.error('复制失败')
  }
}

function openWithBrowser () {
  const path = mappedPathInfo.value.mappedPath
  if (window.kikoeruHelperLoaded || tampermonkeyLoaded.value) {
    window.dispatchEvent(new CustomEvent('kikoeru-open-folder', { detail: { path } }))
    return
  }
  let url = path.replace(/\\/g, '/')
  url = /^[a-zA-Z]:/.test(url) ? `file:///${url}` : `file://${url}`
  try { window.open(url, '_blank') } catch (_) {}
}

function syncSubtitleInspectorTaskState () {
  if (!subtitleInspectorInfo.value.taskId) return
  const task = subtitleTasks.value.find(item => item.id === subtitleInspectorInfo.value.taskId)
  if (!task?.subtitle_dir) {
    clearSubtitleInspectorState()
    return
  }
  subtitleInspectorInfo.value = {
    ...subtitleInspectorInfo.value,
    taskId: task.id,
    libraryId: task.library_id || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,
    audioLibraryId: task.library_id || subtitleInspectorInfo.value.audioLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,
    subtitleLibraryId: task.subtitle_library_id || subtitleInspectorInfo.value.subtitleLibraryId || task.library_id || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,
    folderPath: task.folder_path,
    subtitleDir: task.subtitle_dir,
    sourceMode: task.source_mode || subtitleInspectorInfo.value.sourceMode || '',
    manualMatchCompleted: Boolean(task.manual_match_completed),
    manualMatchAppliedPairs: Number(task.manual_match_applied_pairs || 0),
    manualMatchDeletedSubtitles: Number(task.manual_match_deleted_subtitles || 0),
    manualMatchMessage: task.current_step || ''
  }
}

async function ensureSubtitleInspectorFocus () {
  if (!subtitleDialogVisible.value) return
  if (subtitleInspectorBusy.value || subtitleInspectorInfo.value.subtitleDir) return
  const preferredTaskId = resolveCurrentSubtitleTaskId(subtitleTasks.value)
  const preferredTask = subtitleTasks.value.find(task => task.id === preferredTaskId)
  if (preferredTask?.subtitle_dir) {
    await inspectSubtitleTask(preferredTask)
    return
  }
  const nextTask = sortSubtitleTasksByCreatedAt(subtitleTasks.value.filter(task => task.subtitle_dir && isSubtitleTaskAwaitingManualWork(task)))[0]
    || sortSubtitleTasksByCreatedAt(subtitleTasks.value.filter(task => task.subtitle_dir))[0]
  if (nextTask?.subtitle_dir) {
    await inspectSubtitleTask(nextTask)
  }
}

async function inspectSubtitleSelectionFolder (item, options = {}) {
  const { force = false, preferredTaskId = '' } = options
  if (!item?.folder_path) return

  const inspectorLibraryId = item.library_id || selectedLibraryId.value
  let subtitleDir = joinFolderPath(item.folder_path, 'subtitles')
  const matchedTask = findSubtitleTaskBySelection(item)
  subtitlePreferredSelectionKey.value = buildSubtitleSelectionKey(item)

  if (
    !force &&
    !subtitleInspectorInfo.value.taskId &&
    subtitleInspectorInfo.value.folderPath === item.folder_path &&
    subtitleInspectorInfo.value.subtitleDir === subtitleDir &&
    !subtitleInspectorLoading.value
  ) {
    return
  }

  subtitleInspectorLoading.value = true
  try {
    const existingState = await ensureRJSubtitleExistingStateForItem(item)
    if (existingState?.subtitleDir) {
      subtitleDir = existingState.subtitleDir
    }
    if (!existingState?.hasExistingSubtitles && !Number(item.existing_subtitle_count || 0) && item.status !== 'existing') {
      ElMessage.info('当前目录还没有本地字幕，暂时无法打开字幕树工作台')
      return
    }
    upsertSubtitleSelectionEntry(item, {
      status: existingState?.hasExistingSubtitles ? 'existing' : (item.status || ''),
      existing_subtitle_count: Math.max(
        Number(item.existing_subtitle_count || 0),
        Number(existingState?.existingSubtitleCount || 0)
      )
    })
    const [subtitleData, audioData] = await Promise.all([
      libraryApi.browserFolderContents(inspectorLibraryId, subtitleDir),
      libraryApi.browserFolderContents(inspectorLibraryId, item.folder_path)
    ])
    subtitleInspectorSearch.value = ''
    subtitleInspectorItems.value = subtitleData.items || []
    subtitleInspectorAudioItems.value = audioData.items || []
    resetSubtitleManualMatchState()
    subtitleInspectorInfo.value = {
      taskId: matchedTask?.id || String(preferredTaskId || item.task_id || '').trim(),
      libraryId: inspectorLibraryId,
      audioLibraryId: matchedTask?.library_id || inspectorLibraryId,
      subtitleLibraryId: matchedTask?.subtitle_library_id || inspectorLibraryId,
      folderPath: item.folder_path || '',
      subtitleDir: subtitleData.folder_path || subtitleDir,
      sourceMode: matchedTask?.source_mode || '',
      manualMatchCompleted: Boolean(matchedTask?.manual_match_completed ?? item.manual_match_completed),
      manualMatchAppliedPairs: Number(matchedTask?.manual_match_applied_pairs ?? item.manual_match_applied_pairs ?? 0),
      manualMatchDeletedSubtitles: Number(matchedTask?.manual_match_deleted_subtitles ?? item.manual_match_deleted_subtitles ?? 0),
      manualMatchMessage: String(matchedTask?.current_step || item.queue_message || ''),
      totalFiles: subtitleData.total_files || 0,
      totalSize: (subtitleData.items || []).reduce((sum, child) => sum + (child.size || 0), 0)
    }
    const opened = new Set()
    buildTree(subtitleInspectorItems.value).forEach(node => { if (node.type === 'dir') opened.add(node.id) })
    subtitleInspectorExpandedIds.value = opened
    subtitleInspectorSelectedIds.value = new Set()
    subtitleInspectorLastSelectedId.value = ''
    syncSubtitleSelectionState()
    await nextTick()
    buildAutoSubtitlePairs()
  } catch (error) {
    ElMessage.error('加载现有字幕目录失败: ' + decodePossibleMojibake(error.response?.data?.detail || error.message))
  } finally {
    subtitleInspectorLoading.value = false
  }
}

async function inspectSubtitleTask (task, options = {}) {
  const { force = false } = options
  if (!task?.subtitle_dir) {
    ElMessage.warning('当前任务还没有生成字幕目录')
    return
  }

  focusSubtitleTask(task.id)
  subtitlePreferredSelectionKey.value = buildSubtitleTaskSelectionKey(task)
  if (
    !force &&
    subtitleInspectorInfo.value.taskId === task.id &&
    subtitleInspectorInfo.value.subtitleDir === task.subtitle_dir &&
    !subtitleInspectorLoading.value
  ) {
    return
  }
  subtitleInspectorLoading.value = true
  try {
    const audioLibraryId = task.library_id || selectedLibraryId.value
    const subtitleLibraryId = task.subtitle_library_id || audioLibraryId
    const [subtitleData, audioData] = await Promise.all([
      libraryApi.browserFolderContents(subtitleLibraryId, task.subtitle_dir),
      libraryApi.browserFolderContents(audioLibraryId, task.folder_path)
    ])
    subtitleInspectorSearch.value = ''
    subtitleInspectorItems.value = subtitleData.items || []
    subtitleInspectorAudioItems.value = audioData.items || []
    resetSubtitleManualMatchState()
    subtitleInspectorInfo.value = {
      taskId: task.id,
      libraryId: audioLibraryId,
      audioLibraryId,
      subtitleLibraryId,
      folderPath: task.folder_path || '',
      subtitleDir: subtitleData.folder_path || task.subtitle_dir,
      sourceMode: task.source_mode || '',
      manualMatchCompleted: Boolean(task.manual_match_completed),
      manualMatchAppliedPairs: Number(task.manual_match_applied_pairs || 0),
      manualMatchDeletedSubtitles: Number(task.manual_match_deleted_subtitles || 0),
      manualMatchMessage: task.current_step || '',
      totalFiles: subtitleData.total_files || 0,
      totalSize: (subtitleData.items || []).reduce((sum, item) => sum + (item.size || 0), 0)
    }
    const opened = new Set()
    buildTree(subtitleInspectorItems.value).forEach(node => { if (node.type === 'dir') opened.add(node.id) })
    subtitleInspectorExpandedIds.value = opened
    subtitleInspectorSelectedIds.value = new Set()
    subtitleInspectorLastSelectedId.value = ''
    syncSubtitleSelectionState()
    await nextTick()
    buildAutoSubtitlePairs()
  } catch (error) {
    ElMessage.error('加载字幕目录失败: ' + decodePossibleMojibake(error.response?.data?.detail || error.message))
  } finally {
    subtitleInspectorLoading.value = false
  }
}

async function reloadSubtitleInspector () {
  if (activeSubtitleInspectTask.value) {
    await inspectSubtitleTask(activeSubtitleInspectTask.value, { force: true })
    return
  }
  if (subtitleInspectorInfo.value.subtitleDir && subtitleInspectorInfo.value.folderPath) {
    const matchedItem = subtitleDialogSelection.value.find(item => buildSubtitleSelectionKey(item) === subtitlePreferredSelectionKey.value)
    await inspectSubtitleSelectionFolder({
      library_id: matchedItem?.library_id || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,
      folder_path: matchedItem?.folder_path || subtitleInspectorInfo.value.folderPath,
      folder_name: matchedItem?.folder_name || getFileName(subtitleInspectorInfo.value.folderPath),
      rjcode: matchedItem?.rjcode || extractRJCode(subtitleInspectorInfo.value.folderPath || '') || '',
      manual_match_completed: matchedItem?.manual_match_completed || subtitleInspectorInfo.value.manualMatchCompleted,
      manual_match_applied_pairs: matchedItem?.manual_match_applied_pairs || subtitleInspectorInfo.value.manualMatchAppliedPairs,
      manual_match_deleted_subtitles: matchedItem?.manual_match_deleted_subtitles || subtitleInspectorInfo.value.manualMatchDeletedSubtitles,
      queue_message: matchedItem?.queue_message || subtitleInspectorInfo.value.manualMatchMessage
    }, { force: true })
  }
}

function isTextInputElement (target) {
  if (!target) return false
  const tagName = String(target.tagName || '').toUpperCase()
  return tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT' || target.isContentEditable
}

function getSubtitleInspectorSelectableIds () {
  return subtitleInspectorSelectableRows.value.map(row => row.id)
}

function selectSubtitleInspectorRange (targetId, preserveExisting = true) {
  const rowIds = getSubtitleInspectorSelectableIds()
  const targetIndex = rowIds.indexOf(targetId)
  if (targetIndex < 0) return
  const anchorId = subtitleInspectorLastSelectedId.value && rowIds.includes(subtitleInspectorLastSelectedId.value)
    ? subtitleInspectorLastSelectedId.value
    : targetId
  const anchorIndex = rowIds.indexOf(anchorId)
  const [start, end] = anchorIndex <= targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex]
  const next = preserveExisting ? new Set(subtitleInspectorSelectedIds.value) : new Set()
  rowIds.slice(start, end + 1).forEach(id => next.add(id))
  subtitleInspectorSelectedIds.value = next
  subtitleInspectorLastSelectedId.value = targetId
}

function toggleSubtitleInspectorSelect (row, event = null) {
  if (subtitleInspectorBusy.value) return
  if (!row?.id) return
  if (event?.shiftKey) {
    selectSubtitleInspectorRange(row.id, true)
    return
  }
  const next = new Set(subtitleInspectorSelectedIds.value)
  next.has(row.id) ? next.delete(row.id) : next.add(row.id)
  subtitleInspectorSelectedIds.value = next
  subtitleInspectorLastSelectedId.value = row.id
}

function toggleAllSubtitleInspectorRows (event) {
  if (subtitleInspectorBusy.value) return
  const checked = !subtitleInspectorAllSelected.value
  subtitleInspectorSelectedIds.value = checked
    ? new Set(subtitleInspectorSelectableRows.value.map(row => row.id))
    : new Set()
  subtitleInspectorLastSelectedId.value = checked ? subtitleInspectorSelectableRows.value.at(-1)?.id || '' : ''
}

function clearSubtitleInspectorSelection () {
  if (subtitleInspectorBusy.value) return
  subtitleInspectorSelectedIds.value = new Set()
  subtitleInspectorLastSelectedId.value = ''
}

function handleSubtitleInspectorRowClick (row, event) {
  if (subtitleInspectorBusy.value) return
  if (!row?.id) return
  toggleSubtitleInspectorSelect(row, event)
}

function handleSubtitleDialogKeydown (event) {
  if (isTextInputElement(event.target)) return

  const key = String(event.key || '').toLowerCase()
  if ((event.ctrlKey || event.metaKey) && key === 'a') {
    event.preventDefault()
    if (!subtitleDialogVisible.value || !subtitleInspectorInfo.value.subtitleDir || subtitleInspectorBusy.value) return
    subtitleInspectorSelectedIds.value = new Set(getSubtitleInspectorSelectableIds())
    subtitleInspectorLastSelectedId.value = subtitleInspectorSelectableRows.value.at(-1)?.id || ''
  }
}

async function batchDeleteSubtitleTreeEntries () {
  const rows = [...subtitleInspectorSelectedRows.value]
  if (!rows.length) {
    ElMessage.warning('请先选择要删除的字幕文件或目录')
    return
  }
  const sortedRows = rows.sort((left, right) => (right.path || right.relative_path || '').length - (left.path || left.relative_path || '').length)
  try {
    await showSystemConfirm({
      title: '批量删除确认',
      message: `确定批量删除 ${sortedRows.length} 项字幕文件/目录吗？此操作不可恢复。`,
      tone: 'danger',
      confirmText: '确定删除',
      cancelText: '取消'
    })
  } catch (_) {
    return
  }

  subtitleInspectorDeleting.value = true
  try {
    const batchId = `subtitle-delete-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    for (const row of sortedRows) {
      const path = resolveSubtitleEntryPath(row)
      await libraryApi.browserDelete(
        subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value,
        path,
        true,
        { batchId }
      )
    }

    clearSubtitleInspectorSelection()
    ElMessage.success(`已删除 ${sortedRows.length} 项`)
    await Promise.all([reloadSubtitleInspector(), refreshLibrary({ silent: true }), refreshRJSubtitleStatus(false)])
  } catch (error) {
    ElMessage.error(`删除失败: ${decodePossibleMojibake(error.response?.data?.detail || error.message)}`)
  } finally {
    subtitleInspectorDeleting.value = false
  }
}

function onSubtitleInspectorSearchInput () {
  if (subtitleInspectorSearch.value.trim()) expandSubtitleInspectorTree()
}

function toggleSubtitleInspectorExpand (node) {
  const next = new Set(subtitleInspectorExpandedIds.value)
  next.has(node.id) ? next.delete(node.id) : next.add(node.id)
  subtitleInspectorExpandedIds.value = next
}

function expandSubtitleInspectorTree () {
  const next = new Set()
  const walk = nodes => nodes.forEach(node => { if (node.type === 'dir') { next.add(node.id); walk(node.children || []) } })
  walk(subtitleInspectorFilteredRoot.value)
  subtitleInspectorExpandedIds.value = next
}

function collapseSubtitleInspectorTree () {
  subtitleInspectorExpandedIds.value = new Set()
}

function resolveSubtitleTreeIcon (row) {
  if (row?.type === 'dir') {
    return subtitleInspectorExpandedIds.value.has(row.id) ? FolderOpened : Folder
  }
  return fileIcon(row?.name || '')
}

function openSubtitleRenameDialog (row) {
  if (row?.type !== 'file') return
  subtitleRenameForm.value = { currentName: row.name, newName: row.name, path: row.path }
  subtitleRenameDialogVisible.value = true
}

async function confirmSubtitleRename () {
  if (!subtitleRenameForm.value.newName || subtitleRenameForm.value.newName === subtitleRenameForm.value.currentName) {
    ElMessage.warning('请输入不同的新名称')
    return
  }

  subtitleRenameLoading.value = true
  try {
    await libraryApi.browserRename(subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value, subtitleRenameForm.value.path, subtitleRenameForm.value.newName)
    subtitleRenameDialogVisible.value = false
    ElMessage.success('字幕文件重命名成功')
    await Promise.all([reloadSubtitleInspector(), refreshLibrary({ silent: true })])
  } catch (error) {
    ElMessage.error('重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    subtitleRenameLoading.value = false
  }
}

function resolveSubtitleEntryPath (row) {
  const rowPath = String(row?.path || '').replace(/\\/g, '/')
  const subtitleDir = String(subtitleInspectorInfo.value.subtitleDir || '').replace(/\\/g, '/')
  if (rowPath && subtitleDir && rowPath.startsWith(subtitleDir)) return row.path
  return joinFolderPath(
    subtitleInspectorInfo.value.subtitleDir,
    row.relative_path || row.name || ''
  )
}

async function deleteSubtitleTreeEntry (row) {
  if (subtitleInspectorBusy.value) return
  const path = resolveSubtitleEntryPath(row)
  const inspectorLibraryId = subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value
  try {
    const preview = await libraryApi.browserDelete(inspectorLibraryId, path, false)
    await showSystemConfirm({
      title: '删除确认',
      message: buildDeletePreviewMessage(preview),
      tone: 'danger',
      confirmText: '确定删除',
      cancelText: '取消'
    })
    subtitleInspectorDeleting.value = true
    try {
      await libraryApi.browserDelete(inspectorLibraryId, path, true)
      ElMessage.success('删除成功')
      await Promise.all([
        reloadSubtitleInspector(),
        refreshLibrary({ silent: true }),
        refreshRJSubtitleStatus(false),
        refreshStatsAfterMutation({
          deletedBytes: preview.size || 0,
          deletedFolderCount: preview.folder_count || 0,
          libraryId: inspectorLibraryId
        })
      ])
    } finally {
      subtitleInspectorDeleting.value = false
    }
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

function buildDeletePreviewMessage (preview) {
  if (preview?.size_disabled) {
    return `确定删除 ${preview?.name || '该项'} 吗？\n\n此操作不可恢复！`
  }
  return `确定删除 ${preview?.name || '该项'} 吗？\n大小: ${formatFileSize(preview?.size)}\n\n此操作不可恢复！`
}

function buildDeleteItemMessage (preview) {
  const targetLabel = preview?.type === 'folder' ? '文件夹' : '文件'
  if (preview?.size_disabled) {
    return `确定删除此${targetLabel}吗？\n名称: ${preview?.name || '-'}\n\n此操作不可恢复！`
  }
  return `确定删除此${targetLabel}吗？\n名称: ${preview?.name || '-'}\n大小: ${formatFileSize(preview?.size)}\n\n此操作不可恢复！`
}

function buildBatchDeletePreviewMessage (preview, count) {
  const totalCount = preview?.total_count || count
  if (preview?.size_disabled) {
    return `确定删除 ${totalCount} 项吗？\n\n此操作不可恢复！`
  }
  return `确定删除 ${totalCount} 项？总大小: ${formatFileSize(preview?.total_size || 0)}\n\n此操作不可恢复！`
}

function renameItem (row) {
  renameForm.value = {
    currentName: row.name,
    newName: row.name,
    path: row.path,
    libraryId: row.library_id || selectedLibraryId.value
  }
  renameDialogVisible.value = true
}

async function confirmRename () {
  if (!renameForm.value.newName || renameForm.value.newName === renameForm.value.currentName) {
    ElMessage.warning('请输入不同的新名称')
    return
  }
  isRenaming.value = true
  try {
    await libraryApi.browserRename(renameForm.value.libraryId || selectedLibraryId.value, renameForm.value.path, renameForm.value.newName)
    renameDialogVisible.value = false
    ElMessage.success('重命名成功')
    await Promise.all([
      refreshLibrary(),
      isRemoteCurrentLibrary.value ? Promise.resolve() : refreshStats(true, { refreshLibraryId: selectedLibraryId.value })
    ])
  } catch (error) {
    ElMessage.error('重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    isRenaming.value = false
  }
}

async function apiRenameItem (row) {
  if (apiRenameBusy.value) return
  try {
    await showSystemConfirm({
      title: 'API重命名确认',
      badge: '单项',
      message: '重新获取 DLsite 元数据，并按最新结果重命名当前作品。',
      currentLabel: '当前目录',
      currentValue: row.name,
      confirmText: '确认重命名'
    })
  } catch (_) { return }
  apiRenamingId.value = row.id
  try {
    const data = await libraryApi.apiRename(row.path, selectedLibraryId.value)
    ElMessage.success(data.message || 'API 重命名成功')
    await Promise.all([
      refreshLibrary(),
      isRemoteCurrentLibrary.value ? Promise.resolve() : refreshStats(true, { refreshLibraryId: selectedLibraryId.value })
    ])
  } catch (error) {
    ElMessage.error('API重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    apiRenamingId.value = null
  }
}

async function deleteItem (row) {
  try {
    const preview = await libraryApi.browserDelete(selectedLibraryId.value, row.path, false)
    await showSystemConfirm({
      title: '删除确认',
      message: buildDeleteItemMessage(preview),
      tone: 'danger',
      confirmText: '确定删除',
      cancelText: '取消'
    })
    await libraryApi.browserDelete(selectedLibraryId.value, row.path, true)
    ElMessage.success('删除成功')
    await Promise.all([
      refreshLibrary(),
      refreshStatsAfterMutation({
        deletedBytes: preview.size || 0,
        deletedFolderCount: preview.folder_count || 0,
        libraryId: selectedLibraryId.value
      })
    ])
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
  }
}

async function handleBatchDelete () {
  if (!selectedRows.value.length) return
  batchDeleting.value = true
  try {
    const paths = selectedRows.value.map(row => row.path)
    const preview = await libraryApi.browserBatchDelete(selectedLibraryId.value, paths, false)
    await showSystemConfirm({
      title: '批量删除确认',
      message: buildBatchDeletePreviewMessage(preview, paths.length),
      tone: 'danger',
      confirmText: '确定删除',
      cancelText: '取消'
    })
    const result = await libraryApi.browserBatchDelete(selectedLibraryId.value, paths, true)
    ElMessage.success(`批量删除完成：成功 ${result.success_count || 0} 项`)
    clearSelection()
    await Promise.all([
      refreshLibrary(),
      refreshStatsAfterMutation({
        deletedBytes: preview.total_size || 0,
        deletedFolderCount: preview.total_folder_count || 0,
        libraryId: selectedLibraryId.value
      })
    ])
  } catch (error) {
    if (error === 'cancel' || error?.message === 'cancel') return
    ElMessage.error('批量删除失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    batchDeleting.value = false
  }
}

async function handleBatchApiRename () {
  if (!selectedApiRenameRows.value.length || apiRenameBusy.value) return
  const targetRows = selectedApiRenameRows.value
  const skippedCount = selectedRows.value.length - targetRows.length
  try {
    await showSystemConfirm({
      title: '批量 API重命名确认',
      badge: `${targetRows.length} 项`,
      message: skippedCount > 0
        ? `将对已选 ${targetRows.length} 个目录执行批量 API 重命名，并跳过 ${skippedCount} 个非目录项。`
        : `将对已选 ${targetRows.length} 个目录执行批量 API 重命名。`,
      currentLabel: '执行范围',
      currentValue: targetRows.map(row => row.name).slice(0, 3).join(' / ') + (targetRows.length > 3 ? ` 等 ${targetRows.length} 项` : ''),
      confirmText: '确认批量重命名'
    })
  } catch (_) {
    return
  }
  batchRenaming.value = true
  batchApiRenameTargetIds.value = new Set(targetRows.map(row => row.id))
  batchApiRenameRunningIds.value = new Set()
  try {
    const concurrency = Math.min(4, Math.max(1, targetRows.length))
    const results = []
    let cursor = 0
    const runNext = async () => {
      while (cursor < targetRows.length) {
        const currentIndex = cursor
        cursor += 1
        const row = targetRows[currentIndex]
        batchApiRenameRunningIds.value = new Set([...batchApiRenameRunningIds.value, row.id])
        try {
          const data = await libraryApi.apiRename(row.path, selectedLibraryId.value)
          results.push({ path: row.path, success: true, message: data.message || 'API 重命名成功' })
        } catch (error) {
          results.push({ path: row.path, success: false, error: error.response?.data?.detail || error.message })
        } finally {
          const nextRunning = new Set(batchApiRenameRunningIds.value)
          nextRunning.delete(row.id)
          batchApiRenameRunningIds.value = nextRunning
        }
      }
    }
    await Promise.all(Array.from({ length: concurrency }, () => runNext()))
    const successCount = results.filter(item => item.success).length
    const failed = results.filter(item => !item.success)
    clearSelection()
    if (failed.length) {
      const firstError = failed[0]?.error ? `，首个失败：${failed[0].error}` : ''
      ElMessage.warning(`批量 API重命名完成：成功 ${successCount}，失败 ${failed.length}${firstError}`)
    } else {
      ElMessage.success(`批量 API重命名完成：成功 ${successCount} 项`)
    }
    await Promise.all([
      refreshLibrary(),
      isRemoteCurrentLibrary.value ? Promise.resolve() : refreshStats(true, { refreshLibraryId: selectedLibraryId.value })
    ])
  } catch (error) {
    ElMessage.error('批量 API重命名失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    batchApiRenameTargetIds.value = new Set()
    batchApiRenameRunningIds.value = new Set()
    apiRenamingId.value = null
    batchRenaming.value = false
  }
}

function isLibraryRowSelectable () {
  return !apiRenameBusy.value
}

async function openFolderContentsDialog (row) {
  if (!row?.is_directory) return
  folderDialogLibraryId.value = row.library_id || selectedLibraryId.value
  folderDialogPath.value = row.path
  folderDialogName.value = row.name
  folderDialogVisible.value = true
}

async function handleFolderDialogMutated ({ deletedBytes = 0, deletedFolderCount = 0 } = {}) {
  await Promise.all([
    refreshLibrary({ silent: true }),
    refreshStatsAfterMutation({
      deletedBytes,
      deletedFolderCount,
      libraryId: folderDialogLibraryId.value || selectedLibraryId.value
    })
  ])
}

function joinFolderPath (basePath, relativePath) {
  if (!relativePath) return basePath
  return `${basePath.replace(/[\\/]+$/, '')}/${relativePath.replace(/^[/\\]+/, '')}`
}

function buildTree (items) {
  const root = []
  const dirMap = new Map()
  const sorted = [...items].sort((a, b) => (a.relative_path || '').localeCompare(b.relative_path || ''))
  for (const item of sorted) {
    const parts = (item.relative_path || item.name).split('/').filter(Boolean)
    let children = root
    let path = ''
    for (let index = 0; index < parts.length - 1; index++) {
      path = path ? `${path}/${parts[index]}` : parts[index]
      const key = `dir:${path}`
      if (!dirMap.has(key)) {
        const node = { id: key, name: parts[index], type: 'dir', relative_path: path, size: 0, modified_time: null, children: [] }
        dirMap.set(key, node)
        children.push(node)
      }
      children = dirMap.get(key).children
    }
    children.push({ ...item, id: `file:${item.path}`, type: 'file' })
  }
  const walk = node => {
    let total = 0
    let latest = null
    for (const child of node.children || []) {
      if (child.type === 'dir') walk(child)
      total += child.size || 0
      if (child.modified_time && (!latest || child.modified_time > latest)) latest = child.modified_time
    }
    node.size = total
    node.modified_time = latest
  }
  root.forEach(node => { if (node.type === 'dir') walk(node) })
  return root
}

function filterTree (nodes, keyword) {
  const result = []
  for (const node of nodes) {
    const matched = (node.name || '').toLowerCase().includes(keyword) || (node.relative_path || '').toLowerCase().includes(keyword)
    if (node.type === 'file') {
      if (matched) result.push(node)
      continue
    }
    const children = filterTree(node.children || [], keyword)
    if (matched || children.length) result.push({ ...node, children })
  }
  return result
}

function flattenTree (nodes, depth, openIds) {
  const result = []
  for (const node of nodes) {
    result.push({ ...node, depth })
    if (node.type === 'dir' && openIds.has(node.id) && node.children?.length) result.push(...flattenTree(node.children, depth + 1, openIds))
  }
  return result
}

async function openFilterDeleteDialog () {
  if (filterDeleteBackgroundState.value.active) {
    filterDeleteDialogVisible.value = true
    return
  }
  if (!currentPath.value || !isWritableCurrentLibrary.value) return
  filterDeleteDialogLibraryId.value = selectedLibraryId.value
  filterDeleteDialogPath.value = currentPath.value
  filterDeleteDialogTargetPaths.value = [...toolbarFilterDeletePaths.value]
  filterDeleteDialogRules.value = await loadConfiguredFilterRules()
  filterDeleteDialogScopeLabel.value = toolbarActionScopeLabel.value
  filterDeleteDialogIsRemote.value = isRemoteCurrentLibrary.value
  filterDeleteDialogVisible.value = true
}

async function openSelectedFilterDeleteDialog () {
  if (filterDeleteBackgroundState.value.active) {
    filterDeleteDialogVisible.value = true
    return
  }
  const targetRows = selectedFilterDeleteRows.value
  if (!targetRows.length || !selectedLibraryId.value) return
  const skippedCount = selectedRows.value.length - targetRows.length
  if (skippedCount > 0) {
    ElMessage.warning(`已跳过 ${skippedCount} 个非目录项，删除过滤预审只支持目录`)
  }
  filterDeleteDialogLibraryId.value = selectedLibraryId.value
  filterDeleteDialogPath.value = currentPath.value
  filterDeleteDialogTargetPaths.value = [...new Set(targetRows.map(resolveDirectoryActionPath).filter(Boolean))]
  filterDeleteDialogRules.value = await loadConfiguredFilterRules()
  filterDeleteDialogScopeLabel.value = `已选目录（${filterDeleteDialogTargetPaths.value.length} 项）`
  filterDeleteDialogIsRemote.value = isRemoteCurrentLibrary.value
  filterDeleteDialogVisible.value = true
}

async function openSubtitleInspectorFilterDeleteDialog () {
  if (filterDeleteBackgroundState.value.active) {
    filterDeleteDialogVisible.value = true
    return
  }
  const libraryId = subtitleInspectorInfo.value.subtitleLibraryId || subtitleInspectorInfo.value.libraryId || selectedLibraryId.value
  const folderPath = String(subtitleInspectorInfo.value.folderPath || '').trim()
  const subtitleDir = String(subtitleInspectorInfo.value.subtitleDir || '').trim()
  const targetPath = folderPath || subtitleDir
  if (!libraryId || !targetPath) return
  const library = libraries.value.find(item => item.id === libraryId) || null
  filterDeleteDialogLibraryId.value = libraryId
  filterDeleteDialogPath.value = targetPath
  filterDeleteDialogTargetPaths.value = [targetPath]
  filterDeleteDialogRules.value = subtitleOptions.value.useFilterRules ? sanitizeSubtitleFilterRules(subtitleOptions.value.subtitleFilterRules || []) : []
  filterDeleteDialogScopeLabel.value = `${getTaskDisplayRJCode(activeSubtitleInspectTask.value) || getFileName(targetPath) || '当前任务'} RJ 目录`
  filterDeleteDialogIsRemote.value = library?.type === 'synology_filestation'
  filterDeleteDialogVisible.value = true
}

async function handleFilterDeleteDeleted ({ deletedBytes = 0, deletedFolderCount = 0 } = {}) {
  await Promise.all([
    refreshLibrary({ silent: true }),
    folderDialogVisible.value && folderDialogRef.value?.reload ? folderDialogRef.value.reload() : Promise.resolve(),
    subtitleDialogVisible.value &&
    String(subtitleInspectorInfo.value.folderPath || subtitleInspectorInfo.value.subtitleDir || '').trim() &&
    filterDeleteDialogTargetPaths.value.includes(String(subtitleInspectorInfo.value.folderPath || subtitleInspectorInfo.value.subtitleDir || '').trim())
      ? reloadSubtitleInspector()
      : Promise.resolve(),
    refreshStatsAfterMutation({
      deletedBytes,
      deletedFolderCount,
      libraryId: filterDeleteDialogLibraryId.value || selectedLibraryId.value
    })
  ])
}

function handleFilterDeleteDialogStateChange (state = {}) {
  const status = state.status || 'idle'
  const startedAt = Number(state.startedAt || 0)
  const nextHasBackground = Boolean(state.active) || Boolean(state.reviewable)
  const prevHasBackground = Boolean(filterDeleteBackgroundState.value.active) || Boolean(filterDeleteBackgroundState.value.reviewable)
  const nextSessionKey = nextHasBackground
    ? [
        state.mode || 'preview',
        startedAt,
        state.scopeLabel || '',
        filterDeleteDialogLibraryId.value || '',
        filterDeleteDialogPath.value || ''
      ].join('::')
    : ''
  if (nextHasBackground) {
    if (!prevHasBackground || nextSessionKey !== filterDeleteBackgroundSessionKey.value) {
      filterDeleteBackgroundDismissed.value = false
    }
    filterDeleteBackgroundSessionKey.value = nextSessionKey
  } else {
    filterDeleteBackgroundSessionKey.value = ''
  }
  filterDeleteBackgroundState.value = {
    active: Boolean(state.active),
    mode: state.mode || 'preview',
    status,
    statusLabel: (
      status === 'pending' ? '等待中'
        : status === 'running' ? '执行中'
          : status === 'completed' ? '已完成'
            : status === 'canceled' ? '已取消'
              : status === 'error' ? '失败'
                : '空闲'
    ),
    scopeLabel: state.scopeLabel || '',
    progressMessage: state.progressMessage || '',
    currentPath: state.currentPath || '',
    percentage: Number(state.percentage || 0),
    progressStatus: state.progressStatus || '',
    startedAt,
    startedAtText: startedAt ? formatDate(startedAt) : '',
    previewTargetIndex: Number(state.previewTargetIndex || 0),
    previewTargetTotal: Number(state.previewTargetTotal || 0),
    reviewable: Boolean(state.reviewable),
    selectedCount: Number(state.selectedCount || 0),
    selectedSize: Number(state.selectedSize || 0),
    selectedSizeText: formatFileSize(Number(state.selectedSize || 0)),
    scannedEntries: Number(state.scannedEntries || 0),
    discoveredEntries: Number(state.discoveredEntries || 0),
    pendingDirectories: Number(state.pendingDirectories || 0),
    ruleCount: Number(state.ruleCount || 0),
    deleteDone: Number(state.deleteDone || 0),
    deleteTotal: Number(state.deleteTotal || 0),
    deleteFailed: Number(state.deleteFailed || 0),
    canCancelPreview: Boolean(state.canCancelPreview),
    canStopDelete: Boolean(state.canStopDelete)
  }
  if (filterDeleteBackgroundState.value.active) {
    filterDeleteBackgroundNow.value = Date.now()
    if (!filterDeleteBackgroundTimer) {
      filterDeleteBackgroundTimer = window.setInterval(() => {
        filterDeleteBackgroundNow.value = Date.now()
      }, 1000)
    }
  } else if (filterDeleteBackgroundTimer) {
    clearInterval(filterDeleteBackgroundTimer)
    filterDeleteBackgroundTimer = null
  }
}

function resumeFilterDeleteDialog () {
  filterDeleteBackgroundDismissed.value = false
  filterDeleteDialogVisible.value = true
}

function handleFilterDeleteDialogDismissBackground () {
  filterDeleteBackgroundDismissed.value = true
}

function dismissFilterDeleteBackgroundCard () {
  filterDeleteBackgroundDismissed.value = true
}

async function cancelBackgroundFilterDeletePreview () {
  try {
    await filterDeleteDialogRef.value?.cancelPreviewTask?.()
  } catch (_) {}
}

function stopBackgroundFilterDelete () {
  filterDeleteDialogRef.value?.requestStopDeletion?.()
}

function fileIcon (name = '') {
  const lower = name.toLowerCase()
  if (/\.(wav|flac|mp3|m4a|aac|ogg|opus|cue)$/i.test(lower)) return Headset
  if (/\.(png|jpg|jpeg|webp|bmp|gif)$/i.test(lower)) return Picture
  if (/\.(mp4|mkv|avi|mov|wmv|webm)$/i.test(lower)) return VideoPlay
  if (/\.(lrc|srt|ass|ssa|vtt)$/i.test(lower)) return Tickets
  return Document
}

function formatFileSize (bytes) {
  if (bytes === null || bytes === undefined) return '-'
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** index)).toFixed(2)} ${units[index]}`
}

function libraryRowKey (row) {
  return [
    selectedLibraryId.value || 'default',
    row?.path || row?.id || row?.name || 'unknown'
  ].join('::')
}

function libraryRowClassName ({ row }) {
  if (locatedLibraryPath.value && row?.path === locatedLibraryPath.value) return 'library-row-located'
  return ''
}

function formatRowSize (row) {
  if (isRemoteCurrentLibrary.value && row?.is_directory) return '-'
  if (row?.size_status === 'pending' && (row.size === null || row.size === undefined)) return '统计中'
  if (row?.size_status === 'stale' && row.size !== null && row.size !== undefined) return `${formatFileSize(row.size)} *`
  return formatFileSize(row?.size)
}

function formatDate (value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatGB (value) {
  if (value === null || value === undefined) return '统计中'
  const sizeInGb = Number(value)
  if (sizeInGb > 1000) return `${(sizeInGb / 1000).toFixed(2)} TB`
  return `${sizeInGb.toFixed(2)} GB`
}

function statsSizeText (stats) {
  if (!stats || stats.status === 'pending') return '统计更新中'
  if (stats.status === 'unsupported') return '暂不支持远程容量统计'
  return formatGB(stats.total_size_gb)
}

function statsStatusText (status) {
  if (status === 'ready') return '统计已就绪'
  if (status === 'pending') return '后台正在更新'
  if (status === 'unsupported') return '当前仅显示健康状态'
  return '等待统计'
}

function statsSizeCardText (stats) {
  if (!stats) return '\u7b49\u5f85\u7edf\u8ba1'
  if (stats.status === 'pending') return '\u7edf\u8ba1\u66f4\u65b0\u4e2d'
  if (stats.status === 'idle') return '\u672a\u624b\u52a8\u7edf\u8ba1'
  if (stats.status === 'canceled') return '\u5df2\u53d6\u6d88\uff0c\u4fdd\u7559\u5f53\u524d\u8fdb\u5ea6'
  if (stats.status === 'error') return '\u7edf\u8ba1\u4e2d\u65ad\uff0c\u4fdd\u7559\u5df2\u5b8c\u6210\u6570\u636e'
  if (stats.status === 'unsupported') return '\u6682\u4e0d\u652f\u6301\u5f53\u524d\u7edf\u8ba1'
  return formatGB(stats.total_size_gb)
}

function statsStatusCardText (stats) {
  const status = stats?.status
  if (status === 'ready') {
    const ts = stats?.last_completed_at || stats?.updated_at
    return ts ? `\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : '\u7edf\u8ba1\u5df2\u5b8c\u6210'
  }
  if (status === 'pending') {
    const ts = stats?.last_completed_at
    return ts ? `\u540e\u53f0\u66f4\u65b0\u4e2d\uff0c\u6700\u8fd1\u7edf\u8ba1\u4e8e ${formatDate(ts * 1000)}` : '\u540e\u53f0\u6b63\u5728\u66f4\u65b0'
  }
  if (status === 'canceled') return '\u5df2\u624b\u52a8\u53d6\u6d88\uff0c\u4ecd\u4fdd\u7559\u5df2\u7edf\u8ba1\u8fdb\u5ea6'
  if (status === 'error') return stats?.last_error || '\u7edf\u8ba1\u4e2d\u9014\u51fa\u73b0\u5f02\u5e38\uff0c\u8bf7\u67e5\u770b\u8fdc\u7a0b\u7edf\u8ba1\u65e5\u5fd7'
  if (status === 'idle') return '\u8fdc\u7a0b\u5e93\u9ed8\u8ba4\u4e0d\u81ea\u52a8\u5168\u91cf\u7edf\u8ba1\uff0c\u8bf7\u624b\u52a8\u70b9\u5237\u65b0\u7edf\u8ba1'
  if (status === 'unsupported') return '\u5f53\u524d\u4ec5\u663e\u793a\u5065\u5eb7\u72b6\u6001'
  return '\u7b49\u5f85\u7edf\u8ba1'
}

function healthStatusLabel (status) {
  if (status === 'healthy') return '\u5065\u5eb7'
  if (status === 'warning') return '\u9884\u8b66'
  return '\u5f02\u5e38'
}

function healthDetailText (health) {
  if (!health) return ''
  if (health.errors?.length) return health.errors.map(item => decodePossibleMojibake(item)).join('\uff1b')
  if (health.warnings?.length) return health.warnings.map(item => decodePossibleMojibake(item)).join('\uff1b')
  if (health.free_space_gb !== null && health.free_space_gb !== undefined) return `\u5269\u4f59\u7a7a\u95f4 ${health.free_space_gb} GB`
  return '\u8bfb\u5199\u6743\u9650\u6b63\u5e38'
}

function healthTagType (status) {
  if (status === 'healthy') return 'success'
  if (status === 'warning') return 'warning'
  return 'danger'
}

function healthText (status) {
  if (status === 'healthy') return '健康'
  if (status === 'warning') return '预警'
  return '异常'
}

function healthDetail (health) {
  if (!health) return ''
  if (health.errors?.length) return health.errors.map(item => decodePossibleMojibake(item)).join('；')
  if (health.warnings?.length) return health.warnings.map(item => decodePossibleMojibake(item)).join('；')
  if (health.free_space_gb !== null && health.free_space_gb !== undefined) return `剩余空间 ${health.free_space_gb} GB`
  return '读写权限正常'
}
function statsSizeLabel (stats) {
  if (!stats || stats.status === 'pending') return '统计更新中'
  if (stats.status === 'idle') return '未统计'
  if (stats.status === 'unsupported') return '暂不支持远程容量统计'
  return formatGB(stats.total_size_gb)
}

function statsStatusLabel (stats) {
  const status = stats?.status
  if (status === 'ready') {
    const ts = stats?.last_completed_at || stats?.updated_at
    return ts ? `统计于 ${formatDate(ts * 1000)}` : '统计已就绪'
  }
  if (status === 'pending') {
    const ts = stats?.last_completed_at
    return ts ? `后台更新中，上次统计于 ${formatDate(ts * 1000)}` : '后台正在更新'
  }
  if (status === 'idle') return '未手动统计，沿用已保存结果'
  if (status === 'unsupported') return '当前仅显示健康状态'
  return '等待统计'
}

function statsSizeTextDisplay (stats) {
  if (!stats || stats.status === 'pending') return '统计更新中'
  if (stats.status === 'idle') return '未统计'
  if (stats.status === 'unsupported') return '暂不支持远程容量统计'
  return formatGB(stats.total_size_gb)
}

function statsStatusTextDisplay (stats) {
  const status = stats?.status
  if (status === 'ready') {
    const ts = stats?.last_completed_at || stats?.updated_at
    return ts ? `统计于 ${formatDate(ts * 1000)}` : '统计已就绪'
  }
  if (status === 'pending') {
    const ts = stats?.last_completed_at
    return ts ? `后台更新中，上次统计于 ${formatDate(ts * 1000)}` : '后台正在更新'
  }
  if (status === 'idle') return '未手动统计，沿用已保存结果'
  if (status === 'unsupported') return '当前仅显示健康状态'
  return '等待统计'
}
</script>

<style scoped>
.library-page-loading-shell {
  position: relative;
  min-height: 100vh;
}

:deep(.library-page-loading-mask) {
  inset: 0;
  border-radius: 0;
  background: rgba(250, 251, 255, 0.84);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
  z-index: 50;
}

.library {
  max-width: 1480px;
  margin: 0 auto;
  padding: 16px;
  color: #1d1d1f;
  font-family: "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
}

.page-title {
  margin: 0 0 18px;
  font-size: 29px;
  font-weight: 600;
  line-height: 1.12;
  letter-spacing: -0.2px;
  color: #1d1d1f;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.summary-card {
  min-height: 160px;
  border: none;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 12px 30px rgba(0, 0, 0, .05);
}

.summary-card :deep(.el-card__header) {
  padding: 18px 18px 0;
  border-bottom: none;
  font-size: 12px;
  font-weight: 600;
  color: rgba(29, 29, 31, .52);
}

.summary-card :deep(.el-card__body) {
  padding: 14px 18px 18px;
}

.summary-value {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.18;
  letter-spacing: -0.16px;
  color: #1d1d1f;
}

.summary-meta,
.summary-caption {
  margin-top: 8px;
  font-size: 13px;
}

.summary-meta {
  color: rgba(29, 29, 31, .66);
}

.summary-caption {
  color: rgba(29, 29, 31, .5);
  line-height: 1.58;
}

.summary-progress { margin-top: 10px; }

.path-text { word-break: break-all; }
.summary-tags { display: flex; gap: 8px; margin-top: 12px; }
.main-card {
  border: none;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 12px 30px rgba(0, 0, 0, .05) !important;
}

.main-card :deep(.el-card__header) {
  padding: 18px 18px 0;
  border-bottom: none;
}

.main-card :deep(.el-card__body) {
  padding: 12px 18px 18px;
}

.card-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.header-title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: -0.08px;
  color: #1d1d1f;
  white-space: nowrap;
}
.header-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: flex-end; }
.toolbar-action-btn,
.toolbar-tight-btn { width: 88px; }

:deep(.el-input__wrapper),
:deep(.el-select__wrapper) {
  min-height: 34px;
  border-radius: 12px;
  background: #f5f5f7;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, .06);
}

:deep(.el-input__inner),
:deep(.el-select__selected-item),
:deep(.el-select__placeholder) {
  font-size: 12px;
  color: #1d1d1f;
}

:deep(.toolbar-action-btn.el-button),
:deep(.toolbar-tight-btn.el-button) {
  min-height: 34px;
  padding: 0 !important;
  border-radius: 999px;
  border-color: rgba(29, 29, 31, .08);
  background: #f5f5f7;
  color: #1d1d1f;
  box-shadow: none;
  --el-button-padding-horizontal: 0 !important;
  --el-button-padding-vertical: 0 !important;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background .18s ease, color .18s ease, border-color .18s ease, box-shadow .18s ease, transform .18s ease, opacity .18s ease;
}
:deep(.toolbar-action-btn.el-button > span),
:deep(.toolbar-tight-btn.el-button > span) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  padding: 0 !important;
}

.toolbar-refresh-content {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
}

.toolbar-refresh-icon,
.toolbar-refresh-label {
  transition: color .22s ease, opacity .22s ease, transform .22s ease;
}

.toolbar-refresh-icon {
  font-size: 13px;
  color: rgba(29, 29, 31, .56);
}

.toolbar-refresh-label {
  min-width: 36px;
  letter-spacing: .02em;
}

:deep(.toolbar-refresh-btn.el-button:hover .toolbar-refresh-icon) {
  color: #0071e3;
  transform: rotate(-18deg);
}

:deep(.toolbar-refresh-btn.el-button.is-refreshing),
:deep(.toolbar-refresh-btn.el-button.is-disabled.is-refreshing) {
  opacity: 1;
  cursor: default;
  color: #0b63ce;
  border-color: rgba(0, 113, 227, .16);
  background: linear-gradient(180deg, #f8fbff 0%, #edf4ff 100%);
}

:deep(.toolbar-refresh-btn.el-button.is-refreshing > span),
:deep(.toolbar-refresh-btn.el-button.is-disabled.is-refreshing > span) {
  opacity: 1;
}

:deep(.toolbar-refresh-btn.el-button.is-refreshing .toolbar-refresh-icon) {
  color: #0b63ce;
  animation: library-refresh-spin .95s cubic-bezier(.55, .08, .38, .96) infinite;
}

:deep(.toolbar-action-btn.el-button--primary:hover) {
  background: #0077ed;
  border-color: #0077ed;
  color: #fff;
}

:deep(.toolbar-action-btn.el-button--primary:active) {
  background: #0068d1;
  border-color: #0068d1;
}

:deep(.toolbar-action-btn.el-button--primary) {
  background: #0071e3;
  border-color: #0071e3;
  color: #fff;
}

@keyframes library-refresh-spin {
  0% { transform: rotate(0deg); }
  42% { transform: rotate(160deg); }
  58% { transform: rotate(210deg); }
  100% { transform: rotate(360deg); }
}

:deep(.el-switch__core) {
  border-color: rgba(29, 29, 31, .08);
  background: #e9e9ed;
}

:deep(.el-switch.is-checked .el-switch__core) {
  background: #0071e3;
  border-color: #0071e3;
}

.library-option { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.path-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
  padding: 10px 12px;
  background: #f5f5f7;
  border: none;
  border-radius: 16px;
}
.path-toolbar-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.path-toolbar-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.toolbar-scope-toggle {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-right: 4px;
  padding: 3px;
  border-radius: 999px;
  background: #f5f5f7;
  box-shadow:
    inset 0 0 0 1px rgba(29, 29, 31, .08),
    0 1px 2px rgba(0, 0, 0, .04);
}

.toolbar-scope-option {
  min-width: 72px;
  padding: 6px 14px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: rgba(29, 29, 31, .72);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  letter-spacing: -0.12px;
  cursor: pointer;
  -webkit-font-smoothing: antialiased;
  transition: background .18s ease, color .18s ease, box-shadow .18s ease, transform .18s ease, opacity .18s ease;
}

.toolbar-scope-option:hover {
  color: #1d1d1f;
  background: rgba(255, 255, 255, .78);
}

.toolbar-scope-option:focus-visible {
  outline: 2px solid #0071e3;
  outline-offset: 2px;
}

.toolbar-scope-option.is-active {
  background: #0071e3;
  color: #fff;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, .08),
    0 1px 3px rgba(0, 0, 0, .12);
}

.toolbar-scope-option.is-active:hover {
  background: #0077ed;
  color: #fff;
}

.toolbar-utility-btn,
.batch-action-btn {
  --apple-btn-bg: #fafafc;
  --apple-btn-bg-hover: #ffffff;
  --apple-btn-text: rgba(0, 0, 0, .8);
  --apple-btn-border: rgba(0, 0, 0, .06);
  --apple-btn-border-hover: rgba(0, 0, 0, .1);
  --apple-btn-shadow: rgba(0, 0, 0, .08) 0 1px 3px;
}

:deep(.toolbar-utility-btn.el-button),
:deep(.batch-action-btn.el-button) {
  min-height: 30px;
  padding: 0 14px !important;
  border-radius: 999px;
  border-color: transparent !important;
  background: var(--apple-btn-bg) !important;
  color: var(--apple-btn-text) !important;
  box-shadow:
    inset 0 0 0 1px var(--apple-btn-border),
    0 1px 2px rgba(0, 0, 0, .04);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: -0.12px;
  transition: background .18s ease, color .18s ease, box-shadow .18s ease, transform .18s ease;
}

:deep(.toolbar-utility-btn.el-button:hover),
:deep(.batch-action-btn.el-button:hover) {
  background: var(--apple-btn-bg-hover) !important;
  color: var(--apple-btn-text) !important;
  box-shadow:
    inset 0 0 0 1px var(--apple-btn-border-hover),
    var(--apple-btn-shadow);
  transform: translateY(-1px);
}

:deep(.toolbar-utility-btn.el-button:active),
:deep(.batch-action-btn.el-button:active) {
  transform: translateY(0);
  box-shadow:
    inset 0 0 0 1px var(--apple-btn-border-hover),
    0 1px 2px rgba(0, 0, 0, .04);
}

:deep(.toolbar-utility-btn.el-button:focus-visible),
:deep(.batch-action-btn.el-button:focus-visible) {
  outline: 2px solid #0071e3;
  outline-offset: 2px;
}

:deep(.toolbar-utility-btn.el-button > span),
:deep(.batch-action-btn.el-button > span) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

:deep(.toolbar-utility-btn.el-button .el-icon),
:deep(.batch-action-btn.el-button .el-icon) {
  font-size: 12px;
}

:deep(.toolbar-utility-btn.el-button.is-disabled),
:deep(.toolbar-utility-btn.el-button.is-disabled:hover),
:deep(.batch-action-btn.el-button.is-disabled),
:deep(.batch-action-btn.el-button.is-disabled:hover),
:deep(.batch-action-btn.el-button.is-loading),
:deep(.batch-action-btn.el-button.is-loading:hover) {
  transform: none;
  opacity: .64;
  box-shadow:
    inset 0 0 0 1px var(--apple-btn-border),
    0 1px 2px rgba(0, 0, 0, .03);
}

.toolbar-utility-btn-primary,
.batch-action-btn-primary {
  --apple-btn-bg: #0071e3;
  --apple-btn-bg-hover: #0077ed;
  --apple-btn-text: #fff;
  --apple-btn-border: rgba(255, 255, 255, .08);
  --apple-btn-border-hover: rgba(255, 255, 255, .12);
  --apple-btn-shadow: rgba(0, 113, 227, .24) 0 6px 16px;
}

.toolbar-utility-btn-danger,
.batch-action-btn-danger {
  --apple-btn-bg: #fff5f5;
  --apple-btn-bg-hover: #fff;
  --apple-btn-text: #d70015;
  --apple-btn-border: rgba(215, 0, 21, .2);
  --apple-btn-border-hover: rgba(215, 0, 21, .28);
  --apple-btn-shadow: rgba(215, 0, 21, .12) 0 6px 16px;
}

.toolbar-utility-btn-neutral,
.batch-action-btn-neutral {
  --apple-btn-bg: #fafafc;
  --apple-btn-bg-hover: #ffffff;
  --apple-btn-text: rgba(0, 0, 0, .8);
  --apple-btn-border: rgba(0, 0, 0, .06);
  --apple-btn-border-hover: rgba(0, 0, 0, .1);
  --apple-btn-shadow: rgba(0, 0, 0, .08) 0 6px 16px;
}

.path-label { font-size: 12px; color: rgba(29, 29, 31, .48); white-space: nowrap; }
.path-code {
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, .92);
  color: rgba(29, 29, 31, .7);
  font-size: 11px;
}

:deep(.path-toolbar .el-button--small) {
  min-height: 30px;
  border-radius: 999px;
  font-size: 12px;
}

:deep(.el-table) {
  --el-table-header-bg-color: #f5f5f7;
  --el-table-row-hover-bg-color: #fafafc;
  border-radius: 14px;
  overflow: hidden;
}

:deep(.el-table th.el-table__cell) {
  font-weight: 600;
  font-size: 12px;
  color: rgba(29, 29, 31, .54);
}

:deep(.el-table td.el-table__cell) {
  border-bottom-color: rgba(29, 29, 31, .06);
}

.file-cell { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.file-main-line { display: flex; align-items: center; gap: 6px; min-width: 0; }
.file-icon { margin-right: 6px; color: #0071e3; vertical-align: middle; }
.file-name { vertical-align: middle; font-weight: 500; color: #1d1d1f; }
.file-link-btn { padding: 0; border: none; background: transparent; color: #1d1d1f; font: inherit; font-weight: 500; cursor: pointer; }
.file-link-btn:hover { color: #0066cc; }
.search-result-library { padding-left: 22px; font-size: 11px; line-height: 1.4; color: #7a8ba5; }
:deep(.library-search-mark) { background: #fff1a8; color: #7a4b00; padding: 0 2px; border-radius: 4px; }
:deep(.el-table .library-row-located > td.el-table__cell) { background: #eef7ff !important; }
.empty-text { color: #c0c4cc; }
.action-grid { display: inline-flex; flex-direction: column; gap: 4px; align-items: center; width: 100%; min-width: 0; }
.action-row { display: flex; gap: 4px; width: 100%; max-width: 228px; min-width: 0; }
.action-btn {
  --action-btn-bg: #fafafc;
  --action-btn-bg-hover: #ffffff;
  --action-btn-text: rgba(0, 0, 0, .8);
  --action-btn-border: rgba(0, 0, 0, .06);
  --action-btn-border-hover: rgba(0, 0, 0, .1);
  --action-btn-hover-shadow: rgba(0, 0, 0, .08) 0 6px 16px;
  flex: 1 1 0;
  margin: 0 !important;
  min-width: 0;
  border-radius: 999px;
  border-color: transparent !important;
  font-size: 12px;
  font-weight: 500;
  padding: 5px 0;
  background: var(--action-btn-bg) !important;
  color: var(--action-btn-text) !important;
  letter-spacing: -0.12px;
  box-shadow: inset 0 0 0 1px var(--action-btn-border);
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease, background .18s ease, color .18s ease;
}

.action-btn:hover {
  transform: translateY(-1px);
  background: var(--action-btn-bg-hover) !important;
  color: var(--action-btn-text) !important;
  box-shadow:
    inset 0 0 0 1px var(--action-btn-border-hover),
    var(--action-btn-hover-shadow);
}
.action-btn.is-loading,
.action-btn.is-loading:hover {
  transform: none;
  box-shadow: inset 0 0 0 1px var(--action-btn-border);
  cursor: wait;
}
.action-btn.is-loading :deep(.el-icon),
.action-btn.is-loading :deep(.el-icon svg) {
  color: currentColor !important;
}
:deep(.action-btn.el-button.is-loading),
:deep(.action-btn.el-button.is-disabled) {
  opacity: .66;
}
:deep(.action-btn.el-button.is-loading > span),
:deep(.action-btn.el-button.is-disabled > span) {
  opacity: .95;
}
.action-btn-open,
.action-btn-direct,
.action-btn-rename,
.action-btn-api,
.action-btn-manage {
  --action-btn-bg: #fafafc;
  --action-btn-bg-hover: #ffffff;
  --action-btn-text: rgba(0, 0, 0, .8);
  --action-btn-border: rgba(0, 0, 0, .06);
  --action-btn-border-hover: rgba(0, 0, 0, .1);
  --action-btn-hover-shadow: rgba(0, 0, 0, .08) 0 6px 16px;
}

.action-btn-subtitle {
  --action-btn-bg: #0071e3;
  --action-btn-bg-hover: #0077ed;
  --action-btn-text: #fff;
  --action-btn-border: rgba(255, 255, 255, .08);
  --action-btn-border-hover: rgba(255, 255, 255, .12);
  --action-btn-hover-shadow: rgba(0, 113, 227, .24) 0 6px 16px;
}

.action-btn-delete {
  --action-btn-bg: #fff5f5;
  --action-btn-bg-hover: #ffffff;
  --action-btn-text: #d70015;
  --action-btn-border: rgba(215, 0, 21, .2);
  --action-btn-border-hover: rgba(215, 0, 21, .28);
  --action-btn-hover-shadow: rgba(215, 0, 21, .12) 0 6px 16px;
}

:deep(.action-btn-api.el-button.is-batch-target),
:deep(.action-btn-api.el-button.is-batch-target:hover) {
  transform: none;
  opacity: .92;
  background: #f2f5f9 !important;
  color: rgba(29, 29, 31, .46) !important;
  box-shadow:
    inset 0 0 0 1px rgba(29, 29, 31, .08),
    0 1px 2px rgba(0, 0, 0, .03);
}

:deep(.action-btn-api.el-button.is-batch-target > span) {
  position: relative;
}

:deep(.action-btn-api.el-button.is-batch-target:not(.is-loading) > span::before) {
  content: '';
  width: 10px;
  height: 10px;
  margin-right: 6px;
  border-radius: 50%;
  border: 1.5px solid rgba(29, 29, 31, .12);
  border-top-color: rgba(29, 29, 31, .34);
  display: inline-block;
  vertical-align: middle;
}
.batch-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
  padding: 10px 16px;
  background: #f5f5f7;
  border: none;
  border-radius: 14px;
}
.batch-actions { display: flex; align-items: center; gap: 8px; }
.selected-count {
  font-weight: 600;
  color: #0066cc;
  font-size: 12px;
  background: rgba(255, 255, 255, .92);
  padding: 5px 10px;
  border-radius: 999px;
}

.pagination-wrap { margin-top: 18px; display: flex; justify-content: flex-end; }

:deep(.el-pagination) {
  gap: 6px;
  font-size: 12px;
}

:deep(.el-pagination .btn-prev),
:deep(.el-pagination .btn-next),
:deep(.el-pagination .el-pager li) {
  min-width: 30px;
  height: 30px;
  line-height: 30px;
  border-radius: 10px;
  background: #f5f5f7;
}

:deep(.el-pagination .el-pager li.is-active) {
  background: #0071e3;
  color: #fff;
}

:deep(.el-pagination .el-pagination__sizes .el-select__wrapper),
:deep(.el-pagination .el-pagination__jump .el-input__wrapper) {
  min-height: 30px;
  border-radius: 10px;
  background: #f5f5f7;
}

:deep(.el-tag) {
  border-radius: 999px;
}
.filter-delete-floating-card {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 2100;
  width: 360px;
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid #d7e6ff;
  border-radius: 16px;
  background: rgba(255, 255, 255, .98);
  box-shadow: 0 18px 42px rgba(38, 68, 110, .18);
  backdrop-filter: blur(8px);
}
.filter-delete-floating-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.filter-delete-floating-title { font-size: 14px; font-weight: 700; color: #23426c; }
.filter-delete-floating-mode { margin-top: 2px; font-size: 12px; color: #71839d; }
.filter-delete-floating-percent { font-size: 20px; font-weight: 700; color: #2458a6; line-height: 1; }
.filter-delete-floating-text { font-size: 12px; line-height: 1.5; color: #51657f; }
.filter-delete-floating-chip-row { display: flex; gap: 6px; flex-wrap: wrap; }
.filter-delete-floating-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  border: 1px solid #d8e5f8;
  background: #f5f9ff;
  font-size: 11px;
  font-weight: 600;
  color: #4f6787;
}
.filter-delete-floating-path {
  font-size: 11px;
  line-height: 1.45;
  color: #8090a6;
  word-break: break-all;
  padding: 8px 10px;
  border-radius: 10px;
  background: #f6f9fe;
}
.filter-delete-floating-stats { font-size: 12px; font-weight: 600; color: #466182; }
.filter-delete-floating-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.name-preview, .path-code { font-family: monospace; font-size: 13px; word-break: break-all; }
.name-preview { padding: 8px 12px; background: #f8f9fa; border: 1px solid #e4e7ed; border-radius: 4px; color: #606266; }
.subtitle-dialog-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.subtitle-dialog-title { font-size: 18px; font-weight: 700; color: #1f2d3d; }
.subtitle-dialog-header-actions { display: flex; align-items: center; gap: 8px; }
.subtitle-floating-card {
  position: fixed;
  right: 22px;
  bottom: 22px;
  z-index: 2100;
  width: min(92vw, 420px);
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid rgba(121, 160, 255, .28);
  border-radius: 18px;
  background: radial-gradient(circle at top right, rgba(111, 155, 255, .16), transparent 34%), linear-gradient(180deg, rgba(255, 255, 255, .98) 0%, rgba(247, 250, 255, .98) 100%);
  box-shadow: 0 18px 42px rgba(29, 47, 84, .18);
  backdrop-filter: blur(8px);
}
.subtitle-floating-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.subtitle-floating-title { font-size: 14px; font-weight: 700; color: #23426c; }
.subtitle-floating-mode { margin-top: 2px; font-size: 12px; color: #71839d; line-height: 1.45; word-break: break-all; }
.subtitle-floating-count { display: inline-flex; align-items: center; justify-content: center; min-width: 32px; height: 32px; padding: 0 10px; border-radius: 999px; background: #edf4ff; color: #2458a6; border: 1px solid #d3e2ff; font-size: 13px; font-weight: 700; }
.subtitle-floating-chip-row { display: flex; gap: 6px; flex-wrap: wrap; }
.subtitle-floating-chip { display: inline-flex; align-items: center; padding: 4px 8px; border-radius: 999px; border: 1px solid #d8e5f8; background: #f5f9ff; font-size: 11px; font-weight: 600; color: #4f6787; }
.subtitle-floating-text { font-size: 12px; line-height: 1.5; color: #51657f; word-break: break-all; }
.subtitle-floating-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.subtitle-workbench {
  --apple-bg: #f5f5f7;
  --apple-surface: #ffffff;
  --apple-surface-soft: #fafafc;
  --apple-text: #1d1d1f;
  --apple-text-soft: rgba(29, 29, 31, .78);
  --apple-text-faint: rgba(29, 29, 31, .5);
  --apple-blue: #0071e3;
  --apple-blue-hover: #0077ed;
  --apple-blue-soft: rgba(0, 113, 227, .08);
  --apple-border: rgba(29, 29, 31, .08);
  --apple-border-strong: rgba(29, 29, 31, .14);
  --apple-shadow: 0 18px 44px rgba(0, 0, 0, .08);
  display: grid;
  gap: 16px;
}
.subtitle-hero {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 22px 24px;
  border: 1px solid rgba(255, 255, 255, .78);
  border-radius: 22px;
  background:
    radial-gradient(circle at top right, rgba(0, 113, 227, .09), transparent 28%),
    linear-gradient(180deg, #fbfbfd 0%, var(--apple-bg) 100%);
  box-shadow: var(--apple-shadow);
}
.subtitle-panel-title {
  font-family: 'SF Pro Display', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 32px;
  font-weight: 600;
  color: var(--apple-text);
  line-height: 1.08;
  letter-spacing: -0.28px;
}
.subtitle-panel-desc {
  margin-top: 8px;
  color: var(--apple-text-soft);
  line-height: 1.7;
  max-width: 820px;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-size: 14px;
  font-weight: 400;
  letter-spacing: -0.224px;
}
.subtitle-hero-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
.subtitle-hero-chip, .subtitle-mini-chip, .subtitle-inline-chip {
  display: inline-flex;
  align-items: center;
  padding: 6px 11px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.12px;
}
.subtitle-hero-chip { background: rgba(255, 255, 255, .92); color: var(--apple-text-soft); border: 1px solid rgba(255, 255, 255, .88); box-shadow: inset 0 0 0 1px rgba(29, 29, 31, .04); }
.subtitle-hero-chip-button { cursor: pointer; transition: all .18s ease; }
.subtitle-hero-chip-button:hover { border-color: rgba(0, 113, 227, .18); background: #f4f8ff; color: var(--apple-blue); transform: translateY(-1px); }
.subtitle-hero-chip-button.active { border-color: rgba(0, 113, 227, .18); background: var(--apple-blue); color: #ffffff; box-shadow: 0 10px 22px rgba(0, 113, 227, .18); }
.subtitle-mini-chip { background: #f4f6f9; color: #59697f; border: 1px solid #e6ebf2; }
.subtitle-mini-chip-primary { color: var(--apple-blue); background: #edf4ff; border-color: #cfe0ff; }
.subtitle-mini-chip-warning { color: #a76518; background: #fff7e6; border-color: #f5d3a2; }
.subtitle-mini-chip-danger { color: #c53030; background: #fff1f0; border-color: #ffc8c2; }
.subtitle-mini-chip-muted { color: #66778f; background: #f4f6f9; border-color: #dfe6ef; }
.subtitle-inline-chip { background: #eef4ff; color: #31599b; border: 1px solid #d6e4ff; }
.subtitle-inline-chip.is-success { color: #2f855a; background: #ecfdf3; border-color: #bfe3ca; }
.subtitle-inline-chip.is-warning { color: #b7791f; background: #fff7e6; border-color: #f4d58d; }
.subtitle-panel-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.subtitle-layout { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 14px; align-items: start; }
.subtitle-side-column, .subtitle-main-column { display: grid; gap: 14px; min-width: 0; }
.subtitle-config-card, .subtitle-selection-card, .subtitle-task-card, .subtitle-tree-card {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, .78);
  min-width: 0;
  background: linear-gradient(180deg, #ffffff 0%, #fbfbfd 100%);
  box-shadow: var(--apple-shadow) !important;
}
.subtitle-config-card-strong { background: linear-gradient(180deg, #ffffff 0%, #f9fbff 100%); }
.subtitle-workbench :deep(.el-card__header) { border-bottom: 1px solid rgba(29, 29, 31, .06); }
.subtitle-workbench :deep(.el-card__body) { background: transparent; }
.subtitle-workbench :deep(.el-button) {
  border-radius: 999px;
  font-family: 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', sans-serif;
  font-weight: 500;
  letter-spacing: -0.224px;
}
.subtitle-workbench :deep(.el-button--default) {
  border-color: rgba(29, 29, 31, .08);
  background: var(--apple-surface-soft);
  color: var(--apple-text);
}
.subtitle-workbench :deep(.el-button--default:hover) {
  border-color: rgba(0, 113, 227, .18);
  background: #f4f8ff;
  color: var(--apple-blue);
}
.subtitle-workbench :deep(.el-button--primary) {
  border-color: var(--apple-blue);
  background: var(--apple-blue);
  color: #ffffff;
}
.subtitle-workbench :deep(.el-button--primary:hover) {
  border-color: var(--apple-blue-hover);
  background: var(--apple-blue-hover);
  color: #ffffff;
}
.subtitle-workbench :deep(.el-button--success),
.subtitle-workbench :deep(.el-button--warning),
.subtitle-workbench :deep(.el-button--danger),
.subtitle-workbench :deep(.el-button.is-plain) {
  border-color: rgba(29, 29, 31, .08);
  background: var(--apple-surface-soft);
  color: var(--apple-text);
}
.subtitle-workbench :deep(.el-button--success:hover),
.subtitle-workbench :deep(.el-button--warning:hover),
.subtitle-workbench :deep(.el-button.is-plain:hover) {
  border-color: rgba(0, 113, 227, .18);
  background: #f4f8ff;
  color: var(--apple-blue);
}
.subtitle-workbench :deep(.el-button--danger),
.subtitle-workbench :deep(.el-button--danger.is-plain) {
  border-color: rgba(215, 0, 21, .18);
  background: #fff5f5;
  color: #d70015;
}
.subtitle-workbench :deep(.el-button--danger:hover),
.subtitle-workbench :deep(.el-button--danger.is-plain:hover) {
  border-color: rgba(215, 0, 21, .28);
  background: #fff0f0;
  color: #c40017;
}
.subtitle-workbench :deep(.el-input__wrapper),
.subtitle-workbench :deep(.el-select__wrapper),
.subtitle-workbench :deep(.el-textarea__inner),
.subtitle-workbench :deep(.el-input-number) {
  border-radius: 12px;
  background: var(--apple-surface-soft);
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, .06);
}
.subtitle-workbench :deep(.el-switch__core) {
  border-color: rgba(29, 29, 31, .08);
  background: #e9e9ed;
}
.subtitle-workbench :deep(.el-switch.is-checked .el-switch__core) {
  background: var(--apple-blue);
  border-color: var(--apple-blue);
}
.subtitle-workbench :deep(.el-button:focus-visible),
.subtitle-workbench :deep(.el-select__wrapper.is-focused),
.subtitle-workbench :deep(.el-input__wrapper.is-focus),
.subtitle-workbench :deep(.el-textarea__inner:focus) {
  outline: 2px solid var(--apple-blue);
  outline-offset: 2px;
}
.subtitle-task-toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; justify-content: flex-end; min-width: 0; }
.subtitle-option-stack { display: grid; gap: 14px; min-width: 0; }
.subtitle-switch-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 14px; padding: 12px 0; border-bottom: 1px dashed #e9eef5; }
.subtitle-switch-row-wrap { grid-template-columns: 1fr; }
.subtitle-switch-row:last-of-type { border-bottom: none; }
.subtitle-switch-row > div:first-child { min-width: 0; }
.subtitle-switch-row :deep(.el-input-number) { width: 96px; }
.subtitle-switch-row :deep(.el-radio-group) { display: inline-flex; flex-wrap: wrap; justify-content: flex-end; row-gap: 8px; }
.subtitle-option-title { font-size: 14px; font-weight: 700; color: var(--apple-text); letter-spacing: -0.224px; }
.subtitle-filter-editor { display: grid; gap: 10px; margin-top: 4px; padding: 12px; border-radius: 12px; background: #f8fbff; border: 1px solid #e2ebfb; }
.subtitle-filter-editor-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.subtitle-filter-empty { padding: 10px 12px; border-radius: 10px; border: 1px dashed #cfdcf2; color: #6a7d97; font-size: 12px; background: #fff; }
.subtitle-filter-list { display: grid; gap: 8px; }
.subtitle-filter-row { display: grid; grid-template-columns: minmax(0, 108px) minmax(0, 1fr); gap: 8px; align-items: center; }
.subtitle-filter-row > :nth-child(3) { grid-column: 1 / -1; }
.subtitle-filter-row > :nth-child(4) { justify-self: start; }
.subtitle-filter-row > :nth-child(5) { justify-self: end; }
.subtitle-filter-target { width: 100%; }
.subtitle-filter-name { min-width: 0; }
.subtitle-filter-pattern { min-width: 0; }
.subtitle-divider-label { margin: 16px 0 10px; font-size: 12px; font-weight: 700; letter-spacing: .04em; color: #7f8da3; text-transform: uppercase; }
.subtitle-pill-grid { display: flex; gap: 8px; flex-wrap: wrap; }
.subtitle-toggle-pill { padding: 8px 12px; border-radius: 999px; border: 1px solid rgba(29, 29, 31, .08); background: #fff; color: rgba(29, 29, 31, .72); cursor: pointer; font-size: 12px; font-weight: 600; transition: all .18s ease; }
.subtitle-toggle-pill.active { background: var(--apple-blue); border-color: var(--apple-blue); color: #ffffff; box-shadow: 0 8px 20px rgba(0, 113, 227, .16); }
.subtitle-card-tip { font-size: 12px; color: #7b8797; line-height: 1.6; }
.subtitle-selection-live { display: grid; gap: 8px; min-height: 120px; }
.subtitle-selection-section { display: grid; gap: 8px; }
.subtitle-selection-section-split { margin-top: 2px; padding-top: 12px; border-top: 1px dashed #e7edf6; }
.subtitle-selection-subhead { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.subtitle-selection-subhead-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.subtitle-selection-subhead-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex: 1; min-width: 0; flex-wrap: wrap; }
.subtitle-selection-subtitle { font-size: 13px; font-weight: 700; color: #2f3f56; }
.subtitle-selection-loading { display: flex; align-items: center; gap: 8px; min-height: 64px; color: #6d7c91; font-size: 13px; }
.subtitle-selection-list, .subtitle-task-list { display: grid; gap: 10px; }
.subtitle-selection-header { display: flex; align-items: center; justify-content: space-between; gap: 14px; width: 100%; min-height: 32px; }
.subtitle-selection-header-main { display: flex; align-items: center; min-width: 0; flex: 1; }
.subtitle-selection-header-top { display: flex; align-items: center; gap: 10px; min-width: 0; justify-content: space-between; width: 100%; }
.subtitle-selection-header-title { display: inline-flex; align-items: center; gap: 8px; min-width: 0; font-size: 14px; font-weight: 700; color: #263a57; }
.subtitle-selection-count-pill { display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 22px; padding: 0 8px; border-radius: 999px; background: #edf4ff; color: #2458a6; border: 1px solid #d3e2ff; font-size: 11px; font-weight: 700; line-height: 1; }
.subtitle-selection-progress { margin-left: auto; font-size: 12px; color: #7b8ba5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 320px; display: inline-flex; align-items: center; min-height: 24px; }
.subtitle-selection-pager { display: inline-flex; align-items: center; justify-content: flex-end; gap: 6px; min-height: 24px; font-size: 12px; color: #6c7d93; white-space: nowrap; flex-shrink: 0; }
.subtitle-selection-filter-row { display: flex; gap: 6px; flex-wrap: wrap; }
.subtitle-chip-button { cursor: pointer; transition: border-color .18s ease, background .18s ease, color .18s ease, box-shadow .18s ease; }
.subtitle-chip-button:hover {
  border-color: rgba(0, 113, 227, .18);
  background: #f4f8ff;
  color: var(--apple-blue);
}
.subtitle-chip-button.active { color: #2458a8; background: #eef5ff; border-color: #bfd4ff; box-shadow: 0 0 0 2px rgba(64, 158, 255, .08); }
.subtitle-section-toggle { display: inline-flex; align-items: center; gap: 4px; padding: 0; border: none; background: transparent; color: #6a7d97; font-size: 12px; font-weight: 600; cursor: pointer; }
.subtitle-section-toggle .el-icon { transition: transform .18s ease; }
.subtitle-section-toggle .el-icon.is-collapsed { transform: rotate(-90deg); }
.subtitle-selection-item { width: 100%; padding: 11px 12px; border: 1px solid #e9eef5; border-radius: 12px; background: #fbfcfe; text-align: left; cursor: pointer; transition: border-color .18s ease, box-shadow .18s ease, background .18s ease; }
.subtitle-selection-item:hover { border-color: #bfd4f6; box-shadow: 0 8px 18px rgba(59, 88, 135, .08); background: #fff; }
.subtitle-selection-item.active { border-color: #9fc4ff; box-shadow: 0 0 0 3px rgba(64, 158, 255, .08); background: #f6faff; }
.subtitle-selection-item.skipped { border-style: dashed; background: #fcfdff; }
.subtitle-selection-body { display: grid; gap: 6px; }
.subtitle-selection-name { font-size: 13px; font-weight: 700; color: #24364f; line-height: 1.45; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.subtitle-selection-submeta { display: grid; gap: 2px; min-width: 0; }
.subtitle-selection-library { font-size: 11px; font-weight: 600; color: #4d678b; }
.subtitle-selection-path { font-size: 11px; color: #7a8ba3; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.subtitle-selection-stats { display: flex; gap: 6px; flex-wrap: wrap; }
.subtitle-selection-note { font-size: 11px; color: #66788f; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden; }
.subtitle-selection-actions { display: flex; gap: 6px; flex-wrap: wrap; padding-top: 1px; }
.subtitle-scan-result-summary-compact { margin-bottom: 12px; }
.subtitle-mini-chip-success { color: #2f855a; background: #ecfdf3; border: 1px solid #bfe3ca; }
.subtitle-scan-result-wrap,
.subtitle-scan-skip-wrap { margin-top: 12px; padding-top: 12px; border-top: 1px solid #edf1f6; }
.subtitle-scan-skip-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
.subtitle-scan-result-summary { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.subtitle-scan-result-list,
.subtitle-scan-skip-list { display: grid; gap: 8px; max-height: 220px; overflow: auto; padding-right: 4px; }
.subtitle-scan-skip-title { margin-bottom: 0; font-size: 13px; font-weight: 700; color: #516176; }
.subtitle-scan-result-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; padding: 10px 11px; border: 1px solid #e8edf5; border-radius: 12px; background: #fbfcfe; }
.subtitle-scan-result-row.skipped { background: #fffdf8; }
.subtitle-scan-result-main { min-width: 0; display: grid; gap: 4px; align-content: start; }
.subtitle-scan-result-name { font-size: 13px; font-weight: 700; color: #24364f; line-height: 1.45; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.subtitle-scan-result-submeta { display: grid; gap: 2px; min-width: 0; }
.subtitle-scan-result-library { font-size: 11px; font-weight: 600; color: #4d678b; }
.subtitle-scan-result-path { font-size: 11px; color: #7a8ba3; line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.subtitle-scan-result-meta { flex-shrink: 0; display: grid; gap: 5px; justify-items: end; align-content: start; max-width: 260px; }
.subtitle-scan-result-status { display: inline-flex; align-items: center; justify-content: center; border-radius: 999px; padding: 3px 10px; font-size: 12px; font-weight: 700; white-space: nowrap; }
.subtitle-scan-result-status.status-pending { color: #5f7390; background: #eef2f7; }
.subtitle-scan-result-status.status-success { color: #2f855a; background: #ecfdf3; }
.subtitle-scan-result-status.status-no_audio { color: #b7791f; background: #fff7e6; }
.subtitle-scan-result-status.status-no_match { color: #7b8797; background: #f5f7fa; }
.subtitle-scan-result-status.status-failed { color: #c53030; background: #fff1f0; }
.subtitle-scan-result-message { font-size: 11px; color: #6d7c91; text-align: right; line-height: 1.45; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; max-width: 260px; }
.subtitle-card-fade-enter-active,
.subtitle-card-fade-leave-active { transition: opacity .22s ease, transform .22s ease; }
.subtitle-card-fade-enter-from,
.subtitle-card-fade-leave-to { opacity: 0; transform: translateY(10px); }
.subtitle-section-header { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.subtitle-section-tip { font-size: 12px; color: #7c8ba1; line-height: 1.5; }
.subtitle-task-detail { padding: 14px; border: 1px solid #e9eef5; border-radius: 16px; background: linear-gradient(180deg, #fbfcfe 0%, #ffffff 100%); transition: border-color .18s ease, box-shadow .18s ease; min-width: 0; overflow: hidden; }
.subtitle-task-detail.active { border-color: #9fc4ff; box-shadow: 0 0 0 3px rgba(64, 158, 255, .08); }
.subtitle-task-finish-alert { margin-top: 12px; }
.subtitle-task-detail-collapse { margin-top: 12px; border-top: 1px solid #eef2f7; }
.subtitle-task-detail-collapse :deep(.el-collapse-item__wrap) { border-bottom: none; background: transparent; }
.subtitle-task-detail-collapse :deep(.el-collapse-item__header) { padding: 2px 4px; font-weight: 600; color: #2d405e; background: transparent; border-bottom: 1px solid #eef2f7; }
.subtitle-task-detail-collapse :deep(.el-collapse-item__content) { padding: 12px 0 4px; }
.subtitle-collapse-title { display: flex; justify-content: space-between; align-items: center; gap: 10px; width: 100%; padding-right: 10px; }
.subtitle-task-queue-head {
  position: relative;
  z-index: 3;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 2px;
  min-width: 0;
}
.subtitle-task-queue-filters {
  position: relative;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
  pointer-events: auto;
}
.subtitle-task-queue-filters > * {
  position: relative;
  z-index: 5;
  pointer-events: auto;
}
.subtitle-task-rail {
  position: relative;
  z-index: 1;
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.subtitle-task-queue-rail { padding-top: 2px; }
.subtitle-task-rail::-webkit-scrollbar { height: 8px; }
.subtitle-task-rail::-webkit-scrollbar-thumb { background: #d8e2f0; border-radius: 999px; }
.subtitle-task-compact { min-width: 240px; max-width: 280px; padding: 12px 14px; border-radius: 14px; border: 1px solid #e4ebf5; background: #fff; text-align: left; cursor: pointer; transition: all .18s ease; box-shadow: 0 1px 2px rgba(31, 46, 67, .04); }
.subtitle-task-compact:hover { border-color: #bfd4f6; box-shadow: 0 8px 18px rgba(59, 88, 135, .08); transform: translateY(-1px); }
.subtitle-task-compact.active { border-color: #9fc4ff; box-shadow: 0 0 0 3px rgba(64, 158, 255, .08); }
.subtitle-task-compact.processing { background: linear-gradient(180deg, #fffdf7 0%, #ffffff 100%); border-color: #f1d59d; }
.subtitle-task-compact.finished { background: linear-gradient(180deg, #f6fcf8 0%, #ffffff 100%); border-color: #bfe3ca; }
.subtitle-task-compact-head { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.subtitle-task-compact-rj { font-size: 16px; font-weight: 700; color: #23406f; }
.subtitle-task-compact-status { display: inline-flex; align-items: center; justify-content: center; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; }
.subtitle-task-compact-status.status-pending { color: #606266; background: #f2f3f5; }
.subtitle-task-compact-status.status-processing { color: #b7791f; background: #fff7e6; }
.subtitle-task-compact-status.status-completed { color: #2f855a; background: #ecfdf3; }
.subtitle-task-compact-status.status-awaiting_manual_match { color: #b7791f; background: #fff7e6; }
.subtitle-task-compact-status.status-manual_match_completed { color: #2f855a; background: #ecfdf3; }
.subtitle-task-compact-status.status-failed { color: #c53030; background: #fff1f0; }
.subtitle-task-compact-status.status-cancelled { color: #5e718c; background: #eef2f7; }
.subtitle-task-compact-folder { margin-top: 8px; color: #42556d; font-weight: 600; line-height: 1.5; word-break: break-all; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.subtitle-task-compact-step { margin-top: 8px; font-size: 12px; color: #6d7c91; line-height: 1.5; min-height: 36px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.subtitle-task-compact-meta { margin-top: 10px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 10px; font-size: 12px; color: #5e718c; }
.subtitle-task-meta-chip { display: inline-flex; align-items: center; justify-content: center; width: fit-content; padding: 2px 8px; border-radius: 999px; font-weight: 700; }
.subtitle-task-meta-chip.is-success { color: #2f855a; background: #ecfdf3; }
.subtitle-task-meta-chip.is-warning { color: #b7791f; background: #fff7e6; }
.subtitle-task-compact-actions { margin-top: 8px; display: flex; justify-content: flex-end; }
.subtitle-task-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; min-width: 0; }
.subtitle-task-head > div:first-child { min-width: 0; flex: 1; }
.subtitle-task-rj { font-size: 18px; font-weight: 700; color: #23406f; }
.subtitle-task-folder { margin-top: 4px; color: #42556d; font-weight: 600; word-break: break-all; min-width: 0; }
.subtitle-task-source,
.subtitle-task-compact-source { margin-top: 4px; font-size: 12px; color: #7b8797; line-height: 1.5; word-break: break-all; min-width: 0; }
.subtitle-task-meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; justify-content: flex-end; min-width: 0; flex-shrink: 1; }
.subtitle-task-lang { font-size: 12px; color: #7b8797; }
.subtitle-task-step { margin-top: 10px; color: #516176; font-size: 13px; min-width: 0; word-break: break-word; }
.subtitle-task-inline-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; min-width: 0; }
.subtitle-task-error { margin-top: 10px; padding: 8px 10px; border-radius: 10px; background: #fff1f0; border: 1px solid #ffd7d4; color: #ca4e4a; font-size: 13px; }
.subtitle-task-grid { margin-top: 12px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; align-items: start; }
.subtitle-task-box { padding: 10px 12px; border-radius: 12px; border: 1px solid #edf1f6; background: #fff; min-width: 0; }
.subtitle-task-box-wide { grid-column: 1 / -1; }
.subtitle-task-box-title { margin-bottom: 8px; font-size: 13px; font-weight: 700; color: #24364f; }
.subtitle-written-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; max-height: 176px; overflow: auto; padding-right: 4px; }
.subtitle-written-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding: 8px 10px; border: 1px solid #edf1f6; border-radius: 10px; background: #fbfcfe; }
.subtitle-written-name { flex: 1; min-width: 0; line-height: 1.45; word-break: break-all; }
.subtitle-written-type { flex-shrink: 0; font-size: 12px; color: #5f7390; background: #eef4ff; border: 1px solid #d6e4ff; border-radius: 999px; padding: 2px 8px; }
.subtitle-box-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.subtitle-box-meta { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; font-size: 12px; color: #7c8ba1; }
.subtitle-inline-row { display: grid; grid-template-columns: 120px 80px 1fr; gap: 8px; font-size: 13px; color: #607084; padding: 3px 0; }
.subtitle-inline-primary { color: #24364f; font-weight: 600; word-break: break-all; }
.subtitle-log-list { display: grid; gap: 6px; width: 100%; max-height: 260px; overflow: auto; padding-right: 4px; }
.subtitle-log-row { display: grid; grid-template-columns: 72px 64px minmax(0, 1fr); gap: 8px; width: 100%; align-items: start; font-size: 13px; color: #607084; padding: 4px 0; }
.subtitle-log-time { color: #8a97aa; font-variant-numeric: tabular-nums; }
.subtitle-log-level { display: inline-flex; align-items: center; justify-content: center; border-radius: 999px; padding: 2px 8px; font-size: 12px; font-weight: 700; }
.subtitle-log-level.level-info { color: #31599b; background: #eef4ff; }
.subtitle-log-level.level-success { color: #2f855a; background: #ecfdf3; }
.subtitle-log-level.level-warning { color: #b7791f; background: #fff7e6; }
.subtitle-log-level.level-error { color: #c53030; background: #fff1f0; }
.subtitle-download-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; max-height: 180px; overflow: auto; padding-right: 4px; }
.subtitle-download-row { display: grid; gap: 6px; padding: 8px 10px; border-radius: 10px; border: 1px solid #edf1f6; background: #fbfcfe; min-width: 0; }
.subtitle-download-head { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; }
.subtitle-download-name { flex: 1; line-height: 1.4; word-break: break-all; font-size: 12px; }
.subtitle-download-percent { flex-shrink: 0; font-size: 12px; font-weight: 700; color: #5a6f8f; }
.subtitle-issue-list { display: grid; gap: 8px; max-height: 240px; overflow: auto; padding-right: 4px; }
.subtitle-issue-item { padding: 10px 12px; border-radius: 12px; border: 1px solid #edf1f6; background: #fbfcfe; }
.subtitle-issue-item.issue-warning { background: #fffaf2; border-color: #f5dfb0; }
.subtitle-issue-item.issue-error { background: #fff4f3; border-color: #ffd7d4; }
.subtitle-issue-kind { font-size: 12px; font-weight: 700; color: #6f8098; letter-spacing: .04em; }
.subtitle-issue-title { margin-top: 6px; font-size: 14px; font-weight: 700; color: #24364f; word-break: break-all; line-height: 1.5; }
.subtitle-issue-content, .subtitle-issue-detail { margin-top: 6px; font-size: 13px; color: #516176; line-height: 1.7; word-break: break-word; white-space: pre-wrap; }
.subtitle-tree-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
.subtitle-tree-action-tip { font-size: 12px; color: #7c8ba1; }
.subtitle-tree-shell { display: grid; gap: 12px; min-height: 520px; }
.subtitle-inspector-empty { display: grid; gap: 10px; padding: 18px 0 8px; }
.subtitle-empty-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.subtitle-tree-info { display: grid; gap: 8px; padding: 14px; border-radius: 14px; background: #f8fbff; border: 1px solid #e5eefb; }
.subtitle-tree-title { font-size: 15px; font-weight: 700; color: #223754; }
.subtitle-tree-path { font-size: 12px; color: #75859b; word-break: break-all; line-height: 1.6; }
.subtitle-tree-meta { display: flex; gap: 8px; flex-wrap: wrap; }
.subtitle-match-shell { display: grid; gap: 10px; padding: 12px; border: 1px solid #e7edf6; border-radius: 14px; background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%); }
.subtitle-match-header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; flex-wrap: wrap; }
.subtitle-sequence-hint { margin-top: 6px; font-size: 12px; line-height: 1.55; color: #5a6f8f; }
.subtitle-match-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px minmax(0, 1fr); gap: 10px; align-items: start; }
.subtitle-match-panel, .subtitle-match-center { border: 1px solid #edf1f6; border-radius: 12px; background: #fff; padding: 10px; min-width: 0; }
.subtitle-match-panel-head { display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 8px; }
.subtitle-match-panel-tools { display: flex; align-items: center; gap: 8px; justify-content: flex-end; }
.subtitle-match-filter-select { width: 96px; }
.subtitle-match-search { width: 100%; margin-bottom: 8px; }
.subtitle-match-list, .subtitle-match-pair-list { display: grid; gap: 8px; max-height: 280px; overflow: auto; padding-right: 2px; }
.subtitle-match-item, .subtitle-match-pair { width: 100%; text-align: left; border: 1px solid #e7edf6; border-radius: 10px; background: #fbfcfe; padding: 8px 9px; cursor: pointer; transition: border-color .18s ease, background .18s ease, box-shadow .18s ease; }
.subtitle-match-item:hover, .subtitle-match-pair:hover { border-color: #bfd4f6; background: #f6faff; }
.subtitle-match-item.active, .subtitle-match-pair.active { border-color: #9fc4ff; box-shadow: 0 0 0 3px rgba(64, 158, 255, .08); background: #f3f8ff; }
.subtitle-match-item.paired { opacity: .62; }
.subtitle-match-item.queued { border-color: #7bb4ff; background: #f4f9ff; }
.subtitle-match-item.suspicious, .subtitle-match-pair.suspicious { border-color: #f4c56d; background: #fffaf0; }
.subtitle-match-name { font-size: 11px; font-weight: 700; color: #24364f; line-height: 1.35; word-break: break-word; }
.subtitle-match-badge { display: inline-flex; align-items: center; margin-left: 6px; padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 700; vertical-align: middle; }
.subtitle-match-badge.badge-paired { color: #2f855a; background: #ecfdf3; }
.subtitle-match-badge.badge-low { color: #b7791f; background: #fff7e6; }
.subtitle-match-badge.badge-seq { color: #245b96; background: #e8f2ff; }
.subtitle-match-meta { margin-top: 3px; font-size: 10px; color: #7b8797; line-height: 1.45; word-break: break-all; }
.subtitle-match-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.subtitle-match-preview-head { margin-bottom: 10px; }
.subtitle-match-preview-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.subtitle-match-pair { display: grid; gap: 4px; padding: 7px 8px; }
.subtitle-match-pair-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 11px; }
.subtitle-match-pair-confidence { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 999px; font-weight: 700; }
.subtitle-match-pair-confidence.confidence-high { color: #2f855a; background: #ecfdf3; }
.subtitle-match-pair-confidence.confidence-medium { color: #31599b; background: #eef4ff; }
.subtitle-match-pair-confidence.confidence-low { color: #b7791f; background: #fff7e6; }
.subtitle-match-pair-reason { color: #7b8797; }
.subtitle-match-pair-audio, .subtitle-match-pair-subtitle, .subtitle-match-pair-target { font-size: 12px; line-height: 1.5; word-break: break-all; }
.subtitle-match-pair-audio { color: #23406f; font-weight: 700; }
.subtitle-match-pair-arrow { color: #8da0bb; font-size: 12px; }
.subtitle-match-pair-subtitle { color: #516176; }
.subtitle-match-pair-target { color: #2f855a; font-weight: 700; }
.subtitle-match-preview-line { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 8px; align-items: start; font-size: 11px; line-height: 1.4; }
.subtitle-match-preview-result { grid-template-columns: 42px minmax(0, 1fr) auto minmax(0, 1fr); }
.subtitle-match-preview-label { color: #8a97aa; font-size: 10px; font-weight: 700; letter-spacing: .02em; }
.subtitle-match-preview-audio,
.subtitle-match-preview-subtitle,
.subtitle-match-preview-target { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.subtitle-match-preview-audio { color: #23406f; font-weight: 700; }
.subtitle-match-preview-subtitle { color: #4f6f96; }
.subtitle-match-preview-target { color: #2f855a; font-weight: 700; }
.subtitle-match-preview-target-sep { color: #9ba9bd; font-size: 10px; align-self: center; }
.subtitle-match-row-actions { display: flex; justify-content: flex-end; }
.subtitle-match-empty { padding: 16px 12px; border: 1px dashed #d8e2f0; border-radius: 10px; background: #fbfcfe; color: #6e7f95; display: grid; gap: 6px; text-align: center; }
.subtitle-tree-toolbar { display: flex; justify-content: flex-end; }
.subtitle-tree-selection-bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid #f2d6d2; border-radius: 12px; background: #fff8f7; }
.subtitle-tree-selection-count { font-size: 13px; font-weight: 700; color: #a24a43; }
.subtitle-tree-selection-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.subtitle-tree-selection-tip { font-size: 12px; color: #8a97aa; }
.subtitle-tree-head { padding-right: 10px; }
.subtitle-tree-scroll { max-height: 420px; border: 1px solid #e9eef5; border-radius: 12px; }
.subtitle-tree-row-actions { display: flex; gap: 8px; flex-wrap: nowrap; align-items: center; }
.subtitle-tree-head,
.subtitle-tree-scroll .fm-row { grid-template-columns: 42px minmax(0, 1fr) 110px 170px 124px; }
.mapped-path-box { display: flex; flex-direction: column; gap: 10px; }
.path-actions { display: flex; gap: 8px; }
:deep(.fm-dialog .el-dialog) { border-radius: 8px; overflow: hidden; box-shadow: 0 16px 48px rgba(0,0,0,.18); }
:deep(.fm-dialog .el-dialog__header) { padding: 0; margin: 0; }
:deep(.fm-dialog .el-dialog__body) { padding: 0; }
.fm-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px 12px 20px; border-bottom: 1px solid #e4e7ed; }
.fm-title { display: flex; align-items: center; gap: 10px; font-size: 13px; font-weight: 600; color: #303133; min-width: 0; }
.fm-badge { font-size: 12px; color: #909399; background: #f5f7fa; border: 1px solid #e4e7ed; border-radius: 10px; padding: 2px 8px; }
.fm-count { font-size: 12px; color: #606266; background: #f0f7ff; border: 1px solid #c6e2ff; border-radius: 12px; padding: 2px 10px; }
.fm-body { display: flex; flex-direction: column; height: 540px; background: #fff; }
.fm-toolbar { display: flex; justify-content: space-between; align-items: center; padding: 9px 16px; background: #f8f9fa; border-bottom: 1px solid #e4e7ed; }
.fm-toolbar-left { display: flex; align-items: center; gap: 6px; }
.fm-btn { padding: 4px 11px; font-size: 12px; border-radius: 5px; border: 1px solid #dcdfe6; background: #fff; cursor: pointer; }
.fm-btn-danger { color: #f56c6c; background: #fff0f0; border-color: #fbc4c4; }
.fm-btn-ghost:hover { color: #409eff; border-color: #a0cfff; background: #ecf5ff; }
.fm-search-input { width: 260px; height: 30px; padding: 0 10px; font-size: 12px; border: 1px solid #dcdfe6; border-radius: 5px; outline: none; }
.fm-head, .fm-row { display: grid; grid-template-columns: 42px minmax(0, 1fr) 120px 190px 90px; align-items: center; padding: 0 16px; }
.fm-head { height: 36px; background: #f4f5f7; border-bottom: 1px solid #e4e7ed; font-size: 12px; font-weight: 600; color: #606266; }
.fm-scroll { flex: 1; overflow: auto; contain: strict; }
.fm-row { min-height: 36px; border-bottom: 1px solid #ebeef5; font-size: 13px; contain: layout paint style; }
.fm-row-dir { background: #fafbfc; cursor: pointer; }
.fm-row-selected { background: #ecf5ff !important; }
.fm-row-disabled { background: #fbfbfc; color: #a5afbc; }
.fm-empty { display: flex; align-items: center; justify-content: center; height: 180px; color: #c0c4cc; font-size: 13px; }
.fm-name-cell { display: flex; align-items: center; gap: 6px; min-width: 0; }
.fm-arrow { width: 14px; display: inline-flex; align-items: center; justify-content: center; color: #909399; transition: transform .16s; white-space: nowrap; }
.fm-arrow.open { transform: rotate(90deg); color: #409eff; }
.fm-arrow-toggle { border: 0; background: transparent; padding: 0; cursor: pointer; }
.fm-arrow-placeholder { width: 14px; flex: 0 0 14px; }
.fm-file-icon { width: 22px; flex: 0 0 22px; display: inline-flex; align-items: center; justify-content: center; color: #409eff; }
.fm-name-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-link-edit { background: #eef6ff; color: #3b6db3; border: 1px solid #bfd7ff; border-radius: 4px; padding: 2px 8px; cursor: pointer; }
.fm-link-danger { background: #fff0f0; color: #f56c6c; border: 1px solid #fbc4c4; border-radius: 4px; padding: 2px 8px; cursor: pointer; }
.fm-check { width: 14px; height: 14px; cursor: pointer; accent-color: #409eff; }
@media (max-width: 1280px) {
  .summary-grid { grid-template-columns: 1fr; }
  .card-header { flex-direction: column; align-items: flex-start; }
  .header-actions { width: 100%; justify-content: flex-start; }
  .subtitle-layout,
  .subtitle-task-grid,
  .subtitle-match-layout { grid-template-columns: 1fr; }
  .subtitle-task-box-wide { grid-column: auto; }
  .subtitle-written-list { grid-template-columns: 1fr; }
  .subtitle-switch-row { grid-template-columns: 1fr; }
  .subtitle-switch-row :deep(.el-radio-group) { justify-content: flex-start; }
  .subtitle-filter-row { grid-template-columns: 1fr; }
  .subtitle-filter-row > :nth-child(3) { grid-column: auto; }
  .subtitle-filter-row > :nth-child(4),
  .subtitle-filter-row > :nth-child(5) { justify-self: stretch; }
  .subtitle-download-list { grid-template-columns: 1fr; max-height: 220px; }
  .subtitle-hero,
  .batch-bar,
  .path-toolbar { flex-direction: column; align-items: flex-start; }
  .batch-actions,
  .path-toolbar-right,
  .subtitle-panel-actions,
  .subtitle-tree-actions { width: 100%; justify-content: flex-start; flex-wrap: wrap; }
  .subtitle-task-compact { min-width: 220px; }
  .subtitle-selection-header,
  .subtitle-match-panel-tools { width: 100%; justify-content: space-between; flex-wrap: wrap; }
  .subtitle-scan-result-row { grid-template-columns: 1fr; }
  .subtitle-scan-result-meta { justify-items: start; max-width: none; }
  .subtitle-scan-result-message { text-align: left; max-width: none; }
  .filter-delete-floating-card { left: 12px; right: 12px; bottom: 12px; width: auto; }
}
</style>
