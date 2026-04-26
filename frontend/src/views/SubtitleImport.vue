<template>
  <div class="flex flex-col gap-4 min-h-full pb-8 subtitle-import-page">
    <div class="flex items-center gap-3 flex-wrap">
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          <h1 class="text-xl font-bold tracking-tight text-slate-900">字幕补配</h1>
          <span v-if="pendingItems.length" class="inline-flex items-center px-2 py-0.5 rounded-[6px] bg-slate-100 text-slate-600 text-[10.5px] font-semibold border border-slate-200">{{ pendingItems.length }} 待处理</span>
          <span v-if="(workbenchBackgroundSummary.processing||0)>0" class="inline-flex items-center gap-1 px-2 py-0.5 rounded-[6px] bg-slate-100 text-slate-600 text-[10.5px] font-semibold border border-slate-200"><span class="w-1.5 h-1.5 bg-slate-500 rounded-full animate-pulse"></span>{{ workbenchBackgroundSummary.processing }} 进行中</span>
          <span v-if="workbenchBackgroundSummary.total" class="text-[10.5px] text-slate-400 font-medium">累计 {{ workbenchBackgroundSummary.total }} 次</span>
        </div>
        <p class="text-[11.5px] text-slate-400 mt-0.5 max-w-xl">自动检测的压缩包来源进入预检单；手动字幕目录也可以在这里补进库存。</p>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <button class="h-8 px-3.5 rounded-[8px] text-[12.5px] font-semibold bg-slate-900 hover:bg-slate-800 text-white transition-all hover:-translate-y-0.5 active:scale-95 shadow-sm" @click="openImportWorkbench()">打开工作台</button>
        <button class="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-[8px] text-[12.5px] font-medium border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 transition-all hover:-translate-y-0.5 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed" :disabled="pendingLoading" @click="loadPendingImports">
          <span v-if="pendingLoading" class="animate-spin w-3 h-3 border-2 border-slate-300 border-t-slate-600 rounded-full"></span>刷新
        </button>
      </div>
    </div>

    <div v-show="!workbenchDialogVisible" class="flex flex-col gap-3">
      <div class="inline-flex gap-0.5 p-0.5 rounded-[10px] bg-slate-100 border border-slate-200 self-start">
        <button type="button" class="h-8 px-4 rounded-[7px] text-[12.5px] font-semibold transition-all" :class="activeTab==='archive' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'" @click="activeTab='archive'">压缩包补配</button>
        <button type="button" class="h-8 px-4 rounded-[7px] text-[12.5px] font-semibold transition-all" :class="activeTab==='folder' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'" @click="activeTab='folder'">字幕文件夹补配</button>
      </div>

      <div v-if="activeTab==='archive'" class="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-4 items-start">
        <div class="flex flex-col rounded-2xl border border-slate-200 bg-white overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-100 bg-slate-50/60 flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-[12.5px] font-bold text-slate-800 truncate">预检单</span>
              <span class="px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-500 text-[10px] font-semibold flex-shrink-0">{{ pendingItems.length }}</span>
            </div>
            <div class="flex items-center gap-1.5 flex-shrink-0">
              <button class="px-2.5 py-1 text-[11px] font-medium rounded-lg border border-rose-200 text-rose-600 hover:bg-rose-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="!activePendingItem||pendingClearLoading" @click="clearPendingImports(false)">清除当前</button>
              <button class="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-rose-500 text-white hover:bg-rose-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" :disabled="!pendingItems.length||pendingClearLoading" @click="clearPendingImports(true)">清空</button>
            </div>
          </div>
          <div class="flex-1 flex flex-col min-h-[300px] max-h-[600px] overflow-y-auto">
            <AppEmptyState v-if="pendingLoadedOnce&&!pendingItems.length" description="没有待处理的预检单" size="sm" class="my-auto py-10" />
            <div v-else class="p-2 flex flex-col gap-1">
              <button v-for="item in pendingItems" :key="item.id" type="button" class="w-full text-left px-3 py-2.5 rounded-[10px] border transition-all" :class="item.id===activePendingId ? 'border-slate-300 bg-slate-50 ring-1 ring-slate-300/30' : 'border-transparent hover:border-slate-200 hover:bg-slate-50'" @click="activePendingId=item.id">
                <div class="flex items-center gap-1.5 mb-0.5">
                  <span class="text-[12.5px] font-bold text-slate-800 truncate flex-1">{{ getDisplayRJCode(item.preview?.target_rjcode||item.preview?.source_rjcode)||'未识别 RJ' }}</span>
                  <span class="text-[9.5px] font-semibold px-1.5 py-0.5 rounded flex-shrink-0" :class="item.can_execute ? 'bg-slate-100 text-slate-600' : 'bg-slate-100 text-slate-500'">{{ item.can_execute ? '可执行' : '仅查看' }}</span>
                </div>
                <div class="text-[11px] text-slate-500 truncate">{{ item.preview?.source_label||getFileName(item.source_path) }}</div>
                <div class="flex items-center gap-2 mt-1 text-[10px] text-slate-400">
                  <span>{{ getDisplayRJCode(item.preview?.source_rjcode)||'-' }} → {{ getDisplayRJCode(item.preview?.target_rjcode)||'-' }}</span>
                  <span class="ml-auto">{{ item.preview?.subtitle_count??0 }} 字幕</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        <div class="flex flex-col rounded-2xl border border-slate-200 bg-white overflow-hidden">
          <AppEmptyState v-if="!activePendingItem" description="从左侧选择一条预检单" size="sm" class="py-24" />
          <template v-else>
            <div class="px-4 py-3 border-b border-slate-100 bg-slate-50/60 flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span class="text-[13px] font-bold text-slate-800">{{ getDisplayRJCode(activePendingItem.preview?.target_rjcode||activePendingItem.preview?.source_rjcode)||'预检结果' }}</span>
                <span class="text-[11.5px] text-slate-400">{{ activePendingItem.preview?.source_label }}</span>
              </div>
              <div class="flex items-center gap-2">
                <button v-if="canRetryActivePendingPreview" class="text-[11px] font-medium text-slate-600 hover:bg-slate-100 px-2.5 py-1 rounded-[7px] transition-all disabled:opacity-50" :disabled="retryingPendingId===activePendingItem.id" @click="retryActivePendingPreview">重试搜索</button>
                <span class="inline-flex px-2.5 py-1 rounded-[7px] text-[10.5px] font-semibold border" :class="activePendingItem.can_execute ? 'bg-slate-100 text-slate-700 border-slate-200' : 'bg-white text-slate-500 border-slate-200'">{{ activePendingItem.can_execute ? '可以补配' : '不可执行' }}</span>
              </div>
            </div>
            <div :key="activePendingItem.id" class="p-4 flex flex-col gap-4">
              <div class="flex items-start gap-2.5 px-3 py-2.5 rounded-[10px] border text-[11.5px] leading-relaxed" :class="activePendingItem.can_execute ? 'border-slate-200 bg-slate-50 text-slate-700' : 'border-amber-200 bg-amber-50 text-amber-800'">
                <svg v-if="activePendingItem.can_execute" class="flex-shrink-0 mt-0.5" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg>
                <svg v-else class="flex-shrink-0 mt-0.5" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                {{ activePendingItem.preview?.reason||(activePendingItem.can_execute ? '目标原作已定位，可以继续导入。' : '当前这条来源暂时无法执行。') }}
              </div>
              <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <div class="px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">来源 RJ</span><span class="text-[12.5px] font-bold text-slate-800 font-mono">{{ getDisplayRJCode(activePendingItem.preview?.source_rjcode)||'-' }}</span></div>
                <div class="px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">目标 RJ</span><span class="text-[12.5px] font-bold text-slate-900 font-mono">{{ getDisplayRJCode(activePendingItem.preview?.target_rjcode)||'-' }}</span></div>
                <div class="px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">字幕数</span><span class="text-[12.5px] font-bold text-slate-800">{{ activePendingItem.preview?.subtitle_count??0 }}</span></div>
                <div class="px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">Kikoeru</span><span class="text-[12.5px] font-bold text-slate-700">{{ activePendingItem.preview?.kikoeru_has_work ? '已命中' : '未命中' }}</span></div>
                <div class="col-span-2 px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">预检时间</span><span class="text-[11px] font-semibold text-slate-700">{{ formatDate(activePendingItem.created_at) }}</span></div>
              </div>
              <div v-if="activePendingItem.preview?.subtitle_entries?.length" class="flex flex-col gap-1.5">
                <div class="flex items-center gap-1.5"><span class="text-[11px] font-bold text-slate-700">字幕候选文件树</span><span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 text-[9.5px]">{{ activePendingItem.preview.subtitle_entries.length }}</span></div>
                <div class="grid grid-cols-1 xl:grid-cols-2 gap-2">
                  <div v-for="node in buildSubtitleEntryTreeRows(activePendingItem.preview.subtitle_entries)" :key="node.key" class="flex items-center gap-2 min-w-0 rounded-[8px] border border-slate-100 bg-slate-50 px-2.5 py-1.5 text-[11px] text-slate-700">
                    <span class="shrink-0 text-slate-300 font-mono" :style="{ width: `${node.depth * 14}px` }"></span>
                    <span class="shrink-0 text-slate-400">{{ node.isDir ? '▸' : '└' }}</span>
                    <span class="truncate" :class="node.isDir ? 'font-semibold text-slate-800' : 'font-medium text-slate-600'">{{ node.name }}</span>
                  </div>
                </div>
              </div>
              <div class="flex flex-col gap-2">
                <div class="flex items-center justify-between"><span class="text-[11px] font-bold text-slate-700">目标目录候选</span><span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[9.5px] font-bold">{{ activePendingItem.preview?.candidate_count??0 }} 个</span></div>
                <AppEmptyState v-if="!activePendingItem.preview?.candidates?.length" description="没有可用的目标目录候选" size="sm" />
                <div v-else class="flex flex-col gap-1.5">
                  <div v-for="candidate in activePendingItem.preview.candidates" :key="candidateKey(candidate)" class="flex items-start gap-3 p-3 rounded-[10px] border cursor-pointer transition-all" :class="archiveCandidateSelection[activePendingItem.id]===candidateKey(candidate) ? 'border-slate-400 bg-slate-50 ring-1 ring-slate-300/30' : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'" @click="archiveCandidateSelection[activePendingItem.id]=candidateKey(candidate)">
                    <div class="w-3.5 h-3.5 rounded-[4px] border-2 flex-shrink-0 mt-0.5 flex items-center justify-center" :class="archiveCandidateSelection[activePendingItem.id]===candidateKey(candidate) ? 'border-slate-900 bg-slate-900' : 'border-slate-300'"><div v-if="archiveCandidateSelection[activePendingItem.id]===candidateKey(candidate)" class="w-1.5 h-1.5 rounded-[2px] bg-white"></div></div>
                    <div class="flex-1 min-w-0">
                      <div class="text-[12.5px] font-bold text-slate-800 truncate">{{ candidate.folder_name||candidate.folder_path }}</div>
                      <div class="flex flex-wrap gap-1.5 mt-1.5">
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">{{ candidate.library_name }}</span>
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">{{ candidate.library_type==='synology_filestation' ? '远程' : '本地' }}</span>
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">音频 {{ candidate.audio_count??0 }}</span>
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">字幕 {{ candidate.existing_subtitle_count??0 }}</span>
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">{{ formatSize(candidate.total_size) }}</span>
                      </div>
                      <div class="text-[9.5px] text-slate-400 mt-1 font-mono truncate">{{ candidate.folder_path }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <div class="flex justify-end pt-1">
                <button class="inline-flex items-center gap-2 h-8 px-5 bg-slate-900 hover:bg-slate-800 text-white text-[12.5px] font-bold rounded-[8px] shadow-sm transition-all hover:-translate-y-0.5 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0" :disabled="!activePendingItem.can_execute||!selectedArchiveCandidate||executingPendingId===activePendingItem.id" @click="executePendingImport()">
                  <span v-if="executingPendingId===activePendingItem.id" class="animate-spin w-3 h-3 border-2 border-white/40 border-t-white rounded-full"></span>
                  导入并加入工作台
                </button>
              </div>
            </div>
          </template>
        </div>
      </div>

      <div v-if="activeTab==='folder'" class="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-4 items-start">
        <div class="flex flex-col rounded-2xl border border-slate-200 bg-white overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-100 bg-slate-50/60 flex items-center justify-between">
            <span class="text-[12.5px] font-bold text-slate-800">手动字幕来源</span>
            <span class="px-2 py-0.5 rounded bg-amber-50 text-amber-700 text-[10px] font-semibold border border-amber-100">手动</span>
          </div>
          <div class="p-4 flex flex-col gap-3">
            <div>
              <label class="block text-[11.5px] font-bold text-slate-600 mb-1">字幕文件夹路径</label>
              <div class="relative">
                <input type="text" v-model="folderPath" class="w-full h-9 px-3 pr-8 bg-slate-50 border border-slate-200 rounded-[8px] text-[12.5px] text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:border-slate-300 focus:bg-white transition-all placeholder:text-slate-400" placeholder="例如 D:\Temp\RJ123456" @keyup.enter="previewFolderImport" />
                <button v-if="folderPath" class="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600" @click="folderPath=''"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg></button>
              </div>
            </div>
            <div class="flex gap-2">
              <button class="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-[8px] text-[12px] font-semibold border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 transition-all active:scale-95 disabled:opacity-50" :disabled="folderPreviewLoading" @click="previewFolderImport">
                <span v-if="folderPreviewLoading" class="animate-spin w-3 h-3 border-2 border-slate-300 border-t-slate-600 rounded-full"></span>预检
              </button>
              <button class="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-[8px] text-[12px] font-bold bg-slate-900 hover:bg-slate-800 text-white transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm" :disabled="!canExecuteFolderImport||folderImporting" @click="executeFolderImport">
                <span v-if="folderImporting" class="animate-spin w-3 h-3 border-2 border-white/40 border-t-white rounded-full"></span>导入
              </button>
            </div>
            <div class="p-3 rounded-[10px] bg-slate-50 border border-slate-200 text-[11px] text-slate-600 leading-relaxed">手头有字幕目录时，直接补进原作目录，再进库存页做筛选、配对和应用。</div>
          </div>
        </div>

        <div class="flex flex-col rounded-2xl border border-slate-200 bg-white overflow-hidden">
          <AppEmptyState v-if="!folderPreview&&!folderPreviewLoading" description="输入字幕文件夹路径后做一次预检" size="sm" class="py-24" />
          <template v-else-if="folderPreview">
            <div class="px-4 py-3 border-b border-slate-100 bg-slate-50/60 flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span class="text-[13px] font-bold text-slate-800">{{ getDisplayRJCode(folderPreview.target_rjcode)||'预检结果' }}</span>
                <span class="text-[11.5px] text-slate-400 truncate">{{ folderPreview.source_label }}</span>
              </div>
              <div class="flex items-center gap-2">
                <button v-if="canRetryFolderPreview" class="text-[11px] font-medium text-slate-600 hover:bg-slate-100 px-2.5 py-1 rounded-[7px] transition-all disabled:opacity-50" :disabled="folderPreviewLoading" @click="previewFolderImport">重新检查</button>
                <span class="inline-flex px-2.5 py-1 rounded-[7px] text-[10.5px] font-semibold border" :class="canExecuteFolderImport ? 'bg-slate-100 text-slate-700 border-slate-200' : 'bg-white text-slate-500 border-slate-200'">{{ canExecuteFolderImport ? '可以补配' : '不可执行' }}</span>
              </div>
            </div>
            <div :key="`${folderPreview.source_path||folderPreview.source_label||'fp'}`" class="p-4 flex flex-col gap-4">
              <div class="flex items-start gap-2.5 px-3 py-2.5 rounded-[10px] border text-[11.5px] leading-relaxed" :class="canExecuteFolderImport ? 'border-slate-200 bg-slate-50 text-slate-700' : 'border-amber-200 bg-amber-50 text-amber-800'">
                <svg v-if="canExecuteFolderImport" class="flex-shrink-0 mt-0.5" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg>
                <svg v-else class="flex-shrink-0 mt-0.5" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                {{ folderPreview.reason||(canExecuteFolderImport ? '目标原作已定位，可以继续导入。' : '当前这份字幕文件夹暂时无法执行。') }}
              </div>
              <div class="grid grid-cols-2 gap-2">
                <div class="px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">来源 RJ</span><span class="text-[12.5px] font-bold text-slate-800 font-mono">{{ getDisplayRJCode(folderPreview.source_rjcode)||'-' }}</span></div>
                <div class="px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">目标 RJ</span><span class="text-[12.5px] font-bold text-slate-900 font-mono">{{ getDisplayRJCode(folderPreview.target_rjcode)||'-' }}</span></div>
                <div class="px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">字幕数</span><span class="text-[12.5px] font-bold text-slate-800">{{ folderPreview.subtitle_count??0 }}</span></div>
                <div class="px-3 py-2 rounded-[10px] bg-slate-50 border border-slate-100 flex flex-col gap-0.5 col-span-1"><span class="text-[9.5px] font-semibold text-slate-400 uppercase tracking-wider">来源目录</span><span class="text-[11px] font-semibold text-slate-700 truncate">{{ folderPreview.source_label||'-' }}</span></div>
              </div>
              <div v-if="folderPreview.subtitle_entries?.length" class="flex flex-col gap-1.5">
                <div class="flex items-center gap-1.5"><span class="text-[11px] font-bold text-slate-700">字幕候选文件树</span><span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 text-[9.5px]">{{ folderPreview.subtitle_entries.length }}</span></div>
                <div class="grid grid-cols-1 xl:grid-cols-2 gap-2">
                  <div v-for="node in buildSubtitleEntryTreeRows(folderPreview.subtitle_entries)" :key="node.key" class="flex items-center gap-2 min-w-0 rounded-[8px] border border-slate-100 bg-slate-50 px-2.5 py-1.5 text-[11px] text-slate-700">
                    <span class="shrink-0 text-slate-300 font-mono" :style="{ width: `${node.depth * 14}px` }"></span>
                    <span class="shrink-0 text-slate-400">{{ node.isDir ? '▸' : '└' }}</span>
                    <span class="truncate" :class="node.isDir ? 'font-semibold text-slate-800' : 'font-medium text-slate-600'">{{ node.name }}</span>
                  </div>
                </div>
              </div>
              <div class="flex flex-col gap-2">
                <div class="flex items-center justify-between"><span class="text-[11px] font-bold text-slate-700">目标目录候选</span><span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[9.5px] font-bold">{{ folderPreview.candidate_count??0 }} 个</span></div>
                <AppEmptyState v-if="!folderPreview.candidates?.length" description="没有找到目标目录候选" size="sm" />
                <div v-else class="flex flex-col gap-1.5">
                  <div v-for="candidate in folderPreview.candidates" :key="candidateKey(candidate)" class="flex items-start gap-3 p-3 rounded-[10px] border cursor-pointer transition-all" :class="folderCandidateSelection===candidateKey(candidate) ? 'border-slate-400 bg-slate-50 ring-1 ring-slate-300/30' : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'" @click="folderCandidateSelection=candidateKey(candidate)">
                    <div class="w-3.5 h-3.5 rounded-[4px] border-2 flex-shrink-0 mt-0.5 flex items-center justify-center" :class="folderCandidateSelection===candidateKey(candidate) ? 'border-slate-900 bg-slate-900' : 'border-slate-300'"><div v-if="folderCandidateSelection===candidateKey(candidate)" class="w-1.5 h-1.5 rounded-[2px] bg-white"></div></div>
                    <div class="flex-1 min-w-0">
                      <div class="text-[12.5px] font-bold text-slate-800 truncate">{{ candidate.folder_name||candidate.folder_path }}</div>
                      <div class="flex flex-wrap gap-1.5 mt-1.5">
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">{{ candidate.library_name }}</span>
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">{{ candidate.library_type==='synology_filestation' ? '远程' : '本地' }}</span>
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">音频 {{ candidate.audio_count??0 }}</span>
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">字幕 {{ candidate.existing_subtitle_count??0 }}</span>
                        <span class="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">{{ formatSize(candidate.total_size) }}</span>
                      </div>
                      <div class="text-[9.5px] text-slate-400 mt-1 font-mono truncate">{{ candidate.folder_path }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>
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
      <SubtitleImportWorkbench v-if="workbenchDialogInitialized" :task-id="activeWorkbenchTaskId" :visible="workbenchDialogVisible" :background-active="workbenchBackgroundActive" @close="closeImportWorkbench" @hide-background="hideImportWorkbenchToBackground" @select-task="openImportedTask" @state-change="handleWorkbenchStateChange" />
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
:global(.subtitle-import-workbench-dialog) { padding:0;border-radius:24px;overflow:hidden;background:linear-gradient(180deg,#f8fafc 0%,#f1f5f9 100%);box-shadow:0 26px 80px rgba(15,23,42,0.16); }
:global(.subtitle-import-workbench-dialog .el-dialog__header) { display:none; }
:global(.subtitle-import-workbench-dialog .el-dialog__body) { padding:0;max-height:calc(100vh - 18px);overflow:hidden; }
:global(.subtitle-workbench-overlay) { background: rgba(15, 23, 42, 0.58); backdrop-filter: blur(2px); }
</style>
