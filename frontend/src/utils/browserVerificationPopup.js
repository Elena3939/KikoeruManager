import { browserVerificationApi } from '../api'

export function reserveVerificationPopup() {
  // 在用户点击时同步开窗，避免等待接口后被浏览器拦截。
  const popup = window.open('about:blank', '_blank', 'popup,width=960,height=760')
  if (!popup) throw new Error('浏览器拦截了下载弹窗，请允许本站弹出窗口后重试')
  popup.opener = null
  if (popup.document) {
    popup.document.title = '正在准备下载'
    popup.document.body.textContent = '正在准备下载，请稍候...'
  }
  return popup
}

export async function openVerificationPopup(taskId, popup = reserveVerificationPopup()) {
  let result
  try {
    if (popup.closed) throw new Error('下载弹窗已关闭，请重新打开')
    result = await browserVerificationApi.open(taskId)
    const url = new URL(result.verification_url)
    if (url.protocol !== 'https:' || !url.hostname.endsWith('.imoutoheaven.org') || url.username || url.password) {
      throw new Error('YAAS 返回了非预期下载地址')
    }
    if (popup.closed) throw new Error('下载弹窗已关闭，请重新打开')
    popup.location.replace(url.href)
  } catch (error) {
    popup.close()
    throw error
  }
  try {
    await browserVerificationApi.handoff(taskId)
  } catch {
    throw new Error('浏览器已打开，但系统等待任务清理失败，请手动清理该任务')
  }
  return result
}
