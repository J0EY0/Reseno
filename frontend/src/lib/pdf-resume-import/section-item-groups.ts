import type { TextLine } from "./pdf-text-extraction";
import {
  PDF_IMPORT_PROFILE,
  looksLikePeriodLine,
  type ResumeImportLexiconContext,
} from "./parser-config";
import {
  countMatches,
  countTextGraphemes,
  normalizeWhitespace,
} from "./text-heuristics";

export type ExperienceLine = TextLine & {
  isBullet: boolean;
  hasPeriod: boolean;
};

export function groupPublicationLines(
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

export function groupExperienceLines(
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
      (looksLikeExperienceHeaderStart(rows, index) ||
        looksLikeUndatedHeader(rows, index, current[0]));
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
    currentHasBody ||=
      !rowHasPeriod &&
      row.some((line) => line.isBullet || looksLikeHighlightLine(line.text));
  }

  if (current.length > 0) {
    groups.push(current);
  }

  return groups;
}

export function groupExperienceRows(lines: ExperienceLine[]) {
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
    if (row.some((line) => line.hasPeriod && !line.isBullet)) {
      periodRowIndex = index;
      break;
    }
    if (
      row.some((line) => line.isBullet || looksLikeHighlightLine(line.text))
    ) {
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

function looksLikeUndatedHeader(
  rows: ExperienceLine[][],
  index: number,
  firstHeader: ExperienceLine | undefined,
) {
  const candidate = rows[index]?.[0];
  const previous = rows[index - 1]?.[0];
  const next = rows[index + 1]?.[0];
  if (
    !candidate ||
    !previous ||
    !next ||
    !firstHeader ||
    candidate.isBullet ||
    looksLikeHighlightLine(candidate.text)
  ) {
    return false;
  }

  const tolerance =
    candidate.fontSize * PDF_IMPORT_PROFILE.layout.listContinuationXScale;
  if (Math.abs(candidate.x - firstHeader.x) > tolerance) {
    return false;
  }

  return (
    (candidate.x + tolerance < previous.x &&
      candidate.x + tolerance < next.x) ||
    (candidate.fontSize >
      previous.fontSize * PDF_IMPORT_PROFILE.layout.basicFieldLabelScale &&
      candidate.fontSize >
        next.fontSize * PDF_IMPORT_PROFILE.layout.basicFieldLabelScale) ||
    (candidate.fontName &&
      previous.fontName &&
      next.fontName &&
      candidate.fontName === firstHeader.fontName &&
      candidate.fontName !== previous.fontName &&
      candidate.fontName !== next.fontName)
  );
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

export function extractStandaloneYear(value: string) {
  const match = value.trim().match(/^\d{4}$/);
  if (!match) {
    return "";
  }
  const year = Number(match[0]);
  const { minYear, maxYear } = PDF_IMPORT_PROFILE.dates;
  return year >= minYear && year <= maxYear ? match[0] : "";
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

export function normalizeBulletLine(line: string) {
  return normalizeWhitespace(
    line.replace(/^[\p{Co}]+\s+/u, "").replace(/^[•·*●○◦▪▫-]+\s*/, ""),
  );
}

export function isBulletLine(line: string) {
  return /^[\s•·*●○◦▪▫-]+/.test(line);
}
