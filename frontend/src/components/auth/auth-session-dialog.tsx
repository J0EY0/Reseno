import { useEffect, type ComponentProps } from "react";
import { toast } from "sonner";
import { LoginForm } from "@/components/auth/login-form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export function AuthSessionDialog({
  t,
  onSubmitCredentials,
}: Omit<ComponentProps<typeof LoginForm>, "oauth">) {
  useEffect(() => {
    toast.dismiss();
  }, []);

  return (
    <Dialog open>
      <DialogContent
        className="max-h-[calc(100svh-2rem)] overflow-y-auto"
        showCloseButton={false}
        onEscapeKeyDown={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>{t.authSessionExpiredTitle}</DialogTitle>
          <DialogDescription>
            {t.authSessionExpiredDescription}
          </DialogDescription>
        </DialogHeader>
        <LoginForm t={t} onSubmitCredentials={onSubmitCredentials} />
        <Button variant="outline" asChild>
          <a href="/login" target="_blank" rel="noopener noreferrer">
            {t.authSessionOtherLogin}
          </a>
        </Button>
      </DialogContent>
    </Dialog>
  );
}
