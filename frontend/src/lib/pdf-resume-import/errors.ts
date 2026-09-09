import type { AppMessages } from "@/i18n";
import { isApiErrorCode } from "@/lib/api-errors";

const messageKeys = {
  PDF_IMPORT_NO_TEXT: "pdfImportNoText",
  PDF_IMPORT_PASSWORD_PROTECTED: "pdfImportPasswordProtected",
  PDF_IMPORT_INVALID_PDF: "pdfImportInvalidPdf",
  PDF_IMPORT_FILE_TOO_LARGE: "pdfImportFileTooLarge",
  PDF_IMPORT_TOO_MANY_PAGES: "pdfImportTooManyPages",
  PDF_IMPORT_UNSUPPORTED_GRAPHEME_SEGMENTATION: "pdfImportUnsupportedBrowser",
  INVALID_RESUME_IMPORT_PARSER_CONFIG: "pdfImportParserConfigFailed",
  INVALID_RESUME_IMPORT_LEXICON: "pdfImportParserConfigFailed",
  PDF_IMPORT_FAILED: "pdfImportFailed",
} as const satisfies Record<string, keyof AppMessages>;

type PdfImportErrorCode = keyof typeof messageKeys;

export class PdfImportError extends Error {
  readonly code: PdfImportErrorCode;

  constructor(code: PdfImportErrorCode, options?: ErrorOptions) {
    super(code, options);
    this.name = "PdfImportError";
    this.code = code;
  }
}

export function getPdfImportErrorMessage(
  error: unknown,
  messages: AppMessages,
) {
  return error instanceof PdfImportError
    ? messages[messageKeys[error.code]]
    : undefined;
}

export function normalizePdfImportError(error: unknown): unknown {
  if (
    error instanceof PdfImportError ||
    isApiErrorCode(error, "UNAUTHORIZED_REQUEST")
  )
    return error;
  if (error && typeof error === "object" && "name" in error) {
    if (error.name === "AbortError") return error;
    if (error.name === "PasswordException") {
      return new PdfImportError("PDF_IMPORT_PASSWORD_PROTECTED", {
        cause: error,
      });
    }
    if (error.name === "InvalidPDFException") {
      return new PdfImportError("PDF_IMPORT_INVALID_PDF", { cause: error });
    }
  }
  return new PdfImportError("PDF_IMPORT_FAILED", { cause: error });
}
