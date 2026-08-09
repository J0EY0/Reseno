import type { AppMessages } from "@/i18n";

export const maxResumeTitleLength = 50;

export function createDefaultResumeTitle(t: AppMessages, index: number) {
  return t.defaultResumeTitle.replace("{index}", String(index));
}

export function truncateResumeTitle(value: string) {
  return Array.from(value).slice(0, maxResumeTitleLength).join("");
}

export function normalizeResumeTitle(value: unknown, fallback: string) {
  const title = typeof value === "string" ? value.trim() : "";

  return truncateResumeTitle(title || fallback);
}

export function formatResumeTitleForToolbar(value: string) {
  const copySuffix =
    value.match(
      /\s+-\s+(?:副本|Copy)(?:\s*\(\d+\)|\s*（\d+）|\s+\d+)?$/,
    )?.[0] ?? "";
  const baseTitle = copySuffix
    ? value.slice(0, -copySuffix.length).trimEnd()
    : value;
  const characters = Array.from(baseTitle);
  const visibleBaseCharacterCount = copySuffix ? 4 : 6;

  if (characters.length <= visibleBaseCharacterCount) {
    return value;
  }

  return `${characters
    .slice(0, visibleBaseCharacterCount)
    .join("")
    .trimEnd()}...${copySuffix}`;
}
