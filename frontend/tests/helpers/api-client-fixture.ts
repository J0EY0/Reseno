import assert from "node:assert/strict";
import axios, {
  type AxiosAdapter,
  type AxiosProgressEvent,
  type GenericAbortSignal,
} from "axios";
import { afterEach, beforeEach, expect, vi } from "vitest";

type Reply =
  | { body: string; contentType: string; status: number; headers?: HeadersInit }
  | { kind: "network-error" };

interface RecordedRequest {
  body: unknown;
  credentials?: RequestCredentials | boolean;
  headers: Headers;
  method: string;
  onUploadProgress?: (event: AxiosProgressEvent) => void;
  signal?: AbortSignal | GenericAbortSignal | null;
  timeout?: number;
  transport: "fetch" | "axios";
  url: string;
}

const testState = vi.hoisted(() => ({
  clearedAuthCount: 0,
  invalidatedTokens: new Set<string>(),
  lockRequests: [] as { name: string; options: LockOptions }[],
  refreshPending: null as Promise<void> | null,
  invalidations: [] as string[],
  token: "token-a" as string | null,
  toasts: [] as string[],
}));

export { testState };

vi.mock("@/lib/api-message", () => ({
  resolveApiMessage: (key: string) => `localized:${key}`,
}));
vi.mock("@/lib/auth-session", () => ({
  AUTH_REFRESH_LOCK_NAME: "reseno-auth-refresh",
  clearAuthSession: () => {
    testState.clearedAuthCount += 1;
    testState.token = null;
  },
  getAccessToken: () => testState.token,
  isTokenLocallyInvalidated: (token: string) =>
    testState.invalidatedTokens.has(token),
}));
vi.mock("sonner", () => ({
  toast: { error: (message: string) => testState.toasts.push(message) },
}));

export let api: typeof import("@/lib/api-client");
export let core: typeof import("@/lib/api-request-core");
export let notifyApiError: typeof import("@/lib/api-error-notifier").notifyApiError;
export const replies: (Reply | Promise<Reply>)[] = [];
export const requests: RecordedRequest[] = [];
let unqueuedRequests = 0;

export function enqueueJson(payload: unknown, status = 200) {
  replies.push({
    body: JSON.stringify(payload),
    contentType: "application/json",
    status,
  });
}

export function enqueueEnvelope(data: unknown, status = 200) {
  enqueueJson({ code: 0, data, message: "OK" }, status);
}

export function enqueueNetworkError() {
  replies.push({ kind: "network-error" });
}

export function enqueueDeferred() {
  let resolve!: (reply: Reply) => void;
  replies.push(new Promise<Reply>((next) => (resolve = next)));
  return {
    resolveEnvelope(data: unknown, status = 200) {
      this.resolveJson({ code: 0, data, message: "OK" }, status);
    },
    resolveJson(payload: unknown, status = 200) {
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
  if (!queued) unqueuedRequests += 1;
  assert.ok(queued, "A request was issued without a queued response.");
  return queued;
}

const fetchAdapter: typeof fetch = async (url, init = {}) => {
  if (init.signal?.aborted) {
    throw new DOMException("The operation was aborted.", "AbortError");
  }
  requests.push({
    body: init.body,
    credentials: init.credentials,
    headers: new Headers(init.headers),
    method: init.method ?? "GET",
    signal: init.signal,
    transport: "fetch",
    url: String(url),
  });
  const reply = await takeReply();
  if ("kind" in reply) throw new TypeError("Synthetic network failure.");
  return new Response(reply.body, {
    headers: { ...reply.headers, "Content-Type": reply.contentType },
    status: reply.status,
  });
};

const axiosAdapter: AxiosAdapter = async (config) => {
  requests.push({
    body: config.data,
    credentials: config.withCredentials,
    headers: new Headers(config.headers.toJSON() as Record<string, string>),
    method: String(config.method ?? "get").toUpperCase(),
    onUploadProgress: config.onUploadProgress,
    signal: config.signal,
    timeout: config.timeout,
    transport: "axios",
    url: String(config.url),
  });
  const reply = await takeReply();
  if ("kind" in reply) {
    throw new axios.AxiosError(
      "Synthetic network failure.",
      axios.AxiosError.ERR_NETWORK,
      config,
    );
  }
  config.onUploadProgress?.({
    loaded: 4,
    total: 10,
    bytes: 4,
    lengthComputable: true,
  });
  const response = {
    config,
    data: reply.body,
    headers: { "Content-Type": reply.contentType },
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
};

let originalAxiosAdapter: typeof axios.defaults.adapter;
const assignLocation = vi.fn(() => {
  assert.fail("Authentication failures must not reload the document.");
});

beforeEach(async () => {
  vi.resetModules();
  vi.stubEnv("VITE_API_BASE_URL", "");
  requests.length = 0;
  replies.length = 0;
  unqueuedRequests = 0;
  testState.clearedAuthCount = 0;
  testState.invalidatedTokens.clear();
  testState.lockRequests.length = 0;
  testState.refreshPending = null;
  testState.invalidations.length = 0;
  testState.token = "token-a";
  testState.toasts.length = 0;
  vi.stubGlobal("window", {
    clearTimeout,
    setTimeout,
    isSecureContext: true,
    dispatchEvent(event: Event) {
      testState.invalidations.push(event.type);
      return true;
    },
    location: { pathname: "/resume", assign: assignLocation },
  });
  vi.stubGlobal("navigator", {
    locks: {
      async request(
        name: string,
        options: LockOptions,
        callback: () => unknown,
      ) {
        testState.lockRequests.push({ name, options });
        await testState.refreshPending;
        return callback();
      },
    },
  });
  vi.stubGlobal("fetch", vi.fn(fetchAdapter));
  originalAxiosAdapter = axios.defaults.adapter;
  axios.defaults.adapter = axiosAdapter;
  api = await import("@/lib/api-client");
  core = await import("@/lib/api-request-core");
  ({ notifyApiError } = await import("@/lib/api-error-notifier"));
});

afterEach(() => {
  try {
    expect(replies, "Every queued response must be consumed.").toHaveLength(0);
    expect(unqueuedRequests, "Every request must have a queued response.").toBe(
      0,
    );
    expect(assignLocation).not.toHaveBeenCalled();
  } finally {
    api?.clearApiCache();
    axios.defaults.adapter = originalAxiosAdapter;
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  }
});

export function assertRequestFailure(
  error: unknown,
  options: {
    messageKey?: string;
    status?: number;
    apiCode?: string;
    notified?: boolean;
  } = {},
) {
  assert.ok(error instanceof Error);
  assert.equal(
    error.message,
    `localized:${options.messageKey ?? "REQUEST_FAILED"}`,
  );
  assert.equal(api.getApiErrorStatus(error), options.status);
  assert.equal(
    api.isApiErrorCode(error, options.apiCode ?? ""),
    Boolean(options.apiCode),
  );
  assert.equal(testState.toasts.length > 0, options.notified ?? true);
  return true;
}

export async function waitForRequestCount(expected: number) {
  await vi.waitFor(() => expect(requests).toHaveLength(expected), {
    interval: 1,
  });
}

export const unauthorizedPayload = {
  code: 40001,
  data: null,
  message: "UNAUTHORIZED_REQUEST",
};
