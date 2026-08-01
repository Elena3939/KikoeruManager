import { createReadStream, createWriteStream, promises as fs } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, extname, join } from 'node:path'
import { createBrotliCompress, createGzip, constants } from 'node:zlib'
import { pipeline } from 'node:stream/promises'

const distDir = fileURLToPath(new URL('../dist', import.meta.url))
const minSizeBytes = 1024
const compressibleExtensions = new Set([
  '.css',
  '.html',
  '.js',
  '.json',
  '.map',
  '.svg',
  '.txt',
  '.wasm',
  '.xml',
])

async function* walk(dir) {
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name)
    if (entry.isDirectory()) {
      yield* walk(fullPath)
    } else if (entry.isFile()) {
      yield fullPath
    }
  }
}

async function exists(path) {
  try {
    await fs.access(path)
    return true
  } catch {
    return false
  }
}

async function compressFile(sourcePath, targetPath, streamFactory) {
  await fs.mkdir(dirname(targetPath), { recursive: true })
  await pipeline(createReadStream(sourcePath), streamFactory(), createWriteStream(targetPath))
}

let created = 0
let skipped = 0

for await (const filePath of walk(distDir)) {
  if (filePath.endsWith('.br') || filePath.endsWith('.gz')) {
    skipped += 1
    continue
  }

  const ext = extname(filePath).toLowerCase()
  const stat = await fs.stat(filePath)
  if (!compressibleExtensions.has(ext) || stat.size < minSizeBytes) {
    skipped += 1
    continue
  }

  const brotliPath = `${filePath}.br`
  const gzipPath = `${filePath}.gz`

  if (!(await exists(brotliPath))) {
    await compressFile(filePath, brotliPath, () =>
      createBrotliCompress({
        params: {
          [constants.BROTLI_PARAM_QUALITY]: 11,
        },
      })
    )
    created += 1
  }

  if (!(await exists(gzipPath))) {
    await compressFile(filePath, gzipPath, () => createGzip({ level: 9 }))
    created += 1
  }
}

console.log(`precompress-assets: created ${created}, skipped ${skipped}`)
