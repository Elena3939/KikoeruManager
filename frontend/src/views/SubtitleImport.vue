<template>
  <div class="flex flex-col gap-4 min-h-full pb-8">
    <!-- Hero Section -->
    <div class="relative overflow-hidden rounded-3xl bg-gradient-to-br from-white to-slate-50 border border-slate-200/60 shadow-sm p-6 lg:p-8">
      <!-- Top Right subtle glow -->
      <div class="absolute -top-32 -right-32 w-[32rem] h-[32rem] bg-[radial-gradient(circle_at_center,rgba(99,102,241,0.08)_0,transparent_60%)] pointer-events-none"></div>

      <div class="relative z-10 flex flex-col lg:flex-row gap-8 items-stretch">
        <div class="flex-1 flex flex-col justify-center gap-4">
          <div>
            <div class="text-[11px] font-bold tracking-widest text-indigo-600 uppercase mb-1">Subtitle Import</div>
            <h1 class="text-3xl font-extrabold tracking-tight text-slate-900">字幕补配</h1>
          </div>
          <p class="text-[13px] leading-relaxed text-slate-500 max-w-2xl">
            自动检测到的压缩包来源会先进入预检单，手动拿到的字幕目录也可以在这里补进库存。确认目标原作后，直接进入现有 RJ 字幕工作台继续筛选、配对和应用。
          </p>
          <div class="flex flex-wrap gap-3 mt-2">
            <button class="inline-flex items-center justify-center px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-xl shadow-md shadow-indigo-200 transition-all hover:-translate-y-0.5 active:translate-y-0" @click="openImportWorkbench()">
              打开工作台
            </button>
            <button class="inline-flex items-center justify-center px-5 py-2.5 bg-white border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 text-sm font-medium rounded-xl shadow-sm transition-all hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-60 disabled:cursor-not-allowed" :disabled="pendingLoading" @click="loadPendingImports">
              <span v-if="pendingLoading" class="mr-2 animate-spin w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full"></span>
              刷新预检单
            </button>
          </div>
        </div>
        
        <div class="w-full lg:w-80 bg-white/60 border border-slate-200/80 rounded-xl p-5 shadow-sm backdrop-blur-sm">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-sm font-bold text-slate-800 flex items-center gap-2">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-indigo-500"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
              当前概览
            </h2>
            <div class="h-px flex-1 bg-slate-200 ml-3"></div>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div class="bg-white border border-slate-200/80 rounded-lg p-5 shadow-sm flex flex-col justify-between transition-all hover:border-indigo-200 hover:shadow-md group">
              <span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider group-hover:text-indigo-600 transition-colors">待处理预检</span>
              <div class="mt-3 flex items-baseline gap-1.5">
                <strong class="text-3xl font-bold tracking-tight text-slate-800 group-hover:text-indigo-700 transition-colors">{{ pendingItems.length }}</strong>
                <span class="text-[11px] font-medium text-slate-400">项</span>
              </div>
            </div>
            <div class="bg-white border border-slate-200/80 rounded-lg p-5 shadow-sm flex flex-col justify-between transition-all hover:border-indigo-200 hover:shadow-md group">
              <span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider group-hover:text-indigo-600 transition-colors">累计任务</span>
              <div class="mt-3 flex items-baseline gap-1.5">
                <strong class="text-3xl font-bold tracking-tight text-slate-800 group-hover:text-indigo-700 transition-colors">{{ workbenchBackgroundSummary.total || 0 }}</strong>
                <span class="text-[11px] font-medium text-slate-400">项</span>
              </div>
            </div>
            <div class="bg-white border border-slate-200/80 rounded-lg p-5 shadow-sm flex flex-col justify-between transition-all hover:border-emerald-200 hover:shadow-md group">
              <span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider group-hover:text-emerald-600 transition-colors">进行中</span>
              <div class="mt-3 flex items-baseline gap-1.5">
                <strong class="text-3xl font-bold tracking-tight text-slate-800 group-hover:text-emerald-700 transition-colors">{{ workbenchBackgroundSummary.processing || 0 }}</strong>
                <span class="text-[11px] font-medium text-slate-400">项</span>
              </div>
            </div>
            <div class="bg-white border border-slate-200/80 rounded-lg p-5 shadow-sm flex flex-col justify-between transition-all hover:border-indigo-200 hover:shadow-md group">
              <span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider group-hover:text-indigo-600 transition-colors">目标候选</span>
              <div class="mt-3 flex items-baseline gap-1.5">
                <strong class="text-3xl font-bold tracking-tight text-slate-800 group-hover:text-indigo-700 transition-colors">{{ folderPreview?.candidate_count ?? 0 }}</strong>
                <span class="text-[11px] font-medium text-slate-400">个</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Tabs Area -->
    <el-tabs v-show="!workbenchDialogVisible" v-model="activeTab" class="modern-tabs mt-2">
      <el-tab-pane label="压缩包补配" name="archive">
        <div class="px-2 pb-5 pt-2">
          <h2 class="text-xl font-bold text-slate-900 tracking-tight">自动检测到的字幕来源</h2>
          <p class="text-[13px] text-slate-500 mt-1">左侧管理待处理预检单，右侧查看命中结果并选择目标目录。确认后即可一键送入补配工作台。</p>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-[0.88fr_1.38fr] gap-4 items-start">
          <!-- Left Column: Pending List -->
          <div class="bg-white border border-slate-200/60 rounded-3xl shadow-sm overflow-hidden flex flex-col min-h-[420px]">
            <div class="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
              <div>
                <h3 class="text-base font-bold text-slate-800 tracking-tight">自动检测来源</h3>
                <p class="text-[11px] text-slate-500 mt-0.5">来自正常解压主链路</p>
              </div>
              <span class="px-2.5 py-1 rounded-md bg-indigo-50 text-indigo-600 text-[10px] font-medium border border-indigo-100">主链路</span>
            </div>

            <div class="p-4 flex-1 flex flex-col">
              <el-empty v-if="pendingLoadedOnce && !pendingItems.length" description="当前没有待处理的字幕补配预检单" class="my-auto" />
              
              <div v-else class="flex flex-col h-full">
                <div class="flex justify-end gap-2 mb-3">
                  <button 
                    class="px-3 py-1.5 text-[11px] font-medium rounded-lg border border-rose-200 text-rose-600 bg-rose-50 hover:bg-rose-100 hover:border-rose-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    :disabled="!activePendingItem || pendingClearLoading"
                    @click="clearPendingImports(false)"
                  >
                    清除当前
                  </button>
                  <button 
                    class="px-3 py-1.5 text-[11px] font-medium rounded-lg bg-rose-500 text-white hover:bg-rose-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
                    :disabled="!pendingItems.length || pendingClearLoading"
                    @click="clearPendingImports(true)"
                  >
                    清空预检单
                  </button>
                </div>

                <div class="flex-1 overflow-y-auto max-h-[540px] pr-1 space-y-2 pb-2 custom-scrollbar">
                  <button
                    v-for="item in pendingItems"
                    :key="item.id"
                    type="button"
                    class="w-full text-left p-4 rounded-2xl border transition-all duration-200 relative group"
                    :class="item.id === activePendingId ? 'border-indigo-400 bg-indigo-50/40 shadow-sm ring-1 ring-indigo-500/10' : 'border-slate-200 bg-white hover:border-indigo-300 hover:shadow-md hover:-translate-y-0.5'"
                    @click="activePendingId = item.id"
                  >
                    <div v-if="item.id === activePendingId" class="absolute left-0 top-4 bottom-4 w-1 bg-gradient-to-b from-indigo-500 to-blue-500 rounded-r-full"></div>
                    <div class="flex items-center gap-2 mb-2" :class="item.id === activePendingId ? 'pl-3' : ''">
                      <strong class="text-[14px] font-bold text-slate-800 tracking-tight">{{ getDisplayRJCode(item.preview?.target_rjcode || item.preview?.source_rjcode) || '未识别 RJ' }}</strong>
                      <span class="px-1.5 py-0.5 rounded flex items-center text-[10px] font-medium" :class="item.can_execute ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' : 'bg-slate-100 text-slate-500 border border-slate-200'">
                        {{ item.can_execute ? '可执行' : '仅查看' }}
                      </span>
                    </div>
                    <div class="text-[13px] font-bold text-slate-700 mb-2 truncate" :class="item.id === activePendingId ? 'pl-3' : ''">
                      {{ item.preview?.source_label || getFileName(item.source_path) }}
                    </div>
                    <div class="flex flex-wrap gap-x-3 gap-y-1.5 text-[11px] text-slate-500 mb-2" :class="item.id === activePendingId ? 'pl-3' : ''">
                      <span class="flex items-center gap-1">来源 <span class="font-semibold text-slate-600">{{ getDisplayRJCode(item.preview?.source_rjcode) || '-' }}</span></span>
                      <span class="flex items-center gap-1">目标 <span class="font-semibold text-slate-600">{{ getDisplayRJCode(item.preview?.target_rjcode) || '-' }}</span></span>
                      <span class="flex items-center gap-1">字幕 <span class="font-semibold text-slate-600">{{ item.preview?.subtitle_count ?? 0 }}</span></span>
                    </div>
                    <div class="text-[10px] text-slate-400 truncate" :class="item.id === activePendingId ? 'pl-3' : ''">{{ item.source_path }}</div>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Right Column: Preview Result -->
          <div class="bg-white border border-slate-200/60 rounded-3xl shadow-sm overflow-hidden flex flex-col min-h-[420px]">
            <div class="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
              <div>
                <h3 class="text-base font-bold text-slate-800 tracking-tight">预检结果</h3>
                <p class="text-[11px] text-slate-500 mt-0.5">查看来源、候选字幕和目标目录命中情况</p>
              </div>
              <span v-if="activePendingItem" class="px-2.5 py-1 rounded-md text-[10px] font-medium border" :class="activePendingItem.can_execute ? 'bg-emerald-50 text-emerald-600 border-emerald-100' : 'bg-amber-50 text-amber-600 border-amber-100'">
                {{ activePendingItem.can_execute ? '可以补配' : '当前不可执行' }}
              </span>
            </div>

            <div class="p-6 flex-1">
              <el-empty v-if="!activePendingItem" description="先从左侧选择一条自动检测到的预检单" class="mt-12" />

              <div v-else :key="activePendingItem.id" class="flex flex-col gap-6">
                <div class="rounded-2xl p-5 border relative overflow-hidden" :class="activePendingItem.can_execute ? 'bg-emerald-50/50 border-emerald-100' : 'bg-amber-50/50 border-amber-100'">
                  <div class="absolute top-0 left-0 w-1 h-full" :class="activePendingItem.can_execute ? 'bg-emerald-400' : 'bg-amber-400'"></div>
                  <div class="flex items-start gap-4">
                    <div class="mt-0.5 p-2 rounded-full" :class="activePendingItem.can_execute ? 'bg-emerald-100 text-emerald-600' : 'bg-amber-100 text-amber-600'">
                      <svg v-if="activePendingItem.can_execute" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                      <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    </div>
                    <div class="flex-1">
                      <h4 class="text-[14px] font-bold tracking-tight" :class="activePendingItem.can_execute ? 'text-emerald-800' : 'text-amber-800'">
                        {{ activePendingItem.can_execute ? '这条来源可以进入字幕补配' : '这条来源目前只能查看预检结果' }}
                      </h4>
                      <p class="text-[12.5px] mt-1.5 leading-relaxed" :class="activePendingItem.can_execute ? 'text-emerald-700/90' : 'text-amber-700/90'">
                        {{ activePendingItem.preview?.reason || '目标原作已定位，可以继续导入并进入库存字幕工作台。' }}
                      </p>
                    </div>
                  </div>
                  <div v-if="canRetryActivePendingPreview" class="mt-4 flex justify-end">
                    <button class="text-[12px] font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-3 py-1.5 rounded-lg transition-all disabled:opacity-50" :disabled="retryingPendingId === activePendingItem.id" @click="retryActivePendingPreview">
                      重试远程搜索
                    </button>
                  </div>
                </div>

                <div class="grid grid-cols-2 lg:grid-cols-3 gap-4 p-5 rounded-2xl bg-slate-50/80 border border-slate-100/80">
                  <div class="flex flex-col gap-1.5 col-span-2 lg:col-span-1">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">来源压缩包</span>
                    <span class="text-[13px] font-bold text-slate-800 truncate">{{ activePendingItem.preview?.source_label || '-' }}</span>
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">来源 RJ</span>
                    <span class="inline-flex"><span class="px-2.5 py-0.5 rounded-md bg-indigo-50 text-indigo-700 text-[12px] font-mono font-semibold border border-indigo-100 shadow-sm">{{ getDisplayRJCode(activePendingItem.preview?.source_rjcode) || '-' }}</span></span>
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">目标原作 RJ</span>
                    <span class="inline-flex"><span class="px-2.5 py-0.5 rounded-md bg-indigo-50 text-indigo-700 text-[12px] font-mono font-semibold border border-indigo-100 shadow-sm">{{ getDisplayRJCode(activePendingItem.preview?.target_rjcode) || '-' }}</span></span>
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">字幕候选数</span>
                    <span class="text-[13px] font-bold text-slate-800">{{ activePendingItem.preview?.subtitle_count ?? 0 }} 项</span>
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Kikoeru 原作命中</span>
                    <span class="inline-flex"><span class="px-2.5 py-0.5 rounded-md text-[11px] font-bold shadow-sm" :class="activePendingItem.preview?.kikoeru_has_work ? 'bg-emerald-50 text-emerald-700 border border-emerald-100' : 'bg-slate-100 text-slate-600 border border-slate-200'">{{ activePendingItem.preview?.kikoeru_has_work ? '已命中原作' : '未命中原作' }}</span></span>
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">预检时间</span>
                    <span class="text-[13px] font-semibold text-slate-700">{{ formatDate(activePendingItem.created_at) }}</span>
                  </div>
                </div>

                <div v-if="activePendingItem.preview?.subtitle_entries?.length" class="p-5 rounded-2xl border border-slate-100 shadow-sm bg-white">
                  <h4 class="text-[14px] font-bold text-slate-800 mb-4 flex items-center gap-2">
                    压缩包内检测到的字幕
                    <span class="px-2 py-0.5 rounded-md bg-slate-100 text-slate-500 text-[10px]">{{ activePendingItem.preview.subtitle_entries.length }}</span>
                  </h4>
                  <div class="flex flex-wrap gap-2.5">
                    <span v-for="entry in activePendingItem.preview.subtitle_entries.slice(0, 24)" :key="entry" class="px-3.5 py-1.5 rounded-lg bg-slate-50 text-slate-700 border border-slate-200 text-[12px] font-medium max-w-full truncate hover:border-slate-300 transition-colors cursor-default">
                      {{ formatSubtitleEntryDisplay(entry) }}
                    </span>
                  </div>
                </div>

                <div class="p-5 rounded-2xl border border-slate-100 shadow-sm bg-white">
                  <div class="flex justify-between items-start mb-4">
                    <div>
                      <h4 class="text-[14px] font-bold text-slate-800">目标目录候选</h4>
                      <p class="text-[12px] text-slate-500 mt-1">单命中会默认选中，多命中时请手动选择；已有字幕的目录不会允许执行。</p>
                    </div>
                    <span class="px-2.5 py-1 rounded-md bg-indigo-50 text-indigo-600 text-[11px] font-bold border border-indigo-100">候选 {{ activePendingItem.preview?.candidate_count ?? 0 }}</span>
                  </div>

                  <el-empty v-if="!activePendingItem.preview?.candidates?.length" description="没有可用的目标目录候选" :image-size="60" />

                  <div v-else class="flex flex-col gap-3.5 w-full">
                    <div v-for="candidate in activePendingItem.preview.candidates" :key="candidateKey(candidate)" class="flex items-start p-4 rounded-2xl border cursor-pointer transition-all hover:shadow-md" :class="archiveCandidateSelection[activePendingItem.id] === candidateKey(candidate) ? 'border-indigo-400 bg-indigo-50/40 ring-2 ring-indigo-500/20' : 'border-slate-200 bg-white hover:border-indigo-300'" @click="archiveCandidateSelection[activePendingItem.id] = candidateKey(candidate)">
                      <el-radio :label="candidateKey(candidate)" v-model="archiveCandidateSelection[activePendingItem.id]" class="!mr-0 pointer-events-none mt-0.5 shrink-0" @click.stop>
                        <span class="hidden"></span>
                      </el-radio>
                      <div class="flex-1 min-w-0 pl-3">
                        <div class="text-[14px] font-bold text-slate-800 whitespace-normal break-all leading-tight">{{ candidate.folder_name || candidate.folder_path }}</div>
                        <div class="flex flex-wrap gap-x-3 gap-y-2 text-[12px] text-slate-600 mt-2.5">
                          <span class="flex items-center gap-1.5 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"></path></svg>{{ candidate.library_name }}</span>
                          <span class="flex items-center gap-1 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm">{{ candidate.library_type === 'synology_filestation' ? '远程库' : '本地库' }}</span>
                          <span class="flex items-center gap-1 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm">音频 <strong class="font-bold text-slate-800">{{ candidate.audio_count ?? 0 }}</strong></span>
                          <span class="flex items-center gap-1 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm">现有字幕 <strong class="font-bold text-slate-800">{{ candidate.existing_subtitle_count ?? 0 }}</strong></span>
                          <span class="flex items-center gap-1 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm">{{ formatSize(candidate.total_size) }}</span>
                        </div>
                        <div class="text-[11px] text-slate-400 mt-2.5 break-all font-mono leading-relaxed">{{ candidate.folder_path }}</div>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="flex justify-end mt-4 pt-4 border-t border-slate-100">
                  <button class="px-8 py-3 bg-indigo-600 hover:bg-indigo-700 text-white text-[14px] font-bold rounded-xl shadow-lg shadow-indigo-200 transition-all hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:shadow-none flex items-center gap-2" :disabled="!activePendingItem.can_execute || !selectedArchiveCandidate || executingPendingId === activePendingItem.id" @click="executePendingImport()">
                    <span v-if="executingPendingId === activePendingItem.id" class="animate-spin inline-block w-4 h-4 border-2 border-white/40 border-t-white rounded-full align-middle"></span>
                    导入并加入补配工作台
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Folder Tab -->
      <el-tab-pane label="字幕文件夹补配" name="folder">
        <div class="px-2 pb-5 pt-2">
          <h2 class="text-xl font-bold text-slate-900 tracking-tight">手动补进字幕目录</h2>
          <p class="text-[13px] text-slate-500 mt-1">适合单独拿到字幕文件夹的场景。先输入路径做预检，再选择目标原作并送入工作台继续处理。</p>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-[0.88fr_1.32fr] gap-4 items-start">
          <!-- Left Column: Manual Source -->
          <div class="bg-white border border-slate-200/60 rounded-3xl shadow-sm overflow-hidden flex flex-col min-h-[420px]">
            <div class="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
              <div>
                <h3 class="text-base font-bold text-slate-800 tracking-tight">手动字幕来源</h3>
                <p class="text-[11px] text-slate-500 mt-0.5">保留手动补配入口</p>
              </div>
              <span class="px-2.5 py-1 rounded-md bg-amber-50 text-amber-600 text-[10px] font-medium border border-amber-100">手动入口</span>
            </div>

            <div class="p-6 flex flex-col gap-6">
              <div>
                <label class="block text-[14px] font-bold text-slate-800 mb-2.5">字幕文件夹路径</label>
                <div class="relative group">
                  <input type="text" v-model="folderPath" class="w-full px-4 py-3.5 bg-slate-50 border border-slate-200 rounded-2xl text-[14px] font-medium text-slate-800 focus:outline-none focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-400 focus:bg-white transition-all placeholder:text-slate-400 placeholder:font-normal shadow-sm" placeholder="例如 D:\Temp\RJ123456 或其中带 subtitles 子目录" @keyup.enter="previewFolderImport" />
                  <button v-if="folderPath" @click="folderPath = ''" class="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 bg-white rounded-full p-1 shadow-sm border border-slate-100 transition-all hover:scale-110">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
                  </button>
                </div>
              </div>

              <div class="flex flex-wrap items-center gap-3 pt-2">
                <button class="px-6 py-2.5 bg-white border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 text-[13px] font-bold rounded-xl shadow-sm transition-all hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-60 flex items-center gap-2" :disabled="folderPreviewLoading" @click="previewFolderImport">
                  <span v-if="folderPreviewLoading" class="animate-spin inline-block w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full align-middle"></span>
                  预检目标
                </button>
                <button class="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-[13px] font-bold rounded-xl shadow-md shadow-indigo-200 transition-all hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:shadow-none flex items-center gap-2" :disabled="!canExecuteFolderImport || folderImporting" @click="executeFolderImport">
                  <span v-if="folderImporting" class="animate-spin inline-block w-4 h-4 border-2 border-white/40 border-t-white rounded-full align-middle"></span>
                  导入并加入补配工作台
                </button>
              </div>

              <div class="p-5 rounded-2xl bg-blue-50/80 border border-blue-100 mt-2">
                <h4 class="text-[13px] font-bold text-blue-800 mb-1.5">适用场景</h4>
                <p class="text-[12px] leading-relaxed text-blue-700/80">手头单独拿到了字幕目录时，可以直接在这里补进原作目录，再进入库存页做筛选、删除和手动配对。</p>
              </div>
            </div>
          </div>

          <!-- Right Column: Folder Preview Result -->
          <div class="bg-white border border-slate-200/60 rounded-3xl shadow-sm overflow-hidden flex flex-col min-h-[420px]">
            <div class="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
              <div>
                <h3 class="text-base font-bold text-slate-800 tracking-tight">文件夹预检结果</h3>
                <p class="text-[11px] text-slate-500 mt-0.5">查看来源字幕、目标目录候选和可执行状态</p>
              </div>
              <span v-if="folderPreview" class="px-2.5 py-1 rounded-md text-[10px] font-medium border" :class="canExecuteFolderImport ? 'bg-emerald-50 text-emerald-600 border-emerald-100' : 'bg-amber-50 text-amber-600 border-amber-100'">
                {{ canExecuteFolderImport ? '可以补配' : '当前不可执行' }}
              </span>
            </div>

            <div class="p-6 flex-1">
              <el-empty v-if="!folderPreview && !folderPreviewLoading" description="输入字幕文件夹路径后做一次预检" class="mt-12" />

              <div v-else-if="folderPreview" :key="`${folderPreview.source_path || folderPreview.source_label || 'folder-preview'}`" class="flex flex-col gap-6">
                <div class="rounded-2xl p-5 border relative overflow-hidden" :class="canExecuteFolderImport ? 'bg-emerald-50/50 border-emerald-100' : 'bg-amber-50/50 border-amber-100'">
                  <div class="absolute top-0 left-0 w-1 h-full" :class="canExecuteFolderImport ? 'bg-emerald-400' : 'bg-amber-400'"></div>
                  <div class="flex items-start gap-4">
                    <div class="mt-0.5 p-2 rounded-full" :class="canExecuteFolderImport ? 'bg-emerald-100 text-emerald-600' : 'bg-amber-100 text-amber-600'">
                      <svg v-if="canExecuteFolderImport" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                      <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
                    </div>
                    <div class="flex-1">
                      <h4 class="text-[14px] font-bold tracking-tight" :class="canExecuteFolderImport ? 'text-emerald-800' : 'text-amber-800'">
                        {{ canExecuteFolderImport ? '可以执行字幕文件夹补配' : '这份字幕文件夹当前还不能直接补配' }}
                      </h4>
                      <p class="text-[12.5px] mt-1.5 leading-relaxed" :class="canExecuteFolderImport ? 'text-emerald-700/90' : 'text-amber-700/90'">
                        {{ folderPreview.reason || '目标原作已定位，可以继续导入并进入库存字幕工作台。' }}
                      </p>
                    </div>
                  </div>
                  <div v-if="canRetryFolderPreview" class="mt-4 flex justify-end">
                    <button class="text-[12px] font-medium text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 px-3 py-1.5 rounded-lg transition-all disabled:opacity-50" :disabled="folderPreviewLoading" @click="previewFolderImport">
                      重新检查目标目录
                    </button>
                  </div>
                </div>

                <div class="grid grid-cols-2 lg:grid-cols-3 gap-4 p-5 rounded-2xl bg-slate-50/80 border border-slate-100/80">
                  <div class="flex flex-col gap-1.5">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">来源 RJ</span>
                    <span class="inline-flex"><span class="px-2.5 py-0.5 rounded-md bg-indigo-50 text-indigo-700 text-[12px] font-mono font-semibold border border-indigo-100 shadow-sm">{{ getDisplayRJCode(folderPreview.source_rjcode) || '-' }}</span></span>
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">目标原作 RJ</span>
                    <span class="inline-flex"><span class="px-2.5 py-0.5 rounded-md bg-indigo-50 text-indigo-700 text-[12px] font-mono font-semibold border border-indigo-100 shadow-sm">{{ getDisplayRJCode(folderPreview.target_rjcode) || '-' }}</span></span>
                  </div>
                  <div class="flex flex-col gap-1.5">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">字幕候选数</span>
                    <span class="text-[13px] font-bold text-slate-800">{{ folderPreview.subtitle_count ?? 0 }} 项</span>
                  </div>
                  <div class="flex flex-col gap-1.5 col-span-2 lg:col-span-3 mt-2">
                    <span class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">来源目录</span>
                    <span class="text-[13px] font-bold text-slate-800 break-all bg-white px-3 py-2 rounded-xl border border-slate-100 shadow-sm mt-1">{{ folderPreview.source_label || '-' }}</span>
                  </div>
                </div>

                <div v-if="folderPreview.subtitle_entries?.length" class="p-5 rounded-2xl border border-slate-100 shadow-sm bg-white">
                  <h4 class="text-[14px] font-bold text-slate-800 mb-4 flex items-center gap-2">
                    检测到的字幕文件
                    <span class="px-2 py-0.5 rounded-md bg-slate-100 text-slate-500 text-[10px]">{{ folderPreview.subtitle_entries.length }}</span>
                  </h4>
                  <div class="flex flex-wrap gap-2.5">
                    <span v-for="entry in folderPreview.subtitle_entries.slice(0, 24)" :key="entry" class="px-3.5 py-1.5 rounded-lg bg-slate-50 text-slate-700 border border-slate-200 text-[12px] font-medium max-w-full truncate hover:border-slate-300 transition-colors cursor-default">
                      {{ formatSubtitleEntryDisplay(entry) }}
                    </span>
                  </div>
                </div>

                <div class="p-5 rounded-2xl border border-slate-100 shadow-sm bg-white">
                  <div class="flex justify-between items-start mb-4">
                    <div>
                      <h4 class="text-[14px] font-bold text-slate-800">目标目录候选</h4>
                      <p class="text-[12px] text-slate-500 mt-1">多命中时请选择正确的原作目录。</p>
                    </div>
                    <span class="px-2.5 py-1 rounded-md bg-slate-100 text-slate-600 text-[11px] font-bold border border-slate-200">候选 {{ folderPreview.candidate_count ?? 0 }}</span>
                  </div>

                  <el-empty v-if="!folderPreview.candidates?.length" description="没有找到目标目录候选" :image-size="60" />

                  <div v-else class="flex flex-col gap-3.5 w-full">
                    <div v-for="candidate in folderPreview.candidates" :key="candidateKey(candidate)" class="flex items-start p-4 rounded-2xl border cursor-pointer transition-all hover:shadow-md" :class="folderCandidateSelection === candidateKey(candidate) ? 'border-indigo-400 bg-indigo-50/40 ring-2 ring-indigo-500/20' : 'border-slate-200 bg-white hover:border-indigo-300'" @click="folderCandidateSelection = candidateKey(candidate)">
                      <el-radio :label="candidateKey(candidate)" v-model="folderCandidateSelection" class="!mr-0 pointer-events-none mt-0.5 shrink-0" @click.stop>
                        <span class="hidden"></span>
                      </el-radio>
                      <div class="flex-1 min-w-0 pl-3">
                        <div class="text-[14px] font-bold text-slate-800 whitespace-normal break-all leading-tight">{{ candidate.folder_name || candidate.folder_path }}</div>
                        <div class="flex flex-wrap gap-x-3 gap-y-2 text-[12px] text-slate-600 mt-2.5">
                          <span class="flex items-center gap-1.5 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm"><svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"></path></svg>{{ candidate.library_name }}</span>
                          <span class="flex items-center gap-1 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm">{{ candidate.library_type === 'synology_filestation' ? '远程库' : '本地库' }}</span>
                          <span class="flex items-center gap-1 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm">音频 <strong class="font-bold text-slate-800">{{ candidate.audio_count ?? 0 }}</strong></span>
                          <span class="flex items-center gap-1 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm">现有字幕 <strong class="font-bold text-slate-800">{{ candidate.existing_subtitle_count ?? 0 }}</strong></span>
                          <span class="flex items-center gap-1 bg-white px-2 py-0.5 rounded border border-slate-100 shadow-sm">{{ formatSize(candidate.total_size) }}</span>
                        </div>
                        <div class="text-[11px] text-slate-400 mt-2.5 break-all font-mono leading-relaxed">{{ candidate.folder_path }}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- Dialog -->
    <el-dialog
      v-model="workbenchDialogVisible"
      class="subtitle-import-workbench-dialog"
      append-to-body
      :destroy-on-close="false"
      :close-on-click-modal="false"
      :show-close="false"
      top="3vh"
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
.modern-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.modern-tabs :deep(.el-tabs__nav) {
  gap: 8px;
  padding: 4px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.8);
  background: rgba(248, 250, 252, 0.8);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

.modern-tabs :deep(.el-tabs__item) {
  height: 36px;
  padding: 0 20px;
  border-radius: 8px;
  color: #64748b;
  font-weight: 600;
  font-size: 13px;
  transition: all 0.2s ease;
}

.modern-tabs :deep(.el-tabs__item:hover) {
  color: #4f46e5;
}

.modern-tabs :deep(.el-tabs__item.is-active) {
  color: #ffffff;
  background: #4f46e5;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.25);
}

.modern-tabs :deep(.el-tabs__active-bar) {
  display: none;
}

/* Scrollbar customization for pending list */
.custom-scrollbar::-webkit-scrollbar {
  width: 5px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background-color: #cbd5e1;
  border-radius: 20px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background-color: #94a3b8;
}

:global(.subtitle-import-workbench-dialog) {
  padding: 0;
  border-radius: 24px;
  overflow: hidden;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
  box-shadow: 0 26px 80px rgba(15, 23, 42, 0.16);
}

:global(.subtitle-import-workbench-dialog .el-dialog__header) {
  display: none;
}

:global(.subtitle-import-workbench-dialog .el-dialog__body) {
  padding: 0;
  max-height: calc(100vh - 18px);
  overflow: auto;
}
</style>
