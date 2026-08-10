import {
  useLayoutEffect,
  useRef,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from 'react'

import type { AppMessages } from '@/i18n'
import type {
  AgentResumeEditSuggestion,
  AgentDraftSnapshot,
  AgentRunResponse,
  AgentRunStatus,
  AgentTransactionState,
} from '@/types/api'
import type { ResumeData } from '@/types/resume'

import type { AgentPanelMessage } from './copilot-message-model'

export interface PendingAgentSend {
  optimisticMessageId: string
  resolve: (status: AgentRunStatus) => void
  resumeId?: string
  rollbackMessages: AgentPanelMessage[]
}

export interface AgentConversationRuntime {
  activeRequestAbort: AbortController | null
  activeRun: AgentRunResponse | null
  currentResumeId?: string
  isResponding: boolean
  onPreviewAgentEdits: (
    edits: AgentResumeEditSuggestion[],
    baseResume: ResumeData,
    sourceMessageId?: string,
    transactionState?: AgentTransactionState,
  ) => void
  onReconcileAgentDraft: (snapshot: AgentDraftSnapshot | null) => void
  onRollbackAgentDraft: (sourceMessageId?: string) => void
  optimisticMessageOwner: string | null
  pendingSend: PendingAgentSend | null
  previewedEditsKey: string | null
  replyTimer: number | null
  requestFailedText: string
  requestResume: ResumeData
  sessionReady: boolean
  sessionReadyPromise: Promise<void> | null
  sessionRevision: string | null
  stopRequested: boolean
  transientStatusTexts: readonly string[]
}

export type AgentConversationRuntimeRef =
  MutableRefObject<AgentConversationRuntime>

export interface AgentConversationUpdates {
  setIsResponding: (value: boolean) => void
  setMessages: Dispatch<SetStateAction<AgentPanelMessage[]>>
  setSessionLoadError: (value: boolean) => void
  setSessionReady: (value: boolean) => void
  setStreamingMessage: Dispatch<SetStateAction<AgentPanelMessage | null>>
}

export function isPendingSendOwner(
  currentOwnerId: string | null,
  pendingOwnerId: string | undefined,
  pendingResumeId: string | undefined,
  currentResumeId: string | undefined,
) {
  return (
    currentOwnerId !== null &&
    currentOwnerId === pendingOwnerId &&
    pendingResumeId === currentResumeId
  )
}

export function useAgentConversationRuntime({
  isResponding,
  onPreviewAgentEdits,
  onReconcileAgentDraft,
  onRollbackAgentDraft,
  resume,
  resumeId,
  t,
}: {
  isResponding: boolean
  onPreviewAgentEdits: AgentConversationRuntime['onPreviewAgentEdits']
  onReconcileAgentDraft: AgentConversationRuntime['onReconcileAgentDraft']
  onRollbackAgentDraft: AgentConversationRuntime['onRollbackAgentDraft']
  resume: ResumeData
  resumeId?: string
  t: AppMessages
}) {
  const runtimeRef = useRef<AgentConversationRuntime>({
    activeRequestAbort: null,
    activeRun: null,
    currentResumeId: resumeId,
    isResponding,
    onPreviewAgentEdits,
    onReconcileAgentDraft,
    onRollbackAgentDraft,
    optimisticMessageOwner: null,
    pendingSend: null,
    previewedEditsKey: null,
    replyTimer: null,
    requestFailedText: t.agentRequestFailed,
    requestResume: resume,
    sessionReady: false,
    sessionReadyPromise: null,
    sessionRevision: null,
    stopRequested: false,
    transientStatusTexts: t.agentTransientModelStatusTexts,
  })

  useLayoutEffect(() => {
    const runtime = runtimeRef.current
    runtime.currentResumeId = resumeId
    runtime.isResponding = isResponding
    runtime.onPreviewAgentEdits = onPreviewAgentEdits
    runtime.onReconcileAgentDraft = onReconcileAgentDraft
    runtime.onRollbackAgentDraft = onRollbackAgentDraft
    runtime.requestFailedText = t.agentRequestFailed
    runtime.transientStatusTexts = t.agentTransientModelStatusTexts
  }, [
    isResponding,
    onPreviewAgentEdits,
    onReconcileAgentDraft,
    onRollbackAgentDraft,
    resumeId,
    t.agentRequestFailed,
    t.agentTransientModelStatusTexts,
  ])

  return runtimeRef
}
