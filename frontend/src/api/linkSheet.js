import { apiUrl } from './index'
import axios from 'axios'

// 大清单发布会在后端同一事务内批量切换数万条 RJ 指针；上传解析本身已后台化，
// 这里把发布确认的等待窗口拉长，避免客户端误判超时后重复提交确认。
const client = axios.create({ baseURL: apiUrl('/link-sheet'), withCredentials: true, timeout: 600000 })
export const linkSheetApi = {
  async upload(file) {
    const body = new FormData()
    body.append('file', file)
    return (await client.post('/imports', body)).data
  },
  async history(page = 1) { return (await client.get('/imports', { params: { page } })).data },
  async status(id) { return (await client.get(`/imports/${id}`)).data },
  async confirm(id) { return (await client.post(`/imports/${id}/confirm`)).data },
  async cancel(id) { return (await client.post(`/imports/${id}/cancel`)).data },
  async works(params) { return (await client.get('/works', { params })).data },
  async detail(id) { return (await client.get(`/revisions/${id}`)).data },
  async download(id, groupId = '') { return (await client.post(`/revisions/${id}/download`, { params: { group_id: groupId } })).data },
  async enabled(code, enabled) { return (await client.patch(`/works/${code}`, { enabled })).data },
}
