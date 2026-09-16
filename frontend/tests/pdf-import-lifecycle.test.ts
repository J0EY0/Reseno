import assert from "node:assert/strict";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { saveAuthSession } from "@/lib/auth-session";
import {
  PdfImportError,
  getPdfImportErrorMessage,
  normalizePdfImportError,
} from "@/lib/pdf-resume-import/errors";
import {
  extractPdfText,
  MAX_PDF_IMPORT_BYTES,
} from "@/lib/pdf-resume-import/pdf-text-extraction";
import zh from "@/i18n/locales/zh.json";
import en from "@/i18n/locales/en.json";
import type { AppMessages } from "@/i18n";

const pdfjs = vi.hoisted(() => ({
  getDocument: vi.fn(),
  GlobalWorkerOptions: { workerSrc: "" },
}));
vi.mock("pdfjs-dist/build/pdf.mjs", () => pdfjs);
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({
  default: "worker.mjs",
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
const textContent = (text: string) => ({
  items: [{ str: text, transform: [1, 0, 0, 10, 40, 700], width: 100 }],
});
type PageText = ReturnType<typeof textContent>;
function createExtraction({
  numPages = 2,
  loading,
  pageText,
}: {
  numPages?: number;
  loading?: Promise<unknown>;
  pageText?: (pageNumber: number) => Promise<PageText>;
} = {}) {
  const calls = {
    reads: 0,
    documents: 0,
    pages: [] as number[],
    texts: [] as number[],
    destroys: 0,
  };
  const document = {
    numPages,
    async getPage(pageNumber: number) {
      calls.pages.push(pageNumber);
      return {
        getViewport: () => ({ width: 600 }),
        getTextContent() {
          calls.texts.push(pageNumber);
          return (
            pageText?.(pageNumber) ??
            Promise.resolve(textContent(`Page ${pageNumber}`))
          );
        },
      };
    },
  };
  const task = {
    promise: loading ?? Promise.resolve(document),
    async destroy() {
      calls.destroys += 1;
    },
  };
  pdfjs.getDocument.mockImplementation(() => {
    calls.documents += 1;
    return task;
  });
  const file = {
    size: 100,
    async arrayBuffer() {
      calls.reads += 1;
      return new ArrayBuffer(1);
    },
  } as File;
  return { extractPdfText, MAX_PDF_IMPORT_BYTES, calls, file };
}
const nextTurn = () => new Promise<void>((resolve) => setImmediate(resolve));
beforeEach(() => {
  vi.resetModules();
  pdfjs.getDocument.mockReset();
  localStorage.clear();
  saveAuthSession("owner", "pdf-import-test-token", "2999-01-01T00:00:00Z");
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("PDF extraction destroys its loading task after all pages succeed", async () => {
  const fixture = createExtraction();
  const { lines, pageCount } = await fixture.extractPdfText(fixture.file);
  assert.equal(pageCount, 2);
  assert.deepEqual(
    Array.from(lines, (line) => line.text),
    ["Page 1", "Page 2"],
  );
  assert.equal(fixture.calls.destroys, 1);
});

it("PDF extraction counts a trailing page without text", async () => {
  const fixture = createExtraction({
    numPages: 2,
    pageText: async (page) =>
      page === 1 ? textContent("Page 1") : { items: [] },
  });
  const result = await fixture.extractPdfText(fixture.file);
  assert.equal(result.pageCount, 2);
  assert.equal(result.lines.length, 1);
  assert.equal(result.lines[0]?.page, 1);
  assert.equal(fixture.calls.destroys, 1);
});

it.each(["loading", "text"] as const)(
  "PDF %s failure destroys the task",
  async (stage) => {
    const failure = new Error(`${stage} failed`);
    const fixture = createExtraction(
      stage === "loading"
        ? { loading: Promise.reject(failure) }
        : {
            pageText: async () => {
              throw failure;
            },
          },
    );
    await assert.rejects(
      fixture.extractPdfText(fixture.file),
      (error) => error === failure,
    );
    assert.equal(fixture.calls.destroys, 1);
    assert.ok(fixture.calls.pages.length <= 1);
  },
);

it("PDF size is rejected before any file bytes are read", async () => {
  const fixture = createExtraction();
  await assert.rejects(
    fixture.extractPdfText({
      ...fixture.file,
      size: fixture.MAX_PDF_IMPORT_BYTES + 1,
    }),
    { code: "PDF_IMPORT_FILE_TOO_LARGE" },
  );
  assert.equal(fixture.calls.reads, 0);
  assert.equal(fixture.calls.documents, 0);
});

it("PDFs at the 50-page limit are accepted and larger documents fail before page extraction", async () => {
  const allowed = createExtraction({ numPages: 50 });
  const result = await allowed.extractPdfText(allowed.file);
  assert.equal(result.lines.length, 50);
  assert.equal(result.pageCount, 50);
  assert.equal(allowed.calls.destroys, 1);
  const oversized = createExtraction({ numPages: 51 });
  await assert.rejects(oversized.extractPdfText(oversized.file), {
    code: "PDF_IMPORT_TOO_MANY_PAGES",
  });
  assert.equal(oversized.calls.pages.length, 0);
  assert.equal(oversized.calls.destroys, 1);
});

it("cancelling before PDF import prevents file access", async () => {
  const fixture = createExtraction();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    fixture.extractPdfText(fixture.file, { signal: controller.signal }),
    { name: "AbortError" },
  );
  assert.equal(fixture.calls.reads, 0);
});

it("cancelling while reading PDF bytes returns promptly and never creates a document", async () => {
  const fixture = createExtraction();
  const buffer = deferred<ArrayBuffer>();
  const controller = new AbortController();
  const request = fixture.extractPdfText(
    { ...fixture.file, arrayBuffer: () => buffer.promise },
    { signal: controller.signal },
  );
  controller.abort();
  await assert.rejects(request, { name: "AbortError" });
  buffer.resolve(new ArrayBuffer(1));
  await nextTurn();
  assert.equal(fixture.calls.documents, 0);
});

it("cancelling during document loading destroys the pending worker exactly once", async () => {
  const fixture = createExtraction({ loading: deferred().promise });
  const controller = new AbortController();
  const request = fixture.extractPdfText(fixture.file, {
    signal: controller.signal,
  });
  await vi.waitFor(() => assert.equal(fixture.calls.documents, 1));
  controller.abort();
  await assert.rejects(request, { name: "AbortError" });
  assert.equal(fixture.calls.destroys, 1);
});

it("cancelling during page text extraction stops subsequent pages and destroys the worker", async () => {
  const fixture = createExtraction({
    pageText: () => deferred<PageText>().promise,
  });
  const controller = new AbortController();
  const request = fixture.extractPdfText(fixture.file, {
    signal: controller.signal,
  });
  await vi.waitFor(() => assert.deepEqual(fixture.calls.texts, [1]));
  controller.abort();
  await assert.rejects(request, { name: "AbortError" });
  assert.deepEqual(fixture.calls.pages, [1]);
  assert.equal(fixture.calls.destroys, 1);
});

it("parser configuration failure cancels an already loading PDF", async () => {
  const fixture = createExtraction({ loading: deferred().promise });
  const network = deferred<Response>();
  vi.stubGlobal(
    "fetch",
    vi.fn(() => network.promise),
  );
  const { fetchResumeImportParserConfig } =
    await import("@/lib/pdf-resume-import/parser-config");
  const { importResumeFromPdf } = await import("@/lib/pdf-resume-import");
  const configFailure = fetchResumeImportParserConfig().catch(
    (error: unknown) => error,
  );
  const request = importResumeFromPdf(fixture.file);
  const rejection = request.catch((error: unknown) => error);
  await vi.waitFor(() => assert.equal(fixture.calls.documents, 1));
  network.reject(new Error("Network unavailable"));
  const failure = await configFailure;
  expect(failure).toMatchObject({
    code: "INVALID_RESUME_IMPORT_PARSER_CONFIG",
  });
  assert.equal(await rejection, failure);
  assert.equal(fixture.calls.destroys, 1);
});

it("PDF errors retain their cause and map to specific localized messages", () => {
  for (const [name, code] of [
    ["PasswordException", "PDF_IMPORT_PASSWORD_PROTECTED"],
    ["InvalidPDFException", "PDF_IMPORT_INVALID_PDF"],
  ]) {
    const original = Object.assign(new Error(name), { name });
    const wrapped = normalizePdfImportError(original);
    assert.ok(wrapped instanceof PdfImportError);
    assert.equal(wrapped.code, code);
    assert.equal(wrapped.cause, original);
    for (const messages of [zh, en]) {
      assert.equal(
        getPdfImportErrorMessage(wrapped, messages),
        messages[
          name === "PasswordException"
            ? "pdfImportPasswordProtected"
            : "pdfImportInvalidPdf"
        ],
      );
    }
  }
  const unauthorized = new ApiError("UNAUTHORIZED_REQUEST", {
    apiCode: "UNAUTHORIZED_REQUEST",
  });
  assert.equal(normalizePdfImportError(unauthorized), unauthorized);
  const cancelled = new DOMException("Cancelled", "AbortError");
  assert.equal(normalizePdfImportError(cancelled), cancelled);
  assert.equal(
    getPdfImportErrorMessage(new Error("other"), {} as AppMessages),
    undefined,
  );
});

it("reports unsupported grapheme segmentation through the real heuristics module", async () => {
  vi.stubGlobal("Intl", {});
  const { countTextGraphemes } =
    await import("@/lib/pdf-resume-import/text-heuristics");
  assert.throws(() => countTextGraphemes("Text"), {
    code: "PDF_IMPORT_UNSUPPORTED_GRAPHEME_SEGMENTATION",
  });
});

it("concurrent parser configuration consumers receive the same structured failure and can retry", async () => {
  const pending = deferred<Response>();
  const fetch = vi.fn(() => pending.promise);
  vi.stubGlobal("fetch", fetch);
  const notifier = vi.spyOn(
    await import("@/lib/api-error-notifier"),
    "notifyApiError",
  );
  const { fetchResumeImportParserConfig } =
    await import("@/lib/pdf-resume-import/parser-config");
  const first = fetchResumeImportParserConfig();
  const second = fetchResumeImportParserConfig();
  assert.equal(fetch.mock.calls.length, 2);
  pending.reject(new Error("Network unavailable"));
  await Promise.all(
    [first, second].map((request) =>
      assert.rejects(request, { code: "INVALID_RESUME_IMPORT_PARSER_CONFIG" }),
    ),
  );
  await assert.rejects(fetchResumeImportParserConfig(), {
    code: "INVALID_RESUME_IMPORT_PARSER_CONFIG",
  });
  assert.equal(fetch.mock.calls.length, 4);
  expect(notifier).not.toHaveBeenCalled();
});
