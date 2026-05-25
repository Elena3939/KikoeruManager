import { File, FileArchive, FileText, Film, Folder, Image, Music } from 'lucide-react'
import { classifyLibraryEntryKind, libraryEntryClass } from './libraryUtils'

const iconMap = {
  dir: Folder,
  'audio-lossless': Music,
  audio: Music,
  image: Image,
  video: Film,
  pdf: FileText,
  archive: FileArchive,
  text: FileText,
  file: File
}

export function LibraryFileIcon({ item, size = 18 }) {
  const Icon = iconMap[classifyLibraryEntryKind(item)] || File
  return (
    <span className="file-icon-shell">
      <Icon className={`file-icon ${libraryEntryClass(item)}`} size={size} strokeWidth={2.2} />
    </span>
  )
}
