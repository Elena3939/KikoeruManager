import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  Clock,
  Edit3,
  Eye,
  FileText,
  KeyRound,
  Plus,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  X
} from 'lucide-react'
import { cleanupApi, passwordApi } from '../../api'
import { AppDropdown } from '../components/AppDropdown'
import { Button, Card, Field, IconButton, LoadingState, Modal, PageHeader, TextArea, TextInput } from '../components/Primitives'
import { showSystemAlert, showSystemConfirm } from '../stores/systemPromptStore'
import { formatDateTime, normalizeListPayload } from '../utils/format'

const PAGE_SIZES = [10, 20, 50, 100, 200]

const sortOptions = [
  { value: 'created_at', label: '创建时间' },
  { value: 'updated_at', label: '更新时间' },
  { value: 'rjcode', label: 'RJ 号' },
  { value: 'filename', label: '文件名' },
  { value: 'use_count', label: '使用次数' }
]

const emptyForm = { id: null, rjcode: '', filename: '', password: '', description: '' }

function getSourceLabel(source) {
  if (source === 'manual') return '手动'
  if (source === 'batch') return '批量'
  return source || '自动'
}

function normalizePasswordRow(row) {
  return {
    ...row,
    use_count: Number(row.use_count || 0),
    _created: formatDateTime(row.created_at),
    _updated: formatDateTime(row.updated_at),
    _lastUsed: row.last_used_at ? formatDateTime(row.last_used_at) : '从未使用'
  }
}

function getRowTitle(row) {
  return row.rjcode || row.filename || row.description || row.password || row.id
}

function formatNextCleanupTime(value) {
  const raw = value || ''
  if (!raw) return '未设置'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return raw
  const diff = date.getTime() - Date.now()
  if (diff <= 0) return '即将执行'
  const minutes = Math.floor(diff / 60000)
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  const rest = minutes % 60
  if (days > 0) return `${days}天${hours}小时后`
  if (hours > 0) return `${hours}小时${rest}分钟后`
  return `${Math.max(rest, 1)}分钟后`
}

export function PasswordVaultPage() {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState('created_at')
  const [sortOrder, setSortOrder] = useState('desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [formOpen, setFormOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [cleanupOpen, setCleanupOpen] = useState(false)
  const [cleanupLoading, setCleanupLoading] = useState(false)
  const [cleanupStatus, setCleanupStatus] = useState(null)
  const [cleanupHistory, setCleanupHistory] = useState([])

  const selectedRows = useMemo(() => rows.filter(row => selectedIds.has(row.id)), [rows, selectedIds])
  const allPageSelected = rows.length > 0 && rows.every(row => selectedIds.has(row.id))
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const usedPasswordCount = rows.filter(row => Number(row.use_count || 0) > 0).length
  const scopedPasswordCount = rows.filter(row => row.rjcode || row.filename).length
  const importLineCount = importText.split(/\r?\n/).map(line => line.trim()).filter(Boolean).length
  const isEditing = Boolean(form.id)

  async function loadPasswords(next = {}) {
    const nextPage = next.page ?? page
    setLoading(true)
    try {
      const data = await passwordApi.list({
        search: search || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        page: nextPage,
        page_size: pageSize
      })
      const list = normalizeListPayload(data).map(normalizePasswordRow)
      setRows(list)
      setTotal(Number(data?.total ?? list.length))
      setPage(Number(data?.page ?? nextPage))
      setSelectedIds(prev => {
        const visible = new Set(list.map(row => row.id))
        return new Set([...prev].filter(id => visible.has(id)))
      })
    } finally {
      setLoading(false)
    }
  }

  async function loadCleanupStatus() {
    const status = await cleanupApi.password.status().catch(() => null)
    setCleanupStatus(status)
  }

  async function loadCleanupHistory() {
    setCleanupLoading(true)
    try {
      const data = await cleanupApi.password.history(50)
      setCleanupHistory(normalizeListPayload(data?.history || data).map(row => ({
        ...row,
        _created: formatDateTime(row.created_at)
      })))
    } finally {
      setCleanupLoading(false)
    }
  }

  useEffect(() => {
    loadPasswords()
    loadCleanupStatus()
  }, [])

  useEffect(() => {
    loadPasswords({ page: 1 })
  }, [sortBy, sortOrder, pageSize])

  function resetForm() {
    setForm(emptyForm)
  }

  function openCreateDialog() {
    resetForm()
    setFormOpen(true)
  }

  function openEditDialog(row) {
    setForm({
      id: row.id,
      rjcode: row.rjcode || '',
      filename: row.filename || '',
      password: row.password || '',
      description: row.description || ''
    })
    setFormOpen(true)
  }

  async function submitForm() {
    const password = form.password.trim()
    if (!password) {
      await showSystemAlert({ title: '密码不能为空', tone: 'warning' })
      return
    }

    setSubmitting(true)
    try {
      const payload = {
        rjcode: form.rjcode.trim() || null,
        filename: form.filename.trim() || null,
        password,
        description: form.description.trim() || null,
        source: 'manual'
      }
      const saved = form.id
        ? await passwordApi.update(form.id, payload)
        : await passwordApi.create(payload)
      setFormOpen(false)
      resetForm()
      await loadPasswords()
      if (saved?.merged) {
        await showSystemAlert({ title: '已合并到现有通用密码', tone: 'success' })
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function deleteOne(row) {
    await showSystemConfirm({
      title: '删除密码',
      message: '删除后解压重试、自动匹配和历史诊断将不再使用这条密码。',
      currentValue: getRowTitle(row),
      confirmText: '删除',
      tone: 'danger'
    })
    await passwordApi.delete(row.id)
    await loadPasswords()
  }

  async function deleteSelected() {
    if (!selectedRows.length) return
    await showSystemConfirm({
      title: '批量删除密码',
      message: `将删除 ${selectedRows.length} 条密码记录。`,
      currentValue: selectedRows.map(getRowTitle).join('\n'),
      confirmText: '批量删除',
      tone: 'danger',
      inputType: 'textarea',
      width: 520
    })
    setSubmitting(true)
    try {
      for (const row of selectedRows) {
        await passwordApi.delete(row.id)
      }
      setSelectedIds(new Set())
      await loadPasswords()
    } finally {
      setSubmitting(false)
    }
  }

  async function importPasswords() {
    const text = importText.trim()
    if (!text || !importLineCount) {
      await showSystemAlert({ title: '请输入要导入的密码', tone: 'warning' })
      return
    }
    setImporting(true)
    try {
      const data = await passwordApi.importFromText(text)
      setImportOpen(false)
      setImportText('')
      await loadPasswords({ page: 1 })
      await showSystemAlert({
        title: '批量导入完成',
        message: data?.message || `新建 ${data?.imported ?? 0} 个，跳过 ${data?.skipped ?? 0} 个`,
        tone: 'success'
      })
    } finally {
      setImporting(false)
    }
  }

  async function previewCleanup() {
    setCleanupLoading(true)
    try {
      const data = await cleanupApi.password.preview()
      const deletedCount = Number(data?.deleted_count || 0)
      if (!deletedCount) {
        await showSystemAlert({ title: '没有需要清理的密码', tone: 'success' })
        return
      }
      const passwordList = (data.deleted_passwords || [])
        .slice(0, 30)
        .map(item => `• ${item.rjcode || item.filename || '通用密码'}（${item.use_count || 0} 次，${getSourceLabel(item.source)}）`)
        .join('\n')
      await showSystemConfirm({
        title: '清理预览',
        message: `将清理 ${deletedCount} 个密码：\n\n${passwordList}${deletedCount > 30 ? '\n...' : ''}`,
        confirmText: '立即清理',
        tone: 'warning',
        width: 560,
        inputType: 'textarea'
      })
      await runCleanup()
    } finally {
      setCleanupLoading(false)
    }
  }

  async function runCleanup() {
    setCleanupLoading(true)
    try {
      const data = await cleanupApi.password.run()
      await showSystemAlert({
        title: Number(data?.deleted_count || 0) ? `成功清理 ${data.deleted_count} 个密码` : '没有需要清理的密码',
        tone: 'success'
      })
      await Promise.all([loadPasswords(), loadCleanupStatus(), loadCleanupHistory()])
    } finally {
      setCleanupLoading(false)
    }
  }

  function toggleSelected(row, checked) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (checked) next.add(row.id)
      else next.delete(row.id)
      return next
    })
  }

  function togglePageSelected(checked) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      for (const row of rows) {
        if (checked) next.add(row.id)
        else next.delete(row.id)
      }
      return next
    })
  }

  function handlePageChange(nextPage) {
    const safe = Math.min(Math.max(nextPage, 1), pageCount)
    loadPasswords({ page: safe })
  }

  function openCleanupDialog() {
    setCleanupOpen(true)
    loadCleanupStatus()
    loadCleanupHistory()
  }

  return (
    <div className="km-page password-vault-page">
      <PageHeader
        eyebrow="密码工作台"
        title="解压密码工作台"
        description="集中管理解压密码、作品绑定关系与自动清理规则。同时填写文件名 + RJ 号时，系统会把该文件视为该 RJ。"
        actions={
          <>
            <span className="vault-stat"><ShieldCheck size={14} />总数 <b>{total}</b></span>
            <span className="vault-stat is-success"><Sparkles size={14} />本页已生效 <b>{usedPasswordCount}</b></span>
            <span className="vault-stat is-purple"><FileText size={14} />本页已绑定 <b>{scopedPasswordCount}</b></span>
          </>
        }
      />

      <Card className="vault-toolbar-shell">
        <div className="vault-toolbar-actions">
          <Button variant="primary" onClick={openCreateDialog}><Plus size={16} />添加密码</Button>
          <Button onClick={() => setImportOpen(true)}><FileText size={16} />批量导入</Button>
          <Button onClick={openCleanupDialog}><Sparkles size={16} />智能清理</Button>
          <Button variant="danger" disabled={!selectedRows.length || submitting} loading={submitting} onClick={deleteSelected}>
            <Trash2 size={16} />批量删除 {selectedRows.length ? selectedRows.length : ''}
          </Button>
          <Button onClick={() => loadPasswords()}><RefreshCcw size={16} />刷新</Button>
        </div>
        <div className="vault-toolbar-filters">
          <span className="vault-toolbar-label">排序</span>
          <AppDropdown value={sortBy} onChange={setSortBy} options={sortOptions} width={132} />
          <Button onClick={() => setSortOrder(value => value === 'desc' ? 'asc' : 'desc')}>
            {sortOrder === 'desc' ? <ArrowDown size={15} /> : <ArrowUp size={15} />}
            {sortOrder === 'desc' ? '倒序' : '正序'}
          </Button>
          <div className="vault-search">
            <Search size={15} />
            <TextInput
              value={search}
              onChange={event => setSearch(event.target.value)}
              onKeyDown={event => { if (event.key === 'Enter') loadPasswords({ page: 1 }) }}
              placeholder="搜索 RJ 号、文件名、密码或备注"
            />
          </div>
          <Button variant="primary" onClick={() => loadPasswords({ page: 1 })}>搜索</Button>
        </div>
      </Card>

      <Card className="vault-table-card">
        {loading ? <LoadingState label="正在加载密码库..." /> : null}
        {!loading && !rows.length ? (
          <div className="vault-empty">
            <KeyRound size={38} />
            <strong>还没有录入任何密码</strong>
            <span>先录入常用解压密码，解压、匹配、清理链路才会真正串起来。</span>
            <div className="km-row-actions">
              <Button variant="primary" onClick={openCreateDialog}><Plus size={16} />添加第一个密码</Button>
              <Button onClick={() => setImportOpen(true)}><FileText size={16} />批量导入</Button>
            </div>
          </div>
        ) : null}
        {!loading && rows.length ? (
          <>
            <div className="vault-table-headline">
              <div>
                <h2>密码列表</h2>
                <p>支持批量选择、编辑、删除；双列键值不可同时为空。</p>
              </div>
              <span className="km-tag">本页 {rows.length} / 共 {total}</span>
            </div>
            <div className="vault-table-wrap">
              <table className="vault-table">
                <thead>
                  <tr>
                    <th className="vault-check-cell">
                      <input type="checkbox" checked={allPageSelected} onChange={event => togglePageSelected(event.target.checked)} />
                    </th>
                    <th>RJ 号</th>
                    <th>文件名</th>
                    <th>密码</th>
                    <th>来源</th>
                    <th>使用</th>
                    <th>最后使用</th>
                    <th>创建</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(row => (
                    <tr key={row.id} className={selectedIds.has(row.id) ? 'is-selected' : ''}>
                      <td className="vault-check-cell">
                        <input type="checkbox" checked={selectedIds.has(row.id)} onChange={event => toggleSelected(row, event.target.checked)} />
                      </td>
                      <td>{row.rjcode ? <span className="vault-rj">{row.rjcode}</span> : <span className="km-muted">-</span>}</td>
                      <td className="vault-cell-long">{row.filename || <span className="km-muted">-</span>}</td>
                      <td><code className="vault-password-pill">{row.password}</code></td>
                      <td><span className="vault-source">{getSourceLabel(row.source)}</span></td>
                      <td><b>{row.use_count}</b></td>
                      <td><span className="vault-date"><Clock size={12} />{row._lastUsed}</span></td>
                      <td>{row._created}</td>
                      <td>
                        <div className="km-row-actions">
                          <IconButton title="编辑" onClick={() => openEditDialog(row)}><Edit3 size={15} /></IconButton>
                          <IconButton title="删除" className="is-danger" onClick={() => deleteOne(row)}><Trash2 size={15} /></IconButton>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="vault-mobile-list">
              {rows.map(row => (
                <article className={`vault-mobile-card ${selectedIds.has(row.id) ? 'is-selected' : ''}`} key={`mobile-${row.id}`}>
                  <header>
                    <input type="checkbox" checked={selectedIds.has(row.id)} onChange={event => toggleSelected(row, event.target.checked)} />
                    <div>
                      {row.rjcode ? <span className="vault-rj">{row.rjcode}</span> : <b>未绑定 RJ</b>}
                      <span className="vault-source">{getSourceLabel(row.source)}</span>
                    </div>
                    <IconButton title="编辑" onClick={() => openEditDialog(row)}><Edit3 size={15} /></IconButton>
                    <IconButton title="删除" className="is-danger" onClick={() => deleteOne(row)}><Trash2 size={15} /></IconButton>
                  </header>
                  <dl>
                    <dt>文件名</dt><dd>{row.filename || '-'}</dd>
                    <dt>密码</dt><dd><code className="vault-password-pill">{row.password}</code></dd>
                    <dt>使用</dt><dd>{row.use_count} 次 · {row._lastUsed}</dd>
                  </dl>
                </article>
              ))}
            </div>
            <div className="vault-pagination">
              <Button size="sm" disabled={page <= 1} onClick={() => handlePageChange(page - 1)}>上一页</Button>
              <span>第 <b>{page}</b> / {pageCount} 页</span>
              <Button size="sm" disabled={page >= pageCount} onClick={() => handlePageChange(page + 1)}>下一页</Button>
              <AppDropdown
                value={String(pageSize)}
                onChange={value => setPageSize(Number(value))}
                options={PAGE_SIZES.map(size => ({ value: String(size), label: `${size} / 页` }))}
                width={112}
              />
            </div>
          </>
        ) : null}
      </Card>

      {formOpen ? (
        <Modal title={isEditing ? '编辑密码' : '添加密码'} width={560} onClose={() => setFormOpen(false)} footer={
          <>
            <Button onClick={() => setFormOpen(false)}>取消</Button>
            <Button variant="primary" loading={submitting} onClick={submitForm}>{isEditing ? '保存修改' : '添加密码'}</Button>
          </>
        }>
          <div className="vault-dialog-note"><ShieldCheck size={15} />同时填写文件名 + RJ 号时，该文件会按此 RJ 参与查重、命名和包裹目录。</div>
          <div className="km-form-grid">
            <Field label="RJ 号"><TextInput value={form.rjcode} onChange={event => setForm({ ...form, rjcode: event.target.value })} placeholder="例如 RJ123456" /></Field>
            <Field label="文件名"><TextInput value={form.filename} onChange={event => setForm({ ...form, filename: event.target.value })} placeholder="例如 archive.rar" /></Field>
            <Field label="密码"><TextInput value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} placeholder="请输入解压密码" /></Field>
            <Field label="备注"><TextArea value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} placeholder="备注或来源说明" /></Field>
          </div>
        </Modal>
      ) : null}

      {importOpen ? (
        <Modal title="批量导入密码" width={620} onClose={() => setImportOpen(false)} footer={
          <>
            <Button onClick={() => setImportOpen(false)}>取消</Button>
            <Button variant="primary" loading={importing} onClick={importPasswords}>导入 {importLineCount || ''}</Button>
          </>
        }>
          <div className="vault-dialog-note"><FileText size={15} />每行一个密码；已存在的密码会自动跳过。</div>
          <TextArea className="vault-import-textarea" value={importText} onChange={event => setImportText(event.target.value)} placeholder={'password-one\npassword-two'} />
          <span className="km-muted">有效行数：{importLineCount}</span>
        </Modal>
      ) : null}

      {cleanupOpen ? (
        <Modal title="智能清理" width={900} onClose={() => setCleanupOpen(false)} footer={<Button onClick={() => setCleanupOpen(false)}>关闭</Button>}>
          <div className="vault-cleanup-summary">
            <div><span>下次清理</span><b>{formatNextCleanupTime(cleanupStatus?.next_cleanup_time || cleanupStatus?.next_cleanup_at)}</b></div>
            <div><span>服务状态</span><b>{cleanupStatus?.enabled ? (cleanupStatus?.is_running ? '运行中' : '已启用') : '未启用'}</b></div>
            <div><span>规则</span><b>使用 ≤ {cleanupStatus?.max_use_count ?? '-'}，保留 {cleanupStatus?.preserve_days ?? '-'} 天</b></div>
          </div>
          <div className="km-row-actions">
            <Button variant="primary" loading={cleanupLoading} onClick={previewCleanup}><Eye size={15} />预览清理</Button>
            <Button loading={cleanupLoading} onClick={loadCleanupHistory}><RefreshCcw size={15} />刷新历史</Button>
          </div>
          <div className="vault-cleanup-history">
            {cleanupHistory.length ? cleanupHistory.map(item => (
              <article key={item.id || item.created_at || item._created}>
                <span>{item._created}</span>
                <b>清理 {item.deleted_count ?? item.count ?? 0} 条</b>
                <em>{item.trigger_type || item.trigger || '-'}</em>
              </article>
            )) : <div className="km-empty"><Sparkles size={28} /><strong>暂无清理历史</strong></div>}
          </div>
        </Modal>
      ) : null}
    </div>
  )
}
