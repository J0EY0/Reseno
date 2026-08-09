import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import {
  applyAgentEditsWithMerge,
  createAgentDraftBaseSnapshot,
  type AgentDraftApplyError,
} from "@/lib/resume-agent-edits";
import { createId } from "@/lib/resume";
import type {
  AgentDraftState,
  AgentResumeEditSuggestion,
  AgentTransactionState,
} from "@/types/api";
import type { ResumeData } from "@/types/resume";

function getAgentDraftErrorReason(
  error: AgentDraftApplyError,
  messages: AppMessages,
) {
  switch (error.reason) {
    case "missing_operation":
      return messages.agentDraftErrorMissingOperation;
    case "invalid_operation":
      return messages.agentDraftErrorInvalidOperation;
    case "target_not_found":
      return messages.agentDraftErrorTargetNotFound;
    case "duplicate_target":
      return messages.agentDraftErrorDuplicateTarget;
    case "no_change":
      return messages.agentDraftErrorNoChange;
    case "conflict":
      return messages.agentDraftErrorConflict;
  }
}

function formatAgentDraftErrors(
  errors: AgentDraftApplyError[],
  messages: AppMessages,
) {
  return errors
    .map(
      (error) =>
        `${error.title}: ${getAgentDraftErrorReason(error, messages)}`,
    )
    .join(" · ");
}

export function useResumeAgentDraft({
  messages,
  onApplyResume,
  resume,
}: {
  messages: AppMessages;
  onApplyResume: (resume: ResumeData) => void;
  resume: ResumeData;
}) {
  const [agentDraft, setAgentDraft] = useState<AgentDraftState | null>(null);
  const [lastAgentDraft, setLastAgentDraft] =
    useState<AgentDraftState | null>(null);
  const agentDraftBaseRef = useRef<{
    draftId: string;
    resume: ResumeData;
  } | null>(null);

  const resetAgentDraft = useCallback(() => {
    agentDraftBaseRef.current = null;
    setAgentDraft(null);
    setLastAgentDraft(null);
  }, []);

  const clearRejectedAgentDraft = useCallback((sourceMessageId?: string) => {
    const shouldClear = (draft: AgentDraftState | null) =>
      Boolean(
        draft &&
          draft.status === "pending" &&
          (!sourceMessageId || draft.sourceMessageId === sourceMessageId),
      );

    setAgentDraft((draft) => {
      if (!shouldClear(draft)) {
        return draft;
      }
      if (agentDraftBaseRef.current?.draftId === draft?.id) {
        agentDraftBaseRef.current = null;
      }
      return null;
    });
    setLastAgentDraft((draft) => (shouldClear(draft) ? null : draft));
  }, []);

  const previewAgentEdits = useCallback(
    (
      edits: AgentResumeEditSuggestion[],
      baseResume: ResumeData,
      sourceMessageId?: string,
      transactionState: AgentTransactionState = "committed",
    ) => {
      const draftBase = createAgentDraftBaseSnapshot(baseResume);
      // The immutable Agent base, latest render-phase resume, and stored edits
      // are the three inputs for both preview and final-apply merges.
      const result = applyAgentEditsWithMerge(draftBase, resume, edits);

      if (result.errors.length > 0) {
        if (transactionState === "committed") {
          clearRejectedAgentDraft(sourceMessageId);
          toast.error(messages.agentDraftBatchRejected, {
            description: formatAgentDraftErrors(result.errors, messages),
            closeButton: true,
          });
        }
        return;
      }

      if (result.appliedCount === 0) {
        if (transactionState === "committed") {
          clearRejectedAgentDraft(sourceMessageId);
        }
        return;
      }

      const now = new Date().toISOString();
      const draftId = sourceMessageId
        ? `agent-draft-${sourceMessageId}`
        : createId("agent-draft");
      const nextDraft: AgentDraftState = {
        id: draftId,
        status: "pending",
        sourceMessageId,
        createdAt: agentDraft?.id === draftId ? agentDraft.createdAt : now,
        updatedAt: now,
        resume: result.resume,
        editCount: result.appliedCount,
        edits,
        diffs: result.diffs,
        transactionState,
      };

      agentDraftBaseRef.current = {
        draftId,
        resume: draftBase,
      };
      setAgentDraft(nextDraft);
      setLastAgentDraft(nextDraft);
    },
    [agentDraft, clearRejectedAgentDraft, messages, resume],
  );

  const rollbackAgentDraft = useCallback((sourceMessageId?: string) => {
    const shouldRollback = (draft: AgentDraftState | null) =>
      Boolean(
        draft &&
          draft.status === "pending" &&
          (sourceMessageId
            ? draft.sourceMessageId === sourceMessageId
            : draft.transactionState === "provisional"),
      );

    setAgentDraft((draft) => {
      if (!shouldRollback(draft)) {
        return draft;
      }

      if (agentDraftBaseRef.current?.draftId === draft?.id) {
        agentDraftBaseRef.current = null;
      }
      return null;
    });
    setLastAgentDraft((draft) => (shouldRollback(draft) ? null : draft));
  }, []);

  const applyAgentDraft = useCallback(() => {
    if (!agentDraft || agentDraft.transactionState !== "committed") {
      return;
    }

    const draftBase = agentDraftBaseRef.current;
    if (!draftBase || draftBase.draftId !== agentDraft.id) {
      return;
    }

    const result = applyAgentEditsWithMerge(
      draftBase.resume,
      resume,
      agentDraft.edits,
    );

    if (result.errors.length > 0) {
      toast.error(messages.agentDraftBatchRejected, {
        description: formatAgentDraftErrors(result.errors, messages),
        closeButton: true,
      });
      return;
    }

    onApplyResume(result.resume);
    setLastAgentDraft({
      ...agentDraft,
      status: "applied",
      updatedAt: new Date().toISOString(),
      resume: result.resume,
    });
    agentDraftBaseRef.current = null;
    setAgentDraft(null);
    toast.success(messages.agentDraftApplied, {
      closeButton: true,
    });
  }, [agentDraft, messages, onApplyResume, resume]);

  const discardAgentDraft = useCallback(() => {
    if (!agentDraft || agentDraft.transactionState !== "committed") {
      return;
    }

    setLastAgentDraft({
      ...agentDraft,
      status: "discarded",
      updatedAt: new Date().toISOString(),
    });
    agentDraftBaseRef.current = null;
    setAgentDraft(null);
    toast.success(messages.agentDraftDiscarded, {
      closeButton: true,
    });
  }, [agentDraft, messages]);

  return {
    agentDraft,
    agentDraftState: agentDraft ?? lastAgentDraft,
    applyAgentDraft,
    discardAgentDraft,
    previewAgentEdits,
    resetAgentDraft,
    rollbackAgentDraft,
  };
}
