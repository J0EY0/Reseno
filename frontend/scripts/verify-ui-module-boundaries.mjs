import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import ts from "typescript";

const srcRoot = new URL("../src/", import.meta.url);
const readSource = (path) => readFile(new URL(path, srcRoot), "utf8");

async function loadPureTsModule(path) {
  const source = await readSource(path);
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { exports: module.exports, module });
  return module.exports;
}

const [
  sidebarCore,
  sidebarLayout,
  sidebarMenu,
  appSidebar,
  avatarEntry,
  avatarController,
  avatarCanvas,
  resumeGallery,
  resumeGalleryCard,
  resumeGalleryController,
  templateGallery,
  templateGalleryCard,
  templateGalleryController,
  codeBlock,
  codeBlockHighlighter,
  sourceBudgets,
] = await Promise.all([
  readSource("components/ui/sidebar.tsx"),
  readSource("components/ui/sidebar-layout.tsx"),
  readSource("components/ui/sidebar-menu.tsx"),
  readSource("components/app-sidebar.tsx"),
  readSource("components/editor/avatar-crop-dialog.tsx"),
  readSource("components/editor/use-avatar-crop.ts"),
  readSource("components/editor/avatar-crop-canvas.tsx"),
  readSource("components/resume-gallery.tsx"),
  readSource("components/resume-gallery-card.tsx"),
  readSource("components/use-resume-gallery-controller.ts"),
  readSource("components/templates/template-gallery.tsx"),
  readSource("components/templates/template-gallery-card.tsx"),
  readSource("components/templates/use-template-gallery-controller.ts"),
  readSource("components/ai-elements/code-block.tsx"),
  readSource("components/ai-elements/code-block-highlighter.ts"),
  readFile(new URL("verify-source-budgets.mjs", import.meta.url), "utf8"),
]);

assert(
  sidebarCore.includes("SidebarContext") &&
    sidebarCore.includes("SIDEBAR_KEYBOARD_SHORTCUT") &&
    sidebarLayout.includes('from "@/components/ui/sidebar"') &&
    sidebarMenu.includes('from "@/components/ui/sidebar"'),
  "Sidebar context, layout, and menu responsibilities must remain one-way.",
);
assert(
  /function getInitialSidebarOpen\(defaultOpen:\s*boolean\)/.test(sidebarCore) &&
    /typeof document === ["']undefined["']/.test(sidebarCore) &&
    (sidebarCore.match(/document\.cookie/g) ?? []).length === 2 &&
    (sidebarCore.match(/return defaultOpen/g) ?? []).length === 2 &&
    /cookieValue === ["']true["']/.test(sidebarCore) &&
    /cookieValue === ["']false["']/.test(sidebarCore) &&
    /React\.useState\(\(\)\s*=>\s*getInitialSidebarOpen\(defaultOpen\)\s*\)/.test(
      sidebarCore,
    ),
  "SidebarProvider must synchronously restore its persisted cookie and retain defaultOpen as the fallback.",
);
assert(
  appSidebar.includes('from "@/components/ui/sidebar-layout"') &&
    appSidebar.includes('from "@/components/ui/sidebar-menu"') &&
    !sidebarCore.includes("SidebarMenuButton") &&
    !sidebarCore.includes("SidebarGroupLabel"),
  "AppSidebar must consume narrow layout/menu entries without a compatibility barrel.",
);
assert(
  avatarEntry.includes("useAvatarCrop") &&
    avatarEntry.includes("AvatarCropDialogView") &&
    avatarController.includes("cropAvatarDataUrl") &&
    avatarController.includes("cropWidth: Math.round(crop.width * scaleX)") &&
    avatarCanvas.includes("setPointerCapture") &&
    avatarCanvas.includes("releasePointerCapture") &&
    avatarCanvas.includes("createAspectAvatarCrop"),
  "Avatar crop must retain controller-owned output scaling and canvas pointer capture.",
);
const { createAspectAvatarCrop } = await loadPureTsModule(
  "components/editor/avatar-crop-geometry.ts",
);
assert.equal(
  JSON.stringify(createAspectAvatarCrop(
    { x: 100, y: 100 },
    { x: 180, y: 200 },
    { width: 520, height: 420 },
  )),
  JSON.stringify({ x: 100, y: 100, width: 80, height: 100 }),
  "Avatar crop drawing must preserve the 4:5 output ratio.",
);
assert.equal(
  JSON.stringify(createAspectAvatarCrop(
    { x: 100, y: 100 },
    { x: 20, y: 0 },
    { width: 520, height: 420 },
  )),
  JSON.stringify({ x: 20, y: 0, width: 80, height: 100 }),
  "Avatar crop drawing must preserve direction while clamping to the stage.",
);
for (const [entry, card, controller, name] of [
  [resumeGallery, resumeGalleryCard, resumeGalleryController, "resume"],
  [templateGallery, templateGalleryCard, templateGalleryController, "template"],
]) {
  assert(
    /GalleryGrid/.test(entry) &&
      /GalleryController/.test(entry) &&
      /memo\(function .*GalleryCard/.test(card) &&
      /-preview-\$\{/.test(card) &&
      controller.includes("useDeferredValue") &&
      controller.includes("selectedIdSet") &&
      controller.includes("safeCurrentPage") &&
      card.includes("event.metaKey") &&
      card.includes('event.key === " "'),
    `The ${name} gallery must retain memoized cards, preview transitions, selection, and pagination ownership.`,
  );
}
const literalShikiImports = [
  'import("shiki/core")',
  'import("shiki/engine/javascript")',
  'import("shiki/langs/json.mjs")',
  'import("shiki/themes/github-light.mjs")',
  'import("shiki/themes/github-dark.mjs")',
];
assert(
  codeBlock.includes('from "./code-block-highlighter"') &&
    !codeBlock.includes('from "shiki/core"') &&
    !codeBlock.includes('from "shiki/engine/javascript"') &&
    literalShikiImports.every((moduleImport) =>
      codeBlockHighlighter.includes(moduleImport),
    ) &&
    (codeBlockHighlighter.match(/import\("shiki\//g) ?? []).length === 5 &&
    !codeBlockHighlighter.includes("./code-block") &&
    !/from ["']react["']/.test(codeBlockHighlighter),
  "Code highlighting must retain five literal Shiki chunks without eager or cyclic dependencies.",
);
assert(
  codeBlockHighlighter.includes("highlighterCache.set(language, highlighterPromise)") &&
    codeBlockHighlighter.includes("tokensCache.set(tokensCacheKey, tokenized)") &&
    codeBlockHighlighter.includes("subscribers.get(tokensCacheKey)?.add(callback)") &&
    codeBlockHighlighter.includes("listener(tokenized)") &&
    (codeBlockHighlighter.match(/subscribers\.delete\(tokensCacheKey\)/g) ?? [])
      .length === 2 &&
    codeBlock.includes("highlightCode(code, language) ?? rawTokens") &&
    codeBlock.includes("asyncTokens?.key === tokensCacheKey"),
  "Code highlighting must preserve promise/token caches, subscriber cleanup, and raw-token fallback.",
);
const { createRawTokens, getTokensCacheKey } = await loadPureTsModule(
  "components/ai-elements/code-block-highlighter.ts",
);
assert.equal(
  getTokensCacheKey("x".repeat(101) + "tail", "json"),
  `json:105:${"x".repeat(100)}:${"x".repeat(96)}tail`,
  "Code token cache keys must retain the language, length, and source edges.",
);
assert.equal(
  JSON.stringify(createRawTokens("first\n\nlast")),
  JSON.stringify({
    bg: "transparent",
    fg: "inherit",
    tokens: [
      [{ color: "inherit", content: "first" }],
      [],
      [{ color: "inherit", content: "last" }],
    ],
  }),
  "Raw code tokens must preserve empty lines while Shiki loads.",
);
assert(
  !/ui\/sidebar\.tsx|avatar-crop-dialog\.tsx#AvatarCropDialog|resume-gallery\.tsx#ResumeGallery|template-gallery\.tsx#TemplateGallery|ai-elements\/code-block\.tsx/.test(
    sourceBudgets,
  ),
  "Refactored UI modules must stay on default source and component budgets.",
);

console.log(
  "Sidebar, gallery, avatar crop, and code highlighting boundaries verified.",
);
