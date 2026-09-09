import { SECTION_ITEM_FIELDS } from "@/lib/resume-sections";
import type { AgentResumeEditSuggestion } from "@/types/api";
import type { ResumeData, ResumeDraftDiff } from "@/types/resume";
import type { ResumeEditOperation } from "@/types/resume-edit-operation.generated";
import { applyOperation } from "./apply-operations";
import {
  findItem,
  findSection,
  isDeepEqual,
  itemPath,
  replaceBasicField,
  sectionPath,
} from "./transaction-core";

type MergeOperationResult =
  { ok: true; diffs: ResumeDraftDiff[] } | { ok: false; target: string };

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
    ? { ok: true, diffs: result.diffs }
    : mergeConflict(result.target);
}

function sameIds(left: string[], right: string[]) {
  return isDeepEqual(left, right);
}

export function getManualResumeChanges(
  baseResume: ResumeData,
  currentResume: ResumeData,
) {
  const changes = new Set<string>();
  for (const field of ["headline", "summary"] as const) {
    if (!isDeepEqual(baseResume.basic[field], currentResume.basic[field])) {
      changes.add(`basic.${field}`);
    }
  }
  if (
    !sameIds(
      baseResume.sections.map((section) => section.id),
      currentResume.sections.map((section) => section.id),
    )
  ) {
    changes.add("sections");
  }
  for (const section of baseResume.sections) {
    const current = findSection(currentResume, section.id)?.section;
    const target = sectionPath(section.id);
    if (!isDeepEqual(section, current)) changes.add(target);
    if (section.kind !== current?.kind) changes.add(`${target}.kind`);
    if (section.title !== current?.title) changes.add(`${target}.title`);
    if (
      !sameIds(
        section.items.map((item) => item.id),
        current?.items.map((item) => item.id) ?? [],
      )
    ) {
      changes.add(`${target}.items`);
    }
    for (const item of section.items) {
      const currentItem = current
        ? findItem(current, item.id)?.item
        : undefined;
      const target = itemPath(section.id, item.id);
      if (!isDeepEqual(item, currentItem)) changes.add(target);
      const baseRecord = item as unknown as Record<string, unknown>;
      const currentRecord = currentItem as unknown as
        Record<string, unknown> | undefined;
      for (const field of SECTION_ITEM_FIELDS[section.kind]) {
        if (!isDeepEqual(baseRecord[field], currentRecord?.[field])) {
          changes.add(`${target}.${field}`);
        }
      }
    }
  }
  return changes;
}

export function applyOperationWithMerge(
  baseResume: ResumeData,
  currentResume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: ResumeEditOperation,
  manualChanges?: ReadonlySet<string>,
): MergeOperationResult {
  switch (operation.type) {
    case "replace_field": {
      const field = replaceBasicField(operation.path);
      if (!field) {
        return mergeConflict(operation.path);
      }
      const baseValue = baseResume.basic[field];
      const currentValue = currentResume.basic[field];

      if (
        manualChanges?.has(operation.path) ||
        isDeepEqual(currentValue, operation.value)
      ) {
        return { ok: true, diffs: [] };
      }
      if (!isDeepEqual(currentValue, baseValue)) {
        return mergeConflict(operation.path);
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "insert_section": {
      const baseIds = baseResume.sections.map((section) => section.id);
      const currentIds = currentResume.sections.map((section) => section.id);

      if (
        manualChanges?.has("sections") ||
        !sameIds(baseIds, currentIds) ||
        findSection(currentResume, operation.section.id)
      ) {
        return mergeConflict(sectionPath(operation.section.id));
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "update_section": {
      const baseMatch = findSection(baseResume, operation.sectionId);
      const currentMatch = findSection(currentResume, operation.sectionId);

      if (
        !baseMatch ||
        !currentMatch ||
        manualChanges?.has(`${sectionPath(operation.sectionId)}.kind`)
      ) {
        return mergeConflict(sectionPath(operation.sectionId));
      }

      const desiredValue = operation.patch.title;
      if (
        manualChanges?.has(`${sectionPath(operation.sectionId)}.title`) ||
        isDeepEqual(currentMatch.section.title, desiredValue)
      ) {
        return { ok: true, diffs: [] };
      }
      if (!isDeepEqual(currentMatch.section.title, baseMatch.section.title)) {
        return mergeConflict(`${sectionPath(operation.sectionId)}.title`);
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "delete_section": {
      const baseMatch = findSection(baseResume, operation.sectionId);
      const currentMatch = findSection(currentResume, operation.sectionId);

      if (!baseMatch) {
        return mergeConflict(sectionPath(operation.sectionId));
      }
      if (!currentMatch) {
        return { ok: true, diffs: [] };
      }
      if (
        manualChanges?.has(sectionPath(operation.sectionId)) ||
        !isDeepEqual(currentMatch.section, baseMatch.section)
      ) {
        return mergeConflict(sectionPath(operation.sectionId));
      }
      return applyMergedOperation(currentResume, edit, operation);
    }

    case "reorder_sections": {
      const baseIds = baseResume.sections.map((section) => section.id);
      const currentIds = currentResume.sections.map((section) => section.id);

      if (sameIds(currentIds, operation.sectionIds)) {
        return { ok: true, diffs: [] };
      }
      if (manualChanges?.has("sections") || !sameIds(currentIds, baseIds)) {
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
        manualChanges?.has(`${sectionPath(operation.sectionId)}.items`) ||
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

      if (
        !baseSection ||
        !currentSection ||
        baseSection.section.kind !== currentSection.section.kind
      ) {
        return mergeConflict(target);
      }

      const allowedFields = new Set<string>(
        SECTION_ITEM_FIELDS[currentSection.section.kind],
      );
      const patchRecord = operation.patch as Record<string, unknown>;
      const pendingFields: string[] = [];
      const baseRecord = baseItem.item as unknown as Record<string, unknown>;
      const currentRecord = currentItem.item as unknown as Record<
        string,
        unknown
      >;

      for (const field of Object.keys(patchRecord)) {
        if (!allowedFields.has(field)) {
          return mergeConflict(`${target}.${field}`);
        }
        const desiredValue = patchRecord[field];
        const currentValue = currentRecord[field];
        if (
          manualChanges?.has(`${target}.${field}`) ||
          isDeepEqual(desiredValue, baseRecord[field]) ||
          isDeepEqual(currentValue, desiredValue)
        ) {
          continue;
        }
        if (!isDeepEqual(currentValue, baseRecord[field])) {
          return mergeConflict(`${target}.${field}`);
        }
        pendingFields.push(field);
      }

      if (pendingFields.length === 0) {
        return { ok: true, diffs: [] };
      }

      const pendingPatch = Object.fromEntries(
        pendingFields.map((field) => [field, patchRecord[field]]),
      ) as Extract<ResumeEditOperation, { type: "update_item" }>["patch"];
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
        return { ok: true, diffs: [] };
      }
      if (
        manualChanges?.has(target) ||
        !isDeepEqual(currentItem.item, baseItem.item)
      ) {
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
        return { ok: true, diffs: [] };
      }
      if (manualChanges?.has(target) || !sameIds(currentIds, baseIds)) {
        return mergeConflict(target);
      }
      return applyMergedOperation(currentResume, edit, operation);
    }
  }
}
