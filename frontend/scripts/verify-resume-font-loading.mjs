import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const sourceRoot = new URL("../src/", import.meta.url);
const [
  mainEntry,
  fontLoader,
  thumbnail,
  resumeGallery,
  templateGallery,
  recycleBinPanel,
  previewStyles,
] = await Promise.all([
  readFile(new URL("main.tsx", sourceRoot), "utf8"),
  readFile(
    new URL("components/preview/resume-font-loader.ts", sourceRoot),
    "utf8",
  ),
  readFile(
    new URL("components/preview/resume-thumbnail.tsx", sourceRoot),
    "utf8",
  ),
  readFile(new URL("components/resume-gallery.tsx", sourceRoot), "utf8"),
  readFile(
    new URL("components/templates/template-gallery.tsx", sourceRoot),
    "utf8",
  ),
  readFile(new URL("components/recycle-bin-panel.tsx", sourceRoot), "utf8"),
  readFile(
    new URL("components/preview/resume-preview-styles.ts", sourceRoot),
    "utf8",
  ),
]);

assert(
  mainEntry.includes("@fontsource-variable/inter/wght.css") &&
    mainEntry.includes("@fontsource-variable/ibm-plex-sans/wght.css") &&
    mainEntry.includes("@fontsource/ibm-plex-mono/latin-400.css") &&
    mainEntry.includes("@fontsource/ibm-plex-mono/latin-500.css"),
  "Existing UI, Plex, and monospace fonts must remain globally available.",
);
assert(
  !mainEntry.includes("@fontsource-variable/noto-sans-sc/wght.css") &&
    !mainEntry.includes("@fontsource-variable/noto-serif-sc/wght.css"),
  "Noto resume fonts must not remain in the application entrypoint.",
);
assert(
  /import\(\s*["']@fontsource-variable\/noto-sans-sc\/wght\.css["']\s*\)/.test(
    fontLoader,
  ) &&
    /import\(\s*["']@fontsource-variable\/noto-serif-sc\/wght\.css["']\s*\)/.test(
      fontLoader,
    ),
  "Both Noto stylesheets must use statically analyzable dynamic imports.",
);
assert(
  !thumbnail.includes("useResumeFontReadyToken") &&
    !thumbnail.includes("resume-font-loader"),
  "ResumeThumbnail must stay render-only and must not maintain font-ready state.",
);
assert(
  [resumeGallery, templateGallery, recycleBinPanel].every(
    (source) =>
      source.includes("useResumeThumbnailFonts") &&
      /useResumeThumbnailFonts\(/.test(source),
  ),
  "Each thumbnail collection must prepare its visible font set at collection scope.",
);
assert(
  /inter:\s*[\s\S]{0,300}Noto Sans SC Variable/.test(previewStyles) &&
    /noto_sans_sc:\s*[\s\S]{0,300}Noto Sans SC Variable/.test(previewStyles) &&
    /plex:\s*[\s\S]{0,300}Noto Sans SC Variable/.test(previewStyles) &&
    /serif:\s*[\s\S]{0,300}Noto Serif SC Variable/.test(previewStyles),
  "Conditional assets must preserve the exact preview font fallback stacks.",
);

console.log("Conditional resume font loading verified.");
