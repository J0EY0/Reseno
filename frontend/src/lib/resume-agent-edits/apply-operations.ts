import type { AgentResumeEditSuggestion } from "@/types/api";
import type { ResumeEditOperation } from "@/types/resume-edit-operation.generated";
import {
  isCanonicalResumeSection,
  isSectionItemForKind,
  SECTION_ITEM_FIELDS,
} from "@/lib/resume-sections";
import type { ResumeData, ResumeSection } from "@/types/resume";
import {
  clampInsertIndex,
  findItem,
  findSection,
  isDeepEqual,
  itemLabel,
  itemPath,
  operationApplied,
  operationRejected,
  replaceBasicField,
  sectionLabel,
  sectionPath,
  type OperationApplyResult,
} from "./transaction-core";

/** Return IDs outside one deterministic longest stable subsequence. */
function movedIds(beforeIds: string[], afterIds: string[]) {
  const positions = new Map(beforeIds.map((id, index) => [id, index]));
  const sequences: string[][] = [];
  for (const id of afterIds) {
    const stable = sequences
      .filter((_, index) =>
        positions.get(afterIds[index]!)! < positions.get(id)!)
      .reduce<string[]>((longest, sequence) =>
        sequence.length > longest.length ? sequence : longest, []);
    sequences.push([...stable, id]);
  }
  const stableIds = new Set(sequences.reduce<string[]>((longest, sequence) =>
    sequence.length > longest.length ? sequence : longest, []));
  return new Set(afterIds.filter((id) => !stableIds.has(id)));
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
  const sectionId = operation.section?.id;
  if (!sectionId || !Array.isArray(operation.section.items)) {
    return operationRejected("invalid_operation", edit.target);
  }

  if (!isCanonicalResumeSection(operation.section)) {
    return operationRejected(
      "invalid_operation",
      sectionPath(sectionId),
    );
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

  if (!operation.patch || typeof operation.patch.title !== "string") {
    return operationRejected(
      "invalid_operation",
      sectionPath(operation.sectionId),
    );
  }

  if (match.section.title === operation.patch.title) {
    return operationRejected("no_change", sectionPath(operation.sectionId));
  }

  const before = { ...match.section };
  const nextSection = {
    ...match.section,
    title: operation.patch.title,
    id: match.section.id,
  } as ResumeSection;

  if (!isCanonicalResumeSection(nextSection)) {
    return operationRejected(
      "invalid_operation",
      sectionPath(operation.sectionId),
    );
  }

  resume.sections[match.index] = nextSection;

  return operationApplied({
    id: `diff-${edit.id}-title`,
    operationId: edit.id,
    path: `${sectionPath(operation.sectionId)}.title`,
    kind: "modified",
    label: edit.title,
    sectionId: operation.sectionId,
    before: before.title,
    after: nextSection.title,
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

  const beforePreviousId = resume.sections[match.index - 1]?.id;
  const beforeNextId = resume.sections[match.index + 1]?.id;
  const [removed] = resume.sections.splice(match.index, 1);

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: sectionPath(operation.sectionId),
    kind: "deleted",
    label: edit.title || sectionLabel(removed),
    sectionId: operation.sectionId,
    ...(beforePreviousId ? { beforePreviousId } : {}),
    ...(beforeNextId ? { beforeNextId } : {}),
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

  const movedSectionIds = movedIds(beforeIds, afterIds);
  return operationApplied(
    ...afterIds.flatMap((sectionId, afterIndex) => {
      return !movedSectionIds.has(sectionId)
        ? []
        : [{
            id: `diff-${edit.id}-${sectionId}`,
            operationId: edit.id,
            path: sectionPath(sectionId),
            kind: "moved" as const,
            label: edit.title,
            sectionId,
            before: beforeIds.indexOf(sectionId),
            after: afterIndex,
          }];
    }),
  );
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

  if (match.section.kind === "simple_list") {
    return operationRejected(
      "invalid_operation",
      `${sectionPath(operation.sectionId)}.items`,
    );
  }

  const itemId = operation.item?.id;
  if (!itemId) {
    return operationRejected("invalid_operation", edit.target);
  }

  if (!isSectionItemForKind(match.section.kind, operation.item)) {
    return operationRejected(
      "invalid_operation",
      itemPath(operation.sectionId, itemId),
    );
  }

  if (findItem(match.section, operation.item.id)) {
    return operationRejected(
      "duplicate_target",
      itemPath(operation.sectionId, operation.item.id),
    );
  }

  const insertAt = clampInsertIndex(operation.index, match.section.items.length);
  const nextItems = [...match.section.items];
  nextItems.splice(insertAt, 0, operation.item);
  resume.sections[match.index] = {
    ...match.section,
    items: nextItems,
  } as ResumeSection;

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

  const allowedFields = new Set<string>(
    SECTION_ITEM_FIELDS[sectionMatch.section.kind],
  );
  const patchFields = operation.patch && typeof operation.patch === "object"
    ? Object.keys(operation.patch)
    : [];

  if (
    patchFields.length === 0 ||
    patchFields.some((field) => !allowedFields.has(field))
  ) {
    return operationRejected(
      "invalid_operation",
      itemPath(operation.sectionId, operation.itemId),
    );
  }

  const currentItem = itemMatch.item as unknown as Record<string, unknown>;
  const patch = operation.patch as Record<string, unknown>;

  if (patchFields.every((field) => isDeepEqual(currentItem[field], patch[field]))) {
    return operationRejected(
      "no_change",
      itemPath(operation.sectionId, operation.itemId),
    );
  }

  const changedFields = SECTION_ITEM_FIELDS[sectionMatch.section.kind].filter(
    (field) =>
      patchFields.includes(field) &&
      !isDeepEqual(currentItem[field], patch[field]),
  );
  const nextItem = {
    ...itemMatch.item,
    ...operation.patch,
    id: itemMatch.item.id,
  };

  if (!isSectionItemForKind(sectionMatch.section.kind, nextItem)) {
    return operationRejected(
      "invalid_operation",
      itemPath(operation.sectionId, operation.itemId),
    );
  }

  const nextItems = sectionMatch.section.items.map((item) =>
    item.id === operation.itemId ? nextItem : item,
  );
  resume.sections[sectionMatch.index] = {
    ...sectionMatch.section,
    items: nextItems,
  } as ResumeSection;

  const target = itemPath(operation.sectionId, operation.itemId);
  return operationApplied(
    ...changedFields.map((field) => ({
      id: `diff-${edit.id}-${field}`,
      operationId: edit.id,
      path: `${target}.${field}`,
      kind: "modified" as const,
      label: edit.title || itemLabel(itemMatch.item),
      sectionId: operation.sectionId,
      itemId: operation.itemId,
      before: currentItem[field],
      after: patch[field],
    })),
  );
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

  if (sectionMatch.section.kind === "simple_list") {
    return operationRejected(
      "invalid_operation",
      `${sectionPath(operation.sectionId)}.items`,
    );
  }

  const itemMatch = findItem(sectionMatch.section, operation.itemId);

  if (!itemMatch) {
    return operationRejected(
      "target_not_found",
      itemPath(operation.sectionId, operation.itemId),
    );
  }

  const removed = itemMatch.item;
  const beforePreviousId = sectionMatch.section.items[itemMatch.index - 1]?.id;
  const beforeNextId = sectionMatch.section.items[itemMatch.index + 1]?.id;
  resume.sections[sectionMatch.index] = {
    ...sectionMatch.section,
    items: sectionMatch.section.items.filter(
      (item) => item.id !== operation.itemId,
    ),
  } as ResumeSection;

  return operationApplied({
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: itemPath(operation.sectionId, operation.itemId),
    kind: "deleted",
    label: edit.title || itemLabel(removed),
    sectionId: operation.sectionId,
    itemId: operation.itemId,
    ...(beforePreviousId ? { beforePreviousId } : {}),
    ...(beforeNextId ? { beforeNextId } : {}),
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

  if (sectionMatch.section.kind === "simple_list") {
    return operationRejected(
      "invalid_operation",
      `${sectionPath(operation.sectionId)}.items`,
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

  const ordered = operation.itemIds.map((itemId) => byId.get(itemId)!);
  resume.sections[sectionMatch.index] = {
    ...sectionMatch.section,
    items: ordered,
  } as ResumeSection;
  const afterIds = ordered.map((item) => item.id);

  if (beforeIds.join("|") === afterIds.join("|")) {
    return operationRejected(
      "no_change",
      `${sectionPath(operation.sectionId)}.items`,
    );
  }

  const movedItemIds = movedIds(beforeIds, afterIds);
  return operationApplied(
    ...afterIds.flatMap((itemId, afterIndex) => {
      return !movedItemIds.has(itemId)
        ? []
        : [{
            id: `diff-${edit.id}-${itemId}`,
            operationId: edit.id,
            path: itemPath(operation.sectionId, itemId),
            kind: "moved" as const,
            label: edit.title,
            sectionId: operation.sectionId,
            itemId,
            before: beforeIds.indexOf(itemId),
            after: afterIndex,
          }];
    }),
  );
}

export function applyOperation(
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
