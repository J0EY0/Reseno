import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import axios from "axios";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const apiClientSource = await readFile(
  new URL("../src/lib/api-client.ts", import.meta.url),
  "utf8",
);
assert.doesNotMatch(apiClientSource, /^import[\s\S]*?from ["']axios["'];$/m);
assert.match(apiClientSource, /await import\(["']axios["']\)/);

const testState = {
  clearedAuthCount: 0,
  invalidatedTokens: new Set(),
  lockRequests: [],
  refreshPending: null,
  redirects: [],
  token: "token-a",
  toasts: [],
};
globalThis.__RESUMATE_API_CLIENT_TEST_STATE__ = testState;
globalThis.window = {
  location: {
    pathname: "/resume",
    assign(url) {
      testState.redirects.push(url);
      this.pathname = url;
    },
  },
};
const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    locks: {
      async request(name, options, callback) {
        testState.lockRequests.push({ name, options });
        await testState.refreshPending;
        return callback();
      },
    },
  },
});

const replies = [];
const requests = [];

function enqueueJson(payload, status = 200) {
  replies.push({
    body: JSON.stringify(payload),
    contentType: "application/json",
    status,
  });
}

function enqueueEnvelope(data, status = 200) {
  enqueueJson({ code: 0, data, message: "OK" }, status);
}

function enqueueNetworkError() {
  replies.push({ kind: "network-error" });
}

function enqueueDeferred() {
  let resolve;
  const promise = new Promise((next) => {
    resolve = next;
  });
  replies.push({ kind: "deferred", promise });
  return {
    resolveEnvelope(data, status = 200) {
      resolve({
        body: JSON.stringify({ code: 0, data, message: "OK" }),
        contentType: "application/json",
        status,
      });
    },
    resolveJson(payload, status = 200) {
      resolve({
        body: JSON.stringify(payload),
        contentType: "application/json",
        status,
      });
    },
  };
}

async function takeReply() {
  const queued = replies.shift();
  assert.ok(queued, "A request was issued without a queued response.");
  return queued.kind === "deferred" ? queued.promise : queued;
}

function normalizeHeaders(value) {
  if (value && typeof value.toJSON === "function") {
    return new Headers(value.toJSON());
  }
  return new Headers(value);
}

async function fetchAdapter(url, init = {}) {
  if (init.signal?.aborted) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }

  requests.push({
    body: init.body,
    credentials: init.credentials,
    headers: normalizeHeaders(init.headers),
    method: init.method ?? "GET",
    signal: init.signal,
    transport: "fetch",
    url: String(url),
  });
  const reply = await takeReply();
  if (reply.kind === "network-error") {
    throw new TypeError("Synthetic network failure.");
  }

  return new Response(reply.body ?? "", {
    headers: reply.contentType ? { "Content-Type": reply.contentType } : {},
    status: reply.status,
  });
}

async function axiosAdapter(config) {
  requests.push({
    body: config.data,
    credentials: config.withCredentials,
    headers: normalizeHeaders(config.headers),
    method: String(config.method ?? "get").toUpperCase(),
    onUploadProgress: config.onUploadProgress,
    signal: config.signal,
    timeout: config.timeout,
    transport: "axios",
    url: String(config.url),
  });
  const reply = await takeReply();
  if (reply.kind === "network-error") {
    throw new axios.AxiosError(
      "Synthetic network failure.",
      axios.AxiosError.ERR_NETWORK,
      config,
    );
  }

  config.onUploadProgress?.({ loaded: 4, total: 10 });
  const response = {
    config,
    data: reply.body ?? "",
    headers: reply.contentType ? { "Content-Type": reply.contentType } : {},
    request: {},
    status: reply.status,
    statusText: String(reply.status),
  };
  if (reply.status < 200 || reply.status >= 300) {
    throw new axios.AxiosError(
      `Synthetic HTTP ${reply.status}.`,
      axios.AxiosError.ERR_BAD_RESPONSE,
      config,
      response.request,
      response,
    );
  }
  return response;
}

const originalFetch = globalThis.fetch;
const originalAxiosAdapter = axios.defaults.adapter;
globalThis.fetch = fetchAdapter;
axios.defaults.adapter = axiosAdapter;

const virtualModules = {
  "@/lib/api-message": `
    export function resolveApiMessage(key) {
      return \`localized:\${key}\`;
    }
  `,
  "@/lib/auth-session": `
    const state = globalThis.__RESUMATE_API_CLIENT_TEST_STATE__;
    export const AUTH_REFRESH_LOCK_NAME = "resumate-auth-refresh";
    export function clearAuthSession() {
      state.clearedAuthCount += 1;
      state.token = null;
    }
    export function getAccessToken() { return state.token; }
    export function isTokenLocallyInvalidated(token) {
      return state.invalidatedTokens.has(token);
    }
  `,
  sonner: `
    const state = globalThis.__RESUMATE_API_CLIENT_TEST_STATE__;
    export const toast = {
      error(message) { state.toasts.push(message); },
    };
  `,
};
const virtualImportPrefix = "virtual:resumate-api-client-test:";
const virtualPrefix = `\0${virtualImportPrefix}`;
const server = await createServer({
  cacheDir: createViteTestCacheDir(),
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  root: process.cwd(),
  plugins: [
    {
      name: "resumate-api-client-test-mocks",
      enforce: "pre",
      resolveId(id) {
        return id.startsWith(virtualImportPrefix) ? `\0${id}` : null;
      },
      load(id) {
        return id.startsWith(virtualPrefix)
          ? virtualModules[id.slice(virtualPrefix.length)]
          : null;
      },
    },
  ],
  resolve: {
    alias: [
      {
        find: "@/lib/api-message",
        replacement: `${virtualImportPrefix}@/lib/api-message`,
      },
      {
        find: "@/lib/auth-session",
        replacement: `${virtualImportPrefix}@/lib/auth-session`,
      },
      { find: "sonner", replacement: `${virtualImportPrefix}sonner` },
      { find: "@", replacement: new URL("../src", import.meta.url).pathname },
    ],
  },
  server: { hmr: false, middlewareMode: true, ws: false },
});

function reset(api) {
  api.clearApiCache();
  replies.length = 0;
  requests.length = 0;
  testState.clearedAuthCount = 0;
  testState.invalidatedTokens.clear();
  testState.lockRequests.length = 0;
  testState.refreshPending = null;
  testState.redirects.length = 0;
  testState.token = "token-a";
  testState.toasts.length = 0;
  window.location.pathname = "/resume";
}

function assertRequestFailure(error, api, options = {}) {
  assert.equal(error.message, `localized:${options.messageKey ?? "REQUEST_FAILED"}`);
  assert.equal(api.getApiErrorStatus(error), options.status);
  assert.equal(api.isApiErrorCode(error, options.apiCode ?? ""), Boolean(options.apiCode));
  assert.equal(api.isApiErrorToastShown(error), options.notified ?? true);
  return true;
}

async function waitForRequestCount(expected) {
  for (let attempt = 0; attempt < 20 && requests.length < expected; attempt += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(requests.length, expected);
}

try {
  const api = await server.ssrLoadModule("/src/lib/api-client.ts");

  reset(api);
  enqueueEnvelope({ value: 1 });
  assert.deepEqual(
    await api.requestApi("/api/example", {
      searchParams: { count: 0, enabled: false, ignored: null, query: "a b" },
    }),
    { value: 1 },
  );
  assert.equal(requests[0].url, "/api/example?count=0&enabled=false&query=a+b");
  assert.equal(requests[0].transport, "fetch");
  assert.equal(
    requests[0].headers.get("Accept"),
    "application/json, text/plain, */*",
  );
  assert.equal(requests[0].headers.get("Authorization"), "Bearer token-a");
  assert.equal(requests[0].credentials, undefined);

  reset(api);
  enqueueEnvelope({ loggedIn: true });
  await api.requestApi("/api/auth/login", {
    auth: false,
    body: { password: "secret", username: "admin" },
    method: "POST",
  });
  assert.equal(requests[0].headers.get("Authorization"), null);
  assert.match(requests[0].headers.get("Content-Type"), /^application\/json/);
  assert.equal(requests[0].body, '{"password":"secret","username":"admin"}');

  const standardApiErrors = [
    { code: 40000, message: "BAD_REQUEST", status: 400 },
    { code: 40001, message: "UNAUTHORIZED_REQUEST", status: 401 },
    { code: 40004, message: "NOT_FOUND", status: 404 },
    { code: 40002, message: "VALIDATION_ERROR", status: 422 },
    { code: 50000, message: "INTERNAL_SERVER_ERROR", status: 500 },
  ];

  for (const expected of standardApiErrors) {
    reset(api);
    enqueueJson(
      { code: expected.code, data: null, message: expected.message },
      expected.status,
    );
    await assert.rejects(
      api.requestApi(`/api/failure-${expected.status}`),
      (error) =>
        assertRequestFailure(error, api, {
          apiCode: expected.message,
          messageKey: expected.message,
          status: expected.status,
        }),
    );
    assert.deepEqual(testState.toasts, [`localized:${expected.message}`]);
    assert.equal(
      testState.clearedAuthCount,
      expected.status === 401 ? 1 : 0,
    );
    assert.deepEqual(
      testState.redirects,
      expected.status === 401 ? ["/login"] : [],
    );
  }

  const unauthorizedPayload = {
    code: 40001,
    data: null,
    message: "UNAUTHORIZED_REQUEST",
  };
  const unauthorizedRequests = [
    { run: () => api.requestApi("/api/protected"), status: 401 },
    { run: () => api.requestApi("/api/protected"), status: 200 },
    { run: () => api.uploadApi("/api/upload", new FormData()), status: 401 },
    { run: () => api.uploadApi("/api/upload", new FormData()), status: 200 },
    { run: () => api.fetchApiResource("/api/events"), status: 401 },
    { run: () => api.fetchApiResource("/api/events"), status: 200 },
  ];

  for (const { run, status } of unauthorizedRequests) {
    reset(api);
    const lateFailure = enqueueDeferred();
    const pendingFailure = run();
    await waitForRequestCount(1);
    testState.token = "token-b";
    lateFailure.resolveJson(unauthorizedPayload, status);
    await assert.rejects(pendingFailure, /localized:UNAUTHORIZED_REQUEST/);
    assert.equal(testState.token, "token-b");
    assert.equal(testState.clearedAuthCount, 0);
    assert.deepEqual(testState.redirects, []);
    assert.equal(requests.length, 1);

    reset(api);
    enqueueJson(unauthorizedPayload, status);
    await assert.rejects(run(), /localized:UNAUTHORIZED_REQUEST/);
    assert.equal(testState.clearedAuthCount, 1);
    assert.deepEqual(testState.redirects, ["/login"]);

    reset(api);
    let finishRefresh;
    testState.refreshPending = new Promise((resolve) => {
      finishRefresh = resolve;
    });
    const refreshWindowFailure = enqueueDeferred();
    const waitingFailure = run();
    await waitForRequestCount(1);
    refreshWindowFailure.resolveJson(unauthorizedPayload, status);
    for (let attempt = 0; attempt < 20 && !testState.lockRequests.length; attempt += 1) {
      await new Promise((resolve) => setImmediate(resolve));
    }
    assert.deepEqual(testState.lockRequests, [
      { name: "resumate-auth-refresh", options: { mode: "shared" } },
    ]);
    assert.equal(testState.clearedAuthCount, 0);
    testState.token = "token-b";
    finishRefresh();
    await assert.rejects(waitingFailure, /localized:UNAUTHORIZED_REQUEST/);
    assert.equal(testState.token, "token-b");
    assert.deepEqual(testState.redirects, []);
  }

  for (const run of [
    () => api.requestApi("/api/auth/login", { auth: false, method: "POST" }),
    () => api.uploadApi("/api/upload", new FormData(), { auth: false }),
  ]) {
    reset(api);
    testState.token = null;
    const anonymousFailure = enqueueDeferred();
    const pendingFailure = run();
    await waitForRequestCount(1);
    assert.equal(requests[0].headers.get("Authorization"), null);
    testState.token = "token-b";
    anonymousFailure.resolveJson(unauthorizedPayload, 401);
    await assert.rejects(pendingFailure, /localized:UNAUTHORIZED_REQUEST/);
    assert.equal(testState.token, "token-b");
    assert.equal(testState.clearedAuthCount, 0);
    assert.deepEqual(testState.redirects, []);
    assert.deepEqual(testState.lockRequests, []);
  }

  reset(api);
  testState.refreshPending = new Promise(() => {});
  enqueueJson(unauthorizedPayload, 401);
  await assert.rejects(
    api.requestApi(api.apiRoutes.authRefresh, { method: "POST", body: {} }),
    /localized:UNAUTHORIZED_REQUEST/,
  );
  assert.equal(testState.clearedAuthCount, 1);
  assert.deepEqual(testState.lockRequests, []);

  reset(api);
  enqueueJson(
    { code: 40002, data: null, message: "VALIDATION_ERROR" },
    422,
  );
  await assert.rejects(
    api.requestApi("/api/quiet-failure", { notifyOnError: false }),
    (error) =>
      assertRequestFailure(error, api, {
        apiCode: "VALIDATION_ERROR",
        messageKey: "VALIDATION_ERROR",
        notified: false,
        status: 422,
      }),
  );
  assert.deepEqual(testState.toasts, []);

  reset(api);
  testState.token = null;
  await assert.rejects(
    api.requestApi("/api/protected", { notifyOnError: false }),
    (error) =>
      assertRequestFailure(error, api, {
        messageKey: "AUTHENTICATION_REQUIRED",
        notified: false,
      }),
  );
  assert.equal(requests.length, 0);
  assert.equal(testState.clearedAuthCount, 1);
  assert.deepEqual(testState.redirects, ["/login"]);
  assert.deepEqual(testState.toasts, []);

  for (const run of [
    () => api.requestApi("/api/protected"),
    () => api.uploadApi("/api/upload", new FormData()),
    () => api.fetchApiResource("/api/resource"),
  ]) {
    reset(api);
    testState.token = null;
    await assert.rejects(run(), (error) =>
      assertRequestFailure(error, api, { messageKey: "AUTHENTICATION_REQUIRED" }),
    );
    assert.equal(requests.length, 0);
    assert.deepEqual(testState.toasts, ["localized:AUTHENTICATION_REQUIRED"]);
    assert.deepEqual(testState.redirects, ["/login"]);
  }

  for (const run of [
    () => api.requestApi("/api/failure"),
    () => api.uploadApi("/api/upload", new FormData()),
    () => api.fetchApiResource("/api/resource"),
  ]) {
    for (const reply of [
      { body: '<html>Bad Gateway</html>', contentType: "text/html", status: 502 },
      { body: '{"detail":"Not Found"}', contentType: "application/json", status: 404 },
    ]) {
      reset(api);
      replies.push(reply);
      await assert.rejects(run(), (error) =>
        assertRequestFailure(error, api, { status: reply.status }),
      );
      assert.deepEqual(testState.toasts, ["localized:REQUEST_FAILED"]);
    }

    reset(api);
    enqueueNetworkError();
    await assert.rejects(run(), (error) => assertRequestFailure(error, api));
    assert.deepEqual(testState.toasts, ["localized:REQUEST_FAILED"]);
  }

  reset(api);
  enqueueJson(
    { detail: { code: "AGENT_SESSION_REVISION_CONFLICT", revision: 4 } },
    409,
  );
  await assert.rejects(
    api.requestApi("/api/conflict", { method: "PUT", body: {} }),
    (error) =>
      assertRequestFailure(error, api, {
        apiCode: "AGENT_SESSION_REVISION_CONFLICT",
        messageKey: "AGENT_SESSION_REVISION_CONFLICT",
        status: 409,
      }),
  );

  reset(api);
  replies.push({ body: "not-json", contentType: "application/json", status: 200 });
  await assert.rejects(
    api.requestApi("/api/invalid"),
    (error) =>
      assertRequestFailure(error, api, { messageKey: "INVALID_API_RESPONSE" }),
  );

  reset(api);
  enqueueNetworkError();
  await assert.rejects(
    api.requestApi("/api/network"),
    (error) => assertRequestFailure(error, api),
  );

  reset(api);
  const abortController = new AbortController();
  abortController.abort();
  await assert.rejects(
    api.requestApi("/api/cancelled", { signal: abortController.signal }),
    (error) => {
      assert.equal(api.isAbortError(error), true);
      assert.equal(api.isApiErrorToastShown(error), false);
      return true;
    },
  );
  assert.deepEqual(testState.toasts, []);

  reset(api);
  const deferred = enqueueDeferred();
  const first = api.requestApi("/api/cached", { cacheTtlMs: 1_000 });
  const second = api.requestApi("/api/cached", { cacheTtlMs: 1_000 });
  await waitForRequestCount(1);
  deferred.resolveEnvelope({ version: 1 });
  assert.deepEqual(await Promise.all([first, second]), [
    { version: 1 },
    { version: 1 },
  ]);

  enqueueEnvelope({ saved: true });
  await api.requestApi("/api/mutation", { body: {}, method: "POST" });
  enqueueEnvelope({ version: 2 });
  assert.deepEqual(
    await api.requestApi("/api/cached", { cacheTtlMs: 1_000 }),
    { version: 2 },
  );
  assert.equal(requests.length, 3);

  reset(api);
  enqueueNetworkError();
  await assert.rejects(
    api.requestApi("/api/retry-cache", {
      cacheTtlMs: 1_000,
      notifyOnError: false,
    }),
    /localized:REQUEST_FAILED/,
  );
  enqueueEnvelope({ attempt: 2 });
  assert.deepEqual(
    await api.requestApi("/api/retry-cache", { cacheTtlMs: 1_000 }),
    { attempt: 2 },
  );
  assert.equal(requests.length, 2);

  reset(api);
  enqueueEnvelope({ owner: 1 });
  enqueueEnvelope({ owner: 2 });
  const ownerA = new AbortController();
  const ownerB = new AbortController();
  await Promise.all([
    api.requestApi("/api/owned", { cacheTtlMs: 1_000, signal: ownerA.signal }),
    api.requestApi("/api/owned", { cacheTtlMs: 1_000, signal: ownerB.signal }),
  ]);
  assert.equal(requests.length, 2, "Cancelable GETs must never share a promise.");

  reset(api);
  enqueueJson({ code: 40000, data: null, message: "BAD_REQUEST" });
  const sharedFailureA = api.requestApi("/api/shared-failure", {
    cacheTtlMs: 1_000,
  });
  const sharedFailureB = api.requestApi("/api/shared-failure", {
    cacheTtlMs: 1_000,
  });
  await Promise.allSettled([sharedFailureA, sharedFailureB]);
  assert.equal(requests.length, 1);
  assert.deepEqual(testState.toasts, ["localized:BAD_REQUEST"]);

  reset(api);
  enqueueEnvelope({ id: "attachment-1" });
  const progress = [];
  const uploadBody = new FormData();
  uploadBody.set("file", new Blob(["test"]), "test.txt");
  assert.deepEqual(
    await api.uploadApi("/api/upload", uploadBody, {
      onProgress: (event) => progress.push(event),
      timeoutMs: 2_000,
    }),
    { id: "attachment-1" },
  );
  assert.equal(requests[0].body, uploadBody);
  assert.equal(requests[0].transport, "axios");
  assert.equal(requests[0].timeout, 2_000);
  assert.equal(requests[0].headers.get("Authorization"), "Bearer token-a");
  assert.notEqual(requests[0].headers.get("Content-Type"), "application/json");
  assert.deepEqual(progress, [{ loaded: 4, total: 10 }]);

  reset(api);
  const uploadAbortController = new AbortController();
  uploadAbortController.abort();
  await assert.rejects(
    api.uploadApi("/api/upload", new FormData(), {
      signal: uploadAbortController.signal,
    }),
    (error) => api.isAbortError(error),
  );
  assert.equal(requests.length, 0);
  assert.deepEqual(testState.toasts, []);

  reset(api);
  enqueueEnvelope({ stream: true });
  const resource = await api.fetchApiResource("/api/events", {
    headers: { Accept: "text/event-stream" },
  });
  assert.equal(resource.status, 200);
  assert.equal(requests[0].headers.get("Accept"), "text/event-stream");
  assert.equal(requests[0].headers.get("Authorization"), "Bearer token-a");
  assert.equal(requests[0].credentials, undefined);

  for (const expected of standardApiErrors) {
    reset(api);
    enqueueJson(
      { code: expected.code, data: null, message: expected.message },
      expected.status,
    );
    await assert.rejects(
      api.fetchApiResource(`/api/resource-error-${expected.status}`),
      (error) =>
        assertRequestFailure(error, api, {
          apiCode: expected.message,
          messageKey: expected.message,
          status: expected.status,
        }),
    );
    assert.deepEqual(testState.toasts, [`localized:${expected.message}`]);
    assert.equal(
      testState.clearedAuthCount,
      expected.status === 401 ? 1 : 0,
    );
    assert.deepEqual(
      testState.redirects,
      expected.status === 401 ? ["/login"] : [],
    );
  }

  reset(api);
  enqueueJson(
    { detail: { code: "AGENT_SESSION_TURN_CONFLICT", runId: "run-1" } },
    409,
  );
  await assert.rejects(
    api.fetchApiResource("/api/resource-conflict"),
    (error) =>
      assertRequestFailure(error, api, {
        apiCode: "AGENT_SESSION_TURN_CONFLICT",
        messageKey: "AGENT_SESSION_TURN_CONFLICT",
        status: 409,
      }),
  );
  assert.deepEqual(testState.toasts, [
    "localized:AGENT_SESSION_TURN_CONFLICT",
  ]);

  reset(api);
  enqueueJson(
    { detail: { code: "AGENT_SESSION_REVISION_CONFLICT", revision: 4 } },
    409,
  );
  await assert.rejects(
    api.fetchApiResource("/api/resource-revision-conflict"),
    (error) =>
      assertRequestFailure(error, api, {
        apiCode: "AGENT_SESSION_REVISION_CONFLICT",
        messageKey: "AGENT_SESSION_REVISION_CONFLICT",
        status: 409,
      }),
  );

  assert.equal(replies.length, 0, "Every queued response must be consumed.");
  console.log("API client behavior verified.");
} finally {
  axios.defaults.adapter = originalAxiosAdapter;
  globalThis.fetch = originalFetch;
  delete globalThis.__RESUMATE_API_CLIENT_TEST_STATE__;
  delete globalThis.window;
  if (originalNavigator) {
    Object.defineProperty(globalThis, "navigator", originalNavigator);
  } else {
    delete globalThis.navigator;
  }
  await server.close();
}
