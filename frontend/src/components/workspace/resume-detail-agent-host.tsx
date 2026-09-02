import { ChevronLeft, ChevronRight } from "lucide-react";
import { lazy, Suspense, useCallback, useState } from "react";

import {
  AgentPanelLoadingBody,
  CopilotPanelShell,
} from "@/components/copilot/copilot-panel-shell";
import type { AgentPanelStatus } from "@/components/copilot/copilot-panel-types";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import type { AppMessages } from "@/i18n";
import { cn } from "@/lib/utils";

import "./resume-detail-agent-motion.css";

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

function ResumeDetailAgentPanel({
  messages,
  model,
  panelStatus,
  onStatusChange,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  panelStatus: AgentPanelStatus | null;
  onStatusChange: (status: AgentPanelStatus) => void;
}) {
  const { commands, state } = model;
  const shouldDockAgent = !state.agent.isPanelCollapsed;
  const showStableLoader = panelStatus === null || panelStatus === "loading";

  return (
    <aside
      aria-hidden={!shouldDockAgent}
      className={cn(
        "agent-panel-dock relative min-w-0 self-start overflow-hidden print:hidden",
        !shouldDockAgent && "pointer-events-none",
      )}
      inert={!shouldDockAgent}
    >
      <div className="agent-panel-motion-layer h-full">
        <CopilotPanelShell t={messages}>
          <div className="relative flex min-h-0 flex-1 flex-col">
            {showStableLoader ? (
              <div
                className="absolute inset-0 z-20 flex min-h-0 flex-col"
                data-slot="agent-panel-stable-loader"
              >
                <AgentPanelLoadingBody t={messages} />
              </div>
            ) : null}
            <div
              aria-hidden={showStableLoader}
              className={cn(
                "flex min-h-0 flex-1 flex-col",
                showStableLoader && "invisible",
              )}
              data-slot="agent-panel-live-body"
              inert={showStableLoader}
            >
              <Suspense fallback={null}>
                {state.resumeItem ? (
                  <CopilotPanel
                    key={state.resumeItem.id}
                    documentLocale={state.resumeItem.documentLocale}
                    isPanelCollapsed={state.agent.isPanelCollapsed}
                    resumeId={state.resumeItem.id}
                    t={messages}
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
                    onStatusChange={onStatusChange}
                    onBeforeSend={commands.agent.flushUserSettings}
                  />
                ) : null}
              </Suspense>
            </div>
          </div>
        </CopilotPanelShell>
      </div>
    </aside>
  );
}

function ResumeDetailAgentSeamRail({
  messages,
  model,
  panelStatus,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  panelStatus: AgentPanelStatus | null;
}) {
  const { commands, state } = model;
  const isCollapsed = state.agent.isPanelCollapsed;
  const tooltip = isCollapsed
    ? messages.agentExpandPanel
    : messages.agentCollapsePanel;
  const railStatus =
    panelStatus === "responding"
      ? "responding"
      : panelStatus === "loading"
        ? "loading"
        : panelStatus === "error"
          ? "error"
          : state.agent.draft
            ? "attention"
            : "idle";
  const statusLabel =
    railStatus === "responding"
      ? messages.agentThinking
      : railStatus === "loading"
        ? messages.agentHistoryLoading
        : railStatus === "error"
          ? messages.agentHistoryLoadFailed
          : railStatus === "attention"
            ? messages.agentDraftReady
            : null;

  return (
    <div
      className={cn(
        "agent-seam-rail flex print:hidden",
        isCollapsed && "agent-seam-rail--collapsed",
      )}
      data-agent-status={railStatus}
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
              onPointerDown={() => void loadCopilotPanelModule()}
              onPointerEnter={() => void loadCopilotPanelModule()}
              onClick={() => {
                commands.agent.setPanelCollapsed(
                  !state.agent.isPanelCollapsed,
                );
              }}
            >
              <span className="agent-seam-rail-track" aria-hidden="true">
                <ChevronLeft className="agent-seam-rail-icon agent-seam-rail-icon--collapsed" />
                <ChevronRight className="agent-seam-rail-icon agent-seam-rail-icon--expanded" />
              </span>
              <span
                aria-hidden="true"
                className="agent-seam-rail-status"
                data-slot="agent-status-indicator"
              />
              {isCollapsed && statusLabel ? (
                <span className="sr-only" role="status">
                  {statusLabel}
                </span>
              ) : null}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">{tooltip}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}

export function ResumeDetailAgentHost({
  messages,
  model,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { state } = model;
  const resumeId = state.resumeItem?.id;
  const [hasMountedAgent, setHasMountedAgent] = useState(
    () => !state.agent.isPanelCollapsed,
  );
  const [reportedStatus, setReportedStatus] = useState<{
    resumeId: string | undefined;
    status: AgentPanelStatus;
  } | null>(null);
  const handleStatusChange = useCallback(
    (status: AgentPanelStatus) => {
      setReportedStatus((current) =>
        current && current.resumeId === resumeId && current.status === status
          ? current
          : { resumeId, status },
      );
    },
    [resumeId],
  );
  const panelStatus =
    reportedStatus && reportedStatus.resumeId === resumeId
      ? reportedStatus.status
      : null;
  const shouldActivateAgent = !state.agent.isPanelCollapsed;
  // This one-way latch keeps the conversation controller alive when the dock
  // collapses. The resumeId key remains the only reason to remount its owner.
  if (!hasMountedAgent && shouldActivateAgent) {
    setHasMountedAgent(true);
  }
  const shouldMountAgent = hasMountedAgent || shouldActivateAgent;

  return (
    <>
      <ResumeDetailAgentSeamRail
        messages={messages}
        model={model}
        panelStatus={panelStatus}
      />
      {shouldMountAgent ? (
        <ResumeDetailAgentPanel
          messages={messages}
          model={model}
          panelStatus={panelStatus}
          onStatusChange={handleStatusChange}
        />
      ) : null}
    </>
  );
}
