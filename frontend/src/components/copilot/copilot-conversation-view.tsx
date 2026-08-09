import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation'
import { Button } from '@/components/ui/button'
import type { AppMessages } from '@/i18n'
import { shouldShowAgentDraftActions } from '@/lib/agent-panel-state'
import { cn } from '@/lib/utils'
import type { AgentDraftState } from '@/types/api'
import { RotateCcw } from 'lucide-react'
import type { RefObject } from 'react'
import type { StickToBottomContext } from 'use-stick-to-bottom'

import { AgentAssistantMessageRow } from './copilot-message-presentation'
import { AgentPendingMessage } from './copilot-tool-presentation'
import { AgentUserMessageRow } from './copilot-user-message-row'
import type {
  AgentConversationController,
  CopilotPanelProps,
} from './copilot-panel-types'
import type { AgentMessageActions } from './use-agent-message-actions'
import type { AgentPromptActions } from './use-agent-prompt-actions'

export function CopilotConversationView({
  conversation,
  conversationContextRef,
  draft,
  hasConfiguredModel,
  messageActions,
  onOpenModelSettings,
  promptActions,
  t,
}: {
  conversation: AgentConversationController
  conversationContextRef: RefObject<StickToBottomContext | null>
  draft: {
    hasAgentDraft: boolean
    state: AgentDraftState | null
    onApply: CopilotPanelProps['onApplyAgentDraft']
    onDiscard: CopilotPanelProps['onDiscardAgentDraft']
  }
  hasConfiguredModel: boolean
  messageActions: AgentMessageActions
  onOpenModelSettings: () => void
  promptActions: AgentPromptActions
  t: AppMessages
}) {
  const {
    isResponding,
    messages,
    sessionLoadError,
    streamingMessage,
    visibleMessages,
  } = conversation

  return (
    <Conversation
      className="min-h-0 min-w-0 flex-1 overflow-x-hidden"
      contextRef={conversationContextRef}
      initial="instant"
      resize="instant"
    >
      <ConversationContent
        className={cn(
          'agent-thread-safe-area min-w-0 overflow-x-hidden px-3',
          visibleMessages.length === 0 &&
            'h-full min-h-full flex-1 justify-center',
        )}
        scrollClassName="agent-thread-scroll"
      >
        {visibleMessages.length === 0 ? (
          <ConversationEmptyState className="px-6 py-10">
            <div className="mx-auto grid max-w-[260px] justify-items-center gap-3 text-center">
              <p className="text-sm leading-6 text-muted-foreground">
                {sessionLoadError
                  ? t.agentHistoryLoadFailed
                  : t.agentEmptyPrompt}
              </p>
              {sessionLoadError ? (
                <Button
                  className="h-8 rounded-xl px-3 text-xs"
                  onClick={conversation.retrySession}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  <RotateCcw className="mr-1.5 size-3.5" />
                  {t.agentRetry}
                </Button>
              ) : !hasConfiguredModel ? (
                <Button
                  className="h-8 rounded-xl px-3 text-xs"
                  onClick={onOpenModelSettings}
                  size="sm"
                  type="button"
                >
                  {t.openModelSettings}
                </Button>
              ) : null}
            </div>
          </ConversationEmptyState>
        ) : (
          <div className="grid gap-3">
            {visibleMessages.map((message) => {
              if (message.role === 'user') {
                const isEditing =
                  messageActions.editingMessageId === message.id

                return (
                  <AgentUserMessageRow
                    copied={messageActions.copiedMessageId === message.id}
                    editedText={
                      isEditing
                        ? messageActions.editingMessageText
                        : message.text
                    }
                    isEditing={isEditing}
                    isResponding={isResponding}
                    key={message.id}
                    message={message}
                    onCancelEdit={messageActions.cancelEditingUserMessage}
                    onCopy={() => {
                      void messageActions.copyUserMessage(message)
                    }}
                    onDownloadAttachment={(file) => {
                      void messageActions.downloadHistoryAttachment(file)
                    }}
                    onEditTextChange={messageActions.setEditingMessageText}
                    onReferenceAttachment={
                      promptActions.referenceHistoryAttachment
                    }
                    onRetry={() => {
                      void messageActions.retryUserMessage(message)
                    }}
                    onStartEdit={() =>
                      messageActions.startEditingUserMessage(message)
                    }
                    onSubmitEdit={() => {
                      void messageActions.submitEditedUserMessage(message)
                    }}
                    retryable={message.id === messages.at(-1)?.id}
                    t={t}
                  />
                )
              }

              const showDraftActions =
                draft.hasAgentDraft &&
                shouldShowAgentDraftActions({
                  draft: draft.state,
                  isResponding,
                  messageId: message.id,
                  response: message.response,
                })

              return (
                <AgentAssistantMessageRow
                  hasAgentDraft={draft.hasAgentDraft}
                  isStreamingAssistant={
                    isResponding && streamingMessage?.id === message.id
                  }
                  key={message.id}
                  message={message}
                  onApplyAgentDraft={draft.onApply}
                  onDiscardAgentDraft={draft.onDiscard}
                  shouldShowDraftActions={showDraftActions}
                  t={t}
                />
              )
            })}

            {isResponding && !streamingMessage ? (
              <AgentPendingMessage label={t.agentToolThinking} />
            ) : null}
          </div>
        )}
      </ConversationContent>
      <ConversationScrollButton className="agent-thread-scroll-button z-20" />
    </Conversation>
  )
}
