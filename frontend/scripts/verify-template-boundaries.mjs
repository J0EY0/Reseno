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
  detailView,
  detailSave,
  detailLeave,
  gallery,
  editor,
  editorTabs,
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
  readFile(new URL("template-editor.tsx", templatesDir), "utf8"),
  readFile(new URL("template-editor-tabs.tsx", templatesDir), "utf8"),
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
  app.includes(
    'import("@/components/workspace/template-gallery-workspace-page")',
  ) && app.includes('<Route path="/templates"'),
  "The gallery must remain a literal, independently registered lazy route.",
);
assert(
  app.includes(
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
    'import("@/components/workspace/template-detail-workspace-page")',
  ) &&
    routePreparation.includes(
      'import("@/components/preview/document-preview-card")',
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
    /runViewTransition[\s\S]{0,240}intent\.finish\(\)[\s\S]{0,120}navigate\(getTemplatePath/.test(
      galleryDetailCommit,
    ),
  "Cold gallery navigation must resolve fresh detail data and modules before its view transition.",
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
    /importTemplatePayload[\s\S]*for \(const item of payload\.templates\)[\s\S]*createTemplateApi[\s\S]*commitTemplateDetailNavigation/.test(
      galleryImportTemplates,
    ),
  "Create and import must persist templates before navigating to template detail.",
);
assert(
  /templateIds\.filter[\s\S]*customTemplates\.some[\s\S]*moveTemplateToTrashApi[\s\S]*setCustomTemplates/.test(
    galleryRoute,
  ) &&
    /saveDefaultTemplateApi\(templateId\)[\s\S]*setDefaultTemplateId/.test(
      galleryRoute,
    ),
  "Delete and default-template mutations must remain gallery-owned and server-backed.",
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
