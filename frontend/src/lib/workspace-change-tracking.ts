import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

// Server timestamps and user preferences are not editor content; ignoring them
// prevents background persistence from marking the active document as dirty.
const volatileWorkspaceFields = new Set([
  "agentSettings",
  "savedAt",
  "theme",
  "updatedAt",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isStableEntry([key, value]: [string, unknown]) {
  return !volatileWorkspaceFields.has(key) && typeof value !== "undefined";
}

function countStableValueChanges(before: unknown, after: unknown): number {
  if (Object.is(before, after)) {
    return 0;
  }

  if (Array.isArray(before) && Array.isArray(after)) {
    const sharedLength = Math.min(before.length, after.length);
    let changeCount = Math.abs(before.length - after.length);

    for (let index = 0; index < sharedLength; index += 1) {
      changeCount += countStableValueChanges(before[index], after[index]);
    }

    return changeCount;
  }

  if (isRecord(before) && isRecord(after)) {
    const beforeEntries = Object.entries(before).filter(isStableEntry);
    const afterEntries = Object.entries(after).filter(isStableEntry);
    const beforeByKey = new Map(beforeEntries);
    const afterByKey = new Map(afterEntries);
    const keys = new Set([...beforeByKey.keys(), ...afterByKey.keys()]);
    let changeCount = 0;

    keys.forEach((key) => {
      if (!beforeByKey.has(key) || !afterByKey.has(key)) {
        changeCount += 1;
        return;
      }

      changeCount += countStableValueChanges(
        beforeByKey.get(key),
        afterByKey.get(key),
      );
    });

    return changeCount;
  }

  return 1;
}

function createStableFingerprint(value: unknown) {
  return JSON.stringify(value, (key, entryValue) =>
    volatileWorkspaceFields.has(key) ? undefined : entryValue,
  );
}

export function createResumeFingerprint(item: ResumeWorkspaceItem | null) {
  return item ? createStableFingerprint(item) : "";
}

export function createTemplateFingerprint(
  item: ResumeTemplateDefinition | null,
) {
  return item ? createStableFingerprint(item) : "";
}

export function countResumeChanges(
  before: ResumeWorkspaceItem | null,
  after: ResumeWorkspaceItem | null,
) {
  return countStableValueChanges(before, after);
}

export function countTemplateChanges(
  before: ResumeTemplateDefinition | null,
  after: ResumeTemplateDefinition | null,
) {
  return countStableValueChanges(before, after);
}
