export async function classifyCircleFolder (api, libraryId, path) {
  const data = await api.autoCircleGroup(libraryId, path)
  if (!data?.success) {
    throw new Error(data?.error || data?.message || '无法识别社团，未操作该目录')
  }
  return data
}
