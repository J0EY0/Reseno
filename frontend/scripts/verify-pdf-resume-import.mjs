import assert from "node:assert/strict";
import { File } from "node:buffer";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const require = createRequire(import.meta.url);
const requireFromPdfJs = createRequire(
  require.resolve("pdfjs-dist/package.json"),
);
const { DOMMatrix, ImageData, Path2D } =
  requireFromPdfJs("@napi-rs/canvas");
const pdfWorkerFileUrl = pathToFileURL(
  require.resolve("pdfjs-dist/build/pdf.worker.min.mjs"),
).href;
const pdfWorkerUrlModuleId = "\0reseno-pdf-worker-url";
const authSessionImportId = "virtual:reseno-pdf-import-auth-session";
const authSessionModuleId = `\0${authSessionImportId}`;
const parserModuleDirectory = new URL(
  "../src/lib/pdf-resume-import/",
  import.meta.url,
);

verifyAcyclicParserModules(parserModuleDirectory);

// Browser PDF.js receives these geometry primitives from the DOM. Its own
// Node dependency provides equivalent implementations for this integration
// fixture, keeping the production importer on the normal browser build.
Object.assign(globalThis, { DOMMatrix, ImageData, Path2D });
if (typeof Uint8Array.prototype.toHex !== "function") {
  Object.defineProperty(Uint8Array.prototype, "toHex", {
    configurable: true,
    value() {
      return Array.from(this, (byte) => byte.toString(16).padStart(2, "0")).join(
        "",
      );
    },
  });
}

const sectionRegistry = JSON.parse(
  readFileSync(
    new URL("../../backend/app/services/agent/section_registry.json", import.meta.url),
    "utf8",
  ),
);
const resumeImportLexicon = JSON.parse(
  readFileSync(
    new URL(
      "../../backend/app/services/resume_import_lexicon.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const zhMinimalStructureFixture = JSON.parse(
  readFileSync(
    new URL(
      "./fixtures/pdf-import/zh-minimal-structure.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const originalFetch = globalThis.fetch;
let parserConfigResponseMode = "failure";
const parserConfigRequestCounts = {
  lexicon: 0,
  registry: 0,
};

globalThis.fetch = async (input, init = {}) => {
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
};

const server = await createServer({
  cacheDir: createViteTestCacheDir(),
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  root: process.cwd(),
  plugins: [
    {
      name: "reseno-pdf-worker-url",
      enforce: "pre",
      resolveId(id) {
        if (id === authSessionImportId) {
          return authSessionModuleId;
        }
        return id === "pdfjs-dist/build/pdf.worker.min.mjs?url"
          ? pdfWorkerUrlModuleId
          : null;
      },
      load(id) {
        if (id === authSessionModuleId) {
          return `
            export function clearAuthSession() {}
            export function getAccessToken() { return "pdf-import-test-token"; }
            export function isTokenLocallyInvalidated() { return false; }
          `;
        }
        return id === pdfWorkerUrlModuleId
          ? `export default ${JSON.stringify(pdfWorkerFileUrl)};`
          : null;
      },
    },
  ],
  server: {
    hmr: false,
    middlewareMode: true,
    ws: false,
  },
  resolve: {
    alias: [
      {
        find: "@/lib/auth-session",
        replacement: authSessionImportId,
      },
      {
        find: "@",
        replacement: new URL("../src", import.meta.url).pathname,
      },
    ],
  },
});

try {
  const [
    productEntry,
    parser,
    pdfTextExtraction,
    textHeuristics,
    documentLanguage,
  ] =
    await Promise.all([
      server.ssrLoadModule("/src/lib/pdf-resume-import.ts"),
      server.ssrLoadModule("/src/lib/pdf-resume-import/parser.ts"),
      server.ssrLoadModule(
        "/src/lib/pdf-resume-import/pdf-text-extraction.ts",
      ),
      server.ssrLoadModule("/src/lib/pdf-resume-import/text-heuristics.ts"),
      server.ssrLoadModule(
        "/src/lib/pdf-resume-import/document-language.ts",
      ),
    ]);
  assert.deepEqual(
    Object.keys(productEntry).sort(),
    ["importResumeFromPdf"],
    "the product PDF importer must keep one deep public interface",
  );
  const { importResumeFromPdf } = productEntry;
  const { buildResumeFromPdfLines } = parser;
  const { textContentToLinesForResumeImport } = pdfTextExtraction;
  const { countTextGraphemes } = textHeuristics;
  const { detectPdfResumeDocumentLocale } = documentLanguage;
  const buildResumeFromLines = (
    lines,
    fallbackSectionTitle,
    lexicon = resumeImportLexicon,
  ) =>
    buildResumeFromPdfLines(
      lines,
      fallbackSectionTitle,
      sectionRegistry,
      lexicon,
    );

  verifyColumnLineSplitting(textContentToLinesForResumeImport);
  verifyCompactTwoColumnReadingOrder(buildResumeFromLines);
  verifyMixedSingleAndTwoColumnReadingOrder(buildResumeFromLines);
  verifyDisjointTwoColumnReadingOrder(buildResumeFromLines);
  verifyContactLocationExtraction(buildResumeFromLines);
  verifyProjectItemGrouping(buildResumeFromLines);
  verifyPublicationItemGrouping(buildResumeFromLines);
  verifyFallbackSectionShape(buildResumeFromLines);
  verifyInlineSectionHeading(buildResumeFromLines);
  verifyWrappedLabeledListContinuation(buildResumeFromLines);
  verifyShortBulletsAndContinuation(buildResumeFromLines);
  verifyAdjacentExperienceItems(buildResumeFromLines);
  verifyLargeExperienceTitleIsNotASection(buildResumeFromLines);
  verifyOtherSectionAllowsLaterInlineExperience(buildResumeFromLines);
  verifyMultilineColumnMetadata(buildResumeFromLines);
  verifyDottedTechnologyHeadline(buildResumeFromLines);
  verifyLexiconDrivenDocumentTitleAndPeriod(buildResumeFromLines);
  verifySyntheticLexiconControlsParsing(buildResumeFromLines);
  verifyLocalizedDateSuffixParsing(buildResumeFromLines);
  verifyImportedContentIsNotSilentlyTruncated(buildResumeFromLines);
  verifyUnicodeLengthLimitsUseGraphemes(
    buildResumeFromLines,
    countTextGraphemes,
  );
  verifyPeriodYearRange(buildResumeFromLines);
  verifySectionAtDocumentStartDoesNotBecomeBasicInfo(buildResumeFromLines);
  verifyStrictPeriodShapes(buildResumeFromLines);
  verifyIndentedSingleColumnReadingOrder(buildResumeFromLines);
  verifyContactParsingPreservesLocationAndUrls(buildResumeFromLines);
  verifyDateRangeIsNotAContactPhone(buildResumeFromLines);
  verifyCompactDateRangeIsNotAContactPhone(buildResumeFromLines);
  verifyFullwidthContactAndPeriod(buildResumeFromLines);
  verifyDuplicatePositionedTextIsDeduplicated(
    textContentToLinesForResumeImport,
  );
  verifyNearDuplicatePositionedTextIsDeduplicated(
    textContentToLinesForResumeImport,
  );
  verifyRtlTextOrder(textContentToLinesForResumeImport);
  verifyMixedDirectionTextOrder(textContentToLinesForResumeImport);
  verifyEqualWeightMixedDirectionTextOrder(
    textContentToLinesForResumeImport,
  );
  verifyRotatedTextFontSize(textContentToLinesForResumeImport);
  verifyContinuousHanGlyphTokens(textContentToLinesForResumeImport);
  verifyDocumentLanguageDetection(detectPdfResumeDocumentLocale);
  verifyShortUnmarkedBodySplitsAdjacentExperiences(buildResumeFromLines);
  verifyZhMinimalStructureRegression(
    textContentToLinesForResumeImport,
    buildResumeFromLines,
    detectPdfResumeDocumentLocale,
  );
  await verifyPublicPdfImportEntry(importResumeFromPdf);

  console.log("PDF resume import fixtures verified.");
} finally {
  globalThis.fetch = originalFetch;
  await server.close();
}

function verifyAcyclicParserModules(directory) {
  const moduleNames = readdirSync(directory)
    .filter((name) => name.endsWith(".ts"))
    .sort();
  const graph = new Map(
    moduleNames.map((name) => {
      const source = readFileSync(new URL(name, directory), "utf8");
      const dependencies = Array.from(
        source.matchAll(/from\s+["']\.\/([^"']+)["']/g),
        (match) => `${match[1]}.ts`,
      ).filter((dependency) => moduleNames.includes(dependency));
      return [name, dependencies];
    }),
  );
  const visiting = new Set();
  const visited = new Set();

  function visit(moduleName, trail) {
    assert.ok(
      !visiting.has(moduleName),
      `PDF parser modules must stay acyclic: ${[
        ...trail,
        moduleName,
      ].join(" -> ")}`,
    );
    if (visited.has(moduleName)) {
      return;
    }

    visiting.add(moduleName);
    for (const dependency of graph.get(moduleName) ?? []) {
      visit(dependency, [...trail, moduleName]);
    }
    visiting.delete(moduleName);
    visited.add(moduleName);
  }

  for (const moduleName of moduleNames) {
    visit(moduleName, []);
  }
}

async function verifyPublicPdfImportEntry(importResumeFromPdf) {
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
    const { resume: imported, documentLocale } =
      await importResumeFromPdf(pdf);
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

  const shortPdf = createPdfFile([
    [
      "Short User",
      "short@example.com",
      "Education",
      "Example School",
      "2020 - 2024",
    ],
  ]);
  const shortImport = await importResumeFromPdf(shortPdf);
  assert.equal(
    shortImport.resume.basic.name,
    "Short User",
    "a short text-layer resume must not be rejected by an arbitrary length floor",
  );
  assert.equal(shortImport.documentLocale, "en");

  const freeformPdf = createPdfFile([
    [
      "Test User",
      "test@example.com",
      "Built accessible internal tools.",
      "Improved delivery quality across teams.",
    ],
  ]);
  const freeformImport = await importResumeFromPdf(freeformPdf);
  assert.equal(
    requiredSection(freeformImport.resume, "other").title,
    "Other",
    "fallback section titles must come from the registry and detected document language",
  );

  const noisePdf = createPdfFile([["1"]]);
  await assert.rejects(
    importResumeFromPdf(noisePdf),
    /PDF_IMPORT_NO_TEXT/,
    "a non-empty but meaningless text layer must not create a fake resume",
  );
}

function verifyColumnLineSplitting(textContentToLines) {
  const lines = textContentToLines(
    {
      items: [
        textItem("左栏项目", 40, 700),
        textItem("右栏技能", 360, 700),
        textItem("左栏内容", 40, 680),
        textItem("右栏内容", 360, 680),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["左栏项目", "右栏技能", "左栏内容", "右栏内容"],
  );
}

function verifyCompactTwoColumnReadingOrder(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      // Compact templates place profile details in a narrow left column and
      // the resume body in a wider right column. Interleaving these by y would
      // make the first right-column heading terminate the profile block.
      positionedLine("测试用户", 800, 40, 16),
      positionedLine("前端工程师", 780, 40),
      positionedLine("user@example.com", 760, 40),
      positionedLine("+86 138 0000 0000", 740, 40),
      positionedLine("关注复杂交互与稳定交付。", 720, 40),
      positionedLine("教育经历", 800, 340, 14),
      positionedLine("示例学院", 780, 340),
      positionedLine("2021.09 - 2025.06", 780, 540),
      positionedLine("软件工程", 760, 340),
      positionedLine("• 完成核心课程学习。", 720, 340),
      positionedLine("项目经历", 700, 340, 14),
      positionedLine("示例项目", 680, 340),
      positionedLine("项目负责人", 660, 340),
      positionedLine("2024.01 - 2024.12", 660, 540),
      positionedLine("• 完成项目交付。", 640, 340),
      positionedLine("• 提升使用效率。", 620, 340),
    ],
    "导入内容",
  );

  assert.equal(resume.basic.name, "测试用户");
  assert.equal(resume.basic.headline, "前端工程师");
  assert.equal(resume.basic.email, "user@example.com");
  assert.equal(resume.basic.phone, "+86 138 0000 0000");
  assert.equal(resume.basic.summary, "关注复杂交互与稳定交付。");
  assert.equal(requiredSection(resume, "education").items.length, 1);
  assert.equal(requiredSection(resume, "project").items.length, 1);
}

function verifyMixedSingleAndTwoColumnReadingOrder(buildResumeFromLines) {
  const pageWidth = 612;
  const resume = buildResumeFromLines(
    [
      positionedLine("Test User", 800, 40, 16, pageWidth),
      positionedLine("test@example.com", 780, 40, 10, pageWidth),
      positionedLine("Education", 750, 40, 14, pageWidth),
      positionedLine("Example School", 730, 40, 10, pageWidth),
      positionedLine("2020 - 2024", 730, 500, 10, pageWidth),
      positionedLine("Software Engineering", 710, 40, 10, pageWidth),
      positionedLine("Work Experience", 670, 40, 14, pageWidth),
      positionedLine("Example Organization", 650, 40, 10, pageWidth),
      positionedLine("2024 - Present", 630, 40, 10, pageWidth),
      positionedLine("Example Role", 610, 40, 10, pageWidth),
      positionedLine("• Improved a workflow.", 590, 40, 10, pageWidth),
      positionedLine("Skills", 670, 340, 14, pageWidth),
      positionedLine("TypeScript", 650, 340, 10, pageWidth),
      positionedLine("React", 630, 340, 10, pageWidth),
      positionedLine("Node.js", 610, 340, 10, pageWidth),
      positionedLine("Testing", 590, 340, 10, pageWidth),
      positionedLine("Accessibility", 570, 340, 10, pageWidth),
      positionedLine("Performance", 550, 340, 10, pageWidth),
      positionedLine("Databases", 530, 340, 10, pageWidth),
    ],
    "Imported content",
  );

  assert.equal(
    requiredSection(resume, "education").items[0]?.period,
    "2020 - 2024",
    "a right-aligned date in the single-column header must not move into a later column",
  );
}

function verifyDisjointTwoColumnReadingOrder(buildResumeFromLines) {
  const pageWidth = 612;
  const leftColumn = 40;
  const rightColumn = 340;
  const lines = [
    positionedLine("Test User", 1000, leftColumn, 16, pageWidth),
    positionedLine("test@example.com", 980, leftColumn, 10, pageWidth),
    positionedLine("Work Experience", 920, leftColumn, 14, pageWidth),
    positionedLine("Example Organization", 900, leftColumn, 10, pageWidth),
    positionedLine("Example Role", 880, leftColumn, 10, pageWidth),
    positionedLine("2022 - Present", 860, leftColumn, 10, pageWidth),
    positionedLine("• Improved a workflow.", 840, leftColumn, 10, pageWidth),
    positionedLine("• Reduced processing time.", 820, leftColumn, 10, pageWidth),
    positionedLine("• Documented the result.", 800, leftColumn, 10, pageWidth),
    positionedLine("Skills", 920, rightColumn, 14, pageWidth),
    ...["TypeScript", "React", "Node.js", "Testing", "Accessibility", "SQL", "Git"]
      .map((text, index) =>
        positionedLine(text, 900 - index * 20, rightColumn, 10, pageWidth),
      ),
    positionedLine("Awards", 700, leftColumn, 14, pageWidth),
    positionedLine("Example Award", 680, leftColumn, 10, pageWidth),
    positionedLine("2023", 660, leftColumn, 10, pageWidth),
    positionedLine("Recognized for reliable delivery.", 640, leftColumn, 10, pageWidth),
    positionedLine("Projects", 540, leftColumn, 14, pageWidth),
    positionedLine("Resume Workspace", 520, leftColumn, 10, pageWidth),
    positionedLine("Project Lead", 500, leftColumn, 10, pageWidth),
    positionedLine("2024 - Present", 480, leftColumn, 10, pageWidth),
    positionedLine("• Built structured editing.", 460, leftColumn, 10, pageWidth),
    positionedLine("• Added deterministic import.", 440, leftColumn, 10, pageWidth),
    positionedLine("• Verified export quality.", 420, leftColumn, 10, pageWidth),
    positionedLine("Languages", 540, rightColumn, 14, pageWidth),
    ...["English", "Mandarin", "Spanish", "French", "German", "Japanese", "Korean"]
      .map((text, index) =>
        positionedLine(text, 520 - index * 20, rightColumn, 10, pageWidth),
      ),
  ];
  const resume = buildResumeFromLines(lines, "Imported content");

  assert.deepEqual(
    resume.sections.map((section) => section.kind),
    ["experience", "simple_list", "achievement", "project", "simple_list"],
    "full-width content between independent column bands must keep its position",
  );
}

function verifyContactLocationExtraction(buildResumeFromLines) {
  const withLocation = buildResumeFromLines(
    [
      line("王小明", 0),
      line("杭州 | +86 138 0000 0000 | xiaoming@example.com", 1),
      line("教育经历", 2, 14),
      line("浙江大学", 3),
    ],
    "导入内容",
  );
  assert.equal(withLocation.basic.location, "杭州");

  const withHeadline = buildResumeFromLines(
    [
      line("王小明", 0),
      line("前端工程师 | xiaoming@example.com", 1),
      line("教育经历", 2, 14),
      line("浙江大学", 3),
    ],
    "导入内容",
  );
  assert.equal(withHeadline.basic.location, "");
}

function verifyProjectItemGrouping(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("项目经历", 2, 14),
      line("React + TypeScript + Tailwind", 3),
      line("Reseno", 4),
      line("2026.03 - 至今", 5),
      line("AI Agent 简历制作网站", 6),
      line("• 实现实时编辑、A4 预览、可折叠 section、关键词匹配与 PDF 导出。", 7),
      line("• 将编辑器与真实简历版式拆分为结构化数据模型，渲染更加稳定。", 8),
    ],
    "导入内容",
  );
  const project = resume.sections.find((section) => section.kind === "project");

  assert.equal(project?.items.length, 1);
  assert.equal(project?.items[0]?.name, "Reseno");
  assert.equal(project?.items[0]?.period, "2026.03 - 至今");
  assert.equal(project?.items[0]?.highlights.length, 2);
}

function verifyPublicationItemGrouping(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      positionedLine("Ruoan Shen", 800),
      positionedLine("ruoan@example.com", 780),
      positionedLine("Selected Publications", 750, 40, 14),
      positionedLine("How Traceable Feedback Shapes Trust", 720),
      positionedLine("2026", 720, 500),
      positionedLine("Ruoan Shen, Maya Li", 700),
      positionedLine("National HCI Conference", 680),
      positionedLine("Poster accepted.", 660),
      positionedLine("When Explanations Improve Revision Decisions", 630),
      positionedLine("2025", 630, 500),
      positionedLine("Ruoan Shen, Daniel Wu", 610),
      positionedLine("Human-Centered AI Workshop", 590),
      positionedLine("Peer-reviewed workshop paper.", 570),
    ],
    "Imported content",
  );
  const publications = requiredSection(resume, "publication");

  assert.equal(publications.items.length, 2);
  assert.deepEqual(
    publications.items.map((item) => ({
      title: item.title,
      authors: item.authors,
      venue: item.venue,
      date: item.date,
    })),
    [
      {
        title: "How Traceable Feedback Shapes Trust",
        authors: "Ruoan Shen, Maya Li",
        venue: "National HCI Conference",
        date: "2026",
      },
      {
        title: "When Explanations Improve Revision Decisions",
        authors: "Ruoan Shen, Daniel Wu",
        venue: "Human-Centered AI Workshop",
        date: "2025",
      },
    ],
    "Publication import must preserve separate citation fields and item boundaries.",
  );
}

function verifyFallbackSectionShape(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("+86 138 0000 0000", 2),
      line("个人简介", 3),
      line("保持开头区域不被误判为模块标题", 4),
      line("一段未识别标题", 5, 14),
      line("可以被保留的导入内容", 6),
    ],
    "导入内容",
  );
  const fallback = resume.sections[0];

  assert.equal(fallback?.kind, "simple_list");
  assert.equal(fallback?.title, "一段未识别标题");
  assert.equal(fallback?.items.length, 1);
  assert.equal(
    fallback?.items[0]?.content,
    "<ul><li>可以被保留的导入内容</li></ul>",
  );
}

function verifyInlineSectionHeading(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("技能：能力一、能力二、能力三", 2),
    ],
    "导入内容",
  );
  const skills = requiredSection(resume, "skills");

  assert.equal(skills.items.length, 1);
  assert.equal(
    skills.items[0].content,
    "<ul><li>能力一、能力二、能力三</li></ul>",
  );
}

function verifyWrappedLabeledListContinuation(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line("user@example.com", 1),
      line("技能", 2, 14),
      line("工程能力：TypeScript、React、Node.js 与复杂状态管理", 3),
      line("及自动化测试", 4),
    ],
    "导入内容",
  );
  const skills = requiredSection(resume, "skills");

  assert.equal(skills.items.length, 1);
  assert.equal(
    skills.items[0].content,
    "<ul><li>工程能力：TypeScript、React、Node.js 与复杂状态管理及自动化测试</li></ul>",
  );
}

function verifyShortBulletsAndContinuation(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("工作经历", 2, 14),
      line("示例公司", 3),
      line("2024.01 - 至今", 4),
      line("示例岗位", 5),
      line("• 负责体验优化", 6),
      line("覆盖核心使用流程", 7),
      line("• 维护编辑器稳定性", 8),
    ],
    "导入内容",
  );
  const work = requiredSection(resume, "work");

  assert.equal(work.items.length, 1);
  assert.equal(work.items[0]?.company, "示例公司");
  assert.equal(work.items[0]?.position, "示例岗位");
  assert.deepEqual(work.items[0]?.highlights, [
    "负责体验优化覆盖核心使用流程",
    "维护编辑器稳定性",
  ]);
}

function verifyAdjacentExperienceItems(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("王小明", 0),
      line("xiaoming@example.com", 1),
      line("工作经历", 2, 14),
      line("第一公司", 3),
      line("2023.01 - 2023.12", 4),
      line("第一岗位", 5),
      line("• 完成第一项工作", 6),
      line("第二公司", 7),
      line("2024.01 - 至今", 8),
      line("第二岗位", 9),
      line("• 完成第二项工作", 10),
    ],
    "导入内容",
  );
  const work = requiredSection(resume, "work");

  assert.equal(work.items.length, 2);
  assert.equal(work.items[0]?.company, "第一公司");
  assert.equal(work.items[1]?.company, "第二公司");
  assert.equal(work.items[1]?.period, "2024.01 - 至今");
}

function verifyLargeExperienceTitleIsNotASection(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line("test@example.com", 1),
      line("Work Experience", 2, 14),
      line("First Company", 3, 10),
      line("2022 - 2023", 4, 10),
      line("• Delivered the first result.", 5, 10),
      line("Second Company", 6, 13),
      line("2023 - 2024", 7, 10),
      line("• Delivered the second result.", 8, 10),
    ],
    "Imported content",
  );

  assert.deepEqual(
    requiredSection(resume, "work").items.map((item) => item.company),
    ["First Company", "Second Company"],
    "a prominent item title followed by a date remains inside its experience section",
  );
}

function verifyOtherSectionAllowsLaterInlineExperience(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line("user@example.com", 1),
      line("其他", 2, 14),
      line("技能：能力甲、能力乙", 3),
      line("工作经历：示例公司", 4),
      line("2024.01 - 2024.12", 5),
      line("示例岗位", 6),
      line("完成示例事项。", 7),
    ],
    "导入内容",
  );
  const other = requiredSection(resume, "other");
  const work = requiredSection(resume, "work");

  assert.equal(other.items.length, 1);
  assert.equal(
    other.items[0].content,
    "<ul><li>技能：能力甲、能力乙</li></ul>",
  );
  assert.equal(work.items[0]?.company, "示例公司");
}

function verifyMultilineColumnMetadata(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      positionedLine("测试用户", 800),
      positionedLine("user@example.com", 780),
      positionedLine("工作经历", 760, 40, 14),
      positionedLine("组织甲", 740, 40),
      positionedLine("元数据甲", 740, 360),
      positionedLine("岗位甲", 720, 40),
      positionedLine("元数据乙", 720, 360),
      positionedLine("2024.01 - 2024.12", 700, 360),
      positionedLine("完成示例事项。", 680, 40),
    ],
    "导入内容",
  );
  const work = requiredSection(resume, "work");

  assert.equal(work.items[0]?.company, "组织甲");
  assert.equal(work.items[0]?.position, "岗位甲");
  assert.equal(work.items[0]?.location, "元数据甲 · 元数据乙");
}

function verifyShortUnmarkedBodySplitsAdjacentExperiences(
  buildResumeFromLines,
) {
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line("user@example.com", 1),
      line("工作经历", 2, 14),
      line("组织甲", 3),
      line("2023.01 - 2023.12", 4),
      line("岗位甲", 5),
      line("完成甲项", 6),
      line("组织乙", 7),
      line("2024.01 - 2024.12", 8),
      line("岗位乙", 9),
      line("完成乙项", 10),
    ],
    "导入内容",
  );
  const work = requiredSection(resume, "work");

  assert.equal(work.items.length, 2);
  assert.deepEqual(
    work.items.map(({ company, period }) => ({ company, period })),
    [
      { company: "组织甲", period: "2023.01 - 2023.12" },
      { company: "组织乙", period: "2024.01 - 2024.12" },
    ],
  );
  assert.match(JSON.stringify(work.items[0]), /完成甲项/);
  assert.match(JSON.stringify(work.items[1]), /完成乙项/);
}

function verifyDottedTechnologyHeadline(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line("Senior Node.js Engineer", 1),
      line("user@example.com", 2),
      line("工作经历", 3, 14),
      line("示例组织", 4),
    ],
    "Imported content",
  );

  assert.equal(resume.basic.name, "Test User");
  assert.equal(resume.basic.headline, "Senior Node.js Engineer");
}

function verifyLexiconDrivenDocumentTitleAndPeriod(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("Curriculum Vitae", 0),
      line("Test User", 1),
      line("user@example.com", 2),
      line("Work Experience", 3, 14),
      line("Example Organization", 4),
      line("2024.01 - Present", 5),
      line("Software Engineer", 6),
      line("• Improved a representative workflow.", 7),
    ],
    "Imported content",
  );
  const work = requiredSection(resume, "work");

  assert.equal(resume.basic.name, "Test User");
  assert.equal(work.items[0]?.period, "2024.01 - Present");
}

function verifySyntheticLexiconControlsParsing(buildResumeFromLines) {
  // Regex metacharacters make this a stronger contract test: parsing must use
  // escaped backend terms rather than a hidden copy of the production words.
  const syntheticLexicon = {
    locales: {
      test: {
        documentTitleTerms: ["Career Sheet"],
        currentPeriodTerms: ["ongoing+"],
        dateRangeTerms: ["through+"],
        datePartSeparators: ["~"],
        datePartSuffixes: ["!"],
      },
    },
  };
  const resume = buildResumeFromLines(
    [
      line("ＣＡＲＥＥＲ   ＳＨＥＥＴ", 0),
      line("Test User", 1),
      line("user@example.com", 2),
      line("Work Experience", 3, 14),
      line("Example Organization", 4),
      line("2024~01! through+ ongoing+", 5),
      line("Software Engineer", 6),
      line("• Improved a representative workflow.", 7),
    ],
    "Imported content",
    syntheticLexicon,
  );
  const work = requiredSection(resume, "work");

  assert.equal(resume.basic.name, "Test User");
  assert.equal(work.items[0]?.period, "2024~01! through+ ongoing+");
}

function verifyLocalizedDateSuffixParsing(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line("user@example.com", 1),
      line("工作经历", 2, 14),
      line("示例组织", 3),
      line("2024年01月 - 至今", 4),
      line("示例角色", 5),
    ],
    "导入内容",
  );

  assert.equal(
    requiredSection(resume, "work").items[0]?.period,
    "2024年01月 - 至今",
  );
}

function verifyImportedContentIsNotSilentlyTruncated(
  buildResumeFromLines,
) {
  const contactFields = Array.from(
    { length: 8 },
    (_, index) => `Site${index + 1}: profile${index + 1}.example`,
  ).join(" | ");
  const highlights = Array.from(
    { length: 8 },
    (_, index) => line(`• 完成第 ${index + 1} 项可验证成果。`, index + 6),
  );
  const resume = buildResumeFromLines(
    [
      line("测试用户", 0),
      line(contactFields, 1),
      line("user@example.com", 2),
      line("工作经历", 3, 14),
      line("示例组织", 4),
      line("2024.01 - 2025.01", 5),
      ...highlights,
    ],
    "导入内容",
  );

  assert.equal(resume.basic.customFields.length, 8);
  assert.equal(requiredSection(resume, "work").items[0]?.highlights.length, 8);
}

function verifyUnicodeLengthLimitsUseGraphemes(
  buildResumeFromLines,
  countTextGraphemes,
) {
  // Each character is one grapheme but two UTF-16 code units. The legacy
  // string.length check incorrectly rejected this valid 20-character name.
  const name = "𠮷".repeat(20);
  const resume = buildResumeFromLines(
    [
      line(name, 0),
      line("user@example.com", 1),
      line("教育经历", 2, 14),
      line("示例学院", 3),
    ],
    "导入内容",
  );

  assert.equal(resume.basic.name, name);
  assert.equal(countTextGraphemes("👩‍💻e\u0301"), 2);
  assert.equal(countTextGraphemes("禰\u{E0100}"), 1);
}

function verifyPeriodYearRange(buildResumeFromLines) {
  const supported = buildResumeFromLines(
    [
      line("Test User", 0),
      line("user@example.com", 1),
      line("Work Experience", 2, 14),
      line("Example Organization", 3),
      line("2099.01 - 2100.01", 4),
      line("Example Role", 5),
    ],
    "Imported content",
  );
  assert.equal(
    requiredSection(supported, "work").items[0]?.period,
    "2099.01 - 2100.01",
  );

  const unsupported = buildResumeFromLines(
    [
      line("Test User", 0),
      line("user@example.com", 1),
      line("Work Experience", 2, 14),
      line("Example Organization", 3),
      line("2201.01 - 2202.01", 4),
      line("Example Role", 5),
    ],
    "Imported content",
  );
  assert.equal(requiredSection(unsupported, "work").items[0]?.period, "");

  const validAfterInvalidCandidate = buildResumeFromLines(
    [
      line("Test User", 0),
      line("user@example.com", 1),
      line("Work Experience", 2, 14),
      line("Reference 2201.01 - 2202.01", 3),
      line("Example Organization", 4),
      line("2021.01 - 2022.01", 5),
      line("Example Role", 6),
    ],
    "Imported content",
  );
  assert.equal(
    requiredSection(validAfterInvalidCandidate, "work").items[0]?.period,
    "2021.01 - 2022.01",
  );
}

function verifySectionAtDocumentStartDoesNotBecomeBasicInfo(
  buildResumeFromLines,
) {
  const resume = buildResumeFromLines(
    [
      line("Work Experience", 0, 14),
      line("Example Organization", 1),
      line("2024.01 - 2025.01", 2),
      line("Example Role", 3),
      line("• Delivered a measurable result.", 4),
    ],
    "Imported content",
  );

  assert.equal(resume.basic.name, "");
  assert.equal(resume.basic.summary, "");
  assert.equal(requiredSection(resume, "work").items.length, 1);
}

function verifyStrictPeriodShapes(buildResumeFromLines) {
  const parsePeriod = (candidate) => {
    const resume = buildResumeFromLines(
      [
        line("Test User", 0),
        line("user@example.com", 1),
        line("Work Experience", 2, 14),
        line("Example Organization", 3),
        line(candidate, 4),
        line("Example Role", 5),
      ],
      "Imported content",
    );
    return requiredSection(resume, "work").items[0]?.period ?? "";
  };

  assert.equal(parsePeriod("2024.1 - 2025.12"), "2024.1 - 2025.12");
  assert.equal(parsePeriod("202401 - 202512"), "202401 - 202512");
  for (const invalid of [
    "2024.99 - 2025.42",
    "ISO2024-2025Plan",
    "2024--2025",
    "2024. - 2025",
    "2024 - Currently",
  ]) {
    assert.equal(parsePeriod(invalid), "", invalid);
  }
}

function verifyIndentedSingleColumnReadingOrder(buildResumeFromLines) {
  const pageWidth = 612;
  const resume = buildResumeFromLines(
    [
      positionedLine("Skills", 800, 40, 14, pageWidth),
      positionedLine("Left 1", 780, 40, 10, pageWidth),
      positionedLine("Indented 1", 770, 130, 10, pageWidth),
      positionedLine("Indented 2", 760, 130, 10, pageWidth),
      positionedLine("Left 2", 750, 40, 10, pageWidth),
      positionedLine("Indented 3", 740, 130, 10, pageWidth),
      positionedLine("Side note", 735, 500, 10, pageWidth),
      positionedLine("Indented 4", 730, 130, 10, pageWidth),
      positionedLine("Left 3", 720, 40, 10, pageWidth),
      positionedLine("Indented 5", 710, 130, 10, pageWidth),
      positionedLine("Indented 6", 700, 130, 10, pageWidth),
      positionedLine("Left 4", 690, 40, 10, pageWidth),
      positionedLine("Indented 7", 680, 130, 10, pageWidth),
      positionedLine("Indented 8", 670, 130, 10, pageWidth),
    ],
    "Imported content",
  );
  const section = requiredSection(resume, "skills");
  assert.equal(section.items.length, 1);
  const titles = Array.from(
    section.items[0].content.matchAll(/<li>(.*?)<\/li>/g),
    (match) => match[1],
  );

  assert.deepEqual(titles.slice(0, 4), [
    "Left 1",
    "Indented 1",
    "Indented 2",
    "Left 2",
  ]);
}

function verifyContactParsingPreservesLocationAndUrls(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line(
        "user@example.com | San Francisco, CA | https://portfolio.example",
        1,
      ),
      line("Education", 2, 14),
      line("Example School", 3),
    ],
    "Imported content",
  );

  assert.equal(resume.basic.email, "user@example.com");
  assert.equal(resume.basic.location, "San Francisco, CA");
  assert.deepEqual(
    resume.basic.customFields.map(({ type, label, value }) => ({
      type,
      label,
      value,
    })),
    [
      {
        type: "url",
        label: "portfolio.example",
        value: "https://portfolio.example",
      },
    ],
    "an unlabeled web contact should remain available after import",
  );
}

function verifyDateRangeIsNotAContactPhone(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line("2020 - 2024", 1),
      line("Education", 2, 14),
      line("Example School", 3),
    ],
    "Imported content",
  );

  assert.equal(
    resume.basic.phone,
    "",
    "a standalone employment or education date range is not a phone number",
  );
}

function verifyCompactDateRangeIsNotAContactPhone(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("Test User", 0),
      line("202001 - 202406", 1),
      line("Education", 2, 14),
      line("Example School", 3),
    ],
    "Imported content",
  );

  assert.equal(
    resume.basic.phone,
    "",
    "a compact year-month range is not a phone number",
  );
}

function verifyFullwidthContactAndPeriod(buildResumeFromLines) {
  const resume = buildResumeFromLines(
    [
      line("Ｔｅｓｔ Ｕｓｅｒ", 0),
      line("ｕｓｅｒ＠ｅｘａｍｐｌｅ．ｃｏｍ", 1),
      line("Work Experience", 2, 14),
      line("Example Organization", 3),
      line("２０２４．０１ - ２０２５．０６", 4),
      line("Example Role", 5),
    ],
    "Imported content",
  );

  assert.equal(resume.basic.name, "Test User");
  assert.equal(resume.basic.email, "user@example.com");
  assert.equal(
    requiredSection(resume, "work").items[0]?.period,
    "2024.01 - 2025.06",
  );
}

function verifyDuplicatePositionedTextIsDeduplicated(textContentToLines) {
  const duplicate = textItem("重复文本", 40, 700);
  const lines = textContentToLines(
    {
      items: [duplicate, { ...duplicate }],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["重复文本"],
  );
}

function verifyNearDuplicatePositionedTextIsDeduplicated(textContentToLines) {
  const lines = textContentToLines(
    {
      items: [
        textItem("重复文本", 40, 700),
        textItem("重复文本", 40.1, 700.1, { width: 40.2 }),
        textItem("重复文本", 40, 680),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["重复文本", "重复文本"],
  );
}

function verifyRtlTextOrder(textContentToLines) {
  const lines = textContentToLines(
    {
      items: [
        textItem("مرحبا", 100, 700, { dir: "rtl", width: 40 }),
        textItem("بك", 70, 700, { dir: "rtl", width: 20 }),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["مرحبا بك"],
  );
}

function verifyMixedDirectionTextOrder(textContentToLines) {
  const lines = textContentToLines(
    {
      items: [
        textItem("مرحبا", 100, 700, {
          dir: "rtl",
          width: 40,
        }),
        textItem("2024", 50, 700, {
          dir: "ltr",
          width: 40,
        }),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["مرحبا 2024"],
    "the dominant direction should be weighted by visible text, not token count",
  );
}

function verifyEqualWeightMixedDirectionTextOrder(textContentToLines) {
  const lines = textContentToLines(
    {
      items: [
        textItem("مرح", 100, 700, {
          dir: "rtl",
          width: 30,
        }),
        textItem("abc", 50, 700, {
          dir: "ltr",
          width: 30,
        }),
      ],
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["مرح abc"],
    "equal direction weights should follow the first authored token",
  );
}

function verifyRotatedTextFontSize(textContentToLines) {
  const lines = textContentToLines(
    {
      items: [
        textItem("Rotated", 40, 700, {
          transform: [0, 10, -10, 0, 40, 700],
          height: 0,
        }),
      ],
    },
    1,
  );

  assert.equal(lines[0]?.fontSize, 10);
}

function verifyContinuousHanGlyphTokens(textContentToLines) {
  const lines = textContentToLines(
    {
      items: ["禰\u{E0100}", ..."续中文"].map((character, index) => ({
        ...textItem(character, 40 + index * 10, 700),
        width: 8,
      })),
    },
    1,
  );

  assert.deepEqual(
    lines.map((line) => line.text),
    ["禰\u{E0100}续中文"],
  );
}

function verifyDocumentLanguageDetection(detectDocumentLocale) {
  assert.equal(
    detectDocumentLocale([
      line("Élodie Martin", 0),
      line("Expérience professionnelle", 1),
    ]),
    "en",
    "accented Latin letters should remain an English document",
  );
  assert.equal(
    detectDocumentLocale([
      line("王小明", 0),
      line("Software Engineer", 1),
    ]),
    "zh",
    "mixed Han and Latin text should default to Chinese",
  );
  assert.equal(
    detectDocumentLocale([
      line("Иван Петров", 0),
      line("Software Engineer", 1),
    ]),
    "zh",
    "a non-Latin script should default to Chinese",
  );
  assert.equal(
    detectDocumentLocale([line("Resume", 0)]),
    "en",
    "all-Latin text should be classified as English after import text validation",
  );
}

function verifyZhMinimalStructureRegression(
  textContentToLines,
  buildResumeFromLines,
  detectDocumentLocale,
) {
  // Keep selected PDF.js token boundaries and x/y coordinates from the source
  // PDF. Flattened, hand-ordered strings cannot reproduce same-row right
  // metadata or compatibility ideographs emitted by the original PDF font.
  const lines = textContentToLines(
    zhMinimalStructureFixture,
    zhMinimalStructureFixture.page,
  );
  const resume = buildResumeFromLines(lines, "导入内容");

  assert.equal(detectDocumentLocale(lines), "zh");

  for (const section of resume.sections.filter(
    (candidate) => candidate.kind === "simple_list",
  )) {
    for (const item of section.items) {
      assert.deepEqual(
        Object.keys(item).sort(),
        ["content", "id"],
        "simple-list imports must use only their semantic content field",
      );
    }
  }

  assert.ok(
    lines.some((line) => line.text === "项目经历"),
    "CJK compatibility ideographs in 项⽬经历 should normalize before parsing",
  );
  assert.ok(
    lines.some((line) => /^语言[:：]/.test(line.text)),
    "CJK compatibility ideographs in 语⾔ should normalize before parsing",
  );

  const companyLine = requiredLine(lines, "腾讯");
  const businessLine = requiredLine(lines, "企业协同产品线");
  assert.ok(
    Math.abs(companyLine.y - businessLine.y) <= 2,
    "company and business line should remain on the same visual row",
  );
  assert.ok(
    companyLine.x < businessLine.x,
    "same-row fields should preserve their left-to-right x order",
  );

  const education = requiredSection(resume, "education");
  assert.equal(education.items.length, 1);
  assert.deepEqual(selectItemFields(education.items[0]), {
    title: "浙江大学",
    subtitle: "计算机科学与技术 本科",
    meta: "GPA 3.85 / 4.0",
    period: "2019.09 - 2023.06",
    description: "主修前端工程、数据结构、软件工程与机器学习相关课程。",
    highlights: [
      "获得校一等奖学金。",
      "毕业设计围绕智能内容生成工具展开。",
    ],
  });

  const internship = requiredSection(resume, "internship");
  assert.equal(internship.items.length, 1);
  assert.deepEqual(selectItemFields(internship.items[0]), {
    title: "腾讯",
    subtitle: "前端开发实习生",
    meta: "企业协同产品线",
    period: "2022.07 - 2022.09",
    description: "参与后台管理系统和内容编辑器的体验优化。",
    highlights: [
      "负责编辑器表单模块重构，页面状态管理复杂度显著下降。",
      "联动设计与测试完善交互细节，减少线上样式回归问题。",
    ],
  });

  const project = requiredSection(resume, "project");
  assert.equal(project.items.length, 1);
  assert.deepEqual(selectItemFields(project.items[0]), {
    title: "Reseno",
    subtitle: "AI Agent 简历制作网站",
    meta: "React · TypeScript · Tailwind · shadcn/ui",
    period: "2026.03 - 至今",
    description: "实现实时编辑、A4 预览、可折叠 section、关键词匹配与 PDF 导出。",
    highlights: [
      "将编辑器与真实简历版式拆分为结构化数据模型，渲染更加稳定。",
      "通过 AI Copilot 对 JD 关键词进行识别，并提供简历内容增强建议。",
    ],
  });

  const other = requiredSection(resume, "other");
  assert.equal(other.items.length, 1);
  assert.equal(
    other.items[0].content,
    "<ul><li>技能：React、TypeScript、Node.js、Prompt Engineering</li><li>语言：英语 CET-6（544），雅思 6.5</li></ul>",
  );

  assert.equal(resume.basic.name, "王小明");
  assert.equal(resume.basic.headline, "前端开发工程师 / AI 应用方向");
  assert.equal(resume.basic.phone, "+86 138 0000 0000");
  assert.equal(resume.basic.email, "xiaoming@example.com");
  assert.equal(resume.basic.location, "杭州");
  assert.equal(
    resume.basic.summary,
    "关注 AI Agent 与简历工作流产品，熟悉 React、TypeScript 与实时渲染，能够将复杂编辑体验整理为结构清晰、适合导出的简历页面。",
  );
  assert.deepEqual(
    resume.basic.customFields.map(({ label, value, type }) => ({
      label,
      value,
      type,
    })),
    [
      {
        label: "GitHub",
        value: "github.com/xiaoming",
        type: "url",
      },
      {
        label: "作品集",
        value: "www.xiaoming.dev",
        type: "url",
      },
    ],
  );
}

function requiredLine(lines, text) {
  const matched = lines.find((line) => line.text === text);
  assert.ok(matched, `Expected extracted line: ${text}`);
  return matched;
}

function requiredSection(resume, kind) {
  const semanticKind = {
    work: "experience",
    internship: "experience",
    skills: "simple_list",
    languages: "simple_list",
    other: "simple_list",
    awards: "achievement",
  }[kind] ?? kind;
  const titleMatcher = {
    internship: /intern|实习/i,
    skills: /skill|技能|技术栈/i,
    languages: /language|语言/i,
    other: /other|其他|自定义/i,
  }[kind];
  const candidates = resume.sections.filter(
    (candidate) => candidate.kind === semanticKind,
  );
  const section = candidates.find(
    (candidate) =>
      (!titleMatcher || titleMatcher.test(candidate.title)),
  ) ?? (kind === "internship" && candidates.length === 1
    ? candidates[0]
    : undefined);
  assert.ok(section, `Expected imported section kind: ${kind}`);
  return section;
}

function selectItemFields(item) {
  if ("school" in item) {
    return {
      title: item.school,
      subtitle: [item.degree, item.major].filter(Boolean).join(" · "),
      meta: [item.gpa, item.location].filter(Boolean).join(" · "),
      period: item.period,
      description: item.description,
      highlights: item.highlights,
    };
  }

  if ("company" in item) {
    return {
      title: item.company,
      subtitle: item.position,
      meta: item.location,
      period: item.period,
      description: item.description,
      highlights: item.highlights,
    };
  }

  if ("techStack" in item) {
    return {
      title: item.name,
      subtitle: item.role,
      meta: item.techStack.join(" · "),
      period: item.period,
      description: item.description,
      highlights: item.highlights,
    };
  }

  return {
    title: item?.name ?? "",
    subtitle: item?.issuer ?? "",
    meta: "",
    period: item?.date ?? "",
    description: item?.description ?? "",
    highlights: [],
  };
}

function jsonResponse(data) {
  return new Response(
    JSON.stringify({
      code: 0,
      data,
      message: "SUCCESS",
    }),
    { headers: { "Content-Type": "application/json" }, status: 200 },
  );
}

function createPdfFile(pages) {
  const objects = new Map();
  const pageObjectIds = pages.map((_, index) => 4 + index * 2);
  const contentObjectIds = pages.map((_, index) => 5 + index * 2);

  objects.set(1, "<< /Type /Catalog /Pages 2 0 R >>");
  objects.set(
    2,
    `<< /Type /Pages /Kids [${pageObjectIds
      .map((objectId) => `${objectId} 0 R`)
      .join(" ")}] /Count ${pages.length} >>`,
  );
  objects.set(
    3,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  );

  pages.forEach((lines, index) => {
    const pageObjectId = pageObjectIds[index];
    const contentObjectId = contentObjectIds[index];
    const stream = [
      "BT",
      "/F1 14 Tf",
      "18 TL",
      "72 760 Td",
      ...lines.flatMap((line, lineIndex) => [
        ...(lineIndex > 0 ? ["T*"] : []),
        `(${escapePdfString(line)}) Tj`,
      ]),
      "ET",
    ].join("\n");

    objects.set(
      pageObjectId,
      [
        "<< /Type /Page",
        "/Parent 2 0 R",
        "/MediaBox [0 0 612 792]",
        "/Resources << /Font << /F1 3 0 R >> >>",
        `/Contents ${contentObjectId} 0 R >>`,
      ].join(" "),
    );
    objects.set(
      contentObjectId,
      `<< /Length ${Buffer.byteLength(stream, "ascii")} >>\nstream\n${stream}\nendstream`,
    );
  });

  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  const objectCount = Math.max(...objects.keys());

  for (let objectId = 1; objectId <= objectCount; objectId += 1) {
    offsets[objectId] = Buffer.byteLength(pdf, "ascii");
    pdf += `${objectId} 0 obj\n${objects.get(objectId)}\nendobj\n`;
  }

  const xrefOffset = Buffer.byteLength(pdf, "ascii");
  pdf += `xref\n0 ${objectCount + 1}\n`;
  pdf += "0000000000 65535 f \n";
  for (let objectId = 1; objectId <= objectCount; objectId += 1) {
    pdf += `${String(offsets[objectId]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += [
    "trailer",
    `<< /Size ${objectCount + 1} /Root 1 0 R >>`,
    "startxref",
    String(xrefOffset),
    "%%EOF",
    "",
  ].join("\n");

  return new File([Buffer.from(pdf, "ascii")], "public-entry.pdf", {
    type: "application/pdf",
  });
}

function escapePdfString(value) {
  return value.replaceAll("\\", "\\\\").replaceAll("(", "\\(").replaceAll(")", "\\)");
}

function textItem(text, x, y, overrides = {}) {
  return {
    str: text,
    transform: [1, 0, 0, 10, x, y],
    width: text.length * 10,
    height: 10,
    ...overrides,
  };
}

function line(text, index, fontSize = 10) {
  return {
    text,
    page: 1,
    x: 40,
    y: 800 - index * 20,
    fontSize,
  };
}

function positionedLine(text, y, x = 40, fontSize = 10, pageWidth) {
  return {
    text,
    page: 1,
    ...(pageWidth ? { pageWidth } : {}),
    x,
    y,
    fontSize,
  };
}
