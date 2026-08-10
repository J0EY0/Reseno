import { PromptInputProvider } from '@/components/ai-elements/prompt-input-context'
import { TooltipProvider } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { useMemo } from 'react'

import { CopilotComposer } from './copilot-composer'
import { CopilotConversationView } from './copilot-conversation-view'
import type { CopilotPanelProps } from './copilot-panel-types'
import { useAgentComposerLayout } from './use-agent-composer-layout'
import { useAgentConversation } from './use-agent-conversation'
import { useAgentMessageActions } from './use-agent-message-actions'
import { useAgentPromptActions } from './use-agent-prompt-actions'

/**
 * Stable inline-dock entrypoint. Conversation, history actions, attachments,
 * and rendering each live behind their own behavioral seam.
 */
export function CopilotPanel({
  isPanelCollapsed,
  resumeId,
  t,
  locale,
  resume,
  jobBrief,
  onJobBriefChange,
  keywordMatch,
  modelConfigs,
  selectedModelId,
  onSelectedModelChange,
  hasAgentDraft,
  agentDraftState,
  onPreviewAgentEdits,
  onReconcileAgentDraft,
  onRollbackAgentDraft,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  onOpenModelSettings,
  onBeforeSend,
}: CopilotPanelProps) {
  const selectedModel = useMemo(
    () =>
      modelConfigs.find((config) => config.id === selectedModelId) ??
      modelConfigs[0] ??
      null,
    [modelConfigs, selectedModelId],
  )
  const conversation = useAgentConversation({
    agentDraftState,
    jobBrief,
    keywordMatch,
    locale,
    onBeforeSend,
    onJobBriefChange,
    onPreviewAgentEdits,
    onReconcileAgentDraft,
    onRollbackAgentDraft,
    resume,
    resumeId,
    selectedModel,
    t,
  })
  const promptActions = useAgentPromptActions({
    hasConfiguredModel: Boolean(selectedModel),
    isResponding: conversation.isResponding,
    isSessionReady: conversation.isSessionReady,
    resumeId,
    sessionResetVersion: conversation.sessionResetVersion,
    sendPrompt: conversation.sendPrompt,
    stopConversation: conversation.stopResponding,
    t,
  })
  const messageActions = useAgentMessageActions({
    isResponding: conversation.isResponding,
    messages: conversation.messages,
    resumeId,
    sessionResetVersion: conversation.sessionResetVersion,
    sendPrompt: conversation.sendPrompt,
    t,
  })
  const { composerRef, conversationContextRef, conversationLayoutRef } =
    useAgentComposerLayout()
  const shouldDockAgent = !isPanelCollapsed
  const globalDropActive = shouldDockAgent

  const panelSurface = (
    <TooltipProvider>
      <section
        className={cn(
          'agent-panel-card flex min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-sm print:hidden',
          'h-full xl:self-start',
        )}
      >
        <div className="px-4 pb-2 pt-3">
          <h3 className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
            {t.aiTitle}
          </h3>
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <div
            className="agent-thread-layout relative flex min-h-0 flex-1 flex-col"
            ref={conversationLayoutRef}
          >
            <CopilotConversationView
              conversation={conversation}
              conversationContextRef={conversationContextRef}
              draft={{
                hasAgentDraft,
                onApply: onApplyAgentDraft,
                onDiscard: onDiscardAgentDraft,
                state: agentDraftState,
              }}
              hasConfiguredModel={Boolean(selectedModel)}
              messageActions={messageActions}
              onOpenModelSettings={onOpenModelSettings}
              promptActions={promptActions}
              t={t}
            />
            <section
              className="pointer-events-none absolute inset-x-0 bottom-0 z-10 px-3 pb-3"
              ref={composerRef}
            >
              <div className="pointer-events-auto relative">
                <CopilotComposer
                  globalDropActive={globalDropActive}
                  isResponding={conversation.isResponding}
                  isSessionReady={conversation.isSessionReady}
                  modelConfigs={modelConfigs}
                  onOpenModelSettings={onOpenModelSettings}
                  onSelectedModelChange={onSelectedModelChange}
                  promptActions={promptActions}
                  selectedModel={selectedModel}
                  selectedModelId={selectedModelId}
                  t={t}
                />
              </div>
            </section>
          </div>
        </div>
      </section>
    </TooltipProvider>
  )

  return (
    <PromptInputProvider>
      <aside
        aria-hidden={!shouldDockAgent}
        className={cn(
          'agent-panel-dock relative min-w-0 self-start overflow-hidden print:hidden',
          'transition-opacity duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]',
          !shouldDockAgent && 'pointer-events-none opacity-0',
        )}
        inert={!shouldDockAgent}
      >
        {panelSurface}
      </aside>
    </PromptInputProvider>
  )
}
