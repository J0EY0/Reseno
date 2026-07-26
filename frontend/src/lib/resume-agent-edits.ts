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

type OperationApplyResult =
  | { ok: true; diff: ResumeDraftDiff }
  | {
      ok: false;
      reason: Exclude<AgentDraftApplyErrorReason, "missing_operation">;
      target: string;
    };

function operationApplied(diff: ResumeDraftDiff): OperationApplyResult {
  return { ok: true, diff };
}

function operationRejected(
  reason: Exclude<AgentDraftApplyErrorReason, "missing_operation">,
  target: string,
): OperationApplyResult {
  return { ok: false, reason, target };
}

function sectionPath(sectionId: string) {
  return `sections.${sectionId}`;
}

function itemPath(sectionId: string, itemId: string) {
  return `${sectionPath(sectionId)}.items.${itemId}`;
}

function cloneResume(resume: ResumeData): ResumeData {
  if (typeof structuredClone === "function") {
    return structuredClone(resume);
  }

  return JSON.parse(JSON.stringify(resume)) as ResumeData;
}

/**
 * Captures the immutable merge base used when an Agent draft is generated.
 * The editor may keep changing before the user applies the draft, so retaining
 * a reference to live state would make a later three-way merge unreliable.
 */
export function createAgentDraftBaseSnapshot(
  baseResume: ResumeData,
): ResumeData {
  return cloneResume(baseResume);
}

function isDeepEqual(left: unknown, right: unknown): boolean {
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

function clampInsertIndex(index: number | undefined, length: number) {
  if (!Number.isFinite(index)) {
    return length;
  }

  return Math.min(Math.max(0, Math.trunc(index ?? length)), length);
}

function sectionLabel(section: ResumeSection) {
  return section.customTitle.trim() || section.kind;
}

function itemLabel(item: ResumeSectionItem) {
  return item.title.trim() || item.subtitle.trim() || item.id;
}

function findSection(resume: ResumeData, sectionId: string) {
  const index = resume.sections.findIndex((section) => section.id === sectionId);

  return index >= 0
    ? { index, section: resume.sections[index] }
    : null;
}

function findItem(section: ResumeSection, itemId: string) {
  const index = section.items.findIndex((item) => item.id === itemId);

  return index >= 0 ? { index, item: section.items[index] } : null;
}

type ReplaceBasicField = "headline" | "location" | "summary";

function replaceBasicField(path: unknown): ReplaceBasicField | null {
  switch (path) {
    case "basic.headline":
      return "headline";
    case "basic.location":
      return "location";
    case "basic.summary":
      return "summary";
    default:
      return null;
  }
}

function fallbackOperation(
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

function applyReplaceField(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "replace_field" }>,
): OperationApplyResult {
  const field = replaceBasicField(operation.path);
  if (
    !field ||
    typeof operation.value !== "string"
  ) {
    return operationRejected(
      "invalid_operation",
      typeof operation.path === "string" ? operation.path : edit.target,
    );
  }

  const before = resume.basic[field];

  if (before === operation.value) {
    return operationRejected("no_change", operation.path);
  }

  resume.basic[field] = operation.value;

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: operation.path,
    kind: "modified",
    label: edit.title,
    before,
    after: operation.value,
  });
}

function applyInsertSection(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "insert_section" }>,
): OperationApplyResult {
  if (!operation.section?.id || !Array.isArray(operation.section.items)) {
    return operationRejected("invalid_operation", edit.target);
  }

  if (findSection(resume, operation.section.id)) {
    return operationRejected(
      "duplicate_target",
      sectionPath(operation.section.id),
    );
  }

  const insertAt = clampInsertIndex(operation.index, resume.sections.length);
  resume.sections.splice(insertAt, 0, operation.section);

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: sectionPath(operation.section.id),
    kind: "added",
    label: edit.title,
    sectionId: operation.section.id,
    after: operation.section,
  });
}

function applyUpdateSection(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "update_section" }>,
): OperationApplyResult {
  const match = findSection(resume, operation.sectionId);

  if (!match) {
    return operationRejected(
      "target_not_found",
      sectionPath(operation.sectionId),
    );
  }

  const writableFields = ["kind", "layout", "customTitle"] as const;
  const patchFields = writableFields.filter(
    (field) => operation.patch && field in operation.patch,
  );

  if (patchFields.length === 0) {
    return operationRejected(
      "invalid_operation",
      sectionPath(operation.sectionId),
    );
  }

  if (
    patchFields.every((field) =>
      isDeepEqual(match.section[field], operation.patch[field]),
    )
  ) {
    return operationRejected("no_change", sectionPath(operation.sectionId));
  }

  const before = { ...match.section };
  resume.sections[match.index] = {
    ...match.section,
    ...operation.patch,
    id: match.section.id,
  };

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: sectionPath(operation.sectionId),
    kind: "modified",
    label: edit.title,
    sectionId: operation.sectionId,
    before,
    after: resume.sections[match.index],
  });
}

function applyDeleteSection(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "delete_section" }>,
): OperationApplyResult {
  const match = findSection(resume, operation.sectionId);

  if (!match) {
    return operationRejected(
      "target_not_found",
      sectionPath(operation.sectionId),
    );
  }

  const [removed] = resume.sections.splice(match.index, 1);

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: sectionPath(operation.sectionId),
    kind: "deleted",
    label: edit.title || sectionLabel(removed),
    sectionId: operation.sectionId,
    before: removed,
  });
}

function applyReorderSections(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "reorder_sections" }>,
): OperationApplyResult {
  const beforeIds = resume.sections.map((section) => section.id);
  const byId = new Map(resume.sections.map((section) => [section.id, section]));

  if (!Array.isArray(operation.sectionIds) || operation.sectionIds.length === 0) {
    return operationRejected("invalid_operation", "sections");
  }

  if (new Set(operation.sectionIds).size !== operation.sectionIds.length) {
    return operationRejected("duplicate_target", "sections");
  }

  const missingSectionIds = operation.sectionIds.filter(
    (sectionId) => !byId.has(sectionId),
  );

  if (missingSectionIds.length > 0) {
    return operationRejected(
      "target_not_found",
      missingSectionIds.map(sectionPath).join(", "),
    );
  }

  if (operation.sectionIds.length !== beforeIds.length) {
    return operationRejected("invalid_operation", "sections");
  }

  const ordered = operation.sectionIds
    .map((sectionId) => byId.get(sectionId))
    .filter((section): section is ResumeSection => Boolean(section));
  resume.sections = ordered;
  const afterIds = resume.sections.map((section) => section.id);

  if (beforeIds.join("|") === afterIds.join("|")) {
    return operationRejected("no_change", "sections");
  }

  const movedSectionId = afterIds.find((sectionId, index) => {
    return beforeIds[index] !== sectionId;
  });

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: "sections",
    kind: "moved",
    label: edit.title,
    sectionId: movedSectionId,
    before: beforeIds,
    after: afterIds,
  });
}

function applyInsertItem(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "insert_item" }>,
): OperationApplyResult {
  const match = findSection(resume, operation.sectionId);

  if (!match) {
    return operationRejected(
      "target_not_found",
      sectionPath(operation.sectionId),
    );
  }

  if (!operation.item?.id) {
    return operationRejected("invalid_operation", edit.target);
  }

  if (findItem(match.section, operation.item.id)) {
    return operationRejected(
      "duplicate_target",
      itemPath(operation.sectionId, operation.item.id),
    );
  }

  const insertAt = clampInsertIndex(operation.index, match.section.items.length);
  match.section.items.splice(insertAt, 0, operation.item);

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: itemPath(operation.sectionId, operation.item.id),
    kind: "added",
    label: edit.title || itemLabel(operation.item),
    sectionId: operation.sectionId,
    itemId: operation.item.id,
    after: operation.item,
  });
}

function applyUpdateItem(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "update_item" }>,
): OperationApplyResult {
  const sectionMatch = findSection(resume, operation.sectionId);

  if (!sectionMatch) {
    return operationRejected(
      "target_not_found",
      sectionPath(operation.sectionId),
    );
  }

  const itemMatch = findItem(sectionMatch.section, operation.itemId);

  if (!itemMatch) {
    return operationRejected(
      "target_not_found",
      itemPath(operation.sectionId, operation.itemId),
    );
  }

  const writableFields = [
    "title",
    "subtitle",
    "meta",
    "period",
    "description",
    "highlights",
  ] as const;
  const patchFields = writableFields.filter(
    (field) => operation.patch && field in operation.patch,
  );

  if (patchFields.length === 0) {
    return operationRejected(
      "invalid_operation",
      itemPath(operation.sectionId, operation.itemId),
    );
  }

  if (
    patchFields.every((field) =>
      isDeepEqual(itemMatch.item[field], operation.patch[field]),
    )
  ) {
    return operationRejected(
      "no_change",
      itemPath(operation.sectionId, operation.itemId),
    );
  }

  const before = { ...itemMatch.item };
  sectionMatch.section.items[itemMatch.index] = {
    ...itemMatch.item,
    ...operation.patch,
    id: itemMatch.item.id,
  };

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: itemPath(operation.sectionId, operation.itemId),
    kind: "modified",
    label: edit.title || itemLabel(itemMatch.item),
    sectionId: operation.sectionId,
    itemId: operation.itemId,
    before,
    after: sectionMatch.section.items[itemMatch.index],
  });
}

function applyDeleteItem(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "delete_item" }>,
): OperationApplyResult {
  const sectionMatch = findSection(resume, operation.sectionId);

  if (!sectionMatch) {
    return operationRejected(
      "target_not_found",
      sectionPath(operation.sectionId),
    );
  }

  const itemMatch = findItem(sectionMatch.section, operation.itemId);

  if (!itemMatch) {
    return operationRejected(
      "target_not_found",
      itemPath(operation.sectionId, operation.itemId),
    );
  }

  const [removed] = sectionMatch.section.items.splice(itemMatch.index, 1);

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: itemPath(operation.sectionId, operation.itemId),
    kind: "deleted",
    label: edit.title || itemLabel(removed),
    sectionId: operation.sectionId,
    itemId: operation.itemId,
    before: removed,
  });
}

function applyReorderItems(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "reorder_items" }>,
): OperationApplyResult {
  const sectionMatch = findSection(resume, operation.sectionId);

  if (!sectionMatch) {
    return operationRejected(
      "target_not_found",
      sectionPath(operation.sectionId),
    );
  }

  const beforeIds = sectionMatch.section.items.map((item) => item.id);
  const byId = new Map(sectionMatch.section.items.map((item) => [item.id, item]));

  if (!Array.isArray(operation.itemIds) || operation.itemIds.length === 0) {
    return operationRejected(
      "invalid_operation",
      `${sectionPath(operation.sectionId)}.items`,
    );
  }

  if (new Set(operation.itemIds).size !== operation.itemIds.length) {
    return operationRejected(
      "duplicate_target",
      `${sectionPath(operation.sectionId)}.items`,
    );
  }

  const missingItemIds = operation.itemIds.filter((itemId) => !byId.has(itemId));

  if (missingItemIds.length > 0) {
    return operationRejected(
      "target_not_found",
      missingItemIds
        .map((itemId) => itemPath(operation.sectionId, itemId))
        .join(", "),
    );
  }

  if (operation.itemIds.length !== beforeIds.length) {
    return operationRejected(
      "invalid_operation",
      `${sectionPath(operation.sectionId)}.items`,
    );
  }

  const ordered = operation.itemIds
    .map((itemId) => byId.get(itemId))
    .filter((item): item is ResumeSectionItem => Boolean(item));
  sectionMatch.section.items = ordered;
  const afterIds = sectionMatch.section.items.map((item) => item.id);

  if (beforeIds.join("|") === afterIds.join("|")) {
    return operationRejected(
      "no_change",
      `${sectionPath(operation.sectionId)}.items`,
    );
  }

  const movedItemId = afterIds.find((itemId, index) => {
    return beforeIds[index] !== itemId;
  });

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: `sections.${operation.sectionId}.items`,
    kind: "moved",
    label: edit.title,
    sectionId: operation.sectionId,
    itemId: movedItemId,
    before: beforeIds,
    after: afterIds,
  });
}

function applyOperation(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: ResumeEditOperation,
): OperationApplyResult {
  switch (operation.type) {
    case "replace_field":
      return applyReplaceField(resume, edit, operation);
    case "insert_section":
      return applyInsertSection(resume, edit, operation);
    case "update_section":
      return applyUpdateSection(resume, edit, operation);
    case "delete_section":
      return applyDeleteSection(resume, edit, operation);
    case "reorder_sections":
      return applyReorderSections(resume, edit, operation);
    case "insert_item":
      return applyInsertItem(resume, edit, operation);
    case "update_item":
      return applyUpdateItem(resume, edit, operation);
    case "delete_item":
      return applyDeleteItem(resume, edit, operation);
    case "reorder_items":
      return applyReorderItems(resume, edit, operation);
  }

  // API payloads are runtime data and may contain an operation type newer than
  // this client understands. Reject it inside the transaction instead of
  // throwing or publishing edits that happened earlier in the same batch.
  return operationRejected("invalid_operation", edit.target || edit.id);
}

export function applyAgentEditsToDraft(
  baseResume: ResumeData,
  edits: AgentResumeEditSuggestion[],
): AgentDraftApplyResult {
  const workingResume = cloneResume(baseResume);
  const diffs: ResumeDraftDiff[] = [];
  const errors: AgentDraftApplyError[] = [];

  edits.forEach((edit) => {
    const operation = fallbackOperation(edit);

    if (!operation) {
      errors.push({
        editId: edit.id,
        title: edit.title || edit.id,
        target: edit.target || edit.id,
        reason: "missing_operation",
      });
      return;
    }

    const result = applyOperation(workingResume, edit, operation);

    if (result.ok) {
      diffs.push(result.diff);
      return;
    }

    errors.push({
      editId: edit.id,
      title: edit.title || edit.id,
      operationType: operation.type,
      target: result.target || edit.target || edit.id,
      reason: result.reason,
    });
  });

  // The working copy is the transaction buffer. It is published only after every
  // operation succeeds, so callers can never preview or apply a partial batch.
  if (errors.length > 0) {
    return {
      resume: cloneResume(baseResume),
      diffs: [],
      appliedCount: 0,
      errors,
    };
  }

  return {
    resume: workingResume,
    diffs,
    appliedCount: diffs.length,
    errors,
  };
}

type MergeOperationResult =
  | { ok: true; diff?: ResumeDraftDiff }
  | { ok: false; target: string };

function mergeConflict(target: string): MergeOperationResult {
  return { ok: false, target };
}

function applyMergedOperation(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: ResumeEditOperation,
): MergeOperationResult {
  const result = applyOperation(resume, edit, operation);

  return result.ok
    ? { ok: true, diff: result.diff }
    : mergeConflict(result.target);
}

function sameIds(left: string[], right: string[]) {
  return isDeepEqual(left, right);
}

function applyOperationWithMerge(
  baseResume: ResumeData,
  currentResume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: ResumeEditOperation,
): MergeOperationResult {
  switch (operation.type) {
    case "replace_field": {
      const field = replaceBasicField(operation.path);
      if (!field) {
        return mergeConflict(operation.path);
      }
      const baseValue = baseResume.basic[field];
      const currentValue = currentResume.basic[field];

      if (isDeepEqual(currentValue, operation.value)) {
        return { ok: true };
      }
      if (!isDeepEqual(currentValue, baseValue)) {
        return mergeConflict(operation.path);
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "insert_section": {
      const baseIds = baseResume.sections.map((section) => section.id);
      const currentIds = currentResume.sections.map((section) => section.id);

      if (!sameIds(baseIds, currentIds) || findSection(currentResume, operation.section.id)) {
        return mergeConflict(sectionPath(operation.section.id));
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "update_section": {
      const baseMatch = findSection(baseResume, operation.sectionId);
      const currentMatch = findSection(currentResume, operation.sectionId);

      if (!baseMatch || !currentMatch) {
        return mergeConflict(sectionPath(operation.sectionId));
      }

      const writableFields = ["kind", "layout", "customTitle"] as const;
      const pendingFields: Array<(typeof writableFields)[number]> = [];

      for (const field of writableFields) {
        if (!(field in operation.patch)) {
          continue;
        }

        const desiredValue = operation.patch[field];
        const currentValue = currentMatch.section[field];
        if (isDeepEqual(currentValue, desiredValue)) {
          continue;
        }
        if (!isDeepEqual(currentValue, baseMatch.section[field])) {
          return mergeConflict(`${sectionPath(operation.sectionId)}.${field}`);
        }
        pendingFields.push(field);
      }

      if (pendingFields.length === 0) {
        return { ok: true };
      }

      const pendingPatch = Object.fromEntries(
        pendingFields.map((field) => [field, operation.patch[field]]),
      ) as Extract<
        ResumeEditOperation,
        { type: "update_section" }
      >["patch"];
      return applyMergedOperation(currentResume, edit, {
        ...operation,
        patch: pendingPatch,
      });
    }

    case "delete_section": {
      const baseMatch = findSection(baseResume, operation.sectionId);
      const currentMatch = findSection(currentResume, operation.sectionId);

      if (!baseMatch) {
        return mergeConflict(sectionPath(operation.sectionId));
      }
      if (!currentMatch) {
        return { ok: true };
      }
      if (!isDeepEqual(currentMatch.section, baseMatch.section)) {
        return mergeConflict(sectionPath(operation.sectionId));
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "reorder_sections": {
      const baseIds = baseResume.sections.map((section) => section.id);
      const currentIds = currentResume.sections.map((section) => section.id);

      if (sameIds(currentIds, operation.sectionIds)) {
        return { ok: true };
      }
      if (!sameIds(currentIds, baseIds)) {
        return mergeConflict("sections");
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "insert_item": {
      const baseSection = findSection(baseResume, operation.sectionId);
      const currentSection = findSection(currentResume, operation.sectionId);

      if (!baseSection || !currentSection) {
        return mergeConflict(sectionPath(operation.sectionId));
      }

      const baseIds = baseSection.section.items.map((item) => item.id);
      const currentIds = currentSection.section.items.map((item) => item.id);
      if (
        !sameIds(baseIds, currentIds) ||
        findItem(currentSection.section, operation.item.id)
      ) {
        return mergeConflict(itemPath(operation.sectionId, operation.item.id));
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "update_item": {
      const baseSection = findSection(baseResume, operation.sectionId);
      const currentSection = findSection(currentResume, operation.sectionId);
      const baseItem = baseSection
        ? findItem(baseSection.section, operation.itemId)
        : null;
      const currentItem = currentSection
        ? findItem(currentSection.section, operation.itemId)
        : null;
      const target = itemPath(operation.sectionId, operation.itemId);

      if (!baseItem || !currentItem) {
        return mergeConflict(target);
      }

      const writableFields = [
        "title",
        "subtitle",
        "meta",
        "period",
        "description",
        "highlights",
      ] as const;
      const pendingFields: Array<(typeof writableFields)[number]> = [];

      for (const field of writableFields) {
        if (!(field in operation.patch)) {
          continue;
        }

        const desiredValue = operation.patch[field];
        const currentValue = currentItem.item[field];
        if (isDeepEqual(currentValue, desiredValue)) {
          continue;
        }
        if (!isDeepEqual(currentValue, baseItem.item[field])) {
          return mergeConflict(`${target}.${field}`);
        }
        pendingFields.push(field);
      }

      if (pendingFields.length === 0) {
        return { ok: true };
      }

      const pendingPatch = Object.fromEntries(
        pendingFields.map((field) => [field, operation.patch[field]]),
      ) as Partial<ResumeSectionItem>;
      return applyMergedOperation(currentResume, edit, {
        ...operation,
        patch: pendingPatch,
      });
    }

    case "delete_item": {
      const baseSection = findSection(baseResume, operation.sectionId);
      const currentSection = findSection(currentResume, operation.sectionId);
      const baseItem = baseSection
        ? findItem(baseSection.section, operation.itemId)
        : null;
      const currentItem = currentSection
        ? findItem(currentSection.section, operation.itemId)
        : null;
      const target = itemPath(operation.sectionId, operation.itemId);

      if (!baseItem) {
        return mergeConflict(target);
      }
      if (!currentItem) {
        return { ok: true };
      }
      if (!isDeepEqual(currentItem.item, baseItem.item)) {
        return mergeConflict(target);
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "reorder_items": {
      const baseSection = findSection(baseResume, operation.sectionId);
      const currentSection = findSection(currentResume, operation.sectionId);
      const target = `${sectionPath(operation.sectionId)}.items`;

      if (!baseSection || !currentSection) {
        return mergeConflict(target);
      }

      const baseIds = baseSection.section.items.map((item) => item.id);
      const currentIds = currentSection.section.items.map((item) => item.id);
      if (sameIds(currentIds, operation.itemIds)) {
        return { ok: true };
      }
      if (!sameIds(currentIds, baseIds)) {
        return mergeConflict(target);
      }
      return applyMergedOperation(currentResume, edit, operation);
    }
  }
}

/**
 * Applies an Agent batch against the resume the user is editing now.
 *
 * The Agent's base snapshot is advanced operation-by-operation beside the
 * current resume. Field edits merge when the user changed a different field;
 * competing field or structural edits reject the complete candidate.
 */
export function applyAgentEditsWithMerge(
  baseResume: ResumeData,
  currentResume: ResumeData,
  edits: AgentResumeEditSuggestion[],
): AgentDraftApplyResult {
  const validation = applyAgentEditsToDraft(baseResume, edits);
  if (validation.errors.length > 0) {
    return { ...validation, resume: cloneResume(currentResume) };
  }

  const baseWorking = cloneResume(baseResume);
  const currentWorking = cloneResume(currentResume);
  const diffs: ResumeDraftDiff[] = [];

  for (const edit of edits) {
    const operation = fallbackOperation(edit);
    if (!operation) {
      // The validation pass above guarantees this cannot happen.
      continue;
    }

    const merged = applyOperationWithMerge(
      baseWorking,
      currentWorking,
      edit,
      operation,
    );

    if (!merged.ok) {
      return {
        resume: cloneResume(currentResume),
        diffs: [],
        appliedCount: 0,
        errors: [{
          editId: edit.id,
          title: edit.title || edit.id,
          operationType: operation.type,
          target: merged.target,
          reason: "conflict",
        }],
      };
    }

    if (merged.diff) {
      diffs.push(merged.diff);
    }

    const baseResult = applyOperation(baseWorking, edit, operation);
    if (!baseResult.ok) {
      return {
        resume: cloneResume(currentResume),
        diffs: [],
        appliedCount: 0,
        errors: [{
          editId: edit.id,
          title: edit.title || edit.id,
          operationType: operation.type,
          target: baseResult.target,
          reason: baseResult.reason,
        }],
      };
    }
  }

  return {
    resume: currentWorking,
    diffs,
    appliedCount: diffs.length,
    errors: [],
  };
}
