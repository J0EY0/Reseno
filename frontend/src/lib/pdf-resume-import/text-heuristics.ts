import { PdfImportError } from "./errors";
const GRAPHEME_SEGMENTER =
  typeof Intl.Segmenter === "function"
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;
const CJK_COMPATIBILITY_CHARACTER_PATTERN = /[\u2e80-\u2fff\uf900-\ufaff]/gu;
const CJK_RADICAL_TEXT_EQUIVALENTS: Readonly<Record<string, string>> = {
  // U+2EDA has no NFKC mapping, but Type3 fonts can expose it for the
  // simplified character "页". Treat this as text decoding, not vocabulary.
  "⻚": "页",
  // U+2EEC is similarly emitted for the simplified character "齐".
  "⻬": "齐",
};
export function joinWrappedLines(lines: string[]) {
  return lines.reduce((result, line) => {
    const normalized = normalizeWhitespace(line);
    if (!normalized) {
      return result;
    }
    if (!result) {
      return normalized;
    }

    // Chinese PDF text commonly wraps without an explicit separator. English
    // prose still needs a space when two physical lines are joined.
    const separator =
      /[\p{Script=Han}]$/u.test(result) && /^[\p{Script=Han}]/u.test(normalized)
        ? ""
        : " ";
    return `${result}${separator}${normalized}`;
  }, "");
}
export function splitInlineList(value: string) {
  return value
    .split(/[，,、;；|｜]|\s+\+\s+/)
    .map(normalizeWhitespace)
    .filter(Boolean);
}

export function splitLabeledValue(input: string, maxLabelGraphemes: number) {
  const match = input.match(/^([^：:]+?)[：:]\s*(.+)$/);
  if (!match) {
    return null;
  }

  const label = normalizeWhitespace(match[1] ?? "");
  const value = normalizeWhitespace(match[2] ?? "");
  if (!label || !value || countTextGraphemes(label) > maxLabelGraphemes) {
    return null;
  }

  return { label, value };
}

export function countMatches(value: string, pattern: RegExp) {
  return value.match(pattern)?.length ?? 0;
}

export function countTextGraphemes(value: string) {
  return splitTextGraphemes(value).length;
}

function splitTextGraphemes(value: string) {
  const normalized = value.normalize("NFC");
  if (!GRAPHEME_SEGMENTER) {
    // Grapheme-based thresholds keep parsing behavior consistent across
    // languages. A code-unit/code-point fallback would silently change those
    // semantics for combining marks and joined emoji in older runtimes.
    throw new PdfImportError("PDF_IMPORT_UNSUPPORTED_GRAPHEME_SEGMENTATION");
  }

  return Array.from(
    GRAPHEME_SEGMENTER.segment(normalized),
    ({ segment }) => segment,
  );
}

export function isSingleHanGrapheme(value: string) {
  const graphemes = splitTextGraphemes(value);
  return (
    graphemes.length === 1 &&
    /^\p{Script=Han}\p{Mark}*$/u.test(graphemes[0] ?? "")
  );
}

export function normalizeWhitespace(value: string) {
  return normalizePdfCompatibilityCharacters(value).replace(/\s+/g, " ").trim();
}

export function normalizeMatchingText(value: string) {
  return normalizePdfCompatibilityCharacters(value)
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim();
}

export function normalizeLexiconTerm(value: string) {
  return normalizeMatchingText(value).toLowerCase();
}
export function normalizePdfCompatibilityCharacters(value: string) {
  return value.replace(CJK_COMPATIBILITY_CHARACTER_PATTERN, (character) => {
    return (
      CJK_RADICAL_TEXT_EQUIVALENTS[character] ?? character.normalize("NFKC")
    );
  });
}
