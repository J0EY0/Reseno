import type { AppMessages, Locale } from '@/i18n'
import type {
  AgentChatAttachment,
  AgentDraftState,
  AgentDraftSnapshot,
  AgentResumeEditSuggestion,
  AgentRunStatus,
  AgentSessionResponse,
  AgentTransactionState,
} from '@/types/api'
import type { ModelConfig, ResumeData } from '@/types/resume'

import type { AgentPanelMessage } from './copilot-message-model'

export type AgentPanelStatus = 'loading' | 'ready' | 'responding' | 'error'

export interface CopilotPanelProps {
  isPanelCollapsed: boolean
  resumeId?: string
  t: AppMessages
  locale: Locale
  resume: ResumeData
  modelConfigs: ModelConfig[]
  selectedModelId: string
  onSelectedModelChange: (modelId: string) => void
  hasAgentDraft: boolean
  agentDraftState: AgentDraftState | null
  onPreviewAgentEdits: (
    edits: AgentResumeEditSuggestion[],
    baseResume: ResumeData,
    sourceMessageId?: string,
    transactionState?: AgentTransactionState,
  ) => void
  onRollbackAgentDraft: (sourceMessageId?: string) => void
  onReconcileAgentDraft: (snapshot: AgentDraftSnapshot | null) => void
  onApplyAgentDraft: () => Promise<AgentSessionResponse | null>
  onDiscardAgentDraft: () => Promise<AgentSessionResponse | null>
  onOpenModelSettings: () => void
  onStatusChange: (status: AgentPanelStatus) => void
  onBeforeSend?: () => Promise<void>
}

export interface AgentSendOptions {
  baseMessages?: AgentPanelMessage[]
  messageId?: string
  replaceSessionBeforeSend?: boolean
}

/**
 * Server acceptance and run completion are intentionally separate. Composer
 * input may clear after acceptance without waiting for a potentially long run.
 */
export interface AgentSendOperation {
  accepted: Promise<boolean>
  completion: Promise<AgentRunStatus>
}

export type SendAgentPrompt = (
  text: string,
  files?: AgentChatAttachment[],
  options?: AgentSendOptions,
) => AgentSendOperation

export interface AgentConversationController {
  applyAgentDraft: () => Promise<void>
  discardAgentDraft: () => Promise<void>
  isResponding: boolean
  isSessionReady: boolean
  messages: AgentPanelMessage[]
  retrySession: () => void
  sessionResetVersion: number
  sendPrompt: SendAgentPrompt
  sessionLoadError: boolean
  status: AgentPanelStatus
  stopResponding: () => void
  streamingMessage: AgentPanelMessage | null
  visibleMessages: AgentPanelMessage[]
}
