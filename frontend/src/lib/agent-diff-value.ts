const HIDDEN_DIFF_FIELDS = new Set(["id", "schemaVersion"]);
const EMPTY_DIFF_VALUE = "—";

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
    return value.trim() || EMPTY_DIFF_VALUE;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return EMPTY_DIFF_VALUE;
    }
    const items = value
      .map((item) => formatValue(item, seen))
      .filter(Boolean);
    return items.map((item) => `• ${item.replaceAll("\n", "\n  ")}`).join("\n");
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

/** Resolve the diff owned by this edit identity, never by a descriptive target. */
export function getAgentEditDiff(edit: AgentResumeEditSuggestion) {
  const diff = edit.diffs?.find((candidate) => candidate.operationId === edit.id);
  if (!diff) {
    return undefined;
  }

  return {
    before: formatAgentDiffValue(diff.before),
    after: formatAgentDiffValue(diff.after),
  };
}
import type { AgentResumeEditSuggestion } from "@/types/api";
