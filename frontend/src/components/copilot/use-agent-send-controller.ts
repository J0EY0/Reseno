import { useCallback, useEffect } from 'react'
import { toast } from 'sonner'

import type { AppMessages, Locale } from '@/i18n'
import {
  replaceAgentSession,
  stopAgentRun,
} from '@/lib/agent-session-run-client'
import { sendAgentChatMessage } from '@/lib/agent-stream-client'
import {
  shouldRollbackOptimisticAgentMessages,
} from '@/lib/agent-panel-state'
import {
  isAbortError,
  isApiErrorCode,
  isApiErrorToastShown,
} from '@/lib/api-client'
import { createId, getKeywordMatch } from '@/lib/resume'
import type {
  AgentChatAttachment,
  AgentDraftState,
  AgentRunStatus,
} from '@/types/api'
import type {
  KeywordMatch,
  ModelConfig,
  ResumeData,
} from '@/types/resume'

import {
  isPendingSendOwner,
  type AgentConversationRuntimeRef,
  type AgentConversationUpdates,
} from './agent-conversation-runtime'
import { isLikelyJobBriefPrompt } from './agent-prompt-context'
import {
  toConversationMessage,
  type AgentPanelMessage,
} from './copilot-message-model'
import type {
  AgentSendOptions,
  SendAgentPrompt,
} from './copilot-panel-types'
import type {
  ConsumeAgentRunStream,
  RefreshAgentSession,
} from './use-agent-run-stream'

const AGENT_REQUEST_DEBOUNCE_MS = 420

export function useAgentSendController({
  agentDraftState,
  consumeRunStream,
  jobBrief,
  keywordMatch,
  locale,
  messages,
  onBeforeSend,
  onJobBriefChange,
  refreshAgentSession,
  resume,
  resumeId,
  runtimeRef,
  selectedModel,
  t,
  updates,
}: {
  agentDraftState: AgentDraftState | null
  consumeRunStream: ConsumeAgentRunStream
  jobBrief: string
  keywordMatch: KeywordMatch
  locale: Locale
  messages: AgentPanelMessage[]
  onBeforeSend?: () => Promise<void>
  onJobBriefChange: (value: string) => void
  refreshAgentSession: RefreshAgentSession
  resume: ResumeData
  resumeId?: string
  runtimeRef: AgentConversationRuntimeRef
  selectedModel: ModelConfig | null
  t: AppMessages
  updates: AgentConversationUpdates
}) {
  const cancelScheduledSend = useCallback(
    (rollback: boolean) => {
      const runtime = runtimeRef.current
      if (runtime.replyTimer === null) {
        return false
      }

      window.clearTimeout(runtime.replyTimer)
      runtime.replyTimer = null
      const pending = runtime.pendingSend
      runtime.pendingSend = null
      const ownsOptimisticMessage = Boolean(
        pending &&
          isPendingSendOwner(
            runtime.optimisticMessageOwner,
            pending.optimisticMessageId,
            pending.resumeId,
            runtime.currentResumeId,
          ),
      )

      if (rollback && pending && ownsOptimisticMessage) {
        updates.setMessages(pending.rollbackMessages)
      }
      if (ownsOptimisticMessage) {
        runtime.optimisticMessageOwner = null
      }
      pending?.resolve('cancelled')
      runtime.isResponding = false
      updates.setIsResponding(false)
      return true
    },
    [runtimeRef, updates],
  )

  const stopResponding = useCallback(() => {
    const runtime = runtimeRef.current
    if (cancelScheduledSend(true)) {
      return
    }

    if (runtime.stopRequested) {
      return
    }

    runtime.stopRequested = true
    const activeRun = runtime.activeRun

    // Keep the subscriber connected so the rollback event can clear any
    // provisional preview before the run reports its terminal state.
    if (activeRun) {
      void stopAgentRun(activeRun.id).catch((error) => {
        runtime.stopRequested = false
        console.error('Failed to stop agent run.', error)
        if (!isApiErrorToastShown(error)) {
          toast.error(runtime.requestFailedText, {
            closeButton: true,
          })
        }
      })
      return
    }

    if (!runtime.activeRequestAbort) {
      runtime.stopRequested = false
      updates.setIsResponding(false)
    }
  }, [cancelScheduledSend, runtimeRef, updates])

  const sendPrompt: SendAgentPrompt = useCallback(
    async (
      text: string,
      files: AgentChatAttachment[] = [],
      options: AgentSendOptions = {},
    ): Promise<AgentRunStatus> => {
      const runtime = runtimeRef.current
      const prompt = text.trim()

      if ((!prompt && files.length === 0) || runtime.isResponding) {
        return 'cancelled'
      }

      await onBeforeSend?.()
      await runtime.sessionReadyPromise

      if (runtime.isResponding) {
        return 'cancelled'
      }
      if (resumeId && !runtime.sessionRevision) {
        const session = await refreshAgentSession(resumeId, true)
        if (!session) {
          return 'failed'
        }
      }

      const baseMessages = options.baseMessages ?? messages
      const rollbackMessages = messages
      const looksLikeJobBrief = isLikelyJobBriefPrompt(prompt)
      const nextJobBrief = looksLikeJobBrief ? prompt : jobBrief
      const nextKeywordMatch = looksLikeJobBrief
        ? getKeywordMatch(resume, nextJobBrief, 0, t)
        : keywordMatch
      const userMessage: AgentPanelMessage = {
        files,
        id: options.messageId ?? createId('agent-user'),
        role: 'user',
        text: prompt,
      }
      const nextMessages = [...baseMessages, userMessage]
      const apiMessages = nextMessages.map(toConversationMessage)

      // Abort an in-flight restore before publishing the optimistic message so
      // stale history can never replace this newly submitted prompt.
      runtime.activeRequestAbort?.abort()
      runtime.activeRequestAbort = null
      updates.setSessionLoadError(false)
      cancelScheduledSend(false)
      updates.setIsResponding(true)
      runtime.isResponding = true
      updates.setMessages(nextMessages)
      runtime.optimisticMessageOwner = userMessage.id
      updates.setStreamingMessage(null)
      runtime.previewedEditsKey = null
      runtime.requestResume = resume

      if (looksLikeJobBrief) {
        onJobBriefChange(prompt)
      }

      return new Promise<AgentRunStatus>((resolve) => {
        runtime.pendingSend = {
          optimisticMessageId: userMessage.id,
          resolve,
          resumeId,
          rollbackMessages,
        }
        runtime.replyTimer = window.setTimeout(() => {
          const pending = runtime.pendingSend
          runtime.pendingSend = null
          runtime.replyTimer = null

          void (async () => {
            const abortController = new AbortController()
            let failure: unknown
            let status: AgentRunStatus = 'failed'
            let runAccepted = false
            let sessionReconciled = false

            runtime.activeRequestAbort?.abort()
            runtime.activeRequestAbort = abortController

            try {
              if (options.replaceSessionBeforeSend && resumeId) {
                const revision = runtime.sessionRevision
                if (!revision) {
                  await refreshAgentSession(resumeId, true)
                  sessionReconciled = true
                  throw new Error(
                    'Cannot replace Agent history before loading its revision.',
                  )
                }

                const session = await replaceAgentSession(resumeId, {
                  locale,
                  messages: apiMessages,
                  revision,
                })
                runtime.sessionRevision = session.revision
                runAccepted = true
              }

              if (abortController.signal.aborted) {
                status = 'cancelled'
              } else {
                status = await consumeRunStream(
                  (streamOptions) =>
                    sendAgentChatMessage(
                      {
                        appliedActions: [],
                        clientTurnId: userMessage.id,
                        conversation: apiMessages,
                        expectedRevision:
                          runtime.sessionRevision ?? undefined,
                        files,
                        jobBrief: nextJobBrief,
                        keywordMatch: nextKeywordMatch,
                        locale,
                        message: toConversationMessage(userMessage),
                        messages: apiMessages,
                        modelConfig: selectedModel,
                        prompt,
                        resume,
                        resumeId,
                        draftState: agentDraftState,
                        stream: true,
                      },
                      {
                        ...streamOptions,
                        onRun: (run) => {
                          runAccepted = true
                          streamOptions.onRun?.(run)
                        },
                      },
                    ),
                  abortController,
                  false,
                )
              }
            } catch (error) {
              failure = error
              status = isAbortError(error) ? 'cancelled' : 'failed'
              if (
                status === 'failed' &&
                resumeId &&
                (isApiErrorCode(error, 'AGENT_SESSION_REVISION_CONFLICT') ||
                  isApiErrorCode(error, 'AGENT_SESSION_TURN_CONFLICT'))
              ) {
                try {
                  const session = await refreshAgentSession(resumeId, true)
                  sessionReconciled = Boolean(session)
                  if (sessionReconciled) {
                    runtime.onRollbackAgentDraft()
                  }
                } catch (refreshError) {
                  console.error(
                    'Failed to reconcile the Agent session after a conflict.',
                    refreshError,
                  )
                }
              }
              if (status === 'failed') {
                console.error(
                  'Failed to replace the agent session before editing.',
                  error,
                )
              }
            } finally {
              const ownsOptimisticMessage = Boolean(
                pending &&
                  isPendingSendOwner(
                    runtime.optimisticMessageOwner,
                    pending.optimisticMessageId,
                    pending.resumeId,
                    runtime.currentResumeId,
                  ),
              )
              if (
                status !== 'completed' &&
                !sessionReconciled &&
                pending &&
                ownsOptimisticMessage &&
                shouldRollbackOptimisticAgentMessages({
                  replaceSessionBeforeSend: Boolean(
                    options.replaceSessionBeforeSend,
                  ),
                  runAccepted,
                })
              ) {
                updates.setMessages(pending.rollbackMessages)
              }
              if (ownsOptimisticMessage) {
                runtime.optimisticMessageOwner = null
              }

              if (status === 'failed' && !isApiErrorToastShown(failure)) {
                toast.error(runtime.requestFailedText, {
                  closeButton: true,
                })
              }

              if (runtime.activeRequestAbort === abortController) {
                runtime.activeRequestAbort = null
                runtime.activeRun = null
                runtime.stopRequested = false
                updates.setStreamingMessage(null)
                runtime.isResponding = false
                updates.setIsResponding(false)
              }
              pending?.resolve(status)
            }
          })()
        }, AGENT_REQUEST_DEBOUNCE_MS)
      })
    },
    [
      agentDraftState,
      cancelScheduledSend,
      consumeRunStream,
      jobBrief,
      keywordMatch,
      locale,
      messages,
      onBeforeSend,
      onJobBriefChange,
      refreshAgentSession,
      resume,
      resumeId,
      runtimeRef,
      selectedModel,
      t,
      updates,
    ],
  )

  useEffect(() => {
    const runtime = runtimeRef.current
    return () => {
      if (runtime.replyTimer !== null) {
        window.clearTimeout(runtime.replyTimer)
        runtime.replyTimer = null
      }
      runtime.pendingSend?.resolve('cancelled')
      runtime.pendingSend = null
      runtime.activeRequestAbort?.abort()
    }
  }, [runtimeRef])

  return { cancelScheduledSend, sendPrompt, stopResponding }
}
