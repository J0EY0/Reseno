import assert from "node:assert/strict";
import { File as NodeFile } from "node:buffer";
import { createRequire } from "node:module";
import { afterEach, beforeEach, it, vi } from "vitest";
import { saveAuthSession } from "@/lib/auth-session";
import {
  createPdfFile,
  jsonResponse,
  requiredSection,
  resumeImportLexicon,
  sectionRegistry,
} from "./helpers/pdf-import-fixtures";

vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", async () => {
  const { createRequire } = await import("node:module");
  const { pathToFileURL } = await import("node:url");
  return {
    default: pathToFileURL(
      createRequire(import.meta.url).resolve(
        "pdfjs-dist/build/pdf.worker.min.mjs",
      ),
    ).href,
  };
});
const require = createRequire(import.meta.url);
const requireFromPdfJs = createRequire(
  require.resolve("pdfjs-dist/package.json"),
);
const { DOMMatrix, ImageData, Path2D } = requireFromPdfJs("@napi-rs/canvas");
const toHexDescriptor = Object.getOwnPropertyDescriptor(
  Uint8Array.prototype,
  "toHex",
);
let parserConfigResponseMode = "success";
let parserConfigRequestCounts: { lexicon: number; registry: number };
let importResumeFromPdf: typeof import("@/lib/pdf-resume-import").importResumeFromPdf;

beforeEach(async () => {
  vi.resetModules();
  if (!toHexDescriptor)
    Object.defineProperty(Uint8Array.prototype, "toHex", {
      configurable: true,
      value(this: Uint8Array) {
        return Buffer.from(this).toString("hex");
      },
    });
  vi.stubGlobal("DOMMatrix", DOMMatrix);
  vi.stubGlobal("ImageData", ImageData);
  vi.stubGlobal("Path2D", Path2D);
  vi.stubGlobal("File", NodeFile);
  localStorage.clear();
  saveAuthSession("owner", "pdf-import-test-token", "2999-01-01T00:00:00Z");
  parserConfigResponseMode = "success";
  parserConfigRequestCounts = { lexicon: 0, registry: 0 };
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const route = String(input);

      if (
        route.endsWith("/api/section-registry") ||
        route.endsWith("/api/resume-import-lexicon")
      ) {
        assert.equal(
          new Headers(init.headers).get("Authorization"),
          "Bearer pdf-import-test-token",
          "protected parser-config requests must carry the active session token",
        );
      }

      if (route.endsWith("/api/section-registry")) {
        parserConfigRequestCounts.registry += 1;
        if (parserConfigResponseMode === "registry-conflict") {
          return jsonResponse({
            sections: [
              {
                kind: "page",
                defaultLayout: "list",
                labels: { en: "Page" },
                aliases: ["页"],
              },
              {
                kind: "radical-page",
                defaultLayout: "list",
                labels: { en: "Radical page" },
                aliases: ["⻚"],
              },
            ],
          });
        }
        if (parserConfigResponseMode === "registry-duplicate") {
          return jsonResponse({
            sections: [
              {
                kind: "experience",
                defaultLayout: "timeline",
                labels: { en: "Work", zh: "工作经历" },
                aliases: ["Work Experience", " work：experience "],
              },
            ],
          });
        }
        if (parserConfigResponseMode === "registry-unknown") {
          return jsonResponse({
            sections: [
              {
                kind: "bogus",
                defaultLayout: "timeline",
                labels: { en: "Bogus", zh: "未知" },
                aliases: ["bogus"],
              },
            ],
          });
        }
        if (parserConfigResponseMode === "registry-incomplete") {
          return jsonResponse({
            sections: sectionRegistry.sections.filter(
              (section) => section.kind !== "simple_list",
            ),
          });
        }
        return jsonResponse(sectionRegistry);
      }

      if (route.endsWith("/api/resume-import-lexicon")) {
        parserConfigRequestCounts.lexicon += 1;
        if (parserConfigResponseMode === "failure") {
          throw new Error("Synthetic parser-config request failure.");
        }
        if (parserConfigResponseMode === "malformed") {
          return jsonResponse({
            locales: {
              en: {
                documentTitleTerms: ["resume"],
              },
            },
          });
        }
        if (parserConfigResponseMode === "empty-term") {
          return jsonResponse({
            locales: {
              ...resumeImportLexicon.locales,
              en: {
                ...resumeImportLexicon.locales.en,
                currentPeriodTerms: [" "],
              },
            },
          });
        }
        return jsonResponse(resumeImportLexicon);
      }

      throw new Error(`Unexpected PDF import test request: ${route}`);
    },
  );
  ({ importResumeFromPdf } = await import("@/lib/pdf-resume-import"));
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  if (!toHexDescriptor) Reflect.deleteProperty(Uint8Array.prototype, "toHex");
});
it("retries every malformed configuration without poisoning the cache, then reuses and expires valid inputs", async () => {
  parserConfigResponseMode = "failure";
  const pdf = createPdfFile([
    [
      "Test User",
      "test.user@example.com",
      "Education",
      "Example University",
      "Software Engineering",
      "2020 - 2024",
      "Built a strong foundation in distributed systems and data structures.",
    ],
    [
      "Projects",
      "Resume Workspace",
      "2024 - Present",
      "Designed a structured resume editor with reliable PDF import support.",
      "Improved parsing quality through deterministic geometry regression tests.",
    ],
  ]);

  await assert.rejects(
    importResumeFromPdf(pdf),
    Error,
    "a failed parser-config request should reject the import",
  );

  parserConfigResponseMode = "malformed";
  await assert.rejects(
    importResumeFromPdf(pdf),
    /INVALID_RESUME_IMPORT_PARSER_CONFIG/,
    "a malformed successful response must not poison the parser-config cache",
  );

  parserConfigResponseMode = "registry-conflict";
  await assert.rejects(
    importResumeFromPdf(pdf),
    /INVALID_RESUME_IMPORT_PARSER_CONFIG/,
    "aliases that collide after PDF text normalization must be rejected",
  );

  parserConfigResponseMode = "registry-duplicate";
  await assert.rejects(
    importResumeFromPdf(pdf),
    /INVALID_RESUME_IMPORT_PARSER_CONFIG/,
    "duplicate aliases within one kind must match backend validation",
  );

  parserConfigResponseMode = "registry-unknown";
  await assert.rejects(
    importResumeFromPdf(pdf),
    /INVALID_RESUME_IMPORT_PARSER_CONFIG/,
    "a section kind unsupported by the frontend domain must be rejected",
  );

  parserConfigResponseMode = "registry-incomplete";
  await assert.rejects(
    importResumeFromPdf(pdf),
    /INVALID_RESUME_IMPORT_PARSER_CONFIG/,
    "a registry missing a frontend section kind must be rejected",
  );

  parserConfigResponseMode = "empty-term";
  await assert.rejects(
    importResumeFromPdf(pdf),
    /INVALID_RESUME_IMPORT_PARSER_CONFIG/,
    "blank lexicon terms must be rejected before regex construction",
  );

  const originalDateNow = Date.now;
  let fakeNow = originalDateNow();
  Date.now = () => fakeNow;
  try {
    parserConfigResponseMode = "success";
    const {
      resume: imported,
      documentLocale,
      sourcePageCount,
    } = await importResumeFromPdf(pdf);
    assert.equal(sourcePageCount, 2);
    assert.equal(documentLocale, "en");
    assert.equal(imported.basic.name, "Test User");
    assert.equal(imported.basic.email, "test.user@example.com");
    assert.equal(requiredSection(imported, "education").items.length, 1);
    assert.equal(requiredSection(imported, "project").items.length, 1);
    assert.deepEqual(parserConfigRequestCounts, {
      lexicon: 8,
      registry: 8,
    });

    await importResumeFromPdf(pdf);
    assert.deepEqual(
      parserConfigRequestCounts,
      { lexicon: 8, registry: 8 },
      "successful parser config should be reused within its cache lifetime",
    );

    fakeNow += 5 * 60 * 1000 + 1;
    await importResumeFromPdf(pdf);
    assert.deepEqual(
      parserConfigRequestCounts,
      { lexicon: 9, registry: 9 },
      "expired parser config should be refreshed",
    );
  } finally {
    Date.now = originalDateNow;
  }
});

it("imports a short real PDF and destroys its PDF.js loading task exactly once", async () => {
  const shortPdf = createPdfFile([
    [
      "Short User",
      "short@example.com",
      "Education",
      "Example School",
      "2020 - 2024",
    ],
  ]);
  const { getDocument } = await import("pdfjs-dist/build/pdf.mjs");
  const probe = getDocument({
    data: new Uint8Array(await shortPdf.arrayBuffer()),
  });
  await probe.promise;
  const loadingTaskPrototype = Object.getPrototypeOf(probe);
  await probe.destroy();
  const originalDestroy = loadingTaskPrototype.destroy;
  let destroyCount = 0;
  let shortImport: Awaited<ReturnType<typeof importResumeFromPdf>>;
  loadingTaskPrototype.destroy = function (this: unknown, ...args: unknown[]) {
    destroyCount += 1;
    return originalDestroy.apply(this, args);
  };
  try {
    shortImport = await importResumeFromPdf(shortPdf);
    assert.equal(
      destroyCount,
      1,
      "A real PDF.js loading task must be destroyed after successful import.",
    );
  } finally {
    loadingTaskPrototype.destroy = originalDestroy;
  }
  assert.equal(
    shortImport.resume.basic.name,
    "Short User",
    "a short text-layer resume must not be rejected by an arbitrary length floor",
  );
  assert.equal(shortImport.documentLocale, "en");
  assert.equal(shortImport.sourcePageCount, 1);
});

it("preserves unclassified real PDF content exactly once with the localized fallback title", async () => {
  const freeformPdf = createPdfFile([
    [
      "Test User",
      "test@example.com",
      "Built accessible internal tools.",
      "Improved delivery quality across teams.",
    ],
  ]);
  const freeformImport = await importResumeFromPdf(freeformPdf);
  assert.equal(freeformImport.unclassifiedLineCount, 2);
  assert.equal(
    JSON.stringify(freeformImport.resume).match(
      /Built accessible internal tools/g,
    )?.length,
    1,
    "Unclassified content must be preserved once, without repeating the header or summary.",
  );
  assert.equal(
    requiredSection(freeformImport.resume, "other").title,
    "Other",
    "fallback section titles must come from the registry and detected document language",
  );
});

it("reports a trailing blank source page independently of extracted text", async () => {
  const result = await importResumeFromPdf(
    createPdfFile([
      ["Example User", "example@example.com", "Skills", "TypeScript, Python"],
      [],
    ]),
  );
  assert.equal(result.sourcePageCount, 2);
  assert.equal(result.resume.basic.name, "Example User");
});

it("rejects oversized, invalid, and meaningless real PDFs", async () => {
  await assert.rejects(
    importResumeFromPdf(
      createPdfFile(Array.from({ length: 51 }, () => ["Page text"])),
    ),
    { code: "PDF_IMPORT_TOO_MANY_PAGES" },
  );
  await assert.rejects(
    importResumeFromPdf(
      new File(["invalid pdf bytes"], "invalid.pdf", {
        type: "application/pdf",
      }),
    ),
    { code: "PDF_IMPORT_INVALID_PDF" },
  );

  const noisePdf = createPdfFile([["1"]]);
  await assert.rejects(
    importResumeFromPdf(noisePdf),
    /PDF_IMPORT_NO_TEXT/,
    "a non-empty but meaningless text layer must not create a fake resume",
  );
});

it("keeps one deep public PDF import interface", async () => {
  assert.deepEqual(
    Object.keys(await import("@/lib/pdf-resume-import")).sort(),
    ["importResumeFromPdf"],
    "the product PDF importer must keep one deep public interface",
  );
});

it("imports tilde-separated education dates without treating them as GPA", async () => {
  const { resume } = await importResumeFromPdf(
    createPdfFile([
      [
        "Example Person",
        "person@example.com",
        "Education",
        "Example University",
        "2024-09 ~ 2027-06",
        "GPA: 3.7 / 4.0",
        "Example College",
        "2019-09 ~ 2023-06",
        "GPA: 3.77 / 4.50",
      ],
    ]),
  );

  assert.deepEqual(
    requiredSection(resume, "education").items.map(
      ({ school, degree, gpa, period }) => ({ school, degree, gpa, period }),
    ),
    [
      {
        school: "Example University",
        degree: "",
        gpa: "GPA: 3.7 / 4.0",
        period: "2024-09 ~ 2027-06",
      },
      {
        school: "Example College",
        degree: "",
        gpa: "GPA: 3.77 / 4.50",
        period: "2019-09 ~ 2023-06",
      },
    ],
  );
});

it.each(["zh", "en"])(
  "imports English dates and section labels with a %s workspace locale",
  async (locale) => {
    localStorage.setItem("reseno-locale", locale);
    const result = await importResumeFromPdf(
      createPdfFile([
        [
          "Example Person",
          "person@example.com",
          "Academic Background",
          "Example University",
          "September 2018 - June 2022",
          "Studied computer science and software engineering.",
          "Professional Experience",
          "First Company",
          "Jul 2022 - Dec 2023",
          "Built reliable document processing services.",
          "Second Company",
          "Jan 2024 - Present",
          "Delivered accessible editing and review workflows.",
          "Technical Expertise",
          "TypeScript, Python, SQL",
        ],
      ]),
    );
    assert.equal(result.documentLocale, "en");
    assert.deepEqual(
      result.resume.sections.map(({ title }) => title),
      ["Academic Background", "Professional Experience", "Technical Expertise"],
    );
    assert.deepEqual(
      requiredSection(result.resume, "experience").items.map(
        ({ company, period }) => ({ company, period }),
      ),
      [
        { company: "First Company", period: "Jul 2022 - Dec 2023" },
        { company: "Second Company", period: "Jan 2024 - Present" },
      ],
    );
  },
);
