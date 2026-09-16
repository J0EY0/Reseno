import { createId } from "@/lib/resume";
import type { TextLine } from "./pdf-text-extraction";
import {
  extractPeriod,
  PDF_IMPORT_PROFILE,
  type ResumeImportLexiconContext,
} from "./parser-config";
import {
  extractStandaloneYear,
  isBulletLine,
  normalizeBulletLine,
} from "./section-item-groups";
import type { ParsedSectionItem } from "./section-item-types";
import { joinWrappedLines, normalizeWhitespace } from "./text-heuristics";

type Achievement = {
  item: ParsedSectionItem;
  first: TextLine;
  last: TextLine;
};

export function buildAchievementItems(
  lines: TextLine[],
  lexicon: ResumeImportLexiconContext,
): ParsedSectionItem[] {
  const achievements: Achievement[] = [];
  for (const line of lines) {
    const text = normalizeBulletLine(line.text);
    if (!text) continue;
    const date = extractStandaloneYear(text) || extractPeriod([text], lexicon);
    const dateOnly = date && normalizeWhitespace(text.replace(date, "")) === "";
    const previous = findPreviousAchievement(
      achievements,
      line,
      Boolean(dateOnly),
    );

    if (dateOnly && previous && !previous.item.period) {
      previous.item.period = date;
      previous.last = line;
      continue;
    }

    if (previous && isAchievementContinuation(previous, line)) {
      const sentence = /[.!?。！？；;]$/.test(text);
      if (sentence || previous.item.description) {
        previous.item.description = joinWrappedLines([
          previous.item.description,
          text,
        ]);
      } else {
        previous.item.title = joinWrappedLines([previous.item.title, text]);
      }
      previous.last = line;
      continue;
    }

    const header =
      date && !dateOnly
        ? normalizeWhitespace(
            text.replace(date, "").replace(/[(（]\s*[)）]/g, ""),
          )
        : text;
    const [title, ...issuer] = header
      .split(/[|｜]/)
      .map((part) => part.trim())
      .filter(Boolean);
    achievements.push({
      first: line,
      last: line,
      item: {
        id: createId("item"),
        title,
        subtitle: issuer.join(" · "),
        meta: "",
        period: dateOnly ? "" : date,
        description: "",
        highlights: [],
      },
    });
  }
  return achievements.map(({ item }) => item);
}

function findPreviousAchievement(
  achievements: Achievement[],
  line: TextLine,
  dateOnly: boolean,
) {
  return [...achievements].reverse().find(({ first, last }) => {
    if (last.page !== line.page) return false;
    const fontSize = Math.max(last.fontSize, line.fontSize);
    const sameRow =
      Math.abs(last.y - line.y) <=
      fontSize * PDF_IMPORT_PROFILE.layout.headerRowToleranceScale;
    if (dateOnly && sameRow && first.x < line.x) return true;
    return (
      last.y > line.y &&
      last.y - line.y <=
        fontSize * PDF_IMPORT_PROFILE.layout.listContinuationGapScale &&
      line.x >=
        first.x - fontSize * PDF_IMPORT_PROFILE.layout.listContinuationXScale &&
      line.x - first.x < fontSize * 4
    );
  });
}

function isAchievementContinuation(previous: Achievement, line: TextLine) {
  if (isBulletLine(line.text)) return false;
  const tolerance =
    line.fontSize * PDF_IMPORT_PROFILE.layout.listContinuationXScale;
  return (
    line.x > previous.first.x + tolerance ||
    (Math.abs(line.x - previous.first.x) <= tolerance &&
      Boolean(
        previous.item.period ||
        previous.item.subtitle ||
        previous.item.description ||
        line.fontSize < previous.first.fontSize,
      ) &&
      /[.!?。！？；;]$/.test(line.text.trim()))
  );
}
