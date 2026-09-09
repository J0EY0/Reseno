import type { DocumentLocale, ResumeData } from "@/types/resume";

import { waitForPdfImport } from "./pdf-resume-import/abort";
import { hasMeaningfulResumeText } from "./pdf-resume-import/basic-contact";
import { detectPdfResumeDocumentLocale } from "./pdf-resume-import/document-language";
import {
  PdfImportError,
  normalizePdfImportError,
} from "./pdf-resume-import/errors";
import { extractPdfLines } from "./pdf-resume-import/pdf-text-extraction";
import { fetchResumeImportParserConfig } from "./pdf-resume-import/parser-config";
import { buildResumeFromPdfLines } from "./pdf-resume-import/parser";

export async function importResumeFromPdf(
  file: File,
  { signal }: { signal?: AbortSignal } = {},
): Promise<{
  resume: ResumeData;
  documentLocale: DocumentLocale;
  unclassifiedLineCount: number;
}> {
  signal?.throwIfAborted();
  const controller = new AbortController();
  const importSignal = signal
    ? AbortSignal.any([signal, controller.signal])
    : controller.signal;
  const extraction = extractPdfLines(file, { signal: importSignal });
  try {
    const [lines, { registry, lexicon }] = await Promise.all([
      extraction,
      waitForPdfImport(fetchResumeImportParserConfig(), importSignal),
    ]);
    if (!hasMeaningfulResumeText(lines)) {
      throw new PdfImportError("PDF_IMPORT_NO_TEXT");
    }

    const documentLocale = detectPdfResumeDocumentLocale(lines);
    const fallbackSectionTitle = registry.sections.find(
      (section) => section.kind === "simple_list",
    )?.labels[documentLocale];
    if (!fallbackSectionTitle) {
      throw new PdfImportError("INVALID_RESUME_IMPORT_PARSER_CONFIG");
    }
    signal?.throwIfAborted();
    return {
      ...buildResumeFromPdfLines(
        lines,
        fallbackSectionTitle,
        registry,
        lexicon,
      ),
      documentLocale,
    };
  } catch (error) {
    controller.abort();
    await extraction.catch(() => {});
    throw normalizePdfImportError(error);
  }
}
