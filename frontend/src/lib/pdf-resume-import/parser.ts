import { hasSectionContent } from "@/lib/resume-sections";
import type { ResumeData, ResumeSection } from "@/types/resume";

import { extractBasicInfo } from "./basic-contact";
import { orderLinesForReading, type TextLine } from "./pdf-text-extraction";
import {
  createResumeImportLexiconContext,
  createSectionRegistryContext,
  type ResumeImportLexiconResponse,
  type SectionRegistryResponse,
} from "./parser-config";
import {
  linesBeforeFirstSection,
  sectionCandidateToResumeSection,
  splitSections,
} from "./sections";
import { normalizeWhitespace } from "./text-heuristics";

export function buildResumeFromPdfLines(
  lines: TextLine[],
  fallbackSectionTitle: string,
  registry: SectionRegistryResponse,
  lexicon: ResumeImportLexiconResponse,
): { resume: ResumeData; unclassifiedLineCount: number } {
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
  const { basic, unclassifiedLines } = extractBasicInfo(
    basicLines,
    lexiconContext,
    sections.length > 0,
  );
  const resolvedSections: ResumeSection[] = [];
  let unclassifiedLineCount = 0;
  for (const candidate of sections) {
    const parsed = sectionCandidateToResumeSection(candidate, lexiconContext);
    if (hasSectionContent(parsed)) {
      resolvedSections.push(parsed);
      if (candidate.confidence === 0)
        unclassifiedLineCount += candidate.lines.length;
    } else {
      unclassifiedLines.push(
        {
          ...normalizedLines[candidate.startLineIndex],
          text: candidate.rawTitle,
        },
        ...candidate.lines,
      );
    }
  }
  if (sections.length === 0) {
    unclassifiedLines.push(...normalizedLines.slice(basicLines.length));
  }
  if (unclassifiedLines.length > 0) {
    resolvedSections.push(
      sectionCandidateToResumeSection(
        {
          rawTitle: fallbackSectionTitle,
          kind: "simple_list",
          confidence: 0,
          startLineIndex: 0,
          lines: unclassifiedLines,
        },
        lexiconContext,
      ),
    );
    unclassifiedLineCount += unclassifiedLines.length;
  }

  return {
    resume: { schemaVersion: 2, basic, sections: resolvedSections },
    unclassifiedLineCount,
  };
}
