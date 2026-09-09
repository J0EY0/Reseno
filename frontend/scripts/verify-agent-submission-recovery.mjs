import assert from "node:assert/strict";
import vm from "node:vm";

import { loadTypeScriptModule } from "./typescript-module.mjs";

const sourceRoot = new URL("../src/", import.meta.url);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function flush() {
  await new Promise((resolve) => setImmediate(resolve));
}

async function createConversation({
  fetchResource,
  stopRun,
  loadActiveRun,
} = {}) {
  const context = vm.createContext({
    AbortController,
    DOMException,
    Error,
    Headers,
    Response,
    SyntaxError,
    TextDecoder,
    URL,
    console: { error: () => undefined },
    window: { clearTimeout, setTimeout: (callback) => setTimeout(callback, 0) },
  });
  const react = {
    useCallback: (callback) => callback,
    useEffect: (effect) => effect(),
    useLayoutEffect: (effect) => effect(),
    useMemo: (factory) => factory(),
    useRef: (current) => ({ current }),
    useState: (initial) => [
      typeof initial === "function" ? initial() : initial,
      () => undefined,
    ],
  };
  function load(relativePath, imports = {}) {
    return loadTypeScriptModule(new URL(relativePath, sourceRoot), {
      context,
      imports,
    });
  }

  let messages = [];
  let streamingMessage = null;
  let sessionError = false;
  let sessionReads = 0;
  const requests = [];
  const deletedUploads = [];
  const rollbacks = [];
  const api = {
    apiRoutes: {
      agentChat: "/api/agent/chat",
      agentResumeSession: (id) => `/api/agent/resumes/${id}/session`,
      agentRunEvents: (id) => `/api/agent/runs/${id}/events`,
    },
    clearApiCache: () => undefined,
    fetchApiResource: (route, options) => {
      const url = new URL(route, "http://agent.test").href;
      requests.push({ url, options });
      return fetchResource(url, options);
    },
    getApiErrorStatus: () => undefined,
    isAbortError: (error) => error?.name === "AbortError",
    isApiErrorCode: () => false,
  };
  const runtimeModule = await load(
    "components/copilot/agent-conversation-runtime.ts",
    { react },
  );
  const panelState = await load("lib/agent-panel-state.ts");
  const messageCodec = await load("lib/agent-message-codec.ts");
  const streamClient = await load("lib/agent-stream-client.ts", {
    "@/lib/api-client": api,
    "@/lib/auth-session": { getAccessToken: () => "agent-test-token" },
    "@/lib/api-error-notifier": { notifyApiError: () => false },
    "@/lib/agent-message-codec": messageCodec,
  });
  const runtime = {
    activeRequestAbort: null,
    activeRun: null,
    currentResumeId: "resume-1",
    onPreviewAgentEdits: () => undefined,
    onReconcileAgentDraft: () => undefined,
    onRollbackAgentDraft: (messageId) => rollbacks.push(messageId),
    optimisticMessageOwner: null,
    pendingSend: null,
    previewedEditsKey: null,
    replyTimer: null,
    requestFailedText: "request failed",
    requestPhase: "idle",
    requestResume: {},
    sessionReady: true,
    sessionReadyPromise: null,
    sessionRevision: "revision-1",
    stopRequested: false,
    transientStatusTexts: [],
  };
  const runtimeRef = { current: runtime };
  const updates = {
    setMessages: (value) => {
      messages = typeof value === "function" ? value(messages) : value;
    },
    setRequestPhase: () => undefined,
    setSessionLoadError: (value) => {
      sessionError = value;
    },
    setSessionReady: () => undefined,
    setStreamingMessage: (value) => {
      streamingMessage = value;
    },
  };
  const refreshAgentSession = async () => {
    sessionReads += 1;
    runtime.optimisticMessageOwner = null;
    updates.setMessages([]);
    return { resumeId: "resume-1", revision: "revision-1" };
  };
  const imports = {
    react,
    sonner: { toast: { error: () => undefined, info: () => undefined } },
    "@/lib/api-client": api,
    "@/lib/api-error-notifier": { notifyApiError: () => false },
    "@/lib/agent-stream-client": streamClient,
    "@/lib/agent-session-run-client": { stopAgentRun: stopRun },
    "@/lib/agent-panel-state": panelState,
    "@/lib/resume": { createId: () => "user-1" },
    "./agent-conversation-runtime": runtimeModule,
    "./copilot-message-model": {
      getEditsPreviewKey: () => "",
      toAssistantPanelMessage: (message) => message,
      toConversationMessage: (message) => message,
    },
  };
  const runModule = await load(
    "components/copilot/use-agent-run-stream.ts",
    imports,
  );
  const consumeRunStream = runModule.useAgentRunStream({
    refreshAgentSession,
    runtimeRef,
    updates,
  });
  const hydrationModule = await load(
    "components/copilot/use-agent-session-hydration.ts",
    {
      ...imports,
      "@/lib/agent-session-run-client": {
        loadAgentSessionRecovery: async () => ({
          session: await refreshAgentSession(),
          run: (await loadActiveRun?.()) ?? null,
        }),
      },
      "./copilot-message-model": {
        hydrateAgentSession: async (request) => ({
          session: await request,
          draftSnapshot: null,
          panelMessages: [],
        }),
      },
    },
  );
  const retrySession = () =>
    hydrationModule.useAgentSessionHydration({
      cancelScheduledSend: send.cancelScheduledSend,
      consumeRunStream,
      resumeId: "resume-1",
      retryAttempt: 1,
      runtimeRef,
      updates,
    });
  const sendModule = await load(
    "components/copilot/use-agent-send-controller.ts",
    imports,
  );
  const send = sendModule.useAgentSendController({
    agentDraftState: null,
    consumeRunStream,
    documentLocale: "en",
    isSessionMutationPending: false,
    messages: [],
    onBeforeSend: async () => undefined,
    refreshAgentSession,
    resume: {},
    resumeId: "resume-1",
    retrySession,
    runtimeRef,
    selectedModelConfig: { id: "model-1" },
    updates,
  });
  const promptModule = await load(
    "components/copilot/use-agent-prompt-actions.ts",
    {
      ...imports,
      "@/lib/agent-attachment-client": {
        uploadAgentAttachment: async () => ({
          id: "uploaded-1",
          filename: "resume.pdf",
        }),
      },
      "./copilot-attachment-policy": {
        MAX_AGENT_ATTACHMENTS: 5,
        prepareAgentAttachment: async () => ({ body: {}, byteLength: 1 }),
        deletePendingUploads: async (resumeId, files) =>
          deletedUploads.push(...files),
      },
    },
  );
  const prompt = promptModule.useAgentPromptActions({
    hasConfiguredModel: true,
    isRequestBusy: false,
    isSessionReady: true,
    resumeId: "resume-1",
    sessionResetVersion: 0,
    sendPrompt: send.sendPrompt,
    stopConversation: send.stopResponding,
    t: {},
  });
  const composer = {
    attachments: {
      files: [
        {
          id: "local-1",
          type: "file",
          filename: "resume.pdf",
          url: "data:application/pdf;base64,AA==",
        },
      ],
      add: () => undefined,
      clear: () => undefined,
      openFileDialog: () => undefined,
      remove: (id) => {
        composer.attachments.files = composer.attachments.files.filter(
          (file) => file.id !== id,
        );
      },
    },
    registerFileInput: () => undefined,
    textInput: {
      value: "Keep my original prompt",
      clear: () => {
        composer.textInput.value = "";
      },
    },
  };
  const formModule = await load(
    "components/ai-elements/use-prompt-input-form.ts",
    {
      react,
      nanoid: { nanoid: () => "local-2" },
      "@/components/ai-elements/prompt-input-context": {
        useOptionalPromptInputController: () => composer,
      },
    },
  );
  const form = formModule.usePromptInputForm({ onSubmit: prompt.submitPrompt });
  return {
    composer,
    consumeRunStream,
    deletedUploads,
    form,
    prompt,
    requests,
    retrySession,
    rollbacks,
    runtime,
    send,
    connectRun: (run) => {
      const abortController = new AbortController();
      runtime.activeRequestAbort = abortController;
      return consumeRunStream(
        (options) => streamClient.connectAgentRun(run, options),
        abortController,
      );
    },
    get messages() {
      return messages;
    },
    get sessionError() {
      return sessionError;
    },
    get sessionReads() {
      return sessionReads;
    },
    get streamingMessage() {
      return streamingMessage;
    },
  };
}

{
  let post = deferred();
  let streamController;
  let stops = 0;
  let recoveryReads = 0;
  const conversation = await createConversation({
    fetchResource: () => post.promise,
    loadActiveRun: () => {
      recoveryReads += 1;
      return null;
    },
    stopRun: async () => {
      stops += 1;
      streamController.enqueue(
        new TextEncoder().encode(
          'id: 1\nevent: message_done\ndata: {"message":{"id":"assistant-1","role":"assistant","text":"partial","transactionState":"rolled_back"}}\n\n' +
            'id: 2\nevent: run_done\ndata: {"status":"cancelled","executionState":"cancelled"}\n\n',
        ),
      );
      streamController.close();
      return { id: "run-1", status: "active" };
    },
  });
  conversation.prompt.referenceHistoryAttachment({
    id: "history-1",
    filename: "job.pdf",
  });
  const submitted = conversation.form.handleSubmit({
    preventDefault() {},
    currentTarget: {},
  });
  while (conversation.requests.length === 0) {
    await flush();
  }
  post.reject(new TypeError("Failed to fetch"));
  await submitted;
  await flush();
  assert.equal(
    conversation.composer.textInput.value,
    "Keep my original prompt",
    "A POST rejected before acceptance must preserve the submitted text.",
  );
  assert.equal(
    conversation.composer.attachments.files.length,
    1,
    "A POST rejected before acceptance must preserve the local attachment for retry.",
  );
  assert.equal(conversation.messages.length, 0);
  assert.equal(conversation.runtime.requestPhase, "idle");
  assert.equal(conversation.deletedUploads.length, 1);

  post = deferred();
  const retried = conversation.form.handleSubmit({
    preventDefault() {},
    currentTarget: {},
  });
  while (conversation.requests.length < 2) {
    await flush();
  }
  assert.deepEqual(
    JSON.parse(conversation.requests[1].options.body).message.files.map(
      (file) => file.id,
    ),
    ["history-1", "uploaded-1"],
    "Retry must retain both the referenced attachment and the local upload.",
  );
  post.resolve(
    new Response(
      new ReadableStream({
        start(controller) {
          streamController = controller;
        },
      }),
      {
        headers: {
          "Content-Type": "text/event-stream",
          "X-Agent-Run-Id": "run-1",
        },
      },
    ),
  );
  await retried;
  assert.equal(conversation.composer.textInput.value, "");
  assert.equal(conversation.composer.attachments.files.length, 0);
  assert.equal(
    conversation.runtime.requestPhase,
    "responding",
    "Acceptance must release the composer submission without waiting for stream completion.",
  );
  conversation.send.stopResponding();
  await flush();
  assert.equal(stops, 1);
  assert.equal(
    recoveryReads,
    0,
    "A normal stop must keep its existing subscriber instead of starting session recovery.",
  );
  assert.equal(conversation.requests.length, 2);
  assert.equal(conversation.runtime.requestPhase, "idle");
  assert.ok(conversation.rollbacks.includes("assistant-1"));
}

{
  let stopped = false;
  let stopCount = 0;
  const run = {
    id: "run-1",
    status: "active",
    executionState: "running",
    errorCode: null,
    baseResume: {},
    resumeId: "resume-1",
  };
  const conversation = await createConversation({
    fetchResource: async () =>
      new Response(
        stopped
          ? 'id: 1\nevent: run_done\ndata: {"status":"cancelled","executionState":"cancelled"}\n\n'
          : "",
        {
          headers: { "Content-Type": "text/event-stream" },
        },
      ),
    stopRun: async () => {
      stopCount += 1;
      stopped = true;
      return run;
    },
    loadActiveRun: () => run,
  });
  await conversation.connectRun(run);
  assert.equal(conversation.requests.length, 6);
  assert.equal(conversation.runtime.activeRequestAbort, null);
  assert.equal(
    conversation.sessionError,
    true,
    "Exhausting stream recovery must expose the existing session retry action.",
  );
  assert.equal(
    conversation.sessionReads,
    0,
    "A failed subscription must leave session reads to recovery so no stale refresh can overwrite retry.",
  );
  assert.equal(
    conversation.runtime.requestPhase,
    "responding",
    "A disconnected browser must not submit another turn before reconciling the active run.",
  );
  conversation.send.stopResponding();
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await flush();
    if (conversation.runtime.requestPhase === "idle") break;
  }
  assert.equal(stopCount, 1);
  assert.equal(
    conversation.runtime.requestPhase,
    "idle",
    "Stopping without a subscriber must observe the terminal event and restore sending.",
  );
  assert.equal(conversation.requests.length, 7);
  assert.equal(conversation.runtime.activeRun, null);
  assert.equal(conversation.streamingMessage, null);
  assert.equal(conversation.sessionError, false);
}

for (const runAlreadyFinished of [false, true]) {
  let recoveryStarted = false;
  const run = {
    id: "run-1",
    status: "active",
    executionState: "running",
    errorCode: null,
    baseResume: {},
    resumeId: "resume-1",
  };
  const conversation = await createConversation({
    fetchResource: async () =>
      recoveryStarted
        ? new Response(
            'id: 1\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}\n\n',
            { headers: { "Content-Type": "text/event-stream" } },
          )
        : new Response("Service unavailable", { status: 503 }),
    loadActiveRun: () => (runAlreadyFinished ? null : run),
  });
  await conversation.connectRun(run);
  assert.equal(
    conversation.requests.length,
    1,
    "A rejected stream subscription must retain its bounded recovery policy.",
  );
  assert.equal(conversation.sessionError, true);
  recoveryStarted = true;
  conversation.retrySession();
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await flush();
    if (
      conversation.runtime.sessionReady &&
      !conversation.runtime.activeRequestAbort
    )
      break;
  }
  assert.equal(conversation.sessionError, false);
  assert.equal(conversation.runtime.requestPhase, "idle");
  assert.equal(conversation.runtime.activeRun, null);
  assert.equal(
    conversation.requests.length,
    runAlreadyFinished ? 1 : 2,
    "Explicit retry must restore an active stream or adopt an already finished session.",
  );
}

{
  const stop = deferred();
  let recoveryReads = 0;
  const conversation = await createConversation({
    stopRun: () => stop.promise,
    loadActiveRun: () => {
      recoveryReads += 1;
      return null;
    },
  });
  conversation.runtime.activeRun = { id: "old-run", status: "active" };
  conversation.send.stopResponding();
  conversation.runtime.activeRun = { id: "new-run", status: "active" };
  stop.resolve({ id: "old-run", status: "cancelled" });
  await flush();
  assert.equal(
    recoveryReads,
    0,
    "A stop response from an older run must not reset the current session.",
  );
}

console.log("Agent submission and recovery behavior verified.");
