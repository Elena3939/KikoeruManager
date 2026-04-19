<template>
  <div class="password-vault">
    <div class="page-header">
      <div>
        <h1 class="page-title bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-indigo-600">密码库</h1>
        <p class="page-subtitle">集中管理解压密码、RJ 关联信息和清理历史。</p>
      </div>
      <div class="page-header-meta">
        <span class="pill hover:bg-slate-100 hover:text-slate-900 transition-all duration-300 cursor-default hover:-translate-y-0.5">{{ `总数 ${totalCount}` }}</span>
        <span class="pill text-blue-600 border-blue-100 bg-blue-50 hover:bg-blue-100 transition-all duration-300 cursor-default hover:-translate-y-0.5">{{ `已使用 ${usedPasswordCount}` }}</span>
        <span class="pill text-emerald-600 border-emerald-100 bg-emerald-50 hover:bg-emerald-100 transition-all duration-300 cursor-default hover:-translate-y-0.5">{{ `已关联 ${scopedPasswordCount}` }}</span>
      </div>
    </div>

    <el-card class="bg-white rounded-3xl border border-slate-200 shadow-sm overflow-hidden transition-all duration-300" shadow="never" style="border: none;">
      <div v-if="cleanupStatus" class="cleanup-banner hover:shadow-md transition-shadow duration-300 cursor-pointer">
        <div>
          <div class="banner-title">{{ cleanupStatus.enabled ? '智能清理策略已接管密码库维护' : '智能清理策略尚未启用' }}</div>
          <div class="banner-text">
            <template v-if="cleanupStatus.enabled">下次清理时间 {{ formatNextCleanupTime(cleanupStatus.next_cleanup_time) }}，规则为使用次数 ≤ {{ cleanupStatus.max_use_count }}，保留 {{ cleanupStatus.preserve_days }} 天。</template>
            <template v-else>你可以在设置页开启密码库智能清理，避免低价值密码持续堆积。</template>
          </div>
        </div>
        <div class="banner-meta">
          <span class="pill dark hover:bg-slate-100 transition-colors">{{ cleanupStatus.enabled ? 'AUTO CLEANUP' : 'MANUAL MODE' }}</span>
          <span class="pill dark hover:bg-slate-100 transition-colors">{{ cleanupStatus.is_running ? '服务运行中' : '服务未运行' }}</span>
        </div>
      </div>

      <div class="toolbar-shell">
        <div class="toolbar-group">
          <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg shadow-sm hover:bg-blue-500 hover:shadow-blue-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 active:scale-95 transition-all duration-300" @click="showAddDialog = true"><el-icon class="group-hover:rotate-90 group-hover:scale-110 transition-transform duration-300"><Plus /></el-icon>添加密码</el-button>
          <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-emerald-500 border border-transparent rounded-lg shadow-sm hover:bg-emerald-400 hover:shadow-emerald-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1 active:scale-95 transition-all duration-300" @click="showImportDialog = true"><el-icon class="group-hover:-translate-y-0.5 group-hover:scale-110 transition-transform duration-300"><Document /></el-icon>批量导入</el-button>
          <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-red-700 bg-red-50 border border-red-200 rounded-lg shadow-sm hover:bg-red-100 hover:text-red-800 hover:border-red-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-red-200 focus:ring-offset-1 active:scale-95 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 disabled:hover:shadow-none" @click="handleBatchDelete" :disabled="selectedRows.length === 0"><AppLottieIcon :src="deleteIconAnimation" :size="32" tone="danger" :disabled="selectedRows.length === 0" />批量删除</el-button>
          <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-violet-500 border border-transparent rounded-lg shadow-sm hover:bg-violet-400 hover:shadow-violet-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-violet-500 focus:ring-offset-1 active:scale-95 transition-all duration-300" @click="showCleanupDialog = true"><el-icon class="group-hover:rotate-180 transition-transform duration-500"><Timer /></el-icon>智能清理</el-button>
        </div>
        <div class="toolbar-group toolbar-filters">
          <span class="control-label">排序字段</span>
          <el-select v-model="passwordSortBy" style="width:150px" @change="handlePasswordSortChange">
            <el-option label="添加时间" value="created_at" />
            <el-option label="更新时间" value="updated_at" />
            <el-option label="RJ号" value="rjcode" />
            <el-option label="文件名" value="filename" />
            <el-option label="使用次数" value="use_count" />
          </el-select>
          <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg shadow-sm hover:bg-slate-50 hover:text-slate-900 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-1 active:scale-95 transition-all duration-300 sort-btn" @click="togglePasswordSortOrder"><el-icon class="group-hover:-translate-y-0.5 transition-transform duration-300"><SortDown v-if="passwordSortOrder === 'desc'" /><SortUp v-else /></el-icon>{{ passwordSortOrder === 'desc' ? '降序' : '升序' }}</el-button>
          <el-input v-model="searchQuery" class="vault-search group transition-all duration-300 focus-within:w-[320px]" placeholder="搜索 RJ 号、文件名或密码" clearable @input="handleSearch"><template #prefix><el-icon class="text-slate-400 group-focus-within:text-blue-500 transition-colors duration-300"><Search /></el-icon></template></el-input>
        </div>
      </div>

      <div class="table-shell">
        <div class="table-head">
          <div class="flex items-center gap-3">
            <div class="table-title">密码记录</div>
            <div class="table-subtitle hidden sm:block">保留表格密度，但把筛选、批量操作和状态反馈分层得更清楚。</div>
          </div>
          <div class="table-meta"><span class="pill hover:bg-slate-100 transition-colors">已选 {{ selectedRows.length }}</span><span class="pill hover:bg-slate-100 transition-colors">每页 {{ pageSize }}</span></div>
        </div>

        <div v-if="loading && passwords.length === 0" class="vault-state-panel vault-state-loading" aria-hidden="true">
          <AppLoadingAnimation
            label="正在加载密码库"
            description="正在同步密码记录、RJ 关联信息和使用状态，马上就好。"
            :size="176"
            :min-height="320"
          />
        </div>

        <div v-else-if="!loading && totalCount === 0" class="vault-state-panel vault-state-empty">
          <div class="empty-orb empty-orb-left"></div>
          <div class="empty-orb empty-orb-right"></div>
          <div class="empty-icon-wrap">
            <el-icon class="empty-icon"><Document /></el-icon>
          </div>
          <div class="empty-copy">
            <div class="empty-title">密码库还是空的</div>
            <div class="empty-subtitle">先录入常用解压密码，后面解压、匹配和清理链路才会真正串起来。</div>
          </div>
          <div class="empty-actions">
            <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg shadow-sm hover:bg-blue-500 hover:shadow-blue-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 active:scale-95 transition-all duration-300" @click="showAddDialog = true"><el-icon class="group-hover:rotate-90 group-hover:scale-110 transition-transform duration-300"><Plus /></el-icon>添加第一个密码</el-button>
            <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-emerald-500 border border-transparent rounded-lg shadow-sm hover:bg-emerald-400 hover:shadow-emerald-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1 active:scale-95 transition-all duration-300" @click="showImportDialog = true"><el-icon class="group-hover:-translate-y-0.5 group-hover:scale-110 transition-transform duration-300"><Document /></el-icon>批量导入</el-button>
          </div>
        </div>

        <template v-else>
          <el-table v-app-loading="{ loading, text: '正在加载密码库...', size: 124, delay: 0, minVisible: 360 }" ref="passwordTableRef" :data="tablePasswords" class="password-table transition-all duration-300" row-key="id" @selection-change="handleSelectionChange">
            <el-table-column type="selection" width="55" />
            <el-table-column prop="rjcode" label="RJ号" width="120" sortable align="center" header-align="center">
              <template #default="{ row }"><div class="cell center"><el-tag v-if="row.rjcode" class="vault-tag hover:bg-blue-50 hover:text-blue-600 hover:border-blue-200 transition-colors duration-300" size="small">{{ row.rjcode }}</el-tag><span v-else class="muted">-</span></div></template>
            </el-table-column>
            <el-table-column prop="filename" label="文件名" min-width="200" align="center" header-align="center">
              <template #default="{ row }"><div class="cell center"><span v-if="row.filename">{{ row.filename }}</span><span v-else class="muted">-</span></div></template>
            </el-table-column>
            <el-table-column prop="password" label="密码" width="200" align="center" header-align="center">
              <template #default="{ row }"><div class="cell center"><span class="password-chip hover:scale-105 hover:shadow-sm hover:text-blue-600 transition-all duration-300 cursor-pointer">{{ row.password }}</span></div></template>
            </el-table-column>
            <el-table-column prop="description" label="备注" min-width="150" align="center" header-align="center">
              <template #default="{ row }"><div class="cell center"><span v-if="row.description">{{ row.description }}</span><span v-else class="muted">-</span></div></template>
            </el-table-column>
            <el-table-column prop="use_count" label="使用次数" width="120" sortable align="center" header-align="center">
              <template #default="{ row }"><div class="cell center"><el-tag class="vault-tag hover:scale-105 transition-transform duration-300" :class="row.use_count > 0 ? 'is-strong bg-blue-50 text-blue-600 border-blue-200' : 'bg-slate-50 text-slate-500 border-slate-200'" size="small">{{ row.use_count }}</el-tag></div></template>
            </el-table-column>
            <el-table-column prop="last_used_at" label="最后使用" width="150" align="center" header-align="center">
              <template #default="{ row }"><div class="cell center"><span v-if="row._formatted_last_used">{{ row._formatted_last_used }}</span><span v-else class="muted">未使用</span></div></template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="170" align="center" header-align="center">
              <template #default="{ row }"><div class="cell center">{{ row._formatted_created_at }}</div></template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right" align="center" header-align="center">
              <template #default="{ row }">
                <div class="flex items-center justify-center gap-3">
                  <button type="button" class="group text-slate-500 hover:text-blue-600 focus:outline-none transition-colors duration-300" @click="handleEdit(row)" title="编辑">
                    <AppLottieIcon :src="clipboardIconAnimation" :size="48" tone="primary" />
                  </button>
                  <button type="button" class="group text-slate-500 hover:text-red-600 focus:outline-none transition-colors duration-300" @click="handleDelete(row)" title="删除">
                    <AppLottieIcon :src="deleteIconAnimation" :size="40" tone="danger" />
                  </button>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-bar">
            <el-pagination class="global-pager" v-model:current-page="currentPage" v-model:page-size="pageSize" :page-sizes="[10, 20, 50, 100]" :total="totalCount" layout="total, sizes, prev, pager, next, jumper" background @size-change="handlePageSizeChange" @current-change="handlePageChange" />
          </div>
        </template>
      </div>
    </el-card>

    <el-dialog
      v-model="showAddDialog"
      :show-close="false"
      :lock-scroll="false"
      align-center
      width="min(640px, calc(100vw - 32px))"
      modal-class="custom-preview-overlay"
      append-to-body
      destroy-on-close
      class="vault-centered-dialog vault-workbench-dialog"
    >
      <div class="window panel-enter glass-shell relative flex w-full max-w-[640px] flex-col overflow-hidden rounded-3xl">
        <div class="window-header flex items-center justify-between px-6 py-4">
          <div class="fm-header-main min-w-0">
            <div class="fm-title-row">
              <h1 class="title truncate text-lg font-bold tracking-tight text-slate-900">{{ isEditing ? '编辑密码' : '添加密码' }}</h1>
              <span class="fm-badge">{{ isEditing ? 'MANUAL EDIT' : 'NEW PASSWORD' }}</span>
            </div>
            <p class="mt-1 truncate text-sm text-slate-500">维护解压密码和作品关联信息，后续清理与匹配链路都会吃这里的数据。</p>
          </div>
          <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="showAddDialog = false">
            <el-icon :size="20"><Close /></el-icon>
          </button>
        </div>

        <div class="fm-body flex min-h-0 flex-1 flex-col px-6 pb-5">
          <el-form class="vault-form" :model="form" label-width="100px" :rules="rules" ref="formRef">
            <el-form-item label="密码" prop="password"><el-input v-model="form.password" placeholder="输入解压密码" show-password /><div class="form-tip">必填：解压密码</div></el-form-item>
            <el-form-item label="RJ号"><el-input v-model="form.rjcode" placeholder="例如: RJ123456（可选）" /><div class="form-tip">可选：如果密码与特定作品关联，请填写RJ号</div></el-form-item>
            <el-form-item label="文件名"><el-input v-model="form.filename" placeholder="例如: RJ123456.zip（可选）" /><div class="form-tip">可选：如果密码与特定文件关联，请填写文件名</div></el-form-item>
            <el-form-item label="备注"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选：添加描述信息，如来源、适用范围等" /></el-form-item>
          </el-form>

          <div class="dialog-actions">
            <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg shadow-sm hover:bg-slate-50 hover:text-slate-900 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-1 active:scale-95 transition-all duration-300" @click="showAddDialog = false">取消</el-button>
            <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg shadow-sm hover:bg-blue-500 hover:shadow-blue-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 active:scale-95 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 disabled:hover:shadow-none" @click="handleSubmit" :loading="submitting">{{ isEditing ? '保存' : '添加' }}</el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <el-dialog
      v-model="showCleanupDialog"
      :show-close="false"
      :lock-scroll="false"
      align-center
      width="min(960px, calc(100vw - 32px))"
      modal-class="custom-preview-overlay"
      append-to-body
      destroy-on-close
      class="vault-centered-dialog vault-workbench-dialog"
    >
      <div class="window panel-enter glass-shell relative flex w-full max-w-[960px] flex-col overflow-hidden rounded-3xl">
        <div class="window-header flex items-center justify-between px-6 py-4">
          <div class="fm-header-main min-w-0">
            <div class="fm-title-row">
              <h1 class="title truncate text-lg font-bold tracking-tight text-slate-900">密码库智能清理</h1>
              <span class="fm-badge">{{ cleanupStatus?.enabled ? 'AUTO CLEANUP' : 'MANUAL MODE' }}</span>
            </div>
            <p class="mt-1 truncate text-sm text-slate-500">集中看清理状态、规则和历史，确认后再执行，不把维护动作打散。</p>
          </div>
          <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="showCleanupDialog = false">
            <el-icon :size="20"><Close /></el-icon>
          </button>
        </div>

        <div class="fm-body flex min-h-0 flex-1 flex-col px-6 pb-5">
          <div v-app-loading="{ loading: cleanupLoading, text: '正在清理失效密码...', size: 120 }">
          <el-row :gutter="20" class="cleanup-grid">
            <el-col :span="8"><el-card class="cleanup-card hover:shadow-md hover:-translate-y-1 transition-all duration-300 border-l-4 border-l-blue-500" shadow="never"><template #header><span>清理状态</span></template><div class="cleanup-center"><el-tag class="vault-tag transition-transform duration-300 hover:scale-105 bg-blue-50 text-blue-600 border-blue-200" :class="cleanupStatus?.enabled ? 'is-strong' : ''" size="large">{{ cleanupStatus?.enabled ? '已启用' : '已禁用' }}</el-tag><div class="cleanup-note mt-2 text-slate-500">{{ cleanupStatus?.is_running ? '服务运行中' : '服务未运行' }}</div></div></el-card></el-col>
            <el-col :span="8"><el-card class="cleanup-card hover:shadow-md hover:-translate-y-1 transition-all duration-300 border-l-4 border-l-emerald-500" shadow="never"><template #header><span>下次清理</span></template><div class="cleanup-center"><div class="cleanup-value text-emerald-600 font-bold text-lg">{{ formatNextCleanupTime(cleanupStatus?.next_cleanup_time) }}</div><div class="cleanup-note mt-2 text-slate-500">Cron: {{ cleanupStatus?.cron_expression }}</div></div></el-card></el-col>
            <el-col :span="8"><el-card class="cleanup-card hover:shadow-md hover:-translate-y-1 transition-all duration-300 border-l-4 border-l-amber-500" shadow="never"><template #header><span>清理规则</span></template><div class="cleanup-center"><div class="text-amber-600 font-bold text-lg">使用次数 ≤ {{ cleanupStatus?.max_use_count }}</div><div class="cleanup-note mt-2 text-slate-500">保留 {{ cleanupStatus?.preserve_days }} 天</div></div></el-card></el-col>
          </el-row>
            <div class="cleanup-tools flex flex-wrap gap-2 mb-4">
              <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg shadow-sm hover:bg-blue-500 hover:shadow-blue-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 active:scale-95 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 disabled:hover:shadow-none" @click="previewCleanup" :disabled="!cleanupStatus?.enabled"><el-icon class="group-hover:scale-110 transition-transform duration-300"><View /></el-icon>预览清理</el-button>
              <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-red-700 bg-red-50 border border-red-200 rounded-lg shadow-sm hover:bg-red-100 hover:text-red-800 hover:border-red-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-red-200 focus:ring-offset-1 active:scale-95 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 disabled:hover:shadow-none" @click="runCleanup" :disabled="!cleanupStatus?.enabled"><AppLottieIcon :src="deleteIconAnimation" :size="32" tone="danger" :disabled="!cleanupStatus?.enabled" />立即清理</el-button>
              <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg shadow-sm hover:bg-slate-50 hover:text-slate-900 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-1 active:scale-95 transition-all duration-300" @click="loadCleanupHistory"><el-icon class="group-hover:rotate-180 transition-transform duration-500"><Refresh /></el-icon>刷新历史</el-button>
              <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg shadow-sm hover:bg-slate-50 hover:text-slate-900 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-1 active:scale-95 transition-all duration-300 ml-auto" @click="$router.push('/settings')"><el-icon class="group-hover:rotate-90 transition-transform duration-300"><Setting /></el-icon>前往设置</el-button>
            </div>
            <el-divider>清理历史</el-divider>
            <el-table class="password-table transition-all duration-300" :data="cleanupHistory" style="width:100%" max-height="300" row-key="id">
              <el-table-column prop="created_at" label="清理时间" width="180"><template #default="{ row }">{{ row._formatted_created_at }}</template></el-table-column>
              <el-table-column prop="deleted_count" label="删除数量" width="100"><template #default="{ row }"><el-tag class="vault-tag is-danger hover:scale-105 transition-transform duration-300">{{ row.deleted_count }}</el-tag></template></el-table-column>
              <el-table-column prop="config_snapshot" label="配置快照"><template #default="{ row }"><div class="history-meta">使用次数≤{{ row.config_snapshot?.max_use_count }}, 保留{{ row.config_snapshot?.preserve_days }}天</div></template></el-table-column>
              <el-table-column prop="deleted_passwords_summary" label="删除详情" min-width="200"><template #default="{ row }"><div v-if="row.deleted_passwords_summary && row.deleted_passwords_summary.length > 0" class="history-list"><div v-for="(pwd, idx) in row.deleted_passwords_summary.slice(0, 3)" :key="idx">{{ pwd.rjcode || pwd.filename || '通用密码' }} ({{ pwd.use_count }}次)</div><div v-if="row.deleted_passwords_summary.length > 3" class="muted">等 {{ row.deleted_passwords_summary.length }} 个密码...</div></div><span v-else class="muted">-</span></template></el-table-column>
            </el-table>
            <el-empty v-if="cleanupHistory.length === 0" description="暂无清理记录" />
          </div>
        </div>
      </div>
    </el-dialog>

    <el-dialog
      v-model="showImportDialog"
      :show-close="false"
      :lock-scroll="false"
      align-center
      width="min(680px, calc(100vw - 32px))"
      modal-class="custom-preview-overlay"
      append-to-body
      destroy-on-close
      class="vault-centered-dialog vault-workbench-dialog"
    >
      <div class="window panel-enter glass-shell relative flex w-full max-w-[680px] flex-col overflow-hidden rounded-3xl">
        <div class="window-header flex items-center justify-between px-6 py-4">
          <div class="fm-header-main min-w-0">
            <div class="fm-title-row">
              <h1 class="title truncate text-lg font-bold tracking-tight text-slate-900">批量导入密码</h1>
              <span class="fm-badge">{{ importLineCount }} 条待导入</span>
            </div>
            <p class="mt-1 truncate text-sm text-slate-500">按行粘贴密码列表，系统会在解压链路里自动尝试，不用你额外绑定 RJ。</p>
          </div>
          <button type="button" class="interactive-chip close-button inline-flex size-10 items-center justify-center rounded-full text-slate-400 hover:text-slate-700" @click="showImportDialog = false">
            <el-icon :size="20"><Close /></el-icon>
          </button>
        </div>

        <div class="fm-body flex min-h-0 flex-1 flex-col px-6 pb-5">
          <div class="import-note-card">
            <div class="import-note-title">导入格式说明</div>
            <div class="import-help">
              <p>每行一个密码，系统会尝试解压时使用这些密码。</p>
              <p>系统会自动匹配 RJ 号，无需在导入时指定。</p>
            </div>
          </div>
          <el-input v-model="importText" type="textarea" :rows="10" placeholder="在此粘贴密码列表（每行一个）...&#10;例如：&#10;password123&#10;password456&#10;password789" />

          <div class="dialog-actions">
            <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg shadow-sm hover:bg-slate-50 hover:text-slate-900 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-1 active:scale-95 transition-all duration-300" @click="showImportDialog = false">取消</el-button>
            <el-button class="group relative inline-flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 border border-transparent rounded-lg shadow-sm hover:bg-blue-500 hover:shadow-blue-500/30 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 active:scale-95 transition-all duration-300 disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 disabled:hover:shadow-none" @click="handleImport" :loading="importing">导入 {{ importLineCount }} 个密码</el-button>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, shallowRef, computed, onMounted, watch, nextTick } from 'vue'
import { Plus, Delete, Document, Search, View, Timer, Refresh, Setting, SortDown, SortUp, Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import { passwordApi, cleanupApi } from '../api'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppLottieIcon from '../components/common/AppLottieIcon.vue'
import clipboardIconAnimation from '../assets/anime/Clipboard.lottie'
import deleteIconAnimation from '../assets/anime/Delete icon animation.lottie'

const PAGE_SIZES = [10, 20, 50, 100]
const PAGE_SIZE_STORAGE_KEY = 'kikoeru.ui.passwordVault.pageSize'

function loadPersistedPageSize(fallback) { try { const raw = window.localStorage.getItem(PAGE_SIZE_STORAGE_KEY); const num = Number(raw); if (PAGE_SIZES.includes(num)) return num } catch (_) {} return fallback }
function persistPageSize(size) { try { window.localStorage.setItem(PAGE_SIZE_STORAGE_KEY, String(size)) } catch (_) {} }

const loading = ref(true)
const passwords = shallowRef([])
const passwordTableRef = ref(null)
const selectedRows = ref([])
const searchQuery = ref('')
const passwordSortBy = ref('created_at')
const passwordSortOrder = ref('desc')
const currentPage = ref(1)
const pageSize = ref(loadPersistedPageSize(50))
const totalCount = ref(0)
const isServerPaginated = ref(false)
const showAddDialog = ref(false)
const showImportDialog = ref(false)
const showCleanupDialog = ref(false)
const isEditing = ref(false)
const submitting = ref(false)
const importing = ref(false)
const cleanupLoading = ref(false)
const importText = ref('')
const formRef = ref(null)
const cleanupStatus = ref(null)
const cleanupHistory = shallowRef([])

const form = ref({ id: null, rjcode: '', filename: '', password: '', description: '' })
const rules = { password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { min: 1, max: 255, message: '密码长度应在1-255个字符之间', trigger: 'blur' }] }

const tablePasswords = computed(() => isServerPaginated.value ? passwords.value : passwords.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
const usedPasswordCount = computed(() => passwords.value.filter(item => Number(item?.use_count || 0) > 0).length)
const scopedPasswordCount = computed(() => passwords.value.filter(item => item?.rjcode || item?.filename).length)
const importLineCount = computed(() => importText.value.trim() ? importText.value.trim().split('\n').filter(line => line.trim()).length : 0)

onMounted(() => { loadPasswords(); loadCleanupStatus() })
watch(pageSize, size => { persistPageSize(size) })
watch(showCleanupDialog, value => { if (value) { loadCleanupStatus(); loadCleanupHistory() } })

async function loadPasswords() {
  loading.value = true
  try {
    const params = { sort_by: passwordSortBy.value, sort_order: passwordSortOrder.value, page: currentPage.value, page_size: pageSize.value }
    if (searchQuery.value) params.search = searchQuery.value
    const response = await passwordApi.list(params)
    const rawData = Array.isArray(response) ? response : response.items || []
    isServerPaginated.value = !Array.isArray(response)
    totalCount.value = Array.isArray(response) ? rawData.length : (response.total || 0)
    passwords.value = rawData.map(item => ({ ...item, _formatted_last_used: item.last_used_at ? formatDate(item.last_used_at) : null, _formatted_created_at: formatDate(item.created_at) }))
    selectedRows.value = []
    await nextTick()
    passwordTableRef.value?.clearSelection?.()
    const maxPage = Math.max(1, Math.ceil(totalCount.value / pageSize.value))
    if (currentPage.value > maxPage) { currentPage.value = maxPage; await loadPasswords() }
  } catch (error) {
    console.error('加载密码列表失败:', error)
    ElMessage.error('加载密码列表失败')
  } finally { loading.value = false }
}

function handlePasswordSortChange() { currentPage.value = 1; loadPasswords() }
function togglePasswordSortOrder() { passwordSortOrder.value = passwordSortOrder.value === 'desc' ? 'asc' : 'desc'; currentPage.value = 1; loadPasswords() }
let searchTimeout = null
function handleSearch() { if (searchTimeout) clearTimeout(searchTimeout); searchTimeout = setTimeout(() => { currentPage.value = 1; loadPasswords() }, 300) }
function handleSelectionChange(selection) { selectedRows.value = selection }
function handleEdit(row) { isEditing.value = true; form.value = { id: row.id, rjcode: row.rjcode || '', filename: row.filename || '', password: row.password, description: row.description || '' }; showAddDialog.value = true }

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  const startTime = Date.now()
  try {
    if (isEditing.value) {
      await passwordApi.update(form.value.id, { rjcode: form.value.rjcode || null, filename: form.value.filename || null, password: form.value.password, description: form.value.description || null })
      ElMessage.success('密码已更新')
    } else {
      await passwordApi.create({ rjcode: form.value.rjcode || null, filename: form.value.filename || null, password: form.value.password, description: form.value.description || null, source: 'manual' })
      ElMessage.success('密码已添加')
    }
    const elapsed = Date.now() - startTime
    if (elapsed < 500) await new Promise(r => setTimeout(r, 500 - elapsed))
    showAddDialog.value = false
    resetForm()
    loadPasswords()
  } catch (error) {
    console.error('保存密码失败:', error)
    ElMessage.error('保存失败: ' + (error.response?.data?.detail || error.message))
  } finally { submitting.value = false }
}

async function handleDelete(row) {
  try {
    await showSystemConfirm({ title: '确认删除', message: `确定要删除这个密码吗？${row.rjcode ? `（RJ号: ${row.rjcode}）` : ''}`, confirmText: '删除', cancelText: '取消', tone: 'danger' })
    await passwordApi.delete(row.id)
    ElMessage.success('密码已删除')
    loadPasswords()
  } catch (error) {
    if (error !== 'cancel') { console.error('删除密码失败:', error); ElMessage.error('删除失败') }
  }
}

async function handleBatchDelete() {
  const rowsToDelete = [...selectedRows.value]
  if (rowsToDelete.length === 0) { ElMessage.warning('请先选择要删除的密码'); return }
  try {
    await showSystemConfirm({ title: '确认批量删除', message: `确定要删除选中的 ${rowsToDelete.length} 个密码吗？`, confirmText: '删除', cancelText: '取消', tone: 'danger' })
    let successCount = 0
    for (const row of rowsToDelete) {
      try { await passwordApi.delete(row.id); successCount += 1 } catch (error) { if (error?.response?.status !== 404) throw error }
    }
    ElMessage.success(`已删除 ${successCount} 个密码`)
    selectedRows.value = []
    await nextTick()
    passwordTableRef.value?.clearSelection?.()
    await loadPasswords()
  } catch (error) {
    if (error !== 'cancel') { console.error('批量删除失败:', error); ElMessage.error('删除失败') }
  }
}

async function handleImport() {
  const trimmedText = importText.value.trim()
  if (!trimmedText) { ElMessage.warning('请输入要导入的密码'); return }
  if (importLineCount.value === 0) { ElMessage.warning('请输入有效的密码'); return }
  importing.value = true
  const startTime = Date.now()
  try {
    const { message, imported, skipped } = await passwordApi.importFromText(trimmedText)
    const elapsed = Date.now() - startTime
    if (elapsed < 500) await new Promise(r => setTimeout(r, 500 - elapsed))
    if (skipped > 0) ElMessage.success(`${message}`)
    else ElMessage.success(`成功导入 ${imported} 个密码`)
    showImportDialog.value = false
    importText.value = ''
    loadPasswords()
  } catch (error) {
    console.error('导入失败:', error)
    ElMessage.error('导入失败: ' + (error.response?.data?.detail || error.message))
  } finally { importing.value = false }
}

function resetForm() { form.value = { id: null, rjcode: '', filename: '', password: '', description: '' }; isEditing.value = false; formRef.value?.resetFields() }

function formatDate(dateStr) {
  if (!dateStr) return '-'
  let date
  if (typeof dateStr === 'string') date = dateStr.includes('T') ? new Date(dateStr + 'Z') : new Date(dateStr)
  else date = new Date(dateStr)
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

async function loadCleanupStatus() { try { cleanupStatus.value = await cleanupApi.password.status() } catch (error) { console.error('加载清理状态失败:', error) } }

async function loadCleanupHistory() {
  cleanupLoading.value = true
  try {
    const data = await cleanupApi.password.history(50)
    cleanupHistory.value = (data.history || []).map(row => ({ ...row, _formatted_created_at: formatDate(row.created_at) }))
  } catch (error) {
    console.error('加载清理历史失败:', error)
    ElMessage.error('加载清理历史失败')
  } finally { cleanupLoading.value = false }
}

async function previewCleanup() {
  cleanupLoading.value = true
  try {
    const data = await cleanupApi.password.preview()
    if (data.deleted_count === 0) { ElMessage.info('没有需要清理的密码'); return }
    const passwordList = data.deleted_passwords.map(p => `• ${p.rjcode || p.filename || '通用密码'} (${p.use_count}次使用, ${p.source})`).join('\n')
    await showSystemConfirm({ title: '清理预览', message: `将清理 ${data.deleted_count} 个密码：\n\n${passwordList}\n\n确定要立即清理吗？`, confirmText: '立即清理', cancelText: '取消', tone: 'warning' })
    await runCleanup()
  } catch (error) {
    if (error !== 'cancel') { console.error('预览清理失败:', error); ElMessage.error('预览清理失败: ' + (error.response?.data?.detail || error.message)) }
  } finally { cleanupLoading.value = false }
}

async function runCleanup() {
  cleanupLoading.value = true
  try {
    const data = await cleanupApi.password.run()
    if (data.deleted_count === 0) ElMessage.info('没有需要清理的密码')
    else { ElMessage.success(`成功清理 ${data.deleted_count} 个密码`); loadPasswords(); loadCleanupHistory() }
  } catch (error) {
    console.error('执行清理失败:', error)
    ElMessage.error('执行清理失败: ' + (error.response?.data?.detail || error.message))
  } finally { cleanupLoading.value = false }
}

function formatNextCleanupTime(timeStr) {
  if (!timeStr) return '未设置'
  const date = new Date(timeStr)
  const now = new Date()
  const diff = date - now
  if (diff < 0) return '即将执行'
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
  const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
  if (days > 0) return `${days}天${hours}小时后`
  if (hours > 0) return `${hours}小时${minutes}分钟后`
  return `${minutes}分钟后`
}

function handlePageChange(page) { currentPage.value = page; if (isServerPaginated.value) loadPasswords() }
function handlePageSizeChange(size) { pageSize.value = size; currentPage.value = 1; if (isServerPaginated.value) loadPasswords() }
</script>

<style scoped>
.password-vault {
  max-width: 1480px;
  margin: 0 auto;
  padding: 8px 0 18px;
  color: #1d1d1f;
  font-family: "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 18px;
}

.page-header-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.control-label {
  font-size: 12px;
  letter-spacing: 0.08em;
  color: rgba(29, 29, 31, .48);
}

.page-title {
  margin: 0;
  font-size: 29px;
  font-weight: 600;
  line-height: 1.12;
  letter-spacing: -0.2px;
  color: #1d1d1f;
}

.page-subtitle {
  margin: 8px 0 0;
  font-size: 13px;
  line-height: 1.58;
  color: rgba(29, 29, 31, .5);
}

.pill,
.vault-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(29, 29, 31, .08);
  background: rgba(255, 255, 255, .92);
  color: rgba(29, 29, 31, .72);
  font-size: 12px;
  font-weight: 500;
}

.pill.is-blue,
.vault-tag.is-strong {
  border-color: rgba(0, 113, 227, .16);
  background: #edf4ff;
  color: #0071e3;
}

.pill.dark {
  border-color: rgba(29, 29, 31, .08);
  background: rgba(255, 255, 255, .92);
  color: rgba(29, 29, 31, .72);
}

.vault-tag.is-danger {
  border-color: rgba(215, 0, 21, .16);
  background: #fff5f5;
  color: #d70015;
}

.muted,
.form-tip,
.history-meta,
.import-help,
.cleanup-note {
  color: rgba(29, 29, 31, .5);
}

.main-card,
.table-shell,
.cleanup-banner,
.cleanup-card {
  background: rgba(255, 255, 255, .94);
  border: none;
  box-shadow: 0 12px 30px rgba(0, 0, 0, .05);
}

.main-card {
  border-radius: 18px;
}

.main-card :deep(.el-card__body) {
  padding: 18px;
}

.cleanup-banner {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  margin-bottom: 18px;
  padding: 16px 18px;
  border-radius: 16px;
  background: #f5f5f7;
  box-shadow: none;
}

.banner-title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.08px;
  color: #1d1d1f;
}

.banner-text {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.58;
  color: rgba(29, 29, 31, .5);
}

.banner-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
}

.toolbar-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(420px, 0.95fr);
  gap: 14px;
  margin-bottom: 18px;
}

.toolbar-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 16px 18px;
  border: none;
  border-radius: 16px;
  background: #f5f5f7;
}

.toolbar-filters {
  justify-content: flex-end;
}

.table-shell {
  border-radius: 16px;
  padding: 18px;
}

.vault-state-panel {
  position: relative;
  min-height: 420px;
  display: grid;
  place-items: center;
  gap: 18px;
  padding: 44px 28px;
  overflow: hidden;
  border: 1px solid rgba(219, 228, 244, 0.88);
  border-radius: 28px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(246, 249, 255, 0.96) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.88),
    0 18px 48px rgba(189, 204, 228, 0.18);
}

.vault-state-loading {
  align-content: center;
  justify-content: center;
  text-align: center;
}

.vault-state-empty {
  justify-items: center;
  text-align: center;
}

.state-visual,
.empty-icon-wrap {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
}

.empty-orb {
  position: absolute;
  border-radius: 999px;
  filter: blur(18px);
  opacity: 0.75;
  pointer-events: none;
}

.empty-orb-left {
  width: 220px;
  height: 220px;
  left: 8%;
  top: 18%;
  background: radial-gradient(circle, rgba(147, 197, 253, 0.2) 0%, rgba(191, 219, 254, 0.08) 58%, transparent 80%);
}

.empty-orb-right {
  width: 240px;
  height: 240px;
  right: 9%;
  bottom: 10%;
  background: radial-gradient(circle, rgba(96, 165, 250, 0.18) 0%, rgba(191, 219, 254, 0.08) 56%, transparent 78%);
}

.empty-icon-wrap {
  width: 92px;
  height: 92px;
  border-radius: 28px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.12) 0%, rgba(255, 255, 255, 0.92) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    0 14px 30px rgba(96, 165, 250, 0.15);
}

.empty-icon {
  font-size: 40px;
  color: #2f6bca;
}

.empty-copy {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 8px;
  max-width: 520px;
}

.empty-title {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #163457;
}

.empty-subtitle {
  font-size: 14px;
  line-height: 1.7;
  color: #6b85a5;
}

.empty-actions {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}

.table-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 14px;
}

.table-title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: -0.08px;
  color: #1d1d1f;
}

.table-subtitle {
  font-size: 13px;
  color: rgba(29, 29, 31, .5);
}

.table-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pagination-bar {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}

:deep(.vault-btn.el-button) {
  min-height: 34px;
  padding: 0 14px !important;
  border-radius: 999px;
  box-shadow: none;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: -0.12px;
  transition: color .18s ease, background .18s ease, border-color .18s ease, box-shadow .18s ease, transform .18s ease, opacity .18s ease;
}

:deep(.vault-btn.el-button > span) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.dark-btn {
  background: #0071e3 !important;
  color: #fff !important;
  border: 1px solid #0071e3 !important;
}

.dark-btn:hover {
  background: #0077ed !important;
  border-color: #0077ed !important;
  color: #fff !important;
  box-shadow: 0 8px 18px rgba(0, 113, 227, .2);
  transform: translateY(-1px);
}

.ghost-btn {
  background: #fafafc !important;
  color: rgba(0, 0, 0, .8) !important;
  border: 1px solid rgba(0, 0, 0, .06) !important;
}

@media (max-width: 960px) {
  .vault-state-loading {
    text-align: center;
  }
}

.ghost-btn:hover {
  color: #1d1d1f !important;
  border-color: rgba(0, 0, 0, .1) !important;
  background: #ffffff !important;
  box-shadow: 0 6px 16px rgba(0, 0, 0, .08);
  transform: translateY(-1px);
}

.danger-btn {
  background: #fff5f5 !important;
  color: #d70015 !important;
  border: 1px solid rgba(215, 0, 21, .16) !important;
}

.danger-btn:hover {
  color: #b81d13 !important;
  border-color: rgba(215, 0, 21, .24) !important;
  background: #fff !important;
  box-shadow: 0 6px 16px rgba(215, 0, 21, .1);
  transform: translateY(-1px);
}

.vault-search {
  width: 280px;
}

.sort-btn {
  min-width: 92px;
}

:deep(.vault-search .el-input__wrapper),
:deep(.toolbar-group .el-select__wrapper) {
  min-height: 34px;
  border-radius: 12px;
  background: #f5f5f7;
  box-shadow: inset 0 0 0 1px rgba(29, 29, 31, .06);
  transition: all 0.3s ease !important;
}

:deep(.vault-search .el-input__wrapper:hover),
:deep(.toolbar-group .el-select__wrapper:hover) {
  box-shadow: inset 0 0 0 1px #94a3b8 !important;
}

:deep(.vault-search .el-input__wrapper.is-focus),
:deep(.toolbar-group .el-select__wrapper.is-focused) {
  box-shadow: inset 0 0 0 2px rgba(59, 130, 246, 0.5) !important;
}

.cell {
  display: flex;
  align-items: center;
  min-height: 24px;
}

.center {
  justify-content: center;
}

.password-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(29, 29, 31, .08);
  background: rgba(255, 255, 255, .92);
  color: #1d1d1f;
  font-size: 12px;
}

:deep(.password-table.el-table) {
  --el-table-header-bg-color: #f5f5f7;
  --el-table-row-hover-bg-color: #fafafc;
  border-radius: 14px;
  overflow: hidden;
}

:deep(.password-table .el-table__empty-block) {
  min-height: 280px;
}

:deep(.password-table .el-table__empty-text) {
  width: 100%;
}

:deep(.password-table .el-table__inner-wrapper::before) {
  display: none;
}

:deep(.password-table th.el-table__cell) {
  font-size: 12px;
  font-weight: 500;
  color: rgba(29, 29, 31, .54);
}

:deep(.password-table td.el-table__cell) {
  border-bottom-color: rgba(29, 29, 31, .06);
}

:deep(.password-table .el-table__row) {
  transition: all 0.3s ease;
}

:deep(.password-table .el-table__row:hover) {
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
  z-index: 10;
  position: relative;
}

.actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
}

:deep(.inline-btn.el-button) {
  padding: 0 !important;
  min-height: auto;
  color: #1d1d1f !important;
  font-size: 12px;
  font-weight: 500;
}

:deep(.inline-btn.el-button:hover) {
  color: #0066cc !important;
}

:deep(.inline-btn.danger.el-button:hover) {
  color: #d70015 !important;
}

.vault-centered-dialog :deep(.el-dialog) {
  margin: 0 auto !important;
}

.vault-centered-dialog :deep(.el-dialog__header) {
  display: none;
}

.vault-centered-dialog :deep(.el-dialog__body) {
  padding: 0 !important;
  background: transparent !important;
}

.vault-workbench-dialog :deep(.el-dialog) {
  background: transparent;
  width: auto !important;
  max-width: calc(100vw - 32px) !important;
}

.vault-workbench-dialog .glass-shell {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.76) 0%, rgba(250, 252, 255, 0.7) 100%);
  border: 1px solid rgba(15, 23, 42, 0.06);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow:
    0 24px 80px rgba(148, 163, 184, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.vault-workbench-dialog .window-header {
  border-bottom: 1px solid rgba(226, 232, 240, 0.72);
}

.vault-workbench-dialog .window {
  margin: 0 auto;
}

.fm-header-main {
  min-width: 0;
  flex: 1;
}

.fm-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.fm-badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(96, 165, 250, 0.28);
  background: rgba(239, 246, 255, 0.92);
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid rgba(226, 232, 240, 0.72);
}

.import-note-card {
  margin-bottom: 18px;
  padding: 16px 18px;
  border-radius: 18px;
  border: 1px solid rgba(191, 219, 254, 0.68);
  background:
    linear-gradient(180deg, rgba(239, 246, 255, 0.96) 0%, rgba(248, 250, 252, 0.96) 100%);
}

.import-note-title {
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #1e3a8a;
}

.form-tip {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
}

.cleanup-grid {
  margin-bottom: 18px;
}

.cleanup-card {
  border-radius: 16px;
}

.cleanup-card :deep(.el-card__header) {
  padding: 18px 18px 0;
  border-bottom: none;
  color: rgba(29, 29, 31, .54);
  font-size: 12px;
}

.cleanup-card :deep(.el-card__body) {
  padding: 14px 18px 18px;
}

.cleanup-center {
  text-align: center;
}

.cleanup-value {
  font-size: 20px;
  line-height: 1.2;
  color: #0071e3;
}

.cleanup-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 18px;
}

.settings-btn {
  margin-left: auto;
}

.history-list,
.import-help {
  font-size: 12px;
  line-height: 1.8;
}

.vault-form :deep(.el-form-item) {
  margin-bottom: 20px;
}

.vault-form :deep(.el-input__wrapper),
.vault-form :deep(.el-textarea__inner) {
  border-radius: 16px;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.92),
    0 10px 24px rgba(148, 163, 184, 0.08);
  transition: all 0.3s ease !important;
}

.vault-form :deep(.el-input__wrapper:hover),
.vault-form :deep(.el-textarea__inner:hover) {
  box-shadow: 0 0 0 1px #94a3b8 inset !important;
}

.vault-form :deep(.el-input__wrapper.is-focus),
.vault-form :deep(.el-textarea__inner:focus) {
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.5) inset !important;
}

/* 密码框眼睛图标特效 */
.vault-form :deep(.el-input__password) {
  transition: all 0.3s ease !important;
}
.vault-form :deep(.el-input__password:hover) {
  transform: scale(1.15) rotate(5deg) !important;
  color: #3b82f6 !important;
}

/* 密码框眼睛图标特效 */
:deep(.el-input__password) {
  transition: all 0.3s ease !important;
}
:deep(.el-input__password:hover) {
  transform: scale(1.15) rotate(5deg) !important;
  color: #3b82f6 !important;
}

.vault-workbench-dialog :deep(.el-divider__text) {
  color: #64748b;
  font-weight: 700;
}

@media (max-width: 1200px) {
  .toolbar-shell {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .page-header,
  .table-shell,
  .toolbar-group,
  .cleanup-banner {
    border-radius: 18px;
  }

  .dialog-actions {
    flex-wrap: wrap;
  }

  .pagination-bar {
    overflow-x: auto;
    justify-content: flex-start;
  }

  :deep(.global-pager) {
    min-width: max-content;
  }

  .page-header,
  .cleanup-banner,
  .table-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .banner-meta,
  .table-meta,
  .toolbar-filters,
  .pagination-bar {
    justify-content: flex-start;
  }

  .vault-search {
    width: 100%;
  }

  .settings-btn {
    margin-left: 0;
  }
}
</style>
