import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type RowSelectionState,
} from '@tanstack/react-table'

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

export function DataTable<TData, TValue>({
  columns,
  data,
  emptyMessage,
  tableClassName,
  getRowId,
  getRowClassName,
  enableRowSelection,
  rowSelection,
  onRowSelectionChange,
}: {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  emptyMessage: string
  tableClassName?: string
  getRowId?: (originalRow: TData, index: number) => string
  getRowClassName?: (originalRow: TData) => string | undefined
  enableRowSelection?: boolean
  rowSelection?: RowSelectionState
  onRowSelectionChange?: OnChangeFn<RowSelectionState>
}) {
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    getRowId,
    enableRowSelection,
    onRowSelectionChange,
    state: rowSelection === undefined ? undefined : { rowSelection },
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <div
      data-slot="data-table"
      className="w-full min-w-0 max-w-full overflow-hidden rounded-lg border bg-card"
    >
      <Table className={tableClassName}>
        <TableHeader className="bg-muted">
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id} scope="col">
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                data-state={row.getIsSelected() ? 'selected' : undefined}
                className={cn(
                  'focus-within:bg-muted/50',
                  getRowClassName?.(row.original),
                )}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="h-32 text-center text-sm text-muted-foreground"
              >
                {emptyMessage}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  )
}
