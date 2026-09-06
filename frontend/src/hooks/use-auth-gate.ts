import { startTransition, useEffect, useEffectEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  clearAuthSession,
  getAuthSetupStatus,
  loadAuthSession,
  loginWithCredentials,
  refreshAuthSession,
  setupAuthOwner,
} from "@/lib/auth";
import {
  isApiErrorCode,
  isApiErrorToastShown,
} from "@/lib/api-client";
import { AUTH_SESSION_KEY } from "@/lib/auth-session";
import {
  createWorkspaceLateralRouteHandoff,
  type PreparedWorkspaceRoute,
} from "@/lib/workspace-route-memory";

type AuthGateState =
  | { phase: "loading" }
  | { phase: "setup" }
  | { phase: "login" }
  | { phase: "app" }
  | { phase: "error" };

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
  const [authGate, setAuthGate] = useState<AuthGateState>({ phase: "loading" });
  const [authCheckAttempt, setAuthCheckAttempt] = useState(0);
  const synchronizeAuthSession = useEffectEvent(() => {
    const hasSession = loadAuthSession();
    if (hasSession && authGate.phase === "login") {
      onAuthenticated();
      setAuthGate({ phase: "app" });
    } else if (!hasSession && authGate.phase === "app") {
      onLoggedOut();
      setAuthGate({ phase: "login" });
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

    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  useEffect(() => {
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
          phase: loadAuthSession() ? "app" : "login",
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
  }, [authCheckAttempt]);

  useEffect(() => {
    if (authGate.phase !== "app") {
      return;
    }

    const refreshInterval = window.setInterval(() => {
      void refreshAuthSession().then(
        () => synchronizeAuthSession(),
        (error) => {
          console.error("Failed to refresh auth session.", error);
          synchronizeAuthSession();
        },
      );
    }, 4 * 60 * 60 * 1000);

    return () => {
      window.clearInterval(refreshInterval);
    };
  }, [authGate.phase]);

  async function login(credentials: { username: string; password: string }) {
    try {
      await loginWithCredentials(credentials.username, credentials.password);

      await acceptSession();

      return { ok: true as const };
    } catch (error) {
      return {
        ok: false as const,
        error: error instanceof Error ? error.message : loginFallbackError,
        errorShown: isApiErrorToastShown(error),
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

      return {
        ok: false as const,
        error: error instanceof Error ? error.message : requestFallbackError,
        errorShown: isApiErrorToastShown(error),
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

  async function acceptSession(
    destination: "resume" | "settings" = "resume",
    signal = new AbortController().signal,
  ) {
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

    startTransition(() => {
      setAuthGate({ phase: "app" });
      navigate(`/${destination}`, {
        replace: true,
        state: prepared ? createWorkspaceLateralRouteHandoff(prepared) : null,
      });
    });
  }

  return {
    acceptSession,
    authGate,
    login,
    logout,
    retry,
    setup,
  };
}
