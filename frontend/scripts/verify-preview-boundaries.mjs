import { access, readFile, readdir } from "node:fs/promises";

const frontendRoot = new URL("../", import.meta.url);
const srcRoot = new URL("src/", frontendRoot);
const previewRoot = new URL("components/preview/", srcRoot);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function readCssRule(source, selector) {
  const marker = `${selector} {`;
  const start = source.indexOf(marker);

  assert(start >= 0, `Missing preview style rule: ${selector}`);
  const end = source.indexOf("}", start + marker.length);
  assert(end >= 0, `Unclosed preview style rule: ${selector}`);
  return source.slice(start + marker.length, end);
}

async function readSource(path) {
  return readFile(new URL(path, srcRoot), "utf8");
}

async function resolvePreviewImport(modulePath) {
  const candidates = [`${modulePath}.ts`, `${modulePath}.tsx`];

  for (const candidate of candidates) {
    const url = new URL(candidate, srcRoot);

    try {
      await access(url);
      return candidate;
    } catch (error) {
      if (error?.code !== "ENOENT") {
        throw error;
      }
    }
  }

  return null;
}

async function collectThumbnailPreviewClosure() {
  const entry = "components/preview/resume-thumbnail.tsx";
  const queue = [entry];
  const sources = new Map();

  while (queue.length > 0) {
    const path = queue.shift();

    if (!path || sources.has(path)) {
      continue;
    }

    const source = await readSource(path);
    sources.set(path, source);

    for (const match of source.matchAll(
      /from\s+["']@\/(components\/preview\/[^"']+)["']/g,
    )) {
      const importedPath = await resolvePreviewImport(match[1]);

      if (importedPath && !sources.has(importedPath)) {
        queue.push(importedPath);
      }
    }
  }

  return sources;
}

const [
  resumeGallery,
  resumeGalleryCard,
  templateGallery,
  templateGalleryCard,
  recycleBinThumbnail,
  documentPreview,
  indexCss,
  pdfExport,
  previewDiffText,
  previewDiffPrecision,
  previewRichDiff,
  previewPages,
  previewSectionItems,
  previewSections,
] =
  await Promise.all([
    readSource("components/resume-gallery.tsx"),
    readSource("components/resume-gallery-card.tsx"),
    readSource("components/templates/template-gallery.tsx"),
    readSource("components/templates/template-gallery-card.tsx"),
    readSource("components/recycle-bin-item-row.tsx"),
    readSource("components/preview/document-preview-card.tsx"),
    readSource("index.css"),
    readSource("components/pdf-export-renderer.tsx"),
    readSource("components/preview/resume-preview-diff-text.tsx"),
    readSource("components/preview/resume-preview-diff-precision.tsx"),
    readSource("components/preview/resume-preview-rich-diff.tsx"),
    readSource("components/preview/resume-preview-pages.tsx"),
    readSource("components/preview/resume-preview-section-items.tsx"),
    readSource("components/preview/resume-preview-sections.tsx"),
  ]);
const thumbnailCallers = [
  resumeGalleryCard,
  templateGalleryCard,
  recycleBinThumbnail,
];

assert(
  !/resume-thumbnail/.test(resumeGallery) &&
    !/resume-thumbnail/.test(templateGallery),
  "Gallery route entries must leave thumbnail rendering inside memoized cards.",
);
assert(
  (previewPages.match(/aria-hidden="true"/g)?.length ?? 0) === 2 &&
    (previewPages.match(/\sinert/g)?.length ?? 0) === 2,
  "Both standard and sidebar measurement copies must be aria-hidden and inert.",
);
assert(
  thumbnailCallers.every(
    (source) =>
      /from\s+["']@\/components\/preview\/resume-thumbnail["']/.test(
        source,
      ) &&
      !/from\s+["']@\/components\/preview\/resume-preview["']/.test(
        source,
      ) &&
      !/ResizeObserver|useLayoutEffect|variant=["']thumbnail["']/.test(source),
  ),
  "Gallery and trash routes must consume only the lightweight ResumeThumbnail seam.",
);

assert(
  [documentPreview, pdfExport].every((source) =>
    /from\s+["']@\/components\/preview\/resume-preview["']/.test(source),
  ),
  "Detail and PDF renderers must retain the paginated ResumePreview seam.",
);

const diffBaseRule = readCssRule(indexCss, ".resume-diff");
const diffAnchorRule = readCssRule(indexCss, ".resume-diff-anchor");
const diffLabelRule = readCssRule(
  indexCss,
  ":is(.resume-diff, .resume-diff-anchor)::after",
);
const diffFieldRule = readCssRule(indexCss, ".resume-diff-field");
const diffInlineRule = readCssRule(indexCss, ".resume-diff-inline");
const boxedSectionDiffRule = readCssRule(
  indexCss,
  '.resume-section[data-resume-section-layout="boxed"].resume-diff',
);
const boxedSectionDiffLabelRule = readCssRule(
  indexCss,
  '.resume-section[data-resume-section-layout="boxed"].resume-diff::after',
);
const diffSurfaceRules = ["added", "moved"].map(
  (kind) => readCssRule(indexCss, `.resume-diff--${kind}`),
);

assert(
  !/margin-inline|padding-inline|outline(?:-offset)?\s*:/.test(diffBaseRule) &&
    !/padding|background|box-shadow/.test(diffAnchorRule),
  "Resume diff locators must not change text width, pagination, or tint an unchanged item.",
);
assert(
  !/\.resume-diff::before|@keyframes\s+resume-diff-scan/.test(indexCss),
  "Resume diff surfaces must not recreate an outer ring with a transient scan animation.",
);
assert(
  diffSurfaceRules.every(
    (rule) =>
      /background:\s*rgba\(/.test(rule) &&
      !/linear-gradient|inset\s+3px\s+0/.test(rule),
  ),
  "Every visible resume diff kind must use one quiet flat surface without a left rail or gradient.",
);
assert(
  !/\.resume-diff--deleted/.test(indexCss),
  "Deleted content must not create a preview surface over the candidate resume.",
);
assert(
  !/\.resume-diff--modified\s*\{/.test(indexCss) &&
    /box-decoration-break:\s*clone/.test(diffFieldRule) &&
    /background:\s*rgba\(/.test(diffInlineRule) &&
    /data-resume-diff-path/.test(previewDiffPrecision) &&
    /lazy\(\(\)\s*=>/.test(previewDiffText) &&
    /getRenderableFieldDiffs/.test(previewSectionItems) &&
    !/getDiffClassName\(diff\)/.test(previewSectionItems),
  "Modified drafts must mark canonical fields and inline fragments instead of styling an entire item.",
);
assert(
  !/resume-preview-deletion-marker|resume-diff-(?:deletion-marker|inline-deletion|structural-deletion|deletion-anchor)/.test(
    [
      indexCss,
      previewDiffPrecision,
      previewRichDiff,
      previewSectionItems,
      previewSections,
    ].join("\n"),
  ) &&
    !/IntersectionObserver|TooltipProvider|TooltipTrigger/.test(
      [previewDiffPrecision, previewRichDiff, previewSectionItems, previewSections].join(
        "\n",
      ),
    ),
  "Resume previews must never place deletion controls over candidate text; deleted values belong in the change summary.",
);
assert(
  /font-size:\s*7px/.test(diffLabelRule),
  "Resume diff labels must remain readable after the A4 preview is scaled down.",
);
assert(
  /box-shadow:\s*none/.test(boxedSectionDiffRule) &&
    /top:\s*0\.35rem/.test(boxedSectionDiffLabelRule) &&
    /right:\s*0\.35rem/.test(boxedSectionDiffLabelRule) &&
    (previewSections.match(/data-resume-diff-label=\{getDiffLabel\(markerDiff, t\)\}/g)
      ?.length ?? 0) === 3 &&
    (previewSections.match(/data-resume-section-layout=\{layout\.section\}/g)
      ?.length ?? 0) === 3,
  "Section-level diffs must expose an unclipped status label without disturbing or doubling the boxed template border.",
);

const thumbnailClosure = await collectThumbnailPreviewClosure();
const resumeThumbnail = thumbnailClosure.get(
  "components/preview/resume-thumbnail.tsx",
);
const thumbnailDependencySource = Array.from(thumbnailClosure.entries())
  .map(([path, source]) => `${path}\n${source}`)
  .join("\n");

assert(
  thumbnailClosure.has("components/preview/resume-thumbnail.tsx") &&
    thumbnailClosure.has("components/preview/resume-preview-content.tsx") &&
    !/resume-preview-pagination|resume-preview-pages|ResizeObserver|useLayoutEffect/.test(
      thumbnailDependencySource,
    ),
  "The ResumeThumbnail dependency closure must not include pagination or layout observers.",
);
assert(
  /enableContactLinks=\{false\}/.test(resumeThumbnail ?? "") &&
    !/onMoveTemplateImage|editableTemplateImages/.test(resumeThumbnail ?? ""),
  "ResumeThumbnail must remain non-interactive inside linked gallery cards.",
);

const previewEntries = await readdir(previewRoot, { withFileTypes: true });
const previewTsxEntries = previewEntries.filter(
  (entry) => entry.isFile() && entry.name.endsWith(".tsx"),
);

for (const entry of previewTsxEntries) {
  const source = await readFile(new URL(entry.name, previewRoot), "utf8");
  const lineCount = source.split(/\r\n|\n|\r/).length - 1;

  assert(
    lineCount <= 500,
    `components/preview/${entry.name} has ${lineCount} lines; expected at most 500.`,
  );
}

const sourceBudgets = await readFile(
  new URL("scripts/verify-source-budgets.mjs", frontendRoot),
  "utf8",
);

assert(
  !/LEGACY_FILE_CEILINGS[\s\S]*?src\/components\/preview\/resume-preview\.tsx/.test(
    sourceBudgets,
  ) &&
    !/LEGACY_COMPONENT_CEILINGS[\s\S]*?src\/components\/preview\/resume-preview\.tsx#ResumePreview/.test(
      sourceBudgets,
    ),
  "ResumePreview must stay on the default file and React-body budgets.",
);

console.log("Preview thumbnail and pagination module boundaries verified.");
