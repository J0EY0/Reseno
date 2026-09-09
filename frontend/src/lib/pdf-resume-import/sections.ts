import { serializeListItemsToHtml } from "@/lib/rich-text";
import { createId } from "@/lib/resume";
import type {
  AchievementItem,
  EducationItem,
  ExperienceItem,
  ProjectItem,
  PublicationItem,
  ResumeSection,
  SectionKind,
} from "@/types/resume";

import type { TextLine } from "./pdf-text-extraction";
import {
  PDF_IMPORT_PROFILE,
  looksLikePeriodLine,
  median,
  normalizeTitle,
  type ResumeImportLexiconContext,
  type SectionRegistryContext,
} from "./parser-config";
import {
  buildSectionItems,
  isBulletLine,
  isListSectionKind,
  looksLikeHighlightLine,
  type ParsedSectionItem,
} from "./section-items";
import {
  countTextGraphemes,
  splitInlineList,
  splitLabeledValue,
} from "./text-heuristics";

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
export function splitSections(
  lines: TextLine[],
  registryContext: SectionRegistryContext,
  lexiconContext: ResumeImportLexiconContext,
): SectionCandidate[] {
  const sections: SectionCandidate[] = [];
  let current: SectionCandidate | null = null;
  const bodyFontSize = median(
    lines.map((line) => line.fontSize).filter(Boolean),
  );

  for (const [index, line] of lines.entries()) {
    const titleMatch = classifySectionTitle(line.text, registryContext);
    const inlineTitleMatch = splitInlineSectionTitle(
      line.text,
      registryContext,
    );
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
        bodyFontSize * PDF_IMPORT_PROFILE.text.genericSectionHeadingScale;
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
        bodyFontSize * PDF_IMPORT_PROFILE.text.genericSectionHeadingScale &&
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

  return sections;
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

export function linesBeforeFirstSection(
  lines: TextLine[],
  sections: SectionCandidate[],
): TextLine[] {
  if (!sections[0]) {
    return lines.slice(0, PDF_IMPORT_PROFILE.text.contactScanLineLimit);
  }

  return lines.slice(0, sections[0].startLineIndex);
}
export function sectionCandidateToResumeSection(
  candidate: SectionCandidate,
  lexiconContext: ResumeImportLexiconContext,
): ResumeSection {
  const kind =
    candidate.confidence >=
    PDF_IMPORT_PROFILE.text.sectionKindConfidenceThreshold
      ? candidate.kind
      : "simple_list";
  const parsedItems = buildSectionItems(candidate.lines, kind, lexiconContext);

  return createCanonicalSection(
    kind,
    kind === "simple_list" ? candidate.rawTitle : "",
    parsedItems,
  );
}

function createCanonicalSection(
  kind: SectionKind,
  title: string,
  items: ParsedSectionItem[],
): ResumeSection {
  const id = createId("section");

  switch (kind) {
    case "education":
      return {
        id,
        kind,
        title,
        items: items.map<EducationItem>((item) => ({
          id: item.id,
          school: item.title,
          degree: item.subtitle,
          major: "",
          gpa: item.meta,
          location: "",
          period: item.period,
          description: item.description,
          highlights: item.highlights,
        })),
      };
    case "experience":
      return {
        id,
        kind,
        title,
        items: items.map<ExperienceItem>((item) => ({
          id: item.id,
          company: item.title,
          position: item.subtitle,
          location: item.meta,
          period: item.period,
          description: item.description,
          highlights: item.highlights,
        })),
      };
    case "project":
      return {
        id,
        kind,
        title,
        items: items.map<ProjectItem>((item) => ({
          id: item.id,
          name: item.title,
          role: item.subtitle,
          techStack: splitInlineList(item.meta),
          period: item.period,
          url: "",
          description: item.description,
          highlights: item.highlights,
        })),
      };
    case "publication":
      return {
        id,
        kind,
        title,
        items: items.map<PublicationItem>((item) => ({
          id: item.id,
          title: item.title,
          authors: item.subtitle,
          venue: item.meta,
          date: item.period,
          url: "",
          description: item.description || item.highlights.join(" "),
        })),
      };
    case "achievement":
      return {
        id,
        kind,
        title,
        items: items.map<AchievementItem>((item) => ({
          id: item.id,
          name: item.title,
          issuer: item.subtitle || item.meta,
          date: item.period,
          url: "",
          description: item.description || item.highlights.join(" "),
        })),
      };
    case "simple_list":
      return {
        id,
        kind,
        title,
        // Parsing still yields one record per visual line; collapse those lines
        // at the V2 boundary so the editor receives one rich-text list item.
        items: [
          {
            id: items[0]?.id ?? createId("item"),
            content: serializeListItemsToHtml(
              items.map((item) =>
                item.subtitle
                  ? `${item.title}：${item.subtitle}`
                  : item.title || item.description || item.highlights.join(" "),
              ),
            ),
          },
        ],
      };
  }
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

  const titleMatch = classifySectionTitle(labeledValue.label, registryContext);
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

  return { kind: "simple_list", confidence: 0 };
}
