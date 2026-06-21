import {
  apiRoutes,
  clearApiCache,
  fetchApiResource,
  requestApi,
  resolveApiUrl,
} from "@/lib/api-client";
import type {
  AgentChatActionId,
  AgentFinishMissing,
  AgentChatMessage,
  AgentChatRequest,
  AgentChatResponse,
  AgentResumeEditSuggestion,
  AgentSessionReplaceRequest,
  AgentSessionResponse,
  AgentSource,
  AgentTimelinePart,
  AgentToolInvocation,
} from "@/types/api";

interface AgentChatStreamOptions {
  onMessage?: (message: AgentChatMessage) => void;
  signal?: AbortSignal;
}

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

function toSourceType(value: unknown): AgentSource["sourceType"] | undefined {
  if (value === "jobBrief" || value === "attachment" || value === "web") {
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

      return {
        id: typeof item.id === "string" ? item.id : "",
        title: typeof item.title === "string" ? item.title : "",
        target: typeof item.target === "string" ? item.target : "",
        reason: typeof item.reason === "string" ? item.reason : "",
        replacement:
          typeof item.replacement === "string" ? item.replacement : undefined,
        operation,
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

function createEmptyAssistantMessage(): AgentChatMessage {
  return {
    id: `agent-stream-${Date.now()}`,
    role: "assistant",
    reasoning: "",
    text: "",
    updates: [],
    timeline: [],
  };
}

function mergeAgentMessage(
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
  const quickReplies = toStringArray(patch.quickReplies);

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
    tools: tools ?? current.tools,
    sources: sources ?? current.sources,
    edits: edits ?? current.edits,
    finishMissing: finishMissing ?? current.finishMissing,
    quickReplies: quickReplies ?? current.quickReplies,
    actions: actions ?? current.actions,
  };
}

function parseServerSentEventBlock(block: string) {
  let eventName = "message";
  const dataLines: string[] = [];

  block.split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trimEnd();

    if (!line || line.startsWith(":")) {
      return;
    }

    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
      return;
    }

    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  });

  const data = dataLines.join("\n").trim();

  if (!data || data === "[DONE]") {
    return null;
  }

  const payload = JSON.parse(data) as unknown;
  const type =
    isRecord(payload) && typeof payload.type === "string"
      ? payload.type
      : eventName;

  return { payload, type };
}

function getPayloadPatch(payload: unknown, key: string) {
  if (!isRecord(payload)) {
    return payload;
  }

  return payload[key] ?? payload;
}

function yieldToRenderer() {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, 0);
  });
}

async function readAgentChatStream(
  response: Response,
  options: AgentChatStreamOptions,
) {
  if (!response.body) {
    throw new Error("Agent stream response has no body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let message = createEmptyAssistantMessage();
  let receivedEvent = false;

  const publishMessage = () => {
    options.onMessage?.(message);
  };

  const applyEvent = (type: string, payload: unknown) => {
    if (type === "message_start") {
      message = mergeAgentMessage(message, getPayloadPatch(payload, "message"));
      publishMessage();
      return;
    }

    if (type === "text_delta") {
      const delta = isRecord(payload)
        ? typeof payload.delta === "string"
          ? payload.delta
          : typeof payload.text === "string"
            ? payload.text
            : ""
        : "";

      if (delta) {
        message = {
          ...message,
          text: `${message.text}${delta}`,
        };
        publishMessage();
      }
      return;
    }

    if (type === "reasoning_delta") {
      const delta = isRecord(payload)
        ? typeof payload.delta === "string"
          ? payload.delta
          : ""
        : "";

      if (delta) {
        message = {
          ...message,
          reasoning: `${message.reasoning ?? ""}${delta}`,
        };
        publishMessage();
      }
      return;
    }

    if (
      type === "message_delta" ||
      type === "plan" ||
      type === "updates" ||
      type === "timeline" ||
      type === "suggestions" ||
      type === "knowledge" ||
      type === "tools" ||
      type === "sources" ||
      type === "edits" ||
      type === "quickReplies" ||
      type === "actions"
    ) {
      message = mergeAgentMessage(message, getPayloadPatch(payload, "message"));
      publishMessage();
      return;
    }

    if (type === "message_done") {
      message = mergeAgentMessage(message, getPayloadPatch(payload, "message"));
      options.onMessage?.(message);
      return;
    }

    if (type === "error") {
      const errorMessage =
        isRecord(payload) && typeof payload.message === "string"
          ? payload.message
          : isRecord(payload) && typeof payload.error === "string"
            ? payload.error
            : "";

      if (errorMessage) {
        message = {
          ...message,
          text: message.text || errorMessage,
        };
        publishMessage();
      }
      return;
    }
  };

  const flushBlocks = async (blocks: string[]) => {
    for (const [index, block] of blocks.entries()) {
      const event = parseServerSentEventBlock(block);

      if (!event) {
        continue;
      }

      receivedEvent = true;
      applyEvent(event.type, event.payload);

      if (index < blocks.length - 1) {
        await yieldToRenderer();
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    await flushBlocks(blocks);
  }

  buffer += decoder.decode();

  if (buffer.trim()) {
    await flushBlocks([buffer]);
  }

  if (!receivedEvent) {
    throw new Error("Agent stream completed without events.");
  }

  return message;
}

export async function sendAgentChatMessage(
  request: AgentChatRequest,
  options: AgentChatStreamOptions = {},
) {
  const response = await fetchApiResource(
    resolveApiUrl(apiRoutes.agentChat),
    {
      body: JSON.stringify({ ...request, stream: true }),
      cache: "no-store",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      method: "POST",
      signal: options.signal,
    },
  );

  if (!response.ok) {
    throw new Error(
      `API request failed: ${apiRoutes.agentChat} (${response.status})`,
    );
  }

  const contentType = response.headers.get("Content-Type") ?? "";

  if (!contentType.toLowerCase().includes("text/event-stream")) {
    throw new Error("Agent chat endpoint did not return an event stream.");
  }

  const message = await readAgentChatStream(response, options);
  if (request.resumeId) {
    clearApiCache(apiRoutes.agentResumeSession(request.resumeId));
  }

  return { message } satisfies AgentChatResponse;
}

export async function loadAgentSession(resumeId: string) {
  return requestApi<AgentSessionResponse>(apiRoutes.agentResumeSession(resumeId), {
    cacheTtlMs: 2000,
  });
}

export async function replaceAgentSession(
  resumeId: string,
  request: AgentSessionReplaceRequest,
) {
  return requestApi<AgentSessionResponse>(apiRoutes.agentResumeSession(resumeId), {
    body: request,
    method: "PUT",
  });
}
