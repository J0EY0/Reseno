import GithubIcon from "@lobehub/icons/es/Github/components/Mono";

import type { useOAuthIdentitySettings } from "@/components/auth/use-oauth-identity-settings";
import { SettingsRow } from "@/components/settings-controls";
import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";

export function OAuthIdentitySettings({
  t,
  controller,
}: {
  t: AppMessages;
  controller: ReturnType<typeof useOAuthIdentitySettings>;
}) {
  const {
    data,
    identity,
    configured,
    loadFailed,
    isPending,
    unbindError,
    retryLoad,
    changeBinding,
  } = controller;

  if (loadFailed) {
    return (
      <SettingsRow icon={<GithubIcon />} label="GitHub">
        <div className="flex justify-end">
          <Button
            type="button"
            variant="outline"
            onClick={retryLoad}
          >
            {t.retry}
          </Button>
        </div>
      </SettingsRow>
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
          className="flex min-w-0 items-center justify-end gap-3"
          aria-busy={!data || isPending}
        >
          {!data ? (
            <Skeleton className="h-9 w-24 motion-reduce:animate-none" />
          ) : (
            <>
              <span
                role="status"
                className="inline-flex min-w-0 max-w-full items-center gap-2 text-sm text-muted-foreground"
              >
                {isPending && identity ? (
                  <Spinner
                    aria-hidden="true"
                    className="shrink-0 motion-reduce:animate-none"
                  />
                ) : (
                  <span
                    aria-hidden="true"
                    className={cn(
                      "size-2 shrink-0 rounded-full",
                      identity ? "bg-success" : "bg-destructive",
                    )}
                  />
                )}
                {identity ? (
                  <span className="sr-only">
                    {isPending ? t.oauthUpdating : t.oauthConnected}: {" "}
                  </span>
                ) : null}
                <span
                  className="truncate"
                  title={identity?.label}
                >
                  {identity?.label ?? t.oauthNotConnected}
                </span>
              </span>
              <Button
                type="button"
                variant="outline"
                className="shrink-0"
                disabled={isPending}
                aria-busy={isPending}
                aria-label={identity ? `${actionLabel} GitHub` : actionLabel}
                onClick={() => void changeBinding()}
              >
                {actionLabel}
              </Button>
            </>
          )}
        </div>
      </SettingsRow>
      {unbindError ? (
        <FieldError className="px-5 pb-4 sm:px-6">{unbindError}</FieldError>
      ) : null}
    </>
  );
}
