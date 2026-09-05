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
  documentCanvas,
  documentCanvasHook,
  documentCanvasModel,
  indexCss,
  pdfExport,
  previewDiffText,
  previewDiffPrecision,
  previewRichDiff,
  previewPages,
  previewBasicInfo,
  previewContent,
  previewDiffBadge,
  previewDeletedAnchor,
  draftReviewComparison,
  draftReviewPopover,
  previewSectionItems,
  previewSections,
] =
  await Promise.all([
    readSource("components/resume-gallery.tsx"),
    readSource("components/resume-gallery-card.tsx"),
    readSource("components/templates/template-gallery.tsx"),
    readSource("components/templates/template-gallery-card.tsx"),
    readSource("components/recycle-bin-table.tsx"),
    readSource("components/preview/document-canvas.tsx"),
    readSource("components/preview/use-document-canvas.ts"),
    readSource("components/preview/document-canvas-model.ts"),
    readSource("index.css"),
    readSource("components/pdf-export-renderer.tsx"),
    readSource("components/preview/resume-preview-diff-text.tsx"),
    readSource("components/preview/resume-preview-diff-precision.tsx"),
    readSource("components/preview/resume-preview-rich-diff.tsx"),
    readSource("components/preview/resume-preview-pages.tsx"),
    readSource("components/preview/resume-preview-basic-info.tsx"),
    readSource("components/preview/resume-preview-content.tsx"),
    readSource("components/preview/resume-preview-diff-badge.tsx"),
    readSource("components/preview/resume-preview-deleted-anchor.tsx"),
    readSource("components/preview/resume-draft-review-comparison.tsx"),
    readSource("components/preview/resume-draft-review-popover.tsx"),
    readSource("components/preview/resume-preview-section-items.tsx"),
    readSource("components/preview/resume-preview-sections.tsx"),
  ]);
const thumbnailCallers = [
  resumeGalleryCard,
  templateGalleryCard,
  recycleBinThumbnail,
];
const thumbnailPaperRule = readCssRule(indexCss, ".resume-page--thumbnail");
const printPaperRule = readCssRule(
  indexCss.slice(indexCss.indexOf("@media print")),
  ".resume-page",
);

assert(
  !/from\s+["']@\/components\/preview\/resume-thumbnail["']/.test(
    resumeGallery,
  ) &&
    !/from\s+["']@\/components\/preview\/resume-thumbnail["']/.test(
      templateGallery,
    ),
  "Gallery route entries must leave thumbnail rendering inside memoized cards.",
);
assert(
  (previewPages.match(/aria-hidden="true"/g)?.length ?? 0) === 2 &&
    (previewPages.match(/\sinert/g)?.length ?? 0) === 2,
  "Both standard and sidebar measurement copies must be aria-hidden and inert.",
);
assert(
  !/resume-page-label|Page \$\{pageIndex \+ 1\}/.test(previewPages) &&
    !/\.resume-page-label\s*\{/.test(indexCss),
  "Page numbering must live in the canvas controls instead of repeating above every sheet.",
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
  [documentCanvas, pdfExport].every((source) =>
    /from\s+["']@\/components\/preview\/resume-preview["']/.test(source),
  ),
  "Detail and PDF renderers must retain the paginated ResumePreview seam.",
);
assert(
  !/layoutTransitionKey|PREVIEW_LAYOUT_MOTION|previewLayoutAnimationRef|previewScaleBoxRectRef|shouldAnimateNextLayoutRef|\.animate\(/.test(
    documentCanvas,
  ),
  "Preview resizing must not recreate a FLIP animation or a layout-transition prop.",
);
assert(
  !/showPreviewTitle|previewTitle/.test(documentCanvas),
  "The document surface must not render a redundant visual preview title.",
);
assert(
  [thumbnailPaperRule, printPaperRule].every(
    (rule) =>
      /border:\s*0/.test(rule) &&
      /border-radius:\s*0/.test(rule) &&
      /box-shadow:\s*none/.test(rule),
  ),
  "Thumbnail and print renderers must remove interactive paper chrome.",
);
assert(
  /new ResizeObserver\(/.test(documentCanvasHook) &&
    /resizeObserver\.observe\(viewport\)/.test(documentCanvasHook) &&
    /scrollBy/.test(documentCanvasHook) &&
    /setPointerCapture/.test(documentCanvasHook) &&
    /addEventListener\("wheel", handleWheel, \{ passive: false \}\)/.test(
      documentCanvasHook,
    ) &&
    /event\.key === "0"/.test(documentCanvasHook) &&
    /viewport\.style\.setProperty\("--canvas-scale", String\(scale\)\)/.test(
      documentCanvasHook,
    ) &&
    /data-document-canvas-paper/.test(documentCanvas) &&
    /zoom:\s*var\(--canvas-scale, 1\)/.test(indexCss) &&
    /role="region"/.test(documentCanvas) &&
    /canvasControls\.map/.test(documentCanvas) &&
    /DOCUMENT_CANVAS_MIN_SCALE = 0\.25/.test(documentCanvasModel) &&
    /DOCUMENT_CANVAS_MAX_SCALE = 2/.test(documentCanvasModel) &&
    !/layoutTransitionKey|PREVIEW_LAYOUT_MOTION|\.animate\(/.test(
      documentCanvas + documentCanvasHook,
    ),
  "The document canvas must own bounded wheel and keyboard zoom, anchored scrolling, and pointer panning without FLIP motion.",
);
assert(
  /className="mt-\[1\.25em\]"/.test(previewContent) &&
    (previewSections.match(/showTitle \? "mt-\[0\.25em\]"/g)?.length ?? 0) === 2 &&
    (previewSections.match(/leading-\[1\.2\]/g)?.length ?? 0) === 5 &&
    /resume-item relative grid gap-\[0\.375em\]/.test(previewSectionItems),
  "Shared resume structure spacing must use the compact font-relative defaults.",
);

const diffBaseRule = readCssRule(indexCss, ".resume-diff");
const diffLabelHostRule = readCssRule(indexCss, ".resume-diff-label-host");
const diffBadgeRule = readCssRule(indexCss, ".resume-diff-badge");
const diffFieldRule = readCssRule(indexCss, ".resume-diff-field");
const diffInlineRule = readCssRule(indexCss, ".resume-diff-inline");
const boxedSectionDiffRule = readCssRule(
  indexCss,
  '.resume-section[data-resume-section-layout="boxed"].resume-diff',
);
const diffSurfaceRules = ["added", "moved", "deleted"].map(
  (kind) => readCssRule(indexCss, `.resume-diff--${kind}`),
);

assert(
  !/margin-inline|padding-inline|outline(?:-offset)?\s*:/.test(diffBaseRule),
  "Structural diff locators must not change text width or pagination.",
);
assert(
  /padding-top:\s*1rem/.test(diffLabelHostRule) &&
    !/padding-inline|margin-inline/.test(diffLabelHostRule) &&
    /position:\s*absolute/.test(diffBadgeRule) &&
    /top:\s*0/.test(diffBadgeRule) &&
    /height:\s*0\.875rem/.test(diffBadgeRule),
  "Resume diff labels must occupy a measured top lane instead of covering resume text.",
);
assert(
  /from\s+["']@\/components\/ui\/badge["']/.test(previewDiffBadge) &&
    /data-resume-diff-badge/.test(previewDiffBadge) &&
    [previewBasicInfo, previewSectionItems, previewSections].every((source) =>
      /ResumeDiffBadge/.test(source),
    ),
  "Every resume preview surface must render the shared visible diff badge.",
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
  /resume-diff-deleted-anchor/.test(previewDeletedAnchor) &&
    /data-resume-diff-path/.test(previewDeletedAnchor) &&
    /interleaveDeletedDiffs/.test(previewSectionItems) &&
    /interleaveDeletedDiffs/.test(previewSections),
  "Deleted items and sections must retain a locatable review anchor beside surviving content.",
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
  !/IntersectionObserver|TooltipProvider|TooltipTrigger/.test(
      [previewDiffPrecision, previewRichDiff, previewSectionItems, previewSections].join(
        "\n",
      ),
    ) &&
    /<Popover/.test(draftReviewPopover) &&
    /ResumeDraftReviewComparison/.test(draftReviewPopover) &&
    /formatAgentDiffValue/.test(draftReviewComparison) &&
    /onSelectReviewItem/.test(draftReviewPopover),
  "Diff comparison must use one delegated popover while the preview content remains free of duplicated controls.",
);
assert(
  /font-size:\s*7px/.test(diffBadgeRule),
  "Resume diff labels must remain readable after the A4 preview is scaled down.",
);
assert(
  /box-shadow:\s*none/.test(boxedSectionDiffRule) &&
    (previewSections.match(/data-resume-diff-label=\{getDiffLabel\(markerDiff, t\)\}/g)
      ?.length ?? 0) === 3 &&
    (previewSections.match(/data-resume-section-layout=\{layout\.section\}/g)
      ?.length ?? 0) === 3,
  "Section-level diffs must expose one in-bounds status label without doubling the boxed template border.",
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
assert(
  /onMoveTemplateImage\?:/.test(documentCanvas) &&
    /Boolean\(props\.onMoveTemplateImage\)/.test(documentCanvas),
  "Template previews must become editable only when an image-move command is provided.",
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
