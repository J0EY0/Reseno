import type { ResumeData } from "@/types/resume";

import { hasMeaningfulResumeText } from "./pdf-resume-import/basic-contact";
import { extractPdfLines } from "./pdf-resume-import/pdf-text-extraction";
import { fetchResumeImportParserConfig } from "./pdf-resume-import/parser-config";
import { buildResumeFromPdfLines } from "./pdf-resume-import/parser";

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
