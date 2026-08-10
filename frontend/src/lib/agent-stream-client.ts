import {
  apiRoutes,
  clearApiCache,
  fetchApiResource,
  getApiErrorStatus,
  resolveApiUrl,
} from "@/lib/api-client";
import {
  applyAgentToolStreamEvent,
  createEmptyAssistantMessage,
  mergeAgentMessage,
} from "@/lib/agent-message-codec";
import type {
  AgentChatMessage,
  AgentChatRequest,
  AgentChatResponse,
  AgentRunResponse,
  AgentRunStatus,
  AgentTurnErrorCode,
  AgentTurnExecutionStatus,
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
  executionState: AgentTurnExecutionStatus;
  errorCode: AgentTurnErrorCode | null;
}

class AgentRunStreamHttpError extends Error {}

const agentTurnExecutionStatuses = new Set<AgentTurnExecutionStatus>([
  "running",
  "succeeded",
  "failed",
  "cancelled",
]);
const agentTurnErrorCodes = new Set<AgentTurnErrorCode>([
  "AGENT_PROVIDER_AUTH_ERROR",
  "AGENT_PROVIDER_ERROR",
  "AGENT_PROVIDER_TIMEOUT",
  "AGENT_INTERNAL_ERROR",
  "AGENT_RUN_CANCELLED",
  "AGENT_EDIT_TRANSACTION_INCOMPLETE",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

function toExecutionState(value: unknown) {
  return typeof value === "string" &&
    agentTurnExecutionStatuses.has(value as AgentTurnExecutionStatus)
    ? (value as AgentTurnExecutionStatus)
    : undefined;
}

function toErrorCode(value: unknown) {
  return typeof value === "string" &&
    agentTurnErrorCodes.has(value as AgentTurnErrorCode)
    ? (value as AgentTurnErrorCode)
    : null;
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

function getPayloadPatch(payload: unknown, key: string) {
  if (!isRecord(payload)) {
    return payload;
  }

  return payload[key] ?? payload;
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
      const executionState = isRecord(payload)
        ? toExecutionState(payload.executionState)
        : undefined;
      if (executionState) {
        accumulator.executionState = executionState;
      }
      accumulator.errorCode = isRecord(payload)
        ? toErrorCode(payload.errorCode)
        : null;
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
  run: Pick<AgentRunResponse, "status" | "executionState" | "errorCode">,
): AgentStreamAccumulator {
  return {
    lastEventId: 0,
    message: createEmptyAssistantMessage(),
    messageDone: false,
    receivedEvent: false,
    status: run.status,
    executionState: run.executionState,
    errorCode: run.errorCode,
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
  const accumulator = createStreamAccumulator(run);
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
      response = undefined;

      if (accumulator.status === "active") {
        // A clean EOF before run_done is still a transport interruption. Route
        // it through the same bounded budget as network failures so repeated
        // short streams cannot reconnect forever.
        throw new Error("Agent stream ended before a terminal event.");
      }
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
    errorCode: accumulator.errorCode,
    executionState: accumulator.executionState,
    lastEventId: accumulator.lastEventId,
    status: accumulator.status,
  };
  options.onRun?.(completedRun);

  return {
    errorCode: accumulator.errorCode,
    executionState: accumulator.executionState,
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
      errorCode: null,
      executionState: "running",
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
