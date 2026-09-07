import { toast } from "sonner";

import type { ApiRequestOptions, ApiResponse } from "@/types/api";
import {
  APP_CODE_UNAUTHORIZED,
  AUTH_REFRESH_ROUTE,
  getAuthHeaders,
  handleUnauthorizedResponse,
  redirectToLogin,
} from "@/lib/api-auth";
import { getAccessToken } from "@/lib/auth-session";
import { resolveApiMessage } from "@/lib/api-message";

interface ApiCacheEntry {
  expiresAt: number;
  promise: Promise<unknown>;
}

// GET responses are cached briefly and invalidated by every mutation. This
// keeps route changes and PDF render reloads fast without serving stale writes.
const getRequestCache = new Map<string, ApiCacheEntry>();
const API_ERROR_NOTIFIED = Symbol("apiErrorNotified");

type ResenoApiError = Error & {
  [API_ERROR_NOTIFIED]?: true;
  apiCode?: string;
  status?: number;
};

const DEFAULT_ACCEPT_HEADER = "application/json, text/plain, */*";

export const apiRoutes = {
  authSetup: "/api/auth/setup",
  authLogin: "/api/auth/login",
  authRefresh: AUTH_REFRESH_ROUTE,
  authPassword: "/api/auth/password",
  workspaceDefaultTemplate: "/api/workspace/default-template",
  workspaceUserSettings: "/api/workspace/user-settings",
  resumes: "/api/resumes",
  resume: (resumeId: string) => `/api/resumes/${resumeId}`,
  resumeDuplicate: (resumeId: string) =>
    `/api/resumes/${resumeId}/duplicate`,
  resumeTrash: (resumeId: string) => `/api/resumes/${resumeId}/trash`,
  resumeRestore: (resumeId: string) => `/api/resumes/${resumeId}/restore`,
  resumeVersions: (resumeId: string) => `/api/resumes/${resumeId}/versions`,
  resumeVersion: (resumeId: string, versionId: string) =>
    `/api/resumes/${resumeId}/versions/${versionId}`,
  templates: "/api/templates",
  template: (templateId: string) => `/api/templates/${templateId}`,
  templateTrash: (templateId: string) => `/api/templates/${templateId}/trash`,
  templateRestore: (templateId: string) =>
    `/api/templates/${templateId}/restore`,
  modelConfigs: "/api/model-configs",
  modelProviders: "/api/model-providers",
  modelProviderDiscovery: "/api/model-providers/discover-models",
  agentResumeSession: (resumeId: string) =>
    `/api/agent/resumes/${encodeURIComponent(resumeId)}/session`,
  agentResumeRun: (resumeId: string) =>
    `/api/agent/resumes/${encodeURIComponent(resumeId)}/run`,
  agentRun: (runId: string) =>
    `/api/agent/runs/${encodeURIComponent(runId)}`,
  agentRunEvents: (runId: string) =>
    `/api/agent/runs/${encodeURIComponent(runId)}/events`,
  agentAttachments: "/api/agent/attachments",
  agentAttachment: (resumeId: string, attachmentId: string) =>
    `/api/agent/resumes/${encodeURIComponent(resumeId)}/attachments/${encodeURIComponent(attachmentId)}`,
  agentChat: "/api/agent/chat",
  resumePdfExport: "/api/exports/resume-pdf",
  resumeImagesExport: "/api/exports/resume-images",
  resumeImport: "/api/import/resume",
  templateImport: "/api/import/templates",
  sectionRegistry: "/api/section-registry",
  resumeImportLexicon: "/api/resume-import-lexicon",
} as const;

function buildSearchParams(
  values: ApiRequestOptions["searchParams"],
) {
  if (!values) {
    return "";
  }

  const params = new URLSearchParams();

  Object.entries(values).forEach(([key, value]) => {
    if (value === null || typeof value === "undefined") {
      return;
    }

    params.set(key, String(value));
  });

  const query = params.toString();
  return query ? `?${query}` : "";
}

function createRequestCacheKey(route: string, options: ApiRequestOptions) {
  return `${options.method ?? "GET"} ${resolveApiUrl(route, options)} ${getAccessToken() ?? ""}`;
}

export function clearApiCache(routePrefix?: string) {
  if (!routePrefix) {
    getRequestCache.clear();
    return;
  }

  for (const key of getRequestCache.keys()) {
    if (key.includes(routePrefix)) {
      getRequestCache.delete(key);
    }
  }
}

export function resolveApiUrl(
  route: string,
  options: Pick<ApiRequestOptions, "searchParams"> = {},
) {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;
  const query = buildSearchParams(options.searchParams);

  if (apiBaseUrl?.trim()) {
    return `${apiBaseUrl.replace(/\/$/, "")}${route}${query}`;
  }

  return `${route}${query}`;
}

function isApiResponse<T>(value: unknown): value is ApiResponse<T> {
  if (!value || typeof value !== "object") {
    return false;
  }

  return (
    "code" in value &&
    "message" in value &&
    "data" in value
  );
}

function markApiErrorNotified(error: Error) {
  (error as ResenoApiError)[API_ERROR_NOTIFIED] = true;
  return error as ResenoApiError;
}

function isApiErrorNotified(error: unknown) {
  return Boolean(
    error &&
      typeof error === "object" &&
      API_ERROR_NOTIFIED in error,
  );
}

export function isApiErrorToastShown(error: unknown) {
  return isApiErrorNotified(error);
}

export function isApiErrorCode(error: unknown, code: string) {
  return Boolean(
    error &&
      typeof error === "object" &&
      "apiCode" in error &&
      error.apiCode === code,
  );
}

export function getApiErrorStatus(error: unknown) {
  if (
    !error ||
    typeof error !== "object" ||
    !("status" in error) ||
    typeof error.status !== "number"
  ) {
    return undefined;
  }

  return error.status;
}

export function isAbortError(error: unknown) {
  return Boolean(
    error &&
      typeof error === "object" &&
      (("__CANCEL__" in error && Boolean(error.__CANCEL__)) ||
        ("name" in error &&
          (error.name === "AbortError" || error.name === "CanceledError"))),
  );
}

function notifyApiError(message: string) {
  if (typeof window === "undefined") {
    return;
  }

  toast.error(message, {
    closeButton: true,
  });
}

function notifyApiErrorOnce(error: unknown) {
  if (isAbortError(error) || isApiErrorNotified(error)) {
    return;
  }

  const apiError =
    error instanceof Error
      ? markApiErrorNotified(error)
      : markApiErrorNotified(
          createApiError("REQUEST_FAILED", {}, false),
        );
  notifyApiError(apiError.message);
}

function createApiError(
  messageKey: string,
  metadata: Pick<ResenoApiError, "apiCode" | "status"> = {},
  notifyOnError = true,
) {
  const message = resolveApiMessage(messageKey);
  const error = new Error(message) as ResenoApiError;

  error.apiCode = metadata.apiCode;
  error.status = metadata.status;
  if (notifyOnError) {
    markApiErrorNotified(error);
    notifyApiError(message);
  }

  return error;
}

function createPayloadApiError(
  payload: ApiResponse<unknown>,
  status?: number,
  notifyOnError = true,
) {
  return createApiError(
    payload.message,
    {
      apiCode: payload.message,
      status,
    },
    notifyOnError,
  );
}

function unwrapApiResponse<T>(
  payload: unknown,
  options: Pick<ApiRequestOptions, "notifyOnError"> = {},
) {
  const notifyOnError = options.notifyOnError !== false;

  if (!isApiResponse<T>(payload)) {
    throw createApiError("INVALID_API_RESPONSE", {}, notifyOnError);
  }

  if (payload.code !== 0) {
    if (payload.code === APP_CODE_UNAUTHORIZED) {
      redirectToLogin(clearApiCache);
    }
    throw createPayloadApiError(payload, undefined, notifyOnError);
  }

  return payload.data;
}

function getPayloadDetailCode(payload: unknown) {
  const detail =
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    payload.detail &&
    typeof payload.detail === "object"
      ? payload.detail
      : null;

  return detail && "code" in detail && typeof detail.code === "string"
    ? detail.code
    : null;
}

function createHttpResponseError(
  payload: unknown,
  status: number | undefined,
  notifyOnError: boolean,
) {
  if (isApiResponse<unknown>(payload)) {
    return createPayloadApiError(payload, status, notifyOnError);
  }

  const code = getPayloadDetailCode(payload);
  if (code) {
    return createApiError(
      code,
      { apiCode: code, status },
      notifyOnError,
    );
  }

  return createApiError("REQUEST_FAILED", { status }, notifyOnError);
}

async function readJsonPayload(response: Response) {
  const body = await response.text();
  if (!body) {
    return body;
  }

  try {
    return JSON.parse(body) as unknown;
  } catch {
    return body;
  }
}

function createJsonRequestBody(body: unknown) {
  if (typeof body === "undefined") {
    return undefined;
  }

  if (typeof body === "string") {
    try {
      JSON.parse(body);
      return body;
    } catch {
      return JSON.stringify(body);
    }
  }

  return JSON.stringify(body);
}

async function fetchApiEnvelope(
  route: string,
  options: ApiRequestOptions,
  method: NonNullable<ApiRequestOptions["method"]>,
) {
  const baseHeaders = new Headers();
  baseHeaders.set("Accept", DEFAULT_ACCEPT_HEADER);
  if (options.body) {
    baseHeaders.set("Content-Type", "application/json");
  }

  const headers = getAuthHeaders(options, baseHeaders, clearApiCache);
  if (!headers) {
    throw createApiError("AUTHENTICATION_REQUIRED", {}, false);
  }

  let response: Response;
  try {
    response = await fetch(resolveApiUrl(route, options), {
      body: createJsonRequestBody(options.body),
      credentials: options.credentials,
      headers,
      method,
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error) || isApiErrorNotified(error)) {
      throw error;
    }
    throw createApiError("REQUEST_FAILED", {}, false);
  }

  let payload: unknown;
  try {
    payload = await readJsonPayload(response);
  } catch (error) {
    if (isAbortError(error) || isApiErrorNotified(error)) {
      throw error;
    }
    throw createApiError("REQUEST_FAILED", {}, false);
  }

  await handleUnauthorizedResponse(payload, headers, route, clearApiCache);

  if (!response.ok) {
    throw createHttpResponseError(payload, response.status, false);
  }
  if (isApiResponse<unknown>(payload) && payload.code !== 0) {
    throw createPayloadApiError(payload, response.status, false);
  }

  return unwrapApiResponse<unknown>(payload, { notifyOnError: false });
}

async function rejectApiEnvelopeResource(
  response: Response,
  headers: Headers,
  route: string,
) {
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return;
  }

  const payload = (await response.clone().json().catch(() => null)) as unknown;
  if (!isApiResponse<unknown>(payload) || payload.code === 0) {
    return;
  }

  await handleUnauthorizedResponse(payload, headers, route, clearApiCache);
  throw createPayloadApiError(payload, response.status);
}

async function createApiResourceResponseError(
  response: Response,
  headers: Headers,
  route: string,
) {
  let payload: unknown;

  try {
    payload = await response.clone().json();
  } catch {
    return createApiError("REQUEST_FAILED", { status: response.status });
  }

  await handleUnauthorizedResponse(payload, headers, route, clearApiCache);
  return createHttpResponseError(payload, response.status, true);
}

export async function requestApi<T>(
  route: string,
  options: ApiRequestOptions = {},
) {
  const method = options.method ?? "GET";
  // A cancelable request is owned by its caller. Sharing its promise would
  // let one route abort every other consumer of the same cached GET.
  const shouldUseCache =
    method === "GET" && !options.signal && (options.cacheTtlMs ?? 0) > 0;
  const cacheKey = shouldUseCache ? createRequestCacheKey(route, options) : null;
  const now = Date.now();

  const cached = cacheKey ? getRequestCache.get(cacheKey) : undefined;
  const request =
    cached && cached.expiresAt > now
      ? (cached.promise as Promise<T>)
      : (async () => {
          // Error notification belongs to the caller awaiting this promise,
          // not the shared transport. Otherwise the first cached GET caller
          // would decide whether every other caller sees an error toast.
          const data = (await fetchApiEnvelope(
            route,
            options,
            method,
          )) as T;

          if (method !== "GET") {
            clearApiCache();
          }

          return data;
        })();

  if (cacheKey && request !== cached?.promise) {
    getRequestCache.set(cacheKey, {
      expiresAt: now + (options.cacheTtlMs ?? 0),
      promise: request,
    });
  }

  try {
    return await request;
  } catch (error) {
    if (cacheKey) {
      getRequestCache.delete(cacheKey);
    }
    if (options.notifyOnError !== false) {
      notifyApiErrorOnce(error);
    }
    throw error;
  }
}

export async function uploadApi<T>(
  route: string,
  body: FormData,
  options: Pick<ApiRequestOptions, "auth" | "searchParams"> & {
    onProgress?: (progress: { loaded: number; total?: number }) => void;
    signal?: AbortSignal;
    timeoutMs?: number;
  } = {},
) {
  const headers = getAuthHeaders(
    options,
    { Accept: DEFAULT_ACCEPT_HEADER },
    clearApiCache,
  );
  if (!headers) {
    throw createApiError("AUTHENTICATION_REQUIRED");
  }
  // Uploads use Axios for upload progress and request timeouts.
  const { default: axios } = await import("axios");
  let response;

  try {
    response = await axios.post<unknown>(resolveApiUrl(route, options), body, {
      headers: Object.fromEntries(headers.entries()),
      onUploadProgress: options.onProgress
        ? ({ loaded, total }) => options.onProgress?.({ loaded, total })
        : undefined,
      responseType: "json",
      signal: options.signal,
      timeout: options.timeoutMs,
    });
  } catch (error) {
    if (isAbortError(error) || isApiErrorNotified(error)) {
      throw error;
    }

    if (axios.isAxiosError(error)) {
      await handleUnauthorizedResponse(error.response?.data, headers, route, clearApiCache);
      throw createHttpResponseError(
        error.response?.data,
        error.response?.status,
        true,
      );
    }

    throw createApiError("REQUEST_FAILED");
  }

  if (isApiResponse<unknown>(response.data) && response.data.code !== 0) {
    await handleUnauthorizedResponse(response.data, headers, route, clearApiCache);
    throw createPayloadApiError(response.data, response.status);
  }

  clearApiCache();

  return unwrapApiResponse<T>(response.data);
}

function resolveApiResourceUrl(url: string) {
  if (/^https?:\/\//i.test(url)) {
    return url;
  }

  return resolveApiUrl(url);
}

export async function fetchApiResource(url: string, init: RequestInit = {}) {
  let response: Response;
  let headers: Headers | null;

  try {
    headers = getAuthHeaders({}, init.headers, clearApiCache);
    if (!headers) {
      throw createApiError("AUTHENTICATION_REQUIRED");
    }
    response = await fetch(resolveApiResourceUrl(url), {
      ...init,
      cache: init.cache ?? "no-store",
      headers,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }

    if (isApiErrorNotified(error)) {
      throw error;
    }

    throw createApiError("REQUEST_FAILED");
  }

  if (!response.ok) {
    throw await createApiResourceResponseError(response, headers, url);
  }

  await rejectApiEnvelopeResource(response, headers, url);

  return response;
}
