import { loadMessages, locales } from "@/i18n";
import { createId } from "@/lib/resume";
import type {
  AgentChatAttachment,
  AgentChatMessage,
  AgentConversationMessage,
  AgentDraftSnapshot,
  AgentResumeEditSuggestion,
  AgentSessionResponse,
  AgentSource,
  AgentStoredMessage,
  AgentTurnExecution,
} from "@/types/api";

export interface AgentPanelMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  files?: AgentChatAttachment[];
  response?: AgentChatMessage;
  execution?: AgentTurnExecution;
}

export function getAgentDraftSnapshot(
  messages: AgentStoredMessage[],
): AgentDraftSnapshot | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const response = message.response;
    if (
      message.role !== "assistant" ||
      response?.transactionState !== "committed" ||
      !response.draft ||
      !response.edits?.length
    ) {
      continue;
    }

    return {
      baseResume: response.draft.baseResume,
      edits: response.edits,
      sourceMessageId: message.id,
      status: response.draft.status,
      transactionState: "committed",
    };
  }

  return null;
}

export function getPendingAgentDraftSnapshot(
  messages: AgentStoredMessage[],
): AgentDraftSnapshot | null {
  const draft = getAgentDraftSnapshot(messages);
  return draft?.status === "pending" ? draft : null;
}

export function toConversationMessage(
  message: AgentPanelMessage,
): AgentConversationMessage {
  return {
    files: message.files,
    id: message.id,
    response:
      message.role === "assistant" && message.response
        ? message.response
        : undefined,
    role: message.role,
    text: message.text,
  };
}

function isCitationSource(source: AgentSource) {
  if (source.sourceType === "web" && !source.url) {
    return false;
  }

  return (
    source.sourceType === "web" ||
    source.sourceType === "attachment"
  );
}

function stripTransientModelStatus(
  text: string,
  transientStatusTexts: readonly string[],
) {
  const trimmed = text.trim();

  return transientStatusTexts.some((statusText) => statusText.trim() === trimmed)
    ? ""
    : text;
}

function sanitizeAgentResponse(
  message: AgentChatMessage,
  transientStatusTexts: readonly string[],
): AgentChatMessage {
  return {
    ...message,
    text: stripTransientModelStatus(message.text, transientStatusTexts),
    sources: message.sources?.filter(isCitationSource),
  };
}

export function toAssistantPanelMessage(
  message: AgentChatMessage,
  transientStatusTexts: readonly string[],
): AgentPanelMessage {
  const response = sanitizeAgentResponse(message, transientStatusTexts);

  return {
    id: message.id,
    role: "assistant",
    text: response.text,
    response,
  };
}

function toPanelMessage(
  message: AgentStoredMessage,
  transientStatusTexts: readonly string[],
): AgentPanelMessage {
  const messageId = message.id ?? createId("agent-stored");
  const text = stripTransientModelStatus(message.text, transientStatusTexts);
  const fallbackResponse: AgentChatMessage | undefined =
    message.role === "assistant"
      ? {
          id: messageId,
          role: "assistant",
          text,
        }
      : undefined;

  return {
    files: message.files,
    id: messageId,
    role: message.role,
    text,
    response: message.response
      ? sanitizeAgentResponse(message.response, transientStatusTexts)
      : fallbackResponse,
  };
}

export function toPanelMessages(
  session: AgentSessionResponse,
  transientStatusTexts: readonly string[],
) {
  const latestExecutionByTurn = new Map<string, AgentTurnExecution>();
  for (const execution of session.executions) {
    latestExecutionByTurn.set(execution.turnId, execution);
  }

  return session.messages.map((message) => ({
    ...toPanelMessage(message, transientStatusTexts),
    execution:
      message.role === "user"
        ? latestExecutionByTurn.get(message.id)
        : undefined,
  }));
}

export async function hydrateAgentSession(
  sessionRequest: Promise<AgentSessionResponse>,
) {
  const [session, localeMessages] = await Promise.all([
    sessionRequest,
    Promise.all(locales.map(loadMessages)),
  ]);
  const transientStatusTexts = localeMessages.flatMap(
    (messages) => messages.agentTransientModelStatusTexts,
  );

  return {
    draftSnapshot: getAgentDraftSnapshot(session.messages),
    panelMessages: toPanelMessages(session, transientStatusTexts),
    session,
  };
}

export function getEditsPreviewKey(edits: AgentResumeEditSuggestion[]) {
  return JSON.stringify(
    edits.map((edit) => ({
      id: edit.id,
      operation: edit.operation,
      replacement: edit.replacement,
      status: edit.status,
      target: edit.target,
    })),
  );
}
