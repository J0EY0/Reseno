import { ChevronLeft, ChevronRight } from "lucide-react";
import { lazy, Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
// panel renders or its collapsed rail warms the same module.
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

function AgentPanelFallback({
  isPanelCollapsed,
}: {
  isPanelCollapsed: boolean;
}) {
  const shouldDockAgent = !isPanelCollapsed;

  return (
    <aside
      aria-hidden={!shouldDockAgent}
      className={cn(
        "agent-panel-dock relative min-w-0 self-start overflow-hidden print:hidden",
        !shouldDockAgent && "pointer-events-none opacity-0",
      )}
      inert={!shouldDockAgent}
    >
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
    </aside>
  );
}

function ResumeDetailAgentPanel({
  locale,
  messages,
  model,
}: {
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;

  return (
    <Suspense
      fallback={
        <AgentPanelFallback
          isPanelCollapsed={state.agent.isPanelCollapsed}
        />
      }
    >
      <CopilotPanel
        key={state.resumeItem?.id ?? "resume"}
        isPanelCollapsed={state.agent.isPanelCollapsed}
        resumeId={state.resumeItem?.id ?? undefined}
        t={messages}
        locale={locale}
        resume={state.resume}
        modelConfigs={state.agent.modelConfigs}
        selectedModelId={state.agent.selectedModelId}
        onSelectedModelChange={commands.agent.changeSelectedModel}
        hasAgentDraft={Boolean(state.agent.draft)}
        agentDraftState={state.agent.draftState}
        onPreviewAgentEdits={commands.agent.previewEdits}
        onReconcileAgentDraft={commands.agent.reconcileDraft}
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
  const isCollapsed = state.agent.isPanelCollapsed;
  const tooltip = isCollapsed
    ? messages.agentExpandPanel
    : messages.agentCollapsePanel;
  const RailIcon = isCollapsed ? ChevronLeft : ChevronRight;

  return (
    <div
      className={cn(
        "agent-seam-rail flex print:hidden",
        isCollapsed && "agent-seam-rail--collapsed",
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
              aria-expanded={!state.agent.isPanelCollapsed}
              className="agent-seam-rail-button"
              onFocus={() => void loadCopilotPanelModule()}
              onPointerEnter={() => void loadCopilotPanelModule()}
              onClick={() => {
                commands.agent.setPanelCollapsed(
                  !state.agent.isPanelCollapsed,
                );
              }}
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
  const { state } = model;
  const [hasMountedAgent, setHasMountedAgent] = useState(
    () => !state.agent.isPanelCollapsed,
  );
  const shouldActivateAgent = !state.agent.isPanelCollapsed;
  // This one-way latch keeps the conversation controller alive when the dock
  // collapses. The resumeId key remains the only reason to remount its owner.
  if (!hasMountedAgent && shouldActivateAgent) {
    setHasMountedAgent(true);
  }
  const shouldMountAgent = hasMountedAgent || shouldActivateAgent;

  return (
    <>
      <ResumeDetailAgentSeamRail messages={messages} model={model} />
      {shouldMountAgent ? (
        <ResumeDetailAgentPanel
          locale={locale}
          messages={messages}
          model={model}
        />
      ) : null}
    </>
  );
}
