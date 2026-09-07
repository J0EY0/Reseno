import { Skeleton } from '@/components/ui/skeleton'
import { TooltipProvider } from '@/components/ui/tooltip'
import type { AppMessages } from '@/i18n'
import type { ReactNode, Ref } from 'react'

import { useAgentComposerLayout } from './use-agent-composer-layout'

export function CopilotPanelShell({
  children,
  t,
}: {
  children: ReactNode
  t: AppMessages
}) {
  return (
    <TooltipProvider>
      <section
        className="agent-panel-card flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-(--radius-card) border border-border/60 bg-card shadow-card print:hidden xl:self-start"
        data-slot="agent-panel-shell"
      >
        <div className="px-4 pb-2 pt-3">
          <h3 className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
            {t.aiTitle}
          </h3>
        </div>
        {children}
      </section>
    </TooltipProvider>
  )
}

function AgentSessionLoading({ t }: { t: AppMessages }) {
  return (
    <div
      aria-live="polite"
      className="mx-auto grid w-full max-w-[260px] justify-items-center gap-3 text-center"
      data-slot="agent-panel-loading"
      role="status"
    >
      <div aria-hidden="true" className="grid w-full gap-2">
        <Skeleton className="mx-auto h-3 w-4/5" />
        <Skeleton className="mx-auto h-3 w-3/5" />
        <Skeleton className="mx-auto h-3 w-2/3" />
      </div>
      <p className="text-xs leading-5 text-muted-foreground">
        {t.agentHistoryLoading}
      </p>
    </div>
  )
}

export function CopilotPanelBodyFrame({
  children,
  composer,
  composerRef,
  conversationLayoutRef,
}: {
  children: ReactNode
  composer: ReactNode
  composerRef?: Ref<HTMLElement>
  conversationLayoutRef?: Ref<HTMLDivElement>
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        className="agent-thread-layout relative flex min-h-0 flex-1 flex-col"
        ref={conversationLayoutRef}
      >
        {children}
        <div
          aria-hidden="true"
          className="agent-thread-composer-shield pointer-events-none absolute inset-y-0 left-3 right-3 z-[5]"
          data-slot="agent-thread-composer-shield"
        />
        <section
          className="pointer-events-none absolute inset-x-0 bottom-0 z-10 px-3 pb-3"
          data-slot="agent-composer"
          ref={composerRef}
        >
          <div className="pointer-events-auto relative">{composer}</div>
        </section>
      </div>
    </div>
  )
}

export function AgentPanelLoadingBody({ t }: { t: AppMessages }) {
  const { composerRef, conversationLayoutRef } = useAgentComposerLayout()

  return (
    <CopilotPanelBodyFrame
      composer={
        <Skeleton
          aria-hidden="true"
          className="h-[94px] w-full rounded-[26px]"
        />
      }
      composerRef={composerRef}
      conversationLayoutRef={conversationLayoutRef}
    >
      <div className="agent-thread-safe-area flex min-h-0 min-w-0 flex-1 items-center justify-center px-3">
        <AgentSessionLoading t={t} />
      </div>
    </CopilotPanelBodyFrame>
  )
}
