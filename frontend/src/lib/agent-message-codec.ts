import type {
  AgentChatActionId,
  AgentChatMessage,
  AgentFinishMissing,
  AgentResumeEditSuggestion,
  AgentSource,
  AgentTargetContext,
  AgentTimelinePart,
  AgentToolInvocation,
  AgentTransactionState,
} from "@/types/api";

const agentActionIds = new Set<AgentChatActionId>([
  "summary",
  "bullet",
  "keywords",
  "plan",
  "execute",
]);
const agentFinishMissingValues = new Set<AgentFinishMissing>([
  "pending_draft",
  "url_purpose",
  "resume_target",
  "draft_edit_target",
  "source_material",
  "target_role",
  "user_evidence",
  "explicit_delete_intent",
  "explicit_reorder_intent",
  "model_config",
]);
function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function toStringArray(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : undefined;
}

function toKnowledgeItems(value: unknown): AgentChatMessage["knowledge"] {
  if (!Array.isArray(value)) {
    return undefined;
  }

  return value
    .filter(isRecord)
    .map((item) => ({
      title: typeof item.title === "string" ? item.title : "",
      detail: typeof item.detail === "string" ? item.detail : "",
    }))
    .filter((item) => item.title || item.detail);
}

function toActionIds(value: unknown): AgentChatActionId[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const actions = value
    .map((item) => {
      if (typeof item === "string") {
        return item;
      }

      if (isRecord(item) && typeof item.id === "string") {
        return item.id;
      }

      return "";
    })
    .filter((item): item is AgentChatActionId =>
      agentActionIds.has(item as AgentChatActionId),
    );

  return actions.length > 0 ? actions : undefined;
}

function toFinishMissing(value: unknown): AgentChatMessage["finishMissing"] {
  if (!Array.isArray(value)) {
    return undefined;
  }

  const missing = value.filter(
    (item): item is AgentFinishMissing =>
      typeof item === "string" &&
      agentFinishMissingValues.has(item as AgentFinishMissing),
  );

  return missing.length > 0 ? missing : undefined;
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

function toTargetContext(value: unknown): AgentTargetContext | undefined {
  if (!isRecord(value)) {
    return undefined;
  }
  const kind = value.kind;
  if (
    kind !== "employment" &&
    kind !== "graduate_study" &&
    kind !== "research" &&
    kind !== "scholarship" &&
    kind !== "general"
  ) {
    return undefined;
  }

  return {
    cleared: value.cleared === true,
    kind,
    target: typeof value.target === "string" ? value.target : "",
    locations: toStringArray(value.locations) ?? [],
    seniority: typeof value.seniority === "string" ? value.seniority : "",
    responsibilities: toStringArray(value.responsibilities) ?? [],
    mustHaveSkills: toStringArray(value.mustHaveSkills) ?? [],
    niceToHaveSkills: toStringArray(value.niceToHaveSkills) ?? [],
    requirements: toStringArray(value.requirements) ?? [],
    description: typeof value.description === "string" ? value.description : "",
    exactJobDescription: value.exactJobDescription === true,
    sourceMessageIds: toStringArray(value.sourceMessageIds) ?? [],
  };
}

function toSourceType(value: unknown): AgentSource["sourceType"] | undefined {
  if (value === "targetContext" || value === "attachment" || value === "web") {
    return value;
  }

  return undefined;
}

function toSources(value: unknown): AgentChatMessage["sources"] {
  if (!Array.isArray(value)) {
    return undefined;
  }

  return value
    .filter(isRecord)
    .flatMap((item): AgentSource[] => {
      const sourceType = toSourceType(item.sourceType);
      const id = typeof item.id === "string" ? item.id : "";
      const title = typeof item.title === "string" ? item.title : "";

      if (!sourceType || !id || !title) {
        return [];
      }

      if (id === "source-jd-search-query") {
        return [];
      }

      if (sourceType === "web" && typeof item.url !== "string") {
        return [];
      }

      return [{
        id,
        title,
        sourceType,
        url: typeof item.url === "string" ? item.url : undefined,
        excerpt: typeof item.excerpt === "string" ? item.excerpt : undefined,
      }];
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
      errorText: typeof item.errorText === "string" ? item.errorText : undefined,
      startedAt: typeof item.startedAt === "string" ? item.startedAt : undefined,
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
    isTerminalToolState(current.state) &&
    !isTerminalToolState(incoming.state);

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
      const operation =
        isRecord(item.operation) && typeof item.operation.type === "string"
          ? (item.operation as AgentResumeEditSuggestion["operation"])
          : undefined;
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
        item.type === "text" || item.type === "tool_group"
          ? item.type
          : "text";

      return {
        id: typeof item.id === "string" ? item.id : "",
        type,
        text: typeof item.text === "string" ? item.text : undefined,
        toolIds: Array.isArray(item.toolIds)
          ? item.toolIds.filter((toolId): toolId is string =>
              typeof toolId === "string",
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
    reasoning: "",
    text: "",
    updates: [],
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

  const suggestions = toStringArray(patch.suggestions);
  const plan = toStringArray(patch.plan);
  const updates = toStringArray(patch.updates);
  const timeline = toTimelineParts(patch.timeline);
  const knowledge = toKnowledgeItems(patch.knowledge);
  const actions = toActionIds(patch.actions);
  const tools = toToolInvocations(patch.tools);
  const sources = toSources(patch.sources);
  const edits = toEditSuggestions(patch.edits);
  const finishMissing = toFinishMissing(patch.finishMissing);
  const transactionState = toTransactionState(patch.transactionState);
  const quickReplies = toStringArray(patch.quickReplies);
  const targetContext = toTargetContext(patch.targetContext);

  return {
    ...current,
    id: typeof patch.id === "string" ? patch.id : current.id,
    role: "assistant",
    reasoning:
      typeof patch.reasoning === "string" ? patch.reasoning : current.reasoning,
    tone:
      patch.tone === "default" || patch.tone === "success"
        ? patch.tone
        : current.tone,
    text: typeof patch.text === "string" ? patch.text : current.text,
    updates: updates ?? current.updates,
    timeline: timeline ?? current.timeline,
    plan: plan ?? current.plan,
    suggestions: suggestions ?? current.suggestions,
    knowledge: knowledge ?? current.knowledge,
    tools:
      tools === undefined
        ? current.tools
        : mergeAgentToolInvocations(current.tools, tools),
    sources: sources ?? current.sources,
    edits: edits ?? current.edits,
    targetContext: targetContext ?? current.targetContext,
    transactionState: transactionState ?? current.transactionState,
    finishMissing: finishMissing ?? current.finishMissing,
    quickReplies: quickReplies ?? current.quickReplies,
    actions: actions ?? current.actions,
  };
}

function getPayloadPatch(payload: unknown, key: string) {
  if (!isRecord(payload)) {
    return payload;
  }

  return payload[key] ?? payload;
}

export function applyAgentToolStreamEvent(
  message: AgentChatMessage,
  payload: unknown,
) {
  const tools = toToolInvocations([getPayloadPatch(payload, "tool")]);
  if (!tools?.length) {
    return message;
  }

  return {
    ...message,
    tools: mergeAgentToolInvocations(message.tools, tools),
  };
}
