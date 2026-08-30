import { useCallback, useMemo, useRef, useState } from 'react'

import type { AppMessages, Locale } from '@/i18n'
import { loadAgentSession } from '@/lib/agent-session-run-client'
import { mergeStreamingAgentMessage } from '@/lib/agent-panel-state'
import type { AgentDraftState, AgentSessionResponse } from '@/types/api'
import type { ModelConfig, ResumeData } from '@/types/resume'

import {
  useAgentConversationRuntime,
  type AgentConversationUpdates,
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
  locale,
  onBeforeSend,
  onPreviewAgentEdits,
  onReconcileAgentDraft,
  onRollbackAgentDraft,
  resume,
  resumeId,
  selectedModel,
  t,
}: {
  agentDraftState: AgentDraftState | null
  onApplyAgentDraft: CopilotPanelProps['onApplyAgentDraft']
  onDiscardAgentDraft: CopilotPanelProps['onDiscardAgentDraft']
  locale: Locale
  onBeforeSend?: () => Promise<void>
  onPreviewAgentEdits: CopilotPanelProps['onPreviewAgentEdits']
  onReconcileAgentDraft: CopilotPanelProps['onReconcileAgentDraft']
  onRollbackAgentDraft: CopilotPanelProps['onRollbackAgentDraft']
  resume: ResumeData
  resumeId?: string
  selectedModel: ModelConfig | null
  t: AppMessages
}): AgentConversationController {
  const [messages, setMessages] = useState<AgentPanelMessage[]>([])
  const [streamingMessage, setStreamingMessage] =
    useState<AgentPanelMessage | null>(null)
  const [isResponding, setIsResponding] = useState(false)
  const [isSessionReady, setSessionReady] = useState(false)
  const [isSessionMutationPending, setIsSessionMutationPending] =
    useState(false)
  const [sessionLoadError, setSessionLoadError] = useState(false)
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0)
  const sessionMutationPendingRef = useRef(false)
  const updates = useMemo<AgentConversationUpdates>(
    () => ({
      setIsResponding,
      setMessages,
      setSessionLoadError,
      setSessionReady,
      setStreamingMessage,
    }),
    [],
  )
  const runtimeRef = useAgentConversationRuntime({
    isResponding,
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
  const { cancelScheduledSend, sendPrompt, stopResponding } =
    useAgentSendController({
      agentDraftState,
      consumeRunStream,
      locale,
      messages,
      onBeforeSend,
      refreshAgentSession,
      isSessionMutationPending,
      resume,
      resumeId,
      runtimeRef,
      selectedModel,
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
  const retrySession = useCallback(() => {
    setSessionLoadAttempt((attempt) => attempt + 1)
  }, [])
  const isConversationReady = isSessionReady && !isSessionMutationPending
  const status: AgentPanelStatus = sessionLoadError
    ? 'error'
    : !isConversationReady
      ? 'loading'
      : isResponding
        ? 'responding'
        : 'ready'

  return {
    applyAgentDraft,
    discardAgentDraft,
    isResponding,
    isSessionReady: isConversationReady,
    messages,
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
