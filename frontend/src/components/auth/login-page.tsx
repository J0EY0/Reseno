import {
  ArrowRight,
  UserRound,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'

import type { AppMessages } from '@/i18n'
import {
  validateLoginForm,
  type LoginFormErrors,
} from '@/lib/auth-validation'

import { AuthPageShell } from '@/components/auth/auth-page-shell'
import { PasswordField } from '@/components/auth/password-field'
import { Button } from '@/components/ui/button'
import { Field, FieldError, FieldLabel } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const nextErrors = validateLoginForm(username, password, t)

    if (Object.keys(nextErrors).length > 0) {
      setFormErrors(nextErrors)
      return
    }

    setFormErrors({})
    setIsSubmitting(true)

    try {
      const result = await onSubmitCredentials({
        username: username.trim(),
        password,
      })

      if (!result.ok && !result.errorShown) {
        toast.error(result.error ?? t.loginInvalidCredentials, {
          closeButton: true,
        })
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthPageShell
      title={
        <span className="flex flex-col gap-2 leading-none lg:-translate-y-8">
          <span>{t.loginHeroTitle}</span>
          <span className="whitespace-nowrap">{t.brandTitle}</span>
        </span>
      }
      formTitle={t.loginFormTitle}
    >
      <form className="grid gap-5" onSubmit={handleSubmit} noValidate>
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
          className="mt-1 h-11 rounded-xl"
          disabled={isSubmitting}
        >
          {isSubmitting ? (
            <Spinner data-icon="inline-start" aria-label={t.loginSubmitting} />
          ) : null}
          {isSubmitting ? t.loginSubmitting : t.loginSubmit}
          {!isSubmitting ? <ArrowRight data-icon="inline-end" /> : null}
        </Button>
      </form>
    </AuthPageShell>
  )
}
