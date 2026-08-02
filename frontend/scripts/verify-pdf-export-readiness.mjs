import { readFile } from "node:fs/promises";

const resumePreview = await readFile(
  new URL("../src/components/preview/resume-preview.tsx", import.meta.url),
  "utf8",
);
const pdfExportRenderer = await readFile(
  new URL("../src/components/pdf-export-renderer.tsx", import.meta.url),
  "utf8",
);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

assert(
  /onPaginationReadyChange\?:\s*\(ready:\s*boolean\)\s*=>\s*void/.test(
    resumePreview,
  ),
  "ResumePreview must expose explicit pagination readiness.",
);
assert(
  /PAGINATION_STABLE_FRAME_COUNT\s*=\s*2/.test(resumePreview),
  "Pagination readiness must require two matching animation-frame measurements.",
);
assert(
  !/measuredContentHeight\s*\+\s*addedSpacerDelta\s*-\s*PAGINATION_TOLERANCE_PX/.test(
    resumePreview,
  ),
  "Final page count must not hide real overflow behind the orphan tolerance.",
);
assert(
  /onPaginationReadyChange=\{setIsPaginationReady\}/.test(pdfExportRenderer),
  "PDF export must consume ResumePreview pagination readiness.",
);
assert(
  /const isReady\s*=\s*Boolean\(state\s*&&\s*areAssetsReady\s*&&\s*isPaginationReady\)/.test(
    pdfExportRenderer,
  ),
  "PDF export readiness must wait for both assets and stable pagination.",
);
assert(
  !/window\.print\(|shouldPrint|searchParams\.get\(["']print["']\)/.test(
    pdfExportRenderer,
  ),
  "The render route must not own browser print-dialog behavior.",
);

console.log("PDF export readiness contract verified.");
