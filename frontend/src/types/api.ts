import type { Locale } from "@/i18n";
import type { ResumeEditOperation } from "@/types/resume-edit-operation.generated";
import type {
  AgentSettings,
  BuiltinResumeTemplateId,
  DefaultTemplateIds,
  DocumentLocale,
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ResumeData,
  ResumeDraftDiff,
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
  ResumeWorkspaceItem,
  ThemeMode,
} from "@/types/resume";

export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
  requestId?: string;
}

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  auth?: boolean;
  body?: unknown;
  cacheTtlMs?: number;
  credentials?: RequestCredentials;
  notifyOnError?: boolean;
  searchParams?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

export interface SaveResponse {
  savedAt: string;
  versionId?: string;
}

export interface WorkspaceVersionSummary {
  versionId: string;
  savedAt: string;
}

export interface WorkspaceVersionsResponse {
  versions: WorkspaceVersionSummary[];
}

export interface ResumeCreateRequest {
  documentLocale: DocumentLocale;
  title?: string;
  resume?: ResumeData;
  jobBrief?: string;
  typography?: ResumeWorkspaceItem["typography"];
  template?: ResumeWorkspaceItem["template"];
  templateSettings?: Partial<ResumeTemplateSettings> | null;
}

export type ResumeSaveMode = "autosave" | "checkpoint";

export interface ResumeSaveRequest {
  title: string;
  documentLocale: DocumentLocale;
  resume: ResumeData;
  jobBrief: string;
  typography: ResumeWorkspaceItem["typography"];
  template: ResumeWorkspaceItem["template"];
  templateSettings: Partial<ResumeTemplateSettings> | null;
}

export interface ResumeDetailResponse {
  resume: ResumeWorkspaceItem;
  savedAt: string;
  versionId: string;
}

export interface ResumeListResponse {
  resumes: ResumeWorkspaceItem[];
}

export interface DeletedResumeListResponse {
  resumes: DeletedResumeWorkspaceItem[];
}

export interface ResumeTrashResponse {
  resume: DeletedResumeWorkspaceItem;
}

export interface ResumeDeleteResponse {
  id: string;
}

export interface DefaultTemplateSaveResponse {
  defaultTemplateIds: DefaultTemplateIds;
}

export interface UserSettingsSaveResponse {
  locale: Locale;
  theme?: ThemeMode;
  agentSettings?: AgentSettings;
}

export interface TemplateDetailResponse {
  template: ResumeTemplateDefinition;
}

export interface TemplateTrashResponse {
  template: DeletedResumeTemplateDefinition;
}

export interface TemplateDeleteResponse {
  id: string;
}

export interface ImportResumeResponse {
  templates: EmbeddedTemplateArtifact[];
  resumes: ResumeArtifactItem[];
}

export interface ImportTemplatesResponse {
  templates: TemplateArtifactItem[];
}

export type CustomTemplateArtifactRef = `custom:${number}`;

export interface ResumeArtifactItem {
  title: string;
  documentLocale: DocumentLocale;
  resume: ResumeData;
  jobBrief: string;
  typography: NonNullable<ResumeWorkspaceItem["typography"]>;
  template: BuiltinResumeTemplateId | CustomTemplateArtifactRef;
  templateSettings: Partial<ResumeTemplateSettings> | null;
}

export interface EmbeddedTemplateArtifact {
  ref: CustomTemplateArtifactRef;
  definition: TemplateArtifactItem;
}

export interface ResumeArtifactV1 {
  format: "resumate.resume";
  formatVersion: 1;
  templates: EmbeddedTemplateArtifact[];
  resumes: ResumeArtifactItem[];
}

export type TemplateArtifactItem = Omit<
  ResumeTemplateDefinition,
  "id" | "updatedAt" | "isBuiltIn"
>;

export interface ExportResumePdfRequest {
  resumeId: string;
  fileNameSeed: string;
  savedAt: string;
  versionId?: string;
}

export interface ExportResumePdfResponse {
  exportId: string;
  downloadUrl: string;
  fileName: string;
  expiresAt: string;
}

export type ExportResumeImagesRequest = ExportResumePdfRequest;

export interface ExportResumeImagesResponse extends ExportResumePdfResponse {
  pageCount: number;
  isArchive: boolean;
}

export interface AgentChatAttachment {
  id?: string;
  filename?: string;
  mediaType?: string;
  kind?: "text" | "image";
  url?: string;
  content?: string;
}

export interface AgentConversationMessage {
  id?: string;
  role: "user" | "assistant";
  text: string;
  files?: AgentChatAttachment[];
  createdAt?: string;
  response?: Partial<AgentChatMessage>;
}

export interface AgentChatUserMessage {
  id: string;
  role: "user";
  text: string;
  files?: AgentChatAttachment[];
  createdAt?: string;
}

export type AgentDraftDecisionStatus = "applied" | "discarded";
export type AgentDraftReviewItemStatus =
  | "pending"
  | AgentDraftDecisionStatus;
export type AgentTransactionState =
  | "none"
  | "provisional"
  | "committed"
  | "rolled_back";
export type AgentRunStatus = "active" | "completed" | "cancelled" | "failed";
export type AgentTurnExecutionStatus =
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";
export type AgentTurnErrorCode =
  | "AGENT_PROVIDER_AUTH_ERROR"
  | "AGENT_PROVIDER_ERROR"
  | "AGENT_PROVIDER_TIMEOUT"
  | "AGENT_INTERNAL_ERROR"
  | "AGENT_RUN_CANCELLED"
  | "AGENT_EDIT_TRANSACTION_INCOMPLETE";

export interface AgentDraftState {
  id: string;
  sourceMessageId?: string;
  createdAt?: string;
  updatedAt?: string;
  resume: ResumeData;
  pendingCount: number;
  reviewItems: AgentDraftReviewItem[];
  edits: AgentResumeEditSuggestion[];
  diffs: ResumeDraftDiff[];
  transactionState?: AgentTransactionState;
}

export interface AgentDraftReviewItem {
  id: string;
  editIds: string[];
  status: AgentDraftReviewItemStatus;
}

export interface AgentCommittedDraft {
  baseResume: ResumeData;
  reviewItems: AgentDraftReviewItem[];
}

export interface AgentDraftSnapshot extends AgentCommittedDraft {
  edits: AgentResumeEditSuggestion[];
  sourceMessageId: string;
  transactionState: "committed";
}

export interface AgentChatRequest {
  resumeId?: string;
  expectedRevision?: string;
  message: AgentChatUserMessage;
  messages: AgentConversationMessage[];
  locale: DocumentLocale;
  resume: ResumeData;
  draftState?: AgentDraftState | null;
  modelConfig: AgentModelSelection | null;
  stream?: true;
}

export interface AgentModelSelection {
  id: string;
}

export interface AgentSource {
  id: string;
  title: string;
  sourceType: "attachment" | "web";
  url?: string;
  excerpt?: string;
}

export interface AgentToolInvocation {
  id: string;
  type: string;
  title: string;
  state:
    | "input-streaming"
    | "input-available"
    | "output-available"
    | "output-error"
    | "approval-requested"
    | "approval-responded"
    | "output-denied";
  input?: unknown;
  output?: unknown;
  errorText?: string;
  startedAt?: string;
  completedAt?: string;
}

export interface AgentResumeEditSuggestion {
  id: string;
  title: string;
  target: string;
  reason: string;
  replacement?: string;
  operation?: ResumeEditOperation;
  evidenceRefs?: string[];
  status?: "planned" | "executed" | "rejected";
  diffs?: ResumeDraftDiff[];
}

export interface AgentTimelinePart {
  id: string;
  type: "text" | "tool_group";
  text?: string;
  toolIds?: string[];
}

export interface AgentChatMessage {
  id: string;
  role: "assistant";
  tone?: "default" | "success";
  text: string;
  timeline?: AgentTimelinePart[];
  tools?: AgentToolInvocation[];
  sources?: AgentSource[];
  edits?: AgentResumeEditSuggestion[];
  draft?: AgentCommittedDraft;
  transactionState?: AgentTransactionState;
}

export interface AgentChatResponse {
  message: AgentChatMessage;
  runId: string;
  status: AgentRunStatus;
  executionState: AgentTurnExecutionStatus;
  errorCode: AgentTurnErrorCode | null;
  lastEventId: number;
  messageDone: boolean;
}

export interface AgentRunResponse {
  id: string;
  resumeId?: string;
  baseResume: ResumeData;
  status: AgentRunStatus;
  executionState: AgentTurnExecutionStatus;
  errorCode: AgentTurnErrorCode | null;
  lastEventId: number;
}

export interface AgentStoredMessage extends AgentConversationMessage {
  id: string;
  createdAt: string;
  response?: AgentChatMessage;
}

export interface AgentModelSnapshot {
  configId: string;
  provider: string;
  model: string;
}

export interface AgentTurnExecution {
  runId: string;
  turnId: string;
  status: AgentTurnExecutionStatus;
  errorCode: AgentTurnErrorCode | null;
  modelSnapshot: AgentModelSnapshot | null;
  startedAt: string;
  completedAt: string | null;
}

export interface AgentSessionResponse {
  resumeId: string;
  revision: string;
  messages: AgentStoredMessage[];
  executions: AgentTurnExecution[];
}

export interface AgentSessionReplaceRequest {
  locale: DocumentLocale;
  revision: string;
  messages: AgentConversationMessage[];
}

export type AgentDraftDecisionRequest =
  | {
      revision: string;
      status: "applied";
      reviewItemIds: string[];
      resume: ResumeData;
      expectedVersionId: string;
    }
  | {
      revision: string;
      status: "discarded";
      reviewItemIds: string[];
    };

export interface AgentDraftDecisionResponse {
  session: AgentSessionResponse;
  resume: ResumeDetailResponse | null;
}

export type AgentChatStreamEvent =
  | {
      type: "message_start";
      message: Partial<Pick<AgentChatMessage, "id" | "role" | "tone" | "text">>;
    }
  | {
      type: "text_delta";
      delta: string;
      timelinePartId: string;
    }
  | {
      type: "message_delta";
      message: Partial<Omit<AgentChatMessage, "id" | "role">>;
    }
  | {
      type: "tool_start" | "tool_delta" | "tool_done";
      tool: AgentToolInvocation;
      timelinePartId: string;
    }
  | {
      type: "edits";
      message: Partial<
        Pick<AgentChatMessage, "edits" | "transactionState">
      >;
    }
  | {
      type: "message_done";
      message: AgentChatMessage;
    }
  | {
      type: "run_done";
      runId: string;
      status: AgentRunStatus;
      executionState: AgentTurnExecutionStatus;
      errorCode: AgentTurnErrorCode | null;
    }
  | {
      type: "error";
      message?: string;
      error?: string;
    };
