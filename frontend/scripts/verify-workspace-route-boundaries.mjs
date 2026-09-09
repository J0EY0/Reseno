import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import ts from "typescript";
import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import { matchPath } from "react-router-dom";
import {
  findJsxElements,
  findNodes,
  getLiteralValue,
  getJsxAttributes,
  getMemberPath,
  hasCall,
  hasImport,
  parseSource,
} from "./source-analysis.mjs";
import { evaluateTypeScript } from "./typescript-module.mjs";

const frontendRoot = new URL("../", import.meta.url);
const readText = (path) => readFile(new URL(path, frontendRoot), "utf8");

const [
  appSource,
  resumeGalleryPageSource,
  resumeGalleryRouteSource,
  resumeDetailPageSource,
  resumeDetailRouteSource,
  resumeDetailViewSource,
  resumeDetailLoaderSource,
  resumeDetailModelsSource,
  resumeDetailSaveSource,
  resumeDetailLeaveSource,
  modelsPageSource,
  settingsPageSource,
  templateGalleryPageSource,
  templateGalleryRouteSource,
  templateDetailPageSource,
  templateDetailRouteSource,
  templateDetailLeaveSource,
  trashPageSource,
  trashRouteSource,
  lateralLayoutSource,
  shellSource,
  preferencesProviderSource,
  sidebarSource,
  preferencesRouteSource,
  lateralRouteDataSource,
  preparedNavigationSource,
  navigationTransactionSource,
  workspaceRoutePreparationSource,
  workspaceRouteLoadersSource,
  routeLoaderSource,
  workspaceRouteSource,
  workspaceDetailHandoffSource,
  resumeGallerySource,
  resumeGalleryGridSource,
  resumeGalleryCardSource,
] = await Promise.all([
  readText("src/App.tsx"),
  readText("src/components/workspace/resume-gallery-workspace-page.tsx"),
  readText("src/components/workspace/use-resume-gallery-workspace.ts"),
  readText("src/components/workspace/resume-detail-workspace-page.tsx"),
  readText("src/components/workspace/use-resume-detail-workspace.ts"),
  readText("src/components/workspace/resume-detail-workspace-view.tsx"),
  readText("src/components/workspace/use-resume-detail-loader.ts"),
  readText("src/components/workspace/use-resume-detail-models.ts"),
  readText("src/components/workspace/use-resume-detail-save.ts"),
  readText("src/components/workspace/use-resume-detail-leave.ts"),
  readText("src/components/workspace/models-workspace-page.tsx"),
  readText("src/components/workspace/settings-workspace-page.tsx"),
  readText("src/components/workspace/template-gallery-workspace-page.tsx"),
  readText("src/components/workspace/use-template-gallery-workspace.ts"),
  readText("src/components/workspace/template-detail-workspace-page.tsx"),
  readText("src/components/workspace/use-template-detail-workspace.ts"),
  readText("src/components/workspace/use-template-detail-leave.ts"),
  readText("src/components/workspace/trash-workspace-page.tsx"),
  readText("src/components/workspace/use-trash-workspace.ts"),
  readText("src/components/workspace/workspace-lateral-layout.tsx"),
  readText("src/components/workspace/workspace-shell.tsx"),
  readText("src/components/workspace/workspace-preferences.tsx"),
  readText("src/components/app-sidebar.tsx"),
  readText("src/components/workspace/use-workspace-preferences-route.ts"),
  readText("src/components/workspace/use-workspace-lateral-route-data.ts"),
  readText("src/components/workspace/use-prepared-workspace-navigation.ts"),
  readText("src/components/workspace/use-workspace-navigation-transaction.ts"),
  readText("src/components/workspace/workspace-route-preparation.ts"),
  readText("src/components/workspace/workspace-route-loaders.ts"),
  readText("src/lib/route-loader.ts"),
  readText("src/lib/workspace-route.ts"),
  readText("src/lib/workspace-detail-route-handoff.ts"),
  readText("src/components/resume-gallery.tsx"),
  readText("src/components/resume-gallery-grid.tsx"),
  readText("src/components/resume-gallery-card.tsx"),
]);
const resumeDetailCommandsSource = await readText(
  "src/components/workspace/use-resume-detail-commands.ts",
);
const templateDetailInitialRouteSource = await readText(
  "src/components/workspace/template-detail-initial-route.ts",
);

for (const specifier of [
  "@/lib/workspace-route-handoff",
  "@/lib/workspace-detail-route-handoff",
]) {
  assert.equal(
    hasImport(parseSource(workspaceRouteSource), specifier),
    false,
    "Route matching must not statically load detail handoff payloads into the shell.",
  );
}
const appFile = parseSource(appSource);
const routeLoadersFile = parseSource(workspaceRouteLoadersSource);
const workspaceRoutes = evaluateTypeScript(workspaceRouteSource, {
  imports: { "react-router-dom": { matchPath } },
});
const workspaceLoaders = evaluateTypeScript(workspaceRouteLoadersSource, {
  imports: {
    "@/lib/workspace-route": workspaceRoutes,
    "@/lib/route-loader": {
      createRouteLoader: (_loadModule, component) => async () => ({
        default: component,
      }),
    },
  },
});
const routePreparationFile = parseSource(workspaceRoutePreparationSource);
for (const source of [
  resumeDetailLoaderSource,
  resumeGalleryRouteSource,
  templateDetailRouteSource,
  templateGalleryRouteSource,
  trashRouteSource,
  preferencesRouteSource,
]) {
  const owner = parseSource(source);
  assert.ok(
    hasImport(owner, "@/lib/workspace-load-error"),
    "Every route loader must share ownership of its replaceable load error.",
  );
  assert.ok(hasCall(owner, "dismissWorkspaceLoadError"));
}
for (const routeEntry of [
  "resume-gallery-workspace-page",
  "resume-detail-workspace-page",
  "models-workspace-page",
  "settings-workspace-page",
  "template-gallery-workspace-page",
  "template-detail-workspace-page",
  "trash-workspace-page",
  "workspace-preferences",
]) {
  const specifier = `@/components/workspace/${routeEntry}`;
  assert.ok(
    hasImport(routeLoadersFile, specifier, { dynamic: true }),
    `${routeEntry} must retain its lazy entry.`,
  );
  for (const source of [appFile, routePreparationFile]) {
    assert.equal(
      hasImport(source, specifier, { dynamic: true }),
      false,
      `${routeEntry} must have one shared dynamic-import owner.`,
    );
    assert.equal(
      hasImport(source, specifier),
      false,
      `${routeEntry} must not become a static App dependency.`,
    );
  }
}
assert.ok(hasImport(appFile, "@/components/workspace/workspace-route-loaders"));
const { createRouteLoader } = evaluateTypeScript(routeLoaderSource);
let resolveModule;
let moduleRequests = 0;
const component = {};
const modulePromise = new Promise((resolve) => {
  resolveModule = resolve;
});
const loadPage = createRouteLoader(() => {
  moduleRequests += 1;
  return modulePromise;
}, "Page");
const preload = loadPage();
const renderRequest = loadPage();
assert.equal(
  preload,
  renderRequest,
  "Preloading and React.lazy must share the same in-flight module Promise.",
);
assert.equal(moduleRequests, 1);
resolveModule({ Page: component });
assert.equal((await preload).default, component);
assert.equal(loadPage(), preload, "A loaded route must not reload its module.");
const appRouteSuspenseSource = appSource.slice(
  appSource.indexOf("function AppRouteSuspense"),
  appSource.indexOf("function DocumentMetadata"),
);
assert.doesNotMatch(
  appRouteSuspenseSource,
  /ViewTransitionBoundary|slide-(?:up|down)/,
  "Route Suspense resolution must not animate loading into content; explicit workspace navigation owns route motion.",
);
const routeDeclarations = findJsxElements(appFile, "Route");
const routePaths = routeDeclarations
  .map((element) => getMemberPath(getJsxAttributes(element).get("path")))
  .filter((member) => member?.startsWith("workspaceRoutePaths."));
assert.deepEqual(
  routePaths.slice().sort(),
  Object.keys(workspaceRoutes.workspaceRoutePaths)
    .map((key) => `workspaceRoutePaths.${key}`)
    .sort(),
  "The rendered workspace routes must use the canonical path registry exactly once.",
);
const metadataDocument = { documentElement: { lang: "" }, title: "" };
const metadataLocation = { pathname: "" };
const { DocumentMetadata } = evaluateTypeScript(
  `${appSource}\nexport { DocumentMetadata };`,
  {
    filename: "App.tsx",
    globals: { document: metadataDocument },
    imports: {
      react: { ...React, useEffect: (effect) => effect() },
      "react/jsx-runtime": jsxRuntime,
      "react-router-dom": { useLocation: () => metadataLocation },
      "@/lib/auth": {},
      "@/lib/workspace-route": workspaceRoutes,
      "@/i18n": {},
      "@/i18n/use-locale-messages": {},
      "@/lib/preference-api": {},
      "@/hooks/use-auth-gate": {},
      "@/components/ui/spinner": {},
      "@/hooks/use-oauth-login": {},
      "@/components/workspace/workspace-route-loaders": workspaceLoaders,
      "@/lib/dynamic-import-recovery": {},
      "@/lib/route-loader": { createRouteLoader },
    },
  },
);
const messages = JSON.parse(await readText("src/i18n/locales/en.json"));
for (const [key, componentName, titleKey] of [
  ["resumeGallery", "ResumeGalleryWorkspacePage", "myResume"],
  ["resumeDetail", "ResumeDetailWorkspacePage", "myResume"],
  ["templateGallery", "TemplateGalleryWorkspacePage", "resumeTemplates"],
  ["templateDetail", "TemplateDetailWorkspacePage", "resumeTemplates"],
  ["trash", "TrashWorkspacePage", "recycleBin"],
  ["models", "ModelsWorkspacePage", "modelSettings"],
  ["settings", "SettingsWorkspacePage", "settings"],
]) {
  const path = workspaceRoutes.workspaceRoutePaths[key].replace(
    ":id",
    "example",
  );
  for (const pathname of [path, `${path}/`]) {
    assert.notEqual(
      workspaceRoutes.getWorkspaceRoute(pathname).kind,
      "unknown",
    );
    const loader = workspaceLoaders.getWorkspaceRouteLoader(pathname);
    assert.equal((await loader()).default, componentName, pathname);
    metadataLocation.pathname = pathname;
    DocumentMetadata({ locale: "en", messages });
    assert.equal(
      metadataDocument.title,
      `${messages[titleKey]} · ${messages.brandTitle}`,
      pathname,
    );
  }
}
for (const [pathname, titleKey] of [
  ["/unknown", "brandTitle"],
  ["/templates/example", "brandTitle"],
  ["/login", "loginTitle"],
  ["/setup", "setupTitle"],
  ["/auth/callback", "brandTitle"],
  ["/pdf-export", "brandTitle"],
]) {
  assert.equal(workspaceRoutes.getWorkspaceRoute(pathname).kind, "unknown");
  assert.equal(
    (await workspaceLoaders.getWorkspaceRouteLoader(pathname)()).default,
    "ResumeGalleryWorkspacePage",
  );
  metadataLocation.pathname = pathname;
  DocumentMetadata({ locale: "en", messages });
  assert.equal(metadataDocument.title, messages[titleKey], pathname);
}
assert.equal(metadataDocument.documentElement.lang, "en");
DocumentMetadata({ locale: "zh", messages });
assert.equal(metadataDocument.documentElement.lang, "zh-CN");

const lateralRoutes = routeDeclarations.filter((element) => {
  const value = getJsxAttributes(element).get("element");
  return value && findJsxElements(value, "WorkspaceLateralLayout").length > 0;
});
assert.equal(
  lateralRoutes.length,
  1,
  "The workspace must retain one shared lateral layout route.",
);
const [lateralRoute] = lateralRoutes;
assert.equal(getJsxAttributes(lateralRoute).has("path"), false);
assert.deepEqual(
  findJsxElements(lateralRoute.parent, "Route")
    .map((element) => getMemberPath(getJsxAttributes(element).get("path")))
    .filter(Boolean)
    .sort(),
  ["resumeGallery", "models", "settings", "templateGallery", "trash"]
    .map((key) => `workspaceRoutePaths.${key}`)
    .sort(),
  "The lateral routes must share one persistent workspace layout.",
);
assert.doesNotMatch(
  workspaceRouteSource,
  /resumeBuilderRoutePaths/,
  "The retired Builder route registry must be removed instead of preserved as a compatibility export.",
);
assert.doesNotMatch(
  resumeGalleryPageSource +
    resumeDetailPageSource +
    modelsPageSource +
    settingsPageSource +
    templateGalleryPageSource +
    templateDetailPageSource +
    trashPageSource,
  /from\s+["']@\/components\/resume-builder["']/,
  "Independent workspace pages must not statically depend on the retired ResumeBuilder.",
);
assert.match(
  workspaceRoutePreparationSource,
  /Promise\.all\(\[\s*preloadWorkspaceRoute\(view\),\s*loadWorkspaceRouteData\(view, persistence, options\),\s*\]\)/,
  "Workspace preparation must load the route module and flushed route data in parallel.",
);
assert.match(
  workspaceRoutePreparationSource,
  /fetchWorkspacePageData[\s\S]{0,500}await persistence\.prepareRead\(options\.signal\)[\s\S]{0,180}options\.signal\.throwIfAborted\(\)[\s\S]{0,180}await fetchWorkspaceRouteData\(kind, options\)[\s\S]{0,120}acceptPreferences\(source\.data\)[\s\S]{0,80}return source/,
  "Fresh route reads must await the preference queue, respect cancellation, and accept preferences before exposing page data.",
);
assert.match(
  workspaceRoutePreparationSource,
  /fetchWorkspacePageData\("settings", persistence,\s*\{\s*notifyOnError:\s*false,\s*signal:\s*options\.signal/,
  "Prepared route reads must suppress duplicate error Toasts and forward the navigation signal.",
);
assert.match(
  workspaceRoutePreparationSource,
  /interface RoutePreparationOptions \{\s*signal: AbortSignal;\s*\}/,
  "Committed preparation must require a caller-owned signal so GETs stay fresh and abortable.",
);
assert.match(
  workspaceRoutePreparationSource,
  /Promise<PreparedWorkspaceRoute>[\s\S]*return \{ data: source\.data, view \}/,
  "Preparation must return typed data without allocating a history token.",
);
assert.doesNotMatch(
  workspaceRoutePreparationSource,
  /createWorkspaceLateralRouteHandoff/,
  "Hover preparation must not retain route data in the token registry.",
);
assert.match(
  lateralRouteDataSource,
  /const \[resolution\] = useState\(\(\) =>[\s\S]{0,120}resolveWorkspaceLateralRoute\(location\.state, view\)[\s\S]{0,300}resolution\.shouldScrubHistory[\s\S]{0,300}deleteWorkspaceHandoffToken\(resolution\.tokenToDelete\)[\s\S]{0,300}replace:\s*true, state:\s*null[\s\S]*return resolution\.data/,
  "The consumer must freeze its first frame from a handoff or committed view memory and scrub one-time or dead tokens before paint.",
);
assert.match(
  lateralRouteDataSource,
  /useRememberWorkspaceLateralRouteData[\s\S]{0,500}useLayoutEffect[\s\S]{0,300}rememberWorkspaceLateralRoute/,
  "Only committed usable route data may refresh the bounded per-view memory.",
);
for (const pageSource of [
  resumeGalleryPageSource,
  templateGalleryPageSource,
  trashPageSource,
  modelsPageSource,
  settingsPageSource,
]) {
  assert.match(
    pageSource,
    /useRememberWorkspaceLateralRouteData\([\s\S]{0,160}\.hasLoaded\s*\?\s*[^:]+\.routeData\s*:\s*null/,
    "Every lateral route page must publish only loaded controller state.",
  );
}
assert.match(
  appSource,
  /authGate\.phase === "app"[\s\S]{0,160}hasEnteredAuthenticatedAppRef\.current = true[\s\S]{0,180}!hasEnteredAuthenticatedAppRef\.current[\s\S]{0,240}import\("@\/lib\/workspace-route-memory"\)[\s\S]{0,160}clearWorkspaceRouteMemory\(\)/,
  "Leaving the authenticated app must clear all per-view snapshots and one-time handoffs.",
);
try {
  await access(new URL("src/components/resume-builder.tsx", frontendRoot));
  assert.fail("The retired ResumeBuilder implementation must be deleted.");
} catch (error) {
  if (error?.code !== "ENOENT") {
    throw error;
  }
}
assert.match(shellSource, /<AppSidebar[\s\S]*<SidebarInset/);
assert.match(shellSource, /<AppToaster theme=\{theme\}/);
assert.match(
  lateralLayoutSource,
  /<WorkspaceShell[\s\S]*?<Outlet \/>/,
  "The lateral layout must keep Sidebar and Header mounted around the changing route outlet.",
);
const preferencesRoute = routeDeclarations.find((element) => {
  const value = getJsxAttributes(element).get("element");
  return (
    value && findJsxElements(value, "WorkspacePreferencesProvider").length === 1
  );
});
assert.ok(
  preferencesRoute,
  "The workspace must have one shared preferences provider.",
);
assert.deepEqual(
  findJsxElements(preferencesRoute.parent, "Route")
    .map((element) => getMemberPath(getJsxAttributes(element).get("path")))
    .filter(Boolean)
    .sort(),
  routePaths.slice().sort(),
  "One preferences provider must span every workspace route.",
);

assert.doesNotMatch(
  resumeGalleryPageSource +
    templateGalleryPageSource +
    trashPageSource +
    modelsPageSource +
    settingsPageSource,
  /WorkspaceShell/,
  "Lateral route pages must render content only so their shared chrome keeps DOM identity.",
);
assert.doesNotMatch(
  shellSource,
  /ViewTransitionBoundary|viewTransitionName/,
  "The persistent shell must use ordinary DOM motion instead of the unavailable React ViewTransition API.",
);
assert.match(
  shellSource,
  /pendingView[\s\S]*?setPendingView\(view\)[\s\S]*?key=\{activeView\}[\s\S]*?workspace-route-stage/,
  "Sidebar navigation must report immediate pending intent while each committed view receives one lightweight entry stage.",
);
assert.match(
  sidebarSource,
  /pendingView === item\.id[\s\S]*?aria-busy=\{isPending \|\| undefined\}/,
  "Only the target sidebar item must expose semantic navigation progress.",
);
assert.doesNotMatch(
  sidebarSource,
  /components\/ui\/spinner|<Spinner/,
  "Sidebar navigation must stay visually stable instead of showing a loading icon.",
);
assert.match(
  preferencesProviderSource,
  /WorkspacePreferencesProvider[\s\S]*?createWorkspacePreferencesPersistence[\s\S]*?prefers-color-scheme: dark[\s\S]*?persistence\.change/,
  "The common workspace parent must own one theme surface and preference transaction coordinator.",
);
for (const routePreferencesSource of [
  resumeGalleryRouteSource,
  templateGalleryRouteSource,
  trashRouteSource,
  preferencesRouteSource,
  resumeDetailModelsSource,
  resumeDetailRouteSource,
  templateDetailRouteSource,
  lateralLayoutSource,
]) {
  assert.doesNotMatch(
    routePreferencesSource,
    /hydrateTheme|hydrateRoutePreferences|persistence\.(?:hydrate|enqueue)|WorkspaceThemeProvider|prefers-color-scheme|saveUserSettingsApi/,
    "Route mounts and history snapshots must not hydrate preferences, save them independently, or own another theme listener.",
  );
}
assert.doesNotMatch(
  shellSource,
  /import\("@\/components\/resume-builder"\)/,
  "The shared gallery shell must not pull the detail-owned builder slice.",
);
assert.match(
  shellSource,
  /preloadWorkspaceRoute\(view\)\.catch\(\(\) => undefined\)/,
  "Sidebar hover and focus must preload only the route module.",
);
assert.match(
  navigationTransactionSource,
  /let activeNavigation[\s\S]*function beginWorkspaceNavigation[\s\S]*activeNavigation\?\.controller\.abort\(\)[\s\S]*new AbortController\(\)/,
  "Every workspace navigation owner must share one latest-intent transaction.",
);
for (const transactionCapability of [
  /signal:\s*controller\.signal/,
  /const isCurrent = \(\) =>/,
  /cancel:\s*\(\) =>/,
  /finish:\s*\(\) =>/,
  /activeNavigation\?\.id !== id/,
]) {
  assert.match(
    navigationTransactionSource,
    transactionCapability,
    "The shared transaction must expose guarded cancellation, completion, and staleness checks.",
  );
}
assert.match(
  navigationTransactionSource,
  /useEffect\([\s\S]{0,220}cancelNavigation\(\)/,
  "Unmounting a navigation owner must cancel its still-current transaction.",
);
assert.match(
  navigationTransactionSource,
  /useLayoutEffect\([\s\S]{0,260}cancelNavigation\(\)[\s\S]{0,120}location\.key/,
  "Query-only and history navigation must supersede an older owned intent without relying on unmount.",
);
for (const navigationOwnerSource of [
  shellSource,
  resumeGalleryRouteSource,
  templateGalleryRouteSource,
  preparedNavigationSource,
  resumeDetailRouteSource,
  templateDetailRouteSource,
]) {
  assert.match(
    navigationOwnerSource,
    /useWorkspaceNavigationTransaction\(\)/,
    "Cards, sidebar, detail navigation, and mutation entrances must share the latest-navigation transaction.",
  );
}
const shellViewChangeSource = shellSource.slice(
  shellSource.indexOf("async function handleViewChange"),
  shellSource.indexOf("  return ("),
);
assert.match(
  shellViewChangeSource,
  /const intent = beginNavigation\(\)[\s\S]*prepareWorkspaceRoute\(view, persistence, \{\s*signal: intent\.signal[\s\S]*!intent\.isCurrent\(\)[\s\S]*createWorkspaceLateralRouteHandoff\(prepared\)[\s\S]*intent\.finish\(\)[\s\S]*navigate\(path, \{ state \}\)[\s\S]*WORKSPACE_NAVIGATION_ERROR_TOAST_ID/,
  "Sidebar clicks must commit only fresh prepared route data and surface one stable failure Toast.",
);
assert.doesNotMatch(
  shellViewChangeSource,
  /catch[\s\S]*navigate\(path\)/,
  "A failed sidebar preparation must keep the current route mounted.",
);
assert.match(
  shellViewChangeSource,
  /const intent = beginNavigation\(\);[\s\S]{0,420}if \(view === activeView\) \{[\s\S]{0,140}intent\.finish\(\)/,
  "Clicking the active sidebar entry must still supersede an older card or mutation intent.",
);
assert.doesNotMatch(
  shellViewChangeSource,
  /navigationIntentRef|navigationAbortRef|new AbortController\(\)/,
  "Sidebar navigation must not own a private latest-request counter.",
);
assert.match(
  shellSource,
  /function handleLogout\(\) \{[\s\S]{0,120}beginNavigation\(\)[\s\S]{0,80}intent\.finish\(\)[\s\S]{0,80}onLogout\(\)/,
  "Logout must supersede pending workspace navigation before leaving auth state.",
);
assert.match(
  preparedNavigationSource,
  /preloadWorkspaceRoute\(view\)\.catch\(\(\) => undefined\)/,
  "Detail hover and focus must preload only the route module.",
);
assert.match(
  preparedNavigationSource,
  /const prepareFreshRoute = \(\) =>[\s\S]*prepareWorkspaceRoute\(view, persistence, \{\s*signal: intent\.signal[\s\S]{0,1200}WORKSPACE_NAVIGATION_ERROR_TOAST_ID/,
  "Detail navigation must prepare a fresh target after the first leave guard and keep failures local.",
);
assert.equal(
  (
    preparedNavigationSource.match(
      /requestLeave\(prepareFreshRoute, intent\.cancel\)/g,
    ) ?? []
  ).length,
  2,
  "Detail navigation must guard before preparation and re-enter the same fresh preparation after late edits.",
);
assert.match(
  preparedNavigationSource,
  /if \(requiresLeaveResolution\(\)\) \{[\s\S]{0,180}requestLeave\(prepareFreshRoute, intent\.cancel\)[\s\S]{0,160}return;[\s\S]{0,180}commitPreparedRoute\(prepared\)/,
  "If editing or checkpoint promotion happens during preparation, leave resolution must trigger another fresh preparation before commit.",
);
assert.match(
  preparedNavigationSource,
  /const commitPreparedRoute[\s\S]{0,900}createWorkspaceLateralRouteHandoff\(prepared\)[\s\S]{0,160}intent\.finish\(\)[\s\S]{0,120}navigate\(path, \{ state \}\)[\s\S]{0,260}deleteWorkspaceHandoffToken\(handoffToken\)[\s\S]{0,300}WORKSPACE_NAVIGATION_ERROR_TOAST_ID/,
  "A detail route may allocate its token only inside the final guarded commit and must clean up failed commits.",
);
assert.doesNotMatch(
  preparedNavigationSource,
  /finishPreparation\(null\)|catch[\s\S]{0,240}navigate\(path\)|navigationIntentRef|navigationAbortRef|new AbortController\(\)/,
  "Prepared detail navigation must never fall through to an unprepared destination.",
);
assert.match(
  preparedNavigationSource,
  /cancelPending:\s*cancelNavigation/,
  "Unmounted detail navigation owners must cancel their own pending transaction.",
);
assert.match(
  preparedNavigationSource,
  /intent\.isCurrent\(\)/,
  "Superseded detail navigation intents must not commit late.",
);
for (const detailRouteSource of [
  resumeDetailRouteSource,
  templateDetailRouteSource,
]) {
  assert.match(
    detailRouteSource,
    /usePreparedWorkspaceNavigation\(\{[\s\S]{0,180}preparationErrorMessage:\s*messages\.loadError,[\s\S]{0,100}requestLeave/,
    "Both editable detail routes must share the guarded prepared-navigation owner.",
  );
}
for (const routeSource of [
  resumeGalleryRouteSource,
  templateGalleryRouteSource,
]) {
  assert.match(
    routeSource,
    /hasLoaded, setHasLoaded\] = useState\(Boolean\(preparedRouteData\)\)[\s\S]{0,180}isLoading, setIsLoading\] = useState\(!preparedRouteData\)/,
    "A prepared route must keep its first-frame content interactive.",
  );
  assert.match(
    routeSource,
    /if \(preparedRouteData && retryKey === 0\)[\s\S]{0,700}return;[\s\S]{0,200}new AbortController\(\)/,
    "A prepared lateral handoff must return before the direct-URL loader creates transport.",
  );
  assert.doesNotMatch(
    routeSource,
    /isPreparedCalibration|routeMutationEpochRef|markRouteMutation/,
    "Lateral routes must not retain the obsolete background-calibration path.",
  );
}
assert.match(
  preferencesRouteSource,
  /hasPreparedData\] = useState\([\s\S]{0,100}Boolean\(preparedRouteData\) && agentSettings !== null,[\s\S]{0,100}hasLoaded, setHasLoaded\] = useState\(hasPreparedData\)[\s\S]{0,180}isLoading, setIsLoading\] = useState\(!hasPreparedData\)/,
  "Prepared preference routes must render immediately only when both page data and shared Agent preferences are ready.",
);
assert.match(
  preferencesRouteSource,
  /if \(hasPreparedData && retryKey === 0\) \{\s*return;[\s\S]{0,100}new AbortController\(\)/,
  "A complete preference handoff must skip transport without rehydrating its cached preferences.",
);
assert.doesNotMatch(
  preferencesRouteSource,
  /isPreparedCalibration|routeMutationEpochRef|markRouteMutation/,
  "Preference routes must not retain obsolete background calibration.",
);
assert.match(
  trashRouteSource,
  /hasLoaded, setHasLoaded\] = useState\(Boolean\(preparedRouteData\)\)/,
  "The prepared trash route must render its first-frame content without a loading reset.",
);
assert.match(
  trashRouteSource,
  /if \(preparedRouteData && retryKey === 0\)[\s\S]{0,700}return;[\s\S]{0,200}new AbortController\(\)/,
  "A prepared trash handoff must return before the direct-URL loader creates transport.",
);
assert.match(
  preferencesRouteSource,
  /fetchWorkspacePageData\(\s*kind,\s*persistence,/,
  "A route must wait for queued settings writes before reading server state.",
);
assert.match(
  preferencesRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*showWorkspaceLoadError\([\s\S]*setHasLoadError\(true\)/,
  "Cancelled and stale preference requests must exit before the retry state and Toast.",
);
assert.match(
  preferencesRouteSource,
  /retryLoad:\s*\(\)\s*=>\s*setRetryKey\(\(current\)\s*=>\s*current \+ 1\)/,
  "Preference load failures must expose the abortable loader's retry key.",
);
assert.match(
  preferencesRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "Preference route reads must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  preferencesRouteSource,
  /useWorkspacePreferences\(\)[\s\S]*reconcileModels/,
  "Preference routes must consume shared preferences and reconcile model catalog changes through the coordinator.",
);
assert.match(
  templateGalleryRouteSource,
  /fetchWorkspacePageData\(\s*"template-gallery",\s*persistence,/,
  "The template gallery must flush queued preferences before reading route data.",
);
assert.match(
  workspaceRoutePreparationSource,
  /loadTemplateDetailWorkspacePage\(\)[\s\S]{0,100}loadDocumentCanvas\(\)/,
  "Template preparation must preload the independent detail route entry.",
);
const openTemplateSource = templateGalleryRouteSource.slice(
  templateGalleryRouteSource.indexOf("const openTemplate"),
  templateGalleryRouteSource.indexOf("const createCustomTemplate"),
);
assert.match(
  openTemplateSource,
  /prepareTemplateDetailRoute\(templateId, persistence, \{\s*signal: intent\.signal/,
  "Template card navigation must freshly validate its target with the shared intent.",
);
const templateDetailCommitSource = templateGalleryRouteSource.slice(
  templateGalleryRouteSource.indexOf("const commitTemplateDetailNavigation"),
  templateGalleryRouteSource.indexOf("const openTemplate"),
);
assert.match(
  templateDetailCommitSource,
  /!intent\.isCurrent\(\)[\s\S]*intent\.finish\(\)[\s\S]{0,160}navigate\(/,
  "Template detail commits must be owned by the latest shared intent.",
);

assert.doesNotMatch(
  templateGalleryRouteSource,
  /detailNavigationIntentRef|detailNavigationAbortRef|new AbortController\(\)\.signal/,
  "Template cards and mutations must not retain private navigation owners.",
);
assert.doesNotMatch(
  templateGalleryRouteSource,
  /import\("@\/components\/resume-builder"\)|import\("@\/components\/templates\/template-editor"\)/,
  "Template navigation must not warm the removed Builder-owned detail surface.",
);
assert.match(
  workspaceRoutePreparationSource,
  /loadTemplateDetailRouteData[\s\S]{0,800}fetchWorkspacePageData\("template-detail", persistence, \{[\s\S]{0,120}signal: options\.signal/,
  "Direct template loads and click preparation must share one fresh target-validating read.",
);
assert.match(
  templateDetailRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "Template detail must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  templateDetailRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*showWorkspaceLoadError\([\s\S]*setHasLoadError\(true\)/,
  "Cancelled and stale template detail requests must exit before retry state and Toast.",
);
assert.match(
  templateDetailInitialRouteSource,
  /getTemplateDetailRouteHandoff\(routeState, templateId\)[\s\S]{0,500}getTemplateCatalog/,
  "Template detail must seed its first frame from the typed gallery handoff.",
);
assert.match(
  templateDetailRouteSource,
  /resolveInitialTemplateDetail\(messages, routeState, templateId\)/,
  "Template detail must consume its typed initial-route resolver.",
);
assert.match(
  templateDetailRouteSource,
  /if \(initialDetail && retryKey === 0\)[\s\S]{0,500}setIsLoading\(false\);\s*return;/,
  "A complete template handoff must skip the direct-URL loader entirely.",
);
assert.doesNotMatch(
  templateDetailRouteSource,
  /calibrationFingerprintRef|priorPersistedFingerprint/,
  "Template detail must not retain the retired handoff calibration path.",
);
assert.match(
  templateDetailPageSource,
  /useState\(routeState\)[\s\S]{0,600}replace:\s*true, state:\s*null[\s\S]{0,500}routeState:\s*initialRouteState/,
  "Template detail must consume complete handoff state once and scrub it from history.",
);
assert.match(
  templateDetailPageSource,
  /useNavigationType\(\)[\s\S]{0,180}useLayoutEffect\([\s\S]{0,180}navigationType !== ["']PUSH["'][\s\S]{0,180}window\.scrollTo\([\s\S]{0,120}top:\s*0[\s\S]{0,180}getElementById\(["']main-content["']\)[\s\S]{0,60}\?\.focus\(\{\s*preventScroll:\s*true\s*\}\)/,
  "Template detail PUSH entry must hand focus to main content without reacting to its history scrub.",
);
for (const specifier of [
  "@/components/workspace/use-template-detail-save",
  "@/components/workspace/use-template-detail-leave",
]) {
  assert.ok(
    hasImport(parseSource(templateDetailRouteSource), specifier),
    "Template detail must compose persistence and leave protection through their owning hooks.",
  );
}

assert.match(
  templateDetailLeaveSource,
  /useBlocker\(hasUnsavedChanges\)[\s\S]*beforeunload[\s\S]*saveAndLeave[\s\S]*discardAndLeave/,
  "Template detail must own history, browser-close, save, and discard leave behavior.",
);
const templateCopySource = templateDetailRouteSource.slice(
  templateDetailRouteSource.indexOf("const createCustomTemplate"),
  templateDetailRouteSource.indexOf("const updateTemplate"),
);
assert.match(
  templateCopySource,
  /const intent = beginNavigation\(\)[\s\S]*await save\(\)[\s\S]*!intent\.isCurrent\(\)[\s\S]*createTemplateApi\([\s\S]*setCustomTemplates\([\s\S]*!intent\.isCurrent\(\)[\s\S]*adoptPersistedTemplate\([\s\S]*intent\.finish\(\)[\s\S]*navigate\(/,
  "Creating an editable template copy may update the catalog, but only the latest intent may adopt it or navigate.",
);
assert.match(
  templateDetailRouteSource,
  /const logout = useCallback\([\s\S]{0,500}const intent = beginNavigation\(\)[\s\S]{0,260}requestLeave\([\s\S]{0,180}intent\.finish\(\)[\s\S]{0,100}onLogout\(\)[\s\S]{0,100}intent\.cancel/,
  "Template logout must share dirty-state resolution without allowing an older navigation to commit.",
);
assert.match(
  resumeGalleryRouteSource,
  /fetchWorkspacePageData\(\s*"resume-gallery",\s*persistence,/,
  "The resume gallery must flush queued preferences before reading route data.",
);
const galleryDetailCommits = findNodes(
  parseSource(resumeGalleryRouteSource),
  (node) =>
    ts.isCallExpression(node) &&
    getMemberPath(node.expression) === "commitResumeDetailNavigation",
);
for (const call of galleryDetailCommits) {
  assert.equal(call.arguments.length >= 5, true);
  assert.ok(call.arguments[3] && call.arguments[4]);
}
assert.equal(galleryDetailCommits.length, 3);
assert.match(
  resumeGalleryRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "The resume gallery must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  resumeGalleryRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*showWorkspaceLoadError\([\s\S]*setHasLoadError\(true\)/,
  "Cancelled and stale resume gallery requests must exit before retry state and Toast.",
);
const openResumeSource = resumeGalleryRouteSource.slice(
  resumeGalleryRouteSource.indexOf("const openResume"),
  resumeGalleryRouteSource.indexOf("const createResume"),
);
assert.match(
  resumeGalleryRouteSource,
  /const preloadResumeDetail = useCallback\([\s\S]{0,300}preloadResumeDetailRoute\(\)/,
  "Resume gallery intent must preload only the existing detail modules before navigation.",
);
assert.ok(
  resumeGalleryPageSource.includes(
    "onPreloadResumeDetail={gallery.preloadResumeDetail}",
  ) &&
    resumeGallerySource.includes("onPreloadResumeDetail") &&
    resumeGalleryGridSource.includes("onPreloadResumeDetail") &&
    resumeGalleryCardSource.includes("onPreloadDetail"),
  "Resume detail preload intent must flow explicitly from the route owner to each card.",
);
assert.match(
  resumeGalleryCardSource,
  /aria-busy=\{isOpening \|\| undefined\}[\s\S]{0,900}onPointerEnter=\{preloadDetail\}[\s\S]{0,120}onFocus=\{preloadDetail\}[\s\S]{0,120}onPointerDown=\{preloadDetail\}/,
  "Resume cards must preload on pointer, focus, and touch intent while reporting semantic pending navigation.",
);
assert.doesNotMatch(
  resumeGalleryCardSource,
  /components\/ui\/spinner|<Spinner/,
  "Opening an existing resume must keep its card visually stable without a loading icon.",
);
assert.match(
  openResumeSource,
  /setOpeningResumeId\(resumeId\)[\s\S]*prepareResumeDetailRoute\(resumeId, persistence, \{\s*signal: intent\.signal[\s\S]*clearOpeningResume\(resumeId\)/,
  "Resume card navigation must freshly validate its target with the shared intent.",
);
assert.match(
  openResumeSource,
  /commitResumeDetailNavigation\(\s*intent,\s*prepared,\s*resumeId/,
  "Resume card navigation must hand one complete prepared payload to the cold route.",
);
assert.match(
  resumeGalleryRouteSource,
  /createResumeDetailRouteHandoff\(\s*prepared,\s*resumeOrdinal,\s*resumeCount/,
  "Resume navigation state must contain the complete prepared payload plus gallery position only.",
);
assert.equal(
  (
    resumeGalleryRouteSource.match(
      /prepared = await prepareCreatedResumeDetailRoute\(/g,
    ) ?? []
  ).length,
  2,
  "Resume create and import must combine their mutation response with prepared editor data before navigation.",
);
const resumeDetailCommitSource = resumeGalleryRouteSource.slice(
  resumeGalleryRouteSource.indexOf("const commitResumeDetailNavigation"),
  resumeGalleryRouteSource.indexOf("const openResume"),
);
assert.match(
  resumeDetailCommitSource,
  /!intent\.isCurrent\(\)[\s\S]*startTransition\([\s\S]{0,180}onCommit\?\.\(\)[\s\S]{0,120}setOpeningResumeId\(null\)[\s\S]{0,120}intent\.finish\(\)[\s\S]{0,160}navigate\(/,
  "Resume detail commits must be owned by the latest shared intent.",
);
const createResumeSource = resumeGalleryRouteSource.slice(
  resumeGalleryRouteSource.indexOf("const createResume"),
  resumeGalleryRouteSource.indexOf("const importResume"),
);
assert.match(
  createResumeSource,
  /prepareCreatedResumeDetailRoute\([\s\S]*publishCreatedResume[\s\S]*messages\.resumeCreatedOpenFailed[\s\S]*commitResumeDetailNavigation\(\s*intent,[\s\S]{0,220}publishCreatedResume/,
  "Resume creation must publish only after preparation, publish on preparation failure, and batch success publication with navigation.",
);
assert.ok(
  hasImport(
    parseSource(resumeGalleryRouteSource),
    "@/components/workspace/resume-gallery-import",
    { dynamic: true },
  ),
  "Resume import processing must remain outside the gallery's initial dependency graph.",
);
assert.doesNotMatch(
  resumeGalleryRouteSource,
  /detailNavigationIntentRef|detailNavigationAbortRef|new AbortController\(\)\.signal/,
  "Resume cards and mutations must not retain private navigation owners.",
);
assert.match(
  workspaceDetailHandoffSource,
  /ResumeDetailRouteHandoff \{\s*kind:[\s\S]{0,120}payload: PreparedResumeDetailRouteData;[\s\S]{0,220}createResumeDetailRouteHandoff\(\s*payload:/,
  "Resume handoff must have one complete payload instead of parallel partial and optional forms.",
);
assert.doesNotMatch(
  workspaceDetailHandoffSource,
  /prepared\?|prepared\s*=\s*false/,
  "Detail handoffs must not retain a compatibility path that triggers mount calibration.",
);
assert.match(
  workspaceRoutePreparationSource,
  /loadResumeDetailWorkspacePage\(\)[\s\S]{0,100}loadDocumentCanvas\(\)/,
  "Resume preparation must preload the independent resume-detail route entry.",
);
assert.doesNotMatch(
  resumeGalleryRouteSource,
  /resume-builder/,
  "Resume gallery navigation must not retain the deleted Builder entry.",
);
assert.match(
  resumeDetailPageSource,
  /useParams[\s\S]{0,400}<ResumeDetailRouteOwner[\s\S]{0,100}key=\{id\}/,
  "Resume detail must remount transaction refs when the route id changes.",
);
assert.match(
  resumeDetailPageSource,
  /useState\(routeState\)[\s\S]{0,600}navigate\([\s\S]{0,260}replace:\s*true, state:\s*null[\s\S]{0,500}routeState:\s*initialRouteState/,
  "Resume detail must consume the handoff from history without dropping the current mount's first-frame seed.",
);
assert.match(
  resumeDetailPageSource,
  /useNavigationType\(\)[\s\S]{0,180}useLayoutEffect\([\s\S]{0,180}navigationType !== ["']PUSH["'][\s\S]{0,180}window\.scrollTo\([\s\S]{0,120}top:\s*0[\s\S]{0,180}getElementById\(["']main-content["']\)[\s\S]{0,60}\?\.focus\(\{\s*preventScroll:\s*true\s*\}\)/,
  "Resume detail PUSH entry must hand focus to main content without reacting to its history scrub.",
);
assert.match(
  resumeDetailRouteSource,
  /getResumeDetailRouteHandoff\(routeState, resumeId\)/,
  "Resume detail must seed its first frame from the typed navigation handoff.",
);
assert.ok(
  /initialDetail\.resumeCount \+ 1/.test(resumeDetailRouteSource) &&
    /nextResumeOrdinal,\s*nextResumeOrdinal/.test(resumeDetailRouteSource) &&
    /createDefaultResumeTitle\(messages, resumeOrdinal\)/.test(
      resumeDetailCommandsSource,
    ),
  "A duplicate must advance the handoff count while title fallback keeps the selected document's gallery ordinal.",
);

assert.match(
  resumeDetailLoaderSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "Resume detail must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  resumeDetailLoaderSource,
  /if \(prepared && retryKey === 0\)[\s\S]{0,500}onLoadRef\.current\(prepared\)[\s\S]{0,300}return;/,
  "A complete resume handoff must be consumed without starting the direct-URL loader.",
);
assert.match(
  resumeDetailModelsSource,
  /normalizeModelConfigs\(initialRouteData, locale\)/,
  "Resume detail must initialize its own prepared model catalog synchronously.",
);
const duplicateNavigationSource = resumeDetailRouteSource.slice(
  resumeDetailRouteSource.indexOf("const navigateToResume"),
  resumeDetailRouteSource.indexOf("const documentCommands"),
);
assert.equal(
  (
    duplicateNavigationSource.match(
      /requestLeave\(prepareFreshRoute, intent\.cancel\)/g,
    ) ?? []
  ).length,
  2,
  "The delayed duplicate Toast action must guard both before and after target preparation.",
);
assert.match(
  duplicateNavigationSource,
  /prepareResumeDetailRoute\([\s\S]{0,120}detail\.resume\.id,[\s\S]{0,120}signal: intent\.signal[\s\S]*WORKSPACE_NAVIGATION_ERROR_TOAST_ID/,
  "Viewing a duplicate must freshly validate the delayed target and stay put on failure.",
);
assert.match(
  duplicateNavigationSource,
  /save\.hasUnsavedChanges\(\)[\s\S]{0,100}save\.requiresCheckpointPromotion\(\)[\s\S]{0,180}requestLeave\(prepareFreshRoute, intent\.cancel\)/,
  "Viewing a duplicate must reprepare after late edits or checkpoint promotion.",
);
assert.match(
  duplicateNavigationSource,
  /!intent\.isCurrent\(\)[\s\S]{0,180}intent\.finish\(\)[\s\S]{0,120}navigate\(/,
  "Only the latest duplicate navigation intent may commit.",
);
assert.doesNotMatch(
  duplicateNavigationSource,
  /navigationIntentRef|navigationAbortRef|new AbortController\(\)/,
  "Delayed duplicate navigation must share the global latest-intent transaction.",
);
assert.match(
  resumeDetailRouteSource,
  /const logout = useCallback\([\s\S]{0,500}const intent = beginNavigation\(\)[\s\S]{0,260}requestLeave\([\s\S]{0,180}intent\.finish\(\)[\s\S]{0,100}onLogout\(\)[\s\S]{0,100}intent\.cancel/,
  "Resume logout must share dirty-state resolution without allowing an older navigation to commit.",
);
assert.ok(
  /const \{ isLoading \} = loader[\s\S]*isLoading:\s*isLoading \|\| loader\.hasLoadError/.test(
    resumeDetailRouteSource,
  ),
  "The loader's loading and error states must pause autosave as well as the explicit save shortcut.",
);
assert.doesNotMatch(
  resumeDetailRouteSource + resumeDetailLoaderSource,
  /hasHandoff|onLoadErrorChange|onLoadingChange|hasRouteLoadError|setHasRouteLoadError/,
  "The detail loader must be the single owner of route progress and errors, without mirrored callback state.",
);
assert.doesNotMatch(
  resumeDetailRouteSource,
  /\[isLoading, setIsLoading\]|\[hasLoaded, setHasLoaded\]|\[hasLoadError, setHasLoadError\]/,
  "The composing workspace must consume route state from its loader.",
);
assert.doesNotMatch(
  resumeDetailRouteSource + resumeDetailSaveSource,
  /initialFingerprint|expectedPersistedFingerprint|persistenceEpochRef|hydrateIfUnchanged/,
  "Resume detail must not retain the retired handoff calibration path.",
);
assert.match(
  resumeDetailSaveSource,
  /if \(!hasUnsavedChanges\(\)\) \{[\s\S]{0,220}autosaveBurstStartedAtRef\.current = null[\s\S]{0,120}autosaveRetryAttemptRef\.current = 0[\s\S]{0,120}toast\.dismiss\("autosave-failed"\)/,
  "A clean checkpoint must reset the autosave burst and retry transaction.",
);
const autosaveEffect = findNodes(
  parseSource(resumeDetailSaveSource),
  ts.isCallExpression,
).find(
  (node) =>
    getMemberPath(node.expression) === "useEffect" &&
    node.arguments[0] &&
    hasCall(node.arguments[0], "hasUnsavedChanges"),
);
assert.ok(autosaveEffect, "Autosave must react to unsaved changes.");
const autosaveDependencies = autosaveEffect.arguments[1];
assert.ok(
  autosaveDependencies && ts.isArrayLiteralExpression(autosaveDependencies),
  "Autosave must declare its effect dependencies.",
);
const autosaveDependencyNames = new Set(
  autosaveDependencies.elements.map(getMemberPath),
);
for (const dependency of [
  "authToken",
  "hasUnsavedChanges",
  "isLoading",
  "lastSavedAt",
  "liveFingerprint",
]) {
  assert.ok(
    autosaveDependencyNames.has(dependency),
    `Autosave must react to ${dependency} changes.`,
  );
}
const detailFile = parseSource(resumeDetailRouteSource);
const shortcutRegistration = findNodes(detailFile, ts.isCallExpression).find(
  (node) =>
    getMemberPath(node.expression) === "window.addEventListener" &&
    getLiteralValue(node.arguments[0]) === "keydown",
);
assert.ok(
  shortcutRegistration,
  "The workspace must register its save shortcut.",
);
const shortcutName = getMemberPath(shortcutRegistration.arguments[1]);
const shortcut = findNodes(detailFile, ts.isVariableDeclaration).find(
  (node) => getMemberPath(node.name) === shortcutName,
)?.initializer;
assert.ok(
  shortcut,
  "The registered save shortcut must have an executable handler.",
);
for (const [isLoading, hasLoadError, ctrlKey, metaKey, key, expectedSaves] of [
  [true, false, true, false, "s", 0],
  [false, true, true, false, "s", 0],
  [false, false, true, false, "s", 1],
  [false, false, false, true, "S", 1],
  [false, false, false, false, "s", 0],
  [false, false, true, false, "a", 0],
]) {
  let saves = 0;
  const { onKeyDown } = evaluateTypeScript(
    `export const onKeyDown = ${shortcut.getText()};`,
    {
      globals: {
        isLoading,
        loader: { hasLoadError },
        saveCheckpoint: () => {
          saves += 1;
        },
      },
    },
  );
  onKeyDown({ ctrlKey, metaKey, key, preventDefault() {} });
  assert.equal(
    saves,
    expectedSaves,
    "Save shortcuts must only checkpoint a successfully loaded document.",
  );
}

assert.match(
  resumeDetailRouteSource,
  /hasLoadError:\s*loader\.hasLoadError,[\s\S]{0,80}hasVersionLoadError:\s*save\.hasVersionLoadError/,
  "Route and version failures must remain distinct view states.",
);
assert.match(
  resumeDetailViewSource,
  /hasLoadError=\{state\.hasVersionLoadError\}[\s\S]*model\.state\.hasLoadError \? \([\s\S]{0,120}<WorkspaceRouteError/,
  "Version failures must stay inline while route failures own the full-page retry state.",
);
assert.match(
  resumeDetailSaveSource,
  /const resolveAgentDraftReview[\s\S]*while \(activeRequestRef\.current\)[\s\S]*resolveAgentDraftDecision[\s\S]*resolution\.committed[\s\S]*resolution\.resolvedAsRequested[\s\S]*adoptPersistedSave/,
  "Resume detail must keep serialized saves and protect edits made during an active request.",
);
assert.ok(
  /useBlocker\(shouldBlockNavigation\)[\s\S]*beforeunload/.test(
    resumeDetailLeaveSource,
  ) && /promoteCheckpoint[\s\S]*discardAndLeave/.test(resumeDetailLeaveSource),
  "Resume detail must own history, browser-close, checkpoint promotion, and discard behavior.",
);
assert.match(
  resumeDetailLeaveSource,
  /useRef<Promise<void> \| null>\(null\)[\s\S]*checkpointPromotionInFlightRef\.current \?\?[\s\S]*promotion\.then\(/,
  "Every leave request must await the shared checkpoint promotion instead of dropping a newer navigation.",
);
assert.doesNotMatch(
  resumeDetailLeaveSource,
  /if \(checkpointPromotionInFlightRef\.current\) \{\s*return;/,
  "An in-flight checkpoint must not swallow the latest navigation intent.",
);
assert.match(
  templateGalleryRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "The template gallery must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  templateGalleryRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*showWorkspaceLoadError\([\s\S]*setHasLoadError\(true\)/,
  "Cancelled and stale template requests must exit before retry state and Toast.",
);
assert.match(
  trashRouteSource,
  /fetchWorkspacePageData\(\s*"trash",\s*persistence,/,
  "Trash must flush queued preferences before reading route data.",
);
assert.match(
  trashRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "Trash must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  trashRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*showWorkspaceLoadError\([\s\S]*setHasLoadError\(true\)/,
  "Cancelled and stale trash requests must exit before retry state and Toast.",
);
console.log("Workspace route ownership verified.");
