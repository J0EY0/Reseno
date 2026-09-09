import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import { renderToReadableStream } from "react-dom/server";
import { createServer } from "vite";

import { loadTypeScriptModule } from "./typescript-module.mjs";
import { createViteTestCacheDir } from "./vite-test-cache.mjs";
import {
  findJsxElements,
  getJsxAttributes,
  getLiteralValue,
  hasImport,
  readSourceFile,
} from "./source-analysis.mjs";

const frontendRoot = new URL("../", import.meta.url);
let server;
let tracking;
let smartOnePage;
let workspaceRoute;
let templates;
let resumeTitle;
before(async () => {
  server = await createServer({
    cacheDir: createViteTestCacheDir(),
    configFile: false,
    optimizeDeps: { noDiscovery: true },
    resolve: {
      alias: { "@": new URL("src/", frontendRoot).pathname },
    },
    root: frontendRoot.pathname,
  });
  tracking = await server.ssrLoadModule(
    "/src/lib/workspace-change-tracking.ts",
  );
  smartOnePage = await server.ssrLoadModule("/src/lib/smart-one-page.ts");
  workspaceRoute = await server.ssrLoadModule("/src/lib/workspace-route.ts");
  templates = await server.ssrLoadModule("/src/lib/templates.ts");
  resumeTitle = await server.ssrLoadModule("/src/lib/resume-title.ts");
});
after(async () => {
  await server?.close();
});

test("workspace dirty state ignores server metadata and counts edited fields", () => {
  const persistedResume = {
    id: "resume-1",
    title: "Resume",
    updatedAt: "2026-01-01T00:00:00.000Z",
    savedAt: "2026-01-01T00:00:00.000Z",
    theme: "light",
    agentSettings: { defaultModelConfigId: "model-a" },
    resume: {
      basic: { name: "Ada" },
      sections: [{ id: "experience", items: [{ title: "Engineer" }] }],
    },
    jobBrief: "",
    typography: { fontFamily: "inter", fontSize: 16 },
    template: "minimal",
    templateSettings: null,
  };
  const volatileOnlyChange = {
    ...persistedResume,
    updatedAt: "2026-02-01T00:00:00.000Z",
    savedAt: "2026-02-01T00:00:00.000Z",
    theme: "dark",
    agentSettings: { defaultModelConfigId: "model-b" },
  };
  const contentChange = {
    ...volatileOnlyChange,
    resume: {
      ...persistedResume.resume,
      basic: { name: "Grace" },
    },
  };

  assert.equal(
    tracking.createResumeFingerprint(persistedResume),
    tracking.createResumeFingerprint(volatileOnlyChange),
    "Server metadata and preferences must not make a resume dirty.",
  );
  assert.equal(
    tracking.countResumeChanges(persistedResume, volatileOnlyChange),
    0,
  );
  assert.equal(
    tracking.countResumeChanges(persistedResume, contentChange),
    1,
    "One leaf editor change must remain one observable change.",
  );
});

test("smart fit commits only a measured fit and preserves compact styles", async () => {
  const typography = { fontFamily: "inter", fontSize: 16 };
  const settings = {
    pagePaddingTop: 16,
    pagePaddingX: 16,
    pagePaddingBottom: 16,
    sectionGap: 1.4,
    itemGap: 1,
    bodyLineHeight: 1.7,
    nameScale: 2,
    sectionTitleScale: 1.2,
    itemTitleScale: 1,
    metaScale: 0.9,
    bodyScale: 1,
  };
  const currentStyle = { typography, templateSettings: null };

  const alreadyApplied = [];
  assert.deepEqual(
    await smartOnePage.fitResumeToOnePage(currentStyle, settings, {
      applyStyle: (style) => alreadyApplied.push(style),
      measurePageCount: async () => 1,
    }),
    { status: "already-one-page" },
  );
  assert.equal(alreadyApplied.length, 0);

  const fittedStyles = [];
  const fittedMeasurements = [2, 1];
  const fittedResult = await smartOnePage.fitResumeToOnePage(
    currentStyle,
    settings,
    {
      applyStyle: (style) => fittedStyles.push(style),
      measurePageCount: async () => fittedMeasurements.shift() ?? 1,
    },
  );
  assert.equal(fittedResult.status, "applied");
  assert.deepEqual(fittedResult.previous, currentStyle);
  assert.equal(fittedStyles.length, 1);
  assert.deepEqual(fittedResult.style, fittedStyles[0]);

  const compactGapStyles = [];
  const compactGapMeasurements = [2, 1];
  await smartOnePage.fitResumeToOnePage(
    currentStyle,
    { ...settings, sectionGap: 0.6, bodyLineHeight: 1.15 },
    {
      applyStyle: (style) => compactGapStyles.push(style),
      measurePageCount: async () => compactGapMeasurements.shift() ?? 1,
    },
  );
  assert.equal(
    compactGapStyles[0]?.templateSettings.sectionGap,
    0.6,
    "Smart One Page must not enlarge an already compact section gap.",
  );
  assert.equal(
    compactGapStyles[0]?.templateSettings.bodyLineHeight,
    1.15,
    "Smart One Page must not enlarge an already compact line height.",
  );

  const exhaustedStyles = [];
  const exhaustedResult = await smartOnePage.fitResumeToOnePage(
    currentStyle,
    settings,
    {
      applyStyle: (style) => exhaustedStyles.push(style),
      measurePageCount: async () => 2,
    },
  );
  assert.deepEqual(exhaustedResult, { status: "no-fit" });
  assert.ok(exhaustedStyles.length > 1);
  assert.equal(
    "style" in exhaustedResult,
    false,
    "An unsuccessful preview trial must not return a style to commit.",
  );
});

test("workspace route parsing and resume titles preserve their public values", () => {
  for (const [pathname, expectedRoute] of [
    ["/resume", { kind: "resume-gallery" }],
    ["/resume/abc", { kind: "resume-detail", id: "abc" }],
    ["/templates", { kind: "template-gallery" }],
    ["/template/minimal", { kind: "template-detail", id: "minimal" }],
    ["/trash", { kind: "trash" }],
    ["/models", { kind: "models" }],
    ["/settings", { kind: "settings" }],
    ["/unknown", { kind: "unknown" }],
  ]) {
    assert.deepEqual(workspaceRoute.getWorkspaceRoute(pathname), expectedRoute);
  }
  assert.equal(
    Array.from(resumeTitle.truncateResumeTitle("😀".repeat(60))).length,
    50,
  );
  assert.equal(resumeTitle.normalizeResumeTitle("   ", "Fallback"), "Fallback");
});

test("built-in defaults and duplicated custom template appearance are preserved", () => {
  const expectedBuiltinSectionGaps = {
    minimal: 0.7,
    modern: 0.6,
    compact: 0.7,
    classic: 0.8,
    executive: 0.7,
    academic: 1.2,
  };
  assert.deepEqual(
    Object.fromEntries(
      Object.keys(expectedBuiltinSectionGaps).map((templateId) => [
        templateId,
        templates.createTemplateSettings(templateId).sectionGap,
      ]),
    ),
    expectedBuiltinSectionGaps,
    "Built-in templates must keep their compact default section rhythm.",
  );
  assert.equal(
    templates.createTemplateSettings("minimal", { sectionGap: 0.6 }).sectionGap,
    0.6,
    "The compact section-gap lower bound must remain available.",
  );

  const compactSerifTemplate = templates.createCustomTemplateFromBase({
    id: "template-compact-serif",
    preset: "minimal",
    name: "Compact serif",
    description: "",
    layout: {
      ...templates.createTemplateLayout("minimal"),
      section: "underlined",
    },
    typography: { fontFamily: "times", fontSize: 14 },
    settings: {
      ...templates.createTemplateSettings("minimal"),
      bodyLineHeight: 1.15,
    },
    updatedAt: "",
    isBuiltIn: false,
  });
  assert.deepEqual(
    {
      section: compactSerifTemplate.layout.section,
      typography: compactSerifTemplate.typography,
      bodyLineHeight: compactSerifTemplate.settings.bodyLineHeight,
    },
    {
      section: "underlined",
      typography: { fontFamily: "times", fontSize: 14 },
      bodyLineHeight: 1.15,
    },
    "Duplicating a custom template must preserve its typography and layout.",
  );
});

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

async function renderResumeDetail({
  showSkeleton = false,
  pendingPreview = false,
} = {}) {
  const editorProps = [];
  const previewProps = [];
  const operations = [];
  const document = { basic: { name: "Ada" }, sections: [] };
  const section = {
    id: "skills",
    title: "Skills",
    kind: "simple_list",
    items: [],
  };
  const commands = Object.fromEntries(
    [
      "updateContent",
      "toggleSection",
      "addSection",
      "removeSection",
      "onPreviewReadyChange",
    ].map((name) => [name, (...args) => operations.push([name, ...args])]),
  );
  const state = {
    agent: { isPanelCollapsed: true },
    document: { measurementKey: {} },
    openSectionId: section.id,
    previewResume: document,
    previewTemplate: { id: "minimal" },
    previewTypography: { fontFamily: "inter", fontSize: 16 },
    resume: document,
    resumeItem: { documentLocale: "en" },
    showSkeleton,
    theme: "light",
  };
  const empty = () => null;
  let resolvePreview;
  const preview = {
    default: (props) => {
      previewProps.push(props);
      return React.createElement("section", null, "Ready preview");
    },
  };
  const previewModule = pendingPreview
    ? new Promise((resolve) => {
        resolvePreview = () => resolve(preview);
      })
    : Promise.resolve(preview);
  const messages = { skipToContent: "Skip to content" };
  const { ResumeDetailWorkspaceView } = await loadTypeScriptModule(
    new URL(
      "src/components/workspace/resume-detail-workspace-view.tsx",
      frontendRoot,
    ),
    {
      imports: {
        react: React,
        "react/jsx-runtime": jsxRuntime,
        "@/components/app-toaster": { AppToaster: empty },
        "@/components/editor/resume-editor-pane": {
          ResumeEditorPane: (props) => {
            editorProps.push(props);
            return null;
          },
        },
        "@/components/preview/document-canvas-loader": {
          loadDocumentCanvas: () => previewModule,
        },
        "@/components/ui/sidebar": {
          SidebarProvider: ({ children }) => children,
          SidebarInset: (props) => React.createElement("main", props),
        },
        "@/components/workspace/resume-detail-agent-host": {
          ResumeDetailAgentHost: empty,
          ResumeDetailAgentToggle: empty,
        },
        "@/components/workspace/resume-detail-workspace-header": {
          ResumeDetailWorkspaceHeader: empty,
        },
        "@/components/workspace/resume-detail-leave-dialog": {
          ResumeDetailLeaveDialog: empty,
        },
        "@/components/workspace/resume-detail-title-dialog": {
          ResumeDetailTitleDialog: empty,
        },
        "@/components/workspace/workspace-route-error": {
          WorkspaceRouteError: empty,
        },
        "@/components/workspace-skeletons": {
          WorkspacePreviewSkeleton: () =>
            React.createElement("div", null, "Preview loading"),
        },
        "@/i18n/use-localized-messages": {
          useLocalizedMessages: () => messages,
        },
        "@/lib/utils": { cn: (...values) => values.filter(Boolean).join(" ") },
      },
    },
  );
  const stream = await renderToReadableStream(
    React.createElement(ResumeDetailWorkspaceView, {
      locale: "en",
      messages,
      model: { commands, state },
      onLocaleChange: empty,
      previewRef: { current: null },
    }),
  );
  return {
    stream,
    editorProps,
    previewProps,
    operations,
    state,
    section,
    resolvePreview,
  };
}

test(
  "rendered workspace passes document edits and section operations to its controller",
  { timeout: 5000 },
  async () => {
    const fixture = await renderResumeDetail();
    await fixture.stream.allReady;
    const html = await new Response(fixture.stream).text();
    assert.ok(html.includes("Ready preview"));
    const editor = fixture.editorProps.at(-1);
    assert.equal(editor.resume, fixture.state.resume);
    assert.equal(editor.openSectionId, fixture.section.id);
    const edited = { ...editor.resume, basic: { name: "Grace" } };
    editor.updateContent(edited);
    editor.toggleSection("basic");
    editor.addSection(fixture.section);
    editor.removeSection(fixture.section.id);
    assert.deepEqual(fixture.operations, [
      ["updateContent", edited],
      ["toggleSection", "basic"],
      ["addSection", fixture.section],
      ["removeSection", fixture.section.id],
    ]);
    const preview = fixture.previewProps.at(-1);
    assert.equal(preview.resume, fixture.state.previewResume);
    assert.equal(preview.typography, fixture.state.previewTypography);
    assert.equal(preview.measurementKey, fixture.state.document.measurementKey);
    preview.onPaginationReadyChange(true);
    assert.deepEqual(fixture.operations.at(-1), ["onPreviewReadyChange", true]);
  },
);

test(
  "workspace renders a loading surface until the preview module is ready",
  { timeout: 5000 },
  async () => {
    const fixture = await renderResumeDetail({ pendingPreview: true });
    const reader = fixture.stream.getReader();
    const initial = await reader.read();
    assert.ok(
      new TextDecoder().decode(initial.value).includes("Preview loading"),
    );
    assert.equal(fixture.previewProps.length, 0);
    fixture.resolvePreview();
    let html = "";
    for (;;) {
      const chunk = await reader.read();
      if (chunk.done) break;
      html += new TextDecoder().decode(chunk.value);
    }
    assert.ok(html.includes("Ready preview"));
  },
);

test(
  "workspace keeps its loading surface while document data is pending",
  { timeout: 5000 },
  async () => {
    const fixture = await renderResumeDetail({ showSkeleton: true });
    await fixture.stream.allReady;
    const html = await new Response(fixture.stream).text();
    assert.ok(html.includes("Preview loading"));
    assert.equal(fixture.previewProps.length, 0);
    assert.equal(fixture.editorProps.at(-1).showSkeleton, true);
  },
);
