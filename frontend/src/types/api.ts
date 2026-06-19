import type { Locale } from "@/i18n";
import type {
  AgentSettings,
  KeywordMatch,
  ModelConfig,
  ResumeData,
  ResumeDraftDiff,
  ResumeEditOperation,
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
  WorkspacePayload,
  WorkspaceSnapshot,
  WorkspaceVersionSnapshot,
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
  searchParams?: Record<string, string | number | boolean | null | undefined>;
}

export interface WorkspaceBootstrapQuery {
  locale: Locale;
}

export type WorkspaceBootstrapResponse = WorkspacePayload;

export interface WorkspaceBootstrapResult {
  workspace: WorkspacePayload;
  savedAt: string | null;
  source: "backend";
}

export interface WorkspaceSaveRequest {
  snapshot: WorkspaceSnapshot;
}

export interface WorkspaceSaveResponse {
  savedAt: string;
  versionId?: string;
}

export interface WorkspaceResumeIdResponse {
  id: string;
}

export interface WorkspaceVersionSummary {
  versionId: string;
  savedAt: string;
}

export interface WorkspaceVersionsResponse {
  versions: WorkspaceVersionSummary[];
}

export interface WorkspaceVersionResponse {
  versionId: string;
  snapshot: WorkspaceVersionSnapshot;
}

export interface ImportResumeResponse {
  resumes: ResumeWorkspaceItem[];
}

export interface ImportTemplatesResponse {
  templates: ResumeTemplateDefinition[];
}

export interface ExportResumePdfRequest {
  resumeId: string;
  locale: Locale;
  fileNameSeed: string;
  savedAt: string;
  versionId?: string;
  renderBaseUrl?: string;
}

export interface ExportResumePdfResponse {
  exportId: string;
  downloadUrl: string;
  fileName: string;
  expiresAt?: string;
}

export interface AgentChatAttachment {
  id?: string;
  filename?: string;
  mediaType?: string;
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

export type AgentDraftStatus = "pending" | "applied" | "discarded";

export interface AgentDraftState {
  id: string;
  status: AgentDraftStatus;
  sourceMessageId?: string;
  createdAt?: string;
  updatedAt?: string;
  resume: ResumeData;
  editCount: number;
  edits: AgentResumeEditSuggestion[];
  diffs: ResumeDraftDiff[];
}

export interface AgentChatRequest {
  resumeId?: string;
  prompt: string;
  message?: AgentConversationMessage;
  messages?: AgentConversationMessage[];
  conversation: AgentConversationMessage[];
  files: AgentChatAttachment[];
  locale: Locale;
  resume: ResumeData;
  jobBrief: string;
  keywordMatch: KeywordMatch;
  appliedActions: string[];
  draftState?: AgentDraftState | null;
  modelConfig: ModelConfig | null;
  settings: AgentSettings;
  stream?: boolean;
}

export type AgentChatActionId =
  | "summary"
  | "bullet"
  | "keywords"
  | "plan"
  | "execute";

export interface AgentSource {
  id: string;
  title: string;
  sourceType: "jobBrief" | "attachment" | "web";
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
  reasoning?: string;
  updates?: string[];
  timeline?: AgentTimelinePart[];
  plan?: string[];
  suggestions?: string[];
  knowledge?: Array<{
    title: string;
    detail: string;
  }>;
  tools?: AgentToolInvocation[];
  sources?: AgentSource[];
  edits?: AgentResumeEditSuggestion[];
  quickReplies?: string[];
  actions?: AgentChatActionId[];
}

export interface AgentChatResponse {
  message: AgentChatMessage;
}

export interface AgentStoredMessage extends AgentConversationMessage {
  id: string;
  createdAt: string;
  response?: AgentChatMessage;
}

export interface AgentSessionResponse {
  resumeId: string;
  messages: AgentStoredMessage[];
}

export type AgentChatStreamEvent =
  | {
      type: "message_start";
      message: Partial<Pick<AgentChatMessage, "id" | "role" | "tone" | "text">>;
    }
  | {
      type: "text_delta";
      delta: string;
    }
  | {
      type: "reasoning_delta";
      delta: string;
    }
  | {
      type: "message_delta";
      message: Partial<Omit<AgentChatMessage, "id" | "role">>;
    }
  | {
      type: "plan";
      message: Partial<Pick<AgentChatMessage, "plan">>;
    }
  | {
      type: "updates";
      message: Partial<Pick<AgentChatMessage, "updates">>;
    }
  | {
      type: "timeline";
      message: Partial<Pick<AgentChatMessage, "text" | "timeline">>;
    }
  | {
      type: "suggestions";
      message: Partial<Pick<AgentChatMessage, "suggestions">>;
    }
  | {
      type: "knowledge";
      message: Partial<Pick<AgentChatMessage, "knowledge">>;
    }
  | {
      type: "tools";
      message: Partial<Pick<AgentChatMessage, "text" | "tools" | "timeline">>;
    }
  | {
      type: "sources";
      message: Partial<Pick<AgentChatMessage, "sources">>;
    }
  | {
      type: "edits";
      message: Partial<Pick<AgentChatMessage, "edits">>;
    }
  | {
      type: "quickReplies";
      message: Partial<Pick<AgentChatMessage, "quickReplies">>;
    }
  | {
      type: "actions";
      message: Partial<Pick<AgentChatMessage, "actions">>;
    }
  | {
      type: "message_done";
      message: AgentChatMessage;
    }
  | {
      type: "error";
      message: string;
    };
