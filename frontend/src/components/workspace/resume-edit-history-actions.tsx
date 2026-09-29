import { Redo2, Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AppMessages } from "@/i18n";
import type { ResumeDetailWorkspaceModel } from "./resume-detail-workspace-types";

export function ResumeEditHistoryActions({
  messages,
  model,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;
  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label={messages.richTextUndo}
        title={messages.richTextUndo}
        aria-keyshortcuts="Control+Z Meta+Z"
        disabled={state.editing.disabled || !state.editing.canUndo}
        onClick={commands.undo}
      >
        <Undo2 />
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label={messages.richTextRedo}
        title={messages.richTextRedo}
        aria-keyshortcuts="Control+Shift+Z Meta+Shift+Z Control+Y"
        disabled={state.editing.disabled || !state.editing.canRedo}
        onClick={commands.redo}
      >
        <Redo2 />
      </Button>
    </div>
  );
}
