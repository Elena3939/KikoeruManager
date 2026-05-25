import { flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { EmptyState, LoadingState } from './Primitives'

export function DataTable({ data = [], columns = [], loading, emptyTitle, rowKey, onRowClick }) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel()
  })

  if (loading) return <LoadingState />
  if (!data.length) return <EmptyState title={emptyTitle || '暂无数据'} />

  return (
    <div className="km-table-wrap">
      <table className="km-table">
        <thead>
          {table.getHeaderGroups().map(group => (
            <tr key={group.id}>
              {group.headers.map(header => (
                <th key={header.id}>
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map(row => (
            <tr
              key={rowKey ? rowKey(row.original) : row.id}
              className={onRowClick ? 'is-clickable' : ''}
              onClick={() => onRowClick?.(row.original)}
            >
              {row.getVisibleCells().map(cell => (
                <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
