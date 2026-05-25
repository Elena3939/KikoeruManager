import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, FileText, Loader2, Play, Upload } from 'lucide-react'
import { apiFetchOptions, apiUrl, libraryApi } from '../../../api'
import { Button } from '../../components/Primitives'
import { showSystemAlert } from '../../stores/systemPromptStore'
import { formatBytes } from '../../utils/format'

let uploadUid = 0

function getVolumeBaseName(filename) {
  const zipMatch = filename.match(/^(.+)\.z\d{2}$/i)
  if (zipMatch) return zipMatch[1]
  const rarLegacyMatch = filename.match(/^(.+)\.r\d{2}$/i)
  if (rarLegacyMatch) return rarLegacyMatch[1]
  const rarMatch = filename.match(/^(.+)\.part\d+\.(rar|7z|zip|exe)$/i)
  if (rarMatch) return rarMatch[1]
  const sevenZMatch = filename.match(/^(.+\.(7z|zip|rar))\.\d{3}$/i)
  if (sevenZMatch) return sevenZMatch[1]
  return null
}

function buildUploadGroups(files) {
  const groups = new Map()
  const singles = []
  const volumeBaseNames = new Set()

  files.forEach(file => {
    const baseName = getVolumeBaseName(file.name)
    if (baseName) volumeBaseNames.add(baseName.toLowerCase())
  })

  files.forEach(file => {
    if (file.name.toLowerCase().endsWith('.zip')) {
      const nameWithoutExt = file.name.slice(0, -4)
      if (volumeBaseNames.has(nameWithoutExt.toLowerCase())) volumeBaseNames.add(file.name.toLowerCase())
    }
  })

  files.forEach(file => {
    const nameLower = file.name.toLowerCase()
    let baseName = getVolumeBaseName(file.name)
    if (!baseName && nameLower.endsWith('.zip')) {
      const nameWithoutExt = file.name.slice(0, -4)
      if (volumeBaseNames.has(nameWithoutExt.toLowerCase())) baseName = nameWithoutExt
    }
    if (baseName) {
      const groupKey = baseName.toLowerCase()
      if (!groups.has(groupKey)) {
        groups.set(groupKey, {
          id: `group-${groupKey}`,
          displayName: baseName,
          isVolumeGroup: true,
          files: [],
          totalSize: 0
        })
      }
      const group = groups.get(groupKey)
      group.files.push(file)
      group.totalSize += Number(file.size || 0)
    } else {
      singles.push({
        id: file._uid,
        displayName: file.name,
        isVolumeGroup: false,
        files: [file],
        totalSize: Number(file.size || 0)
      })
    }
  })

  return [...groups.values(), ...singles].map(group => ({ ...group, fileCount: group.files.length }))
}

export function DashboardFileUploader({ onUploadSuccess }) {
  const fileInputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [libraries, setLibraries] = useState([])
  const [targetLibraryId, setTargetLibraryId] = useState('')

  useEffect(() => {
    let cancelled = false
    libraryApi.listLibraries()
      .then(data => {
        if (cancelled) return
        const list = data?.libraries || []
        setLibraries(list)
        setTargetLibraryId(data?.default_extract_library_id || data?.default_library_id || list[0]?.id || '')
      })
      .catch(error => console.error('读取库存库失败:', error))
    return () => {
      cancelled = true
    }
  }, [])

  const displayFiles = useMemo(() => buildUploadGroups(selectedFiles), [selectedFiles])

  function addFiles(files) {
    const incoming = Array.from(files || []).map(file => ({
      _file: file,
      name: file.name,
      size: file.size,
      lastModified: file.lastModified,
      _uid: `file-${Date.now()}-${uploadUid++}`
    }))
    if (!incoming.length) {
      showSystemAlert({ title: '没有可添加的文件', tone: 'warning' })
      return
    }
    const next = incoming.filter(file => !selectedFiles.some(item => item.name === file.name && item.size === file.size))
    if (!next.length) {
      showSystemAlert({ title: '文件已在待处理列表中', tone: 'info' })
      return
    }
    setSelectedFiles(value => [...value, ...next])
  }

  async function startUpload() {
    if (!selectedFiles.length || uploading) return
    setUploading(true)
    try {
      const formData = new FormData()
      for (const file of selectedFiles) formData.append('files', file._file)
      if (targetLibraryId) formData.append('target_library_id', targetLibraryId)
      const response = await fetch(apiUrl('/upload'), apiFetchOptions({ method: 'POST', body: formData }))
      if (!response.ok) throw new Error(`上传失败: ${response.statusText}`)
      const result = await response.json()
      setSelectedFiles([])
      await showSystemAlert({ title: result?.message || '上传任务已提交', tone: 'success' })
      onUploadSuccess?.()
    } catch (error) {
      await showSystemAlert({ title: '处理失败', message: error.message, tone: 'danger' })
    } finally {
      setUploading(false)
    }
  }

  return (
    <div
      className={`dashboard-uploader ${dragOver ? 'is-drag-over' : ''}`}
      onClick={() => fileInputRef.current?.click()}
      onDragOver={event => {
        event.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={event => {
        event.preventDefault()
        setDragOver(false)
      }}
      onDrop={event => {
        event.preventDefault()
        setDragOver(false)
        addFiles(event.dataTransfer.files)
      }}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        onChange={event => {
          addFiles(event.target.files)
          event.target.value = ''
        }}
      />
      <div className="dashboard-uploader-head">
        <span><Upload size={16} /></span>
        <div>
          <strong>拖拽或点击上传文件</strong>
          <small>支持多种压缩格式，自动识别分卷</small>
        </div>
      </div>

      {displayFiles.length ? (
        <div className="dashboard-uploader-body" onClick={event => event.stopPropagation()}>
          <label className="dashboard-uploader-select">
            <span>解压目标库</span>
            <select value={targetLibraryId} onChange={event => setTargetLibraryId(event.target.value)}>
              <option value="" disabled>选择目标库存</option>
              {libraries.map(library => <option key={library.id} value={library.id}>{library.name}</option>)}
            </select>
            <ChevronDown size={14} />
          </label>
          <div className="dashboard-upload-files">
            {displayFiles.map(group => (
              <div key={group.id}>
                <FileText size={13} />
                <span title={group.displayName}>
                  {group.displayName}
                  {group.isVolumeGroup ? <em>{group.fileCount} 个分卷</em> : null}
                </span>
                <b>{formatBytes(group.totalSize)}</b>
              </div>
            ))}
          </div>
          <Button variant="primary" loading={uploading} onClick={startUpload}>
            {uploading ? <Loader2 size={14} className="km-spin" /> : <Play size={14} />}
            开始处理 ({displayFiles.length} 个任务)
          </Button>
        </div>
      ) : null}
    </div>
  )
}
