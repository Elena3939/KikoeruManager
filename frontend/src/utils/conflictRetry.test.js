import { describe, expect, it, vi } from 'vitest'
import { buildConflictRetryPayload, isApiRenameConflict, passwordRetryTargets, requestRetryInput } from './conflictRetry'

const rename = { id: 'rename', conflict_type: 'PROCESS_FAILED', new_metadata: { source_operation: 'api_rename' } }
const archive = { id: 'archive', conflict_type: 'EXTRACT_FAILED' }
const importing = { id: 'import', conflict_type: 'PROCESS_FAILED', new_metadata: { failure_stage: 'metadata' } }

describe('问题作品按业务阶段重试', () => {
  it('已有 API 重命名失败直接重试，不调用密码弹窗，也不携带解压参数', async () => {
    const ask = vi.fn()
    expect(isApiRenameConflict(rename)).toBe(true)
    expect(await requestRetryInput(rename, ask)).toEqual({})
    expect(ask).not.toHaveBeenCalled()
    expect(buildConflictRetryPayload(rename, {
      password: '旧密码', passwords: ['旧密码'], filenameEncoding: 'gbk', ignoreGarbled: true,
    })).toEqual({})
  })

  it('混选只给压缩包显示密码输入，完整提交时不会漏掉 API 重命名', () => {
    const selected = [rename, archive, importing]
    expect(passwordRetryTargets(selected)).toEqual([archive, importing])
    expect(passwordRetryTargets([rename])).toEqual([])
    const inputs = { archive: { password: 'zip密码', filenameEncoding: 'shift_jis' } }
    expect(selected.map(conflict => ({ id: conflict.id, payload: buildConflictRetryPayload(conflict, inputs[conflict.id]) }))).toEqual([
      { id: 'rename', payload: {} },
      { id: 'archive', payload: { passwords: ['zip密码'], password: 'zip密码', filename_encoding: 'shift_jis' } },
      { id: 'import', payload: {} },
    ])
  })

  it('保留解压重试的多密码、编码、乱码确认与取消交互', async () => {
    const input = { passwords: ['first', '', 'second'], filenameEncoding: 'gbk', ignoreGarbled: true }
    const ask = vi.fn().mockResolvedValueOnce(input).mockResolvedValueOnce({ cancelled: true })
    expect(buildConflictRetryPayload(archive, await requestRetryInput(archive, ask))).toEqual({
      passwords: ['first', 'second'], password: 'first', filename_encoding: 'gbk', ignore_garbled: true,
    })
    expect(await requestRetryInput(archive, ask)).toEqual({ cancelled: true })
    expect(isApiRenameConflict(importing)).toBe(false)
    expect(buildConflictRetryPayload(archive, { filenameEncoding: 'auto' })).toEqual({})
  })
})
