<template>
  <div class="password-vault mx-auto w-full max-w-[1480px] px-1 pb-6 pt-2 text-slate-900">
    <!-- 顶部标题 -->
    <header class="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div class="min-w-0">
        <div class="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-blue-600/80">
          <IconKey :size="13" :stroke-width="2.2" />
          <span>密码库</span>
        </div>
        <h1 class="m-0 text-[28px] font-semibold leading-tight tracking-tight text-slate-900">解压密码工作台</h1>
        <p class="mt-1.5 max-w-xl text-[13px] leading-relaxed text-slate-500">集中管理解压密码、作品绑定关系与自动清理规则。<span class="text-slate-600">同时填写文件名 + RJ 号时，系统会把该文件视为该 RJ，查重/命名/包裹目录都以此为准。</span></p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="inline-flex h-8 items-center gap-1.5 rounded-full border border-slate-200 bg-white/80 px-3 text-xs font-medium text-slate-600 shadow-sm">
          <IconShield :size="14" :stroke-width="2.2" class="text-slate-400" />总数 <b class="text-slate-800">{{ totalCount }}</b>
        </span>
        <span class="inline-flex h-8 items-center gap-1.5 rounded-full border border-emerald-200/70 bg-emerald-50/70 px-3 text-xs font-medium text-emerald-700">
          <IconSparkles :size="14" :stroke-width="2.2" />已生效 <b>{{ usedPasswordCount }}</b>
        </span>
        <span class="inline-flex h-8 items-center gap-1.5 rounded-full border border-violet-200/70 bg-violet-50/70 px-3 text-xs font-medium text-violet-700">
          <IconDoc :size="14" :stroke-width="2.2" />已绑定 <b>{{ scopedPasswordCount }}</b>
        </span>
      </div>
    </header>

    <!-- 工具栏 -->
    <section class="vault-toolbar-shell mb-4">
      <div class="vault-toolbar-panel vault-toolbar-panel-actions rounded-2xl border border-slate-200/80 bg-white/80 p-2.5 shadow-sm backdrop-blur">
        <div class="vault-toolbar-main-actions">
          <button type="button" class="vault-btn vault-btn-primary" @click="() => { resetForm(); showAddDialog = true }">
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
        <el-select v-model="passwordSortBy" size="small" class="vault-select !w-[128px]" @change="handlePasswordSortChange">
          <el-option label="创建时间" value="created_at" />
          <el-option label="更新时间" value="updated_at" />
          <el-option label="RJ 号" value="rjcode" />
          <el-option label="文件名" value="filename" />
          <el-option label="使用次数" value="use_count" />
        </el-select>
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
    <section class="rounded-2xl border border-slate-200/80 bg-white/90 p-4 shadow-[0_12px_40px_-12px_rgba(15,23,42,0.12)] backdrop-blur">
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
            <button type="button" class="vault-btn vault-btn-primary" @click="() => { resetForm(); showAddDialog = true }">
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
              <div class="inline-flex items-center justify-center gap-1.5">
                <button type="button" class="inline-flex size-12 items-center justify-center rounded-lg text-slate-500 transition-all duration-300 hover:-translate-y-0.5 hover:bg-blue-50 hover:text-blue-600 active:scale-95" @click="handleEdit(row)" title="编辑">
                  <AppLottieIcon :src="editIconAnimation" :size="52" tone="primary" />
                </button>
                <button type="button" class="group inline-flex size-11 items-center justify-center rounded-lg text-slate-500 transition-all duration-300 hover:-translate-y-0.5 hover:bg-rose-50 hover:text-rose-600 active:scale-95" @click="handleDelete(row)" title="删除">
                  <AppLottieIcon :src="deleteIconAnimation" :size="38" tone="danger" />
                </button>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <div class="mt-4 flex justify-end">
          <el-pagination background layout="total, sizes, prev, pager, next, jumper"
            :current-page="currentPage" :page-size="pageSize" :page-sizes="PAGE_SIZES" :total="totalCount"
            @current-change="handlePageChange" @size-change="handlePageSizeChange" />
        </div>
      </template>
    </section>

    <!-- 添加/编辑弹框 -->
    <el-dialog v-model="showAddDialog" :show-close="false" width="520px" align-center class="vault-dialog" @close="resetForm">
      <div class="vault-dialog-shell">
        <header class="vault-dialog-header">
          <div class="flex items-center gap-3">
            <div class="grid size-10 place-items-center rounded-xl bg-blue-50 text-blue-600">
              <IconKey :size="18" :stroke-width="2.2" />
            </div>
            <div>
              <div class="text-base font-semibold text-slate-900">{{ isEditing ? '编辑密码' : '添加密码' }}</div>
              <div class="text-xs text-slate-500">维护解压密码与作品绑定信息</div>
            </div>
          </div>
          <button type="button" class="vault-icon-btn" @click="showAddDialog = false"><IconClose :size="16" :stroke-width="2.2" /></button>
        </header>

        <div class="vault-dialog-body">
          <p class="vault-dialog-note mb-4 flex items-start gap-1.5 text-xs leading-relaxed text-slate-500"><IconShield :size="13" :stroke-width="2.2" class="mt-0.5 shrink-0 text-blue-500" />同时填写 <b>文件名</b> + <b>RJ 号</b> 时，系统会把匹配到的压缩包视为该 RJ 作品，查重、重命名和包裹目录都按这个绑定执行。</p>

          <el-form ref="formRef" :model="form" :rules="rules" label-width="72px" class="vault-form">
            <el-form-item label="RJ 号" prop="rjcode">
              <el-input v-model="form.rjcode" placeholder="例如 RJ123456（可选）" clearable />
            </el-form-item>
            <el-form-item label="文件名" prop="filename">
              <el-input v-model="form.filename" placeholder="例如 my_archive.rar（可选）" clearable />
              <div class="mt-1 text-[11px] text-slate-400">留空表示不按文件名匹配。</div>
            </el-form-item>
            <el-form-item label="密码" prop="password" required>
              <AnimatedPasswordInput v-model="form.password" placeholder="请输入解压密码" show-password />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="form.description" type="textarea" :rows="2" placeholder="备注或来源说明（可选）" />
            </el-form-item>
          </el-form>
        </div>

        <footer class="vault-dialog-footer">
          <button type="button" class="vault-btn vault-btn-ghost" @click="showAddDialog = false">取消</button>
          <button type="button" class="vault-btn vault-btn-primary" :disabled="submitting" @click="handleSubmit">
            <span v-if="submitting" class="size-3.5 animate-spin rounded-full border-2 border-white/50 border-t-white"></span>
            {{ isEditing ? '保存修改' : '添加密码' }}
          </button>
        </footer>
      </div>
    </el-dialog>

    <!-- 智能清理弹框 -->
    <el-dialog v-model="showCleanupDialog" :show-close="false" width="880px" align-center class="vault-dialog">
      <div class="vault-dialog-shell">
        <header class="vault-dialog-header">
          <div class="flex items-center gap-3">
            <div class="grid size-10 place-items-center rounded-xl bg-amber-50 text-amber-600">
              <IconSparkles :size="18" :stroke-width="2.2" />
            </div>
            <div>
              <div class="text-base font-semibold text-slate-900">智能清理</div>
              <div class="text-xs text-slate-500">查看规则、预览匹配、确认后再执行</div>
            </div>
          </div>
          <button type="button" class="vault-icon-btn" @click="showCleanupDialog = false"><IconClose :size="16" :stroke-width="2.2" /></button>
        </header>

        <div class="vault-dialog-body">
          <div class="vault-cleanup-summary mb-3">
            <div class="vault-cleanup-meta">
              <span class="vault-cleanup-label">下次清理</span>
              <span class="vault-cleanup-value text-blue-600">{{ formatNextCleanupTime(cleanupStatus?.next_cleanup_at) }}</span>
            </div>
            <div class="vault-cleanup-meta">
              <span class="vault-cleanup-label">已清理</span>
              <span class="vault-cleanup-value text-emerald-600">{{ cleanupStatus?.total_cleaned_count ?? 0 }}</span>
            </div>
            <div class="vault-cleanup-meta">
              <span class="vault-cleanup-label">规则</span>
              <span class="vault-cleanup-value text-amber-600">使用 ≤ {{ cleanupStatus?.max_use_count ?? '-' }}，保留 {{ cleanupStatus?.preserve_days ?? '-' }} 天</span>
            </div>
          </div>

          <div class="mb-3 flex flex-wrap gap-2">
            <button type="button" class="vault-btn vault-btn-primary" :disabled="cleanupLoading" @click="previewCleanup">
              <IconEye :size="15" :stroke-width="2.2" />预览清理
            </button>
            <button type="button" class="vault-btn vault-btn-ghost" :disabled="cleanupLoading" @click="loadCleanupHistory">
              <IconRefresh :size="15" :stroke-width="2.2" :class="{ 'animate-spin': cleanupLoading }" />刷新历史
            </button>
            <button type="button" class="vault-btn vault-btn-ghost ml-auto" onclick="window.location.href='/settings#cleanup'">
              <IconSettings :size="15" :stroke-width="2.2" />清理设置
            </button>
          </div>

          <div class="mb-2 flex items-center gap-2 text-[12px] font-medium uppercase tracking-wider text-slate-400">
            <span class="h-px flex-1 bg-slate-200"></span><span>清理历史</span><span class="h-px flex-1 bg-slate-200"></span>
          </div>
          <el-table :data="cleanupHistory" class="password-table" style="width:100%" max-height="300" row-key="id">
            <el-table-column prop="_formatted_created_at" label="时间" width="180" />
            <el-table-column prop="deleted_count" label="清理数" width="90" align="center" />
            <el-table-column prop="trigger_type" label="触发方式" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="row.trigger_type === 'manual' ? 'warning' : ''" effect="plain">{{ row.trigger_type === 'manual' ? '手动' : '自动' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="note" label="备注" show-overflow-tooltip />
          </el-table>
        </div>
      </div>
    </el-dialog>

    <!-- 批量导入弹框 -->
    <el-dialog v-model="showImportDialog" :show-close="false" width="560px" align-center class="vault-dialog">
      <div class="vault-dialog-shell">
        <header class="vault-dialog-header">
          <div class="flex items-center gap-3">
            <div class="grid size-11 place-items-center rounded-xl bg-violet-50 text-violet-600">
              <IconDoc :size="20" :stroke-width="2.3" />
            </div>
            <div>
              <div class="text-base font-semibold text-slate-900">批量导入密码</div>
              <div class="text-xs text-slate-500">按行粘贴通用密码，解压链路会自动尝试</div>
            </div>
          </div>
          <button type="button" class="vault-icon-btn" @click="showImportDialog = false"><IconClose :size="16" :stroke-width="2.2" /></button>
        </header>

        <div class="vault-dialog-body">
          <p class="vault-dialog-note vault-dialog-note-subtle mb-3 text-xs leading-relaxed text-slate-500"><IconShield :size="13" :stroke-width="2.2" class="shrink-0 text-violet-500" />每行一个密码；此处导入的都是通用密码（不绑定 RJ / 文件名），适合添加常见公共解压密码。</p>
          <el-input v-model="importText" type="textarea" :rows="10" placeholder="每行一个密码，例如：&#10;pass123&#10;kikoeru&#10;asmr.one" />
          <div class="mt-2 text-xs text-slate-500">已识别有效密码 <b class="text-slate-800">{{ importLineCount }}</b> 条</div>
        </div>

        <footer class="vault-dialog-footer">
          <button type="button" class="vault-btn vault-btn-ghost" @click="showImportDialog = false">取消</button>
          <button type="button" class="vault-btn vault-btn-primary" :disabled="importing || importLineCount === 0" @click="handleImport">
            <span v-if="importing" class="size-3.5 animate-spin rounded-full border-2 border-white/50 border-t-white"></span>
            导入 {{ importLineCount }} 个密码
          </button>
        </footer>
      </div>
    </el-dialog>
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
import AppLottieIcon from '../components/common/AppLottieIcon.vue'
import AppEmptyState from '../components/common/AppEmptyState.vue'
import AnimatedPasswordInput from '../components/common/AnimatedPasswordInput.vue'
import editIconAnimation from '../assets/anime/Clipboard.lottie'
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
.vault-btn:hover:not(:disabled) { transform: translateY(-2px) scale(1.02); }
.vault-btn:active:not(:disabled) { transform: scale(0.96); }
.vault-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.vault-btn-primary {
  background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
}
.vault-btn-primary:hover:not(:disabled) { box-shadow: 0 8px 20px rgba(37, 99, 235, 0.35); }

.vault-btn-ghost {
  background: rgba(248, 250, 252, 0.8);
  color: #334155;
  border-color: rgba(203, 213, 225, 0.7);
}
.vault-btn-ghost:hover:not(:disabled) {
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
.vault-btn-danger:hover:not(:disabled) {
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

.vault-toolbar-btn:hover:not(:disabled) .vault-btn-icon {
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

.vault-btn:hover:not(:disabled) .vault-btn-icon {
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

/* ============ 输入框 / 选择框 ============ */
:deep(.vault-select .el-select__wrapper),
:deep(.vault-form .el-input__wrapper),
:deep(.vault-form .el-textarea__inner) {
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.7);
  box-shadow: inset 0 0 0 1px rgba(203, 213, 225, 0.7);
  transition: all 0.3s ease;
}
:deep(.vault-select .el-select__wrapper:hover),
:deep(.vault-form .el-input__wrapper:hover),
:deep(.vault-form .el-textarea__inner:hover) {
  box-shadow: inset 0 0 0 1px #94a3b8;
  background: #ffffff;
}
:deep(.vault-select .el-select__wrapper.is-focused),
:deep(.vault-form .el-input__wrapper.is-focus),
:deep(.vault-form .el-textarea__inner:focus) {
  box-shadow: inset 0 0 0 2px rgba(59, 130, 246, 0.5) !important;
  background: #ffffff;
}

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

/* ============ 弹框 ============ */
:deep(.vault-dialog.el-dialog) {
  background: transparent;
  box-shadow: none;
  padding: 0;
  width: auto !important;
  overflow: visible;
}
:deep(.vault-dialog .el-dialog__header),
:deep(.vault-dialog .el-dialog__body) { padding: 0 !important; }
:deep(.vault-dialog .el-dialog__header) { display: none; }

.vault-dialog-shell {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 80px);
  overflow: hidden;
  border-radius: 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(249, 250, 252, 0.96) 100%);
  border: 1px solid rgba(226, 232, 240, 0.65);
  box-shadow: 0 24px 64px -24px rgba(15, 23, 42, 0.28);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
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
  overflow-y: auto;
  flex: 1;
}

.vault-dialog-note b {
  font-weight: 600;
  color: #334155;
}

.vault-dialog-note {
  display: flex;
  align-items: center;
  gap: 6px;
}

.vault-dialog-note-subtle b {
  color: #475569;
}

.vault-cleanup-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
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

@media (max-width: 720px) {
  .vault-cleanup-summary {
    grid-template-columns: 1fr;
  }
}

.vault-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid rgba(226, 232, 240, 0.7);
  background: rgba(248, 250, 252, 0.7);
}

.vault-form :deep(.el-form-item) { margin-bottom: 14px; }
.vault-form :deep(.el-form-item__label) { font-size: 12px; font-weight: 500; color: #475569; }

:deep(.vault-form .el-input__wrapper),
:deep(.vault-form .el-textarea__inner),
:deep(.vault-form .el-select__wrapper),
:deep(.vault-form .el-input__inner),
:deep(.vault-form input),
:deep(.vault-form textarea),
:deep(.vault-form .animated-password-input .el-input__wrapper),
:deep(.vault-form .animated-password-input input) {
  background-color: #ffffff !important;
}

:deep(.vault-form .el-input__inner:-webkit-autofill),
:deep(.vault-form .el-input__inner:-webkit-autofill:hover),
:deep(.vault-form .el-input__inner:-webkit-autofill:focus),
:deep(.vault-form input:-webkit-autofill),
:deep(.vault-form input:-webkit-autofill:hover),
:deep(.vault-form input:-webkit-autofill:focus),
:deep(.vault-form textarea:-webkit-autofill),
:deep(.vault-form textarea:-webkit-autofill:hover),
:deep(.vault-form textarea:-webkit-autofill:focus) {
  -webkit-text-fill-color: #0f172a !important;
  box-shadow: 0 0 0 1000px #ffffff inset !important;
  transition: background-color 9999s ease-out 0s;
}

/* ============ 响应式 ============ */
@media (max-width: 960px) {
  .password-vault { padding-left: 12px; padding-right: 12px; }
}
</style>
