import { useCallback, useMemo, useState } from 'react'

import type { AppMessages, Locale } from '@/i18n'
import { loadAgentSession } from '@/lib/agent-session-run-client'
import { mergeStreamingAgentMessage } from '@/lib/agent-panel-state'
import type { AgentDraftState } from '@/types/api'
import type {
  KeywordMatch,
  ModelConfig,
  ResumeData,
} from '@/types/resume'

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
  jobBrief,
  keywordMatch,
  locale,
  onBeforeSend,
  onJobBriefChange,
  onPreviewAgentEdits,
  onRollbackAgentDraft,
  resume,
  resumeId,
  selectedModel,
  t,
}: {
  agentDraftState: AgentDraftState | null
  jobBrief: string
  keywordMatch: KeywordMatch
  locale: Locale
  onBeforeSend?: () => Promise<void>
  onJobBriefChange: CopilotPanelProps['onJobBriefChange']
  onPreviewAgentEdits: CopilotPanelProps['onPreviewAgentEdits']
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
  const [sessionLoadError, setSessionLoadError] = useState(false)
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0)
  const updates = useMemo<AgentConversationUpdates>(
    () => ({
      setIsResponding,
      setMessages,
      setSessionLoadError,
      setStreamingMessage,
    }),
    [],
  )
  const runtimeRef = useAgentConversationRuntime({
    isResponding,
    onPreviewAgentEdits,
    onRollbackAgentDraft,
    resume,
    resumeId,
    t,
  })

  const refreshAgentSession = useCallback(
    async (expectedResumeId: string, replaceMessages = false) => {
      const runtime = runtimeRef.current
      const { panelMessages, session } = await hydrateAgentSession(
        loadAgentSession(expectedResumeId),
      )
      if (expectedResumeId !== runtime.currentResumeId) {
        return null
      }

      runtime.sessionRevision = session.revision
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
