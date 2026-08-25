import type { AgentResumeEditSuggestion } from "@/types/api";

const MARKDOWN_BLOCK_PATTERN =
  /(^|\n)\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>|```)/;
const MARKDOWN_INLINE_PATTERN =
  /`|[[\]]|(\*\*|__)[^\n]+?\1|(?:^|[\s\u3000])([*_])[^*_\n]+?\2/;

export function isPlainAgentText(text: string) {
  return !MARKDOWN_BLOCK_PATTERN.test(text) && !MARKDOWN_INLINE_PATTERN.test(text);
}

function addFieldLabel(
  labelsByToken: Map<string, Set<string>>,
  token: string,
  label: string,
) {
  const labels = labelsByToken.get(token) ?? new Set<string>();
  labels.add(label);
  labelsByToken.set(token, labels);
}

/**
 * Projects schema tokens used in an edit summary onto the localized labels
 * already carried by its structured diffs. The stored assistant text remains
 * untouched and unrelated inline code is not part of this map.
 */
export function getAgentDisplayFieldLabels(
  edits: AgentResumeEditSuggestion[] | undefined,
  fallbackLabels: Readonly<Record<string, string>>,
) {
  const labelsByToken = new Map<string, Set<string>>();

  for (const edit of edits ?? []) {
    for (const diff of edit.diffs ?? []) {
      const path = diff.path.trim();
      const label = diff.label.trim();

      if (!path || !label) {
        continue;
      }

      addFieldLabel(labelsByToken, path, label);
      addFieldLabel(labelsByToken, path.split(".").at(-1) ?? path, label);
    }
  }

  const displayLabels = new Map<string, string>();

  for (const [token, labels] of labelsByToken) {
    const uniqueLabel = labels.size === 1
      ? labels.values().next().value
      : undefined;
    if (uniqueLabel) {
      displayLabels.set(token, uniqueLabel);
      continue;
    }

    const field = token.split(".").at(-1) ?? token;
    const fallback = fallbackLabels[field];
    if (fallback) {
      displayLabels.set(token, fallback);
    }
  }

  return displayLabels;
}
