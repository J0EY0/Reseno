import { access, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";

const frontendRoot = new URL("../", import.meta.url);
const srcDir = new URL("src/", frontendRoot);
const templatesDir = new URL("components/templates/", srcDir);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const [
  app,
  galleryPage,
  galleryRoute,
  detailPage,
  detailRoute,
  routePreparation,
  routeLoaders,
  detailView,
  detailSave,
  detailLeave,
  gallery,
  galleryController,
  galleryToolbar,
  galleryGrid,
  galleryCard,
  editor,
  metadataDialog,
  editorTabs,
  editorFields,
  layoutTab,
  imagesTab,
  imageEditorState,
  imageCard,
  imageFieldControls,
] = await Promise.all([
  readFile(new URL("App.tsx", srcDir), "utf8"),
  readFile(
    new URL("components/workspace/template-gallery-workspace-page.tsx", srcDir),
    "utf8",
  ),
  readFile(
    new URL("components/workspace/use-template-gallery-workspace.ts", srcDir),
    "utf8",
  ),
  readFile(
    new URL("components/workspace/template-detail-workspace-page.tsx", srcDir),
    "utf8",
  ),
  readFile(
    new URL("components/workspace/use-template-detail-workspace.ts", srcDir),
    "utf8",
  ),
  readFile(
    new URL("components/workspace/workspace-route-preparation.ts", srcDir),
    "utf8",
  ),
  readFile(
    new URL("components/workspace/workspace-route-loaders.ts", srcDir),
    "utf8",
  ),
  readFile(
    new URL("components/workspace/template-detail-workspace-view.tsx", srcDir),
    "utf8",
  ),
  readFile(
    new URL("components/workspace/use-template-detail-save.ts", srcDir),
    "utf8",
  ),
  readFile(
    new URL("components/workspace/use-template-detail-leave.ts", srcDir),
    "utf8",
  ),
  readFile(new URL("template-gallery.tsx", templatesDir), "utf8"),
  readFile(
    new URL("use-template-gallery-controller.ts", templatesDir),
    "utf8",
  ),
  readFile(new URL("components/gallery-toolbar.tsx", srcDir), "utf8"),
  readFile(new URL("template-gallery-grid.tsx", templatesDir), "utf8"),
  readFile(new URL("template-gallery-card.tsx", templatesDir), "utf8"),
  readFile(new URL("template-editor.tsx", templatesDir), "utf8"),
  readFile(new URL("template-metadata-dialog.tsx", templatesDir), "utf8"),
  readFile(new URL("template-editor-tabs.tsx", templatesDir), "utf8"),
  readFile(new URL("editor/editor-fields.tsx", templatesDir), "utf8"),
  readFile(new URL("editor/layout-tab.tsx", templatesDir), "utf8"),
  readFile(new URL("editor/images-tab.tsx", templatesDir), "utf8"),
  readFile(new URL("editor/use-template-images-editor.ts", templatesDir), "utf8"),
  readFile(new URL("editor/template-image-card.tsx", templatesDir), "utf8"),
  readFile(
    new URL("editor/template-image-field-controls.tsx", templatesDir),
    "utf8",
  ),
]);

const galleryDetailCommit = galleryRoute.slice(
  galleryRoute.indexOf("const commitTemplateDetailNavigation"),
  galleryRoute.indexOf("const openTemplate"),
);
const galleryOpenTemplate = galleryRoute.slice(
  galleryRoute.indexOf("const openTemplate"),
  galleryRoute.indexOf("const createCustomTemplate"),
);
const galleryCreateTemplate = galleryRoute.slice(
  galleryRoute.indexOf("const createCustomTemplate"),
  galleryRoute.indexOf("const importTemplates"),
);
const galleryImportTemplates = galleryRoute.slice(
  galleryRoute.indexOf("const importTemplates"),
  galleryRoute.indexOf("const deleteTemplates"),
);

assert(
  routeLoaders.includes(
    'import("@/components/workspace/template-gallery-workspace-page")',
  ) && app.includes('<Route path="/templates"'),
  "The gallery must remain a literal, independently registered lazy route.",
);
assert(
  routeLoaders.includes(
    'import("@/components/workspace/template-detail-workspace-page")',
  ) && app.includes('<Route path="/template/:id"'),
  "Template detail must remain a literal, independently registered lazy route.",
);
assert(
  !gallery.includes("template-editor") &&
    !editor.includes("template-gallery"),
  "The removed template-library module must not remain as a shared or compatibility seam.",
);
assert(
  galleryPage.includes(
    'import { TemplateGallery } from "@/components/templates/template-gallery"',
  ) &&
    galleryPage.includes("useTemplateGalleryWorkspace") &&
    !galleryPage.includes("resume-builder") &&
    !galleryPage.includes("template-editor"),
  "The route page must statically compose only the gallery and its route-owned controller.",
);
assert(
  routePreparation.includes(
    "loadTemplateDetailWorkspacePage()",
  ) &&
    routePreparation.includes(
      "loadDocumentPreviewCard()",
    ) &&
    !/from\s+["']@\/components\/templates\/template-editor["']/.test(
      galleryRoute,
    ) &&
    !/resume-builder/.test(galleryRoute),
  "Gallery intent may preload detail modules only through literal dynamic imports.",
);
assert(
  /await prepareTemplateDetailRoute\(templateId, persistence, \{[\s\S]{0,120}signal: intent\.signal/.test(
    galleryOpenTemplate,
  ) &&
    /commitTemplateDetailNavigation\(\s*intent,\s*templateId,\s*data/.test(
      galleryOpenTemplate,
    ) &&
    /startTransition[\s\S]{0,240}intent\.finish\(\)[\s\S]{0,120}navigate\(getTemplatePath/.test(
      galleryDetailCommit,
    ),
  "Cold gallery navigation must resolve fresh detail data and modules before its transition commit.",
);
assert(
  /const preloadTemplateDetail = useCallback\([\s\S]{0,300}preloadTemplateDetailRoute\(\)/.test(
    galleryRoute,
  ) &&
    galleryPage.includes(
      "onPreloadTemplateDetail={gallery.preloadTemplateDetail}",
    ) &&
    gallery.includes("onPreloadTemplateDetail") &&
    galleryGrid.includes("onPreloadTemplateDetail") &&
    galleryCard.includes("onPreloadDetail"),
  "Template detail preload intent must flow explicitly from the route owner to each card.",
);
assert(
  /aria-busy=\{isOpening \|\| undefined\}[\s\S]{0,900}onPointerEnter=\{preloadDetail\}[\s\S]{0,120}onFocus=\{preloadDetail\}[\s\S]{0,120}onPointerDown=\{preloadDetail\}/.test(
    galleryCard,
  ) &&
    /setOpeningTemplateId\(templateId\)[\s\S]*prepareTemplateDetailRoute\([\s\S]*clearOpeningTemplate\(templateId\)/.test(
      galleryOpenTemplate,
    ),
  "Template cards must preload on pointer, focus, and touch intent while reporting semantic pending navigation.",
);
assert(
  !galleryCard.includes("<Spinner") &&
    galleryCard.includes("const isSettingDefaultTemplate =") &&
    galleryCard.includes(
      "aria-busy={isSettingDefaultTemplate || undefined}",
    ),
  "Opening or setting a default template must keep its card visually stable without a loading icon.",
);
assert(
  galleryCard.includes("{isDefaultTemplate ? (") &&
    galleryCard.includes(
      "disabled={isSelecting || settingDefaultTemplateId !== null}",
    ) &&
    !galleryCard.includes("{isSelecting ? null : isDefaultTemplate ?"),
  "Template default controls must remain rendered but disabled during selection mode.",
);
assert(
  /const toggleSelected = useCallback\([\s\S]{0,240}if \(!customTemplateIdSet\.has\(templateId\)\) \{\s*return;/.test(
    galleryController,
  ),
  "Built-in template ids must never enter gallery selection state.",
);
assert(
  galleryCard.includes(
    "const canSelect = isSelecting && !template.isBuiltIn;",
  ) &&
    /if \(isSelecting\) \{[\s\S]{0,300}if \(canSelect\) \{[\s\S]{0,120}onToggleSelected\(template\.id\)/.test(
      galleryCard,
    ) &&
    galleryCard.includes("{canSelect ? (") &&
    galleryCard.includes("if (canSelect && event.key === \" \")") &&
    galleryCard.includes("aria-disabled={isSelecting && template.isBuiltIn}") &&
    galleryCard.includes(
      "tabIndex={isSelecting && template.isBuiltIn ? -1 : undefined}",
    ) &&
    galleryCard.includes(
      'isSelecting && !canSelect ? "cursor-default" : "cursor-pointer"',
    ),
  "Built-in template cards must remain visible but expose no selectable pointer, keyboard, or visual state.",
);
assert(
  !galleryController.includes(
    "const hasCustomTemplates = customTemplateIdSet.size > 0;",
  ) &&
    !gallery.includes("canSelect={gallery.hasCustomTemplates}") &&
    !galleryToolbar.includes("canSelect: boolean") &&
    !galleryToolbar.includes("disabled={!isSelecting && !canSelect}"),
  "Template selection mode must remain available even when only built-in templates are visible.",
);
assert(
  /await persistence\.flush\(\)[\s\S]{0,1000}fetchWorkspaceRouteData\(\s*"template-gallery"/.test(
    galleryRoute,
  ) &&
    /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/.test(
      galleryRoute,
    ),
  "The gallery route must flush shared preferences and own an abortable StrictMode-safe load.",
);
assert(
  /createCustomTemplateFromBase[\s\S]*createTemplateApi[\s\S]*commitTemplateDetailNavigation/.test(
    galleryCreateTemplate,
  ) &&
    /await detailRouteReady[\s\S]*publishCreatedTemplate[\s\S]*messages\.templateCreatedOpenFailed[\s\S]*commitTemplateDetailNavigation\([\s\S]{0,260}publishCreatedTemplate/.test(
      galleryCreateTemplate,
    ) &&
    /importTemplatePayload[\s\S]*for \(const item of payload\.templates\)[\s\S]*createTemplateApi[\s\S]*commitTemplateDetailNavigation/.test(
      galleryImportTemplates,
    ),
  "Create must publish only after preparation or its failure, while import persists before detail navigation.",
);
assert(
  /templateIds\.filter[\s\S]*customTemplates\.some[\s\S]*moveTemplateToTrashApi[\s\S]*setCustomTemplates/.test(
    galleryRoute,
  ) &&
    /saveDefaultTemplateApi\(\s*templateLocale,\s*templateId,?\s*\)[\s\S]*setDefaultTemplateIds/.test(
      galleryRoute,
    ),
  "Delete and default-template mutations must remain gallery-owned and server-backed.",
);
assert(
  galleryRoute.includes("useLocalizedMessages(templateLocale)") &&
    galleryRoute.includes("defaultTemplateIds[templateLocale]") &&
    gallery.includes("<TemplateLocaleSelect") &&
    editor.includes("<TemplateLocaleSelect"),
  "Template preview language and per-language defaults must remain independent from the UI locale.",
);
assert(
  !editor.includes("t.templateEditableStatus") &&
    !editor.includes("template.description || t.templateDescriptionFallback") &&
    !editor.includes("{template.description ? (") &&
    editor.includes('data-slot="template-editor-header"') &&
    editor.includes('data-slot="template-editor-actions"') &&
    !editor.includes("flex flex-wrap items-start justify-between gap-4") &&
    editor.includes('data-slot="template-description"') &&
    editor.includes("mt-1 min-h-6 max-w-[460px]") &&
    editor.includes("<TemplateMetadataDialog") &&
    !editor.includes("<TemplateEditorPanel") &&
    !editor.includes("t.templateInfoPanel"),
  "Custom template headers must expose metadata editing beside the title without a redundant details panel.",
);
assert(
  metadataDialog.includes('data-template-metadata-trigger="true"') &&
    metadataDialog.includes("<DialogTrigger asChild>") &&
    metadataDialog.includes("<DialogTitle>{messages.editTemplateInfo}</DialogTitle>") &&
    metadataDialog.includes("<FieldGroup") &&
    metadataDialog.includes("<FieldLabel htmlFor={nameInputId}>") &&
    metadataDialog.includes("<FieldLabel htmlFor={descriptionInputId}>") &&
    metadataDialog.includes("const trimmedName = name.trim()") &&
    metadataDialog.includes("onSave({ name: trimmedName, description })"),
  "Template metadata editing must use the shared accessible Dialog and commit name and description together.",
);
assert(
  editor.includes('data-slot="template-default-button"') &&
    editor.includes("const isSettingDefaultTemplate =") &&
    editor.includes("aria-busy={isSettingDefaultTemplate || undefined}") &&
    !editor.includes("min-w-36") &&
    editor.includes('className="invisible col-start-1 row-start-1"') &&
    editor.includes("transition-colors") &&
    editor.includes("disabled:opacity-100"),
  "The template default action must reserve translated label width without forcing the action row to wrap.",
);
assert(
  detailPage.includes("useTemplateDetailWorkspace") &&
    detailPage.includes("<TemplateDetailWorkspaceView") &&
    !detailPage.includes("resume-builder"),
  "The detail page must remain a narrow route binding over its controller and view.",
);
assert(
  detailView.includes(
    'import { TemplateEditor } from "@/components/templates/template-editor"',
  ) &&
    detailView.includes("<TemplateEditor") &&
    detailView.includes("<DocumentPreviewCard") &&
    !detailView.includes("resume-builder") &&
    !/<TemplateEditor[\s\S]*?key=/.test(detailView),
  "TemplateEditor must keep its identity across template-detail navigation.",
);
assert(
  /loadTemplateDetailRouteData[\s\S]{0,500}await persistence\.flush\(\)[\s\S]{0,300}fetchWorkspaceRouteData\("template-detail"/.test(
    routePreparation,
  ) &&
    /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/.test(
      detailRoute,
    ),
  "Template detail must own an abortable, StrictMode-safe direct-URL read.",
);
assert(
  /if \(initialDetail && retryKey === 0\)[\s\S]{0,500}setIsLoading\(false\);\s*return;/.test(
    detailRoute,
  ),
  "A complete template handoff must skip the direct-URL read.",
);
assert(
  /activeRequestRef[\s\S]*submittedFingerprint[\s\S]*acceptedFingerprints[\s\S]*onAdoptSavedTemplateRef/.test(
    detailSave,
  ) &&
    /AUTOSAVE_DELAY_MS[\s\S]*AUTOSAVE_MAX_WAIT_MS[\s\S]*AUTOSAVE_RETRY_DELAYS_MS/.test(
      detailSave,
    ),
  "Template detail must retain serialized race-safe persistence and bounded autosave retries.",
);
assert(
  /useBlocker\(hasUnsavedChanges\)[\s\S]*beforeunload[\s\S]*saveAndLeave[\s\S]*discardAndLeave/.test(
    detailLeave,
  ),
  "Template detail must protect route, browser, save, and discard leave paths.",
);
assert(
  !/\blazy\b|\bimport\s*\(/.test(editorTabs) &&
    ["layout-tab", "typography-tab", "visual-tab", "images-tab"].every(
      (moduleName) => editorTabs.includes(moduleName),
    ),
  "Editor tabs must be statically composed inside the editor route chunk.",
);
assert(
  editorFields.includes("children: ReactNode") &&
    (editorFields.match(/useId\(\);/g)?.length ?? 0) === 1 &&
    !editorFields.includes("labelId") &&
    (editorFields.match(/htmlFor=\{controlId\}/g)?.length ?? 0) === 1 &&
    /<label className="grid min-h-\[58px\][\s\S]{0,600}\{children\}[\s\S]{0,60}<\/label>/.test(
      editorFields,
    ) &&
    !layoutTab.includes("controlProps") &&
    (layoutTab.match(/<SelectTrigger className="w-full">/g)?.length ?? 0) === 9,
  "Every template Select trigger must derive its accessible name from its visible row label.",
);
assert(
  !/<TemplateSelectRow[^>]*\bicon=/.test(layoutTab) &&
    !/export function TemplateSelectRow\([\s\S]{0,500}<Icon/.test(
      editorFields,
    ) &&
    editorFields.includes("icon: LucideIcon") &&
    editorFields.includes("<Icon className=\"max-sm:hidden\" />"),
  "Template setting rows must stay text-led while tab icons remain visible.",
);
assert(
  layoutTab.includes('template.layout.avatarPosition !== "none"') &&
    /avatarSizeScalePercentValues[\s\S]*avatarWidth[\s\S]*avatarHeight/.test(
      layoutTab,
    ) &&
    /updateLayout\([\s\S]*getAvatarSizeLayout\([\s\S]*template\.preset/.test(
      layoutTab,
    ),
  "Avatar sizing must stay proportional to the template preset and disappear when the avatar is hidden.",
);
assert(
  /<Slider[\s\S]{0,500}thumbProps=\{\{[\s\S]{0,120}"aria-label": label/.test(
    editorFields,
  ) &&
    /<Input[\s\S]{0,200}id=\{controlId\}[\s\S]{0,120}type="color"/.test(
      editorFields,
    ),
  "Template sliders and color inputs must expose their visible labels on the actual focusable controls.",
);
assert(
  editorTabs.includes('className="relative max-w-full"') &&
    editorTabs.includes("flex-[0_1_auto]") &&
    editorTabs.includes('aria-hidden="true"') &&
    editorTabs.includes("useLayoutEffect") &&
    editorTabs.includes("getBoundingClientRect()") &&
    editorTabs.includes("new ResizeObserver(scheduleIndicatorSync)") &&
    editorTabs.includes("requestAnimationFrame(syncIndicator)") &&
    editorTabs.includes('indicator.style.width = `${width}px`') &&
    editorTabs.includes(
      'indicator.style.transform = `translate3d(${offset}px, 0, 0)`',
    ) &&
    !editorTabs.includes("grid-cols-[") &&
    editorTabs.includes("motion-reduce:transition-none") &&
    editorTabs.includes("dark:border-input dark:bg-input/30") &&
    !editorTabs.includes('variant="line"'),
  "Editor tabs must retain a content-sized shadcn control with a measured sliding indicator.",
);
assert(
  imagesTab.includes('from "./template-image-card"') &&
    imagesTab.includes('from "./use-template-images-editor"') &&
    !imagesTab.includes("readAvatarFileAsDataUrl"),
  "The images tab must compose the narrow card and editor-state modules directly.",
);
assert(
  imageEditorState.includes("expandedImageIdByTemplate") &&
    imageEditorState.includes("imageNameDraft") &&
    imageEditorState.includes("[template.id]: nextImage.id") &&
    imageEditorState.includes("readAvatarFileAsDataUrl(file)") &&
    imageEditorState.includes('file.name.replace(/\\.[^.]+$/, "")'),
  "Template image drafts, expansion, creation, and upload adoption must remain in editor state.",
);
assert(
  imageCard.includes("<Collapsible") &&
    imageCard.includes('event.key === "Enter"') &&
    imageCard.includes('event.key === "Escape"') &&
    imageCard.includes("<TemplateImageFieldControls"),
  "Each image card must retain expansion, keyboard name editing, and field composition.",
);
for (const fieldId of [
  "-x`",
  "-y`",
  "-width`",
  "-height`",
  "-opacity`",
  "-border-radius`",
  "-border-width`",
  "-border-color`",
]) {
  assert(
    imageFieldControls.includes(fieldId),
    `Template image field controls must retain the ${fieldId} editor.`,
  );
}
assert(
  imageFieldControls.includes("objectFit") &&
    imageFieldControls.includes("onUpload(event.target.files?.[0])"),
  "Template image source replacement and fit controls must remain wired.",
);

try {
  await access(new URL("components/template-library.tsx", srcDir));
  throw new Error("The obsolete template-library.tsx compatibility file must be deleted.");
} catch (error) {
  if (error?.code !== "ENOENT") {
    throw error;
  }
}

async function collectSourceFiles(directoryUrl) {
  const entries = await readdir(directoryUrl, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const entryUrl = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directoryUrl);

    if (entry.isDirectory()) {
      files.push(...(await collectSourceFiles(entryUrl)));
    } else if (entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")) {
      files.push(entryUrl);
    }
  }

  return files;
}

for (const sourceUrl of await collectSourceFiles(templatesDir)) {
  const source = await readFile(sourceUrl, "utf8");
  const lineCount = source.split(/\r?\n/).length;

  assert(
    lineCount <= 500,
    `${join("components/templates", sourceUrl.pathname.split("/components/templates/")[1])} has ${lineCount} lines; expected at most 500.`,
  );
}

console.log("Template route chunks and module size boundaries verified.");
