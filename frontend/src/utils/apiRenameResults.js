import { normalizeLibraryIndexPath } from '../stores/libraryIndexState'

export function apiRenameDeletedPaths (results) {
  return (Array.isArray(results) ? results : [])
    .filter(item => {
      if (!item?.success || item.no_change) return false
      const source = normalizeLibraryIndexPath(item.path)
      const target = normalizeLibraryIndexPath(item.new_path || item.path_after)
      return source && target && source !== target
    })
    .map(item => String(item.path).trim())
}
