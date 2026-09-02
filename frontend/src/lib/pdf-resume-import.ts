import type { DocumentLocale, ResumeData } from "@/types/resume";

import { hasMeaningfulResumeText } from "./pdf-resume-import/basic-contact";
import {
  detectPdfResumeDocumentLocale,
} from "./pdf-resume-import/document-language";
import { extractPdfLines } from "./pdf-resume-import/pdf-text-extraction";
import { fetchResumeImportParserConfig } from "./pdf-resume-import/parser-config";
import { buildResumeFromPdfLines } from "./pdf-resume-import/parser";

export async function importResumeFromPdf(
  file: File,
): Promise<{
  resume: ResumeData;
  documentLocale: DocumentLocale;
}> {
  const [lines, { registry, lexicon }] = await Promise.all([
    extractPdfLines(file),
    fetchResumeImportParserConfig(),
  ]);
  const text = lines.map((line) => line.text).join("\n").trim();

  if (!text || !hasMeaningfulResumeText(lines)) {
    throw new Error("PDF_IMPORT_NO_TEXT");
  }

  const documentLocale = detectPdfResumeDocumentLocale(lines);
  const fallbackSectionTitle = registry.sections.find(
    (section) => section.kind === "simple_list",
  )?.labels[documentLocale];
  if (!fallbackSectionTitle) {
    throw new Error("INVALID_RESUME_IMPORT_PARSER_CONFIG");
  }

  return {
    resume: buildResumeFromPdfLines(
      lines,
      fallbackSectionTitle,
      registry,
      lexicon,
    ),
    documentLocale,
  };
}
