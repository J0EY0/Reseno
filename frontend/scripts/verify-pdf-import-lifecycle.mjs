import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { evaluateTypeScript } from "./typescript-module.mjs";

const root = new URL("../src/lib/pdf-resume-import/", import.meta.url);
const source = (name) => readFileSync(new URL(`${name}.ts`, root), "utf8");
const globals = {
  Error,
  DOMException,
  AbortController,
  AbortSignal,
  Uint8Array,
  Intl,
};
const apiErrors = evaluateTypeScript(
  readFileSync(new URL("../api-errors.ts", root), "utf8"),
  {
    globals,
    imports: { "@/lib/api-message": { resolveApiMessage: (key) => key } },
  },
);
const errors = evaluateTypeScript(source("errors"), {
  globals,
  imports: { "@/lib/api-errors": apiErrors },
});
const abort = evaluateTypeScript(source("abort"), { globals });
const heuristics = evaluateTypeScript(source("text-heuristics"), {
  globals,
  imports: { "./errors": errors },
});
const config = evaluateTypeScript(source("parser-config"), {
  globals,
  imports: {
    "./errors": errors,
    "./text-heuristics": heuristics,
    "@/lib/api-client": {},
    "@/lib/api-errors": apiErrors,
    "@/types/resume": { SECTION_KINDS: [] },
  },
});
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
};
const textContent = (text) => ({
  items: [{ str: text, transform: [1, 0, 0, 10, 40, 700], width: 100 }],
});

function createExtraction({ numPages = 2, loading, pageText } = {}) {
  const calls = { reads: 0, documents: 0, pages: [], texts: [], destroys: 0 };
  const document = {
    numPages,
    async getPage(pageNumber) {
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
  const extraction = evaluateTypeScript(source("pdf-text-extraction"), {
    globals,
    imports: {
      "./errors": errors,
      "./abort": abort,
      "./parser-config": config,
      "./text-heuristics": heuristics,
      "pdfjs-dist/build/pdf.worker.min.mjs?url": { default: "worker.mjs" },
      "pdfjs-dist/build/pdf.mjs": {
        GlobalWorkerOptions: {},
        getDocument() {
          calls.documents += 1;
          return task;
        },
      },
    },
  });
  const file = {
    size: 100,
    async arrayBuffer() {
      calls.reads += 1;
      return new ArrayBuffer(1);
    },
  };
  return { ...extraction, calls, file };
}
const nextTurn = () => new Promise((resolve) => setImmediate(resolve));

test("PDF extraction destroys its loading task after all pages succeed", async () => {
  const fixture = createExtraction();
  const lines = await fixture.extractPdfLines(fixture.file);
  assert.deepEqual(
    Array.from(lines, (line) => line.text),
    ["Page 1", "Page 2"],
  );
  assert.equal(fixture.calls.destroys, 1);
});

test("PDF loading and text extraction failures both destroy the task", async () => {
  for (const stage of ["loading", "text"]) {
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
      fixture.extractPdfLines(fixture.file),
      (error) => error === failure,
    );
    assert.equal(fixture.calls.destroys, 1);
    assert.ok(fixture.calls.pages.length <= 1);
  }
});

test("PDF size is rejected before any file bytes are read", async () => {
  const fixture = createExtraction();
  await assert.rejects(
    fixture.extractPdfLines({
      ...fixture.file,
      size: fixture.MAX_PDF_IMPORT_BYTES + 1,
    }),
    { code: "PDF_IMPORT_FILE_TOO_LARGE" },
  );
  assert.equal(fixture.calls.reads, 0);
  assert.equal(fixture.calls.documents, 0);
});

test("PDFs at the 50-page limit are accepted and larger documents fail before page extraction", async () => {
  const allowed = createExtraction({ numPages: 50 });
  assert.equal((await allowed.extractPdfLines(allowed.file)).length, 50);
  assert.equal(allowed.calls.destroys, 1);
  const oversized = createExtraction({ numPages: 51 });
  await assert.rejects(oversized.extractPdfLines(oversized.file), {
    code: "PDF_IMPORT_TOO_MANY_PAGES",
  });
  assert.equal(oversized.calls.pages.length, 0);
  assert.equal(oversized.calls.destroys, 1);
});

test("cancelling before PDF import prevents file access", async () => {
  const fixture = createExtraction();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    fixture.extractPdfLines(fixture.file, { signal: controller.signal }),
    { name: "AbortError" },
  );
  assert.equal(fixture.calls.reads, 0);
});

test("cancelling while reading PDF bytes returns promptly and never creates a document", async () => {
  const fixture = createExtraction();
  const buffer = deferred();
  const controller = new AbortController();
  const request = fixture.extractPdfLines(
    { ...fixture.file, arrayBuffer: () => buffer.promise },
    { signal: controller.signal },
  );
  controller.abort();
  await assert.rejects(request, { name: "AbortError" });
  buffer.resolve(new ArrayBuffer(1));
  await nextTurn();
  assert.equal(fixture.calls.documents, 0);
});

test("cancelling during document loading destroys the pending worker exactly once", async () => {
  const fixture = createExtraction({ loading: deferred().promise });
  const controller = new AbortController();
  const request = fixture.extractPdfLines(fixture.file, {
    signal: controller.signal,
  });
  await nextTurn();
  assert.equal(fixture.calls.documents, 1);
  controller.abort();
  await assert.rejects(request, { name: "AbortError" });
  assert.equal(fixture.calls.destroys, 1);
});

test("cancelling during page text extraction stops subsequent pages and destroys the worker", async () => {
  const fixture = createExtraction({ pageText: () => deferred().promise });
  const controller = new AbortController();
  const request = fixture.extractPdfLines(fixture.file, {
    signal: controller.signal,
  });
  await nextTurn();
  assert.deepEqual(fixture.calls.texts, [1]);
  controller.abort();
  await assert.rejects(request, { name: "AbortError" });
  assert.deepEqual(fixture.calls.pages, [1]);
  assert.equal(fixture.calls.destroys, 1);
});

test("parser configuration failure cancels an already loading PDF", async () => {
  const fixture = createExtraction({ loading: deferred().promise });
  const configRequest = deferred();
  const importer = evaluateTypeScript(
    readFileSync(new URL("../pdf-resume-import.ts", root), "utf8"),
    {
      globals,
      imports: {
        "./pdf-resume-import/errors": errors,
        "./pdf-resume-import/abort": abort,
        "./pdf-resume-import/pdf-text-extraction": fixture,
        "./pdf-resume-import/parser-config": {
          fetchResumeImportParserConfig: () => configRequest.promise,
        },
        "./pdf-resume-import/basic-contact": {},
        "./pdf-resume-import/document-language": {},
        "./pdf-resume-import/parser": {},
      },
    },
  );
  const request = importer.importResumeFromPdf(fixture.file);
  await nextTurn();
  const failure = new errors.PdfImportError(
    "INVALID_RESUME_IMPORT_PARSER_CONFIG",
  );
  configRequest.reject(failure);
  await assert.rejects(request, (error) => error === failure);
  assert.equal(fixture.calls.destroys, 1);
});

test("PDF errors retain their cause and map to specific localized messages", () => {
  for (const [name, code] of [
    ["PasswordException", "PDF_IMPORT_PASSWORD_PROTECTED"],
    ["InvalidPDFException", "PDF_IMPORT_INVALID_PDF"],
  ]) {
    const original = Object.assign(new Error(name), { name });
    const wrapped = errors.normalizePdfImportError(original);
    assert.equal(wrapped.code, code);
    assert.equal(wrapped.cause, original);
    for (const locale of ["zh", "en"]) {
      const messages = JSON.parse(
        readFileSync(
          new URL(`../src/i18n/locales/${locale}.json`, import.meta.url),
          "utf8",
        ),
      );
      assert.equal(
        errors.getPdfImportErrorMessage(wrapped, messages),
        messages[
          name === "PasswordException"
            ? "pdfImportPasswordProtected"
            : "pdfImportInvalidPdf"
        ],
      );
    }
  }
  const unauthorized = new apiErrors.ApiError("UNAUTHORIZED_REQUEST", {
    apiCode: "UNAUTHORIZED_REQUEST",
  });
  assert.equal(errors.normalizePdfImportError(unauthorized), unauthorized);
  const cancelled = new DOMException("Cancelled", "AbortError");
  assert.equal(errors.normalizePdfImportError(cancelled), cancelled);
  assert.equal(
    errors.getPdfImportErrorMessage(new Error("other"), {}),
    undefined,
  );
  const unsupported = evaluateTypeScript(source("text-heuristics"), {
    globals: { ...globals, Intl: {} },
    imports: { "./errors": errors },
  });
  assert.throws(() => unsupported.countTextGraphemes("Text"), {
    code: "PDF_IMPORT_UNSUPPORTED_GRAPHEME_SEGMENTATION",
  });
});

test("concurrent parser configuration consumers receive the same structured failure and can retry", async () => {
  const pending = deferred();
  let requests = 0;
  const parserConfig = evaluateTypeScript(source("parser-config"), {
    globals,
    imports: {
      "./errors": errors,
      "./text-heuristics": heuristics,
      "@/lib/api-errors": apiErrors,
      "@/lib/api-client": {
        apiRoutes: {
          sectionRegistry: "registry",
          resumeImportLexicon: "lexicon",
        },
        requestApi(_route, options) {
          requests += 1;
          assert.equal(options.notifyOnError, false);
          return pending.promise;
        },
      },
      "@/types/resume": { SECTION_KINDS: [] },
    },
  });
  const first = parserConfig.fetchResumeImportParserConfig();
  const second = parserConfig.fetchResumeImportParserConfig();
  assert.equal(requests, 2);
  pending.reject(new Error("Network unavailable"));
  await Promise.all(
    [first, second].map((request) =>
      assert.rejects(request, { code: "INVALID_RESUME_IMPORT_PARSER_CONFIG" }),
    ),
  );
  await assert.rejects(parserConfig.fetchResumeImportParserConfig(), {
    code: "INVALID_RESUME_IMPORT_PARSER_CONFIG",
  });
  assert.equal(requests, 4);
});
