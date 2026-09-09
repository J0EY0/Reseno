import { PromptInputProvider } from "@/components/ai-elements/prompt-input-context";
import { useLayoutEffect, useMemo } from "react";

import {
  AgentDraftReviewDock,
  type AgentDraftReviewDockView,
} from "./agent-draft-review-dock";
import { CopilotComposer } from "./copilot-composer";
import { CopilotConversationView } from "./copilot-conversation-view";
import { CopilotPanelBodyFrame } from "./copilot-panel-shell";
import type { CopilotPanelProps } from "./copilot-panel-types";
import { useAgentComposerLayout } from "./use-agent-composer-layout";
import { useAgentConversation } from "./use-agent-conversation";
import { useAgentMessageActions } from "./use-agent-message-actions";
import { useAgentPromptActions } from "./use-agent-prompt-actions";

/**
 * Stable inline-dock entrypoint. Conversation, history actions, attachments,
 * and rendering each live behind their own behavioral seam.
 */
export function CopilotPanel({
  isPanelCollapsed,
  resumeId,
  t,
  documentLocale,
  resume,
  modelConfigs,
  selectedModelConfigId,
  onSelectedModelConfigChange,
  agentDraftState,
  agentDraftReview,
  onPreviewAgentEdits,
  onReconcileAgentDraft,
  onRollbackAgentDraft,
  onApplyAgentDraft,
  onDiscardAgentDraft,
  onOpenModelSettings,
  onStatusChange,
  onBeforeSend,
}: CopilotPanelProps) {
  const agentModelConfigs = useMemo(
    () => modelConfigs.filter((config) => config.supportsTools),
    [modelConfigs],
  );
  const selectedModelConfig = useMemo(
    () =>
      agentModelConfigs.find((config) => config.id === selectedModelConfigId) ??
      null,
    [agentModelConfigs, selectedModelConfigId],
  );
  const conversation = useAgentConversation({
    agentDraftState,
    documentLocale,
    onApplyAgentDraft,
    onBeforeSend,
    onDiscardAgentDraft,
    onPreviewAgentEdits,
    onReconcileAgentDraft,
    onRollbackAgentDraft,
    resume,
    resumeId,
    selectedModelConfig,
    t,
  });
  const isRequestBusy = conversation.requestPhase !== "idle";
  const promptActions = useAgentPromptActions({
    hasConfiguredModel: Boolean(selectedModelConfig),
    isRequestBusy,
    isSessionReady: conversation.isSessionReady,
    resumeId,
    sessionResetVersion: conversation.sessionResetVersion,
    sendPrompt: conversation.sendPrompt,
    stopConversation: conversation.stopResponding,
    t,
  });
  const messageActions = useAgentMessageActions({
    isRequestBusy,
    messages: conversation.messages,
    resumeId,
    sessionResetVersion: conversation.sessionResetVersion,
    sendPrompt: conversation.sendPrompt,
    t,
  });
  const { composerRef, conversationContextRef, conversationLayoutRef } =
    useAgentComposerLayout();
  const globalDropActive = !isPanelCollapsed;
  const reviewDockView = useMemo<AgentDraftReviewDockView | null>(() => {
    if (!agentDraftReview) {
      return null;
    }

    return {
      conflicts: agentDraftReview.allConflicts,
      disabled:
        agentDraftReview.disabled ||
        isRequestBusy ||
        !conversation.isSessionReady,
      hasScopeConflicts: agentDraftReview.projection.conflicts.length > 0,
      mode: agentDraftReview.mode,
      onApply: () => {
        void conversation.applyAgentDraft();
      },
      onApplyOriginal: () => {
        void conversation.runAgentDraftDecision(agentDraftReview.applyOriginal);
      },
      onDiscard: () => {
        void conversation.discardAgentDraft();
      },
      onKeepManual: () => {
        void conversation.runAgentDraftDecision(agentDraftReview.keepManual);
      },
      onNext: agentDraftReview.selectNext,
      onPrevious: agentDraftReview.selectPrevious,
      onSelectFirst: agentDraftReview.selectFirst,
      onShowAll: agentDraftReview.showAll,
      pendingCount: agentDraftReview.pendingCount,
      resolvingStatus: agentDraftReview.resolvingStatus,
      selectedIndex: agentDraftReview.selectedIndex,
    };
  }, [agentDraftReview, conversation, isRequestBusy]);

  useLayoutEffect(() => {
    onStatusChange(conversation.status);
  }, [conversation.status, onStatusChange]);

  return (
    <PromptInputProvider>
      <CopilotPanelBodyFrame
        composer={
          <div className="grid min-w-0 grid-cols-1 gap-2">
            <AgentDraftReviewDock t={t} view={reviewDockView} />
            <CopilotComposer
              globalDropActive={globalDropActive}
              hasConversationHistory={conversation.messages.length > 0}
              isSessionReady={conversation.isSessionReady}
              modelConfigs={agentModelConfigs}
              onOpenModelSettings={onOpenModelSettings}
              onSelectedModelConfigChange={onSelectedModelConfigChange}
              promptActions={promptActions}
              requestPhase={conversation.requestPhase}
              selectedModelConfig={selectedModelConfig}
              selectedModelConfigId={selectedModelConfigId}
              t={t}
            />
          </div>
        }
        composerRef={composerRef}
        conversationLayoutRef={conversationLayoutRef}
      >
        <CopilotConversationView
          key={conversation.sessionResetVersion}
          conversation={conversation}
          conversationContextRef={conversationContextRef}
          hasConfiguredModel={Boolean(selectedModelConfig)}
          messageActions={messageActions}
          onOpenModelSettings={onOpenModelSettings}
          promptActions={promptActions}
          t={t}
        />
      </CopilotPanelBodyFrame>
    </PromptInputProvider>
  );
}
