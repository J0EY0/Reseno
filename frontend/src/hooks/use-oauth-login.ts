import { useEffect, useEffectEvent, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { isAbortError, isApiErrorCode } from "@/lib/api-client";
import { getAuthSetupStatus } from "@/lib/auth";
import {
  completeGitHubLogin,
  parseOAuthLoginCallback,
  redirectToGitHubLogin,
  resolveOAuthLoginError,
  type OAuthLoginCallback,
} from "@/lib/auth-oauth-login";

type GitHubAvailability =
  | { status: "loading" }
  | { status: "ready"; available: boolean }
  | { status: "error"; message: string };

export interface OAuthLoginControls {
  availability: GitHubAvailability;
  isPending: boolean;
  requestError: string | null;
  retry: () => void;
  signIn: () => Promise<void>;
}

export function useOAuthLogin({
  enabled,
  onComplete,
  t,
}: {
  enabled: boolean;
  onComplete: (signal: AbortSignal) => Promise<void>;
  t: AppMessages;
}) {
  const [callback] = useState(() => window.location.pathname === "/login"
    ? parseOAuthLoginCallback(window.location.hash)
    : null);
  const callbackConsumedRef = useRef(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [isCompleting, setIsCompleting] = useState(Boolean(callback && "code" in callback));
  const [isPending, setIsPending] = useState(Boolean(callback));
  const [availability, setAvailability] = useState<GitHubAvailability>({
    status: "loading",
  });
  const [loadAttempt, setLoadAttempt] = useState(0);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let active = true;
    getAuthSetupStatus().then(
      (result) => {
        if (active) {
          setAvailability({ status: "ready", available: result.githubLoginAvailable });
        }
      },
      (error: unknown) => {
        if (active) {
          setAvailability({
            status: "error",
            message: error instanceof Error ? error.message : t.oauthStartFailed,
          });
        }
      },
    );
    return () => { active = false; };
  }, [enabled, loadAttempt, t.oauthStartFailed]);

  useEffect(() => () => {
    const controller = requestRef.current;
    requestRef.current = null;
    controller?.abort();
  }, []);

  function cancelSignIn() {
    if (callback && !callbackConsumedRef.current) {
      callbackConsumedRef.current = true;
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}`);
    }
    const controller = requestRef.current;
    requestRef.current = null;
    controller?.abort();
    setIsCompleting(false);
    setRequestError(null);
    setIsPending(false);
  }

  const resetAfterNavigation = useEffectEvent(cancelSignIn);
  useEffect(() => {
    const hide = () => resetAfterNavigation();
    const show = (event: PageTransitionEvent) => {
      if (event.persisted) resetAfterNavigation();
    };
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", show);
    return () => {
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", show);
    };
  }, []);

  function showRequestError(error: unknown) {
    if (isApiErrorCode(error, "OAUTH_NOT_CONFIGURED") || isApiErrorCode(error, "OAUTH_NOT_BOUND")) {
      setAvailability({ status: "ready", available: false });
      toast.info(t.oauthGithubNotBound, { closeButton: true });
    } else {
      const message = error instanceof Error ? error.message : "";
      setRequestError(resolveOAuthLoginError(message, t, message || t.oauthStartFailed));
    }
  }

  const consumeCallback = useEffectEvent(async (result: OAuthLoginCallback) => {
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}`);
    setRequestError(null);
    if ("error" in result) {
      setRequestError(resolveOAuthLoginError(result.error, t));
      setIsPending(false);
      return;
    }

    const controller = new AbortController();
    requestRef.current = controller;
    setIsPending(true);
    setIsCompleting(true);
    try {
      await completeGitHubLogin(result.code, controller.signal, onComplete);
    } catch (error) {
      if (!controller.signal.aborted && requestRef.current === controller && !isAbortError(error)) {
        showRequestError(error);
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setIsCompleting(false);
        setIsPending(false);
      }
    }
  });

  useEffect(() => {
    if (!enabled || !callback) return;
    let active = true;
    queueMicrotask(() => {
      if (!active || callbackConsumedRef.current) return;
      callbackConsumedRef.current = true;
      void consumeCallback(callback);
    });
    return () => { active = false; };
  }, [callback, enabled]);

  async function signIn() {
    if (!enabled || isPending || requestRef.current || availability.status !== "ready") return;

    setRequestError(null);
    if (!availability.available) {
      toast.info(t.oauthGithubNotBound, { closeButton: true });
      return;
    }

    const controller = new AbortController();
    requestRef.current = controller;
    setIsPending(true);
    let redirected = false;
    try {
      await redirectToGitHubLogin(controller.signal);
      redirected = true;
    } catch (error) {
      if (!controller.signal.aborted && requestRef.current === controller && !isAbortError(error)) {
        showRequestError(error);
      }
    } finally {
      if (requestRef.current === controller && !redirected) {
        requestRef.current = null;
        setIsPending(false);
      }
    }
  }

  return {
    controls: {
      availability,
      isPending,
      requestError,
      retry: () => {
        setAvailability({ status: "loading" });
        setLoadAttempt((current) => current + 1);
      },
      signIn,
    } satisfies OAuthLoginControls,
    isCompleting,
  };
}
