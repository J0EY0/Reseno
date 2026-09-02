import type { DocumentLocale } from "@/types/resume";

import type { TextLine } from "./pdf-text-extraction";
import { normalizeMatchingText } from "./text-heuristics";

const LETTER_PATTERN = /\p{L}/gu;
const LATIN_LETTER_PATTERN = /^\p{Script=Latin}$/u;

export function detectPdfResumeDocumentLocale(
  lines: TextLine[],
): DocumentLocale {
  const letterLines = lines
    .map((line) => normalizeMatchingText(line.text))
    .filter((line) => /\p{L}/u.test(line));
  const letters = letterLines.join("").match(LETTER_PATTERN) ?? [];
  const containsOnlyLatinLetters =
    letters.length > 0 &&
    letters.every((letter) => LATIN_LETTER_PATTERN.test(letter));

  return containsOnlyLatinLetters ? "en" : "zh";
}
