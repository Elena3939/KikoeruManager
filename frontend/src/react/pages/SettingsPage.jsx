import { useEffect, useState } from 'react'
import { RefreshCcw, Save, Send, ShieldCheck } from 'lucide-react'
import { configApi, notificationApi, pathMappingApi, kikoeruApi, emailWatcherApi } from '../../api'
import { Button, Card, Field, PageHeader, TextArea, TextInput } from '../components/Primitives'
import { showSystemAlert } from '../stores/systemPromptStore'
import { NotificationTemplateManager } from '../components/NotificationTemplateManager'

export function SettingsPage() {
  const [configText, setConfigText] = useState('{}')
  const [pathTest, setPathTest] = useState('')
  const [state, setState] = useState(null)
  const [saving, setSaving] = useState(false)

  async function refresh() {
    const [config, configState] = await Promise.all([
      configApi.get(),
      configApi.state().catch(() => null)
    ])
    setConfigText(JSON.stringify(config, null, 2))
    setState(configState)
  }

  useEffect(() => {
    refresh()
  }, [])

  async function save() {
    setSaving(true)
    try {
      await configApi.save(JSON.parse(configText))
      await showSystemAlert({ title: '配置已保存', tone: 'success' })
      await refresh()
    } finally {
      setSaving(false)
    }
  }

  async function testPath() {
    const result = await pathMappingApi.test(pathTest)
    await showSystemAlert({ title: '路径映射测试', message: JSON.stringify(result, null, 2), tone: 'info' })
  }

  async function testKikoeru() {
    const result = await kikoeruApi.testConnection()
    await showSystemAlert({ title: 'Kikoeru 连接测试', message: JSON.stringify(result, null, 2), tone: 'info' })
  }

  async function testEmail() {
    const result = await notificationApi.testEmail()
    await showSystemAlert({ title: '测试邮件已触发', message: JSON.stringify(result, null, 2), tone: 'success' })
  }

  async function pollEmail() {
    const result = await emailWatcherApi.pollNow()
    await showSystemAlert({ title: '邮件监视轮询已触发', message: JSON.stringify(result, null, 2), tone: 'success' })
  }

  return (
    <div className="km-page settings-page react-settings-page">
      <PageHeader
        eyebrow="系统设置"
        title="设置"
        description="React 版保留完整配置读写，敏感字段脱敏逻辑仍由后端负责。"
        actions={<><Button onClick={refresh}><RefreshCcw size={16} />刷新</Button><Button variant="primary" loading={saving} onClick={save}><Save size={16} />保存</Button></>}
      />
      <div className="km-two-col wide-left">
        <Card>
          <h2>配置 JSON</h2>
          <TextArea className="km-config-editor" value={configText} onChange={event => setConfigText(event.target.value)} spellCheck={false} />
        </Card>
        <aside className="km-settings-rail">
          <Card>
            <h2>运行态</h2>
            <pre className="km-json">{JSON.stringify(state || {}, null, 2)}</pre>
          </Card>
          <Card>
            <h2>联通测试</h2>
            <Field label="路径映射"><TextInput value={pathTest} onChange={event => setPathTest(event.target.value)} placeholder="输入本地/远程路径" /></Field>
            <div className="km-action-grid">
              <Button onClick={testPath}><ShieldCheck size={15} />路径测试</Button>
              <Button onClick={testKikoeru}>Kikoeru</Button>
              <Button onClick={testEmail}><Send size={15} />测试邮件</Button>
              <Button onClick={pollEmail}>轮询邮件</Button>
            </div>
          </Card>
        </aside>
      </div>
      <NotificationTemplateManager />
    </div>
  )
}
