import type { AppMessages, Locale } from '@/i18n'
import type {
  AgentChatAttachment,
  AgentDraftState,
  AgentResumeEditSuggestion,
  AgentRunStatus,
  AgentTransactionState,
} from '@/types/api'
import type { KeywordMatch, ModelConfig, ResumeData } from '@/types/resume'

import type { AgentPanelMessage } from './copilot-message-model'

export interface CopilotPanelProps {
  mode?: 'docked' | 'sheet'
  resumeId?: string
  t: AppMessages
  locale: Locale
  resume: ResumeData
  jobBrief: string
  onJobBriefChange: (value: string) => void
  keywordMatch: KeywordMatch
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
  onApplyAgentDraft: () => void
  onDiscardAgentDraft: () => void
  onOpenModelSettings: () => void
  onBeforeSend?: () => Promise<void>
}

export interface AgentSendOptions {
  baseMessages?: AgentPanelMessage[]
  messageId?: string
  replaceSessionBeforeSend?: boolean
}

export type SendAgentPrompt = (
  text: string,
  files?: AgentChatAttachment[],
  options?: AgentSendOptions,
) => Promise<AgentRunStatus>

export interface AgentConversationController {
  isResponding: boolean
  messages: AgentPanelMessage[]
  retrySession: () => void
  sessionResetVersion: number
  sendPrompt: SendAgentPrompt
  sessionLoadError: boolean
  stopResponding: () => void
  streamingMessage: AgentPanelMessage | null
  visibleMessages: AgentPanelMessage[]
}
