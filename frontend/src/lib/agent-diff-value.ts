import type { ResumeDraftDiff } from "@/types/resume";
import { formatRichTextAsPlainText } from "@/lib/rich-text";

const HIDDEN_DIFF_FIELDS = new Set(["id", "schemaVersion"]);
const EMPTY_DIFF_VALUE = "—";

function valuesEqual(left: unknown, right: unknown) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function canonicalPathSegments(diff: ResumeDraftDiff) {
  if (diff.path === "sections") {
    return ["sections"];
  }

  if (diff.path.startsWith("basic.")) {
    return ["basic", diff.path.slice("basic.".length)];
  }

  if (diff.sectionId) {
    const sectionPath = `sections.${diff.sectionId}`;
    const sectionSegments = ["sections", diff.sectionId];

    if (diff.itemId) {
      const itemPath = `${sectionPath}.items.${diff.itemId}`;
      const itemSegments = [...sectionSegments, "items", diff.itemId];
      if (diff.path === itemPath) {
        return itemSegments;
      }
      if (diff.path.startsWith(`${itemPath}.`)) {
        return [
          ...itemSegments,
          ...diff.path.slice(itemPath.length + 1).split("."),
        ];
      }
    } else {
      if (diff.path === sectionPath) {
        return sectionSegments;
      }
      if (diff.path.startsWith(`${sectionPath}.`)) {
        return [
          ...sectionSegments,
          ...diff.path.slice(sectionPath.length + 1).split("."),
        ];
      }
    }
  }

  return ["unresolved", diff.sectionId ?? "", diff.itemId ?? "", diff.path];
}

function canonicalPathKey(diff: ResumeDraftDiff) {
  return JSON.stringify(canonicalPathSegments(diff));
}

function isDescendantPath(path: string[], parentPath: string[]) {
  return (
    path.length > parentPath.length &&
    parentPath.every((segment, index) => path[index] === segment)
  );
}

function relativePathSegments(diff: ResumeDraftDiff, parent: ResumeDraftDiff) {
  return canonicalPathSegments(diff).slice(canonicalPathSegments(parent).length);
}

function replaceSnapshotField(
  field: string,
  current: unknown,
  replacement: unknown,
): { ok: true; value: unknown } | { ok: false } {
  if (
    field !== "items" ||
    !Array.isArray(current) ||
    !Array.isArray(replacement) ||
    !replacement.every((item) => typeof item === "string")
  ) {
    return { ok: true, value: replacement };
  }

  if (
    !current.every(
      (item) => isRecord(item) && typeof item.id === "string",
    )
  ) {
    return { ok: false };
  }

  const itemsById = new Map(current.map((item) => [item.id, item]));
  if (
    itemsById.size !== current.length ||
    replacement.length !== current.length ||
    new Set(replacement).size !== replacement.length ||
    replacement.some((itemId) => !itemsById.has(itemId))
  ) {
    return { ok: false };
  }

  return {
    ok: true,
    value: replacement.map((itemId) => itemsById.get(itemId)),
  };
}

function replaceRecordPath(
  value: unknown,
  segments: string[],
  replacement: unknown,
): { ok: true; value: unknown } | { ok: false } {
  if (segments.length === 0) {
    return { ok: false };
  }

  const [segment, ...remaining] = segments;
  if (Array.isArray(value)) {
    const index = value.findIndex(
      (item) => isRecord(item) && item.id === segment,
    );
    if (index < 0) {
      return { ok: false };
    }

    if (remaining.length === 0) {
      return {
        ok: true,
        value: value.map((item, itemIndex) =>
          itemIndex === index ? replacement : item,
        ),
      };
    }

    const nested = replaceRecordPath(value[index], remaining, replacement);
    return nested.ok
      ? {
          ok: true,
          value: value.map((item, itemIndex) =>
            itemIndex === index ? nested.value : item,
          ),
        }
      : nested;
  }

  if (!isRecord(value)) {
    return { ok: false };
  }

  if (!Object.prototype.hasOwnProperty.call(value, segment)) {
    return { ok: false };
  }

  if (remaining.length === 0) {
    const field = replaceSnapshotField(segment, value[segment], replacement);
    return field.ok
      ? { ok: true, value: { ...value, [segment]: field.value } }
      : field;
  }

  const nested = replaceRecordPath(value[segment], remaining, replacement);
  return nested.ok
    ? { ok: true, value: { ...value, [segment]: nested.value } }
    : nested;
}

/** Collapse sequential changes to the same canonical path into the net draft. */
export function compactResumeDraftDiffs(diffs: ResumeDraftDiff[]) {
  const compactedByPath = new Map<string, ResumeDraftDiff>();

  for (const diff of diffs) {
    const diffPath = canonicalPathSegments(diff);
    const diffPathKey = canonicalPathKey(diff);
    const addedAncestor = [...compactedByPath.values()]
      .filter(
        (candidate) =>
          candidate.kind === "added" &&
          isDescendantPath(diffPath, canonicalPathSegments(candidate)),
      )
      .sort(
        (left, right) =>
          canonicalPathSegments(right).length -
          canonicalPathSegments(left).length,
      )[0];
    if (addedAncestor) {
      const replaced = replaceRecordPath(
        addedAncestor.after,
        relativePathSegments(diff, addedAncestor),
        diff.after,
      );
      if (replaced.ok) {
        compactedByPath.set(canonicalPathKey(addedAncestor), {
          ...addedAncestor,
          after: replaced.value,
        });
        continue;
      }
    }

    const previous = compactedByPath.get(diffPathKey);
    let compacted = previous
      ? { ...diff, before: previous.before }
      : diff;

    if (diff.kind === "deleted" && !valuesEqual(compacted.before, compacted.after)) {
      const descendants = [...compactedByPath.values()]
        .filter((candidate) =>
          isDescendantPath(canonicalPathSegments(candidate), diffPath),
        )
        .sort(
          (left, right) =>
            relativePathSegments(right, diff).length -
            relativePathSegments(left, diff).length,
        );
      let originalSnapshot = compacted.before;
      let canCollapseDescendants = true;

      for (const descendant of descendants) {
        const replaced = replaceRecordPath(
          originalSnapshot,
          relativePathSegments(descendant, diff),
          descendant.before,
        );
        if (!replaced.ok) {
          canCollapseDescendants = false;
          break;
        }
        originalSnapshot = replaced.value;
      }

      if (canCollapseDescendants) {
        compacted = { ...compacted, before: originalSnapshot };
        for (const descendant of descendants) {
          compactedByPath.delete(canonicalPathKey(descendant));
        }
      }
    }

    if (valuesEqual(compacted.before, compacted.after)) {
      compactedByPath.delete(diffPathKey);
      for (const [pathKey, candidate] of compactedByPath) {
        if (isDescendantPath(canonicalPathSegments(candidate), diffPath)) {
          compactedByPath.delete(pathKey);
        }
      }
    } else {
      compactedByPath.set(diffPathKey, compacted);
    }
  }

  return [...compactedByPath.values()];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function indent(value: string) {
  return value
    .split("\n")
    .map((line) => `  ${line}`)
    .join("\n");
}

function formatValue(value: unknown, seen: WeakSet<object>): string {
  if (typeof value === "string") {
    const richText = formatRichTextAsPlainText(value);
    return richText === null
      ? value.trim() || EMPTY_DIFF_VALUE
      : richText.text || EMPTY_DIFF_VALUE;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return EMPTY_DIFF_VALUE;
    }
    const items = value
      .map((item) => {
        if (typeof item === "string") {
          const richText = formatRichTextAsPlainText(item);
          if (richText !== null) {
            if (!richText.text) {
              return "";
            }
            return richText.blockKind === "list"
              ? richText.text
              : `• ${richText.text.replaceAll("\n", "\n  ")}`;
          }
        }
        const formatted = formatValue(item, seen);
        return `• ${formatted.replaceAll("\n", "\n  ")}`;
      })
      .filter(Boolean);
    return items.join("\n") || EMPTY_DIFF_VALUE;
  }

  if (!isRecord(value) || seen.has(value)) {
    return EMPTY_DIFF_VALUE;
  }

  seen.add(value);
  const lines = Object.entries(value)
    .filter(([key]) => !HIDDEN_DIFF_FIELDS.has(key))
    .map(([key, fieldValue]) => {
      const formatted = formatValue(fieldValue, seen);
      if (!formatted) {
        return "";
      }
      return formatted.includes("\n")
        ? `${key}:\n${indent(formatted)}`
        : `${key}: ${formatted}`;
    })
    .filter(Boolean);
  seen.delete(value);
  return lines.join("\n") || EMPTY_DIFF_VALUE;
}

/** Format every canonical diff field without coupling the UI to item schemas. */
export function formatAgentDiffValue(value: unknown) {
  return formatValue(value, new WeakSet());
}
