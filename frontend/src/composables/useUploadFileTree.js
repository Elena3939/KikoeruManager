import { computed, ref } from 'vue'

// 补齐清单中隐含的父目录，根层文件保持平铺；节点保留原始传输项。
export function useUploadFileTree(files) {
  const collapsed = ref(new Set())
  const rows = computed(() => {
    const roots = new Map()
    for (const file of files.value) {
      const parts = file.relative_path.split('/').filter(Boolean)
      let siblings = roots, path = ''
      for (let i = 0; i < parts.length; i++) {
        path += (path ? '/' : '') + parts[i]
        let node = siblings.get(parts[i])
        if (!node) {
          node = { id: path, name: parts[i], depth: i, type: 'dir', children: new Map() }
          siblings.set(parts[i], node)
        }
        if (i === parts.length - 1) { node.file = file; node.type = file.is_directory ? 'dir' : 'file'; node.size_bytes = file.size }
        siblings = node.children
      }
    }
    const result = [], stack = [...roots.values()].reverse()
    while (stack.length) {
      const node = stack.pop()
      result.push(node)
      if (!collapsed.value.has(node.id)) {
        for (const child of [...node.children.values()].reverse()) stack.push(child)
      }
    }
    return result
  })
  const expandedIds = computed(() => new Set(rows.value.filter(row => row.type === 'dir' && !collapsed.value.has(row.id)).map(row => row.id)))
  function toggle(row) {
    const next = new Set(collapsed.value)
    next.has(row.id) ? next.delete(row.id) : next.add(row.id)
    collapsed.value = next
  }
  return { rows, expandedIds, toggle }
}
