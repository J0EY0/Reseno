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
  skipAuth?: boolean;
}

interface ResuMateInternalAxiosRequestConfig
  extends InternalAxiosRequestConfig {
  skipAuth?: boolean;
}

// GET responses are cached briefly and invalidated by every mutation. This
// keeps route changes and PDF render reloads fast without serving stale writes.
const getRequestCache = new Map<string, ApiCacheEntry>();
const APP_CODE_UNAUTHORIZED = 40001;
const API_ERROR_NOTIFIED = Symbol("apiErrorNotified");

type NotifiedApiError = Error & {
  [API_ERROR_NOTIFIED]?: true;
};

const apiClient = axios.create({
  responseType: "json",
});

export const apiRoutes = {
  authLogin: "/api/auth/login",
  authRefresh: "/api/auth/refresh",
  authPassword: "/api/auth/password",
  workspaceBootstrap: "/api/workspace/bootstrap",
  workspaceDefaultTemplate: "/api/workspace/default-template",
  workspaceUserSettings: "/api/workspace/user-settings",
  resumes: "/api/resumes",
  resume: (resumeId: string) => `/api/resumes/${resumeId}`,
  resumeTrash: (resumeId: string) => `/api/resumes/${resumeId}/trash`,
  resumeRestore: (resumeId: string) => `/api/resumes/${resumeId}/restore`,
  resumeVersions: (resumeId: string) => `/api/resumes/${resumeId}/versions`,
  resumeVersion: (resumeId: string, versionId: string) =>
    `/api/resumes/${resumeId}/versions/${versionId}`,
  resumeTrashEmpty: "/api/resumes/trash",
  templates: "/api/templates",
  template: (templateId: string) => `/api/templates/${templateId}`,
  templateTrash: (templateId: string) => `/api/templates/${templateId}/trash`,
  templateRestore: (templateId: string) =>
    `/api/templates/${templateId}/restore`,
  templateTrashEmpty: "/api/templates/trash",
  modelConfigs: "/api/model-configs",
  modelProviders: "/api/model-providers",
  modelProviderDiscovery: "/api/model-providers/discover-models",
  agentSettings: "/api/agent/settings",
  agentResumeSession: (resumeId: string) =>
    `/api/agent/resumes/${encodeURIComponent(resumeId)}/session`,
  agentChat: "/api/agent/chat",
  resumePdfExport: "/api/exports/resume-pdf",
  resumeImport: "/api/import/resume",
  templateImport: "/api/import/templates",
  sectionRegistry: "/api/section-registry",
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
  (error as NotifiedApiError)[API_ERROR_NOTIFIED] = true;
  return error as NotifiedApiError;
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

export function isAbortError(error: unknown) {
  return Boolean(
    error &&
      typeof error === "object" &&
      "name" in error &&
      error.name === "AbortError",
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

function createNotifiedApiError(messageKey: string) {
  const message = resolveApiMessage(messageKey);
  const error = markApiErrorNotified(new Error(message));

  notifyApiError(message);

  return error;
}

function createPayloadApiError(payload: ApiResponse<unknown>) {
  if (payload.code === APP_CODE_UNAUTHORIZED) {
    redirectToLogin();
  }

  return createNotifiedApiError(payload.message);
}

export function unwrapApiResponse<T>(payload: unknown) {
  if (!isApiResponse<T>(payload)) {
    throw createNotifiedApiError("INVALID_API_RESPONSE");
  }

  if (payload.code !== 0) {
    throw createPayloadApiError(payload);
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
    throw createNotifiedApiError("AUTHENTICATION_REQUIRED");
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
      return Promise.reject(createNotifiedApiError("AUTHENTICATION_REQUIRED"));
    }

    headers.set("Authorization", `Bearer ${token}`);
  }

  config.headers = headers;

  return config;
});

apiClient.interceptors.response.use(
  (response) => {
    if (isApiResponse<unknown>(response.data) && response.data.code !== 0) {
      return Promise.reject(createPayloadApiError(response.data));
    }

    return response;
  },
  (error) => {
    if (isApiErrorNotified(error)) {
      return Promise.reject(error);
    }

    if (axios.isAxiosError(error)) {
      const payload = error.response?.data;

      if (isApiResponse<unknown>(payload)) {
        return Promise.reject(createPayloadApiError(payload));
      }

      return Promise.reject(createNotifiedApiError("REQUEST_FAILED"));
    }

    return Promise.reject(createNotifiedApiError("REQUEST_FAILED"));
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

  throw createPayloadApiError(payload);
}

export async function requestApi<T>(
  route: string,
  options: ApiRequestOptions = {},
) {
  const method = options.method ?? "GET";
  const shouldUseCache = method === "GET" && (options.cacheTtlMs ?? 0) > 0;
  const cacheKey = shouldUseCache ? createRequestCacheKey(route, options) : null;
  const now = Date.now();

  if (cacheKey) {
    const cached = getRequestCache.get(cacheKey);
    if (cached && cached.expiresAt > now) {
      return cached.promise as Promise<T>;
    }
  }

  const request = (async () => {
    const requestConfig: ResuMateAxiosRequestConfig = {
      data: options.body,
      headers: options.body
        ? {
            "Content-Type": "application/json",
          }
        : undefined,
      method,
      skipAuth: options.auth === false,
      url: resolveApiUrl(route, options),
    };
    const response = await apiClient.request<unknown>(requestConfig);

    const data = unwrapApiResponse<T>(response.data);

    if (method !== "GET") {
      clearApiCache();
    }

    return data;
  })();

  if (cacheKey) {
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
    throw error;
  }
}

export async function uploadApi<T>(
  route: string,
  body: FormData,
  options: Pick<ApiRequestOptions, "auth" | "searchParams"> = {},
) {
  const requestConfig: ResuMateAxiosRequestConfig = {
    skipAuth: options.auth === false,
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

    throw createNotifiedApiError("REQUEST_FAILED");
  }

  if (!response.ok) {
    throw createNotifiedApiError("REQUEST_FAILED");
  }

  await rejectApiEnvelopeResource(response);

  return response;
}
