import type { DocumentLocale } from "@/types/resume";

import type { TextLine } from "./pdf-text-extraction";
import { normalizeMatchingText } from "./text-heuristics";

const HAN_LETTER_PATTERN = /\p{Script=Han}/gu;
const OTHER_CJK_LETTER_PATTERN =
  /[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/gu;
const OTHER_WORD_PATTERN = /[\p{L}\p{M}]+/gu;

export function detectPdfResumeDocumentLocale(
  lines: TextLine[],
): DocumentLocale {
  const text = lines
    .map((line) => normalizeMatchingText(line.text))
    .join(" ")
    .replace(/\S+@\S+|(?:https?:\/\/|www\.)\S+/giu, " ");
  const hanLetters = text.match(HAN_LETTER_PATTERN)?.length ?? 0;
  const otherCjkLetters = text.match(OTHER_CJK_LETTER_PATTERN)?.length ?? 0;
  const otherWords =
    text
      .replace(HAN_LETTER_PATTERN, " ")
      .replace(OTHER_CJK_LETTER_PATTERN, " ")
      .match(OTHER_WORD_PATTERN)?.length ?? 0;

  return hanLetters > otherWords + otherCjkLetters ? "zh" : "en";
}
