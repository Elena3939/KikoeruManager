import { useEffect, useMemo, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Eye, Plus, RefreshCcw, Save, Trash2 } from 'lucide-react'
import { notificationApi } from '../../api'
import { Button, Card, Field, SelectInput, TextArea, TextInput } from './Primitives'
import { showSystemAlert, showSystemConfirm } from '../stores/systemPromptStore'
import { normalizeListPayload } from '../utils/format'

const EMPTY_TEMPLATE = {
  name: '',
  event_type: 'completed',
  domain: 'import',
  subject_template: '',
  html_template: '',
  blocks: []
}

export function NotificationTemplateManager() {
  const [templates, setTemplates] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [draft, setDraft] = useState(EMPTY_TEMPLATE)
  const [blocksText, setBlocksText] = useState('[]')
  const [preview, setPreview] = useState(null)

  const selected = useMemo(() => templates.find(item => String(item.id) === String(selectedId)), [templates, selectedId])
  const editor = useEditor({
    extensions: [StarterKit],
    content: draft.html_template || '',
    immediatelyRender: false,
    onUpdate: ({ editor: nextEditor }) => {
      setDraft(value => ({ ...value, html_template: nextEditor.getHTML() }))
    }
  })

  useEffect(() => {
    loadTemplates()
  }, [])

  useEffect(() => {
    if (!selected) {
      setDraft(EMPTY_TEMPLATE)
      setBlocksText('[]')
      editor?.commands.setContent('')
      return
    }
    const next = { ...EMPTY_TEMPLATE, ...selected }
    setDraft(next)
    setBlocksText(JSON.stringify(next.blocks || [], null, 2))
    editor?.commands.setContent(next.html_template || '')
  }, [selected, editor])

  async function loadTemplates() {
    const data = await notificationApi.listTemplates()
    setTemplates(normalizeListPayload(data))
  }

  function updateDraft(patch) {
    setDraft(value => ({ ...value, ...patch }))
  }

  function parseBlocks() {
    try {
      const parsed = JSON.parse(blocksText || '[]')
      return Array.isArray(parsed) ? parsed : []
    } catch (error) {
      throw new Error('blocks JSON 格式不正确')
    }
  }

  async function save() {
    const payload = { ...draft, blocks: parseBlocks() }
    const result = selectedId ? await notificationApi.updateTemplate(selectedId, payload) : await notificationApi.createTemplate(payload)
    await showSystemAlert({ title: selectedId ? '模板已更新' : '模板已创建', tone: 'success' })
    await loadTemplates()
    setSelectedId(String(result.id || selectedId || ''))
  }

  async function remove() {
    if (!selectedId) return
    await showSystemConfirm({ title: '删除通知模板', currentValue: draft.name, tone: 'danger' })
    await notificationApi.deleteTemplate(selectedId)
    setSelectedId('')
    await loadTemplates()
  }

  async function previewTemplate() {
    const blocks = parseBlocks()
    const data = blocks.length
      ? await notificationApi.previewBlocks(blocks, draft.event_type, draft.domain, draft.subject_template)
      : await notificationApi.previewTemplate(selectedId || null, { template: draft })
    setPreview(data)
  }

  return (
    <Card className="km-template-manager">
      <header className="km-section-head">
        <div>
          <h2>通知模板</h2>
          <p>React 版模板编辑器，保留旧 HTML 模板和新 blocks 预览链路。</p>
        </div>
        <div className="km-row-actions">
          <Button onClick={loadTemplates}><RefreshCcw size={14} />刷新</Button>
          <Button onClick={() => { setSelectedId(''); setDraft(EMPTY_TEMPLATE); setBlocksText('[]'); editor?.commands.setContent('') }}><Plus size={14} />新建</Button>
          <Button variant="primary" onClick={save}><Save size={14} />保存</Button>
          <Button onClick={previewTemplate}><Eye size={14} />预览</Button>
          <Button variant="danger" disabled={!selectedId} onClick={remove}><Trash2 size={14} />删除</Button>
        </div>
      </header>

      <div className="km-form-grid">
        <Field label="选择模板">
          <SelectInput value={selectedId} onChange={event => setSelectedId(event.target.value)}>
            <option value="">新建模板</option>
            {templates.map(item => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}
          </SelectInput>
        </Field>
        <Field label="名称"><TextInput value={draft.name || ''} onChange={event => updateDraft({ name: event.target.value })} /></Field>
        <Field label="事件"><TextInput value={draft.event_type || ''} onChange={event => updateDraft({ event_type: event.target.value })} /></Field>
        <Field label="领域"><TextInput value={draft.domain || ''} onChange={event => updateDraft({ domain: event.target.value })} /></Field>
        <Field label="主题"><TextInput value={draft.subject_template || ''} onChange={event => updateDraft({ subject_template: event.target.value })} /></Field>
      </div>

      <div className="km-two-col">
        <Field label="HTML 模板">
          <div className="km-rich-editor"><EditorContent editor={editor} /></div>
        </Field>
        <Field label="Blocks JSON">
          <TextArea value={blocksText} onChange={event => setBlocksText(event.target.value)} className="km-blocks-editor" spellCheck={false} />
        </Field>
      </div>

      {preview ? <pre className="km-json">{JSON.stringify(preview, null, 2)}</pre> : null}
    </Card>
  )
}
