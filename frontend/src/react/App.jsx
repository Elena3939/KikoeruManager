import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Menu, Moon, Package2, PanelLeftClose, PanelLeftOpen, Play, Radar, Square, Sun } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { conflictApi, watcherApi } from '../api'
import { appRoutes, gateRoutes } from './routes'
import { RequireGate } from './components/RequireGate'
import { NotificationBell } from './components/Notifications'
import { SystemPromptHost } from './components/SystemPrompt'
import { useInterval } from './hooks/useAsync'

const appVersion = '1.5.46'
const themeStorageKey = 'kikoerumanager.theme'
const sidebarPinStorageKey = 'kikoerumanager.sidebarPinned'

function readInitialTheme() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(themeStorageKey) === 'dark'
}

function readInitialSidebarPinned() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(sidebarPinStorageKey) === 'true'
}

export function App() {
  const location = useLocation()
  const isGateRoute = gateRoutes.some(route => route.path === location.pathname)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [sidebarPinned, setSidebarPinned] = useState(readInitialSidebarPinned)
  const [sidebarHover, setSidebarHover] = useState(false)
  const sidebarCloseTimer = useRef(null)
  const [isDarkTheme, setIsDarkTheme] = useState(readInitialTheme)
  const [watcherStatus, setWatcherStatus] = useState({ is_running: false, watch_path: '', pending_files: [] })
  const [conflictCount, setConflictCount] = useState(0)

  const navRoutes = useMemo(() => appRoutes, [])
  const sidebarExpanded = mobileNavOpen || sidebarPinned || sidebarHover

  useEffect(() => {
    document.documentElement.classList.toggle('kikoerumanager-dark', isDarkTheme)
    document.body.classList.toggle('kikoerumanager-dark', isDarkTheme)
    window.localStorage.setItem(themeStorageKey, isDarkTheme ? 'dark' : 'light')
  }, [isDarkTheme])

  useEffect(() => {
    window.localStorage.setItem(sidebarPinStorageKey, sidebarPinned ? 'true' : 'false')
  }, [sidebarPinned])

  useEffect(() => {
    return () => {
      if (sidebarCloseTimer.current) window.clearTimeout(sidebarCloseTimer.current)
    }
  }, [])

  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  useEffect(() => {
    document.body.classList.toggle('app-mobile-nav-locked', mobileNavOpen)
    return () => document.body.classList.remove('app-mobile-nav-locked')
  }, [mobileNavOpen])

  async function refreshSidebarState() {
    if (isGateRoute) return
    const [watcher, conflicts] = await Promise.allSettled([
      watcherApi.status(),
      conflictApi.count?.() || Promise.resolve({ count: 0 })
    ])
    if (watcher.status === 'fulfilled') setWatcherStatus(watcher.value || {})
    if (conflicts.status === 'fulfilled') setConflictCount(conflicts.value?.count || conflicts.value?.total || 0)
  }

  useEffect(() => {
    refreshSidebarState()
  }, [isGateRoute])

  useInterval(refreshSidebarState, 3000, !isGateRoute)

  async function toggleWatcher() {
    if (watcherStatus.is_running) await watcherApi.stop()
    else await watcherApi.start()
    await refreshSidebarState()
  }

  function openSidebarPreview() {
    if (sidebarCloseTimer.current) window.clearTimeout(sidebarCloseTimer.current)
    setSidebarHover(true)
  }

  function closeSidebarPreview() {
    if (sidebarCloseTimer.current) window.clearTimeout(sidebarCloseTimer.current)
    sidebarCloseTimer.current = window.setTimeout(() => setSidebarHover(false), 110)
  }

  return (
    <div className={`app-container react-app ${mobileNavOpen ? 'is-mobile-nav-open' : ''} ${sidebarExpanded ? 'is-sidebar-expanded' : 'is-sidebar-collapsed'} ${isGateRoute ? 'is-gate-route' : ''}`}>
      {!isGateRoute ? (
        <header className="app-mobile-topbar safe-area-top">
          <button type="button" className="app-mobile-trigger safe-touch-target" aria-label="打开导航菜单" onClick={() => setMobileNavOpen(true)}>
            <Menu size={22} strokeWidth={2.2} />
          </button>
          <Brand compact />
          <NotificationBell className="app-mobile-bell" />
        </header>
      ) : null}

      {mobileNavOpen && !isGateRoute ? <div className="app-drawer-mask" onClick={() => setMobileNavOpen(false)} /> : null}

      {!isGateRoute ? (
        <aside
          className={`sidebar ${mobileNavOpen ? 'is-mobile-open' : ''} ${sidebarExpanded ? 'is-expanded' : 'is-collapsed'}`}
          style={{ '--km-sidebar-width': sidebarExpanded ? '268px' : '82px' }}
          onPointerEnter={openSidebarPreview}
          onPointerLeave={closeSidebarPreview}
        >
          <div className="sidebar-shell">
            <div className="sidebar-head">
              <Brand collapsed={!sidebarExpanded} />
              <button
                type="button"
                className="sidebar-collapse-button"
                aria-label={sidebarPinned ? '收起侧边栏' : '固定展开侧边栏'}
                title={sidebarPinned ? '收起侧边栏' : '固定展开侧边栏'}
                onClick={() => setSidebarPinned(value => !value)}
              >
                {sidebarPinned ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
              </button>
            </div>
            <div className="sidebar-section-label">导航</div>
            <nav className="sidebar-menu react-sidebar-menu">
              {navRoutes.map(route => {
                const Icon = route.icon
                return (
                  <NavLink
                    key={route.path}
                    to={route.path}
                    title={route.title}
                    className={({ isActive }) => `react-menu-item ${isActive ? 'is-active' : ''} ${sidebarExpanded ? 'is-expanded' : 'is-icon-only'}`}
                  >
                    <Icon size={18} strokeWidth={2.2} />
                    <span className="react-menu-label">{route.title}</span>
                    {route.path === '/conflicts' && conflictCount > 0 ? <em className={sidebarExpanded ? '' : 'is-dot'}>{sidebarExpanded ? conflictCount : ''}</em> : null}
                  </NavLink>
                )
              })}
            </nav>

            <div className="sidebar-footer">
              <div className={`sidebar-status-card ${sidebarExpanded ? '' : 'is-compact'}`}>
                <div className="sidebar-status-header">
                  <span className={`sidebar-status-icon ${watcherStatus.is_running ? 'is-running' : ''}`}><Radar size={16} /></span>
                  <span className="sidebar-status-title">监视器</span>
                  <span className={`km-tag ${watcherStatus.is_running ? 'is-success' : ''}`}>{watcherStatus.is_running ? '运行中' : '已停止'}</span>
                </div>
                <div className="sidebar-status-text">{watcherStatus.is_running ? '正在监听新文件进入队列。' : '当前没有自动监听任务。'}</div>
                <button
                  type="button"
                  className="sidebar-watch-button"
                  title={watcherStatus.is_running ? '停止监视器' : '启动监视器'}
                  aria-label={watcherStatus.is_running ? '停止监视器' : '启动监视器'}
                  onClick={toggleWatcher}
                >
                  {watcherStatus.is_running ? <Square size={13} /> : <Play size={13} />}
                  <span>{watcherStatus.is_running ? '停止监视器' : '启动监视器'}</span>
                </button>
              </div>

              <div className="version-info">
                <span className="version-text">KikoeruManager</span>
                <button
                  type="button"
                  className={`theme-toggle-button ${isDarkTheme ? 'is-dark' : ''}`}
                  onClick={() => setIsDarkTheme(value => !value)}
                  title={isDarkTheme ? '当前深色模式，点击切换到浅色模式' : '当前浅色模式，点击切换到深色模式'}
                >
                  {isDarkTheme ? <Moon size={15} /> : <Sun size={15} />}
                  <span className="theme-toggle-text">{isDarkTheme ? '深色' : '浅色'}</span>
                </button>
              </div>
            </div>
          </div>
        </aside>
      ) : null}

      <main className="main-frame">
        <section className="main-content main-shell">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              className="content-shell"
              initial={{ opacity: 0, y: 10, filter: 'blur(6px)' }}
              animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, y: -8, filter: 'blur(4px)' }}
              transition={{ duration: 0.22, ease: [0.34, 1.56, 0.64, 1] }}
            >
              <Routes location={location}>
                {gateRoutes.map(route => <Route key={route.path} path={route.path} element={route.element} />)}
                {appRoutes.map(route => (
                  <Route key={route.path} path={route.path} element={<RequireGate>{route.element}</RequireGate>} />
                ))}
                <Route path="*" element={<RequireGate>{appRoutes[0].element}</RequireGate>} />
              </Routes>
            </motion.div>
          </AnimatePresence>
        </section>
      </main>

      <SystemPromptHost />
    </div>
  )
}

function Brand({ compact = false, collapsed = false }) {
  if (compact) {
    return (
      <div className="app-mobile-brand">
        <div className="app-mobile-brand-mark"><Package2 size={16} strokeWidth={2.2} /></div>
        <div className="app-mobile-brand-copy">
          <span className="app-mobile-brand-text">KikoeruManager</span>
          <span className="app-mobile-brand-version">v{appVersion}</span>
        </div>
      </div>
    )
  }

  return (
    <div className={`logo ${collapsed ? 'is-collapsed' : ''}`}>
      <div className="logo-mark"><Package2 size={22} strokeWidth={2.2} /></div>
      <div className="logo-copy">
        <span className="logo-text">KikoeruManager</span>
        <div className="logo-meta-row">
          <span className="logo-subtitle">v{appVersion}</span>
          <NotificationBell className="logo-bell" />
        </div>
      </div>
    </div>
  )
}
