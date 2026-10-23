// 必须在 drop 同步阶段取出 entry；不能等网络请求结束后再读 DataTransfer。
export function captureUploadSources(transfer) {
  const items = Array.from(transfer.items || []).filter(item => item.kind === 'file')
  if (items.length) return items.map(item => item.webkitGetAsEntry?.() || item.getAsFile()).filter(Boolean)
  return Array.from(transfer.files || [])
}

const fileOf = entry => new Promise((resolve, reject) => entry.file(resolve, reject))
const readPage = reader => new Promise((resolve, reject) => reader.readEntries(resolve, reject))
export const yieldUploadThread = () => new Promise(resolve => setTimeout(resolve, 0))

export async function* enumerateUploadEntries(sources, check = async () => {}) {
  const stack = sources.map(entry => ({ entry, prefix: '' })).reverse()
  let lastYield = performance.now()
  let processed = 0
  while (stack.length) {
    await check()
    if (++processed % 128 === 0 || performance.now() - lastYield > 8) {
      await yieldUploadThread()
      lastYield = performance.now()
    }
    const { entry, prefix, reader } = stack.pop()
    if (reader) {
      const page = await readPage(reader)
      if (page.length) {
        stack.push({ reader, prefix })
        for (let i = page.length - 1; i >= 0; i--) stack.push({ entry: page[i], prefix })
      }
      continue
    }
    const relativePath = prefix + (entry.webkitRelativePath || entry.name)
    if (entry.isDirectory) {
      yield { relative_path: relativePath, size: 0, last_modified: 0, is_directory: true }
      stack.push({ reader: entry.createReader(), prefix: relativePath + '/' })
    } else {
      const file = entry.isFile ? await fileOf(entry) : entry
      yield { relative_path: relativePath, size: file.size, last_modified: file.lastModified, is_directory: false, file }
    }
  }
}
