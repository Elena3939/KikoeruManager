<template>
  <div class="min-h-0 p-6 space-y-6">
    <!-- Page Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-bold text-slate-900 tracking-tight">ASMR 同步下载</h1>
        <p class="text-sm text-slate-500 mt-1">根据字幕文件自动下载并匹配，或手动输入 RJ 号查询下载</p>
      </div>
      <div class="flex items-center gap-2">
        <button
          class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 active:scale-95 transition-all duration-200 disabled:opacity-50 disabled:pointer-events-none"
          @click="scanFolder" :disabled="scanning || !subtitleFolder"
        >
          <Search class="w-4 h-4" />
          {{ scanning ? '扫描中...' : '扫描' }}
        </button>
        <button
          class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 active:scale-95 transition-all duration-200 disabled:opacity-50 disabled:pointer-events-none"
          @click="startSync" :disabled="syncing || selectedItems.length === 0"
        >
          <DownloadIcon class="w-4 h-4" />
          {{ syncing ? '同步中...' : '开始同步下载' }}
        </button>
        <button
          class="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-slate-300 active:scale-95 transition-all duration-200"
          @click="refreshStatus" :disabled="refreshing"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': refreshing }" />
        </button>
      </div>
    </div>

    <!-- Scan Input -->
    <section class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
        <h2 class="text-base font-semibold text-slate-900">字幕文件夹扫描</h2>
      </div>
      <div class="p-6">
        <div class="flex items-center gap-3">
          <FolderSearch class="w-5 h-5 text-slate-400 shrink-0" />
          <el-input v-model="subtitleFolder" placeholder="输入包含字幕文件的文件夹路径" clearable class="flex-1" />
        </div>
      </div>
    </section>

    <!-- Enhanced Download Workbench -->
    <section class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
        <div>
          <h2 class="text-base font-semibold text-slate-900">增强下载工作台</h2>
          <p class="text-xs text-slate-500 mt-0.5">手动输入 RJ 号直接查询并下载</p>
        </div>
        <div class="flex items-center gap-2">
          <button
            class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 active:scale-95 transition-all duration-200 disabled:opacity-50"
            @click="buildEnhancedPlans" :disabled="enhancedPlanning"
          >
            <Search class="w-3.5 h-3.5" />
            {{ enhancedPlanning ? '查询中...' : '查询 RJ' }}
          </button>
          <button
            v-if="enhancedDownloadWorkbenchTaskIds.length"
            class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 active:scale-95 transition-all duration-200"
            @click="enhancedDownloadWorkbenchVisible = true"
          >
            <DownloadIcon class="w-3.5 h-3.5" />
            下载工作台
          </button>
        </div>
      </div>
      <div class="p-6">
        <el-input
          v-model="enhancedInput"
          type="textarea"
          :rows="3"
          placeholder="支持粘贴 RJ123456、RJ234567，空格 / 换行 / 逗号分隔"
          class="mb-4"
        />

        <!-- Enhanced Plans -->
        <div v-if="enhancedPlans.length > 0" class="space-y-4">
          <!-- Batch Toolbar -->
          <div class="flex items-center justify-between bg-slate-50/80 border border-slate-200/80 rounded-xl px-4 py-3 shadow-sm backdrop-blur-sm">
            <div class="flex items-center gap-3">
              <span class="text-sm font-bold text-slate-700 tracking-wide">批量操作</span>
              <span class="text-xs font-semibold text-slate-500 bg-white px-2 py-0.5 rounded border border-slate-200 shadow-sm">已选 {{ selectedPlanRjcodes.length }} / {{ enhancedPlans.length }}</span>
            </div>
            <div class="flex items-center gap-2">
              <button class="px-2.5 py-1 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 active:scale-95 transition-all" @click="selectAllPlans">全选</button>
              <button class="px-2.5 py-1 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 active:scale-95 transition-all" @click="clearPlanSelection">清空</button>
              <button
                class="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 active:scale-95 transition-all duration-200 disabled:opacity-50 ml-2"
                @click="openEnhancedPreview" :disabled="enhancedStarting || selectedPlanRjcodes.length === 0"
              >
                <DownloadIcon class="w-3.5 h-3.5" />
                {{ enhancedStarting ? '创建中...' : `下载选中 (${selectedPlanRjcodes.length})` }}
              </button>
            </div>
          </div>

          <!-- Plan Cards Grid -->
          <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
            <WorkCard
              v-for="(plan, idx) in enhancedPlans"
              :key="plan.rjcode"
              :item="plan"
              :card-index="idx"
              :selected="selectedPlanSet.has(plan.rjcode)"
              image-field="cover_url"
              code-field="rjcode"
              size="default"
              class="enhanced-plan-card"
              @select="(p) => togglePlanSelect(p.rjcode)"
            >
              <template #cover-placeholder>
                <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center shadow">
                  <DownloadIcon class="w-5 h-5 text-white" />
                </div>
              </template>
              <template #meta>
                <div class="enhanced-plan-meta">
                  <span class="enhanced-plan-meta-pill is-code">RJ {{ plan.rjcode }}</span>
                  <span class="enhanced-plan-meta-pill is-downloadable">{{ plan.summary?.selectable_total || 0 }} 个可下载</span>
                </div>
              </template>
              <template #tags>
                <div class="enhanced-plan-tags">
                  <span class="enhanced-plan-tag is-primary">资源构成</span>
                  <span v-for="group in (plan.grouped_resources || []).slice(0, 3)" :key="group.group_key" class="enhanced-plan-tag is-soft">
                    {{ getResourceTypeLabel(group.resource_type) }} ×{{ group.count }}
                  </span>
                  <span v-if="(plan.grouped_resources || []).length > 3" class="enhanced-plan-tag is-muted">
                    +{{ (plan.grouped_resources || []).length - 3 }}
                  </span>
                </div>
              </template>
              <template #actions><span /></template>
            </WorkCard>
          </div>
        </div>
      </div>
    </section>

    <!-- Enhanced Download Workbench Dialog -->
    <DownloadTaskWorkbenchDialog
      v-model:visible="enhancedDownloadWorkbenchVisible"
      :tasks="enhancedDownloadWorkbenchTasks"
      :refreshing="enhancedDownloadWorkbenchRefreshing"
      :retrying-keys="[...enhancedRetryingTaskIds]"
      title="ASMR 增强下载"
      subtitle="增强下载任务进度"
      @refresh="refreshEnhancedDownloadWorkbench({ silent: true })"
      @background="hideEnhancedDownloadWorkbenchToBackground"
      @close="closeEnhancedDownloadWorkbench"
      @retry-task="retryEnhancedDownloadTask"
      @pause-task="handlePauseEnhancedDownloadTask"
      @resume-task="handleResumeEnhancedDownloadTask"
      @cancel-task="handleCancelEnhancedDownloadTask"
    />

    <!-- Enhanced Download Preview Dialog -->
    <CircleDownloadPreviewDialog
      v-model:visible="enhancedPreviewVisible"
      :starting="previewStarting"
      :plans="previewPlans"
      :libraries="libraries"
      :target-subdir-options="[]"
      :settings="downloadSettings"
      circle-name=""
      :enable-direct-mode="true"
      :existing-paths="existingRJPaths"
      :direct-loading="locatingRJ"
      @submit="handlePreviewSubmit"
    />

    <!-- Enhanced Download Background Card -->
    <div v-if="showEnhancedDownloadBackgroundCard" class="fixed bottom-6 right-6 z-50 w-80 bg-white/95 backdrop-blur-sm rounded-2xl border border-slate-200 shadow-xl p-4 space-y-3">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-sm font-semibold text-slate-800">增强下载正在后台运行</div>
          <div class="text-xs text-slate-500 mt-0.5">
            {{ enhancedActiveBackgroundTask ? `${enhancedActiveBackgroundTask.rjcode || 'RJ'} · ${enhancedActiveBackgroundTask.work_title || '-'}` : '保留下载队列与进度' }}
          </div>
        </div>
        <div class="text-lg font-bold text-blue-600">{{ enhancedBackgroundPercent }}%</div>
      </div>
      <div class="h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div class="h-full bg-blue-500 rounded-full transition-all duration-500" :style="{ width: enhancedBackgroundPercent + '%' }" />
      </div>
      <div class="flex flex-wrap gap-1.5">
        <span class="text-[11px] px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100">进行中 {{ enhancedProcessingTasks.length }}</span>
        <span class="text-[11px] px-2 py-0.5 rounded-full bg-slate-50 text-slate-600 border border-slate-200">等待 {{ enhancedPendingTasks.length }}</span>
        <span class="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-100">完成 {{ enhancedCompletedTasks.length }}</span>
        <span class="text-[11px] px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-100">失败 {{ enhancedFailedTasks.length }}</span>
      </div>
      <div class="flex items-center gap-2">
        <button class="flex-1 px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 active:scale-95 transition-all" @click="resumeEnhancedDownloadWorkbench">恢复工作台</button>
        <button class="px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 active:scale-95 transition-all" @click="closeEnhancedDownloadWorkbench">关闭</button>
      </div>
    </div>

    <!-- Scan Results -->
    <section v-if="scanResults.length > 0" class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
        <h2 class="text-base font-semibold text-slate-900">扫描结果 <span class="text-sm font-normal text-slate-500">({{ scanResults.length }} 个作品)</span></h2>
        <label class="inline-flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
          <input type="checkbox" v-model="selectAll" @change="handleSelectAll($event.target.checked)" class="rounded border-slate-300" />
          全选
        </label>
      </div>
      <div class="overflow-auto" style="max-height: 400px;">
        <el-table :data="scanResults" style="width: 100%" row-key="rjcode" @selection-change="handleSelectionChange">
          <el-table-column type="selection" width="50" />
          <el-table-column prop="rjcode" label="RJ号" width="120">
            <template #default="{ row }">
              <span class="font-mono font-semibold text-blue-600 text-sm">{{ row.rjcode }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="folder_name" label="文件夹名称" min-width="250">
            <template #default="{ row }">
              <div class="flex items-center gap-2">
                <FolderIcon class="w-4 h-4 text-slate-400 shrink-0" />
                <span class="text-sm text-slate-700 truncate">{{ row.folder_name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="subtitle_count" label="字幕数" width="80" align="center">
            <template #default="{ row }">
              <span class="text-sm text-slate-600">{{ row.subtitle_count }}</span>
            </template>
          </el-table-column>
          <el-table-column label="预览" width="80" align="center">
            <template #default="{ row }">
              <button class="text-xs text-blue-600 hover:text-blue-800 hover:underline transition-colors" @click="previewDownload(row)" :disabled="row.previewing">
                {{ row.previewing ? '...' : '预览' }}
              </button>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border" :class="{
                'bg-slate-50 text-slate-600 border-slate-200': row.status === 'pending',
                'bg-amber-50 text-amber-700 border-amber-200': row.status === 'downloading',
                'bg-emerald-50 text-emerald-700 border-emerald-200': row.status === 'completed',
                'bg-red-50 text-red-700 border-red-200': row.status === 'failed',
              }">{{ { pending: '待下载', downloading: '下载中', completed: '已完成', failed: '失败' }[row.status] || row.status }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </section>

    <!-- Waiting Retry Tasks -->
    <section v-if="waitingRetryTasks.length > 0" class="bg-amber-50/50 rounded-2xl border border-amber-200 shadow-sm overflow-hidden">
      <div class="px-6 py-3 border-b border-amber-100 flex items-center justify-between bg-amber-50">
        <div class="flex items-center gap-2">
          <Clock class="w-4 h-4 text-amber-600" />
          <h2 class="text-sm font-semibold text-amber-800">等待重试 ({{ waitingRetryTasks.length }})</h2>
        </div>
        <span v-if="nextRetryTime" class="text-xs text-slate-500">下次: {{ formatNextRetryTime(nextRetryTime) }}</span>
      </div>
      <div class="p-4 space-y-2">
        <div v-for="task in waitingRetryTasks" :key="task.id"
          class="flex items-center justify-between gap-3 p-3 bg-white rounded-xl border border-amber-100"
        >
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span class="font-mono font-semibold text-sm text-blue-600">{{ task.rjcode }}</span>
              <span class="text-sm text-slate-600 truncate">{{ task.work_title || task.task_metadata?.work_title }}</span>
            </div>
            <div class="flex items-center gap-3 mt-1 text-xs text-slate-500">
              <span class="text-amber-600">{{ task.task_metadata?.retry_reason || task.current_step || '未找到版本' }}</span>
              <span>已重试 {{ task.task_metadata?.retry_count || 0 }} 次</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5 shrink-0">
            <button class="px-2.5 py-1 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 active:scale-95 transition-all" @click="retryWaitingTask(task.id)">重试</button>
            <button class="px-2.5 py-1 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 active:scale-95 transition-all" @click="cancelWaitingTask(task.id)">取消</button>
          </div>
        </div>
      </div>
    </section>

    <!-- Active Tasks -->
    <section v-if="activeTasks.length > 0" class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
      <div class="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
        <h2 class="text-base font-semibold text-slate-900">下载任务</h2>
      </div>
      <div class="p-4 space-y-3">
        <div v-for="task in activeTasks" :key="task.id"
          class="rounded-xl border p-4 transition-colors" :class="{
            'border-emerald-200 bg-emerald-50/30': task.status === 'completed',
            'border-red-200 bg-red-50/30': task.status === 'failed',
            'border-slate-200 bg-slate-50/30': task.status === 'paused',
            'border-blue-200 bg-blue-50/20': task.status === 'processing',
            'border-slate-200': !['completed','failed','paused','processing'].includes(task.status),
          }"
        >
          <!-- Task Header -->
          <div class="flex items-center justify-between gap-3">
            <div class="flex items-center gap-2 min-w-0">
              <span class="font-mono font-bold text-sm text-blue-600">{{ task.actual_rjcode || task.rjcode }}</span>
              <span v-if="task.actual_rjcode && task.actual_rjcode !== task.rjcode" class="text-xs text-slate-400">(原: {{ task.rjcode }})</span>
              <span class="text-sm text-slate-600 truncate">{{ task.work_title }}</span>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
              <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border" :class="{
                'bg-emerald-50 text-emerald-700 border-emerald-200': task.status === 'completed',
                'bg-red-50 text-red-700 border-red-200': task.status === 'failed',
                'bg-slate-100 text-slate-600 border-slate-200': task.status === 'paused',
                'bg-amber-50 text-amber-700 border-amber-200': task.status === 'waiting_retry',
                'bg-blue-50 text-blue-700 border-blue-200': task.status === 'processing',
                'bg-slate-50 text-slate-600 border-slate-200': task.status === 'pending',
              }">{{ getStatusText(task.status) }}</span>
              <button v-if="task.status === 'processing'" class="px-2 py-0.5 text-[11px] font-medium text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 active:scale-95 transition-all" @click="pauseTask(task.id)">暂停</button>
              <button v-if="task.status === 'paused'" class="px-2 py-0.5 text-[11px] font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 active:scale-95 transition-all" @click="resumeTask(task.id)">继续</button>
              <button v-if="task.status === 'waiting_retry'" class="px-2 py-0.5 text-[11px] font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 active:scale-95 transition-all" @click="retryWaitingTask(task.id)">立即重试</button>
              <button v-if="task.failed_files && task.failed_files.length > 0" class="px-2 py-0.5 text-[11px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100 active:scale-95 transition-all" @click="retryFailed(task.id)">
                重试失败 ({{ task.failed_files.length }})
              </button>
            </div>
          </div>

          <!-- Progress -->
          <div class="mt-3">
            <AppLottieProgressBar :percentage="task.progress" size="sm" />
          </div>

          <!-- Step -->
          <div class="flex items-center gap-1.5 mt-2 text-xs text-slate-500">
            <AppLoadingAnimation v-if="task.status === 'processing'" variant="inline" :size="20" />
            <span>{{ task.current_step }}</span>
          </div>

          <!-- Error -->
          <div v-if="task.error_message" class="flex items-center gap-1.5 mt-2 px-3 py-2 bg-red-50 rounded-lg border border-red-100">
            <AlertTriangle class="w-3.5 h-3.5 text-red-500 shrink-0" />
            <span class="text-xs text-red-700">{{ task.error_message }}</span>
          </div>

          <!-- Subtitle Sync Result (collapsible) -->
          <details v-if="task.sync_result?.renamed_files?.length" class="mt-3">
            <summary class="flex items-center gap-1.5 text-xs font-medium text-emerald-700 cursor-pointer select-none hover:text-emerald-800">
              <FileText class="w-3.5 h-3.5" />
              字幕同步映射 ({{ task.sync_result.renamed_files.length }} 对)
            </summary>
            <div class="mt-2 space-y-2">
              <div v-for="(item, idx) in task.sync_result.renamed_files" :key="idx" class="p-2.5 bg-emerald-50/50 rounded-lg border border-emerald-100 text-xs space-y-1">
                <div class="flex items-baseline gap-2"><span class="text-slate-400 w-14 shrink-0">原音频</span><span class="text-amber-600 font-medium truncate">{{ item.original }}</span></div>
                <div class="text-center text-emerald-500 font-bold">↓</div>
                <div class="flex items-baseline gap-2"><span class="text-slate-400 w-14 shrink-0">重命名</span><span class="text-blue-600 font-medium truncate">{{ item.new }}</span></div>
                <div class="flex items-baseline gap-2"><span class="text-slate-400 w-14 shrink-0">字幕</span><span class="text-emerald-600 font-medium truncate">{{ item.subtitle }}</span></div>
              </div>
            </div>
          </details>

          <!-- Failed Files (collapsible) -->
          <details v-if="task.failed_files?.length" class="mt-3">
            <summary class="flex items-center gap-1.5 text-xs font-medium text-red-600 cursor-pointer select-none hover:text-red-700">
              <AlertTriangle class="w-3.5 h-3.5" />
              失败文件 ({{ task.failed_files.length }})
            </summary>
            <div class="mt-2 space-y-1">
              <div v-for="(file, idx) in task.failed_files" :key="idx" class="flex items-center justify-between px-2.5 py-1.5 bg-red-50/50 rounded-lg text-xs">
                <span class="text-slate-600 truncate">{{ file.title || file.path }}</span>
                <span class="text-red-600 shrink-0 ml-2">{{ file.reason }}</span>
              </div>
            </div>
          </details>

          <!-- Download Files (collapsible) -->
          <details v-if="task.download_files?.length" class="mt-3">
            <summary class="flex items-center gap-1.5 text-xs font-medium text-slate-700 cursor-pointer select-none hover:text-slate-900">
              <FolderIcon class="w-3.5 h-3.5" />
              文件下载进度 ({{ task.download_files.length }})
            </summary>
            <div class="mt-2 space-y-1.5">
              <div v-for="file in task.download_files" :key="file.name" class="flex items-center gap-2 px-2.5 py-1.5 bg-slate-50 rounded-lg text-xs min-w-0">
                <span class="flex-1 min-w-0 truncate text-slate-700">{{ file.name }}</span>
                <div class="w-20 shrink-0">
                  <div class="h-1.5 bg-slate-200 rounded-full overflow-hidden">
                    <div class="h-full bg-blue-500 rounded-full transition-all" :style="{ width: file.progress + '%' }" />
                  </div>
                </div>
                <span class="text-slate-400 shrink-0 whitespace-nowrap font-mono text-[11px] min-w-[132px] text-right">{{ formatSize(file.downloaded) }} / {{ formatSize(file.total) }}</span>
              </div>
            </div>
          </details>
        </div>
      </div>
    </section>

    <!-- Preview Dialog -->
    <el-dialog v-model="previewDialogVisible" title="下载预览" width="900px" class="rounded-2xl">
      <div v-if="previewLoading" class="flex items-center justify-center py-10">
        <AppLoadingAnimation label="正在获取作品信息..." :size="132" :min-height="180" />
      </div>
      <div v-else-if="previewData" class="space-y-5">
        <div class="grid grid-cols-3 gap-4">
          <div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
            <div class="text-xs text-slate-500 mb-1">请求 RJ 号</div>
            <div class="font-mono font-semibold text-slate-900">{{ previewData.rjcode }}</div>
          </div>
          <div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
            <div class="text-xs text-slate-500 mb-1">实际下载</div>
            <div class="flex items-center gap-2">
              <span class="font-mono font-semibold" :class="previewData.actual_rjcode !== previewData.rjcode ? 'text-amber-600' : 'text-emerald-600'">{{ previewData.actual_rjcode || '未找到' }}</span>
              <span v-if="previewData.lang" class="text-xs text-slate-500">({{ previewData.lang }})</span>
            </div>
          </div>
          <div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
            <div class="text-xs text-slate-500 mb-1">预计大小</div>
            <div class="font-semibold text-blue-600">{{ formatSize(previewData.total_size) }}</div>
          </div>
        </div>
        <div class="flex items-center gap-4 text-sm text-slate-600">
          <span>标题: <strong class="text-slate-900">{{ previewData.title }}</strong></span>
          <span>文件: {{ previewData.total_files }} → <strong class="text-emerald-600">{{ previewData.filtered_files }}</strong></span>
        </div>

        <!-- Available Versions -->
        <div v-if="previewData.available_versions?.length">
          <h4 class="text-sm font-semibold text-slate-700 mb-2">可用版本</h4>
          <div class="space-y-1.5">
            <div v-for="ver in previewData.available_versions" :key="ver.rjcode"
              class="flex items-center gap-3 px-3 py-2 bg-slate-50 rounded-lg border border-slate-100 text-sm"
            >
              <span class="font-mono font-semibold text-slate-900 w-24">{{ ver.rjcode }}</span>
              <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border" :class="{
                'bg-emerald-50 text-emerald-700 border-emerald-200': ver.priority <= 1,
                'bg-amber-50 text-amber-700 border-amber-200': ver.priority === 2,
                'bg-slate-100 text-slate-600 border-slate-200': ver.priority > 2,
              }">{{ getLangName(ver.lang) }}</span>
              <span class="text-slate-500">{{ ver.file_count }} 文件</span>
              <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[11px]" :class="ver.available ? 'text-emerald-600 bg-emerald-50' : 'text-red-600 bg-red-50'">{{ ver.available ? '可用' : '不可用' }}</span>
              <span class="text-slate-500 truncate flex-1">{{ ver.title }}</span>
            </div>
          </div>
        </div>

        <!-- File List -->
        <div>
          <h4 class="text-sm font-semibold text-slate-700 mb-2">下载文件 ({{ previewData.filtered_files }})</h4>
          <div class="overflow-auto" style="max-height: 350px;">
            <el-table :data="previewData.files" size="small">
              <el-table-column type="index" label="#" width="50" />
              <el-table-column label="文件路径" min-width="300">
                <template #default="{ row }">
                  <div class="flex items-center gap-1.5 text-sm">
                    <FileIcon class="w-3.5 h-3.5 text-slate-400 shrink-0" />
                    <span class="truncate" :title="row.path || row.title">{{ row.title }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="type" label="类型" width="80">
                <template #default="{ row }">
                  <span class="text-xs text-slate-500">{{ row.type || '文件' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="{ row }">
                  <span class="text-xs font-mono text-slate-600">{{ formatSize(row.size) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>
      <div v-else class="py-10">
        <AppEmptyState description="无法获取预览信息" size="sm" />
      </div>
    </el-dialog>

    <!-- Enhanced Session Drawer -->
    <el-drawer v-model="enhancedSessionDrawerVisible" size="55%" :title="enhancedSessionDetail?.rjcode ? `${enhancedSessionDetail.rjcode} 会话详情` : '会话详情'">
      <div v-app-loading="{ loading: enhancedSessionDetailLoading, text: '正在加载增强下载详情...', size: 124 }">
        <template v-if="enhancedSessionDetail">
          <div class="flex flex-wrap gap-2 mb-4">
            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">{{ getSessionStatusLabel(enhancedSessionDetail.status) }}</span>
            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">优先级 {{ enhancedSessionDetail.queue_priority }}</span>
            <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 text-slate-600 border border-slate-200">{{ getUploadModeLabel(enhancedSessionDetail.upload_mode) }}</span>
          </div>

          <div class="grid grid-cols-2 gap-3 mb-4">
            <div class="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div class="text-xs text-slate-500">标题</div>
              <div class="text-sm text-slate-900 font-medium mt-0.5">{{ enhancedSessionDetail.source_label || '未命名会话' }}</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div class="text-xs text-slate-500">目标路径</div>
              <div class="text-sm text-slate-900 font-mono mt-0.5 break-all">{{ enhancedSessionDetail.target_path || '未设置' }}</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div class="text-xs text-slate-500">已选/已上传</div>
              <div class="text-sm text-slate-900 font-medium mt-0.5">{{ enhancedSessionDetail.statistics?.selected_resource_count || 0 }} / {{ enhancedSessionDetail.statistics?.uploaded_count || 0 }}</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div class="text-xs text-slate-500">成功/失败/MD5失败</div>
              <div class="text-sm font-medium mt-0.5">
                <span class="text-emerald-600">{{ enhancedSessionDetail.statistics?.success_count || 0 }}</span>
                <span class="text-slate-400 mx-1">/</span>
                <span class="text-red-600">{{ enhancedSessionDetail.statistics?.failed_count || 0 }}</span>
                <span class="text-slate-400 mx-1">/</span>
                <span class="text-amber-600">{{ enhancedSessionDetail.statistics?.verify_summary?.failed || 0 }}</span>
              </div>
            </div>
          </div>

          <el-table v-if="enhancedSessionDetail.resources?.length" :data="enhancedSessionDetail.resources" max-height="420" size="small">
            <el-table-column prop="file_name" label="文件" min-width="240" show-overflow-tooltip />
            <el-table-column prop="resource_type" label="类型" width="90" />
            <el-table-column prop="download_status" label="下载" width="100" />
            <el-table-column prop="verify_status" label="校验" width="100" />
            <el-table-column prop="upload_status" label="上传" width="100" />
            <el-table-column label="匹配依据" min-width="180">
              <template #default="{ row }">{{ row.extra_metadata?.match_basis?.join(' / ') || '-' }}</template>
            </el-table-column>
            <el-table-column prop="upload_path" label="上传目标" min-width="220" show-overflow-tooltip />
            <el-table-column prop="last_error" label="异常" min-width="180" show-overflow-tooltip />
          </el-table>
          <AppEmptyState v-else description="暂无资源详情" size="sm" />
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, Download as DownloadIcon, Folder as FolderIcon, RefreshCw, FolderSearch, Clock, AlertTriangle, FileText, File as FileIcon, CheckCircle2 } from 'lucide-vue-next'
import { asmrSyncApi, configApi, libraryApi, taskApi } from '../api'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppLottieProgressBar from '../components/common/AppLottieProgressBar.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import DownloadTaskWorkbenchDialog from '../components/download/DownloadTaskWorkbenchDialog.vue'
import CircleDownloadPreviewDialog from '../components/circle/CircleDownloadPreviewDialog.vue'
import WorkCard from '../components/circle/WorkCard.vue'

const ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY = 'prekikoeru.asmrSync.downloadWorkbench'

const subtitleFolder = ref('')
const scanning = ref(false)
const syncing = ref(false)
const refreshing = ref(false)
const scanResults = ref([])
const selectedItems = ref([])
const selectAll = ref(false)
const previewDialogVisible = ref(false)
const previewLoading = ref(false)
const previewData = ref(null)
const tasks = ref([])
const nextRetryTime = ref('')
const enhancedInput = ref('')
const enhancedFolderPath = ref('')
const enhancedPlanning = ref(false)
const enhancedStarting = ref(false)
const enhancedDashboardLoading = ref(false)
const enhancedSessionsLoading = ref(false)
const enhancedSessionDrawerVisible = ref(false)
const enhancedSessionDetailLoading = ref(false)
const enhancedSessionDetail = ref(null)
const enhancedPlans = ref([])
const enhancedSessions = ref([])
const selectedPlanSet = ref(new Set())
const enhancedDownloadWorkbenchTaskIds = ref([])
const enhancedDownloadWorkbenchTasks = ref([])
const enhancedDownloadWorkbenchVisible = ref(false)
const enhancedDownloadWorkbenchBackgroundActive = ref(false)
const enhancedDownloadWorkbenchRefreshing = ref(false)
const enhancedRetryingTaskIds = ref(new Set())
let enhancedDownloadWorkbenchTimer = null

// Enhanced preview dialog state
const enhancedPreviewVisible = ref(false)
const previewStarting = ref(false)
const previewPlans = ref([])
const libraries = ref([])
const downloadSettings = ref({
  mode: 'classify',
  targetLibraryId: '',
  targetSubdir: '',
  namingMode: 'api',
  classifyMode: 'none',
  downloadBasePath: '',
  directLibraryId: '',
  directBasePath: '',
  directLibraryType: '',
  directSubPath: ''
})
const existingRJPaths = ref({})
const locatingRJ = ref(false)
const enhancedDashboard = ref({
  total_rj: 0,
  total_resources: 0,
  downloaded_resources: 0,
  uploaded_resources: 0,
  processing_tasks: 0,
  pending_tasks: 0,
  failed_tasks: 0
})
const enhancedFilters = ref({
  resourceTypes: ['audio', 'subtitle', 'cover'],
  audioFormats: [],
  subtitleLanguages: [],
  includeExisting: false
})
const enhancedUpload = ref({
  mode: 'disabled',
  targetPath: '',
  libraryId: ''
})
let statusInterval = null
let asmrSyncInitialized = false
let asmrSyncViewActive = false

// 计算属性：分离等待重试的任务和活动任务
const waitingRetryTasks = computed(() => {
  return tasks.value.filter(t => t.status === 'waiting_retry')
})

const activeTasks = computed(() => {
  return tasks.value.filter(t => t.status !== 'waiting_retry')
})

const enhancedMetricCards = computed(() => {
  const dashboard = enhancedDashboard.value || {}
  return [
    {
      label: '已建档 RJ',
      value: dashboard.total_rj || 0,
      help: '资源库中已记录的作品数'
    },
    {
      label: '资源条目',
      value: dashboard.total_resources || 0,
      help: '已抓取并落库的远端资源'
    },
    {
      label: '已下载',
      value: dashboard.downloaded_resources || 0,
      help: '已完成下载的文件数'
    },
    {
      label: '已上传',
      value: dashboard.uploaded_resources || 0,
      help: '已进入自动上传管道的文件数'
    },
    {
      label: '处理中',
      value: dashboard.processing_tasks || 0,
      help: '当前运行中的增强下载任务'
    },
    {
      label: '待处理/失败',
      value: `${dashboard.pending_tasks || 0} / ${dashboard.failed_tasks || 0}`,
      help: '当前排队与失败任务概况'
    }
  ]
})

const hasEnhancedSelections = computed(() => {
  return enhancedPlans.value.some(plan => (plan.selectable_resources || []).some(item => item.selected))
})

const selectedPlanRjcodes = computed(() => [...selectedPlanSet.value])
const enhancedProcessingTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => t.status === 'processing'))
const enhancedPendingTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => ['pending', 'paused', 'waiting_retry'].includes(String(t.status || ''))))
const enhancedCompletedTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => t.status === 'completed'))
const enhancedFailedTasks = computed(() => enhancedDownloadWorkbenchTasks.value.filter(t => t.status === 'failed'))
const showEnhancedDownloadBackgroundCard = computed(() => enhancedDownloadWorkbenchBackgroundActive.value && !enhancedDownloadWorkbenchVisible.value && enhancedDownloadWorkbenchTaskIds.value.length > 0)
const enhancedActiveBackgroundTask = computed(() => enhancedProcessingTasks.value[0] || enhancedPendingTasks.value[0] || enhancedDownloadWorkbenchTasks.value[0] || null)
const enhancedBackgroundPercent = computed(() => {
  if (!enhancedDownloadWorkbenchTasks.value.length) return 0
  const total = enhancedDownloadWorkbenchTasks.value.reduce((sum, t) => sum + Number(t.progress || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total / enhancedDownloadWorkbenchTasks.value.length)))
})

// 格式化下次重试时间
const formatNextRetryTime = (isoString) => {
  if (!isoString) return '未知'
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = date - now
  if (diffMs <= 0) return '即将重试'

  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffDays > 0) {
    return `${diffDays}天${diffHours % 24}小时后`
  } else if (diffHours > 0) {
    return `${diffHours}小时${diffMins % 60}分钟后`
  } else {
    return `${diffMins}分钟后`
  }
}

const getLangName = (lang) => {
  const map = { 'CHI_HANS': '简中', 'CHI_SIMP': '简中', 'CHI_HANT': '繁中', 'CHI_TRAD': '繁中', 'JPN': '日文', 'JAP': '日文', 'ENG': '英文' }
  return map[lang] || lang
}

const getStatusText = (status) => {
  const map = { 'pending': '等待中', 'processing': '处理中', 'completed': '已完成', 'failed': '失败', 'paused': '已暂停', 'waiting_retry': '等待重试' }
  return map[status] || status
}

const getResourceTypeLabel = (type) => {
  const map = { audio: '音频', subtitle: '字幕', cover: '封面', other: '其他' }
  return map[type] || type || '资源'
}

const parseEnhancedRJCodes = () => {
  return [...new Set(
    (enhancedInput.value || '')
      .split(/[\s,，;；]+/)
      .map(item => item.trim().toUpperCase())
      .filter(Boolean)
  )]
}

const getSelectedResourceCount = (plan) => {
  return (plan?.selectable_resources || []).filter(item => item.selected).length
}

const summarizePlanResources = (resources = []) => {
  const summary = {}
  for (const item of Array.isArray(resources) ? resources : []) {
    const key = getResourceTypeLabel(item?.resource_type)
    summary[key] = (summary[key] || 0) + 1
  }
  return Object.entries(summary)
    .map(([label, count]) => `${label} ${count}`)
    .join(' / ')
}

const getUploadModeLabel = (mode) => {
  const map = { disabled: '仅下载', local: '本地复制', synology: '群晖上传' }
  return map[mode] || mode || '未设置'
}

const getSessionStatusLabel = (status) => {
  const map = {
    planning: '规划中',
    queued: '排队中',
    downloading: '下载中',
    verifying: '校验中',
    uploading: '上传中',
    completed: '已完成',
    partial_failed: '部分失败',
    failed: '失败',
    paused: '已暂停'
  }
  return map[status] || status || '未知'
}

const togglePlanSelection = (plan, checked) => {
  ;(plan.selectable_resources || []).forEach(item => {
    item.selected = Boolean(checked)
  })
}

const applyPlanPreset = (plan, presetKey) => {
  const preset = new Set(plan?.selection_presets?.[presetKey] || [])
  ;(plan.selectable_resources || []).forEach(item => {
    item.selected = preset.has(item.relative_path)
  })
}

const loadEnhancedDashboard = async () => {
  enhancedDashboardLoading.value = true
  try {
    const result = await asmrSyncApi.dashboardEnhanced()
    enhancedDashboard.value = result.dashboard || enhancedDashboard.value
  } catch (error) {
    console.error('加载增强看板失败:', error)
  } finally {
    enhancedDashboardLoading.value = false
  }
}

const loadEnhancedSessions = async () => {
  enhancedSessionsLoading.value = true
  try {
    const result = await asmrSyncApi.sessionsEnhanced()
    enhancedSessions.value = result.sessions || []
  } catch (error) {
    console.error('加载增强会话失败:', error)
  } finally {
    enhancedSessionsLoading.value = false
  }
}

const buildEnhancedPlans = async () => {
  const rjcodes = parseEnhancedRJCodes()
  if (rjcodes.length === 0) return ElMessage.warning('请先输入至少一个 RJ 号')
  enhancedPlanning.value = true
  try {
    const result = await asmrSyncApi.planEnhanced({
      rjcodes,
      folder_path: '',
      resource_types: ['audio', 'subtitle', 'cover'],
      audio_formats: [],
      subtitle_languages: [],
      include_existing: false
    })
    enhancedPlans.value = (result.plans || []).map(plan => ({
      ...plan,
      selectable_resources: (plan.selectable_resources || []).map(item => ({
        ...item,
        selected: item.selected !== false
      }))
    }))
    if (result.errors?.length) {
      ElMessage.warning(`已生成 ${result.planned_count} 个计划，${result.errors.length} 个 RJ 失败`)
    } else {
      ElMessage.success(`已生成 ${result.planned_count} 个增强下载计划`)
    }
    await loadEnhancedDashboard()
    // Auto-select all plans after query
    selectedPlanSet.value = new Set(enhancedPlans.value.map(p => p.rjcode))
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '生成下载计划失败')
  } finally {
    enhancedPlanning.value = false
  }
}

function togglePlanSelect(rjcode) {
  const next = new Set(selectedPlanSet.value)
  if (next.has(rjcode)) next.delete(rjcode)
  else next.add(rjcode)
  selectedPlanSet.value = next
}

function selectAllPlans() {
  selectedPlanSet.value = new Set(enhancedPlans.value.map(p => p.rjcode))
}

function clearPlanSelection() {
  selectedPlanSet.value = new Set()
}

async function loadLibraries() {
  try {
    const result = await libraryApi.listLibraries()
    libraries.value = result.libraries || result || []
  } catch { /* ignore */ }
}

async function openEnhancedPreview() {
  const selectedRjs = selectedPlanSet.value
  const plans = enhancedPlans.value.filter(plan => selectedRjs.has(plan.rjcode))
  if (!plans.length) return ElMessage.warning('请先选中至少一个计划')
  previewPlans.value = plans
  enhancedPreviewVisible.value = true
  loadLibraries()
  loadExistingRJPaths(plans.map(plan => plan.rjcode))
}

async function loadExistingRJPaths(rjcodes) {
  const list = Array.from(new Set((rjcodes || []).map(rj => String(rj || '').trim().toUpperCase()).filter(Boolean)))
  if (!list.length) {
    existingRJPaths.value = {}
    return
  }
  locatingRJ.value = true
  try {
    const data = await asmrSyncApi.locateRJ(list)
    const map = {}
    ;(data?.results || []).forEach(item => {
      const rj = String(item?.rjcode || '').toUpperCase()
      if (!rj) return
      map[rj] = { matches: Array.isArray(item?.matches) ? item.matches : [] }
    })
    existingRJPaths.value = map
  } catch (error) {
    console.error('locate-rj 失败:', error)
    existingRJPaths.value = {}
  } finally {
    locatingRJ.value = false
  }
}

async function handlePreviewSubmit(payload) {
  const items = Array.isArray(payload.items) ? payload.items : []
  if (!items.length) return ElMessage.warning('没有选中任何文件')
  previewStarting.value = true
  enhancedStarting.value = true
  try {
    const result = await asmrSyncApi.startEnhanced(items)
    const newTaskIds = (result.tasks || []).map(t => t.task_id).filter(Boolean)
    enhancedDownloadWorkbenchTaskIds.value = [
      ...newTaskIds,
      ...enhancedDownloadWorkbenchTaskIds.value.filter(id => !newTaskIds.includes(id))
    ]
    enhancedDownloadWorkbenchVisible.value = newTaskIds.length > 0
    enhancedDownloadWorkbenchBackgroundActive.value = false
    persistEnhancedDownloadWorkbenchState()
    await refreshEnhancedDownloadWorkbench()
    ElMessage.success(result.message || '增强下载任务已创建')
    enhancedPreviewVisible.value = false
    await refreshStatus()
    await loadEnhancedSessions()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动增强下载失败')
  } finally {
    enhancedStarting.value = false
    previewStarting.value = false
  }
}

// --- Enhanced Download Workbench Management ---

function persistEnhancedDownloadWorkbenchState() {
  try {
    localStorage.setItem(ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY, JSON.stringify({
      taskIds: enhancedDownloadWorkbenchTaskIds.value,
      visible: enhancedDownloadWorkbenchVisible.value,
      background: enhancedDownloadWorkbenchBackgroundActive.value
    }))
  } catch (_) {}
}

function hydrateEnhancedDownloadWorkbenchState() {
  try {
    const raw = JSON.parse(localStorage.getItem(ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY) || '{}')
    enhancedDownloadWorkbenchTaskIds.value = Array.isArray(raw.taskIds) ? raw.taskIds.filter(Boolean) : []
    enhancedDownloadWorkbenchVisible.value = Boolean(raw.visible && enhancedDownloadWorkbenchTaskIds.value.length)
    enhancedDownloadWorkbenchBackgroundActive.value = Boolean(raw.background && enhancedDownloadWorkbenchTaskIds.value.length)
  } catch (_) {
    enhancedDownloadWorkbenchTaskIds.value = []
    enhancedDownloadWorkbenchVisible.value = false
    enhancedDownloadWorkbenchBackgroundActive.value = false
  }
}

function clearEnhancedDownloadWorkbenchState() {
  enhancedDownloadWorkbenchTaskIds.value = []
  enhancedDownloadWorkbenchTasks.value = []
  enhancedDownloadWorkbenchVisible.value = false
  enhancedDownloadWorkbenchBackgroundActive.value = false
  stopEnhancedDownloadWorkbenchPolling()
  try { localStorage.removeItem(ASMR_SYNC_DOWNLOAD_WORKBENCH_KEY) } catch (_) {}
}

function stopEnhancedDownloadWorkbenchPolling() {
  if (enhancedDownloadWorkbenchTimer) {
    window.clearTimeout(enhancedDownloadWorkbenchTimer)
    enhancedDownloadWorkbenchTimer = null
  }
}

function startEnhancedDownloadWorkbenchPolling() {
  if (!enhancedDownloadWorkbenchTaskIds.value.length) return
  stopEnhancedDownloadWorkbenchPolling()
  enhancedDownloadWorkbenchTimer = window.setTimeout(() => {
    refreshEnhancedDownloadWorkbench()
  }, 2000)
}

async function refreshEnhancedDownloadWorkbench(options = {}) {
  const silent = Boolean(options?.silent)
  if (!enhancedDownloadWorkbenchTaskIds.value.length) {
    enhancedDownloadWorkbenchTasks.value = []
    stopEnhancedDownloadWorkbenchPolling()
    return
  }
  if (!silent) enhancedDownloadWorkbenchRefreshing.value = true
  try {
    const result = await asmrSyncApi.status()
    const allTasks = Array.isArray(result.tasks) ? result.tasks : []
    enhancedDownloadWorkbenchTasks.value = enhancedDownloadWorkbenchTaskIds.value
      .map(id => allTasks.find(t => t.id === id))
      .filter(Boolean)
    enhancedDownloadWorkbenchTaskIds.value = enhancedDownloadWorkbenchTasks.value.map(t => t.id)
    const stillActive = enhancedDownloadWorkbenchTasks.value.some(t => ['pending', 'processing', 'paused', 'waiting_retry'].includes(String(t.status || '')))
    if (stillActive || enhancedDownloadWorkbenchVisible.value || enhancedDownloadWorkbenchBackgroundActive.value) startEnhancedDownloadWorkbenchPolling()
    else stopEnhancedDownloadWorkbenchPolling()
  } catch (error) {
    console.error('刷新增强下载工作台失败:', error)
    startEnhancedDownloadWorkbenchPolling()
  } finally {
    if (!silent) enhancedDownloadWorkbenchRefreshing.value = false
  }
}

function hideEnhancedDownloadWorkbenchToBackground() {
  enhancedDownloadWorkbenchVisible.value = false
  enhancedDownloadWorkbenchBackgroundActive.value = true
}

function resumeEnhancedDownloadWorkbench() {
  enhancedDownloadWorkbenchVisible.value = true
  enhancedDownloadWorkbenchBackgroundActive.value = false
}

function closeEnhancedDownloadWorkbench() {
  clearEnhancedDownloadWorkbenchState()
}

async function retryEnhancedDownloadTask(task) {
  const sessionId = String(task?.task_metadata?.session_id || task?.session_id || '').trim()
  const taskId = String(task?.id || '').trim()
  const next = new Set(enhancedRetryingTaskIds.value)
  next.add(taskId)
  enhancedRetryingTaskIds.value = next
  try {
    if (sessionId) {
      const response = await asmrSyncApi.retryFailedSession(sessionId)
      const nextTaskId = String(response?.session?.task_id || '').trim()
      if (nextTaskId && nextTaskId !== taskId) {
        enhancedDownloadWorkbenchTaskIds.value = [
          nextTaskId,
          ...enhancedDownloadWorkbenchTaskIds.value.filter(id => id !== nextTaskId && id !== taskId)
        ]
      }
    } else if (taskId) {
      await asmrSyncApi.retry(taskId)
    }
    ElMessage.success('已提交重试')
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || error.message || '提交重试失败')
  } finally {
    const done = new Set(enhancedRetryingTaskIds.value)
    done.delete(taskId)
    enhancedRetryingTaskIds.value = done
  }
}

async function handlePauseEnhancedDownloadTask(task) {
  const sessionId = String(task?.session_id || task?.task_metadata?.session_id || '').trim()
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.pauseSession(sessionId)
    } else if (taskId) {
      await taskApi.pause(taskId)
    } else {
      return ElMessage.warning('无法识别任务，缺少会话或任务 ID')
    }
    ElMessage.success('已暂停')
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    console.error('[ASMR] pause failed', { sessionId, taskId, error })
    ElMessage.error(error.response?.data?.detail || error.message || '暂停失败')
  }
}

async function handleResumeEnhancedDownloadTask(task) {
  const sessionId = String(task?.session_id || task?.task_metadata?.session_id || '').trim()
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.resumeSession(sessionId)
    } else if (taskId) {
      await taskApi.resume(taskId)
    } else {
      return ElMessage.warning('无法识别任务，缺少会话或任务 ID')
    }
    ElMessage.success('已恢复')
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    console.error('[ASMR] resume failed', { sessionId, taskId, error })
    ElMessage.error(error.response?.data?.detail || error.message || '恢复失败')
  }
}

async function handleCancelEnhancedDownloadTask(task) {
  const rjcode = String(task?.rjcode || '').trim()
  const title = String(task?.work_title || task?.source_label || '').trim()
  try {
    await showSystemConfirm({
      title: '取消下载任务',
      message: `确定要取消 ${rjcode || title || '此任务'} 的下载吗？`,
      description: '取消后将停止下载并清理已下载的临时文件，此操作不可撤销。',
      tone: 'danger',
      confirmText: '取消下载',
    })
  } catch {
    return
  }
  const sessionId = String(task?.session_id || task?.task_metadata?.session_id || '').trim()
  const taskId = String(task?.id || task?.active_task_id || '').trim()
  try {
    if (sessionId) {
      await asmrSyncApi.cancelSession(sessionId, { cleanup: true })
    } else if (taskId) {
      await taskApi.batchCancelCleanup([taskId])
    } else {
      return ElMessage.warning('无法识别任务，缺少会话或任务 ID')
    }
    ElMessage.success('已取消并清理')
    await refreshEnhancedDownloadWorkbench({ silent: true })
  } catch (error) {
    console.error('[ASMR] cancel failed', { sessionId, taskId, error })
    ElMessage.error(error.response?.data?.detail || error.message || '取消失败')
  }
}

const openEnhancedSession = async (session) => {
  enhancedSessionDrawerVisible.value = true
  enhancedSessionDetailLoading.value = true
  try {
    const result = await asmrSyncApi.sessionEnhanced(session.id)
    enhancedSessionDetail.value = result.session || null
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载会话详情失败')
  } finally {
    enhancedSessionDetailLoading.value = false
  }
}

const changeSessionPriority = async (session, delta) => {
  const nextPriority = Math.max(1, Number(session.queue_priority || 100) + delta)
  try {
    await asmrSyncApi.updateSessionPriority(session.id, nextPriority)
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '调整优先级失败')
  }
}

const pauseEnhancedSession = async (session) => {
  try {
    await asmrSyncApi.pauseSession(session.id)
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '暂停会话失败')
  }
}

const resumeEnhancedSession = async (session) => {
  try {
    await asmrSyncApi.resumeSession(session.id)
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '恢复会话失败')
  }
}

const retryEnhancedSession = async (session) => {
  try {
    await asmrSyncApi.retryFailedSession(session.id)
    await loadEnhancedSessions()
    await refreshStatus()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重试失败资源失败')
  }
}

const pauseTask = async (taskId) => {
  try {
    await asmrSyncApi.pause(taskId)
    ElMessage.success('任务已暂停')
    await refreshStatus()
  } catch (error) {
    ElMessage.error('暂停失败')
  }
}

const resumeTask = async (taskId) => {
  try {
    await asmrSyncApi.resume(taskId)
    ElMessage.success('任务已恢复')
    await refreshStatus()
  } catch (error) {
    ElMessage.error('恢复失败')
  }
}

const retryFailed = async (taskId) => {
  try {
    const result = await asmrSyncApi.retry(taskId)
    ElMessage.success(result.message)
    await refreshStatus()
  } catch (error) {
    ElMessage.error('重试失败')
  }
}

const retryWaitingTask = async (taskId) => {
  try {
    const result = await asmrSyncApi.retryWaiting(taskId)
    ElMessage.success(result.message)
    await refreshStatus()
  } catch (error) {
    ElMessage.error('重试失败')
  }
}

const cancelWaitingTask = async (taskId) => {
  try {
    // 从数据库和内存中删除等待重试的任务
    await asmrSyncApi.deleteWaitingRetry(taskId)
    ElMessage.success('任务已取消')
    // 从本地列表中移除
    const index = tasks.value.findIndex(t => t.id === taskId)
    if (index > -1) {
      tasks.value.splice(index, 1)
    }
  } catch (error) {
    ElMessage.error('取消失败')
  }
}

const loadSavedFolder = async () => {
  try {
    const config = await configApi.get()
    if (config.storage?.asmr_subtitle_path) {
      subtitleFolder.value = config.storage.asmr_subtitle_path
    }
    if (config.storage?.temp_path && !downloadSettings.value.downloadBasePath) {
      downloadSettings.value.downloadBasePath = config.storage.temp_path.replace(/[\\/]$/, '') + '/asmr_enhanced'
    }
    enhancedUpload.value = {
      mode: config.asmr_sync?.auto_upload_enabled ? (config.asmr_sync?.auto_upload_mode || 'local') : 'disabled',
      targetPath: config.asmr_sync?.auto_upload_target_path || '',
      libraryId: config.asmr_sync?.auto_upload_library_id || ''
    }
  } catch (error) {
    console.error('加载配置失败:', error)
  }
}

// 加载等待重试任务
const loadWaitingRetryTasks = async () => {
  try {
    const result = await asmrSyncApi.getWaitingRetry()
    nextRetryTime.value = result.next_retry_time || ''

    // 将等待重试任务添加到任务列表
    if (result.tasks && result.tasks.length > 0) {
      const waitingTasks = result.tasks.map(t => ({
        id: t.id,
        rjcode: t.rjcode,
        work_title: t.work_title,
        status: 'waiting_retry',
        progress: 0,
        current_step: `等待重试: ${t.retry_reason || '未找到版本'}`,
        task_metadata: {
          retry_reason: t.retry_reason,
          retry_count: t.retry_count,
          retry_after: t.retry_after,
          subtitle_folder: t.subtitle_folder
        }
      }))

      // 合并到任务列表（避免重复）
      const existingIds = new Set(tasks.value.map(t => t.id))
      for (const task of waitingTasks) {
        if (!existingIds.has(task.id)) {
          tasks.value.push(task)
        }
      }
    }
  } catch (error) {
    console.error('加载等待重试任务失败:', error)
  }
}

const selectFolder = () => ElMessage.info('请手动输入文件夹路径')

const scanFolder = async () => {
  if (!subtitleFolder.value) return ElMessage.warning('请先选择字幕文件夹')
  scanning.value = true
  scanResults.value = []
  try {
    const result = await asmrSyncApi.scan(subtitleFolder.value)
    if (result.success) {
      scanResults.value = result.items.map(item => ({ ...item, status: 'pending', previewing: false }))
      ElMessage.success(`发现 ${result.total_found} 个作品`)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '扫描失败')
  } finally {
    scanning.value = false
  }
}

const previewDownload = async (row) => {
  previewLoading.value = true
  previewDialogVisible.value = true
  previewData.value = null
  row.previewing = true
  try {
    const result = await asmrSyncApi.preview(row.rjcode)
    previewData.value = result
    if (!result.success) ElMessage.warning(result.error || '未找到可用版本')
  } catch (error) {
    ElMessage.error('获取预览信息失败')
  } finally {
    previewLoading.value = false
    row.previewing = false
  }
}

const startSync = async () => {
  if (selectedItems.value.length === 0) return ElMessage.warning('请先选择要下载的作品')
  syncing.value = true
  try {
    const items = selectedItems.value.map(item => ({ rjcode: item.rjcode, subtitle_folder: item.folder_path, work_title: item.folder_name }))
    const result = await asmrSyncApi.start(items)
    if (result.success) {
      ElMessage.success(result.message)
      await refreshStatus()
      result.tasks.forEach(task => {
        const item = scanResults.value.find(i => i.rjcode === task.rjcode)
        if (item) { item.status = 'downloading'; item.taskId = task.task_id }
      })
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动下载失败')
  } finally {
    syncing.value = false
  }
}

const handleSelectAll = (val) => {
  selectedItems.value = val ? scanResults.value.filter(item => item.status === 'pending') : []
}

const handleSelectionChange = (selection) => {
  selectedItems.value = selection
  selectAll.value = selection.length === scanResults.value.filter(i => i.status === 'pending').length
}

const refreshStatus = async () => {
  refreshing.value = true
  try {
    const result = await asmrSyncApi.status()
    tasks.value = result.tasks
    result.tasks.forEach(task => {
      const item = scanResults.value.find(i => i.rjcode === task.rjcode)
      if (item) item.status = task.status === 'processing' ? 'downloading' : task.status
    })
  } catch (error) {
    console.error('获取状态失败:', error)
  } finally {
    refreshing.value = false
  }
}

const formatSize = (bytes) => {
  if (!bytes) return '未知'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0, size = bytes
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++ }
  return `${size.toFixed(2)} ${units[i]}`
}

function stopStatusPolling () {
  if (statusInterval) {
    clearInterval(statusInterval)
    statusInterval = null
  }
}

function startStatusPolling () {
  stopStatusPolling()
  statusInterval = setInterval(refreshStatus, 3000)
}

async function initializeASMRSyncPage () {
  if (asmrSyncInitialized) return
  hydrateEnhancedDownloadWorkbenchState()
  await loadSavedFolder()
  await loadWaitingRetryTasks()
  await refreshStatus()
  if (enhancedDownloadWorkbenchTaskIds.value.length) await refreshEnhancedDownloadWorkbench()
  if (subtitleFolder.value) {
    await scanFolder()
  }
  asmrSyncInitialized = true
}

onMounted(async () => {
  await initializeASMRSyncPage()
  asmrSyncViewActive = true
  startStatusPolling()
})

onActivated(async () => {
  if (asmrSyncViewActive) return
  asmrSyncViewActive = true
  await loadWaitingRetryTasks()
  await refreshStatus()
  await loadEnhancedSessions()
  if (enhancedDownloadWorkbenchTaskIds.value.length) refreshEnhancedDownloadWorkbench()
  startStatusPolling()
})

onDeactivated(() => {
  asmrSyncViewActive = false
  stopStatusPolling()
})

onBeforeUnmount(() => {
  stopEnhancedDownloadWorkbenchPolling()
})

onUnmounted(() => {
  asmrSyncViewActive = false
  stopStatusPolling()
  stopEnhancedDownloadWorkbenchPolling()
})

watch(enhancedDownloadWorkbenchVisible, (visible) => {
  persistEnhancedDownloadWorkbenchState()
  if (visible || enhancedDownloadWorkbenchBackgroundActive.value) startEnhancedDownloadWorkbenchPolling()
  else stopEnhancedDownloadWorkbenchPolling()
})

watch(enhancedDownloadWorkbenchBackgroundActive, () => {
  persistEnhancedDownloadWorkbenchState()
  if (enhancedDownloadWorkbenchVisible.value || enhancedDownloadWorkbenchBackgroundActive.value) startEnhancedDownloadWorkbenchPolling()
  else stopEnhancedDownloadWorkbenchPolling()
})

watch(enhancedDownloadWorkbenchTaskIds, () => {
  persistEnhancedDownloadWorkbenchState()
}, { deep: true })
</script>

<style scoped>
/* Minimal overrides — Tailwind handles most styling */
:deep(.el-dialog) {
  border-radius: 16px !important;
}
.enhanced-plan-card {
  max-width: 248px;
}
.enhanced-plan-card :deep(.work-cover-wrapper) {
  aspect-ratio: 1 / 0.82;
}
.enhanced-plan-card :deep(.work-card-body) {
  gap: 6px;
  padding: 10px 10px 12px;
}
.enhanced-plan-card :deep(.work-title) {
  font-size: 12px;
  line-height: 1.45;
}
.enhanced-plan-card :deep(.work-rj) {
  display: none;
}
.enhanced-plan-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.enhanced-plan-meta-pill,
.enhanced-plan-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 800;
  line-height: 1;
  border: 1px solid transparent;
}
.enhanced-plan-meta-pill.is-code {
  color: #4f6b95;
  background: #f8fbff;
  border-color: #d8e6fb;
}
.enhanced-plan-meta-pill.is-downloadable {
  color: #216e56;
  background: #edf9f3;
  border-color: #cbeedd;
}
.enhanced-plan-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: auto;
}
.enhanced-plan-tag.is-primary {
  color: #2b63c8;
  background: #edf4ff;
  border-color: #cadeff;
}
.enhanced-plan-tag.is-soft {
  color: #5d6d81;
  background: #f6f8fb;
  border-color: #e2e8f0;
}
.enhanced-plan-tag.is-muted {
  color: #7b8797;
  background: #fafafa;
  border-color: #e5e7eb;
}
button {
  cursor: pointer;
}
button:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
button:not(:disabled):active {
  transform: translateY(0) scale(0.97);
  box-shadow: none;
}
</style>
