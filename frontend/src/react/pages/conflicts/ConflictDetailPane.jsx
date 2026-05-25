import {
  AlertTriangle,
  CheckSquare,
  Copy,
  FileEdit,
  FileSearch,
  FileWarning,
  GitMerge,
  Loader2,
  RotateCcw,
  Save,
  SkipForward
} from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, EmptyState } from '../../components/Primitives'
import {
  canPreviewFilenames,
  conflictCanUseAction,
  filenameEncodingOptions,
  formatConflictDate,
  formatConflictLabel,
  formatConflictSize,
  formatConflictTimestamp,
  formatPreviewName,
  getConflictId,
  getConflictSourcePath,
  getConflictStatusLabel,
  getConflictTypeDetail,
  getExistingConflictPath,
  getFilenamePreviewRows,
  getGarbledMeta,
  isExtractFailed,
  isFailureConflict,
  isConflictRetrying
} from './conflictUtils'

function FieldRow({ label, value, mono = false }) {
  return (
    <div className="conflicts-info-row">
      <span>{label}</span>
      <b className={mono ? 'is-mono' : ''}>{value || '-'}</b>
    </div>
  )
}

export function ConflictDetailPane({
  conflict,
  selected,
  statsBackfilling,
  batchRunning,
  localRetryingIds,
  actionState,
  filenameState,
  onFilenameEncodingChange,
  onFilenamePreview,
  onKeepNew,
  onRetry,
  onSkip,
  onMerge,
  onRenameVolumes,
  labelForAction
}) {
  if (!conflict) {
    return (
      <section className="conflicts-detail-pane is-empty">
        <EmptyState icon={FileWarning} title="请选择问题作品" description="左侧列表支持单选、多选和批量处理。" />
      </section>
    )
  }

  const id = getConflictId(conflict)
  const garbled = getGarbledMeta(conflict)
  const preview = filenameState?.preview
  const encoding = filenameState?.encoding || 'auto'
  const sourceStats = conflict.context?.source?.stats
  const existingStats = conflict.context?.existing?.stats
  const metadata = conflict.new_metadata || {}
  const actionLoading = action => Boolean(actionState[`${id}:${action}`])
  const busy = batchRunning || Object.keys(actionState).some(key => key.startsWith(`${id}:`)) || isConflictRetrying(conflict, localRetryingIds)

  return (
    <section className="conflicts-detail-pane">
      <header className="conflicts-detail-header">
        <div className="conflicts-detail-bg-glyph">
          {isFailureConflict(conflict) ? <FileWarning size={190} /> : <Copy size={190} />}
        </div>
        <div className="conflicts-detail-title-block">
          <div>
            <h2>{conflict.rjcode || '未识别项目'}</h2>
            {selected ? <span><CheckSquare size={12} />已选入批量</span> : null}
          </div>
          <p><i data-tone={isFailureConflict(conflict) ? 'danger' : 'info'} />{getConflictTypeDetail(conflict)}</p>
        </div>
        <div className="conflicts-detail-actions">
          {conflictCanUseAction(conflict, 'KEEP_NEW') ? (
            <Button variant="primary" disabled={busy} loading={actionLoading('KEEP_NEW')} onClick={() => onKeepNew(conflict)}>
              {actionLoading('KEEP_NEW') ? null : <Save size={16} />}
              {labelForAction('KEEP_NEW', conflict)}
            </Button>
          ) : null}
          {canPreviewFilenames(conflict) ? (
            <Button disabled={busy || actionLoading('PREVIEW_FILENAME')} loading={actionLoading('PREVIEW_FILENAME')} onClick={() => onFilenamePreview(conflict)}>
              {actionLoading('PREVIEW_FILENAME') ? null : <FileSearch size={16} />}
              预览文件名
            </Button>
          ) : null}
          {conflictCanUseAction(conflict, 'RENAME_VOLUMES') ? (
            <Button variant="warning" disabled={busy} loading={actionLoading('RENAME_VOLUMES')} onClick={() => onRenameVolumes(conflict)}>
              {actionLoading('RENAME_VOLUMES') ? null : <FileEdit size={16} />}
              手动重命名分卷
            </Button>
          ) : null}
          {conflictCanUseAction(conflict, 'RETRY') ? (
            <Button variant="success" disabled={busy} loading={actionLoading('RETRY')} onClick={() => onRetry(conflict)}>
              {isConflictRetrying(conflict, localRetryingIds) || actionLoading('RETRY') ? <Loader2 size={16} className="km-spin" /> : <RotateCcw size={16} />}
              {labelForAction('RETRY', conflict)}
            </Button>
          ) : null}
          {conflictCanUseAction(conflict, 'SKIP') ? (
            <Button disabled={busy} loading={actionLoading('SKIP')} onClick={() => onSkip(conflict)}>
              {actionLoading('SKIP') ? null : <SkipForward size={16} />}
              {labelForAction('SKIP', conflict)}
            </Button>
          ) : null}
          {conflictCanUseAction(conflict, 'MERGE') ? (
            <Button variant="warning" disabled={busy} loading={actionLoading('MERGE')} onClick={() => onMerge(conflict)}>
              {actionLoading('MERGE') ? null : <GitMerge size={16} />}
              合并
            </Button>
          ) : null}
        </div>
      </header>

      <div className="conflicts-detail-body">
        {isFailureConflict(conflict) ? (
          <div className="conflicts-detail-alert" data-tone={isExtractFailed(conflict) ? 'warning' : 'danger'}>
            <AlertTriangle size={20} />
            <div>
              <h3>{isExtractFailed(conflict) ? '解压阶段失败，非重复冲突' : '处理中途失败，非重复冲突'}</h3>
              <p>{metadata.error_message || (isExtractFailed(conflict) ? '请检查密码、分卷完整性或压缩包本身是否损坏。' : '请按失败原因修复后重试。')}</p>
            </div>
          </div>
        ) : null}

        {garbled ? (
          <section className="conflicts-garbled-card">
            <header>
              <AlertTriangle size={17} />
              <div>
                <h3>文件名乱码诊断</h3>
                <p>样本：{formatPreviewName(garbled.sample, encoding) || '-'}</p>
              </div>
            </header>
            <div className="conflicts-garbled-toolbar">
              <span>压缩包文件名编码</span>
              <AppDropdown value={encoding} onChange={value => onFilenameEncodingChange(conflict, value)} options={filenameEncodingOptions} width={220} />
              <Button size="sm" disabled={actionLoading('PREVIEW_FILENAME')} onClick={() => onFilenamePreview(conflict)}>
                {actionLoading('PREVIEW_FILENAME') ? <Loader2 size={14} className="km-spin" /> : <FileSearch size={14} />}
                刷新预览
              </Button>
            </div>
            <div className="conflicts-garbled-grid">
              <div><span>评分</span><b>{garbled.scoreBefore} → {garbled.scoreAfter}</b></div>
              <div><span>修复 / 编码尝试</span><b>{garbled.repairedCount} / {garbled.codecPairsTried}</b></div>
              <div><span>触发位置</span><b>{garbled.origin || '-'}</b></div>
              <div><span>命中数量</span><b>{garbled.garbledCount} / {garbled.totalNames || '-'}</b></div>
            </div>
            {garbled.topSamples?.length ? (
              <div className="conflicts-garbled-samples">
                {garbled.topSamples.slice(0, 8).map((entry, index) => (
                  <div key={`${entry.name}-${index}`}><span>{formatPreviewName(entry.name, encoding)}</span><b>{entry.score}</b></div>
                ))}
              </div>
            ) : null}
            {preview ? (
              <div className="conflicts-filename-preview-inline">
                <header>
                  <span>编码：{preview.encoding || 'auto'} / codepage={preview.codepage || 'auto'} / 密码来源={preview.password_source || '未指定'}</span>
                  <b>{preview.file_count || 0} 个文件</b>
                </header>
                <div>
                  {getFilenamePreviewRows(preview, encoding).slice(0, 18).map((row, index) => (
                    <p key={`${row.name}-${index}`} className={row.garbled ? 'is-garbled' : ''}>
                      <span>{row.displayName || row.name || '-'}</span>
                      {row.garbled ? <em>乱码</em> : null}
                      {row.score != null ? <b>{row.score}</b> : null}
                    </p>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        <div className="conflicts-info-grid">
          <section className="conflicts-info-card">
            <h3>新来源</h3>
            <FieldRow label="路径" value={getConflictSourcePath(conflict)} mono />
            <FieldRow label="大小" value={formatConflictSize(sourceStats?.size, statsBackfilling)} />
            <FieldRow label="创建时间" value={formatConflictTimestamp(sourceStats?.created_at, statsBackfilling)} />
          </section>
          <section className="conflicts-info-card">
            <h3>已存在</h3>
            <FieldRow label="路径" value={getExistingConflictPath(conflict)} mono />
            <FieldRow label="大小" value={formatConflictSize(existingStats?.size, statsBackfilling)} />
            <FieldRow label="创建时间" value={formatConflictTimestamp(existingStats?.created_at, statsBackfilling)} />
          </section>
          <section className="conflicts-info-card">
            <h3>处理元信息</h3>
            <FieldRow label="状态" value={getConflictStatusLabel(conflict, localRetryingIds)} />
            <FieldRow label="创建时间" value={formatConflictDate(conflict.created_at)} />
            <FieldRow label="失败原因" value={metadata.extract_failure_reason || metadata.error_message || conflict.error_message} />
          </section>
          <section className="conflicts-info-card">
            <h3>建议</h3>
            <p className="conflicts-help-text">
              KEEP_NEW 会走后台任务链并写历史；SKIP 会删除待处理来源；MERGE 会打开差异工作台逐文件决策；RETRY 可指定一个或多个密码。
            </p>
          </section>
        </div>
      </div>
    </section>
  )
}
