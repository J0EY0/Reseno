import { AUTH_REFRESH_LOCK_NAME } from "@/lib/auth-session";
import { resolveApiMessage } from "@/lib/api-message";

export function getAuthEnvironmentError() {
  if (typeof window === "undefined") return null;
  if (!window.isSecureContext) return "AUTH_SECURE_CONTEXT_REQUIRED";
  if (typeof navigator.locks?.request !== "function")
    return "AUTH_BROWSER_UNSUPPORTED";
  return null;
}

export async function withAuthSessionLock<T>(
  mode: LockMode,
  action: () => T | Promise<T>,
): Promise<T> {
  const error = getAuthEnvironmentError();
  if (error) throw new Error(resolveApiMessage(error));
  return navigator.locks.request(AUTH_REFRESH_LOCK_NAME, { mode }, action);
}
