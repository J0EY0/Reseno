import { resolveApiMessage } from "@/lib/api-message";

export class ApiError extends Error {
  apiCode?: string;
  status?: number;

  constructor(
    messageKey: string,
    metadata: { apiCode?: string; status?: number } = {},
  ) {
    super(resolveApiMessage(messageKey));
    this.name = "ApiError";
    this.apiCode = metadata.apiCode;
    this.status = metadata.status;
  }
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
