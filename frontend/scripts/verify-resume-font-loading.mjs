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
  sansFonts,
  serifFonts,
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
  readFile(new URL("assets/fonts/resume-sans.css", sourceRoot), "utf8"),
  readFile(new URL("assets/fonts/resume-serif.css", sourceRoot), "utf8"),
]);

assert(
  mainEntry.includes("@fontsource-variable/inter/wght.css") &&
    mainEntry.includes("@fontsource/ibm-plex-mono/latin-400.css") &&
    mainEntry.includes("@fontsource/ibm-plex-mono/latin-500.css"),
  "UI and monospace fonts must remain globally available.",
);
assert(
  !/@fontsource(?:-variable)?\/(?:noto-|ibm-plex-sans)/.test(mainEntry),
  "Resume fonts must not remain in the application entrypoint.",
);
for (const family of [
  "inter",
  "ibm-plex-sans",
  "noto-sans-sc",
  "noto-serif-sc",
]) {
  for (const weight of [400, 500, 600, 700, 800]) {
    if (family === "ibm-plex-sans" && weight === 800) continue;
    assert(
      (family === "noto-serif-sc" ? serifFonts : sansFonts).includes(
        `@import "@fontsource/${family}/${weight}.css"`,
      ),
      `${family} ${weight} must be included in the resume font stylesheet.`,
    );
  }
}
assert(
  fontLoader.includes('import("@/assets/fonts/resume-sans.css")') &&
    fontLoader.includes('import("@/assets/fonts/resume-serif.css")'),
  "Both resume font stylesheets must use statically analyzable dynamic imports.",
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
  !previewStyles.includes(' Variable"') &&
    /inter:\s*[\s\S]{0,200}Noto Sans SC/.test(previewStyles) &&
    /noto_sans_sc:\s*[\s\S]{0,200}Noto Sans SC/.test(previewStyles) &&
    /plex:\s*[\s\S]{0,200}Noto Sans SC/.test(previewStyles) &&
    /serif:\s*[\s\S]{0,200}Noto Serif SC/.test(previewStyles),
  "Resume previews and exports must use the static font families.",
);

console.log("Conditional resume font loading verified.");
