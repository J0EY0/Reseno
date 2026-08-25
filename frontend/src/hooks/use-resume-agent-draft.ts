import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import {
  resolveAgentDraftDecision,
  type AgentDraftDecisionResolution,
} from "@/lib/agent-session-run-client";
import {
  applyAgentEditsWithMerge,
  createAgentDraftBaseSnapshot,
  type AgentDraftApplyError,
} from "@/lib/resume-agent-edits";
import { createId } from "@/lib/resume";
import type {
  AgentDraftState,
  AgentDraftSnapshot,
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
  onResolveAppliedDraft,
  resume,
  resumeId,
}: {
  messages: AppMessages;
  onApplyResume: (resume: ResumeData) => void;
  onResolveAppliedDraft: (
    messageId: string,
    resume: ResumeData,
  ) => Promise<AgentDraftDecisionResolution>;
  resume: ResumeData;
  resumeId?: string;
}) {
  const [agentDraft, setAgentDraft] = useState<AgentDraftState | null>(null);
  const [lastAgentDraft, setLastAgentDraft] =
    useState<AgentDraftState | null>(null);
  const agentDraftBaseRef = useRef<{
    draftId: string;
    resume: ResumeData;
  } | null>(null);
  const agentDraftRef = useRef(agentDraft);
  const currentResumeRef = useRef(resume);
  const draftDecisionTokenRef = useRef<symbol | null>(null);
  agentDraftRef.current = agentDraft;
  currentResumeRef.current = resume;

  const resetAgentDraft = useCallback(() => {
    draftDecisionTokenRef.current = null;
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

  const reconcileAgentDraft = useCallback(
    (snapshot: AgentDraftSnapshot | null) => {
      if (snapshot?.status === "pending") {
        previewAgentEdits(
          snapshot.edits,
          snapshot.baseResume,
          snapshot.sourceMessageId,
          snapshot.transactionState,
        );
        return;
      }

      draftDecisionTokenRef.current = null;
      agentDraftBaseRef.current = null;
      setAgentDraft((draft) =>
        draft?.transactionState === "committed" ? null : draft,
      );
      setLastAgentDraft((draft) =>
        draft?.transactionState === "committed" ? null : draft,
      );
    },
    [previewAgentEdits],
  );

  const mergeCommittedAgentDraft = useCallback(
    (
      draft: AgentDraftState,
      baseResume: ResumeData,
      reportConflict = true,
    ) => {
      const result = applyAgentEditsWithMerge(
        baseResume,
        currentResumeRef.current,
        draft.edits,
      );

      if (result.errors.length > 0) {
        if (reportConflict) {
          toast.error(messages.agentDraftBatchRejected, {
            description: formatAgentDraftErrors(result.errors, messages),
            closeButton: true,
          });
        }
        return null;
      }

      return result;
    },
    [messages],
  );

  const adoptAppliedDraftResolution = useCallback(
    (
      resolution: AgentDraftDecisionResolution,
      draft: AgentDraftState,
      baseResume: ResumeData,
    ) => {
      if (!resolution.committed) {
        const authoritativeResume = resolution.resume?.resume.resume;
        if (!authoritativeResume) {
          throw new Error("The authoritative applied resume is unavailable.");
        }
        onApplyResume(authoritativeResume);
        return authoritativeResume;
      }

      const result = mergeCommittedAgentDraft(draft, baseResume, false);
      if (result) {
        onApplyResume(result.resume);
        return result.resume;
      }

      // A same-field edit made after this tab committed is newer than the
      // submitted candidate. Keep it as a dirty edit after the saved receipt.
      return currentResumeRef.current;
    },
    [mergeCommittedAgentDraft, onApplyResume],
  );

  const applyAgentDraft = useCallback(async () => {
    if (!agentDraft || agentDraft.transactionState !== "committed") {
      return null;
    }

    const draftBase = agentDraftBaseRef.current;
    if (!draftBase || draftBase.draftId !== agentDraft.id) {
      return null;
    }

    const candidate = mergeCommittedAgentDraft(agentDraft, draftBase.resume);
    if (!candidate) {
      return null;
    }

    if (!resumeId || !agentDraft.sourceMessageId) {
      toast.error(messages.agentRequestFailed, { closeButton: true });
      return null;
    }

    if (draftDecisionTokenRef.current) {
      return null;
    }
    const decisionToken = Symbol("agent-draft-decision");
    draftDecisionTokenRef.current = decisionToken;

    try {
      const resolution = await onResolveAppliedDraft(
        agentDraft.sourceMessageId,
        candidate.resume,
      );
      if (
        draftDecisionTokenRef.current !== decisionToken ||
        agentDraftRef.current?.id !== agentDraft.id
      ) {
        return null;
      }

      if (resolution.status === "pending") {
        return resolution.session;
      }
      let resolvedResume = agentDraft.resume;
      if (resolution.status === "applied") {
        resolvedResume = adoptAppliedDraftResolution(
          resolution,
          agentDraft,
          draftBase.resume,
        );
      }
      if (!resolution.status) {
        agentDraftBaseRef.current = null;
        setAgentDraft(null);
        setLastAgentDraft(null);
        return resolution.session;
      }

      setLastAgentDraft({
        ...agentDraft,
        status: resolution.status,
        updatedAt: new Date().toISOString(),
        resume: resolvedResume,
      });
      agentDraftBaseRef.current = null;
      setAgentDraft(null);
      toast.success(
        resolution.status === "applied"
          ? messages.agentDraftApplied
          : messages.agentDraftDiscarded,
        { closeButton: true },
      );
      return resolution.session;
    } catch (error) {
      if (isAbortError(error)) {
        return null;
      }
      console.error("Failed to persist the Agent draft decision.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.agentRequestFailed, { closeButton: true });
      }
      return null;
    } finally {
      if (draftDecisionTokenRef.current === decisionToken) {
        draftDecisionTokenRef.current = null;
      }
    }
  }, [
    agentDraft,
    adoptAppliedDraftResolution,
    mergeCommittedAgentDraft,
    messages,
    onResolveAppliedDraft,
    resumeId,
  ]);

  const discardAgentDraft = useCallback(async () => {
    if (!agentDraft || agentDraft.transactionState !== "committed") {
      return null;
    }

    const draftBase = agentDraftBaseRef.current;
    if (!draftBase || draftBase.draftId !== agentDraft.id) {
      return null;
    }

    if (!resumeId || !agentDraft.sourceMessageId) {
      toast.error(messages.agentRequestFailed, { closeButton: true });
      return null;
    }
    if (draftDecisionTokenRef.current) {
      return null;
    }
    const decisionToken = Symbol("agent-draft-decision");
    draftDecisionTokenRef.current = decisionToken;

    try {
      const resolution = await resolveAgentDraftDecision(
        resumeId,
        agentDraft.sourceMessageId,
        { status: "discarded" },
      );
      if (
        draftDecisionTokenRef.current !== decisionToken ||
        agentDraftRef.current?.id !== agentDraft.id
      ) {
        return null;
      }

      if (resolution.status === "pending") {
        return resolution.session;
      }
      if (!resolution.status) {
        agentDraftBaseRef.current = null;
        setAgentDraft(null);
        setLastAgentDraft(null);
        return resolution.session;
      }

      let resolvedResume = agentDraft.resume;
      if (resolution.status === "applied") {
        resolvedResume = adoptAppliedDraftResolution(
          resolution,
          agentDraft,
          draftBase.resume,
        );
      }

      setLastAgentDraft({
        ...agentDraft,
        status: resolution.status,
        updatedAt: new Date().toISOString(),
        resume: resolvedResume,
      });
      agentDraftBaseRef.current = null;
      setAgentDraft(null);
      toast.success(
        resolution.status === "applied"
          ? messages.agentDraftApplied
          : messages.agentDraftDiscarded,
        { closeButton: true },
      );
      return resolution.session;
    } catch (error) {
      console.error("Failed to persist the Agent draft decision.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.agentRequestFailed, { closeButton: true });
      }
      return null;
    } finally {
      if (draftDecisionTokenRef.current === decisionToken) {
        draftDecisionTokenRef.current = null;
      }
    }
  }, [
    agentDraft,
    adoptAppliedDraftResolution,
    messages,
    resumeId,
  ]);

  return {
    agentDraft,
    agentDraftState: agentDraft ?? lastAgentDraft,
    applyAgentDraft,
    discardAgentDraft,
    previewAgentEdits,
    reconcileAgentDraft,
    resetAgentDraft,
    rollbackAgentDraft,
  };
}
