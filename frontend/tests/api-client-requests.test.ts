// @vitest-environment node

import assert from "node:assert/strict";
import { describe, it } from "vitest";
import {
  api,
  core,
  notifyApiError,
  assertRequestFailure,
  enqueueEnvelope,
  enqueueJson,
  enqueueDeferred,
  enqueueNetworkError,
  requests,
  replies,
  testState,
} from "./helpers/api-client-fixture";

it("encodes query values and sends authenticated fetch headers", async () => {
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
});

it("serializes anonymous login JSON without an Authorization header", async () => {
  enqueueEnvelope({ loggedIn: true });
  await api.requestApi("/api/auth/login", {
    auth: false,
    body: { password: "secret", username: "admin" },
    method: "POST",
  });
  assert.equal(requests[0].headers.get("Authorization"), null);
  assert.match(
    requests[0].headers.get("Content-Type") ?? "",
    /^application\/json/,
  );
  assert.equal(requests[0].body, '{"password":"secret","username":"admin"}');
});

const standardApiErrors = [
  { code: 40000, message: "BAD_REQUEST", status: 400 },
  { code: 40001, message: "UNAUTHORIZED_REQUEST", status: 401 },
  { code: 40004, message: "NOT_FOUND", status: 404 },
  { code: 40000, message: "AGENT_RUN_CONFLICT", status: 409 },
  { code: 40000, message: "BAD_REQUEST", status: 412 },
  { code: 40000, message: "BAD_REQUEST", status: 428 },
  { code: 40002, message: "VALIDATION_ERROR", status: 422 },
  { code: 50000, message: "INTERNAL_SERVER_ERROR", status: 500 },
];
describe.each([
  { name: "JSON", run: (route: string) => api.requestApi(route) },
  { name: "resource", run: (route: string) => api.fetchApiResource(route) },
])("$name response protocol", ({ run }) => {
  it.each(standardApiErrors)(
    "normalizes HTTP $status $message",
    async (expected) => {
      enqueueJson(
        { code: expected.code, data: null, message: expected.message },
        expected.status,
      );
      await assert.rejects(run(`/api/failure-${expected.status}`), (error) =>
        assertRequestFailure(error, {
          apiCode: expected.message,
          messageKey: expected.message,
          status: expected.status,
          notified: expected.status !== 401,
        }),
      );
      assert.deepEqual(
        testState.toasts,
        expected.status === 401 ? [] : [`localized:${expected.message}`],
      );
      assert.equal(testState.clearedAuthCount, expected.status === 401 ? 1 : 0);
      assert.deepEqual(
        testState.invalidations,
        expected.status === 401 ? ["reseno:auth-session-invalidated"] : [],
      );
    },
  );
});
it("respects notifyOnError false on validation failures", async () => {
  enqueueJson({ code: 40002, data: null, message: "VALIDATION_ERROR" }, 422);
  await assert.rejects(
    api.requestApi("/api/quiet-failure", { notifyOnError: false }),
    (error) =>
      assertRequestFailure(error, {
        apiCode: "VALIDATION_ERROR",
        messageKey: "VALIDATION_ERROR",
        notified: false,
        status: 422,
      }),
  );
  assert.deepEqual(testState.toasts, []);
});

describe.each([
  { name: "JSON", run: () => api.requestApi("/api/failure") },
  { name: "upload", run: () => api.uploadApi("/api/upload", new FormData()) },
  { name: "resource", run: () => api.fetchApiResource("/api/resource") },
])("$name failures", ({ run }) => {
  it.each([
    { body: "<html>Bad Gateway</html>", contentType: "text/html", status: 502 },
    {
      body: '{"detail":"Not Found"}',
      contentType: "application/json",
      status: 404,
    },
  ])("maps non-envelope HTTP $status failures", async (reply) => {
    replies.push(reply);
    await assert.rejects(run(), (error) =>
      assertRequestFailure(error, { status: reply.status }),
    );
    assert.deepEqual(testState.toasts, ["localized:REQUEST_FAILED"]);
  });
  it("localizes transport failures", async () => {
    enqueueNetworkError();
    await assert.rejects(run(), (error) => assertRequestFailure(error));
    assert.deepEqual(testState.toasts, ["localized:REQUEST_FAILED"]);
  });
});
it("preserves Agent revision conflicts from JSON requests", async () => {
  enqueueJson(
    {
      code: 40000,
      message: "AGENT_SESSION_REVISION_CONFLICT",
      data: { revision: 4 },
      requestId: null,
    },
    409,
  );
  await assert.rejects(
    api.requestApi("/api/conflict", { method: "PUT", body: {} }),
    (error) =>
      assertRequestFailure(error, {
        apiCode: "AGENT_SESSION_REVISION_CONFLICT",
        messageKey: "AGENT_SESSION_REVISION_CONFLICT",
        status: 409,
      }),
  );
});

it("rejects successful malformed JSON as an invalid envelope", async () => {
  replies.push({
    body: "not-json",
    contentType: "application/json",
    status: 200,
  });
  await assert.rejects(api.requestApi("/api/invalid"), (error) =>
    assertRequestFailure(error, { messageKey: "INVALID_API_RESPONSE" }),
  );
});

it("uses Axios for multipart uploads with progress and timeout", async () => {
  enqueueEnvelope({ id: "attachment-1" });
  const progress: { loaded: number; total?: number }[] = [];
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
});

it("preserves resource Accept headers and authenticated credentials", async () => {
  enqueueEnvelope({ stream: true });
  const resource = await api.fetchApiResource("/api/events", {
    headers: { Accept: "text/event-stream" },
  });
  assert.equal(resource.status, 200);
  assert.equal(requests[0].headers.get("Accept"), "text/event-stream");
  assert.equal(requests[0].headers.get("Authorization"), "Bearer token-a");
  assert.equal(requests[0].credentials, undefined);
});

it.each(["AGENT_SESSION_TURN_CONFLICT", "AGENT_SESSION_REVISION_CONFLICT"])(
  "preserves %s resource conflicts",
  async (message) => {
    enqueueJson(
      {
        code: 40000,
        message: message,
        data:
          message === "AGENT_SESSION_TURN_CONFLICT"
            ? { runId: "run-1" }
            : { revision: 4 },
        requestId: null,
      },
      409,
    );
    await assert.rejects(
      api.fetchApiResource("/api/resource-conflict"),
      (error) =>
        assertRequestFailure(error, {
          apiCode: message,
          messageKey: message,
          status: 409,
        }),
    );
    assert.deepEqual(testState.toasts, [`localized:${message}`]);
  },
);
it.each([
  {
    name: "JSON",
    run: (signal: AbortSignal) => api.requestApi("/api/abort", { signal }),
  },
  {
    name: "upload",
    run: (signal: AbortSignal) =>
      api.uploadApi("/api/abort", new FormData(), { signal }),
  },
  {
    name: "resource",
    run: (signal: AbortSignal) =>
      api.fetchApiResource("/api/abort", { signal }),
  },
])("$name aborts before transport without notification", async ({ run }) => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(run(controller.signal), (error) =>
    api.isAbortError(error),
  );
  assert.deepEqual(testState.toasts, []);
  assert.equal(requests.length, 0);
});
it.each([
  ["text/event-stream", "id: 1\nevent: run_done\ndata: {}\n\n"],
  ["application/pdf", "%PDF-binary-content"],
  [
    "application/json",
    JSON.stringify({ code: 0, message: "OK", data: { value: true } }),
  ],
])("leaves %s resource bodies readable", async (contentType, body) => {
  replies.push({ body, contentType, status: 200 });
  const resource = await api.fetchApiResource("/api/resource-body", {
    notifyOnError: false,
  });
  assert.equal(await resource.text(), body);
});
describe.each([
  {
    name: "quiet JSON",
    run: () => api.requestApi("/api/quiet", { notifyOnError: false }),
  },
  {
    name: "quiet upload",
    run: () =>
      api.uploadApi("/api/quiet", new FormData(), { notifyOnError: false }),
  },
  {
    name: "quiet resource",
    run: () => api.fetchApiResource("/api/quiet", { notifyOnError: false }),
  },
  { name: "core JSON", run: () => core.requestApiEnvelope("/api/core") },
  {
    name: "core upload",
    run: () => core.uploadApiEnvelope("/api/core", new FormData()),
  },
  { name: "core resource", run: () => core.fetchApiResponse("/api/core") },
])("$name policy", ({ run }) => {
  it.each([
    {
      kind: "HTTP",
      reply: {
        body: JSON.stringify({
          code: 40002,
          message: "VALIDATION_ERROR",
          data: null,
        }),
        contentType: "application/json",
        status: 422,
      },
    },
    { kind: "network", reply: { kind: "network-error" as const } },
  ])(
    "permits exactly one caller notification for $kind failure",
    async ({ reply }) => {
      replies.push(reply);
      let failure;
      await assert.rejects(run(), (error) => {
        failure = error;
        return assertRequestFailure(error, {
          messageKey: "status" in reply ? "VALIDATION_ERROR" : "REQUEST_FAILED",
          apiCode: "status" in reply ? "VALIDATION_ERROR" : undefined,
          status: "status" in reply ? reply.status : undefined,
          notified: false,
        });
      });
      assert.equal(notifyApiError(failure, "fallback"), true);
      assert.equal(notifyApiError(failure, "duplicate"), false);
      assert.equal(testState.toasts.length, 1);
    },
  );
});
it.each([true, false])(
  "notifies a shared failure once with quietFirst=%s",
  async (quietFirst) => {
    const delayed = enqueueDeferred();
    const runs = Promise.allSettled([
      api.requestApi("/api/shared-policy", {
        cacheTtlMs: 1_000,
        notifyOnError: !quietFirst,
      }),
      api.requestApi("/api/shared-policy", {
        cacheTtlMs: 1_000,
        notifyOnError: quietFirst,
      }),
    ]);
    delayed.resolveJson(
      { code: 40002, message: "VALIDATION_ERROR", data: null },
      422,
    );
    await runs;
    assert.equal(requests.length, 1);
    assert.deepEqual(testState.toasts, ["localized:VALIDATION_ERROR"]);
  },
);
it("deduplicates frozen errors without notifying aborts", () => {
  const frozenFailure = Object.freeze(new Error("read-only error"));
  assert.equal(notifyApiError(frozenFailure, "fallback"), true);
  assert.equal(notifyApiError(frozenFailure, "duplicate"), false);
  assert.deepEqual(testState.toasts, ["fallback"]);
  assert.equal(
    notifyApiError(new DOMException("cancelled", "AbortError")),
    false,
  );
  assert.equal(testState.toasts.length, 1);
});
