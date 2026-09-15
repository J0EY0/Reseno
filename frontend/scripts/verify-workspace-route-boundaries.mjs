import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { workspaceRoutePaths } from "../src/lib/workspace-route.ts";
import {
  findJsxElements,
  getJsxAttributes,
  getMemberPath,
  hasImport,
  parseSource,
} from "./source-analysis.mjs";

const root = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(`src/${path}`, root), "utf8");
const pageNames = [
  "resume-gallery",
  "resume-detail",
  "models",
  "settings",
  "template-gallery",
  "template-detail",
  "trash",
];
const ownerNames = [
  "resume-gallery",
  "resume-detail",
  "template-gallery",
  "template-detail",
  "trash",
  "workspace-preferences-route",
];
const [
  app,
  loaders,
  preparation,
  routes,
  handoff,
  shell,
  sidebar,
  lateral,
  preferences,
  pages,
  owners,
] = await Promise.all([
  read("App.tsx"),
  read("components/workspace/workspace-route-loaders.ts"),
  read("components/workspace/workspace-route-preparation.ts"),
  read("lib/workspace-route.ts"),
  read("lib/workspace-detail-route-handoff.ts"),
  read("components/workspace/workspace-shell.tsx"),
  read("components/app-sidebar.tsx"),
  read("components/workspace/workspace-lateral-layout.tsx"),
  read("components/workspace/workspace-preferences.tsx"),
  Promise.all(
    pageNames.map((name) =>
      read(`components/workspace/${name}-workspace-page.tsx`),
    ),
  ),
  Promise.all(
    ownerNames.map((name) =>
      read(
        `components/workspace/use-${name}${name === "workspace-preferences-route" ? "" : "-workspace"}.ts`,
      ),
    ),
  ),
]);
const appFile = parseSource(app),
  loadersFile = parseSource(loaders),
  preparationFile = parseSource(preparation);
for (const specifier of [
  "@/lib/workspace-route-handoff",
  "@/lib/workspace-detail-route-handoff",
])
  assert.equal(hasImport(parseSource(routes), specifier), false);
for (const entry of [
  ...pageNames.map((name) => `${name}-workspace-page`),
  "workspace-preferences",
]) {
  const specifier = `@/components/workspace/${entry}`;
  assert.ok(
    hasImport(loadersFile, specifier, { dynamic: true }),
    `${entry} retains its shared lazy entry`,
  );
  for (const file of [appFile, preparationFile]) {
    assert.equal(hasImport(file, specifier), false);
    assert.equal(hasImport(file, specifier, { dynamic: true }), false);
  }
}
assert.ok(hasImport(appFile, "@/components/workspace/workspace-route-loaders"));
const declarations = findJsxElements(appFile, "Route");
const paths = (elements) =>
  elements
    .map((element) => getMemberPath(getJsxAttributes(element).get("path")))
    .filter((member) => member?.startsWith("workspaceRoutePaths."))
    .sort();
assert.deepEqual(
  paths(declarations),
  Object.keys(workspaceRoutePaths)
    .map((key) => `workspaceRoutePaths.${key}`)
    .sort(),
);
for (const [component, expected] of [
  [
    "WorkspaceLateralLayout",
    ["resumeGallery", "models", "settings", "templateGallery", "trash"],
  ],
  ["WorkspacePreferencesProvider", Object.keys(workspaceRoutePaths)],
]) {
  const parents = declarations.filter((element) => {
    const value = getJsxAttributes(element).get("element");
    return value && findJsxElements(value, component).length > 0;
  });
  assert.equal(parents.length, 1, `${component} has one route owner`);
  assert.equal(getJsxAttributes(parents[0]).has("path"), false);
  assert.deepEqual(
    paths(findJsxElements(parents[0].parent, "Route")),
    expected.map((key) => `workspaceRoutePaths.${key}`).sort(),
  );
}
assert.doesNotMatch(routes, /resumeBuilderRoutePaths/);
assert.doesNotMatch(
  pages.join("\n"),
  /from\s+["']@\/components\/resume-builder["']/,
);
await assert.rejects(
  access(new URL("src/components/resume-builder.tsx", root)),
  { code: "ENOENT" },
);
assert.match(
  preparation,
  /interface RoutePreparationOptions \{\s*signal: AbortSignal;\s*\}/,
);
assert.doesNotMatch(preparation, /createWorkspaceLateralRouteHandoff/);
assert.match(
  handoff,
  /ResumeDetailRouteHandoff \{\s*kind:[\s\S]{0,120}payload: PreparedResumeDetailRouteData;/,
);
assert.doesNotMatch(handoff, /prepared\?|prepared\s*=\s*false/);
assert.match(shell, /<AppSidebar[\s\S]*<SidebarInset/);
assert.match(shell, /<AppToaster theme=\{theme\}/);
assert.match(lateral, /<WorkspaceShell[\s\S]*?<Outlet \/>/);
assert.doesNotMatch(
  pages.filter((_, i) => ![1, 5].includes(i)).join("\n"),
  /WorkspaceShell/,
);
assert.doesNotMatch(
  shell,
  /ViewTransitionBoundary|viewTransitionName|import\("@\/components\/resume-builder"\)/,
);
assert.doesNotMatch(
  app.slice(
    app.indexOf("function AppRouteSuspense"),
    app.indexOf("function DocumentMetadata"),
  ),
  /ViewTransitionBoundary|slide-(?:up|down)/,
);
assert.doesNotMatch(sidebar, /components\/ui\/spinner|<Spinner/);
assert.match(preferences, /createWorkspacePreferencesPersistence/);
for (const source of [...owners, lateral]) {
  assert.doesNotMatch(
    source,
    /hydrateTheme|hydrateRoutePreferences|persistence\.(?:hydrate|enqueue)|WorkspaceThemeProvider|prefers-color-scheme|saveUserSettingsApi/,
  );
  assert.doesNotMatch(
    source,
    /calibrationFingerprintRef|priorPersistedFingerprint|initialFingerprint|expectedPersistedFingerprint|persistenceEpochRef|hydrateIfUnchanged/,
  );
}
for (const name of ["resume", "template"]) {
  const gallery = owners[name === "resume" ? 0 : 2];
  assert.doesNotMatch(
    gallery,
    /detailNavigationIntentRef|detailNavigationAbortRef|new AbortController\(\)\.signal|resume-builder/,
  );
  assert.doesNotMatch(
    gallery,
    /import\("@\/components\/templates\/template-editor"\)/,
  );
  const detail = owners[name === "resume" ? 1 : 3];
  for (const module of ["save", "leave"])
    assert.ok(
      hasImport(
        parseSource(detail),
        `@/components/workspace/use-${name}-detail-${module}`,
      ),
    );
}
assert.ok(
  hasImport(
    parseSource(owners[0]),
    "@/components/workspace/resume-gallery-import",
    { dynamic: true },
  ),
);
assert.doesNotMatch(
  owners[1],
  /hasHandoff|onLoadErrorChange|onLoadingChange|hasRouteLoadError|setHasRouteLoadError|\[isLoading, setIsLoading\]|\[hasLoaded, setHasLoaded\]|\[hasLoadError, setHasLoadError\]/,
);
console.log("Workspace route ownership verified.");
const [models, loader, save, preparedNavigation] = await Promise.all(
  [
    "use-resume-detail-models.ts",
    "use-resume-detail-loader.ts",
    "use-resume-detail-save.ts",
    "use-prepared-workspace-navigation.ts",
  ].map((name) => read(`components/workspace/${name}`)),
);
assert.doesNotMatch(
  models,
  /hydrateTheme|hydrateRoutePreferences|persistence\.(?:hydrate|enqueue)|WorkspaceThemeProvider|prefers-color-scheme|saveUserSettingsApi/,
);
assert.doesNotMatch(
  loader,
  /hasHandoff|onLoadErrorChange|onLoadingChange|hasRouteLoadError|setHasRouteLoadError/,
);
assert.doesNotMatch(
  save,
  /initialFingerprint|expectedPersistedFingerprint|persistenceEpochRef|hydrateIfUnchanged/,
);
for (const source of [shell, ...owners.slice(0, 4), preparedNavigation])
  assert.ok(
    hasImport(
      parseSource(source),
      "@/components/workspace/use-workspace-navigation-transaction",
    ),
  );
for (const source of [owners[1], owners[3]])
  assert.ok(
    hasImport(
      parseSource(source),
      "@/components/workspace/use-prepared-workspace-navigation",
    ),
  );
