import axios, {
  AxiosHeaders,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";
import { toast } from "sonner";

import type { ApiRequestOptions, ApiResponse } from "@/types/api";
import {
  clearAuthSession,
  getAccessToken,
  isAuthRequired,
  isTokenLocallyInvalidated,
} from "@/lib/auth-session";
import { resolveApiMessage } from "@/lib/api-message";

interface ApiCacheEntry {
  expiresAt: number;
  promise: Promise<unknown>;
}

interface ResuMateAxiosRequestConfig extends AxiosRequestConfig {
  notifyOnError?: boolean;
  skipAuth?: boolean;
}

interface ResuMateInternalAxiosRequestConfig
  extends InternalAxiosRequestConfig {
  notifyOnError?: boolean;
  skipAuth?: boolean;
}

// GET responses are cached briefly and invalidated by every mutation. This
// keeps route changes and PDF render reloads fast without serving stale writes.
const getRequestCache = new Map<string, ApiCacheEntry>();
const APP_CODE_UNAUTHORIZED = 40001;
const API_ERROR_NOTIFIED = Symbol("apiErrorNotified");

type ResuMateApiError = Error & {
  [API_ERROR_NOTIFIED]?: true;
  apiCode?: string;
  status?: number;
};

const apiClient = axios.create({
  responseType: "json",
});

export const apiRoutes = {
  authLogin: "/api/auth/login",
  authRefresh: "/api/auth/refresh",
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
  (error as ResuMateApiError)[API_ERROR_NOTIFIED] = true;
  return error as ResuMateApiError;
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
    axios.isCancel(error) ||
      (error &&
        typeof error === "object" &&
        "name" in error &&
        (error.name === "AbortError" || error.name === "CanceledError")),
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
  metadata: Pick<ResuMateApiError, "apiCode" | "status"> = {},
  notifyOnError = true,
) {
  const message = resolveApiMessage(messageKey);
  const error = new Error(message) as ResuMateApiError;

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
  if (payload.code === APP_CODE_UNAUTHORIZED) {
    redirectToLogin();
  }

  return createApiError(
    payload.message,
    {
      apiCode: payload.message,
      status,
    },
    notifyOnError,
  );
}

export function unwrapApiResponse<T>(
  payload: unknown,
  options: Pick<ApiRequestOptions, "notifyOnError"> = {},
) {
  const notifyOnError = options.notifyOnError !== false;

  if (!isApiResponse<T>(payload)) {
    throw createApiError("INVALID_API_RESPONSE", {}, notifyOnError);
  }

  if (payload.code !== 0) {
    throw createPayloadApiError(payload, undefined, notifyOnError);
  }

  return payload.data;
}

function redirectToLogin() {
  if (typeof window === "undefined") {
    return;
  }

  clearAuthSession();
  clearApiCache();

  if (window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

function getAuthHeaders(
  options: Pick<ApiRequestOptions, "auth"> = {},
  baseHeaders?: HeadersInit,
) {
  const headers = new Headers(baseHeaders);
  const shouldAuthenticate = options.auth !== false && isAuthRequired();

  if (!shouldAuthenticate) {
    return headers;
  }

  const token = getAccessToken();
  if (!token || isTokenLocallyInvalidated(token)) {
    redirectToLogin();
    throw createApiError("AUTHENTICATION_REQUIRED");
  }

  headers.set("Authorization", `Bearer ${token}`);

  return headers;
}

apiClient.interceptors.request.use((config: ResuMateInternalAxiosRequestConfig) => {
  const headers = AxiosHeaders.from(config.headers as AxiosHeaders | undefined);

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  if (!config.skipAuth && isAuthRequired()) {
    const token = getAccessToken();
    if (!token || isTokenLocallyInvalidated(token)) {
      redirectToLogin();
      return Promise.reject(
        createApiError(
          "AUTHENTICATION_REQUIRED",
          {},
          config.notifyOnError !== false,
        ),
      );
    }

    headers.set("Authorization", `Bearer ${token}`);
  }

  config.headers = headers;

  return config;
});

apiClient.interceptors.response.use(
  (response) => {
    if (isApiResponse<unknown>(response.data) && response.data.code !== 0) {
      return Promise.reject(
        createPayloadApiError(
          response.data,
          response.status,
          (
            response.config as ResuMateInternalAxiosRequestConfig
          ).notifyOnError !== false,
        ),
      );
    }

    return response;
  },
  (error) => {
    if (isAbortError(error)) {
      return Promise.reject(error);
    }

    if (isApiErrorNotified(error)) {
      return Promise.reject(error);
    }

    if (axios.isAxiosError(error)) {
      const payload = error.response?.data;
      const notifyOnError =
        (
          error.config as ResuMateInternalAxiosRequestConfig | undefined
        )?.notifyOnError !== false;

      if (isApiResponse<unknown>(payload)) {
        return Promise.reject(
          createPayloadApiError(
            payload,
            error.response?.status,
            notifyOnError,
          ),
        );
      }

      const detail =
        payload &&
        typeof payload === "object" &&
        "detail" in payload &&
        payload.detail &&
        typeof payload.detail === "object"
          ? payload.detail
          : null;
      const code =
        detail && "code" in detail && typeof detail.code === "string"
          ? detail.code
          : null;

      if (code) {
        return Promise.reject(
          createApiError(
            code,
            {
              apiCode: code,
              status: error.response?.status,
            },
            notifyOnError,
          ),
        );
      }

      return Promise.reject(
        createApiError("REQUEST_FAILED", {}, notifyOnError),
      );
    }

    return Promise.reject(createApiError("REQUEST_FAILED"));
  },
);

async function rejectApiEnvelopeResource(response: Response) {
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return;
  }

  const payload = (await response.clone().json().catch(() => null)) as unknown;
  if (!isApiResponse<unknown>(payload) || payload.code === 0) {
    return;
  }

  throw createPayloadApiError(payload, response.status);
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
          const requestConfig: ResuMateAxiosRequestConfig = {
            data: options.body,
            headers: options.body
              ? {
                  "Content-Type": "application/json",
                }
              : undefined,
            method,
            // Error notification belongs to the caller awaiting this promise,
            // not the shared transport. Otherwise the first cached GET caller
            // would decide whether every other caller sees an error toast.
            notifyOnError: false,
            signal: options.signal,
            skipAuth: options.auth === false,
            url: resolveApiUrl(route, options),
          };
          const response = await apiClient.request<unknown>(requestConfig);
          const data = unwrapApiResponse<T>(response.data, {
            notifyOnError: false,
          });

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
  const requestConfig: ResuMateAxiosRequestConfig = {
    onUploadProgress: options.onProgress
      ? ({ loaded, total }) => options.onProgress?.({ loaded, total })
      : undefined,
    signal: options.signal,
    skipAuth: options.auth === false,
    timeout: options.timeoutMs,
  };
  const response = await apiClient.post<unknown>(
    resolveApiUrl(route, options),
    body,
    requestConfig,
  );

  clearApiCache();

  return unwrapApiResponse<T>(response.data);
}

export function resolveApiResourceUrl(url: string) {
  if (/^https?:\/\//i.test(url)) {
    return url;
  }

  return resolveApiUrl(url);
}

export async function fetchApiResource(url: string, init: RequestInit = {}) {
  let response: Response;

  try {
    response = await fetch(resolveApiResourceUrl(url), {
      ...init,
      cache: init.cache ?? "no-store",
      headers: getAuthHeaders({}, init.headers),
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
    throw createApiError("REQUEST_FAILED", {
      status: response.status,
    });
  }

  await rejectApiEnvelopeResource(response);

  return response;
}
