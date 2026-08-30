import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import type { AppMessages } from "@/i18n";

export function ResumeDetailLeaveDialog({
  messages,
  model,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;

  return (
    <Dialog
      open={state.leave.isOpen}
      onOpenChange={(open) => {
        if (!open && !state.leave.isResolving) {
          commands.cancelLeave();
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
              String(Math.max(1, state.save.changeCount)),
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2 sm:justify-end">
          <Button
            type="button"
            variant="outline"
            disabled={state.leave.isResolving}
            onClick={commands.cancelLeave}
          >
            {messages.unsavedChangesContinueEditing}
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={state.leave.isResolving}
            onClick={() => void commands.discardAndLeave()}
          >
            {messages.unsavedChangesDiscard}
          </Button>
          <Button
            type="button"
            disabled={state.leave.isResolving}
            onClick={() => void commands.saveAndLeave()}
          >
            {state.leave.isResolving
              ? messages.saving
              : messages.unsavedChangesSaveAndLeave}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
