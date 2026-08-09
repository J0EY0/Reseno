import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "vite";

const frontendRoot = new URL("../", import.meta.url);
const server = await createServer({
  configFile: false,
  resolve: {
    alias: { "@": new URL("src/", frontendRoot).pathname },
  },
  root: frontendRoot.pathname,
});

try {
  const tracking = await server.ssrLoadModule(
    "/src/lib/workspace-change-tracking.ts",
  );
  const smartOnePage = await server.ssrLoadModule(
    "/src/lib/smart-one-page.ts",
  );
  const workspaceRoute = await server.ssrLoadModule(
    "/src/lib/workspace-route.ts",
  );
  const resumeTitle = await server.ssrLoadModule("/src/lib/resume-title.ts");

  const persistedResume = {
    id: "resume-1",
    title: "Resume",
    updatedAt: "2026-01-01T00:00:00.000Z",
    savedAt: "2026-01-01T00:00:00.000Z",
    theme: "light",
    agentSettings: { defaultModelId: "model-a" },
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
    agentSettings: { defaultModelId: "model-b" },
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
  assert.deepEqual(
    exhaustedStyles.at(-1),
    currentStyle,
    "An unsuccessful fit must restore the exact prior style.",
  );

  assert.deepEqual(workspaceRoute.getWorkspaceRoute("/resume/abc"), {
    kind: "resume-detail",
    id: "abc",
  });
  assert.deepEqual(workspaceRoute.getWorkspaceRoute("/template/minimal"), {
    kind: "template-detail",
    id: "minimal",
  });
  assert.deepEqual(workspaceRoute.getWorkspaceRoute("/unknown"), {
    kind: "unknown",
  });
  assert.deepEqual(workspaceRoute.workspaceAppRoutePaths, [
    "/resume",
    "/resume/:id",
    "/templates",
    "/template/:id",
    "/trash",
    "/models",
    "/settings",
  ]);
  assert.equal(
    Array.from(resumeTitle.truncateResumeTitle("😀".repeat(60))).length,
    50,
  );
  assert.equal(resumeTitle.normalizeResumeTitle("   ", "Fallback"), "Fallback");
  assert.equal(
    resumeTitle.formatResumeTitleForToolbar("Long Resume Name - Copy (2)"),
    "Long... - Copy (2)",
  );

  const resumeDetailRouteSource = await readFile(
    new URL(
      "src/components/workspace/use-resume-detail-workspace.ts",
      frontendRoot,
    ),
    "utf8",
  );
  const resumeDetailLoaderSource = await readFile(
    new URL(
      "src/components/workspace/use-resume-detail-loader.ts",
      frontendRoot,
    ),
    "utf8",
  );
  const resumeDetailCommandsSource = await readFile(
    new URL(
      "src/components/workspace/use-resume-detail-commands.ts",
      frontendRoot,
    ),
    "utf8",
  );
  const resumeDetailViewSource = await readFile(
    new URL(
      "src/components/workspace/resume-detail-workspace-view.tsx",
      frontendRoot,
    ),
    "utf8",
  );
  const resumeGalleryRouteSource = await readFile(
    new URL(
      "src/components/workspace/use-resume-gallery-workspace.ts",
      frontendRoot,
    ),
    "utf8",
  );
  const templateDetailRouteSource = await readFile(
    new URL(
      "src/components/workspace/use-template-detail-workspace.ts",
      frontendRoot,
    ),
    "utf8",
  );
  const templateDetailViewSource = await readFile(
    new URL(
      "src/components/workspace/template-detail-workspace-view.tsx",
      frontendRoot,
    ),
    "utf8",
  );
  const documentPreviewSource = await readFile(
    new URL(
      "src/components/preview/document-preview-card.tsx",
      frontendRoot,
    ),
    "utf8",
  );
  const resumeEditorPaneSource = await readFile(
    new URL("src/components/editor/resume-editor-pane.tsx", frontendRoot),
    "utf8",
  );
  assert.ok(
    !/from\s+["']@\/lib\/pdf-resume-import["']/.test(
      resumeGalleryRouteSource,
    ),
    "The optional PDF parser must not be a static workspace dependency.",
  );
  assert.ok(
    /import\(\s*["']@\/lib\/pdf-resume-import["']\s*\)/.test(
      resumeGalleryRouteSource,
    ) &&
      !/pdf-resume-import/.test(resumeDetailRouteSource),
    "PDF import must retain a statically analyzable dynamic chunk boundary.",
  );
  assert.ok(
    !/from\s+["']@\/components\/preview\/resume-preview["']/.test(
      resumeDetailViewSource,
    ) &&
      /import\(["']@\/components\/preview\/document-preview-card["']\)/.test(
        resumeDetailViewSource,
      ),
    "Document preview rendering must remain behind its detail-route chunk.",
  );
  assert.ok(
    /void import\("@\/components\/preview\/document-preview-card"\)/.test(
      resumeDetailLoaderSource,
    ) &&
      /void import\("@\/components\/preview\/document-preview-card"\)/.test(
        templateDetailRouteSource,
      ),
    "Each direct detail route must preload the preview chunk while route data loads.",
  );
  assert.ok(
    /useImperativeHandle\(/.test(documentPreviewSource) &&
      /measurePageCount:\s*\(\)\s*=>/.test(documentPreviewSource) &&
      /remainingFrames = 8/.test(documentPreviewSource) &&
      /remainingFrames = 24/.test(documentPreviewSource) &&
      /measurePageCount:\s*\(\)\s*=>\s*previewHandle\.measurePageCount\(\)/.test(
        resumeDetailCommandsSource,
      ),
    "The preview module must own scaling and expose only pagination measurement.",
  );
  assert.ok(
    /<Suspense fallback=\{<WorkspacePreviewSkeleton \/>\}>/.test(
      resumeDetailViewSource,
    ) &&
      /<Suspense fallback=\{<WorkspacePreviewSkeleton \/>\}>/.test(
        templateDetailViewSource,
      ) &&
      !/<DocumentPreviewCard[^>]*\bkey=/.test(resumeDetailViewSource) &&
      !/<DocumentPreviewCard[^>]*\bkey=/.test(templateDetailViewSource),
    "Both detail routes need a preview fallback without forcing preview remounts.",
  );
  assert.ok(
    /<ResumeEditorPane[\s\S]*?setResume=\{commands\.setResume\}[\s\S]*?setCollapsedState=\{commands\.setCollapsedState\}/.test(
      resumeDetailViewSource,
    ) &&
      !/function updateBasic|applySectionMutation|readAvatarFileAsDataUrl/.test(
        resumeDetailRouteSource + resumeDetailViewSource,
      ),
    "Resume detail must retain editor state ownership without reabsorbing editor mutations.",
  );
  assert.ok(
    /export const ResumeEditorPane = memo\(/.test(resumeEditorPaneSource) &&
      /applySectionMutation/.test(resumeEditorPaneSource) &&
      /<AvatarCropDialog/.test(resumeEditorPaneSource) &&
      !/createContext|useContext/.test(resumeEditorPaneSource),
    "The resume editor pane must remain a memoized, self-contained mutation boundary.",
  );
  assert.ok(
    resumeDetailRouteSource.split("\n").length <= 600 &&
      resumeDetailViewSource.split("\n").length <= 500 &&
      resumeEditorPaneSource.split("\n").length <= 300,
    "Workspace orchestration and editor modules must stay within their size budgets.",
  );

  console.log("Workspace architecture behavior verified.");
} finally {
  await server.close();
}
