import type { AppMessages } from '@/i18n'
import type { AgentDraftReviewController } from '@/hooks/use-resume-agent-draft'
import type {
  AgentChatAttachment,
  AgentDraftState,
  AgentDraftSnapshot,
  AgentResumeEditSuggestion,
  AgentRunStatus,
  AgentSessionResponse,
  AgentTransactionState,
} from '@/types/api'
import type { DocumentLocale, ModelConfig, ResumeData } from '@/types/resume'

import type { AgentPanelMessage } from './copilot-message-model'
import type { AgentRequestPhase } from './agent-conversation-runtime'

export type AgentPanelStatus = 'loading' | 'ready' | 'responding' | 'error'

export interface CopilotPanelProps {
  isPanelCollapsed: boolean
  resumeId?: string
  t: AppMessages
  documentLocale: DocumentLocale
  resume: ResumeData
  modelConfigs: ModelConfig[]
  selectedModelConfigId: string
  onSelectedModelConfigChange: (modelConfigId: string) => void
  agentDraftState: AgentDraftState | null
  agentDraftReview: AgentDraftReviewController | null
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

/** Local submission, server acceptance, and run completion are separate. */
export interface AgentSendOperation {
  submitted: boolean
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
  isSessionReady: boolean
  messages: AgentPanelMessage[]
  requestPhase: AgentRequestPhase
  retrySession: () => void
  sessionResetVersion: number
  sendPrompt: SendAgentPrompt
  sessionLoadError: boolean
  status: AgentPanelStatus
  stopResponding: () => void
  streamingMessage: AgentPanelMessage | null
  visibleMessages: AgentPanelMessage[]
}
