import { useCallback, useMemo, useRef, useState } from 'react'

import type { AppMessages } from '@/i18n'
import { loadAgentSession } from '@/lib/agent-session-run-client'
import { mergeStreamingAgentMessage } from '@/lib/agent-panel-state'
import type { AgentDraftState, AgentSessionResponse } from '@/types/api'
import type { DocumentLocale, ModelConfig, ResumeData } from '@/types/resume'

import {
  useAgentConversationRuntime,
  type AgentConversationUpdates,
  type AgentRequestPhase,
} from './agent-conversation-runtime'
import {
  hydrateAgentSession,
  type AgentPanelMessage,
} from './copilot-message-model'
import type {
  AgentConversationController,
  AgentPanelStatus,
  CopilotPanelProps,
} from './copilot-panel-types'
import { useAgentRunStream } from './use-agent-run-stream'
import { useAgentSendController } from './use-agent-send-controller'
import { useAgentSessionHydration } from './use-agent-session-hydration'

export function useAgentConversation({
  agentDraftState,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  documentLocale,
  onBeforeSend,
  onPreviewAgentEdits,
  onReconcileAgentDraft,
  onRollbackAgentDraft,
  resume,
  resumeId,
  selectedModelConfig,
  t,
}: {
  agentDraftState: AgentDraftState | null
  onApplyAgentDraft: CopilotPanelProps['onApplyAgentDraft']
  onDiscardAgentDraft: CopilotPanelProps['onDiscardAgentDraft']
  documentLocale: DocumentLocale
  onBeforeSend?: () => Promise<void>
  onPreviewAgentEdits: CopilotPanelProps['onPreviewAgentEdits']
  onReconcileAgentDraft: CopilotPanelProps['onReconcileAgentDraft']
  onRollbackAgentDraft: CopilotPanelProps['onRollbackAgentDraft']
  resume: ResumeData
  resumeId?: string
  selectedModelConfig: ModelConfig | null
  t: AppMessages
}): AgentConversationController {
  const [messages, setMessages] = useState<AgentPanelMessage[]>([])
  const [streamingMessage, setStreamingMessage] =
    useState<AgentPanelMessage | null>(null)
  const [requestPhase, setRequestPhase] =
    useState<AgentRequestPhase>('idle')
  const [isSessionReady, setSessionReady] = useState(false)
  const [isSessionMutationPending, setIsSessionMutationPending] =
    useState(false)
  const [sessionLoadError, setSessionLoadError] = useState(false)
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0)
  const sessionMutationPendingRef = useRef(false)
  const updates = useMemo<AgentConversationUpdates>(
    () => ({
      setMessages,
      setRequestPhase,
      setSessionLoadError,
      setSessionReady,
      setStreamingMessage,
    }),
    [],
  )
  const runtimeRef = useAgentConversationRuntime({
    requestPhase,
    onPreviewAgentEdits,
    onReconcileAgentDraft,
    onRollbackAgentDraft,
    resume,
    resumeId,
    t,
  })

  const adoptAgentSession = useCallback(
    async (
      expectedResumeId: string,
      sessionRequest: Promise<AgentSessionResponse>,
      replaceMessages = false,
    ) => {
      const runtime = runtimeRef.current
      const { draftSnapshot, panelMessages, session } = await hydrateAgentSession(
        sessionRequest,
      )
      if (
        expectedResumeId !== runtime.currentResumeId ||
        session.resumeId !== expectedResumeId
      ) {
        return null
      }

      runtime.sessionRevision = session.revision
      runtime.onReconcileAgentDraft(draftSnapshot)
      if (replaceMessages) {
        runtime.optimisticMessageOwner = null
        setMessages(panelMessages)
      }
      return session
    },
    [runtimeRef],
  )
  const refreshAgentSession = useCallback(
    (expectedResumeId: string, replaceMessages = false) =>
      adoptAgentSession(
        expectedResumeId,
        loadAgentSession(expectedResumeId),
        replaceMessages,
      ),
    [adoptAgentSession],
  )
  const adoptSession = useCallback(
    async (session: AgentSessionResponse) => {
      const expectedResumeId = runtimeRef.current.currentResumeId
      if (!expectedResumeId) {
        return
      }
      await adoptAgentSession(
        expectedResumeId,
        Promise.resolve(session),
        true,
      )
    },
    [adoptAgentSession, runtimeRef],
  )
  const runAgentDraftDecision = useCallback(
    async (decision: CopilotPanelProps['onApplyAgentDraft']) => {
      if (sessionMutationPendingRef.current) {
        return
      }
      sessionMutationPendingRef.current = true
      setIsSessionMutationPending(true)
      try {
        const session = await decision()
        if (session) {
          await adoptSession(session)
        }
      } finally {
        sessionMutationPendingRef.current = false
        setIsSessionMutationPending(false)
      }
    },
    [adoptSession],
  )
  const applyAgentDraft = useCallback(
    () => runAgentDraftDecision(onApplyAgentDraft),
    [onApplyAgentDraft, runAgentDraftDecision],
  )
  const discardAgentDraft = useCallback(
    () => runAgentDraftDecision(onDiscardAgentDraft),
    [onDiscardAgentDraft, runAgentDraftDecision],
  )
  const consumeRunStream = useAgentRunStream({
    refreshAgentSession,
    runtimeRef,
    updates,
  })
  const retrySession = useCallback(() => {
    setSessionLoadAttempt((attempt) => attempt + 1)
  }, [])
  const { cancelScheduledSend, sendPrompt, stopResponding } =
    useAgentSendController({
      agentDraftState,
      consumeRunStream,
      documentLocale,
      messages,
      onBeforeSend,
      refreshAgentSession,
      isSessionMutationPending,
      resume,
      resumeId,
      retrySession,
      runtimeRef,
      selectedModelConfig,
      updates,
    })

  useAgentSessionHydration({
    cancelScheduledSend,
    consumeRunStream,
    resumeId,
    retryAttempt: sessionLoadAttempt,
    runtimeRef,
    updates,
  })

  const visibleMessages = useMemo(
    () => mergeStreamingAgentMessage(messages, streamingMessage),
    [messages, streamingMessage],
  )
  const isConversationReady = isSessionReady && !isSessionMutationPending
  const isRequestBusy = requestPhase !== 'idle'
  const status: AgentPanelStatus = sessionLoadError
    ? 'error'
    : !isSessionReady
      ? 'loading'
      : isRequestBusy
        ? 'responding'
        : 'ready'

  return {
    applyAgentDraft,
    discardAgentDraft,
    runAgentDraftDecision,
    isSessionReady: isConversationReady,
    messages,
    requestPhase,
    retrySession,
    sendPrompt,
    sessionLoadError,
    sessionResetVersion: sessionLoadAttempt,
    status,
    stopResponding,
    streamingMessage,
    visibleMessages,
  }
}
