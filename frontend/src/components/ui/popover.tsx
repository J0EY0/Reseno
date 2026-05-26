import * as React from 'react'
import * as PopoverPrimitive from '@radix-ui/react-popover'

import { cn } from '@/lib/utils'

function Popover({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Root>) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Trigger>) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverContent({
  className,
  align = 'center',
  sideOffset = 8,
  centered = false,
  backdrop = false,
  style,
  ...props
}: React.ComponentProps<typeof PopoverPrimitive.Content> & {
  centered?: boolean
  backdrop?: boolean
}) {
  const content = (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        data-slot="popover-content"
        align={align}
        sideOffset={sideOffset}
        avoidCollisions={!centered}
        style={
          centered
            ? {
                position: 'fixed',
                left: '50%',
                top: '50%',
                transform: 'translate(-50%, -50%)',
                width: 'min(560px, calc(100vw - 2rem))',
                ...style,
              }
            : style
        }
        className={cn(
          'z-50 w-72 rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-md outline-none',
          'data-[state=open]:animate-in data-[state=closed]:animate-out',
          'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
          'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
          'data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2',
          'data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2',
          centered &&
            'z-[60] rounded-3xl border-border/90 shadow-2xl',
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )

  if (!backdrop) {
    return content
  }

  return (
    <>
      <PopoverPrimitive.Portal>
        <div
          aria-hidden="true"
          className={cn(
            'fixed inset-0 z-50 bg-black/35 backdrop-blur-sm',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
          )}
        />
      </PopoverPrimitive.Portal>
      {content}
    </>
  )
}

export { Popover, PopoverContent, PopoverTrigger }
