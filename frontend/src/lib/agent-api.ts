import {
  apiRoutes,
  clearApiCache,
  fetchApiResource,
  getApiErrorStatus,
  requestApi,
  resolveApiUrl,
  uploadApi,
} from "@/lib/api-client";
import type {
  AgentChatAttachment,
  AgentChatActionId,
  AgentFinishMissing,
  AgentChatMessage,
  AgentChatRequest,
  AgentChatResponse,
  AgentResumeEditSuggestion,
  AgentRunResponse,
  AgentRunStatus,
  AgentSessionReplaceRequest,
  AgentSessionResponse,
  AgentSource,
  AgentTimelinePart,
  AgentToolInvocation,
  AgentTransactionState,
} from "@/types/api";

export interface AgentChatStreamOptions {
  onMessage?: (message: AgentChatMessage) => void;
  onRun?: (run: AgentRunResponse) => void;
  signal?: AbortSignal;
}

interface AgentStreamAccumulator {
  lastEventId: number;
  message: AgentChatMessage;
  messageDone: boolean;
  receivedEvent: boolean;
  status: AgentRunStatus;
}

class AgentRunStreamHttpError extends Error {}

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

function toRunStatus(value: unknown): AgentRunStatus | undefined {
  if (
    value === "active" ||
    value === "completed" ||
    value === "cancelled" ||
    value === "failed"
  ) {
    return value;
  }

  return undefined;
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
  const transactionState = toTransactionState(patch.transactionState);
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
    tools:
      tools === undefined
        ? current.tools
        : mergeAgentToolInvocations(current.tools, tools),
    sources: sources ?? current.sources,
    edits: edits ?? current.edits,
    transactionState: transactionState ?? current.transactionState,
    finishMissing: finishMissing ?? current.finishMissing,
    quickReplies: quickReplies ?? current.quickReplies,
    actions: actions ?? current.actions,
  };
}

function parseServerSentEventBlock(block: string) {
  let eventName = "message";
  let eventId: number | undefined;
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

    if (line.startsWith("id:")) {
      const parsed = Number.parseInt(line.slice("id:".length).trim(), 10);
      eventId = Number.isFinite(parsed) ? parsed : eventId;
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

  return { eventId, payload, type };
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

function yieldToRenderer() {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, 0);
  });
}

async function readAgentChatStream(
  response: Response,
  options: AgentChatStreamOptions,
  accumulator: AgentStreamAccumulator,
) {
  if (!response.body) {
    throw new Error("Agent stream response has no body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const publishMessage = () => {
    options.onMessage?.(accumulator.message);
  };

  const applyEvent = (type: string, payload: unknown) => {
    if (type === "message_start") {
      accumulator.message = mergeAgentMessage(
        accumulator.message,
        getPayloadPatch(payload, "message"),
      );
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
        accumulator.message = {
          ...accumulator.message,
          text: `${accumulator.message.text}${delta}`,
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
        accumulator.message = {
          ...accumulator.message,
          reasoning: `${accumulator.message.reasoning ?? ""}${delta}`,
        };
        publishMessage();
      }
      return;
    }

    if (
      type === "tool_start" ||
      type === "tool_delta" ||
      type === "tool_done"
    ) {
      accumulator.message = applyAgentToolStreamEvent(
        accumulator.message,
        payload,
      );
      publishMessage();
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
      accumulator.message = mergeAgentMessage(
        accumulator.message,
        getPayloadPatch(payload, "message"),
      );
      publishMessage();
      return;
    }

    if (type === "message_done") {
      accumulator.message = mergeAgentMessage(
        accumulator.message,
        getPayloadPatch(payload, "message"),
      );
      accumulator.messageDone = true;
      options.onMessage?.(accumulator.message);
      return;
    }

    if (type === "run_done") {
      const status = isRecord(payload) ? toRunStatus(payload.status) : undefined;
      if (status) {
        accumulator.status = status;
      }
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
        accumulator.message = {
          ...accumulator.message,
          text: accumulator.message.text || errorMessage,
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

      accumulator.receivedEvent = true;
      if (event.eventId !== undefined) {
        accumulator.lastEventId = Math.max(
          accumulator.lastEventId,
          event.eventId,
        );
      }
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

  return accumulator;
}

function createStreamAccumulator(
  status: AgentRunStatus = "active",
): AgentStreamAccumulator {
  return {
    lastEventId: 0,
    message: createEmptyAssistantMessage(),
    messageDone: false,
    receivedEvent: false,
    status,
  };
}

function throwIfAborted(signal: AbortSignal | undefined) {
  if (signal?.aborted) {
    throw new DOMException("Agent stream subscription aborted.", "AbortError");
  }
}

function waitBeforeReconnect(signal: AbortSignal | undefined, delayMs: number) {
  return new Promise<void>((resolve, reject) => {
    throwIfAborted(signal);

    function handleAbort() {
      window.clearTimeout(timeoutId);
      reject(new DOMException("Agent stream subscription aborted.", "AbortError"));
    }

    const timeoutId = window.setTimeout(() => {
      signal?.removeEventListener("abort", handleAbort);
      resolve();
    }, delayMs);

    signal?.addEventListener("abort", handleAbort, { once: true });
  });
}

function assertEventStreamResponse(response: Response, route: string) {
  if (!response.ok) {
    throw new AgentRunStreamHttpError(
      `API request failed: ${route} (${response.status})`,
    );
  }

  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    throw new AgentRunStreamHttpError(
      "Agent chat endpoint did not return an event stream.",
    );
  }
}

async function fetchAgentRunEvents(
  runId: string,
  after: number,
  signal: AbortSignal | undefined,
) {
  const route = apiRoutes.agentRunEvents(runId);
  const response = await fetchApiResource(
    resolveApiUrl(route, { searchParams: { after } }),
    {
      cache: "no-store",
      headers: { Accept: "text/event-stream" },
      method: "GET",
      signal,
    },
  );
  assertEventStreamResponse(response, route);
  return response;
}

async function consumeAgentRun(
  run: AgentRunResponse,
  options: AgentChatStreamOptions,
  initialResponse?: Response,
) {
  const accumulator = createStreamAccumulator(run.status);
  let response = initialResponse;
  let reconnectDelayMs = 250;
  let reconnectAttempts = 0;
  const maxReconnectAttempts = 5;

  options.onRun?.(run);

  while (accumulator.status === "active") {
    throwIfAborted(options.signal);

    try {
      response ??= await fetchAgentRunEvents(
        run.id,
        accumulator.lastEventId,
        options.signal,
      );
      await readAgentChatStream(response, options, accumulator);
      reconnectDelayMs = 250;
      reconnectAttempts = 0;
      response = undefined;
    } catch (error) {
      throwIfAborted(options.signal);
      if (
        error instanceof AgentRunStreamHttpError ||
        getApiErrorStatus(error) !== undefined ||
        error instanceof SyntaxError
      ) {
        throw error;
      }

      // A subscriber can disappear while the process-local Agent run keeps
      // working. Retry bounded transport interruptions from the last
      // acknowledged SSE id, but never loop forever on a broken connection.
      reconnectAttempts += 1;
      if (reconnectAttempts > maxReconnectAttempts) {
        throw error;
      }
      await waitBeforeReconnect(options.signal, reconnectDelayMs);
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, 2000);
      response = undefined;
    }
  }

  if (!accumulator.receivedEvent) {
    throw new Error("Agent stream completed without events.");
  }

  const completedRun: AgentRunResponse = {
    ...run,
    lastEventId: accumulator.lastEventId,
    status: accumulator.status,
  };
  options.onRun?.(completedRun);

  return {
    lastEventId: accumulator.lastEventId,
    message: accumulator.message,
    messageDone: accumulator.messageDone,
    runId: run.id,
    status: accumulator.status,
  } satisfies AgentChatResponse;
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

  assertEventStreamResponse(response, apiRoutes.agentChat);
  const runId = response.headers.get("X-Agent-Run-Id")?.trim();
  if (!runId) {
    throw new Error("Agent chat endpoint did not return a run id.");
  }

  const result = await consumeAgentRun(
    {
      baseResume: request.resume,
      id: runId,
      lastEventId: 0,
      resumeId: request.resumeId,
      status: "active",
    },
    options,
    response,
  );
  if (request.resumeId) {
    clearApiCache(apiRoutes.agentResumeSession(request.resumeId));
  }

  return result;
}

export async function connectAgentRun(
  run: AgentRunResponse,
  options: AgentChatStreamOptions = {},
) {
  // Reconnecting clients replay from the beginning of the short in-memory
  // buffer so the partial assistant message can be rebuilt deterministically.
  return consumeAgentRun({ ...run, lastEventId: 0, status: "active" }, options);
}

export function loadActiveAgentRun(resumeId: string) {
  return requestApi<AgentRunResponse | null>(apiRoutes.agentResumeRun(resumeId));
}

export function stopAgentRun(runId: string) {
  return requestApi<AgentRunResponse>(apiRoutes.agentRun(runId), {
    method: "DELETE",
  });
}

export function uploadAgentAttachment(
  file: FormData,
  resumeId: string,
  options: {
    onProgress?: (progress: { loaded: number; total?: number }) => void;
    signal?: AbortSignal;
  } = {},
) {
  file.set("resumeId", resumeId);
  return uploadApi<AgentChatAttachment>(apiRoutes.agentAttachments, file, {
    onProgress: options.onProgress,
    signal: options.signal,
  });
}

export function downloadAgentAttachment(
  resumeId: string,
  attachmentId: string,
) {
  return fetchApiResource(
    resolveApiUrl(apiRoutes.agentAttachment(resumeId, attachmentId)),
    {
      cache: "no-store",
    },
  );
}

export function deletePendingAgentAttachment(
  resumeId: string,
  attachmentId: string,
) {
  return requestApi<{ id: string }>(
    apiRoutes.agentAttachment(resumeId, attachmentId),
    {
      method: "DELETE",
    },
  );
}

export async function loadAgentSession(resumeId: string) {
  return requestApi<AgentSessionResponse>(apiRoutes.agentResumeSession(resumeId), {
    // Session revisions are optimistic-concurrency tokens. Reusing even a
    // short-lived GET cache can make an otherwise valid history edit stale.
    cacheTtlMs: 0,
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
