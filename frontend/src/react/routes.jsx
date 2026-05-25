import {
  Archive,
  Boxes,
  Captions,
  Download,
  FolderTree,
  History,
  House,
  KeyRound,
  ListTodo,
  ScrollText,
  Settings2,
  Tags,
  TriangleAlert
} from 'lucide-react'
import { DashboardPage } from './pages/DashboardPage'
import { TasksPage } from './pages/TasksPage'
import { ConflictsPage } from './pages/ConflictsPage'
import { LibraryPage } from './pages/LibraryPage'
import { SubtitleImportPage } from './pages/SubtitleImportPage'
import { PasswordVaultPage } from './pages/PasswordVaultPage'
import { ExistingFoldersPage } from './pages/ExistingFoldersPage'
import { ASMRSyncPage } from './pages/ASMRSyncPage'
import { CircleCompletionPage } from './pages/CircleCompletionPage'
import { LibraryBackupPage } from './pages/LibraryBackupPage'
import { SettingsPage } from './pages/SettingsPage'
import { LogsPage } from './pages/LogsPage'
import { ActivityHistoryPage } from './pages/ActivityHistoryPage'
import { VerifyGatePage } from './pages/VerifyGatePage'
import { BlockedGatePage } from './pages/BlockedGatePage'

export const appRoutes = [
  { path: '/', title: '概览', icon: House, element: <DashboardPage />, cache: true },
  { path: '/tasks', title: '任务队列', icon: ListTodo, element: <TasksPage /> },
  { path: '/conflicts', title: '问题作品', icon: TriangleAlert, element: <ConflictsPage />, cache: true },
  { path: '/library', title: '库存管理', icon: Boxes, element: <LibraryPage />, cache: true },
  { path: '/subtitle-import', title: '字幕补配', icon: Captions, element: <SubtitleImportPage />, cache: true },
  { path: '/passwords', title: '密码库', icon: KeyRound, element: <PasswordVaultPage />, cache: true },
  { path: '/existing-folders', title: '已有文件夹', icon: FolderTree, element: <ExistingFoldersPage />, cache: true },
  { path: '/asmr-sync', title: 'ASMR 同步下载', icon: Download, element: <ASMRSyncPage />, cache: true },
  { path: '/circle-completion', title: '社团补全', icon: Tags, element: <CircleCompletionPage />, cache: true },
  { path: '/library-backup', title: '库存打包', icon: Archive, element: <LibraryBackupPage />, cache: true },
  { path: '/settings', title: '设置', icon: Settings2, element: <SettingsPage />, cache: true },
  { path: '/logs', title: '日志', icon: ScrollText, element: <LogsPage /> },
  { path: '/activity-history', title: '操作记录', icon: History, element: <ActivityHistoryPage /> }
]

export const gateRoutes = [
  { path: '/verify', element: <VerifyGatePage />, gatePage: true },
  { path: '/blocked', element: <BlockedGatePage />, gatePage: true }
]
