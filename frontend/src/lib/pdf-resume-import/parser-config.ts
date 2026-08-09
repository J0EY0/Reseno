import { apiRoutes, requestApi } from "@/lib/api-client";
import { SECTION_KINDS } from "@/types/resume";
import type { SectionKind, SectionLayout } from "@/types/resume";

import {
  normalizeLexiconTerm,
  normalizeMatchingText,
  normalizePdfCompatibilityCharacters,
} from "./text-heuristics";

type SectionRegistryEntry = {
  kind: SectionKind;
  defaultLayout: SectionLayout;
  labels: Record<string, string>;
  aliases: string[];
};

export type SectionRegistryResponse = {
  sections: SectionRegistryEntry[];
};

export type SectionRegistryContext = {
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

export type ResumeImportLexiconResponse = {
  locales: Record<string, ResumeImportLexiconLocale>;
};

export type ResumeImportLexiconContext = {
  documentTitleTerms: Set<string>;
  periodPattern: RegExp;
};

type ResumeImportParserConfig = {
  registry: SectionRegistryResponse;
  lexicon: ResumeImportLexiconResponse;
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
export const PDF_IMPORT_PROFILE = {
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
const IMPORT_PARSER_CONFIG_CACHE_TTL_MS = 5 * 60 * 1000;
let resumeImportParserConfigCache:
  | {
      expiresAt: number;
      request: Promise<ResumeImportParserConfig>;
    }
  | undefined;
const SECTION_KIND_SET = new Set<string>(SECTION_KINDS);
export async function fetchResumeImportParserConfig(): Promise<ResumeImportParserConfig> {
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
export function createSectionRegistryContext(
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

export function createResumeImportLexiconContext(
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
export function normalizeTitle(value: string) {
  return normalizePdfCompatibilityCharacters(value)
    .normalize("NFKC")
    .replace(/\s+/g, "")
    .replace(/[：:]/g, "")
    .toLowerCase();
}

export function extractPeriod(
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

export function looksLikePeriodLine(
  line: string,
  lexiconContext: ResumeImportLexiconContext,
) {
  return Boolean(extractPeriod([line], lexiconContext));
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
export function median(values: number[]) {
  if (values.length === 0) {
    return PDF_IMPORT_PROFILE.fallbacks.bodyFontSize;
  }
  const sorted = [...values].sort((left, right) => left - right);
  return (
    sorted[Math.floor(sorted.length / 2)] ??
    PDF_IMPORT_PROFILE.fallbacks.bodyFontSize
  );
}

