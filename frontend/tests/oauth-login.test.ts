// @vitest-environment node

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getMessagesSync } from "@/i18n";
import {
  completeGitHubLogin,
  parseOAuthLoginCallback,
  redirectToGitHubLogin,
  resolveOAuthLoginError,
} from "@/lib/auth-oauth-login";
import type { AuthTokenPayload } from "@/lib/auth";

const io = vi.hoisted(() => ({
  request: vi.fn(),
  save: vi.fn(),
  clear: vi.fn(),
  token: null as string | null,
}));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  requestApi: io.request,
}));
vi.mock("@/lib/auth-session", () => ({
  saveAuthSession: io.save,
  getAccessToken: () => io.token,
  clearAuthSession: io.clear,
}));
const t = getMessagesSync("en");
const token: AuthTokenPayload = {
  username: "owner",
  accessToken: "login-jwt",
  expiresAt: "2099-01-01",
  tokenType: "bearer",
};
const completion = { provider: "github", intent: "login", auth: token };
const assign = vi.fn();
const open = vi.fn();
const focus = vi.fn();

beforeEach(() => {
  io.request.mockReset().mockResolvedValue(completion);
  io.token = null;
  io.save.mockImplementation((_username, accessToken: string) => {
    io.token = accessToken;
  });
  io.clear.mockImplementation(() => {
    io.token = null;
  });
  vi.stubGlobal("window", { location: { assign }, open, focus });
});
afterEach(() => {
  expect(open).not.toHaveBeenCalled();
  expect(focus).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});

it.each([
  ["#section", null] as const,
  ["#oauth_code=one-use-code", { code: "one-use-code" }] as const,
  ["#oauth_error=OAUTH_CANCELLED", { error: "OAUTH_CANCELLED" }] as const,
  ...[
    "#oauth_code=",
    "#oauth_error=",
    "#oauth_code=a&oauth_code=b",
    "#oauth_error=a&oauth_error=b",
    "#oauth_code=a&oauth_error=b",
    `#oauth_code=${"x".repeat(129)}`,
    `#oauth_error=${"x".repeat(129)}`,
  ].map((hash) => [hash, { error: "OAUTH_INVALID_STATE" }] as const),
])("parses the bounded, single-use callback %s", (hash, expected) => {
  expect(parseOAuthLoginCallback(hash as string)).toEqual(expected);
});

it.each([
  "__proto__",
  "constructor",
  "toString",
  "hasOwnProperty",
  "wrong",
  "untrusted text",
])("rejects inherited, non-string or unknown error messages: %s", (code) => {
  const messages = { ...t, apiMessages: { ...t.apiMessages, wrong: {} } };
  expect(resolveOAuthLoginError(code, messages as typeof t, "failed")).toBe(
    "failed",
  );
  expect(resolveOAuthLoginError("OAUTH_CANCELLED", t)).toBe(
    t.apiMessages.OAUTH_CANCELLED,
  );
});

it("waits for the final authorization URL before navigating the current tab", async () => {
  const authorization = Promise.withResolvers<{ authorizationUrl: string }>();
  io.request.mockReturnValue(authorization.promise);
  const controller = new AbortController();
  const pending = redirectToGitHubLogin(controller.signal);
  expect(assign).not.toHaveBeenCalled();
  expect(io.request).toHaveBeenCalledWith("/api/auth/oauth/github/login", {
    auth: false,
    body: {},
    credentials: "include",
    method: "POST",
    notifyOnError: false,
    signal: controller.signal,
  });
  authorization.resolve({
    authorizationUrl: "https://github.com/login/oauth/authorize?state=ready",
  });
  await pending;
  expect(assign).toHaveBeenCalledExactlyOnceWith(
    "https://github.com/login/oauth/authorize?state=ready",
  );
});

it.each([false, true])(
  "does not navigate after cancellation, already aborted=%s",
  async (alreadyAborted) => {
    const authorization = Promise.withResolvers<{ authorizationUrl: string }>();
    io.request.mockReturnValue(authorization.promise);
    const controller = new AbortController();
    if (alreadyAborted) controller.abort();
    const rejected = expect(
      redirectToGitHubLogin(controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    authorization.resolve({ authorizationUrl: "https://github.com/late" });
    await rejected;
    expect(assign).not.toHaveBeenCalled();
    expect(io.request).toHaveBeenCalledTimes(alreadyAborted ? 0 : 1);
  },
);

it("exchanges once, persists the token, and awaits the destination commit", async () => {
  const commit = Promise.withResolvers<void>();
  const controller = new AbortController();
  const onComplete = vi.fn(async (signal: AbortSignal) => {
    expect(signal).toBe(controller.signal);
    expect(io.token).toBe("login-jwt");
    await commit.promise;
  });
  let finished = false;
  const pending = completeGitHubLogin(
    "one-use-code",
    controller.signal,
    onComplete,
  ).then(() => {
    finished = true;
  });
  await vi.waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
  expect(finished).toBe(false);
  expect(io.request).toHaveBeenCalledExactlyOnceWith(
    "/api/auth/oauth/complete",
    {
      auth: false,
      body: { code: "one-use-code" },
      credentials: "include",
      method: "POST",
      notifyOnError: false,
      signal: controller.signal,
    },
  );
  expect(io.save).toHaveBeenCalledExactlyOnceWith(
    "owner",
    "login-jwt",
    "2099-01-01",
  );
  expect(assign).not.toHaveBeenCalled();
  commit.resolve();
  await pending;
  expect(finished).toBe(true);
});

it("ignores a late exchange response after cancellation", async () => {
  const exchange = Promise.withResolvers<typeof completion>();
  io.request.mockReturnValue(exchange.promise);
  const controller = new AbortController();
  const onComplete = vi.fn();
  const rejected = expect(
    completeGitHubLogin("code", controller.signal, onComplete),
  ).rejects.toMatchObject({ name: "AbortError" });
  controller.abort();
  exchange.resolve(completion);
  await rejected;
  expect(io.save).not.toHaveBeenCalled();
  expect(onComplete).not.toHaveBeenCalled();
});

it.each([false, true])(
  "cancels only its own accepted token while awaiting the destination, replacement=%s",
  async (replace) => {
    const commit = Promise.withResolvers<void>();
    const controller = new AbortController();
    const onComplete = vi.fn(async (signal: AbortSignal) => {
      await commit.promise;
      signal.throwIfAborted();
    });
    const rejected = expect(
      completeGitHubLogin("code", controller.signal, onComplete),
    ).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
    controller.abort();
    if (replace) io.token = "newer-login";
    commit.resolve();
    await rejected;
    expect(io.clear).toHaveBeenCalledTimes(replace ? 0 : 1);
    expect(io.token).toBe(replace ? "newer-login" : null);
  },
);

it.each([
  { provider: "github", intent: "bind", auth: null },
  { provider: "github", intent: "login", auth: null },
])("rejects an incompatible completion: $intent", async (result) => {
  io.request.mockResolvedValue(result);
  await expect(
    completeGitHubLogin("code", new AbortController().signal, vi.fn()),
  ).rejects.toThrow("OAUTH_INVALID_STATE");
  expect(io.save).not.toHaveBeenCalled();
});
