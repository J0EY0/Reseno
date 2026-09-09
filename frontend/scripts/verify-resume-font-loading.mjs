import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { evaluateTypeScript } from "./typescript-module.mjs";

const sourceRoot = new URL("../src/", import.meta.url);
const [
  mainEntry,
  fontLoader,
  thumbnailFonts,
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
    new URL("components/preview/resume-thumbnail-fonts.ts", sourceRoot),
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
  /resumeFontStyleLoaders[\s\S]*?inter:\s*loadNotoSansStyles[\s\S]*?noto_sans_sc:\s*loadNotoSansStyles[\s\S]*?plex:\s*loadNotoSansStyles[\s\S]*?serif:\s*loadNotoSerifStyles/.test(
    fontLoader,
  ),
  "Every persisted resume font must map to its required Noto fallback.",
);
assert(
  /export function useResumeThumbnailFonts\(/.test(thumbnailFonts) &&
    /useEffect\([\s\S]*?loadResumeFontStyles\(/.test(thumbnailFonts) &&
    /\[needsSansStyles, needsSerifStyles\]/.test(thumbnailFonts),
  "Thumbnail font styles must be prepared once by a shared owner hook.",
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

const requestedFonts = [];
const thumbnailFontModule = evaluateTypeScript(thumbnailFonts, {
  imports: {
    react: { useEffect: (effect) => effect() },
    "@/components/preview/resume-font-loader": {
      loadResumeFontStyles(fontFamily) {
        requestedFonts.push(fontFamily);
        return Promise.resolve();
      },
    },
  },
});
for (const [fontFamilies, expectedFonts] of [
  [["times"], ["serif"]],
  [
    ["times", "serif", "inter"],
    ["inter", "serif"],
  ],
  [[], []],
]) {
  requestedFonts.length = 0;
  thumbnailFontModule.useResumeThumbnailFonts(fontFamilies);
  assert.deepEqual(
    requestedFonts,
    expectedFonts,
    "Thumbnail collections must load each required script font only once.",
  );
}

console.log("Conditional resume font loading verified.");
