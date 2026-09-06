import { UserRound } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import type { AppMessages } from '@/i18n'
import {
  validateLoginForm,
  type LoginFormErrors,
} from '@/lib/auth-validation'

import { AuthPageShell } from '@/components/auth/auth-page-shell'
import { PasswordField } from '@/components/auth/password-field'
import { ProviderLoginButtons } from '@/components/auth/provider-login-buttons'
import { Button } from '@/components/ui/button'
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '@/components/ui/input-group'
import { toast } from 'sonner'

type LoginResult = {
  ok: boolean
  error?: string
  errorShown?: boolean
}

export function LoginPage({
  t,
  onSubmitCredentials,
}: {
  t: AppMessages
  onSubmitCredentials: (credentials: {
    username: string
    password: string
  }) => Promise<LoginResult>
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [formErrors, setFormErrors] = useState<LoginFormErrors>({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isOAuthPending, setIsOAuthPending] = useState(false)
  const isPending = isSubmitting || isOAuthPending

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (isPending) {
      return
    }

    const nextErrors = validateLoginForm(username, password, t)

    if (Object.keys(nextErrors).length > 0) {
      setFormErrors(nextErrors)
      return
    }

    setFormErrors({})
    setIsSubmitting(true)

    let shouldResetPending = true

    try {
      const result = await onSubmitCredentials({
        username: username.trim(),
        password,
      })

      if (result.ok) {
        shouldResetPending = false
        return
      }

      if (!result.ok && !result.errorShown) {
        toast.error(result.error ?? t.loginInvalidCredentials, {
          closeButton: true,
        })
      }
    } finally {
      if (shouldResetPending) {
        setIsSubmitting(false)
      }
    }
  }

  return (
    <AuthPageShell
      formTitle={t.loginFormTitle}
      description={t.loginFormSubtitle}
    >
      <form onSubmit={handleSubmit} noValidate>
        <FieldGroup className="gap-6">
          <Field
            data-invalid={Boolean(formErrors.username)}
            className="gap-2"
          >
            <FieldLabel htmlFor="username">{t.loginUsernameLabel}</FieldLabel>
            <InputGroup>
              <InputGroupAddon>
                <UserRound />
              </InputGroupAddon>
              <InputGroupInput
                id="username"
                autoComplete="username"
                autoFocus
                aria-describedby={
                  formErrors.username ? 'username-error' : undefined
                }
                aria-invalid={Boolean(formErrors.username)}
                value={username}
                onChange={(event) => {
                  setUsername(event.target.value)
                  setFormErrors((current) => ({
                    ...current,
                    username: undefined,
                  }))
                }}
                placeholder={t.loginUsernamePlaceholder}
              />
            </InputGroup>
            <FieldError id="username-error">{formErrors.username}</FieldError>
          </Field>

          <PasswordField
            id="password"
            label={t.loginPasswordLabel}
            autoComplete="current-password"
            value={password}
            placeholder={t.loginPasswordPlaceholder}
            error={formErrors.password}
            showPasswordLabel={t.loginShowPassword}
            hidePasswordLabel={t.loginHidePassword}
            onChange={(value) => {
              setPassword(value)
              setFormErrors((current) => ({
                ...current,
                password: undefined,
              }))
            }}
          />

          <Button
            type="submit"
            size="lg"
            className="auth-loading-button h-11 w-full"
            aria-busy={isSubmitting || undefined}
            aria-disabled={isPending}
            disabled={isPending}
          >
            <span className="auth-loading-border" aria-hidden="true" />
            {t.loginSubmit}
          </Button>
          <span
            data-slot="auth-pending-announcement"
            className="sr-only"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {isSubmitting ? t.loginSubmitting : ''}
          </span>

          <ProviderLoginButtons
            t={t}
            disabled={isSubmitting}
            isPending={isOAuthPending}
            onPendingChange={setIsOAuthPending}
          />
        </FieldGroup>
      </form>
    </AuthPageShell>
  )
}
