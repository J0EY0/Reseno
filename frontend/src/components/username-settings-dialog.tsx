import { PasswordField } from "@/components/auth/password-field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import type { UsernameSettingsController } from "@/components/use-username-settings";
import type { AppMessages } from "@/i18n";

export function UsernameSettingsDialog({
  t,
  controller,
}: {
  t: AppMessages;
  controller: UsernameSettingsController;
}) {
  return (
    <Dialog open={controller.isOpen} onOpenChange={controller.changeOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="w-40 max-w-full [&:lang(zh)]:w-28"
        >
          {t.updateUsername}
        </Button>
      </DialogTrigger>
      <DialogContent
        showCloseButton={!controller.isSubmitting}
        closeLabel={t.close}
        aria-describedby={undefined}
        className="w-[min(420px,calc(100vw-2rem))]"
      >
        <form className="grid gap-4" onSubmit={controller.submit} noValidate>
          <DialogHeader>
            <DialogTitle>{t.updateUsername}</DialogTitle>
          </DialogHeader>
          <fieldset disabled={controller.isSubmitting} className="grid gap-3">
            <Field
              data-invalid={Boolean(controller.formErrors.newUsername)}
              className="gap-2"
            >
              <FieldLabel htmlFor="new-username">{t.newUsername}</FieldLabel>
              <Input
                id="new-username"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                value={controller.newUsername}
                placeholder={t.newUsername}
                aria-invalid={Boolean(controller.formErrors.newUsername)}
                aria-describedby={
                  controller.formErrors.newUsername
                    ? "new-username-error"
                    : undefined
                }
                onChange={(event) =>
                  controller.changeUsername(event.target.value)
                }
              />
              <FieldError id="new-username-error">
                {controller.formErrors.newUsername}
              </FieldError>
            </Field>
            <PasswordField
              id="username-current-password"
              label={t.currentPassword}
              autoComplete="current-password"
              value={controller.currentPassword}
              placeholder={t.currentPassword}
              error={controller.formErrors.currentPassword}
              showPasswordLabel={t.loginShowPassword}
              hidePasswordLabel={t.loginHidePassword}
              onChange={controller.changePassword}
            />
          </fieldset>
          <DialogFooter>
            <DialogClose asChild>
              <Button
                type="button"
                variant="outline"
                disabled={controller.isSubmitting}
              >
                {t.cancel}
              </Button>
            </DialogClose>
            <Button
              type="submit"
              aria-busy={controller.isSubmitting}
              disabled={controller.isSubmitting || !controller.hasChanges}
            >
              {controller.isSubmitting ? (
                <Spinner data-icon="inline-start" aria-hidden="true" />
              ) : null}
              {controller.isSubmitting ? t.usernameUpdating : t.updateUsername}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
