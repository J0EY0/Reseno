import assert from "node:assert/strict";
import { test } from "node:test";
import {
  findJsxElements,
  getJsxAttributes,
  getLiteralValue,
  hasImport,
  readSourceFile,
} from "./source-analysis.mjs";

const frontendRoot = new URL("../", import.meta.url);
test("workspace imports retain document boundaries and one main landmark", async () => {
  const readSource = (name) =>
    readSourceFile(new URL(`src/${name}`, frontendRoot));
  const [
    detailRoute,
    detailView,
    galleryImport,
    templateView,
    canvasLoader,
    sidebar,
    shell,
  ] = await Promise.all(
    [
      "components/workspace/use-resume-detail-workspace.ts",
      "components/workspace/resume-detail-workspace-view.tsx",
      "components/workspace/resume-gallery-import.ts",
      "components/workspace/template-detail-workspace-view.tsx",
      "components/preview/document-canvas-loader.ts",
      "components/ui/sidebar.tsx",
      "components/workspace/workspace-shell.tsx",
    ].map(readSource),
  );

  assert.equal(
    findJsxElements(sidebar, "main").length,
    1,
    "SidebarInset must own the workspace main landmark.",
  );
  for (const source of [shell, detailView, templateView]) {
    const landmarks = findJsxElements(source, "SidebarInset");
    assert.equal(landmarks.length, 1);
    const attributes = getJsxAttributes(landmarks[0]);
    assert.equal(getLiteralValue(attributes.get("id")), "main-content");
    assert.equal(getLiteralValue(attributes.get("tabIndex")), -1);
  }
  for (const name of [
    "workspace-route-error.tsx",
    "resume-gallery-workspace-page.tsx",
    "template-gallery-workspace-page.tsx",
    "models-workspace-page.tsx",
    "resume-detail-workspace-view.tsx",
    "resume-workspace-columns.tsx",
    "template-detail-workspace-view.tsx",
  ]) {
    assert.equal(
      findJsxElements(await readSource(`components/workspace/${name}`), "main")
        .length,
      0,
      `${name} must not nest another main landmark.`,
    );
  }
  for (const name of [
    "workspace-skeletons.tsx",
    "settings-panel.tsx",
    "recycle-bin-panel.tsx",
    "gallery-skeletons.tsx",
    "preview/resume-preview-content.tsx",
  ]) {
    assert.equal(
      findJsxElements(await readSource(`components/${name}`), "main").length,
      0,
    );
  }

  const pdfModule = "@/lib/pdf-resume-import";
  assert.equal(hasImport(galleryImport, pdfModule), false);
  assert.equal(hasImport(galleryImport, pdfModule, { dynamic: true }), true);
  assert.equal(hasImport(detailRoute, pdfModule), false);
  assert.equal(
    hasImport(canvasLoader, "@/components/preview/document-canvas", {
      dynamic: true,
    }),
    true,
  );
  for (const source of [detailView, templateView]) {
    assert.equal(
      hasImport(source, "@/components/preview/resume-preview"),
      false,
    );
  }
  for (const source of [detailRoute, detailView]) {
    assert.equal(hasImport(source, "@/lib/resume-section-mutations"), false);
    assert.equal(hasImport(source, "@/lib/avatar"), false);
  }
});
