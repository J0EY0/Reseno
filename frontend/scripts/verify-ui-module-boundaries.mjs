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
  galleryPagination,
  galleryToolbar,
  saveStatusButton,
  resumeGallery,
  resumeGalleryCard,
  resumeGalleryGrid,
  resumeGalleryController,
  templateGallery,
  templateGalleryCard,
  templateGalleryGrid,
  templateGalleryController,
  workspaceSkeletons,
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
  readSource("components/gallery-pagination.tsx"),
  readSource("components/gallery-toolbar.tsx"),
  readSource("components/save-status-button.tsx"),
  readSource("components/resume-gallery.tsx"),
  readSource("components/resume-gallery-card.tsx"),
  readSource("components/resume-gallery-grid.tsx"),
  readSource("components/use-resume-gallery-controller.ts"),
  readSource("components/templates/template-gallery.tsx"),
  readSource("components/templates/template-gallery-card.tsx"),
  readSource("components/templates/template-gallery-grid.tsx"),
  readSource("components/templates/use-template-gallery-controller.ts"),
  readSource("components/workspace-skeletons.tsx"),
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
assert.match(
  saveStatusButton,
  /import[\s\S]*Popover[\s\S]*PopoverContent[\s\S]*PopoverTrigger[\s\S]*from ["']@\/components\/ui\/popover["']/,
  "Resume version history must use the installed shadcn Popover primitive.",
);
assert.doesNotMatch(
  saveStatusButton,
  /HoverCard|components\/ui\/hover-card/,
  "Actionable resume version history must not use a hover-only surface.",
);
assert.match(
  saveStatusButton,
  /const saveButton = \([\s\S]*onClick=\{onSave\}[\s\S]*role="group"[\s\S]*\{saveButton\}[\s\S]*<PopoverTrigger asChild>[\s\S]*aria-label=\{versionsLabel\}[\s\S]*<PopoverContent[\s\S]*aria-label=\{versionsLabel\}/,
  "Saving must remain a direct action while version history receives its own keyboard and touch trigger.",
);
assert.match(
  saveStatusButton,
  /onClick=\{\(\) => onSelectVersion\(version\.versionId\)\}/,
  "Selecting a resume version must keep the Popover stable while loading that version.",
);
assert.match(
  saveStatusButton,
  /role="status"[\s\S]{0,160}aria-live="polite"[\s\S]{0,160}aria-atomic="true"/,
  "Saving and saved state changes must be announced without moving focus.",
);
assert.doesNotMatch(
  saveStatusButton,
  /setVersionsOpen\(false\)/,
  "Selecting a resume version must not dismiss its hovered or focused history surface.",
);
assert.match(
  galleryPagination,
  /useLocation\(\)[\s\S]*new URLSearchParams\(location\.search\)/,
  "Gallery pagination links must derive navigable URLs from the current route.",
);
assert.doesNotMatch(
  galleryPagination,
  /href=["']#["']/,
  "Gallery pagination must not use fragment placeholders for URL-backed pages.",
);
for (const modifier of ["metaKey", "ctrlKey", "shiftKey", "altKey"]) {
  assert(
    galleryPagination.includes(`event.${modifier}`),
    `Gallery pagination must preserve native ${modifier} link behavior.`,
  );
}
for (const [entry, card, controller, name] of [
  [resumeGallery, resumeGalleryCard, resumeGalleryController, "resume"],
  [templateGallery, templateGalleryCard, templateGalleryController, "template"],
]) {
  assert(
      /GalleryGrid/.test(entry) &&
      /GalleryController/.test(entry) &&
      /memo\(function .*GalleryCard/.test(card) &&
      card.includes("ResumeThumbnail") &&
      controller.includes("useDeferredValue") &&
      controller.includes("selectedIdSet") &&
      controller.includes("safeCurrentPage") &&
      card.includes("event.metaKey") &&
      card.includes('event.key === " "'),
    `The ${name} gallery must retain memoized cards, preview rendering, selection, and pagination ownership.`,
  );
}
for (const [gallery, name] of [
  [resumeGallery, "resume"],
  [templateGallery, "template"],
]) {
  assert.match(
    gallery,
    /import \{[^}]*\bCopyPlus\b[^}]*\} from ["']lucide-react["'][\s\S]*?<CopyPlus data-icon="inline-start" \/>/,
    `The ${name} gallery create action must use the shared CopyPlus resource-create icon.`,
  );
}
assert(
  [resumeGallery, templateGallery, workspaceSkeletons].every((source) =>
    /grid-cols-\[repeat\(auto-fill,minmax\(208px,228px\)\)\][^"\n]*justify-center/.test(
      source,
    ),
  ),
  "Resume, template, and skeleton galleries must center the available tracks while sparse rows start in the first track.",
);
assert(
  /const canBulkDelete = isSelecting && selectedCount >= 2/.test(
    galleryToolbar,
  ) &&
    galleryToolbar.includes('data-gallery-bulk-action=""') &&
    /data-state=\{canBulkDelete \? "open" : "closed"\}/.test(
      galleryToolbar,
    ) &&
    galleryToolbar.includes("transition-all duration-150 ease-out") &&
    galleryToolbar.includes(
      'gridTemplateColumns: canBulkDelete ? "1fr" : "0fr"',
    ) &&
    galleryToolbar.includes('marginLeft: canBulkDelete ? 0 : "-0.5rem"') &&
    galleryToolbar.includes("opacity: canBulkDelete ? 1 : 0") &&
    galleryToolbar.includes('"translateX(0.25rem) scale(0.98)"') &&
    /aria-hidden=\{!canBulkDelete\}/.test(galleryToolbar) &&
    /inert=\{!canBulkDelete\}/.test(galleryToolbar) &&
    /key=\{selectedCount\}/.test(galleryToolbar) &&
    galleryToolbar.includes("animate-in fade-in-0 zoom-in-95 duration-150") &&
    galleryToolbar.includes('<Trash2 data-icon="inline-start"'),
  "Gallery bulk actions and count changes must retain a restrained, accessible state transition.",
);
const getStaticClassTokens = (tag) =>
  tag.match(/\bclassName="([^"]*)"/)?.[1].split(/\s+/) ?? [];
for (const [
  gallery,
  grid,
  paginatedListName,
  totalListName,
  emptyKey,
  searchKey,
  name,
] of [
  [
    resumeGallery,
    resumeGalleryGrid,
    "paginatedResumes",
    "resumes",
    "emptyResumes",
    "emptyResumeSearch",
    "resume",
  ],
  [
    templateGallery,
    templateGalleryGrid,
    "paginatedTemplates",
    "templates",
    "emptyTemplates",
    "emptyTemplateSearch",
    "template",
  ],
]) {
  const emptyTag = gallery.match(/<Empty\b[^>]*>/)?.[0] ?? "";
  const emptyClasses = getStaticClassTokens(emptyTag);

  assert(
    /<section\b[^>]*className="[^"]*\bborder\b/.test(gallery) &&
      gallery.includes(`gallery.${paginatedListName}.length === 0`) &&
      !grid.includes("<Empty") &&
      !grid.includes('from "@/components/ui/empty"') &&
      !emptyClasses.some(
        (token) =>
          token === "border" ||
          token.startsWith("border-") ||
          token.startsWith("bg-") ||
          token.startsWith("shadow"),
      ) &&
      new RegExp(
        `${totalListName}\\.length\\s*===\\s*0\\s*\\?\\s*t\\.${emptyKey}\\s*:\\s*t\\.${searchKey}`,
      ).test(gallery) &&
      gallery.indexOf("<Empty") < gallery.indexOf("ref={gridRef}"),
    `The ${name} gallery empty state must remain flat inside its single bordered surface.`,
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
