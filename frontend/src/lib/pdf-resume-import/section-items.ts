import { createId } from "@/lib/resume";
import type { SectionKind } from "@/types/resume";

import { looksLikeShortLabel } from "./basic-contact";
import { buildAchievementItems } from "./achievement-items";
import type { ParsedSectionItem } from "./section-item-types";
import {
  extractStandaloneYear,
  groupExperienceLines,
  groupExperienceRows,
  groupPublicationLines,
  looksLikeHighlightLine,
  normalizeBulletLine,
  type ExperienceLine,
} from "./section-item-groups";
import type { TextLine } from "./pdf-text-extraction";
import {
  PDF_IMPORT_PROFILE,
  extractPeriod,
  type ResumeImportLexiconContext,
} from "./parser-config";
import {
  countMatches,
  countLeadingWordGraphemes,
  countTextGraphemes,
  joinWrappedLines,
  normalizeWhitespace,
  splitInlineList,
  splitLabeledValue,
} from "./text-heuristics";

export function buildSectionItems(
  lines: TextLine[],
  kind: SectionKind,
  lexiconContext: ResumeImportLexiconContext,
): ParsedSectionItem[] {
  if (isListSectionKind(kind)) {
    return buildListSectionItems(lines);
  }
  if (kind === "achievement") {
    return buildAchievementItems(lines, lexiconContext);
  }

  const groups =
    kind === "publication"
      ? groupPublicationLines(lines, lexiconContext)
      : groupExperienceLines(lines, lexiconContext);
  return groups
    .map((group) => groupToItem(group, kind, lexiconContext))
    .filter(hasItemText);
}

export function isListSectionKind(kind: SectionKind) {
  return kind === "simple_list";
}

function buildListSectionItems(lines: TextLine[]): ParsedSectionItem[] {
  const items: ParsedSectionItem[] = [];
  let current: {
    item: ParsedSectionItem;
    line: TextLine;
    labeled: boolean;
  } | null = null;

  for (const line of lines) {
    const text = normalizeBulletLine(line.text);
    const labeled = splitLabeledListLine(text);
    if (
      current &&
      !labeled &&
      text === normalizeWhitespace(line.text) &&
      (looksLikeMeasuredListContinuation(current.line, line, lines) ||
        (current.labeled &&
          !current.line.width &&
          looksLikeListContinuation(current.line, line)))
    ) {
      const field = current.labeled ? "subtitle" : "title";
      current.item[field] = joinWrappedLines([current.item[field], text]);
      current.line = line;
      continue;
    }

    if (labeled) {
      const item = buildItem({
        title: labeled.label,
        subtitle: labeled.value,
      });
      items.push(item);
      current = { item, line, labeled: true };
      continue;
    }

    const item = buildItem({ title: text });
    items.push(item);
    current = { item, line, labeled: false };
  }

  return items.filter(hasItemText);
}

function looksLikeMeasuredListContinuation(
  previous: TextLine,
  current: TextLine,
  lines: TextLine[],
) {
  if (!previous.width || !looksLikeListContinuation(previous, current)) {
    return false;
  }
  const fontSize = Math.max(previous.fontSize, current.fontSize);
  if (Math.abs(previous.fontSize - current.fontSize) > fontSize * 0.05) {
    return false;
  }
  const columnWidth = Math.max(
    ...lines
      .filter(
        (line) =>
          line.page === previous.page &&
          Math.abs(line.x - previous.x) <=
            fontSize * PDF_IMPORT_PROFILE.layout.listContinuationXScale,
      )
      .map((line) => line.width ?? 0),
  );
  const leadingWordWidth = current.width
    ? (current.width * countLeadingWordGraphemes(current.text)) /
      Math.max(1, countTextGraphemes(current.text))
    : 0;
  const wrapAllowance = Math.max(fontSize * 2, leadingWordWidth + fontSize / 2);
  return previous.width >= columnWidth - wrapAllowance;
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
    const text = normalizeWhitespace(
      line.text.replace(period, "").replace(/[(（]\s*[)）]/g, ""),
    );
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
      (line.hasPeriod ||
        (!looksLikeHighlightLine(text) &&
          !isIndentedBodyLine(line, headerLines)))
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
    description: [item.description, description].filter(Boolean).join("\n\n"),
    highlights,
  });
}

function isIndentedBodyLine(line: ExperienceLine, header: ExperienceLine[]) {
  const first = header[0];
  if (!first || first.page !== line.page) {
    return false;
  }
  const tolerance =
    line.fontSize * PDF_IMPORT_PROFILE.layout.listContinuationXScale;
  return (
    line.y <
      first.y -
        line.fontSize * PDF_IMPORT_PROFILE.layout.headerRowToleranceScale &&
    line.x > first.x + tolerance &&
    !header.some((cell) => Math.abs(cell.x - line.x) <= tolerance)
  );
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
      meta: (kind === "project"
        ? rightCells.filter(looksLikeListMetaLine)
        : rightCells
      ).join(" · "),
      description:
        kind === "project"
          ? rightCells
              .filter((text) => !looksLikeListMetaLine(text))
              .join("\n\n")
          : "",
    };
  }

  const textLines = headerLines.map((line) => line.text);
  // Field placement is best-effort. When the shape is unclear, preserve text in
  // subtitle/meta rather than dropping it or forcing a brittle semantic guess.
  if (kind === "education") {
    const fields = textLines.flatMap((line) =>
      line
        .split(/[|｜]/)
        .map((part) => part.trim())
        .filter(Boolean),
    );
    const meta = fields.find(looksLikeScoreMetaLine) ?? "";
    const remaining = fields.filter((line) => line !== meta);
    const title = /[|｜]/.test(textLines[0] ?? "")
      ? (remaining[0] ?? "")
      : (pickMostLikelyTitleLine(remaining) ?? "");
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
