import type { ResumeDraftDiff } from "@/types/resume";

/** Inserts deleted targets beside their nearest surviving neighbor. */
export function interleaveDeletedDiffs<T extends { id: string }>(
  entries: T[],
  deletedDiffs: ResumeDraftDiff[],
) {
  const entryIds = new Set(entries.map((entry) => entry.id));
  const beforeById = new Map<string, ResumeDraftDiff[]>();
  const afterById = new Map<string, ResumeDraftDiff[]>();
  const unplaced: ResumeDraftDiff[] = [];

  for (const diff of deletedDiffs) {
    if (diff.beforeNextId && entryIds.has(diff.beforeNextId)) {
      const before = beforeById.get(diff.beforeNextId) ?? [];
      before.push(diff);
      beforeById.set(diff.beforeNextId, before);
    } else if (
      diff.beforePreviousId &&
      entryIds.has(diff.beforePreviousId)
    ) {
      const after = afterById.get(diff.beforePreviousId) ?? [];
      after.push(diff);
      afterById.set(diff.beforePreviousId, after);
    } else {
      unplaced.push(diff);
    }
  }

  return {
    afterById,
    beforeById,
    unplaced,
  };
}
