import assert from "node:assert/strict";
import test from "node:test";
import { matchPath } from "react-router-dom";
import { loadTypeScriptModule } from "./typescript-module.mjs";

const root = new URL("../src/", import.meta.url);
const routes = await loadTypeScriptModule(
  new URL("lib/workspace-route.ts", root),
  {
    imports: {
      "react-router-dom": { matchPath },
    },
  },
);
const loaders = await loadTypeScriptModule(
  new URL("components/workspace/workspace-route-loaders.ts", root),
  {
    imports: {
      "@/lib/workspace-route": routes,
      "@/lib/route-loader": {
        createRouteLoader: (_load, name) => () => Promise.resolve(name),
      },
    },
  },
);

const destinations = [
  ["/resume", "resume-gallery", "ResumeGalleryWorkspacePage"],
  ["/resume/resume-id", "resume-detail", "ResumeDetailWorkspacePage"],
  ["/templates", "template-gallery", "TemplateGalleryWorkspacePage"],
  ["/template/template-id", "template-detail", "TemplateDetailWorkspacePage"],
  ["/models", "models", "ModelsWorkspacePage"],
  ["/settings", "settings", "SettingsWorkspacePage"],
  ["/trash", "trash", "TrashWorkspacePage"],
];

for (const [pathname, kind, page] of destinations) {
  test(`${pathname} resolves and preloads the same page with an optional trailing slash`, async () => {
    for (const path of [
      pathname,
      `${pathname}/`,
      `${pathname.toUpperCase()}/`,
    ]) {
      assert.equal(routes.getWorkspaceRoute(path).kind, kind);
      assert.equal(await loaders.getWorkspaceRouteLoader(path)(), page);
    }
  });
}

test("unknown routes preload the gallery redirect destination", async () => {
  assert.equal(routes.getWorkspaceRoute("/missing").kind, "unknown");
  assert.equal(
    await loaders.getWorkspaceRouteLoader("/missing")(),
    "ResumeGalleryWorkspacePage",
  );
});

for (const [view, page] of [
  ["resume", "ResumeGalleryWorkspacePage"],
  ["templates", "TemplateGalleryWorkspacePage"],
  ["models", "ModelsWorkspacePage"],
  ["settings", "SettingsWorkspacePage"],
  ["trash", "TrashWorkspacePage"],
]) {
  test(`${view} sidebar preparation uses the canonical route loader`, async () => {
    assert.deepEqual(Array.from(await loaders.preloadWorkspaceRoute(view)), [
      "WorkspacePreferencesProvider",
      "WorkspaceLateralLayout",
      page,
    ]);
  });
}
