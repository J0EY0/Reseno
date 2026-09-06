import GithubIcon from "@lobehub/icons/es/Github/components/Mono";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldSeparator } from "@/components/ui/field";
import type { AppMessages } from "@/i18n";
import { isApiErrorCode } from "@/lib/api-client";
import { requestOAuthAuthorization } from "@/lib/auth-oauth";

export function ProviderLoginButtons({
  disabled,
  isPending,
  onPendingChange,
  t,
}: {
  disabled: boolean;
  isPending: boolean;
  onPendingChange: (isPending: boolean) => void;
  t: AppMessages;
}) {
  const [requestError, setRequestError] = useState<string | null>(null);

  async function signIn() {
    if (disabled || isPending) {
      return;
    }
    setRequestError(null);
    onPendingChange(true);

    try {
      const authorizationUrl = await requestOAuthAuthorization("github", "login");
      window.location.assign(authorizationUrl);
    } catch (error) {
      if (
        isApiErrorCode(error, "OAUTH_NOT_CONFIGURED") ||
        isApiErrorCode(error, "OAUTH_NOT_BOUND")
      ) {
        toast.info(t.oauthGithubNotBound, { closeButton: true });
      } else {
        setRequestError(error instanceof Error ? error.message : t.oauthStartFailed);
      }
      onPendingChange(false);
    }
  }

  return (
    <>
      <FieldSeparator className="*:data-[slot=field-separator-content]:bg-card">
        {t.oauthContinueSeparator}
      </FieldSeparator>
      <Field aria-label={t.oauthSignInTitle}>
        <div className="flex justify-center">
          <Button
            type="button"
            variant="outline"
            size="icon-lg"
            className="auth-loading-button h-11 w-30"
            aria-label={t.oauthContinueGithub}
            title={t.oauthContinueGithub}
            aria-busy={isPending || undefined}
            aria-disabled={disabled || isPending}
            disabled={disabled || isPending}
            onClick={() => void signIn()}
          >
            <span className="auth-loading-border" aria-hidden="true" />
            <GithubIcon data-icon="inline-start" aria-hidden="true" />
          </Button>
        </div>
        <span
          data-slot="auth-pending-announcement"
          className="sr-only"
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {isPending ? t.oauthStarting : ""}
        </span>
        <FieldError>{requestError}</FieldError>
      </Field>
    </>
  );
}
