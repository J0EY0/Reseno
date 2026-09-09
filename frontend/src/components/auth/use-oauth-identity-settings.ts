import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { isAbortError } from "@/lib/api-client";
import {
  getOAuthIdentities,
  unbindOAuth,
  type OAuthIdentitySettingsState,
} from "@/lib/auth-oauth";
import {
  authorizeGitHubBinding,
  type OAuthProgress,
} from "@/lib/auth-oauth-tab";

export function useOAuthIdentitySettings(t: AppMessages) {
  const [state, setState] = useState<OAuthIdentitySettingsState>();
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [progress, setProgress] = useState<OAuthProgress | null>(null);
  const [pendingAction, setPendingAction] = useState<
    "authorize" | "unbind" | null
  >(null);
  const requestRef = useRef<AbortController | null>(null);
  const [unbindError, setUnbindError] = useState<string | null>(null);
  const data = state?.status === "ready" ? state.data : null;
  const identity = data?.identities.find((item) => item.provider === "github");
  const configured = data?.providers.some(
    (item) => item.provider === "github" && item.configured,
  );

  useEffect(() => {
    let active = true;
    getOAuthIdentities().then(
      (result) => {
        if (active) {
          setState({ status: "ready", data: result });
        }
      },
      () => {
        if (active) {
          setState({ status: "error" });
        }
      },
    );

    return () => {
      active = false;
    };
  }, [loadAttempt]);

  useEffect(
    () => () => {
      const controller = requestRef.current;
      requestRef.current = null;
      controller?.abort();
    },
    [],
  );

  function retryLoad() {
    setState(undefined);
    setLoadAttempt((current) => current + 1);
  }

  function cancelAuthorization() {
    const controller = requestRef.current;
    if (!controller || pendingAction !== "authorize") return;
    requestRef.current = null;
    controller.abort();
    setProgress(null);
    setPendingAction(null);
    toast.error(t.oauthBindingFailed);
  }

  async function changeBinding() {
    if (requestRef.current || !data) {
      return;
    }

    const controller = new AbortController();
    requestRef.current = controller;
    setUnbindError(null);
    setPendingAction(identity ? "unbind" : "authorize");

    try {
      if (identity) {
        await unbindOAuth("github");
        controller.signal.throwIfAborted();
        setState({ status: "ready", data: { ...data, identities: [] } });
        toast.success(t.oauthUnbound);
      } else {
        await authorizeGitHubBinding({
          setup: !configured,
          signal: controller.signal,
          onProgress: (nextProgress) => {
            if (requestRef.current === controller) setProgress(nextProgress);
          },
          onComplete: async (_, signal) => {
            try {
              const result = await getOAuthIdentities(signal);
              signal.throwIfAborted();
              setState({ status: "ready", data: result });
            } catch (error) {
              if (!signal.aborted) {
                setState({ status: "error" });
              }
              throw error;
            }
          },
          t,
        });
        if (!controller.signal.aborted && requestRef.current === controller) {
          toast.success(t.oauthBindingSuccess);
        }
      }
    } catch (error) {
      if (
        !controller.signal.aborted &&
        requestRef.current === controller &&
        !isAbortError(error)
      ) {
        if (identity) {
          setUnbindError(
            error instanceof Error
              ? error.message
              : t.apiMessages.REQUEST_FAILED,
          );
        } else {
          toast.error(t.oauthBindingFailed);
        }
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        if (!controller.signal.aborted) {
          setPendingAction(null);
        }
      }
    }
  }

  return {
    data,
    identity,
    configured,
    loadFailed: state?.status === "error",
    isPending: pendingAction !== null,
    progress,
    cancelAuthorization,
    unbindError,
    retryLoad,
    changeBinding,
  };
}
