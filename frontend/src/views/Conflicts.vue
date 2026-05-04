<template>
  <div class="h-full flex flex-col bg-slate-50 overflow-hidden">
    <!-- Header -->
    <header class="flex-none px-8 py-6 bg-white border-b border-slate-200/60 flex items-center justify-between z-10">
      <div>
        <h1 class="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-3">
          问题作品
          <span v-if="conflicts.length > 0" class="px-2.5 py-0.5 bg-slate-100 text-slate-600 text-sm font-medium border border-slate-200 rounded-md">
            {{ pendingConflicts.length }} 项待处理
          </span>
          <span v-if="retryingConflicts.length > 0" class="px-2.5 py-0.5 bg-emerald-50 text-emerald-700 text-sm font-medium border border-emerald-200 rounded-md">
            {{ retryingConflicts.length }} 项重试中
          </span>
          <span v-if="processingConflicts.length > 0" class="px-2.5 py-0.5 bg-blue-50 text-blue-600 text-sm font-medium border border-blue-200 rounded-md">
            {{ processingConflicts.length }} 项处理中
          </span>
        </h1>
        <p class="text-sm text-slate-500 mt-1">重复作品以及解压或处理失败作品的集中处理站</p>
      </div>
      <div class="flex items-center gap-4">
        <span v-if="batchRunning" class="text-sm font-medium text-indigo-600 flex items-center gap-2">
          <AppLoadingAnimation variant="inline" :size="32" />
          批量处理中: {{ batchActionLabel }}
        </span>
        <button
          type="button"
          class="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 hover:border-slate-400 hover:bg-slate-50 text-slate-700 text-sm font-medium shadow-sm transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed group rounded-xl"
          :disabled="loading || batchRunning"
          @click="fetchConflicts"
        >
          <RefreshCw class="w-4 h-4 transition-transform duration-500 group-hover:rotate-180" :class="{ 'animate-spin': loading }" />
          刷新列表
        </button>
      </div>
    </header>

    <!-- Error Alert -->
    <div v-if="errorMessage" class="flex-none mx-8 mt-6 p-4 bg-red-50 border border-red-100 flex items-start gap-3 text-red-700 rounded-2xl">
      <AlertCircle class="w-5 h-5 flex-shrink-0 mt-0.5 text-red-500" />
      <div>
        <h3 class="font-medium">获取问题作品失败</h3>
        <p class="text-sm mt-1 opacity-90">{{ errorMessage }}</p>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 min-h-0 p-6 lg:p-8 flex gap-6 overflow-hidden" v-if="!loading || conflicts.length > 0">
      <template v-if="filteredConflicts.length === 0">
        <div class="flex-1 flex flex-col items-center justify-center text-slate-400 bg-white border border-slate-200/60 shadow-sm border-dashed rounded-3xl">
          <CheckCircle2 class="w-16 h-16 mb-4 text-emerald-400" stroke-width="1.5" />
          <p class="text-lg font-medium text-slate-600">{{ conflictFilter === 'processing' ? '当前没有处理中问题项' : '当前没有待处理的问题作品' }}</p>
          <p class="text-sm mt-1">{{ conflictFilter === 'processing' ? '新提交的保留新版或指定密码重试会在这里短暂显示。' : '所有作品都在正常导入或库中已处于良好状态' }}</p>
        </div>
      </template>

      <template v-else>
        <!-- Left List -->
        <aside class="w-[360px] lg:w-[400px] flex-shrink-0 flex flex-col bg-white border border-slate-200/60 shadow-sm overflow-hidden rounded-3xl">
          <div class="p-4 border-b border-slate-100 bg-slate-50/50">
            <div class="flex items-center justify-between mb-3">
              <h3 class="font-medium text-slate-800">待处理列表</h3>
              <span class="text-xs font-medium px-2 py-1 bg-white border border-slate-200 text-slate-500 shadow-sm rounded-md">
                已选 {{ selectedCount }} / {{ filteredConflicts.length }}
              </span>
            </div>
            <div class="flex gap-2 mb-3">
              <button
                v-for="option in filterOptions"
                :key="option.value"
                type="button"
                class="px-3 py-1.5 text-xs font-medium transition-all duration-300 border shadow-sm flex-1 rounded-xl"
                :class="conflictFilter === option.value ? 'bg-indigo-50 border-indigo-200 text-indigo-700' : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-400'"
                @click="conflictFilter = option.value"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="flex flex-wrap gap-2 mb-2">
              <button
                class="px-3 py-1.5 text-xs font-medium transition-all duration-300 border shadow-sm flex-1 group flex items-center justify-center gap-1.5 rounded-xl"
                :class="isAllSelected ? 'bg-indigo-50 border-indigo-200 text-indigo-700 hover:bg-indigo-100' : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-400'"
                :disabled="batchRunning"
                @click="toggleSelectAll"
              >
                <CheckSquare class="w-3.5 h-3.5 transition-transform duration-300 group-hover:scale-110" />
                {{ isAllSelected ? '取消全选' : '全选' }}
              </button>
              <button
                class="px-3 py-1.5 text-xs font-medium bg-white border border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-400 transition-all duration-300 shadow-sm disabled:opacity-50 flex-1 group flex items-center justify-center gap-1.5 rounded-xl"
                :disabled="batchRunning || !selectedCount"
                @click="clearSelection"
              >
                <XSquare class="w-3.5 h-3.5 transition-transform duration-300 group-hover:rotate-90" />
                清空选择
              </button>
            </div>
            <!-- Batch Actions Toolbar -->
            <div v-if="selectedCount > 0" class="flex gap-2 animate-in fade-in slide-in-from-top-2 duration-200">
              <button
                v-if="selectedActionCount('RETRY') > 0"
                class="px-3 py-1.5 text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white border border-emerald-700 transition-all duration-300 shadow-sm disabled:opacity-50 flex-1 flex items-center justify-center gap-1.5 group rounded-xl"
                :disabled="batchRunning"
                @click="handleBatchRetry"
              >
                <RotateCcw class="w-3.5 h-3.5 transition-transform duration-300 group-hover:-rotate-90" />
                一键重试
              </button>
              <button
                v-if="selectedActionCount('SKIP') > 0"
                class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-900 text-white border border-slate-900 transition-all duration-300 shadow-sm disabled:opacity-50 flex-1 flex items-center justify-center gap-1.5 group rounded-xl"
                :disabled="batchRunning"
                @click="handleBatchSkip"
              >
                <SkipForward class="w-3.5 h-3.5 transition-transform duration-300 group-hover:translate-x-1" />
                批量跳过
              </button>
            </div>
            <p class="text-[11px] text-slate-400 mt-2 text-center">单击聚焦，Ctrl/⌘ 多选，Shift 连选</p>
          </div>

          <div class="flex-1 overflow-y-auto p-3 space-y-2 no-scrollbar">
            <button
              v-for="conflict in filteredConflicts"
              :key="conflict.id"
              :disabled="isConflictRetrying(conflict)"
              class="w-full text-left p-3.5 border transition-all duration-300 relative group overflow-hidden rounded-2xl"
              :class="[
                isConflictSelected(conflict.id)
                  ? 'bg-indigo-50/50 border-indigo-300 shadow-sm ring-1 ring-indigo-500/20'
                  : 'bg-white border-slate-200 hover:border-indigo-400 hover:shadow-md hover:-translate-y-0.5',
                conflict.id === activeConflictId ? 'before:absolute before:left-0 before:top-0 before:bottom-0 before:w-1 before:bg-indigo-500 pl-4.5' : '',
                isConflictProcessing(conflict) ? 'processing-conflict-card' : '',
                isConflictRetrying(conflict) ? 'retry-conflict-card' : ''
              ]"
              @click="handleConflictCardClick(conflict, $event)"
            >
              <span v-if="isConflictRetrying(conflict)" class="retry-card-orbit" aria-hidden="true">
                <RotateCcw class="w-3.5 h-3.5" />
              </span>
              <div class="flex items-center justify-between gap-3 mb-2" :class="conflict.id === activeConflictId ? 'pl-2' : ''">
                <strong class="text-sm font-bold text-slate-800 tracking-tight truncate flex items-center gap-1">
                  {{ conflict.rjcode || conflict.new_metadata?.work_name || conflict.new_path || '未识别项目' }}
                  <ChevronRight class="w-3.5 h-3.5 opacity-0 -translate-x-2 transition-all duration-300 group-hover:opacity-100 group-hover:translate-x-0 text-indigo-500" />
                </strong>
                <span
                  class="shrink-0 px-1.5 py-0.5 flex items-center gap-1 text-[10px] font-medium border rounded-md"
                  :class="conflict.context?.existing?.is_remote ? 'bg-amber-50 text-amber-600 border-amber-200/60' : 'bg-slate-100 text-slate-500 border-slate-200'"
                >
                  <Cloud v-if="conflict.context?.existing?.is_remote" class="w-3 h-3" />
                  <HardDrive v-else class="w-3 h-3" />
                  {{ conflict.context?.existing?.is_remote ? '远程' : '本地' }}
                </span>
              </div>
              <div class="flex items-center justify-between mt-1 text-xs" :class="conflict.id === activeConflictId ? 'pl-2' : ''">
                <span class="text-slate-500 flex items-center gap-1.5 font-medium">
                  <FileWarning v-if="isFailureConflict(conflict)" class="w-3.5 h-3.5 text-red-400" />
                  <Copy v-else class="w-3.5 h-3.5 text-indigo-400" />
                  {{ getConflictTypeLabel(conflict.conflict_type) }}
                </span>
                <div class="flex items-center gap-2">
                  <span
                    class="px-1.5 py-0.5 text-[10px] font-semibold border rounded-md"
                    :class="getConflictStatusClass(conflict)"
                  >
                    {{ getConflictStatusLabel(conflict) }}
                  </span>
                  <span class="text-slate-400">{{ formatDate(conflict.created_at).split(' ')[0] }}</span>
                </div>
              </div>
              <div v-if="isConflictRetrying(conflict)" class="mt-2 flex items-center gap-2" :class="conflict.id === activeConflictId ? 'pl-2' : ''">
                <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-emerald-100">
                  <div class="h-full rounded-full bg-gradient-to-r from-emerald-400 to-teal-500 transition-all duration-700" :style="{ width: `${getConflictRetryProgress(conflict)}%` }" />
                </div>
                <span class="text-[10px] font-bold tabular-nums text-emerald-700">{{ getConflictRetryProgress(conflict) }}%</span>
              </div>
            </button>
          </div>
        </aside>

        <!-- Right Detail -->
        <section class="flex-1 flex flex-col bg-white border border-slate-200/60 shadow-sm overflow-hidden rounded-3xl" v-if="activeConflict">
          <!-- Detail Header -->
          <div class="p-6 border-b border-slate-100 bg-gradient-to-br from-slate-50 to-white relative overflow-hidden flex-shrink-0">
            <div class="absolute -top-4 -right-4 p-8 opacity-5 pointer-events-none">
              <FileWarning v-if="isFailureConflict(activeConflict)" class="w-64 h-64" />
              <Copy v-else class="w-64 h-64" />
            </div>
            <div class="relative z-10 flex flex-col xl:flex-row justify-between gap-6 items-start xl:items-center">
              <div>
                <div class="flex items-center gap-3 mb-2">
                  <h2 class="text-2xl font-bold text-slate-900 tracking-tight">{{ activeConflict.rjcode || '未识别项目' }}</h2>
                  <span v-if="isConflictSelected(activeConflict.id)" class="px-2 py-1 bg-indigo-100 text-indigo-700 text-xs font-semibold border border-indigo-200 rounded-md">
                    已选入批量
                  </span>
                </div>
                <p class="text-slate-500 flex items-center gap-2 text-sm font-medium">
                  <span class="inline-flex w-2 h-2 rounded-full" :class="isFailureConflict(activeConflict) ? 'bg-red-400' : 'bg-indigo-400'"></span>
                  {{ getConflictTypeLabel(activeConflict.conflict_type) }}
                </p>
              </div>

              <div class="flex flex-wrap gap-3">
                <button
                  v-if="canUseAction(activeConflict, 'KEEP_NEW')"
                  class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium shadow-sm transition-all duration-300 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed group rounded-xl"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id)"
                  @click="handleKeepNew(activeConflict)"
                >
                  <AppLoadingAnimation v-if="isActionLoading(activeConflict.id, 'KEEP_NEW')" variant="inline" :size="32" />
                  <Save v-else class="w-4 h-4 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:scale-110" />
                  {{ isActionLoading(activeConflict.id, 'KEEP_NEW') ? '保留新版中' : '保留新版' }}
                </button>
                <button
                  v-if="canUseAction(activeConflict, 'RETRY')"
                  class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium shadow-sm transition-all duration-300 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed group rounded-xl"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id)"
                  @click="handleRetry(activeConflict)"
                >
                  <AppLoadingAnimation v-if="isConflictRetrying(activeConflict)" variant="inline" :size="32" />
                  <RotateCcw v-else class="w-4 h-4 transition-transform duration-300 group-hover:-rotate-90" />
                  {{ isConflictRetrying(activeConflict) ? '重试中' : '重试' }}
                </button>
                <button
                  v-if="canUseAction(activeConflict, 'SKIP')"
                  class="px-4 py-2 bg-slate-800 hover:bg-slate-900 text-white text-sm font-medium shadow-sm transition-all duration-300 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed group rounded-xl"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id)"
                  @click="handleSkip(activeConflict)"
                >
                  <AppLoadingAnimation v-if="isActionLoading(activeConflict.id, 'SKIP')" variant="inline" :size="32" />
                  <SkipForward v-else class="w-4 h-4 transition-transform duration-300 group-hover:translate-x-1" />
                  跳过
                </button>
                <button
                  v-if="canUseAction(activeConflict, 'MERGE')"
                  class="px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white text-sm font-medium shadow-sm transition-all duration-300 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed group rounded-xl"
                  :disabled="batchRunning || isConflictBusy(activeConflict.id)"
                  @click="openMergeWorkbench(activeConflict)"
                >
                  <AppLoadingAnimation v-if="mergeLoading && mergeConflictId === activeConflict.id" variant="inline" :size="32" />
                  <GitMerge v-else class="w-4 h-4 transition-transform duration-300 group-hover:rotate-12 group-hover:scale-110" />
                  合并
                </button>
              </div>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto p-6 no-scrollbar bg-slate-50/30">
            <!-- Alert for failure conflicts -->
            <div
              v-if="isFailureConflict(activeConflict)"
              class="mb-6 p-4 flex items-start gap-3 border shadow-sm rounded-2xl"
              :class="isExtractFailed(activeConflict) ? 'bg-amber-50 border-amber-200 text-amber-800' : 'bg-red-50 border-red-200 text-red-800'"
            >
              <AlertTriangle class="w-5 h-5 flex-shrink-0 mt-0.5" :class="isExtractFailed(activeConflict) ? 'text-amber-500' : 'text-red-500'" />
              <div>
                <h4 class="font-bold mb-1">
                  {{ isExtractFailed(activeConflict) ? '解压阶段失败，非重复冲突' : '处理中途失败，非重复冲突' }}
                </h4>
                <p class="text-sm opacity-90 leading-relaxed">
                  {{ activeConflict.new_metadata?.error_message || (isExtractFailed(activeConflict) ? '请检查密码、分卷完整性或压缩包本身是否损坏。' : '请按失败原因修复后重试。') }}
                </p>
              </div>
            </div>

            <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <!-- Source Card -->
              <div class="bg-white border border-slate-200/80 overflow-hidden shadow-sm flex flex-col rounded-2xl">
                <div class="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
                  <FolderOpen class="w-4 h-4 text-slate-400" />
                  <h3 class="font-bold text-slate-700 text-sm">{{ isFailureConflict(activeConflict) ? '失败来源' : '当前新内容' }}</h3>
                </div>
                <div class="p-5 space-y-4 flex-1">
                  <div>
                    <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">来源路径</span>
                    <div class="bg-slate-50 border border-slate-100 p-3 text-xs text-slate-700 font-mono break-all leading-relaxed max-h-32 overflow-y-auto no-scrollbar rounded-xl">
                      {{ getConflictSourcePath(activeConflict) }}
                    </div>
                  </div>
                  
                  <div class="grid grid-cols-2 gap-4">
                    <div>
                      <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">类型</span>
                      <p class="text-sm text-slate-800 font-medium">{{ activeConflict.context?.new_path_kind === 'archive' ? '压缩包' : '目录' }}</p>
                    </div>
                    <div>
                      <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">大小</span>
                      <p class="text-sm text-slate-800 font-medium">{{ formatFileSize(activeConflict.context?.source?.stats?.size) }}</p>
                    </div>
                  </div>
                  
                  <div>
                    <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">创建时间</span>
                    <p class="text-sm text-slate-600">{{ formatTimestamp(activeConflict.context?.source?.stats?.created_at) }}</p>
                  </div>

                  <div v-if="activeConflict.new_metadata" class="pt-3 border-t border-slate-100">
                    <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">
                      {{ isFailureConflict(activeConflict) ? '附带信息' : '作品信息' }}
                    </span>
                    <div class="space-y-2">
                      <div class="flex items-start gap-2 text-sm" v-if="activeConflict.new_metadata.work_name">
                        <span class="text-slate-500 min-w-[40px]">名称:</span>
                        <span class="text-slate-800 font-medium break-all">{{ activeConflict.new_metadata.work_name }}</span>
                      </div>
                      <div class="flex items-start gap-2 text-sm" v-if="activeConflict.new_metadata.maker_name">
                        <span class="text-slate-500 min-w-[40px]">社团:</span>
                        <span class="text-slate-800">{{ activeConflict.new_metadata.maker_name }}</span>
                      </div>
                      <div class="flex items-start gap-2 text-sm" v-if="activeConflict.new_metadata.cvs?.length">
                        <span class="text-slate-500 min-w-[40px]">声优:</span>
                        <span class="text-slate-800">{{ activeConflict.new_metadata.cvs.join(' / ') }}</span>
                      </div>
                    </div>
                  </div>
                  
                  <div v-if="activeConflict.new_metadata?.error_message" class="pt-3 border-t border-slate-100">
                    <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">失败原因</span>
                    <p class="text-sm text-red-600 font-medium">{{ activeConflict.new_metadata.error_message }}</p>
                  </div>
                </div>
              </div>

              <!-- Target Card -->
              <div class="bg-white border border-slate-200/80 overflow-hidden shadow-sm flex flex-col rounded-2xl">
                <div class="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
                  <Archive class="w-4 h-4 text-slate-400" />
                  <h3 class="font-bold text-slate-700 text-sm">{{ isFailureConflict(activeConflict) ? '处理建议' : '已存在目录' }}</h3>
                </div>
                <div class="p-5 space-y-4 flex-1">
                  <div>
                    <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                      {{ isFailureConflict(activeConflict) ? '建议动作' : '目标路径' }}
                    </span>
                    <div v-if="!isFailureConflict(activeConflict)" class="bg-indigo-50/50 border border-indigo-100 p-3 text-xs text-indigo-900 font-mono break-all leading-relaxed max-h-32 overflow-y-auto no-scrollbar rounded-xl">
                      {{ getExistingConflictPath(activeConflict) }}
                    </div>
                    <p v-else class="text-sm text-slate-700 leading-relaxed bg-slate-50 p-3 border border-slate-200 rounded-xl">
                      {{ isExtractFailed(activeConflict) ? '可直接跳过并删除当前失败来源；如果你已经补充了正确密码或完整分卷，建议回到任务列表重新处理。' : '可先根据失败原因修复来源内容后重试；如果确认不再处理，也可以直接跳过删除当前失败来源。' }}
                    </p>
                  </div>

                  <div v-if="!isFailureConflict(activeConflict)" class="grid grid-cols-2 gap-4">
                    <div>
                      <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">落地位置</span>
                      <p class="text-sm text-slate-800 font-medium flex items-center gap-1.5">
                        {{ activeConflict.context?.existing?.library_name || '默认库存' }}
                        <span class="text-[10px] px-1.5 py-0.5 bg-slate-100 text-slate-500 border border-slate-200 rounded-md">{{ activeConflict.context?.existing?.is_remote ? '远程' : '本地' }}</span>
                      </p>
                    </div>
                    <div>
                      <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">大小</span>
                      <p class="text-sm text-slate-800 font-medium">{{ formatFileSize(activeConflict.context?.existing?.stats?.size) }}</p>
                    </div>
                  </div>

                  <div class="pt-3 border-t border-slate-100 grid grid-cols-2 gap-4">
                    <div>
                      <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">
                        {{ isFailureConflict(activeConflict) ? '记录时间' : '检测时间' }}
                      </span>
                      <p class="text-sm text-slate-600">{{ formatDate(activeConflict.created_at) }}</p>
                    </div>
                    <div v-if="!isFailureConflict(activeConflict)">
                      <span class="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">目标创建时间</span>
                      <p class="text-sm text-slate-600">{{ formatTimestamp(activeConflict.context?.existing?.stats?.created_at) }}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Help Card -->
            <div class="mt-6 bg-white border border-slate-200/80 p-5 shadow-sm rounded-2xl">
              <h4 class="flex items-center gap-2 text-sm font-bold text-slate-700 mb-3">
                <Info class="w-4 h-4 text-slate-400" />
                {{ isFailureConflict(activeConflict) ? '失败说明' : '动作说明' }}
              </h4>
              <ul v-if="!isFailureConflict(activeConflict)" class="space-y-2 text-sm text-slate-600 list-disc list-inside marker:text-slate-400 ml-1">
                <li><strong class="text-slate-800">保留新版：</strong>先经过删除审查，再安全替换已有目录，失败时走最小化破坏路径。</li>
                <li><strong class="text-slate-800">跳过：</strong>不解压，直接删除当前压缩包或待处理目录，原有目录保持不变。</li>
                <li><strong class="text-slate-800">合并：</strong>进入组件文件夹对比视图，逐文件决定保留新文件、旧文件或删除。</li>
              </ul>
              <ul v-else class="space-y-2 text-sm text-slate-600 list-disc list-inside marker:text-slate-400 ml-1">
                <li>{{ isExtractFailed(activeConflict) ? '当前问题发生在解压阶段，不代表库存中已经有重复作品。' : '当前问题发生在导入处理链路中，不代表库存中已经有重复作品。' }}</li>
                <li>{{ isExtractFailed(activeConflict) ? '如果错误是密码不正确、分卷缺失或压缩包损坏，修复后重新处理通常更合适。' : '如果错误发生在元数据、重命名、过滤或分类阶段，优先按当前失败原因排查对应链路。' }}</li>
                <li>如果确认不再处理这个包，可以直接点击“跳过”删除失败来源。</li>
              </ul>
            </div>
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
      :submitting="mergeSubmitting"
      @update:decisions="handleDecisionUpdate"
      @refresh="refreshMergePreview"
      @submit="submitMerge"
    />

    <BatchRetryPasswordDialog
      v-model="batchRetryDialogVisible"
      :conflicts="batchRetryTargets"
      @confirm="handleBatchRetryConfirm"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  RefreshCw, AlertCircle, CheckCircle2, Cloud, HardDrive,
  FileWarning, Copy, Save, RotateCcw, SkipForward,
  GitMerge, AlertTriangle, FolderOpen, Archive, Info,
  CheckSquare, XSquare, ChevronRight
} from 'lucide-vue-next'
import ConflictMergeWorkbench from '../components/conflicts/ConflictMergeWorkbench.vue'
import BatchRetryPasswordDialog from '../components/conflicts/BatchRetryPasswordDialog.vue'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import { conflictApi, taskCenterApi } from '../api'
import { showSystemAlert, showSystemConfirm, showSystemPrompt } from '../composables/useSystemPrompt'

const ACTIVE_CONFLICT_STORAGE_KEY = 'prekikoeru-conflicts-active-id'

const conflicts = ref([])
const loading = ref(false)
const errorMessage = ref('')
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
const conflictFilter = ref('all')
const retryPollers = new Map()
const localRetryingConflictIds = reactive({})

const batchRetryDialogVisible = ref(false)
const batchRetryTargets = ref([])

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
})

onUnmounted(() => {
  for (const timerId of retryPollers.values()) {
    clearTimeout(timerId)
  }
  retryPollers.clear()
  for (const key of Object.keys(localRetryingConflictIds)) {
    delete localRetryingConflictIds[key]
  }
})


async function fetchConflicts() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await conflictApi.list()
    conflicts.value = data.conflicts || []
    syncSelectedConflicts()
    syncActiveConflict()
  } catch (error) {
    console.error('获取问题作品失败:', error)
    errorMessage.value = resolveErrorMessage(error, '获取问题作品失败')
  } finally {
    loading.value = false
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

function isConflictProcessing(conflict) {
  return String(conflict?.status || '').trim().toUpperCase() === 'PROCESSING'
}

function isRetryProcessing(conflict) {
  return isConflictProcessing(conflict) && isRetryConflict(conflict)
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
  return String(metadata.resolution_action || metadata.conflict_resolution_action || '').trim().toUpperCase() === 'RETRY' ||
    Boolean(metadata.retry_from_conflicts || metadata.retry_conflict_id || metadata.retry_task_id || metadata.resolution_task_id)
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

function getConflictRetryProgress(conflict) {
  const value = Number(conflict?.linked_task?.progress ?? conflict?.new_metadata?.resolution_progress ?? 0)
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

function getConflictStatusLabel(conflict) {
  if (isConflictRetrying(conflict)) return '重试中'
  if (isConflictProcessing(conflict)) return '处理中'
  return '待处理'
}

function getConflictStatusClass(conflict) {
  if (isConflictRetrying(conflict)) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (isConflictProcessing(conflict)) return 'bg-blue-50 text-blue-600 border-blue-200'
  return 'bg-slate-100 text-slate-500 border-slate-200'
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

  const poll = async () => {
    attempts++
    try {
      const task = await taskCenterApi.getItem({ engine_task_id: taskId })
      if (task) {
        if (task.status === 'completed') {
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
        if (task.status === 'failed') {
          retryPollers.delete(taskId)
          markConflictRetrying(conflictId, false)
          await fetchConflicts()
          ElMessage.warning(task.error_message ? `重试失败：${task.error_message}` : '重试失败，请查看任务详情')
          return
        }
      }
      if (attempts % 4 === 0) {
        await fetchConflicts()
      }
    } catch (_) {
    }
    if (attempts < maxAttempts && retryPollers.has(taskId)) {
      const timerId = setTimeout(poll, 5000)
      retryPollers.set(taskId, timerId)
    } else {
      retryPollers.delete(taskId)
      markConflictRetrying(conflictId, false)
      await fetchConflicts()
    }
  }

  const timerId = setTimeout(poll, 3000)
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
  const titleLabel = isBatch
    ? `批量重试 ${batchCount} 个问题项`
    : `重试 ${conflict.rjcode || '当前问题项'}`
  const messageText = isBatch
    ? `可选：指定一个密码用于全部 ${batchCount} 项重试。如各项需要不同密码，请关闭后单独逐项重试。留空则各项按原逻辑走密码库、RJ 推导和默认密码。`
    : '可选：指定一个密码只用这一条来重试；直接明文输入，留空则按原逻辑继续走密码库、RJ 推导和默认密码。'
  try {
    const value = await showSystemPrompt({
      title: titleLabel,
      message: messageText,
      confirmText: isBatch ? `开始批量重试 (${batchCount} 项)` : '开始重试',
      cancelText: '取消',
      inputType: 'text',
      placeholder: '直接输入明文密码；留空表示正常重试',
      closeOnClickModal: false
    })
    return {
      cancelled: false,
      password: String(value || '').trim(),
    }
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return { cancelled: true, password: '' }
    }
    throw error
  }
}

async function getMergePreview(conflict, forceRefresh = false) {
  let preview = mergePreviewCache[conflict.id]
  if (!preview || forceRefresh) {
    preview = await conflictApi.preview(conflict.id, 'MERGE')
    mergePreviewCache[conflict.id] = preview
  }
  return preview
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
    const result = await startRetry(conflict, retryInput.password ? { password: retryInput.password } : {})
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

async function openMergeWorkbench(conflict, forceRefresh = false) {
  mergeConflictId.value = conflict.id
  mergeDialogVisible.value = true
  mergeLoading.value = true
  try {
    const preview = await getMergePreview(conflict, forceRefresh)
    mergePreview.value = preview
    mergeDecisions.value = {
      ...(mergeDecisionCache[conflict.id] || preview.default_decisions || {})
    }
  } catch (error) {
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
    LINKED_WORK: '关联作品',
    EXTRACT_FAILED: '解压失败',
    PROCESS_FAILED: '处理失败'
  }[type] || type || '未知冲突'
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
</script>

<style scoped>
button:not(:disabled) {
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
}

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
  border-radius: 18px;
  pointer-events: none;
  box-shadow:
    0 0 0 1px rgba(134, 239, 172, 0.28),
    0 0 22px rgba(74, 222, 128, 0.22),
    0 0 42px rgba(34, 197, 94, 0.18);
  opacity: 0.78;
  animation: processing-conflict-aura 1.9s ease-in-out infinite;
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
