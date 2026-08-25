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
