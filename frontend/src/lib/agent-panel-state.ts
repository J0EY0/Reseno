import type {
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

export function shouldRollbackOptimisticAgentMessages({
  runAccepted,
}: {
  replaceSessionBeforeSend: boolean;
  runAccepted: boolean;
}) {
  // Once the backend accepts a run, its user turn is authoritative and will
  // reappear during reconciliation. Before acceptance, the optimistic row has
  // no durable counterpart and must be removed for every send mode.
  return !runAccepted;
}

/**
 * One submit gate is shared by the textarea, attachments, and send button so
 * a partial session bootstrap cannot be bypassed by another composer control.
 */
export function canSubmitAgentPrompt({
  hasConfiguredModel,
  isRequestBusy,
  isSessionReady,
  isSubmitting,
}: {
  hasConfiguredModel: boolean;
  isRequestBusy: boolean;
  isSessionReady: boolean;
  isSubmitting: boolean;
}) {
  return (
    hasConfiguredModel &&
    isSessionReady &&
    !isRequestBusy &&
    !isSubmitting
  );
}

export interface AgentQualityWarning {
  code: string;
  target: string;
}

export function getAgentQualityWarnings(tools: AgentToolInvocation[]) {
  const warnings: AgentQualityWarning[] = [];
  const seen = new Set<string>();

  for (const tool of tools) {
    if (
      tool.state !== "output-available" ||
      !tool.output ||
      typeof tool.output !== "object"
    ) {
      continue;
    }

    const issues = (tool.output as Record<string, unknown>).qualityIssues;
    if (!Array.isArray(issues)) {
      continue;
    }
    for (const issue of issues) {
      if (!issue || typeof issue !== "object") {
        continue;
      }
      const value = issue as Record<string, unknown>;
      if (value.severity !== "warning" || typeof value.code !== "string") {
        continue;
      }
      const target = typeof value.target === "string" ? value.target : "";
      const key = `${value.code}\0${target}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      warnings.push({ code: value.code, target });
    }
  }

  return warnings;
}
