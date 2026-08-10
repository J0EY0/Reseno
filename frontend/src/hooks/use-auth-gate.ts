import { useEffect, useState } from "react";

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
import { runViewTransition } from "@/lib/view-transition";

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
  requestFallbackError,
}: {
  loginFallbackError: string;
  onAuthenticated: () => void;
  onLoggedOut: () => void;
  requestFallbackError: string;
}) {
  const [authGate, setAuthGate] = useState<AuthGateState>({ phase: "loading" });
  const [authCheckAttempt, setAuthCheckAttempt] = useState(0);

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
      void refreshAuthSession().catch((error) => {
        console.error("Failed to refresh auth session.", error);
        clearAuthSession();
        setAuthGate({ phase: "login" });
      });
    }, 4 * 60 * 60 * 1000);

    return () => {
      window.clearInterval(refreshInterval);
    };
  }, [authGate.phase]);

  async function login(credentials: { username: string; password: string }) {
    try {
      await loginWithCredentials(credentials.username, credentials.password);

      runViewTransition(() => {
        onAuthenticated();
        setAuthGate({ phase: "app" });
      }, "nav-forward");

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

      runViewTransition(() => {
        onAuthenticated();
        setAuthGate({ phase: "app" });
      }, "nav-forward");

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
    runViewTransition(() => {
      onLoggedOut();
      setAuthGate({ phase: "login" });
    }, "nav-back");
  }

  function retry() {
    setAuthGate({ phase: "loading" });
    setAuthCheckAttempt((current) => current + 1);
  }

  return {
    authGate,
    login,
    logout,
    retry,
    setup,
  };
}
