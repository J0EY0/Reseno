import type { AppMessages } from "@/i18n";
import {
  completeOAuth,
  requestGitHubSetup,
  requestOAuthAuthorization,
  submitGitHubSetup,
  type OAuthResult,
} from "@/lib/auth-oauth";

export const OAUTH_TAB_RESULT = "resumate:oauth:result";
export const OAUTH_TAB_RECEIVED = "resumate:oauth:received";

export type OAuthProgress =
  | { stage: "preparing" | "waiting" }
  | { stage: "blocked"; open: () => void };

interface OAuthBindingOptions {
  setup?: boolean;
  signal: AbortSignal;
  onProgress: (progress: OAuthProgress | null) => void;
  onComplete: (result: OAuthResult, signal: AbortSignal) => Promise<void>;
  t: AppMessages;
}

export async function authorizeGitHubBinding({
  setup = false,
  signal,
  onProgress,
  onComplete,
  t,
}: OAuthBindingOptions): Promise<void> {
  signal.throwIfAborted();
  const name = `resumate-github-${crypto.randomUUID()}`;
  const controller = new AbortController();
  const origin = window.location.origin;
  let tab: Window | null = null;
  let handling = false;
  let settled = false;

  await new Promise<void>((resolve, reject) => {
    function finish(error?: unknown) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", receiveResult);
      signal.removeEventListener("abort", abort);
      window.clearInterval(closeTimer);
      window.clearTimeout(timeout);
      window.clearTimeout(preparingTimer);
      controller.abort();
      onProgress(null);
      tab?.close();
      if (tab && !signal.aborted) window.focus();
      if (error) reject(error);
      else resolve();
    }

    function abort() {
      finish(signal.reason);
    }

    async function receiveResult(event: MessageEvent<unknown>) {
      if (!tab || event.origin !== origin || event.source !== tab || handling || settled) {
        return;
      }
      const result = event.data;
      if (!result || typeof result !== "object" || !("type" in result) || result.type !== OAUTH_TAB_RESULT) {
        return;
      }
      const payload = result as Record<string, unknown>;
      if (typeof payload.error === "string" && payload.error.length <= 128) {
        finish(new Error((t.apiMessages as Record<string, string>)[payload.error] ?? t.oauthStartFailed));
        return;
      }
      if (typeof payload.code !== "string" || !payload.code || payload.code.length > 128 || payload.intent !== "bind") {
        return;
      }

      handling = true;
      tab?.postMessage({ type: OAUTH_TAB_RECEIVED }, origin);
      try {
        const completion = await completeOAuth(payload.code, controller.signal, "bind");
        controller.signal.throwIfAborted();
        await onComplete(completion, controller.signal);
        finish();
      } catch (error) {
        finish(error instanceof Error && error.message === "OAUTH_INVALID_STATE"
          ? new Error(t.apiMessages.OAUTH_INVALID_STATE)
          : error);
      }
    }

    const closeTimer = window.setInterval(() => {
      if (tab?.closed) finish(new Error(t.oauthTabClosed));
    }, 250);
    const timeout = window.setTimeout(() => finish(new Error(t.oauthTabTimeout)), 10 * 60 * 1_000);
    const preparingTimer = window.setTimeout(() => {
      if (!settled) onProgress({ stage: "preparing" });
    }, 150);
    window.addEventListener("message", receiveResult);
    signal.addEventListener("abort", abort, { once: true });

    void (async () => {
      try {
        const authorization = setup
          ? await requestGitHubSetup(controller.signal)
          : await requestOAuthAuthorization("github", "bind", controller.signal);
        controller.signal.throwIfAborted();
        window.clearTimeout(preparingTimer);

        function openAuthorization() {
          if (settled || tab) return;
          try {
            tab = window.open(typeof authorization === "string" ? authorization : "", name);
            if (!tab) {
              onProgress({ stage: "blocked", open: openAuthorization });
              return;
            }
            if (typeof authorization !== "string") {
              submitGitHubSetup(name, authorization);
            }
            tab.focus();
            onProgress({ stage: "waiting" });
          } catch (error) {
            finish(error);
          }
        }

        openAuthorization();
      } catch (error) {
        finish(error);
      }
    })();
  });
}
