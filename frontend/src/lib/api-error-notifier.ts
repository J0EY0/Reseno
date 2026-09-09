import { toast } from "sonner";

import { ApiError, isAbortError, isApiErrorCode } from "@/lib/api-errors";
import { resolveApiMessage } from "@/lib/api-message";
import { getAccessToken } from "@/lib/auth-session";

const notifiedErrors = new WeakSet<object>();

export function notifyApiError(
  error: unknown,
  fallbackMessage?: string,
  showError: (message: string) => void = (message) =>
    toast.error(message, { closeButton: true }),
) {
  if (
    typeof window === "undefined" ||
    isAbortError(error) ||
    (isApiErrorCode(error, "UNAUTHORIZED_REQUEST") && !getAccessToken())
  ) {
    return false;
  }

  if (error && typeof error === "object") {
    if (notifiedErrors.has(error)) {
      return false;
    }
    notifiedErrors.add(error);
  }

  const message =
    error instanceof ApiError
      ? error.message
      : (fallbackMessage ??
        (error instanceof Error
          ? error.message
          : resolveApiMessage("REQUEST_FAILED")));
  showError(message);
  return true;
}
