import { describe, expect, it } from 'vitest'
import { createHash, randomBytes } from 'node:crypto'
import { sha256 } from './uploadSha256'
import { captureUploadSources, enumerateUploadEntries } from './browserUploadEntries'

describe('HTTP 环境摘要', () => {
  for (const length of [0, 3, 55, 56, 63, 64, 65, 1000, 8 * 1024 * 1024]) {
    it(`与标准实现一致：${length} 字节`, () => {
      const bytes = randomBytes(length)
      const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
      expect(sha256(buffer)).toBe(createHash('sha256').update(bytes).digest('hex'))
    })
  }
})

function directory(name, children) {
  return { name, isDirectory: true, createReader() {
    let cursor = 0
    return { readEntries(resolve) { const page = children.slice(cursor, cursor + 100); cursor += page.length; resolve(page) } }
  } }
}

describe('增量目录枚举', () => {
  it('读取全部分页，保留顶层和空目录，及时让出事件循环', async () => {
    const children = Array.from({ length: 10000 }, (_, i) => new File(['x'], `${i}.bin`, { lastModified: 123 }))
    children.push(directory('空目录', []))
    let ticks = 0
    const timer = setInterval(() => ticks++, 0)
    const entries = []
    for await (const entry of enumerateUploadEntries([directory('来源', children)])) entries.push(entry)
    clearInterval(timer)
    expect(entries).toHaveLength(10002)
    expect(entries[0]).toMatchObject({ relative_path: '来源', is_directory: true })
    expect(entries.at(-1)).toMatchObject({ relative_path: '来源/空目录', is_directory: true })
    expect(entries[10000].relative_path).toBe('来源/9999.bin')
    expect(ticks).toBeGreaterThan(0)
  })

  it('投放时同步提取文件系统 entry', () => {
    const source = directory('原始目录', [])
    expect(captureUploadSources({ items: [{ kind: 'file', webkitGetAsEntry: () => source }] })).toEqual([source])
  })
})
