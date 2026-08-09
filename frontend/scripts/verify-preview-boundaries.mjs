import { access, readFile, readdir } from "node:fs/promises";

const frontendRoot = new URL("../", import.meta.url);
const srcRoot = new URL("src/", frontendRoot);
const previewRoot = new URL("components/preview/", srcRoot);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
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
  pdfExport,
] =
  await Promise.all([
    readSource("components/resume-gallery.tsx"),
    readSource("components/resume-gallery-card.tsx"),
    readSource("components/templates/template-gallery.tsx"),
    readSource("components/templates/template-gallery-card.tsx"),
    readSource("components/recycle-bin-item-row.tsx"),
    readSource("components/preview/document-preview-card.tsx"),
    readSource("components/pdf-export-renderer.tsx"),
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
