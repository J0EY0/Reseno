import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resolveApiMessage } from "@/lib/api-message";

const requestApi = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  requestApi,
}));

const now = Date.parse("2030-01-01T00:00:00Z");
const expiresAt = new Date(now + 3_600_000).toISOString();
const invalidatedKey = "reseno-invalidated-jwts";
let session: typeof import("@/lib/auth-session");
let lock: ReturnType<typeof vi.fn>;

beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.setSystemTime(now);
  localStorage.clear();
  sessionStorage.clear();
  requestApi.mockReset();
  vi.stubGlobal("isSecureContext", true);
  lock = vi.fn((_name, _options, action: () => unknown) => action());
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: { request: lock },
  });
  session = await import("@/lib/auth-session");
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  Reflect.deleteProperty(navigator, "locks");
});

it("reads unchanged sessions without writes or repeated parsing", () => {
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  session.saveAuthSession("owner", "token-1", expiresAt);
  const parse = vi.spyOn(JSON, "parse");
  expect(session.getAccessToken()).toBe("token-1");
  const parsed = parse.mock.calls.length;
  for (let index = 0; index < 20; index++) {
    expect(session.getAccessToken()).toBe("token-1");
    expect(session.loadAuthSession()).toBe(true);
  }
  expect(parse).toHaveBeenCalledTimes(parsed);
  expect(setItem).toHaveBeenCalledTimes(1);
  expect(setItem.mock.instances[0]).toBe(localStorage);
});

it("publishes same-page updates after persisting the trimmed username and token", () => {
  const observed: unknown[] = [];
  const listener = () =>
    observed.push({
      username: session.getAuthUsername(),
      token: session.getAccessToken(),
      stored: JSON.parse(localStorage.getItem(session.AUTH_SESSION_KEY)!),
    });
  window.addEventListener(session.AUTH_SESSION_UPDATED_EVENT, listener);
  try {
    for (const [username, token] of [
      [" owner ", "token-1"],
      [" renamed ", "token-2"],
    ]) {
      session.saveAuthSession(username, token, expiresAt);
    }
    expect(observed).toEqual([
      {
        username: "owner",
        token: "token-1",
        stored: { username: "owner", accessToken: "token-1", expiresAt },
      },
      {
        username: "renamed",
        token: "token-2",
        stored: { username: "renamed", accessToken: "token-2", expiresAt },
      },
    ]);
    session.recordInvalidatedToken("token-2");
    expect(session.getAuthUsername()).toBeNull();
    session.saveAuthSession("owner", "token-3", expiresAt);
    session.clearAuthSession();
    expect(session.getAuthUsername()).toBeNull();
  } finally {
    window.removeEventListener(session.AUTH_SESSION_UPDATED_EVENT, listener);
  }
});

it("observes another module instance replacing, clearing, corrupting and restoring shared storage", async () => {
  session.saveAuthSession("owner", "token-1", expiresAt);
  expect(session.getAccessToken()).toBe("token-1");
  vi.resetModules();
  const otherTab = await import("@/lib/auth-session");
  otherTab.saveAuthSession("renamed", "token-2", expiresAt);
  expect(session.getAccessToken()).toBe("token-2");
  expect(session.getAuthUsername()).toBe("renamed");
  otherTab.clearAuthSession();
  expect(session.getAccessToken()).toBeNull();
  localStorage.setItem(session.AUTH_SESSION_KEY, "not-json");
  expect(session.getAccessToken()).toBeNull();
  otherTab.saveAuthSession("owner", "token-3", expiresAt);
  expect(session.getAccessToken()).toBe("token-3");
});

it("expires a cached session at the exact expiry time", () => {
  session.saveAuthSession("owner", "token-1", expiresAt);
  expect(session.getAccessToken()).toBe("token-1");
  vi.setSystemTime(now + 3_600_000);
  expect(session.getAccessToken()).toBeNull();
  expect(session.getAuthUsername()).toBeNull();
});

it("persists invalidations across reloads and prunes expired entries only when recording", async () => {
  session.recordInvalidatedToken("token-1");
  vi.resetModules();
  session = await import("@/lib/auth-session");
  expect(session.isTokenLocallyInvalidated("token-1")).toBe(true);
  const write = vi.spyOn(Storage.prototype, "setItem");
  vi.setSystemTime(now + 4 * 3_600_000);
  expect(session.isTokenLocallyInvalidated("token-1")).toBe(false);
  expect(write).not.toHaveBeenCalled();
  session.recordInvalidatedToken("token-2");
  expect(JSON.parse(sessionStorage.getItem(invalidatedKey)!)).toEqual({
    "token-2": now + 8 * 3_600_000,
  });
  expect(write).toHaveBeenCalledTimes(1);
});

describe.each(["quota", "blocked"])(
  "unavailable invalidation storage: %s",
  (failure) => {
    it("retains invalidations in memory without preventing a later login", () => {
      if (failure === "quota") {
        const original = Storage.prototype.setItem;
        vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
          this: Storage,
          key,
          value,
        ) {
          if (this === sessionStorage)
            throw new DOMException("Full", "QuotaExceededError");
          original.call(this, key, value);
        });
      } else {
        vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
          throw new DOMException("Blocked", "SecurityError");
        });
      }
      session.saveAuthSession("owner", "token-1", expiresAt);
      expect(session.getAccessToken()).toBe("token-1");
      expect(() => session.recordInvalidatedToken("token-1")).not.toThrow();
      expect(session.isTokenLocallyInvalidated("token-1")).toBe(true);
      expect(session.getAccessToken()).toBeNull();
      session.saveAuthSession("owner", "token-2", expiresAt);
      expect(session.getAccessToken()).toBe("token-2");
    });
  },
);

it.each(["not-json", "null", "[]", '{"token-1":"2099"}'])(
  "ignores malformed invalidations: %s",
  (raw) => {
    sessionStorage.setItem(invalidatedKey, raw);
    session.saveAuthSession("owner", "token-1", expiresAt);
    expect(session.getAccessToken()).toBe("token-1");
  },
);

it("refreshes under the exclusive Web Lock despite a full session storage", async () => {
  const original = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
    this: Storage,
    key,
    value,
  ) {
    if (this === sessionStorage)
      throw new DOMException("Full", "QuotaExceededError");
    original.call(this, key, value);
  });
  session.saveAuthSession("owner", "token-1", expiresAt);
  requestApi.mockResolvedValue({
    username: "owner",
    accessToken: "token-2",
    expiresAt,
    tokenType: "bearer",
  });
  const { refreshAuthSession } = await import("@/lib/auth");
  await expect(refreshAuthSession()).resolves.toBe(true);
  expect(session.getAccessToken()).toBe("token-2");
  expect(session.isTokenLocallyInvalidated("token-1")).toBe(true);
  expect(requestApi).toHaveBeenCalledWith("/api/auth/refresh", {
    body: {},
    method: "POST",
  });
  expect(lock).toHaveBeenCalledWith(
    "reseno-auth-refresh",
    { mode: "exclusive" },
    expect.any(Function),
  );
});

it.each(["AUTH_SECURE_CONTEXT_REQUIRED", "AUTH_BROWSER_UNSUPPORTED"] as const)(
  "rejects %s before an unlocked request",
  async (code) => {
    session.saveAuthSession("owner", "token-1", expiresAt);
    if (code === "AUTH_SECURE_CONTEXT_REQUIRED")
      vi.stubGlobal("isSecureContext", false);
    else
      Object.defineProperty(navigator, "locks", {
        configurable: true,
        value: undefined,
      });
    const { refreshAuthSession } = await import("@/lib/auth");
    await expect(refreshAuthSession()).rejects.toThrow(resolveApiMessage(code));
    expect(session.getAccessToken()).toBe("token-1");
    expect(requestApi).not.toHaveBeenCalled();
    expect(lock).not.toHaveBeenCalled();
  },
);

it.each([false, true])(
  "handles a late 401 after token expiry, replacement=%s",
  async (replace) => {
    const apiAuth = await import("@/lib/api-auth");
    const invalidated = vi.fn();
    const event = vi.fn();
    window.addEventListener(apiAuth.AUTH_SESSION_INVALIDATED_EVENT, event);
    try {
      session.saveAuthSession("owner", "request-token", expiresAt);
      const headers = apiAuth.getAuthHeaders({}, undefined, invalidated)!;
      expect(headers.get("Authorization")).toBe("Bearer request-token");
      vi.setSystemTime(now + 3_600_000);
      if (replace)
        session.saveAuthSession(
          "owner",
          "new-token",
          new Date(now + 7_200_000).toISOString(),
        );
      await apiAuth.handleUnauthorizedResponse(
        { code: 40001, message: "UNAUTHORIZED_REQUEST", data: null },
        headers,
        "/api/resumes",
        invalidated,
        401,
      );
      expect(invalidated).toHaveBeenCalledTimes(replace ? 0 : 1);
      expect(event).toHaveBeenCalledTimes(replace ? 0 : 1);
      expect(session.getAccessToken()).toBe(replace ? "new-token" : null);
      expect(lock).toHaveBeenCalledWith(
        "reseno-auth-refresh",
        { mode: "shared" },
        expect.any(Function),
      );
    } finally {
      window.removeEventListener(apiAuth.AUTH_SESSION_INVALIDATED_EVENT, event);
    }
  },
);
