import {
  clearAuthSession,
  getAccessToken,
  isTokenLocallyInvalidated,
} from "@/lib/auth-session";
import { withAuthSessionLock } from "@/lib/auth-environment";
import type { ApiRequestOptions } from "@/types/api";

export const AUTH_REFRESH_ROUTE = "/api/auth/refresh";
const APP_CODE_UNAUTHORIZED = 40001;

export const AUTH_SESSION_INVALIDATED_EVENT = "reseno:auth-session-invalidated";
export const AUTH_SESSION_RESTORED_EVENT = "reseno:auth-session-restored";

function invalidateAuthSession(onInvalidated: () => void) {
  if (typeof window === "undefined") {
    return;
  }

  clearAuthSession();
  onInvalidated();

  window.dispatchEvent(new Event(AUTH_SESSION_INVALIDATED_EVENT));
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
    invalidateAuthSession(onInvalidated);
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
  status?: number,
) {
  if (
    status !== 401 &&
    (!payload ||
      typeof payload !== "object" ||
      !("code" in payload) ||
      !("message" in payload) ||
      !("data" in payload) ||
      payload.code !== APP_CODE_UNAUTHORIZED)
  ) {
    return;
  }

  const requestToken = headers.get("Authorization")?.slice("Bearer ".length);
  if (!requestToken) {
    return;
  }

  const invalidateSession = () => {
    const currentToken = getAccessToken();
    if (!currentToken || currentToken === requestToken) {
      invalidateAuthSession(onInvalidated);
    }
  };

  if (route === AUTH_REFRESH_ROUTE) {
    invalidateSession();
    return;
  }

  await withAuthSessionLock("shared", invalidateSession);
}
