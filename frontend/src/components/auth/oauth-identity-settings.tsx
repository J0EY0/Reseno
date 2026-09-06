import GithubIcon from "@lobehub/icons/es/Github/components/Mono";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { SettingsRow } from "@/components/settings-controls";
import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import {
  getOAuthIdentities,
  requestOAuthAuthorization,
  startGitHubSetup,
  unbindOAuth,
} from "@/lib/auth-oauth";

export function OAuthIdentitySettings({ t }: { t: AppMessages }) {
  const [data, setData] = useState<
    Awaited<ReturnType<typeof getOAuthIdentities>> | null
  >(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [isPending, setIsPending] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const identity = data?.identities.find((item) => item.provider === "github");
  const configured = data?.providers.some(
    (item) => item.provider === "github" && item.configured,
  );

  useEffect(() => {
    let active = true;

    getOAuthIdentities().then(
      (result) => {
        if (active) {
          setData(result);
        }
      },
      () => {
        if (active) {
          setLoadFailed(true);
        }
      },
    );

    return () => {
      active = false;
    };
  }, [loadAttempt]);

  async function changeBinding() {
    setRequestError(null);
    setIsPending(true);

    try {
      if (identity) {
        await unbindOAuth("github");
        setData((current) => current ? { ...current, identities: [] } : current);
        toast.success(t.oauthUnbound);
      } else if (configured) {
        window.location.assign(
          await requestOAuthAuthorization("github", "bind"),
        );
      } else {
        await startGitHubSetup();
      }
    } catch (error) {
      setRequestError(
        error instanceof Error ? error.message : t.oauthBindingFailed,
      );
    } finally {
      setIsPending(false);
    }
  }

  if (loadFailed) {
    return (
      <div className="flex flex-col items-start gap-3 px-5 py-4 sm:px-6">
        <FieldError>{t.oauthSettingsLoadFailed}</FieldError>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setLoadFailed(false);
            setLoadAttempt((current) => current + 1);
          }}
        >
          {t.retry}
        </Button>
      </div>
    );
  }

  const description = !data
    ? t.oauthLoading
    : identity
      ? t.oauthConnectedDescription
      : configured
        ? t.oauthConnectDescription
        : t.oauthSetupDescription;
  const actionLabel = identity
    ? t.oauthDisconnect
    : configured
      ? t.oauthConnectGithub
      : t.oauthSetupGithub;

  return (
    <>
      <SettingsRow icon={<GithubIcon />} label="GitHub" description={description}>
        <div
          className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-end"
          aria-busy={!data || isPending}
        >
          {!data ? (
            <Skeleton className="h-9 w-24 motion-reduce:animate-none" />
          ) : (
            <>
              {identity ? (
                <span
                  className="min-w-0 flex-1 truncate text-sm text-muted-foreground"
                  title={identity.label}
                >
                  {identity.label}
                </span>
              ) : null}
              <Button
                type="button"
                variant="outline"
                className="w-full sm:w-auto"
                disabled={isPending}
                aria-label={identity ? `${actionLabel} GitHub` : actionLabel}
                onClick={() => void changeBinding()}
              >
                {isPending ? (
                  <Spinner data-icon="inline-start" aria-label={t.oauthUpdating} />
                ) : null}
                {isPending ? t.oauthUpdating : actionLabel}
              </Button>
            </>
          )}
        </div>
      </SettingsRow>
      {requestError ? (
        <FieldError className="px-5 pb-4 sm:px-6">{requestError}</FieldError>
      ) : null}
    </>
  );
}
