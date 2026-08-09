import { readFile } from "node:fs/promises";

const resumePreview = await readFile(
  new URL("../src/components/preview/resume-preview.tsx", import.meta.url),
  "utf8",
);
const resumeFontLoader = await readFile(
  new URL(
    "../src/components/preview/resume-font-loader.ts",
    import.meta.url,
  ),
  "utf8",
);
const resumePagination = await readFile(
  new URL(
    "../src/components/preview/resume-preview-pagination.ts",
    import.meta.url,
  ),
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
  /PAGINATION_STABLE_FRAME_COUNT\s*=\s*2/.test(resumePagination),
  "Pagination readiness must require two matching animation-frame measurements.",
);
assert(
  /const resumeFontReadyToken\s*=\s*useResumeFontReadyToken\(fontFamily, resume, t\)/.test(
    resumePreview,
  ) &&
    /useResumePagination\(\s*model,\s*resumeFontReadyToken,?\s*\)/.test(
      resumePreview,
    ) &&
    /useLayoutEffect\(\(\)\s*=>\s*\{\s*if \(!resumeFontReadyToken\)\s*\{\s*return/.test(
      resumePagination,
    ) &&
    /await loadResumeFontStyles\(fontFamily\)[\s\S]*?await waitForAnimationFrame\(\)[\s\S]*?document\.fonts\?\.ready/.test(
      resumeFontLoader,
    ),
  "Pagination must settle the conditional stylesheet before waiting for its font and measuring.",
);
assert(
  !/measuredContentHeight\s*\+\s*addedSpacerDelta\s*-\s*PAGINATION_TOLERANCE_PX/.test(
    resumePagination,
  ),
  "Final page count must not hide real overflow behind the orphan tolerance.",
);
assert(
  /onPaginationReadyChange=\{handlePaginationReadyChange\}/.test(
    pdfExportRenderer,
  ),
  "PDF export must consume ResumePreview pagination readiness.",
);
assert(
  /const isReady\s*=\s*Boolean\([\s\S]*?activeState[\s\S]*?assetsReadyLoadKey\s*===\s*loadKey[\s\S]*?paginationReadyLoadKey\s*===\s*loadKey[\s\S]*?\)/.test(
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
