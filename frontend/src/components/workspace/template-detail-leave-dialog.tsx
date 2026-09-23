import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { AppMessages } from "@/i18n";

export function TemplateDetailLeaveDialog({
  changeCount,
  isOpen,
  isResolving,
  messages,
  onCancel,
  onDiscard,
  onSave,
}: {
  changeCount: number;
  isOpen: boolean;
  isResolving: boolean;
  messages: AppMessages;
  onCancel: () => void;
  onDiscard: () => Promise<void>;
  onSave: () => Promise<void>;
}) {
  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open && !isResolving) {
          onCancel();
        }
      }}
    >
      <DialogContent
        showCloseButton
        closeLabel={messages.close}
        className="w-[min(460px,calc(100vw-2rem))]"
      >
        <DialogHeader>
          <DialogTitle>{messages.unsavedChangesTitle}</DialogTitle>
          <DialogDescription>
            {messages.unsavedChangesDescription.replace(
              "{count}",
              String(Math.max(1, changeCount)),
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:justify-end">
          <Button
            type="button"
            variant="outline"
            disabled={isResolving}
            onClick={onCancel}
          >
            {messages.unsavedChangesContinueEditing}
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={isResolving}
            onClick={() => void onDiscard()}
          >
            {messages.unsavedChangesDiscard}
          </Button>
          <Button
            type="button"
            className="grid"
            aria-busy={isResolving}
            disabled={isResolving}
            onClick={() => void onSave()}
          >
            <span
              className="col-start-1 row-start-1 aria-hidden:invisible"
              aria-hidden={isResolving}
            >
              {messages.unsavedChangesSaveAndLeave}
            </span>
            <span
              className="col-start-1 row-start-1 aria-hidden:invisible"
              aria-hidden={!isResolving}
            >
              {messages.saving}
            </span>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
