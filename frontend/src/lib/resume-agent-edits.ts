import type { AgentResumeEditSuggestion } from "@/types/api";
import type {
  ResumeBasicInfo,
  ResumeData,
  ResumeDraftDiff,
  ResumeEditOperation,
  ResumeSection,
  ResumeSectionItem,
} from "@/types/resume";

export interface AgentDraftApplyResult {
  resume: ResumeData;
  diffs: ResumeDraftDiff[];
  appliedCount: number;
  errors: string[];
}

function cloneResume(resume: ResumeData): ResumeData {
  if (typeof structuredClone === "function") {
    return structuredClone(resume);
  }

  return JSON.parse(JSON.stringify(resume)) as ResumeData;
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

function fallbackOperation(
  edit: AgentResumeEditSuggestion,
): ResumeEditOperation | null {
  if (edit.operation) {
    return edit.operation;
  }

  if (edit.replacement && edit.target.startsWith("basic.")) {
    return {
      type: "replace_field",
      path: edit.target,
      value: edit.replacement,
    };
  }

  return null;
}

function applyReplaceField(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "replace_field" }>,
): ResumeDraftDiff | null {
  if (!operation.path.startsWith("basic.") || typeof operation.value !== "string") {
    return null;
  }

  const fieldName = operation.path.slice("basic.".length);
  const writableFields = new Set<keyof ResumeBasicInfo>([
    "name",
    "headline",
    "phone",
    "email",
    "location",
    "avatar",
    "summary",
  ]);

  if (!writableFields.has(fieldName as keyof ResumeBasicInfo)) {
    return null;
  }

  const field = fieldName as keyof ResumeBasicInfo;
  const before = resume.basic[field];

  if (typeof before !== "string") {
    return null;
  }

  if (before === operation.value) {
    return null;
  }

  switch (fieldName) {
    case "name":
      resume.basic.name = operation.value;
      break;
    case "headline":
      resume.basic.headline = operation.value;
      break;
    case "phone":
      resume.basic.phone = operation.value;
      break;
    case "email":
      resume.basic.email = operation.value;
      break;
    case "location":
      resume.basic.location = operation.value;
      break;
    case "avatar":
      resume.basic.avatar = operation.value;
      break;
    case "summary":
      resume.basic.summary = operation.value;
      break;
  }

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: operation.path,
    kind: "modified",
    label: edit.title,
    before,
    after: operation.value,
  };
}

function applyInsertSection(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "insert_section" }>,
): ResumeDraftDiff | null {
  if (!operation.section?.id || !Array.isArray(operation.section.items)) {
    return null;
  }

  const insertAt = clampInsertIndex(operation.index, resume.sections.length);
  resume.sections.splice(insertAt, 0, operation.section);

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: `sections.${operation.section.id}`,
    kind: "added",
    label: edit.title,
    sectionId: operation.section.id,
    after: operation.section,
  };
}

function applyUpdateSection(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "update_section" }>,
): ResumeDraftDiff | null {
  const match = findSection(resume, operation.sectionId);

  if (!match) {
    return null;
  }

  const before = { ...match.section };
  resume.sections[match.index] = {
    ...match.section,
    ...operation.patch,
    id: match.section.id,
  };

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: `sections.${operation.sectionId}`,
    kind: "modified",
    label: edit.title,
    sectionId: operation.sectionId,
    before,
    after: resume.sections[match.index],
  };
}

function applyDeleteSection(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "delete_section" }>,
): ResumeDraftDiff | null {
  const match = findSection(resume, operation.sectionId);

  if (!match) {
    return null;
  }

  const [removed] = resume.sections.splice(match.index, 1);

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: `sections.${operation.sectionId}`,
    kind: "deleted",
    label: edit.title || sectionLabel(removed),
    sectionId: operation.sectionId,
    before: removed,
  };
}

function applyReorderSections(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "reorder_sections" }>,
): ResumeDraftDiff | null {
  const beforeIds = resume.sections.map((section) => section.id);
  const byId = new Map(resume.sections.map((section) => [section.id, section]));
  const ordered = operation.sectionIds
    .map((sectionId) => byId.get(sectionId))
    .filter((section): section is ResumeSection => Boolean(section));
  const remaining = resume.sections.filter(
    (section) => !operation.sectionIds.includes(section.id),
  );
  resume.sections = [...ordered, ...remaining];
  const afterIds = resume.sections.map((section) => section.id);

  if (beforeIds.join("|") === afterIds.join("|")) {
    return null;
  }

  const movedSectionId = afterIds.find((sectionId, index) => {
    return beforeIds[index] !== sectionId;
  });

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: "sections",
    kind: "moved",
    label: edit.title,
    sectionId: movedSectionId,
    before: beforeIds,
    after: afterIds,
  };
}

function applyInsertItem(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "insert_item" }>,
): ResumeDraftDiff | null {
  const match = findSection(resume, operation.sectionId);

  if (!match || !operation.item?.id) {
    return null;
  }

  const insertAt = clampInsertIndex(operation.index, match.section.items.length);
  match.section.items.splice(insertAt, 0, operation.item);

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: `sections.${operation.sectionId}.items.${operation.item.id}`,
    kind: "added",
    label: edit.title || itemLabel(operation.item),
    sectionId: operation.sectionId,
    itemId: operation.item.id,
    after: operation.item,
  };
}

function applyUpdateItem(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "update_item" }>,
): ResumeDraftDiff | null {
  const sectionMatch = findSection(resume, operation.sectionId);

  if (!sectionMatch) {
    return null;
  }

  const itemMatch = findItem(sectionMatch.section, operation.itemId);

  if (!itemMatch) {
    return null;
  }

  const before = { ...itemMatch.item };
  sectionMatch.section.items[itemMatch.index] = {
    ...itemMatch.item,
    ...operation.patch,
    id: itemMatch.item.id,
  };

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: `sections.${operation.sectionId}.items.${operation.itemId}`,
    kind: "modified",
    label: edit.title || itemLabel(itemMatch.item),
    sectionId: operation.sectionId,
    itemId: operation.itemId,
    before,
    after: sectionMatch.section.items[itemMatch.index],
  };
}

function applyDeleteItem(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "delete_item" }>,
): ResumeDraftDiff | null {
  const sectionMatch = findSection(resume, operation.sectionId);

  if (!sectionMatch) {
    return null;
  }

  const itemMatch = findItem(sectionMatch.section, operation.itemId);

  if (!itemMatch) {
    return null;
  }

  const [removed] = sectionMatch.section.items.splice(itemMatch.index, 1);

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: `sections.${operation.sectionId}.items.${operation.itemId}`,
    kind: "deleted",
    label: edit.title || itemLabel(removed),
    sectionId: operation.sectionId,
    itemId: operation.itemId,
    before: removed,
  };
}

function applyReorderItems(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: Extract<ResumeEditOperation, { type: "reorder_items" }>,
): ResumeDraftDiff | null {
  const sectionMatch = findSection(resume, operation.sectionId);

  if (!sectionMatch) {
    return null;
  }

  const beforeIds = sectionMatch.section.items.map((item) => item.id);
  const byId = new Map(sectionMatch.section.items.map((item) => [item.id, item]));
  const ordered = operation.itemIds
    .map((itemId) => byId.get(itemId))
    .filter((item): item is ResumeSectionItem => Boolean(item));
  const remaining = sectionMatch.section.items.filter(
    (item) => !operation.itemIds.includes(item.id),
  );
  sectionMatch.section.items = [...ordered, ...remaining];
  const afterIds = sectionMatch.section.items.map((item) => item.id);

  if (beforeIds.join("|") === afterIds.join("|")) {
    return null;
  }

  const movedItemId = afterIds.find((itemId, index) => {
    return beforeIds[index] !== itemId;
  });

  return {
    id: `diff-${edit.id}`,
    operationId: edit.id,
    path: `sections.${operation.sectionId}.items`,
    kind: "moved",
    label: edit.title,
    sectionId: operation.sectionId,
    itemId: movedItemId,
    before: beforeIds,
    after: afterIds,
  };
}

function applyOperation(
  resume: ResumeData,
  edit: AgentResumeEditSuggestion,
  operation: ResumeEditOperation,
) {
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
}

export function applyAgentEditsToDraft(
  baseResume: ResumeData,
  edits: AgentResumeEditSuggestion[],
): AgentDraftApplyResult {
  const resume = cloneResume(baseResume);
  const diffs: ResumeDraftDiff[] = [];
  const errors: string[] = [];

  edits.forEach((edit) => {
    const operation = fallbackOperation(edit);

    if (!operation) {
      errors.push(edit.title || edit.id);
      return;
    }

    const diff = applyOperation(resume, edit, operation);

    if (diff) {
      diffs.push(diff);
      return;
    }

    errors.push(edit.title || edit.id);
  });

  return {
    resume,
    diffs,
    appliedCount: diffs.length,
    errors,
  };
}
