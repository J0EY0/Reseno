import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import vm from "node:vm";
import * as ts from "typescript";

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
  resumeDetailPreferencesSource,
  resumeDetailSaveSource,
  resumeDetailLeaveSource,
  modelsPageSource,
  settingsPageSource,
  templateGalleryPageSource,
  templateGalleryRouteSource,
  templateDetailPageSource,
  templateDetailRouteSource,
  templateDetailSaveSource,
  templateDetailLeaveSource,
  trashPageSource,
  trashRouteSource,
  lateralLayoutSource,
  shellSource,
  workspaceThemeSource,
  sidebarSource,
  preferencesRouteSource,
  lateralRouteDataSource,
  persistenceSource,
  preparedNavigationSource,
  navigationTransactionSource,
  workspaceRoutePreparationSource,
  workspaceRouteLoadersSource,
  routeLoaderSource,
  workspaceRouteSource,
  workspaceRouteMemorySource,
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
  readText("src/components/workspace/use-resume-detail-preferences.ts"),
  readText("src/components/workspace/use-resume-detail-save.ts"),
  readText("src/components/workspace/use-resume-detail-leave.ts"),
  readText("src/components/workspace/models-workspace-page.tsx"),
  readText("src/components/workspace/settings-workspace-page.tsx"),
  readText("src/components/workspace/template-gallery-workspace-page.tsx"),
  readText("src/components/workspace/use-template-gallery-workspace.ts"),
  readText("src/components/workspace/template-detail-workspace-page.tsx"),
  readText("src/components/workspace/use-template-detail-workspace.ts"),
  readText("src/components/workspace/use-template-detail-save.ts"),
  readText("src/components/workspace/use-template-detail-leave.ts"),
  readText("src/components/workspace/trash-workspace-page.tsx"),
  readText("src/components/workspace/use-trash-workspace.ts"),
  readText("src/components/workspace/workspace-lateral-layout.tsx"),
  readText("src/components/workspace/workspace-shell.tsx"),
  readText("src/components/workspace/workspace-theme.tsx"),
  readText("src/components/app-sidebar.tsx"),
  readText("src/components/workspace/use-workspace-preferences-route.ts"),
  readText("src/components/workspace/use-workspace-lateral-route-data.ts"),
  readText("src/lib/workspace-preferences-persistence.ts"),
  readText(
    "src/components/workspace/use-prepared-workspace-navigation.ts",
  ),
  readText(
    "src/components/workspace/use-workspace-navigation-transaction.ts",
  ),
  readText("src/components/workspace/workspace-route-preparation.ts"),
  readText("src/components/workspace/workspace-route-loaders.ts"),
  readText("src/lib/route-loader.ts"),
  readText("src/lib/workspace-route.ts"),
  readText("src/lib/workspace-route-memory.ts"),
  readText("src/components/resume-gallery.tsx"),
  readText("src/components/resume-gallery-grid.tsx"),
  readText("src/components/resume-gallery-card.tsx"),
]);
const resumeDetailCommandsSource = await readText(
  "src/components/workspace/use-resume-detail-commands.ts",
);

for (const routeEntry of [
  "resume-gallery-workspace-page",
  "resume-detail-workspace-page",
  "models-workspace-page",
  "settings-workspace-page",
  "template-gallery-workspace-page",
  "template-detail-workspace-page",
  "trash-workspace-page",
]) {
  assert.match(
    workspaceRouteLoadersSource,
    new RegExp(`import\\("@/components/workspace/${routeEntry}"\\)`),
    `${routeEntry} must remain a literal, statically analyzable lazy entry.`,
  );
  assert.doesNotMatch(
    appSource + workspaceRoutePreparationSource,
    new RegExp(`import\\("@/components/workspace/${routeEntry}"\\)`),
    `${routeEntry} must have one shared dynamic-import owner.`,
  );
}
for (const routeLoader of [
  "loadResumeGalleryWorkspacePage",
  "loadResumeDetailWorkspacePage",
  "loadModelsWorkspacePage",
  "loadSettingsWorkspacePage",
  "loadTemplateGalleryWorkspacePage",
  "loadTemplateDetailWorkspacePage",
  "loadTrashWorkspacePage",
  "loadWorkspaceLateralLayout",
]) {
  assert.match(
    appSource,
    new RegExp(`lazy\\(${routeLoader}\\)`),
    `${routeLoader} must be consumed directly by React.lazy.`,
  );
}
assert.match(
  appSource,
  /from "@\/components\/workspace\/workspace-route-loaders"/,
  "App lazy routes must consume the shared workspace route loaders.",
);
assert.match(
  routeLoaderSource,
  /function createRouteLoader[\s\S]{0,220}let request:[\s\S]{0,180}request \|\|= loader\(\)\.then/,
  "Workspace route preload and React.lazy must share one memoized module Promise.",
);
const appRouteSuspenseSource = appSource.slice(
  appSource.indexOf("function AppRouteSuspense"),
  appSource.indexOf("function DocumentMetadata"),
);
assert.doesNotMatch(
  appRouteSuspenseSource,
  /ViewTransitionBoundary|slide-(?:up|down)/,
  "Route Suspense resolution must not animate loading into content; explicit workspace navigation owns route motion.",
);
assert.match(appSource, /<Route path="\/resume"/);
assert.match(appSource, /<Route path="\/resume\/:id"/);
assert.match(appSource, /<Route path="\/models"/);
assert.match(appSource, /<Route path="\/settings"/);
assert.match(appSource, /<Route path="\/templates"/);
assert.match(appSource, /<Route path="\/template\/:id"/);
assert.match(appSource, /<Route path="\/trash"/);
assert.match(
  appSource,
  /loadWorkspaceLateralLayout[\s\S]*?<Route element=\{renderWorkspaceLateralLayout\(\)\}>[\s\S]*?<Route path="\/resume"[\s\S]*?<Route path="\/trash"[\s\S]*?<\/Route>/,
  "The five lateral routes must share one lazy persistent workspace layout.",
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
  /case "resume":\s*return loadResumeGalleryWorkspacePage\(\)/,
  "Prepared workspace navigation must preload the independent resume gallery route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /case "models":\s*return loadModelsWorkspacePage\(\)/,
  "Prepared workspace navigation must preload the models route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /case "settings":\s*return loadSettingsWorkspacePage\(\)/,
  "Prepared workspace navigation must preload the settings route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /case "templates":\s*return loadTemplateGalleryWorkspacePage\(\)/,
  "Prepared workspace navigation must preload the template gallery route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /case "trash":\s*return loadTrashWorkspacePage\(\)/,
  "Prepared workspace navigation must preload the trash route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /return Promise\.all\(\[\s*loadWorkspaceLateralLayout\(\),\s*loadWorkspaceRoute\(view\),\s*\]\)/,
  "Prepared lateral navigation must preload the persistent layout with its child route.",
);
assert.match(
  workspaceRoutePreparationSource,
  /Promise\.all\(\[\s*preloadWorkspaceRoute\(view\),\s*loadWorkspaceRouteData\(view, persistence, options\),\s*\]\)/,
  "Workspace preparation must load the route module and flushed route data in parallel.",
);
assert.match(
  workspaceRoutePreparationSource,
  /await persistence\.flush\(\)[\s\S]{0,2200}fetchWorkspaceRouteData\("settings",\s*\{\s*notifyOnError:\s*false,\s*signal:\s*options\.signal/,
  "Prepared route reads must wait for queued preference writes and suppress duplicate error Toasts.",
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
  workspaceRouteMemorySource,
  /WorkspaceLateralRouteHandoffState[\s\S]{0,300}token:\s*string[\s\S]*routeDataByToken = new Map[\s\S]*committedRouteDataByView = new Map<[\s\S]{0,80}WorkspaceView[\s\S]*rememberWorkspaceLateralRoute[\s\S]*Object\.prototype\.hasOwnProperty\.call\(candidate, "data"\)/,
  "Lateral history must contain only a token while validated one-time and per-view committed data stay in bounded memory.",
);
const lateralHistoryStateSource = workspaceRouteMemorySource.slice(
  workspaceRouteMemorySource.indexOf(
    "export type WorkspaceLateralRouteHandoffState",
  ),
  workspaceRouteMemorySource.indexOf(
    "export interface WorkspaceLateralRouteResolution",
  ),
);
assert.doesNotMatch(
  lateralHistoryStateSource,
  /data\s*:/,
  "The browser-cloned lateral state must never contain route payload data.",
);
assert.match(
  lateralRouteDataSource,
  /const \[resolution\] = useState\(\(\) =>[\s\S]{0,120}resolveWorkspaceLateralRoute\(location\.state, view\)[\s\S]{0,300}resolution\.shouldScrubHistory[\s\S]{0,300}deleteWorkspaceLateralRouteHandoff\(resolution\.tokenToDelete\)[\s\S]{0,300}replace:\s*true, state:\s*null[\s\S]*return resolution\.data/,
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
  /authGate\.phase === "app"[\s\S]{0,160}hasEnteredAuthenticatedAppRef\.current = true[\s\S]{0,180}!hasEnteredAuthenticatedAppRef\.current[\s\S]{0,240}import\("@\/lib\/workspace-route-memory"\)[\s\S]{0,160}clearWorkspaceLateralRouteMemory\(\)/,
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
  /<WorkspaceThemeProvider[\s\S]*?<WorkspaceShell[\s\S]*?<Outlet \/>/,
  "The lateral layout must keep theme, Sidebar, and Header mounted around the changing route outlet.",
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
  workspaceThemeSource,
  /WorkspaceThemeProvider[\s\S]*?prefers-color-scheme: dark[\s\S]*?persistence\.enqueue/,
  "The persistent lateral layout must own one theme surface and serialized persistence path.",
);
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
  /const commitPreparedRoute[\s\S]{0,900}createWorkspaceLateralRouteHandoff\(prepared\)[\s\S]{0,160}intent\.finish\(\)[\s\S]{0,120}navigate\(path, \{ state \}\)[\s\S]{0,260}deleteWorkspaceLateralRouteHandoff\(handoffToken\)[\s\S]{0,300}WORKSPACE_NAVIGATION_ERROR_TOAST_ID/,
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
  preferencesRouteSource,
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
  /await persistence\.flush\(\)[\s\S]{0,900}fetchWorkspaceRouteData\(\s*kind/,
  "A route must wait for queued settings writes before reading server state.",
);
assert.match(
  preferencesRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*id:\s*"workspace-load-error"[\s\S]*setHasLoadError\(true\)/,
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
  /persistence\.enqueue\([\s\S]*onRollback\(persisted\)[\s\S]*onError\(error\)/,
  "Preference mutations must use the shared serialized rollback coordinator.",
);
assert.match(
  templateGalleryRouteSource,
  /await persistence\.flush\(\)[\s\S]{0,900}fetchWorkspaceRouteData\(\s*"template-gallery"/,
  "The template gallery must flush queued preferences before reading route data.",
);
assert.match(
  workspaceRoutePreparationSource,
  /loadTemplateDetailWorkspacePage\(\)[\s\S]{0,100}loadDocumentPreviewCard\(\)/,
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
assert.match(
  openTemplateSource,
  /commitTemplateDetailNavigation\(\s*intent,\s*templateId,\s*data/,
  "Template card navigation must commit the complete prepared handoff.",
);
assert.equal(
  (templateGalleryRouteSource.match(/await detailRouteReady;/g) ?? []).length,
  2,
  "Template create and import must finish preparing the detail module before navigation.",
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
for (const [start, end, label] of [
  ["const createCustomTemplate", "const importTemplates", "creation"],
  ["const importTemplates", "const deleteTemplates", "import"],
]) {
  const mutationSource = templateGalleryRouteSource.slice(
    templateGalleryRouteSource.indexOf(start),
    templateGalleryRouteSource.indexOf(end),
  );
  assert.match(
    mutationSource,
    /const intent = beginNavigation\(\)[\s\S]*setCustomTemplates\([\s\S]{0,180}!intent\.isCurrent\(\)[\s\S]*await detailRouteReady[\s\S]*commitTemplateDetailNavigation\(\s*intent/,
    `Template ${label} must keep its mutation result but never navigate after a newer intent.`,
  );
}
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
  /loadTemplateDetailRouteData[\s\S]{0,500}await persistence\.flush\(\)[\s\S]{0,300}fetchWorkspaceRouteData\("template-detail", \{[\s\S]{0,120}signal: options\.signal/,
  "Direct template loads and click preparation must share one fresh target-validating read.",
);
assert.match(
  templateDetailRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "Template detail must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  templateDetailRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*id:\s*"workspace-load-error"[\s\S]*setHasLoadError\(true\)/,
  "Cancelled and stale template detail requests must exit before retry state and Toast.",
);
assert.match(
  templateDetailRouteSource,
  /getTemplateDetailRouteHandoff\(routeState, templateId\)[\s\S]{0,500}getTemplateCatalog/,
  "Template detail must seed its first frame from the typed gallery handoff.",
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
assert.match(
  templateDetailSaveSource,
  /activeRequestRef[\s\S]*submittedFingerprint[\s\S]*acceptedFingerprints[\s\S]*onAdoptSavedTemplateRef/,
  "Template detail must keep serialized saves and protect edits made during an active request.",
);
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
  /await persistence\.flush\(\)[\s\S]{0,900}fetchWorkspaceRouteData\(\s*"resume-gallery"/,
  "The resume gallery must flush queued preferences before reading route data.",
);
assert.ok(
  /targetIndex \+ 1,\s*resumes\.length/.test(resumeGalleryRouteSource) &&
    /resumes\.length \+ savedImports\.length/.test(resumeGalleryRouteSource) &&
    /resumeCount/.test(workspaceRouteSource) &&
    /resumeOrdinal/.test(workspaceRouteSource),
  "The typed handoff must preserve the gallery ordinal and count without another detail request.",
);
assert.match(
  resumeGalleryRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "The resume gallery must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  resumeGalleryRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*id:\s*"workspace-load-error"[\s\S]*setHasLoadError\(true\)/,
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
const importResumeSource = resumeGalleryRouteSource.slice(
  resumeGalleryRouteSource.indexOf("const importResume"),
  resumeGalleryRouteSource.indexOf("const moveResumesToTrash"),
);
assert.match(
  importResumeSource,
  /const intent = beginNavigation\(\)[\s\S]*setResumes\([\s\S]{0,300}!intent\.isCurrent\(\)[\s\S]*prepareCreatedResumeDetailRoute\([\s\S]{0,180}signal: intent\.signal[\s\S]*commitResumeDetailNavigation\(\s*intent/,
  "Resume import must keep its mutation result but never navigate after a newer intent.",
);
assert.doesNotMatch(
  resumeGalleryRouteSource,
  /detailNavigationIntentRef|detailNavigationAbortRef|new AbortController\(\)\.signal/,
  "Resume cards and mutations must not retain private navigation owners.",
);
assert.match(
  workspaceRouteSource,
  /ResumeDetailRouteHandoff \{\s*kind:[\s\S]{0,120}payload: PreparedResumeDetailRouteData;[\s\S]{0,220}createResumeDetailRouteHandoff\(\s*payload:/,
  "Resume handoff must have one complete payload instead of parallel partial and optional forms.",
);
assert.doesNotMatch(
  workspaceRouteSource,
  /prepared\?|prepared\s*=\s*false/,
  "Detail handoffs must not retain a compatibility path that triggers mount calibration.",
);
assert.match(
  workspaceRoutePreparationSource,
  /loadResumeDetailWorkspacePage\(\)[\s\S]{0,100}loadDocumentPreviewCard\(\)/,
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
  workspaceRoutePreparationSource,
  /loadResumeDetailRouteData[\s\S]{0,600}fetchWorkspaceRouteData\("resume-detail"[\s\S]{0,300}fetchResumeApi\(resumeId[\s\S]{0,300}fetchResumeVersionsApi\(resumeId[\s\S]{0,500}Promise\.all/,
  "Resume preparation and direct loads must share one parallel abortable read transaction.",
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
  resumeDetailPreferencesSource,
  /initialRouteData\?: ResumeEditorRouteData[\s\S]{0,900}normalizeModelConfigs\(initialRouteData, locale\)[\s\S]{0,900}initialRouteData\?\.agentSettings/,
  "Prepared model and Agent preferences must initialize synchronously for the first detail frame.",
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
  /isLoading:\s*isLoading \|\| hasRouteLoadError/.test(
    resumeDetailRouteSource,
  ) &&
    /onLoadErrorChange:\s*setHasRouteLoadError/.test(
      resumeDetailRouteSource,
    ),
  "A route calibration failure must pause autosave as well as the explicit save shortcut.",
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
assert.match(
  resumeDetailSaveSource,
  /\[\s*hasUnsavedChanges,[\s\S]{0,100}isLoading,[\s\S]{0,100}lastSavedAt,[\s\S]{0,160}liveFingerprint/,
  "A manual checkpoint must trigger the clean autosave reset even when the live content fingerprint is unchanged.",
);
assert.match(
  resumeDetailRouteSource,
  /event\.key\.toLowerCase\(\) !== "s"[\s\S]{0,240}isLoading \|\| loader\.hasLoadError[\s\S]{0,120}saveResume\("checkpoint"\)/,
  "The save shortcut must not persist an uncalibrated handoff after route loading fails.",
);
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
  /const resolveAppliedAgentDraft[\s\S]*while \(activeRequestRef\.current\)[\s\S]*resolveAgentDraftDecision[\s\S]*resolution\.committed[\s\S]*adoptPersistedSave/,
  "Resume detail must keep serialized saves and protect edits made during an active request.",
);
assert.ok(
  /useBlocker\(shouldBlockNavigation\)[\s\S]*beforeunload/.test(
    resumeDetailLeaveSource,
  ) &&
    /promoteCheckpoint[\s\S]*discardAndLeave/.test(resumeDetailLeaveSource),
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
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*id:\s*"workspace-load-error"[\s\S]*setHasLoadError\(true\)/,
  "Cancelled and stale template requests must exit before retry state and Toast.",
);
assert.match(
  trashRouteSource,
  /await persistence\.flush\(\)[\s\S]{0,900}fetchWorkspaceRouteData\(\s*"trash"/,
  "Trash must flush queued preferences before reading route data.",
);
assert.match(
  trashRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "Trash must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  trashRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*id:\s*"workspace-load-error"[\s\S]*setHasLoadError\(true\)/,
  "Cancelled and stale trash requests must exit before retry state and Toast.",
);
assert.match(
  trashRouteSource,
  /for \(const resumeId of resumeIds\)[\s\S]{0,100}await restoreResumeApi\(resumeId\)[\s\S]*setDeletedResumes\(\(current\)/,
  "Trash must own sequential resume restore and remove restored items from its route state.",
);
assert.match(
  trashRouteSource,
  /for \(const templateId of templateIds\)[\s\S]{0,120}await restoreTemplateApi\(templateId\)[\s\S]*setDeletedTemplates\(\(current\)[\s\S]*setCustomTemplates\(\(current\)/,
  "Trash must restore templates into its local catalog and remove their deleted records.",
);
assert.match(
  trashRouteSource,
  /for \(const resumeId of resumeIds\)[\s\S]{0,100}await deleteResumeForeverApi\(resumeId\)/,
  "Trash must keep permanent resume deletion serialized.",
);
assert.match(
  trashRouteSource,
  /for \(const templateId of templateIds\)[\s\S]{0,100}await deleteTemplateForeverApi\(templateId\)/,
  "Trash must keep permanent template deletion serialized.",
);

const compiledPersistence = ts.transpileModule(persistenceSource, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const persistenceModule = { exports: {} };
const cachedThemes = [];
vm.runInNewContext(compiledPersistence, {
  exports: persistenceModule.exports,
  module: persistenceModule,
  require(specifier) {
    assert.equal(specifier, "@/lib/workspace-theme");
    return {
      saveWorkspaceThemePreference(theme) {
        cachedThemes.push(theme);
      },
    };
  },
});

const { createWorkspacePreferencesPersistence } = persistenceModule.exports;
const persistence = createWorkspacePreferencesPersistence();
const base = {
  locale: "en",
  theme: "light",
  agentSettings: { defaultModelId: "base" },
};
const first = {
  locale: "en",
  theme: "dark",
  agentSettings: { defaultModelId: "first" },
};
const second = {
  locale: "zh",
  theme: "system",
  agentSettings: { defaultModelId: "second" },
};
const order = [];
let releaseFirst;
const firstGate = new Promise((resolve) => {
  releaseFirst = resolve;
});

persistence.hydrate(base);
assert.deepEqual(cachedThemes, ["light"]);
persistence.enqueue(
  first,
  async () => {
    order.push("first:start");
    await firstGate;
    order.push("first:end");
  },
  { onError: () => assert.fail("first save failed"), onRollback: () => {} },
);
persistence.enqueue(
  second,
  async () => {
    order.push("second");
  },
  { onError: () => assert.fail("second save failed"), onRollback: () => {} },
);

await new Promise((resolve) => setTimeout(resolve, 0));
assert.deepEqual(order, ["first:start"], "Preference writes must be serialized.");
assert.deepEqual(
  cachedThemes,
  ["light"],
  "The first-paint cache must not commit an in-flight preference.",
);
releaseFirst();
await persistence.flush();
assert.deepEqual(order, ["first:start", "first:end", "second"]);
assert.deepEqual(persistence.getSnapshot(), second);
assert.deepEqual(cachedThemes, ["light", "dark", "system"]);

let staleRollbackCount = 0;
const newest = {
  locale: "en",
  theme: "light",
  agentSettings: { defaultModelId: "newest" },
};
persistence.enqueue(
  { ...second, theme: "dark" },
  async () => {
    throw new Error("stale expected failure");
  },
  { onError: () => {}, onRollback: () => staleRollbackCount++ },
);
persistence.enqueue(newest, async () => {}, {
  onError: () => assert.fail("newest save failed"),
  onRollback: () => assert.fail("newest save rolled back"),
});
await persistence.flush();
assert.equal(staleRollbackCount, 0, "An older failure must not revert newer UI.");
assert.deepEqual(persistence.getSnapshot(), newest);
assert.deepEqual(
  cachedThemes,
  ["light", "dark", "system", "light"],
  "Only committed preference writes may update the first-paint cache.",
);

let rollbackSnapshot = null;
persistence.enqueue(
  { ...newest, theme: "dark" },
  async () => {
    throw new Error("expected failure");
  },
  {
    onError: () => {},
    onRollback: (snapshot) => {
      rollbackSnapshot = snapshot;
    },
  },
);
await persistence.flush();
assert.deepEqual(
  rollbackSnapshot,
  newest,
  "The latest failed mutation must roll back to the last committed snapshot.",
);
assert.deepEqual(
  cachedThemes,
  ["light", "dark", "system", "light"],
  "A failed latest mutation must leave the committed first-paint theme intact.",
);

console.log("Workspace route ownership and preference persistence verified.");
