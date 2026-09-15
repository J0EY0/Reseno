// @vitest-environment node

import assert from "node:assert/strict";
import { describe, it, vi } from "vitest";
import {
  api,
  assertRequestFailure,
  enqueueDeferred,
  enqueueJson,
  requests,
  replies,
  testState,
  unauthorizedPayload,
  waitForRequestCount,
} from "./helpers/api-client-fixture";

const transports = [
  { name: "JSON", run: () => api.requestApi("/api/protected") },
  { name: "upload", run: () => api.uploadApi("/api/upload", new FormData()) },
  { name: "resource", run: () => api.fetchApiResource("/api/resource") },
];

describe.each(transports)("$name authorization", ({ name, run }) => {
  describe.each([401, 200])("unauthorized envelope at HTTP %i", (status) => {
    it("preserves a replacement token when an earlier request fails", async () => {
      const lateFailure = enqueueDeferred();
      const pendingFailure = run();
      await waitForRequestCount(1);
      testState.token = "token-b";
      lateFailure.resolveJson(unauthorizedPayload, status);
      await assert.rejects(pendingFailure, (error) =>
        assertRequestFailure(error, {
          messageKey: "UNAUTHORIZED_REQUEST",
          apiCode: "UNAUTHORIZED_REQUEST",
          status,
          notified: true,
        }),
      );
      assert.equal(testState.token, "token-b");
      assert.equal(testState.clearedAuthCount, 0);
      assert.deepEqual(testState.invalidations, []);
      assert.deepEqual(testState.toasts, ["localized:UNAUTHORIZED_REQUEST"]);
      assert.equal(requests.length, 1);
    });

    it("invalidates the current session without an error toast", async () => {
      enqueueJson(unauthorizedPayload, status);
      await assert.rejects(run(), /localized:UNAUTHORIZED_REQUEST/);
      assert.deepEqual(testState.toasts, []);
      assert.equal(testState.clearedAuthCount, 1);
      assert.deepEqual(testState.invalidations, [
        "reseno:auth-session-invalidated",
      ]);
    });

    it("waits for the refresh lock before invalidating a token", async () => {
      let finishRefresh!: () => void;
      testState.refreshPending = new Promise<void>((resolve) => {
        finishRefresh = resolve;
      });
      const refreshWindowFailure = enqueueDeferred();
      const waitingFailure = run();
      await waitForRequestCount(1);
      refreshWindowFailure.resolveJson(unauthorizedPayload, status);
      await vi.waitFor(() => assert.equal(testState.lockRequests.length, 1));
      assert.deepEqual(testState.lockRequests, [
        { name: "reseno-auth-refresh", options: { mode: "shared" } },
      ]);
      assert.equal(testState.clearedAuthCount, 0);
      testState.token = "token-b";
      finishRefresh();
      await assert.rejects(waitingFailure, /localized:UNAUTHORIZED_REQUEST/);
      assert.equal(testState.token, "token-b");
      assert.deepEqual(testState.invalidations, []);
      assert.deepEqual(testState.toasts, ["localized:UNAUTHORIZED_REQUEST"]);
    });
  });
  it("rejects a missing token before using a transport", async () => {
    testState.token = null;
    await assert.rejects(run(), (error) =>
      assertRequestFailure(error, {
        messageKey: "UNAUTHORIZED_REQUEST",
        apiCode: "UNAUTHORIZED_REQUEST",
        notified: false,
      }),
    );
    assert.equal(requests.length, 0);
    assert.deepEqual(testState.toasts, []);
    assert.deepEqual(testState.invalidations, [
      "reseno:auth-session-invalidated",
    ]);
  });

  it("handles a late unauthorized failure after logout without a toast", async () => {
    const failure = enqueueDeferred();
    const pending = run();
    await waitForRequestCount(1);
    testState.token = null;
    failure.resolveJson(unauthorizedPayload, 401);
    await assert.rejects(pending, (error) =>
      assertRequestFailure(error, {
        messageKey: "UNAUTHORIZED_REQUEST",
        apiCode: "UNAUTHORIZED_REQUEST",
        status: 401,
        notified: false,
      }),
    );
    assert.deepEqual(testState.invalidations, [
      "reseno:auth-session-invalidated",
    ]);
    assert.deepEqual(testState.toasts, []);
    assert.equal(testState.token, null);
  });
  it("invalidates the session on a plain HTTP 401 without a toast", async () => {
    replies.push({
      body: "Unauthorized",
      contentType: "text/plain",
      status: 401,
    });
    await assert.rejects(
      name === "JSON"
        ? api.requestApi("/api/plain-401", { notifyOnError: false })
        : name === "upload"
          ? api.uploadApi("/api/plain-401", new FormData(), {
              notifyOnError: false,
            })
          : api.fetchApiResource("/api/plain-401", { notifyOnError: false }),
      (error) => assertRequestFailure(error, { status: 401, notified: false }),
    );
    assert.equal(testState.clearedAuthCount, 1);
    assert.deepEqual(testState.invalidations, [
      "reseno:auth-session-invalidated",
    ]);
  });
});

it.each([
  {
    name: "JSON",
    run: () =>
      api.requestApi("/api/auth/login", { auth: false, method: "POST" }),
  },
  {
    name: "upload",
    run: () => api.uploadApi("/api/upload", new FormData(), { auth: false }),
  },
])("$name anonymous failure preserves a concurrent login", async ({ run }) => {
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
  assert.deepEqual(testState.invalidations, []);
  assert.deepEqual(testState.lockRequests, []);
});
it.each(["authRefresh", "authUsername"] as const)(
  "%s does not wait on its own refresh lock",
  async (routeKey) => {
    const route = api.apiRoutes[routeKey];
    testState.refreshPending = new Promise(() => {});
    enqueueJson(unauthorizedPayload, 401);
    await assert.rejects(
      api.requestApi(route, { method: "POST", body: {} }),
      /localized:UNAUTHORIZED_REQUEST/,
    );
    assert.equal(testState.clearedAuthCount, 1);
    assert.deepEqual(testState.lockRequests, []);
  },
  1_000,
);
it("rejects a missing token even when notifications are explicitly disabled", async () => {
  testState.token = null;
  await assert.rejects(
    api.requestApi("/api/protected", { notifyOnError: false }),
    (error) =>
      assertRequestFailure(error, {
        messageKey: "UNAUTHORIZED_REQUEST",
        apiCode: "UNAUTHORIZED_REQUEST",
        notified: false,
      }),
  );
  assert.equal(requests.length, 0);
  assert.equal(testState.clearedAuthCount, 1);
  assert.deepEqual(testState.invalidations, [
    "reseno:auth-session-invalidated",
  ]);
  assert.deepEqual(testState.toasts, []);
});

it("reports invalid credentials without invalidating an anonymous session", async () => {
  testState.token = null;
  enqueueJson({ code: 40001, message: "INVALID_CREDENTIALS", data: null }, 401);
  await assert.rejects(
    api.requestApi(api.apiRoutes.authLogin, {
      auth: false,
      method: "POST",
      body: {},
    }),
    (error) =>
      assertRequestFailure(error, {
        messageKey: "INVALID_CREDENTIALS",
        apiCode: "INVALID_CREDENTIALS",
        status: 401,
      }),
  );
  assert.deepEqual(testState.toasts, ["localized:INVALID_CREDENTIALS"]);
  assert.deepEqual(testState.invalidations, []);
});
