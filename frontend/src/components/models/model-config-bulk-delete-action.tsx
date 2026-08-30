import { Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { cn } from '@/lib/utils'

export function ModelConfigBulkDeleteAction({
  label,
  selectedCount,
  disabled,
  isPending,
  onDelete,
}: {
  label: string
  selectedCount: number
  disabled: boolean
  isPending: boolean
  onDelete: () => void
}) {
  const canBulkDelete = selectedCount > 0

  return (
    <div
      data-slot="model-config-bulk-actions"
      data-state={canBulkDelete ? 'open' : 'closed'}
      aria-hidden={!canBulkDelete}
      inert={!canBulkDelete}
      className={cn(
        'grid min-w-0 transition-all duration-150 ease-out',
        !canBulkDelete && 'pointer-events-none',
      )}
      style={{
        gridTemplateColumns: canBulkDelete ? '1fr' : '0fr',
        marginRight: canBulkDelete ? 0 : '-0.5rem',
        opacity: canBulkDelete ? 1 : 0,
        transform: canBulkDelete
          ? 'translateX(0) scale(1)'
          : 'translateX(0.25rem) scale(0.98)',
        transformOrigin: 'right center',
      }}
    >
      <div className="min-w-0 overflow-hidden">
        <Button
          type="button"
          variant="destructive"
          size="default"
          tabIndex={canBulkDelete ? undefined : -1}
          disabled={disabled || !canBulkDelete}
          onClick={onDelete}
        >
          {isPending ? (
            <Spinner data-icon="inline-start" aria-label={label} />
          ) : (
            <Trash2 data-icon="inline-start" />
          )}
          {label}
        </Button>
      </div>
    </div>
  )
}
