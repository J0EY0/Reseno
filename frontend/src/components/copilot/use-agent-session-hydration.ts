import { useEffect } from 'react'

import {
  loadActiveAgentRun,
  loadAgentSession,
} from '@/lib/agent-session-run-client'
import { connectAgentRun } from '@/lib/agent-stream-client'
import { isAbortError } from '@/lib/api-client'

import type {
  AgentConversationRuntimeRef,
  AgentConversationUpdates,
} from './agent-conversation-runtime'
import { hydrateAgentSession } from './copilot-message-model'
import type { ConsumeAgentRunStream } from './use-agent-run-stream'

export function useAgentSessionHydration({
  cancelScheduledSend,
  consumeRunStream,
  resumeId,
  retryAttempt,
  runtimeRef,
  updates,
}: {
  cancelScheduledSend: (rollback: boolean) => boolean
  consumeRunStream: ConsumeAgentRunStream
  resumeId?: string
  retryAttempt: number
  runtimeRef: AgentConversationRuntimeRef
  updates: AgentConversationUpdates
}) {
  useEffect(() => {
    const runtime = runtimeRef.current
    let cancelled = false
    const abortController = new AbortController()
    let resolveSessionReady: () => void = () => undefined
    let sessionReadyResolved = false
    const sessionReadyPromise = new Promise<void>((resolve) => {
      resolveSessionReady = resolve
    })
    const releaseSessionWaiters = () => {
      if (sessionReadyResolved) {
        return
      }
      sessionReadyResolved = true
      resolveSessionReady()
    }

    runtime.activeRequestAbort?.abort()
    runtime.activeRequestAbort = abortController
    runtime.sessionReady = false
    runtime.sessionReadyPromise = sessionReadyPromise
    runtime.activeRun = null
    runtime.stopRequested = false
    runtime.previewedEditsKey = null

    cancelScheduledSend(false)

    updates.setMessages([])
    updates.setStreamingMessage(null)
    updates.setIsResponding(false)
    updates.setSessionLoadError(false)
    updates.setSessionReady(false)
    runtime.sessionRevision = null
    runtime.optimisticMessageOwner = null

    if (!resumeId) {
      runtime.sessionReady = true
      updates.setSessionReady(true)
      releaseSessionWaiters()
      runtime.sessionReadyPromise = null
      runtime.activeRequestAbort = null
      return () => {
        cancelled = true
        abortController.abort()
      }
    }

    void (async () => {
      try {
        // Both reads depend only on resumeId, so start them together. Capture
        // the run rejection now so a failed session read cannot orphan it.
        const sessionRequest = loadAgentSession(resumeId, {
          signal: abortController.signal,
        })
        const activeRunRequest = loadActiveAgentRun(resumeId, {
          signal: abortController.signal,
        }).then(
          (run) => ({ status: 'fulfilled' as const, run }),
          (error: unknown) => ({ status: 'rejected' as const, error }),
        )
        const { draftSnapshot, panelMessages, session } =
          await hydrateAgentSession(sessionRequest)
        if (cancelled || runtime.activeRequestAbort !== abortController) {
          return
        }

        updates.setMessages(panelMessages)
        runtime.sessionRevision = session.revision
        runtime.onReconcileAgentDraft(draftSnapshot)

        const activeRunResult = await activeRunRequest
        if (activeRunResult.status === 'rejected') {
          throw activeRunResult.error
        }
        const { run } = activeRunResult
        if (cancelled || runtime.activeRequestAbort !== abortController) {
          return
        }
        runtime.sessionReady = true
        updates.setSessionReady(true)
        releaseSessionWaiters()
        if (!run || run.status !== 'active') {
          if (runtime.activeRequestAbort === abortController) {
            runtime.activeRequestAbort = null
          }
          return
        }

        runtime.requestResume = run.baseResume
        runtime.activeRun = run
        runtime.isResponding = true
        updates.setIsResponding(true)
        await consumeRunStream(
          (options) => connectAgentRun(run, options),
          abortController,
        )
      } catch (error) {
        releaseSessionWaiters()
        if (
          !cancelled &&
          runtime.activeRequestAbort === abortController &&
          !isAbortError(error)
        ) {
          console.error('Failed to restore agent session.', error)
          updates.setSessionLoadError(true)
        }
        if (runtime.activeRequestAbort === abortController) {
          runtime.activeRequestAbort = null
        }
      } finally {
        releaseSessionWaiters()
        if (runtime.sessionReadyPromise === sessionReadyPromise) {
          runtime.sessionReadyPromise = null
        }
      }
    })()

    return () => {
      cancelled = true
      releaseSessionWaiters()
      abortController.abort()
      if (runtime.sessionReadyPromise === sessionReadyPromise) {
        runtime.sessionReadyPromise = null
      }
      if (runtime.activeRequestAbort === abortController) {
        runtime.activeRequestAbort = null
      }
    }
  }, [
    cancelScheduledSend,
    consumeRunStream,
    resumeId,
    retryAttempt,
    runtimeRef,
    updates,
  ])
}
