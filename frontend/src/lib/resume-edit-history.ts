import { countResumeChanges } from "@/lib/workspace-change-tracking";
import type { ResumeWorkspaceItem } from "@/types/resume";

const HISTORY_LIMIT = 100;
const INPUT_GROUP_DELAY_MS = 500;

export interface ResumeEditHistory {
  document: ResumeWorkspaceItem | null;
  past: ResumeWorkspaceItem[];
  future: ResumeWorkspaceItem[];
  group: string | null;
  editedAt: number;
}

export function createResumeEditHistory(
  document: ResumeWorkspaceItem | null,
): ResumeEditHistory {
  return { document, past: [], future: [], group: null, editedAt: 0 };
}

export function recordResumeEdit(
  history: ResumeEditHistory,
  document: ResumeWorkspaceItem,
  editedAt: number,
  group?: string,
): ResumeEditHistory {
  if (
    !history.document ||
    countResumeChanges(history.document, document) === 0
  ) {
    return history;
  }
  const merge = Boolean(
    group &&
    group === history.group &&
    editedAt - history.editedAt < INPUT_GROUP_DELAY_MS,
  );
  return {
    document,
    past: merge
      ? history.past
      : [...history.past, history.document].slice(-HISTORY_LIMIT),
    future: [],
    group: group ?? null,
    editedAt,
  };
}

export function travelResumeHistory(
  history: ResumeEditHistory,
  direction: "undo" | "redo",
): ResumeEditHistory {
  const source = direction === "undo" ? history.past : history.future;
  const target = source.at(-1);
  if (!target || !history.document) return history;
  return {
    document: { ...target, updatedAt: history.document.updatedAt },
    past:
      direction === "undo"
        ? source.slice(0, -1)
        : [...history.past, history.document],
    future:
      direction === "redo"
        ? source.slice(0, -1)
        : [...history.future, history.document],
    group: null,
    editedAt: 0,
  };
}
