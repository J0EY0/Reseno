import { useCallback } from 'react'
import { toast } from 'sonner'

import { stopAgentRun } from '@/lib/agent-session-run-client'
import type { AgentChatStreamOptions } from '@/lib/agent-stream-client'
import { isAbortError, isApiErrorToastShown } from '@/lib/api-client'
import type {
  AgentChatResponse,
  AgentResumeEditSuggestion,
  AgentRunStatus,
  AgentSessionResponse,
  AgentTransactionState,
} from '@/types/api'
import type { ResumeData } from '@/types/resume'

import {
  setAgentRequestPhase,
  type AgentConversationRuntimeRef,
  type AgentConversationUpdates,
} from './agent-conversation-runtime'
import {
  getEditsPreviewKey,
  toAssistantPanelMessage,
} from './copilot-message-model'

export type RefreshAgentSession = (
  expectedResumeId: string,
  replaceMessages?: boolean,
) => Promise<AgentSessionResponse | null>

interface ConsumeAgentRunStreamOptions {
  notifyOnFailure?: boolean
  throwOnFailure?: boolean
}

export type ConsumeAgentRunStream = (
  start: (options: AgentChatStreamOptions) => Promise<AgentChatResponse>,
  abortController: AbortController,
  options?: ConsumeAgentRunStreamOptions,
) => Promise<AgentRunStatus>

export function useAgentRunStream({
  refreshAgentSession,
  runtimeRef,
  updates,
}: {
  refreshAgentSession: RefreshAgentSession
  runtimeRef: AgentConversationRuntimeRef
  updates: AgentConversationUpdates
}): ConsumeAgentRunStream {
  const syncPreviewEdits = useCallback(
    (
      edits: AgentResumeEditSuggestion[] | undefined,
      baseResume: ResumeData,
      sourceMessageId: string | undefined,
      transactionState: AgentTransactionState | undefined,
    ) => {
      const runtime = runtimeRef.current
      if (
        !edits?.length ||
        (transactionState !== 'provisional' &&
          transactionState !== 'committed')
      ) {
        return
      }

      const key = `${transactionState}:${getEditsPreviewKey(edits)}`
      if (runtime.previewedEditsKey === key) {
        return
      }

      runtime.previewedEditsKey = key
      runtime.onPreviewAgentEdits(
        edits,
        baseResume,
        sourceMessageId,
        transactionState,
      )
    },
    [runtimeRef],
  )

  return useCallback(
    async (
      start,
      abortController,
      {
        notifyOnFailure = true,
        throwOnFailure = false,
      }: ConsumeAgentRunStreamOptions = {},
    ): Promise<AgentRunStatus> => {
      const runtime = runtimeRef.current
      let streamedMessageId: string | undefined
      let runMayStillBeActive = false
      const expectedResumeId = runtime.currentResumeId

      try {
        const response = await start({
          onRun: (run) => {
            if (abortController.signal.aborted) {
              return
            }

            runtime.requestResume = run.baseResume
            runtime.activeRun = run.status === 'active' ? run : null

            if (run.status === 'active') {
              // The run id is the acceptance boundary: from here the backend
              // owns the turn and the selected model is frozen for this run.
              setAgentRequestPhase(runtime, updates, 'responding')
            }

            if (run.status === 'active' && runtime.stopRequested) {
              void stopAgentRun(run.id).catch((error) => {
                runtime.stopRequested = false
                console.error('Failed to stop agent run.', error)
                if (!isApiErrorToastShown(error)) {
                  toast.error(runtime.requestFailedText, {
                    closeButton: true,
                  })
                }
              })
            }
          },
          onMessage: (streamedMessage) => {
            if (abortController.signal.aborted) {
              return
            }

            streamedMessageId = streamedMessage.id
            updates.setStreamingMessage(
              toAssistantPanelMessage(
                streamedMessage,
                runtime.transientStatusTexts,
              ),
            )

            if (streamedMessage.transactionState === 'rolled_back') {
              runtime.onRollbackAgentDraft(streamedMessage.id)
              return
            }

            syncPreviewEdits(
              streamedMessage.edits,
              runtime.requestResume,
              streamedMessage.id,
              streamedMessage.transactionState,
            )
          },
          signal: abortController.signal,
        })

        if (abortController.signal.aborted) {
          return 'cancelled'
        }

        const finalMessage = toAssistantPanelMessage(
          response.message,
          runtime.transientStatusTexts,
        )
        const shouldRollback =
          response.message.transactionState === 'rolled_back' ||
          response.status === 'cancelled' ||
          response.status === 'failed'

        if (shouldRollback) {
          runtime.onRollbackAgentDraft(response.message.id)
        } else {
          syncPreviewEdits(
            response.message.edits,
            runtime.requestResume,
            response.message.id,
            response.message.transactionState,
          )
        }

        // A stopped run may durably retain the text already shown to the user.
        // Keep that terminal snapshot locally even if session refresh fails.
        if (
          response.messageDone &&
          (response.status === 'completed' || response.status === 'cancelled')
        ) {
          updates.setMessages((currentMessages) => {
            const existingIndex = currentMessages.findIndex(
              (message) => message.id === finalMessage.id,
            )

            if (existingIndex < 0) {
              return [...currentMessages, finalMessage]
            }

            return currentMessages.map((message, index) =>
              index === existingIndex ? finalMessage : message,
            )
          })
        }
        return response.status
      } catch (error) {
        if (isAbortError(error)) {
          return 'cancelled'
        }

        // A non-retryable subscription failure means this browser can no
        // longer observe a commit. Never leave its provisional preview active.
        runMayStillBeActive = runtime.activeRun?.status === 'active'
        runtime.onRollbackAgentDraft(streamedMessageId)
        if (
          runMayStillBeActive &&
          runtime.activeRequestAbort === abortController
        ) {
          updates.setSessionLoadError(true)
        }
        console.error('Failed to consume agent run.', error)
        if (notifyOnFailure && !isApiErrorToastShown(error)) {
          toast.error(runtime.requestFailedText, {
            closeButton: true,
          })
        }
        if (throwOnFailure) {
          throw error
        }
        return 'failed'
      } finally {
        if (expectedResumeId && !runMayStillBeActive) {
          try {
            await refreshAgentSession(expectedResumeId, true)
          } catch (error) {
            if (!isAbortError(error)) {
              console.error(
                'Failed to refresh the Agent session revision.',
                error,
              )
              if (runtime.currentResumeId === expectedResumeId) {
                runtime.sessionRevision = null
                runtime.sessionReady = false
                updates.setSessionReady(false)
                updates.setSessionLoadError(true)
              }
            }
          }
        }

        if (runtime.activeRequestAbort === abortController) {
          runtime.activeRequestAbort = null
          if (!runMayStillBeActive) {
            runtime.activeRun = null
            runtime.stopRequested = false
            updates.setStreamingMessage(null)
            setAgentRequestPhase(runtime, updates, 'idle')
          }
        }
      }
    },
    [refreshAgentSession, runtimeRef, syncPreviewEdits, updates],
  )
}
