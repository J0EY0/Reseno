import type {
  AgentChatMessage,
  AgentDraftState,
  AgentToolInvocation,
} from "@/types/api";

/**
 * Keep the in-flight assistant message visible without duplicating the final
 * persisted message during the short handoff between stream completion and
 * cleanup.
 */
export function mergeStreamingAgentMessage<T extends { id: string }>(
  messages: T[],
  streamingMessage: T | null,
) {
  if (!streamingMessage) {
    return messages;
  }

  const existingIndex = messages.findIndex(
    (message) => message.id === streamingMessage.id,
  );
  if (existingIndex < 0) {
    return [...messages, streamingMessage];
  }

  return messages.map((message, index) =>
    index === existingIndex ? streamingMessage : message,
  );
}

export function shouldShowAgentDraftActions({
  draft,
  isResponding,
  messageId,
  response,
}: {
  draft: AgentDraftState | null;
  isResponding: boolean;
  messageId: string;
  response: AgentChatMessage | undefined;
}) {
  return Boolean(
    !isResponding &&
      draft?.status === "pending" &&
      draft.transactionState === "committed" &&
      draft.sourceMessageId === messageId &&
      response?.transactionState === "committed" &&
      response.edits?.length,
  );
}

export function shouldRollbackOptimisticAgentMessages({
  replaceSessionBeforeSend,
  runAccepted,
}: {
  replaceSessionBeforeSend: boolean;
  runAccepted: boolean;
}) {
  // Keep ordinary prompts visible after transport/provider failures so users
  // can retry them. Only an edited-history replacement that never reached
  // persistence can safely restore the exact previous conversation.
  return replaceSessionBeforeSend && !runAccepted;
}

export function getAgentQualityWarningCount(tools: AgentToolInvocation[]) {
  return tools.reduce((total, tool) => {
    if (
      tool.state !== "output-available" ||
      !tool.output ||
      typeof tool.output !== "object"
    ) {
      return total;
    }

    const count = (tool.output as Record<string, unknown>).qualityIssueCount;
    return total + (typeof count === "number" && count > 0 ? count : 0);
  }, 0);
}
