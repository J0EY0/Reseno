import GithubIcon from "@lobehub/icons/es/Github/components/Mono";

import { AuthLoadingSweep } from "@/components/auth/auth-loading-sweep";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldSeparator } from "@/components/ui/field";
import type { OAuthLoginControls } from "@/hooks/use-oauth-login";
import type { AppMessages } from "@/i18n";

export function ProviderLoginButtons({
  disabled,
  oauth,
  t,
}: {
  disabled: boolean;
  oauth: OAuthLoginControls;
  t: AppMessages;
}) {
  const { availability, isPending, requestError } = oauth;
  const isDisabled = disabled || isPending || availability.status !== "ready";

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
            aria-disabled={isDisabled}
            disabled={isDisabled}
            onClick={() => void oauth.signIn()}
          >
            <AuthLoadingSweep />
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
        <FieldError>
          {requestError ??
            (availability.status === "error" ? availability.message : null)}
        </FieldError>
        {availability.status === "error" ? (
          <Button
            type="button"
            variant="link"
            size="sm"
            className="self-center"
            disabled={disabled || isPending}
            onClick={oauth.retry}
          >
            {t.retry}
          </Button>
        ) : null}
      </Field>
    </>
  );
}
