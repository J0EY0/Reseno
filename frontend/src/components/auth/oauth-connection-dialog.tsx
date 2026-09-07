import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import type { AppMessages } from "@/i18n";
import type { OAuthProgress } from "@/lib/auth-oauth-tab";

export function OAuthConnectionDialog({
  progress,
  onCancel,
  t,
}: {
  progress: OAuthProgress | null;
  onCancel: () => void;
  t: AppMessages;
}) {
  const title = progress?.stage === "preparing"
    ? t.oauthConnectionPreparingTitle
    : progress?.stage === "blocked"
      ? t.oauthConnectionBlockedTitle
      : t.oauthConnectionTitle;
  const description = progress?.stage === "preparing"
    ? t.oauthConnectionPreparingDescription
    : progress?.stage === "blocked"
      ? t.oauthConnectionBlockedDescription
      : t.oauthConnectionDescription;

  return (
    <Dialog
      open={progress !== null}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onCancel();
      }}
    >
      {progress ? (
        <DialogContent
          closeLabel={t.close}
          className="sm:max-w-md"
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
        >
          <DialogHeader>
            <div
              role="status"
              className="flex items-center justify-center gap-3 sm:justify-start"
            >
              {progress.stage === "blocked" ? null : (
                <Spinner
                  aria-hidden="true"
                  className="shrink-0 motion-reduce:animate-none"
                />
              )}
              <DialogTitle>{title}</DialogTitle>
            </div>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t.cancel}
              </Button>
            </DialogClose>
            {progress.stage === "blocked" ? (
              <Button type="button" onClick={progress.open}>
                {t.oauthConnectionOpen}
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
