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
import { Spinner } from "@/components/ui/spinner";
import type { PasswordSettingsController } from "@/components/use-password-settings";
import type { AppMessages } from "@/i18n";

export function PasswordSettingsDialog({
  t,
  controller,
}: {
  t: AppMessages;
  controller: PasswordSettingsController;
}) {
  return (
    <Dialog open={controller.isOpen} onOpenChange={controller.changeOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" className="w-full sm:w-auto">
          {t.updatePassword}
        </Button>
      </DialogTrigger>
      <DialogContent
        showCloseButton
        closeLabel={t.close}
        aria-describedby={undefined}
        className="w-[min(420px,calc(100vw-2rem))]"
      >
        <form className="grid gap-4" onSubmit={controller.submit}>
          <DialogHeader>
            <DialogTitle>{t.passwordSettingsTitle}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <PasswordField
              id="current-password"
              label={t.currentPassword}
              autoComplete="current-password"
              value={controller.currentPassword}
              placeholder={t.currentPassword}
              error={controller.formErrors.currentPassword}
              showPasswordLabel={t.loginShowPassword}
              hidePasswordLabel={t.loginHidePassword}
              onChange={controller.changeCurrentPassword}
            />
            <PasswordField
              id="new-password"
              label={t.newPassword}
              autoComplete="new-password"
              value={controller.newPassword}
              placeholder={t.newPassword}
              error={controller.formErrors.newPassword}
              showPasswordLabel={t.loginShowPassword}
              hidePasswordLabel={t.loginHidePassword}
              onChange={controller.changeNewPassword}
            />
            <PasswordField
              id="confirm-password"
              label={t.confirmPassword}
              autoComplete="new-password"
              value={controller.confirmPassword}
              placeholder={t.confirmPassword}
              error={controller.formErrors.confirmPassword}
              showPasswordLabel={t.loginShowPassword}
              hidePasswordLabel={t.loginHidePassword}
              onChange={controller.changeConfirmPassword}
            />
            {controller.requestError ? (
              <p className="text-sm text-destructive">
                {controller.requestError}
              </p>
            ) : null}
          </div>
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
            <Button type="submit" disabled={controller.isSubmitting}>
              {controller.isSubmitting ? (
                <Spinner
                  data-icon="inline-start"
                  aria-label={t.passwordUpdating}
                />
              ) : null}
              {controller.isSubmitting ? t.passwordUpdating : t.updatePassword}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
