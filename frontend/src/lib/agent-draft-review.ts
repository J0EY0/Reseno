import type {
  AgentDraftReviewItem,
  AgentDraftSnapshot,
  AgentResumeEditSuggestion,
  AgentStoredMessage,
} from "@/types/api";
import type { ResumeData, ResumeDraftDiff } from "@/types/resume";

import {
  applyAgentEditsWithMerge,
  type AgentDraftApplyError,
} from "./resume-agent-edits";

export type AgentDraftReviewMode = "all" | "single";

export interface AgentDraftReviewProjection {
  diffs: ResumeDraftDiff[];
  errors: AgentDraftApplyError[];
  resume: ResumeData;
  reviewItemIds: string[];
}

export function getAgentDraftSnapshotFromMessages(
  messages: AgentStoredMessage[],
): AgentDraftSnapshot | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const response = message.response;
    if (
      message.role !== "assistant" ||
      response?.transactionState !== "committed" ||
      !response.draft ||
      !response.edits?.length
    ) {
      continue;
    }

    return {
      baseResume: response.draft.baseResume,
      edits: response.edits,
      reviewItems: response.draft.reviewItems,
      sourceMessageId: message.id,
      transactionState: "committed",
    };
  }

  return null;
}

export function createProvisionalAgentDraftReviewItems(
  edits: AgentResumeEditSuggestion[],
): AgentDraftReviewItem[] {
  return edits.map((edit) => ({
    editIds: [edit.id],
    id: `agent-review-${edit.id}`,
    status: "pending",
  }));
}

export function getPendingAgentDraftReviewItems(
  reviewItems: AgentDraftReviewItem[],
) {
  return reviewItems.filter((item) => item.status === "pending");
}

function getReviewItemEdits(
  reviewItems: AgentDraftReviewItem[],
  edits: AgentResumeEditSuggestion[],
) {
  const editById = new Map(edits.map((edit) => [edit.id, edit]));
  const selectedEdits: AgentResumeEditSuggestion[] = [];

  for (const reviewItem of reviewItems) {
    for (const editId of reviewItem.editIds) {
      const edit = editById.get(editId);
      if (!edit) {
        throw new Error(
          `Agent review item ${reviewItem.id} references missing edit ${editId}.`,
        );
      }
      selectedEdits.push(edit);
    }
  }

  return selectedEdits;
}

/**
 * Builds one complete preview from the formal resume and the selected review
 * items. The selection controls both rendered content and highlighted diffs.
 */
export function projectAgentDraftReview({
  baseResume,
  currentResume,
  edits,
  reviewItemIds,
  reviewItems,
}: {
  baseResume: ResumeData;
  currentResume: ResumeData;
  edits: AgentResumeEditSuggestion[];
  reviewItemIds?: string[];
  reviewItems: AgentDraftReviewItem[];
}): AgentDraftReviewProjection {
  const requestedIds = reviewItemIds ??
    getPendingAgentDraftReviewItems(reviewItems).map((item) => item.id);
  const requestedIdSet = new Set(requestedIds);
  const selectedItems = reviewItems.filter(
    (item) => item.status === "pending" && requestedIdSet.has(item.id),
  );
  const selectedIdSet = new Set(selectedItems.map((item) => item.id));

  if (
    requestedIds.length !== requestedIdSet.size ||
    selectedItems.length !== requestedIds.length
  ) {
    throw new Error("Agent review selection contains an unavailable item.");
  }

  // Preserve the caller's review-item order even if the durable list is later
  // stored in a different presentation order.
  const orderedItems = requestedIds.map((id) => {
    const item = selectedItems.find((candidate) => candidate.id === id);
    if (!item || !selectedIdSet.has(id)) {
      throw new Error(`Agent review item ${id} is unavailable.`);
    }
    return item;
  });
  const result = applyAgentEditsWithMerge(
    baseResume,
    currentResume,
    getReviewItemEdits(orderedItems, edits),
  );

  return {
    diffs: result.diffs,
    errors: result.errors,
    resume: result.resume,
    reviewItemIds: requestedIds,
  };
}

export function createReviewItemIdByOperationId(
  reviewItems: AgentDraftReviewItem[],
) {
  const result: Record<string, string> = {};

  for (const item of getPendingAgentDraftReviewItems(reviewItems)) {
    for (const editId of item.editIds) {
      result[editId] = item.id;
    }
  }

  return result;
}

export function getAdjacentAgentDraftReviewItemId(
  pendingItems: AgentDraftReviewItem[],
  selectedItemId: string | null,
  direction: -1 | 1,
) {
  if (pendingItems.length === 0) {
    return null;
  }

  const selectedIndex = pendingItems.findIndex(
    (item) => item.id === selectedItemId,
  );
  if (selectedIndex < 0) {
    return direction > 0
      ? pendingItems[0].id
      : pendingItems[pendingItems.length - 1].id;
  }

  const nextIndex =
    (selectedIndex + direction + pendingItems.length) % pendingItems.length;
  return pendingItems[nextIndex].id;
}

export function getAgentDraftReviewSuccessorId(
  previousPendingItems: AgentDraftReviewItem[],
  remainingPendingItems: AgentDraftReviewItem[],
  resolvedItemId: string,
) {
  if (remainingPendingItems.length === 0) {
    return null;
  }

  const resolvedIndex = previousPendingItems.findIndex(
    (item) => item.id === resolvedItemId,
  );
  const successorIndex = Math.min(
    Math.max(resolvedIndex, 0),
    remainingPendingItems.length - 1,
  );
  return remainingPendingItems[successorIndex].id;
}
