import type { ApiRequestOptions, ApiResponse } from "@/types/api";
import { getAuthHeaders, handleUnauthorizedResponse } from "@/lib/api-auth";
import { getAccessToken } from "@/lib/auth-session";
import { ApiError, isAbortError } from "@/lib/api-errors";

interface ApiCacheEntry {
  pathname: string;
  expiresAt: number;
  promise: Promise<unknown>;
}

export type ApiUploadOptions = Pick<
  ApiRequestOptions,
  "auth" | "searchParams" | "notifyOnError"
> & {
  onProgress?: (progress: { loaded: number; total?: number }) => void;
  signal?: AbortSignal;
  timeoutMs?: number;
};

export type ApiResourceOptions = RequestInit &
  Pick<ApiRequestOptions, "notifyOnError">;

const getRequestCache = new Map<string, ApiCacheEntry>();
const DEFAULT_ACCEPT_HEADER = "application/json, text/plain, */*";

function buildSearchParams(values: ApiRequestOptions["searchParams"]) {
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

  const prefix = getApiPathname(routePrefix);
  for (const [key, entry] of getRequestCache) {
    if (entry.pathname === prefix || entry.pathname.startsWith(`${prefix}/`)) {
      getRequestCache.delete(key);
    }
  }
}

export function getApiPathname(route: string) {
  const base = new URL(resolveApiUrl("/"), "http://api.local");
  const url = new URL(route, base);
  const pathname =
    /^https?:\/\//i.test(route) &&
    url.origin === base.origin &&
    url.pathname.startsWith(base.pathname)
      ? `/${url.pathname.slice(base.pathname.length)}`
      : url.pathname;
  return pathname.replace(/\/+$/, "");
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
  return Boolean(
    value &&
    typeof value === "object" &&
    "code" in value &&
    "message" in value &&
    "data" in value,
  );
}

function createHttpResponseError(payload: unknown, status?: number) {
  if (isApiResponse<unknown>(payload)) {
    return new ApiError(payload.message, { apiCode: payload.message, status });
  }

  return new ApiError("REQUEST_FAILED", { status });
}

async function validateResponse(
  payload: unknown,
  status: number,
  headers: Headers,
  route: string,
) {
  await handleUnauthorizedResponse(
    payload,
    headers,
    route,
    clearApiCache,
    status,
  );
  if (
    status < 200 ||
    status >= 300 ||
    (isApiResponse<unknown>(payload) && payload.code !== 0)
  ) {
    throw createHttpResponseError(payload, status);
  }
}

function unwrapEnvelope<T>(payload: unknown): T {
  if (!isApiResponse<T>(payload)) {
    throw new ApiError("INVALID_API_RESPONSE");
  }
  return payload.data;
}

function requireAuthHeaders(
  options: Pick<ApiRequestOptions, "auth">,
  baseHeaders?: HeadersInit,
) {
  const headers = getAuthHeaders(options, baseHeaders, clearApiCache);
  if (!headers) {
    throw new ApiError("UNAUTHORIZED_REQUEST", {
      apiCode: "UNAUTHORIZED_REQUEST",
    });
  }
  return headers;
}

async function fetchResponse(url: string, init: RequestInit) {
  try {
    return await fetch(url, init);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ApiError("REQUEST_FAILED");
  }
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

async function parseResponse(response: Response) {
  try {
    return await readJsonPayload(response);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new ApiError("REQUEST_FAILED", { status: response.status });
  }
}

async function fetchEnvelope(route: string, options: ApiRequestOptions) {
  const baseHeaders = new Headers({ Accept: DEFAULT_ACCEPT_HEADER });
  if (options.body !== undefined) {
    baseHeaders.set("Content-Type", "application/json");
  }
  const headers = requireAuthHeaders(options, baseHeaders);
  const response = await fetchResponse(resolveApiUrl(route, options), {
    body: createJsonRequestBody(options.body),
    credentials: options.credentials,
    headers,
    method: options.method ?? "GET",
    signal: options.signal,
  });
  const payload = await parseResponse(response);
  await validateResponse(payload, response.status, headers, route);
  return unwrapEnvelope<unknown>(payload);
}

export async function requestApiEnvelope<T>(
  route: string,
  options: ApiRequestOptions = {},
) {
  const method = options.method ?? "GET";
  const shouldUseCache =
    method === "GET" && !options.signal && (options.cacheTtlMs ?? 0) > 0;
  const cacheKey = shouldUseCache
    ? createRequestCacheKey(route, options)
    : null;
  const now = Date.now();
  const cached = cacheKey ? getRequestCache.get(cacheKey) : undefined;
  const request =
    cached && cached.expiresAt > now
      ? (cached.promise as Promise<T>)
      : (fetchEnvelope(route, options) as Promise<T>);

  if (cacheKey && request !== cached?.promise) {
    getRequestCache.set(cacheKey, {
      pathname: getApiPathname(route),
      expiresAt: now + (options.cacheTtlMs ?? 0),
      promise: request,
    });
  }

  try {
    return await request;
  } catch (error) {
    if (cacheKey && getRequestCache.get(cacheKey)?.promise === request) {
      getRequestCache.delete(cacheKey);
    }
    throw error;
  }
}

export async function uploadApiEnvelope<T>(
  route: string,
  body: FormData,
  options: ApiUploadOptions = {},
) {
  const headers = requireAuthHeaders(options, {
    Accept: DEFAULT_ACCEPT_HEADER,
  });
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
    if (isAbortError(error)) {
      throw error;
    }
    if (axios.isAxiosError(error) && error.response) {
      response = error.response;
    } else {
      throw new ApiError("REQUEST_FAILED");
    }
  }

  await validateResponse(response.data, response.status, headers, route);
  return unwrapEnvelope<T>(response.data);
}

export async function fetchApiResponse(url: string, init: RequestInit = {}) {
  const headers = requireAuthHeaders({}, init.headers);
  const response = await fetchResponse(
    /^https?:\/\//i.test(url) ? url : resolveApiUrl(url),
    {
      ...init,
      cache: init.cache ?? "no-store",
      headers,
    },
  );
  const contentType = response.headers.get("Content-Type") ?? "";
  const payload =
    !response.ok || contentType.toLowerCase().includes("application/json")
      ? await parseResponse(response.clone())
      : undefined;
  await validateResponse(payload, response.status, headers, url);
  return response;
}
