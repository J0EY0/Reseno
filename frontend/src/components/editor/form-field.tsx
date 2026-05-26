import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export function FormField({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <label className={cn('grid min-w-0 gap-2', className)}>
      <span className="break-words text-[11px] font-medium uppercase leading-tight tracking-[0.2em] text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  )
}
