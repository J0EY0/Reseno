import { PanelLeft } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

import { SidebarContext, useSidebar } from './sidebar-context'
import { Button } from './button'

function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(true)
  const [openMobile, setOpenMobile] = React.useState(false)

  const toggleSidebar = React.useCallback(() => {
    if (window.matchMedia('(max-width: 767px)').matches) {
      setOpenMobile((current) => !current)
      return
    }

    setOpen((current) => !current)
  }, [])

  return (
    <SidebarContext.Provider
      value={{ open, setOpen, openMobile, setOpenMobile, toggleSidebar }}
    >
      <div className="group/sidebar-wrapper flex min-h-svh w-full overflow-x-clip bg-background">
        {children}
      </div>
    </SidebarContext.Provider>
  )
}

function Sidebar({ className, children }: React.ComponentProps<'aside'>) {
  const { open, openMobile, setOpenMobile } = useSidebar()

  return (
    <>
      <div
        className={cn(
          'fixed inset-0 z-40 bg-black/40 transition-opacity md:hidden',
          openMobile ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={() => setOpenMobile(false)}
        aria-hidden="true"
      />
      <aside
        data-open={open}
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex shrink-0 -translate-x-full flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] md:sticky md:top-0 md:z-0 md:h-svh md:translate-x-0',
          open ? 'md:w-72' : 'md:w-[4.5rem]',
          openMobile && 'translate-x-0',
          className,
        )}
      >
        {children}
      </aside>
    </>
  )
}

function SidebarInset({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'flex min-w-0 flex-1 flex-col overflow-x-clip bg-background',
        className,
      )}
      {...props}
    />
  )
}

function SidebarTrigger({ className }: React.ComponentProps<typeof Button>) {
  const { toggleSidebar } = useSidebar()

  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      className={className}
      onClick={toggleSidebar}
    >
      <PanelLeft className="size-4" />
      <span className="sr-only">Toggle Sidebar</span>
    </Button>
  )
}

function SidebarHeader({ className, ...props }: React.ComponentProps<'div'>) {
  const { open } = useSidebar()

  return (
    <div
      className={cn(
        'flex flex-col gap-4 p-4 transition-[padding]',
        !open && 'items-center px-3',
        className,
      )}
      {...props}
    />
  )
}

function SidebarContent({ className, ...props }: React.ComponentProps<'div'>) {
  const { open } = useSidebar()

  return (
    <div
      className={cn(
        'flex flex-1 flex-col gap-4 overflow-auto overscroll-contain p-4',
        !open && 'px-3',
        className,
      )}
      {...props}
    />
  )
}

function SidebarFooter({ className, ...props }: React.ComponentProps<'div'>) {
  const { open } = useSidebar()

  return (
    <div
      className={cn(
        'mt-auto flex flex-col gap-4 p-4',
        !open && 'items-center px-3',
        className,
      )}
      {...props}
    />
  )
}

function SidebarGroup({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-2', className)} {...props} />
}

function SidebarGroupLabel({ className, ...props }: React.ComponentProps<'div'>) {
  const { open } = useSidebar()

  return open ? (
    <div
      className={cn(
        'px-2 text-[11px] font-medium uppercase tracking-[0.2em] text-sidebar-foreground/60',
        className,
      )}
      {...props}
    />
  ) : null
}

function SidebarGroupContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1', className)} {...props} />
}

function SidebarMenu({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1', className)} {...props} />
}

function SidebarMenuItem({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('', className)} {...props} />
}

function SidebarMenuButton({
  className,
  isActive,
  ...props
}: React.ComponentProps<'button'> & {
  isActive?: boolean
}) {
  const { open } = useSidebar()

  return (
    <button
      className={cn(
        'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
        isActive && 'bg-sidebar-accent text-sidebar-accent-foreground',
        !open && 'justify-center px-0',
        className,
      )}
      {...props}
    />
  )
}

export {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
}
