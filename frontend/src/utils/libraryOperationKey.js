export function buildLibraryPathKey (libraryId, path) {
  return `${String(libraryId || '')}::${String(path || '').replace(/\\/g, '/').replace(/\/+$/, '')}`
}
