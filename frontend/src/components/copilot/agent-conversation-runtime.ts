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

/**
 * `preparing` covers local preflight and the request awaiting server
 * acceptance. `responding` starts only after an active run is identified.
 */
export type AgentRequestPhase = 'idle' | 'preparing' | 'responding'

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
  requestPhase: AgentRequestPhase
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
  setMessages: Dispatch<SetStateAction<AgentPanelMessage[]>>
  setRequestPhase: (value: AgentRequestPhase) => void
  setSessionLoadError: (value: boolean) => void
  setSessionReady: (value: boolean) => void
  setStreamingMessage: Dispatch<SetStateAction<AgentPanelMessage | null>>
}

/** Keep the synchronous request gate and its rendered phase in lockstep. */
export function setAgentRequestPhase(
  runtime: AgentConversationRuntime,
  updates: AgentConversationUpdates,
  phase: AgentRequestPhase,
) {
  runtime.requestPhase = phase
  updates.setRequestPhase(phase)
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
  requestPhase,
  onPreviewAgentEdits,
  onReconcileAgentDraft,
  onRollbackAgentDraft,
  resume,
  resumeId,
  t,
}: {
  requestPhase: AgentRequestPhase
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
    requestPhase,
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
    runtime.requestPhase = requestPhase
    runtime.onPreviewAgentEdits = onPreviewAgentEdits
    runtime.onReconcileAgentDraft = onReconcileAgentDraft
    runtime.onRollbackAgentDraft = onRollbackAgentDraft
    runtime.requestFailedText = t.agentRequestFailed
    runtime.transientStatusTexts = t.agentTransientModelStatusTexts
  }, [
    requestPhase,
    onPreviewAgentEdits,
    onReconcileAgentDraft,
    onRollbackAgentDraft,
    resumeId,
    t.agentRequestFailed,
    t.agentTransientModelStatusTexts,
  ])

  return runtimeRef
}
