import { access, readFile } from "node:fs/promises";
import {
  findJsxElements,
  getJsxAttributes,
  getMemberPath,
  hasImport,
  parseSource,
} from "./source-analysis.mjs";

const frontendRoot = new URL("../", import.meta.url);
const srcDir = new URL("src/", frontendRoot);

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
  routePreparation,
  routeLoaders,
  detailView,
  detailSave,
  gallery,
  editor,
  metadataDialog,
  editorTabs,
  imagesTab,
] = await Promise.all(
  [
    "App.tsx",
    "components/workspace/template-gallery-workspace-page.tsx",
    "components/workspace/use-template-gallery-workspace.ts",
    "components/workspace/template-detail-workspace-page.tsx",
    "components/workspace/workspace-route-preparation.ts",
    "components/workspace/workspace-route-loaders.ts",
    "components/workspace/template-detail-workspace-view.tsx",
    "components/workspace/use-template-detail-save.ts",
    "components/templates/template-gallery.tsx",
    "components/templates/template-editor.tsx",
    "components/templates/template-metadata-dialog.tsx",
    "components/templates/template-editor-tabs.tsx",
    "components/templates/editor/images-tab.tsx",
  ].map((path) => readFile(new URL(path, srcDir), "utf8")),
);

const appFile = parseSource(app);
const routeLoaderFile = parseSource(routeLoaders);

for (const [entry, routeKey] of [
  ["template-gallery-workspace-page", "templateGallery"],
  ["template-detail-workspace-page", "templateDetail"],
]) {
  assert(
    hasImport(routeLoaderFile, `@/components/workspace/${entry}`, {
      dynamic: true,
    }),
    `${entry} must remain an independently loaded route.`,
  );
  assert(
    findJsxElements(appFile, "Route").some(
      (element) =>
        getMemberPath(getJsxAttributes(element).get("path")) ===
        `workspaceRoutePaths.${routeKey}`,
    ),
    `${entry} must use its canonical route path.`,
  );
}

assert(
  !gallery.includes("template-editor") && !editor.includes("template-gallery"),
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
  routePreparation.includes("loadTemplateDetailWorkspacePage()") &&
    routePreparation.includes("loadDocumentCanvas()") &&
    !/from\s+["']@\/components\/templates\/template-editor["']/.test(
      galleryRoute,
    ) &&
    !/resume-builder/.test(galleryRoute),
  "Gallery intent may preload detail modules only through literal dynamic imports.",
);

assert(
  editor.includes('data-slot="template-editor"') &&
    !editor.includes("@/components/ui/card") &&
    !editor.includes("<Card"),
  "Template editing must remain a cardless inspector.",
);

assert(
  ["@/components/ui/dialog", "@/components/ui/field"].every((specifier) =>
    hasImport(parseSource(metadataDialog), specifier),
  ),
  "Template metadata editing must use the shared Dialog and Field components.",
);

assert(
  detailPage.includes("useTemplateDetailWorkspace") &&
    detailPage.includes("<TemplateDetailWorkspaceView") &&
    !detailPage.includes("resume-builder"),
  "The detail page must remain a narrow route binding over its controller and view.",
);

assert(
  ["@/lib/workspace-api", "@/lib/workspace-change-tracking"].every(
    (specifier) => hasImport(parseSource(detailSave), specifier),
  ),
  "Template persistence must use the shared API and change-tracking modules.",
);

assert(
  ["layout-tab", "typography-tab"].every((moduleName) =>
    hasImport(parseSource(editorTabs), `./editor/${moduleName}`),
  ) &&
    ["visual-tab", "images-tab"].every(
      (moduleName) =>
        hasImport(parseSource(editorTabs), `./editor/${moduleName}`, {
          dynamic: true,
        }) && !hasImport(parseSource(editorTabs), `./editor/${moduleName}`),
    ),
  "Layout and typography must remain in the editor route while color and image controls load on demand.",
);

assert(
  imagesTab.includes('from "./template-image-card"') &&
    imagesTab.includes('from "./use-template-images-editor"') &&
    !imagesTab.includes("readAvatarFileAsDataUrl"),
  "The images tab must compose the narrow card and editor-state modules directly.",
);

assert(
  hasImport(
    parseSource(detailView),
    "@/components/templates/template-editor",
  ) &&
    detailView.includes("<TemplateEditor") &&
    detailView.includes("<DocumentCanvas") &&
    !detailView.includes("resume-builder"),
  "Template detail must compose the dedicated editor and document canvas.",
);

try {
  await access(new URL("components/template-library.tsx", srcDir));
  throw new Error(
    "The obsolete template-library.tsx compatibility file must be deleted.",
  );
} catch (error) {
  if (error?.code !== "ENOENT") {
    throw error;
  }
}

const previewStyles = await readFile(new URL("index.css", srcDir), "utf8");
for (const layout of ["columns", "inline"]) {
  assert(
    new RegExp(
      `\\[data-resume-list-layout=["']${layout}["']\\] > div > (?:ul|:is\\(ul,\\s*ol\\))`,
    ).test(previewStyles),
    `${layout} lists must style the sanitized rich-text wrapper used by previews.`,
  );
}

console.log("Template route boundaries verified.");
