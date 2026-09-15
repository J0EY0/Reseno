import {
  startTransition,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";

import {
  clearAuthSession,
  getAuthSetupStatus,
  loadAuthSession,
  loginWithCredentials,
  refreshAuthSession,
  setupAuthOwner,
} from "@/lib/auth";
import { isApiErrorCode } from "@/lib/api-client";
import { notifyApiError } from "@/lib/api-error-notifier";
import {
  AUTH_SESSION_INVALIDATED_EVENT,
  AUTH_SESSION_RESTORED_EVENT,
} from "@/lib/api-auth";
import { getAuthEnvironmentError } from "@/lib/auth-environment";
import { AUTH_SESSION_KEY, getAccessToken } from "@/lib/auth-session";
import {
  createWorkspaceLateralRouteHandoff,
  type PreparedWorkspaceRoute,
} from "@/lib/workspace-route-memory";

type AuthGateState =
  | { phase: "loading" }
  | { phase: "setup" }
  | { phase: "login" }
  | { phase: "app"; sessionExpired?: boolean }
  | { phase: "error" }
  | {
      phase: "unsupported";
      reason: NonNullable<ReturnType<typeof getAuthEnvironmentError>>;
    };

type AuthDestinationCommit = {
  destination: "resume" | "settings";
  complete: () => void;
};

export function useAuthGate({
  loginFallbackError,
  onAuthenticated,
  onLoggedOut,
  prepareDestination,
  requestFallbackError,
}: {
  loginFallbackError: string;
  onAuthenticated: () => void | Promise<unknown>;
  onLoggedOut: () => void;
  prepareDestination: (
    destination: "resume" | "settings",
    options: { signal: AbortSignal },
  ) => Promise<PreparedWorkspaceRoute<"resume" | "settings">>;
  requestFallbackError: string;
}) {
  const navigate = useNavigate();
  const [authGate, setAuthGate] = useState<AuthGateState>(() => {
    const reason = getAuthEnvironmentError();
    return reason ? { phase: "unsupported", reason } : { phase: "loading" };
  });
  const [authCheckAttempt, setAuthCheckAttempt] = useState(0);
  const [hasOAuthLoginCallback] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    return (
      window.location.pathname === "/login" &&
      (params.has("oauth_code") || params.has("oauth_error"))
    );
  });
  const [destinationCommit, setDestinationCommit] =
    useState<AuthDestinationCommit | null>(null);
  const commitRef = useRef<{
    request: AuthDestinationCommit;
    cancel: () => void;
  } | null>(null);
  const synchronizeAuthSession = useEffectEvent(() => {
    const hasSession = loadAuthSession();
    if (hasSession && authGate.phase === "login") {
      onAuthenticated();
      setAuthGate({ phase: "app" });
    } else if (authGate.phase === "app") {
      if (hasSession && authGate.sessionExpired) {
        restoreWorkspaceSession();
      } else if (!hasSession && !authGate.sessionExpired) {
        setAuthGate({ phase: "app", sessionExpired: true });
      }
    }
  });

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (
        event.storageArea === window.localStorage &&
        (event.key === AUTH_SESSION_KEY || event.key === null)
      ) {
        synchronizeAuthSession();
      }
    };
    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) synchronizeAuthSession();
    };

    const handleSessionChange = () => synchronizeAuthSession();
    window.addEventListener(
      AUTH_SESSION_INVALIDATED_EVENT,
      handleSessionChange,
    );
    window.addEventListener("focus", handleSessionChange);
    window.addEventListener("storage", handleStorage);
    window.addEventListener("pageshow", handlePageShow);
    return () => {
      window.removeEventListener(
        AUTH_SESSION_INVALIDATED_EVENT,
        handleSessionChange,
      );
      window.removeEventListener("focus", handleSessionChange);
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener("pageshow", handlePageShow);
    };
  }, []);

  useEffect(() => {
    if (getAuthEnvironmentError()) return;
    let cancelled = false;

    void getAuthSetupStatus()
      .then(({ setupRequired }) => {
        if (cancelled) {
          return;
        }

        if (setupRequired) {
          clearAuthSession();
          setAuthGate({ phase: "setup" });
          return;
        }

        setAuthGate({
          phase: !hasOAuthLoginCallback && loadAuthSession() ? "app" : "login",
        });
      })
      .catch(() => {
        if (!cancelled) {
          setAuthGate({ phase: "error" });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [authCheckAttempt, hasOAuthLoginCallback]);

  useEffect(
    () => () => {
      commitRef.current?.cancel();
    },
    [],
  );

  useEffect(() => {
    if (authGate.phase !== "app" || authGate.sessionExpired) {
      return;
    }

    const refreshInterval = window.setInterval(
      () => {
        void refreshAuthSession().then(
          () => synchronizeAuthSession(),
          (error) => {
            console.error("Failed to refresh auth session.", error);
            synchronizeAuthSession();
          },
        );
      },
      4 * 60 * 60 * 1000,
    );

    return () => {
      window.clearInterval(refreshInterval);
    };
  }, [authGate]);

  async function login(credentials: { username: string; password: string }) {
    let fallbackError = loginFallbackError;
    try {
      await loginWithCredentials(credentials.username, credentials.password);

      fallbackError = requestFallbackError;
      await acceptSession();

      return { ok: true as const };
    } catch (error) {
      notifyApiError(error, fallbackError);
      return {
        ok: false as const,
        error: error instanceof Error ? error.message : fallbackError,
        errorShown: true,
      };
    }
  }

  async function setup(credentials: {
    username: string;
    password: string;
    confirmPassword: string;
  }) {
    try {
      await setupAuthOwner(credentials);

      await acceptSession();

      return { ok: true as const };
    } catch (error) {
      if (isApiErrorCode(error, "SETUP_ALREADY_COMPLETED")) {
        setAuthGate({ phase: "login" });
      }

      notifyApiError(error, requestFallbackError);
      return {
        ok: false as const,
        error: error instanceof Error ? error.message : requestFallbackError,
        errorShown: true,
      };
    }
  }

  function logout() {
    clearAuthSession();
    startTransition(() => {
      onLoggedOut();
      setAuthGate({ phase: "login" });
    });
  }

  function retry() {
    setAuthGate({ phase: "loading" });
    setAuthCheckAttempt((current) => current + 1);
  }

  function restoreWorkspaceSession() {
    setAuthGate({ phase: "app" });
    window.dispatchEvent(new Event(AUTH_SESSION_RESTORED_EVENT));
  }

  async function acceptSession(
    destination: "resume" | "settings" = "resume",
    signal = new AbortController().signal,
  ) {
    if (authGate.phase === "app" && authGate.sessionExpired) {
      signal.throwIfAborted();
      if (!loadAuthSession()) throw new Error(requestFallbackError);
      restoreWorkspaceSession();
      return;
    }
    const [prepared] = await Promise.all([
      prepareDestination(destination, { signal }).catch((error: unknown) => {
        signal.throwIfAborted();
        console.error("Failed to prepare the authenticated workspace.", error);
        return null;
      }),
      onAuthenticated(),
    ]);
    signal.throwIfAborted();
    if (!loadAuthSession()) {
      setAuthGate({ phase: "login" });
      throw new Error(requestFallbackError);
    }
    const acceptedToken = getAccessToken();

    commitRef.current?.cancel();
    await new Promise<void>((resolve, reject) => {
      function finish(error?: unknown) {
        if (commitRef.current?.request !== request) return;
        commitRef.current = null;
        signal.removeEventListener("abort", abort);
        setDestinationCommit(null);
        if (error) reject(error);
        else resolve();
      }
      function abort() {
        if (commitRef.current?.request !== request) return;
        finish(signal.reason);
        if (getAccessToken() === acceptedToken) {
          setAuthGate({ phase: "login" });
          navigate("/login", { replace: true });
        }
      }
      const request: AuthDestinationCommit = {
        destination,
        complete: () => {
          if (signal.aborted) abort();
          else finish();
        },
      };
      commitRef.current = {
        request,
        cancel: () => finish(new DOMException("Aborted", "AbortError")),
      };
      signal.addEventListener("abort", abort, { once: true });
      startTransition(() => {
        if (signal.aborted) return;
        setDestinationCommit(request);
        setAuthGate({ phase: "app" });
        navigate(`/${destination}`, {
          replace: true,
          state: prepared ? createWorkspaceLateralRouteHandoff(prepared) : null,
        });
      });
    });
  }

  return {
    acceptSession,
    authGate,
    destinationCommit,
    login,
    logout,
    retry,
    setup,
  };
}
