import { ChevronLeft, ChevronRight } from "lucide-react";
import { lazy, Suspense } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import type { AppMessages, Locale } from "@/i18n";
import { cn } from "@/lib/utils";

let copilotPanelModulePromise:
  | Promise<typeof import("@/components/copilot/copilot-panel")>
  | null = null;

// Keep the conversation runtime out of the detail entry chunk until the Agent
// dock is rendered or the compact-layout trigger warms the same module.
function loadCopilotPanelModule() {
  copilotPanelModulePromise ??= import(
    "@/components/copilot/copilot-panel"
  );
  return copilotPanelModulePromise;
}

const CopilotPanel = lazy(() =>
  loadCopilotPanelModule().then((module) => ({
    default: module.CopilotPanel,
  })),
);

function AgentPanelFallback() {
  return (
    <Card className="h-full min-h-0 rounded-[32px] border-border/60">
      <CardContent className="space-y-5 p-4">
        <div className="flex items-center gap-3">
          <Skeleton className="size-11 rounded-2xl" />
          <Skeleton className="h-5 w-28" />
        </div>
        <Skeleton className="h-36 rounded-3xl" />
        <Skeleton className="h-48 rounded-3xl" />
        <Skeleton className="mt-auto h-44 rounded-[26px]" />
      </CardContent>
    </Card>
  );
}

function ResumeDetailAgentPanel({
  locale,
  messages,
  mode,
  model,
}: {
  locale: Locale;
  messages: AppMessages;
  mode: "docked" | "sheet";
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;

  return (
    <Suspense fallback={<AgentPanelFallback />}>
      <CopilotPanel
        key={`${state.resumeItem?.id ?? "resume"}-${mode}`}
        mode={mode}
        resumeId={state.resumeItem?.id ?? undefined}
        t={messages}
        locale={locale}
        resume={state.resume}
        jobBrief={state.agent.jobBrief}
        onJobBriefChange={commands.agent.changeJobBrief}
        keywordMatch={state.agent.keywordMatch}
        modelConfigs={state.agent.modelConfigs}
        selectedModelId={state.agent.selectedModelId}
        onSelectedModelChange={commands.agent.changeSelectedModel}
        hasAgentDraft={Boolean(state.agent.draft)}
        agentDraftState={state.agent.draftState}
        onPreviewAgentEdits={commands.agent.previewEdits}
        onRollbackAgentDraft={commands.agent.rollbackDraft}
        onApplyAgentDraft={commands.agent.applyDraft}
        onDiscardAgentDraft={commands.agent.discardDraft}
        onOpenModelSettings={commands.agent.openModelSettings}
        onBeforeSend={commands.agent.flushUserSettings}
      />
    </Suspense>
  );
}

function ResumeDetailAgentSeamRail({
  messages,
  model,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;

  if (!state.agent.isDockLayout) {
    return null;
  }

  const tooltip = state.agent.isPanelCollapsed
    ? messages.agentExpandPanel
    : messages.agentCollapsePanel;
  const RailIcon = state.agent.isPanelCollapsed
    ? ChevronLeft
    : ChevronRight;

  return (
    <div
      className={cn(
        "agent-seam-rail hidden print:hidden 2xl:flex",
        state.agent.isPanelCollapsed && "agent-seam-rail--collapsed",
      )}
    >
      <TooltipProvider delayDuration={180}>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={tooltip}
              className="agent-seam-rail-button"
              onClick={() =>
                commands.agent.setPanelCollapsed(
                  !state.agent.isPanelCollapsed,
                )
              }
            >
              <span className="agent-seam-rail-track" aria-hidden="true">
                <RailIcon className="agent-seam-rail-icon" />
              </span>
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">{tooltip}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}

export function ResumeDetailAgentHost({
  locale,
  messages,
  model,
}: {
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;
  const shouldDockAgent =
    state.agent.isDockLayout && !state.agent.isPanelCollapsed;

  return (
    <>
      <ResumeDetailAgentSeamRail messages={messages} model={model} />

      {state.agent.isDockLayout ? (
        <aside
          aria-hidden={!shouldDockAgent}
          className={cn(
            "agent-panel-dock relative min-w-0 self-start overflow-hidden print:hidden",
            "transition-opacity duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]",
            !shouldDockAgent && "pointer-events-none opacity-0",
          )}
        >
          <ResumeDetailAgentPanel
            locale={locale}
            messages={messages}
            mode="docked"
            model={model}
          />
        </aside>
      ) : null}

      {!state.agent.isDockLayout ? (
        <Sheet
          open={state.agent.isSheetOpen}
          onOpenChange={commands.agent.setSheetOpen}
        >
          <SheetContent
            closeLabel={messages.close}
            side="right"
            className="w-[420px] max-w-[calc(100vw-1rem)] p-2 sm:max-w-[420px]"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{messages.aiTitle}</SheetTitle>
              <SheetDescription>{messages.agentEmptyPrompt}</SheetDescription>
            </SheetHeader>
            <ResumeDetailAgentPanel
              locale={locale}
              messages={messages}
              mode="sheet"
              model={model}
            />
          </SheetContent>
        </Sheet>
      ) : null}
    </>
  );
}
