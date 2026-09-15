// @vitest-environment node

import assert from "node:assert/strict";
import { it, vi } from "vitest";
import {
  api,
  enqueueEnvelope,
  enqueueJson,
  enqueueDeferred,
  enqueueNetworkError,
  requests,
  replies,
  testState,
  waitForRequestCount,
} from "./helpers/api-client-fixture";

import type { ApiRequestOptions } from "@/types/api";
async function readCached(
  route: string,
  searchParams?: ApiRequestOptions["searchParams"],
) {
  const response = { route, revision: requests.length + 1 };
  const previousRequestCount = requests.length;
  enqueueEnvelope(response);
  const result = await api.requestApi<{ route: string; revision: number }>(
    route,
    {
      cacheTtlMs: 60_000,
      searchParams,
    },
  );
  if (requests.length === previousRequestCount) replies.pop();
  return result;
}

it("shares pending GETs and invalidates them after a mutation", async () => {
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
  await api.requestApi("/api/cached", { body: {}, method: "POST" });
  enqueueEnvelope({ version: 2 });
  assert.deepEqual(await api.requestApi("/api/cached", { cacheTtlMs: 1_000 }), {
    version: 2,
  });
  assert.equal(requests.length, 3);
});

it("clears exact path segments without matching tokens, queries or similar prefixes", async () => {
  testState.token = "token-containing-/api/resumes/r1";
  const prefixCases: [string, ApiRequestOptions["searchParams"], boolean][] = [
    ["/api/resumes/r1", undefined, true],
    ["/api/resumes/r1/versions", undefined, true],
    ["/api/resumes/r10", undefined, false],
    ["/api/resumes-archive/r1", undefined, false],
    ["/api/templates", { returnTo: "/api/resumes/r1" }, false],
  ];
  const prefixValues = await Promise.all(
    prefixCases.map(([route, params]) => readCached(route, params)),
  );
  api.clearApiCache("/api/resumes/r1/");
  for (const [
    index,
    [route, params, shouldInvalidate],
  ] of prefixCases.entries()) {
    const current = await readCached(route, params);
    assert.equal(
      current.revision !== prefixValues[index].revision,
      shouldInvalidate,
      `Prefix invalidation must respect path segments for ${route}.`,
    );
  }
});
const cacheRoutes = [
  "/api/resumes/r1/versions",
  "/api/templates/t1",
  "/api/model-configs",
  "/api/auth/setup",
  "/api/workspace/pages/resumes",
  "/api/workspace/pages/trash",
  "/api/workspace/pages/templates",
  "/api/workspace/pages/resume-editor",
  "/api/workspace/pages/models",
  "/api/workspace/pages/settings",
];
const resumeDependencies = [0, 4, 5];
const templateDependencies = [0, 1, 4, 5, 6, 7];
it.each([
  ["/api/resumes/r1", "PUT", resumeDependencies],
  ["/api/resumes/r1/trash", "POST", resumeDependencies],
  ["/api/templates/t1/trash", "POST", templateDependencies],
  ["/api/model-configs/config1", "DELETE", [2, 7, 8, 9]],
  ["/api/workspace/user-settings", "PUT", [4, 5, 6, 7, 8, 9]],
  ["/api/workspace/default-template", "PUT", [0, 4, 5, 6, 7]],
  [
    "/api/agent/resumes/r1/session/messages/m1/draft",
    "PATCH",
    resumeDependencies,
  ],
  ["/api/auth/oauth/complete", "POST", [3]],
  ["/api/exports/resume-pdf", "POST", []],
  ["/api/model-providers/discover-models", "POST", []],
] satisfies [string, NonNullable<ApiRequestOptions["method"]>, number[]][])(
  "%s %s invalidates only its dependent resources",
  async (route, method, affected) => {
    const previous = [];
    for (const cachedRoute of cacheRoutes)
      previous.push(await readCached(cachedRoute));
    enqueueEnvelope({ saved: true });
    await api.requestApi(route, { method, body: {} });
    for (const [index, cachedRoute] of cacheRoutes.entries()) {
      const current = await readCached(cachedRoute);
      assert.equal(
        current.revision !== previous[index].revision,
        affected.includes(index),
        `${method} ${route} must invalidate only dependent resources: ${cachedRoute}.`,
      );
    }
  },
);
it.each(["/api/import/resume", "/api/import/templates"])(
  "%s uploads preserve resume version caches",
  async (route) => {
    const previous = await readCached("/api/resumes/r1/versions");
    enqueueEnvelope({ resumes: [], templates: [] });
    await api.uploadApi(route, new FormData());
    assert.deepEqual(await readCached("/api/resumes/r1/versions"), previous);
  },
);
it("preserves cached reads after a failed mutation", async () => {
  const cachedBeforeFailure = await readCached("/api/resumes/r1/versions");
  enqueueJson({ code: 40000, data: null, message: "VERSION_CONFLICT" }, 409);
  await assert.rejects(
    api.requestApi("/api/resumes/r1", { method: "PUT", notifyOnError: false }),
  );
  assert.deepEqual(
    await readCached("/api/resumes/r1/versions"),
    cachedBeforeFailure,
  );
});

it("does not restore an invalidated cache when an older request resolves", async () => {
  const staleRead = enqueueDeferred();
  const oldVersions = api.requestApi("/api/resumes/r1/versions", {
    cacheTtlMs: 60_000,
  });
  await waitForRequestCount(1);
  enqueueEnvelope({ saved: true });
  await api.requestApi("/api/resumes/r1", { method: "PUT", body: {} });
  const currentVersions = await readCached("/api/resumes/r1/versions");
  staleRead.resolveEnvelope({ revision: "old" });
  await oldVersions;
  assert.deepEqual(
    await readCached("/api/resumes/r1/versions"),
    currentVersions,
  );
  assert.equal(
    requests.length,
    3,
    "A late read must not restore an invalidated cache entry.",
  );
});

it("invalidates absolute resource writes while retaining unrelated templates", async () => {
  const beforeResourceWrite = await readCached("/api/resumes/r1/versions");
  const unrelatedTemplate = await readCached("/api/templates/t1");
  enqueueEnvelope({ saved: true });
  await api.fetchApiResource("https://api.example/api/resumes/r1", {
    method: "PATCH",
  });
  assert.notDeepEqual(
    await readCached("/api/resumes/r1/versions"),
    beforeResourceWrite,
  );
  assert.deepEqual(await readCached("/api/templates/t1"), unrelatedTemplate);
});

it.each([
  "https://api.example",
  "https://api.example/proxy",
  "https://api.example/api",
])("normalizes canonical and absolute invalidation under %s", async (base) => {
  vi.stubEnv("VITE_API_BASE_URL", base);
  const routes = [
    "/api/resumes/r1/versions",
    "/api/workspace/pages/resumes",
    "/api/templates/t1",
  ];
  let previous = await Promise.all(routes.map((route) => readCached(route)));
  assert.deepEqual(
    requests.map((request) => request.url),
    routes.map((route) => `${base}${route}`),
  );
  for (const absolute of [false, true]) {
    enqueueEnvelope({ saved: true });
    if (absolute) {
      await api.fetchApiResource(`${base}/api/resumes/r1`, {
        method: "PATCH",
      });
    } else {
      await api.requestApi("/api/resumes/r1", { method: "PUT", body: {} });
    }
    assert.equal(requests.at(-1)?.url, `${base}/api/resumes/r1`);
    const current = await Promise.all(routes.map((route) => readCached(route)));
    for (const [index, route] of routes.entries()) {
      assert.equal(
        current[index].revision !== previous[index].revision,
        index < 2,
        `${absolute ? "Absolute" : "Canonical"} write under ${base}: ${route}`,
      );
    }
    previous = current;
  }
  const beforePrefixClear = previous[0];
  api.clearApiCache(`${base}/api/resumes/r1`);
  assert.notDeepEqual(
    await readCached(routes[0]),
    beforePrefixClear,
    `An absolute cache prefix must match canonical reads under ${base}.`,
  );
});
it("retries a failed cached GET instead of retaining its rejection", async () => {
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
});

it("keeps cancelable GET ownership separate despite a cache TTL", async () => {
  enqueueEnvelope({ owner: 1 });
  enqueueEnvelope({ owner: 2 });
  const ownerA = new AbortController();
  const ownerB = new AbortController();
  await Promise.all([
    api.requestApi("/api/owned", { cacheTtlMs: 1_000, signal: ownerA.signal }),
    api.requestApi("/api/owned", { cacheTtlMs: 1_000, signal: ownerB.signal }),
  ]);
  assert.equal(
    requests.length,
    2,
    "Cancelable GETs must never share a promise.",
  );
});

it("notifies only once for a shared rejected GET", async () => {
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
});

it("keeps a newer cache entry when the expired request later rejects", async () => {
  let now = Date.now();
  vi.spyOn(Date, "now").mockImplementation(() => now);
  const previous = enqueueDeferred();
  const previousFailure = assert.rejects(
    api.requestApi("/api/cache-owner", {
      cacheTtlMs: 5,
      notifyOnError: false,
    }),
    /localized:VALIDATION_ERROR/,
  );
  await waitForRequestCount(1);
  now += 10;
  const current = enqueueDeferred();
  const currentRequest = api.requestApi("/api/cache-owner", {
    cacheTtlMs: 100,
  });
  await waitForRequestCount(2);
  previous.resolveJson(
    { code: 40002, message: "VALIDATION_ERROR", data: null },
    422,
  );
  await previousFailure;
  const joinedRequests = Promise.all([
    currentRequest,
    api.requestApi("/api/cache-owner", { cacheTtlMs: 100 }),
  ]);
  current.resolveEnvelope({ current: true });
  assert.deepEqual(await joinedRequests, [
    { current: true },
    { current: true },
  ]);
  assert.equal(requests.length, 2);
});
