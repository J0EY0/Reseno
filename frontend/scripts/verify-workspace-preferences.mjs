import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { evaluateTypeScript } from "./typescript-module.mjs";

const frontendRoot = new URL("../", import.meta.url);
const [source, agentSource, routePreparationSource] = await Promise.all([
  readFile(new URL("src/lib/workspace-preferences-persistence.ts", frontendRoot), "utf8"),
  readFile(new URL("src/lib/agent-settings.ts", frontendRoot), "utf8"),
  readFile(new URL("src/components/workspace/workspace-route-preparation.ts", frontendRoot), "utf8"),
]);
const cachedThemes = [];

function compileModule(sourceText, dependencies = {}) {
  return evaluateTypeScript(sourceText, {
    globals: { DOMException },
    imports: dependencies,
  });
}

const { createWorkspacePreferencesPersistence } = compileModule(source, {
  "@/lib/agent-settings": compileModule(agentSource),
  "@/lib/workspace-theme": {
    saveWorkspaceThemePreference(theme) {
      cachedThemes.push(theme);
    },
  },
});
const plain = (value) => JSON.parse(JSON.stringify(value));
const tick = () => new Promise((resolve) => setImmediate(resolve));
const settings = (id = "model-a") => ({
  defaultModelConfigId: id,
  responseLanguage: "follow",
  behaviorMode: "balanced",
  confirmationMode: "always",
});
const initial = (agentSettings = settings()) => ({
  locale: "en",
  theme: "light",
  agentSettings,
});
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}
function fixture({ snapshot = initial(), save = async (patch) => patch } = {}) {
  const changes = [];
  const errors = [];
  const requests = [];
  const persistence = createWorkspacePreferencesPersistence(snapshot, {
    onChange: (value) => changes.push(plain(value)),
    onError: (error) => errors.push(error),
    save(patch, locale) {
      requests.push({ locale, patch: plain(patch) });
      return save(patch, locale);
    },
  });
  return { changes, errors, persistence, requests };
}
const prepareRead = (persistence) => persistence.prepareRead(new AbortController().signal);
function routeReader(fetchWorkspaceRouteData) {
  return compileModule(routePreparationSource, {
    "@/lib/api-client": { isAbortError: (error) => error?.name === "AbortError" },
    "@/lib/template-presets": {},
    "@/lib/workspace-api": { fetchWorkspaceRouteData },
    "@/components/preview/document-canvas-loader": {},
    "@/components/workspace/workspace-route-loaders": {},
  }).fetchWorkspacePageData;
}

{
  const { persistence, requests } = fixture({ snapshot: initial(null) });
  const readTheme = await prepareRead(persistence);
  readTheme({ theme: "dark" });
  assert.deepEqual(plain(persistence.getSnapshot()), { ...initial(null), theme: "dark" });
  const readAgent = await prepareRead(persistence);
  readAgent({ agentSettings: settings("not-loaded-yet") });
  assert.equal(persistence.getSnapshot().agentSettings.defaultModelConfigId, "not-loaded-yet",
    "An omitted model catalog must not be interpreted as an empty catalog.");
  assert.equal(persistence.getSnapshot().theme, "dark", "Partial route data must preserve unrelated preferences.");
  assert.equal(requests.length, 0, "Reading preferences must not issue a write.");
}

{
  const gate = deferred();
  const { persistence, requests } = fixture({ snapshot: initial(null), save: () => gate.promise });
  const cachedBefore = [...cachedThemes];
  persistence.change({ theme: "dark" });
  assert.equal(persistence.getSnapshot().theme, "dark", "Theme changes must be visible before saving completes.");
  await tick();
  assert.deepEqual(requests, [{ locale: "en", patch: { theme: "dark" } }],
    "Changing the theme before Agent preferences load must save only the changed field.");
  assert.deepEqual(cachedThemes, cachedBefore, "In-flight preferences must not replace the first-paint cache.");
  gate.resolve({ theme: "dark", agentSettings: settings("server-default") });
  await persistence.flush();
  assert.equal(persistence.getSnapshot().agentSettings.defaultModelConfigId, "server-default");
  assert.equal(cachedThemes.at(-1), "dark");
}

{
  const gate = deferred();
  const { persistence, requests } = fixture({
    save: (patch) => patch.theme ? gate.promise : Promise.resolve(patch),
  });
  persistence.change({ theme: "dark" });
  persistence.change({ locale: "zh" });
  persistence.change({ agentSettings: { ...settings(), behaviorMode: "strict" } });
  const expected = { locale: "zh", theme: "dark", agentSettings: { ...settings(), behaviorMode: "strict" } };
  assert.deepEqual(plain(persistence.getSnapshot()), expected, "All pending changes must project into the current UI.");
  await tick();
  assert.equal(requests.length, 1, "Preference requests must be serialized.");
  gate.resolve({ ...initial(), theme: "dark" });
  await persistence.flush();
  assert.deepEqual(requests.map(({ patch }) => patch), [
    { theme: "dark" }, { locale: "zh" }, { agentSettings: expected.agentSettings },
  ]);
  assert.deepEqual(plain(persistence.getSnapshot()), expected,
    "A full response to an older save must not erase later queued changes.");
  assert.equal(requests.at(-1).locale, "zh", "Subsequent writes must use the committed locale.");
}

{
  const gate = deferred();
  const failed = new Error("theme save failed");
  const { persistence, errors } = fixture({ save: (patch) => patch.theme ? gate.promise : Promise.resolve(patch) });
  persistence.change({ theme: "dark" });
  persistence.change({ agentSettings: settings("model-b") });
  await tick();
  gate.reject(failed);
  await persistence.flush();
  assert.deepEqual(plain(persistence.getSnapshot()), initial(settings("model-b")),
    "A failed theme patch must roll back even if a later Agent patch succeeds.");
  assert.deepEqual(errors, [failed]);
}

{
  const { persistence, errors } = fixture({ save: async () => { throw new Error("save failed"); } });
  persistence.change({ theme: "dark" });
  persistence.change({ theme: "system" });
  await persistence.flush();
  assert.equal(persistence.getSnapshot().theme, "light",
    "Several failed changes to one field must return to its confirmed value.");
  assert.equal(errors.length, 2);
}

{
  const { persistence } = fixture({ snapshot: initial(null) });
  const applyRead = await prepareRead(persistence);
  persistence.change({ theme: "dark" });
  await persistence.flush();
  applyRead({ theme: "light", agentSettings: settings("loaded-during-save") });
  assert.deepEqual(plain(persistence.getSnapshot()), {
    ...initial(settings("loaded-during-save")), theme: "dark",
  }, "A read crossing a local write must retain the newer field and still hydrate untouched fields.");
}

{
  const gate = deferred();
  const { persistence } = fixture({ save: () => gate.promise });
  persistence.change({ theme: "dark" });
  let readReady = false;
  const readRequest = prepareRead(persistence).then((read) => { readReady = true; return read; });
  await tick();
  assert.equal(readReady, false, "Fresh route reads must wait until writes and rollback finish.");
  gate.reject(new Error("save failed"));
  const applyRead = await readRequest;
  assert.equal(persistence.getSnapshot().theme, "light");
  applyRead({ theme: "system" });
  assert.equal(persistence.getSnapshot().theme, "system");
}

{
  const first = deferred();
  const second = deferred();
  const { persistence } = fixture({ save: (patch) => patch.theme ? first.promise : second.promise });
  persistence.change({ theme: "dark" });
  let flushed = false;
  const flushing = persistence.flush().then(() => { flushed = true; });
  persistence.change({ locale: "zh" });
  first.resolve({ theme: "dark" });
  await tick();
  assert.equal(flushed, false, "A navigation flush must also wait for writes added while it was waiting.");
  second.resolve({ locale: "zh" });
  await flushing;
  assert.equal(persistence.getSnapshot().locale, "zh");
}

{
  const gate = deferred();
  const { persistence } = fixture({ save: () => gate.promise });
  const preparingRead = prepareRead(persistence);
  queueMicrotask(() => persistence.change({ theme: "dark" }));
  const applyRead = await preparingRead;
  applyRead({ theme: "system", agentSettings: settings("model-b") });
  gate.reject(new Error("theme save failed"));
  await persistence.flush();
  assert.deepEqual(plain(persistence.getSnapshot()), initial(settings("model-b")),
    "A write queued between flush and read capture must prevent that field from changing the rollback baseline.");
}

{
  const { persistence } = fixture();
  const oldRead = await prepareRead(persistence);
  const newRead = await prepareRead(persistence);
  newRead({ theme: "dark", agentSettings: settings("model-b") });
  oldRead({ theme: "light", agentSettings: settings("model-a") });
  assert.deepEqual(plain(persistence.getSnapshot()), { ...initial(settings("model-b")), theme: "dark" },
    "A slower older route response must not overwrite a newer response.");
  const controller = new AbortController();
  const cancelledRead = await persistence.prepareRead(controller.signal);
  controller.abort();
  cancelledRead({ theme: "system" });
  assert.equal(persistence.getSnapshot().theme, "dark", "Cancelled route responses must not hydrate preferences.");
}

{
  const gate = deferred();
  const { persistence, changes, errors, requests } = fixture({ save: () => gate.promise });
  const readBeforeLogout = await prepareRead(persistence);
  persistence.change({ theme: "dark" });
  persistence.change({ locale: "zh" });
  await tick();
  persistence.reset(initial(null));
  const changeCount = changes.length;
  const cacheBefore = [...cachedThemes];
  gate.resolve({ locale: "zh", theme: "dark", agentSettings: settings("previous-session") });
  await persistence.flush();
  await tick();
  readBeforeLogout({ theme: "system", agentSettings: settings("previous-session") });
  assert.deepEqual(plain(persistence.getSnapshot()), initial(null), "Logout must reset in-memory preferences.");
  assert.equal(requests.length, 1, "Logout must discard writes that have not started.");
  assert.equal(changes.length, changeCount, "Old session completions must not update the next session.");
  assert.deepEqual(cachedThemes, cacheBefore, "An old session response must not change the theme cache.");
  assert.equal(errors.length, 0);
}

{
  const gate = deferred();
  const { persistence, errors } = fixture({ save: () => gate.promise });
  persistence.change({ theme: "dark" });
  await tick();
  persistence.reset(initial(null));
  gate.reject(new Error("old session failure"));
  await persistence.flush();
  await tick();
  assert.equal(errors.length, 0, "An obsolete session failure must not surface in a new session.");
}

{
  const gate = deferred();
  const { persistence } = fixture({ save: () => gate.promise });
  persistence.change({ theme: "dark" });
  const waitingRead = prepareRead(persistence);
  await tick();
  persistence.reset(initial(null));
  gate.resolve({ theme: "dark" });
  const applyRead = await waitingRead;
  applyRead({ theme: "dark", agentSettings: settings("previous-session") });
  assert.deepEqual(plain(persistence.getSnapshot()), initial(null),
    "A read waiting for an old session's saves must remain invalid after logout.");
}

{
  const { persistence, requests } = fixture();
  persistence.reconcileModels([{ id: "model-a" }, { id: "model-b" }]);
  await persistence.flush();
  assert.equal(requests.length, 0, "An unchanged default model must not cause a redundant save.");
  persistence.reconcileModels([{ id: "model-b" }]);
  assert.equal(persistence.getSnapshot().agentSettings.defaultModelConfigId, "model-b");
  await persistence.flush();
  assert.deepEqual(requests.map(({ patch }) => patch), [{ agentSettings: settings("model-b") }],
    "Removing the selected model must persist the remaining model as default.");
  persistence.reconcileModels([]);
  await persistence.flush();
  assert.equal(persistence.getSnapshot().agentSettings.defaultModelConfigId, "",
    "An explicitly empty model catalog must clear the default selection.");
}

{
  const { persistence } = fixture({ save: async () => { throw new Error("default save failed"); } });
  persistence.reconcileModels([{ id: "model-b" }]);
  await persistence.flush();
  assert.equal(persistence.getSnapshot().agentSettings.defaultModelConfigId, "model-b",
    "Rolling back a failed default-model save must not resurrect a deleted model.");
}

{
  const gate = deferred();
  const { persistence } = fixture({ save: (patch) => patch.agentSettings.defaultModelConfigId === "model-b" ? gate.promise : Promise.resolve(patch) });
  persistence.reconcileModels([{ id: "model-a" }, { id: "model-b" }]);
  persistence.change({ agentSettings: settings("model-b") });
  await tick();
  persistence.reconcileModels([{ id: "model-a" }]);
  gate.resolve({ agentSettings: settings("model-b") });
  await persistence.flush();
  assert.equal(persistence.getSnapshot().agentSettings.defaultModelConfigId, "model-a",
    "An in-flight preference response must not restore a model deleted while it was saving.");
}

{
  const { persistence } = fixture();
  const applyOldRead = await prepareRead(persistence);
  persistence.reconcileModels([{ id: "model-a" }]);
  applyOldRead({ agentSettings: settings("model-b"), modelConfigs: [{ id: "model-a" }, { id: "model-b" }] });
  assert.equal(persistence.getSnapshot().agentSettings.defaultModelConfigId, "model-a",
    "A read started before model deletion must not restore the deleted catalog or default.");
}

{
  const { persistence, requests } = fixture();
  persistence.synchronizeLocale("zh");
  assert.equal(persistence.getSnapshot().locale, "zh",
    "A saved locale restored by App must update preference transaction metadata.");
  await persistence.flush();
  assert.equal(requests.length, 0, "External locale restoration must not issue a preference write.");
  persistence.change({ theme: "dark" });
  await persistence.flush();
  assert.deepEqual(requests, [{ locale: "zh", patch: { theme: "dark" } }],
    "The first preference change after locale restoration must use the restored locale.");
}

{
  const gate = deferred();
  const { persistence } = fixture({ save: () => gate.promise });
  persistence.change({ locale: "zh" });
  await tick();
  persistence.synchronizeLocale("zh");
  gate.reject(new Error("locale save failed"));
  await persistence.flush();
  assert.equal(persistence.getSnapshot().locale, "en",
    "Synchronizing an explicit in-flight locale choice must not replace its rollback baseline.");
}

{
  const gate = deferred();
  const { persistence, requests } = fixture({
    save: (patch) => patch.theme ? gate.promise : Promise.resolve(patch),
  });
  persistence.change({ theme: "dark" });
  await tick();
  persistence.synchronizeLocale("zh");
  gate.resolve({ ...initial(), theme: "dark" });
  await persistence.flush();
  assert.equal(persistence.getSnapshot().locale, "zh",
    "An older theme response must not revert a locale restored while it was saving.");
  persistence.change({ agentSettings: settings("model-b") });
  await persistence.flush();
  assert.equal(requests.at(-1).locale, "zh",
    "Later writes must retain the external locale after an older save completes.");
}

{
  const gate = deferred();
  const { persistence } = fixture({ snapshot: initial(null), save: () => gate.promise });
  const controller = new AbortController();
  const reads = [];
  const fetchPageData = routeReader(async (kind, options) => {
    reads.push({ kind, options });
    return { kind, data: { theme: "dark", agentSettings: settings("model-b") } };
  });
  persistence.change({ theme: "dark" });
  const loading = fetchPageData("settings", persistence, { signal: controller.signal, notifyOnError: false });
  await tick();
  assert.equal(reads.length, 0, "Fresh page transport must wait for the preference save queue.");
  gate.resolve({ theme: "dark" });
  const result = await loading;
  assert.equal(reads[0].options.signal, controller.signal);
  assert.equal(reads[0].options.notifyOnError, false);
  assert.equal(result.kind, "settings");
  assert.equal(persistence.getSnapshot().agentSettings.defaultModelConfigId, "model-b",
    "The first usable page response must already have hydrated shared preferences.");
}

{
  const gate = deferred();
  const { persistence } = fixture({ save: () => gate.promise });
  const controller = new AbortController();
  const fetchPageData = routeReader(() => assert.fail("Cancelled navigation must not start page transport."));
  persistence.change({ theme: "dark" });
  const loading = fetchPageData("settings", persistence, { signal: controller.signal });
  controller.abort();
  gate.resolve({ theme: "dark" });
  await assert.rejects(loading, { name: "AbortError" });
}

console.log("Workspace preference transactions, fresh reads, session resets, and model reconciliation verified.");
