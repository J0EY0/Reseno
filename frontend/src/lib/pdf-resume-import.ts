import { apiRoutes, requestApi } from "@/lib/api-client";
import { createId } from "@/lib/resume";
import type {
  ResumeData,
  ResumeSection,
  ResumeSectionItem,
  SectionKind,
  SectionLayout,
} from "@/types/resume";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

type PdfTextItem = {
  str?: string;
  transform?: number[];
  width?: number;
  height?: number;
};

type PdfTextContent = {
  items?: PdfTextItem[];
};

type PdfPage = {
  getTextContent(): Promise<PdfTextContent>;
};

type PdfDocument = {
  numPages: number;
  getPage(pageNumber: number): Promise<PdfPage>;
};

type PdfJsModule = {
  GlobalWorkerOptions: {
    workerSrc: string;
  };
  getDocument(
    source: { data: Uint8Array },
  ): { promise: Promise<PdfDocument> };
};

type TextLine = {
  text: string;
  page: number;
  x: number;
  y: number;
  fontSize: number;
};

type SectionCandidate = {
  rawTitle: string;
  kind: SectionKind;
  confidence: number;
  lines: string[];
};

type ClassifiedSectionTitle = {
  kind: SectionKind;
  confidence: number;
};

type SectionRegistryEntry = {
  kind: SectionKind;
  defaultLayout: SectionLayout;
  labels: Record<string, string>;
  aliases: string[];
};

type SectionRegistryResponse = {
  sections: SectionRegistryEntry[];
};

type SectionRegistryContext = {
  kindByAlias: Map<string, SectionKind>;
  defaultLayoutByKind: Map<SectionKind, SectionLayout>;
};

type ExperienceLine = {
  text: string;
  isBullet: boolean;
  hasPeriod: boolean;
};

type PositionedTextItem = {
  text: string;
  x: number;
  y: number;
  fontSize: number;
  width: number;
};

// These parser knobs describe structural guardrails, not resume content.
// Keep them centralized so tuning the PDF heuristics does not spread magic
// numbers through the extraction pipeline.
const MAX_IMPORTED_HIGHLIGHTS = 6;
const PDF_IMPORT_MIN_TEXT_LENGTH = 80;
const SECTION_KIND_CONFIDENCE_THRESHOLD = 0.75;
const CONTACT_SCAN_LINE_LIMIT = 8;
const GENERIC_SECTION_HEADING_SKIP_LINES = 4;
const GENERIC_SECTION_HEADING_SCALE = 1.15;
const MAX_GENERIC_SECTION_HEADING_CHARS = 18;
const MAX_HEADER_LINES_PER_ITEM = 4;
const MAX_NAME_CHARS = 32;
const MAX_NAME_SCAN_LINES = 5;
const MAX_TITLE_LINE_CHARS = 32;
const MAX_SHORT_LABEL_CHARS = 16;
const MAX_LOCATION_CHARS = 32;
const MIN_CJK_LOCATION_CHARS = 2;
const MAX_CJK_LOCATION_CHARS = 12;
const MAX_PREFIX_CJK_LOCATION_CHARS = 4;
const MAX_ITEM_HEADING_CHARS = 48;
const MIN_LONG_DESCRIPTION_CHARS = 52;
const MIN_DENSE_COMMA_COUNT = 2;
const MIN_SCORE_DIGIT_COUNT = 2;
const MIN_LIST_META_PARTS = 3;
const MIN_COLUMN_GAP_WORDS = 10;
const MAX_STANDALONE_LOCATION_TOKENS = 1;
const CONTACT_TOKEN_SEPARATOR = /[|｜·•,，]/;
const EMAIL_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;
const PHONE_PATTERN = /(?:\+?\d[\d\s-]{6,}\d)/;
const DOMAIN_PATTERN = /\b[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\/\S*)?\b/i;
const SECTION_TITLE_CONFIDENCE = 0.95;
const SECTION_REGISTRY_CACHE_TTL_MS = 5 * 60 * 1000;

const NAME_BLOCKED_WORDS = new Set([
  "resume",
  "curriculum",
  "vitae",
  "简历",
  "个人简历",
]);

export async function importResumeFromPdf(
  file: File,
  fallbackSectionTitle: string,
): Promise<ResumeData> {
  const [lines, registry] = await Promise.all([
    extractPdfLines(file),
    fetchSectionRegistry(),
  ]);
  const text = lines.map((line) => line.text).join("\n").trim();

  if (text.length < PDF_IMPORT_MIN_TEXT_LENGTH) {
    throw new Error("PDF_IMPORT_NO_TEXT");
  }

  return buildResumeFromPdfLines(lines, fallbackSectionTitle, registry);
}

async function fetchSectionRegistry() {
  return requestApi<SectionRegistryResponse>(apiRoutes.sectionRegistry, {
    cacheTtlMs: SECTION_REGISTRY_CACHE_TTL_MS,
  });
}

async function extractPdfLines(file: File): Promise<TextLine[]> {
  const pdfjs = await loadPdfJs();
  const buffer = await file.arrayBuffer();
  const document = await pdfjs.getDocument({ data: new Uint8Array(buffer) }).promise;
  const lines: TextLine[] = [];

  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const content = await page.getTextContent();
    lines.push(...textContentToLinesForResumeImport(content, pageNumber));
  }

  return lines;
}

async function loadPdfJs(): Promise<PdfJsModule> {
  const pdfjs = (await import("pdfjs-dist/build/pdf.mjs")) as PdfJsModule;
  pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
  return pdfjs;
}

export function textContentToLinesForResumeImport(
  content: PdfTextContent,
  page: number,
): TextLine[] {
  // PDF.js exposes positioned text fragments, not logical lines. Rebuild lines
  // from the document's own font/width statistics so different templates do
  // not depend on a single fixed y-threshold or word-gap value.
  const items = (content.items ?? [])
    .filter((item) => typeof item.str === "string" && item.str.trim())
    .map<PositionedTextItem>((item) => {
      const transform = item.transform ?? [];
      return {
        text: String(item.str ?? "").trim(),
        x: Number(transform[4] ?? 0),
        y: Number(transform[5] ?? 0),
        fontSize: Math.abs(Number(transform[3] ?? item.height ?? 0)),
        width: Number(item.width ?? 0),
      };
    });

  const lineTolerance = estimateLineTolerance(items);
  const wordGap = estimateWordGap(items);
  const buckets = groupTextItemsByLine(items, lineTolerance);

  return buckets
    .flatMap((bucket) => splitLineBucketByColumnGap(bucket, wordGap))
    .map((bucket) => textItemBucketToLine(bucket, page, wordGap))
    .filter((line) => line.text)
    .sort((left, right) =>
      left.page === right.page
        ? right.y - left.y || left.x - right.x
        : left.page - right.page,
    );
}

function groupTextItemsByLine(
  items: PositionedTextItem[],
  lineTolerance: number,
) {
  const buckets: PositionedTextItem[][] = [];

  for (const item of items) {
    const bucket = buckets.find(
      (candidate) => Math.abs((candidate[0]?.y ?? item.y) - item.y) <= lineTolerance,
    );

    if (bucket) {
      bucket.push(item);
    } else {
      buckets.push([item]);
    }
  }

  return buckets;
}

function splitLineBucketByColumnGap(
  bucket: PositionedTextItem[],
  wordGap: number,
) {
  const sorted = [...bucket].sort((left, right) => left.x - right.x);
  const columnGap = Math.max(wordGap * MIN_COLUMN_GAP_WORDS, medianItemWidth(sorted));
  const lines: PositionedTextItem[][] = [];
  let current: PositionedTextItem[] = [];
  let previousEnd = 0;

  for (const item of sorted) {
    const gap = item.x - previousEnd;
    if (current.length > 0 && gap > columnGap) {
      lines.push(current);
      current = [];
    }

    current.push(item);
    previousEnd = item.x + item.width;
  }

  if (current.length > 0) {
    lines.push(current);
  }

  return lines;
}

function textItemBucketToLine(
  bucket: PositionedTextItem[],
  page: number,
  wordGap: number,
): TextLine {
  const sorted = bucket.sort((left, right) => left.x - right.x);
  const text = joinLineItems(sorted, wordGap);
  const averageFontSize =
    sorted.reduce((sum, item) => sum + item.fontSize, 0) / sorted.length;

  return {
    text,
    page,
    x: sorted[0]?.x ?? 0,
    y: median(sorted.map((item) => item.y)),
    fontSize: averageFontSize,
  };
}

function estimateLineTolerance(items: PositionedTextItem[]) {
  const fontSize = median(items.map((item) => item.fontSize).filter(Boolean));
  return Math.max(1, fontSize * 0.25);
}

function estimateWordGap(items: PositionedTextItem[]) {
  const widths = items
    .map((item) => item.width / Math.max(item.text.length, 1))
    .filter((width) => Number.isFinite(width) && width > 0);
  return Math.max(2, median(widths) * 0.8);
}

function medianItemWidth(items: PositionedTextItem[]) {
  return median(items.map((item) => item.width).filter((width) => width > 0));
}

function joinLineItems(
  items: Array<{ text: string; x: number; width: number }>,
  wordGap: number,
) {
  let line = "";
  let previousEnd = 0;
  for (const item of items) {
    const gap = item.x - previousEnd;
    const separator = line && gap > wordGap ? " " : "";
    line = `${line}${separator}${item.text}`;
    previousEnd = item.x + item.width;
  }

  return normalizeWhitespace(line);
}

export function buildResumeFromPdfLines(
  lines: TextLine[],
  fallbackSectionTitle: string,
  registry: SectionRegistryResponse,
): ResumeData {
  const registryContext = createSectionRegistryContext(registry);
  const plainLines = lines.map((line) => line.text).filter(Boolean);
  const sections = splitSections(lines, registryContext);
  const basicLines = linesBeforeFirstSection(plainLines, sections);
  const basic = extractBasicInfo(basicLines);
  const resolvedSections =
    sections.length > 0
      ? sections
      : [
          {
            rawTitle: fallbackSectionTitle,
            kind: "other" as const,
            confidence: 0,
            lines: plainLines.slice(basicLines.length).length > 0
              ? plainLines.slice(basicLines.length)
              : plainLines,
          },
        ];

  return {
    basic,
    sections: resolvedSections
      .map((section) =>
        sectionCandidateToResumeSection(section, registryContext),
      )
      .filter((section) => section.items.length > 0),
  };
}

function createSectionRegistryContext(
  registry: SectionRegistryResponse,
): SectionRegistryContext {
  return {
    kindByAlias: new Map(
      registry.sections.flatMap((section) =>
        section.aliases.map((alias) => [normalizeTitle(alias), section.kind]),
      ),
    ),
    defaultLayoutByKind: new Map(
      registry.sections.map((section) => [section.kind, section.defaultLayout]),
    ),
  };
}

function splitSections(
  lines: TextLine[],
  registryContext: SectionRegistryContext,
): SectionCandidate[] {
  const sections: SectionCandidate[] = [];
  let current: SectionCandidate | null = null;
  const bodyFontSize = median(lines.map((line) => line.fontSize).filter(Boolean));

  for (const [index, line] of lines.entries()) {
    const titleMatch = classifySectionTitle(line.text, registryContext);
    const inlineTitleMatch = splitInlineSectionTitle(line.text, registryContext);
    // A resume name is often the largest line on page one. Only treat font-size
    // signals as generic section headings after the contact block; explicit
    // aliases such as "项目经历" still match anywhere.
    const canUseFontHeading = index > GENERIC_SECTION_HEADING_SKIP_LINES;
    const looksLikeHeading =
      titleMatch.confidence > 0 ||
      Boolean(inlineTitleMatch) ||
      (canUseFontHeading &&
        line.fontSize > bodyFontSize * GENERIC_SECTION_HEADING_SCALE &&
        line.text.length <= MAX_GENERIC_SECTION_HEADING_CHARS);

    if (looksLikeHeading) {
      const sectionTitle = inlineTitleMatch?.title ?? line.text;
      const sectionKind = inlineTitleMatch?.match ?? titleMatch;
      current = {
        rawTitle: sectionTitle,
        kind: sectionKind.kind,
        confidence: sectionKind.confidence,
        lines: [],
      };
      if (inlineTitleMatch?.content) {
        current.lines.push(inlineTitleMatch.content);
      }
      sections.push(current);
      continue;
    }

    if (current) {
      current.lines.push(line.text);
    }
  }

  return sections.filter((section) => section.lines.length > 0);
}

function linesBeforeFirstSection(
  lines: string[],
  sections: SectionCandidate[],
): string[] {
  if (!sections[0]) {
    return lines.slice(0, CONTACT_SCAN_LINE_LIMIT);
  }

  const firstSectionIndex = lines.findIndex((line) => line === sections[0].rawTitle);
  return firstSectionIndex > 0
    ? lines.slice(0, firstSectionIndex)
    : lines.slice(0, CONTACT_SCAN_LINE_LIMIT);
}

function extractBasicInfo(lines: string[]) {
  const joined = lines.join(" ");
  const email = joined.match(EMAIL_PATTERN)?.[0] ?? "";
  const phone = joined.match(PHONE_PATTERN)?.[0]?.replace(/\s+/g, " ").trim() ?? "";
  const name = inferName(lines);
  const location = extractLocation(lines, name);

  return {
    name,
    headline: "",
    phone,
    email,
    location,
    avatar: "",
    summary: "",
    customFields: [],
  };
}

function extractLocation(lines: string[], name: string) {
  // Keep this conservative: a wrong full contact line is more damaging than
  // an empty location field. Candidate tokens are only considered after the
  // same contact line has already exposed an email, phone, or web token; this
  // avoids treating a headline before the contact details as a location.
  for (const line of contactLines(lines)) {
    let sawContactToken = false;
    const locationCandidates: string[] = [];
    const tokens = line
      .split(CONTACT_TOKEN_SEPARATOR)
      .map(stripLeadingContactLabel)
      .map(normalizeWhitespace)
      .filter(Boolean);

    for (const token of tokens) {
      if (looksLikeContactToken(token)) {
        sawContactToken = true;
        continue;
      }

      if (sawContactToken && looksLikeLocationToken(token, name)) {
        return token;
      }

      if (!sawContactToken && looksLikePrefixLocationToken(token, name)) {
        locationCandidates.push(token);
      }
    }

    if (locationCandidates.length === MAX_STANDALONE_LOCATION_TOKENS) {
      return locationCandidates[0] ?? "";
    }
  }

  return "";
}

function contactLines(lines: string[]) {
  return lines
    .slice(0, CONTACT_SCAN_LINE_LIMIT)
    .filter(
      (line) =>
        EMAIL_PATTERN.test(line) ||
        PHONE_PATTERN.test(line) ||
        looksLikeWebContactToken(line),
    );
}

function stripLeadingContactLabel(token: string) {
  const parts = token.split(/[:：]/);
  if (parts.length < 2) {
    return token;
  }

  const [label, ...rest] = parts;
  return looksLikeShortLabel(label ?? "") ? rest.join(":") : token;
}

function looksLikeShortLabel(value: string) {
  const normalized = normalizeWhitespace(value);
  return (
    normalized.length > 0 &&
    normalized.length <= MAX_SHORT_LABEL_CHARS &&
    !EMAIL_PATTERN.test(normalized) &&
    !PHONE_PATTERN.test(normalized) &&
    !DOMAIN_PATTERN.test(normalized)
  );
}

function looksLikeContactToken(value: string) {
  return (
    EMAIL_PATTERN.test(value) ||
    PHONE_PATTERN.test(value) ||
    looksLikeWebContactToken(value)
  );
}

function looksLikeWebContactToken(value: string) {
  const normalized = normalizeWhitespace(value);
  return (
    /^https?:\/\//i.test(normalized) ||
    /^www\./i.test(normalized) ||
    DOMAIN_PATTERN.test(normalized)
  );
}

function looksLikeLocationToken(token: string, name: string) {
  const normalized = normalizeWhitespace(token);
  if (!normalized || normalized === name) {
    return false;
  }

  if (
    EMAIL_PATTERN.test(normalized) ||
    PHONE_PATTERN.test(normalized) ||
    looksLikeWebContactToken(normalized)
  ) {
    return false;
  }

  if (/^\d+$/.test(normalized) || /[@/\\]/.test(normalized)) {
    return false;
  }

  const chineseText = normalized.replace(/\s+/g, "");
  if (
    chineseText.length >= MIN_CJK_LOCATION_CHARS &&
    chineseText.length <= MAX_CJK_LOCATION_CHARS &&
    /^[\p{Script=Han}]+$/u.test(chineseText)
  ) {
    return true;
  }

  return (
    normalized.length <= MAX_LOCATION_CHARS &&
    /^[A-Za-z][A-Za-z .'-]+$/.test(normalized) &&
    /\s/.test(normalized)
  );
}

function looksLikePrefixLocationToken(token: string, name: string) {
  const normalized = normalizeWhitespace(token);
  const chineseText = normalized.replace(/\s+/g, "");

  if (chineseText !== normalized) {
    return looksLikeLocationToken(normalized, name);
  }

  return (
    looksLikeLocationToken(normalized, name) &&
    /^[\p{Script=Han}]+$/u.test(chineseText) &&
    chineseText.length <= MAX_PREFIX_CJK_LOCATION_CHARS
  );
}

function inferName(lines: string[]) {
  for (const line of lines.slice(0, MAX_NAME_SCAN_LINES)) {
    const normalized = normalizeWhitespace(
      line
        .replace(/[|｜·•].*$/, "")
        .replace(new RegExp(EMAIL_PATTERN, "gi"), "")
        .replace(new RegExp(PHONE_PATTERN, "g"), ""),
    );
    const lower = normalized.toLowerCase();
    if (
      normalized &&
      normalized.length <= MAX_NAME_CHARS &&
      !NAME_BLOCKED_WORDS.has(lower) &&
      !/[：:]/.test(normalized)
    ) {
      return normalized;
    }
  }

  return "";
}

function sectionCandidateToResumeSection(
  candidate: SectionCandidate,
  registryContext: SectionRegistryContext,
): ResumeSection {
  const kind =
    candidate.confidence >= SECTION_KIND_CONFIDENCE_THRESHOLD
      ? candidate.kind
      : "other";
  const items = buildSectionItems(candidate.lines, kind);

  return {
    id: createId("section"),
    kind,
    layout: registryContext.defaultLayoutByKind.get(kind) ?? "timeline",
    customTitle: kind === "other" ? candidate.rawTitle : "",
    items,
  };
}

function buildSectionItems(lines: string[], kind: SectionKind): ResumeSectionItem[] {
  if (
    kind === "skills" ||
    kind === "languages" ||
    kind === "certificates" ||
    kind === "other"
  ) {
    return [
      buildItem({
        title: "",
        highlights: splitInlineList(lines.join(" ")).slice(0, MAX_IMPORTED_HIGHLIGHTS),
      }),
    ];
  }

  const groups = groupExperienceLines(lines);
  return groups.map((group) => groupToItem(group, kind)).filter(hasItemText);
}

function groupExperienceLines(lines: string[]) {
  // Experience-like sections usually contain a compact header followed by
  // bullets. Start a new item only after the current group has body evidence,
  // otherwise company, role, date, and degree lines get split too eagerly.
  const groups: ExperienceLine[][] = [];
  let current: ExperienceLine[] = [];
  const parsedLines = lines.map(parseExperienceLine).filter((line) => line.text);

  for (const [index, line] of parsedLines.entries()) {
    const startsNew =
      current.length > 0 &&
      shouldStartExperienceGroup(line, current, parsedLines[index + 1]);
    if (startsNew) {
      groups.push(current);
      current = [];
    }
    current.push(line);
  }

  if (current.length > 0) {
    groups.push(current);
  }

  return groups;
}

function parseExperienceLine(rawLine: string): ExperienceLine {
  const text = normalizeBulletLine(rawLine);
  return {
    text,
    isBullet: isBulletLine(rawLine),
    hasPeriod: looksLikePeriodLine(text),
  };
}

function shouldStartExperienceGroup(
  line: ExperienceLine,
  current: ExperienceLine[],
  nextLine: ExperienceLine | undefined,
) {
  // A new non-bullet heading after bullets is the clearest boundary between
  // adjacent experiences only when the following line confirms the header
  // shape. Otherwise a wrapped bullet continuation is too easy to split into a
  // bogus new item.
  if (
    !line.isBullet &&
    groupHasBullets(current) &&
    looksLikeItemHeading(line.text) &&
    nextLine?.hasPeriod
  ) {
    return true;
  }

  return line.hasPeriod && groupHasPeriod(current) && groupHasBullets(current);
}

function groupToItem(
  group: ExperienceLine[],
  kind: SectionKind,
): ResumeSectionItem {
  // Treat early compact lines as the item header and sentence-shaped lines as
  // highlights. This intentionally avoids content dictionaries such as tech
  // names or action verbs; structure is more stable across languages/domains.
  const lines = group.map((line) => line.text);
  const period = extractPeriod(lines);
  const headerLines: string[] = [];
  const highlightLines: string[] = [];

  for (const line of group) {
    const text = normalizeWhitespace(line.text.replace(period, ""));
    if (!text) {
      continue;
    }

    if (line.isBullet) {
      highlightLines.push(text);
      continue;
    }

    if (highlightLines.length > 0) {
      appendHighlightLine(highlightLines, text);
      continue;
    }

    if (headerLines.length < MAX_HEADER_LINES_PER_ITEM && !looksLikeHighlightLine(text)) {
      headerLines.push(text);
    } else {
      highlightLines.push(text);
    }
  }

  const item = headerLinesToItem(headerLines, kind);
  const highlights = highlightLines
    .filter(Boolean)
    .slice(0, MAX_IMPORTED_HIGHLIGHTS);

  return buildItem({
    ...item,
    period,
    highlights,
  });
}

function headerLinesToItem(
  headerLines: string[],
  kind: SectionKind,
): Partial<ResumeSectionItem> {
  // Field placement is best-effort. When the shape is unclear, preserve text in
  // subtitle/meta rather than dropping it or forcing a brittle semantic guess.
  if (kind === "education") {
    const meta = headerLines.find(looksLikeScoreMetaLine) ?? "";
    const remaining = headerLines.filter((line) => line !== meta);
    const title = pickMostLikelyTitleLine(remaining) ?? "";
    const subtitle = remaining.filter((line) => line !== title).join(" · ");
    return { title, subtitle, meta };
  }

  if (kind === "project") {
    const meta = headerLines.find(looksLikeListMetaLine) ?? "";
    const remaining = headerLines.filter((line) => line !== meta);
    const title = pickMostLikelyTitleLine(remaining) ?? "";
    const subtitle = remaining.filter((line) => line !== title).join(" · ");
    return { title, subtitle, meta };
  }

  const [titleLine, ...rest] = headerLines;
  const [title, inlineSubtitle] = splitTitleAndSubtitle(titleLine ?? "");
  return {
    title,
    subtitle: inlineSubtitle || rest[0] || "",
    meta: rest.slice(inlineSubtitle ? 0 : 1).join(" · "),
  };
}

function buildItem(overrides: Partial<ResumeSectionItem>): ResumeSectionItem {
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

function splitInlineSectionTitle(
  value: string,
  registryContext: SectionRegistryContext,
) {
  const match = value.match(/^(.{1,24}?)[：:]\s*(.+)$/);
  if (!match) {
    return null;
  }

  const [, title = "", content = ""] = match;
  const titleMatch = classifySectionTitle(title, registryContext);
  if (titleMatch.confidence === 0) {
    return null;
  }

  return {
    title: normalizeWhitespace(title),
    content: normalizeWhitespace(content),
    match: titleMatch,
  };
}

function classifySectionTitle(
  title: string,
  registryContext: SectionRegistryContext,
): ClassifiedSectionTitle {
  const normalized = normalizeTitle(title);
  const kind = registryContext.kindByAlias.get(normalized);
  if (kind) {
    return { kind, confidence: SECTION_TITLE_CONFIDENCE };
  }

  return { kind: "other", confidence: 0 };
}

function normalizeTitle(value: string) {
  return value.replace(/\s+/g, "").replace(/[：:]/g, "").toLowerCase();
}

function extractPeriod(lines: string[]) {
  const text = lines.join(" ");
  return (
    text.match(
      /(?:20\d{2}|19\d{2})[./年-]?\d{0,2}\s*(?:-|–|—|至|到)\s*(?:20\d{2}|19\d{2}|至今|今|现在|Present|Current)[./年-]?\d{0,2}/i,
    )?.[0] ?? ""
  );
}

function looksLikePeriodLine(line: string) {
  return Boolean(extractPeriod([line]));
}

function looksLikeItemHeading(line: string) {
  return line.length <= MAX_ITEM_HEADING_CHARS && !/[。；;]/.test(line);
}

function groupHasPeriod(group: ExperienceLine[]) {
  return group.some((line) => line.hasPeriod);
}

function groupHasBullets(group: ExperienceLine[]) {
  return group.some((line) => line.isBullet || looksLikeHighlightLine(line.text));
}

function looksLikeHighlightLine(line: string) {
  // Avoid content-word dictionaries here. A line is treated as body text only
  // when its shape looks like a sentence or a dense comma-separated statement.
  return (
    line.length > MIN_LONG_DESCRIPTION_CHARS ||
    /[。；;.]$/.test(line) ||
    countMatches(line, /[，,、]/g) >= MIN_DENSE_COMMA_COUNT
  );
}

function appendHighlightLine(highlights: string[], line: string) {
  if (looksLikeHighlightLine(line)) {
    highlights.push(line);
    return;
  }

  const lastIndex = highlights.length - 1;
  highlights[lastIndex] = normalizeWhitespace(`${highlights[lastIndex]} ${line}`);
}

function looksLikeScoreMetaLine(line: string) {
  // Education metadata is usually numeric even when labels vary by language.
  return (
    /\d/.test(line) &&
    (/\/|%|[()（）]/.test(line) ||
      countMatches(line, /\d/g) >= MIN_SCORE_DIGIT_COUNT)
  );
}

function looksLikeListMetaLine(line: string) {
  if (looksLikeHighlightLine(line)) {
    return false;
  }

  return splitInlineList(line).length >= MIN_LIST_META_PARTS || /[+/]/.test(line);
}

function pickMostLikelyTitleLine(lines: string[]) {
  return [...lines]
    .filter(Boolean)
    .sort((left, right) => titleLineScore(right) - titleLineScore(left))[0];
}

function titleLineScore(line: string) {
  let score = 0;
  if (/[\p{Script=Han}A-Za-z]/u.test(line)) {
    score += 3;
  }
  if (!looksLikeListMetaLine(line)) {
    score += 2;
  }
  if (!looksLikeHighlightLine(line)) {
    score += 2;
  }
  if (line.length <= MAX_TITLE_LINE_CHARS) {
    score += 1;
  }

  return score;
}

function hasItemText(item: ResumeSectionItem) {
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

function isBulletLine(line: string) {
  return /^[\s•·*●○◦▪▫-]+/.test(line);
}

function splitInlineList(value: string) {
  return value
    .split(/[，,、;；|｜+]/)
    .map(normalizeWhitespace)
    .filter(Boolean);
}

function countMatches(value: string, pattern: RegExp) {
  return value.match(pattern)?.length ?? 0;
}

function normalizeWhitespace(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function median(values: number[]) {
  if (values.length === 0) {
    return 10;
  }
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.floor(sorted.length / 2)] ?? 10;
}
