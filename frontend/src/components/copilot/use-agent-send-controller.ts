import { useCallback, useEffect, useRef } from 'react'
import { toast } from 'sonner'

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
import { createId } from '@/lib/resume'
import type {
  AgentChatAttachment,
  AgentChatUserMessage,
  AgentDraftState,
  AgentRunStatus,
} from '@/types/api'
import type { DocumentLocale, ModelConfig, ResumeData } from '@/types/resume'

import {
  isPendingSendOwner,
  setAgentRequestPhase,
  type AgentConversationRuntimeRef,
  type AgentConversationUpdates,
} from './agent-conversation-runtime'
import {
  toConversationMessage,
  type AgentPanelMessage,
} from './copilot-message-model'
import type {
  AgentSendOperation,
  AgentSendOptions,
  SendAgentPrompt,
} from './copilot-panel-types'
import type {
  ConsumeAgentRunStream,
  RefreshAgentSession,
} from './use-agent-run-stream'

const AGENT_REQUEST_DEBOUNCE_MS = 420

function waitForAgentSendPreflight(
  task: Promise<unknown>,
  signal: AbortSignal,
): Promise<boolean> {
  if (signal.aborted) {
    return Promise.resolve(false)
  }

  return new Promise<boolean>((resolve, reject) => {
    let settled = false
    const removeAbortListener = () => {
      signal.removeEventListener('abort', handleAbort)
    }
    const settle = (completed: boolean) => {
      if (settled) {
        return
      }
      settled = true
      removeAbortListener()
      resolve(completed)
    }
    const handleAbort = () => settle(false)

    signal.addEventListener('abort', handleAbort, { once: true })
    void task.then(
      () => settle(true),
      (error) => {
        if (settled) {
          return
        }
        settled = true
        removeAbortListener()
        reject(error)
      },
    )
  })
}

function ownsAgentSendPreflight(
  current: AbortController | null,
  owner: AbortController,
) {
  return current === owner && !owner.signal.aborted
}

export function useAgentSendController({
  agentDraftState,
  consumeRunStream,
  documentLocale,
  isSessionMutationPending,
  messages,
  onBeforeSend,
  refreshAgentSession,
  resume,
  resumeId,
  retrySession,
  runtimeRef,
  selectedModelConfig,
  updates,
}: {
  agentDraftState: AgentDraftState | null
  consumeRunStream: ConsumeAgentRunStream
  documentLocale: DocumentLocale
  isSessionMutationPending: boolean
  messages: AgentPanelMessage[]
  onBeforeSend?: () => Promise<void>
  refreshAgentSession: RefreshAgentSession
  resume: ResumeData
  resumeId?: string
  retrySession: () => void
  runtimeRef: AgentConversationRuntimeRef
  selectedModelConfig: ModelConfig | null
  updates: AgentConversationUpdates
}) {
  const preflightAbortRef = useRef<AbortController | null>(null)
  const cancelAgentSendPreflight = useCallback(() => {
    const preflight = preflightAbortRef.current
    if (!preflight) {
      return false
    }

    preflightAbortRef.current = null
    preflight.abort()
    return true
  }, [])

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
      setAgentRequestPhase(runtime, updates, 'idle')
      return true
    },
    [runtimeRef, updates],
  )

  const stopResponding = useCallback(() => {
    const runtime = runtimeRef.current
    if (cancelAgentSendPreflight()) {
      setAgentRequestPhase(runtime, updates, 'idle')
      return
    }
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
      void stopAgentRun(activeRun.id).then(() => {
        if (
          runtime.activeRun === activeRun &&
          !runtime.activeRequestAbort
        ) {
          retrySession()
        }
      }).catch((error) => {
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
      setAgentRequestPhase(runtime, updates, 'idle')
    }
  }, [
    cancelAgentSendPreflight,
    cancelScheduledSend,
    retrySession,
    runtimeRef,
    updates,
  ])

  const sendPrompt: SendAgentPrompt = useCallback(
    (
      text: string,
      files: AgentChatAttachment[] = [],
      options: AgentSendOptions = {},
    ): AgentSendOperation => {
      const modelConfigId = selectedModelConfig?.id ?? null
      let acceptanceSettled = false
      let resolveAcceptance: (accepted: boolean) => void = () => undefined
      const acceptedPromise = new Promise<boolean>((resolve) => {
        resolveAcceptance = resolve
      })
      const settleAcceptance = (accepted: boolean) => {
        if (acceptanceSettled) {
          return
        }
        acceptanceSettled = true
        resolveAcceptance(accepted)
      }
      let preflightOwner: AbortController | null = null
      const releasePreflight = () => {
        if (
          preflightOwner &&
          preflightAbortRef.current === preflightOwner
        ) {
          preflightAbortRef.current = null
        }
        preflightOwner = null
      }
      const releaseRejectedPreflight = () => {
        const ownsPreflight = Boolean(
          preflightOwner && preflightAbortRef.current === preflightOwner,
        )
        releasePreflight()
        const runtime = runtimeRef.current
        if (ownsPreflight && runtime.requestPhase === 'preparing') {
          setAgentRequestPhase(runtime, updates, 'idle')
        }
      }

      const completion = (async (): Promise<AgentRunStatus> => {
        const runtime = runtimeRef.current
        const prompt = text.trim()

        if (
          (!prompt && files.length === 0) ||
          runtime.requestPhase !== 'idle' ||
          isSessionMutationPending
        ) {
          return 'cancelled'
        }

        preflightAbortRef.current?.abort()
        const preflightAbortController = new AbortController()
        preflightOwner = preflightAbortController
        preflightAbortRef.current = preflightAbortController
        // Claim the request before the first asynchronous preflight step so
        // every send path exposes feedback and rejects concurrent actions.
        setAgentRequestPhase(runtime, updates, 'preparing')
        const preflightCompleted = await waitForAgentSendPreflight(
          Promise.resolve().then(() => onBeforeSend?.()),
          preflightAbortController.signal,
        )
        if (
          !preflightCompleted ||
          !ownsAgentSendPreflight(
            preflightAbortRef.current,
            preflightAbortController,
          )
        ) {
          return 'cancelled'
        }

        await runtime.sessionReadyPromise
        if (
          !ownsAgentSendPreflight(
            preflightAbortRef.current,
            preflightAbortController,
          )
        ) {
          return 'cancelled'
        }

        if (!runtime.sessionReady) {
          return 'failed'
        }
        if (runtimeRef.current.requestPhase !== 'preparing') {
          return 'cancelled'
        }
        if (resumeId && !runtime.sessionRevision) {
          const session = await refreshAgentSession(resumeId, true)
          if (
            !ownsAgentSendPreflight(
              preflightAbortRef.current,
              preflightAbortController,
            )
          ) {
            return 'cancelled'
          }
          if (!session) {
            return 'failed'
          }
        }
        const loadedRevision = runtime.sessionRevision
        let expectedRevision: string | undefined =
          resumeId && loadedRevision ? loadedRevision : undefined
        if (resumeId && !expectedRevision) {
          return 'failed'
        }

        const baseMessages = options.baseMessages ?? messages
        const rollbackMessages = messages
        const userMessage: AgentPanelMessage = {
          files,
          id: options.messageId ?? createId('agent-user'),
          role: 'user',
          text: prompt,
        }
        const nextMessages = [...baseMessages, userMessage]
        const currentMessage: AgentChatUserMessage = {
          files,
          id: userMessage.id,
          role: 'user',
          text: prompt,
        }
        const priorMessages = baseMessages.map(toConversationMessage)
        const apiMessages = [...priorMessages, currentMessage]

        // Abort an in-flight restore before publishing the optimistic message
        // so stale history can never replace this newly submitted prompt.
        runtime.activeRequestAbort?.abort()
        runtime.activeRequestAbort = null
        updates.setSessionLoadError(false)
        cancelScheduledSend(false)
        updates.setMessages(nextMessages)
        runtime.optimisticMessageOwner = userMessage.id
        updates.setStreamingMessage(null)
        runtime.previewedEditsKey = null
        runtime.requestResume = resume

        return await new Promise<AgentRunStatus>((resolve) => {
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
                    locale: documentLocale,
                    messages: apiMessages,
                    revision,
                  })
                  runtime.sessionRevision = session.revision
                  expectedRevision = session.revision
                  runAccepted = true
                }

                if (abortController.signal.aborted) {
                  status = 'cancelled'
                } else {
                  status = await consumeRunStream(
                    (streamOptions) =>
                      sendAgentChatMessage(
                        {
                          expectedRevision,
                          locale: documentLocale,
                          message: currentMessage,
                          messages: resumeId ? [] : priorMessages,
                          modelConfig: modelConfigId
                            ? { id: modelConfigId }
                            : null,
                          resume,
                          resumeId,
                          draftState: agentDraftState,
                          stream: true,
                        },
                        {
                          ...streamOptions,
                          onRun: (run) => {
                            runAccepted = true
                            settleAcceptance(true)
                            streamOptions.onRun?.(run)
                          },
                        },
                    ),
                    abortController,
                    {
                      notifyOnFailure: false,
                      throwOnFailure: true,
                    },
                  )
                }
              } catch (error) {
                failure = error
                status = isAbortError(error) ? 'cancelled' : 'failed'
                if (
                  status === 'failed' &&
                  resumeId &&
                  (isApiErrorCode(
                    error,
                    'AGENT_SESSION_REVISION_CONFLICT',
                  ) || isApiErrorCode(error, 'AGENT_SESSION_TURN_CONFLICT'))
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
                    'Failed to start or consume the Agent run.',
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
                  setAgentRequestPhase(runtime, updates, 'idle')
                }
                pending?.resolve(status)
              }
            })()
          }, AGENT_REQUEST_DEBOUNCE_MS)
          releasePreflight()
        })
      })()

      // Every pre-acceptance exit settles the input gate as rejected. The
      // handler above is the only path that can mark server acceptance.
      void completion.then(
        () => {
          releaseRejectedPreflight()
          settleAcceptance(false)
        },
        () => {
          releaseRejectedPreflight()
          settleAcceptance(false)
        },
      )

      return {
        accepted: acceptedPromise,
        completion,
        submitted: preflightOwner !== null,
      }
    },
    [
      agentDraftState,
      cancelScheduledSend,
      consumeRunStream,
      documentLocale,
      isSessionMutationPending,
      messages,
      onBeforeSend,
      refreshAgentSession,
      resume,
      resumeId,
      runtimeRef,
      selectedModelConfig,
      updates,
    ],
  )

  useEffect(() => {
    const runtime = runtimeRef.current
    return () => {
      cancelAgentSendPreflight()
      if (runtime.replyTimer !== null) {
        window.clearTimeout(runtime.replyTimer)
        runtime.replyTimer = null
      }
      runtime.pendingSend?.resolve('cancelled')
      runtime.pendingSend = null
      runtime.activeRequestAbort?.abort()
    }
  }, [cancelAgentSendPreflight, runtimeRef])

  return { cancelScheduledSend, sendPrompt, stopResponding }
}
