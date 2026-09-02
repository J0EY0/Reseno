import { PromptInputProvider } from '@/components/ai-elements/prompt-input-context'
import { useLayoutEffect, useMemo } from 'react'

import { CopilotComposer } from './copilot-composer'
import { CopilotConversationView } from './copilot-conversation-view'
import { CopilotPanelBodyFrame } from './copilot-panel-shell'
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
  documentLocale,
  resume,
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
  onStatusChange,
  onBeforeSend,
}: CopilotPanelProps) {
  const agentModelConfigs = useMemo(
    () => modelConfigs.filter((config) => config.supportsTools),
    [modelConfigs],
  )
  const selectedModel = useMemo(
    () =>
      agentModelConfigs.find((config) => config.id === selectedModelId) ??
      null,
    [agentModelConfigs, selectedModelId],
  )
  const conversation = useAgentConversation({
    agentDraftState,
    documentLocale,
    onApplyAgentDraft,
    onBeforeSend,
    onDiscardAgentDraft,
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
  const globalDropActive = !isPanelCollapsed

  useLayoutEffect(() => {
    onStatusChange(conversation.status)
  }, [conversation.status, onStatusChange])

  return (
    <PromptInputProvider>
      <CopilotPanelBodyFrame
        composer={
          <CopilotComposer
            globalDropActive={globalDropActive}
            isResponding={conversation.isResponding}
            isSessionReady={conversation.isSessionReady}
            modelConfigs={agentModelConfigs}
            onOpenModelSettings={onOpenModelSettings}
            onSelectedModelChange={onSelectedModelChange}
            promptActions={promptActions}
            selectedModel={selectedModel}
            selectedModelId={selectedModelId}
            t={t}
          />
        }
        composerRef={composerRef}
        conversationLayoutRef={conversationLayoutRef}
      >
        <CopilotConversationView
          key={conversation.sessionResetVersion}
          conversation={conversation}
          conversationContextRef={conversationContextRef}
          draft={{
            hasAgentDraft,
            onApply: conversation.applyAgentDraft,
            onDiscard: conversation.discardAgentDraft,
            state: agentDraftState,
          }}
          hasConfiguredModel={Boolean(selectedModel)}
          messageActions={messageActions}
          onOpenModelSettings={onOpenModelSettings}
          promptActions={promptActions}
          t={t}
        />
      </CopilotPanelBodyFrame>
    </PromptInputProvider>
  )
}
