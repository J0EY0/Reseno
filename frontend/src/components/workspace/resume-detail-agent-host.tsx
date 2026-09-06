import { ChevronRight } from "lucide-react";
import { lazy, Suspense, useState } from "react";

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
const RESUME_DETAIL_AGENT_PANEL_ID = "resume-detail-agent-panel";

function loadCopilotPanelModule() {
  copilotPanelModulePromise ??= import(
    "@/components/copilot/copilot-panel"
  );
  return copilotPanelModulePromise;
}

function preloadCopilotPanelModule() {
  void loadCopilotPanelModule();
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
      id={RESUME_DETAIL_AGENT_PANEL_ID}
      aria-label={messages.aiTitle}
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
                    selectedModelConfigId={state.agent.selectedModelConfigId}
                    onSelectedModelConfigChange={commands.agent.changeSelectedModelConfig}
                    agentDraftState={state.agent.draftState}
                    agentDraftReview={state.agent.review}
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

export function ResumeDetailAgentToggle({
  messages,
  model,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;
  const panelStatus = state.agent.panelStatus;
  const isCollapsed = state.agent.isPanelCollapsed;
  const tooltip = isCollapsed
    ? messages.agentExpandPanel
    : messages.agentCollapsePanel;
  const statusLabel =
    panelStatus === "responding"
      ? messages.agentThinking
      : panelStatus === "loading"
        ? messages.agentHistoryLoading
        : panelStatus === "error"
          ? messages.agentHistoryLoadFailed
          : state.agent.draft
            ? messages.agentDraftReady
            : null;

  return (
    <TooltipProvider delayDuration={180}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-controls={RESUME_DETAIL_AGENT_PANEL_ID}
            aria-label={tooltip}
            aria-expanded={!isCollapsed}
            className={cn(
              "hidden w-10 rounded-md bg-background/95 shadow-lg dark:bg-background/95 dark:hover:bg-accent xl:inline-flex",
              !isCollapsed &&
                "bg-accent text-accent-foreground dark:bg-accent",
            )}
            data-agent-status={panelStatus ?? "idle"}
            data-slot="agent-panel-toggle"
            onFocus={preloadCopilotPanelModule}
            onPointerDown={preloadCopilotPanelModule}
            onPointerEnter={preloadCopilotPanelModule}
            onClick={() => {
              commands.agent.setPanelCollapsed(!isCollapsed);
            }}
          >
            <ChevronRight
              aria-hidden="true"
              className={cn(
                "transition-transform duration-200",
                !isCollapsed && "rotate-180",
              )}
            />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="top">{tooltip}</TooltipContent>
      </Tooltip>
      {isCollapsed && statusLabel ? (
        <span className="sr-only" role="status">
          {statusLabel}
        </span>
      ) : null}
    </TooltipProvider>
  );
}

export function ResumeDetailAgentHost({
  messages,
  model,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;
  const [hasMountedAgent, setHasMountedAgent] = useState(
    () => !state.agent.isPanelCollapsed,
  );
  const shouldActivateAgent = !state.agent.isPanelCollapsed;
  if (!hasMountedAgent && shouldActivateAgent) {
    setHasMountedAgent(true);
  }
  const shouldMountAgent = hasMountedAgent || shouldActivateAgent;

  return shouldMountAgent ? (
    <ResumeDetailAgentPanel
      messages={messages}
      model={model}
      panelStatus={state.agent.panelStatus}
      onStatusChange={commands.agent.reportPanelStatus}
    />
  ) : null;
}
