import { apiRoutes, requestApi } from "@/lib/api-client";
import { createId } from "@/lib/resume";
import { SECTION_KINDS } from "@/types/resume";
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
  dir?: string;
  transform?: number[];
  width?: number;
  height?: number;
};

type PdfTextContent = {
  items?: PdfTextItem[];
};

type PdfPage = {
  getTextContent(): Promise<PdfTextContent>;
  getViewport(params: { scale: number }): { width: number };
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
  pageWidth?: number;
  x: number;
  y: number;
  fontSize: number;
};

type SectionCandidate = {
  rawTitle: string;
  kind: SectionKind;
  confidence: number;
  startLineIndex: number;
  lines: TextLine[];
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

type ResumeImportLexiconLocale = {
  documentTitleTerms: string[];
  currentPeriodTerms: string[];
  dateRangeTerms: string[];
  datePartSeparators: string[];
  datePartSuffixes: string[];
};

type ResumeImportLexiconResponse = {
  locales: Record<string, ResumeImportLexiconLocale>;
};

type ResumeImportLexiconContext = {
  documentTitleTerms: Set<string>;
  periodPattern: RegExp;
};

type ResumeImportParserConfig = {
  registry: SectionRegistryResponse;
  lexicon: ResumeImportLexiconResponse;
};

type ExperienceLine = TextLine & {
  isBullet: boolean;
  hasPeriod: boolean;
};

type PositionedTextItem = {
  text: string;
  direction: "ltr" | "rtl";
  sourceIndex: number;
  x: number;
  y: number;
  fontSize: number;
  width: number;
};

type PdfResumeImportParserProfile = {
  text: {
    sectionKindConfidenceThreshold: number;
    contactScanLineLimit: number;
    genericSectionHeadingSkipLines: number;
    genericSectionHeadingScale: number;
    maxGenericSectionHeadingGraphemes: number;
    maxHeaderLinesPerItem: number;
    maxHeaderRowsPerItem: number;
    maxNameGraphemes: number;
    maxNameScanLines: number;
    maxTitleLineGraphemes: number;
    maxShortLabelGraphemes: number;
    maxInlineSectionLabelGraphemes: number;
    maxLocationGraphemes: number;
    standaloneLocationLookaheadLines: number;
    minCjkLocationGraphemes: number;
    maxCjkLocationGraphemes: number;
    maxPrefixCjkLocationGraphemes: number;
    minLongDescriptionGraphemes: number;
    minDenseCommaCount: number;
    minScoreDigitCount: number;
    minListMetaParts: number;
    maxStandaloneLocationTokens: number;
    maxDirectPeriodRowIndex: number;
    minMeaningfulLines: number;
    sectionTitleConfidence: number;
  };
  layout: {
    minColumnGapWords: number;
    minLineTolerance: number;
    lineToleranceScale: number;
    minWordGap: number;
    wordGapScale: number;
    headerRowToleranceScale: number;
    spaceGapScale: number;
    columnStartClusterScale: number;
    columnStartGapScale: number;
    minLeftColumnLines: number;
    minRightColumnLines: number;
    minRightColumnStartRatio: number;
    maxRightColumnStartRatio: number;
    minColumnVerticalOverlapScale: number;
    maxColumnBandGapScale: number;
    duplicatePositionToleranceScale: number;
    minDuplicatePositionTolerance: number;
    basicFieldLabelScale: number;
    listContinuationGapScale: number;
    listContinuationXScale: number;
  };
  dates: {
    minYear: number;
    maxYear: number;
  };
  scoring: {
    titleContainsText: number;
    titleIsNotListMetadata: number;
    titleIsNotBodyText: number;
    titleFitsLengthLimit: number;
  };
  fallbacks: {
    bodyFontSize: number;
  };
};

// These values tune the parser algorithm itself, so they are versioned with
// the implementation. User-language vocabulary lives in the backend lexicon;
// keeping geometry and structural thresholds here prevents remote config from
// drifting out of sync with the code that interprets it.
const PDF_IMPORT_PROFILE = {
  text: {
    sectionKindConfidenceThreshold: 0.75,
    contactScanLineLimit: 8,
    genericSectionHeadingSkipLines: 4,
    genericSectionHeadingScale: 1.15,
    maxGenericSectionHeadingGraphemes: 18,
    maxHeaderLinesPerItem: 4,
    maxHeaderRowsPerItem: 3,
    maxNameGraphemes: 32,
    maxNameScanLines: 5,
    maxTitleLineGraphemes: 32,
    maxShortLabelGraphemes: 16,
    maxInlineSectionLabelGraphemes: 24,
    maxLocationGraphemes: 32,
    standaloneLocationLookaheadLines: 2,
    minCjkLocationGraphemes: 2,
    maxCjkLocationGraphemes: 12,
    maxPrefixCjkLocationGraphemes: 4,
    minLongDescriptionGraphemes: 52,
    minDenseCommaCount: 2,
    minScoreDigitCount: 2,
    minListMetaParts: 3,
    maxStandaloneLocationTokens: 1,
    maxDirectPeriodRowIndex: 1,
    minMeaningfulLines: 2,
    sectionTitleConfidence: 0.95,
  },
  layout: {
    minColumnGapWords: 6,
    minLineTolerance: 1,
    lineToleranceScale: 0.25,
    minWordGap: 2,
    wordGapScale: 0.8,
    headerRowToleranceScale: 0.35,
    spaceGapScale: 0.25,
    columnStartClusterScale: 1.5,
    columnStartGapScale: 8,
    minLeftColumnLines: 5,
    minRightColumnLines: 8,
    minRightColumnStartRatio: 0.22,
    maxRightColumnStartRatio: 0.6,
    minColumnVerticalOverlapScale: 4,
    // Ordinary section spacing can be about four body lines. Only split when
    // the gap is large enough to plausibly contain an independent full-width
    // region; smaller gaps still belong to one compact two-column layout.
    maxColumnBandGapScale: 6,
    duplicatePositionToleranceScale: 0.08,
    minDuplicatePositionTolerance: 0.25,
    basicFieldLabelScale: 1.04,
    listContinuationGapScale: 2.4,
    listContinuationXScale: 0.75,
  },
  dates: {
    minYear: 1900,
    maxYear: 2100,
  },
  scoring: {
    titleContainsText: 3,
    titleIsNotListMetadata: 2,
    titleIsNotBodyText: 2,
    titleFitsLengthLimit: 1,
  },
  fallbacks: {
    bodyFontSize: 10,
  },
} as const satisfies PdfResumeImportParserProfile;

const CONTACT_TOKEN_SEPARATOR = /[|｜·•]/;
const EMAIL_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;
const PHONE_PATTERN = /(?:\+?\d[\d\s-]{6,}\d)/;
const YEAR_RANGE_PATTERN =
  /^\d{4}(?:0[1-9]|1[0-2])?\s*[-–—]\s*\d{4}(?:0[1-9]|1[0-2])?$/;
const DOMAIN_PATTERN = /\b[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\/\S*)?\b/i;
const WEB_CONTACT_PATTERN =
  /^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/\S*)?$/i;
const IMPORT_PARSER_CONFIG_CACHE_TTL_MS = 5 * 60 * 1000;
let resumeImportParserConfigCache:
  | {
      expiresAt: number;
      request: Promise<ResumeImportParserConfig>;
    }
  | undefined;
const GRAPHEME_SEGMENTER =
  typeof Intl.Segmenter === "function"
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;
const CJK_COMPATIBILITY_CHARACTER_PATTERN =
  /[\u2e80-\u2fff\uf900-\ufaff]/gu;
const CJK_RADICAL_TEXT_EQUIVALENTS: Readonly<Record<string, string>> = {
  // U+2EDA has no NFKC mapping, but Type3 fonts can expose it for the
  // simplified character "页". Treat this as text decoding, not vocabulary.
  "⻚": "页",
  // U+2EEC is similarly emitted for the simplified character "齐".
  "⻬": "齐",
};
const SECTION_KIND_SET = new Set<string>(SECTION_KINDS);

export async function importResumeFromPdf(
  file: File,
  fallbackSectionTitle: string,
): Promise<ResumeData> {
  const [lines, { registry, lexicon }] = await Promise.all([
    extractPdfLines(file),
    fetchResumeImportParserConfig(),
  ]);
  const text = lines.map((line) => line.text).join("\n").trim();

  if (!text || !hasMeaningfulResumeText(lines)) {
    throw new Error("PDF_IMPORT_NO_TEXT");
  }

  return buildResumeFromPdfLines(
    lines,
    fallbackSectionTitle,
    registry,
    lexicon,
  );
}

async function fetchResumeImportParserConfig(): Promise<ResumeImportParserConfig> {
  const now = Date.now();
  if (
    resumeImportParserConfigCache &&
    resumeImportParserConfigCache.expiresAt > now
  ) {
    return resumeImportParserConfigCache.request;
  }

  // These endpoints are immutable parser inputs during a frontend session.
  // Keep their cache independent from requestApi's mutation invalidation so
  // saving a resume or uploading a file does not trigger redundant refetches.
  const request = Promise.all([
    requestApi<unknown>(apiRoutes.sectionRegistry),
    requestApi<unknown>(apiRoutes.resumeImportLexicon),
  ]).then(([registry, lexicon]) =>
    parseResumeImportParserConfig(registry, lexicon),
  );
  resumeImportParserConfigCache = {
    expiresAt: now + IMPORT_PARSER_CONFIG_CACHE_TTL_MS,
    request,
  };

  try {
    return await request;
  } catch (error) {
    // A rejected promise must never poison subsequent import attempts.
    if (resumeImportParserConfigCache?.request === request) {
      resumeImportParserConfigCache = undefined;
    }
    throw error;
  }
}

function parseResumeImportParserConfig(
  registry: unknown,
  lexicon: unknown,
): ResumeImportParserConfig {
  if (
    !isRecord(registry) ||
    !Array.isArray(registry.sections) ||
    registry.sections.length === 0 ||
    !registry.sections.every(isSectionRegistryEntry) ||
    !isRecord(lexicon) ||
    !isRecord(lexicon.locales) ||
    Object.keys(lexicon.locales).length === 0 ||
    !Object.values(lexicon.locales).every(isResumeImportLexiconLocale)
  ) {
    throw new Error("INVALID_RESUME_IMPORT_PARSER_CONFIG");
  }

  const config = {
    registry: registry as SectionRegistryResponse,
    lexicon: lexicon as ResumeImportLexiconResponse,
  };
  // Validate cross-locale requirements before caching. This keeps a malformed
  // HTTP 200 response retryable instead of storing a promise that fails later
  // inside the parser for the entire cache lifetime.
  createSectionRegistryContext(config.registry);
  createResumeImportLexiconContext(config.lexicon);
  return config;
}

function isSectionRegistryEntry(value: unknown) {
  return (
    isRecord(value) &&
    typeof value.kind === "string" &&
    SECTION_KIND_SET.has(value.kind) &&
    (value.defaultLayout === "timeline" || value.defaultLayout === "list") &&
    isStringRecord(value.labels) &&
    isStringArray(value.aliases) &&
    value.aliases.length > 0
  );
}

function isResumeImportLexiconLocale(value: unknown) {
  return (
    isRecord(value) &&
    isStringArray(value.documentTitleTerms) &&
    isStringArray(value.currentPeriodTerms) &&
    isStringArray(value.dateRangeTerms) &&
    isStringArray(value.datePartSeparators) &&
    isStringArray(value.datePartSuffixes)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

function isStringRecord(value: unknown) {
  return (
    isRecord(value) &&
    Object.keys(value).length > 0 &&
    Object.entries(value).every(
      ([key, item]) => key.trim().length > 0 && isNonEmptyString(item),
    )
  );
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function hasMeaningfulResumeText(lines: TextLine[]) {
  const normalizedLines = lines
    .map((line) => normalizeMatchingText(line.text))
    .filter(Boolean);
  if (normalizedLines.some(looksLikeContactLine)) {
    return true;
  }

  return (
    normalizedLines.filter((line) => /\p{L}/u.test(line)).length >=
    PDF_IMPORT_PROFILE.text.minMeaningfulLines
  );
}

async function extractPdfLines(file: File): Promise<TextLine[]> {
  const pdfjs = await loadPdfJs();
  const buffer = await file.arrayBuffer();
  const document = await pdfjs.getDocument({ data: new Uint8Array(buffer) }).promise;
  const lines: TextLine[] = [];

  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const content = await page.getTextContent();
    const pageWidth = page.getViewport({ scale: 1 }).width;
    lines.push(
      ...textContentToLinesForResumeImport(content, pageNumber, pageWidth),
    );
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
  pageWidth = 0,
): TextLine[] {
  // PDF.js exposes positioned text fragments, not logical lines. Rebuild lines
  // from the document's own font/width statistics so different templates do
  // not depend on a single fixed y-threshold or word-gap value.
  const items = dedupePositionedTextItems(
    (content.items ?? [])
      .filter((item) => typeof item.str === "string" && item.str.trim())
      .map<PositionedTextItem>((item, sourceIndex) => {
        const transform = item.transform ?? [];
        return {
          text: String(item.str ?? "").trim(),
          direction: item.dir === "rtl" ? "rtl" : "ltr",
          sourceIndex,
          x: Number(transform[4] ?? 0),
          y: Number(transform[5] ?? 0),
          fontSize: resolveTextItemFontSize(item, transform),
          width: Number(item.width ?? 0),
        };
      }),
  );

  const lineTolerance = estimateLineTolerance(items);
  const wordGap = estimateWordGap(items);
  const buckets = groupTextItemsByLine(items, lineTolerance);

  const lines = buckets
    .flatMap((bucket) => {
      // Fragments in opposite columns often have baselines that differ by
      // 1-2pt. Once PDF.js has grouped them into one visual row, retain that
      // shared y-coordinate so right-side metadata cannot sort before the
      // left-side title later in the import pipeline.
      const visualRowY = median(bucket.map((item) => item.y));
      return splitLineBucketByColumnGap(bucket, wordGap).map((column) =>
        textItemBucketToLine(column, page, pageWidth, wordGap, visualRowY),
      );
    })
    .filter((line) => line.text);

  return orderLinesForReading(lines);
}

function dedupePositionedTextItems(items: PositionedTextItem[]) {
  const acceptedByText = new Map<string, PositionedTextItem[]>();
  return items.filter((item) => {
    // Hidden accessibility/text layers are often offset by a fraction of a
    // point from their visible counterpart. Compare only equal normalized text
    // within a font-relative coordinate tolerance; repeated authored text at a
    // different position must remain intact.
    const key = normalizeWhitespace(item.text);
    const accepted = acceptedByText.get(key) ?? [];
    const isDuplicate = accepted.some((candidate) => {
      const tolerance = Math.max(
        PDF_IMPORT_PROFILE.layout.minDuplicatePositionTolerance,
        Math.max(item.fontSize, candidate.fontSize) *
          PDF_IMPORT_PROFILE.layout.duplicatePositionToleranceScale,
      );
      return (
        Math.abs(item.x - candidate.x) <= tolerance &&
        Math.abs(item.y - candidate.y) <= tolerance
      );
    });
    if (isDuplicate) {
      return false;
    }

    accepted.push(item);
    acceptedByText.set(key, accepted);
    return true;
  });
}

function resolveTextItemFontSize(item: PdfTextItem, transform: number[]) {
  const reportedHeight = Math.abs(Number(item.height ?? 0));
  if (Number.isFinite(reportedHeight) && reportedHeight > 0) {
    return reportedHeight;
  }

  // Rotated text can have a zero vertical scale component. The two basis-vector
  // lengths recover the rendered size without assuming a particular rotation.
  const horizontalScale = Math.hypot(
    Number(transform[0] ?? 0),
    Number(transform[1] ?? 0),
  );
  const verticalScale = Math.hypot(
    Number(transform[2] ?? 0),
    Number(transform[3] ?? 0),
  );
  return Math.max(horizontalScale, verticalScale);
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
  const columnGap =
    wordGap * PDF_IMPORT_PROFILE.layout.minColumnGapWords;
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
  pageWidth: number,
  wordGap: number,
  visualRowY: number,
): TextLine {
  const direction = dominantTextDirection(bucket);
  const sorted = [...bucket].sort((left, right) =>
    direction === "rtl" ? right.x - left.x : left.x - right.x,
  );
  const text = joinLineItems(sorted, wordGap, direction);
  const averageFontSize =
    sorted.reduce((sum, item) => sum + item.fontSize, 0) / sorted.length;

  return {
    text,
    page,
    pageWidth: pageWidth > 0 ? pageWidth : undefined,
    x: Math.min(...sorted.map((item) => item.x)),
    y: visualRowY,
    fontSize: averageFontSize,
  };
}

function dominantTextDirection(items: PositionedTextItem[]) {
  const directionWeights = items.reduce(
    (weights, item) => {
      weights[item.direction] += countTextGraphemes(item.text);
      return weights;
    },
    { ltr: 0, rtl: 0 },
  );
  if (directionWeights.rtl !== directionWeights.ltr) {
    return directionWeights.rtl > directionWeights.ltr ? "rtl" : "ltr";
  }

  // Equal visible-text weights are uncommon, but choosing the first authored
  // token keeps mixed-direction lines stable instead of always forcing LTR.
  return (
    [...items]
      .sort((left, right) => left.sourceIndex - right.sourceIndex)
      .find((item) => countTextGraphemes(item.text) > 0)?.direction ?? "ltr"
  );
}

function estimateLineTolerance(items: PositionedTextItem[]) {
  const fontSize = median(items.map((item) => item.fontSize).filter(Boolean));
  return Math.max(
    PDF_IMPORT_PROFILE.layout.minLineTolerance,
    fontSize * PDF_IMPORT_PROFILE.layout.lineToleranceScale,
  );
}

function estimateWordGap(items: PositionedTextItem[]) {
  const widths = items
    .map(
      (item) =>
        item.width / Math.max(countTextGraphemes(item.text), 1),
    )
    .filter((width) => Number.isFinite(width) && width > 0);
  return Math.max(
    PDF_IMPORT_PROFILE.layout.minWordGap,
    median(widths) * PDF_IMPORT_PROFILE.layout.wordGapScale,
  );
}

function joinLineItems(
  items: Array<{ text: string; x: number; width: number }>,
  wordGap: number,
  direction: "ltr" | "rtl",
) {
  let line = "";
  let previousItem: { text: string; x: number; width: number } | null = null;
  for (const item of items) {
    const gap = previousItem
      ? direction === "rtl"
        ? previousItem.x - (item.x + item.width)
        : item.x - (previousItem.x + previousItem.width)
      : 0;
    // PDF.js preserves the physical width of an authored space but often
    // splits the text immediately around it. That width is much smaller than
    // the conservative threshold used to detect separate columns, so use a
    // dedicated threshold when reconstructing readable line text.
    const separator =
      line &&
      previousItem &&
      shouldSeparateTextItems(previousItem, item, gap, wordGap)
        ? " "
        : "";
    line = `${line}${separator}${item.text}`;
    previousItem = item;
  }

  return normalizeWhitespace(line);
}

function shouldSeparateTextItems(
  previous: { text: string },
  current: { text: string },
  gap: number,
  wordGap: number,
) {
  if (
    gap <=
    Math.max(
      PDF_IMPORT_PROFILE.layout.minLineTolerance,
      wordGap * PDF_IMPORT_PROFILE.layout.spaceGapScale,
    )
  ) {
    return false;
  }

  const previousText = normalizePdfCompatibilityCharacters(previous.text);
  const currentText = normalizePdfCompatibilityCharacters(current.text);
  // PDF.js can emit punctuation as a separate token whose bounding box starts
  // after a small visual gap. Unicode punctuation still belongs to the
  // adjacent text, so do not turn that glyph positioning into an authored
  // space (for example, `语言 ：` instead of `语言：`).
  if (
    /^(?:[\p{Pe}\p{Pf}\p{M}]|[,.;:!?，。；：！？、%％])/u.test(
      currentText,
    ) ||
    /[\p{Ps}\p{Pi}]$/u.test(previousText)
  ) {
    return false;
  }
  // Some embedded fonts expose every Han glyph as a separate PDF.js token
  // whose advance is slightly wider than its reported box. A visual gap there
  // is glyph positioning, not an authored word separator.
  if (
    isSingleHanGrapheme(previousText) &&
    isSingleHanGrapheme(currentText)
  ) {
    return false;
  }

  return true;
}

function orderLinesForReading(lines: TextLine[]) {
  const pages = new Map<number, TextLine[]>();
  for (const line of lines) {
    const pageLines = pages.get(line.page) ?? [];
    pageLines.push(line);
    pages.set(line.page, pageLines);
  }

  return [...pages.entries()]
    .sort(([leftPage], [rightPage]) => leftPage - rightPage)
    .flatMap(([, pageLines]) => orderPageLinesForReading(pageLines));
}

function orderPageLinesForReading(lines: TextLine[]) {
  const visualOrder = sortLinesTopToBottom(lines);
  if (
    lines.length <
    PDF_IMPORT_PROFILE.layout.minLeftColumnLines +
      PDF_IMPORT_PROFILE.layout.minRightColumnLines
  ) {
    return visualOrder;
  }

  const bodyFontSize = median(lines.map((line) => line.fontSize).filter(Boolean));
  const clusterTolerance =
    bodyFontSize * PDF_IMPORT_PROFILE.layout.columnStartClusterScale;
  const clusters = clusterLineStarts(lines, clusterTolerance);
  const minimumX = Math.min(...lines.map((line) => line.x));
  const maximumX = Math.max(...lines.map((line) => line.x));
  const measuredPageWidths = lines
    .map((line) => line.pageWidth ?? 0)
    .filter((width) => width > 0);
  const pageWidth =
    measuredPageWidths.length > 0
      ? median(measuredPageWidths)
      : maximumX - minimumX;

  // A real body column repeats the same x start over many rows. Right-aligned
  // dates and scores occur at several unrelated x positions, so they do not
  // form a large cluster and remain in normal visual-row order.
  const rightColumn = clusters.find(
    (cluster) =>
      cluster.lines.length >=
        PDF_IMPORT_PROFILE.layout.minRightColumnLines &&
      cluster.center - minimumX >=
        bodyFontSize * PDF_IMPORT_PROFILE.layout.columnStartGapScale &&
      cluster.center - minimumX >=
        pageWidth * PDF_IMPORT_PROFILE.layout.minRightColumnStartRatio &&
      cluster.center - minimumX <=
        pageWidth * PDF_IMPORT_PROFILE.layout.maxRightColumnStartRatio,
  );
  if (!rightColumn) {
    return visualOrder;
  }

  const provenBands = splitColumnLinesIntoBands(
    rightColumn.lines,
    bodyFontSize,
  )
    .filter(
      (rightLines) =>
        rightLines.length >= PDF_IMPORT_PROFILE.layout.minRightColumnLines,
    )
    .map((rightLines) =>
      createProvenColumnBand(
        lines,
        rightLines,
        rightColumn.center - clusterTolerance,
        bodyFontSize,
      ),
    )
    .filter((band): band is ProvenColumnBand => band !== null)
    .sort((left, right) => right.top - left.top);
  if (provenBands.length === 0) {
    return visualOrder;
  }

  // A page may contain multiple independent two-column regions separated by
  // full-width content. Reorder each proven band independently so content
  // between those regions keeps its visual position.
  let remaining = visualOrder;
  const ordered: TextLine[] = [];
  for (const band of provenBands) {
    ordered.push(...remaining.filter((line) => line.y > band.top));
    ordered.push(...sortLinesTopToBottom(band.leftLines));
    ordered.push(...sortLinesTopToBottom(band.rightLines));
    remaining = remaining.filter((line) => line.y < band.bottom);
  }
  return [...ordered, ...remaining];
}

type ProvenColumnBand = {
  top: number;
  bottom: number;
  leftLines: TextLine[];
  rightLines: TextLine[];
};

function splitColumnLinesIntoBands(
  lines: TextLine[],
  bodyFontSize: number,
) {
  const sorted = sortLinesTopToBottom(lines);
  const maximumGap =
    bodyFontSize * PDF_IMPORT_PROFILE.layout.maxColumnBandGapScale;
  const bands: TextLine[][] = [];
  let current: TextLine[] = [];

  for (const line of sorted) {
    const previous = current.at(-1);
    if (previous && previous.y - line.y > maximumGap) {
      bands.push(current);
      current = [];
    }
    current.push(line);
  }
  if (current.length > 0) {
    bands.push(current);
  }

  return bands;
}

function createProvenColumnBand(
  lines: TextLine[],
  rightLines: TextLine[],
  boundary: number,
  bodyFontSize: number,
): ProvenColumnBand | null {
  const padding =
    bodyFontSize * PDF_IMPORT_PROFILE.layout.headerRowToleranceScale;
  const top = Math.max(...rightLines.map((line) => line.y)) + padding;
  const bottom = Math.min(...rightLines.map((line) => line.y)) - padding;
  const bandLines = lines.filter((line) => line.y <= top && line.y >= bottom);
  const leftLines = bandLines.filter((line) => line.x < boundary);
  const resolvedRightLines = bandLines.filter((line) => line.x >= boundary);

  if (
    leftLines.length < PDF_IMPORT_PROFILE.layout.minLeftColumnLines ||
    resolvedRightLines.length <
      PDF_IMPORT_PROFILE.layout.minRightColumnLines ||
    !columnsShareVerticalRange(leftLines, resolvedRightLines, bodyFontSize)
  ) {
    return null;
  }

  return { top, bottom, leftLines, rightLines: resolvedRightLines };
}

function clusterLineStarts(lines: TextLine[], tolerance: number) {
  const sorted = [...lines].sort((left, right) => left.x - right.x);
  const clusters: Array<{ center: number; lines: TextLine[] }> = [];

  for (const line of sorted) {
    const current = clusters.at(-1);
    if (current && Math.abs(line.x - current.center) <= tolerance) {
      current.lines.push(line);
      current.center = median(current.lines.map((candidate) => candidate.x));
    } else {
      clusters.push({ center: line.x, lines: [line] });
    }
  }

  return clusters;
}

function columnsShareVerticalRange(
  leftLines: TextLine[],
  rightLines: TextLine[],
  bodyFontSize: number,
) {
  const leftTop = Math.max(...leftLines.map((line) => line.y));
  const leftBottom = Math.min(...leftLines.map((line) => line.y));
  const rightTop = Math.max(...rightLines.map((line) => line.y));
  const rightBottom = Math.min(...rightLines.map((line) => line.y));
  const overlap =
    Math.min(leftTop, rightTop) - Math.max(leftBottom, rightBottom);
  return (
    overlap >=
    bodyFontSize *
      PDF_IMPORT_PROFILE.layout.minColumnVerticalOverlapScale
  );
}

function sortLinesTopToBottom(lines: TextLine[]) {
  return [...lines].sort(
    (left, right) => right.y - left.y || left.x - right.x,
  );
}

export function buildResumeFromPdfLines(
  lines: TextLine[],
  fallbackSectionTitle: string,
  registry: SectionRegistryResponse,
  lexicon: ResumeImportLexiconResponse,
): ResumeData {
  const registryContext = createSectionRegistryContext(registry);
  const lexiconContext = createResumeImportLexiconContext(lexicon);
  const normalizedLines = orderLinesForReading(
    lines
      .map((line) => ({
        ...line,
        text: normalizeWhitespace(line.text),
      }))
      .filter((line) => line.text),
  );
  const sections = splitSections(
    normalizedLines,
    registryContext,
    lexiconContext,
  );
  const basicLines = linesBeforeFirstSection(normalizedLines, sections);
  const basic = extractBasicInfo(basicLines, lexiconContext);
  const resolvedSections =
    sections.length > 0
      ? sections
      : [
          {
            rawTitle: fallbackSectionTitle,
            kind: "other" as const,
            confidence: 0,
            startLineIndex: basicLines.length,
            lines: normalizedLines.slice(basicLines.length).length > 0
              ? normalizedLines.slice(basicLines.length)
              : normalizedLines,
          },
        ];

  return {
    basic,
    sections: resolvedSections
      .map((section) =>
        sectionCandidateToResumeSection(
          section,
          registryContext,
          lexiconContext,
        ),
      )
      .filter((section) => section.items.length > 0),
  };
}

function createSectionRegistryContext(
  registry: SectionRegistryResponse,
): SectionRegistryContext {
  const kindByAlias = new Map<string, SectionKind>();
  const defaultLayoutByKind = new Map<SectionKind, SectionLayout>();

  for (const section of registry.sections) {
    if (defaultLayoutByKind.has(section.kind)) {
      throw new Error("INVALID_RESUME_IMPORT_PARSER_CONFIG");
    }
    defaultLayoutByKind.set(section.kind, section.defaultLayout);

    for (const alias of section.aliases) {
      const normalizedAlias = normalizeTitle(alias);
      const existingKind = kindByAlias.get(normalizedAlias);
      if (!normalizedAlias || existingKind !== undefined) {
        throw new Error("INVALID_RESUME_IMPORT_PARSER_CONFIG");
      }
      kindByAlias.set(normalizedAlias, section.kind);
    }
  }

  if (SECTION_KINDS.some((kind) => !defaultLayoutByKind.has(kind))) {
    throw new Error("INVALID_RESUME_IMPORT_PARSER_CONFIG");
  }

  return {
    kindByAlias,
    defaultLayoutByKind,
  };
}

function createResumeImportLexiconContext(
  lexicon: ResumeImportLexiconResponse,
): ResumeImportLexiconContext {
  // A resume can use a different language from the current UI. Merge every
  // backend locale so parsing never depends on the user's display language.
  const localeLexicons = Object.values(lexicon.locales);
  const documentTitleTerms = new Set(
    localeLexicons
      .flatMap((locale) => locale.documentTitleTerms)
      .map(normalizeLexiconTerm),
  );
  const currentPeriodTerms = localeLexicons.flatMap(
    (locale) => locale.currentPeriodTerms,
  );
  const dateRangeTerms = localeLexicons.flatMap(
    (locale) => locale.dateRangeTerms,
  );
  const datePartSeparators = localeLexicons.flatMap(
    (locale) => locale.datePartSeparators,
  );
  const datePartSuffixes = localeLexicons.flatMap(
    (locale) => locale.datePartSuffixes,
  );

  if (documentTitleTerms.size === 0 || currentPeriodTerms.length === 0) {
    throw new Error("INVALID_RESUME_IMPORT_LEXICON");
  }

  return {
    documentTitleTerms,
    periodPattern: buildPeriodPattern({
      currentPeriodTerms,
      dateRangeTerms,
      datePartSeparators,
      datePartSuffixes,
    }),
  };
}

function splitSections(
  lines: TextLine[],
  registryContext: SectionRegistryContext,
  lexiconContext: ResumeImportLexiconContext,
): SectionCandidate[] {
  const sections: SectionCandidate[] = [];
  let current: SectionCandidate | null = null;
  const bodyFontSize = median(lines.map((line) => line.fontSize).filter(Boolean));

  for (const [index, line] of lines.entries()) {
    const titleMatch = classifySectionTitle(line.text, registryContext);
    const inlineTitleMatch = splitInlineSectionTitle(line.text, registryContext);
    // A generic list section commonly contains labeled rows such as
    // "技能：..." and "语言：...". Once that outer section is established,
    // keep those rows as editable list items instead of silently replacing the
    // source structure with multiple inferred sections.
    const keepsInlineListItem =
      current !== null &&
      isListSectionKind(current.kind) &&
      inlineTitleMatch !== null &&
      isListSectionKind(inlineTitleMatch.match.kind) &&
      line.fontSize <=
        bodyFontSize *
          PDF_IMPORT_PROFILE.text.genericSectionHeadingScale;
    const effectiveInlineTitleMatch: ReturnType<
      typeof splitInlineSectionTitle
    > = keepsInlineListItem ? null : inlineTitleMatch;
    // A resume name is often the largest line on page one. Only treat font-size
    // signals as generic section headings after the contact block; explicit
    // localized aliases from the backend section registry still match anywhere.
    const canUseFontHeading =
      index > PDF_IMPORT_PROFILE.text.genericSectionHeadingSkipLines;
    const isFontOnlyHeading =
      canUseFontHeading &&
      line.fontSize >
        bodyFontSize *
          PDF_IMPORT_PROFILE.text.genericSectionHeadingScale &&
      countTextGraphemes(line.text) <=
        PDF_IMPORT_PROFILE.text.maxGenericSectionHeadingGraphemes;
    const keepsExperienceItemHeader =
      current !== null &&
      !isListSectionKind(current.kind) &&
      titleMatch.confidence === 0 &&
      effectiveInlineTitleMatch === null &&
      isFontOnlyHeading &&
      looksLikeDatedExperienceHeader(lines, index, lexiconContext);
    const looksLikeHeading =
      titleMatch.confidence > 0 ||
      Boolean(effectiveInlineTitleMatch) ||
      (isFontOnlyHeading && !keepsExperienceItemHeader);

    if (looksLikeHeading) {
      const sectionTitle: string =
        effectiveInlineTitleMatch?.title ?? line.text;
      const sectionKind: ClassifiedSectionTitle =
        effectiveInlineTitleMatch?.match ?? titleMatch;
      current = {
        rawTitle: sectionTitle,
        kind: sectionKind.kind,
        confidence: sectionKind.confidence,
        startLineIndex: index,
        lines: [],
      };
      if (effectiveInlineTitleMatch?.content) {
        current.lines.push({
          ...line,
          text: effectiveInlineTitleMatch.content,
        });
      }
      sections.push(current);
      continue;
    }

    if (current) {
      current.lines.push(line);
    }
  }

  return sections.filter((section) => section.lines.length > 0);
}

function looksLikeDatedExperienceHeader(
  lines: TextLine[],
  startIndex: number,
  lexiconContext: ResumeImportLexiconContext,
) {
  for (const line of lines.slice(
    startIndex,
    startIndex + PDF_IMPORT_PROFILE.text.maxHeaderRowsPerItem,
  )) {
    if (isBulletLine(line.text) || looksLikeHighlightLine(line.text)) {
      return false;
    }
    if (looksLikePeriodLine(line.text, lexiconContext)) {
      return true;
    }
  }
  return false;
}

function linesBeforeFirstSection(
  lines: TextLine[],
  sections: SectionCandidate[],
): TextLine[] {
  if (!sections[0]) {
    return lines.slice(
      0,
      PDF_IMPORT_PROFILE.text.contactScanLineLimit,
    );
  }

  return lines.slice(0, sections[0].startLineIndex);
}

function extractBasicInfo(
  lines: TextLine[],
  lexiconContext: ResumeImportLexiconContext,
) {
  const rawTextLines = lines.map((line) => line.text);
  const name = inferName(rawTextLines, lexiconContext);
  const bodyFontSize = median(lines.map((line) => line.fontSize).filter(Boolean));
  const semanticLines = lines.filter(
    (line) =>
      !looksLikeBasicFieldLabel(
        line,
        name,
        bodyFontSize,
        lexiconContext,
      ),
  );
  const textLines = semanticLines.map((line) => line.text);
  const joined = normalizeMatchingText(textLines.join(" "));
  const email = joined.match(EMAIL_PATTERN)?.[0] ?? "";
  const phone = extractPhone(
    textLines.slice(0, PDF_IMPORT_PROFILE.text.contactScanLineLimit),
  );
  const location = extractLocation(
    lines,
    name,
    bodyFontSize,
    lexiconContext,
  );
  const nameIndex = textLines.findIndex((line) => line === name);
  const contactIndexes = textLines
    .map((line, index) => (looksLikeContactLine(line) ? index : -1))
    .filter((index) => index >= 0);
  const firstContactIndex = contactIndexes[0] ?? -1;
  const lastContactIndex = contactIndexes.at(-1) ?? -1;
  const headline =
    firstContactIndex > nameIndex + 1
      ? joinWrappedLines(textLines.slice(nameIndex + 1, firstContactIndex))
      : "";
  const summaryLines =
    lastContactIndex >= 0 ? textLines.slice(lastContactIndex + 1) : [];
  const locationIndex = summaryLines.findIndex((line) => line === location);
  if (locationIndex >= 0) {
    summaryLines.splice(locationIndex, 1);
  }
  const summary = joinWrappedLines(summaryLines);

  return {
    name,
    headline,
    phone,
    email,
    location,
    avatar: "",
    summary,
    customFields: extractCustomContactFields(textLines),
  };
}

function looksLikeContactLine(line: string) {
  const normalized = normalizeMatchingText(line);
  return (
    EMAIL_PATTERN.test(normalized) ||
    looksLikePhoneToken(normalized) ||
    line
      .split(CONTACT_TOKEN_SEPARATOR)
      .map(stripLeadingContactLabel)
      .some(looksLikeWebContactToken)
  );
}

function extractCustomContactFields(lines: string[]) {
  const fields: Array<{
    id: string;
    type: "url";
    label: string;
    value: string;
  }> = [];
  const seen = new Set<string>();

  for (const line of lines.slice(
    0,
    PDF_IMPORT_PROFILE.text.contactScanLineLimit,
  )) {
    const tokens = line
      .split(CONTACT_TOKEN_SEPARATOR)
      .map(normalizeWhitespace)
      .filter(Boolean);

    for (const token of tokens) {
      const isBareWebContact = looksLikeWebContactToken(token);
      const labeledValue = isBareWebContact
        ? null
        : splitLabeledValue(
            token,
            PDF_IMPORT_PROFILE.text.maxShortLabelGraphemes,
          );
      const label = isBareWebContact
        ? deriveWebContactLabel(token)
        : labeledValue?.label ?? "";
      const value = isBareWebContact ? token : labeledValue?.value ?? "";
      const normalizedValue = normalizeMatchingText(value);
      const dedupeKey = normalizedValue.toLowerCase();
      if (
        (!isBareWebContact && !looksLikeShortLabel(label)) ||
        !looksLikeWebContactToken(normalizedValue) ||
        seen.has(dedupeKey)
      ) {
        continue;
      }

      seen.add(dedupeKey);
      fields.push({
        id: createId("field"),
        type: "url",
        label,
        value: normalizedValue,
      });
    }
  }

  return fields;
}

function extractPhone(lines: string[]) {
  const matcher = new RegExp(PHONE_PATTERN.source, "g");
  for (const line of lines) {
    const normalized = normalizeMatchingText(line);
    for (const match of normalized.matchAll(matcher)) {
      const candidate = normalizeWhitespace(match[0] ?? "");
      if (looksLikePhoneToken(candidate)) {
        return candidate;
      }
    }
  }
  return "";
}

function looksLikePhoneToken(value: string) {
  const normalized = normalizeMatchingText(value).trim();
  const candidate = normalized.match(PHONE_PATTERN)?.[0]?.trim() ?? "";
  return Boolean(candidate) && !YEAR_RANGE_PATTERN.test(candidate);
}

function deriveWebContactLabel(value: string) {
  const normalized = normalizeMatchingText(value);
  try {
    const url = new URL(
      /^https?:\/\//i.test(normalized)
        ? normalized
        : `https://${normalized}`,
    );
    return url.hostname.replace(/^www\./i, "") || normalized;
  } catch {
    return normalized.split(/[/?#]/, 1)[0] ?? normalized;
  }
}

function joinWrappedLines(lines: string[]) {
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
      /[\p{Script=Han}]$/u.test(result) &&
      /^[\p{Script=Han}]/u.test(normalized)
        ? ""
        : " ";
    return `${result}${separator}${normalized}`;
  }, "");
}

function extractLocation(
  lines: TextLine[],
  name: string,
  bodyFontSize: number,
  lexiconContext: ResumeImportLexiconContext,
) {
  // Keep this conservative: a wrong full contact line is more damaging than
  // an empty location field. Candidate tokens are only considered after the
  // same contact line has already exposed an email, phone, or web token; this
  // avoids treating a headline before the contact details as a location.
  for (const line of contactLines(lines)) {
    let sawContactToken = false;
    const locationCandidates: string[] = [];
    const tokens = line.text
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

    if (
      locationCandidates.length ===
      PDF_IMPORT_PROFILE.text.maxStandaloneLocationTokens
    ) {
      return locationCandidates[0] ?? "";
    }
  }

  const lastContactIndex = lines.findLastIndex((line) =>
    looksLikeContactLine(line.text),
  );
  if (lastContactIndex >= 0) {
    const candidates = lines.slice(
      lastContactIndex + 1,
      lastContactIndex +
        1 +
        PDF_IMPORT_PROFILE.text.standaloneLocationLookaheadLines,
    );
    for (const [index, line] of candidates.entries()) {
      const nextLine = candidates[index + 1];
      if (
        looksLikeLocationToken(line.text, name) &&
        (isStrongStandaloneLocation(line.text) ||
          (nextLine !== undefined &&
            looksLikeBasicFieldLabel(
              nextLine,
              name,
              bodyFontSize,
              lexiconContext,
            )))
      ) {
        return line.text;
      }
    }
  }

  return "";
}

function contactLines(lines: TextLine[]) {
  return lines
    .slice(0, PDF_IMPORT_PROFILE.text.contactScanLineLimit)
    .filter((line) => looksLikeContactLine(line.text));
}

function looksLikeBasicFieldLabel(
  line: TextLine,
  name: string,
  bodyFontSize: number,
  lexiconContext: ResumeImportLexiconContext,
) {
  return (
    line.text !== name &&
    countTextGraphemes(line.text) <=
      PDF_IMPORT_PROFILE.text.maxShortLabelGraphemes &&
    line.fontSize >=
      bodyFontSize * PDF_IMPORT_PROFILE.layout.basicFieldLabelScale &&
    !looksLikeContactLine(line.text) &&
    !looksLikePeriodLine(line.text, lexiconContext)
  );
}

function isStrongStandaloneLocation(value: string) {
  const normalized = normalizeWhitespace(value);
  const cjkText = normalized.replace(/\s+/g, "");
  return (
    /[/,，]/.test(normalized) ||
    (countTextGraphemes(cjkText) >=
      PDF_IMPORT_PROFILE.text.minCjkLocationGraphemes &&
      countTextGraphemes(cjkText) <=
        PDF_IMPORT_PROFILE.text.maxPrefixCjkLocationGraphemes &&
      /^[\p{Script=Han}]+$/u.test(cjkText))
  );
}

function stripLeadingContactLabel(token: string) {
  if (/^https?:\/\//i.test(token)) {
    return token;
  }

  const parts = token.split(/[:：]/);
  if (parts.length < 2) {
    return token;
  }

  const [label, ...rest] = parts;
  return looksLikeShortLabel(label ?? "") ? rest.join(":") : token;
}

function looksLikeShortLabel(value: string) {
  const normalized = normalizeWhitespace(value);
  const matchingText = normalizeMatchingText(normalized);
  return (
    countTextGraphemes(normalized) > 0 &&
    countTextGraphemes(normalized) <=
      PDF_IMPORT_PROFILE.text.maxShortLabelGraphemes &&
    !EMAIL_PATTERN.test(matchingText) &&
    !looksLikePhoneToken(matchingText) &&
    !DOMAIN_PATTERN.test(matchingText)
  );
}

function looksLikeContactToken(value: string) {
  const normalized = normalizeMatchingText(value);
  return (
    EMAIL_PATTERN.test(normalized) ||
    looksLikePhoneToken(normalized) ||
    looksLikeWebContactToken(normalized)
  );
}

function looksLikeWebContactToken(value: string) {
  const normalized = normalizeMatchingText(value);
  return (
    /^https?:\/\//i.test(normalized) ||
    /^www\./i.test(normalized) ||
    WEB_CONTACT_PATTERN.test(normalized)
  );
}

function looksLikeLocationToken(token: string, name: string) {
  const normalized = normalizeWhitespace(token);
  const matchingText = normalizeMatchingText(normalized);
  if (!normalized || normalized === name) {
    return false;
  }

  if (
    EMAIL_PATTERN.test(matchingText) ||
    looksLikePhoneToken(matchingText) ||
    looksLikeWebContactToken(matchingText)
  ) {
    return false;
  }

  if (/^\d+$/.test(normalized) || /[@\\]/.test(normalized)) {
    return false;
  }

  const chineseText = normalized.replace(/\s+/g, "");
  if (
    countTextGraphemes(chineseText) >=
      PDF_IMPORT_PROFILE.text.minCjkLocationGraphemes &&
    countTextGraphemes(chineseText) <=
      PDF_IMPORT_PROFILE.text.maxCjkLocationGraphemes &&
    /^[\p{Script=Han}]+$/u.test(chineseText)
  ) {
    return true;
  }

  return (
    countTextGraphemes(normalized) <=
      PDF_IMPORT_PROFILE.text.maxLocationGraphemes &&
    /^[\p{L}\p{M}][\p{L}\p{M} .,'’/-]+$/u.test(normalized) &&
    /[\s/,，]/.test(normalized)
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
    countTextGraphemes(chineseText) <=
      PDF_IMPORT_PROFILE.text.maxPrefixCjkLocationGraphemes
  );
}

function inferName(
  lines: string[],
  lexiconContext: ResumeImportLexiconContext,
) {
  for (const line of lines.slice(
    0,
    PDF_IMPORT_PROFILE.text.maxNameScanLines,
  )) {
    const normalized = normalizeMatchingText(
      line
        .replace(/[|｜·•].*$/, "")
        .replace(new RegExp(EMAIL_PATTERN, "gi"), "")
        .replace(new RegExp(PHONE_PATTERN, "g"), ""),
    );
    const normalizedTerm = normalizeLexiconTerm(normalized);
    if (
      normalized &&
      countTextGraphemes(normalized) <=
        PDF_IMPORT_PROFILE.text.maxNameGraphemes &&
      !lexiconContext.documentTitleTerms.has(normalizedTerm) &&
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
  lexiconContext: ResumeImportLexiconContext,
): ResumeSection {
  const kind =
    candidate.confidence >=
    PDF_IMPORT_PROFILE.text.sectionKindConfidenceThreshold
      ? candidate.kind
      : "other";
  const items = buildSectionItems(candidate.lines, kind, lexiconContext);

  return {
    id: createId("section"),
    kind,
    layout: registryContext.defaultLayoutByKind.get(kind) ?? "timeline",
    customTitle: kind === "other" ? candidate.rawTitle : "",
    items,
  };
}

function buildSectionItems(
  lines: TextLine[],
  kind: SectionKind,
  lexiconContext: ResumeImportLexiconContext,
): ResumeSectionItem[] {
  if (isListSectionKind(kind)) {
    return buildListSectionItems(lines, kind);
  }

  const groups = groupExperienceLines(lines, lexiconContext);
  return groups
    .map((group) => groupToItem(group, kind, lexiconContext))
    .filter(hasItemText);
}

function isListSectionKind(kind: SectionKind) {
  return (
    kind === "skills" ||
    kind === "languages" ||
    kind === "certificates" ||
    kind === "other"
  );
}

function buildListSectionItems(
  lines: TextLine[],
  kind: SectionKind,
): ResumeSectionItem[] {
  const items: ResumeSectionItem[] = [];
  let labeledItem: { item: ResumeSectionItem; line: TextLine } | null = null;

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

    if (
      labeledItem &&
      looksLikeListContinuation(labeledItem.line, line)
    ) {
      labeledItem.item.subtitle = joinWrappedLines([
        labeledItem.item.subtitle,
        line.text,
      ]);
      labeledItem.line = line;
      continue;
    }

    labeledItem = null;
    if (kind === "other") {
      items.push(buildItem({ title: line.text }));
      continue;
    }

    items.push(
      ...splitInlineList(line.text).map((value) =>
        buildItem({ title: value }),
      ),
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
    if (row.some((line) => line.isBullet || looksLikeHighlightLine(line.text))) {
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

  if (
    periodRowIndex <= PDF_IMPORT_PROFILE.text.maxDirectPeriodRowIndex
  ) {
    return true;
  }

  // A distant date is only reliable when the preceding rows already form a
  // visible multi-column header. In a plain single-column PDF, accepting any
  // short line before a later date would move the previous item's final body
  // sentence into the next experience.
  return candidateRows
    .slice(0, periodRowIndex)
    .some((row) => row.length > 1);
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
): ResumeSectionItem {
  // Treat early compact lines as the item header and sentence-shaped lines as
  // highlights. This intentionally avoids content dictionaries such as tech
  // names or action verbs; structure is more stable across languages/domains.
  const textLines = group.map((line) => line.text);
  const period = extractPeriod(textLines, lexiconContext);
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
        looksLikeWrappedBodyContinuation(
          descriptionLastLine,
          line,
          description,
        )
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
      headerLines.length <
        PDF_IMPORT_PROFILE.text.maxHeaderLinesPerItem &&
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
): Partial<ResumeSectionItem> {
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
  const labeledValue = splitLabeledValue(
    value,
    PDF_IMPORT_PROFILE.text.maxInlineSectionLabelGraphemes,
  );
  if (!labeledValue) {
    return null;
  }

  const titleMatch = classifySectionTitle(
    labeledValue.label,
    registryContext,
  );
  if (titleMatch.confidence === 0) {
    return null;
  }

  return {
    title: labeledValue.label,
    content: labeledValue.value,
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
    return {
      kind,
      confidence: PDF_IMPORT_PROFILE.text.sectionTitleConfidence,
    };
  }

  return { kind: "other", confidence: 0 };
}

function normalizeTitle(value: string) {
  return normalizePdfCompatibilityCharacters(value)
    .normalize("NFKC")
    .replace(/\s+/g, "")
    .replace(/[：:]/g, "")
    .toLowerCase();
}

function extractPeriod(
  lines: string[],
  lexiconContext: ResumeImportLexiconContext,
) {
  const text = normalizeMatchingText(lines.join(" "));
  const { minYear, maxYear } = PDF_IMPORT_PROFILE.dates;
  for (const match of text.matchAll(lexiconContext.periodPattern)) {
    const period = match[0];
    const years = period.match(/\d{4}/g)?.map(Number) ?? [];
    if (years.every((year) => year >= minYear && year <= maxYear)) {
      return period;
    }
  }

  return "";
}

function looksLikePeriodLine(
  line: string,
  lexiconContext: ResumeImportLexiconContext,
) {
  return Boolean(extractPeriod([line], lexiconContext));
}

function looksLikeHighlightLine(line: string) {
  // Avoid content-word dictionaries here. A line is treated as body text only
  // when its shape looks like a sentence or a dense comma-separated statement.
  return (
    countTextGraphemes(line) >
      PDF_IMPORT_PROFILE.text.minLongDescriptionGraphemes ||
    /[。；;.]$/.test(line) ||
    countMatches(line, /[，,、]/g) >=
      PDF_IMPORT_PROFILE.text.minDenseCommaCount
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

function appendHighlightContinuation(highlights: string[], line: string) {
  const lastIndex = highlights.length - 1;
  highlights[lastIndex] = joinWrappedLines([
    highlights[lastIndex] ?? "",
    line,
  ]);
}

function looksLikeScoreMetaLine(line: string) {
  // Education metadata is usually numeric even when labels vary by language.
  return (
    /\d/.test(line) &&
    (/\/|%|[()（）]/.test(line) ||
      countMatches(line, /\d/g) >=
        PDF_IMPORT_PROFILE.text.minScoreDigitCount)
  );
}

function looksLikeListMetaLine(line: string) {
  if (looksLikeHighlightLine(line)) {
    return false;
  }

  return (
    splitInlineList(line).length >=
      PDF_IMPORT_PROFILE.text.minListMetaParts || /[+/]/.test(line)
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
    countTextGraphemes(line) <=
    PDF_IMPORT_PROFILE.text.maxTitleLineGraphemes
  ) {
    score += PDF_IMPORT_PROFILE.scoring.titleFitsLengthLimit;
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
    .split(/[，,、;；|｜]|\s+\+\s+/)
    .map(normalizeWhitespace)
    .filter(Boolean);
}

function splitLabeledValue(
  input: string,
  maxLabelGraphemes: number,
) {
  const match = input.match(/^([^：:]+?)[：:]\s*(.+)$/);
  if (!match) {
    return null;
  }

  const label = normalizeWhitespace(match[1] ?? "");
  const value = normalizeWhitespace(match[2] ?? "");
  if (
    !label ||
    !value ||
    countTextGraphemes(label) > maxLabelGraphemes
  ) {
    return null;
  }

  return { label, value };
}

function countMatches(value: string, pattern: RegExp) {
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
    throw new Error("PDF_IMPORT_UNSUPPORTED_GRAPHEME_SEGMENTATION");
  }

  return Array.from(
    GRAPHEME_SEGMENTER.segment(normalized),
    ({ segment }) => segment,
  );
}

function isSingleHanGrapheme(value: string) {
  const graphemes = splitTextGraphemes(value);
  return (
    graphemes.length === 1 &&
    /^\p{Script=Han}\p{Mark}*$/u.test(graphemes[0] ?? "")
  );
}

function normalizeWhitespace(value: string) {
  return normalizePdfCompatibilityCharacters(value)
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeMatchingText(value: string) {
  return normalizePdfCompatibilityCharacters(value)
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeLexiconTerm(value: string) {
  return normalizeMatchingText(value).toLowerCase();
}

function buildPeriodPattern({
  currentPeriodTerms,
  dateRangeTerms,
  datePartSeparators,
  datePartSuffixes,
}: {
  currentPeriodTerms: string[];
  dateRangeTerms: string[];
  datePartSeparators: string[];
  datePartSuffixes: string[];
}) {
  if (currentPeriodTerms.length === 0) {
    throw new Error("INVALID_RESUME_IMPORT_LEXICON");
  }

  // Match the shape first, then enforce the supported year range in
  // extractPeriod. Keeping range policy out of this regex avoids coupling the
  // parser to particular century prefixes.
  const yearPattern = "\\d{4}";
  const monthNumberPattern = "(?:0?[1-9]|1[0-2])";
  const compactMonthPattern = "(?:0[1-9]|1[0-2])";
  const datePartSeparatorPattern = literalAlternation([
    ".",
    "/",
    "-",
    ...datePartSeparators,
  ]);
  const rangeSeparatorPattern = literalAlternation([
    "-",
    "–",
    "—",
    ...dateRangeTerms,
  ]);
  const currentPeriodPattern = literalAlternation(currentPeriodTerms);
  const datePartSuffixPattern = literalAlternation(datePartSuffixes);
  const localizedDateSuffix = datePartSuffixPattern
    ? `(?:${datePartSuffixPattern})?`
    : "";
  // A month can be compact (YYYYMM), separated (YYYY.MM), or localized
  // (YYYY年MM月). Reject impossible months and partial separators here so an
  // invalid date cannot consume adjacent prose as an experience period.
  const separatedMonthPattern =
    `(?:${datePartSeparatorPattern})${monthNumberPattern}` +
    localizedDateSuffix;
  const monthPattern =
    `(?:${compactMonthPattern}|${separatedMonthPattern})?`;
  const datePattern = `${yearPattern}${monthPattern}`;

  return new RegExp(
    `(?<![\\p{L}\\p{N}])${datePattern}\\s*` +
      `(?:${rangeSeparatorPattern})\\s*` +
      `(?:${datePattern}|${currentPeriodPattern})(?![\\p{L}\\p{N}])`,
    "giu",
  );
}

function literalAlternation(values: string[]) {
  return [...new Set(values.map(normalizeMatchingText).filter(Boolean))]
    .sort((left, right) => right.length - left.length)
    .map(escapeRegExp)
    .join("|");
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizePdfCompatibilityCharacters(value: string) {
  return value.replace(CJK_COMPATIBILITY_CHARACTER_PATTERN, (character) => {
    return (
      CJK_RADICAL_TEXT_EQUIVALENTS[character] ??
      character.normalize("NFKC")
    );
  });
}

function median(values: number[]) {
  if (values.length === 0) {
    return PDF_IMPORT_PROFILE.fallbacks.bodyFontSize;
  }
  const sorted = [...values].sort((left, right) => left - right);
  return (
    sorted[Math.floor(sorted.length / 2)] ??
    PDF_IMPORT_PROFILE.fallbacks.bodyFontSize
  );
}
