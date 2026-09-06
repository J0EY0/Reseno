import { useEffect, useEffectEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AuthPageShell } from "@/components/auth/auth-page-shell";
import { WorkspaceEntrySkeleton } from "@/components/workspace/workspace-entry-skeleton";
import { Button } from "@/components/ui/button";
import type { AppMessages } from "@/i18n";
import { completeOAuth, type OAuthIntent } from "@/lib/auth-oauth";
import { loadAuthSession } from "@/lib/auth-session";

export function OAuthCallbackPage({
  onComplete,
  t,
}: {
  onComplete: (
    destination: "resume" | "settings",
    signal: AbortSignal,
  ) => Promise<void>;
  t: AppMessages;
}) {
  const navigate = useNavigate();
  const [params] = useState(() => new URLSearchParams(window.location.hash.slice(1)));
  const [intent, setIntent] = useState<OAuthIntent>(() =>
    params.get("intent") === "bind" ? "bind" : "login",
  );
  const [error, setError] = useState<string | null>(() =>
    params.get("error") || (params.get("code") ? null : "OAUTH_INVALID_STATE"),
  );
  const acceptSession = useEffectEvent(onComplete);
  const code = params.get("code");

  useEffect(() => {
    window.history.replaceState(window.history.state, "", window.location.pathname);
    if (!code || params.get("error")) {
      return;
    }

    const controller = new AbortController();
    void (async () => {
      try {
        const { intent } = await completeOAuth(code, controller.signal);
        if (controller.signal.aborted) {
          return;
        }

        setIntent(intent);
        await acceptSession(
          intent === "bind" ? "settings" : "resume",
          controller.signal,
        );
      } catch (reason) {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "REQUEST_FAILED");
        }
      }
    })();

    return () => {
      controller.abort();
    };
  }, [code, params]);

  const apiMessages = t.apiMessages as Record<string, string>;
  const errorDescription = error
    ? params.get("error") === error || error === "OAUTH_INVALID_STATE"
      ? apiMessages[error] ?? apiMessages.REQUEST_FAILED
      : apiMessages[error] ?? error
    : null;
  const hasSession = loadAuthSession();

  if (!error) {
    return (
      <WorkspaceEntrySkeleton
        destination={intent === "bind" ? "settings" : "resume"}
        label={t.workspaceLoading}
      />
    );
  }

  return (
    <AuthPageShell
      formTitle={t.oauthCallbackErrorTitle}
      description={errorDescription ?? undefined}
    >
      <Button onClick={() => navigate(hasSession ? "/settings" : "/login", { replace: true })}>
        {hasSession ? t.oauthBackToSettings : t.oauthBackToLogin}
      </Button>
    </AuthPageShell>
  );
}
