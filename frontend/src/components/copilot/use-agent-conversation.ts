import { useCallback, useMemo, useState } from 'react'

import type { AppMessages, Locale } from '@/i18n'
import { loadAgentSession } from '@/lib/agent-session-run-client'
import { mergeStreamingAgentMessage } from '@/lib/agent-panel-state'
import type { AgentDraftState } from '@/types/api'
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
  CopilotPanelProps,
} from './copilot-panel-types'
import { useAgentRunStream } from './use-agent-run-stream'
import { useAgentSendController } from './use-agent-send-controller'
import { useAgentSessionHydration } from './use-agent-session-hydration'

export function useAgentConversation({
  agentDraftState,
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
  const [sessionLoadError, setSessionLoadError] = useState(false)
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0)
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

  const refreshAgentSession = useCallback(
    async (expectedResumeId: string, replaceMessages = false) => {
      const runtime = runtimeRef.current
      const { draftSnapshot, panelMessages, session } = await hydrateAgentSession(
        loadAgentSession(expectedResumeId),
      )
      if (expectedResumeId !== runtime.currentResumeId) {
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

  return {
    isResponding,
    isSessionReady,
    messages,
    retrySession,
    sendPrompt,
    sessionLoadError,
    sessionResetVersion: sessionLoadAttempt,
    stopResponding,
    streamingMessage,
    visibleMessages,
  }
}
