import type { AgentResumeEditSuggestion } from "@/types/api";
import type { ResumeEditOperation } from "@/types/resume-edit-operation.generated";
import type {
  ResumeData,
  ResumeDraftDiff,
  ResumeSection,
  ResumeSectionItem,
} from "@/types/resume";

export type AgentDraftApplyErrorReason =
  | "missing_operation"
  | "invalid_operation"
  | "target_not_found"
  | "duplicate_target"
  | "no_change"
  | "conflict";

export interface AgentDraftApplyError {
  editId: string;
  title: string;
  operationType?: ResumeEditOperation["type"];
  target: string;
  reason: AgentDraftApplyErrorReason;
}

export interface AgentDraftApplyResult {
  resume: ResumeData;
  diffs: ResumeDraftDiff[];
  appliedCount: number;
  errors: AgentDraftApplyError[];
}

export type OperationApplyResult =
  | { ok: true; diff: ResumeDraftDiff }
  | {
      ok: false;
      reason: Exclude<AgentDraftApplyErrorReason, "missing_operation">;
      target: string;
    };

export function operationApplied(diff: ResumeDraftDiff): OperationApplyResult {
  return { ok: true, diff };
}

export function operationRejected(
  reason: Exclude<AgentDraftApplyErrorReason, "missing_operation">,
  target: string,
): OperationApplyResult {
  return { ok: false, reason, target };
}

export function sectionPath(sectionId: string) {
  return `sections.${sectionId}`;
}

export function itemPath(sectionId: string, itemId: string) {
  return `${sectionPath(sectionId)}.items.${itemId}`;
}

export function cloneResume(resume: ResumeData): ResumeData {
  if (typeof structuredClone === "function") {
    return structuredClone(resume);
  }

  return JSON.parse(JSON.stringify(resume)) as ResumeData;
}
export function isDeepEqual(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) {
    return true;
  }

  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length &&
      left.every((item, index) => isDeepEqual(item, right[index]))
    );
  }

  if (
    left &&
    right &&
    typeof left === "object" &&
    typeof right === "object"
  ) {
    const leftRecord = left as Record<string, unknown>;
    const rightRecord = right as Record<string, unknown>;
    const leftKeys = Object.keys(leftRecord).sort();
    const rightKeys = Object.keys(rightRecord).sort();

    return (
      isDeepEqual(leftKeys, rightKeys) &&
      leftKeys.every((key) => isDeepEqual(leftRecord[key], rightRecord[key]))
    );
  }

  return false;
}

export function clampInsertIndex(index: number | undefined, length: number) {
  if (!Number.isFinite(index)) {
    return length;
  }

  return Math.min(Math.max(0, Math.trunc(index ?? length)), length);
}

export function sectionLabel(section: ResumeSection) {
  return section.title.trim() || section.kind;
}

export function itemLabel(item: ResumeSectionItem) {
  if ("school" in item) return item.school.trim() || item.degree.trim() || item.id;
  if ("company" in item) return item.company.trim() || item.position.trim() || item.id;
  if ("role" in item) return item.name.trim() || item.role.trim() || item.id;
  if ("issuer" in item) return item.name.trim() || item.issuer.trim() || item.id;
  return item.content.trim() || item.id;
}

export function findSection(resume: ResumeData, sectionId: string) {
  const index = resume.sections.findIndex((section) => section.id === sectionId);

  return index >= 0
    ? { index, section: resume.sections[index] }
    : null;
}

export function findItem(section: ResumeSection, itemId: string) {
  const index = section.items.findIndex((item) => item.id === itemId);

  return index >= 0 ? { index, item: section.items[index] } : null;
}

export type ReplaceBasicField = "headline" | "summary";

export function replaceBasicField(path: unknown): ReplaceBasicField | null {
  switch (path) {
    case "basic.headline":
      return "headline";
    case "basic.summary":
      return "summary";
    default:
      return null;
  }
}

export function fallbackOperation(
  edit: AgentResumeEditSuggestion,
): ResumeEditOperation | null {
  if (edit.operation) {
    return edit.operation;
  }

  const field = replaceBasicField(edit.target);
  if (edit.replacement && field) {
    return {
      type: "replace_field",
      path: `basic.${field}`,
      value: edit.replacement,
    };
  }

  return null;
}
