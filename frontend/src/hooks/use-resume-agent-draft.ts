import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  useAgentDraftReviewSelection,
  waitForAgentDraftReviewExit,
} from "@/hooks/use-agent-draft-review-selection";
import type { AppMessages } from "@/i18n";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import {
  createProvisionalAgentDraftReviewItems,
  createReviewItemIdByOperationId,
  getAgentDraftReviewSuccessorId,
  getAgentDraftSnapshotFromMessages,
  getPendingAgentDraftReviewItems,
  projectAgentDraftReview,
  type AgentDraftReviewProjection,
} from "@/lib/agent-draft-review";
import type { AgentDraftDecisionResolution } from "@/lib/agent-session-run-client";
import { createId } from "@/lib/resume";
import {
  createAgentDraftBaseSnapshot,
  type AgentDraftApplyError,
} from "@/lib/resume-agent-edits";
import type {
  AgentDraftDecisionStatus,
  AgentDraftReviewItem,
  AgentDraftSnapshot,
  AgentDraftState,
  AgentResumeEditSuggestion,
  AgentSessionResponse,
  AgentTransactionState,
} from "@/types/api";
import type { ResumeData } from "@/types/resume";

export interface AgentDraftReviewController {
  applyScope: () => Promise<AgentSessionResponse | null>;
  disabled: boolean;
  discardScope: () => Promise<AgentSessionResponse | null>;
  exitingReviewItemIds: string[];
  mode: "all" | "single";
  pendingCount: number;
  pendingItems: AgentDraftReviewItem[];
  projection: AgentDraftReviewProjection;
  resolvingStatus: AgentDraftDecisionStatus | null;
  reviewItemIdByOperationId: Record<string, string>;
  selectFirst: () => void;
  selectItem: (reviewItemId: string) => void;
  selectNext: () => void;
  selectPrevious: () => void;
  selectedIndex: number;
  selectedItem: AgentDraftReviewItem | null;
  selectedItemId: string | null;
  showAll: () => void;
}

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

function createAgentDraftState({
  baseResume,
  currentResume,
  draftId,
  edits,
  existingCreatedAt,
  reviewItems,
  sourceMessageId,
  transactionState,
}: {
  baseResume: ResumeData;
  currentResume: ResumeData;
  draftId: string;
  edits: AgentResumeEditSuggestion[];
  existingCreatedAt?: string;
  reviewItems: AgentDraftReviewItem[];
  sourceMessageId?: string;
  transactionState: AgentTransactionState;
}) {
  const projection = projectAgentDraftReview({
    baseResume,
    currentResume,
    edits,
    reviewItems,
  });
  const now = new Date().toISOString();

  return {
    draft: {
      createdAt: existingCreatedAt ?? now,
      diffs: projection.diffs,
      edits,
      id: draftId,
      pendingCount: getPendingAgentDraftReviewItems(reviewItems).length,
      resume: projection.resume,
      reviewItems,
      sourceMessageId,
      transactionState,
      updatedAt: now,
    } satisfies AgentDraftState,
    errors: projection.errors,
  };
}

export function useResumeAgentDraft({
  messages,
  onApplyResume,
  onResolveDraftReview,
  resume,
  resumeId,
}: {
  messages: AppMessages;
  onApplyResume: (resume: ResumeData) => void;
  onResolveDraftReview: (
    messageId: string,
    resume: ResumeData,
    reviewItemIds: string[],
    status: AgentDraftDecisionStatus,
  ) => Promise<AgentDraftDecisionResolution>;
  resume: ResumeData;
  resumeId?: string;
}) {
  const [storedAgentDraft, setStoredAgentDraft] =
    useState<AgentDraftState | null>(null);
  const [resolvingStatus, setResolvingStatus] =
    useState<AgentDraftDecisionStatus | null>(null);
  const agentDraftBaseRef = useRef<{
    draftId: string;
    resume: ResumeData;
  } | null>(null);
  const storedAgentDraftRef = useRef(storedAgentDraft);
  const currentResumeRef = useRef(resume);
  const reviewSelectionControllerRef = useRef<ReturnType<
    typeof useAgentDraftReviewSelection
  > | null>(null);
  const draftDecisionTokenRef = useRef<symbol | null>(null);
  storedAgentDraftRef.current = storedAgentDraft;
  currentResumeRef.current = resume;

  const resetAgentDraft = useCallback(() => {
    draftDecisionTokenRef.current = null;
    agentDraftBaseRef.current = null;
    setStoredAgentDraft(null);
    setResolvingStatus(null);
    reviewSelectionControllerRef.current?.reset();
  }, []);

  const clearRejectedAgentDraft = useCallback((sourceMessageId?: string) => {
    const shouldClear = (draft: AgentDraftState | null) =>
      Boolean(
        draft &&
          draft.pendingCount > 0 &&
          (!sourceMessageId || draft.sourceMessageId === sourceMessageId),
      );

    setStoredAgentDraft((draft) => {
      if (!shouldClear(draft)) {
        return draft;
      }
      if (agentDraftBaseRef.current?.draftId === draft?.id) {
        agentDraftBaseRef.current = null;
      }
      return null;
    });
  }, []);

  const previewAgentEdits = useCallback(
    (
      edits: AgentResumeEditSuggestion[],
      baseResume: ResumeData,
      sourceMessageId?: string,
      transactionState: AgentTransactionState = "committed",
    ) => {
      const draftBase = createAgentDraftBaseSnapshot(baseResume);
      const reviewItems = createProvisionalAgentDraftReviewItems(edits);
      const draftId = sourceMessageId
        ? `agent-draft-${sourceMessageId}`
        : createId("agent-draft");
      const currentDraft = storedAgentDraftRef.current;
      const result = createAgentDraftState({
        baseResume: draftBase,
        currentResume: currentResumeRef.current,
        draftId,
        edits,
        existingCreatedAt:
          currentDraft?.id === draftId ? currentDraft.createdAt : undefined,
        reviewItems,
        sourceMessageId,
        transactionState,
      });

      if (result.errors.length > 0) {
        if (transactionState === "committed") {
          clearRejectedAgentDraft(sourceMessageId);
          toast.error(messages.agentDraftBatchRejected, {
            closeButton: true,
            description: formatAgentDraftErrors(result.errors, messages),
          });
        }
        return;
      }
      if (reviewItems.length === 0) {
        if (transactionState === "committed") {
          clearRejectedAgentDraft(sourceMessageId);
        }
        return;
      }

      agentDraftBaseRef.current = { draftId, resume: draftBase };
      setStoredAgentDraft(result.draft);
      if (currentDraft?.id !== draftId) {
        reviewSelectionControllerRef.current?.reset();
      }
    },
    [clearRejectedAgentDraft, messages],
  );

  const rollbackAgentDraft = useCallback((sourceMessageId?: string) => {
    const shouldRollback = (draft: AgentDraftState | null) =>
      Boolean(
        draft &&
          draft.pendingCount > 0 &&
          (sourceMessageId
            ? draft.sourceMessageId === sourceMessageId
            : draft.transactionState === "provisional"),
      );

    setStoredAgentDraft((draft) => {
      if (!shouldRollback(draft)) {
        return draft;
      }
      if (agentDraftBaseRef.current?.draftId === draft?.id) {
        agentDraftBaseRef.current = null;
      }
      return null;
    });
  }, []);

  const reconcileAgentDraft = useCallback(
    (snapshot: AgentDraftSnapshot | null) => {
      if (!snapshot) {
        draftDecisionTokenRef.current = null;
        setStoredAgentDraft((draft) =>
          draft?.transactionState === "committed" ? null : draft,
        );
        return;
      }

      const draftId = `agent-draft-${snapshot.sourceMessageId}`;
      const currentDraft = storedAgentDraftRef.current;
      const result = createAgentDraftState({
        baseResume: snapshot.baseResume,
        currentResume: currentResumeRef.current,
        draftId,
        edits: snapshot.edits,
        existingCreatedAt:
          currentDraft?.id === draftId ? currentDraft.createdAt : undefined,
        reviewItems: snapshot.reviewItems,
        sourceMessageId: snapshot.sourceMessageId,
        transactionState: snapshot.transactionState,
      });

      if (result.errors.length > 0) {
        clearRejectedAgentDraft(snapshot.sourceMessageId);
        toast.error(messages.agentDraftBatchRejected, {
          closeButton: true,
          description: formatAgentDraftErrors(result.errors, messages),
        });
        return;
      }

      if (result.draft.pendingCount === 0) {
        agentDraftBaseRef.current = null;
        setStoredAgentDraft(null);
        return;
      }

      agentDraftBaseRef.current = {
        draftId,
        resume: createAgentDraftBaseSnapshot(snapshot.baseResume),
      };
      setStoredAgentDraft(result.draft);
      reviewSelectionControllerRef.current?.reconcile(
        getPendingAgentDraftReviewItems(snapshot.reviewItems),
        currentDraft?.id !== draftId,
      );
    },
    [clearRejectedAgentDraft, messages],
  );

  const agentDraft = useMemo(() => {
    if (!storedAgentDraft) {
      return null;
    }
    const draftBase = agentDraftBaseRef.current;
    if (!draftBase || draftBase.draftId !== storedAgentDraft.id) {
      return storedAgentDraft;
    }

    const projection = projectAgentDraftReview({
      baseResume: draftBase.resume,
      currentResume: resume,
      edits: storedAgentDraft.edits,
      reviewItems: storedAgentDraft.reviewItems,
    });
    if (projection.errors.length > 0) {
      return {
        ...storedAgentDraft,
        diffs: [],
        resume,
      };
    }
    return {
      ...storedAgentDraft,
      diffs: projection.diffs,
      resume: projection.resume,
    };
  }, [resume, storedAgentDraft]);
  const agentDraftRef = useRef(agentDraft);
  agentDraftRef.current = agentDraft;

  const pendingItems = useMemo(
    () => getPendingAgentDraftReviewItems(agentDraft?.reviewItems ?? []),
    [agentDraft?.reviewItems],
  );
  const reviewSelection = useAgentDraftReviewSelection({
    decisionPending: resolvingStatus !== null,
    pendingItems,
  });
  reviewSelectionControllerRef.current = reviewSelection;
  const {
    exitingReviewItemIds,
    isTransitioning,
    mode: reviewMode,
    selectFirst,
    selectItem,
    selectNext,
    selectPrevious,
    selectedIndex,
    selectedItem,
    selectedItemId,
    showAll,
  } = reviewSelection;

  const resolveCurrentScope = useCallback(
    async (status: AgentDraftDecisionStatus) => {
      const draft = agentDraftRef.current;
      if (!draft || draft.transactionState !== "committed") {
        return null;
      }

      const draftBase = agentDraftBaseRef.current;
      if (!draftBase || draftBase.draftId !== draft.id) {
        return null;
      }
      if (!resumeId || !draft.sourceMessageId) {
        toast.error(messages.agentRequestFailed, { closeButton: true });
        return null;
      }
      if (draftDecisionTokenRef.current) {
        return null;
      }

      const previousPendingItems = getPendingAgentDraftReviewItems(
        draft.reviewItems,
      );
      const selection = reviewSelectionControllerRef.current;
      if (!selection || selection.isTransitioning) {
        return null;
      }
      const selectedItem = selection.mode === "single"
        ? previousPendingItems.find(
            (item) => item.id === selection.selectedItemId,
          ) ?? previousPendingItems[0]
        : null;
      const scopeItems = selection.mode === "single"
        ? selectedItem
          ? [selectedItem]
          : []
        : previousPendingItems;
      if (scopeItems.length === 0) {
        return null;
      }
      const reviewItemIds = scopeItems.map((item) => item.id);
      const candidate = status === "applied"
        ? projectAgentDraftReview({
            baseResume: draftBase.resume,
            currentResume: currentResumeRef.current,
            edits: draft.edits,
            reviewItemIds,
            reviewItems: draft.reviewItems,
          })
        : null;
      if (candidate?.errors.length) {
        toast.error(messages.agentDraftBatchRejected, {
          closeButton: true,
          description: formatAgentDraftErrors(candidate.errors, messages),
        });
        return null;
      }

      const decisionToken = Symbol("agent-draft-decision");
      if (!selection.beginDecisionExit(reviewItemIds)) {
        return null;
      }
      draftDecisionTokenRef.current = decisionToken;
      setResolvingStatus(status);

      try {
        const decisionRequest = onResolveDraftReview(
          draft.sourceMessageId,
          currentResumeRef.current,
          reviewItemIds,
          status,
        );
        const [resolution] = await Promise.all([
          decisionRequest,
          waitForAgentDraftReviewExit(),
        ]);
        if (
          draftDecisionTokenRef.current !== decisionToken ||
          agentDraftRef.current?.id !== draft.id
        ) {
          return null;
        }

        const authoritativeResume = resolution.resume?.resume.resume;
        if (authoritativeResume) {
          currentResumeRef.current = authoritativeResume;
          onApplyResume(authoritativeResume);
        }

        const snapshot = getAgentDraftSnapshotFromMessages(
          resolution.session.messages,
        );
        reconcileAgentDraft(snapshot);

        const requestedItemsResolved = reviewItemIds.every((reviewItemId) =>
          resolution.draft?.reviewItems.some(
            (item) => item.id === reviewItemId && item.status === status,
          ),
        );
        if (
          selection.mode === "single" &&
          selectedItem &&
          requestedItemsResolved
        ) {
          const remainingPendingItems = getPendingAgentDraftReviewItems(
            resolution.draft?.reviewItems ?? [],
          );
          reviewSelectionControllerRef.current?.adoptResolvedItems(
            remainingPendingItems,
            getAgentDraftReviewSuccessorId(
              previousPendingItems,
              remainingPendingItems,
              selectedItem.id,
            ),
          );
        }

        if (requestedItemsResolved) {
          toast.success(
            status === "applied"
              ? messages.agentDraftApplied
              : messages.agentDraftDiscarded,
            { closeButton: true },
          );
        }
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
          setResolvingStatus(null);
          reviewSelectionControllerRef.current?.endDecisionExit();
        }
      }
    },
    [
      messages,
      onApplyResume,
      onResolveDraftReview,
      reconcileAgentDraft,
      resumeId,
    ],
  );
  const applyAgentDraft = useCallback(
    () => resolveCurrentScope("applied"),
    [resolveCurrentScope],
  );
  const discardAgentDraft = useCallback(
    () => resolveCurrentScope("discarded"),
    [resolveCurrentScope],
  );

  const review = useMemo<AgentDraftReviewController | null>(() => {
    if (
      !agentDraft ||
      agentDraft.transactionState !== "committed" ||
      pendingItems.length === 0
    ) {
      return null;
    }

    const draftBase = agentDraftBaseRef.current;
    if (!draftBase || draftBase.draftId !== agentDraft.id) {
      return null;
    }
    const projection = projectAgentDraftReview({
      baseResume: draftBase.resume,
      currentResume: resume,
      edits: agentDraft.edits,
      reviewItemIds: selectedItem
        ? [selectedItem.id]
        : undefined,
      reviewItems: agentDraft.reviewItems,
    });

    return {
      applyScope: applyAgentDraft,
      disabled: resolvingStatus !== null || isTransitioning,
      discardScope: discardAgentDraft,
      exitingReviewItemIds,
      mode: reviewMode,
      pendingCount: pendingItems.length,
      pendingItems,
      projection,
      resolvingStatus,
      reviewItemIdByOperationId: createReviewItemIdByOperationId(
        agentDraft.reviewItems,
      ),
      selectFirst,
      selectItem,
      selectNext,
      selectPrevious,
      selectedIndex,
      selectedItem,
      selectedItemId,
      showAll,
    };
  }, [
    agentDraft,
    applyAgentDraft,
    discardAgentDraft,
    exitingReviewItemIds,
    isTransitioning,
    pendingItems,
    resolvingStatus,
    resume,
    reviewMode,
    selectFirst,
    selectItem,
    selectNext,
    selectPrevious,
    selectedIndex,
    selectedItem,
    selectedItemId,
    showAll,
  ]);

  return {
    agentDraft,
    agentDraftState: agentDraft,
    applyAgentDraft,
    discardAgentDraft,
    previewAgentEdits,
    reconcileAgentDraft,
    resetAgentDraft,
    review,
    rollbackAgentDraft,
  };
}
