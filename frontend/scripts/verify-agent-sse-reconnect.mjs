import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { evaluateTypeScript } from "./typescript-module.mjs";

const frontendRoot = new URL("..", import.meta.url).pathname;
let activeFetch;
const clearedRoutes = [];

const apiClient = {
  apiRoutes: {
    agentChat: "/api/agent/chat",
    agentResumeSession: (resumeId) => `/api/agent/resumes/${resumeId}/session`,
    agentRunEvents: (runId) => `/api/agent/runs/${runId}/events`,
  },
  clearApiCache: (route) => clearedRoutes.push(route),
  fetchApiResource: (route, options) =>
    activeFetch(new URL(route, "http://agent.test").href, options),
  getApiErrorStatus: () => undefined,
  requestApi: () => {
    throw new Error("Unexpected requestApi call.");
  },
  uploadApi: () => {
    throw new Error("Unexpected uploadApi call.");
  },
};

function createEventStream(body = "", headers = {}) {
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream", ...headers },
    status: 200,
  });
}

function createActiveRun() {
  return {
    baseResume: null,
    errorCode: null,
    executionState: "running",
    id: "run-reconnect-test",
    lastEventId: 0,
    resumeId: null,
    status: "active",
  };
}

async function loadTypeScriptModule(fileName, imports = {}, globals = {}) {
  const source = await readFile(
    join(frontendRoot, "src", "lib", fileName),
    "utf8",
  );

  return evaluateTypeScript(source, {
    globals: {
      DOMException,
      Error,
      Response,
      SyntaxError,
      TextDecoder,
      URL,
      window: {
        clearTimeout,
        setTimeout: (callback) => setTimeout(callback, 0),
      },
      ...globals,
    },
    imports,
  });
}

async function captureError(action) {
  try {
    await action();
  } catch (error) {
    return error;
  }
  throw new Error("Expected Agent stream consumption to fail.");
}

function setAgentRequestPhase(runtime, updates, phase) {
  runtime.requestPhase = phase;
  updates.setRequestPhase(phase);
}

const messageCodec = await loadTypeScriptModule("agent-message-codec.ts");
const agentStreamClient = await loadTypeScriptModule("agent-stream-client.ts", {
  "@/lib/agent-message-codec": messageCodec,
  "@/lib/api-client": apiClient,
});
const agentRunStreamHook = await loadTypeScriptModule(
  "../components/copilot/use-agent-run-stream.ts",
  {
    react: { useCallback: (callback) => callback },
    sonner: { toast: { error: () => undefined } },
    "@/lib/agent-session-run-client": {
      stopAgentRun: () => Promise.resolve(),
    },
    "@/lib/api-client": {
      isAbortError: (error) => error?.name === "AbortError",
    },
    "@/lib/api-error-notifier": { notifyApiError: () => false },
    "./agent-conversation-runtime": { setAgentRequestPhase },
    "./copilot-message-model": {
      getEditsPreviewKey: () => "",
      toAssistantPanelMessage: (message) => message,
    },
  },
  { console: { error: () => undefined } },
);

for (const abrupt of [false, true]) {
  let requests = 0;
  const cursors = [];
  activeFetch = async (url) => {
    cursors.push(Number(new URL(url).searchParams.get("after")));
    const id = ++requests;
    const event =
      id === 9
        ? `id: ${id}\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}\n\n`
        : `id: ${id}\nevent: text_delta\ndata: {"delta":"a","timelinePartId":"text-1"}\n\n`;
    if (!abrupt || id === 9) return createEventStream(event);
    let delivered = false;
    return new Response(
      new ReadableStream({
        pull(controller) {
          if (delivered)
            controller.error(new Error("network interrupted after progress"));
          else {
            delivered = true;
            controller.enqueue(new TextEncoder().encode(event));
          }
        },
      }),
      { headers: { "Content-Type": "text/event-stream" } },
    );
  };
  const result = await agentStreamClient.connectAgentRun(createActiveRun());
  assert.equal(result.status, "completed");
  assert.equal(result.message.text, "aaaaaaaa");
  assert.deepEqual(cursors, [0, 1, 2, 3, 4, 5, 6, 7, 8]);
}

{
  const requestedUrls = [];
  activeFetch = async (url) => {
    requestedUrls.push(url);
    if (requestedUrls.length > 8) {
      return new Response("", { status: 500 });
    }
    const firstEvent =
      requestedUrls.length === 1
        ? 'id: 41\nevent: text_delta\ndata: {"delta":"partial","timelinePartId":"timeline-text-1"}\n\n'
        : "";
    return createEventStream(firstEvent);
  };

  const error = await captureError(() =>
    agentStreamClient.connectAgentRun(createActiveRun()),
  );

  assert.equal(
    requestedUrls.length,
    6,
    "A stream that repeatedly reaches EOF before run_done must stop after the bounded retry budget.",
  );
  assert.match(
    String(error),
    /terminal event/i,
    "Premature EOF exhaustion must report that the terminal event was not received.",
  );
  assert.ok(
    requestedUrls
      .slice(1)
      .every((url) => new URL(url).searchParams.get("after") === "41"),
    "Every reconnect must resume after the last acknowledged SSE event id.",
  );
}

{
  let requestCount = 0;
  activeFetch = async () => {
    requestCount += 1;
    if (requestCount > 8) {
      return new Response("", { status: 500 });
    }
    if (requestCount % 2 === 0) {
      throw new Error(`network interruption ${requestCount / 2}`);
    }
    return createEventStream();
  };

  const error = await captureError(() =>
    agentStreamClient.connectAgentRun(createActiveRun()),
  );

  assert.equal(
    requestCount,
    6,
    "Premature EOF and network failures must consume one shared reconnect budget.",
  );
  assert.match(
    String(error),
    /network interruption 3/,
    "The transport error that exhausts the shared retry budget must be preserved.",
  );
}

{
  let requestCount = 0;
  activeFetch = async () => {
    requestCount += 1;
    return createEventStream();
  };
  const abortController = new AbortController();
  const requestPhaseWrites = [];
  const streamingWrites = [];
  const runtime = {
    activeRequestAbort: abortController,
    activeRun: null,
    currentResumeId: "resume-active-after-exhaustion",
    onPreviewAgentEdits: () => undefined,
    onRollbackAgentDraft: () => undefined,
    previewedEditsKey: null,
    requestPhase: "responding",
    requestFailedText: "request failed",
    requestResume: null,
    sessionReady: true,
    sessionRevision: "revision-active",
    stopRequested: false,
    transientStatusTexts: [],
  };
  const consumeRunStream = agentRunStreamHook.useAgentRunStream({
    refreshAgentSession: () => Promise.resolve(null),
    runtimeRef: { current: runtime },
    updates: {
      setMessages: () => undefined,
      setRequestPhase: (value) => requestPhaseWrites.push(value),
      setSessionLoadError: () => undefined,
      setSessionReady: () => undefined,
      setStreamingMessage: (value) => streamingWrites.push(value),
    },
  });
  const run = {
    ...createActiveRun(),
    id: "run-still-active-after-exhaustion",
    resumeId: runtime.currentResumeId,
  };

  const status = await consumeRunStream(
    (options) => agentStreamClient.connectAgentRun(run, options),
    abortController,
  );

  assert.equal(status, "failed");
  assert.equal(
    requestCount,
    6,
    "The controller must not turn a spent reconnect budget into an unbounded resubscription loop.",
  );
  assert.equal(
    runtime.activeRequestAbort,
    null,
    "A failed subscription must release its spent abort-controller ownership.",
  );
  assert.equal(
    runtime.activeRun?.id,
    run.id,
    "Transport exhaustion must preserve the accepted active run so Stop can still target it.",
  );
  assert.equal(
    requestPhaseWrites.includes("idle"),
    false,
    "Transport exhaustion must keep the send gate closed while the backend run may still be active.",
  );
  assert.equal(
    streamingWrites.includes(null),
    false,
    "Transport exhaustion must preserve the last observable streaming frame for an active run.",
  );
}

{
  let requestCount = 0;
  const publishedMessages = [];
  activeFetch = async () => {
    requestCount += 1;
    return createEventStream(
      [
        'id: 7\nevent: text_delta\ndata: {"delta":"done","timelinePartId":"timeline-text-1"}',
        'id: 8\nevent: message_done\ndata: {"message":{"id":"message-done","role":"assistant","text":"done","timeline":[{"id":"timeline-text-1","type":"text","text":"done","toolIds":[]}]}}',
        'id: 9\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}',
        "",
      ].join("\n\n"),
    );
  };

  const result = await agentStreamClient.connectAgentRun(createActiveRun(), {
    onMessage: (message) => publishedMessages.push(message),
  });

  assert.equal(
    requestCount,
    1,
    "A stream that includes run_done must finish without reconnecting.",
  );
  assert.equal(result.status, "completed");
  assert.equal(result.lastEventId, 9);
  assert.equal(result.message.text, "done");
  assert.equal(result.message.timeline[0].text, "done");
  assert.equal(
    publishedMessages.length,
    1,
    "Events received in one transport chunk must publish one React state update.",
  );
}

{
  let requestCount = 0;
  activeFetch = async () => {
    requestCount += 1;
    return createEventStream(
      [
        'id: 10\nevent: message_done\ndata: {"message":{"id":"message-cancelled","role":"assistant","text":"kept partial","transactionState":"rolled_back"}}',
        'id: 11\nevent: run_done\ndata: {"status":"cancelled","executionState":"cancelled","errorCode":"AGENT_RUN_CANCELLED"}',
        "",
      ].join("\n\n"),
    );
  };

  const result = await agentStreamClient.connectAgentRun(createActiveRun());

  assert.equal(requestCount, 1);
  assert.equal(result.status, "cancelled");
  assert.equal(result.executionState, "cancelled");
  assert.equal(result.messageDone, true);
  assert.equal(result.message.text, "kept partial");
  assert.equal(result.message.transactionState, "rolled_back");
}

{
  activeFetch = async () =>
    createEventStream(
      [
        'id: 20\nevent: error\ndata: {"error":"Agent model turn limit reached.","errorCode":"AGENT_INTERNAL_ERROR"}',
        'id: 21\nevent: message_done\ndata: {"message":{"id":"message-turn-limit","role":"assistant","text":"No unfinished changes were applied.","transactionState":"rolled_back"}}',
        'id: 22\nevent: run_done\ndata: {"status":"failed","executionState":"failed","errorCode":"AGENT_INTERNAL_ERROR"}',
        "",
      ].join("\n\n"),
    );

  const result = await agentStreamClient.connectAgentRun(createActiveRun());

  assert.equal(result.status, "failed");
  assert.equal(result.executionState, "failed");
  assert.equal(result.errorCode, "AGENT_INTERNAL_ERROR");
  assert.equal(result.message.transactionState, "rolled_back");
}

{
  const controller = new AbortController();
  const request = {
    message: "Improve the summary",
    resume: { basics: { name: "Test User" } },
    resumeId: "resume-send-test",
  };
  let capturedRequest;
  activeFetch = async (...args) => {
    capturedRequest = args;
    return createEventStream(
      [
        'id: 1\nevent: message_done\ndata: {"message":{"id":"message-send-test","text":"done"}}',
        'id: 2\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}',
        "",
      ].join("\n\n"),
      { "X-Agent-Run-Id": "run-send-test" },
    );
  };

  const result = await agentStreamClient.sendAgentChatMessage(request, {
    signal: controller.signal,
  });
  const [url, init] = capturedRequest;

  assert.equal(url, "http://agent.test/api/agent/chat");
  assert.equal(init.method, "POST");
  assert.equal(init.cache, "no-store");
  assert.equal(init.headers.Accept, "text/event-stream");
  assert.equal(init.headers["Content-Type"], "application/json");
  assert.equal(init.signal, controller.signal);
  assert.deepEqual(JSON.parse(init.body), { ...request, stream: true });
  assert.equal(result.runId, "run-send-test");
  assert.equal(result.messageDone, true);
  assert.equal(
    clearedRoutes.at(-1),
    "/api/agent/resumes/resume-send-test/session",
    "A completed persisted run must invalidate the owning Agent session cache.",
  );
}

{
  const controller = new AbortController();
  controller.abort();
  let requestCount = 0;
  activeFetch = async () => {
    requestCount += 1;
    return createEventStream();
  };

  const error = await captureError(() =>
    agentStreamClient.connectAgentRun(createActiveRun(), {
      signal: controller.signal,
    }),
  );

  assert.equal(error.name, "AbortError");
  assert.equal(
    requestCount,
    0,
    "An already-aborted stream subscription must not start a request.",
  );
}

console.log("Agent SSE reconnect budget checks passed.");
