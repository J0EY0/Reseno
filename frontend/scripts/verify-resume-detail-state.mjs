import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import * as ts from "typescript";

const frontendRoot = new URL("../", import.meta.url);
const plain = (value) => JSON.parse(JSON.stringify(value));

async function loadModule(path, imports = {}, globals = {}) {
  const source = await readFile(new URL(path, frontendRoot), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, {
    module,
    exports: module.exports,
    AbortController,
    DOMException,
    console: { error() {}, warn() {} },
    require(specifier) {
      assert.ok(Object.hasOwn(imports, specifier), `Unexpected dependency: ${specifier}`);
      return imports[specifier];
    },
    ...globals,
  });
  return module.exports;
}

function createHookRunner() {
  const cells = [];
  let cursor = 0;
  let dirty = false;
  let renderHook;
  let current;
  let effects = [];
  const sameDependencies = (left, right) => left && right && left.length === right.length && left.every((value, index) => Object.is(value, right[index]));
  function useMemo(factory, dependencies) {
    const index = cursor++;
    if (!cells[index] || !sameDependencies(cells[index].dependencies, dependencies)) {
      cells[index] = { dependencies, value: factory() };
    }
    return cells[index].value;
  }
  function effect(callback, dependencies) {
    const index = cursor++;
    const previous = cells[index];
    if (!previous || !sameDependencies(previous.dependencies, dependencies)) {
      effects.push({ callback, index, previous });
      cells[index] = { ...previous, dependencies };
    }
  }
  const react = {
    useCallback: (callback, dependencies) => useMemo(() => callback, dependencies),
    useDeferredValue: (value) => value,
    useEffect: effect,
    useLayoutEffect: effect,
    useMemo,
    useRef(value) {
      const index = cursor++;
      cells[index] ??= { current: value };
      return cells[index];
    },
    useState(initial) {
      const index = cursor++;
      cells[index] ??= { value: typeof initial === "function" ? initial() : initial };
      cells[index].set ??= (next) => {
        const value = typeof next === "function" ? next(cells[index].value) : next;
        if (!Object.is(cells[index].value, value)) {
          cells[index].value = value;
          dirty = true;
        }
      };
      return [cells[index].value, cells[index].set];
    },
  };
  const runner = {
    react,
    window: { setTimeout: () => 0, clearTimeout() {} },
    mount(hook) { renderHook = hook; return runner.render(); },
    render() { dirty = true; return runner.flush(); },
    flush() {
      let commits = 0;
      while (dirty) {
        assert.ok(++commits < 30, "The hook must settle without a render/effect loop.");
        dirty = false;
        cursor = 0;
        effects = [];
        current = renderHook();
        for (const pending of effects) {
          pending.previous?.cleanup?.();
          cells[pending.index].cleanup = pending.callback();
        }
      }
      return current;
    },
    unmount() { for (const cell of cells) cell.cleanup?.(); },
    get current() { return current; },
  };
  return runner;
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, reject, resolve };
}

function resumeItem(id = "resume-a") {
  return {
    id,
    title: "Original title",
    updatedAt: "2026-09-01T00:00:00.000Z",
    documentLocale: "en",
    jobBrief: "Original job brief",
    template: "minimal",
    templateSettings: null,
    typography: { fontFamily: "inter", fontSize: 16 },
    resume: {
      schemaVersion: 2,
      basic: { name: "Ada", headline: "Engineer" },
      sections: [],
    },
  };
}
const detail = (resume, versionId = "version-a") => ({ resume, versionId, savedAt: resume.updatedAt });
const tracking = await loadModule("src/lib/workspace-change-tracking.ts");
const messages = { loadError: "Request failed" };
const toast = { dismiss() {}, error() {} };

async function sessionFixture(initial = resumeItem()) {
  const runner = createHookRunner();
  let draft = null;
  let resetCount = 0;
  const { useResumeDetailSession } = await loadModule("src/components/workspace/use-resume-detail-session.ts", {
    react: runner.react,
    "@/hooks/use-resume-agent-draft": {
      useResumeAgentDraft: () => ({
        agentDraft: draft,
        review: null,
        resetAgentDraft() { draft = null; resetCount += 1; },
      }),
    },
    "@/lib/resume": { createEmptyResume: () => resumeItem().resume },
    "@/lib/workspace-change-tracking": tracking,
  });
  runner.mount(() => useResumeDetailSession({ initialResume: initial, messages, onResolveDraftReview: async () => null }));
  return { runner, setDraft(value) { draft = value; runner.render(); }, get resetCount() { return resetCount; } };
}

{
  const { runner, setDraft } = await sessionFixture();
  const getSnapshot = runner.current.getSnapshot;
  const changedResume = { ...runner.current.resume, basic: { name: "Grace", headline: "Engineer" } };
  runner.current.setResume(changedResume);
  runner.current.setJobBrief("New job brief");
  runner.current.setTypography({ fontFamily: "noto-sans-sc", fontSize: 18 });
  runner.current.setTemplate("modern");
  runner.current.setTemplateSettings({ pagePaddingX: 24 });
  runner.current.setResumeItem((current) => ({ ...current, title: "Edited title" }));
  runner.flush();
  assert.equal(runner.current.getSnapshot, getSnapshot, "Async save and discard callers must retain a stable snapshot getter.");
  assert.deepEqual(plain(getSnapshot("request-time")), { ...plain(runner.current.liveResume), updatedAt: "request-time" },
    "Visible live content and save snapshots must include the same edited fields.");
  assert.equal(runner.current.liveFingerprint, tracking.createResumeFingerprint(runner.current.liveResume));
  const fingerprint = runner.current.liveFingerprint;
  setDraft({ resume: { ...changedResume, basic: { name: "Unconfirmed draft", headline: "Director" } }, diffs: [] });
  assert.equal(runner.current.previewResume.basic.name, "Unconfirmed draft");
  assert.equal(getSnapshot("later").resume.basic.name, "Grace", "Unconfirmed Agent changes must remain outside the formal save snapshot.");
  assert.equal(runner.current.liveFingerprint, fingerprint, "A preview-only Agent draft must not mark formal content dirty.");
  runner.unmount();
}

{
  const fixture = await sessionFixture();
  const { runner } = fixture;
  const getter = runner.current.getSnapshot;
  fixture.setDraft({ resume: resumeItem().resume, diffs: [] });
  const nextDocument = { ...resumeItem("resume-b"), title: "Next document", jobBrief: "Next job" };
  runner.current.hydrate(nextDocument);
  runner.flush();
  assert.equal(fixture.resetCount, 1, "Replacing the document must clear the whole Agent draft once.");
  assert.deepEqual(plain(getter("next-time")), { ...nextDocument, updatedAt: "next-time" },
    "The stable getter must follow a hydrated document rather than retain the old document.");
  assert.equal(runner.current.previewResume, nextDocument.resume);
  runner.unmount();
}

{
  const { runner } = await sessionFixture();
  const submitted = runner.current.getSnapshot("submitted");
  runner.current.setResume({ ...submitted.resume, basic: { name: "New typing", headline: "Engineer" } });
  runner.current.setResumeItem((current) => ({ ...current, title: "New title after submit" }));
  runner.flush();
  runner.current.adoptSavedResume({ ...submitted, title: "Server-normalized title", updatedAt: "saved" }, submitted);
  runner.flush();
  assert.equal(runner.current.liveResume.resume.basic.name, "New typing", "A save receipt must not replace text entered after submission.");
  assert.equal(runner.current.liveResume.title, "New title after submit", "A save receipt must preserve a newer local title.");
  assert.equal(runner.current.liveResume.updatedAt, "saved");
  const unchangedTitle = runner.current.getSnapshot("submitted-again");
  runner.current.adoptSavedResume({ ...unchangedTitle, title: "Normalized unchanged title" }, unchangedTitle);
  runner.flush();
  assert.equal(runner.current.liveResume.title, "Normalized unchanged title", "An untouched submitted title may adopt server normalization.");
  runner.unmount();
}

async function saveFixture({ initial = resumeItem(), api = {} } = {}) {
  const runner = createHookRunner();
  let liveResume = initial;
  const checkpoint = { savedAt: initial.updatedAt, versionId: "version-a" };
  const requests = [];
  const { useResumeDetailSave } = await loadModule("src/components/workspace/use-resume-detail-save.ts", {
    react: runner.react,
    sonner: { toast },
    "@/lib/workspace-change-tracking": tracking,
    "@/lib/agent-session-run-client": { resolveAgentDraftDecision: () => assert.fail("Unexpected Agent decision.") },
    "@/lib/workspace-api": {
      async saveResumeApi(id, payload, mode) {
        requests.push({ id, payload: plain(payload), mode });
        return api.save?.(id, payload, mode) ?? detail({ ...liveResume, ...payload, updatedAt: `saved-${requests.length}` }, `version-${requests.length + 1}`);
      },
      fetchResumeVersionsApi: async () => ({ versions: [checkpoint] }),
      fetchResumeVersionApi: (...args) => api.version(...args),
    },
  }, { window: runner.window });
  const getSnapshot = (updatedAt) => liveResume ? { ...liveResume, updatedAt } : null;
  runner.mount(() => useResumeDetailSave({
    getSnapshot,
    initialCheckpoint: checkpoint,
    initialResume: initial,
    isLoading: false,
    liveFingerprint: tracking.createResumeFingerprint(liveResume),
    liveResume,
    messages,
    onAdoptSavedResume() {},
    onHydrateResume(value) { liveResume = value; },
    resumeId: initial.id,
  }));
  return { runner, requests, edit(value) { liveResume = value; runner.render(); }, get live() { return liveResume; } };
}

{
  const gate = deferred();
  const { runner, edit, requests } = await saveFixture({ api: { save: () => gate.promise } });
  const submitted = { ...resumeItem(), title: "Submitted title" };
  edit(submitted);
  const saving = runner.current.save();
  edit({ ...submitted, title: "Typed while saving" });
  gate.resolve(detail({ ...submitted, updatedAt: "saved" }, "version-b"));
  await saving;
  runner.flush();
  assert.equal(requests[0].payload.title, "Submitted title");
  assert.equal(runner.current.hasUnsavedChanges(), true, "A successful older save must not clear newer local edits.");
  assert.equal(runner.current.changeCount, 1, "The confirmed baseline must expose only the newer title as unsaved.");
  assert.equal(runner.current.activeVersionId, "version-b");
  runner.unmount();
}

{
  const fixture = await saveFixture();
  const { runner } = fixture;
  fixture.edit({ ...resumeItem(), title: "Autosaved title" });
  await runner.current.save("autosave");
  runner.flush();
  assert.equal(runner.current.hasUnsavedChanges(), false);
  assert.equal(runner.current.changeCount, 0);
  assert.equal(runner.current.requiresCheckpointPromotion(), true);
  await runner.current.save("checkpoint");
  runner.flush();
  assert.deepEqual(fixture.requests.map(({ mode }) => mode), ["autosave", "checkpoint"], "A clean autosave still needs a formal checkpoint before leaving.");
  assert.equal(runner.current.requiresCheckpointPromotion(), false);
  runner.unmount();
}

{
  const selected = { ...resumeItem(), title: "Historical title", updatedAt: "historical-time" };
  const fixture = await saveFixture({ api: { version: async () => detail(selected, "version-old") } });
  const { runner } = fixture;
  const current = { ...resumeItem(), title: "Loaded current title", updatedAt: "current-time" };
  fixture.edit(current);
  runner.current.hydratePersistedResume(detail(current, "version-current"), [
    { versionId: "version-current", savedAt: current.updatedAt },
    { versionId: "version-old", savedAt: selected.updatedAt },
  ]);
  runner.flush();
  assert.equal(runner.current.hasUnsavedChanges(), false);
  assert.equal(runner.current.changeCount, 0);
  await runner.current.selectVersion("version-old");
  runner.flush();
  assert.equal(fixture.live.title, "Historical title");
  assert.equal(runner.current.activeVersionId, "version-old");
  assert.equal(runner.current.lastSavedAt, "historical-time");
  assert.equal(runner.current.hasUnsavedChanges(), false);
  assert.equal(runner.current.changeCount, 0, "Selecting history must move both synchronous and rendered save baselines.");
  fixture.edit({ ...selected, title: "Autosaved historical edit" });
  await runner.current.save("autosave");
  runner.flush();
  assert.equal(runner.current.requiresCheckpointPromotion(), true);
  fixture.edit({ ...selected, title: "Unsaved historical edit" });
  await runner.current.discard();
  runner.flush();
  assert.equal(fixture.live.title, "Autosaved historical edit");
  assert.deepEqual(fixture.requests.map(({ mode }) => mode), ["autosave", "checkpoint"]);
  assert.equal(runner.current.hasUnsavedChanges(), false);
  assert.equal(runner.current.changeCount, 0);
  assert.equal(runner.current.lastSavedAt, "saved-2");
  assert.equal(runner.current.activeVersionId, "version-3");
  assert.equal(runner.current.requiresCheckpointPromotion(), false,
    "Discarding after autosave must adopt the restoration checkpoint and clear promotion state.");
  runner.unmount();
}

console.log("Resume detail snapshots and save baselines verified.");
