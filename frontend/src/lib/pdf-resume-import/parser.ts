import { hasSectionContent } from "@/lib/resume-sections";
import type { ResumeData } from "@/types/resume";

import { extractBasicInfo } from "./basic-contact";
import {
  orderLinesForReading,
  type TextLine,
} from "./pdf-text-extraction";
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
            kind: "simple_list" as const,
            confidence: 0,
            startLineIndex: basicLines.length,
            lines: normalizedLines.slice(basicLines.length).length > 0
              ? normalizedLines.slice(basicLines.length)
              : normalizedLines,
          },
        ];

  return {
    schemaVersion: 2,
    basic,
    sections: resolvedSections
      .map((section) =>
        sectionCandidateToResumeSection(
          section,
          lexiconContext,
        ),
      )
      .filter(hasSectionContent),
  };
}

