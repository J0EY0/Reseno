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
  shellSource,
  preferencesRouteSource,
  lateralRouteDataSource,
  persistenceSource,
  preparedNavigationSource,
  workspaceRoutePreparationSource,
  workspaceRouteSource,
  workspaceRouteMemorySource,
] = await Promise.all([
  readText("src/App.tsx"),
  readText("src/components/workspace/resume-gallery-workspace-page.tsx"),
  readText("src/components/workspace/use-resume-gallery-workspace.ts"),
  readText("src/components/workspace/resume-detail-workspace-page.tsx"),
  readText("src/components/workspace/use-resume-detail-workspace.ts"),
  readText("src/components/workspace/resume-detail-workspace-view.tsx"),
  readText("src/components/workspace/use-resume-detail-loader.ts"),
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
  readText("src/components/workspace/workspace-shell.tsx"),
  readText("src/components/workspace/use-workspace-preferences-route.ts"),
  readText("src/components/workspace/use-workspace-lateral-route-data.ts"),
  readText("src/lib/workspace-preferences-persistence.ts"),
  readText(
    "src/components/workspace/use-prepared-workspace-navigation.ts",
  ),
  readText("src/components/workspace/workspace-route-preparation.ts"),
  readText("src/lib/workspace-route.ts"),
  readText("src/lib/workspace-route-memory.ts"),
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
    appSource,
    new RegExp(`import\\("@/components/workspace/${routeEntry}"\\)`),
    `${routeEntry} must remain a literal, statically analyzable lazy entry.`,
  );
}
assert.match(appSource, /<Route path="\/resume"/);
assert.match(appSource, /<Route path="\/resume\/:id"/);
assert.match(appSource, /<Route path="\/models"/);
assert.match(appSource, /<Route path="\/settings"/);
assert.match(appSource, /<Route path="\/templates"/);
assert.match(appSource, /<Route path="\/template\/:id"/);
assert.match(appSource, /<Route path="\/trash"/);
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
  /case "resume":\s*return import\(\s*"@\/components\/workspace\/resume-gallery-workspace-page"\s*\)/,
  "Prepared workspace navigation must preload the independent resume gallery route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /case "models":\s*return import\(\s*"@\/components\/workspace\/models-workspace-page"\s*\)/,
  "Prepared workspace navigation must preload the models route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /case "settings":\s*return import\(\s*"@\/components\/workspace\/settings-workspace-page"\s*\)/,
  "Prepared workspace navigation must preload the settings route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /case "templates":\s*return import\(\s*"@\/components\/workspace\/template-gallery-workspace-page"\s*\)/,
  "Prepared workspace navigation must preload the template gallery route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /case "trash":\s*return import\(\s*"@\/components\/workspace\/trash-workspace-page"\s*\)/,
  "Prepared workspace navigation must preload the trash route entry.",
);
assert.match(
  workspaceRoutePreparationSource,
  /Promise\.all\(\[\s*loadWorkspaceRouteModule\(view\),\s*loadWorkspaceRouteData\(view, persistence\),\s*\]\)/,
  "Workspace preparation must load the route module and flushed route data in parallel.",
);
assert.match(
  workspaceRoutePreparationSource,
  /await persistence\.flush\(\)[\s\S]{0,1800}fetchWorkspaceRouteData\("settings",\s*\{\s*notifyOnError:\s*false,?\s*\}\)/,
  "Prepared route reads must wait for queued preference writes and suppress duplicate error Toasts.",
);
assert.doesNotMatch(
  workspaceRoutePreparationSource,
  /fetchWorkspaceRouteData\([\s\S]{0,100}signal\s*:/,
  "Prepared GETs must stay uncancelled so requestApi can share its three-second cache.",
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
  /WorkspaceLateralRouteHandoffState[\s\S]{0,300}token:\s*string[\s\S]*routeDataByToken = new Map[\s\S]*latestRouteDataByView = new Map[\s\S]*rememberWorkspaceLateralRoute[\s\S]*Object\.prototype\.hasOwnProperty\.call\(candidate, "data"\)/,
  "Lateral history must contain only a token while validated one-time and per-view data stay in bounded memory.",
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
  "The consumer must freeze its first frame from handoff or latest view memory and scrub one-time or dead tokens before paint.",
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
  /authGate\.phase !== "app"[\s\S]{0,100}clearWorkspaceLateralRouteMemory\(\)/,
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
assert.match(shellSource, /<ViewTransitionBoundary/);
assert.doesNotMatch(
  shellSource,
  /import\("@\/components\/resume-builder"\)/,
  "The shared gallery shell must not pull the detail-owned builder slice.",
);
assert.match(
  shellSource,
  /prepareWorkspaceRoute\(view, persistence\)\.catch\(\(\) => undefined\)/,
  "Sidebar hover and focus preparation must never create an unhandled rejection.",
);
assert.match(
  shellSource,
  /await prepareWorkspaceRoute\(view, persistence\)[\s\S]{0,300}createWorkspaceLateralRouteHandoff\(prepared\)[\s\S]{0,160}navigate\(path, \{ state \}\)[\s\S]{0,160}catch[\s\S]{0,180}deleteWorkspaceLateralRouteHandoff\(handoffToken\)[\s\S]{0,180}navigate\(path\)/,
  "Sidebar clicks must await preparation and fall back to ordinary target-owned loading without stale state.",
);
assert.match(
  shellSource,
  /navigationIntentRef[\s\S]{0,500}view === activeView[\s\S]{0,500}navigationIntentRef\.current !== intentId/,
  "Only the latest non-active sidebar intent may commit an asynchronous navigation.",
);
assert.match(
  preparedNavigationSource,
  /prepareWorkspaceRoute\(view, persistence\)\.catch\(\(\) => undefined\)/,
  "Detail hover and focus preparation must never create an unhandled rejection.",
);
assert.match(
  preparedNavigationSource,
  /requestLeave\(\(\) => \{\s*void prepareWorkspaceRoute\(view, persistence\)\.then\(\s*finishPreparation,\s*\(\) => finishPreparation\(null\)/,
  "Detail preparation failures must hand ordinary target-owned loading to the destination.",
);
assert.equal(
  (preparedNavigationSource.match(/requestLeave\(\(\) =>/g) ?? []).length,
  2,
  "Detail routes must guard immediately and again after preparation.",
);
assert.match(
  preparedNavigationSource,
  /finishPreparation[\s\S]{0,300}requestLeave\(\(\) =>[\s\S]{0,500}createWorkspaceLateralRouteHandoff\(prepared\)[\s\S]{0,220}deleteWorkspaceLateralRouteHandoff\(handoffToken\)[\s\S]{0,120}navigate\(path\)/,
  "A detail route may allocate its token only inside the final guarded commit and must clean up before fallback.",
);
assert.match(
  preparedNavigationSource,
  /cancelPending[\s\S]{0,240}useEffect\([\s\S]{0,160}cancelPending\(\)[\s\S]*navigationIntentRef\.current !== intentId/,
  "Superseded and unmounted detail navigation intents must not commit late.",
);
for (const detailRouteSource of [
  resumeDetailRouteSource,
  templateDetailRouteSource,
]) {
  assert.match(
    detailRouteSource,
    /usePreparedWorkspaceNavigation\(\{ persistence, requestLeave \}\)/,
    "Both editable detail routes must share the guarded prepared-navigation owner.",
  );
}
for (const [routeSource, expectedMutationCommands] of [
  [resumeGalleryRouteSource, 4],
  [templateGalleryRouteSource, 5],
  [trashRouteSource, 5],
  [preferencesRouteSource, 4],
]) {
  assert.match(
    routeSource,
    /hasLoaded, setHasLoaded\] = useState\(Boolean\(preparedRouteData\)\)[\s\S]{0,180}isLoading, setIsLoading\] = useState\(!preparedRouteData\)/,
    "A prepared route must keep its first-frame content interactive during background calibration.",
  );
  assert.match(
    routeSource,
    /isPreparedCalibration\s*\? \{ notifyOnError: false \}\s*:\s*\{ notifyOnError: false, signal \}/,
    "Prepared calibration must reuse the uncancelled shared GET while direct loads remain abortable.",
  );
  assert.equal(
    (routeSource.match(
      /isPreparedCalibration &&\s*routeMutationEpochRef\.current !== mutationEpoch\s*\) \{\s*continue;/g,
    ) ?? []).length,
    3,
    "Prepared calibration must retry pre-GET, post-GET, and failed results after local mutation ownership changes.",
  );
  assert.match(
    routeSource,
    /if \(!isPreparedCalibration\) \{\s*setHasLoaded\(false\);\s*setHasLoadError\(true\);\s*\}/,
    "A failed background calibration must retain valid handoff content while direct loads keep retry UI.",
  );
  assert.equal(
    (routeSource.match(/markRouteMutation\(\);/g) ?? []).length,
    expectedMutationCommands,
    "Every current route-local mutation command must advance calibration ownership.",
  );
}
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
  templateGalleryRouteSource,
  /import\("@\/components\/workspace\/template-detail-workspace-page"\)/,
  "The template gallery must preload the independent detail route entry.",
);
assert.doesNotMatch(
  templateGalleryRouteSource,
  /import\("@\/components\/resume-builder"\)|import\("@\/components\/templates\/template-editor"\)/,
  "Template navigation must not warm the removed Builder-owned detail surface.",
);
assert.match(
  templateDetailRouteSource,
  /await persistence\.flush\(\)[\s\S]{0,500}fetchWorkspaceRouteData\("template-detail"/,
  "Template detail must flush queued preferences before its route-owned calibration read.",
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
  /priorPersistedFingerprint[\s\S]{0,500}createTemplateFingerprint\(currentTarget\)\s*===\s*priorPersistedFingerprint[\s\S]{0,500}item\.id === templateId \? currentTarget : item[\s\S]{0,300}hydratePersistedTemplate\(targetTemplate\)/,
  "Server calibration must update the persisted baseline without replacing a handoff draft edited in flight.",
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
assert.match(
  resumeGalleryRouteSource,
  /createResumeDetailRouteHandoff\([\s\S]{0,400}customTemplates:[\s\S]{0,120}defaultTemplateId:[\s\S]{0,120}theme[\s\S]{0,160}resumeOrdinal/,
  "Resume navigation must hand the selected document and gallery template snapshot to the cold detail route.",
);
assert.match(
  resumeGalleryRouteSource,
  /import\("@\/components\/workspace\/resume-detail-workspace-page"\)/,
  "The gallery must warm the independent resume-detail route entry.",
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
  /await persistence\.flush\(\)[\s\S]{0,700}fetchWorkspaceRouteData\("resume-detail"[\s\S]{0,500}fetchResumeApi\(resumeId[\s\S]{0,500}fetchResumeVersionsApi\(resumeId[\s\S]{0,500}Promise\.all/,
  "The resume handoff must not replace the parallel abortable server calibration.",
);
assert.match(
  resumeDetailLoaderSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "Resume detail must suppress StrictMode preflight and abort cleanup.",
);
assert.match(
  resumeDetailRouteSource,
  /hydrateIfUnchanged\(detail\.resume, initialFingerprint\)[\s\S]{0,400}hydratePersistedResume\([\s\S]{0,160}initialFingerprint \?\? undefined/,
  "Resume calibration must preserve a handoff draft while updating its persisted baseline.",
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
assert.match(
  resumeDetailSaveSource,
  /expectedPersistedFingerprint[\s\S]{0,240}persistedFingerprintRef\.current !== expectedPersistedFingerprint[\s\S]{0,120}persistenceEpochRef\.current !== 0[\s\S]{0,80}return false/,
  "A same-content checkpoint completed before calibration must prevent stale GET metadata from rolling back the persisted baseline.",
);
assert.ok(
  (resumeDetailSaveSource.match(/persistenceEpochRef\.current \+= 1/g) ?? [])
    .length >= 3,
  "Successful saves, restores, and version selections must advance calibration authority.",
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
  /while \(activeRequestRef\.current\)[\s\S]*submittedFingerprint[\s\S]*recentlySavedFingerprintsRef/,
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
vm.runInNewContext(compiledPersistence, {
  exports: persistenceModule.exports,
  module: persistenceModule,
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
releaseFirst();
await persistence.flush();
assert.deepEqual(order, ["first:start", "first:end", "second"]);
assert.deepEqual(persistence.getSnapshot(), second);

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

console.log("Workspace route ownership and preference persistence verified.");
