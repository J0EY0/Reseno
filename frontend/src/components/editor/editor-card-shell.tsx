import { ChevronDown, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

export function EditorCardShell({
  icon: Icon,
  title,
  titleMeta,
  toggleLabel,
  collapsed,
  onToggle,
  headerAction,
  children,
}: {
  icon: LucideIcon
  title: string
  titleMeta?: string
  toggleLabel: string
  collapsed: boolean
  onToggle: () => void
  headerAction?: ReactNode
  children: ReactNode
}) {
  return (
    <Card
      data-collapsed={collapsed ? 'true' : 'false'}
      className={cn(
        'gap-0 overflow-hidden rounded-xl border-border/75 py-0 shadow-xs transition-[border-color,box-shadow] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]',
        !collapsed && 'border-primary/20',
      )}
    >
      <Collapsible open={!collapsed} onOpenChange={onToggle}>
        <div className="flex min-h-[60px] items-center justify-between gap-3 px-4 py-3">
          <div className="grid min-w-0 flex-1 grid-cols-[2.25rem_minmax(0,1fr)] items-center gap-2.5">
            <div className="flex size-9 items-center justify-center rounded-xl bg-primary/8 text-primary">
              <Icon className="size-4" />
            </div>
            <h3 className="flex min-w-0 items-baseline gap-2 text-sm font-semibold leading-5 tracking-tight">
              <span className="min-w-0 truncate" title={title}>
                {title}
              </span>
              {titleMeta ? (
                <span className="shrink-0 whitespace-nowrap text-xs font-normal leading-4 text-muted-foreground">
                  {titleMeta}
                </span>
              ) : null}
            </h3>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {headerAction}
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label={toggleLabel}
              >
                <ChevronDown
                  className={cn('size-4 transition-transform', collapsed && '-rotate-90')}
                />
                <span className="sr-only">{toggleLabel}</span>
              </Button>
            </CollapsibleTrigger>
          </div>
        </div>
        <CollapsibleContent className="collapsible-content">
          <CardContent className="collapsible-content-inner grid gap-4 border-t border-border/70 p-4">
            {children}
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
