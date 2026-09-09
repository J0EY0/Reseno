import type { ContactFieldType } from "@/types/resume";

const contactFieldTypes = new Set<ContactFieldType>([
  "email",
  "phone",
  "url",
  "text",
]);
const explicitSchemePattern = /^[a-z][a-z\d+.-]*:/i;
const emailProtocols = new Set(["mailto:"]);
const phoneProtocols = new Set(["tel:"]);
const urlProtocols = new Set(["http:", "https:"]);

export function normalizeContactFieldType(value: unknown): ContactFieldType {
  return typeof value === "string" &&
    contactFieldTypes.has(value as ContactFieldType)
    ? (value as ContactFieldType)
    : "text";
}

function containsControlCharacter(value: string) {
  return Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint <= 31 || codePoint === 127;
  });
}

/**
 * Build a link target from the declared contact type, never from a guessed
 * label. Explicit schemes are preserved only when they match the type; URL
 * values without a scheme use HTTPS so common portfolio inputs remain useful.
 */
export function createContactHref(
  type: ContactFieldType,
  rawValue: string,
): string | null {
  const value = rawValue.trim();

  if (!value || type === "text" || containsControlCharacter(value)) {
    return null;
  }

  let candidate: string;
  let allowedProtocols: ReadonlySet<string>;

  switch (type) {
    case "email":
      candidate = explicitSchemePattern.test(value) ? value : `mailto:${value}`;
      allowedProtocols = emailProtocols;
      break;
    case "phone":
      candidate = explicitSchemePattern.test(value) ? value : `tel:${value}`;
      allowedProtocols = phoneProtocols;
      break;
    case "url":
      candidate = value.startsWith("//")
        ? `https:${value}`
        : explicitSchemePattern.test(value)
          ? value
          : `https://${value}`;
      allowedProtocols = urlProtocols;
      break;
  }

  try {
    const url = new URL(candidate);

    if (!allowedProtocols.has(url.protocol)) {
      return null;
    }

    if (
      (url.protocol === "http:" || url.protocol === "https:") &&
      !url.hostname
    ) {
      return null;
    }

    if (
      (url.protocol === "mailto:" || url.protocol === "tel:") &&
      !url.pathname
    ) {
      return null;
    }

    return url.href;
  } catch {
    return null;
  }
}
