import type {
  AgentChatMessage,
  AgentResumeEditSuggestion,
  AgentSource,
  AgentTimelinePart,
  AgentToolInvocation,
  AgentTransactionState,
} from "@/types/api";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function toTransactionState(value: unknown): AgentTransactionState | undefined {
  if (
    value === "none" ||
    value === "provisional" ||
    value === "committed" ||
    value === "rolled_back"
  ) {
    return value;
  }

  return undefined;
}

function toSourceType(value: unknown): AgentSource["sourceType"] | undefined {
  if (value === "attachment" || value === "web") {
    return value;
  }

  return undefined;
}

function toSources(value: unknown): AgentChatMessage["sources"] {
  if (!Array.isArray(value)) {
    return undefined;
  }

  return value.filter(isRecord).flatMap((item): AgentSource[] => {
    const sourceType = toSourceType(item.sourceType);
    const id = typeof item.id === "string" ? item.id : "";
    const title = typeof item.title === "string" ? item.title : "";

    if (!sourceType || !id || !title) {
      return [];
    }

    if (sourceType === "web" && typeof item.url !== "string") {
      return [];
    }

    return [
      {
        id,
        title,
        sourceType,
        url: typeof item.url === "string" ? item.url : undefined,
        excerpt: typeof item.excerpt === "string" ? item.excerpt : undefined,
      },
    ];
  });
}

function toToolState(value: unknown): AgentToolInvocation["state"] {
  if (
    value === "input-streaming" ||
    value === "input-available" ||
    value === "output-available" ||
    value === "output-error" ||
    value === "approval-requested" ||
    value === "approval-responded" ||
    value === "output-denied"
  ) {
    return value;
  }

  return "output-available";
}

function toToolInvocations(value: unknown): AgentChatMessage["tools"] {
  if (!Array.isArray(value)) {
    return undefined;
  }

  return value
    .filter(isRecord)
    .map((item) => ({
      id: typeof item.id === "string" ? item.id : "",
      type: typeof item.type === "string" ? item.type : "",
      title: typeof item.title === "string" ? item.title : "",
      state: toToolState(item.state),
      input: item.input,
      output: item.output,
      errorText:
        typeof item.errorText === "string" ? item.errorText : undefined,
      startedAt:
        typeof item.startedAt === "string" ? item.startedAt : undefined,
      completedAt:
        typeof item.completedAt === "string" ? item.completedAt : undefined,
    }))
    .filter((item) => item.id && item.type && item.title);
}

function isTerminalToolState(state: AgentToolInvocation["state"]) {
  return (
    state === "output-available" ||
    state === "output-error" ||
    state === "output-denied"
  );
}

function mergeAgentToolInvocation(
  current: AgentToolInvocation,
  incoming: AgentToolInvocation,
): AgentToolInvocation {
  const preserveTerminalState =
    isTerminalToolState(current.state) && !isTerminalToolState(incoming.state);

  return {
    ...current,
    ...incoming,
    state: preserveTerminalState ? current.state : incoming.state,
    input: incoming.input === undefined ? current.input : incoming.input,
    output: incoming.output === undefined ? current.output : incoming.output,
    errorText:
      incoming.errorText === undefined ? current.errorText : incoming.errorText,
    startedAt:
      incoming.startedAt === undefined ? current.startedAt : incoming.startedAt,
    completedAt:
      incoming.completedAt === undefined
        ? current.completedAt
        : incoming.completedAt,
  };
}

/**
 * Reconcile incremental tool events and full message snapshots by invocation id.
 * First-seen order is stable, duplicate events update in place, and a late
 * non-terminal snapshot cannot regress a completed invocation.
 */
export function mergeAgentToolInvocations(
  current: AgentToolInvocation[] = [],
  incoming: AgentToolInvocation[] = [],
) {
  const toolsById = new Map<string, AgentToolInvocation>();
  const orderedIds: string[] = [];

  for (const tool of current) {
    if (!toolsById.has(tool.id)) {
      orderedIds.push(tool.id);
      toolsById.set(tool.id, tool);
    } else {
      toolsById.set(
        tool.id,
        mergeAgentToolInvocation(toolsById.get(tool.id)!, tool),
      );
    }
  }

  for (const tool of incoming) {
    const existing = toolsById.get(tool.id);
    if (!existing) {
      orderedIds.push(tool.id);
      toolsById.set(tool.id, tool);
      continue;
    }

    toolsById.set(tool.id, mergeAgentToolInvocation(existing, tool));
  }

  return orderedIds.map((id) => toolsById.get(id)!);
}

function toEditSuggestions(value: unknown): AgentChatMessage["edits"] {
  if (!Array.isArray(value)) {
    return undefined;
  }

  return value
    .filter(isRecord)
    .map((item): AgentResumeEditSuggestion => {
      if (
        !isRecord(item.operation) ||
        typeof item.operation.type !== "string"
      ) {
        throw new TypeError("Agent edit requires an explicit operation.");
      }
      const operation =
        item.operation as AgentResumeEditSuggestion["operation"];
      const diffs = Array.isArray(item.diffs)
        ? (item.diffs as AgentResumeEditSuggestion["diffs"])
        : undefined;
      const evidenceRefs = Array.isArray(item.evidenceRefs)
        ? item.evidenceRefs.filter(
            (reference): reference is string =>
              typeof reference === "string" && reference.length > 0,
          )
        : undefined;

      return {
        id: typeof item.id === "string" ? item.id : "",
        title: typeof item.title === "string" ? item.title : "",
        target: typeof item.target === "string" ? item.target : "",
        reason: typeof item.reason === "string" ? item.reason : "",
        replacement:
          typeof item.replacement === "string" ? item.replacement : undefined,
        operation,
        evidenceRefs,
        status:
          item.status === "planned" ||
          item.status === "executed" ||
          item.status === "rejected"
            ? item.status
            : undefined,
        diffs,
      };
    })
    .filter((item) => item.id && item.title && item.target);
}

function toTimelineParts(value: unknown): AgentChatMessage["timeline"] {
  if (!Array.isArray(value)) {
    return undefined;
  }

  return value
    .filter(isRecord)
    .map((item): AgentTimelinePart => {
      const type: AgentTimelinePart["type"] =
        item.type === "text" || item.type === "tool_group" ? item.type : "text";

      return {
        id: typeof item.id === "string" ? item.id : "",
        type,
        text: typeof item.text === "string" ? item.text : undefined,
        toolIds: Array.isArray(item.toolIds)
          ? item.toolIds.filter(
              (toolId): toolId is string => typeof toolId === "string",
            )
          : undefined,
      };
    })
    .filter((item) => item.id);
}

export function createEmptyAssistantMessage(): AgentChatMessage {
  return {
    id: `agent-stream-${Date.now()}`,
    role: "assistant",
    text: "",
    timeline: [],
  };
}

export function mergeAgentMessage(
  current: AgentChatMessage,
  patch: unknown,
): AgentChatMessage {
  if (!isRecord(patch)) {
    return current;
  }

  const timeline = toTimelineParts(patch.timeline);
  const tools = toToolInvocations(patch.tools);
  const sources = toSources(patch.sources);
  const edits = toEditSuggestions(patch.edits);
  const transactionState = toTransactionState(patch.transactionState);

  return {
    ...current,
    id: typeof patch.id === "string" ? patch.id : current.id,
    role: "assistant",
    tone:
      patch.tone === "default" || patch.tone === "success"
        ? patch.tone
        : current.tone,
    text: typeof patch.text === "string" ? patch.text : current.text,
    timeline: timeline ?? current.timeline,
    tools:
      tools === undefined
        ? current.tools
        : mergeAgentToolInvocations(current.tools, tools),
    sources: sources ?? current.sources,
    edits: edits ?? current.edits,
    transactionState: transactionState ?? current.transactionState,
  };
}

function getPayloadPatch(payload: unknown, key: string) {
  if (!isRecord(payload)) {
    return payload;
  }

  return payload[key] ?? payload;
}

function getTimelinePartId(payload: unknown) {
  return isRecord(payload) && typeof payload.timelinePartId === "string"
    ? payload.timelinePartId
    : "";
}

function appendTimelineText(
  timeline: AgentTimelinePart[] = [],
  partId: string,
  delta: string,
) {
  const last = timeline.at(-1);
  if (last?.id === partId && last.type === "text") {
    return [
      ...timeline.slice(0, -1),
      { ...last, text: `${last.text ?? ""}${delta}` },
    ];
  }

  return [...timeline, { id: partId, type: "text" as const, text: delta }];
}

function appendTimelineTool(
  timeline: AgentTimelinePart[] = [],
  partId: string,
  toolId: string,
) {
  const last = timeline.at(-1);
  if (last?.id === partId && last.type === "tool_group") {
    if (last.toolIds?.includes(toolId)) {
      return timeline;
    }
    return [
      ...timeline.slice(0, -1),
      { ...last, toolIds: [...(last.toolIds ?? []), toolId] },
    ];
  }

  return [
    ...timeline,
    { id: partId, type: "tool_group" as const, toolIds: [toolId] },
  ];
}

export function applyAgentTextStreamEvent(
  message: AgentChatMessage,
  payload: unknown,
) {
  if (!isRecord(payload) || typeof payload.delta !== "string") {
    return message;
  }

  const partId = getTimelinePartId(payload);
  return {
    ...message,
    text: `${message.text}${payload.delta}`,
    timeline: partId
      ? appendTimelineText(message.timeline, partId, payload.delta)
      : message.timeline,
  };
}

export function applyAgentToolStreamEvent(
  message: AgentChatMessage,
  payload: unknown,
) {
  const tools = toToolInvocations([getPayloadPatch(payload, "tool")]);
  if (!tools?.length) {
    return message;
  }

  const partId = getTimelinePartId(payload);
  return {
    ...message,
    tools: mergeAgentToolInvocations(message.tools, tools),
    timeline: partId
      ? appendTimelineTool(message.timeline, partId, tools[0].id)
      : message.timeline,
  };
}
