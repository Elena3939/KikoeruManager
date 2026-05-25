import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Bell, CheckCircle2, ChevronDown, Info, Loader2, X, XCircle } from 'lucide-react'
import { DotLottieReact } from '@lottiefiles/dotlottie-react'
import notificationLottie from '../../assets/anime/Notification.lottie'
import {
  closePanel,
  deleteItem,
  loadMore,
  markAllRead,
  openPanel,
  startSSE,
  stopSSE,
  useNotificationState
} from '../stores/notificationsStore'
import { formatDateTime } from '../utils/format'

const THREE_DAYS_MS = 3 * 24 * 60 * 60 * 1000

function severityIcon(severity) {
  const map = {
    success: CheckCircle2,
    danger: XCircle,
    warning: AlertTriangle,
    info: Info
  }
  return map[severity] || Info
}

function domainLabel(item) {
  return item.domain_label || item.task_domain || '任务'
}

export function NotificationBell({ className }) {
  const bellRef = useRef(null)
  const [panelStyle, setPanelStyle] = useState({})
  const state = useNotificationState()

  useEffect(() => {
    startSSE()
    return () => stopSSE()
  }, [])

  function togglePanel() {
    const rect = bellRef.current?.getBoundingClientRect()
    if (rect) {
      const width = 360
      let left = rect.left
      if (left + width > window.innerWidth - 8) left = window.innerWidth - width - 8
      if (left < 8) left = 8
      setPanelStyle({ top: rect.bottom + 8, left })
    }
    if (state.panelOpen) closePanel()
    else openPanel()
  }

  return (
    <div className={className} ref={bellRef}>
      <button
        type="button"
        className={`notif-bell-btn ${state.panelOpen ? 'notif-bell-btn--active' : ''} ${state.unreadCount > 0 ? 'notif-bell-btn--has-unread' : ''}`}
        onClick={togglePanel}
        title="通知"
      >
        <DotLottieReact className="notif-bell-player" src={notificationLottie} autoplay={state.unreadCount > 0} loop={state.unreadCount > 0} />
      </button>
      {state.panelOpen ? <NotificationPanel panelStyle={panelStyle} /> : null}
      {state.panelOpen ? <div className="notif-overlay" onClick={closePanel} /> : null}
    </div>
  )
}

export function NotificationPanel({ panelStyle }) {
  const navigate = useNavigate()
  const state = useNotificationState()
  const cutoff = Date.now() - THREE_DAYS_MS
  const displayedItems = state.items.filter(item => new Date(item.created_at).getTime() >= cutoff)
  const hasUnread = displayedItems.some(item => !item.is_read)
  const hasMore = state.items.length < state.total

  function onItemClick(item) {
    closePanel()
    if (item.route_path) {
      navigate({ pathname: item.route_path, search: item.route_query ? new URLSearchParams(item.route_query).toString() : '' })
    }
  }

  return (
    <section className="notif-panel notif-panel--visible" style={{ top: panelStyle.top || 72, left: panelStyle.left || 8 }} onClick={event => event.stopPropagation()}>
      <header className="notif-panel-header">
        <span className="notif-panel-title">通知</span>
        <div className="notif-panel-actions">
          {hasUnread ? <button className="notif-action-btn" onClick={markAllRead}>全部已读</button> : null}
          <button className="notif-close-btn" onClick={closePanel}><X size={16} /></button>
        </div>
      </header>

      {state.loading ? (
        <div className="notif-empty"><Loader2 size={24} className="notif-spin" /><span>加载中...</span></div>
      ) : state.items.length === 0 ? (
        <div className="notif-empty"><Bell size={32} strokeWidth={1.4} /><span>暂无通知</span></div>
      ) : displayedItems.length === 0 ? (
        <div className="notif-empty"><Bell size={32} strokeWidth={1.4} /><span>近3天内无通知</span></div>
      ) : (
        <div className="notif-list">
          {displayedItems.map((item, index) => {
            const Icon = severityIcon(item.severity)
            return (
              <article
                key={item.id}
                className={`notif-item notif-item--${item.severity || 'info'} ${item.is_read ? 'notif-item--read' : 'notif-item--unread'}`}
                style={item.is_read ? { transitionDelay: `${index * 45}ms` } : undefined}
                onClick={() => onItemClick(item)}
              >
                <div className="notif-item-icon"><Icon size={16} /></div>
                <div className="notif-item-body">
                  <div className="notif-item-title">{item.title}</div>
                  <div className="notif-item-summary">{item.summary}</div>
                  <div className="notif-item-meta">
                    <span className="notif-meta-tag notif-meta-domain">{domainLabel(item)}</span>
                    {item.rjcode ? <span className="notif-meta-tag notif-meta-rj">{item.rjcode}</span> : null}
                    <span className="notif-item-time">{formatDateTime(item.created_at)}</span>
                  </div>
                </div>
                <button className="notif-item-del" onClick={event => { event.stopPropagation(); deleteItem(item.id) }} title="删除">
                  <X size={12} />
                </button>
              </article>
            )
          })}
          {hasMore || state.loadingMore ? (
            <div className="notif-load-more">
              {state.loadingMore ? (
                <div className="notif-load-more-spin"><Loader2 size={14} className="notif-spin" /><span>加载中...</span></div>
              ) : (
                <button className="notif-load-more-btn" onClick={loadMore}><ChevronDown size={13} />查看更多</button>
              )}
            </div>
          ) : null}
        </div>
      )}
    </section>
  )
}
