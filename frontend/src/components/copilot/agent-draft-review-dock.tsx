import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { AppMessages } from "@/i18n";
import type { AgentDraftReviewConflict } from "@/lib/agent-draft-review";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  ListChecks,
  RotateCcw,
} from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

import { AgentDraftConflictNotice } from "./agent-draft-conflict-notice";

export interface AgentDraftReviewDockView {
  conflicts: AgentDraftReviewConflict[];
  disabled: boolean;
  hasScopeConflicts: boolean;
  mode: "all" | "single";
  onApply: () => void;
  onApplyOriginal: () => void;
  onDiscard: () => void;
  onKeepManual: () => void;
  onNext: () => void;
  onPrevious: () => void;
  onSelectFirst: () => void;
  onShowAll: () => void;
  pendingCount: number;
  /** Zero-based position within the current pending review items. */
  selectedIndex: number;
  resolvingStatus: "applied" | "discarded" | null;
}

const DOCK_EXIT_DURATION_MS = 200;

function formatCount(template: string, count: number) {
  return template.replace("{count}", String(count));
}

function formatPosition(template: string, current: number, total: number) {
  return template
    .replace("{current}", String(current))
    .replace("{total}", String(total));
}

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function ReviewDecisionIcon({
  active,
  label,
  type,
}: {
  active: boolean;
  label: string;
  type: "apply" | "discard";
}) {
  if (active) {
    return <Spinner aria-label={label} data-icon="inline-start" />;
  }

  return type === "apply" ? (
    <Check aria-hidden="true" data-icon="inline-start" />
  ) : (
    <RotateCcw aria-hidden="true" data-icon="inline-start" />
  );
}

function ReviewIconButton({
  children,
  disabled,
  label,
  onClick,
}: {
  children: ReactNode;
  disabled: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          aria-label={label}
          disabled={disabled}
          onClick={onClick}
          size="icon-xs"
          type="button"
          variant="ghost"
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}

function DraftReviewDockContent({
  isLeaving,
  t,
  view,
}: {
  isLeaving: boolean;
  t: AppMessages;
  view: AgentDraftReviewDockView;
}) {
  const isResolving = view.resolvingStatus !== null;
  const decisionsDisabled = view.disabled || isResolving || isLeaving;
  const navigationDisabled = view.disabled || isResolving || isLeaving;
  const current = Math.min(view.selectedIndex + 1, view.pendingCount);
  const applyLabel =
    view.mode === "all" ? t.agentApplyRemaining : t.agentApplyThis;
  const discardLabel =
    view.mode === "all" ? t.agentDiscardRemaining : t.agentDiscardThis;

  return (
    <TooltipProvider>
      <div className="grid min-w-0 gap-2">
        {view.conflicts.length > 0 ? (
          <div
            className="agent-draft-review-dock min-w-0"
            data-presence={isLeaving ? "exiting" : "entered"}
          >
            <AgentDraftConflictNotice
              conflicts={view.conflicts}
              disabled={navigationDisabled}
              onApplyOriginal={view.onApplyOriginal}
              onKeepManual={view.onKeepManual}
              pendingCount={view.pendingCount}
              t={t}
            />
          </div>
        ) : null}
        <section
          aria-label={t.agentDraftReview}
          aria-live="polite"
          className="agent-draft-review-dock flex min-w-0 items-center gap-1 rounded-md border bg-background/95 p-1 shadow-lg"
          data-orientation="horizontal"
          data-presence={isLeaving ? "exiting" : "entered"}
          data-slot="agent-draft-review-dock"
        >
          {view.mode === "all" ? (
            <>
              <div className="flex min-w-0 flex-1 items-center gap-1.5 px-2">
                <ListChecks
                  aria-hidden="true"
                  className="size-3 shrink-0 text-muted-foreground"
                />
                <span className="truncate text-xs font-medium tabular-nums">
                  {formatCount(t.agentReviewRemaining, view.pendingCount)}
                </span>
              </div>
              <ReviewIconButton
                disabled={navigationDisabled}
                label={t.agentReviewOneByOne}
                onClick={view.onSelectFirst}
              >
                <ChevronRight aria-hidden="true" />
              </ReviewIconButton>
            </>
          ) : (
            <>
              <Button
                disabled={navigationDisabled}
                onClick={view.onShowAll}
                size="xs"
                type="button"
                variant="ghost"
              >
                <ListChecks aria-hidden="true" data-icon="inline-start" />
                {t.agentReviewAll}
              </Button>
              <div className="min-w-0 flex-1 text-center">
                <span className="block truncate text-xs font-medium tabular-nums">
                  {formatPosition(
                    t.agentReviewSinglePosition,
                    current,
                    view.pendingCount,
                  )}
                </span>
                <span className="sr-only">{t.agentReviewSingleMode}</span>
              </div>
              <ReviewIconButton
                disabled={navigationDisabled || view.pendingCount < 2}
                label={t.agentReviewPrevious}
                onClick={view.onPrevious}
              >
                <ChevronLeft aria-hidden="true" />
              </ReviewIconButton>
              <ReviewIconButton
                disabled={navigationDisabled || view.pendingCount < 2}
                label={t.agentReviewNext}
                onClick={view.onNext}
              >
                <ChevronRight aria-hidden="true" />
              </ReviewIconButton>
            </>
          )}

          <ReviewIconButton
            disabled={decisionsDisabled || view.hasScopeConflicts}
            label={applyLabel}
            onClick={view.onApply}
          >
            <ReviewDecisionIcon
              active={view.resolvingStatus === "applied"}
              label={t.agentApplyingDraft}
              type="apply"
            />
          </ReviewIconButton>
          <ReviewIconButton
            disabled={decisionsDisabled}
            label={discardLabel}
            onClick={view.onDiscard}
          >
            <ReviewDecisionIcon
              active={view.resolvingStatus === "discarded"}
              label={t.agentDiscardingDraft}
              type="discard"
            />
          </ReviewIconButton>
        </section>
      </div>
    </TooltipProvider>
  );
}

/** Keeps the last dock frame mounted long enough for its exit animation. */
export function AgentDraftReviewDock({
  t,
  view,
}: {
  t: AppMessages;
  view: AgentDraftReviewDockView | null;
}) {
  const [renderedView, setRenderedView] =
    useState<AgentDraftReviewDockView | null>(view);
  const [isLeaving, setIsLeaving] = useState(false);

  useEffect(() => {
    let exitTimer: number | null = null;
    const frame = window.requestAnimationFrame(() => {
      if (view) {
        setRenderedView(view);
        setIsLeaving(false);
        return;
      }

      setIsLeaving(true);
      exitTimer = window.setTimeout(
        () => {
          setRenderedView(null);
          setIsLeaving(false);
        },
        prefersReducedMotion() ? 0 : DOCK_EXIT_DURATION_MS,
      );
    });

    return () => {
      window.cancelAnimationFrame(frame);
      if (exitTimer !== null) {
        window.clearTimeout(exitTimer);
      }
    };
  }, [view]);

  if (!renderedView) {
    return null;
  }

  return (
    <DraftReviewDockContent isLeaving={isLeaving} t={t} view={renderedView} />
  );
}
