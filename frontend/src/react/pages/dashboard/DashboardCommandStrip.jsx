import {
  AlertTriangle,
  ListChecks,
  ListTodo,
  PauseCircle,
  Play,
  PlayCircle,
  Search,
  SearchCheck,
  ShieldAlert,
  StopCircle
} from 'lucide-react'
import { Button } from '../../components/Primitives'

export function DashboardCommandStrip({ scanning, watcherRunning, onScan, onToggleWatcher, onGo }) {
  return (
    <section className="dashboard-command-strip" data-section="dashboard-command">
      <Button variant="primary" loading={scanning} disabled={scanning} onClick={onScan}>
        {scanning ? <Search size={15} className="km-spin" /> : <SearchCheck size={15} />}
        {scanning ? '扫描中' : '扫描处理'}
      </Button>
      <Button onClick={onToggleWatcher}>
        {watcherRunning ? <StopCircle size={15} /> : <PlayCircle size={15} />}
        {watcherRunning ? '停止监视' : '启动监视'}
      </Button>
      <span className="dashboard-command-divider" />
      <Button onClick={() => onGo('/conflicts')}>
        <ShieldAlert size={15} />
        问题作品
      </Button>
      <Button onClick={() => onGo('/tasks')}>
        <ListTodo size={15} />
        任务中心
      </Button>
      <span className="dashboard-command-spacer" />
      <span className="dashboard-command-hint">
        {watcherRunning ? <PauseCircle size={13} /> : <Play size={13} />}
        <span>{watcherRunning ? '自动监听输入目录' : '监视器未运行'}</span>
      </span>
      <span className="dashboard-command-hint is-warning">
        <AlertTriangle size={13} />
        <span>失败与重复会汇入问题作品</span>
      </span>
      <span className="dashboard-command-hint">
        <ListChecks size={13} />
        <span>任务中心保留完整动作</span>
      </span>
    </section>
  )
}
