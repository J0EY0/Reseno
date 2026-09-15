import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { defaultMessages as t } from "@/i18n";
import {
  authorizeGitHubBinding,
  OAUTH_TAB_RECEIVED,
  OAUTH_TAB_RESULT,
  type OAuthProgress,
} from "@/lib/auth-oauth-tab";
import type { ApiRequestOptions } from "@/types/api";

const io = vi.hoisted(() => ({ request: vi.fn(), save: vi.fn() }));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  requestApi: io.request,
}));
vi.mock("@/lib/auth-session", () => ({ saveAuthSession: io.save }));
const completion = { provider: "github", intent: "bind", auth: null };
const authorization = { authorizationUrl: "https://github.com/authorize" };
const setupAuthorization = {
  registrationUrl: "https://github.com/settings/apps/new",
  manifest: { public: false },
};
const token = {
  username: "owner",
  accessToken: "server-only-jwt",
  expiresAt: "2099-01-01",
  tokenType: "bearer",
};
const origin = window.location.origin;
const deadline = 600_000;
let popup: {
  closed: boolean;
  close: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
  postMessage: ReturnType<typeof vi.fn>;
};
let blocked: boolean;
let forms: HTMLFormElement[];
let focusHistory: string[];
let progress: (OAuthProgress | null)[];
let requests: { route: string; options: ApiRequestOptions }[];
let start: Promise<unknown> | undefined;
let exchange: Promise<unknown> | undefined;
let result: unknown;

beforeEach(() => {
  vi.useFakeTimers();
  blocked = false;
  forms = [];
  focusHistory = [];
  progress = [];
  requests = [];
  start = exchange = undefined;
  result = completion;
  popup = {
    closed: false,
    close: vi.fn(() => {
      popup.closed = true;
    }),
    focus: vi.fn(() => {
      focusHistory.push("tab");
    }),
    postMessage: vi.fn(),
  };
  vi.spyOn(window, "open").mockImplementation(() =>
    blocked ? null : (popup as unknown as Window),
  );
  vi.spyOn(window, "focus").mockImplementation(() => {
    focusHistory.push("parent");
  });
  vi.spyOn(window, "addEventListener");
  vi.spyOn(window, "removeEventListener");
  vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(function (
    this: HTMLFormElement,
  ) {
    forms.push(this);
  });
  io.request.mockImplementation(
    async (route: string, options: ApiRequestOptions) => {
      requests.push({ route, options });
      if (route.endsWith("/complete")) return exchange ?? result;
      return (
        start ?? (route.endsWith("/setup") ? setupAuthorization : authorization)
      );
    },
  );
});
afterEach(() => {
  expect(io.save).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
  const added = vi
    .mocked(window.addEventListener)
    .mock.calls.filter(([type]) => type === "message");
  const removed = vi
    .mocked(window.removeEventListener)
    .mock.calls.filter(([type]) => type === "message");
  expect(removed.map(([, listener]) => listener)).toEqual(
    added.map(([, listener]) => listener),
  );
  expect(document.querySelector("form")).toBeNull();
  vi.useRealTimers();
});
function run(
  options: Partial<Parameters<typeof authorizeGitHubBinding>[0]> = {},
) {
  return authorizeGitHubBinding({
    signal: new AbortController().signal,
    onComplete: async () => {},
    onProgress: (value) => progress.push(value),
    t,
    ...options,
  });
}
async function flush() {
  await vi.advanceTimersByTimeAsync(0);
}
function send(
  data: unknown,
  eventOrigin = origin,
  source: MessageEventSource | null = popup as unknown as Window,
) {
  window.dispatchEvent(
    new MessageEvent("message", { data, origin: eventOrigin, source }),
  );
}
function sendCode() {
  send({ type: OAUTH_TAB_RESULT, code: "one-use-code", intent: "bind" });
}
function reopen() {
  const state = progress.at(-1);
  expect(state?.stage).toBe("blocked");
  if (state?.stage !== "blocked") throw new Error("Expected blocked popup");
  return state.open;
}
async function end(
  kind: "abort" | "close" | "timeout" | "cancel",
  controller: AbortController,
) {
  if (kind === "abort") controller.abort();
  if (kind === "close") {
    popup.closed = true;
    await vi.advanceTimersByTimeAsync(250);
  }
  if (kind === "timeout") await vi.advanceTimersByTimeAsync(deadline);
  if (kind === "cancel")
    send({ type: OAUTH_TAB_RESULT, error: "OAUTH_CANCELLED" });
}
function rejectedBy(
  pending: Promise<void>,
  kind: "abort" | "close" | "timeout" | "cancel",
) {
  return kind === "abort"
    ? expect(pending).rejects.toMatchObject({ name: "AbortError" })
    : expect(pending).rejects.toThrow(
        kind === "close"
          ? t.oauthTabClosed
          : kind === "timeout"
            ? t.oauthTabTimeout
            : t.apiMessages.OAUTH_CANCELLED,
      );
}

it.each([false, true])(
  "opens only after authorization is ready and focuses once, setup=%s",
  async (setup) => {
    const ready = Promise.withResolvers<unknown>();
    start = ready.promise;
    const pending = run({ setup });
    expect(window.open).not.toHaveBeenCalled();
    expect(progress).toEqual([]);
    send(
      { type: OAUTH_TAB_RESULT, code: "premature", intent: "bind" },
      origin,
      null,
    );
    expect(requests).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(150);
    expect(progress).toEqual([{ stage: "preparing" }]);
    ready.resolve(setup ? setupAuthorization : authorization);
    await flush();
    expect(window.open).toHaveBeenCalledExactlyOnceWith(
      setup ? "" : authorization.authorizationUrl,
      expect.stringMatching(/^reseno-github-/),
    );
    expect(forms).toHaveLength(setup ? 1 : 0);
    expect(focusHistory).toEqual(["tab"]);
    expect(progress.at(-1)).toEqual({ stage: "waiting" });
    await vi.advanceTimersByTimeAsync(500);
    expect(focusHistory).toEqual(["tab"]);
    sendCode();
    await pending;
    expect(focusHistory).toEqual(["tab", "parent"]);
    expect(progress.at(-1)).toBeNull();
  },
);

it("ignores untrusted messages, acknowledges and exchanges a valid code only once", async () => {
  const controller = new AbortController();
  const onComplete = vi.fn(async () => {});
  const pending = run({ signal: controller.signal, onComplete });
  await flush();
  const valid = {
    type: OAUTH_TAB_RESULT,
    code: "one-use-code",
    intent: "bind",
  };
  send(valid, "https://evil.test");
  send(valid, origin, null);
  for (const data of [
    { ...valid, intent: "login" },
    { type: OAUTH_TAB_RESULT, token },
    { ...valid, code: "" },
    { ...valid, code: "x".repeat(129) },
  ])
    send(data);
  expect(requests).toHaveLength(1);
  send(valid);
  send(valid);
  await pending;
  expect(requests).toHaveLength(2);
  expect(requests[1]).toMatchObject({
    route: "/api/auth/oauth/complete",
    options: {
      auth: false,
      body: { code: "one-use-code" },
      credentials: "include",
      method: "POST",
      notifyOnError: false,
    },
  });
  expect(onComplete).toHaveBeenCalledExactlyOnceWith(
    { provider: "github", intent: "bind" },
    expect.any(AbortSignal),
  );
  expect(popup.postMessage).toHaveBeenCalledExactlyOnceWith(
    { type: OAUTH_TAB_RECEIVED },
    origin,
  );
  expect(popup.close).toHaveBeenCalledOnce();
  controller.abort();
  send(valid);
  await vi.advanceTimersByTimeAsync(deadline);
  expect(requests).toHaveLength(2);
  expect(onComplete).toHaveBeenCalledOnce();
  expect(popup.close).toHaveBeenCalledOnce();
});

it.each(["login", "bind"])(
  "rejects an authoritative %s completion carrying a login token",
  async (intent) => {
    result = { provider: "github", intent, auth: token };
    const rejected = expect(run()).rejects.toThrow(
      t.apiMessages.OAUTH_INVALID_STATE,
    );
    await flush();
    sendCode();
    await rejected;
  },
);

it("does nothing when the caller has already aborted", async () => {
  const controller = new AbortController();
  controller.abort();
  await rejectedBy(run({ signal: controller.signal }), "abort");
  expect(requests).toEqual([]);
  expect(progress).toEqual([]);
  expect(window.open).not.toHaveBeenCalled();
});

it.each([false, true])(
  "retries a blocked popup with the same authorization and deadline, setup=%s",
  async (setup) => {
    blocked = true;
    const timeout = vi.spyOn(window, "setTimeout");
    const pending = run({ setup });
    await flush();
    const open = reopen();
    expect(forms).toEqual([]);
    expect(focusHistory).toEqual([]);
    await vi.advanceTimersByTimeAsync(500);
    send(
      { type: OAUTH_TAB_RESULT, code: "unopened", intent: "bind" },
      origin,
      null,
    );
    expect(progress.at(-1)?.stage).toBe("blocked");
    open();
    expect(window.open).toHaveBeenCalledTimes(2);
    expect(requests).toHaveLength(1);
    expect(forms).toEqual([]);
    blocked = false;
    open();
    expect(window.open).toHaveBeenCalledTimes(3);
    const opened = vi.mocked(window.open).mock.calls;
    expect(opened[2]).toEqual(opened[0]);
    expect(focusHistory).toEqual(["tab"]);
    expect(forms).toHaveLength(setup ? 1 : 0);
    expect(progress.at(-1)).toEqual({ stage: "waiting" });
    expect(
      timeout.mock.calls.filter(([, delay]) => delay === deadline),
    ).toHaveLength(1);
    expect(requests).toHaveLength(1);
    open();
    expect(window.open).toHaveBeenCalledTimes(3);
    sendCode();
    await pending;
    open();
    expect(window.open).toHaveBeenCalledTimes(3);
    expect(progress.at(-1)).toBeNull();
  },
);

it.each(["abort", "timeout"] as const)(
  "disables a blocked callback after %s",
  async (kind) => {
    blocked = true;
    const controller = new AbortController();
    const rejected = rejectedBy(run({ signal: controller.signal }), kind);
    await flush();
    const open = reopen();
    await end(kind, controller);
    await rejected;
    blocked = false;
    open();
    expect(window.open).toHaveBeenCalledOnce();
    expect(popup.close).not.toHaveBeenCalled();
    expect(focusHistory).toEqual([]);
    expect(requests).toHaveLength(1);
    expect(progress.at(-1)).toBeNull();
  },
);

it.each(["abort", "close", "timeout", "cancel"] as const)(
  "cleans up after %s and suppresses late authorization",
  async (kind) => {
    const ready = Promise.withResolvers<unknown>();
    start = ready.promise;
    const controller = new AbortController();
    const rejected = rejectedBy(run({ signal: controller.signal }), kind);
    const opened = kind === "close" || kind === "cancel";
    if (opened) {
      ready.resolve(authorization);
      await flush();
    }
    await end(kind, controller);
    await rejected;
    ready.resolve(authorization);
    await flush();
    expect(window.open).toHaveBeenCalledTimes(opened ? 1 : 0);
    expect(focusHistory).toEqual(opened ? ["tab", "parent"] : []);
    expect(requests[0].options.signal?.aborted).toBe(true);
    expect(progress.at(-1)).toBeNull();
  },
);

it.each(["close", "timeout"] as const)(
  "aborts the pending exchange when the tab ends by %s",
  async (kind) => {
    const exchanged = Promise.withResolvers<unknown>();
    exchange = exchanged.promise;
    const controller = new AbortController();
    const onComplete = vi.fn(async () => {});
    const rejected = rejectedBy(
      run({ signal: controller.signal, onComplete }),
      kind,
    );
    await flush();
    sendCode();
    await flush();
    expect(requests).toHaveLength(2);
    await end(kind, controller);
    await rejected;
    expect(requests[1].options.signal?.aborted).toBe(true);
    exchanged.resolve(completion);
    await flush();
    expect(onComplete).not.toHaveBeenCalled();
  },
);

it.each(["close", "timeout"] as const)(
  "aborts the awaiting destination on %s before it can update",
  async (kind) => {
    const prepared = Promise.withResolvers<void>();
    const controller = new AbortController();
    const updated = vi.fn();
    const onComplete = vi.fn(async (_result, signal: AbortSignal) => {
      expect(signal.aborted).toBe(false);
      await prepared.promise;
      signal.throwIfAborted();
      updated();
    });
    const rejected = rejectedBy(
      run({ signal: controller.signal, onComplete }),
      kind,
    );
    await flush();
    sendCode();
    await flush();
    expect(onComplete).toHaveBeenCalledOnce();
    await end(kind, controller);
    await rejected;
    expect(onComplete.mock.calls[0][1].aborted).toBe(true);
    prepared.resolve();
    await flush();
    expect(updated).not.toHaveBeenCalled();
  },
);

it("submits a real hidden manifest form to the exact named popup and removes it", async () => {
  const pending = run({ setup: true });
  await flush();
  expect(requests[0]).toMatchObject({
    route: "/api/auth/oauth/github/setup",
    options: {
      auth: true,
      body: { publicBaseUrl: origin },
      credentials: "include",
      method: "POST",
      notifyOnError: false,
    },
  });
  expect(forms).toHaveLength(1);
  const form = forms[0];
  expect(form.action).toBe(setupAuthorization.registrationUrl);
  expect(form.method).toBe("post");
  expect(form.target).toBe(vi.mocked(window.open).mock.calls[0][1]);
  expect(form.target).not.toBe("_self");
  expect(form.hidden).toBe(true);
  const input = form.querySelector("input")!;
  expect(input.type).toBe("hidden");
  expect(input.name).toBe("manifest");
  expect(JSON.parse(input.value)).toEqual(setupAuthorization.manifest);
  expect(form.isConnected).toBe(false);
  sendCode();
  await pending;
});

it("never submits a late setup form after cancellation", async () => {
  const ready = Promise.withResolvers<unknown>();
  start = ready.promise;
  const controller = new AbortController();
  const rejected = rejectedBy(
    run({ setup: true, signal: controller.signal }),
    "abort",
  );
  controller.abort();
  await rejected;
  ready.resolve(setupAuthorization);
  await flush();
  expect(forms).toEqual([]);
  expect(window.open).not.toHaveBeenCalled();
  expect(focusHistory).toEqual([]);
});
