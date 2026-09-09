import { ResumeDraftReviewComparison } from "@/components/preview/resume-draft-review-comparison";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { AppMessages } from "@/i18n";
import type { AgentDraftReviewConflict } from "@/lib/agent-draft-review";
import { TriangleAlert } from "lucide-react";
import { useState } from "react";

export function AgentDraftConflictNotice({
  conflicts,
  disabled,
  onApplyOriginal,
  onKeepManual,
  pendingCount,
  t,
}: {
  conflicts: AgentDraftReviewConflict[];
  disabled: boolean;
  onApplyOriginal: () => void;
  onKeepManual: () => void;
  pendingCount: number;
  t: AppMessages;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div
      className="min-w-0 rounded-md border border-warning/25 bg-background/95 p-2.5 text-xs shadow-sm"
      data-slot="agent-draft-conflict-notice"
    >
      <div className="flex items-start gap-2" role="status">
        <TriangleAlert
          aria-hidden="true"
          className="mt-0.5 size-3.5 shrink-0 text-warning"
        />
        <div className="min-w-0 space-y-1 break-words leading-5">
          <p className="font-medium">
            {t.agentDraftConflictTitle.replace(
              "{count}",
              String(conflicts.length),
            )}
          </p>
          <p className="text-muted-foreground">
            {t.agentDraftConflictDescription}
          </p>
        </div>
      </div>
      <Popover onOpenChange={setIsOpen} open={isOpen}>
        <PopoverTrigger asChild>
          <Button
            className="mt-1.5 max-w-full"
            disabled={disabled}
            size="xs"
            type="button"
            variant="ghost"
          >
            {t.agentDraftConflictInspect}
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          aria-label={t.agentDraftConflictInspect}
          className="flex max-h-[min(32rem,var(--radix-popover-content-available-height))] w-[min(24rem,calc(100vw-2rem))] flex-col overflow-hidden p-3"
          collisionPadding={16}
          data-slot="agent-draft-conflict-comparison"
          side="top"
          sideOffset={8}
        >
          <PopoverTitle className="shrink-0 break-words text-sm">
            {t.agentDraftConflictInspect}
          </PopoverTitle>
          <p className="mt-1.5 shrink-0 break-words text-xs leading-5 text-muted-foreground">
            {t.agentDraftConflictOriginalDescription}
          </p>
          <div className="mt-3 grid min-h-0 min-w-0 gap-3 overflow-y-auto overscroll-contain">
            {conflicts.map((conflict) => (
              <div
                className="min-w-0 border-t pt-3"
                data-review-item-id={conflict.reviewItemId}
                key={conflict.reviewItemId}
              >
                <div className="grid min-w-0 gap-3 [overflow-wrap:anywhere]">
                  {conflict.diffs.map((diff) => (
                    <div className="min-w-0" key={diff.id}>
                      <ResumeDraftReviewComparison diff={diff} t={t} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div
            className="mt-3 shrink-0 border-t pt-3"
            data-slot="agent-draft-conflict-actions"
          >
            <p className="mb-2 break-words text-xs font-medium leading-5">
              {t.agentDraftConflictScope.replace(
                "{count}",
                String(pendingCount),
              )}
            </p>
            <div className="grid grid-cols-2 gap-x-2 gap-y-1.5">
              <Button
                className="h-full min-h-6 min-w-0 whitespace-normal py-0.5 leading-4"
                disabled={disabled}
                onClick={onApplyOriginal}
                size="xs"
                type="button"
              >
                {t.agentDraftConflictApplyOriginal}
              </Button>
              <Button
                className="h-full min-h-6 min-w-0 whitespace-normal py-0.5 leading-4"
                disabled={disabled}
                onClick={onKeepManual}
                size="xs"
                type="button"
                variant="outline"
              >
                {t.agentDraftConflictKeepManual}
              </Button>
              <p className="min-w-0 break-words text-xs leading-5 text-muted-foreground">
                {t.agentDraftConflictApplyOriginalHint}
              </p>
              <p className="min-w-0 break-words text-xs leading-5 text-muted-foreground">
                {t.agentDraftConflictKeepManualHint}
              </p>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
