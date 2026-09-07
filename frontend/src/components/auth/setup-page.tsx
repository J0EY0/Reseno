import { ArrowRight, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import {
  validateSetupForm,
  type SetupFormErrors,
} from "@/lib/auth-validation";

import { AuthPageShell } from "@/components/auth/auth-page-shell";
import { PasswordField } from "@/components/auth/password-field";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group";
import { Spinner } from "@/components/ui/spinner";

type SetupResult = {
  ok: boolean;
  error?: string;
  errorShown?: boolean;
};

export function SetupPage({
  onSubmitCredentials,
  t,
}: {
  onSubmitCredentials: (credentials: {
    username: string;
    password: string;
    confirmPassword: string;
  }) => Promise<SetupResult>;
  t: AppMessages;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [formErrors, setFormErrors] = useState<SetupFormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextErrors = validateSetupForm(
      username,
      password,
      confirmPassword,
      t,
    );
    if (Object.keys(nextErrors).length > 0) {
      setFormErrors(nextErrors);
      return;
    }

    setFormErrors({});
    setIsSubmitting(true);

    try {
      const result = await onSubmitCredentials({
        username: username.trim(),
        password,
        confirmPassword,
      });

      if (!result.ok && !result.errorShown) {
        toast.error(result.error ?? t.apiMessages.REQUEST_FAILED, {
          closeButton: true,
        });
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthPageShell brandTitle={t.brandTitle} formTitle={t.setupFormTitle}>
      <form className="grid gap-5" onSubmit={handleSubmit} noValidate>
        <Field data-invalid={Boolean(formErrors.username)} className="gap-2">
          <FieldLabel htmlFor="setup-username">
            {t.loginUsernameLabel}
          </FieldLabel>
          <InputGroup>
            <InputGroupAddon>
              <UserRound />
            </InputGroupAddon>
            <InputGroupInput
              id="setup-username"
              autoComplete="username"
              autoFocus
              aria-describedby={
                formErrors.username ? "setup-username-error" : undefined
              }
              aria-invalid={Boolean(formErrors.username)}
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
                setFormErrors((current) => ({
                  ...current,
                  username: undefined,
                }));
              }}
              placeholder={t.loginUsernamePlaceholder}
            />
          </InputGroup>
          <FieldError id="setup-username-error">
            {formErrors.username}
          </FieldError>
        </Field>

        <PasswordField
          id="setup-password"
          label={t.loginPasswordLabel}
          autoComplete="new-password"
          value={password}
          placeholder={t.loginPasswordPlaceholder}
          error={formErrors.password}
          showPasswordLabel={t.loginShowPassword}
          hidePasswordLabel={t.loginHidePassword}
          onChange={(value) => {
            setPassword(value);
            setFormErrors((current) => ({
              ...current,
              password: undefined,
              confirmPassword:
                confirmPassword === value
                  ? undefined
                  : current.confirmPassword,
            }));
          }}
        />

        <PasswordField
          id="setup-confirm-password"
          label={t.setupConfirmPasswordLabel}
          autoComplete="new-password"
          value={confirmPassword}
          placeholder={t.setupConfirmPasswordPlaceholder}
          error={formErrors.confirmPassword}
          showPasswordLabel={t.loginShowPassword}
          hidePasswordLabel={t.loginHidePassword}
          onChange={(value) => {
            setConfirmPassword(value);
            setFormErrors((current) => ({
              ...current,
              confirmPassword: undefined,
            }));
          }}
        />

        <Button
          type="submit"
          size="lg"
          className="mt-1 h-11 rounded-xl"
          disabled={isSubmitting}
        >
          {isSubmitting ? (
            <Spinner data-icon="inline-start" aria-label={t.setupSubmitting} />
          ) : null}
          {isSubmitting ? t.setupSubmitting : t.setupSubmit}
          {!isSubmitting ? <ArrowRight data-icon="inline-end" /> : null}
        </Button>
      </form>
    </AuthPageShell>
  );
}
