import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { defaultMessages as t } from "@/i18n";
import { SetupPage } from "@/components/auth/setup-page";
import {
  validateLoginForm,
  validateSetupForm,
  validateUsernameUpdateForm,
} from "@/lib/auth-validation";
import type { AuthTokenPayload } from "@/lib/auth";

const request = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  requestApi: request,
}));
let auth: typeof import("@/lib/auth");
let session: typeof import("@/lib/auth-session");
let lock: ReturnType<typeof vi.fn>;
let requestTokens: (string | null)[];
const now = Date.parse("2030-01-01T00:00:00Z");
const token = (accessToken: string, username = "owner"): AuthTokenPayload => ({
  username,
  accessToken,
  expiresAt: new Date(now + 3_600_000).toISOString(),
  tokenType: "bearer",
});
const renamePayload = {
  currentPassword: "password1",
  newUsername: " renamed-owner ",
};

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  sessionStorage.clear();
  requestTokens = [];
  request.mockReset().mockImplementation(() => {
    throw new Error("Unexpected request");
  });
  vi.stubGlobal("isSecureContext", true);
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  let tail: Promise<unknown> = Promise.resolve();
  lock = vi.fn((_name, _options, action: () => unknown) => {
    const pending = tail.then(action);
    tail = pending.catch(() => {});
    return pending;
  });
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: { request: lock },
  });
  session = await import("@/lib/auth-session");
  auth = await import("@/lib/auth");
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  Reflect.deleteProperty(navigator, "locks");
});
function save(accessToken: string) {
  const value = token(accessToken);
  session.saveAuthSession(value.username, value.accessToken, value.expiresAt);
}
function respond(...responses: unknown[]) {
  for (const response of responses)
    request.mockImplementationOnce(() => {
      requestTokens.push(session.getAccessToken());
      return Promise.resolve(response);
    });
}
function invalidated(...tokens: string[]) {
  for (const value of tokens)
    expect(session.isTokenLocallyInvalidated(value)).toBe(true);
}

it("loads setup status and persists the created owner's returned identity", async () => {
  const status = { setupRequired: true, githubLoginAvailable: false };
  respond(status, token("created", "created-owner"));
  await expect(auth.getAuthSetupStatus()).resolves.toEqual(status);
  expect(request).toHaveBeenNthCalledWith(1, "/api/auth/setup", {
    auth: false,
    cacheTtlMs: 1000,
    notifyOnError: false,
  });
  const payload = {
    username: "owner",
    password: "password1",
    confirmPassword: "password1",
  };
  await expect(auth.setupAuthOwner(payload)).resolves.toBe("created-owner");
  expect(request).toHaveBeenNthCalledWith(2, "/api/auth/setup", {
    auth: false,
    body: payload,
    method: "POST",
  });
  expect(session.getAuthUsername()).toBe("created-owner");
  expect(session.getAccessToken()).toBe("created");
});

it("serializes refreshes so concurrent callers share one replacement token", async () => {
  save("token-1");
  respond(token("token-2"), token("token-3"));
  await expect(auth.refreshAuthSession()).resolves.toBe(true);
  expect(request).toHaveBeenLastCalledWith("/api/auth/refresh", {
    body: {},
    method: "POST",
  });
  expect(session.getAccessToken()).toBe("token-2");
  await expect(
    Promise.all([auth.refreshAuthSession(), auth.refreshAuthSession()]),
  ).resolves.toEqual([true, true]);
  expect(request).toHaveBeenCalledTimes(2);
  expect(session.getAccessToken()).toBe("token-3");
  invalidated("token-1", "token-2");
  expect(lock).toHaveBeenCalledTimes(3);
  for (const call of lock.mock.calls)
    expect(call.slice(0, 2)).toEqual([
      "reseno-auth-refresh",
      { mode: "exclusive" },
    ]);
});

it("does not refresh without a session or acquire an unnecessary lock", async () => {
  await expect(auth.refreshAuthSession()).resolves.toBe(false);
  expect(request).not.toHaveBeenCalled();
  expect(lock).not.toHaveBeenCalled();
});

it.each([false, true])(
  "ignores a late refresh after logout or replacement login, replacement=%s",
  async (replace) => {
    save("old");
    const refreshed = Promise.withResolvers<AuthTokenPayload>();
    respond(refreshed.promise, token("new-login"));
    const pending = auth.refreshAuthSession();
    await waitFor(() => expect(request).toHaveBeenCalledOnce());
    if (replace) {
      await expect(
        auth.loginWithCredentials(" owner ", "password1"),
      ).resolves.toBe("owner");
      expect(request).toHaveBeenLastCalledWith("/api/auth/login", {
        auth: false,
        body: { username: "owner", password: "password1" },
        method: "POST",
      });
    } else auth.clearAuthSession();
    const storage = localStorage.getItem(session.AUTH_SESSION_KEY);
    const invalidations = sessionStorage.getItem("reseno-invalidated-jwts");
    refreshed.resolve(token("stale-refresh"));
    await expect(pending).resolves.toBe(replace);
    expect(localStorage.getItem(session.AUTH_SESSION_KEY)).toBe(storage);
    expect(sessionStorage.getItem("reseno-invalidated-jwts")).toBe(
      invalidations,
    );
    expect(session.getAccessToken()).toBe(replace ? "new-login" : null);
  },
);

it("renames with the current token and replaces it under an exclusive lock", async () => {
  save("before-rename");
  respond(token("renamed-token", "renamed-owner"));
  await expect(auth.updateAuthUsername(renamePayload)).resolves.toBe(
    "renamed-owner",
  );
  expect(request).toHaveBeenCalledExactlyOnceWith("/api/auth/username", {
    body: { ...renamePayload, newUsername: "renamed-owner" },
    method: "POST",
    notifyOnError: false,
  });
  expect(requestTokens).toEqual(["before-rename"]);
  expect(session.getAuthUsername()).toBe("renamed-owner");
  expect(session.getAccessToken()).toBe("renamed-token");
  invalidated("before-rename");
  expect(lock).toHaveBeenCalledWith(
    "reseno-auth-refresh",
    { mode: "exclusive" },
    expect.any(Function),
  );
});

it("lets a queued rename use the refreshed token", async () => {
  save("before-refresh");
  const refreshed = Promise.withResolvers<AuthTokenPayload>();
  respond(refreshed.promise, token("queued-rename", "queued-owner"));
  const refresh = auth.refreshAuthSession();
  const rename = auth.updateAuthUsername({
    ...renamePayload,
    newUsername: "queued-owner",
  });
  await waitFor(() => expect(request).toHaveBeenCalledOnce());
  expect(request.mock.calls[0][0]).toBe("/api/auth/refresh");
  refreshed.resolve(token("refresh-ahead"));
  await expect(refresh).resolves.toBe(true);
  await expect(rename).resolves.toBe("queued-owner");
  expect(request.mock.calls[1][0]).toBe("/api/auth/username");
  expect(requestTokens).toEqual(["before-refresh", "refresh-ahead"]);
  expect(session.getAccessToken()).toBe("queued-rename");
  invalidated("before-refresh", "refresh-ahead");
});

it("lets a queued refresh adopt a rename without another request", async () => {
  save("before-rename");
  const renamed = Promise.withResolvers<AuthTokenPayload>();
  respond(renamed.promise);
  const rename = auth.updateAuthUsername(renamePayload);
  const refresh = auth.refreshAuthSession();
  await waitFor(() => expect(request).toHaveBeenCalledOnce());
  expect(request.mock.calls[0][0]).toBe("/api/auth/username");
  renamed.resolve(token("rename-ahead", "renamed-owner"));
  await expect(rename).resolves.toBe("renamed-owner");
  await expect(refresh).resolves.toBe(true);
  expect(request).toHaveBeenCalledOnce();
  expect(session.getAccessToken()).toBe("rename-ahead");
  invalidated("before-rename");
});

it("accepts a rename response when its unchanged session expires while waiting", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(now);
  session.saveAuthSession(
    "owner",
    "expiring-rename",
    new Date(now + 1000).toISOString(),
  );
  const renamed = Promise.withResolvers<AuthTokenPayload>();
  respond(renamed.promise);
  const pending = auth.updateAuthUsername(renamePayload);
  await waitFor(() => expect(request).toHaveBeenCalledOnce());
  expect(requestTokens).toEqual(["expiring-rename"]);
  vi.setSystemTime(now + 1000);
  expect(auth.loadAuthSession()).toBe(false);
  renamed.resolve(token("after-expiry", "renamed-owner"));
  await expect(pending).resolves.toBe("renamed-owner");
  expect(auth.loadAuthSession()).toBe(true);
  expect(session.getAccessToken()).toBe("after-expiry");
  invalidated("expiring-rename");
});

it.each([false, true])(
  "rejects a late rename after logout or replacement login, replacement=%s",
  async (replace) => {
    save("pending-rename");
    const renamed = Promise.withResolvers<AuthTokenPayload>();
    respond(renamed.promise, token("new-login"));
    const rejected = expect(
      auth.updateAuthUsername(renamePayload),
    ).rejects.toMatchObject({ name: "AbortError" });
    await waitFor(() => expect(request).toHaveBeenCalledOnce());
    if (replace) await auth.loginWithCredentials("owner", "password1");
    else auth.clearAuthSession();
    const storage = localStorage.getItem(session.AUTH_SESSION_KEY);
    const invalidations = sessionStorage.getItem("reseno-invalidated-jwts");
    renamed.resolve(token("stale-rename", "renamed-owner"));
    await rejected;
    expect(localStorage.getItem(session.AUTH_SESSION_KEY)).toBe(storage);
    expect(sessionStorage.getItem("reseno-invalidated-jwts")).toBe(
      invalidations,
    );
    expect(session.getAccessToken()).toBe(replace ? "new-login" : null);
  },
);

it.each([
  ["owner", "password1", "password1", {}],
  ["ab", "password1", "password1", { username: t.loginUsernameTooShort }],
  ["owner!", "password1", "password1", { username: t.loginUsernameInvalid }],
  ["owner", "password", "password", { password: t.loginPasswordInvalid }],
  [
    "owner",
    "password1",
    "password2",
    { confirmPassword: t.apiMessages.PASSWORD_CONFIRMATION_MISMATCH },
  ],
] as const)(
  "validates owner setup: %s / %s / %s",
  (username, password, confirmation, expected) => {
    expect(validateSetupForm(username, password, confirmation, t)).toEqual(
      expected,
    );
  },
);
it("requires only nonempty credentials during login", () => {
  expect(validateLoginForm("x", "x", t)).toEqual({});
});
it.each([
  ["x", " owner_2 ", {}],
  [
    "",
    "",
    {
      currentPassword: t.loginPasswordRequired,
      newUsername: t.loginUsernameRequired,
    },
  ],
  ["password1", "ab", { newUsername: t.loginUsernameTooShort }],
  ["password1", "owner!", { newUsername: t.loginUsernameInvalid }],
] as const)(
  "validates a username update: %s / %s",
  (password, username, expected) => {
    expect(validateUsernameUpdateForm(password, username, t)).toEqual(expected);
  },
);

it("shows the form heading and clears a confirmation mismatch when the password is edited to match", async () => {
  const submit = vi.fn(async () => ({ ok: true }));
  render(<SetupPage onSubmitCredentials={submit} t={t} />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
    t.setupFormTitle,
  );
  expect(
    screen.getByText(t.brandTitle).closest('[aria-hidden="true"]'),
  ).not.toBeNull();
  expect(screen.getByRole("heading", { level: 1 }).textContent).not.toContain(
    t.brandTitle,
  );
  const header = screen
    .getByRole("heading", { level: 1 })
    .closest('[data-slot="card-header"]')!;
  expect(header.querySelector("svg")).toBeNull();
  expect(header.querySelector('[data-slot="card-description"]')).toBeNull();
  fireEvent.change(screen.getByLabelText(t.loginUsernameLabel), {
    target: { value: " owner " },
  });
  fireEvent.change(screen.getByLabelText(t.loginPasswordLabel), {
    target: { value: "password1" },
  });
  fireEvent.change(screen.getByLabelText(t.setupConfirmPasswordLabel), {
    target: { value: "password2" },
  });
  fireEvent.click(screen.getByRole("button", { name: t.setupSubmit }));
  expect(
    screen.getByText(t.apiMessages.PASSWORD_CONFIRMATION_MISMATCH),
  ).not.toBeNull();
  expect(submit).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(t.loginPasswordLabel), {
    target: { value: "password2" },
  });
  expect(
    screen.queryByText(t.apiMessages.PASSWORD_CONFIRMATION_MISMATCH),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: t.setupSubmit }));
  await waitFor(() =>
    expect(submit).toHaveBeenCalledExactlyOnceWith({
      username: "owner",
      password: "password2",
      confirmPassword: "password2",
    }),
  );
});
