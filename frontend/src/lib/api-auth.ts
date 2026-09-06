import {
  AUTH_REFRESH_LOCK_NAME,
  clearAuthSession,
  getAccessToken,
  isTokenLocallyInvalidated,
} from "@/lib/auth-session";
import type { ApiRequestOptions } from "@/types/api";

export const AUTH_REFRESH_ROUTE = "/api/auth/refresh";
export const APP_CODE_UNAUTHORIZED = 40001;

export function redirectToLogin(onInvalidated: () => void) {
  if (typeof window === "undefined") {
    return;
  }

  clearAuthSession();
  onInvalidated();

  if (window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

export function getAuthHeaders(
  options: Pick<ApiRequestOptions, "auth">,
  baseHeaders: HeadersInit | undefined,
  onInvalidated: () => void,
) {
  const headers = new Headers(baseHeaders);
  if (options.auth === false) {
    return headers;
  }

  const token = getAccessToken();
  if (!token || isTokenLocallyInvalidated(token)) {
    redirectToLogin(onInvalidated);
    return null;
  }

  headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

export async function handleUnauthorizedResponse(
  payload: unknown,
  headers: Headers,
  route: string,
  onInvalidated: () => void,
) {
  if (
    !payload ||
    typeof payload !== "object" ||
    !("code" in payload) ||
    !("message" in payload) ||
    !("data" in payload) ||
    payload.code !== APP_CODE_UNAUTHORIZED
  ) {
    return;
  }

  const requestToken = headers.get("Authorization")?.slice("Bearer ".length);
  if (!requestToken) {
    return;
  }

  const invalidateSession = () => {
    if (getAccessToken() === requestToken) {
      redirectToLogin(onInvalidated);
    }
  };

  if (route === AUTH_REFRESH_ROUTE) {
    invalidateSession();
    return;
  }

  await navigator.locks.request(
    AUTH_REFRESH_LOCK_NAME,
    { mode: "shared" },
    invalidateSession,
  );
}
