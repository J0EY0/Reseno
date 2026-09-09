import { createId } from "@/lib/resume";
import type { SectionKind } from "@/types/resume";

import { looksLikeShortLabel } from "./basic-contact";
import type { TextLine } from "./pdf-text-extraction";
import {
  PDF_IMPORT_PROFILE,
  extractPeriod,
  looksLikePeriodLine,
  type ResumeImportLexiconContext,
} from "./parser-config";
import {
  countMatches,
  countTextGraphemes,
  joinWrappedLines,
  normalizeWhitespace,
  splitInlineList,
  splitLabeledValue,
} from "./text-heuristics";

type ExperienceLine = TextLine & {
  isBullet: boolean;
  hasPeriod: boolean;
};

// PDF parsing first produces a layout-oriented item. A single adapter below
// maps that intermediate shape into the canonical kind-specific V2 contract.
export type ParsedSectionItem = {
  id: string;
  title: string;
  subtitle: string;
  meta: string;
  period: string;
  description: string;
  highlights: string[];
};
export function buildSectionItems(
  lines: TextLine[],
  kind: SectionKind,
  lexiconContext: ResumeImportLexiconContext,
): ParsedSectionItem[] {
  if (isListSectionKind(kind)) {
    return buildListSectionItems(lines, kind);
  }

  const groups =
    kind === "publication"
      ? groupPublicationLines(lines, lexiconContext)
      : groupExperienceLines(lines, lexiconContext);
  return groups
    .map((group) => groupToItem(group, kind, lexiconContext))
    .filter(hasItemText);
}

function groupPublicationLines(
  lines: TextLine[],
  lexiconContext: ResumeImportLexiconContext,
) {
  const groups: ExperienceLine[][] = [];
  let current: ExperienceLine[] = [];
  let currentHasPeriod = false;
  const rows = groupExperienceRows(
    lines
      .map((line) => {
        const parsed = parseExperienceLine(line, lexiconContext);
        return {
          ...parsed,
          hasPeriod:
            parsed.hasPeriod || Boolean(extractStandaloneYear(parsed.text)),
        };
      })
      .filter((line) => line.text),
  );

  for (const row of rows) {
    const rowHasPeriod = row.some((line) => line.hasPeriod);
    if (current.length > 0 && currentHasPeriod && rowHasPeriod) {
      groups.push(current);
      current = [];
      currentHasPeriod = false;
    }
    current.push(...row);
    currentHasPeriod ||= rowHasPeriod;
  }

  if (current.length > 0) {
    groups.push(current);
  }
  return groups;
}

export function isListSectionKind(kind: SectionKind) {
  return kind === "simple_list";
}

function buildListSectionItems(
  lines: TextLine[],
  kind: SectionKind,
): ParsedSectionItem[] {
  const items: ParsedSectionItem[] = [];
  let labeledItem: { item: ParsedSectionItem; line: TextLine } | null = null;

  for (const line of lines) {
    const labeled = splitLabeledListLine(line.text);
    if (labeled) {
      const item = buildItem({
        title: labeled.label,
        subtitle: labeled.value,
      });
      items.push(item);
      labeledItem = { item, line };
      continue;
    }

    if (labeledItem && looksLikeListContinuation(labeledItem.line, line)) {
      labeledItem.item.subtitle = joinWrappedLines([
        labeledItem.item.subtitle,
        line.text,
      ]);
      labeledItem.line = line;
      continue;
    }

    labeledItem = null;
    if (kind === "simple_list") {
      items.push(buildItem({ title: line.text }));
      continue;
    }

    items.push(
      ...splitInlineList(line.text).map((value) => buildItem({ title: value })),
    );
  }

  return items.filter(hasItemText);
}

function looksLikeListContinuation(previous: TextLine, current: TextLine) {
  if (
    previous.page !== current.page ||
    countTextGraphemes(previous.text) <=
      PDF_IMPORT_PROFILE.text.maxTitleLineGraphemes
  ) {
    return false;
  }

  const fontSize = Math.max(previous.fontSize, current.fontSize);
  return (
    Math.abs(previous.x - current.x) <=
      fontSize * PDF_IMPORT_PROFILE.layout.listContinuationXScale &&
    previous.y - current.y > 0 &&
    previous.y - current.y <=
      fontSize * PDF_IMPORT_PROFILE.layout.listContinuationGapScale
  );
}

function splitLabeledListLine(value: string) {
  const labeledValue = splitLabeledValue(
    value,
    PDF_IMPORT_PROFILE.text.maxShortLabelGraphemes,
  );
  return labeledValue && looksLikeShortLabel(labeledValue.label)
    ? labeledValue
    : null;
}

function groupExperienceLines(
  lines: TextLine[],
  lexiconContext: ResumeImportLexiconContext,
) {
  // Experience-like sections usually contain a compact header followed by
  // body copy. Use visual rows for the boundary check so a right-column date
  // remains part of the same item as the left-column company or project name.
  const groups: ExperienceLine[][] = [];
  let current: ExperienceLine[] = [];
  const parsedLines = lines
    .map((line) => parseExperienceLine(line, lexiconContext))
    .filter((line) => line.text);
  const rows = groupExperienceRows(parsedLines);
  let currentHasBody = false;
  let currentHasPeriod = false;

  for (const [index, row] of rows.entries()) {
    const startsNew =
      current.length > 0 &&
      currentHasBody &&
      looksLikeExperienceHeaderStart(rows, index);
    if (startsNew) {
      groups.push(current);
      current = [];
      currentHasBody = false;
      currentHasPeriod = false;
    }

    current.push(...row);
    const rowHasPeriod = row.some((line) => line.hasPeriod);
    // Vector bullets are absent from PDF.js text. Once a dated header has been
    // followed by another row, the current item has enough structural body
    // evidence to let a later dated header start the next item, even when the
    // body text is short and has no terminal punctuation.
    currentHasBody ||= currentHasPeriod && !rowHasPeriod;
    currentHasPeriod ||= rowHasPeriod;
    currentHasBody ||= row.some(
      (line) => line.isBullet || looksLikeHighlightLine(line.text),
    );
  }

  if (current.length > 0) {
    groups.push(current);
  }

  return groups;
}

function groupExperienceRows(lines: ExperienceLine[]) {
  const rows: ExperienceLine[][] = [];

  for (const line of lines) {
    const row = rows.find((candidate) => {
      const anchor = candidate[0];
      if (!anchor || anchor.page !== line.page) {
        return false;
      }
      const tolerance =
        Math.max(anchor.fontSize, line.fontSize) *
        PDF_IMPORT_PROFILE.layout.headerRowToleranceScale;
      return Math.abs(anchor.y - line.y) <= tolerance;
    });

    if (row) {
      row.push(line);
    } else {
      rows.push([line]);
    }
  }

  return rows.map((row) => [...row].sort((left, right) => left.x - right.x));
}

function looksLikeExperienceHeaderStart(
  rows: ExperienceLine[][],
  startIndex: number,
) {
  const candidateRows = rows.slice(
    startIndex,
    startIndex + PDF_IMPORT_PROFILE.text.maxHeaderRowsPerItem,
  );
  let periodRowIndex = -1;

  for (const [index, row] of candidateRows.entries()) {
    if (
      row.some((line) => line.isBullet || looksLikeHighlightLine(line.text))
    ) {
      break;
    }
    if (row.some((line) => line.hasPeriod)) {
      periodRowIndex = index;
      break;
    }
  }

  if (periodRowIndex < 0) {
    return false;
  }

  if (periodRowIndex <= PDF_IMPORT_PROFILE.text.maxDirectPeriodRowIndex) {
    return true;
  }

  // A distant date is only reliable when the preceding rows already form a
  // visible multi-column header. In a plain single-column PDF, accepting any
  // short line before a later date would move the previous item's final body
  // sentence into the next experience.
  return candidateRows.slice(0, periodRowIndex).some((row) => row.length > 1);
}

function parseExperienceLine(
  rawLine: TextLine,
  lexiconContext: ResumeImportLexiconContext,
): ExperienceLine {
  const text = normalizeBulletLine(rawLine.text);
  return {
    ...rawLine,
    text,
    isBullet: isBulletLine(rawLine.text),
    hasPeriod: looksLikePeriodLine(text, lexiconContext),
  };
}

function groupToItem(
  group: ExperienceLine[],
  kind: SectionKind,
  lexiconContext: ResumeImportLexiconContext,
): ParsedSectionItem {
  // Treat early compact lines as the item header and sentence-shaped lines as
  // highlights. This intentionally avoids content dictionaries such as tech
  // names or action verbs; structure is more stable across languages/domains.
  const textLines = group.map((line) => line.text);
  const period =
    extractPeriod(textLines, lexiconContext) ||
    (kind === "publication"
      ? (textLines.map(extractStandaloneYear).find(Boolean) ?? "")
      : "");
  const headerLines: ExperienceLine[] = [];
  const highlightLines: string[] = [];
  let description = "";
  let descriptionLastLine: ExperienceLine | null = null;
  let highlightLastLine: ExperienceLine | null = null;

  for (const line of group) {
    const text = normalizeWhitespace(line.text.replace(period, ""));
    if (!text) {
      continue;
    }

    if (line.isBullet) {
      highlightLines.push(text);
      highlightLastLine = line;
      continue;
    }

    if (highlightLines.length > 0) {
      if (
        highlightLastLine &&
        looksLikeWrappedBodyContinuation(
          highlightLastLine,
          line,
          highlightLines.at(-1) ?? "",
        )
      ) {
        appendHighlightContinuation(highlightLines, text);
      } else if (looksLikeHighlightLine(text)) {
        highlightLines.push(text);
        highlightLastLine = line;
      } else {
        appendHighlightLine(highlightLines, text);
      }
      highlightLastLine = line;
      continue;
    }

    if (description) {
      if (
        descriptionLastLine &&
        looksLikeWrappedBodyContinuation(descriptionLastLine, line, description)
      ) {
        description = joinWrappedLines([description, text]);
        descriptionLastLine = line;
      } else if (looksLikeHighlightLine(text)) {
        highlightLines.push(text);
        highlightLastLine = line;
      } else {
        description = joinWrappedLines([description, text]);
        descriptionLastLine = line;
      }
      continue;
    }

    if (
      headerLines.length < PDF_IMPORT_PROFILE.text.maxHeaderLinesPerItem &&
      !looksLikeHighlightLine(text)
    ) {
      headerLines.push({ ...line, text });
    } else {
      description = text;
      descriptionLastLine = line;
    }
  }

  const item = headerLinesToItem(headerLines, kind);
  const highlights = highlightLines.filter(Boolean);

  return buildItem({
    ...item,
    period,
    description,
    highlights,
  });
}

function extractStandaloneYear(value: string) {
  const match = value.trim().match(/^\d{4}$/);
  if (!match) {
    return "";
  }
  const year = Number(match[0]);
  const { minYear, maxYear } = PDF_IMPORT_PROFILE.dates;
  return year >= minYear && year <= maxYear ? match[0] : "";
}

function looksLikeWrappedBodyContinuation(
  previousLine: ExperienceLine,
  currentLine: ExperienceLine,
  previousText: string,
) {
  if (
    currentLine.isBullet ||
    previousLine.page !== currentLine.page ||
    endsSentence(previousText)
  ) {
    return false;
  }

  const fontSize = Math.max(previousLine.fontSize, currentLine.fontSize);
  return (
    Math.abs(previousLine.x - currentLine.x) <=
      fontSize * PDF_IMPORT_PROFILE.layout.listContinuationXScale &&
    previousLine.y - currentLine.y > 0 &&
    previousLine.y - currentLine.y <=
      fontSize * PDF_IMPORT_PROFILE.layout.listContinuationGapScale
  );
}

function endsSentence(value: string) {
  return /[.!?。！？；;]$/.test(value.trim());
}

function headerLinesToItem(
  headerLines: ExperienceLine[],
  kind: SectionKind,
): Partial<ParsedSectionItem> {
  const visualRows = groupExperienceRows(headerLines);
  if (visualRows.some((row) => row.length > 1)) {
    const firstRow = visualRows[0] ?? [];
    const laterLeftCells = visualRows
      .slice(1)
      .map((row) => row[0]?.text ?? "")
      .filter(Boolean);
    const rightCells = visualRows
      .flatMap((row) => row.slice(1))
      .map((line) => line.text)
      .filter(Boolean);

    // In multi-column resume headers, reading order is semantic: the left
    // column carries title/subtitle while the right column carries compact
    // metadata. Mapping by x-position avoids provider- or language-specific
    // content dictionaries.
    return {
      title: firstRow[0]?.text ?? "",
      subtitle: laterLeftCells.join(" · "),
      meta: rightCells.join(" · "),
    };
  }

  const textLines = headerLines.map((line) => line.text);
  // Field placement is best-effort. When the shape is unclear, preserve text in
  // subtitle/meta rather than dropping it or forcing a brittle semantic guess.
  if (kind === "education") {
    const meta = textLines.find(looksLikeScoreMetaLine) ?? "";
    const remaining = textLines.filter((line) => line !== meta);
    const title = pickMostLikelyTitleLine(remaining) ?? "";
    const subtitle = remaining.filter((line) => line !== title).join(" · ");
    return { title, subtitle, meta };
  }

  if (kind === "project") {
    const meta = textLines.find(looksLikeListMetaLine) ?? "";
    const remaining = textLines.filter((line) => line !== meta);
    const title = pickMostLikelyTitleLine(remaining) ?? "";
    const subtitle = remaining.filter((line) => line !== title).join(" · ");
    return { title, subtitle, meta };
  }

  const [titleLine, ...rest] = textLines;
  const [title, inlineSubtitle] = splitTitleAndSubtitle(titleLine ?? "");
  return {
    title,
    subtitle: inlineSubtitle || rest[0] || "",
    meta: rest.slice(inlineSubtitle ? 0 : 1).join(" · "),
  };
}

function buildItem(overrides: Partial<ParsedSectionItem>): ParsedSectionItem {
  return {
    id: createId("item"),
    title: "",
    subtitle: "",
    meta: "",
    period: "",
    description: "",
    highlights: [],
    ...overrides,
  };
}

function splitTitleAndSubtitle(value: string): [string, string] {
  const parts = value
    .split(/\s{2,}|[|｜]/)
    .map((part) => part.trim())
    .filter(Boolean);

  return [parts[0] ?? value, parts.slice(1).join(" · ")];
}
export function looksLikeHighlightLine(line: string) {
  // Avoid content-word dictionaries here. A line is treated as body text only
  // when its shape looks like a sentence or a dense comma-separated statement.
  return (
    countTextGraphemes(line) >
      PDF_IMPORT_PROFILE.text.minLongDescriptionGraphemes ||
    /[。；;.]$/.test(line) ||
    countMatches(line, /[，,、]/g) >= PDF_IMPORT_PROFILE.text.minDenseCommaCount
  );
}

function appendHighlightLine(highlights: string[], line: string) {
  if (looksLikeHighlightLine(line)) {
    highlights.push(line);
    return;
  }

  const lastIndex = highlights.length - 1;
  highlights[lastIndex] = normalizeWhitespace(
    `${highlights[lastIndex]} ${line}`,
  );
}

function appendHighlightContinuation(highlights: string[], line: string) {
  const lastIndex = highlights.length - 1;
  highlights[lastIndex] = joinWrappedLines([highlights[lastIndex] ?? "", line]);
}

function looksLikeScoreMetaLine(line: string) {
  // Education metadata is usually numeric even when labels vary by language.
  return (
    /\d/.test(line) &&
    (/\/|%|[()（）]/.test(line) ||
      countMatches(line, /\d/g) >= PDF_IMPORT_PROFILE.text.minScoreDigitCount)
  );
}

function looksLikeListMetaLine(line: string) {
  if (looksLikeHighlightLine(line)) {
    return false;
  }

  return (
    splitInlineList(line).length >= PDF_IMPORT_PROFILE.text.minListMetaParts ||
    /[+/]/.test(line)
  );
}

function pickMostLikelyTitleLine(lines: string[]) {
  return [...lines]
    .filter(Boolean)
    .sort((left, right) => titleLineScore(right) - titleLineScore(left))[0];
}

function titleLineScore(line: string) {
  let score = 0;
  if (/[\p{Script=Han}A-Za-z]/u.test(line)) {
    score += PDF_IMPORT_PROFILE.scoring.titleContainsText;
  }
  if (!looksLikeListMetaLine(line)) {
    score += PDF_IMPORT_PROFILE.scoring.titleIsNotListMetadata;
  }
  if (!looksLikeHighlightLine(line)) {
    score += PDF_IMPORT_PROFILE.scoring.titleIsNotBodyText;
  }
  if (
    countTextGraphemes(line) <= PDF_IMPORT_PROFILE.text.maxTitleLineGraphemes
  ) {
    score += PDF_IMPORT_PROFILE.scoring.titleFitsLengthLimit;
  }

  return score;
}

function hasItemText(item: ParsedSectionItem) {
  return [
    item.title,
    item.subtitle,
    item.meta,
    item.period,
    item.description,
    ...item.highlights,
  ].some((value) => value.trim());
}

function normalizeBulletLine(line: string) {
  return normalizeWhitespace(line.replace(/^[•·*●○◦▪▫-]+\s*/, ""));
}
export function isBulletLine(line: string) {
  return /^[\s•·*●○◦▪▫-]+/.test(line);
}
