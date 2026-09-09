import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import type { AppMessages } from "@/i18n";
import { maxResumeTitleLength, truncateResumeTitle } from "@/lib/resume-title";

export function ResumeDetailTitleDialog({
  messages,
  model,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;

  return (
    <Dialog
      open={state.title.isOpen}
      onOpenChange={commands.setTitleDialogOpen}
    >
      <DialogContent
        showCloseButton
        closeLabel={messages.close}
        className="w-[min(420px,calc(100vw-2rem))]"
      >
        <DialogHeader>
          <DialogTitle>{messages.editResumeTitle}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-2">
          <label
            htmlFor="resume-title-input"
            className="text-sm font-medium text-foreground"
          >
            {messages.resumeTitle}
          </label>
          <Input
            id="resume-title-input"
            value={state.title.draft}
            autoFocus
            onChange={(event) =>
              commands.changeTitleDraft(truncateResumeTitle(event.target.value))
            }
          />
          <p className="text-right text-xs text-muted-foreground">
            {Array.from(state.title.draft).length}/{maxResumeTitleLength}
          </p>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button
              type="button"
              variant="outline"
              className="h-10 min-w-[72px] rounded-lg px-4"
            >
              {messages.cancel}
            </Button>
          </DialogClose>
          <Button
            type="button"
            variant="ghost"
            className="h-10 min-w-[72px] rounded-lg px-4 font-semibold hover:opacity-90"
            style={{
              backgroundColor: "var(--foreground)",
              color: "var(--background)",
            }}
            onClick={() => void commands.saveTitle()}
          >
            {messages.saveResumeTitle}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
