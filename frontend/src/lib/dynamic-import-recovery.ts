const DYNAMIC_IMPORT_ERROR_PATTERN =
  /failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module|chunkloaderror|loading chunk [^ ]+ failed|unable to preload css for /i;

function getErrorMessage(error: unknown): string | null {
  if (typeof error === "string") {
    return error;
  }
  if (!error || typeof error !== "object") {
    return null;
  }

  const candidate = error as {
    data?: unknown;
    message?: unknown;
    statusText?: unknown;
  };
  if (typeof candidate.message === "string") {
    return candidate.message;
  }
  if (typeof candidate.data === "string") {
    return candidate.data;
  }
  if (
    candidate.data &&
    typeof candidate.data === "object" &&
    "message" in candidate.data &&
    typeof candidate.data.message === "string"
  ) {
    return candidate.data.message;
  }
  return typeof candidate.statusText === "string" ? candidate.statusText : null;
}

export function getApplicationRouteErrorDetails(error: unknown) {
  const message = getErrorMessage(error);
  return {
    kind:
      message && DYNAMIC_IMPORT_ERROR_PATTERN.test(message)
        ? ("dynamic-import" as const)
        : ("unexpected" as const),
    message,
  };
}

export function isDynamicImportFailure(error: unknown) {
  return getApplicationRouteErrorDetails(error).kind === "dynamic-import";
}
