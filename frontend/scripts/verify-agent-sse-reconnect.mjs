import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import vm from "node:vm";
import * as ts from "typescript";

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
  fetchApiResource: (...args) => activeFetch(...args),
  getApiErrorStatus: () => undefined,
  requestApi: () => {
    throw new Error("Unexpected requestApi call.");
  },
  resolveApiUrl: (route, options = {}) => {
    const url = new URL(route, "http://agent.test");
    for (const [key, value] of Object.entries(options.searchParams ?? {})) {
      url.searchParams.set(key, String(value));
    }
    return url.toString();
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

async function loadTypeScriptModule(fileName, imports = {}) {
  const source = await readFile(
    join(frontendRoot, "src", "lib", fileName),
    "utf8",
  );
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };

  vm.runInNewContext(compiled, {
    DOMException,
    Error,
    Response,
    SyntaxError,
    TextDecoder,
    URL,
    exports: module.exports,
    module,
    require: (specifier) => {
      if (Object.hasOwn(imports, specifier)) {
        return imports[specifier];
      }
      throw new Error(`Unexpected import: ${specifier}`);
    },
    window: {
      clearTimeout,
      setTimeout: (callback) => setTimeout(callback, 0),
    },
  });

  return module.exports;
}

async function captureError(action) {
  try {
    await action();
  } catch (error) {
    return error;
  }
  throw new Error("Expected Agent stream consumption to fail.");
}

const messageCodec = await loadTypeScriptModule("agent-message-codec.ts");
const agentStreamClient = await loadTypeScriptModule(
  "agent-stream-client.ts",
  {
    "@/lib/agent-message-codec": messageCodec,
    "@/lib/api-client": apiClient,
  },
);

{
  const requestedUrls = [];
  activeFetch = async (url) => {
    requestedUrls.push(url);
    if (requestedUrls.length > 8) {
      return new Response("", { status: 500 });
    }
    const firstEvent =
      requestedUrls.length === 1
        ? 'id: 41\nevent: text_delta\ndata: {"delta":"partial"}\n\n'
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
    return createEventStream(
      [
        'id: 7\nevent: text_delta\ndata: {"delta":"done"}',
        'id: 8\nevent: message_done\ndata: {"message":{"text":"done"}}',
        'id: 9\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}',
        "",
      ].join("\n\n"),
    );
  };

  const result = await agentStreamClient.connectAgentRun(createActiveRun());

  assert.equal(
    requestCount,
    1,
    "A stream that includes run_done must finish without reconnecting.",
  );
  assert.equal(result.status, "completed");
  assert.equal(result.lastEventId, 9);
  assert.equal(result.message.text, "done");
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

await import("./verify-agent-client-boundaries.mjs");

console.log("Agent SSE reconnect budget checks passed.");
