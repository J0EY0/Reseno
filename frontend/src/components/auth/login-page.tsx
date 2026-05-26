import {
  ArrowRight,
  FileText,
  UserRound,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'

import type { AppMessages } from '@/i18n'
import {
  validateLoginForm,
  type LoginFormErrors,
} from '@/lib/auth-validation'

import { PasswordField } from '@/components/auth/password-field'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Toaster } from '@/components/ui/sonner'
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
    <main className="relative min-h-svh overflow-hidden bg-background text-foreground">
      <Toaster position="bottom-right" closeButton />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(24,24,27,0.08),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(24,24,27,0.06),transparent_24%)]" />
      <div className="relative flex min-h-svh items-center justify-center p-5 sm:p-8">
        <Card className="w-full max-w-5xl overflow-hidden rounded-[32px] border-border/80 shadow-xl">
          <div className="grid lg:grid-cols-[1.08fr_0.92fr]">
            <div className="flex items-start border-b border-border bg-muted/25 p-8 lg:border-b-0 lg:border-r lg:p-10">
              <div className="space-y-6 pt-1 lg:pt-3">
                <div className="inline-flex items-center gap-3 rounded-full border border-border/80 bg-background px-3 py-2 shadow-sm">
                  <div className="flex size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                    <FileText className="size-4" />
                  </div>
                  <p className="text-sm font-semibold tracking-tight text-foreground">
                    {t.brandTitle}
                  </p>
                </div>

                <div>
                  <h1 className="max-w-[9ch] text-5xl font-black tracking-[-0.07em] text-foreground sm:text-6xl">
                    {t.loginTitle}
                  </h1>
                </div>
              </div>
            </div>

            <div className="flex p-8 lg:p-10">
              <div className="w-full self-center">
                <CardHeader className="p-0">
                  <CardTitle className="text-3xl font-bold tracking-tight">
                    {t.loginFormTitle}
                  </CardTitle>
                </CardHeader>

                <CardContent className="p-0 pt-8">
                  <form className="grid gap-5" onSubmit={handleSubmit} noValidate>
                    <div className="grid gap-2">
                      <label
                        htmlFor="username"
                        className="text-sm font-medium text-foreground"
                      >
                        {t.loginUsernameLabel}
                      </label>
                      <div className="relative">
                        <UserRound className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                        <Input
                          id="username"
                          autoComplete="username"
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
                          className="h-11 rounded-xl border-border bg-background pl-10"
                        />
                      </div>
                      {formErrors.username ? (
                        <p id="username-error" className="text-xs text-red-600">
                          {formErrors.username}
                        </p>
                      ) : null}
                    </div>

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
                      {isSubmitting ? t.loginSubmitting : t.loginSubmit}
                      <ArrowRight className="size-4" />
                    </Button>
                  </form>
                </CardContent>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </main>
  )
}
