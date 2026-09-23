import type { Locale } from "@/i18n";

const storageKey = "reseno-template-editor-width-v1";

function normalizeWidth(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(560, Math.max(340, value))
    : undefined;
}

export function readTemplateEditorWidth() {
  try {
    return normalizeWidth(
      JSON.parse(localStorage.getItem(storageKey) ?? "null"),
    );
  } catch {
    return undefined;
  }
}

export function writeTemplateEditorWidth(width: number) {
  const normalized = normalizeWidth(width);
  if (normalized === undefined) return;
  try {
    localStorage.setItem(storageKey, String(normalized));
  } catch {
    return;
  }
}

export function resolveTemplateWorkspaceWidth(
  containerWidth: number,
  preference: number | undefined,
  locale: Locale,
) {
  const minimum = locale === "en" ? 400 : 340;
  const maximum = Math.max(minimum, Math.min(560, containerWidth - 420));
  return {
    minimum,
    maximum,
    width: Math.min(
      maximum,
      Math.max(minimum, normalizeWidth(preference) ?? minimum),
    ),
  };
}
