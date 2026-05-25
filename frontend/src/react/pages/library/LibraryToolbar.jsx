import { ArrowLeft, FilterX } from 'lucide-react'
import { AppDropdown } from '../../components/AppDropdown'
import { Button, Card, Field } from '../../components/Primitives'
import { LibrarySearchBox } from './LibrarySearchBox'

export function LibraryToolbar({
  libraries,
  libraryId,
  search,
  searchKind,
  currentPath,
  searchLibraryIds,
  onLibraryChange,
  onSearchChange,
  onSearchKindChange,
  onLocateSearchResult,
  onOpenSearchOverlay,
  onFilterDelete,
  onGoUp
}) {
  return (
    <Card className="library-toolbar">
      <Field label="库存库">
        <AppDropdown
          value={libraryId || 'default'}
          onChange={onLibraryChange}
          options={[
            { value: 'default', label: '默认库存' },
            ...libraries.map(item => ({ value: String(item.id), label: item.name || String(item.id) }))
          ]}
          width={220}
        />
      </Field>
      <Field label="搜索">
        <LibrarySearchBox
          value={search}
          kindFilter={searchKind}
          libraryIds={searchLibraryIds}
          onChange={onSearchChange}
          onKindFilterChange={onSearchKindChange}
          onLocate={onLocateSearchResult}
          onOpenOverlay={onOpenSearchOverlay}
        />
      </Field>
      <Button onClick={onFilterDelete} disabled={!currentPath}><FilterX size={15} />删除过滤文件</Button>
      <Button onClick={onGoUp} disabled={!currentPath}><ArrowLeft size={15} />上级</Button>
    </Card>
  )
}
