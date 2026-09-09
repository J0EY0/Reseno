import type {
  AgentDraftReviewItem,
  AgentDraftSnapshot,
  AgentResumeEditSuggestion,
  AgentStoredMessage,
} from "@/types/api";
import type { ResumeData, ResumeDraftDiff } from "@/types/resume";

import {
  applyAgentEditsToDraft,
  applyAgentEditsWithMerge,
  createAgentDraftBaseSnapshot,
  type AgentDraftApplyError,
  type AgentDraftApplyResult,
} from "./resume-agent-edits";

export type AgentDraftConflictResolution = "use-original" | "keep-manual";

export interface AgentDraftReviewProjection {
  diffs: ResumeDraftDiff[];
  errors: AgentDraftApplyError[];
  resume: ResumeData;
  reviewItemIds: string[];
}

export interface AgentDraftReviewConflict {
  reviewItemId: string;
  diffs: ResumeDraftDiff[];
}

export interface AgentDraftReviewPreview extends AgentDraftReviewProjection {
  conflicts: AgentDraftReviewConflict[];
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

function mergePendingReviewKeepingManual(
  baseResume: ResumeData,
  currentResume: ResumeData,
  edits: AgentResumeEditSuggestion[],
  reviewItems: AgentDraftReviewItem[],
): AgentDraftApplyResult {
  const applied = applyAgentEditsToDraft(
    baseResume,
    getReviewItemEdits(
      reviewItems.filter((item) => item.status === "applied"),
      edits,
    ),
  );
  const pendingItems = getPendingAgentDraftReviewItems(reviewItems);
  const validation =
    applied.errors.length > 0
      ? applied
      : applyAgentEditsToDraft(
          applied.resume,
          getReviewItemEdits(pendingItems, edits),
        );
  if (validation.errors.length > 0) {
    return {
      ...validation,
      resume: createAgentDraftBaseSnapshot(currentResume),
    };
  }

  let base = applied.resume;
  let resume = createAgentDraftBaseSnapshot(currentResume);
  const diffs: ResumeDraftDiff[] = [];
  let appliedCount = 0;
  for (const item of pendingItems) {
    const groupEdits = getReviewItemEdits([item], edits);
    const result = applyAgentEditsWithMerge(
      base,
      resume,
      groupEdits,
      "keep-manual",
    );
    if (result.errors.some((error) => error.reason !== "conflict")) {
      return { ...result, resume: createAgentDraftBaseSnapshot(currentResume) };
    }
    if (result.errors.length === 0) {
      resume = result.resume;
      diffs.push(...result.diffs);
      appliedCount += result.appliedCount;
    }
    base = applyAgentEditsToDraft(base, groupEdits).resume;
  }
  return { resume, diffs, errors: [], appliedCount };
}

/**
 * Builds one complete preview from the formal resume and the selected review
 * items. The selection controls both rendered content and highlighted diffs.
 */
export function projectAgentDraftReview({
  baseResume,
  conflictResolution,
  currentResume,
  edits,
  reviewItemIds,
  reviewItems,
}: {
  baseResume: ResumeData;
  conflictResolution?: AgentDraftConflictResolution;
  currentResume: ResumeData;
  edits: AgentResumeEditSuggestion[];
  reviewItemIds?: string[];
  reviewItems: AgentDraftReviewItem[];
}): AgentDraftReviewProjection {
  const pendingItems = getPendingAgentDraftReviewItems(reviewItems);
  const requestedIds = reviewItemIds ?? pendingItems.map((item) => item.id);
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

  if (conflictResolution) {
    if (!reviewItemIds?.length || requestedIds.length !== pendingItems.length) {
      throw new Error(
        "Agent conflict resolution requires every pending review item.",
      );
    }
    const result =
      conflictResolution === "use-original"
        ? applyAgentEditsToDraft(
            baseResume,
            getReviewItemEdits(
              reviewItems.filter(
                (item) =>
                  item.status === "pending" || item.status === "applied",
              ),
              edits,
            ),
          )
        : mergePendingReviewKeepingManual(
            baseResume,
            currentResume,
            edits,
            reviewItems,
          );
    return {
      diffs: result.diffs,
      errors: result.errors,
      resume:
        result.errors.length > 0
          ? createAgentDraftBaseSnapshot(currentResume)
          : result.resume,
      reviewItemIds: requestedIds,
    };
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

export function previewAgentDraftReview(
  input: Omit<
    Parameters<typeof projectAgentDraftReview>[0],
    "conflictResolution"
  >,
): AgentDraftReviewPreview {
  const projection = projectAgentDraftReview(input);
  if (
    projection.errors.length === 0 ||
    projection.errors.some((error) => error.reason !== "conflict")
  ) {
    return { ...projection, conflicts: [] };
  }

  let baseResume = input.baseResume;
  let resume = input.currentResume;
  const diffs: ResumeDraftDiff[] = [];
  const errors: AgentDraftApplyError[] = [];
  const conflicts: AgentDraftReviewConflict[] = [];

  for (const reviewItemId of projection.reviewItemIds) {
    const item = input.reviewItems.find((item) => item.id === reviewItemId)!;
    const edits = getReviewItemEdits([item], input.edits);
    const proposal = applyAgentEditsToDraft(baseResume, edits);
    const merged = applyAgentEditsWithMerge(baseResume, resume, edits);

    if (merged.errors.length > 0) {
      errors.push(...merged.errors);
      conflicts.push({
        reviewItemId,
        diffs: proposal.diffs,
      });
    } else {
      resume = merged.resume;
      diffs.push(...merged.diffs);
    }
    baseResume = proposal.resume;
  }

  return {
    conflicts,
    diffs,
    errors,
    resume,
    reviewItemIds: projection.reviewItemIds,
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
