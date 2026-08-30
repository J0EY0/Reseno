const DYNAMIC_IMPORT_RELOAD_GUARD_KEY =
  "resumate-dynamic-import-reload-route";

const DYNAMIC_IMPORT_ERROR_PATTERN =
  /failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module|chunkloaderror|loading chunk [^ ]+ failed/i;

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
  return typeof candidate.statusText === "string"
    ? candidate.statusText
    : null;
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

function claimReloadForCurrentRoute() {
  const routeKey = window.location.pathname;
  try {
    if (
      window.sessionStorage.getItem(DYNAMIC_IMPORT_RELOAD_GUARD_KEY) ===
      routeKey
    ) {
      return false;
    }
    window.sessionStorage.setItem(DYNAMIC_IMPORT_RELOAD_GUARD_KEY, routeKey);
    return true;
  } catch {
    // Without durable session state an automatic reload could loop forever.
    return false;
  }
}

export function isDynamicImportFailure(error: unknown) {
  return getApplicationRouteErrorDetails(error).kind === "dynamic-import";
}

export function tryReloadAfterDynamicImportFailure(error: unknown) {
  if (!isDynamicImportFailure(error) || !claimReloadForCurrentRoute()) {
    return false;
  }

  window.location.reload();
  return true;
}

export function clearDynamicImportReloadGuard() {
  try {
    window.sessionStorage.removeItem(DYNAMIC_IMPORT_RELOAD_GUARD_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
}

export function installDynamicImportRecovery() {
  const handlePreloadError = (event: Event) => {
    // Vite emits this event specifically for failed dynamic-import preloads.
    // Prevent the rejection only when this route owns a safe reload attempt.
    if (!claimReloadForCurrentRoute()) {
      return;
    }

    event.preventDefault();
    window.location.reload();
  };

  window.addEventListener("vite:preloadError", handlePreloadError);
  return () => {
    window.removeEventListener("vite:preloadError", handlePreloadError);
  };
}
