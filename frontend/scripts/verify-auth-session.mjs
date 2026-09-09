import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { evaluateTypeScript } from "./typescript-module.mjs";

const source = await readFile(
  new URL("../src/lib/auth-session.ts", import.meta.url),
  "utf8",
);
const invalidatedKey = "reseno-invalidated-jwts";
const expiresAt = "2099-01-01T00:00:00Z";

function createStorage() {
  const values = new Map();
  return {
    values,
    writes: 0,
    writeError: null,
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      this.writes += 1;
      if (this.writeError) throw this.writeError;
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

function fixture({
  localStorage = createStorage(),
  sessionStorage = createStorage(),
  storageError,
} = {}) {
  let now = Date.parse("2026-09-08T00:00:00Z");
  let parseCount = 0;
  class Clock extends Date {
    static now() {
      return now;
    }
  }
  const window = { localStorage };
  Object.defineProperty(window, "sessionStorage", {
    get() {
      if (storageError) throw storageError;
      return sessionStorage;
    },
  });
  const auth = evaluateTypeScript(source, {
    globals: {
      window,
      Date: Clock,
      JSON: {
        parse(value) {
          parseCount += 1;
          return JSON.parse(value);
        },
        stringify: JSON.stringify,
      },
    },
  });
  return {
    auth,
    window,
    localStorage,
    sessionStorage,
    get parseCount() {
      return parseCount;
    },
    advance(ms) {
      now += ms;
    },
  };
}

test("token reads never write storage and reuse parsed unchanged sessions", () => {
  const f = fixture();
  f.auth.saveAuthSession("owner", "token-1", expiresAt);
  assert.equal(f.auth.getAccessToken(), "token-1");
  const parseCount = f.parseCount;
  for (let i = 0; i < 20; i += 1) {
    assert.equal(f.auth.getAccessToken(), "token-1");
    assert.equal(f.auth.loadAuthSession(), true);
  }
  assert.equal(f.sessionStorage.writes, 0);
  assert.equal(f.localStorage.writes, 1);
  assert.equal(f.parseCount, parseCount);
});

test("cached sessions immediately observe another tab's token replacement and logout", () => {
  const f = fixture();
  f.auth.saveAuthSession("owner", "token-1", expiresAt);
  assert.equal(f.auth.getAccessToken(), "token-1");
  const secondTab = fixture({ localStorage: f.localStorage });
  secondTab.auth.saveAuthSession("owner", "token-2", expiresAt);
  assert.equal(f.auth.getAccessToken(), "token-2");
  secondTab.auth.clearAuthSession();
  assert.equal(f.auth.loadAuthSession(), false);
  f.localStorage.values.set(f.auth.AUTH_SESSION_KEY, "not-json");
  assert.equal(f.auth.getAccessToken(), null);
  secondTab.auth.saveAuthSession("owner", "token-3", expiresAt);
  assert.equal(f.auth.getAccessToken(), "token-3");
});

test("cache hits still reject expired sessions", () => {
  const f = fixture();
  f.auth.saveAuthSession("owner", "token-1", "2026-09-08T01:00:00Z");
  assert.equal(f.auth.getAccessToken(), "token-1");
  f.advance(60 * 60 * 1000);
  assert.equal(f.auth.getAccessToken(), null);
});

test("invalidations survive reload, expire on reads, and prune on the next write", () => {
  const f = fixture();
  f.auth.recordInvalidatedToken("token-1");
  assert.equal(f.sessionStorage.writes, 1);
  assert.equal(f.auth.isTokenLocallyInvalidated("token-1"), true);
  const reloaded = fixture({ sessionStorage: f.sessionStorage });
  assert.equal(reloaded.auth.isTokenLocallyInvalidated("token-1"), true);
  reloaded.advance(4 * 60 * 60 * 1000);
  assert.equal(reloaded.auth.isTokenLocallyInvalidated("token-1"), false);
  assert.equal(f.sessionStorage.writes, 1);
  reloaded.auth.recordInvalidatedToken("token-2");
  assert.deepEqual(
    Object.keys(JSON.parse(f.sessionStorage.values.get(invalidatedKey))),
    ["token-2"],
  );
  assert.equal(f.sessionStorage.writes, 2);
});

test("quota errors cannot invalidate a valid login or interrupt refreshed token persistence", () => {
  const f = fixture();
  f.sessionStorage.writeError = new DOMException(
    "Storage is full",
    "QuotaExceededError",
  );
  f.auth.saveAuthSession("owner", "token-1", expiresAt);
  assert.equal(f.auth.loadAuthSession(), true);
  assert.doesNotThrow(() => f.auth.recordInvalidatedToken("token-1"));
  assert.equal(f.auth.isTokenLocallyInvalidated("token-1"), true);
  assert.equal(f.auth.getAccessToken(), null);
  f.auth.saveAuthSession("owner", "token-2", expiresAt);
  assert.equal(f.auth.getAccessToken(), "token-2");
});

test("blocked sessionStorage access preserves current-page invalidation and refreshed sessions", () => {
  const f = fixture({
    storageError: new DOMException("Storage is disabled", "SecurityError"),
  });
  f.auth.saveAuthSession("owner", "token-1", expiresAt);
  assert.equal(f.auth.loadAuthSession(), true);
  assert.doesNotThrow(() => f.auth.recordInvalidatedToken("token-1"));
  assert.equal(f.auth.isTokenLocallyInvalidated("token-1"), true);
  f.auth.saveAuthSession("owner", "token-2", expiresAt);
  assert.equal(f.auth.getAccessToken(), "token-2");
});

test("malformed invalidation data cannot reject valid sessions", () => {
  for (const raw of ["not-json", "null", "[]", '{"token-1":"2099"}']) {
    const f = fixture();
    f.sessionStorage.values.set(invalidatedKey, raw);
    f.auth.saveAuthSession("owner", "token-1", expiresAt);
    assert.equal(f.auth.getAccessToken(), "token-1");
  }
});

const [authSource, environmentSource] = await Promise.all([
  readFile(new URL("../src/lib/auth.ts", import.meta.url), "utf8"),
  readFile(new URL("../src/lib/auth-environment.ts", import.meta.url), "utf8"),
]);

function refreshFixture({ secure = true, locks = true } = {}) {
  const f = fixture();
  const requests = [];
  const lockCalls = [];
  f.window.isSecureContext = secure;
  const environment = evaluateTypeScript(environmentSource, {
    globals: {
      window: f.window,
      navigator: {
        locks: locks
          ? {
              request(name, options, action) {
                lockCalls.push({ name, ...options });
                return action();
              },
            }
          : undefined,
      },
    },
    imports: {
      "@/lib/auth-session": f.auth,
      "@/lib/api-message": { resolveApiMessage: (key) => key },
    },
  });
  const auth = evaluateTypeScript(authSource, {
    imports: {
      "@/lib/auth-session": f.auth,
      "@/lib/auth-environment": environment,
      "@/lib/api-client": {
        apiRoutes: { authRefresh: "/api/auth/refresh" },
        async requestApi(route) {
          requests.push(route);
          return {
            username: "owner",
            accessToken: "refreshed-token",
            expiresAt,
          };
        },
      },
    },
  });
  return {
    ...f,
    refresh: auth.refreshAuthSession,
    requests,
    lockCalls,
    environment,
  };
}

test("the real refresh flow persists its new token when invalidation storage is full", async () => {
  const f = refreshFixture();
  f.sessionStorage.writeError = new DOMException(
    "Storage is full",
    "QuotaExceededError",
  );
  f.auth.saveAuthSession("owner", "previous-token", expiresAt);
  assert.equal(await f.refresh(), true);
  assert.equal(f.auth.getAccessToken(), "refreshed-token");
  assert.equal(f.auth.isTokenLocallyInvalidated("previous-token"), true);
  assert.deepEqual(f.requests, ["/api/auth/refresh"]);
  assert.deepEqual(f.lockCalls, [
    { name: "reseno-auth-refresh", mode: "exclusive" },
  ]);
});

for (const [options, error] of [
  [{ secure: false }, "AUTH_SECURE_CONTEXT_REQUIRED"],
  [{ locks: false }, "AUTH_BROWSER_UNSUPPORTED"],
]) {
  test(`refresh reports ${error} before issuing an unlocked request`, async () => {
    const f = refreshFixture(options);
    f.auth.saveAuthSession("owner", "previous-token", expiresAt);
    await assert.rejects(f.refresh(), { message: error });
    assert.equal(f.auth.getAccessToken(), "previous-token");
    assert.deepEqual(f.requests, []);
    assert.deepEqual(f.lockCalls, []);
  });
}

test("a response after local expiry invalidates the session unless a new valid token replaced it", async () => {
  const apiAuthSource = await readFile(
    new URL("../src/lib/api-auth.ts", import.meta.url),
    "utf8",
  );
  for (const replaced of [false, true]) {
    const f = refreshFixture();
    const events = [];
    f.window.dispatchEvent = (event) => {
      events.push(event.type);
      return true;
    };
    const apiAuth = evaluateTypeScript(apiAuthSource, {
      globals: { window: f.window, Event, Headers },
      imports: {
        "@/lib/auth-session": f.auth,
        "@/lib/auth-environment": f.environment,
      },
    });
    f.auth.saveAuthSession("owner", "request-token", "2026-09-08T01:00:00Z");
    let invalidations = 0;
    const headers = apiAuth.getAuthHeaders(
      {},
      undefined,
      () => invalidations++,
    );
    assert.equal(headers.get("Authorization"), "Bearer request-token");
    f.advance(60 * 60 * 1000);
    assert.equal(f.auth.getAccessToken(), null);
    if (replaced) f.auth.saveAuthSession("owner", "new-token", expiresAt);
    await apiAuth.handleUnauthorizedResponse(
      { code: 40001, message: "UNAUTHORIZED_REQUEST", data: null },
      headers,
      "/api/protected",
      () => invalidations++,
      401,
    );
    assert.equal(invalidations, replaced ? 0 : 1);
    assert.deepEqual(
      events,
      replaced ? [] : ["reseno:auth-session-invalidated"],
    );
    assert.equal(f.auth.getAccessToken(), replaced ? "new-token" : null);
    assert.deepEqual(f.lockCalls, [
      { name: "reseno-auth-refresh", mode: "shared" },
    ]);
  }
});
