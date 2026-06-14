<template>
  <div class="password-vault mx-auto w-full max-w-[1480px] px-1 pb-6 pt-2 text-slate-900">
    <!-- 页头走共享组件 AppPageHeader，右侧 slot 保留三个统计 chip -->
    <AppPageHeader
      :icon="IconKey"
      icon-color="var(--km-nav-passwords-icon)"
      title="解压密码工作台"
      subtitle="集中管理解压密码、作品绑定关系与自动清理规则。同时填写文件名 + RJ 号时，系统会把该文件视为该 RJ，查重/命名/包裹目录都以此为准。"
    >
      <span class="inline-flex h-8 items-center gap-1.5 rounded-full border border-slate-200 bg-white/80 px-3 text-xs font-medium text-slate-600 shadow-sm">
        <IconShield :size="14" :stroke-width="2.2" class="text-slate-400" />总数 <b class="text-slate-800">{{ totalCount }}</b>
      </span>
      <span class="inline-flex h-8 items-center gap-1.5 rounded-full border border-emerald-200/70 bg-emerald-50/70 px-3 text-xs font-medium text-emerald-700">
        <IconSparkles :size="14" :stroke-width="2.2" />已生效 <b>{{ usedPasswordCount }}</b>
      </span>
      <span class="inline-flex h-8 items-center gap-1.5 rounded-full border border-violet-200/70 bg-violet-50/70 px-3 text-xs font-medium text-violet-700">
        <IconDoc :size="14" :stroke-width="2.2" />已绑定 <b>{{ scopedPasswordCount }}</b>
      </span>
    </AppPageHeader>

    <!-- 工具栏 -->
    <section class="vault-toolbar-shell mb-4">
      <div class="vault-toolbar-panel vault-toolbar-panel-actions rounded-2xl border border-slate-200/80 bg-white/80 p-2.5 shadow-sm backdrop-blur">
        <div class="vault-toolbar-main-actions">
          <button type="button" class="vault-btn vault-btn-primary" @click="openAddDialog">
            <span class="vault-btn-icon vault-btn-icon-add"><IconPlus :size="15" :stroke-width="2.4" /></span>
            <span>添加密码</span>
          </button>
          <button type="button" class="vault-btn vault-btn-ghost" @click="showImportDialog = true">
            <span class="vault-btn-icon vault-btn-icon-import"><IconDoc :size="15" :stroke-width="2.2" /></span>
            <span>批量导入</span>
          </button>
          <button type="button" class="vault-btn vault-btn-ghost" @click="showCleanupDialog = true">
            <span class="vault-btn-icon vault-btn-icon-cleanup"><IconSparkles :size="15" :stroke-width="2.2" /></span>
            <span>智能清理</span>
          </button>
          <div class="vault-toolbar-divider"></div>
          <button type="button" class="vault-btn vault-btn-danger" :disabled="!selectedRows.length" @click="handleBatchDelete">
            <span class="vault-btn-icon vault-btn-icon-delete"><IconTrash :size="15" :stroke-width="2.2" /></span>
            <span>批量删除</span>
            <span v-if="selectedRows.length" class="rounded-full bg-rose-100 px-1.5 text-[11px] text-rose-700">{{ selectedRows.length }}</span>
          </button>
          <button type="button" class="vault-btn vault-btn-ghost ml-auto vault-btn-refresh-inline" @click="loadPasswords" :title="'刷新'">
            <span class="vault-btn-icon vault-btn-icon-refresh"><IconRefresh :size="15" :stroke-width="2.2" :class="{ 'animate-spin': loading }" /></span>
            <span>刷新</span>
          </button>
        </div>
      </div>

      <div class="vault-toolbar-panel vault-toolbar-panel-filters rounded-2xl border border-slate-200/80 bg-white/80 p-2.5 shadow-sm backdrop-blur">
        <span class="text-xs font-medium uppercase tracking-wider text-slate-400">排序</span>
        <AppDropdown
          v-model="passwordSortBy"
          class="password-sort-dd"
          :options="passwordSortByOptions"
          :width="128"
          :menu-min-width="160"
          menu-class="password-sort-dd-menu"
          :show-trigger-badge="false"
          @update:model-value="handlePasswordSortChange"
        />
        <button type="button" class="vault-btn vault-btn-ghost !min-w-[84px]" @click="togglePasswordSortOrder">
          <component :is="passwordSortOrder === 'desc' ? IconArrowDown : IconArrowUp" :size="14" :stroke-width="2.4" />
          {{ passwordSortOrder === 'desc' ? '倒序' : '正序' }}
        </button>
        <div class="relative">
          <IconSearch :size="15" :stroke-width="2.2" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input v-model="searchQuery" type="text" placeholder="搜索 RJ 号、文件名或密码"
            class="h-9 w-[280px] rounded-xl border border-slate-200 bg-slate-50/70 pl-9 pr-3 text-[13px] text-slate-700 outline-none transition-all duration-300 placeholder:text-slate-400 hover:border-slate-300 focus:w-[320px] focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-500/20"
            @input="handleSearch" />
        </div>
      </div>
    </section>

    <!-- 主卡片 -->
    <section class="vault-main-panel rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-[0_12px_40px_-12px_rgba(15,23,42,0.12)] backdrop-blur">
      <!-- Loading -->
      <div v-if="loading" class="grid min-h-[420px] place-items-center gap-4 rounded-2xl border border-slate-100 bg-slate-50/50 p-10">
        <AppLoadingAnimation :size="132" variant="block" />
        <div class="text-sm text-slate-500">正在加载密码库…</div>
      </div>

      <!-- Empty -->
      <div v-else-if="!passwords.length" class="relative overflow-hidden rounded-2xl border border-slate-100 bg-gradient-to-b from-white to-slate-50 p-12">
        <AppEmptyState>
          <template #icon>
            <div class="grid size-20 place-items-center rounded-3xl bg-gradient-to-br from-blue-100 via-white to-blue-50 shadow-inner">
              <IconKey :size="40" :stroke-width="1.8" class="text-blue-600" />
            </div>
          </template>
          <template #title><span class="text-[22px] font-bold tracking-tight text-slate-800">还没有录入任何密码</span></template>
          <template #subtitle><span class="text-sm text-slate-500">先录入常用解压密码，解压、匹配、清理链路才会真正串起来。</span></template>
          <template #actions>
            <button type="button" class="vault-btn vault-btn-primary" @click="openAddDialog">
              <IconPlus :size="15" :stroke-width="2.4" />添加第一个密码
            </button>
            <button type="button" class="vault-btn vault-btn-ghost" @click="showImportDialog = true">
              <IconDoc :size="15" :stroke-width="2.2" />批量导入
            </button>
          </template>
        </AppEmptyState>
      </div>

      <!-- Table -->
      <template v-else>
        <div class="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="text-base font-semibold tracking-tight text-slate-800">密码列表</h2>
            <p class="mt-0.5 text-xs text-slate-500">支持批量选择、编辑、删除；双列键值不可同时为空。</p>
          </div>
          <div class="flex items-center gap-2">
            <span class="inline-flex h-7 items-center rounded-full bg-slate-100 px-2.5 text-[11px] font-medium text-slate-600">
              本页 {{ tablePasswords.length }} / 共 {{ totalCount }}
            </span>
          </div>
        </div>

        <el-table ref="passwordTableRef" class="password-table" :data="tablePasswords" style="width:100%"
          @selection-change="handleSelectionChange" row-key="id" stripe>
          <el-table-column type="selection" width="44" />
          <el-table-column prop="rjcode" label="RJ 号" width="130">
            <template #default="{ row }">
              <span v-if="row.rjcode" class="inline-flex h-6 items-center rounded-md bg-blue-50 px-2 font-mono text-[12px] font-medium text-blue-700">{{ row.rjcode }}</span>
              <span v-else class="text-xs text-slate-400">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.filename" class="text-[13px] text-slate-700">{{ row.filename }}</span>
              <span v-else class="text-xs text-slate-400">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="password" label="密码" min-width="180">
            <template #default="{ row }">
              <div class="password-pill-wrap">
                <el-tooltip :content="row.password" placement="top-start" :show-after="260">
                  <span class="password-pill" :title="row.password">{{ row.password }}</span>
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源" width="92">
            <template #default="{ row }">
              <el-tag size="small" :type="row.source === 'manual' ? '' : row.source === 'batch' ? 'success' : 'info'" effect="plain">
                {{ row.source === 'manual' ? '手动' : row.source === 'batch' ? '批量' : '自动' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="use_count" label="使用" width="72" align="center">
            <template #default="{ row }">
              <span class="font-mono text-sm font-semibold text-slate-700">{{ row.use_count }}</span>
            </template>
          </el-table-column>
          <el-table-column label="最后使用" width="170">
            <template #default="{ row }">
              <span v-if="row._formatted_last_used" class="inline-flex items-center gap-1 text-xs text-slate-500">
                <IconClock :size="12" :stroke-width="2.2" />{{ row._formatted_last_used }}
              </span>
              <span v-else class="text-xs text-slate-400">从未使用</span>
            </template>
          </el-table-column>
          <el-table-column label="创建" width="170">
            <template #default="{ row }">
              <span class="text-xs text-slate-500">{{ row._formatted_created_at }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="170" align="center" fixed="right">
            <template #default="{ row }">
              <div class="vault-row-actions">
                <button type="button" class="vault-row-action is-edit" @click="handleEdit(row)" title="编辑">
                  <IconEdit :size="18" :stroke-width="2.3" />
                </button>
                <button type="button" class="vault-row-action is-delete" @click="handleDelete(row)" title="删除">
                  <IconTrash :size="18" :stroke-width="2.3" />
                </button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <div class="vault-mobile-list">
          <article
            v-for="row in tablePasswords"
            :key="`mobile-password-${row.id}`"
            class="vault-mobile-card"
            :class="{ 'is-selected': isMobileRowSelected(row) }"
          >
            <header class="vault-mobile-card-head">
              <label class="vault-mobile-check">
                <input
                  type="checkbox"
                  :checked="isMobileRowSelected(row)"
                  @change="toggleMobileSelection(row, $event.target.checked)"
                >
              </label>
              <div class="vault-mobile-title-wrap">
                <span v-if="row.rjcode" class="vault-mobile-rj">{{ row.rjcode }}</span>
                <span v-else class="vault-mobile-empty">未绑定 RJ</span>
                <span class="vault-mobile-source">{{ row.source === 'manual' ? '手动' : row.source === 'batch' ? '批量' : '自动' }}</span>
              </div>
              <div class="vault-mobile-actions">
                <button type="button" class="vault-mobile-action is-edit" title="编辑" @click="handleEdit(row)">
                  <IconEdit :size="16" :stroke-width="2.3" />
                </button>
                <button type="button" class="vault-mobile-action is-delete" title="删除" @click="handleDelete(row)">
                  <IconTrash :size="16" :stroke-width="2.3" />
                </button>
              </div>
            </header>

            <div class="vault-mobile-field">
              <span class="vault-mobile-label">文件名</span>
              <span class="vault-mobile-value">{{ row.filename || '—' }}</span>
            </div>
            <div class="vault-mobile-field">
              <span class="vault-mobile-label">密码</span>
              <code class="vault-mobile-password">{{ row.password }}</code>
            </div>
            <footer class="vault-mobile-meta">
              <span>使用 {{ row.use_count }}</span>
              <span>{{ row._formatted_last_used ? `最后 ${row._formatted_last_used}` : '从未使用' }}</span>
              <span>{{ row._formatted_created_at }}</span>
            </footer>
          </article>
        </div>

        <div class="mt-4 flex justify-end">
          <el-pagination class="vault-pagination" popper-class="vault-pagination-size-popper" background
            layout="total, sizes, prev, pager, next, jumper"
            :current-page="currentPage" :page-size="pageSize" :page-sizes="PAGE_SIZES" :total="totalCount"
            @current-change="handlePageChange" @size-change="handlePageSizeChange" />
        </div>
      </template>
    </section>

    <Teleport to="body">
      <Transition name="vault-modal">
        <div v-if="showAddDialog" class="vault-modal-layer" @click.self="closeAddDialog">
          <section class="vault-dialog-shell vault-dialog-edit" role="dialog" aria-modal="true" :aria-label="isEditing ? '编辑密码' : '添加密码'">
            <header class="vault-dialog-header">
              <div class="vault-dialog-title-row">
                <div class="vault-dialog-icon vault-dialog-icon-key">
                  <IconKey :size="18" :stroke-width="2.2" />
                </div>
                <div>
                  <div class="vault-dialog-title">{{ isEditing ? '编辑密码' : '添加密码' }}</div>
                  <div class="vault-dialog-subtitle">维护解压密码与作品绑定信息</div>
                </div>
              </div>
              <button type="button" class="vault-icon-btn" aria-label="关闭" @click="closeAddDialog">
                <IconClose :size="16" :stroke-width="2.2" />
              </button>
            </header>

            <div class="vault-dialog-body">
              <p class="vault-dialog-note">
                <IconShield :size="13" :stroke-width="2.2" class="vault-dialog-note-icon" />
                <span>同时填写 <b>文件名</b> + <b>RJ 号</b> 时，系统会把匹配到的压缩包视为该 RJ 作品，查重、重命名和包裹目录都按这个绑定执行。</span>
              </p>

              <div class="vault-form">
                <label class="vault-field">
                  <span class="vault-field-label">RJ 号</span>
                  <input v-model="form.rjcode" class="vault-input" type="text" placeholder="例如 RJ123456（可选）">
                </label>
                <label class="vault-field">
                  <span class="vault-field-label">文件名</span>
                  <input v-model="form.filename" class="vault-input" type="text" placeholder="例如 my_archive.rar（可选）">
                  <span class="vault-field-hint">留空表示不按文件名匹配。</span>
                </label>
                <label class="vault-field">
                  <span class="vault-field-label is-required">密码</span>
                  <AnimatedPasswordInput v-model="form.password" placeholder="请输入解压密码" autocomplete="new-password" />
                  <span v-if="formPasswordError" class="vault-field-error">{{ formPasswordError }}</span>
                </label>
                <label class="vault-field">
                  <span class="vault-field-label">备注</span>
                  <textarea v-model="form.description" class="vault-textarea" rows="2" placeholder="备注或来源说明（可选）"></textarea>
                </label>
              </div>
            </div>

            <footer class="vault-dialog-footer">
              <button type="button" class="vault-btn vault-btn-ghost" @click="closeAddDialog">取消</button>
              <button type="button" class="vault-btn vault-btn-primary" :disabled="submitting" @click="handleSubmit">
                <span v-if="submitting" class="size-3.5 animate-spin rounded-full border-2 border-white/50 border-t-white"></span>
                {{ isEditing ? '保存修改' : '添加密码' }}
              </button>
            </footer>
          </section>
        </div>
      </Transition>

      <Transition name="vault-modal">
        <div v-if="showCleanupDialog" class="vault-modal-layer" @click.self="showCleanupDialog = false">
          <section class="vault-dialog-shell vault-dialog-cleanup" role="dialog" aria-modal="true" aria-label="智能清理">
            <header class="vault-dialog-header">
              <div class="vault-dialog-title-row">
                <div class="vault-dialog-icon vault-dialog-icon-cleanup">
                  <IconSparkles :size="18" :stroke-width="2.2" />
                </div>
                <div>
                  <div class="vault-dialog-title">智能清理</div>
                  <div class="vault-dialog-subtitle">查看规则、预览匹配、确认后再执行</div>
                </div>
              </div>
              <button type="button" class="vault-icon-btn" aria-label="关闭" @click="showCleanupDialog = false">
                <IconClose :size="16" :stroke-width="2.2" />
              </button>
            </header>

            <div class="vault-dialog-body">
              <div class="vault-cleanup-summary">
                <div class="vault-cleanup-meta">
                  <span class="vault-cleanup-label">下次清理</span>
                  <span class="vault-cleanup-value is-info">{{ formatNextCleanupTime(cleanupStatus?.next_cleanup_at) }}</span>
                </div>
                <div class="vault-cleanup-meta">
                  <span class="vault-cleanup-label">已清理</span>
                  <span class="vault-cleanup-value is-success">{{ cleanupStatus?.total_cleaned_count ?? 0 }}</span>
                </div>
                <div class="vault-cleanup-meta">
                  <span class="vault-cleanup-label">规则</span>
                  <span class="vault-cleanup-value is-warning">使用 ≤ {{ cleanupStatus?.max_use_count ?? '-' }}，保留 {{ cleanupStatus?.preserve_days ?? '-' }} 天</span>
                </div>
              </div>

              <div class="vault-cleanup-actions">
                <button type="button" class="vault-btn vault-btn-primary" :disabled="cleanupLoading" @click="previewCleanup">
                  <IconEye :size="15" :stroke-width="2.2" />预览清理
                </button>
                <button type="button" class="vault-btn vault-btn-ghost" :disabled="cleanupLoading" @click="loadCleanupHistory">
                  <IconRefresh :size="15" :stroke-width="2.2" :class="{ 'animate-spin': cleanupLoading }" />刷新历史
                </button>
                <button type="button" class="vault-btn vault-btn-ghost vault-cleanup-settings" @click="goCleanupSettings">
                  <IconSettings :size="15" :stroke-width="2.2" />清理设置
                </button>
              </div>

              <div class="vault-section-divider">
                <span></span><b>清理历史</b><span></span>
              </div>

              <div class="vault-cleanup-table" role="table" aria-label="清理历史">
                <div class="vault-cleanup-row is-head" role="row">
                  <span role="columnheader">时间</span>
                  <span role="columnheader">清理数</span>
                  <span role="columnheader">触发方式</span>
                  <span role="columnheader">备注</span>
                </div>
                <div v-if="cleanupLoading" class="vault-cleanup-empty">正在加载…</div>
                <div v-else-if="!cleanupHistory.length" class="vault-cleanup-empty">No Data</div>
                <div
                  v-for="row in cleanupHistory"
                  v-else
                  :key="row.id || `${row.created_at}-${row.deleted_count}`"
                  class="vault-cleanup-row"
                  role="row"
                >
                  <span role="cell">{{ row._formatted_created_at }}</span>
                  <span role="cell" class="vault-cleanup-count">{{ row.deleted_count }}</span>
                  <span role="cell">
                    <b class="vault-source-badge" :class="{ 'is-manual': row.trigger_type === 'manual' }">{{ row.trigger_type === 'manual' ? '手动' : '自动' }}</b>
                  </span>
                  <span role="cell" class="vault-cleanup-note">{{ row.note || '—' }}</span>
                </div>
              </div>
            </div>
          </section>
        </div>
      </Transition>

      <Transition name="vault-modal">
        <div v-if="showImportDialog" class="vault-modal-layer" @click.self="showImportDialog = false">
          <section class="vault-dialog-shell vault-dialog-import" role="dialog" aria-modal="true" aria-label="批量导入密码">
            <header class="vault-dialog-header">
              <div class="vault-dialog-title-row">
                <div class="vault-dialog-icon vault-dialog-icon-import">
                  <IconDoc :size="20" :stroke-width="2.3" />
                </div>
                <div>
                  <div class="vault-dialog-title">批量导入密码</div>
                  <div class="vault-dialog-subtitle">按行粘贴通用密码，解压链路会自动尝试</div>
                </div>
              </div>
              <button type="button" class="vault-icon-btn" aria-label="关闭" @click="showImportDialog = false">
                <IconClose :size="16" :stroke-width="2.2" />
              </button>
            </header>

            <div class="vault-dialog-body">
              <p class="vault-dialog-note vault-dialog-note-subtle">
                <IconShield :size="13" :stroke-width="2.2" class="vault-dialog-note-icon is-violet" />
                <span>每行一个密码；此处导入的都是通用密码（不绑定 RJ / 文件名），适合添加常见公共解压密码。</span>
              </p>
              <textarea
                v-model="importText"
                class="vault-import-textarea"
                rows="10"
                placeholder="每行一个密码，例如：&#10;pass123&#10;kikoeru&#10;asmr.one"
              ></textarea>
              <div class="vault-import-count">已识别有效密码 <b>{{ importLineCount }}</b> 条</div>
            </div>

            <footer class="vault-dialog-footer">
              <button type="button" class="vault-btn vault-btn-ghost" @click="showImportDialog = false">取消</button>
              <button type="button" class="vault-btn vault-btn-primary" :disabled="importing || importLineCount === 0" @click="handleImport">
                <span v-if="importing" class="size-3.5 animate-spin rounded-full border-2 border-white/50 border-t-white"></span>
                导入 {{ importLineCount }} 个密码
              </button>
            </footer>
          </section>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, shallowRef, computed, onMounted, watch, nextTick } from 'vue'
import {
  Plus as IconPlus,
  Trash2 as IconTrash,
  FileText as IconDoc,
  Search as IconSearch,
  Eye as IconEye,
  Clock as IconClock,
  RefreshCw as IconRefresh,
  Settings as IconSettings,
  PencilLine as IconEdit,
  ArrowUp as IconArrowUp,
  ArrowDown as IconArrowDown,
  X as IconClose,
  KeyRound as IconKey,
  ShieldCheck as IconShield,
  Sparkles as IconSparkles,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { showSystemConfirm } from '../composables/useSystemPrompt'
import { passwordApi, cleanupApi } from '../api'
import AppLoadingAnimation from '../components/common/AppLoadingAnimation.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AppPageHeader from '../components/common/AppPageHeader.vue'
import AppDropdown from '../components/common/AppDropdown.vue'
import AnimatedPasswordInput from '../components/common/AnimatedPasswordInput.vue'

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

// 密码档案排序选项
const passwordSortByOptions = [
  { value: 'created_at', label: '创建时间' },
  { value: 'updated_at', label: '更新时间' },
  { value: 'rjcode', label: 'RJ 号' },
  { value: 'filename', label: '文件名' },
  { value: 'use_count', label: '使用次数' },
]
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
const formPasswordError = ref('')
const cleanupStatus = ref(null)
const cleanupHistory = shallowRef([])

const form = ref({ id: null, rjcode: '', filename: '', password: '', description: '' })

const tablePasswords = computed(() => isServerPaginated.value ? passwords.value : passwords.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
const usedPasswordCount = computed(() => passwords.value.filter(item => Number(item?.use_count || 0) > 0).length)
const scopedPasswordCount = computed(() => passwords.value.filter(item => item?.rjcode || item?.filename).length)
const importLineCount = computed(() => importText.value.trim() ? importText.value.trim().split('\n').filter(line => line.trim()).length : 0)

onMounted(() => { loadPasswords() })
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
function isMobileRowSelected(row) { return selectedRows.value.some(item => item.id === row.id) }
function toggleMobileSelection(row, checked) {
  if (checked) {
    if (!isMobileRowSelected(row)) selectedRows.value = [...selectedRows.value, row]
    return
  }
  selectedRows.value = selectedRows.value.filter(item => item.id !== row.id)
}
function openAddDialog() {
  resetForm()
  showAddDialog.value = true
}

function closeAddDialog() {
  showAddDialog.value = false
  resetForm()
}

function handleEdit(row) {
  formPasswordError.value = ''
  isEditing.value = true
  form.value = { id: row.id, rjcode: row.rjcode || '', filename: row.filename || '', password: row.password, description: row.description || '' }
  showAddDialog.value = true
}

function validatePasswordForm() {
  const password = String(form.value.password || '')
  if (!password.trim()) {
    formPasswordError.value = '请输入密码'
    return false
  }
  if (password.length > 255) {
    formPasswordError.value = '密码长度应在 1-255 个字符之间'
    return false
  }
  formPasswordError.value = ''
  return true
}

async function handleSubmit() {
  if (!validatePasswordForm()) return
  submitting.value = true
  const startTime = Date.now()
  try {
    if (isEditing.value) {
      await passwordApi.update(form.value.id, { rjcode: form.value.rjcode || null, filename: form.value.filename || null, password: form.value.password, description: form.value.description || null })
      ElMessage.success('密码已更新')
    } else {
      const result = await passwordApi.create({ rjcode: form.value.rjcode || null, filename: form.value.filename || null, password: form.value.password, description: form.value.description || null, source: 'manual' })
      if (result?.merged) ElMessage.info('该通用密码已存在，已合并到现有记录')
      else ElMessage.success('密码已添加')
    }
    const elapsed = Date.now() - startTime
    if (elapsed < 500) await new Promise(r => setTimeout(r, 500 - elapsed))
    closeAddDialog()
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

function resetForm() {
  form.value = { id: null, rjcode: '', filename: '', password: '', description: '' }
  isEditing.value = false
  formPasswordError.value = ''
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  let date
  if (typeof dateStr === 'string') {
    const raw = dateStr.trim()
    const hasExplicitTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
    const normalized = hasExplicitTimezone ? raw : raw.replace(' ', 'T')
    date = new Date(normalized)
  } else date = new Date(dateStr)
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

function goCleanupSettings() {
  window.location.href = '/settings#cleanup'
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
  font-family: "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
}

/* ============ 按钮 ============ */
.vault-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  position: relative;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: -0.1px;
  white-space: nowrap;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.vault-btn:hover { transform: translateY(-2px) scale(1.02); }
.vault-btn:active:not(:disabled) { transform: scale(0.96); }
/* disabled：仅 opacity + cursor，不重置 transform/shadow，避免 hover 中点击瞬间塌回闪烁 */
.vault-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.vault-btn-primary {
  background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
}
.vault-btn-primary:hover { box-shadow: 0 8px 20px rgba(37, 99, 235, 0.35); }

.vault-btn-ghost {
  background: rgba(248, 250, 252, 0.8);
  color: #334155;
  border-color: rgba(203, 213, 225, 0.7);
}
.vault-btn-ghost:hover {
  background: #ffffff;
  border-color: rgba(148, 163, 184, 0.7);
  color: #0f172a;
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08);
}

.vault-btn-danger {
  background: rgba(254, 242, 242, 0.8);
  color: #dc2626;
  border-color: rgba(252, 165, 165, 0.7);
}
.vault-btn-danger:hover {
  background: #fff;
  border-color: rgba(239, 68, 68, 0.6);
  box-shadow: 0 6px 14px rgba(220, 38, 38, 0.15);
}

.vault-toolbar-panel {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.vault-toolbar-shell {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.vault-toolbar-panel-actions {
  flex: 0 1 auto;
  min-width: 0;
}

.vault-toolbar-panel-filters {
  flex: 1 1 420px;
  justify-content: flex-end;
  min-width: min(100%, 420px);
}

.vault-toolbar-main-actions {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.vault-btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  border: 1px solid transparent;
  transition: inherit;
}

.vault-toolbar-btn:hover .vault-btn-icon {
  transform: rotate(-8deg) scale(1.08);
}

.vault-toolbar-divider {
  width: 1px;
  align-self: center;
  height: 26px;
  margin: 0 2px;
  background: linear-gradient(180deg, rgba(148, 163, 184, 0), rgba(148, 163, 184, 0.7), rgba(148, 163, 184, 0));
}

.vault-btn-refresh-inline {
  margin-left: auto;
}

.vault-btn:hover .vault-btn-icon {
  transform: translateY(-1px) scale(1.05);
}

.vault-btn-icon-add {
  color: #1d4ed8;
  background: rgba(219, 234, 254, 0.78);
  border-color: rgba(96, 165, 250, 0.18);
}

.vault-btn-icon-import {
  color: #7c3aed;
  background: rgba(237, 233, 254, 0.78);
  border-color: rgba(167, 139, 250, 0.2);
}

.vault-btn-icon-cleanup {
  color: #0f766e;
  background: rgba(204, 251, 241, 0.78);
  border-color: rgba(45, 212, 191, 0.18);
}

.vault-btn-icon-delete {
  color: #be123c;
  background: rgba(255, 228, 230, 0.78);
  border-color: rgba(251, 113, 133, 0.18);
}

.vault-btn-icon-refresh {
  color: #475569;
  background: rgba(241, 245, 249, 0.78);
  border-color: rgba(148, 163, 184, 0.18);
}

@media (max-width: 960px) {
  .vault-toolbar-shell {
    align-items: stretch;
  }

  .vault-toolbar-panel-actions,
  .vault-toolbar-panel-filters {
    flex-basis: 100%;
  }

  .vault-toolbar-divider {
    display: none;
  }

  .vault-btn-refresh-inline {
    margin-left: 0;
  }
}

@media (max-width: 640px) {
  .vault-toolbar-main-actions > .vault-btn {
    flex: 1 1 calc(50% - 10px);
  }

  /* 搜索框移动端全宽，覆盖 Tailwind w-[280px] focus:w-[320px] inline class */
  .vault-toolbar-panel-filters input[type="text"] {
    width: 100% !important;
    min-width: 0 !important;
  }
  .vault-toolbar-panel-filters input[type="text"]:focus {
    width: 100% !important;
  }
  .vault-toolbar-panel-filters > .relative {
    flex: 1 1 100%;
    min-width: 0;
  }

  .vault-btn-refresh-inline {
    flex-basis: 100%;
  }

  .vault-toolbar-panel-filters {
    justify-content: flex-start;
  }
}

.vault-icon-btn {
  display: inline-grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(241, 245, 249, 0.8);
  color: #64748b;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.vault-icon-btn:hover { transform: translateY(-2px) scale(1.05); color: #0f172a; background: #ffffff; border-color: rgba(203, 213, 225, 0.8); }
.vault-icon-btn:active { transform: scale(0.95); }

/* ============ 表格 ============ */
:deep(.password-table.el-table) {
  --el-table-header-bg-color: #f8fafc;
  --el-table-row-hover-bg-color: #f8fafc;
  border-radius: 12px;
  overflow: hidden;
}
:deep(.password-table .el-table__inner-wrapper::before) { display: none; }
:deep(.password-table th.el-table__cell) {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #64748b;
  background: #f8fafc !important;
}
:deep(.password-table td.el-table__cell) { border-bottom-color: rgba(226, 232, 240, 0.7); }
:deep(.password-table .el-table__row) { transition: all 0.25s ease; }
:deep(.password-table .el-table__row:hover) { background: #f8fafc !important; }

:global(html.kikoerumanager-dark body #app .password-vault .vault-toolbar-shell.vault-toolbar-shell),
:global(html.kikoerumanager-dark body #app .password-vault .vault-toolbar-panel.vault-toolbar-panel),
:global(html.kikoerumanager-dark body #app .password-vault .vault-main-panel.vault-main-panel),
:global(body.kikoerumanager-dark #app .password-vault .vault-toolbar-shell.vault-toolbar-shell),
:global(body.kikoerumanager-dark #app .password-vault .vault-toolbar-panel.vault-toolbar-panel),
:global(body.kikoerumanager-dark #app .password-vault .vault-main-panel.vault-main-panel) {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .password-vault .password-table.el-table),
:global(html.kikoerumanager-dark body #app .password-vault .password-table .el-table__inner-wrapper),
:global(html.kikoerumanager-dark body #app .password-vault .password-table .el-table__body-wrapper),
:global(html.kikoerumanager-dark body #app .password-vault .password-table .el-table__header-wrapper),
:global(body.kikoerumanager-dark #app .password-vault .password-table.el-table),
:global(body.kikoerumanager-dark #app .password-vault .password-table .el-table__inner-wrapper),
:global(body.kikoerumanager-dark #app .password-vault .password-table .el-table__body-wrapper),
:global(body.kikoerumanager-dark #app .password-vault .password-table .el-table__header-wrapper) {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .password-vault .password-table th.el-table__cell),
:global(html.kikoerumanager-dark body #app .password-vault .password-table td.el-table__cell),
:global(html.kikoerumanager-dark body #app .password-vault .password-table tr),
:global(body.kikoerumanager-dark #app .password-vault .password-table th.el-table__cell),
:global(body.kikoerumanager-dark #app .password-vault .password-table td.el-table__cell),
:global(body.kikoerumanager-dark #app .password-vault .password-table tr) {
  background: transparent !important;
  background-color: transparent !important;
}

:global(html.kikoerumanager-dark body #app .password-vault .password-table th.el-table__cell),
:global(body.kikoerumanager-dark #app .password-vault .password-table th.el-table__cell) {
  border-bottom-color: rgba(148, 163, 184, 0.18) !important;
}

:global(html.kikoerumanager-dark body #app .password-vault .password-table td.el-table__cell),
:global(body.kikoerumanager-dark #app .password-vault .password-table td.el-table__cell) {
  border-bottom-color: rgba(148, 163, 184, 0.12) !important;
}

:global(html.kikoerumanager-dark body #app .password-vault .password-table .el-table__row:hover > td.el-table__cell),
:global(body.kikoerumanager-dark #app .password-vault .password-table .el-table__row:hover > td.el-table__cell) {
  background: rgba(59, 130, 246, 0.08) !important;
}

:global(html.kikoerumanager-dark body #app .password-vault .vault-mobile-card.vault-mobile-card),
:global(body.kikoerumanager-dark #app .password-vault .vault-mobile-card.vault-mobile-card) {
  background: transparent !important;
  background-image: none !important;
  box-shadow: none !important;
}

:global(html.kikoerumanager-dark body #app .password-vault .vault-mobile-card.vault-mobile-card.is-selected),
:global(body.kikoerumanager-dark #app .password-vault .vault-mobile-card.vault-mobile-card.is-selected) {
  background: rgba(59, 130, 246, 0.08) !important;
  border-color: rgba(96, 165, 250, 0.38) !important;
}

.vault-row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.vault-row-action {
  display: inline-flex;
  width: 46px;
  height: 46px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.vault-row-action:hover {
  transform: translateY(-2px) scale(1.02);
}

.vault-row-action:active {
  transform: scale(0.96);
}

.vault-row-action.is-edit:hover {
  border-color: rgba(59, 130, 246, 0.22);
  background: rgba(59, 130, 246, 0.08);
  color: #2563eb;
}

.vault-row-action.is-delete:hover {
  border-color: rgba(244, 63, 94, 0.22);
  background: rgba(244, 63, 94, 0.08);
  color: #e11d48;
}

.password-pill-wrap {
  width: 100%;
  min-width: 0;
}

.password-pill {
  display: block;
  max-width: 100%;
  height: 28px;
  line-height: 26px;
  box-sizing: border-box;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 10px;
  border: 1px solid rgba(203, 213, 225, 0.85);
  background: rgba(248, 250, 252, 0.88);
  padding: 0 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 12px;
  color: #334155;
}

.vault-mobile-list {
  display: none;
}

/* ============ 分页 ============ */
.vault-pagination.el-pagination {
  --el-pagination-button-width: 34px;
  --el-pagination-button-height: 34px;
  --el-pagination-button-bg-color: transparent;
  --el-pagination-hover-color: #0f172a;
  align-items: center;
  gap: 10px;
  color: #64748b;
  font-weight: 700;
}

.vault-pagination.el-pagination :deep(.el-pager) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.vault-pagination.el-pagination :deep(.el-pagination__total),
.vault-pagination.el-pagination :deep(.el-pagination__jump),
.vault-pagination.el-pagination :deep(.el-pagination__goto),
.vault-pagination.el-pagination :deep(.el-pagination__classifier) {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.vault-pagination.el-pagination.is-background :deep(.btn-prev),
.vault-pagination.el-pagination.is-background :deep(.btn-next),
.vault-pagination.el-pagination.is-background :deep(.el-pager li),
.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-select__wrapper),
.vault-pagination.el-pagination :deep(.el-pagination__jump .el-input__wrapper) {
  min-width: 34px;
  height: 34px;
  margin: 0;
  border: 1px solid rgba(148, 163, 184, 0.26);
  border-radius: 12px;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.86), rgba(248, 250, 252, 0.64)),
    rgba(255, 255, 255, 0.7) !important;
  color: #334155 !important;
  box-shadow: none !important;
  backdrop-filter: blur(16px) saturate(130%);
  -webkit-backdrop-filter: blur(16px) saturate(130%);
  transition:
    background-color 0.22s ease,
    border-color 0.22s ease,
    color 0.22s ease,
    transform 0.24s cubic-bezier(0.22, 1, 0.36, 1);
}

.vault-pagination.el-pagination.is-background :deep(.btn-prev:hover:not(:disabled)),
.vault-pagination.el-pagination.is-background :deep(.btn-next:hover:not(:disabled)),
.vault-pagination.el-pagination.is-background :deep(.el-pager li:hover),
.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-select__wrapper:hover),
.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-select__wrapper.is-hovering),
.vault-pagination.el-pagination :deep(.el-pagination__jump .el-input__wrapper:hover),
.vault-pagination.el-pagination :deep(.el-pagination__jump .el-input__wrapper.is-focus) {
  border-color: rgba(100, 116, 139, 0.36);
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(241, 245, 249, 0.74)),
    rgba(255, 255, 255, 0.76) !important;
  color: #0f172a !important;
  transform: translateY(-1px);
}

.vault-pagination.el-pagination.is-background :deep(.el-pager li.is-active) {
  border-color: rgba(15, 23, 42, 0.18);
  background: #111827 !important;
  color: #ffffff !important;
}

.vault-pagination.el-pagination.is-background :deep(.btn-prev:disabled),
.vault-pagination.el-pagination.is-background :deep(.btn-next:disabled),
.vault-pagination.el-pagination.is-background :deep(.btn-prev.is-disabled),
.vault-pagination.el-pagination.is-background :deep(.btn-next.is-disabled) {
  background: rgba(241, 245, 249, 0.54) !important;
  color: #cbd5e1 !important;
  opacity: 0.72;
  transform: none;
}

.vault-pagination.el-pagination :deep(.el-pagination__sizes) {
  margin-right: 0;
}

.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-select__wrapper) {
  min-width: 116px;
  padding: 0 12px;
}

.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-select__placeholder),
.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-select__selected-item),
.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-select__selected-item span),
.vault-pagination.el-pagination :deep(.el-pagination__jump .el-input__inner) {
  color: #334155 !important;
  -webkit-text-fill-color: #334155;
  font-size: 12px;
  font-weight: 800;
}

.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-select__caret),
.vault-pagination.el-pagination :deep(.el-pagination__sizes .el-icon) {
  color: #94a3b8;
}

.vault-pagination.el-pagination :deep(.el-pagination__jump .el-input) {
  width: 54px;
}

.vault-pagination.el-pagination :deep(.el-pagination__jump .el-input__wrapper) {
  width: 54px;
  min-width: 54px;
  padding: 0 10px;
}

.vault-pagination.el-pagination :deep(.el-pagination__jump .el-input__inner) {
  height: 32px;
  padding: 0;
  text-align: center;
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
}

:global(.vault-pagination-size-popper.el-popper) {
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.24) !important;
  border-radius: 14px !important;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(248, 250, 252, 0.76)),
    rgba(255, 255, 255, 0.86) !important;
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.14) !important;
  backdrop-filter: blur(18px) saturate(135%) !important;
  -webkit-backdrop-filter: blur(18px) saturate(135%) !important;
}

:global(.vault-pagination-size-popper .el-select-dropdown) {
  min-width: 116px !important;
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
}

:global(.vault-pagination-size-popper .el-select-dropdown__list) {
  padding: 6px !important;
}

:global(.vault-pagination-size-popper .el-select-dropdown__item) {
  height: 32px !important;
  margin: 2px 0 !important;
  border-radius: 10px !important;
  background: transparent !important;
  color: #475569 !important;
  font-size: 12px !important;
  font-weight: 700 !important;
  transition:
    background-color 0.18s ease,
    color 0.18s ease,
    transform 0.2s cubic-bezier(0.22, 1, 0.36, 1) !important;
}

:global(.vault-pagination-size-popper .el-select-dropdown__item:hover),
:global(.vault-pagination-size-popper .el-select-dropdown__item.is-hovering) {
  background: #eef0f3 !important;
  color: #0f172a !important;
  transform: translateY(-1px);
}

:global(.vault-pagination-size-popper .el-select-dropdown__item.is-selected) {
  background: #e2e6ec !important;
  color: #111827 !important;
}

:global(.vault-pagination-size-popper .el-popper__arrow::before) {
  border-color: rgba(148, 163, 184, 0.24) !important;
  background: rgba(255, 255, 255, 0.9) !important;
}

/* ============ 弹框 ============ */
.vault-modal-layer {
  position: fixed;
  inset: 0;
  z-index: 2700;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.24);
}

.vault-dialog-shell {
  display: flex;
  flex-direction: column;
  width: min(560px, calc(100vw - 32px));
  max-height: calc(100vh - 80px);
  overflow: hidden;
  border-radius: 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(249, 250, 252, 0.96) 100%);
  border: 1px solid rgba(226, 232, 240, 0.65);
  box-shadow: 0 24px 64px -24px rgba(15, 23, 42, 0.28);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.vault-dialog-cleanup {
  width: min(880px, calc(100vw - 32px));
}

.vault-dialog-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.vault-dialog-icon {
  display: inline-grid;
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  place-items: center;
  border-radius: 14px;
  border: 1px solid rgba(203, 213, 225, 0.76);
}

.vault-dialog-icon-key {
  color: #2563eb;
  background: #eff6ff;
}

.vault-dialog-icon-cleanup {
  color: #0f766e;
  background: #ccfbf1;
}

.vault-dialog-icon-import {
  color: #7c3aed;
  background: #f5f3ff;
}

.vault-dialog-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.2;
}

.vault-dialog-subtitle {
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.35;
}

.vault-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(226, 232, 240, 0.7);
  background: rgba(255, 255, 255, 0.6);
}

.vault-dialog-body {
  padding: 18px 18px 16px;
  flex: 1;
  overflow: hidden;
}

.vault-dialog-note b {
  font-weight: 600;
  color: #334155;
}

.vault-dialog-note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-bottom: 14px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(239, 246, 255, 0.78);
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.vault-dialog-note-icon {
  margin-top: 3px;
  flex-shrink: 0;
  color: #2563eb;
}

.vault-dialog-note-icon.is-violet {
  color: #7c3aed;
}

.vault-dialog-note-subtle b {
  color: #475569;
}

.vault-form {
  display: grid;
  gap: 13px;
}

.vault-field {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
}

.vault-field-label {
  padding-top: 11px;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
  text-align: right;
}

.vault-field-label.is-required::before {
  content: "* ";
  color: #ef4444;
}

.vault-field-hint,
.vault-field-error {
  grid-column: 2;
  margin-top: -5px;
  font-size: 11px;
  line-height: 1.45;
}

.vault-field-hint {
  color: #94a3b8;
}

.vault-field-error {
  color: #e11d48;
}

.vault-input,
.vault-textarea,
.vault-import-textarea {
  width: 100%;
  border: 0;
  border-radius: 12px;
  background: #ffffff;
  color: #0f172a;
  outline: none;
  box-shadow: inset 0 0 0 1px rgba(203, 213, 225, 0.82);
  transition: box-shadow 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.vault-input {
  height: 42px;
  padding: 0 12px;
  font-size: 14px;
}

.vault-textarea,
.vault-import-textarea {
  min-height: 66px;
  resize: vertical;
  padding: 10px 12px;
  font-size: 14px;
  line-height: 1.55;
}

.vault-input:hover,
.vault-textarea:hover,
.vault-import-textarea:hover {
  background: #ffffff;
  box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.9);
}

.vault-input:focus,
.vault-textarea:focus,
.vault-import-textarea:focus {
  background: #ffffff;
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.95), 0 0 0 4px rgba(191, 219, 254, 0.42);
}

.vault-input::placeholder,
.vault-textarea::placeholder,
.vault-import-textarea::placeholder {
  color: #94a3b8;
}

.vault-form :deep(.animated-password-input__field) {
  background: #ffffff;
}

.vault-cleanup-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}

.vault-cleanup-meta {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  min-height: 66px;
  border-radius: 12px;
  border: 1px solid rgba(226, 232, 240, 0.85);
  background: rgba(248, 250, 252, 0.72);
  padding: 8px 10px;
}

.vault-cleanup-label {
  font-size: 11px;
  font-weight: 600;
  color: #94a3b8;
  letter-spacing: 0.03em;
}

.vault-cleanup-value {
  font-size: 13px;
  font-weight: 700;
  line-height: 1.3;
}

.vault-cleanup-value.is-info {
  color: #2563eb;
}

.vault-cleanup-value.is-success {
  color: #059669;
}

.vault-cleanup-value.is-warning {
  color: #d97706;
}

.vault-cleanup-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

.vault-cleanup-settings {
  margin-left: auto;
}

.vault-section-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 0 12px;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.vault-section-divider span {
  height: 1px;
  flex: 1;
  background: rgba(203, 213, 225, 0.9);
}

.vault-cleanup-table {
  overflow: hidden;
  border: 1px solid rgba(226, 232, 240, 0.86);
  border-radius: 14px;
  background: #ffffff;
}

.vault-cleanup-row {
  display: grid;
  grid-template-columns: 180px 90px 110px minmax(0, 1fr);
  min-height: 42px;
  align-items: center;
  gap: 14px;
  padding: 0 14px;
  border-top: 1px solid rgba(226, 232, 240, 0.74);
  color: #475569;
  font-size: 12px;
}

.vault-cleanup-row.is-head {
  min-height: 46px;
  border-top: 0;
  background: #f8fafc;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.vault-cleanup-count {
  color: #0f172a;
  font-weight: 700;
}

.vault-cleanup-note {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vault-cleanup-empty {
  display: grid;
  min-height: 76px;
  place-items: center;
  border-top: 1px solid rgba(226, 232, 240, 0.74);
  color: #94a3b8;
  font-size: 14px;
}

.vault-source-badge {
  display: inline-flex;
  height: 22px;
  align-items: center;
  border-radius: 7px;
  border: 1px solid rgba(203, 213, 225, 0.8);
  background: rgba(248, 250, 252, 0.9);
  padding: 0 8px;
  color: #64748b;
  font-size: 11px;
}

.vault-source-badge.is-manual {
  border-color: rgba(251, 191, 36, 0.42);
  background: rgba(254, 243, 199, 0.78);
  color: #b45309;
}

.vault-import-count {
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
}

.vault-import-count b {
  color: #0f172a;
}

.vault-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  background: rgba(248, 250, 252, 0.7);
}

.vault-form input:-webkit-autofill,
.vault-form input:-webkit-autofill:hover,
.vault-form input:-webkit-autofill:focus,
.vault-form textarea:-webkit-autofill,
.vault-form textarea:-webkit-autofill:hover,
.vault-form textarea:-webkit-autofill:focus,
.vault-import-textarea:-webkit-autofill,
.vault-import-textarea:-webkit-autofill:hover,
.vault-import-textarea:-webkit-autofill:focus {
  -webkit-text-fill-color: #0f172a !important;
  box-shadow: 0 0 0 1000px #ffffff inset !important;
  transition: background-color 9999s ease-out 0s;
}

.vault-modal-enter-active,
.vault-modal-leave-active {
  transition: opacity 0.22s ease;
}

.vault-modal-enter-active .vault-dialog-shell,
.vault-modal-leave-active .vault-dialog-shell {
  transition: transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease;
}

.vault-modal-enter-from,
.vault-modal-leave-to {
  opacity: 0;
}

.vault-modal-enter-from .vault-dialog-shell,
.vault-modal-leave-to .vault-dialog-shell {
  opacity: 0;
  transform: translateY(14px) scale(0.96);
}

/* ============ 响应式 ============ */
@media (max-width: 960px) {
  .password-vault { padding-left: 12px; padding-right: 12px; }
}

@media (max-width: 640px) {
  .password-vault {
    max-width: 100vw;
    padding-left: 10px !important;
    padding-right: 10px !important;
    overflow-x: hidden;
  }
  .vault-toolbar-shell,
  .vault-toolbar-panel,
  .vault-toolbar-main-actions,
  .vault-toolbar-panel-filters {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    overflow-x: hidden;
  }
  .vault-toolbar-panel {
    padding: 8px !important;
    border-radius: 14px !important;
  }
  .vault-btn {
    min-width: 0;
    height: 34px;
    padding: 0 10px;
    font-size: 12px;
  }
  .vault-toolbar-main-actions {
    gap: 7px;
  }
  .vault-toolbar-panel-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .vault-toolbar-panel-filters :deep(.app-dropdown) {
    min-width: 0;
  }
  :deep(.password-table.el-table) {
    display: none;
  }
  .vault-mobile-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: 100%;
    max-width: 100%;
    min-width: 0;
  }
  .vault-mobile-card {
    width: 100%;
    max-width: 100%;
    min-width: 0;
    border-radius: 16px;
    border: 1px solid rgba(226, 232, 240, 0.82);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.7));
    padding: 10px;
    box-shadow: 0 10px 24px -18px rgba(15, 23, 42, 0.28);
    overflow: hidden;
    transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  .vault-mobile-card.is-selected {
    border-color: rgba(59, 130, 246, 0.38);
    box-shadow: 0 12px 28px -18px rgba(37, 99, 235, 0.45);
  }
  .vault-mobile-card-head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .vault-mobile-check {
    display: inline-flex;
    flex: 0 0 auto;
  }
  .vault-mobile-check input {
    width: 15px;
    height: 15px;
    accent-color: #2563eb;
  }
  .vault-mobile-title-wrap {
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .vault-mobile-rj {
    display: inline-flex;
    max-width: 100%;
    height: 23px;
    align-items: center;
    border-radius: 8px;
    background: #eff6ff;
    padding: 0 8px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 12px;
    font-weight: 700;
    color: #2563eb;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .vault-mobile-empty {
    font-size: 12px;
    font-weight: 700;
    color: #94a3b8;
  }
  .vault-mobile-source {
    display: inline-flex;
    height: 21px;
    align-items: center;
    border-radius: 999px;
    background: rgba(241, 245, 249, 0.9);
    padding: 0 7px;
    font-size: 10.5px;
    font-weight: 700;
    color: #64748b;
  }
  .vault-mobile-actions {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .vault-mobile-action {
    display: inline-flex;
    width: 34px;
    height: 34px;
    align-items: center;
    justify-content: center;
    border: 0;
    border-radius: 10px;
    background: transparent;
    cursor: pointer;
    transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  .vault-mobile-action:hover {
    transform: translateY(-2px) scale(1.02);
  }
  .vault-mobile-action:active {
    transform: scale(0.96);
  }
  .vault-mobile-field {
    display: grid;
    grid-template-columns: 54px minmax(0, 1fr);
    gap: 8px;
    margin-top: 8px;
    min-width: 0;
  }
  .vault-mobile-label {
    padding-top: 2px;
    font-size: 11px;
    font-weight: 700;
    color: #94a3b8;
  }
  .vault-mobile-value,
  .vault-mobile-password {
    min-width: 0;
    max-width: 100%;
    font-size: 12px;
    line-height: 1.5;
    word-break: break-all;
    overflow-wrap: anywhere;
  }
  .vault-mobile-value {
    color: #334155;
  }
  .vault-mobile-password {
    display: block;
    border-radius: 10px;
    border: 1px solid rgba(203, 213, 225, 0.72);
    background: rgba(255, 255, 255, 0.78);
    padding: 6px 8px;
    color: #0f172a;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
  .vault-mobile-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-top: 9px;
    padding-top: 9px;
    border-top: 1px dashed rgba(203, 213, 225, 0.78);
    color: #64748b;
    font-size: 11px;
    line-height: 1.35;
  }
  .vault-mobile-meta span {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .password-vault :deep(.el-pagination) {
    width: 100%;
    justify-content: center;
    flex-wrap: wrap;
    gap: 6px;
  }
  .password-vault :deep(.el-pagination__sizes),
  .password-vault :deep(.el-pagination__jump) {
    display: none;
  }
  .vault-modal-layer {
    padding: 0;
    place-items: stretch;
  }
  .vault-dialog-shell {
    width: 100vw;
    max-width: 100vw;
    max-height: 100dvh;
    min-height: 100dvh;
    border-radius: 0;
  }
  .vault-dialog-header {
    padding: 14px;
  }
  .vault-dialog-body {
    padding: 14px;
  }
  .vault-dialog-footer {
    padding: 10px 14px calc(10px + env(safe-area-inset-bottom));
  }
  .vault-dialog-footer .vault-btn {
    flex: 1;
  }
  .vault-field {
    grid-template-columns: 1fr;
    gap: 5px;
  }
  .vault-field-label {
    padding-top: 0;
    text-align: left;
  }
  .vault-field-hint,
  .vault-field-error {
    grid-column: auto;
    margin-top: -1px;
  }
  .vault-cleanup-summary {
    grid-template-columns: 1fr;
  }
  .vault-cleanup-actions {
    align-items: stretch;
  }
  .vault-cleanup-actions .vault-btn,
  .vault-cleanup-settings {
    flex: 1 1 calc(50% - 6px);
    margin-left: 0;
  }
  .vault-cleanup-row {
    grid-template-columns: minmax(0, 1fr) 64px 72px;
  }
  .vault-cleanup-row span:nth-child(4) {
    display: none;
  }
}

</style>
